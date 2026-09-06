"""Head-to-head statistics (Strategy 10 pure core).

Ported from `utils/h2h_service.py`. Wins and goals are attributed by team ID
only — never by name. Callers fetch fixtures; this module aggregates them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

DEFAULT_MIN_SAMPLE: Final = 5


@dataclass(frozen=True, slots=True)
class H2HFixture:
    match_id: str = ""
    home_team: str = ""
    away_team: str = ""
    home_team_id: int = 0
    away_team_id: int = 0
    home_score: int = 0
    away_score: int = 0
    match_date: str = ""
    league_name: str = ""
    league_id: int = 0


@dataclass(frozen=True, slots=True)
class CountPct:
    count: int
    pct: int


@dataclass(frozen=True, slots=True)
class TeamH2H:
    id: int
    name: str
    wins: int
    goals_total: int


@dataclass(frozen=True, slots=True)
class H2HStats:
    ok: bool
    insufficient: bool
    reason: str | None
    sample: int
    attributed: int
    team1: TeamH2H
    team2: TeamH2H
    draws: int
    btts: CountPct
    over_2_5: CountPct
    under_2_5: CountPct
    home_cs: CountPct
    away_cs: CountPct
    avg_goals: float | None
    fixtures: tuple[H2HFixture, ...]


def _to_int(v: Any, default: int = 0) -> int:
    try:
        if v is None or v == "":
            return default
        return int(str(v).strip())
    except (ValueError, TypeError):
        return default


def normalize_fixture(raw: dict[str, Any] | H2HFixture) -> H2HFixture:
    if isinstance(raw, H2HFixture):
        return raw
    score_raw = raw.get("score")
    score_block: dict[str, Any] = score_raw if isinstance(score_raw, dict) else {}
    return H2HFixture(
        match_id=str(raw.get("match_id") or "").strip(),
        home_team=str(raw.get("home_team") or ""),
        away_team=str(raw.get("away_team") or ""),
        home_team_id=_to_int(raw.get("home_team_id")),
        away_team_id=_to_int(raw.get("away_team_id")),
        home_score=_to_int(raw.get("home_score", score_block.get("home"))),
        away_score=_to_int(raw.get("away_score", score_block.get("away"))),
        match_date=str(raw.get("match_date") or ""),
        league_name=str(raw.get("league_name") or ""),
        league_id=_to_int(raw.get("league_id")),
    )


def dedup_fixtures(fixtures: list[H2HFixture]) -> list[H2HFixture]:
    seen: set[Any] = set()
    out: list[H2HFixture] = []
    for fx in fixtures:
        key = fx.match_id if fx.match_id else (fx.match_date, fx.home_team, fx.away_team)
        if key in seen:
            continue
        seen.add(key)
        out.append(fx)
    return out


def empty_h2h(
    team1_id: int,
    team2_id: int,
    team1_name: str = "",
    team2_name: str = "",
    *,
    sample: int = 0,
    reason: str = "no_data",
) -> H2HStats:
    zero = CountPct(0, 0)
    return H2HStats(
        ok=False,
        insufficient=True,
        reason=reason,
        sample=sample,
        attributed=0,
        team1=TeamH2H(team1_id, team1_name, 0, 0),
        team2=TeamH2H(team2_id, team2_name, 0, 0),
        draws=0,
        btts=zero,
        over_2_5=zero,
        under_2_5=zero,
        home_cs=zero,
        away_cs=zero,
        avg_goals=None,
        fixtures=(),
    )


def compute_h2h_stats(
    fixtures: list[dict[str, Any]] | list[H2HFixture],
    *,
    team1_id: int,
    team2_id: int,
    team1_name: str = "",
    team2_name: str = "",
    min_sample: int = DEFAULT_MIN_SAMPLE,
) -> H2HStats:
    """Canonical H2H aggregation. Below `min_sample` still returns counts."""
    normalized = dedup_fixtures([normalize_fixture(f) for f in (fixtures or [])])
    n = len(normalized)
    if n == 0:
        return empty_h2h(team1_id, team2_id, team1_name, team2_name, reason="no_data")

    insufficient = n < min_sample
    t1_wins = t2_wins = draws = 0
    t1_goals = t2_goals = 0
    both_scored = over25 = 0
    t1_home_cs = t2_home_cs = 0
    total_goals = 0

    for fx in normalized:
        hs, as_ = fx.home_score, fx.away_score
        hid, aid = fx.home_team_id, fx.away_team_id
        total = hs + as_
        total_goals += total
        if hs > 0 and as_ > 0:
            both_scored += 1
        if total > 2:
            over25 += 1

        if hid == team1_id and aid == team2_id:
            t1_goals += hs
            t2_goals += as_
            if hs > as_:
                t1_wins += 1
                t1_home_cs += 1 if as_ == 0 else 0
            elif as_ > hs:
                t2_wins += 1
            else:
                draws += 1
        elif hid == team2_id and aid == team1_id:
            t1_goals += as_
            t2_goals += hs
            if as_ > hs:
                t1_wins += 1
            elif hs > as_:
                t2_wins += 1
                t2_home_cs += 1 if as_ == 0 else 0
            else:
                draws += 1
        else:
            continue

    under25 = n - over25
    attributed = t1_wins + t2_wins + draws
    return H2HStats(
        ok=True,
        insufficient=insufficient,
        reason="insufficient_sample" if insufficient else None,
        sample=n,
        attributed=attributed,
        team1=TeamH2H(team1_id, team1_name, t1_wins, t1_goals),
        team2=TeamH2H(team2_id, team2_name, t2_wins, t2_goals),
        draws=draws,
        btts=CountPct(both_scored, round(both_scored / n * 100)),
        over_2_5=CountPct(over25, round(over25 / n * 100)),
        under_2_5=CountPct(under25, round(under25 / n * 100)),
        home_cs=CountPct(t1_home_cs, round(t1_home_cs / n * 100)),
        away_cs=CountPct(t2_home_cs, round(t2_home_cs / n * 100)),
        avg_goals=round(total_goals / n, 2),
        fixtures=tuple(normalized),
    )


@dataclass(frozen=True, slots=True)
class GoalEventMinute:
    minute: int
    team: str = ""  # side label as stored on events


@dataclass(frozen=True, slots=True)
class TimingCounts:
    sample: int
    late_goals: CountPct
    final_15: CountPct
    stoppage_time_goals: CountPct
    early_goals_15: CountPct
    fast_start_10: CountPct
    first_half_goals: CountPct
    btts_first_half: CountPct
    first_goal_before_30: CountPct


def compute_timing_counts(
    enriched_fixtures: list[dict[str, Any]],
) -> TimingCounts | None:
    """Timing patterns from fixtures that already carry `goal_events`.

    Each event is a dict with `minute` and optional `team`. Fixtures without
    events are excluded from the timing sample.
    """
    with_events = [f for f in enriched_fixtures if f.get("goal_events")]
    n = len(with_events)
    if n == 0:
        return None

    late_goals = final_15 = stoppage = 0
    early_15 = fast_10 = 0
    first_half_c = btts_fh = 0
    fgb30 = 0

    for fx in with_events:
        evts = fx["goal_events"]
        mins = [g["minute"] for g in evts]
        sorted_mins = sorted(mins)

        if any(m >= 70 for m in mins):
            late_goals += 1
        if any(m >= 75 for m in mins):
            final_15 += 1
        if any(m >= 90 for m in mins):
            stoppage += 1
        if any(m <= 15 for m in mins):
            early_15 += 1
        if any(m <= 10 for m in mins):
            fast_10 += 1

        fh_goals = [g for g in evts if g["minute"] <= 45]
        if fh_goals:
            first_half_c += 1
        teams_fh = {g["team"] for g in fh_goals if g.get("team")}
        if len(teams_fh) >= 2:
            btts_fh += 1
        if sorted_mins and sorted_mins[0] <= 30:
            fgb30 += 1

    def pct(c: int) -> CountPct:
        return CountPct(c, round(c / n * 100))

    return TimingCounts(
        sample=n,
        late_goals=pct(late_goals),
        final_15=pct(final_15),
        stoppage_time_goals=pct(stoppage),
        early_goals_15=pct(early_15),
        fast_start_10=pct(fast_10),
        first_half_goals=pct(first_half_c),
        btts_first_half=pct(btts_fh),
        first_goal_before_30=pct(fgb30),
    )
