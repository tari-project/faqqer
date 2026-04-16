import logging
import os

import httpx

logger = logging.getLogger(__name__)


async def push_to_kb(question: str, answer: str) -> bool:
    try:
        base_url = os.getenv("ANYTHINGLLM_BASE_URL", "").strip().rstrip("/")
        api_key = os.getenv("ANYTHINGLLM_API_KEY", "").strip()
        workspace_slug = os.getenv("ANYTHINGLLM_WORKSPACE_SLUG", "").strip()

        if not base_url or not api_key or not workspace_slug:
            logger.warning("KB push failed: AnythingLLM env vars missing")
            return False

        url = f"{base_url}/api/v1/workspace/{workspace_slug}/upload-text"
        headers = {"Authorization": f"Bearer {api_key}"}
        title = f"Approved QA - {question[:40]}"
        payload = {
            "textContent": f"Q: {question}\nA: {answer}",
            "metadata": {"title": title},
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()

        logger.info("KB push succeeded title=%r", title)
        return True
    except Exception as e:
        logger.error("KB push failed: %s", e)
        return False
