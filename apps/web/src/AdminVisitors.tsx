import { useCallback, useEffect, useMemo, useState } from "react";
import { countryFlag } from "./App";
import {
  BarList,
  Card,
  Delta,
  Legend,
  StackedBars,
  StatStrip,
  fmtDay,
  fmtDur,
  fmtInt,
  fmtShort,
  fmtWindow,
  pct,
  pct1,
  prevLabel,
  rangeQuery,
  rangeValid,
  sequential,
  tip,
  type Api,
  type Range,
} from "./AdminKit";

type MatchRef = { match_id: string; home_team: string | null; away_team: string | null };

type Visit = {
  id: number;
  visitor_id: string | null;
  ip: string | null;
  country: string;
  first_seen: string;
  last_seen: string;
  duration_seconds: number;
  page_loads: number;
  heartbeats: number;
  referrer: string | null;
  landing_path: string | null;
  matches: MatchRef[];
  telegram_free: boolean;
  telegram_paid: boolean;
  watchlist: string[];
  visit_count: number;
  returning: boolean;
  user_agent: string;
  browser: string;
  os: string;
  device: string;
  likely_human: boolean;
  reasons: string[];
};

export type VisitStats = {
  visitors: number;
  visits: number;
  median_seconds: number | null;
  returning_share: number | null;
  bounce_rate: number | null;
  engaged: number;
  match_viewers: number;
  telegram_visitors: number;
  paid_visitors: number;
  telegram_rate: number | null;
  watchlist_visitors: number;
  watchlist_rate: number | null;
};

type Count = { label: string; visitors: number };

type WatchlistUsage = {
  visitors: number;
  opened: number;
  ways_in: Count[];
  inside: Count[];
  daily: { date: string; visitors: number; opened: number }[];
};

type Win = { first: string; last: string; days: number };
type Share = { label: string; visitors: number; other?: boolean };

type VisitorsInsights = {
  window: Win;
  previous_window: Win | null;
  chart_window: Win;
  live_now: number | null;
  summary: VisitStats;
  previous: VisitStats | null;
  daily: { date: string; new: number; returning: number }[];
  hourly: { hour: number; new: number; returning: number }[];
  heatmap: number[][];
  durations: { label: string; visits: number }[];
  sources: {
    source: string;
    visitors: number;
    previous: number | null;
    median_seconds: number | null;
    telegram_rate: number | null;
  }[];
  countries: Share[];
  devices: Share[];
  browsers: Share[];
  os: Share[];
  matches: (MatchRef & { viewers: number })[];
  watchlist: WatchlistUsage;
  filtered: number;
  log: Visit[];
};

/** Short names for the raw log's Watchlist column. */
const WATCHLIST_SHORT: Record<string, string> = {
  "in:hero": "hero",
  "in:board": "board tag",
  "in:panel": "pop-up",
  "in:tab": "mobile tab",
  "in:link": "link",
  match: "match page",
  tomorrow: "tomorrow",
  past: "past day",
  calendar: "calendar",
};

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const DEVICE_COLORS = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--muted)"];
const VISITOR_ID_KEY = "kalchas.visitor.v1";

function ownVisitorId(): string {
  try {
    return localStorage.getItem(VISITOR_ID_KEY) || "";
  } catch {
    return "";
  }
}

function hh(hour: number): string {
  return String(hour).padStart(2, "0");
}

function countryName(code: string): string {
  if (!code) return "Unknown";
  try {
    return new Intl.DisplayNames(["en"], { type: "region" }).of(code) || code;
  } catch {
    return code;
  }
}

function seenAt(iso: string): string {
  return new Date(iso).toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function AdminVisitors({ api, range, zone }: { api: Api; range: Range; zone: string }) {
  const me = useMemo(ownVisitorId, []);
  const [body, setBody] = useState<VisitorsInsights | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [by, setBy] = useState<"day" | "hour">("day");
  const [bots, setBots] = useState(false);
  const [query, setQuery] = useState("");

  const load = useCallback(async () => {
    if (!rangeValid(range)) return;
    setBusy(true);
    setError("");
    try {
      setBody(await api<VisitorsInsights>(`/api/admin/insights/visitors?${rangeQuery(range, zone).toString()}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "load failed");
    } finally {
      setBusy(false);
    }
  }, [api, range, zone]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!rangeValid(range)) return <p className="kit-empty">Pick a From date on or before the To date.</p>;
  if (!body) return <p className="kit-empty">{error || "Loading visitors…"}</p>;

  const S = body.summary;
  const P = body.previous;
  const label = prevLabel(body.window.days);
  const daySpark = body.daily.map((d) => d.new + d.returning);
  const steps: [string, number][] = [
    ["Landed", S.visitors],
    ["Stayed 1 min+", S.engaged],
    ["Opened a match", S.match_viewers],
    ["Clicked Telegram", S.telegram_visitors],
    ["Clicked paid", S.paid_visitors],
  ];
  const W = body.watchlist;
  const durMax = Math.max(1, ...body.durations.map((d) => d.visits));
  const srcMax = Math.max(1, ...body.sources.map((s) => s.visitors));
  const heatMax = Math.max(1, ...body.heatmap.flat());
  const deviceTotal = body.devices.reduce((s, d) => s + d.visitors, 0);
  const needle = query.trim().toLowerCase();
  const log = body.log.filter(
    (v) =>
      (bots || v.likely_human) &&
      (!needle ||
        [v.country, v.ip, v.browser, v.os, v.device, v.referrer, v.landing_path]
          .concat(v.matches.map((m) => `${m.home_team} ${m.away_team}`))
          .some((f) => (f || "").toLowerCase().includes(needle))),
  );

  return (
    <>
      <div className="kit-chips">
        <span className="kit-chips-note">
          {fmtWindow(body.window)} · likely humans only
          {body.filtered ? ` · ${fmtInt(body.filtered)} bot / no-JS visits hidden` : ""}
        </span>
        {body.live_now != null ? (
          <span className="kit-live">
            <i />
            <b>{body.live_now}</b> on the board now
          </span>
        ) : null}
      </div>
      {error ? <p className="kit-error">{error}</p> : null}

      <StatStrip
        stats={[
          {
            label: "Unique visitors",
            hero: true,
            value: fmtInt(S.visitors),
            foot: <Delta cur={S.visitors} prev={P?.visitors} label={label} />,
            spark: daySpark,
          },
          { label: "Visits", value: fmtInt(S.visits), foot: <Delta cur={S.visits} prev={P?.visits} label={label} /> },
          {
            label: "Typical visit (median)",
            value: fmtDur(S.median_seconds),
            foot: <Delta cur={S.median_seconds} prev={P?.median_seconds} label={label} />,
          },
          {
            label: "Returning visitors",
            value: pct(S.returning_share),
            foot: <Delta cur={S.returning_share} prev={P?.returning_share} pts label={label} />,
          },
          {
            label: "Bounced (<15s)",
            value: pct(S.bounce_rate),
            foot: <Delta cur={S.bounce_rate} prev={P?.bounce_rate} pts invert label={label} />,
          },
          {
            label: "Clicked Telegram",
            value: (
              <>
                {fmtInt(S.telegram_visitors)}
                <small>{pct1(S.telegram_rate)}</small>
              </>
            ),
            foot: <Delta cur={S.telegram_rate} prev={P?.telegram_rate} pts label={label} />,
          },
        ]}
      />

      <Card
        title="Traffic"
        sub={by === "day" ? `Unique visitors per day · ${fmtWindow(body.chart_window)}` : "Visits by hour of day, this period"}
        right={
          <>
            <Legend
              items={[
                { label: "New", color: "var(--s1)" },
                { label: "Returning", color: "var(--s2)" },
              ]}
            />
            <div className="kit-seg">
              <button type="button" className={by === "day" ? "is-on" : ""} onClick={() => setBy("day")}>
                By day
              </button>
              <button type="button" className={by === "hour" ? "is-on" : ""} onClick={() => setBy("hour")}>
                By hour of day
              </button>
            </div>
          </>
        }
      >
        {by === "day" ? (
          <StackedBars
            ariaLabel="Unique visitors per day"
            columns={body.daily.map((d, i) => ({
              label: fmtShort(d.date),
              title: `${fmtDay(d.date)}${i === body.daily.length - 1 ? " (so far)" : ""}`,
              a: d.new,
              b: d.returning,
              dim: i === body.daily.length - 1,
              rows: [
                ["Visitors", fmtInt(d.new + d.returning)],
                ["New", fmtInt(d.new)],
                ["Returning", fmtInt(d.returning)],
              ],
            }))}
          />
        ) : (
          <StackedBars
            ariaLabel="Visits by hour of day"
            labelEvery={3}
            columns={body.hourly.map((h) => ({
              label: `${hh(h.hour)}h`,
              title: `${hh(h.hour)}:00–${hh(h.hour)}:59`,
              a: h.new,
              b: h.returning,
              rows: [
                ["Visits", fmtInt(h.new + h.returning)],
                ["New", fmtInt(h.new)],
                ["Returning", fmtInt(h.returning)],
              ],
            }))}
          />
        )}
      </Card>

      <div className="kit-grid-2">
        <Card title="Conversion funnel" sub="From landing to the paid Telegram button, per visitor">
          <div className="vis-funnel">
            {steps.map(([name, n], i) => {
              const share = S.visitors ? n / S.visitors : 0;
              const prevN = i ? steps[i - 1][1] : n;
              return (
                <div
                  key={name}
                  className="vis-step"
                  {...tip(name, [
                    ["Visitors", fmtInt(n)],
                    ["Of everyone who landed", pct1(share)],
                    ...(i ? ([["Of the step before", pct1(prevN ? n / prevN : null)]] as [string, string][]) : []),
                  ])}
                >
                  <span className="vis-step-name">{name}</span>
                  <span className="vis-step-track">
                    <span className="vis-step-fill" style={{ width: `${Math.max(share * 100, 1.5)}%` }} />
                    <span className="vis-step-n kit-num" style={{ left: `calc(${Math.max(share * 100, 1.5)}% + 8px)` }}>
                      {fmtInt(n)}
                    </span>
                  </span>
                  <span className="vis-step-conv kit-num">
                    {i ? pct(prevN ? n / prevN : null) : "100%"}
                    <small>{i ? "of step before" : "landed"}</small>
                  </span>
                </div>
              );
            })}
          </div>
        </Card>
        <Card title="How long people stay" sub="Visits by length">
          <div className="vis-hist">
            {body.durations.map((d) => (
              <div
                key={d.label}
                className="vis-hist-col"
                {...tip(d.label, [
                  ["Visits", fmtInt(d.visits)],
                  ["Share", pct1(S.visits ? d.visits / S.visits : null)],
                ])}
              >
                <span className="kit-num">{pct(S.visits ? d.visits / S.visits : null)}</span>
                <span className="vis-hist-bar" style={{ height: `${(d.visits / durMax) * 100}%` }} />
                <span className="vis-hist-label">{d.label}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <Card
        title="Watchlist"
        sub={
          <>
            Opened by <b className="kit-num">{fmtInt(W.opened)}</b> of {fmtInt(W.visitors)} visitors (
            {pct1(S.watchlist_rate)})
            {P ? (
              <>
                {" · "}
                <Delta cur={S.watchlist_rate} prev={P.watchlist_rate} pts label={label} />
              </>
            ) : null}
          </>
        }
        right={
          <Legend
            items={[
              { label: "Opened the watchlist", color: "var(--s1)" },
              { label: "Didn't", color: "var(--border-2)" },
            ]}
          />
        }
      >
        <StackedBars
          ariaLabel="Visitors who opened the watchlist, per day"
          height={180}
          topColor="var(--border-2)"
          columns={W.daily.map((d, i) => ({
            label: fmtShort(d.date),
            title: `${fmtDay(d.date)}${i === W.daily.length - 1 ? " (so far)" : ""}`,
            a: d.opened,
            b: d.visitors - d.opened,
            dim: i === W.daily.length - 1,
            rows: [
              ["Visitors", fmtInt(d.visitors)],
              ["Opened the watchlist", fmtInt(d.opened)],
              ["Share", pct1(d.visitors ? d.opened / d.visitors : null)],
            ],
          }))}
        />
        <div className="kit-grid-2 kit-grid-even vis-wl">
          <div>
            <div className="vis-sub">How they got in · share of those who opened it</div>
            <BarList
              total={W.opened}
              rows={W.ways_in.map((r) => ({
                key: r.label,
                label: (
                  <>
                    {r.label} <small className="kit-muted kit-num">{fmtInt(r.visitors)}</small>
                  </>
                ),
                value: r.visitors,
                tipRows: [["Visitors", fmtInt(r.visitors)]],
              }))}
            />
          </div>
          <div>
            <div className="vis-sub">What they did inside · share of those who opened it</div>
            <BarList
              total={W.opened}
              rows={W.inside.map((r) => ({
                key: r.label,
                label: (
                  <>
                    {r.label} <small className="kit-muted kit-num">{fmtInt(r.visitors)}</small>
                  </>
                ),
                value: r.visitors,
                tipRows: [["Visitors", fmtInt(r.visitors)]],
              }))}
            />
          </div>
        </div>
        <p className="kit-muted vis-wl-note">
          Counted from 3 Nov 2026. "Direct link" is someone who landed straight on a watchlist page (a shared link or a
          bookmark). One person can come in more than one way, so the ways in can add up to more than 100%.
        </p>
      </Card>

      <Card title="Where visitors come from" sub="Referrer of the first page load. Telegram click rate is per visitor.">
        <div className="kit-table-wrap">
          <table className="kit-table">
            <thead>
              <tr>
                <th>Source</th>
                <th>Visitors</th>
                <th className="r">Change</th>
                <th className="r">Typical visit</th>
                <th className="r">Telegram click rate</th>
              </tr>
            </thead>
            <tbody>
              {body.sources.map((s) => (
                <tr key={s.source}>
                  <td>{s.source}</td>
                  <td>
                    <span className="vis-src">
                      <span className="kit-num">{fmtInt(s.visitors)}</span>
                      <span className="kit-bar-track">
                        <span className="kit-bar-fill" style={{ width: `${(s.visitors / srcMax) * 100}%` }} />
                      </span>
                    </span>
                  </td>
                  <td className="r">
                    <Delta cur={s.visitors} prev={s.previous} />
                  </td>
                  <td className="r kit-num">{fmtDur(s.median_seconds)}</td>
                  <td className="r kit-num">{pct1(s.telegram_rate)}</td>
                </tr>
              ))}
              {!body.sources.length ? (
                <tr>
                  <td colSpan={5} className="kit-muted kit-pad">
                    No visits in this period.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="kit-grid-3">
        <Card title="Countries">
          <BarList
            total={S.visitors}
            rows={body.countries.map((c) => ({
              key: c.label || "unknown",
              label: c.other ? c.label : `${countryFlag(c.label)} ${countryName(c.label)}`,
              value: c.visitors,
              muted: c.other,
              tipRows: [["Visitors", fmtInt(c.visitors)]],
            }))}
          />
        </Card>
        <Card title="Devices">
          <div className="vis-split">
            {body.devices.map((d, i) => (
              <span
                key={d.label}
                style={{ width: `${deviceTotal ? (d.visitors / deviceTotal) * 100 : 0}%`, background: DEVICE_COLORS[i] }}
                {...tip(d.label, [
                  ["Visitors", fmtInt(d.visitors)],
                  ["Share", pct1(deviceTotal ? d.visitors / deviceTotal : null)],
                ])}
              />
            ))}
          </div>
          <div className="kit-legend vis-device-legend">
            {body.devices.map((d, i) => (
              <span key={d.label}>
                <i style={{ background: DEVICE_COLORS[i] }} />
                {d.label} <b className="kit-num">{pct(deviceTotal ? d.visitors / deviceTotal : null)}</b>
              </span>
            ))}
          </div>
          <div className="vis-sub">Browser</div>
          <BarList total={S.visitors} rows={body.browsers.map((b) => ({ key: b.label, label: b.label, value: b.visitors, muted: b.other }))} />
          <div className="vis-sub">OS</div>
          <BarList total={S.visitors} rows={body.os.map((b) => ({ key: b.label, label: b.label, value: b.visitors, muted: b.other }))} />
        </Card>
        <Card title="Most-watched matches">
          <table className="kit-table">
            <thead>
              <tr>
                <th>Match</th>
                <th className="r">Viewers</th>
              </tr>
            </thead>
            <tbody>
              {body.matches.map((m) => (
                <tr key={m.match_id}>
                  <td>{m.home_team && m.away_team ? `${m.home_team} v ${m.away_team}` : m.match_id}</td>
                  <td className="r kit-num">{m.viewers}</td>
                </tr>
              ))}
              {!body.matches.length ? (
                <tr>
                  <td colSpan={2} className="kit-muted kit-pad">
                    No match views yet.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </Card>
      </div>

      <Card
        title="When they visit"
        sub="Visits by weekday and hour, your time zone"
        right={
          <div className="kit-legend">
            <span>
              fewer
              <i className="kit-ramp" style={{ background: "linear-gradient(90deg,#14263b,#1c5cab,#86b6ef)" }} />
              more
            </span>
          </div>
        }
      >
        <div className="kit-table-wrap">
          <div className="kit-heat vis-week" style={{ gridTemplateColumns: "40px repeat(24, minmax(20px, 1fr))" }}>
            <span />
            {Array.from({ length: 24 }, (_, h) => (
              <span key={h} className="kit-heat-col">
                {h % 3 === 0 ? hh(h) : ""}
              </span>
            ))}
            {body.heatmap.map((row, d) => (
              <FragmentRow key={WEEKDAYS[d]} day={WEEKDAYS[d]} row={row} max={heatMax} />
            ))}
          </div>
        </div>
      </Card>

      <div className="kit-note">
        <h3>Not tracked yet</h3>
        <ul>
          <li>
            <b>Retention over time</b> (are week-1 visitors still coming in week 4?): visits are deleted
            after 30 days, so this needs a small daily summary table.
          </li>
          <li>
            <b>Campaigns</b> (which Telegram post or tweet sent people): needs the <code>utm_</code> tags
            saved with each visit.
          </li>
          <li>
            <b>Real paid conversions</b>: only the click on the paid button is recorded, not the subscription.
          </li>
        </ul>
      </div>

      <details className="kit-card vis-raw">
        <summary className="kit-card-head">
          <h2>Raw visit log</h2>
          <span className="kit-sub">
            {log.length} visit(s){body.log.length >= 400 ? " · latest 400" : ""}
          </span>
        </summary>
        <div className="kit-card-body">
          <div className="kit-tools vis-raw-tools">
            <input
              className="kit-search"
              type="search"
              value={query}
              placeholder="Country, IP, browser, match…"
              onChange={(event) => setQuery(event.target.value)}
            />
            <label className="kit-toggle">
              <input type="checkbox" checked={bots} onChange={(event) => setBots(event.target.checked)} />
              Include bots / no-JS
            </label>
            <button type="button" className="kit-btn" disabled={busy} onClick={() => void load()}>
              {busy ? "Loading…" : "Refresh"}
            </button>
          </div>
          <div className="kit-table-wrap">
            <table className="kit-table">
              <thead>
                <tr>
                  <th>Last seen</th>
                  <th>Visitor</th>
                  <th>Country</th>
                  <th>Device</th>
                  <th>Came from</th>
                  <th className="r">Length</th>
                  <th>Matches</th>
                  <th>Telegram</th>
                  <th>Watchlist</th>
                </tr>
              </thead>
              <tbody>
                {log.map((v) => (
                  <tr key={v.id}>
                    <td className="kit-num">{seenAt(v.last_seen)}</td>
                    <td>
                      <span className="kit-pill">{v.returning ? "returning" : "new"}</span>
                      <small>
                        {v.visit_count} visit(s)
                        {me && v.visitor_id === me ? " · you" : ""}
                        {v.likely_human ? "" : ` · bot: ${v.reasons.join(", ")}`}
                      </small>
                    </td>
                    <td>
                      {countryFlag(v.country)} {v.country || "?"}
                      <small>
                        <code>{v.ip || "?"}</code>
                      </small>
                    </td>
                    <td title={v.user_agent}>
                      {v.browser} · {v.os}
                      <small>{v.device}</small>
                    </td>
                    <td>
                      {v.referrer || "Direct"}
                      {v.landing_path && v.landing_path !== "/" ? <small>{v.landing_path}</small> : null}
                    </td>
                    <td className="r kit-num">{fmtDur(v.duration_seconds)}</td>
                    <td title={v.matches.map((m) => `${m.home_team} v ${m.away_team}`).join("\n")}>
                      {v.matches.length || ""}
                      {v.matches.slice(0, 2).map((m) => (
                        <small key={m.match_id}>{m.home_team && m.away_team ? `${m.home_team} v ${m.away_team}` : m.match_id}</small>
                      ))}
                    </td>
                    <td>
                      {v.telegram_paid ? (
                        <span className="kit-pill is-ok">
                          <i>✓</i>paid
                        </span>
                      ) : v.telegram_free ? (
                        <span className="kit-pill is-ok">
                          <i>✓</i>free
                        </span>
                      ) : null}
                    </td>
                    <td>
                      {v.watchlist.some((e) => e.startsWith("in:")) ? (
                        <span className="kit-pill is-ok">
                          <i>✓</i>
                          {WATCHLIST_SHORT[v.watchlist.find((e) => e.startsWith("in:")) ?? ""]}
                        </span>
                      ) : null}
                      {v.watchlist.some((e) => !e.startsWith("in:")) ? (
                        <small>
                          {v.watchlist
                            .filter((e) => !e.startsWith("in:"))
                            .map((e) => WATCHLIST_SHORT[e] ?? e)
                            .join(", ")}
                        </small>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </details>
    </>
  );
}

function FragmentRow({ day, row, max }: { day: string; row: number[]; max: number }) {
  return (
    <>
      <span className="kit-heat-row">{day}</span>
      {row.map((n, h) => (
        <span
          key={h}
          className="kit-heat-cell vis-week-cell"
          style={{ background: sequential(n / max) }}
          {...tip(`${day} ${hh(h)}:00`, [["Visits", fmtInt(n)]])}
        />
      ))}
    </>
  );
}
