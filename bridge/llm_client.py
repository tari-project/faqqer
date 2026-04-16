import logging
import os
import httpx

logger = logging.getLogger(__name__)

_FALLBACK = (
    "Sorry, I couldn't find an answer.\n"
    "Please ask in the support channel."
)


async def ask_anythingllm(question: str) -> str:
    try:
        base_url = os.getenv("ANYTHINGLLM_BASE_URL", "").strip().rstrip("/")
        api_key = os.getenv("ANYTHINGLLM_API_KEY", "").strip()
        workspace_slug = os.getenv("ANYTHINGLLM_WORKSPACE_SLUG", "").strip()

        if not base_url or not api_key or not workspace_slug:
            logger.warning("AnythingLLM env vars missing, returning fallback")
            return _FALLBACK

        url = f"{base_url}/api/v1/workspace/{workspace_slug}/chat"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {"message": question, "mode": "chat"}

        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        text = data.get("textResponse")
        if not isinstance(text, str) or not text.strip():
            logger.warning("AnythingLLM returned empty textResponse")
            return _FALLBACK

        return text

    except Exception as e:
        logger.error("AnythingLLM request failed: %s", e)
        return _FALLBACK
