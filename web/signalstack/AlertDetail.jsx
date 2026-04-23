// Alert Detail Screen

function AlertDetail({ alert: alertProp }) {
  const [alert, setAlert] = React.useState(alertProp);

  // Fetch full evidence-enriched alert when we have a real numeric ID
  React.useEffect(() => {
    setAlert(alertProp);
    if (!alertProp) return;
    const numId = parseInt(alertProp.id, 10);
    if (!isNaN(numId)) {
      SS_API.alertById(numId)
        .then(full => setAlert(full))
        .catch(() => {}); // keep base on error
    }
  }, [alertProp?.id]);

  if (!alert) {
    return (
      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "#687388", padding: 40, textAlign: "center" }}>
        <div>
          <div style={{ fontSize: 28, marginBottom: 10, opacity: 0.4 }}>◈</div>
          <div style={{ fontSize: 14, fontWeight: 600, color: "#1F1F1F", marginBottom: 4 }}>No alert selected</div>
          <div style={{ fontSize: 12, lineHeight: 1.6, maxWidth: 360 }}>
            Pick an alert from the Alerts or Overview screen to see its evidence trail, scoring, and paper execution.
          </div>
        </div>
      </div>
    );
  }

  const news    = alert.news    || null;
  const price   = alert.price   || null;
  const options = alert.options || null;
  const scoring = alert.scoring || null;

  const scoreTotal = scoring ? scoring.total : 0;
  const gradeColor = { A: "#16A34A", B: "#2563EB", "B-": "#D97706", C: "#DC2626" }[alert.grade] || "#687388";

  const noData = <span style={{ fontSize: 11, color: "#687388", fontStyle: "italic" }}>No data recorded for this detector.</span>;

  const evidenceSteps = [
    { num: 1, title: "Tier 1 News Catalyst", badge: news ? "Positive" : "—", badgeVariant: news ? "positive" : "default", content: news ? (
      <div>
        <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
          <Badge label={news.source} variant="tier-1" />
          <Badge label="Wire" variant="default" />
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 12, marginBottom: 10 }}>
          <div><div style={adStyles.miniLabel}>Event type</div><div style={adStyles.miniVal}>{news.eventType}</div></div>
          <div><div style={adStyles.miniLabel}>Polarity</div><div style={{ ...adStyles.miniVal, color: "#16A34A" }}>{news.polarity}</div></div>
          <div><div style={adStyles.miniLabel}>Confidence</div><div style={adStyles.miniVal}>{news.confidence}</div></div>
          <div><div style={adStyles.miniLabel}>Importance</div><div style={{ ...adStyles.miniVal, color: "#D97706" }}>{news.importance}</div></div>
        </div>
        <div style={adStyles.llmBox}>
          <span style={adStyles.miniLabel}>LLM Summary: </span>
          <span style={{ fontSize: 11, color: "#1F1F1F", lineHeight: 1.5 }}>{news.llmSummary}</span>
        </div>
      </div>
    ) : noData},
    { num: 2, title: "Price Detector", badge: price ? "Confirmed" : "—", badgeVariant: price ? "positive" : "default", content: price ? (
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>
        <div><div style={adStyles.miniLabel}>Pattern</div><div style={adStyles.miniVal}>{price.pattern}</div></div>
        <div><div style={adStyles.miniLabel}>Trigger price</div><div style={{ ...adStyles.miniVal, fontFamily: "monospace" }}>{price.triggerPrice || "—"}</div></div>
        <div><div style={adStyles.miniLabel}>Confidence</div><div style={adStyles.miniVal}>{price.confidence}</div></div>
        <div style={{ gridColumn: "1 / -1" }}><div style={adStyles.miniLabel}>Confirmation</div><div style={adStyles.miniVal}>{price.confirmation || "—"}</div></div>
      </div>
    ) : noData},
    { num: 3, title: "Options Detector", badge: options ? "Supportive" : "—", badgeVariant: options ? "info" : "default", content: options ? (
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>
        <div><div style={adStyles.miniLabel}>Signal</div><div style={adStyles.miniVal}>{options.signal}</div></div>
        <div><div style={adStyles.miniLabel}>Provider mode</div><div style={adStyles.miniVal}>{options.providerMode}</div></div>
        <div><div style={adStyles.miniLabel}>Relative activity</div><div style={{ ...adStyles.miniVal, color: "#16A34A", fontWeight: 700 }}>{options.relativeActivity}</div></div>
        <div><div style={adStyles.miniLabel}>Confidence</div><div style={adStyles.miniVal}>{options.confidence}</div></div>
      </div>
    ) : noData},
    { num: 4, title: "Scoring", badge: null, content: scoring ? (
      <div style={{ display: "flex", gap: 20, alignItems: "flex-start" }}>
        <table style={{ ...sharedStyles.table, flex: 1 }}>
          <thead>
            <tr>{["Component","Score","Weight","Weighted"].map(h => <th key={h} style={sharedStyles.th}>{h}</th>)}</tr>
          </thead>
          <tbody>
            {[
              ["News score", scoring.news?.score, `${scoring.news?.weight ?? 30}%`, scoring.news?.weighted],
              ["Price score", scoring.price?.score, `${scoring.price?.weight ?? 25}%`, scoring.price?.weighted],
              ["Options score", scoring.options?.score, `${scoring.options?.weight ?? 25}%`, scoring.options?.weighted],
              ["Liquidity score", scoring.liquidity?.score, `${scoring.liquidity?.weight ?? 10}%`, scoring.liquidity?.weighted],
              ["Data confidence score", scoring.dataConfidence?.score, `${scoring.dataConfidence?.weight ?? 10}%`, scoring.dataConfidence?.weighted],
            ].map(([label, score, weight, weighted]) => (
              <tr key={label} style={{ background: "#fff" }}>
                <td style={sharedStyles.td}>{label}</td>
                <td style={{ ...sharedStyles.td, fontVariantNumeric: "tabular-nums" }}>{score ?? "—"}</td>
                <td style={{ ...sharedStyles.td, color: "#687388" }}>{weight}</td>
                <td style={{ ...sharedStyles.td, fontVariantNumeric: "tabular-nums" }}>{weighted ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4, padding: "8px 20px", border: "2px solid #E5E2D8", borderRadius: 8, minWidth: 90 }}>
          <span style={{ fontSize: 10, color: "#687388", textTransform: "uppercase", letterSpacing: "0.05em" }}>Total Score</span>
          <span style={{ fontSize: 36, fontWeight: 800, color: "#1F1F1F", lineHeight: 1 }}>{scoreTotal}</span>
          <span style={{ fontSize: 10, color: "#687388", textTransform: "uppercase", letterSpacing: "0.05em", marginTop: 4 }}>Grade</span>
          <span style={{ fontSize: 24, fontWeight: 700, color: gradeColor }}>{alert.grade}</span>
        </div>
      </div>
    ) : noData},
    { num: 5, title: "Contract Selector", badge: alert.contract_detail?.symbol ? "Selected" : "—", badgeVariant: alert.contract_detail?.symbol ? "positive" : "default", content: (
      <div>
        <div style={{ fontSize: 12, marginBottom: 10 }}>
          <strong>Selected contract:</strong>{" "}
          <span style={{ fontFamily: "monospace" }}>{alert.contract_detail?.symbol || "—"}</span>
        </div>
        {alert.contractRejected && alert.contractRejected.length > 0 && (
          <>
            <div style={adStyles.miniLabel}>Rejected alternatives</div>
            <table style={sharedStyles.table}>
              <thead><tr>{["Contract","Reason rejected"].map(h => <th key={h} style={sharedStyles.th}>{h}</th>)}</tr></thead>
              <tbody>
                {alert.contractRejected.map(c => (
                  <tr key={c.symbol} style={{ background: "#fff" }}>
                    <td style={{ ...sharedStyles.td, fontFamily: "monospace" }}>{c.symbol}</td>
                    <td style={{ ...sharedStyles.td, color: "#687388" }}>{c.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </div>
    )},
  ];

  return (
    <div style={{ display: "flex", flex: 1, gap: 0, minHeight: 0, overflow: "hidden" }}>
      {/* Left column */}
      <div style={adStyles.leftCol}>
        <div style={{ padding: "16px", borderBottom: "1px solid #E5E2D8" }}>
          <div style={adStyles.sectionLbl}>Alert Summary</div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
            <span style={{ fontSize: 24, fontWeight: 800, letterSpacing: "-0.03em", color: "#1F1F1F" }}>{alert.ticker} {alert.direction.toUpperCase()}</span>
            <span style={{ fontSize: 20, color: alert.direction === "bullish" ? "#16A34A" : "#DC2626" }}>{alert.direction === "bullish" ? "↑" : "↓"}</span>
          </div>
          <div style={{ display: "flex", gap: 10, marginBottom: 14 }}>
            <div style={adStyles.scoreBox}>
              <div style={adStyles.scoreLabel}>Score</div>
              <div style={adStyles.scoreVal}>{alert.score}</div>
            </div>
            <div style={adStyles.scoreBox}>
              <div style={adStyles.scoreLabel}>Grade</div>
              <div style={{ ...adStyles.scoreVal, color: gradeColor }}>{alert.grade}</div>
            </div>
            <div style={adStyles.scoreBox}>
              <div style={adStyles.scoreLabel}>Tier</div>
              <div style={adStyles.scoreVal}>{alert.sourceTier.replace("Tier ", "")}</div>
            </div>
            <Badge label="Tradeable" variant="positive" size="md" />
          </div>
          {[
            { label: "Sent to Telegram", value: alert.telegram ? "Yes" : "No", color: alert.telegram ? "#16A34A" : "#DC2626" },
            { label: "Dry run", value: String(alert.dryRun), color: "#D97706" },
            { label: "Data note", value: alert.dataCaveat || "no caveats", color: alert.dataCaveat ? "#D97706" : "#16A34A" },
            { label: "Direction", value: alert.direction, color: alert.direction === "bullish" ? "#16A34A" : "#DC2626" },
            { label: "Trigger status", value: "fired", color: "#16A34A" },
          ].map(r => (
            <div key={r.label} style={adStyles.metaRow}>
              <span style={adStyles.metaLabel}>{r.label}</span>
              <span style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: r.color, fontWeight: 600 }}>
                <span style={{ width: 6, height: 6, borderRadius: "50%", background: r.color, display: "inline-block" }} />
                {r.value}
              </span>
            </div>
          ))}
          <p style={{ fontSize: 11, color: "#687388", marginTop: 10, lineHeight: 1.5 }}>
            Signal promoted after aligned news, price confirmation, and directional options activity.
          </p>
        </div>

        {/* Contract section */}
        <div style={{ padding: "14px 16px" }}>
          <div style={adStyles.sectionLbl}>Contract</div>
          <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 12, fontFamily: "monospace" }}>{alert.contract_detail?.symbol || "—"}</div>
          {[
            ["Entry", alert.plan?.entry],
            ["Invalidation", alert.plan?.invalidation],
            ["Target 1", alert.plan?.target1],
            ["Target 2", alert.plan?.target2],
            ["Time stop", alert.plan?.timeStop],
          ].map(([k, v]) => (
            <div key={k} style={adStyles.planRow}>
              <span style={adStyles.metaLabel}>{k}</span>
              <span style={{ fontSize: 11, color: "#1F1F1F", flex: 1, lineHeight: 1.4 }}>{v || "—"}</span>
            </div>
          ))}
          <div style={{ marginTop: 10, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div>
              <span style={adStyles.metaLabel}>Liquidity</span>
              <span style={{ fontSize: 11, color: "#687388" }}> spread {alert.contract_detail?.spread || "—"}</span>
            </div>
            {alert.contract_detail?.spread && <Badge label="Liquid" variant="positive" />}
          </div>
          <div style={{ marginTop: 6, display: "flex", gap: 20 }}>
            <div><span style={adStyles.metaLabel}>OI</span> <span style={{ fontSize: 11, fontWeight: 600 }}>{alert.contract_detail?.oi?.toLocaleString() || "—"}</span></div>
            <div><span style={adStyles.metaLabel}>Volume</span> <span style={{ fontSize: 11, fontWeight: 600 }}>{alert.contract_detail?.volume ?? "—"}</span></div>
          </div>
        </div>
      </div>

      {/* Middle: evidence timeline */}
      <div style={adStyles.midCol}>
        <div style={{ padding: "14px 20px 10px", borderBottom: "1px solid #E5E2D8" }}>
          <div style={adStyles.sectionLbl}>Evidence Timeline</div>
        </div>
        <div style={{ padding: "16px 20px", overflowY: "auto", flex: 1, display: "flex", flexDirection: "column", gap: 12 }}>
          {evidenceSteps.map(step => (
            <div key={step.num} style={adStyles.evidenceCard}>
              <div style={adStyles.evidenceHeader}>
                <div style={adStyles.evidenceNum}>{step.num}</div>
                <span style={{ fontSize: 13, fontWeight: 700, color: "#1F1F1F", flex: 1 }}>{step.title}</span>
                {step.badge && <Badge label={step.badge} variant={step.badgeVariant} />}
              </div>
              <div style={{ padding: "12px 12px 12px 42px" }}>{step.content}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Right column */}
      <div style={adStyles.rightCol}>
        {/* Mini chart placeholder */}
        <div style={{ padding: "14px 16px 10px", borderBottom: "1px solid #E5E2D8" }}>
          <div style={adStyles.sectionLbl}>Underlying</div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
            <span style={{ fontSize: 14, fontWeight: 700 }}>{alert.ticker}</span>
            <span style={{ fontSize: 10, color: "#687388" }}>1-min preview</span>
          </div>
        </div>
        <div style={{ padding: "0 16px 12px", borderBottom: "1px solid #E5E2D8" }}>
          <MiniPriceChart ticker={alert.ticker} />
        </div>

        {/* Option quote */}
        <div style={{ padding: "14px 16px 10px", borderBottom: "1px solid #E5E2D8" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
            <div style={adStyles.sectionLbl}>Option Quote</div>
            {alert.contract_detail?.bid != null && <Badge label="Liquid" variant="positive" />}
          </div>
          <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 10, fontFamily: "monospace" }}>{alert.contract_detail?.symbol || "—"}</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
            {[
              ["Bid", alert.contract_detail?.bid != null ? `$${alert.contract_detail.bid}` : "—"],
              ["Ask", alert.contract_detail?.ask != null ? `$${alert.contract_detail.ask}` : "—"],
              ["Mid", alert.contract_detail?.mid != null ? `$${alert.contract_detail.mid}` : "—"],
              ["Spread", alert.contract_detail?.spread || "—"],
              ["OI", alert.contract_detail?.oi?.toLocaleString() || "—"],
              ["Volume", alert.contract_detail?.volume ?? "—"],
            ].map(([k, v]) => (
              <div key={k} style={{ textAlign: "center" }}>
                <div style={adStyles.miniLabel}>{k}</div>
                <div style={{ fontSize: 13, fontWeight: 700, color: "#1F1F1F", fontVariantNumeric: "tabular-nums" }}>{v}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Paper execution */}
        <div style={{ padding: "14px 16px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
            <div style={adStyles.sectionLbl}>Paper Execution</div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
            {[
              ["Order status", alert.execution?.orderStatus || "—"],
              ["Fill price", alert.execution?.fillPrice != null ? `$${alert.execution.fillPrice}` : "—"],
              ["Position", alert.execution?.position || "—"],
              ["Exit price", alert.execution?.exitPrice != null ? `$${alert.execution.exitPrice}` : "—"],
              ["Realized PnL", alert.execution?.realizedPnl != null ? <span style={{ color: alert.execution.realizedPnl >= 0 ? "#16A34A" : "#DC2626", fontWeight: 700 }}>{alert.execution.realizedPnl >= 0 ? "+" : ""}${alert.execution.realizedPnl}</span> : "—"],
              ["Entry time", alert.execution?.entryTime || "—"],
              ["Exit time", alert.execution?.exitTime || "—"],
              ["Duration", alert.execution?.duration || "—"],
            ].map(([k, v]) => (
              <div key={k}>
                <div style={adStyles.miniLabel}>{k}</div>
                <div style={{ fontSize: 12, color: "#1F1F1F", fontWeight: 500 }}>{v}</div>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 10, padding: "8px 10px", background: "#F3F0EA", borderRadius: 6 }}>
            <p style={{ fontSize: 10, color: "#687388", margin: 0, lineHeight: 1.5 }}>
              Execution was within modeled spread tolerance and met V1 liquidity rules.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

function MiniPriceChart({ ticker }) {
  const [bars, setBars] = React.useState([]);
  const [status, setStatus] = React.useState("loading");
  React.useEffect(() => {
    if (!ticker) return;
    setStatus("loading");
    SS_API.underlyingBars(ticker, 120)
      .then(b => { setBars(b); setStatus(b.length === 0 ? "empty" : "ok"); })
      .catch(() => setStatus("error"));
  }, [ticker]);

  const W = 260, H = 80;

  if (status !== "ok" || bars.length < 2) {
    const msg = status === "loading" ? "Loading bars…"
      : status === "empty" ? `No recent 1-min bars for ${ticker}.`
      : `Couldn't load bars for ${ticker}.`;
    return (
      <div style={{ height: H, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, color: "#687388", marginTop: 8, border: "1px dashed #E5E2D8", borderRadius: 4 }}>
        {msg}
      </div>
    );
  }

  const closes = bars.map(b => b.close);
  const vwapSeries = bars.map(b => b.vwap).filter(v => v != null);
  const allVals = [...closes, ...vwapSeries];
  const min = Math.min(...allVals);
  const max = Math.max(...allVals);
  const pad = (max - min) * 0.05 || 0.5;
  const yMin = min - pad;
  const yMax = max + pad;

  const toY = v => H - ((v - yMin) / (yMax - yMin)) * H * 0.9 - H * 0.05;
  const toX = i => (i / (bars.length - 1)) * W;
  const pricePts = closes.map((v, i) => `${toX(i)},${toY(v)}`).join(" ");
  const vwapPts = bars.map((b, i) => b.vwap != null ? `${toX(i)},${toY(b.vwap)}` : null).filter(Boolean).join(" ");

  const ticks = 4;
  const gridVals = Array.from({ length: ticks + 1 }, (_, i) => yMin + ((yMax - yMin) * i) / ticks);
  const tfmt = d => d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false });

  return (
    <div>
      <svg width={W} height={H} style={{ display: "block", marginTop: 8 }}>
        {gridVals.map((v, i) => (
          <g key={i}>
            <line x1={0} y1={toY(v)} x2={W} y2={toY(v)} stroke="#F0EDE7" strokeWidth={0.5} />
            <text x={W - 2} y={toY(v) + 3} fontSize={8} fill="#C8C4BC" textAnchor="end">{v.toFixed(2)}</text>
          </g>
        ))}
        <polyline points={pricePts} fill="none" stroke="#16A34A" strokeWidth={1.5} />
        {vwapPts && <polyline points={vwapPts} fill="none" stroke="#2563EB" strokeWidth={1} strokeDasharray="3,2" />}
      </svg>
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 2, fontSize: 9, color: "#687388" }}>
        <span>{tfmt(bars[0].time)}</span>
        <span>{bars.length} bars · close {closes[closes.length - 1].toFixed(2)}</span>
        <span>{tfmt(bars[bars.length - 1].time)}</span>
      </div>
    </div>
  );
}

const adStyles = {
  leftCol: { width: 230, flexShrink: 0, borderRight: "1px solid #E5E2D8", overflowY: "auto", background: "#FAF7F1" },
  midCol: { flex: 1, borderRight: "1px solid #E5E2D8", display: "flex", flexDirection: "column", overflowY: "auto", background: "#fff" },
  rightCol: { width: 300, flexShrink: 0, overflowY: "auto", background: "#FAF7F1" },
  sectionLbl: { fontSize: 10, fontWeight: 700, color: "#687388", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8 },
  scoreBox: { display: "flex", flexDirection: "column", alignItems: "center", padding: "6px 12px", border: "1px solid #E5E2D8", borderRadius: 6, background: "#fff" },
  scoreLabel: { fontSize: 9, color: "#687388", textTransform: "uppercase", letterSpacing: "0.05em" },
  scoreVal: { fontSize: 18, fontWeight: 700, color: "#1F1F1F", lineHeight: 1.2 },
  metaRow: { display: "flex", justifyContent: "space-between", alignItems: "center", paddingBottom: 5, marginBottom: 5, borderBottom: "1px solid #F3F0EA" },
  metaLabel: { fontSize: 11, color: "#687388" },
  planRow: { display: "flex", gap: 10, marginBottom: 7, alignItems: "flex-start" },
  evidenceCard: { border: "1px solid #E5E2D8", borderRadius: 8, overflow: "hidden", background: "#fff" },
  evidenceHeader: { display: "flex", alignItems: "center", gap: 10, padding: "10px 12px", background: "#FAFAF8", borderBottom: "1px solid #E5E2D8" },
  evidenceNum: { width: 22, height: 22, borderRadius: "50%", background: "#1F1F1F", color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700, flexShrink: 0 },
  miniLabel: { fontSize: 10, color: "#687388", textTransform: "uppercase", letterSpacing: "0.04em", marginBottom: 3 },
  miniVal: { fontSize: 12, color: "#1F1F1F", fontWeight: 600 },
  llmBox: { background: "#F3F0EA", borderRadius: 6, padding: "8px 10px", fontSize: 11, color: "#1F1F1F", lineHeight: 1.5 },
};

Object.assign(window, { AlertDetail });
