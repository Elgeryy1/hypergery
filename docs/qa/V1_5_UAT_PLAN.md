# Plan UAT v1.5 — live migration física (U10–U12)

- **Bloquea:** el tag/release de v1.5.0. La RC existe; publicar no, hasta 3/3 PASS.
- **Equipos:** PC (origen) y portátil (destino), ambos con la RC instalada o
  el venv actualizado, conectados por la LAN privada.
- **Regla de oro:** SOLO VMs `hgtest-*`. Jamás una VM real. Limpieza al acabar.

## Preparación (una vez)

```bash
# En ambos equipos: ssh sin contraseña entre ellos (qemu+ssh) y libvirt activo.
ssh gery@portatil true                          # debe entrar sin preguntar
virsh --connect qemu+ssh://gery@portatil/system version   # desde el PC

# VM de prueba desechable en el PC (pequeña: 1 GiB disco, 512 MiB RAM):
hypergery-cli create-vm --name hgtest-u10 --iso <iso-pequeña> --ram-mib 512 --disk-gb 1
hypergery-cli start hgtest-u10
```

## U10 — shared storage (disco visible en ambos hosts)

```bash
hypergery-cli v1 migrate-live --vm hgtest-u10 \
  --target qemu+ssh://gery@portatil/system --shared-storage --confirm
```

**Preflight esperado:** pasa (VM running, destino alcanzable, RAM suficiente,
sin `<hostdev>`); estrategia shared.
**PASS si:** la VM nunca se apaga; `downtime_ms` en el resultado/progreso es
< 1000; el destino queda `running`; el origen queda undefined tras confirmar;
`virsh list` en ambos hosts lo confirma (**nunca activa en los dos**).

## U11 — block migration (sin storage compartido)

```bash
hypergery-cli v1 migrate-live --vm hgtest-u11 \
  --target qemu+ssh://gery@portatil/system --block-migration --confirm
```

**PASS si:** los discos viajan por el canal de migración (sin NAS), y el resto
igual que U10 (downtime medido, origen limpio, destino running, no double-active).

## U12 — cancelación a mitad

```bash
# Lanza U10 o U11 y, durante el pre-copy (mira /progress o la salida):
virsh domjobabort hgtest-u12          # o Ctrl-C en la CLI
```

**PASS si:** el origen sigue `running` e intacto; el destino queda limpio (sin
VM definida); el estado en `/progress` es `cancelled`; el journal de migración
no deja la VM bloqueada (`hypergery-cli v1 migrate-journal list` vacío o
liberado tras el rollback).

## Comprobaciones transversales (en los tres)

- **Rollback**: ante cualquier fallo, el origen debe quedar como estaba
  (running) y el destino sin restos.
- **No double-active**: en ningún instante `virsh list` muestra la VM running
  en ambos hosts. Tras un switchover confirmado, `backend.start_vm` del origen
  debe negarse si el journal retiene la entrada.
- **downtime_ms**: anotar el valor real de cada migración en el resultado.
- **qemu+tcp**: probar que `--target qemu+tcp://...` se RECHAZA con error
  humano (control negativo, no necesita red).

## Limpieza

```bash
hypergery-cli delete-vm hgtest-u10 --delete-disks    # en el host donde quedara
hypergery-cli delete-vm hgtest-u11 --delete-disks
hypergery-cli v1 migrate-journal list                 # debe quedar vacío
```

## Registro

Anotar resultados (PASS/FAIL + downtime_ms + incidencias) en
`docs/qa/V1_5_UAT_RESULT.md` al ejecutarlos.
