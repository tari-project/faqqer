"""Telegram Q&A bot using python-telegram-bot v21."""
from __future__ import annotations

import logging
import time
from typing import Optional

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .config import Settings
from .feedback import FeedbackStore, QAPair, promote_to_kb
from .rag_client import AnythingLLMClient, RAGEmptyKnowledgeBase, RAGError

logger = logging.getLogger(__name__)

_EMPTY_REPLY = (
    "I don't know the answer yet. An admin can teach me by replying to a "
    "good response with /approve."
)


class TelegramBot:
    def __init__(
        self,
        settings: Settings,
        rag: AnythingLLMClient,
        feedback: FeedbackStore,
    ) -> None:
        self._settings = settings
        self._rag = rag
        self._feedback = feedback
        self._app: Optional[Application] = None

    def build(self) -> Application:
        if not self._settings.telegram_bot_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN required for Telegram Q&A bot")
        app = (
            Application.builder()
            .token(self._settings.telegram_bot_token)
            .build()
        )
        app.add_handler(CommandHandler("start", self._cmd_start))
        app.add_handler(CommandHandler("ask", self._cmd_ask))
        app.add_handler(CommandHandler("faq", self._cmd_ask))
        app.add_handler(CommandHandler("approve", self._cmd_approve))
        # Reply to direct messages and to messages that mention the bot.
        app.add_handler(
            MessageHandler(
                filters.TEXT & ~filters.COMMAND
                & (filters.ChatType.PRIVATE | filters.Entity("mention")),
                self._on_text,
            )
        )
        self._app = app
        return app

    # ------------------------------------------------------------------ helpers
    def _is_admin(self, user_id: Optional[int]) -> bool:
        if user_id is None:
            return False
        return user_id in self._settings.telegram_admin_user_ids

    async def _answer(self, question: str) -> str:
        try:
            return await self._rag.ask(question)
        except RAGEmptyKnowledgeBase:
            return _EMPTY_REPLY
        except RAGError as exc:
            logger.error("RAG failure: %s", exc)
            return (
                "Sorry, the knowledge base is unreachable right now. "
                "Please try again in a minute."
            )

    async def _record_pair(
        self,
        update: Update,
        question: str,
        answer: str,
        sent_message_id: int,
    ) -> None:
        if not update.effective_chat or not update.effective_user:
            return
        pair = QAPair(
            channel="telegram",
            chat_id=str(update.effective_chat.id),
            message_id=str(sent_message_id),
            user_id=str(update.effective_user.id),
            question=question,
            answer=answer,
            created_at=time.time(),
        )
        await self._feedback.record(pair)

    # ------------------------------------------------------------------ handlers
    async def _cmd_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not update.effective_message:
            return
        await update.effective_message.reply_text(
            "Hi! Ask me anything about Tari. In a group, mention me or use /ask <question>."
        )

    async def _cmd_ask(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not update.effective_message:
            return
        question = " ".join(context.args or []).strip()
        if not question and update.effective_message.reply_to_message:
            question = (update.effective_message.reply_to_message.text or "").strip()
        if not question:
            await update.effective_message.reply_text("Usage: /ask <your question>")
            return
        await self._handle_question(update, question)

    async def _on_text(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        msg = update.effective_message
        if not msg or not msg.text:
            return
        question = msg.text
        # Strip the bot's @mention if present.
        if context.bot and context.bot.username:
            handle = f"@{context.bot.username}"
            question = question.replace(handle, "").strip()
        if not question:
            return
        await self._handle_question(update, question)

    async def _handle_question(self, update: Update, question: str) -> None:
        chat = update.effective_chat
        msg = update.effective_message
        if not chat or not msg:
            return
        try:
            await chat.send_action(ChatAction.TYPING)
        except Exception:  # pragma: no cover - best-effort
            pass
        answer = await self._answer(question)
        sent = await msg.reply_text(answer)
        await self._record_pair(update, question, answer, sent.message_id)

    async def _cmd_approve(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        msg = update.effective_message
        user = update.effective_user
        if not msg or not user:
            return
        if not self._is_admin(user.id):
            await msg.reply_text("Only configured admins can approve answers.")
            return
        target = msg.reply_to_message
        if not target:
            await msg.reply_text(
                "Reply to one of my answers with /approve to add it to the KB."
            )
            return
        chat = update.effective_chat
        if not chat:
            return
        pair = await self._feedback.get(
            "telegram", str(chat.id), str(target.message_id)
        )
        if not pair:
            await msg.reply_text(
                "I can't find a Q&A pair for that message (it may be too old)."
            )
            return
        try:
            await promote_to_kb(self._rag, pair, approver=f"telegram:{user.id}")
        except RAGError as exc:
            await msg.reply_text(f"Could not save to KB: {exc}")
            return
        await self._feedback.remove("telegram", str(chat.id), str(target.message_id))
        await msg.reply_text("Saved. I will use this answer going forward.")

    # ------------------------------------------------------------------ lifecycle
    async def run(self) -> None:
        if not self._app:
            self.build()
        assert self._app is not None
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram Q&A bot is running")

    async def shutdown(self) -> None:
        if not self._app:
            return
        try:
            if self._app.updater and self._app.updater.running:
                await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
        except Exception as exc:  # pragma: no cover - best effort during teardown
            logger.warning("Telegram shutdown raised: %s", exc)
