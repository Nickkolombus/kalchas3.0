import { useCallback, useEffect, useMemo, useState, type MouseEvent } from "react";
import kalchasMark from "./assets/kalchas-mark.png";

type Watch = "strong" | "look" | "quiet";
type Day = "today" | "tomorrow";
type Record = { confirmed: number; settled: number };
type TeamRef = { name: string; badge?: string | null; position?: number | null };

type WatchRow = {
  match_id: string;
  kickoff: string;
  league_key: string;
  home: TeamRef;
  away: TeamRef;
  odds?: { home?: number | null; draw?: number | null; away?: number | null } | null;
  watch: Watch;
  score: number;
  headline: string;
  reason: string;
  tags: string[];
};

type LeagueGroup = {
  key: string;
  name: string;
  country: string;
  logo?: string | null;
  record?: Record | null;
  match_ids: string[];
};

type WatchlistDay = {
  status: "ready" | "preparing";
  day: string;
  built_at?: string | null;
  partial: boolean;
  matches: WatchRow[];
  leagues: LeagueGroup[];
  shortlist: string[];
  overall_record?: Record | null;
};

type PatternOut = { key: string; tag: string; title: string; detail: string; brief: string; score: number };
type Count = { count: number; n: number };
type PatternRow = {
  key: string;
  label: string;
  home: Count;
  away: Count;
  league_pct: number;
  h2h?: Count | null;
  flagged: boolean;
};
type FormGame = {
  match_date: string;
  opponent: string;
  venue: "H" | "A";
  goals_for: number;
  goals_against: number;
  result: "W" | "D" | "L";
};
type TeamForm = {
  games: number;
  source: "competition" | "all";
  wins: number;
  draws: number;
  losses: number;
  scored_per_game: number;
  conceded_per_game: number;
  clean_sheets: number;
  failed_to_score: number;
  results: FormGame[];
};
type TimingSide = { games: number; of: number; scored: number[]; conceded: number[] };
type MatchResearch = {
  match_id: string;
  day: string;
  built_at: string;
  kickoff: string;
  league: { id: number; name: string; country: string; logo?: string | null; round: string };
  home: { id: number; name: string; badge?: string | null; position?: number | null; points?: number | null };
  away: { id: number; name: string; badge?: string | null; position?: number | null; points?: number | null };
  odds?: {
    home?: number | null;
    draw?: number | null;
    away?: number | null;
    over_2_5?: number | null;
    under_2_5?: number | null;
    btts_yes?: number | null;
    btts_no?: number | null;
  } | null;
  watch: Watch;
  score: number;
  points: PatternOut[];
  patterns: PatternOut[];
  pattern_table: PatternRow[];
  form: { home: TeamForm; away: TeamForm };
  timing: { labels: string[]; home: TimingSide; away: TimingSide; note: string };
  h2h?: {
    sample: number;
    home_wins: number;
    draws: number;
    away_wins: number;
    avg_goals?: number | null;
    btts: number;
    over_2_5: number;
    meetings: { match_date: string; home_team: string; away_team: string; home_score: number; away_score: number }[];
  } | null;
  table: { position: number; team_id: number; team: string; played: number; goal_difference: number; points: number }[];
  record: { league?: Record | null; overall?: Record | null };
};

const WATCH_LABEL: { [K in Watch]: string } = {
  strong: "Strong watch",
  look: "Worth a look",
  quiet: "Quiet",
};
const MIN_RECORD = 10;

type Route = { day: Day; matchId: string | null };

function parseRoute(pathname: string): Route {
  const parts = pathname.replace(/\/+$/, "").split("/").filter(Boolean);
  const head = parts[0] === "today" ? "today" : "tomorrow";
  const id = parts[1] && /^\d+$/.test(parts[1]) ? parts[1] : null;
  return { day: head, matchId: id };
}

function routePath(route: Route): string {
  return route.matchId ? `/${route.day}/${route.matchId}` : `/${route.day}`;
}

export function isWatchlistPath(pathname: string): boolean {
  return /^\/(today|tomorrow)(\/\d+)?\/?$/.test(pathname);
}

function clock(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "";
  return at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

function dayLabel(iso: string): string {
  const at = new Date(`${iso}T12:00:00`);
  if (Number.isNaN(at.getTime())) return iso;
  return at.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
}

function shortDate(iso: string): string {
  const at = new Date(`${iso}T12:00:00`);
  if (Number.isNaN(at.getTime())) return iso;
  return at.toLocaleDateString([], { day: "numeric", month: "short", year: "2-digit" });
}

function pct(record: Record): number {
  return Math.round((record.confirmed / record.settled) * 100);
}

function price(value?: number | null): string {
  return value ? value.toFixed(2) : "–";
}

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

function ordinal(n: number): string {
  const tail = n % 100 >= 11 && n % 100 <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" } as { [k: number]: string })[n % 10] ?? "th";
  return `${n}${tail}`;
}

function Crest({ src, name, size = 18 }: { src?: string | null; name: string; size?: number }) {
  const [broken, setBroken] = useState(false);
  if (!src || broken) {
    return (
      <span className="wl-crest wl-crest-blank" style={{ width: size, height: size, fontSize: size * 0.45 }} aria-hidden>
        {name.slice(0, 1)}
      </span>
    );
  }
  return (
    <img
      className="wl-crest"
      src={src}
      alt=""
      width={size}
      height={size}
      loading="lazy"
      onError={() => setBroken(true)}
    />
  );
}

function WatchMark({ watch }: { watch: Watch }) {
  return (
    <span className={`wl-watch is-${watch}`}>
      <i />
      {WATCH_LABEL[watch]}
    </span>
  );
}

function useJson<T>(url: string | null): { data: T | null; error: string | null; loading: boolean } {
  const [state, setState] = useState<{ data: T | null; error: string | null; loading: boolean }>({
    data: null,
    error: null,
    loading: Boolean(url),
  });
  useEffect(() => {
    if (!url) return;
    let alive = true;
    setState({ data: null, error: null, loading: true });
    fetch(url)
      .then(async (res) => {
        if (!res.ok) throw new Error(res.status === 404 ? "not_found" : `HTTP ${res.status}`);
        return (await res.json()) as T;
      })
      .then((data) => alive && setState({ data, error: null, loading: false }))
      .catch((err: Error) => alive && setState({ data: null, error: err.message, loading: false }));
    return () => {
      alive = false;
    };
  }, [url]);
  return state;
}

/* ------------------------------------------------------------------ list */

type Filter = "all" | "strong" | "look";

function DayView({ day, onOpen, onDay }: { day: Day; onOpen: (id: string) => void; onDay: (d: Day) => void }) {
  const { data, error, loading } = useJson<WatchlistDay>(`/api/watchlist/day/${day}`);
  const [filter, setFilter] = useState<Filter>("all");

  const byId = useMemo(() => new Map((data?.matches ?? []).map((m) => [m.match_id, m])), [data]);
  const counts = useMemo(() => {
    const out = { all: 0, strong: 0, look: 0 };
    for (const m of data?.matches ?? []) {
      out.all += 1;
      if (m.watch === "strong") out.strong += 1;
      if (m.watch === "look") out.look += 1;
    }
    return out;
  }, [data]);

  const shown = (m: WatchRow) => filter === "all" || m.watch === filter;
  const picks = (data?.shortlist ?? []).map((id) => byId.get(id)).filter((m): m is WatchRow => Boolean(m));
  const title = day === "tomorrow" ? "Tomorrow's watchlist" : "Today's watchlist";

  return (
    <>
      <div className="wl-intro">
        <h1>{title}</h1>
        <p>
          Every match bookmakers price, checked for the same patterns: both teams scoring, goals, late goals,
          first-half goals, clean sheets and scoring runs. Each team's last 10 games are compared with their
          league's average, and the matches where something stands out come first.
        </p>
      </div>

      <div className="wl-card">
        <div className="wl-bar">
          <div className="wl-tabs" role="tablist" aria-label="Day">
            {(["today", "tomorrow"] as const).map((d) => (
              <button
                key={d}
                type="button"
                role="tab"
                aria-selected={day === d}
                className={day === d ? "on" : ""}
                onClick={() => onDay(d)}
              >
                {d === "today" ? "Today" : "Tomorrow"}
                {data?.day && day === d ? <span> · {dayLabel(data.day)}</span> : null}
              </button>
            ))}
          </div>
          {data?.status === "ready" ? (
            <div className="wl-filters" role="group" aria-label="Filter">
              {(
                [
                  ["all", `All ${counts.all}`],
                  ["strong", `Strong watch ${counts.strong}`],
                  ["look", `Worth a look ${counts.look}`],
                ] as const
              ).map(([key, label]) => (
                <button key={key} type="button" className={filter === key ? "on" : ""} onClick={() => setFilter(key)}>
                  {label}
                </button>
              ))}
            </div>
          ) : null}
        </div>

        {loading ? <p className="wl-empty">Loading…</p> : null}
        {error ? <p className="wl-empty">The watchlist is unavailable right now. Try again in a minute.</p> : null}
        {data?.status === "preparing" ? (
          <p className="wl-empty">
            {day === "tomorrow" ? "Tomorrow's" : "Today's"} list is still being put together. Check back in a few
            minutes.
          </p>
        ) : null}
        {data?.status === "ready" && !data.matches.length ? (
          <p className="wl-empty">No priced matches on this day.</p>
        ) : null}

        {data?.status === "ready" && picks.length && filter === "all" ? (
          <section className="wl-picks" aria-label="Top picks">
            <h2>{picks.length === 1 ? "One to have open" : `${picks.length} to have open`}</h2>
            {picks.map((m, i) => (
              <a key={m.match_id} className="wl-pick" href={`/${day}/${m.match_id}`} onClick={linkTo(() => onOpen(m.match_id))}>
                <span className="wl-pick-n">{i + 1}</span>
                <div className="wl-pick-body">
                  <div className="wl-pick-teams">
                    <Crest src={m.home.badge} name={m.home.name} />
                    {m.home.name} v {m.away.name}
                    <small>{leagueName(data, m.league_key)}</small>
                  </div>
                  <p>
                    <b>{m.headline}</b> {m.reason}
                  </p>
                  <div className="wl-tags">
                    {m.tags.map((t) => (
                      <span key={t} className="wl-tag">
                        {t}
                      </span>
                    ))}
                  </div>
                </div>
                <span className="wl-pick-time">{clock(m.kickoff)}</span>
              </a>
            ))}
          </section>
        ) : null}

        {data?.status === "ready"
          ? data.leagues.map((league) => {
              const rows = league.match_ids
                .map((id) => byId.get(id))
                .filter((m): m is WatchRow => Boolean(m) && shown(m as WatchRow))
                .sort((a, b) => a.kickoff.localeCompare(b.kickoff));
              if (!rows.length) return null;
              return (
                <section key={league.key} className="wl-league">
                  <header className="wl-league-head">
                    <b>
                      {league.logo ? <Crest src={league.logo} name={league.name} size={16} /> : null}
                      {league.country} · {league.name}
                    </b>
                    {league.record && league.record.settled >= MIN_RECORD ? (
                      <span>
                        Our live alerts here: <em>{pct(league.record)}% landed</em> ({league.record.confirmed} of{" "}
                        {league.record.settled})
                      </span>
                    ) : null}
                  </header>
                  {rows.map((m) => (
                    <a key={m.match_id} className="wl-row" href={`/${day}/${m.match_id}`} onClick={linkTo(() => onOpen(m.match_id))}>
                      <span className="wl-time">{clock(m.kickoff)}</span>
                      <div className="wl-teams">
                        {[m.home, m.away].map((t) => (
                          <div key={t.name}>
                            <Crest src={t.badge} name={t.name} />
                            <span className="wl-name">{t.name}</span>
                            {t.position ? <span className="wl-pos">{ordinal(t.position)}</span> : null}
                          </div>
                        ))}
                      </div>
                      <div className="wl-odds" aria-label="Match odds">
                        {(["home", "draw", "away"] as const).map((k, idx) => (
                          <span key={k}>
                            <b>{["1", "X", "2"][idx]}</b>
                            {price(m.odds?.[k])}
                          </span>
                        ))}
                      </div>
                      <div className="wl-why">{m.reason || "Nothing stands out against the league norm."}</div>
                      <div className="wl-end">
                        <WatchMark watch={m.watch} />
                      </div>
                    </a>
                  ))}
                </section>
              );
            })
          : null}

        {data?.status === "ready" ? (
          <p className="wl-foot">
            {data.built_at ? `Updated ${clock(data.built_at)}. ` : ""}
            Kick-off times in your time zone.
            {data.partial ? " Some leagues are still loading and will appear at the next update." : ""}
          </p>
        ) : null}
      </div>
    </>
  );
}

function leagueName(day: WatchlistDay, key: string): string {
  return day.leagues.find((l) => l.key === key)?.name ?? "";
}

function linkTo(go: () => void) {
  return (event: MouseEvent<HTMLAnchorElement>) => {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    event.preventDefault();
    go();
  };
}

/* ------------------------------------------------------------ match page */

function FormPills({ form }: { form: TeamForm }) {
  return (
    <div className="wl-pills">
      {form.results.map((g) => (
        <span
          key={`${g.match_date}-${g.opponent}`}
          className={`wl-pill is-${g.result.toLowerCase()}`}
          title={`${g.venue === "H" ? "v" : "at"} ${g.opponent}, ${shortDate(g.match_date)}`}
        >
          {g.result}
          <small>
            {g.goals_for}–{g.goals_against}
          </small>
        </span>
      ))}
    </div>
  );
}

function CountCell({ value }: { value: Count }) {
  if (!value.n) return <td className="wl-num">–</td>;
  const share = Math.round((value.count / value.n) * 100);
  return (
    <td className="wl-num">
      {value.count}/{value.n}
      <span className="wl-mini" aria-hidden>
        <i style={{ width: `${share}%` }} />
      </span>
    </td>
  );
}

function TimingChart({ research }: { research: MatchResearch }) {
  const { timing, home, away } = research;
  const rows = timing.labels.map((label, i) => ({
    label,
    home: [timing.home.scored[i], timing.home.conceded[i]] as const,
    away: [timing.away.scored[i], timing.away.conceded[i]] as const,
  }));
  const max = Math.max(1, ...rows.map((r) => Math.max(r.home[0] + r.home[1], r.away[0] + r.away[1])));
  const unit = 100 / max;
  const bars = (pair: readonly [number, number], side: "l" | "r") => {
    const total = pair[0] + pair[1];
    return (
      <div className={`wl-bars is-${side}`}>
        {side === "l" ? <em>{total || ""}</em> : null}
        <span style={{ width: `${pair[1] * unit}%` }} className="ag" />
        <span style={{ width: `${pair[0] * unit}%` }} className="for" />
        {side === "r" ? <em>{total || ""}</em> : null}
      </div>
    );
  };
  if (timing.home.games < 3 || timing.away.games < 3) {
    return <p className="wl-sub">Not enough timed goals from the provider for these teams yet.</p>;
  }
  return (
    <>
      <div className="wl-legend">
        <span>
          <i className="k-for" />
          Scored
        </span>
        <span>
          <i className="k-ag" />
          Conceded
        </span>
      </div>
      <div className="wl-tm-head">
        <span>{home.name}</span>
        <span />
        <span>{away.name}</span>
      </div>
      {rows.map((r, i) => (
        <div key={r.label} className="wl-tm">
          {bars(r.home, "l")}
          <div className={`wl-tm-lab${i === rows.length - 1 ? " is-late" : ""}`}>{r.label}</div>
          {bars(r.away, "r")}
        </div>
      ))}
      {timing.home.games < timing.home.of || timing.away.games < timing.away.of ? (
        <p className="wl-sub wl-tm-n">
          Only games with goal times count: {timing.home.games} of {home.name}'s last {timing.home.of} and{" "}
          {timing.away.games} of {away.name}'s last {timing.away.of}.
        </p>
      ) : null}
      {timing.note ? <p className="wl-callout">{timing.note}</p> : null}
    </>
  );
}

function RecordLine({ label, record, overall }: { label: string; record: Record; overall?: Record | null }) {
  const share = pct(record);
  return (
    <div className="wl-rec">
      <p>
        {label}: <b>{record.confirmed} of {record.settled}</b> landed ({share}%).
      </p>
      <div className="wl-cmp">
        <i style={{ width: `${share}%` }} />
        {overall ? <u style={{ left: `${pct(overall)}%` }} title="Our overall average" /> : null}
      </div>
    </div>
  );
}

function MatchView({ matchId, day, onBack }: { matchId: string; day: Day; onBack: () => void }) {
  const { data, error, loading } = useJson<MatchResearch>(`/api/watchlist/match/${matchId}`);

  if (loading) return <p className="wl-empty">Loading…</p>;
  if (error || !data) {
    return (
      <div className="wl-card">
        <p className="wl-empty">
          {error === "not_found"
            ? "This match isn't on the watchlist any more. Lists cover today and tomorrow."
            : "The match page is unavailable right now. Try again in a minute."}
        </p>
        <p className="wl-empty">
          <a href={`/${day}`} onClick={linkTo(onBack)}>
            Back to the list
          </a>
        </p>
      </div>
    );
  }

  const { home, away, odds, form, h2h, table, record } = data;
  const formSource = (f: TeamForm) =>
    f.source === "all" ? "all competitions" : data.league.name.split(" - ")[0];

  return (
    <div className="wl-card">
      <header className="wl-mhead">
        <div className="wl-crumb">
          <a href={`/${day}`} onClick={linkTo(onBack)}>
            ← {day === "tomorrow" ? "Tomorrow" : "Today"}
          </a>
          <span>
            {data.league.country} · {data.league.name}
            {data.league.round ? ` · Round ${data.league.round}` : ""}
          </span>
        </div>
        <div className="wl-vs">
          <div className="wl-side">
            <Crest src={home.badge} name={home.name} size={44} />
            <div>
              <b>{home.name}</b>
              {home.position ? (
                <span>
                  {ordinal(home.position)}
                  {home.points != null ? ` · ${home.points} pts` : ""}
                </span>
              ) : null}
            </div>
          </div>
          <div className="wl-ko">
            <b>{clock(data.kickoff)}</b>
            <span>{dayLabel(data.day)}</span>
          </div>
          <div className="wl-side is-away">
            <div>
              <b>{away.name}</b>
              {away.position ? (
                <span>
                  {ordinal(away.position)}
                  {away.points != null ? ` · ${away.points} pts` : ""}
                </span>
              ) : null}
            </div>
            <Crest src={away.badge} name={away.name} size={44} />
          </div>
        </div>
        {odds ? (
          <div className="wl-mprices">
            <span>
              {home.name} <b>{price(odds.home)}</b>
            </span>
            <span>
              Draw <b>{price(odds.draw)}</b>
            </span>
            <span>
              {away.name} <b>{price(odds.away)}</b>
            </span>
            {odds.over_2_5 ? (
              <span>
                Over 2.5 <b>{price(odds.over_2_5)}</b>
              </span>
            ) : null}
            {odds.btts_yes ? (
              <span>
                Both score <b>{price(odds.btts_yes)}</b>
              </span>
            ) : null}
          </div>
        ) : null}
      </header>

      <div className="wl-mbody">
        <div className="wl-col">
          <section className="wl-sec">
            <div className="wl-sec-head">
              <h3>What to watch</h3>
              <WatchMark watch={data.watch} />
            </div>
            {data.points.length ? (
              <ol className="wl-points">
                {data.points.map((p, i) => (
                  <li key={p.key} data-n={i + 1}>
                    <div>
                      <b>{p.title}</b> <span>{p.detail}</span>
                    </div>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="wl-sub">
                Nothing stands out: both teams' recent games look like a normal game in this league.
              </p>
            )}
          </section>

          <section className="wl-sec">
            <h3>Every pattern, side by side</h3>
            <p className="wl-sub">
              How often each happened in the teams' last games, against the league average. Highlighted rows are
              the ones above.
            </p>
            <div className="wl-table-wrap">
              <table className="wl-ptable">
                <thead>
                  <tr>
                    <th />
                    <th className="wl-num">{home.name}</th>
                    <th className="wl-num">{away.name}</th>
                    <th className="wl-num">League</th>
                    <th className="wl-num">Meetings</th>
                  </tr>
                </thead>
                <tbody>
                  {data.pattern_table.map((row) => (
                    <tr key={row.key} className={row.flagged ? "is-flagged" : ""}>
                      <th scope="row">{row.label}</th>
                      <CountCell value={row.home} />
                      <CountCell value={row.away} />
                      <td className="wl-num">{row.league_pct}%</td>
                      <td className="wl-num">{row.h2h ? `${row.h2h.count}/${row.h2h.n}` : "–"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="wl-sec">
            <h3>Recent form</h3>
            <p className="wl-sub">Last 6 games, newest on the left. Hover a result for the opponent.</p>
            {(["home", "away"] as const).map((side) => {
              const team = side === "home" ? home : away;
              const f = form[side];
              return (
                <div key={side} className="wl-form-row">
                  <div className="wl-who">
                    <Crest src={team.badge} name={team.name} />
                    {team.name}
                  </div>
                  <FormPills form={f} />
                </div>
              );
            })}
            <div className="wl-form-sum">
              {(["home", "away"] as const).map((side) => {
                const team = side === "home" ? home : away;
                const f = form[side];
                return (
                  <div key={side}>
                    <b>{team.name}</b> score {f.scored_per_game} and concede {f.conceded_per_game} a game.{" "}
                    {plural(f.wins, "win")}, {plural(f.draws, "draw")}, {plural(f.losses, "defeat")} in their last{" "}
                    {f.games} ({formSource(f)}).
                  </div>
                );
              })}
            </div>
          </section>

          <section className="wl-sec">
            <h3>When the goals come</h3>
            <p className="wl-sub">Goals for and against in each team's recent games, by part of the match.</p>
            <TimingChart research={data} />
          </section>
        </div>

        <div className="wl-col">
          <section className="wl-sec">
            <h3>Head-to-head</h3>
            {h2h && h2h.sample ? (
              <>
                <p className="wl-sub">
                  Last {h2h.sample === 1 ? "meeting" : `${h2h.sample} meetings`}
                  {h2h.avg_goals != null ? `, ${h2h.avg_goals} goals a game` : ""}.
                </p>
                <div className="wl-split" aria-hidden>
                  <i className="h" style={{ flex: h2h.home_wins || 0.001 }} />
                  <i className="d" style={{ flex: h2h.draws || 0.001 }} />
                  <i className="a" style={{ flex: h2h.away_wins || 0.001 }} />
                </div>
                <div className="wl-split-keys">
                  <span>
                    <b>{h2h.home_wins}</b> {home.name}
                  </span>
                  <span>
                    <b>{h2h.draws}</b> {h2h.draws === 1 ? "draw" : "draws"}
                  </span>
                  <span>
                    <b>{h2h.away_wins}</b> {away.name}
                  </span>
                </div>
                {h2h.meetings.map((m) => (
                  <div key={`${m.match_date}-${m.home_team}`} className="wl-meet">
                    <span className="d">{shortDate(m.match_date)}</span>
                    <span className="h">{m.home_team}</span>
                    <span className="s">
                      {m.home_score}–{m.away_score}
                    </span>
                    <span>{m.away_team}</span>
                  </div>
                ))}
              </>
            ) : (
              <p className="wl-sub">No recent meetings on record.</p>
            )}
          </section>

          {table.length ? (
            <section className="wl-sec">
              <h3>Table</h3>
              <table className="wl-ltable">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Team</th>
                    <th className="wl-num">P</th>
                    <th className="wl-num">GD</th>
                    <th className="wl-num">Pts</th>
                  </tr>
                </thead>
                <tbody>
                  {table.map((row, i) => {
                    const gap = i > 0 && row.position - table[i - 1].position > 1;
                    const mine = row.team_id === home.id || row.team_id === away.id;
                    return [
                      gap ? (
                        <tr key={`gap-${row.position}`} className="wl-gap">
                          <td colSpan={5}>· · ·</td>
                        </tr>
                      ) : null,
                      <tr key={row.team_id} className={mine ? "is-me" : ""}>
                        <td>{row.position}</td>
                        <td>{row.team}</td>
                        <td className="wl-num">{row.played}</td>
                        <td className="wl-num">
                          {row.goal_difference > 0 ? `+${row.goal_difference}` : row.goal_difference}
                        </td>
                        <td className="wl-num">{row.points}</td>
                      </tr>,
                    ];
                  })}
                </tbody>
              </table>
            </section>
          ) : null}

          {record.league && record.league.settled >= MIN_RECORD ? (
            <section className="wl-sec">
              <h3>Our live alerts in this league</h3>
              <p className="wl-sub">
                Last six months, settled alerts only.
                {record.overall ? ` The line marks our overall average (${pct(record.overall)}%).` : ""}
              </p>
              <RecordLine label={data.league.name.split(" - ")[0]} record={record.league} overall={record.overall} />
            </section>
          ) : null}

          <section className="wl-sec">
            <p className="wl-sub">
              Updated {clock(data.built_at)}. Patterns come from results only. Team news and line-ups are not
              included yet, so check them before kick-off.
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ app */

export function WatchlistApp() {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.pathname));

  useEffect(() => {
    const onPop = () => setRoute(parseRoute(window.location.pathname));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const go = useCallback((next: Route) => {
    window.history.pushState(null, "", routePath(next));
    setRoute(next);
    window.scrollTo({ top: 0 });
  }, []);

  useEffect(() => {
    document.title = route.matchId ? "Match research · Kalchas" : "Watchlist · Kalchas";
  }, [route.matchId]);

  return (
    <div className="wl-shell">
      <header className="wl-top">
        <a className="wl-brand" href="/">
          <img src={kalchasMark} alt="" width={28} height={28} />
          Kalchas
        </a>
        <a className="wl-live" href="/">
          Live board →
        </a>
      </header>
      {route.matchId ? (
        <MatchView matchId={route.matchId} day={route.day} onBack={() => go({ day: route.day, matchId: null })} />
      ) : (
        <DayView
          day={route.day}
          onOpen={(id) => go({ day: route.day, matchId: id })}
          onDay={(d) => go({ day: d, matchId: null })}
        />
      )}
    </div>
  );
}
