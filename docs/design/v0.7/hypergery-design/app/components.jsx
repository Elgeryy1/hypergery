/* HyperGery shared UI primitives. Depends on window.Icon. Exports to window. */
const { useState, useEffect, useRef, useMemo } = React;

const STATE_META = {
  running: { cls: "running", label: "RUNNING" },
  shutoff: { cls: "shutoff", label: "SHUTOFF" },
  paused:  { cls: "paused",  label: "PAUSED" },
  unknown: { cls: "unknown", label: "UNKNOWN" },
};

function StateChip({ state }) {
  const m = STATE_META[state] || STATE_META.unknown;
  return <span className={"chip " + m.cls}><i className="cdot" />{m.label}</span>;
}

function RoleBadge({ role }) {
  if (!role) return null;
  const cls = role.toLowerCase();
  return <span className={"rolebadge " + cls}>{role.toUpperCase()}</span>;
}

function Btn({ children, icon, variant, size, className = "", iconOnly, ...rest }) {
  const cls = ["btn", variant, size, iconOnly ? "icon" : "", className].filter(Boolean).join(" ");
  return (
    <button className={cls} {...rest}>
      {icon && <Icon name={icon} size={size === "xs" ? 14 : 16} />}
      {children}
    </button>
  );
}

function Card({ title, sub, right, icon, children, className = "", bodyClass = "", noBody }) {
  return (
    <div className={"card " + className}>
      {title && (
        <div className="card-head">
          {icon && <Icon name={icon} size={16} style={{ color: "var(--accent)" }} />}
          <div className="col" style={{ gap: 1 }}>
            <h3>{title}</h3>
            {sub && <span className="sub">{sub}</span>}
          </div>
          <div className="spacer" />
          {right}
        </div>
      )}
      {!noBody && <div className={bodyClass || "pad"} style={bodyClass ? undefined : { padding: "var(--pad)" }}>{children}</div>}
      {noBody && children}
    </div>
  );
}

function StatPill({ dot, label, value, mono }) {
  return (
    <div className="statuspill">
      {dot && <span className={"dot " + dot} />}
      {label && <span>{label}</span>}
      {value && <b className={mono ? "mono" : ""}>{value}</b>}
    </div>
  );
}

function Bar({ pct, tone }) {
  const t = tone || (pct > 88 ? "bad" : pct > 70 ? "warn" : "");
  return <div className="bar"><i className={t} style={{ width: Math.max(2, Math.min(100, pct)) + "%" }} /></div>;
}

function Callout({ tone = "info", icon, children, style }) {
  const ic = icon || (tone === "warn" ? "alert" : tone === "danger" ? "alert" : tone === "ok" ? "check" : "info");
  return <div className={"callout " + tone} style={style}><Icon name={ic} size={17} /><div>{children}</div></div>;
}

function Seg({ value, onChange, options }) {
  return (
    <div className="seg">
      {options.map((o) => (
        <button key={o.value} className={value === o.value ? "on" : ""} onClick={() => onChange(o.value)}>{o.label}</button>
      ))}
    </div>
  );
}

function Tabs({ value, onChange, options }) {
  return (
    <div className="tabs">
      {options.map((o) => (
        <button key={o} className={value === o ? "on" : ""} onClick={() => onChange(o)}>{o}</button>
      ))}
    </div>
  );
}

function Field({ label, hint, children, src }) {
  return (
    <div className="field">
      {label && (
        <label className="row spread">
          <span>{label}</span>
          {src && <span className={"tag-src " + src}>{src}</span>}
        </label>
      )}
      {children}
      {hint && <span className="hint">{hint}</span>}
    </div>
  );
}

function Switch({ checked, onChange }) {
  return (
    <label className="switch">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="track" /><span className="thumb" />
    </label>
  );
}

function Empty({ icon = "info", title, children, action }) {
  return (
    <div className="empty">
      <Icon name={icon} size={46} className="ico" />
      <h3>{title}</h3>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}

function Toolbar({ children }) {
  return <div className="row wrap gap8" style={{ marginBottom: 16 }}>{children}</div>;
}

function Modal({ title, sub, onClose, children, footer, width = 560 }) {
  useEffect(() => {
    const h = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);
  return (
    <div onMouseDown={onClose} style={{ position: "absolute", inset: 0, zIndex: 60, background: "rgba(4,7,12,.66)",
      backdropFilter: "blur(3px)", display: "grid", placeItems: "center", padding: 24 }}>
      <div onMouseDown={(e) => e.stopPropagation()} className="card viewfade"
        style={{ width, maxWidth: "100%", maxHeight: "100%", display: "flex", flexDirection: "column", boxShadow: "var(--shadow-pop)" }}>
        <div className="card-head">
          <div className="col" style={{ gap: 2 }}>
            <h3>{title}</h3>
            {sub && <span className="sub">{sub}</span>}
          </div>
          <div className="spacer" />
          <Btn variant="ghost" iconOnly size="sm" icon="x" onClick={onClose} />
        </div>
        <div className="pad" style={{ padding: "var(--pad)", overflowY: "auto" }}>{children}</div>
        {footer && <div className="row gap8" style={{ padding: 14, borderTop: "1px solid var(--border)", justifyContent: "flex-end" }}>{footer}</div>}
      </div>
    </div>
  );
}

/* Mini gauge ring for dashboard */
function Gauge({ pct, label, value, tone = "var(--accent)", size = 92 }) {
  const r = (size - 12) / 2, c = 2 * Math.PI * r;
  return (
    <div className="col center" style={{ gap: 6 }}>
      <div style={{ position: "relative", width: size, height: size }}>
        <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
          <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="#16202f" strokeWidth="7" />
          <circle cx={size/2} cy={size/2} r={r} fill="none" stroke={tone} strokeWidth="7" strokeLinecap="round"
            strokeDasharray={c} strokeDashoffset={c * (1 - pct / 100)} style={{ transition: "stroke-dashoffset .6s ease" }} />
        </svg>
        <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center" }}>
          <div className="col center" style={{ gap: 0 }}>
            <span style={{ fontSize: 19, fontWeight: 700 }} className="mono">{value}</span>
          </div>
        </div>
      </div>
      <span className="dim" style={{ fontSize: 12 }}>{label}</span>
    </div>
  );
}

Object.assign(window, { STATE_META, StateChip, RoleBadge, Btn, Card, StatPill, Bar, Callout, Seg, Tabs, Field, Switch, Empty, Toolbar, Modal, Gauge });
