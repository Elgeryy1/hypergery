# Plan UAT v1.5 — migración mediada por el Hub (flujo oficial)

- **Bloquea:** el tag/release de v1.5.0 (junto con la suite automática).
- **Arquitectura:** `docs/architecture/HUB_MEDIATED_MIGRATION.md`.
- **Entorno:** PC origen + portátil destino, ambos con agente emparejado al
  Hub Docker del NAS (192.168.1.150:8765). Solo VMs `hgtest-*`.
- **Nota:** parte de este flujo YA tiene UAT real en verde: teleport por Hub
  Transfer (smoke 2-hosts 2026-06-06) y migración con safe-resume
  (`docs/qa/V1_0_1_UAT_RESULT.md`, 5/5). Este plan lo re-valida sobre la RC.

## Preparación

```bash
# Hub vivo y con token:
hypergery-cli hub health --hub-url http://192.168.1.150:8765
hypergery-cli hub pairing-info          # token (SECRETO)
# Agentes corriendo y online en ambos hosts:
scripts/install-agent-user-service.sh   # o setsid nohup ... agent run
hypergery-cli hub vms --hub-url ...     # ambos hosts reportando
# VM de prueba:
hypergery-cli create-vm --name hgtest-hm1 --iso <iso-dummy> --ram-mib 512 --vcpus 1 --disk-gb 1
```

## HM1 — migración apagada por el Hub (hub transfer)

```bash
hypergery-cli migrate remote hgtest-hm1 --transfer hub \
  --source-host-id <id-pc> --target-host-id <id-portatil>
hypergery-cli migrate status --migration-id <id> --hub-url http://192.168.1.150:8765
```

**PASS si:** estados `preflight→packaging→uploaded→waiting_target→importing→done`
visibles en el Hub; paquete en el staging del Hub (`hub packages`); el destino
importa con UUID/MAC nuevos; **el origen sigue definido e intacto** (se borra
a mano solo tras verificar el destino); checksums validados (probar también
HM1-neg: corromper un byte del paquete en staging → import FALLA y destino
limpio).

## HM2 — VM encendida por el Hub (teleport save/restore)

```bash
hypergery-cli v1 teleport --vm hgtest-hm2 --target-host <id-portatil> --confirm
```

**PASS si:** la VM se guarda en origen, viaja por Hub/NAS, **continúa donde
estaba** en destino (no reboot); el origen no queda corriendo a la vez en
ningún momento; si se fuerza un fallo de envío, el origen **se reanuda solo**
desde su estado guardado.

## HM3 — autorización y auditoría

```bash
# Sin token (o token malo): TODO debe dar 401 y quedar auditado.
curl -s -o /dev/null -w '%{http_code}\n' http://192.168.1.150:8765/migrations/x   # → 401
hypergery-cli hub packages --hub-url ...    # con token: staging visible
```

**PASS si:** sin token no hay job/subida/bajada (401) y los rechazos aparecen
en los eventos del Hub.

## HM4 — el Hub coordina, los hosts obedecen

**PASS si:** el destino NO importa nada hasta que el comando aparece en su
cola (parar el agente del destino → el job se queda en `waiting_target`;
arrancarlo → procesa); el comando caduca por TTL si nadie lo recoge.

## Limpieza

Como siempre: solo `hgtest-*`, en ambos hosts y en el staging del Hub
(`hub cleanup-packages` o borrado del paquete del job).
