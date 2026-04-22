from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from app.config import get_settings
from app.observability.metrics import uk_score_histogram

UK_POSTCODE_RE = re.compile(
    r"\b(GIR\s?0AA|[A-PR-UWYZ]([0-9]{1,2}|([A-HK-Y][0-9]([0-9]|[ABEHMNPRV-Y])?)|[0-9][A-HJKPS-UW])\s?[0-9][ABD-HJLNP-UW-Z]{2})\b",
    re.IGNORECASE,
)
UK_PHONE_RE = re.compile(r"(?:\+44|0044|\b0)(?:\d\s?){9,10}\b")


@dataclass(frozen=True)
class UKCategory:
    name: str
    weight: float
    terms: tuple[str, ...]


@lru_cache(maxsize=1)
def _load_categories() -> tuple[UKCategory, ...]:
    path = Path(get_settings().uk_keywords_path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    cats: list[UKCategory] = []
    for name, block in data.items():
        cats.append(
            UKCategory(
                name=name,
                weight=float(block["weight"]),
                terms=tuple(t.lower() for t in block["terms"]),
            )
        )
    return tuple(cats)


def score_text(
    text: str | None,
    language_code: str | None = None,
) -> float:
    """Return a composite UK-confidence score in [0, 1]."""
    if not text and not language_code:
        return 0.0

    haystack = (text or "").lower()
    hits_weight = 0.0
    max_possible = 0.0

    for cat in _load_categories():
        max_possible += cat.weight
        matched = False
        for term in cat.terms:
            if cat.name == "language_codes":
                if language_code and term in language_code.lower():
                    matched = True
                    break
            elif term in haystack:
                matched = True
                break
        if matched:
            hits_weight += cat.weight

    if UK_POSTCODE_RE.search(text or ""):
        hits_weight += 0.8
        max_possible += 0.8
    if UK_PHONE_RE.search(text or ""):
        hits_weight += 0.5
        max_possible += 0.5

    score = 0.0 if max_possible == 0 else min(1.0, hits_weight / max_possible)
    uk_score_histogram.observe(score)
    return score


def is_uk_audience(text: str | None, language_code: str | None = None) -> bool:
    return score_text(text, language_code) >= get_settings().uk_score_threshold
