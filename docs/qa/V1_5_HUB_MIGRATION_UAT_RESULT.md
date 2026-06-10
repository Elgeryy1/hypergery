# HyperGery v1.5 — UAT Result: migración mediada por el Hub (HM1–HM4)

- **Fecha:** 2026-06-10
- **Rama:** `release/v1.5.0-rc`
- **Plan:** `docs/qa/V1_5_HUB_MIGRATION_UAT_PLAN.md`
- **Arquitectura:** `docs/architecture/HUB_MEDIATED_MIGRATION.md`
- **Logs crudos:** `~/hgtest-uat/logs/hm*.txt` en el escritorio

## Resultado global: **HM1 PASS · HM2 PASS · HM3 PASS · HM4 PASS (4/4)**

## Entorno

| | Origen | Destino | Hub |
|---|---|---|---|
| Equipo | gerard-MS-7E26 (192.168.1.44) | gery-Lenovo-ideapad-330S-14IKB (192.168.1.73) | NAS QNAP (192.168.1.150) |
| Rol | PC + agente | portátil + agente | **Hub Docker** `http://192.168.1.150:8765` |
| Código | 1.5.0rc0 | 1.5.0rc0 | imagen RC redesplegada |

**Hub Docker preflight:** se reconstruyó la imagen del Hub con la RC
(`docker build` → `1.5.0rc0`), se envió al NAS (`docker save | gzip` →
`docker load`) y se reinició el contenedor (`docker compose up -d`,
`Up (healthy)`). Verificado: `/health` ok; **auth obligatoria** (`/vms` sin
token → 401); token leído de `/data/hub_token` y configurado en ambos hosts
con permisos 0600 (nunca impreso). Ambos agentes registrados y `online` con
heartbeat (`list_hosts`: los dos hosts, `kvm_ok: true`). Staging, cola de
comandos y eventos operativos.

## HM1 — job hub-mediado básico (PASS)

```bash
hypergery-cli create-vm --name hgtest-hm1 --iso ~/hgtest-uat/dummy.iso \
  --ram-mib 512 --vcpus 1 --disk-gb 1 --display vnc
hypergery-cli migrate remote hgtest-hm1 --transfer hub \
  --source-host-id gerard-MS-7E26 \
  --target-host-id gery-Lenovo-ideapad-330S-14IKB \
  --target-vm-name hgtest-hm1-moved
```

- `package_dir: hub://hgtest-hm1-aaf64e810905` → el paquete viaja por el Hub,
  no host-a-host. `strategy: hub_transfer`.
- Estado final en el Hub: **`done`**; `result.imported: true`,
  `hub_package_deleted: true`, **`source_will_be_deleted: false`**.
- Origen `hgtest-hm1` **sigue definido e intacto** (apagado); destino
  `hgtest-hm1-moved` importado con **UUID nuevo** (`7b0a50ea-…`). Nunca activa
  en dos hosts. VMs reales intactas.

## HM2 — el Hub coordina; arranque tras import (PASS)

```bash
# Agente del destino DETENIDO a propósito antes de lanzar:
hypergery-cli migrate remote hgtest-hm2 --transfer hub ... \
  --target-vm-name hgtest-hm2-moved --start-after-import
```

- Con el agente del destino parado, el job quedó en **`waiting_target`** (el
  Hub guarda el comando en cola; el destino no importa por libre).
- Al **arrancar el agente del destino**, recogió el comando: estado →
  **`done`**, `imported: true`, **`started: true`**; en el portátil
  `virsh domstate hgtest-hm2-moved` → **`ejecutando`**.
- Origen intacto, no borrado. Demuestra: (a) ningún host migra sin job del
  Hub, (b) `start_after_import` arranca el destino correctamente.
- *(Equivalente al UAT real de safe-migration de v1.0.1, revalidado sobre la
  RC por el flujo oficial del Hub.)*

## HM3 — corrupción de paquete (PASS)

```bash
# 1er intento: dd de ceros sobre región ya-cero del qcow2 disperso → NO cambió
#   el contenido (sha igual) → import done. NO era fallo del producto: la
#   inyección fue inefectiva. Se repitió con corrupción efectiva:
# en el staging del Hub: escribir 0xFF en el header del qcow2
#   sha antes=3b107e52f63fab10  después=e6977b9b6d2f0fdb   (cambió)
```

- Con el disco realmente corrupto en el staging del Hub, el agente del destino
  descargó e intentó importar → estado **`failed`** con error humano:
  **«Invalid migration package: Packaged asset checksum mismatch:
  disks/hgtest-hm3b.qcow2»**.
- **Destino limpio** (sin `hgtest-hm3b-moved` definida); **origen intacto**
  (`hgtest-hm3b` apagado en el PC). El checksum sha256 del manifest protege la
  importación de extremo a extremo.

## HM4 — auth / RBAC (PASS)

Contra el Hub vivo:

| Petición | Esperado | Obtenido |
|---|---|---|
| `GET /migrations/x` sin token | 401 | **401** |
| `GET /vms` token incorrecto | 401 | **401** |
| `POST /commands` sin token | 401 | **401** |
| `GET /packages/x` sin token | 401 | **401** |
| `GET /vms` token owner | 200 | **200** |

- **Sin token o token incorrecto no hay migración** (todos los endpoints del
  flujo gateados). El Hub registry usa el token Bearer de propietario.
- El caso **Guest→403** es RBAC del **API v1** (`v1/api.py`,
  `require_permission`), cubierto por la suite automática (`test_security_v12`,
  13 asserts 401/403, incluida escalada de rol). No aplica al Hub registry, que
  es de token único.
- **Sin fuga de tokens**: el token no aparece en `~/hgtest-uat/logs/`, ni en
  los logs de agente, ni en `docs/` (verificado por grep).

## Limpieza (solo hgtest-*)

- Destino (portátil): `hgtest-hm1/2/3/3b-moved` destruidas/undefined, discos
  borrados. `virsh list --all` → solo VMs reales apagadas.
- Origen (escritorio): `hgtest-hm1/2/3/3b` destruidas y borradas
  (delete-vm --delete-disks). `virsh list --all` → solo VMs reales apagadas.
- Staging del Hub: paquetes `hgtest-*` borrados (queda solo el `ubuntu-…`
  preexistente, ajeno a este UAT). Nota: el inventario de VMs del Hub conserva
  registros `hgtest` obsoletos (metadata reportada; caduca al re-sincronizar —
  no son VMs ni paquetes).
- **VMs reales intactas y apagadas** en ambos hosts (escritorio:
  `hg-v06-2host-source`, `hg-v06-e2e-source`, `ubuntu`,
  `ubuntu-migrated-migrated`; portátil: `ubuntu-hub-e2e`, `ubuntu-migrated`,
  `ubuntu-test-v07`). Agentes dejados online (estado normal del laboratorio).

## Veredicto

**El flujo oficial de v1.5 — migración mediada por el Hub Docker del NAS —
PASA su gate completo (HM1–HM4) en hardware real:** job creado y autorizado en
el Hub, paquete subido a su staging y descargado por el destino, checksums
verificados de extremo a extremo (corrupción rechazada), el origen nunca se
libera automáticamente, el destino solo actúa por job del Hub, y sin
token/RBAC no hay migración.

→ **LISTO para tag/release de v1.5.0** desde `release/v1.5.0-rc` cuando Gerard
lo autorice (el tag/release es su decisión; este UAT levanta el bloqueo
técnico). El modo avanzado directo (U11/U12 PASS, U10 requiere NFS) y los gaps
de v1.6 (Hub decisor en dos fases, journal en el flujo Hub) no bloquean.
