"""Feedback pipeline.

Tracks the most recent answers a user has received so that a thumbs-up
reaction or an admin ``!approve`` command can promote a Q&A pair into
the knowledge base. The store is intentionally in-memory + a small
on-disk JSON shadow; we do not need a real database for this and any
loss only costs the most recent feedback opportunities.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from .rag_client import AnythingLLMClient, RAGError

logger = logging.getLogger(__name__)


@dataclass
class QAPair:
    channel: str          # "telegram" | "discord"
    chat_id: str
    message_id: str
    user_id: str
    question: str
    answer: str
    created_at: float


class FeedbackStore:
    def __init__(self, data_dir: Path, max_entries: int = 5000) -> None:
        self._max = max_entries
        self._path = data_dir / "feedback_pending.json"
        self._lock = asyncio.Lock()
        self._entries: "OrderedDict[str, QAPair]" = OrderedDict()
        self._load()

    @staticmethod
    def make_key(channel: str, chat_id: str, message_id: str) -> str:
        return f"{channel}:{chat_id}:{message_id}"

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            for key, payload in raw.items():
                self._entries[key] = QAPair(**payload)
        except (json.JSONDecodeError, OSError, TypeError) as exc:
            logger.warning("Could not load feedback store: %s", exc)

    async def _flush_locked(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = {k: asdict(v) for k, v in self._entries.items()}
            self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not persist feedback store: %s", exc)

    async def record(self, pair: QAPair) -> None:
        async with self._lock:
            key = self.make_key(pair.channel, pair.chat_id, pair.message_id)
            self._entries[key] = pair
            self._entries.move_to_end(key)
            while len(self._entries) > self._max:
                self._entries.popitem(last=False)
            await self._flush_locked()

    async def get(
        self, channel: str, chat_id: str, message_id: str
    ) -> Optional[QAPair]:
        async with self._lock:
            return self._entries.get(self.make_key(channel, chat_id, message_id))

    async def latest_for_user(
        self, channel: str, user_id: str
    ) -> Optional[QAPair]:
        async with self._lock:
            for pair in reversed(self._entries.values()):
                if pair.channel == channel and pair.user_id == user_id:
                    return pair
            return None

    async def remove(self, channel: str, chat_id: str, message_id: str) -> None:
        async with self._lock:
            self._entries.pop(self.make_key(channel, chat_id, message_id), None)
            await self._flush_locked()


async def promote_to_kb(rag: AnythingLLMClient, pair: QAPair, approver: str) -> None:
    """Push an approved Q&A pair into the knowledge base."""
    try:
        title = (
            f"approved-qa/{pair.channel}/"
            f"{pair.chat_id}-{pair.message_id}"
        )
        body = (
            "# Approved Q&A\n\n"
            f"_Source channel:_ {pair.channel}\n"
            f"_Approved by:_ {approver}\n"
            f"_Approved at:_ {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n\n"
            f"## Question\n\n{pair.question.strip()}\n\n"
            f"## Answer\n\n{pair.answer.strip()}\n"
        )
        await rag.upload_text_document(
            title=title, body=body, source="feedback/approved"
        )
    except RAGError:
        # Already logged inside the client; re-raise so callers can surface
        # an error to the requesting admin.
        raise
