// Overview Dashboard Screen

function Overview({ onNav, onSelectAlert }) {
  const { data: alerts, live: alertsLive } = useAutoRefresh(() => SS_API.alerts(), [], 30000);
  const { data: providers } = useAutoRefresh(() => SS_API.providers(), [], 30000);
  const { data: perfDays } = useAPI(() => SS_API.performance(7), []);
  const { data: openPositions } = useAutoRefresh(() => SS_API.positions("open"), [], 30000);
  const performance = { daily: perfDays };
  const [selectedId, setSelectedId] = React.useState(null);
  const effectiveSelectedId = selectedId || (alerts[0] && alerts[0].id);
  const [filter, setFilter] = React.useState("All");
  const [timeFilter, setTimeFilter] = React.useState("Today");

  const hasAlerts = alerts.length > 0;
  const selected = hasAlerts ? (alerts.find(a => a.id === effectiveSelectedId) || alerts[0]) : null;

  const filterBtns = ["All", "Bullish", "Bearish", "A-grade", "Watch", "Rejected"];
  const timeBtns = ["Today", "7D", "30D"];

  const nowMs = Date.now();
  const timeWindowMs = { "Today": null, "7D": 7 * 86400_000, "30D": 30 * 86400_000 }[timeFilter];
  const todayUtc = new Date().toISOString().slice(0, 10);
  const inTimeFilter = a => {
    const iso = a.sentAtISO || a.createdAtISO;
    if (!iso) return timeFilter !== "Today"; // unknown time → show in 7D/30D but not Today
    if (timeFilter === "Today") return iso.slice(0, 10) === todayUtc;
    if (timeWindowMs == null) return true;
    return (nowMs - new Date(iso).getTime()) <= timeWindowMs;
  };

  const filteredAlerts = alerts.filter(a => {
    if (!inTimeFilter(a)) return false;
    if (filter === "All") return true;
    if (filter === "Bullish") return a.direction === "bullish";
    if (filter === "Bearish") return a.direction === "bearish";
    if (filter === "A-grade") return a.grade === "A";
    if (filter === "Watch") return a.status === "Watch";
    if (filter === "Rejected") return a.status === "Rejected";
    return true;
  });

  // ── Live KPI computations ──────────────────────────────────────────────
  const todayISO = new Date().toISOString().slice(0, 10);
  const isToday = iso => iso && iso.slice(0, 10) === todayISO;

  const todaysAlerts = alerts.filter(a => isToday(a.sentAtISO) || isToday(a.createdAtISO)).length;
  const promotedSignals = alerts.length;
  const watchSignals = alerts.filter(a => a.status === "Watch").length;
  const openPositionsCount = openPositions.length;
  const closedPnl = performance.daily.reduce((s, d) => s + (d.pnl || 0), 0);
  const avgScore = alerts.length
    ? alerts.reduce((s, a) => s + (a.score || 0), 0) / alerts.length
    : null;
  const healthyProviders = providers.filter(p => p.confidence > 0);
  const avgProviderConfidence = healthyProviders.length
    ? healthyProviders.reduce((s, p) => s + p.confidence, 0) / healthyProviders.length
    : null;

  const fmtPnl = v => (v >= 0 ? `+$${v.toFixed(2)}` : `-$${Math.abs(v).toFixed(2)}`);
  const dash = "—";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 0, flex: 1 }}>
      {/* Toolbar */}
      <div style={ovStyles.toolbar}>
        <div style={{ display: "flex", gap: 4 }}>
          {timeBtns.map(b => (
            <button key={b} onClick={() => setTimeFilter(b)} style={{ ...ovStyles.toolBtn, ...(timeFilter === b ? ovStyles.toolBtnActive : {}) }}>{b}</button>
          ))}
        </div>
        <div style={{ display: "flex", gap: 4, marginLeft: "auto" }}>
          {filterBtns.map(b => (
            <button key={b} onClick={() => setFilter(b)} style={{ ...ovStyles.filterChip, ...(filter === b ? ovStyles.filterChipActive(b) : {}) }}>{b}</button>
          ))}
        </div>
      </div>

      {/* KPI Row */}
      <div style={ovStyles.kpiRow}>
        <KpiCard label="Today's Alerts" value={todaysAlerts} info />
        <KpiCard label="Promoted Signals" value={promotedSignals} info />
        <KpiCard label="Watch Signals" value={watchSignals} info />
        <KpiCard label="Open Positions" value={openPositionsCount} info />
        <KpiCard
          label="Closed PnL (7D)"
          value={performance.daily.length ? fmtPnl(closedPnl) : dash}
          valueColor={closedPnl >= 0 ? "#16A34A" : "#DC2626"}
          info
        />
        <KpiCard
          label="Avg Score"
          value={avgScore != null ? avgScore.toFixed(1) : dash}
          info
        />
        <KpiCard
          label="Provider Confidence"
          value={avgProviderConfidence != null ? avgProviderConfidence.toFixed(2) : dash}
          info
        />
      </div>

      {/* Main area */}
      <div style={ovStyles.mainArea}>
        {/* Left: table */}
        <div style={ovStyles.tableCol}>
          <Card>
            <div style={{ padding: "14px 16px 10px", borderBottom: "1px solid #E5E2D8", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span style={{ fontSize: 13, fontWeight: 700, color: "#1F1F1F" }}>Recent Decision-Ready Alerts</span>
              <button onClick={() => onNav("alerts")} style={ovStyles.linkBtn}>View all alerts →</button>
            </div>
            <table style={{ ...sharedStyles.table }}>
              <thead>
                <tr>
                  {["Time","Ticker","Direction","Score","Grade","Contract","Source Tier","Spread","Status"].map(h => (
                    <th key={h} style={sharedStyles.th}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filteredAlerts.map((a, i) => (
                  <tr
                    key={a.id}
                    onClick={() => { setSelectedId(a.id); onSelectAlert(a); }}
                    style={{
                      ...sharedStyles.tr,
                      background: effectiveSelectedId === a.id ? "#F0F7FF" : i % 2 === 0 ? "#fff" : "#FAFAF8",
                      cursor: "pointer",
                      borderLeft: effectiveSelectedId === a.id ? `3px solid ${a.direction === "bullish" ? "#16A34A" : "#DC2626"}` : "3px solid transparent",
                    }}
                  >
                    <td style={{ ...sharedStyles.td, color: "#687388", fontVariantNumeric: "tabular-nums" }}>{a.time}</td>
                    <td style={{ ...sharedStyles.td, fontWeight: 700 }}>{a.ticker}</td>
                    <td style={sharedStyles.td}><DirectionBadge dir={a.direction} /></td>
                    <td style={{ ...sharedStyles.td, fontWeight: 700 }}>{a.score}</td>
                    <td style={sharedStyles.td}><GradeBadge grade={a.grade} /></td>
                    <td style={{ ...sharedStyles.td, fontFamily: "monospace", fontSize: 11 }}>{a.contract}</td>
                    <td style={sharedStyles.td}><Badge label={a.sourceTier} variant={a.sourceTier === "Tier 1" ? "tier-1" : "tier-2"} /></td>
                    <td style={{ ...sharedStyles.td, color: parseFloat(a.spread) > 15 ? "#DC2626" : "#687388" }}>{a.spread}</td>
                    <td style={sharedStyles.td}><Badge label={a.status} variant={a.status.toLowerCase()} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div style={{ padding: "10px 16px", borderTop: "1px solid #E5E2D8", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontSize: 11, color: "#687388" }}>Showing {filteredAlerts.length} of {alerts.length} alerts</span>
              <button onClick={() => onNav("alerts")} style={ovStyles.linkBtn}>View all alerts →</button>
            </div>
          </Card>
        </div>

        {/* Right: evidence panel */}
        <div style={ovStyles.evidenceCol}>
          <Card style={{ height: "100%" }}>
            <div style={{ padding: "14px 16px 10px", borderBottom: "1px solid #E5E2D8" }}>
              <span style={{ fontSize: 13, fontWeight: 700, color: "#1F1F1F" }}>Signal Evidence Stack</span>
            </div>
            <div style={{ padding: "16px" }}>
              {/* Evidence pipeline */}
              <div style={ovStyles.pipeline}>
                {[
                  { label: "News", icon: "📰", active: true },
                  { label: "Price", icon: "📈", active: true },
                  { label: "Options", icon: "📊", active: true },
                  { label: "Alert", icon: "🔔", active: true, last: true },
                ].map((step, i, arr) => (
                  <React.Fragment key={step.label}>
                    <div style={ovStyles.pipelineStep}>
                      <div style={{ ...ovStyles.pipelineIcon, background: step.last ? "#1F1F1F" : "#DCFCE7", border: `2px solid ${step.last ? "#1F1F1F" : "#16A34A"}` }}>
                        <span style={{ fontSize: 14 }}>{step.icon}</span>
                      </div>
                      <span style={{ fontSize: 10, color: "#687388", marginTop: 4 }}>{step.label}</span>
                    </div>
                    {i < arr.length - 1 && (
                      <div style={ovStyles.pipelineLine} />
                    )}
                  </React.Fragment>
                ))}
              </div>

              {selected ? (
                <>
                  <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 16 }}>
                    <EvidenceRow label="Ticker" value={selected.ticker} mono />
                    {selected.news && <EvidenceRow label="News Catalyst" value={selected.news.summary} />}
                    {selected.price && <EvidenceRow label="Price Confirmation" value={`${selected.price.pattern}, confidence ${selected.price.confidence}`} />}
                    {selected.options && <EvidenceRow label="Options Activity" value={`${selected.options.signal}, confidence ${selected.options.confidence}`} />}
                    {selected.contract_detail && selected.contract_detail.oi != null && (
                      <EvidenceRow label="Contract Selection" value={`OI ${selected.contract_detail.oi.toLocaleString()}, volume ${selected.contract_detail.volume ?? "—"}, spread ${selected.contract_detail.spread}`} />
                    )}
                  </div>

                  <div style={{ marginTop: 16, paddingTop: 14, borderTop: "1px solid #E5E2D8" }}>
                    <div style={{ fontSize: 11, fontWeight: 700, color: "#687388", letterSpacing: "0.05em", textTransform: "uppercase", marginBottom: 8 }}>Risk Plan</div>
                    {Object.entries({ "entry condition": selected.plan.entry, "invalidation": selected.plan.invalidation, "target 1": selected.plan.target1, "target 2": selected.plan.target2, "time stop": selected.plan.timeStop }).map(([k, v]) => (
                      <div key={k} style={{ display: "flex", gap: 6, marginBottom: 5, alignItems: "flex-start" }}>
                        <span style={{ color: "#E5E2D8", fontSize: 12, marginTop: 1 }}>•</span>
                        <span style={{ fontSize: 11, color: "#687388", minWidth: 80, flexShrink: 0 }}>{k}:</span>
                        <span style={{ fontSize: 11, color: "#1F1F1F" }}>{v}</span>
                      </div>
                    ))}
                  </div>

                  <button
                    onClick={() => { onSelectAlert(selected); onNav("alert-detail"); }}
                    style={{ ...ovStyles.detailBtn, marginTop: 14 }}
                  >
                    View full alert detail →
                  </button>
                </>
              ) : (
                <div style={{ marginTop: 20, padding: "24px 16px", textAlign: "center", color: "#687388", fontSize: 12, lineHeight: 1.6 }}>
                  <div style={{ fontSize: 24, marginBottom: 8, opacity: 0.4 }}>◎</div>
                  <div style={{ fontWeight: 600, color: "#1F1F1F", marginBottom: 4 }}>No alerts yet</div>
                  <div>Select an alert from the table to see its evidence stack, or run the pipeline during market hours.</div>
                </div>
              )}
            </div>
          </Card>
        </div>
      </div>

      {/* Bottom panels */}
      <div style={ovStyles.bottomRow}>
        {/* Provider health */}
        <Card style={{ flex: 1 }}>
          <div style={{ padding: "12px 16px 8px", borderBottom: "1px solid #E5E2D8", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontSize: 13, fontWeight: 700 }}>Provider Health</span>
          </div>
          <table style={{ ...sharedStyles.table }}>
            <thead>
              <tr>
                {["Provider", "Status", "Uptime (7D)"].map(h => <th key={h} style={sharedStyles.th}>{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {providers.slice(0, 4).map((p, i) => (
                <tr key={p.name} style={{ ...sharedStyles.tr, background: i % 2 === 0 ? "#fff" : "#FAFAF8" }}>
                  <td style={sharedStyles.td}>{p.name}</td>
                  <td style={sharedStyles.td}><div style={{ display: "flex", alignItems: "center", gap: 6 }}><StatusDot status={p.status} />{p.status}</div></td>
                  <td style={{ ...sharedStyles.td, fontVariantNumeric: "tabular-nums" }}>{p.confidence.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ padding: "8px 16px", borderTop: "1px solid #E5E2D8" }}>
            <button onClick={() => onNav("providers")} style={ovStyles.linkBtn}>View all providers →</button>
          </div>
        </Card>

        {/* Mini chart */}
        <Card style={{ flex: 2 }}>
          <div style={{ padding: "12px 16px 8px", borderBottom: "1px solid #E5E2D8", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontSize: 13, fontWeight: 700 }}>Performance</span>
            <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
              <span style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: "#687388" }}><span style={{ width: 10, height: 10, borderRadius: 2, background: "#16A34A", display: "inline-block" }} />Daily PnL (USD)</span>
              <span style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: "#687388" }}><span style={{ width: 16, height: 2, background: "#1F1F1F", display: "inline-block", opacity: 0.5 }} />Alert Count</span>
            </div>
          </div>
          <div style={{ padding: "16px" }}>
            <MiniBarChart data={performance.daily} width={380} height={90} />
          </div>
          <div style={{ padding: "8px 16px", borderTop: "1px solid #E5E2D8" }}>
            <button onClick={() => onNav("performance")} style={ovStyles.linkBtn}>View full performance →</button>
          </div>
        </Card>

        {/* Replay summary */}
        <Card style={{ flex: 1 }}>
          <div style={{ padding: "12px 16px 8px", borderBottom: "1px solid #E5E2D8" }}>
            <span style={{ fontSize: 13, fontWeight: 700 }}>Replay Summary</span>
          </div>
          <div style={{ padding: "20px 16px", display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>
            <button
              onClick={() => onNav("replay")}
              style={{ width: 48, height: 48, borderRadius: "50%", border: "2px solid #E5E2D8", background: "#fff", display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", fontSize: 20 }}
            >
              ▶
            </button>
            <p style={{ fontSize: 11, color: "#687388", textAlign: "center", margin: 0, lineHeight: 1.5 }}>
              Run a replay to re-feed a historical window<br />
              through the same pipeline.
            </p>
          </div>
          <div style={{ padding: "8px 16px", borderTop: "1px solid #E5E2D8" }}>
            <button onClick={() => onNav("replay")} style={ovStyles.linkBtn}>Open replay →</button>
          </div>
        </Card>
      </div>
    </div>
  );
}

function EvidenceRow({ label, value, mono }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "110px 1fr", gap: 8, alignItems: "flex-start" }}>
      <span style={{ fontSize: 11, color: "#687388", fontWeight: 600 }}>{label}</span>
      <span style={{ fontSize: 11, color: "#1F1F1F", fontFamily: mono ? "monospace" : "inherit", lineHeight: 1.4 }}>{value}</span>
    </div>
  );
}

const ovStyles = {
  toolbar: {
    padding: "10px 24px",
    borderBottom: "1px solid #E5E2D8",
    display: "flex",
    alignItems: "center",
    gap: 8,
    background: "#FAF7F1",
    flexShrink: 0,
  },
  toolBtn: {
    padding: "5px 12px",
    border: "1px solid #E5E2D8",
    borderRadius: 5,
    background: "#fff",
    color: "#687388",
    fontSize: 12,
    fontWeight: 500,
    cursor: "pointer",
    fontFamily: "inherit",
    transition: "all 0.1s",
  },
  toolBtnActive: {
    background: "#1F1F1F",
    color: "#fff",
    border: "1px solid #1F1F1F",
  },
  filterChip: {
    padding: "4px 11px",
    border: "1px solid #E5E2D8",
    borderRadius: 20,
    background: "#fff",
    color: "#687388",
    fontSize: 11.5,
    fontWeight: 500,
    cursor: "pointer",
    fontFamily: "inherit",
    transition: "all 0.1s",
  },
  filterChipActive: (label) => {
    const map = { Bullish: { bg: "#DCFCE7", color: "#16A34A", border: "#16A34A" }, Bearish: { bg: "#FEE2E2", color: "#DC2626", border: "#DC2626" }, "A-grade": { bg: "#DCFCE7", color: "#16A34A", border: "#16A34A" }, Watch: { bg: "#FEF3C7", color: "#D97706", border: "#D97706" } };
    const s = map[label] || { bg: "#1F1F1F", color: "#fff", border: "#1F1F1F" };
    return { background: s.bg, color: s.color, border: `1px solid ${s.border}` };
  },
  kpiRow: {
    display: "flex",
    gap: 12,
    padding: "16px 24px",
    background: "#FAF7F1",
    flexShrink: 0,
  },
  mainArea: {
    display: "flex",
    gap: 16,
    padding: "0 24px",
    flex: 1,
    minHeight: 0,
    marginBottom: 16,
  },
  tableCol: { flex: 1.6, minWidth: 0 },
  evidenceCol: { flex: 1, minWidth: 280 },
  pipeline: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 0,
  },
  pipelineStep: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: 2,
  },
  pipelineIcon: {
    width: 38, height: 38,
    borderRadius: "50%",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
  },
  pipelineLine: {
    flex: 1,
    height: 2,
    background: "#E5E2D8",
    minWidth: 20,
    maxWidth: 40,
    margin: "0 4px",
    marginBottom: 16,
  },
  bottomRow: {
    display: "flex",
    gap: 16,
    padding: "0 24px 16px",
    flexShrink: 0,
  },
  linkBtn: {
    background: "none",
    border: "none",
    color: "#2563EB",
    fontSize: 11,
    fontWeight: 500,
    cursor: "pointer",
    padding: 0,
    fontFamily: "inherit",
  },
  detailBtn: {
    width: "100%",
    padding: "7px 12px",
    border: "1px solid #E5E2D8",
    borderRadius: 6,
    background: "#fff",
    color: "#1F1F1F",
    fontSize: 12,
    fontWeight: 600,
    cursor: "pointer",
    fontFamily: "inherit",
    textAlign: "center",
  },
};

Object.assign(window, { Overview });
