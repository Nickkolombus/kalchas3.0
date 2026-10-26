"""Paid-channel join tracking: matching a new member to the invite link used."""

from __future__ import annotations

from types import SimpleNamespace

from kalchas_bot.paid_join import joined_via_invite


def _update(*, old_status: str, new_status: str, invite_link: str | None, user_id: int = 42):
    link = SimpleNamespace(invite_link=invite_link) if invite_link else None
    return SimpleNamespace(
        old_chat_member=SimpleNamespace(status=old_status),
        new_chat_member=SimpleNamespace(status=new_status, user=SimpleNamespace(id=user_id)),
        invite_link=link,
    )


def test_join_via_invite_link_is_matched() -> None:
    update = _update(old_status="left", new_status="member", invite_link="https://t.me/+abc")
    assert joined_via_invite(update) == (42, "https://t.me/+abc")


def test_join_without_an_invite_link_is_ignored() -> None:
    update = _update(old_status="left", new_status="member", invite_link=None)
    assert joined_via_invite(update) is None


def test_non_join_transition_is_ignored() -> None:
    update = _update(old_status="member", new_status="left", invite_link="https://t.me/+abc")
    assert joined_via_invite(update) is None


def test_already_a_member_is_ignored() -> None:
    update = _update(old_status="member", new_status="member", invite_link="https://t.me/+abc")
    assert joined_via_invite(update) is None
