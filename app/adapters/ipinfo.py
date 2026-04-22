from __future__ import annotations

from typing import Any, Optional

import httpx

from app.config import get_settings
from app.observability.logging import get_logger

log = get_logger(__name__)


class IPInfoClient:
    """Thin async client for ipinfo.io.

    Falls back gracefully when no token is configured; still works on the
    unauthenticated free tier (rate limited).
    """

    BASE_URL = "https://ipinfo.io"

    def __init__(self, client: Optional[httpx.AsyncClient] = None) -> None:
        settings = get_settings()
        self._token = (
            settings.ipinfo_token.get_secret_value() if settings.ipinfo_token else None
        )
        self._client = client or httpx.AsyncClient(timeout=5.0)

    async def lookup(self, ip: str) -> Optional[dict[str, Any]]:
        params = {"token": self._token} if self._token else {}
        try:
            resp = await self._client.get(f"{self.BASE_URL}/{ip}/json", params=params)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            log.warning("ipinfo.error", ip=ip, error=str(e))
            return None

    async def aclose(self) -> None:
        await self._client.aclose()
