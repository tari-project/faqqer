import asyncio
import logging
import os

import discord
from discord import app_commands

from kb_queue import push_to_kb
from llm_client import ask_anythingllm


logger = logging.getLogger(__name__)


class BridgeDiscordClient(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.reactions = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.pending_qa: dict[int, tuple[str, str]] = {}

        @self.tree.command(name="ask", description="Ask a question (echo only)")
        @app_commands.describe(question="Your question")
        async def ask(interaction: discord.Interaction, question: str) -> None:
            user = interaction.user.name if interaction.user else None
            guild = interaction.guild_id
            channel = interaction.channel_id
            logger.info(
                "Discord /ask received guild_id=%s channel_id=%s user=%s question=%r",
                guild,
                channel,
                user,
                question,
            )
            await interaction.response.defer()
            answer = await ask_anythingllm(question)
            logger.info(
                "Discord /ask answer returned guild_id=%s channel_id=%s user=%s answer=%r",
                guild,
                channel,
                user,
                answer,
            )
            msg = await interaction.followup.send(answer, wait=True)
            self.pending_qa[msg.id] = (question, answer)
            if len(self.pending_qa) > 1000:
                self.pending_qa.pop(next(iter(self.pending_qa)))

    async def on_ready(self) -> None:
        logger.info("Discord bot ready user=%s", self.user)

    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        try:
            emoji = str(payload.emoji)

            if emoji == "👍":
                logger.info(
                    "Discord 👍 reaction analytics guild_id=%s channel_id=%s user_id=%s message_id=%s",
                    payload.guild_id,
                    payload.channel_id,
                    payload.user_id,
                    payload.message_id,
                )
                return

            if emoji != "💾":
                return

            admin_role_id_raw = os.getenv("DISCORD_ADMIN_ROLE_ID", "").strip()
            if not admin_role_id_raw:
                logger.info(
                    "Discord 💾 reaction ignored (DISCORD_ADMIN_ROLE_ID unset) guild_id=%s channel_id=%s user_id=%s",
                    payload.guild_id,
                    payload.channel_id,
                    payload.user_id,
                )
                return

            try:
                admin_role_id = int(admin_role_id_raw)
            except ValueError:
                logger.warning("Invalid DISCORD_ADMIN_ROLE_ID=%r", admin_role_id_raw)
                return

            member = payload.member
            if member is None and payload.guild_id is not None:
                guild = self.get_guild(payload.guild_id)
                if guild is None:
                    try:
                        guild = await self.fetch_guild(payload.guild_id)
                    except Exception as e:
                        logger.error("Discord failed to fetch guild %s: %s", payload.guild_id, e)
                        return

                try:
                    member = guild.get_member(payload.user_id)
                    if member is None:
                        member = await guild.fetch_member(payload.user_id)
                except Exception as e:
                    logger.error(
                        "Discord failed to fetch member %s in guild %s: %s",
                        payload.user_id,
                        payload.guild_id,
                        e,
                    )
                    return

            if member is None:
                logger.warning(
                    "Discord 💾 reaction ignored (member unavailable) guild_id=%s channel_id=%s user_id=%s",
                    payload.guild_id,
                    payload.channel_id,
                    payload.user_id,
                )
                return

            is_admin = any(role.id == admin_role_id for role in getattr(member, "roles", []))
            if not is_admin:
                logger.info(
                    "Discord 💾 reaction ignored (missing admin role) guild_id=%s channel_id=%s user_id=%s",
                    payload.guild_id,
                    payload.channel_id,
                    payload.user_id,
                )
                return

            qa = self.pending_qa.get(payload.message_id)
            if not qa:
                logger.warning(
                    "Discord 💾 reaction received but no pending QA found message_id=%s",
                    payload.message_id,
                )
                return

            question, answer = qa
            ok = await push_to_kb(question, answer)
            if ok:
                self.pending_qa.pop(payload.message_id, None)
            logger.info(
                "Discord KB push attempted guild_id=%s channel_id=%s user_id=%s ok=%s",
                payload.guild_id,
                payload.channel_id,
                payload.user_id,
                ok,
            )

            try:
                channel = self.get_channel(payload.channel_id)
                if channel is None:
                    channel = await self.fetch_channel(payload.channel_id)
                await channel.send("Answer saved to knowledge base (pending review)")
            except Exception as e:
                logger.error("Discord failed to send KB confirmation message: %s", e)
        except Exception as e:
            logger.error("Discord reaction handler failed: %s", e)

    async def setup_hook(self) -> None:
        guild_id = os.getenv("DISCORD_TEST_GUILD_ID")
        if guild_id and guild_id.strip().isdigit():
            guild = discord.Object(id=int(guild_id.strip()))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logger.info("Discord command tree synced to guild %s", guild_id)
        elif guild_id:
            logger.warning(
                "DISCORD_TEST_GUILD_ID=%r is not a valid integer, skipping guild-specific sync",
                guild_id,
            )
            await self.tree.sync()
            logger.info("Discord command tree synced globally")
        else:
            await self.tree.sync()
            logger.info("Discord command tree synced globally")


async def run_discord_bot(stop_event) -> None:
    """
    Run discord bot in the current asyncio event loop until stop_event is set.
    stop_event must be an asyncio.Event-like object with an awaitable .wait().
    """
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        raise ValueError("Missing DISCORD_BOT_TOKEN in environment")

    client = BridgeDiscordClient()
    start_task = None
    stop_task = None
    try:
        start_task = asyncio.create_task(client.start(token))
        stop_task = asyncio.create_task(stop_event.wait())
        logger.info("Discord bot started (connecting)")

        done, pending = await asyncio.wait(
            {start_task, stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )

        if start_task in done:
            stop_event.set()
            await start_task
            return

        logger.info("Discord bot stopping...")
        await client.close()
        await start_task
        logger.info("Discord bot stopped")
    finally:
        if stop_task is not None and not stop_task.done():
            stop_task.cancel()
        try:
            await client.close()
        except Exception:
            pass
