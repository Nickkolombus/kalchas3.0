"""Rule of Three (Strategy 1) -- teams creating more than the scoreboard shows.

Roughly one goal is expected per three shots on target. A team well above that
rate without the goals to match is overdue, and this measures by how much.

    quality  = quality_base + quality_slope × SOT/(SOT + SOFFT)
    UG_base  = SOT × sot_weight × quality + SOFFT × sofft_weight − goals
    UG       = UG_base × (1 + possession_adj) × odds × game_state × time

Ported from Kalchas 2.2 `utils/rule_of_three.py` and
`strategies/strategy_001_rule_of_three/formula.py`. The arithmetic is
unchanged; four things around it are not, each noted at the point it applies:
the `league_name` parameter (never read), the `return_points` flag (changed
the return type), two unreachable branches in the game-state modifier, and the
mutation of the caller's dictionary to return detail.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from kalchas_core.match import Side, TeamStats
from kalchas_core.weights import WeightSet

STRATEGY_KEY = "rule_of_three"

# The "rule of three" itself: shots off target are discounted six-to-one
# against shots on target, and three effective shots on target are worth one
# expected goal.
SHOTS_OFF_TARGET_DISCOUNT = 6.0
SHOTS_PER_EXPECTED_GOAL = 3.0

# Minute assumed when the caller does not supply one. Carried over from 2.2,
# where the game-state modifier defaulted to mid-match while the time
# multiplier defaulted to neutral instead -- see `evaluate`.
ASSUMED_MINUTE = 45


@dataclass(frozen=True, slots=True)
class TeamShotProfile:
    """One team's shooting and context for a Rule of Three evaluation."""

    shots_on_target: int = 0
    shots_off_target: int = 0
    goals: int = 0
    possession: float | None = None
    kickoff_odds: float | None = None

    @classmethod
    def from_stats(
        cls,
        stats: TeamStats,
        *,
        goals: int = 0,
        kickoff_odds: float | None = None,
    ) -> TeamShotProfile:
        """Build from a timeline snapshot's stat line."""
        return cls(
            shots_on_target=stats.shots_on_target,
            shots_off_target=stats.shots_off_target,
            goals=goals,
            possession=stats.possession or None,
            kickoff_odds=kickoff_odds,
        )

    @property
    def total_shots(self) -> int:
        return self.shots_on_target + self.shots_off_target

    @property
    def effective_shots_on_target(self) -> float:
        """Shots on target plus a discounted contribution from those off it."""
        return self.shots_on_target + self.shots_off_target / SHOTS_OFF_TARGET_DISCOUNT

    @property
    def expected_goals(self) -> float:
        """What the rule of three says this team's shooting should have yielded."""
        return self.effective_shots_on_target / SHOTS_PER_EXPECTED_GOAL


@dataclass(frozen=True, slots=True)
class TeamUnrealised:
    """One team's unrealised-goal reading, with the factors that produced it."""

    unrealised_goals: float
    effective_shots_on_target: float
    expected_goals: float
    goals: int
    shot_quality: float
    possession_adjustment: float
    odds_factor: float
    game_state_modifier: float
    time_multiplier: float


@dataclass(frozen=True, slots=True)
class RuleOfThreeResult:
    """Both teams' readings for one match."""

    home: TeamUnrealised
    away: TeamUnrealised
    minute: int

    def team(self, side: Side) -> TeamUnrealised:
        return self.home if side is Side.HOME else self.away

    @property
    def trigger_value(self) -> float:
        """The value the strategy fires on: the higher of the two teams."""
        return max(self.home.unrealised_goals, self.away.unrealised_goals)

    @property
    def total(self) -> float:
        return self.home.unrealised_goals + self.away.unrealised_goals

    @property
    def leader(self) -> Side | None:
        """The team more overdue to score, or None if they are level."""
        if self.home.unrealised_goals == self.away.unrealised_goals:
            return None
        return Side.HOME if self.home.unrealised_goals > self.away.unrealised_goals else Side.AWAY


def shot_quality_factor(shots_on_target: int, shots_off_target: int, weights: WeightSet) -> float:
    """Shot accuracy as a proxy for chance quality.

    A team hitting the target with most of its shots is getting better looks
    than one spraying them wide, so its shots on target are worth more.
    """
    total = shots_on_target + shots_off_target
    if total == 0:
        return 1.0

    accuracy = shots_on_target / total
    base = weights.get(STRATEGY_KEY, "quality_base")
    slope = weights.get(STRATEGY_KEY, "quality_slope")
    return base + slope * accuracy


def game_state_modifier(team_goals: int, opponent_goals: int, minute: int) -> float:
    """Scoreline psychology: leaders ease off, chasers push, settled games flatten.

    2.2 ended each branch of this function with an unreachable `return`
    (`0.70` when leading, `1.0` when trailing) -- a lead is either exactly one
    goal or two-or-more, with nothing in between. Both are dropped; the
    reachable arithmetic is untouched.
    """
    difference = team_goals - opponent_goals
    if difference == 0:
        return 1.0

    total_goals = team_goals + opponent_goals
    time_factor = min(1.0, minute / 90.0) if minute else 0.0

    if difference > 0:
        if difference == 1:
            return 0.90
        # A two-goal lead in a high-scoring game (3-1) reads as settled, and
        # discounts harder than the same lead at 2-0.
        if difference == 2 and total_goals >= 4:
            return 0.70 - 0.05 * time_factor
        return 0.75 - 0.05 * time_factor

    if difference == -1:
        return 1.05
    if difference == -2 and total_goals >= 4:
        return 0.80 + 0.05 * (1.0 - time_factor)
    # Two down early still has hope; two down late does not.
    return 0.95 - 0.10 * time_factor


def time_of_match_multiplier(minute: int | None, weights: WeightSet) -> float:
    """Goals cluster late, so late pressure is worth more."""
    if not minute or minute <= 0:
        return 1.0
    if minute <= 30:
        return weights.get(STRATEGY_KEY, "time_mult_0_30")
    if minute <= 60:
        return weights.get(STRATEGY_KEY, "time_mult_31_60")
    if minute <= 75:
        return weights.get(STRATEGY_KEY, "time_mult_61_75")
    return weights.get(STRATEGY_KEY, "time_mult_75_plus")


def possession_adjustment(possession: float | None, weights: WeightSet) -> float:
    """Penalty for teams seeing little of the ball. No bonus above 50%."""
    if possession is None:
        return 0.0
    try:
        share = float(possession)
    except (TypeError, ValueError):
        return 0.0
    if share >= 50:
        return 0.0

    penalty = weights.get(STRATEGY_KEY, "possession_penalty")
    return penalty * (50 - share) / 50


def odds_difficulty_factor(own_odds: float | None, opponent_odds: float | None) -> float:
    """Weight by pre-match expectation, favouring the stronger side.

    Driven by `opponent_odds / own_odds`, so a short-priced favourite is
    boosted (up to 1.6x) and a long-priced underdog discounted (down to 0.5x).
    That direction is deliberate for an overdue-to-score signal: a favourite
    dominating without converting is genuinely behind where it should be,
    whereas an underdog creating a few chances is closer to par.

    Scaled on the log of the ratio, so the curve flattens at the extremes
    instead of rewarding a 20-to-1 mismatch twentyfold. Neutral when either
    price is missing.
    """
    if not own_odds or not opponent_odds:
        return 1.0
    try:
        ratio = max(0.2, min(5.0, float(opponent_odds) / float(own_odds)))
    except (TypeError, ValueError, ZeroDivisionError):
        return 1.0

    log_ratio = math.log(ratio)

    if ratio >= 2.0:
        return 1.4 + 0.1 * min(2.0, log_ratio - math.log(2.0))
    if ratio >= 1.3:
        span = math.log(2.0) - math.log(1.3)
        return 1.15 + 0.25 * (log_ratio - math.log(1.3)) / span
    if ratio >= 0.8:
        span = math.log(1.3) - math.log(0.8)
        return 0.9 + 0.25 * (log_ratio - math.log(0.8)) / span

    span = math.log(0.8) - math.log(0.5)
    return max(0.5, 0.7 - 0.2 * (math.log(0.8) - log_ratio) / span)


def _evaluate_team(
    team: TeamShotProfile,
    opponent: TeamShotProfile,
    *,
    minute: int | None,
    weights: WeightSet,
) -> TeamUnrealised:
    quality = shot_quality_factor(team.shots_on_target, team.shots_off_target, weights)
    sot_weight = weights.get(STRATEGY_KEY, "sot_weight")
    sofft_weight = weights.get(STRATEGY_KEY, "sofft_weight")

    base = (
        team.shots_on_target * sot_weight * quality
        + team.shots_off_target * sofft_weight
        - team.goals
    )

    possession_adj = possession_adjustment(team.possession, weights)
    odds = odds_difficulty_factor(team.kickoff_odds, opponent.kickoff_odds)
    # 2.2 assumed mid-match here when the minute was unknown, but neutral in
    # the time multiplier below. Preserved: changing it would move every
    # historical value computed without a minute.
    state = game_state_modifier(team.goals, opponent.goals, minute or ASSUMED_MINUTE)
    time_mult = time_of_match_multiplier(minute, weights)

    return TeamUnrealised(
        unrealised_goals=base * (1 + possession_adj) * odds * state * time_mult,
        effective_shots_on_target=team.effective_shots_on_target,
        expected_goals=team.expected_goals,
        goals=team.goals,
        shot_quality=quality,
        possession_adjustment=possession_adj,
        odds_factor=odds,
        game_state_modifier=state,
        time_multiplier=time_mult,
    )


def evaluate(
    home: TeamShotProfile,
    away: TeamShotProfile,
    *,
    minute: int | None = None,
    weights: WeightSet | None = None,
) -> RuleOfThreeResult:
    """Unrealised goal potential for both teams.

    2.2's entry point was `async def calculate(match_data)` despite performing
    no IO, and returned only the larger of the two values -- the per-team
    detail was delivered by writing a `rule_of_3_results` key into the
    caller's dictionary. This returns everything instead, and mutates nothing.

    2.2 also accepted a `league_name` argument here. It was never read: the
    intended per-league possession baseline was never implemented, though
    callers populated it from real league data. It is dropped rather than
    carried across as a parameter that does nothing.
    """
    w = weights or WeightSet.defaults()

    return RuleOfThreeResult(
        home=_evaluate_team(home, away, minute=minute, weights=w),
        away=_evaluate_team(away, home, minute=minute, weights=w),
        minute=minute if minute is not None else ASSUMED_MINUTE,
    )


def legacy_points(result: RuleOfThreeResult) -> int:
    """The 0-25 banded score the goal detector consumes.

    2.2 produced this from `unrealised_goals(..., return_points=True)`, a flag
    that changed the function's return type from a 2-tuple to a 3-tuple, so
    every caller unpacked defensively by checking the tuple's length. Exactly
    one caller ever set it. It is a separate function here.
    """
    total = result.total

    if total <= 0:
        return 0
    if total <= 1:
        return 5
    if total <= 3:
        return 10 + int((total - 2) * 5)
    return min(25, 16 + int((total - 4) * 2))
