"""Ask Claude to stress-test an admin parlay before it posts.

Uses ANTHROPIC_API_KEY. Advises only — never mutates the slip. Grounded on
structured Kalchas facts so it cannot invent prices or matches.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

log = logging.getLogger("kalchas.api.parlay_claude")

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-20250514"

SYSTEM = """You are Kalchas's parlay stress-test assistant for an operator who already
built a multi-leg slip from our watchlist research.

Rules:
- Cite only numbers and matches present in the JSON facts you are given.
- Do not invent odds, kick-offs, teams, or recent records.
- If something is unclear, say so.
- Be concise and practical. No hype. No gambling encouragement beyond research framing.
- Output plain text with short sections:
  1) Weakest leg (name it and why, using the provided recent hit rate and price)
  2) One optional swap idea from the unused candidates if any look quieter, else say none
  3) Overall read in one or two sentences
"""


def _facts(
    *,
    slot: str,
    style: str,
    day: str,
    selected: Sequence[Mapping[str, Any]],
    unused: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    def pack(leg: Mapping[str, Any]) -> dict[str, Any]:
        home = leg.get("home") if isinstance(leg.get("home"), Mapping) else {}
        away = leg.get("away") if isinstance(leg.get("away"), Mapping) else {}
        return {
            "match_id": str(leg.get("match_id")),
            "kickoff": str(leg.get("kickoff") or ""),
            "home": str(home.get("name") or ""),
            "away": str(away.get("name") or ""),
            "market": str(leg.get("label") or leg.get("market") or ""),
            "price": leg.get("price"),
            "recent_hit": leg.get("hit"),
            "recent_games": leg.get("n"),
            "watch": leg.get("watch"),
            "brief": str(leg.get("brief") or "")[:240],
            "score": leg.get("score"),
        }

    return {
        "slot": slot,
        "style": style,
        "day": day,
        "selected_legs": [pack(leg) for leg in selected],
        "unused_candidates": [pack(leg) for leg in unused[:12]],
    }


def evaluate(
    *,
    slot: str,
    style: str,
    day: str,
    selected: Sequence[Mapping[str, Any]],
    unused: Sequence[Mapping[str, Any]],
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        return {"ok": False, "error": "ANTHROPIC_API_KEY is not set"}

    facts = _facts(slot=slot, style=style, day=day, selected=selected, unused=unused)
    owns = client is None
    http = client or httpx.Client(timeout=60.0)
    try:
        res = http.post(
            ANTHROPIC_URL,
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": MODEL,
                "max_tokens": 700,
                "system": SYSTEM,
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "Stress-test this Kalchas parlay. Facts JSON follows.\n\n"
                            + json.dumps(facts, ensure_ascii=False)
                        ),
                    }
                ],
            },
        )
        if res.status_code >= 400:
            log.warning("anthropic evaluate HTTP %s: %s", res.status_code, res.text[:300])
            return {"ok": False, "error": f"Claude HTTP {res.status_code}"}
        data = res.json()
        parts = data.get("content") or []
        text = "\n".join(str(p.get("text") or "") for p in parts if isinstance(p, Mapping)).strip()
        if not text:
            return {"ok": False, "error": "empty Claude response"}
        return {"ok": True, "advice": text, "model": data.get("model") or MODEL}
    except Exception as exc:
        log.exception("parlay claude evaluate failed")
        return {"ok": False, "error": str(exc)[:300]}
    finally:
        if owns:
            http.close()
