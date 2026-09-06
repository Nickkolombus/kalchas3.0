"""H2H stats and timing counts (Strategy 10 enrichment)."""

from __future__ import annotations

from kalchas_core.h2h import (
    H2HFixture,
    compute_h2h_stats,
    compute_timing_counts,
    dedup_fixtures,
    normalize_fixture,
)


def meeting(
    t1: int,
    t2: int,
    hs: int,
    aws: int,
    *,
    t1_home: bool = True,
    match_id: str = "",
) -> H2HFixture:
    if t1_home:
        return H2HFixture(
            match_id=match_id or f"{t1}-{t2}-{hs}-{aws}",
            home_team_id=t1,
            away_team_id=t2,
            home_score=hs,
            away_score=aws,
        )
    return H2HFixture(
        match_id=match_id or f"{t2}-{t1}-{hs}-{aws}",
        home_team_id=t2,
        away_team_id=t1,
        home_score=hs,
        away_score=aws,
    )


class TestComputeH2H:
    def test_empty(self) -> None:
        stats = compute_h2h_stats([], team1_id=1, team2_id=2)
        assert stats.ok is False
        assert stats.insufficient is True

    def test_attribution_by_id_not_name(self) -> None:
        fixtures = [
            meeting(1, 2, 2, 0),
            meeting(1, 2, 1, 1, t1_home=False),
            meeting(1, 2, 0, 3),
            meeting(1, 2, 2, 1),
            meeting(1, 2, 0, 0),
        ]
        stats = compute_h2h_stats(fixtures, team1_id=1, team2_id=2, team1_name="A", team2_name="B")
        assert stats.ok is True
        assert stats.sample == 5
        assert stats.insufficient is False
        assert stats.team1.wins == 2
        assert stats.team2.wins == 1
        assert stats.draws == 2
        assert stats.btts.count == 2
        assert stats.over_2_5.count == 2  # 2-0 no, 1-1 no, 0-3 yes, 2-1 yes, 0-0 no
        assert stats.avg_goals == 2.0

    def test_insufficient_sample_still_computes_counts(self) -> None:
        fixtures = [meeting(1, 2, 1, 0), meeting(1, 2, 2, 2)]
        stats = compute_h2h_stats(fixtures, team1_id=1, team2_id=2, min_sample=5)
        assert stats.ok is True
        assert stats.insufficient is True
        assert stats.reason == "insufficient_sample"
        assert stats.sample == 2

    def test_mismatched_ids_skipped_from_wl(self) -> None:
        fixtures = [
            meeting(1, 2, 1, 0),
            H2HFixture(match_id="x", home_team_id=9, away_team_id=8, home_score=3, away_score=0),
        ]
        stats = compute_h2h_stats(fixtures, team1_id=1, team2_id=2, min_sample=1)
        assert stats.sample == 2
        assert stats.attributed == 1
        assert stats.team1.wins == 1

    def test_dedup_by_match_id(self) -> None:
        a = meeting(1, 2, 1, 0, match_id="same")
        b = meeting(1, 2, 9, 9, match_id="same")
        assert len(dedup_fixtures([a, b])) == 1

    def test_normalize_nested_score(self) -> None:
        fx = normalize_fixture(
            {
                "match_id": "1",
                "home_team_id": 1,
                "away_team_id": 2,
                "score": {"home": 3, "away": 1},
            }
        )
        assert fx.home_score == 3
        assert fx.away_score == 1


class TestTiming:
    def test_none_without_events(self) -> None:
        assert compute_timing_counts([{"goal_events": []}]) is None
        assert compute_timing_counts([{}]) is None

    def test_late_and_early_patterns(self) -> None:
        fixtures = [
            {"goal_events": [{"minute": 80, "team": "home"}]},
            {"goal_events": [{"minute": 12, "team": "away"}, {"minute": 40, "team": "home"}]},
            {"goal_events": [{"minute": 5, "team": "home"}]},
        ]
        timing = compute_timing_counts(fixtures)
        assert timing is not None
        assert timing.sample == 3
        assert timing.late_goals.count == 1
        assert timing.early_goals_15.count == 2
        assert timing.btts_first_half.count == 1
        assert timing.first_goal_before_30.count == 2
