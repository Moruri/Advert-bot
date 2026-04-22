from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from app.adapters.ipinfo import IPInfoClient
from app.config import get_settings
from app.observability.logging import get_logger

log = get_logger(__name__)


@dataclass
class GeoResult:
    country: Optional[str]
    confidence: float


class GeoService:
    def __init__(self, client: Optional[IPInfoClient] = None) -> None:
        self.client = client or IPInfoClient()
        self._cache: dict[str, tuple[float, GeoResult]] = {}
        self._ttl = get_settings().ipinfo_ttl_seconds

    async def classify_ip(self, ip: str) -> GeoResult:
        now = time.time()
        cached = self._cache.get(ip)
        if cached and (now - cached[0]) < self._ttl:
            return cached[1]

        data = await self.client.lookup(ip)
        country = data.get("country") if data else None
        confidence = 0.95 if country else 0.0
        result = GeoResult(country=country, confidence=confidence)
        self._cache[ip] = (now, result)
        log.info("geo.classified", ip=ip, country=country, confidence=confidence)
        return result

    def classify_language(self, language_code: Optional[str]) -> GeoResult:
        if not language_code:
            return GeoResult(country=None, confidence=0.0)
        lc = language_code.lower()
        if lc in {"en-gb", "en_gb"}:
            return GeoResult(country="GB", confidence=0.7)
        if lc.startswith("en"):
            return GeoResult(country=None, confidence=0.15)
        return GeoResult(country=None, confidence=0.0)
