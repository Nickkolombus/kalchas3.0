"""Paid channel env: TIPS_CHANNEL_ID wins over the legacy name."""

from kalchas_bot.paid_channel import paid_chat_id

PREMIUM = "-1002915748607"


def test_tips_channel_id_wins_over_legacy_name() -> None:
    assert (
        paid_chat_id(
            {
                "TIPS_CHANNEL_ID": PREMIUM,
                "TELEGRAM_CHAT_ID": "-1000000000000",
            }
        )
        == PREMIUM
    )


def test_legacy_telegram_chat_id_still_works() -> None:
    assert paid_chat_id({"TELEGRAM_CHAT_ID": PREMIUM}) == PREMIUM


def test_blank_is_missing() -> None:
    assert paid_chat_id({"TIPS_CHANNEL_ID": "  ", "TELEGRAM_CHAT_ID": ""}) is None
