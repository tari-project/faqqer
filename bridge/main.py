import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from telegram import Bot

from discord_handler import run_discord_bot
from telegram_handler import run_telegram_bot
from jobs.blockchain_job import (
    BLOCK_HEIGHT_CRON_DEFAULT,
    HASH_POWER_CRON_DEFAULT,
    post_block_height,
    post_hash_power,
)
from jobs.customer_analysis_job import CUSTOMER_ANALYSIS_CRON_DEFAULT, run_customer_service_analysis


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    def _handle_signal(signum, _frame=None) -> None:
        logging.getLogger(__name__).info("Signal received: %s", signum)
        stop_event.set()

    try:
        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)
    except Exception:
        logging.getLogger(__name__).warning("Signal handlers not fully supported in this environment")


async def main() -> int:
    _configure_logging()

    env_path = Path(__file__).with_name(".env")
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
        logging.getLogger(__name__).info("Loaded env file: %s", env_path)
    else:
        load_dotenv()
        logging.getLogger(__name__).warning("No bridge/.env found; relying on process environment")

    logging.getLogger(__name__).info(
        "Env present: TELEGRAM_BOT_TOKEN=%s DISCORD_BOT_TOKEN=%s DISCORD_TEST_GUILD_ID=%s",
        "yes" if os.getenv("TELEGRAM_BOT_TOKEN") else "no",
        "yes" if os.getenv("DISCORD_BOT_TOKEN") else "no",
        "set" if os.getenv("DISCORD_TEST_GUILD_ID") else "unset",
    )

    # Start scheduler (asyncio-based) before bot tasks.
    scheduler = AsyncIOScheduler()

    job_bot: Bot | None = None
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if telegram_token:
        job_bot = Bot(token=telegram_token)
        await job_bot.initialize()

        block_height_cron = os.getenv("BLOCK_HEIGHT_CRON", BLOCK_HEIGHT_CRON_DEFAULT)
        hash_power_cron = os.getenv("HASH_POWER_CRON", HASH_POWER_CRON_DEFAULT)
        customer_analysis_cron = os.getenv("CUSTOMER_ANALYSIS_CRON", CUSTOMER_ANALYSIS_CRON_DEFAULT)

        scheduler.add_job(
            post_block_height,
            CronTrigger.from_crontab(block_height_cron),
            args=[job_bot],
            id="block_height",
            replace_existing=True,
        )
        scheduler.add_job(
            post_hash_power,
            CronTrigger.from_crontab(hash_power_cron),
            args=[job_bot],
            id="hash_power",
            replace_existing=True,
        )
        scheduler.add_job(
            run_customer_service_analysis,
            CronTrigger.from_crontab(customer_analysis_cron),
            args=[job_bot],
            id="customer_analysis",
            replace_existing=True,
        )
    else:
        logging.getLogger(__name__).warning("TELEGRAM_BOT_TOKEN missing; scheduler jobs will not start")

    scheduler.start()

    stop_event = asyncio.Event()
    _install_signal_handlers(stop_event)

    async def _run_and_stop_on_error(coro):
        try:
            await coro
        except Exception:
            logging.getLogger(__name__).exception("Bot crashed; triggering shutdown")
            stop_event.set()
            raise

    telegram_task = asyncio.create_task(_run_and_stop_on_error(run_telegram_bot(stop_event)))
    discord_task = asyncio.create_task(_run_and_stop_on_error(run_discord_bot(stop_event)))

    try:
        await asyncio.gather(telegram_task, discord_task)
        return 0
    except asyncio.CancelledError:
        stop_event.set()
        raise
    except Exception:
        return 1
    finally:
        try:
            scheduler.shutdown(wait=False)
        except Exception:
            pass
        if job_bot is not None:
            try:
                await job_bot.shutdown()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
