"""Normalise football-API statistics payloads into timeline-friendly counters."""

from __future__ import annotations

from typing import Any


def parse_statistics_payload(
    stats: Any,
    home_possession: int = 50,
    away_possession: int = 50,
) -> dict[str, int]:
    """Flatten API/SSOT statistics into per-side counters.

    Accepts the three shapes used in 2.2 (nested home_team dict, two-element
    list, or anything else → zeros).
    """
    if isinstance(stats, dict) and "home_team" in stats and "away_team" in stats:
        home_stats = stats["home_team"]
        away_stats = stats["away_team"]
        return {
            "home_sot": int(home_stats.get("on_target", 0)),
            "away_sot": int(away_stats.get("on_target", 0)),
            "home_sofft": int(home_stats.get("off_target", 0)),
            "away_sofft": int(away_stats.get("off_target", 0)),
            "home_corners": int(home_stats.get("corners", 0)),
            "away_corners": int(away_stats.get("corners", 0)),
            "home_attacks": int(home_stats.get("attacks", 0)),
            "away_attacks": int(away_stats.get("attacks", 0)),
            "home_dangerous_attacks": int(home_stats.get("dangerous_attacks", 0)),
            "away_dangerous_attacks": int(away_stats.get("dangerous_attacks", 0)),
            "home_possession": home_possession,
            "away_possession": away_possession,
        }

    if isinstance(stats, list) and len(stats) >= 2:
        home_stats = stats[0]
        away_stats = stats[1]
        return {
            "home_sot": int(home_stats.get("shots_on_goal", 0)),
            "away_sot": int(away_stats.get("shots_on_goal", 0)),
            "home_sofft": int(home_stats.get("shots", 0)) - int(home_stats.get("shots_on_goal", 0)),
            "away_sofft": int(away_stats.get("shots", 0)) - int(away_stats.get("shots_on_goal", 0)),
            "home_corners": int(home_stats.get("corner_kicks", 0)),
            "away_corners": int(away_stats.get("corner_kicks", 0)),
            "home_attacks": int(home_stats.get("attacks", 0)),
            "away_attacks": int(away_stats.get("attacks", 0)),
            "home_dangerous_attacks": int(home_stats.get("dangerous_attacks", 0)),
            "away_dangerous_attacks": int(away_stats.get("dangerous_attacks", 0)),
            "home_possession": home_possession,
            "away_possession": away_possession,
        }

    return {
        "home_sot": 0,
        "away_sot": 0,
        "home_sofft": 0,
        "away_sofft": 0,
        "home_corners": 0,
        "away_corners": 0,
        "home_attacks": 0,
        "away_attacks": 0,
        "home_dangerous_attacks": 0,
        "away_dangerous_attacks": 0,
        "home_possession": home_possession,
        "away_possession": away_possession,
    }


def flattened_to_minute_block(flat: dict[str, int]) -> dict[str, dict[str, int]]:
    """Convert flat counters into the ``MatchTimeline.from_raw`` minute shape."""
    return {
        "shots_on_target": {
            "home": flat.get("home_sot", 0),
            "away": flat.get("away_sot", 0),
        },
        "shots_off_target": {
            "home": flat.get("home_sofft", 0),
            "away": flat.get("away_sofft", 0),
        },
        "corners": {
            "home": flat.get("home_corners", 0),
            "away": flat.get("away_corners", 0),
        },
        "attacks": {
            "home": flat.get("home_attacks", 0),
            "away": flat.get("away_attacks", 0),
        },
        "dangerous_attacks": {
            "home": flat.get("home_dangerous_attacks", 0),
            "away": flat.get("away_dangerous_attacks", 0),
        },
        "possession": {
            "home": flat.get("home_possession", 50),
            "away": flat.get("away_possession", 50),
        },
    }
