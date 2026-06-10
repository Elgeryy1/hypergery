# Política de conectividad de HyperGery

- **Fecha:** 2026-06-10 · **Aplica a:** v1.x en adelante
- **Resumen en una línea:** HyperGery conecta máquinas **tuyas**, en redes
  **tuyas o autorizadas**, con canales **autenticados y cifrados**. Nada más.

## Lo que HyperGery NO hace (y no hará)

- **No implementa evasión de cortafuegos** ni técnicas para "saltarse" filtros
  de red.
- **No implementa DNS tunneling** ni ningún transporte encubierto sobre
  protocolos ajenos.
- **No camufla su tráfico** como aplicaciones de terceros (Teams, Zoom, etc.).
- **No intenta eludir políticas de redes educativas, corporativas o públicas**
  (AP isolation, puertos filtrados, portales cautivos…). Si una red bloquea el
  tráfico, la respuesta es usar una red propia o pedir autorización, no un
  bypass.
- **No borra rastros**: el Hub y el API auditan los accesos (incluidos los
  fallidos) y esa auditoría es parte del diseño.

Cualquier documento histórico que explore ideas de este tipo queda
**descartado y no implementado**; si se encuentra lenguaje así en docs
antiguas, debe reescribirse apuntando a esta política.

## Conexiones remotas permitidas

| Canal | Uso en HyperGery |
|---|---|
| VPN propia / WireGuard / Tailscale | acceso al Hub y al API v1 desde fuera de la LAN |
| SSH autorizado (claves) | `qemu+ssh://`, túneles `ssh -L` |
| HTTPS/TLS (reverse proxy) | Hub/API expuestos fuera de localhost |
| `qemu+ssh://` y `qemu+tls://` | migración de VMs (la única vía; `qemu+tcp://` se **rechaza** en código) |
| Reverse tunnel autorizado | solo sobre SSH/VPN propios |

## Reglas operativas

1. **Toda conexión multi-host es consentida y autenticada**: token Bearer
   obligatorio por defecto en Hub y API v1; `--no-auth` existe solo de forma
   explícita, marcado DANGEROUS y con warning en runtime.
2. **Por defecto se escucha en `127.0.0.1`**; exponer en `0.0.0.0` es una
   decisión explícita (flag/env, como en el contenedor Docker del NAS) y debe
   ir detrás de TLS o VPN (ver `docs/HUB_SECURITY.md`).
3. **Guest/Classmate no usa recursos de Gerard sin permiso explícito**: RBAC
   con permisos por rol, scoping por lab y acciones destructivas fuera del
   alcance de Guest.
4. **Las operaciones destructivas requieren confirmación** (force-off,
   delete, undefine, apply de planes, migración).
5. **La live migration exige preflight + journal anti double-active +
   `--confirm`**, y solo sobre `qemu+ssh://`/`qemu+tls://`.
