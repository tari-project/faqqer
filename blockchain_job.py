import asyncio
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from telethon.tl.types import PeerChat, PeerChannel
from apscheduler.triggers.cron import CronTrigger
import requests
import random

# Initialize logging
logging.basicConfig(level=logging.INFO)

# Group IDs for posting announcements (blockchain stats, customer analysis, etc.)
group_ids = [ -1002281038272, -1188782007] # -2165121610,

# Customer Analysis Configuration
ANALYSIS_CHANNELS = ["tariproject"]  # Channels to analyze for customer issues
ANALYSIS_HOURS = 3  # Hours back to analyze
CUSTOMER_SERVICE_GROUP_ID = -1002281038272  # Where to post customer analysis results

# Helper function to format hash rate with appropriate units
def format_hash_rate(hash_rate):
    units = ['H', 'kH', 'MH', 'GH', 'TH', 'PH', 'EH']
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
    units = ['g', 'Kg', 'Mg', 'Gg', 'Tg', 'Pg', 'Eg']
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
def get_latest_info():
    url = "https://textexplore.tari.com/?json"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        block_height = int(data['tipInfo']['metadata']['best_block_height'])
        currentShaHashRate = int(str(data['currentSha3xHashRate']).replace(',', ''))
        currentMoneroHashRate = int(str(data['currentMoneroRandomxHashRate']).replace(',', ''))
        currentTariRXHashRate = int(str(data['currentTariRandomxHashRate']).replace(',', ''))
        currentCuckarooHashRate = float(data['currentCuckarooHashRate']) 
        return block_height, currentShaHashRate, currentMoneroHashRate, currentTariRXHashRate, currentCuckarooHashRate
    else:
        raise Exception(f"Failed to fetch data: {response.status_code}")

async def post_block_height(client):
    try:
        # Fetch the block height stats
        block_height, x, y, z, w = get_latest_info()

        # List of sample questions
        questions = [
            "What are gems?",
            "What is Tari Universe?",
            "What is tXTM?",
            "What is the reward for mining?",
            "When will I earn tXTM?",
            "What is the block height?"
        ]

        # Select a random question from the list
        random_question = random.choice(questions)

        # Format the block height stats with the random question
        block_height_stats = f"Current Tari block height: ~{block_height:,}. Got a question? Type e.g. '/faq {random_question}' in any language to get answers to recent questions."
        # Loop over the group IDs and send the message
        for group_id in group_ids:
            try:
                # Determine if the ID is for a channel/supergroup (PeerChannel) or regular group (PeerChat)
                if group_id < 0:  # This indicates a channel or supergroup
                    peer = PeerChannel(group_id)
                else:  # This is a regular group
                    peer = PeerChat(group_id)

                # Send the message to the group/channel
                await client.send_message(peer, block_height_stats)
                logging.info(f"Posted block height stats to group ID {group_id}: {block_height_stats}")
            except Exception as e:
                logging.error(f"Error posting block height stats to group ID {group_id}: {e}")
    except Exception as e:
        logging.error(f"Error fetching block height stats: {e}")
        
def schedule_block_height_job(client, loop):
    # Initialize the scheduler
    scheduler = BackgroundScheduler()

    # Add the job to post block height every 4 hours
    scheduler.add_job(lambda: loop.create_task(post_block_height(client)),
                      CronTrigger.from_crontab('0 */4 * * *'))

    # Start the scheduler
    scheduler.start()

    logging.info("Scheduler started for block height job")

async def post_hash_power(client):
    try:
        # Fetch block height and hash rates
        block_height, current_sha_hash_rate, current_rxm_hash_rate, current_rxt_hash_rate, current_cuckaroo_hash_rate = get_latest_info()
        
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
        for group_id in group_ids:
            try:
                # Determine if the ID is for a channel/supergroup (PeerChannel) or regular group (PeerChat)
                if group_id < 0:  # This indicates a channel or supergroup
                    peer = PeerChannel(group_id)
                else:  # This is a regular group
                    peer = PeerChat(group_id)

                # Send the message to the group/channel
                await client.send_message(peer, hash_power_stats)
                logging.info(f"Posted hash power stats to group ID {group_id}")
            except Exception as e:
                logging.error(f"Error posting hash power stats to group ID {group_id}: {e}")
    except Exception as e:
        logging.error(f"Error fetching hash power stats: {e}")

def schedule_hash_power_job(client, loop):
    # Initialize the scheduler
    scheduler = BackgroundScheduler()

    # Add the job to post hash power twice daily (every 12 hours)
    scheduler.add_job(lambda: loop.create_task(post_hash_power(client)),
                      CronTrigger.from_crontab('0 */12 * * *'))

    # Start the scheduler
    scheduler.start()

    logging.info("Scheduler started for hash power job (twice daily)")


if __name__ == "__main__":
    # test post hash power function
    # call and print the result
    block_height, current_sha_hash_rate, current_rxm_hash_rate, current_rxt_hash_rate, current_cuckaroo_hash_rate = get_latest_info()
    formatted_sha_hash_rate = format_hash_rate(current_sha_hash_rate)
    formatted_rxm_hash_rate = format_hash_rate(current_rxm_hash_rate)
    formatted_rxt_hash_rate = format_hash_rate(current_rxt_hash_rate)
    formatted_cuckaroo_hash_rate = format_cuckaroo_rate(current_cuckaroo_hash_rate)
    print(f"Block Height: {block_height:,}")
    print(f"RandomX (Tari) Hash Rate: {formatted_rxt_hash_rate}")
    print(f"RandomX (Merged-Mined XMR) Hash Rate: {formatted_rxm_hash_rate}")
    print(f"SHA3x Hash Rate: {formatted_sha_hash_rate}")
    print(f"Cuckaroo Hash Rate: {formatted_cuckaroo_hash_rate}")


