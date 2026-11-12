"""Admin-edited alert text, with today's built-in text as the fallback.

A template is plain text with ``{tags}``, ``**bold**`` and ``_italic_``.
Everything the admin types is escaped, so a template cannot break Telegram's
HTML; ``\\*``, ``\\_``, ``\\{`` and ``\\}`` give the plain characters.

Rules when filling a template in:
- a line whose tags all came out empty is dropped (no league -> no league line);
- empty bold/italic and dangling `` · `` separators left by an empty tag go;
- runs of blank lines become one, and leading/trailing blank lines go.

Ready-made blocks (``{versus}``, ``{strategy_lines}``, ``{stats}``, ``{lede}``,
``{goal_line}``) are the same lines the built-in text uses (``format.py``).

If a saved template cannot be used for a message (bad syntax, too long, came
out empty), that message goes out with the built-in text and the reason is
reported so admin can show it.
"""

from __future__ import annotations

import html
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from kalchas_core.chance import chance_for_alert
from kalchas_core.weights import short_label_for

from kalchas_bot.discord_channel import html_to_discord
from kalchas_bot.format import (
    ALERT_NAMES,
    alert_blocks,
    format_alert_html,
    format_joint_html,
    format_outcome_html,
    goal_blocks,
    value_text,
)
from kalchas_bot.twitter_channel import html_to_tweet, match_link

CHANNELS: tuple[str, ...] = ("paid", "free", "discord")
KINDS: tuple[str, ...] = ("alert", "goal")

CAPTION_LIMIT = 1024
"""Telegram caption under a photo. Alerts go out as photo + caption."""
TEXT_LIMIT = 4096
"""Telegram text message: the no-photo alert and the GOAL reply."""
DISCORD_LIMIT = 2000

DEFAULT_TEMPLATES: dict[str, str] = {
    "alert": "{versus}\n_{league}_\n{strategy_lines}\n\n{stats}",
    "goal": "{lede}\n\n⚽ {goal_line}",
}
"""Templates that come out the same as the built-in text."""


@dataclass(frozen=True)
class Tag:
    name: str
    label: str
    group: str
    example: str
    kinds: tuple[str, ...] = KINDS
    block: bool = False


def _pair_tags(key: str, label: str, example: tuple[str, str]) -> tuple[Tag, Tag]:
    group = "Stats so far (whole match)"
    return (
        Tag(f"{key}_home", f"{label}, home team", group, example[0]),
        Tag(f"{key}_away", f"{label}, away team", group, example[1]),
    )


TAGS: tuple[Tag, ...] = (
    Tag("home", "Home team", "Match", "Arsenal"),
    Tag("away", "Away team", "Match", "Chelsea"),
    Tag("league", "League", "Match", "Premier League"),
    Tag("country", "Country", "Match", "England"),
    Tag("minute", "Minute the signal fired", "Match", "67′"),
    Tag("score", "Score when the signal fired", "Match", "1-0"),
    Tag(
        "time_since_goal",
        "Minutes since each team last scored (home - away)",
        "Match",
        "12 - 67",
    ),
    Tag(
        "match_link", "Link to the match on kalchas.live", "Match", "https://kalchas.live/?match=1"
    ),
    Tag(
        "strategy", "Strategy name (joined with + when several fire)", "Signal", "5-minute pressure"
    ),
    Tag("strategy_short", "Strategy short name", "Signal", "Δ5′"),
    Tag("value", "The reading, out of its maximum", "Signal", "8.4 / 12.0"),
    Tag("team", "Team the signal is for (empty if it's for both)", "Signal", "Arsenal"),
    Tag("side", "home or away", "Signal", "home"),
    Tag("form_note", "Form Bar's note (Form Bar only)", "Signal", "Scored in 9 of last 10"),
    Tag(
        "chance",
        "Chance the signal's team scores before full time (needs kickoff odds)",
        "Signal",
        "58%",
    ),
    Tag(
        "chance_odds_only",
        "The same chance from kickoff odds and the clock alone, without the signal",
        "Signal",
        "44%",
    ),
    Tag(
        "versus",
        "Match line: teams, minute, signal team in bold",
        "Ready-made lines",
        "**Arsenal** vs Chelsea · 67′",
        block=True,
    ),
    Tag(
        "strategy_lines",
        "One line per strategy with its reading",
        "Ready-made lines",
        "**Δ5′** (5-minute pressure): 8.4 / 12.0 for **Arsenal**",
        block=True,
    ),
    Tag(
        "stats",
        "Last 5 or 10 minutes: shots, attacks, corners, possession",
        "Ready-made lines",
        "**Last 5 mins (62′-67′):**\nSOT: **3** - 0",
        block=True,
    ),
    *_pair_tags("sot", "Shots on target", ("6", "2")),
    *_pair_tags("shots_off", "Shots off target", ("5", "3")),
    *_pair_tags("corners", "Corners", ("7", "1")),
    *_pair_tags("attacks", "Attacks", ("88", "54")),
    *_pair_tags("dangerous_attacks", "Dangerous attacks", ("61", "30")),
    *_pair_tags("possession", "Possession", ("62%", "38%")),
    *_pair_tags("yellow", "Yellow cards", ("1", "3")),
    *_pair_tags("red", "Red cards", ("0", "0")),
    Tag("odds_home", "Home win odds at kickoff", "Odds at kickoff", "1.85"),
    Tag("odds_draw", "Draw odds at kickoff", "Odds at kickoff", "3.60"),
    Tag("odds_away", "Away win odds at kickoff", "Odds at kickoff", "4.20"),
    Tag("favourite", "Favourite at kickoff (lower odds)", "Odds at kickoff", "Arsenal"),
    Tag("team_odds", "Kickoff odds of the team the signal is for", "Odds at kickoff", "1.85"),
    Tag("h2h_meetings", "Past meetings counted", "Head to head", "8"),
    Tag("h2h_home_wins", "Home team wins", "Head to head", "4"),
    Tag("h2h_draws", "Draws", "Head to head", "2"),
    Tag("h2h_away_wins", "Away team wins", "Head to head", "2"),
    Tag(
        "lede",
        "The alert's first lines: match, league, strategy",
        "Goal reply",
        "**Arsenal** vs Chelsea · 67′\n_Premier League_\n**Δ5′** (5-minute pressure): 8.4 / 12.0",
        kinds=("goal",),
        block=True,
    ),
    Tag(
        "goal_line",
        "GOAL at minute · score before → after",
        "Goal reply",
        "GOAL at 72′ · 1-0 → 2-0",
        kinds=("goal",),
        block=True,
    ),
    Tag("goal_minute", "Minute of the goal", "Goal reply", "72′", kinds=("goal",)),
    Tag("fire_score", "Score when the signal fired", "Goal reply", "1-0", kinds=("goal",)),
    Tag("settle_score", "Score after the goal", "Goal reply", "2-0", kinds=("goal",)),
    Tag("scoring_team", "Team that scored", "Goal reply", "Arsenal", kinds=("goal",)),
)

TAG_BY_NAME: dict[str, Tag] = {tag.name: tag for tag in TAGS}


class TemplateError(ValueError):
    pass


@dataclass(frozen=True)
class Problem:
    line: int
    message: str


# Escapes, {tags}, ** and _ markers, plain runs, then any single stray char.
_TOKEN = re.compile(r"\\([*_{}\\])|\{([^{}\n]*)\}|\*\*|_|[^\\{}*_]+|.", re.DOTALL)
_MARK = {"**": "b", "_": "i"}
_MARK_NAME = {"b": "**bold**", "i": "_italic_"}

Piece = tuple[str, str]
"""("text", s) | ("tag", name) | ("mark", "b" | "i")."""


def _tokens(line: str) -> list[Piece]:
    out: list[Piece] = []
    for match in _TOKEN.finditer(line):
        whole = match.group(0)
        if match.group(1) is not None:
            out.append(("text", match.group(1)))
        elif match.group(2) is not None:
            out.append(("tag", match.group(2).strip()))
        elif whole in _MARK:
            out.append(("mark", _MARK[whole]))
        else:
            out.append(("text", whole))
    return out


def _lines(body: str) -> list[str]:
    return body.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def check(body: str, kind: str) -> list[Problem]:
    """Every problem that stops a template being used, in plain words."""
    if not body.strip():
        return [Problem(0, "The template is empty.")]
    problems: list[Problem] = []
    for number, line in enumerate(_lines(body), start=1):
        stack: list[str] = []
        for part_kind, value in _tokens(line):
            if part_kind == "tag":
                problem = _tag_problem(value, kind)
                if problem:
                    problems.append(Problem(number, f"Line {number}: {problem}"))
            elif part_kind == "mark":
                if stack and stack[-1] == value:
                    stack.pop()
                elif value in stack:
                    problems.append(
                        Problem(
                            number,
                            f"Line {number}: bold and italic overlap. Close the inner one first.",
                        )
                    )
                    stack.remove(value)
                else:
                    stack.append(value)
        for mark in stack:
            marker = "**" if mark == "b" else "_"
            problems.append(
                Problem(
                    number,
                    f"Line {number}: {marker} isn't closed. {_MARK_NAME[mark]} has to close "
                    f"on the same line. For a plain {marker[0]}, write \\{marker[0]}.",
                )
            )
    return problems


def _tag_problem(name: str, kind: str) -> str | None:
    tag = TAG_BY_NAME.get(name)
    if tag is None:
        lowered = name.lower().replace(" ", "_")
        if lowered in TAG_BY_NAME:
            return f"{{{name}}} should be written {{{lowered}}}."
        if not name:
            return "{} is empty. Put a tag name inside, like {home}."
        return f"there's no {{{name}}} tag."
    if kind not in tag.kinds:
        return f"{{{name}}} only works in the goal reply."
    return None


def render(body: str, values: Mapping[str, str]) -> str:
    """Fill a checked template in. ``values`` are HTML-safe already."""
    out_lines: list[str] = []
    for line in _lines(body):
        tokens = _tokens(line)
        tags = [value for kind, value in tokens if kind == "tag"]
        if tags and all(not values.get(name) for name in tags):
            continue
        parts: list[str] = []
        stack: list[str] = []
        for part_kind, value in tokens:
            if part_kind == "text":
                parts.append(html.escape(value, quote=False))
            elif part_kind == "tag":
                if value not in TAG_BY_NAME:
                    raise TemplateError(f"there's no {{{value}}} tag")
                parts.append(values.get(value, ""))
            elif stack and stack[-1] == value:
                stack.pop()
                parts.append(f"</{value}>")
            elif value in stack:
                raise TemplateError("bold and italic overlap")
            else:
                stack.append(value)
                parts.append(f"<{value}>")
        if stack:
            raise TemplateError("bold or italic isn't closed")
        rendered = "".join(parts)
        if any(not values.get(name) for name in tags):
            rendered = _tidy(rendered)
        out_lines.append(rendered)
    return _squeeze_blank_lines(out_lines)


_EMPTY_MARK = re.compile(r"<(b|i)>\s*</\1>")
_DOUBLE_DOT = re.compile(r"\s*·\s*(?:·\s*)+")
_EDGE_DOT = re.compile(r"^\s*·\s*|\s*·\s*$")


def _tidy(line: str) -> str:
    previous = None
    while previous != line:
        previous = line
        line = _EMPTY_MARK.sub("", line)
    line = _DOUBLE_DOT.sub(" · ", line)
    return _EDGE_DOT.sub("", line).rstrip()


def _squeeze_blank_lines(lines: Sequence[str]) -> str:
    text = "\n".join(lines)
    text = re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", text)
    return text.strip("\n").rstrip()


def visible_length(html_text: str) -> int:
    """Characters Telegram counts: tags removed, entities decoded, UTF-16 units."""
    plain = html.unescape(re.sub(r"<[^>]+>", "", html_text))
    return len(plain.encode("utf-16-le")) // 2


# --- values ---------------------------------------------------------------


def _esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def _mapping(raw: object) -> Mapping[str, Any]:
    if isinstance(raw, str) and raw.strip():
        import json

        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return raw if isinstance(raw, Mapping) else {}


def _slot_order(row: Mapping[str, Any]) -> tuple[int, int]:
    try:
        slot = int(row.get("strategy_slot") or 0)
    except (TypeError, ValueError):
        slot = 0
    try:
        alert_id = int(row.get("id") or 0)
    except (TypeError, ValueError):
        alert_id = 0
    return slot, alert_id


def _merged(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for row in rows:
        for key, value in _mapping(row.get("payload")).items():
            if value not in (None, "", {}, []) and key not in merged:
                merged[key] = value
    return merged


def _side(row: Mapping[str, Any]) -> str:
    side = str(row.get("team") or _mapping(row.get("payload")).get("team") or "").lower()
    return side if side in ("home", "away") else ""


def _int_text(raw: object) -> str:
    if raw is None or raw == "":
        return ""
    try:
        return str(int(float(raw)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ""


def _odd(raw: object) -> float | None:
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return value if value > 1.0 else None


_PAIR_KEYS = (
    ("sot", "sot", ""),
    ("shots_off", "sofft", ""),
    ("corners", "corners", ""),
    ("attacks", "attacks", ""),
    ("dangerous_attacks", "da", ""),
    ("possession", "possession", "%"),
    ("yellow", "yc", ""),
    ("red", "rc", ""),
)


def alert_values(rows: Sequence[Mapping[str, Any]], *, with_score: bool = False) -> dict[str, str]:
    """Every alert tag's value for one message (one or several strategies), HTML-safe."""
    ordered = sorted(rows, key=_slot_order)
    first = ordered[0]
    payload = _merged(ordered)
    home = str(first.get("home_team") or payload.get("home") or "")
    away = str(first.get("away_team") or payload.get("away") or "")
    sides = {_side(row) for row in ordered} - {""}
    side = next(iter(sides)) if len(sides) == 1 else ""
    team = home if side == "home" else away if side == "away" else ""
    keys = [str(row.get("strategy_key") or "") for row in ordered]
    shorts = [short_label_for(key) for key in keys if key]
    names = [ALERT_NAMES.get(key) or short_label_for(key) for key in keys if key]
    readings = [reading for row in ordered if (reading := value_text(row))]
    minute = _int_text(first.get("minute"))
    form_bar = payload.get("form_bar")
    values: dict[str, str] = {
        "home": _esc(home),
        "away": _esc(away),
        "league": _esc(payload.get("league")),
        "country": _esc(payload.get("country")),
        "minute": f"{minute}′" if minute else "",
        "score": _esc(str(first.get("score") or payload.get("score") or "").replace("–", "-")),
        "time_since_goal": _esc(payload.get("tslg")),
        "match_link": _esc(match_link(first.get("match_id") or payload.get("match_id"))),
        "strategy": _esc(" + ".join(names)),
        "strategy_short": _esc(" + ".join(shorts)),
        "value": _esc(" · ".join(readings)),
        "team": _esc(team),
        "side": side,
        "form_note": _esc(form_bar.get("note") if isinstance(form_bar, Mapping) else ""),
        **alert_blocks(ordered, with_score=with_score),
    }
    for name, key, suffix in _PAIR_KEYS:
        pair = payload.get(key)
        for team_side in ("home", "away"):
            raw = pair.get(team_side) if isinstance(pair, Mapping) else None
            number = _int_text(raw)
            values[f"{name}_{team_side}"] = f"{number}{suffix}" if number else ""
    values.update(_odds_values(payload.get("odds"), home=home, away=away, side=side))
    chance = (
        chance_for_alert(payload, team=side, minute=first.get("minute"), score=values["score"])
        if side
        else None
    )
    values["chance"] = f"{chance.percent}%" if chance else ""
    values["chance_odds_only"] = f"{chance.baseline_percent}%" if chance else ""
    values.update(_h2h_values(payload.get("h2h")))
    return values


def _odds_values(raw: object, *, home: str, away: str, side: str) -> dict[str, str]:
    odds = _mapping(raw)
    kickoff = _mapping(odds.get("kickoff")) or odds
    home_odd = _odd(kickoff.get("home"))
    draw_odd = _odd(kickoff.get("draw"))
    away_odd = _odd(kickoff.get("away"))

    def fmt(value: float | None) -> str:
        return f"{value:.2f}" if value is not None else ""

    favourite = ""
    if home_odd is not None and away_odd is not None and home_odd != away_odd:
        favourite = home if home_odd < away_odd else away
    team_odd = home_odd if side == "home" else away_odd if side == "away" else None
    return {
        "odds_home": fmt(home_odd),
        "odds_draw": fmt(draw_odd),
        "odds_away": fmt(away_odd),
        "favourite": _esc(favourite),
        "team_odds": fmt(team_odd),
    }


def _h2h_values(raw: object) -> dict[str, str]:
    h2h = _mapping(raw)
    return {
        "h2h_meetings": _int_text(h2h.get("sample")),
        "h2h_home_wins": _int_text(h2h.get("home_wins")),
        "h2h_draws": _int_text(h2h.get("draws")),
        "h2h_away_wins": _int_text(h2h.get("away_wins")),
    }


def goal_values(row: Mapping[str, Any]) -> dict[str, str]:
    """Alert tags for the original fire plus the goal reply's own tags."""
    detail = _mapping(row.get("detail"))
    fire_row = dict(row)
    fire_row["home_team"] = row.get("home_team") or detail.get("home_team")
    fire_row["away_team"] = row.get("away_team") or detail.get("away_team")
    if fire_row.get("minute") is None:
        fire_row["minute"] = detail.get("fire_minute")
    payload = dict(_mapping(row.get("payload")))
    if not payload.get("league") and detail.get("league"):
        payload["league"] = detail.get("league")
    fire_row["payload"] = payload
    values = alert_values([fire_row])
    values.update(goal_blocks(row))
    side = scoring_side(detail)
    team = (
        fire_row["home_team"] if side == "home" else fire_row["away_team"] if side == "away" else ""
    )
    values["scoring_team"] = _esc(team)
    return values


def scoring_side(detail: Mapping[str, Any]) -> str:
    """home / away for the goal that settled the alert; empty when it can't be told.

    The settler records ``scoring_side`` from the goal event. Older rows fall back
    to the score: exactly one side's count went up between fire and settle.
    """
    side = str(detail.get("scoring_side") or "").lower()
    if side in ("home", "away"):
        return side
    fire = _score_pair(detail.get("fire_score"))
    settle = _score_pair(detail.get("settle_score"))
    if fire is None or settle is None:
        return ""
    if settle[0] > fire[0] and settle[1] == fire[1]:
        return "home"
    if settle[1] > fire[1] and settle[0] == fire[0]:
        return "away"
    return ""


def _score_pair(raw: object) -> tuple[int, int] | None:
    parts = re.split(r"\s*[-–:]\s*", str(raw or "").strip())
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


# --- choosing text per channel --------------------------------------------


@dataclass(frozen=True)
class Rendered:
    text: str
    problem: str | None = None


def render_or_builtin(
    body: str,
    values: Mapping[str, str],
    builtin: str,
    *,
    kind: str,
    limit: int,
    measure: Any = visible_length,
) -> Rendered:
    problems = check(body, kind)
    if problems:
        return Rendered(builtin, problems[0].message)
    try:
        text = render(body, values)
    except Exception as exc:  # noqa: BLE001 — any template failure means built-in text
        return Rendered(builtin, f"could not fill in: {exc}")
    if not text.strip():
        return Rendered(builtin, "came out empty for this alert")
    length = int(measure(text))
    if length > limit:
        return Rendered(builtin, f"came to {length:,} characters, over the {limit:,} limit")
    return Rendered(text)


def _discord_length(text: str) -> int:
    return len(html_to_discord(text))


Templates = Mapping[tuple[str, str], str]
"""Switched-on templates keyed by (channel, kind)."""

Fallback = tuple[str, str, str]
"""(channel, kind, reason) for a saved template that could not be used."""


@dataclass(frozen=True)
class ChannelText:
    caption: str
    fallback: str
    builtin: tuple[str, str]

    @property
    def templated(self) -> bool:
        return (self.caption, self.fallback) != self.builtin


@dataclass
class AlertTexts:
    paid: ChannelText
    free: ChannelText
    discord_paid: str
    discord_free: str
    fallbacks: list[Fallback] = field(default_factory=list)


def builtin_alert(rows: Sequence[Mapping[str, Any]]) -> tuple[str, str]:
    if len(rows) > 1:
        return format_joint_html(rows), format_joint_html(rows, with_score=True)
    return format_alert_html(rows[0]), format_alert_html(rows[0], with_score=True)


def alert_texts(
    rows: Sequence[Mapping[str, Any]],
    templates: Templates | None,
    *,
    caption: str,
    fallback: str,
) -> AlertTexts:
    """Text for each place an alert goes. ``caption``/``fallback`` are the built-in pair."""
    builtin = (caption, fallback)
    plain = ChannelText(caption, fallback, builtin)
    if not templates or not rows or not any(kind == "alert" for _, kind in templates):
        return AlertTexts(plain, plain, caption, caption)
    caption_values = alert_values(rows, with_score=False)
    fallback_values = alert_values(rows, with_score=True)
    fallbacks: list[Fallback] = []

    def tier(channel: str) -> ChannelText:
        body = templates.get((channel, "alert"))
        if body is None:
            return plain
        cap = render_or_builtin(body, caption_values, caption, kind="alert", limit=CAPTION_LIMIT)
        text = render_or_builtin(body, fallback_values, fallback, kind="alert", limit=TEXT_LIMIT)
        problem = cap.problem or text.problem
        if problem:
            fallbacks.append((channel, "alert", problem))
            return plain
        return ChannelText(cap.text, text.text, builtin)

    paid = tier("paid")
    free = tier("free")
    discord_paid, discord_free = paid.caption, free.caption
    discord_body = templates.get(("discord", "alert"))
    if discord_body is not None:
        made = render_or_builtin(
            discord_body,
            caption_values,
            "",
            kind="alert",
            limit=DISCORD_LIMIT,
            measure=_discord_length,
        )
        if made.problem:
            fallbacks.append(("discord", "alert", made.problem))
        else:
            discord_paid = discord_free = made.text
    return AlertTexts(paid, free, discord_paid, discord_free, fallbacks)


@dataclass
class GoalTexts:
    paid: str
    free: str
    discord_paid: str
    discord_free: str
    builtin: str
    fallbacks: list[Fallback] = field(default_factory=list)


def goal_texts(rows: Sequence[Mapping[str, Any]], templates: Templates | None) -> GoalTexts:
    """GOAL reply text for each place. Several confirmed alerts join with a blank line."""
    builtins = [format_outcome_html(row) for row in rows]
    builtin = "\n\n".join(builtins)
    if not templates or not any(kind == "goal" for _, kind in templates):
        return GoalTexts(builtin, builtin, builtin, builtin, builtin)
    fallbacks: list[Fallback] = []
    values = [goal_values(row) for row in rows]

    def made(channel: str, limit: int, measure: Any = visible_length) -> str | None:
        body = templates.get((channel, "goal"))
        if body is None:
            return None
        parts: list[str] = []
        for row_values, row_builtin in zip(values, builtins, strict=True):
            part = render_or_builtin(
                body, row_values, row_builtin, kind="goal", limit=limit, measure=measure
            )
            if part.problem:
                fallbacks.append((channel, "goal", part.problem))
                return None
            parts.append(part.text)
        joined = "\n\n".join(parts)
        if measure(joined) > limit:
            fallbacks.append((channel, "goal", f"over the {limit:,} limit"))
            return None
        return joined

    paid = made("paid", TEXT_LIMIT) or builtin
    free = made("free", TEXT_LIMIT) or builtin
    discord = made("discord", DISCORD_LIMIT, _discord_length)
    return GoalTexts(
        paid,
        free,
        discord if discord is not None else paid,
        discord if discord is not None else free,
        builtin,
        fallbacks,
    )


# --- admin: long sample and preview ----------------------------------------


def long_rows() -> list[dict[str, Any]]:
    """Worst case for length: three strategies, long names, every stat present."""
    window = {
        "start": 79,
        "end": 89,
        "sot": {"home": 14, "away": 12},
        "sofft": {"home": 13, "away": 11},
        "da": {"home": 48, "away": 47},
        "corners": {"home": 11, "away": 10},
        "possession": {"home": 51, "away": 49},
    }
    payload = {
        "league": "UEFA Europa Conference League - Qualification Round 3",
        "country": "Bosnia and Herzegovina",
        "tslg": "88 - 88",
        "sot": {"home": 24, "away": 22},
        "sofft": {"home": 23, "away": 21},
        "corners": {"home": 15, "away": 14},
        "attacks": {"home": 188, "away": 177},
        "da": {"home": 111, "away": 109},
        "possession": {"home": 51, "away": 49},
        "yc": {"home": 5, "away": 6},
        "rc": {"home": 1, "away": 1},
        "odds": {"home": 12.75, "draw": 10.25, "away": 13.5},
        "h2h": {"sample": 10, "home_wins": 4, "draws": 3, "away_wins": 3},
        "last_5min": window,
        "last_10min": window,
        "form_bar": {"note": "Scored in each of the last ten matches against this opponent"},
    }
    base = {
        "match_id": "9999999",
        "minute": 89,
        "score": "10-10",
        "home_team": "Borussia Mönchengladbach Amateure II",
        "away_team": "Wolverhampton Wanderers Under 21 Reserves",
        "payload": payload,
    }
    return [
        {
            **base,
            "id": 1,
            "strategy_slot": 1,
            "strategy_key": "rule_of_three",
            "team": "home",
            "value": 9.9,
        },
        {
            **base,
            "id": 2,
            "strategy_slot": 2,
            "strategy_key": "delta_5min",
            "team": "away",
            "value": 11.9,
        },
        {
            **base,
            "id": 3,
            "strategy_slot": 3,
            "strategy_key": "pressure_index",
            "team": "home",
            "value": 99,
        },
    ]


def long_goal_row() -> dict[str, Any]:
    row = dict(long_rows()[1])
    row["state"] = "Confirmed"
    row["detail"] = {"goal_minute": 90, "fire_score": "10-10", "settle_score": "11-10"}
    return row


def limit_for(channel: str, kind: str) -> int:
    if channel == "discord":
        return DISCORD_LIMIT
    return CAPTION_LIMIT if kind == "alert" else TEXT_LIMIT


def _measure_for(channel: str) -> Any:
    return _discord_length if channel == "discord" else visible_length


def long_sample_problem(channel: str, kind: str, body: str) -> str | None:
    """Does the template fit with long names and three strategies?"""
    if kind == "alert":
        values = alert_values(long_rows())
        what = "long team names and three strategies at once"
    else:
        values = goal_values(long_goal_row())
        what = "long team names"
    try:
        text = render(body, values)
    except TemplateError:
        return None  # check() already reports it
    limit = limit_for(channel, kind)
    length = int(_measure_for(channel)(text))
    if length <= limit:
        return None
    where = (
        "Discord allows"
        if channel == "discord"
        else "Telegram allows" + (" under a photo" if kind == "alert" else "")
    )
    return (
        f"With {what} this comes to {length:,} characters; {where} {limit:,}. "
        "Shorten it, or the long ones will go out with the built-in text."
    )


def validate(channel: str, kind: str, body: str) -> list[str]:
    """Problems that block saving."""
    messages = [problem.message for problem in check(body, kind)]
    if not messages:
        long_problem = long_sample_problem(channel, kind, body)
        if long_problem:
            messages.append(long_problem)
    return messages


def preview(
    channel: str,
    kind: str,
    body: str,
    rows: Sequence[Mapping[str, Any]],
    active: Templates | None = None,
) -> dict[str, Any]:
    """What each place would get for ``rows`` if ``body`` were saved now."""
    templates: dict[tuple[str, str], str] = dict(active or {})
    templates[(channel, kind)] = body
    problems = validate(channel, kind, body)
    result: dict[str, Any] = {
        "problems": problems,
        "telegram": "",
        "discord": "",
        "x": "",
        "length": 0,
        "limit": limit_for(channel, kind),
        "fell_back": None,
        "discord_follows": ("discord", kind) not in templates,
    }
    if not rows:
        return result
    if kind == "alert":
        caption, fallback = builtin_alert(rows)
        texts = alert_texts(rows, templates, caption=caption, fallback=fallback)
        tier = texts.free if channel == "free" else texts.paid
        discord = texts.discord_free if channel == "free" else texts.discord_paid
        telegram = tier.caption
        fallbacks = texts.fallbacks
    else:
        goals = goal_texts(rows, templates)
        telegram = goals.free if channel == "free" else goals.paid
        discord = goals.discord_free if channel == "free" else goals.discord_paid
        fallbacks = goals.fallbacks
    mine = next((reason for ch, kd, reason in fallbacks if ch == channel and kd == kind), None)
    result["fell_back"] = mine
    if channel != "discord":
        result["telegram"] = telegram
        result["length"] = visible_length(telegram)
    else:
        result["length"] = _discord_length(discord)
    result["discord"] = html_to_discord(discord)
    if channel == "free" and kind == "alert":
        result["x"] = html_to_tweet(telegram)
    return result


def tag_list() -> list[dict[str, Any]]:
    return [
        {
            "name": tag.name,
            "label": tag.label,
            "group": tag.group,
            "example": tag.example,
            "kinds": list(tag.kinds),
            "block": tag.block,
        }
        for tag in TAGS
    ]
