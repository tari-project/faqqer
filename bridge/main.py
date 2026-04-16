import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from dotenv import load_dotenv

from discord_handler import run_discord_bot
from telegram_handler import run_telegram_bot


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


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
