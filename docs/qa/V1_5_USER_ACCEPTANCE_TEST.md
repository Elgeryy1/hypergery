# HyperGery v1.5.0 — Prueba de aceptación de usuario (Gerard)

> **Esto NO publica nada.** No hay tag, ni merge a main, ni release de GitHub.
> Es una guía para que Gerard pruebe a mano la RC antes de decidir publicar.
> Ejecuta tú los comandos; cada paso dice **qué esperar** y **cómo parar/revertir**.

## Reglas de seguridad (léelas una vez)

- Solo se usan VMs de prueba: **`hgtest-user-hub`** y **`hgtest-user-live`**.
  Cualquier comando destructivo va con nombre `hgtest-*` explícito.
- **Nunca** se toca ni se borra una VM que no empiece por `hgtest-`. Tus VMs
  reales (`ubuntu`, `ubuntu-migrated-migrated`, `hg-v06-*`, en el portátil
  `ubuntu-hub-e2e`, `ubuntu-migrated`, `ubuntu-test-v07`) se quedan como están.
- Si un paso falla, **PARA**: cada sección tiene su "Si falla / rollback".
- Las dos formas de mover una VM son distintas y honestas:

| | A) **Hub-mediated** (oficial) | B) **Live directa** (avanzada) |
|---|---|---|
| Ruta | Origen → **Hub Docker NAS** → Destino | Origen → Destino (libvirt qemu+ssh) |
| ¿La VM sigue encendida? | **NO de forma continua**: VM apagada se empaqueta/importa; VM encendida usa *teleport* (se congela, viaja, **continúa** donde estaba — hay una pausa breve, no es "sin corte") | **SÍ**: la VM sigue **running** todo el tiempo, downtime ~0,15 s |
| Para qué | el flujo normal, auditado, con checksums, el Hub coordina | laboratorio/avanzado, dos hosts con libvirt directo |
| Bloquea release | **sí (ya PASÓ HM1–HM4)** | no |

> Resumen honesto: si quieres ver la VM **encendida en origen y seguir
> encendida en destino sin reiniciar**, eso es **B (live directa)**. El flujo
> oficial **A** prioriza seguridad/auditoría (checksums, origen intacto hasta
> confirmar), no el "cero corte".

## Entorno (referencia)

- PC origen: `gerard-MS-7E26` (192.168.1.44), usuario `gerard`,
  venv `~/.venvs/hypergery`.
- Portátil destino: `gery@192.168.1.73`, venv `/home/gery/.venvs/hypergery`.
- Hub Docker: `http://192.168.1.150:8765` (contenedor `hypergery-hub` en el NAS).
- ISO de prueba dummy (1 MiB, ya creada en los UAT):
  `~/hgtest-uat/dummy.iso`. Si no existe:
  `mkdir -p ~/hgtest-uat && dd if=/dev/zero of=~/hgtest-uat/dummy.iso bs=1M count=1`

Activa el venv en cada terminal del PC:
```bash
source ~/.venvs/hypergery/bin/activate
```

---

## Test 1 — Instalar el .deb

```bash
cd ~/NAS_Gerard/proyectos_hacen_bulto_en_CV/miversiondevirtualbox
ls -lh dist/hypergery_1.5.0~rc0_all.deb          # debe existir; si no: ./scripts/build-deb.sh
sudo apt install ./dist/hypergery_1.5.0~rc0_all.deb
hash -r
hypergery --version
hypergery-cli --version
hypergery-agent --version
```
**Esperar:** apt instala dependencias Qt/PySide6 sin error; las tres versiones
imprimen `HyperGery 1.5.0rc0` / `hypergery-cli 1.5.0rc0` / `hypergery-agent 1.5.0rc0`.

> Ojo: si tienes el venv activado, sus binarios tapan los de `/usr/bin`. Para
> probar el paquete instalado, abre una terminal SIN venv o comprueba
> `command -v hypergery-agent` → `/usr/bin/hypergery-agent`.

**Si falla / rollback:** `sudo apt remove hypergery` (conserva
`~/.config/hypergery` y `~/.local/share/hypergery`). PARA y anota el error.

**PASS si:** los tres comandos imprimen `1.5.0rc0`.

---

## Test 2 — First Run Wizard

```bash
hypergery-cli setup status          # estado actual (no imprime el token)
hypergery --first-run               # abre el asistente gráfico
```
Recorre: Bienvenida → Perfil (elige **"Este PC + Hub/Docker en otro equipo
dedicado/NAS"**) → Hub (ahí va el test 3) → Almacenamiento ("Comprobar permisos
y espacio") → Virtualización (debe decir virsh ✓, qemu:///system ✓) →
Seguridad → Resumen → Finalizar.

**Esperar:** el asistente no cambia nada del sistema sin preguntar; la página
de Virtualización no ejecuta sudo (si falta algo, te muestra el comando para
copiar). Al Finalizar, `setup status` muestra `first_run_completed: True` y el
perfil elegido.

**Si falla / rollback:** cierra el asistente (no rompe nada); reábrelo con
`hypergery-cli setup reset-first-run && hypergery --first-run`.

**PASS si:** completas el asistente y `setup status` queda `first_run_completed: True`.

---

## Test 3 — Conexión al Hub Docker del NAS

En la página "Hub" del asistente (o por CLI):
```bash
hypergery-cli hub health --hub-url http://192.168.1.150:8765
hypergery-cli setup test-hub --url http://192.168.1.150:8765 --token <TU_TOKEN>
```
El token del Hub lo lees en el NAS (no lo pegues en chats ni docs):
```bash
ssh -i ~/.ssh/hypergery_smoke Gery@192.168.1.150 \
  '/share/CACHEDEV2_DATA/.qpkg/container-station/bin/docker exec hypergery-hub cat /data/hub_token'
```
**Esperar:** `hub health` → `{"ok": true}`. `setup test-hub` con el token bueno
→ `ok: Conexión correcta…`. Con un token inventado → `auth_error` (es la prueba
negativa, correcta). La config se guarda con permisos 0600.

**Si falla / rollback:** si `unreachable`, comprueba que el contenedor está
arriba en el NAS:
`ssh ... docker ps | grep hypergery-hub` (debe decir `Up … (healthy)`). PARA si
no responde.

**PASS si:** `hub health` ok y `test-hub` con token bueno = `ok`, con token
malo = `auth_error`.

---

## Test 4 — Agentes PC y portátil online

Arranca el agente en cada host (apuntan al Hub por la config que acabas de
guardar):
```bash
# PC origen:
setsid nohup ~/.venvs/hypergery/bin/python -m hypergery_ubuntu.cli agent run \
  > ~/hgtest-uat/agent-pc.log 2>&1 < /dev/null &
# Portátil destino (token ya configurado en su ~/.config/hypergery/config.json):
ssh gery@192.168.1.73 'setsid nohup ~/.venvs/hypergery/bin/python -m hypergery_ubuntu.cli agent run \
  > ~/agent-laptop.log 2>&1 < /dev/null &'
sleep 8
```
Comprueba que el Hub ve ambos online:
```bash
hypergery-cli hub vms --hub-url http://192.168.1.150:8765 | head -20
python3 - <<'PY'
from hypergery_ubuntu.registry import RegistryClient
from hypergery_ubuntu.config import HyperGeryConfig
c = HyperGeryConfig.load(); cli = RegistryClient(c.hub_url, token=c.hub_token)
for h in cli.list_hosts():
    print(h["host_id"], h["status"], "kvm:", h.get("kvm_ok"))
PY
```
**Esperar:** los dos hosts (`gerard-MS-7E26` y `gery-Lenovo-ideapad-330S-14IKB`)
aparecen `online`, `kvm: True`.

**Si falla / rollback:** mira el log del agente (`tail ~/hgtest-uat/agent-pc.log`).
Para parar un agente: `pkill -f "[c]li agent run"` (en el host correspondiente;
el truco `[c]` evita matar la propia sesión SSH).

**PASS si:** ambos hosts `online` en el Hub.

---

## Test 5 — Migración OFICIAL Hub-mediated (flujo principal)

Crea una VM de prueba apagada en el PC:
```bash
hypergery-cli create-vm --name hgtest-user-hub --iso ~/hgtest-uat/dummy.iso \
  --ram-mib 512 --vcpus 1 --disk-gb 1 --display vnc
virsh domstate hgtest-user-hub          # → shut off
```
Lanza el job por el Hub:
```bash
hypergery-cli migrate remote hgtest-user-hub --transfer hub \
  --source-host-id gerard-MS-7E26 \
  --target-host-id gery-Lenovo-ideapad-330S-14IKB \
  --target-vm-name hgtest-user-hub-moved
```
Guarda el `migration_id` que imprime y sigue el estado:
```bash
hypergery-cli migrate status --migration-id <migration_id> | python3 -c \
  "import json,sys; m=json.load(sys.stdin)['migration']; print(m['status'], '| strategy:', m.get('strategy'))"
```
**Esperar:** `package_dir` empieza por `hub://` (viaja por el Hub, no
host-a-host); el estado recorre `preflight → packaging → uploaded →
waiting_target → importing → done`. Al terminar:
```bash
virsh domstate hgtest-user-hub                       # → shut off (ORIGEN INTACTO, no borrado)
ssh gery@192.168.1.73 'virsh dominfo hgtest-user-hub-moved | head -4'   # importada con UUID nuevo
```
**Cómo ver que el Hub registró el job:**
```bash
hypergery-cli migrate status --migration-id <migration_id>   # status, checksums, source_will_be_deleted:false
hypergery-cli hub packages --hub-url http://192.168.1.150:8765   # staging (se limpia al completar)
```

**Si falla / rollback:** el origen `hgtest-user-hub` **no se toca nunca**
(garantía del flujo). Si el destino falla, el origen sigue ahí para reintentar.
Limpia el destino fallido: `ssh gery@192.168.1.73 'virsh undefine
hgtest-user-hub-moved'`. PARA y anota el `status` y los `errors`.

**PASS si:** estado `done`, destino importado, **origen apagado e intacto**,
nunca activa en dos hosts.

---

## Test 6 — Live migration directa (VM ENCENDIDA, modo avanzado)

> Este es el único modo que mantiene la VM **encendida** de origen a destino.
> Requiere libvirt directo entre hosts. Avisos importantes abajo.

**Prerequisitos (una vez):**
- SSH sin contraseña del PC al portátil: `ssh gery@192.168.1.73 true` entra
  directo.
- El PC resuelve el hostname del portátil — añade a `/etc/hosts` del PC:
  `192.168.1.73 gery-Lenovo-ideapad-330S-14IKB` (necesita sudo, una vez).
- CPU cross-vendor (tu PC es AMD, el portátil Intel): la VM de prueba usa un
  modelo común; los comandos de abajo ya lo hacen.

Crea `hgtest-user-live` con CPU portable y arráncala:
```bash
hypergery-cli create-vm --name hgtest-user-live --iso ~/hgtest-uat/dummy.iso \
  --ram-mib 512 --vcpus 1 --disk-gb 1 --display vnc --disk-dir /var/tmp/hgtest-vms
virsh destroy hgtest-user-live 2>/dev/null
virsh dumpxml hgtest-user-live --inactive > /tmp/hgtest-user-live.xml
sed -i "s|<cpu mode='host-passthrough'[^/]*/>|<cpu mode='custom' match='exact' check='partial'><model fallback='forbid'>qemu64</model><feature policy='disable' name='svm'/></cpu>|" /tmp/hgtest-user-live.xml
virsh define /tmp/hgtest-user-live.xml
virsh change-media hgtest-user-live sda --eject --config 2>/dev/null
virsh start hgtest-user-live
```
**Comprueba que está ENCENDIDA antes:**
```bash
virsh domstate hgtest-user-live          # → ejecutando
```
Pre-crea el disco destino en la MISMA ruta (block migration) y migra:
```bash
ssh gery@192.168.1.73 'mkdir -p /var/tmp/hgtest-vms && qemu-img create -f qcow2 /var/tmp/hgtest-vms/hgtest-user-live.qcow2 1G'
hypergery-cli v1 migrate-live --vm hgtest-user-live \
  --target qemu+ssh://gery@192.168.1.73/system --block-migration --confirm
```
**Esperar:** JSON con `"ok": true`, `"status": "done"` y un
`"measured_downtime_ms"` pequeño (en el UAT fue 145 ms). Durante todo el
proceso la VM nunca se apaga.

**Comprueba que está ENCENDIDA después (en el destino) y que el origen ya no
corre:**
```bash
ssh gery@192.168.1.73 'virsh domstate hgtest-user-live'   # → ejecutando (DESTINO)
virsh list --all | grep hgtest-user-live                  # ya no está running en el ORIGEN
hypergery-cli v1 migrate-journal list                     # → in_flight vacío
```

**Variante shared-storage (opcional, requiere NFS):** `--shared-storage` solo
funciona si el disco está en **NFS** montado igual en ambos hosts. **CIFS/SMB
no está soportado** (el preflight lo rechaza con mensaje claro). Guía:
`docs/setup/NFS_SHARED_STORAGE_FOR_LIVE_MIGRATION.md`. No es necesario para
este UAT.

**Si falla / rollback:** el migrador deja **el origen running e intacto** y el
destino limpio (rollback automático; verificado en UAT). Si por un fallo de
infraestructura el origen quedara en pausa:
`virsh destroy hgtest-user-live && hypergery-cli v1 migrate-journal clear hgtest-user-live && virsh start hgtest-user-live`.
PARA y anota el `error` del JSON.

**PASS si:** `ok: true`, downtime medido, **destino ejecutando**, origen ya no
running, journal vacío, sin doble-activa.

---

## Test 7 — Verificar que las VMs reales NO se tocan

En cualquier momento (antes y después de los tests 5–6):
```bash
echo "== PC =="; virsh list --all
echo "== Portátil =="; ssh gery@192.168.1.73 'virsh list --all'
```
**Esperar:** tus VMs reales siguen **apagadas e intactas** en ambos hosts:
PC `ubuntu`, `ubuntu-migrated-migrated`, `hg-v06-2host-source`,
`hg-v06-e2e-source`; portátil `ubuntu-hub-e2e`, `ubuntu-migrated`,
`ubuntu-test-v07`. Solo deben aparecer/desaparecer las `hgtest-user-*`.

**PASS si:** ninguna VM real cambió de estado ni desapareció.

---

## Limpieza (solo hgtest-*)

```bash
# PC origen:
for vm in hgtest-user-hub hgtest-user-live; do
  virsh destroy $vm 2>/dev/null
  hypergery-cli delete-vm $vm --delete-disks 2>/dev/null
done
rm -f /var/tmp/hgtest-vms/hgtest-user-live.qcow2
# Portátil destino:
ssh gery@192.168.1.73 'for vm in hgtest-user-hub-moved hgtest-user-live; do virsh destroy $vm 2>/dev/null; virsh undefine $vm 2>/dev/null; rm -f /var/tmp/hgtest-vms/$vm.qcow2; done'
# Hub: borrar paquetes de staging de prueba (si quedara alguno)
hypergery-cli hub packages --hub-url http://192.168.1.150:8765
# Verifica que no queda nada hgtest:
virsh list --all | grep hgtest || echo "PC limpio"
ssh gery@192.168.1.73 'virsh list --all | grep hgtest || echo "portátil limpio"'
```
> El guard de discos no-gestionados puede negarse a borrar un .qcow2 fuera de
> su control: en ese caso borra el fichero a mano (las rutas de arriba), nunca
> toques rutas que no sean `hgtest-*`.

---

## Checklist PASS/FAIL para Gerard

| # | Prueba | PASS / FAIL | Notas |
|---|---|---|---|
| 1 | .deb instala; 3 comandos `1.5.0rc0` | ☐ / ☐ | |
| 2 | First Run Wizard completa; `first_run_completed: True` | ☐ / ☐ | |
| 3 | Hub `health` ok; `test-hub` ok (bueno) / auth_error (malo) | ☐ / ☐ | |
| 4 | Ambos agentes `online` en el Hub | ☐ / ☐ | |
| 5 | Hub-mediated: estado `done`, **origen intacto**, destino importado | ☐ / ☐ | downtime no aplica |
| 6 | Live directa: `ok: true`, **destino ejecutando**, origen no running | ☐ / ☐ | downtime_ms: ____ |
| 7 | VMs reales intactas en ambos hosts | ☐ / ☐ | |

**Veredicto de Gerard:**
- ☐ Todo PASS → autorizo publicar v1.5.0 (tag/release los hace Gerard a mano).
- ☐ Algún FAIL → NO publicar; anotar arriba y reportar.

> Recordatorio: este documento **no** publica nada. El tag, el merge a main y
> la release de GitHub los decides y ejecutas tú, después de este UAT.
