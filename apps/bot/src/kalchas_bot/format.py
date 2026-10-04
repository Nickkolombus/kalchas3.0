"""HTML Telegram alert body from an outbox row.

2.2 also rendered Playwright versus-banners. Those were expensive. The
scanner now persists the same live stats 2.2 put in the text card — league,
1X2, SOT, attacks, possession, cards, TSLG — with no extra HTTP.
"""

from __future__ import annotations

import html
import json
from collections.abc import Mapping
from typing import Any

from kalchas_core.odds import is_short_price, kickoff_home_away
from kalchas_core.strategies.omega import DEFAULT_ANGLE_SCALE, alert_theta_degrees
from kalchas_core.weights import display_name_for, short_label_for


def format_alert_html(row: Mapping[str, Any]) -> str:
    """Telegram HTML parse_mode body. Team names are escaped."""
    payload = _payload(row.get("payload"))
    home = _esc(row.get("home_team"))
    away = _esc(row.get("away_team"))
    key = str(row.get("strategy_key") or "")
    short = _esc(short_label_for(key))
    name = _esc(display_name_for(key))
    score = _esc(_score(row.get("score")))
    minute = _minute(row.get("minute"))
    trigger = _trigger(row, home, away)
    value = _value(row.get("value"), key=key, payload=payload)
    league = _esc(payload.get("league") or "")
    tslg = _esc(_tslg(payload))

    title = f"<b>{short}</b> · {name}" if short != name else f"<b>{name}</b>"
    lines = [title]
    if league:
        lines.append(f"<i>{league}</i>")
    lines.append(_versus_html(home, away, score, payload))
    meta = " · ".join(part for part in (minute, trigger, value) if part)
    if meta:
        lines.append(meta)
    odds = _odds_line(payload.get("odds"))
    if odds:
        lines.append(odds)
    stats = _stats_lines(payload)
    if stats:
        lines.append("")
        lines.extend(stats)
    if tslg:
        lines.append(f"TSLG: {tslg}")
    return "\n".join(lines)


def _versus_html(
    home: str, away: str, score: str, payload: Mapping[str, Any]
) -> str:
    """Bold only the side whose kickoff decimal is under 1.68."""
    ko_home, ko_away = kickoff_home_away(payload.get("odds"))
    home_html = f"<b>{home}</b>" if is_short_price(ko_home) else home
    away_html = f"<b>{away}</b>" if is_short_price(ko_away) else away
    return f"{home_html}  {score}  {away_html}"


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
        return "–"
    return text.replace("-", "–")


def _minute(raw: object) -> str:
    if raw is None or raw == "":
        return ""
    try:
        return f"{int(raw)}′"
    except (TypeError, ValueError):
        return f"{raw}′"


def _trigger(row: Mapping[str, Any], home: str, away: str) -> str:
    side = str(row.get("team") or "").lower()
    if side == "home":
        return home
    if side == "away":
        return away
    if side in ("", "match", "none"):
        return "match"
    return _esc(side)


def _value(raw: object, *, key: str = "", payload: Mapping[str, Any] | None = None) -> str:
    if raw is None or raw == "":
        return ""
    try:
        numeric = float(raw)
    except (TypeError, ValueError):
        return ""
    if key == "omega":
        k_scale = DEFAULT_ANGLE_SCALE
        theta: float | None = None
        if isinstance(payload, Mapping):
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
        deg = alert_theta_degrees(numeric, k_scale, theta=theta)
        return f"<code>{deg:.0f}°</code>"
    return f"<code>{numeric:.1f}</code>"


def _tslg(payload: Mapping[str, Any]) -> str:
    display = payload.get("tslg")
    if display is None:
        return ""
    if isinstance(display, Mapping):
        display = display.get("display")
    return str(display or "").strip()


def _pair(payload: Mapping[str, Any], key: str) -> str:
    raw = payload.get(key)
    if not isinstance(raw, Mapping):
        return ""
    try:
        home = int(raw.get("home") or 0)
        away = int(raw.get("away") or 0)
    except (TypeError, ValueError):
        return ""
    return f"{home}–{away}"


def _odds_triple(block: object, prefix: str) -> str:
    if not isinstance(block, Mapping):
        return ""
    try:
        home = float(block["home"])
        away = float(block["away"])
    except (KeyError, TypeError, ValueError):
        return ""
    draw_raw = block.get("draw")
    try:
        draw = f"{float(draw_raw):.2f}" if draw_raw is not None else "-"
    except (TypeError, ValueError):
        draw = "-"
    return f"{prefix} {home:.2f} / {draw} / {away:.2f}"


def _odds_line(raw: object) -> str:
    if not isinstance(raw, Mapping):
        return ""
    kickoff = raw.get("kickoff") if isinstance(raw.get("kickoff"), Mapping) else raw
    lines = [part for part in (_odds_triple(kickoff, "KO"), _odds_triple(raw.get("live"), "Live")) if part]
    return "\n".join(lines)


def _stats_lines(payload: Mapping[str, Any]) -> list[str]:
    sot = _pair(payload, "sot")
    sofft = _pair(payload, "sofft")
    corners = _pair(payload, "corners")
    attacks = _pair(payload, "attacks")
    da = _pair(payload, "da")
    poss = _pair(payload, "possession")
    yc = _pair(payload, "yc")
    rc = _pair(payload, "rc")
    if not any((sot, sofft, corners, attacks, da, poss, yc, rc)):
        return []
    lines: list[str] = []
    if sot:
        lines.append(f"SOT: {sot}")
    if sofft:
        lines.append(f"SoffT: {sofft}")
    if corners:
        lines.append(f"Corners: {corners}")
    if attacks:
        lines.append(f"Atk.: {attacks}")
    if da:
        lines.append(f"D.Atk.: {da}")
    if poss:
        lines.append(f"Possession: {poss.replace('–', '%–')}%")
    cards = "  ".join(
        part
        for part in (
            f"YC: {yc}" if yc and yc != "0–0" else "",
            f"RC: {rc}" if rc and rc != "0–0" else "",
        )
        if part
    )
    if cards:
        lines.append(cards)
    return lines
