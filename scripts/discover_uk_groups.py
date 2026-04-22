"""Discover candidate UK-oriented Telegram public directories.

ToS note
--------
This script only reads *public* listing pages from curated seed URLs you
provide, and scores each entry by title/description against the UK keyword
list. It does NOT log in with a user account, scrape private content, auto-join
groups, or use MTProto/userbot APIs. Those actions can violate Telegram's
Terms of Service and are explicitly out of scope.

Operator responsibility
-----------------------
- You must still obtain consent from group admins before broadcasting into
  their groups.
- Respect each source site's robots.txt and rate limits.
- UK GDPR: the output may include identifiers of group admins — treat as
  personal data and do not retain beyond operational need.

Usage
-----
    python scripts/discover_uk_groups.py --seeds seeds.txt --out candidates.csv
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.observability.logging import configure_logging, get_logger  # noqa: E402
from app.services.targeting import score_text  # noqa: E402

log = get_logger("discover_uk_groups")

TELEGRAM_LINK_RE = re.compile(
    r"https?://t\.me/(?:joinchat/)?([A-Za-z0-9_\-+]+)", re.IGNORECASE
)


@dataclass
class Candidate:
    url: str
    title: str
    description: str
    uk_score: float


async def fetch_page(client: httpx.AsyncClient, url: str) -> str:
    try:
        resp = await client.get(url, follow_redirects=True, timeout=15.0)
        resp.raise_for_status()
        return resp.text
    except httpx.HTTPError as e:
        log.warning("discover.fetch_failed", url=url, error=str(e))
        return ""


def extract_candidates(html: str) -> list[Candidate]:
    candidates: list[Candidate] = []
    for match in TELEGRAM_LINK_RE.finditer(html):
        url = match.group(0)
        start = max(0, match.start() - 200)
        end = min(len(html), match.end() + 200)
        context = re.sub(r"<[^>]+>", " ", html[start:end])
        title = context.strip()[:80]
        score = score_text(context)
        candidates.append(Candidate(url=url, title=title, description=context[:240], uk_score=score))
    return candidates


async def run(seeds: list[str], out_path: Path, threshold: float) -> int:
    async with httpx.AsyncClient(headers={"User-Agent": "advert-bot-discover/0.1"}) as client:
        all_candidates: list[Candidate] = []
        for seed in seeds:
            html = await fetch_page(client, seed)
            if html:
                all_candidates.extend(extract_candidates(html))

    dedup: dict[str, Candidate] = {}
    for c in all_candidates:
        prev = dedup.get(c.url)
        if prev is None or c.uk_score > prev.uk_score:
            dedup[c.url] = c

    ranked = sorted(dedup.values(), key=lambda c: c.uk_score, reverse=True)
    filtered = [c for c in ranked if c.uk_score >= threshold]

    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["url", "uk_score", "title", "description"])
        for c in filtered:
            writer.writerow([c.url, f"{c.uk_score:.3f}", c.title, c.description])

    log.info(
        "discover.done",
        seen=len(all_candidates),
        unique=len(dedup),
        kept=len(filtered),
        out=str(out_path),
    )
    return len(filtered)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--seeds", type=Path, required=True, help="File with one URL per line")
    p.add_argument("--out", type=Path, default=Path("candidates.csv"))
    p.add_argument("--threshold", type=float, default=0.5)
    return p.parse_args()


def main() -> None:
    configure_logging()
    args = parse_args()
    seeds = [line.strip() for line in args.seeds.read_text(encoding="utf-8").splitlines() if line.strip()]
    kept = asyncio.run(run(seeds, args.out, args.threshold))
    print(f"Kept {kept} candidates → {args.out}")


if __name__ == "__main__":
    main()
