/* HyperGery: NAS Clone Migration wizard + Migrations history */
const { useState: useStateMig, useEffect: useEffectMig } = React;

const PREFLIGHT_CHECKS = [
  "Hub online",
  "Source VM exists",
  "Source VM is shut off",
  "Target host online",
  "Target KVM / libvirt OK",
  "Target VM name available",
  "NAS staging writable",
  "Package path inside staging (safe)",
  "Attached ISO exists (if included)",
  "Source VM will NOT be deleted",
];

const PROGRESS_STATES = [
  ["created", "Migration record created"],
  ["preflight", "Preflight re-validated"],
  ["packaging", "Packaging domain.xml + qcow2 → NAS staging"],
  ["uploaded", "Package uploaded to NAS"],
  ["waiting_target", "Waiting for target agent"],
  ["importing", "Target importing package"],
  ["defining_vm", "Defining VM · regenerating UUID/MAC"],
  ["done", "Migration complete"],
];

function MigrationWizard({ app, initialVm }) {
  const [step, setStep] = useStateMig(initialVm ? 1 : 0);
  const [vmId, setVmId] = useStateMig(initialVm ? initialVm.id : null);
  const [target, setTarget] = useStateMig(null);
  const [opts, setOpts] = useStateMig({ targetName: "", includeIso: false, includeSnaps: true, startAfter: false, allowPaused: false });
  const [preDone, setPreDone] = useStateMig(0);
  const [progress, setProgress] = useStateMig(-1);

  const vm = HG.vms.find((v) => v.id === vmId);
  const onlineTargets = HG.hosts.filter((h) => !h.local && h.status === "online" && h.kvm && h.libvirt);
  const eligibleVms = HG.vms.filter((v) => v.state === "shutoff" || v.state === "paused");

  useEffectMig(() => { if (vm && !opts.targetName) setOpts((o) => ({ ...o, targetName: vm.name + "-copy" })); }, [vmId]);

  // preflight animation
  useEffectMig(() => {
    if (step !== 3) return;
    setPreDone(0);
    const iv = setInterval(() => setPreDone((n) => { if (n >= PREFLIGHT_CHECKS.length) { clearInterval(iv); return n; } return n + 1; }), 280);
    return () => clearInterval(iv);
  }, [step]);

  // progress animation
  useEffectMig(() => {
    if (step !== 4) return;
    setProgress(0);
    const iv = setInterval(() => setProgress((n) => { if (n >= PROGRESS_STATES.length - 1) { clearInterval(iv); setTimeout(() => setStep(5), 700); return n; } return n + 1; }), 720);
    return () => clearInterval(iv);
  }, [step]);

  const steps = ["Select VM", "Target Host", "Options", "Preflight", "Progress", "Result"];
  const canNext = (step === 0 && vmId) || (step === 1 && target) || (step === 2 && opts.targetName.trim()) || (step === 3 && preDone >= PREFLIGHT_CHECKS.length);
  const targetHost = HG.hosts.find((h) => h.id === target);
  const migId = "mig-20260605-" + (vm ? vm.id.slice(-3) : "x") + "a";

  return (
    <div onMouseDown={() => app.closeMigration()} style={{ position: "absolute", inset: 0, zIndex: 65, background: "rgba(4,7,12,.7)", backdropFilter: "blur(3px)", display: "grid", placeItems: "center", padding: 28 }}>
      <div onMouseDown={(e) => e.stopPropagation()} className="card viewfade" style={{ width: 860, maxWidth: "100%", height: 600, maxHeight: "100%", display: "flex", boxShadow: "var(--shadow-pop)", overflow: "hidden" }}>
        {/* left rail */}
        <div style={{ width: 240, flex: "0 0 240px", background: "var(--bg-alt)", borderRight: "1px solid var(--border)", padding: 18, display: "flex", flexDirection: "column" }}>
          <div className="row gap10" style={{ marginBottom: 4 }}>
            <div className="brand-mark" style={{ width: 30, height: 30 }}><Icon name="migrations" size={16} style={{ color: "#04141a" }} /></div>
            <div><div style={{ fontWeight: 700, fontSize: 14 }}>NAS Clone Migration</div></div>
          </div>
          <div className="faint" style={{ fontSize: 11, marginBottom: 18, lineHeight: 1.5 }}>No es live RAM migration. La VM origen queda intacta.</div>
          <div className="stepper">
            {steps.map((s, i) => (
              <div key={s} className={"step " + (i === step ? "active" : i < step ? "done" : "pending")}>
                <span className="sdot">{i < step ? <Icon name="check" size={12} /> : i + 1}</span>
                <div><div className="st">{s}</div></div>
              </div>
            ))}
          </div>
          <div className="grow" />
          <Callout tone="ok" style={{ fontSize: 11 }}>Source VM remains untouched · UUID & MAC regenerated on target.</Callout>
        </div>

        {/* right content */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
          <div className="card-head">
            <div className="col" style={{ gap: 2 }}><h3>{steps[step]}</h3><span className="sub">Paso {step + 1} de 6</span></div>
            <div className="spacer" />
            <Btn variant="ghost" iconOnly size="sm" icon="x" onClick={() => app.closeMigration()} />
          </div>

          <div className="pad" style={{ padding: 20, overflowY: "auto", flex: 1 }}>
            {/* STEP 0: select VM */}
            {step === 0 && (
              <div className="col gap10">
                <Callout tone="info">Solo se pueden empaquetar VMs <b>apagadas</b> (o en pausa con permiso explícito). Las VMs en running están bloqueadas.</Callout>
                {eligibleVms.map((v) => (
                  <div key={v.id} className="card row spread" onClick={() => setVmId(v.id)} style={{ cursor: "pointer", padding: "11px 14px", background: v.id === vmId ? "var(--accent-bg)" : "var(--surface-2)", borderColor: v.id === vmId ? "var(--accent-line)" : undefined }}>
                    <div className="row gap10"><RoleBadge role={v.role} /><div><div style={{ fontWeight: 600, fontSize: 13 }}>{v.name}</div><div className="faint mono" style={{ fontSize: 11 }}>{v.os} · {v.disk} GB</div></div></div>
                    <StateChip state={v.state} />
                  </div>
                ))}
                <div className="faint" style={{ fontSize: 11.5 }}>VMs en running ({HG.vms.filter(v=>v.state==="running").length}) ocultas: detenlas primero con ACPI Shutdown.</div>
              </div>
            )}

            {/* STEP 1: target host */}
            {step === 1 && (
              <div className="col gap10">
                {HG.hosts.filter((h) => !h.local).map((h) => {
                  const ok = h.status === "online" && h.kvm && h.libvirt;
                  return (
                    <div key={h.id} className="card row spread" onClick={() => ok && setTarget(h.id)} style={{ padding: "12px 14px", cursor: ok ? "pointer" : "not-allowed", opacity: ok ? 1 : .55, background: h.id === target ? "var(--accent-bg)" : "var(--surface-2)", borderColor: h.id === target ? "var(--accent-line)" : undefined }}>
                      <div className="row gap10"><Icon name="server" size={18} style={{ color: ok ? "var(--accent)" : "var(--offline)" }} />
                        <div><div style={{ fontWeight: 600, fontSize: 13 }}>{h.name}</div><div className="faint mono" style={{ fontSize: 11 }}>{h.ip} · RAM libre {h.ramFree} GB · disco {h.diskFree} GB</div></div></div>
                      {ok ? <span className="chip ok"><i className="cdot" />ONLINE</span> : <span className="chip danger"><i className="cdot" />{h.status === "offline" ? "OFFLINE" : "NOT READY"}</span>}
                    </div>
                  );
                })}
                {onlineTargets.length === 0 && <Callout tone="warn">No hay hosts destino disponibles. Revisa Remote Hosts.</Callout>}
              </div>
            )}

            {/* STEP 2: options */}
            {step === 2 && (
              <div className="col gap16">
                <Field label="Target VM name" hint="Nombre de la VM importada en el host destino.">
                  <input className="input mono" value={opts.targetName} onChange={(e) => setOpts({ ...opts, targetName: e.target.value })} />
                </Field>
                <div className="col gap10">
                  {[["includeIso", "Incluir ISO adjunta", "Empaqueta la ISO de instalación si está conectada."],
                    ["includeSnaps", "Incluir snapshots", "Copia los ficheros de snapshot si el formato lo soporta."],
                    ["startAfter", "Arrancar tras importar", "La VM destino arranca automáticamente al terminar."],
                    ["allowPaused", "Permitir VM en pausa", "Requerido explícitamente si la VM origen está paused."]].map(([k, t, d]) => (
                    <div key={k} className="card row spread" style={{ background: "var(--surface-2)", padding: "11px 14px" }}>
                      <div><div style={{ fontSize: 13, fontWeight: 550 }}>{t}</div><div className="faint" style={{ fontSize: 11.5 }}>{d}</div></div>
                      <Switch checked={opts[k]} onChange={(v) => setOpts({ ...opts, [k]: v })} />
                    </div>
                  ))}
                </div>
                <Callout tone="info">Paquete en <span className="mono">{HG.hub.nasRoot}/migrations/{migId}/</span></Callout>
              </div>
            )}

            {/* STEP 3: preflight */}
            {step === 3 && (
              <div className="col gap6">
                {PREFLIGHT_CHECKS.map((c, i) => {
                  const done = i < preDone;
                  return (
                    <div key={c} className="row gap10" style={{ padding: "7px 10px", borderRadius: 7, background: done ? "var(--surface-2)" : "transparent" }}>
                      <span style={{ width: 18, height: 18, display: "grid", placeItems: "center" }}>
                        {done ? <Icon name="check" size={15} style={{ color: "var(--running)" }} /> : <Icon name="refresh" size={14} className="spin" style={{ color: "var(--text-faint)" }} />}
                      </span>
                      <span style={{ fontSize: 13, color: done ? "var(--text)" : "var(--text-faint)" }}>{c}</span>
                      {done && <span className="grow" />}
                      {done && <span className="chip ok" style={{ fontSize: 10 }}><i className="cdot" />PASS</span>}
                    </div>
                  );
                })}
                {preDone >= PREFLIGHT_CHECKS.length && <Callout tone="ok" style={{ marginTop: 8 }}>Preflight superado. Listo para empaquetar y migrar.</Callout>}
              </div>
            )}

            {/* STEP 4: progress */}
            {step === 4 && (
              <div className="col gap4">
                <div className="row spread" style={{ marginBottom: 8 }}><span className="mono dim" style={{ fontSize: 12 }}>{migId}</span><span className="mono dim" style={{ fontSize: 12 }}>{vm && vm.name} → {targetHost && targetHost.id}</span></div>
                {PROGRESS_STATES.map(([key, label], i) => {
                  const st = i < progress ? "done" : i === progress ? "active" : "pending";
                  return (
                    <div key={key} className={"pstate " + st}>
                      <span className="pdot">{st === "done" ? <Icon name="check" size={11} /> : st === "active" ? <Icon name="refresh" size={10} className="spin" /> : ""}</span>
                      <span className="mono" style={{ fontSize: 11, opacity: .7, width: 110 }}>{key}</span>
                      <span style={{ fontSize: 12.5 }}>{label}</span>
                    </div>
                  );
                })}
              </div>
            )}

            {/* STEP 5: result */}
            {step === 5 && (
              <div className="col gap14">
                <div className="row gap12" style={{ alignItems: "center" }}>
                  <div style={{ width: 44, height: 44, borderRadius: 12, background: "var(--running-bg)", display: "grid", placeItems: "center" }}><Icon name="check" size={22} style={{ color: "var(--running)" }} /></div>
                  <div><h3 style={{ margin: 0, fontSize: 16 }}>Migración completada</h3><span className="dim" style={{ fontSize: 12.5 }}>VM importada en {targetHost && targetHost.name}</span></div>
                </div>
                <dl className="kv">
                  <dt>migration_id</dt><dd>{migId}</dd>
                  <dt>package path</dt><dd style={{ fontSize: 11 }}>{HG.hub.nasRoot}/migrations/{migId}/</dd>
                  <dt>source</dt><dd>{vm && vm.name} <span className="chip ok" style={{ fontSize: 10, marginLeft: 6 }}><i className="cdot" />INTACT</span></dd>
                  <dt>target</dt><dd>{opts.targetName} <span className="chip accent" style={{ fontSize: 10, marginLeft: 6 }}><i className="cdot" />IMPORTED</span></dd>
                  <dt>identity</dt><dd>UUID + MAC regenerados</dd>
                </dl>
                <div className="row gap8">
                  <Btn icon="copy" size="sm" onClick={() => app.toast("Logs copiados al portapapeles")}>Copy logs</Btn>
                  <Btn icon="folder" size="sm" onClick={() => app.toast("Abriendo carpeta del paquete…")}>Open package folder</Btn>
                </div>
                <Callout tone="ok">La VM origen, sus discos y el manifest del lab no se han modificado.</Callout>
              </div>
            )}
          </div>

          {/* footer nav */}
          <div className="row gap8" style={{ padding: 14, borderTop: "1px solid var(--border)", justifyContent: "space-between" }}>
            <Btn variant="ghost" onClick={() => app.closeMigration()}>Cancelar</Btn>
            <div className="row gap8">
              {step > 0 && step < 4 && <Btn icon="chevron" className="" onClick={() => setStep(step - 1)} style={{ flexDirection: "row-reverse" }}>Atrás</Btn>}
              {step < 3 && <Btn variant="primary" disabled={!canNext} onClick={() => setStep(step + 1)}>Continuar</Btn>}
              {step === 3 && <Btn variant="primary" icon="rocket" disabled={!canNext} onClick={() => setStep(4)}>Empaquetar y migrar</Btn>}
              {step === 5 && <Btn variant="primary" icon="check" onClick={() => app.closeMigration()}>Hecho</Btn>}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Migrations({ app }) {
  return (
    <div className="viewfade">
      <div className="page-head row spread" style={{ alignItems: "flex-end" }}>
        <div><h1>Migrations</h1><p>Historial de NAS Clone Migrations. La VM origen nunca se borra ni se modifica.</p></div>
        <Btn variant="primary" icon="migrations" onClick={() => app.openMigration()}>Nueva migración</Btn>
      </div>
      <Callout tone="info" style={{ marginBottom: 16 }}>
        <b>Esto es NAS Clone Migration, no live RAM migration.</b> La VM se empaqueta en el NAS y se importa en otro host con UUID/MAC nuevos; el origen queda intacto. La live migration real con RAM llegará en v0.7+.
      </Callout>
      <Card noBody>
        <table className="tbl">
          <thead><tr><th>Migration ID</th><th>VM origen</th><th>Ruta host</th><th>VM destino</th><th>Tamaño</th><th>Duración</th><th>Estado</th><th>Cuándo</th></tr></thead>
          <tbody>
            {HG.migrations.map((m) => (
              <tr key={m.id}>
                <td className="mono">{m.id}</td>
                <td className="name">{m.vm}</td>
                <td className="mono">{m.from} → {m.to}</td>
                <td className="mono">{m.targetVm}</td>
                <td className="mono">{m.size}</td>
                <td className="mono">{m.duration}</td>
                <td>{m.state === "done" ? <span className="chip ok"><i className="cdot" />DONE</span> : <span className="chip danger" title={m.error}><i className="cdot" />FAILED</span>}</td>
                <td className="dim">{m.when}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <div className="faint" style={{ fontSize: 11.5, marginTop: 10 }}>mig-20260531: target host offline durante preflight — el origen no sufrió cambios.</div>
    </div>
  );
}

Object.assign(window, { MigrationWizard, Migrations });
