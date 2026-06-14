# HyperGery v1.1 — UAT Result (packaging U1)

- **Fecha:** 2026-06-10
- **Rama:** `fix/v1.1-packaging-uat` (desde `feat/v1.1-real-libvirt-hygiene`)
- **Ejecutor:** Gerard (UAT humano real, con sudo)
- **Procedimiento de referencia:** `docs/qa/V1_1_PACKAGING_UAT_FIX.md`
  (comandos desde la raíz del repo)
- **Artefacto probado:** `dist/hypergery_1.1.0~dev0_all.deb`

## Resultado: **U1 PASS completo**

## Evidencia

### Instalación

- `sudo apt install ./dist/hypergery_1.1.0~dev0_all.deb` instaló
  `hypergery 1.1.0~dev0` correctamente.
- apt resolvió e instaló las dependencias Qt/PySide6.
- `command -v` confirmó los tres lanzadores del paquete:
  - `/usr/bin/hypergery`
  - `/usr/bin/hypergery-cli`
  - `/usr/bin/hypergery-agent`
- Los tres comandos respondieron a `--version`:
  - `HyperGery 1.1.0.dev0`
  - `hypergery-cli 1.1.0.dev0`
  - `hypergery-agent 1.1.0.dev0`

### Desinstalación

- `sudo apt remove hypergery` desinstaló el paquete sin errores.
- `command -v` tras el remove confirmó que los tres comandos desaparecieron:
  `hypergery`, `hypergery-cli` y `hypergery-agent` removed OK.

### Conservación de datos de usuario (garantía U1)

- `~/.config/hypergery` se conservó: `agent.json`, `config.json`, `config.json.bak`.
- `~/.local/share/hypergery` se conservó: `hub-transfer`, `isos`, `labs`,
  `templates`, `vms`.

### VMs reales intactas

`virsh list --all` conservó las VMs reales tras instalar/desinstalar:

| VM | Estado |
|---|---|
| hg-v06-2host-source | apagado |
| hg-v06-e2e-source | apagado |
| ubuntu | apagado |
| ubuntu-migrated-migrated | apagado |

### Limpieza

- `sudo apt autoremove` retiró las dependencias automáticas Qt/PySide6 sin
  tocar datos de usuario ni VMs.
- (Un typo `sudo appt autoremove` durante la sesión fue irrelevante: el
  comando correcto se ejecutó después.)

## Conclusión

El packaging Debian de v1.1 cumple el contrato completo de U1: build
reproducible, instalación con resolución de dependencias, tres comandos
operativos con `--version`, desinstalación limpia y conservación de datos de
usuario y VMs. Queda cerrado el fallo del primer UAT documentado en
`docs/qa/V1_1_PACKAGING_UAT_FIX.md`.
