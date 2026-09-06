"""English insight strings from team form metrics.

Presentation rules for Strategy 9 enrichment. Thresholds match 2.2's
hardcoded defaults (config nesting under `parameters` was never applied).
"""

from __future__ import annotations

from collections.abc import Sequence

from kalchas_core.form.metrics import (
    DEFAULT_CONCEDE_FLAG,
    DEFAULT_FORM_POINTS_GAP,
    DEFAULT_GD_INSIGHT,
    DEFAULT_HIGH_SCORING,
    DEFAULT_MIN_STREAK,
    DEFAULT_POSITION_GAP,
    DEFAULT_SCORING_GAP,
    TeamForm,
)

_PRIORITY_KEYWORDS: dict[str, int] = {
    "streak": 10,
    "winning": 9,
    "averaging": 8,
    "much better": 7,
    "clash": 6,
    "conceding": 5,
    "winless": 4,
    "difference": 3,
    "place": 2,
}


def streak_insights(
    team_name: str,
    form: TeamForm,
    *,
    min_streak: int = DEFAULT_MIN_STREAK,
) -> list[str]:
    streak = form.current_streak
    if streak.count < min_streak or streak.type is None:
        return []
    if streak.type == "W":
        return [f"{team_name} on {streak.count}-game winning streak"]
    if streak.type == "L":
        return [f"{team_name} winless in last {streak.count} games"]
    if streak.type == "D" and streak.count >= 3:
        return [f"{team_name}: {streak.count} consecutive draws"]
    return []


def goal_form_insights(
    team_name: str,
    form: TeamForm,
    *,
    high_scoring: float = DEFAULT_HIGH_SCORING,
    concede_flag: float = DEFAULT_CONCEDE_FLAG,
    gd_insight: int = DEFAULT_GD_INSIGHT,
) -> list[str]:
    if form.games_played < 3:
        return []
    insights: list[str] = []
    if form.goals_per_game >= high_scoring:
        insights.append(f"{team_name} averaging {form.goals_per_game} goals in recent form")
    if form.goals_against_per_game >= concede_flag:
        insights.append(
            f"{team_name} conceding {form.goals_against_per_game} goals per game recently"
        )
    if form.goal_difference >= gd_insight:
        insights.append(f"{team_name}: +{form.goal_difference} goal difference in recent games")
    elif form.goal_difference <= -gd_insight:
        insights.append(f"{team_name}: {form.goal_difference} goal difference in recent form")
    return insights


def comparative_insights(
    home_name: str,
    away_name: str,
    home_form: TeamForm,
    away_form: TeamForm,
    *,
    form_points_gap: int = DEFAULT_FORM_POINTS_GAP,
    scoring_gap: float = DEFAULT_SCORING_GAP,
) -> list[str]:
    insights: list[str] = []
    home_points = home_form.form_points
    away_points = away_form.form_points
    if home_points - away_points >= form_points_gap:
        insights.append(
            f"{home_name} in much better recent form "
            f"({home_form.form_string} vs {away_form.form_string})"
        )
    elif away_points - home_points >= form_points_gap:
        insights.append(
            f"{away_name} in much better recent form "
            f"({away_form.form_string} vs {home_form.form_string})"
        )

    goal_diff = home_form.goals_per_game - away_form.goals_per_game
    if goal_diff >= scoring_gap:
        insights.append(f"{home_name} scoring {goal_diff:.1f} more goals per game than {away_name}")
    elif goal_diff <= -scoring_gap:
        insights.append(
            f"{away_name} scoring {abs(goal_diff):.1f} more goals per game than {home_name}"
        )
    return insights


def position_insights(
    standings: Sequence[dict],
    home_id: int,
    away_id: int,
    home_name: str,
    away_name: str,
    *,
    position_gap: int = DEFAULT_POSITION_GAP,
) -> list[str]:
    """Table-clash lines from a flat standings list (already unwrapped).

    Each entry needs `team_id` (or nested `team.id`) and optional `position`.
    """
    home_position = away_position = None
    for i, team_data in enumerate(standings):
        raw_team = team_data.get("team")
        team_block: dict = raw_team if isinstance(raw_team, dict) else {}
        team_id = int(team_data.get("team_id", team_block.get("id", 0)) or 0)
        position = int(team_data.get("position", i + 1) or (i + 1))
        if team_id == home_id:
            home_position = position
        elif team_id == away_id:
            away_position = position

    if home_position is None or away_position is None:
        return []

    insights: list[str] = []
    gap = abs(home_position - away_position)
    if gap >= position_gap:
        if home_position < away_position:
            insights.append(f"Table clash: {home_position}th vs {away_position}th place")
        else:
            insights.append(f"Table clash: {away_position}th vs {home_position}th place")
    elif home_position <= 3 and away_position <= 3:
        insights.append(f"Top-table clash: {home_position}nd vs {away_position}rd place")
    elif home_position <= 6 or away_position <= 6:
        insights.append(f"European spots clash: {home_position}th vs {away_position}th place")
    # home_name / away_name unused in 2.2's position strings too — kept for API symmetry
    _ = (home_name, away_name)
    return insights


def prioritize_insights(insights: Sequence[str], *, limit: int = 3) -> list[str]:
    """Score by keyword interest, dedupe, return top `limit`."""
    if not insights:
        return []
    scored: list[tuple[int, str]] = []
    for insight in insights:
        score = 0
        lower = insight.lower()
        for keyword, points in _PRIORITY_KEYWORDS.items():
            if keyword in lower:
                score += points
        scored.append((score, insight))
    scored.sort(key=lambda x: x[0], reverse=True)
    unique: list[str] = []
    seen: set[str] = set()
    for _, insight in scored:
        if insight not in seen:
            unique.append(insight)
            seen.add(insight)
        if len(unique) >= limit:
            break
    return unique


def build_form_insights(
    home_name: str,
    away_name: str,
    home_form: TeamForm,
    away_form: TeamForm,
    *,
    standings: Sequence[dict] | None = None,
    home_id: int = 0,
    away_id: int = 0,
    limit: int = 3,
) -> list[str]:
    """Full enrichment pipeline once forms (and optional standings) are known."""
    insights: list[str] = []
    insights.extend(streak_insights(home_name, home_form))
    insights.extend(streak_insights(away_name, away_form))
    insights.extend(goal_form_insights(home_name, home_form))
    insights.extend(goal_form_insights(away_name, away_form))
    insights.extend(comparative_insights(home_name, away_name, home_form, away_form))
    if standings is not None and home_id and away_id:
        insights.extend(position_insights(standings, home_id, away_id, home_name, away_name))
    return prioritize_insights(insights, limit=limit)
