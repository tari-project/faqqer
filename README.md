# Faqqer V2  Self-Learning Multi-Channel AI Help Bot

## Framework Choice
AnythingLLM was selected over Quivr, Danswer, and RAGFlow because it is Docker-native, exposes a simple REST API for chat and document ingestion, includes a built-in admin UI for non-developers to manage knowledge, uses LanceDB as a lightweight vector DB, and is model-agnostic so the LLM provider can be swapped without rewriting the bot.

## Architecture
Two-service design:
- Service A: AnythingLLM (Brain)  RAG backend, vector DB, admin UI at localhost:3001
- Service B: Python Bridge  async Telegram + Discord listeners, background scheduled jobs, KB feedback loop

## Quick Start (Docker)

CRITICAL: Follow these steps in exact order.
AnythingLLM generates API keys only after the web wizard
is completed. The bridge container must be restarted
after the API key is added to .env.

1. Clone the repo
2. Copy bridge/.env.example to bridge/.env
   Fill in: TELEGRAM_BOT_TOKEN, DISCORD_BOT_TOKEN,
   OPENAI_API_KEY
3. Run: docker-compose up -d
   (starts AnythingLLM and bridge containers)
4. Open http://localhost:3001 and complete the setup
   wizard. Select OpenAI as LLM provider and paste
   your OpenAI API key. Create a workspace named "tari".
5. In AnythingLLM go to Settings  API Keys
   Generate New API Key. Copy the key.
   Add to bridge/.env:
     ANYTHINGLLM_API_KEY=your_key_here
     ANYTHINGLLM_WORKSPACE_SLUG=tari
6. Restart bridge to load the new keys:
   docker-compose restart bridge
7. Bootstrap the knowledge base:
   docker exec faqqer-bridge python init_kb.py
   (uploads all files from faqs/ into AnythingLLM,
   skipping faq_l2_general.txt automatically)
8. Invite your Telegram bot and Discord bot to their
   respective servers. For Discord, ensure the bot has
   the applications.commands scope and reactions intent.

## Environment Variables
| Variable | Description | Default |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token used by the bridge listener. | (empty) |
| `DISCORD_BOT_TOKEN` | Discord bot token used by the bridge listener. | (empty) |
| `DISCORD_TEST_GUILD_ID` | Optional: guild-specific slash-command sync for faster testing. | (empty) |
| `TELEGRAM_ADMIN_IDS` | Comma-separated Telegram user IDs allowed to 💾 save Q&A to the KB. | (empty) |
| `DISCORD_ADMIN_ROLE_ID` | Discord role ID required to 💾 save Q&A to the KB. | (empty) |
| `ANYTHINGLLM_BASE_URL` | AnythingLLM base URL (no trailing slash). In Docker this is overridden to `http://anythingllm:3001`. | `http://localhost:3001` |
| `ANYTHINGLLM_API_KEY` | AnythingLLM API key for chat + document upload endpoints. | (empty) |
| `ANYTHINGLLM_WORKSPACE_SLUG` | AnythingLLM workspace slug used by the bridge. | `tari` |
| `BLOCKCHAIN_TARGET_CHAT_IDS` | Comma-separated Telegram chat IDs to post blockchain stats into. | (empty) |
| `TARI_EXPLORER_URL` | Explorer endpoint used for block height + hash rate stats. | `https://textexplore.tari.com/?json` |
| `BLOCK_HEIGHT_CRON` | Cron schedule for block height posts. | `0 */4 * * *` |
| `HASH_POWER_CRON` | Cron schedule for hash power posts. | `0 */12 * * *` |
| `CUSTOMER_ANALYSIS_CRON` | Cron schedule for customer service analysis posts. | `0 */3 * * *` |
| `CUSTOMER_SERVICE_GROUP_ID` | Telegram chat ID where the customer analysis summary is posted. | (empty) |
| `ANALYSIS_CHANNELS` | Comma-separated Telegram channel usernames to scan. | `tariproject` |
| `ANALYSIS_HOURS` | Hours of history to analyze per run. | `3` |
| `ANALYSIS_MODEL` | OpenAI model used for customer service analysis. | `gpt-4o` |
| `ANALYSIS_TEMPERATURE` | OpenAI temperature used for customer service analysis. | `0.3` |

## Self-Learning Loop
Explain the admin-gated 💾 reaction workflow:
- User asks a question, bot answers from knowledge base
- Admin reacts with 💾 to the bot's answer message
- Q&A pair is pushed to AnythingLLM as a pending document
- Community manager reviews and clicks Save and Embed
  in the AnythingLLM admin UI at localhost:3001
- Bot uses updated knowledge in all future answers
- 👍 reactions are logged as analytics only,
  no KB write occurs

## Background Jobs
Three scheduled jobs (all configurable via env vars):
- Block Height: posts current Tari block height
  to configured Telegram chats (default: every 4 hours)
- Hash Power: posts full network hash rate stats
  (default: every 12 hours)
- Customer Analysis: scans configured Telegram channels,
  analyzes support issues via OpenAI, posts summary
  (default: every 3 hours, requires TELEGRAM_PHONE_NUMBER)

## Knowledge Base Updates
Two ways to update without code changes or redeployment:
1. Edit or add files in faqs/ directory, then run:
   docker exec faqqer-bridge python init_kb.py
2. Use AnythingLLM admin UI directly at localhost:3001
   to upload documents, URLs, or paste text directly

## Acceptance Criteria Coverage
Add a section explicitly mapping each bounty acceptance
criterion to how this PR satisfies it:
- Framework selected: AnythingLLM (see Framework Choice)
- Telegram answers grounded in KB: llm_client.py queries
  AnythingLLM workspace via REST API
- Discord answers grounded in KB: same AnythingLLM
  workspace via /ask slash command
- KB update without code changes: AnythingLLM admin UI
  or re-running init_kb.py
- Self-learning from feedback: 💾 admin reaction loop
- Legacy jobs preserved: blockchain_job.py and
  customer_analysis_job.py ported to bridge/jobs/
- Docker containerization: docker-compose.yml with
  AnythingLLM + bridge, optimized for 2GB RAM / 2-core
