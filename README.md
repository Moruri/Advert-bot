# Advert-bot

Production-ready Telegram bot that automates advertising for an existing Telegram channel, with logic-based UK targeting and a funnel from paid external ads (Google Ads) into the bot.

## Architecture

```
                          +-------------------+
 Google Ads (UK geo) ---> |  t.me/<bot>?start |---> Telegram Bot API
                          +-------------------+            |
                                                           v
                                           +-------------------------------+
                                           |  app/main.py  (async loop)    |
                                           |  ApplicationBuilder + PTB v21 |
                                           +---------------+---------------+
                                                           |
           +-----------------------------+-----------------+-------------------+
           |                             |                                     |
           v                             v                                     v
    handlers/start.py          handlers/admin.py                  handlers/member_tracking.py
    (attribution, geo)         (/campaign_new, /broadcast,        (ChatMemberHandler ->
                                /stats)                            invite-link attribution)
           |                             |                                     |
           +-------+---------+-----------+-------+-----------+-----------------+
                   |         |                   |           |
                   v         v                   v           v
        services/targeting  services/        services/     services/
        (UK scoring, YAML)  invite_links     broadcaster   geolocation
                            (create_chat_    (token-bucket (ipinfo + lang)
                             invite_link)    rate limiter)
                   |                               |
                   +---------------+---------------+
                                   v
                      adapters/google_ads.py   adapters/ipinfo.py
                   (offline conversion upload) (IP -> country)
                                   |
                                   v
                         db/ (SQLAlchemy async, Postgres/SQLite)
                         observability/ (structlog JSON, Prometheus /metrics)
```

## Quick start

```bash
cp .env.example .env
# Fill in TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, BOT_USERNAME, ADMIN_USER_IDS
docker compose up -d --build
# Bot polls Telegram; metrics at http://localhost:9090/metrics
# Prometheus UI at http://localhost:9091
```

Local (no Docker):

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env   # edit values
make run
```

## Environment variables

| Variable                            | Required | Description |
|-------------------------------------|----------|-------------|
| `TELEGRAM_BOT_TOKEN`                | yes      | Bot token from BotFather |
| `TELEGRAM_CHANNEL_ID`               | yes      | Numeric channel id (negative) |
| `BOT_USERNAME`                      | yes      | Bot username (no @); used in ad final URLs |
| `ADMIN_USER_IDS`                    | yes      | Comma-separated Telegram user IDs allowed to run admin commands |
| `DATABASE_URL`                      | no       | SQLAlchemy async URL. Default: SQLite in `./data/` |
| `METRICS_PORT`                      | no       | Prometheus scrape port (default 9090) |
| `LOG_LEVEL` / `LOG_JSON`            | no       | Structlog config |
| `UK_KEYWORDS_PATH`                  | no       | Path to keyword YAML |
| `UK_SCORE_THRESHOLD`                | no       | Score cutoff for `is_uk_audience` |
| `IPINFO_TOKEN` / `IPINFO_TTL_SECONDS` | no     | IP geolocation |
| `GOOGLE_ADS_ENABLED`                | no       | Toggle real Google Ads calls |
| `GOOGLE_ADS_CONFIG_PATH`            | no       | Path to `google-ads.yaml` credentials |
| `GOOGLE_ADS_CUSTOMER_ID`            | no       | Ads account id |
| `BROADCAST_RATE_GLOBAL_PER_SEC`     | no       | Global token-bucket rate (Telegram-safe default 25) |
| `BROADCAST_RATE_PER_CHAT_PER_MIN`   | no       | Per-chat rate (default 18) |

## Admin commands

Send these to the bot from one of the `ADMIN_USER_IDS`.

- `/campaign_new <name> <source> [creative text...]` — creates a campaign, mints a unique invite link, prints the ad final URL.
- `/broadcast <campaign_id>` — broadcasts the campaign's latest invite link to every non-opted-out target chat with rate limiting.
- `/stats` — shows up to 20 most-recent campaigns with sent / joins counters.

## Deployment notes

- **Scaling beyond one worker**: `getUpdates` long-polling cannot be load-balanced — run a single bot process and scale broadcasters horizontally by switching to webhooks behind a gateway, or by moving the broadcast queue to Redis/RQ.
- **Rate limits**: Telegram permits ~30 msg/s globally and ~20/min per group. Defaults sit below both. Raise only after observing `RetryAfter` counts near zero.
- **Postgres**: flip `DATABASE_URL` to `postgresql+asyncpg://...`. Tables auto-create on boot via `init_db`.
- **Secrets**: never bake into the image. `docker-compose.yml` reads `.env`; in K8s, mount a `Secret`.

## Compliance & Ethics

This bot is a **legitimate marketing automation tool**. The author's responsibility — and yours, as the operator — is to stay inside these lines.

- **Telegram ToS**: only the official Bot API is used. No userbot / MTProto impersonation, no auto-join of groups, no scraping of private chats. Broadcasting into a group requires that the bot be invited by an admin of that group.
- **UK GDPR**: UK users are data subjects under UK GDPR. Before going live, document:
  - lawful basis (usually legitimate interest or consent);
  - retention periods for `contacts`, `conversions`, `broadcasts` tables (default retention is not set — add a periodic DELETE job);
  - a way to satisfy data subject requests (export / erasure) via `user_id`.
- **Google Ads policies**: the final URL pattern `https://t.me/<bot>?start=<token>` is a landing page. It must disclose what the user will receive and link to a privacy policy. The Offline Conversion Import feed must not carry PII beyond the GCLID.
- **Group discovery**: `scripts/discover_uk_groups.py` reads only *public* directory pages from seeds you provide, respects robots.txt, and never joins groups. Still obtain admin consent before broadcasting.

## Tests

```bash
make install-dev
make test       # pytest
make typecheck  # mypy --strict app
make lint       # ruff
```

## Next steps

- **a. BotFather**: DM [@BotFather](https://t.me/BotFather), `/newbot`, copy the token into `TELEGRAM_BOT_TOKEN`. Run `/setprivacy` → *Disable* only if the bot must read messages in groups. Add the bot to your channel as admin with *Invite Users via Link* permission.
- **b. Google Ads credentials**: follow [developers.google.com/google-ads/api/docs/oauth/cloud-project](https://developers.google.com/google-ads/api/docs/oauth/cloud-project) to mint OAuth credentials, produce a refresh token, and save `google-ads.yaml` beside the bot. Set `GOOGLE_ADS_ENABLED=true` and `GOOGLE_ADS_CUSTOMER_ID`. Geo-target UK in the Ads UI (criterion `2826`) or via API.
- **c. Scaling broadcasting**: move from in-process scheduling to Redis-backed job queues (RQ or arq). Keep the bot process as the single Telegram poller; workers call the Bot API directly.
- **d. Suggested KPIs**:
  - **CPA** = Google Ads spend ÷ `/start` events attributed to a campaign;
  - **Join-through rate** = `InviteLink.joins` ÷ `InviteLink.clicks` (clicks via tracking redirect);
  - **7-day retention** = contacts still present in channel 7d after join (via `getChatMember`);
  - **Broadcast efficiency** = `sent` ÷ (`sent + failed`) per campaign.
