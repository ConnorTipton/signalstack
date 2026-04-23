// Sidebar navigation component

const NAV_ITEMS = [
  { id: "overview", label: "Overview", icon: "⊞" },
  { id: "alerts", label: "Alerts", icon: "◎" },
  { id: "alert-detail", label: "Alert Detail", icon: "◈" },
  { id: "positions", label: "Positions", icon: "▦" },
  { id: "performance", label: "Performance", icon: "∿" },
  { id: "providers", label: "Providers", icon: "⬡" },
  { id: "replay", label: "Replay", icon: "↺" },
  { id: "source-trace", label: "Source Trace", icon: "⌖" },
  { id: "settings", label: "Settings", icon: "⚙" },
];

function Sidebar({ active, onNav }) {
  const { data: sysHealth } = useAutoRefresh(
    () => SS_API.health(),
    { runtime_mode: null, environment: null },
    60000,
  );
  const modeLabels = { build: "Build Mode", core: "Core Budget Mode", upgrade: "Upgrade Mode" };
  const mode = sysHealth.runtime_mode;
  const modeLabel = mode ? (modeLabels[mode] || `${mode} mode`) : "Mode —";
  const env = sysHealth.environment || "—";

  return (
    <aside style={sidebarStyles.root}>
      <div style={sidebarStyles.brand}>
        <div style={sidebarStyles.brandName}>SignalStack V1</div>
      </div>

      <nav style={sidebarStyles.nav}>
        {NAV_ITEMS.map(item => (
          <button
            key={item.id}
            onClick={() => onNav(item.id)}
            style={{
              ...sidebarStyles.navItem,
              ...(active === item.id ? sidebarStyles.navItemActive : {})
            }}
          >
            <span style={sidebarStyles.navIcon}>{item.icon}</span>
            <span>{item.label}</span>
          </button>
        ))}
      </nav>

      <div style={sidebarStyles.footer}>
        <div style={sidebarStyles.footerRow}>
          <span style={sidebarStyles.footerDot} />
          <span style={sidebarStyles.footerLabel}>{modeLabel}</span>
          <span style={{ width: 7, height: 7, borderRadius: "50%", background: mode ? "#16A34A" : "#C8C4BC", display: "inline-block" }} />
        </div>
        <div style={sidebarStyles.footerRow}>
          <span style={{ ...sidebarStyles.footerLabel, fontSize: 10, opacity: 0.8 }}>env: {env}</span>
        </div>
        <div style={sidebarStyles.footerUser}>
          <div style={sidebarStyles.userAvatar}>A</div>
          <span style={sidebarStyles.footerLabel}>Analyst</span>
          <span style={{ marginLeft: "auto", color: "#687388", fontSize: 11 }}>›</span>
        </div>
      </div>
    </aside>
  );
}

const sidebarStyles = {
  root: {
    width: 160,
    minWidth: 160,
    background: "#FAF7F1",
    borderRight: "1px solid #E5E2D8",
    display: "flex",
    flexDirection: "column",
    height: "100vh",
    position: "fixed",
    left: 0, top: 0,
    zIndex: 100,
    fontFamily: "inherit",
  },
  brand: {
    padding: "18px 16px 14px",
    borderBottom: "1px solid #E5E2D8",
  },
  brandName: {
    fontSize: 13,
    fontWeight: 700,
    color: "#1F1F1F",
    letterSpacing: "-0.02em",
  },
  nav: {
    flex: 1,
    padding: "8px 8px",
    overflowY: "auto",
    display: "flex",
    flexDirection: "column",
    gap: 1,
  },
  navItem: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    padding: "7px 8px",
    borderRadius: 6,
    border: "none",
    background: "transparent",
    color: "#687388",
    fontSize: 12.5,
    fontWeight: 500,
    cursor: "pointer",
    width: "100%",
    textAlign: "left",
    transition: "background 0.1s, color 0.1s",
    fontFamily: "inherit",
  },
  navItemActive: {
    background: "#1F1F1F",
    color: "#fff",
  },
  navIcon: {
    fontSize: 14,
    width: 16,
    textAlign: "center",
    flexShrink: 0,
  },
  footer: {
    borderTop: "1px solid #E5E2D8",
    padding: "10px 12px",
    display: "flex",
    flexDirection: "column",
    gap: 6,
  },
  footerRow: {
    display: "flex",
    alignItems: "center",
    gap: 6,
  },
  footerDot: {
    width: 6, height: 6,
    borderRadius: "50%",
    background: "#687388",
    display: "inline-block",
  },
  footerLabel: {
    fontSize: 11,
    color: "#687388",
    fontWeight: 500,
  },
  footerUser: {
    display: "flex",
    alignItems: "center",
    gap: 7,
    cursor: "pointer",
  },
  userAvatar: {
    width: 22, height: 22,
    borderRadius: "50%",
    background: "#E5E2D8",
    color: "#1F1F1F",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: 11,
    fontWeight: 700,
  },
};

Object.assign(window, { Sidebar });
