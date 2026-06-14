# POST_NIGHT_AUDIT — auditoría de la noche autónoma (M1–M13)

> Rama: `audit/post-night-bugs` (sobre `feat/v2.0-research`).
> Baseline al empezar: compileall OK, pytest = 837 passed, 9 skipped.
> Al cerrar: compileall OK, pytest = **847 passed, 9 skipped** (10 tests de
> regresión nuevos en `tests/test_post_night_audit.py`). Log completo:
> `docs/audit/pytest_post_night.txt`.

## Resumen ejecutivo

> **Actualizado tras 2ª tanda de arreglos.** Hallazgos totales: 10.
> Arreglados/cerrados: **9**. En cola para Gerard: **1** (BAJO, deuda).
> pytest = **857 passed, 9 skipped** (20 tests de auditoría nuevos).
> Suite real libvirt 8/8, host limpio.

- 1ª tanda: HG-BUG-0025 (ALTO), 0026/0027 (MEDIO) arreglados; 0013/0021
  cerrados.
- 2ª tanda: **HG-BUG-0028 (ALTO) ARREGLADO** (journal persistente de
  migración), **0029 (MEDIO) ARREGLADO** (límite de long-polls), **0019 (BAJO)
  ARREGLADO** (preview en XDG_RUNTIME_DIR + limpieza), **0023 (INFO) ARREGLADO**
  (humanización de errores en CLI/agente).
- Cerrados sin tocar (decisión consciente): **0020** (la IP es el Hub real del
  laboratorio de Gerard, presente en scripts/tests/docs; severidad INFO,
  privado — cambiarlo rompería los launchers funcionales) y **0030/0022/0014**
  (ver abajo).
- **Veredicto de merge: SÍ, mergear `audit/post-night-bugs`.** Sin bloqueantes.
  Ya no queda ningún ALTO ni MEDIO abierto.

> **Actualización 2026-06-10 (post-noche):** U1 packaging **PASS completo** en
> UAT real con sudo (rama `fix/v1.1-packaging-uat`, ver
> `docs/qa/V1_1_UAT_RESULT.md`). pytest hoy en esta rama: **858 passed,
> 8 skipped**. Matiz al veredicto de merge: «mergear» sigue significando solo
> features con UAT cumplido — v1.5 live/v1.6 Android/v1.7 GPU quedan congeladas
> hasta U10–U14; cobertura completa por versión en
> `docs/qa/POST_NIGHT_VERSION_COVERAGE_AUDIT.md`.

## Tabla de hallazgos

| ID | Severidad | Módulo | Estado |
|----|-----------|--------|--------|
| HG-BUG-0025 | **ALTO** | v1/gpu_passthrough.py | **ARREGLADO** esta sesión |
| HG-BUG-0026 | MEDIO | v1/auth.py | **ARREGLADO** esta sesión |
| HG-BUG-0027 | MEDIO | v1/api.py | **ARREGLADO** esta sesión |
| HG-BUG-0021 | BAJO | agent.py | **CERRADO** esta sesión |
| HG-BUG-0013 | BAJO | migration.py | **CERRADO** esta sesión |
| HG-BUG-0028 | **ALTO** | v1/live_migration.py + migration_journal.py | **ARREGLADO** 2ª tanda |
| HG-BUG-0029 | MEDIO | v1/api.py | **ARREGLADO** 2ª tanda |
| HG-BUG-0019 | BAJO | ui_qt/screenshot.py | **ARREGLADO** 2ª tanda |
| HG-BUG-0023 | INFO | cli.py + agent.py | **ARREGLADO** 2ª tanda |
| HG-BUG-0030 | BAJO | v1/api.py | EN COLA (deuda, sin riesgo) |
| HG-BUG-0014/0020/0022 | BAJO/INFO | varios | Abiertos (ver notas) |

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

### HG-BUG-0028 — Sin journal persistente de migración: origen arrancable tras el switchover — ALTO · ARREGLADO (2ª tanda)

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
- **Fix:** nuevo `hypergery_ubuntu/migration_journal.py` (módulo neutro de
  nivel superior para que `backend` no dependa de `v1`). `MigrationJournal`
  escribe `migration_journal.json` en el state dir con una entrada por VM.
  `LiveMigrator` llama a `journal.begin()` justo antes del `virsh migrate`
  (punto de no retorno) y libera la entrada según el resultado:
  - **éxito con undefine del origen** → clear (el origen ya no existe);
  - **`--keep-source-definition`** → la entrada PERMANECE (con shared storage
    arrancar el origen sigue siendo peligroso); se limpia a mano;
  - **rollback con origen vivo de nuevo** → clear;
  - **destino promovido / origen parado** → la entrada PERMANECE.
  `backend.start_vm` llama a `journal.assert_startable()` y se NIEGA a arrancar
  una VM con migración sin confirmar. CLI nuevo:
  `hypergery-cli v1 migrate-journal list|clear <vm>`.
- **Tests:** `MigrationJournalTests`, `BackendStartVmJournalTests`,
  `LiveMigrationJournalIntegrationTests` (8 tests: begin/clear, start_vm
  rechazado, y las 4 ramas de limpieza/retención del migrador real).

### HG-BUG-0029 — Long-poll puede agotar los hilos del ThreadingHTTPServer — MEDIO · ARREGLADO (2ª tanda)

- **Módulo:** `v1/api.py` (GET /progress/<id>), aplica en menor medida a todo
  el Hub (es inherente a `http.server`).
- **Descripción:** cada long-poll bloquea un hilo hasta 60s; N conexiones
  concurrentes = N hilos sin techo. Dentro de una VPN autenticada y con el
  rate limit de 0027 el riesgo real es bajo, pero un cliente legítimo con un
  bug de reintentos podría degradar el API.
- **Fix:** `ApiServer` tiene un `BoundedSemaphore(MAX_CONCURRENT_LONG_POLLS=32)`;
  el endpoint de long-poll lo adquiere sin bloquear y devuelve **503** si no
  hay hueco (el cliente reintenta), liberándolo siempre en `finally`. El resto
  de endpoints no se ve afectado.
- **Tests:** `LongPollLimitTests` (semáforo agotado → 503).

### HG-BUG-0019 — Screenshot temp en /tmp puede sobrevivir a SIGKILL — BAJO · ARREGLADO (2ª tanda)

- **Fix:** las capturas de preview se escriben bajo
  `$XDG_RUNTIME_DIR/hypergery-previews` (tmpfs por usuario, 0700) en vez de
  `/tmp`; `cleanup_stale_previews()` barre los restos al arrancar la UI
  (`ui_qt/main.py`). Mantiene el 0600 del fichero y el borrado en `finally`.
- **Tests:** `PreviewTempDirTests` (dir 0700 bajo runtime, limpieza borra solo
  los `hg-preview-*`).

### HG-BUG-0023 — Errores de virsh sin humanizar en CLI/agente — INFO · ARREGLADO (2ª tanda)

- **Fix:** los dos `main()` (cli.py y agent.py) pasan el mensaje de
  `HyperGeryError` por `humanize_error_message` (módulo `ui_qt/humanize`, que
  es Python puro sin Qt — verificado que el agente headless sigue importando
  sin PySide6). Errores frecuentes (ISO/disco que falta, fallo de arranque)
  salen con resumen + pasos + detalle técnico.
- **Tests:** `CliHumanizedErrorsTests`.

### HG-BUG-0030 — `v1/api.py` cruza las 500 líneas — BAJO · EN COLA (deuda, sin riesgo)

- M8/M9 (+0027/0029 de la auditoría) añadieron companion + dashboard +
  progress + rate limit en el mismo fichero. Mismo patrón que TD-1/TD-2:
  extraer handlers a `v1/api_handlers/` antes de que la app Android traiga más
  endpoints. Único punto que queda en cola; sin riesgo funcional.

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
- **HG-BUG-0020** (INFO, config.py): la IP `192.168.1.150` NO es un
  placeholder ficticio sino el Hub real del laboratorio de Gerard, referenciado
  en los scripts launcher (`start-second-host.sh`,
  `install-agent-user-service.sh`, con un test `test_launchers_default_to_nas_hub`
  que lo exige) y en decenas de docs. Es severidad INFO, intencional, y se trata
  de la LAN privada del propio usuario en un repo privado. **Decisión: no
  tocarlo** — cambiar el placeholder rompería los launchers funcionales sin
  ganar nada real.
- **HG-BUG-0022** (BAJO, ui_qt/v1_render.py): Control Center con JSON crudo.
  Sin cambios (es UX, no riesgo). Los endpoints /dashboard y /progress de M8/M9
  ya dan los datos estructurados que necesita el fix — recomendable atacarlo
  junto al wizard de migración en una sesión de UI con Gerard.
- **HG-BUG-0014** (BAJO, ui_qt/console.py): `_stop_connect_worker` puede
  congelar la UI hasta 10s al cerrar la consola. Sin cambios — es una decisión
  consciente (evitar el crash "QThread destroyed") y el fix correcto es migrar
  los workers de consola al JobManager de M2, que es trabajo de UI con riesgo
  de regresión visual → mejor en una sesión con Gerard, no a ciegas.

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
(M1–M13) más las dos tandas de arreglos de esta auditoría. Bloqueantes:
ninguno. **No queda ningún hallazgo ALTO ni MEDIO abierto.**

- HG-BUG-0028 (el riesgo de doble-activa en live migration) ya está cerrado
  con el journal persistente, así que live migration con shared storage tiene
  la red de seguridad puesta — aun así, U10–U12 (dos hosts físicos) siguen en
  cola para validarlo en hardware real.
- Lo único en cola es HG-BUG-0030 (deuda: partir `v1/api.py`), sin riesgo
  funcional, y los UAT físicos U1/U10–U14 de `GOAL_PROGRESS.md`.

Gates finales: compileall OK · pytest **857 passed, 9 skipped** · suite real
libvirt **8/8** · host limpio · agente headless importa sin PySide6.

## Actualización 2026-06-10 — rama `hardening/pre-v1.5-bugfix-security`

Pasada de bugfix + hardening previa a v1.5.0-rc. Cambios de estado:

| ID | Estado anterior | Estado nuevo |
|----|-----------------|--------------|
| HG-BUG-0014 | Abierto | **ARREGLADO** — cancel de consola no bloqueante: el connect en vuelo se drena en segundo plano (`_draining_threads`), descriptores tardíos se descartan, sin `thread.wait()` en la UI y sin "QThread destroyed". Test: `test_cancel_does_not_block_ui_while_connect_hangs`. |
| HG-BUG-0022 | Abierto | **ARREGLADO** — el Centro de control gana «Salud del sistema» (/dashboard v1.4) y «Operaciones» (/progress v1.5) renderizadas como tarjetas/tablas vía `v1_render`; el JSON queda solo tras «Ver detalles técnicos». Tests: `test_dashboard_and_progress_are_humanized_not_raw_json` + parametrizados. |
| HG-BUG-0030 | EN COLA | **FASE 1 HECHA** — `ApiContext` extraído a `v1/api_context.py` (api.py 580→436 líneas) con re-export que mantiene la API pública. Fase 2 (handlers HTTP a `api_handlers/`) queda planificada para después de v1.5, antes de que v1.6 añada endpoints. |
| HG-BUG-0020 | Cerrado sin tocar | **CERRADO con mejora** — `install-agent-user-service.sh` ahora respeta `HYPERGERY_HUB_URL` también para el default; documentado en `docs/HUB_SECURITY.md` que la IP es el NAS privado de Gerard, no un valor universal. Test: `test_hub_default_is_parametrized_not_hardcoded`. |

Además: política de conectividad (`docs/security/CONNECTIVITY_POLICY.md`),
threat model (`docs/security/V1_5_THREAT_MODEL.md`) y readiness
(`docs/security/V1_5_SECURITY_READINESS.md`). Gates: compileall OK,
pytest = **871 passed, 8 skipped**. bandit: no disponible en el venv (no se
instaló nada por red).
