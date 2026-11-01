"""X/Twitter: env gate, plain-text conversion, threading, OAuth 1.0a, REST calls."""

from __future__ import annotations

import json

import httpx
import pytest
from kalchas_bot.twitter_channel import (
    TwitterCredentials,
    html_to_tweet,
    match_link,
    oauth1_header,
    post_alert_tweet,
    reply_tweet,
    thread_chunks,
    tweet_weight,
    twitter_credentials,
)

CREDS = TwitterCredentials(
    "xvz1evFS4wEEPTGEFPHBog",
    "kAcSOqF21Fu85e7zjz7ZN2U4ZRhfV3WpwPAoE3Z7kBw",
    "370773112-GmHxMAgYyLbNEtIKZeRNFsMKPR9EyMZeS9weJAEb",
    "LswwdoUaIvS8ltyTt5jkRh4J50vUBVVHVk6ZQRtfzWVq",
)

FULL_ENV = {
    "TWITTER_POSTING_ENABLED": "true",
    "TWITTER_API_KEY": "k",
    "TWITTER_API_SECRET": "ks",
    "TWITTER_ACCESS_TOKEN": "t",
    "TWITTER_ACCESS_TOKEN_SECRET": "ts",
}


class TestTwitterCredentials:
    def test_enabled_with_all_keys(self) -> None:
        assert twitter_credentials(FULL_ENV) == TwitterCredentials("k", "ks", "t", "ts")

    def test_disabled_flag_is_none(self) -> None:
        assert twitter_credentials({**FULL_ENV, "TWITTER_POSTING_ENABLED": "false"}) is None
        assert (
            twitter_credentials(
                {k: v for k, v in FULL_ENV.items() if k != "TWITTER_POSTING_ENABLED"}
            )
            is None
        )

    def test_missing_key_is_none(self) -> None:
        assert twitter_credentials({**FULL_ENV, "TWITTER_ACCESS_TOKEN_SECRET": " "}) is None


class TestText:
    def test_tags_dropped_and_entities_unescaped(self) -> None:
        assert html_to_tweet("<b>A &amp; B</b> vs C\n<i>League</i>") == "A & B vs C\nLeague"

    def test_match_link(self) -> None:
        assert match_link(1234) == "https://kalchas.live/?match=1234"
        assert match_link(None) == "https://kalchas.live/"

    def test_weight_counts_urls_as_23_and_emoji_as_2(self) -> None:
        assert tweet_weight("abc") == 3
        assert tweet_weight("⚽") == 2
        assert tweet_weight("67′") == 3
        assert tweet_weight("go https://kalchas.live/?match=123456789") == 3 + 23

    def test_short_text_is_one_tweet_with_link(self) -> None:
        chunks = thread_chunks("A vs B · 67′\nLeague", link="https://kalchas.live/?match=1")
        assert chunks == ["A vs B · 67′\nLeague\n\n↳ https://kalchas.live/?match=1"]

    def test_long_text_threads_with_link_in_first_tweet(self) -> None:
        lines = [f"Line {i}: " + "x" * 40 for i in range(12)]
        link = "https://kalchas.live/?match=1"
        chunks = thread_chunks("\n".join(lines), link=link)
        assert len(chunks) > 1
        assert chunks[0].endswith(f"↳ {link}")
        assert all(link not in chunk for chunk in chunks[1:])
        assert all(tweet_weight(chunk) <= 280 for chunk in chunks)
        rebuilt = "\n".join(chunks).replace(f"\n\n↳ {link}", "")
        assert all(line in rebuilt for line in lines)


class TestOauth1:
    def test_signature_matches_oauthlib(self) -> None:
        # Reference values produced by oauthlib.oauth1.Client for the same inputs.
        header = oauth1_header(
            "POST",
            "https://api.x.com/2/tweets",
            CREDS,
            nonce="kYjzVBB8Y0ZFabxSWbWovY3uYSQ2pTgmZeNu2VS4cg",
            timestamp="1318622958",
        )
        assert header.startswith("OAuth ")
        assert 'oauth_signature="icQDx5njdJFuxkU1R5rLzJaS7x4%3D"' in header
        assert 'oauth_consumer_key="xvz1evFS4wEEPTGEFPHBog"' in header


class TestPosting:
    @pytest.mark.asyncio
    async def test_alert_uploads_banner_then_tweets_with_media(self) -> None:
        calls: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if request.url.path == "/2/media/upload":
                return httpx.Response(200, json={"data": {"id": "m1"}})
            return httpx.Response(201, json={"data": {"id": "t1"}})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            tweet_id = await post_alert_tweet(
                CREDS,
                caption="<b>A</b> vs B · 67′",
                match_id="55",
                photo_bytes=b"png",
                client=client,
            )
        assert tweet_id == "t1"
        assert [c.url.path for c in calls] == ["/2/media/upload", "/2/tweets"]
        assert all(c.headers["authorization"].startswith("OAuth ") for c in calls)
        body = json.loads(calls[1].content)
        assert body["media"] == {"media_ids": ["m1"]}
        assert body["text"] == "A vs B · 67′\n\n↳ https://kalchas.live/?match=55"
        assert "reply" not in body

    @pytest.mark.asyncio
    async def test_failed_upload_still_tweets_text(self) -> None:
        bodies: list[dict[str, object]] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/2/media/upload":
                return httpx.Response(403, json={"title": "Forbidden"})
            bodies.append(json.loads(request.content))
            return httpx.Response(201, json={"data": {"id": "t1"}})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            tweet_id = await post_alert_tweet(
                CREDS, caption="A vs B", match_id="1", photo_bytes=b"png", client=client
            )
        assert tweet_id == "t1"
        assert "media" not in bodies[0]

    @pytest.mark.asyncio
    async def test_api_error_returns_none(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"title": "Too Many Requests"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert (
                await post_alert_tweet(
                    CREDS, caption="A vs B", match_id="1", photo_bytes=None, client=client
                )
                is None
            )

    @pytest.mark.asyncio
    async def test_reply_threads_under_the_alert_tweet(self) -> None:
        bodies: list[dict[str, object]] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            bodies.append(json.loads(request.content))
            return httpx.Response(201, json={"data": {"id": "r1"}})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            reply_id = await reply_tweet(CREDS, "✅ <b>GOAL</b> at 71′", "t1", client=client)
        assert reply_id == "r1"
        assert bodies == [{"text": "✅ GOAL at 71′", "reply": {"in_reply_to_tweet_id": "t1"}}]
