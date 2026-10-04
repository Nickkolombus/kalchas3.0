"""Strategy runner — evaluate active slots against a timeline.

Returns alert candidates; does not check cooldown or deliver messages.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kalchas_core.conditions import (
    ConditionMatch,
    favourite_from_kickoff,
    passes_extra_conditions,
)
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
    3: 6.0,  # League Bar signed score threshold
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


def _clears_fire(value: float, threshold: float) -> bool:
    """Admin fire threshold: alert only when the displayed value meets the bar."""
    return float(value) >= float(threshold)


def _card_pair(raw: Any) -> tuple[int, int]:
    if isinstance(raw, dict):
        return int(raw.get("home") or 0), int(raw.get("away") or 0)
    if isinstance(raw, (tuple, list)) and len(raw) >= 2:
        return int(raw[0] or 0), int(raw[1] or 0)
    return 0, 0


def _slot_rows(conditions: Any, slot: int) -> list:
    if not conditions:
        return []
    rows = conditions.get(slot) if isinstance(conditions, dict) else None
    return list(rows) if rows else []


def _condition_match(
    timeline: MatchTimeline,
    *,
    home_goals: int,
    away_goals: int,
    ro3: Any,
    pi: Any,
    d5: Any,
    dg: Any,
    om: Any,
    npei_snap: Any,
    ks: Any,
    home_odds: float | None,
    away_odds: float | None,
    live_home_odds: float | None,
    live_away_odds: float | None,
    yellow_cards: Any,
    red_cards: Any,
) -> ConditionMatch:
    snap = timeline.current
    yellow = _card_pair(yellow_cards)
    red = _card_pair(red_cards)

    def _side(side: Side, index: int) -> dict[str, float | None]:
        team = snap.team(side) if snap is not None else None
        omega_team = om.team(side) if om is not None else None
        return {
            "rule_of_three": float(ro3.team(side).unrealised_goals) if ro3 is not None else 0.0,
            "pressure_index": float(pi.team(side).pressure) if pi is not None else 0.0,
            "delta_5min": float(d5.team(side).pressure) if d5 is not None else 0.0,
            "delta_goal": float(dg.team(side).threat) if dg is not None else 0.0,
            "npei": float(npei_snap.team(side).score) if npei_snap is not None else 0.0,
            "omega": float(omega_team.theta) if omega_team is not None else 0.0,
            "kscore": float(ks.team(side).score) if ks is not None else 0.0,
            "shots_on_target": float(team.shots_on_target) if team is not None else 0.0,
            "shots_off_target": float(team.shots_off_target) if team is not None else 0.0,
            "attacks": float(team.attacks) if team is not None else 0.0,
            "dangerous_attacks": float(team.dangerous_attacks) if team is not None else 0.0,
            "corners": float(team.corners) if team is not None else 0.0,
            "possession": float(team.possession) if team is not None else 0.0,
            "yellow_cards": float(yellow[index]),
            "red_cards": float(red[index]),
            "goals": float(home_goals if side is Side.HOME else away_goals),
            "kickoff_odds": home_odds if side is Side.HOME else away_odds,
            "live_odds": live_home_odds if side is Side.HOME else live_away_odds,
        }

    return ConditionMatch(
        home=_side(Side.HOME, 0),
        away=_side(Side.AWAY, 1),
        favourite=favourite_from_kickoff(home_odds, away_odds),
    )


def _extra_ok(conditions: Any, slot: int, side: Side, match: ConditionMatch | None) -> bool:
    if match is None:
        return True
    return passes_extra_conditions(_slot_rows(conditions, slot), match, side)


def _parse_decimal_odds(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 1.0 else None


def _odds_pair(block: Any) -> tuple[float | None, float | None]:
    if not isinstance(block, dict):
        return None, None
    home = _parse_decimal_odds(block.get("home"))
    away = _parse_decimal_odds(block.get("away"))
    if home is None or away is None:
        return None, None
    return home, away


def home_away_odds(odds: dict[str, Any] | None) -> tuple[float | None, float | None]:
    """Kickoff 1X2 home/away only when both parse as decimal odds greater than 1."""
    if not isinstance(odds, dict):
        return None, None
    nested = _odds_pair(odds.get("kickoff"))
    if nested != (None, None):
        return nested
    return _odds_pair(odds)


def live_home_away_odds(odds: dict[str, Any] | None) -> tuple[float | None, float | None]:
    """Cached live 1X2. Missing or incomplete lines stay (None, None)."""
    if not isinstance(odds, dict):
        return None, None
    return _odds_pair(odds.get("live"))


def evaluate_match(
    timeline: MatchTimeline,
    *,
    home_goals: int = 0,
    away_goals: int = 0,
    weights: WeightSet | None = None,
    thresholds: dict[int, float] | None = None,
    slots: tuple[int, ...] = (1, 2, 3, 4, 6, 7),
    league_id: str | int | None = None,
    league_name: str | None = None,
    country_name: str | None = None,
    home_odds: float | None = None,
    away_odds: float | None = None,
    live_home_odds: float | None = None,
    live_away_odds: float | None = None,
    yellow_cards: Any = (0, 0),
    red_cards: Any = (0, 0),
    conditions: dict[int, list] | None = None,
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
    dg = None
    ks = None

    if 1 in slots:
        ro3 = rule_of_three.evaluate(
            _shot_profile(timeline, Side.HOME),
            _shot_profile(timeline, Side.AWAY),
            minute=minute,
            weights=w,
        )
        for side in (Side.HOME, Side.AWAY):
            team = ro3.team(side)
            if _clears_fire(team.unrealised_goals, th[1]):
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
                if _clears_fire(reading.pressure, th[2]):
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
        dg = delta_goal.evaluate(
            timeline,
            home_score=home_goals,
            away_score=away_goals,
            league_id=league_id,
            league_name=league_name,
            country_name=country_name,
            home_odds=home_odds,
            away_odds=away_odds,
            threshold=th[3],
            weights=w,
        )
        if (
            dg is not None
            and dg.triggering_team is not None
            and _clears_fire(dg.trigger_value, th[3])
        ):
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
        if (
            d5 is not None
            and d5.triggering_team is not None
            and _clears_fire(d5.trigger_value, th[4])
        ):
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

    if 6 in slots or 7 in slots:
        om = omega.evaluate(timeline, weights=w)

    if 6 in slots:
        if om is not None and om.triggering_team is not None:
            side = om.triggering_team
            reading = om.team(side)
            candidates.append(
                AlertCandidate(
                    6,
                    "omega",
                    side,
                    float(om.trigger_value),
                    {
                        "accel": om.trigger_value,
                        "theta": float(reading.theta) if reading else 0.0,
                        "k_scale": float(om.settings.angle_scale),
                    },
                )
            )

    if 7 in slots:
        # Consultants needed for K-Score even when their own slots are off.
        if pi is None and 2 not in slots:
            pi = pressure_index.evaluate(
                timeline, home_goals=home_goals, away_goals=away_goals, weights=w
            )
        if d5 is None and 4 not in slots:
            d5 = delta_5min.evaluate(timeline, weights=w)
        if ro3 is None and 1 not in slots:
            ro3 = rule_of_three.evaluate(
                _shot_profile(timeline, Side.HOME),
                _shot_profile(timeline, Side.AWAY),
                minute=minute,
                weights=w,
            )

        def _signals(side: Side) -> TeamSignals:
            return TeamSignals.from_omega(
                om.team(side) if om else None,
                delta_5min=float(d5.team(side).pressure) if d5 else 0.0,
                pressure_index=float(pi.team(side).pressure) if pi else 0.0,
                rule_of_three=float(ro3.team(side).unrealised_goals) if ro3 else 0.0,
                npei=float(npei_snap.team(side).score) if npei_snap else 0.0,
            )

        ks = kscore.evaluate(_signals(Side.HOME), _signals(Side.AWAY), weights=w, threshold=th[7])
        if ks.triggering_team is not None and _clears_fire(ks.trigger_value, th[7]):
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

    if candidates and any(_slot_rows(conditions, cand.strategy_slot) for cand in candidates):
        if npei_snap is None:
            npei_snap = compute_npei(timeline, weights=w)
        if pi is None:
            pi = pressure_index.evaluate(
                timeline, home_goals=home_goals, away_goals=away_goals, weights=w
            )
        if d5 is None:
            d5 = delta_5min.evaluate(timeline, weights=w)
        if ro3 is None:
            ro3 = rule_of_three.evaluate(
                _shot_profile(timeline, Side.HOME),
                _shot_profile(timeline, Side.AWAY),
                minute=minute,
                weights=w,
            )
        if dg is None:
            dg = delta_goal.evaluate(
                timeline,
                home_score=home_goals,
                away_score=away_goals,
                league_id=league_id,
                league_name=league_name,
                country_name=country_name,
                home_odds=home_odds,
                away_odds=away_odds,
                threshold=th[3],
                weights=w,
            )
        if om is None:
            om = omega.evaluate(timeline, weights=w)
        if ks is None:

            def _cond_signals(side: Side) -> TeamSignals:
                return TeamSignals.from_omega(
                    om.team(side) if om else None,
                    delta_5min=float(d5.team(side).pressure) if d5 else 0.0,
                    pressure_index=float(pi.team(side).pressure) if pi else 0.0,
                    rule_of_three=float(ro3.team(side).unrealised_goals) if ro3 else 0.0,
                    npei=float(npei_snap.team(side).score) if npei_snap else 0.0,
                )

            ks = kscore.evaluate(
                _cond_signals(Side.HOME),
                _cond_signals(Side.AWAY),
                weights=w,
                threshold=th[7],
            )
        ctx = _condition_match(
            timeline,
            home_goals=home_goals,
            away_goals=away_goals,
            ro3=ro3,
            pi=pi,
            d5=d5,
            dg=dg,
            om=om,
            npei_snap=npei_snap,
            ks=ks,
            home_odds=home_odds,
            away_odds=away_odds,
            live_home_odds=live_home_odds,
            live_away_odds=live_away_odds,
            yellow_cards=yellow_cards,
            red_cards=red_cards,
        )
        candidates = [
            cand
            for cand in candidates
            if cand.side is None or _extra_ok(conditions, cand.strategy_slot, cand.side, ctx)
        ]

    return candidates


def _team_cell(value: float, *, triggered: bool, digits: int = 1) -> dict[str, Any]:
    cell: dict[str, Any] = {"value": round(float(value), digits)}
    if triggered:
        cell["triggered"] = True
    return cell


def board_snapshot(
    timeline: MatchTimeline,
    *,
    home_goals: int = 0,
    away_goals: int = 0,
    weights: WeightSet | None = None,
    thresholds: dict[int, float] | None = None,
    league_id: str | int | None = None,
    league_name: str | None = None,
    country_name: str | None = None,
    home_odds: float | None = None,
    away_odds: float | None = None,
    live_home_odds: float | None = None,
    live_away_odds: float | None = None,
    yellow_cards: Any = (0, 0),
    red_cards: Any = (0, 0),
    conditions: dict[int, list] | None = None,
) -> dict[str, Any]:
    """Continuous strategy + stat lines for the live board (not only alert fires)."""
    w = weights or WeightSet.defaults()
    th = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    minute = timeline.current_minute
    npei_th = float(th.get(5, 55.0))

    ro3 = rule_of_three.evaluate(
        _shot_profile(timeline, Side.HOME),
        _shot_profile(timeline, Side.AWAY),
        minute=minute,
        weights=w,
    )
    pi = pressure_index.evaluate(timeline, home_goals=home_goals, away_goals=away_goals, weights=w)
    d5 = delta_5min.evaluate(timeline, weights=w)
    dg = delta_goal.evaluate(
        timeline,
        home_score=home_goals,
        away_score=away_goals,
        league_id=league_id,
        league_name=league_name,
        country_name=country_name,
        home_odds=home_odds,
        away_odds=away_odds,
        weights=w,
        threshold=th[3],
    )
    om = omega.evaluate(timeline, weights=w)
    npei_snap = compute_npei(timeline, weights=w)

    def _signals(side: Side) -> TeamSignals:
        return TeamSignals.from_omega(
            om.team(side) if om else None,
            delta_5min=float(d5.team(side).pressure) if d5 else 0.0,
            pressure_index=float(pi.team(side).pressure) if pi else 0.0,
            rule_of_three=float(ro3.team(side).unrealised_goals) if ro3 else 0.0,
            npei=float(npei_snap.team(side).score) if npei_snap else 0.0,
        )

    ks = kscore.evaluate(_signals(Side.HOME), _signals(Side.AWAY), weights=w, threshold=th[7])

    ctx = None
    if conditions and any(conditions.values()):
        ctx = _condition_match(
            timeline,
            home_goals=home_goals,
            away_goals=away_goals,
            ro3=ro3,
            pi=pi,
            d5=d5,
            dg=dg,
            om=om,
            npei_snap=npei_snap,
            ks=ks,
            home_odds=home_odds,
            away_odds=away_odds,
            live_home_odds=live_home_odds,
            live_away_odds=live_away_odds,
            yellow_cards=yellow_cards,
            red_cards=red_cards,
        )

    def _fired(slot: int, side: Side, native: bool) -> bool:
        return bool(native) and _extra_ok(conditions, slot, side, ctx)

    strategy_status: dict[str, Any] = {
        "rule_of_three": {
            "teams": {
                "home": _team_cell(
                    ro3.home.unrealised_goals,
                    triggered=_fired(1, Side.HOME, ro3.home.unrealised_goals >= th[1]),
                ),
                "away": _team_cell(
                    ro3.away.unrealised_goals,
                    triggered=_fired(1, Side.AWAY, ro3.away.unrealised_goals >= th[1]),
                ),
            },
            "threshold": th[1],
        },
        "pressure_index": {
            "teams": {
                "home": _team_cell(
                    pi.home.pressure if pi else 0.0,
                    triggered=_fired(2, Side.HOME, bool(pi and pi.home.pressure >= th[2])),
                    digits=0,
                ),
                "away": _team_cell(
                    pi.away.pressure if pi else 0.0,
                    triggered=_fired(2, Side.AWAY, bool(pi and pi.away.pressure >= th[2])),
                    digits=0,
                ),
            },
            "threshold": th[2],
        },
        "delta_5min": {
            "teams": {
                "home": _team_cell(
                    d5.home.pressure if d5 else 0.0,
                    triggered=_fired(
                        4,
                        Side.HOME,
                        bool(d5 and d5.home.pressure >= th[4] and d5.home.passes_gate),
                    ),
                    digits=1,
                ),
                "away": _team_cell(
                    d5.away.pressure if d5 else 0.0,
                    triggered=_fired(
                        4,
                        Side.AWAY,
                        bool(d5 and d5.away.pressure >= th[4] and d5.away.passes_gate),
                    ),
                    digits=1,
                ),
            },
            "threshold": th[4],
        },
        "delta_goal": {
            "teams": {
                "home": _team_cell(
                    dg.home.threat, triggered=_fired(3, Side.HOME, dg.home.qualifies)
                ),
                "away": _team_cell(
                    dg.away.threat, triggered=_fired(3, Side.AWAY, dg.away.qualifies)
                ),
            },
            "threshold": th[3],
        },
        "npei": {
            "teams": {
                "home": _team_cell(
                    npei_snap.home.score if npei_snap else 0.0,
                    triggered=bool(npei_snap and npei_snap.home.score >= npei_th),
                    digits=0,
                ),
                "away": _team_cell(
                    npei_snap.away.score if npei_snap else 0.0,
                    triggered=bool(npei_snap and npei_snap.away.score >= npei_th),
                    digits=0,
                ),
            },
            "threshold": npei_th,
        },
        "omega": {
            "teams": {
                "home": _team_cell(
                    (om.home.theta if om and om.home else 0.0),
                    triggered=_fired(
                        6, Side.HOME, bool(om and om.home and om.home.meets(om.settings))
                    ),
                    digits=0,
                ),
                "away": _team_cell(
                    (om.away.theta if om and om.away else 0.0),
                    triggered=_fired(
                        6, Side.AWAY, bool(om and om.away and om.away.meets(om.settings))
                    ),
                    digits=0,
                ),
            },
            "threshold": round(
                om.settings.theta_threshold if om else omega.DEFAULT_THETA_THRESHOLD
            ),
        },
        "kscore": {
            "teams": {
                "home": _team_cell(
                    ks.home.score,
                    triggered=_fired(7, Side.HOME, ks.home.score >= th[7]),
                    digits=0,
                ),
                "away": _team_cell(
                    ks.away.score,
                    triggered=_fired(7, Side.AWAY, ks.away.score >= th[7]),
                    digits=0,
                ),
            },
            "threshold": th[7],
            "match": ks.match_score,
        },
    }

    active: list[str] = []
    for key, block in strategy_status.items():
        teams = block.get("teams") or {}
        if any((teams.get(side) or {}).get("triggered") for side in ("home", "away")):
            active.append(key)

    snap = timeline.current
    stat_lines: dict[str, dict[str, float | int]] = {}
    if snap is not None:
        for key in (
            "shots_on_target",
            "shots_off_target",
            "attacks",
            "dangerous_attacks",
            "corners",
            "possession",
        ):
            stat_lines[key] = {
                "home": getattr(snap.home, key),
                "away": getattr(snap.away, key),
            }

    return {
        "strategy_status": strategy_status,
        "active_strategies": active,
        "hot_score": int(ks.match_score),
        "stat_lines": stat_lines,
    }
