/* HyperGery: Diagnostics, Settings, Activity Logs, New VM dialog */
const { useState: useStateSys, useEffect: useEffectSys, useMemo: useMemoSys } = React;

/* ============================== DIAGNOSTICS ============================== */
function Diagnostics({ app }) {
  const [running, setRunning] = useStateSys(false);
  const [shown, setShown] = useStateSys(HG.diagnostics.length);
  const items = HG.diagnostics;
  const ok = items.filter((d) => d.status === "OK").length;
  const warn = items.filter((d) => d.status === "WARN").length;
  const fail = items.filter((d) => d.status === "FAIL").length;

  function run() {
    setRunning(true); setShown(0);
    const iv = setInterval(() => setShown((n) => { if (n >= items.length) { clearInterval(iv); setRunning(false); return n; } return n + 1; }), 130);
  }
  const meta = { OK: ["ok", "var(--running)"], WARN: ["warn", "var(--warning)"], FAIL: ["danger", "var(--danger)"] };

  return (
    <div className="viewfade">
      <div className="page-head row spread" style={{ alignItems: "flex-end" }}>
        <div><h1>Diagnostics · Doctor</h1><p>Comprobaciones de entorno sin cambiar el sistema: KVM, libvirt, herramientas QEMU, Hub, NAS y Docker.</p></div>
        <div className="row gap8">
          <Btn icon="copy" onClick={() => app.toast("Reporte copiado al portapapeles")}>Copy Report</Btn>
          <Btn icon="external" onClick={() => app.toast("Abriendo guía de troubleshooting…")}>Troubleshooting</Btn>
          <Btn variant="primary" icon={running ? "refresh" : "doctor"} onClick={run}>{running ? "Ejecutando…" : "Run Doctor"}</Btn>
        </div>
      </div>

      <div className="row gap10" style={{ marginBottom: 16 }}>
        <span className="chip ok" style={{ fontSize: 12 }}><i className="cdot" />{ok} OK</span>
        <span className="chip warn" style={{ fontSize: 12 }}><i className="cdot" />{warn} WARN</span>
        <span className="chip danger" style={{ fontSize: 12 }}><i className="cdot" />{fail} FAIL</span>
        <span className="grow" />
        <span className="faint" style={{ fontSize: 12 }}>{fail === 0 ? "Sin fallos críticos · exit code 0" : "Fallos críticos presentes · exit code 1"}</span>
      </div>

      <Card noBody>
        <table className="tbl">
          <thead><tr><th style={{ width: 90 }}>Estado</th><th style={{ width: 200 }}>Check</th><th>Detalle</th><th style={{ width: 130 }}>Origen</th></tr></thead>
          <tbody>
            {items.slice(0, shown).map((d) => {
              const [cls, color] = meta[d.status];
              return (
                <tr key={d.name} style={{ cursor: "default" }}>
                  <td><span className={"chip " + cls} style={{ fontSize: 10.5 }}><i className="cdot" />{d.status}</span></td>
                  <td><div className="row gap8"><span className="name mono nowrap" style={{ fontSize: 12.5 }}>{d.name}</span>{d.critical && <span className="rolebadge" style={{ fontSize: 9.5 }}>CRÍTICO</span>}</div></td>
                  <td className="mono dim" style={{ fontSize: 12 }}>{d.detail}</td>
                  <td>{d.src ? <span className={"tag-src " + d.src}>{d.src}</span> : <span className="faint" style={{ fontSize: 11 }}>—</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Card>
      <Callout tone="warn" style={{ marginTop: 14 }}><b>SQLite DB del Hub:</b> debe vivir en el volumen Docker, nunca en NAS/SMB — el bloqueo de ficheros sobre SMB corrompe la base de datos.</Callout>
    </div>
  );
}

/* ============================== SETTINGS ============================== */
function Settings({ app }) {
  const [tab, setTab] = useStateSys(app.params.tab || "General");
  const tabs = ["General", "Hub", "Host Agent", "NAS", "VM Defaults", "Console", "Appearance", "Advanced"];

  const F = ({ label, src, children, hint }) => <Field label={label} src={src} hint={hint}>{children}</Field>;
  const Row2 = ({ children }) => <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 16 }}>{children}</div>;

  return (
    <div className="viewfade">
      <div className="page-head"><h1>Settings</h1><p>Configuración del Hub, agente, NAS y valores por defecto. Cada campo indica si viene de <b>environment</b>, <b>config</b> o <b>default</b>.</p></div>
      <div style={{ display: "grid", gridTemplateColumns: "200px 1fr", gap: 20 }}>
        <div className="col gap2" style={{ position: "sticky", top: 0 }}>
          {tabs.map((t) => (
            <div key={t} onClick={() => setTab(t)} className="nav-item" style={{ background: t === tab ? "var(--accent-bg)" : undefined, color: t === tab ? "#d6fbff" : undefined, fontSize: 13 }}>{t}</div>
          ))}
        </div>

        <div className="card pad" style={{ padding: 22 }}>
          {tab === "General" && <div className="col gap16">
            <Row2><F label="Host ID" src="config"><input className="input mono" defaultValue="aula12-pc03" /></F><F label="Host Name" src="config"><input className="input" defaultValue="Aula 12 · PC 03" /></F></Row2>
            <F label="Idioma" src="default"><select className="select" defaultValue="es"><option value="es">Español</option><option value="en">English</option><option value="ca">Català</option></select></F>
            <F label="Comportamiento al iniciar" src="default"><select className="select"><option>Abrir Dashboard</option><option>Última sección</option><option>Virtual Machines</option></select></F>
          </div>}

          {tab === "Hub" && <div className="col gap16">
            <F label="Hub URL" src="environment" hint="HYPERGERY_HUB_URL — el environment tiene prioridad sobre config."><input className="input mono" defaultValue="http://192.168.1.150:8765" /></F>
            <Row2><F label="Timeout (s)" src="default"><input className="input mono" defaultValue="3" /></F><F label="Intervalo de polling (s)" src="config"><input className="input mono" defaultValue="15" /></F></Row2>
            <div className="row gap8"><Btn icon="bolt" onClick={() => app.toast("Hub OK · healthy · 23 ms")}>Test Hub</Btn><span className="chip ok" style={{ alignSelf: "center" }}><i className="cdot" />Última prueba: OK</span></div>
          </div>}

          {tab === "Host Agent" && <div className="col gap16">
            <F label="Agent enabled" src="config"><div className="row gap10"><Switch checked={true} onChange={()=>{}} /><span className="dim" style={{ fontSize: 12.5 }}>El agente envía heartbeats y atiende comandos del allowlist.</span></div></F>
            <Row2><F label="Heartbeat (s)" src="default"><input className="input mono" defaultValue="10" /></F><F label="Command allowlist" src="default"><input className="input mono" defaultValue="preflight, import_vm_package, migration_status" /></F></Row2>
            <Callout tone="info">El agente solo ejecuta comandos del allowlist y rechaza rutas fuera del NAS staging.</Callout>
          </div>}

          {tab === "NAS" && <div className="col gap16">
            <F label="NAS staging path" src="environment" hint="HYPERGERY_NAS_STAGING_PATH"><input className="input mono" defaultValue="/mnt/hypergery-nas/hypergery" /></F>
            <F label="NAS root (QNAP)" src="config"><input className="input mono" defaultValue="/share/CACHEDEV2_DATA/Gerard/hypergery" /></F>
            <div className="row gap8"><Btn icon="bolt" onClick={() => app.toast("NAS staging writable=true ✓")}>Test NAS write</Btn><span className="chip ok" style={{ alignSelf: "center" }}><i className="cdot" />Writable</span></div>
            <Callout tone="danger">La base de datos SQLite del Hub <b>no</b> debe ubicarse en NAS/SMB. Mantenla en el volumen Docker.</Callout>
          </div>}

          {tab === "VM Defaults" && <div className="col gap16">
            <Row2><F label="Default display" src="default"><select className="select" defaultValue="VNC"><option>VNC</option><option>SPICE</option></select></F><F label="RAM por defecto (MiB)" src="default"><input className="input mono" defaultValue="4096" /></F></Row2>
            <Row2><F label="vCPU por defecto" src="default"><input className="input mono" defaultValue="2" /></F><F label="Disco por defecto (GB)" src="default"><input className="input mono" defaultValue="40" /></F></Row2>
            <F label="Default ISO folder" src="config"><input className="input mono" defaultValue="~/ISOs" /></F>
            <F label="Default VM storage path" src="default"><input className="input mono" defaultValue="~/.local/share/hypergery/vms" /></F>
          </div>}

          {tab === "Console" && <div className="col gap16">
            <F label="Integrated console enabled" src="config"><div className="row gap10"><Switch checked={true} onChange={()=>{}} /><span className="dim" style={{ fontSize: 12.5 }}>Consola VNC integrada tipo VirtualBox.</span></div></F>
            <F label="External viewer command" src="default"><input className="input mono" defaultValue="virt-viewer --connect qemu:///system" /></F>
            <F label="Scale to Fit por defecto" src="default"><div className="row gap10"><Switch checked={true} onChange={()=>{}} /><span className="dim" style={{ fontSize: 12.5 }}>Mantiene aspect ratio y centra el framebuffer.</span></div></F>
            <Callout tone="info">Host Key para liberar input: <span className="kbd">Right Ctrl</span>. SPICE usa siempre visor externo.</Callout>
          </div>}

          {tab === "Appearance" && <div className="col gap16">
            <F label="Theme" src="config"><Seg value="dark" onChange={()=>{}} options={[{value:"dark",label:"Dark"},{value:"midnight",label:"Midnight"}]} /></F>
            <F label="Accent color" src="config">
              <div className="row gap10">
                {[["#22D3EE","Cian"],["#38BDF8","Sky"],["#60A5FA","Azul"]].map(([c,n]) => (
                  <div key={c} onClick={() => app.setTweak("accent", c)} className="row gap6" style={{ cursor: "pointer", padding: "6px 10px", borderRadius: 8, border: "1px solid " + (app.tweaks.accent===c?"var(--accent-line)":"var(--border)"), background: app.tweaks.accent===c?"var(--accent-bg)":"var(--surface-2)" }}>
                    <span style={{ width: 16, height: 16, borderRadius: "50%", background: c }} /><span style={{ fontSize: 12.5 }}>{n}</span>
                  </div>
                ))}
              </div>
            </F>
            <F label="Densidad" src="config"><Seg value={app.tweaks.density||"comfortable"} onChange={(v)=>app.setTweak("density",v)} options={[{value:"comfortable",label:"Cómoda"},{value:"compact",label:"Compacta"}]} /></F>
          </div>}

          {tab === "Advanced" && <div className="col gap16">
            <div className="row gap8"><Btn icon="bolt" onClick={()=>app.toast("libvirt: connected to qemu:///system ✓")}>Test libvirt</Btn><Btn icon="bolt" onClick={()=>app.toast("Hub: healthy ✓")}>Test Hub</Btn><Btn icon="bolt" onClick={()=>app.toast("NAS writable ✓")}>Test NAS</Btn></div>
            <F label="libvirt URI" src="default"><input className="input mono" defaultValue="qemu:///system" /></F>
            <F label="Log level" src="default"><select className="select"><option>INFO</option><option>DEBUG</option><option>WARN</option></select></F>
            <Callout tone="warn">“Reset defaults” restablece config.json; las variables de environment seguirán teniendo prioridad.</Callout>
          </div>}

          <div className="divider" style={{ margin: "20px 0 16px" }} />
          <div className="row gap8 spread">
            <Btn variant="danger" icon="refresh" onClick={() => app.toast("Config restablecida a defaults")}>Reset defaults</Btn>
            <div className="row gap8"><Btn onClick={() => app.toast("Cambios descartados")}>Cancel</Btn><Btn variant="primary" icon="check" onClick={() => app.toast("Configuración guardada")}>Save</Btn></div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ============================== ACTIVITY LOGS (section K) ============================== */
const LOG_FILTERS = ["All", "VM", "Hub", "Migration", "Agent", "Console", "Error"];
function ActivityLogs({ app }) {
  const [filter, setFilter] = useStateSys("All");
  const list = useMemoSys(() => HG.logs.filter((l) =>
    filter === "All" ? true : filter === "Error" ? l.level === "error" : l.src === filter.toLowerCase()
  ), [filter]);
  return (
    <div className="viewfade" style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      <div className="page-head"><h1>Activity Logs</h1><p>Eventos de VMs, Hub, migraciones, agente y consola. Compacto y filtrable.</p></div>
      <div className="row spread" style={{ marginBottom: 14 }}>
        <div className="seg">{LOG_FILTERS.map((f) => <button key={f} className={filter===f?"on":""} onClick={()=>setFilter(f)}>{f}</button>)}</div>
        <div className="row gap8"><Btn size="sm" icon="copy" onClick={()=>app.toast("Logs copiados")}>Copy</Btn><Btn size="sm" icon="x" onClick={()=>app.toast("Vista limpiada")}>Clear View</Btn><Btn size="sm" icon="download" onClick={()=>app.toast("Logs exportados")}>Export</Btn><Btn size="sm" icon="refresh" variant="ghost" onClick={()=>app.toast("Actualizado")} /></div>
      </div>
      <div className="card" style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
        {list.map((l, i) => (
          <div key={i} className={"logline " + (l.level === "error" ? "err" : "")}>
            <span className="ts">{l.t}</span>
            <span className={"src lsrc-" + l.src}>{l.src.toUpperCase()}</span>
            <span className="msg grow">{l.msg}</span>
          </div>
        ))}
        {list.length === 0 && <div className="faint" style={{ padding: 30, textAlign: "center" }}>Sin eventos para este filtro.</div>}
      </div>
    </div>
  );
}

/* ============================== NEW VM DIALOG ============================== */
function NewVmDialog({ app, template }) {
  const [f, setF] = useStateSys({
    name: "", iso: "", lab: HG.labs[0].id,
    ram: template ? template.ram : 4096, vcpu: template ? template.vcpu : 2, disk: template ? template.disk : 40,
    display: template ? template.display : "VNC",
  });
  const set = (k, v) => setF({ ...f, [k]: v });
  return (
    <Modal title="New Virtual Machine" sub={template ? "Desde template · " + template.name : "Crear desde ISO"} width={600} onClose={() => app.closeNewVm()}
      footer={<><Btn onClick={() => app.closeNewVm()}>Cancel</Btn><Btn variant="primary" icon="check" disabled={!f.name.trim()} onClick={() => { app.closeNewVm(); app.toast("VM “" + f.name + "” creada y definida en libvirt"); }}>Crear VM</Btn></>}>
      <div className="col gap16">
        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          <Field label="Nombre de la VM"><input className="input mono" placeholder="WS2022-DC03" value={f.name} onChange={(e) => set("name", e.target.value)} autoFocus /></Field>
          <Field label="Lab"><select className="select" value={f.lab} onChange={(e) => set("lab", e.target.value)}>{HG.labs.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select></Field>
        </div>
        <Field label="ISO de instalación" hint="Carpeta por defecto: ~/ISOs">
          <div className="row gap8"><input className="input mono" placeholder="/home/alumno/ISOs/ubuntu-24.04.iso" value={f.iso} onChange={(e) => set("iso", e.target.value)} /><Btn icon="folder" onClick={() => set("iso", "~/ISOs/ubuntu-24.04.1-live-server.iso")}>Browse</Btn></div>
        </Field>
        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>
          <Field label="RAM (MiB)"><input className="input mono" value={f.ram} onChange={(e) => set("ram", e.target.value)} /></Field>
          <Field label="vCPU"><input className="input mono" value={f.vcpu} onChange={(e) => set("vcpu", e.target.value)} /></Field>
          <Field label="Disco (GB)"><input className="input mono" value={f.disk} onChange={(e) => set("disk", e.target.value)} /></Field>
        </div>
        <Field label="Display"><Seg value={f.display} onChange={(v) => set("display", v)} options={[{ value: "VNC", label: "VNC (consola integrada)" }, { value: "SPICE", label: "SPICE (visor externo)" }]} /></Field>
        {f.display === "SPICE" && <Callout tone="warn">Con SPICE la consola integrada no está disponible; se usa el visor externo. Elige VNC para consola integrada.</Callout>}
      </div>
    </Modal>
  );
}

Object.assign(window, { Diagnostics, Settings, ActivityLogs, NewVmDialog });
