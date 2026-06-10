# HyperGery v1.5.0 — Release Candidate (1.5.0rc0)

> **Estado: RELEASE CANDIDATE.** No hay tag ni release final hasta que los UAT
> físicos de live migration (U10–U12) estén en PASS. Esta RC se puede instalar
> y probar; no se publica.

v1.5.0 integra TODO lo estable desde v1.0.1: las versiones v1.1, v1.2, v1.3,
v1.4 y v1.5 en una sola release, más el hardening pre-release.

## Incluido

- **Paquete Debian instalable** (`dist/hypergery_1.5.0~rc0_all.deb`): tres
  comandos (`hypergery`, `hypergery-cli`, `hypergery-agent`, todos con
  `--version`), lanzador de escritorio, icono, About; desinstalar conserva los
  datos de usuario. Procedimiento U1 validado en real (PASS, v1.1).
- **First Run Setup Wizard** (nuevo): asistente de primera ejecución
  (`hypergery --first-run`, `hypergery-cli setup wizard`) con perfiles de uso
  (solo PC / Hub local en Docker / Hub en NAS dedicado / cliente), bundle
  Docker exportable del Hub, comprobación de almacenamiento, diagnóstico de
  libvirt sin sudo y prueba de conexión al Hub. CLI: `setup status |
  generate-docker-bundle | test-hub | reset-first-run`.
- **Hub seguro (v1.2)**: token Bearer obligatorio, comparación constant-time,
  RBAC con scoping por lab, rate-limit anti fuerza bruta, audit log, ficheros
  0600, pairing (`hub pairing-info`), docs TLS/VPN.
- **Backups y plantillas (v1.3)**: políticas de backup al NAS con retención,
  Backup Verifier (restaura y arranca de verdad), snapshot branching, tags,
  presupuestos por lab.
- **Orquestación y telemetría (v1.4)**: telemetría por heartbeat, dashboard de
  salud, orchestrator que solo aplica con confirmación, API companion con
  acciones seguras (start/ACPI/snapshot).
- **Live migration (v1.5)**: migración en caliente sobre `virsh migrate`
  (solo `qemu+ssh://`/`qemu+tls://`; `qemu+tcp://` rechazado), preflight,
  rollback con origen intacto, cancelación, journal persistente
  anti double-active, downtime medido, CLI `v1 migrate-live --confirm`,
  canal de progreso con long-poll.
- **Hardening pre-v1.5**: cierre de consola sin congelar la UI (HG-BUG-0014),
  Centro de control humanizado con «Salud del sistema» y «Operaciones»
  (HG-BUG-0022), `v1/api.py` modularizado fase 1 (HG-BUG-0030), launchers del
  Hub parametrizados (HG-BUG-0020), threat model y política de conectividad
  (`docs/security/`).
- UI del Centro de control con resúmenes en español; JSON solo bajo
  «Ver detalles técnicos».

## Fuera de esta release (a propósito)

- **Android companion (v1.6)**: queda en su rama; sin CI activado, sin APK,
  sin UAT (U13).
- **GPU passthrough (v1.7)**: queda en su rama; pendiente de U14 (2ª GPU).
- **v2.0 research**: solo investigación, nunca fue feature.

## Condición de publicación

`v1.5.0` final **solo** se taggea y publica cuando U10 (live migration con
storage compartido), U11 (block migration) y U12 (cancelación) pasen en los
dos equipos físicos. Plan exacto: `docs/qa/V1_5_UAT_PLAN.md`.
