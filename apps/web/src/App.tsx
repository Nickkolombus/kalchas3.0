import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent,
} from "react";
import { HoverTip } from "./HoverTip";
import { MatchOverlay } from "./MatchPanel";
import kalchasMark from "./assets/kalchas-mark.png";

type SideValue = { home: number; away: number };
type TeamCell = { value: number; triggered?: boolean };
type StrategyBlock = {
  teams: { home?: TeamCell; away?: TeamCell };
  threshold?: number;
  match?: number | null;
};

type OddsLine = {
  home?: number;
  draw?: number;
  away?: number;
};

type OddsFlat = OddsLine & {
  matched?: number;
  kickoff?: OddsLine | null;
  live?: OddsLine | null;
};

type LastGoal = {
  minute?: number;
  side?: string;
  team?: string;
};

type MatchEvent = {
  event_type: "goal" | "card" | string;
  minute: number;
  side: string;
  team?: string | null;
  player_name?: string | null;
  detail?: string | null;
};

export type LiveMatch = {
  match_id: string;
  home_team: string;
  away_team: string;
  minute: number;
  score: string;
  league?: string | null;
  status_short?: string | null;
  minute_display?: string | null;
  country_code?: string | null;
  country_name?: string | null;
  country_logo?: string | null;
  home_team_id?: number | null;
  away_team_id?: number | null;
  home_team_logo?: string | null;
  away_team_logo?: string | null;
  hot_score?: number;
  stat_lines?: Record<string, SideValue>;
  strategy_status?: Record<string, StrategyBlock>;
  active_strategies?: string[];
  odds?: OddsFlat | null;
  last_goal?: LastGoal | null;
  goal_events?: { minute: number; side: string }[];
  card_events?: MatchEvent[];
  /** Explicit override from the feed. When omitted, activity counters decide. */
  statless?: boolean;
};

type RecentAlert = {
  id: number;
  match_id: string;
  strategy: string;
  team?: string | null;
  value: number;
  minute: number;
  score?: string | null;
  home_team?: string | null;
  away_team?: string | null;
  state?: string;
  kind?: string | null;
  scoring_side?: string | null;
  goal_minute?: number | null;
  opponent_side?: string | null;
  delivery_status?: string;
  created_at: string;
  current_score?: string | null;
  current_minute?: number | null;
  current_status?: string | null;
};
type SweetSpot = {
  ht1_start: number;
  ht1_end: number;
  ht2_start: number;
  ht2_end: number;
  include_injury_time: boolean;
};
type LiveResponse = {
  matches: LiveMatch[];
  source: string;
  recent_alerts?: RecentAlert[];
  sweet_spot?: SweetSpot;
};
type FeedStatus = {
  state: string;
  mode: string;
  connected: boolean;
  last_message_at?: string | null;
  last_http_poll_at?: string | null;
  updated_at?: string | null;
};
type SortKey =
  | "league"
  | "score"
  | "match"
  | "minute"
  | "odds"
  | "kscore"
  | "rule_of_three"
  | "delta_5min"
  | "pressure_index"
  | "delta_goal"
  | "npei"
  | "omega"
  | "tslg"
  | "shots_on_target"
  | "shots_off_target"
  | "attacks"
  | "dangerous_attacks"
  | "corners"
  | "possession";
type SortDir = "asc" | "desc";

const POLL_MS = 15_000;
const FAV_KEY = "kalchas.favorites.v1";
const DEFAULT_SWEET_SPOT: SweetSpot = {
  ht1_start: 28,
  ht1_end: 44,
  ht2_start: 72,
  ht2_end: 88,
  include_injury_time: false,
};
const TSLG_COOLDOWN = 10;
const FINISHED_STATUS = new Set([
  "FT",
  "AET",
  "PEN",
  "PST",
  "CANC",
  "ABD",
  "SUSP",
  "AWD",
  "WO",
  "W/O",
]);

/** Feed wording shown to end users. Provider and billing detail stays server-side. */
const FEED_COPY: Record<string, { label: string; title: string; body: string }> = {
  live: {
    label: "Live",
    title: "Live coverage active",
    body: "Match data is updating as play develops.",
  },
  idle: {
    label: "Idle",
    title: "No supported matches are live right now",
    body: "Coverage appears automatically when the next match kicks off.",
  },
  paused: {
    label: "Paused",
    title: "Live coverage is temporarily paused",
    body: "Match data will return shortly.",
  },
  starting: {
    label: "Starting",
    title: "Connecting to live coverage",
    body: "The match feed is starting up.",
  },
  unconfigured: {
    label: "Offline",
    title: "Live coverage is not configured",
    body: "This dashboard is running without a match feed.",
  },
};

const STRATEGY_CARD: Record<string, string> = {
  rule_of_three: "Unrealised Goals",
  delta_5min: "Δ5′",
  pressure_index: "Δ10′",
  delta_goal: "League Bar",
  npei: "ΦI",
  omega: "Ωmega",
  kscore: "K Index",
};

const SIGNAL_TONE: Record<string, string> = {
  Monitoring: "monitoring",
  Confirmed: "confirmed",
  Expired: "expired",
};

const KIND_RANK: Record<string, number> = {
  confirmed: 0,
  monitoring: 1,
  counter_scored: 2,
  too_late: 3,
  half_ended: 4,
  no_goal: 5,
};

const STRAT_COLS: {
  key: string;
  label: string;
  name: string;
  digits: number;
  tip: string;
  suffix?: string;
  signed?: boolean;
  tone: string;
}[] = [
  {
    key: "rule_of_three",
    label: "UrG",
    name: "Unrealised goals",
    digits: 1,
    tone: "urg",
    tip: "Shots say they should have scored more. Around 1 is worth a look. Negative means the score is already ahead of the chances.",
  },
  {
    key: "delta_5min",
    label: "Δ5′",
    name: "5-minute spike",
    digits: 1,
    tone: "d5",
    tip: "A burst in the last 5 minutes. 4 is common. 8+ is a real wave.",
  },
  {
    key: "pressure_index",
    label: "Δ10′",
    name: "Sustained pressure",
    digits: 0,
    tone: "d10",
    tip: "Pressure over about 10 minutes, out of 100. 70 is a surge. 90+ is a siege.",
  },
  {
    key: "delta_goal",
    label: "L Bar",
    name: "League Bar",
    digits: 1,
    signed: true,
    tone: "lbar",
    tip: "Are they more likely to score than a typical side in this league, right now. 0 is average. +6 is clearly above.",
  },
  {
    key: "npei",
    label: "ΦI",
    name: "Efficiency",
    digits: 0,
    tone: "phi",
    tip: "How well attacks become shots, out of 100. High means clinical, not just busy.",
  },
  {
    key: "omega",
    label: "Ω",
    name: "Omega",
    digits: 0,
    suffix: "°",
    tone: "omega",
    tip: "How steeply pressure is building, in degrees. 20° is building. 30° fires. 35°+ is rare. Negative means it is flattening.",
  },
];

const STAT_COLS: { key: string; label: string }[] = [
  { key: "shots_on_target", label: "SOT" },
  { key: "shots_off_target", label: "SOFF" },
  { key: "attacks", label: "ATT" },
  { key: "dangerous_attacks", label: "DA" },
  { key: "corners", label: "CRN" },
  { key: "possession", label: "POS" },
  { key: "yellow_cards", label: "YC" },
  { key: "red_cards", label: "RC" },
];

function fmtCell(v: number | undefined | null, digits = 1): string {
  if (v === undefined || v === null || Number.isNaN(v)) return "—";
  return Number.isInteger(v) && digits === 0
    ? String(v)
    : Number(v).toFixed(digits);
}

function fmtStrat(
  v: number | undefined | null,
  digits: number,
  extras?: { suffix?: string; signed?: boolean },
): string {
  if (v === undefined || v === null || Number.isNaN(v)) return "—";
  const core =
    extras?.signed && v > 0
      ? `+${fmtCell(v, digits)}`
      : fmtCell(v, digits);
  return extras?.suffix && core !== "—" ? `${core}${extras.suffix}` : core;
}

function fmtAlertValue(alert: RecentAlert): string {
  if (alert.strategy === "omega") {
    return fmtStrat(alert.value, 0, { signed: true, suffix: "°" });
  }
  if (alert.strategy === "delta_goal") {
    return fmtStrat(alert.value, 1, { signed: true });
  }
  if (alert.strategy === "kscore" || alert.strategy === "pressure_index") {
    return fmtStrat(alert.value, 0);
  }
  return fmtStrat(alert.value, 1);
}

function agoText(iso?: string | null): string {
  const ago = minutesAgo(iso);
  if (ago == null || ago < 1) return "";
  return `${ago}′ ago`;
}

function flagEmoji(cc?: string | null): string {
  if (!cc || cc.length !== 2) return "";
  const base = 0x1f1e6;
  return String.fromCodePoint(
    ...[...cc.toUpperCase()].map((c) => base + c.charCodeAt(0) - 65),
  );
}

function flagCdnUrl(cc?: string | null): string {
  if (!cc || cc.length !== 2) return "";
  return `https://flagcdn.com/20x15/${cc.toLowerCase()}.png`;
}

function apifootballBadgeUrl(
  teamId?: number | null,
  teamName?: string,
): string {
  if (!teamId || teamId <= 0 || !teamName) return "";
  let slug = teamName
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "");
  while (/^[a-z]\.\s*/.test(slug)) {
    slug = slug.replace(/^[a-z]\.\s*/, "");
  }
  slug = slug
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-+|-+$/g, "");
  if (!slug) return "";
  return `https://apiv3.apifootball.com/badges/${teamId}_${slug}.jpg`;
}

function loadFavorites(): Set<string> {
  try {
    const raw = localStorage.getItem(FAV_KEY);
    const arr = raw ? (JSON.parse(raw) as string[]) : [];
    return new Set(arr);
  } catch {
    return new Set();
  }
}

function saveFavorites(ids: Set<string>) {
  localStorage.setItem(FAV_KEY, JSON.stringify([...ids]));
}

function matchK(m: LiveMatch): number {
  const k = m.strategy_status?.kscore;
  return Number(k?.match ?? m.hot_score ?? 0);
}

function scoreTotal(m: LiveMatch): number {
  const [h, a] = m.score.split("-").map((x) => Number(x.trim()) || 0);
  return h + a;
}

function tslgMinutes(match: LiveMatch): {
  home: number | null;
  away: number | null;
} {
  let homeGoal: number | null = null;
  let awayGoal: number | null = null;
  for (const g of match.goal_events || []) {
    if (g.side === "home") homeGoal = g.minute;
    if (g.side === "away") awayGoal = g.minute;
  }
  if (match.last_goal?.minute != null) {
    if (match.last_goal.side === "home") homeGoal = match.last_goal.minute;
    if (match.last_goal.side === "away") awayGoal = match.last_goal.minute;
  }
  return {
    home: homeGoal != null ? Math.max(0, match.minute - homeGoal) : null,
    away: awayGoal != null ? Math.max(0, match.minute - awayGoal) : null,
  };
}

function minTslg(match: LiveMatch): number {
  const t = tslgMinutes(match);
  const vals = [t.home, t.away].filter((v): v is number => v != null);
  if (!vals.length) return Number.POSITIVE_INFINITY;
  return Math.min(...vals);
}

function stratMax(m: LiveMatch, key: string): number {
  const b = m.strategy_status?.[key];
  return Math.max(b?.teams?.home?.value ?? 0, b?.teams?.away?.value ?? 0);
}

function statMax(m: LiveMatch, key: string): number {
  const s = m.stat_lines?.[key];
  return Math.max(s?.home ?? 0, s?.away ?? 0);
}

/** Shots, attacks, corners. Possession 50/50 and cards do not count as stats. */
const ACTIVITY_STAT_KEYS = [
  "shots_on_target",
  "shots_off_target",
  "attacks",
  "dangerous_attacks",
  "corners",
] as const;

function isMatchStatless(m: LiveMatch): boolean {
  if (m.statless === true) return true;
  if (m.statless === false) return false;
  const lines = m.stat_lines || {};
  return !ACTIVITY_STAT_KEYS.some((key) => {
    const line = lines[key];
    return Number(line?.home || 0) > 0 || Number(line?.away || 0) > 0;
  });
}

function compareMatches(
  a: LiveMatch,
  b: LiveMatch,
  key: SortKey,
  dir: SortDir,
): number {
  let cmp = 0;
  switch (key) {
    case "league":
      cmp = String(a.league || "").localeCompare(String(b.league || ""));
      break;
    case "score":
      cmp = scoreTotal(a) - scoreTotal(b);
      break;
    case "match":
      cmp = a.home_team.localeCompare(b.home_team);
      break;
    case "minute":
      cmp = a.minute - b.minute;
      break;
    case "odds":
      cmp = (a.odds?.home ?? 99) - (b.odds?.home ?? 99);
      break;
    case "kscore":
      cmp = matchK(a) - matchK(b);
      break;
    case "tslg": {
      const am = minTslg(a);
      const bm = minTslg(b);
      const ax = Number.isFinite(am) ? am : 999;
      const bx = Number.isFinite(bm) ? bm : 999;
      cmp = ax - bx;
      break;
    }
    case "rule_of_three":
    case "delta_5min":
    case "pressure_index":
    case "delta_goal":
    case "npei":
    case "omega":
      cmp = stratMax(a, key) - stratMax(b, key);
      break;
    default:
      cmp = statMax(a, key) - statMax(b, key);
  }
  return dir === "asc" ? cmp : -cmp;
}

function SortTh({
  label,
  sortKey,
  activeKey,
  dir,
  onSort,
  className,
  hintTitle,
  hintBody,
}: {
  label: string;
  sortKey: SortKey;
  activeKey: SortKey;
  dir: SortDir;
  onSort: (k: SortKey) => void;
  className?: string;
  hintTitle?: string;
  hintBody?: string;
}) {
  const active = activeKey === sortKey;
  const inner = (
    <span className="th-inner">
      <span className="th-label">{label}</span>
      <span className="th-dir" aria-hidden>
        {active ? (dir === "asc" ? "↑" : "↓") : ""}
      </span>
    </span>
  );
  return (
    <th
      className={`sortable ${className || ""}${active ? " sorted" : ""}`}
      onClick={() => onSort(sortKey)}
    >
      {hintBody ? (
        <HoverTip title={hintTitle || label} body={<p>{hintBody}</p>}>
          {inner}
        </HoverTip>
      ) : (
        inner
      )}
    </th>
  );
}

function LeagueCell({
  league,
  countryCode,
  countryLogo,
}: {
  league?: string | null;
  countryCode?: string | null;
  countryLogo?: string | null;
}) {
  const [flagFailed, setFlagFailed] = useState(false);
  const src = countryLogo || flagCdnUrl(countryCode);
  return (
    <td className="col-league">
      <div className="band">
        <div className="band-line">
          {src && !flagFailed ? (
            <img
              className="flag-img"
              src={src}
              alt={countryCode || ""}
              loading="lazy"
              onError={() => setFlagFailed(true)}
            />
          ) : (
            <span className="flag-fallback">{flagEmoji(countryCode) || "•"}</span>
          )}
        </div>
        <div className="band-line">
          <span
            className="league-name"
            title={league || ""}
            style={{ WebkitBoxOrient: "vertical" }}
          >
            {league || "—"}
          </span>
        </div>
      </div>
    </td>
  );
}

function TeamBadge({ name, src }: { name: string; src?: string | null }) {
  const [failed, setFailed] = useState(!src);
  const initial = (name || "?").charAt(0).toUpperCase();
  return (
    <span className={`badge-wrap${failed || !src ? " is-fallback" : ""}`}>
      {src && !failed ? (
        <img
          className="badge-img"
          src={src}
          alt=""
          loading="lazy"
          onError={() => setFailed(true)}
        />
      ) : null}
      <span className="badge-fallback" aria-hidden>
        {initial}
      </span>
    </span>
  );
}

function TeamStack({ match }: { match: LiveMatch }) {
  const homeLogo =
    match.home_team_logo ||
    apifootballBadgeUrl(match.home_team_id, match.home_team);
  const awayLogo =
    match.away_team_logo ||
    apifootballBadgeUrl(match.away_team_id, match.away_team);
  return (
    <div className="team-stack">
      <div className="team-line">
        <TeamBadge name={match.home_team} src={homeLogo} />
        <span className="team-label">{match.home_team}</span>
      </div>
      <div className="team-line">
        <TeamBadge name={match.away_team} src={awayLogo} />
        <span className="team-label">{match.away_team}</span>
      </div>
    </div>
  );
}

function StratCell({
  match,
  block,
  col,
}: {
  match: LiveMatch;
  block?: StrategyBlock;
  col: (typeof STRAT_COLS)[number];
}) {
  const home = block?.teams?.home;
  const away = block?.teams?.away;
  const extras = { suffix: col.suffix, signed: col.signed };
  return (
    <td className={`col-strat col-tone-${col.tone}`}>
      <HoverTip
        title={`${col.name} - ${match.home_team} vs ${match.away_team}`}
        body={
          <>
            <p>{col.tip}</p>
            <p>
              <strong>H</strong> {fmtStrat(home?.value, col.digits, extras)}
              {home?.triggered ? " · triggered" : ""}
            </p>
            <p>
              <strong>A</strong> {fmtStrat(away?.value, col.digits, extras)}
              {away?.triggered ? " · triggered" : ""}
            </p>
          </>
        }
      >
        <div className="band">
          <div className={`band-line team-row${home?.triggered ? " trig" : ""}`}>
            <span className="tag">H</span>
            <span className="val">{fmtStrat(home?.value, col.digits, extras)}</span>
          </div>
          <div className={`band-line team-row${away?.triggered ? " trig" : ""}`}>
            <span className="tag">A</span>
            <span className="val">{fmtStrat(away?.value, col.digits, extras)}</span>
          </div>
        </div>
      </HoverTip>
    </td>
  );
}

function StatCell({ line, start }: { line?: SideValue; start?: boolean }) {
  return (
    <td className={`col-stat${start ? " col-stat-start" : ""}`}>
      <div className="band">
        <div className="band-line">{fmtCell(line?.home, 0)}</div>
        <div className="band-line">{fmtCell(line?.away, 0)}</div>
      </div>
    </td>
  );
}

function ScoreCell({ score }: { score: string }) {
  const [home, away] = score.split("-");
  return (
    <td className="col-score">
      <div className="band">
        <div className="band-line score-n">{home?.trim() ?? "—"}</div>
        <div className="band-line score-n">{away?.trim() ?? "—"}</div>
      </div>
    </td>
  );
}

function displayClockToken(display?: string | null): string {
  return (display || "").replace(/′/g, "'").replace(/\s+/g, "").replace(/'$/, "");
}

function formatInjuryClock(raw?: string | null): string {
  const token = displayClockToken(raw);
  const plus = token.indexOf("+");
  if (plus < 0) return token ? `${token}'` : "";
  const base = token.slice(0, plus);
  const added = token.slice(plus + 1);
  return added ? `${base}'+${added}'` : `${base}+'`;
}

function stoppageDisplayFromEvents(
  display?: string | null,
  match?: Pick<LiveMatch, "goal_events" | "card_events" | "last_goal">,
): string {
  const token = displayClockToken(display);
  if (!token.includes("+")) return (display || "").trim();
  const [baseS, stated = ""] = token.split("+", 2);
  const base = Number(baseS);
  if (!Number.isFinite(base)) return token;
  let added = /^\d+$/.test(stated) ? Number(stated) : 0;
  const minutes = [
    ...(match?.goal_events || []).map((event) => event.minute),
    ...(match?.card_events || []).map((event) => event.minute),
    match?.last_goal?.minute,
  ];
  for (const minute of minutes) {
    if (typeof minute === "number" && minute > base && minute <= base + 15) {
      added = Math.max(added, minute - base);
    }
  }
  return added ? `${base}+${added}` : `${base}+`;
}

function isFirstHalfInjury(
  minute: number,
  status?: string | null,
  display?: string | null,
): boolean {
  if (displayClockToken(display).startsWith("45+")) return true;
  return (status || "").toUpperCase() === "1H" && minute > 45;
}

function isSecondHalfInjury(
  minute: number,
  status?: string | null,
  display?: string | null,
): boolean {
  if (displayClockToken(display).startsWith("90+")) return true;
  return (status || "").toUpperCase() === "2H" && minute > 90;
}

function inSweetSpot(match: LiveMatch, windows: SweetSpot): boolean {
  const status = (match.status_short || "").toUpperCase();
  if (status === "ET") return false;
  if (
    isFirstHalfInjury(match.minute, match.status_short, match.minute_display) ||
    isSecondHalfInjury(match.minute, match.status_short, match.minute_display)
  ) {
    return windows.include_injury_time;
  }
  const minute = match.minute;
  return (
    (windows.ht1_start <= minute && minute <= windows.ht1_end) ||
    (windows.ht2_start <= minute && minute <= windows.ht2_end)
  );
}

function clockFace(
  minute: number,
  status?: string | null,
  display?: string | null,
): { label: string; phase: string } {
  const statusU = (status || "").toUpperCase();
  if (statusU === "HT") return { label: "☕", phase: "HT" };
  if (statusU === "FT") return { label: "FT", phase: "Full" };

  let phase = statusU || "LIVE";
  if (statusU === "1H" || statusU === "2H" || statusU === "ET") {
    phase = statusU;
  } else if (/^\d+$/.test(statusU)) {
    const elapsed = Number(statusU);
    phase = elapsed <= 45 ? "1H" : elapsed <= 90 ? "2H" : "ET";
  } else if (minute > 45 && minute <= 90) {
    phase = "2H";
  } else if (minute > 90) {
    phase = statusU === "2H" ? "2H" : "ET";
  } else if (minute > 0) {
    phase = "1H";
  }

  const raw = (display || "").trim().replace(/′/g, "'").replace(/'$/, "");
  if (raw.includes("+")) {
    return { label: formatInjuryClock(raw), phase };
  }
  if (statusU === "1H" && minute > 45) {
    return { label: formatInjuryClock(`45+${minute - 45}`), phase: "1H" };
  }
  if (statusU === "2H" && minute > 90) {
    return { label: formatInjuryClock(`90+${minute - 90}`), phase: "2H" };
  }
  if (/^\d+$/.test(statusU)) {
    return { label: `${Number(statusU)}'`, phase };
  }
  return { label: `${minute}'`, phase };
}

function TimeCell({ match }: { match: LiveMatch }) {
  const display = stoppageDisplayFromEvents(match.minute_display, match);
  const face = clockFace(match.minute, match.status_short, display);
  return (
    <td className="col-time">
      <div className="band">
        <div className="band-line time-min">{face.label}</div>
        <div className="band-line time-phase">{face.phase}</div>
      </div>
    </td>
  );
}

function hasOddsLine(line?: OddsLine | null): boolean {
  return Boolean(line && (line.home != null || line.draw != null || line.away != null));
}

function OddsPills({ line }: { line: OddsLine }) {
  const pill = (v: number | undefined | null) =>
    v === undefined || v === null || Number.isNaN(v) ? "-" : Number(v).toFixed(2);
  return (
    <div className="band-line odds-row">
      <span className="odds-pill">{pill(line.home)}</span>
      <span className="odds-pill">{pill(line.draw)}</span>
      <span className="odds-pill">{pill(line.away)}</span>
    </div>
  );
}

function OddsCell({ odds }: { odds?: OddsFlat | null }) {
  const kickoff = odds?.kickoff ?? (hasOddsLine(odds) ? odds : null);
  const live = odds?.live ?? null;
  const showKo = hasOddsLine(kickoff);
  const showLive = hasOddsLine(live);
  if (!showKo && !showLive) {
    return (
      <td className="col-odds">
        <div className="band band-center">
          <div className="band-span muted">-</div>
        </div>
      </td>
    );
  }
  return (
    <td className="col-odds">
      <div className="band band-center odds-stack">
        {showKo && kickoff ? (
          <div className="odds-pair">
            <span className="odds-tag">KO</span>
            <OddsPills line={kickoff} />
          </div>
        ) : null}
        {showLive && live ? (
          <div className="odds-pair">
            <span className="odds-tag">Live</span>
            <OddsPills line={live} />
          </div>
        ) : null}
      </div>
    </td>
  );
}

function KCell({ match }: { match: LiveMatch }) {
  const score = matchK(match);
  const k = match.strategy_status?.kscore;
  return (
    <td className="col-k col-strat col-tone-k">
      <HoverTip
        title={`K·idx - ${match.home_team} vs ${match.away_team}`}
        body={
          <>
            <p>Blend of the other signals, out of 100. 60+ is a picked match.</p>
            <p>
              <strong>Match</strong> {score < 5 ? "—" : score}
            </p>
            <p>
              <strong>H</strong> {fmtCell(k?.teams?.home?.value, 0)}
              {k?.teams?.home?.triggered ? " · triggered" : ""}
            </p>
            <p>
              <strong>A</strong> {fmtCell(k?.teams?.away?.value, 0)}
              {k?.teams?.away?.triggered ? " · triggered" : ""}
            </p>
          </>
        }
      >
        <div className="band band-center">
          <div className={`band-span k-num${score < 5 ? " muted" : ""}`}>
            {score < 5 ? "—" : score}
          </div>
        </div>
      </HoverTip>
    </td>
  );
}

function TslgCell({ match }: { match: LiveMatch }) {
  const t = tslgMinutes(match);
  const homeCd = t.home != null && t.home < TSLG_COOLDOWN;
  const awayCd = t.away != null && t.away < TSLG_COOLDOWN;
  return (
    <td className="col-tslg col-strat col-tone-tslg">
      <HoverTip
        title={`TSLG - minutes since last goal`}
        body={
          <>
            <p>Minutes since that team last scored. Alerts stay quiet for 10 minutes after a goal.</p>
            <p>
              <strong>H</strong>{" "}
              {t.home == null ? "—" : `${t.home}'`}
              {homeCd ? " · cooldown" : ""}
            </p>
            <p>
              <strong>A</strong>{" "}
              {t.away == null ? "—" : `${t.away}'`}
              {awayCd ? " · cooldown" : ""}
            </p>
          </>
        }
      >
        <div className="band">
          <div className={`band-line${homeCd ? " tslg-cd" : ""}`}>
            {t.home == null ? "—" : `${t.home}'`}
          </div>
          <div className={`band-line${awayCd ? " tslg-cd" : ""}`}>
            {t.away == null ? "—" : `${t.away}'`}
          </div>
        </div>
      </HoverTip>
    </td>
  );
}

function clockTime(iso?: string | null): string {
  if (!iso) return "";
  const at = new Date(iso);
  return Number.isNaN(at.getTime())
    ? ""
    : at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

function minutesAgo(iso?: string | null): number | null {
  if (!iso) return null;
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return null;
  return Math.max(0, Math.floor((Date.now() - at.getTime()) / 60_000));
}

function signalClock(
  minute: number | null | undefined,
  status?: string | null,
): string {
  const phase = (status || "").trim().toUpperCase();
  if (phase === "HT" || phase === "BT") {
    return phase;
  }
  if (phase === "PEN" || phase === "P" || phase === "PENALTIES") {
    return "PEN";
  }
  if (minute != null && Number.isFinite(minute) && minute > 0) {
    if (phase === "1H" && minute > 45) return `45'+${minute - 45}'`;
    if (phase === "2H" && minute > 90) return `90'+${minute - 90}'`;
    return `${minute}′`;
  }
  if (phase) {
    return phase;
  }
  return "";
}

function signalProgress(alert: RecentAlert): string {
  const fireScore = alert.score || "–";
  const fireMin = `${alert.minute}′`;
  const liveScore = alert.current_score || "";
  const liveMin = signalClock(alert.current_minute, alert.current_status);
  if (liveScore && liveScore !== fireScore) {
    return `${fireScore} (${fireMin}) → ${liveScore} (${liveMin || fireMin})`;
  }
  if (liveMin) {
    return `${fireScore} (${liveMin})`;
  }
  return `${fireScore} (${fireMin})`;
}

function clipTeamName(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length < 3) return parts.join(" ");
  return parts.slice(0, 2).join(" ");
}

function sideName(
  side: string | null | undefined,
  home: string,
  away: string,
): string | null {
  if (side === "home") return home;
  if (side === "away") return away;
  return null;
}

function triggerClip(alert: RecentAlert): string | null {
  if (alert.team === "home") return clipTeamName(alert.home_team || "Home");
  if (alert.team === "away") return clipTeamName(alert.away_team || "Away");
  return null;
}

function kindOf(alert: RecentAlert): string {
  if (alert.kind) return alert.kind;
  if (alert.state === "Confirmed") return "confirmed";
  if (alert.state === "Monitoring") return "monitoring";
  return "no_goal";
}

function punchAlert(rows: RecentAlert[]): RecentAlert {
  return [...rows].sort(
    (a, b) => (KIND_RANK[kindOf(a)] ?? 9) - (KIND_RANK[kindOf(b)] ?? 9),
  )[0];
}

function groupTone(kind: string, state: string): string {
  if (kind === "confirmed") return "confirmed";
  if (kind === "monitoring") return "monitoring";
  if (kind === "counter_scored") return "counter";
  return SIGNAL_TONE[state] || "expired";
}

function groupRecentAlerts(alerts: RecentAlert[]): RecentAlert[][] {
  const order: string[] = [];
  const byMatch = new Map<string, RecentAlert[]>();
  for (const alert of alerts) {
    const id = alert.match_id;
    if (!byMatch.has(id)) {
      order.push(id);
      byMatch.set(id, []);
    }
    byMatch.get(id)!.push(alert);
  }
  return order.map((id) => {
    const seen = new Set<string>();
    const unique: RecentAlert[] = [];
    for (const row of byMatch.get(id) || []) {
      const key = `${row.strategy}|${row.team || ""}`;
      if (seen.has(key)) continue;
      seen.add(key);
      unique.push(row);
    }
    return unique;
  });
}

function SignalPunch({ alert }: { alert: RecentAlert }) {
  const kind = kindOf(alert);
  const home = alert.home_team || "Home";
  const away = alert.away_team || "Away";
  const scorer = clipTeamName(
    sideName(alert.scoring_side, home, away) ||
      (alert.team === "home" ? home : alert.team === "away" ? away : "") ||
      "",
  );
  const opp = sideName(alert.opponent_side, home, away);
  if (kind === "confirmed") {
    return (
      <div className="signal-right">
        <div className="signal-goal-line">
          <span className="signal-check">✓</span>{" "}
          <span className="signal-punch">⚽GOAL!</span>
        </div>
        {scorer ? <div className="signal-scorer">{scorer}</div> : null}
      </div>
    );
  }
  if (kind === "monitoring") {
    return (
      <div className="signal-right">
        <span className="signal-punch is-watch">MONITORING</span>
      </div>
    );
  }
  if (kind === "counter_scored") {
    return (
      <div className="signal-right">
        <span className="signal-punch is-counter">
          {opp || "Opponent"} counter-scored
        </span>
      </div>
    );
  }
  if (kind === "too_late") {
    const at =
      alert.goal_minute != null && Number.isFinite(alert.goal_minute)
        ? ` (Goal at ${alert.goal_minute}')`
        : "";
    return (
      <div className="signal-right">
        <span className="signal-punch is-miss">Expired{at}</span>
      </div>
    );
  }
  if (kind === "half_ended") {
    return (
      <div className="signal-right">
        <span className="signal-punch is-miss">Expired (No goal by HT)</span>
      </div>
    );
  }
  return (
    <div className="signal-right">
      <span className="signal-punch is-miss">No goal</span>
    </div>
  );
}

function SignalRow({
  alerts,
  onOpen,
}: {
  alerts: RecentAlert[];
  onOpen: (matchId: string) => void;
}) {
  const primary = alerts[0];
  const oldest = alerts[alerts.length - 1];
  const headline = punchAlert(alerts);
  const kind = kindOf(headline);
  const tone = groupTone(kind, headline.state || "Monitoring");
  const latest = [...alerts].sort((a, b) => {
    const ta = Date.parse(a.created_at || "") || 0;
    const tb = Date.parse(b.created_at || "") || 0;
    return tb - ta;
  })[0];
  const lines = [...alerts].sort((a, b) => {
    const ta = Date.parse(a.created_at || "") || 0;
    const tb = Date.parse(b.created_at || "") || 0;
    return ta - tb;
  });
  const sentAt = clockTime(latest?.created_at);
  const latestAgo = agoText(latest?.created_at);
  const progress = signalProgress({
    ...oldest,
    current_score: primary.current_score || oldest.current_score,
    current_minute: primary.current_minute ?? oldest.current_minute,
    current_status: primary.current_status || oldest.current_status,
  });
  return (
    <article
      className={`signal signal--${tone}`}
      onClick={() => onOpen(primary.match_id)}
    >
      <div className="signal-main">
        <div className="signal-headline">
          <span className="signal-teams">
            {primary.home_team || "Home"} vs {primary.away_team || "Away"}
          </span>
        </div>
        <div className="signal-progress">{progress}</div>
        <div className="signal-lines">
          {lines.map((alert) => {
            const clip = triggerClip(alert);
            const ago = agoText(alert.created_at);
            return (
              <div key={alert.id} className="signal-line">
                {clip ? <span className="signal-line-team">{clip} </span> : null}
                {STRATEGY_CARD[alert.strategy] || alert.strategy}
                <span className="signal-sep"> · </span>
                <span className="signal-value">{fmtAlertValue(alert)}</span>
                {ago ? (
                  <>
                    <span className="signal-sep"> · </span>
                    <span className="signal-ago">{ago}</span>
                  </>
                ) : null}
              </div>
            );
          })}
        </div>
        {sentAt ? (
          <div className="signal-meta">
            Triggered {sentAt}
            {latestAgo ? ` · ${latestAgo}` : ""}
          </div>
        ) : null}
      </div>
      <SignalPunch alert={headline} />
    </article>
  );
}

function BoardSearch({
  value,
  onChange,
  locked,
}: {
  value: string;
  onChange: (next: string) => void;
  locked: boolean;
}) {
  const [open, setOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const expanded = open || value.length > 0;

  useEffect(() => {
    if (expanded) inputRef.current?.focus();
  }, [expanded]);

  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (locked) return;
      const target = event.target as HTMLElement | null;
      const typing =
        target?.tagName === "INPUT" ||
        target?.tagName === "TEXTAREA" ||
        Boolean(target?.isContentEditable);
      if (event.key === "/" && !typing && !event.ctrlKey && !event.metaKey && !event.altKey) {
        event.preventDefault();
        setOpen(true);
        return;
      }
      if (event.key === "Escape" && expanded) {
        if (value) onChange("");
        setOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [expanded, locked, onChange, value]);

  return (
    <div
      className={`board-search${expanded ? " is-open" : ""}${value ? " is-active" : ""}`}
    >
      <button
        type="button"
        className="board-search-toggle"
        aria-label={expanded ? "Close search" : "Search team or league"}
        aria-expanded={expanded}
        onClick={() => {
          if (expanded && !value) setOpen(false);
          else setOpen(true);
        }}
      >
        <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true">
          <circle cx="6.5" cy="6.5" r="4.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
          <path d="M10.2 10.2 14 14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
      </button>
      {expanded ? (
        <input
          ref={inputRef}
          className="search-input board-search-input"
          type="search"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onBlur={() => {
            if (!value) setOpen(false);
          }}
          placeholder="Team or league"
          aria-label="Search team or league"
        />
      ) : null}
    </div>
  );
}

export function App() {
  const [matches, setMatches] = useState<LiveMatch[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [feedStatus, setFeedStatus] = useState<FeedStatus | null>(null);
  const [recentAlerts, setRecentAlerts] = useState<RecentAlert[]>([]);
  const [favorites, setFavorites] = useState<Set<string>>(() => loadFavorites());
  const [sortKey, setSortKey] = useState<SortKey>("kscore");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [search, setSearch] = useState("");
  const [triggeredOnly, setTriggeredOnly] = useState(false);
  const [pinnedOnly, setPinnedOnly] = useState(false);
  const [hideHalfTimers, setHideHalfTimers] = useState(true);
  const [hideStatless, setHideStatless] = useState(false);
  const [hideTslgUnder10, setHideTslgUnder10] = useState(true);
  const [sweetSpotOnly, setSweetSpotOnly] = useState(false);
  const [sweetSpot, setSweetSpot] = useState<SweetSpot>(DEFAULT_SWEET_SPOT);
  const [selectedId, setSelectedId] = useState<string | null>(() => {
    const id = new URLSearchParams(window.location.search).get("match");
    return id && id.trim() ? id.trim() : null;
  });

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/live");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const body = (await res.json()) as LiveResponse;
      const rows = Array.isArray(body.matches) ? body.matches : [];
      setMatches(rows);
      setRecentAlerts(body.recent_alerts || []);
      if (body.sweet_spot) setSweetSpot(body.sweet_spot);
      setError(null);
      setUpdatedAt(new Date());
      try {
        const statusRes = await fetch("/api/scanner-status");
        if (statusRes.ok) setFeedStatus((await statusRes.json()) as FeedStatus);
      } catch {
        // The live board remains usable when status telemetry is unavailable.
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load");
    }
  }, []);

  useEffect(() => {
    void load();
    const id = window.setInterval(() => void load(), POLL_MS);
    return () => window.clearInterval(id);
  }, [load]);

  const onSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(
        key === "league" || key === "match" || key === "odds" ? "asc" : "desc",
      );
    }
  };

  const display = useMemo(() => {
    let base = matches;
    const query = search.trim().toLowerCase();
    if (query) {
      base = base.filter(
        (m) =>
          m.home_team.toLowerCase().includes(query) ||
          m.away_team.toLowerCase().includes(query) ||
          (m.league || "").toLowerCase().includes(query),
      );
    }
    if (triggeredOnly) {
      base = base.filter((m) => Boolean(m.active_strategies?.length));
    }
    if (pinnedOnly) {
      base = base.filter((m) => favorites.has(m.match_id));
    }
    base = base.filter(
      (m) => !FINISHED_STATUS.has((m.status_short || "").toUpperCase()),
    );
    if (hideHalfTimers) {
      base = base.filter((m) => (m.status_short || "").toUpperCase() !== "HT");
    }
    if (hideStatless) {
      base = base.filter((m) => !isMatchStatless(m));
    }
    if (hideTslgUnder10) {
      base = base.filter((m) => {
        const mins = minTslg(m);
        return mins === Number.POSITIVE_INFINITY || mins >= TSLG_COOLDOWN;
      });
    }
    if (sweetSpotOnly) {
      base = base.filter((m) => inSweetSpot(m, sweetSpot));
    }
    return [...base].sort((a, b) => {
      const af = favorites.has(a.match_id) ? 1 : 0;
      const bf = favorites.has(b.match_id) ? 1 : 0;
      if (af !== bf) return bf - af;
      return compareMatches(a, b, sortKey, sortDir);
    });
  }, [
    matches,
    search,
    triggeredOnly,
    pinnedOnly,
    hideHalfTimers,
    hideStatless,
    favorites,
    sortKey,
    sortDir,
    hideTslgUnder10,
    sweetSpotOnly,
    sweetSpot,
  ]);

  const selected = display.find((m) => m.match_id === selectedId) ?? null;
  const displayedAlerts = groupRecentAlerts(recentAlerts);

  const reportedState =
    feedStatus?.state ??
    (error && matches.length === 0 ? "paused" : matches.length > 0 ? "live" : "starting");
  // A populated board means data is arriving even when the socket is down.
  const feedState =
    reportedState === "idle" && matches.length > 0 ? "live" : reportedState;
  const feed = {
    state: feedState,
    copy: FEED_COPY[feedState] ?? FEED_COPY.starting,
  };

  const toggleFav = (id: string, e: MouseEvent) => {
    e.stopPropagation();
    setFavorites((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      saveFavorites(next);
      return next;
    });
  };

  return (
    <div className="shell">
      <header className="hero">
        <div className="hero-left">
          <div className="identity">
            <img className="mark" src={kalchasMark} alt="" width={96} height={96} />
            <div className="identity-text">
              <p className="brand">Kalchas</p>
              <h1>Live Match Intelligence</h1>
              <p className="lede">
                Follow pressure, attacking momentum and goal signals as they build
                across every live match - before the score changes.
              </p>
            </div>
          </div>
          <div className="hero-filters">
            <label className="filter-check">
              <input
                type="checkbox"
                checked={triggeredOnly}
                onChange={(event) => setTriggeredOnly(event.target.checked)}
              />
              Triggered
            </label>
            <label className="filter-check">
              <input
                type="checkbox"
                checked={pinnedOnly}
                onChange={(event) => setPinnedOnly(event.target.checked)}
              />
              Pinned
            </label>
            <label className="filter-check">
              <input
                type="checkbox"
                checked={hideHalfTimers}
                onChange={(event) => setHideHalfTimers(event.target.checked)}
              />
              Hide halftimers
            </label>
            <label className="filter-check">
              <input
                type="checkbox"
                checked={hideStatless}
                onChange={(event) => setHideStatless(event.target.checked)}
              />
              Hide statless
            </label>
            <label className="filter-check">
              <input
                type="checkbox"
                checked={hideTslgUnder10}
                onChange={(e) => setHideTslgUnder10(e.target.checked)}
              />
              Hide TSLG &lt; {TSLG_COOLDOWN}&apos;
            </label>
            <label className="filter-check">
              <input
                type="checkbox"
                checked={sweetSpotOnly}
                onChange={(e) => setSweetSpotOnly(e.target.checked)}
              />
              Sweet spot t
            </label>
            <BoardSearch
              value={search}
              onChange={setSearch}
              locked={selectedId != null}
            />
          </div>
        </div>

        <aside className="signals" aria-label="Recent signals">
          <div className="signals-head">
            <span className="section-kicker">Recent signals</span>
            <div className="signals-status">
              <span className="signals-updated">
                {error
                  ? "reconnecting"
                  : updatedAt
                    ? `Updated ${updatedAt.toLocaleTimeString([], {
                        hour: "2-digit",
                        minute: "2-digit",
                        hour12: false,
                      })}`
                    : "Updating"}
              </span>
              <span className={`feed-chip is-${feed.state}`}>
                <span className="feed-dot" />
                {feed.copy.label}
              </span>
            </div>
          </div>
          {displayedAlerts.length ? (
            <div className="signal-list">
              {displayedAlerts.map((alerts) => (
                <SignalRow
                  key={alerts[0].match_id}
                  alerts={alerts}
                  onOpen={setSelectedId}
                />
              ))}
            </div>
          ) : (
            <p className="panel-note">
              No signals yet. Triggered strategies appear here as matches
              develop.
            </p>
          )}
        </aside>
      </header>

      {feed.state !== "live" ? (
        <section className="feed-state" aria-live="polite">
          <span className="feed-dot" />
          <div>
            <strong>{feed.copy.title}</strong>
            <p>{feed.copy.body}</p>
          </div>
        </section>
      ) : null}

      <div className="board-wrap">
        <table className="board">
          <thead>
            <tr>
              <th className="col-fav" aria-label="Favorite" />
              <SortTh
                label="League"
                sortKey="league"
                activeKey={sortKey}
                dir={sortDir}
                onSort={onSort}
                className="col-league"
              />
              <SortTh
                label="Score"
                sortKey="score"
                activeKey={sortKey}
                dir={sortDir}
                onSort={onSort}
                className="col-score"
              />
              <SortTh
                label="Match"
                sortKey="match"
                activeKey={sortKey}
                dir={sortDir}
                onSort={onSort}
                className="col-match"
              />
              <SortTh
                label="Time"
                sortKey="minute"
                activeKey={sortKey}
                dir={sortDir}
                onSort={onSort}
                className="col-time"
              />
              <SortTh
                label="Odds"
                sortKey="odds"
                activeKey={sortKey}
                dir={sortDir}
                onSort={onSort}
                className="col-odds"
                hintTitle="Odds"
                hintBody="KO is the frozen kickoff 1X2. Live is the in-play 1X2. Empty means the provider has no book for that match."
              />
              <SortTh
                label="K·idx"
                sortKey="kscore"
                activeKey={sortKey}
                dir={sortDir}
                onSort={onSort}
                className="col-k col-strat col-tone-k"
                hintTitle="K·idx"
                hintBody="Blend of the other signals, out of 100. 60+ is a picked match."
              />
              {STRAT_COLS.map((c) => (
                <SortTh
                  key={c.key}
                  label={c.label}
                  sortKey={c.key as SortKey}
                  activeKey={sortKey}
                  dir={sortDir}
                  onSort={onSort}
                  className={`col-strat col-tone-${c.tone}`}
                  hintTitle={c.name}
                  hintBody={c.tip}
                />
              ))}
              <SortTh
                label="TSLG"
                sortKey="tslg"
                activeKey={sortKey}
                dir={sortDir}
                onSort={onSort}
                className="col-tslg col-strat col-tone-tslg"
                hintTitle="TSLG"
                hintBody="Minutes since that team last scored. Alerts stay quiet for 10 minutes after a goal."
              />
              {STAT_COLS.map((c, index) => (
                <SortTh
                  key={c.key}
                  label={c.label}
                  sortKey={c.key as SortKey}
                  activeKey={sortKey}
                  dir={sortDir}
                  onSort={onSort}
                  className={`col-stat${index === 0 ? " col-stat-start" : ""}`}
                />
              ))}
            </tr>
          </thead>
          <tbody>
            {display.map((m, idx) => {
              const ss = m.strategy_status || {};
              const fav = favorites.has(m.match_id);
              const hot = Boolean(m.active_strategies?.length);
              const zebra = idx % 2 === 0 ? "row-a" : "row-b";
              return (
                <tr
                  key={m.match_id}
                  className={[
                    zebra,
                    hot ? "row-hot" : "",
                    selectedId === m.match_id ? "row-sel" : "",
                    fav ? "row-fav" : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  onClick={() =>
                    setSelectedId((id) =>
                      id === m.match_id ? null : m.match_id,
                    )
                  }
                >
                  <td className="col-fav">
                    <button
                      type="button"
                      className={`star${fav ? " on" : ""}`}
                      title="Favorite"
                      onClick={(e) => toggleFav(m.match_id, e)}
                    >
                      {fav ? "★" : "☆"}
                    </button>
                  </td>
                  <LeagueCell
                    league={m.league}
                    countryCode={m.country_code}
                    countryLogo={m.country_logo}
                  />
                  <ScoreCell score={m.score} />
                  <td className="col-match">
                    <TeamStack match={m} />
                  </td>
                  <TimeCell match={m} />
                  <OddsCell odds={m.odds} />
                  <KCell match={m} />
                  {STRAT_COLS.map((c) => (
                    <StratCell
                      key={c.key}
                      match={m}
                      block={ss[c.key]}
                      col={c}
                    />
                  ))}
                  <TslgCell match={m} />
                  {STAT_COLS.map((c, index) => (
                    <StatCell
                      key={c.key}
                      line={m.stat_lines?.[c.key]}
                      start={index === 0}
                    />
                  ))}
                </tr>
              );
            })}
            {display.length === 0 ? (
              <tr className="empty-row">
                <td colSpan={22}>
                  {matches.length === 0
                    ? "No live matches are currently available."
                    : "No matches satisfy the selected filters."}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      {selected ? (
        <MatchOverlay
          match={selected}
          onClose={() => setSelectedId(null)}
        />
      ) : null}
    </div>
  );
}
