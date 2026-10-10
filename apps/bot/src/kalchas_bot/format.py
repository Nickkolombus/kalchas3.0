"""HTML Telegram alert caption from an outbox row.

Crests go on the photo. This module is caption-only: strategy, firing team,
clock, last-5-minute counts for Δ5, H2H when the sample is at least 5.
"""

from __future__ import annotations

import html
import json
from collections.abc import Mapping
from typing import Any

from kalchas_core.h2h import DEFAULT_MIN_SAMPLE
from kalchas_core.strategies.omega import DEFAULT_ANGLE_SCALE, alert_theta_degrees
from kalchas_core.weights import short_label_for

ALERT_NAMES: dict[str, str] = {
    "rule_of_three": "Unrealised goals",
    "delta_5min": "5-minute pressure",
    "pressure_index": "Sustained pressure",
    "delta_goal": "League Bar",
    "npei": "Efficiency",
    "omega": "Omega",
    "kscore": "K-Score",
}

# Ceiling is a display cap (x / cap). None means show the number only.
ALERT_CEILING: dict[str, tuple[float | None, int, str]] = {
    "rule_of_three": (None, 1, ""),
    "delta_5min": (12.0, 1, ""),
    "pressure_index": (100.0, 0, ""),
    "delta_goal": (10.0, 1, ""),
    "npei": (100.0, 0, ""),
    "omega": (None, 0, "°"),
    "kscore": (100.0, 0, ""),
}


def format_alert_html(row: Mapping[str, Any], *, with_score: bool = False) -> str:
    """Telegram HTML parse_mode caption. Team names are escaped."""
    payload = _payload(row.get("payload"))
    home = _esc(row.get("home_team"))
    away = _esc(row.get("away_team"))
    key = str(row.get("strategy_key") or "")
    short = _esc(short_label_for(key))
    name = _esc(ALERT_NAMES.get(key) or short)
    league = _esc(payload.get("league") or "")
    minute = _minute(row.get("minute"))

    lines = [_title_line(short, name, row, key, payload)]
    lines.append(_versus_line(row, home, away, minute, with_score=with_score))
    if league:
        lines.append(f"<i>{league}</i>")

    stats = _stat_block(key, payload, row.get("minute"))
    if stats:
        lines.append("")
        lines.extend(stats)

    h2h = _h2h_lines(payload, home, away)
    if h2h:
        lines.append("")
        lines.extend(h2h)
    return "\n".join(lines)


def _title_line(
    short: str,
    name: str,
    row: Mapping[str, Any],
    key: str,
    payload: Mapping[str, Any],
) -> str:
    shown = _value_over_ceiling(row.get("value"), key=key, payload=payload)
    if short == name:
        return f"<b>{short}</b>: {shown}" if shown else f"<b>{short}</b>"
    if shown:
        return f"<b>{short}</b> ({name}): {shown}"
    return f"<b>{short}</b> ({name})"


def _versus_line(
    row: Mapping[str, Any],
    home: str,
    away: str,
    minute: str,
    *,
    with_score: bool,
) -> str:
    side = str(row.get("team") or "").lower()
    home_html = f"<b>{home}</b>" if side == "home" else home
    away_html = f"<b>{away}</b>" if side == "away" else away
    parts = [f"{home_html} vs {away_html}"]
    if with_score:
        score = _score(row.get("score"))
        if score:
            parts.append(score)
    if minute:
        parts.append(minute)
    return " · ".join(parts)


def _stat_block(key: str, payload: Mapping[str, Any], minute: object) -> list[str]:
    if key == "delta_5min":
        window = payload.get("last_5min")
        if not isinstance(window, Mapping):
            return []
        start = _minute_int(window.get("start"))
        end = _minute_int(window.get("end"))
        if end is None:
            end = _minute_int(minute)
        if start is not None and end is not None:
            heading = f"<b>Last 5 mins ({start}′-{end}′):</b>"
        else:
            heading = "<b>Last 5 mins:</b>"
        rows = _stat_rows(window)
        return [heading, *rows] if rows else []
    rows = _stat_rows(payload)
    return rows


def _stat_rows(block: Mapping[str, Any]) -> list[str]:
    rows: list[str] = []
    for key, label, percent in (
        ("sot", "SOT", False),
        ("sofft", "SOFFT", False),
        ("da", "DA", False),
        ("corners", "Corners", False),
        ("possession", "Possession", True),
    ):
        line = _pair_line(block.get(key), label, percent=percent)
        if line:
            rows.append(line)
    return rows


def _pair_line(raw: object, label: str, *, percent: bool) -> str:
    if not isinstance(raw, Mapping):
        return ""
    try:
        home = int(raw.get("home") or 0)
        away = int(raw.get("away") or 0)
    except (TypeError, ValueError):
        return ""
    if home == 0 and away == 0:
        return ""
    return f"{label}: {_bold_bigger(home, away, percent=percent)}"


def _bold_bigger(home: int, away: int, *, percent: bool) -> str:
    home_s = f"{home}%" if percent else str(home)
    away_s = f"{away}%" if percent else str(away)
    if home > away:
        return f"<b>{home_s}</b> - {away_s}"
    if away > home:
        return f"{home_s} - <b>{away_s}</b>"
    return f"{home_s} - {away_s}"


def _h2h_lines(payload: Mapping[str, Any], home: str, away: str) -> list[str]:
    raw = payload.get("h2h")
    if not isinstance(raw, Mapping):
        return []
    try:
        sample = int(raw.get("sample") or 0)
        home_avg = float(raw.get("home_avg"))
        away_avg = float(raw.get("away_avg"))
    except (TypeError, ValueError):
        return []
    if sample < DEFAULT_MIN_SAMPLE:
        return []
    lines = [
        f"· {home} average {home_avg:.1f} goals per meeting vs {away} {away_avg:.1f}, "
        f"last {sample}."
    ]
    try:
        wins = int(raw.get("home_wins"))
        draws = int(raw.get("draws"))
        losses = int(raw.get("away_wins"))
    except (TypeError, ValueError):
        return lines
    lines.append(f"· {wins}W-{draws}D-{losses}L for {home}.")
    return lines


def _payload(raw: object) -> Mapping[str, Any]:
    if isinstance(raw, str) and raw.strip():
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    if isinstance(raw, Mapping):
        return raw
    return {}


def _esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def _score(raw: object) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    return text.replace("–", "-")


def _minute_int(raw: object) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _plain_minute(raw: object) -> str:
    value = _minute_int(raw)
    if value is None:
        return f"{raw}′" if raw not in (None, "") else ""
    return f"{value}′"


def _minute(raw: object) -> str:
    return _plain_minute(raw)


def _value_over_ceiling(
    raw: object, *, key: str, payload: Mapping[str, Any]
) -> str:
    if raw is None or raw == "":
        return ""
    try:
        numeric = float(raw)
    except (TypeError, ValueError):
        return ""
    ceiling, digits, suffix = ALERT_CEILING.get(key, (None, 1, ""))
    if key == "omega":
        k_scale = DEFAULT_ANGLE_SCALE
        theta: float | None = None
        raw_k = payload.get("k_scale")
        if raw_k is not None:
            try:
                k_scale = float(raw_k)
            except (TypeError, ValueError):
                pass
        raw_th = payload.get("theta")
        if raw_th is not None:
            try:
                theta = float(raw_th)
            except (TypeError, ValueError):
                theta = None
        numeric = alert_theta_degrees(numeric, k_scale, theta=theta)
        digits = 0
        suffix = "°"
    if digits <= 0:
        shown = f"{numeric:.0f}{suffix}"
        cap = f"{ceiling:.0f}{suffix}" if ceiling is not None else ""
    else:
        shown = f"{numeric:.{digits}f}{suffix}"
        cap = f"{ceiling:.{digits}f}{suffix}" if ceiling is not None else ""
    if cap:
        return f"{shown} / {cap}"
    return shown
