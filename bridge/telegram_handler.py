import logging
import os

from telegram import ReactionTypeEmoji, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    MessageReactionHandler,
    filters,
)

from kb_queue import push_to_kb
from llm_client import ask_anythingllm


logger = logging.getLogger(__name__)

_MAX_PENDING_QA = 1000


def _load_telegram_admin_ids() -> set[int]:
    raw = os.getenv("TELEGRAM_ADMIN_IDS", "")
    admin_ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            admin_ids.add(int(part))
        except ValueError:
            logger.warning("Ignoring invalid TELEGRAM_ADMIN_IDS entry: %r", part)
    return admin_ids


def build_telegram_app() -> Application:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("Missing TELEGRAM_BOT_TOKEN in environment")

    pending_qa: dict[tuple[int, int], tuple[str, str]] = {}
    admin_ids = _load_telegram_admin_ids()
    logger.info("Telegram admin IDs loaded: %d", len(admin_ids))

    async def answer_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        text = update.effective_message.text if update.effective_message else None
        chat_id = update.effective_chat.id if update.effective_chat else None
        user = update.effective_user.username if update.effective_user else None
        logger.info("Telegram question received chat_id=%s user=%s text=%r", chat_id, user, text)
        if text is None:
            return

        answer = await ask_anythingllm(text)
        logger.info("Telegram answer returned chat_id=%s user=%s answer=%r", chat_id, user, answer)
        sent_msg = await update.effective_message.reply_text(answer)

        if chat_id is not None and sent_msg is not None:
            pending_qa[(chat_id, sent_msg.message_id)] = (text, answer)
            if len(pending_qa) > _MAX_PENDING_QA:
                pending_qa.pop(next(iter(pending_qa)))

    async def on_reaction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        reaction_update = update.message_reaction
        if not reaction_update:
            return

        chat_id = reaction_update.chat.id if reaction_update.chat else None
        user_id = reaction_update.user.id if reaction_update.user else None
        message_id = reaction_update.message_id

        emojis: list[str] = []
        for reaction in reaction_update.new_reaction or ():
            if isinstance(reaction, ReactionTypeEmoji):
                emojis.append(reaction.emoji)

        if "👍" in emojis:
            logger.info(
                "Telegram 👍 reaction analytics chat_id=%s user_id=%s message_id=%s",
                chat_id,
                user_id,
                message_id,
            )

        if "💾" not in emojis:
            return

        if user_id is None or user_id not in admin_ids:
            logger.info(
                "Telegram 💾 reaction ignored (not admin) chat_id=%s user_id=%s message_id=%s",
                chat_id,
                user_id,
                message_id,
            )
            return

        if chat_id is None or (chat_id, message_id) not in pending_qa:
            logger.warning(
                "Telegram 💾 reaction received but no pending QA found chat_id=%s user_id=%s message_id=%s",
                chat_id,
                user_id,
                message_id,
            )
            return

        question, answer = pending_qa[(chat_id, message_id)]
        ok = await push_to_kb(question, answer)
        logger.info(
            "Telegram KB push attempted chat_id=%s user_id=%s ok=%s",
            chat_id,
            user_id,
            ok,
        )

        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text="Answer saved to knowledge base (pending review)",
                reply_to_message_id=message_id,
            )
        except Exception as e:
            logger.error("Telegram failed to send KB confirmation message: %s", e)

    app = ApplicationBuilder().token(token).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, answer_question))
    app.add_handler(MessageReactionHandler(on_reaction))
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
        await app.updater.start_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
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
