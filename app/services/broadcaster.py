from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Iterable, Optional

from sqlalchemy import select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import Forbidden, RetryAfter, TelegramError
from telegram.ext import Application

from app.config import get_settings
from app.db.models import Broadcast, Campaign, InviteLink
from app.db.session import session_scope
from app.observability.logging import get_logger
from app.observability.metrics import broadcasts_sent_total

log = get_logger(__name__)


class TokenBucket:
    """Simple async token bucket rate limiter."""

    def __init__(self, rate_per_sec: float, capacity: Optional[float] = None) -> None:
        self.rate = rate_per_sec
        self.capacity = capacity or max(1.0, rate_per_sec)
        self._tokens = self.capacity
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, amount: float = 1.0) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self._updated
                self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
                self._updated = now
                if self._tokens >= amount:
                    self._tokens -= amount
                    return
                deficit = amount - self._tokens
                wait = deficit / self.rate
                await asyncio.sleep(wait)


@dataclass
class BroadcastResult:
    sent: int
    failed: int
    skipped: int


class Broadcaster:
    def __init__(self, application: Application) -> None:
        settings = get_settings()
        self.app = application
        self.global_bucket = TokenBucket(settings.broadcast_rate_global_per_sec)
        self._per_chat_buckets: dict[int, TokenBucket] = {}
        self._per_chat_rate = settings.broadcast_rate_per_chat_per_min / 60.0

    def _chat_bucket(self, chat_id: int) -> TokenBucket:
        bucket = self._per_chat_buckets.get(chat_id)
        if bucket is None:
            bucket = TokenBucket(self._per_chat_rate, capacity=1.0)
            self._per_chat_buckets[chat_id] = bucket
        return bucket

    async def _send_one(
        self,
        chat_id: int,
        campaign: Campaign,
        invite_link: InviteLink,
    ) -> tuple[str, Optional[str]]:
        await self.global_bucket.acquire()
        await self._chat_bucket(chat_id).acquire()

        reply_markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton(text="Join the channel", url=invite_link.invite_link)]]
        )

        try:
            if campaign.creative_media_file_id:
                await self.app.bot.send_photo(
                    chat_id=chat_id,
                    photo=campaign.creative_media_file_id,
                    caption=campaign.creative_text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML,
                )
            else:
                await self.app.bot.send_message(
                    chat_id=chat_id,
                    text=campaign.creative_text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=False,
                )
            return "sent", None
        except RetryAfter as e:
            log.warning("broadcast.retry_after", chat_id=chat_id, seconds=e.retry_after)
            await asyncio.sleep(float(e.retry_after) + 1.0)
            return "retry", str(e)
        except Forbidden as e:
            return "forbidden", str(e)
        except TelegramError as e:
            return "failed", str(e)

    async def broadcast(
        self,
        campaign_id: int,
        chat_ids: Iterable[int],
    ) -> BroadcastResult:
        chat_list = list(dict.fromkeys(chat_ids))
        sent = failed = skipped = 0

        async with session_scope() as s:
            campaign = (
                await s.execute(select(Campaign).where(Campaign.id == campaign_id))
            ).scalar_one_or_none()
            if campaign is None or not campaign.active:
                log.error("broadcast.campaign_missing_or_inactive", campaign_id=campaign_id)
                return BroadcastResult(0, 0, len(chat_list))

            link = (
                await s.execute(
                    select(InviteLink)
                    .where(InviteLink.campaign_id == campaign_id)
                    .order_by(InviteLink.created_at.desc())
                )
            ).scalars().first()
            if link is None:
                log.error("broadcast.no_invite_link", campaign_id=campaign_id)
                return BroadcastResult(0, 0, len(chat_list))

        for chat_id in chat_list:
            status, err = await self._send_one(chat_id, campaign, link)
            if status == "retry":
                status, err = await self._send_one(chat_id, campaign, link)

            async with session_scope() as s:
                s.add(
                    Broadcast(
                        campaign_id=campaign_id,
                        chat_id=chat_id,
                        status=status,
                        error=err,
                    )
                )

            broadcasts_sent_total.labels(campaign=str(campaign_id), outcome=status).inc()
            if status == "sent":
                sent += 1
            elif status == "forbidden":
                skipped += 1
            else:
                failed += 1
                log.warning("broadcast.failed", chat_id=chat_id, error=err)

        log.info(
            "broadcast.done",
            campaign_id=campaign_id,
            sent=sent,
            failed=failed,
            skipped=skipped,
        )
        return BroadcastResult(sent=sent, failed=failed, skipped=skipped)
