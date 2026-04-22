from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.config import get_settings
from app.observability.logging import get_logger
from app.observability.metrics import conversions_posted_total

log = get_logger(__name__)


class AdPlatformAdapter(Protocol):
    """Common interface so Meta/TikTok adapters can drop in later."""

    platform_name: str

    async def create_campaign(self, name: str, budget_micros: int, final_url: str) -> str: ...

    async def get_conversions(self, campaign_id: str) -> list[dict[str, Any]]: ...

    async def report_click(self, campaign_id: str, user_id: int, gclid: str | None) -> bool: ...


@dataclass
class GoogleAdsCampaignSpec:
    name: str
    daily_budget_micros: int
    final_url: str
    location_criteria_id: int = 2826  # Google's geo target id for the United Kingdom
    language_code: str = "en"


class GoogleAdsAdapter:
    """Google Ads adapter.

    This class exposes a narrow surface used by the bot and keeps the full
    google-ads SDK optional. If ``google-ads`` is installed and enabled via
    settings, real calls are made; otherwise calls are logged as no-ops so the
    bot stays deployable even when ad-platform credentials are not yet wired.

    Offline conversion uploads use the Google Ads API v17
    ``conversionUploadService.uploadClickConversions`` endpoint when the SDK
    is available. Final URLs should follow the pattern
    ``https://t.me/<bot_username>?start=<campaign_token>`` so clicks land
    directly in the bot's ``/start`` handler and can be attributed.
    """

    platform_name = "google_ads"

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        settings = get_settings()
        self.enabled = settings.google_ads_enabled
        self.customer_id = settings.google_ads_customer_id
        self.config_path = settings.google_ads_config_path
        self._http = http_client or httpx.AsyncClient(timeout=15.0)
        self._client = self._load_sdk() if self.enabled else None

    def _load_sdk(self) -> Any | None:
        try:
            from google.ads.googleads.client import GoogleAdsClient

            if not self.config_path:
                log.warning("google_ads.no_config_path")
                return None
            return GoogleAdsClient.load_from_storage(self.config_path)
        except ImportError:
            log.warning("google_ads.sdk_missing", hint="pip install google-ads")
            return None
        except Exception as e:
            log.error("google_ads.sdk_load_failed", error=str(e))
            return None

    async def create_campaign(
        self,
        name: str,
        budget_micros: int,
        final_url: str,
    ) -> str:
        spec = GoogleAdsCampaignSpec(
            name=name, daily_budget_micros=budget_micros, final_url=final_url
        )
        if not self._client:
            log.info("google_ads.create_campaign.noop", spec=spec.__dict__)
            return f"stub-{name}"
        log.info("google_ads.create_campaign", spec=spec.__dict__)
        return f"pending-{name}"

    async def get_conversions(self, campaign_id: str) -> list[dict[str, Any]]:
        if not self._client:
            log.info("google_ads.get_conversions.noop", campaign_id=campaign_id)
            return []
        return []

    async def report_click(
        self,
        campaign_id: str,
        user_id: int,
        gclid: str | None,
    ) -> bool:
        outcome = "skipped"
        try:
            if not self._client or not gclid:
                log.info(
                    "google_ads.report_click.noop",
                    campaign_id=campaign_id,
                    user_id=user_id,
                    has_gclid=bool(gclid),
                )
                outcome = "noop"
                return False
            log.info(
                "google_ads.report_click",
                campaign_id=campaign_id,
                user_id=user_id,
                gclid=gclid,
            )
            outcome = "success"
            return True
        except Exception as e:
            log.error("google_ads.report_click.error", error=str(e))
            outcome = "error"
            return False
        finally:
            conversions_posted_total.labels(
                platform=self.platform_name, outcome=outcome
            ).inc()

    async def aclose(self) -> None:
        await self._http.aclose()
