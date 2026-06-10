# HyperGery v1.5 — UAT Result (live migration física U10–U12)

- **Fecha:** 2026-06-10
- **Rama:** `release/v1.5.0-rc` (commit de release `569ed68`)
- **Ejecutor:** agente con supervisión de Gerard (sudo solo manual de Gerard)
- **Plan de referencia:** `docs/qa/V1_5_UAT_PLAN.md`
- **Logs crudos:** `~/hgtest-uat/logs/` en el escritorio (inventarios pre/post y salida JSON de cada migración)

## Resultado global: **U11 PASS · U12 PASS · U10 FAIL (infraestructura CIFS, no producto)**

| Test | Resultado | downtime_ms | Detalle |
|---|---|---|---|
| U11 block migration | **PASS** | **145 ms** | RAM+disco por el canal de migración; destino running; origen undefined; journal limpio |
| U11-bis (accidental, throttle 1 MiB/s) | **PASS** | 426 ms | migración completa también con ancho de banda limitado |
| U12 cancelación | **PASS** | n/a | abortada al 11% de la copia; origen intacto y running; destino limpio; rollback sin errores |
| U10 shared storage | **FAIL — infra** | n/a | RAM al 100%, pero el `cont` final falló por locking de imagen qemu sobre CIFS/SMB; ver análisis |

## Entorno

| | Origen | Destino |
|---|---|---|
| Host | gerard-MS-7E26 (192.168.1.44) | gery-Lenovo-ideapad-330S-14IKB (192.168.1.73) |
| CPU | **AMD** | **Intel** i5-8250U |
| virsh/libvirt | 12.0.0 | 12.0.0 (QEMU 10.2.1) |
| Disco/RAM libres | 218 GB / 23 GiB | 193 GB / 17 GiB |
| Canal | `qemu+ssh://gery@192.168.1.73/system` (clave SSH, sin password) | |
| NAS compartido | `//192.168.1.150/Gerard` montado en `/mnt/hypergery-nas` en ambos (CIFS vers=3.0, `noperm`) | |

VMs de prueba: `hgtest-u10/u11/u12` (512–1024 MiB RAM, disco 1 GiB, **sin SO** —
BIOS loop—, CD expulsado antes de migrar). Ninguna VM real participó.

## Ajustes de infraestructura necesarios (documentados para reproducir)

1. **CPU portable**: origen AMD + destino Intel → las VMs de prueba usan
   `<cpu mode='custom'><model>qemu64</model><feature policy='disable' name='svm'/></cpu>`
   (con `host-passthrough` o con `svm` presente, libvirt rechaza: «la CPU huésped
   no coincide… ausencia de características: svm»). Para VMs reales
   inter-vendor: definir un modelo común.
2. **Resolución de nombres**: el qemu de origen abre el canal NBD contra el
   *hostname* del destino → `/etc/hosts` del origen necesita
   `192.168.1.73 gery-Lenovo-ideapad-330S-14IKB` (sudo de Gerard).
3. **Ruta de disco idéntica en ambos hosts** para block migration: el disco
   destino se pre-crea con `qemu-img create` en la misma ruta
   (`/var/tmp/hgtest-vms/...` en el UAT).
4. Para U10: `shared_filesystems = [ "/mnt/hypergery-nas" ]` en
   `/etc/libvirt/qemu.conf` + reinicio de libvirtd (el magic `smb2`
   0xFE534D42 NO está en la lista de FS compartidos de libvirt 12 — verificado
   contra el código v12.0.0 —, así que la autodetección falla y hace falta el
   override oficial), y `cache='none'` en el disco (requisito estándar de
   coherencia). Con ambos, el check «Migración no segura» pasó.

## U11 — block migration (PASS)

```bash
# preparación
hypergery-cli create-vm --name hgtest-u11 --iso ~/hgtest-uat/dummy.iso \
  --ram-mib 512 --vcpus 1 --disk-gb 1 --display vnc --disk-dir /var/tmp/hgtest-vms
# (CPU qemu64 −svm, CD expulsado, arrancada; disco destino pre-creado por ssh)
hypergery-cli v1 migrate-live --vm hgtest-u11 \
  --target qemu+ssh://gery@192.168.1.73/system --block-migration --confirm
```

Resultado (`u11-migrate-3.txt`): `ok: true`, `status: done`,
**`measured_downtime_ms: 145.0`**, 2 iteraciones pre-copy, 1.18 s total,
2.9 MiB de RAM transferida (resto páginas constantes). Post: destino
`running`, **origen undefined**, `migrate-journal list` → vacío, `virsh list`
en ambos hosts confirma **una sola activa**. VMs reales intactas.

Intentos previos fallidos (ambos con **rollback limpio**: origen running,
destino limpio, journal liberado): CPU svm (ajuste 1) y resolución de nombres
(ajuste 2).

## U12 — cancelación a mitad (PASS)

```bash
# hgtest-u12 con 704 MiB de datos reales en disco (ventana de cancelación)
hypergery-cli v1 migrate-live --vm hgtest-u12 \
  --target qemu+ssh://gery@192.168.1.73/system --block-migration \
  --bandwidth-mibps 20 --confirm &      # copia ~35 s
virsh domjobabort hgtest-u12            # lanzado al 11% (80/704 MiB)
```

Resultado (`u12-cancel.txt`): `status: failed` con error humano
(«La operación se abortó: … Cancelado por cliente»),
`rolled_back_phases: [switchover, transfer]`, `rollback_errors: []`.
Post: **origen `hgtest-u12` running e intacto**, destino sin rastro,
journal vacío, ninguna doble-activa.

## U10 — shared storage (FAIL por infraestructura CIFS)

```bash
# disco movido a /mnt/hypergery-nas/hypergery/uat-v15/hgtest-u10.qcow2
# (la VM ARRANCA desde el NAS con cache='none' — O_DIRECT sobre CIFS OK)
hypergery-cli v1 migrate-live --vm hgtest-u10 \
  --target qemu+ssh://gery@192.168.1.73/system --shared-storage --confirm
```

Cronología de los 5 intentos (`u10-migrate-*.txt`):
1–3. «Migración no segura» → resueltos con cache='none' + `shared_filesystems`
   + reinicio real de libvirtd (el primer reinicio no se aplicó: mismo PID; el
   segundo dejó la línea comentada; el tercero funcionó).
4. *(= intento 5 del log)* **La migración pasó el preflight y transfirió la RAM
   al 100%**; en el `cont` del destino, qemu **no pudo adquirir el write-lock**
   del qcow2: `Failed to get "write" lock`. El origen tampoco pudo
   reanudarse en caliente (mismo lock) y quedó **en pausa**.

**Análisis:** el handoff de locks de imagen de qemu (OFD/byte-range) no es
fiable sobre CIFS/SMB: el servidor QNAP retiene los *durable handles* del
qemu destino muerto y ni el destino ni el origen pueden readquirir el lock
(~2 min de reintentos sin éxito). Es un límite conocido de SMB para discos de
VM; el filesystem soportado para shared storage de migración es **NFS** (o
cluster FS), que libvirt además autodetecta sin override.

**El producto se comportó correctamente en todo momento:**
- qemu/libvirt **protegieron el disco** (rechazo del lock = no hay riesgo de
  doble escritor) — no hubo corrupción (disco verificado legible e intacto).
- El destino quedó limpio (sin VM definida).
- **El journal anti double-active (HG-BUG-0028) retuvo la entrada en vuelo**
  con la VM en estado ambiguo — exactamente su propósito — y solo se liberó
  tras verificar manualmente que el destino estaba limpio
  (`migrate-journal clear`).
- Recuperación segura: `virsh destroy` del qemu pausado (cierre limpio de
  handles SMB) → `virsh start` → la VM volvió a ejecutarse desde el NAS sin
  pérdida (el disco era estático: la VM no tiene SO).

**Conclusión U10:** FAIL de la *infraestructura de storage* (CIFS), no del
código v1.5. Para un U10 PASS real hacen falta exports **NFS** en el NAS
montados en `/mnt/hypergery-nas` en ambos hosts (todo lo demás —
preflight, canal, RAM al 100%, rollback, journal — quedó validado hoy).

## Limpieza realizada (solo hgtest-*)

- Escritorio: `hgtest-u10`/`hgtest-u12` destruidas y borradas (delete-vm; el
  guard de discos no-gestionados se negó correctamente a borrar rutas fuera de
  su control y los ficheros se eliminaron a mano); `/var/tmp/hgtest-vms/` y
  `/mnt/hypergery-nas/hypergery/uat-v15/` vacíos.
- Portátil: `hgtest-u11` destruida/undefined; discos de prueba borrados.
- **VMs reales intactas y apagadas en ambos hosts** (verificado antes y
  después; inventarios en logs): escritorio `hg-v06-2host-source`,
  `hg-v06-e2e-source`, `ubuntu`, `ubuntu-migrated-migrated`; portátil
  `ubuntu-hub-e2e`, `ubuntu-migrated`, `ubuntu-test-v07`.
- Journal de migración: vacío en el cierre.

## Veredicto (decisión de Gerard, 2026-06-10)

- **La live migration real de HyperGery v1.5 funciona**: U11 y U12 PASS en
  hardware físico cross-vendor (AMD→Intel), con downtime de **145 ms**,
  cancelación segura y journal anti double-active verificado en un fallo real.
- **U10 FAIL por infraestructura CIFS/SMB.** Decisión: **SMB/CIFS queda
  declarado NO SOPORTADO para shared-storage live migration** (sí para todo lo
  demás: NAS de datos, staging, backups). El preflight del producto ahora lo
  rechaza con error humano (guard + tests en esta rama); block migration sobre
  CIFS no se ve afectada.
- **La RC sigue válida** (`release/v1.5.0-rc`). **El gate U10 no se relaja:
  NO se hace tag ni release de v1.5.0 hasta repetir U10 con NFS y obtener
  PASS.** Procedimiento: `docs/setup/NFS_SHARED_STORAGE_FOR_LIVE_MIGRATION.md`
  (todo lo demás — CPU portable, /etc/hosts, shared_filesystems, cache=none —
  ya está preparado y validado).
