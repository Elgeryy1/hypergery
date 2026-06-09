# POST_NIGHT_AUDIT — auditoría de la noche autónoma (M1–M13)

> Rama: `audit/post-night-bugs` (sobre `feat/v2.0-research`).
> Baseline al empezar: compileall OK, pytest = 837 passed, 9 skipped.
> Al cerrar: compileall OK, pytest = **847 passed, 9 skipped** (10 tests de
> regresión nuevos en `tests/test_post_night_audit.py`). Log completo:
> `docs/audit/pytest_post_night.txt`.

## Resumen ejecutivo

- **8 hallazgos**: 3 nuevos arreglados (1 ALTO, 2 MEDIOS), 2 antiguos cerrados
  (0013, 0021), 3 en cola para Gerard (1 ALTO de diseño, 1 MEDIO, 1 BAJO).
- Los bugs antiguos 0014/0019/0020/0022/0023 siguen abiertos sin cambios (no
  empeoraron; ninguno era objetivo de la noche).
- **Veredicto de merge: SÍ, mergear `audit/post-night-bugs`** (no
  `feat/v2.0-research` a secas: esta rama incluye los arreglos de seguridad).
  El único ALTO restante (HG-BUG-0028) es una decisión de diseño documentada
  que requiere una acción manual peligrosa para materializarse; no bloquea.

## Tabla de hallazgos

| ID | Severidad | Módulo | Estado |
|----|-----------|--------|--------|
| HG-BUG-0025 | **ALTO** | v1/gpu_passthrough.py | **ARREGLADO** esta sesión |
| HG-BUG-0026 | MEDIO | v1/auth.py | **ARREGLADO** esta sesión |
| HG-BUG-0027 | MEDIO | v1/api.py | **ARREGLADO** esta sesión |
| HG-BUG-0021 | BAJO | agent.py | **CERRADO** esta sesión |
| HG-BUG-0013 | BAJO | migration.py | **CERRADO** esta sesión |
| HG-BUG-0028 | **ALTO** | v1/live_migration.py | EN COLA (diseño) |
| HG-BUG-0029 | MEDIO | v1/api.py + registry/server.py | EN COLA |
| HG-BUG-0030 | BAJO | v1/api.py | EN COLA (deuda) |
| HG-BUG-0014/0019/0020/0022/0023 | BAJO/INFO | varios | Abiertos, sin cambios |

## Hallazgos nuevos (detalle)

### HG-BUG-0025 — `v1 gpu bind` se saltaba la parada dura de la GPU del escritorio — ALTO · ARREGLADO

- **Módulo:** `v1/gpu_passthrough.py` (VfioBinder.bind_to_vfio), `v1/cli_v1.py:362`.
- **Descripción:** el preflight con la regla "nunca la GPU del escritorio sin
  segunda GPU" solo corría en `attach_gpu_to_vm`. El camino directo
  `hypergery-cli v1 gpu bind 0000:00:02.0 --confirm` llamaba a
  `VfioBinder.bind_to_vfio` sin ninguna comprobación → con root habría
  desvinculado la iGPU i915 y dejado el host sin pantalla.
- **Reproducción mínima (NO ejecutada en real):** `v1 gpu bind <addr-iGPU> --confirm` en un host de una sola GPU.
- **Fix:** nueva `ensure_safe_to_detach(address, sysfs_root)` que corre
  SIEMPRE dentro de `bind_to_vfio` (sin flag de bypass): si el dispositivo es
  la única GPU de display (boot_vga o driver i915/amdgpu/nouveau/nvidia/radeon),
  se rechaza. Dispositivos no-GPU (p. ej. una NIC para §5.8) no se restringen.
- **Tests:** `GpuBindHardStopTests` (3) — el bind de la iGPU única falla con
  confirm=True y el driver queda intacto; la GPU secundaria y una NIC siguen
  funcionando.

### HG-BUG-0026 — Tokens de usuario del API v1 sin comparación en tiempo constante — MEDIO · ARREGLADO

- **Módulo:** `v1/auth.py:93` (`ApiTokenStore.resolve`).
- **Descripción:** el token de propietario usaba `hmac.compare_digest`, pero
  los tokens por usuario se resolvían con un lookup de dict
  (`self._load().get(token)`), inconsistente con la política declarada en M6
  (riesgo práctico bajo — el hash de dict no es un comparador byte a byte
  clásico — pero la promesa "comparación constante" era falsa).
- **Fix:** `resolve` recorre el almacén completo comparando cada token con
  `hmac.compare_digest` (sin cortar en el primer match para no filtrar la
  posición).
- **Tests:** `ConstantTimeTokenTests` (roundtrip + guard estático de que el
  código usa compare_digest y no `.get(token)`).

### HG-BUG-0027 — API v1 sin rate limit de fallos de autenticación — MEDIO · ARREGLADO

- **Módulo:** `v1/api.py` (`ApiRequestHandler._authenticate`).
- **Descripción:** M6 añadió el anti fuerza bruta al Hub pero NO al API v1 —
  precisamente la superficie que consumirá un móvil expuesto en la VPN
  (companion M8) y el long-poll (M9). Un atacante en la VPN podía probar
  tokens sin límite.
- **Fix:** `ApiServer` instancia el mismo `AuthRateLimiter` del Hub (10
  fallos/60s por IP → 429); éxito limpia el contador.
- **Tests:** `V1ApiRateLimitTests` (3 fallos → 429, incluso con token bueno
  hasta expirar la ventana).

### HG-BUG-0028 — Sin journal persistente de migración: origen arrancable tras el switchover — ALTO · EN COLA (diseño)

- **Módulo:** `v1/live_migration.py` / `v1/migration_engine.py`.
- **Traza del camino de fallo (§2.3):** si el proceso muere entre el éxito de
  `virsh migrate` (switchover) y la fase `activate`, el estado queda: destino
  RUNNING + **origen DEFINIDO y apagado** (libvirt para el QEMU de origen en
  el switchover, así que NO hay doble-activa automática). PERO el origen
  sigue siendo arrancable a mano; con shared storage, un `virsh start` del
  origen mientras el destino corre = **corrupción de disco**. El invariante
  "nunca activa en dos hosts" vive solo en memoria (engine + chequeo de
  activate); no hay lock/journal persistente que sobreviva al proceso.
- **`virDomainAbortJob` post-switchover:** benigno — `domjobabort` con
  check=False devuelve error ignorado, y el rollback tiene la guarda "nunca
  destruir un destino promovido" (testeada).
- **Rollback inverso:** verificado — la fase fallida se deshace primero y las
  completadas en orden inverso (tests del motor).
- **Propuesta (decisión de Gerard):** journal persistente en el state dir
  (`migrations-journal.json`: vm, target_uri, fase, timestamp) escrito al
  entrar en switchover y limpiado en activate; `backend.start_vm` y el
  preflight de migración consultan el journal y bloquean/avisan si la VM
  tiene una migración sin confirmar. ~1 sesión de trabajo.

### HG-BUG-0029 — Long-poll puede agotar los hilos del ThreadingHTTPServer — MEDIO · EN COLA

- **Módulo:** `v1/api.py` (GET /progress/<id>), aplica en menor medida a todo
  el Hub (es inherente a `http.server`).
- **Descripción:** cada long-poll bloquea un hilo hasta 60s; N conexiones
  concurrentes = N hilos sin techo. Dentro de una VPN autenticada y con el
  rate limit de 0027 el riesgo real es bajo, pero un cliente legítimo con un
  bug de reintentos podría degradar el API.
- **Propuesta:** semáforo de long-polls concurrentes (p. ej. 32) devolviendo
  503 al excederse, o migrar el API a un servidor con pool acotado.

### HG-BUG-0030 — `v1/api.py` cruza las 500 líneas (551) — BAJO · EN COLA (deuda)

- M8/M9 añadieron companion + dashboard + progress en el mismo fichero.
  Mismo patrón de crecimiento que TD-1/TD-2: extraer handlers a
  `v1/api_handlers/` antes de que siga creciendo (la app Android traerá más
  endpoints).

## Bugs antiguos cerrados esta sesión

### HG-BUG-0021 — Agente tragaba excepciones — CERRADO

- 5 `except Exception: pass` totalmente mudos en `agent.py` (heartbeat
  report, post-import report, post-power report, migration status update) +
  2 silencios nuevos introducidos en M8 (telemetría e inventario) y el probe
  de libvirt. Todos ahora hacen `logging.warning` con contexto, manteniendo
  el comportamiento (el heartbeat nunca muere). Guard de regresión estático:
  `AgentSilentExceptionTests` (cubre agent.py Y los módulos v1 nuevos).

### HG-BUG-0013 — Import sin preflight de espacio — CERRADO

- `import_vm_package` ahora suma los `package_size_bytes` del manifest y
  exige espacio libre + 256 MiB de margen en `backend.vms_dir` ANTES de crear
  nada (el error llega antes de tocar el destino). Tests:
  `ImportSpacePreflightTests` (falla pronto sin espacio y no deja rastro;
  con espacio importa igual que antes).

## Bugs antiguos que siguen abiertos (sin cambios esta noche)

- **HG-BUG-0014** (BAJO, ui_qt/console.py): `_stop_connect_worker` puede
  congelar la UI hasta 10s al cerrar la consola. Sin cambios. Nota: el
  JobManager de M2 NO cubre los workers de la consola — candidato natural a
  migrarlos al JobManager en el mismo refactor.
- **HG-BUG-0019** (BAJO, ui_qt/screenshot.py): temp `.ppm` puede sobrevivir a
  un SIGKILL. Sin cambios; sigue 0600 y best-effort. Backlog.
- **HG-BUG-0020** (INFO, config.py): placeholder con IP doméstica. Sin
  cambios, intencional y oculto por `hub_is_configured()`. Backlog.
- **HG-BUG-0022** (BAJO, ui_qt/v1_render.py): Control Center con JSON crudo.
  Sin cambios. Los endpoints /dashboard y /progress de M8/M9 dan ya los datos
  estructurados que necesita el fix — recomendable atacarlo junto al wizard.
- **HG-BUG-0023** (INFO, cli/agent): errores de virsh sin humanizar fuera de
  la UI. Sin cambios. Nota: los mensajes nuevos de live migration/GPU ya
  salen redactados con causa y acción, así que no empeoró.

## §2.2 Seguridad — resto de comprobaciones (sin hallazgo)

- Cobertura de auth: Hub gatea los 4 verbos en la entrada (solo GET /health
  abierto); API v1 gatea GET tras /health y POST en la entrada; ningún
  endpoint de M7–M12 (/dashboard, /progress, /vms/<id>/*, /orchestrator/apply)
  se salta el middleware (verificado por inspección y por los tests 401).
- Fugas de token: no hay tokens en logs (se loguea IP/método, nunca el
  token), ni en `--version`, ni en GOAL_PROGRESS.md ni en ningún fichero
  commiteado (barrido `git grep` de cadenas largas en docs: limpio). Los dos
  únicos `print` de token son los comandos de pairing/emisión, intencionales
  y con ADVERTENCIA por stderr. `agent config show` redacta. Ficheros de
  token y config: 0600 (testeado).

## §2.4 GPU — resto (sin hallazgo adicional)

- Parada dura: por boot_vga **o** driver de display, no por nombre — no se
  bypassea con argumentos (tras 0025 tampoco por el camino de bind). Caso
  borde aceptado y documentado: si el probe de vfio falla Y el rebind del
  rollback también falla, el dispositivo queda sin driver (se loguea error).
- `propose-host-changes`: no existe ningún camino que escriba en
  /etc/default/grub ni initramfs; devuelve `applied: false` constante.

## §2.5 Android — sin hallazgos

- Sin tokens/URLs hardcodeadas (solo el prefill "http://" y un hint de UI),
  sin `android.util.Log` en todo el árbol, manifest con INTERNET únicamente,
  CI con versiones pinneadas (JDK 17, Gradle 8.9, AGP 8.5.2) y sin variables
  de entorno externas → build reproducible. Nota (no bug):
  `usesCleartextTraffic=true` está documentado como tradeoff de VPN; al
  desplegar el reverse proxy TLS conviene quitarlo.

## §2.6 Tests — valoración

- 837 → **847 passed**, 9 skipped; log en `pytest_post_night.txt`.
- Sin asserts triviales (`assertTrue(True)`: 0). Los tests con dobles
  verifican orden de llamadas y argumentos (p. ej. flags exactos de
  `virsh migrate`, orden undefine-después-de-confirmar), no solo retornos.
- Debilidad honesta: la live migration solo está probada contra un host
  guionizado (inevitable sin segundo host físico); la verdad final la dan
  U10–U12. El Backup Verifier y la suite needsRealLibvirt sí ejercitan
  hipervisor real (8/8).

## §2.7 Deuda nueva

- Módulos nuevos < 500 líneas (live_migration 409, gpu 361) salvo
  `v1/api.py` → HG-BUG-0030. `main_window.py` sigue en 4701 (TD-1,
  preexistente, sin empeorar).
- Sin imports circulares (import con warnings activados: OK); sin
  TODO/FIXME/HACK nuevos (grep: 0).
- Type hints presentes en los módulos críticos nuevos (migration_engine,
  auth, gpu, progress); `Any` solo en fronteras backend/payload (aceptable).

## Veredicto de merge

**Mergear `audit/post-night-bugs` a develop: SÍ.** Contiene toda la noche
(M1–M13) más los arreglos de esta auditoría. Bloqueantes: ninguno.
Condiciones recomendadas (no bloqueantes): tratar HG-BUG-0028 (journal de
migración) ANTES de usar live migration en producción con shared storage, y
pasar U1/U10–U14 según la cola de GOAL_PROGRESS.md.
