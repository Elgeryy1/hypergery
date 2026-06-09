# HyperGery v1.0 — Release Readiness

- **Fecha:** 2026-06-09
- **Rama final candidate:** `feature/v1.1-ux`
- **Commit de referencia del UAT:** `5c37f42`
- **Estado:** Final candidate preparada. **NO** se ha hecho merge/tag/declaración final.

> Documento de preparación. No autoriza el release: el merge y el tag `v1.0.0`
> requieren decisión explícita de Gerard.

---

## Qué está aprobado para v1.0

- Gestión de VMs estilo VirtualBox (UI VM-first: árbol izq., detalles centro, preview dcha.).
- UI humanizada/traducida al español (botones, estados, mensajes; sin JSON crudo ni literales técnicos).
- Vistas secundarias funcionales: Laboratorios, Otros equipos, Migraciones, Tareas remotas,
  Centro de control, Diagnóstico, Ajustes.
- VNC/consola fuera del hilo de UI (sin congelación).
- Defaults de runtime más seguros + validación de ISO + helpers de formateo compartidos.
- **Migración segura/verificable** (no live): verificada en UAT real (origen intacto, destino correcto,
  sin UUID/MAC duplicados, VM destino arranca, staging limpio, sin tareas colgadas).
- Fixes bloqueantes pre-v1 cerrados con tests:
  - `d731440` — rechazo de rutas inseguras en paquetes de migración (path traversal).
  - `708ed85` — host test no bloqueante por defecto.
- Calidad: compileall OK, suite **661 passed, 0 skipped**.

## Qué queda FUERA de v1.0 (no bloqueante)

- Live migration en caliente.
- Autenticación fuerte del Hub/API (v1.0 asume LAN de confianza).
- Resolución del known issue de Centro de control → Redes (DHCP/CIDR/Duplicate Gateway).
- Limpieza/refactor de `ui_qt/main_window.py` (deuda técnica).

## Qué va para v1.5

- **Live migration real** con VM encendida y downtime mínimo.
- Endurecimiento de autenticación del Hub/API.

---

## Checklist final antes del tag (pendiente de decisión de Gerard)

> Ninguno de estos pasos se ejecuta en esta sesión.

- [ ] **Decisión explícita de Gerard** para proceder al release final.
- [ ] Merge controlado de `feature/v1.1-ux` → `main` (estrategia a decidir).
- [ ] Bump de versión a `v1.0.0` si hace falta.
- [ ] Changelog / release notes finales (`CHANGELOG.md`, `RELEASE_NOTES_v1.0.md`).
- [ ] Tag `v1.0.0`.
- [ ] Push del tag.
- [ ] Publicar release.

---

## Recomendación

La rama está **lista para preparar el release v1.0 final**. El siguiente paso es una
decisión de producto (merge/tag), no una tarea técnica pendiente.
