import { useCallback, useEffect, useMemo, useState } from "react";

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
};

type ResultsPayload = {
  summary: {
    total: number;
    confirmed: number;
    expired: number;
    monitoring: number;
    hit_rate: number | null;
  };
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

  return (
    <>
      <header>
        <h1>Results</h1>
        <p>
          Settled Recent signals. Changing confirmation rules does not rewrite
          these rows. History starts when the scanner first settles an alert.
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
      </div>
      {error ? <p className="admin-status">{error}</p> : null}
      <div className="admin-results-table-wrap">
        <table className="admin-results-table">
          <thead>
            <tr>
              <th>When</th>
              <th>Match</th>
              <th>Strategy</th>
              <th>Fire</th>
              <th>Settle</th>
              <th>Result</th>
            </tr>
          </thead>
          <tbody>
            {(body?.items || []).map((row) => (
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
                  {row.league ? <small>{row.league}</small> : null}
                </td>
                <td>
                  {strategies.find((item) => item.key === row.strategy)?.short || row.strategy}
                  {row.team ? ` · ${row.team}` : ""}
                </td>
                <td>
                  {row.score || "–"} {row.minute}′
                </td>
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
            ))}
          </tbody>
        </table>
        {!busy && (body?.items || []).length === 0 ? (
          <p className="admin-hint">No alerts in this window yet.</p>
        ) : null}
      </div>
    </>
  );
}