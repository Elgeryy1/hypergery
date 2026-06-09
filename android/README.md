# HyperGery Companion (Android, v1.6)

App nativa (Kotlin + Jetpack Compose) contra el **API v1 seguro** de HyperGery
(token bearer + RBAC). MVP:

- **Pairing seguro**: URL del API + token (de `hypergery-cli hub pairing-info`
  o `hypergery-cli v1 guests token <usuario>`), validado con una llamada
  autenticada real antes de guardarse. Solo por conectividad legítima:
  VPN/WireGuard/Tailscale o HTTPS detrás del reverse proxy de
  `docs/HUB_SECURITY.md`.
- **Dashboard**: hosts con telemetría, VMs por estado, alertas, batería y
  operaciones en curso (long-poll del canal de progreso TD-9 — una live
  migration se ve avanzar en vivo).
- **Inventario de VMs** con **acciones seguras únicamente**: arrancar,
  apagado ACPI y snapshot — todas con diálogo de confirmación; snapshot exige
  además nombre + `confirm:true` en el API. Nada destructivo (force-off,
  delete y undefine no existen en esta app ni en el API companion).

## Compilar

Requiere Android SDK + JDK 17. Sin wrapper binario en el repo (política de no
binarios): usa un Gradle 8.9 local o el CI.

```bash
cd android
gradle test            # unit tests JVM (parsers)
gradle assembleDebug   # APK en app/build/outputs/apk/debug/
```

CI: `.github/workflows/android.yml` compila y sube el APK como artefacto en
cada push que toque `android/`.

## Probar contra el Hub (U13)

1. En el PC: `hypergery-cli v1 api serve` (el API escucha en loopback;
   con `--allow-remote` y VPN puede escuchar en la IP de WireGuard/Tailscale).
2. `hypergery-cli v1 guests token gerard` → token para la app.
3. En el móvil (misma VPN): parear con `http://<ip-vpn>:8799` + token.

## CI (acción manual pendiente)

El token git de esta sesión no tiene scope `workflow`, así que el workflow de
GitHub Actions vive en `android/ci/android.yml`. Para activarlo:

```bash
mkdir -p .github/workflows
git mv android/ci/android.yml .github/workflows/android.yml
git commit -m "ci: enable android workflow" && git push
```
