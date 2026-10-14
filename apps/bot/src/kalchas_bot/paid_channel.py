"""Paid Telegram destination. InviteMember gates who is in this channel."""

from __future__ import annotations

import os
from collections.abc import Mapping


def paid_chat_id(env: Mapping[str, str] | None = None) -> str | None:
    """Prefer ``TIPS_CHANNEL_ID`` (Kalchas_Tips_Premium). Fall back to the old name."""
    source = env if env is not None else os.environ
    for key in ("TIPS_CHANNEL_ID", "TELEGRAM_CHAT_ID"):
        value = (source.get(key) or "").strip()
        if value:
            return value
    return None
