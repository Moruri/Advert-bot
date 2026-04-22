from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, start_http_server

invite_links_created_total = Counter(
    "advert_invite_links_created_total",
    "Total number of invite links created.",
    ["campaign"],
)

broadcasts_sent_total = Counter(
    "advert_broadcasts_sent_total",
    "Total broadcast messages sent.",
    ["campaign", "outcome"],
)

joins_attributed_total = Counter(
    "advert_joins_attributed_total",
    "Total channel joins attributed to an invite link.",
    ["campaign"],
)

conversions_posted_total = Counter(
    "advert_conversions_posted_total",
    "Offline conversions pushed to the ad platform.",
    ["platform", "outcome"],
)

uk_score_histogram = Histogram(
    "advert_uk_score",
    "Distribution of UK-targeting confidence scores.",
    buckets=(0.0, 0.1, 0.25, 0.5, 0.55, 0.7, 0.85, 1.0),
)

active_campaigns_gauge = Gauge(
    "advert_active_campaigns",
    "Number of currently active campaigns.",
)


def start_metrics_server(port: int) -> None:
    start_http_server(port)
