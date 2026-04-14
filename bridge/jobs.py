"""Scheduled jobs (blockchain stats + customer-service analysis).

Wraps the legacy modules at the repository root so that:

  * the original posting/analysis logic is preserved verbatim, and
  * the schedule is owned by the bridge worker (single APScheduler with
    a SQLite jobstore, so jobs survive restarts and never double-fire).
"""
from __future__ import annotations

import asyncio
import importlib
import logging
import sys
from pathlib import Path
from typing import Any, Optional

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import Settings

logger = logging.getLogger(__name__)


def _ensure_repo_root_on_path() -> None:
    # bridge/jobs.py -> bridge/ -> repo root
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


def _import_legacy(module_name: str) -> Optional[Any]:
    _ensure_repo_root_on_path()
    try:
        return importlib.import_module(module_name)
    except Exception as exc:
        logger.warning(
            "Legacy module %s could not be imported (%s); jobs disabled.",
            module_name,
            exc,
        )
        return None


class JobRunner:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        jobstore_path = settings.data_dir / "jobs.sqlite"
        jobstores = {
            "default": SQLAlchemyJobStore(url=f"sqlite:///{jobstore_path}")
        }
        self._scheduler = AsyncIOScheduler(jobstores=jobstores, timezone="UTC")
        self._telethon_client: Optional[Any] = None

    async def _ensure_telethon(self) -> Optional[Any]:
        if self._telethon_client is not None:
            return self._telethon_client
        if not self._settings.telegram_legacy_enabled:
            logger.info(
                "Telethon not configured (TELEGRAM_API_ID / TELEGRAM_API_HASH "
                "missing); blockchain + customer-analysis jobs will be skipped."
            )
            return None
        try:
            from telethon import TelegramClient  # type: ignore
        except ImportError:
            logger.warning("Telethon not installed; legacy jobs disabled.")
            return None
        session = str(
            self._settings.data_dir / f"{self._settings.telegram_session_name}.session"
        )
        client = TelegramClient(
            session,
            self._settings.telegram_api_id,
            self._settings.telegram_api_hash,
        )
        await client.start()
        self._telethon_client = client
        return client

    # ------------------------------------------------------------------ jobs
    async def _run_block_height(self) -> None:
        mod = _import_legacy("blockchain_job")
        client = await self._ensure_telethon()
        if not mod or client is None:
            return
        try:
            await mod.post_block_height(client)
        except Exception as exc:
            logger.exception("post_block_height failed: %s", exc)

    async def _run_hash_power(self) -> None:
        mod = _import_legacy("blockchain_job")
        client = await self._ensure_telethon()
        if not mod or client is None:
            return
        try:
            await mod.post_hash_power(client)
        except Exception as exc:
            logger.exception("post_hash_power failed: %s", exc)

    async def _run_customer_analysis(self) -> None:
        mod = _import_legacy("customer_analysis_job")
        client = await self._ensure_telethon()
        if not mod or client is None:
            return
        try:
            await mod.run_customer_service_analysis(
                client,
                target_group_id=self._settings.telegram_customer_service_group_id,
            )
        except Exception as exc:
            logger.exception("run_customer_service_analysis failed: %s", exc)

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._settings.enable_blockchain_jobs:
            self._scheduler.add_job(
                self._run_block_height,
                CronTrigger.from_crontab("0 */4 * * *"),
                id="block_height",
                replace_existing=True,
                coalesce=True,
                max_instances=1,
            )
            self._scheduler.add_job(
                self._run_hash_power,
                CronTrigger.from_crontab("0 */12 * * *"),
                id="hash_power",
                replace_existing=True,
                coalesce=True,
                max_instances=1,
            )
        if self._settings.enable_customer_analysis_job:
            self._scheduler.add_job(
                self._run_customer_analysis,
                CronTrigger.from_crontab("0 */3 * * *"),
                id="customer_analysis",
                replace_existing=True,
                coalesce=True,
                max_instances=1,
            )
        self._scheduler.start()
        logger.info(
            "Scheduler started with %d job(s)",
            len(self._scheduler.get_jobs()),
        )

    async def shutdown(self) -> None:
        try:
            self._scheduler.shutdown(wait=False)
        except Exception:  # pragma: no cover
            pass
        if self._telethon_client is not None:
            try:
                await self._telethon_client.disconnect()
            except Exception:  # pragma: no cover
                pass
