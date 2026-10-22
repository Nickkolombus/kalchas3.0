"""Team form enrichment (Strategy 9) — pure metrics and insight strings."""

from kalchas_core.form.insights import (
    build_form_insights,
    comparative_insights,
    goal_form_insights,
    position_insights,
    prioritize_insights,
    streak_insights,
)
from kalchas_core.form.metrics import (
    DEFAULT_FORM_WINDOW,
    EMPTY_FORM,
    MIN_FIXTURES_FOR_FORM,
    PLAYED_STATUS_CODES,
    FinishedFixture,
    Streak,
    TeamForm,
    VenueRecord,
    calculate_team_form,
    form_cache_key,
    form_cache_payload,
    form_from_cache_payload,
    played_fixtures,
)

__all__ = [
    "DEFAULT_FORM_WINDOW",
    "EMPTY_FORM",
    "MIN_FIXTURES_FOR_FORM",
    "PLAYED_STATUS_CODES",
    "FinishedFixture",
    "Streak",
    "TeamForm",
    "VenueRecord",
    "build_form_insights",
    "calculate_team_form",
    "comparative_insights",
    "form_cache_key",
    "form_cache_payload",
    "form_from_cache_payload",
    "goal_form_insights",
    "played_fixtures",
    "position_insights",
    "prioritize_insights",
    "streak_insights",
]
