"""Bridge entrypoint.

Boots the knowledge-base seed, then starts whichever channels and
scheduled jobs are enabled by configuration. Each channel runs in its
own asyncio task so a failure in one (e.g. Discord token revoked)
does not take the others down.
"""
from __future__ import annotations

import asyncio
import logging
import signal
from typing import List, Optional

from .config import Settings, load_settings
from .discord_bot import DiscordBot
from .feedback import FeedbackStore
from .init_kb import seed_knowledge_base
from .jobs import JobRunner
from .rag_client import AnythingLLMClient, RAGError
from .telegram_bot import TelegramBot

logger = logging.getLogger("bridge")


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )


async def _maybe_seed(rag: AnythingLLMClient, settings: Settings) -> None:
    try:
        await rag.ensure_workspace()
        await seed_knowledge_base(rag, settings.faq_dir, settings.data_dir)
    except RAGError as exc:
        logger.error("Initial KB seed failed: %s", exc)


async def _run_telegram(bot: TelegramBot) -> None:
    await bot.run()
    # `run_polling` is started as a task; keep alive forever.
    await asyncio.Event().wait()


async def run() -> int:
    _setup_logging()
    try:
        settings = load_settings()
    except RuntimeError as exc:
        logger.error("Configuration error: %s", exc)
        return 2

    rag = AnythingLLMClient(
        base_url=settings.anythingllm_base_url,
        api_key=settings.anythingllm_api_key,
        workspace=settings.anythingllm_workspace,
        timeout=settings.rag_request_timeout,
        max_question_chars=settings.rag_max_question_chars,
    )
    feedback = FeedbackStore(settings.data_dir)

    try:
        await rag.wait_until_ready()
    except RAGError as exc:
        logger.error("Knowledge base never came up: %s", exc)
        return 3

    await _maybe_seed(rag, settings)

    tasks: List[asyncio.Task] = []
    telegram_bot: Optional[TelegramBot] = None
    discord_bot: Optional[DiscordBot] = None

    if settings.enable_telegram_qa and settings.telegram_bot_token:
        telegram_bot = TelegramBot(settings, rag, feedback)
        telegram_bot.build()
        tasks.append(asyncio.create_task(_run_telegram(telegram_bot), name="telegram"))
    else:
        logger.info("Telegram Q&A disabled (token missing or flag off).")

    if settings.enable_discord_qa and settings.discord_bot_token:
        discord_bot = DiscordBot(settings, rag, feedback)
        tasks.append(asyncio.create_task(discord_bot.run(), name="discord"))
    else:
        logger.info("Discord Q&A disabled (token missing or flag off).")

    job_runner = JobRunner(settings)
    job_runner.start()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig_name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, sig_name, None)
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            # Windows: signal handlers via add_signal_handler not supported.
            pass

    if not tasks:
        logger.warning(
            "No channel bots are enabled; running in scheduler-only mode."
        )

    stop_task = asyncio.create_task(stop.wait(), name="stop")
    try:
        done, pending = await asyncio.wait(
            tasks + [stop_task], return_when=asyncio.FIRST_COMPLETED
        )
        for t in done:
            if t is stop_task:
                continue
            exc = t.exception()
            if exc:
                logger.error("Task %s exited with error: %s", t.get_name(), exc)
    finally:
        for t in tasks:
            t.cancel()
        if telegram_bot:
            await telegram_bot.shutdown()
        if discord_bot:
            await discord_bot.shutdown()
        await job_runner.shutdown()
        for t in tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass

    return 0


def main() -> None:
    raise SystemExit(asyncio.run(run()))


if __name__ == "__main__":
    main()
