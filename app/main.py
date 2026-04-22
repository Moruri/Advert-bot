# Framework choice: python-telegram-bot v21+ — chosen for first-class ChatMemberHandler support,
# mature async API, and clean integration with APScheduler via JobQueue, which the attribution flow
# and scheduled broadcasts both depend on.
from __future__ import annotations

import asyncio
import signal
from typing import Any

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    ChatMemberHandler,
    CommandHandler,
)

from app.adapters.google_ads import GoogleAdsAdapter
from app.config import get_settings
from app.db.session import init_db
from app.handlers.admin import broadcast_cmd, campaign_new, stats_cmd
from app.handlers.member_tracking import on_chat_member
from app.handlers.start import help_command, start
from app.observability.logging import configure_logging, get_logger
from app.observability.metrics import start_metrics_server
from app.services.broadcaster import Broadcaster


def build_application() -> Application:
    settings = get_settings()
    application = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token.get_secret_value())
        .concurrent_updates(True)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("campaign_new", campaign_new))
    application.add_handler(CommandHandler("broadcast", broadcast_cmd))
    application.add_handler(CommandHandler("stats", stats_cmd))
    application.add_handler(ChatMemberHandler(on_chat_member, ChatMemberHandler.CHAT_MEMBER))

    application.bot_data["broadcaster"] = Broadcaster(application)
    application.bot_data["google_ads"] = GoogleAdsAdapter()
    return application


async def _amain() -> None:
    configure_logging()
    log = get_logger("main")
    settings = get_settings()

    start_metrics_server(settings.metrics_port)
    log.info("metrics.started", port=settings.metrics_port)

    await init_db()
    log.info("db.initialized", url=settings.database_url)

    application = build_application()

    stop_event = asyncio.Event()

    def _on_signal(*_: Any) -> None:
        log.info("shutdown.signal_received")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _on_signal)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler for SIGTERM.
            pass

    await application.initialize()
    await application.start()
    await application.updater.start_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
    )
    log.info("bot.started")

    try:
        await stop_event.wait()
    finally:
        log.info("bot.shutting_down")
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
        ga: GoogleAdsAdapter = application.bot_data.get("google_ads")
        if ga:
            await ga.aclose()


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
