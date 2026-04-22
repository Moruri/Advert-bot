from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from telegram import Bot

from app.config import get_settings
from app.db.models import Campaign, InviteLink
from app.db.session import session_scope
from app.observability.logging import get_logger
from app.observability.metrics import invite_links_created_total, joins_attributed_total

log = get_logger(__name__)


def _token() -> str:
    return secrets.token_urlsafe(8)


async def ensure_campaign(
    name: str,
    source: str,
    creative_text: str,
    creator_id: int,
    creative_media_file_id: Optional[str] = None,
) -> Campaign:
    async with session_scope() as s:
        camp = Campaign(
            token=_token(),
            name=name,
            source=source,
            creative_text=creative_text,
            creative_media_file_id=creative_media_file_id,
            created_by=creator_id,
            active=True,
        )
        s.add(camp)
        await s.flush()
        await s.refresh(camp)
        log.info("campaign.created", campaign_id=camp.id, token=camp.token, name=name)
        return camp


async def mint_invite_link(
    bot: Bot,
    campaign_id: int,
    name: str,
    member_limit: Optional[int] = None,
    expire_in_days: Optional[int] = 30,
) -> InviteLink:
    settings = get_settings()
    expire_dt: Optional[datetime] = (
        datetime.now(tz=timezone.utc) + timedelta(days=expire_in_days)
        if expire_in_days
        else None
    )

    tg_link = await bot.create_chat_invite_link(
        chat_id=settings.telegram_channel_id,
        name=name[:32],
        member_limit=member_limit,
        expire_date=expire_dt,
    )

    async with session_scope() as s:
        record = InviteLink(
            campaign_id=campaign_id,
            invite_link=tg_link.invite_link,
            name=name,
            member_limit=member_limit,
            expire_date=expire_dt,
        )
        s.add(record)
        await s.flush()
        await s.refresh(record)

    invite_links_created_total.labels(campaign=str(campaign_id)).inc()
    log.info(
        "invite_link.created",
        campaign_id=campaign_id,
        invite_link=tg_link.invite_link,
        name=name,
    )
    return record


async def attribute_join(invite_link_url: str) -> Optional[int]:
    """Increment join counter for the given invite link, return campaign_id if matched."""
    async with session_scope() as s:
        stmt = select(InviteLink).where(InviteLink.invite_link == invite_link_url)
        row = (await s.execute(stmt)).scalar_one_or_none()
        if row is None:
            log.warning("invite_link.unknown", invite_link=invite_link_url)
            return None
        row.joins += 1
        joins_attributed_total.labels(campaign=str(row.campaign_id)).inc()
        log.info(
            "invite_link.join_attributed",
            campaign_id=row.campaign_id,
            invite_link=invite_link_url,
            joins=row.joins,
        )
        return row.campaign_id
