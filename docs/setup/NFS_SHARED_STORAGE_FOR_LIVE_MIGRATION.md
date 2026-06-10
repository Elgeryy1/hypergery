# NFS como shared storage para live migration

Por qué NFS: en el UAT U10 (2026-06-10) se verificó que **CIFS/SMB no sirve**
para shared-storage live migration — el handoff del write-lock de imágenes de
QEMU falla sobre SMB (durable handles del servidor) y la VM queda pausada en
origen sin poder reanudar en destino. El preflight de HyperGery rechaza
CIFS/SMB en modo shared desde esta rama. NFS tiene semántica de locks
correcta y además libvirt lo autodetecta como FS compartido (sin necesidad de
`shared_filesystems`).

## 1. Export NFS en el NAS (QNAP)

En la interfaz del QNAP:
1. **Panel de control → Servicios de red y archivos → Win/Mac/NFS → Servicio NFS**:
   activar **NFS v4** (y v3 si lo pide la red).
2. **Panel de control → Privilegios → Carpetas compartidas** → carpeta para
   las VMs compartidas (p. ej. `Gerard/hypergery/vms-shared`) → **Editar
   permisos → Acceso de host NFS**: añadir las IPs de los dos hosts
   (`192.168.1.44` y `192.168.1.73`) con acceso lectura/escritura,
   `squash`: *no mapear* (no_root_squash si qemu corre como root; con
   libvirt-qemu basta rw + mapeo a un uid con escritura).

## 2. Montaje en AMBOS hosts — misma ruta absoluta

> La ruta debe ser idéntica en los dos. Recomendada: `/mnt/hypergery-nas`
> (si ya hay un CIFS ahí, usar otra como `/mnt/hypergery-nfs` — EN AMBOS).

```bash
sudo mkdir -p /mnt/hypergery-nfs
sudo mount -t nfs4 192.168.1.150:/Gerard/hypergery/vms-shared /mnt/hypergery-nfs
# Persistente, en /etc/fstab:
# 192.168.1.150:/Gerard/hypergery/vms-shared  /mnt/hypergery-nfs  nfs4  rw,hard,_netdev  0  0
```

Opciones recomendadas: `nfs4`, `rw`, `hard` (nunca `soft` para discos de VM),
`_netdev`. Verificar el tipo: `stat -f -c %T /mnt/hypergery-nfs` → debe decir
`nfs`/`nfs4`.

## 3. Probar escritura desde ambos hosts

```bash
# en cada host:
touch /mnt/hypergery-nfs/.probe-$(hostname) && ls -la /mnt/hypergery-nfs/
# y como usuario qemu (clave para libvirt):
sudo -u libvirt-qemu touch /mnt/hypergery-nfs/.probe-qemu-$(hostname)
```

Las cuatro sondas deben crearse sin error; bórralas después.

## 4. Probar que qemu arranca una VM hgtest desde ahí

```bash
hypergery-cli create-vm --name hgtest-nfs --iso <iso-dummy> --ram-mib 512 \
  --vcpus 1 --disk-gb 1 --display vnc --disk-dir /mnt/hypergery-nfs
# poner cache='none' en el disco (virsh edit o el wizard de migración) y:
virsh start hgtest-nfs && virsh domstate hgtest-nfs   # → ejecutando
```

## 5. Repetir U10

Seguir `docs/qa/V1_5_UAT_PLAN.md` § U10 con el disco bajo el montaje NFS:

```bash
hypergery-cli v1 migrate-live --vm hgtest-u10 \
  --target qemu+ssh://gery@192.168.1.73/system --shared-storage --confirm
```

Recordatorio de prerequisitos ya configurados en el laboratorio (2026-06-10):
`/etc/hosts` del escritorio resuelve el hostname del portátil; CPU de la VM de
prueba `qemu64` sin `svm` (hosts AMD↔Intel); `cache='none'` en el disco. Con
NFS no hace falta `shared_filesystems` en qemu.conf (autodetectado), pero la
entrada existente no estorba.

Registrar el resultado (downtime_ms, estados, journal) en
`docs/qa/V1_5_UAT_RESULT.md`. Solo con **U10 PASS** se desbloquea el tag de
v1.5.0.
