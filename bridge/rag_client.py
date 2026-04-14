"""Async client for AnythingLLM's REST API.

We deliberately keep this thin so swapping AnythingLLM out for another
RAG framework (LibreChat, Danswer, etc.) is a single-file change.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


class RAGError(RuntimeError):
    """Raised when the knowledge-base service cannot answer a query."""


class RAGEmptyKnowledgeBase(RAGError):
    """The KB has no documents yet."""


# Phrases AnythingLLM emits when a workspace has no documents or
# the LLM declines to answer for lack of context. We detect these so
# end-users get a friendlier message.
_EMPTY_KB_HINTS = (
    "no relevant",
    "do not have any information",
    "i don't know",
    "no context",
    "i was not able",
)


class AnythingLLMClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        workspace: str,
        timeout: float = 60.0,
        max_question_chars: int = 4000,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._workspace = workspace
        self._timeout = timeout
        self._max_question_chars = max_question_chars
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        }

    async def wait_until_ready(self, max_seconds: float = 300.0) -> None:
        """Block until AnythingLLM responds to /api/v1/auth.

        The compose stack starts both services in parallel, so the bridge
        worker must tolerate the RAG container coming up later.
        """
        deadline = asyncio.get_event_loop().time() + max_seconds
        delay = 1.0
        async with httpx.AsyncClient(timeout=10.0, headers=self._headers) as client:
            while True:
                try:
                    resp = await client.get(f"{self._base_url}/api/v1/auth")
                    if resp.status_code < 500:
                        logger.info("AnythingLLM is reachable (status=%s)", resp.status_code)
                        return
                except httpx.HTTPError as exc:
                    logger.info("Waiting for AnythingLLM... (%s)", exc)
                if asyncio.get_event_loop().time() > deadline:
                    raise RAGError(
                        f"AnythingLLM never became reachable at {self._base_url}"
                    )
                await asyncio.sleep(delay)
                delay = min(delay * 1.5, 15.0)

    async def ensure_workspace(self) -> None:
        """Create the workspace if it does not already exist."""
        async with httpx.AsyncClient(
            timeout=self._timeout, headers=self._headers
        ) as client:
            resp = await client.get(f"{self._base_url}/api/v1/workspaces")
            if resp.status_code == 200:
                workspaces = resp.json().get("workspaces", [])
                slugs = {w.get("slug") for w in workspaces}
                if self._workspace in slugs:
                    return
            create = await client.post(
                f"{self._base_url}/api/v1/workspace/new",
                json={"name": self._workspace},
            )
            if create.status_code >= 400:
                raise RAGError(
                    f"Could not create workspace {self._workspace!r}: "
                    f"{create.status_code} {create.text[:200]}"
                )
            logger.info("Created AnythingLLM workspace %s", self._workspace)

    async def ask(self, question: str, session_id: Optional[str] = None) -> str:
        question = (question or "").strip()
        if not question:
            raise RAGError("Empty question")
        if len(question) > self._max_question_chars:
            question = question[: self._max_question_chars] + "\n[truncated]"

        payload: Dict[str, Any] = {
            "message": question,
            "mode": "chat",
        }
        if session_id:
            payload["sessionId"] = session_id

        url = f"{self._base_url}/api/v1/workspace/{self._workspace}/chat"

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(min=1, max=8),
            retry=retry_if_exception_type((httpx.HTTPError,)),
            reraise=True,
        ):
            with attempt:
                async with httpx.AsyncClient(
                    timeout=self._timeout, headers=self._headers
                ) as client:
                    resp = await client.post(url, json=payload)
                    if resp.status_code >= 500:
                        raise httpx.HTTPError(f"upstream {resp.status_code}")
                    if resp.status_code >= 400:
                        raise RAGError(
                            f"AnythingLLM rejected the request: "
                            f"{resp.status_code} {resp.text[:200]}"
                        )
                    data = resp.json()

        text = (
            data.get("textResponse")
            or data.get("response")
            or data.get("message")
            or ""
        ).strip()

        if not text:
            raise RAGEmptyKnowledgeBase(
                "The knowledge base did not return an answer."
            )

        if any(hint in text.lower() for hint in _EMPTY_KB_HINTS):
            # Surface a more helpful message to end-users.
            raise RAGEmptyKnowledgeBase(text)

        return text

    async def upload_text_document(
        self,
        title: str,
        body: str,
        source: str = "bridge",
    ) -> None:
        """Push a text document into the workspace.

        Used both for the initial bulk-upload from ``faqs/`` and for
        feeding admin-approved Q&A pairs back into the KB.
        """
        body = (body or "").strip()
        if not body:
            return
        payload = {
            "textContent": body,
            "metadata": {
                "title": title,
                "source": source,
            },
            "addToWorkspaces": self._workspace,
        }
        async with httpx.AsyncClient(
            timeout=self._timeout, headers=self._headers
        ) as client:
            resp = await client.post(
                f"{self._base_url}/api/v1/document/raw-text", json=payload
            )
            if resp.status_code >= 400:
                raise RAGError(
                    f"Document upload failed: {resp.status_code} {resp.text[:200]}"
                )
        logger.info("Uploaded document %r to workspace %s", title, self._workspace)
