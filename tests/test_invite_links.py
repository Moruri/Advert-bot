from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "0:test")
os.environ.setdefault("TELEGRAM_CHANNEL_ID", "-1001234567890")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import pytest

from app.db.session import engine, init_db, session_scope
from app.db.models import Base
from app.services.invite_links import attribute_join, ensure_campaign, mint_invite_link


@pytest.fixture(autouse=True)
async def _fresh_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.mark.asyncio
async def test_ensure_campaign_persists() -> None:
    camp = await ensure_campaign(
        name="ukcamp1",
        source="google_ads",
        creative_text="Join our channel",
        creator_id=42,
    )
    assert camp.id is not None
    assert camp.token
    assert camp.active is True


@pytest.mark.asyncio
async def test_mint_and_attribute_join() -> None:
    camp = await ensure_campaign(
        name="ukcamp1",
        source="google_ads",
        creative_text="Join",
        creator_id=42,
    )

    fake_link = MagicMock()
    fake_link.invite_link = "https://t.me/+abc123xyz"
    bot = MagicMock()
    bot.create_chat_invite_link = AsyncMock(return_value=fake_link)

    record = await mint_invite_link(bot=bot, campaign_id=camp.id, name="ukcamp1-main")
    bot.create_chat_invite_link.assert_awaited_once()
    assert record.invite_link == fake_link.invite_link
    assert record.joins == 0

    matched_campaign = await attribute_join(fake_link.invite_link)
    assert matched_campaign == camp.id

    async with session_scope() as s:
        refreshed = await s.get(type(record), record.id)
        assert refreshed is not None
        assert refreshed.joins == 1


@pytest.mark.asyncio
async def test_attribute_unknown_link_returns_none() -> None:
    result = await attribute_join("https://t.me/+not-real")
    assert result is None
