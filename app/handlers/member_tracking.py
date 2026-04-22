from __future__ import annotations

from telegram import ChatMemberUpdated, Update
from telegram.ext import ContextTypes

from app.observability.logging import get_logger
from app.services.invite_links import attribute_join

log = get_logger(__name__)


async def on_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Attribute channel joins to the invite link they used.

    Telegram sends a ``chat_member`` update when a user's status changes.
    When someone joins via an invite link we created, the payload's
    ``invite_link`` field is populated with our link object.
    """
    cmu: ChatMemberUpdated | None = update.chat_member
    if cmu is None:
        return

    old = cmu.old_chat_member.status
    new = cmu.new_chat_member.status
    joined = old in {"left", "kicked"} and new in {"member", "restricted"}

    if not joined:
        return

    invite = cmu.invite_link
    if not invite:
        log.info(
            "member.joined_without_invite",
            user_id=cmu.new_chat_member.user.id,
            chat_id=cmu.chat.id,
        )
        return

    campaign_id = await attribute_join(invite.invite_link)
    log.info(
        "member.joined",
        user_id=cmu.new_chat_member.user.id,
        chat_id=cmu.chat.id,
        invite_link=invite.invite_link,
        campaign_id=campaign_id,
    )
