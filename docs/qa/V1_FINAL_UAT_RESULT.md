# HyperGery v1.0 — Final UAT Result

- **Fecha/hora:** 2026-06-09 20:30 CEST
- **Rama:** `feature/v1.1-ux`
- **Commit en el momento del UAT:** `5c37f42` (`docs: record pre-v1 review fixes and deferred UI optionals`)
- **Estado:** Release candidate de v1.0 — **NO** es v1.0 final (sin merge, sin tag, sin declaración final).

> Este documento registra el resultado del UAT final de v1.0. No autoriza por sí mismo
> el merge ni el tag: eso queda pendiente de decisión explícita de Gerard.

---

## Entorno

| Componente | Valor |
|---|---|
| PC principal (UAT visual) | Ubuntu, sesión Wayland (XDG_SESSION_TYPE=wayland, DISPLAY=:0) |
| Python | 3.14.4 (venv `~/.venvs/hypergery`) |
| PySide6 | 6.11.1 |
| pytest | 9.0.3 |
| Hub/NAS | NAS como hub del laboratorio; hosts en LAN de confianza (ver known issues sobre auth) |
| Host destino migración | Host destino del laboratorio (UAT de migración ejecutado y verificado) |

El lanzamiento de la app real se hace con `QT_QPA_PLATFORM=xcb` (X11 vía XWayland).

---

## Tests

| Verificación | Comando | Resultado |
|---|---|---|
| Compilación | `python -m compileall hypergery_ubuntu` | **OK** (exit 0) |
| Qt focalizados | `QT_QPA_PLATFORM=offscreen pytest tests/test_qt_ui.py tests/test_qt_v1_render.py tests/test_qt_iso_validation.py -q` | **128 passed** |
| Suite completa | `QT_QPA_PLATFORM=offscreen pytest -q` | **661 passed, 0 skipped** |

No hay regresiones. No se modificaron tests para forzar el verde.

---

## UAT visual (aprobado por Gerard)

### Pantalla principal — PASS
- [x] Aspecto tipo VirtualBox, no dashboard web.
- [x] Menú superior claro.
- [x] Toolbar superior clara.
- [x] Lista/árbol de VMs a la izquierda.
- [x] Detalles de VM en el centro.
- [x] Preview a la derecha.
- [x] Laboratorios no invade la pantalla principal.
- [x] Registro/log no roba media pantalla.
- [x] Botones en español.
- [x] Estados en español: Encendida / Apagada / Pausada.
- [x] No aparece JSON crudo.
- [x] No aparecen literales técnicos (RUNNING, shut off, DEFAULT, reachable, etc.).

### Selección de VM — PASS
- [x] Seleccionar una VM actualiza los detalles.
- [x] El preview cambia al nombre de la VM.
- [x] La toolbar se activa/desactiva según el estado.
- [x] Configuración no se habilita donde no debe.
- [x] Consola solo tiene sentido con la VM encendida.

### Vistas secundarias — PASS
- [x] Laboratorios abre.
- [x] Otros equipos abre.
- [x] Migraciones abre.
- [x] Tareas remotas abre.
- [x] Centro de control abre.
- [x] Diagnóstico abre.
- [x] Ajustes abre.
- [x] Todas mantienen español/humanización.

### Errores — PASS
- [x] No hay traceback visible.
- [x] No hay congelación de UI.
- [x] Los mensajes de error son humanos.

---

## UAT de migración (aprobado por Gerard)

Migración **segura/verificable** (no live), ejecutada en el laboratorio real:

- [x] Terminó sin crash.
- [x] El origen sigue intacto.
- [x] El destino aparece en el host correcto.
- [x] UUID/MAC no duplicados.
- [x] El disco existe y el tamaño es correcto.
- [x] La VM destino arranca.
- [x] La consola abre.
- [x] El staging del Hub queda limpio.
- [x] Logs humanos, sin traceback.
- [x] No quedó ninguna tarea colgada.

---

## Evidencias

Capturas de la app abierta (UAT final), en `docs/qa/evidence/v1-final/`:

- `01-main-vm-manager.png` — ventana principal (pestaña **Inicio**): resumen del equipo, Hub
  «En línea», Zona NAS «Funciona», equipos en línea 2/2 y último traslado; menú y toolbar en
  español, estados humanos, sin JSON crudo.
- `02-vm-selected-details.png` — layout VM-first estilo VirtualBox: árbol de VMs a la izquierda,
  panel de detalles en el centro (General/Sistema/Pantalla/Almacenamiento/Audio/Red/USB) y
  previsualización a la derecha. VM `ubuntu-migrated-migrated` seleccionada, estado **Encendida**.
- `03-secondary-views.png` — vista secundaria **Laboratorios** (no invade la principal), tabla de
  laboratorios/equipos en español.
- `04-control-center.png` — **Centro de control** renderizado como tarjetas (CPU/Memoria/Disco,
  resumen del equipo), con aviso «Esta página solo muestra información…» y «Ver detalles
  técnicos». Sin JSON crudo.
- `05-migration-result-or-logs.png` — vista **Migraciones**: historial con Origen/Destino/Ruta/
  Método/Estado/Actualizado y limpieza de archivos temporales del Hub. Logs humanos.

> **Nota sobre captura (GNOME Wayland):** Las capturas no se pudieron automatizar (GNOME deniega
> capturas programáticas vía `org.gnome.Shell.Screenshot` y el fallback X11/XWayland falla). Se
> tomaron manualmente con la app abierta usando la captura de ventana de GNOME (Alt+Impr Pant) y
> se incorporaron a la carpeta de evidencias. Verificadas: 5/5, imágenes válidas no vacías.

---

## Known issues no bloqueantes

1. **Centro de control → Redes:** muestra un error sobre DHCP/CIDR/Duplicate Gateway.
   No afecta al flujo principal de gestión/migración de VMs. Aceptado como known issue de v1.0.
2. **Hub/API sin autenticación fuerte:** usar únicamente en LAN de confianza. Endurecer en v1.x.
3. **Live migration fuera de v1.0:** la migración de v1.0 es segura/verificable (no live).
   La live migration real (VM encendida, downtime mínimo) queda planificada para v1.5.

---

## Riesgos diferidos

- **Live migration** (en caliente) → v1.5.
- **Autenticación fuerte del Hub/API** → v1.x.
- **Limpieza/refactor de `ui_qt/main_window.py`** si crece en complejidad (deuda técnica, no bloqueante).

---

## Veredicto

- **Apto para preparar el release v1.0 final.** Tests verdes, UAT visual y de migración aprobados.
- **Pendiente únicamente la decisión explícita de Gerard** para el merge controlado a `main`,
  el bump de versión, las release notes finales y el tag `v1.0.0`.
- Mientras tanto, la rama `feature/v1.1-ux` queda como **final candidate** documentada y subida.
