// Shared building blocks for the admin Insights pages: period picker, stat
// strip, sparkline / line / stacked-bar charts and the hover tooltip.
import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
  type RefObject,
  type ReactNode,
} from "react";

export type Api = <T>(path: string, init?: RequestInit) => Promise<T>;

/* ---------------------------------------------------------------- period */

export type RangeMode = "1" | "7" | "30" | "custom";
export type Range = { mode: RangeMode; from: string; to: string };

export function browserZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

// YYYY-MM-DD for `daysAgo` local days before today.
export function isoDay(daysAgo = 0): string {
  const at = new Date();
  at.setDate(at.getDate() - daysAgo);
  return at.toLocaleDateString("en-CA");
}

export function defaultRange(mode: RangeMode = "1"): Range {
  return { mode, from: isoDay(29), to: isoDay(0) };
}

export function rangeQuery(range: Range, zone: string): URLSearchParams {
  const params = new URLSearchParams({ tz: zone });
  if (range.mode === "custom") {
    params.set("since", range.from);
    params.set("until", range.to);
  } else {
    params.set("days", range.mode);
  }
  return params;
}

export function rangeValid(range: Range): boolean {
  return range.mode !== "custom" || Boolean(range.from && range.to && range.from <= range.to);
}

// "vs yesterday" / "vs prev 7d" for delta captions.
export function prevLabel(days: number): string {
  return days === 1 ? "vs yesterday" : `vs prev ${days}d`;
}

export function RangePicker({
  range,
  onChange,
  minDate,
  compact = false,
}: {
  range: Range;
  onChange: (next: Range) => void;
  minDate?: string;
  compact?: boolean;
}) {
  const bad = !rangeValid(range);
  return (
    <div className={`kit-range ${compact ? "is-compact" : ""}`}>
      <div className="kit-seg" role="group" aria-label="Period">
        {(["1", "7", "30", "custom"] as RangeMode[]).map((mode) => (
          <button
            key={mode}
            type="button"
            className={range.mode === mode ? "is-on" : ""}
            onClick={() => onChange({ ...range, mode })}
          >
            {mode === "1" ? "Today" : mode === "custom" ? "Custom" : compact ? `${mode}d` : `${mode} days`}
          </button>
        ))}
      </div>
      {range.mode === "custom" ? (
        <div className={`kit-dates ${bad ? "is-bad" : ""}`}>
          <label>
            From
            <input
              type="date"
              value={range.from}
              min={minDate}
              max={isoDay(0)}
              onChange={(event) => onChange({ ...range, from: event.target.value })}
            />
          </label>
          <label>
            To
            <input
              type="date"
              value={range.to}
              min={minDate}
              max={isoDay(0)}
              onChange={(event) => onChange({ ...range, to: event.target.value })}
            />
          </label>
        </div>
      ) : null}
    </div>
  );
}

/* ---------------------------------------------------------------- format */

export function pct(rate: number | null | undefined): string {
  return rate == null || Number.isNaN(rate) ? "–" : `${Math.round(rate * 100)}%`;
}

export function pct1(rate: number | null | undefined): string {
  return rate == null || Number.isNaN(rate) ? "–" : `${(rate * 100).toFixed(1)}%`;
}

export function fmtInt(n: number | null | undefined): string {
  return n == null ? "–" : n.toLocaleString("en-GB");
}

export function fmtDur(seconds: number | null | undefined): string {
  if (seconds == null) return "–";
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
  return `${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}m`;
}

function dayDate(iso: string): Date {
  return new Date(`${iso}T12:00:00`);
}

export function fmtDay(iso: string): string {
  return dayDate(iso).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
}

export function fmtShort(iso: string): string {
  return dayDate(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

export function fmtWindow(win: { first: string; last: string; days: number } | null | undefined): string {
  if (!win) return "";
  if (win.days === 1) return fmtDay(win.first);
  return `${fmtShort(win.first)} – ${fmtShort(win.last)} · ${win.days} days`;
}

// 90% Wilson interval: the honest "likely range" for a hit rate on n alerts.
export function wilson(k: number, n: number, z = 1.645): [number, number] {
  if (!n) return [0, 0];
  const p = k / n;
  const z2 = z * z;
  const den = 1 + z2 / n;
  const centre = (p + z2 / (2 * n)) / den;
  const half = (z * Math.sqrt((p * (1 - p)) / n + z2 / (4 * n * n))) / den;
  return [Math.max(0, centre - half), Math.min(1, centre + half)];
}

export function median(values: number[]): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = sorted.length >> 1;
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

/* ---------------------------------------------------------------- colour */

function hexRgb(hex: string): number[] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function mix(a: string, b: string, t: number): string {
  const A = hexRgb(a);
  const B = hexRgb(b);
  return `rgb(${A.map((v, i) => Math.round(v + (B[i] - v) * t)).join(",")})`;
}

// Better than average -> blue, worse -> orange, about average -> neutral grey.
export function diverging(lift: number, span = 0.2): string {
  const t = Math.max(-1, Math.min(1, lift / span));
  return t >= 0 ? mix("#2a3340", "#3987e5", t) : mix("#2a3340", "#d95926", -t);
}

export function sequential(t: number): string {
  if (t <= 0) return "#101b28";
  return t < 0.5 ? mix("#14263b", "#1c5cab", t * 2) : mix("#1c5cab", "#86b6ef", (t - 0.5) * 2);
}

export function inkFor(rgb: string): string {
  const m = rgb.match(/\d+/g);
  if (!m) return "var(--text)";
  const [r, g, b] = m.map(Number);
  return 0.299 * r + 0.587 * g + 0.114 * b > 150 ? "#08131d" : "var(--text)";
}

/* ---------------------------------------------------------------- tooltip */

export type TipRow = [string, string];

let tipEl: HTMLDivElement | null = null;

function tipNode(): HTMLDivElement {
  if (!tipEl) {
    tipEl = document.createElement("div");
    tipEl.className = "kit-tip";
    document.body.appendChild(tipEl);
  }
  return tipEl;
}

export function showTip(title: string, rows: TipRow[], x: number, y: number) {
  const el = tipNode();
  el.replaceChildren();
  const head = document.createElement("div");
  head.className = "kit-tip-title";
  head.textContent = title;
  el.appendChild(head);
  for (const [label, value] of rows) {
    const row = document.createElement("div");
    row.className = "kit-tip-row";
    const a = document.createElement("span");
    a.textContent = label;
    const b = document.createElement("b");
    b.textContent = value;
    row.append(a, b);
    el.appendChild(row);
  }
  el.classList.add("is-on");
  const box = el.getBoundingClientRect();
  let left = x + 14;
  let top = y + 14;
  if (left + box.width > window.innerWidth - 8) left = x - box.width - 14;
  if (top + box.height > window.innerHeight - 8) top = y - box.height - 14;
  el.style.left = `${Math.max(4, left)}px`;
  el.style.top = `${Math.max(4, top)}px`;
}

export function hideTip() {
  tipEl?.classList.remove("is-on");
}

export function tip(title: string, rows: TipRow[]) {
  return {
    onMouseMove: (event: ReactMouseEvent) => showTip(title, rows, event.clientX, event.clientY),
    onMouseLeave: hideTip,
  };
}

/* ---------------------------------------------------------------- deltas */

export function Delta({
  cur,
  prev,
  pts = false,
  invert = false,
  label = "",
}: {
  cur: number | null | undefined;
  prev: number | null | undefined;
  pts?: boolean;
  invert?: boolean;
  label?: string;
}) {
  if (cur == null || prev == null || (!pts && prev === 0)) {
    return <span className="kit-delta">no prior data</span>;
  }
  const diff = pts ? (cur - prev) * 100 : ((cur - prev) / prev) * 100;
  const up = diff > 0.5;
  const down = diff < -0.5;
  const good = invert ? down : up;
  const bad = invert ? up : down;
  const text = pts
    ? `${diff > 0 ? "+" : ""}${diff.toFixed(1)} pts`
    : `${diff > 0 ? "+" : ""}${Math.round(diff)}%`;
  return (
    <span className={`kit-delta ${good ? "is-up" : bad ? "is-down" : ""}`}>
      {up ? "▲" : down ? "▼" : "•"} {text}
      {label ? <em>{label}</em> : null}
    </span>
  );
}

/* ---------------------------------------------------------------- stat strip */

export type Stat = {
  label: string;
  value: ReactNode;
  foot?: ReactNode;
  spark?: (number | null)[];
  hero?: boolean;
  tipTitle?: string;
  tipRows?: TipRow[];
};

// Open row of numbers with hairline dividers. Fits as many per row as the
// width allows, then evens the rows out (6 -> 3 + 3, never 5 + 1).
export function StatStrip({ stats, minWidth = 150 }: { stats: Stat[]; minWidth?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [cols, setCols] = useState(stats.length);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const fit = () => {
      const perRow = Math.max(1, Math.floor(el.clientWidth / minWidth));
      const rows = Math.ceil(stats.length / perRow);
      setCols(Math.ceil(stats.length / rows));
    };
    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(el);
    return () => observer.disconnect();
  }, [stats.length, minWidth]);
  return (
    <div ref={ref} className="kit-strip" style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}>
      {stats.map((stat) => (
        <div
          key={stat.label}
          className={`kit-stat ${stat.hero ? "is-hero" : ""}`}
          {...(stat.tipRows ? tip(stat.tipTitle || stat.label, stat.tipRows) : {})}
        >
          <div className="kit-stat-label">{stat.label}</div>
          <div className="kit-stat-value">{stat.value}</div>
          <div className="kit-stat-foot">
            {stat.foot}
            {stat.spark ? <Sparkline values={stat.spark} /> : null}
          </div>
        </div>
      ))}
    </div>
  );
}

/* ---------------------------------------------------------------- charts */

export function Sparkline({
  values,
  width = 92,
  height = 26,
}: {
  values: (number | null)[];
  width?: number;
  height?: number;
}) {
  const pts = values
    .map((v, i) => [i, v] as const)
    .filter((p): p is readonly [number, number] => p[1] != null && !Number.isNaN(p[1]));
  if (pts.length < 2) return <svg width={width} height={height} aria-hidden="true" />;
  const ys = pts.map(([, v]) => v);
  const lo = Math.min(...ys);
  const span = Math.max(...ys) - lo || 1;
  const X = (i: number) => 2 + (i / Math.max(1, values.length - 1)) * (width - 6);
  const Y = (v: number) => height - 3 - ((v - lo) / span) * (height - 6);
  const d = pts.map(([i, v], k) => `${k ? "L" : "M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join("");
  const [li, lv] = pts[pts.length - 1];
  return (
    <svg width={width} height={height} aria-hidden="true" className="kit-spark">
      <path d={d} fill="none" stroke="var(--accent)" strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={X(li)} cy={Y(lv)} r="2.6" fill="var(--accent)" />
    </svg>
  );
}

function useWidth<T extends HTMLElement>(): [RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(600);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setWidth(Math.max(280, el.clientWidth)));
    observer.observe(el);
    setWidth(Math.max(280, el.clientWidth));
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

const M = { t: 10, r: 10, b: 24, l: 38 };

function labelStep(count: number, innerWidth: number, minGap: number): number {
  return Math.ceil(count / Math.max(2, Math.floor(innerWidth / minGap)));
}

function showLabel(i: number, count: number, every: number): boolean {
  return i === count - 1 || (i % every === 0 && count - 1 - i >= every * 0.6);
}

export type LinePoint = { label: string; title: string; value: number | null; rows: TipRow[] };

export function LineChart({
  points,
  baseline,
  height = 230,
  ariaLabel,
}: {
  points: LinePoint[];
  baseline?: number | null;
  height?: number;
  ariaLabel: string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const iw = width - M.l - M.r;
  const ih = height - M.t - M.b;
  const X = (i: number) => M.l + (points.length <= 1 ? iw / 2 : (i / (points.length - 1)) * iw);
  const Y = (v: number) => M.t + ih - v * ih;
  const every = labelStep(points.length, iw, 70);
  let d = "";
  let on = false;
  points.forEach((p, i) => {
    if (p.value == null) {
      on = false;
      return;
    }
    d += `${on ? "L" : "M"}${X(i).toFixed(1)},${Y(p.value).toFixed(1)}`;
    on = true;
  });
  const hp = hover != null ? points[hover] : null;
  return (
    <div ref={ref} className="kit-chart">
      <svg width={width} height={height} role="img" aria-label={ariaLabel}>
        {[0, 0.25, 0.5, 0.75, 1].map((g) => (
          <g key={g}>
            <line x1={M.l} x2={width - M.r} y1={Y(g)} y2={Y(g)} stroke="var(--grid)" />
            <text x={M.l - 8} y={Y(g) + 3.5} textAnchor="end">
              {g * 100}%
            </text>
          </g>
        ))}
        {points.map((p, i) =>
          showLabel(i, points.length, every) ? (
            <text key={p.title} x={X(i)} y={height - 6} textAnchor="middle">
              {p.label}
            </text>
          ) : null,
        )}
        {baseline != null ? (
          <line x1={M.l} x2={width - M.r} y1={Y(baseline)} y2={Y(baseline)} stroke="var(--muted)" strokeDasharray="4 4" />
        ) : null}
        <path d={d} fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        {points.length <= 31
          ? points.map((p, i) =>
              p.value != null ? (
                <circle
                  key={p.title}
                  cx={X(i)}
                  cy={Y(p.value)}
                  r={points.length > 14 ? 2.2 : 3.2}
                  fill="var(--accent)"
                  stroke="var(--surface)"
                  strokeWidth="2"
                />
              ) : null,
            )
          : null}
        {hp && hover != null ? (
          <g>
            <line x1={X(hover)} x2={X(hover)} y1={M.t} y2={M.t + ih} stroke="var(--border-2)" />
            {hp.value != null ? (
              <circle cx={X(hover)} cy={Y(hp.value)} r="5" fill="var(--accent)" stroke="var(--surface)" strokeWidth="2" />
            ) : null}
          </g>
        ) : null}
        <rect
          x={M.l}
          y={M.t}
          width={iw}
          height={ih}
          fill="transparent"
          onMouseMove={(event) => {
            const box = (event.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect();
            const i = Math.round(((event.clientX - box.left - M.l) / iw) * (points.length - 1));
            const idx = Math.max(0, Math.min(points.length - 1, i));
            setHover(idx);
            showTip(points[idx].title, points[idx].rows, event.clientX, event.clientY);
          }}
          onMouseLeave={() => {
            setHover(null);
            hideTip();
          }}
        />
      </svg>
    </div>
  );
}

export type BarColumn = { label: string; title: string; a: number; b: number; dim?: boolean; rows: TipRow[] };

function roundTop(x: number, y: number, w: number, h: number, r: number): string {
  const rr = Math.min(r, w / 2, h);
  return `M${x},${y + h}V${y + rr}Q${x},${y} ${x + rr},${y}H${x + w - rr}Q${x + w},${y} ${x + w},${y + rr}V${y + h}Z`;
}

// Two-series stacked bars: `a` (blue) at the base, `b` (orange, or `topColor`) on top.
export function StackedBars({
  columns,
  height = 240,
  labelEvery,
  ariaLabel,
  topColor = "var(--s2)",
}: {
  columns: BarColumn[];
  height?: number;
  labelEvery?: number;
  ariaLabel: string;
  topColor?: string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const iw = width - M.l - M.r;
  const ih = height - M.t - M.b;
  const max = Math.max(1, ...columns.map((c) => c.a + c.b));
  const step = max <= 10 ? 2 : max <= 50 ? 10 : max <= 200 ? 20 : 100;
  const top = Math.ceil(max / step) * step;
  const bw = iw / Math.max(1, columns.length);
  const gap = Math.min(10, bw * 0.28);
  const barW = bw - gap;
  const every = labelEvery || labelStep(columns.length, iw, 56);
  const H = (v: number) => (v / top) * ih;
  const base = M.t + ih;
  return (
    <div ref={ref} className="kit-chart">
      <svg width={width} height={height} role="img" aria-label={ariaLabel}>
        {[0, 0.25, 0.5, 0.75, 1].map((g) => (
          <g key={g}>
            <line x1={M.l} x2={width - M.r} y1={base - g * ih} y2={base - g * ih} stroke="var(--grid)" />
            <text x={M.l - 8} y={base - g * ih + 3.5} textAnchor="end">
              {Math.round(top * g)}
            </text>
          </g>
        ))}
        {columns.map((c, i) => {
          const x = M.l + i * bw + gap / 2;
          const ha = H(c.a);
          const hb = H(c.b);
          return (
            <g key={c.title} {...tip(c.title, c.rows)} opacity={c.dim ? 0.55 : 1}>
              <rect x={x - gap / 2} y={M.t} width={bw} height={ih} fill="transparent" />
              {c.a ? (
                <path
                  d={c.b ? `M${x},${base}V${base - ha}H${x + barW}V${base}Z` : roundTop(x, base - ha, barW, ha, 4)}
                  fill="var(--s1)"
                />
              ) : null}
              {c.b ? <path d={roundTop(x, base - ha - hb - (c.a ? 2 : 0), barW, hb, 4)} fill={topColor} /> : null}
              {showLabel(i, columns.length, every) ? (
                <text x={x + barW / 2} y={height - 6} textAnchor="middle">
                  {c.label}
                </text>
              ) : null}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

export function BarList({
  rows,
  total,
}: {
  rows: { label: ReactNode; key: string; value: number; muted?: boolean; tipRows?: TipRow[] }[];
  total: number;
}) {
  const max = Math.max(1, ...rows.map((row) => row.value));
  return (
    <div className="kit-bars">
      {rows.map((row) => (
        <div key={row.key} className="kit-bar-row" {...(row.tipRows ? tip(row.key, row.tipRows) : {})}>
          <span className="kit-bar-name">{row.label}</span>
          <span className="kit-bar-track">
            <span className="kit-bar-fill" style={{ width: `${(row.value / max) * 100}%`, opacity: row.muted ? 0.45 : 1 }} />
          </span>
          <span className="kit-num">{pct(total ? row.value / total : null)}</span>
        </div>
      ))}
    </div>
  );
}

export function Card({
  title,
  sub,
  right,
  children,
  className = "",
}: {
  title: ReactNode;
  sub?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <article className={`kit-card ${className}`}>
      <header className="kit-card-head">
        <h2>{title}</h2>
        {sub ? <span className="kit-sub">{sub}</span> : null}
        {right ? <div className="kit-card-right">{right}</div> : null}
      </header>
      <div className="kit-card-body">{children}</div>
    </article>
  );
}

export function Legend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <div className="kit-legend">
      {items.map((item) => (
        <span key={item.label}>
          <i style={{ background: item.color }} />
          {item.label}
        </span>
      ))}
    </div>
  );
}

export function OutcomePill({ state }: { state: string }) {
  if (state === "Confirmed")
    return (
      <span className="kit-pill is-ok">
        <i>✓</i>Hit
      </span>
    );
  if (state === "Expired")
    return (
      <span className="kit-pill is-miss">
        <i>✕</i>Miss
      </span>
    );
  return (
    <span className="kit-pill is-open">
      <i>●</i>Open
    </span>
  );
}
