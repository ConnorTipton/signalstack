// Settings tab — sensitivity selector for the desktop app.
// Hides itself with a friendly message when opened in a regular browser
// (no pywebview bridge available).

function Settings() {
  const inDesktopApp = typeof window !== "undefined" && !!window.pywebview;
  const [mode, setMode] = React.useState("medium");
  const [loading, setLoading] = React.useState(inDesktopApp);
  const [toast, setToast] = React.useState(null);

  React.useEffect(() => {
    if (!inDesktopApp) return;
    let cancelled = false;
    window.pywebview.api.get_sensitivity().then((m) => {
      if (cancelled) return;
      setMode(m);
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, [inDesktopApp]);

  async function pick(newMode) {
    if (!inDesktopApp || newMode === mode) return;
    const prev = mode;
    setMode(newMode);
    const result = await window.pywebview.api.set_sensitivity(newMode);
    if (!result.ok) {
      setMode(prev);
      setToast({ kind: "error", message: result.error || "Failed to save" });
    } else {
      setToast({ kind: "success", message: `Sensitivity set to ${newMode}` });
    }
    setTimeout(() => setToast(null), 2500);
  }

  if (!inDesktopApp) {
    return (
      <div style={{ padding: 16 }}>
        <Card>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Settings</div>
          <div style={{ color: "#687388", fontSize: 12 }}>
            Settings are only available inside the SignalStack desktop app.
          </div>
        </Card>
      </div>
    );
  }

  if (loading) {
    return (
      <div style={{ padding: 16 }}>
        <Card><div style={{ color: "#687388" }}>Loading…</div></Card>
      </div>
    );
  }

  const options = [
    { id: "high",   label: "High",   desc: "A-grade alerts only (most selective)" },
    { id: "medium", label: "Medium", desc: "A and B grade alerts (default)" },
    { id: "low",    label: "Low",    desc: "A, B, and C grade alerts (most permissive)" },
  ];

  return (
    <div style={{ padding: 16 }}>
      <Card>
        <div style={{ fontSize: 13, fontWeight: 700, color: "#1F1F1F", marginBottom: 12 }}>
          Sensitivity
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {options.map((opt) => (
            <label
              key={opt.id}
              style={{
                display: "flex", alignItems: "flex-start", gap: 10,
                padding: 10, border: "1px solid #E5E2D8", borderRadius: 6,
                cursor: "pointer",
                background: mode === opt.id ? "#F0F7FF" : "transparent",
              }}
            >
              <input
                type="radio"
                name="sensitivity"
                checked={mode === opt.id}
                onChange={() => pick(opt.id)}
                style={{ marginTop: 3 }}
              />
              <div>
                <div style={{ fontSize: 12.5, fontWeight: 600, color: "#1F1F1F" }}>{opt.label}</div>
                <div style={{ color: "#687388", fontSize: 11 }}>{opt.desc}</div>
              </div>
            </label>
          ))}
        </div>
        <div style={{ marginTop: 14, color: "#687388", fontSize: 11 }}>
          Changes apply immediately — no restart needed.
        </div>
      </Card>

      {toast && (
        <div
          style={{
            position: "fixed", bottom: 20, right: 20, padding: "10px 14px",
            background: "#fff",
            border: "1px solid",
            borderColor: toast.kind === "error" ? "#DC2626" : "#16A34A",
            borderRadius: 6, fontSize: 12, color: "#1F1F1F",
            boxShadow: "0 4px 12px rgba(0,0,0,0.08)",
          }}
        >
          {toast.message}
        </div>
      )}
    </div>
  );
}

Object.assign(window, { Settings });
