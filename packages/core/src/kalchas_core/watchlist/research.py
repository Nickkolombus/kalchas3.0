"""Watchlist payloads: one list row per match and the full research page.

Plain dicts in the shape the API serves, so the builder can store them in
``panel_cache`` as they are.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final

from kalchas_core.watchlist.patterns import (
    Pattern,
    match_patterns,
    pattern_table,
    watch_level,
    watch_score,
)
from kalchas_core.watchlist.profile import (
    TIMING_LABELS,
    LeagueNorms,
    TeamProfile,
    default_norms,
)
from kalchas_core.watchlist.results import day_summary

FORM_SHOWN: Final = 6
POINTS_SHOWN: Final = 3
POINT_MIN: Final = 0.15
"""Weaker than this and a pattern is noise: it stays in the table but is not
written up as something to watch."""
TAGS_SHOWN: Final = 3
SHORTLIST_SIZE: Final = 5
SHORTLIST_PER_LEAGUE: Final = 2


def _pattern_out(p: Pattern) -> dict[str, Any]:
    return {
        "key": p.key,
        "tag": p.tag,
        "title": p.title,
        "detail": p.detail,
        "brief": p.brief,
        "score": round(p.score, 3),
    }


def _form_out(profile: TeamProfile, source: str) -> dict[str, Any]:
    return {
        "games": profile.n,
        "source": source,
        "wins": profile.count("win"),
        "draws": profile.count("draw"),
        "losses": profile.count("loss"),
        "scored_per_game": profile.per_game(profile.goals_for),
        "conceded_per_game": profile.per_game(profile.goals_against),
        "clean_sheets": profile.count("clean_sheet"),
        "failed_to_score": profile.count("failed_to_score"),
        "results": [
            {
                "match_date": g.match_date,
                "opponent": g.opponent,
                "venue": g.venue,
                "goals_for": g.goals_for,
                "goals_against": g.goals_against,
                "result": g.result,
            }
            for g in profile.games[:FORM_SHOWN]
        ],
    }


def _timing_side(profile: TeamProfile) -> dict[str, Any]:
    games = profile.timed_games
    return {
        "games": len(games),
        "of": profile.n,
        "scored": [sum(g.for_by_bucket[i] for g in games) for i in range(len(TIMING_LABELS))],
        "conceded": [sum(g.against_by_bucket[i] for g in games) for i in range(len(TIMING_LABELS))],
    }


def timing_note(home: dict[str, Any], away: dict[str, Any], home_name: str, away_name: str) -> str:
    """One sentence on when goals come, or "" when there is nothing to say."""
    if home["games"] < 5 or away["games"] < 5:
        return ""
    totals = [
        home["scored"][i] + home["conceded"][i] + away["scored"][i] + away["conceded"][i]
        for i in range(len(TIMING_LABELS))
    ]
    goals = sum(totals)
    if not goals:
        return ""
    busiest = max(range(len(totals)), key=lambda i: (totals[i], i))
    share = totals[busiest] / goals
    if share < 0.22:
        return "Goals come fairly evenly through the game for both teams."
    window = TIMING_LABELS[busiest]
    lead = (
        "The last 15 minutes is"
        if busiest == len(TIMING_LABELS) - 1
        else "The first 15 minutes is"
        if busiest == 0
        else f"{window} is"
    )
    note = f"{lead} the busiest part of these teams' games: {totals[busiest]} of {goals} goals."
    late_for = home["scored"][-1] >= 3 and away["conceded"][-1] >= 3
    late_against = away["scored"][-1] >= 3 and home["conceded"][-1] >= 3
    if busiest == len(TIMING_LABELS) - 1 and late_for:
        note += f" {home_name} score late and {away_name} concede late."
    elif busiest == len(TIMING_LABELS) - 1 and late_against:
        note += f" {away_name} score late and {home_name} concede late."
    return note


def _h2h_out(h2h: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not h2h:
        return None
    summary = h2h.get("summary") or {}
    patterns = h2h.get("patterns") or {}
    sample = int(summary.get("sample") or 0)
    if sample <= 0:
        return None
    return {
        "sample": sample,
        "home_wins": int(summary.get("home_wins") or 0),
        "draws": int(summary.get("draws") or 0),
        "away_wins": int(summary.get("away_wins") or 0),
        "avg_goals": patterns.get("avg_goals"),
        "btts": int((patterns.get("btts") or {}).get("count") or 0),
        "over_2_5": int((patterns.get("over_2_5") or {}).get("count") or 0),
        "meetings": [
            {
                "match_date": str(m.get("match_date") or ""),
                "home_team": str(m.get("home_team") or ""),
                "away_team": str(m.get("away_team") or ""),
                "home_score": int(m.get("home_score") or 0),
                "away_score": int(m.get("away_score") or 0),
            }
            for m in (h2h.get("fixtures") or [])[:5]
        ],
    }


def table_slice(
    rows: Sequence[Mapping[str, Any]], team_ids: Sequence[int], *, around: int = 1
) -> list[dict[str, Any]]:
    """The table rows within `around` places of either team, in order."""
    positions = {int(r["team_id"]): int(r["position"]) for r in rows}
    keep: set[int] = set()
    for team_id in team_ids:
        pos = positions.get(int(team_id))
        if pos is not None:
            keep.update(range(pos - around, pos + around + 1))
    return [
        {
            "position": int(r["position"]),
            "team_id": int(r["team_id"]),
            "team": str(r.get("team") or ""),
            "played": int(r.get("played") or 0),
            "goal_difference": int(r.get("goal_difference") or 0),
            "points": int(r.get("points") or 0),
        }
        for r in rows
        if int(r["position"]) in keep
    ]


def _record_out(record: Mapping[str, Any] | None) -> dict[str, int] | None:
    if not record or not int(record.get("settled") or 0):
        return None
    return {"confirmed": int(record["confirmed"]), "settled": int(record["settled"])}


def league_label(fixture: Mapping[str, Any]) -> str:
    """Short league name for sentences ("Championship", not "England ·")."""
    name = str(fixture.get("league_name") or "").split(" - ")[0].strip()
    return name or "league"


def build_match_research(
    fixture: Mapping[str, Any],
    *,
    kickoff: str,
    home: TeamProfile,
    away: TeamProfile,
    home_source: str,
    away_source: str,
    norms: LeagueNorms,
    odds: Mapping[str, Any] | None,
    h2h: Mapping[str, Any] | None,
    table: Sequence[Mapping[str, Any]],
    league_record: Mapping[str, Any] | None,
    overall_record: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """The research page for one match. ``h2h`` is an oriented H2H payload
    (``kalchas_core.h2h.orient_h2h_payload``)."""
    league = league_label(fixture)
    if "all" in (home_source, away_source):
        norms = default_norms()
    if norms.games == 0:
        league = ""
    h2h_patterns = (h2h or {}).get("patterns") if h2h else None
    patterns = match_patterns(home, away, norms, league=league, h2h=h2h_patterns, odds=odds)
    timing_home, timing_away = _timing_side(home), _timing_side(away)
    positions = {int(r["team_id"]): r for r in table}

    def team(profile: TeamProfile, prefix: str) -> dict[str, Any]:
        row = positions.get(profile.team_id)
        return {
            "id": profile.team_id,
            "name": profile.name,
            "badge": fixture.get(f"{prefix}_badge") or None,
            "position": int(row["position"]) if row else None,
            "points": int(row["points"]) if row else None,
        }

    return {
        "match_id": str(fixture.get("match_id") or ""),
        "kickoff": kickoff,
        "league": {
            "id": int(fixture.get("league_id") or 0),
            "name": str(fixture.get("league_name") or ""),
            "country": str(fixture.get("country_name") or ""),
            "logo": fixture.get("league_logo") or None,
            "round": str(fixture.get("round") or ""),
        },
        "home": team(home, "home"),
        "away": team(away, "away"),
        "odds": dict(odds) if odds else None,
        "watch": watch_level(patterns),
        "score": watch_score(patterns),
        "points": [_pattern_out(p) for p in patterns if p.score >= POINT_MIN][:POINTS_SHOWN],
        "patterns": [_pattern_out(p) for p in patterns],
        "pattern_table": pattern_table(home, away, norms, h2h=h2h_patterns, patterns=patterns),
        "form": {"home": _form_out(home, home_source), "away": _form_out(away, away_source)},
        "timing": {
            "labels": list(TIMING_LABELS),
            "home": timing_home,
            "away": timing_away,
            "note": timing_note(timing_home, timing_away, home.name, away.name),
        },
        "h2h": _h2h_out(h2h),
        "table": table_slice(table, [home.team_id, away.team_id]) if table else [],
        "record": {
            "league": _record_out(league_record),
            "overall": _record_out(overall_record),
        },
    }


def league_key(research: Mapping[str, Any]) -> str:
    league = research.get("league") or {}
    return f"{int(league.get('id') or 0)}:{league.get('name') or ''}"


def _tags(patterns: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Chips for the list: the strongest patterns, one per label (both teams
    "struggling to score" is one chip, not two)."""
    out: list[dict[str, Any]] = []
    for p in patterns:
        if len(out) >= TAGS_SHOWN or p["score"] < POINT_MIN:
            break
        if any(t["label"] == p["tag"] for t in out):
            continue
        out.append({"label": p["tag"], "outcome": p.get("outcome")})
    return out


def list_row(research: Mapping[str, Any], league_key: str) -> dict[str, Any]:
    """The compact row the day list shows for one match. Once it is played
    the row carries the score and whether its lead pattern landed."""
    patterns = research.get("patterns") or []
    top = patterns[0] if patterns and research["watch"] != "quiet" else None
    odds = research.get("odds") or {}
    result = research.get("result") or None
    return {
        "match_id": research["match_id"],
        "kickoff": research["kickoff"],
        "league_key": league_key,
        "home": {k: research["home"][k] for k in ("name", "badge", "position")},
        "away": {k: research["away"][k] for k in ("name", "badge", "position")},
        "odds": {k: odds[k] for k in ("home", "draw", "away") if k in odds} or None,
        "watch": research["watch"],
        "score": research["score"],
        "lead_key": top["key"] if top else "",
        "headline": top["title"] if top else "",
        "reason": top["brief"] if top else "",
        "tags": _tags(patterns),
        "result": {k: result.get(k) for k in ("status", "label", "home", "away", "pens")}
        if result
        else None,
        "outcome": top.get("outcome") if top else None,
        "outcome_note": (top.get("outcome_note") or "") if top else "",
    }


def assemble_day(
    day: str,
    pages: Sequence[Mapping[str, Any]],
    *,
    built_at: str,
    timezone: str,
    partial: bool = False,
) -> dict[str, Any]:
    """A day's list from its match pages: rows by kick-off, leagues with the
    standout matches first, the top five and the day's tally."""
    rows: list[dict[str, Any]] = []
    leagues: dict[str, dict[str, Any]] = {}
    for page in sorted(pages, key=lambda p: (str(p.get("kickoff")), str(p.get("match_id")))):
        key = league_key(page)
        rows.append(list_row(page, key))
        meta = page.get("league") or {}
        league = leagues.setdefault(
            key,
            {
                "key": key,
                "name": str(meta.get("name") or ""),
                "country": str(meta.get("country") or ""),
                "logo": meta.get("logo") or None,
                "match_ids": [],
            },
        )
        league["match_ids"].append(str(page["match_id"]))
    best = {
        key: max((float(r["score"]) for r in rows if r["league_key"] == key), default=0.0)
        for key in leagues
    }
    top = shortlist(rows)
    return {
        "day": day,
        "built_at": built_at,
        "timezone": timezone,
        "partial": partial,
        "matches": rows,
        "leagues": sorted(leagues.values(), key=lambda lg: -best[lg["key"]]),
        "shortlist": top,
        "summary": day_summary(rows, top),
    }


def shortlist(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """The day's top matches, at most two from any one league."""
    picked: list[str] = []
    per_league: dict[str, int] = {}
    for row in sorted(rows, key=lambda r: float(r.get("score") or 0), reverse=True):
        if row.get("watch") == "quiet" or len(picked) >= SHORTLIST_SIZE:
            continue
        league = str(row.get("league_key") or "")
        if per_league.get(league, 0) >= SHORTLIST_PER_LEAGUE:
            continue
        per_league[league] = per_league.get(league, 0) + 1
        picked.append(str(row["match_id"]))
    return picked
