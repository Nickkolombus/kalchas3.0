"""NPEI (ΦI) -- how efficiently a team converts activity into danger.

Three ratios over a rolling window, each 0-1:

    R1 = ΔD / ΔA   attack conversion  (dangerous attacks / attacks)
    R2 = ΔT / ΔS   shot accuracy      (shots on target / shots)
    R3 = ΔS / ΔA   shot creation      (shots / attacks)

    score = 100 × (w1·R1 + w2·R2 + w3·R3)

A ratio is only computed when its denominator clears a minimum-activity guard;
one dangerous attack out of one attack is not a 100% conversion rate, it is
noise. Ratios below the guard are dropped and contribute **0** — their weight
is not redistributed. Thin samples must not inflate the score. Callers can
see what was dropped via ``TeamEfficiency.dropped_ratios`` / ``is_partial``.

Ported from Kalchas 2.2 `utils/npei_calculator.py` (behaviour matched the
code there; an old 2.2 docstring that claimed redistribution was wrong and
is not carried forward).
"""

from __future__ import annotations

from dataclasses import dataclass

from kalchas_core.match import ActivityWindow, MatchTimeline, Side, TeamDeltas, resolve_window
from kalchas_core.npei.zones import EfficiencyZone, classify_efficiency
from kalchas_core.weights import WeightSet

NPEI_CAP = 100.0


@dataclass(frozen=True, slots=True)
class TeamEfficiency:
    """One team's efficiency reading for a window."""

    score: float
    raw_score: float
    zone: EfficiencyZone
    attack_conversion: float | None
    shot_accuracy: float | None
    shot_creation: float | None
    deltas: TeamDeltas

    @property
    def dropped_ratios(self) -> tuple[str, ...]:
        """Ratios the activity guards excluded from this score.

        A partial score is not comparable to a full three-ratio reading;
        missing ratios contribute 0 (see ``compute_npei``).
        """
        missing = {
            "attack_conversion": self.attack_conversion,
            "shot_accuracy": self.shot_accuracy,
            "shot_creation": self.shot_creation,
        }
        return tuple(name for name, value in missing.items() if value is None)

    @property
    def is_partial(self) -> bool:
        return bool(self.dropped_ratios)


@dataclass(frozen=True, slots=True)
class NpeiSnapshot:
    """Both teams' efficiency over the same window."""

    home: TeamEfficiency
    away: TeamEfficiency
    window_start_minute: int
    window_end_minute: int
    cap: float = NPEI_CAP

    def team(self, side: Side) -> TeamEfficiency:
        return self.home if side is Side.HOME else self.away

    @property
    def leader(self) -> Side | None:
        """The more efficient team, or None if they are level."""
        if self.home.score == self.away.score:
            return None
        return Side.HOME if self.home.score > self.away.score else Side.AWAY


def cap_signal(value: float, cap: float = NPEI_CAP) -> float:
    """Clamp to [0, cap]. Efficiency is a ratio blend, so it is never negative."""
    try:
        return max(0.0, min(cap, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _ratio(numerator: int, denominator: int, minimum: int) -> float | None:
    """`numerator / denominator` in 0-1, or None if there was too little activity."""
    if denominator < minimum:
        return None
    return max(0.0, min(1.0, numerator / denominator))


def _efficiency_for(
    deltas: TeamDeltas,
    *,
    w1: float,
    w2: float,
    w3: float,
    min_attacks: int,
    min_shots: int,
    weights: WeightSet,
) -> TeamEfficiency:
    attack_conversion = _ratio(deltas.dangerous_attacks, deltas.attacks, min_attacks)
    shot_accuracy = _ratio(deltas.shots_on_target, deltas.shots, min_shots)
    shot_creation = _ratio(deltas.shots, deltas.attacks, min_attacks)

    raw = 100.0 * (
        (w1 * attack_conversion if attack_conversion is not None else 0.0)
        + (w2 * shot_accuracy if shot_accuracy is not None else 0.0)
        + (w3 * shot_creation if shot_creation is not None else 0.0)
    )
    score = cap_signal(raw)

    return TeamEfficiency(
        score=score,
        raw_score=raw,
        zone=classify_efficiency(score, weights=weights),
        attack_conversion=attack_conversion,
        shot_accuracy=shot_accuracy,
        shot_creation=shot_creation,
        deltas=deltas,
    )


def compute_npei(
    timeline: MatchTimeline,
    *,
    weights: WeightSet | None = None,
    window: ActivityWindow | None = None,
) -> NpeiSnapshot | None:
    """Efficiency for both teams over the most recent window.

    Returns None when no window can be resolved -- the match is too young, or
    the minutes needed were never recorded. That is "no reading", which the
    caller must not confuse with a reading of zero.

    Dropped ratios (below activity guards) contribute 0. Weight is **not**
    redistributed across the surviving ratios: incomplete samples must not
    look as efficient as full ones. A team below the attack guard therefore
    cannot score above the remaining weights' share (e.g. R2 alone caps at
    40 when w2=0.4). ``TeamEfficiency.dropped_ratios`` makes the gap visible.
    """
    resolved = window if window is not None else resolve_window(timeline)
    if resolved is None:
        return None

    w = weights or WeightSet.defaults()
    w1 = w.get("npei", "w1_attack_conv")
    w2 = w.get("npei", "w2_shot_accuracy")
    w3 = w.get("npei", "w3_shot_creation")
    min_attacks = int(w.get("npei", "min_attacks"))
    min_shots = int(w.get("npei", "min_shots"))

    def efficiency(side: Side) -> TeamEfficiency:
        return _efficiency_for(
            resolved.deltas(side),
            w1=w1,
            w2=w2,
            w3=w3,
            min_attacks=min_attacks,
            min_shots=min_shots,
            weights=w,
        )

    return NpeiSnapshot(
        home=efficiency(Side.HOME),
        away=efficiency(Side.AWAY),
        window_start_minute=resolved.start_minute,
        window_end_minute=resolved.end_minute,
    )
