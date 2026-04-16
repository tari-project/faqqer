import asyncio
import logging
import os

import discord
from discord import app_commands


logger = logging.getLogger(__name__)


class BridgeDiscordClient(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.none()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

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
            await interaction.response.send_message(f"[Discord Echo]: {question}")

    async def on_ready(self) -> None:
        logger.info("Discord bot ready user=%s", self.user)

    async def setup_hook(self) -> None:
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
