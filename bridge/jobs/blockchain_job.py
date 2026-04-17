import logging
import os
import random

import httpx

logger = logging.getLogger(__name__)

BLOCK_HEIGHT_CRON_DEFAULT = "0 */4 * * *"
HASH_POWER_CRON_DEFAULT = "0 */12 * * *"


def _load_target_chat_ids() -> list[int]:
    raw = os.getenv("BLOCKCHAIN_TARGET_CHAT_IDS", "")
    chat_ids: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            chat_ids.append(int(part))
        except ValueError:
            logger.warning("Ignoring invalid BLOCKCHAIN_TARGET_CHAT_IDS entry: %r", part)
    return chat_ids


# Helper function to format hash rate with appropriate units
def format_hash_rate(hash_rate):
    units = ["H", "kH", "MH", "GH", "TH", "PH", "EH"]
    unit_index = 0

    # Adjust the unit until we get a readable number
    while hash_rate >= 1000 and unit_index < len(units) - 1:
        hash_rate /= 1000
        unit_index += 1

    # Format with appropriate precision based on the value
    if hash_rate < 10:
        return f"{hash_rate:.2f} {units[unit_index]}"
    elif hash_rate < 100:
        return f"{hash_rate:.1f} {units[unit_index]}"
    else:
        return f"{int(hash_rate)} {units[unit_index]}"


# Helper function to format Cuckaroo hash rate with graph units
def format_cuckaroo_rate(hash_rate):
    units = ["g", "Kg", "Mg", "Gg", "Tg", "Pg", "Eg"]
    unit_index = 0

    # Adjust the unit until we get a readable number
    while hash_rate >= 1000 and unit_index < len(units) - 1:
        hash_rate /= 1000
        unit_index += 1

    # Format with appropriate precision based on the value
    if hash_rate < 10:
        return f"{hash_rate:.2f} {units[unit_index]}"
    elif hash_rate < 100:
        return f"{hash_rate:.1f} {units[unit_index]}"
    else:
        return f"{int(hash_rate)} {units[unit_index]}"


# Function to get the latest block height and metadata
async def get_latest_info() -> tuple[int, int, int, int, float]:
    url = os.getenv("TARI_EXPLORER_URL", "https://textexplore.tari.com/?json").strip()
    if not url:
        url = "https://textexplore.tari.com/?json"
logger = logging.getLogger(__name__)

# Initialize a persistent client
_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))

BLOCK_HEIGHT_CRON_DEFAULT = "0 */4 * * *"

# ... (rest of the file)

# Function to get the latest block height and metadata
async def get_latest_info() -> tuple[int, int, int, int, float]:
    url = os.getenv("TARI_EXPLORER_URL", "https://textexplore.tari.com/?json").strip()
    if not url:
        url = "https://textexplore.tari.com/?json"
    
    response = await _client.get(url)
    response.raise_for_status()
    data = response.json()
        response = await client.get(url)
        response.raise_for_status()
        data = response.json()

    def _to_int(value) -> int:
        try:
            return int(float(str(value).replace(",", "")))
        except Exception:
            return 0

    def _to_float(value) -> float:
        try:
            return float(str(value).replace(",", ""))
        except Exception:
            return 0.0

    block_height = _to_int(((data.get("tipInfo") or {}).get("metadata") or {}).get("best_block_height", 0))
    currentShaHashRate = _to_int(data.get("currentSha3xHashRate", 0))
    currentMoneroHashRate = _to_int(data.get("currentMoneroRandomxHashRate", 0))
    currentTariRXHashRate = _to_int(data.get("currentTariRandomxHashRate", 0))
    currentCuckarooHashRate = _to_float(data.get("currentCuckarooHashRate", 0))
    return block_height, currentShaHashRate, currentMoneroHashRate, currentTariRXHashRate, currentCuckarooHashRate


async def post_block_height(bot):
    chat_ids = _load_target_chat_ids()
    if not chat_ids:
        logger.info("No BLOCKCHAIN_TARGET_CHAT_IDS configured; skipping block height post")
        return

    try:
        # Fetch the block height stats
        block_height, *_ = await get_latest_info()

        # List of sample questions
        questions = [
            "What are gems?",
            "What is Tari Universe?",
            "What is tXTM?",
            "What is the reward for mining?",
            "When will I earn tXTM?",
            "What is the block height?",
        ]

        # Select a random question from the list
        random_question = random.choice(questions)

        # Format the block height stats with the random question
        block_height_stats = (
            f"Current Tari block height: ~{block_height:,}. Got a question? Just type it here (e.g. '{random_question}') "
            "in any language to get answers to recent questions."
        )
        # Loop over the group IDs and send the message
        for chat_id in chat_ids:
            try:
                await bot.send_message(chat_id=chat_id, text=block_height_stats)
                logger.info("Posted block height stats to chat ID %s: %s", chat_id, block_height_stats)
            except Exception as e:
                logger.error("Error posting block height stats to chat ID %s: %s", chat_id, e)
    except Exception as e:
        logger.error("Error fetching block height stats: %s", e)


async def post_hash_power(bot):
    chat_ids = _load_target_chat_ids()
    if not chat_ids:
        logger.info("No BLOCKCHAIN_TARGET_CHAT_IDS configured; skipping hash power post")
        return

    try:
        # Fetch block height and hash rates
        (
            block_height,
            current_sha_hash_rate,
            current_rxm_hash_rate,
            current_rxt_hash_rate,
            current_cuckaroo_hash_rate,
        ) = await get_latest_info()

        # Format the hash rates with appropriate units
        formatted_sha_hash_rate = format_hash_rate(current_sha_hash_rate)
        formatted_rxm_hash_rate = format_hash_rate(current_rxm_hash_rate)
        formatted_rxt_hash_rate = format_hash_rate(current_rxt_hash_rate)
        formatted_cuckaroo_hash_rate = format_cuckaroo_rate(current_cuckaroo_hash_rate)

        # Create the hash power stats message
        hash_power_stats = (
            f"📊 Current Tari Network Stats 📊\n"
            f"Block Height: {block_height:,}\n"
            f"RandomX (Tari): {formatted_rxt_hash_rate}\n"
            f"RandomX (Merged-Mined XMR): {formatted_rxm_hash_rate}\n"
            f"SHA3x: {formatted_sha_hash_rate}\n"
            f"Cuckaroo 29: {formatted_cuckaroo_hash_rate}\n\n"
            f"Want to learn more? Try '@faqqer mining' to get information about mining Tari."
        )

        # Loop over the group IDs and send the message
        for chat_id in chat_ids:
            try:
                await bot.send_message(chat_id=chat_id, text=hash_power_stats)
                logger.info("Posted hash power stats to chat ID %s", chat_id)
            except Exception as e:
                logger.error("Error posting hash power stats to chat ID %s: %s", chat_id, e)
    except Exception as e:
        logger.error("Error fetching hash power stats: %s", e)
