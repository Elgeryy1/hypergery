/* HyperGery Console Window — separate-window mock, 3 states */
const { useState: useStateC, useEffect: useEffectC, useRef: useRefC } = React;

function FauxWindowsServer({ vm }) {
  return (
    <div style={{ width: "100%", height: "100%", position: "relative",
      background: "radial-gradient(120% 120% at 30% 10%, #0a3a66, #06243f 60%, #04162a)", color: "#eaf2ff",
      fontFamily: "Segoe UI, var(--font-sans)" }}>
      <div style={{ position: "absolute", top: 22, left: 22, width: 360 }}>
        <div style={{ background: "rgba(8,20,34,.86)", border: "1px solid rgba(120,170,220,.25)", borderRadius: 6, overflow: "hidden", boxShadow: "0 18px 50px rgba(0,0,0,.5)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", background: "#0c2034", borderBottom: "1px solid rgba(120,170,220,.18)", fontSize: 12.5 }}>
            <div style={{ width: 14, height: 14, borderRadius: 3, background: "#3b82f6" }} /> Server Manager · Dashboard
          </div>
          <div style={{ padding: 14, fontSize: 12, lineHeight: 1.9 }}>
            <div style={{ color: "#9fc4ec", fontWeight: 600, marginBottom: 6 }}>WELCOME TO WINDOWS SERVER 2022</div>
            <div>Roles and Features</div>
            <div style={{ color: "#7dd3fc" }}>● AD DS &nbsp; ● DNS Server &nbsp; ● DHCP</div>
            <div style={{ marginTop: 8, color: "#86efac" }}>Domain: aula.local — Forest functional level 2016</div>
            <div style={{ color: "#cbd5e1" }}>{vm.ip} / 24 · GW 10.20.0.1</div>
          </div>
        </div>
      </div>
      {/* taskbar */}
      <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 38, background: "rgba(6,16,28,.92)", borderTop: "1px solid rgba(120,170,220,.2)", display: "flex", alignItems: "center", gap: 12, padding: "0 14px", fontSize: 12 }}>
        <div style={{ width: 20, height: 20, borderRadius: 3, background: "linear-gradient(135deg,#38bdf8,#2563eb)" }} />
        <div style={{ color: "#9fb6d4" }}>{vm.name}</div>
        <div style={{ marginLeft: "auto", color: "#7e95b3" }}>{new Date().toTimeString().slice(0, 5)} · ENG</div>
      </div>
    </div>
  );
}

function FauxTerminal({ vm }) {
  const lines = vm.role === "Router"
    ? ["vyos@VyOS-Router:~$ show interfaces", "eth0   10.30.0.1/24   u/u   LAN-aula", "eth1   192.168.1.50/24  u/u   WAN", "vyos@VyOS-Router:~$ show ip route", "S>* 0.0.0.0/0 [210/0] via 192.168.1.1", "C>* 10.30.0.0/24 is directly connected, eth0", "vyos@VyOS-Router:~$ _"]
    : ["Ubuntu 24.04.1 LTS  " + vm.name + " tty1", "", vm.name.toLowerCase() + " login: alumno", "Last login: " + new Date().toDateString(), "alumno@" + vm.name.toLowerCase() + ":~$ ip -4 addr show | grep inet", "    inet 127.0.0.1/8 scope host lo", "    inet " + (vm.ip || "10.30.0.20") + "/24 scope global enp1s0", "alumno@" + vm.name.toLowerCase() + ":~$ _"];
  return (
    <div style={{ width: "100%", height: "100%", background: "#05070b", color: "#c7f0d8", fontFamily: "var(--font-mono)", fontSize: 13, padding: 18, lineHeight: 1.65 }}>
      {lines.map((l, i) => <div key={i} style={{ color: l.startsWith(vm.name) || l.includes("login") || l.includes("$") ? "#9fe6b8" : "#8fb0d6" }}>{l || "\u00a0"}</div>)}
    </div>
  );
}

function ConsoleWindow({ vm, app }) {
  const isVNCRun = vm.state === "running" && vm.display === "VNC";
  const isSpice = vm.display === "SPICE";
  const isOff = vm.state === "shutoff" || vm.state === "unknown";

  const [connected, setConnected] = useStateC(isVNCRun);
  const [connecting, setConnecting] = useStateC(false);
  const [captured, setCaptured] = useStateC(false);
  const [scaleFit, setScaleFit] = useStateC(true);

  useEffectC(() => {
    const h = (e) => { if (e.code === "ControlRight") { setCaptured(false); } };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  function doConnect() {
    setConnecting(true);
    setTimeout(() => { setConnecting(false); setConnected(true); }, 900);
  }

  const status = connecting ? "Connecting…" : connected ? "Connected" : "Disconnected";
  const statusDot = connecting ? "warn" : connected ? "ok" : "off";

  return (
    <div className="app-viewport" style={{ position: "absolute", inset: 0, zIndex: 70, padding: app.consoleFs ? 0 : 30 }}>
      <div className="os-window viewfade" style={{ maxWidth: app.consoleFs ? "100%" : 1080, maxHeight: app.consoleFs ? "100%" : 760 }}>
        {/* titlebar */}
        <div className="titlebar">
          <div className="win-dots">
            <span className="win-dot close" onClick={() => app.closeConsole()} style={{ cursor: "pointer" }} />
            <span className="win-dot min" /><span className="win-dot max" />
          </div>
          <Icon name="terminal" size={15} style={{ color: "var(--accent)", marginLeft: 4 }} />
          <div className="tb-title">HyperGery Console — <b>{vm.name}</b></div>
          <div className="grow" />
          <span className="faint" style={{ fontSize: 11, fontFamily: "var(--font-mono)" }}>libvirt · {vm.host}</span>
        </div>

        <div className="console-win">
          {/* toolbar */}
          <div className="console-toolbar">
            <Btn size="sm" variant={connected ? undefined : "success"} icon="plug" disabled={connected || connecting || !isVNCRun} onClick={doConnect}>Connect</Btn>
            <Btn size="sm" icon="unplug" disabled={!connected} onClick={() => { setConnected(false); setCaptured(false); }}>Disconnect</Btn>
            <Btn size="sm" icon="refresh" disabled={!isVNCRun} onClick={() => { setConnected(false); setCaptured(false); doConnect(); }}>Reconnect</Btn>
            <div style={{ width: 1, height: 22, background: "var(--border)", margin: "0 3px" }} />
            <Btn size="sm" icon="keyboard" disabled={!connected} onClick={() => app.toast("Ctrl+Alt+Del enviado a " + vm.name)}>Ctrl+Alt+Del</Btn>
            <Btn size="sm" icon="unplug" disabled={!captured} onClick={() => setCaptured(false)}>Release Input</Btn>
            <Btn size="sm" variant={scaleFit ? "primary" : undefined} icon="fit" onClick={() => setScaleFit((s) => !s)}>Scale to Fit</Btn>
            <Btn size="sm" icon="expand" onClick={() => app.toggleConsoleFs()}>Fullscreen</Btn>
            <div className="grow" />
            <Btn size="sm" icon="external" onClick={() => app.toast("Lanzando virt-viewer…")}>External Viewer</Btn>
            <Btn size="sm" variant="ghost" icon="x" onClick={() => app.closeConsole()}>Close</Btn>
          </div>

          {/* stage */}
          <div className="console-stage" onClick={() => { if (connected) setCaptured(true); }}
            style={{ cursor: connected && !captured ? "pointer" : "default", background: connecting ? "#000" : undefined }}>
            {connecting && (
              <div className="col center gap12">
                <Icon name="refresh" size={26} className="spin" style={{ color: "var(--accent)" }} />
                <span className="dim mono" style={{ fontSize: 13 }}>Negotiating VNC handshake · 127.0.0.1{vm.vnc}…</span>
              </div>
            )}

            {/* STATE 1: VNC connected framebuffer */}
            {connected && !connecting && (
              <div style={{ position: "relative", width: "100%", height: "100%", display: "grid", placeItems: "center", padding: scaleFit ? 0 : 0 }}>
                <div style={{ width: scaleFit ? "92%" : 1024, maxWidth: scaleFit ? 1024 : "none", aspectRatio: "4 / 3", maxHeight: "94%",
                  border: "1px solid #1f3147", borderRadius: 4, overflow: "hidden", boxShadow: "0 0 0 1px rgba(0,0,0,.6), 0 30px 80px -20px rgba(0,0,0,.8)" }}>
                  {vm.os.includes("Windows") ? <FauxWindowsServer vm={vm} /> : <FauxTerminal vm={vm} />}
                </div>
                {!captured && (
                  <div style={{ position: "absolute", bottom: 18, background: "rgba(8,14,24,.9)", border: "1px solid var(--border)", borderRadius: 8, padding: "8px 14px", fontSize: 12.5 }} className="row gap8 dim">
                    <Icon name="info" size={15} style={{ color: "var(--accent)" }} /> Haz clic para capturar el ratón y teclado — pulsa <span className="kbd">Right Ctrl</span> para liberar
                  </div>
                )}
                {captured && (
                  <div style={{ position: "absolute", top: 14, background: "var(--accent-bg)", border: "1px solid var(--accent-line)", borderRadius: 8, padding: "5px 12px", fontSize: 12 }} className="row gap8">
                    <span className="dot accent" /> Input capturado · <span className="kbd">Right Ctrl</span> libera
                  </div>
                )}
              </div>
            )}

            {/* STATE 2: SPICE */}
            {isSpice && !connecting && (
              <div className="card pad" style={{ maxWidth: 460, textAlign: "center", padding: 30 }}>
                <div style={{ width: 56, height: 56, borderRadius: 14, background: "var(--warning-bg)", display: "grid", placeItems: "center", margin: "0 auto 16px" }}>
                  <Icon name="monitor" size={26} style={{ color: "var(--warning)" }} />
                </div>
                <h3 style={{ margin: "0 0 8px", fontSize: 17 }}>Integrated console requires VNC</h3>
                <p className="dim" style={{ margin: "0 0 20px", fontSize: 13, lineHeight: 1.55 }}>
                  This VM uses SPICE. Use External Viewer, or switch to VNC while the VM is powered off.
                </p>
                <div className="row gap8" style={{ justifyContent: "center" }}>
                  <Btn variant="primary" icon="external" onClick={() => app.toast("Lanzando remote-viewer (SPICE)…")}>Open External Viewer</Btn>
                  <Btn icon="monitor" disabled={vm.state === "running"} onClick={() => app.toast("Cambiado a VNC (requiere VM apagada)")}>Switch to VNC</Btn>
                </div>
                {vm.state === "running" && <div className="faint" style={{ fontSize: 11.5, marginTop: 12 }}>“Switch to VNC” solo disponible con la VM apagada.</div>}
              </div>
            )}

            {/* STATE 3: powered off */}
            {isOff && !isSpice && !connecting && (
              <div className="card pad" style={{ maxWidth: 420, textAlign: "center", padding: 30 }}>
                <div style={{ width: 56, height: 56, borderRadius: 14, background: "var(--offline-bg)", display: "grid", placeItems: "center", margin: "0 auto 16px" }}>
                  <Icon name="power" size={26} style={{ color: "var(--offline)" }} />
                </div>
                <h3 style={{ margin: "0 0 8px", fontSize: 17 }}>VM is powered off</h3>
                <p className="dim" style={{ margin: "0 0 20px", fontSize: 13 }}>Arranca la VM para conectar la consola integrada.</p>
                <Btn variant="success" icon="play" onClick={() => { app.vmAction(vm, "Start"); }}>Start VM</Btn>
              </div>
            )}
          </div>

          {/* status bar */}
          <div className="console-statusbar">
            <span className="row gap6"><span className={"dot " + statusDot} />{status}</span>
            <span>{connected ? "1024 × 768" : "—"}</span>
            <span>Display: <b style={{ color: "var(--text)" }}>{vm.display}</b>{vm.vnc ? ` ${vm.vnc}` : vm.spicePort ? ` :${vm.spicePort}` : ""}</span>
            <span>Host Key: <span className="kbd">Right Ctrl</span></span>
            <span className="grow" />
            <span className="faint">Closing this window does not stop the VM</span>
          </div>
        </div>
      </div>
    </div>
  );
}

window.ConsoleWindow = ConsoleWindow;
