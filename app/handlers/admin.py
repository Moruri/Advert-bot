from __future__ import annotations

from functools import wraps
from typing import Any, Awaitable, Callable

from sqlalchemy import func, select
from telegram import Update
from telegram.ext import ContextTypes

from app.config import get_settings
from app.db.models import Broadcast, Campaign, InviteLink, TargetChat
from app.db.session import session_scope
from app.observability.logging import get_logger
from app.observability.metrics import active_campaigns_gauge
from app.services.broadcaster import Broadcaster
from app.services.invite_links import ensure_campaign, mint_invite_link

log = get_logger(__name__)

Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[Any]]


def admin_only(func: Handler) -> Handler:
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Any:
        user = update.effective_user
        if not user or user.id not in get_settings().admin_ids:
            if update.message:
                await update.message.reply_text("Not authorized.")
            log.warning("admin.unauthorized", user_id=user.id if user else None)
            return
        return await func(update, context)

    return wrapper


@admin_only
async def campaign_new(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: /campaign_new <name> <source> [creative text...]"
        )
        return

    name, source, *rest = args
    creative = " ".join(rest) or f"Check out our channel — {name}"

    campaign = await ensure_campaign(
        name=name,
        source=source,
        creative_text=creative,
        creator_id=update.effective_user.id,
    )
    link = await mint_invite_link(
        bot=context.bot,
        campaign_id=campaign.id,
        name=f"{name}-{campaign.token}",
    )

    async with session_scope() as s:
        total = (
            await s.execute(
                select(func.count()).select_from(Campaign).where(Campaign.active == True)  # noqa: E712
            )
        ).scalar_one()
    active_campaigns_gauge.set(total)

    await update.message.reply_text(
        f"Campaign #{campaign.id} created.\n"
        f"Token: {campaign.token}\n"
        f"Invite link: {link.invite_link}\n"
        f"Ad final URL: https://t.me/{get_settings().bot_username or '<bot_username>'}"
        f"?start={campaign.token}"
    )


@admin_only
async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    args = context.args or []
    if len(args) < 1 or not args[0].isdigit():
        await update.message.reply_text("Usage: /broadcast <campaign_id>")
        return

    campaign_id = int(args[0])
    async with session_scope() as s:
        chats = (
            await s.execute(
                select(TargetChat.chat_id).where(TargetChat.opted_out == False)  # noqa: E712
            )
        ).scalars().all()

    if not chats:
        await update.message.reply_text("No target chats configured.")
        return

    broadcaster: Broadcaster = context.bot_data["broadcaster"]
    result = await broadcaster.broadcast(campaign_id, chats)
    await update.message.reply_text(
        f"Broadcast complete. sent={result.sent} failed={result.failed} skipped={result.skipped}"
    )


@admin_only
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    async with session_scope() as s:
        campaigns = (await s.execute(select(Campaign).order_by(Campaign.created_at.desc()))).scalars().all()
        lines = ["<b>Campaign stats</b>"]
        for c in campaigns[:20]:
            joins = (
                await s.execute(
                    select(func.coalesce(func.sum(InviteLink.joins), 0)).where(
                        InviteLink.campaign_id == c.id
                    )
                )
            ).scalar_one()
            sent = (
                await s.execute(
                    select(func.count())
                    .select_from(Broadcast)
                    .where(Broadcast.campaign_id == c.id, Broadcast.status == "sent")
                )
            ).scalar_one()
            lines.append(
                f"#{c.id} <b>{c.name}</b> src={c.source} sent={sent} joins={joins} active={c.active}"
            )
        if len(lines) == 1:
            lines.append("(no campaigns yet)")
    await update.message.reply_html("\n".join(lines))
