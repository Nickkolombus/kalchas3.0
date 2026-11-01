"""Map API-Football team names to Betfair event names for the BFbot feed.

Port of Kalchas 2.2 `betfair_match_correlator` (gist source only). Betfair's API
returns 403 from Railway, so fixtures come from the gist that
`scripts/update_gist_manual.py` in the 2.2 repo uploads from a machine with access.
"""

from __future__ import annotations

import csv
import io
import logging
import os
import re
import threading
import time
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Any

import httpx

logger = logging.getLogger("kalchas.api.betfair_names")

DEFAULT_CSV_URL = (
    "https://gist.githubusercontent.com/Nickkolombus/"
    "121d11598977dbd4c835573249d4a7b0/raw/betfair_7d.csv"
)
CACHE_TTL_SECONDS = 300
DEFAULT_MIN_SIMILARITY = 0.55
# 2.2 used 0.40, which let "Rizespor" map to "Eyupspor" (0.44). Wrong game = wrong bet.
MIN_INDIVIDUAL = 0.60

METHOD_EXACT = "gist_exact"
METHOD_FUZZY = "gist_fuzzy"
METHOD_NONE = "none"

_PREFIXES = (
    "afc ",
    "ac ",
    "fc ",
    "cf ",
    "sc ",
    "fk ",
    "bk ",
    "sk ",
    "nk ",
    "gk ",
    "tsv ",
    "fsv ",
    "if ",
    "ik ",
)
_SUFFIXES = (" fc", " ac", " afc", " cf", " sc", " united", " city", " fk", " bk", " sk")
_RESERVE_SUFFIXES = (" 2", " b", " ii", " u21", " u23")
_REGIONAL_SUFFIXES = (
    " de cali",
    " de cordoba",
    " de quito",
    " de guayaquil",
    " de santa fe",
    " de tucuman",
    " de mendoza",
    " de cuenca",
    " de merida",
    " de salta",
    " de rosario",
    " de la plata",
    " de avellaneda",
    " de barranquilla",
    " de medellin",
    " de bogota",
    " de santiago",
    " de lima",
    " de asuncion",
)
_REPLACEMENTS = {
    "manchester united": "man utd",
    "man united": "man utd",
    "manchester city": "man city",
    "tottenham hotspur": "tottenham",
    "spurs": "tottenham",
    "paris saint-germain": "paris st-g",
    "paris saint germain": "paris st-g",
    "psg": "paris st-g",
    "bayern": "bayern munich",
    "barca": "barcelona",
    "fc barcelona": "barcelona",
    "ac milan": "ac milan",
    "milan": "ac milan",
    "internazionale": "inter",
    "inter milan": "inter",
    "juve": "juventus",
    "as roma": "roma",
}
_NOISE = {
    "de",
    "la",
    "el",
    "los",
    "las",
    "del",
    "al",
    "le",
    "les",
    "do",
    "da",
    "dos",
    "das",
    "von",
    "van",
    "fc",
}


@dataclass(frozen=True)
class Fixture:
    home: str
    away: str
    open_date: str = ""


@dataclass(frozen=True)
class NameMatch:
    home: str
    away: str
    method: str
    fuzzy_applied: bool


def _clean(value: str) -> str:
    text = re.sub(r"<[^>]+>", "", value or "").strip()
    return "".join(ch for ch in text if ch.isprintable())


@lru_cache(maxsize=4096)
def normalize_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ASCII", "ignore").decode("ASCII")
    text = text.lower().strip()
    # 2.2 only applied the aliases after stripping " united"/" city", so
    # "manchester united" never reached its alias. Apply them first as well.
    text = _REPLACEMENTS.get(text, text)
    for prefix in _PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix) :]
            break
    for suffix in _SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    for suffix in _RESERVE_SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
            break
    for suffix in _REGIONAL_SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
            break
    return _REPLACEMENTS.get(text, text)


def team_kind(name: str) -> tuple[bool, str, bool]:
    """(women, youth age, reserve) markers. A men's side must never map to its W/U19/B team."""
    tokens = re.sub(r"[()\.]", " ", name.lower()).split()
    women = bool(tokens) and tokens[-1] in {"w", "women", "ladies"}
    youth = next((tok for tok in tokens if re.fullmatch(r"u\d{2}", tok)), "")
    reserve = len(tokens) > 1 and tokens[-1] in {"b", "2", "ii", "c"}
    return women, youth, reserve


def similarity(name1: str, name2: str) -> float:
    norm1 = normalize_name(name1)
    norm2 = normalize_name(name2)
    if norm1 == norm2:
        return 1.0
    seq_score = SequenceMatcher(None, norm1, norm2).ratio()
    tokens1 = set(norm1.split())
    tokens2 = set(norm2.split())
    clean1 = tokens1 - _NOISE
    clean2 = tokens2 - _NOISE

    token_score = 0.0
    if clean1 and clean2:
        token_score = len(clean1 & clean2) / min(len(clean1), len(clean2))

    containment = 0.20 if (norm1 in norm2 or norm2 in norm1) else 0.0
    subset = 0.0
    if clean1 and clean2 and (clean1.issubset(clean2) or clean2.issubset(clean1)):
        subset = 0.18

    combined = seq_score * 0.36 + token_score * 0.36 + containment + subset
    if tokens1 and tokens2:
        overlap = len(tokens1 & tokens2) / len(tokens1 | tokens2)
        combined = max(combined, seq_score * 0.7 + overlap * 0.3)
    return min(1.0, combined)


def min_similarity() -> float:
    try:
        return float(os.environ.get("BETFAIR_MIN_SIMILARITY", DEFAULT_MIN_SIMILARITY))
    except ValueError:
        return DEFAULT_MIN_SIMILARITY


def match_fixture(
    api_home: str, api_away: str, fixtures: list[Fixture], *, threshold: float | None = None
) -> NameMatch | None:
    """Exact (normalised) pair first, then best fuzzy pair. Home/away may be swapped."""
    thr = min_similarity() if threshold is None else threshold
    norm_home = normalize_name(api_home)
    norm_away = normalize_name(api_away)

    best: tuple[str, str] | None = None
    best_score = 0.0
    kind_home = team_kind(api_home)
    kind_away = team_kind(api_away)
    for fx in fixtures:
        kind_fx_home = team_kind(fx.home)
        kind_fx_away = team_kind(fx.away)
        straight_kinds = kind_home == kind_fx_home and kind_away == kind_fx_away
        reverse_kinds = kind_home == kind_fx_away and kind_away == kind_fx_home
        if not (straight_kinds or reverse_kinds):
            continue
        if (
            straight_kinds
            and normalize_name(fx.home) == norm_home
            and normalize_name(fx.away) == norm_away
        ):
            return NameMatch(fx.home, fx.away, METHOD_EXACT, False)
        if (
            reverse_kinds
            and normalize_name(fx.away) == norm_home
            and normalize_name(fx.home) == norm_away
        ):
            return NameMatch(fx.away, fx.home, METHOD_EXACT, False)

        s1 = similarity(api_home, fx.home)
        s2 = similarity(api_away, fx.away)
        s1r = similarity(api_home, fx.away)
        s2r = similarity(api_away, fx.home)
        straight = (s1 + s2) / 2
        reverse = (s1r + s2r) / 2
        if straight >= reverse:
            score = straight
            valid = straight_kinds and s1 >= MIN_INDIVIDUAL and s2 >= MIN_INDIVIDUAL
            pair = (fx.home, fx.away)
        else:
            score = reverse
            valid = reverse_kinds and s1r >= MIN_INDIVIDUAL and s2r >= MIN_INDIVIDUAL
            pair = (fx.away, fx.home)
        if valid and score > best_score and score >= thr:
            best_score = score
            best = pair
    if best:
        return NameMatch(best[0], best[1], METHOD_FUZZY, True)
    return None


def parse_fixtures(content: str) -> list[Fixture]:
    out: list[Fixture] = []
    for row in csv.DictReader(io.StringIO(content)):
        home = _clean(row.get("Home") or row.get("TeamA") or row.get("home") or "")
        away = _clean(row.get("Away") or row.get("TeamB") or row.get("away") or "")
        if home and away:
            out.append(Fixture(home, away, (row.get("OpenDate") or "").strip()))
    return out


_lock = threading.Lock()
_cache: dict[str, Any] = {"at": 0.0, "fixtures": [], "ok": False, "error": None}


def csv_url() -> str:
    return (os.environ.get("BETFAIR_CSV_URL") or DEFAULT_CSV_URL).strip()


def get_fixtures(*, client: httpx.Client | None = None) -> list[Fixture]:
    """Cached gist fixtures. A failed refresh keeps serving the last good list."""
    now = time.monotonic()
    with _lock:
        if _cache["at"] and now - _cache["at"] < CACHE_TTL_SECONDS:
            return _cache["fixtures"]
    http = client or httpx.Client(timeout=15.0, follow_redirects=True)
    try:
        resp = http.get(csv_url())
        resp.raise_for_status()
        fixtures = parse_fixtures(resp.text)
        with _lock:
            _cache.update(at=now, fixtures=fixtures, ok=True, error=None)
        return fixtures
    except (httpx.HTTPError, csv.Error, UnicodeDecodeError) as exc:
        logger.warning("betfair fixture list fetch failed: %s", exc)
        with _lock:
            _cache.update(at=now, ok=False, error=str(exc)[:200])
            return _cache["fixtures"]
    finally:
        if client is None:
            http.close()


def source_status() -> dict[str, Any]:
    """Admin view: how many fixtures are loaded and how far ahead they run."""
    fixtures = get_fixtures()
    dates = sorted(fx.open_date for fx in fixtures if fx.open_date)
    with _lock:
        ok, error = bool(_cache["ok"]), _cache["error"]
    return {
        "fixtures": len(fixtures),
        "newest_open_date": dates[-1] if dates else None,
        "ok": ok,
        "error": error,
    }


def correlate(api_home: str, api_away: str, fixtures: list[Fixture] | None = None) -> NameMatch:
    """Betfair names for an API pair; falls back to the API names (method "none")."""
    pool = get_fixtures() if fixtures is None else fixtures
    found = match_fixture(api_home, api_away, pool) if pool else None
    if found:
        return found
    return NameMatch(api_home, api_away, METHOD_NONE, False)
