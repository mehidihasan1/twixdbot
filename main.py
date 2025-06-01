#!/usr/bin/env python
# pylint: disable=unused-argument, wrong-import-position
# This program is dedicated to the public domain under the CC0 license.

"""
A Telegram bot to manage Twilio phone numbers with interactive buttons.

Functionalities:
- User provides Twilio Account SID and Auth Token for setup.
- Search for available phone numbers by country, optionally by area code, pattern, or zip code (with 'Buy' buttons).
- Buy phone numbers.
- List owned phone numbers (with 'Release' and 'Check SMS' buttons).
- Release phone numbers.
- Check recent SMS messages for an owned number.
- Display developer/owner information via /ownerinfo.
- Basic admin command (/admin_stats) for simple statistics (admin-only).

Usage:
1. Set your TELEGRAM_BOT_TOKEN environment variable or replace the placeholder.
2. Set your ADMIN_CHAT_IDS in the script.
3. Customize OWNER_DETAILS_TEXT in the script.
4. Run the script.
5. Interact with the bot on Telegram, starting with /start.

Commands:
/start - Welcome message and main menu.
/help - Show available commands.
/configure <ACCOUNT_SID> <AUTH_TOKEN> - Set your Twilio credentials.
/search_numbers <country_code> [area_code_or_none] [pattern_or_none] [zip_code_or_none] - Search for available local numbers.
/buy_number <phone_number_to_buy> - Buy an available phone number.
/my_numbers - List your currently owned Twilio numbers.
/release_number <phone_number_to_release> - Release an owned Twilio number.
/check_sms <your_twilio_number> [limit] - Check recent SMS.
/ownerinfo - Display information about the bot owner/developer.
/admin_stats - (Admin Only) Display basic bot statistics.
"""

import logging
import os
from functools import wraps

# Corrected import for ParseMode for newer python-telegram-bot versions
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode 

from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Configuration ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "7834336817:AAH4kMBdCvTEUjHIWGq5NBUR9MCCg8SjGMI")

# IMPORTANT: Set your Telegram User ID(s) here for admin commands
ADMIN_CHAT_IDS = [123456789]  # Replace 123456789 with your actual Telegram user ID(s)

# IMPORTANT: Customize the owner/developer details
OWNER_DETAILS_TEXT = (
    "**Bot Name:** @twilloxd_bot\n\n"
    "**Owner/Developer:**\n"
    "👤 Name: Mehidi Hasan\n"
    "📧 Username: @mehidih0003\n\n"
    "**Contact Information:**\n"
    "✈️ Telegram: @mehidixd_bot\n"
    "✉️ Email: mehidiha94@gmail.com\n"
    "📢 Support Channel/Group: t.me/mytestks"
)

# In-memory storage for user Twilio credentials
user_twilio_credentials = {} # {chat_id: {"sid": "AC...", "token": "auth...", "client": TwilioClient}}

# Callback Data Prefixes
BUY_CALLBACK_PREFIX = "buy_"
RELEASE_CALLBACK_PREFIX = "release_"
CHECKSMS_CALLBACK_PREFIX = "sms_"
MAIN_MENU_CALLBACK_PREFIX = "menu_"

# --- Twilio Helper Functions (Internal Logic) ---

def get_twilio_client(chat_id: int) -> Client | None:
    """Retrieves or initializes a Twilio client for the given chat_id."""
    if chat_id in user_twilio_credentials and "client" in user_twilio_credentials[chat_id]:
        try:
            user_twilio_credentials[chat_id]["client"].api.accounts(user_twilio_credentials[chat_id]["sid"]).fetch()
            return user_twilio_credentials[chat_id]["client"]
        except TwilioRestException:
            logger.info(f"Twilio client for chat_id {chat_id} seems invalid, re-initializing.")
            if chat_id in user_twilio_credentials:
                user_twilio_credentials[chat_id].pop("client", None)

    if chat_id in user_twilio_credentials:
        sid = user_twilio_credentials[chat_id].get("sid")
        token = user_twilio_credentials[chat_id].get("token")
        if sid and token:
            try:
                client = Client(sid, token)
                client.api.accounts(sid).fetch() 
                user_twilio_credentials[chat_id]["client"] = client
                return client
            except TwilioRestException as e:
                logger.error(f"Failed to initialize Twilio client for chat_id {chat_id}: {e}")
                if chat_id in user_twilio_credentials:
                    del user_twilio_credentials[chat_id] 
                return None
    return None

async def _internal_search_numbers(client: Client, country_code: str, area_code: str | None, contains_pattern: str | None, zip_code: str | None) -> tuple[str | None, list[any] | None]:
    """Internal logic to search for numbers."""
    search_params = {'limit': 5} 
    if area_code:
        search_params['area_code'] = area_code
    if contains_pattern:
        search_params['contains'] = contains_pattern
    if zip_code:
        search_params['in_postal_code'] = zip_code 
    
    try:
        logger.info(f"Searching Twilio for numbers: Country={country_code}, Params={search_params}")
        available_numbers = client.available_phone_numbers(country_code).local.list(**search_params)
        if not available_numbers:
            return f"😕 No phone numbers found in `{country_code}` matching your criteria:\n" \
                   f"   - Area Code: `{area_code or 'N/A'}`\n" \
                   f"   - Pattern: `{contains_pattern or 'N/A'}`\n" \
                   f"   - Zip Code: `{zip_code or 'N/A'}`", None
        return None, available_numbers
    except TwilioRestException as e:
        logger.error(f"Twilio API error during internal search: {e}")
        return f"❌ Error searching numbers: _{e.details.get('message', str(e)) if e.details else str(e)}_", None
    except Exception as e:
        logger.error(f"Unexpected error during internal search: {e}")
        return "❗ An unexpected error occurred while searching for numbers.", None

async def _internal_buy_number(client: Client, phone_number_to_buy: str) -> str:
    """Internal logic to buy a number."""
    try:
        logger.info(f"Attempting to buy Twilio number: {phone_number_to_buy}")
        purchased_number = client.incoming_phone_numbers.create(phone_number=phone_number_to_buy)
        return (
            f"🎉 Successfully purchased number: *{purchased_number.friendly_name}* (`{purchased_number.phone_number}`)\n"
            f"   SID: `{purchased_number.sid}`"
        )
    except TwilioRestException as e:
        logger.error(f"Twilio API error during internal purchase: {e}")
        error_message = f"❌ Error buying number `{phone_number_to_buy}`: _{e.details.get('message', str(e)) if e.details else str(e)}_"
        if e.code == 21452: 
             error_message += "\n   _This number might not be available, or there could be account restrictions._"
        return error_message
    except Exception as e:
        logger.error(f"Unexpected error during internal purchase: {e}")
        return f"❗ An unexpected error occurred while trying to buy `{phone_number_to_buy}`."

async def _internal_list_my_numbers(client: Client) -> tuple[str | None, list[any] | None]:
    """Internal logic to list owned numbers."""
    try:
        logger.info("Fetching owned Twilio numbers.")
        incoming_numbers = client.incoming_phone_numbers.list(limit=20)
        if not incoming_numbers:
            return "ℹ️ You don't own any Twilio numbers yet.", None
        return None, incoming_numbers
    except TwilioRestException as e:
        logger.error(f"Twilio API error listing numbers: {e}")
        return f"❌ Error listing your numbers: _{e.details.get('message', str(e)) if e.details else str(e)}_", None
    except Exception as e:
        logger.error(f"Unexpected error listing numbers: {e}")
        return "❗ An unexpected error occurred while listing your numbers.", None

async def _internal_release_number(client: Client, phone_number_to_release: str) -> str:
    """Internal logic to release a number."""
    try:
        logger.info(f"Attempting to release Twilio number: {phone_number_to_release}")
        numbers = client.incoming_phone_numbers.list(phone_number=phone_number_to_release, limit=1)
        if not numbers:
            return f"❓ Number `{phone_number_to_release}` not found in your account."
        
        number_sid_to_release = numbers[0].sid
        client.incoming_phone_numbers(number_sid_to_release).delete()
        return f"🗑️ Successfully released number: `{phone_number_to_release}`"
    except TwilioRestException as e:
        logger.error(f"Twilio API error releasing number: {e}")
        return f"❌ Error releasing number `{phone_number_to_release}`: _{e.details.get('message', str(e)) if e.details else str(e)}_", None
    except Exception as e:
        logger.error(f"Unexpected error releasing number: {e}")
        return f"❗ An unexpected error occurred while releasing `{phone_number_to_release}`."

async def _internal_check_sms(client: Client, twilio_number: str, limit: int = 5) -> str:
    """Internal logic to check SMS messages."""
    try:
        logger.info(f"Checking SMS for Twilio number: {twilio_number}, limit: {limit}")
        owned_numbers = client.incoming_phone_numbers.list(phone_number=twilio_number, limit=1)
        if not owned_numbers:
            return f"🤔 You do not seem to own the number `{twilio_number}`, or it's not a Twilio number in your account."

        messages = client.messages.list(to=twilio_number, limit=limit)
        if not messages:
            return f"📪 No recent SMS messages found for `{twilio_number}` (last {limit})."

        response_text = f"💬 Recent SMS for *{twilio_number}* (last {limit}):\n\n"
        for msg in messages:
            direction = "⬅️ From" if msg.direction == "inbound" else "➡️ To" # Should mostly be inbound for 'to' filter
            status_emoji = "✅" if msg.status in ['delivered', 'received', 'sent'] else "⏳" if msg.status in ['queued', 'accepted', 'sending'] else "❌"
            response_text += (
                f"{status_emoji} {direction}: `{msg.from_}`\n"
                f"   🗓️ _Sent: {msg.date_sent.strftime('%Y-%m-%d %H:%M:%S UTC') if msg.date_sent else 'N/A'}_\n"
                f"   📜 Body: {msg.body}\n"
                f"   🆔 SID: `{msg.sid}`\n---\n"
            )
        return response_text
    except TwilioRestException as e:
        logger.error(f"Twilio API error checking SMS: {e}")
        return f"❌ Error checking SMS for `{twilio_number}`: _{e.details.get('message', str(e)) if e.details else str(e)}_", None
    except Exception as e:
        logger.error(f"Unexpected error checking SMS: {e}")
        return f"❗ An unexpected error occurred while checking SMS for `{twilio_number}`."

# --- Decorators ---
def require_twilio_config(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        chat_id = update.effective_chat.id
        client = get_twilio_client(chat_id)
        if not client:
            await update.message.reply_text(
                "🔒 *Twilio Credentials Needed*\n\n"
                "It looks like your Twilio credentials are not set or are invalid. "
                "Please use the /configure command first:\n"
                "`/configure <YOUR_ACCOUNT_SID> <YOUR_AUTH_TOKEN>`",
                parse_mode=ParseMode.MARKDOWN
            )
            return None
        return await func(update, context, *args, **kwargs)
    return wrapper

def admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        chat_id = update.effective_chat.id
        if chat_id not in ADMIN_CHAT_IDS:
            logger.warning(f"Unauthorized access attempt to admin command by chat_id: {chat_id}")
            await update.message.reply_text("⛔ Sorry, this command is for admins only.")
            return None
        return await func(update, context, *args, **kwargs)
    return wrapper

# --- Telegram Command Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    welcome_message = (
        f"👋 Hello *{user.first_name}*!\n\n"
        "I'm your Twilio Phone Number Management Bot. 🤖\n\n"
        "Use the buttons below or type commands directly.\n"
        "First, ensure your Twilio credentials are set using /configure (see guide below if needed)."
    )
    keyboard = [
        [InlineKeyboardButton("🔍 Search Guide", callback_data=f"{MAIN_MENU_CALLBACK_PREFIX}search_guide")],
        [InlineKeyboardButton("📞 List My Numbers", callback_data=f"{MAIN_MENU_CALLBACK_PREFIX}my_numbers_action")],
        [InlineKeyboardButton("⚙️ Configure Guide", callback_data=f"{MAIN_MENU_CALLBACK_PREFIX}configure_guide")],
        [InlineKeyboardButton("❓ Full Help (/help)", callback_data=f"{MAIN_MENU_CALLBACK_PREFIX}help_overview")],
        [InlineKeyboardButton("ℹ️ Owner Info", callback_data=f"{MAIN_MENU_CALLBACK_PREFIX}owner_info")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = (
        "📖 *Available Commands & Features:*\n\n"
        "`/start` - Welcome message & main menu.\n"
        "`/help` - Show this help message.\n"
        "`/configure <SID> <TOKEN>` - Set your Twilio credentials.\n"
        "    _Example: `/configure ACxxxx your_token_here`_\n"
        "`/search_numbers <country> [area_code] [pattern] [zip]` - Search numbers.\n"
        "    _Country (e.g., US, GB, CA). Use 'none' or '_' to skip optional parts._\n"
        "    _Example: `/search_numbers US 415 SHOP 94107`_\n"
        "    _Example: `/search_numbers US none none 94107`_\n"
        "`/buy_number <+phonenumber>` - Buy an available number.\n"
        "    _Example: `/buy_number +1234567890`_\n"
        "`/my_numbers` - List your owned Twilio numbers.\n"
        "`/release_number <+phonenumber>` - Release an owned number.\n"
        "    _Example: `/release_number +1234567890`_\n"
        "`/check_sms <+phonenumber> [limit]` - Check recent SMS.\n"
        "    _Example: `/check_sms +1234567890 5`_\n"
        "`/ownerinfo` - Display bot owner/developer info.\n"
    )
    if update.effective_chat.id in ADMIN_CHAT_IDS:
        help_text += "`/admin_stats` - (Admin Only) Basic bot stats.\n"
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

async def configure_twilio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    args = context.args
    if len(args) != 2:
        await update.message.reply_text(
            "⚠️ *Incorrect Usage*\n\n"
            "Please provide both Account SID and Auth Token.\n"
            "Usage: `/configure <ACCOUNT_SID> <AUTH_TOKEN>`\n"
            "Example: `/configure ACxxxxxxxxxxxxxxx your_auth_token_here`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    account_sid, auth_token = args[0], args[1]
    if not account_sid.startswith("AC") or len(account_sid) != 34:
        await update.message.reply_text(
            "⚠️ *Invalid Account SID Format*\n\n"
            "Your Account SID should start with `AC` and be 34 characters long.",
            parse_mode=ParseMode.MARKDOWN
            )
        return

    user_twilio_credentials[chat_id] = {"sid": account_sid, "token": auth_token}
    client = get_twilio_client(chat_id) 
    if client:
        await update.message.reply_text("✅ Twilio credentials configured and validated successfully! You're all set. ✨", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(
            "❌ *Authentication Failed*\n\n"
            "Failed to validate your Twilio credentials. Please double-check your Account SID and Auth Token and try again.",
            parse_mode=ParseMode.MARKDOWN
        )

def _normalize_search_arg(arg_val: str | None) -> str | None:
    """Helper to normalize 'none' or '_' to None for search arguments."""
    if arg_val and arg_val.lower() in ["none", "_", "-"]:
        return None
    return arg_val

@require_twilio_config
async def search_available_numbers_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    client = get_twilio_client(chat_id) 

    args = context.args
    if not args or len(args) < 1:
        await update.message.reply_text(
            "❓*How to Search for Numbers*\n\n"
            "Usage: `/search_numbers <country_code> [area_code_or_none] [pattern_or_none] [zip_code_or_none]`\n"
            "Example: `/search_numbers US 415 SHOP 94107`\n"
            "_Type /help for more examples and details._",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    country_code = args[0].upper()
    area_code_str = args[1] if len(args) > 1 else None
    pattern_str = args[2] if len(args) > 2 else None
    zip_code_str = args[3] if len(args) > 3 else None

    area_code = _normalize_search_arg(area_code_str)
    contains_pattern = _normalize_search_arg(pattern_str)
    zip_code_arg = _normalize_search_arg(zip_code_str)
    
    search_criteria_parts = [f"*Country:* `{country_code}`"]
    if area_code: search_criteria_parts.append(f"*Area Code:* `{area_code}`")
    if contains_pattern: search_criteria_parts.append(f"*Pattern:* `{contains_pattern}`")
    if zip_code_arg: search_criteria_parts.append(f"*Zip Code:* `{zip_code_arg}`")
    
    await update.message.reply_text(f"🔍 Searching for local numbers with criteria:\n {', '.join(search_criteria_parts)}...", parse_mode=ParseMode.MARKDOWN)
    error_msg, numbers = await _internal_search_numbers(client, country_code, area_code, contains_pattern, zip_code_arg)

    if error_msg:
        await update.message.reply_text(error_msg, parse_mode=ParseMode.MARKDOWN)
        return
    
    if not numbers: 
        await update.message.reply_text("😕 No numbers found matching your criteria.", parse_mode=ParseMode.MARKDOWN) 
        return

    response_text = "✅ *Found Available Numbers:*\n\n"
    keyboard_rows = []
    for number_obj in numbers:
        phone_num_str = str(number_obj.phone_number)
        response_text += f"📞 *{number_obj.friendly_name}* (`{phone_num_str}`)\n" \
                         f"   _Region:_ {number_obj.region}, _Locality:_ {number_obj.locality}\n---\n"
        keyboard_rows.append([
            InlineKeyboardButton(f"💰 Buy {number_obj.friendly_name}", callback_data=f"{BUY_CALLBACK_PREFIX}{phone_num_str}")
        ])
    
    if not keyboard_rows: # Should not happen if numbers is populated
        await update.message.reply_text(response_text + "\n_No numbers to display with buy actions._", parse_mode=ParseMode.MARKDOWN)
        return

    reply_markup = InlineKeyboardMarkup(keyboard_rows)
    await update.message.reply_text(response_text + "\n👇 Select a number to buy:", reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

@require_twilio_config
async def buy_number_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    client = get_twilio_client(chat_id)

    args = context.args
    if not args or len(args) != 1:
        await update.message.reply_text(
            "❓*How to Buy a Number*\n\n"
            "Usage: `/buy_number <phone_number_to_buy>`\n"
            "Example: `/buy_number +1234567890`",
            parse_mode=ParseMode.MARKDOWN
            )
        return
    phone_number_to_buy = args[0]
    if not phone_number_to_buy.startswith("+"):
        await update.message.reply_text(
            "⚠️ *Invalid Phone Number Format*\n\n"
            "The phone number should start with `+` (e.g., `+1234567890`).",
            parse_mode=ParseMode.MARKDOWN
            )
        return

    await update.message.reply_text(f"🛒 Attempting to buy `{phone_number_to_buy}`...", parse_mode=ParseMode.MARKDOWN)
    result_message = await _internal_buy_number(client, phone_number_to_buy)
    await update.message.reply_text(result_message, parse_mode=ParseMode.MARKDOWN)

@require_twilio_config
async def list_my_numbers_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    client = get_twilio_client(chat_id)

    await update.message.reply_text("📋 Fetching your Twilio numbers...", parse_mode=ParseMode.MARKDOWN)
    error_msg, numbers = await _internal_list_my_numbers(client)

    if error_msg:
        await update.message.reply_text(error_msg, parse_mode=ParseMode.MARKDOWN)
        return
    if not numbers: 
        await update.message.reply_text("ℹ️ You don't own any Twilio numbers yet.", parse_mode=ParseMode.MARKDOWN)
        return

    response_text = "🌟 *Your Twilio Numbers:*\n\n"
    keyboard_rows = []
    for number_obj in numbers:
        phone_num_str = str(number_obj.phone_number)
        response_text += f"📞 *{number_obj.friendly_name}* (`{phone_num_str}`)\n" \
                         f"   _SID:_ `{number_obj.sid}`\n---\n"
        buttons = [
            InlineKeyboardButton(f"♻️ Release", callback_data=f"{RELEASE_CALLBACK_PREFIX}{phone_num_str}"),
            InlineKeyboardButton(f"💬 Check SMS", callback_data=f"{CHECKSMS_CALLBACK_PREFIX}{phone_num_str}")
        ]
        keyboard_rows.append(buttons)
    
    if not keyboard_rows: # Should not happen if numbers is populated
        await update.message.reply_text(response_text + "\n_No numbers to display with actions._", parse_mode=ParseMode.MARKDOWN)
        return
        
    reply_markup = InlineKeyboardMarkup(keyboard_rows)
    full_message = response_text + "\n👇 Manage your numbers:"
    if len(full_message) > 4000: 
        await update.message.reply_text(response_text, parse_mode=ParseMode.MARKDOWN)
        await update.message.reply_text("👇 Manage your numbers:", reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(full_message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)


@require_twilio_config
async def release_number_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    client = get_twilio_client(chat_id)
    args = context.args
    if not args or len(args) != 1:
        await update.message.reply_text(
            "❓*How to Release a Number*\n\n"
            "Usage: `/release_number <phone_number_to_release>`\n"
            "Example: `/release_number +1234567890`",
            parse_mode=ParseMode.MARKDOWN
            )
        return
    phone_number_to_release = args[0]
    if not phone_number_to_release.startswith("+"):
        await update.message.reply_text(
            "⚠️ *Invalid Phone Number Format*\n\n"
            "The phone number should start with `+` (e.g., `+1234567890`).",
            parse_mode=ParseMode.MARKDOWN
            )
        return
        
    await update.message.reply_text(f"⏳ Attempting to release `{phone_number_to_release}`...", parse_mode=ParseMode.MARKDOWN)
    result_message = await _internal_release_number(client, phone_number_to_release)
    await update.message.reply_text(result_message, parse_mode=ParseMode.MARKDOWN)

@require_twilio_config
async def check_sms_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    client = get_twilio_client(chat_id)
    args = context.args
    if not args or len(args) < 1:
        await update.message.reply_text(
            "❓*How to Check SMS*\n\n"
            "Usage: `/check_sms <your_twilio_number> [limit]`\n"
            "Example: `/check_sms +1234567890 5`",
            parse_mode=ParseMode.MARKDOWN
            )
        return

    twilio_number = args[0]
    limit = 5
    if len(args) > 1:
        try:
            limit = int(args[1])
            if not (1 <= limit <= 20): 
                await update.message.reply_text("⚠️ Limit must be between 1 and 20.", parse_mode=ParseMode.MARKDOWN)
                return
        except ValueError:
            await update.message.reply_text("⚠️ Invalid limit. It must be a number.", parse_mode=ParseMode.MARKDOWN)
            return
            
    if not twilio_number.startswith("+"):
        await update.message.reply_text(
            "⚠️ *Invalid Phone Number Format*\n\n"
            "The phone number should start with `+` (e.g., `+1234567890`).",
            parse_mode=ParseMode.MARKDOWN
            )
        return

    await update.message.reply_text(f"📨 Fetching last {limit} SMS messages for `{twilio_number}`...", parse_mode=ParseMode.MARKDOWN)
    result_message = await _internal_check_sms(client, twilio_number, limit)
    await update.message.reply_text(result_message, parse_mode=ParseMode.MARKDOWN)

async def owner_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays the owner/developer information."""
    await update.message.reply_text(OWNER_DETAILS_TEXT, parse_mode=ParseMode.MARKDOWN)

@admin_only
async def admin_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """(Admin Only) Displays basic bot statistics."""
    active_configs = len(user_twilio_credentials)
    stats_message = (
        "📊 *Admin Statistics*\n\n"
        f"Active Twilio configurations in this session: *{active_configs}*"
    )
    await update.message.reply_text(stats_message, parse_mode=ParseMode.MARKDOWN)

# --- Callback Query Handler ---
async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer() 

    chat_id = query.message.chat_id
    data = query.data
    client = None 

    actions_requiring_client = [
        BUY_CALLBACK_PREFIX, 
        RELEASE_CALLBACK_PREFIX, 
        CHECKSMS_CALLBACK_PREFIX,
        f"{MAIN_MENU_CALLBACK_PREFIX}my_numbers_action" 
    ]
    
    needs_client = any(data.startswith(prefix) for prefix in actions_requiring_client)

    if needs_client:
        client = get_twilio_client(chat_id)
        if not client:
            await query.edit_message_text(
                text="🔒 *Twilio Credentials Needed*\n\n"
                     "It looks like your Twilio credentials are not set or are invalid. "
                     "Please use the /configure command first:\n"
                     "`/configure <YOUR_ACCOUNT_SID> <YOUR_AUTH_TOKEN>`",
                reply_markup=None,
                parse_mode=ParseMode.MARKDOWN
            )
            return

    if data.startswith(MAIN_MENU_CALLBACK_PREFIX):
        action = data[len(MAIN_MENU_CALLBACK_PREFIX):]
        if action == "search_guide":
            await query.edit_message_text(
                text="*🔍 How to Search for Numbers:*\n\n"
                     "Use the command:\n"
                     "`/search_numbers <country_code> [area_code_or_none] [pattern_or_none] [zip_code_or_none]`\n\n"
                     "*Examples:*\n"
                     "- `/search_numbers US 415 SHOP 94107`\n"
                     "- `/search_numbers US none none 12345` (search by zip only)\n\n"
                     "_Use 'none' or '_' to skip optional parts. Type /help for more details._",
                reply_markup=None,
                parse_mode=ParseMode.MARKDOWN
            )
        elif action == "my_numbers_action":
            await query.edit_message_text("📋 Fetching your Twilio numbers...", reply_markup=None, parse_mode=ParseMode.MARKDOWN)
            error_msg, numbers = await _internal_list_my_numbers(client) 

            if error_msg:
                await query.message.reply_text(error_msg, parse_mode=ParseMode.MARKDOWN) 
                return
            if not numbers:
                 await query.message.reply_text("ℹ️ You don't own any Twilio numbers yet.", parse_mode=ParseMode.MARKDOWN)
                 return

            response_text = "🌟 *Your Twilio Numbers:*\n\n"
            keyboard_rows = []
            for number_obj in numbers:
                phone_num_str = str(number_obj.phone_number)
                response_text += f"📞 *{number_obj.friendly_name}* (`{phone_num_str}`)\n" \
                                 f"   _SID:_ `{number_obj.sid}`\n---\n"
                buttons = [
                    InlineKeyboardButton(f"♻️ Release", callback_data=f"{RELEASE_CALLBACK_PREFIX}{phone_num_str}"),
                    InlineKeyboardButton(f"💬 Check SMS", callback_data=f"{CHECKSMS_CALLBACK_PREFIX}{phone_num_str}")
                ]
                keyboard_rows.append(buttons)
            
            reply_markup = InlineKeyboardMarkup(keyboard_rows)
            await query.message.reply_text(response_text + "\n👇 Manage your numbers:", reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

        elif action == "configure_guide":
            await query.edit_message_text(
                text="⚙️ *How to Configure Twilio Credentials:*\n\n"
                     "Use the command with your Account SID and Auth Token:\n"
                     "`/configure <YOUR_ACCOUNT_SID> <YOUR_AUTH_TOKEN>`\n\n"
                     "_You can find these on your Twilio Console dashboard._",
                reply_markup=None,
                parse_mode=ParseMode.MARKDOWN
            )
        elif action == "help_overview":
            await query.edit_message_text(
                text="ℹ️ For a full list of commands and their usage, please type `/help`.",
                reply_markup=None,
                parse_mode=ParseMode.MARKDOWN
            )
        elif action == "owner_info":
            await query.edit_message_text(OWNER_DETAILS_TEXT, reply_markup=None, parse_mode=ParseMode.MARKDOWN)
    
    elif data.startswith(BUY_CALLBACK_PREFIX):
        phone_number_to_buy = data[len(BUY_CALLBACK_PREFIX):]
        await query.edit_message_text(text=f"🛒 Processing purchase for `{phone_number_to_buy}`...", reply_markup=None, parse_mode=ParseMode.MARKDOWN)
        result_message = await _internal_buy_number(client, phone_number_to_buy) 
        await query.message.reply_text(result_message, parse_mode=ParseMode.MARKDOWN)

    elif data.startswith(RELEASE_CALLBACK_PREFIX):
        phone_number_to_release = data[len(RELEASE_CALLBACK_PREFIX):]
        await query.edit_message_text(text=f"⏳ Processing release for `{phone_number_to_release}`...", reply_markup=None, parse_mode=ParseMode.MARKDOWN)
        result_message = await _internal_release_number(client, phone_number_to_release) 
        await query.message.reply_text(result_message, parse_mode=ParseMode.MARKDOWN)

    elif data.startswith(CHECKSMS_CALLBACK_PREFIX):
        phone_number_for_sms = data[len(CHECKSMS_CALLBACK_PREFIX):]
        default_limit = 5 
        await query.edit_message_text(text=f"📨 Fetching last {default_limit} SMS for `{phone_number_for_sms}`...", reply_markup=None, parse_mode=ParseMode.MARKDOWN)
        result_message = await _internal_check_sms(client, phone_number_for_sms, default_limit) 
        await query.message.reply_text(result_message, parse_mode=ParseMode.MARKDOWN)

# --- Main Bot Setup ---
def main() -> None:
    if TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        logger.critical("CRITICAL: TELEGRAM_BOT_TOKEN is not set. Please set it in the script or as an environment variable.")
        return
    if ADMIN_CHAT_IDS == [123456789] or not ADMIN_CHAT_IDS: 
        logger.warning("WARNING: ADMIN_CHAT_IDS is not set or is using the default placeholder. Admin commands will not be secure. Please update it with your Telegram User ID.")
    if "Mehidi Hasan" not in OWNER_DETAILS_TEXT and "[Your Name/Organization]" in OWNER_DETAILS_TEXT : 
        logger.warning("WARNING: OWNER_DETAILS_TEXT has not been customized with your specific details. Please update it.")


    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Command Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("configure", configure_twilio))
    application.add_handler(CommandHandler("search_numbers", search_available_numbers_command))
    application.add_handler(CommandHandler("buy_number", buy_number_command))
    application.add_handler(CommandHandler("my_numbers", list_my_numbers_command))
    application.add_handler(CommandHandler("release_number", release_number_command))
    application.add_handler(CommandHandler("check_sms", check_sms_command))
    application.add_handler(CommandHandler("ownerinfo", owner_info_command))
    application.add_handler(CommandHandler("admin_stats", admin_stats_command))


    # Callback Query Handler for buttons
    application.add_handler(CallbackQueryHandler(button_callback_handler))
    
    logger.info("Bot is starting with corrected ParseMode import, owner info, and basic admin features...")
    application.run_polling()
    logger.info("Bot has stopped.")

if __name__ == "__main__":
    main()
