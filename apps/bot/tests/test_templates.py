"""Alert text templates: same output as the built-in text by default, safe, and fall back."""

from __future__ import annotations

from typing import Any

import pytest
from kalchas_bot import templates as t
from kalchas_bot.format import format_alert_html, format_joint_html, format_outcome_html


def _row(**extra: Any) -> dict[str, Any]:
    payload = {
        "league": "Premier League",
        "country": "England",
        "tslg": "12 - 67",
        "sot": {"home": 6, "away": 2},
        "sofft": {"home": 5, "away": 3},
        "corners": {"home": 7, "away": 1},
        "attacks": {"home": 88, "away": 54},
        "da": {"home": 61, "away": 30},
        "possession": {"home": 62, "away": 38},
        "yc": {"home": 1, "away": 3},
        "rc": {"home": 0, "away": 0},
        "odds": {
            "home": 1.85,
            "draw": 3.6,
            "away": 4.2,
            "kickoff": {"home": 1.85, "draw": 3.6, "away": 4.2},
        },
        "h2h": {"sample": 8, "home_wins": 4, "draws": 2, "away_wins": 2},
        "last_5min": {
            "start": 62,
            "end": 67,
            "sot": {"home": 3, "away": 0},
            "da": {"home": 9, "away": 2},
        },
        "last_10min": {"start": 57, "end": 67, "sot": {"home": 4, "away": 1}},
    }
    row: dict[str, Any] = {
        "id": 10,
        "match_id": "555",
        "strategy_slot": 2,
        "strategy_key": "delta_5min",
        "team": "home",
        "value": 8.4,
        "minute": 67,
        "score": "1-0",
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "payload": payload,
    }
    row.update(extra)
    return row


ALERT = t.DEFAULT_TEMPLATES["alert"]
GOAL = t.DEFAULT_TEMPLATES["goal"]


@pytest.mark.parametrize(
    "row",
    [
        _row(),
        _row(strategy_key="pressure_index", value=72),
        _row(strategy_key="rule_of_three", value=2.3, team="away"),
        _row(strategy_key="delta_goal", value=1.2, payload={"form_bar": {"note": "Hot"}}),
        _row(strategy_key="kscore", team=None, payload={}),
        _row(home_team="A & <B>", payload={"league": 'L\'éague "x"'}),
    ],
)
def test_default_alert_template_matches_built_in(row: dict[str, Any]) -> None:
    assert t.render(ALERT, t.alert_values([row])) == format_alert_html(row)
    assert t.render(ALERT, t.alert_values([row], with_score=True)) == format_alert_html(
        row, with_score=True
    )


def test_default_alert_template_matches_built_in_joint_post() -> None:
    rows = [
        _row(),
        _row(id=11, strategy_slot=1, strategy_key="rule_of_three", value=2.1, team="away"),
    ]
    assert t.render(ALERT, t.alert_values(rows)) == format_joint_html(rows)
    rows = t.long_rows()
    assert t.render(ALERT, t.alert_values(rows)) == format_joint_html(rows)


def test_default_goal_template_matches_built_in() -> None:
    row = _row(
        state="Confirmed", detail={"goal_minute": 72, "fire_score": "1-0", "settle_score": "2-0"}
    )
    assert t.render(GOAL, t.goal_values(row)) == format_outcome_html(row)
    bare = _row(state="Confirmed", detail={})
    assert t.render(GOAL, t.goal_values(bare)) == format_outcome_html(bare)


def test_values_cover_every_tag() -> None:
    alert = t.alert_values([_row()])
    goal = t.goal_values(_row(state="Confirmed", detail={"goal_minute": 72}))
    for tag in t.TAGS:
        source = goal if "alert" not in tag.kinds else alert
        assert tag.name in source, tag.name
    assert alert["sot_home"] == "6"
    assert alert["possession_away"] == "38%"
    assert alert["favourite"] == "Arsenal"
    assert alert["team_odds"] == "1.85"
    assert alert["odds_draw"] == "3.60"
    assert alert["h2h_meetings"] == "8"
    assert alert["minute"] == "67′"
    assert alert["match_link"].endswith("?match=555")
    assert goal["goal_minute"] == "72′"


def test_joint_values_join_strategies_and_blank_team_when_both_sides() -> None:
    rows = [
        _row(),
        _row(id=11, strategy_slot=1, strategy_key="rule_of_three", value=2.1, team="away"),
    ]
    values = t.alert_values(rows)
    assert values["strategy_short"].count("+") == 1
    assert values["team"] == ""
    assert values["value"] == "2.1 · 8.4 / 12.0"


def test_everything_typed_and_every_value_is_escaped() -> None:
    row = _row(home_team="<b>Evil</b> & Co")
    out = t.render("<i>hi</i> & {home} **{away}**", t.alert_values([row]))
    assert out == "&lt;i&gt;hi&lt;/i&gt; &amp; &lt;b&gt;Evil&lt;/b&gt; &amp; Co <b>Chelsea</b>"


def test_backslash_gives_plain_characters() -> None:
    out = t.render("a\\_b \\*\\* \\{home\\}", {"home": "X"})
    assert out == "a_b ** {home}"


def test_line_with_only_empty_tags_is_dropped_and_separators_tidied() -> None:
    body = (
        "{home} vs {away} · {league} · {minute}\n_{country}_\n\n\n\nLink: {match_link}\n\n{stats}"
    )
    out = t.render(body, {"home": "A", "away": "B", "minute": "5′", "match_link": "x"})
    assert out == "A vs B · 5′\n\nLink: x"


def test_lines_without_tags_stay() -> None:
    assert t.render("Hello\n\nWorld", {}) == "Hello\n\nWorld"


@pytest.mark.parametrize(
    ("body", "kind", "needle"),
    [
        ("{nope}", "alert", "there's no {nope} tag"),
        ("{Home}", "alert", "{Home} should be written {home}"),
        ("{goal_minute}", "alert", "only works in the goal reply"),
        ("**open", "alert", "** isn't closed"),
        ("a_b", "alert", "_ isn't closed"),
        ("**a _b** c_", "alert", "overlap"),
        ("   ", "alert", "empty"),
        ("{}", "alert", "{} is empty"),
    ],
)
def test_check_explains_problems(body: str, kind: str, needle: str) -> None:
    problems = t.check(body, kind)
    assert problems
    assert any(needle in p.message for p in problems), problems


def test_check_accepts_defaults_and_goal_tags_in_goal() -> None:
    assert t.check(ALERT, "alert") == []
    assert t.check(GOAL, "goal") == []
    assert t.check("{goal_minute} {home}", "goal") == []


def test_validate_blocks_templates_too_long_for_a_caption() -> None:
    body = "{strategy_lines}\n{stats}\n" * 4
    problems = t.validate("paid", "alert", body)
    assert problems and "1,024" in problems[0]
    assert t.validate("discord", "alert", body) == []  # 2,000 on Discord


def test_no_templates_means_built_in_everywhere() -> None:
    texts = t.alert_texts([_row()], {}, caption="C", fallback="F")
    assert texts.paid.caption == "C" and texts.free.fallback == "F"
    assert texts.discord_paid == "C" and texts.discord_free == "C"
    assert not texts.paid.templated
    assert texts.fallbacks == []


def test_free_template_only_changes_free_and_its_discord() -> None:
    row = _row()
    caption, fallback = t.builtin_alert([row])
    texts = t.alert_texts(
        [row], {("free", "alert"): "Free: {home}\nJoin paid"}, caption=caption, fallback=fallback
    )
    assert texts.free.caption == "Free: Arsenal\nJoin paid"
    assert texts.free.templated
    assert texts.paid.caption == caption
    assert texts.discord_free == texts.free.caption
    assert texts.discord_paid == caption


def test_discord_template_covers_both_discord_channels() -> None:
    row = _row()
    caption, fallback = t.builtin_alert([row])
    texts = t.alert_texts(
        [row], {("discord", "alert"): "**{home}** {minute}"}, caption=caption, fallback=fallback
    )
    assert texts.discord_paid == texts.discord_free == "<b>Arsenal</b> 67′"
    assert texts.paid.caption == caption


def test_template_that_breaks_falls_back_and_is_reported() -> None:
    row = _row()
    caption, fallback = t.builtin_alert([row])
    texts = t.alert_texts(
        [row],
        {("paid", "alert"): "{nope}", ("free", "alert"): "{league}"},
        caption=caption,
        fallback=fallback,
    )
    assert texts.paid.caption == caption
    assert ("paid", "alert") in {(ch, kd) for ch, kd, _ in texts.fallbacks}
    assert texts.free.caption == "Premier League"


def test_template_empty_for_this_alert_falls_back() -> None:
    row = _row(payload={})
    caption, fallback = t.builtin_alert([row])
    texts = t.alert_texts(
        [row], {("paid", "alert"): "{league}"}, caption=caption, fallback=fallback
    )
    assert texts.paid.caption == caption
    assert "empty" in texts.fallbacks[0][2]


def test_too_long_for_a_caption_falls_back() -> None:
    row = _row()
    caption, fallback = t.builtin_alert([row])
    texts = t.alert_texts(
        [row], {("paid", "alert"): "x" * 1100}, caption=caption, fallback=fallback
    )
    assert texts.paid.caption == caption
    assert "1,024" in texts.fallbacks[0][2]


def test_goal_texts_per_channel() -> None:
    row = _row(
        state="Confirmed", detail={"goal_minute": 72, "fire_score": "1-0", "settle_score": "2-0"}
    )
    goals = t.goal_texts([row, row], {("free", "goal"): "⚽ {home} at {goal_minute}"})
    built_in = format_outcome_html(row)
    assert goals.paid == f"{built_in}\n\n{built_in}"
    assert goals.free == "⚽ Arsenal at 72′\n\n⚽ Arsenal at 72′"
    assert goals.discord_free == goals.free
    assert goals.discord_paid == goals.paid


@pytest.mark.parametrize(
    ("detail", "expected"),
    [
        ({"scoring_side": "away", "fire_score": "1-0", "settle_score": "1-1"}, "Chelsea"),
        ({"scoring_side": "home"}, "Arsenal"),
        ({"fire_score": "1-0", "settle_score": "2-0"}, "Arsenal"),  # older rows: from the score
        ({"fire_score": "1-0", "settle_score": "1-1"}, "Chelsea"),
        ({"fire_score": "1-0", "settle_score": "2-1"}, ""),  # both scored: can't tell
        ({}, ""),
    ],
)
def test_scoring_team(detail: dict[str, Any], expected: str) -> None:
    row = _row(state="Confirmed", detail={"goal_minute": 72, **detail})
    assert t.goal_values(row)["scoring_team"] == expected


def test_scorer_message_and_missing_scorer_line_drops() -> None:
    body = "{scoring_team} scores! ⚽\n{lede}"
    row = _row(state="Confirmed", detail={"goal_minute": 72, "scoring_side": "away"})
    assert t.render(body, t.goal_values(row)).startswith("Chelsea scores! ⚽\n")
    unknown = _row(state="Confirmed", detail={"goal_minute": 72})
    assert not t.render(body, t.goal_values(unknown)).startswith(" scores")
    assert t.check("{scoring_team}", "alert")  # goal reply only


def test_visible_length_counts_what_telegram_counts() -> None:
    assert t.visible_length("<b>a&amp;b</b>") == 3
    assert t.visible_length("⚽") == 1
    assert t.visible_length("😢") == 2  # UTF-16 pair


def test_preview_free_alert_shows_telegram_discord_and_x() -> None:
    out = t.preview("free", "alert", "**{home}** vs {away}", [_row()])
    assert out["problems"] == []
    assert out["telegram"] == "<b>Arsenal</b> vs Chelsea"
    assert out["discord"] == "**Arsenal** vs Chelsea"
    assert out["x"] == "Arsenal vs Chelsea"
    assert out["discord_follows"] is True
    assert out["fell_back"] is None
    assert out["limit"] == 1024


def test_preview_reports_problems_and_fallback() -> None:
    out = t.preview("paid", "alert", "{nope}", [_row()])
    assert out["problems"]
    assert out["fell_back"]
    assert out["telegram"] == format_alert_html(_row())


def test_preview_discord_goal() -> None:
    row = _row(state="Confirmed", detail={"goal_minute": 72})
    out = t.preview("discord", "goal", "GOAL {goal_minute}", [row])
    assert out["discord"] == "GOAL 72′"
    assert out["telegram"] == ""
    assert out["limit"] == 2000
