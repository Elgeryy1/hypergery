# First Run Setup Wizard (v1.5)

Asistente de primera ejecución de HyperGery: prepara el modo de uso, el Hub,
el almacenamiento y comprueba la virtualización, sin tocar nada del sistema
sin confirmación.

## Cuándo aparece

- Al arrancar `hypergery` si no existe `~/.config/hypergery/config.json` o si
  `first_run_completed` no es `"true"`.
- Forzado: `hypergery --first-run` o `hypergery-cli setup wizard`.
- Para que vuelva a salir: `hypergery-cli setup reset-first-run`.

Cancelar el asistente nunca bloquea la aplicación: se abre igualmente y el
asistente volverá a ofrecerse en el siguiente arranque.

## Pantallas

1. **Bienvenida.**
2. **Perfil de uso**: A) Solo este PC · B) Este PC + Hub local en Docker ·
   C) Este PC + Hub/Docker en NAS o equipo dedicado · D) Cliente ligero.
3. **Hub y Docker** (según perfil):
   - *Local*: detecta `docker`/`docker compose`, genera la configuración en
     `~/.config/hypergery/hub-docker/` y solo arranca el Hub si confirmas
     explícitamente el `docker compose up -d`.
   - *NAS/dedicado*: genera la carpeta exportable `dist/hypergery-hub-docker/`
     (compose + Dockerfile + código + `.env.example` + `README_SETUP.md` +
     `SECURITY.md`); tras desplegarla en el NAS, pegas URL y token y pruebas
     la conexión. Guía completa: `docs/setup/HUB_DOCKER_ON_NAS.md`.
   - *Cliente*: solo URL + token + prueba de conexión.
4. **Almacenamiento**: por defecto `~/.local/share/hypergery/vms`; ruta
   personalizada o montaje del NAS; comprueba permisos y espacio con un
   fichero sonda que se borra solo — **nunca borra nada tuyo**.
5. **Virtualización**: comprueba `virsh`, `qemu:///system` y los grupos
   `libvirt`/`kvm`. Si falta algo, muestra los comandos para que los ejecutes
   TÚ en una terminal — el asistente jamás ejecuta sudo.
6. **Seguridad**: resumen de las reglas (token siempre, nada a Internet sin
   TLS/VPN, qemu+tcp prohibido, invitados limitados, confirmaciones).
7. **Resumen**: modo, hub_url, almacenamiento, estado de libvirt/Docker,
   exportar informe (JSON, sin token) y Finalizar → guarda la config (0600).

## CLI equivalente

```bash
hypergery-cli setup status                  # estado (nunca imprime el token)
hypergery-cli setup generate-docker-bundle  # carpeta exportable del Hub
hypergery-cli setup test-hub --url http://IP:8765 --token …   # ok/auth_error/unreachable
hypergery-cli setup reset-first-run         # el wizard vuelve a salir
```

## Campos de configuración

`first_run_completed` ("true"/vacío), `setup_profile`
(`solo|local-docker|nas-docker|client`), más los ya existentes `hub_url`,
`hub_token`, `default_vm_storage_path`. Todo en
`~/.config/hypergery/config.json` con permisos 0600.
