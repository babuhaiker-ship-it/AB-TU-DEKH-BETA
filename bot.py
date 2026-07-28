import os
import asyncio
import uuid
import base64
import logging
from datetime import datetime, timedelta, timezone

from hydrogram import Client, filters, StopPropagation
from hydrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, Message, InputMediaVideo, CallbackQuery, WebAppInfo, User as HyUser, Chat as HyChat
)
from hydrogram.handlers import MessageHandler, CallbackQueryHandler
from hydrogram.errors import UserIsBlocked, ChatInvalid, MessageIdInvalid, FloodWait, PeerIdInvalid, RPCError, FileIdInvalid, FileReferenceExpired, ChatAdminRequired
from hydrogram.enums import ChatMemberStatus, ChatType
from pymongo import MongoClient, ASCENDING, DESCENDING, ReturnDocument, UpdateOne # Import UpdateOne for bulk operations
import aiohttp
from aiohttp import ClientTimeout
from collections import defaultdict, deque
import re
import html
import urllib.parse
from shortzy import Shortzy

# --- Mini App / Web Server Imports ---
import uvicorn
from fastapi import FastAPI, Request, HTTPException, Depends, Response
from fastapi.responses import RedirectResponse, JSONResponse


# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Configuration ---
class BotConfig:
    # Essential Variables (No Defaults)
    BOT_TOKEN = os.environ.get('BOT_TOKEN')
    API_ID = os.environ.get('API_ID')
    API_HASH = os.environ.get('API_HASH')
    BOT_USERNAME = os.environ.get('BOT_USERNAME')
    MONGO_URI = os.environ.get('MONGO_URI')
    MONGO_DB_NAME = os.environ.get('MONGO_DB_NAME')

    # Configuration Parameters (With Defaults)
    BUY_BOT_URL = os.environ.get('BUY_BOT_URL', 'https://t.me/nyraapaybot?start')
    OWNER_ID = int(os.environ.get('OWNER_ID', 6612030110))
    TUTORIAL_LINK_2 = os.environ.get('TUTORIAL_LINK_2', 'https://t.me/urlshortenertutorial')
    TOKEN_EXPIRY = int(os.environ.get('TOKEN_EXPIRY', 21600))
    NEW_USER_TOKENS = int(os.environ.get('NEW_USER_TOKENS', 1))
    REFERRAL_BONUS = int(os.environ.get('REFERRAL_BONUS', 1))
    REFRESH_BONUS = int(os.environ.get('REFRESH_BONUS', 1))
    PREMIUM_TRIAL_PRICE_INR = int(os.environ.get('PREMIUM_TRIAL_PRICE_INR', 33))
    PREMIUM_MONTH_PRICE_INR = int(os.environ.get('PREMIUM_MONTH_PRICE_INR', 99))
    FREE_USER_SAVE_LIMIT = int(os.environ.get('FREE_USER_SAVE_LIMIT', 5))
    MENU_EXPIRY_MINUTES = int(os.environ.get('MENU_EXPIRY_MINUTES', 10))
    REFRESH_TOKEN_LINK_EXPIRY_SECONDS = int(os.environ.get('REFRESH_TOKEN_LINK_EXPIRY_SECONDS', 21600))
    NEW_USER_SCROLLS = int(os.environ.get('NEW_USER_SCROLLS', 0))
    DAILY_FREE_SCROLLS = int(os.environ.get('DAILY_FREE_SCROLLS', 0))
    FREE_SCROLL_RESET_HOURS = int(os.environ.get('FREE_SCROLL_RESET_HOURS', 6))
    FREE_BATCH_LIMIT = int(os.environ.get('FREE_BATCH_LIMIT', 0))
    FREE_LIMIT_RESET_HOURS = int(os.environ.get('FREE_LIMIT_RESET_HOURS', 12))
    DAILY_FREE_VIDEOS = int(os.environ.get('DAILY_FREE_VIDEOS', 1))
    FREE_VIDEO_RESET_HOURS = int(os.environ.get('FREE_VIDEO_RESET_HOURS', 24))
    TOKEN_ACCESS_HOURS = float(os.environ.get('TOKEN_ACCESS_HOURS', 6.0))
    VERIFICATION_TOKEN_DURATION_HOURS = float(os.environ.get('VERIFICATION_TOKEN_DURATION_HOURS', 6.0))

    # Upload Configuration Defaults
    UPLOAD_DAILY_MAX = int(os.environ.get('UPLOAD_DAILY_MAX', 100))
    UPLOAD_TEMP_SCROLLS = int(os.environ.get('UPLOAD_TEMP_SCROLLS', 20))
    UPLOAD_TEMP_SCROLLS_EXPIRY_HOURS = int(os.environ.get('UPLOAD_TEMP_SCROLLS_EXPIRY_HOURS', 48))
    UPLOAD_MIN_COUNT = int(os.environ.get('UPLOAD_MIN_COUNT', 1))
    UPLOAD_MAX_PENDING = int(os.environ.get('UPLOAD_MAX_PENDING', 30))

try:
    config = BotConfig()
    # UPDATED: Removed force sub channel checks
    if not all([config.BOT_TOKEN, config.API_ID, config.API_HASH, config.MONGO_URI, config.BOT_USERNAME]):
        raise ValueError("One or more essential configuration variables are not set. Please check all config variables.")

    # Cast essential numeric variables to correct type after checking they exist
    config.API_ID = int(config.API_ID)
except Exception as e:
    raise RuntimeError(f"Failed to load bot configuration: {e}")

# --- Batch Add Constants ---
BATCH_UPLOAD_LIMIT = 20
BATCH_COOLDOWN_SECONDS = 60

# --- MongoDB Setup ---
client = MongoClient(config.MONGO_URI, tz_aware=True)
db = client[config.MONGO_DB_NAME]
users_collection = db['users']
tokens_collection = db['tokens']
media_collection = db['media']
history_collection = db['history']
categories_collection = db['categories']
settings_collection = db['settings']
refresh_tokens_used_collection = db['refresh_tokens_used']
video_batches_collection = db['video_batches'] # New collection for batch videos
ssrb_verifications_collection = db['ssrb_verifications'] # New collection for cross-bot verification
pending_uploads_collection = db['pending_uploads'] # New collection for user video uploads
# NEW: Collections for dynamic channel IDs
force_sub_channels_collection = db['force_sub_channels']
data_channel_collection = db['data_channel']
shortener_logs_collection = db['shortener_logs'] # New collection for token stats




# Create indexes
users_collection.create_index([("user_id", ASCENDING)], unique=True)
tokens_collection.create_index([("user_id", ASCENDING)], unique=True)
media_collection.create_index([("uuid", ASCENDING)], unique=True)
media_collection.create_index([("category", ASCENDING)])
media_collection.create_index([("file_unique_id", ASCENDING)], unique=True)
media_collection.create_index([("category", ASCENDING), ("sequence_number", ASCENDING)])
history_collection.create_index([("user_id", ASCENDING)], unique=True)
categories_collection.create_index([("name", ASCENDING)], unique=True)
refresh_tokens_used_collection.create_index([("ad_code", ASCENDING)], unique=True) # Renamed to "used url link" conceptually
video_batches_collection.create_index([("batch_id", ASCENDING)], unique=True)
ssrb_verifications_collection.create_index([("user_id", ASCENDING)], unique=True)
pending_uploads_collection.create_index([("upload_id", ASCENDING)], unique=True)
pending_uploads_collection.create_index([("user_id", ASCENDING)])
pending_uploads_collection.create_index([("file_unique_id", ASCENDING)])
pending_uploads_collection.create_index([("status", ASCENDING)])
# NEW: Indexes for new collections
force_sub_channels_collection.create_index([("channel_id", ASCENDING)], unique=True)
# FIX: Removed unique=True for _id index as it's redundant and causes an error
data_channel_collection.create_index([("_id", ASCENDING)])


# --- Session Management with MongoDB ---
def get_session_string():
    """Retrieves the session string from the database."""
    session_doc = settings_collection.find_one({'_id': 'hydrogram_session'})
    return session_doc.get('session_string') if session_doc else None

def set_session_string(session_string):
    """Saves the session string to the database."""
    settings_collection.update_one(
        {'_id': 'hydrogram_session'},
        {'$set': {'session_string': session_string}},
        upsert=True
    )
    logger.info("Hydrogram session string has been saved to the database.")

# --- Hydrogram Client Proxy ---
class BotProxy:
    """
    A proxy for the Hydrogram Client that allows registering handlers
    before the actual Client is initialized within the running event loop.
    """
    def __init__(self):
        self._real_bot = None
        self._pending_handlers = []

    def initialize(self, real_bot):
        self._real_bot = real_bot
        logger.info(f"Initializing BotProxy with real client. Registering {len(self._pending_handlers)} pending handlers.")
        for handler, group in self._pending_handlers:
            self._real_bot.add_handler(handler, group)
        self._pending_handlers.clear()

    def on_message(self, filters=None, group=0):
        def decorator(func):
            if self._real_bot:
                self._real_bot.add_handler(MessageHandler(func, filters), group)
            else:
                self._pending_handlers.append((MessageHandler(func, filters), group))
            return func
        return decorator

    def on_callback_query(self, filters=None, group=0):
        def decorator(func):
            if self._real_bot:
                self._real_bot.add_handler(CallbackQueryHandler(func, filters), group)
            else:
                self._pending_handlers.append((CallbackQueryHandler(func, filters), group))
            return func
        return decorator

    def __getattr__(self, name):
        if name == "is_connected":
            return self._real_bot.is_connected if self._real_bot else False
        if self._real_bot is None:
            raise RuntimeError(f"Bot not initialized yet. Accessing '{name}' before startup.")
        return getattr(self._real_bot, name)

bot = BotProxy()

# --- FastAPI App Initialization with Lifespan ---
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    logger.info("FastAPI lifespan starting up...")
    # Initialize real bot here where we have a running event loop
    real_bot = Client(
        name="spicynyraa_session",
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        bot_token=config.BOT_TOKEN,
        session_string=get_session_string(),
        in_memory=True
    )
    bot.initialize(real_bot)

    # Launch the bot background task
    create_tracked_task(run_bot_background())

    yield

    # Shutdown logic
    logger.info("FastAPI lifespan shutting down...")
    # Shutdown logic to delete all active menus
    for user_id, menu_info in list(active_video_message.items()):
        try:
            if bot.is_connected:
                await bot.delete_messages(menu_info['chat_id'], menu_info['message_id'])
                await bot.send_message(
                    menu_info['chat_id'],
                    "⏳ Video Expired!\nTap below to get a new video.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Get Video", callback_data="get_default_video")]])
                )
        except Exception as e:
            logger.error(f"Failed to delete active menu for user {user_id} on shutdown: {e}")

    if bot.is_connected:
        await bot.stop()
    logger.info("Hydrogram client stopped.")

app = FastAPI(lifespan=lifespan)
fastapi_app = app # Alias for environments explicitly seeking 'fastapi_app'


# --- GLOBAL SET FOR TRACKING ASYNC TASKS ---
active_tasks = set()

# --- Admin State Management ---
admin_shortener_setup_state = defaultdict(dict)
admin_delete_video_state = defaultdict(bool)
batch_processing_timers = {}
admin_rename_category_state = defaultdict(dict)
admin_batch_link_state = defaultdict(list) # State for /batchvideoadd
owner_add_admin_state = defaultdict(dict) # State for /addadmin
admin_delete_user_state = defaultdict(dict) # State for /deleteuser
batch_add_state = {} # State for /batchadd
# NEW: Admin states for channel management
admin_fsub_state = defaultdict(dict)
admin_data_channel_state = defaultdict(dict)


# --- Message Tracking and Immediate Deletion ---
active_video_message = {}

# --- User Upload State ---
user_upload_state = defaultdict(dict) # user_id -> {'in_upload_mode': bool, 'session_uploads': int}
REVIEW_CHAT_ID = None
UPLOAD_CONFIG = {
    'daily_max': config.UPLOAD_DAILY_MAX,
    'auto_give_scrolls': True,
    'temp_scrolls_amount': config.UPLOAD_TEMP_SCROLLS,
    'temp_scrolls_expiry_hours': config.UPLOAD_TEMP_SCROLLS_EXPIRY_HOURS,
    'min_upload_count': config.UPLOAD_MIN_COUNT,
    'max_pending': config.UPLOAD_MAX_PENDING,
    'milestones_enabled': False,
    'milestones': {
        "5": 2.0,
        "10": 4.0
    },
    'reward_tokens_hours': 2.0,
    'session_limit_count': 10,
    'session_limit_minutes': 10
}

# --- Navigation Spam Control ---
processing_navigation_lock = set()
user_session_history = {} # user_id -> {'category': str, 'videos': [uuid], 'position': int, 'is_get_video': bool}

# --- Dynamic Admin Management ---
BOT_ADMINS = {config.OWNER_ID} # Initialize with Owner ID from config
# NEW: Global variables for dynamically loaded settings
DATA_CHANNEL_ID = None
FORCE_SUB_CHANNELS = [] # List of {'channel_id': int, 'link': str, 'name': str}
SHORTENER_DISABLED = False

async def load_admins_from_db():
    """Loads admin list from DB and ensures owner is always included."""
    global BOT_ADMINS
    settings_doc = settings_collection.find_one({'_id': 'bot_settings'})
    db_admins = settings_doc.get('admins', []) if settings_doc else []

    # Cast all loaded admin IDs to int to guarantee type safety for comparison
    valid_admins = set()
    for admin_id in db_admins:
        try:
            valid_admins.add(int(admin_id))
        except (ValueError, TypeError):
            logger.warning(f"Ignored invalid admin ID in database configuration: {admin_id}")

    BOT_ADMINS = valid_admins
    BOT_ADMINS.add(config.OWNER_ID) # Ensure owner is always an admin
    logger.info(f"Loaded admins from DB. Current admins: {BOT_ADMINS}")

async def load_data_channel_id():
    """Loads the data channel ID from the database."""
    global DATA_CHANNEL_ID
    data_doc = data_channel_collection.find_one({'_id': 'data_channel'})
    if data_doc:
        DATA_CHANNEL_ID = data_doc.get('channel_id')
        logger.info(f"Loaded data channel ID: {DATA_CHANNEL_ID}")
    else:
        DATA_CHANNEL_ID = None
        logger.warning("No data channel ID found in DB.")

async def load_force_sub_channels():
    """Loads force subscribe channels from the database."""
    global FORCE_SUB_CHANNELS
    FORCE_SUB_CHANNELS = list(force_sub_channels_collection.find({}))
    logger.info(f"Loaded {len(FORCE_SUB_CHANNELS)} force subscribe channels.")

async def load_shortener_setting():
    """Loads the shortener disabled setting from the database."""
    global SHORTENER_DISABLED
    settings_doc = settings_collection.find_one({'_id': 'bot_settings'})
    SHORTENER_DISABLED = settings_doc.get('shortener_disabled', False) if settings_doc else False
    logger.info(f"Loaded shortener setting: {'Disabled' if SHORTENER_DISABLED else 'Enabled'}")

async def load_upload_config():
    """Loads upload configuration and review chat ID from database."""
    global REVIEW_CHAT_ID, UPLOAD_CONFIG
    config_doc = settings_collection.find_one({'_id': 'upload_config'})
    if config_doc:
        UPLOAD_CONFIG.update(config_doc.get('settings', {}))
        REVIEW_CHAT_ID = config_doc.get('review_chat_id')
        logger.info(f"Loaded upload config: {UPLOAD_CONFIG}, Review Chat ID: {REVIEW_CHAT_ID}")
    else:
        logger.info("No upload config found in DB, using defaults.")

def is_admin(user_id: int) -> bool:
    """Checks if the given user ID belongs to an administrator."""
    return user_id in BOT_ADMINS

def is_owner(user_id: int) -> bool:
    """Checks if the user is the bot owner."""
    return user_id == config.OWNER_ID

# MODIFIED: Custom filter for admin commands to allow dynamic admin list
def admin_filter(_, __, message: Message):
    return bool(message.from_user and is_admin(message.from_user.id))

admin_only = filters.create(admin_filter)

def owner_filter(_, __, message: Message):
    return bool(message.from_user and is_owner(message.from_user.id))

owner_only = filters.create(owner_filter)

def non_command_filter(_, __, message: Message):
    return not bool(message.text and message.text.startswith("/"))

non_command = filters.create(non_command_filter)


def create_tracked_task(coro):
    """
    Creates an asyncio task, adds it to the global active_tasks set,
    and removes it when it finishes (successfully or with an exception).
    """
    task = asyncio.create_task(coro)
    active_tasks.add(task)
    task.add_done_callback(active_tasks.discard)
    logger.debug(f"Task {task.get_name()} created and tracked. Total active tasks: {len(active_tasks)}")
    return task

# --- Force Subscribe Check ---
async def check_membership(client: Client, user_id: int) -> bool:
    """
    Checks if the user is a member of ALL force subscribe channels.
    Returns True if a member of all (or admin), False otherwise.
    """
    if is_admin(user_id):
        return True

    if not FORCE_SUB_CHANNELS:
        logger.info("No force subscribe channels configured. Skipping membership check.")
        return True

    async def check_channel(channel_id):
        try:
            member = await client.get_chat_member(channel_id, user_id)
            return member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
        except PeerIdInvalid:
            logger.error(f"Force subscribe channel ID {channel_id} is invalid. Please check config.")
            return True # Allow access if a channel is misconfigured
        except Exception as e:
            logger.error(f"Error checking membership for user {user_id} in channel {channel_id}: {e}", exc_info=True)
            return False

    results = await asyncio.gather(*[check_channel(c['channel_id']) for c in FORCE_SUB_CHANNELS])

    is_member_of_all = all(results)
    if is_member_of_all:
        logger.info(f"User {user_id} is a member of all force sub channels.")
    else:
        logger.info(f"User {user_id} is NOT a member of all force sub channels. Results: {results}")

    return is_member_of_all

async def send_force_subscribe_message(client: Client, chat_id: int, custom_text: str = None):
    """Sends a message prompting the user to join the force subscribe channels."""
    logger.info(f"Sending force subscribe message to user {chat_id}.")

    if not FORCE_SUB_CHANNELS:
        await client.send_message(chat_id, "⚠️ No force subscribe channels are configured. Please contact an admin.")
        return

    buttons = []
    for channel_info in FORCE_SUB_CHANNELS:
        buttons.append([InlineKeyboardButton(f"📢 Join {channel_info.get('name', 'Updates Channel')}", url=channel_info.get('link', 'https://t.me/telegram'))])
    buttons.append([InlineKeyboardButton("🔄 Try Again", callback_data="check_join_status")])

    reply_markup = InlineKeyboardMarkup(buttons)

    text_to_send = custom_text
    if not text_to_send:
        text_to_send = (
            "⚠️ <b>Access Requirement</b> ⚠️\n\n"
            "To enjoy our exclusive collection, you need to join our updates channels first.\n\n"
            "Please join the channels listed below, then tap the <b>🔄 Try Again</b> button to unlock full access! 🚀"
        )

    await client.send_message(
        chat_id,
        text_to_send,
        reply_markup=reply_markup
    )

# --- Utility Functions ---
def str_to_b64(string: str) -> str:
    """Encodes a string to URL-safe base64."""
    return base64.urlsafe_b64encode(string.encode('utf-8')).decode('utf-8')

def b64_to_str(b64: str) -> str:
    """Decodes a URL-safe base64 string."""
    try:
        return base64.urlsafe_b64decode(b64.encode('utf-8')).decode('utf-8')
    except Exception as e:
        logger.error(f"Failed to decode base64 string: {e}")
        return ""

def get_fake_like_ratio(video_uuid: str) -> int:
    """Generates a deterministic base like ratio between 45% and 95% based on the video UUID."""
    import random
    state = random.getstate()
    random.seed(video_uuid)
    ratio = random.randint(45, 95)
    random.setstate(state)
    return ratio

def get_user_adjusted_fake_ratio(user_id: int, video_uuid: str) -> int:
    """Calculates the fake ratio adjusted dynamically by +1-2% or -1-2% if the user has liked/disliked."""
    import random
    base_ratio = get_fake_like_ratio(video_uuid)

    user_doc = users_collection.find_one({'user_id': user_id})
    user_ratings = user_doc.get('ratings', {}) if user_doc else {}
    user_rating = user_ratings.get(video_uuid)

    state = random.getstate()
    random.seed(video_uuid + str(user_id))
    adjustment = random.randint(1, 2)
    random.setstate(state)

    if user_rating == "like":
        return min(99, base_ratio + adjustment)
    elif user_rating == "dislike":
        return max(40, base_ratio - adjustment)
    return base_ratio

def get_channel_msg_link(channel_id, message_id):
    """Generates a t.me link for a message in a channel, handling private channels."""
    if not channel_id or not message_id:
        return None
    str_id = str(channel_id)
    if str_id.startswith("-100"):
        return f"https://t.me/c/{str_id[4:]}/{message_id}"
    return f"https://t.me/{str_id}/{message_id}"

def get_current_time() -> int:
    """Returns the current UTC timestamp as an integer."""
    return int(datetime.now(timezone.utc).timestamp())

async def get_shortener_config_and_shorten_url(long_url: str) -> str:
    """
    Shortens a given URL using the configured URL shortener service (Shortzy).
    Fetches configuration from the database. If no config or API error, returns original URL.
    """
    logger.info(f"Attempting to shorten URL: {long_url}")
    shortener_config = settings_collection.find_one({'_id': 'shortener_config'})
    logger.info(f"Retrieved shortener_config from DB: {shortener_config}")

    if not shortener_config:
        logger.warning("URL shortener configuration not found in DB. Returning original URL.")
        return long_url

    template_url = shortener_config.get('template_url')
    logger.info(f"Template URL from config: {template_url}")

    if not template_url or '{long_url}' not in template_url:
        logger.warning("Missing or invalid 'template_url' in shortener config (no {long_url} placeholder). Returning original URL.")
        return long_url

    try:
        parsed_url = urllib.parse.urlparse(template_url)
        base_site = parsed_url.netloc

        query_params = urllib.parse.parse_qs(parsed_url.query)
        api_key_list = query_params.get('api')

        if not api_key_list:
            logger.warning("No 'api' key found in the template_url query parameters. Cannot initialize Shortzy. Returning original URL.")
            return long_url

        api_key = api_key_list[0]

        if base_site.startswith("http://"):
            base_site = base_site[len("http://"):]
        elif base_site.startswith("https://"):
            base_site = base_site[len("https://"):]

        base_site = parsed_url.netloc

        shortzy_client = Shortzy(api_key=api_key, base_site=base_site)
        logger.info(f"Initialized Shortzy with base_site: {base_site}, api_key: {'*' * len(api_key)}")

        shortened_url = await shortzy_client.convert(long_url)

        if shortened_url and (shortened_url.startswith("http://") or shortened_url.startswith("https://")):
            logger.info(f"URL shortened successfully (Shortzy) to: {shortened_url}")
            return shortened_url
        else:
            logger.warning(f"Shortzy returned an invalid or non-URL string: {shortened_url}. Returning original URL.")
            return long_url

    except Exception as e:
        logger.error(f"Error using Shortzy to shorten URL {long_url}: {e}", exc_info=True)
        return long_url

# --- Token and Premium Management ---
def add_token(user_id: int, duration_seconds: int = config.TOKEN_EXPIRY, is_admin_granted: bool = False):
    """
    Adds a new token for a user with a specified duration.
    Admin-granted tokens (Premium) are activated immediately.
    Others are banked until manually activated by the user.
    """
    now = datetime.now(timezone.utc)
    # Admin granted tokens activate immediately.
    should_activate = is_admin_granted

    expires_at = now + timedelta(seconds=duration_seconds) if should_activate else None

    token = {
        'token_id': str(uuid.uuid4()),
        'created_at': now,
        'expires_at': expires_at,
        'duration_seconds': duration_seconds,
        'is_admin_granted': is_admin_granted,
        'is_activated': should_activate
    }
    try:
        tokens_collection.update_one(
            {'user_id': user_id},
            {'$push': {'tokens': token}},
            upsert=True
        )
        logger.info(f"Token added for user {user_id}. Admin granted: {is_admin_granted}, Activated: {should_activate}")
        return token
    except Exception as e:
        logger.error(f"Error adding token for user {user_id}: {e}", exc_info=True)
        return None

def is_premium_user(user_id: int) -> bool:
    """Checks if a user is a premium user (has an active admin-granted token)."""
    now = datetime.now(timezone.utc)
    doc = tokens_collection.find_one({'user_id': user_id})
    if not doc or 'tokens' not in doc:
        return False

    for token in doc['tokens']:
        # Consider both is_activated field and legacy tokens (where field might be missing)
        if token.get('is_activated', True) and token.get('is_admin_granted', False) and token.get('expires_at') and token['expires_at'] > now:
            return True
    return False

def user_has_token(user_id: int) -> bool:
    """Checks if a user has any valid tokens (admin-granted or not) for general access."""
    now = datetime.now(timezone.utc)
    doc = tokens_collection.find_one({'user_id': user_id})
    if not doc or 'tokens' not in doc:
        return False

    for token in doc['tokens']:
        # Consider both is_activated field and legacy tokens (where field might be missing)
        if token.get('is_activated', True) and token.get('expires_at') and token['expires_at'] > now:
            return True

    # No active token found! Check if they have any banked tokens to automatically activate
    banked_tokens = [t for t in doc['tokens'] if not t.get('is_activated', False)]
    if banked_tokens:
        # Sort by creation date to activate the oldest one first
        banked_tokens.sort(key=lambda x: x.get('created_at', datetime.min.replace(tzinfo=timezone.utc)))
        target_token = banked_tokens[0]

        duration = target_token.get('duration_seconds', config.TOKEN_EXPIRY)
        expires_at = now + timedelta(seconds=duration)

        try:
            # Atomically update the specific token in the array
            result = tokens_collection.update_one(
                {'user_id': user_id, 'tokens.token_id': target_token['token_id']},
                {'$set': {
                    'tokens.$.is_activated': True,
                    'tokens.$.expires_at': expires_at,
                    'tokens.$.activated_at': now
                }}
            )
            if result.modified_count > 0:
                logger.info(f"Automatically activated banked token {target_token['token_id']} for user {user_id}.")
                return True
        except Exception as e:
            logger.error(f"Error automatically activating banked token for user {user_id}: {e}", exc_info=True)

    return False

def get_banked_tokens_count(user_id: int) -> int:
    """Returns the number of unactivated tokens a user has."""
    doc = tokens_collection.find_one({'user_id': user_id})
    if not doc or 'tokens' not in doc:
        return 0
    return sum(1 for t in doc['tokens'] if not t.get('is_activated', False))

async def activate_bank_token(user_id: int) -> tuple[bool, str]:
    """Activates one banked token for the user."""
    doc = tokens_collection.find_one({'user_id': user_id})
    if not doc or 'tokens' not in doc:
        return False, "You don't have any tokens to activate."

    banked_tokens = [t for t in doc['tokens'] if not t.get('is_activated', False)]
    if not banked_tokens:
        return False, "Your token bank is empty."

    # Sort by creation date to activate the oldest one first
    banked_tokens.sort(key=lambda x: x.get('created_at', datetime.min.replace(tzinfo=timezone.utc)))
    target_token = banked_tokens[0]

    now = datetime.now(timezone.utc)
    duration = target_token.get('duration_seconds', config.TOKEN_EXPIRY)
    expires_at = now + timedelta(seconds=duration)

    try:
        # Atomically update the specific token in the array
        result = tokens_collection.update_one(
            {'user_id': user_id, 'tokens.token_id': target_token['token_id']},
            {'$set': {
                'tokens.$.is_activated': True,
                'tokens.$.expires_at': expires_at,
                'tokens.$.activated_at': now
            }}
        )

        if result.modified_count > 0:
            hours = int(duration / 3600)
            return True, f"✅ **Token Activated!**\n\nYou now have **{hours} hours** of full access. Enjoy! 🍿"
        else:
            return False, "Failed to activate token. Please try again."
    except Exception as e:
        logger.error(f"Error activating token for user {user_id}: {e}", exc_info=True)
        return False, "An error occurred during activation."

def user_can_access_video(user_id: int) -> bool:
    """Checks if a user can access video content (is premium or has a token)."""
    return is_premium_user(user_id) or user_has_token(user_id)

def has_free_video_access(user_id: int, limit: int = None, current_video_uuid: str = None) -> bool:
    """Checks if a user has daily free video access remaining, including temporary and permanent scrolls."""
    if is_premium_user(user_id) or user_has_token(user_id):
        return True

    # Allow interacting with the current video even if limit reached (Liking/Sharing the last allowed preview)
    active_menu = active_video_message.get(user_id)
    if current_video_uuid and active_menu and active_menu.get('video_uuid') == current_video_uuid:
        return True

    user = users_collection.find_one({'user_id': user_id})
    if not user:
        return False

    # Check Permanent Scrolls
    if user.get('permanent_scrolls', 0) > 0:
        return True

    # Check Temporary Scrolls
    now = datetime.now(timezone.utc)
    temp_scrolls = user.get('temp_scrolls', [])
    valid_temp_scrolls = [s for s in temp_scrolls if (s.get('expires_at') is None or s['expires_at'] > now) and s.get('amount', 0) > 0]
    if valid_temp_scrolls:
        return True

    if limit is None:
        limit = config.DAILY_FREE_VIDEOS

    usage = user.get('free_video_usage')
    now = datetime.now(timezone.utc)
    if not usage or now > usage.get('reset_at', datetime.min.replace(tzinfo=timezone.utc)):
        # Reset usage
        users_collection.update_one(
            {'user_id': user_id},
            {'$set': {
                'free_video_usage.count': 0,
                'free_video_usage.reset_at': now + timedelta(hours=config.FREE_VIDEO_RESET_HOURS)
            }}
        )
        return True

    return usage.get('count', 0) < limit

def mark_free_video_used(user_id: int):
    """Consumes a scroll (permanent or temporary) or increments daily free usage."""
    if is_premium_user(user_id) or user_has_token(user_id):
        return

    user = users_collection.find_one({'user_id': user_id})
    if not user:
        return

    # 1. Try consuming Permanent Scroll
    if user.get('permanent_scrolls', 0) > 0:
        users_collection.update_one({'user_id': user_id}, {'$inc': {'permanent_scrolls': -1}})
        logger.info(f"Consumed 1 permanent scroll for user {user_id}.")
        return

    # 2. Try consuming Temporary Scroll
    now = datetime.now(timezone.utc)
    temp_scrolls = user.get('temp_scrolls', [])
    # Find oldest valid temp scroll
    valid_indices = [i for i, s in enumerate(temp_scrolls) if (s.get('expires_at') is None or s['expires_at'] > now) and s.get('amount', 0) > 0]
    if valid_indices:
        # Sort by expiry to use the one expiring soonest, with permanent scrolls used last
        valid_indices.sort(key=lambda i: temp_scrolls[i].get('expires_at') or datetime.max.replace(tzinfo=timezone.utc))
        target_idx = valid_indices[0]

        # Decrement amount
        users_collection.update_one(
            {'user_id': user_id},
            {'$inc': {f'temp_scrolls.{target_idx}.amount': -1}}
        )
        logger.info(f"Consumed 1 temporary scroll for user {user_id}.")
        return

    # 3. Fallback to daily free usage
    users_collection.update_one(
        {'user_id': user_id},
        {'$inc': {'free_video_usage.count': 1}}
    )

# --- Access Limit Management ---
async def send_access_limit_reached_message(client: Client, chat_id: int):
    """Sends a message informing the user they need a token to access content."""
    user_id = chat_id
    ad_code = str_to_b64(f"{user_id}:{get_current_time()}")
    shortener_logs_collection.insert_one({'ad_code': ad_code, 'user_id': user_id, 'created_at': datetime.now(timezone.utc)})
    long_url = f"https://t.me/{config.BOT_USERNAME[1:]}?start=token_{ad_code}"
    ad_url = await get_shortener_config_and_shorten_url(long_url) if not SHORTENER_DISABLED else ""

    if SHORTENER_DISABLED:
        text = (
            "✨ <b>Almost there! Just one quick step...</b>\n\n"
            "Please verify you're human to instantly unlock the next video and keep watching! ❤️"
        )
    else:
        text = (
            "🛑 <b>Access Token Required</b> 🛑\n\n"
            "To continue watching our private collection, you need a temporary access token. 🤫\n\n"
            f"Unlock <b>{int(config.TOKEN_ACCESS_HOURS)} hours</b> of uninterrupted, premium access and keep the vibe going! ✨"
        )
    reply_markup = generate_token_earning_keyboard(ad_url, user_id=user_id)
    await client.send_message(chat_id, text, reply_markup=reply_markup)

# --- Premium Status Check and Notification ---
async def check_premium_status_and_notify(client: Client, user_id: int):
    """
    Checks user's premium status and sends a notification if they just lost premium.
    Updates the user's last_premium_check_status in DB.
    """
    user_doc = users_collection.find_one({'user_id': user_id})
    if not user_doc:
        return

    current_premium_status = is_premium_user(user_id)
    last_known_premium_status = user_doc.get('last_premium_check_status', False)

    if last_known_premium_status and not current_premium_status:
        try:
            await client.send_message(user_id, "⚠️ <b>Your Premium Access Has Expired!</b>💔\n\nYour premium token has expired. You are no longer a premium user. Enjoy regular features or purchase new premium access! 🛒")
            logger.info(f"Notified user {user_id} about premium expiry.")
        except (UserIsBlocked, ChatInvalid):
            logger.warning(f"Could not notify user {user_id} about premium expiry; user blocked or chat invalid.")
        except Exception as e:
            logger.error(f"Failed to send premium expiry notification to user {user_id}: {e}")

    if current_premium_status != last_known_premium_status:
        users_collection.update_one(
            {'user_id': user_id},
            {'$set': {'last_premium_check_status': current_premium_status}}
        )
        logger.info(f"Updated last_premium_check_status for user {user_id} to {current_premium_status}.")

# --- Referral System ---
def handle_referral(new_user_id: int, ref_code: str) -> int | None:
    """Handles a new user joining via a referral link, rewarding the referrer."""
    if ref_code.startswith('ref_'):
        try:
            referrer_id = int(ref_code[4:])
        except ValueError:
            logger.warning(f"Invalid referrer ID format in ref_code: {ref_code}")
            return None

        if referrer_id != new_user_id:
            ref_user = users_collection.find_one({'user_id': referrer_id})
            if ref_user:
                add_token(referrer_id, config.REFERRAL_BONUS * config.TOKEN_EXPIRY, is_admin_granted=False)
                users_collection.update_one({'user_id': referrer_id}, {'$inc': {'referral_count': 1}}, upsert=True)
                users_collection.update_one({'user_id': new_user_id}, {'$set': {'referred_by': referrer_id}}, upsert=True)
                logger.info(f"User {new_user_id} successfully referred by {referrer_id}.")
                return referrer_id
    elif ref_code.startswith('video_'):
        try:
            # ref_code format: video_UUID_REFERRERID
            parts = ref_code.rsplit('_', 1)
            if len(parts) == 2:
                referrer_id_str = parts[1]
                if referrer_id_str.isdigit() or (referrer_id_str.startswith('-') and referrer_id_str[1:].isdigit()):
                    referrer_id = int(referrer_id_str)
                else:
                    return None

                if referrer_id != new_user_id:
                    ref_user = users_collection.find_one({'user_id': referrer_id})
                    if ref_user:
                        add_token(referrer_id, config.REFERRAL_BONUS * config.TOKEN_EXPIRY, is_admin_granted=False)
                        users_collection.update_one({'user_id': referrer_id}, {'$inc': {'referral_count': 1}}, upsert=True)
                        users_collection.update_one({'user_id': new_user_id}, {'$set': {'referred_by': referrer_id}}, upsert=True)
                        logger.info(f"User {new_user_id} successfully referred by {referrer_id} via video share.")
                        return referrer_id
        except ValueError:
            logger.warning(f"Invalid referrer ID format in video share ref_code: {ref_code}")
        except IndexError:
            logger.warning(f"Invalid video share ref_code format: {ref_code}")

    return None

async def check_and_grant_referral_milestones(client: Client, referrer_id: int):
    """
    Checks if the referrer has reached a milestone and grants premium rewards.
    Milestones:
    - 5 referrals -> 1 Day Premium (+86400 seconds, is_admin_granted=True)
    - 10 referrals -> 3 Days Premium (+259200 seconds, is_admin_granted=True)
    - 20 referrals -> 7 Days Premium (+604800 seconds, is_admin_granted=True)
    - 50 referrals -> 30 Days Premium (+2592000 seconds, is_admin_granted=True)
    """
    try:
        user_doc = users_collection.find_one({'user_id': referrer_id})
        if not user_doc:
            return

        referral_count = user_doc.get('referral_count', 0)
        claimed_milestones = user_doc.get('claimed_referral_milestones', [])

        milestones = [
            (5, 1, 86400, "Tier 1"),
            (10, 3, 259200, "Tier 2"),
            (20, 7, 604800, "Tier 3"),
            (50, 30, 2592000, "Tier 4")
        ]

        for req_count, days_reward, duration_seconds, tier_name in milestones:
            if referral_count >= req_count and req_count not in claimed_milestones:
                # Grant the token
                add_token_info = add_token(referrer_id, duration_seconds=duration_seconds, is_admin_granted=True)
                if add_token_info:
                    # Update claimed list
                    users_collection.update_one(
                        {'user_id': referrer_id},
                        {
                            '$addToSet': {'claimed_referral_milestones': req_count},
                            '$set': {'last_premium_check_status': True}
                        }
                    )
                    logger.info(f"Referrer {referrer_id} reached {req_count} referrals and won {days_reward} days premium!")
                    try:
                        await client.send_message(
                            referrer_id,
                            f"🏆 <b>Referral Milestone Reached!</b> ({tier_name}) 🎉\n\n"
                            f"Outstanding job! You have reached <b>{req_count} successful referrals</b>.\n\n"
                            f"🎁 As a reward, you have been granted <b>{days_reward} Days of unlimited VIP Premium Access</b> for free! Enjoy your ad-free, download-ready experience! 💎"
                        )
                    except Exception as notify_e:
                        logger.warning(f"Could not notify referrer {referrer_id} about milestone reward: {notify_e}")
    except Exception as e:
        logger.error(f"Error checking referral milestones for {referrer_id}: {e}", exc_info=True)

# --- Category Management ---
def validate_category_name(name: str) -> tuple[bool, str]:
    """
    Validates a category name.
    Allows spaces, letters, numbers, and most Unicode characters including emojis.
    Returns (is_valid, error_message).
    """
    if not name:
        return False, "Category name cannot be empty."
    # Allowing more characters, but still limiting length
    if len(name) > 64: # Increased max length slightly for longer names/emojis
        return False, "Category name cannot be longer than 64 characters."
    return True, ""

def get_categories(for_admin_use: bool = False) -> list[str]:
    """
    Gets all category names.
    Prepends 'default (all)' for user-facing lists.
    """
    categories = [c['name'] for c in categories_collection.find({})]
    sorted_categories = sorted(list(set(categories)))
    if not for_admin_use:
        return ["default (all)"] + sorted_categories
    return sorted_categories

def add_category(name: str) -> tuple[bool, str]:
    """Adds a new category. Returns (success, message)"""
    try:
        valid, error = validate_category_name(name)
        if not valid:
            return False, error

        if categories_collection.find_one({'name': name}):
            return False, f"Category '{html.escape(name)}' already exists."

        categories_collection.insert_one({
            'name': name,
            'created_at': datetime.now(timezone.utc)
        })
        logger.info(f"Category '{name}' added")
        return True, f"Category '{html.escape(name)}' added successfully."
    except Exception as e:
        logger.error(f"Error adding category '{name}': {e}")
        return False, "Failed to add category. Please try again."

def delete_category(name: str) -> tuple[bool, str, int]:
    """Deletes a category and its associated videos. Returns (success, message, deleted_count)"""
    if name == "default (all)":
        return False, "The 'default (all)' category cannot be deleted.", 0
    try:
        if not categories_collection.find_one({'name': name}):
            return False, f"Category '{html.escape(name)}' does not exist."

        result = media_collection.delete_many({'category': name})
        deleted_count = result.deleted_count

        categories_collection.delete_one({'name': name})
        logger.info(f"Category '{name}' and {deleted_count} videos deleted")
        return True, f"Category '{html.escape(name)}' and {deleted_count} videos deleted.", deleted_count
    except Exception as e:
        logger.error(f"Error deleting category '{name}': {e}")
        return False, "Failed to delete category. Please try again.", 0

# --- Video Navigation ---

def get_first_video_by_sequence_number(category: str) -> dict | None:
    """
    Retrieves the first video in the specified category based on its sequence_number.
    Filters for valid, non-banned videos with a sequence number.
    """
    video = media_collection.find_one(
        {'category': category, 'sequence_number': {'$exists': True, '$ne': None}, 'banned': {'$ne': True}},
        sort=[('sequence_number', ASCENDING)]
    )
    return video

def get_video_by_uuid(uuid_: str) -> dict | None:
    """Retrieves a video by its UUID."""
    return media_collection.find_one({'uuid': uuid_})

def get_video_and_position(video_uuid: str, category: str, is_saved: bool, user_id: int = None) -> tuple[dict | None, int, int]:
    """
    Retrieves a video and its position (index + total) within its category,
    considering if it's a regular or saved video.
    Returns (video_data, current_position, total_videos).
    """
    if is_saved and user_id is not None:
        user_doc = users_collection.find_one({'user_id': user_id})
        bookmarked_videos = user_doc.get('bookmarked_videos', [])

        # Filter for the specific category and validity, then sort by bookmarked_at
        filtered_saved_videos = []
        for bookmark in bookmarked_videos:
            video_data = get_video_by_uuid(bookmark['uuid'])
            if video_data and video_data.get('category') == category:
                filtered_saved_videos.append(bookmark)

        filtered_saved_videos.sort(key=lambda x: x.get('bookmarked_at', datetime.min.replace(tzinfo=timezone.utc)))

        total_videos = len(filtered_saved_videos)
        if not total_videos:
            return None, 0, 0

        current_video_index = -1
        for i, entry in enumerate(filtered_saved_videos):
            if entry['uuid'] == video_uuid:
                current_video_index = i
                break

        if current_video_index != -1:
            video = get_video_by_uuid(video_uuid)
            return video, current_video_index + 1, total_videos
        return None, 0, 0

    else: # Regular category navigation, use sequence_number for ordering
        all_videos_in_category = list(media_collection.find(
            {'category': category, 'sequence_number': {'$exists': True, '$ne': None}, 'banned': {'$ne': True}},
            sort=[('sequence_number', ASCENDING)]
        ))

        total_videos = len(all_videos_in_category)
        if not total_videos:
            return None, 0, 0

        current_video_index = -1
        for i, video_doc in enumerate(all_videos_in_category):
            if video_doc['uuid'] == video_uuid:
                current_video_index = i
                break

        if current_video_index != -1:
            video = all_videos_in_category[current_video_index]
            # Added log for missing sequence_number during navigation
            if 'sequence_number' not in video:
                logger.warning(f"Video {video['uuid']} in category {category} is missing 'sequence_number' but is being retrieved for navigation. This indicates a potential data inconsistency or failed migration.")
            return video, current_video_index + 1, total_videos
        return None, 0, 0

def get_video_and_position_batch(batch_id: str, current_index: int) -> tuple[dict | None, int, int]:
    """
    Retrieves a video and its position from a specific batch.
    Returns (video_data, current_position, total_videos).
    """
    batch_doc = video_batches_collection.find_one({'batch_id': batch_id})
    if not batch_doc:
        return None, 0, 0

    video_uuids = batch_doc.get('video_uuids', [])
    total_videos = len(video_uuids)

    if not (0 <= current_index < total_videos):
        return None, 0, 0

    video_uuid = video_uuids[current_index]
    video = get_video_by_uuid(video_uuid)

    return video, current_index + 1, total_videos

def get_next_video_chronological(current_uuid: str, category: str) -> dict | None:
    """
    Retrieves the video immediately after the current video in the same category,
    based on sequence_number. Loops to the first video if at the end.
    """
    current_video = media_collection.find_one({'uuid': current_uuid, 'category': category})
    if not current_video or 'sequence_number' not in current_video:
        logger.warning(f"Current video {current_uuid} not found or missing sequence_number for next chronological lookup. Attempting to get first video.")
        return get_first_video_by_sequence_number(category)

    current_sequence = current_video['sequence_number']

    # Find the next video with a sequence number strictly greater than the current one
    next_video = media_collection.find_one(
        {'category': category, 'sequence_number': {'$gt': current_sequence}, 'banned': {'$ne': True}},
        sort=[('sequence_number', ASCENDING)]
    )

    if next_video:
        logger.debug(f"Found next video {next_video['uuid']} with sequence {next_video['sequence_number']} after {current_sequence}.")
        return next_video
    else:
        logger.info(f"End of videos reached for category '{category}'. Looping to first video.")
        return get_first_video_by_sequence_number(category)

def get_previous_video_chronological(current_uuid: str, category: str) -> dict | None:
    """
    Retrieves the video immediately before the current video in the same category,
    based on sequence_number. Loops to the last video if at the beginning.
    """
    current_video = media_collection.find_one({'uuid': current_uuid, 'category': category})
    if not current_video or 'sequence_number' not in current_video:
        logger.warning(f"Current video {current_uuid} not found or missing sequence_number for previous chronological lookup. Attempting to get last video.")
        return media_collection.find_one(
            {'category': category},
            sort=[('sequence_number', DESCENDING)]
        )

    current_sequence = current_video['sequence_number']

    # Find the previous video with a sequence number strictly less than the current one
    prev_video = media_collection.find_one(
        {'category': category, 'sequence_number': {'$lt': current_sequence}, 'banned': {'$ne': True}},
        sort=[('sequence_number', DESCENDING)] # Sort descending to get the largest sequence_number less than current
    )

    if prev_video:
        logger.debug(f"Found previous video {prev_video['uuid']} with sequence {prev_video['sequence_number']} before {current_sequence}.")
        return prev_video
    else:
        logger.info(f"Beginning of videos reached for category '{category}'. Looping to last video.")
        return media_collection.find_one(
            {'category': category},
            sort=[('sequence_number', DESCENDING)]
        )

def get_next_saved_video_chronological(user_id: int, current_uuid: str, category: str) -> dict | None:
    """
    Retrieves the next saved video for a user in a specific category,
    based on their bookmarking order. Loops to the first if at the end.
    """
    user_doc = users_collection.find_one({'user_id': user_id})
    if not user_doc or not user_doc.get('bookmarked_videos'):
        return None

    bookmarked_videos = user_doc['bookmarked_videos']

    # Filter for the specific category and validity, then sort by bookmarked_at
    filtered_saved_videos = []
    for bookmark in bookmarked_videos:
        video_data = get_video_by_uuid(bookmark['uuid'])
        if video_data and video_data.get('category') == category:
            filtered_saved_videos.append(bookmark)

    filtered_saved_videos.sort(key=lambda x: x.get('bookmarked_at', datetime.min.replace(tzinfo=timezone.utc)))

    if not filtered_saved_videos:
        return None

    current_video_index = -1
    for i, entry in enumerate(filtered_saved_videos):
        if entry['uuid'] == current_uuid:
            current_video_index = i
            break

    if current_video_index == -1: # Current video not found in the filtered list, return first
        logger.warning(f"Current saved video {current_uuid} not found in filtered list for user {user_id}. Returning first saved video in category {category}.")
        return get_video_by_uuid(filtered_saved_videos[0]['uuid'])

    next_index = (current_video_index + 1) % len(filtered_saved_videos)
    next_video_uuid = filtered_saved_videos[next_index]['uuid']

    return get_video_by_uuid(next_video_uuid)

def get_previous_saved_video_chronological(user_id: int, current_uuid: str, category: str) -> dict | None:
    """
    Retrieves the previous saved video for a user in a specific category,
    based on their bookmarking order. Loops to the last if at the beginning.
    """
    user_doc = users_collection.find_one({'user_id': user_id})
    if not user_doc or not user_doc.get('bookmarked_videos'):
        return None

    bookmarked_videos = user_doc['bookmarked_videos']

    # Filter for the specific category and validity, then sort by bookmarked_at
    filtered_saved_videos = []
    for bookmark in bookmarked_videos:
        video_data = get_video_by_uuid(bookmark['uuid'])
        if video_data and video_data.get('category') == category:
            filtered_saved_videos.append(bookmark)

    filtered_saved_videos.sort(key=lambda x: x.get('bookmarked_at', datetime.min.replace(tzinfo=timezone.utc)))

    if not filtered_saved_videos:
        return None

    current_video_index = -1
    for i, entry in enumerate(filtered_saved_videos):
        if entry['uuid'] == current_uuid:
            current_video_index = i
            break

    if current_video_index == -1: # Current video not found in the filtered list, return last
        logger.warning(f"Current saved video {current_uuid} not found in filtered list for user {user_id}. Returning last saved video in category {category}.")
        return get_video_by_uuid(filtered_saved_videos[-1]['uuid'])

    prev_index = (current_video_index - 1 + len(filtered_saved_videos)) % len(filtered_saved_videos)
    prev_video_uuid = filtered_saved_videos[prev_index]['uuid']

    return get_video_by_uuid(prev_video_uuid)


def get_random_video() -> dict | None:
    """Retrieves one random video from the entire collection (valid and non-banned only)."""
    pipeline = [
        {'$match': {'sequence_number': {'$exists': True, '$ne': None}, 'banned': {'$ne': True}}},
        {'$sample': {'size': 1}}
    ]
    random_videos = list(media_collection.aggregate(pipeline))
    if random_videos:
        return random_videos[0]
    return None

def get_random_video_from_different_category(exclude_category: str) -> dict | None:
    """Retrieves one random video from any category except the excluded one (valid and non-banned only)."""
    pipeline = [
        {'$match': {'category': {'$ne': exclude_category}, 'sequence_number': {'$exists': True, '$ne': None}, 'banned': {'$ne': True}}},
        {'$sample': {'size': 1}}
    ]
    random_videos = list(media_collection.aggregate(pipeline))
    if random_videos:
        return random_videos[0]
    # Fallback in case the only videos available are from the excluded category
    return get_random_video()


def save_history(user_id: int, video_uuid: str, category: str):
    """
    Saves a video viewing entry to a user's general history (limited to 100 entries)
    AND updates the last viewed video for the specific category.
    """
    now = datetime.now(timezone.utc)
    entry = {'video_uuid': video_uuid, 'category': category, 'viewed_at': now}
    try:
        history_collection.update_one(
            {'user_id': user_id},
            {'$push': {'history': {'$each': [entry], '$slice': -100}}},
            upsert=True
        )
        logger.info(f"General history saved for user {user_id}, video {video_uuid}. History size limited to 100.")

        if category != "default (all)":
            users_collection.update_one(
                {'user_id': user_id},
                {'$set': {f'last_viewed_per_category.{category}': video_uuid}},
                upsert=True
            )
            logger.info(f"Last viewed video for category '{category}' updated to '{video_uuid}' for user {user_id}.")

    except Exception as e:
        logger.error(f"Error saving history/last viewed for user {user_id}, video {video_uuid}: {e}", exc_info=True)

# --- Message Tracking and Immediate Deletion ---
active_video_message = {}

def set_active_video_message(user_id: int, message_id: int, chat_id: int, video_uuid: str = None):
    """Set the active message for a user, to be deleted on next action."""
    active_video_message[user_id] = {
        'message_id': message_id,
        'chat_id': chat_id,
        'timestamp': datetime.now(timezone.utc),
        'video_uuid': video_uuid
    }
    logger.info(f"Active video message set for user {user_id}: message_id={message_id}, chat_id={chat_id}, video_uuid={video_uuid}")

def clear_active_video_message(user_id: int):
    """Clear a user's active message state."""
    if user_id in active_video_message:
        del active_video_message[user_id]
        logger.info(f"Active video message cleared for user {user_id}.")

# --- Real-time self-healing functions ---
def rearrange_sequences_after_deletion(category: str, deleted_sequence_number: int):
    """
    Decrements sequence numbers for all videos in a category that come after a deleted video.
    This is a synchronous function for use within async contexts.
    """
    logger.info(f"Rearranging sequences for category '{category}' after deleting sequence {deleted_sequence_number}.")
    try:
        # Find all videos with sequence number greater than the deleted one
        videos_to_update = list(media_collection.find(
            {'category': category, 'sequence_number': {'$gt': deleted_sequence_number}},
            projection={'_id': 1, 'sequence_number': 1}
        ).sort('sequence_number', ASCENDING))

        if not videos_to_update:
            logger.info(f"No videos found after sequence {deleted_sequence_number} in category '{category}' to rearrange.")
            return

        operations = []
        for video_doc in videos_to_update:
            current_seq = video_doc['sequence_number']
            new_seq = current_seq - 1
            operations.append(
                UpdateOne(
                    {'_id': video_doc['_id']},
                    {'$set': {'sequence_number': new_seq}}
                )
            )
            logger.debug(f"Preparing update: video_id={video_doc['_id']}, old_seq={current_seq}, new_seq={new_seq}")

        if operations:
            result = media_collection.bulk_write(operations)
            logger.info(f"Successfully rearranged sequences for category '{category}'. Modified {result.modified_count} documents.")
        else:
            logger.info(f"No bulk write operations needed for category '{category}'.")

    except Exception as e:
        logger.error(f"Error rearranging sequences for category '{category}' after deleting sequence {deleted_sequence_number}: {e}", exc_info=True)

async def delete_broken_video_from_db_and_channel(client: Client, video_uuid: str, category: str, sequence_number: int, message_id_in_channel: int):
    """
    Deletes a video entry from MongoDB and attempts to delete its message from the channel.
    Handles sequence rearrangement and user data cleanup.
    """
    logger.info(f"Attempting to delete broken video {video_uuid} from DB and channel.")
    if not DATA_CHANNEL_ID:
        logger.error("DATA_CHANNEL_ID is not set. Cannot delete from channel.")
        return False

    try:
        # 1. Delete from media collection
        result = media_collection.delete_one({'uuid': video_uuid})
        if result.deleted_count > 0:
            logger.info(f"Successfully deleted video {video_uuid} from media_collection.")

            # 2. Rearrange sequences
            if category and sequence_number is not None:
                rearrange_sequences_after_deletion(category, sequence_number)
            else:
                logger.warning(f"Skipping sequence rearrangement for {video_uuid}: category or sequence_number missing.")

            # 3. Clean up user bookmarks
            users_collection.update_many(
                {},
                {'$pull': {'bookmarked_videos': {'uuid': video_uuid}}}
            )
            logger.info(f"Removed video {video_uuid} from all users' bookmarked_videos.")

            # 4. Clean up user history
            history_collection.update_many(
                {},
                {'$pull': {'history': {'video_uuid': video_uuid}}}
            )
            logger.info(f"Removed video {video_uuid} from all users' history.")

            # 5. Clean up last_viewed_per_category
            all_users_with_last_viewed = users_collection.find({'last_viewed_per_category': {'$exists': True}})
            for user_doc in all_users_with_last_viewed:
                user_id_to_update = user_doc['user_id']
                updated_last_viewed = {}
                changed = False
                for cat, vid_uuid_in_map in user_doc['last_viewed_per_category'].items():
                    if vid_uuid_in_map == video_uuid:
                        changed = True
                    else:
                        updated_last_viewed[cat] = vid_uuid_in_map
                if changed:
                    users_collection.update_one(
                        {'user_id': user_id_to_update},
                        {'$set': {'last_viewed_per_category': updated_last_viewed}}
                    )
                    logger.info(f"Removed video {video_uuid} from last_viewed_per_category for user {user_id_to_update}.")

            # 6. Attempt to delete from Telegram channel (only if bot has permission)
            if message_id_in_channel:
                logger.info(f"Checking bot permissions to delete message {message_id_in_channel} from channel {DATA_CHANNEL_ID}.")
                try:
                    me = await client.get_me()
                    member = await client.get_chat_member(DATA_CHANNEL_ID, me.id)

                    if member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER] and member.can_delete_messages:
                        await client.delete_messages(DATA_CHANNEL_ID, message_id_in_channel)
                        logger.info(f"Successfully deleted message {message_id_in_channel} from channel {DATA_CHANNEL_ID}.")
                    else:
                        logger.warning(f"Bot lacks 'Delete Messages' permission in channel {DATA_CHANNEL_ID}. Cannot delete message {message_id_in_channel}. DB entry removed.")
                except MessageIdInvalid:
                    logger.warning(f"Message {message_id_in_channel} already deleted or invalid in channel {DATA_CHANNEL_ID}. DB entry removed.")
                except FloodWait as fw:
                    logger.warning(f"FloodWait deleting message {message_id_in_channel}: {fw.value}s. Skipping channel deletion for now. DB entry removed.")
                except ChatAdminRequired:
                    logger.warning(f"Bot is not admin in channel {DATA_CHANNEL_ID}. Cannot delete message {message_id_in_channel}. DB entry removed.")
                except Exception as e:
                    logger.error(f"Failed to delete channel message {message_id_in_channel} for broken video {video_uuid}: {e}", exc_info=True)
                    logger.warning(f"Channel deletion failed for {video_uuid}. DB entry removed.")
            else:
                logger.info(f"Video {video_uuid} has no message_id_in_channel. Skipping channel deletion. DB entry removed.")

            return True
        else:
            logger.warning(f"Video {video_uuid} not found in media_collection for deletion (already deleted?).")
            return False
    except Exception as e:
        logger.error(f"Failed to delete broken video {video_uuid} from DB/channel: {e}", exc_info=True)
        return False

async def send_and_replace_message(
    client: Client,
    chat_id: int,
    message_id_to_edit_or_delete: int,
    new_message_type: str,
    video_data: dict = None,
    reply_markup: InlineKeyboardMarkup = None,
    text_content: str = None,
    force_new_message: bool = False,
    is_batch: bool = False,
    batch_id: str = None,
    batch_index: int = -1
) -> tuple[bool, Message | str]:
    """
    [MODIFIED] Prefers editing media/text over sending new messages for a smoother experience.
    It attempts to edit an existing message. If that fails, or if forced, it deletes the old one and sends a new one.
    Returns (success: bool, sent_message: Message | error_message: str)
    """
    sent_message = None
    settings = settings_collection.find_one({'_id': 'settings'}) or {}
    protect_content_for_user = settings.get('protect_content', True)

    if new_message_type == "video" and not DATA_CHANNEL_ID:
        logger.error("DATA_CHANNEL_ID is not set. Cannot send videos.")
        return False, "Video storage channel is not configured. Please contact an admin."

    # --- Prepare Caption ---
    caption_text = ""
    if new_message_type == "video" and video_data:
        current_position, total_videos = 0, 0
        if is_batch:
            _, current_position, total_videos = get_video_and_position_batch(batch_id, batch_index)
        else:
            is_saved_from_markup = False
            if reply_markup:
                for row in reply_markup.inline_keyboard:
                    for button in row:
                        if button.callback_data and '|' in button.callback_data:
                            parts = button.callback_data.split('|')
                            if (len(parts) == 3 or len(parts) == 4) and (parts[0] == 'next' or parts[0] == 'prev'):
                                is_saved_from_markup = bool(int(parts[-1]))
                                break
                    if is_saved_from_markup:
                        break
            _, current_position, total_videos = get_video_and_position(
                video_data['uuid'], video_data.get('category'), is_saved_from_markup, chat_id
            )

        custom_caption = video_data.get('custom_caption')
        category_name = video_data.get('category') or 'Default'

        if not is_batch and not is_saved_from_markup:
            # It's the Get Video menu! Use our premium layout with fake like ratio
            fake_ratio = get_user_adjusted_fake_ratio(chat_id, video_data['uuid'])
            caption_text = (
                f"🎬 <b>Now Playing: {html.escape(category_name)} Collection</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📦 <b>Video:</b> <code>#{current_position} of {total_videos}</code>\n"
                f"📈 <b>Community Rating:</b> <code>{fake_ratio}%</code> of users liked this ❤️\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            )
            if custom_caption:
                caption_text += f"📝 <i>{html.escape(custom_caption)}</i>\n\n"
            caption_text += f"🍿 <i>Enjoy your watch! Use the controls below to browse.</i>"
        else:
            # Other menus (saved, batch, shared links)
            if is_batch:
                caption_text = (
                    f"🎬 <b>Batch Video Playing</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"📦 <b>Video:</b> <code>#{current_position} of {total_videos}</code>\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                )
            elif is_saved_from_markup:
                caption_text = (
                    f"🔖 <b>Saved Videos: {html.escape(category_name)}</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"📦 <b>Video:</b> <code>#{current_position} of {total_videos}</code>\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                )
            else:
                caption_text = (
                    f"🔗 <b>Shared Video</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"🍿 <i>Enjoy your watch!</i>\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                )
            if custom_caption:
                caption_text += f"📝 <i>{html.escape(custom_caption)}</i>\n"

    # --- Delete Old Message if Forced ---
    if force_new_message and message_id_to_edit_or_delete:
        try:
            await client.delete_messages(chat_id, message_id_to_edit_or_delete)
            logger.info(f"Deleted old message {message_id_to_edit_or_delete} in chat {chat_id} before sending new.")
        except MessageIdInvalid:
            logger.warning(f"Old message {message_id_to_edit_or_delete} for deletion was already invalid.")
        except Exception as e:
            logger.error(f"Failed to delete old message {message_id_to_edit_or_delete}: {e}")

    # --- Attempt to Send/Edit Video ---
    if new_message_type == "video" and video_data:
        # Method 1: Try to edit the existing message
        if not force_new_message and message_id_to_edit_or_delete:
            try:
                sent_message = await client.edit_message_media(
                    chat_id=chat_id,
                    message_id=message_id_to_edit_or_delete,
                    media=InputMediaVideo(media=video_data['file_id'], caption=caption_text),
                    reply_markup=reply_markup
                )
                logger.info(f"Successfully edited message {message_id_to_edit_or_delete} with video {video_data['uuid']}.")
            except FileReferenceExpired:
                logger.warning(f"FileReferenceExpired on edit_message_media for video {video_data['uuid']}. Attempting self-healing.")
                try:
                    message_id_in_channel = video_data.get('message_id')
                    if not message_id_in_channel: raise ValueError("No message_id for healing.")
                    healed_message = await client.get_messages(DATA_CHANNEL_ID, message_id_in_channel)
                    if not healed_message or not healed_message.video: raise ValueError("Failed to fetch healed message.")
                    new_file_id = healed_message.video.file_id
                    media_collection.update_one({'uuid': video_data['uuid']}, {'$set': {'file_id': new_file_id}})
                    video_data['file_id'] = new_file_id
                    logger.info(f"DB updated with new file_id for {video_data['uuid']}. Retrying edit.")

                    sent_message = await client.edit_message_media(
                        chat_id=chat_id,
                        message_id=message_id_to_edit_or_delete,
                        media=InputMediaVideo(media=video_data['file_id'], caption=caption_text),
                        reply_markup=reply_markup
                    )
                    logger.info(f"Successfully edited message {message_id_to_edit_or_delete} after self-healing.")
                except Exception as heal_e:
                    logger.error(f"Self-healing or retry-edit failed: {heal_e}. Will send a new message instead.")
                    sent_message = None
            except Exception as e:
                logger.warning(f"Editing message {message_id_to_edit_or_delete} failed with non-healable error: {e}. Will send a new message instead.")
                sent_message = None

            if not sent_message and message_id_to_edit_or_delete:
                 try:
                    await client.delete_messages(chat_id, message_id_to_edit_or_delete)
                 except Exception:
                    pass

        # Method 2: Send a new message if editing failed or was skipped
        if not sent_message:
            try:
                logger.info(f"Attempting to send video {video_data['uuid']} via copy_message from channel.")
                sent_message = await client.copy_message(
                    chat_id=chat_id,
                    from_chat_id=DATA_CHANNEL_ID,
                    message_id=video_data.get('message_id'),
                    caption=caption_text,
                    protect_content=protect_content_for_user,
                    reply_markup=reply_markup
                )
                logger.info(f"Successfully sent video {video_data['uuid']} via copy_message.")
            except ChatAdminRequired:
                logger.critical(f"Bot is not an admin in the video channel {DATA_CHANNEL_ID}. Cannot copy messages.")
                await client.send_message(chat_id, "Please wait, the bot just got restarted. The admin is adding the bot to the channel.")
                return False, "Bot is not admin in video channel."
            except MessageIdInvalid as e:
                logger.warning(f"copy_message failed for video {video_data['uuid']} (Msg ID: {video_data.get('message_id')}). Reason: {e}. Triggering deletion.")
                await client.send_message(chat_id, "Oops! This video seems to be permanently unavailable and has been removed. Trying the next one... 🔄")
                create_tracked_task(delete_broken_video_from_db_and_channel(client, video_data['uuid'], video_data.get('category'), video_data.get('sequence_number'), video_data.get('message_id')))
                return False, "Video was permanently unavailable."
            except Exception as e:
                logger.error(f"copy_message failed for video {video_data['uuid']}. Error: {e}. Falling back to send_video.", exc_info=True)
                try:
                    logger.info(f"Attempting to send video {video_data['uuid']} via send_video fallback.")
                    sent_message = await client.send_video(
                        chat_id,
                        video_data['file_id'],
                        caption=caption_text,
                        reply_markup=reply_markup,
                        protect_content=protect_content_for_user
                    )
                    logger.info(f"Successfully sent video {video_data['uuid']} via send_video fallback.")
                except FileReferenceExpired:
                    logger.warning(f"FileReferenceExpired for video {video_data['uuid']} on send_video. Attempting self-healing.")
                    try:
                        message_id_in_channel = video_data.get('message_id')
                        if not message_id_in_channel:
                            raise ValueError("No message_id found in DB for self-healing.")

                        healed_message = await client.get_messages(DATA_CHANNEL_ID, message_id_in_channel)
                        if not healed_message or not healed_message.video:
                            raise ValueError("Failed to fetch or find video in healed message.")

                        new_file_id = healed_message.video.file_id
                        logger.info(f"Successfully obtained new file_id for video {video_data['uuid']}: {new_file_id}")

                        media_collection.update_one(
                            {'uuid': video_data['uuid']},
                            {'$set': {'file_id': new_file_id}}
                        )
                        logger.info(f"Database updated with new file_id for video {video_data['uuid']}.")
                        video_data['file_id'] = new_file_id

                        logger.info(f"Retrying send_video with healed file_id for {video_data['uuid']}.")
                        sent_message = await client.send_video(
                            chat_id,
                            video_data['file_id'],
                            caption=caption_text,
                            reply_markup=reply_markup,
                            protect_content=protect_content_for_user
                        )
                        logger.info(f"Successfully sent video {video_data['uuid']} via send_video after self-healing.")
                    except Exception as heal_e:
                        logger.error(f"Self-healing failed for video {video_data['uuid']}: {heal_e}", exc_info=True)
                        await client.send_message(chat_id, "Oops! This video is unavailable and has been removed. Trying the next one... 🔄")
                        create_tracked_task(delete_broken_video_from_db_and_channel(client, video_data['uuid'], video_data.get('category'), video_data.get('sequence_number'), video_data.get('message_id')))
                        return False, "Video was unavailable and self-healing failed."
                except Exception as e2:
                    logger.error(f"Fallback send_video also failed for {video_data['uuid']}: {e2}. The video might be broken.", exc_info=True)
                    # Check if the error is likely due to the video file itself being missing/invalid
                    broken_video_errors = ["FILE_ID_INVALID", "FILE_REFERENCE_EXPIRED", "MESSAGE_ID_INVALID", "MEDIA_EMPTY"]
                    is_probably_broken = any(err in str(e2) for err in broken_video_errors) or isinstance(e2, (FileIdInvalid, FileReferenceExpired, MessageIdInvalid))

                    # Avoid deleting for markup errors or user-related errors
                    avoid_deletion_errors = ["BUTTON_DATA_INVALID", "REPLY_MARKUP_INVALID", "USER_IS_BLOCKED", "PEER_ID_INVALID", "CHAT_WRITE_FORBIDDEN"]
                    should_avoid = any(err in str(e2) for err in avoid_deletion_errors) or isinstance(e2, (UserIsBlocked, PeerIdInvalid))

                    if is_probably_broken and not should_avoid:
                        await client.send_message(chat_id, "Oops! This video is unavailable and has been removed. Trying the next one... 🔄")
                        create_tracked_task(delete_broken_video_from_db_and_channel(client, video_data['uuid'], video_data.get('category'), video_data.get('sequence_number'), video_data.get('message_id')))
                        return False, "Video was unavailable by all methods."
                    else:
                        return False, f"Failed to send video: {e2}"

    # --- Handle Text Message Sending/Editing ---
    elif new_message_type == "text" and text_content:
        try:
            if not force_new_message and message_id_to_edit_or_delete:
                 sent_message = await client.edit_message_text(chat_id, message_id_to_edit_or_delete, text_content, reply_markup=reply_markup)
            else:
                sent_message = await client.send_message(chat_id, text_content, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Failed to send/edit text message: {e}. Sending new as fallback.")
            try:
                sent_message = await client.send_message(chat_id, text_content, reply_markup=reply_markup)
            except Exception as e2:
                 logger.critical(f"Total failure to send text message: {e2}")
                 return False, "Failed to send message."

    # --- Finalization ---
    if isinstance(sent_message, Message):
        v_uuid = video_data.get('uuid') if video_data else None
        set_active_video_message(chat_id, sent_message.id, chat_id, video_uuid=v_uuid)
        return True, sent_message
    else:
        error_message = "Failed to send or edit the message due to an unexpected error."
        logger.error(error_message)
        return False, error_message


# --- Keyboards ---
async def get_main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    """Main keyboard for the bot."""
    buttons = [
        [KeyboardButton("🎞️ Get Video")],
        [KeyboardButton("👤 Profile"), KeyboardButton("🔖 Saved Videos")]
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def generate_token_earning_keyboard(ad_url: str, is_pending_content: bool = False, user_id: int = None, remove_tutorial: bool = False) -> InlineKeyboardMarkup:
    """Generates the keyboard for token earning options with conditional buttons."""
    buttons = []

    if user_id:
        banked_count = get_banked_tokens_count(user_id)
        if banked_count > 0:
            buttons.append([InlineKeyboardButton(f"🔋 Activate Token (Bank: {banked_count})", callback_data="activate_bank_token")])

    if not SHORTENER_DISABLED:
        buttons.append([InlineKeyboardButton(f"🔓 Unlock {int(config.TOKEN_ACCESS_HOURS)}-Hour Access (Watch Ad)", url=ad_url)])

    if user_id:
        ssrb_link = f"https://t.me/SaveRestrict_Robot?start=verify_for_atdb_{user_id}"
        v_btn_text = "✅ Verify You're Human" if SHORTENER_DISABLED else "🔐 Human Verification"
        buttons.append([InlineKeyboardButton(v_btn_text, url=ssrb_link)])
        buttons.append([InlineKeyboardButton("📤 Upload & Earn", callback_data="upload_btn")])

    vip_text = "⚡ Bypass Verification" if SHORTENER_DISABLED else "💎 Become a VIP (Ad-Free)"
    buttons.append([InlineKeyboardButton(vip_text, url=config.BUY_BOT_URL)])

    if not SHORTENER_DISABLED:
        if not remove_tutorial:
            buttons.append([InlineKeyboardButton(f"📚 {int(config.TOKEN_ACCESS_HOURS)}-Hour Access Tutorial", url=config.TUTORIAL_LINK_2)])
        buttons.append([InlineKeyboardButton("🔗 Refer & Earn", callback_data="refer_and_earn_inline")])

    # Always append the Refresh button when we display the token required/earning screen
    buttons.append([InlineKeyboardButton("🔄 Refresh Status", callback_data="reload_pending_content")])
    return InlineKeyboardMarkup(buttons)

def category_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for selecting video categories, with 3 buttons per row."""
    cats = get_categories()
    if not cats:
        return InlineKeyboardMarkup([[InlineKeyboardButton("😔 No Categories Available", callback_data="no_cat")]])

    buttons = []
    row = []
    for i, cat in enumerate(cats):
        # Changed: Encode category name for callback data
        row.append(InlineKeyboardButton(f"🎬 {html.escape(cat)}", callback_data=f"cat_{str_to_b64(cat)}"))
        if (i + 1) % 3 == 0:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    # Removed "🔖 Saved Videos" from this keyboard as it's now a main menu button
    return InlineKeyboardMarkup(buttons)

def video_nav_keyboard(
    video_uuid: str,
    category: str,
    user_id: int,
    is_saved: bool = False,
    is_batch: bool = False,
    batch_id: str = None,
    batch_index: int = -1,
    is_shared_link: bool = False
) -> InlineKeyboardMarkup:
    """
    Keyboard for navigating videos. Handles regular, saved, batch, and shared video menus.
    """
    buttons = []

    # --- Interaction Row (Like/Dislike) ---
    if not is_saved and not is_batch and not is_shared_link:
        if category == "default (all)":
            dislike_cb = f"dislike_default|{video_uuid}"
            like_cb = f"like_default|{video_uuid}"
        else:
            # Shorten "default (all)" to "def" to save space in callback data
            cat_payload = "def" if category == "default (all)" else str_to_b64(category)
            dislike_cb = f"dislike|{video_uuid}|{cat_payload}|{int(is_saved)}"
            like_cb = f"like|{video_uuid}|{cat_payload}|{int(is_saved)}"

            # TRUNCATION: If still over 64 bytes, we MUST omit category and rely on DB lookup
            if len(dislike_cb) > 64 or len(like_cb) > 64:
                dislike_cb = f"dislike|{video_uuid}|{int(is_saved)}"
                like_cb = f"like|{video_uuid}|{int(is_saved)}"

        buttons.append([
            InlineKeyboardButton("❤️ Like", callback_data=like_cb),
            InlineKeyboardButton("💔 Dislike", callback_data=dislike_cb)
        ])

    # --- Navigation Row (Previous/Next) ---
    if category == "default (all)":
        nav_buttons = [InlineKeyboardButton("⏩ Next Video", callback_data=f"next_default|{video_uuid}")]
        # Disable previous button if there is no history
        if user_id in user_session_history and user_session_history[user_id]['position'] > 0:
            nav_buttons.insert(0, InlineKeyboardButton("⏪ Prev Video", callback_data=f"prev_default|{video_uuid}"))
        buttons.append(nav_buttons)
    elif is_shared_link:
        buttons.append([
            InlineKeyboardButton("⏪ Prev Video", callback_data="shared_nav"),
            InlineKeyboardButton("⏩ Next Video", callback_data="shared_nav")
        ])
    elif is_batch:
        nav_buttons = [InlineKeyboardButton("⏩ Next Video", callback_data=f"next_batch|{batch_id}|{batch_index}")]
        # Disable previous button if there is no history or at start
        if user_id in user_session_history and user_session_history[user_id].get('batch_id') == batch_id and user_session_history[user_id]['position'] > 0:
            nav_buttons.insert(0, InlineKeyboardButton("⏪ Prev Video", callback_data=f"prev_batch|{batch_id}|{batch_index}"))
        buttons.append(nav_buttons)
    else:
        cat_payload = str_to_b64(category)
        prev_cb = f"prev|{video_uuid}|{cat_payload}|{int(is_saved)}"
        next_cb = f"next|{video_uuid}|{cat_payload}|{int(is_saved)}"

        # TRUNCATION: Ensure we stay under Telegram's 64-byte limit
        if len(prev_cb) > 64 or len(next_cb) > 64:
            prev_cb = f"prev|{video_uuid}|{int(is_saved)}"
            next_cb = f"next|{video_uuid}|{int(is_saved)}"

        nav_buttons = [InlineKeyboardButton("⏩ Next Video", callback_data=next_cb)]
        # Disable previous button if there is no history or at start
        if user_id in user_session_history and user_session_history[user_id].get('category') == category and user_session_history[user_id]['position'] > 0:
            nav_buttons.insert(0, InlineKeyboardButton("⏪ Prev Video", callback_data=prev_cb))
        buttons.append(nav_buttons)

    # --- Action Row (Bookmark/Share/Download) ---
    row_2_buttons = []
    if is_saved:
        # For saved videos, the "Bookmark" button is replaced by "Remove"
        row_2_buttons.append(InlineKeyboardButton("🗑️ Unsave", callback_data=f"remove_saved_{video_uuid}"))
    else:
        row_2_buttons.append(InlineKeyboardButton("🔖 Save Video", callback_data=f"bookmark_{video_uuid}"))

    row_2_buttons.append(InlineKeyboardButton("📤 Share", callback_data=f"share_{video_uuid}"))
    row_2_buttons.append(InlineKeyboardButton("📥 Download", callback_data=f"download_{video_uuid}"))
    buttons.append(row_2_buttons)

    # --- Third Row (Context-dependent) ---
    row_3_buttons = []
    if is_batch or is_shared_link:
        row_3_buttons.append(InlineKeyboardButton("👀 Discover More", callback_data="watch_more"))
    elif is_saved:
        row_3_buttons.append(InlineKeyboardButton("🔙 Go Back", callback_data="back_to_saved_cats"))
    else: # Regular navigation
        if category == "default (all)":
            row_3_buttons.append(InlineKeyboardButton("📤 Upload & Earn", callback_data="upload_btn"))
        row_3_buttons.append(InlineKeyboardButton("🗂️ Browse Categories", callback_data="change_cat"))

    if row_3_buttons:
        buttons.append(row_3_buttons)

    return InlineKeyboardMarkup(buttons)

def referral_keyboard(ref_link: str) -> InlineKeyboardMarkup:
    """Keyboard for displaying a referral link."""
    # MODIFIED: Removed the copy button as requested
    return None

def get_premium_only_text() -> str:
    """Returns the text highlighting only premium user benefits."""
    return (
        "✨ <b>Premium User Benefits</b> ✨\n\n"
        "✅ <b>Unlimited Saved Videos</b> — keep as many bookmarks as you like.\n"
        "✅ <b>Direct Video Downloads</b> — instantly get the actual file with no restrictions.\n"
        "✅ <b>No Ad Refresh Needed</b> — enjoy uninterrupted access for your entire premium period.\n"
        "✅ <b>Bookmarks Never Deleted</b> — your saved videos are safe.\n"
        "✅ <b>Priority Content Delivery</b> — faster, reliable downloads so you always get the video.\n\n"
        f"💳 Upgrade for just <b>₹{config.PREMIUM_MONTH_PRICE_INR}/month</b> and enjoy all premium benefits instantly! 🚀"
    )

def buy_token_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for buying tokens."""
    btn_text = "⚡ Bypass Verification" if SHORTENER_DISABLED else "💳 Buy VIP Premium Access"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(btn_text, url=config.BUY_BOT_URL)]
    ])

def saved_category_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """
    Generates an inline keyboard with categories from which the user has saved videos.
    """
    user_doc = users_collection.find_one({'user_id': user_id})
    if not user_doc or not user_doc.get('bookmarked_videos'):
        return InlineKeyboardMarkup([[InlineKeyboardButton("😔 No Saved Videos Yet", callback_data="no_saved_videos")]])

    bookmarked_videos = user_doc['bookmarked_videos']

    # Get unique categories from bookmarked videos
    saved_categories = set()
    for bookmark in bookmarked_videos:
        video_data = get_video_by_uuid(bookmark['uuid'])
        if video_data and video_data.get('category'):
            saved_categories.add(video_data['category'])

    if not saved_categories:
        return InlineKeyboardMarkup([[InlineKeyboardButton("😔 No Valid Saved Videos Yet", callback_data="no_valid_saved_videos")]])

    buttons = []
    row = []
    sorted_categories = sorted(list(saved_categories))
    for i, cat in enumerate(sorted_categories):
        # Changed: Encode category name for callback data
        row.append(InlineKeyboardButton(f"🗂️ {html.escape(cat)}", callback_data=f"view_saved_cat_{str_to_b64(cat)}"))
        if (i + 1) % 2 == 0: # 2 buttons per row for saved categories
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    return InlineKeyboardMarkup(buttons)

# --- Video Sharing ---
async def handle_shared_video(client: Client, user_id: int, video_uuid: str) -> tuple[bool, dict | str]:
    """
    Handles a user attempting to view a video shared via a deep link.
    Returns (success: bool, result: dict | str), where result is video data on success, or an error message on failure.
    """
    logger.info(f"Handling shared video request: user_id={user_id}, video_uuid={video_uuid}")
    video = get_video_by_uuid(video_uuid)
    if not video:
        logger.warning(f"User {user_id} attempted to view non-existent shared video. UUID requested: '{video_uuid}'")
        return False, "Oops, invalid link. Try again! 😔"

    if video.get('banned'):
        logger.warning(f"User {user_id} attempted to view banned video {video_uuid}.")
        return False, "🚫 This content is no longer available."

    return True, video

# --- Token Refresh ---
async def handle_token_refresh(user_id: int, ad_code: str) -> tuple[bool, str]:
    """Handles token refresh requests from users."""
    if SHORTENER_DISABLED:
        return False, "❌ The URL shortener service is currently disabled. Please use other methods to earn tokens. 🚫"
    try:
        if await is_rate_limited(user_id):
            return False, "⚠️ You're refreshing too quickly. Please wait a minute and try again. ⏳"

        if is_premium_user(user_id):
            logger.info(f"User {user_id} attempted token refresh but already has valid premium access.")
            return False, "💡 You already have active premium access. No need to refresh yet! Enjoy the videos! 🥳"

        # Bypass detection logic
        settings = settings_collection.find_one({'_id': 'bot_settings'})
        bypass_limit_seconds = settings.get('bypass_limit_seconds', 0) if settings else 0

        if bypass_limit_seconds > 0:
            log_entry = shortener_logs_collection.find_one({'ad_code': ad_code, 'user_id': user_id})
            if log_entry:
                time_elapsed = (datetime.now(timezone.utc) - log_entry['created_at']).total_seconds()
                if time_elapsed < bypass_limit_seconds:
                    logger.warning(f"Bypass detected for user {user_id}. Time elapsed: {time_elapsed}s, Limit: {bypass_limit_seconds}s")

                    # Invalidate the current token log
                    shortener_logs_collection.delete_one({'ad_code': ad_code})

                    # Generate a new token and link
                    new_ad_code = str_to_b64(f"{user_id}:{get_current_time()}")
                    shortener_logs_collection.insert_one({'ad_code': new_ad_code, 'user_id': user_id, 'created_at': datetime.now(timezone.utc)})
                    long_url = f"https://t.me/{config.BOT_USERNAME[1:]}?start=token_{new_ad_code}"
                    new_ad_url = await get_shortener_config_and_shorten_url(long_url)

                    # Send the bypass message and the new link
                    await bot.send_message(user_id, "Bypass detected! Your access link has been blocked.")
                    await bot.send_message(
                        user_id,
                        "Please try again with this new link:",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔓 Try New Link", url=new_ad_url)]])
                    )
                    return False, "" # Return False and an empty message as the messages have been sent

        decoded = b64_to_str(ad_code)
        if not decoded:
            logger.warning(f"User {user_id} provided invalid base64 for token refresh: {ad_code}")
            return False, "Oops, invalid link. Try again! 🧐"

        try:
            code_user_id_str, timestamp_str = decoded.split(':', 1)
            code_user_id = int(code_user_id_str)
        except ValueError:
            logger.error(f"User {user_id} provided invalid token refresh code format: {ad_code}")
            return False, "Invalid token refresh link format. 🐛"

        if code_user_id != user_id:
            logger.warning(f"User {user_id} attempted to use another user's token refresh link ({code_user_id}).")
            return False, "This Token Is Not For You 😠\n\nor maybe you are using 2 telegram apps, if yes then please uninstall this one and try again."

        if refresh_tokens_used_collection.find_one({'ad_code': ad_code}):
            logger.warning(f"User {user_id} attempted to reuse token refresh link: {ad_code}")
            return False, "This token refresh link has already been used. Please generate a new one. 🔄"

        added_token = add_token(user_id, config.REFRESH_BONUS * config.TOKEN_EXPIRY, is_admin_granted=False)
        if added_token:
            refresh_tokens_used_collection.insert_one({'ad_code': ad_code, 'used_at': datetime.now(timezone.utc)})
            logger.info(f"Token added for user {user_id} via refresh. Token is banked.")
            return True, f"🎉 <b>Success!</b> You got {config.REFRESH_BONUS} token. It has been added to your bank. Activate it whenever you need access! 🏦"
        else:
            return False, "❌ <b>Something went wrong!</b>\nFailed to add token. Please try again later. 🛠️"
    except Exception as e:
        logger.error(f"Token refresh failed for user {user_id}: {e}", exc_info=True)
        return False, "❌ <b>Something went wrong!</b>\nPlease try again later. 🤷‍♀️"

# --- Rate Limiting ---
RATE_LIMIT_WINDOW = 120
RATE_LIMIT_MAX = 60

async def is_rate_limited(user_id: int) -> bool:
    """
    Checks if a user is rate-limited based on their recent requests.
    Stores request timestamps in MongoDB for persistence.
    """
    if is_admin(user_id):
        return False

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(seconds=RATE_LIMIT_WINDOW)

    try:
        # Step 1: Atomically remove old timestamps. This avoids the conflicting operator error.
        tokens_collection.update_one(
            {'user_id': user_id},
            {'$pull': {'rate_limits': {'timestamp': {'$lt': window_start}}}},
            upsert=True
        )

        # Step 2: Atomically add the new timestamp.
        tokens_collection.update_one(
            {'user_id': user_id},
            {'$push': {'rate_limits': {'timestamp': now}}}
        )

        # Step 3: Retrieve the document to check the current count.
        result = tokens_collection.find_one({'user_id': user_id})
        current_requests = len(result.get('rate_limits', [])) if result else 0

        if current_requests > RATE_LIMIT_MAX:
            logger.warning(f"User {user_id} is rate limited. Current requests: {current_requests}, Max: {RATE_LIMIT_MAX}")
            return True
        return False
    except Exception as e:
        logger.error(f"Error in is_rate_limited for user {user_id}: {e}", exc_info=True)
        return False

# --- Error Handling ---
async def handle_error(client: Client, message: Message, error: Exception):
    """Generic error handler for bot commands."""
    if isinstance(error, FloodWait):
        logger.warning(f"FloodWait: {error.value} seconds for user {message.from_user.id}")
        await message.reply_text(f"⚠️ <b>Too Many Requests!</b>\nPlease wait <b>{error.value}</b> seconds before trying again. ⏳")
    else:
        logger.error(f"An unexpected error occurred for user {message.from_user.id}: {error}", exc_info=True)
        await message.reply_text(f"❌ <b>An unexpected error occurred.</b>\nPlease try again later. 🥺")

@app.get("/")
@app.head("/")
async def health_check_fastapi():
    """Simple health check endpoint for Render."""
    return Response(status_code=200, content="OK")


# --- Handlers ---
@bot.on_message(filters.command("upload") & filters.private)
async def upload_cmd(client: Client, message: Message):
    """Handles the /upload command for users to contribute videos."""
    user_id = message.from_user.id

    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    instructions = (
        "📤 <b>Contribute & Earn!</b> 🌶️\n\n"
        "Share your videos to earn exclusive access tokens! 🎁\n\n"
        "<b>Steps:</b>\n"
        "1. Tap '📤 Send Video Now' below to pick a category.\n"
        "2. Send your video(s) directly to this chat.\n"
        "3. Type /done when finished.\n\n"
        f"⚡ <b>Instant Reward:</b> You get <b>{UPLOAD_CONFIG['temp_scrolls_amount']} scrolls</b> immediately for each upload! ⏳"
    )

    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Send Video Now", callback_data="upl_start_cat")]
    ])

    await message.reply(instructions, reply_markup=reply_markup)

@bot.on_callback_query(filters.regex(r"^upload_btn$"))
async def upload_btn_callback(client: Client, callback_query: CallbackQuery):
    """Handles the 'Upload and Earn' button from the video menu."""
    user_id = callback_query.from_user.id

    if not await check_membership(client, user_id):
        await callback_query.answer("You must join our channels first!", show_alert=True)
        await send_force_subscribe_message(client, user_id)
        return

    instructions = (
        "📤 <b>Contribute & Earn!</b> 🌶️\n\n"
        "Share your videos to earn exclusive access tokens! 🎁\n\n"
        "<b>Steps:</b>\n"
        "1. Tap '📤 Send Video Now' below to pick a category.\n"
        "2. Send your video(s) directly to this chat.\n"
        "3. Type /done when finished.\n\n"
        f"⚡ <b>Instant Reward:</b> You get <b>{UPLOAD_CONFIG['temp_scrolls_amount']} scrolls</b> immediately for each upload! ⏳"
    )

    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Send Video Now", callback_data="upl_start_cat")]
    ])

    await callback_query.message.reply(instructions, reply_markup=reply_markup)
    await callback_query.answer()

@bot.on_callback_query(filters.regex(r"^activate_bank_token$"))
async def activate_bank_token_callback(client: Client, callback_query: CallbackQuery):
    """Handles the manual activation of a banked token."""
    user_id = callback_query.from_user.id
    success, message = await activate_bank_token(user_id)

    if success:
        await callback_query.answer(message, show_alert=True)
        # Refresh the keyboard to reflect updated bank count or remove the button
        ad_code = str_to_b64(f"{user_id}:{get_current_time()}")
        long_url = f"https://t.me/{config.BOT_USERNAME[1:]}?start=token_{ad_code}"
        ad_url = await get_shortener_config_and_shorten_url(long_url) if not SHORTENER_DISABLED else ""

        # Check if we should use the "pending content" version of the keyboard
        is_pending = "Access Token Required" in callback_query.message.text or "Almost there" in callback_query.message.text

        await callback_query.message.edit_reply_markup(
            reply_markup=generate_token_earning_keyboard(ad_url, is_pending_content=is_pending, user_id=user_id)
        )
    else:
        await callback_query.answer(message, show_alert=True)

@bot.on_callback_query(filters.regex(r"^upl_start_cat$"))
async def upload_start_category_callback(client: Client, callback_query: CallbackQuery):
    """Prompt user to select a category before uploading."""
    user_id = callback_query.from_user.id
    categories = get_categories(for_admin_use=True)
    if not categories:
        await callback_query.answer("😔 No categories available for upload at the moment.", show_alert=True)
        return

    buttons = []
    row = []
    for i, cat in enumerate(categories):
        row.append(InlineKeyboardButton(f"🗂️ {cat}", callback_data=f"upl_cat_{str_to_b64(cat)}"))
        if (i + 1) % 2 == 0:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    await callback_query.message.edit_text("🎬 **Select a Category for your Upload:**", reply_markup=InlineKeyboardMarkup(buttons))
    await callback_query.answer()

@bot.on_callback_query(filters.regex(r"^upl_cat_(.+)$"))
async def upload_category_selection_callback(client: Client, callback_query: CallbackQuery):
    """Handles category selection for the /upload command."""
    user_id = callback_query.from_user.id
    category = b64_to_str(callback_query.data[8:])

    user_upload_state[user_id]['in_upload_mode'] = True
    user_upload_state[user_id]['session_uploads'] = 0
    user_upload_state[user_id]['selected_category'] = category

    await callback_query.message.edit_text(
        f"✅ **Category selected:** `{category}`\n\n"
        "📤 **Now, send your video(s) directly here!**\n"
        "I will process them one by one. Type /done when finished. ✨"
    )
    await callback_query.answer(f"Category set to {category}")

@bot.on_message(filters.command("myuploads") & filters.private)
async def my_uploads_cmd(client: Client, message: Message):
    """Shows the user their pending uploads."""
    user_id = message.from_user.id
    pending = list(pending_uploads_collection.find({"user_id": user_id, "status": "pending"}).sort("submitted_at", DESCENDING))

    if not pending:
        await message.reply("You have no pending uploads at the moment. ❤️")
        return

    text = f"📝 **Your Pending Uploads ({len(pending)})**\n\n"
    for i, up in enumerate(pending[:10]):
        text += f"{i+1}. Uploaded on {up['submitted_at'].strftime('%Y-%m-%d %H:%M')} - `Pending` ⏳\n"

    if len(pending) > 10:
        text += f"\n...and {len(pending)-10} more."

    await message.reply(text)

@bot.on_callback_query(filters.regex(r"^send_video_prompt$"))
async def send_video_prompt_callback(client: Client, callback_query: CallbackQuery):
    """Answers the prompt button for uploading."""
    await callback_query.answer("📤 Send your video(s) directly here! I'm waiting...", show_alert=True)

@bot.on_message(filters.command("start") & filters.private)
async def start_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    first_name_safe = html.escape(message.from_user.first_name) if message.from_user.first_name else "there"

    try:
        args = message.text.split()
        deep_link_arg = args[1] if len(args) > 1 else None

        # --- Step 1: Handle new user registration and token grant immediately ---
        user = users_collection.find_one({'user_id': user_id})
        is_new_user = not user
        if is_new_user:
            username_safe = html.escape(message.from_user.username) if message.from_user.username else ""
            users_collection.insert_one({
                'user_id': user_id, 'username': username_safe, 'first_name': first_name_safe,
                'last_name': html.escape(message.from_user.last_name) if message.from_user.last_name else None,
                'joined_date': datetime.now(timezone.utc), 'referral_count': 0, 'bookmarked_videos': [],
                'last_premium_check_status': False, 'last_viewed_per_category': {}, 'pending_command': None,
                'new_user_scrolls_used': 0, 'has_claimed_special_token': False,
                'has_seen_free_scroll_popup': False,
                'free_scroll_usage': {'count': 0, 'reset_at': datetime.now(timezone.utc) + timedelta(hours=config.FREE_SCROLL_RESET_HOURS)},
                'free_batch_usage': {'claimed_batches': [], 'reset_at': datetime.now(timezone.utc) + timedelta(hours=config.FREE_LIMIT_RESET_HOURS)},
                'free_video_usage': {'count': 0, 'reset_at': datetime.now(timezone.utc) + timedelta(hours=config.FREE_VIDEO_RESET_HOURS)},
                'temp_scrolls': [],
                'permanent_scrolls': 0,
                'upload_stats': {
                    'total_uploads': 0,
                    'pending_count': 0,
                    'approved_count': 0,
                    'daily_uploads': {'count': 0, 'reset_at': datetime.now(timezone.utc) + timedelta(hours=24)}
                }
            })
            logger.info(f"New user registered: {user_id} and received {config.NEW_USER_SCROLLS} free scrolls.")

            # Handle referral for the newly created user
            if deep_link_arg:
                referrer_id = handle_referral(user_id, deep_link_arg)
                if referrer_id:
                    try:
                        await client.send_message(
                            referrer_id,
                            f"🎉 <b>Referral Bonus!</b> Your friend, {first_name_safe}, joined! You've received {config.REFERRAL_BONUS} token. 🤩"
                        )
                    except Exception as e:
                        logger.warning(f"Failed to notify referrer {referrer_id}: {e}")

                    # Check and grant any unlocked milestone rewards
                    create_tracked_task(check_and_grant_referral_milestones(client, referrer_id))

        # --- Step 2: Check channel membership for ALL users ---
        has_joined = await check_membership(client, user_id)
        if not has_joined:
            if deep_link_arg:
                # User doc now exists for new users, so this is just an update
                users_collection.update_one({'user_id': user_id}, {'$set': {'pending_command': deep_link_arg}})

            # Prepare custom force-sub message based on user state
            custom_text = None
            if is_new_user:
                part1 = f"✨ <b>Welcome {first_name_safe} to our Spicy Collection!</b> 🌶️\n\n"
                part2 = (
                    "To watch the video you requested, you just need to join our updates channels first.\n\n"
                    "Once joined, tap the <b>🔄 Try Again</b> button below and I will immediately deliver your video! 🚀"
                ) if deep_link_arg else (
                    "Please join our updates channels below to access the ultimate video library.\n\n"
                    "Once you join, tap the <b>🔄 Try Again</b> button to unlock everything! 🚀"
                )
                custom_text = part1 + part2

            await send_force_subscribe_message(client, user_id, custom_text=custom_text)
            return

        # --- Step 3: User has joined. Handle the request. ---
        if await is_rate_limited(user_id):
            raise FloodWait(10)
        create_tracked_task(check_premium_status_and_notify(client, user_id))

        # Handle deep links first
        if deep_link_arg:
            # NEW: Delete existing active menu to ensure only one is active
            if user_id in active_video_message:
                try:
                    old_menu = active_video_message[user_id]
                    await client.delete_messages(old_menu['chat_id'], old_menu['message_id'])
                except Exception:
                    pass
                clear_active_video_message(user_id)

            loading_msg = await message.reply("Loading your request, please wait...")
            try:
                deep_link_type, deep_link_data = None, None
                if deep_link_arg.startswith('token_'):
                    deep_link_type, deep_link_data = 'token_refresh', deep_link_arg[6:]
                elif deep_link_arg.startswith('video_'):
                    # Handle formats like video_UUID or video_UUID_REFERRERID
                    video_payload = deep_link_arg[6:]
                    if '_' in video_payload:
                        # The payload is UUID_REFERRERID or just UUID
                        # Use rsplit to correctly handle UUIDs that might contain underscores
                        p = video_payload.rsplit('_', 1)
                        if p[1].isdigit() or (p[1].startswith('-') and p[1][1:].isdigit()):
                            deep_link_data = p[0]
                        else:
                            deep_link_data = video_payload
                    else:
                        deep_link_data = video_payload
                    deep_link_type = 'video_share'
                elif deep_link_arg.startswith('ref_'): # Referral was already handled for new users
                    pass
                elif deep_link_arg.startswith('batch_'):
                    deep_link_type, deep_link_data = 'batch', deep_link_arg[6:]
                elif deep_link_arg == 'getvideo':
                    deep_link_type = 'getvideo'

                if deep_link_type == 'token_refresh':
                    success, msg = await handle_token_refresh(user_id, deep_link_data)
                    await message.reply(msg)
                    # After successful token refresh, check for pending command
                    user_doc = users_collection.find_one_and_update(
                        {'user_id': user_id},
                        {'$unset': {'pending_command': ""}},
                        return_document=ReturnDocument.BEFORE
                    )
                    pending_command = user_doc.get('pending_command') if user_doc else None
                    if pending_command:
                        await message.reply("✅ Token received! Loading your content now...")
                        mock_message = message
                        mock_message.text = f"/start {pending_command}"
                        create_tracked_task(start_cmd(client, mock_message))

                elif deep_link_type == 'video_share':
                    if not has_free_video_access(user_id):
                        users_collection.update_one({'user_id': user_id}, {'$set': {'pending_command': deep_link_arg}})
                        await send_token_earning_options(client, message, is_pending_content=True)
                        return
                    success, result = await handle_shared_video(client, user_id, deep_link_data)
                    if not success:
                        await message.reply(result)
                    else:
                        video = result
                        sent_success, _ = await send_and_replace_message(
                            client, message.chat.id, message.id, "video", video_data=video,
                            reply_markup=video_nav_keyboard(video['uuid'], video['category'], user_id, is_shared_link=True),
                            force_new_message=True
                        )
                        if sent_success:
                            if not user_can_access_video(user_id):
                                mark_free_video_used(user_id)
                            save_history(user_id, video['uuid'], video['category'])
                            await client.send_message(
                                message.chat.id,
                                "🍿 <b>Enjoying the video?</b>\n\n"
                                "✨ Tap <b>'👀 Watch More'</b> below or choose from the keyboard to browse unlimited spicy content instantly without waiting for links! 🚀",
                                reply_markup=await get_main_keyboard(user_id)
                            )

                elif deep_link_type == 'batch':
                    batch_doc = video_batches_collection.find_one({'batch_id': deep_link_data})
                    if not batch_doc or not batch_doc.get('video_uuids'):
                        await message.reply("This batch link is invalid or has expired.😔")
                    else:
                        video = get_video_by_uuid(batch_doc['video_uuids'][0])
                        if not video:
                            await message.reply("The first video in this batch is unavailable.😔")
                        else:
                            sent_success, _ = await send_and_replace_message(
                                client, message.chat.id, message.id, "video", video_data=video,
                                reply_markup=video_nav_keyboard(video['uuid'], video['category'], user_id, is_batch=True, batch_id=deep_link_data, batch_index=0),
                                force_new_message=True, is_batch=True, batch_id=deep_link_data, batch_index=0
                            )
                            if sent_success:
                                user_session_history[user_id] = {'category': video['category'], 'videos': [video['uuid']], 'position': 0, 'is_get_video': False, 'batch_id': deep_link_data}
                                await client.send_message(
                                    message.chat.id,
                                    "🍿 <b>Enjoying the video?</b>\n\n"
                                    "✨ Tap <b>'👀 Watch More'</b> below or choose from the keyboard to browse unlimited spicy content instantly without waiting for links! 🚀",
                                    reply_markup=await get_main_keyboard(user_id)
                                )

                elif deep_link_type == 'getvideo':
                    if not has_free_video_access(user_id, limit=2):
                        await send_access_limit_reached_message(client, user_id)
                        return
                    video = get_random_video()
                    if not video:
                        await message.reply("😔 No videos available at the moment. Please ask an admin to add some! 🛠️")
                    else:
                        sent_success, _ = await send_and_replace_message(
                            client, message.chat.id, message.id, "video", video_data=video,
                            reply_markup=video_nav_keyboard(video['uuid'], "default (all)", user_id),
                            force_new_message=True
                        )
                        if sent_success:
                            mark_free_video_used(user_id)
                            user_session_history[user_id] = {'videos': [video['uuid']], 'position': 0, 'is_get_video': True}
                            save_history(user_id, video['uuid'], "default (all)")
                            await client.send_message(
                                message.chat.id,
                                "🍿 <b>Enjoying the video?</b>\n\n"
                                "✨ Tap <b>'👀 Watch More'</b> below or choose from the keyboard to browse unlimited spicy content instantly without waiting for links! 🚀",
                                reply_markup=await get_main_keyboard(user_id)
                            )
            finally:
                if loading_msg: await loading_msg.delete()
        elif is_new_user: # New user, already joined, no deep link
            welcome_inline_keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🎞️ Get Video", callback_data="get_default_video"),
                    InlineKeyboardButton("📤 Upload & Earn", callback_data="upload_btn")
                ]
            ])
            await message.reply(
                f"🎉 <b>Welcome {first_name_safe} to our Spicy Collection!</b> 🌶️\n\n"
                f"You have unlocked exclusive access to our premium library. Enjoy unlimited content on demand! ✨\n\n"
                f"👉 <b>Tap '🎞️ Get Video' below</b> to instantly launch a random video or browse by categories! 🚀",
                reply_markup=welcome_inline_keyboard
            )
            # Send small follow-up message to initialize the custom main reply keyboard
            await client.send_message(
                message.chat.id,
                "✨",
                reply_markup=await get_main_keyboard(user_id)
            )
        else: # Existing user, no deep link
            welcome_inline_keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🎞️ Get Video", callback_data="get_default_video"),
                    InlineKeyboardButton("📤 Upload & Earn", callback_data="upload_btn")
                ]
            ])
            await message.reply(
                f"👋 <b>Welcome back, {first_name_safe}!</b> 🌶️\n\n"
                f"Ready for your next watch? Tap <b>'🎞️ Get Video'</b> below to start exploring your favorites! 🍿",
                reply_markup=welcome_inline_keyboard
            )
            # Send small follow-up message to initialize the custom main reply keyboard
            await client.send_message(
                message.chat.id,
                "✨",
                reply_markup=await get_main_keyboard(user_id)
            )

    except FloodWait as e:
        await handle_error(client, message, e)
    except Exception as e:
        logger.error(f"User {user_id} encountered an unexpected error in start command: {e}", exc_info=True)
        await handle_error(client, message, e)

@bot.on_callback_query(filters.regex(r"^check_join_status$"))
async def check_join_status_callback(client: Client, callback_query: CallbackQuery):
    """Handles the 'Try Again' button after a user is prompted to join channels."""
    user_id = callback_query.from_user.id
    if await check_membership(client, user_id):
        await callback_query.answer("✅ Thank you for joining! Processing your request...", show_alert=False)

        user_doc = users_collection.find_one_and_update(
            {'user_id': user_id},
            {'$unset': {'pending_command': ""}},
            return_document=ReturnDocument.BEFORE
        )

        pending_command = user_doc.get('pending_command') if user_doc else None

        try:
            await callback_query.message.delete()
        except Exception as e:
            logger.warning(f"Could not delete join message for user {user_id}: {e}")

        # Re-trigger the start command to handle deep links or show the welcome message
        mock_message = callback_query.message
        mock_message.text = f"/start {pending_command}" if pending_command else "/start"
        mock_message.from_user = callback_query.from_user
        create_tracked_task(start_cmd(client, mock_message))
    else:
        await callback_query.answer("⚠️ You still need to join all channels to proceed.", show_alert=True)

@bot.on_callback_query(filters.regex(r"^reload_pending_content$"))
async def reload_pending_content_callback(client: Client, callback_query: CallbackQuery):
    """Handles the 'Refresh' button to reload content after getting a token."""
    user_id = callback_query.from_user.id

    if not await check_membership(client, user_id):
        await callback_query.answer("You must join our channels first!", show_alert=True)
        await send_force_subscribe_message(client, user_id)
        return

    if not user_can_access_video(user_id):
        ad_code = str_to_b64(f"{user_id}:{get_current_time()}")
        shortener_logs_collection.insert_one({'ad_code': ad_code, 'user_id': user_id, 'created_at': datetime.now(timezone.utc)})
        long_url = f"https://t.me/{config.BOT_USERNAME[1:]}?start=token_{ad_code}"
        ad_url = await get_shortener_config_and_shorten_url(long_url) if not SHORTENER_DISABLED else ""

        info_text = (
            "💡 Information \n\n"
            " Here's how to get your token! 🚀 \n\n"
            " Hey 💕 unlimited money hack, \n\n"
            " Your Ads token is expired. Please refresh your token by clicking the button below and try again. 👇 \n\n"
            " Token Timeout: 24 hours ⏰ \n\n"
            " What is a token? \n\n"
            " This is an ads token. If you pass 1 ad, you can use the bot for 24 hours after passing the ad. It's that simple! ✨ \n\n"
            " ‼️ APPLE/IPHONE USERS: Copy the token link and open it in a Chrome browser for best experience. 🍎"
        )
        reply_markup = generate_token_earning_keyboard(ad_url, is_pending_content=True, user_id=user_id, remove_tutorial=True)

        await callback_query.message.reply(
            info_text,
            reply_markup=reply_markup,
            disable_web_page_preview=True
        )
        await callback_query.answer()
        return

    user_doc = users_collection.find_one_and_update(
        {'user_id': user_id},
        {'$unset': {'pending_command': ""}},
        return_document=ReturnDocument.BEFORE
    )
    pending_command = user_doc.get('pending_command') if user_doc else None

    if not pending_command:
        await callback_query.answer("Nothing to reload. You can browse using the menu.", show_alert=True)
        return

    await callback_query.answer("Loading your content...")
    try:
        await callback_query.message.delete()
    except Exception as e:
        logger.warning(f"Could not delete 'reload' message for user {user_id}: {e}")

    mock_message = callback_query.message
    mock_message.text = f"/start {pending_command}"
    mock_message.from_user = callback_query.from_user
    create_tracked_task(start_cmd(client, mock_message))

@bot.on_callback_query(filters.regex(r"^shared_nav$"))
async def shared_nav_callback(client: Client, callback_query: CallbackQuery):
    """Handles navigation for single shared videos."""
    await callback_query.answer(
        "✨ You've watched all the videos from this menu! ✨\n\n"
        "To watch more videos like this, click 'Watch More'.",
        show_alert=True
    )

@bot.on_callback_query(filters.regex(r"^watch_more$"))
async def watch_more_callback(client: Client, callback_query: CallbackQuery):
    """Handles the 'Watch More' button to show a random video from the default category."""
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id
    logger.info(f"User {user_id} clicked 'Watch More'.")

    try:
        await callback_query.answer()
        await callback_query.message.delete()
        clear_active_video_message(user_id)

        if not await check_membership(client, user_id):
            await send_force_subscribe_message(client, user_id)
            return

        create_tracked_task(check_premium_status_and_notify(client, user_id))

        if await is_rate_limited(user_id):
            await client.send_message(chat_id, "⚠️ You're clicking too fast! Please wait a moment. ⏳")
            logger.warning(f"User {user_id} hit rate limit in watch_more_callback.")
            return

        users_collection.update_one({'user_id': user_id}, {'$set': {'has_seen_free_scroll_popup': False}})

        if not has_free_video_access(user_id, limit=2):
            await callback_query.answer("Human verification required! 🔐", show_alert=True)
            await send_token_earning_options(client, callback_query.message)
            return

        wait_msg = await client.send_message(chat_id, "Just a moment...")

        video = get_random_video()

        await wait_msg.delete()

        if not video:
            await client.send_message(chat_id, "😔 No videos available at the moment. Please ask an admin to add some! 🛠️")
            logger.warning(f"No videos found in database for user {user_id} on Watch More.")
            return

        sent_success, sent_message_or_error = await send_and_replace_message(
            client,
            chat_id,
            message_id_to_edit_or_delete=None,
            new_message_type="video",
            video_data=video,
            reply_markup=video_nav_keyboard(video['uuid'], "default (all)", user_id),
            force_new_message=True
        )

        if sent_success:
            mark_free_video_used(user_id)
            user_session_history[user_id] = {'videos': [video['uuid']], 'position': 0, 'is_get_video': True}
            save_history(user_id, video['uuid'], "default (all)")
        else:
            await client.send_message(chat_id, sent_message_or_error)
            logger.error(f"User {user_id} failed to send default video from Watch More: {sent_message_or_error}")

    except Exception as e:
        logger.error(f"Error in watch_more_callback for user {user_id}: {e}", exc_info=True)
        try:
            await client.send_message(chat_id, "An error occurred. Please try again!")
        except Exception:
            pass

@bot.on_message(filters.command("help") & filters.private)
async def help_cmd(client: Client, message: Message):
    """Handles the /help command."""
    user_id = message.from_user.id
    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    user_mention_safe = html.escape(message.from_user.first_name) if message.from_user.first_name else "there"
    create_tracked_task(check_premium_status_and_notify(client, user_id))

    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Support", url=config.BUY_BOT_URL)]
    ])

    await message.reply(
        f"👋 <b>Hey {user_mention_safe}! Here's how to use the bot:</b> 📚\n\n"
        f"• <b>🎞️ Get Video</b>: Browse, watch, and discover premium spicy content on-demand.\n"
        f"• <b>👤 Profile</b>: Check your status, session tokens, scrolls remaining, and referrals.\n"
        f"• <b>🔖 Saved Videos</b>: View or manage your personalized bookmark collection.\n\n"
        f"💡 <i>Have any issues or questions? Click below to contact our support team. Enjoy! 🌶️</i>",
        reply_markup=reply_markup
    )

@bot.on_message(filters.command("helpadmin") & filters.private & admin_only)
async def help_admin_cmd(client: Client, message: Message):
    """Admin command to list all admin-only commands."""
    help_text = (
        "🛠️ **Admin Help Menu** 🛠️\n\n"
        "**User Management:**\n"
        "- /addpremium <id> <days>: Grant premium\n"
        "- /removepremium <id>: Revoke access\n"
        "- /deleteuser <id>: Wipe user data\n"
        "- /viewtoken: Token leaderboard\n"
        "- /showuserscrolls: Scrolls leaderboard\n\n"
        "**Content Management:**\n"
        "- /addcategory <name>: Create category\n"
        "- /deletecategory: Remove category\n"
        "- /categoryrename: Rename category\n"
        "- /batchadd: Continuous video upload\n"
        "- /deletevideo: Interactive deletion\n"
        "- /batchvideoadd: Create shareable batch\n\n"
        "**Bot Configuration:**\n"
        "- /configupload: Manage rewards/limits\n"
        "- /setdata: Set video storage channel\n"
        "- /setfsub: Manage join-to-use channels\n"
        "- /setreviewchat: Set upload review group\n"
        "- /setshortener: Configure URL shortener\n"
        "- /bypass_limit <sec>: Shortener anti-cheat\n"
        "- /turnoff_shortener / /turnon_shortener\n\n"
        "**Utility & Stats:**\n"
        "- /broadcast (reply): Global broadcast\n"
        "- /stats: General bot stats\n"
        "- /token_stats: Shortener usage stats\n"
        "- /toggle_auto_delete / /toggle_protect\n"
        "- /stop / /done: End active admin modes\n"
    )

    if is_owner(message.from_user.id):
        help_text += (
            "\n**Owner Commands:**\n"
            "- /addadmin <id>: Promote user\n"
            "- /removeadmin: Demote user\n"
        )

    await message.reply(help_text)

@bot.on_message(filters.command("profile") & filters.private)
async def profile_cmd(client: Client, message: Message):
    """Handles the /profile command to show user statistics."""
    user_id = message.from_user.id
    logger.info(f"User {user_id} requested profile.")

    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    create_tracked_task(check_premium_status_and_notify(client, user_id))

    if await is_rate_limited(user_id):
        await handle_error(client, message, FloodWait(10))
        logger.warning(f"User {user_id} hit rate limit in profile_cmd.")
        return

    try:
        user = users_collection.find_one({'user_id': user_id})
        if not user:
            logger.warning(f"Profile requested for non-existent user {user_id}. Attempting to re-initialize.")
            users_collection.insert_one({
                'user_id': user_id,
                'username': html.escape(message.from_user.username) if message.from_user.username else "",
                'first_name': html.escape(message.from_user.first_name) if message.from_user.first_name else "User",
                'last_name': html.escape(message.from_user.last_name) if message.from_user.last_name else None,
                'joined_date': datetime.now(timezone.utc),
                'referral_count': 0,
                'bookmarked_videos': [],
                'last_premium_check_status': False,
                'last_viewed_per_category': {},
                'pending_command': None
            })
            user = users_collection.find_one({'user_id': user_id})
            if not user:
                raise Exception("Failed to create or retrieve user document for profile.")


        tokens_doc = tokens_collection.find_one({'user_id': user_id})

        tokens_count = 0
        banked_tokens = 0
        if tokens_doc and 'tokens' in tokens_doc:
            now = datetime.now(timezone.utc)
            tokens_count = sum(1 for token in tokens_doc['tokens'] if token.get('is_activated', True) and token.get('expires_at') and token['expires_at'] > now)
            banked_tokens = sum(1 for token in tokens_doc['tokens'] if not token.get('is_activated', False))

        referral_count = user.get('referral_count', 0)
        bookmarked_videos = user.get('bookmarked_videos', [])

        # Calculate total scrolls
        now = datetime.now(timezone.utc)
        permanent_scrolls = user.get('permanent_scrolls', 0)
        temp_scrolls = user.get('temp_scrolls', [])
        valid_temp_scrolls_count = sum(s.get('amount', 0) for s in temp_scrolls if s.get('amount', 0) > 0 and (s.get('expires_at') is None or s['expires_at'] > now))
        total_scrolls = permanent_scrolls + valid_temp_scrolls_count

        is_premium = is_premium_user(user_id)
        user_status = "💎 Premium User" if is_premium else "✨ Free User"

        if is_premium:
            save_limit_display = f"{len(bookmarked_videos)} / Unlimited"
        else:
            save_limit_display = f"{len(bookmarked_videos)} / {config.FREE_USER_SAVE_LIMIT}"

        ref_link = f"https://t.me/{config.BOT_USERNAME[1:]}?start=ref_{user_id}"

        # Determine next milestone
        milestone_tiers = [5, 10, 20, 50]
        next_milestone = "All Milestone Rewards Unlocked! 🏆"
        for m in milestone_tiers:
            if referral_count < m:
                next_milestone = f"<code>{referral_count}/{m}</code> for next Milestone reward! 🎁"
                break

        profile_text = (
            f"👤 <b>USER PROFILE</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👑 <b>Status:</b> {user_status}\n"
            f"🪙 <b>Active Session Tokens:</b> <code>{tokens_count}</code>\n"
            f"🏦 <b>Banked Tokens:</b> <code>{banked_tokens}</code>\n"
            f"📜 <b>Remaining Scrolls:</b> <code>{total_scrolls}</code>\n"
            f"🔖 <b>Saved Videos:</b> <code>{save_limit_display}</code>\n"
            f"👥 <b>Total Referrals:</b> <code>{referral_count}</code>\n"
            f"🏆 <b>Milestones:</b> {next_milestone}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 <b>Your Referral Link:</b>\n"
            f"<code>{html.escape(ref_link)}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🎁 <i>Milestone Rewards:</i>\n"
            f"• 5 Referrals: 1 Day Premium 💎\n"
            f"• 10 Referrals: 3 Days Premium 💎\n"
            f"• 20 Referrals: 7 Days Premium 💎\n"
            f"• 50 Referrals: 30 Days Premium 💎\n\n"
            f"🎁 <i>Share your link with friends to earn additional tokens and scrolls automatically!</i>"
        )

        await message.reply(profile_text, reply_markup=await get_main_keyboard(user_id))
        logger.info(f"User {user_id}: Profile sent successfully.")
    except Exception as e:
        logger.error(f"User {user_id} failed to send profile: {e}", exc_info=True)
        await handle_error(client, message, e)


@bot.on_message(filters.regex("^🎞️ Get Video$") & filters.private)
async def get_video(client: Client, message: Message):
    """
    Handles the 'Get Video' button request by immediately showing a random video.
    """
    user_id = message.from_user.id
    chat_id = message.chat.id
    logger.info(f"User {user_id} requested Get Video.")

    # Delete existing active menu if one is already active to ensure only one is active at a time
    if user_id in active_video_message:
        try:
            old_menu = active_video_message[user_id]
            await client.delete_messages(old_menu['chat_id'], old_menu['message_id'])
        except Exception:
            pass
        clear_active_video_message(user_id)

    # Ensure user is a member of required channels
    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    create_tracked_task(check_premium_status_and_notify(client, user_id))

    # Check for rate limiting
    if await is_rate_limited(user_id):
        await handle_error(client, message, FloodWait(10))
        logger.warning(f"User {user_id} hit rate limit in get_video.")
        return

    wait_msg = await message.reply("Just a moment...")

    # Fetch a random video
    if not has_free_video_access(user_id, limit=2):
        await wait_msg.delete()
        await send_access_limit_reached_message(client, user_id)
        return

    video = get_random_video()

    await wait_msg.delete()

    if not video:
        await message.reply("😔 No videos available at the moment. Please ask an admin to add some! 🛠️")
        logger.warning(f"No videos found in database for user {user_id} on Get Video.")
        return

    # Send the video to the user
    sent_success, sent_message_or_error = await send_and_replace_message(
        client,
        chat_id,
        message_id_to_edit_or_delete=message.id,
        new_message_type="video",
        video_data=video,
        reply_markup=video_nav_keyboard(video['uuid'], "default (all)", user_id),
        force_new_message=True
    )

    if sent_success:
        mark_free_video_used(user_id)
        # Initialize history for "default (all)" category navigation
        user_session_history[user_id] = {'videos': [video['uuid']], 'position': 0, 'is_get_video': True}
        save_history(user_id, video['uuid'], "default (all)")
    else:
        # Attempt to notify user of the failure
        try:
            await message.reply(sent_message_or_error)
        except RPCError as e:
            logger.error(f"Could not reply to original message after send_and_replace_message failed: {e}")
            await client.send_message(chat_id, sent_message_or_error)
        logger.error(f"User {user_id} failed to send default video: {sent_message_or_error}")

@bot.on_callback_query(filters.regex(r"^cat_(.+)$"))
async def select_category(client: Client, callback_query: CallbackQuery):
    """Handles category selection callback (for main categories)."""
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id
    # Changed: Decode category name from callback data
    category_name = b64_to_str(callback_query.data[4:])
    logger.info(f"User {user_id} selected category: {category_name}.")

    if not await check_membership(client, user_id):
        await callback_query.answer("You must join our channel first!", show_alert=True)
        await send_force_subscribe_message(client, user_id)
        return

    create_tracked_task(check_premium_status_and_notify(client, user_id))

    if not has_free_video_access(user_id, limit=1):
        await callback_query.answer("Human verification required! 🔐", show_alert=True)
        await send_token_earning_options(client, callback_query.message)
        return

    if await is_rate_limited(user_id):
        await callback_query.answer("⚠️ Too many category changes. Wait 1 min. ⏳", show_alert=True)
        logger.warning(f"User {user_id} hit rate limit in select_category.")
        return

    current_active_tracked_message = active_video_message.get(user_id)
    if current_active_tracked_message and \
       current_active_tracked_message.get('message_id') == callback_query.message.id and \
       datetime.now(timezone.utc) - current_active_tracked_message.get('timestamp', datetime.min.replace(tzinfo=timezone.utc)) > timedelta(minutes=config.MENU_EXPIRY_MINUTES):

        logger.warning(f"User {user_id} tried to select category but menu expired. Callback Message ID: {callback_query.message.id}, Active Menu ID: {current_active_tracked_message.get('message_id')}")
        await callback_query.answer("Menu expired. Click '🎞️ Get Video' to restart. ⏰", show_alert=True)
        try:
            await client.delete_messages(callback_query.message.chat.id, callback_query.message.id)
        except MessageIdInvalid:
            pass
        except Exception as e:
            logger.warning(f"Failed to delete expired menu message for user {user_id}: {e}")
        clear_active_video_message(user_id)
        await client.send_message(chat_id, "Your menu has expired. Please click '🎞️ Get Video' to get a new one. ⏰")
        return

    if current_active_tracked_message and current_active_tracked_message.get('message_id') != callback_query.message.id:
        logger.warning(f"User {user_id} clicked old menu button. Callback Message ID: {callback_query.message.id}, Active Menu ID: {current_active_tracked_message.get('message_id')}")
        await callback_query.answer("This menu is outdated. Please use the latest one. 🔄", show_alert=True)
        # No need to delete message here, it will be handled by cleanup_expired_menus or next send_and_replace_message
        return

    # Send "Please wait" message before fetching video/menu
    temp_msg = await client.send_message(chat_id, "⏳ Please wait, almost done... ✨")

    if category_name not in get_categories():
        logger.warning(f"User {user_id} selected invalid category '{category_name}'.")
        await callback_query.answer("Category not found. Try again! 🧐", show_alert=True)
        await temp_msg.delete()
        await callback_query.message.edit_text(
            "Category not found. Try another! 🧐",
            reply_markup=category_keyboard()
        )
        return

    user_doc = users_collection.find_one({'user_id': user_id})
    last_viewed_uuid = user_doc.get('last_viewed_per_category', {}).get(category_name)

    video = None
    if category_name == "default (all)":
        video = get_random_video()
    else:
        if last_viewed_uuid:
            video = get_video_by_uuid(last_viewed_uuid)
            # Ensure the last viewed video still matches the category and is valid
            if not video or video.get('category') != category_name or video.get('banned') or not video.get('sequence_number'):
                logger.warning(f"Last viewed video {last_viewed_uuid} for user {user_id} in category {category_name} is no longer valid. Falling back.")
                video = None
                users_collection.update_one(
                    {'user_id': user_id},
                    {'$unset': {f'last_viewed_per_category.{category_name}': ""}}
                )

        if not video:
            video = get_first_video_by_sequence_number(category_name)

    if not video:
        logger.warning(f"No videos found in category '{category_name}' for user {user_id}.")
        await callback_query.answer("No videos in this category. Try another! 😔", show_alert=True)
        try:
            await temp_msg.delete()
        except Exception:
            pass
        await callback_query.message.edit_text(
            "No videos in this category. Try another! 😔",
            reply_markup=category_keyboard()
        )
        return

    sent_success, sent_message_or_error = await send_and_replace_message(
        client,
        chat_id,
        message_id_to_edit_or_delete=temp_msg.id,
        new_message_type="video",
        video_data=video,
        reply_markup=video_nav_keyboard(video['uuid'], category_name, user_id, is_saved=False), # Not from saved_videos path
        force_new_message=True # Force a new message for a clean transition from category menu
    )

    if sent_success:
        mark_free_video_used(user_id)
        if category_name == "default (all)":
            user_session_history[user_id] = {'videos': [video['uuid']], 'position': 0, 'is_get_video': True}
        else:
            user_session_history[user_id] = {'category': category_name, 'videos': [video['uuid']], 'position': 0, 'is_get_video': False}
        save_history(user_id, video['uuid'], category_name)
        await callback_query.answer()
        # If the original message was the category selection, delete it
        if callback_query.message.id != temp_msg.id:
            try:
                await client.delete_messages(chat_id, callback_query.message.id)
            except MessageIdInvalid:
                pass
            except Exception as e:
                logger.warning(f"Failed to delete original category selection message {callback_query.message.id}: {e}")
    else:
        logger.error(f"User {user_id} failed to send video after category selection: {sent_message_or_error}. Clearing active video message.")
        await callback_query.answer("❌ Failed to load video. Please try again.😥", show_alert=True)
        clear_active_video_message(user_id)
        await temp_msg.delete()

# Rejection Reasons Mapping
REJECTION_REASONS = {
    "1": "Low Quality",
    "2": "Duplicate",
    "3": "Wrong Content",
    "4": "Broken/Short",
    "5": "Other"
}

@bot.on_callback_query(filters.regex(r"^adm_appr_(.+)$"))
async def admin_approve_callback(client: Client, callback_query: CallbackQuery):
    """Handles the initial 'Approve' click by admin, prompting for category."""
    user_id = callback_query.from_user.id
    if not is_admin(user_id):
        await callback_query.answer("❌ Not authorized.", show_alert=True)
        return

    upload_id = callback_query.data[9:]
    upload_data = pending_uploads_collection.find_one({"upload_id": upload_id})
    if not upload_data:
        await callback_query.answer("❌ Upload data not found.", show_alert=True)
        return

    if upload_data['status'] != "pending":
        await callback_query.answer(f"❌ This upload has already been {upload_data['status']}.", show_alert=True)
        return

    categories = get_categories(for_admin_use=True)
    buttons = []
    row = []
    for i, cat in enumerate(categories):
        # Prevent 64-byte limit by sending category index instead of raw base64 string
        row.append(InlineKeyboardButton(f"🗂️ {cat}", callback_data=f"apr_cat_{upload_id}_{i}"))
        if (i + 1) % 2 == 0:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data=f"apr_cancel_{upload_id}")])

    await callback_query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(buttons))
    await callback_query.answer("Select a category for this video.")

@bot.on_callback_query(filters.regex(r"^apr_cat_(.+?)_(.+)$"))
async def admin_final_approve_callback(client: Client, callback_query: CallbackQuery):
    """Finalizes approval after category selection."""
    user_id = callback_query.from_user.id
    if not is_admin(user_id):
        await callback_query.answer("❌ Not authorized.", show_alert=True)
        return

    match = re.match(r"^apr_cat_(.+?)_(.+)$", callback_query.data)
    upload_id = match.group(1)
    category_repr = match.group(2)

    categories = get_categories(for_admin_use=True)
    if category_repr.isdigit():
        idx = int(category_repr)
        if idx < len(categories):
            category = categories[idx]
        else:
            await callback_query.answer("❌ Invalid category selection.", show_alert=True)
            return
    else:
        category = b64_to_str(category_repr)

    upload_data = pending_uploads_collection.find_one({"upload_id": upload_id})
    if not upload_data or upload_data['status'] != "pending":
        await callback_query.answer("❌ Error: Already processed or not found.", show_alert=True)
        return

    # 1. Move to Main Media Collection
    if not DATA_CHANNEL_ID:
        await callback_query.answer("❌ Data channel not set. Cannot approve.", show_alert=True)
        return

    try:
        # Copy to data channel officially with robust fallback to send_video
        caption_to_use = upload_data.get('caption') or f"Category: {category}"
        try:
            sent_video = await client.copy_message(
                chat_id=DATA_CHANNEL_ID,
                from_chat_id=upload_data['user_id'],
                message_id=upload_data['message_id_in_user_chat'],
                caption=caption_to_use
            )
        except Exception as copy_err:
            logger.warning(f"copy_message failed for upload approval: {copy_err}. Retrying with direct send_video...")
            sent_video = await client.send_video(
                chat_id=DATA_CHANNEL_ID,
                video=upload_data['file_id'],
                caption=caption_to_use
            )

        # Get next sequence number
        last_video = media_collection.find_one({'category': category}, sort=[('sequence_number', DESCENDING)])
        next_seq = (last_video['sequence_number'] + 1) if last_video and 'sequence_number' in last_video else 1

        video_uuid = str(uuid.uuid4())
        media_doc = {
            "uuid": video_uuid,
            "file_id": sent_video.video.file_id,
            "file_unique_id": upload_data['file_unique_id'],
            "category": category,
            "timestamp": get_current_time(),
            "sequence_number": next_seq,
            "message_id": sent_video.id,
            "banned": False,
            "custom_caption": upload_data.get('caption')
        }
        media_collection.insert_one(media_doc)

        # 2. Grant Reward (Token)
        # Fetch updated user stats first
        user_doc = users_collection.find_one_and_update(
            {'user_id': upload_data['user_id']},
            {'$inc': {'upload_stats.approved_count': 1}},
            return_document=ReturnDocument.AFTER
        )
        approved_count = user_doc.get('upload_stats', {}).get('approved_count', 1) if user_doc else 1

        min_req = UPLOAD_CONFIG.get('min_upload_count', 1)
        token_threshold_met = (approved_count % min_req == 0) if min_req > 0 else True

        reward_duration_hours = 0

        if token_threshold_met:
            # Check for milestone rewards first
            if UPLOAD_CONFIG.get('milestones_enabled'):
                milestones = UPLOAD_CONFIG.get('milestones', {})
                count_str = str(approved_count)
                if count_str in milestones:
                    reward_duration_hours = float(milestones[count_str])

            # Fallback to base reward if no milestone hit
            if reward_duration_hours == 0:
                reward_duration_hours = UPLOAD_CONFIG.get('reward_tokens_hours', 2.0)

            if reward_duration_hours > 0:
                reward_duration_sec = int(reward_duration_hours * 3600)
                add_token(upload_data['user_id'], duration_seconds=reward_duration_sec, is_admin_granted=False)

        # 3. Handle Temp Scrolls (Convert to Permanent)
        scroll_reward = 0
        if user_doc and 'temp_scrolls' in user_doc:
            for s in user_doc['temp_scrolls']:
                if s.get('upload_id') == upload_id:
                    scroll_reward = s.get('amount', 0)
                    break

        users_collection.update_one(
            {'user_id': upload_data['user_id']},
            {
                '$pull': {'temp_scrolls': {'upload_id': upload_id}},
                '$inc': {'upload_stats.pending_count': -1, 'permanent_scrolls': scroll_reward}
            }
        )

        # 4. Update Pending Record
        pending_uploads_collection.update_one(
            {"upload_id": upload_id},
            {"$set": {"status": "approved", "reviewed_by": user_id, "reviewed_at": datetime.now(timezone.utc), "category": category}}
        )

        # 5. Notify User
        try:
            video_share_link = f"https://t.me/{config.BOT_USERNAME[1:]}?start=video_{video_uuid}_{upload_data['user_id']}"
            reward_text = ""
            goal_reached_header = ""
            if token_threshold_met and reward_duration_hours > 0:
                goal_reached_header = "🎯 **Goal Reached! Special Reward Unlocked!** 🎊\n\n"
                reward_text = f"Reward: **{reward_duration_hours} hours** of general access token added to your bank! 🎁\n"
            elif not token_threshold_met:
                more_needed = min_req - (approved_count % min_req)
                reward_text = f"Progress: **{approved_count}** total approvals. Need **{more_needed} more** videos approved to get your next reward! 🚀\n"
            elif UPLOAD_CONFIG.get('milestones_enabled'):
                reward_text = f"Progress: **{approved_count}** total approvals. Keep going to reach the next milestone! 🚀\n"

            approval_message = (
                f"{goal_reached_header}"
                f"🎉 **Good News! Your video has been approved!**\n\n"
                f"Category: `{category}`\n"
                f"{reward_text}\n"
                f"🔗 **Your Video Link:**\n`{video_share_link}`\n\n"
                f"💡 You can earn more by refferaling user with this link! 🤝\n\n"
                "Thank you for contributing to the community! ❤️"
            )

            try:
                await client.send_message(
                    upload_data['user_id'],
                    approval_message,
                    reply_to_message_id=upload_data.get('message_id_in_user_chat')
                )
            except RPCError:
                # Fallback to direct send if user deleted original message / reply_to fails
                await client.send_message(
                    upload_data['user_id'],
                    approval_message
                )

            # Update original confirmation message
            if upload_data.get('confirmation_message_id'):
                try:
                    await client.edit_message_text(
                        chat_id=upload_data['user_id'],
                        message_id=upload_data['confirmation_message_id'],
                        text="✅ **Your contribution was approved!** Thank you! ❤️"
                    )
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Failed to notify user {upload_data['user_id']} of approval: {e}")

        await callback_query.message.edit_text(f"✅ Upload Approved!\nCategory: {category}\nReviewed by: {user_id}")
        await callback_query.answer("Upload approved successfully!")

    except Exception as e:
        logger.error(f"Approval error for upload {upload_id}: {e}", exc_info=True)
        await callback_query.answer("❌ An error occurred during approval.", show_alert=True)

@bot.on_callback_query(filters.regex(r"^adm_rejc_(.+)$"))
async def admin_reject_callback(client: Client, callback_query: CallbackQuery):
    """Handles the 'Reject' click by admin, prompting for reason."""
    user_id = callback_query.from_user.id
    if not is_admin(user_id):
        await callback_query.answer("❌ Not authorized.", show_alert=True)
        return

    upload_id = callback_query.data[9:]
    upload_data = pending_uploads_collection.find_one({"upload_id": upload_id})
    if not upload_data or upload_data['status'] != "pending":
        await callback_query.answer("❌ Already processed or not found.", show_alert=True)
        return

    buttons = []
    # Avoid 64-byte limits by mapping reasons to small numeric keys
    for k, reason_text in REJECTION_REASONS.items():
        buttons.append([InlineKeyboardButton(reason_text, callback_data=f"rej_res_{upload_id}_{k}")])

    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data=f"apr_cancel_{upload_id}")])

    await callback_query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(buttons))
    await callback_query.answer("Select a reason for rejection.")

@bot.on_callback_query(filters.regex(r"^rej_res_(.+?)_(.+)$"))
async def admin_final_reject_callback(client: Client, callback_query: CallbackQuery):
    """Finalizes rejection after reason selection."""
    user_id = callback_query.from_user.id
    if not is_admin(user_id):
        await callback_query.answer("❌ Not authorized.", show_alert=True)
        return

    match = re.match(r"^rej_res_(.+?)_(.+)$", callback_query.data)
    upload_id = match.group(1)
    reason_key = match.group(2)
    reason = REJECTION_REASONS.get(reason_key, "Other")

    upload_data = pending_uploads_collection.find_one({"upload_id": upload_id})
    if not upload_data or upload_data['status'] != "pending":
        await callback_query.answer("❌ Already processed or not found.", show_alert=True)
        return

    # 1. Update Pending Record
    pending_uploads_collection.update_one(
        {"upload_id": upload_id},
        {"$set": {"status": "rejected", "reviewed_by": user_id, "reviewed_at": datetime.now(timezone.utc), "review_reason": reason}}
    )

    # 2. Update User Stats & Remove Temp Scrolls
    users_collection.update_one(
        {'user_id': upload_data['user_id']},
        {
            '$pull': {'temp_scrolls': {'upload_id': upload_id}},
            '$inc': {'upload_stats.pending_count': -1}
        }
    )

    # 3. Notify User
    try:
        rejection_message = (
            f"❌ **Your video contribution was not approved.**\n\n"
            f"Reason: `{reason}`\n"
            "Feel free to contribute other high-quality videos! ✨"
        )
        try:
            await client.send_message(
                upload_data['user_id'],
                rejection_message,
                reply_to_message_id=upload_data.get('message_id_in_user_chat')
            )
        except RPCError:
            # Fallback to direct send if user deleted original message / reply_to fails
            await client.send_message(
                upload_data['user_id'],
                rejection_message
            )

        if upload_data.get('confirmation_message_id'):
            try:
                await client.edit_message_text(
                    chat_id=upload_data['user_id'],
                    message_id=upload_data['confirmation_message_id'],
                    text=f"❌ **Your contribution was not approved.** (Reason: {reason})"
                )
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"Failed to notify user {upload_data['user_id']} of rejection: {e}")

    await callback_query.message.edit_text(f"❌ Upload Rejected!\nReason: {reason}\nReviewed by: {user_id}")
    await callback_query.answer("Upload rejected.")

@bot.on_callback_query(filters.regex(r"^apr_cancel_(.+)$"))
async def admin_cancel_review_callback(client: Client, callback_query: CallbackQuery):
    """Cancels the approve/reject flow and returns to main buttons."""
    user_id = callback_query.from_user.id
    if not is_admin(user_id):
        return

    upload_id = callback_query.data[11:]

    reply_markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"adm_appr_{upload_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"adm_rejc_{upload_id}")
        ]
    ])
    await callback_query.message.edit_reply_markup(reply_markup=reply_markup)
    await callback_query.answer("Cancelled.")

@bot.on_callback_query(filters.regex(r"^view_saved_cat_(.+)$"))
async def view_saved_category_callback(client: Client, callback_query: CallbackQuery):
    """Handles selection of a specific category within the 'Saved Videos' menu."""
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id
    # Changed: Decode category name from callback data
    selected_category = b64_to_str(callback_query.data[15:])
    logger.info(f"User {user_id} selected saved category: {selected_category}.")

    if not await check_membership(client, user_id):
        await callback_query.answer("You must join our channel first!", show_alert=True)
        await send_force_subscribe_message(client, user_id)
        return

    create_tracked_task(check_premium_status_and_notify(client, user_id))

    if not has_free_video_access(user_id, limit=1):
        await callback_query.answer("You need an access token to view saved videos! 🧐", show_alert=True)
        await send_token_earning_options(client, callback_query.message)
        return

    if await is_rate_limited(user_id):
        await callback_query.answer("⚠️ Browse too quickly. Wait 1 min. ⏳", show_alert=True)
        logger.warning(f"User {user_id} hit rate limit in view_saved_category_callback.")
        return

    # Check for menu expiry
    current_active_tracked_message = active_video_message.get(user_id)
    if current_active_tracked_message and \
       current_active_tracked_message.get('message_id') == callback_query.message.id and \
       datetime.now(timezone.utc) - current_active_tracked_message.get('timestamp', datetime.min.replace(tzinfo=timezone.utc)) > timedelta(minutes=config.MENU_EXPIRY_MINUTES):

        logger.warning(f"User {user_id} tried to select saved category but menu expired.")
        await callback_query.answer("Menu expired. Click '🎞️ Get Video' to restart. ⏰", show_alert=True)
        try:
            await client.delete_messages(chat_id, callback_query.message.id)
        except MessageIdInvalid:
            pass
        clear_active_video_message(user_id)
        await client.send_message(chat_id, "Your menu has expired. Please click '🎞️ Get Video' to get a new one. ⏰")
        return

    user_doc = users_collection.find_one({'user_id': user_id})
    bookmarked_videos = user_doc.get('bookmarked_videos', [])

    # Filter bookmarks for the selected category and sort by bookmarked_at
    filtered_saved_videos = []
    for bookmark in bookmarked_videos:
        video_data = get_video_by_uuid(bookmark['uuid'])
        if video_data and video_data.get('category') == selected_category:
            filtered_saved_videos.append(bookmark)

    filtered_saved_videos.sort(key=lambda x: x.get('bookmarked_at', datetime.min.replace(tzinfo=timezone.utc)))

    if not filtered_saved_videos:
        await callback_query.answer(f"You haven't saved any videos from the '{html.escape(selected_category)}' category yet. ❤️", show_alert=True)
        # Re-show the saved categories menu
        await send_and_replace_message(
            client,
            chat_id,
            message_id_to_edit_or_delete=callback_query.message.id,
            new_message_type="text",
            text_content="🗂️ <b>Select a Category from your Saved Videos:</b>",
            reply_markup=saved_category_keyboard(user_id)
        )
        return

    # Get the first video in this specific saved category
    first_saved_video_uuid = filtered_saved_videos[0]['uuid']
    video_to_display = get_video_by_uuid(first_saved_video_uuid)

    if not video_to_display:
        await callback_query.answer("The first video in this saved category was not found. It may have been removed. 😔", show_alert=True)
        # Clean up the invalid bookmark
        users_collection.update_one(
            {'user_id': user_id},
            {'$pull': {'bookmarked_videos': {'uuid': first_saved_video_uuid}}}
        )
        # Re-show the saved categories menu
        await send_and_replace_message(
            client,
            chat_id,
            message_id_to_edit_or_delete=callback_query.message.id,
            new_message_type="text",
            text_content="🗂️ <b>Select a Category from your Saved Videos:</b>",
            reply_markup=saved_category_keyboard(user_id)
        )
        return

    # MODIFIED: Changed force_new_message to True for a robust transition
    sent_success, sent_message_or_error = await send_and_replace_message(
        client,
        chat_id,
        message_id_to_edit_or_delete=callback_query.message.id,
        new_message_type="video",
        video_data=video_to_display,
        reply_markup=video_nav_keyboard(video_to_display['uuid'], selected_category, user_id, is_saved=True),
        force_new_message=True
    )

    if sent_success:
        mark_free_video_used(user_id)
        user_session_history[user_id] = {'category': selected_category, 'videos': [video_to_display['uuid']], 'position': 0, 'is_get_video': False, 'is_saved': True}
        save_history(user_id, video_to_display['uuid'], selected_category)
        await callback_query.answer()
        logger.info(f"User {user_id} viewed first saved video {video_to_display['uuid']} in category {selected_category}.")
    else:
        await callback_query.answer("❌ Failed to load video. Please try again.😥", show_alert=True)
        clear_active_video_message(user_id)


@bot.on_callback_query(filters.regex(r"^(dislike|like)\|(.+)\|"))
async def interaction_callback(client: Client, callback_query: CallbackQuery):
    """Handles 'Like' and 'Dislike' video callbacks in-place by adjusting rating."""
    user_id = callback_query.from_user.id
    parts = callback_query.data.split('|')
    video_uuid = parts[1]

    if not has_free_video_access(user_id, current_video_uuid=video_uuid):
        await callback_query.answer("Human verification required! 🔐", show_alert=True)
        await send_token_earning_options(client, callback_query.message)
        return

    is_like = callback_query.data.startswith("like")
    popup = "You liked this video! ❤️" if is_like else "You disliked this video! 💔"
    try:
        # Save rating to DB
        users_collection.update_one(
            {'user_id': user_id},
            {'$set': {f'ratings.{video_uuid}': "like" if is_like else "dislike"}},
            upsert=True
        )

        await callback_query.answer(popup, show_alert=False)

        video_data = get_video_by_uuid(video_uuid)
        if not video_data:
            return

        is_saved_from_markup = False
        if len(parts) >= 4:
            is_saved_from_markup = bool(int(parts[3]))

        _, current_position, total_videos = get_video_and_position(
            video_uuid, video_data.get('category'), is_saved_from_markup, user_id
        )

        fake_ratio = get_user_adjusted_fake_ratio(user_id, video_uuid)
        custom_caption = video_data.get('custom_caption')
        category_name = video_data.get('category') or 'Default'

        # Since it is a category-specific video in the get video menu, format it with the rating
        new_caption = (
            f"🎬 <b>Now Playing: {html.escape(category_name)} Collection</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📦 <b>Video:</b> <code>#{current_position} of {total_videos}</code>\n"
            f"📈 <b>Community Rating:</b> <code>{fake_ratio}%</code> of users liked this ❤️\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        )
        if custom_caption:
            new_caption += f"📝 <i>{html.escape(custom_caption)}</i>\n\n"
        new_caption += f"🍿 <i>Enjoy your watch! Use the controls below to browse.</i>"

        await client.edit_message_caption(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.id,
            caption=new_caption,
            reply_markup=callback_query.message.reply_markup
        )
        raise StopPropagation
    except StopPropagation:
        raise
    except Exception as e:
        logger.error(f"User {user_id} failed in interaction_callback: {e}", exc_info=True)
        await callback_query.answer("❌ Failed to register reaction.", show_alert=True)

@bot.on_callback_query(filters.regex(r"^(next|prev)\|(.+)\|")) # Updated regex to capture is_saved flag
async def navigate_video(client: Client, callback_query: CallbackQuery):
    """Handles 'Next' and 'Previous' video navigation."""
    user_id = callback_query.from_user.id

    # --- Processing Lock to prevent race conditions ---
    if user_id in processing_navigation_lock:
        await callback_query.answer("don't spam again", show_alert=True)
        return
    processing_navigation_lock.add(user_id)
    # --- End Processing Lock ---

    try:
        chat_id = callback_query.message.chat.id
        # Parse callback data: action (next/prev), current_uuid, [category], is_saved_flag
        parts = callback_query.data.split('|')

        if len(parts) == 4:
            action, current_uuid, category_payload, is_saved_flag_str = parts
            category = "default (all)" if category_payload == "def" else b64_to_str(category_payload)
            is_saved = bool(int(is_saved_flag_str))
        elif len(parts) == 3:
            action, current_uuid, is_saved_flag_str = parts
            is_saved = bool(int(is_saved_flag_str))
            # Retrieve category from database as it's no longer in the callback to save space
            video_doc = get_video_by_uuid(current_uuid)
            if not video_doc:
                await callback_query.answer("Video not found. It might have been removed. 😔", show_alert=True)
                return
            category = video_doc.get('category')
        else:
            logger.error(f"Invalid callback data for navigate_video: {callback_query.data}")
            await callback_query.answer("Invalid request. Please try again.", show_alert=True)
            return

        logger.info(f"User {user_id} requested {action} video in category '{category}', is_saved: {is_saved}.")

        if not await check_membership(client, user_id):
            await send_force_subscribe_message(client, user_id)
            return

        create_tracked_task(check_premium_status_and_notify(client, user_id))

        # Determine the applicable limit
        session = user_session_history.get(user_id)
        limit = 2 if session and session.get('is_get_video') else 1

        if action == "next":
            if not has_free_video_access(user_id, limit=limit):
                await callback_query.answer("Human verification required! 🔐", show_alert=True)
                await send_token_earning_options(client, callback_query.message)
                return
        elif action == "prev":
            # Allow previous if it's within session history or if they have access for a new one
            is_within_session = session and session['position'] > 0
            if not is_within_session and not has_free_video_access(user_id, limit=limit, current_video_uuid=current_uuid):
                 await callback_query.answer("Human verification required! 🔐", show_alert=True)
                 await send_token_earning_options(client, callback_query.message)
                 return

        try:
            if await is_rate_limited(user_id):
                await callback_query.answer("⚠️ Browse too quickly. Wait 1 min. ⏳", show_alert=True)
                logger.warning(f"User {user_id} hit rate limit in navigate_video.")
                return

            current_active_tracked_message = active_video_message.get(user_id)
            if current_active_tracked_message and \
               current_active_tracked_message.get('message_id') == callback_query.message.id and \
               datetime.now(timezone.utc) - current_active_tracked_message.get('timestamp', datetime.min.replace(tzinfo=timezone.utc)) > timedelta(minutes=config.MENU_EXPIRY_MINUTES):

                logger.warning(f"User {user_id} tried to navigate but menu expired.")
                await callback_query.answer("Menu expired. Click '🎞️ Get Video' to restart. ⏰", show_alert=True)
                try:
                    await client.delete_messages(chat_id, callback_query.message.id)
                except MessageIdInvalid:
                    pass
                except Exception as e:
                    logger.warning(f"Failed to delete expired menu message for user {user_id}: {e}")
                clear_active_video_message(user_id)
                await client.send_message(chat_id, "Your menu has expired. Please click '🎞️ Get Video' to get a new one. ⏰")
                return

            # If the user clicks an old button, just answer and return. The active message logic will handle it.
            if current_active_tracked_message and current_active_tracked_message.get('message_id') != callback_query.message.id:
                logger.warning(f"User {user_id} clicked old menu button. Callback Message ID: {callback_query.message.id}, Active Menu ID: {current_active_tracked_message.get('message_id')}")
                await callback_query.answer("This menu is outdated. Please use the latest one. 🔄", show_alert=True)
                # No need to delete message here, it will be handled by cleanup_expired_menus or next send_and_replace_message
                return

            # --- MODIFICATION: Check for last video ---
            if action == "next":
                _, current_pos, total_videos = get_video_and_position(current_uuid, category, is_saved, user_id)
                if total_videos > 0 and current_pos >= total_videos:
                    await callback_query.answer(
                        "✨ You've watched all the videos from this menu! ✨\n\n"
                        "To watch more videos like this, click 'Watch More'.",
                        show_alert=True
                    )
                    return
            # --- END MODIFICATION ---

            video = None
            if action == "prev" and session and session['position'] > 0:
                # Use session history for Previous
                prev_uuid = session['videos'][session['position'] - 1]
                video = get_video_by_uuid(prev_uuid)

            if not video:
                if is_saved:
                    if action == "next":
                        video = get_next_saved_video_chronological(user_id, current_uuid, category)
                    elif action == "prev":
                        video = get_previous_saved_video_chronological(user_id, current_uuid, category)

                    if not video: # This should not be hit if the check above is correct, but as a fallback.
                        await callback_query.answer("No more saved videos in this category. ❤️", show_alert=True)
                        return

                else: # Not a saved video, use regular chronological navigation based on sequence_number
                    if category not in get_categories():
                        logger.warning(f"User {user_id} used invalid category '{category}' for navigation (non-saved).")
                        await callback_query.answer("Category not found. Try 'Change Category'! 🧐", show_alert=True)
                        return

                    if action == "next":
                        video = get_next_video_chronological(current_uuid, category)
                    elif action == "prev":
                        video = get_previous_video_chronological(current_uuid, category)

                    if not video: # This case should ideally not be hit with looping logic, but as a fallback.
                        await callback_query.answer(f"No more {action} videos in this category. Try another! 😔", show_alert=True)
                        return

            # Call send_and_replace_message. It will handle broken videos and recursive retries.
            sent_success, sent_message_or_error = await send_and_replace_message(
                client,
                chat_id,
                message_id_to_edit_or_delete=callback_query.message.id,
                new_message_type="video",
                video_data=video,
                reply_markup=video_nav_keyboard(video['uuid'], category, user_id, is_saved=is_saved),
                force_new_message=False # Try to edit the existing message
            )

            if sent_success:
                if action == "next":
                    mark_free_video_used(user_id)
                    # Update session history
                    if session:
                        if video['uuid'] not in session['videos']:
                            session['videos'].append(video['uuid'])
                        session['position'] = session['videos'].index(video['uuid'])
                else: # prev
                    if session:
                        try:
                            session['position'] = session['videos'].index(video['uuid'])
                        except ValueError:
                            pass

                save_history(user_id, video['uuid'], category)
                logger.info(f"User {user_id} navigated to {action} video {video['uuid']} in category {category}.")
                await callback_query.answer()
            else:
                logger.error(f"User {user_id} failed to send {action} video: {sent_message_or_error}. Clearing active video message.")
                await callback_query.answer(f"❌ Failed to load {action} video. Please try again. 😥", show_alert=True)
                clear_active_video_message(user_id)
        except Exception as e:
            logger.error(f"User {user_id} error in navigate_video ({action}): {e}", exc_info=True)
            await callback_query.answer(
                "An unexpected error occurred. Try again. 🤷‍♀️",
                show_alert=True
            )
    finally:
        # Ensure the lock is always released
        if user_id in processing_navigation_lock:
            processing_navigation_lock.remove(user_id)


@bot.on_callback_query(filters.regex(r"^(dislike_default|like_default)\|(.+)$"))
async def interaction_default_callback(client: Client, callback_query: CallbackQuery):
    """Handles 'Like' and 'Dislike' for default category in-place by adjusting rating."""
    user_id = callback_query.from_user.id
    video_uuid = callback_query.data.split('|')[1]

    if not has_free_video_access(user_id, current_video_uuid=video_uuid):
        await callback_query.answer("Human verification required! 🔐", show_alert=True)
        await send_token_earning_options(client, callback_query.message)
        return

    is_like = callback_query.data.startswith("like_default")
    popup = "You liked this video! ❤️" if is_like else "You disliked this video! 💔"
    try:
        # Save rating to DB
        users_collection.update_one(
            {'user_id': user_id},
            {'$set': {f'ratings.{video_uuid}': "like" if is_like else "dislike"}},
            upsert=True
        )

        await callback_query.answer(popup, show_alert=False)

        video_data = get_video_by_uuid(video_uuid)
        if not video_data:
            return

        _, current_position, total_videos = get_video_and_position(
            video_uuid, "default (all)", False, user_id
        )

        fake_ratio = get_user_adjusted_fake_ratio(user_id, video_uuid)
        custom_caption = video_data.get('custom_caption')
        category_name = video_data.get('category') or 'Default'

        new_caption = (
            f"🎬 <b>Now Playing: {html.escape(category_name)} Collection</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📦 <b>Video:</b> <code>#{current_position} of {total_videos}</code>\n"
            f"📈 <b>Community Rating:</b> <code>{fake_ratio}%</code> of users liked this ❤️\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        )
        if custom_caption:
            new_caption += f"📝 <i>{html.escape(custom_caption)}</i>\n\n"
        new_caption += f"🍿 <i>Enjoy your watch! Use the controls below to browse.</i>"

        await client.edit_message_caption(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.id,
            caption=new_caption,
            reply_markup=callback_query.message.reply_markup
        )
        raise StopPropagation
    except StopPropagation:
        raise
    except Exception as e:
        logger.error(f"User {user_id} failed in interaction_default_callback: {e}", exc_info=True)
        await callback_query.answer("❌ Failed to register reaction.", show_alert=True)

@bot.on_callback_query(filters.regex(r"^(next_default|prev_default)\|(.+)$"))
async def navigate_default_category(client: Client, callback_query: CallbackQuery):
    """Handles 'Next' and 'Previous' for the 'default (all)' category."""
    user_id = callback_query.from_user.id
    action, current_uuid = callback_query.data.split('|', 1)

    if user_id in processing_navigation_lock:
        await callback_query.answer("don't spam again", show_alert=True)
        return
    processing_navigation_lock.add(user_id)

    try:
        chat_id = callback_query.message.chat.id
        logger.info(f"User {user_id} requested {action} in 'default (all)' category.")

        if not await check_membership(client, user_id):
            await send_force_subscribe_message(client, user_id)
            return

        session = user_session_history.get(user_id)
        limit = 2 if session and session.get('is_get_video') else 1

        if action == "next_default":
            if not has_free_video_access(user_id, limit=limit):
                await callback_query.answer("Human verification required! 🔐", show_alert=True)
                await send_token_earning_options(client, callback_query.message)
                return
        elif action == "prev_default":
             if not has_free_video_access(user_id, current_video_uuid=current_uuid):
                await callback_query.answer("Human verification required! 🔐", show_alert=True)
                await send_token_earning_options(client, callback_query.message)
                return
        if not session:
            await callback_query.answer("Your session has expired. Please select the category again.", show_alert=True)
            return

        video = None
        if action == "next_default":
            session['position'] += 1
            if session['position'] >= len(session['videos']):
                # Fetch a new video from a different category
                current_video_doc = get_video_by_uuid(current_uuid)
                current_category = current_video_doc.get('category') if current_video_doc else None
                new_video = get_random_video_from_different_category(current_category)
                if new_video:
                    session['videos'].append(new_video['uuid'])
                    video = new_video
                else: # No other videos found, end of the line
                    await callback_query.answer("No more videos available.", show_alert=True)
                    session['position'] -= 1 # Revert position
                    return
            else:
                # Get the next video from history
                video = get_video_by_uuid(session['videos'][session['position']])

        elif action == "prev_default":
            if session['position'] > 0:
                session['position'] -= 1
                video = get_video_by_uuid(session['videos'][session['position']])
            else:
                await callback_query.answer("You are at the beginning of your history.", show_alert=True)
                return

        if not video:
            await callback_query.answer("The next video is unavailable.", show_alert=True)
            return

        sent_success, _ = await send_and_replace_message(
            client, chat_id, callback_query.message.id, "video", video_data=video,
            reply_markup=video_nav_keyboard(video['uuid'], "default (all)", user_id),
            force_new_message=False
        )
        if sent_success:
            if action == "next_default":
                 mark_free_video_used(user_id)
            save_history(user_id, video['uuid'], "default (all)")
        await callback_query.answer()

    except Exception as e:
        logger.error(f"Error in navigate_default_category for user {user_id}: {e}", exc_info=True)
        await callback_query.answer("An error occurred.", show_alert=True)
    finally:
        if user_id in processing_navigation_lock:
            processing_navigation_lock.remove(user_id)


@bot.on_callback_query(filters.regex(r"^(next_batch|prev_batch)\|(.+)\|(\d+)$"))
async def navigate_batch_video(client: Client, callback_query: CallbackQuery):
    """Handles 'Next' and 'Previous' for batch video menus."""
    user_id = callback_query.from_user.id
    action, batch_id, current_index_str = callback_query.data.split('|')
    current_index = int(current_index_str)

    active_menu = active_video_message.get(user_id)
    current_uuid = active_menu.get('video_uuid') if active_menu else None
    session = user_session_history.get(user_id)
    is_prev = action == "prev_batch"

    # For batches, "Next" is strictly gated for free users (limit=0).
    if action == "next_batch" and not has_free_video_access(user_id, limit=0):
         await callback_query.answer("Human verification required! 🔐", show_alert=True)
         await send_token_earning_options(client, callback_query.message)
         return

    # Allow "Previous" if it's within session history
    if is_prev and not has_free_video_access(user_id, current_video_uuid=current_uuid):
         is_within_session = session and session.get('batch_id') == batch_id and current_index > 0
         if not is_within_session:
             await callback_query.answer("Human verification required! 🔐", show_alert=True)
             await send_token_earning_options(client, callback_query.message)
             return

    if user_id in processing_navigation_lock:
        await callback_query.answer("don't spam again", show_alert=True)
        return
    processing_navigation_lock.add(user_id)

    try:
        chat_id = callback_query.message.chat.id
        action, batch_id, current_index_str = callback_query.data.split('|')
        current_index = int(current_index_str)

        logger.info(f"User {user_id} requested {action} in batch '{batch_id}'.")

        if not await check_membership(client, user_id):
            await send_force_subscribe_message(client, user_id)
            return

        batch_doc = video_batches_collection.find_one({'batch_id': batch_id})
        if not batch_doc or not batch_doc.get('video_uuids'):
            await callback_query.answer("This batch is no longer available.", show_alert=True)
            return

        video_uuids = batch_doc['video_uuids']
        total_videos = len(video_uuids)

        # --- MODIFICATION: Check for last video ---
        if action == "next_batch" and current_index >= total_videos - 1:
            await callback_query.answer(
                "✨ You've watched all the videos from this menu! ✨\n\n"
                "To watch more videos like this, click 'Watch More'.",
                show_alert=True
            )
            return
        # --- END MODIFICATION ---

        if action == "next_batch":
            new_index = (current_index + 1)
            if new_index >= total_videos: new_index = 0 # Loop fallback
        else: # prev_batch
            new_index = (current_index - 1 + total_videos) % total_videos


        next_video_uuid = video_uuids[new_index]
        video = get_video_by_uuid(next_video_uuid)

        if not video:
            await callback_query.answer("The next video in this batch is unavailable.", show_alert=True)
            # In a more robust system, you might skip to the next available one.
            return

        sent_success, _ = await send_and_replace_message(
            client, chat_id, callback_query.message.id, "video", video_data=video,
            reply_markup=video_nav_keyboard(video['uuid'], video['category'], user_id, is_batch=True, batch_id=batch_id, batch_index=new_index),
            force_new_message=False, is_batch=True, batch_id=batch_id, batch_index=new_index
        )
        if sent_success:
            if session and session.get('batch_id') == batch_id:
                if video['uuid'] not in session['videos']:
                    session['videos'].append(video['uuid'])
                session['position'] = session['videos'].index(video['uuid'])
        # DO NOT save history for batch videos
        await callback_query.answer()

    except Exception as e:
        logger.error(f"Error in navigate_batch_video for user {user_id}: {e}", exc_info=True)
        await callback_query.answer("An error occurred.", show_alert=True)
    finally:
        if user_id in processing_navigation_lock:
            processing_navigation_lock.remove(user_id)

@bot.on_callback_query(filters.regex(r"^change_cat$"))
async def change_category(client: Client, callback_query: CallbackQuery):
    """Handles 'Change Category' request."""
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id
    logger.info(f"User {user_id} requested to change category.")

    active_menu = active_video_message.get(user_id)
    current_uuid = active_menu.get('video_uuid') if active_menu else None

    if not has_free_video_access(user_id, current_video_uuid=current_uuid):
        await callback_query.answer("Human verification required! 🔐", show_alert=True)
        await send_token_earning_options(client, callback_query.message)
        return

    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    create_tracked_task(check_premium_status_and_notify(client, user_id))

    try:
        current_active_tracked_message = active_video_message.get(user_id)
        if current_active_tracked_message and \
           current_active_tracked_message.get('message_id') == callback_query.message.id and \
           datetime.now(timezone.utc) - current_active_tracked_message.get('timestamp', datetime.min.replace(tzinfo=timezone.utc)) > timedelta(minutes=config.MENU_EXPIRY_MINUTES):

            logger.warning(f"User {user_id} tried to change category but menu expired. Callback Message ID: {callback_query.message.id}, Active Menu ID: {current_active_tracked_message.get('message_id')}")
            await callback_query.answer("Menu expired. Click '🎞️ Get Video' to restart. ⏰", show_alert=True)
            try:
                await client.delete_messages(callback_query.message.chat.id, callback_query.message.id)
            except MessageIdInvalid:
                pass
            except Exception as e:
                logger.warning(f"Failed to delete expired menu message for user {user_id}: {e}")
            clear_active_video_message(user_id)
            await client.send_message(chat_id, "Your menu has expired. Please click '🎞️ Get Video' to get a new one. ⏰")
            return

        if current_active_tracked_message and current_active_tracked_message.get('message_id') != callback_query.message.id:
            logger.warning(f"User {user_id} clicked old menu button. Callback Message ID: {callback_query.message.id}, Active Menu ID: {current_active_tracked_message.get('message_id')}")
            await callback_query.answer("This menu is outdated. Please use the latest one. 🔄", show_alert=True)
            try:
                await client.delete_messages(chat_id, callback_query.message.id)
            except MessageIdInvalid:
                pass
            except Exception as e:
                logger.warning(f"Failed to delete outdated menu message for user {user_id}: {e}")
            return

        try:
            await client.delete_messages(chat_id, callback_query.message.id)
            logger.info(f"Deleted current video message {callback_query.message.id} for user {user_id} to show category menu.")
            clear_active_video_message(user_id)
        except MessageIdInvalid:
            logger.warning(f"Message {callback_query.message.id} for user {user_id} was already invalid/deleted when changing category.")
            clear_active_video_message(user_id)
        except Exception as e:
            logger.error(f"Failed to delete current video message {callback_query.message.id} for user {user_id} during change category: {e}")

        cats = get_categories()
        if not cats:
            await callback_query.answer("😔 No categories available. Please ask an admin to add some! 🛠️", show_alert=True)
            return

        sent_message = await client.send_message(
            chat_id,
            "🎬 <b>Choose a Category:</b>",
            reply_markup=category_keyboard()
        )
        set_active_video_message(user_id, sent_message.id, chat_id)
        await callback_query.answer()
        logger.info(f"User {user_id} sent new message to show change category menu.")

    except Exception as e:
        logger.error(f"User {user_id} failed to send change category menu: {e}", exc_info=True)
        await callback_query.answer("❌ Something went wrong. Please try again. 🤷‍♀️", show_alert=True)

@bot.on_message(filters.regex("^👤 Profile$") & filters.private)
async def profile_btn(client: Client, message: Message):
    """Handles 'Profile' button click."""
    user_id = message.from_user.id
    logger.info(f"User {user_id} clicked Profile button.")
    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return
    try:
        await profile_cmd(client, message)
        logger.info(f"User {user_id}: Profile command triggered from button.")
    except Exception as e:
        logger.error(f"User {user_id} failed to trigger profile command from button: {e}", exc_info=True)
        await handle_error(client, message, e)


@bot.on_callback_query(filters.regex(r"^refer_and_earn_inline$"))
async def refer_and_earn_inline_callback(client: Client, callback_query: CallbackQuery):
    """Handles the inline 'Refer & Earn' button click from token earning options."""
    user_id = callback_query.from_user.id
    logger.info(f"User {user_id} clicked inline Refer & Earn button.")

    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    create_tracked_task(check_premium_status_and_notify(client, user_id))

    try:
        if await is_rate_limited(user_id):
            await callback_query.answer("⚠️ You're requesting too quickly. Please wait a minute and try again. ⏳", show_alert=True)
            logger.warning(f"User {user_id} hit rate limit in refer_and_earn_inline_callback.")
            return

        ref_link = f"https://t.me/{config.BOT_USERNAME[1:]}?start=ref_{user_id}"
        await callback_query.message.reply(
            f"🔗 <b>Share & Earn!</b>\nWhen a new user joins through this link, you'll receive {config.REFERRAL_BONUS} token. It's a win-win! 🎉\n\n<code>{html.escape(ref_link)}</code>\n\nShare this link to new users only to get the token! 📢",
            quote=True,
            disable_web_page_preview=True
        )
        await callback_query.answer("Referral link sent! 🎁")
        logger.info(f"User {user_id}: Inline referral link sent successfully.")
    except Exception as e:
        logger.error(f"User {user_id} failed to send inline referral link: {e}", exc_info=True)
        await callback_query.answer("❌ Something went wrong. Please try again. 🤷‍♀️", show_alert=True)



async def send_token_earning_options(client: Client, message: Message, is_pending_content: bool = False):
    """Sends messages to a user detailing how to earn tokens."""
    user_id = message.chat.id
    logger.info(f"User {user_id} is being sent token earning options.")

    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    wait_msg = None
    try:
        wait_msg = await message.reply("⏳ Preparing your options, please wait...")
        create_tracked_task(check_premium_status_and_notify(client, user_id))

        if await is_rate_limited(user_id):
            await message.reply_text("⚠️ You're requesting token options too quickly. Please wait a minute and try again. ⏳")
            logger.warning(f"User {user_id} hit rate limit in send_token_earning_options.")
            if wait_msg: await wait_msg.delete()
            return

        ad_code = str_to_b64(f"{user_id}:{get_current_time()}")
        shortener_logs_collection.insert_one({'ad_code': ad_code, 'user_id': user_id, 'created_at': datetime.now(timezone.utc)})
        long_url = f"https://t.me/{config.BOT_USERNAME[1:]}?start=token_{ad_code}"
        ad_url = await get_shortener_config_and_shorten_url(long_url) if not SHORTENER_DISABLED else ""

        if SHORTENER_DISABLED:
            text = (
                "✨ <b>Almost there! Just one quick step...</b>\n\n"
                "Please verify you're human to instantly unlock the next video and keep watching! ❤️"
            )
            reply_markup = generate_token_earning_keyboard(ad_url, is_pending_content, user_id=user_id, remove_tutorial=True)
        elif is_pending_content:
            text = (
                "🔒 <b>Access Token Required!</b>\n\n"
                "To continue watching the video you requested, please complete human verification or watch a quick ad.\n\n"
                "👉 Once done, click the <b>🔄 Refresh Status</b> button below to instantly view your video! 🍿"
            )
            reply_markup = generate_token_earning_keyboard(ad_url, is_pending_content, user_id=user_id)
        else:
            text = (
                "❌ <b>No Active Session or Tokens Left!</b> 😔\n\n"
                "Keep the vibe going! Use any of the options below to acquire a temporary access token or unlock premium bypass instantly! 👇"
            )
            reply_markup = generate_token_earning_keyboard(ad_url, is_pending_content, user_id=user_id, remove_tutorial=True)

        await message.reply(
            text,
            reply_markup=reply_markup,
            disable_web_page_preview=True
        )
        if wait_msg: await wait_msg.delete()
        logger.info(f"User {user_id}: Token earning options sent.")
    except Exception as e:
        if wait_msg:
            try: await wait_msg.delete()
            except: pass
        logger.error(f"User {user_id} failed to send token earning options: {e}", exc_info=True)
        await handle_error(client, message, e)

@bot.on_callback_query(filters.regex(r"^share_(.+)$"))
async def share_callback(client: Client, callback_query: CallbackQuery):
    """Handles 'Share' video callback to generate a shareable link with user_id."""
    user_id = callback_query.from_user.id
    video_uuid = callback_query.data.split('_', 1)[1]

    if not has_free_video_access(user_id, current_video_uuid=video_uuid):
        await callback_query.answer("Human verification required! 🔐", show_alert=True)
        await send_token_earning_options(client, callback_query.message)
        return

    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    create_tracked_task(check_premium_status_and_notify(client, user_id))

    try:
        try:
            uuid.UUID(video_uuid)
        except ValueError:
            logger.warning(f"User {user_id} attempted to share with invalid UUID format: {video_uuid}.")
            await callback_query.answer("❌ Invalid video ID. 🐛", show_alert=True)
            return

        share_payload = f"video_{video_uuid}_{user_id}"
        share_link = f"https://t.me/{config.BOT_USERNAME[1:]}?start={share_payload}"

        await callback_query.answer()
        logger.info(f"User {user_id} requested share link for video {video_uuid}.")

        # Build in-place edit with share details and back button
        share_caption = (
            f"🔗 <b>Share this Video & Earn!</b> 🎁\n\n"
            f"Send this link to your friends or post it in groups. When a new user joins through your link, you'll receive <b>{config.REFERRAL_BONUS} token</b> instantly! It's a win-win! 🎉\n\n"
            f"<code>{html.escape(share_link)}</code>\n\n"
            f"📢 <i>Note: You only earn tokens for introducing new users! Enjoy!</i>"
        )

        back_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back to Video", callback_data=f"back_from_share|{video_uuid}")]
        ])

        await client.edit_message_caption(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.id,
            caption=share_caption,
            reply_markup=back_keyboard
        )
        logger.info(f"User {user_id}: Menu edited with share link for video {video_uuid} in-place.")
    except Exception as e:
        logger.error(f"User {user_id} failed to edit menu with share link for video {video_uuid}: {e}", exc_info=True)
        await callback_query.answer("❌ Something went wrong. Please try again. 🤷‍♀️", show_alert=True)

@bot.on_callback_query(filters.regex(r"^back_from_share\|(.+)$"))
async def back_from_share_callback(client: Client, callback_query: CallbackQuery):
    """Restores the video navigation menu and caption from share state."""
    user_id = callback_query.from_user.id
    video_uuid = callback_query.data.split('|')[1]

    video_data = get_video_by_uuid(video_uuid)
    if not video_data:
        await callback_query.answer("Video not found.")
        return

    category_name = video_data.get('category') or 'Default'

    # Load user session
    session = user_session_history.get(user_id) or {}
    is_batch = session.get('batch_id') is not None
    batch_id = session.get('batch_id')
    batch_index = session.get('position', 1) - 1

    user_doc = users_collection.find_one({'user_id': user_id})
    is_saved = any(b['uuid'] == video_uuid for b in user_doc.get('bookmarked_videos', [])) if user_doc else False

    is_shared_link = not session.get('is_get_video', False) and not is_batch and not is_saved

    _, current_position, total_videos = get_video_and_position(
        video_uuid, category_name, is_saved, user_id
    )

    # Build back caption
    fake_ratio = get_user_adjusted_fake_ratio(user_id, video_uuid)
    custom_caption = video_data.get('custom_caption')

    # Rebuild caption text
    if not is_batch and not is_saved:
        new_caption = (
            f"🎬 <b>Now Playing: {html.escape(category_name)} Collection</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📦 <b>Video:</b> <code>#{current_position} of {total_videos}</code>\n"
            f"📈 <b>Community Rating:</b> <code>{fake_ratio}%</code> of users liked this ❤️\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        )
        if custom_caption:
            new_caption += f"📝 <i>{html.escape(custom_caption)}</i>\n\n"
        new_caption += f"🍿 <i>Enjoy your watch! Use the controls below to browse.</i>"
    else:
        if is_batch:
            new_caption = (
                f"🎬 <b>Batch Video Playing</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📦 <b>Video:</b> <code>#{current_position} of {total_videos}</code>\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            )
        elif is_saved:
            new_caption = (
                f"🔖 <b>Saved Videos: {html.escape(category_name)}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📦 <b>Video:</b> <code>#{current_position} of {total_videos}</code>\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            )
        else:
            new_caption = (
                f"🔗 <b>Shared Video</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🍿 <i>Enjoy your watch!</i>\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            )
        if custom_caption:
            new_caption += f"📝 <i>{html.escape(custom_caption)}</i>\n"

    # Restore original navigation keyboard
    back_keyboard = video_nav_keyboard(
        video_uuid, category_name, user_id,
        is_saved=is_saved, is_batch=is_batch,
        batch_id=batch_id, batch_index=batch_index,
        is_shared_link=is_shared_link
    )

    await client.edit_message_caption(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.id,
        caption=new_caption,
        reply_markup=back_keyboard
    )
    await callback_query.answer()

async def auto_delete_download(client: Client, chat_id: int, video_message: Message, info_message: Message):
    """Automatically deletes the downloaded video and its info warning message after 10 minutes and notifies the user."""
    await asyncio.sleep(600)  # Wait 10 minutes
    try:
        await client.delete_messages(chat_id, [video_message.id, info_message.id])
    except Exception as e:
        logger.warning(f"Failed to delete download messages in auto_delete_download: {e}")
    try:
        await client.send_message(chat_id, "🗑️ **The downloaded video has been auto-deleted to protect content privacy.**")
    except Exception as e:
        logger.warning(f"Failed to send deletion confirmation message: {e}")

@bot.on_callback_query(filters.regex(r"^download_(.+)$"))
async def download_video_callback(client: Client, callback_query: CallbackQuery):
    """Handles 'Download' video callback for premium users with auto-delete after 10 minutes."""
    user_id = callback_query.from_user.id
    video_uuid = callback_query.data.split('_', 1)[1]
    chat_id = callback_query.message.chat.id

    logger.info(f"User {user_id} requested download for video {video_uuid}.")

    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    create_tracked_task(check_premium_status_and_notify(client, user_id))

    try:
        if not is_premium_user(user_id):
            logger.info(f"Non-premium user {user_id} attempted to download video {video_uuid}.")
            await callback_query.answer("⚠️ Premium feature only! ✨", show_alert=True)
            await client.send_message(
                chat_id,
                get_premium_only_text(),
                reply_markup=buy_token_keyboard()
            )
            return

        video = get_video_by_uuid(video_uuid)
        if not video:
            logger.warning(f"Premium user {user_id} requested download for non-existent video {video_uuid}.")
            await callback_query.answer("Video not found. It might have been removed. 😔", show_alert=True)
            return

        if not DATA_CHANNEL_ID:
            logger.error("DATA_CHANNEL_ID is not set. Cannot download videos.")
            await callback_query.answer("Video storage channel is not configured. Please contact an an admin.", show_alert=True)
            return

        try:
            sent_video = await client.send_video(
                chat_id,
                video=video['file_id'],
                caption="⚠️ This video is for temporary download only and will be deleted in 10 minutes! Please save or forward it if you want to keep it.",
                protect_content=False
            )
            sent_info = await client.send_message(
                chat_id,
                "⏳ **Temporary Download Link Generated!**\n\nThis video and this message will be automatically deleted in **10 minutes** to protect privacy. Please download, save, or forward it now! 🚀"
            )
            create_tracked_task(auto_delete_download(client, chat_id, sent_video, sent_info))
            await callback_query.answer("Download initiated! 🚀")
            logger.info(f"Premium user {user_id} successfully received download for video {video_uuid}.")
        except FileReferenceExpired:
            logger.warning(f"FileReferenceExpired during download for video {video['uuid']}. Attempting self-healing.")
            try:
                message_id_in_channel = video.get('message_id')
                if not message_id_in_channel:
                    raise ValueError("No message_id found in DB for self-healing during download.")

                healed_message = await client.get_messages(DATA_CHANNEL_ID, message_id_in_channel)
                if not healed_message or not healed_message.video:
                    raise ValueError("Failed to fetch or find video in healed message during download.")

                new_file_id = healed_message.video.file_id
                media_collection.update_one({'uuid': video['uuid']}, {'$set': {'file_id': new_file_id}})
                logger.info(f"Database updated with new file_id for video {video['uuid']} during download.")

                sent_video = await client.send_video(
                    chat_id,
                    video=new_file_id,
                    caption="⚠️ This video is for temporary download only and will be deleted in 10 minutes! Please save or forward it if you want to keep it.",
                    protect_content=False
                )
                sent_info = await client.send_message(
                    chat_id,
                    "⏳ **Temporary Download Link Generated!**\n\nThis video and this message will be automatically deleted in **10 minutes** to protect privacy. Please download, save, or forward it now! 🚀"
                )
                create_tracked_task(auto_delete_download(client, chat_id, sent_video, sent_info))
                await callback_query.answer("Download initiated! 🚀")
                logger.info(f"Premium user {user_id} successfully received download for video {video_uuid} after self-healing.")
            except Exception as heal_e:
                logger.error(f"Self-healing failed during download for video {video['uuid']}: {heal_e}", exc_info=True)
                await callback_query.answer("❌ Failed to send video for download. Please try again later. 😥", show_alert=True)
                return

    except Exception as e:
        logger.error(f"Error handling download for user {user_id}, video {video_uuid}: {e}", exc_info=True)
        await callback_query.answer("❌ Failed to send video for download. Please try again later. 😥", show_alert=True)


@bot.on_callback_query(filters.regex(r"^bookmark_(.+)$"))
async def bookmark_video_callback(client: Client, callback_query: CallbackQuery):
    """Handles 'Bookmark' video callback."""
    user_id = callback_query.from_user.id
    video_uuid = callback_query.data.split('_', 1)[1]

    logger.info(f"User {user_id} requested to bookmark video {video_uuid}.")

    if not has_free_video_access(user_id, current_video_uuid=video_uuid):
        await callback_query.answer("Human verification required! 🔐", show_alert=True)
        await send_token_earning_options(client, callback_query.message)
        return

    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    create_tracked_task(check_premium_status_and_notify(client, user_id))

    try:
        user = users_collection.find_one({'user_id': user_id})
        if not user:
            await callback_query.answer("User not found. Please restart the bot.", show_alert=True)
            return

        bookmarked_videos = user.get('bookmarked_videos', [])

        if any(v['uuid'] == video_uuid for v in bookmarked_videos):
            await callback_query.answer("This video is already bookmarked! ❤️", show_alert=True)
            return

        is_premium = is_premium_user(user_id)

        if not is_premium and len(bookmarked_videos) >= config.FREE_USER_SAVE_LIMIT:
            await callback_query.answer(f"You've reached your limit of {config.FREE_USER_SAVE_LIMIT} saved videos! Upgrade to Premium for unlimited saves. ✨", show_alert=True)
            return

        video_data = get_video_by_uuid(video_uuid)
        if not video_data:
            await callback_query.answer("Cannot bookmark: video not found. 😔", show_alert=True)
            return

        # Add the video with timestamp for ordering and its category for filtering
        bookmarked_videos.append({'uuid': video_uuid, 'bookmarked_at': datetime.now(timezone.utc), 'category': video_data.get('category')})

        users_collection.update_one(
            {'user_id': user_id},
            {'$set': {'bookmarked_videos': bookmarked_videos}}
        )

        await callback_query.answer("Video bookmarked successfully! ❤️")
        logger.info(f"User {user_id} bookmarked video {video_uuid}.")

    except Exception as e:
        logger.error(f"Error handling bookmark for user {user_id}, video {video_uuid}: {e}", exc_info=True)
        await callback_query.answer("❌ Failed to bookmark video. Please try again later. 😥", show_alert=True)

@bot.on_message(filters.regex("^🔖 Saved Videos$") & filters.private)
async def saved_videos_btn(client: Client, message: Message):
    """Handles 'Saved Videos' button click by showing categories of saved videos."""
    user_id = message.from_user.id
    chat_id = message.chat.id
    logger.info(f"User {user_id} clicked Saved Videos button.")

    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    create_tracked_task(check_premium_status_and_notify(client, user_id))

    if await is_rate_limited(user_id):
        await handle_error(client, message, FloodWait(10))
        logger.warning(f"User {user_id} hit rate limit in saved_videos_btn.")
        return

    if not user_can_access_video(user_id):
        logger.info(f"User {user_id} has no access, prompting earning options for saved videos.")
        await send_token_earning_options(client, message)
        return

    user = users_collection.find_one({'user_id': user_id})
    if not user or not user.get('bookmarked_videos'):
        await message.reply("You haven't saved any videos yet. ❤️ Click 'Get Video' and then 'Bookmark' your favorites! ✨", reply_markup=await get_main_keyboard(user_id))
        return

    # Get the keyboard with categories from saved videos
    saved_cats_keyboard = saved_category_keyboard(user_id)

    if saved_cats_keyboard.inline_keyboard[0][0].callback_data in ["no_saved_videos", "no_valid_saved_videos"]:
        await message.reply("You haven't saved any valid videos yet. ❤️ Click 'Get Video' and then 'Bookmark' your favorites! ✨", reply_markup=await get_main_keyboard(user_id))
        return

    message_id_to_edit_or_delete = message.id

    sent_success, sent_message_or_error = await send_and_replace_message(
        client,
        chat_id,
        message_id_to_edit_or_delete=message_id_to_edit_or_delete,
        new_message_type="text",
        text_content="🗂️ <b>Select a Category from your Saved Videos:</b>",
        reply_markup=saved_cats_keyboard,
        force_new_message=True
    )

    if not sent_success:
        await message.reply(sent_message_or_error)
        logger.error(f"User {user_id} failed to send saved categories menu: {sent_message_or_error}")


@bot.on_callback_query(filters.regex(r"^remove_saved_(.+)$"))
async def remove_saved_video_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    # Split by '_' and then take the part after 'remove_saved_'
    video_uuid = callback_query.data.split('_', 2)[2]
    chat_id = callback_query.message.chat.id
    logger.info(f"User {user_id} requested to remove saved video {video_uuid}.")

    if not has_free_video_access(user_id, current_video_uuid=video_uuid):
        await callback_query.answer("Human verification required! 🔐", show_alert=True)
        await send_token_earning_options(client, callback_query.message)
        return

    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    create_tracked_task(check_premium_status_and_notify(client, user_id))

    try:
        current_active_tracked_message = active_video_message.get(user_id)
        if current_active_tracked_message and \
           current_active_tracked_message.get('message_id') == callback_query.message.id and \
           datetime.now(timezone.utc) - current_active_tracked_message.get('timestamp', datetime.min.replace(tzinfo=timezone.utc)) > timedelta(minutes=config.MENU_EXPIRY_MINUTES):

            logger.warning(f"User {user_id} tried to remove saved video but menu expired.")
            await callback_query.answer("Menu expired. Click '🎞️ Get Video' to restart. ⏰", show_alert=True)
            try:
                await client.delete_messages(chat_id, callback_query.message.id)
            except MessageIdInvalid:
                pass
            except Exception as e:
                logger.warning(f"Failed to delete expired menu message for user {user_id}: {e}")
            clear_active_video_message(user_id)
            await client.send_message(chat_id, "Your menu has expired. Please click '🎞️ Get Video' to get a new one. ⏰")
            return

        if current_active_tracked_message and current_active_tracked_message.get('message_id') != callback_query.message.id:
            logger.warning(f"User {user_id} clicked old menu button. Callback Message ID: {callback_query.message.id}, Active Menu ID: {current_active_tracked_message.get('message_id')}")
            await callback_query.answer("This menu is outdated. Please use the latest one. 🔄", show_alert=True)
            try:
                await client.delete_messages(chat_id, callback_query.message.id)
            except MessageIdInvalid:
                pass
            except Exception as e:
                logger.warning(f"Failed to delete outdated menu message for user {user_id}: {e}")
            return

        result = users_collection.update_one(
            {'user_id': user_id},
            {'$pull': {'bookmarked_videos': {'uuid': video_uuid}}}
        )

        if result.modified_count > 0:
            await callback_query.answer("Video removed from saved videos. 🗑️")
            user = users_collection.find_one({'user_id': user_id})
            bookmarked_videos = user.get('bookmarked_videos', [])

            existing_bookmarked_videos = []
            for bookmark in bookmarked_videos:
                if get_video_by_uuid(bookmark['uuid']):
                    existing_bookmarked_videos.append(bookmark)
                else:
                    logger.warning(f"Saved video {bookmark['uuid']} for user {user_id} not found in media_collection during remove_saved_video_callback. Removing from bookmarks.")
                    users_collection.update_one(
                        {'user_id': user_id},
                        {'$pull': {'bookmarked_videos': {'uuid': bookmark['uuid']}}}
                    )

            current_video_info = media_collection.find_one({'uuid': video_uuid})

            if current_video_info:
                current_category_of_removed_video = current_video_info.get('category')

                remaining_in_same_category = [
                    b for b in existing_bookmarked_videos
                    if get_video_by_uuid(b['uuid']) and get_video_by_uuid(b['uuid']).get('category') == current_category_of_removed_video
                ]
                remaining_in_same_category.sort(key=lambda x: x.get('bookmarked_at', datetime.min.replace(tzinfo=timezone.utc)))

                if remaining_in_same_category:
                    # Show the next video in the same category (chronologically by bookmark date)
                    # For simplicity, let's just show the first one in that category after removal
                    next_video_uuid = remaining_in_same_category[0]['uuid']
                    next_video = get_video_by_uuid(next_video_uuid)

                    if next_video:
                        sent_success, sent_message_or_error = await send_and_replace_message(
                            client,
                            chat_id,
                            message_id_to_edit_or_delete=callback_query.message.id,
                            new_message_type="video",
                            video_data=next_video,
                            reply_markup=video_nav_keyboard(next_video['uuid'], current_category_of_removed_video, user_id, is_saved=True),
                            force_new_message=False # Try to edit the existing message
                        )
                        if not sent_success:
                            await client.send_message(chat_id, "❌ Failed to load next saved video. Please try again. 😥")
                    else:
                        await client.send_message(chat_id, "The next saved video was not found. It may have been removed.😔")
                else:
                    # No more saved videos in this category, go back to saved categories menu
                    await send_and_replace_message(
                        client,
                        chat_id,
                        message_id_to_edit_or_delete=callback_query.message.id,
                        new_message_type="text",
                        text_content="You have no more saved videos in this category. ❤️ Select another category or click '🎞️ Get Video' to find new ones!",
                        reply_markup=saved_category_keyboard(user_id)
                    )
            else: # If the original video info was missing, just go back to saved categories menu
                await send_and_replace_message(
                    client,
                    chat_id,
                    message_id_to_edit_or_delete=callback_query.message.id,
                    new_message_type="text",
                    text_content="The video was removed. Select another category or click '🎞️ Get Video' to find new ones!",
                    reply_markup=saved_category_keyboard(user_id)
                )
        else:
            await callback_query.answer("Video not found in your saved videos. 🧐", show_alert=True)
    except Exception as e:
        logger.error(f"Error removing saved video for user {user_id}, video {video_uuid}: {e}", exc_info=True)
        await callback_query.answer("❌ Failed to remove video. Please try again. 😥", show_alert=True)


# The view_saved_video_callback is effectively deprecated by the new direct display logic for "Saved Videos"
# but kept here in case future functionality explicitly links to individual saved videos from somewhere else.
@bot.on_callback_query(filters.regex(r"^view_saved_video_(.+)$"))
async def view_saved_video_callback(client: Client, callback_query: CallbackQuery):
    """Handles viewing a specific saved video."""
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id
    # Split by '_' and then take the part after 'view_saved_video_'
    video_uuid = callback_query.data.split('_', 3)[3]

    logger.info(f"User {user_id} requested to view saved video {video_uuid}.")

    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    create_tracked_task(check_premium_status_and_notify(client, user_id))

    if await is_rate_limited(user_id):
        await callback_query.answer("⚠️ You're Browse too quickly. Please wait a minute and try again. ⏳", show_alert=True)
        return

    current_active_tracked_message = active_video_message.get(user_id)
    if current_active_tracked_message and \
       current_active_tracked_message.get('message_id') == callback_query.message.id and \
       datetime.now(timezone.utc) - current_active_tracked_message.get('timestamp', datetime.min.replace(tzinfo=timezone.utc)) > timedelta(minutes=config.MENU_EXPIRY_MINUTES):

        logger.warning(f"User {user_id} tried to view saved video but menu expired.")
        await callback_query.answer("Menu expired. Click '🎞️ Get Video' to restart. ⏰", show_alert=True)
        try:
            await client.delete_messages(chat_id, callback_query.message.id)
        except MessageIdInvalid:
            pass
        except Exception as e:
                logger.warning(f"Failed to delete expired menu message for user {user_id}: {e}")
        clear_active_video_message(user_id)
        await client.send_message(chat_id, "Your menu has expired. Please click '🎞️ Get Video' to get a new one. ⏰")
        return

    if current_active_tracked_message and current_active_tracked_message.get('message_id') != callback_query.message.id:
        logger.warning(f"User {user_id} clicked old menu button. Callback Message ID: {callback_query.message.id}, Active Menu ID: {current_active_tracked_message.get('message_id')}")
        await callback_query.answer("This menu is outdated. Please use the latest one. 🔄", show_alert=True)
        try:
            await client.delete_messages(chat_id, callback_query.message.id)
        except MessageIdInvalid:
            pass
        except Exception as e:
            logger.warning(f"Failed to delete outdated menu message for user {user_id}: {e}")
        return

    wait_msg = await callback_query.message.reply("Just a moment, checking your access...")
    if not has_free_video_access(user_id, limit=1):
        await wait_msg.delete()
        await callback_query.answer("Human verification required! 🔐", show_alert=True)
        await send_token_earning_options(client, callback_query.message)
        return
    await wait_msg.delete()

    video = get_video_by_uuid(video_uuid)
    if not video:
        await callback_query.answer("Video not found or has been removed. 😔", show_alert=True)
        users_collection.update_one(
            {'user_id': user_id},
            {'$pull': {'bookmarked_videos': {'uuid': video_uuid}}}
        )
        return

    sent_success, sent_message_or_error = await send_and_replace_message(
        client,
        chat_id,
        message_id_to_edit_or_delete=callback_query.message.id,
        new_message_type="video",
        video_data=video,
        reply_markup=video_nav_keyboard(video['uuid'], video['category'], user_id, is_saved=True),
        force_new_message=False # Try to edit the existing message
    )

    if sent_success:
        mark_free_video_used(user_id)
        user_session_history[user_id] = {'category': video['category'], 'videos': [video['uuid']], 'position': 0, 'is_get_video': False, 'is_saved': True}
        save_history(user_id, video['uuid'], video['category'])
        await callback_query.answer()
        logger.info(f"User {user_id} viewed saved video {video_uuid}.")
    else:
        await callback_query.answer("❌ Failed to load saved video. Please try again.😥", show_alert=True)
        logger.error(f"User {user_id} failed to load saved video {video_uuid}: {sent_message_or_error}")


@bot.on_callback_query(filters.regex(r"^unavailable_(.+)$"))
async def unavailable_video_callback(client: Client, callback_query: CallbackQuery):
    """Handles clicks on unavailable videos in the saved list."""
    user_id = callback_query.from_user.id
    video_uuid = callback_query.data.split('_', 1)[1]

    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    await callback_query.answer("This video is no longer available. It may have been removed. 😔", show_alert=True)
    users_collection.update_one(
        {'user_id': user_id},
        {'$pull': {'bookmarked_videos': {'uuid': video_uuid}}}
    )
    logger.info(f"User {user_id} clicked unavailable video {video_uuid}. Removed from bookmarks.")

@bot.on_callback_query(filters.regex(r"^confirm_clear_all_saved$"))
async def confirm_clear_all_saved_callback(client: Client, callback_query: CallbackQuery):
    """Asks for confirmation before clearing all saved videos."""
    user_id = callback_query.from_user.id
    logger.info(f"User {user_id} requested to confirm clearing all saved videos.")

    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes, Clear All", callback_data="clear_all_saved_videos")],
        [InlineKeyboardButton("❌ No, Keep Them", callback_data="cancel_clear_saved")]
    ])

    await callback_query.message.edit_text(
        "⚠️ Are you sure you want to clear ALL your saved videos? This action cannot be undone.",
        reply_markup=reply_markup
    )
    await callback_query.answer()

@bot.on_callback_query(filters.regex(r"^clear_all_saved_videos$"))
async def clear_all_saved_videos_callback(client: Client, callback_query: CallbackQuery):
    """Clears all saved videos for the user."""
    user_id = callback_query.from_user.id
    logger.info(f"User {user_id} confirmed clearing all saved videos.")

    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    try:
        users_collection.update_one(
            {'user_id': user_id},
            {'$set': {'bookmarked_videos': []}}
        )
        await callback_query.message.edit_text("🗑️ All your saved videos have been cleared! ✨")
        await callback_query.answer("All saved videos cleared.")
        logger.info(f"User {user_id} successfully cleared all saved videos.")
    except Exception as e:
        logger.error(f"Error clearing all saved videos for user {user_id}: {e}", exc_info=True)
        await callback_query.answer("❌ Failed to clear saved videos. Please try again. 🐛", show_alert=True)
        await callback_query.message.edit_text("❌ Failed to clear saved videos. Please try again. 😥")

@bot.on_callback_query(filters.regex(r"^cancel_clear_saved$"))
async def cancel_clear_saved_callback(client: Client, callback_query: CallbackQuery):
    """Cancels clearing all saved videos."""
    user_id = callback_query.from_user.id
    logger.info(f"User {user_id} cancelled clearing all saved videos.")

    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    await callback_query.message.edit_text("Operation cancelled. Your saved videos are safe! ✅")
    await callback_query.answer("Operation cancelled.")


@bot.on_callback_query(filters.regex(r"^back_to_saved_cats$"))
async def back_to_saved_cats_callback(client: Client, callback_query: CallbackQuery):
    """Handles the 'Back' button from a saved video to the saved categories menu."""
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id
    logger.info(f"User {user_id} clicked 'Back' to saved categories menu.")

    active_menu = active_video_message.get(user_id)
    current_uuid = active_menu.get('video_uuid') if active_menu else None

    if not has_free_video_access(user_id, current_video_uuid=current_uuid):
        await callback_query.answer("Human verification required! 🔐", show_alert=True)
        await send_token_earning_options(client, callback_query.message)
        return

    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    try:
        await client.delete_messages(chat_id, callback_query.message.id)
        clear_active_video_message(user_id)
    except Exception as e:
        logger.warning(f"Could not delete message on 'Back' to saved cats: {e}")

    saved_cats_keyboard = saved_category_keyboard(user_id)
    if saved_cats_keyboard.inline_keyboard[0][0].callback_data in ["no_saved_videos", "no_valid_saved_videos"]:
        await client.send_message(chat_id, "You have no more saved videos. ❤️")
        return

    sent_message = await client.send_message(
        chat_id,
        "🗂️ <b>Select a Category from your Saved Videos:</b>",
        reply_markup=saved_cats_keyboard
    )
    set_active_video_message(user_id, sent_message.id, chat_id)
    await callback_query.answer()

@bot.on_callback_query(filters.regex(r"^get_default_video$"))
async def get_default_video_callback(client: Client, callback_query: CallbackQuery):
    """Handles the 'Get Video' button from the expiration message."""
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id
    logger.info(f"User {user_id} clicked 'Get Video' from expiration message.")

    if not await check_membership(client, user_id):
        await callback_query.answer("You must join our channels first!", show_alert=True)
        await send_force_subscribe_message(client, user_id)
        return

    create_tracked_task(check_premium_status_and_notify(client, user_id))

    if not has_free_video_access(user_id, limit=2):
        await callback_query.answer("Human verification required! 🔐", show_alert=True)
        await send_token_earning_options(client, callback_query.message)
        return

    video = get_random_video()
    if not video:
        await callback_query.answer("No videos available at the moment. Please try again later.", show_alert=True)
        return

    sent_success, _ = await send_and_replace_message(
        client,
        chat_id,
        message_id_to_edit_or_delete=callback_query.message.id,
        new_message_type="video",
        video_data=video,
        reply_markup=video_nav_keyboard(video['uuid'], "default (all)", user_id),
        force_new_message=True
    )
    if sent_success:
        mark_free_video_used(user_id)
        user_session_history[user_id] = {'videos': [video['uuid']], 'position': 0, 'is_get_video': True}
        save_history(user_id, video['uuid'], "default (all)")
    await callback_query.answer()

# --- NEW: Mini App Launch Handler ---

# --- Admin Commands ---
@bot.on_message(filters.command("broadcast") & filters.private & admin_only & filters.reply)
async def broadcast_cmd(client: Client, message: Message):
    """Admin command to broadcast a replied message to all users."""
    user_id = message.from_user.id
    replied_message = message.reply_to_message
    logger.info(f"Admin {user_id} initiated broadcast.")
    try:
        users_cursor = users_collection.find({}, {'user_id': 1})
        total_users = users_collection.count_documents({})
        broadcast_msg = await message.reply(f"📣 <b>Broadcasting</b> to <b>{total_users}</b> users... Please wait! 🚀")
        logger.info(f"Admin {user_id} initiating broadcast to {total_users} users.")

        success = 0
        blocked = 0
        failed = 0

        for user in users_cursor:
            try:
                await replied_message.copy(user['user_id'])
                success += 1
            except UserIsBlocked:
                blocked += 1
                logger.info(f"User {user['user_id']} blocked the bot during broadcast.")
            except ChatInvalid:
                failed += 1
                logger.error(f"Invalid chat for user {user['user_id']} during broadcast.")
            except FloodWait as e:
                logger.warning(f"User {user['user_id']} hit FloodWait during broadcast: {e.value} seconds. Pausing broadcast.")
                await asyncio.sleep(e.value + 1)
                try:
                    await replied_message.copy(user['user_id'])
                    success += 1
                    logger.info(f"Broadcast retry successful for user {user['user_id']}.")
                except Exception as retry_e:
                    failed += 1
                    logger.error(f"Broadcast retry failed for user {user['user_id']}: {retry_e}")
            except Exception as e:
                failed += 1
                logger.error(f"Broadcast failed for user {user['user_id']}: {e}")

            if (success + blocked + failed) % 25 == 0:
                await broadcast_msg.edit_text(
                    f"Broadcasting... 📡\n\n"
                    f"Progress: {success + blocked + failed}/{total_users}\n"
                    f"Successful: {success} ✅\n"
                    f"Blocked Users: {blocked} 🚫\n"
                    f"Unsuccessful: {failed} ❌"
                )
            await asyncio.sleep(0.5)

        await broadcast_msg.edit_text(
            f"Broadcast Completed! 🎉\n\n"
            f"Total Users: {total_users}\n"
            f"Successful: {success} ✅\n"
            f"Blocked Users: {blocked} 🚫\n"
            f"Unsuccessful: {failed} ❌"
        )
        logger.info(f"Broadcast completed by admin {user_id}. Success: {success}, Blocked: {blocked}, Failed: {failed}.")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to complete broadcast: {e}", exc_info=True)
        await message.reply("❌ An error occurred during broadcast. Check logs for details. 🐛")

@bot.on_message(filters.command("addcategory") & filters.private & admin_only)
async def addcategory_cmd(client: Client, message: Message):
    """Admin command to add a new video category."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} requested to add category.")
    try:
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            logger.warning(f"Admin {user_id} used addcategory with insufficient arguments.")
            await message.reply(
                "Usage: <code>/addcategory &lt;category_name&gt;</code>\n"
                "Category name can contain letters, numbers, spaces, underscores, hyphens, and emojis. 📝"
            )
            return

        name = args[1].strip() # Strip whitespace
        success, msg = add_category(name)
        if success:
            logger.info(f"Admin {user_id} successfully added category '{name}'.")
            await message.reply(f"✅ {msg}")
        else:
            logger.warning(f"Admin {user_id} failed to add category '{name}': {msg}")
            await message.reply(f"❌ {msg}")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to add category: {e}", exc_info=True)
        await message.reply("❌ An error occurred while adding category. Please try again. 🐛")

@bot.on_message(filters.command("deletecategory") & filters.private & admin_only)
async def deletecategory_cmd(client: Client, message: Message):
    """Admin command to delete a video category."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} requested to delete category.")
    try:
        categories = get_categories(for_admin_use=True)
        if not categories:
            logger.warning(f"Admin {user_id} tried to delete category but no categories exist.")
            await message.reply_text("😔 No categories to delete. Add some first! ➕")
            return

        buttons = []
        for category in categories:
            # Changed: Encode category name for callback data
            buttons.append([InlineKeyboardButton(f"🗑️ {html.escape(category)}", callback_data=f"confirmdelcat_{str_to_b64(category)}")])

        await message.reply_text(
            """Select a category to delete:

⚠️ All videos in the selected category will be deleted permanently. This action cannot be undone. Click on a category name below to confirm deletion.🚨""",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        logger.info(f"Admin {user_id}: Delete category options sent.")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to send delete category options: {e}", exc_info=True)
        await message.reply("❌ An error occurred while preparing delete category options. Please try again. 🐛")

@bot.on_callback_query(filters.regex(r"^confirmdelcat_(.+)$"))
async def confirm_delcat_callback(client: Client, callback_query: CallbackQuery):
    """Handles confirmation for category deletion."""
    user_id = callback_query.from_user.id
    # Changed: Decode category name from callback data
    category = b64_to_str(callback_query.data[14:])
    logger.info(f"Admin {user_id} confirmed deletion of category: {category}.")
    try:
        if not is_admin(user_id):
            await callback_query.answer("❌ Not authorized. 🚫", show_alert=True)
            logger.warning(f"Non-admin user {user_id} attempted to confirm category deletion.")
            return

        logger.warning(f"Admin {user_id} is confirming deletion of category: {category}")

        success, msg, deleted_count = delete_category(category)

        if success:
            formatted_msg = f"✅ Category '<b>{html.escape(category)}</b>' deleted, and <b>{deleted_count}</b> videos removed permanently. Use /addcategory to create new categories. ✨"
            await callback_query.message.edit_text(formatted_msg)
            logger.info(f"Admin {user_id} successfully deleted category {category} with {deleted_count} videos.")
        else:
            await callback_query.answer(msg, show_alert=True)
            await callback_query.message.edit_text(f"❌ Failed to delete category: {msg}")
            logger.error(f"Admin {user_id} failed to delete category {category}: {msg}")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to confirm category deletion: {e}", exc_info=True)
        await callback_query.answer("❌ An error occurred during category deletion. Please try again. 🐛", show_alert=True)

@bot.on_message(filters.command(["addtoken", "addpremium", "add_premium"]) & filters.private & admin_only)
async def addtoken_cmd(client: Client, message: Message):
    """Admin command to grant premium access to a specific user for a number of days."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} requested to add premium access.")
    try:
        args = message.text.split()
        if len(args) < 3:
            logger.warning(f"Admin {user_id} used addpremium with insufficient arguments: {message.text}")
            await message.reply("Usage: <code>/addpremium &lt;user_id&gt; &lt;num_days&gt;</code>\nExample: /addpremium 12345678 30 (for 30 days unlimited access) 📝")
            return

        target_user_id = int(args[1])

        if target_user_id <= 0:
            logger.warning(f"Admin {user_id} provided invalid target user ID: {target_user_id}.")
            await message.reply("User ID must be a positive integer. 🔢")
            return

        num_days = int(args[2])
        if num_days <= 0:
            logger.warning(f"Admin {user_id} provided invalid number of days: {num_days}.")
            await message.reply("Number of days must be a positive integer. 🔢")
            return

        user_doc = users_collection.find_one({'user_id': target_user_id})
        if not user_doc:
            logger.warning(f"Admin {user_id} attempted to add premium to non-existent user {target_user_id}.")
            await message.reply("User not found in database. 🧐")
            return

        # Grant unlimited access for specified number of days
        duration_seconds = num_days * 86400
        add_token_info = add_token(target_user_id, duration_seconds=duration_seconds, is_admin_granted=True)

        if not add_token_info:
            await message.reply("❌ Failed to grant premium access. Please try again. 🐛")
            return

        expiry_date = add_token_info['expires_at']
        logger.info(f"Admin {user_id} granted {num_days} days of premium to user {target_user_id}. Expires: {expiry_date}")
        await message.reply(f"✅ Granted <b>{num_days}</b> days of unlimited Premium access to user <b>{target_user_id}</b>. New expiry: {expiry_date.strftime('%Y-%m-%d %H:%M:%S UTC')}. 🎉")

        try:
            await client.send_message(target_user_id, f"🎉 <b>Congratulations!</b> You have been granted <b>{num_days}</b> days of unlimited Premium Access by an admin! Your access now expires on <b>{expiry_date.strftime('%Y-%m-%d %H:%M:%S UTC')}</b>. Enjoy exclusive features! 💎")
            users_collection.update_one(
                {'user_id': target_user_id},
                {'$set': {'last_premium_check_status': True}}
            )
        except (UserIsBlocked, ChatInvalid):
            logger.warning(f"Could not notify user {target_user_id} about premium access; user blocked or chat invalid.")
        except Exception as notify_e:
            logger.error(f"Failed to notify user {target_user_id} about premium access: {notify_e}")

    except ValueError:
        logger.warning(f"Admin {user_id} provided invalid input for addtoken: {message.text}")
        await message.reply("User ID and duration (in days) must be valid integers. 🔢")
    except Exception as e:
        logger.error(f"Admin {user_id} error adding tokens/premium access: {e}", exc_info=True)
        await message.reply("❌ Failed to add premium access. Please try again. 🐛")

@bot.on_message(filters.command(["removetoken", "removepremium", "remove_premium"]) & filters.private & admin_only)
async def removetoken_cmd(client: Client, message: Message):
    """Admin command to remove all premium access/tokens from a user."""
    admin_user_id = message.from_user.id
    logger.info(f"Admin {admin_user_id} requested to remove premium.")
    try:
        args = message.text.split()
        if len(args) < 2:
            logger.warning(f"Admin {admin_user_id} used removepremium with insufficient arguments: {message.text}")
            await message.reply("Usage: <code>/removepremium &lt;user_id&gt;</code> 📝")
            return

        target_user_id = int(args[1])

        if target_user_id <= 0:
            logger.warning(f"Admin {admin_user_id} provided invalid target user ID: {target_user_id}.")
            await message.reply("User ID must be a positive integer. 🔢")
            return

        if is_owner(target_user_id):
            await message.reply("❌ You cannot remove the owner's access.")
            return

        user_doc = users_collection.find_one({'user_id': target_user_id})
        if not user_doc:
            logger.warning(f"Admin {admin_user_id} attempted to remove tokens from non-existent user {target_user_id}.")
            await message.reply("User not found in database. 🧐")
            return

        # Remove all tokens for the user
        result = tokens_collection.delete_one({'user_id': target_user_id})

        if result.deleted_count > 0:
            # Update the user's premium status in the users collection
            users_collection.update_one(
                {'user_id': target_user_id},
                {'$set': {'last_premium_check_status': False}}
            )
            logger.info(f"Admin {admin_user_id} removed premium access for user {target_user_id}.")
            await message.reply(f"✅ Premium access and all active tokens for user <b>{target_user_id}</b> have been revoked.")

            try:
                await client.send_message(target_user_id, "⚠️ Your Premium Access has been revoked by an administrator.")
            except (UserIsBlocked, ChatInvalid):
                logger.warning(f"Could not notify user {target_user_id} about premium removal; user blocked or chat invalid.")
            except Exception as notify_e:
                logger.error(f"Failed to notify user {target_user_id} about premium removal: {notify_e}")
        else:
            await message.reply(f"User <b>{target_user_id}</b> had no active Premium Access to remove.")
            logger.info(f"Admin {admin_user_id} attempted to remove premium, but user {target_user_id} had none.")

    except ValueError:
        logger.warning(f"Admin {admin_user_id} provided invalid input for removetoken: {message.text}")
        await message.reply("User ID must be a valid integer. 🔢")
    except Exception as e:
        logger.error(f"Admin {admin_user_id} error removing tokens: {e}", exc_info=True)
        await message.reply("❌ Failed to remove tokens. Please try again. 🐛")

@bot.on_message(filters.command("removeallnewuserfreescrolls") & filters.private & admin_only)
async def remove_all_new_user_free_scrolls_cmd(client: Client, message: Message):
    """Admin command to remove all new user free scrolls from all users."""
    admin_user_id = message.from_user.id
    logger.info(f"Admin {admin_user_id} initiated /removeallnewuserfreescrolls command.")

    try:
        # This operation updates all documents in the users_collection.
        # It sets the 'new_user_scrolls_used' field to the value of config.NEW_USER_SCROLLS.
        result = users_collection.update_many(
            {},
            {'$set': {'new_user_scrolls_used': config.NEW_USER_SCROLLS}}
        )

        # result.modified_count will contain the number of users that were updated.
        updated_count = result.modified_count

        await message.reply(
            f"✅ Successfully removed all new user free scrolls for <b>{updated_count}</b> users."
        )
        logger.info(f"Admin {admin_user_id} successfully removed new user free scrolls for {updated_count} users.")

    except Exception as e:
        logger.error(f"Admin {admin_user_id} failed during /removeallnewuserfreescrolls: {e}", exc_info=True)
        await message.reply("❌ An error occurred while removing new user free scrolls. Please check the logs. 🐛")

# --- Batch Add Videos ---

async def delayed_start_processing(user_id: int, client: Client):
    """Waits for 5 seconds of silence before starting batch processing."""
    try:
        await asyncio.sleep(5)
        state = batch_add_state.get(user_id)
        if state and not state.get('is_processing') and state.get('video_queue'):
            state['is_processing'] = True
            await process_batch_queue(user_id, client)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"Error in delayed_start_processing for user {user_id}: {e}", exc_info=True)

async def process_batch_queue(user_id: int, client: Client):
    """Processes a queue of videos for batch adding, handling rate limits."""
    state = batch_add_state.get(user_id)
    if not state or not state.get('batch_mode'):
        if state: state['is_processing'] = False
        return

    logger.info(f"Starting batch processing queue for admin {user_id}.")
    queue = state['video_queue']

    if not DATA_CHANNEL_ID:
        await client.send_message(user_id, "❌ Video storage channel is not configured. Please set it using /setdata before adding videos.")
        state['is_processing'] = False
        return

    while batch_add_state.get(user_id, {}).get('batch_mode'):
        if not queue:
            state['is_processing'] = False
            # Double check to prevent race condition
            if not queue:
                break
            state['is_processing'] = True

        message = queue.popleft()
        category = state['current_category']

        try:
            file_unique_id = message.video.file_unique_id
            existing_video = media_collection.find_one({"file_unique_id": file_unique_id})
            if existing_video:
                link = get_channel_msg_link(DATA_CHANNEL_ID, existing_video.get('message_id'))
                link_text = f"\nLink: {link}" if link else ""
                await message.reply_text(f"⚠️ This video has already been added. Skipping.{link_text}")
                continue

            caption_to_use = message.caption or f"Category: {category}"
            sent_video_message = await client.send_video(
                chat_id=DATA_CHANNEL_ID, video=message.video.file_id,
                caption=caption_to_use
            )
            if not sent_video_message or not sent_video_message.video:
                raise Exception("send_video did not return a valid video message.")

            video_uuid = str(uuid.uuid4())
            next_sequence_number = state['next_sequence']
            video_data = {
                "uuid": video_uuid, "file_id": sent_video_message.video.file_id,
                "file_unique_id": file_unique_id, "category": category,
                "timestamp": get_current_time(),
                "sequence_number": next_sequence_number, "message_id": sent_video_message.id,
                "banned": False, "custom_caption": message.caption
            }
            media_collection.insert_one(video_data)
            state['next_sequence'] += 1
            state['videos_this_session'] += 1

            await message.reply_text(
                f"✅ File Added to <b>{html.escape(category)}</b>!\n"
                f"🔢 Sequence: {next_sequence_number}\n"
                f"Videos processed this session: <b>{state['videos_this_session']}</b>"
            )
            logger.info(f"Successfully processed video for {user_id}. Waiting 5 seconds.")
            await asyncio.sleep(5)

        except FloodWait as e:
            logger.warning(f"FloodWait encountered for admin {user_id}. Waiting for {e.value} seconds.")
            await message.reply_text(f"⏳ FloodWait from Telegram. Pausing for {e.value + 1} seconds. The bot will resume automatically.")
            queue.appendleft(message)
            await asyncio.sleep(e.value + 1)

        except Exception as e:
            logger.error(f"Admin {user_id} error adding video from queue: {e}", exc_info=True)
            await message.reply("❌ Failed to add this video due to an error. Check logs. Skipping.")

    if batch_add_state.get(user_id):
        batch_add_state[user_id]['is_processing'] = False
        if not batch_add_state[user_id]['video_queue']:
            logger.info(f"Batch processing queue for admin {user_id} is now empty.")
            await client.send_message(user_id, "✅ All queued videos have been processed. You can send more videos or type /done.")
        else:
            logger.info(f"Batch processing stopped for admin {user_id}. {len(batch_add_state[user_id]['video_queue'])} videos remain in queue.")

@bot.on_message(filters.command("batchadd") & filters.private & admin_only)
async def batchadd_cmd(client: Client, message: Message):
    """Admin command to enter batch video adding mode and choose category."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} initiated batch add mode.")
    try:
        if not DATA_CHANNEL_ID:
            await message.reply("❌ Video storage channel is not configured. Please set it using /setdata before adding videos.")
            return

        categories = get_categories()
        if not categories:
            await message.reply("⚠️ No categories exist. Please create at least one category using /addcategory before starting batch add. ➕")
            logger.warning(f"Admin {user_id} tried to start batch add with no categories.")
            return

        buttons = []
        for category in categories:
            buttons.append([InlineKeyboardButton(f"🗂️ {html.escape(category)}", callback_data=f"batchselcat_{str_to_b64(category)}")])

        await message.reply(
            "🎬 <b>Choose a Category for Batch Adding:</b>",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        logger.info(f"Admin {user_id}: Prompted to choose category for batch add.")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to initiate batch add mode: {e}", exc_info=True)
        await message.reply("❌ An error occurred while starting batch add mode. Please try again. 🐛")

@bot.on_callback_query(filters.regex(r"^batchselcat_(.+)$"))
async def batch_select_category_callback(client: Client, callback_query: CallbackQuery):
    """Handles callback for selecting the category in batch add mode."""
    user_id = callback_query.from_user.id
    category_name = b64_to_str(callback_query.data[12:])
    logger.info(f"Admin {user_id} selected category for batch adding: {category_name}.")
    try:
        if not is_admin(user_id):
            await callback_query.answer("❌ Not authorized. 🚫", show_alert=True)
            return

        if not DATA_CHANNEL_ID:
            await callback_query.answer("❌ Video storage channel is not configured. Please set it using /setdata.", show_alert=True)
            return

        if category_name not in get_categories():
            await callback_query.answer(f"❌ Invalid category '<b>{html.escape(category_name)}</b>'. 🧐", show_alert=True)
            await callback_query.message.edit_text(
                "Category not found. Please try again! 🧐",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"🗂️ {html.escape(cat)}", callback_data=f"batchselcat_{str_to_b64(cat)}")] for cat in get_categories()])
            )
            return

        last_video_in_category = media_collection.find_one(
            {'category': category_name},
            sort=[('sequence_number', DESCENDING)]
        )
        next_sequence_for_batch = 1
        if last_video_in_category and 'sequence_number' in last_video_in_category:
            next_sequence_for_batch = last_video_in_category['sequence_number'] + 1

        batch_add_state[user_id] = {
            'batch_mode': True,
            'current_category': category_name,
            'videos_this_session': 0,
            'next_sequence': next_sequence_for_batch,
            'video_queue': deque(),
            'is_processing': False
        }

        logger.info(f"Admin {user_id} starting batch add for category '{category_name}'. Next sequence will start from: {next_sequence_for_batch}")

        await callback_query.message.edit_text(
            f"✅ You are now in batch add mode for category: <b>{html.escape(category_name)}</b>! 🎉\n"
            f"The next video will be sequence <b>{next_sequence_for_batch}</b>.\n"
            "Send me videos to add. They will be processed one by one. Type /done when finished. ✅\n"
            "You can use /category to change the current batch category without exiting batch mode. 🔄"
        )
        await callback_query.answer(f"Category set to '{html.escape(category_name)}'")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to set batch category in callback: {e}", exc_info=True)
        await callback_query.answer("❌ An error occurred while setting category. Please try again. 🐛", show_alert=True)

@bot.on_message(filters.command(["stop", "done"]) & filters.private & admin_only)
async def stop_cmd(client: Client, message: Message):
    """Admin command to stop any active process (batch add, delete video, etc.)."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} used stop/done command.")
    try:
        cleared_states = []

        if admin_delete_video_state.get(user_id):
            del admin_delete_video_state[user_id]
            cleared_states.append("Video Deletion")

        if user_id in admin_batch_link_state:
            del admin_batch_link_state[user_id]
            cleared_states.append("Batch Link Creation")

        if user_id in batch_add_state:
            state = batch_add_state[user_id]
            total_added = state.get('videos_this_session', 0)
            remaining_in_queue = len(state.get('video_queue', []))
            del batch_add_state[user_id]

            if user_id in batch_processing_timers:
                batch_processing_timers[user_id].cancel()
                del batch_processing_timers[user_id]

            msg = f"Batch Add (Added: {total_added}"
            if remaining_in_queue:
                msg += f", Remaining: {remaining_in_queue}"
            msg += ")"
            cleared_states.append(msg)

        # Clear other possible states
        for state_dict in [admin_shortener_setup_state, admin_rename_category_state,
                        admin_delete_user_state, admin_fsub_state, admin_data_channel_state]:
            if user_id in state_dict:
                del state_dict[user_id]
                if "Input Flows" not in cleared_states:
                    cleared_states.append("Input Flows")

        if cleared_states:
            await message.reply(f"✅ Process stopped: {', '.join(cleared_states)}")
        else:
            await message.reply("No active process to stop.")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to disable batch add mode: {e}", exc_info=True)
        await message.reply("❌ An error occurred while ending batch add mode. Please try again. 🐛")

@bot.on_message(filters.video & filters.private)
async def handle_incoming_videos(client: Client, message: Message):
    """Handles incoming videos for both users (uploads) and admins (modes)."""
    user_id = message.from_user.id

    # --- Admin Mode Handling ---
    if is_admin(user_id):
        if admin_delete_video_state.get(user_id):
            logger.info(f"Admin {user_id} sent a video for deletion.")
            try:
                file_unique_id = message.video.file_unique_id
                video_to_delete = media_collection.find_one({"file_unique_id": file_unique_id})
                if not video_to_delete:
                    await message.reply_text("❌ Video not found in the database.")
                    return
                success = await delete_broken_video_from_db_and_channel(
                    client, video_to_delete['uuid'], video_to_delete.get('category'),
                    video_to_delete.get('sequence_number'), video_to_delete.get('message_id')
                )
                if success:
                    await message.reply_text(f"✅ Video (UUID: <code>{video_to_delete['uuid']}</code>) deleted.\n\nSend /stop to stop the process.")
                else:
                    await message.reply_text(f"❌ Failed to delete video (UUID: <code>{video_to_delete['uuid']}</code>).\n\nSend /stop to stop the process.")
            except Exception as e:
                logger.error(f"Admin {user_id} error deleting video: {e}", exc_info=True)
                await message.reply("❌ An error occurred while deleting the video.\n\nSend /stop to stop the process.")
            return

        if user_id in admin_batch_link_state:
            logger.info(f"Admin {user_id} sent a video for batch link creation.")
            file_unique_id = message.video.file_unique_id
            video_doc = media_collection.find_one({"file_unique_id": file_unique_id}, {"uuid": 1})
            if video_doc:
                admin_batch_link_state[user_id].append(video_doc['uuid'])
                await message.reply(f"✅ Video added to batch. Total: {len(admin_batch_link_state[user_id])}.")
            else:
                await message.reply("⚠️ This video is not in the database. Please add it first using /batchadd.")
            return

        if batch_add_state.get(user_id, {}).get('batch_mode'):
            if not DATA_CHANNEL_ID:
                await message.reply("❌ Video storage channel is not configured. Please set it using /setdata before adding videos.")
                return

            logger.info(f"Admin {user_id} queued a video for batch adding.")
            state = batch_add_state[user_id]
            state['video_queue'].append(message)

            queue_text = f"✅ Video queued for category <b>{html.escape(state['current_category'])}</b>. Position in queue: {len(state['video_queue'])}."

            if state.get('last_msg_id'):
                try:
                    await client.edit_message_text(message.chat.id, state['last_msg_id'], queue_text)
                except Exception:
                    sent = await message.reply_text(queue_text)
                    state['last_msg_id'] = sent.id
            else:
                sent = await message.reply_text(queue_text)
                state['last_msg_id'] = sent.id

            if not state.get('is_processing'):
                if user_id in batch_processing_timers:
                    batch_processing_timers[user_id].cancel()

                logger.info(f"Setting/Resetting batch processing timer for admin {user_id}.")
                batch_processing_timers[user_id] = create_tracked_task(delayed_start_processing(user_id, client))
            else:
                logger.info(f"Batch processing task for admin {user_id} is already running.")
            return

        if user_id in admin_rename_category_state and admin_rename_category_state[user_id].get('step') == 'chg_cat_await_video':
            logger.info(f"Admin {user_id} sent video for re-categorization.")
            file_unique_id = message.video.file_unique_id
            video_doc = media_collection.find_one({"file_unique_id": file_unique_id})
            if not video_doc:
                await message.reply("❌ Video not found in database. Please send a valid UUID or send a video.")
                return

            video_uuid = video_doc['uuid']
            categories = get_categories(for_admin_use=True)
            if not categories:
                await message.reply("⚠️ No categories available. Please create one using /addcategory first.")
                del admin_rename_category_state[user_id]
                return

            buttons = []
            for idx, cat in enumerate(categories):
                buttons.append([InlineKeyboardButton(f"🗂️ {cat}", callback_data=f"chg_cat_{video_uuid}_{idx}")])

            await message.reply(
                f"Select the **new category** for this video (Current: <code>{video_doc.get('category')}</code>):",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
            del admin_rename_category_state[user_id]
            return

        logger.warning(f"Admin {user_id} sent video outside of any active admin mode, ignoring.")
        return

    # --- User Upload Handling ---
    if user_upload_state.get(user_id, {}).get('in_upload_mode'):
        # --- Check Session Cooldown ---
        now = datetime.now(timezone.utc)
        limit_mins = UPLOAD_CONFIG.get('session_limit_minutes', 10)
        limit_count = UPLOAD_CONFIG.get('session_limit_count', 10)

        recent_uploads = list(pending_uploads_collection.find({
            "user_id": user_id,
            "submitted_at": {"$gt": now - timedelta(minutes=limit_mins)}
        }))
        if len(recent_uploads) >= limit_count:
            await message.reply_text(f"⏳ **Slow down!** You can only upload {limit_count} videos every {limit_mins} minutes. Please wait a bit. 🛑")
            return

        await handle_user_upload(client, message)
        return

async def handle_user_upload(client: Client, message: Message):
    """Processes a video uploaded by a user."""
    user_id = message.from_user.id
    file_unique_id = message.video.file_unique_id

    # 1. Membership check (redundant but safe)
    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    # 2. Duplicate Check
    existing_in_media = media_collection.find_one({"file_unique_id": file_unique_id})
    if existing_in_media:
        await message.reply_text("🙏 **Thank you!** But this video already exists in our collection. Please send something new! ✨")
        return

    existing_in_pending = pending_uploads_collection.find_one({"file_unique_id": file_unique_id})
    if existing_in_pending:
        await message.reply_text("⏳ This video is already under review! Thank you for your patience. ❤️")
        return

    # 3. Rate Limiting Check
    user_doc = users_collection.find_one({'user_id': user_id})
    stats = user_doc.get('upload_stats', {})

    # Daily max check
    now = datetime.now(timezone.utc)
    daily = stats.get('daily_uploads', {})
    if now > daily.get('reset_at', datetime.min.replace(tzinfo=timezone.utc)):
        daily = {'count': 0, 'reset_at': now + timedelta(hours=24)}

    if daily['count'] >= UPLOAD_CONFIG['daily_max']:
        await message.reply_text(f"🛑 You've reached your daily limit of {UPLOAD_CONFIG['daily_max']} uploads. Come back tomorrow! 📅")
        return

    # Pending count check
    max_pend = UPLOAD_CONFIG.get('max_pending', 30)
    if stats.get('pending_count', 0) >= max_pend:
        await message.reply_text(f"🛑 You have {max_pend} pending uploads. Please wait for them to be reviewed before sending more! ⏳")
        return

    # 4. Store in pending_uploads
    upload_id = str(uuid.uuid4())
    category = user_upload_state[user_id].get('selected_category')
    pending_data = {
        "upload_id": upload_id,
        "user_id": user_id,
        "file_id": message.video.file_id,
        "file_unique_id": file_unique_id,
        "status": "pending",
        "submitted_at": now,
        "caption": message.caption,
        "message_id_in_user_chat": message.id,
        "category": category
    }
    pending_uploads_collection.insert_one(pending_data)

    # 5. Update User Stats & Session Count
    user_upload_state[user_id]['session_uploads'] = user_upload_state[user_id].get('session_uploads', 0) + 1
    session_count = user_upload_state[user_id]['session_uploads']
    min_req = UPLOAD_CONFIG.get('min_upload_count', 1)

    users_collection.update_one(
        {'user_id': user_id},
        {
            '$inc': {'upload_stats.total_uploads': 1, 'upload_stats.pending_count': 1, 'upload_stats.daily_uploads.count': 1},
            '$set': {'upload_stats.daily_uploads.reset_at': daily['reset_at']}
        }
    )

    # 6. Grant Reward (Temp Scrolls) immediately on every upload
    reward_granted = False
    threshold_met = (session_count % min_req == 0) if min_req > 0 else True

    if UPLOAD_CONFIG['auto_give_scrolls']:
        expiry_hours = UPLOAD_CONFIG.get('temp_scrolls_expiry_hours', 0)
        temp_scroll_expiry = (now + timedelta(hours=expiry_hours)) if expiry_hours > 0 else None
        temp_scroll_entry = {
            'amount': UPLOAD_CONFIG['temp_scrolls_amount'],
            'expires_at': temp_scroll_expiry,
            'upload_id': upload_id
        }
        users_collection.update_one(
            {'user_id': user_id},
            {'$push': {'temp_scrolls': temp_scroll_entry}}
        )
        reward_granted = True

    # 7. Notify User
    if UPLOAD_CONFIG['auto_give_scrolls']:
        reward_text = f" You received **{UPLOAD_CONFIG['temp_scrolls_amount']} temporary scrolls** while waiting."
    else:
        if threshold_met:
            reward_text = ""
        else:
            more_needed = min_req - (session_count % min_req)
            reward_text = f"\n\n🚀 **Upload {more_needed} more video(s)** to receive your waiting reward!"

    confirmation = (
        "✅ **Video received! Thank you for contributing.**\n\n"
        f"Videos uploaded this session: **{session_count}**\n"
        f"Status: `Pending Approval` ⏳\n\n"
        f"Your contribution is under review.{reward_text}"
    )
    sent_confirmation = await message.reply_text(confirmation)

    # Store confirmation message ID to edit later
    pending_uploads_collection.update_one(
        {"upload_id": upload_id},
        {"$set": {"confirmation_message_id": sent_confirmation.id}}
    )

    # 8. Notify Admins
    await notify_admins_of_upload(client, pending_data)

async def notify_admins_of_upload(client: Client, upload_data: dict):
    """Sends a notification to the review chat or admins about a new upload."""
    user_id = upload_data['user_id']
    upload_id = upload_data['upload_id']

    text = (
        "🆕 **New Video Uploaded for Review!**\n\n"
        f"👤 **User:** `{user_id}`\n"
        f"📅 **Time:** {upload_data['submitted_at'].strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        f"🗂️ **Suggested Category:** `{upload_data.get('category') or 'None'}`\n"
        f"📝 **Caption:** {upload_data.get('caption') or 'None'}\n\n"
        "Select an action below:"
    )

    # Buttons for notification
    if upload_data.get('category'):
        categories = get_categories(for_admin_use=True)
        if upload_data['category'] in categories:
            cat_idx = categories.index(upload_data['category'])
            approve_cb = f"apr_cat_{upload_id}_{cat_idx}"
        else:
            approve_cb = f"apr_cat_{upload_id}_{str_to_b64(upload_data['category'])}"

        reply_markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Approve", callback_data=approve_cb),
                InlineKeyboardButton("❌ Reject", callback_data=f"adm_rejc_{upload_id}")
            ],
            [
                InlineKeyboardButton("🗂️ Change Category", callback_data=f"adm_appr_{upload_id}")
            ]
        ])
    else:
        reply_markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"adm_appr_{upload_id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"adm_rejc_{upload_id}")
            ]
        ])

    if REVIEW_CHAT_ID:
        try:
            await client.copy_message(
                chat_id=REVIEW_CHAT_ID,
                from_chat_id=user_id,
                message_id=upload_data['message_id_in_user_chat'],
                caption=text,
                reply_markup=reply_markup
            )
            return
        except Exception as e:
            logger.error(f"Failed to forward to review chat {REVIEW_CHAT_ID}: {e}")

    # Fallback: send to all admins
    for admin_id in BOT_ADMINS:
        try:
            await client.copy_message(
                chat_id=admin_id,
                from_chat_id=user_id,
                message_id=upload_data['message_id_in_user_chat'],
                caption=text,
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.warning(f"Failed to notify admin {admin_id} about upload: {e}")


@bot.on_message(filters.command("category") & filters.private & admin_only)
async def set_category_cmd(client: Client, message: Message):
    """Admin command to set the current category for batch adding."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} requested to set category for batch add.")
    try:
        if user_id not in batch_add_state or not batch_add_state[user_id].get('batch_mode', False):
            logger.warning(f"Admin {user_id} tried to set category outside of batch add mode.")
            await message.reply_text("❌ Error: Start batch mode with /batchadd first. 🚀")
            return

        categories = get_categories()
        if not categories:
            logger.warning(f"Admin {user_id} tried to set category but no categories available.")
            await message.reply_text("⚠️ No categories available to set. Use /addcategory to create one.➕")
            return

        buttons = []
        for category in categories:
            # Changed: Encode category name for callback data
            buttons.append([InlineKeyboardButton(f"🗂️ {html.escape(category)}", callback_data=f"setcat_{str_to_b64(category)}")])

        await message.reply_text(
            "Select a category for batch adding videos: 👇",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        logger.info(f"Admin {user_id}: Set category options sent.")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to send set category options: {e}", exc_info=True)
        await message.reply("❌ An error occurred while preparing set category options. Please try again. 🐛")

@bot.on_callback_query(filters.regex(r"^setcat_(.+)$"))
async def setcat_callback(client: Client, callback_query: CallbackQuery):
    """Handles callback for setting the batch add category."""
    user_id = callback_query.from_user.id
    logger.info(f"Admin {user_id} selected category for batch adding: {callback_query.data[7:]}.")
    try:
        match = re.match(r"^setcat_(.+)$", callback_query.data)
        if not match:
            await callback_query.answer("❌ Invalid category data. 🐛", show_alert=True)
            logger.warning(f"Admin {user_id} received invalid category data in setcat_callback: {callback_query.data}.")
            return
        # Changed: Decode category name from callback data
        category_name = b64_to_str(match.group(1))

        if not is_admin(user_id):
            await callback_query.answer("❌ Only admins can use this command. 🚫", show_alert=True)
            logger.warning(f"Non-admin user {user_id} attempted to set batch category.")
            return

        if user_id not in batch_add_state or not batch_add_state[user_id].get('batch_mode', False):
            await callback_query.answer("❌ Error: Batch mode not active. 🚫", show_alert=True)
            logger.warning(f"Admin {user_id} tried to set category but batch mode not active.")
            return

        if category_name not in get_categories():
            await callback_query.answer(f"❌ Invalid category '<b>{html.escape(category_name)}</b>'. 🧐", show_alert=True)
            await callback_query.message.edit_text(
                "Category not found. Please try again! 🧐",
                # Changed: Encode category name for callback data in error case
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"🗂️ {html.escape(cat)}", callback_data=f"setcat_{str_to_b64(cat)}")] for cat in get_categories()])
            )
            logger.warning(f"Admin {user_id} tried to set invalid category: '{category_name}'.")
            return

        # When changing category within batch mode, re-calculate the next sequence for the new category
        last_video_in_category = media_collection.find_one(
            {'category': category_name},
            sort=[('sequence_number', DESCENDING)]
        )
        next_sequence_for_batch = 1
        if last_video_in_category and 'sequence_number' in last_video_in_category:
            next_sequence_for_batch = last_video_in_category['sequence_number'] + 1

        batch_add_state[user_id]['current_category'] = category_name
        batch_add_state[user_id]['next_sequence'] = next_sequence_for_batch # Update next_sequence for the new category

        await callback_query.message.edit_text(
            f"✅ Category set to '<b>{html.escape(category_name)}</b>' for batch adding. 🎉\n"
            f"The next video will be sequence <b>{next_sequence_for_batch}</b>.\n"
            "Send videos now or use /done to finish. 🎥"
        )
        await callback_query.answer(f"Category set to '{html.escape(category_name)}'")
        logger.info(f"Admin {user_id} successfully set batch category to '{category_name}'. Next sequence: {next_sequence_for_batch}.")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to set batch category: {e}", exc_info=True)
        await callback_query.answer("❌ An error occurred while setting category. Please try again. 🐛", show_alert=True)

@bot.on_message(filters.command("viewtoken") & filters.private & admin_only)
async def view_token_cmd(client: Client, message: Message):
    """Admin command to view users with the most tokens."""
    try:
        await view_token_page(client, message)
    except Exception as e:
        logger.error(f"Error in /viewtoken command: {e}", exc_info=True)
        await message.reply("An error occurred while fetching token stats.")

async def view_token_page(client: Client, message_or_query, page: int = 0):
    """Helper function to display a page of the token leaderboard."""
    now = datetime.now(timezone.utc)
    pipeline = [
        {"$unwind": "$tokens"},
        {"$match": {"tokens.expires_at": {"$gt": now}}},
        {"$group": {"_id": "$user_id", "token_count": {"$sum": 1}}},
        {"$sort": {"token_count": -1}}
    ]
    all_users = list(tokens_collection.aggregate(pipeline))

    total_users = len(all_users)
    if total_users == 0:
        text = "No users with active tokens found."
        if isinstance(message_or_query, Message):
            await message_or_query.reply(text)
        else: # CallbackQuery
            await message_or_query.answer(text, show_alert=True)
        return

    start_index = page * 10
    end_index = start_index + 10
    users_on_page = all_users[start_index:end_index]

    text = "👑 **Top Users by Token Count** 👑\n\n"

    # Fetch user info in a single query
    user_ids = [user_data['_id'] for user_data in users_on_page]
    user_info_map = {user['user_id']: user for user in users_collection.find({"user_id": {"$in": user_ids}})}

    for i, user_data in enumerate(users_on_page):
        user_id = user_data['_id']
        token_count = user_data['token_count']
        rank = start_index + i + 1

        user_info = user_info_map.get(user_id)
        username = f"@{user_info['username']}" if user_info and user_info.get('username') else "N/A"

        text += f"**{rank}.** `{user_id}` ({username}) - **{token_count}** tokens\n"

    total_pages = (total_users + 9) // 10
    text += f"\nPage {page + 1} of {total_pages}"

    buttons = []
    row = []
    if page > 0:
        row.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"viewtoken_{page - 1}"))
    if end_index < total_users:
        row.append(InlineKeyboardButton("➡️ Next", callback_data=f"viewtoken_{page + 1}"))
    if row:
        buttons.append(row)

    reply_markup = InlineKeyboardMarkup(buttons) if buttons else None

    if isinstance(message_or_query, Message):
        await message_or_query.reply(text, reply_markup=reply_markup)
    else: # CallbackQuery
        await message_or_query.message.edit_text(text, reply_markup=reply_markup)
        await message_or_query.answer()

@bot.on_callback_query(filters.regex(r"^viewtoken_(\d+)$"))
async def view_token_callback(client: Client, callback_query: CallbackQuery):
    """Callback for /viewtoken pagination."""
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("Not authorized.", show_alert=True)
        return

    page = int(callback_query.data.split("_")[1])
    try:
        await view_token_page(client, callback_query, page)
    except Exception as e:
        logger.error(f"Error in viewtoken callback: {e}", exc_info=True)
        await callback_query.answer("An error occurred.", show_alert=True)

@bot.on_message(filters.command("showuserscrolls") & filters.private & admin_only)
async def show_user_scrolls_cmd(client: Client, message: Message):
    """Admin command to show all users and their scrolls remaining with pagination."""
    try:
        await show_user_scrolls_page(client, message)
    except Exception as e:
        logger.error(f"Error in /showuserscrolls command: {e}", exc_info=True)
        await message.reply("An error occurred while fetching user scrolls stats.")

async def show_user_scrolls_page(client: Client, message_or_query, page: int = 0):
    """Helper function to display a page of the users and their scrolls remaining."""
    now = datetime.now(timezone.utc)
    all_users = list(users_collection.find({}, {
        "user_id": 1,
        "username": 1,
        "first_name": 1,
        "permanent_scrolls": 1,
        "temp_scrolls": 1
    }))

    calculated_users = []
    for user in all_users:
        user_id = user['user_id']
        perm = user.get('permanent_scrolls', 0)
        temp = user.get('temp_scrolls', [])
        valid_temp_count = sum(
            s.get('amount', 0) for s in temp
            if s.get('amount', 0) > 0 and (s.get('expires_at') is None or s['expires_at'] > now)
        )
        total = perm + valid_temp_count

        username = f"@{user['username']}" if user.get('username') else (user.get('first_name') or "User")
        calculated_users.append({
            'user_id': user_id,
            'username': username,
            'scrolls': total
        })

    # Sort users by scrolls count descending
    calculated_users.sort(key=lambda x: x['scrolls'], reverse=True)

    total_users = len(calculated_users)
    if total_users == 0:
        text = "No registered users found."
        if isinstance(message_or_query, Message):
            await message_or_query.reply(text)
        else:
            await message_or_query.answer(text, show_alert=True)
        return

    start_index = page * 10
    end_index = start_index + 10
    users_on_page = calculated_users[start_index:end_index]

    text = "📜 **User Scrolls Leaderboard** 📜\n\n"

    for i, user_data in enumerate(users_on_page):
        rank = start_index + i + 1
        username_display = html.escape(user_data['username'])
        text += f"**{rank}.** `{user_data['user_id']}` ({username_display}) - **{user_data['scrolls']}** scrolls remaining\n"

    total_pages = (total_users + 9) // 10
    text += f"\nPage {page + 1} of {total_pages} (Total Users: {total_users})"

    buttons = []
    row = []
    if page > 0:
        row.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"showscrolls_{page - 1}"))
    if end_index < total_users:
        row.append(InlineKeyboardButton("➡️ Next", callback_data=f"showscrolls_{page + 1}"))
    if row:
        buttons.append(row)

    reply_markup = InlineKeyboardMarkup(buttons) if buttons else None

    if isinstance(message_or_query, Message):
        await message_or_query.reply(text, reply_markup=reply_markup)
    else: # CallbackQuery
        await message_or_query.message.edit_text(text, reply_markup=reply_markup)
        await message_or_query.answer()

@bot.on_callback_query(filters.regex(r"^showscrolls_(\d+)$"))
async def show_user_scrolls_callback(client: Client, callback_query: CallbackQuery):
    """Callback query handler for showuserscrolls pagination."""
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("Not authorized.", show_alert=True)
        return

    page = int(callback_query.data.split("_")[1])
    try:
        await show_user_scrolls_page(client, callback_query, page)
    except Exception as e:
        logger.error(f"Error in showscrolls callback: {e}", exc_info=True)
        await callback_query.answer("An error occurred.", show_alert=True)

@bot.on_message(filters.command("stats") & filters.private & admin_only)
async def stats_cmd(client: Client, message: Message):
    """Admin command to display bot statistics, including category video counts."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} requested stats.")
    try:
        total_users = users_collection.count_documents({})
        total_videos = media_collection.count_documents({})
        total_categories = categories_collection.count_documents({})

        stats_text = f"📊 <b>Bot Statistics</b> 📈\n\n" \
                     f"<b>Total Users:</b> {total_users} 👥\n" \
                     f"<b>Total Videos:</b> {total_videos} 🎞️\n" \
                     f"<b>Total Categories:</b> {total_categories} 🗂️\n\n" \
                     f"<b>Videos per Category:</b>\n"

        categories = get_categories()
        if categories:
            for category in categories:
                video_count_in_category = media_collection.count_documents({'category': category})
                stats_text += f"  - <b>{html.escape(category)}:</b> {video_count_in_category} videos\n"
        else:
            stats_text += "  <i>No categories found.</i>\n"

        await message.reply(stats_text)
        logger.info(f"Admin {user_id} retrieved stats: Users={total_users}, Videos={total_videos}, Categories={total_categories}.")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to retrieve stats: {e}", exc_info=True)
        await message.reply("❌ An error occurred while fetching stats. Please try again. 🐛")

@bot.on_message(filters.command("token_stats") & filters.private & admin_only)
async def token_stats_cmd(client: Client, message: Message):
    """Admin command to show URL shortener usage statistics."""
    try:
        one_day_ago = datetime.now(timezone.utc) - timedelta(days=1)
        count = shortener_logs_collection.count_documents({'timestamp': {'$gte': one_day_ago}})
        await message.reply(f"📊 **Token Generation Stats**\n\n"
                            f"The URL shortener has been used **{count}** times in the last 24 hours.")
    except Exception as e:
        logger.error(f"Error in /token_stats command: {e}", exc_info=True)
        await message.reply("An error occurred while fetching token generation stats.")


@bot.on_message(filters.command("bypass_limit") & filters.private & admin_only)
async def bypass_limit_cmd(client: Client, message: Message):
    """Admin command to set the minimum time for URL shortener completion."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} initiated /bypass_limit command.")
    try:
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.reply("Usage: `/bypass_limit <seconds>`\n\nSet the minimum time in seconds a user should take to complete the shortener. Use 0 to disable.")
            return

        seconds_str = args[1]
        if not seconds_str.isdigit():
            await message.reply("Invalid input. Please provide a non-negative integer for seconds.")
            return

        seconds = int(seconds_str)
        if seconds < 0:
            await message.reply("Invalid input. Please provide a non-negative integer for seconds.")
            return

        settings_collection.update_one(
            {'_id': 'bot_settings'},
            {'$set': {'bypass_limit_seconds': seconds}},
            upsert=True
        )

        if seconds == 0:
            await message.reply(f"✅ Bypass detection has been disabled.")
            logger.info(f"Admin {user_id} disabled bypass detection.")
        else:
            await message.reply(f"✅ Bypass limit has been updated to {seconds} seconds.")
            logger.info(f"Admin {user_id} updated bypass limit to {seconds} seconds.")

    except Exception as e:
        logger.error(f"Error in /bypass_limit command: {e}", exc_info=True)
        await message.reply("An error occurred while setting the bypass limit.")

# --- New Admin Commands ---

@bot.on_message(filters.command("addadmin") & filters.private & owner_only)
async def add_admin_cmd(client: Client, message: Message):
    """Owner command to add a new admin."""
    args = message.text.split()
    if len(args) > 1:
        try:
            user_id_to_add = int(args[1])
            if user_id_to_add in BOT_ADMINS:
                await message.reply("This user is already an admin.")
                return

            BOT_ADMINS.add(user_id_to_add)
            # Persist change to DB
            settings_collection.update_one(
                {'_id': 'bot_settings'},
                {'$addToSet': {'admins': user_id_to_add}},
                upsert=True
            )
            await message.reply(f"✅ User {user_id_to_add} has been promoted to admin.")
            logger.info(f"Owner {message.from_user.id} added new admin: {user_id_to_add}")
            return
        except ValueError:
            await message.reply("Invalid User ID format. Please send a valid integer ID.")
            return
        except Exception as e:
            await message.reply(f"An error occurred: {e}")
            logger.error(f"Error in /addadmin flow: {e}")
            return

    owner_add_admin_state[message.from_user.id] = {'step': 'await_user_id'}
    await message.reply("Please send the <b>User ID</b> of the user you want to add as an admin. 📝")

@bot.on_message(filters.command("removeadmin") & filters.private & owner_only)
async def remove_admin_cmd(client: Client, message: Message):
    """Owner command to remove an admin."""
    buttons = []
    # List all admins except the owner for removal
    admins_to_list = [admin_id for admin_id in BOT_ADMINS if admin_id != config.OWNER_ID]

    if not admins_to_list:
        await message.reply("No other admins to remove.")
        return

    for admin_id in admins_to_list:
        try:
            user = await client.get_users(admin_id)
            buttons.append([InlineKeyboardButton(f"{user.first_name} ({user.id})", callback_data=f"rem_admin_{admin_id}")])
        except Exception:
            buttons.append([InlineKeyboardButton(f"ID: {admin_id}", callback_data=f"rem_admin_{admin_id}")])

    await message.reply("Select an admin to remove:", reply_markup=InlineKeyboardMarkup(buttons))

async def perform_user_deletion(client: Client, admin_user_id: int, target_user_id: int) -> str:
    """Helper function to delete a user's data from all collections."""
    if is_owner(target_user_id):
        return "❌ You cannot delete the bot owner."

    if is_admin(target_user_id) and admin_user_id != config.OWNER_ID:
        return "❌ You cannot delete another admin. Please remove them from admin status first using /removeadmin."

    try:
        user_deleted = users_collection.delete_one({'user_id': target_user_id})
        tokens_deleted = tokens_collection.delete_one({'user_id': target_user_id})
        history_deleted = history_collection.delete_one({'user_id': target_user_id})
        ssrb_deleted = ssrb_verifications_collection.delete_one({'user_id': target_user_id})
        pending_uploads_deleted = pending_uploads_collection.delete_many({'user_id': target_user_id})
        shortener_logs_deleted = shortener_logs_collection.delete_many({'user_id': target_user_id})

        if user_deleted.deleted_count > 0:
            logger.info(f"Admin {admin_user_id} successfully deleted user {target_user_id}.")
            return (f"✅ Successfully deleted user {target_user_id} from the database.\n"
                    f"- User record: {'Deleted' if user_deleted.deleted_count > 0 else 'Not Found'}\n"
                    f"- Tokens record: {'Deleted' if tokens_deleted.deleted_count > 0 else 'Not Found'}\n"
                    f"- History record: {'Deleted' if history_deleted.deleted_count > 0 else 'Not Found'}\n"
                    f"- SSRB Record: {'Deleted' if ssrb_deleted.deleted_count > 0 else 'Not Found'}\n"
                    f"- Pending Uploads: {pending_uploads_deleted.deleted_count} removed\n"
                    f"- Shortener Logs: {shortener_logs_deleted.deleted_count} removed")
        else:
            logger.warning(f"Admin {admin_user_id} tried to delete non-existent user {target_user_id}.")
            return f"🤷 User {target_user_id} not found in the database."
    except Exception as e:
        logger.error(f"Error in perform_user_deletion for {target_user_id}: {e}", exc_info=True)
        return f"❌ An error occurred during deletion: {e}"

@bot.on_message(filters.command("deleteuser") & filters.private & admin_only)
async def deleteuser_cmd(client: Client, message: Message):
    """Admin command to delete a user from the database."""
    admin_user_id = message.from_user.id
    logger.info(f"Admin {admin_user_id} initiated /deleteuser command.")

    args = message.text.split()
    if len(args) > 1:
        try:
            target_user_id = int(args[1])
            result_msg = await perform_user_deletion(client, admin_user_id, target_user_id)
            await message.reply(result_msg)
            return
        except ValueError:
            await message.reply("Invalid User ID format. Please provide a numeric ID.")
            return

    admin_delete_user_state[admin_user_id] = {'step': 'await_user_id'}
    await message.reply("Please send the <b>User ID</b> of the user you want to permanently delete from the database. 📝\n\n⚠️ This action is irreversible and will delete all their data, including tokens and history.")

@bot.on_callback_query(filters.regex(r"^rem_admin_(\d+)$"))
async def remove_admin_callback(client: Client, callback_query: CallbackQuery):
    """Callback to handle admin removal."""
    if not is_owner(callback_query.from_user.id):
        await callback_query.answer("You are not authorized to perform this action.", show_alert=True)
        return

    try:
        admin_id_to_remove = int(callback_query.data.split("_")[2])
        if admin_id_to_remove in BOT_ADMINS:
            BOT_ADMINS.remove(admin_id_to_remove)
            # Persist change to DB
            settings_collection.update_one(
                {'_id': 'bot_settings'},
                {'$pull': {'admins': admin_id_to_remove}},
                upsert=True
            )
            await callback_query.message.edit_text(f"✅ Admin {admin_id_to_remove} has been removed.")
            logger.info(f"Owner {callback_query.from_user.id} removed admin: {admin_id_to_remove}")
        else:
            await callback_query.message.edit_text("User is no longer an admin.")
    except Exception as e:
        await callback_query.message.edit_text(f"An error occurred: {e}")
        logger.error(f"Error in remove_admin_callback: {e}")

@bot.on_message(filters.command("setshortener") & filters.private & admin_only)
async def set_shortener_cmd(client: Client, message: Message):
    """Admin command to set the URL shortener API template URL."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} initiated /setshortener command.")
    admin_shortener_setup_state[user_id]['step'] = 'await_template_url'
    await message.reply(
        "Please send the <b>full template URL</b> for your URL shortener API.\n\n"
        "It must include `http://` or `https://` and contain `{long_url}` as a placeholder for the URL to be shortened, and an `api=` parameter with your API key.\n\n"
        "<b>Example:</b> `https://get2short.com/st?api=YOUR_API_KEY&url={long_url}`\n\n"
        "If your shortener doesn't use `api=` in the URL, provide the full API endpoint URL that accepts the long URL as a parameter (e.g., `https://api.shortener.com/shorten?url={long_url}&key=YOUR_API_KEY`)."
    )

@bot.on_message(filters.command("deletevideo") & filters.private & admin_only)
async def deletevideo_cmd(client: Client, message: Message):
    """Admin command to initiate video deletion mode."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} initiated /deletevideo command.")
    if not DATA_CHANNEL_ID:
        await message.reply("❌ Video storage channel is not configured. Please set it using /setdata first.")
        return
    admin_delete_video_state[user_id] = True
    await message.reply("Send the <b>video file from the database</b> to delete it. This must be the original video file, not a forwarded one. 🎥")

@bot.on_message(filters.command("batchvideoadd") & filters.private & admin_only)
async def batch_video_add_cmd(client: Client, message: Message):
    """Admin command to create a shareable link for a batch of videos."""
    user_id = message.from_user.id
    if not DATA_CHANNEL_ID:
        await message.reply("❌ Video storage channel is not configured. Please set it using /setdata first.")
        return
    admin_batch_link_state[user_id] = [] # Reset state
    await message.reply(
        "You are now in <b>Batch Video Link Creation Mode</b>.\n\n"
        "1. Forward videos from your database channel to me.\n"
        "2. When you are finished, send /createbatchlink to generate the shareable link."
    )

@bot.on_message(filters.command("createbatchlink") & filters.private & admin_only)
async def create_batch_link_cmd(client: Client, message: Message):
    """Admin command to finalize a batch video link."""
    user_id = message.from_user.id
    if user_id not in admin_batch_link_state or not admin_batch_link_state[user_id]:
        await message.reply("You haven't added any videos to the batch. Batch mode disabled.")
        if user_id in admin_batch_link_state:
            del admin_batch_link_state[user_id]
        return

    video_uuids = admin_batch_link_state[user_id]
    batch_id = str(uuid.uuid4())

    video_batches_collection.insert_one({
        "batch_id": batch_id,
        "video_uuids": video_uuids,
        "created_by": user_id,
        "created_at": datetime.now(timezone.utc)
    })

    share_link = f"https://t.me/{config.BOT_USERNAME[1:]}?start=batch_{batch_id}"

    await message.reply(
        f"✅ Batch link created successfully for <b>{len(video_uuids)}</b> videos!\n\n"
        f"Share this link:\n`{share_link}`"
    )
    del admin_batch_link_state[user_id] # Clear state

async def perform_video_category_change(video_uuid: str, new_category: str) -> tuple[bool, str]:
    """Helper function to change a video's category in DB and cascade updates."""
    try:
        video_doc = media_collection.find_one({"uuid": video_uuid})
        if not video_doc:
            return False, "Video not found in database."

        old_category = video_doc.get('category')
        old_seq = video_doc.get('sequence_number')

        if old_category == new_category:
            return True, "Video is already in this category."

        # 1. Rearrange sequence numbers in old category
        if old_category and old_seq is not None:
            rearrange_sequences_after_deletion(old_category, old_seq)

        # 2. Get next sequence number in new category
        last_video = media_collection.find_one({'category': new_category}, sort=[('sequence_number', DESCENDING)])
        next_seq = (last_video['sequence_number'] + 1) if last_video and 'sequence_number' in last_video else 1

        # 3. Update video document
        media_collection.update_one(
            {"uuid": video_uuid},
            {"$set": {"category": new_category, "sequence_number": next_seq}}
        )

        # 4. Cascade updates to bookmarks
        users_collection.update_many(
            {'bookmarked_videos.uuid': video_uuid},
            {'$set': {'bookmarked_videos.$[elem].category': new_category}},
            array_filters=[{'elem.uuid': video_uuid}]
        )

        # 5. Cascade updates to history
        history_collection.update_many(
            {'history.video_uuid': video_uuid},
            {'$set': {'history.$[elem].category': new_category}},
            array_filters=[{'elem.video_uuid': video_uuid}]
        )

        return True, "Success"
    except Exception as e:
        logger.error(f"Error performing video category change for {video_uuid}: {e}", exc_info=True)
        return False, str(e)

@bot.on_message(filters.command(["changecategory", "change_category"]) & filters.private & admin_only)
async def changecategory_cmd(client: Client, message: Message):
    """Admin command to change a video's category."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} initiated /changecategory command.")

    args = message.text.split(maxsplit=2)
    video_uuid = None
    new_category_name = None
    video_doc = None

    # Try to extract from reply message
    if message.reply_to_message and message.reply_to_message.video:
        file_unique_id = message.reply_to_message.video.file_unique_id
        video_doc = media_collection.find_one({"file_unique_id": file_unique_id})
        if video_doc:
            video_uuid = video_doc['uuid']
        if len(args) > 1:
            new_category_name = args[1].strip()

    elif len(args) > 1:
        # Check if first arg is a valid UUID
        possible_uuid = args[1].strip()
        video_doc = media_collection.find_one({"uuid": possible_uuid})
        if video_doc:
            video_uuid = video_doc['uuid']
            if len(args) > 2:
                new_category_name = args[2].strip()

    # If we have video_uuid and new_category_name, perform direct change
    if video_uuid and new_category_name:
        if new_category_name not in get_categories(for_admin_use=True):
            await message.reply(f"❌ Category '<b>{html.escape(new_category_name)}</b>' does not exist. Please create it first using /addcategory.")
            return

        success, err_or_msg = await perform_video_category_change(video_uuid, new_category_name)
        if success:
            await message.reply(f"✅ Video category changed successfully to '<b>{html.escape(new_category_name)}</b>'.")
        else:
            await message.reply(f"❌ Failed to change category: {err_or_msg}")
        return

    # Otherwise, enter interactive state or ask for input
    if not video_uuid:
        # Enter state to await video or UUID
        admin_rename_category_state[user_id] = {'step': 'chg_cat_await_video'}
        await message.reply("Please **reply to a video** with this command, or **send/forward a video**, or send the **video UUID** to change its category. 🎥")
    else:
        # We have the video, but need the category. Show category buttons!
        categories = get_categories(for_admin_use=True)
        if not categories:
            await message.reply("⚠️ No categories available. Please create one using /addcategory first.")
            return

        buttons = []
        for idx, cat in enumerate(categories):
            buttons.append([InlineKeyboardButton(f"🗂️ {cat}", callback_data=f"chg_cat_{video_uuid}_{idx}")])

        await message.reply(
            f"Select the **new category** for the video (Current: <code>{video_doc.get('category')}</code>):",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

@bot.on_callback_query(filters.regex(r"^chg_cat_(.+?)_(\d+)$"))
async def chg_cat_callback(client: Client, callback_query: CallbackQuery):
    """Handles category selection in /changecategory interactive flow."""
    user_id = callback_query.from_user.id
    if not is_admin(user_id):
        await callback_query.answer("❌ Not authorized.", show_alert=True)
        return

    match = re.match(r"^chg_cat_(.+?)_(\d+)$", callback_query.data)
    video_uuid = match.group(1)
    cat_idx = int(match.group(2))

    categories = get_categories(for_admin_use=True)
    if cat_idx >= len(categories):
        await callback_query.answer("❌ Invalid category index.", show_alert=True)
        return

    new_category = categories[cat_idx]
    success, err_or_msg = await perform_video_category_change(video_uuid, new_category)

    if success:
        await callback_query.message.edit_text(f"✅ Video category changed successfully to '<b>{html.escape(new_category)}</b>'.")
        await callback_query.answer("Category updated successfully!")
    else:
        await callback_query.message.edit_text(f"❌ Failed to change category: {err_or_msg}")
        await callback_query.answer("Error updating category.", show_alert=True)

@bot.on_message(filters.command("categoryrename") & filters.private & admin_only)
async def categoryrename_cmd(client: Client, message: Message):
    """Admin command to initiate category renaming flow."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} initiated /categoryrename command.")
    admin_rename_category_state[user_id] = {'step': 'await_old_name'}
    await message.reply("Please send the <b>current name</b> of the category you want to rename. 📝")

# NEW: Admin command for setting force subscribe channels
@bot.on_message(filters.command("setfsub") & filters.private & admin_only)
async def set_fsub_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} initiated /setfsub command.")

    buttons = []
    if FORCE_SUB_CHANNELS:
        for channel_info in FORCE_SUB_CHANNELS:
            buttons.append([InlineKeyboardButton(f"🔗 {html.escape(channel_info.get('name', f'Channel {channel_info['channel_id']}'))}", callback_data=f"viewfsub_{channel_info['channel_id']}")])

    buttons.append([InlineKeyboardButton("➕ Add New Channel", callback_data="addfsub_step1")])

    await message.reply(
        "<b>Force Subscribe Channels Configuration:</b>\n\n"
        "Below are the channels currently set for force subscription. Users must join these to use the bot.\n\n"
        "Click on a channel to view its details or remove it. Click '➕ Add New Channel' to add another one.",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

@bot.on_callback_query(filters.regex(r"^addfsub_step1$"))
async def add_fsub_step1_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if not is_admin(user_id):
        await callback_query.answer("❌ Not authorized.", show_alert=True)
        return

    admin_fsub_state[user_id] = {'step': 'await_channel_id'}
    await callback_query.message.edit_text(
        "Please send the <b>Channel ID</b> (e.g., -1001234567890) or the channel's public username (e.g., @channelname).\n\n"
        "<b>Important:</b> Make sure the bot is an <b>admin</b> in the channel with 'Invite Users' permission to generate a link, and 'Delete Messages' permission for future management. 📝"
    )
    await callback_query.answer()

@bot.on_callback_query(filters.regex(r"^viewfsub_(-?\d+)$"))
async def view_fsub_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if not is_admin(user_id):
        await callback_query.answer("❌ Not authorized.", show_alert=True)
        return

    channel_id = int(callback_query.data.split('_')[1])
    channel_info = next((c for c in FORCE_SUB_CHANNELS if c['channel_id'] == channel_id), None)

    if not channel_info:
        await callback_query.answer("Channel not found in configuration.", show_alert=True)
        await set_fsub_cmd(client, callback_query.message) # Refresh menu
        return

    text = (
        f"<b>Force Subscribe Channel Details:</b>\n"
        f"ID: <code>{channel_info['channel_id']}</code>\n"
        f"Name: {html.escape(channel_info.get('name', 'N/A'))}\n"
        f"Link: {html.escape(channel_info.get('link', 'N/A'))}"
    )

    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑️ Remove Channel", callback_data=f"removefsub_{channel_id}")],
        [InlineKeyboardButton("⬅️ Back to List", callback_data="back_to_fsub_list")]
    ])

    await callback_query.message.edit_text(text, reply_markup=reply_markup)
    await callback_query.answer()

@bot.on_callback_query(filters.regex(r"^removefsub_(-?\d+)$"))
async def remove_fsub_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if not is_admin(user_id):
        await callback_query.answer("❌ Not authorized.", show_alert=True)
        return

    channel_id = int(callback_query.data.split('_')[1])

    result = force_sub_channels_collection.delete_one({'channel_id': channel_id})
    if result.deleted_count > 0:
        await load_force_sub_channels() # Reload global list
        await callback_query.answer("Channel removed successfully!", show_alert=True)
        await set_fsub_cmd(client, callback_query.message) # Refresh menu
        logger.info(f"Admin {user_id} removed force sub channel: {channel_id}")
    else:
        await callback_query.answer("Channel not found in database.", show_alert=True)
        await set_fsub_cmd(client, callback_query.message) # Refresh menu

@bot.on_callback_query(filters.regex(r"^back_to_fsub_list$"))
async def back_to_fsub_list_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if not is_admin(user_id):
        await callback_query.answer("❌ Not authorized.", show_alert=True)
        return

    await set_fsub_cmd(client, callback_query.message) # Re-send the main fsub menu
    await callback_query.answer()

# NEW: Admin command for setting data channel
@bot.on_message(filters.command("configupload") & filters.private & admin_only)
async def config_upload_cmd(client: Client, message: Message):
    """Admin command to configure upload settings."""
    milestones_str = "\n".join([f"   • {k} videos -> {v} hours" for k, v in sorted(UPLOAD_CONFIG.get('milestones', {}).items(), key=lambda x: int(x[0]))])
    if not milestones_str:
        milestones_str = "   <i>None set</i>"

    expiry_text = "Disabled (Permanent) ♾️" if UPLOAD_CONFIG.get('temp_scrolls_expiry_hours', 0) == 0 else f"{UPLOAD_CONFIG['temp_scrolls_expiry_hours']} hours"
    text = (
        "⚙️ **Upload Configuration**\n\n"
        f"🔢 **Min Uploads for Reward:** {UPLOAD_CONFIG.get('min_upload_count', 1)} videos\n"
        f"⏳ **Max Pending Uploads:** {UPLOAD_CONFIG.get('max_pending', 30)} videos\n"
        f"📅 **Daily Max per User:** {UPLOAD_CONFIG['daily_max']} videos\n"
        f"📜 **Auto-give Scrolls:** {'Enabled ✅' if UPLOAD_CONFIG['auto_give_scrolls'] else 'Disabled ❌'}\n"
        f"➕ **Scrolls Amount:** {UPLOAD_CONFIG['temp_scrolls_amount']}\n"
        f"🕒 **Scrolls Expiry:** {expiry_text}\n"
        f"🎁 **Base Token Reward:** {UPLOAD_CONFIG.get('reward_tokens_hours', 2.0)} hours\n"
        f"⏳ **Session Limit:** {UPLOAD_CONFIG.get('session_limit_count', 10)} vids / {UPLOAD_CONFIG.get('session_limit_minutes', 10)} mins\n\n"
        f"🏆 **Milestones:** {'Enabled ✅' if UPLOAD_CONFIG.get('milestones_enabled') else 'Disabled ❌'}\n"
        f"{milestones_str}\n\n"
        "Tap a button to change a setting:"
    )

    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔢 Min Uploads", callback_data="cfg_upl_min_count"), InlineKeyboardButton("⏳ Max Pending", callback_data="cfg_upl_max_pending")],
        [InlineKeyboardButton("📅 Daily Max", callback_data="cfg_upl_daily"), InlineKeyboardButton("📜 Toggle Scrolls", callback_data="cfg_upl_toggle_scrolls")],
        [InlineKeyboardButton("➕ Scrolls Amt", callback_data="cfg_upl_scroll_amt"), InlineKeyboardButton("🕒 Scrolls Expiry", callback_data="cfg_upl_scroll_exp"), InlineKeyboardButton("📴 Disable Expiry", callback_data="cfg_upl_disable_expiry")],
        [InlineKeyboardButton("🎁 Token Reward", callback_data="cfg_upl_reward_tokens"), InlineKeyboardButton("🏆 Milestones", callback_data="cfg_upl_toggle_milestones")],
        [InlineKeyboardButton("⏲️ Session Limit", callback_data="cfg_upl_sess_cnt"), InlineKeyboardButton("⏱️ Session Time", callback_data="cfg_upl_sess_min")],
        [InlineKeyboardButton("📝 Edit Milestones", callback_data="cfg_upl_edit_milestones")]
    ])

    await message.reply(text, reply_markup=reply_markup)

@bot.on_callback_query(filters.regex(r"^cfg_upl_(.+)$"))
async def config_upload_callback(client: Client, callback_query: CallbackQuery):
    """Handles configuration setting changes."""
    user_id = callback_query.from_user.id
    if not is_admin(user_id):
        return

    setting = callback_query.data[8:]

    if setting == "disable_expiry":
        UPLOAD_CONFIG['temp_scrolls_expiry_hours'] = 0
        settings_collection.update_one({'_id': 'upload_config'}, {'$set': {'settings': UPLOAD_CONFIG}}, upsert=True)
        await callback_query.answer("Scrolls expiry disabled (scrolls are now permanent)!")
        await config_upload_cmd(client, callback_query.message)
        return

    if setting == "toggle_scrolls":
        UPLOAD_CONFIG['auto_give_scrolls'] = not UPLOAD_CONFIG['auto_give_scrolls']
        settings_collection.update_one({'_id': 'upload_config'}, {'$set': {'settings': UPLOAD_CONFIG}}, upsert=True)
        await callback_query.answer(f"Auto-give scrolls: {'Enabled' if UPLOAD_CONFIG['auto_give_scrolls'] else 'Disabled'}")
        await config_upload_cmd(client, callback_query.message)
        return

    if setting == "toggle_milestones":
        UPLOAD_CONFIG['milestones_enabled'] = not UPLOAD_CONFIG.get('milestones_enabled', False)
        settings_collection.update_one({'_id': 'upload_config'}, {'$set': {'settings': UPLOAD_CONFIG}}, upsert=True)
        await callback_query.answer(f"Milestones: {'Enabled' if UPLOAD_CONFIG['milestones_enabled'] else 'Disabled'}")
        await config_upload_cmd(client, callback_query.message)
        return

    # For other settings, prompt for input
    prompt_map = {
        "min_count": "Enter **minimum videos** user must upload to get a reward (e.g., 5):",
        "max_pending": "Enter **maximum pending uploads** allowed per user (e.g., 30):",
        "daily": "Enter new **daily maximum** videos per user (e.g., 100):",
        "scroll_amt": f"Enter new **temporary scrolls** amount per upload (Current: {UPLOAD_CONFIG['temp_scrolls_amount']}):",
        "scroll_exp": f"Enter new **scrolls expiry** in hours (Current: {UPLOAD_CONFIG['temp_scrolls_expiry_hours']}):",
        "reward_tokens": f"Enter **token reward hours** for reaching min uploads (Current: {UPLOAD_CONFIG.get('reward_tokens_hours', 2.0)}):",
        "sess_cnt": f"Enter **max videos** allowed per session (Current: {UPLOAD_CONFIG.get('session_limit_count', 10)}):",
        "sess_min": f"Enter **session duration** in minutes (Current: {UPLOAD_CONFIG.get('session_limit_minutes', 10)}):",
        "edit_milestones": "Enter milestones in `count:hours` format, separated by commas (e.g., `5:2,10:4`):"
    }

    admin_rename_category_state[user_id] = {'step': f'cfg_upl_{setting}'} # Reusing state dict for simplicity
    await callback_query.message.reply(prompt_map[setting])
    await callback_query.answer()

@bot.on_message(filters.command("setreviewchat") & filters.private & admin_only)
async def set_review_chat_cmd(client: Client, message: Message):
    """Admin command to set the review chat ID."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} initiated /setreviewchat command.")

    args = message.text.split()
    if len(args) < 2:
        # Prompt to send ID if not provided in command
        admin_data_channel_state[user_id] = {'step': 'await_review_chat_id'} # Reuse data channel state conceptually or create new
        await message.reply("Please send the **Chat ID** of the group/channel where uploads should be reviewed. 📝")
        return

    try:
        chat_id = int(args[1])
        global REVIEW_CHAT_ID
        REVIEW_CHAT_ID = chat_id
        settings_collection.update_one(
            {'_id': 'upload_config'},
            {'$set': {'review_chat_id': chat_id}},
            upsert=True
        )
        await message.reply(f"✅ Review chat ID set to ` {chat_id} `.")
        logger.info(f"Admin {user_id} set review chat ID to {chat_id}")
    except ValueError:
        await message.reply("Invalid Chat ID. Please provide a valid integer.")

@bot.on_message(filters.command("setdata") & filters.private & admin_only)
async def set_data_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} initiated /setdata command.")

    current_data_channel_id = DATA_CHANNEL_ID
    text = "<b>Video Storage Channel Configuration:</b>\n\n"
    buttons = []

    if current_data_channel_id:
        try:
            chat = await client.get_chat(current_data_channel_id)
            channel_name = chat.title
            text += f"Currently set to: <b>{html.escape(channel_name)}</b> (ID: <code>{current_data_channel_id}</code>)\n\n"
            buttons.append([InlineKeyboardButton("🗑️ Remove Data Channel", callback_data="removedatachannel")])
        except Exception as e:
            logger.warning(f"Could not get info for current data channel {current_data_channel_id}: {e}")
            text += f"Currently set to: <b>Invalid Channel</b> (ID: <code>{current_data_channel_id}</code>)\n\n"
    else:
        text += "No video storage channel is currently configured.\n\n"

    text += "Click '✏️ Set/Change Data Channel' to configure or update it."
    buttons.append([InlineKeyboardButton("✏️ Set/Change Data Channel", callback_data="setdatachannel_step1")])

    await message.reply(text, reply_markup=InlineKeyboardMarkup(buttons))

@bot.on_callback_query(filters.regex(r"^setdatachannel_step1$"))
async def set_data_channel_step1_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if not is_admin(user_id):
        await callback_query.answer("❌ Not authorized.", show_alert=True)
        return

    admin_data_channel_state[user_id] = {'step': 'await_channel_id'}
    await callback_query.message.edit_text(
        "Please send the <b>Channel ID</b> (e.g., -1001234567890) or the channel's public username (e.g., @channelname).\n\n"
        "<b>Important:</b> Make sure the bot is an <b>admin</b> in this channel with 'Post Messages' and 'Delete Messages' permissions. 📝"
    )
    await callback_query.answer()

@bot.on_callback_query(filters.regex(r"^removedatachannel$"))
async def remove_data_channel_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if not is_admin(user_id):
        await callback_query.answer("❌ Not authorized.", show_alert=True)
        return

    result = data_channel_collection.delete_one({'_id': 'data_channel'})
    if result.deleted_count > 0:
        await load_data_channel_id() # Reload global variable
        await callback_query.answer("Data channel removed successfully!", show_alert=True)
        await set_data_cmd(client, callback_query.message) # Refresh menu
        logger.info(f"Admin {user_id} removed data channel.")
    else:
        await callback_query.answer("No data channel found to remove.", show_alert=True)
        await set_data_cmd(client, callback_query.message) # Refresh menu


@bot.on_message(filters.command(["turnoff_shortener", "turnoff"]) & filters.private & admin_only)
async def turnoff_shortener_cmd(client: Client, message: Message):
    """Admin command to turn off the URL shortener."""
    global SHORTENER_DISABLED

    # If using /turnoff, check if the argument is 'shortener'
    if message.command[0] == "turnoff":
        if len(message.command) < 2 or message.command[1].lower() != "shortener":
            return # Ignore other /turnoff commands or pass to handle_text_input if propagation continued

    try:
        settings_collection.update_one(
            {'_id': 'bot_settings'},
            {'$set': {'shortener_disabled': True}},
            upsert=True
        )
        SHORTENER_DISABLED = True
        await message.reply(f"✅ URL Shortener has been <b>turned OFF</b>. 'Unlock {int(config.TOKEN_ACCESS_HOURS)}-Hour Access' and Tutorial buttons are now hidden from users. 🚫")
        logger.info(f"Admin {message.from_user.id} turned off the shortener.")
    except Exception as e:
        logger.error(f"Error in /turnoff_shortener: {e}", exc_info=True)
        await message.reply("❌ Failed to turn off the shortener. Check logs.")

@bot.on_message(filters.command(["turnon_shortener", "turnon"]) & filters.private & admin_only)
async def turnon_shortener_cmd(client: Client, message: Message):
    """Admin command to turn on the URL shortener."""
    global SHORTENER_DISABLED

    # If using /turnon, check if the argument is 'shortener'
    if message.command[0] == "turnon":
        if len(message.command) < 2 or message.command[1].lower() != "shortener":
            return

    try:
        settings_collection.update_one(
            {'_id': 'bot_settings'},
            {'$set': {'shortener_disabled': False}},
            upsert=True
        )
        SHORTENER_DISABLED = False
        await message.reply("✅ URL Shortener has been <b>turned ON</b>. All options are now visible to users. 🔓")
        logger.info(f"Admin {message.from_user.id} turned on the shortener.")
    except Exception as e:
        logger.error(f"Error in /turnon_shortener: {e}", exc_info=True)
        await message.reply("❌ Failed to turn on the shortener. Check logs.")

@bot.on_message(filters.command("shortener_status") & filters.private & admin_only)
async def shortener_status_cmd(client: Client, message: Message):
    """Admin command to check the shortener status."""
    status = "Disabled 🚫" if SHORTENER_DISABLED else "Enabled 🔓"
    await message.reply(f"📊 <b>URL Shortener Status:</b> {status}")

@bot.on_message(filters.text & filters.private & non_command)
async def handle_text_input(client: Client, message: Message):
    """Handles text input for various multi-step commands for owner and admins."""
    user_id = message.from_user.id
    text_input = message.text.strip()

    # --- Owner-only state handling ---
    if is_owner(user_id):
        if user_id in owner_add_admin_state and owner_add_admin_state[user_id].get('step') == 'await_user_id':
            try:
                user_id_to_add = int(text_input)
                if user_id_to_add in BOT_ADMINS:
                    await message.reply("This user is already an admin.")
                    return

                BOT_ADMINS.add(user_id_to_add)
                # Persist change to DB
                settings_collection.update_one(
                    {'_id': 'bot_settings'},
                    {'$addToSet': {'admins': user_id_to_add}},
                    upsert=True
                )
                await message.reply(f"✅ User {user_id_to_add} has been promoted to admin.")
                logger.info(f"Owner {user_id} added new admin: {user_id_to_add}")

            except ValueError:
                await message.reply("Invalid User ID. Please send a valid integer ID.")
            except Exception as e:
                await message.reply(f"An error occurred: {e}")
                logger.error(f"Error in /addadmin flow: {e}")
            finally:
                del owner_add_admin_state[user_id]
            return

    # --- Admin-only state handling ---
    if is_admin(user_id):
        if user_id in admin_delete_user_state and admin_delete_user_state[user_id].get('step') == 'await_user_id':
            try:
                target_user_id = int(text_input)
                result_msg = await perform_user_deletion(client, user_id, target_user_id)
                await message.reply(result_msg)
            except ValueError:
                await message.reply("Invalid User ID. Please send a valid integer ID.")
            except Exception as e:
                await message.reply(f"An error occurred: {e}")
                logger.error(f"Error in /deleteuser interactive flow: {e}")
            finally:
                del admin_delete_user_state[user_id]
            return

        if user_id in admin_shortener_setup_state and admin_shortener_setup_state[user_id].get('step') == 'await_template_url':
            template_url = text_input

            if not template_url.startswith("http://") and not template_url.startswith("https://"):
                await message.reply("Invalid URL. Please send a valid URL starting with `http://` or `https://`.")
                logger.warning(f"Admin {user_id} provided invalid template URL format for shortener: {template_url}")
                return

            if '{long_url}' not in template_url:
                await message.reply(
                    "❌ Error: The template URL must contain `{long_url}` as a placeholder for the URL to be shortened.\n\n"
                    "Please send the correct template URL. 📝"
                )
                logger.warning(f"Admin {user_id} provided template URL without {{long_url}} placeholder for shortener: {template_url}")
                return

            if 'api=' not in template_url:
                await message.reply(
                    "❌ Error: The template URL must contain an 'api=' parameter with your API key.\n\n"
                    "Example: `https://get2short.com/st?api=YOUR_API_KEY&url={long_url}`\n"
                    "Please send the correct template URL. 📝"
                )
                logger.warning(f"Admin {user_id} provided template URL without 'api=' parameter for shortener: {template_url}")
                return

            try:
                settings_collection.update_one(
                    {'_id': 'shortener_config'},
                    {'$set': {'template_url': template_url}},
                    upsert=True
                )
                del admin_shortener_setup_state[user_id]
                await message.reply("✅ Shortener API Template URL Set Successfully!")
                logger.info(f"Admin {user_id} successfully set shortener template URL: {template_url}")
            except Exception as e:
                logger.error(f"Error saving shortener template URL for admin {user_id}: {e}", exc_info=True)
                await message.reply("❌ Failed to save shortener configuration. Please try again. 🐛")
                del admin_shortener_setup_state[user_id]
            return

        if user_id in admin_rename_category_state:
            current_step = admin_rename_category_state[user_id].get('step')

            if current_step == 'chg_cat_await_video':
                video_uuid = text_input
                video_doc = media_collection.find_one({"uuid": video_uuid})
                if not video_doc:
                    await message.reply("❌ Video not found in database. Please send a valid UUID or send a video.")
                    return

                categories = get_categories(for_admin_use=True)
                if not categories:
                    await message.reply("⚠️ No categories available. Please create one using /addcategory first.")
                    del admin_rename_category_state[user_id]
                    return

                buttons = []
                for idx, cat in enumerate(categories):
                    buttons.append([InlineKeyboardButton(f"🗂️ {cat}", callback_data=f"chg_cat_{video_uuid}_{idx}")])

                await message.reply(
                    f"Select the **new category** for this video (Current: <code>{video_doc.get('category')}</code>):",
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
                del admin_rename_category_state[user_id]
                return

            if current_step == 'await_old_name':
                old_name = text_input

                if old_name == "default (all)":
                    await message.reply("❌ The 'default (all)' category cannot be renamed.")
                    del admin_rename_category_state[user_id]
                    return

                valid, error = validate_category_name(old_name)
                if not valid:
                    await message.reply(f"❌ Invalid old category name: {error}. Please try again. 📝")
                    logger.warning(f"Admin {user_id} provided invalid old category name for rename: {old_name}")
                    return

                if not categories_collection.find_one({'name': old_name}):
                    await message.reply(f"❌ Category '<b>{html.escape(old_name)}</b>' does not exist. Please send an existing category name. 🧐")
                    logger.warning(f"Admin {user_id} tried to rename non-existent category: {old_name}")
                    return

                admin_rename_category_state[user_id]['old_name'] = old_name
                admin_rename_category_state[user_id]['step'] = 'await_new_name'
                await message.reply(f"Okay, the current category is '<b>{html.escape(old_name)}</b>'. Now send the <b>new name</b> for this category. 📝")
                logger.info(f"Admin {user_id} set old category name to '{old_name}'. Awaiting new name.")
                return

            elif current_step == 'await_new_name':
                new_name = text_input
                old_name = admin_rename_category_state[user_id].get('old_name')

                valid, error = validate_category_name(new_name)
                if not valid:
                    await message.reply(f"❌ Invalid new category name: {error}. Please try again. 📝")
                    logger.warning(f"Admin {user_id} provided invalid new category name for rename: {new_name}")
                    return

                if categories_collection.find_one({'name': new_name}):
                    await message.reply(f"❌ Category '<b>{html.escape(new_name)}</b>' already exists. Please choose a different new name. 🧐")
                    logger.warning(f"Admin {user_id} tried to rename to an existing category: {new_name}")
                    return

                try:
                    categories_collection.update_one({'name': old_name}, {'$set': {'name': new_name}})
                    logger.info(f"Category '{old_name}' renamed to '{new_name}' in categories_collection.")

                    media_collection.update_many({'category': old_name}, {'$set': {'category': new_name}})
                    logger.info(f"Updated media_collection documents from '{old_name}' to '{new_name}'.")

                    users_collection.update_many(
                        {'bookmarked_videos.category': old_name},
                        {'$set': {'bookmarked_videos.$[elem].category': new_name}},
                        array_filters=[{'elem.category': old_name}]
                    )
                    logger.info(f"Updated bookmarked_videos in users_collection from '{old_name}' to '{new_name}'.")

                    history_collection.update_many(
                        {'history.category': old_name},
                        {'$set': {'history.$[elem].category': new_name}},
                        array_filters=[{'elem.category': old_name}]
                    )
                    logger.info(f"Updated history in history_collection from '{old_name}' to '{new_name}'.")

                    all_users_with_last_viewed = users_collection.find({'last_viewed_per_category': {'$exists': True}})
                    for user_doc in all_users_with_last_viewed:
                        user_id_to_update = user_doc['user_id']
                        last_viewed_map = user_doc['last_viewed_per_category']
                        if old_name in last_viewed_map:
                            video_uuid_to_move = last_viewed_map.pop(old_name)
                            last_viewed_map[new_name] = video_uuid_to_move
                            users_collection.update_one(
                                {'user_id': user_id_to_update},
                                {'$set': {'last_viewed_per_category': last_viewed_map}}
                            )
                            logger.info(f"Updated last_viewed_per_category for user {user_id_to_update} from '{old_name}' to '{new_name}'.")

                    await message.reply(f"✅ Category '<b>{html.escape(old_name)}</b>' successfully renamed to '<b>{html.escape(new_name)}</b>'! 🎉")
                    logger.info(f"Admin {user_id} successfully renamed category from '{old_name}' to '{new_name}'.")

                except Exception as e:
                    logger.error(f"Error renaming category for admin {user_id}: {e}", exc_info=True)
                    await message.reply("❌ An error occurred while renaming the category. Please try again. 🐛")
                finally:
                    del admin_rename_category_state[user_id]
                return

        # NEW: Admin Fsub state handling
        if user_id in admin_fsub_state and admin_fsub_state[user_id].get('step') == 'await_channel_id':
            try:
                channel_identifier = text_input
                try:
                    # This will handle both integer IDs and string usernames (@channelname)
                    chat = await client.get_chat(channel_identifier)
                    channel_id = chat.id
                    channel_name = chat.title
                except Exception as e:
                    logger.error(f"Error getting chat info for identifier {channel_identifier}: {e}")
                    await message.reply(f"❌ Could not find the channel or bot is not a member. Please check the ID/username and try again. Error: {e}")
                    return

                if force_sub_channels_collection.find_one({'channel_id': channel_id}):
                    await message.reply("This channel is already in the force subscribe list.")
                    del admin_fsub_state[user_id]
                    return

                try:
                    invite_link = await client.export_chat_invite_link(channel_id)
                except ChatAdminRequired:
                    await message.reply("❌ Bot is not an admin in this channel or lacks 'Invite Users' permission. Please add the bot as admin and try again.")
                    return
                except Exception as e:
                    logger.error(f"Error getting invite link for channel {channel_id}: {e}")
                    await message.reply(f"An unexpected error occurred while getting the invite link: {e}")
                    return

                force_sub_channels_collection.insert_one({
                    'channel_id': channel_id,
                    'name': channel_name,
                    'link': invite_link,
                    'added_by': user_id,
                    'added_at': datetime.now(timezone.utc)
                })
                await load_force_sub_channels() # Reload global list
                await message.reply(f"✅ Channel '<b>{html.escape(channel_name)}</b>' (<code>{channel_id}</code>) added to force subscribe list.")
                logger.info(f"Admin {user_id} added force sub channel: {channel_id}")

            except Exception as e:
                await message.reply(f"An error occurred: {e}")
                logger.error(f"Error in /setfsub flow: {e}")
            finally:
                del admin_fsub_state[user_id]
            return

        # NEW: Upload Config state handling
        if user_id in admin_rename_category_state and admin_rename_category_state[user_id].get('step', '').startswith('cfg_upl_'):
            setting = admin_rename_category_state[user_id]['step'][8:]
            try:
                if setting == "min_count":
                    val = int(text_input)
                    if val < 1:
                        await message.reply("❌ Minimum upload count must be at least 1.")
                        return
                    UPLOAD_CONFIG['min_upload_count'] = val
                elif setting == "max_pending":
                    val = int(text_input)
                    if val < 1:
                        await message.reply("❌ Maximum pending count must be at least 1.")
                        return
                    UPLOAD_CONFIG['max_pending'] = val
                elif setting == "daily":
                    UPLOAD_CONFIG['daily_max'] = int(text_input)
                elif setting == "scroll_amt":
                    UPLOAD_CONFIG['temp_scrolls_amount'] = int(text_input)
                elif setting == "scroll_exp":
                    UPLOAD_CONFIG['temp_scrolls_expiry_hours'] = int(text_input)
                elif setting == "reward_tokens":
                    UPLOAD_CONFIG['reward_tokens_hours'] = float(text_input)
                elif setting == "sess_cnt":
                    UPLOAD_CONFIG['session_limit_count'] = int(text_input)
                elif setting == "sess_min":
                    UPLOAD_CONFIG['session_limit_minutes'] = int(text_input)
                elif setting == "edit_milestones":
                    new_milestones = {}
                    parts = text_input.replace(" ", "").split(",")
                    for part in parts:
                        if ":" in part:
                            k, v = part.split(":", 1)
                            if k.isdigit():
                                try:
                                    new_milestones[k] = float(v)
                                except ValueError:
                                    continue
                    if not new_milestones and text_input.strip().lower() != "none":
                        await message.reply("❌ Invalid format. Use `count:hours`, e.g., `5:2,10:4`.")
                        return
                    UPLOAD_CONFIG['milestones'] = new_milestones

                settings_collection.update_one({'_id': 'upload_config'}, {'$set': {'settings': UPLOAD_CONFIG}}, upsert=True)
                await message.reply(f"✅ Setting **{setting}** updated successfully!")
                await config_upload_cmd(client, message)
            except ValueError:
                await message.reply("❌ Invalid input. Please provide a numeric value.")
            finally:
                del admin_rename_category_state[user_id]
            return

        # NEW: Admin Review Chat state handling
        if user_id in admin_data_channel_state and admin_data_channel_state[user_id].get('step') == 'await_review_chat_id':
            try:
                chat_id = int(text_input)
                global REVIEW_CHAT_ID
                REVIEW_CHAT_ID = chat_id
                settings_collection.update_one(
                    {'_id': 'upload_config'},
                    {'$set': {'review_chat_id': chat_id}},
                    upsert=True
                )
                await message.reply(f"✅ Review chat ID set to ` {chat_id} `.")
                logger.info(f"Admin {user_id} set review chat ID to {chat_id}")
            except ValueError:
                await message.reply("Invalid Chat ID. Please provide a valid integer.")
            finally:
                del admin_data_channel_state[user_id]
            return

        # NEW: Admin Data Channel state handling
        if user_id in admin_data_channel_state and admin_data_channel_state[user_id].get('step') == 'await_channel_id':
            try:
                channel_identifier = text_input
                try:
                    chat = await client.get_chat(channel_identifier)
                    channel_id = chat.id
                    channel_name = chat.title
                except Exception as e:
                    logger.error(f"Error getting chat info for identifier {channel_identifier}: {e}")
                    await message.reply(f"❌ Could not find the channel or bot is not a member. Please check the ID/username and try again. Error: {e}")
                    return

                try:
                    # Check if bot has necessary permissions
                    me = await client.get_me()
                    member = await client.get_chat_member(channel_id, me.id)
                    # FIX: Access permissions via member.privileges for administrators
                    if not (member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER] and member.privileges and member.privileges.can_post_messages and member.privileges.can_delete_messages):
                        await message.reply("❌ Bot is not an admin in this channel or lacks necessary permissions ('Post Messages' and 'Delete Messages'). Please grant them and try again.")
                        return
                except ChatAdminRequired:
                    await message.reply("❌ Bot is not an admin in this channel. Please add the bot as admin and try again.")
                    return
                except Exception as e:
                    logger.error(f"Error checking bot permissions in channel {channel_id}: {e}")
                    await message.reply(f"An unexpected error occurred while checking permissions: {e}")
                    return

                data_channel_collection.update_one(
                    {'_id': 'data_channel'},
                    {'$set': {'channel_id': channel_id, 'name': channel_name, 'set_by': user_id, 'set_at': datetime.now(timezone.utc)}},
                    upsert=True
                )
                await load_data_channel_id() # Reload global variable
                await message.reply(f"✅ Video storage channel set to '<b>{html.escape(channel_name)}</b>' (<code>{channel_id}</code>).")
                logger.info(f"Admin {user_id} set data channel: {channel_id}")

            except Exception as e:
                await message.reply(f"An error occurred: {e}")
                logger.error(f"Error in /setdata flow: {e}")
            finally:
                del admin_data_channel_state[user_id]
            return

    logger.debug(f"User {user_id} sent text message '{message.text}' not part of any active multi-step command. Ignoring.")

# --- Auto-Delete & Protect Content Settings ---
@bot.on_message(filters.command('toggle_auto_delete') & filters.private & admin_only)
async def toggle_auto_delete(client: Client, message: Message):
    """Admin command to toggle auto-deletion of sent videos."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} requested to toggle auto-delete.")
    try:
        s = settings_collection.find_one({'_id': 'settings'}) or {'auto_delete': True}
        new_status = not s.get('auto_delete', True)
        settings_collection.update_one({'_id': 'settings'}, {'$set': {'auto_delete': new_status}}, upsert=True)
        await message.reply(f"Auto-delete feature (for videos *sent into the channel*) is now {'<b>enabled</b> ✅' if new_status else '<b>disabled</b> 🚫'}.")
        logger.info(f"Admin {user_id} toggled auto-delete to {'enabled' if new_status else 'disabled'}.")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to toggle auto-delete: {e}", exc_info=True)
        await message.reply("❌ An error occurred while toggling auto-delete. Please try again. 🐛")

@bot.on_message(filters.command('toggle_protect') & filters.private & admin_only)
async def toggle_protect(client: Client, message: Message):
    """Admin command to toggle content protection for sent videos."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} requested to toggle content protection.")
    try:
        s = settings_collection.find_one({'_id': 'settings'}) or {'protect_content': True}
        new_status = not s.get('protect_content', True)
        settings_collection.update_one({'_id': 'settings'}, {'$set': {'protect_content': new_status}}, upsert=True)
        await message.reply(f"Content protection is now {'<b>enabled</b> ✅' if new_status else '<b>disabled</b> 🚫'}.")
        logger.info(f"Admin {user_id} toggled content protection to {'enabled' if new_status else 'disabled'}.")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to toggle content protection: {e}", exc_info=True)
        await message.reply("❌ An error occurred while toggling content protection. Please try again. 🐛")

# --- Database Cleanup ---
async def cleanup_expired_data():
    """Periodically cleans up expired tokens and handles bookmark truncation for non-premium users."""
    while True:
        try:
            now = datetime.now(timezone.utc)

            tokens_collection.update_many(
                {},
                {'$pull': {'tokens': {'expires_at': {'$lt': now}}}}
            )
            logger.info("Expired tokens cleanup completed.")

            all_users = users_collection.find({})
            for user in all_users:
                user_id = user['user_id']

                is_currently_premium = is_premium_user(user_id)

                bookmarked_videos = user.get('bookmarked_videos', [])

                if not is_currently_premium and len(bookmarked_videos) > config.FREE_USER_SAVE_LIMIT:
                    bookmarked_videos.sort(key=lambda x: x.get('bookmarked_at', datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
                    truncated_bookmarks = bookmarked_videos[:config.FREE_USER_SAVE_LIMIT]

                    users_collection.update_one(
                        {'user_id': user_id},
                        {'$set': {'bookmarked_videos': truncated_bookmarks}}
                    )
                    logger.info(f"User {user_id}'s bookmarked videos truncated to {config.FREE_USER_SAVE_LIMIT}.")

            history_collection.delete_many({'history': {'$size': 0}})
            logger.info("Empty history documents cleanup completed.")

            tokens_collection.delete_many({'tokens': {'$size': 0}})
            logger.info("Empty token documents cleanup completed.")

            logger.info("Database cleanup cycle completed.")
        except asyncio.CancelledError:
            logger.info("cleanup_expired_data task cancelled gracefully.")
            break
        except Exception as e:
            logger.error(f"Error in database cleanup task: {e}", exc_info=True)

        await asyncio.sleep(86400)

async def cleanup_expired_menus():
    """
    Periodically checks for and deletes expired interactive menus from chats.
    A menu is considered expired if its timestamp in active_video_message is older than MENU_EXPIRY_MINUTES.
    """
    while True:
        logger.info("Starting expired menu cleanup task.")
        now = datetime.now(timezone.utc)
        expired_threshold = now - timedelta(minutes=config.MENU_EXPIRY_MINUTES)

        users_to_clear = []
        for user_id, menu_info in list(active_video_message.items()):
            if menu_info.get('timestamp') and menu_info['timestamp'] < expired_threshold:
                chat_id = menu_info['chat_id']
                message_id = menu_info['message_id']

                logger.info(f"Attempting to delete expired menu for user {user_id} (msg_id: {message_id}, chat_id: {chat_id}).")
                try:
                    await bot.delete_messages(chat_id, message_id)
                    logger.info(f"Successfully deleted expired menu message {message_id} for user {user_id}.")
                    await bot.send_message(
                        chat_id,
                        "⏳ Video Expired!\nTap below to get a new video.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Get Video", callback_data="get_default_video")]])
                    )
                except MessageIdInvalid:
                    logger.info(f"Expired menu message {message_id} for user {user_id} already deleted or invalid.")
                    await bot.send_message(
                        chat_id,
                        "⏳ Video Expired!\nTap below to get a new video.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Get Video", callback_data="get_default_video")]])
                    )
                except Exception as e:
                    logger.error(f"Failed to delete expired menu message {message_id} for user {user_id}: {e}", exc_info=True)
                    try:
                        await bot.send_message(
                            chat_id,
                            "⏳ Video Expired!\nTap below to get a new video.",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Get Video", callback_data="get_default_video")]])
                        )
                    except Exception as send_e:
                        logger.error(f"Failed to send expiry notification to user {user_id}: {send_e}")
                finally:
                    users_to_clear.append(user_id)

        for user_id in users_to_clear:
            clear_active_video_message(user_id)
            logger.info(f"Cleared active_video_message state for user {user_id} after menu expiry.")

        try:
            sleep_interval = max(60, config.MENU_EXPIRY_MINUTES * 60 / 2)
            await asyncio.sleep(sleep_interval)
        except asyncio.CancelledError:
            logger.info("cleanup_expired_menus task cancelled gracefully.")
            break
        except Exception as e:
            logger.error(f"Error during sleep in cleanup_expired_menus: {e}", exc_info=True)

async def verify_and_cleanup_media():
    """Periodically verifies if media files still exist in the channel and logs missing/inaccessible entries, but does NOT delete anything."""
    while True:
        logger.info("Starting media verification and cleanup task.")
        if not DATA_CHANNEL_ID:
            logger.warning("DATA_CHANNEL_ID is not set. Skipping media verification.")
            await asyncio.sleep(6 * 3600)
            continue

        try:
            all_media = list(media_collection.find({}))
            for media_item in all_media:
                video_uuid = media_item.get('uuid')
                message_id_in_channel = media_item.get('message_id')

                if not message_id_in_channel:
                    logger.warning(f"Media item {video_uuid} has no message_id in channel. (Would delete, but deletion is disabled)")
                    continue

                try:
                    await bot.get_messages(DATA_CHANNEL_ID, message_id_in_channel)
                    logger.debug(f"Verified media {video_uuid} (message_id: {message_id_in_channel}) exists in channel.")
                except (MessageIdInvalid, ValueError):
                    logger.warning(f"Video {video_uuid} (message_id: {message_id_in_channel}) no longer exists in channel. (Would delete, but deletion is disabled)")
                    continue
                except Exception as e:
                    logger.error(f"Error verifying media {video_uuid} in channel {DATA_CHANNEL_ID}: {e}", exc_info=True)
                    if "not enough rights" in str(e).lower() or "permission" in str(e).lower() or "access" in str(e).lower():
                        logger.warning(f"Bot has no access to channel. Skipping deletion for {video_uuid}.")
                        continue
                    continue

            logger.info("Media verification and cleanup task completed.")
        except asyncio.CancelledError:
            logger.info("verify_and_cleanup_media task cancelled gracefully.")
            break
        except Exception as e:
            logger.error(f"Error in media verification cleanup task: {e}", exc_info=True)

        await asyncio.sleep(6 * 3600)


async def keep_alive():
    """Sends a message every 2 minutes to keep the bot alive on Render."""
    while True:
        try:
            sent_message = await bot.send_message(config.OWNER_ID, "Bot is running...")
            await sent_message.delete()
        except Exception as e:
            logger.error(f"Keep-alive task failed: {e}", exc_info=True)
        await asyncio.sleep(120) # Sleep for 2 minutes


async def health_check():
    try:
        me = await bot.get_me()
        logger.info(f"Bot username: {me.username}")

        if DATA_CHANNEL_ID:
            try:
                member = await bot.get_chat_member(DATA_CHANNEL_ID, me.id)
                logger.info(f"Bot status in data channel ({DATA_CHANNEL_ID}): {member.status}")
            except Exception as e:
                logger.error(f"Health check failed for data channel {DATA_CHANNEL_ID}: {e}", exc_info=True)
        else:
            logger.warning("No data channel configured. Skipping data channel health check.")

        if FORCE_SUB_CHANNELS:
            for channel_info in FORCE_SUB_CHANNELS:
                try:
                    force_sub_member = await bot.get_chat_member(channel_info['channel_id'], me.id)
                    logger.info(f"Bot status in force subscribe channel ({channel_info['channel_id']}): {force_sub_member.status}")
                except Exception as e:
                    logger.error(f"Health check failed for force subscribe channel {channel_info['channel_id']}: {e}", exc_info=True)
        else:
            logger.warning("No force subscribe channels configured. Skipping force sub health check.")

    except Exception as e:
        logger.error(f"Overall health check failed: {e}", exc_info=True)

async def monitor_ssrb_verifications(client: Client):
    """
    Background task to monitor SSRB verifications and grant tokens in ATDB.
    """
    logger.info("Starting SSRB verification monitor task...")
    while True:
        try:
            # Find unconsumed verifications
            unconsumed = list(ssrb_verifications_collection.find({"is_consumed_by_atdb": False}))
            for doc in unconsumed:
                user_id = doc['user_id']
                logger.info(f"Detected new SSRB verification for user {user_id}. Granting token...")

                # Grant token
                duration = config.VERIFICATION_TOKEN_DURATION_HOURS * 3600
                add_token(user_id, duration_seconds=duration, is_admin_granted=False)

                # Notify user
                try:
                    await client.send_message(
                        user_id,
                        f"✅ <b>Verification Successful!</b>\n\n"
                        f"You have received your token! It has been added to your bank. Activate it whenever you need access! 🏦"
                    )
                except Exception as e:
                    logger.warning(f"Failed to notify user {user_id} about ATDB token: {e}")

                # NEW: Automatically load request if pending command exists
                user_doc = users_collection.find_one_and_update(
                    {'user_id': user_id},
                    {'$unset': {'pending_command': ""}},
                    return_document=ReturnDocument.BEFORE
                )
                pending_command = user_doc.get('pending_command') if user_doc else None

                if pending_command:
                    try:
                        await client.send_message(user_id, "✅ Verification Success! Loading your content now...")
                        # Reuse start_cmd by creating a mock message
                        mock_msg = Message(
                            id=0,
                            client=client,
                            text=f"/start {pending_command}",
                            from_user=HyUser(id=user_id, is_bot=False, first_name="User"),
                            chat=HyChat(id=user_id, type=ChatType.PRIVATE),
                            date=datetime.now(timezone.utc)
                        )
                        create_tracked_task(start_cmd(client, mock_msg))
                    except Exception as e:
                        logger.error(f"Failed to auto-trigger pending command for user {user_id}: {e}")

                # Mark as consumed
                ssrb_verifications_collection.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"is_consumed_by_atdb": True}}
                )

        except Exception as e:
            logger.error(f"Error in monitor_ssrb_verifications: {e}", exc_info=True)

        await asyncio.sleep(10) # Poll every 10 seconds

async def run_bot_background():
    """
    Starts the Hydrogram client and background tasks.
    """
    try:
        logger.info("Starting Hydrogram client...")

        try:
            await bot.start()
        except RPCError as e:
            if any(err in str(e) for err in ["SESSION_REVOKED", "SESSION_EXPIRED", "USER_DEACTIVATED"]):
                logger.error(f"Session is invalid ({e}). Clearing session string and forcing container restart.")
                settings_collection.delete_one({'_id': 'hydrogram_session'})
                # Force exit to trigger container restart on hosting platforms
                os._exit(1)
            raise e
        logger.info("Hydrogram client started.")

        # If this is the first run, save the session string
        SESSION_STRING = get_session_string()
        if not SESSION_STRING:
            logger.info("Saving session string to DB for future runs...")
            new_session_string = await bot.export_session_string()
            set_session_string(new_session_string)

        # Load admins and run background tasks
        await load_admins_from_db()
        await load_data_channel_id()
        await load_force_sub_channels()
        await load_shortener_setting()
        await load_upload_config()
        await health_check()
        create_tracked_task(cleanup_expired_data())
        create_tracked_task(verify_and_cleanup_media())
        create_tracked_task(cleanup_expired_menus())
        create_tracked_task(keep_alive())
        create_tracked_task(monitor_ssrb_verifications(bot))
        logger.info("Bot background initialization complete. Bot is now fully operational.")
    except Exception as e:
        logger.error(f"Error during bot background initialization: {e}", exc_info=True)



if __name__ == "__main__":
    # PRIMARY DIRECTIVE: The FastAPI/Web server must bind to the port defined by the
    # PORT environment variable (defaulting to 10000).

    # ENVIRONMENT PRIORITY: Force the application to prioritize the system's PORT
    # variable over any hardcoded values to ensure it stays in sync with Render's load balancer.
    port = int(os.environ.get("PORT", 10000))

    # NON-BLOCKING: The web server listener starts immediately via uvicorn.
    # The Hydrogram client initialization has been moved to a non-blocking background
    # task in the FastAPI startup event handler.
    # We use loop='asyncio' to ensure compatibility with Python 3.14 and
    # prevent conflicts between uvloop and Hydrogram's internal logic.
    uvicorn.run(app, host="0.0.0.0", port=port, loop="asyncio")
