# Hub en Docker sobre un NAS o equipo dedicado

El caso de Gerard (y el perfil C del First Run Wizard): el escritorio
HyperGery corre en Ubuntu, y el Hub corre 24/7 en Docker dentro de un NAS.

## Flujo completo

1. **En el PC** — genera la carpeta exportable:
   - Wizard → perfil «Este PC + Hub/Docker en otro equipo dedicado/NAS» →
     «Generar carpeta Docker del Hub», o por CLI:
     ```bash
     hypergery-cli setup generate-docker-bundle --output dist/hypergery-hub-docker
     ```
   - La carpeta es autocontenida: `docker-compose.yml`, `Dockerfile`, el
     código del Hub, `.env.example`, `README_SETUP.md` y `SECURITY.md`.
     No se ejecuta nada de Docker al generarla.
2. **Copia la carpeta al NAS**, por ejemplo:
   ```bash
   scp -r dist/hypergery-hub-docker usuario@nas:/share/Contenedores/
   ```
3. **En el NAS**:
   ```bash
   cd /share/Contenedores/hypergery-hub-docker
   cp .env.example .env
   # edita .env: puerto, carpeta de datos y HYPERGERY_HUB_TOKEN
   # (genera el token: python3 -c "import secrets; print(secrets.token_urlsafe(32))")
   docker compose up -d
   curl http://127.0.0.1:8765/health    # → {"status": "ok", ...}
   ```
   Si dejaste el token vacío, el Hub genera uno:
   `docker exec hypergery-hub cat /data/hub_token`.
4. **De vuelta en HyperGery** (wizard o CLI): pega la URL
   (`http://IP-del-NAS:8765`) y el token, y prueba la conexión:
   ```bash
   hypergery-cli setup test-hub --url http://IP-del-NAS:8765 --token TU_TOKEN
   ```
   Estados posibles: `ok` (todo bien), `auth_error` (Hub vivo, token mal),
   `unreachable` (red/servicio). Al guardar, la config queda con permisos
   0600 en `~/.config/hypergery/config.json`.

## Seguridad

- El puerto del Hub debe ser alcanzable **solo** desde tu LAN privada o tu
  VPN (WireGuard/Tailscale). Nunca lo abras en el router sin TLS delante
  (reverse proxy con certificado) — y aun así, mejor VPN.
- El token es un secreto: vive en el `.env` del NAS y en la config 0600 del
  PC. `hypergery-cli setup status` nunca lo imprime.
- Política completa: `docs/security/CONNECTIVITY_POLICY.md` y
  `docs/HUB_SECURITY.md`.
