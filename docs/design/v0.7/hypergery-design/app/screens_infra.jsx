/* HyperGery: Remote Hosts + Hub, Labs, Lab Topology, Templates */
const { useState: useStateInf } = React;

/* ============================== REMOTE HOSTS ============================== */
function RemoteHosts({ app }) {
  const { hub, hosts } = HG;
  return (
    <div className="viewfade">
      <div className="page-head row spread" style={{ alignItems: "flex-end" }}>
        <div><h1>Remote Hosts</h1><p>Hosts del aula descubiertos por el HyperGery Hub en el NAS, con su inventario de VMs.</p></div>
        <Btn icon="refresh" onClick={() => app.toast("Consultando Hub…")}>Refresh</Btn>
      </div>

      {/* Hub card */}
      <div className="card" style={{ marginBottom: 16, borderColor: hub.online ? "rgba(34,211,238,.28)" : "rgba(239,68,68,.4)", background: "linear-gradient(180deg, rgba(34,211,238,.05), transparent 60%), var(--surface)" }}>
        <div className="row spread pad" style={{ padding: 18 }}>
          <div className="row gap14">
            <div style={{ width: 46, height: 46, borderRadius: 12, background: "var(--accent-bg)", display: "grid", placeItems: "center" }}><Icon name="database" size={24} style={{ color: "var(--accent)" }} /></div>
            <div>
              <div className="row gap10" style={{ alignItems: "center" }}><h3 style={{ margin: 0, fontSize: 16 }}>HyperGery Hub</h3>
                {hub.online ? <span className="chip ok"><i className="cdot" />ONLINE · {hub.health.toUpperCase()}</span> : <span className="chip danger"><i className="cdot" />OFFLINE</span>}</div>
              <div className="mono dim" style={{ fontSize: 12, marginTop: 3 }}>{hub.url} · NAS Docker · {hub.lastCheck}</div>
            </div>
          </div>
          <Btn size="sm" icon="settings" onClick={() => app.go("settings", { tab: "Hub" })}>Config Hub</Btn>
        </div>
        <div className="divider" />
        <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)" }}>
          {[["Latency", hub.latency + " ms", "ok"], ["Hosts online", hub.hostsOnline + " / " + hub.hostsTotal, hub.hostsOnline === hub.hostsTotal ? "ok" : "warn"],
            ["VM inventory", hub.vmRecords + " records", "ok"], ["NAS staging", hub.nasWritable ? "Writable" : "Read-only", hub.nasWritable ? "ok" : "bad"],
            ["Docker", hub.docker, "ok"]].map(([l, v, dot], i) => (
            <div key={l} style={{ padding: "14px 18px", borderLeft: i ? "1px solid var(--border)" : "none" }}>
              <div className="faint" style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: ".06em", marginBottom: 6 }}>{l}</div>
              <div className="row gap8"><span className={"dot " + dot} /><span style={{ fontSize: 15, fontWeight: 600 }} className="mono">{v}</span></div>
            </div>
          ))}
        </div>
      </div>

      {/* Hosts */}
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(330px, 1fr))" }}>
        {hosts.map((h) => {
          const off = h.status === "offline";
          const ramPct = off ? 0 : Math.round(((h.ramTotal - h.ramFree) / h.ramTotal) * 100);
          return (
            <div key={h.id} className="card" style={{ opacity: off ? .82 : 1, borderColor: off ? "rgba(239,68,68,.3)" : undefined }}>
              <div className="row spread pad" style={{ padding: 14, borderBottom: "1px solid var(--border)" }}>
                <div className="row gap10"><Icon name="server" size={18} style={{ color: off ? "var(--offline)" : "var(--accent)" }} />
                  <div><div className="row gap8"><b style={{ fontSize: 13.5 }}>{h.id}</b>{h.local && <span className="chip accent" style={{ fontSize: 10 }}><i className="cdot" />LOCAL</span>}</div>
                    <span className="faint mono" style={{ fontSize: 11 }}>{h.ip} · {h.cpu}</span></div></div>
                {off ? <span className="chip danger"><i className="cdot" />OFFLINE</span> : <span className="chip ok"><i className="cdot" />ONLINE</span>}
              </div>
              <div className="pad" style={{ padding: 14 }}>
                {off ? (
                  <Callout tone="danger" style={{ marginBottom: 12 }}>Sin heartbeat desde {h.heartbeat}. No disponible como destino de migración.</Callout>
                ) : (
                  <div className="col gap10" style={{ marginBottom: 12 }}>
                    <div className="row gap14">
                      <span className="row gap6" style={{ fontSize: 12 }}>{h.kvm ? <Icon name="check" size={14} style={{ color: "var(--running)" }} /> : <Icon name="x" size={14} style={{ color: "var(--danger)" }} />} KVM</span>
                      <span className="row gap6" style={{ fontSize: 12 }}>{h.libvirt ? <Icon name="check" size={14} style={{ color: "var(--running)" }} /> : <Icon name="x" size={14} style={{ color: "var(--danger)" }} />} libvirt</span>
                      <span className="grow" /><span className="dim" style={{ fontSize: 12 }}><b className="mono" style={{ color: "var(--text)" }}>{h.activeVms}</b> VMs activas</span>
                    </div>
                    <div className="row spread"><span className="dim" style={{ fontSize: 12 }}>RAM</span><span className="mono" style={{ fontSize: 12 }}>{(h.ramTotal - h.ramFree).toFixed(1)} / {h.ramTotal} GB</span></div>
                    <Bar pct={ramPct} />
                    <div className="row spread"><span className="dim" style={{ fontSize: 12 }}>Disco libre</span><span className="mono" style={{ fontSize: 12 }}>{h.diskFree} / {h.diskTotal} GB</span></div>
                  </div>
                )}
                <div className="faint mono" style={{ fontSize: 11, marginBottom: 12 }}>heartbeat {h.heartbeat}</div>
                <div className="row gap6 wrap">
                  <Btn size="xs" icon="bolt" disabled={off} onClick={() => app.toast("Test host " + h.id + ": OK")}>Test</Btn>
                  <Btn size="xs" icon="vm" onClick={() => app.go("vms")}>View VMs</Btn>
                  {!h.local && <Btn size="xs" variant={off ? undefined : "primary"} icon="migrations" disabled={off} onClick={() => app.openMigration()}>Migration target</Btn>}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ============================== LABS ============================== */
function Labs({ app }) {
  const [sel, setSel] = useStateInf(HG.labs[0].id);
  const lab = HG.labs.find((l) => l.id === sel);
  const labVms = lab ? lab.vms.map((id) => HG.vms.find((v) => v.id === id)).filter(Boolean) : [];

  return (
    <div className="viewfade" style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      <div className="page-head row spread" style={{ alignItems: "flex-end" }}>
        <div><h1>Labs</h1><p>Entornos aislados para prácticas de SMX/ASIX, cada uno con su red, bridge y subnet.</p></div>
        <Btn variant="primary" icon="plus" onClick={() => app.toast("Asistente New Lab")}>New Lab</Btn>
      </div>

      <div style={{ flex: 1, minHeight: 0, display: "grid", gridTemplateColumns: "300px 1fr", gap: 16 }}>
        <div className="card" style={{ overflowY: "auto" }}>
          {HG.labs.map((l) => (
            <div key={l.id} onClick={() => setSel(l.id)} style={{ padding: 14, cursor: "pointer", borderBottom: "1px solid var(--border-soft)", borderLeft: l.id === sel ? "3px solid var(--accent)" : "3px solid transparent", background: l.id === sel ? "var(--accent-bg)" : "transparent" }}>
              <div className="row gap8" style={{ marginBottom: 4 }}><Icon name="labs" size={16} style={{ color: "var(--accent)" }} /><b style={{ fontSize: 13.5 }}>{l.name}</b></div>
              <div className="faint mono" style={{ fontSize: 11 }}>{l.subnet} · {l.vms.length} VMs</div>
            </div>
          ))}
        </div>

        <div className="card" style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
          <div className="card-head">
            <div className="col" style={{ gap: 2 }}><h3>{lab.name}</h3><span className="sub">{lab.desc}</span></div>
            <div className="spacer" />
            <Btn size="xs" icon="route" variant="primary" onClick={() => app.go("topology", { lab: lab.id })}>Topología</Btn>
          </div>
          <div className="pad" style={{ padding: 16, overflowY: "auto", flex: 1 }}>
            <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", marginBottom: 16 }}>
              <dl className="kv"><dt>Red libvirt</dt><dd>{lab.net}</dd><dt>Bridge</dt><dd>{lab.bridge}</dd><dt>Subnet</dt><dd>{lab.subnet}</dd></dl>
              <div className="col gap8"><span className="dim" style={{ fontSize: 12 }}>Templates usados</span><div className="row wrap gap6">{lab.templates.map((t) => <span key={t} className="chip plain" style={{ fontSize: 10.5 }}>{t}</span>)}</div></div>
            </div>
            <div className="row spread" style={{ marginBottom: 10 }}><span className="dim" style={{ fontSize: 12.5, fontWeight: 600 }}>VMs del lab ({labVms.length})</span></div>
            <div className="col gap8" style={{ marginBottom: 18 }}>
              {labVms.map((v) => (
                <div key={v.id} className="card row spread" style={{ background: "var(--surface-2)", padding: "10px 13px" }}>
                  <div className="row gap10"><RoleBadge role={v.role} /><div><div style={{ fontSize: 13, fontWeight: 600 }}>{v.name}</div><div className="faint mono" style={{ fontSize: 11 }}>{v.ip || "sin IP"} · {v.host}</div></div></div>
                  <div className="row gap8"><StateChip state={v.state} /><Btn size="xs" icon="terminal" onClick={() => app.openConsole(v)} /></div>
                </div>
              ))}
            </div>
            <div className="row wrap gap8">
              <Btn size="sm" icon="edit">Rename</Btn>
              <Btn size="sm" icon="clone">Duplicate</Btn>
              <Btn size="sm" icon="download">Export</Btn>
              <Btn size="sm" icon="upload">Import</Btn>
              <Btn size="sm" variant="danger" icon="trash">Delete</Btn>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ============================== LAB TOPOLOGY ============================== */
function LabTopology({ app }) {
  const labId = app.params.lab || HG.labs[0].id;
  const lab = HG.labs.find((l) => l.id === labId);
  const vms = lab.vms.map((id) => HG.vms.find((v) => v.id === id)).filter(Boolean);
  const [selNode, setSelNode] = useStateInf("net");

  const stateColor = { running: "var(--running)", shutoff: "var(--offline)", paused: "var(--warning)", unknown: "var(--accent-3)" };
  // layout positions (% of canvas)
  const netPos = { x: 16, y: 50 };
  const vmPos = vms.map((_, i) => ({ x: 62, y: 14 + (i * 72) / Math.max(1, vms.length - 1) || 50 }));
  if (vms.length === 1) vmPos[0] = { x: 62, y: 50 };

  const selVm = selNode !== "net" ? vms.find((v) => v.id === selNode) : null;

  return (
    <div className="viewfade" style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      <div className="page-head row spread" style={{ alignItems: "flex-end" }}>
        <div><h1>Lab Topology</h1><p>{lab.name} — nodos coloreados por estado. Haz clic en un nodo para inspeccionarlo.</p></div>
        <div className="row gap8">
          <select className="select" value={labId} onChange={(e) => app.go("topology", { lab: e.target.value })} style={{ width: 210 }}>
            {HG.labs.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
          </select>
          <Btn icon="refresh" onClick={() => app.toast("Topología actualizada")} />
        </div>
      </div>

      <div style={{ flex: 1, minHeight: 0, display: "grid", gridTemplateColumns: "1fr 300px", gap: 16 }}>
        {/* canvas */}
        <div className="card" style={{ position: "relative", overflow: "hidden", background: "radial-gradient(120% 100% at 20% 50%, rgba(34,211,238,.05), transparent 55%), var(--surface-2)" }}>
          <svg style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none" }}>
            {vms.map((v, i) => {
              const p = vmPos[i];
              const x1 = netPos.x + "%", y1 = netPos.y + "%", x2 = p.x + "%", y2 = p.y + "%";
              const c = stateColor[v.state];
              return <path key={v.id} d={`M ${netPos.x}% ${netPos.y}% C ${(netPos.x + p.x) / 2}% ${netPos.y}%, ${(netPos.x + p.x) / 2}% ${p.y}%, ${p.x}% ${p.y}%`}
                fill="none" stroke={c} strokeWidth={v.state === "running" ? 2 : 1.4} strokeOpacity={v.state === "running" ? .7 : .4} strokeDasharray={v.state === "running" ? "none" : "4 4"} />;
            })}
          </svg>

          {/* network node */}
          <div onClick={() => setSelNode("net")} style={{ position: "absolute", left: netPos.x + "%", top: netPos.y + "%", transform: "translate(-50%,-50%)", cursor: "pointer" }}>
            <div className="card" style={{ padding: 14, width: 150, textAlign: "center", borderColor: selNode === "net" ? "var(--accent-line)" : undefined, background: selNode === "net" ? "var(--accent-bg)" : "var(--elevated)" }}>
              <Icon name="net" size={26} style={{ color: "var(--accent)" }} />
              <div style={{ fontWeight: 650, fontSize: 13, marginTop: 6 }}>{lab.bridge}</div>
              <div className="faint mono" style={{ fontSize: 10.5 }}>{lab.subnet}</div>
            </div>
          </div>

          {/* vm nodes */}
          {vms.map((v, i) => {
            const p = vmPos[i];
            return (
              <div key={v.id} onClick={() => setSelNode(v.id)} style={{ position: "absolute", left: p.x + "%", top: p.y + "%", transform: "translate(-50%,-50%)", cursor: "pointer" }}>
                <div className="card" style={{ padding: "10px 12px", width: 176, borderColor: selNode === v.id ? "var(--accent-line)" : undefined, background: selNode === v.id ? "var(--accent-bg)" : "var(--elevated)" }}>
                  <div className="row spread" style={{ marginBottom: 5 }}><RoleBadge role={v.role} /><span className="cdot" style={{ width: 9, height: 9, borderRadius: "50%", background: stateColor[v.state], boxShadow: v.state === "running" ? "0 0 8px " + stateColor[v.state] : "none" }} /></div>
                  <div style={{ fontSize: 12.5, fontWeight: 600 }}>{v.name}</div>
                  <div className="faint mono" style={{ fontSize: 10.5 }}>{v.ip || "sin IP"}</div>
                </div>
              </div>
            );
          })}

          {/* legend */}
          <div className="row gap12" style={{ position: "absolute", bottom: 12, left: 14, fontSize: 11 }}>
            {[["running", "Running"], ["shutoff", "Shut off"], ["paused", "Paused"], ["unknown", "Not created"]].map(([k, l]) => (
              <span key={k} className="row gap6 dim"><span style={{ width: 8, height: 8, borderRadius: "50%", background: stateColor[k] }} />{l}</span>
            ))}
          </div>
        </div>

        {/* side panel */}
        <div className="card" style={{ display: "flex", flexDirection: "column" }}>
          <div className="card-head"><h3>{selVm ? "Nodo VM" : "Nodo de red"}</h3></div>
          <div className="pad" style={{ padding: 16, flex: 1, overflowY: "auto" }}>
            {selVm ? (
              <div className="col gap14">
                <div className="row spread"><RoleBadge role={selVm.role} /><StateChip state={selVm.state} /></div>
                <div><div style={{ fontSize: 15, fontWeight: 650 }}>{selVm.name}</div><div className="faint mono" style={{ fontSize: 11 }}>{selVm.os}</div></div>
                <dl className="kv" style={{ gridTemplateColumns: "auto 1fr" }}><dt>IP</dt><dd>{selVm.ip || "—"}</dd><dt>CPU/RAM</dt><dd>{selVm.cpu} · {(selVm.ram/1024).toFixed(0)} GB</dd><dt>Host</dt><dd>{selVm.host}</dd></dl>
                <div className="col gap8">
                  <Btn size="sm" variant="success" icon="play" disabled={selVm.state === "running"} block onClick={() => app.vmAction(selVm, "Start")}>Start selected VM</Btn>
                  <Btn size="sm" variant="primary" icon="terminal" block onClick={() => app.openConsole(selVm)}>Open console</Btn>
                  <Btn size="sm" icon="vm" block onClick={() => app.go("vms", { vm: selVm.id })}>Ver en lista</Btn>
                </div>
              </div>
            ) : (
              <div className="col gap14">
                <Icon name="net" size={30} style={{ color: "var(--accent)" }} />
                <dl className="kv" style={{ gridTemplateColumns: "auto 1fr" }}><dt>Red</dt><dd>{lab.net}</dd><dt>Bridge</dt><dd>{lab.bridge}</dd><dt>Subnet</dt><dd>{lab.subnet}</dd><dt>VMs</dt><dd>{vms.length}</dd></dl>
                <Btn size="sm" icon="camera" block disabled onClick={() => {}}>Export screenshot</Btn>
                <span className="faint" style={{ fontSize: 11 }}>Export de captura llega en v0.7.</span>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ============================== TEMPLATES ============================== */
function Templates({ app }) {
  const [tab, setTab] = useStateInf("VM Templates");
  return (
    <div className="viewfade">
      <div className="page-head"><h1>Templates</h1><p>Perfiles reutilizables de VMs y estructuras de laboratorio para instanciar prácticas rápidamente.</p></div>
      <div className="row spread" style={{ marginBottom: 16 }}>
        <Tabs value={tab} onChange={setTab} options={["VM Templates", "Lab Templates"]} />
        <div className="row gap8"><Btn size="sm" icon="upload" variant="ghost">Import</Btn><Btn size="sm" variant="primary" icon="plus">New</Btn></div>
      </div>

      {tab === "VM Templates" ? (
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(290px, 1fr))" }}>
          {HG.vmTemplates.map((t) => (
            <div key={t.id} className="card pad" style={{ padding: 16 }}>
              <div className="row spread" style={{ marginBottom: 10 }}>
                <div className="row gap8"><Icon name={t.os === "Windows" ? "win" : "vm"} size={18} style={{ color: "var(--accent)" }} /><span className="chip plain" style={{ fontSize: 10.5 }}>{t.os}</span></div>
                <span className={"chip " + (t.display === "SPICE" ? "warn" : "plain")} style={{ fontSize: 10.5 }}>{t.display}</span>
              </div>
              <div style={{ fontWeight: 650, fontSize: 14 }}>{t.name}</div>
              <div className="faint mono" style={{ fontSize: 11, marginBottom: 12 }}>{t.id}</div>
              <dl className="kv" style={{ gridTemplateColumns: "auto 1fr", fontSize: 12, gap: "5px 10px", marginBottom: 14 }}>
                <dt>RAM</dt><dd>{(t.ram/1024).toFixed(0)} GB</dd><dt>vCPU</dt><dd>{t.vcpu}</dd><dt>Disco</dt><dd>{t.disk} GB</dd>
              </dl>
              <div className="row gap6 wrap">
                <Btn size="xs" variant="primary" icon="plus" onClick={() => app.openNewVm(t)}>Create VM</Btn>
                <Btn size="xs" icon="edit" />
                <Btn size="xs" icon="download" />
                <Btn size="xs" variant="danger" icon="trash" />
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))" }}>
          {HG.labTemplates.map((t) => (
            <div key={t.id} className="card pad" style={{ padding: 16 }}>
              <div className="row gap8" style={{ marginBottom: 8 }}><Icon name="labs" size={18} style={{ color: "var(--accent)" }} /><span className="chip plain" style={{ fontSize: 10.5 }}>{t.planned} VMs planificadas</span></div>
              <div style={{ fontWeight: 650, fontSize: 14 }}>{t.name}</div>
              <div className="faint mono" style={{ fontSize: 11, marginBottom: 10 }}>{t.id}</div>
              <div className="dim" style={{ fontSize: 12, marginBottom: 6 }}>{t.vms}</div>
              <div className="faint mono" style={{ fontSize: 11.5, marginBottom: 14 }}>RAM total ~{(t.ram/1024).toFixed(0)} GB</div>
              <div className="row gap6 wrap">
                <Btn size="xs" variant="primary" icon="rocket" onClick={() => app.toast("Instanciando lab " + t.name)}>Instantiate</Btn>
                <Btn size="xs" icon="edit" />
                <Btn size="xs" icon="download" />
                <Btn size="xs" variant="danger" icon="trash" />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

Object.assign(window, { RemoteHosts, Labs, LabTopology, Templates });
