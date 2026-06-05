# V1_LOCAL_SMOKE — comandos exactos para validar v0.9/v1 en el portátil

Todo es local y no destructivo (dry-run salvo donde se indica `--confirm`).

```bash
cd /mnt/hypergery-nas/proyectos_hacen_bulto_en_CV/miversiondevirtualbox/hypergery-ubuntu
PY=~/.venvs/hypergery/bin/python

# 0. Suite completa
QT_QPA_PLATFORM=offscreen $PY -m pytest -q

# 1. Salud global (hosts + NAS + batería)
$PY -m hypergery_ubuntu.cli v1 health

# 2. Hosts unificados (local + Hub)
$PY -m hypergery_ubuntu.cli v1 hosts

# 3. Telemetría local + alertas (graba historial)
$PY -m hypergery_ubuntu.cli v1 telemetry

# 4. Batería real (tier + acciones recomendadas)
$PY -m hypergery_ubuntu.cli v1 battery

# 5. Labs: validación v0.9
$PY -m hypergery_ubuntu.cli v1 labs validate

# 6. Redes por lab: conflictos CIDR/gateway/DHCP
$PY -m hypergery_ubuntu.cli v1 network validate

# 7. NAS: salud + commit dry-run (no escribe nada)
$PY -m hypergery_ubuntu.cli v1 nas status
$PY -m hypergery_ubuntu.cli v1 nas commit --lab default-lab --dry-run
# Real (escribe en el NAS configurado, solo metadatos del lab):
# $PY -m hypergery_ubuntu.cli v1 nas commit --lab default-lab --confirm

# 8. Orchestrator: plan explicable (nunca ejecuta)
$PY -m hypergery_ubuntu.cli v1 orchestrator plan
$PY -m hypergery_ubuntu.cli v1 orchestrator plan --local-only

# 9. Teleport dry-run sobre una VM real local (no copia nada)
$PY -m hypergery_ubuntu.cli list-vms
$PY -m hypergery_ubuntu.cli v1 teleport dry-run --vm <vm-name>
# Loopback real (exporta+importa en este host con otro nombre):
# $PY -m hypergery_ubuntu.cli v1 teleport loopback --vm <vm-name> --staging-dir /tmp/hg-teleport

# 10. Guests/RBAC
$PY -m hypergery_ubuntu.cli v1 guests list

# 11. API Android-ready (en otra terminal o con & y luego curl)
$PY -m hypergery_ubuntu.cli v1 api serve &
sleep 1
curl -s http://127.0.0.1:8799/health
curl -s http://127.0.0.1:8799/battery
curl -s http://127.0.0.1:8799/orchestrator/plan
curl -s http://127.0.0.1:8799/telemetry
kill %1

# 12. UI: página Control Center
QT_QPA_PLATFORM=xcb $PY -m hypergery_ubuntu  # sidebar → Control Center → Refresh All
```

Esperado: JSON limpio en todos los comandos, sin tracebacks; los errores de
dependencias ausentes (Hub off, NAS sin montar) aparecen como mensajes claros.
