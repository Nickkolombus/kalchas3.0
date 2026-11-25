"""Shot-quality xG."""

from kalchas_core.match import MatchTimeline
from kalchas_core.match.snapshot import TeamStats
from kalchas_core.stats import flattened_to_minute_block, parse_statistics_payload
from kalchas_core.xg import match_xg, shot_quality_xg


def test_box_model_prices_penalties_and_shot_location() -> None:
    # Sporting v Man Utd, 2026-11-25 full time: 8 in the box (2 penalties), 3 outside.
    sporting = TeamStats(penalties=2, shots_inside_box=8, shots_outside_box=3)
    xg = shot_quality_xg(sporting)
    assert xg.source == "box"
    assert xg.value == 2.35  # 0.76*2 + 0.12*6 + 0.035*3


def test_falls_back_to_a_flat_price_per_shot_without_locations() -> None:
    team = TeamStats(shots_on_target=4, shots_off_target=6, penalties=1)
    xg = shot_quality_xg(team)
    assert xg.source == "shots"
    assert xg.value == 1.48  # 0.76 + 0.08*9


def test_fallback_reads_on_the_box_scale() -> None:
    # UNAN-Managua v Sport Sebaco, 43': Sebaco 7 on target, 4 off, no locations.
    assert shot_quality_xg(TeamStats(shots_on_target=7, shots_off_target=4)).value == 0.88


def test_penalties_never_push_box_shots_negative() -> None:
    xg = shot_quality_xg(TeamStats(penalties=1, shots_inside_box=0, shots_outside_box=0))
    assert xg.value == 0.76


def test_match_source_is_box_only_when_both_sides_have_locations() -> None:
    box = TeamStats(shots_inside_box=3, shots_outside_box=1)
    rough = TeamStats(shots_on_target=1)
    assert match_xg(box, box)[1] == "box"
    assert match_xg(box, rough)[1] == "shots"


def test_feed_to_timeline_keeps_absent_locations_unknown() -> None:
    def team_stats(stats: dict) -> TeamStats:
        block = flattened_to_minute_block(parse_statistics_payload(stats))
        snap = MatchTimeline.from_raw({"60": block}, 60).current
        assert snap is not None
        return snap.home

    plain = team_stats(
        {"home_team": {"on_target": 2, "off_target": 3}, "away_team": {"on_target": 1}}
    )
    assert plain.shots_inside_box is None
    assert plain.penalties == 0

    extended = team_stats(
        {
            "home_team": {
                "on_target": 4,
                "shots_inside_box": 8,
                "shots_outside_box": 3,
                "penalties": 2,
            },
            "away_team": {"on_target": 2, "shots_inside_box": 4, "shots_outside_box": 3},
        }
    )
    assert extended.shots_inside_box == 8
    assert extended.penalties == 2
    assert shot_quality_xg(extended).value == 2.35
