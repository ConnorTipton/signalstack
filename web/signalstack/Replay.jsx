// Replay Report Screen

const EMPTY_REPLAY = {
  kpis: {
    newsArticles: 0, detectedEvents: 0, signalCandidates: 0,
    alertsSent: 0, positionsOpened: 0, positionsClosed: 0,
    realizedPnl: 0, winRate: 0,
  },
  events: [], sourceTrace: [], detectors: [],
};

function _todayAt(hours, minutes) {
  const d = new Date();
  d.setHours(hours, minutes, 0, 0);
  return d;
}

function _fmtLocalInput(d) {
  const pad = n => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function _parseLocalInput(s) {
  // Accepts "YYYY-MM-DD HH:MM" (or the T-separated variant); returns ISO for API.
  const m = s.trim().replace("T", " ").match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
  if (!m) return null;
  const [, y, mo, da, h, mi] = m;
  const d = new Date(Number(y), Number(mo) - 1, Number(da), Number(h), Number(mi));
  return isNaN(d.getTime()) ? null : d.toISOString().slice(0, 19);
}

function Replay() {
  const [running, setRunning] = React.useState(false);
  const [replayData, setReplayData] = React.useState(null);
  const [windowStart, setWindowStart] = React.useState(_fmtLocalInput(_todayAt(9, 30)));
  const [windowEnd, setWindowEnd] = React.useState(_fmtLocalInput(_todayAt(16, 0)));
  const [monitoredTickers, setMonitoredTickers] = React.useState([]);
  const [selectedTickers, setSelectedTickers] = React.useState([]);
  const [maxEvents, setMaxEvents] = React.useState(250);
  const [loadError, setLoadError] = React.useState(null);

  React.useEffect(() => {
    SS_API.settings()
      .then(rows => {
        const row = rows.find(r => r.key === "MONITORED_TICKERS");
        const tickers = row ? row.value.split(",").map(s => s.trim()).filter(Boolean) : [];
        setMonitoredTickers(tickers);
        setSelectedTickers(tickers);
      })
      .catch(() => {});
  }, []);

  const data = replayData || EMPTY_REPLAY;

  const eventColors = {
    news_article: "#2563EB",
    detected_event: "#D97706",
    signal_candidate: "#7C3AED",
    alert: "#16A34A",
    position_open: "#059669",
    position_close: "#687388",
  };
  const outcomeVariant = { Promoted: "positive", Sent: "sent", Opened: "open", Closed: "closed", amber: "amber" };

  const handleRun = () => {
    const startISO = _parseLocalInput(windowStart);
    const endISO = _parseLocalInput(windowEnd);
    if (!startISO || !endISO) {
      setLoadError("Invalid date format. Use YYYY-MM-DD HH:MM");
      return;
    }
    if (selectedTickers.length === 0) {
      setLoadError("Pick at least one ticker.");
      return;
    }
    setLoadError(null);
    setRunning(true);
    SS_API.replay({
      window_start: startISO,
      window_end: endISO,
      ticker: selectedTickers,
      max_events: maxEvents,
    })
      .then(d => { setReplayData(d); })
      .catch(err => { setLoadError(err.message || "Replay failed"); })
      .finally(() => setRunning(false));
  };

  const removeTicker = t => setSelectedTickers(xs => xs.filter(x => x !== t));
  const addTicker = t => setSelectedTickers(xs => xs.includes(t) ? xs : [...xs, t]);
  const bumpMax = delta => setMaxEvents(n => Math.max(1, Math.min(5000, n + delta)));

  const availableToAdd = monitoredTickers.filter(t => !selectedTickers.includes(t));

  const kpis = data.kpis;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 0, flex: 1, overflow: "hidden" }}>
      {/* Controls */}
      <div style={rpStyles.controls}>
        <div style={rpStyles.dateRange}>
          <span style={rpStyles.calIcon}>📅</span>
          <input
            style={rpStyles.dateInput}
            value={windowStart}
            onChange={e => setWindowStart(e.target.value)}
            placeholder="YYYY-MM-DD HH:MM"
          />
          <span style={{ color: "#687388" }}>—</span>
          <input
            style={rpStyles.dateInput}
            value={windowEnd}
            onChange={e => setWindowEnd(e.target.value)}
            placeholder="YYYY-MM-DD HH:MM"
          />
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
          {selectedTickers.map(t => (
            <span key={t} style={rpStyles.tickerChip}>
              {t}{" "}
              <span style={{ color: "#E5E2D8", cursor: "pointer" }} onClick={() => removeTicker(t)}>×</span>
            </span>
          ))}
          {availableToAdd.length > 0 && (
            <select
              onChange={e => { if (e.target.value) { addTicker(e.target.value); e.target.value = ""; } }}
              defaultValue=""
              style={{ fontSize: 11, padding: "3px 6px", border: "1px solid #E5E2D8", borderRadius: 12, background: "#fff", fontFamily: "inherit", cursor: "pointer" }}
            >
              <option value="">+ add…</option>
              {availableToAdd.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginLeft: "auto" }}>
          <span style={{ fontSize: 12, color: "#687388" }}>Max events</span>
          <div style={rpStyles.spinnerBox}>
            <input
              type="number"
              value={maxEvents}
              min={1}
              max={5000}
              onChange={e => setMaxEvents(Math.max(1, Math.min(5000, parseInt(e.target.value, 10) || 1)))}
              style={{ ...rpStyles.spinnerVal, border: "none", outline: "none", width: 50, background: "transparent", fontFamily: "inherit" }}
            />
            <div style={{ display: "flex", flexDirection: "column" }}>
              <button style={rpStyles.spinBtn} onClick={() => bumpMax(50)}>▲</button>
              <button style={rpStyles.spinBtn} onClick={() => bumpMax(-50)}>▼</button>
            </div>
          </div>
          <button onClick={handleRun} style={rpStyles.runBtn} disabled={running}>
            {running ? "⟳ Running…" : "▶ Run Replay"}
          </button>
        </div>
        {loadError && (
          <div style={{ width: "100%", fontSize: 11, color: "#DC2626", marginTop: 6 }}>{loadError}</div>
        )}
      </div>

      {/* KPIs */}
      <div style={rpStyles.kpiRow}>
        {[
          { label: "News Articles", value: kpis.newsArticles },
          { label: "Detected Events", value: kpis.detectedEvents },
          { label: "Signal Candidates", value: kpis.signalCandidates },
          { label: "Alerts Sent", value: kpis.alertsSent },
          { label: "Positions Opened", value: kpis.positionsOpened },
          { label: "Positions Closed", value: kpis.positionsClosed },
          { label: "Realized PnL", value: `+$${kpis.realizedPnl.toFixed(2)}`, color: "#16A34A" },
          { label: "Win Rate", value: `${kpis.winRate}%`, color: "#16A34A" },
        ].map(k => (
          <div key={k.label} style={rpStyles.kpi}>
            <div style={rpStyles.kpiLabel}>{k.label} <span style={{ color: "#C8C4BC", fontSize: 9 }}>ⓘ</span></div>
            <div style={{ ...rpStyles.kpiVal, color: k.color || "#1F1F1F" }}>{k.value}</div>
          </div>
        ))}
      </div>

      {/* Main area */}
      <div style={rpStyles.mainArea}>
        {/* Left: timeline */}
        <div style={rpStyles.timelineCol}>
          <Card style={{ flex: 1, display: "flex", flexDirection: "column" }}>
            <div style={{ padding: "12px 16px 10px", borderBottom: "1px solid #E5E2D8" }}>
              <span style={{ fontSize: 13, fontWeight: 700 }}>Replay Event Timeline</span>
            </div>
            <div style={{ overflowY: "auto", flex: 1 }}>
              <table style={sharedStyles.table}>
                <thead>
                  <tr>
                    {["", "Time", "Event Type", "Ticker", "Source / Detector", "Detail", "Outcome"].map(h => (
                      <th key={h} style={sharedStyles.th}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.events.map((ev, i) => (
                    <tr key={i} style={{ ...sharedStyles.tr, background: i % 2 === 0 ? "#fff" : "#FAFAF8" }}>
                      <td style={{ ...sharedStyles.td, width: 8, padding: "9px 8px 9px 12px" }}>
                        <span style={{ width: 7, height: 7, borderRadius: "50%", background: eventColors[ev.type] || "#687388", display: "inline-block" }} />
                      </td>
                      <td style={{ ...sharedStyles.td, color: "#687388", fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }}>{ev.time}</td>
                      <td style={sharedStyles.td}>
                        <span style={{ fontSize: 11, fontFamily: "monospace", fontWeight: 600, color: eventColors[ev.type] || "#687388" }}>{ev.type}</span>
                      </td>
                      <td style={{ ...sharedStyles.td, fontWeight: 700 }}>{ev.ticker}</td>
                      <td style={{ ...sharedStyles.td, color: "#687388", fontSize: 11 }}>{ev.sourceDetector}</td>
                      <td style={{ ...sharedStyles.td, fontSize: 11 }}>{ev.detail}</td>
                      <td style={sharedStyles.td}>
                        {ev.outcome && ev.outcome !== "amber" && <Badge label={ev.outcome} variant={outcomeVariant[ev.outcome] || "default"} />}
                        {ev.outcome === "amber" && <span style={{ width: 8, height: 8, borderRadius: "50%", background: "#D97706", display: "inline-block" }} />}
                        {!ev.outcome && <span style={{ color: "#C8C4BC" }}>—</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          {/* Source trace */}
          <Card style={{ flexShrink: 0 }}>
            <div style={{ padding: "12px 16px 10px", borderBottom: "1px solid #E5E2D8", display: "flex", justifyContent: "space-between" }}>
              <span style={{ fontSize: 13, fontWeight: 700 }}>Provider Source Trace</span>
            </div>
            <table style={sharedStyles.table}>
              <thead>
                <tr>
                  {["article_id", "provider_name", "provider_status", "source_tier", "raw_table", "raw_event_id", "received_at"].map(h => (
                    <th key={h} style={sharedStyles.th}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.sourceTrace.map((row, i) => (
                  <tr key={i} style={{ ...sharedStyles.tr, background: i % 2 === 0 ? "#fff" : "#FAFAF8" }}>
                    <td style={{ ...sharedStyles.td, fontFamily: "monospace", fontSize: 11 }}>{row.articleId}</td>
                    <td style={{ ...sharedStyles.td, fontWeight: 600 }}>{row.provider}</td>
                    <td style={sharedStyles.td}><div style={{ display: "flex", alignItems: "center", gap: 5 }}><StatusDot status={row.providerStatus} />{row.providerStatus}</div></td>
                    <td style={sharedStyles.td}><Badge label={row.sourceTier} variant={row.sourceTier === "Tier 1" ? "tier-1" : row.sourceTier === "Tier 2" ? "tier-2" : "default"} /></td>
                    <td style={{ ...sharedStyles.td, fontFamily: "monospace", fontSize: 11, color: "#687388" }}>{row.rawTable}</td>
                    <td style={{ ...sharedStyles.td, fontFamily: "monospace", fontSize: 11, color: "#687388" }}>{row.rawEventId}</td>
                    <td style={{ ...sharedStyles.td, fontFamily: "monospace", fontSize: 11, color: "#687388" }}>{row.receivedAt}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div style={{ padding: "8px 16px", borderTop: "1px solid #E5E2D8", display: "flex", justifyContent: "space-between" }}>
              <span style={{ fontSize: 11, color: "#687388" }}>Showing {data.sourceTrace.length} of {data.sourceTrace.length} rows</span>
              <button style={{ background: "none", border: "none", color: "#2563EB", fontSize: 11, cursor: "pointer", fontFamily: "inherit" }}>View full source trace →</button>
            </div>
          </Card>
        </div>

        {/* Right: postmortems + summary */}
        <div style={rpStyles.rightCol}>
          {/* Detector postmortems */}
          <Card>
            <div style={{ padding: "12px 16px 10px", borderBottom: "1px solid #E5E2D8" }}>
              <span style={{ fontSize: 13, fontWeight: 700 }}>Detector Postmortems</span>
            </div>
            <table style={sharedStyles.table}>
              <thead>
                <tr>{["Detector","Type","Events","Led to Signal","Led to Alert","Notes"].map(h => <th key={h} style={sharedStyles.th}>{h}</th>)}</tr>
              </thead>
              <tbody>
                {data.detectors.map((d, i) => (
                  <tr key={d.id} style={{ ...sharedStyles.tr, background: i % 2 === 0 ? "#fff" : "#FAFAF8" }}>
                    <td style={{ ...sharedStyles.td, fontWeight: 600 }}>{d.name}</td>
                    <td style={{ ...sharedStyles.td, color: "#687388" }}>{d.type}</td>
                    <td style={{ ...sharedStyles.td, fontVariantNumeric: "tabular-nums" }}>{d.totalEvents}</td>
                    <td style={{ ...sharedStyles.td, fontVariantNumeric: "tabular-nums" }}>{d.ledToSignal}</td>
                    <td style={{ ...sharedStyles.td, fontVariantNumeric: "tabular-nums" }}>{d.ledToAlert}</td>
                    <td style={sharedStyles.td}>
                      <Badge label={d.notes} variant={d.notes === "Tier 1 aligned" ? "tier-1" : d.notes === "high precision" ? "positive" : "default"} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div style={{ padding: "8px 16px", borderTop: "1px solid #E5E2D8" }}>
              <button style={{ background: "none", border: "none", color: "#2563EB", fontSize: 11, cursor: "pointer", fontFamily: "inherit" }}>View detector details →</button>
            </div>
          </Card>

          {/* Outcome summary */}
          <Card>
            <div style={{ padding: "12px 16px 10px", borderBottom: "1px solid #E5E2D8" }}>
              <span style={{ fontSize: 13, fontWeight: 700 }}>Replay Outcome Summary</span>
            </div>
            <div style={{ padding: "14px 16px", display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
                <span style={{ width: 24, height: 24, borderRadius: "50%", background: "#DCFCE7", border: "2px solid #16A34A", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, flexShrink: 0 }}>✓</span>
                <p style={{ fontSize: 12, color: "#1F1F1F", margin: 0, lineHeight: 1.5 }}>
                  AAPL sequence fully aligned across news, price, and options; alert sent and paper position opened.
                </p>
              </div>
              {[
                { icon: "⊡", label: "Auditability", value: "full" },
                { icon: "⟳", label: "Replay status", value: "completed" },
                { icon: "⇌", label: "Decision path", value: "reviewable" },
              ].map(r => (
                <div key={r.label} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span style={{ fontSize: 16, width: 24, textAlign: "center", color: "#687388" }}>{r.icon}</span>
                  <span style={{ fontSize: 12, color: "#687388", minWidth: 110 }}>{r.label}:</span>
                  <span style={{ fontSize: 12, fontWeight: 600, color: "#1F1F1F" }}>{r.value}</span>
                </div>
              ))}
              <button style={{ background: "none", border: "none", color: "#2563EB", fontSize: 11, cursor: "pointer", fontFamily: "inherit", textAlign: "left", padding: 0 }}>View decision path →</button>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

const rpStyles = {
  controls: {
    padding: "12px 24px",
    borderBottom: "1px solid #E5E2D8",
    display: "flex",
    alignItems: "center",
    gap: 12,
    background: "#FAF7F1",
    flexShrink: 0,
    flexWrap: "wrap",
  },
  dateRange: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    border: "1px solid #E5E2D8",
    borderRadius: 6,
    padding: "5px 10px",
    background: "#fff",
    fontSize: 12,
  },
  calIcon: { fontSize: 14 },
  dateInput: {
    border: "none",
    outline: "none",
    fontSize: 12,
    color: "#1F1F1F",
    background: "transparent",
    fontFamily: "inherit",
    width: 130,
  },
  tickerChip: {
    display: "inline-flex",
    alignItems: "center",
    gap: 4,
    padding: "4px 10px",
    background: "#1F1F1F",
    color: "#fff",
    borderRadius: 20,
    fontSize: 11,
    fontWeight: 600,
  },
  spinnerBox: {
    display: "flex",
    alignItems: "center",
    border: "1px solid #E5E2D8",
    borderRadius: 6,
    background: "#fff",
    overflow: "hidden",
  },
  spinnerVal: { padding: "5px 12px", fontSize: 12, fontVariantNumeric: "tabular-nums" },
  spinBtn: { background: "none", border: "none", fontSize: 8, cursor: "pointer", padding: "2px 6px", color: "#687388", lineHeight: 1, fontFamily: "inherit" },
  runBtn: {
    padding: "8px 20px",
    background: "#1F1F1F",
    color: "#fff",
    border: "none",
    borderRadius: 6,
    fontSize: 13,
    fontWeight: 700,
    cursor: "pointer",
    fontFamily: "inherit",
    whiteSpace: "nowrap",
  },
  kpiRow: {
    display: "flex",
    gap: 0,
    borderBottom: "1px solid #E5E2D8",
    flexShrink: 0,
  },
  kpi: {
    flex: 1,
    padding: "12px 16px",
    borderRight: "1px solid #E5E2D8",
  },
  kpiLabel: { fontSize: 10, color: "#687388", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em", marginBottom: 4 },
  kpiVal: { fontSize: 22, fontWeight: 700, letterSpacing: "-0.02em" },
  mainArea: {
    display: "flex",
    gap: 16,
    padding: "16px 24px",
    flex: 1,
    minHeight: 0,
    overflow: "hidden",
  },
  timelineCol: {
    flex: 1.6,
    display: "flex",
    flexDirection: "column",
    gap: 16,
    minWidth: 0,
    overflowY: "auto",
  },
  rightCol: {
    width: 360,
    flexShrink: 0,
    display: "flex",
    flexDirection: "column",
    gap: 16,
    overflowY: "auto",
  },
};

Object.assign(window, { Replay });
