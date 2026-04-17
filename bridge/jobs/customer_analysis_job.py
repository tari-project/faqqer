#!/usr/bin/env python3
"""
Customer Support Analysis Job
Analyzes recent chat messages for customer service issues and posts summaries.
"""

import asyncio
import json
import logging
import os
import traceback
from datetime import datetime

from openai import AsyncOpenAI, OpenAIError

from faq_archiver import archive_channels

logger = logging.getLogger(__name__)

CUSTOMER_ANALYSIS_CRON_DEFAULT = "0 */3 * * *"

# Analysis settings
ANALYSIS_MODEL = "gpt-4o"
ANALYSIS_TEMPERATURE = 0.3
ANALYSIS_TIMEOUT = 120
MAX_MESSAGE_LENGTH = 4000
MAX_EXAMPLE_LENGTH = 200  # Increased from 80 to 200 for longer quotes
MAX_TOKENS_PER_REQUEST = 25000  # Leave room for response tokens (30k limit - 5k buffer)
CHARS_PER_TOKEN_ESTIMATE = 4  # Rough estimate: 1 token ≈ 4 characters


def _load_analysis_channels() -> list[str]:
    raw = os.getenv("ANALYSIS_CHANNELS", "tariproject")
    channels = [c.strip() for c in raw.split(",") if c.strip()]
    return channels or ["tariproject"]


def _load_analysis_hours() -> int:
    raw = os.getenv("ANALYSIS_HOURS", "3").strip()
    try:
        hours = int(raw)
        return hours if hours > 0 else 3
    except ValueError:
        return 3


def _load_customer_service_group_id() -> int | None:
    raw = os.getenv("CUSTOMER_SERVICE_GROUP_ID", "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid CUSTOMER_SERVICE_GROUP_ID=%r", raw)
        return None


# Customer service analysis prompt
ANALYSIS_PROMPT = """
You are a customer service analyst for a cryptocurrency/blockchain project. Analyze the provided chat messages and categorize customer service issues.

IMPORTANT: 
- Translate any non-English text to English before analysis
- Present all results in English only
- Focus on actual customer problems/issues, not general questions

Look for these specific categories and any new ones you identify:

1. **Bridge reliability** - Issues with blockchain bridges, cross-chain transactions
2. **Network fragmentation** - Network connectivity, node communication issues  
3. **Node setup and sync issues** - Problems setting up or syncing blockchain nodes
4. **Wallet and swap fixes** - Wallet functionality, transaction swaps
5. **Mobile wallet, sync'ing, backup** - Mobile app wallet issues, syncing, backups
6. **Fork or Orphan Chain Issues** - Mentions of forks, orphan chains, users stuck on wrong chain
7. **Setup & Installation Problems** - Installing, updating, running software including:
   - Being stuck at installation steps
   - Missing DLLs or components
   - Software failing to launch or crashing
8. **Mining Rewards Too Low** - Complaints about mining rewards:
   - Discrepancies in estimated vs actual mining output
   - Questions about why mining returns dropped
9. **Universe Wallet & Balance Issues** - Problems with:
   - Incorrect balances
   - Missing funds
   - Balance discrepancies between devices/transactions
10. **Memory Leak Issues** - Reports of:
    - High RAM usage
    - Memory leaks
    - System running out of memory
11. **GPU Not Working** - Mentions of:
    - GPUs not being recognized
    - GPUs not turning on
    - Hash rates lower than expected
12. **Mobile App Issues** - Mobile wallet problems:
    - Syncing issues
    - Wallet balance not updating
    - Transactions failing to appear
    - Problems with wallet backups
13. **Anti-Virus, Firewalls, VPNs** - Issues with security software:
    - Anti-virus warnings/false positives
    - Firewalls blocking connections
    - VPN-related connection problems

For each category found, provide:
- The issue category name
- Total number of unique people mentioning it
- A detailed representative example of the issue (actual message text if possible, translated to English - include more context and detail, not just brief quotes)

IMPORTANT: 
- Return the TOP 10 most frequent customer service issues found in the messages
- If fewer than 10 different issues exist, return all issues found
- Prioritize issues by frequency (number of people mentioning them)
- Provide longer, more detailed examples that show the full context of the customer's problem
- Respond ONLY with valid JSON format. Do not include any text before or after the JSON. Do not wrap in code blocks or markdown.

Respond in JSON format with this exact structure:
{
  "analysis_summary": "Brief overview of main issues found",
  "total_issues_found": number,
  "categories": [
    {
      "category": "Issue Category Name",
      "count": number_of_people,
      "representative_example": "Example message in English"
    }
  ]
}
"""


def truncate_chat_content(chat_content, max_tokens=MAX_TOKENS_PER_REQUEST):
    """
    Truncate chat content to fit within token limits while preserving recent messages.
    Uses character count as proxy for token count (rough estimate: 1 token ≈ 4 chars)
    """
    max_chars = max_tokens * CHARS_PER_TOKEN_ESTIMATE

    if len(chat_content) <= max_chars:
        return chat_content

    logger.warning(
        "Chat content too large (%s chars, ~%s tokens). Truncating to recent messages...",
        len(chat_content),
        len(chat_content) // CHARS_PER_TOKEN_ESTIMATE,
    )

    # Split into lines (messages)
    lines = chat_content.split("\n")

    # Keep the most recent messages that fit within the limit
    truncated_lines = []
    current_length = 0

    # Add lines from the end (most recent) until we hit the limit
    for line in reversed(lines):
        line_length = len(line) + 1  # +1 for newline
        if current_length + line_length > max_chars:
            break
        truncated_lines.append(line)
        current_length += line_length

    # Reverse back to chronological order
    truncated_lines.reverse()

    truncated_content = "\n".join(truncated_lines)

    # Add header explaining truncation
    header = f"[TRUNCATED: Showing most recent {len(truncated_lines)} messages out of {len(lines)} total messages]\n\n"
    final_content = header + truncated_content

    logger.info(
        "Truncated content: %s -> %s messages, %s -> %s chars",
        len(lines),
        len(truncated_lines),
        len(chat_content),
        len(final_content),
    )

    return final_content


async def query_openai_analysis(chat_content, custom_question=None):
    """Query OpenAI for customer service analysis

    Args:
        chat_content: The chat messages to analyze
        custom_question: Optional custom question that becomes the dominant analysis prompt
    """
    try:
        # Truncate content if it's too large
        truncated_content = truncate_chat_content(chat_content)

        client = AsyncOpenAI()

        # Use custom question if provided, otherwise use default analysis prompt
        if custom_question:
            # Create a custom prompt that focuses ONLY on the specific question
            analysis_prompt = f"""
You are a customer service analyst for a cryptocurrency/blockchain project. Your task is to analyze chat messages EXCLUSIVELY for issues related to this specific topic:

**EXCLUSIVE FOCUS: {custom_question}**

CRITICAL INSTRUCTIONS:
- IGNORE all other customer service issues that are not directly related to "{custom_question}"
- ONLY identify and categorize messages that relate to the specified topic
- If no messages relate to the topic, return an empty categories array
- Translate any non-English text to English before analysis
- Present all results in English only

ANALYSIS SCOPE:
- Search for messages that mention, discuss, or report problems related to "{custom_question}"
- Look for variations, synonyms, and related terms
- Include both direct mentions and indirect references to the topic
- Focus on actual problems, issues, complaints, or questions about "{custom_question}"

For ONLY the issues related to "{custom_question}", provide:
- A specific category name that relates to the focused topic
- Total number of unique people mentioning issues related to this topic
- A detailed representative example from the actual messages (translated to English if needed - include more context and detail, not just brief quotes)

IMPORTANT:
- Return the TOP 10 most frequent issues related to "{custom_question}" found in the messages
- If fewer than 10 different related issues exist, return all related issues found
- Prioritize issues by frequency (number of people mentioning them)
- Provide longer, more detailed examples that show the full context of the customer's problem
- DO NOT include general customer service issues unless they directly relate to "{custom_question}"

IMPORTANT: Respond ONLY with valid JSON format. Do not include any text before or after the JSON. Do not wrap in code blocks or markdown.

Respond in JSON format with this exact structure:
{{
  "analysis_summary": "Summary of issues found specifically related to '{custom_question}' - if none found, state that clearly",
  "total_issues_found": number,
  "categories": [
    {{
      "category": "Specific issue category related to {custom_question}",
      "count": number_of_people,
      "representative_example": "Example message in English"
    }}
  ]
}}

If no issues related to "{custom_question}" are found, respond with:
{{
  "analysis_summary": "No issues related to '{custom_question}' were found in the analyzed messages",
  "total_issues_found": 0,
  "categories": []
}}
"""
            full_prompt = analysis_prompt + "\n\n" + truncated_content
            logger.info("Using custom analysis question (exclusive focus): %s", custom_question)
        else:
            full_prompt = ANALYSIS_PROMPT + "\n\n" + truncated_content

        # Estimate total tokens for logging
        estimated_tokens = len(full_prompt) // CHARS_PER_TOKEN_ESTIMATE
        logger.info("Sending analysis request: ~%s tokens (%s chars)", estimated_tokens, len(full_prompt))

        response = await client.chat.completions.create(
            model=ANALYSIS_MODEL,
            temperature=ANALYSIS_TEMPERATURE,
            response_format={"type": "json_object"},  # Force JSON response
            messages=[
                {"role": "user", "content": full_prompt},
            ],
            timeout=ANALYSIS_TIMEOUT,
        )

        result = response.choices[0].message.content
        logger.info("OpenAI analysis response received: %s characters", len(result))
        logger.info("Raw OpenAI response: %s...", result[:500])
        return result

    except OpenAIError as e:
        error_info = {
            "message": str(e),
            "type": type(e).__name__,
            "traceback": traceback.format_exc(),
        }
        logger.error("OpenAI analysis error: %s", error_info)
        return None


async def send_message_to_group(telegram_bot, message, target_group_id=None):
    """Send message to specified group or the configured default group"""
    default_group_id = _load_customer_service_group_id()
    group_id = target_group_id if target_group_id is not None else default_group_id

    if not group_id:
        logger.error("No CUSTOMER_SERVICE_GROUP_ID configured and no target_group_id provided")
        return False

    try:
        await telegram_bot.send_message(chat_id=group_id, text=message)
        logger.info("Posted customer service analysis to chat ID %s", group_id)
        return True
    except Exception as e:
        logger.error("Error posting analysis to chat ID %s: %s", group_id, e)
        return False


def format_telegram_table(analysis_data, analysis_hours, custom_question=None):
    """Format analysis results for Telegram (using clean text instead of tables)"""
    try:
        # First try to parse as direct JSON
        try:
            data = json.loads(analysis_data)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code blocks
            import re

            json_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", analysis_data, re.DOTALL)
            if json_match:
                logger.info("Found JSON in markdown code block, extracting...")
                data = json.loads(json_match.group(1))
            else:
                # Try to find JSON-like content without code blocks
                json_match = re.search(r"(\{.*\})", analysis_data, re.DOTALL)
                if json_match:
                    logger.info("Found JSON-like content, attempting to parse...")
                    data = json.loads(json_match.group(1))
                else:
                    raise json.JSONDecodeError("No JSON content found", analysis_data, 0)

        channels = _load_analysis_channels()

        # Check if no significant issues found
        if not data.get("categories") or len(data["categories"]) == 0:
            title = "Customer Service Analysis"
            no_issues_message = f"No major customer service issues detected in the last {analysis_hours} hours."

            if custom_question:
                title = f"Custom Analysis: {custom_question}"
                no_issues_message = (
                    f"No issues related to '{custom_question}' were found in the last {analysis_hours} hours."
                )

            return f"""
🔍 **{title} - {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}**

📊 **Summary:** {data.get('analysis_summary', 'No significant customer service issues found in the analyzed period.')}

✅ {no_issues_message}
"""

        # Build the clean formatted message
        title = "Customer Service Analysis"
        focus_line = ""
        issues_header = "**Issue Breakdown:**"

        if custom_question:
            title = f"Custom Analysis: {custom_question}"
            focus_line = f"\n🎯 **Exclusive Focus:** Only showing issues related to '{custom_question}'"
            issues_header = f"**Issues Related to '{custom_question}':**"

        message = f"""
🔍 **{title} - {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}**{focus_line}

📊 **Summary:** {data.get('analysis_summary', 'Analysis completed')}

📈 **Total Issues Found:** {data.get('total_issues_found', len(data['categories']))}

{issues_header}
"""

        for i, category in enumerate(data["categories"], 1):
            cat_name = category.get("category", "Unknown")
            count = category.get("count", 0)
            example = category.get("representative_example", "No example provided")

            # Truncate long examples
            if len(example) > MAX_EXAMPLE_LENGTH:
                example = example[: MAX_EXAMPLE_LENGTH - 3] + "..."

            message += f'\n{i}. **{cat_name}** ({count} people)\n   └ _"{example}"_\n'

        message += f"\n📅 **Analysis Period:** Last {analysis_hours} hours"
        message += f"\n🔗 **Channels:** {', '.join(channels)}"

        return message

    except json.JSONDecodeError as e:
        logger.error("Error parsing analysis JSON: %s", e)
        logger.error("Raw analysis data (first 1000 chars): %s", analysis_data[:1000])
        return f"""
🔍 **Customer Service Analysis - {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}**

❌ Error processing analysis results. Raw response was received but could not be parsed.

**Debug Info:** JSON decode error at position {e.pos if hasattr(e, 'pos') else 'unknown'}
"""
    except Exception as e:
        logger.error("Error formatting analysis results: %s", e)
        return f"""
🔍 **Customer Service Analysis - {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}**

❌ Error formatting analysis results: {str(e)}
"""


async def run_customer_service_analysis(telegram_bot, target_group_id=None, hours=None, custom_question=None):
    """Run the customer service analysis and post results

    Args:
        telegram_bot: The python-telegram-bot Bot instance
        target_group_id: Optional specific group ID to post to. If None, uses CUSTOMER_SERVICE_GROUP_ID
        hours: Optional hours to analyze. If None, uses ANALYSIS_HOURS env var (default 3)
        custom_question: Optional custom question that becomes the dominant analysis prompt
    """
    analysis_hours = hours if hours is not None else _load_analysis_hours()
    channels = _load_analysis_channels()

    try:
        # Check if phone number is available for user authentication
        phone_number = os.getenv("TELEGRAM_PHONE_NUMBER")
        if not phone_number:
            logger.warning("TELEGRAM_PHONE_NUMBER not configured - customer analysis requires user account access")
            no_auth_msg = f"""
🔍 **Customer Service Analysis - {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}**

⚠️ **Analysis Unavailable**
Customer service analysis requires a Telegram user account to read channel history.
Bot accounts cannot access historical messages from channels.

**To enable this feature:**
• Configure TELEGRAM_PHONE_NUMBER environment variable
• Ensure the user account has access to the analyzed channels

**Current Configuration:**
• Analysis would cover: {', '.join(channels)}
• Time period: Last {analysis_hours} hours
"""
            await send_message_to_group(telegram_bot, no_auth_msg, target_group_id)
            return

        logger.info("Starting customer service analysis for last %s hours...", analysis_hours)
        logger.info("Fetching messages from channels: %s", channels)

        stats = await archive_channels(
            channels=channels,
            hours_history=analysis_hours,
            output_dir="temp_analysis",
            output_as_text=True,
        )

        if stats["total_messages"] == 0:
            logger.info("No messages found for analysis")
            no_messages_msg = f"""
🔍 **Customer Service Analysis - {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}**

📊 No messages found in the last {analysis_hours} hours to analyze.
"""
            await send_message_to_group(telegram_bot, no_messages_msg, target_group_id)
            return

        logger.info(
            "Analyzing %s messages from %s channels",
            stats["total_messages"],
            len(stats["channels_processed"]),
        )

        # Read the archived messages for analysis
        try:
            with open("temp_analysis/combined_channel_history.txt", "r", encoding="utf-8") as f:
                chat_content = f.read()
        except FileNotFoundError:
            logger.error("Analysis archive file not found")
            return

        # Analyze with OpenAI
        analysis_result = await query_openai_analysis(chat_content, custom_question)
        if not analysis_result:
            logger.error("Failed to get analysis from OpenAI")
            error_msg = f"""
🔍 **Customer Service Analysis - {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}**

❌ Analysis failed due to AI service error. Please try again later.
"""
            await send_message_to_group(telegram_bot, error_msg, target_group_id)
            return

        formatted_message = format_telegram_table(analysis_result, analysis_hours, custom_question)

        # Split message if it's too long (Telegram limit ~4096 characters)
        if len(formatted_message) > MAX_MESSAGE_LENGTH:
            parts = [
                formatted_message[i : i + MAX_MESSAGE_LENGTH]
                for i in range(0, len(formatted_message), MAX_MESSAGE_LENGTH)
            ]
            for i, part in enumerate(parts):
                if i == 0:
                    await send_message_to_group(telegram_bot, part, target_group_id)
                else:
                    continuation_msg = f"**(continued...)**\n{part}"
                    await send_message_to_group(telegram_bot, continuation_msg, target_group_id)
                await asyncio.sleep(1)  # Rate limiting
        else:
            await send_message_to_group(telegram_bot, formatted_message, target_group_id)

        logger.info("Customer service analysis completed and posted")

    except Exception as e:
        logger.error("Error in customer service analysis: %s", e)
        logger.error(traceback.format_exc())

        # Send error notification
        try:
            error_msg = f"""
🔍 **Customer Service Analysis - {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}**

❌ Analysis failed with error: {str(e)}
"""
            await send_message_to_group(telegram_bot, error_msg, target_group_id)
        except Exception:
            pass  # Don't fail if we can't send error message


async def manual_analysis_trigger(telegram_bot, target_group_id=None, hours=None, custom_question=None):
    """Manually trigger analysis for bot commands"""
    await run_customer_service_analysis(telegram_bot, target_group_id, hours, custom_question)
