# Tari AI Help Bot (v2)

A multi-channel AI help bot for the Tari community that answers questions on **Telegram** and **Discord** using a retrieval-augmented generation (RAG) pipeline backed by [AnythingLLM](https://github.com/Mintplex-Labs/anything-llm). The bot is grounded in an updatable knowledge base built from the `faqs/` directory, learns from admin-approved answers, and continues running the original scheduled blockchain stats and customer-analysis jobs without modification.

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Docker + Docker Compose v2 | `docker compose version` should print v2.x |
| AnythingLLM API key | Generated in the admin UI after first boot (step 4 below) |
| Telegram bot token | Create a bot with [@BotFather](https://t.me/BotFather) |
| Discord bot token | Create an application at [discord.com/developers](https://discord.com/developers/applications) |
| OpenAI API key | Or configure a different LLM provider in `.env` |
| Telethon credentials _(optional)_ | Required only for the blockchain stats / customer-analysis jobs; obtain from [my.telegram.org/apps](https://my.telegram.org/apps) |

---

## Quick start

```bash
# 1. Clone the repository
git clone https://github.com/tari-project/faqqer.git
cd faqqer

# 2. Copy the example environment file
cp .env.example .env

# 3. Open .env in your editor and fill in at minimum:
#    OPENAI_API_KEY, TELEGRAM_BOT_TOKEN, DISCORD_BOT_TOKEN
#    (leave ANYTHINGLLM_API_KEY blank for now — you will generate it in step 4)
$EDITOR .env

# 4. Start AnythingLLM and generate an API key
docker compose up -d anythingllm
# Open http://localhost:3001 in your browser
# Complete the setup wizard, then go to Settings → API Keys → Create new key
# Copy the key into ANYTHINGLLM_API_KEY in your .env file

# 5. Start the bridge
docker compose up -d bridge
# Tail the logs to confirm startup
docker compose logs -f bridge
```

The bridge will:
- Wait for AnythingLLM to become reachable.
- Create the `tari` workspace if it does not exist.
- Bulk-upload every `.txt` / `.md` file from `faqs/` into the knowledge base (idempotent — safe to restart).
- Start the Telegram and Discord bots.
- Register the `/ask` slash command with Discord.
- Start the APScheduler for the blockchain stats and customer-analysis jobs.

---

## Adding and updating the knowledge base

The `faqs/` directory is bind-mounted (read-only) into the bridge container.  To add or update knowledge:

1. Place `.txt` or `.md` files in `faqs/` on the host.
2. Restart the bridge to trigger re-ingest:
   ```bash
   docker compose restart bridge
   ```
   The bridge checks a manifest (`data/kb_manifest.json`) and only uploads files it has not seen before.  To force a full re-ingest after editing existing files, remove the manifest first:
   ```bash
   docker compose exec bridge rm /app/data/kb_manifest.json
   docker compose restart bridge
   ```

You can also upload documents directly via the AnythingLLM admin UI at `http://localhost:3001` without restarting the bridge.

---

## How admin feedback learning works

Every answer the bot sends is stored temporarily in a feedback cache (`data/feedback_pending.json`).

**Telegram:** An admin (whose user ID is in `TELEGRAM_ADMIN_USER_IDS`) replies to a bot message with `/approve`.

**Discord:** An admin replies to a bot message with `!approve`, or reacts to it with 👍 (the bot detects the reaction if the reactor holds a role listed in `DISCORD_ADMIN_ROLE_IDS`).

When an answer is approved, the question–answer pair is formatted as a Markdown document and uploaded into the AnythingLLM workspace.  From that point onward the approved answer is part of the retrieval context and will influence future responses to similar questions.

---

## Architecture overview

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for:
- Framework selection rationale (why AnythingLLM)
- Full component breakdown
- Data-flow diagram
- Security notes

---

## Job schedules

The two legacy scheduled jobs are preserved verbatim and wrapped by `bridge/jobs.py`.

| Job | Default schedule | Env flag to disable |
|---|---|---|
| Block height post to Telegram | Every 4 hours (`0 */4 * * *`) | `ENABLE_BLOCKCHAIN_JOBS=false` |
| Hash-power stats post to Telegram | Every 12 hours (`0 */12 * * *`) | `ENABLE_BLOCKCHAIN_JOBS=false` |
| Customer service analysis | Every 3 hours (`0 */3 * * *`) | `ENABLE_CUSTOMER_ANALYSIS_JOB=false` |

Both jobs require Telethon user-account credentials (`TELEGRAM_API_ID` and `TELEGRAM_API_HASH`).  If these are absent the jobs are skipped gracefully; all bot Q&A functionality continues normally.

The customer-analysis job also requires `OPENAI_API_KEY` for the analysis step and `TELEGRAM_PHONE_NUMBER` for reading channel history (user-account access only).

Job state is persisted in `data/jobs.sqlite` so jobs survive container restarts without double-firing.

---

## Environment variables reference

See [.env.example](.env.example) for the full annotated list.  The minimum required set to get Q&A working is:

```
OPENAI_API_KEY
ANYTHINGLLM_API_KEY    # generated in step 4 above
TELEGRAM_BOT_TOKEN     # or leave blank to disable Telegram
DISCORD_BOT_TOKEN      # or leave blank to disable Discord
```
