import { useCallback, useEffect, useMemo, useState } from "react";
import { countryFlag } from "./App";

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
  visit_count: number;
  returning: boolean;
  user_agent: string;
  browser: string;
  os: string;
  device: string;
  likely_human: boolean;
  reasons: string[];
};

type Day = {
  date: string;
  visitors: number;
  new: number;
  returning: number;
  visits: number;
  total_seconds: number;
  avg_seconds: number;
  telegram_clicks: number;
  filtered: number;
  countries: { code: string; count: number }[];
};

type VisitorsPayload = {
  since: string;
  tz: string;
  humans_only: boolean;
  summary: { visits: number; human_visits: number; human_visitors: number; filtered: number };
  daily: Day[];
  items: Visit[];
};

type SortKey = "last_seen" | "first_seen" | "duration" | "country" | "visits" | "matches";

const VISITOR_ID_KEY = "kalchas.visitor.v1";

function browserZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

function ownVisitorId(): string {
  try {
    return localStorage.getItem(VISITOR_ID_KEY) || "";
  } catch {
    return "";
  }
}

function localDay(iso: string, zone: string): string {
  // en-CA formats as YYYY-MM-DD, matching the API's day keys.
  return new Date(iso).toLocaleDateString("en-CA", { timeZone: zone });
}

function fmtTime(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  return at.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function fmtDuration(seconds: number): string {
  if (seconds < 15) return "<15s";
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${String(seconds % 60).padStart(2, "0")}s`;
  return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`;
}

function fmtDay(date: string): string {
  const at = new Date(`${date}T12:00:00`);
  return at.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

function matchLabel(m: MatchRef): string {
  return m.home_team && m.away_team ? `${m.home_team} v ${m.away_team}` : m.match_id;
}

function sortValue(v: Visit, key: SortKey): number | string {
  switch (key) {
    case "first_seen":
      return v.first_seen;
    case "duration":
      return v.duration_seconds;
    case "country":
      return v.country;
    case "visits":
      return v.visit_count;
    case "matches":
      return v.matches.length;
    default:
      return v.last_seen;
  }
}

export function AdminVisitors({
  api,
}: {
  api: <T>(path: string, init?: RequestInit) => Promise<T>;
}) {
  const zone = useMemo(browserZone, []);
  const me = useMemo(ownVisitorId, []);
  const [days, setDays] = useState(7);
  const [humansOnly, setHumansOnly] = useState(true);
  const [body, setBody] = useState<VisitorsPayload | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [day, setDay] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("last_seen");
  const [sortDesc, setSortDesc] = useState(true);

  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const params = new URLSearchParams({
        days: String(days),
        humans: String(humansOnly),
        tz: zone,
      });
      setBody(await api<VisitorsPayload>(`/api/admin/visitors?${params.toString()}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "load failed");
    } finally {
      setBusy(false);
    }
  }, [api, days, humansOnly, zone]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    setDay(null);
  }, [days]);

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const list = (body?.items || []).filter((v) => {
      if (day && localDay(v.first_seen, zone) !== day) return false;
      if (!needle) return true;
      return [v.country, v.ip, v.browser, v.os, v.device, v.referrer, v.landing_path, v.user_agent]
        .concat(v.matches.map(matchLabel))
        .some((field) => (field || "").toLowerCase().includes(needle));
    });
    const dir = sortDesc ? -1 : 1;
    return [...list].sort((a, b) => {
      const x = sortValue(a, sortKey);
      const y = sortValue(b, sortKey);
      if (x === y) return b.last_seen.localeCompare(a.last_seen);
      return x > y ? dir : -dir;
    });
  }, [body, day, query, sortKey, sortDesc, zone]);

  const peak = Math.max(1, ...(body?.daily || []).map((d) => d.visitors));

  function sortBy(key: SortKey) {
    if (key === sortKey) setSortDesc((current) => !current);
    else {
      setSortKey(key);
      setSortDesc(key !== "country");
    }
  }

  function header(key: SortKey, label: string) {
    const on = key === sortKey;
    return (
      <th aria-sort={on ? (sortDesc ? "descending" : "ascending") : "none"}>
        <button type="button" className="admin-sort" onClick={() => sortBy(key)}>
          {label}
          {on ? (sortDesc ? " ↓" : " ↑") : ""}
        </button>
      </th>
    );
  }

  const summary = body?.summary;

  return (
    <>
      <header>
        <h1>Visitors</h1>
        <p>
          Visits to kalchas.live over the last 30 days. A visit ends after 30 minutes of
          silence. Likely humans ran the board&apos;s JS heartbeat with a browser user agent.
          Days are in {zone}.
        </p>
      </header>

      <div className="admin-results-filters">
        <label>
          Range
          <select value={days} onChange={(event) => setDays(Number(event.target.value))}>
            <option value={1}>Today</option>
            <option value={7}>Last 7 days</option>
            <option value={14}>Last 14 days</option>
            <option value={30}>Last 30 days</option>
          </select>
        </label>
        <label>
          Show
          <select
            value={humansOnly ? "humans" : "all"}
            onChange={(event) => setHumansOnly(event.target.value === "humans")}
          >
            <option value="humans">Likely humans</option>
            <option value="all">Everything (incl. bots)</option>
          </select>
        </label>
        <label>
          Search
          <input
            type="search"
            value={query}
            placeholder="Country, IP, browser, match…"
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
      </div>

      <div className="admin-results-summary">
        <span>
          human visitors <strong>{summary?.human_visitors ?? 0}</strong>
        </span>
        <span>
          human visits <strong>{summary?.human_visits ?? 0}</strong>
        </span>
        <span>
          bots / no-JS <strong>{summary?.filtered ?? 0}</strong>
        </span>
        <button type="button" disabled={busy} onClick={() => void load()}>
          {busy ? "Loading…" : "Refresh"}
        </button>
      </div>
      {error ? <p className="admin-status">{error}</p> : null}

      <article className="admin-card">
        <div className="admin-card-head">
          <h2>By day</h2>
          {day ? (
            <button type="button" className="admin-sort" onClick={() => setDay(null)}>
              Show all days
            </button>
          ) : (
            <span className="admin-hint">Click a day to filter the log</span>
          )}
        </div>
        <div className="admin-results-table-wrap">
          <table className="admin-results-table admin-visitor-days">
            <thead>
              <tr>
                <th>Day</th>
                <th>Visitors</th>
                <th>New</th>
                <th>Returning</th>
                <th>Visits</th>
                <th>Avg visit</th>
                <th>Total time</th>
                <th>Telegram</th>
                <th>Countries</th>
                {humansOnly ? <th>Hidden</th> : null}
              </tr>
            </thead>
            <tbody>
              {(body?.daily || []).map((d) => (
                <tr
                  key={d.date}
                  className={day === d.date ? "is-on" : ""}
                  onClick={() => setDay((current) => (current === d.date ? null : d.date))}
                >
                  <td>{fmtDay(d.date)}</td>
                  <td>
                    <strong>{d.visitors}</strong>
                    <span
                      className="admin-visitor-bar"
                      style={{ width: `${(d.visitors / peak) * 100}%` }}
                    />
                  </td>
                  <td>{d.new}</td>
                  <td>{d.returning}</td>
                  <td>{d.visits}</td>
                  <td>{d.visits ? fmtDuration(d.avg_seconds) : ""}</td>
                  <td>{d.visits ? fmtDuration(d.total_seconds) : ""}</td>
                  <td>{d.telegram_clicks || ""}</td>
                  <td title={d.countries.map((c) => `${c.code || "??"} ${c.count}`).join(", ")}>
                    {d.countries.map((c) => countryFlag(c.code) || c.code || "?").join(" ")}
                  </td>
                  {humansOnly ? <td>{d.filtered || ""}</td> : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </article>

      <article className="admin-card">
        <div className="admin-card-head">
          <h2>{day ? `Visits on ${fmtDay(day)}` : "Visit log"}</h2>
          <span className="admin-hint">{rows.length} visit(s)</span>
        </div>
        <div className="admin-results-table-wrap">
          <table className="admin-results-table">
            <thead>
              <tr>
                {header("last_seen", "Last seen")}
                {header("first_seen", "First seen")}
                {header("duration", "Duration")}
                {header("country", "Country")}
                <th>IP</th>
                <th>Device</th>
                <th>Came from</th>
                {header("matches", "Matches")}
                <th>Telegram</th>
                {header("visits", "Visitor")}
                {humansOnly ? null : <th>Filter</th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((v) => (
                <tr key={v.id}>
                  <td>{fmtTime(v.last_seen)}</td>
                  <td>{fmtTime(v.first_seen)}</td>
                  <td>
                    {fmtDuration(v.duration_seconds)}
                    <small>
                      {v.page_loads} load(s) · {v.heartbeats} ping(s)
                    </small>
                  </td>
                  <td>
                    {countryFlag(v.country)} {v.country || "?"}
                  </td>
                  <td>
                    <code>{v.ip || "?"}</code>
                  </td>
                  <td title={v.user_agent}>
                    {v.browser} · {v.os}
                    <small>{v.device}</small>
                  </td>
                  <td>
                    {v.referrer || "direct"}
                    {v.landing_path && v.landing_path !== "/" ? (
                      <small>{v.landing_path}</small>
                    ) : null}
                  </td>
                  <td title={v.matches.map(matchLabel).join("\n")}>
                    {v.matches.length || ""}
                    {v.matches.slice(0, 2).map((m) => (
                      <small key={m.match_id}>{matchLabel(m)}</small>
                    ))}
                    {v.matches.length > 2 ? <small>+{v.matches.length - 2} more</small> : null}
                  </td>
                  <td>
                    {v.telegram_free ? (
                      <span className="admin-result-pill is-confirmed">free</span>
                    ) : null}{" "}
                    {v.telegram_paid ? (
                      <span className="admin-result-pill is-confirmed">paid</span>
                    ) : null}
                  </td>
                  <td>
                    <span
                      className={`admin-result-pill ${v.returning ? "is-monitoring" : "is-confirmed"}`}
                    >
                      {v.returning ? "returning" : "new"}
                    </span>
                    <small>
                      {v.visit_count} visit(s)
                      {me && v.visitor_id === me ? " · you" : ""}
                    </small>
                  </td>
                  {humansOnly ? null : (
                    <td>
                      {v.likely_human ? (
                        <span className="admin-result-pill is-confirmed">human</span>
                      ) : (
                        <>
                          <span className="admin-result-pill is-expired">bot</span>
                          <small>{v.reasons.join(", ")}</small>
                        </>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          {!busy && rows.length === 0 ? (
            <p className="admin-hint">No visits in this range.</p>
          ) : null}
        </div>
      </article>
    </>
  );
}
