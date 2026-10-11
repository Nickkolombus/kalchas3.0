import { useCallback, useEffect, useMemo, useState } from "react";

type SidePair = { home?: number | null; away?: number | null };

type ResultFactors = {
  status?: string | null;
  country?: string | null;
  sweet_spot?: boolean | null;
  half?: string | null;
  tslg?: string | null;
  tslg_home?: number | null;
  tslg_away?: number | null;
  odds_home?: number | null;
  odds_draw?: number | null;
  odds_away?: number | null;
  trigger_odds?: number | null;
  sot?: SidePair;
  da?: SidePair;
  urg?: SidePair;
  d5?: SidePair;
  d10?: SidePair;
  lbar?: SidePair;
  phi?: SidePair;
  omega?: SidePair;
  k?: SidePair;
  k_match?: number | null;
  also_firing?: string[];
  has_board?: boolean;
};

export type ResultItem = {
  id: number;
  match_id: string;
  strategy: string;
  slot: number;
  team: string | null;
  value: number;
  theta?: number | null;
  minute: number;
  score: string | null;
  home_team: string | null;
  away_team: string | null;
  league?: string | null;
  state: string;
  created_at: string | null;
  evaluated_at: string | null;
  settle_score?: string | null;
  settle_minute?: number | null;
  live: boolean;
  factors?: ResultFactors;
};

type PatternBlock = {
  title: string;
  rows: { label: string; n: number; confirmed: number; hit_rate: number }[];
};

type ResultsPayload = {
  summary: {
    total: number;
    confirmed: number;
    expired: number;
    monitoring: number;
    hit_rate: number | null;
  };
  patterns?: PatternBlock[];
  items: ResultItem[];
};

type StrategyChip = { key: string; short: string; name: string };

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function daysAgoIso(days: number): string {
  const at = new Date();
  at.setUTCDate(at.getUTCDate() - days);
  return at.toISOString().slice(0, 10);
}

function fmtTime(iso: string | null): string {
  if (!iso) return "";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  return at.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function pct(rate: number | null): string {
  if (rate == null) return "–";
  return `${Math.round(rate * 100)}%`;
}

function fmtNum(value: number | null | undefined, digits = 0): string {
  if (value == null || Number.isNaN(Number(value))) return "–";
  const n = Number(value);
  return Number.isInteger(n) && digits === 0 ? String(n) : n.toFixed(digits);
}

function sideVal(pair: SidePair | undefined, team: string | null, digits = 0): string {
  if (!pair) return "–";
  return fmtNum(team === "away" ? pair.away : pair.home, digits);
}

function triggerOdds(row: ResultItem): string {
  const factors = row.factors;
  if (!factors) return "–";
  if (factors.trigger_odds != null) return fmtNum(factors.trigger_odds, 2);
  if (row.team === "away") return fmtNum(factors.odds_away, 2);
  return fmtNum(factors.odds_home, 2);
}

export function AdminResults({
  strategies,
  selected,
  onToggle,
  api,
}: {
  strategies: StrategyChip[];
  selected: string[];
  onToggle: (key: string) => void;
  api: <T>(path: string, init?: RequestInit) => Promise<T>;
}) {
  const [since, setSince] = useState(() => daysAgoIso(7));
  const [until, setUntil] = useState(() => todayIso());
  const [state, setState] = useState("");
  const [team, setTeam] = useState("");
  const [league, setLeague] = useState("");
  const [body, setBody] = useState<ResultsPayload | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [csvBusy, setCsvBusy] = useState(false);

  const query = useMemo(() => {
    const params = new URLSearchParams();
    if (since) params.set("since", since);
    if (until) params.set("until", until);
    if (state) params.set("state", state);
    if (team) params.set("team", team);
    if (league.trim()) params.set("league", league.trim());
    for (const key of selected) params.append("strategy", key);
    params.set("limit", "100");
    return params.toString();
  }, [since, until, state, team, league, selected]);

  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const next = await api<ResultsPayload>(`/api/admin/results?${query}`);
      setBody(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "load failed");
    } finally {
      setBusy(false);
    }
  }, [api, query]);

  useEffect(() => {
    void load();
  }, [load]);

  const summary = body?.summary;

  async function downloadCsv() {
    setCsvBusy(true);
    setError("");
    try {
      const res = await fetch(`/api/admin/results.csv?${query}`, { credentials: "include" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "kalchas-results.csv";
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "csv failed");
    } finally {
      setCsvBusy(false);
    }
  }

  return (
    <>
      <header>
        <h1>Results</h1>
        <p>
          Fire-time board plus settle result. Changing confirmation rules does
          not rewrite these rows. Full K / Δ5 / Δ10 / Ω snapshots start on
          alerts after this deploy; older rows still have stats, odds, and TSLG.
        </p>
      </header>
      <nav className="admin-tabs" role="tablist" aria-label="Strategy filter">
        {strategies.map((row) => (
          <button
            key={row.key}
            type="button"
            role="tab"
            aria-selected={selected.length === 0 || selected.includes(row.key)}
            className={selected.length === 0 || selected.includes(row.key) ? "is-on" : ""}
            title={row.name}
            onClick={() => onToggle(row.key)}
          >
            {row.short}
          </button>
        ))}
      </nav>
      <p className="admin-hint">
        {selected.length === 0
          ? "All strategies. Click a chip to filter."
          : "Click a chip again to drop it. Click until none are selected for all."}
      </p>
      <div className="admin-results-filters">
        <label>
          From
          <input type="date" value={since} onChange={(event) => setSince(event.target.value)} />
        </label>
        <label>
          To
          <input type="date" value={until} onChange={(event) => setUntil(event.target.value)} />
        </label>
        <label>
          Result
          <select value={state} onChange={(event) => setState(event.target.value)}>
            <option value="">All</option>
            <option value="Confirmed">Confirmed</option>
            <option value="Expired">Expired</option>
            <option value="Monitoring">Monitoring</option>
          </select>
        </label>
        <label>
          Side
          <select value={team} onChange={(event) => setTeam(event.target.value)}>
            <option value="">Any</option>
            <option value="home">Home</option>
            <option value="away">Away</option>
          </select>
        </label>
        <label>
          League
          <input
            type="search"
            value={league}
            placeholder="contains"
            onChange={(event) => setLeague(event.target.value)}
          />
        </label>
      </div>
      <div className="admin-results-summary">
        <span>
          <strong>{summary?.total ?? 0}</strong> alerts
        </span>
        <span>
          <strong>{summary?.confirmed ?? 0}</strong> confirmed
        </span>
        <span>
          <strong>{summary?.expired ?? 0}</strong> expired
        </span>
        <span>
          <strong>{summary?.monitoring ?? 0}</strong> open
        </span>
        <span>
          hit rate <strong>{pct(summary?.hit_rate ?? null)}</strong>
        </span>
        <button type="button" disabled={csvBusy || busy} onClick={() => void downloadCsv()}>
          {csvBusy ? "CSV…" : "Download CSV"}
        </button>
      </div>
      {error ? <p className="admin-status">{error}</p> : null}
      {(body?.patterns || []).length ? (
        <div className="admin-pattern-grid">
          {(body?.patterns || []).map((block) => (
            <article key={block.title} className="admin-pattern-card">
              <h2>{block.title}</h2>
              <table>
                <thead>
                  <tr>
                    <th>Slice</th>
                    <th>n</th>
                    <th>Hit</th>
                  </tr>
                </thead>
                <tbody>
                  {block.rows.map((row) => (
                    <tr key={row.label}>
                      <td>{row.label}</td>
                      <td>{row.n}</td>
                      <td>{pct(row.hit_rate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </article>
          ))}
        </div>
      ) : null}
      <p className="admin-hint">
        Board columns are the trigger side at fire. CSV has both sides plus DA / SOT / possession.
      </p>
      <div className="admin-results-table-wrap">
        <table className="admin-results-table">
          <thead>
            <tr>
              <th>When</th>
              <th>Match</th>
              <th>Strategy</th>
              <th>Fire</th>
              <th>K</th>
              <th>Δ5</th>
              <th>Δ10</th>
              <th>Ω</th>
              <th>ΦI</th>
              <th>TSLG</th>
              <th>Odds</th>
              <th>Settle</th>
              <th>Result</th>
            </tr>
          </thead>
          <tbody>
            {(body?.items || []).map((row) => {
              const factors = row.factors;
              return (
                <tr key={row.id}>
                  <td>{fmtTime(row.created_at)}</td>
                  <td>
                    {row.live ? (
                      <a href={`/?match=${encodeURIComponent(row.match_id)}`}>
                        {row.home_team} vs {row.away_team}
                      </a>
                    ) : (
                      <>
                        {row.home_team} vs {row.away_team}
                      </>
                    )}
                    <small>
                      {[row.league, factors?.country, factors?.half, factors?.sweet_spot ? "sweet" : null]
                        .filter(Boolean)
                        .join(" · ")}
                    </small>
                  </td>
                  <td>
                    {strategies.find((item) => item.key === row.strategy)?.short || row.strategy}
                    {row.team ? ` · ${row.team}` : ""}
                    {factors?.also_firing?.length ? (
                      <small>
                        +{" "}
                        {factors.also_firing
                          .map((key) => strategies.find((item) => item.key === key)?.short || key)
                          .join(", ")}
                      </small>
                    ) : null}
                  </td>
                  <td>
                    {row.score || "–"} {row.minute}′
                    <small>{fmtNum(row.value, 1)}</small>
                  </td>
                  <td>{sideVal(factors?.k, row.team)}</td>
                  <td>{sideVal(factors?.d5, row.team, 1)}</td>
                  <td>{sideVal(factors?.d10, row.team)}</td>
                  <td>{sideVal(factors?.omega, row.team)}</td>
                  <td>{sideVal(factors?.phi, row.team)}</td>
                  <td>{factors?.tslg || "–"}</td>
                  <td>{triggerOdds(row)}</td>
                  <td>
                    {row.settle_score
                      ? `${row.settle_score}${
                          row.settle_minute != null ? ` ${row.settle_minute}′` : ""
                        }`
                      : "–"}
                  </td>
                  <td>
                    <span className={`admin-result-pill is-${row.state.toLowerCase()}`}>
                      {row.state}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {!busy && (body?.items || []).length === 0 ? (
          <p className="admin-hint">No alerts in this window yet.</p>
        ) : null}
      </div>
    </>
  );
}