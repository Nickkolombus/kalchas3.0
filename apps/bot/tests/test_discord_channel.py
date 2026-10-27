"""Discord bot REST calls: markdown conversion, env lookup, send/edit/react/reply."""

from __future__ import annotations

import httpx
import pytest
from kalchas_bot.discord_channel import (
    discord_bot_token,
    edit_discord_message,
    html_to_discord,
    react_discord_message,
    reply_discord_message,
    send_discord_message,
)


class TestDiscordBotToken:
    def test_reads_from_env(self) -> None:
        assert discord_bot_token({"DISCORD_BOT_TOKEN": "abc.def.ghi"}) == "abc.def.ghi"

    def test_blank_is_none(self) -> None:
        assert discord_bot_token({"DISCORD_BOT_TOKEN": "  "}) is None
        assert discord_bot_token({}) is None


class TestHtmlToDiscord:
    def test_bold_and_italic_become_markdown(self) -> None:
        assert html_to_discord("<b>Form Bar</b>: <i>Arsenal</i>") == "**Form Bar**: *Arsenal*"

    def test_unknown_tags_are_dropped(self) -> None:
        assert html_to_discord("plain <u>text</u>") == "plain text"

    def test_entities_are_unescaped(self) -> None:
        assert html_to_discord("Arsenal &amp; Chelsea") == "Arsenal & Chelsea"


class TestSendDiscordMessage:
    @pytest.mark.asyncio
    async def test_posts_json_without_a_photo(self) -> None:
        calls: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json={"id": "123"})

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            message_id = await send_discord_message(
                "tok", "456", photo_bytes=None, caption="<b>Form Bar</b>", client=client
            )
        assert message_id == 123
        assert len(calls) == 1
        assert calls[0].headers["authorization"] == "Bot tok"
        assert calls[0].headers["content-type"] == "application/json"

    @pytest.mark.asyncio
    async def test_posts_multipart_with_a_photo(self) -> None:
        calls: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json={"id": "789"})

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            message_id = await send_discord_message(
                "tok", "456", photo_bytes=b"\x89PNG", caption="<b>Form Bar</b>", client=client
            )
        assert message_id == 789
        assert calls[0].headers["content-type"].startswith("multipart/form-data")

    @pytest.mark.asyncio
    async def test_a_failed_post_returns_none(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            message_id = await send_discord_message(
                "tok", "456", photo_bytes=None, caption="x", client=client
            )
        assert message_id is None


class TestEditDiscordMessage:
    @pytest.mark.asyncio
    async def test_patches_content(self) -> None:
        calls: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json={"id": "123"})

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            await edit_discord_message("tok", "456", 123, caption="<b>x</b>", client=client)
        assert len(calls) == 1
        assert calls[0].method == "PATCH"

    @pytest.mark.asyncio
    async def test_a_failed_edit_does_not_raise(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            await edit_discord_message(
                "tok", "456", 123, caption="x", client=client
            )  # must not raise


class TestReplyDiscordMessage:
    @pytest.mark.asyncio
    async def test_sends_with_message_reference(self) -> None:
        calls: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json={"id": "321"})

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            message_id = await reply_discord_message(
                "tok", "456", text="goal", reply_to_message_id=123, client=client
            )
        assert message_id == 321
        import json as _json

        body = _json.loads(calls[0].content)
        assert body["message_reference"] == {"message_id": "123"}

    @pytest.mark.asyncio
    async def test_a_failed_reply_returns_none(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            message_id = await reply_discord_message(
                "tok", "456", text="x", reply_to_message_id=123, client=client
            )
        assert message_id is None


class TestReactDiscordMessage:
    @pytest.mark.asyncio
    async def test_puts_own_reaction(self) -> None:
        calls: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(204)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            await react_discord_message("tok", "456", 123, "✅", client=client)
        assert len(calls) == 1
        assert calls[0].method == "PUT"
        assert str(calls[0].url).endswith("/reactions/%E2%9C%85/@me")

    @pytest.mark.asyncio
    async def test_a_failed_reaction_does_not_raise(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            await react_discord_message("tok", "456", 123, "✅", client=client)  # must not raise
