import asyncio
from telethon import TelegramClient
import os
import logging
import html
from datetime import datetime, timedelta
from dotenv import load_dotenv
import sys

# Load environment variables from the .env file
load_dotenv()

logger = logging.getLogger(__name__)

# Replace these with your actual API details
bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
api_id = os.getenv('TELEGRAM_API_ID')     # From Telegram Developer Portal
api_hash = os.getenv('TELEGRAM_API_HASH') # From Telegram Developer Portal
phone_number = os.getenv('TELEGRAM_PHONE_NUMBER')  # Your own Telegram phone number

# Default configuration
DEFAULT_CHANNELS = ["tariproject", "OrderOfSoon"]  # Target channel/group usernames
DEFAULT_HOURS_HISTORY = 24  # Number of hours of history to fetch
DEFAULT_OUTPUT_DIR = 'archive'
DEFAULT_MEDIA_FOLDER = 'media_files'

# Set up logging to print to console
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s', 
    stream=sys.stdout
)

def ensure_directories_exist(output_dir, media_folder):
    """Ensure output and media directories exist"""
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    if not os.path.exists(media_folder):
        os.makedirs(media_folder)

# Initialize the Telegram client for user login
_session_file = os.getenv("TELEGRAM_SESSION_FILE", "faq_archiver")
client = TelegramClient(_session_file, api_id, api_hash)

async def get_messages_from_channel(channel_username, hours_history, media_folder):
    """
    Fetches all messages from the given channel within the specified time period.
    Returns messages sorted in chronological order (oldest first).
    """
    now_utc_naive = datetime.utcnow()  # naive UTC
    cutoff_time_naive = now_utc_naive - timedelta(hours=hours_history)

    offset_id = 0
    limit = 100
    all_messages = []

    logging.info(f"Starting to fetch messages from the last {hours_history}h in channel: {channel_username}")

    while True:
        # Fetch up to 'limit' messages (newest first)
        messages = await client.get_messages(
            channel_username,
            limit=limit,
            offset_id=offset_id
        )
        
        if not messages:
            logging.info(f"No more messages found in {channel_username}. Stopping.")
            break

        # The oldest message in this batch
        batch_oldest_date = messages[-1].date.replace(tzinfo=None)

        # Keep only messages within the specified time period
        for msg in messages:
            msg_date_naive = msg.date.replace(tzinfo=None)
            if msg_date_naive >= cutoff_time_naive:
                # Add channel info to message for combined output
                msg.channel_name = channel_username
                all_messages.append(msg)

        # If the oldest message in the batch is older than our cutoff, stop
        if batch_oldest_date < cutoff_time_naive:
            break

        # Prepare to fetch older messages next time
        offset_id = messages[-1].id

        # Sleep to respect Telegram rate limits
        await asyncio.sleep(1)

    logging.info(f"Finished fetching from {channel_username}. Messages found: {len(all_messages)}")
    return all_messages

async def write_combined_text_history(all_messages, filepath, channels, hours_history):
    """Write combined messages from all channels to a text file"""
    with open(filepath, 'w', encoding='utf-8') as f:
        # Write header
        f.write(f"Combined Chat History for channels: {', '.join(channels)}\n")
        f.write(f"Time period: Last {hours_history} hours\n")
        f.write(f"Generated on: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n")
        f.write('=' * 70 + '\n\n')
        
        # To store a mapping of message ID to its content (used for "reply to" info)
        message_dict = {}
        
        for msg in all_messages:
            sender = await msg.get_sender()
            username = sender.username if sender else "Unknown"
            date_str = msg.date.strftime('%Y-%m-%d %H:%M:%S')
            content = msg.text or "Media message"
            channel_name = getattr(msg, 'channel_name', 'Unknown')

            # Check if message is a reply to another
            if msg.reply_to_msg_id:
                replied_message = message_dict.get(msg.reply_to_msg_id, "Unknown message")
                reply_info = f"(Replying to: {replied_message})"
            else:
                reply_info = ""

            # Add message content to dictionary for future replies
            message_dict[msg.id] = content

            f.write(f"Channel: {channel_name} | User: {username} | Date: {date_str}\n")
            f.write(f"Message: {content} {reply_info}\n")
            f.write('-' * 50 + '\n')  # Separator

    logging.info(f"Combined text chat history saved to {os.path.abspath(filepath)}")

async def write_combined_html_history(all_messages, filepath, channels, hours_history, media_folder):
    """Write combined messages from all channels to an HTML file"""
    with open(filepath, 'w', encoding='utf-8') as f:
        # HTML header and CSS
        f.write("""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Telegram Chat History</title>
    <style>
        body { font-family: Arial, sans-serif; background-color: #f5f5f5; }
        .message { background: #fff; margin: 10px; padding: 10px; border-radius: 5px; }
        .channel { font-weight: bold; color: #3498db; }
        .user { font-weight: bold; }
        .date { font-size: 0.9em; color: #888; }
        .content { margin-top: 5px; }
        .reply { margin-left: 20px; font-style: italic; color: #666; }
        .media { margin-top: 10px; }
    </style>
</head>
<body>
""")

        # Write header info
        f.write(f"<h1>Combined Chat History</h1>")
        f.write(f"<p><strong>Channels:</strong> {', '.join(channels)}</p>")
        f.write(f"<p><strong>Time period:</strong> Last {hours_history} hours</p>")
        f.write(f"<p><strong>Generated on:</strong> {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</p>")
        
        # To store a mapping of message ID to its content (used for "reply to" info)
        message_dict = {}

        for msg in all_messages:
            sender = await msg.get_sender()
            username = sender.username if sender else "Unknown"
            date_str = msg.date.strftime('%Y-%m-%d %H:%M:%S')
            content = msg.text or ""
            channel_name = getattr(msg, 'channel_name', 'Unknown')

            # Reply info
            if msg.reply_to_msg_id:
                replied_message = message_dict.get(msg.reply_to_msg_id, "Unknown message")
                reply_info = f'<div class="reply">Replying to: {html.escape(replied_message)}</div>'
            else:
                reply_info = ""

            media_reference = ""
            if msg.media:
                try:
                    media_path = await msg.download_media(file=media_folder)
                    if media_path:
                        media_filename = os.path.basename(media_path)
                        if media_filename.lower().endswith(('.jpg', '.jpeg', '.png', '.gif')):
                            media_reference = (
                                f'<div class="media">'
                                f'<img src="{media_folder}/{media_filename}" alt="Image" width="300">'
                                '</div>'
                            )
                        elif media_filename.lower().endswith(('.mp4', '.webm', '.mkv')):
                            media_reference = (
                                f'<div class="media">'
                                f'<video width="300" controls>'
                                f'<source src="{media_folder}/{media_filename}" type="video/mp4">'
                                'Your browser does not support the video tag.'
                                '</video></div>'
                            )
                        else:
                            media_reference = (
                                f'<div class="media">'
                                f'<a href="{media_folder}/{media_filename}" download>'
                                f'Download {media_filename}</a></div>'
                            )
                    else:
                        logging.warning(f"Failed to download media for message {msg.id}")
                except Exception as e:
                    logging.error(f"Error downloading media for message {msg.id}: {e}")

            # Store for future replies
            message_dict[msg.id] = content if content else "Media message"

            # HTML output
            f.write('<div class="message">')
            f.write(f'<div class="channel">#{channel_name}</div>')
            f.write(f'<div class="user">{username}</div>')
            f.write(f'<div class="date">{date_str}</div>')
            if content:
                f.write(f'<div class="content">{html.escape(content)}</div>')
            else:
                f.write(f'<div class="content">Media message</div>')
            f.write(reply_info)
            f.write(media_reference)
            f.write('</div>')

        f.write('</body></html>')

    logging.info(f"Combined HTML chat history saved to {os.path.abspath(filepath)}")

async def archive_channels(channels=None, hours_history=None, output_dir=None, 
                          media_folder=None, output_as_text=True):
    """
    Main function to archive messages from multiple Telegram channels.
    
    Args:
        channels (list): List of channel usernames to archive
        hours_history (int): Number of hours of history to fetch
        output_dir (str): Directory to save output files
        media_folder (str): Directory to save media files
        output_as_text (bool): Whether to output as text (True) or HTML (False)
    
    Returns:
        dict: Summary statistics including message counts and unique senders
    """
    # Use defaults if not provided
    if channels is None:
        channels = DEFAULT_CHANNELS
    if hours_history is None:
        hours_history = DEFAULT_HOURS_HISTORY
    if output_dir is None:
        output_dir = DEFAULT_OUTPUT_DIR
    if media_folder is None:
        media_folder = DEFAULT_MEDIA_FOLDER
    
    # Ensure directories exist
    ensure_directories_exist(output_dir, media_folder)
    
    # Output file paths
    output_text_file = os.path.join(output_dir, 'combined_channel_history.txt')
    output_html_file = os.path.join(output_dir, 'combined_channel_history.html')
    
    logging.info(f"Starting archive process for channels: {channels}")
    logging.info(f"Fetching last {hours_history} hours of messages")
    
    # Start the Telegram client
    session_file = os.getenv("TELEGRAM_SESSION_FILE", "faq_archiver")
    if os.path.exists(f"{session_file}.session"):
        await client.start(phone=phone_number)
    else:
        logger.error(
            "No Telethon session file found. "
            "Customer analysis requires a pre-generated "
            "session. Run faq_archiver.py interactively "
            "once to create the session, then mount "
            "the .session file into the container."
        )
        return {"total_messages": 0, "channels_processed": []}
    
    # Collect all messages from all channels
    all_messages = []
    channel_stats = {}
    
    for channel in channels:
        try:
            messages = await get_messages_from_channel(channel, hours_history, media_folder)
            all_messages.extend(messages)
            channel_stats[channel] = len(messages)
            logging.info(f"Channel {channel}: {len(messages)} messages")
        except Exception as e:
            logging.error(f"Error fetching messages from {channel}: {e}")
            channel_stats[channel] = 0
    
    # Sort all messages in chronological order (oldest to newest)
    all_messages.sort(key=lambda x: x.date)
    
    # Generate output file
    if output_as_text:
        await write_combined_text_history(all_messages, output_text_file, channels, hours_history)
    else:
        await write_combined_html_history(all_messages, output_html_file, channels, hours_history, media_folder)
    
    # Count unique senders
    unique_senders = set()
    for msg in all_messages:
        sender = await msg.get_sender()
        if sender:
            unique_senders.add(sender.id)
    
    # Return summary statistics
    return {
        "total_messages": len(all_messages),
        "unique_senders": len(unique_senders),
        "channel_stats": channel_stats,
        "channels_processed": list(channel_stats.keys())
    }
