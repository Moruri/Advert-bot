from __future__ import annotations

import os

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "0:test")
os.environ.setdefault("TELEGRAM_CHANNEL_ID", "-1001234567890")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("GOOGLE_ADS_ENABLED", "false")

import httpx
import pytest
import respx

from app.adapters.google_ads import GoogleAdsAdapter


@pytest.mark.asyncio
async def test_adapter_is_noop_when_disabled() -> None:
    adapter = GoogleAdsAdapter()
    assert adapter.enabled is False

    campaign_id = await adapter.create_campaign(
        name="uk_search_q2",
        budget_micros=5_000_000,
        final_url="https://t.me/advert_bot?start=ukcamp1",
    )
    assert campaign_id.startswith("stub-")

    conversions = await adapter.get_conversions(campaign_id)
    assert conversions == []

    reported = await adapter.report_click(
        campaign_id=campaign_id,
        user_id=12345,
        gclid="GCLID_EXAMPLE",
    )
    assert reported is False
    await adapter.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_adapter_uses_injected_http_client() -> None:
    """Adapter accepts a shared httpx client so external calls are mockable."""
    route = respx.get("https://example.test/ping").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    async with httpx.AsyncClient() as client:
        adapter = GoogleAdsAdapter(http_client=client)
        resp = await client.get("https://example.test/ping")
        assert resp.status_code == 200
        assert route.called
        assert adapter.platform_name == "google_ads"
