# NEXT_STEPS_V11 — plan de bugfix/UX para v1.1

Prioridad sobre V1_KNOWN_BUGS.md más lo siguiente.

## Crashes / robustez
- Barrer rutas de error de la API con fuzzing ligero de parámetros.
- Timeout/cancelación en los collectors del Control Center si el Hub tarda.
- Reintentos suaves en HostRegistry cuando el Hub devuelve 5xx intermitente.

## UX
- Control Center: tablas/cards en vez de JSON; chips OK/WARN/FAIL por tab.
- Orchestrator: botón "Apply plan…" con confirmación por plan (hoy es
  read-only) y enlace directo al teleport dry-run.
- NAS: commit/restore desde UI con diálogo de confirmación y dry-run previo.
- Battery: indicador permanente en la top bar (chip con tier).
- Teleport: asistente con los 4 modos y explicación de riesgos.
- Guests: alta/edición de usuarios desde UI (hoy: JSON/CLI).

## Rendimiento
- Cachear list_hosts del Hub unos segundos (Control Center refresca 8 tabs).
- `read_cpu_percent` sin sleep(0.1) usando muestreo diferido.

## Tests que faltan
- Qt: tab Orchestrator con datos reales simulados ricos (hoy texto).
- API: concurrencia (varios clientes simultáneos).
- Teleport suspend_copy_start contra agent real en contenedor.
- memdiff con archivos grandes (rendimiento, block sizes).

## Refactors
- Extraer `ApiContext` a `v1/context.py` y reutilizarlo en UI/CLI (hoy la UI
  construye servicios a mano en `_v1_collect`).
- Unificar los dos `format_size` (cli.py y main_window.py) en un helper.
- Mover el FakeBackend de tests a un fixture compartido oficial.
