// Provider Health Screen

function Providers() {
  const { data: providers, live } = useAutoRefresh(() => SS_API.providers(), [], 15000);

  const overallHealth = providers.filter(p => p.status === "healthy").length;
  const degraded = providers.filter(p => p.status === "degraded").length;
  const errorCount = providers.filter(p => p.status === "error").length;

  const latestCheckedISO = providers
    .map(p => p.checkedAtISO)
    .filter(Boolean)
    .sort()
    .pop();
  const lastChecked = latestCheckedISO ? fmtAgo(latestCheckedISO) : "—";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 0, flex: 1, overflow: "hidden" }}>
      {/* Summary bar */}
      <div style={phStyles.summaryBar}>
        <div style={{ display: "flex", gap: 20 }}>
          <div style={phStyles.summaryItem}>
            <span style={{ ...phStyles.summaryDot, background: "#16A34A" }} />
            <span style={{ fontSize: 12, color: "#1F1F1F", fontWeight: 500 }}>{overallHealth} Healthy</span>
          </div>
          <div style={phStyles.summaryItem}>
            <span style={{ ...phStyles.summaryDot, background: "#D97706" }} />
            <span style={{ fontSize: 12, color: "#1F1F1F", fontWeight: 500 }}>{degraded} Degraded</span>
          </div>
          <div style={phStyles.summaryItem}>
            <span style={{ ...phStyles.summaryDot, background: "#DC2626" }} />
            <span style={{ fontSize: 12, color: "#1F1F1F", fontWeight: 500 }}>{errorCount} Error</span>
          </div>
        </div>
        <span style={{ fontSize: 11, color: "#687388", marginLeft: "auto" }}>
          {live ? `Last checked: ${lastChecked} · Auto-refreshing` : "Backend unreachable"}
        </span>
      </div>

      {/* Provider cards grid */}
      <div style={phStyles.grid}>
        {providers.map(p => (
          <ProviderCard key={p.name} provider={p} />
        ))}
      </div>

      {/* Detailed table */}
      <div style={{ padding: "0 24px 24px" }}>
        <Card>
          <div style={{ padding: "12px 16px 10px", borderBottom: "1px solid #E5E2D8" }}>
            <span style={{ fontSize: 13, fontWeight: 700 }}>Provider Detail Table</span>
          </div>
          <table style={sharedStyles.table}>
            <thead>
              <tr>
                {["Provider","Type","Status","Confidence","Last Success","Lag (s)","Consec. Failures","Latest Error","Mode / Priority"].map(h => (
                  <th key={h} style={sharedStyles.th}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {providers.map((p, i) => (
                <tr key={p.name} style={{ ...sharedStyles.tr, background: i % 2 === 0 ? "#fff" : "#FAFAF8" }}>
                  <td style={{ ...sharedStyles.td, fontWeight: 700 }}>{p.name}</td>
                  <td style={{ ...sharedStyles.td, color: "#687388", fontSize: 11 }}>{p.type}</td>
                  <td style={sharedStyles.td}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <StatusDot status={p.status} />
                      <Badge label={p.status} variant={p.status} />
                    </div>
                  </td>
                  <td style={{ ...sharedStyles.td, fontVariantNumeric: "tabular-nums" }}>
                    <ConfBar val={p.confidence} />
                  </td>
                  <td style={{ ...sharedStyles.td, color: "#687388", fontSize: 11 }}>{p.lastSuccess}</td>
                  <td style={{ ...sharedStyles.td, fontVariantNumeric: "tabular-nums", color: p.lagSeconds > 300 ? "#D97706" : "#1F1F1F" }}>{p.lagSeconds}</td>
                  <td style={{ ...sharedStyles.td, fontVariantNumeric: "tabular-nums", color: p.consecutiveFailures > 0 ? "#DC2626" : "#687388" }}>{p.consecutiveFailures}</td>
                  <td style={{ ...sharedStyles.td, fontSize: 11, color: p.latestError ? "#DC2626" : "#C8C4BC" }}>
                    {p.latestError || "—"}
                  </td>
                  <td style={{ ...sharedStyles.td, fontSize: 11, color: "#687388" }}>{p.mode}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
    </div>
  );
}

function ProviderCard({ provider: p }) {
  const borderColor = { healthy: "#16A34A", degraded: "#D97706", error: "#DC2626", inactive: "#C8C4BC" }[p.status];
  return (
    <div style={{ ...phStyles.card, borderTop: `3px solid ${borderColor}` }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10 }}>
        <div>
          <div style={{ fontSize: 14, fontWeight: 700, color: "#1F1F1F" }}>{p.name}</div>
          <div style={{ fontSize: 11, color: "#687388" }}>{p.type}</div>
        </div>
        <Badge label={p.status} variant={p.status} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        <ProviderStat label="Confidence" value={p.confidence.toFixed(2)} />
        <ProviderStat label="Last success" value={p.lastSuccess} />
        <ProviderStat label="Lag" value={`${p.lagSeconds}s`} alert={p.lagSeconds > 300} />
        <ProviderStat label="Failures" value={p.consecutiveFailures} alert={p.consecutiveFailures > 0} />
      </div>

      {p.latestError && (
        <div style={{ marginTop: 8, padding: "6px 8px", background: "#FEE2E2", borderRadius: 5, fontSize: 10, color: "#DC2626" }}>
          {p.latestError}
        </div>
      )}

      <div style={{ marginTop: 8, paddingTop: 8, borderTop: "1px solid #F3F0EA", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontSize: 10, color: "#687388" }}>{p.mode}</span>
        <span style={{ fontSize: 10, color: "#687388" }}>Priority {p.priority}</span>
      </div>
    </div>
  );
}

function ProviderStat({ label, value, alert }) {
  return (
    <div>
      <div style={{ fontSize: 10, color: "#687388", textTransform: "uppercase", letterSpacing: "0.04em", marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 13, fontWeight: 600, color: alert ? "#DC2626" : "#1F1F1F" }}>{value}</div>
    </div>
  );
}

function ConfBar({ val }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <div style={{ width: 60, height: 4, background: "#E5E2D8", borderRadius: 2, overflow: "hidden" }}>
        <div style={{ width: `${val * 100}%`, height: "100%", background: val >= 0.9 ? "#16A34A" : val >= 0.75 ? "#D97706" : "#DC2626", borderRadius: 2 }} />
      </div>
      <span style={{ fontSize: 11, color: "#1F1F1F", fontVariantNumeric: "tabular-nums" }}>{val.toFixed(2)}</span>
    </div>
  );
}

const phStyles = {
  summaryBar: {
    padding: "10px 24px",
    borderBottom: "1px solid #E5E2D8",
    display: "flex",
    alignItems: "center",
    gap: 16,
    background: "#FAF7F1",
    flexShrink: 0,
  },
  summaryItem: { display: "flex", alignItems: "center", gap: 6 },
  summaryDot: { width: 8, height: 8, borderRadius: "50%", display: "inline-block" },
  grid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))",
    gap: 16,
    padding: "20px 24px",
    flexShrink: 0,
  },
  card: {
    background: "#fff",
    border: "1px solid #E5E2D8",
    borderRadius: 8,
    padding: "14px 16px",
  },
};

Object.assign(window, { Providers });
