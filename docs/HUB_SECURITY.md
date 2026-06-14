# Seguridad del Hub y del API v1 (v1.2)

## Autenticación por token (obligatoria)

Desde v1.2 el Hub (registry, puerto 8765) y el API v1 (puerto 8799) exigen
`Authorization: Bearer <token>` en todas las peticiones excepto `GET /health`.

### Hub

- El token se resuelve en este orden: `HYPERGERY_HUB_TOKEN` (entorno) → fichero
  `hub_token` junto a la base de datos (se genera automáticamente con permisos
  `0600` la primera vez).
- Los clientes (UI, CLI, agente) lo toman de `HYPERGERY_HUB_TOKEN` o del campo
  `hub_token` de `~/.config/hypergery/config.json` (el fichero se guarda con
  `0600`). El agente admite además `registry_token` en `agent.json`.
- Ver el token y la información de pareado: `hypergery-cli hub pairing-info`.
- Fallos de autenticación: `401`; tras 10 fallos por IP en 60 s la IP queda
  bloqueada temporalmente (`429`). Cada rechazo se audita en la tabla de
  eventos del Hub (`kind=auth_failure`).
- `--no-auth` desactiva la autenticación. **Solo** para una LAN de confianza y
  queda registrado en el log con un aviso.
- En Docker: `docker exec hypergery-hub cat /data/hub_token`.

### API v1

- Token de propietario: `HYPERGERY_API_TOKEN` o `~/.local/state/hypergery/api_token`
  (auto-generado, `0600`). Identidad implícita: SuperAdmin.
- Tokens por usuario (RBAC): `hypergery-cli v1 guests token <user_id>` emite un
  token ligado a ese usuario (`--revoke` lo revoca). Cada petición se autoriza
  con los permisos efectivos del usuario (`v1/rbac.py`) y se audita en el log
  estructurado (categoría `guest`).
- Mapa de permisos: lecturas → `can_view_labs`; `/guests` → `can_manage_guests`;
  `POST /orchestrator/dry-run` → `can_use_remote_compute`;
  `POST /teleport/*` → `can_teleport`. Sin permiso → `403` (auditado).
- El API sigue negándose a escuchar fuera de loopback sin `--allow-remote`.

## TLS — reverse proxy

El token viaja en claro por HTTP. Dentro de la LAN de confianza puede ser
aceptable; para cualquier otro escenario pon el Hub detrás de TLS:

### Caddy (recomendado por simplicidad)

```caddyfile
hub.example.lan {
    reverse_proxy 127.0.0.1:8765
}
```

### nginx

```nginx
server {
    listen 443 ssl;
    server_name hub.example.lan;
    ssl_certificate     /etc/ssl/hub.crt;
    ssl_certificate_key /etc/ssl/hub.key;
    client_max_body_size 0;           # las subidas de paquetes son grandes
    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_request_buffering off;  # streaming de discos
    }
}
```

Configura entonces `hub_url` con `https://...` (los clientes usan TLS de serie
vía `urllib`).

## Conectividad legítima fuera de la LAN

Nunca expongas el Hub directamente a Internet. Opciones soportadas:
WireGuard/Tailscale/VPN, túnel SSH (`ssh -L 8765:127.0.0.1:8765 nas`), o el
reverse proxy TLS anterior dentro de una red privada. Nada de evasión de
NAT/cortafuegos.

## Pairing seguro (app Android / segundo host)

1. En el equipo del Hub: `hypergery-cli hub pairing-info` (muestra URL, token y
   un `pair_uri`). El token es un secreto: compártelo solo por un canal seguro.
2. En el otro extremo, exporta `HYPERGERY_HUB_URL` y `HYPERGERY_HUB_TOKEN`, o
   guarda `hub_url`/`hub_token` en `~/.config/hypergery/config.json`.

## Nota sobre la IP `192.168.1.150` (HG-BUG-0020)

La dirección `192.168.1.150` que aparece en scripts, tests y documentación es
el Hub del **NAS privado de Gerard** en su LAN doméstica — un valor por defecto
local, **no** un valor universal ni un secreto (es una dirección RFC 1918 sin
valor fuera de esa red). Los launchers la usan solo como *default*
parametrizable: `start-second-host.sh` acepta el URL por argumento o por
`HYPERGERY_HUB_URL`, e `install-agent-user-service.sh` acepta `--hub-url` o
`HYPERGERY_HUB_URL`. En cualquier otro despliegue, configura tu propio URL.
