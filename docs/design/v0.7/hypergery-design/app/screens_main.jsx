/* HyperGery screens: Dashboard + Virtual Machines */
const { useState: useStateM, useMemo: useMemoM } = React;

/* ============================== DASHBOARD ============================== */
function Dashboard({ app }) {
  const { vms, hub, hosts, migrations, diagnostics } = HG;
  const running = vms.filter((v) => v.state === "running").length;
  const shutoff = vms.filter((v) => v.state === "shutoff").length;
  const paused = vms.filter((v) => v.state === "paused").length;
  const hostsOnline = hosts.filter((h) => h.status === "online").length;
  const failCount = diagnostics.filter((d) => d.status === "FAIL").length;
  const warnCount = diagnostics.filter((d) => d.status === "WARN").length;
  const localHost = hosts.find((h) => h.local);
  const ramPct = Math.round(((localHost.ramTotal - localHost.ramFree) / localHost.ramTotal) * 100);
  const diskPct = Math.round(((localHost.diskTotal - localHost.diskFree) / localHost.diskTotal) * 100);
  const offlineHost = hosts.find((h) => h.status === "offline");
  const metricsMode = app.tweaks.dashboardMode !== "actions";

  const quick = [
    { ico: "plus", t: "New VM", s: "Crear desde ISO", go: () => app.openNewVm() },
    { ico: "labs", t: "New Lab", s: "Entorno aislado", go: () => app.go("labs") },
    { ico: "terminal", t: "Open Console", s: "VNC integrada", go: () => app.openConsole(vms.find((v) => v.state === "running" && v.display === "VNC")) },
    { ico: "migrations", t: "Live Migration", s: "NAS Clone", go: () => app.openMigration() },
    { ico: "doctor", t: "Run Doctor", s: "Diagnóstico", go: () => app.go("diagnostics") },
    { ico: "settings", t: "Open Settings", s: "Hub · NAS · VM", go: () => app.go("settings") },
  ];

  const stat = (icon, dot, big, unit, label, sub) => (
    <div className="card pad">
      <div className="row spread" style={{ marginBottom: 12 }}>
        <span className="dim" style={{ fontSize: 12.5, fontWeight: 600 }}>{label}</span>
        <Icon name={icon} size={17} style={{ color: "var(--text-faint)" }} />
      </div>
      <div className="row" style={{ alignItems: "baseline", gap: 8 }}>
        {dot && <span className={"dot " + dot} style={{ alignSelf: "center" }} />}
        <span className="metric"><span className="big">{big}</span> <span className="unit">{unit}</span></span>
      </div>
      <div className="dim" style={{ fontSize: 12, marginTop: 8 }}>{sub}</div>
    </div>
  );

  return (
    <div className="viewfade">
      <div className="page-head row spread" style={{ alignItems: "flex-end" }}>
        <div>
          <h1>Dashboard</h1>
          <p>Estado del host local, del Hub en NAS y de los hosts remotos del aula.</p>
        </div>
        <Seg value={app.tweaks.dashboardMode || "metrics"} onChange={(v) => app.setTweak("dashboardMode", v)}
          options={[{ value: "metrics", label: "Métricas" }, { value: "actions", label: "Acciones" }]} />
      </div>

      <div className="grid" style={{ gridTemplateColumns: "repeat(4, 1fr)", marginBottom: 16 }}>
        {stat("vm", "ok", running, "running", "Virtual Machines", `${shutoff} shutoff · ${paused} paused · ${vms.length} total`)}
        {stat("database", hub.online ? "ok" : "bad", hub.online ? "Online" : "Offline", "", "HyperGery Hub", `${hub.latency} ms · ${hub.vmRecords} VM records`)}
        {stat("folder", hub.nasWritable ? "ok" : "bad", hub.nasWritable ? "Writable" : "Read-only", "", "NAS Staging", "/mnt/hypergery-nas/hypergery")}
        {stat("server", hostsOnline === hosts.length ? "ok" : "warn", hostsOnline, `/ ${hosts.length}`, "Hosts online", offlineHost ? `${offlineHost.id} offline` : "todos operativos")}
      </div>

      {/* Quick actions */}
      <div className="grid" style={{ gridTemplateColumns: metricsMode ? "1.55fr 1fr" : "1fr", gap: 16 }}>
        <div className="col gap16">
          <Card title="Acciones rápidas" icon="bolt" bodyClass="pad">
            <div style={{ padding: "var(--pad)" }}>
              <div className="grid" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
                {quick.map((q) => (
                  <div key={q.t} className="quick" onClick={q.go}>
                    <div className="qico"><Icon name={q.ico} size={18} /></div>
                    <div><div className="qt">{q.t}</div><div className="qs">{q.s}</div></div>
                  </div>
                ))}
              </div>
            </div>
          </Card>

          {/* Warnings */}
          <Card title="Avisos" icon="alert" sub={`${warnCount + (offlineHost ? 1 : 0)} para revisar`} bodyClass="pad">
            <div className="col gap10" style={{ padding: "var(--pad)" }}>
              {offlineHost && (
                <Callout tone="warn">
                  <b>{offlineHost.id} está offline.</b> Último heartbeat {offlineHost.heartbeat}. No disponible como destino de migración.
                </Callout>
              )}
              <Callout tone="warn">
                <b>Docker Compose no disponible en este equipo.</b> Es esperado: el Hub corre en el NAS. El doctor lo marca como WARN, no FAIL.
              </Callout>
              <Callout tone="info">
                <b>Win11-Client01 usa SPICE.</b> La consola integrada requiere VNC — usa el visor externo o cambia a VNC con la VM apagada.
              </Callout>
            </div>
          </Card>
        </div>

        {metricsMode && (
          <div className="col gap16">
            <Card title="Recursos · host local" icon="cpu" sub={localHost.name} bodyClass="pad">
              <div style={{ padding: "var(--pad)" }}>
                <div className="row" style={{ justifyContent: "space-around", marginBottom: 16 }}>
                  <Gauge pct={ramPct} value={ramPct + "%"} label="RAM" tone="var(--accent)" />
                  <Gauge pct={diskPct} value={diskPct + "%"} label="Disco" tone="var(--accent-3)" />
                </div>
                <dl className="kv">
                  <dt>RAM</dt><dd>{(localHost.ramTotal - localHost.ramFree).toFixed(1)} / {localHost.ramTotal} GB</dd>
                  <dt>Disco</dt><dd>{(localHost.diskTotal - localHost.diskFree)} / {localHost.diskTotal} GB</dd>
                  <dt>VMs activas</dt><dd>{localHost.activeVms}</dd>
                </dl>
              </div>
            </Card>

            <Card title="Último diagnóstico" icon="diagnostics" right={<Btn size="xs" variant="ghost" icon="refresh" onClick={() => app.go("diagnostics")}>Doctor</Btn>} bodyClass="pad">
              <div className="col gap10" style={{ padding: "var(--pad)" }}>
                <div className="row gap10">
                  <span className="chip ok"><i className="cdot" />{diagnostics.length - failCount - warnCount} OK</span>
                  <span className="chip warn"><i className="cdot" />{warnCount} WARN</span>
                  <span className="chip danger"><i className="cdot" />{failCount} FAIL</span>
                </div>
                <div className="dim" style={{ fontSize: 12 }}>Sin fallos críticos. KVM, libvirt y Hub operativos.</div>
              </div>
            </Card>
          </div>
        )}
      </div>

      {/* Recent migrations */}
      <Card title="Últimas migraciones" icon="migrations" className="" style={{ marginTop: 16 }}
        right={<Btn size="xs" variant="ghost" icon="chevron" onClick={() => app.go("migrations")}>Ver todas</Btn>} noBody>
        <table className="tbl">
          <thead><tr><th>Migration ID</th><th>VM origen</th><th>Ruta</th><th>VM destino</th><th>Tamaño</th><th>Estado</th><th>Cuándo</th></tr></thead>
          <tbody>
            {migrations.map((m) => (
              <tr key={m.id} onClick={() => app.go("migrations")}>
                <td className="mono">{m.id}</td>
                <td className="name">{m.vm}</td>
                <td className="mono">{m.from} → {m.to}</td>
                <td className="mono">{m.targetVm}</td>
                <td className="mono">{m.size}</td>
                <td>{m.state === "done" ? <span className="chip ok"><i className="cdot" />DONE</span> : <span className="chip danger"><i className="cdot" />FAILED</span>}</td>
                <td className="dim">{m.when}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

/* ============================== VIRTUAL MACHINES ============================== */
function VMActionBar({ vm, app, compact }) {
  const isRun = vm.state === "running";
  const isOff = vm.state === "shutoff";
  return (
    <div className="row wrap gap6">
      <Btn size={compact ? "xs" : "sm"} variant="success" icon="play" disabled={isRun} onClick={() => app.vmAction(vm, "Start")}>Start</Btn>
      <Btn size={compact ? "xs" : "sm"} icon="power" disabled={!isRun} onClick={() => app.vmAction(vm, "Shutdown")}>Shutdown</Btn>
      <Btn size={compact ? "xs" : "sm"} icon="stop" disabled={isOff} onClick={() => app.vmAction(vm, "Force Off")}>Force Off</Btn>
      <Btn size={compact ? "xs" : "sm"} variant="primary" icon="terminal" onClick={() => app.openConsole(vm)}>Console</Btn>
      {!compact && <>
        <Btn size="sm" icon="external" onClick={() => app.vmAction(vm, "External Console")}>External</Btn>
        <Btn size="sm" icon="camera" onClick={() => app.go("vms", { vm: vm.id, tab: "Snapshots" })}>Snapshots</Btn>
        <Btn size="sm" icon="clone" disabled={!isOff} onClick={() => app.vmAction(vm, "Clone")}>Clone</Btn>
        <Btn size="sm" icon="migrations" onClick={() => app.openMigration(vm)}>Live Migration</Btn>
        <Btn size="sm" icon="settings" onClick={() => app.toast("VM Settings (próximamente)")}>Settings</Btn>
        <Btn size="sm" variant="danger" icon="trash" onClick={() => app.vmAction(vm, "Delete")}>Delete</Btn>
      </>}
    </div>
  );
}

function VMDetails({ vm, app }) {
  const [tab, setTab] = useStateM(app.params.tab || "General");
  const lab = HG.labs.find((l) => l.id === vm.lab);
  const snaps = [
    { name: "base-install", when: "01 jun 09:14", size: "2.1 GB", current: false },
    { name: "post-sysprep", when: "02 jun 16:40", size: "3.4 GB", current: true },
  ];
  return (
    <div className="card" style={{ display: "flex", flexDirection: "column", minHeight: 0, height: "100%" }}>
      <div className="card-head">
        <Icon name="vm" size={18} style={{ color: "var(--accent)" }} />
        <div className="col" style={{ gap: 2 }}>
          <h3>{vm.name}</h3>
          <span className="sub mono">{vm.os}</span>
        </div>
        <div className="spacer" />
        <StateChip state={vm.state} />
      </div>
      <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--border)" }}>
        <VMActionBar vm={vm} app={app} compact />
        <div className="row wrap gap6" style={{ marginTop: 8 }}>
          <Btn size="xs" icon="external" onClick={() => app.vmAction(vm, "External Console")}>External</Btn>
          <Btn size="xs" icon="clone" disabled={vm.state !== "shutoff"} onClick={() => app.vmAction(vm, "Clone")}>Clone</Btn>
          <Btn size="xs" icon="migrations" onClick={() => app.openMigration(vm)}>Migrate</Btn>
          <Btn size="xs" variant="danger" icon="trash" onClick={() => app.vmAction(vm, "Delete")}>Delete</Btn>
        </div>
      </div>
      <div style={{ padding: "0 8px" }}>
        <Tabs value={tab} onChange={setTab} options={["General", "System", "Storage", "Network", "Snapshots", "Logs", "Console"]} />
      </div>
      <div className="pad" style={{ padding: 16, overflowY: "auto", flex: 1 }}>
        {tab === "General" && (
          <dl className="kv">
            <dt>Estado</dt><dd><StateChip state={vm.state} /></dd>
            <dt>Lab</dt><dd>{lab ? lab.name : "—"}</dd>
            <dt>Rol</dt><dd><RoleBadge role={vm.role} /></dd>
            <dt>Host</dt><dd>{vm.host}</dd>
            <dt>Uptime</dt><dd>{vm.uptime}</dd>
            <dt>UUID</dt><dd style={{ fontSize: 11 }}>{vm.uuid}</dd>
            <dt>Display</dt><dd>{vm.display}{vm.vnc ? ` (${vm.vnc})` : vm.spicePort ? ` (:${vm.spicePort})` : ""}</dd>
            <dt>IP</dt><dd>{vm.ip || "—"}</dd>
          </dl>
        )}
        {tab === "System" && (
          <div className="col gap16">
            <dl className="kv">
              <dt>vCPU</dt><dd>{vm.cpu} cores</dd>
              <dt>Carga CPU</dt><dd>{vm.cpuLoad}%</dd>
              <dt>RAM</dt><dd>{vm.ram} MiB</dd>
              <dt>Chipset</dt><dd>q35 · UEFI (OVMF)</dd>
              <dt>Aceleración</dt><dd>KVM</dd>
            </dl>
            <div className="col gap8">
              <div className="row spread"><span className="dim" style={{ fontSize: 12 }}>CPU</span><span className="mono" style={{ fontSize: 12 }}>{vm.cpuLoad}%</span></div>
              <Bar pct={vm.cpuLoad} />
              <div className="row spread"><span className="dim" style={{ fontSize: 12 }}>RAM</span><span className="mono" style={{ fontSize: 12 }}>{vm.ramUsed} / {vm.ram} MiB</span></div>
              <Bar pct={Math.round((vm.ramUsed / vm.ram) * 100)} />
            </div>
          </div>
        )}
        {tab === "Storage" && (
          <div className="col gap12">
            <div className="card" style={{ background: "var(--surface-2)" }}>
              <div className="row gap10 pad" style={{ padding: 14 }}>
                <Icon name="disk" size={20} style={{ color: "var(--accent-3)" }} />
                <div className="grow">
                  <div className="row spread"><b style={{ fontSize: 13 }}>{vm.name.toLowerCase()}.qcow2</b><span className="mono dim" style={{ fontSize: 12 }}>{vm.diskUsed} / {vm.disk} GB</span></div>
                  <div className="mono faint" style={{ fontSize: 11, margin: "4px 0 8px" }}>~/.local/share/hypergery/vms/{vm.id}/</div>
                  <Bar pct={Math.round((vm.diskUsed / vm.disk) * 100)} tone="" />
                </div>
              </div>
            </div>
            <Callout tone="info">Formato qcow2 con asignación dinámica. Bus virtio para máximo rendimiento.</Callout>
          </div>
        )}
        {tab === "Network" && (
          <dl className="kv">
            <dt>Red lab</dt><dd>{lab ? lab.net : "default"}</dd>
            <dt>Bridge</dt><dd>{lab ? lab.bridge : "virbr0"}</dd>
            <dt>Subnet</dt><dd>{lab ? lab.subnet : "192.168.122.0/24"}</dd>
            <dt>IP</dt><dd>{vm.ip || "sin lease"}</dd>
            <dt>MAC</dt><dd>{vm.mac}</dd>
            <dt>Modelo</dt><dd>virtio-net</dd>
          </dl>
        )}
        {tab === "Snapshots" && (
          <div className="col gap10">
            <div className="row spread"><span className="dim" style={{ fontSize: 12.5 }}>{snaps.length} snapshots</span>
              <Btn size="xs" variant="primary" icon="camera" onClick={() => app.toast("Snapshot creado: snap-" + Date.now().toString().slice(-4))}>Tomar snapshot</Btn></div>
            {snaps.map((s) => (
              <div key={s.name} className="card row spread" style={{ background: "var(--surface-2)", padding: "10px 12px" }}>
                <div className="row gap10"><Icon name="camera" size={16} style={{ color: s.current ? "var(--accent)" : "var(--text-faint)" }} />
                  <div><div className="row gap8"><b style={{ fontSize: 13 }}>{s.name}</b>{s.current && <span className="chip accent" style={{ fontSize: 10 }}><i className="cdot" />CURRENT</span>}</div>
                    <span className="faint mono" style={{ fontSize: 11 }}>{s.when} · {s.size}</span></div></div>
                <div className="row gap6"><Btn size="xs" icon="refresh">Revert</Btn><Btn size="xs" variant="danger" iconOnly icon="trash" /></div>
              </div>
            ))}
          </div>
        )}
        {tab === "Logs" && (
          <div className="card" style={{ background: "#070b12", fontFamily: "var(--font-mono)", fontSize: 11.5, padding: 12, lineHeight: 1.7 }}>
            <div className="dim">[{vm.name}] virsh define domain.xml → defined</div>
            <div className="dim">[{vm.name}] virsh start → ok</div>
            <div style={{ color: "var(--running)" }}>[{vm.name}] qemu: VNC server running on 127.0.0.1{vm.vnc}</div>
            <div className="dim">[{vm.name}] guest agent: connected</div>
            {vm.ip && <div className="dim">[{vm.name}] dhcp lease → {vm.ip}</div>}
          </div>
        )}
        {tab === "Console" && (
          <div className="col gap12">
            <Callout tone={vm.display === "SPICE" ? "warn" : "info"}>
              {vm.display === "SPICE"
                ? <span><b>Esta VM usa SPICE.</b> La consola integrada requiere VNC. Usa el visor externo o cambia a VNC con la VM apagada.</span>
                : <span><b>Display VNC ({vm.vnc}).</b> La consola integrada se conecta automáticamente cuando la VM está en running.</span>}
            </Callout>
            <Btn variant="primary" icon="terminal" onClick={() => app.openConsole(vm)}>Abrir HyperGery Console</Btn>
            <span className="faint" style={{ fontSize: 11.5 }}>Cerrar la consola no detiene la VM.</span>
          </div>
        )}
      </div>
    </div>
  );
}

function VirtualMachines({ app }) {
  const [q, setQ] = useStateM("");
  const [labFilter, setLabFilter] = useStateM("all");
  const [sel, setSel] = useStateM(app.params.vm || HG.vms[0].id);
  const view = app.tweaks.vmView || "table";

  const list = useMemoM(() => HG.vms.filter((v) =>
    (labFilter === "all" || v.lab === labFilter) &&
    (v.name.toLowerCase().includes(q.toLowerCase()) || (v.ip || "").includes(q))
  ), [q, labFilter]);
  const vm = HG.vms.find((v) => v.id === sel) || list[0];

  const labOpts = [{ value: "all", label: "Todos los labs" }, ...HG.labs.map((l) => ({ value: l.id, label: l.name }))];

  return (
    <div className="viewfade" style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      <div className="page-head">
        <h1>Virtual Machines</h1>
        <p>Máquinas gestionadas por KVM/QEMU/libvirt en este host y hosts remotos del Hub.</p>
      </div>

      <Toolbar>
        <div className="row" style={{ position: "relative" }}>
          <Icon name="search" size={15} style={{ position: "absolute", left: 11, color: "var(--text-faint)" }} />
          <input className="input mono" placeholder="Buscar VM o IP…" value={q} onChange={(e) => setQ(e.target.value)}
            style={{ width: 240, paddingLeft: 32, height: 36 }} />
        </div>
        <select className="select" value={labFilter} onChange={(e) => setLabFilter(e.target.value)} style={{ width: 200, height: 36 }}>
          {labOpts.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <div className="grow" />
        <Seg value={view} onChange={(v) => app.setTweak("vmView", v)} options={[{ value: "table", label: "Tabla" }, { value: "cards", label: "Cards" }]} />
        <Btn icon="refresh" variant="ghost" onClick={() => app.toast("Inventario actualizado")} />
        <Btn icon="plus" variant="primary" onClick={() => app.openNewVm()}>New VM</Btn>
      </Toolbar>

      <div style={{ flex: 1, minHeight: 0, display: "grid", gridTemplateColumns: "1fr 400px", gap: 16 }}>
        <div style={{ minHeight: 0, overflowY: "auto" }}>
          {view === "table" ? (
            <div className="card" style={{ overflow: "hidden" }}>
              <table className="tbl">
                <thead><tr><th>Nombre</th><th>Lab</th><th>CPU</th><th>RAM</th><th>Disco</th><th>Display</th><th>IP</th><th>Estado</th></tr></thead>
                <tbody>
                  {list.map((v) => {
                    const lab = HG.labs.find((l) => l.id === v.lab);
                    const labShort = lab ? lab.name.split("·")[0].trim() : "—";
                    return (
                      <tr key={v.id} className={v.id === sel ? "selected" : ""} onClick={() => setSel(v.id)}>
                        <td><div className="row gap8"><RoleBadge role={v.role} /><span className="name">{v.name}</span></div></td>
                        <td><span className="chip plain" style={{ fontSize: 10.5 }}>{labShort}</span></td>
                        <td className="mono">{v.cpu}</td>
                        <td className="mono">{(v.ram / 1024).toFixed(0)}G</td>
                        <td className="mono">{v.disk}G</td>
                        <td><span className={"chip " + (v.display === "SPICE" ? "warn" : "plain")} style={{ fontSize: 10.5 }}>{v.display}</span></td>
                        <td className="mono nowrap">{v.ip || "—"}</td>
                        <td><StateChip state={v.state} /></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(258px, 1fr))" }}>
              {list.map((v) => {
                const lab = HG.labs.find((l) => l.id === v.lab);
                return (
                  <div key={v.id} className="card pad" onClick={() => setSel(v.id)}
                    style={{ cursor: "pointer", padding: 15, borderColor: v.id === sel ? "var(--accent-line)" : undefined }}>
                    <div className="row spread" style={{ marginBottom: 10 }}>
                      <div className="row gap8"><Icon name={v.os.includes("Windows") ? "win" : v.role === "Router" ? "route" : "vm"} size={18} style={{ color: "var(--accent)" }} /><RoleBadge role={v.role} /></div>
                      <StateChip state={v.state} />
                    </div>
                    <div style={{ fontWeight: 650, fontSize: 14, marginBottom: 2 }}>{v.name}</div>
                    <div className="faint mono" style={{ fontSize: 11, marginBottom: 12 }}>{v.os}</div>
                    <dl className="kv" style={{ gridTemplateColumns: "auto 1fr", fontSize: 12, gap: "5px 10px" }}>
                      <dt>CPU/RAM</dt><dd>{v.cpu} · {(v.ram/1024).toFixed(0)} GB</dd>
                      <dt>IP</dt><dd>{v.ip || "—"}</dd>
                      <dt>Display</dt><dd>{v.display}</dd>
                    </dl>
                  </div>
                );
              })}
            </div>
          )}
        </div>
        {vm && <VMDetails vm={vm} app={{ ...app, params: app.params }} key={vm.id} />}
      </div>
    </div>
  );
}

Object.assign(window, { Dashboard, VirtualMachines });
