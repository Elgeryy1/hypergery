/* HyperGery — app shell, router, overlays, tweaks */
const { useState: useStateApp, useEffect: useEffectApp, useCallback } = React;

const NAV = [
  ["dashboard", "Dashboard", "dashboard"],
  ["vms", "Virtual Machines", "vm"],
  ["labs", "Labs", "labs"],
  ["topology", "Lab Topology", "route"],
  ["templates", "Templates", "templates"],
  ["hosts", "Remote Hosts", "hosts"],
  ["migrations", "Migrations", "migrations"],
  ["diagnostics", "Diagnostics", "diagnostics"],
  ["logs", "Activity Logs", "logs"],
  ["settings", "Settings", "settings"],
  ["spec", "Especificación", "package"],
];

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "accent": "#22D3EE",
  "density": "comfortable",
  "vmView": "table",
  "dashboardMode": "metrics"
}/*EDITMODE-END*/;

function Toasts({ items }) {
  return (
    <div style={{ position: "absolute", bottom: 18, left: "50%", transform: "translateX(-50%)", zIndex: 90, display: "flex", flexDirection: "column", gap: 8, alignItems: "center", pointerEvents: "none" }}>
      {items.map((t) => (
        <div key={t.id} className="viewfade row gap8" style={{ background: "var(--elevated)", border: "1px solid var(--accent-line)", borderRadius: 9, padding: "9px 15px", fontSize: 12.5, boxShadow: "var(--shadow-pop)" }}>
          <Icon name="check" size={15} style={{ color: "var(--accent)" }} /> {t.msg}
        </div>
      ))}
    </div>
  );
}

function App() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const [view, setView] = useStateApp("dashboard");
  const [params, setParams] = useStateApp({});
  const [console_, setConsole_] = useStateApp(null);
  const [consoleFs, setConsoleFs] = useStateApp(false);
  const [migration, setMigration] = useStateApp(undefined);
  const [newVm, setNewVm] = useStateApp(undefined);
  const [toasts, setToasts] = useStateApp([]);
  const [logOpen, setLogOpen] = useStateApp(false);

  // apply tweaks → CSS vars
  useEffectApp(() => {
    const r = document.documentElement.style;
    const hx = t.accent.replace("#", "");
    const R = parseInt(hx.slice(0, 2), 16), G = parseInt(hx.slice(2, 4), 16), B = parseInt(hx.slice(4, 6), 16);
    const rgba = (a) => `rgba(${R}, ${G}, ${B}, ${a})`;
    r.setProperty("--accent", t.accent);
    r.setProperty("--accent-bg", rgba(0.14));
    r.setProperty("--accent-line", rgba(0.48));
    r.setProperty("--accent-ghost", rgba(0.18));
    const compact = t.density === "compact";
    r.setProperty("--density", compact ? "0.66" : "1");
    r.setProperty("--pad", compact ? "12px" : "16px");
    r.setProperty("--row-h", compact ? "38px" : "44px");
  }, [t.accent, t.density]);

  const toast = useCallback((msg) => {
    const id = Math.random();
    setToasts((s) => [...s, { id, msg }]);
    setTimeout(() => setToasts((s) => s.filter((x) => x.id !== id)), 2600);
  }, []);

  const go = useCallback((v, p = {}) => { setView(v); setParams(p); }, []);

  const vmAction = useCallback((vm, action) => {
    const msgs = {
      "Start": `Arrancando ${vm.name}… (virsh start)`,
      "Shutdown": `ACPI shutdown enviado a ${vm.name}`,
      "Force Off": `Force off de ${vm.name} (virsh destroy)`,
      "Clone": `Clonando ${vm.name}… (qemu-img convert)`,
      "Delete": `Eliminado ${vm.name} (con confirmación de disco)`,
      "External Console": `Lanzando virt-viewer para ${vm.name}…`,
    };
    toast(msgs[action] || `${action} · ${vm.name}`);
  }, [toast]);

  const app = {
    tweaks: t, setTweak, params,
    go,
    toast, vmAction,
    openConsole: (vm) => { if (vm) { setConsole_(vm); setConsoleFs(false); } else toast("No hay VM running con VNC"); },
    closeConsole: () => setConsole_(null),
    consoleFs, toggleConsoleFs: () => setConsoleFs((f) => !f),
    openMigration: (vm) => setMigration(vm || null),
    closeMigration: () => setMigration(undefined),
    openNewVm: (tpl) => setNewVm(tpl || null),
    closeNewVm: () => setNewVm(undefined),
  };

  const SCREENS = {
    dashboard: Dashboard, vms: VirtualMachines, labs: Labs, topology: LabTopology,
    templates: Templates, hosts: RemoteHosts, migrations: Migrations,
    diagnostics: Diagnostics, logs: ActivityLogs, settings: Settings, spec: Spec,
  };
  const Screen = SCREENS[view] || Dashboard;
  const flush = view === "vms" || view === "labs" || view === "topology" || view === "logs" || view === "spec";

  const { hub, hosts } = HG;
  const localHost = hosts.find((h) => h.local);
  const runningCount = HG.vms.filter((v) => v.state === "running").length;
  const navBadge = { vms: HG.vms.length, hosts: hosts.filter((h) => h.status === "online").length, migrations: HG.migrations.length };

  return (
    <div className="app-viewport">
      <div className="os-window">
        {/* titlebar */}
        <div className="titlebar">
          <div className="win-dots"><span className="win-dot close" /><span className="win-dot min" /><span className="win-dot max" /></div>
          <div className="tb-title" style={{ marginLeft: 6 }}>HyperGery <span className="faint">— VM Manager · Ubuntu KVM/QEMU/libvirt</span></div>
          <div className="grow" />
          <span className="faint" style={{ fontSize: 11 }}>aula.local</span>
        </div>

        <div className="app-body">
          {/* sidebar */}
          <div className="sidebar">
            <div className="brand">
              <div className="brand-mark"><Icon name="bolt" size={18} style={{ color: "#04141a" }} fill /></div>
              <div><div className="brand-name">Hyper<span>Gery</span></div><div className="brand-ver">v0.6.0 · RC-candidate</div></div>
            </div>
            <div className="nav">
              {NAV.slice(0, 9).map(([id, label, ico]) => (
                <div key={id} className={"nav-item " + (view === id ? "active" : "")} onClick={() => go(id)}>
                  <Icon name={ico} size={18} className="nav-ico" />{label}
                  {navBadge[id] != null && <span className="nav-badge">{navBadge[id]}</span>}
                </div>
              ))}
              <div className="nav-label">Sistema</div>
              {NAV.slice(9).map(([id, label, ico]) => (
                <div key={id} className={"nav-item " + (view === id ? "active" : "")} onClick={() => go(id)}>
                  <Icon name={ico} size={18} className="nav-ico" />{label}
                </div>
              ))}
            </div>
            <div className="sidebar-foot">
              <StatPill dot={hub.online ? "ok" : "bad"} label="Hub" value={hub.online ? "online" : "offline"} />
              <div className="row gap8" style={{ fontSize: 11.5 }} >
                <span className="faint">{localHost.name.split("(")[0]}</span>
              </div>
            </div>
          </div>

          {/* main column */}
          <div className="main-col">
            {/* top bar */}
            <div className="topbar">
              <div className="crumbs">
                <span className="page-title">{(NAV.find((n) => n[0] === view) || [])[1]}</span>
              </div>
              <div className="topbar-spacer" />
              <StatPill dot={hub.online ? "ok" : "bad"} label="Hub" value={hub.online ? "Online" : "Offline"} />
              <StatPill dot="accent" label="Host" value={HG.HOST_LOCAL} mono />
              <StatPill dot={hub.nasWritable ? "ok" : "bad"} label="NAS" value={hub.nasWritable ? "Writable" : "RO"} />
              <div style={{ width: 1, height: 26, background: "var(--border)", margin: "0 2px" }} />
              <Btn size="sm" icon="plus" variant="primary" onClick={() => app.openNewVm()}>New VM</Btn>
              <Btn size="sm" icon="refresh" variant="ghost" iconOnly onClick={() => toast("Inventario actualizado")} />
              <Btn size="sm" icon="settings" variant="ghost" iconOnly onClick={() => go("settings")} />
            </div>

            {/* content */}
            <div className={"content" + (flush ? " flush" : "")} style={flush ? { padding: "22px 24px 16px", display: "flex", flexDirection: "column" } : undefined} key={view}>
              <Screen app={app} />
            </div>

            {/* activity log strip */}
            <div className="logstrip">
              <div className="logstrip-head" onClick={() => setLogOpen((o) => !o)}>
                <Icon name="logs" size={14} />
                <b style={{ color: "var(--text)", fontWeight: 600 }}>Activity Log</b>
                <span className="lsrc-vm">{HG.logs[0].t}</span>
                <span className="grow" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontFamily: "var(--font-mono)" }}>{HG.logs[0].msg}</span>
                <Icon name={logOpen ? "chevdown" : "chevron"} size={14} style={{ transform: logOpen ? "rotate(180deg)" : "rotate(-90deg)" }} />
              </div>
              {logOpen && (
                <div className="logstrip-body">
                  {HG.logs.map((l, i) => (
                    <div key={i} className={"logline " + (l.level === "error" ? "err" : "")}>
                      <span className="ts">{l.t}</span><span className={"src lsrc-" + l.src}>{l.src.toUpperCase()}</span><span className="msg grow">{l.msg}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* overlays */}
        {console_ && <ConsoleWindow vm={console_} app={app} />}
        {migration !== undefined && <MigrationWizard app={app} initialVm={migration} />}
        {newVm !== undefined && <NewVmDialog app={app} template={newVm} />}
        <Toasts items={toasts} />
      </div>

      {/* Tweaks panel */}
      <TweaksPanel>
        <TweakSection label="Apariencia" />
        <TweakColor label="Acento" value={t.accent} options={["#22D3EE", "#38BDF8", "#60A5FA"]} onChange={(v) => setTweak("accent", v)} />
        <TweakRadio label="Densidad" value={t.density} options={["comfortable", "compact"]} onChange={(v) => setTweak("density", v)} />
        <TweakSection label="Pantallas" />
        <TweakRadio label="Vista de VMs" value={t.vmView} options={["table", "cards"]} onChange={(v) => setTweak("vmView", v)} />
        <TweakRadio label="Dashboard" value={t.dashboardMode} options={["metrics", "actions"]} onChange={(v) => setTweak("dashboardMode", v)} />
      </TweaksPanel>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
