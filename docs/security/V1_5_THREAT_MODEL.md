# Threat model — HyperGery v1.5

- **Fecha:** 2026-06-10 · **Rama:** `hardening/pre-v1.5-bugfix-security`
- **Ámbito:** lo que entraría en una release v1.5.0 (v1.1–v1.5). Android (v1.6),
  GPU passthrough (v1.7) y v2.0 research quedan FUERA de la release productiva.

## 1. Activos protegidos

| Activo | Dónde vive |
|---|---|
| VMs (definición + ejecución) | libvirt/QEMU en cada host |
| Discos qcow2 | `~/.local/share/hypergery/vms`, NAS |
| Snapshots y backups | libvirt + NAS (`hub-transfer`, policies v1.3) |
| Tokens (Hub, API v1, usuarios RBAC) | `~/.config/hypergery/*` (0600) |
| NAS (staging, backups, ISOs) | montaje del NAS de Gerard |
| Hub/registry (inventario, comandos, eventos) | SQLite en el NAS (Docker) |
| API v1 (estado, acciones, progreso) | proceso local por host |
| Hosts (PC, portátil) | LAN privada de Gerard |
| Datos de invitados (labs asignados) | stores v1 (labs, RBAC) |

## 2. Actores

| Actor | Capacidad | Trato |
|---|---|---|
| **Gerard (Owner/SuperAdmin)** | todo | confirmaciones para lo destructivo; el diseño le protege del error humano |
| **Guest/Classmate** | rol RBAC limitado | sin acciones destructivas, scoping por lab, sin recursos de Gerard sin permiso |
| **Atacante en la LAN** | alcanza puertos abiertos | token obligatorio, rate-limit, bind 127.0.0.1 por defecto, TLS/VPN recomendado |
| **Cliente Android comprometido** (futuro v1.6) | tiene un token de usuario | tokens por usuario revocables, RBAC, solo acciones seguras (start/ACPI/snapshot) |
| **Agente comprometido** | credencial de host | solo informa y consume su cola; el Hub valida y audita |
| **Error humano** | borrar/migrar mal | confirmaciones, preflight, journal, backups verificables |

## 3. Superficies de ataque y controles

| Superficie | Riesgos principales | Controles (verificados en código/tests) |
|---|---|---|
| Hub/registry HTTP | acceso no autenticado, fuerza bruta, flooding | Bearer obligatorio (TD-5), comparación constant-time (HG-BUG-0026), `AuthRateLimiter` por IP, audit log de fallos, WAL/busy_timeout, TTL de comandos, límite de tamaño de upload, bind 127.0.0.1 por defecto |
| API v1 | escalada de rol, abuso de long-poll | RBAC `require_permission` (401/403), rate limit (HG-BUG-0027), semáforo de long-polls (HG-BUG-0029), token 0600 |
| CLI | acciones destructivas por descuido | `--confirm` en migrate-live/apply, `--no-auth` marcado DANGEROUS + warning runtime |
| Agente | tragarse errores, exfiltrar token | excepciones logueadas (HG-BUG-0021), `agent config show` redacta el token |
| Uploads/downloads del Hub | path traversal, llenado de disco | ids validados + `resolve()` contra el staging root, límite de tamaño |
| Live migration (v1.5) | double-active, URI insegura, VM colgada | journal persistente (HG-BUG-0028), solo `qemu+ssh/qemu+tls` (qemu+tcp rechazado), preflight, rollback `domjobabort`, cancel |
| Backups (v1.3) | restaurar basura | Backup Verifier (arranque real de VM temporal + cleanup) |
| Consola VNC | UI congelada, fd huérfanos | connect en worker con timeout; cancel no bloqueante con drenaje y descarte de descriptores tardíos (HG-BUG-0014, esta rama) |
| Packaging .deb | binarios ajenos, datos de usuario | build desde el árbol git, sin tocar ~/.config ni ~/.local al desinstalar (U1 PASS) |
| Temporales | symlink/exposición en /tmp | `NamedTemporaryFile`/`mkstemp`; previews bajo `XDG_RUNTIME_DIR` (HG-BUG-0019) |

No hay CORS que abrir: ni el Hub ni el API v1 sirven a navegadores (clientes
son CLI/agente/app), y no emiten `Access-Control-Allow-Origin`.

## 4. Riesgos residuales (aceptados y visibles)

1. **U10–U12 pendientes**: la live migration solo está probada con tests
   simulados; sin UAT físico, v1.5 NO se etiqueta como release.
2. **Android U13 pendiente** (+CI/APK): fuera de la release v1.5.
3. **GPU U14 pendiente**: fuera de la release v1.5.
4. **UI**: el cierre no bloqueante de consola y las secciones nuevas del
   Centro de control tienen tests offscreen, pero la validación visual es
   manual (checklist UAT UI en `V1_5_SECURITY_READINESS.md`).
5. **Sin TLS nativo**: el Hub/API confían en reverse proxy o VPN para el
   cifrado fuera de localhost (documentado en `docs/HUB_SECURITY.md`).
6. **Token en claro dentro de la LAN de confianza** si no se aplica el punto 5
   (decisión documentada; LAN privada de Gerard).

## 5. Criterios de bloqueo para v1.5.0

- ❌ Cualquier endpoint que se salte `_authenticate`/RBAC.
- ❌ Cualquier vía de migración que acepte `qemu+tcp://` o no pase preflight.
- ❌ Doble-active reproducible pese al journal.
- ❌ Token o secreto en logs, docs o salidas de CLI sin redactar.
- ❌ U10–U12 sin ejecutar → **no tag, no release** (RC preparable, release no).
- ❌ pytest o compileall en rojo en la rama de release.
