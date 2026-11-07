from datetime import UTC, date, datetime

from kalchas_core.recap import (
    DAY_FIELDS,
    WEEK_FIELDS,
    build_daily,
    build_recap,
    call_story,
    caption_text,
    final_caption,
    group_signals,
    miss_notes,
    miss_story,
    normalize_texts,
    week_bounds,
)

WEEK = date(2026, 10, 26)


def _pair(home, away):
    return {"home": home, "away": away}


def _row(
    match_id,
    minute,
    *,
    home,
    away,
    team,
    state,
    day=28,
    key="delta_goal",
    value=1.1,
    fire="0-0",
    settle=None,
    goal=None,
    league="Botola Pro",
    stats=None,
    payload_extra=None,
):
    payload = {"league": league, **(stats or {}), **(payload_extra or {})}
    detail = {"fire_score": fire, "settle_score": settle, "goal_minute": goal}
    return {
        "match_id": match_id,
        "minute": minute,
        "strategy_key": key,
        "team": team,
        "value": value,
        "score": fire,
        "home_team": home,
        "away_team": away,
        "created_at": datetime(2026, 10, day, 20, 0, tzinfo=UTC),
        "payload": payload,
        "state": state,
        "detail": detail,
    }


OLIMPIA = _row(
    "olimpia",
    12,
    home="Olimpia",
    away="Cartaginés",
    team="home",
    state="Confirmed",
    key="delta_5min",
    value=9.5,
    settle="1-0",
    goal=13,
    league="Central American Cup",
    payload_extra={"last_5min": {"da": _pair(11, 2), "sot": _pair(2, 0), "corners": _pair(2, 0)}},
)
NOAH = _row(
    "noah",
    79,
    home="Noah",
    away="Syunik",
    team="home",
    state="Confirmed",
    fire="0-2",
    settle="1-2",
    goal=80,
    league="Cup - 1/8-finals",
    stats={"da": _pair(51, 21), "corners": _pair(10, 6), "sot": _pair(3, 4)},
)
FAR = _row(
    "far",
    76,
    home="FAR Rabat",
    away="IR Tanger",
    team="home",
    state="Confirmed",
    settle="1-0",
    goal=81,
    stats={"sot": _pair(7, 2), "sofft": _pair(8, 0), "da": _pair(41, 22)},
)
BRAGANTINO = _row(
    "brag",
    76,
    home="Bragantino",
    away="Chapecoense",
    team="away",
    state="Confirmed",
    fire="2-0",
    settle="3-0",
    goal=77,
    stats={"da": _pair(51, 27)},
)
KOZAKKEN = _row(
    "koz",
    75,
    home="Kozakken Boys",
    away="Utrecht",
    team="home",
    state="Expired",
    day=29,
    value=1.9,
    league="KNVB Beker - 1/32-finals",
    stats={
        "possession": _pair(23, 77),
        "sot": _pair(3, 2),
        "sofft": _pair(11, 3),
        "da": _pair(30, 28),
        "corners": _pair(5, 3),
    },
)
VENLO = _row(
    "venlo",
    69,
    home="Venlo",
    away="Vitesse",
    team="home",
    state="Expired",
    value=1.7,
    league="KNVB Beker",
    stats={"da": _pair(46, 47)},
)
OPEN = _row("open", 50, home="A", away="B", team="home", state=None)


def recap():
    rows = [OLIMPIA, NOAH, FAR, BRAGANTINO, KOZAKKEN, VENLO, OPEN]
    return build_recap(rows, week_start=WEEK, thresholds={"delta_goal": 1.0, "delta_5min": 8.0})


def test_week_bounds_is_last_full_monday_to_sunday():
    assert week_bounds(date(2026, 11, 2)) == (date(2026, 10, 26), date(2026, 11, 1))
    assert week_bounds(date(2026, 11, 8)) == (date(2026, 10, 26), date(2026, 11, 1))


def test_alerts_on_the_same_match_minute_are_one_signal():
    twin = {**OLIMPIA, "strategy_key": "pressure_index", "state": "Expired"}
    signals = group_signals([OLIMPIA, twin, NOAH])
    assert len(signals) == 2
    assert next(s for s in signals if s.match_id == "olimpia").result == "goal"


def test_totals_leave_open_signals_out():
    data = recap()
    assert (data["total"], data["goals"], data["misses"]) == (6, 4, 2)


def test_wait_buckets_and_days():
    data = recap()
    assert [w["count"] for w in data["waits"]] == [3, 1, 0, 0]
    assert data["fastest"] == 1
    wed = next(d for d in data["days"] if d["day"] == "Wed")
    assert (wed["goals"], wed["total"]) == (4, 5)


def test_calls_prefer_the_flagged_side_scoring_then_speed():
    data = recap()
    picked = [c["match_id"] for c in data["calls"]]
    # Olimpia and Noah both scored a minute later; Noah led by more, so first.
    # Bragantino's goal came as fast, but by the side we didn't flag.
    assert picked == ["noah", "olimpia", "far"]
    assert data["honourable"]["match_id"] == "brag"


def test_miss_is_the_most_confident_one():
    assert recap()["miss"]["match_id"] == "koz"


def test_confidence_is_relative_to_each_strategy_threshold():
    rows = [
        {**KOZAKKEN, "value": 1.5},
        _row(
            "d5", 30, home="X", away="Y", team="home", state="Expired", key="delta_5min", value=11.9
        ),
    ]
    data = build_recap(rows, week_start=WEEK, thresholds={"delta_goal": 1.0, "delta_5min": 8.0})
    assert data["miss"]["match_id"] == "koz"  # 1.5x its bar beats 11.9 / 8 = 1.49x


def test_call_story_reads_like_a_person_wrote_it():
    data = recap()
    noah, olimpia, far = data["calls"]
    assert call_story(olimpia) == (
        "Still 0–0, and Olimpia were all over it: 11 dangerous attacks to 2 in the last five "
        "minutes. We posted at 12′. They scored a minute later."
    )
    assert call_story(noah).startswith(
        "Two goals down, but Noah were the side pushing: 51 dangerous"
    )
    assert call_story(far).endswith("We posted at 76′. They scored 5 minutes later.")


def test_other_side_goal_is_worded_honestly():
    assert call_story(recap()["honourable"]).endswith("The goal came a minute later.")


def test_miss_story_and_notes():
    miss = recap()["miss"]
    assert miss_story(miss) == (
        "Our most confident call of the week. Kozakken Boys had 30 dangerous attacks to 28 "
        "when we posted at 75′. But they had just 23% of the ball. No goal came."
    )
    notes = miss_notes(miss)
    assert any("Cup tie" in note for note in notes)
    assert any("23%" in note for note in notes)
    assert "11 shots off target against 3 on it." in notes


def test_stats_are_from_the_flagged_side():
    away = _row(
        "a",
        60,
        home="H",
        away="A",
        team="away",
        state="Expired",
        stats={"possession": _pair(70, 30)},
    )
    miss = build_recap([away], week_start=WEEK)["miss"]
    assert miss["stats"][0] == {"label": "Possession", "own": 30, "other": 70, "percent": True}


def test_drafts_leave_the_lesson_empty_and_caption_adds_it():
    data = recap()
    assert data["texts"]["lesson"] == ""
    assert all(data["texts"][f"call_{i}"] for i in (1, 2, 3))
    caption = caption_text(data, lesson="Lower-league form doesn't travel.")
    assert "4 of 6 signals found a goal." in caption
    assert "Lower-league form doesn't travel." in caption
    assert "26 Oct – 1 Nov" in caption


def test_final_caption_works_the_lesson_in_above_the_sign_off():
    texts = {
        "caption": "Head.\n\nBody.\n\nEvery signal goes out live.",
        "lesson": "Form travels badly.",
    }
    assert (
        final_caption(texts)
        == "Head.\n\nBody.\n\nForm travels badly.\n\nEvery signal goes out live."
    )
    assert (
        final_caption({**texts, "caption": texts["caption"] + " Form travels badly."}).count(
            "Form travels badly."
        )
        == 1
    )
    assert final_caption({**texts, "lesson": ""}) == texts["caption"]


def test_one_busy_day_is_not_also_the_worst():
    rows = [
        _row(f"m{i}", 60 + i, home="H", away="A", team="home", state="Expired") for i in range(3)
    ]
    data = build_recap(rows, week_start=WEEK)
    assert data["best_day"]["day"] == "Wed"
    assert data["worst_day"] is None


def test_empty_week():
    data = build_recap([], week_start=WEEK)
    assert data["total"] == 0
    assert data["calls"] == [] and data["miss"] is None
    assert data["texts"]["cover_line"] == ""


def test_a_goal_in_the_signal_minute_is_worded_as_such():
    same = {**FAR, "match_id": "same", "detail": {**FAR["detail"], "goal_minute": 76}}
    data = build_recap([same], week_start=WEEK)
    assert data["fastest"] == 0
    assert data["texts"]["cover_line"] == "The quickest goal came the same minute as the signal."
    assert "goal the same minute as the signal" in data["texts"]["x"]
    assert call_story(data["calls"][0]).endswith("They scored that same minute.")


def test_every_field_has_a_draft_so_every_word_is_editable():
    week = recap()
    day = build_daily([OLIMPIA, NOAH, FAR], day=date(2026, 10, 28))
    assert {key for key, *_ in WEEK_FIELDS} <= set(week["texts"])
    assert {key for key, *_ in DAY_FIELDS} <= set(day["texts"])
    assert week["texts"]["headline_number"] == "4 of 6"
    assert week["texts"]["period_dates"] == "Mon 26 Oct – Sun 1 Nov"


def test_daily_has_up_to_four_calls_and_no_miss():
    data = build_daily([OLIMPIA, NOAH, FAR, BRAGANTINO, KOZAKKEN], day=date(2026, 10, 28))
    assert data["kind"] == "day" and data["days"] == []
    assert data["miss"] is None
    assert [c["match_id"] for c in data["calls"]] == ["noah", "olimpia", "far", "brag"]
    texts = data["texts"]
    assert texts["period_dates"] == "Wednesday 28 Oct"
    assert texts["fastest_title"] == "Fastest: 1 min"
    assert texts["call_1"] == "Two goals down. We posted at 79′; they scored a minute later."
    assert "yesterday" in texts["x"]


def test_one_call_per_match_naming_every_signal():
    first = {**NOAH, "minute": 60, "detail": {**NOAH["detail"]}}
    data = build_recap([first, NOAH], week_start=WEEK)
    assert len(data["calls"]) == 1
    assert data["calls"][0]["flags"] == [60, 79]
    assert data["texts"]["feature_line"] == "Flagged at 60′ and 79′ while 2–0 down. Goal at 80′."
    assert data["texts"]["call_1"].endswith("We flagged them at 60′ and 79′. The goal came at 80′.")


def test_crests_come_from_the_signal():
    row = {
        **FAR,
        "payload": {
            **FAR["payload"],
            "home_logo": "https://x/h.png",
            "away_logo": "https://x/a.png",
        },
    }
    call = build_recap([row], week_start=WEEK)["calls"][0]
    assert (call["home_logo"], call["away_logo"]) == ("https://x/h.png", "https://x/a.png")


def test_old_drafts_keep_their_words_under_the_new_fields():
    data = recap()
    old = {"calls": ["a", "b", "c"], "honourable": "Hon.", "lesson": "L.", "cover_line": "Mine."}
    texts = normalize_texts(old, data)
    assert (texts["call_1"], texts["call_3"], texts["calls_footer"]) == ("a", "c", "Hon.")
    assert texts["cover_line"] == "Mine." and texts["lesson"] == "L."
    assert texts["kicker"] == "Every signal we sent"


def test_daily_can_keep_only_some_strategies():
    rows = [OLIMPIA, FAR, NOAH]
    everything = build_daily(rows, day=date(2026, 10, 28))
    assert everything["goals"] == 3 and everything["strategy_filter"] == []

    pressure = build_daily(rows, day=date(2026, 10, 28), strategies=["delta_5min"])
    assert pressure["goals"] == 1 and pressure["total"] == 1
    assert [c["home"] for c in pressure["calls"]] == ["Olimpia"]
    assert pressure["strategy_filter"] == ["delta_5min"]
