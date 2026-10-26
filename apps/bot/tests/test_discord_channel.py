"""Discord webhook cross-post: markdown conversion and env lookup."""

from __future__ import annotations

import httpx
import pytest
from kalchas_bot.discord_channel import (
    discord_paid_webhook_url,
    discord_webhook_url,
    html_to_discord,
    send_discord_alert,
)


class TestDiscordWebhookUrl:
    def test_reads_from_env(self) -> None:
        assert discord_webhook_url({"DISCORD_WEBHOOK_URL": "https://discord.com/x"}) == (
            "https://discord.com/x"
        )

    def test_blank_is_none(self) -> None:
        assert discord_webhook_url({"DISCORD_WEBHOOK_URL": "  "}) is None
        assert discord_webhook_url({}) is None


class TestDiscordPaidWebhookUrl:
    def test_reads_from_env(self) -> None:
        assert discord_paid_webhook_url({"DISCORD_PAID_WEBHOOK_URL": "https://discord.com/y"}) == (
            "https://discord.com/y"
        )

    def test_blank_is_none(self) -> None:
        assert discord_paid_webhook_url({"DISCORD_PAID_WEBHOOK_URL": "  "}) is None
        assert discord_paid_webhook_url({}) is None


class TestHtmlToDiscord:
    def test_bold_and_italic_become_markdown(self) -> None:
        assert html_to_discord("<b>Form Bar</b>: <i>Arsenal</i>") == "**Form Bar**: *Arsenal*"

    def test_unknown_tags_are_dropped(self) -> None:
        assert html_to_discord("plain <u>text</u>") == "plain text"

    def test_entities_are_unescaped(self) -> None:
        assert html_to_discord("Arsenal &amp; Chelsea") == "Arsenal & Chelsea"


class TestSendDiscordAlert:
    @pytest.mark.asyncio
    async def test_posts_json_without_a_photo(self) -> None:
        calls: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(204)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            await send_discord_alert(
                "https://discord.com/api/webhooks/1/abc",
                photo_bytes=None,
                caption="<b>Form Bar</b>",
                client=client,
            )
        assert len(calls) == 1
        assert calls[0].headers["content-type"] == "application/json"

    @pytest.mark.asyncio
    async def test_posts_multipart_with_a_photo(self) -> None:
        calls: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(204)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            await send_discord_alert(
                "https://discord.com/api/webhooks/1/abc",
                photo_bytes=b"\x89PNG",
                caption="<b>Form Bar</b>",
                client=client,
            )
        assert len(calls) == 1
        assert calls[0].headers["content-type"].startswith("multipart/form-data")

    @pytest.mark.asyncio
    async def test_a_failed_post_is_swallowed(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            await send_discord_alert(
                "https://discord.com/api/webhooks/1/abc",
                photo_bytes=None,
                caption="x",
                client=client,
            )  # must not raise
