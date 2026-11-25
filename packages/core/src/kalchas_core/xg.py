"""Shot-quality expected goals (xG) from the feed's shot counters.

The feed has no per-shot data, so this prices each shot by the kind of shot it
was, using standard published averages:

    xG = 0.76 x penalties
       + 0.12 x (shots inside the box - penalties)
       + 0.035 x shots outside the box

Shot locations (inside / outside the box) come only with the extended stats
block that top leagues carry. Elsewhere the estimate falls back to a flat price
per shot, which is rougher, and says so through `source`:

    xG = 0.76 x penalties
       + 0.08 x (shots on target + shots off target - penalties)

The fallback is fitted to the box version, so both read on one scale: on
4,100 top-league team-halves (27 Oct - 25 Nov 2026, where both can be worked
out) the box version priced a shot at about 0.08 whether it was on target or
off, and knowing the goals scored added nothing. Out of sample it misses the
box version by 0.23 a half. The earlier fallback (0.19 per shot on target,
0.077 off) read 0.20 a half higher and missed by 0.36.

Checked on 2026-11-25 against a commercial board's full-time xG for four
Champions League teams: the box version missed by 0.47 on average (three of
four within 0.16). It is an estimate; one clear one-on-one chance can be worth
far more than its shot type suggests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from kalchas_core.match.snapshot import TeamStats

PENALTY_XG = 0.76
INSIDE_BOX_XG = 0.12
OUTSIDE_BOX_XG = 0.035
SHOT_XG = 0.08

XgSource = Literal["box", "shots"]


@dataclass(frozen=True, slots=True)
class ShotXg:
    value: float
    source: XgSource
    """"box" when shot locations were available, "shots" for the rough fallback."""


def shot_quality_xg(team: TeamStats) -> ShotXg:
    """Expected goals for one team from its cumulative counters."""
    pens = team.penalties
    if team.shots_inside_box is not None and team.shots_outside_box is not None:
        value = (
            PENALTY_XG * pens
            + INSIDE_BOX_XG * max(0, team.shots_inside_box - pens)
            + OUTSIDE_BOX_XG * team.shots_outside_box
        )
        return ShotXg(round(value, 2), "box")
    shots = max(0, team.shots_on_target + team.shots_off_target - pens)
    return ShotXg(round(PENALTY_XG * pens + SHOT_XG * shots, 2), "shots")


def match_xg(home: TeamStats, away: TeamStats) -> tuple[dict[str, float], XgSource]:
    """Board line ``{"home", "away"}`` plus the weaker of the two sources."""
    h = shot_quality_xg(home)
    a = shot_quality_xg(away)
    source: XgSource = "box" if h.source == a.source == "box" else "shots"
    return {"home": h.value, "away": a.value}, source
