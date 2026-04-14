"""Centralised configuration loading and validation.

Every required environment variable is checked once at startup so the
container fails loudly with a clear error rather than misbehaving
silently inside a worker thread.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def _split_csv(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _split_int_csv(value: Optional[str]) -> List[int]:
    out: List[int] = []
    for item in _split_csv(value):
        try:
            out.append(int(item))
        except ValueError:
            logger.warning("Ignoring non-integer entry %r", item)
    return out


@dataclass
class Settings:
    # RAG / knowledge-base service
    anythingllm_base_url: str
    anythingllm_api_key: str
    anythingllm_workspace: str

    # Telegram (python-telegram-bot for Q&A; Telethon for legacy stats jobs)
    telegram_bot_token: Optional[str]
    telegram_api_id: Optional[int]
    telegram_api_hash: Optional[str]
    telegram_session_name: str
    telegram_admin_user_ids: List[int]
    telegram_announce_group_ids: List[int]
    telegram_analysis_channels: List[str]
    telegram_customer_service_group_id: Optional[int]

    # Discord
    discord_bot_token: Optional[str]
    discord_guild_id: Optional[int]
    discord_admin_role_ids: List[int]

    # Filesystem / runtime
    data_dir: Path
    faq_dir: Path

    # Behaviour toggles
    enable_telegram_qa: bool = True
    enable_discord_qa: bool = True
    enable_blockchain_jobs: bool = True
    enable_customer_analysis_job: bool = True

    # Internal
    rag_request_timeout: float = 60.0
    rag_max_question_chars: int = 4000

    @property
    def telegram_legacy_enabled(self) -> bool:
        """Telethon-based stats / analysis jobs need API id+hash."""
        return bool(self.telegram_api_id and self.telegram_api_hash)


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def load_settings() -> Settings:
    load_dotenv()

    base_url = os.getenv("ANYTHINGLLM_BASE_URL", "http://anythingllm:3001").rstrip("/")
    api_key = os.getenv("ANYTHINGLLM_API_KEY", "")
    workspace = os.getenv("ANYTHINGLLM_WORKSPACE", "tari")

    if not api_key:
        raise RuntimeError(
            "ANYTHINGLLM_API_KEY is required. Generate one in the AnythingLLM "
            "admin UI (Settings -> API Keys) and add it to your .env file."
        )

    telegram_api_id_raw = os.getenv("TELEGRAM_API_ID")
    telegram_api_id: Optional[int] = None
    if telegram_api_id_raw:
        try:
            telegram_api_id = int(telegram_api_id_raw)
        except ValueError as exc:
            raise RuntimeError("TELEGRAM_API_ID must be an integer") from exc

    discord_guild_raw = os.getenv("DISCORD_GUILD_ID")
    discord_guild_id: Optional[int] = None
    if discord_guild_raw:
        try:
            discord_guild_id = int(discord_guild_raw)
        except ValueError as exc:
            raise RuntimeError("DISCORD_GUILD_ID must be an integer") from exc

    customer_group_raw = os.getenv("TELEGRAM_CUSTOMER_SERVICE_GROUP_ID")
    customer_group: Optional[int] = None
    if customer_group_raw:
        try:
            customer_group = int(customer_group_raw)
        except ValueError as exc:
            raise RuntimeError(
                "TELEGRAM_CUSTOMER_SERVICE_GROUP_ID must be an integer"
            ) from exc

    settings = Settings(
        anythingllm_base_url=base_url,
        anythingllm_api_key=api_key,
        anythingllm_workspace=workspace,
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
        telegram_api_id=telegram_api_id,
        telegram_api_hash=os.getenv("TELEGRAM_API_HASH") or None,
        telegram_session_name=os.getenv("TELEGRAM_SESSION_NAME", "tari_bridge"),
        telegram_admin_user_ids=_split_int_csv(os.getenv("TELEGRAM_ADMIN_USER_IDS")),
        telegram_announce_group_ids=_split_int_csv(
            os.getenv("TELEGRAM_ANNOUNCE_GROUP_IDS")
        ),
        telegram_analysis_channels=_split_csv(os.getenv("TELEGRAM_ANALYSIS_CHANNELS")),
        telegram_customer_service_group_id=customer_group,
        discord_bot_token=os.getenv("DISCORD_BOT_TOKEN") or None,
        discord_guild_id=discord_guild_id,
        discord_admin_role_ids=_split_int_csv(os.getenv("DISCORD_ADMIN_ROLE_IDS")),
        data_dir=Path(os.getenv("BRIDGE_DATA_DIR", "./data")).resolve(),
        faq_dir=Path(os.getenv("BRIDGE_FAQ_DIR", "./faqs")).resolve(),
        enable_telegram_qa=_bool_env("ENABLE_TELEGRAM_QA", True),
        enable_discord_qa=_bool_env("ENABLE_DISCORD_QA", True),
        enable_blockchain_jobs=_bool_env("ENABLE_BLOCKCHAIN_JOBS", True),
        enable_customer_analysis_job=_bool_env("ENABLE_CUSTOMER_ANALYSIS_JOB", True),
    )

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings
