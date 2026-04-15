# Architecture — Tari AI Help Bot (v2)

## Overview

The v2 help-bot replaces the original single-file `faqqer_bot.py` (OpenAI completions called directly from the bot handler) with a proper RAG pipeline backed by **AnythingLLM** and a structured multi-channel bridge worker.

```
                ┌─────────────────────────────────────────────────────┐
                │                  docker-compose stack                 │
                │                                                       │
 Telegram users │   ┌─────────────┐        ┌──────────────────────┐   │
 ───────────────┼──►│             │        │    AnythingLLM        │   │
                │   │   bridge    │◄──────►│  (RAG engine +        │   │
 Discord users  │   │   worker    │  REST  │   vector store +      │   │
 ───────────────┼──►│             │  API   │   admin UI)           │   │
                │   └──────┬──────┘        └──────────────────────┘   │
                │          │                        ▲                  │
                │    ┌─────▼──────┐                 │                  │
                │    │ APScheduler│         faqs/ volume mount         │
                │    │  (jobs)    │         (hot-reloadable KB files)  │
                │    └─────┬──────┘                                    │
                │          │                                           │
                │    ┌─────▼──────┐                                    │
                │    │  Telethon  │                                    │
                │    │  (legacy   │                                    │
                │    │   stats)   │                                    │
                │    └────────────┘                                    │
                └─────────────────────────────────────────────────────┘
```

---

## Framework selection rationale

### Why AnythingLLM instead of a bare OpenAI call?

| Concern | Old approach (direct completion) | New approach (AnythingLLM) |
|---|---|---|
| Knowledge-base updates | Code redeploy + prompt rewrite | Admin drops a file in the volume; `/reingest` or next auto-scan |
| Model lock-in | Hard-coded `gpt-4o` | Switchable via env var — OpenAI, Anthropic, Ollama, LocalAI, Azure |
| Admin visibility | None | Full admin UI at `:3001` — see docs, conversations, workspace settings |
| Grounding / citation | None | AnythingLLM embeds documents and retrieves relevant chunks |
| Docker-native | No | Official `mintplexlabs/anythingllm` image; no extra infra |
| REST API stability | N/A | Stable `/api/v1/workspace/{slug}/chat` endpoint; versioned |

AnythingLLM was preferred over alternatives for these reasons:

- **LibreChat** is a full chat UI product; it exposes no lightweight REST API suitable for bot integration.
- **Danswer / Perplexica** require a Postgres + Redis stack; heavier than necessary for a community bot.
- **LangChain + Chroma** would work but require writing and maintaining a RAG server ourselves; AnythingLLM ships that server already.
- **OpenAI Assistants API** locks us into a single provider and carries per-token costs for document storage.

---

## Component breakdown

### `bridge/config.py`

Single `Settings` dataclass loaded via `load_settings()`.  Every required env var is validated at startup and raises `RuntimeError` with a human-readable message before any network connection is attempted.  This means the container exits with code 2 and a clear log line rather than failing silently inside a worker thread.

### `bridge/rag_client.py` — `AnythingLLMClient`

Thin async HTTP wrapper around AnythingLLM's REST API.  Key behaviours:

- `wait_until_ready()` — polls `/api/v1/auth` with exponential back-off up to 5 minutes so the bridge tolerates AnythingLLM starting slowly.
- `ask()` — posts to `/api/v1/workspace/{slug}/chat`, retries up to 3× on HTTP errors, detects "I don't know" style responses and converts them to `RAGEmptyKnowledgeBase` so callers can give users a friendlier message.
- `upload_text_document()` — pushes plain-text documents into the workspace; used by both the initial KB seed and the feedback pipeline.

### `bridge/init_kb.py`

Bulk-uploads every `.txt` / `.md` file from `faqs/` into the AnythingLLM workspace on startup.  A JSON manifest (`data/kb_manifest.json`) tracks which files have already been uploaded so re-starts do not create duplicate documents.

### `bridge/telegram_bot.py`

Uses `python-telegram-bot` v21 (async).  Responds to:

- Direct messages (private chat)
- `@mention` in groups
- `/ask <question>` and `/faq <question>` commands
- `/approve` (admin-only) — promotes a replied-to bot answer into the KB

### `bridge/discord_bot.py`

Uses `discord.py` v2.4.  Responds to:

- `@mention` in any channel
- `/ask` slash command
- `!approve` prefix command (admin-only, also triggered by a 👍 reaction from an admin)

Discord message limit (2000 chars for regular messages, 4096 for embeds) is handled defensively: the `_answer()` helper returns the raw string from the RAG client; if AnythingLLM returns a very long answer the `rag_client` truncates the _question_ to `max_question_chars` before sending, and discord.py will raise `HTTPException` for overlong replies — callers should truncate or page if that becomes an issue in production.

### `bridge/feedback.py`

In-memory `OrderedDict` capped at 5000 entries with a JSON shadow file for persistence across restarts.  `promote_to_kb()` formats an approved Q&A pair as a structured Markdown document and uploads it via `upload_text_document()`.

### `bridge/jobs.py` — `JobRunner`

Wraps the two legacy modules via `importlib.import_module` so their source is never modified.  Uses APScheduler with a SQLite jobstore (`data/jobs.sqlite`) so jobs survive container restarts without double-firing.

| Job | Schedule | Legacy function |
|---|---|---|
| Block height post | `0 */4 * * *` (every 4 h) | `blockchain_job.post_block_height` |
| Hash-power post | `0 */12 * * *` (twice daily) | `blockchain_job.post_hash_power` |
| Customer analysis | `0 */3 * * *` (every 3 h) | `customer_analysis_job.run_customer_service_analysis` |

All three jobs require Telethon (user-account credentials).  If `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` are absent the jobs are skipped gracefully with an `INFO` log; the Q&A bots continue running unaffected.

### `bridge/main.py`

Entrypoint.  Boot sequence:

1. Load and validate `Settings` (exit 2 on config error).
2. Instantiate `AnythingLLMClient` and call `wait_until_ready()` (exit 3 if never reachable).
3. Seed knowledge base from `faqs/`.
4. Start Telegram bot task (if token present).
5. Start Discord bot task (if token present).
6. Start APScheduler.
7. Wait for SIGINT / SIGTERM; graceful shutdown of all components.

---

## Data flow — Q&A request

```
User message
    │
    ▼
telegram_bot._handle_question()  OR  discord_bot.on_message()
    │
    ▼
rag_client.ask(question)
    │  POST /api/v1/workspace/tari/chat
    ▼
AnythingLLM (retrieves relevant KB chunks, calls LLM, returns answer)
    │
    ▼
Bot sends reply to user
    │
    ▼
feedback.record(QAPair)   ← stored in memory + feedback_pending.json
    │
    (optional: admin /approve or 👍 reaction)
    ▼
feedback.promote_to_kb()
    │  POST /api/v1/document/raw-text
    ▼
AnythingLLM ingests approved Q&A as new KB document
```

---

## Updating the knowledge base

Any `.txt` or `.md` file placed in the `faqs/` directory (which is bind-mounted read-only into the bridge container) will be picked up on the next bridge restart, or immediately if you trigger a re-ingest via:

```bash
docker compose restart bridge
```

The manifest ensures existing documents are not re-uploaded.  To force a full re-ingest (e.g. after editing a file), delete `data/kb_manifest.json` before restarting.

---

## Security notes

- `ANYTHINGLLM_API_KEY` should be treated as a secret; it grants full API access including document deletion.
- The AnythingLLM admin UI port (3001) is exposed to the host by default for initial setup.  After generating an API key and finishing configuration, consider removing the `ports:` entry from `docker-compose.yml` or binding it to `127.0.0.1` only.
- Telethon session files are stored in the `bridge-data` Docker volume.  Protect this volume; it contains an authenticated Telegram user session.
