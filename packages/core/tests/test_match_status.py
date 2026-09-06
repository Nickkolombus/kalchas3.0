"""Match phase / finished detection."""

from __future__ import annotations

from kalchas_core.match_status import (
    MatchPhase,
    infer_phase,
    is_live_phase,
    is_match_finished,
    is_match_live,
    is_truly_finished_phase,
    normalize_score,
)


class TestInferPhase:
    def test_halftime_with_match_live_zero_is_not_finished(self) -> None:
        phase = infer_phase(
            status_short="HT",
            status_long="Half Time",
            minute=45,
            match_live="0",
        )
        assert phase is MatchPhase.HALF_TIME
        assert not is_truly_finished_phase(phase)
        assert is_live_phase(phase)

    def test_ft_is_finished(self) -> None:
        phase = infer_phase(status_short="FT", status_long="Finished", minute=90, match_live="0")
        assert phase is MatchPhase.FINISHED
        assert is_truly_finished_phase(phase)

    def test_second_half_not_finished(self) -> None:
        phase = infer_phase(status_short="2H", minute=60, match_live="1")
        assert phase is MatchPhase.SECOND_HALF
        assert not is_truly_finished_phase(phase)

    def test_injury_time_still_second_half(self) -> None:
        phase = infer_phase(status_short="2H", status_long="90+5", minute=95, match_live="1")
        assert phase is MatchPhase.SECOND_HALF

    def test_aet_is_finished(self) -> None:
        assert infer_phase(status_short="AET", minute=120) is MatchPhase.FINISHED

    def test_pen_short_code_is_finished(self) -> None:
        assert infer_phase(status_short="PEN", minute=120) is MatchPhase.FINISHED


class TestIsMatchFinished:
    def test_ft_short_code(self) -> None:
        assert is_match_finished(status_short="FT", minute=105) is True

    def test_ft_in_stoppage_returns_false(self) -> None:
        assert is_match_finished(status_short="FT", minute=92) is False

    def test_ht_short_alone_is_not_finished(self) -> None:
        assert is_match_finished(status_short="HT") is False

    def test_ht_with_half_time_long_reports_finished(self) -> None:
        """Pinned defect: long-status tokens fire even when short code is HT."""
        assert is_match_finished(status_short="HT", status_long="Half Time") is True

    def test_half_time_token_alone_reports_finished(self) -> None:
        """Pinned defect: FINISHED_TOKENS includes 'half time'."""
        assert is_match_finished(status_long="Half Time") is True

    def test_is_match_live(self) -> None:
        assert is_match_live("HT") is True
        assert is_match_live("FT") is False


class TestNormalizeScore:
    def test_dict_and_string(self) -> None:
        assert normalize_score({"home": 1, "away": 0}) == "1-0"
        assert normalize_score("2-2") == "2-2"
        assert normalize_score(None) == ""
