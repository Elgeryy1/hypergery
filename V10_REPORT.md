# V10_REPORT — HyperGery v1.0 (visión completa, versión funcional bruta)

Estado por módulo. Leyenda: **functional** (implementado, conectado y
testeado), **experimental** (funciona, marcado como experimental),
**partial** (versión mínima funcional, evoluciona en v1.x),
**blocked** (necesita recurso externo).

| Módulo | Estado | Archivos principales | Pruebas | Notas |
| --- | --- | --- | --- | --- |
| Orchestrator / Auto-Boost | **functional** | `v1/orchestrator.py` | 10 + integración | Reglas: offline, RAM headroom, batería→offload, pesos light/medium/heavy/critical, guest, offline_mode. Explicable (reason + datos + fallback + confianza). Nunca ejecuta. |
| Battery Manager | **functional** | `v1/battery.py` | 8 + integración | Batería real (sysfs+psutil), tiers 50/30/20/10 configurables, eventos de transición, modos disabled/recommend_only/auto_prepare/auto_execute_safe (solo acciones data-safe ejecutables). Probado con la batería real del portátil. |
| Teleport Engine | **functional** (suspend_copy_start **partial**: requiere host remoto vivo) | `v1/teleport.py` | 10 + integración | dry_run y local_loopback validados E2E en tests; suspend_copy_start completo sobre la pipeline de migración v0.8 (suspende→empaqueta→Hub→import→start) con rollback (resume) — pendiente de smoke real con el PC encendido. |
| MemDiff | **experimental** | `v1/memdiff.py` | 6 + integración | Deltas por bloques sha256 sobre estados serializados: snapshot/compare/delta/apply/verify + persistencia con detección de corrupción. Integrado en teleport como estimador. No es live-RAM real. |
| NAS Commit/Restore | **functional** | `v1/nas.py` | 10 + integración | Dry-run por defecto, checksums, staging atómico, restore validado sin sobrescritura. |
| Network Manager | **functional** | `v1/networks.py` | 6 | Redes por lab desde manifests, conflictos CIDR/gateway/DHCP, cross-lab bloqueado salvo allowed_hosts, eventos propios. |
| Guests / RBAC | **functional** (local) | `v1/rbac.py` | 7 + integración | 4 roles, permisos por rol + grants, Guest jamás obtiene remote_compute/manage_guests/change_settings, scoping por lab, audit log. Sin autenticación de red (v1.2). |
| External Nodes / Isard | **partial** | `v1/external_nodes.py` | 5 | Registro manual + health HTTP + loopback + adaptador a HostInfo (el orchestrator ya los considera). Sin conector Isard real (necesita un Isard accesible). |
| Hosts / Telemetry | **functional** | `v1/hosts.py`, `v1/telemetry.py` | 20 | Ver V09_REPORT. |
| Labs v0.9 | **functional** | `labs.py`, `v1/labsx.py` | 21 | Ver V09_REPORT. |
| VM Providers | **functional** | `v1/providers.py` | 9 | Local/Agent/Simulated. |
| Android Hub API | **functional** (LAN, sin auth) | `v1/api.py`, `docs/API_V1.md` | 15 (HTTP real) | Envelope ok/data/error+códigos, 15 GET + 3 POST; /teleport/start exige confirm:true. Auth pendiente (v1.2). |
| UI v1 | **partial** | `ui_qt/main_window.py` (Control Center) | 5 Qt | Página Control Center con 8 tabs conectados a servicios reales (read-only/dry-run) + Export Report. Las pantallas ricas por módulo quedan para v1.1. Dashboard/Hosts/Labs/VMs/Logs/Settings ya existían de v0.7/v0.8. |
| CLI / Commands | **functional** | `v1/cli_v1.py` | 7 | `v1 health/hosts/telemetry/battery/labs validate/nas status|commit|restore/orchestrator plan/teleport dry-run|loopback/network validate/guests list/api serve`. |
| Docs | **functional** | V09/V10 reports, ARCHITECTURE_V1, API_V1, KNOWN_BUGS, NEXT_STEPS, smokes | — | — |

## Pruebas realizadas

- Suite completa: **463 passed + 1 skip (hardware)** en venv;
  **464 OK (70 skips limpios)** en python3 del sistema. 149 tests nuevos.
- Flujos de integración 1–5 del goal §20.2 en verde (ver TEST_RESULTS_V1.md).
- Real: batería del portátil leída por BatteryService; redes del lab real
  validadas; CLI v1 smoke en el portátil.

## Próximos pasos

- v1.1 (bugfix/UX): NEXT_STEPS_V11.md
- v1.2 (seguridad): NEXT_STEPS_V12_SECURITY.md
- Smoke manual con PC de casa: V1_MANUAL_SMOKE.md
