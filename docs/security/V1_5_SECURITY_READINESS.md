# Security release readiness — v1.5.0-rc

- **Fecha:** 2026-06-10
- **Rama:** `hardening/pre-v1.5-bugfix-security` (desde `audit/post-night-bugs`,
  que contiene toda la cadena v1.1→v1.5 + los fixes de la auditoría nocturna)
- **Ámbito de la release:** v1.1–v1.5. v1.6 Android, v1.7 GPU y v2.0 research
  quedan FUERA (sin UAT físico / solo investigación).

## Checklist de seguridad (PASS/FAIL)

| Control | Resultado | Evidencia |
|---|---|---|
| Sin secretos hardcodeados | **PASS** | barrido git grep; los únicos `print` de token son pairing/emisión con ADVERTENCIA |
| Tokens fuera de logs | **PASS** | se loguea IP/método, nunca el token; `agent config show` redacta |
| Tokens en docs solo como ejemplos falsos | **PASS** | barrido docs limpio |
| Ficheros token/config 0600 | **PASS** | `config.py:110`, `registry/auth.py:40-41` + tests |
| Comparación constant-time de tokens | **PASS** | HG-BUG-0026, `ConstantTimeTokenTests` |
| Rate limit Hub y API v1 | **PASS** | `AuthRateLimiter` en ambos (HG-BUG-0027) |
| Bearer obligatorio por defecto | **PASS** | TD-5; tests 401/403 (`test_security_v12.py`, 21) |
| No expuesto en 0.0.0.0 por defecto | **PASS** | default `127.0.0.1`; `0.0.0.0` solo explícito (Docker del NAS, documentado) |
| `--no-auth` explícito + warning fuerte | **PASS** | help DANGEROUS + `logging.warning` runtime |
| Acciones destructivas con confirmación | **PASS** | `--confirm` en migrate-live/apply; companion API sin force-off/delete/undefine |
| Guests sin acciones destructivas | **PASS** | RBAC `GUEST_FORBIDDEN`, scoping por lab |
| Límite de tamaño en uploads | **PASS** | Hub robusto v1.1 + tests |
| Long-poll con límite de concurrencia | **PASS** | `MAX_CONCURRENT_LONG_POLLS=32` (HG-BUG-0029) |
| Migración con journal anti double-active | **PASS** | `migration_journal.py` (HG-BUG-0028) + 8 tests |
| `qemu+tcp` rechazado | **PASS** | `MigrationPlan.__post_init__` solo ssh/tls |
| Errores humanizados sin secretos | **PASS** | HG-BUG-0023 + `test_humanize.py` |
| Temporales seguros (no /tmp a pelo) | **PASS** | `NamedTemporaryFile`/`mkstemp`; previews en `XDG_RUNTIME_DIR` (HG-BUG-0019) |
| Sin path traversal en uploads/downloads | **PASS** | ids validados + `resolve()` contra staging root (`registry/server.py:59-67`) |
| Sin CORS abierto | **PASS** | ningún `Access-Control-Allow-Origin` en el código; clientes no-navegador |
| Sin operaciones root automáticas | **PASS** | GPU bind (root) exige --confirm y está fuera de v1.5; enable-linger es manual |
| Sin lenguaje de evasión en docs | **PASS** | barrido (evasión/bypass/tunneling/camuflaje/etc.): limpio; política nueva en `docs/security/CONNECTIVITY_POLICY.md` |
| bandit | **N/A** | **no disponible** en el venv; no se instaló nada por red (regla de la sesión) |

## Qué se auditó

- Barrido grep de patrones peligrosos (`shell=True`, `os.system`, `eval/exec`,
  `pickle`, `yaml.load`, `verify=False`, `qemu+tcp`, `--no-auth`, `0.0.0.0`,
  `/tmp`, CORS…) sobre `hypergery-ubuntu`, `scripts`, `docker`, `docs`,
  `android`. Hallazgos reales: ninguno nuevo (los `exec(` son `dialog.exec()`
  de Qt; los `subprocess` van con listas de argumentos, sin `shell=True`).
- Revisión dirigida de `v1/api.py`, `v1/auth.py`, `registry/server.py`,
  `registry/auth.py`, `registry/client.py`, `agent.py`, `cli.py`, `backend.py`,
  `migration.py`, `v1/live_migration.py`, `migration_journal.py`,
  `v1/progress.py`, `ui_qt/*`, `scripts/*`, `docker/*`.
- Barrido de lenguaje de riesgo en `docs/` (evasión, bypass, DNS tunneling,
  camuflaje, "saltarse" restricciones, borrar rastros): **limpio**;
  `docs/HUB_SECURITY.md` ya decía expresamente «nada de evasión».

## Bugs cerrados en esta pasada

| ID | Fix |
|---|---|
| HG-BUG-0014 | Cancel de consola no bloqueante (drenaje en segundo plano, descarte de sockets tardíos, sin `thread.wait()` en la UI) |
| HG-BUG-0022 | Centro de control: secciones «Salud del sistema» (/dashboard) y «Operaciones» (/progress) como tarjetas/tablas; JSON solo bajo «Ver detalles técnicos» |
| HG-BUG-0030 | Fase 1: `ApiContext` → `v1/api_context.py` (api.py 580→436 líneas), API pública intacta |
| HG-BUG-0020 | Default del Hub parametrizado también en `install-agent-user-service.sh`; naturaleza de la IP documentada |

## Bugs/deuda restantes (no bloquean v1.5.0-rc)

- HG-BUG-0030 fase 2: extraer los handlers HTTP de `api.py` a `api_handlers/`
  — planificada para antes de v1.6 (cuando Android añada endpoints).
- TD-1: `main_window.py` sigue grande (4700+ líneas; preexistente, sin empeorar).
- Wizard Qt de live migration: decisión de UX pendiente con Gerard (la CLI y
  el progreso están completos).

## Riesgos residuales

Los del threat model §4 (`docs/security/V1_5_THREAT_MODEL.md`): U10–U12
pendientes (bloquean tag/release, no la RC), U13/U14 fuera de v1.5, validación
visual manual de la UI, TLS vía reverse proxy/VPN.

### Checklist UAT UI (manual, antes del tag)

1. Abrir consola de una VM apagada/encendida; cerrar la ventana mientras pone
   «Conectando…» → la app no se congela y no aparece ningún aviso de QThread.
2. Centro de control → «Salud del sistema» y «Operaciones» muestran tarjetas
   (no JSON); «Ver detalles técnicos» sigue mostrando el JSON.
3. `hypergery-cli hub pairing-info` avisa de que el token es secreto.

## Comandos ejecutados

```
git checkout audit/post-night-bugs && git pull --ff-only
git checkout -b hardening/pre-v1.5-bugfix-security
git grep -n "shell=True|os.system|…"        # barrido seguridad (limpio)
python -m bandit -r hypergery_ubuntu        # NO DISPONIBLE (módulo ausente)
python -m compileall -q hypergery_ubuntu    # OK
QT_QPA_PLATFORM=offscreen pytest -q         # 871 passed, 8 skipped
```

needsRealLibvirt NO ejecutada (no era imprescindible); último resultado
conocido 8/8 PASS en host real. Sin live migration real, sin GPU bind, sin
build Android, sin tocar VMs.

## Veredicto

**LISTO para construir `release/v1.5.0-rc`** desde esta rama (que ya contiene
v1.1→v1.5 + fixes de auditoría + este hardening), **con dos condiciones**:

1. **No tag y no release hasta que U10–U12 (live migration física) estén
   PASS.** La RC se puede construir y probar; publicarla no.
2. Incluir también `fix/v1.1-packaging-uat` (el fix del packaging U1 y sus
   tests viven en esa rama hermana, no en esta cadena).
