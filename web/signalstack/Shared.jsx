// Shared UI primitives

function Badge({ label, variant = "default", size = "sm" }) {
  const colors = {
    bullish: { bg: "#DCFCE7", color: "#16A34A", border: "#BBF7D0" },
    bearish: { bg: "#FEE2E2", color: "#DC2626", border: "#FECACA" },
    watch: { bg: "#FEF3C7", color: "#D97706", border: "#FDE68A" },
    sent: { bg: "#DCFCE7", color: "#16A34A", border: "#BBF7D0" },
    rejected: { bg: "#F3F4F6", color: "#687388", border: "#E5E7EB" },
    "tier-1": { bg: "#EFF6FF", color: "#2563EB", border: "#BFDBFE" },
    "tier-2": { bg: "#F5F3FF", color: "#7C3AED", border: "#DDD6FE" },
    healthy: { bg: "#DCFCE7", color: "#16A34A", border: "#BBF7D0" },
    degraded: { bg: "#FEF3C7", color: "#D97706", border: "#FDE68A" },
    error: { bg: "#FEE2E2", color: "#DC2626", border: "#FECACA" },
    inactive: { bg: "#F3F4F6", color: "#687388", border: "#E5E7EB" },
    "grade-a": { bg: "#DCFCE7", color: "#16A34A", border: "#BBF7D0" },
    "grade-b": { bg: "#EFF6FF", color: "#2563EB", border: "#BFDBFE" },
    "grade-b-": { bg: "#FEF3C7", color: "#D97706", border: "#FDE68A" },
    "grade-c": { bg: "#FEE2E2", color: "#DC2626", border: "#FECACA" },
    open: { bg: "#EFF6FF", color: "#2563EB", border: "#BFDBFE" },
    closed: { bg: "#F3F4F6", color: "#687388", border: "#E5E7EB" },
    promoted: { bg: "#DCFCE7", color: "#16A34A", border: "#BBF7D0" },
    default: { bg: "#F3F4F6", color: "#687388", border: "#E5E7EB" },
    positive: { bg: "#DCFCE7", color: "#16A34A", border: "#BBF7D0" },
    negative: { bg: "#FEE2E2", color: "#DC2626", border: "#FECACA" },
    info: { bg: "#EFF6FF", color: "#2563EB", border: "#BFDBFE" },
    amber: { bg: "#FEF3C7", color: "#D97706", border: "#FDE68A" },
    paper: { bg: "#FEF3C7", color: "#D97706", border: "#FDE68A" },
  };
  const c = colors[variant] || colors.default;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center",
      padding: size === "sm" ? "1px 7px" : "3px 10px",
      borderRadius: 4,
      fontSize: size === "sm" ? 11 : 12,
      fontWeight: 600,
      background: c.bg,
      color: c.color,
      border: `1px solid ${c.border}`,
      whiteSpace: "nowrap",
      lineHeight: 1.6,
      letterSpacing: "0.01em",
    }}>
      {label}
    </span>
  );
}

function GradeBadge({ grade }) {
  const map = { A: "grade-a", B: "grade-b", "B-": "grade-b-", C: "grade-c" };
  return <Badge label={grade} variant={map[grade] || "default"} size="sm" />;
}

function DirectionBadge({ dir }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 12, color: dir === "bullish" ? "#16A34A" : "#DC2626", fontWeight: 600 }}>
      <span style={{ fontSize: 13 }}>{dir === "bullish" ? "↑" : "↓"}</span>
      {dir}
    </span>
  );
}

function StatusDot({ status }) {
  const colors = { healthy: "#16A34A", degraded: "#D97706", error: "#DC2626", inactive: "#C8C4BC" };
  return <span style={{ width: 7, height: 7, borderRadius: "50%", background: colors[status] || "#C8C4BC", display: "inline-block", flexShrink: 0 }} />;
}

function KpiCard({ label, value, sub, valueColor, info }) {
  return (
    <div style={sharedStyles.kpiCard}>
      <div style={sharedStyles.kpiLabel}>{label}{info && <span style={{ color: "#C8C4BC", marginLeft: 4, fontSize: 10 }}>ⓘ</span>}</div>
      <div style={{ ...sharedStyles.kpiValue, color: valueColor || "#1F1F1F" }}>{value}</div>
      {sub && <div style={sharedStyles.kpiSub}>{sub}</div>}
    </div>
  );
}

function SectionLabel({ children }) {
  return <div style={sharedStyles.sectionLabel}>{children}</div>;
}

function Card({ children, style }) {
  return <div style={{ ...sharedStyles.card, ...style }}>{children}</div>;
}

function Table({ cols, rows, onRowClick, selectedId }) {
  return (
    <table style={sharedStyles.table}>
      <thead>
        <tr>
          {cols.map(c => (
            <th key={c.key} style={{ ...sharedStyles.th, textAlign: c.align || "left", width: c.width }}>
              {c.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, i) => (
          <tr
            key={row.id || i}
            onClick={() => onRowClick && onRowClick(row)}
            style={{
              ...sharedStyles.tr,
              background: selectedId && selectedId === (row.id || i) ? "#F0F7FF" : i % 2 === 0 ? "#fff" : "#FAFAF8",
              cursor: onRowClick ? "pointer" : "default",
              borderLeft: selectedId && selectedId === (row.id || i) ? "3px solid #2563EB" : "3px solid transparent",
            }}
          >
            {cols.map(c => (
              <td key={c.key} style={{ ...sharedStyles.td, textAlign: c.align || "left" }}>
                {row[c.key]}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// Mini bar chart using SVG
function MiniBarChart({ data, width = 320, height = 80 }) {
  const pnls = data.map(d => d.pnl);
  const counts = data.map(d => d.alerts);
  const maxAbs = Math.max(...pnls.map(Math.abs), 1);
  const maxCount = Math.max(...counts, 1);
  const bw = width / data.length;
  const barW = bw * 0.45;
  const midY = height * 0.65;
  const chartH = midY * 0.9;

  return (
    <svg width={width} height={height} style={{ display: "block" }}>
      {data.map((d, i) => {
        const x = i * bw + bw * 0.1;
        const barH = Math.abs(d.pnl) / maxAbs * chartH;
        const y = d.pnl >= 0 ? midY - barH : midY;
        const lineY = (1 - d.alerts / maxCount) * height * 0.8 + height * 0.05;
        return (
          <g key={i}>
            <rect x={x} y={y} width={barW} height={Math.max(barH, 1)}
              fill={d.pnl >= 0 ? "#16A34A" : "#DC2626"} rx={1.5} opacity={0.85} />
            {i > 0 && (
              <line
                x1={(i - 1) * bw + bw * 0.5 + barW * 0.25}
                y1={(1 - data[i - 1].alerts / maxCount) * height * 0.8 + height * 0.05}
                x2={x + barW * 0.25}
                y2={lineY}
                stroke="#1F1F1F" strokeWidth={1.2} opacity={0.5}
              />
            )}
            <circle cx={x + barW * 0.25} cy={lineY} r={2.5} fill="#1F1F1F" opacity={0.6} />
            <text x={x + barW * 0.25} y={height - 2} textAnchor="middle" fontSize={9} fill="#687388">
              {d.date.replace("Apr ", "")}
            </text>
          </g>
        );
      })}
      <line x1={0} y1={midY} x2={width} y2={midY} stroke="#E5E2D8" strokeWidth={0.8} />
    </svg>
  );
}

// Sparkline
function Sparkline({ values, width = 80, height = 28, color = "#16A34A" }) {
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const pts = values.map((v, i) => {
    const x = (i / (values.length - 1)) * width;
    const y = height - ((v - min) / range) * height * 0.85 - height * 0.075;
    return `${x},${y}`;
  }).join(" ");
  return (
    <svg width={width} height={height}>
      <polyline points={pts} fill="none" stroke={color} strokeWidth={1.5} />
    </svg>
  );
}

const sharedStyles = {
  kpiCard: {
    background: "#fff",
    border: "1px solid #E5E2D8",
    borderRadius: 8,
    padding: "14px 18px",
    minWidth: 120,
    flex: 1,
  },
  kpiLabel: { fontSize: 11, color: "#687388", fontWeight: 600, letterSpacing: "0.03em", textTransform: "uppercase", marginBottom: 6, display: "flex", alignItems: "center" },
  kpiValue: { fontSize: 26, fontWeight: 700, color: "#1F1F1F", letterSpacing: "-0.02em", lineHeight: 1.1 },
  kpiSub: { fontSize: 11, color: "#687388", marginTop: 2 },
  sectionLabel: { fontSize: 11, fontWeight: 700, color: "#687388", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 12 },
  card: { background: "#fff", border: "1px solid #E5E2D8", borderRadius: 8, overflow: "hidden" },
  table: { width: "100%", borderCollapse: "collapse", fontSize: 12 },
  th: { padding: "8px 12px", fontWeight: 600, color: "#687388", fontSize: 11, letterSpacing: "0.04em", textTransform: "uppercase", borderBottom: "1px solid #E5E2D8", background: "#FAFAF8", whiteSpace: "nowrap" },
  tr: { transition: "background 0.1s" },
  td: { padding: "9px 12px", color: "#1F1F1F", borderBottom: "1px solid #F3F0EA", verticalAlign: "middle" },
};

Object.assign(window, { Badge, GradeBadge, DirectionBadge, StatusDot, KpiCard, SectionLabel, Card, Table, MiniBarChart, Sparkline, sharedStyles });
