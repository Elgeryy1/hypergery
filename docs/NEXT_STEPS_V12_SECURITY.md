# NEXT_STEPS_V12_SECURITY — plan de hardening para v1.2

## Autenticación y transporte
- Token bearer para la API v1 (generado localmente, guardado fuera del repo,
  permisos 0600) + opción TLS (certificado autofirmado gestionado).
- Autenticación del Hub (hoy LAN-only sin auth, documentado): token compartido
  App/Agent↔Hub como mínimo; rotación documentada.
- Revisar binds por defecto (API 127.0.0.1 ✓; Hub 0.0.0.0 en Docker → limitar
  por firewall del NAS o token).

## RBAC hardening
- Sesiones/identidad real para usuarios (hoy RBAC local sin login).
- Enforcement de RBAC en la API (hoy la API no identifica al llamante).
- Tests de escalada: Guest no puede llegar a ningún endpoint mutante.

## Audit
- Audit log firmado/append-only (hoy JSONL plano).
- Retención y rotación de logs estructurados.

## Secret scanning / higiene
- Hook pre-commit con grep de patrones (ghp_, github_pat_, BEGIN PRIVATE KEY,
  password=) — el grep manual ya forma parte de la validación final.
- `gh auth logout` tras sesiones de push si el portátil es compartido
  (el token OAuth de gh vive en ~/.config/gh/hosts.yml, fuera del repo).

## Least privilege
- Usuario dedicado para el Agent como servicio (ya es user-service sin sudo ✓).
- Revisar permisos de los JSON de estado (users.json, external-nodes.json,
  v1-settings.json) → 0600.
- Allowlists: mantener la doble validación Hub+Agent como invariante con un
  test de contrato que falle si alguien añade un command_type sin revisar.

## NAS credentials
- Nunca credenciales NAS en repo/config (invariante actual ✓). Documentar
  el montaje con credenciales en keyring del sistema, no en fstab plano.

## TLS / exposición
- Si el Hub o la API deben salir de la LAN: reverse proxy con TLS y auth,
  nunca el puerto directo.
