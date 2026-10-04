"""H2H overlay payload: cached stats + optional timing from the H2H row."""

from __future__ import annotations

from typing import Any

from kalchas_core.h2h import compute_h2h_stats, compute_timing_counts

DEFAULT_LAST = 10


def _count(raw: Any) -> dict[str, int]:
    if raw is None:
        return {"count": 0, "pct": 0}
    return {"count": int(raw.count), "pct": int(raw.pct)}


def build_h2h_payload(
    fixtures: list[dict[str, Any]],
    *,
    home_team_id: int,
    away_team_id: int,
    home_team: str,
    away_team: str,
) -> dict[str, Any]:
    stats = compute_h2h_stats(
        fixtures,
        team1_id=home_team_id,
        team2_id=away_team_id,
        team1_name=home_team,
        team2_name=away_team,
    )
    by_id = {str(item.get("match_id") or ""): item for item in fixtures}
    enriched = []
    listed = []
    for fx in stats.fixtures:
        raw = by_id.get(fx.match_id) or {}
        listed.append(
            {
                "match_id": fx.match_id,
                "home_team": fx.home_team,
                "away_team": fx.away_team,
                "home_score": fx.home_score,
                "away_score": fx.away_score,
                "match_date": fx.match_date,
                "league_name": fx.league_name,
                "home_team_id": fx.home_team_id,
                "away_team_id": fx.away_team_id,
            }
        )
        enriched.append({**listed[-1], "goal_events": list(raw.get("goal_events") or [])})

    listed.sort(key=lambda row: str(row.get("match_date") or ""), reverse=True)

    timing_raw = compute_timing_counts(enriched)
    timing = None
    if timing_raw is not None:
        timing = {
            "sample": timing_raw.sample,
            "late_goals": _count(timing_raw.late_goals),
            "final_15": _count(timing_raw.final_15),
            "stoppage_time_goals": _count(timing_raw.stoppage_time_goals),
            "early_goals_15": _count(timing_raw.early_goals_15),
            "fast_start_10": _count(timing_raw.fast_start_10),
            "first_half_goals": _count(timing_raw.first_half_goals),
            "btts_first_half": _count(timing_raw.btts_first_half),
            "first_goal_before_30": _count(timing_raw.first_goal_before_30),
        }

    n = stats.sample
    return {
        "home_team": home_team,
        "away_team": away_team,
        "insufficient": stats.insufficient,
        "reason": stats.reason,
        "summary": {
            "home_wins": stats.team1.wins,
            "draws": stats.draws,
            "away_wins": stats.team2.wins,
            "sample": n,
        },
        "fixtures": listed,
        "patterns": {
            "sample": n,
            "over_2_5": _count(stats.over_2_5),
            "under_2_5": _count(stats.under_2_5),
            "btts": _count(stats.btts),
            "home_cs": {**_count(stats.home_cs), "team": home_team},
            "away_cs": {**_count(stats.away_cs), "team": away_team},
            "avg_goals": stats.avg_goals,
            "home_goals": stats.team1.goals_total,
            "away_goals": stats.team2.goals_total,
            "timing": timing,
        },
    }


def empty_h2h_payload(*, home_team: str, away_team: str, reason: str = "no_data") -> dict[str, Any]:
    zero = {"count": 0, "pct": 0}
    return {
        "home_team": home_team,
        "away_team": away_team,
        "insufficient": True,
        "reason": reason,
        "summary": {"home_wins": 0, "draws": 0, "away_wins": 0, "sample": 0},
        "fixtures": [],
        "patterns": {
            "sample": 0,
            "over_2_5": zero,
            "under_2_5": zero,
            "btts": zero,
            "home_cs": {**zero, "team": home_team},
            "away_cs": {**zero, "team": away_team},
            "avg_goals": None,
            "home_goals": 0,
            "away_goals": 0,
            "timing": None,
        },
    }
