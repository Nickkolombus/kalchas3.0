"""parse_statistics_payload."""

from kalchas_core.stats import flattened_to_minute_block, parse_statistics_payload


def test_list_shape() -> None:
    flat = parse_statistics_payload(
        [
            {
                "shots_on_goal": 3,
                "shots": 5,
                "corner_kicks": 2,
                "attacks": 10,
                "dangerous_attacks": 4,
            },
            {
                "shots_on_goal": 1,
                "shots": 2,
                "corner_kicks": 0,
                "attacks": 6,
                "dangerous_attacks": 1,
            },
        ]
    )
    assert flat["home_sot"] == 3
    assert flat["home_sofft"] == 2
    assert flat["away_corners"] == 0


def test_dict_shape() -> None:
    flat = parse_statistics_payload(
        {
            "home_team": {"on_target": 2, "off_target": 1, "corners": 3},
            "away_team": {"on_target": 0, "off_target": 0, "corners": 1},
        }
    )
    assert flat["home_corners"] == 3
    block = flattened_to_minute_block(flat)
    assert block["shots_on_target"]["home"] == 2


def test_empty_falls_to_zeros() -> None:
    flat = parse_statistics_payload(None)
    assert flat["home_sot"] == 0
