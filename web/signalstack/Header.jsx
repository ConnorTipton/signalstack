// Header component — single clean row

function Header({ screen, live }) {
  const [time, setTime] = React.useState(new Date());
  const { data: providers } = useAutoRefresh(() => SS_API.providers(), [], 30000);
  const { data: sysHealth } = useAutoRefresh(() => SS_API.health(), { database: "unknown" }, 30000);
  const { data: apiHealth } = useAutoRefresh(
    () => fetch("/api/v1/health").then(r => r.ok ? r.json() : { database: "unknown" }),
    { database: "unknown" },
    30000,
  );
  React.useEffect(() => {
    const t = setInterval(() => setTime(new Date()), 10000);
    return () => clearInterval(t);
  }, []);

  const fmt = d => d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false }) + " ET";

  const titles = {
    overview: "Signal Review Cockpit",
    alerts: "Alerts",
    "alert-detail": "Alert Detail",
    positions: "Positions",
    performance: "Performance",
    providers: "Provider Health",
    replay: "Replay Report",
    "source-trace": "Source Trace",
    settings: "Settings",
  };

  const marketProvider = providers.find(p => p.type === "Market Data" && p.mode && p.mode.toLowerCase().includes("primary")) || providers.find(p => p.type === "Market Data");
  const telegramProvider = providers.find(p => p.type === "Delivery");
  const llmProvider = providers.find(p => p.type === "LLM Labeler");

  const dbOk = apiHealth.database === "ok";
  const runtime = sysHealth.runtime_mode || "—";

  const pillFromStatus = (label, status) => {
    if (status === "healthy") return { label, color: "#16A34A", bg: "#DCFCE7", border: "#BBF7D0" };
    if (status === "degraded") return { label: `${label} degraded`, color: "#D97706", bg: "#FEF3C7", border: "#FDE68A" };
    if (status === "error") return { label: `${label} error`, color: "#DC2626", bg: "#FEE2E2", border: "#FECACA" };
    return { label: `${label} offline`, color: "#687388", bg: "#F3F4F6", border: "#E5E7EB" };
  };

  const dbPill = dbOk
    ? { label: "DB OK", color: "#16A34A", bg: "#DCFCE7", border: "#BBF7D0" }
    : { label: "DB error", color: "#DC2626", bg: "#FEE2E2", border: "#FECACA" };
  const tgPill = pillFromStatus("Telegram", telegramProvider?.status);
  const llmPill = pillFromStatus("LLM", llmProvider?.status);

  return (
    <header style={headerStyles.root}>
      {/* Left: title + meta */}
      <div style={headerStyles.left}>
        <h1 style={headerStyles.title}>{titles[screen] || "SignalStack V1"}</h1>
        <div style={headerStyles.meta}>
          <span style={headerStyles.metaItem}>{runtime === "—" ? "Runtime —" : runtime.replace(/^\w/, c => c.toUpperCase()) + " mode"}</span>
          <span style={headerStyles.sep}>·</span>
          <span style={headerStyles.metaItem}>{marketProvider ? `${marketProvider.name} ${marketProvider.mode?.toLowerCase() || ""}`.trim() : "No market provider"}</span>
          <span style={headerStyles.sep}>·</span>
          <span style={headerStyles.metaItem}>Refreshed {fmt(time)}</span>
        </div>
      </div>

      {/* Right: status pills */}
      <div style={headerStyles.right}>
        <StatusPill label="Paper Only" color="#D97706" bg="#FEF3C7" border="#FDE68A" />
        <StatusPill {...dbPill} dot />
        <StatusPill {...tgPill} dot />
        <StatusPill {...llmPill} dot />
        <StatusPill
          label={live ? "Live" : "Mock data"}
          color={live ? "#16A34A" : "#D97706"}
          bg={live ? "#DCFCE7" : "#FEF3C7"}
          border={live ? "#BBF7D0" : "#FDE68A"}
          dot
        />
      </div>
    </header>
  );
}

function StatusPill({ label, color, bg, border, dot }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 5,
      background: bg,
      border: `1px solid ${border}`,
      borderRadius: 20,
      padding: "3px 10px",
      flexShrink: 0,
    }}>
      {dot && <span style={{ width: 6, height: 6, borderRadius: "50%", background: color, display: "inline-block", flexShrink: 0 }} />}
      <span style={{ fontSize: 11, color, fontWeight: 600, whiteSpace: "nowrap" }}>{label}</span>
    </div>
  );
}

const headerStyles = {
  root: {
    height: 56,
    borderBottom: "1px solid #E5E2D8",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "0 24px",
    background: "#fff",
    flexShrink: 0,
    gap: 20,
  },
  left: {
    display: "flex",
    alignItems: "baseline",
    gap: 16,
    minWidth: 0,
    overflow: "hidden",
  },
  title: {
    margin: 0,
    fontSize: 17,
    fontWeight: 700,
    color: "#1F1F1F",
    letterSpacing: "-0.02em",
    lineHeight: 1,
    whiteSpace: "nowrap",
  },
  meta: {
    display: "flex",
    alignItems: "center",
    gap: 5,
    flexShrink: 0,
  },
  metaItem: {
    fontSize: 11,
    color: "#687388",
    whiteSpace: "nowrap",
  },
  sep: { fontSize: 11, color: "#C8C4BC" },
  right: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    flexShrink: 0,
  },
};

Object.assign(window, { Header });
