import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { BrandIdentity } from "./BrandHero";
import { liveNote, liveVerdict } from "./WatchlistPicks";
import { logVisitEvent, pingVisit, visitorId, type VisitEvent } from "./visit";

type Watch = "strong" | "look" | "quiet";
type Outcome = "landed" | "missed";
type DayKey = string; // "today" | "tomorrow" | "YYYY-MM-DD"
type TeamRef = { name: string; badge?: string | null; position?: number | null };
type Tally = { landed: number; settled: number };

type RowResult = {
  status: "finished" | "off";
  label: string;
  home?: number | null;
  away?: number | null;
  pens?: number[] | null;
};

type WatchRow = {
  match_id: string;
  kickoff: string;
  league_key: string;
  home: TeamRef;
  away: TeamRef;
  odds?: { home?: number | null; draw?: number | null; away?: number | null } | null;
  watch: Watch;
  score: number;
  lead_key?: string;
  headline: string;
  reason: string;
  tags: { label: string; outcome?: Outcome | null }[];
  result?: RowResult | null;
  outcome?: Outcome | null;
  outcome_note?: string;
};

type LeagueGroup = {
  key: string;
  name: string;
  country: string;
  logo?: string | null;
  match_ids: string[];
};

type DaySummary = {
  matches: number;
  strong: number;
  look: number;
  finished: number;
  called_off: number;
  top: Tally;
  strong_tally: Tally;
  look_tally: Tally;
};

type WatchlistDay = {
  status: "ready" | "preparing" | "none";
  day: string;
  today: string;
  first_day?: string | null;
  built_at?: string | null;
  partial: boolean;
  matches: WatchRow[];
  leagues: LeagueGroup[];
  shortlist: string[];
  summary?: DaySummary | null;
};

type WatchlistMonth = {
  month: string;
  today: string;
  first_day?: string | null;
  days: { day: string; summary: DaySummary }[];
};

type PatternOut = {
  key: string;
  tag: string;
  title: string;
  detail: string;
  brief: string;
  score: number;
  outcome?: Outcome | null;
  outcome_note?: string;
};
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
type MatchResult = RowResult & {
  home_90?: number | null;
  away_90?: number | null;
  ht?: number[] | null;
  timed?: boolean;
  goals?: { time: string; half: string; side: string }[];
};
export type MatchResearch = {
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
  shots?: { home?: TeamShots | null; away?: TeamShots | null } | null;
  result?: MatchResult | null;
};
type ShotLine = { stat: "shots" | "on_target"; at_least: number; hits: number };
type Shooter = {
  name: string;
  apps: number;
  minutes: number;
  shots: number[];
  per_90: number;
  on_target_per_90: number;
  lines: ShotLine[];
};
type TeamShots = { games: number; source: "competition" | "all"; players: Shooter[] };

const WATCH_LABEL: { [K in Watch]: string } = {
  strong: "Strong watch",
  look: "Worth a look",
  quiet: "Quiet",
};

/* ---------------------------------------------------------------- routes */

type Route =
  | { view: "day"; day: DayKey }
  | { view: "match"; day: DayKey; matchId: string }
  | { view: "calendar"; month: string | null }
  | { view: "parlay"; day: DayKey };

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;
const ISO_MONTH = /^\d{4}-\d{2}$/;

function isDayKey(part: string | undefined): part is string {
  return part === "today" || part === "tomorrow" || ISO_DAY.test(part ?? "");
}

function parseRoute(pathname: string): Route {
  const parts = pathname.replace(/\/+$/, "").split("/").filter(Boolean);
  if (parts[0] === "calendar") {
    return { view: "calendar", month: parts[1] && ISO_MONTH.test(parts[1]) ? parts[1] : null };
  }
  if (parts[0] === "parlay") return { view: "parlay", day: isDayKey(parts[1]) ? parts[1] : "today" };
  const day = isDayKey(parts[0]) ? parts[0] : "tomorrow";
  if (parts[1] && /^\d+$/.test(parts[1])) return { view: "match", day, matchId: parts[1] };
  return { view: "day", day };
}

function routePath(route: Route): string {
  if (route.view === "calendar") return route.month ? `/calendar/${route.month}` : "/calendar";
  if (route.view === "match") return `/${route.day}/${route.matchId}`;
  if (route.view === "parlay") return route.day === "today" ? "/parlay" : `/parlay/${route.day}`;
  return `/${route.day}`;
}

const VISIT_PING_MS = 30_000;

function visitEventFor(route: Route): VisitEvent | null {
  if (route.view === "match") return "wl_match";
  if (route.view === "calendar") return "wl_calendar";
  if (route.view === "parlay") return null;
  if (route.day === "tomorrow") return "wl_tomorrow";
  return route.day === "today" ? null : "wl_past";
}

export function isWatchlistPath(pathname: string): boolean {
  return (
    /^\/(today|tomorrow|\d{4}-\d{2}-\d{2})(\/\d+)?\/?$/.test(pathname) ||
    /^\/calendar(\/\d{4}-\d{2})?\/?$/.test(pathname) ||
    /^\/parlay(\/(today|tomorrow|\d{4}-\d{2}-\d{2}))?\/?$/.test(pathname)
  );
}

function addDays(iso: string, days: number): string {
  const at = new Date(`${iso}T12:00:00Z`);
  at.setUTCDate(at.getUTCDate() + days);
  return at.toISOString().slice(0, 10);
}

/** "today" / "tomorrow" for those two dates, so their links stay friendly. */
function dayKey(iso: string, today: string): DayKey {
  if (iso === today) return "today";
  if (iso === addDays(today, 1)) return "tomorrow";
  return iso;
}

/* -------------------------------------------------------------- helpers */

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

function longDay(iso: string): string {
  const at = new Date(`${iso}T12:00:00`);
  if (Number.isNaN(at.getTime())) return iso;
  return at.toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" });
}

function shortDate(iso: string): string {
  const at = new Date(`${iso}T12:00:00`);
  if (Number.isNaN(at.getTime())) return iso;
  return at.toLocaleDateString([], { day: "numeric", month: "short", year: "2-digit" });
}

function monthLabel(month: string): string {
  const at = new Date(`${month}-15T12:00:00`);
  return at.toLocaleDateString([], { month: "long", year: "numeric" });
}

function addMonths(month: string, n: number): string {
  const [y, m] = month.split("-").map(Number);
  const at = new Date(Date.UTC(y, m - 1 + n, 15));
  return at.toISOString().slice(0, 7);
}

function price(value?: number | null): string {
  return value ? value.toFixed(2) : "–";
}

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : /(ch|sh|s|x)$/.test(word) ? "es" : "s"}`;
}

function ordinal(n: number): string {
  const tail = n % 100 >= 11 && n % 100 <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" } as { [k: number]: string })[n % 10] ?? "th";
  return `${n}${tail}`;
}

function addTally(a: Tally, b: Tally): Tally {
  return { landed: a.landed + b.landed, settled: a.settled + b.settled };
}

function scoreText(r: RowResult): string {
  return r.home != null && r.away != null ? `${r.home}–${r.away}` : "";
}

function resultLabel(r: RowResult): string {
  if (r.status === "off") return r.label;
  if (r.label === "Pens" && r.pens) return `Pens ${r.pens[0]}–${r.pens[1]}`;
  return r.label;
}

function isTyping(event: KeyboardEvent): boolean {
  const el = event.target as HTMLElement | null;
  return Boolean(el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)));
}

/* ------------------------------------------------------------ data cache */

/**
 * Every response is kept for the visit, so going back, stepping days or
 * flicking between matches shows the page at once. Anything older than a
 * minute is shown as it is and quietly refreshed.
 */
type Entry = { at: number; data?: unknown; promise?: Promise<unknown> };
const responses = new Map<string, Entry>();
const FRESH_MS = 60_000;

function load<T>(url: string, force = false): Promise<T> {
  const hit = responses.get(url);
  if (hit?.promise) return hit.promise as Promise<T>;
  if (!force && hit && hit.data !== undefined && Date.now() - hit.at < FRESH_MS) return Promise.resolve(hit.data as T);
  const entry: Entry = { at: Date.now(), data: hit?.data };
  entry.promise = fetch(url)
    .then(async (res) => {
      if (!res.ok) throw new Error(res.status === 404 ? "not_found" : `HTTP ${res.status}`);
      return res.json();
    })
    .then((data) => {
      entry.data = data;
      entry.at = Date.now();
      entry.promise = undefined;
      return data;
    })
    .catch((err) => {
      entry.promise = undefined;
      if (entry.data === undefined) responses.delete(url);
      throw err;
    });
  responses.set(url, entry);
  return entry.promise as Promise<T>;
}

function prefetch(url: string): void {
  load(url).catch(() => undefined);
}

function cached<T>(url: string | null): T | null {
  const hit = url ? responses.get(url) : undefined;
  return hit && hit.data !== undefined ? (hit.data as T) : null;
}

/** `refreshMs` > 0 re-fetches on that interval (while matches are being played). */
function useJson<T>(
  url: string | null,
  refreshMs = 0,
): { data: T | null; error: string | null; loading: boolean } {
  const [state, setState] = useState(() => {
    const data = cached<T>(url);
    return { url, data, error: null as string | null, loading: Boolean(url) && !data };
  });
  let view = state;
  if (state.url !== url) {
    const data = cached<T>(url);
    view = { url, data, error: null, loading: Boolean(url) && !data };
    setState(view);
  }
  useEffect(() => {
    if (!url) return;
    let alive = true;
    load<T>(url)
      .then((data) => alive && setState({ url, data, error: null, loading: false }))
      .catch(
        (err: Error) =>
          alive && setState((prev) => ({ url, data: prev.url === url ? prev.data : null, error: err.message, loading: false })),
      );
    return () => {
      alive = false;
    };
  }, [url]);
  useEffect(() => {
    if (!url || !refreshMs) return;
    let alive = true;
    const timer = window.setInterval(() => {
      load<T>(url, true)
        .then((data) => alive && setState({ url, data, error: null, loading: false }))
        .catch(() => undefined);
    }, refreshMs);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [url, refreshMs]);
  return { data: view.data, error: view.data ? null : view.error, loading: view.loading };
}

/* ------------------------------------------------------------ live scores */

export type Live = { home: number; away: number; minute: number; display: string; status: string; finished: boolean };
const LIVE_POLL_MS = 30_000;

/** Scores of the day's listed matches while they're played, from the live
 * board, until the scanner settles each one. */
function useLive(day: DayKey, enabled: boolean): Record<string, Live> {
  const [live, setLive] = useState<Record<string, Live>>({});
  useEffect(() => {
    if (!enabled) {
      setLive({});
      return;
    }
    let alive = true;
    const pull = () =>
      fetch(`/api/watchlist/live/${day}`)
        .then((res) => (res.ok ? (res.json() as Promise<Record<string, Live>>) : null))
        .then((body) => {
          if (alive && body) setLive(body);
        })
        .catch(() => undefined);
    void pull();
    const timer = window.setInterval(pull, LIVE_POLL_MS);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [day, enabled]);
  return live;
}

function liveClock(live: Live): string {
  if (live.finished) return "FT";
  if (live.status === "HT") return "HT";
  return `${live.display || live.minute}'`;
}

/** The live note without its "…: landed." ending, for when a mark says it. */
function noteBeside(note: string): string {
  return note.replace(/: (landed|missed)\.$/, ".");
}

function started(iso: string): boolean {
  const at = Date.parse(iso);
  return !Number.isNaN(at) && at <= Date.now();
}

/* ---------------------------------------------------------- small parts */

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
    <img className="wl-crest" src={src} alt="" width={size} height={size} loading="lazy" onError={() => setBroken(true)} />
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

function OutcomeMark({ outcome }: { outcome?: Outcome | null }) {
  if (!outcome) return null;
  return <span className={`wl-out is-${outcome}`}>{outcome === "landed" ? "Landed" : "Missed"}</span>;
}

function Tag({ label, outcome }: { label: string; outcome?: Outcome | null }) {
  return (
    <span className={`wl-tag${outcome ? ` is-${outcome}` : ""}`} title={outcome ? (outcome === "landed" ? "Landed" : "Missed") : undefined}>
      {outcome ? <i aria-hidden>{outcome === "landed" ? "✓" : "✗"}</i> : null}
      {label}
    </span>
  );
}

function TallyBar({ tally, label }: { tally: Tally; label: string }) {
  const share = tally.settled ? Math.round((tally.landed / tally.settled) * 100) : 0;
  return (
    <div className="wl-stat">
      <span>{label}</span>
      <b>
        {tally.landed} of {tally.settled}
      </b>
      <i className="wl-stat-bar" aria-hidden>
        <i style={{ width: `${share}%` }} />
      </i>
    </div>
  );
}

function linkTo(go: () => void) {
  return (event: MouseEvent<HTMLAnchorElement>) => {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    event.preventDefault();
    go();
  };
}

function CalendarIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" aria-hidden fill="none" stroke="currentColor" strokeWidth="1.5">
      <rect x="2" y="3" width="12" height="11" rx="2" />
      <path d="M2 6.5h12M5.5 1.5v3M10.5 1.5v3" />
    </svg>
  );
}

/* --------------------------------------------------------------- the nav */

type Nav = {
  go: (route: Route, options?: { replace?: boolean }) => void;
  back: (route: Route) => void;
};

/* ------------------------------------------------------ the date control */

type DayBounds = { iso?: string; today?: string; first?: string | null };

/** One day back and forward within the archive: from the first list to tomorrow. */
function neighbours({ iso, today, first }: DayBounds): { prev: string | null; next: string | null } {
  return {
    prev: iso && (!first || iso > first) ? addDays(iso, -1) : null,
    next: iso && today && iso < addDays(today, 1) ? addDays(iso, 1) : null,
  };
}

/** ← and → step a day, as the arrows either side of the date do. */
function useDayKeys(bounds: DayBounds, onPick: (iso: string) => void): void {
  const { prev, next } = neighbours(bounds);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (isTyping(event) || event.altKey || event.metaKey || event.ctrlKey) return;
      if (event.key === "ArrowLeft" && prev) onPick(prev);
      else if (event.key === "ArrowRight" && next) onPick(next);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [prev, next, onPick]);
}

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** The month as calendar cells, Monday first; null pads the first and last week. */
function monthCells(month: string): (string | null)[] {
  const [y, m] = month.split("-").map(Number);
  const lead = (new Date(Date.UTC(y, m - 1, 1)).getUTCDay() + 6) % 7;
  const days = new Date(Date.UTC(y, m, 0)).getUTCDate();
  const out: (string | null)[] = Array.from({ length: lead }, () => null);
  for (let d = 1; d <= days; d += 1) out.push(`${month}-${String(d).padStart(2, "0")}`);
  while (out.length % 7) out.push(null);
  return out;
}

function MonthPicker({
  selected,
  today,
  first,
  onPick,
  onWholeMonth,
}: {
  selected?: string;
  today: string;
  first?: string | null;
  onPick: (iso: string) => void;
  onWholeMonth: (month: string) => void;
}) {
  const [month, setMonth] = useState((selected ?? today).slice(0, 7));
  const { data } = useJson<WatchlistMonth>(`/api/watchlist/month/${month}`);
  const tomorrow = addDays(today, 1);
  const firstMonth = first ? first.slice(0, 7) : null;
  const canPrev = Boolean(firstMonth && month > firstMonth);
  const canNext = month < tomorrow.slice(0, 7);
  const byDay = useMemo(() => new Map((data?.days ?? []).map((d) => [d.day, d.summary])), [data]);
  return (
    <div className="wl-mp">
      <div className="wl-mp-head">
        <button type="button" disabled={!canPrev} onClick={() => setMonth(addMonths(month, -1))} aria-label="Previous month">
          ‹
        </button>
        <b>{monthLabel(month)}</b>
        <button type="button" disabled={!canNext} onClick={() => setMonth(addMonths(month, 1))} aria-label="Next month">
          ›
        </button>
      </div>
      <div className="wl-mp-grid">
        {WEEKDAYS.map((w) => (
          <span key={w} className="wl-mp-wd" aria-hidden>
            {w.slice(0, 2)}
          </span>
        ))}
        {monthCells(month).map((iso, i) => {
          if (!iso) return <span key={`blank-${i}`} />;
          const summary = byDay.get(iso);
          const n = Number(iso.slice(8));
          const cls = `wl-mp-day${iso === today ? " is-today" : ""}${iso === selected ? " on" : ""}`;
          if (!summary) {
            return (
              <span key={iso} className={cls}>
                {n}
              </span>
            );
          }
          const picks = addTally(summary.strong_tally, summary.look_tally);
          const share = picks.settled ? picks.landed / picks.settled : null;
          return (
            <button
              key={iso}
              type="button"
              className={`${cls} has`}
              onClick={() => onPick(iso)}
              aria-label={`${longDay(iso)}${picks.settled ? `: ${picks.landed} of ${picks.settled} picks landed` : ""}`}
            >
              {n}
              {share != null ? (
                <small className={share >= 0.6 ? "is-good" : share < 0.45 ? "is-poor" : ""}>
                  {picks.landed}/{picks.settled}
                </small>
              ) : (
                <small>{iso === today ? "today" : iso === tomorrow ? "next" : ""}</small>
              )}
            </button>
          );
        })}
      </div>
      <div className="wl-mp-foot">
        <span>Picks landed, of those played</span>
        <a href={`/calendar/${month}`} onClick={linkTo(() => onWholeMonth(month))}>
          Whole month →
        </a>
      </div>
    </div>
  );
}

/**
 * The one date control: ‹ the day before, the date itself (opens the month,
 * with Today and Tomorrow on top), the day after ›.
 */
function DateControl({
  day,
  bounds,
  onPick,
  onWholeMonth,
}: {
  day: DayKey;
  bounds: DayBounds;
  onPick: (iso: string) => void;
  onWholeMonth: (month: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const { iso } = bounds;
  const today = bounds.today ?? new Date().toISOString().slice(0, 10);
  const { prev, next } = neighbours(bounds);

  useEffect(() => setOpen(false), [day]);
  useEffect(() => {
    if (!open) return;
    const onDown = (event: PointerEvent) => {
      if (box.current && !box.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const pick = (target: string) => {
    setOpen(false);
    onPick(target);
  };
  const tag = day === "today" ? "Today" : day === "tomorrow" ? "Tomorrow" : null;
  const label = iso ? dayLabel(iso) : (tag ?? (ISO_DAY.test(day) ? dayLabel(day) : ""));
  return (
    <div className="wl-date" ref={box}>
      <button type="button" className="wl-date-step" disabled={!prev} onClick={() => prev && pick(prev)} aria-label="Previous day">
        ‹
      </button>
      <button
        type="button"
        className={`wl-date-mid${open ? " on" : ""}`}
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen((v) => !v)}
      >
        <CalendarIcon />
        <span>{label}</span>
        {tag && iso ? <em>{tag}</em> : null}
        <i className="wl-date-chev" aria-hidden />
      </button>
      <button type="button" className="wl-date-step" disabled={!next} onClick={() => next && pick(next)} aria-label="Next day">
        ›
      </button>
      {open ? (
        <div className="wl-date-pop" role="dialog" aria-label="Pick a day">
          <div className="wl-date-quick">
            {(
              [
                [today, "Today"],
                [addDays(today, 1), "Tomorrow"],
              ] as const
            ).map(([target, name]) => (
              <button key={name} type="button" className={iso === target ? "on" : ""} onClick={() => pick(target)}>
                {name}
              </button>
            ))}
          </div>
          <MonthPicker selected={iso} today={today} first={bounds.first} onPick={pick} onWholeMonth={onWholeMonth} />
        </div>
      ) : null}
    </div>
  );
}

/** The links between the three pages, beside the masthead. Live board is the
 * home page, a full page load as it always was. */
function PageSwitch({ route, nav }: { route: Route; nav: Nav }) {
  const day = route.view === "calendar" ? "today" : route.day;
  const onList = route.view !== "parlay";
  return (
    <nav className="wl-switch" aria-label="Pages">
      <a href="/">
        <i className="wl-switch-live" aria-hidden />
        Live board
      </a>
      <a
        href={`/${day}`}
        className={onList ? "on" : ""}
        aria-current={onList ? "page" : undefined}
        onClick={linkTo(() => nav.go({ view: "day", day }))}
      >
        Watchlist
      </a>
      <a
        href={routePath({ view: "parlay", day })}
        className={onList ? "" : "on"}
        aria-current={onList ? undefined : "page"}
        onClick={linkTo(() => nav.go({ view: "parlay", day }))}
      >
        Parlay
      </a>
    </nav>
  );
}


/* ------------------------------------------------------------------ list */

type Filter = "all" | "strong" | "look";
type Layout = "time" | "league";

const LAYOUT_KEY = "wl-layout";

function savedLayout(): Layout {
  try {
    return window.localStorage.getItem(LAYOUT_KEY) === "league" ? "league" : "time";
  } catch {
    return "time";
  }
}

function saveLayout(layout: Layout): void {
  try {
    window.localStorage.setItem(LAYOUT_KEY, layout);
  } catch {
    /* private window: the choice just won't stick */
  }
}

const WATCH_RANK: { [K in Watch]: number } = { strong: 0, look: 1, quiet: 2 };

/** Kick-off order; matches starting together put the stronger ones first. */
function byKickoff(a: WatchRow, b: WatchRow): number {
  return a.kickoff.localeCompare(b.kickoff) || WATCH_RANK[a.watch] - WATCH_RANK[b.watch] || b.score - a.score;
}

/** Kick-off to final whistle with room for stoppages and a late start. */
const MATCH_SPAN_MS = 150 * 60_000;

type TimeGroup = { key: string; title: string; kind: "live" | "slot" | "played"; rows: WatchRow[] };

/** The day as a schedule: what's being played, then each kick-off time still
 * to come, then what's done. Past days are just their kick-off times. */
function timeGroups(rows: WatchRow[], live: Record<string, Live>, past: boolean): TimeGroup[] {
  const sorted = [...rows].sort(byKickoff);
  const inPlay: WatchRow[] = [];
  const played: WatchRow[] = [];
  const slots = new Map<string, WatchRow[]>();
  const now = Date.now();
  for (const m of sorted) {
    const since = now - Date.parse(m.kickoff);
    // No score and long past kick-off: over, its result just isn't in yet.
    if (!past && (m.result || (!live[m.match_id] && since > MATCH_SPAN_MS))) played.push(m);
    else if (!past && (live[m.match_id] || since >= 0)) inPlay.push(m);
    else {
      const at = clock(m.kickoff);
      slots.set(at, [...(slots.get(at) ?? []), m]);
    }
  }
  const out: TimeGroup[] = [];
  if (inPlay.length) out.push({ key: "live", title: "Live now", kind: "live", rows: inPlay });
  for (const [at, group] of slots) out.push({ key: at, title: at, kind: "slot", rows: group });
  if (played.length) out.push({ key: "played", title: "Played", kind: "played", rows: played });
  return out;
}

function orderedRows(data: WatchlistDay, filter: Filter, layout: Layout, past: boolean): WatchRow[] {
  const byId = new Map(data.matches.map((m) => [m.match_id, m]));
  const keep = (m: WatchRow | undefined): m is WatchRow => Boolean(m) && (filter === "all" || m!.watch === filter);
  if (layout === "time") {
    return timeGroups(data.matches.filter(keep), {}, past).flatMap((g) => g.rows);
  }
  const out: WatchRow[] = [];
  for (const league of data.leagues) {
    out.push(...league.match_ids.map((id) => byId.get(id)).filter(keep).sort((a, b) => a.kickoff.localeCompare(b.kickoff)));
  }
  return out;
}

function dayTitle(day: DayKey, iso?: string): string {
  if (day === "today") return "Today's watchlist";
  if (day === "tomorrow") return "Tomorrow's watchlist";
  return iso ? `Watchlist for ${longDay(iso)}` : "Watchlist";
}

function HowItWent({ data }: { data: WatchlistDay }) {
  const s = data.summary;
  if (!s || !(s.finished || s.called_off)) return null;
  const toPlay = s.matches - s.finished - s.called_off;
  const picks = addTally(s.strong_tally, s.look_tally);
  return (
    <section className="wl-went" aria-label="How it went">
      <div className="wl-went-head">
        <h2>How it went</h2>
        <p>
          A match counts as landed when its headline pattern happened in the 90 minutes.
          {toPlay > 0 ? ` ${plural(toPlay, "match")} still to finish.` : ""}
          {s.called_off ? ` ${s.called_off} called off.` : ""}
        </p>
      </div>
      <div className="wl-stats">
        {s.top.settled ? <TallyBar tally={s.top} label="Top five" /> : null}
        {s.strong_tally.settled ? <TallyBar tally={s.strong_tally} label="Strong watch" /> : null}
        {s.look_tally.settled ? <TallyBar tally={s.look_tally} label="Worth a look" /> : null}
        {!picks.settled ? <p className="wl-sub">No strong or worth-a-look matches have finished yet.</p> : null}
      </div>
    </section>
  );
}

function RowScore({ result, kickoff, live }: { result?: RowResult | null; kickoff: string; live?: Live }) {
  if (!result && live) {
    return (
      <span className="wl-time is-live" title={`Kick-off ${clock(kickoff)}`}>
        {liveClock(live)}
      </span>
    );
  }
  if (!result) return <span className="wl-time">{clock(kickoff)}</span>;
  return (
    <span className={`wl-time is-done${result.status === "off" ? " is-off" : ""}`} title={`Kick-off ${clock(kickoff)}`}>
      {result.status === "off" ? "Off" : resultLabel(result)}
    </span>
  );
}

function LiveLine({ m, live }: { m: WatchRow; live: Live }) {
  if (live.finished) return <span className="wl-why-out is-live">Full time. Marking how it went…</span>;
  const score = `${live.home}-${live.away}`;
  const verdict = m.lead_key ? liveVerdict(m.lead_key, score) : null;
  const note = m.lead_key ? liveNote(m.lead_key, score, m.home.name, m.away.name, live.minute) : "";
  if (!note && !verdict) return null;
  return (
    <span className="wl-why-out is-live">
      {verdict ? <OutcomeMark outcome={verdict} /> : <i className="wl-live-dot" aria-hidden />}{" "}
      {verdict ? noteBeside(note) : note}
    </span>
  );
}

function MatchRow({
  m,
  day,
  live,
  league,
  recent,
  open,
  warm,
}: {
  m: WatchRow;
  day: DayKey;
  live?: Live;
  league?: LeagueGroup;
  recent: boolean;
  open: (id: string) => void;
  warm: (id: string) => void;
}) {
  return (
    <a
      className={`wl-row${recent ? " is-recent" : ""}`}
      href={`/${day}/${m.match_id}`}
      data-match={m.match_id}
      onClick={linkTo(() => open(m.match_id))}
      onPointerEnter={() => warm(m.match_id)}
      onFocus={() => warm(m.match_id)}
    >
      <RowScore result={m.result} kickoff={m.kickoff} live={live} />
      <div className="wl-teams">
        {(["home", "away"] as const).map((side) => {
          const t = m[side];
          const lv = m.result ? undefined : live;
          const goals = m.result?.status === "finished" ? m.result[side] : lv ? lv[side] : null;
          return (
            <div key={side}>
              <Crest src={t.badge} name={t.name} />
              <span className="wl-name">{t.name}</span>
              {t.position ? <span className="wl-pos">{ordinal(t.position)}</span> : null}
              {goals != null ? <b className={`wl-goals${lv ? " is-live" : ""}`}>{goals}</b> : null}
            </div>
          );
        })}
        {league ? (
          <small className="wl-row-league">
            {league.logo ? <Crest src={league.logo} name={league.name} size={12} /> : null}
            <span>
              {league.country} · {league.name}
            </span>
          </small>
        ) : null}
      </div>
      <div className="wl-odds" aria-label="Match odds">
        {(["home", "draw", "away"] as const).map((k, idx) => (
          <span key={k}>
            <b>{["1", "X", "2"][idx]}</b>
            {price(m.odds?.[k])}
          </span>
        ))}
      </div>
      <div className="wl-why">
        {m.reason || "Nothing stands out against the league norm."}
        {m.outcome ? (
          <span className="wl-why-out">
            <OutcomeMark outcome={m.outcome} /> {m.outcome_note}
          </span>
        ) : !m.result && live ? (
          <LiveLine m={m} live={live} />
        ) : null}
      </div>
      <div className="wl-end">
        <WatchMark watch={m.watch} />
      </div>
    </a>
  );
}

function DayView({
  day,
  filter,
  setFilter,
  layout,
  setLayout,
  recent,
  nav,
  onReady,
}: {
  day: DayKey;
  filter: Filter;
  setFilter: (f: Filter) => void;
  layout: Layout;
  setLayout: (l: Layout) => void;
  recent: string | null;
  nav: Nav;
  onReady: () => void;
}) {
  const [refreshMs, setRefreshMs] = useState(0);
  const [showPlayed, setShowPlayed] = useState(false);
  const { data, error, loading } = useJson<WatchlistDay>(`/api/watchlist/day/${day}`, refreshMs);
  const underway = Boolean(data?.status === "ready" && data.matches.some((m) => !m.result && started(m.kickoff)));
  const live = useLive(day, underway);
  const ending = Object.values(live).some((l) => l.finished);
  useEffect(() => {
    // Re-read the list soon after a match ends, so its marks show up.
    setRefreshMs(ending ? 45_000 : underway ? 180_000 : 0);
  }, [ending, underway]);

  useEffect(() => {
    if (data) onReady();
  }, [data, onReady]);

  // Neighbouring days load in the background, so stepping is instant.
  useEffect(() => {
    if (!data?.day || !data.today) return;
    if (!data.first_day || data.day > data.first_day) prefetch(`/api/watchlist/day/${dayKey(addDays(data.day, -1), data.today)}`);
    if (data.day < addDays(data.today, 1)) prefetch(`/api/watchlist/day/${dayKey(addDays(data.day, 1), data.today)}`);
  }, [data?.day, data?.today, data?.first_day]);

  const bounds = useMemo<DayBounds>(
    () => ({ iso: data?.day, today: data?.today, first: data?.first_day }),
    [data?.day, data?.today, data?.first_day],
  );
  const toDay = useCallback(
    (iso: string) => nav.go({ view: "day", day: bounds.today ? dayKey(iso, bounds.today) : iso }),
    [nav, bounds.today],
  );
  useDayKeys(bounds, toDay);

  const byId = useMemo(() => new Map((data?.matches ?? []).map((m) => [m.match_id, m])), [data]);
  const leagueByKey = useMemo(() => new Map((data?.leagues ?? []).map((l) => [l.key, l])), [data]);
  const counts = useMemo(() => {
    const out = { all: 0, strong: 0, look: 0 };
    for (const m of data?.matches ?? []) {
      out.all += 1;
      if (m.watch === "strong") out.strong += 1;
      if (m.watch === "look") out.look += 1;
    }
    return out;
  }, [data]);

  const ready = data?.status === "ready";
  const shown = (m: WatchRow) => filter === "all" || m.watch === filter;
  const picks = (data?.shortlist ?? []).map((id) => byId.get(id)).filter((m): m is WatchRow => Boolean(m));
  const open = (id: string) => nav.go({ view: "match", day, matchId: id });
  const warm = (id: string) => prefetch(`/api/watchlist/match/${id}`);
  const past = day !== "today" && day !== "tomorrow";
  const played = Boolean(data?.summary && (data.summary.finished || data.summary.called_off));

  return (
    <>
      <div className="wl-intro">
        <div className="wl-head">
          <h1>{dayTitle(day, data?.day ?? (ISO_DAY.test(day) ? day : undefined))}</h1>
          <DateControl
            day={day}
            bounds={bounds}
            onPick={toDay}
            onWholeMonth={(month) => nav.go({ view: "calendar", month })}
          />
        </div>
        <p>
          {past
            ? "The list as it stood before kick-off, with each match's score and whether its patterns landed."
            : "Every match bookmakers price, checked for the same patterns: both teams scoring, goals, late goals, first-half goals, clean sheets and scoring runs. Each team's last 10 games are compared with their league's average, and the matches where something stands out come first."}
        </p>
      </div>

      <div className="wl-card">
        <div className="wl-bar">
          {ready && data.matches.length ? (
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
              <span className="wl-filters-gap" aria-hidden />
              {(
                [
                  ["time", "By time"],
                  ["league", "By league"],
                ] as const
              ).map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  className={layout === key ? "on" : ""}
                  aria-pressed={layout === key}
                  onClick={() => setLayout(key)}
                >
                  {label}
                </button>
              ))}
            </div>
          ) : null}
        </div>

        {loading ? <p className="wl-empty">Loading…</p> : null}
        {error ? (
          <p className="wl-empty">
            {error === "not_found" ? "There's no watchlist for that day." : "The watchlist is unavailable right now. Try again in a minute."}
          </p>
        ) : null}
        {data?.status === "preparing" ? (
          <p className="wl-empty">
            {day === "tomorrow" ? "Tomorrow's" : "Today's"} list is still being put together. Check back in a few minutes.
          </p>
        ) : null}
        {data?.status === "none" ? (
          <p className="wl-empty">
            No watchlist was made for {longDay(data.day)}.{" "}
            <a href="/calendar" onClick={linkTo(() => nav.go({ view: "calendar", month: data.day.slice(0, 7) }))}>
              Open the calendar
            </a>
            .
          </p>
        ) : null}
        {ready && !data.matches.length ? <p className="wl-empty">No priced matches on this day.</p> : null}

        {ready && played ? <HowItWent data={data} /> : null}

        {ready && picks.length && filter === "all" ? (
          <section className="wl-picks" aria-label="Top picks">
            <h2>{played || past ? "Top picks" : picks.length === 1 ? "One to have open" : `${picks.length} to have open`}</h2>
            {picks.map((m, i) => (
              <a
                key={m.match_id}
                className={`wl-pick${m.outcome ? ` is-${m.outcome}` : ""}${recent === m.match_id ? " is-recent" : ""}`}
                href={`/${day}/${m.match_id}`}
                data-match={m.match_id}
                onClick={linkTo(() => open(m.match_id))}
                onPointerEnter={() => warm(m.match_id)}
                onFocus={() => warm(m.match_id)}
              >
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
                  {m.outcome ? (
                    <p className="wl-verdict">
                      <OutcomeMark outcome={m.outcome} /> {m.outcome_note}
                    </p>
                  ) : live[m.match_id] ? (
                    <p className="wl-verdict">
                      <LiveLine m={m} live={live[m.match_id]} />
                    </p>
                  ) : null}
                  <div className="wl-tags">
                    {m.tags.map((t, k) => (
                      <Tag key={`${t.label}-${k}`} label={t.label} outcome={t.outcome} />
                    ))}
                  </div>
                </div>
                <span className="wl-pick-time">
                  {m.result ? (
                    <>
                      <b>{scoreText(m.result) || m.result.label}</b>
                      {m.result.status === "finished" ? <small>{resultLabel(m.result)}</small> : null}
                    </>
                  ) : live[m.match_id] ? (
                    <>
                      <b className="is-live">
                        {live[m.match_id].home}–{live[m.match_id].away}
                      </b>
                      <small className="is-live">{liveClock(live[m.match_id])}</small>
                    </>
                  ) : (
                    clock(m.kickoff)
                  )}
                </span>
              </a>
            ))}
          </section>
        ) : null}

        {ready && layout === "time"
          ? (() => {
              const groups = timeGroups(data.matches.filter(shown), live, past);
              const pending = groups.some((g) => g.kind !== "played");
              return groups.map((g) => {
                const folded = g.kind === "played" && pending && !showPlayed;
                const count = plural(g.rows.length, "match");
                return (
                  <section key={g.key} className={`wl-league wl-slot is-${g.kind}`}>
                    <header className="wl-league-head">
                      {g.kind === "played" && pending ? (
                        <button
                          type="button"
                          className="wl-slot-toggle"
                          aria-expanded={!folded}
                          onClick={() => setShowPlayed((v) => !v)}
                        >
                          <b>
                            Played <span className="wl-slot-n">· {count}</span>
                          </b>
                          <span className="wl-slot-more">{folded ? "Show" : "Hide"}</span>
                        </button>
                      ) : (
                        <b>
                          {g.kind === "live" ? <i className="wl-live-dot" aria-hidden /> : null}
                          {g.title} <span className="wl-slot-n">· {count}</span>
                        </b>
                      )}
                    </header>
                    {folded
                      ? null
                      : g.rows.map((m) => (
                          <MatchRow
                            key={m.match_id}
                            m={m}
                            day={day}
                            live={live[m.match_id]}
                            league={leagueByKey.get(m.league_key)}
                            recent={recent === m.match_id}
                            open={open}
                            warm={warm}
                          />
                        ))}
                  </section>
                );
              });
            })()
          : null}

        {ready && layout === "league"
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
                  </header>
                  {rows.map((m) => (
                    <MatchRow
                      key={m.match_id}
                      m={m}
                      day={day}
                      live={live[m.match_id]}
                      recent={recent === m.match_id}
                      open={open}
                      warm={warm}
                    />
                  ))}
                </section>
              );
            })
          : null}

        {ready ? (
          <p className="wl-foot">
            {past
              ? "Lists are frozen at kick-off, so what you see is what was published before each game. "
              : data.built_at
                ? `Updated ${clock(data.built_at)}. `
                : ""}
            Kick-off times in your time zone. Use ← and → to move between days.
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

/* ---------------------------------------------------------------- parlay */

type ParlayStyle = "safer" | "balanced" | "bolder";

type ParlayLeg = {
  match_id: string;
  kickoff: string;
  league: string;
  country: string;
  home: TeamRef;
  away: TeamRef;
  watch: Watch;
  market: string;
  label: string;
  price: number;
  hit: number;
  n: number;
  brief: string;
  score: number;
  result?: RowResult | null;
  outcome?: Outcome | null;
  outcome_note?: string;
};

type ParlayDay = {
  status: "ready" | "preparing" | "none";
  day: string;
  today: string;
  first_day?: string | null;
  legs: ParlayLeg[];
  order: { [K in ParlayStyle]: string[] };
  unpriced: { match_id: string; home: string; away: string; tags: string[] }[];
};

const PARLAY_MIN = 3;
const PARLAY_PRESETS = [3, 5, 8, 12, 18];
const PARLAY_STYLES: { key: ParlayStyle; name: string; desc: string }[] = [
  { key: "safer", name: "Safer", desc: "Shortest prices first, and only legs that came in at least 7 times in 10 recently." },
  { key: "balanced", name: "Balanced", desc: "The strongest patterns of the day, in the order the watchlist ranks them." },
  {
    key: "bolder",
    name: "Bolder",
    desc: "Legs whose recent record beats the price by the most. Longer odds, less likely to all come in.",
  },
];

/** "about 1 in 14" from the combined decimal odds. */
function oneIn(odds: number): string {
  if (odds < 2) return "better than even";
  const n = Math.round(odds);
  if (n >= 10_000) return `about 1 in ${Math.round(n / 1000).toLocaleString()},000`;
  if (n >= 1000) return `about 1 in ${(Math.round(n / 100) * 100).toLocaleString()}`;
  return `about 1 in ${n}`;
}

/** Where the slip stands once games are played. */
function parlayState(legs: ParlayLeg[]): string | null {
  const missed = legs.filter((l) => l.outcome === "missed").length;
  const landed = legs.filter((l) => l.outcome === "landed").length;
  if (missed) return `Lost: ${missed} of ${legs.length} ${missed === 1 ? "leg" : "legs"} missed.`;
  if (landed === legs.length) return `Came in: all ${legs.length} legs landed.`;
  if (landed) return `${landed} of ${legs.length} landed so far, none missed.`;
  return null;
}

function Record({ leg }: { leg: ParlayLeg }) {
  const share = leg.n ? Math.round((leg.hit / leg.n) * 100) : 0;
  return (
    <span className="wl-rec" title={`Happened in ${leg.hit} of the two teams' last ${leg.n} games`}>
      <i aria-hidden>
        <i style={{ width: `${share}%` }} />
      </i>
      {leg.hit} of {leg.n}
    </span>
  );
}

function ParlayView({
  day,
  legs: wanted,
  setLegs,
  style,
  setStyle,
  nav,
  onReady,
}: {
  day: DayKey;
  legs: number;
  setLegs: (n: number) => void;
  style: ParlayStyle;
  setStyle: (s: ParlayStyle) => void;
  nav: Nav;
  onReady: () => void;
}) {
  const { data, error, loading } = useJson<ParlayDay>(`/api/watchlist/parlay/${day}`);
  useEffect(() => {
    if (data) onReady();
  }, [data, onReady]);

  const bounds = useMemo<DayBounds>(
    () => ({ iso: data?.day, today: data?.today, first: data?.first_day }),
    [data?.day, data?.today, data?.first_day],
  );
  const toDay = useCallback(
    (iso: string) => nav.go({ view: "parlay", day: bounds.today ? dayKey(iso, bounds.today) : iso }),
    [nav, bounds.today],
  );
  useDayKeys(bounds, toDay);

  const ready = data?.status === "ready";
  const byId = useMemo(() => new Map((data?.legs ?? []).map((l) => [l.match_id, l])), [data]);
  const order = data?.order?.[style] ?? [];
  const most = order.length;
  const n = Math.max(Math.min(wanted, most), Math.min(PARLAY_MIN, most));
  const legs = order
    .slice(0, n)
    .map((id) => byId.get(id))
    .filter((l): l is ParlayLeg => Boolean(l))
    .sort((a, b) => a.kickoff.localeCompare(b.kickoff) || a.match_id.localeCompare(b.match_id));
  const odds = legs.reduce((total, l) => total * l.price, 1);
  const looks = legs.filter((l) => l.watch === "look").length;
  const strongPriced = data ? data.legs.filter((l) => l.watch === "strong").length : 0;
  const strongLeftOver = data
    ? data.legs.filter((l) => l.watch === "strong" && !legs.some((x) => x.match_id === l.match_id)).length
    : 0;
  const past = day !== "today" && day !== "tomorrow";
  const state = parlayState(legs);
  const lost = legs.some((l) => l.outcome === "missed");
  const won = legs.length > 0 && legs.every((l) => l.outcome === "landed");
  const settled = lost || won;
  const iso = data?.day ?? (ISO_DAY.test(day) ? day : undefined);
  const title = day === "today" ? "Today's parlay" : day === "tomorrow" ? "Tomorrow's parlay" : iso ? `Parlay for ${longDay(iso)}` : "Parlay";
  const styleInfo = PARLAY_STYLES.find((s) => s.key === style) ?? PARLAY_STYLES[1];

  return (
    <>
      <div className="wl-intro">
        <div className="wl-head">
          <h1>{title}</h1>
          <DateControl
            day={day}
            bounds={bounds}
            onPick={toDay}
            onWholeMonth={(month) => nav.go({ view: "calendar", month })}
          />
        </div>
        <p>
          {past
            ? "The parlay as the list stood before kick-off, and how each leg went."
            : "The strongest picks on the watchlist added up into one bet: one leg per match, each from its strongest pattern that bookmakers price."}
        </p>
      </div>

      <div className="wl-card">
        {loading ? <p className="wl-empty">Loading…</p> : null}
        {error ? <p className="wl-empty">The parlay is unavailable right now. Try again in a minute.</p> : null}
        {data?.status === "preparing" ? (
          <p className="wl-empty">The list for this day is still being put together. Check back in a few minutes.</p>
        ) : null}
        {data?.status === "none" ? <p className="wl-empty">No watchlist was made for {longDay(data.day)}.</p> : null}
        {ready && most < PARLAY_MIN ? (
          <p className="wl-empty">
            Not enough strong picks with a bookmaker price on this day to make a parlay of {PARLAY_MIN}.
          </p>
        ) : null}

        {ready && most >= PARLAY_MIN ? (
          <>
            <div className={`wl-par-sum${lost ? " is-missed" : won ? " is-landed" : ""}`}>
              <div className="wl-par-big">
                <small>{plural(legs.length, "leg")} · combined odds</small>
                <b>{odds.toFixed(2)}</b>
              </div>
              <p>
                {state ? <strong className="wl-par-state">{state} </strong> : null}
                {settled
                  ? `Bookmakers rated all ${legs.length} landing ${oneIn(odds)}.`
                  : `All ${legs.length} have to land. At these prices bookmakers rate that ${oneIn(odds)}.`}{" "}
                Each leg shows how often it happened in the two teams' recent games.
                {looks ? ` ${plural(looks, "leg")} from Worth a look, added to reach ${legs.length}.` : ""}
              </p>
              {lost ? null : (
                <div className="wl-par-big is-side">
                  <small>{won ? "A 10 stake returned" : "A 10 stake returns"}</small>
                  <b>{(10 * odds).toFixed(2)}</b>
                </div>
              )}
            </div>

            <div className="wl-par-ctl">
              <span className="wl-par-field">
                <label id="wl-par-n">Legs</label>
                <span className="wl-stepper-n" role="group" aria-labelledby="wl-par-n">
                  <button type="button" disabled={n <= PARLAY_MIN} onClick={() => setLegs(n - 1)} aria-label="One leg fewer">
                    −
                  </button>
                  <b aria-live="polite">{n}</b>
                  <button type="button" disabled={n >= most} onClick={() => setLegs(n + 1)} aria-label="One leg more">
                    +
                  </button>
                </span>
              </span>
              <span className="wl-par-field">
                <label>Quick</label>
                <span className="wl-seg" role="group" aria-label="Number of legs">
                  {PARLAY_PRESETS.map((p) => (
                    <button
                      key={p}
                      type="button"
                      className={n === p ? "on" : ""}
                      aria-pressed={n === p}
                      disabled={p > most}
                      onClick={() => setLegs(p)}
                    >
                      {p}
                    </button>
                  ))}
                </span>
              </span>
              <span className="wl-par-field">
                <label>Style</label>
                <span className="wl-seg" role="group" aria-label="Style">
                  {PARLAY_STYLES.map((s) => (
                    <button
                      key={s.key}
                      type="button"
                      className={style === s.key ? "on" : ""}
                      aria-pressed={style === s.key}
                      onClick={() => setStyle(s.key)}
                    >
                      {s.name}
                    </button>
                  ))}
                </span>
              </span>
              <p className="wl-par-desc">
                {styleInfo.desc}
                {most < 18 ? ` Up to ${most} legs in this style on this day.` : ""}
              </p>
            </div>

            <ol className="wl-legs">
              {legs.map((l, i) => (
                <li key={l.match_id}>
                  <a
                    className={`wl-leg${l.outcome ? ` is-${l.outcome}` : ""}`}
                    href={`/${day}/${l.match_id}`}
                    onClick={linkTo(() => nav.go({ view: "match", day, matchId: l.match_id }))}
                    onPointerEnter={() => prefetch(`/api/watchlist/match/${l.match_id}`)}
                  >
                    <span className="wl-leg-n">{i + 1}</span>
                    <span className="wl-leg-time">
                      {l.result ? (
                        <b>{l.result.status === "off" ? "Off" : scoreText(l.result) || l.result.label}</b>
                      ) : (
                        clock(l.kickoff)
                      )}
                    </span>
                    <span className="wl-leg-body">
                      <span className="wl-leg-match">
                        <Crest src={l.home.badge} name={l.home.name} size={16} />
                        <span>
                          {l.home.name} v {l.away.name}
                        </span>
                        <small>{l.league}</small>
                      </span>
                      <span className="wl-leg-mkt">
                        {l.label}
                        {l.watch === "look" ? <small> · Worth a look</small> : null}
                      </span>
                      <span className="wl-leg-why">
                        {l.outcome ? (
                          <>
                            <OutcomeMark outcome={l.outcome} /> {l.outcome_note}
                          </>
                        ) : (
                          l.brief
                        )}
                      </span>
                    </span>
                    <Record leg={l} />
                    <span className="wl-leg-price">{l.price.toFixed(2)}</span>
                  </a>
                </li>
              ))}
            </ol>

            {data.unpriced.length || strongLeftOver ? (
              <details className="wl-par-out">
                <summary>Left out ({data.unpriced.length + (strongLeftOver ? 1 : 0)})</summary>
                <ul>
                  {data.unpriced.map((m) => (
                    <li key={m.match_id}>
                      <a href={`/${day}/${m.match_id}`} onClick={linkTo(() => nav.go({ view: "match", day, matchId: m.match_id }))}>
                        {m.home} v {m.away}
                      </a>
                      : a strong watch, but its patterns ({m.tags.join(", ")}) have no bookmaker price we hold.
                    </li>
                  ))}
                  {strongLeftOver ? (
                    <li>
                      {plural(strongLeftOver, "more strong pick")} with a price, outside this {styleInfo.name.toLowerCase()}{" "}
                      {plural(legs.length, "leg")}
                      {style === "safer" ? " or below its 7-in-10 bar" : style === "bolder" ? " or below its bar" : ""}.
                    </li>
                  ) : null}
                </ul>
              </details>
            ) : null}

            <p className="wl-foot">
              One leg per match, from Strong watch first ({strongPriced} with a price on this day), then Worth a look.
              Only markets with a bookmaker price we hold: goals over or under 2.5, both teams to score, or a clear
              favourite to win. Prices are from when the list was made and may have moved. Kick-off times in your time
              zone.
            </p>
          </>
        ) : null}
      </div>
    </>
  );
}

/* -------------------------------------------------------------- calendar */

function CalendarView({ month, nav, onReady }: { month: string | null; nav: Nav; onReady: () => void }) {
  // Without a month in the address, the board's current month; the API says which.
  const todayGuess = new Date().toISOString().slice(0, 7);
  const shownMonth = month ?? todayGuess;
  const { data, error, loading } = useJson<WatchlistMonth>(`/api/watchlist/month/${shownMonth}`);

  useEffect(() => {
    if (data) onReady();
  }, [data, onReady]);

  const today = data?.today ?? "";
  const tomorrow = today ? addDays(today, 1) : "";
  const firstMonth = data?.first_day ? data.first_day.slice(0, 7) : null;
  const lastMonth = tomorrow ? tomorrow.slice(0, 7) : null;
  const canPrev = Boolean(firstMonth && shownMonth > firstMonth);
  const canNext = Boolean(lastMonth && shownMonth < lastMonth);
  const step = (n: number) => nav.go({ view: "calendar", month: addMonths(shownMonth, n) });

  useEffect(() => {
    if (canPrev) prefetch(`/api/watchlist/month/${addMonths(shownMonth, -1)}`);
    if (canNext) prefetch(`/api/watchlist/month/${addMonths(shownMonth, 1)}`);
  }, [shownMonth, canPrev, canNext]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (isTyping(event) || event.altKey || event.metaKey || event.ctrlKey) return;
      if (event.key === "ArrowLeft" && canPrev) step(-1);
      if (event.key === "ArrowRight" && canNext) step(1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const byDay = useMemo(() => new Map((data?.days ?? []).map((d) => [d.day, d.summary])), [data]);
  const cells = useMemo(() => monthCells(shownMonth), [shownMonth]);

  const totals = useMemo(() => {
    let top = { landed: 0, settled: 0 };
    let picks = { landed: 0, settled: 0 };
    let lists = 0;
    for (const d of data?.days ?? []) {
      lists += 1;
      top = addTally(top, d.summary.top);
      picks = addTally(picks, addTally(d.summary.strong_tally, d.summary.look_tally));
    }
    return { top, picks, lists };
  }, [data]);

  return (
    <>
      <div className="wl-intro">
        <h1>Watchlist calendar</h1>
        <p>
          Every day's list is kept with its results. Pick a day to see the matches as they were before kick-off, the
          final scores and which patterns landed.
        </p>
      </div>
      <div className="wl-card">
        <div className="wl-bar">
          <nav className="wl-days" aria-label="Month">
            <button type="button" className="wl-step" disabled={!canPrev} onClick={() => step(-1)} aria-label="Previous month">
              ‹
            </button>
            <span className="wl-month">{monthLabel(shownMonth)}</span>
            <button type="button" className="wl-step" disabled={!canNext} onClick={() => step(1)} aria-label="Next month">
              ›
            </button>
          </nav>
          <nav className="wl-days" aria-label="Day">
            {(["today", "tomorrow"] as const).map((d) => (
              <a
                key={d}
                href={`/${d}`}
                className="wl-chip"
                onClick={linkTo(() => nav.go({ view: "day", day: d }))}
                onPointerEnter={() => prefetch(`/api/watchlist/day/${d}`)}
              >
                {d === "today" ? "Today" : "Tomorrow"}
              </a>
            ))}
          </nav>
        </div>

        {loading ? <p className="wl-empty">Loading…</p> : null}
        {error ? <p className="wl-empty">The calendar is unavailable right now. Try again in a minute.</p> : null}

        {data ? (
          <>
            {totals.picks.settled ? (
              <div className="wl-stats wl-month-stats">
                <TallyBar tally={totals.top} label="Top five this month" />
                <TallyBar tally={totals.picks} label="Strong and worth a look" />
              </div>
            ) : null}
            <div className="wl-cal">
              {WEEKDAYS.map((w) => (
                <div key={w} className="wl-cal-wd" aria-hidden>
                  {w}
                </div>
              ))}
              {cells.map((iso, i) => {
                if (!iso) return <div key={`blank-${i}`} className="wl-cal-cell is-blank" />;
                const summary = byDay.get(iso);
                const n = Number(iso.slice(8));
                const isToday = iso === today;
                if (!summary) {
                  return (
                    <div key={iso} className={`wl-cal-cell is-empty${isToday ? " is-today" : ""}`}>
                      <span className="wl-cal-n">{n}</span>
                    </div>
                  );
                }
                const picks = addTally(summary.strong_tally, summary.look_tally);
                const share = picks.settled ? Math.round((picks.landed / picks.settled) * 100) : 0;
                const key = today ? dayKey(iso, today) : iso;
                const upcoming = iso >= today && !summary.finished;
                return (
                  <a
                    key={iso}
                    href={`/${key}`}
                    className={`wl-cal-cell${isToday ? " is-today" : ""}${upcoming ? " is-upcoming" : ""}`}
                    onClick={linkTo(() => nav.go({ view: "day", day: key }))}
                    onPointerEnter={() => prefetch(`/api/watchlist/day/${key}`)}
                    aria-label={`${longDay(iso)}: ${plural(summary.matches, "match")}${
                      picks.settled ? `, ${picks.landed} of ${picks.settled} picks landed` : ""
                    }`}
                  >
                    <span className="wl-cal-n">{n}</span>
                    <span className="wl-cal-m">{summary.matches}</span>
                    {picks.settled ? (
                      <>
                        <span className="wl-cal-t">
                          {picks.landed}/{picks.settled}
                        </span>
                        <i className="wl-stat-bar" aria-hidden>
                          <i style={{ width: `${share}%` }} />
                        </i>
                      </>
                    ) : (
                      <span className="wl-cal-t is-soft">
                        {iso === tomorrow ? "Tomorrow" : isToday ? "Today" : upcoming ? "Upcoming" : `${summary.strong + summary.look} picks`}
                      </span>
                    )}
                  </a>
                );
              })}
            </div>
            <p className="wl-foot">
              Each day shows how many priced matches were listed and, once played, how many of its strong and
              worth-a-look matches landed their headline pattern.
              {totals.lists ? ` ${plural(totals.lists, "list")} this month.` : " No lists this month."}
            </p>
          </>
        ) : null}
      </div>
    </>
  );
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

function lineLabel(line: ShotLine): string {
  if (line.stat === "on_target") return `${line.at_least}+ on target`;
  return `${line.at_least}+ ${line.at_least === 1 ? "shot" : "shots"}`;
}

/** Decimal odds a record implies on its own: 31 of 35 → 1.13. */
function fairOdds(hits: number, games: number): string {
  return hits > 0 ? (games / hits).toFixed(2) : "–";
}

function PlayerShots({ research }: { research: MatchResearch }) {
  const pair = research.shots;
  if (!pair || (!pair.home && !pair.away)) return null;
  const league = research.league.name.split(" - ")[0];
  return (
    <section className="wl-sec">
      <h3>Player shots</h3>
      <p className="wl-sub">
        Each team's most frequent shooters who are still in the side. Every game they got on the pitch counts, sub
        appearances too. Odds are the fair decimal price each record implies: a bookmaker offering more is paying
        above the record.
      </p>
      {(["home", "away"] as const).map((side) => {
        const team = research[side];
        const shots = pair[side];
        if (!shots) {
          return (
            <div key={side} className="wl-shots-team">
              <div className="wl-who">
                <Crest src={team.badge} name={team.name} />
                {team.name}
              </div>
              <p className="wl-sub">No player shots from the provider for {team.name}'s recent games.</p>
            </div>
          );
        }
        const lines = shots.players[0]?.lines ?? [];
        return (
          <div key={side} className="wl-shots-team">
            <div className="wl-who">
              <Crest src={team.badge} name={team.name} />
              {team.name}
            </div>
            <p className="wl-sub wl-shots-n">
              Last {shots.games} games with player data, {shots.source === "all" ? "all competitions" : league}.
            </p>
            <div className="wl-table-wrap">
              <table className="wl-ptable wl-shots">
                <thead>
                  <tr>
                    <th />
                    <th className="wl-num">Per 90</th>
                    {lines.map((l) => (
                      <th key={`${l.stat}${l.at_least}`} className="wl-num">
                        {lineLabel(l)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {shots.players.map((p) => [
                    <tr key={p.name} className="wl-shots-player">
                      <th scope="row">{p.name}</th>
                      <td className="wl-num">{p.per_90.toFixed(1)}</td>
                      {p.lines.map((l) => (
                        <td
                          key={`${l.stat}${l.at_least}`}
                          className={`wl-num wl-shots-cell${l.hits / p.apps >= 0.8 ? " is-high" : ""}`}
                          title={`${lineLabel(l)} in ${l.hits} of ${p.apps} games`}
                        >
                          <b>{fairOdds(l.hits, p.apps)}</b>
                          <small>
                            {l.hits}/{p.apps}
                          </small>
                        </td>
                      ))}
                    </tr>,
                    <tr key={`${p.name}-run`} className="wl-shots-run">
                      <td colSpan={2 + p.lines.length}>
                        Shots, newest first: {p.shots.join(", ")}
                      </td>
                    </tr>,
                  ])}
                </tbody>
              </table>
            </div>
          </div>
        );
      })}
    </section>
  );
}

function backLabel(day: DayKey, iso?: string): string {
  if (day === "today") return "Today";
  if (day === "tomorrow") return "Tomorrow";
  return iso ? dayLabel(iso) : dayLabel(day);
}

function MatchCentre({ data, live }: { data: MatchResearch; live?: Live }) {
  const r = data.result;
  if (!r && live) {
    return (
      <div className="wl-ko is-done is-live">
        <b>
          {live.home}–{live.away}
        </b>
        <span>
          <i className="wl-live-dot" aria-hidden />
          {live.finished ? "Full time · marking how it went" : `Live · ${liveClock(live)}`}
        </span>
      </div>
    );
  }
  if (!r) {
    return (
      <div className="wl-ko">
        <b>{clock(data.kickoff)}</b>
        <span>{dayLabel(data.day)}</span>
      </div>
    );
  }
  if (r.status === "off") {
    return (
      <div className="wl-ko">
        <b className="wl-ko-off">{r.label}</b>
        <span>{dayLabel(data.day)}</span>
      </div>
    );
  }
  return (
    <div className="wl-ko is-done">
      <b>{scoreText(r)}</b>
      <span>
        {resultLabel(r)}
        {r.ht ? ` · HT ${r.ht[0]}–${r.ht[1]}` : ""}
      </span>
    </div>
  );
}

function GoalLine({ data }: { data: MatchResearch }) {
  const goals = data.result?.goals ?? [];
  if (!goals.length) return null;
  return (
    <div className="wl-goal-line" aria-label="Goals">
      {goals.map((g, i) => (
        <span key={`${g.time}-${i}`} className={g.side === "home" ? "is-home" : "is-away"}>
          <b>{g.time}'</b> {g.side === "home" ? data.home.name : data.away.name}
        </span>
      ))}
    </div>
  );
}

/** The research under a match page's header: what to watch, the patterns,
 * form, goal timing, head-to-head and table. Also shown in the live board's
 * match pop-up. `footer` closes the right-hand column. */
export function ResearchBody({ data, live, footer }: { data: MatchResearch; live?: Live; footer?: ReactNode }) {
  const { home, away, form, h2h, table, result } = data;
  const formSource = (f: TeamForm) => (f.source === "all" ? "all competitions" : data.league.name.split(" - ")[0]);
  return (
    <div className="wl-mbody">
      <div className="wl-col">
        <section className="wl-sec">
          <div className="wl-sec-head">
            <h3>What to watch</h3>
            <WatchMark watch={data.watch} />
          </div>
          {result?.status === "finished" ? (
            <p className="wl-sub">
              Written before kick-off. Each point is marked with how it went
              {result.label !== "FT" ? ", judged on the 90 minutes" : ""}.
            </p>
          ) : live ? (
            <p className="wl-sub">
              Written before kick-off. While it's played, each point shows where it stands; a tick means it can't
              be undone.
            </p>
          ) : null}
          {data.points.length ? (
            <ol className="wl-points">
              {data.points.map((p, i) => (
                <li key={p.key} data-n={i + 1} className={p.outcome ? `is-${p.outcome}` : ""}>
                  <div>
                    <b>{p.title}</b> <span>{p.detail}</span>
                    {p.outcome ? (
                      <p className="wl-verdict">
                        <OutcomeMark outcome={p.outcome} /> {p.outcome_note}
                      </p>
                    ) : live && !live.finished ? (
                      <p className="wl-verdict is-live">
                        {liveVerdict(p.key, `${live.home}-${live.away}`) ? (
                          <OutcomeMark outcome={liveVerdict(p.key, `${live.home}-${live.away}`)} />
                        ) : (
                          <i className="wl-live-dot" aria-hidden />
                        )}{" "}
                        {noteBeside(liveNote(p.key, `${live.home}-${live.away}`, home.name, away.name, live.minute)) ||
                          "Can't tell from the score yet."}
                      </p>
                    ) : null}
                  </div>
                </li>
              ))}
            </ol>
          ) : (
            <p className="wl-sub">Nothing stands out: both teams' recent games look like a normal game in this league.</p>
          )}
        </section>

        <section className="wl-sec">
          <h3>Every pattern, side by side</h3>
          <p className="wl-sub">
            How often each happened in the teams' last games, against the league average. Highlighted rows are the
            ones above.
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
          <p className="wl-sub">
            {result ? "Last 6 games before this one" : "Last 6 games"}, newest on the left. Hover a result for the
            opponent.
          </p>
          {(["home", "away"] as const).map((side) => {
            const team = side === "home" ? home : away;
            return (
              <div key={side} className="wl-form-row">
                <div className="wl-who">
                  <Crest src={team.badge} name={team.name} />
                  {team.name}
                </div>
                <FormPills form={form[side]} />
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

        <PlayerShots research={data} />
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
            <h3>{result ? "Table before kick-off" : "Table"}</h3>
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
                      <td className="wl-num">{row.goal_difference > 0 ? `+${row.goal_difference}` : row.goal_difference}</td>
                      <td className="wl-num">{row.points}</td>
                    </tr>,
                  ];
                })}
              </tbody>
            </table>
          </section>
        ) : null}

        {footer ? <section className="wl-sec">{footer}</section> : null}
      </div>
    </div>
  );
}

function MatchView({
  matchId,
  day,
  filter,
  layout,
  nav,
  onReady,
}: {
  matchId: string;
  day: DayKey;
  filter: Filter;
  layout: Layout;
  nav: Nav;
  onReady: () => void;
}) {
  const [refreshMs, setRefreshMs] = useState(0);
  const { data, error, loading } = useJson<MatchResearch>(`/api/watchlist/match/${matchId}`, refreshMs);
  const list = useJson<WatchlistDay>(`/api/watchlist/day/${day}`).data;
  const lives = useLive(day, Boolean(data && !data.result && started(data.kickoff)));
  const live = data && !data.result ? lives[matchId] : undefined;
  useEffect(() => {
    // Full time on the board: re-read until the marks are in.
    setRefreshMs(live?.finished ? 30_000 : 0);
  }, [live?.finished]);

  useEffect(() => {
    if (data) onReady();
  }, [data, onReady]);

  const pastDay = day !== "today" && day !== "tomorrow";
  const order = useMemo(
    () => (list?.status === "ready" ? orderedRows(list, filter, layout, pastDay) : []),
    [list, filter, layout, pastDay],
  );
  const at = order.findIndex((m) => m.match_id === matchId);
  const prev = at > 0 ? order[at - 1] : null;
  const next = at >= 0 && at < order.length - 1 ? order[at + 1] : null;

  useEffect(() => {
    if (prev) prefetch(`/api/watchlist/match/${prev.match_id}`);
    if (next) prefetch(`/api/watchlist/match/${next.match_id}`);
  }, [prev, next]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (isTyping(event) || event.altKey || event.metaKey || event.ctrlKey) return;
      if (event.key === "ArrowLeft" && prev) nav.go({ view: "match", day, matchId: prev.match_id }, { replace: true });
      if (event.key === "ArrowRight" && next) nav.go({ view: "match", day, matchId: next.match_id }, { replace: true });
      if (event.key === "Escape") nav.back({ view: "day", day });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [prev, next, day, nav]);

  useEffect(() => {
    if (data) document.title = `${data.home.name} v ${data.away.name} · Kalchas`;
  }, [data]);

  const backTo: Route = { view: "day", day };
  const crumb = (
    <a href={`/${day}`} className="wl-back" onClick={linkTo(() => nav.back(backTo))}>
      ← {backLabel(day, list?.day)}
    </a>
  );

  if (loading) return <p className="wl-empty">Loading…</p>;
  if (error || !data) {
    return (
      <div className="wl-card">
        <p className="wl-empty">
          {error === "not_found"
            ? "This match isn't on the watchlist."
            : "The match page is unavailable right now. Try again in a minute."}
        </p>
        <p className="wl-empty">
          {crumb}
          {" · "}
          <a href="/calendar" onClick={linkTo(() => nav.go({ view: "calendar", month: null }))}>
            Calendar
          </a>
        </p>
      </div>
    );
  }

  const { home, away, odds, result } = data;
  const stepper = (
    <div className="wl-stepper">
      {prev ? (
        <a
          href={`/${day}/${prev.match_id}`}
          onClick={linkTo(() => nav.go({ view: "match", day, matchId: prev.match_id }, { replace: true }))}
          title={`${prev.home.name} v ${prev.away.name}`}
        >
          ‹ Previous
        </a>
      ) : (
        <span className="is-off">‹ Previous</span>
      )}
      {at >= 0 ? (
        <span className="wl-stepper-n">
          {at + 1} of {order.length}
        </span>
      ) : null}
      {next ? (
        <a
          href={`/${day}/${next.match_id}`}
          onClick={linkTo(() => nav.go({ view: "match", day, matchId: next.match_id }, { replace: true }))}
          title={`${next.home.name} v ${next.away.name}`}
        >
          Next ›
        </a>
      ) : (
        <span className="is-off">Next ›</span>
      )}
    </div>
  );

  return (
    <div className="wl-card">
      <header className="wl-mhead">
        <div className="wl-crumb">
          {crumb}
          <span className="wl-crumb-league">
            {data.league.country} · {data.league.name}
            {data.league.round ? ` · Round ${data.league.round}` : ""}
          </span>
          {stepper}
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
          <MatchCentre data={data} live={live} />
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
        <GoalLine data={data} />
        {odds ? (
          <div className="wl-mprices">
            {result ? <span className="wl-mprices-lab">Prices before kick-off</span> : null}
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

      <ResearchBody
        data={data}
        live={live}
        footer={
          <p className="wl-sub">
            {result || live
              ? `Written ${dayLabel(data.built_at.slice(0, 10))} at ${clock(data.built_at)}, before kick-off, and left unchanged since.`
              : `Updated ${clock(data.built_at)}. Patterns come from results only. Team news and line-ups are not included yet, so check them before kick-off.`}{" "}
            Use ← and → for the previous and next match.
          </p>
        }
      />
      <footer className="wl-mfoot">
        {crumb}
        {stepper}
      </footer>
    </div>
  );
}

/* ------------------------------------------------------------------ app */

type HistoryState = { scroll?: number; from?: string } | null;

function titleFor(route: Route): string {
  if (route.view === "calendar") return "Watchlist calendar · Kalchas";
  if (route.view === "match") return "Match research · Kalchas";
  if (route.view === "parlay") {
    if (route.day === "today") return "Today's parlay · Kalchas";
    if (route.day === "tomorrow") return "Tomorrow's parlay · Kalchas";
    return `Parlay · ${dayLabel(route.day)} · Kalchas`;
  }
  if (route.day === "today") return "Today's watchlist · Kalchas";
  if (route.day === "tomorrow") return "Tomorrow's watchlist · Kalchas";
  return `Watchlist · ${dayLabel(route.day)} · Kalchas`;
}

export function WatchlistApp() {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.pathname));
  const [filter, setFilter] = useState<Filter>("all");
  const [parlayLegs, setParlayLegs] = useState(5);
  const [parlayStyle, setParlayStyle] = useState<ParlayStyle>("balanced");
  const [layout, setLayoutState] = useState<Layout>(savedLayout);
  const setLayout = useCallback((next: Layout) => {
    setLayoutState(next);
    saveLayout(next);
  }, []);
  const [recent, setRecent] = useState<string | null>(null);
  const pendingScroll = useRef<number | null>(null);
  const current = useRef(route);
  current.current = route;

  useEffect(() => {
    if ("scrollRestoration" in window.history) window.history.scrollRestoration = "manual";
    const onPop = (event: PopStateEvent) => {
      const state = event.state as HistoryState;
      const left = current.current;
      pendingScroll.current = state?.scroll ?? 0;
      setRecent(left.view === "match" ? left.matchId : null);
      setRoute(parseRoute(window.location.pathname));
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const go = useCallback(
    (next: Route, options?: { replace?: boolean }) => {
      const here = window.location.pathname;
      const path = routePath(next);
      if (path === here) return;
      const leaving = route.view === "match" ? route.matchId : null;
      if (options?.replace) {
        // Stepping match to match: one history entry, so Back still means
        // "the list I came from".
        window.history.replaceState({ ...(window.history.state as object), scroll: 0 }, "", path);
      } else {
        // Remember where this page was scrolled, so coming back lands there.
        window.history.replaceState({ ...(window.history.state as object), scroll: window.scrollY }, "");
        window.history.pushState({ scroll: 0, from: here } satisfies HistoryState, "", path);
      }
      pendingScroll.current = null;
      setRecent(next.view === "day" ? leaving : null);
      setRoute(next);
      window.scrollTo({ top: 0 });
    },
    [route],
  );

  const back = useCallback(
    (target: Route) => {
      // The list this page was opened from: go back in history, so it comes
      // back scrolled where it was. Otherwise it's a fresh visit.
      const state = window.history.state as HistoryState;
      if (state?.from === routePath(target)) {
        window.history.back();
        return;
      }
      go(target);
    },
    [go],
  );

  const nav = useMemo<Nav>(() => ({ go, back }), [go, back]);

  const onReady = useCallback(() => {
    const y = pendingScroll.current;
    if (y == null) {
      // Arrived from a match without history: bring that match into view.
      if (recent) {
        const el = document.querySelector(`[data-match="${recent}"]`);
        if (el && el.getBoundingClientRect().top > window.innerHeight) el.scrollIntoView({ block: "center" });
      }
      return;
    }
    pendingScroll.current = null;
    requestAnimationFrame(() => {
      window.scrollTo({ top: y });
      // Stepped on to other matches since: show the last one opened.
      const el = recent ? document.querySelector(`[data-match="${recent}"]`) : null;
      const box = el?.getBoundingClientRect();
      if (el && box && (box.bottom < 0 || box.top > window.innerHeight)) el.scrollIntoView({ block: "center" });
    });
  }, [recent]);

  // The visit log: these pages don't poll the live board, so they keep the
  // visit going themselves, and note what was opened (once per visit).
  const visitor = useMemo(visitorId, []);
  const pinged = useRef<Promise<void> | null>(null);
  useEffect(() => {
    pinged.current = pingVisit(visitor, document.referrer);
    const timer = window.setInterval(() => {
      if (!document.hidden) void pingVisit(visitor);
    }, VISIT_PING_MS);
    return () => window.clearInterval(timer);
  }, [visitor]);
  useEffect(() => {
    const event = visitEventFor(route);
    if (event) void pinged.current?.then(() => logVisitEvent(event, visitor));
  }, [route, visitor]);

  useEffect(() => {
    // A match page names its teams once it has loaded (MatchView).
    if (route.view !== "match") document.title = titleFor(route);
  }, [route]);

  let page: ReactNode;
  if (route.view === "calendar") {
    page = <CalendarView month={route.month} nav={nav} onReady={onReady} />;
  } else if (route.view === "parlay") {
    page = (
      <ParlayView
        day={route.day}
        legs={parlayLegs}
        setLegs={setParlayLegs}
        style={parlayStyle}
        setStyle={setParlayStyle}
        nav={nav}
        onReady={onReady}
      />
    );
  } else if (route.view === "match") {
    page = (
      <MatchView
        key={route.matchId}
        matchId={route.matchId}
        day={route.day}
        filter={filter}
        layout={layout}
        nav={nav}
        onReady={onReady}
      />
    );
  } else {
    page = (
      <DayView
        day={route.day}
        filter={filter}
        setFilter={setFilter}
        layout={layout}
        setLayout={setLayout}
        recent={recent}
        nav={nav}
        onReady={onReady}
      />
    );
  }

  return (
    <div className="wl-shell">
      <header className="hero wl-hero">
        <div className="hero-left">
          <BrandIdentity heading={false} />
        </div>
        <PageSwitch route={route} nav={nav} />
      </header>
      {page}
    </div>
  );
}
