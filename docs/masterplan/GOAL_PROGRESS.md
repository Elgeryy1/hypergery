# GOAL_PROGRESS — noche autónoma (inicio: 2026-06-09)

> Memoria viva del agente. Si el contexto se compacta: leer esto y continuar.
> Plan maestro: `goalplan.md` (raíz del repo). Orden de milestones: §10.

## Estado global

- **Baseline verificado:** `main` @ 2148aec — `compileall` OK, `pytest -q` = **667 passed, 1 skipped** (30.8s), venv `~/.venvs/hypergery` (Python 3.14).
- **Milestone actual:** M1 — v1.1 identidad de app + `.deb` + `--version`/About.
- **Rama actual:** `feat/v1.1-app-identity`.

## Milestones (orden §10 del goalplan)

| # | Milestone | Estado |
|---|-----------|--------|
| 1 | v1.1 identidad app + .deb + --version/About | EN CURSO |
| 2 | v1.1 JobManager + closeEvent + throttle preview (TD-3, 0008/0015) | pendiente |
| 3 | v1.1 Hub robusto (busy_timeout/WAL, TTL, upload) (0005/0006/0010) | pendiente |
| 4 | v1.1 redes coherentes + colisión octetos (0009/0012/0016) | pendiente |
| 5 | v1.1 needsRealLibvirt + higiene (0011/0017/0018, retirar Tk) | pendiente |
| 6 | v1.2 token/TLS + RBAC enforced + audit log (0001, TD-5) | pendiente |
| 7 | v1.3 Template Store + Backup Verifier + snapshots + tags | pendiente |
| 8 | v1.4 orchestrator aplicable + /telemetry + health + API companion | pendiente |
| 9 | v1.5 prep migration_engine (TD-4) + canal progreso (TD-9) | pendiente |
| 10 | v1.5 live migration en caliente + preflight + wizard | pendiente |
| 11 | v1.6 app Android nativa | pendiente |
| 12 | v1.7 GPU passthrough VFIO | pendiente |
| 13 | v2.0 investigación | pendiente |

## M1 — v1.1 identidad de app (EN CURSO)

**Hallazgos de auditoría previa:**
- Versión triplicada (HG-BUG-0017): `pyproject.toml` (1.0.1), `hypergery_ubuntu/__init__.py` (`__version__`), `ui_qt/styles.py` (`APP_DISPLAY_VERSION`). Además `app_tk.py` tiene una cuarta ("0.6.0", muerto).
- Ya existe `scripts/install-desktop-launcher.sh` (launcher de usuario, no .deb).
- About dialog ya existe (`main_window.py:show_about`), usa APP_DISPLAY_VERSION.
- Sin icono de app (iconos por código en `ui_qt/icons.py`, sin assets).
- Entry points: `hypergery` (app.py→ui_qt.main), `hypergery-cli` (cli.py), `hypergery-agent` (agent.py). Ninguno acepta `--version`.

**Plan M1:**
1. Versión única: `__init__.py` canónica; pyproject `dynamic=["version"]`; styles importa.
2. `--version` en app/cli/agent (app: antes de importar Qt).
3. Icono de app por código (window icon) + SVG para .desktop/.deb.
4. `packaging/`: `hypergery.desktop`, `hypergery.svg`, `scripts/build-deb.sh` (dpkg-deb, paquete `all`, wrappers /usr/bin, sin tocar datos de usuario al desinstalar).
5. Tests: identidad de versión única, --version x3, .desktop válido, build .deb real si dpkg-deb disponible.
6. U1: build+inspección automatizada; instalación real requiere sudo → probar `sudo -n`, si no, cola UAT.

## Cola de UAT humano (para Gerard)

- (pendiente de rellenar; U10–U14 caerán aquí en sus milestones)

## Bloqueos

- (ninguno)

## Próximo paso

- Implementar plan M1 (arriba).
