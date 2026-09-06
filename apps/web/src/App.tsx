import { useEffect, useState } from "react";
import liveFull from "../mocks/live_full.json";

type MatchRow = {
  match_id: string;
  home_team: string;
  away_team: string;
  minute: number;
  score: string;
  league?: string;
};

export function App() {
  const [matches, setMatches] = useState<MatchRow[]>([]);
  const [source, setSource] = useState("mock");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/live");
        if (res.ok) {
          const body = await res.json();
          if (!cancelled && Array.isArray(body.matches)) {
            setMatches(body.matches);
            setSource("api");
            return;
          }
        }
      } catch {
        /* fall through to mock */
      }
      if (!cancelled) {
        setMatches((liveFull as { matches: MatchRow[] }).matches ?? []);
        setSource("mock");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="shell">
      <header className="hero">
        <p className="brand">Kalchas</p>
        <h1>Live strategies</h1>
        <p className="lede">
          Dashboard scaffold reading mock fixtures until the OpenAPI live
          contract is wired.
        </p>
      </header>
      <p className="meta">source: {source}</p>
      <ul className="match-list">
        {matches.map((m) => (
          <li key={m.match_id}>
            <span className="teams">
              {m.home_team} vs {m.away_team}
            </span>
            <span className="score">{m.score}</span>
            <span className="minute">{m.minute}&apos;</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
