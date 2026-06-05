"""Entry point: build and run the Telegram bot application."""

import logging

from dotenv import load_dotenv
load_dotenv()

from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ConversationHandler

from src import config
from src.database import init_db
from src.handlers.commands import (
    cmd_start,
    cmd_upcoming,
    cmd_today,
    cmd_cs2,
    cmd_f1,
    cmd_music,
    cmd_birthdays,
    cmd_reminders,
    cmd_delete,
    cmd_refresh,
)
from src.handlers.conversations import (
    add_conversation_handler,
)
from src.scheduler import setup_scheduler

logger = logging.getLogger(__name__)


async def post_init(application: Application) -> None:
    """Called after the application is initialised."""
    await init_db(config.DB_PATH)
    scheduler = setup_scheduler(application)
    scheduler.start()
    logger.info("Scheduler started")
    # Store scheduler reference so it can be shut down cleanly
    application.bot_data["scheduler"] = scheduler


async def post_shutdown(application: Application) -> None:
    """Called when the application shuts down."""
    scheduler = application.bot_data.get("scheduler")
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


def build_application() -> Application:
    app = (
        Application.builder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Command handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("upcoming", cmd_upcoming))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("cs2", cmd_cs2))
    app.add_handler(CommandHandler("f1", cmd_f1))
    app.add_handler(CommandHandler("music", cmd_music))
    app.add_handler(CommandHandler("birthdays", cmd_birthdays))
    app.add_handler(CommandHandler("reminders", cmd_reminders))
    app.add_handler(CommandHandler("delete", cmd_delete))
    app.add_handler(CommandHandler("refresh", cmd_refresh))

    # Conversation handler for /add
    app.add_handler(add_conversation_handler())

    return app


def main() -> None:
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    )
    logger.info("Starting remme bot...")
    app = build_application()
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
