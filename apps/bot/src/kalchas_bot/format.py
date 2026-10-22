"""HTML Telegram captions from an outbox row.

Crests go on the photo. Fire captions: strategy, firing team, clock,
last-5-minute counts for Δ5, last-10-minute counts for Δ10 and Ω, H2H
when the sample is at least 5. Outcome replies: fire lede plus GOAL /
No goal under the original fire message.
"""

from __future__ import annotations

import html
import json
from collections.abc import Mapping, Sequence
from typing import Any

from kalchas_core.alert_outcomes import DEFAULT_RULES, rule_for_alert
from kalchas_core.h2h import DEFAULT_MIN_SAMPLE
from kalchas_core.strategies.omega import DEFAULT_ANGLE_SCALE, alert_theta_degrees
from kalchas_core.weights import short_label_for

ALERT_NAMES: dict[str, str] = {
    "rule_of_three": "Unrealised goals",
    "delta_5min": "5-minute pressure",
    "pressure_index": "Sustained pressure",
    "delta_goal": "Form Bar",
    "npei": "Efficiency",
    "omega": "Omega",
    "kscore": "K-Score",
}

# Joint posts use one window. Δ5′ + UrG is the only pair that stays on 5 minutes.
_JOINT_FIVE_MINUTE = frozenset({"delta_5min", "rule_of_three"})

# Ceiling is a display cap (x / cap). None means show the number only.
ALERT_CEILING: dict[str, tuple[float | None, int, str]] = {
    "rule_of_three": (None, 1, ""),
    "delta_5min": (12.0, 1, ""),
    "pressure_index": (100.0, 0, ""),
    "delta_goal": (None, 1, " behind pace"),
    "npei": (100.0, 0, ""),
    "omega": (None, 0, "°"),
    "kscore": (100.0, 0, ""),
}


def format_alert_html(
    row: Mapping[str, Any],
    *,
    with_score: bool = False,
    compact: bool = False,
) -> str:
    """Telegram HTML parse_mode caption. Team names are escaped.

    ``compact`` is the fire lede only (versus, league, title) for outcome replies.
    """
    payload = _payload(row.get("payload"))
    home = _esc(row.get("home_team"))
    away = _esc(row.get("away_team"))
    key = str(row.get("strategy_key") or "")
    short = _esc(short_label_for(key))
    name = _esc(ALERT_NAMES.get(key) or short)
    league = _esc(payload.get("league") or "")
    minute = _minute(row.get("minute"))
    side = _trigger_side(row, payload)
    trigger = _trigger_name(side, home, away)

    lines = [_versus_line(side, home, away, minute, with_score=with_score, score=row.get("score"))]
    if league:
        lines.append(f"<i>{league}</i>")
    lines.append(_title_line(short, name, row, key, payload, trigger=trigger))

    if compact:
        return "\n".join(lines)

    stats = _stat_block(key, payload, row.get("minute"))
    if stats:
        lines.append("")
        lines.extend(stats)

    h2h = _h2h_lines(payload, home, away, side=side)
    if h2h:
        lines.append("")
        lines.extend(h2h)
    return "\n".join(lines)


def joint_window_span(keys: Sequence[str]) -> int:
    """10-minute delta for a joint post. 5 minutes only for exactly Δ5′ and UrG."""
    present = {str(key) for key in keys if key}
    if present == _JOINT_FIVE_MINUTE:
        return 5
    return 10


def format_joint_html(
    rows: Sequence[Mapping[str, Any]],
    *,
    with_score: bool = False,
) -> str:
    """One caption for every strategy that fired on the same match minute."""
    if len(rows) == 1:
        return format_alert_html(rows[0], with_score=with_score)
    ordered = sorted(rows, key=_strategy_sort_key)
    first = ordered[0]
    payload = _merged_payload(ordered)
    home = _esc(first.get("home_team"))
    away = _esc(first.get("away_team"))
    league = _esc(payload.get("league") or "")
    minute = _minute(first.get("minute"))
    sides = {_trigger_side(row, _payload(row.get("payload"))) for row in ordered}
    sides.discard("")

    lines = [
        _versus_line(
            "",
            home,
            away,
            minute,
            with_score=with_score,
            score=first.get("score"),
            bold_sides=sides,
        )
    ]
    if league:
        lines.append(f"<i>{league}</i>")
    for row in ordered:
        row_payload = _payload(row.get("payload"))
        key = str(row.get("strategy_key") or "")
        short = _esc(short_label_for(key))
        name = _esc(ALERT_NAMES.get(key) or short)
        side = _trigger_side(row, row_payload)
        trigger = _trigger_name(side, home, away)
        lines.append(_title_line(short, name, row, key, row_payload, trigger=trigger))

    span = joint_window_span([str(row.get("strategy_key") or "") for row in ordered])
    window_key = "last_5min" if span == 5 else "last_10min"
    stats = _window_stat_lines(payload.get(window_key), first.get("minute"), span=span)
    if stats:
        lines.append("")
        lines.extend(stats)

    h2h_side = next(iter(sides)) if len(sides) == 1 else ""
    h2h = _h2h_lines(payload, home, away, side=h2h_side)
    if h2h:
        lines.append("")
        lines.extend(h2h)
    return "\n".join(lines)


def format_outcome_html(row: Mapping[str, Any]) -> str:
    """Reply under the original fire: GOAL at the settle minute, or No goal."""
    detail = _payload(row.get("detail"))
    payload = _payload(row.get("payload"))
    if not payload.get("league") and detail.get("league"):
        payload = {**payload, "league": detail.get("league")}
    home = _esc(row.get("home_team") or detail.get("home_team"))
    away = _esc(row.get("away_team") or detail.get("away_team"))
    key = str(row.get("strategy_key") or "")
    short = _esc(short_label_for(key))
    side = str(row.get("team") or detail.get("team") or "").lower()
    trigger = _trigger_name(side if side in ("home", "away") else "", home, away)
    state = str(row.get("state") or "")
    fire = _score(detail.get("fire_score"))
    settle = _score(detail.get("settle_score"))
    goal_at = _minute_int(detail.get("goal_minute"))
    settle_at = _minute_int(detail.get("settle_minute"))
    if state == "Confirmed":
        clock = _plain_minute(goal_at if goal_at is not None else settle_at)
        head = f"GOAL at {clock}" if clock else "GOAL"
        if fire and settle:
            head = f"{head} · {fire} → {settle}"
        elif settle:
            head = f"{head} · {settle}"
        fire_minute = row.get("minute")
        if fire_minute is None:
            fire_minute = detail.get("fire_minute")
        lede = format_alert_html(
            {
                "home_team": row.get("home_team") or detail.get("home_team"),
                "away_team": row.get("away_team") or detail.get("away_team"),
                "minute": fire_minute,
                "strategy_key": key,
                "team": row.get("team") or detail.get("team"),
                "value": row.get("value"),
                "payload": payload,
            },
            compact=True,
        )
        return f"{lede}\n\n⚽ {head}"
    window = _success_window(row, detail)
    if window is None:
        head = "No goal arrived"
    else:
        head = f"No goal arrived within {_plain_minute(window)}"
    if trigger:
        return f"{head}\n<b>{short}</b> for <b>{trigger}</b>"
    return f"{head}\n<b>{short}</b>"


def _success_window(row: Mapping[str, Any], detail: Mapping[str, Any]) -> int | None:
    if detail.get("infinite_ttl"):
        return None
    stored = _minute_int(detail.get("success_window_minutes"))
    if stored is not None:
        return stored
    key = str(row.get("strategy_key") or "") or None
    rule = rule_for_alert(strategy_slot=None, strategy_key=key, rules=DEFAULT_RULES)
    if rule.infinite_ttl:
        return None
    return int(rule.success_window_minutes)


def _trigger_side(row: Mapping[str, Any], payload: Mapping[str, Any]) -> str:
    side = str(row.get("team") or payload.get("team") or "").lower()
    if side in ("home", "away"):
        return side
    return ""


def _trigger_name(side: str, home: str, away: str) -> str:
    if side == "home":
        return home
    if side == "away":
        return away
    return ""


def _title_line(
    short: str,
    name: str,
    row: Mapping[str, Any],
    key: str,
    payload: Mapping[str, Any],
    *,
    trigger: str,
) -> str:
    shown = _value_over_ceiling(row.get("value"), key=key, payload=payload)
    if short == name:
        head = f"<b>{short}</b>: {shown}" if shown else f"<b>{short}</b>"
    elif shown:
        head = f"<b>{short}</b> ({name}): {shown}"
    else:
        head = f"<b>{short}</b> ({name})"
    if trigger:
        return f"{head} for <b>{trigger}</b>"
    return head


def _strategy_sort_key(row: Mapping[str, Any]) -> tuple[int, int]:
    try:
        slot = int(row.get("strategy_slot") or 0)
    except (TypeError, ValueError):
        slot = 0
    try:
        alert_id = int(row.get("id") or 0)
    except (TypeError, ValueError):
        alert_id = 0
    return slot, alert_id


def _merged_payload(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for row in rows:
        payload = _payload(row.get("payload"))
        for key, value in payload.items():
            if value not in (None, "", {}, []):
                merged[key] = value
    return merged


def _versus_line(
    side: str,
    home: str,
    away: str,
    minute: str,
    *,
    with_score: bool,
    score: object = None,
    bold_sides: set[str] | None = None,
) -> str:
    bold = bold_sides if bold_sides is not None else {side} if side else set()
    home_html = f"<b>{home}</b>" if "home" in bold else home
    away_html = f"<b>{away}</b>" if "away" in bold else away
    parts = [f"{home_html} vs {away_html}"]
    if with_score:
        scored = _score(score)
        if scored:
            parts.append(scored)
    if minute:
        parts.append(minute)
    return " · ".join(parts)


def _stat_block(key: str, payload: Mapping[str, Any], minute: object) -> list[str]:
    if key == "delta_5min":
        return _window_stat_lines(payload.get("last_5min"), minute, span=5)
    if key in ("pressure_index", "omega"):
        windowed = _window_stat_lines(payload.get("last_10min"), minute, span=10)
        if windowed or isinstance(payload.get("last_10min"), Mapping):
            return windowed
    if key == "delta_goal":
        form_bar = payload.get("form_bar")
        note = form_bar.get("note") if isinstance(form_bar, Mapping) else None
        if note:
            return [_esc(note), *_stat_rows(payload)]
    return _stat_rows(payload)


def _window_stat_lines(window: object, minute: object, *, span: int) -> list[str]:
    if not isinstance(window, Mapping):
        return []
    start = _minute_int(window.get("start"))
    end = _minute_int(window.get("end"))
    if end is None:
        end = _minute_int(minute)
    if start is not None and end is not None:
        heading = f"<b>Last {span} mins ({start}′-{end}′):</b>"
    else:
        heading = f"<b>Last {span} mins:</b>"
    rows = _stat_rows(window)
    return [heading, *rows] if rows else []


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


def _h2h_lines(payload: Mapping[str, Any], home: str, away: str, *, side: str) -> list[str]:
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
    if side == "away":
        subject, other = away, home
        subject_avg, other_avg = away_avg, home_avg
    else:
        subject, other = home, away
        subject_avg, other_avg = home_avg, away_avg
    lines = [
        f"· {subject} average {subject_avg:.1f} goals per meeting vs {other} {other_avg:.1f}, "
        f"last {sample}."
    ]
    try:
        home_wins = int(raw.get("home_wins"))
        draws = int(raw.get("draws"))
        away_wins = int(raw.get("away_wins"))
    except (TypeError, ValueError):
        return lines
    if side == "away":
        wins, losses = away_wins, home_wins
    else:
        wins, losses = home_wins, away_wins
    lines.append(f"· {wins}W-{draws}D-{losses}L for {subject}.")
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


def _value_over_ceiling(raw: object, *, key: str, payload: Mapping[str, Any]) -> str:
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
