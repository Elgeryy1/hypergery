# HyperGery v1.0.0 — Security Review

> Revisión de seguridad acompañando al bug hunt post-release. Solo análisis; sin cambios de código.

## 1. Modelo de amenaza

HyperGery se despliega en un **laboratorio doméstico/LAN de confianza**: 2 hosts KVM (PC, portátil) + un Hub/registry en el NAS (Container Station), comunicándose por HTTP en la LAN. El usuario es administrador local (grupo `libvirt`/`kvm`) y ejecuta `qemu:///system`.

**Activos:** VMs (discos qcow2, ISOs, snapshots), estado de RAM en teleport, paquetes de migración en staging NAS, base de datos del Hub (inventario de hosts/VMs/comandos).

**Adversarios considerados:**
- (A) Otro equipo/persona en la **misma LAN** sin credenciales (el más realista dada la ausencia de auth).
- (B) Un **paquete de migración malicioso o corrupto** (manifest manipulado).
- (C) Entrada de usuario malformada (nombres de VM/lab/host, rutas).
- (D) Procesos locales no privilegiados (ficheros temporales).

**Fuera de alcance declarado por el proyecto:** atacante con acceso root local; exposición a Internet (el Hub no debe abrirse fuera de la LAN).

## 2. Postura actual — lo que está BIEN

- **0 `shell=True`, 0 `os.system`, 0 `os.popen`.** Todo `subprocess` usa **listas de argumentos** (`backend.run`, `doctor`, `screenshot`, `external_nodes`) → **sin command injection** por construcción.
- **0 deserialización insegura:** no hay `eval`, `exec`, `pickle`, `yaml.load`, `tarfile`, `zipfile`, `extractall`. Los paquetes son **árboles de ficheros + JSON**, no archivos comprimidos auto-extraíbles.
- **Path traversal cerrado en paquetes** (adversario B): `migration.safe_package_member()` rechaza vacío, absolutos, `..`, escapes del root y symlinks; usado en `validate_vm_package`, `import_vm_package` y `state_migration`. El Hub valida con `_safe_package_path()` (rechaza `/`, `.`, `..` en migration_id y escapes en rel_path). El NAS valida ids con `_safe_segment()`.
- **Validación estricta de nombres** (adversario C): `validate_vm_name` (regex + sin `/\..`), `validate_lab_id`, `_host_id` (sin traversal). Nombres usados como subdirectorios y argumentos virsh.
- **XML de libvirt:** se parsea con `xml.etree.ElementTree` y se reconstruye programáticamente (no concatenación de strings con entrada de usuario en los puntos críticos de identidad/UUID/MAC). UUID y MAC se **regeneran** en import para evitar colisiones.
- **Operaciones destructivas opt-in:** `delete_vm(delete_disks=...)`, `nas commit/cleanup` con `--confirm`/`--dry-run`, y el disco solo se borra si está marcado como HyperGery-managed (`backend.py:960-985`).
- **Secretos:** no hay secretos en el repo; `.gitignore` cubre `.env/*.key/*.pem/secrets.*/firebase*.json`. `docker/.env.example` solo tiene puerto y ruta NAS.
- **Lista blanca de comandos del agente** (`ALLOWED_COMMAND_TYPES`): excluye explícitamente delete/undefine/shell/edición de XML.

## 3. Postura actual — lo PENDIENTE (priorizado)

### P0 — Antes/junto a v1.0.1
- **HG-BUG-0001 — Hub sin auth (adversario A).** Cualquier equipo de la LAN puede `POST /commands` (incl. `vm_force_off`), `PUT`/`DELETE` paquetes y `POST /packages/cleanup`. **Mitigación mínima v1.0.1:** bind `127.0.0.1` por defecto (existe `--allow-remote`), banner de arranque "sin auth", y aviso destacado en README. **Solución v1.2:** token compartido en cabecera + TLS opcional (ya en `NEXT_STEPS_V12_SECURITY.md`).
- **HG-BUG-0002 / HG-BUG-0007 — Integridad/seguridad de paquetes de estado.** Falta rollback en fallo (deja la VM origen apagada) y faltan checksums (acepta paquete corrupto). Endurecer en v1.0.1.

### P1 — v1.1
- **HG-BUG-0010 — Límite de recursos en upload.** PUT sin límite de tamaño → DoS por disco lleno. Añadir tamaño máximo y comprobación de espacio.
- **HG-BUG-0006 — Comandos sin expiración.** Replay de comandos peligrosos al reconectar. TTL + descarte de pendientes antiguos.
- **HG-BUG-0021 — Swallow de excepciones** dificulta detectar abusos/fallos de red en el agente. Loguear.

### P2 — backlog
- **HG-BUG-0019 — Temp de screenshot** (0600, best-effort) en `/tmp`; mover a `XDG_RUNTIME_DIR`.
- **HG-BUG-0020 — IP doméstica** como placeholder; usar neutro.
- **Permisos de `config.json`:** se escribe con umask por defecto (`config.save`); no guarda secretos hoy, pero si v1.2 añade token, debe ser `0600`.

## 4. Áreas revisadas específicamente

| Vector | Estado | Nota |
|--------|--------|------|
| Path traversal (paquetes) | ✅ Cerrado | `safe_package_member`, `_safe_package_path`, `_safe_segment` |
| Rutas absolutas en manifest | ✅ Rechazadas | absolutos → error |
| Symlinks en paquetes | ✅ Rechazados | `is_symlink()` antes de resolve |
| Command injection | ✅ N/A | sin shell=True, args en lista |
| XML/libvirt injection | ✅ Mitigado | parseo ET + regeneración UUID/MAC |
| zip/tar/pickle/yaml | ✅ N/A | no se usan |
| Validación VM/lab/host | ✅ Estricta | regex + anti-traversal |
| Hub auth | ❌ Ausente | HG-BUG-0001 |
| Borrados remotos | ⚠️ Sin auth | DELETE paquete sin credencial |
| Upload (recursos) | ❌ Sin límite | HG-BUG-0010 |
| Staging NAS cleanup | ✅ Conservador | skip de activos/recientes, `MIN_CLEANUP_AGE_HOURS`, re-valida traversal |
| Checksums VM package | ✅ sha256+size | `validate_vm_package` |
| Checksums state package | ❌ Ausente | HG-BUG-0007 |
| CORS | N/A | API no pensada para navegador |
| Secretos en repo | ✅ Ninguno | `.gitignore` correcto |
| Fugas en errores | ⚠️ Parcial | rutas absolutas aparecen en mensajes/manifest (info disclosure menor en LAN) |

## 5. Hardening recomendado (orden de impacto)

1. **Auth del Hub** (token + bind loopback por defecto) — corta al adversario A de un golpe.
2. **Checksums + rollback en state migration** — protege integridad y disponibilidad de VMs reales.
3. **Límites de recursos en el Hub** (tamaño de upload, cuota staging) — anti-DoS.
4. **TTL/expiración de comandos** — evita replay de acciones peligrosas.
5. **Logging de fallos silenciados** — visibilidad ante abuso/fallo.
6. **Permisos 0600** para cualquier fichero que en el futuro contenga tokens.

## 6. Prioridades

- **No** hay vulnerabilidad de ejecución remota ni de corrupción silenciosa: **no se requiere hotfix de emergencia**.
- El mayor riesgo práctico es el **Hub sin auth** combinado con **sin límites de recursos**: aceptable solo en LAN realmente aislada. Si el despliegue sale de esa LAN, **pasa a blocker**.
