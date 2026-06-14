# HyperGery v1.1 — Packaging UAT Fix (U1)

- **Fecha:** 2026-06-10
- **Rama:** `fix/v1.1-packaging-uat` (desde `feat/v1.1-real-libvirt-hygiene`)
- **Alcance:** solo packaging v1.1. Sin tocar `main`, sin merge, sin tag, sin release, sin VMs, sin v1.2+.

## Fallo real detectado por Gerard (primer UAT U1)

Ejecutado con `cwd = .../miversiondevirtualbox/hypergery-ubuntu`:

| Comando | Resultado |
|---|---|
| `./scripts/build-deb.sh` | "No existe el archivo o el directorio" |
| `sudo apt install ./dist/hypergery_1.1.0~dev0_all.deb` | apt no pudo instalarlo |
| `hypergery --version` | OK (`HyperGery 1.1.0.dev0`) |
| `hypergery-cli --version` | OK (`hypergery-cli 1.1.0.dev0`) |
| `hypergery-agent --version` | "no se encontró la orden" |

## Causa raíz

1. **cwd equivocado, no packaging roto.** `scripts/build-deb.sh` y `dist/` viven en la
   **raíz del repo**, no dentro de `hypergery-ubuntu/`. Desde `hypergery-ubuntu/` ni el
   script ni `./dist/…` existen, de ahí los dos primeros fallos. El .deb en sí ya se
   construía correcto y completo.
2. **Instalación editable obsoleta.** El venv `~/.venvs/hypergery` se instaló en editable
   **antes** de que `pyproject.toml` añadiera el entry point `hypergery-agent`
   (commit `a10aa5d`). Los console scripts del venv no se regeneran solos: existían
   `hypergery` y `hypergery-cli` (antiguos, pero leen la versión del código en vivo)
   y faltaba `hypergery-agent`. El código del agente sí soportaba `--version`.

## Correcciones

| Archivo | Cambio |
|---|---|
| `hypergery-ubuntu/scripts/build-deb.sh` | **Nuevo.** Wrapper que delega en el script de la raíz: ahora `./scripts/build-deb.sh` funciona también con `cwd=hypergery-ubuntu/` (el caso exacto del UAT). |
| `scripts/build-deb.sh` | Mensajes humanos si faltan `python3`/`dpkg-deb` o el código fuente; al terminar imprime en stderr la orden `sudo apt install` con la **ruta absoluta** del .deb (stdout sigue siendo solo la ruta, contrato de los tests). |
| `~/.venvs/hypergery` | Reinstalado editable (`pip install -e ./hypergery-ubuntu`): los 3 comandos existen y responden a `--version`. (Acción en la máquina, no en el repo.) |
| `hypergery-ubuntu/tests/test_packaging_uat.py` | **Nuevo** (ver abajo). |
| `hypergery-ubuntu/tests/test_app_identity.py` | El test del build real ahora exige también el nombre exacto del artefacto `hypergery_1.1.0~dev0_all.deb`. |

## Tests añadidos (fallan si U1 vuelve a romperse)

`tests/test_packaging_uat.py`:
- falta `<raíz>/scripts/build-deb.sh`;
- falta el wrapper `hypergery-ubuntu/scripts/build-deb.sh` o no delega/compila (`bash -n`);
- `pyproject.toml` no define exactamente los 3 console scripts
  (`hypergery`, `hypergery-cli`, `hypergery-agent`);
- algún módulo de entrada pierde el guard `if __name__ == "__main__"` (los lanzadores
  del .deb usan `python3 -m`);
- `python3 -m hypergery_ubuntu{,.cli,.agent} --version` no devuelve `<prog> <versión>`
  con exit 0 (cubre el parser del agente).

Ya existentes en `test_app_identity.py` (verificados): el .deb contiene los 3 comandos
en `/usr/bin`, `hypergery.desktop`, `hypergery.svg`, `copyright`, sin `__pycache__`;
ahora además el nombre del .deb.

## Gates ejecutados (2026-06-10)

- `python -m compileall -q hypergery_ubuntu` → OK
- `QT_QPA_PLATFORM=offscreen pytest -q` → **727 passed, 6 skipped**
- Build real desde la raíz **y** desde `hypergery-ubuntu/` → OK
- `dpkg-deb --info` / `--contents` → contiene `/usr/bin/hypergery{,-cli,-agent}`,
  `/usr/share/applications/hypergery.desktop`,
  `/usr/share/icons/hicolor/scalable/apps/hypergery.svg`, app en `/usr/lib/hypergery/`.

Artefacto: `<raíz>/dist/hypergery_1.1.0~dev0_all.deb` (no se versiona; `dist/` está en `.gitignore`).

## Comandos exactos para repetir U1

```bash
cd ~/NAS_Gerard/proyectos_hacen_bulto_en_CV/miversiondevirtualbox   # ← raíz del repo
./scripts/build-deb.sh
sudo apt install ./dist/hypergery_1.1.0~dev0_all.deb
hash -r            # refresca la caché de comandos del shell
hypergery --version
hypergery-cli --version
hypergery-agent --version
```

Nota: si el venv `~/.venvs/hypergery` está activado, sus binarios tienen prioridad
sobre `/usr/bin`. Para probar **el paquete instalado**, hazlo sin venv activo o
verifica con `command -v hypergery-agent` que apunta a `/usr/bin/hypergery-agent`.

## Pendiente de probar con sudo (cola UAT humano)

- `sudo apt install ./dist/hypergery_1.1.0~dev0_all.deb` real (resuelve
  `python3-pyside6.qtwidgets | python3-pyside6`; candidato disponible en archive: 6.10.2).
- Lanzador en el menú de aplicaciones con icono.
- `sudo apt remove hypergery` y comprobar que `~/.config/hypergery` y
  `~/.local/share/hypergery` sobreviven.

## Veredicto

**LISTO para U1 real.** Todo lo automatizable está verificado (build desde ambos cwd,
contenido del .deb, 3 entry points con `--version` en editable y vía `python3 -m`).
Solo queda la parte que exige sudo, listada arriba.
