"""League Bar (Strategy 3, key ``delta_goal``) -- scoring chance vs the league bar.

Display name: **League Bar**. Internal key stays ``delta_goal`` for stability.

The chain estimates short-horizon goal probability from attacking pressure,
compares it to the league (or odds) prior, and reports whether the team is
**below**, **normal**, or **above** that bar (lift ``P / P0``). A 0-20 threat
score still drives alerts when evidence clears the gate.

1. Count attacking events for one team over the last 5 minutes, and over the
   5 minutes before that.
2. Normalise each count by what is typical for the competition, and weight
   them, giving an event score `E`.
3. Compress with `log(1 + E)` and blend the current window with the previous
   one, giving a pressure index `PI`. Squash to a 0-100 pressure score `PS`.
4. Convert `PI` into a probability of scoring in the next 5 minutes, and blend
   it against the competition's prior `P0`. Confidence in the live signal
   (`lambda`) rises with how much has actually happened in the last 10 minutes,
   so a quiet match stays near its prior.
5. Divide by the prior to get lift `L` -- how much more likely a goal is than
   it would be by default. Map `L` onto League Bar: below / normal / above.
6. Map lift onto a signed League Bar score in ``[-10, +10]`` (0 = on the
   league prior) and alert when it clears the threshold with evidence.

Ported from Kalchas 2.2's `strategies/strategy_003_delta_goal/`, which held
roughly 3,900 lines across six files. Only `formula.py` was reachable in
production, and only part of it:

* `enhanced_formula.py` (732 lines) was a stale fork, imported by nothing but
  a migration helper and an archived deploy script.
* `migration_manager.py` (211 lines) was never consulted at runtime.
* `math_engine.py` ran an alternative model in shadow mode on every
  evaluation. Its output was logged and discarded; it never moved an alert.
  It also imported numpy without ever using it.
* `data_collector.py` (940 lines) wrote feature rows to PostgreSQL for later
  analysis, and computed nothing.
* `safe_learning_system.py` nudged the four event weights after each outcome
  and persisted them to JSON. That belongs outside the core: it consumes
  results and produces weight overrides, which arrive here as a `WeightSet`.

What is left is the arithmetic, which is what this module is.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from kalchas_core.match import MatchTimeline, MinuteSnapshot, Side
from kalchas_core.weights import WeightSet

STRATEGY_KEY = "delta_goal"

# --------------------------------------------------------------------------
# Structural constants
# --------------------------------------------------------------------------

WINDOW_MINUTES: Final = 5
CONFIDENCE_WINDOW_MINUTES: Final = 10
MINIMUM_MINUTE: Final = 10
"""Below this the windows have too little history to mean anything.

2.2's `config.json` declared `min_match_minute: 12` and the code used 10,
with a comment noting it had been lowered. The config value was never read.
"""

MAX_THREAT_SCORE: Final = 10.0
"""Half-width of the League Bar scale. Readings live in ``[-10, +10]``."""

BAR_SCORE_MAX: Final = MAX_THREAT_SCORE

DEFAULT_ALERT_THRESHOLD: Final = 6.0
"""Alert when the signed bar score clears this (clearly above the league bar)."""

SNAPSHOT_LOOKBACK: Final = 5
"""How far back to accept a stale snapshot when a minute is missing."""


# --------------------------------------------------------------------------
# Coefficients that 2.2 hardcoded
# --------------------------------------------------------------------------
# None of these were in the weights registry, so none were admin-tunable, and
# most were bare literals inside a 380-line method. Named here rather than
# promoted to the registry: making them tunable is a product decision, and
# this port is meant to change no numbers. Promoting them is a follow-up.

PRESSURE_BLEND: Final = 0.6
"""How much of the pressure index comes from the current window rather than
the previous one. 2.2's `beta`."""

PRESSURE_STEEPNESS: Final = 1.6
"""Slope of the squash from pressure index to 0-100 pressure score. 2.2's `k`."""

CONFIDENCE_SCALE: Final = 6.0
"""Events over 10 minutes needed before the live signal is trusted over the
competition prior. Larger means slower to trust."""

PRESSURE_TO_GOAL_INTERCEPT: Final = -4.5
PRESSURE_TO_GOAL_SLOPE: Final = 0.8
"""Maps pressure index to the chance of scoring in the next 5 minutes."""

ODDS_PRIOR_INTERCEPT: Final = -2.8
ODDS_PRIOR_SLOPE: Final = 0.9
"""Maps a bookmaker odds gap to a prior, replacing the competition average
when odds are available."""

PROBABILITY_CEILING: Final = 0.12
LIFT_CEILING: Final = 2.5
"""Values at which the probability and lift terms are considered maxed out.
A 12% chance of a goal in 5 minutes, or 2.5x the prior, scores full marks."""

# League Bar bands on lift L = P / P0 (1.0 = on the league bar).
LEAGUE_BAR_NORMAL_LOW: Final = 0.85
LEAGUE_BAR_NORMAL_HIGH: Final = 1.15

THREAT_URGENCY_MULTIPLIER: Final = 0.2
"""Boost to the whole threat score from late, close-game urgency.

Distinct from the registry's `time_urgency_mult`, which 2.2 applied earlier to
the probability. Two separate urgency adjustments compound in the live path.
"""

LATE_GAME_PROBABILITY_BONUS: Final = 0.1
TIED_GAME_PROBABILITY_BONUS: Final = 0.05
"""Added to the probability weight when the match is late and when it is level,
so the same pressure counts for more when a goal matters more."""

MINIMUM_LIVE_THREAT: Final = 0.5
"""Legacy floor for the old composite scorer; unused by League Bar score."""

LATE_GAME_MINUTE: Final = 75
EARLY_GAME_MINUTE: Final = 30

TIER_ORANGE_MARGIN: Final = 2.0
TIER_RED_MARGIN: Final = 3.5

SUSTAINED_ATTACK_EVENTS: Final = 3
CORNER_SEQUENCE_CORNERS: Final = 3
SHOT_BURST_SHOTS: Final = 3

EVIDENCE_SHOTS_ALONE: Final = 2
EVIDENCE_SHOTS_SUPPORTED: Final = 1
EVIDENCE_DANGEROUS_ATTACKS: Final = 6
EVIDENCE_CORNERS: Final = 2

_SIGMOID_LIMIT: Final = 30.0


def sigmoid(x: float) -> float:
    """Logistic squash, saturating rather than overflowing at the extremes."""
    if x > _SIGMOID_LIMIT:
        return 1.0
    if x < -_SIGMOID_LIMIT:
        return 0.0
    return 1.0 / (1.0 + math.exp(-x))


# --------------------------------------------------------------------------
# Competition priors and baselines
# --------------------------------------------------------------------------

GLOBAL_AVERAGE_GOALS_PER_GAME: Final = 2.65

LEAGUE_GOALS_PER_GAME: Final[dict[str, float]] = {
    # Top 5 European
    "152": 2.85,  # England - Premier League
    "302": 2.55,  # Spain - La Liga
    "175": 3.17,  # Germany - Bundesliga
    "207": 2.60,  # Italy - Serie A
    "168": 2.75,  # France - Ligue 1
    # Other major European
    "244": 2.95,  # Netherlands - Eredivisie
    "266": 2.72,  # Portugal - Primeira Liga
    "322": 2.42,  # Turkey - Super Lig
    "344": 2.40,  # Greece - Super League
    "63": 2.63,  # Belgium - Pro League
    "387": 2.48,  # Switzerland - Super League
    "384": 2.82,  # Austria - Bundesliga
    "68": 2.50,  # Scotland - Premiership
    "256": 2.78,  # Poland - Ekstraklasa
    "99": 2.60,  # Czech Republic - First League
    "135": 2.55,  # Denmark - Superliga
    "340": 2.35,  # Croatia - HNL
    "365": 2.50,  # Serbia - Super Liga
    "283": 2.60,  # Romania - Liga 1
    "225": 2.65,  # Norway - Eliteserien
    "308": 2.75,  # Sweden - Allsvenskan
    "109": 2.45,  # Ukraine - Premier League
    "282": 2.90,  # Russia - Premier League
    # South America
    "73": 2.25,  # Brazil - Serie A
    "44": 2.35,  # Argentina - Primera Division
    "104": 2.40,  # Colombia - Primera A
    "82": 2.30,  # Chile - Primera Division
    "155": 2.50,  # Ecuador - Liga Pro
    "269": 2.45,  # Peru - Liga 1
    "328": 2.55,  # Uruguay - Primera Division
    "237": 2.50,  # Paraguay - Division Profesional
    # North and Central America
    "332": 2.50,  # USA - MLS
    "211": 2.55,  # Mexico - Liga MX
    # Asia
    "188": 2.65,  # Japan - J-League
    "276": 2.60,  # South Korea - K League 1
    "81": 2.70,  # China - Super League
    "351": 2.45,  # Saudi Arabia - Pro League
    "334": 2.45,  # UAE - Pro League
    "267": 2.50,  # Qatar - Stars League
    # Africa
    "342": 2.25,  # South Africa - Premier Soccer League
    "156": 2.30,  # Egypt - Premier League
    # Oceania
    "45": 3.10,  # Australia - A-League
    # Second divisions
    "153": 2.75,  # England - Championship
    "301": 2.45,  # Spain - La Liga 2
    "176": 3.05,  # Germany - 2. Bundesliga
    "208": 2.70,  # Italy - Serie B
    "169": 2.60,  # France - Ligue 2
    # International
    "28": 2.65,  # UEFA Champions League
    "29": 2.75,  # UEFA Europa League
    "547": 2.60,  # UEFA Conference League
    "4": 2.50,  # World Cup
    "1": 2.45,  # European Championship
    "19": 2.55,  # Copa America
    "183": 2.45,  # Copa Libertadores
    "184": 2.50,  # Copa Sudamericana
}

_MINUTES_PER_HALF_WINDOW_COUNT: Final = 18
"""A 90-minute match holds eighteen 5-minute windows."""


def league_prior(league_id: str | int | None) -> float:
    """Chance of one team scoring in any given 5-minute window.

    Derived from the competition's goals per game: halved to get one team's
    share, then spread across the eighteen windows in a match.
    """
    goals_per_game = LEAGUE_GOALS_PER_GAME.get(str(league_id), GLOBAL_AVERAGE_GOALS_PER_GAME)
    return (goals_per_game / 2.0) / _MINUTES_PER_HALF_WINDOW_COUNT


@dataclass(frozen=True, slots=True)
class EventBaseline:
    """Typical event counts for one team in a 5-minute window.

    Used as normalisation denominators, so that three shots means more in a
    cagey competition than in an open one.
    """

    shots_on_target: float = 0.5
    shots_off_target: float = 0.8
    corners: float = 0.3
    dangerous_attacks: float = 1.2


DEFAULT_BASELINE: Final = EventBaseline()

LEAGUE_BASELINES: Final[dict[str, EventBaseline]] = {
    # Premier League: more physical, fewer shots
    "152": EventBaseline(0.4, 0.7, 0.4, 1.0),
    # La Liga: more possession-based
    "302": EventBaseline(0.6, 0.9, 0.3, 1.4),
    # Bundesliga: high tempo
    "175": EventBaseline(0.5, 0.8, 0.4, 1.3),
    # Serie A: tactical, fewer chances
    "207": EventBaseline(0.4, 0.6, 0.3, 1.0),
    # Ligue 1
    "168": EventBaseline(0.5, 0.8, 0.3, 1.2),
}


def baseline_for(league_id: str | int | None) -> EventBaseline:
    """Event baselines for a competition, falling back to a global default.

    2.2 carried machinery to learn these from observed matches
    (`EnhancedLeagueBaselines.update_baseline`), but nothing ever called it, so
    the sample count stayed at zero and the hardcoded values were always used.
    Only the learning was dropped in this port; the values are unchanged.
    """
    return LEAGUE_BASELINES.get(str(league_id), DEFAULT_BASELINE)


_BASELINE_FLOOR: Final = 0.1
"""Smallest usable denominator, guarding against a zero baseline."""


# --------------------------------------------------------------------------
# Match context
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MatchContext:
    """How much a goal matters right now, from the clock and the scoreline."""

    minute: int
    score_difference: int
    is_tied: bool

    @property
    def is_late_game(self) -> bool:
        return self.minute >= LATE_GAME_MINUTE

    @property
    def is_early_game(self) -> bool:
        return self.minute <= EARLY_GAME_MINUTE

    @property
    def urgency(self) -> float:
        """Rises towards 1.0 late in a close match, near 0 early or in a rout."""
        time_factor = min(1.0, self.minute / 90.0)
        closeness = 1.0 / (1.0 + self.score_difference)
        return time_factor * closeness

    @classmethod
    def build(cls, minute: int, home_score: int, away_score: int) -> MatchContext:
        return cls(
            minute=minute,
            score_difference=abs(home_score - away_score),
            is_tied=home_score == away_score,
        )


# --------------------------------------------------------------------------
# Window events
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WindowEvents:
    """One team's attacking events over a window."""

    shots_on_target: int = 0
    shots_off_target: int = 0
    corners: int = 0
    dangerous_attacks: int = 0
    fouls: int = 0

    @property
    def attacking_total(self) -> int:
        """Events that represent attacking, which excludes fouls."""
        return self.shots_on_target + self.shots_off_target + self.corners + self.dangerous_attacks

    @property
    def total_including_fouls(self) -> int:
        """Attacking events plus fouls (diagnostic only; not used for patterns)."""
        return self.attacking_total + self.fouls


def _empty_or(snapshot: MinuteSnapshot | None, side: Side) -> tuple[int, ...]:
    if snapshot is None:
        return (0, 0, 0, 0, 0)
    stats = snapshot.team(side)
    return (
        stats.shots_on_target,
        stats.shots_off_target,
        stats.corners,
        stats.dangerous_attacks,
        stats.fouls,
    )


def window_events(
    timeline: MatchTimeline,
    side: Side,
    end_minute: int,
    span: int = WINDOW_MINUTES,
) -> WindowEvents:
    """Events for one team between `end_minute - span` and `end_minute`.

    Both ends are read by minute, accepting a snapshot up to five minutes stale
    if the exact one is missing. Unlike the other strategies, the window is not
    clamped at half time, so a window spanning the break measures across it.

    Returns zeros when fewer than two minutes have been recorded: 2.2 refused
    to work from a single snapshot, and had earlier fabricated synthetic data
    here before that was removed.
    """
    if len(timeline.minutes) < 2:
        return WindowEvents()

    start_minute = max(0, end_minute - span)
    end = timeline.snapshot_at_or_before(end_minute, lookback=SNAPSHOT_LOOKBACK)
    start = timeline.snapshot_at_or_before(start_minute, lookback=SNAPSHOT_LOOKBACK)

    end_counts = _empty_or(end, side)
    start_counts = _empty_or(start, side)

    deltas = [max(0, e - s) for e, s in zip(end_counts, start_counts, strict=True)]
    return WindowEvents(*deltas)


# --------------------------------------------------------------------------
# Attacking patterns
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AttackingPatterns:
    """Shapes in the last 15 minutes that suggest a goal is coming."""

    sustained_attack: bool = False
    corner_sequence: bool = False
    shot_burst: bool = False

    building_pressure: bool = False
    """Activity rising window over window.

    Detected but never scored, in 2.2 or here. Kept because it is cheap and
    the dashboard may want it; it contributes nothing to an alert.
    """


def detect_patterns(
    timeline: MatchTimeline,
    side: Side,
    current_minute: int,
) -> AttackingPatterns:
    """Look for sustained pressure across three consecutive 5-minute windows.

    Windows are ordered most recent first.

    ``sustained_attack`` uses ``attacking_total`` only (shots, corners,
    dangerous attacks). Fouls are excluded so broken play cannot clear the
    evidence gate on its own.
    """
    if len(timeline.minutes) < 3:
        return AttackingPatterns()

    windows = [
        window_events(timeline, side, current_minute - offset * WINDOW_MINUTES)
        for offset in range(3)
    ]

    recent_two = windows[:2]

    return AttackingPatterns(
        sustained_attack=all(w.attacking_total >= SUSTAINED_ATTACK_EVENTS for w in recent_two),
        corner_sequence=sum(w.corners for w in recent_two) >= CORNER_SEQUENCE_CORNERS,
        shot_burst=(windows[0].shots_on_target + windows[0].shots_off_target) >= SHOT_BURST_SHOTS,
        building_pressure=windows[0].shots_on_target > windows[1].shots_on_target,
    )


# --------------------------------------------------------------------------
# Threat score / League Bar
# --------------------------------------------------------------------------


class LeagueBar(StrEnum):
    """Where live scoring chance sits relative to the league prior.

    Derived from lift ``L = P / P0``: below the bar, on it (normal), or above.
    """

    BELOW = "below"
    NORMAL = "normal"
    ABOVE = "above"


def league_bar_for(lift: float) -> LeagueBar:
    """Map lift onto below / normal / above the league bar."""
    if lift > LEAGUE_BAR_NORMAL_HIGH:
        return LeagueBar.ABOVE
    if lift < LEAGUE_BAR_NORMAL_LOW:
        return LeagueBar.BELOW
    return LeagueBar.NORMAL


def league_bar_score(lift: float) -> float:
    """Signed League Bar reading from lift ``L = P / P0``.

    ``0`` means on the league prior. Positive is above the bar, negative below.
    Clamped to ``[-10, +10]``: each +1 of lift above 1.0 adds +10 points until
    the cap (so ``L = 2`` → ``+10``, ``L = 0`` → ``-10``).
    """
    raw = BAR_SCORE_MAX * (float(lift) - 1.0)
    return round(max(-BAR_SCORE_MAX, min(BAR_SCORE_MAX, raw)), 1)


class Tier(StrEnum):
    """Alert severity from how far the bar score clears the threshold."""

    YELLOW = "Y"
    ORANGE = "O"
    RED = "R"

    @property
    def rank(self) -> int:
        return {Tier.YELLOW: 1, Tier.ORANGE: 2, Tier.RED: 3}[self]


def tier_for(threat: float, threshold: float) -> Tier | None:
    if threat >= threshold + TIER_RED_MARGIN:
        return Tier.RED
    if threat >= threshold + TIER_ORANGE_MARGIN:
        return Tier.ORANGE
    if threat >= threshold:
        return Tier.YELLOW
    return None


def threat_score(
    probability: float,
    lift: float,
    pressure_score: float,
    context: MatchContext,
    patterns: AttackingPatterns,
    weights: WeightSet,
) -> float:
    """Legacy 2.2 composite (kept for differentials). Live path uses ``league_bar_score``."""
    p = min(probability / PROBABILITY_CEILING, 1.0)
    l = min(lift / LIFT_CEILING, 1.0)  # noqa: E741 - matches the published formula
    s = pressure_score / 100.0

    weight_p = weights.get(STRATEGY_KEY, "threat_w_p")
    weight_ps = weights.get(STRATEGY_KEY, "threat_w_ps")
    weight_l = weights.get(STRATEGY_KEY, "threat_w_l")

    if context.is_late_game:
        weight_p += LATE_GAME_PROBABILITY_BONUS
    if context.is_tied:
        weight_p += TIED_GAME_PROBABILITY_BONUS

    bonus = 0.0
    if patterns.sustained_attack:
        bonus += weights.get(STRATEGY_KEY, "pattern_sustained")
    if patterns.corner_sequence:
        bonus += weights.get(STRATEGY_KEY, "pattern_corner_seq")
    if patterns.shot_burst:
        bonus += weights.get(STRATEGY_KEY, "pattern_shot_burst")

    composite = (weight_p * p + weight_ps * s + weight_l * l) * (1 + bonus)
    composite *= 1 + context.urgency * THREAT_URGENCY_MULTIPLIER

    score = round(composite * 20.0, 1)

    if score <= 0 and (patterns.sustained_attack or context.urgency > 0.5):
        return MINIMUM_LIVE_THREAT
    return score


# --------------------------------------------------------------------------
# Per-team evaluation
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TeamThreat:
    """The full chain of intermediate values for one team."""

    events: WindowEvents
    patterns: AttackingPatterns
    pressure_index: float
    pressure_score: float
    confidence: float
    prior: float
    probability: float
    lift: float
    league_bar: LeagueBar
    threat: float
    tier: Tier | None

    @property
    def has_evidence(self) -> bool:
        """Whether the window holds enough attacking evidence to alert on.

        Intended as a gate against alerting on a score built from dangerous
        attacks alone, which is the noisiest thing the feed carries. The first
        two clauses require a shot on target (alone or with support).

        The third clause allows a sustained attack pattern on its own.
        That pattern counts attacking events only (not fouls). Dangerous
        attacks alone can still form a sustained attack when volume is high
        across consecutive windows — see the dedicated tests.
        """
        return (
            self.events.shots_on_target >= EVIDENCE_SHOTS_ALONE
            or (
                self.events.shots_on_target >= EVIDENCE_SHOTS_SUPPORTED
                and (
                    self.events.dangerous_attacks >= EVIDENCE_DANGEROUS_ATTACKS
                    or self.events.corners >= EVIDENCE_CORNERS
                )
            )
            or self.patterns.sustained_attack
        )

    @property
    def qualifies(self) -> bool:
        return self.tier is not None and self.has_evidence


@dataclass(frozen=True, slots=True)
class DeltaGoalResult:
    """Both teams' threat assessments, and which one alerts."""

    home: TeamThreat
    away: TeamThreat
    threshold: float
    is_early_match: bool = False

    def team(self, side: Side) -> TeamThreat:
        return self.home if side is Side.HOME else self.away

    @property
    def triggering_team(self) -> Side | None:
        """The qualifying team with the highest tier, then the highest threat.

        Ties go to the home team, which is checked first.
        """
        best: Side | None = None
        best_rank: tuple[int, float] | None = None

        for side in (Side.HOME, Side.AWAY):
            team = self.team(side)
            if team.tier is None or not team.has_evidence:
                continue
            rank = (team.tier.rank, team.threat)
            if best_rank is None or rank > best_rank:
                best, best_rank = side, rank

        return best

    @property
    def trigger_value(self) -> float:
        """Signed League Bar score for the triggering team (0 if none)."""
        side = self.triggering_team
        return self.team(side).threat if side else 0.0

    @property
    def strongest_team(self) -> Side:
        """Whichever team has the higher threat, qualifying or not.

        For the dashboard, which shows a reading even when nothing alerts.
        """
        return max(Side, key=lambda side: self.team(side).threat)


def _odds_prior(team_odds: float, opponent_odds: float) -> float:
    """A prior from the bookmakers' view rather than the competition average.

    Uses the gap between the two implied probabilities, so a heavy favourite
    starts from a higher chance of scoring.
    """
    gap = math.log(max(1e-9, 1.0 / team_odds)) - math.log(max(1e-9, 1.0 / opponent_odds))
    return sigmoid(ODDS_PRIOR_INTERCEPT + ODDS_PRIOR_SLOPE * gap)


def _event_score(events: WindowEvents, baseline: EventBaseline, weights: WeightSet) -> float:
    """Weighted, competition-normalised attacking score.

    Fouls and possession are excluded. 2.2 declared a ``weight_possession``
    admin coefficient that never entered this sum; 3.0 drops that dead control
    from the registry rather than inventing a use for it.
    """

    def normalised(count: int, mu: float) -> float:
        return count / max(mu, _BASELINE_FLOOR)

    return (
        weights.get(STRATEGY_KEY, "weight_sot")
        * normalised(events.shots_on_target, baseline.shots_on_target)
        + weights.get(STRATEGY_KEY, "weight_sofft")
        * normalised(events.shots_off_target, baseline.shots_off_target)
        + weights.get(STRATEGY_KEY, "weight_corners") * normalised(events.corners, baseline.corners)
        + weights.get(STRATEGY_KEY, "weight_da")
        * normalised(events.dangerous_attacks, baseline.dangerous_attacks)
    )


def _evaluate_team(
    timeline: MatchTimeline,
    side: Side,
    context: MatchContext,
    baseline: EventBaseline,
    prior: float,
    threshold: float,
    weights: WeightSet,
) -> TeamThreat:
    minute = context.minute

    events = window_events(timeline, side, minute)
    previous = window_events(timeline, side, max(0, minute - WINDOW_MINUTES))
    patterns = detect_patterns(timeline, side, minute)

    current_pressure = math.log(1.0 + _event_score(events, baseline, weights))
    previous_pressure = math.log(1.0 + _event_score(previous, baseline, weights))
    pressure_index = PRESSURE_BLEND * current_pressure + (1.0 - PRESSURE_BLEND) * previous_pressure
    pressure_score = 100.0 * sigmoid(PRESSURE_STEEPNESS * pressure_index)

    # Confidence in the live signal, from how much has happened over a longer
    # window. Near 0 in a quiet match, so the prior dominates.
    longer = window_events(timeline, side, minute, CONFIDENCE_WINDOW_MINUTES)
    confidence = 1.0 - math.exp(-(longer.attacking_total / CONFIDENCE_SCALE))

    pressure_probability = sigmoid(
        PRESSURE_TO_GOAL_INTERCEPT + PRESSURE_TO_GOAL_SLOPE * pressure_index
    )
    blended = (1.0 - confidence) * prior + confidence * pressure_probability
    probability = blended * (1 + context.urgency * weights.get(STRATEGY_KEY, "time_urgency_mult"))

    lift = probability / max(prior, 1e-6)
    threat = league_bar_score(lift)

    return TeamThreat(
        events=events,
        patterns=patterns,
        pressure_index=pressure_index,
        pressure_score=pressure_score,
        confidence=confidence,
        prior=prior,
        probability=probability,
        lift=lift,
        league_bar=league_bar_for(lift),
        threat=threat,
        tier=tier_for(threat, threshold),
    )


def evaluate(
    timeline: MatchTimeline,
    *,
    home_score: int = 0,
    away_score: int = 0,
    league_id: str | int | None = None,
    home_odds: float | None = None,
    away_odds: float | None = None,
    threshold: float = DEFAULT_ALERT_THRESHOLD,
    weights: WeightSet | None = None,
) -> DeltaGoalResult:
    """Threat assessment for both teams.

    Always returns a result. Before `MINIMUM_MINUTE` the result is zeroed and
    flagged `is_early_match`, matching 2.2, which returned a non-triggering
    payload rather than nothing so the live dashboard had something to show.
    Callers should alert on `triggering_team`, not on getting a result.

    Pass `home_odds` and `away_odds` to derive the prior from the bookmakers'
    view instead of the competition average.
    """
    w = weights or WeightSet.defaults()
    context = MatchContext.build(timeline.current_minute, home_score, away_score)

    if timeline.current_minute < MINIMUM_MINUTE:
        empty = TeamThreat(
            events=WindowEvents(),
            patterns=AttackingPatterns(),
            pressure_index=0.0,
            pressure_score=0.0,
            confidence=0.0,
            prior=league_prior(league_id),
            probability=0.0,
            lift=1.0,
            league_bar=LeagueBar.NORMAL,
            threat=0.0,
            tier=None,
        )
        return DeltaGoalResult(home=empty, away=empty, threshold=threshold, is_early_match=True)

    baseline = baseline_for(league_id)

    def prior_for(side: Side) -> float:
        if home_odds and away_odds:
            return (
                _odds_prior(home_odds, away_odds)
                if side is Side.HOME
                else _odds_prior(away_odds, home_odds)
            )
        return league_prior(league_id)

    return DeltaGoalResult(
        home=_evaluate_team(
            timeline, Side.HOME, context, baseline, prior_for(Side.HOME), threshold, w
        ),
        away=_evaluate_team(
            timeline, Side.AWAY, context, baseline, prior_for(Side.AWAY), threshold, w
        ),
        threshold=threshold,
    )
