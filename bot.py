import logging
import os
from functools import wraps
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

# Enable logging for the bot
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Configuration ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", None)
if not TELEGRAM_BOT_TOKEN:
    logger.critical("Telegram Bot Token is not set. Please set TELEGRAM_BOT_TOKEN environment variable.")
    exit(1)

# IMPORTANT: Set your Telegram User ID(s) here for admin commands
ADMIN_CHAT_IDS = [6256742423]  # Replace with your actual Telegram User ID(s)

# Twilio client credentials (temporary storage per user)
user_twilio_credentials = {}

# Callback Data Prefixes
BUY_CALLBACK_PREFIX = "buy_"
RELEASE_CALLBACK_PREFIX = "release_"
CHECKSMS_CALLBACK_PREFIX = "sms_"
MAIN_MENU_CALLBACK_PREFIX = "menu_"

# --- Twilio Helper Functions ---
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

# --- Command Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    welcome_message = (
        f"👋 Hello *{user.first_name}*!\n\n"
        "I'm your Twilio Phone Number Management Bot. 🤖\n\n"
        "Please ensure your Twilio credentials are set using `/configure`.\n"
        "Use the commands below or type /help for more options."
    )
    keyboard = [
        [InlineKeyboardButton("🔍 Search Guide", callback_data=f"{MAIN_MENU_CALLBACK_PREFIX}search_guide")],
        [InlineKeyboardButton("📞 List My Numbers", callback_data=f"{MAIN_MENU_CALLBACK_PREFIX}my_numbers_action")],
        [InlineKeyboardButton("⚙️ Configure Guide", callback_data=f"{MAIN_MENU_CALLBACK_PREFIX}configure_guide")],
        [InlineKeyboardButton("❓ Full Help (/help)", callback_data=f"{MAIN_MENU_CALLBACK_PREFIX}help_overview")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = (
        "📖 *Available Commands & Features:*\n\n"
        "`/start` - Welcome message & main menu.\n"
        "`/help` - Show this help message.\n"
        "`/configure <SID> <TOKEN>` - Set your Twilio credentials.\n"
        "`/search_numbers <country> [area_code] [pattern] [zip]` - Search available numbers.\n"
        "`/buy_number <+phonenumber>` - Buy a number.\n"
        "`/my_numbers` - List your owned Twilio numbers.\n"
        "`/release_number <+phonenumber>` - Release a number.\n"
        "`/check_sms <+phonenumber> [limit]` - Check recent SMS.\n"
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
            "⚠️ *Incorrect Usage*\n\nPlease provide both Account SID and Auth Token.\nUsage: `/configure <ACCOUNT_SID> <AUTH_TOKEN>`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    account_sid, auth_token = args[0], args[1]
    if not account_sid.startswith("AC") or len(account_sid) != 34:
        await update.message.reply_text(
            "⚠️ *Invalid Account SID Format*\n\nYour Account SID should start with `AC` and be 34 characters long.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    user_twilio_credentials[chat_id] = {"sid": account_sid, "token": auth_token}
    client = get_twilio_client(chat_id) 
    if client:
        await update.message.reply_text("✅ Twilio credentials successfully configured!", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(
            "❌ *Authentication Failed*\n\nPlease double-check your credentials and try again.",
            parse_mode=ParseMode.MARKDOWN
        )

# Helper function to handle search arguments and provide feedback
def _normalize_search_arg(arg_val: str | None) -> str | None:
    """Normalize 'none' or '_' to None for search arguments."""
    if arg_val and arg_val.lower() in ["none", "_", "-"]:
        return None
    return arg_val

# --- Main Bot Setup ---
def main() -> None:
    if TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        logger.critical("CRITICAL: TELEGRAM_BOT_TOKEN is not set. Please set it in the script or as an environment variable.")
        return
    if ADMIN_CHAT_IDS == [123456789] or not ADMIN_CHAT_IDS: 
        logger.warning("WARNING: ADMIN_CHAT_IDS is not set or is using the default placeholder.")

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Command Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("configure", configure_twilio))

    # Add other handlers as needed...
    
    logger.info("Bot is starting...")
    application.run_polling()

if __name__ == "__main__":
    main()
