import { useCallback, useEffect, useState } from "react";

type LiveRow = {
  match_id: string;
  alert_time: string;
  api_home: string;
  api_away: string;
  event_name: string;
  market_type: string;
  selection_name: string;
  correlation_method: string;
  strategies: string[];
  minute?: number;
  score?: string;
};

type HistoryRow = LiveRow & { recorded_at: string | null };

type PollRow = {
  polled_at: string | null;
  row_count: number;
  user_agent: string;
};

type TipsPayload = {
  settings: {
    alert_window_seconds: number;
    last_polled_at: string | null;
    last_row_count: number;
    poll_count: number;
    updated_at: string | null;
  };
  feed_path: string;
  live: LiveRow[];
  history: HistoryRow[];
  polls: PollRow[];
};

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  return at.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function AdminTips({
  api,
}: {
  api: <T>(path: string, init?: RequestInit) => Promise<T>;
}) {
  const [days, setDays] = useState(1);
  const [windowSec, setWindowSec] = useState(1800);
  const [body, setBody] = useState<TipsPayload | null>(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const next = await api<TipsPayload>(`/api/admin/tips?days=${days}`);
      setBody(next);
      setWindowSec(next.settings.alert_window_seconds);
    } catch (err) {
      setError(err instanceof Error ? err.message : "load failed");
    } finally {
      setBusy(false);
    }
  }, [api, days]);

  useEffect(() => {
    void load();
  }, [load]);

  async function saveWindow() {
    setBusy(true);
    setStatus("");
    setError("");
    try {
      const saved = await api<{ ok: boolean; settings: TipsPayload["settings"] }>(
        "/api/admin/tips/settings",
        {
          method: "PUT",
          body: JSON.stringify({ alert_window_seconds: windowSec }),
        },
      );
      setStatus("Saved.");
      if (body) setBody({ ...body, settings: saved.settings });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "save failed");
    } finally {
      setBusy(false);
    }
  }

  const feedUrl =
    typeof window !== "undefined" ? `${window.location.origin}/tips.csv` : "/tips.csv";
  const settings = body?.settings;

  return (
    <>
      <header>
        <h1>Tips feed</h1>
        <p>
          CSV BFbot polls. One row per match from open alerts in the window.
          Names are the API-Football names until the Betfair map is ported.
        </p>
      </header>

      <article className="admin-card">
        <div className="admin-card-head">
          <h2>Poll URL</h2>
          <a href="/tips.csv" target="_blank" rel="noreferrer">
            Open /tips.csv
          </a>
        </div>
        <p className="admin-hint">
          Point BFbot at <code>{feedUrl}</code>. Header is Provider, EventName,
          MarketType, SelectionName, BetType.
        </p>
        <div className="admin-results-summary">
          <span>
            polls <strong>{settings?.poll_count ?? 0}</strong>
          </span>
          <span>
            last poll <strong>{fmtTime(settings?.last_polled_at) || "never"}</strong>
          </span>
          <span>
            last rows <strong>{settings?.last_row_count ?? 0}</strong>
          </span>
        </div>
      </article>

      <article className="admin-card">
        <h2>Inclusion window</h2>
        <p className="admin-hint">
          A tip stays in the CSV while it is still Monitoring and younger than
          this many seconds. 30 seconds was too short: alerts dropped out
          before BFbot (and this page) could see them.
        </p>
        <div className="admin-fields">
          <label>
            Seconds
            <input
              type="number"
              min={1}
              max={3600}
              value={windowSec}
              onChange={(event) => setWindowSec(Number(event.target.value))}
            />
          </label>
        </div>
        <div className="admin-actions">
          <button type="button" disabled={busy} onClick={() => void saveWindow()}>
            Save window
          </button>
          <button type="button" disabled={busy} onClick={() => void load()}>
            Refresh
          </button>
        </div>
        {status ? <p className="admin-status">{status}</p> : null}
        {error ? <p className="admin-status">{error}</p> : null}
      </article>

      <article className="admin-card">
        <div className="admin-card-head">
          <h2>In the window now</h2>
          <span className="admin-hint">{body?.live.length ?? 0} match(es)</span>
        </div>
        <div className="admin-results-table-wrap">
          <table className="admin-results-table">
            <thead>
              <tr>
                <th>API names</th>
                <th>EventName</th>
                <th>Market</th>
                <th>Map</th>
                <th>When</th>
              </tr>
            </thead>
            <tbody>
              {(body?.live || []).map((row) => (
                <tr key={row.match_id}>
                  <td>
                    {row.api_home} / {row.api_away}
                    <small>
                      {row.score || "0-0"} {row.minute ?? 0}′
                    </small>
                  </td>
                  <td>{row.event_name}</td>
                  <td>
                    <code>{row.market_type}</code>
                    <small>{row.selection_name}</small>
                    {row.strategies.length ? (
                      <small>{row.strategies.join(", ")}</small>
                    ) : null}
                  </td>
                  <td>{row.correlation_method}</td>
                  <td>{fmtTime(row.alert_time)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!busy && (body?.live || []).length === 0 ? (
            <p className="admin-hint">No open alerts in the window.</p>
          ) : null}
        </div>
      </article>

      <article className="admin-card">
        <div className="admin-card-head">
          <h2>First-seen log</h2>
          <label>
            Days
            <select value={days} onChange={(event) => setDays(Number(event.target.value))}>
              <option value={1}>1</option>
              <option value={3}>3</option>
              <option value={7}>7</option>
            </select>
          </label>
        </div>
        <p className="admin-hint">
          Written the first time a match appears in a live /tips.csv response.
        </p>
        <div className="admin-results-table-wrap">
          <table className="admin-results-table">
            <thead>
              <tr>
                <th>Recorded</th>
                <th>EventName</th>
                <th>Market</th>
                <th>Map</th>
              </tr>
            </thead>
            <tbody>
              {(body?.history || []).map((row) => (
                <tr key={`${row.match_id}-${row.alert_time}`}>
                  <td>{fmtTime(row.recorded_at)}</td>
                  <td>
                    {row.event_name}
                    <small>
                      {row.api_home} / {row.api_away}
                    </small>
                  </td>
                  <td>
                    <code>{row.market_type}</code>
                    <small>{row.selection_name}</small>
                  </td>
                  <td>{row.correlation_method}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!busy && (body?.history || []).length === 0 ? (
            <p className="admin-hint">Nothing served yet.</p>
          ) : null}
        </div>
      </article>

      <article className="admin-card">
        <h2>Recent polls</h2>
        <p className="admin-hint">Last 50 GETs of /tips.csv, including empty ones.</p>
        <div className="admin-results-table-wrap">
          <table className="admin-results-table">
            <thead>
              <tr>
                <th>When</th>
                <th>Rows</th>
                <th>User-Agent</th>
              </tr>
            </thead>
            <tbody>
              {(body?.polls || []).map((row, index) => (
                <tr key={`${row.polled_at}-${index}`}>
                  <td>{fmtTime(row.polled_at)}</td>
                  <td>{row.row_count}</td>
                  <td>
                    <small>{row.user_agent || ""}</small>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!busy && (body?.polls || []).length === 0 ? (
            <p className="admin-hint">No polls recorded yet.</p>
          ) : null}
        </div>
      </article>
    </>
  );
}
