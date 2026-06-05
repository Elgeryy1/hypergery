/* HyperGery: Especificación de producto (puntos 1-11) */
const { useState: useStateSpec, useEffect: useEffectSpec, useRef: useRefSpec } = React;

const SPEC_SECTIONS = [
  ["vision", "1 · Visión general"],
  ["ds", "2 · Design system"],
  ["nav", "3 · Navegación"],
  ["layouts", "4 · Layout por pantalla"],
  ["components", "5 · Componentes"],
  ["states", "6 · Estados visuales"],
  ["microcopy", "7 · Microcopy"],
  ["flows", "8 · Flujos"],
  ["notnow", "9 · Qué NO diseñar (v0.6)"],
  ["roadmap", "10 · Roadmap v0.7+"],
  ["impl", "11 · Implementación PySide6"],
];

function SwatchRow({ name, hex, note }) {
  return (
    <div className="row gap10" style={{ alignItems: "center" }}>
      <span style={{ width: 34, height: 34, borderRadius: 8, background: hex, border: "1px solid rgba(255,255,255,.1)", flex: "0 0 34px" }} />
      <div className="grow"><div style={{ fontSize: 12.5, fontWeight: 600 }}>{name}</div><div className="faint" style={{ fontSize: 11 }}>{note}</div></div>
      <span className="mono dim" style={{ fontSize: 12 }}>{hex}</span>
    </div>
  );
}

function H({ children }) { return <h2 style={{ fontSize: 19, fontWeight: 700, margin: "0 0 14px", letterSpacing: "-0.3px" }}>{children}</h2>; }
function P({ children }) { return <p style={{ margin: "0 0 12px", fontSize: 13.5, lineHeight: 1.65, color: "var(--text-dim)", maxWidth: 760 }}>{children}</p>; }
function Sec({ id, children }) { return <section id={"spec-" + id} style={{ scrollMarginTop: 20, marginBottom: 40 }}>{children}</section>; }
function LI({ children }) { return <li style={{ marginBottom: 7 }}>{children}</li>; }
function UL({ children }) { return <ul style={{ margin: "0 0 14px", paddingLeft: 18, fontSize: 13.5, lineHeight: 1.6, color: "var(--text-dim)", maxWidth: 760 }}>{children}</ul>; }

function Spec({ app }) {
  const [active, setActive] = useStateSpec("vision");
  const scrollRef = useRefSpec(null);

  function jump(id) {
    const el = document.getElementById("spec-" + id);
    const cont = scrollRef.current;
    if (el && cont) cont.scrollTo({ top: el.offsetTop - 12, behavior: "smooth" });
    setActive(id);
  }

  return (
    <div className="viewfade" style={{ height: "100%", display: "grid", gridTemplateColumns: "212px 1fr", gap: 22 }}>
      <div className="col gap2" style={{ overflowY: "auto" }}>
        <div className="nav-label" style={{ paddingTop: 0 }}>Especificación</div>
        {SPEC_SECTIONS.map(([id, label]) => (
          <div key={id} className="nav-item" style={{ fontSize: 12.5, background: active === id ? "var(--accent-bg)" : undefined, color: active === id ? "#d6fbff" : undefined }} onClick={() => jump(id)}>{label}</div>
        ))}
      </div>

      <div ref={scrollRef} style={{ overflowY: "auto", paddingRight: 12 }} onScroll={(e) => {
        const top = e.target.scrollTop;
        for (let i = SPEC_SECTIONS.length - 1; i >= 0; i--) {
          const el = document.getElementById("spec-" + SPEC_SECTIONS[i][0]);
          if (el && el.offsetTop - 60 <= top) { setActive(SPEC_SECTIONS[i][0]); break; }
        }
      }}>
        <div style={{ maxWidth: 820 }}>
          <div className="page-head"><h1>Especificación de producto · HyperGery v0.6.0</h1><p>Documento de diseño/UX listo para pasar a implementación. Acompaña al prototipo navegable de las pestañas anteriores.</p></div>

          <Sec id="vision">
            <H>1 · Visión general del producto</H>
            <P>HyperGery es un gestor de máquinas virtuales de escritorio para Ubuntu sobre KVM/QEMU/libvirt, pensado como una versión moderna de VirtualBox enfocada a laboratorios de aula SMX/ASIX (Windows Server, Active Directory, DNS, routers, clientes, redes).</P>
            <P>En v0.6 evoluciona hacia una <b>plataforma distribuida</b>: gestor local de VMs, gestor de labs, plantillas, consola propia tipo VirtualBox, hosts remotos, un Hub en NAS sobre Docker, agentes por host y migración segura de VMs por NAS.</P>
            <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 12 }}>
              <Callout tone="ok"><b>Lo que es v0.6 (RC-candidate):</b> VMs locales, consola propia VNC + fallback SPICE externo, labs, templates, topología, remote hosts, Hub Docker, agente, NAS Clone Migration, doctor.</Callout>
              <Callout tone="warn"><b>Lo que NO es aún:</b> live RAM migration real, HG-MEMDIFF, AutoBoost, IA/scheduler, Android Hub, IsardVDI, P2P, SPICE integrado, USB passthrough, audio, GPU remoto.</Callout>
            </div>
          </Sec>

          <Sec id="ds">
            <H>2 · Design system</H>
            <P>Dark mode por defecto, fondo azul/negro profundo, cards limpias de borde suave, acento cian eléctrico, chips de estado y acciones destructivas en rojo. Tipografía técnica pero legible. Densidad compacta sin agobiar.</P>
            <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 14 }}>
              <Card title="Superficies & texto" bodyClass="pad"><div className="col gap10" style={{ padding: 14 }}>
                <SwatchRow name="Background" hex="#080D14" note="ventana / fondo principal" />
                <SwatchRow name="Surface / card" hex="#111C2E" note="tarjetas y paneles" />
                <SwatchRow name="Surface elevado" hex="#162033" note="hover, inputs, popovers" />
                <SwatchRow name="Border" hex="#263244" note="separadores" />
                <SwatchRow name="Text primary" hex="#E5E7EB" note="texto principal" />
                <SwatchRow name="Text secondary" hex="#94A3B8" note="texto secundario" />
              </div></Card>
              <Card title="Acento & estados" bodyClass="pad"><div className="col gap10" style={{ padding: 14 }}>
                <SwatchRow name="Primary accent" hex="#22D3EE" note="cian — acciones primarias" />
                <SwatchRow name="Secondary accent" hex="#60A5FA" note="azul — enlaces / info" />
                <SwatchRow name="Running / Healthy" hex="#22C55E" note="VM running, checks OK" />
                <SwatchRow name="Warning / Paused" hex="#F59E0B" note="pausa, WARN, SPICE" />
                <SwatchRow name="Failed / Destructive" hex="#EF4444" note="errores, delete, FAIL" />
                <SwatchRow name="Shutoff / Offline" hex="#64748B" note="apagado, offline" />
              </div></Card>
            </div>
            <P><b>Tipografía:</b> IBM Plex Sans para UI; IBM Plex Mono para datos técnicos (IPs, MAC, UUID, paths, IDs de migración). Escala: títulos 19–22 px, secciones 14–16 px, cuerpo 13–13.5 px, datos mono 11–12.5 px.</P>
            <P><b>Geometría:</b> radios 7/10/14 px, sombras suaves, líneas de 1 px. Inspiración: Proxmox (infra), UTM (limpieza), JetBrains (app técnica), Linear/Vercel (dashboard), Raycast (polish), GNOME Console (oscuridad limpia).</P>
          </Sec>

          <Sec id="nav">
            <H>3 · Navegación principal</H>
            <P>Estructura de tres zonas: <b>sidebar</b> izquierda (secciones), <b>top bar</b> (identidad + estado del sistema + acciones globales) y <b>área central</b> que cambia por sección. Panel inferior opcional de Activity Log colapsable.</P>
            <UL>
              <LI><b>Sidebar:</b> Dashboard · Virtual Machines · Labs · Templates · Remote Hosts · Migrations · Diagnostics · Settings. Item activo con barra de acento y badge de conteo.</LI>
              <LI><b>Top bar:</b> nombre HyperGery + versión, Hub status, host actual, NAS status, botón New VM, Refresh y Settings.</LI>
              <LI><b>Activity Log:</b> tira inferior colapsable global presente en todas las secciones; además sección completa con filtros.</LI>
            </UL>
          </Sec>

          <Sec id="layouts">
            <H>4 · Layout de cada pantalla</H>
            {[["Dashboard", "Cuatro tarjetas de estado (VMs running, Hub, NAS, hosts), rejilla de acciones rápidas, avisos importantes, gauges de recursos del host, último diagnóstico y tabla de últimas migraciones. Útil al abrir, no decorativo."],
              ["Virtual Machines", "Toolbar (buscar, filtro por lab, toggle tabla/cards, New VM) + lista principal a la izquierda y panel de detalles a la derecha con pestañas General, System, Storage, Network, Snapshots, Logs, Console. Acciones por VM en barra contextual."],
              ["VM Console Window", "Ventana separada con su propia barra de título “HyperGery Console — <vm>”, toolbar (Connect/Disconnect/Reconnect, Ctrl+Alt+Del, Release Input, Scale to Fit, Fullscreen, External Viewer, Close), área de framebuffer y status bar. Tres estados: VNC running, SPICE y apagada."],
              ["Labs", "Lista de labs a la izquierda; detalle a la derecha con red, subnet, bridge, templates usados, VMs del lab y acciones (New/Rename/Duplicate/Export/Import/Delete). Empty state para aula nueva. Acceso directo a topología."],
              ["Lab Topology", "Lienzo con el nodo de red a la izquierda y nodos de VM a la derecha unidos por líneas curvas coloreadas por estado, con badges de rol (AD/DNS/WEB/DB/Router/Client). Panel lateral con el nodo seleccionado y acciones."],
              ["Templates", "Dos secciones (VM Templates y Lab Templates) en cards con id, OS, RAM, vCPU, disco, display y VMs planificadas. Acciones New/Edit/Delete/Export/Import, Create VM from Template e Instantiate Lab Template."],
              ["Remote Hosts", "Card de Hub destacada arriba (URL, estado, latencia, hosts online, VM inventory, NAS writable, Docker) y rejilla de hosts con readiness KVM/libvirt, RAM/disco, VMs activas y heartbeat. Host offline claramente diferenciado."],
              ["NAS Clone Migration", "Wizard de 6 pasos (Select VM → Target Host → Options → Preflight → Progress → Result) con stepper lateral. Evita venderse como live RAM; recalca que el origen queda intacto."],
              ["Settings", "Navegación lateral de 8 pestañas (General, Hub, Host Agent, NAS, VM Defaults, Console, Appearance, Advanced). Cada campo etiqueta su origen: environment / config / default. Botones Test Hub/NAS/libvirt, Reset, Save, Cancel."],
              ["Diagnostics / Doctor", "Tabla de checks con OK/WARN/FAIL, detalle, marca de crítico y origen. Resumen de conteos y exit code. Acciones Run Doctor, Copy Report, Troubleshooting."],
              ["Activity Logs", "Filtros All/VM/Hub/Migration/Agent/Console/Error, líneas mono compactas con timestamp + fuente coloreada + mensaje. Acciones Copy/Clear View/Export/Refresh."]].map(([t, d]) => (
              <div key={t} className="card" style={{ padding: "12px 16px", marginBottom: 10 }}>
                <div style={{ fontWeight: 650, fontSize: 13.5, marginBottom: 4 }}>{t}</div>
                <div className="dim" style={{ fontSize: 12.5, lineHeight: 1.5 }}>{d}</div>
              </div>
            ))}
          </Sec>

          <Sec id="components">
            <H>5 · Componentes reutilizables</H>
            <UL>
              <LI><b>StateChip:</b> RUNNING / SHUTOFF / PAUSED / UNKNOWN con punto de color y texto mono.</LI>
              <LI><b>RoleBadge:</b> AD, DNS, WEB, DB, ROUTER, CLIENT, cada uno con su color.</LI>
              <LI><b>Btn:</b> variantes default, primary (cian), success (verde), danger (rojo), ghost; tamaños sm/xs; sólo-icono.</LI>
              <LI><b>Card / card-head:</b> contenedor con cabecera, icono, subtítulo y slot derecho.</LI>
              <LI><b>StatPill:</b> indicador de estado en top bar (Hub/host/NAS).</LI>
              <LI><b>Bar / Gauge:</b> uso de CPU/RAM/disco.</LI>
              <LI><b>Callout:</b> info / warn / danger / ok para microcopy contextual.</LI>
              <LI><b>Seg / Tabs:</b> control segmentado y pestañas.</LI>
              <LI><b>Field / Switch / Select / Input:</b> formularios con etiqueta de origen.</LI>
              <LI><b>Stepper + pstate:</b> wizard de migración y lista de estados de progreso.</LI>
              <LI><b>Tabla (tbl):</b> filas seleccionables, hover, columnas mono.</LI>
              <LI><b>Empty / Modal / Toast:</b> estados vacíos, diálogos y notificaciones.</LI>
            </UL>
          </Sec>

          <Sec id="states">
            <H>6 · Estados visuales</H>
            <div className="row wrap gap8" style={{ marginBottom: 12 }}>
              <StateChip state="running" /><StateChip state="shutoff" /><StateChip state="paused" /><StateChip state="unknown" />
              <span className="chip ok"><i className="cdot" />OK</span><span className="chip warn"><i className="cdot" />WARN</span><span className="chip danger"><i className="cdot" />FAIL</span>
            </div>
            <div className="row wrap gap8" style={{ marginBottom: 14 }}>
              <RoleBadge role="AD" /><RoleBadge role="DNS" /><RoleBadge role="WEB" /><RoleBadge role="DB" /><RoleBadge role="Router" /><RoleBadge role="Client" />
            </div>
            <UL>
              <LI><b>VM:</b> running (verde), shutoff (slate), paused (ámbar), unknown (azul slate).</LI>
              <LI><b>Hub / host:</b> online (verde), offline (rojo, claramente atenuado), not ready (rojo, KVM/libvirt KO).</LI>
              <LI><b>Doctor:</b> OK / WARN / FAIL, con distinción de checks críticos.</LI>
              <LI><b>Migración:</b> created → preflight → packaging → uploaded → waiting_target → importing → defining_vm → done / failed.</LI>
              <LI><b>Consola:</b> connecting (fondo negro + spinner), connected (framebuffer + captura de input), SPICE (card explicativa), apagada (card + Start).</LI>
            </UL>
          </Sec>

          <Sec id="microcopy">
            <H>7 · Microcopy clave</H>
            <div className="col gap8">
              {[["Hub offline", "“HyperGery Hub no responde. Revisa la URL del Hub y que el contenedor Docker esté en healthy.”"],
                ["NAS not mounted", "“NAS staging no montado. Monta el recurso del NAS antes de empaquetar migraciones.”"],
                ["VM shutoff", "“VM is powered off — arranca la VM para conectar la consola integrada.”"],
                ["VM running cannot migrate", "“Las VMs en running están bloqueadas. Detenla con ACPI Shutdown antes de migrar.”"],
                ["SPICE requires External Viewer", "“This VM uses SPICE. Use External Viewer or switch to VNC while powered off.”"],
                ["VNC integrated console", "“Integrated console requires VNC.”"],
                ["Release input", "“Right Ctrl releases input.”"],
                ["Source untouched", "“Source VM remains untouched · UUID & MAC regenerated on target.”"],
                ["Not live RAM", "“This is NAS Clone Migration, not live RAM migration.”"],
                ["Docker unhealthy", "“Docker Hub unhealthy — revisa docker compose ps y el healthcheck del contenedor.”"],
                ["SQLite on NAS", "“La base de datos SQLite no debe estar en NAS/SMB; mantenla en el volumen Docker.”"]].map(([k, v]) => (
                <div key={k} className="card row gap12" style={{ padding: "10px 14px", alignItems: "flex-start" }}>
                  <span className="chip plain" style={{ flex: "0 0 auto", fontSize: 10.5 }}>{k}</span>
                  <span className="dim" style={{ fontSize: 12.5, lineHeight: 1.5 }}>{v}</span>
                </div>
              ))}
            </div>
          </Sec>

          <Sec id="flows">
            <H>8 · Flujos principales</H>
            {[["Crear VM", ["New VM (toolbar/dashboard/template)", "Nombre + lab + ISO + RAM/vCPU/disco + display", "Si SPICE → aviso de consola", "Crear → virsh define + qcow2", "VM aparece en lista como SHUTOFF"]],
              ["Abrir consola", ["Console en la VM", "Si VNC running → conexión automática + Scale to Fit", "Clic captura input · Right Ctrl libera", "Si SPICE → card + External Viewer", "Si apagada → card + Start VM", "Cerrar no detiene la VM"]],
              ["Migrar VM por NAS", ["Live Migration", "Select VM (apagada) → Target Host (online)", "Options (nombre, ISO, snapshots, start after)", "Preflight (10 checks)", "Empaquetar → NAS staging → import en destino", "Result: origen intacto, UUID/MAC nuevos"]],
              ["Revisar hosts remotos", ["Remote Hosts", "Card Hub (latencia, inventario, NAS)", "Refresh / Test Host", "View VMs / Use as Migration Target", "Offline claramente diferenciado"]],
              ["Ejecutar doctor", ["Diagnostics → Run Doctor", "Checks de KVM/libvirt/QEMU/Hub/NAS/Docker", "OK/WARN/FAIL + críticos", "Copy Report / Troubleshooting"]],
              ["Configurar Hub/NAS", ["Settings → Hub / NAS", "Editar URL y staging path", "Test Hub / Test NAS write", "Ver origen environment/config/default", "Save"]]].map(([t, steps]) => (
              <div key={t} className="card" style={{ padding: 14, marginBottom: 10 }}>
                <div style={{ fontWeight: 650, fontSize: 13.5, marginBottom: 8 }}>{t}</div>
                <div className="row wrap" style={{ gap: 6, alignItems: "center" }}>
                  {steps.map((s, i) => (
                    <React.Fragment key={i}>
                      <span className="chip plain" style={{ fontSize: 11 }}>{s}</span>
                      {i < steps.length - 1 && <Icon name="chevron" size={13} style={{ color: "var(--text-faint)" }} />}
                    </React.Fragment>
                  ))}
                </div>
              </div>
            ))}
          </Sec>

          <Sec id="notnow">
            <H>9 · Qué NO diseñar todavía para v0.6</H>
            <Callout tone="warn" style={{ marginBottom: 12 }}>Se pueden mencionar como futuro, pero no presentarse como features actuales principales.</Callout>
            <div className="row wrap gap8">
              {["Live RAM migration real", "HG-MEMDIFF", "AutoBoost inteligente", "IA / scheduler automático", "Android Hub", "IsardVDI", "P2P avanzado", "SPICE integrado", "USB passthrough", "Clipboard avanzado", "Audio integrado", "GPU remoto"].map((x) => (
                <span key={x} className="chip danger" style={{ fontSize: 11.5 }}><Icon name="x" size={11} />{x}</span>
              ))}
            </div>
          </Sec>

          <Sec id="roadmap">
            <H>10 · Roadmap visual v0.7+</H>
            {[["v0.6.0 · RC-candidate", "done", "VMs locales, consola propia, labs, templates, topología, remote hosts, Hub Docker, agente, NAS Clone Migration, doctor. Falta smoke en dos hosts físicos reales."],
              ["v0.7.0", "active", "Topología con zoom/pan + export PNG/SVG, role badges en nodos, progreso por VM en instanciación, refinamiento UX general."],
              ["v0.8+", "pending", "SPICE integrado, clipboard/USB/audio passthrough, streaming byte-level de progreso del agente."],
              ["v1.0.0", "pending", "Release estable lista para aula; posible live RAM migration real, AutoBoost e integraciones (IsardVDI / Android Hub) como exploración."]].map(([v, st, d]) => (
              <div key={v} className="row gap12" style={{ marginBottom: 12, alignItems: "flex-start" }}>
                <span className="pdot" style={{ width: 18, height: 18, borderRadius: "50%", flex: "0 0 18px", marginTop: 2, background: st === "done" ? "var(--running)" : st === "active" ? "var(--accent)" : "transparent", border: st === "pending" ? "1px solid var(--border)" : "none", display: "grid", placeItems: "center", color: "#04141a" }}>{st !== "pending" && <Icon name={st === "done" ? "check" : "bolt"} size={11} />}</span>
                <div className="grow"><div className="row gap8"><b style={{ fontSize: 13.5 }}>{v}</b>{st === "active" && <span className="chip accent" style={{ fontSize: 10 }}><i className="cdot" />EN CURSO</span>}</div><div className="dim" style={{ fontSize: 12.5, lineHeight: 1.5, marginTop: 3 }}>{d}</div></div>
              </div>
            ))}
          </Sec>

          <Sec id="impl">
            <H>11 · Recomendaciones de implementación (PySide6)</H>
            <P>El stack actual es PySide6/Qt con backend real KVM/QEMU/libvirt vía virsh/qemu-img/virt-viewer. Sugerencia de migración del UI por fases, sin reescribir todo de golpe:</P>
            {[["Fase 1 · Tokens & QSS", "Centralizar la paleta y tipografía en un QSS único (ya existe styles.py). Definir variables de color, radios y estados; aplicar StateChip y botones con object names (primaryButton, dangerButton, ghostButton)."],
              ["Fase 2 · Shell", "Reestructurar a sidebar + top bar + stacked central widget (QStackedWidget). Top bar con StatPills de Hub/host/NAS conectados a señales del RegistryClient."],
              ["Fase 3 · VMs + detalles", "QTableView con modelo de VMs + panel de detalles QTabWidget. Acciones contextuales como QToolBar por VM. Estados desde el backend."],
              ["Fase 4 · Consola", "Pulir la ventana de consola VNC existente: toolbar, status bar, estados SPICE/apagada como QStackedWidget; Scale to Fit por defecto; Right Ctrl como host key."],
              ["Fase 5 · Migración", "Wizard QWizard de 6 páginas reusando migrate preflight/package/import. Preflight y progress conectados a estados reales del Hub (polling de migration_status)."],
              ["Fase 6 · Hub/Hosts/Doctor/Settings", "Remote Hosts y Hub card desde RegistryClient; Diagnostics desde collect_doctor_items(); Settings con QTabWidget y etiquetas de origen desde effective_config()."],
              ["Transversal", "Workers en QThread para operaciones libvirt/NAS (ya existe workers.py). Nunca bloquear el hilo de UI. Mantener microcopy y estados de seguridad de la migración."]].map(([t, d], i) => (
              <div key={t} className="card" style={{ padding: 14, marginBottom: 10 }}>
                <div className="row gap8" style={{ marginBottom: 4 }}><span className="step active" style={{ padding: 0, background: "none" }}><span className="sdot">{i + 1}</span></span><b style={{ fontSize: 13.5 }}>{t}</b></div>
                <div className="dim" style={{ fontSize: 12.5, lineHeight: 1.55, paddingLeft: 36 }}>{d}</div>
              </div>
            ))}
            <Callout tone="info" style={{ marginTop: 8 }}>Este prototipo HTML es una referencia visual: define el objetivo de UI por pantalla, estados y microcopy. La fuente de verdad funcional sigue siendo el backend Python existente.</Callout>
          </Sec>
        </div>
      </div>
    </div>
  );
}

window.Spec = Spec;
