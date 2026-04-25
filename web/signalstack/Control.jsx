// Control tab — Start/Stop the SignalStack system, with live status + log tail.
// Hides itself with a friendly message when not in the desktop app.

function SystemStatusDot({ state }) {
  const colors = {
    running: "#16A34A",
    stopped: "#DC2626",
    transitioning: "#D97706",
  };
  return (
    <span
      style={{
        display: "inline-block", width: 8, height: 8, borderRadius: "50%",
        background: colors[state] || colors.stopped, marginRight: 10,
        flexShrink: 0,
      }}
    />
  );
}

function Control() {
  const inDesktopApp = typeof window !== "undefined" && !!window.pywebview;

  const [status, setStatus] = React.useState({
    docker: "stopped", postgres: "stopped", workers: "stopped", api: "stopped",
  });
  const [logs, setLogs] = React.useState([]);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState(null);
  const [lastStarted, setLastStarted] = React.useState(null);
  const [sensitivity, setSensitivity] = React.useState("medium");

  React.useEffect(() => {
    if (!inDesktopApp) return;
    let cancelled = false;
    async function poll() {
      try {
        const [s, l, ts, m] = await Promise.all([
          window.pywebview.api.get_status(),
          window.pywebview.api.get_recent_logs(50),
          window.pywebview.api.get_last_started_at(),
          window.pywebview.api.get_sensitivity(),
        ]);
        if (cancelled) return;
        setStatus(s); setLogs(l); setLastStarted(ts); setSensitivity(m);
      } catch (e) {
        // pywebview API can throw during teardown; ignore and keep polling
      }
    }
    poll();
    const id = setInterval(poll, 2000);
    return () => { cancelled = true; clearInterval(id); };
  }, [inDesktopApp]);

  if (!inDesktopApp) {
    return (
      <div style={{ padding: 16 }}>
        <Card>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Control</div>
          <div style={{ color: "#687388", fontSize: 12 }}>
            System control is only available inside the SignalStack desktop app.
          </div>
        </Card>
      </div>
    );
  }

  const allRunning =
    status.docker === "running" && status.postgres === "running" &&
    status.workers === "running" && status.api === "running";
  const fullyStopped = status.workers === "stopped" && status.api === "stopped";

  async function start() {
    setBusy(true); setError(null);
    const result = await window.pywebview.api.start_system();
    if (!result.ok) setError(result.error || "Failed to start");
    setBusy(false);
  }

  async function stop() {
    setBusy(true); setError(null);
    await window.pywebview.api.stop_system();
    setBusy(false);
  }

  const rows = [
    { name: "Docker",   state: status.docker },
    { name: "Postgres", state: status.postgres },
    { name: "Workers",  state: status.workers },
    { name: "API",      state: status.api },
  ];

  return (
    <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12 }}>
      <Card>
        <div style={{ fontSize: 13, fontWeight: 700, color: "#1F1F1F", marginBottom: 12 }}>
          System Status
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "auto auto 1fr", rowGap: 6, columnGap: 12, alignItems: "center" }}>
          {rows.map((r) => (
            <React.Fragment key={r.name}>
              <SystemStatusDot state={r.state} />
              <div style={{ fontSize: 12.5, color: "#1F1F1F", fontWeight: 500 }}>{r.name}</div>
              <div style={{ fontSize: 12, color: "#687388", textTransform: "capitalize" }}>{r.state}</div>
            </React.Fragment>
          ))}
        </div>

        <div style={{ marginTop: 20, textAlign: "center" }}>
          {allRunning ? (
            <button
              disabled={busy}
              onClick={stop}
              style={{
                padding: "10px 28px", fontSize: 13, fontWeight: 600,
                background: "#DC2626", color: "#fff", border: "none",
                borderRadius: 6, cursor: busy ? "wait" : "pointer",
                fontFamily: "inherit",
              }}
            >
              {busy ? "Stopping…" : "■ Stop System"}
            </button>
          ) : (
            <button
              disabled={busy || !fullyStopped}
              onClick={start}
              style={{
                padding: "10px 28px", fontSize: 13, fontWeight: 600,
                background: "#16A34A", color: "#fff", border: "none",
                borderRadius: 6, cursor: (busy || !fullyStopped) ? "wait" : "pointer",
                opacity: (busy || !fullyStopped) ? 0.6 : 1,
                fontFamily: "inherit",
              }}
            >
              {busy ? "Starting…" : "▶ Start System"}
            </button>
          )}
        </div>

        {error && (
          <div style={{
            marginTop: 14, padding: 10, fontSize: 12,
            background: "#fff", color: "#DC2626",
            border: "1px solid #DC2626", borderRadius: 6,
          }}>
            {error}
          </div>
        )}

        <div style={{ marginTop: 18, color: "#687388", fontSize: 11, display: "flex", flexDirection: "column", gap: 2 }}>
          <div>Last started: {lastStarted || "—"}</div>
          <div>Sensitivity: <span style={{ textTransform: "capitalize" }}>{sensitivity}</span></div>
        </div>
      </Card>

      <Card>
        <div style={{ fontSize: 12, fontWeight: 700, color: "#1F1F1F", marginBottom: 8 }}>
          Recent log output
        </div>
        <pre style={{
          fontFamily: '"IBM Plex Mono", ui-monospace, monospace', fontSize: 11,
          maxHeight: 220, overflowY: "auto", margin: 0, whiteSpace: "pre-wrap",
          color: "#1F1F1F", lineHeight: 1.5,
        }}>
          {logs.length === 0 ? "(no output yet)" : logs.join("\n")}
        </pre>
      </Card>
    </div>
  );
}

Object.assign(window, { Control });
