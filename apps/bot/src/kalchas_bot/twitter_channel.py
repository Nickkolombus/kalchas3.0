"""X/Twitter cross-post of free-channel fires, ported from 2.2's twitter_poster.

Same mechanics as 2.2: OAuth 1.0a user context (Bearer tokens are read-only),
the banner uploaded as media on the first tweet, a thread when the text runs
past 280, and the outcome posted as a reply under the original tweet. Only
fires that reach the free Telegram channel come here.

Every call is best effort: logged and swallowed, never allowed to break
Telegram delivery.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import logging
import os
import re
import secrets
import time
import urllib.parse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import httpx

logger = logging.getLogger("kalchas.bot.twitter")

API_BASE = "https://api.x.com/2"
TWEET_LIMIT = 280
URL_WEIGHT = 23
SITE_URL = "https://kalchas.live/"

_TAG = re.compile(r"<[^>]+>")
_URL = re.compile(r"https?://\S+")
_BLANKS = re.compile(r"\n{3,}")
# twitter-text v3: these code points weigh 1, everything else (emoji, arrows,
# CJK) weighs 2.
_LIGHT_RANGES = ((0, 4351), (8192, 8205), (8208, 8223), (8242, 8247))
_CREDENTIAL_ENV = (
    "TWITTER_API_KEY",
    "TWITTER_API_SECRET",
    "TWITTER_ACCESS_TOKEN",
    "TWITTER_ACCESS_TOKEN_SECRET",
)


@dataclass(frozen=True)
class TwitterCredentials:
    api_key: str
    api_secret: str
    access_token: str
    access_token_secret: str


def twitter_credentials(env: Mapping[str, str] | None = None) -> TwitterCredentials | None:
    """None unless TWITTER_POSTING_ENABLED=true and all four OAuth 1.0a keys are set."""
    source = env if env is not None else os.environ
    if (source.get("TWITTER_POSTING_ENABLED") or "").strip().lower() != "true":
        return None
    values = [(source.get(name) or "").strip() for name in _CREDENTIAL_ENV]
    missing = [name for name, value in zip(_CREDENTIAL_ENV, values, strict=True) if not value]
    if missing:
        logger.warning("twitter posting enabled but missing %s", ", ".join(missing))
        return None
    return TwitterCredentials(*values)


def match_link(match_id: object) -> str:
    match = str(match_id or "").strip()
    if not match:
        return SITE_URL
    return f"{SITE_URL}?match={urllib.parse.quote(match, safe='')}"


def html_to_tweet(text: str) -> str:
    """Telegram HTML caption -> plain text. X has no bold or italics."""
    out = html.unescape(_TAG.sub("", text))
    return _BLANKS.sub("\n\n", out).strip()


def tweet_weight(text: str) -> int:
    """Length as X counts it: URLs are 23, emoji and most symbols are 2."""
    total = 0
    last = 0
    for found in _URL.finditer(text):
        total += _char_weight(text[last : found.start()]) + URL_WEIGHT
        last = found.end()
    return total + _char_weight(text[last:])


def _char_weight(text: str) -> int:
    return sum(
        1 if any(low <= ord(ch) <= high for low, high in _LIGHT_RANGES) else 2 for ch in text
    )


def thread_chunks(text: str, *, link: str | None = None, limit: int = TWEET_LIMIT) -> list[str]:
    """Split on line boundaries. The link always lands in the first tweet."""
    tail = f"\n\n↳ {link}" if link else ""
    chunks: list[str] = []
    current: list[str] = []
    for line in text.split("\n"):
        reserve = tail if not chunks else ""
        candidate = "\n".join([*current, line]).strip("\n") + reserve
        if current and tweet_weight(candidate) > limit:
            chunks.append("\n".join(current).strip("\n") + reserve)
            current = [line] if line.strip() else []
        else:
            current.append(line)
    rest = "\n".join(current).strip("\n")
    if rest or not chunks:
        chunks.append(rest + (tail if not chunks else ""))
    return [_hard_clip(chunk.strip(), limit) for chunk in chunks if chunk.strip()]


def _hard_clip(text: str, limit: int) -> str:
    if tweet_weight(text) <= limit:
        return text
    while text and tweet_weight(text + "…") > limit:
        text = text[:-1]
    return text + "…"


def _quote(value: str) -> str:
    return urllib.parse.quote(value, safe="~")


def oauth1_header(
    method: str,
    url: str,
    creds: TwitterCredentials,
    *,
    params: Mapping[str, str] | None = None,
    nonce: str | None = None,
    timestamp: str | None = None,
) -> str:
    """OAuth 1.0a HMAC-SHA1 Authorization header.

    JSON and multipart bodies are not part of the signature; only the oauth_*
    fields and any query or form-encoded ``params`` are.
    """
    oauth = {
        "oauth_consumer_key": creds.api_key,
        "oauth_nonce": nonce or secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": timestamp or str(int(time.time())),
        "oauth_token": creds.access_token,
        "oauth_version": "1.0",
    }
    signed = {**oauth, **(params or {})}
    pairs = sorted((_quote(key), _quote(value)) for key, value in signed.items())
    param_string = "&".join(f"{key}={value}" for key, value in pairs)
    base = "&".join((method.upper(), _quote(url), _quote(param_string)))
    key = f"{_quote(creds.api_secret)}&{_quote(creds.access_token_secret)}"
    digest = hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()
    oauth["oauth_signature"] = base64.b64encode(digest).decode()
    fields = ", ".join(f'{_quote(key)}="{_quote(value)}"' for key, value in sorted(oauth.items()))
    return f"OAuth {fields}"


async def upload_media(
    creds: TwitterCredentials,
    image: bytes,
    *,
    client: httpx.AsyncClient,
) -> str | None:
    url = f"{API_BASE}/media/upload"
    try:
        response = await client.post(
            url,
            headers={"Authorization": oauth1_header("POST", url, creds)},
            data={"media_category": "tweet_image", "media_type": "image/png"},
            files={"media": ("alert.png", image, "image/png")},
        )
        response.raise_for_status()
        body = response.json()
        data = body.get("data") if isinstance(body, dict) else None
        media_id = (data or {}).get("id") or body.get("media_id_string")
        return str(media_id) if media_id else None
    except Exception:
        logger.exception("twitter media upload failed")
        return None


async def post_tweet(
    creds: TwitterCredentials,
    text: str,
    *,
    media_id: str | None = None,
    reply_to: str | None = None,
    client: httpx.AsyncClient,
) -> str | None:
    """Post one tweet. Returns its id, or None on failure."""
    url = f"{API_BASE}/tweets"
    body: dict[str, object] = {"text": text}
    if media_id:
        body["media"] = {"media_ids": [media_id]}
    if reply_to:
        body["reply"] = {"in_reply_to_tweet_id": str(reply_to)}
    try:
        response = await client.post(
            url,
            headers={"Authorization": oauth1_header("POST", url, creds)},
            json=body,
        )
        if response.status_code >= 400:
            logger.warning("twitter post %s: %s", response.status_code, response.text[:500])
            return None
        tweet_id = response.json().get("data", {}).get("id")
        return str(tweet_id) if tweet_id else None
    except Exception:
        logger.exception("twitter post failed")
        return None


async def post_thread(
    creds: TwitterCredentials,
    chunks: Sequence[str],
    *,
    photo_bytes: bytes | None = None,
    reply_to: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> str | None:
    """Post chunks as a reply chain. Returns the first tweet's id."""
    if not chunks:
        return None
    owns_client = client is None
    http_client = client or httpx.AsyncClient(timeout=30.0)
    try:
        media_id = None
        if photo_bytes is not None:
            media_id = await upload_media(creds, photo_bytes, client=http_client)
            if media_id is None:
                logger.warning("twitter banner upload failed, posting text only")
        first: str | None = None
        previous = reply_to
        for index, chunk in enumerate(chunks):
            tweet_id = await post_tweet(
                creds,
                chunk,
                media_id=media_id if index == 0 else None,
                reply_to=previous,
                client=http_client,
            )
            if tweet_id is None:
                break
            first = first or tweet_id
            previous = tweet_id
        return first
    finally:
        if owns_client:
            await http_client.aclose()


async def post_alert_tweet(
    creds: TwitterCredentials,
    *,
    caption: str,
    match_id: object,
    photo_bytes: bytes | None,
    client: httpx.AsyncClient | None = None,
) -> str | None:
    """The free-channel caption as a tweet (thread if long) with a link to the match."""
    chunks = thread_chunks(html_to_tweet(caption), link=match_link(match_id))
    return await post_thread(creds, chunks, photo_bytes=photo_bytes, client=client)


async def reply_tweet(
    creds: TwitterCredentials,
    text: str,
    reply_to: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> str | None:
    """Outcome reply under the original alert tweet."""
    return await post_thread(
        creds, thread_chunks(html_to_tweet(text)), reply_to=reply_to, client=client
    )
