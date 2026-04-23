// Performance + Positions Screen

function Performance() {
  const { data: perfDays } = useAPI(() => SS_API.performance(30), []);
  const { data: openPos } = useAutoRefresh(() => SS_API.positions("open"), [], 15000);
  const { data: closedPos } = useAPI(() => SS_API.positions("closed"), []);
  const positions = { open: openPos, closed: closedPos };

  // Aggregate grades across all days from live data
  const grades = perfDays.reduce((acc, d) => {
    Object.entries(d.grades || {}).forEach(([g, n]) => { acc[g] = (acc[g] || 0) + n; });
    return acc;
  }, {});
  const performance = { daily: perfDays, grades };
  const [posTab, setPosTab] = React.useState("open");

  const totalPnl = perfDays.reduce((s, d) => s + (d.pnl || 0), 0);
  const wins = perfDays.reduce((s, d) => s + (d.wins || 0), 0);
  const losses = perfDays.reduce((s, d) => s + (d.losses || 0), 0);
  const winRate = (wins + losses) > 0 ? wins / (wins + losses) : 0;
  const scoredDays = perfDays.filter(d => d.avgScore > 0);
  const avgScore = scoredDays.length
    ? scoredDays.reduce((s, d) => s + d.avgScore, 0) / scoredDays.length
    : null;
  const totalAlerts = perfDays.reduce((s, d) => s + (d.alerts || 0), 0);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 0, flex: 1, overflowY: "auto" }}>
      {/* Top KPIs */}
      <div style={perfStyles.kpiRow}>
        <KpiCard
          label="Total PnL (30D)"
          value={perfDays.length ? (totalPnl >= 0 ? `+$${totalPnl.toFixed(2)}` : `-$${Math.abs(totalPnl).toFixed(2)}`) : "—"}
          valueColor={totalPnl >= 0 ? "#16A34A" : "#DC2626"}
        />
        <KpiCard
          label="Win Rate (30D)"
          value={(wins + losses) > 0 ? `${(winRate * 100).toFixed(1)}%` : "—"}
          valueColor={winRate >= 0.5 ? "#16A34A" : "#DC2626"}
        />
        <KpiCard label="Avg Score (30D)" value={avgScore != null ? avgScore.toFixed(1) : "—"} />
        <KpiCard label="Total Wins" value={wins} />
        <KpiCard label="Total Losses" value={losses} />
        <KpiCard label="Alerts (30D)" value={totalAlerts} />
      </div>

      {/* Charts row */}
      <div style={perfStyles.chartsRow}>
        {/* PnL bar chart */}
        <Card style={{ flex: 2 }}>
          <div style={{ padding: "12px 16px 8px", borderBottom: "1px solid #E5E2D8", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontSize: 13, fontWeight: 700 }}>Daily PnL (7D)</span>
            <div style={{ display: "flex", gap: 10 }}>
              <span style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: "#687388" }}><span style={{ width: 10, height: 10, borderRadius: 2, background: "#16A34A" }} />Profit</span>
              <span style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: "#687388" }}><span style={{ width: 10, height: 10, borderRadius: 2, background: "#DC2626" }} />Loss</span>
            </div>
          </div>
          <div style={{ padding: "20px 16px" }}>
            <MiniBarChart data={performance.daily} width={420} height={100} />
          </div>
        </Card>

        {/* Alerts by grade */}
        <Card style={{ flex: 1 }}>
          <div style={{ padding: "12px 16px 8px", borderBottom: "1px solid #E5E2D8" }}>
            <span style={{ fontSize: 13, fontWeight: 700 }}>Alerts by Grade</span>
          </div>
          <div style={{ padding: "16px" }}>
            <GradeDistribution grades={performance.grades} />
          </div>
        </Card>

        {/* Score trend */}
        <Card style={{ flex: 1 }}>
          <div style={{ padding: "12px 16px 8px", borderBottom: "1px solid #E5E2D8" }}>
            <span style={{ fontSize: 13, fontWeight: 700 }}>Avg Score Trend</span>
          </div>
          <div style={{ padding: "20px 16px" }}>
            <Sparkline values={performance.daily.map(d => d.avgScore)} width={180} height={60} color="#2563EB" />
            <div style={{ display: "flex", justifyContent: "space-between", marginTop: 4 }}>
              {performance.daily.map(d => (
                <span key={d.date} style={{ fontSize: 9, color: "#687388" }}>{d.date.replace("Apr ", "")}</span>
              ))}
            </div>
          </div>
        </Card>
      </div>

      {/* Daily table */}
      <div style={{ padding: "0 24px 16px" }}>
        <Card>
          <div style={{ padding: "12px 16px 10px", borderBottom: "1px solid #E5E2D8" }}>
            <span style={{ fontSize: 13, fontWeight: 700 }}>Daily Metrics Table</span>
          </div>
          <table style={sharedStyles.table}>
            <thead>
              <tr>
                {["Date","PnL","Alerts","Wins","Losses","Win Rate","Avg Score"].map(h => <th key={h} style={sharedStyles.th}>{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {performance.daily.map((d, i) => {
                const wr = d.wins / (d.wins + d.losses);
                return (
                  <tr key={d.date} style={{ ...sharedStyles.tr, background: i % 2 === 0 ? "#fff" : "#FAFAF8" }}>
                    <td style={{ ...sharedStyles.td, fontWeight: 600 }}>{d.date}</td>
                    <td style={{ ...sharedStyles.td, fontWeight: 700, color: d.pnl >= 0 ? "#16A34A" : "#DC2626", fontVariantNumeric: "tabular-nums" }}>
                      {d.pnl >= 0 ? "+" : ""}${d.pnl}
                    </td>
                    <td style={{ ...sharedStyles.td, fontVariantNumeric: "tabular-nums" }}>{d.alerts}</td>
                    <td style={{ ...sharedStyles.td, color: "#16A34A", fontVariantNumeric: "tabular-nums" }}>{d.wins}</td>
                    <td style={{ ...sharedStyles.td, color: "#DC2626", fontVariantNumeric: "tabular-nums" }}>{d.losses}</td>
                    <td style={{ ...sharedStyles.td, fontVariantNumeric: "tabular-nums" }}>
                      <WinRateBar val={isNaN(wr) ? 0 : wr} />
                    </td>
                    <td style={{ ...sharedStyles.td, fontVariantNumeric: "tabular-nums" }}>{d.avgScore}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      </div>

      {/* Positions section */}
      <div style={{ padding: "0 24px 24px" }}>
        <div style={{ marginBottom: 14 }}>
          <div style={{ display: "flex", gap: 0, borderBottom: "2px solid #E5E2D8", marginBottom: 0 }}>
            {["open", "closed"].map(tab => (
              <button
                key={tab}
                onClick={() => setPosTab(tab)}
                style={{
                  ...perfStyles.tabBtn,
                  borderBottom: posTab === tab ? "2px solid #1F1F1F" : "2px solid transparent",
                  color: posTab === tab ? "#1F1F1F" : "#687388",
                  fontWeight: posTab === tab ? 700 : 500,
                }}
              >
                {tab === "open" ? `Open Positions (${positions.open.length})` : `Closed Positions (${positions.closed.length})`}
              </button>
            ))}
          </div>
        </div>

        <Card>
          <table style={sharedStyles.table}>
            <thead>
              <tr>
                {posTab === "open"
                  ? ["Ticker","Contract","Type","Strike","Expiration","Qty","Entry Price","Status","Opened At"].map(h => <th key={h} style={sharedStyles.th}>{h}</th>)
                  : ["Ticker","Contract","Type","Strike","Expiration","Qty","Entry","Exit","Exit Reason","PnL","PnL %","Opened","Closed"].map(h => <th key={h} style={sharedStyles.th}>{h}</th>)
                }
              </tr>
            </thead>
            <tbody>
              {(posTab === "open" ? positions.open : positions.closed).map((pos, i) => (
                <tr key={pos.id} style={{ ...sharedStyles.tr, background: i % 2 === 0 ? "#fff" : "#FAFAF8" }}>
                  <td style={{ ...sharedStyles.td, fontWeight: 700 }}>{pos.ticker}</td>
                  <td style={{ ...sharedStyles.td, fontFamily: "monospace", fontSize: 11 }}>{pos.symbol}</td>
                  <td style={sharedStyles.td}><Badge label={pos.type} variant={pos.type === "Call" ? "positive" : "bearish"} /></td>
                  <td style={{ ...sharedStyles.td, fontVariantNumeric: "tabular-nums" }}>${pos.strike}</td>
                  <td style={{ ...sharedStyles.td, fontVariantNumeric: "tabular-nums", color: "#687388" }}>{pos.expiration}</td>
                  <td style={{ ...sharedStyles.td, fontVariantNumeric: "tabular-nums" }}>{pos.qty}</td>
                  <td style={{ ...sharedStyles.td, fontVariantNumeric: "tabular-nums" }}>${pos.entryPrice}</td>
                  {posTab === "closed" && <>
                    <td style={{ ...sharedStyles.td, fontVariantNumeric: "tabular-nums" }}>${pos.exitPrice}</td>
                    <td style={sharedStyles.td}><Badge label={pos.exitReason} variant={pos.exitReason === "stop" ? "bearish" : "default"} /></td>
                    <td style={{ ...sharedStyles.td, fontWeight: 700, color: pos.pnl >= 0 ? "#16A34A" : "#DC2626", fontVariantNumeric: "tabular-nums" }}>
                      {pos.pnl >= 0 ? "+" : ""}${pos.pnl}
                    </td>
                    <td style={{ ...sharedStyles.td, fontWeight: 600, color: pos.pnlPct >= 0 ? "#16A34A" : "#DC2626", fontVariantNumeric: "tabular-nums" }}>
                      {pos.pnlPct >= 0 ? "+" : ""}{pos.pnlPct}%
                    </td>
                    <td style={{ ...sharedStyles.td, fontSize: 11, color: "#687388" }}>{pos.openedAt}</td>
                    <td style={{ ...sharedStyles.td, fontSize: 11, color: "#687388" }}>{pos.closedAt}</td>
                  </>}
                  {posTab === "open" && <>
                    <td style={sharedStyles.td}><Badge label={pos.status} variant="open" /></td>
                    <td style={{ ...sharedStyles.td, fontSize: 11, color: "#687388" }}>{pos.openedAt}</td>
                  </>}
                </tr>
              ))}
            </tbody>
          </table>
          {(posTab === "open" ? positions.open : positions.closed).length === 0 && (
            <div style={{ padding: "24px", textAlign: "center", color: "#687388", fontSize: 12 }}>No {posTab} positions</div>
          )}
        </Card>
      </div>
    </div>
  );
}

function GradeDistribution({ grades }) {
  const total = Object.values(grades).reduce((s, v) => s + v, 0);
  const colors = { A: "#16A34A", B: "#2563EB", "B-": "#D97706", C: "#DC2626" };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {Object.entries(grades).map(([g, count]) => (
        <div key={g} style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ width: 20, fontSize: 11, fontWeight: 700, color: colors[g] }}>{g}</span>
          <div style={{ flex: 1, height: 10, background: "#F3F0EA", borderRadius: 3, overflow: "hidden" }}>
            <div style={{ width: `${(count / total) * 100}%`, height: "100%", background: colors[g], borderRadius: 3 }} />
          </div>
          <span style={{ fontSize: 11, color: "#687388", width: 20, textAlign: "right" }}>{count}</span>
        </div>
      ))}
      <div style={{ marginTop: 4, fontSize: 10, color: "#687388" }}>Total: {total} alerts</div>
    </div>
  );
}

function WinRateBar({ val }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
      <div style={{ width: 50, height: 4, background: "#E5E2D8", borderRadius: 2, overflow: "hidden" }}>
        <div style={{ width: `${val * 100}%`, height: "100%", background: val >= 0.6 ? "#16A34A" : val >= 0.4 ? "#D97706" : "#DC2626", borderRadius: 2 }} />
      </div>
      <span style={{ fontSize: 11, fontVariantNumeric: "tabular-nums" }}>{(val * 100).toFixed(0)}%</span>
    </div>
  );
}

const perfStyles = {
  kpiRow: {
    display: "flex",
    gap: 12,
    padding: "16px 24px",
    flexShrink: 0,
  },
  chartsRow: {
    display: "flex",
    gap: 16,
    padding: "0 24px 16px",
    flexShrink: 0,
  },
  tabBtn: {
    padding: "8px 16px",
    border: "none",
    background: "none",
    fontSize: 13,
    cursor: "pointer",
    fontFamily: "inherit",
    marginBottom: -2,
    transition: "all 0.1s",
  },
};

Object.assign(window, { Performance });
