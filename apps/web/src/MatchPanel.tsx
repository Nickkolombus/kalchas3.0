import { useEffect, useMemo, useState, type ReactNode } from "react";
import { ResearchBody, type Live, type MatchResearch } from "./Watchlist";
import { PickBox } from "./WatchlistPicks";
import { logVisitEvent } from "./visit";
import {
  HoverLedger,
  HoverTip,
  hoverBarPct,
  hoverLead,
  phiInk,
  windowLabel,
  windowRecipe,
  type HoverScale,
  type WindowBlock,
} from "./HoverTip";

type SideValue = { home: number; away: number };
type TeamCell = {
  value: number | null;
  triggered?: boolean;
  note?: string | null;
  delivered?: boolean;
};
type StrategyBlock = {
  teams: { home?: TeamCell; away?: TeamCell };
  threshold?: number;
  match?: number | null;
};

type MatchEvent = {
  event_type: string;
  minute: number;
  side: string;
  team?: string | null;
  player_name?: string | null;
  detail?: string | null;
};

type LineupPlayer = { player: string; number: string; position: string };
type TeamLineup = {
  starting: LineupPlayer[];
  substitutes: LineupPlayer[];
  coach?: string | null;
};

type Substitution = {
  minute: number;
  side: string;
  player_out: string;
  player_in: string;
};

type TimelinePoint = {
  minute: number;
  dangerous_attacks: SideValue;
  attacks: SideValue;
  shots_on_target: SideValue;
  possession: SideValue;
  rule_of_three: SideValue;
  kscore: number;
};

export type OverlayMatch = {
  match_id: string;
  home_team: string;
  away_team: string;
  minute: number;
  score: string;
  league?: string | null;
  status_short?: string | null;
  minute_display?: string | null;
  home_team_id?: number | null;
  away_team_id?: number | null;
  home_team_logo?: string | null;
  away_team_logo?: string | null;
  stat_lines?: Record<string, SideValue>;
  strategy_status?: Record<string, StrategyBlock>;
  goal_events?: { minute: number; side: string }[];
  card_events?: MatchEvent[];
};

type MatchPanel = {
  match_id: string;
  home_team: string;
  away_team: string;
  minute: number;
  score: string;
  league?: string | null;
  status_short?: string | null;
  minute_display?: string | null;
  home_team_id?: number | null;
  away_team_id?: number | null;
  home_team_logo?: string | null;
  away_team_logo?: string | null;
  stat_lines: Record<string, SideValue>;
  strategy_status: Record<string, StrategyBlock>;
  events: MatchEvent[];
  substitutions: Substitution[];
  timeline: TimelinePoint[];
  lineup: { home: TeamLineup; away: TeamLineup };
  last_5min?: WindowBlock | null;
  last_10min?: WindowBlock | null;
};

type H2HCount = { count: number; pct: number; team?: string | null };
type H2HFixture = {
  match_id: string;
  home_team: string;
  away_team: string;
  home_score: number;
  away_score: number;
    match_date: string;
  league_name?: string;
  home_team_id?: number;
  away_team_id?: number;
};
type H2HTiming = {
  sample: number;
  late_goals: H2HCount;
  final_15: H2HCount;
  stoppage_time_goals: H2HCount;
  early_goals_15: H2HCount;
  fast_start_10: H2HCount;
  first_half_goals: H2HCount;
  btts_first_half: H2HCount;
  first_goal_before_30: H2HCount;
};

function leagueRankLabel(rank?: number | null): string {
  if (rank == null || rank < 1) return "";
  const mod = rank % 100;
  const suffix =
    mod >= 11 && mod <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" }[rank % 10] ?? "th");
  return `${rank}${suffix}`;
}

type H2HData = {
  home_team: string;
  away_team: string;
  insufficient: boolean;
  reason?: string | null;
  summary: { home_wins: number; draws: number; away_wins: number; sample: number };
  home_rank?: number | null;
  away_rank?: number | null;
  fixtures: H2HFixture[];
  patterns: {
    sample: number;
    over_2_5: H2HCount;
    under_2_5: H2HCount;
    btts: H2HCount;
    home_cs: H2HCount;
    away_cs: H2HCount;
    avg_goals: number | null;
    home_goals: number;
    away_goals: number;
    timing?: H2HTiming | null;
  };
};

const TIMING_SLOTS: { key: keyof H2HTiming; label: string; threshold: number }[] = [
  { key: "late_goals", label: "Late goals (70'+)", threshold: 75 },
  { key: "first_goal_before_30", label: "1st goal before 30'", threshold: 75 },
  { key: "final_15", label: "Goals in final 15 min", threshold: 75 },
  { key: "early_goals_15", label: "Early goals (0-15')", threshold: 75 },
  { key: "first_half_goals", label: "1st-half goals", threshold: 80 },
  { key: "btts_first_half", label: "BTTS in 1st half", threshold: 75 },
];

type TabId = "signals" | "stats" | "timeline" | "before" | "lineups";

const TABS: { id: TabId; label: string }[] = [
  { id: "signals", label: "Signals" },
  { id: "stats", label: "Stats" },
  { id: "timeline", label: "Timeline" },
  { id: "before", label: "Before kick-off" },
  { id: "lineups", label: "Line-ups" },
];

const STAT_BARS: { key: string; label: string }[] = [
  { key: "shots_on_target", label: "Shots on target" },
  { key: "shots_off_target", label: "Shots off target" },
  { key: "attacks", label: "Attacks" },
  { key: "dangerous_attacks", label: "Dangerous attacks" },
  { key: "corners", label: "Corners" },
  { key: "possession", label: "Possession %" },
  { key: "yellow_cards", label: "Yellow cards" },
  { key: "red_cards", label: "Red cards" },
];

const STRAT_ROWS: {
  key: string;
  label: string;
  digits: number;
  tip: string;
  /** The "What's normal" column on the Signals tab. */
  normal: string;
  suffix?: string;
  signed?: boolean;
  tone: string;
  scale: HoverScale;
}[] = [
  {
    key: "rule_of_three",
    normal: "Around 1 is worth a look",
    label: "Unrealised goals",
    digits: 1,
    tone: "urg",
    scale: { min: -1, max: 3 },
    tip: "Shots say they should have scored more. Around 1 is worth a look. Negative means the score is already ahead of the chances.",
  },
  {
    key: "delta_5min",
    normal: "4 is common, 8+ is a wave",
    label: "5-minute pressure",
    digits: 1,
    tone: "d5",
    scale: { min: 0, max: 12 },
    tip: "Pressure in the last 5 minutes. 4 is common. 8+ is a real wave.",
  },
  {
    key: "pressure_index",
    normal: "70 is a surge, 90+ a siege",
    label: "Sustained pressure",
    digits: 0,
    tone: "d10",
    scale: { min: 0, max: 100 },
    tip: "Pressure over about 10 minutes, out of 100. 70 is a surge. 90+ is a siege.",
  },
  {
    key: "delta_goal",
    normal: "1.0 = a goal behind their pace",
    label: "Form Bar",
    digits: 1,
    tone: "lbar",
    scale: { min: -2, max: 2 },
    tip: "Goals behind the pace their form sets: their median scored and the opponent's median conceded over the last 10 games, spread over 90 minutes. 1.0 is a goal behind. Ahead means they have scored more than their pace so far. Done means they already have their full expected share. Needs 5+ recent games, or reads blank.",
  },
  {
    key: "npei",
    normal: "Attacks turned into shots, out of 100",
    label: "Efficiency",
    digits: 0,
    tone: "phi",
    scale: { min: 0, max: 100 },
    tip: "How well attacks become shots, out of 100. A higher number means more shots from the same attacks.",
  },
  {
    key: "kscore",
    normal: "60+ is a picked match",
    label: "K-Score",
    digits: 0,
    tone: "k",
    scale: { min: 0, max: 100 },
    tip: "Blend of the other signals, out of 100. 60+ is a picked match.",
  },
];

function fmt(v: number | undefined | null, digits = 0): string {
  if (v === undefined || v === null || Number.isNaN(v)) return "—";
  return Number.isInteger(v) && digits === 0 ? String(v) : Number(v).toFixed(digits);
}

function fmtSignal(
  v: number | undefined | null,
  digits: number,
  extras?: { suffix?: string; signed?: boolean },
): string {
  if (v === undefined || v === null || Number.isNaN(v)) return "—";
  const core = extras?.signed && v > 0 ? `+${fmt(v, digits)}` : fmt(v, digits);
  return extras?.suffix && core !== "—" ? `${core}${extras.suffix}` : core;
}

/** Form Bar's words, matching the board: Done once delivered, Ahead for a negative gap. */
function formBarText(cell: TeamCell | undefined): string {
  if (cell?.delivered) return "Done";
  if (cell?.value == null) return "—";
  return cell.value < 0 ? "Ahead" : fmt(cell.value, 1);
}

function panelFromLive(match: OverlayMatch): MatchPanel {
  const events: MatchEvent[] = [
    ...(match.goal_events || []).map((event) => ({
      ...event,
      event_type: "goal",
      detail: "Goal",
    })),
    ...(match.card_events || []),
  ];
  return {
    match_id: match.match_id,
    home_team: match.home_team,
    away_team: match.away_team,
    minute: match.minute,
    minute_display: match.minute_display,
    score: match.score,
    league: match.league,
    status_short: match.status_short,
    home_team_id: match.home_team_id,
    away_team_id: match.away_team_id,
    home_team_logo: match.home_team_logo,
    away_team_logo: match.away_team_logo,
    stat_lines: match.stat_lines || {},
    strategy_status: match.strategy_status || {},
    events,
    substitutions: [],
    timeline: [],
    lineup: {
      home: { starting: [], substitutes: [], coach: null },
      away: { starting: [], substitutes: [], coach: null },
    },
  };
}

/** Fill uses non-negative signal only. Negative labels stay signed; they do not widen the bar. */
function overlayClock(
  minute: number,
  status?: string | null,
  display?: string | null,
  eventMinutes: number[] = [],
): string {
  const phase = (status || "").toUpperCase();
  if (phase === "HT") return "HT";
  let raw = (display || "").trim().replace(/′/g, "'").replace(/'$/, "");
  if (raw.includes("+")) {
    const plus = raw.indexOf("+");
    const baseS = raw.slice(0, plus);
    const stated = raw.slice(plus + 1);
    const base = Number(baseS);
    let added = /^\d+$/.test(stated) ? Number(stated) : 0;
    if (Number.isFinite(base)) {
      for (const eventMinute of eventMinutes) {
        if (eventMinute > base && eventMinute <= base + 15) {
          added = Math.max(added, eventMinute - base);
        }
      }
    }
    raw = added ? `${baseS}+${added}` : `${baseS}+`;
    const shownAdded = raw.split("+")[1] || "";
    return shownAdded ? `${baseS}'+${shownAdded}'` : `${baseS}+'`;
  }
  if (phase === "1H" && minute > 45) return `45'+${minute - 45}'`;
  if (phase === "2H" && minute > 90) return `90'+${minute - 90}'`;
  return `${minute}'`;
}

/** One signal as a table row: a value and small bar per team, what's normal,
 * and the same hover card on the name as before. */
function SignalRow({
  label,
  home,
  away,
  digits = 0,
  homeTriggered = false,
  awayTriggered = false,
  tip,
  suffix,
  signed = false,
  homeName,
  awayName,
  tone,
  scale,
  inkHome,
  inkAway,
  homeNote,
  awayNote,
  windowHeading,
  homeText,
  awayText,
  normal,
}: {
  label: string;
  home: number;
  away: number;
  digits?: number;
  homeTriggered?: boolean;
  awayTriggered?: boolean;
  tip?: string;
  suffix?: string;
  signed?: boolean;
  homeName?: string;
  awayName?: string;
  tone?: string;
  scale?: HoverScale;
  inkHome?: string;
  inkAway?: string;
  homeNote?: string;
  awayNote?: string;
  windowHeading?: string;
  /** Replaces the formatted number (Form Bar's Done / Ahead). */
  homeText?: string;
  awayText?: string;
  normal: string;
}) {
  const extras = { suffix, signed };
  const lead = hoverLead(
    { value: home, triggered: homeTriggered },
    { value: away, triggered: awayTriggered },
  );
  const title =
    homeName && awayName ? `${label} - ${homeName} vs ${awayName}` : label;
  const labelNode = tip ? (
    <HoverTip
      title={title}
      cardClass={tone ? `hover-tone-${tone}` : undefined}
      body={
        homeName && awayName ? (
          <HoverLedger
            tip={tip}
            homeName={homeName}
            awayName={awayName}
            homeValue={homeText ?? fmtSignal(home, digits, extras)}
            awayValue={awayText ?? fmtSignal(away, digits, extras)}
            homeLead={lead.home}
            awayLead={lead.away}
            homePct={hoverBarPct(home, scale)}
            awayPct={hoverBarPct(away, scale)}
            homeNote={homeNote}
            awayNote={awayNote}
            windowHeading={windowHeading}
          />
        ) : (
          <p>{tip}</p>
        )
      }
    >
      <span>{label}</span>
    </HoverTip>
  ) : (
    label
  );
  const cell = (value: number, text: string, triggered: boolean, ink?: string) => (
    <td className={`wl-num mp-sig-val${triggered ? " is-on" : ""}`}>
      <span style={ink && !triggered ? { color: ink } : undefined}>{text}</span>
      <span className="wl-mini" aria-hidden>
        <i style={{ width: `${Math.max(3, hoverBarPct(value, scale) ?? 0)}%` }} />
      </span>
    </td>
  );
  return (
    <tr className={homeTriggered || awayTriggered ? "is-on" : ""}>
      <th scope="row">{labelNode}</th>
      {cell(home, homeText ?? fmtSignal(home, digits, extras), homeTriggered, inkHome)}
      {cell(away, awayText ?? fmtSignal(away, digits, extras), awayTriggered, inkAway)}
      <td className="mp-sig-norm">{normal}</td>
    </tr>
  );
}

/** One match stat: the name in the middle, a number at each end, and a bar
 * split at the centre where each team fills its half by its share. */
function StatRow({ label, home, away }: { label: string; home: number; away: number }) {
  const total = home + away;
  const lead = home > away ? "home" : away > home ? "away" : null;
  const share = (value: number) => `${total > 0 ? (value / total) * 100 : 0}%`;
  return (
    <div className="mp-stat">
      <b className={lead === "home" ? "is-lead" : ""}>{fmt(home)}</b>
      <span>{label}</span>
      <b className={lead === "away" ? "is-lead" : ""}>{fmt(away)}</b>
      <span className="mp-stat-bars" aria-hidden>
        <span className="mp-half is-home">
          <i className={lead === "home" ? "is-lead" : ""} style={{ width: share(home) }} />
        </span>
        <span className="mp-half is-away">
          <i className={lead === "away" ? "is-lead" : ""} style={{ width: share(away) }} />
        </span>
      </span>
    </div>
  );
}

type PulsePoint = { minute: number; home: number; away: number };

function cumulativeToPerMinute(
  points: TimelinePoint[],
  homeOf: (point: TimelinePoint) => number,
  awayOf: (point: TimelinePoint) => number,
): PulsePoint[] {
  const series = [...points]
    .filter((point) => point.minute > 0)
    .sort((a, b) => a.minute - b.minute);
  if (!series.length) return [];
  const out: PulsePoint[] = [];
  let prevHome = 0;
  let prevAway = 0;
  let prevMinute = 0;
  for (const point of series) {
    const home = Math.max(0, homeOf(point));
    const away = Math.max(0, awayOf(point));
    const dHome = Math.max(0, home - prevHome);
    const dAway = Math.max(0, away - prevAway);
    const span = Math.max(1, point.minute - prevMinute);
    for (let minute = prevMinute + 1; minute <= point.minute; minute += 1) {
      out.push({
        minute,
        home: dHome / span,
        away: dAway / span,
      });
    }
    prevHome = home;
    prevAway = away;
    prevMinute = point.minute;
  }
  return out;
}

type TimelineView = "pressure" | "shots" | "unrealised";

const TIMELINE_VIEWS: { id: TimelineView; label: string; short: string }[] = [
  { id: "pressure", label: "Pressure", short: "Pressure" },
  { id: "shots", label: "Shots on target", short: "Shots" },
  { id: "unrealised", label: "Unrealised goals", short: "Unrealised" },
];

/** The graph's width until its box has been measured. */
const GRAPH_W = 900;
const GRAPH_LEFT = 26;
const GRAPH_RIGHT = 10;
const AXIS_MINUTES = [0, 15, 30, 45, 60, 75, 90];
/** Pressure is smoothed over five minutes, the middle one counting most. */
const MOMENTUM_WEIGHTS = [1, 2, 3, 2, 1];
// Rows of the drawing: home events, the plot, away events, the minute axis.
const HOME_ROW = 11;
const PLOT_TOP = 26;
const PLOT_BOTTOM = 166;
const AWAY_ROW = 181;
const GRAPH_H = 206;

/** One value per minute: who was on top. Each team's dangerous attacks per
 * minute, smoothed over five minutes, home minus away. */
function momentum(per: PulsePoint[]): { minute: number; home: number; away: number; net: number }[] {
  const byMinute = new Map(per.map((p) => [p.minute, p]));
  return per.map((p) => {
    let home = 0;
    let away = 0;
    let weight = 0;
    MOMENTUM_WEIGHTS.forEach((w, i) => {
      const at = byMinute.get(p.minute + i - 2);
      if (!at) return;
      home += w * at.home;
      away += w * at.away;
      weight += w;
    });
    home /= weight || 1;
    away /= weight || 1;
    return { minute: p.minute, home, away, net: home - away };
  });
}

/** The whole match on one short graph, like the momentum charts football
 * apps use: one thin bar a minute, above the line when the home side was on
 * top and below when the away side was. Goals and cards sit above the graph
 * for the home team and below it for the away team. The switch shows shots
 * on target the same way, or unrealised goals as two lines; it always opens
 * on pressure. */
function TimelineGraph({
  points,
  story,
  homeName,
  awayName,
  minute,
}: {
  points: TimelinePoint[];
  story: StoryEvent[];
  homeName: string;
  awayName: string;
  minute: number;
}) {
  const [view, setView] = useState<TimelineView>("pressure");
  // Drawn at its real width, so text stays 11px on a phone as on a laptop.
  const [plot, setPlot] = useState<HTMLDivElement | null>(null);
  const [W, setW] = useState(GRAPH_W);
  useEffect(() => {
    if (!plot) return;
    const measure = () => setW(Math.max(280, Math.round(plot.clientWidth)));
    measure();
    const watcher = new ResizeObserver(measure);
    watcher.observe(plot);
    return () => watcher.disconnect();
  }, [plot]);

  const last = Math.max(90, minute, ...points.map((p) => p.minute), ...story.map((e) => e.minute));
  const x = (m: number) => GRAPH_LEFT + (m / last) * (W - GRAPH_LEFT - GRAPH_RIGHT);
  const step = x(1) - x(0);
  const barWidth = Math.max(1.5, step - Math.min(1.5, step * 0.25));
  const mid = (PLOT_TOP + PLOT_BOTTOM) / 2;
  const half = (PLOT_BOTTOM - PLOT_TOP) / 2;
  const events = story.filter((e) => e.kind !== "sub");
  const blurb = {
    pressure: `Who was on top, minute by minute: above the line when ${homeName} had more dangerous attacks, below when ${awayName} did. Goals and cards sit on their team's side.`,
    shots: `Shots on target, minute by minute: ${homeName} above the line, ${awayName} below.`,
    unrealised: `Shots against the scoreboard, minute by minute. Above 1, a goal is overdue; below 0, they've scored more than their chances.`,
  }[view];

  const axis = (
    <g transform={`translate(0,${GRAPH_H - 2})`}>
      {AXIS_MINUTES.map((m) => (
        <text key={m} className="mp-tl-ax" x={x(m)} textAnchor="middle">
          {m}&apos;
        </text>
      ))}
    </g>
  );
  const halfTime = <line className="mp-tl-ht" x1={x(45)} x2={x(45)} y1={PLOT_TOP} y2={PLOT_BOTTOM} />;

  // Goals and cards in a row above (home) or below (away) the plot. A goal's
  // score sits to its right, or to its left when the next goal or card on
  // that side is too close.
  const marks = events.map((e, i) => {
    const row = e.side === "away" ? AWAY_ROW : HOME_ROW;
    const cx = x(e.minute - 0.5);
    if (e.kind === "card") {
      const tone = cardTone(e.detail);
      return (
        <rect key={`e${i}`} className={`mp-tl-card is-${tone}`} x={cx - 3.5} y={row - 5} width={7} height={10} rx={1.5}>
          <title>{`${e.minute}' ${tone === "red" ? "red card" : "yellow card"}: ${e.player}`}</title>
        </rect>
      );
    }
    const next = events.slice(i + 1).find((n) => n.side === e.side);
    const crowded = (next && x(next.minute) - x(e.minute) < 38) || cx > W - 40;
    return (
      <g key={`e${i}`}>
        <title>{`${e.minute}' goal: ${e.player} ${(e.scoreAfter ?? "").replace("-", "–")}`}</title>
        <circle className="mp-tl-goal" cx={cx} cy={row} r={5.5} />
        <text
          className="mp-tl-goal-l"
          x={crowded ? cx - 9 : cx + 9}
          y={row + 4}
          textAnchor={crowded ? "end" : "start"}
        >
          {(e.scoreAfter ?? "").replace("-", "–")}
        </text>
      </g>
    );
  });

  let body: ReactNode;
  if (!points.some((p) => p.minute > 0)) {
    body = null;
  } else if (view === "unrealised") {
    const lo = -1;
    const hi = 3;
    const y = (v: number) => PLOT_BOTTOM - ((Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo)) * (PLOT_BOTTOM - PLOT_TOP);
    const line = (of: (p: TimelinePoint) => number) =>
      points
        .filter((p) => p.minute > 0)
        .sort((a, b) => a.minute - b.minute)
        .map((p, i) => `${i ? "L" : "M"}${x(p.minute).toFixed(1)},${y(of(p)).toFixed(1)}`)
        .join("");
    body = (
      <>
        {[-1, 0, 1, 2, 3].map((v) => (
          <g key={v}>
            <line className="mp-tl-grid" x1={GRAPH_LEFT} x2={W - GRAPH_RIGHT} y1={y(v)} y2={y(v)} />
            <text className="mp-tl-ax" x={GRAPH_LEFT - 8} y={y(v) + 4} textAnchor="end">
              {v}
            </text>
          </g>
        ))}
        <line className="mp-tl-due" x1={GRAPH_LEFT} x2={W - GRAPH_RIGHT} y1={y(1)} y2={y(1)} />
        <text className="mp-tl-due-l" x={W - GRAPH_RIGHT} y={y(1) - 5} textAnchor="end">
          1 = a goal is due
        </text>
        {halfTime}
        <path className="mp-tl-line is-home" d={line((p) => Number(p.rule_of_three.home || 0))} />
        <path className="mp-tl-line is-away" d={line((p) => Number(p.rule_of_three.away || 0))} />
      </>
    );
  } else if (view === "shots") {
    const per = cumulativeToPerMinute(
      points,
      (p) => Number(p.shots_on_target.home || 0),
      (p) => Number(p.shots_on_target.away || 0),
    );
    const peak = Math.max(1, ...per.map((p) => Math.max(p.home, p.away)));
    body = (
      <>
        {halfTime}
        {per.map((p) => {
          const left = x(p.minute - 1) + (step - barWidth) / 2;
          const hh = (p.home / peak) * half;
          const ha = (p.away / peak) * half;
          if (hh <= 0 && ha <= 0) return null;
          return (
            <g key={p.minute}>
              <title>{`${p.minute}': ${homeName} ${Math.round(p.home)}, ${awayName} ${Math.round(p.away)} on target`}</title>
              {hh > 0 ? <rect className="mp-tl-bar is-home" x={left} y={mid - hh} width={barWidth} height={hh} rx={1} /> : null}
              {ha > 0 ? <rect className="mp-tl-bar is-away" x={left} y={mid} width={barWidth} height={ha} rx={1} /> : null}
            </g>
          );
        })}
        <line className="mp-tl-mid" x1={GRAPH_LEFT} x2={W - GRAPH_RIGHT} y1={mid} y2={mid} />
      </>
    );
  } else {
    const per = cumulativeToPerMinute(
      points,
      (p) => Number(p.dangerous_attacks.home || 0),
      (p) => Number(p.dangerous_attacks.away || 0),
    );
    const flow = momentum(per);
    const peak = Math.max(0.6, ...flow.map((p) => Math.abs(p.net)));
    body = (
      <>
        {halfTime}
        {flow.map((p) => {
          const h = (Math.abs(p.net) / peak) * half;
          if (h < 0.5) return null;
          const home = p.net > 0;
          return (
            <rect
              key={p.minute}
              className={`mp-tl-bar ${home ? "is-home" : "is-away"}`}
              x={x(p.minute - 1) + (step - barWidth) / 2}
              y={home ? mid - h : mid}
              width={barWidth}
              height={h}
              rx={1}
            >
              <title>{`${p.minute}': ${home ? homeName : awayName} on top (dangerous attacks a minute, over 5 minutes: ${homeName} ${p.home.toFixed(1)}, ${awayName} ${p.away.toFixed(1)})`}</title>
            </rect>
          );
        })}
        <line className="mp-tl-mid" x1={GRAPH_LEFT} x2={W - GRAPH_RIGHT} y1={mid} y2={mid} />
      </>
    );
  }

  return (
    <section className="wl-sec mp-tl">
      <div className="mp-tl-head">
        <h3>Timeline</h3>
        <div className="mp-seg" role="group" aria-label="Graph">
          {TIMELINE_VIEWS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={view === item.id ? "on" : ""}
              aria-pressed={view === item.id}
              onClick={() => setView(item.id)}
            >
              <span className="mp-seg-long">{item.label}</span>
              <span className="mp-seg-short">{item.short}</span>
            </button>
          ))}
        </div>
        <p className="wl-sub">{blurb}</p>
      </div>
      <div className="mp-keys">
        <span>
          <i className="is-home" />
          {homeName}
          {view === "unrealised" ? "" : " ↑"}
        </span>
        <span>
          {awayName}
          {view === "unrealised" ? "" : " ↓"}
          <i className="is-away" />
        </span>
      </div>
      <div ref={setPlot} className="mp-tl-plot">
        {body ? (
          <svg viewBox={`0 0 ${W} ${GRAPH_H}`} role="img" aria-label={`Timeline: ${blurb}`}>
            {body}
            {marks}
            {axis}
          </svg>
        ) : (
          <p className="wl-sub mp-tl-empty">The minute-by-minute feed for this match isn&apos;t in yet.</p>
        )}
      </div>
    </section>
  );
}

type StoryEvent = {
  kind: "goal" | "card" | "sub";
  minute: number;
  side: string;
  player: string;
  detail: string;
  scoreAfter?: string;
};

function formatScore(home: number, away: number): string {
  return `${home}-${away}`;
}

function cardTone(detail: string): "yellow" | "red" {
  const text = detail.toLowerCase();
  if (text.includes("second") || text.includes("red")) return "red";
  return "yellow";
}

function collapseStoryEvents(rows: StoryEvent[]): StoryEvent[] {
  const drop = new Set<StoryEvent>();
  const cards = rows.filter((row) => row.kind === "card");
  for (let i = 0; i < cards.length; i += 1) {
    for (let j = i + 1; j < cards.length; j += 1) {
      const left = cards[i];
      const right = cards[j];
      if (left.side !== right.side) continue;
      if (left.player.trim().toLowerCase() !== right.player.trim().toLowerCase()) {
        continue;
      }
      if (Math.abs(left.minute - right.minute) > 1) continue;
      const leftTone = cardTone(left.detail);
      const rightTone = cardTone(right.detail);
      if (leftTone === rightTone) {
        drop.add(left.minute < right.minute ? left : right);
        continue;
      }
      const yellow = leftTone === "yellow" ? left : right;
      const red = leftTone === "red" ? left : right;
      drop.add(yellow);
      red.detail = "Second Yellow";
      red.minute = Math.max(left.minute, right.minute);
    }
  }
  return rows.filter((row) => !drop.has(row));
}

function collectStoryEvents(
  events: MatchEvent[],
  substitutions: Substitution[],
): StoryEvent[] {
  const goals = events
    .filter((event) => event.event_type === "goal")
    .sort((a, b) => a.minute - b.minute);
  let home = 0;
  let away = 0;
  const scoreAtGoal = new Map<MatchEvent, string>();
  for (const goal of goals) {
    if (goal.side === "away") away += 1;
    else home += 1;
    scoreAtGoal.set(goal, formatScore(home, away));
  }
  const rows: StoryEvent[] = [
    ...events.map((event) => ({
      kind: event.event_type === "goal" ? ("goal" as const) : ("card" as const),
      minute: event.minute,
      side: event.side,
      player: event.player_name || event.team || event.side,
      detail: event.event_type === "goal" ? "Goal" : event.detail || "Card",
      scoreAfter: scoreAtGoal.get(event),
    })),
    ...substitutions.map((sub) => ({
      kind: "sub" as const,
      minute: sub.minute,
      side: sub.side,
      player: sub.player_in || "In",
      detail: sub.player_out || "Out",
    })),
  ];
  rows.sort((a, b) => a.minute - b.minute || a.kind.localeCompare(b.kind));
  return collapseStoryEvents(rows);
}

/** Goals and cards, newest first. Substitutions fold away behind a link so
 * the moments that change a match stand out. */
function EventList({
  story,
  homeName,
  awayName,
}: {
  story: StoryEvent[];
  homeName: string;
  awayName: string;
}) {
  const [showSubs, setShowSubs] = useState(false);
  const subs = story.filter((e) => e.kind === "sub").length;
  const rows = story.filter((e) => showSubs || e.kind !== "sub").reverse();
  const team = (side: string) => (side === "away" ? awayName : homeName);
  return (
    <section className="wl-sec">
      <h3>What&apos;s happened</h3>
      {rows.length ? <p className="wl-sub">Newest first.</p> : <p className="wl-sub">No goals or cards yet.</p>}
      {rows.map((e, i) => {
        const key = `${e.kind}-${e.minute}-${e.side}-${i}`;
        if (e.kind === "goal") {
          return (
            <div key={key} className="mp-ev">
              <span className="mp-ev-min">{e.minute}&apos;</span>
              <i className="mp-ball" aria-label="Goal" />
              <span>
                <b>{e.player}</b>
                <small>{team(e.side)}</small>
              </span>
              <b className="mp-ev-score">{(e.scoreAfter ?? "").replace("-", "–")}</b>
            </div>
          );
        }
        if (e.kind === "card") {
          const tone = cardTone(e.detail);
          const what =
            tone === "red" ? (e.detail.toLowerCase().includes("second") ? "second yellow" : "red card") : "yellow card";
          return (
            <div key={key} className="mp-ev">
              <span className="mp-ev-min">{e.minute}&apos;</span>
              <i className={`mp-card is-${tone}`} aria-label={what} />
              <span>
                {e.player}
                <small>
                  {team(e.side)} · {what}
                </small>
              </span>
              <span />
            </div>
          );
        }
        return (
          <div key={key} className="mp-ev is-sub">
            <span className="mp-ev-min">{e.minute}&apos;</span>
            <span aria-label="Substitution">⇄</span>
            <span>
              {e.player} for {e.detail}
              <small>{team(e.side)}</small>
            </span>
            <span />
          </div>
        );
      })}
      {subs ? (
        <button type="button" className="mp-link" onClick={() => setShowSubs((v) => !v)}>
          {showSubs ? "Hide substitutions" : `Show substitutions (${subs})`}
        </button>
      ) : null}
    </section>
  );
}

function overlayBadgeSrc(src?: string | null): string {
  const text = (src || "").trim();
  if (!text) return "";
  return text.replace(/\/badges\/\//g, "/badges/");
}

function OverlayBadge({ name, src }: { name: string; src?: string | null }) {
  const url = overlayBadgeSrc(src);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    setFailed(false);
  }, [url]);
  const initial = (name || "?").charAt(0).toUpperCase();
  const showImg = Boolean(url) && !failed;
  return (
    <span className={`overlay-badge-wrap${showImg ? "" : " is-fallback"}`}>
      {showImg ? (
        <img
          src={url}
          alt=""
          className="overlay-badge"
          referrerPolicy="no-referrer"
          onError={() => setFailed(true)}
        />
      ) : (
        <span className="overlay-badge-fallback" aria-hidden>
          {initial}
        </span>
      )}
    </span>
  );
}

function formatH2HDate(raw: string): string {
  const match = raw.match(/(\d{4})-(\d{2})-(\d{2})/);
  if (!match) return raw.slice(0, 10);
  return `${match[3]}/${match[2]}/${match[1]}`;
}

function foldTeamName(name: string): string {
  return name.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
}

const TEAM_SKIP = new Set(["fc", "cf", "sc", "ac", "afc", "cfc", "club", "de", "del", "la", "el", "the"]);

function teamKey(name: string): string {
  return foldTeamName(name)
    .replace(/[^a-z0-9]+/g, " ")
    .trim()
    .split(/\s+/)
    .filter((token) => token.length > 1 && !TEAM_SKIP.has(token))
    .join(" ");
}

function teamsMatch(a: string, b: string): boolean {
  const ka = teamKey(a);
  const kb = teamKey(b);
  if (!ka || !kb) return false;
  if (ka === kb) return true;
  const ta = ka.split(" ");
  const tb = kb.split(" ");
  const [short, long] = ta.length <= tb.length ? [ta, tb] : [tb, ta];
  if (!short.every((token) => long.includes(token))) return false;
  const extra = long.filter((token) => !short.includes(token));
  if (extra.length === 0) return true;
  const identity = short.reduce((n, token) => n + token.length, 0);
  return identity >= 5 && extra.every((token) => token.length <= 4);
}

function hasTeamId(id?: number | null): id is number {
  return typeof id === "number" && id > 0;
}

function overlayHomeWasHome(
  fx: H2HFixture,
  overlayHome: string,
  overlayAway: string,
  homeId?: number | null,
  awayId?: number | null,
): boolean | null {
  const homeIsUs =
    (hasTeamId(homeId) && fx.home_team_id === homeId) || teamsMatch(fx.home_team, overlayHome);
  const awayIsUs =
    (hasTeamId(homeId) && fx.away_team_id === homeId) || teamsMatch(fx.away_team, overlayHome);
  if (homeIsUs && !awayIsUs) return true;
  if (awayIsUs && !homeIsUs) return false;
  const homeIsThem =
    (hasTeamId(awayId) && fx.home_team_id === awayId) || teamsMatch(fx.home_team, overlayAway);
  const awayIsThem =
    (hasTeamId(awayId) && fx.away_team_id === awayId) || teamsMatch(fx.away_team, overlayAway);
  if (awayIsThem && !homeIsThem) return true;
  if (homeIsThem && !awayIsThem) return false;
  return null;
}

function H2HPane({
  matchId,
  homeTeam,
  awayTeam,
  homeTeamId,
  awayTeamId,
}: {
  matchId: string;
  homeTeam: string;
  awayTeam: string;
  homeTeamId?: number | null;
  awayTeamId?: number | null;
}) {
  const [data, setData] = useState<H2HData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        const res = await fetch(`/api/match/${encodeURIComponent(matchId)}/h2h`, {
          signal: controller.signal,
        });
        if (res.status === 404) {
          setError("Match not synced yet.");
          setData(null);
          return;
        }
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const body = (await res.json()) as { data: H2HData };
        setData(body.data);
      } catch (err) {
        if (controller.signal.aborted) return;
        setError(err instanceof Error ? err.message : "H2H unavailable");
        setData(null);
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    })();
    return () => controller.abort();
  }, [matchId]);

  if (loading) return <p className="mp-note">Loading head-to-head…</p>;
  if (error) return <p className="mp-note">{error}</p>;
  if (!data) return <p className="mp-note">No head-to-head on record.</p>;

  const n = data.summary.sample;
  const home = data.home_team || homeTeam;
  const away = data.away_team || awayTeam;
  const games = data.fixtures.slice(0, 5);
  const p = data.patterns;

  let dominance = "";
  if (p.home_goals && p.away_goals && n >= 5) {
    const ratio = Math.max(p.home_goals, p.away_goals) / Math.min(p.home_goals, p.away_goals);
    if (ratio >= 2) {
      const name = p.home_goals > p.away_goals ? home : away;
      const big = Math.max(p.home_goals, p.away_goals);
      const small = Math.min(p.home_goals, p.away_goals);
      dominance =
        ratio >= 2.5
          ? `${name} average ${(big / n).toFixed(1)} goals a game in these meetings, against ${(small / n).toFixed(1)}.`
          : `${name} scored twice as many goals in these meetings (${big} to ${small}).`;
    }
  }

  const timing = p.timing;
  const timingRows =
    timing && timing.sample
      ? TIMING_SLOTS.filter((slot) => {
          const row = timing[slot.key];
          return typeof row === "object" && row !== null && (row.pct || 0) >= slot.threshold;
        })
      : [];
  const patternRows: { label: string; count: number; of: number }[] = [
    { label: "Over 2.5 goals", count: p.over_2_5.count, of: n },
    { label: "Both teams scored", count: p.btts.count, of: n },
    { label: "Draws", count: data.summary.draws, of: n },
    { label: `${home} kept a clean sheet`, count: p.home_cs.count, of: n },
    { label: `${away} kept a clean sheet`, count: p.away_cs.count, of: n },
    ...timingRows.map((slot) => ({
      label: slot.label,
      count: (timing?.[slot.key] as H2HCount).count,
      of: timing?.sample ?? n,
    })),
  ];

  return (
    <div className="wl-mbody">
      <div className="wl-col">
        <section className="wl-sec">
          <h3>Head-to-head</h3>
          {n === 0 ? (
            <p className="wl-sub">First meeting, or no history on record yet.</p>
          ) : (
            <>
              <p className="wl-sub">
                Last {n === 1 ? "meeting" : `${n} meetings`}
                {p.avg_goals != null ? `, ${p.avg_goals} goals a game` : ""}.
              </p>
              <div className="wl-split" aria-hidden>
                <i className="h" style={{ flex: data.summary.home_wins || 0.001 }} />
                <i className="d" style={{ flex: data.summary.draws || 0.001 }} />
                <i className="a" style={{ flex: data.summary.away_wins || 0.001 }} />
              </div>
              <div className="wl-split-keys">
                <span>
                  <b>{data.summary.home_wins}</b> {home}
                  {leagueRankLabel(data.home_rank) ? ` (${leagueRankLabel(data.home_rank)})` : ""}
                </span>
                <span>
                  <b>{data.summary.draws}</b> {data.summary.draws === 1 ? "draw" : "draws"}
                </span>
                <span>
                  <b>{data.summary.away_wins}</b> {away}
                  {leagueRankLabel(data.away_rank) ? ` (${leagueRankLabel(data.away_rank)})` : ""}
                </span>
              </div>
              {games.map((fx) => {
                const usHome = overlayHomeWasHome(fx, home, away, homeTeamId, awayTeamId);
                return (
                  <div key={`${fx.match_id}-${fx.match_date}`} className="wl-meet">
                    <span className="d">{formatH2HDate(fx.match_date)}</span>
                    <span className={`h${usHome === true ? " mp-us" : ""}`}>{fx.home_team}</span>
                    <span className="s">
                      {fx.home_score}–{fx.away_score}
                    </span>
                    <span className={usHome === false ? "mp-us" : ""}>{fx.away_team}</span>
                  </div>
                );
              })}
            </>
          )}
        </section>
      </div>
      <div className="wl-col">
        {n > 0 ? (
          <section className="wl-sec">
            <h3>Patterns in their meetings</h3>
            <p className="wl-sub">
              {data.insufficient
                ? `Only ${n === 1 ? "one meeting" : `${n} meetings`}, too few to read much into.`
                : `How often each happened in the last ${n} meetings.`}
            </p>
            <table className="wl-ptable">
              <tbody>
                {patternRows.map((row) => (
                  <tr key={row.label}>
                    <th scope="row">{row.label}</th>
                    <td className="wl-num">
                      {row.count}/{row.of}
                      <span className="wl-mini" aria-hidden>
                        <i style={{ width: `${row.of ? Math.round((row.count / row.of) * 100) : 0}%` }} />
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {dominance ? <p className="wl-callout">{dominance}</p> : null}
          </section>
        ) : null}
        <section className="wl-sec">
          <p className="wl-sub">
            This match isn&apos;t on the watchlist (there were no prices before kick-off), so only past meetings are
            shown.
          </p>
        </section>
      </div>
    </div>
  );
}

function LineupColumn({ name, lineup }: { name: string; lineup: TeamLineup }) {
  const players = (list: LineupPlayer[], bench = false) => (
    <ol className={`mp-xi${bench ? " is-bench" : ""}`}>
      {list.map((player) => (
        <li key={`${bench ? "b" : "s"}-${player.number}-${player.player}`}>
          <span>{player.number || "–"}</span>
          {player.player}
        </li>
      ))}
    </ol>
  );
  return (
    <div className="mp-lineup">
      <b>{name}</b>
      {lineup.coach ? <small>Coach: {lineup.coach}</small> : null}
      {lineup.starting.length ? players(lineup.starting) : <p className="wl-sub">Not announced.</p>}
      {lineup.substitutes.length ? (
        <>
          <p className="mp-bench-h">Bench</p>
          {players(lineup.substitutes, true)}
        </>
      ) : null}
    </div>
  );
}

const ENDED = new Set(["FT", "AET", "PEN"]);

/** The panel's score as the watchlist's live shape, so the research can mark
 * each point while the match is played. */
function liveForResearch(panel: MatchPanel): Live | undefined {
  const m = /^(\d+)\s*[-–]\s*(\d+)/.exec(panel.score || "");
  if (!m) return undefined;
  const status = (panel.status_short || "").toUpperCase();
  if (status === "NS" || !status) return undefined;
  return {
    home: Number(m[1]),
    away: Number(m[2]),
    minute: panel.minute,
    display: panel.minute_display || "",
    status,
    finished: ENDED.has(status),
  };
}

function ordinalRank(position?: number | null): string {
  return position ? leagueRankLabel(position) : "";
}

export function MatchOverlay({
  match,
  onClose,
}: {
  match: OverlayMatch;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<TabId>("signals");
  const [panel, setPanel] = useState<MatchPanel>(() => panelFromLive(match));
  const [loadError, setLoadError] = useState<string | null>(null);
  const [research, setResearch] = useState<MatchResearch | null>(null);
  const [researchDone, setResearchDone] = useState(false);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [onClose]);

  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const res = await fetch(`/api/match/${match.match_id}/panel`, {
          signal: controller.signal,
        });
        if (res.status === 404) {
          setPanel(panelFromLive(match));
          setLoadError(null);
          return;
        }
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const body = (await res.json()) as MatchPanel;
        setPanel(body);
        setLoadError(null);
      } catch (err) {
        if (controller.signal.aborted) return;
        setPanel(panelFromLive(match));
        setLoadError(err instanceof Error ? err.message : "panel unavailable");
      }
    })();
    return () => controller.abort();
  }, [match, match.match_id, match.minute, match.score]);

  useEffect(() => {
    // The watchlist's research for this match: every priced match of the day
    // has one. It feeds the header (positions, prices) and Before kick-off.
    const controller = new AbortController();
    setResearch(null);
    setResearchDone(false);
    fetch(`/api/watchlist/match/${encodeURIComponent(match.match_id)}`, { signal: controller.signal })
      .then((res) => (res.ok ? (res.json() as Promise<MatchResearch>) : null))
      .then((body) => {
        setResearch(body);
        setResearchDone(true);
      })
      .catch(() => {
        if (!controller.signal.aborted) setResearchDone(true);
      });
    return () => controller.abort();
  }, [match.match_id]);

  const story = useMemo(
    () => collectStoryEvents(panel.events, panel.substitutions),
    [panel.events, panel.substitutions],
  );

  const status = (panel.status_short || match.status_short || "").toUpperCase();
  const clock = ENDED.has(status)
    ? "Full time"
    : status === "HT"
      ? "Half-time"
      : `Live · ${overlayClock(
          panel.minute,
          panel.status_short || match.status_short,
          panel.minute_display || match.minute_display,
          [
            ...(panel.events || []).map((event) => event.minute),
            ...(match.goal_events || []).map((event) => event.minute),
            ...(match.card_events || []).map((event) => event.minute),
          ],
        )}`;
  const league = research
    ? [research.league.country, research.league.name, research.league.round ? `Round ${research.league.round}` : ""]
        .filter(Boolean)
        .join(" · ")
    : panel.league || match.league || "";
  const odds = research?.odds;
  const price = (value?: number | null) => (value ? value.toFixed(2) : "–");
  const standing = (side: "home" | "away") => {
    const team = research?.[side];
    if (!team?.position) return null;
    return (
      <span>
        {ordinalRank(team.position)}
        {team.points != null ? ` · ${team.points} pts` : ""}
      </span>
    );
  };
  const hasLineups = Boolean(panel.lineup.home.starting.length || panel.lineup.away.starting.length);

  return (
    <div className="overlay-backdrop" onClick={onClose} role="presentation">
      <div
        className="overlay mp wl-vars"
        role="dialog"
        aria-modal="true"
        aria-labelledby="overlay-title"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="mp-head">
          <div className="mp-crumb">
            <span>{league}</span>
            <button type="button" className="mp-close" onClick={onClose}>
              Close
            </button>
          </div>
          <div className="wl-vs">
            <div className="wl-side">
              <OverlayBadge name={panel.home_team} src={panel.home_team_logo} />
              <div>
                <b>{panel.home_team}</b>
                {standing("home")}
              </div>
            </div>
            <div className="wl-ko">
              <b id="overlay-title">{(panel.score || "").replace("-", "–")}</b>
              <span>
                {ENDED.has(status) || status === "HT" ? null : <i className="wl-live-dot" aria-hidden />}
                {clock}
              </span>
            </div>
            <div className="wl-side is-away">
              <div>
                <b>{panel.away_team}</b>
                {standing("away")}
              </div>
              <OverlayBadge name={panel.away_team} src={panel.away_team_logo} />
            </div>
          </div>
          {odds ? (
            <div className="mp-prices">
              <em>Before kick-off</em>
              <span>
                {panel.home_team} <b>{price(odds.home)}</b>
              </span>
              <span>
                Draw <b>{price(odds.draw)}</b>
              </span>
              <span>
                {panel.away_team} <b>{price(odds.away)}</b>
              </span>
              {odds.over_2_5 ? (
                <span className="is-extra">
                  Over 2.5 <b>{price(odds.over_2_5)}</b>
                </span>
              ) : null}
              {odds.btts_yes ? (
                <span className="is-extra">
                  Both score <b>{price(odds.btts_yes)}</b>
                </span>
              ) : null}
            </div>
          ) : null}
        </header>
        <PickBox matchId={match.match_id} score={panel.score || match.score} minute={panel.minute ?? match.minute} />
        <nav className="mp-tabs" aria-label="Match sections">
          {TABS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={tab === item.id ? "on" : ""}
              aria-current={tab === item.id ? "page" : undefined}
              onClick={() => setTab(item.id)}
            >
              {item.label}
            </button>
          ))}
        </nav>
        {loadError ? <p className="mp-note">Showing the live row until the match feed catches up.</p> : null}
        <div className="mp-body">
          {tab === "signals" ? (
            <section className="wl-sec">
              <div>
                <h3>Kalchas signals</h3>
                <p className="wl-sub">
                  Who is pushing right now and whether a goal looks due. A value turns teal once that team passes its
                  alert line. Hover or tap a name for how it&apos;s worked out.
                </p>
                <div className="wl-table-wrap">
                  <table className="wl-ptable mp-sig">
                    <thead>
                      <tr>
                        <th />
                        <th className="wl-num">{panel.home_team}</th>
                        <th className="wl-num">{panel.away_team}</th>
                        <th className="mp-sig-norm">What&apos;s normal</th>
                      </tr>
                    </thead>
                    <tbody>
                      {STRAT_ROWS.map((row) => {
                        const block = panel.strategy_status[row.key];
                        const window =
                          row.key === "delta_5min"
                            ? panel.last_5min
                            : row.key === "pressure_index"
                              ? panel.last_10min
                              : null;
                        const span = row.key === "delta_5min" ? 5 : row.key === "pressure_index" ? 10 : 0;
                        return (
                          <SignalRow
                            key={row.key}
                            label={row.label}
                            normal={row.normal}
                            home={Number(block?.teams?.home?.value || 0)}
                            away={Number(block?.teams?.away?.value || 0)}
                            digits={row.digits}
                            homeTriggered={row.key !== "npei" && Boolean(block?.teams?.home?.triggered)}
                            awayTriggered={row.key !== "npei" && Boolean(block?.teams?.away?.triggered)}
                            inkHome={row.key === "npei" ? phiInk(block?.teams?.home?.value) : undefined}
                            inkAway={row.key === "npei" ? phiInk(block?.teams?.away?.value) : undefined}
                            tip={row.tip}
                            suffix={row.suffix}
                            signed={row.signed}
                            homeName={panel.home_team}
                            awayName={panel.away_team}
                            tone={row.tone}
                            scale={row.scale}
                            homeNote={window ? windowRecipe(window, "home") : (block?.teams?.home?.note ?? undefined)}
                            awayNote={window ? windowRecipe(window, "away") : (block?.teams?.away?.note ?? undefined)}
                            windowHeading={window && span ? windowLabel(window, span) : undefined}
                            homeText={row.key === "delta_goal" ? formBarText(block?.teams?.home) : undefined}
                            awayText={row.key === "delta_goal" ? formBarText(block?.teams?.away) : undefined}
                          />
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>
          ) : null}
          {tab === "stats" ? (
            <section className="wl-sec">
              <div>
                <h3>Match stats</h3>
                <div className="mp-keys">
                  <span>
                    <i className="is-home" />
                    {panel.home_team}
                  </span>
                  <span>
                    {panel.away_team}
                    <i className="is-away" />
                  </span>
                </div>
                {STAT_BARS.map((row) => (
                  <StatRow
                    key={row.key}
                    label={row.label}
                    home={Number(panel.stat_lines[row.key]?.home || 0)}
                    away={Number(panel.stat_lines[row.key]?.away || 0)}
                  />
                ))}
              </div>
            </section>
          ) : null}
          {tab === "timeline" ? (
            <>
              <TimelineGraph
                points={panel.timeline}
                story={story}
                homeName={panel.home_team}
                awayName={panel.away_team}
                minute={panel.minute}
              />
              <EventList story={story} homeName={panel.home_team} awayName={panel.away_team} />
            </>
          ) : null}
          {tab === "before" ? (
            research ? (
              <ResearchBody
                data={research}
                live={liveForResearch(panel)}
                footer={
                  <>
                    <p className="wl-sub">Written before kick-off from results only.</p>
                    <a
                      className="mp-more"
                      href={`/${research.day}/${research.match_id}`}
                      onClick={() => logVisitEvent("wl_panel")}
                    >
                      Open the full match page →
                    </a>
                  </>
                }
              />
            ) : researchDone ? (
              <H2HPane
                matchId={panel.match_id}
                homeTeam={panel.home_team}
                awayTeam={panel.away_team}
                homeTeamId={panel.home_team_id}
                awayTeamId={panel.away_team_id}
              />
            ) : (
              <p className="mp-note">Loading…</p>
            )
          ) : null}
          {tab === "lineups" ? (
            <section className="wl-sec">
              <div>
                <h3>Line-ups</h3>
                {hasLineups ? (
                  <>
                    <p className="wl-sub">Starting eleven and bench, as announced.</p>
                    <div className="mp-lineups">
                      <LineupColumn name={panel.home_team} lineup={panel.lineup.home} />
                      <LineupColumn name={panel.away_team} lineup={panel.lineup.away} />
                    </div>
                  </>
                ) : (
                  <p className="wl-sub">Not announced for this match. Most lower leagues never publish them.</p>
                )}
              </div>
            </section>
          ) : null}
        </div>
      </div>
    </div>
  );
}
