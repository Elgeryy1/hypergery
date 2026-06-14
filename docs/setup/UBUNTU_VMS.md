# Crear VMs Ubuntu/Linux fiables (blocker B2)

Guía para que instalar Ubuntu desde la UI de HyperGery sea fiable, y qué mirar
si el instalador se cuelga.

## Perfil recomendado

En el asistente «Crear máquina» → Sistema operativo → **«Linux / Ubuntu
(recomendado)»**. Genera:

- Chipset **q35**, firmware **BIOS** (probado y fiable para Ubuntu 22.04/24.04;
  no depende de OVMF).
- Disco **virtio** (`vda`), red **virtio**, vídeo **qxl**, ratón tablet USB.
- CD-ROM SATA con la ISO, orden de arranque `cdrom` → `hd`.
- Recursos mínimos recomendados: **2048 MiB RAM**, **15 GiB disco**, 2 vCPU.

Hay también **«Linux / Ubuntu (UEFI)»** si necesitas arranque UEFI (requiere
`ovmf`; el asistente avisa si falta).

## Validación de la ISO

Antes de crear, HyperGery comprueba la ISO (tamaño razonable, extensión,
firma ISO 9660 `CD001`). Una ISO inexistente o ilegible **bloquea** la
creación con un error claro; una sospechosa (muy pequeña, sin firma) muestra
un **aviso** pero deja continuar.

## Si el instalador se cuelga (troubleshooting)

1. **Pantalla negra al principio:** normal unos segundos. Espera 30–60 s. Pulsa
   «Abrir consola» (consola VNC integrada) y mira el estado de la VM
   (encendida/apagada) en la barra de la máquina.
2. **Se queda en el menú de GRUB o en "Try/Install":** mueve el ratón / pulsa
   una tecla dentro de la consola para capturar el foco (tecla para soltar:
   la que indica la consola). Algunas ISOs tardan en pintar por qxl.
3. **RAM insuficiente:** el instalador gráfico de Ubuntu necesita ≥ 2 GiB. Si
   pusiste menos, apaga, borra y recrea con 2048 MiB o más.
4. **Disco lleno a mitad:** si el disco virtual es muy pequeño (< 15 GiB) la
   instalación puede fallar al final. Usa ≥ 15 GiB.
5. **ISO corrupta o incompleta:** verifica el sha256 de la ISO frente a la web
   de Ubuntu; una descarga truncada cuelga el instalador.
6. **Cuelgue real reproducible:** apaga a la fuerza desde la UI («Apagar a la
   fuerza»), NO borres la VM, y captura: estado de la VM, qué pantalla mostraba
   la consola, RAM/disco asignados. Eso es lo que hace falta para diagnosticar.

> Apagar/forzar/borrar son acciones con confirmación; cerrar la ventana de la
> consola **no** apaga la VM.

## Verificar el estado en cualquier momento

UI: la barra de acciones de la máquina muestra el estado (ENCENDIDA/APAGADA) y
tiene «Abrir consola». Para diagnóstico secundario por terminal:
`virsh domstate <nombre>` y `virsh dominfo <nombre>` (solo lectura).
