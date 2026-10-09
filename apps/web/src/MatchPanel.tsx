import { useEffect, useMemo, useState } from "react";
import {
  HoverLedger,
  HoverTip,
  hoverBarPct,
  hoverLead,
  type HoverScale,
} from "./HoverTip";

type SideValue = { home: number; away: number };
type TeamCell = { value: number; triggered?: boolean };
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
  omega: SideValue;
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
type H2HData = {
  home_team: string;
  away_team: string;
  insufficient: boolean;
  reason?: string | null;
  summary: { home_wins: number; draws: number; away_wins: number; sample: number };
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

type TabId = "stats" | "timeline" | "omega" | "h2h" | "lineups";

const TABS: { id: TabId; label: string }[] = [
  { id: "stats", label: "Stats" },
  { id: "timeline", label: "Timeline" },
  { id: "omega", label: "Omega" },
  { id: "h2h", label: "H2H" },
  { id: "lineups", label: "Lineups" },
];

const STAT_BARS: { key: string; label: string }[] = [
  { key: "shots_on_target", label: "On target" },
  { key: "shots_off_target", label: "Off target" },
  { key: "attacks", label: "Attacks" },
  { key: "dangerous_attacks", label: "Dangerous attacks" },
  { key: "corners", label: "Corners" },
  { key: "possession", label: "Possession" },
  { key: "yellow_cards", label: "Yellow cards" },
  { key: "red_cards", label: "Red cards" },
];

const STRAT_ROWS: {
  key: string;
  label: string;
  digits: number;
  tip: string;
  suffix?: string;
  signed?: boolean;
  tone: string;
  scale: HoverScale;
}[] = [
  {
    key: "rule_of_three",
    label: "Unrealised goals",
    digits: 1,
    tone: "urg",
    scale: { min: -1, max: 3 },
    tip: "Shots say they should have scored more. Around 1 is worth a look. Negative means the score is already ahead of the chances.",
  },
  {
    key: "delta_5min",
    label: "5-minute pressure",
    digits: 1,
    tone: "d5",
    scale: { min: 0, max: 12 },
    tip: "Pressure in the last 5 minutes. 4 is common. 8+ is a real wave.",
  },
  {
    key: "pressure_index",
    label: "Sustained pressure",
    digits: 0,
    tone: "d10",
    scale: { min: 0, max: 100 },
    tip: "Pressure over about 10 minutes, out of 100. 70 is a surge. 90+ is a siege.",
  },
  {
    key: "delta_goal",
    label: "League Bar",
    digits: 1,
    signed: true,
    tone: "lbar",
    scale: { min: -10, max: 10 },
    tip: "Are they more likely to score than a typical side in this league, right now. 0 is average. +6 is clearly above.",
  },
  {
    key: "npei",
    label: "Efficiency",
    digits: 0,
    tone: "phi",
    scale: { min: 0, max: 100 },
    tip: "How well attacks become shots, out of 100. A higher number means more shots from the same attacks.",
  },
  {
    key: "omega",
    label: "Omega",
    digits: 0,
    suffix: "°",
    tone: "omega",
    scale: { min: -15, max: 40 },
    tip: "How steeply pressure is building, in degrees. 20° is building. 30° fires. 35°+ is rare. Negative means it is flattening.",
  },
  {
    key: "kscore",
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

function catmullRomPath(points: { x: number; y: number }[], tension = 0.45): string {
  if (!points.length) return "";
  if (points.length === 1) {
    return `M ${points[0].x.toFixed(1)} ${points[0].y.toFixed(1)}`;
  }
  if (points.length === 2) {
    return `M ${points[0].x.toFixed(1)} ${points[0].y.toFixed(1)} L ${points[1].x.toFixed(1)} ${points[1].y.toFixed(1)}`;
  }
  const parts = [`M ${points[0].x.toFixed(1)} ${points[0].y.toFixed(1)}`];
  for (let i = 0; i < points.length - 1; i += 1) {
    const p0 = points[i - 1] || points[i];
    const p1 = points[i];
    const p2 = points[i + 1];
    const p3 = points[i + 2] || p2;
    const c1x = p1.x + ((p2.x - p0.x) / 6) * tension;
    const c1y = p1.y + ((p2.y - p0.y) / 6) * tension;
    const c2x = p2.x - ((p3.x - p1.x) / 6) * tension;
    const c2y = p2.y - ((p3.y - p1.y) / 6) * tension;
    parts.push(
      `C ${c1x.toFixed(1)} ${c1y.toFixed(1)} ${c2x.toFixed(1)} ${c2y.toFixed(1)} ${p2.x.toFixed(1)} ${p2.y.toFixed(1)}`,
    );
  }
  return parts.join(" ");
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

function dualBarFillPcts(home: number, away: number): { homePct: number; awayPct: number } {
  const homeFill = Math.max(0, home);
  const awayFill = Math.max(0, away);
  const peak = Math.max(homeFill, awayFill, 1);
  return {
    homePct: (homeFill / peak) * 100,
    awayPct: (awayFill / peak) * 100,
  };
}

function DualBar({
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
}) {
  const { homePct, awayPct } = dualBarFillPcts(home, away);
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
            homeValue={fmtSignal(home, digits, extras)}
            awayValue={fmtSignal(away, digits, extras)}
            homeLead={lead.home}
            awayLead={lead.away}
            homePct={hoverBarPct(home, scale)}
            awayPct={hoverBarPct(away, scale)}
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
  return (
    <div className="stat-bar">
      <div className="stat-bar-label">{labelNode}</div>
      <div className="stat-bar-row">
        <span className={`stat-bar-val home${homeTriggered ? " trig" : ""}`}>
          {fmtSignal(home, digits, extras)}
        </span>
        <div className="stat-bar-track" aria-hidden>
          <div className="stat-bar-half home">
            <div className="stat-bar-fill home" style={{ width: `${homePct}%` }} />
          </div>
          <div className="stat-bar-half away">
            <div className="stat-bar-fill away" style={{ width: `${awayPct}%` }} />
          </div>
        </div>
        <span className={`stat-bar-val away${awayTriggered ? " trig" : ""}`}>
          {fmtSignal(away, digits, extras)}
        </span>
      </div>
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

function DangerPulseChart({
  points,
  events,
  title,
  blurb,
  homeName,
  awayName,
  currentMinute,
}: {
  points: TimelinePoint[];
  events: MatchEvent[];
  title: string;
  blurb: string;
  homeName: string;
  awayName: string;
  currentMinute: number;
}) {
  const pulses = cumulativeToPerMinute(
    points,
    (p) => Number(p.dangerous_attacks.home || 0),
    (p) => Number(p.dangerous_attacks.away || 0),
  );
  if (pulses.length < 2) {
    return (
      <article className="chart-card">
        <header className="chart-head">
          <h3>{title}</h3>
          <p>{blurb}</p>
        </header>
        <p className="muted">A line appears after a few minutes have been recorded.</p>
      </article>
    );
  }
  const width = 720;
  const height = 248;
  const padL = 44;
  const padR = 18;
  const padT = 18;
  const padB = 32;
  const maxX = Math.max(90, pulses[pulses.length - 1].minute, currentMinute);
  const peak = Math.max(1, ...pulses.flatMap((point) => [point.home, point.away]));
  const plotW = width - padL - padR;
  const plotH = height - padT - padB;
  const midY = padT + plotH / 2;
  const xAt = (minute: number) => padL + (Math.max(0, minute) / maxX) * plotW;
  const yAt = (signed: number) => midY - (signed / peak) * (plotH / 2);
  const barW = Math.max(1.2, Math.min(4, plotW / Math.max(pulses.length, 1) / 2));
  const toLine = (signedOf: (point: PulsePoint) => number) =>
    catmullRomPath(
      pulses.map((point) => ({ x: xAt(point.minute), y: yAt(signedOf(point)) })),
    );
  const toArea = (signedOf: (point: PulsePoint) => number) => {
    const line = toLine(signedOf);
    const first = pulses[0];
    const last = pulses[pulses.length - 1];
    return `${line} L ${xAt(last.minute).toFixed(1)} ${midY.toFixed(1)} L ${xAt(first.minute).toFixed(1)} ${midY.toFixed(1)} Z`;
  };
  const last = pulses[pulses.length - 1];
  const goals = events.filter((event) => event.event_type === "goal");
  const yTickDigits = peak < 8 ? 1 : 0;
  return (
    <article className="chart-card">
      <header className="chart-head">
        <h3>{title}</h3>
        <p>{blurb}</p>
      </header>
      <ul className="chart-legend">
        <li className="lg-home">
          {homeName}
          <span>{fmt(last.home, yTickDigits)}/min</span>
        </li>
        <li className="lg-away">
          {awayName}
          <span>{fmt(last.away, yTickDigits)}/min</span>
        </li>
        <li className="lg-goal">Goal</li>
      </ul>
      <svg className="series-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={title}>
        {[-peak, -peak / 2, 0, peak / 2, peak].map((tick) => (
          <g key={`y-${tick}`}>
            <line
              x1={padL}
              x2={width - padR}
              y1={yAt(tick)}
              y2={yAt(tick)}
              className={tick === 0 ? "chart-zero" : "chart-grid"}
            />
            <text x={padL - 8} y={yAt(tick) + 3} className="chart-axis" textAnchor="end">
              {fmt(Math.abs(tick), yTickDigits)}
            </text>
          </g>
        ))}
        {xTicks(maxX).map((tick) => (
          <g key={`x-${tick}`}>
            <line
              x1={xAt(tick)}
              x2={xAt(tick)}
              y1={padT}
              y2={height - padB}
              className="chart-grid chart-grid-x"
            />
            <text x={xAt(tick)} y={height - 10} className="chart-axis" textAnchor="middle">
              {tick}&apos;
            </text>
          </g>
        ))}
        {pulses.map((point) => (
          <g key={`bar-${point.minute}`}>
            <rect
              className="pulse-bar home"
              x={xAt(point.minute) - barW / 2}
              y={yAt(point.home)}
              width={barW}
              height={Math.max(0, midY - yAt(point.home))}
            />
            <rect
              className="pulse-bar away"
              x={xAt(point.minute) - barW / 2}
              y={midY}
              width={barW}
              height={Math.max(0, yAt(-point.away) - midY)}
            />
          </g>
        ))}
        <path d={toArea((p) => p.home)} className="series-home-fill" />
        <path d={toArea((p) => -p.away)} className="series-away-fill" />
        <path d={toLine((p) => p.home)} className="series-home" />
        <path d={toLine((p) => -p.away)} className="series-away" />
        <line
          x1={xAt(currentMinute)}
          x2={xAt(currentMinute)}
          y1={padT}
          y2={height - padB}
          className="chart-now"
        />
        {goals.map((goal, index) => {
          const pulse =
            pulses.find((point) => point.minute === goal.minute) ||
            pulses.reduce((best, point) =>
              Math.abs(point.minute - goal.minute) < Math.abs(best.minute - goal.minute)
                ? point
                : best,
            );
          const signed = goal.side === "away" ? -pulse.away : pulse.home;
          return (
            <circle
              key={`${goal.minute}-${goal.side}-${index}`}
              cx={xAt(goal.minute)}
              cy={yAt(signed)}
              r={4.5}
              className={goal.side === "away" ? "goal-away" : "goal-home"}
            >
              <title>
                {goal.minute}&apos; {goal.side === "away" ? awayName : homeName} goal
              </title>
            </circle>
          );
        })}
      </svg>
    </article>
  );
}

function plotPoints(points: TimelinePoint[]): TimelinePoint[] {
  const usable = points.filter((point) => point.minute > 0);
  return usable.length >= 2 ? usable : points;
}

function valueAt(
  points: TimelinePoint[],
  minute: number,
  read: (point: TimelinePoint) => number,
): number {
  if (!points.length) return 0;
  if (minute <= points[0].minute) return read(points[0]);
  for (let i = 1; i < points.length; i += 1) {
    const prev = points[i - 1];
    const next = points[i];
    if (minute <= next.minute) {
      const span = Math.max(1, next.minute - prev.minute);
      const t = (minute - prev.minute) / span;
      return read(prev) + t * (read(next) - read(prev));
    }
  }
  return read(points[points.length - 1]);
}

function xTicks(maxX: number): number[] {
  const step = maxX > 60 ? 15 : 10;
  const ticks: number[] = [];
  for (let minute = 0; minute < maxX; minute += step) ticks.push(minute);
  ticks.push(maxX);
  return ticks;
}

function yTicks(minY: number, maxY: number): number[] {
  const span = maxY - minY || 1;
  return [0, 1, 2, 3, 4].map((step) => minY + (span * step) / 4);
}

function SeriesChart({
  points,
  homeOf,
  awayOf,
  events,
  title,
  blurb,
  homeName,
  awayName,
  unit = "",
  signed = false,
  guide,
  guideLabel,
}: {
  points: TimelinePoint[];
  homeOf: (p: TimelinePoint) => number;
  awayOf: (p: TimelinePoint) => number;
  events: MatchEvent[];
  title: string;
  blurb: string;
  homeName: string;
  awayName: string;
  unit?: string;
  signed?: boolean;
  guide?: number;
  guideLabel?: string;
}) {
  const series = plotPoints(points);
  if (series.length < 2) {
    return (
      <article className="chart-card">
        <header className="chart-head">
          <h3>{title}</h3>
          <p>{blurb}</p>
        </header>
        <p className="muted">A line appears after a few minutes have been recorded.</p>
      </article>
    );
  }
  const width = 720;
  const height = 248;
  const padL = 44;
  const padR = 18;
  const padT = 18;
  const padB = 32;
  const maxX = Math.max(90, series[series.length - 1].minute);
  const ys = series.flatMap((point) => [homeOf(point), awayOf(point)]);
  let minY = signed ? Math.min(0, ...ys) : 0;
  let maxY = Math.max(signed ? 1 : 1, ...ys);
  if (guide != null) {
    maxY = Math.max(maxY, guide);
    minY = Math.min(minY, 0);
  }
  if (maxY === minY) maxY = minY + 1;
  const plotW = width - padL - padR;
  const plotH = height - padT - padB;
  const xAt = (minute: number) => padL + (Math.max(0, minute) / maxX) * plotW;
  const yAt = (value: number) => padT + (1 - (value - minY) / (maxY - minY)) * plotH;
  const toLine = (read: (point: TimelinePoint) => number) =>
    catmullRomPath(
      series.map((point) => ({ x: xAt(point.minute), y: yAt(read(point)) })),
    );
  const toArea = (read: (point: TimelinePoint) => number) => {
    const line = toLine(read);
    const base = yAt(Math.max(minY, 0));
    const first = series[0];
    const last = series[series.length - 1];
    return `${line} L ${xAt(last.minute).toFixed(1)} ${base.toFixed(1)} L ${xAt(first.minute).toFixed(1)} ${base.toFixed(1)} Z`;
  };
  const homePath = toLine(homeOf);
  const awayPath = toLine(awayOf);
  const goals = events.filter((event) => event.event_type === "goal");
  const last = series[series.length - 1];
  const yTickDigits = signed || maxY - minY < 8 ? 1 : 0;
  return (
    <article className="chart-card">
      <header className="chart-head">
        <h3>{title}</h3>
        <p>{blurb}</p>
      </header>
      <ul className="chart-legend">
        <li className="lg-home">
          {homeName}
          <span>
            {fmt(homeOf(last), yTickDigits)}
            {unit}
          </span>
        </li>
        <li className="lg-away">
          {awayName}
          <span>
            {fmt(awayOf(last), yTickDigits)}
            {unit}
          </span>
        </li>
        <li className="lg-goal">Goal</li>
        {guide != null && guideLabel ? <li className="lg-guide">{guideLabel}</li> : null}
      </ul>
      <svg
        className="series-chart"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={title}
      >
        {yTicks(minY, maxY).map((tick) => (
          <g key={`y-${tick}`}>
            <line
              x1={padL}
              x2={width - padR}
              y1={yAt(tick)}
              y2={yAt(tick)}
              className="chart-grid"
            />
            <text x={padL - 8} y={yAt(tick) + 3} className="chart-axis" textAnchor="end">
              {fmt(tick, yTickDigits)}
              {unit}
            </text>
          </g>
        ))}
        {xTicks(maxX).map((tick) => (
          <g key={`x-${tick}`}>
            <line
              x1={xAt(tick)}
              x2={xAt(tick)}
              y1={padT}
              y2={height - padB}
              className="chart-grid chart-grid-x"
            />
            <text x={xAt(tick)} y={height - 10} className="chart-axis" textAnchor="middle">
              {tick}&apos;
            </text>
          </g>
        ))}
        {signed ? (
          <line
            x1={padL}
            x2={width - padR}
            y1={yAt(0)}
            y2={yAt(0)}
            className="chart-zero"
          />
        ) : null}
        {guide != null ? (
          <line
            x1={padL}
            x2={width - padR}
            y1={yAt(guide)}
            y2={yAt(guide)}
            className="chart-guide"
          />
        ) : null}
        <path d={toArea(homeOf)} className="series-home-fill" />
        <path d={toArea(awayOf)} className="series-away-fill" />
        <path d={homePath} className="series-home" />
        <path d={awayPath} className="series-away" />
        {goals.map((goal, index) => {
          const read = goal.side === "away" ? awayOf : homeOf;
          return (
            <circle
              key={`${goal.minute}-${goal.side}-${index}`}
              cx={xAt(goal.minute)}
              cy={yAt(valueAt(series, goal.minute, read))}
              r={4.5}
              className={goal.side === "away" ? "goal-away" : "goal-home"}
            >
              <title>
                {goal.minute}&apos; {goal.side === "away" ? awayName : homeName} goal
              </title>
            </circle>
          );
        })}
      </svg>
    </article>
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

type StoryRow =
  | { type: "period"; key: string; label: string; score: string }
  | { type: "added"; key: string; minutes: number }
  | { type: "event"; key: string; event: StoryEvent };

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

function htScoreFrom(
  events: MatchEvent[],
  liveScore: string,
  status?: string | null,
): string {
  if ((status || "").toUpperCase() === "HT") return liveScore;
  let home = 0;
  let away = 0;
  for (const event of events) {
    if (event.event_type !== "goal" || event.minute > 45) continue;
    if (event.side === "away") away += 1;
    else home += 1;
  }
  return formatScore(home, away);
}

function buildStoryRows(
  events: MatchEvent[],
  substitutions: Substitution[],
  liveScore: string,
  status?: string | null,
  minute = 0,
): StoryRow[] {
  const items = collectStoryEvents(events, substitutions);
  if (!items.length) return [];
  const first = items.filter((item) => item.minute <= 45);
  const second = items.filter((item) => item.minute > 45);
  const statusU = (status || "").toUpperCase();
  const showSecond =
    second.length > 0 || ["2H", "FT", "AET", "PEN"].includes(statusU) || minute > 45;
  const showHt = showSecond || statusU === "HT";
  const ht = htScoreFrom(events, liveScore, status);
  const out: StoryRow[] = [];
  if (showSecond) {
    out.push({ type: "period", key: "p-2h", label: "2nd half", score: liveScore });
    if (minute > 90) {
      out.push({ type: "added", key: "add-90", minutes: minute - 90 });
    }
    for (const [index, event] of [...second].reverse().entries()) {
      out.push({
        type: "event",
        key: `2h-${event.kind}-${event.minute}-${event.side}-${index}`,
        event,
      });
    }
  }
  if (showHt) {
    out.push({ type: "period", key: "p-ht", label: "HT", score: ht });
  }
  if (statusU === "1H" && minute > 45) {
    out.push({ type: "added", key: "add-45", minutes: minute - 45 });
  }
  for (const [index, event] of [...first].reverse().entries()) {
    out.push({
      type: "event",
      key: `1h-${event.kind}-${event.minute}-${event.side}-${index}`,
      event,
    });
  }
  return out;
}

function StoryEventBody({ event }: { event: StoryEvent }) {
  if (event.kind === "goal") {
    return (
      <span className="story-payload">
        <span className="story-score-pill">{event.scoreAfter || ""}</span>
        <span className="story-player">{event.player}</span>
      </span>
    );
  }
  if (event.kind === "card") {
    const tone = cardTone(event.detail);
    return (
      <span className="story-payload">
        <span className={`story-card-sq ${tone}`} aria-hidden />
        <span className="story-player">{event.player}</span>
        <span className="story-reason">
          {tone === "red"
            ? event.detail.toLowerCase().includes("second")
              ? "2nd yellow"
              : "Red"
            : "Yellow"}
        </span>
      </span>
    );
  }
  return (
    <span className="story-payload">
      <span className="story-sub">
        <span className="story-sub-in">{event.player}</span>
        <span className="story-sub-out">{event.detail}</span>
      </span>
    </span>
  );
}

function MatchStory({
  events,
  substitutions,
  liveScore,
  status,
  minute,
}: {
  events: MatchEvent[];
  substitutions: Substitution[];
  liveScore: string;
  status?: string | null;
  minute: number;
}) {
  const rows = buildStoryRows(events, substitutions, liveScore, status, minute);
  return (
    <section className="story-block">
      <h3>Match story</h3>
      {rows.length ? (
        <ol className="story-timeline">
          {rows.map((row) => {
            if (row.type === "period") {
              return (
                <li key={row.key} className="story-period">
                  <span>{row.label}</span>
                  <span className="story-period-score">{row.score}</span>
                </li>
              );
            }
            if (row.type === "added") {
              return (
                <li key={row.key} className="story-added">
                  Additional time {row.minutes}
                </li>
              );
            }
            const { event } = row;
            const home = event.side !== "away";
            return (
              <li
                key={row.key}
                className={`story-event ${home ? "is-home" : "is-away"} is-${event.kind}`}
              >
                <div className="story-col home">
                  {home ? (
                    <>
                      <span className="story-min">{event.minute}&apos;</span>
                      <StoryEventBody event={event} />
                    </>
                  ) : null}
                </div>
                <div className="story-spine" aria-hidden>
                  <span className="story-dot" />
                </div>
                <div className="story-col away">
                  {!home ? (
                    <>
                      <StoryEventBody event={event} />
                      <span className="story-min">{event.minute}&apos;</span>
                    </>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ol>
      ) : (
        <p className="muted">No goals, cards, or substitutions yet.</p>
      )}
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

function LineupColumn({
  name,
  src,
  lineup,
}: {
  name: string;
  src?: string | null;
  lineup: TeamLineup;
}) {
  return (
    <div className="lineup-col">
      <div className="lineup-head">
        <OverlayBadge name={name} src={src} />
        <div>
          <h3>{name}</h3>
          {lineup.coach ? <p className="muted">{lineup.coach}</p> : null}
        </div>
      </div>
      {lineup.starting.length ? (
        <ol className="lineup-xi">
          {lineup.starting.map((player) => (
            <li key={`${player.number}-${player.player}`}>
              <span className="shirt">{player.number || "—"}</span>
              {player.player}
            </li>
          ))}
        </ol>
      ) : (
        <p className="muted">Starting XI is not in the live feed yet.</p>
      )}
      {lineup.substitutes.length ? (
        <>
          <h4>Bench</h4>
          <ul className="lineup-bench">
            {lineup.substitutes.map((player) => (
              <li key={`b-${player.number}-${player.player}`}>
                <span className="shirt">{player.number || "—"}</span>
                {player.player}
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </div>
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

function patternTone(pct: number | null): "green" | "gold" | "red" | "avg" {
  if (pct == null) return "avg";
  if (pct >= 60) return "green";
  if (pct >= 40) return "gold";
  return "red";
}

function H2HPatternRow({
  label,
  pct,
  count,
  sample,
  insufficient,
}: {
  label: string;
  pct: number | null;
  count: number;
  sample: number;
  insufficient: boolean;
}) {
  const sub = sample > 0 ? `${count}/${sample}` : "";
  const tone = insufficient ? "avg" : patternTone(pct);
  const width = insufficient ? 0 : Math.max(0, Math.min(100, pct ?? 0));
  return (
    <div className="h2h-pl-row">
      <span className="h2h-pl-label">{label}</span>
      <div className="h2h-pl-bar">
        <div className={`h2h-pl-fill ${tone}`} style={{ width: `${width}%` }} />
      </div>
      <div className="h2h-pl-val">
        <span className={tone}>{insufficient ? sub || "—" : pct == null ? "—" : `${pct}%`}</span>
        {!insufficient && sub ? <small>{sub}</small> : null}
      </div>
    </div>
  );
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

  if (loading) return <p className="overlay-note">Loading H2H…</p>;
  if (error) return <p className="overlay-note">{error}</p>;
  if (!data) return <p className="overlay-note">No H2H data available.</p>;

  const n = data.summary.sample;
  const empty = n === 0;
  const total = data.summary.home_wins + data.summary.draws + data.summary.away_wins || 1;
  const homeW = Math.round((data.summary.home_wins / total) * 100);
  const drawW = Math.round((data.summary.draws / total) * 100);
  const awayW = 100 - homeW - drawW;
  const games = data.fixtures.slice(0, 5);
  const p = data.patterns;
  const homeAvg = n > 0 ? (p.home_goals / n).toFixed(1) : "—";
  const awayAvg = n > 0 ? (p.away_goals / n).toFixed(1) : "—";

  let dominance = "";
  if (p.home_goals && p.away_goals && n >= 5) {
    const ratio = Math.max(p.home_goals, p.away_goals) / Math.min(p.home_goals, p.away_goals);
    if (ratio >= 2) {
      const name = p.home_goals > p.away_goals ? data.home_team : data.away_team;
      const big = Math.max(p.home_goals, p.away_goals);
      const small = Math.min(p.home_goals, p.away_goals);
      dominance =
        ratio >= 2.5
          ? `${name} averages ${(big / n).toFixed(1)} goals vs ${(small / n).toFixed(1)}`
          : `${name} scores 2x more goals (${big} vs ${small})`;
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

  return (
    <div className="h2h-pane">
      <div className="h2h-header">
        <div className="h2h-team-col">
          <div className="h2h-team-name home">{data.home_team || homeTeam}</div>
          <div className="h2h-wins home">{empty ? "—" : data.summary.home_wins}</div>
          <div className="h2h-wins-lbl">Wins</div>
        </div>
        <div className="h2h-center">
          <div className="h2h-draws">{empty ? "—" : data.summary.draws}</div>
          <div className="h2h-wins-lbl">{empty ? "No data" : "Draws"}</div>
          {!empty ? (
            <div className="h2h-sample">
              {n} game{n === 1 ? "" : "s"}
              {data.insufficient ? " · small sample" : ""}
            </div>
          ) : null}
        </div>
        <div className="h2h-team-col">
          <div className="h2h-team-name away">{data.away_team || awayTeam}</div>
          <div className="h2h-wins away">{empty ? "—" : data.summary.away_wins}</div>
          <div className="h2h-wins-lbl">Wins</div>
        </div>
      </div>
      {empty ? (
        <p className="overlay-note">First meeting or history not yet available.</p>
      ) : (
        <>
          <div className="h2h-tug">
            <div className="h2h-tug-home" style={{ width: `${homeW}%` }} />
            <div className="h2h-tug-draw" style={{ width: `${drawW}%` }} />
            <div className="h2h-tug-away" style={{ width: `${awayW}%` }} />
          </div>
          <div className="h2h-goals">
            <div>
              <div className="h2h-goals-num home">{homeAvg}</div>
              <div className="h2h-wins-lbl">Goals / game</div>
            </div>
            <div className="h2h-goals-mid">Avg {p.avg_goals ?? "—"}</div>
            <div>
              <div className="h2h-goals-num away">{awayAvg}</div>
              <div className="h2h-wins-lbl">Goals / game</div>
            </div>
          </div>
        </>
      )}
      {games.length ? (
        <div className="h2h-games">
          {games.map((fx) => {
            const usHome = overlayHomeWasHome(
              fx,
              data.home_team || homeTeam,
              data.away_team || awayTeam,
              homeTeamId,
              awayTeamId,
            );
            const wr =
              fx.home_score === fx.away_score
                ? "D"
                : usHome == null
                  ? ""
                  : fx.home_score > fx.away_score
                    ? usHome
                      ? "W"
                      : "L"
                    : usHome
                      ? "L"
                      : "W";
            return (
              <div className="h2h-game" key={`${fx.match_id}-${fx.match_date}`}>
                <span className={`h2h-badge ${wr.toLowerCase()}`}>{wr || "·"}</span>
                <span className={`h2h-gteam${usHome === true ? " hl" : ""}`}>{fx.home_team}</span>
                <span className="h2h-score">
                  {fx.home_score} - {fx.away_score}
                </span>
                <span className={`h2h-gteam right${usHome === false ? " hl" : ""}`}>{fx.away_team}</span>
                <span className="h2h-date">{formatH2HDate(fx.match_date)}</span>
              </div>
            );
          })}
        </div>
      ) : null}
      {games.length ? (
        <p className="h2h-wdl-note">W / D / L is for {data.home_team || homeTeam}</p>
      ) : null}
      <h3 className="h2h-section">
        {empty ? "Pattern statistics - no H2H sample" : `Pattern statistics - last ${n} H2H`}
      </h3>
      <div className="h2h-patterns">
        <H2HPatternRow
          label="Over 2.5 goals"
          pct={p.over_2_5.pct}
          count={p.over_2_5.count}
          sample={n}
          insufficient={data.insufficient}
        />
        <H2HPatternRow
          label="Both teams score"
          pct={p.btts.pct}
          count={p.btts.count}
          sample={n}
          insufficient={data.insufficient}
        />
        <H2HPatternRow
          label="Draws"
          pct={n > 0 ? Math.round((data.summary.draws / n) * 100) : null}
          count={data.summary.draws}
          sample={n}
          insufficient={data.insufficient}
        />
        <H2HPatternRow
          label={`${data.home_team || homeTeam} clean sheet`}
          pct={p.home_cs.pct}
          count={p.home_cs.count}
          sample={n}
          insufficient={data.insufficient}
        />
        <H2HPatternRow
          label={`${data.away_team || awayTeam} clean sheet`}
          pct={p.away_cs.pct}
          count={p.away_cs.count}
          sample={n}
          insufficient={data.insufficient}
        />
      </div>
      {timingRows.length && timing ? (
        <>
          <h3 className="h2h-section">Timing patterns - last {timing.sample} H2H</h3>
          <div className="h2h-patterns">
            {timingRows.map((slot) => {
              const row = timing[slot.key] as H2HCount;
              return (
                <H2HPatternRow
                  key={slot.key}
                  label={slot.label}
                  pct={row.pct}
                  count={row.count}
                  sample={timing.sample}
                  insufficient={data.insufficient}
                />
              );
            })}
          </div>
        </>
      ) : null}
      {dominance ? <p className="h2h-dominance">{dominance}</p> : null}
      {data.insufficient && n > 0 ? (
        <p className="overlay-note">
          Only {n} meeting{n === 1 ? "" : "s"} - percentages stay hidden until 5.
        </p>
      ) : null}
    </div>
  );
}

export function MatchOverlay({
  match,
  onClose,
}: {
  match: OverlayMatch;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<TabId>("stats");
  const [panel, setPanel] = useState<MatchPanel>(() => panelFromLive(match));
  const [loadError, setLoadError] = useState<string | null>(null);

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

  const events = useMemo(
    () =>
      [...panel.events].sort(
        (a, b) => a.minute - b.minute || a.event_type.localeCompare(b.event_type),
      ),
    [panel.events],
  );

  return (
    <div
      className="overlay-backdrop"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="overlay"
        role="dialog"
        aria-modal="true"
        aria-labelledby="overlay-title"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="overlay-head">
          <div className="overlay-teams">
            <div className="overlay-side">
              <OverlayBadge name={panel.home_team} src={panel.home_team_logo} />
              <span>{panel.home_team}</span>
            </div>
            <div className="overlay-scoreblock">
              <p className="overlay-league">
                {panel.league || match.league} · {panel.status_short || match.status_short}{" "}
                {overlayClock(
                  panel.minute,
                  panel.status_short || match.status_short,
                  panel.minute_display || match.minute_display,
                  [
                    ...(panel.events || []).map((event) => event.minute),
                    ...(match.goal_events || []).map((event) => event.minute),
                    ...(match.card_events || []).map((event) => event.minute),
                  ],
                )}
              </p>
              <h2 id="overlay-title" className="overlay-score">
                {panel.score}
              </h2>
            </div>
            <div className="overlay-side away">
              <span>{panel.away_team}</span>
              <OverlayBadge name={panel.away_team} src={panel.away_team_logo} />
            </div>
          </div>
          <button type="button" className="ghost overlay-close" onClick={onClose}>
            Close
          </button>
        </header>
        <nav className="overlay-tabs" aria-label="Match sections">
          {TABS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={tab === item.id ? "tab on" : "tab"}
              onClick={() => setTab(item.id)}
            >
              {item.label}
            </button>
          ))}
        </nav>
        {loadError ? (
          <p className="overlay-note">Showing live row until the panel feed catches up.</p>
        ) : null}
        <div className="overlay-body">
          {tab === "stats" ? (
            <div className="overlay-stats">
              <section>
                {STAT_BARS.map((row) => (
                  <DualBar
                    key={row.key}
                    label={row.label}
                    home={Number(panel.stat_lines[row.key]?.home || 0)}
                    away={Number(panel.stat_lines[row.key]?.away || 0)}
                  />
                ))}
              </section>
              <section className="overlay-signals">
                <h3>Signals</h3>
                {STRAT_ROWS.map((row) => {
                  const block = panel.strategy_status[row.key];
                  return (
                    <DualBar
                      key={row.key}
                      label={row.label}
                      home={Number(block?.teams?.home?.value || 0)}
                      away={Number(block?.teams?.away?.value || 0)}
                      digits={row.digits}
                      homeTriggered={Boolean(block?.teams?.home?.triggered)}
                      awayTriggered={Boolean(block?.teams?.away?.triggered)}
                      tip={row.tip}
                      suffix={row.suffix}
                      signed={row.signed}
                      homeName={panel.home_team}
                      awayName={panel.away_team}
                      tone={row.tone}
                      scale={row.scale}
                    />
                  );
                })}
              </section>
            </div>
          ) : null}
          {tab === "timeline" ? (
            <div className="overlay-timeline">
              <DangerPulseChart
                points={panel.timeline}
                events={events}
                title="Dangerous attacks"
                blurb="Per-minute intensity, not a running total. Home pulses above the midline, away below. The line follows those peaks."
                homeName={panel.home_team}
                awayName={panel.away_team}
                currentMinute={panel.minute}
              />
              <MatchStory
                events={events}
                substitutions={panel.substitutions}
                liveScore={panel.score}
                status={panel.status_short || match.status_short}
                minute={panel.minute}
              />
            </div>
          ) : null}
          {tab === "omega" ? (
            <div className="overlay-timeline">
              <SeriesChart
                points={panel.timeline}
                homeOf={(p) => Number(p.omega.home || 0)}
                awayOf={(p) => Number(p.omega.away || 0)}
                events={events}
                title="Omega tilt"
                blurb="How steeply pressure is building, in degrees. 20° is building. 30° fires. 35°+ is rare. Negative means the wave is flattening."
                homeName={panel.home_team}
                awayName={panel.away_team}
                unit="°"
                signed
                guide={30}
                guideLabel="Fire 30°"
              />
              <SeriesChart
                points={panel.timeline}
                homeOf={(p) => Number(p.rule_of_three.home || 0)}
                awayOf={(p) => Number(p.rule_of_three.away || 0)}
                events={events}
                title="Unrealised goals"
                blurb="Shots versus the scoreboard. Around 1 they are overdue. Negative means they have already scored more than the chances say."
                homeName={panel.home_team}
                awayName={panel.away_team}
                signed
              />
            </div>
          ) : null}
          {tab === "h2h" ? (
            <H2HPane
              matchId={panel.match_id}
              homeTeam={panel.home_team}
              awayTeam={panel.away_team}
              homeTeamId={panel.home_team_id}
              awayTeamId={panel.away_team_id}
            />
          ) : null}
          {tab === "lineups" ? (
            <div className="overlay-lineups">
              <LineupColumn
                name={panel.home_team}
                src={panel.home_team_logo}
                lineup={panel.lineup.home}
              />
              <LineupColumn
                name={panel.away_team}
                src={panel.away_team_logo}
                lineup={panel.lineup.away}
              />
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
