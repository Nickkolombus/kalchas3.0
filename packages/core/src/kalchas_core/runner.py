"""Strategy runner — evaluate active slots against a timeline.

Returns alert candidates; does not check cooldown or deliver messages.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kalchas_core.match import MatchTimeline, Side
from kalchas_core.npei import compute_npei
from kalchas_core.strategies import (
    delta_5min,
    delta_goal,
    kscore,
    omega,
    pressure_index,
    rule_of_three,
)
from kalchas_core.strategies.kscore import TeamSignals
from kalchas_core.strategies.rule_of_three import TeamShotProfile
from kalchas_core.weights import WeightSet

# Slot → default fire threshold (2.2 triggers.json defaults where known).
DEFAULT_THRESHOLDS: dict[int, float] = {
    1: 1.0,  # Rule of Three unrealised goals
    2: 70.0,  # Pressure Index
    3: 8.0,  # Delta Goal threat
    4: 3.0,  # Delta 5min
    6: 0.0,  # Omega uses its own gate; threshold unused
    7: 60.0,  # K-Score
}


@dataclass(frozen=True, slots=True)
class AlertCandidate:
    strategy_slot: int
    strategy_key: str
    side: Side | None
    value: float
    detail: dict[str, Any]


def _shot_profile(timeline: MatchTimeline, side: Side) -> TeamShotProfile:
    snap = timeline.current
    if snap is None:
        return TeamShotProfile()
    team = snap.team(side)
    return TeamShotProfile.from_stats(team, goals=int(team.goals or 0))


def evaluate_match(
    timeline: MatchTimeline,
    *,
    home_goals: int = 0,
    away_goals: int = 0,
    weights: WeightSet | None = None,
    thresholds: dict[int, float] | None = None,
    slots: tuple[int, ...] = (1, 2, 3, 4, 6, 7),
) -> list[AlertCandidate]:
    """Run selected strategy slots; return candidates that cross their threshold."""
    w = weights or WeightSet.defaults()
    th = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    minute = timeline.current_minute
    candidates: list[AlertCandidate] = []

    npei_snap = compute_npei(timeline, weights=w) if 7 in slots else None
    pi = None
    d5 = None
    om = None
    ro3 = None

    if 1 in slots:
        ro3 = rule_of_three.evaluate(
            _shot_profile(timeline, Side.HOME),
            _shot_profile(timeline, Side.AWAY),
            minute=minute,
            weights=w,
        )
        for side in (Side.HOME, Side.AWAY):
            team = ro3.team(side)
            if team.unrealised_goals >= th[1]:
                candidates.append(
                    AlertCandidate(
                        1,
                        "rule_of_three",
                        side,
                        float(team.unrealised_goals),
                        {"unrealised": team.unrealised_goals},
                    )
                )

    if 2 in slots:
        pi = pressure_index.evaluate(
            timeline, home_goals=home_goals, away_goals=away_goals, weights=w
        )
        if pi is not None:
            for side in (Side.HOME, Side.AWAY):
                reading = pi.team(side)
                if reading.pressure >= th[2]:
                    candidates.append(
                        AlertCandidate(
                            2,
                            "pressure_index",
                            side,
                            float(reading.pressure),
                            {"pressure": reading.pressure},
                        )
                    )

    if 3 in slots:
        dg = delta_goal.evaluate(timeline, weights=w)
        if dg is not None and dg.triggering_team is not None:
            side = dg.triggering_team
            candidates.append(
                AlertCandidate(
                    3,
                    "delta_goal",
                    side,
                    float(dg.trigger_value),
                    {"threat": dg.trigger_value},
                )
            )

    if 4 in slots:
        d5 = delta_5min.evaluate(timeline, weights=w)
        if d5 is not None and d5.triggering_team is not None:
            side = d5.triggering_team
            candidates.append(
                AlertCandidate(
                    4,
                    "delta_5min",
                    side,
                    float(d5.trigger_value),
                    {"delta": d5.trigger_value},
                )
            )

    if 6 in slots:
        om = omega.evaluate(timeline, weights=w)
        if om is not None and om.triggering_team is not None:
            side = om.triggering_team
            candidates.append(
                AlertCandidate(
                    6,
                    "omega",
                    side,
                    float(om.trigger_value),
                    {"accel": om.trigger_value},
                )
            )

    if 7 in slots:

        def _signals(side: Side) -> TeamSignals:
            om_team = om.team(side) if om else None
            return TeamSignals(
                delta_5min=float(d5.team(side).pressure) if d5 else 0.0,
                pressure_index=float(pi.team(side).pressure) if pi else 0.0,
                rule_of_three=float(ro3.team(side).unrealised_goals) if ro3 else 0.0,
                npei=float(npei_snap.team(side).score) if npei_snap else 0.0,
                omega_acceleration=float(om_team.acceleration) if om_team else None,
                omega_baseline=float(om_team.baseline_slope) if om_team else None,
                omega_level=float(om_team.level) if om_team else None,
            )

        ks = kscore.evaluate(_signals(Side.HOME), _signals(Side.AWAY), weights=w, threshold=th[7])
        if ks.triggering_team is not None:
            side = ks.triggering_team
            candidates.append(
                AlertCandidate(
                    7,
                    "kscore",
                    side,
                    float(ks.trigger_value),
                    {"score": ks.trigger_value, "match": ks.match_score},
                )
            )

    return candidates
