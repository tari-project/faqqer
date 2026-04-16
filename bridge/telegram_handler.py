import logging
import os

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    filters,
)


logger = logging.getLogger(__name__)


def build_telegram_app() -> Application:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("Missing TELEGRAM_BOT_TOKEN in environment")

    async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        text = update.effective_message.text if update.effective_message else None
        chat_id = update.effective_chat.id if update.effective_chat else None
        user = update.effective_user.username if update.effective_user else None
        logger.info("Telegram message received chat_id=%s user=%s text=%r", chat_id, user, text)
        if text is None:
            return
        await update.effective_message.reply_text(f"[Telegram Echo]: {text}")

    app = ApplicationBuilder().token(token).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    return app


async def run_telegram_bot(stop_event) -> None:
    """
    Run telegram bot in the current asyncio event loop until stop_event is set.
    stop_event must be an asyncio.Event-like object with an awaitable .wait().
    """
    app = build_telegram_app()
    try:
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram bot started (polling)")

        await stop_event.wait()
        logger.info("Telegram bot stopping...")
    finally:
        try:
            if app.updater:
                await app.updater.stop()
        finally:
            await app.stop()
            await app.shutdown()
            logger.info("Telegram bot stopped")
