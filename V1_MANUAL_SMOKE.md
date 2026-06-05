# V1_MANUAL_SMOKE — checklist para Gerard (PC casa + NAS + portátil)

Antes: `V1_LOCAL_SMOKE.md` cubre lo local; esto añade lo que necesita
hardware real. Nada de esto borra datos; lo único que escribe es el commit
NAS (metadatos) y el teleport loopback (define una VM nueva local).

## Preparación
- [ ] Encender el PC de casa y reiniciar su agent:
      `systemctl --user restart hypergery-agent` (o el lanzador habitual).
- [ ] Verificar el agent del portátil: `pgrep -af "cli agent run"`.
- [ ] Verificar NAS/Hub: `curl http://192.168.1.150:8765/health`.

## Hosts & Telemetry
- [ ] `python -m hypergery_ubuntu.cli v1 hosts` → portátil online + PC online
      con RAM/roles correctos.
- [ ] `python -m hypergery_ubuntu.cli v1 telemetry` → muestra local sin alertas
      inesperadas.
- [ ] Apagar el agent del PC un minuto → `v1 hosts` lo marca offline y
      `v1 telemetry`/Control Center muestran la alerta host_offline → volver a
      encenderlo.

## Battery
- [ ] `python -m hypergery_ubuntu.cli v1 battery` con el portátil desenchufado
      → percent real y tier correcto.
- [ ] Enchufar el cargador → `charging: true`, tier normal, sin acciones.

## Labs / Network
- [ ] `v1 labs validate` y `v1 network validate` en verde con tus labs reales.
- [ ] UI → Labs: roles y workspace OK (regresión v0.8).

## NAS commit (real, metadatos)
- [ ] `v1 nas commit --lab <lab> --dry-run` → plan correcto.
- [ ] `v1 nas commit --lab <lab> --confirm` → verified:true; revisar el
      paquete en el NAS bajo `labs-commits/`.
- [ ] `v1 nas restore --lab <lab> --commit-id <id> --destination /tmp/hg-restore --confirm`
      → restaura sin tocar nada vivo.

## Orchestrator (con el PC online)
- [ ] `v1 orchestrator plan` → con batería baja (o forzando
      `HYPERGERY_V1_BATTERY_ECO_PERCENT=99` para simular), las VMs pesadas
      apuntan al PC con razón explicada.

## Teleport
- [ ] `v1 teleport dry-run --vm <vm> --target <pc-host-id>` → ok:true.
- [ ] (Opcional, consciente) teleport real:
      `python - <<'PY'` con TeleportEngine suspend_copy_start, o esperar a la
      acción de UI en v1.1. El origen queda PAUSADO: verificar el destino y
      decidir resume/stop del origen.
- [ ] `v1 teleport loopback --vm <vm> --staging-dir /tmp/hg-teleport` →
      aparece `<vm>-loopback` definida localmente; borrarla después si no se
      quiere conservar.

## API
- [ ] `v1 api serve` + abrir `http://127.0.0.1:8799/orchestrator/plan` desde
      el móvil en la LAN (cambiando --host 0.0.0.0 conscientemente y
      cerrándolo después: la API no tiene auth todavía).

## UI
- [ ] Control Center → Refresh All: 8 tabs con datos reales, sin errores.
- [ ] Export Report → JSON correcto.

## Cierre
- [ ] Anotar bugs en V1_KNOWN_BUGS.md.
- [ ] Si todo OK: decidir si v0.9/v1.0 se queda en develop o se planifica
      release (recuerda: sin merge a main ni tag sin decisión explícita).
