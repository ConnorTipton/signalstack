// Alerts list screen + Source Trace + Settings stubs

function Alerts({ onNav, onSelectAlert }) {
  const { data: alerts, live } = useAutoRefresh(() => SS_API.alerts(), [], 30000);
  const [selected, setSelected] = React.useState(null);
  const [search, setSearch] = React.useState("");
  const [filter, setFilter] = React.useState("All");

  const filtered = alerts.filter(a => {
    if (search && !a.ticker.toLowerCase().includes(search.toLowerCase())
               && !a.contract.toLowerCase().includes(search.toLowerCase())) {
      return false;
    }
    if (filter === "All") return true;
    if (filter === "Bullish") return a.direction === "bullish";
    if (filter === "Bearish") return a.direction === "bearish";
    if (filter === "Watch") return a.status === "Watch";
    if (filter === "Sent") return a.status === "Sent";
    return true;
  });

  const chipStyle = (active) => ({
    padding: "4px 10px",
    border: `1px solid ${active ? "#1F1F1F" : "#E5E2D8"}`,
    borderRadius: 20,
    background: active ? "#1F1F1F" : "#fff",
    color: active ? "#fff" : "#687388",
    fontSize: 11,
    cursor: "pointer",
    fontFamily: "inherit",
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1, overflow: "hidden" }}>
      <div style={{ padding: "12px 24px", borderBottom: "1px solid #E5E2D8", display: "flex", gap: 10, alignItems: "center", background: "#FAF7F1", flexShrink: 0 }}>
        <input
          placeholder="Search ticker or contract…"
          value={search}
          onChange={e => setSearch(e.target.value)}
          style={{ padding: "6px 12px", border: "1px solid #E5E2D8", borderRadius: 6, fontSize: 12, width: 240, fontFamily: "inherit", background: "#fff", outline: "none" }}
        />
        <div style={{ display: "flex", gap: 4 }}>
          {["All", "Bullish", "Bearish", "Watch", "Sent"].map(f => (
            <button key={f} onClick={() => setFilter(f)} style={chipStyle(filter === f)}>{f}</button>
          ))}
        </div>
        <span style={{ marginLeft: "auto", fontSize: 11, color: "#687388" }}>
          {filtered.length} of {alerts.length} alerts{live ? "" : " (backend unreachable)"}
        </span>
      </div>

      <div style={{ padding: "16px 24px", flex: 1, overflowY: "auto" }}>
        <Card>
          <table style={sharedStyles.table}>
            <thead>
              <tr>
                {["Time","Ticker","Direction","Score","Grade","Contract","Source Tier","Spread","Status","Dry Run","Telegram"].map(h => (
                  <th key={h} style={sharedStyles.th}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((a, i) => (
                <tr
                  key={a.id}
                  onClick={() => { setSelected(a.id); onSelectAlert(a); onNav("alert-detail"); }}
                  style={{ ...sharedStyles.tr, background: i % 2 === 0 ? "#fff" : "#FAFAF8", cursor: "pointer", borderLeft: selected === a.id ? "3px solid #2563EB" : "3px solid transparent" }}
                >
                  <td style={{ ...sharedStyles.td, color: "#687388", fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }}>{a.time}</td>
                  <td style={{ ...sharedStyles.td, fontWeight: 700 }}>{a.ticker}</td>
                  <td style={sharedStyles.td}><DirectionBadge dir={a.direction} /></td>
                  <td style={{ ...sharedStyles.td, fontWeight: 700 }}>{a.score}</td>
                  <td style={sharedStyles.td}><GradeBadge grade={a.grade} /></td>
                  <td style={{ ...sharedStyles.td, fontFamily: "monospace", fontSize: 11 }}>{a.contract}</td>
                  <td style={sharedStyles.td}><Badge label={a.sourceTier} variant={a.sourceTier === "Tier 1" ? "tier-1" : "tier-2"} /></td>
                  <td style={{ ...sharedStyles.td, color: parseFloat(a.spread) > 15 ? "#DC2626" : "#687388" }}>{a.spread}</td>
                  <td style={sharedStyles.td}><Badge label={a.status} variant={a.status.toLowerCase()} /></td>
                  <td style={sharedStyles.td}><Badge label={a.dryRun ? "true" : "false"} variant={a.dryRun ? "amber" : "default"} /></td>
                  <td style={sharedStyles.td}><Badge label={a.telegram ? "Yes" : "No"} variant={a.telegram ? "positive" : "default"} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
    </div>
  );
}

function SourceTrace() {
  const { data: rows, live } = useAutoRefresh(() => SS_API.sourceTrace(100), [], 60000);
  return (
    <div style={{ padding: "24px", flex: 1, overflowY: "auto" }}>
      <Card>
        <div style={{ padding: "12px 16px", borderBottom: "1px solid #E5E2D8" }}>
          <span style={{ fontSize: 13, fontWeight: 700 }}>Full Source Trace</span>
          <p style={{ fontSize: 11, color: "#687388", marginTop: 4, marginBottom: 0 }}>
            Complete audit trail of article ingestion from raw provider events to normalized alerts.
            {live ? "" : " (backend unreachable)"}
          </p>
        </div>
        {rows.length === 0 ? (
          <div style={{ padding: "32px", textAlign: "center", color: "#687388", fontSize: 12 }}>
            No news articles ingested yet.
          </div>
        ) : (
          <table style={sharedStyles.table}>
            <thead>
              <tr>{["article_id","provider_name","source_tier","raw_table","raw_event_id","received_at","title"].map(h => <th key={h} style={sharedStyles.th}>{h}</th>)}</tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={row.articleId} style={{ ...sharedStyles.tr, background: i % 2 === 0 ? "#fff" : "#FAFAF8" }}>
                  <td style={{ ...sharedStyles.td, fontFamily: "monospace", fontSize: 11 }}>{row.articleId}</td>
                  <td style={{ ...sharedStyles.td, fontWeight: 600 }}>{row.provider}</td>
                  <td style={sharedStyles.td}><Badge label={row.sourceTier} variant={row.sourceTier === "Tier 1" ? "tier-1" : row.sourceTier === "Tier 2" ? "tier-2" : "default"} /></td>
                  <td style={{ ...sharedStyles.td, fontFamily: "monospace", fontSize: 11, color: "#687388" }}>{row.rawTable}</td>
                  <td style={{ ...sharedStyles.td, fontFamily: "monospace", fontSize: 11, color: "#687388" }}>{row.rawEventId}</td>
                  <td style={{ ...sharedStyles.td, fontFamily: "monospace", fontSize: 11, color: "#687388" }}>{row.receivedAt}</td>
                  <td style={{ ...sharedStyles.td, fontSize: 11, maxWidth: 380, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{row.title}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}

function Settings() {
  const { data: rows, live, error } = useAPI(() => SS_API.settings(), []);
  const paperOnly = rows.find(r => r.key === "PAPER_ONLY")?.value === "true";
  return (
    <div style={{ padding: "24px", flex: 1, overflowY: "auto" }}>
      <Card>
        <div style={{ padding: "12px 16px", borderBottom: "1px solid #E5E2D8" }}>
          <span style={{ fontSize: 13, fontWeight: 700 }}>System Configuration</span>
          <p style={{ fontSize: 11, color: "#687388", marginTop: 4, marginBottom: 0 }}>
            Read-only view of active runtime settings from .env and config.
            {!live && error ? ` (load error: ${error})` : ""}
          </p>
        </div>
        {rows.length === 0 ? (
          <div style={{ padding: "32px", textAlign: "center", color: "#687388", fontSize: 12 }}>
            {live ? "No settings returned." : "Loading…"}
          </div>
        ) : (
          <table style={sharedStyles.table}>
            <thead>
              <tr>{["Section","Key","Value"].map(h => <th key={h} style={sharedStyles.th}>{h}</th>)}</tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={r.key} style={{ ...sharedStyles.tr, background: i % 2 === 0 ? "#fff" : "#FAFAF8" }}>
                  <td style={{ ...sharedStyles.td, color: "#687388", fontSize: 11 }}>{r.section}</td>
                  <td style={{ ...sharedStyles.td, fontFamily: "monospace", fontWeight: 600, fontSize: 11 }}>{r.key}</td>
                  <td style={sharedStyles.td}>
                    {r.kind === "badge"
                      ? <Badge label={r.value} variant={r.variant || "default"} />
                      : <span style={{ fontSize: 12, color: "#1F1F1F" }}>{r.value}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      {paperOnly && (
        <div style={{ marginTop: 16, padding: "12px 16px", background: "#FEF3C7", border: "1px solid #FDE68A", borderRadius: 8, display: "flex", gap: 10, alignItems: "center" }}>
          <span style={{ fontSize: 16 }}>⚠</span>
          <span style={{ fontSize: 12, color: "#92400E" }}>
            <strong>Paper Only / Live Disabled.</strong> This system operates in paper-trading mode only. Live execution is not enabled.
          </span>
        </div>
      )}
    </div>
  );
}

Object.assign(window, { Alerts, SourceTrace, Settings });
