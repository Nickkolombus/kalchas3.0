/**
 * Watchlist picks on the live board: the hero button, the strong-watch mark
 * on board rows, and the box in the match overlay. One fetch feeds all three.
 */
import { createContext, useContext, useEffect, useMemo, useState, type MouseEvent, type ReactNode } from "react";
import { HoverTip } from "./HoverTip";

type Outcome = "landed" | "missed";

export type Pick = {
  match_id: string;
  day: string;
  kickoff: string;
  home: { name: string };
  away: { name: string };
  lead_key: string;
  tag: string;
  headline: string;
  reason: string;
  result?: { status: "finished" | "off"; label: string; home?: number | null; away?: number | null } | null;
  outcome?: Outcome | null;
  outcome_note?: string;
};

type LivePicks = { today: string; next?: Pick | null; picks: Pick[] };

type PicksState = { today: string | null; byId: Map<string, Pick>; next: Pick | null };

const PicksContext = createContext<PicksState>({ today: null, byId: new Map(), next: null });

const REFRESH_MS = 5 * 60_000;

/** Fetches the strong watches every few minutes and works out, minute by
 * minute, which is the next one still to kick off. */
export function PicksProvider({ children }: { children: ReactNode }) {
  const [data, setData] = useState<LivePicks | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    let alive = true;
    const load = () =>
      fetch("/api/watchlist/picks")
        .then((res) => (res.ok ? (res.json() as Promise<LivePicks>) : null))
        .then((body) => {
          if (alive && body) setData(body);
        })
        .catch(() => undefined);
    void load();
    const refresh = window.setInterval(load, REFRESH_MS);
    const tick = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => {
      alive = false;
      window.clearInterval(refresh);
      window.clearInterval(tick);
    };
  }, []);

  const value = useMemo<PicksState>(() => {
    const picks = data?.picks ?? [];
    const next =
      picks
        .filter((p) => p.day === data?.today && Date.parse(p.kickoff) > now)
        .sort((a, b) => a.kickoff.localeCompare(b.kickoff))[0] ?? null;
    return { today: data?.today ?? null, byId: new Map(picks.map((p) => [p.match_id, p])), next };
  }, [data, now]);

  return <PicksContext.Provider value={value}>{children}</PicksContext.Provider>;
}

export function usePick(matchId: string | null | undefined): Pick | null {
  const { byId } = useContext(PicksContext);
  return matchId ? (byId.get(String(matchId)) ?? null) : null;
}

function pickHref(pick: Pick, today: string | null): string {
  return `/${pick.day === today ? "today" : pick.day}/${pick.match_id}`;
}

function clock(iso: string): string {
  const at = new Date(iso);
  return Number.isNaN(at.getTime()) ? "" : at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

/** A spyglass on a tripod: the watchlist's mark everywhere on the site. */
export function SpyglassIcon({ size = 18 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <g transform="rotate(-25 12 9)">
        <rect x="2" y="7.6" width="3.2" height="2.8" rx="0.7" />
        <rect x="5.2" y="6.6" width="15" height="4.8" rx="1" />
        <path d="M16 6.6v4.8" />
      </g>
      <path d="M12 12.2l-4 9M12 12.2l4 9M12 12.2v9" />
    </svg>
  );
}

/* ---------------------------------------------------------------- hero */

/** "Watchlist picks", and while one is still to come today, the next
 * strong watch. Always opens today's list. Sized as a hero tile, the same
 * height as the join buttons beside it. */
export function WatchlistButton() {
  const { next } = useContext(PicksContext);
  return (
    <a className="wl-entry" href="/today">
      <span className="wl-entry-icon">
        <SpyglassIcon size={28} />
      </span>
      <b>Watchlist picks</b>
      <span className="wl-entry-next">
        {next ? (
          <>
            Next <i>{clock(next.kickoff)}</i> {next.home.name} v {next.away.name}
          </>
        ) : (
          "Today's list"
        )}
      </span>
    </a>
  );
}

/* ------------------------------------------------------------ live notes */

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

/** One line on where the lead pattern stands right now, from the live score.
 * Empty when the score alone can't say (late goals, cards). */
export function liveNote(key: string, score: string, home: string, away: string, minute: number): string {
  const m = /^(\d+)\s*[-–]\s*(\d+)/.exec(score || "");
  if (!m) return "";
  const hs = Number(m[1]);
  const as = Number(m[2]);
  const total = hs + as;
  const need = (line: number) => line - total;
  switch (key) {
    case "btts_yes":
      if (hs && as) return "Both have scored: landed.";
      if (hs) return `${away} still need a goal.`;
      if (as) return `${home} still need a goal.`;
      return "Both teams still need a goal.";
    case "btts_no":
      return hs && as ? "Both have scored: missed." : "Holding: one side hasn't scored.";
    case "over_2_5":
    case "over_3_5": {
      const line = key === "over_2_5" ? 3 : 4;
      return need(line) <= 0 ? `${plural(total, "goal")} in: landed.` : `${plural(need(line), "more goal")} needed.`;
    }
    case "under_2_5":
      return total >= 3 ? `${plural(total, "goal")} in: missed.` : `Holding at ${plural(total, "goal")}.`;
    case "team_over_1_5_home":
    case "team_over_1_5_away": {
      const [name, goals] = key.endsWith("home") ? [home, hs] : [away, as];
      return goals >= 2 ? `${name} have ${goals}: landed.` : `${name} need ${2 - goals} more.`;
    }
    case "first_half_goal":
      if (total && minute <= 45) return "A first-half goal is in: landed.";
      return minute > 45 ? "" : "No goal yet before half-time.";
    case "late_goal":
      return minute < 75 ? "The window opens at 75'." : "";
    default:
      return "";
  }
}

/** Already decided while the match is still on: goals can't be taken back,
 * so "3 goals in" has landed an over 2.5 for good. `null` while it's open. */
export function liveVerdict(key: string, score: string): Outcome | null {
  const m = /^(\d+)\s*[-–]\s*(\d+)/.exec(score || "");
  if (!m) return null;
  const hs = Number(m[1]);
  const as = Number(m[2]);
  const total = hs + as;
  switch (key) {
    case "btts_yes":
      return hs && as ? "landed" : null;
    case "btts_no":
      return hs && as ? "missed" : null;
    case "over_2_5":
      return total >= 3 ? "landed" : null;
    case "over_3_5":
      return total >= 4 ? "landed" : null;
    case "under_2_5":
      return total >= 3 ? "missed" : null;
    case "team_over_1_5_home":
      return hs >= 2 ? "landed" : null;
    case "team_over_1_5_away":
      return as >= 2 ? "landed" : null;
    case "home_scoring_run":
      return hs ? "landed" : null;
    case "away_scoring_run":
      return as ? "landed" : null;
    case "leaky_home":
      return as ? "landed" : null;
    case "leaky_away":
      return hs ? "landed" : null;
    case "blanks_home":
      return hs ? "missed" : null;
    case "blanks_away":
      return as ? "missed" : null;
    default:
      return null;
  }
}

/** The team a pattern is about: "away over 1.5" belongs next to the away side. */
export function pickSide(key: string): "home" | "away" {
  return key.endsWith("_away") || key.startsWith("away_") ? "away" : "home";
}

/* ------------------------------------------------------------ board mark */

/** The strong-watch tag on the desktop board, next to the team its pattern
 * is about (match-wide patterns sit with the home side). */
export function PickTag({
  matchId,
  score,
  minute,
  side,
}: {
  matchId: string;
  score: string;
  minute: number;
  side: "home" | "away";
}) {
  const { today } = useContext(PicksContext);
  const pick = usePick(matchId);
  if (!pick || pickSide(pick.lead_key) !== side) return null;
  const decided = pick.outcome ?? liveVerdict(pick.lead_key, score);
  const note = pick.outcome ? pick.outcome_note : liveNote(pick.lead_key, score, pick.home.name, pick.away.name, minute);
  const stop = (event: MouseEvent) => event.stopPropagation();
  return (
    <span className="pick-mark" data-hover-stop onClick={stop} onMouseDown={stop}>
      <HoverTip
        anchorClass="pick-anchor"
        cardClass="hover-card-pick"
        body={
          <div className="pick-tip">
            <p className="pick-tip-k">Watchlist pick · strong watch</p>
            <p>
              <b>{pick.headline}</b> {pick.reason}
            </p>
            {note ? (
              <p className="pick-tip-now">
                {pick.outcome ? (pick.outcome === "landed" ? "Landed. " : "Missed. ") : "Now: "}
                {note}
              </p>
            ) : null}
            <p className="pick-tip-go">Click the tag for the research page.</p>
          </div>
        }
      >
        <a
          className={`pick-tag${decided ? ` is-${decided}` : ""}`}
          href={pickHref(pick, today)}
          title={decided === "landed" ? "Landed" : decided === "missed" ? "Missed" : undefined}
        >
          <SpyglassIcon size={12} />
          {decided ? <i aria-hidden>{decided === "landed" ? "✓" : "✗"}</i> : null}
          {pick.tag}
        </a>
      </HoverTip>
    </span>
  );
}

/* --------------------------------------------------------- overlay box */

/** At the top of the match overlay: what Kalchas expected and how it stands. */
export function PickBox({ matchId, score, minute }: { matchId: string; score: string; minute: number }) {
  const { today } = useContext(PicksContext);
  const pick = usePick(matchId);
  if (!pick) return null;
  const note = pick.outcome ? pick.outcome_note : liveNote(pick.lead_key, score, pick.home.name, pick.away.name, minute);
  return (
    <section className="pick-box" aria-label="Watchlist pick">
      <p className="pick-box-k">
        <SpyglassIcon size={13} />
        Watchlist pick · strong watch
      </p>
      <p>
        <b>{pick.headline}</b> {pick.reason}
      </p>
      {note ? (
        <p className="pick-box-now">
          {pick.outcome ? (pick.outcome === "landed" ? "Landed. " : "Missed. ") : "Now: "}
          {note}
        </p>
      ) : null}
      <a href={pickHref(pick, today)}>Open the research page →</a>
    </section>
  );
}
