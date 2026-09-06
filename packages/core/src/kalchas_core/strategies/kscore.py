"""K-Score (Strategy 7) -- four consultants, one number.

Unlike every other strategy, K-Score does not read the match timeline. It
takes the *outputs* of other strategies as inputs and blends them into a
0-100 score per team:

    momentum  ← Delta 5min pressure
    pressure  ← Pressure Index
    rule3     ← Rule of Three unrealised goals
    omega     ← Omega (acceleration + baseline + level) — same TeamOmega SSOT
    focus ΦI  ← NPEI, as a multiplier rather than a fifth vote

Each consultant produces a vote in [0, 1]. The votes are levered around 0.5,
weighted by trust coefficients, shifted by a bias and optional match-context
terms, squashed through a sigmoid, and scaled by ΦI.

Ported from `utils/kscore_formula.py`. In 2.2 the weights lived in a separate
`kscore_settings` Postgres table (not `strategy_weights`); here they are a
normal `WeightSet` strategy key. Removed: the database resolver, the
`_formula_cache` mutation, and the orchestrator that assembled signals from
whatever earlier slots had written onto the match dict.

3.0 SSOT: Omega's consultant vote always uses the full ``TeamOmega`` reading
(acceleration, baseline slope, level). The 2.2 alert path that forwarded
acceleration alone is retired — incomplete Omega inputs vote neutral (0.5)
instead of applying the truncated drag. The unused 2.2 ``horizon`` admin
control is not carried forward.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Final

from kalchas_core.match import Side
from kalchas_core.strategies.omega import TeamOmega
from kalchas_core.weights import WeightSet

STRATEGY_KEY = "kscore"

DEFAULT_THRESHOLD: Final = 60.0

# Hardcoded inside the Omega vote -- scaled for 3.0's window-normalised
# accel / baseline (2.2 used 8.0 and 2.5 on the unnormalised slopes).
_OMEGA_ACCEL_SCALE: Final = 0.8
_OMEGA_BASELINE_SCALE: Final = 0.4
_OMEGA_LEVEL_DIVISOR: Final = 55.0
_OMEGA_LEVEL_FLOOR: Final = 0.2
_OMEGA_BASELINE_MIX: Final = (0.45, 0.55)

_RULE3_OFFSET: Final = 0.3
_RULE3_SPAN: Final = 1.3
_RED_CARD_CAP: Final = 2
_TRAILING_DEFICIT_CAP: Final = 2
_FULL_TIME_MINUTE: Final = 90.0


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def sigmoid(x: float) -> float:
    """Numerically stable logistic."""
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MatchContext:
    """Optional match-state adjustments to the logit.

    Every field is optional. Missing context contributes nothing, matching
    2.2's `context_logit_delta` when the match dict lacked the fields.
    """

    minute: int = 0
    home_score: int = 0
    away_score: int = 0
    home_red_cards: int = 0
    away_red_cards: int = 0
    home_kickoff_odds: float | None = None
    away_kickoff_odds: float | None = None

    def red_cards(self, side: Side) -> int:
        return self.home_red_cards if side is Side.HOME else self.away_red_cards

    def score(self, side: Side) -> int:
        return self.home_score if side is Side.HOME else self.away_score

    def kickoff_odds(self, side: Side) -> float | None:
        return self.home_kickoff_odds if side is Side.HOME else self.away_kickoff_odds


@dataclass(frozen=True, slots=True)
class TeamSignals:
    """One team's consultant inputs.

    Omega SSOT: pass acceleration, baseline, and level together from
    ``TeamOmega``. Use ``TeamSignals.from_omega`` so the three fields stay
    aligned. Incomplete Omega (acceleration without baseline/level) votes
    neutral rather than applying the retired 2.2 accel-only drag.
    """

    delta_5min: float = 0.0
    pressure_index: float = 0.0
    rule_of_three: float = 0.0
    npei: float = 0.0
    omega_acceleration: float | None = None
    omega_baseline: float | None = None
    omega_level: float | None = None
    omega_theta: float = 0.0
    omega_alpha: float = 0.0

    @classmethod
    def from_omega(cls, omega: TeamOmega | None, **kwargs: Any) -> TeamSignals:
        """Build signals with Omega fields copied from a ``TeamOmega`` reading."""
        if omega is None:
            return cls(**kwargs)
        return cls(
            omega_acceleration=float(omega.acceleration),
            omega_baseline=float(omega.baseline_slope),
            omega_level=float(omega.level),
            omega_theta=float(omega.theta),
            omega_alpha=float(omega.alpha),
            **kwargs,
        )


# --------------------------------------------------------------------------
# Consultant votes
# --------------------------------------------------------------------------


def omega_vote(
    *,
    acceleration: float | None = None,
    baseline: float | None = None,
    level: float | None = None,
    theta: float = 0.0,
    alpha: float = 0.0,
) -> float:
    """Omega's consultant vote in [0, 1].

    Full linear form (SSOT — requires acceleration, baseline, and level):

        σ(accel/0.8) · (0.45 + 0.55 · σ(baseline/0.4)) · clamp(level/55, 0.2, 1)

    Incomplete Omega (acceleration set but baseline or level missing) returns
    neutral 0.5 so a truncated feed cannot drag the score. Legacy angle form
    when acceleration is absent: sine product of the display angles.
    """
    if acceleration is not None:
        if baseline is None or level is None:
            return 0.5
        accel = max(0.0, float(acceleration))
        base = max(0.0, float(baseline))
        lvl = float(level)
        return _clamp(
            sigmoid(accel / _OMEGA_ACCEL_SCALE)
            * (
                _OMEGA_BASELINE_MIX[0]
                + _OMEGA_BASELINE_MIX[1] * sigmoid(base / _OMEGA_BASELINE_SCALE)
            )
            * _clamp(lvl / _OMEGA_LEVEL_DIVISOR, _OMEGA_LEVEL_FLOOR, 1.0),
            0.0,
            1.0,
        )

    return _clamp(
        0.5 + 0.5 * math.sin(math.radians(alpha)) * math.sin(math.radians(theta)),
        0.0,
        1.0,
    )


def consultant_votes(signals: TeamSignals, weights: WeightSet) -> dict[str, float]:
    """The four consultant votes in [0, 1]."""
    scale = weights.get(STRATEGY_KEY, "momentum_scale")
    if scale <= 0:
        scale = 8.0

    return {
        "momentum": sigmoid(signals.delta_5min / scale),
        "pressure": _clamp(signals.pressure_index / 100.0, 0.0, 1.0),
        "rule3": _clamp((signals.rule_of_three + _RULE3_OFFSET) / _RULE3_SPAN, 0.0, 1.0),
        "omega": omega_vote(
            acceleration=signals.omega_acceleration,
            baseline=signals.omega_baseline,
            level=signals.omega_level,
            theta=signals.omega_theta,
            alpha=signals.omega_alpha,
        ),
    }


def focus(npei: float, weights: WeightSet) -> float:
    """ΦI scoring-dedication multiplier from NPEI."""
    floor = _clamp(weights.get(STRATEGY_KEY, "phi_floor"), 0.0, 1.0)
    return floor + (1.0 - floor) * _clamp(npei / 100.0, 0.0, 1.0)


def context_logit_delta(
    side: Side,
    context: MatchContext | None,
    weights: WeightSet,
) -> float:
    """Additive logit shift from match context. Zero when context is absent."""
    if context is None:
        return 0.0

    delta = 0.0

    red_weight = weights.get(STRATEGY_KEY, "ctx_red_card")
    if red_weight > 0:
        cards = context.red_cards(side)
        if cards > 0:
            delta -= red_weight * min(cards, _RED_CARD_CAP)

    trail_weight = weights.get(STRATEGY_KEY, "ctx_trailing")
    late_minute = int(weights.get(STRATEGY_KEY, "ctx_late_minute"))
    if trail_weight > 0 and context.minute >= late_minute:
        mine = context.score(side)
        theirs = context.score(side.opponent)
        deficit = theirs - mine
        if deficit > 0:
            ramp = min(
                1.0,
                max(
                    0.0,
                    (context.minute - late_minute) / max(1.0, _FULL_TIME_MINUTE - late_minute),
                ),
            )
            delta += trail_weight * min(deficit, _TRAILING_DEFICIT_CAP) * ramp

    ko_weight = weights.get(STRATEGY_KEY, "ctx_ko_prior")
    home_odds = context.home_kickoff_odds
    away_odds = context.away_kickoff_odds
    if ko_weight > 0 and home_odds and away_odds:
        try:
            implied_home = 1.0 / float(home_odds)
            implied_away = 1.0 / float(away_odds)
            total = implied_home + implied_away
            if total > 0:
                team_share = implied_home / total if side is Side.HOME else implied_away / total
                delta += ko_weight * (team_share - 0.5) * 2.0
        except (TypeError, ValueError, ZeroDivisionError):
            pass

    return delta


# --------------------------------------------------------------------------
# Per-team and match evaluation
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TeamKScore:
    """One team's K-Score and the chain that produced it."""

    score: int
    probability: float
    probability_raw: float
    focus: float
    logit: float
    votes: dict[str, float]

    @property
    def value(self) -> int:
        """Alias used by the 2.2 return shape."""
        return self.score


@dataclass(frozen=True, slots=True)
class KScoreResult:
    """Both teams' scores and the match-level OR of their probabilities."""

    home: TeamKScore
    away: TeamKScore
    match_score: int
    threshold: float

    def team(self, side: Side) -> TeamKScore:
        return self.home if side is Side.HOME else self.away

    @property
    def triggering_team(self) -> Side | None:
        """The team at or above the threshold with the higher score.

        Ties go to the home team. When neither team clears the threshold,
        nothing triggers -- even if the match-level OR score is high. 2.2's
        slot 7 returned a non-triggering payload with `value=match_score` in
        that case; `strategy_manager` could still treat the match score as a
        fireable signal, which is an orchestration concern outside this module.
        """
        home_ok = self.home.score >= self.threshold
        away_ok = self.away.score >= self.threshold
        if not home_ok and not away_ok:
            return None
        if home_ok and (not away_ok or self.home.score >= self.away.score):
            return Side.HOME
        return Side.AWAY

    @property
    def trigger_value(self) -> float:
        side = self.triggering_team
        return float(self.team(side).score) if side else 0.0


def _lever(vote: float) -> float:
    """Map a [0,1] vote onto [-1, +1] around neutrality."""
    return (vote - 0.5) * 2.0


def evaluate_team(
    signals: TeamSignals,
    *,
    side: Side | None = None,
    context: MatchContext | None = None,
    weights: WeightSet | None = None,
) -> TeamKScore:
    """K-Score components for one team."""
    w = weights or WeightSet.defaults()
    votes = consultant_votes(signals, w)

    logit = (
        w.get(STRATEGY_KEY, "bias")
        + w.get(STRATEGY_KEY, "trust_momentum") * _lever(votes["momentum"])
        + w.get(STRATEGY_KEY, "trust_pressure") * _lever(votes["pressure"])
        + w.get(STRATEGY_KEY, "trust_rule3") * _lever(votes["rule3"])
        + w.get(STRATEGY_KEY, "trust_omega") * _lever(votes["omega"])
    )
    if side is not None:
        logit += context_logit_delta(side, context, w)

    probability_raw = sigmoid(logit)
    focus_value = focus(signals.npei, w)
    probability = _clamp(probability_raw * focus_value, 0.0, 1.0)
    score = max(0, min(100, round(100.0 * probability)))

    return TeamKScore(
        score=score,
        probability=probability,
        probability_raw=probability_raw,
        focus=focus_value,
        logit=logit,
        votes=votes,
    )


def evaluate(
    home: TeamSignals,
    away: TeamSignals,
    *,
    context: MatchContext | None = None,
    threshold: float = DEFAULT_THRESHOLD,
    weights: WeightSet | None = None,
) -> KScoreResult:
    """K-Score for both teams and the match-level combined score.

    The match score is `1 - (1 - p_home) * (1 - p_away)` -- the probability
    that at least one side's signal fires -- scaled to 0-100. It is reported
    but does not decide `triggering_team`.
    """
    w = weights or WeightSet.defaults()
    home_result = evaluate_team(home, side=Side.HOME, context=context, weights=w)
    away_result = evaluate_team(away, side=Side.AWAY, context=context, weights=w)

    match_probability = 1.0 - (1.0 - home_result.probability) * (1.0 - away_result.probability)
    match_score = max(0, min(100, round(100.0 * match_probability)))

    return KScoreResult(
        home=home_result,
        away=away_result,
        match_score=match_score,
        threshold=threshold,
    )
