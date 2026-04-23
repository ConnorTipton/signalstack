// SignalStack V1 — API client
// Maps real backend field names → frontend display shape.

const SS_API_BASE = "http://localhost:8000";

// ─── Field mappers ────────────────────────────────────────────────────────────

function mapAlert(a) {
  const sentAt = a.sent_at ? new Date(a.sent_at) : null;
  const timeStr = sentAt
    ? sentAt.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false }) + " ET"
    : "—";

  const contractDisplay = a.contract_symbol ||
    (a.ticker && a.expiration_date && a.strike && a.option_type
      ? `${a.ticker} ${a.expiration_date} ${a.strike}${a.option_type === "call" ? "C" : "P"}`
      : "—");

  const ev = a.evidence || {};

  // Scoring — weights are fixed in V1 spec
  const scoring = ev.news_score != null ? {
    news:          { score: ev.news_score,           weight: 30, weighted: +(ev.news_score * 0.3).toFixed(2) },
    price:         { score: ev.price_score,          weight: 25, weighted: +(ev.price_score * 0.25).toFixed(2) },
    options:       { score: ev.options_score,        weight: 25, weighted: +(ev.options_score * 0.25).toFixed(2) },
    liquidity:     { score: ev.liquidity_score,      weight: 10, weighted: +(ev.liquidity_score * 0.1).toFixed(2) },
    dataConfidence:{ score: ev.data_confidence_score,weight: 10, weighted: +(ev.data_confidence_score * 0.1).toFixed(2) },
    total: parseFloat(a.score),
  } : null;

  // Spread display
  const spreadDisplay = ev.contract_spread_pct != null
    ? `${(ev.contract_spread_pct * 100).toFixed(0)}%`
    : "—";

  // Source tier from news evidence
  const sourceTier = ev.news_source_tier != null ? `Tier ${ev.news_source_tier}` : "Tier 1";

  return {
    id: String(a.id),
    ticker: a.ticker,
    direction: a.direction,
    score: parseFloat(a.score),
    grade: a.grade || "—",
    contract: contractDisplay,
    contract_symbol: a.contract_symbol,
    expiration_date: a.expiration_date,
    strike: a.strike ? parseFloat(a.strike) : null,
    option_type: a.option_type,
    sourceTier,
    spread: spreadDisplay,
    status: sentAt ? "Sent" : "Watch",
    sentAtISO: a.sent_at || null,
    createdAtISO: a.created_at || null,
    time: timeStr,
    dryRun: a.dry_run,
    telegram: !!a.sent_at,
    dataCaveat: a.data_note || null,
    providerConfidence: ev.provider_confidence || 0.90,

    plan: {
      entry:       a.entry_condition || "—",
      invalidation:a.invalidation    || "—",
      target1:     a.target1         || "—",
      target2:     a.target2         || "—",
      timeStop:    a.time_stop       || "—",
    },

    // News evidence
    news: ev.news_summary ? {
      summary:    ev.news_summary,
      source:     sourceTier === "Tier 1" ? "EDGAR" : "Marketaux",
      wire:       "Wire",
      eventType:  ev.news_event_type  || "—",
      polarity:   ev.news_polarity    ? ev.news_polarity.charAt(0).toUpperCase() + ev.news_polarity.slice(1) : "—",
      confidence: ev.news_confidence  || 0,
      importance: ev.news_importance != null ? (ev.news_importance > 0.7 ? "High" : ev.news_importance > 0.4 ? "Medium" : "Low") : "—",
      llmSummary: ev.news_summary,
    } : null,

    // Price evidence
    price: ev.price_pattern ? {
      pattern:      ev.price_pattern  || "—",
      triggerPrice: null,
      confirmation: ev.price_polarity || "—",
      confidence:   ev.price_confidence || 0,
    } : null,

    // Options evidence
    options: ev.options_signal ? {
      signal:           ev.options_signal            || "—",
      providerMode:     "full",
      relativeActivity: ev.options_relative_activity || "—",
      confidence:       ev.options_confidence        || 0,
    } : null,

    scoring,

    contract_detail: {
      symbol:   contractDisplay,
      bid:      ev.contract_bid   != null ? parseFloat(ev.contract_bid)   : null,
      ask:      ev.contract_ask   != null ? parseFloat(ev.contract_ask)   : null,
      mid:      ev.contract_bid != null && ev.contract_ask != null
                  ? +((parseFloat(ev.contract_bid) + parseFloat(ev.contract_ask)) / 2).toFixed(2)
                  : null,
      spread:   spreadDisplay,
      oi:       ev.contract_oi     || null,
      volume:   ev.contract_volume || null,
      expiration: a.expiration_date,
      strike:   a.strike ? parseFloat(a.strike) : null,
      type:     a.option_type ? (a.option_type.charAt(0).toUpperCase() + a.option_type.slice(1)) : null,
    },

    execution: {
      orderStatus: "—",
      fillPrice:   null,
      position:    "—",
      exitPrice:   null,
      realizedPnl: null,
      entryTime:   null,
      exitTime:    null,
      duration:    null,
      tradeability:false,
    },

    contractRejected: Array.isArray(ev.contract_rejection_json)
      ? ev.contract_rejection_json.map(r => ({
          symbol: r.symbol || r.contract_symbol || "—",
          reason: r.reason || r.rejection_reason || "—",
        }))
      : [],
  };
}

function mapPosition(p) {
  return {
    id: String(p.id),
    ticker: p.ticker,
    symbol: p.contract_symbol,
    type: p.option_type === "call" ? "Call" : "Put",
    strike: parseFloat(p.strike),
    expiration: p.expiration_date,
    qty: p.quantity,
    entryPrice: parseFloat(p.entry_price),
    exitPrice: p.exit_price ? parseFloat(p.exit_price) : null,
    status: p.status === "open" ? "Open" : "Closed",
    exitReason: p.exit_reason || null,
    openedAt: p.opened_at ? new Date(p.opened_at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }) + " ET" : "—",
    closedAt: p.closed_at ? new Date(p.closed_at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }) + " ET" : null,
    pnl: p.pnl ? parseFloat(p.pnl) : null,
    pnlPct: p.pnl_pct ? parseFloat(p.pnl_pct) : null,
  };
}

function mapPerformanceDay(d) {
  return {
    date: d.metric_date,
    pnl: d.total_pnl ? parseFloat(d.total_pnl) : 0,
    alerts: d.total_alerts || 0,
    wins: d.winning_positions || 0,
    losses: d.losing_positions || 0,
    avgScore: d.avg_score ? parseFloat(d.avg_score) : 0,
    grades: d.alerts_by_grade || {},
  };
}

function fmtAgo(iso) {
  if (!iso) return null;
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 0) return "just now";
  if (diff < 60) return `${Math.round(diff)}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  return `${Math.round(diff / 3600)}h ago`;
}

function mapProvider(p) {
  return {
    name: p.provider_name,
    type: inferProviderType(p.provider_name),
    status: p.is_healthy ? "healthy" : (p.consecutive_failures > 5 ? "error" : "degraded"),
    confidence: p.provider_confidence != null ? parseFloat(p.provider_confidence) : 0,
    lastSuccess: fmtAgo(p.last_success_at) || "never",
    lastSuccessISO: p.last_success_at || null,
    checkedAtISO: p.checked_at || null,
    lagSeconds: p.lag_seconds != null ? Math.round(p.lag_seconds) : null,
    consecutiveFailures: p.consecutive_failures || 0,
    latestError: p.error_message || null,
    mode: inferProviderMode(p.provider_name),
    priority: inferProviderPriority(p.provider_name),
  };
}

function inferProviderType(name) {
  const n = name.toLowerCase();
  if (n.includes("tradier") || n.includes("alpaca")) return "Market Data";
  if (n.includes("edgar") || n.includes("marketaux") || n.includes("rss") || n.includes("businesswire")) return "News";
  if (n.includes("anthropic") || n.includes("llm") || n.includes("claude")) return "LLM Labeler";
  if (n.includes("telegram")) return "Delivery";
  return "Other";
}

function inferProviderMode(name) {
  const n = name.toLowerCase();
  if (n.includes("tradier")) return "Primary";
  if (n.includes("alpaca")) return "Fallback";
  if (n.includes("edgar")) return "Primary (SEC filings)";
  if (n.includes("marketaux")) return "Tier 2 supplement";
  if (n.includes("rss")) return "Supplement";
  if (n.includes("telegram")) return "Bot delivery";
  if (n.includes("anthropic") || n.includes("llm")) return "Cloud (claude-haiku)";
  return "—";
}

function inferProviderPriority(name) {
  const n = name.toLowerCase();
  if (n.includes("tradier") || n.includes("edgar") || n.includes("telegram") || n.includes("anthropic") || n.includes("llm")) return 1;
  if (n.includes("alpaca") || n.includes("marketaux")) return 2;
  return 3;
}

function mapReplay(r) {
  return {
    kpis: {
      newsArticles: r.total_news_articles,
      detectedEvents: r.total_detected_events,
      signalCandidates: r.total_signal_candidates,
      alertsSent: r.total_alerts_sent,
      positionsOpened: r.total_positions_opened,
      positionsClosed: r.total_positions_closed,
      realizedPnl: parseFloat(r.realized_pnl) || 0,
      winRate: r.win_rate != null ? parseFloat(r.win_rate) * 100 : 0,
    },
    events: (r.timeline || []).map(ev => ({
      time: new Date(ev.event_time).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false }),
      type: ev.event_kind,
      ticker: ev.ticker || "—",
      sourceDetector: [ev.source_tier ? `Tier ${ev.source_tier}` : null, ev.source_name].filter(Boolean).join(" · ") || "—",
      detail: ev.details?.summary || ev.details?.pattern || ev.details?.signal || "—",
      outcome: ev.details?.outcome || null,
    })),
    detectors: (r.detector_postmortems || []).map(d => ({
      id: d.detector,
      name: d.detector,
      type: d.detector.toLowerCase().includes("news") ? "News" : d.detector.toLowerCase().includes("price") ? "Price" : "Options",
      totalEvents: d.total_events,
      ledToSignal: d.events_that_led_to_signal,
      ledToAlert: d.events_that_led_to_alert,
      notes: "—",
    })),
    sourceTrace: (r.provider_traces || []).map(t => ({
      articleId: t.article_id,
      provider: t.provider_name,
      providerStatus: "healthy",
      sourceTier: t.source_tier != null ? `Tier ${t.source_tier}` : "n/a",
      rawTable: t.raw_table || "—",
      rawEventId: t.provider_event_id || (t.raw_event_id ? String(t.raw_event_id) : "—"),
      receivedAt: t.received_at ? new Date(t.received_at).toISOString().replace("T", " ").slice(0, 19) : "—",
    })),
  };
}

// ─── Fetch helpers ────────────────────────────────────────────────────────────

async function apiFetch(path, params = {}) {
  const url = new URL(SS_API_BASE + path);
  Object.entries(params).forEach(([k, v]) => {
    if (Array.isArray(v)) v.forEach(val => url.searchParams.append(k, val));
    else if (v != null) url.searchParams.set(k, v);
  });
  const res = await fetch(url.toString());
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

const SS_API = {
  async alerts(params = {}) {
    const data = await apiFetch("/api/v1/alerts", { sent_only: false, limit: 100, ...params });
    return data.map(mapAlert);
  },
  async alertById(id) {
    const data = await apiFetch(`/api/v1/alerts/${id}`);
    return mapAlert(data);
  },
  async positions(status = "open") {
    const data = await apiFetch("/api/v1/positions", { status, limit: 200 });
    return data.map(mapPosition);
  },
  async performance(days = 30) {
    const data = await apiFetch("/api/v1/performance", { days });
    return data.map(mapPerformanceDay).reverse(); // oldest first for charts
  },
  async providers() {
    const data = await apiFetch("/api/v1/providers/health");
    return data.map(mapProvider);
  },
  async health() {
    return apiFetch("/health");
  },
  async replay(params = {}) {
    const data = await apiFetch("/api/v1/replay", params);
    return mapReplay(data);
  },
  async settings() {
    const data = await apiFetch("/api/v1/settings");
    return data.rows;
  },
  async sourceTrace(limit = 50) {
    const data = await apiFetch("/api/v1/source-trace", { limit });
    return data.map(r => ({
      articleId: String(r.article_id),
      provider: r.provider_name,
      providerStatus: "healthy",
      sourceTier: r.source_tier != null ? `Tier ${r.source_tier}` : "n/a",
      rawTable: r.raw_table,
      rawEventId: r.raw_event_id || "—",
      receivedAt: r.received_at ? new Date(r.received_at).toISOString().replace("T", " ").slice(0, 19) : "—",
      title: r.title,
    }));
  },
  async underlyingBars(ticker, minutes = 60) {
    const data = await apiFetch(`/api/v1/underlying/${ticker}/bars`, { minutes });
    return data.map(b => ({
      time: new Date(b.bar_time),
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
      volume: b.volume,
      vwap: b.vwap,
    }));
  },
};

// ─── React hook: useAPI ───────────────────────────────────────────────────────
// Usage: const { data, loading, error, live } = useAPI(() => SS_API.alerts(), fallbackData)

function useAPI(fetcher, fallback, deps = []) {
  const [state, setState] = React.useState({ data: fallback, loading: true, error: null, live: false });

  React.useEffect(() => {
    let cancelled = false;
    setState(s => ({ ...s, loading: true }));
    fetcher()
      .then(data => {
        if (!cancelled) setState({ data, loading: false, error: null, live: true });
      })
      .catch(err => {
        if (!cancelled) setState({ data: fallback, loading: false, error: err.message, live: false });
      });
    return () => { cancelled = true; };
  }, deps);

  return state;
}

// ─── Auto-refresh hook ────────────────────────────────────────────────────────

function useAutoRefresh(fetcher, fallback, intervalMs = 30000) {
  const [tick, setTick] = React.useState(0);
  React.useEffect(() => {
    const t = setInterval(() => setTick(n => n + 1), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs]);
  return useAPI(fetcher, fallback, [tick]);
}

Object.assign(window, { SS_API, useAPI, useAutoRefresh, fmtAgo });
