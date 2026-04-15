"""Discord Q&A bot using discord.py 2.4."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from .config import Settings
from .feedback import FeedbackStore, QAPair, promote_to_kb
from .rag_client import AnythingLLMClient, RAGEmptyKnowledgeBase, RAGError

logger = logging.getLogger(__name__)

_EMPTY_REPLY = (
    "I don't know the answer yet. An admin can teach me by reacting "
    "to a good answer with \U0001F44D and then running !approve."
)
_THUMBS_UP = "\U0001F44D"
# Discord hard limit for regular messages and webhook followups.
_DISCORD_MAX_CHARS = 2000


def _truncate(text: str, limit: int = _DISCORD_MAX_CHARS) -> str:
    """Truncate *text* to *limit* chars, appending an ellipsis if needed."""
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


class DiscordBot:
    def __init__(
        self,
        settings: Settings,
        rag: AnythingLLMClient,
        feedback: FeedbackStore,
    ) -> None:
        self._settings = settings
        self._rag = rag
        self._feedback = feedback

        intents = discord.Intents.default()
        intents.message_content = True
        intents.reactions = True
        self._bot = commands.Bot(command_prefix="!", intents=intents)
        self._task: Optional[asyncio.Task] = None
        self._register()

    @property
    def client(self) -> commands.Bot:
        return self._bot

    # ------------------------------------------------------------------ helpers
    def _is_admin(self, member: Optional[discord.abc.User]) -> bool:
        if member is None:
            return False
        if isinstance(member, discord.Member):
            role_ids = {r.id for r in member.roles}
            if role_ids & set(self._settings.discord_admin_role_ids):
                return True
            if member.guild_permissions.administrator:
                return True
        return False

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
        message: discord.Message,
        user_id: int,
        question: str,
        answer: str,
    ) -> None:
        pair = QAPair(
            channel="discord",
            chat_id=str(message.channel.id),
            message_id=str(message.id),
            user_id=str(user_id),
            question=question,
            answer=answer,
            created_at=time.time(),
        )
        await self._feedback.record(pair)

    # ------------------------------------------------------------------ events / commands
    def _register(self) -> None:
        bot = self._bot

        @bot.event
        async def on_ready() -> None:
            try:
                if self._settings.discord_guild_id:
                    guild = discord.Object(id=self._settings.discord_guild_id)
                    synced = await bot.tree.sync(guild=guild)
                else:
                    synced = await bot.tree.sync()
                logger.info(
                    "Discord bot ready as %s; synced %d commands",
                    bot.user,
                    len(synced),
                )
            except Exception as exc:
                logger.error("Slash command sync failed: %s", exc)

        guild_kwargs = {}
        if self._settings.discord_guild_id:
            guild_kwargs["guild"] = discord.Object(
                id=self._settings.discord_guild_id
            )

        @bot.tree.command(
            name="ask",
            description="Ask the Tari knowledge base a question.",
            **guild_kwargs,
        )
        @app_commands.describe(question="What would you like to know?")
        async def ask(
            interaction: discord.Interaction, question: str
        ) -> None:
            await interaction.response.defer(thinking=True)
            answer = await self._answer(question)
            sent = await interaction.followup.send(_truncate(answer))
            try:
                await self._record_pair(sent, interaction.user.id, question, answer)
            except Exception as exc:  # pragma: no cover
                logger.warning("Could not record QA pair: %s", exc)

        @bot.event
        async def on_message(message: discord.Message) -> None:
            if message.author.bot:
                return
            # Process commands first so !approve still works.
            await bot.process_commands(message)
            # Mention-based Q&A.
            if bot.user and bot.user in message.mentions:
                question = message.content
                for mention in message.mentions:
                    question = question.replace(f"<@{mention.id}>", "")
                    question = question.replace(f"<@!{mention.id}>", "")
                question = question.strip()
                if not question:
                    return
                async with message.channel.typing():
                    answer = await self._answer(question)
                sent = await message.reply(_truncate(answer), mention_author=False)
                try:
                    await self._record_pair(sent, message.author.id, question, answer)
                except Exception as exc:  # pragma: no cover
                    logger.warning("Could not record QA pair: %s", exc)

        @bot.command(name="approve")
        async def approve_cmd(ctx: commands.Context) -> None:
            if not self._is_admin(ctx.author):
                await ctx.reply(
                    "Only admins can approve answers.", mention_author=False
                )
                return
            target: Optional[discord.Message] = None
            if ctx.message.reference and ctx.message.reference.message_id:
                try:
                    target = await ctx.channel.fetch_message(
                        ctx.message.reference.message_id
                    )
                except discord.NotFound:
                    target = None
            if target is None:
                pair = await self._feedback.latest_for_user(
                    "discord", str(ctx.author.id)
                )
            else:
                pair = await self._feedback.get(
                    "discord", str(ctx.channel.id), str(target.id)
                )
            if not pair:
                await ctx.reply(
                    "Reply to one of my answers with !approve, "
                    "or ask me a question first.",
                    mention_author=False,
                )
                return
            try:
                await promote_to_kb(
                    self._rag, pair, approver=f"discord:{ctx.author.id}"
                )
            except RAGError as exc:
                await ctx.reply(f"Could not save to KB: {exc}", mention_author=False)
                return
            await self._feedback.remove(
                "discord", pair.chat_id, pair.message_id
            )
            await ctx.reply(
                "Saved. I will use this answer going forward.",
                mention_author=False,
            )

        @bot.event
        async def on_raw_reaction_add(
            payload: discord.RawReactionActionEvent,
        ) -> None:
            if str(payload.emoji) != _THUMBS_UP:
                return
            if payload.user_id == (bot.user.id if bot.user else 0):
                return
            pair = await self._feedback.get(
                "discord", str(payload.channel_id), str(payload.message_id)
            )
            if not pair:
                return
            # Only auto-promote when an admin reacts.
            # Prefer payload.member (populated directly by the gateway event)
            # over a cache lookup, which may return None for uncached members.
            member = payload.member
            if member is None:
                guild = bot.get_guild(payload.guild_id) if payload.guild_id else None
                member = guild.get_member(payload.user_id) if guild else None
            if not self._is_admin(member):
                return
            try:
                await promote_to_kb(
                    self._rag, pair, approver=f"discord-react:{payload.user_id}"
                )
            except RAGError as exc:
                logger.warning("Reaction-approve failed: %s", exc)
                return
            await self._feedback.remove(
                "discord", str(payload.channel_id), str(payload.message_id)
            )

    # ------------------------------------------------------------------ lifecycle
    async def run(self) -> None:
        token = self._settings.discord_bot_token
        if not token:
            raise RuntimeError("DISCORD_BOT_TOKEN required for Discord Q&A bot")
        # discord.py's `start` blocks forever; we run it as a task so the
        # bridge can manage Telegram and the scheduler concurrently.
        await self._bot.start(token)

    async def shutdown(self) -> None:
        try:
            await self._bot.close()
        except Exception as exc:  # pragma: no cover
            logger.warning("Discord shutdown raised: %s", exc)
