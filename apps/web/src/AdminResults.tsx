import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { countryFlag } from "./App";
import {
  Card,
  Delta,
  LineChart,
  Legend,
  OutcomePill,
  Sparkline,
  StatStrip,
  diverging,
  fmtDay,
  fmtInt,
  fmtShort,
  fmtWindow,
  inkFor,
  isoDay,
  pct,
  pct1,
  prevLabel,
  rangeQuery,
  rangeValid,
  tip,
  wilson,
  type Api,
  type Range,
} from "./AdminKit";

type SidePair = { home?: number | null; away?: number | null };

type ResultFactors = {
  country?: string | null;
  sweet_spot?: boolean | null;
  half?: string | null;
  tslg?: string | null;
  odds_home?: number | null;
  odds_away?: number | null;
  trigger_odds?: number | null;
  d5?: SidePair;
  d10?: SidePair;
  phi?: SidePair;
  k?: SidePair;
  also_firing?: string[];
  score_state?: string | null;
  odds_bucket?: string | null;
  tslg_bucket?: string | null;
};

type ResultItem = {
  id: number;
  match_id: string;
  strategy: string;
  team: string | null;
  value: number;
  minute: number;
  score: string | null;
  home_team: string | null;
  away_team: string | null;
  league?: string | null;
  state: string;
  created_at: string | null;
  settle_score?: string | null;
  settle_minute?: number | null;
  live: boolean;
  factors?: ResultFactors;
};

export type AlertStats = {
  total: number;
  confirmed: number;
  expired: number;
  open: number;
  settled: number;
  hit_rate: number | null;
  median_to_goal: number | null;
};

type Win = { first: string; last: string; days: number };

type Slice = { dim: string; label: string; n: number; confirmed: number; hit_rate: number };

type MatrixRow = { strategy: string; cells: { confirmed: number; settled: number }[] };

export type StrategyRow = {
  strategy: string;
  current: AlertStats;
  previous: AlertStats;
  trend: (number | null)[];
  best_slice: Slice | null;
};

export type ResultsInsights = {
  window: Win;
  previous_window: Win;
  chart_window: Win;
  summary: AlertStats;
  previous: AlertStats;
  daily: { date: string; total: number; confirmed: number; settled: number; hit_rate: number | null }[];
  by_strategy: StrategyRow[];
  overall_hit_rate: number | null;
  matrix: { columns: string[]; rows: MatrixRow[] };
  side_matrix: { columns: { group: string; label: string }[]; rows: MatrixRow[] };
  slices: Slice[];
  names: Record<string, string>;
};

export type StrategyMeta = { key: string; short: string; name: string; enabled: boolean };

function localDay(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString("en-CA") : "";
}

function clock(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

function sideVal(pair: SidePair | undefined, team: string | null, digits = 0): string {
  const raw = pair ? (team === "away" ? pair.away : pair.home) : null;
  if (raw == null || Number.isNaN(Number(raw))) return "–";
  return digits ? Number(raw).toFixed(digits) : String(Math.round(Number(raw)));
}

function triggerOdds(row: ResultItem): string {
  const f = row.factors;
  const raw = f?.trigger_odds ?? (row.team === "away" ? f?.odds_away : f?.odds_home);
  return raw == null ? "–" : Number(raw).toFixed(2);
}

type HeatColumn = { label: string; group?: string };

// Strategy rows × columns of hit rate, coloured against all strategies. Columns
// that carry a `group` get a header above them and a gap where the group changes.
function HeatGrid({
  columns,
  rows,
  overall,
  short,
  cellName,
}: {
  columns: HeatColumn[];
  rows: MatrixRow[];
  overall: number | null;
  short: (key: string) => string;
  cellName: (strategy: string, column: HeatColumn) => string;
}) {
  const starts = columns.map((c, i) => i > 0 && c.group !== columns[i - 1].group);
  const groups = columns.some((c) => c.group)
    ? columns.reduce<{ label: string; span: number }[]>((out, c, i) => {
        if (i && !starts[i]) out[out.length - 1].span += 1;
        else out.push({ label: c.group || "", span: 1 });
        return out;
      }, [])
    : [];
  const gap = (i: number) => (starts[i] ? "is-group-start" : "");
  return (
    <>
      <div className="kit-heat-wrap">
        <div className="kit-heat" style={{ gridTemplateColumns: `58px repeat(${columns.length}, minmax(34px, 1fr))` }}>
          {groups.length ? (
            <>
              <span />
              {groups.map((g, i) => (
                <span key={g.label} className={`kit-heat-group ${i ? "is-group-start" : ""}`} style={{ gridColumn: `span ${g.span}` }}>
                  {g.label}
                </span>
              ))}
            </>
          ) : null}
          <span />
          {columns.map((c, i) => (
            <span key={`${c.group}:${c.label}`} className={`kit-heat-col ${gap(i)}`}>
              {c.label}
            </span>
          ))}
          {rows.map((row) => (
            <Fragment key={row.strategy}>
              <span className="kit-heat-row">{short(row.strategy)}</span>
              {row.cells.map((cell, i) => {
                const name = cellName(row.strategy, columns[i]);
                if (cell.settled < 5 || overall == null) {
                  return (
                    <span
                      key={i}
                      className={`kit-heat-cell is-empty ${gap(i)}`}
                      {...tip(name, [["Settled", String(cell.settled)], ["Hit rate", cell.settled ? pct(cell.confirmed / cell.settled) : "–"]])}
                    >
                      {cell.settled ? "·" : ""}
                    </span>
                  );
                }
                const rate = cell.confirmed / cell.settled;
                const bg = diverging(rate - overall);
                return (
                  <span
                    key={i}
                    className={`kit-heat-cell ${gap(i)}`}
                    style={{ background: bg, color: inkFor(bg) }}
                    {...tip(name, [
                      ["Hit rate", pct1(rate)],
                      ["Hits / settled", `${cell.confirmed} / ${cell.settled}`],
                      ["vs all strategies", `${rate >= overall ? "+" : ""}${((rate - overall) * 100).toFixed(1)} pts`],
                    ])}
                  >
                    {pct(rate)}
                  </span>
                );
              })}
            </Fragment>
          ))}
        </div>
      </div>
      <div className="kit-legend kit-legend-gap">
        <span>
          worse
          <i className="kit-ramp" style={{ background: "linear-gradient(90deg,#d95926,#2a3340,#3987e5)" }} />
          better
        </span>
        <span>
          <i className="kit-hatch" />
          fewer than 5 settled
        </span>
      </div>
    </>
  );
}

// Local-day bounds of the picked period, as UTC instants for /results.
function logBounds(range: Range): { since: string; until: string } {
  const first = range.mode === "custom" ? range.from : isoDay(Number(range.mode) - 1);
  const last = range.mode === "custom" ? range.to : isoDay(0);
  const end = new Date(`${last}T00:00:00`);
  end.setDate(end.getDate() + 1);
  return { since: new Date(`${first}T00:00:00`).toISOString(), until: end.toISOString() };
}

export function AdminResults({
  api,
  range,
  zone,
  strategies,
  strategy,
  onStrategy,
}: {
  api: Api;
  range: Range;
  zone: string;
  strategies: StrategyMeta[];
  strategy: string | null;
  onStrategy: (key: string | null) => void;
}) {
  const [body, setBody] = useState<ResultsInsights | null>(null);
  const [log, setLog] = useState<ResultItem[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [minN, setMinN] = useState(true);
  const [logState, setLogState] = useState("");
  const [query, setQuery] = useState("");
  const [openRow, setOpenRow] = useState<number | null>(null);

  const load = useCallback(async () => {
    if (!rangeValid(range)) return;
    setBusy(true);
    setError("");
    try {
      const params = rangeQuery(range, zone);
      if (strategy) params.append("strategy", strategy);
      const bounds = logBounds(range);
      const logParams = new URLSearchParams({ ...bounds, limit: "1000", patterns: "false" });
      if (strategy) logParams.append("strategy", strategy);
      const [insights, rows] = await Promise.all([
        api<ResultsInsights>(`/api/admin/insights/results?${params.toString()}`),
        api<{ items: ResultItem[] }>(`/api/admin/results?${logParams.toString()}`),
      ]);
      setBody(insights);
      setLog(rows.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "load failed");
    } finally {
      setBusy(false);
    }
  }, [api, range, zone, strategy]);

  useEffect(() => {
    void load();
  }, [load]);

  const names = useMemo(() => {
    const out: Record<string, string> = { ...(body?.names || {}) };
    for (const s of strategies) out[s.key] = s.short;
    return out;
  }, [body, strategies]);
  const short = (key: string) => names[key] || key;

  async function downloadCsv() {
    const params = new URLSearchParams(logBounds(range));
    if (strategy) params.append("strategy", strategy);
    const res = await fetch(`/api/admin/results.csv?${params.toString()}`, { credentials: "include" });
    if (!res.ok) {
      setError(`CSV failed: HTTP ${res.status}`);
      return;
    }
    const url = URL.createObjectURL(await res.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = "kalchas-results.csv";
    link.click();
    URL.revokeObjectURL(url);
  }

  if (!rangeValid(range)) return <p className="kit-empty">Pick a From date on or before the To date.</p>;
  if (!body) return <p className="kit-empty">{error || "Loading results…"}</p>;

  const days = body.window.days;
  const S = body.summary;
  const P = body.previous;
  const label = prevLabel(days);
  const spark = body.daily.map((d) => d.hit_rate);
  const overall = body.overall_hit_rate;
  const [lo, hi] = wilson(S.confirmed, S.settled);
  const chartSettled = body.daily.reduce((s, d) => s + d.settled, 0);
  const chartHits = body.daily.reduce((s, d) => s + d.confirmed, 0);

  const scorecard = [...body.by_strategy].sort(
    (a, b) => (b.current.hit_rate ?? -1) - (a.current.hit_rate ?? -1),
  );
  const minSlice = minN ? 15 : 5;
  const base = S.hit_rate ?? 0;
  const ranked = body.slices
    .filter((s) => s.n >= minSlice)
    .map((s) => ({ ...s, lift: s.hit_rate - base }));
  const lean = ranked.filter((s) => s.lift > 0).sort((a, b) => b.lift - a.lift).slice(0, 7);
  const avoid = ranked.filter((s) => s.lift < 0).sort((a, b) => a.lift - b.lift).slice(0, 7);
  const maxLift = Math.max(0.05, ...ranked.map((s) => Math.abs(s.lift)));

  const needle = query.trim().toLowerCase();
  const rows = log.filter(
    (row) =>
      (!logState || row.state === logState) &&
      (!needle ||
        [row.home_team, row.away_team, row.league, row.factors?.country]
          .some((field) => (field || "").toLowerCase().includes(needle))),
  );
  const byDay = new Map<string, ResultItem[]>();
  for (const row of rows) {
    const key = localDay(row.created_at);
    byDay.set(key, [...(byDay.get(key) || []), row]);
  }
  const today = isoDay(0);
  const yesterday = isoDay(1);

  const liftRow = (s: (typeof ranked)[number]) => (
    <div
      key={`${s.dim}:${s.label}`}
      className="res-lift"
      {...tip(`${s.dim}: ${s.label}`, [
        ["Hit rate", pct1(s.hit_rate)],
        ["Hits / settled", `${s.confirmed} / ${s.n}`],
        ["This period overall", pct1(base)],
        ["90% likely range", wilson(s.confirmed, s.n).map(pct).join(" – ")],
      ])}
    >
      <div className="res-lift-what">
        <b>{s.dim === "Country" ? `${countryFlag(s.label)} ${s.label}` : s.label}</b>
        <span>{s.dim}</span>
      </div>
      <span className="kit-num kit-muted">n {s.n}</span>
      <span className="res-lift-track">
        <span
          className={`res-lift-fill ${s.lift >= 0 ? "is-pos" : "is-neg"}`}
          style={{ width: `${(Math.abs(s.lift) / maxLift) * 50}%` }}
        />
      </span>
      <span className="kit-num res-lift-pts">
        {s.lift >= 0 ? "+" : "−"}
        {Math.abs(Math.round(s.lift * 100))} pts
      </span>
    </div>
  );

  return (
    <>
      <div className="kit-chips">
        <span className="kit-chips-label">Strategy</span>
        <button type="button" className={!strategy ? "is-on" : ""} onClick={() => onStrategy(null)}>
          All <span>{body.by_strategy.reduce((s, r) => s + r.current.total, 0)}</span>
        </button>
        {body.by_strategy.map((row) => {
          const meta = strategies.find((s) => s.key === row.strategy);
          return (
            <button
              key={row.strategy}
              type="button"
              className={strategy === row.strategy ? "is-on" : ""}
              title={meta?.name}
              onClick={() => onStrategy(strategy === row.strategy ? null : row.strategy)}
            >
              {short(row.strategy)} <span>{row.current.total}</span>
              {meta && !meta.enabled ? <span>off</span> : null}
              {!meta ? <span>retired</span> : null}
            </button>
          );
        })}
        <span className="kit-chips-note">{fmtWindow(body.window)}</span>
      </div>
      {error ? <p className="kit-error">{error}</p> : null}

      <StatStrip
        stats={[
          {
            label: "Hit rate",
            hero: true,
            value: pct(S.hit_rate),
            foot: <Delta cur={S.hit_rate} prev={P.hit_rate} pts label={label} />,
            spark,
            tipRows: [
              ["This period", pct1(S.hit_rate)],
              ["Previous period", pct1(P.hit_rate)],
              ["90% likely range", S.settled ? `${pct(lo)} – ${pct(hi)}` : "–"],
            ],
          },
          {
            label: "Alerts fired",
            value: fmtInt(S.total),
            foot: <Delta cur={S.total} prev={P.total} label={label} />,
            spark: body.daily.map((d) => d.total),
          },
          {
            label: "Hits",
            value: (
              <>
                {fmtInt(S.confirmed)}
                <small>/ {fmtInt(S.settled)} settled</small>
              </>
            ),
            foot: <Delta cur={S.confirmed} prev={P.confirmed} label={label} />,
            spark: body.daily.map((d) => d.confirmed),
          },
          {
            label: "Median minutes to goal",
            value: (
              <>
                {S.median_to_goal ?? "–"}
                <small>min</small>
              </>
            ),
            foot: <Delta cur={S.median_to_goal} prev={P.median_to_goal} invert label={label} />,
          },
          {
            label: "Still open",
            value: fmtInt(S.open),
            foot: <span className="kit-delta">being monitored now</span>,
          },
        ]}
      />

      <Card
        title="Strategy scorecard"
        sub="Dot = hit rate, band = 90% likely range for that many alerts, dashed line = all strategies. Click a row to focus the page on it."
      >
        <div className="kit-table-wrap">
          <table className="kit-table">
            <thead>
              <tr>
                <th>Strategy</th>
                <th className="r">Alerts</th>
                <th>Hit rate</th>
                <th className="r">Change</th>
                <th>Last 14 days</th>
                <th className="r">Median to goal</th>
                <th>Best slice</th>
              </tr>
            </thead>
            <tbody>
              {scorecard.map((row) => {
                const c = row.current;
                const [a, b] = wilson(c.confirmed, c.settled);
                const meta = strategies.find((s) => s.key === row.strategy);
                const pos = (x: number) => `${(x * 100).toFixed(1)}%`;
                return (
                  <tr
                    key={row.strategy}
                    className={`is-click ${strategy && strategy !== row.strategy ? "is-dim" : ""}`}
                    onClick={() => onStrategy(strategy === row.strategy ? null : row.strategy)}
                  >
                    <td>
                      <span className="kit-tag">{short(row.strategy)}</span>
                      {meta && !meta.enabled ? <small>disabled</small> : null}
                      {!meta ? <small>retired</small> : null}
                    </td>
                    <td className="r kit-num">
                      {c.total}
                      <small>{c.settled} settled</small>
                    </td>
                    <td>
                      <div
                        className="res-rate"
                        {...tip(short(row.strategy), [
                          ["Hit rate", pct1(c.hit_rate)],
                          ["Hits / settled", `${c.confirmed} / ${c.settled}`],
                          ["90% likely range", c.settled ? `${pct(a)} – ${pct(b)}` : "–"],
                          ["All strategies", pct1(overall)],
                        ])}
                      >
                        <span className="kit-num">{pct(c.hit_rate)}</span>
                        <span className="res-rate-track">
                          {c.settled && c.hit_rate != null ? (
                            <>
                              <span className="res-rate-ci" style={{ left: pos(a), width: pos(b - a) }} />
                              <span className="res-rate-pt" style={{ left: pos(c.hit_rate) }} />
                            </>
                          ) : null}
                          {overall != null ? <span className="res-rate-base" style={{ left: pos(overall) }} /> : null}
                        </span>
                      </div>
                    </td>
                    <td className="r">
                      <Delta cur={c.hit_rate} prev={row.previous.hit_rate} pts />
                    </td>
                    <td>
                      <Sparkline values={row.trend} width={110} />
                    </td>
                    <td className="r kit-num">{c.median_to_goal != null ? `${c.median_to_goal}′` : "–"}</td>
                    <td>
                      {row.best_slice ? (
                        <>
                          {row.best_slice.label}
                          <small>
                            {pct(row.best_slice.hit_rate)} on {row.best_slice.n} · {row.best_slice.dim}
                          </small>
                        </>
                      ) : (
                        <span className="kit-muted">not enough data</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="kit-grid-2">
        <Card
          title="Hit rate by day"
          sub={fmtWindow(body.chart_window)}
          right={
            <Legend
              items={[
                { label: "Hit rate", color: "var(--accent)" },
                { label: "Period average", color: "var(--muted)" },
              ]}
            />
          }
        >
          <LineChart
            ariaLabel="Hit rate by day"
            baseline={chartSettled ? chartHits / chartSettled : null}
            points={body.daily.map((d) => ({
              label: fmtShort(d.date),
              title: fmtDay(d.date),
              value: d.hit_rate,
              rows: [
                ["Hit rate", pct(d.hit_rate)],
                ["Hits / settled", `${d.confirmed} / ${d.settled}`],
                ["Fired", String(d.total)],
              ],
            }))}
          />
        </Card>
        <Card title="Minute of fire × strategy" sub="Hit rate per cell, coloured against all strategies">
          <HeatGrid
            columns={body.matrix.columns.map((c) => ({ label: `${c}′` }))}
            rows={body.matrix.rows}
            overall={overall}
            short={short}
            cellName={(key, c) => `${short(key)} · fired ${c.label}`}
          />
        </Card>
      </div>

      {body.side_matrix ? (
        <Card
          title="Trigger side × strategy"
          sub="Who the alert fired for: home or away, kickoff favourite or underdog, and that side's score at fire. Alerts without both kickoff prices sit out the favourite/underdog pair."
        >
          <HeatGrid
            columns={body.side_matrix.columns}
            rows={body.side_matrix.rows}
            overall={overall}
            short={short}
            cellName={(key, c) => `${short(key)} · ${c.group}: ${c.label}`}
          />
        </Card>
      ) : null}

      <Card
        title="Where it works"
        sub="Every slice (minute, score, odds, side, sweet spot, league, weekday…) ranked by how far it beats or trails this period's rate"
        right={
          <label className="kit-toggle">
            <input type="checkbox" checked={minN} onChange={(event) => setMinN(event.target.checked)} />
            Hide slices under 15 alerts
          </label>
        }
      >
        <div className="kit-grid-2 res-lift-cols">
          <div>
            <Legend items={[{ label: "Lean into", color: "var(--s1)" }]} />
            {lean.length ? lean.map(liftRow) : <p className="kit-muted">Nothing clearly above average on this much data.</p>}
          </div>
          <div>
            <Legend items={[{ label: "Avoid or tighten", color: "var(--s2)" }]} />
            {avoid.length ? avoid.map(liftRow) : <p className="kit-muted">Nothing clearly below average on this much data.</p>}
          </div>
        </div>
      </Card>

      <Card
        title="Alert log"
        sub={`${rows.length} alert(s) · newest first, grouped by day${log.length >= 1000 ? " · showing the latest 1,000" : ""}`}
        right={
          <div className="kit-tools">
            <div className="kit-seg">
              {[
                ["", "All"],
                ["Confirmed", "✓ Hit"],
                ["Expired", "✕ Miss"],
                ["Monitoring", "● Open"],
              ].map(([value, text]) => (
                <button key={value} type="button" className={logState === value ? "is-on" : ""} onClick={() => setLogState(value)}>
                  {text}
                </button>
              ))}
            </div>
            <input
              className="kit-search"
              type="search"
              value={query}
              placeholder="Team, league, country…"
              onChange={(event) => setQuery(event.target.value)}
            />
            <button type="button" className="kit-btn" onClick={() => void downloadCsv()}>
              Export CSV
            </button>
            <button type="button" className="kit-btn" disabled={busy} onClick={() => void load()}>
              {busy ? "Loading…" : "Refresh"}
            </button>
          </div>
        }
      >
        <div className="kit-table-wrap res-log-wrap">
          <table className="kit-table res-log">
            <thead>
              <tr>
                <th>Time</th>
                <th>Match</th>
                <th>Strategy</th>
                <th>At fire</th>
                <th>Board at fire</th>
                <th className="r">Odds</th>
                <th>Settled</th>
                <th>Outcome</th>
              </tr>
            </thead>
            <tbody>
              {[...byDay.entries()].map(([day, items]) => {
                const confirmed = items.filter((r) => r.state === "Confirmed").length;
                const settled = items.filter((r) => r.state !== "Monitoring").length;
                return (
                  <Fragment key={day}>
                    <tr className="res-day">
                      <td colSpan={8}>
                        <b>{day === today ? "Today" : day === yesterday ? "Yesterday" : fmtDay(day)}</b>
                        {items.length} alerts
                        <span className="kit-num">
                          {confirmed}/{settled} hit · {pct(settled ? confirmed / settled : null)}
                        </span>
                        {items.length - settled ? <span className="kit-num">· {items.length - settled} open</span> : null}
                      </td>
                    </tr>
                    {items.map((row) => {
                      const f = row.factors;
                      const tone = row.state === "Confirmed" ? "is-ok" : row.state === "Expired" ? "is-miss" : "is-open";
                      const gap =
                        row.state === "Confirmed" && row.settle_minute != null ? row.settle_minute - row.minute : null;
                      return (
                        <Fragment key={row.id}>
                          <tr className={`res-row is-click ${tone}`} onClick={() => setOpenRow(openRow === row.id ? null : row.id)}>
                            <td className="kit-num">{clock(row.created_at)}</td>
                            <td>
                              {row.live ? (
                                <a href={`/?match=${encodeURIComponent(row.match_id)}`} onClick={(e) => e.stopPropagation()}>
                                  {row.home_team} v {row.away_team}
                                </a>
                              ) : (
                                <>
                                  {row.home_team} v {row.away_team}
                                </>
                              )}
                              <small>
                                {f?.country ? `${countryFlag(f.country)} ` : ""}
                                {row.league || f?.country || ""}
                              </small>
                            </td>
                            <td>
                              <span className="kit-tag">{short(row.strategy)}</span>{" "}
                              <span className="kit-muted">{row.team || ""}</span>
                              {f?.also_firing?.length ? <small>+ {f.also_firing.map(short).join(", ")} also firing</small> : null}
                            </td>
                            <td className="kit-num">
                              {row.score || "–"} · {row.minute}′<small>value {row.value.toFixed(1)}</small>
                            </td>
                            <td>
                              <span className="res-facts">
                                <span>
                                  <b>K</b>
                                  {sideVal(f?.k, row.team)}
                                </span>
                                <span>
                                  <b>Δ5</b>
                                  {sideVal(f?.d5, row.team, 1)}
                                </span>
                                <span>
                                  <b>Δ10</b>
                                  {sideVal(f?.d10, row.team)}
                                </span>
                                <span>
                                  <b>ΦI</b>
                                  {sideVal(f?.phi, row.team)}
                                </span>
                              </span>
                            </td>
                            <td className="r kit-num">{triggerOdds(row)}</td>
                            <td className="kit-num">
                              {row.settle_score ? `${row.settle_score}${row.settle_minute != null ? ` ${row.settle_minute}′` : ""}` : "–"}
                            </td>
                            <td>
                              <OutcomePill state={row.state} />
                            </td>
                          </tr>
                          {openRow === row.id ? (
                            <tr className="res-expand">
                              <td colSpan={8}>
                                <div className="res-expand-grid">
                                  <div><span>Half</span><b>{f?.half || "–"}</b></div>
                                  <div><span>Score state</span><b>{f?.score_state || "–"}</b></div>
                                  <div><span>Time since last goal</span><b>{f?.tslg_bucket || f?.tslg || "–"}</b></div>
                                  <div><span>Odds band</span><b>{f?.odds_bucket || "–"}</b></div>
                                  <div><span>Sweet spot</span><b>{f?.sweet_spot == null ? "–" : f.sweet_spot ? "yes" : "no"}</b></div>
                                  <div><span>Minutes to goal</span><b>{gap != null ? `${gap}′` : "–"}</b></div>
                                </div>
                              </td>
                            </tr>
                          ) : null}
                        </Fragment>
                      );
                    })}
                  </Fragment>
                );
              })}
              {!rows.length ? (
                <tr>
                  <td colSpan={8} className="kit-muted kit-pad">
                    {busy ? "Loading…" : "No alerts match these filters."}
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
