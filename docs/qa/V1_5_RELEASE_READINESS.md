# Release readiness — HyperGery v1.5.0-rc (1.5.0rc0)

- **Fecha:** 2026-06-10 · **Rama:** `release/v1.5.0-rc` (desde `main` @ v1.0.1)

## Ramas integradas (en orden)

| # | Rama | Cómo |
|---|---|---|
| 1 | `feat/v1.1-real-libvirt-hygiene` (arrastra toda la cadena v1.1) | merge |
| 2 | `fix/v1.1-packaging-uat` (U1 PASS) | merge (divergencia resuelta sin conflictos) |
| 3 | `feat/v1.2-hub-security` | merge |
| 4 | `feat/v1.3-backups-templates` | merge |
| 5 | `feat/v1.4-orchestration-telemetry` | merge |
| 6 | `feat/v1.5-prep-migration-engine` | merge |
| 7 | `feat/v1.5-live-migration` | merge |
| 8 | Fixes de auditoría + hardening | **cherry-picks selectivos**: `765ca3a` (0026/0027), `65ec7d3` (0021/0013), `e15a8e3` (docs), `e5f3750` (0028 journal), `d21922a` (0029), `d297f00` (0019/0023), `2380052` (tests round 2), `85096cd` (docs cobertura), `a79d0eb` (hardening 0014/0022/0030/0020 + docs/security) |

**Excluido conscientemente:** `18f25a3` (fix HG-BUG-0025, solo aplica a
`gpu_passthrough.py`, que no entra) y las 3 clases de test GPU de
`test_post_night_audit.py` (anotado en el propio fichero).

## Features incluidas

.deb instalable (U1 PASS heredado) · **First Run Setup Wizard** (nuevo en esta
RC: perfiles, bundle Docker del Hub exportable a NAS, prueba de conexión,
diagnóstico libvirt sin sudo, CLI `setup …`) · Hub seguro v1.2 · backups +
verifier v1.3 · orquestación + telemetría + companion v1.4 · live migration
v1.5 con journal anti double-active · hardening completo (0014/0022/0030/0020)
· docs de seguridad (threat model, connectivity policy, readiness).

## Features EXCLUIDAS (verificado en el árbol)

- `android/` — no existe; `.github/workflows/android.yml` — no existe.
- `v1/gpu_passthrough.py` — no existe; cero referencias en código.
- `docs/research/V2_0_RESEARCH.md` — no entra; v2.0 no se anuncia.
- El .deb tampoco contiene nada de GPU/Android (verificado con dpkg-deb).

## Validación (2026-06-10)

- `python -m compileall -q hypergery_ubuntu` → OK
- `QT_QPA_PLATFORM=offscreen pytest -q` → **877 passed, 7 skipped**
  (851 al integrar + 26 tests nuevos del First Run Setup)
- `./scripts/build-deb.sh` → `dist/hypergery_1.5.0~rc0_all.deb` (189 KB);
  `dpkg-deb --info/--contents`: Version 1.5.0~rc0, 3 binarios en /usr/bin,
  .desktop, .svg, copyright; sin __pycache__, sin GPU/Android.
- `hypergery --version` / `hypergery-cli --version` / `hypergery-agent
  --version` → `1.5.0rc0` (editable reinstalado).
- needsRealLibvirt: no ejecutada hoy; último resultado real conocido 8/8 PASS
  (la parte GPU de esa suite queda en su rama).

## Heredado / pendiente

- **U1 packaging: PASS real** (v1.1, `docs/qa/V1_1_UAT_RESULT.md`). El .deb de
  esta RC sale del mismo script con la versión nueva; reinstalación real con
  sudo queda como smoke opcional.
- **Hardening: PASS** (`docs/security/V1_5_SECURITY_READINESS.md`); bandit no
  disponible offline.
- **Flujo OFICIAL (Hub-mediated): HM1–HM4 PASS** en hardware real
  (`docs/qa/V1_5_HUB_MIGRATION_UAT_RESULT.md`, 2026-06-10) — Hub Docker del NAS
  redesplegado con la RC, job creado/autorizado, paquete por staging,
  checksums e2e (corrupción rechazada), origen nunca liberado solo, destino
  obedece al Hub, sin token no hay migración. **Este es el gate de release y
  está superado.**
- **Modo avanzado (live directa): U11/U12 PASS**; U10 requiere NFS y **ya no
  bloquea** (decisión de arquitectura 2026-06-10). `docs/qa/V1_5_UAT_RESULT.md`.
- First Run Wizard: lógica y reglas de seguridad testeadas offscreen (26
  tests); pase visual humano recomendado en el primer arranque real.

## Veredicto

**v1.5.0 RC PREPARADA y con el gate de release SUPERADO** en
`release/v1.5.0-rc`: el flujo oficial mediado por el Hub pasa HM1–HM4 en
hardware real. **Técnicamente lista para tag/release de v1.5.0** cuando Gerard
lo autorice (el tag/release sigue siendo su decisión explícita; este informe
no lo ejecuta).
