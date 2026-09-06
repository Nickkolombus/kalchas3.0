"""Football API adapter package."""

from kalchas_football.client import FootballAPIClient, LiveMatch, RateLimiter, live_match_from_event

__all__ = [
    "FootballAPIClient",
    "LiveMatch",
    "RateLimiter",
    "live_match_from_event",
]