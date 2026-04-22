from __future__ import annotations

from sqlalchemy import select
from telegram import Update
from telegram.ext import ContextTypes

from app.adapters.google_ads import GoogleAdsAdapter
from app.db.models import Campaign, Contact, Conversion
from app.db.session import session_scope
from app.observability.logging import get_logger
from app.services.geolocation import GeoService
from app.services.targeting import score_text

log = get_logger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start [campaign_token] from external ad clicks or direct DMs."""
    if not update.effective_user or not update.message:
        return

    user = update.effective_user
    args = context.args or []
    campaign_token = args[0] if args else None

    geo = GeoService()
    lang_geo = geo.classify_language(user.language_code)
    bio_score = score_text(getattr(user, "first_name", None), user.language_code)
    country = lang_geo.country
    uk_score = max(lang_geo.confidence, bio_score)

    campaign_id: int | None = None
    async with session_scope() as s:
        if campaign_token:
            stmt = select(Campaign).where(Campaign.token == campaign_token)
            camp = (await s.execute(stmt)).scalar_one_or_none()
            if camp:
                campaign_id = camp.id

        existing = (
            await s.execute(select(Contact).where(Contact.user_id == user.id))
        ).scalar_one_or_none()
        if existing:
            existing.username = user.username
            existing.language_code = user.language_code
            if country and not existing.country:
                existing.country = country
            existing.uk_score = max(existing.uk_score, uk_score)
            if campaign_id and not existing.attributed_campaign_id:
                existing.attributed_campaign_id = campaign_id
        else:
            s.add(
                Contact(
                    user_id=user.id,
                    username=user.username,
                    language_code=user.language_code,
                    country=country,
                    uk_score=uk_score,
                    attributed_campaign_id=campaign_id,
                )
            )

        if campaign_id:
            s.add(
                Conversion(
                    campaign_id=campaign_id,
                    user_id=user.id,
                    platform="telegram",
                    posted=False,
                )
            )

    log.info(
        "start.received",
        user_id=user.id,
        username=user.username,
        campaign_token=campaign_token,
        campaign_id=campaign_id,
        uk_score=uk_score,
        country=country,
    )

    if campaign_id and context.bot_data.get("google_ads"):
        ads: GoogleAdsAdapter = context.bot_data["google_ads"]
        await ads.report_click(
            campaign_id=str(campaign_id),
            user_id=user.id,
            gclid=context.user_data.get("gclid") if context.user_data else None,
        )

    welcome = (
        "Welcome! Tap the button in the channel post to access the content.\n"
        "Use /help to see what I can do."
    )
    await update.message.reply_text(welcome)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    text = (
        "<b>Advert-bot commands</b>\n"
        "/start [campaign_token] — attribute your visit to an ad campaign\n"
        "/help — this message\n"
        "Admin only:\n"
        "/campaign_new — create a new campaign + invite link\n"
        "/broadcast &lt;campaign_id&gt; — broadcast a campaign to target chats\n"
        "/stats — show campaign metrics"
    )
    await update.message.reply_html(text)
