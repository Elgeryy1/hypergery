# HyperGery v1.5 — Resultado del UAT UI-first (sesión 2026-06-10)

- **Rama:** `release/v1.5.0-rc`
- **Probador:** Gerard, desde la UI real (lanzada con `./scripts/dev-run.sh`,
  que ejecuta el código vivo de la rama)
- **Plan de referencia:** `docs/qa/V1_5_UI_USER_ACCEPTANCE_TEST.md`

## Resultado de la sesión

| Prueba (desde la UI) | Resultado | Evidencia |
|---|---|---|
| Crear VM Windows 11 (UEFI + Secure Boot + TPM 2.0) | **PASS** | la VM arranca con OVMF `.ms` (secure=yes), SMM, swtpm 2.0 vivo; el instalador ya no se queja de TPM/arranque seguro |
| Instalador Windows arranca (sin bootloop «Press any key») | **PASS (Gerard: «lo de windows ya va»)** | barrido automático de «espacio» vía `virsh send-key` (independiente del display); verificado con la ISO real hasta «Seleccionar idioma» |
| **Migración EN VIVO de VM encendida desde la UI** | **PASS (Gerard: «FUNCIONÓ»)** | flujo completo: CPU compatible → URI autorrellenada del Hub → carpeta del destino autorizada EN el receptor → disco destino pre-creado solo → migración con downtime de ms; prueba automatizada previa: ok:true, 395 ms |
| Hosts visibles entre sí vía Hub | **PASS** | agentes como servicio persistente en ambos; destino autorrellenado `qemu+ssh://gery@192.168.1.73/system` |

## Bugs reales encontrados y arreglados HOY (cronología de commits)

| Commit | Bug | Causa raíz |
|---|---|---|
| `ec4aee7` | live migration pedía «lo de qemu» a mano | el Hub no guardaba ssh_user/IP del agente; ahora el agente los reporta y la URI se autorrellena |
| `378e417`→`3db0d25` | Windows clavado en «Press any key» | la ventana del prompt dura ~5 s tras la init de OVMF; y el primer nudge iba por consola VNC (rota con SPICE, el display por defecto) → ahora `virsh send-key` barrido 1,5–18 s, cualquier display |
| `a6820b6` | «no storage pool with matching target path» | libvirt no crea el disco destino; ahora se pre-crea por SSH con su tamaño |
| `69a7b93` | la contraseña debía pedirla EL RECEPTOR (diseño Gerard) | comando Hub `prepare_storage`: el agente receptor muestra zenity+sudo EN SU PANTALLA; la contraseña nunca viaja por la red |
| `2ff10df` | «Source and target image have different sizes» | `qemu-img info` sin `-U` falla con la VM encendida → tamaño 0; + la CPU migratable emitía qemu64 CON svm (rompía AMD→Intel) |
| `a23933e` | **crash de la app** tras encender VM con ISO; migración muerta al 3,6% (`TSC mismatch`/`XSAVE`); fallo por CD conectado | QThread liberado dentro de su `finished` (segfault PySide); preflight ahora BLOQUEA cross-vendor con CPU del host consultando `virsh capabilities` de ambos; el wizard ofrece expulsar el CD |

Anteriores de la misma jornada: `df38824` (destinos desde el registro del Hub,
sin exigir visibilidad directa), `e693689` (el .deb auto-arranca el agente),
`484ab30` (diálogo de creación estilo VirtualBox), `2f44846` (perfiles
Windows 11/Ubuntu, QtNetwork en el .deb).

## Lecciones operativas (para no repetir)

- **Gerard lanza la app con `./scripts/dev-run.sh`** → ejecuta el código vivo
  de la rama checked-out; los fixes llegan sin reinstalar. El .deb instalado
  (icono del menú) sí requiere `apt install --reinstall` — fue la causa de
  varios «sigue sin funcionar».
- VMs que deban migrar EN VIVO entre el PC (AMD) y el portátil (Intel) deben
  crearse con **«Preparar para migración en vivo (CPU compatible)»**; las
  creadas con la CPU del host quedan bloqueadas por el preflight con un
  mensaje claro (no a mitad de migración).
- El CD/ISO conectado debe expulsarse antes de migrar (el wizard lo ofrece).

## Pendiente para mañana (refinamiento)

1. Pasar el checklist completo A–G del UAT UI-first y marcar el veredicto.
2. UAT con el **.deb instalado** (lo que vería un usuario final), no solo con
   el script.
3. `sudo loginctl enable-linger` en ambos equipos (agentes sin sesión abierta).
4. Progreso en vivo fino en el modo B del wizard (streaming de fases, hoy
   muestra preflight→resultado con downtime).
5. Opcional avanzado: NFS compartido para shared-storage (U10 real).
6. Limpieza menor: `dist/hypergery_1.1.0~dev0_all.deb` viejo; carpeta
   `/home/gerard/hypergery vms` creada en el portátil durante las pruebas
   (decidir si se queda como ruta de migración o se cambia el default de
   almacenamiento a una ruta sin espacios y migrable).
7. Roadmap v1.6 ya declarado: activación en dos fases decidida por el Hub,
   journal extendido al flujo Hub, vista de jobs de migración en la UI.

## Estado del gate de release

El flujo oficial Hub-mediated ya tenía HM1–HM4 PASS; hoy cayó también el
gran pendiente de UX: **migración en vivo utilizable desde la UI por un
usuario normal**. Tag/merge/release siguen siendo decisión explícita de
Gerard tras rematar el checklist UI-first.
