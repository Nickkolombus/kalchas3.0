import { useEffect, useState } from "react";
import type { ExtraCondition } from "./AdminConditions";

type CellPair = {
  home: number;
  away: number;
  home_triggered?: boolean;
  away_triggered?: boolean;
  match?: number | null;
};

export type PreviewMatch = {
  match_id: string;
  home_team: string;
  away_team: string;
  minute: number;
  score: string;
  league?: string | null;
  hot: number;
  strategy: CellPair;
  kscore: CellPair;
  baseline?: {
    strategy?: CellPair | null;
    kscore?: CellPair | null;
    hot?: number;
  };
};

const DIGITS: Record<string, number> = {
  pressure_index: 0,
  npei: 0,
  omega: 0,
  kscore: 0,
};

function fmt(value: number, digits: number, suffix = ""): string {
  if (!Number.isFinite(value)) return "–";
  return `${value.toFixed(digits)}${suffix}`;
}

function deltaClass(now: number, was: number | undefined, digits: number): string | null {
  if (was == null || Math.abs(now - was) < 10 ** -Math.max(digits, 1)) return null;
  return now - was > 0 ? "is-up" : "is-down";
}

function deltaText(now: number, was: number | undefined, digits: number): string | null {
  if (was == null || Math.abs(now - was) < 10 ** -Math.max(digits, 1)) return null;
  const diff = now - was;
  const sign = diff > 0 ? "+" : "";
  return `${sign}${diff.toFixed(digits)} vs saved`;
}

function MetricCell({
  now,
  was,
  digits,
  suffix,
  triggered,
}: {
  now: number;
  was?: number;
  digits: number;
  suffix?: string;
  triggered?: boolean;
}) {
  const change = deltaText(now, was, digits);
  const tone = deltaClass(now, was, digits);
  return (
    <div className="admin-preview-cell">
      <strong>
        {fmt(now, digits, suffix)}
        {triggered ? <span className="admin-preview-fire">Fire</span> : null}
      </strong>
      {change ? <small className={tone || undefined}>{change}</small> : null}
    </div>
  );
}

export function AdminPreview({
  strategy,
  short,
  weights,
  conditions,
  api,
}: {
  strategy: string;
  short: string;
  weights: Record<string, number>;
  conditions: ExtraCondition[];
  api: <T>(path: string, init?: RequestInit) => Promise<T>;
}) {
  const [matchId, setMatchId] = useState<string | null>(null);
  const [rows, setRows] = useState<PreviewMatch[]>([]);
  const [error, setError] = useState("");
  const digits = DIGITS[strategy] ?? 1;
  const suffix = strategy === "omega" ? "°" : "";

  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(() => {
      void (async () => {
        try {
          const body = await api<{ matches: PreviewMatch[] }>("/api/admin/preview", {
            method: "POST",
            body: JSON.stringify({
              strategy,
              weights,
              conditions,
              match_id: matchId,
            }),
          });
          if (cancelled) return;
          setRows(body.matches || []);
          setError("");
        } catch (err) {
          if (!cancelled) setError(err instanceof Error ? err.message : "preview failed");
        }
      })();
    }, 200);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [api, strategy, weights, conditions, matchId]);

  const selected = rows.find((row) => row.match_id === matchId) || rows[0] || null;
  const kNow = selected ? Number(selected.kscore.match ?? selected.hot) : 0;
  const kWas = selected?.baseline?.kscore?.match ?? selected?.baseline?.hot;
  const kChange = selected ? deltaText(kNow, kWas, 0) : null;
  const kTone = selected ? deltaClass(kNow, kWas, 0) : null;

  return (
    <aside className="admin-preview">
      <h2>Live preview</h2>
      <p className="admin-hint">
        Home and away for {short}, like that board column. K·idx is the match
        number. Green or red is the move vs the last saved weights.
      </p>
      {error ? <p className="admin-status">{error}</p> : null}
      {rows.length === 0 && !error ? (
        <p className="admin-hint">No live matches with a timeline to preview.</p>
      ) : null}
      <ul className="admin-preview-matches">
        {rows.map((row) => (
          <li key={row.match_id}>
            <button
              type="button"
              className={selected?.match_id === row.match_id ? "is-on" : ""}
              onClick={() => setMatchId(row.match_id)}
            >
              <span>
                {row.home_team} vs {row.away_team}
              </span>
              <small>
                {row.score} · {row.minute}′ · K {row.hot}
              </small>
            </button>
          </li>
        ))}
      </ul>
      {selected ? (
        <div className="admin-preview-board">
          <p className="admin-preview-fixture">
            {selected.home_team} vs {selected.away_team}
            <small>
              {selected.score} · {selected.minute}′
            </small>
          </p>
          <div className="admin-preview-grid">
            <span />
            <div className="admin-preview-side">
              <span>Home</span>
              <strong title={selected.home_team}>{selected.home_team}</strong>
            </div>
            <div className="admin-preview-side">
              <span>Away</span>
              <strong title={selected.away_team}>{selected.away_team}</strong>
            </div>
            <span className="admin-preview-metric">{short}</span>
            <MetricCell
              now={selected.strategy.home}
              was={selected.baseline?.strategy?.home}
              digits={digits}
              suffix={suffix}
              triggered={selected.strategy.home_triggered}
            />
            <MetricCell
              now={selected.strategy.away}
              was={selected.baseline?.strategy?.away}
              digits={digits}
              suffix={suffix}
              triggered={selected.strategy.away_triggered}
            />
          </div>
          <div className="admin-preview-k">
            <span>K·idx</span>
            <div className="admin-preview-cell">
              <strong>{Number.isFinite(kNow) ? kNow : "–"}</strong>
              {kChange ? <small className={kTone || undefined}>{kChange}</small> : null}
            </div>
          </div>
        </div>
      ) : null}
    </aside>
  );
}
