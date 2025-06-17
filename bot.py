# Spicy Nyraa Bot - Main Script
import os
import asyncio
import uuid
import base64
import random
import logging
from datetime import datetime, timedelta
from typing import List
from pyrogram import Client, filters
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, Message, CallbackQuery
)
from pyrogram.errors import UserIsBlocked, ChatInvalid, MessageIdInvalid, UserNotParticipant, FloodWait
from pymongo import MongoClient, ASCENDING
import aiohttp
import re
import html
from pyrogram.enums import ChatMemberStatus
import traceback
import pyrogram.errors.exceptions.bad_request_400

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Configuration ---

class BotConfig:
    BOT_TOKEN = '7213744072:AAGMCqo0OhNaCHFya8M0aETz3rn-eIwyFQ8'
    API_ID = 29800015
    API_HASH = 'c8f37108be31ab9ea2818bfe533fbb6f'
    BOT_USERNAME = '@Spicynyraabot'
    MONGO_URI = 'mongodb+srv://Pyasipriya:00pEcao9sYhNC5VQ@cluster0.2dfenf7.mongodb.net/spicybot?retryWrites=true&w=majority&appName=Cluster0'
    MONGO_DB_NAME = 'spicybot'
    CHANNEL_ID = -1002622483638 # Corrected Channel ID
    VIDEO_CHANNEL_ID = -1002626689003
    CHANNEL_JOIN_LINK = 'https://t.me/spicynyraa' # New hardcoded join link
    BUY_BOT_URL = 'https://t.me/hanielxsupportbot'
    ADMIN_IDS = [6612030110]
    URL_SHORTENER = 'https://api.linkshortify.com/st'
    SHORTENER_API_KEY = '5cd923c490f64017cffa6e3bb6cc724560a8cfc6'
    TUTORIAL_LINK_2 = 'https://t.me/urlshortenertutorial'
    TOKEN_EXPIRY = 86400  # 24 hours in seconds
    DEFAULT_CATEGORY = 'default'
    NEW_USER_TOKENS = 3
    REFERRAL_BONUS = 1
    REFRESH_BONUS = 1
    MENU_TIMEOUT = 1800
    FORCE_MSG = "<b>To use this bot, you must join our channel first!</b>"
    JOIN_REQUEST_ENABLE = False
    START_MSG = "👋 Welcome! Use the menu below."
    START_PIC = None
    AUTO_DELETE_TIME = 1200 # 20 minutes
    AUTO_DEL_SUCCESS_MSG = "✅ Message auto-deleted successfully!"

try:
    config = BotConfig()
    if not all([
        config.BOT_TOKEN, config.API_ID, config.API_HASH, config.MONGO_URI,
        config.SHORTENER_API_KEY
    ]):
        raise ValueError("One or more essential configuration variables are not set. Please check BOT_TOKEN, API_ID, API_HASH, MONGO_URI, SHORTENER_API_KEY in your environment variables.")
except Exception as e:
    raise RuntimeError(f"Failed to load bot configuration: {e}")

# --- MongoDB Setup ---
client = MongoClient(config.MONGO_URI)
db = client[config.MONGO_DB_NAME]
users_collection = db['users']
tokens_collection = db['tokens']
media_collection = db['media']
history_collection = db['history']
categories_collection = db['categories']
settings_collection = db['settings']

# Create indexes
users_collection.create_index([("user_id", ASCENDING)], unique=True)
tokens_collection.create_index([("user_id", ASCENDING)], unique=True)
media_collection.create_index([("uuid", ASCENDING)], unique=True)
media_collection.create_index([("category", ASCENDING)])
media_collection.create_index([("file_unique_id", ASCENDING)], unique=True)
media_collection.create_index([("size_bytes", ASCENDING)])
history_collection.create_index([("history.viewed_at", ASCENDING)]) # Added index for history viewed_at
history_collection.create_index([("user_id", ASCENDING)], unique=True)
categories_collection.create_index([("name", ASCENDING)], unique=True)

# --- Pyrogram Client ---
app = Client("spicynyraa", api_id=config.API_ID, api_hash=config.API_HASH, bot_token=config.BOT_TOKEN)

# --- Admin Check Utility ---
def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS

# --- Utility Functions ---
def str_to_b64(string: str) -> str:
    return base64.urlsafe_b64encode(string.encode()).decode()

def b64_to_str(b64: str) -> str:
    try:
        return base64.urlsafe_b64decode(b64.encode()).decode()
    except Exception as e:
        logger.error(f"Failed to decode base64 string: {e}")
        return None

def get_current_time() -> int:
    return int(datetime.utcnow().timestamp())

async def shorten_url(long_url: str) -> str:
    logger.info(f"Attempting to shorten URL: {long_url}")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(config.URL_SHORTENER, json={
                'api': config.SHORTENER_API_KEY,
                'url': long_url
            }, timeout=10) as resp:
                logger.info(f"URL shortener API response status: {resp.status}")
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('shortenedUrl'):
                        logger.info(f"URL shortened successfully to: {data['shortenedUrl']}")
                        return data['shortenedUrl']
                    else:
                        logger.warning(f"URL shortening API returned 200 but no shortenedUrl: {data}")
                else:
                    logger.warning(f"URL shortening API returned non-200 status {resp.status} for {long_url}")
        logger.warning(f"URL shortening failed for {long_url} after API call.")
        return long_url
    except aiohttp.ClientError as ce:
        logger.error(f"Aiohttp client error during URL shortening for {long_url}: {ce}", exc_info=True)
        return long_url
    except Exception as e:
        logger.error(f"General error shortening URL {long_url}: {e}", exc_info=True)
        return long_url

# --- Token Management ---
def get_valid_tokens(user_id: int) -> List[dict]:
    doc = tokens_collection.find_one({'user_id': user_id})
    if not doc:
        return []
    now = datetime.utcnow()
    return [t for t in doc['tokens'] if t['expires_at'] > now]

def add_token(user_id: int, duration: int = None) -> dict:
    if duration is None:
        duration = config.TOKEN_EXPIRY
    now = datetime.utcnow()
    expires = now + timedelta(seconds=duration)
    token = {
        'token_id': str(uuid.uuid4()),
        'created_at': now,
        'expires_at': expires
    }
    try:
        tokens_collection.update_one(
            {'user_id': user_id},
            {'$push': {'tokens': token}},
            upsert=True
        )
        logger.info(f"Token added for user {user_id}")
        return token
    except Exception as e:
        logger.error(f"Error adding token for user {user_id}: {e}", exc_info=True)
        return None

def get_and_cleanup_tokens(user_id: int) -> List[dict]:
    if is_admin(user_id):
        return [{'token_id': 'admin', 'created_at': datetime.utcnow(), 'expires_at': datetime.utcnow() + timedelta(days=365)}]
    now = datetime.utcnow()
    try:
        tokens_collection.update_one(
            {'user_id': user_id},
            {'$pull': {'tokens': {'expires_at': {'$lt': now}}}},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error cleaning up expired tokens for user {user_id}: {e}", exc_info=True)
    doc = tokens_collection.find_one({'user_id': user_id})
    return doc.get('tokens', []) if doc else []

def user_has_token(user_id: int) -> bool:
    if is_admin(user_id):
        return True
    return len(get_and_cleanup_tokens(user_id)) > 0

# --- Referral System ---
def handle_referral(new_user_id: int, ref_code: str):
    if ref_code.startswith('ref_'):
        referrer_id = int(ref_code[4:])
        if referrer_id != new_user_id:
            ref_user = users_collection.find_one({'user_id': referrer_id})
            if ref_user:
                add_token(referrer_id)
                users_collection.update_one({'user_id': referrer_id}, {'$inc': {'referral_count': 1}}, upsert=True)
                users_collection.update_one({'user_id': new_user_id}, {'$set': {'referred_by': referrer_id}}, upsert=True)
                return referrer_id
    return None

# --- Subscription Check ---
async def check_subscription(client: Client, user_id: int) -> bool:
    logger.info(f"Checking subscription for user {user_id} in channel {config.CHANNEL_ID}")
    try:
        member = await client.get_chat_member(int(config.CHANNEL_ID), user_id)
        logger.info(f"User {user_id} subscription status in channel {config.CHANNEL_ID}: {member.status}")
        return member.status in ["member", "administrator", "creator"]
    except pyrogram.errors.exceptions.bad_request_400.ChannelInvalid as e:
        logger.error(f"ChannelInvalid error checking subscription for user {user_id} in channel {config.CHANNEL_ID}: {e}. Ensure bot is admin and CHANNEL_ID is correct.", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"Error checking subscription for user {user_id} in channel {config.CHANNEL_ID}: {e}", exc_info=True)
        # Added for more detailed logging of Pyrogram errors
        if hasattr(e, 'MESSAGE') and hasattr(e, 'ID') and hasattr(e, 'NAME'):
            logger.error(f"Pyrogram Error Details: MESSAGE={e.MESSAGE}, ID={e.ID}, NAME={e.NAME}")
        return False

# Cache subscription status
subscription_cache = {}
SUBSCRIPTION_CACHE_TTL = 60  # 1 minutes

async def check_subscription_cached(client: Client, user_id: int) -> bool:
    """Check subscription status with caching"""
    if is_admin(user_id):  # Skip cache for admins
        return await check_subscription(client, user_id)
        
    now = get_current_time()
    cache_key = f"{user_id}"
    
    # Return cached result if valid
    if cache_key in subscription_cache:
        status, timestamp = subscription_cache[cache_key]
        if now - timestamp < SUBSCRIPTION_CACHE_TTL:
            return status
    
    # Check actual status
    try:
        member = await client.get_chat_member(config.CHANNEL_ID, user_id)
        status = member.status in ["member", "administrator", "creator"]
        subscription_cache[cache_key] = (status, now)
        return status
    except Exception as e:
        logger.error(f"Error checking subscription for user {user_id} in channel {config.CHANNEL_ID} (cached function): {e}", exc_info=True)
        return False

# Custom Filter for Subscribed Users
async def _subscribed_filter(_, client, message: Message):
    return await check_subscription_cached(client, message.from_user.id)

subscribed = filters.create(_subscribed_filter)

# --- Category Management ---
def validate_category_name(name: str) -> tuple[bool, str]:
    """Validate a category name.
    Returns (is_valid, error_message)"""
    if not name:
        return False, "Category name cannot be empty."
    if not re.match(r'^[a-zA-Z0-9_-]+$', name):
        return False, "Category name can only contain letters, numbers, underscores, and hyphens."
    if len(name) > 32:
        return False, "Category name cannot be longer than 32 characters."
    return True, ""

def get_categories() -> list[str]:
    """Get all category names, ensuring default category exists."""
    categories = [c['name'] for c in categories_collection.find({})]
    if not categories or config.DEFAULT_CATEGORY not in categories:
        add_category(config.DEFAULT_CATEGORY)
        categories = [config.DEFAULT_CATEGORY]
    return categories

def add_category(name: str) -> tuple[bool, str]:
    """Add a new category.
    Returns (success, message)"""
    try:
        # Validate name
        valid, error = validate_category_name(name)
        if not valid:
            return False, error
            
        # Check if exists
        if categories_collection.find_one({'name': name}):
            return False, f"Category '{name}' already exists."
            
        # Add category
        categories_collection.insert_one({
            'name': name,
            'created_at': datetime.utcnow()
        })
        logger.info(f"Category '{name}' added")
        return True, f"Category '{name}' added successfully."
    except Exception as e:
        logger.error(f"Error adding category '{name}': {e}")
        return False, "Failed to add category. Please try again."

def delete_category(name: str) -> tuple[bool, str, int]:
    """Delete a category and its videos.
    Returns (success, message, deleted_count)"""
    try:
        # Don't allow deleting default category
        if name == config.DEFAULT_CATEGORY:
            return False, "Cannot delete the default category.", 0
            
        # Check if exists
        if not categories_collection.find_one({'name': name}):
            return False, f"Category '{name}' does not exist.", 0
            
        # Delete videos in category
        result = media_collection.delete_many({'category': name})
        deleted_count = result.deleted_count
        
        # Delete category
        categories_collection.delete_one({'name': name})
        logger.info(f"Category '{name}' and {deleted_count} videos deleted")
        return True, f"Category '{name}' and {deleted_count} videos deleted.", deleted_count
    except Exception as e:
        logger.error(f"Error deleting category '{name}': {e}")
        return False, "Failed to delete category. Please try again.", 0

# --- Video Navigation ---
def get_random_video(category: str):
    videos = list(media_collection.find({'category': category}))
    if not videos:
        return None
    return random.choice(videos)

def get_video_by_uuid(uuid_: str):
    return media_collection.find_one({'uuid': uuid_})

def save_history(user_id: int, video_uuid: str, category: str):
    now = datetime.utcnow()
    entry = {'video_uuid': video_uuid, 'category': category, 'viewed_at': now}
    try:
        history_collection.update_one(
            {'user_id': user_id},
            {'$push': {'history': {'$each': [entry], '$slice': -100}}}, # Limit history to last 100 entries
            upsert=True
        )
        logger.info(f"History saved for user {user_id}, video {video_uuid}. History size limited to 100.")
    except Exception as e:
        logger.error(f"Error saving history for user {user_id}, video {video_uuid}: {e}", exc_info=True)

def get_last_video(user_id: int):
    doc = history_collection.find_one({'user_id': user_id})
    if doc and doc.get('history'):
        return doc['history'][-2] if len(doc['history']) > 1 else None
    return None

# --- Menu State Management ---
active_menus = {}
MENU_TIMEOUT = config.MENU_TIMEOUT  # Use configured timeout

def set_active_menu(user_id: int, message_id: int):
    """Set an active menu for a user."""
    active_menus[user_id] = {
        'message_id': message_id,
        'timestamp': get_current_time(),
        'chat_id': None  # Will be set when needed
    }

def clear_active_menu(user_id: int):
    """Clear a user's active menu state."""
    if user_id in active_menus:
        del active_menus[user_id]

async def cleanup_expired_menu(client: Client, user_id: int, chat_id: int = None):
    """Clean up an expired menu by deleting the message."""
    try:
        menu = active_menus.get(user_id)
        if menu and chat_id:
            try:
                await client.delete_messages(chat_id, menu['message_id'])
                logger.info(f"Deleted expired menu message {menu['message_id']} for user {user_id}")
            except Exception as e:
                logger.error(f"Failed to delete expired menu message {menu['message_id']} for user {user_id} in chat {chat_id}: {e}")
        clear_active_menu(user_id)
    except Exception as e:
        logger.error(f"Error in cleanup_expired_menu for user {user_id}: {e}")

async def is_menu_active(client: Client, user_id: int, chat_id: int = None) -> bool:
    """Check if a user has an active menu and clean up if expired."""
    if user_id not in active_menus:
        return False
        
    menu = active_menus[user_id]
    if get_current_time() - menu['timestamp'] > MENU_TIMEOUT:
        await cleanup_expired_menu(client, user_id, chat_id)
        return False
        
    # Update chat_id if provided
    if chat_id and not menu.get('chat_id'):
        menu['chat_id'] = chat_id
        
    return True

# --- Keyboards ---
def join_channel_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Join Channel", url=config.CHANNEL_JOIN_LINK)],
        [InlineKeyboardButton("Check Subscription", callback_data="check_sub")]
    ])

def token_earning_keyboard(ad_url):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Click Here To Refresh Token", url=ad_url)],
        [InlineKeyboardButton("How To Open Links?", url=config.TUTORIAL_LINK_2)],
        [InlineKeyboardButton("Buy Token", url=config.BUY_BOT_URL)]
    ])

def category_keyboard():
    cats = get_categories()
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(cat, callback_data=f"cat_{cat}")] for cat in cats]
    )

def video_nav_keyboard(video_uuid, category):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Previous", callback_data=f"prev_{video_uuid}_{category}"),
            InlineKeyboardButton("Next", callback_data=f"next_{video_uuid}_{category}")
        ],
        [InlineKeyboardButton("Change Category", callback_data="change_cat")],
        [InlineKeyboardButton("Share", callback_data=f"share_{video_uuid}")]
    ])

def referral_keyboard(ref_link):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Copy Referral Link", url=ref_link)]
    ])

def buy_token_keyboard():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Buy Token", url=config.BUY_BOT_URL)]]
    )

async def get_main_keyboard(user_id: int = None) -> ReplyKeyboardMarkup:
    """Async version of main_keyboard that uses cached subscription check"""
    buttons = [
        [KeyboardButton("Get Video"), KeyboardButton("Profile")],
        [KeyboardButton("Refer & Earn"), KeyboardButton("Buy Token")],
        [KeyboardButton("Refresh Token")]
    ]
    
    # Add subscription buttons if user is not subscribed
    if user_id and not await check_subscription_cached(app, user_id):
        buttons.insert(0, [KeyboardButton("Join Channel"), KeyboardButton("Check Subscription")])
    
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

# --- Video Sharing ---
async def handle_shared_video(client, user_id, video_uuid, message_id=None):
    video = get_video_by_uuid(video_uuid)
    if not video:
        logger.warning(f"User {user_id} attempted to view non-existent shared video {video_uuid}.")
        return False, "Oops, invalid link. Try again!"
    
    if video.get('banned'): # Check for banned status
        logger.warning(f"User {user_id} attempted to view banned video {video_uuid}.")
        return False, "❌ This content is no longer available."
    
    if not user_has_token(user_id):
        return False, await send_token_earning_options(client, message_id)
        
    if not await check_subscription_cached(client, user_id): # Using cached subscription check
        return False, "Join the channel to watch!", join_channel_keyboard()
    
    save_history(user_id, video_uuid, video['category'])
    return True, video

# --- Token Refresh ---
async def handle_token_refresh(user_id: int, ad_code: str):
    try:
        if is_rate_limited(user_id):
            return False, "⚠️ You're refreshing too quickly. Please wait a minute and try again."

        # Prevent token refresh if user already has valid tokens
        if user_has_token(user_id):
            logger.info(f"User {user_id} attempted token refresh but already has valid tokens.")
            return False, "💡 You already have an active token. No need to refresh yet!"
            
        decoded = b64_to_str(ad_code)
        if not decoded:
            logger.warning(f"User {user_id} provided invalid base64 for token refresh: {ad_code}")
            return False, "Oops, invalid link. Try again!"
        
        try:
            code_user_id, timestamp = map(int, decoded.split(':'))
        except ValueError:
            logger.error(f"User {user_id} provided invalid token refresh code format: {ad_code}")
            return False, "Invalid token refresh link format."
            
        if code_user_id != user_id:
            logger.warning(f"User {user_id} attempted to use another user's token refresh link ({code_user_id}).")
            return False, "This token refresh link is not for you."
            
        if timestamp < get_current_time():
            logger.warning(f"User {user_id} attempted to use expired token refresh link.")
            return False, "This token refresh link has expired."
            
        added_token = add_token(user_id, config.REFRESH_BONUS * 86400) # Use REFRESH_BONUS and convert to seconds
        if added_token:
            logger.info(f"Token added for user {user_id} via refresh. New token count: {len(get_valid_tokens(user_id))}")
            return True, f"🎉 <b>Success!</b> You got {config.REFRESH_BONUS} token. Each token lasts 24 hours."
        else:
            return False, "❌ <b>Something went wrong!</b>\nFailed to add token. Please try again later."
    except Exception as e:
        logger.error(f"Token refresh failed for user {user_id}: {e}", exc_info=True)
        return False, "❌ <b>Something went wrong!</b>\nPlease try again later."

# --- Auto-Delete & Protect Content ---
async def schedule_auto_delete(message: Message, delay: int = 1200):  # 20 minutes
    try:
        await asyncio.sleep(delay)
        await message.delete()
        logger.info(f"Auto-deleted message {message.id} from chat {message.chat.id}")
    except Exception as e:
        logger.error(f"Failed to auto-delete message {message.id}: {e}")

async def send_video_with_auto_delete(client: Client, chat_id: int, video_data: dict, reply_markup=None):
    settings = settings_collection.find_one({'_id': 'settings'}) or {}
    protect_content = settings.get('protect_content', True)
    auto_delete = settings.get('auto_delete', True)
    
    try:
        sent = await client.send_video(
            chat_id,
            video_data['file_id'],
            caption=f"Category: {video_data['category']}",
            reply_markup=reply_markup,
            protect_content=protect_content
        )
        
        if auto_delete:
            asyncio.create_task(schedule_auto_delete(sent))
        
        return True, sent # Return success and the sent message object
    except Exception as e:
        logger.error(f"Failed to send video to chat {chat_id}: {e}")
        return False, "❌ <b>Failed to send video.</b>\nPlease try again later." # Return failure and an error message

# --- Rate Limiting ---
# In-memory defaultdict for rate limiting (will be replaced by MongoDB)
# rate_limits = defaultdict(list)
RATE_LIMIT_WINDOW = 120  # Increased to 2 minutes
RATE_LIMIT_MAX = 60  # Increased to 60 requests per 2 minutes

async def is_rate_limited(user_id: int) -> bool:
    if is_admin(user_id):  # Skip rate limiting for admins
        return False
        
    now = datetime.utcnow()
    window_start = now - timedelta(seconds=RATE_LIMIT_WINDOW)
    
    # Use aggregation to count documents within the sliding window efficiently
    # This ensures only active rate limit entries are considered
    try:
        # First, remove old entries to keep the array lean and accurate
        tokens_collection.update_one(
            {'user_id': user_id},
            {'$pull': {'rate_limits': {'timestamp': {'$lt': window_start}}}},
            upsert=True
        )
    
        # Then, push the new timestamp
        tokens_collection.update_one(
            {'user_id': user_id},
            {'$push': {'rate_limits': {'timestamp': now}}},
            upsert=True
        )

        # Get the count after adding the new entry and cleaning up old ones
        rate_limit_doc = tokens_collection.find_one({'user_id': user_id}, {'rate_limits': 1})
        current_requests = len(rate_limit_doc.get('rate_limits', [])) if rate_limit_doc else 0
        
        if current_requests > RATE_LIMIT_MAX:
            logger.warning(f"User {user_id} is rate limited. Current requests: {current_requests}, Max: {RATE_LIMIT_MAX}")
            return True
        return False
    except Exception as e:
        logger.error(f"Error in is_rate_limited for user {user_id}: {e}", exc_info=True)
        # Default to not rate-limiting if there's a database error to prevent bot from stopping
        return False

# --- Error Handling ---
async def handle_error(client: Client, message: Message, error: Exception):
    if isinstance(error, UserNotParticipant):
        return
    elif isinstance(error, FloodWait):
        logger.warning(f"FloodWait: {error.value} seconds")
        await message.reply_text(f"⚠️ <b>Too Many Requests!</b>\nPlease wait <b>{error.value}</b> seconds before trying again.")
    else:
        logger.error(f"An error occurred: {error}", exc_info=True)
        await message.reply_text(f"❌ <b>An unexpected error occurred.</b>\nPlease try again later.")

# --- Handlers ---
@app.on_message(filters.command("start") & filters.private & subscribed)
async def start_command(client, message: Message):
    # This is your main /start logic for subscribed users (copy from your current start_cmd)
    # ... existing start_cmd code here ...
    user_id = message.from_user.id
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            if await is_rate_limited(user_id):
                raise FloodWait(10)
            user = users_collection.find_one({'user_id': user_id})
            args = message.text.split()
            if not user:
                users_collection.insert_one({
                    'user_id': user_id,
                    'username': html.escape(message.from_user.username) if message.from_user.username else None,
                    'first_name': html.escape(message.from_user.first_name) if message.from_user.first_name else None,
                    'last_name': html.escape(message.from_user.last_name) if message.from_user.last_name else None,
                    'joined_date': datetime.utcnow(),
                    'referral_count': 0
                })
                for _ in range(config.NEW_USER_TOKENS):
                    add_token(user_id)
                logger.info(f"New user registered: {user_id}")
                if len(args) > 1:
                    ref_code = args[1]
                    referrer_id = handle_referral(user_id, ref_code)
                    if referrer_id:
                        logger.info(f"User {user_id} referred by {referrer_id} via referral link.")
            if len(args) > 1:
                arg = args[1]
                if arg.startswith('token_'):
                    success, msg = await handle_token_refresh(user_id, arg[6:])
                    await message.reply(msg)
                    if success:
                        await message.reply(
                            "🎉 <b>Success!</b> Click on Get Video to watch spicy content.",
                            reply_markup=await get_main_keyboard(user_id)
                        )
                    return
                video_uuid = arg
                logger.info(f"User {user_id} attempting to view shared video {video_uuid}")
                try:
                    uuid.UUID(video_uuid)
                except ValueError:
                    logger.warning(f"User {user_id} attempted to view shared video with invalid UUID format: {video_uuid}.")
                    await handle_error(client, message, ValueError("Invalid video link format."))
                    return
                if not media_collection.find_one({'uuid': video_uuid}):
                    logger.warning(f"User {user_id} attempted to view non-existent shared video UUID {video_uuid}.")
                    await handle_error(client, message, ValueError("Invalid video link"))
                    return
                success, result_or_msg = await handle_shared_video(client, user_id, video_uuid)
                if not success:
                    if isinstance(result_or_msg, tuple):
                        error_msg, keyboard = result_or_msg
                        await message.reply(error_msg, reply_markup=keyboard)
                    else:
                        await message.reply(result_or_msg)
                    return
                video = result_or_msg
                if await is_menu_active(client, user_id, message.chat.id):
                    try:
                        old_menu = active_menus.get(user_id)
                        if old_menu and old_menu.get('chat_id'):
                            try:
                                await client.delete_messages(old_menu['chat_id'], old_menu['message_id'])
                                logger.info(f"User {user_id} deleted old menu message {old_menu['message_id']} for shared video update.")
                            except Exception as e:
                                logger.warning(f"User {user_id} failed to delete old menu message {old_menu['message_id']}: {e}")
                        sent_success, sent_message_or_error = await send_video_with_auto_delete(
                            client,
                            message.chat.id,
                            video,
                            reply_markup=video_nav_keyboard(video['uuid'], video['category'])
                        )
                        if sent_success:
                            save_history(user_id, video['uuid'], video['category'])
                            set_active_menu(user_id, sent_message_or_error.id)
                            await message.reply("🎉 <b>Success!</b> Video updated in your active menu.")
                            logger.info(f"User {user_id} updated menu with shared video {video_uuid}.")
                        else:
                            await message.reply(sent_message_or_error)
                    except Exception as e:
                        logger.error(f"User {user_id} failed to update menu with shared video: {e}", exc_info=True)
                        await handle_error(client, message, e)
                else:
                    sent_success, sent_message_or_error = await send_video_with_auto_delete(
                        client,
                        message.chat.id,
                        video,
                        reply_markup=video_nav_keyboard(video['uuid'], video['category'])
                    )
                    if sent_success:
                        save_history(user_id, video['uuid'], video['category'])
                        set_active_menu(user_id, sent_message_or_error.id)
                        logger.info(f"User {user_id} sent shared video {video_uuid} as new menu.")
                    else:
                        await message.reply(sent_message_or_error)
            if not user:
                user_mention_safe = html.escape(message.from_user.first_name) if message.from_user.first_name else "there"
                await message.reply(
                    f"👋 dear {user_mention_safe} This is Spicy Nyraa Bot. To watch spicy content, click on the Get Video button. Need help? Tap /help.",
                    reply_markup=await get_main_keyboard(user_id)
                )
            else:
                await message.reply(
                    "👋 This is Spicy Nyraa Bot. Click on Get Video to watch spicy content.",
                    reply_markup=await get_main_keyboard(user_id)
                )
            break
        except FloodWait as e:
            wait_time = e.value
            logger.warning(f"User {user_id} hit FloodWait: Waiting for {wait_time} seconds (attempt {attempt + 1}/{max_retries}).")
            await asyncio.sleep(wait_time + 1)
            if attempt < max_retries - 1:
                continue
            else:
                logger.error(f"User {user_id} failed to process /start after {max_retries} retries due to FloodWait.")
                await handle_error(client, message, e)
                break
        except Exception as e:
            logger.error(f"User {user_id} encountered an unexpected error in start command: {e}", exc_info=True)
            await handle_error(client, message, e)

@app.on_message(filters.command("start") & filters.private & ~subscribed)
async def not_joined(client, message: Message):
    user_id = message.from_user.id
    logger.info(f"User {user_id} not subscribed to channel, handled by not_joined().")
    if await is_rate_limited(user_id):
        await handle_error(client, message, FloodWait(10))
        logger.warning(f"User {user_id} hit rate limit in not_joined().")
        return

    join_link = config.CHANNEL_JOIN_LINK

    buttons = [[InlineKeyboardButton("Join Channel", url=join_link)]]
    args = message.text.split()
    if len(args) > 1:
        buttons.append([InlineKeyboardButton("Try Again", callback_data="try_again")])
    await message.reply(
        config.FORCE_MSG,
        reply_markup=InlineKeyboardMarkup(buttons)
    )

@app.on_message(filters.command("help") & filters.private)
async def help_cmd(client, message: Message):
    user_id = message.from_user.id
    # Sanitize message.from_user.mention explicitly
    user_mention_safe = html.escape(message.from_user.first_name) if message.from_user.first_name else "there"
    await message.reply(
        f"👋 dear {user_mention_safe} this is how to use spicy nyraa.\n\n"
        "- Use Get Video to watch spicy content.\n"
        "- Each token gives you 24 hours access.\n"
        "- Earn tokens by referral, refresh, or buy.\n"
        "- Join the channel to access videos.\n"
        "- Use /profile to check your stats.",
        reply_markup=await get_main_keyboard(user_id)
    )

@app.on_message(filters.command("profile") & filters.private)
async def profile_cmd(client, message: Message):
    user_id = message.from_user.id
    logger.info(f"User {user_id} requested profile.")
    if await is_rate_limited(user_id):
        await handle_error(client, message, FloodWait(10))
        logger.warning(f"User {user_id} hit rate limit in profile_cmd.")
        return

    user = users_collection.find_one({'user_id': user_id})
    tokens = get_and_cleanup_tokens(user_id)
    referral_count = user.get('referral_count', 0) if user else 0
    referred_by = user.get('referred_by', None) if user else None
    views = history_collection.find_one({'user_id': user_id})
    view_count = len(views['history']) if views and 'history' in views else 0
    ref_link = f"https://t.me/{config.BOT_USERNAME[1:]}?start=ref_{user_id}"
    
    # Sanitize user's first name and username for HTML (already present, verifying and ensuring usage)
    sanitized_first_name = html.escape(message.from_user.first_name if message.from_user.first_name else '')
    sanitized_username = html.escape(message.from_user.username if message.from_user.username else '')

    await message.reply(f"👤 <b>Your Profile</b>\n\n<b>Tokens:</b> {len(tokens)}\n<b>Video Views:</b> {view_count}\n<b>Referrals:</b> {referral_count}\n<b>Referral Link:</b> <code>{ref_link}</code>\n{(f'Referred by: {referred_by}') if referred_by else ''}", reply_markup=referral_keyboard(ref_link))

@app.on_message(filters.regex("^Get Video$") & filters.private)
async def get_video(client, message: Message):
    user_id = message.from_user.id
    logger.info(f"User {user_id} requested Get Video.")
    
    if await is_rate_limited(user_id):
        await handle_error(client, message, FloodWait(10))
        logger.warning(f"User {user_id} hit rate limit in get_video.")
        return

    if not await check_subscription_cached(client, user_id):
        logger.info(f"User {user_id} not subscribed, prompting to join channel.")
        await message.reply("📢 <b>Join our channel to watch videos!</b>", reply_markup=join_channel_keyboard())
        return
    if not user_has_token(user_id):
        logger.info(f"User {user_id} has no tokens, prompting earning options.")
        await send_token_earning_options(client, message)
        return
    
    chat_id = message.chat.id # Get chat_id here
    if await is_menu_active(client, user_id, chat_id): # Pass chat_id to is_menu_active
        logger.warning(f"User {user_id} tried to open new menu but active menu already open.")
        await message.reply("⚠️ <b>Menu Already Open</b>\nScroll up, your menu is already open.")
        return
    
    cats = get_categories()
    if not cats:
        add_category(config.DEFAULT_CATEGORY)
        cats = [config.DEFAULT_CATEGORY]
        logger.info(f"Default category '{config.DEFAULT_CATEGORY}' created for user {user_id}.")
    logger.info(f"User {user_id} prompted to choose category.")
    await message.reply("🎬 <b>Choose a Category:</b>", reply_markup=category_keyboard())

@app.on_callback_query(filters.regex(r"^cat_(.+)"))
async def select_category(client, callback_query):
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id
    category = callback_query.data[4:] # Extract category from callback_data
    logger.info(f"User {user_id} selected category: {category}.")
    
    if await is_rate_limited(user_id):
        await callback_query.answer("⚠️ You're changing categories too quickly. Please wait a minute and try again.", show_alert=True)
        logger.warning(f"User {user_id} hit rate limit in select_category.")
        return
        
    # Check for active menu
    if await is_menu_active(client, user_id, chat_id): # Pass chat_id
        logger.warning(f"User {user_id} tried to select category but already has active menu.")
        await callback_query.message.reply(
            "You already have an active menu. Please use that one or wait for it to expire."
        )
        return
        
    # Ensure category exists and sanitize input
    sanitized_category = html.escape(category)
    if sanitized_category not in get_categories():
        sanitized_category = config.DEFAULT_CATEGORY
        logger.warning(f"User {user_id} selected invalid category '{category}', falling back to default.")
    
    video = get_random_video(sanitized_category)
    if not video:
        logger.warning(f"No videos found in category '{sanitized_category}' for user {user_id}.")
        await callback_query.message.edit_text(
            "No videos in this category. Try another!",
            reply_markup=category_keyboard()
        )
        return
    
    try:
        sent_success, sent_message_or_error = await send_video_with_auto_delete(
            client,
            chat_id,
            video,
            reply_markup=video_nav_keyboard(video['uuid'], sanitized_category)
        )
        
        if sent_success:
            save_history(user_id, video['uuid'], sanitized_category)
            set_active_menu(user_id, sent_message_or_error.id)
            await callback_query.message.delete()
            logger.info(f"User {user_id} selected category {sanitized_category} and video {video['uuid']} sent.")
        else:
            logger.error(f"User {user_id} failed to send video after category selection: {sent_message_or_error}")
            await callback_query.message.edit_text(
                sent_message_or_error,
                reply_markup=category_keyboard()
            )
    except Exception as e:
        logger.error(f"User {user_id} error sending video after category selection: {e}", exc_info=True)
        await callback_query.message.edit_text(
            "❌ Something went wrong. Please try again.",
            reply_markup=category_keyboard()
        )

@app.on_callback_query(filters.regex(r"^next_(.+)_(.+)$"))
async def next_video(client, callback_query):
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id # Get chat_id
    logger.info(f"User {user_id} requested next video.")
    try:
        _, current_uuid, category = callback_query.data.split('_')
        
        if await is_rate_limited(user_id):
            await callback_query.answer("⚠️ You're browsing too quickly. Please wait a minute and try again.", show_alert=True)
            logger.warning(f"User {user_id} hit rate limit in next_video.")
            return

        # Ensure category exists and sanitize input
        sanitized_category = html.escape(category)
        if sanitized_category not in get_categories():
            sanitized_category = config.DEFAULT_CATEGORY
            logger.warning(f"User {user_id} used invalid category '{category}' for next video, falling back to default.")

        video = get_random_video(sanitized_category)
        
        if not video:
            logger.warning(f"No next video found in category '{sanitized_category}' for user {user_id}.")
            await callback_query.answer("No videos in this category. Try another!", show_alert=True)
            return
        
        # Check for active menu before attempting to delete/edit
        if not await is_menu_active(client, user_id, chat_id):
            logger.warning(f"User {user_id} tried to navigate next but menu expired or not active.")
            await callback_query.message.reply("Menu expired. Please click Get Video to restart.")
            return
        
        try:
            sent_success, sent_message_or_error = await send_video_with_auto_delete(
                client,
                chat_id, # Use chat_id
                video,
                reply_markup=video_nav_keyboard(video['uuid'], sanitized_category)
            )
            
            if sent_success:
                save_history(user_id, video['uuid'], sanitized_category)
                set_active_menu(user_id, sent_message_or_error.id)
                await callback_query.message.delete()
                logger.info(f"User {user_id} navigated to next video {video['uuid']} in category {sanitized_category}.")
            else:
                logger.error(f"User {user_id} failed to send next video: {sent_message_or_error}")
                await callback_query.answer(sent_message_or_error, show_alert=True)
        except MessageIdInvalid:
            logger.warning(f"User {user_id} encountered MessageIdInvalid while sending next video, sending as new message.")
            # If edit fails, send as new message
            sent_success, sent_message_or_error = await send_video_with_auto_delete(
                client,
                chat_id, # Use chat_id
                video,
                reply_markup=video_nav_keyboard(video['uuid'], sanitized_category)
            )
            if sent_success:
                save_history(user_id, video['uuid'], sanitized_category)
                set_active_menu(user_id, sent_message_or_error.id)
                logger.info(f"User {user_id} sent next video {video['uuid']} as new message.")
            else:
                logger.error(f"User {user_id} failed to send next video as new message: {sent_message_or_error}")
                await callback_query.answer(sent_message_or_error, show_alert=True)
    except Exception as e:
        logger.error(f"User {user_id} error in next_video: {e}", exc_info=True)
        await callback_query.answer("Something went wrong. Please try again.", show_alert=True)

@app.on_callback_query(filters.regex(r"^prev_(.+)_(.+)$"))
async def prev_video(client, callback_query):
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id # Get chat_id
    logger.info(f"User {user_id} requested previous video.")
    try:
        _, current_uuid, category_hint = callback_query.data.split('_') # Use category_hint as it might not be the actual category of the prev video
        
        if await is_rate_limited(user_id):
            await callback_query.answer("⚠️ You're browsing too quickly. Please wait a minute and try again.", show_alert=True)
            logger.warning(f"User {user_id} hit rate limit in prev_video.")
            return

        history_doc = history_collection.find_one({'user_id': user_id})
        
        if not history_doc or not history_doc.get('history'):
            logger.warning(f"User {user_id} has no previous video history.")
            await callback_query.answer(
                "No previous videos available in your history. Try 'Get Video' to start!",
                show_alert=True
            )
            return
            
        history_entries = history_doc['history']
        
        found_video = None
        found_category = None
        
        # Efficient history lookup by getting the last two entries if available
        # The current_uuid is the last one, so we want the one before it.
        if len(history_entries) > 1:
            # Check the second to last entry
            prev_entry = history_entries[-2]
            # Ensure it's not the same as the current video (in case of double clicks or rapid navigation)
            if prev_entry['video_uuid'] != current_uuid:
                video = media_collection.find_one({'uuid': prev_entry['video_uuid']})
                if video:
                    found_video = video
                    found_category = prev_entry['category'] # Use the category from history for navigation
        
        if not found_video:
            logger.warning(f"User {user_id} could not find valid previous video in history after efficient lookup.")
            # Fallback to full reverse iteration if efficient lookup fails
            for entry in reversed(history_entries):
                if entry['video_uuid'] == current_uuid:
                    continue # Skip the current video
                
                video = media_collection.find_one({'uuid': entry['video_uuid']})
                if video:
                    found_video = video
                    found_category = entry['category'] # Use the category from history for navigation
                    break # Found a valid previous video
        
        if not found_video:
            logger.warning(f"User {user_id} could not find any valid previous video in history after full scan.")
            await callback_query.answer(
                "Could not find any valid previous videos in your history. Some videos might have been deleted.",
                show_alert=True
            )
            return
            
        # Check for active menu before attempting to delete/edit
        if not await is_menu_active(client, user_id, chat_id):
            logger.warning(f"User {user_id} tried to navigate previous but menu expired or not active.")
            await callback_query.message.reply("Menu expired. Please click Get Video to restart.")
            return
            
        # Delete old menu before sending new one
        try:
            await callback_query.message.delete()
            logger.info(f"User {user_id} deleted old menu message for previous video navigation.")
        except Exception as e:
            logger.error(f"User {user_id} failed to delete old menu message for prev_video: {e}")
        
        sent_success, sent_message_or_error = await send_video_with_auto_delete(
            client,
            chat_id, # Use chat_id
            found_video,
            reply_markup=video_nav_keyboard(found_video['uuid'], found_category)
        )
        
        if sent_success:
            save_history(user_id, found_video['uuid'], found_category)
            set_active_menu(user_id, sent_message_or_error.id)
            logger.info(f"User {user_id} navigated to previous video {found_video['uuid']} in category {found_category}.")
        else:
            logger.error(f"User {user_id} failed to send previous video: {sent_message_or_error}")
            await callback_query.answer(
                sent_message_or_error,
                show_alert=True
            )
    except Exception as e:
        logger.error(f"User {user_id} error in prev_video: {e}", exc_info=True)
        await callback_query.answer(
            "An unexpected error occurred while trying to go to the previous video. Please try again.",
            show_alert=True
        )

@app.on_callback_query(filters.regex(r"^change_cat$"))
async def change_category(client, callback_query):
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id # Get chat_id
    logger.info(f"User {user_id} requested to change category.")
    try:
        await callback_query.message.edit_text("🎬 <b>Choose a Category:</b>", reply_markup=category_keyboard())
        logger.info(f"User {user_id}: Change category menu sent.")
    except Exception as e:
        logger.error(f"User {user_id} failed to send change category menu: {e}", exc_info=True)
        await callback_query.answer("❌ Something went wrong. Please try again.", show_alert=True)

@app.on_message(filters.regex("^Profile$") & filters.private)
async def profile_btn(client, message: Message):
    user_id = message.from_user.id # Added user_id for logging
    logger.info(f"User {user_id} clicked Profile button.")
    try:
        await profile_cmd(client, message)
        logger.info(f"User {user_id}: Profile command triggered from button.")
    except Exception as e:
        logger.error(f"User {user_id} failed to trigger profile command from button: {e}", exc_info=True)
        await handle_error(client, message, e)

@app.on_message(filters.regex("^Refer & Earn$") & filters.private)
async def refer_btn(client, message: Message):
    user_id = message.from_user.id
    logger.info(f"User {user_id} clicked Refer & Earn button.")
    
    try:
        if await is_rate_limited(user_id):
            await handle_error(client, message, FloodWait(10))
            logger.warning(f"User {user_id} hit rate limit in refer_btn.")
            return

        ref_link = f"https://t.me/{config.BOT_USERNAME[1:]}?start=ref_{user_id}"
        await message.reply(f"🔗 <b>Share & Earn!</b>\nShare this link to earn tokens:\n<code>{html.escape(ref_link)}</code>", reply_markup=referral_keyboard(ref_link))
        logger.info(f"User {user_id}: Referral link sent successfully.")
    except Exception as e:
        logger.error(f"User {user_id} failed to send referral link: {e}", exc_info=True)
        await handle_error(client, message, e)

@app.on_message(filters.regex("^Buy Token$") & filters.private)
async def buy_token_btn(client, message: Message):
    user_id = message.from_user.id # Added user_id for logging
    logger.info(f"User {user_id} clicked Buy Token button.")
    try:
        await message.reply("Buy tokens from our support bot.", reply_markup=buy_token_keyboard())
        logger.info(f"User {user_id}: Buy token message sent successfully.")
    except Exception as e:
        logger.error(f"User {user_id} failed to send buy token message: {e}", exc_info=True)
        await handle_error(client, message, e)

@app.on_message(filters.regex("^Refresh Token$") & filters.private)
async def refresh_token_btn(client, message: Message):
    user_id = message.from_user.id
    logger.info(f"User {user_id} requested token refresh. Handler entered.")

    try:
        if await is_rate_limited(user_id):
            await message.reply_text("⚠️ You're refreshing too quickly. Please wait a minute and try again.")
            logger.warning(f"User {user_id} hit rate limit in refresh_token_btn.")
            return

        temp_msg = await message.reply("Please wait...")
        logger.info(f"User {user_id}: 'Please wait...' message sent. Checking for existing token.")

        if user_has_token(user_id):
            await temp_msg.delete()
            await message.reply("💡 You already have an active token. No need to refresh yet!")
            logger.info(f"User {user_id} attempted token refresh but already has valid tokens. Exiting.")
            return

        logger.info(f"User {user_id}: User does not have valid token. Generating ad_code and attempting to shorten URL.")
        ad_code = str_to_b64(f"{user_id}:{get_current_time() + config.TOKEN_EXPIRY}")
        long_url = f"https://telegram.dog/{client.username}?start=token_{ad_code}"
        ad_url = await shorten_url(long_url)
        logger.info(f"User {user_id}: shorten_url call completed. Result: {ad_url}")
        
        await temp_msg.delete()

        disable_preview = False
        if ad_url.startswith(f"https://telegram.dog/{client.username}"):
            logger.warning(f"User {user_id} URL shortening failed for refresh_token_btn. Using long URL: {ad_url}")
            disable_preview = True # Disable preview for long Telegram links

        # Sanitize user mention
        user_mention_safe = html.escape(message.from_user.first_name) if message.from_user.first_name else "there"
        await message.reply_text(
            f"💡 <b>Information</b>\nHere are the details you requested...\n\n"
            f"Hey 💕 <b>{user_mention_safe}</b>\n\nYour Ads token is expired, refresh your token and try again.\n\n<b>Token Timeout:</b> 24 hour\n\n<b>What is token?</b>\nThis is an ads token. If you pass 1 ad, you can use the bot for 24 hour after passing the ad.\n\nAPPLE/IPHONE USERS COPY TOKEN LINK AND OPEN IN CHROME BROWSER</b>",
            disable_web_page_preview = disable_preview,
            reply_markup=token_earning_keyboard(ad_url)
        )
        logger.info(f"User {user_id}: Refresh token message sent. Handler finished.")
    except Exception as e:
        logger.error(f"User {user_id} failed in refresh_token_btn: {e}", exc_info=True)
        # Ensure temp_msg is deleted even on error
        try:
            await temp_msg.delete()
            logger.info(f"User {user_id}: Deleted 'Please wait...' message due to error.")
        except Exception as delete_e:
            logger.warning(f"User {user_id}: Failed to delete 'Please wait...' message during error handling: {delete_e}")
        await handle_error(client, message, e)

async def send_token_earning_options(client: Client, message: Message):
    user_id = message.from_user.id
    logger.info(f"User {user_id} is being sent token earning options.")
    try:
        if await is_rate_limited(user_id):
            await message.reply_text("⚠️ You're requesting token options too quickly. Please wait a minute and try again.")
            logger.warning(f"User {user_id} hit rate limit in send_token_earning_options.")
            return

        # No need to generate a new ad_code if user already has tokens, just provide options
        # This function is typically called when user_has_token is False
        ad_code = str_to_b64(f"{user_id}:{get_current_time() + config.TOKEN_EXPIRY}")
        long_url = f"https://telegram.dog/{config.BOT_USERNAME[1:]}?start=token_{ad_code}"
        ad_url = await shorten_url(long_url)
        
        disable_preview = False
        if ad_url.startswith(f"https://telegram.dog/{client.username}"):
            logger.warning(f"User {user_id} URL shortening failed for send_token_earning_options. Using long URL: {ad_url}")
            disable_preview = True

        await message.reply(
            "❌ <b>No Tokens Left!</b>\nUse any of these methods to gain tokens:",
            reply_markup=token_earning_keyboard(ad_url),
            disable_web_page_preview=disable_preview
        )
        logger.info(f"User {user_id}: Token earning options sent.")
    except Exception as e:
        logger.error(f"User {user_id} failed to send token earning options: {e}", exc_info=True)
        await handle_error(client, message, e)

@app.on_callback_query(filters.regex("^check_sub$"))
async def check_sub_callback(client, callback_query):
    user_id = callback_query.from_user.id
    logger.info(f"User {user_id} clicked Check Subscription button (callback). ")
    try:
        if await is_rate_limited(user_id):
            await callback_query.answer("⚠️ You're checking too quickly. Please wait a minute and try again.", show_alert=True)
            logger.warning(f"User {user_id} hit rate limit in check_sub_callback.")
            return

        is_member = await check_subscription_cached(client, user_id)  # Use cached version
        
        # Invalidate cache after explicit check
        if f"{user_id}" in subscription_cache:
            del subscription_cache[f"{user_id}"]

        current_text = callback_query.message.text

        if is_member:
            expected_text = "🎉 <b>Success!</b> You are subscribed! You can now watch videos."
            if current_text != expected_text:
                await callback_query.message.edit_text(
                    expected_text,
                    reply_markup=await get_main_keyboard(user_id)
                )
                logger.info(f"User {user_id} confirmed subscription (callback). ")
            else:
                await callback_query.answer("You are already subscribed!", show_alert=False)
                logger.info(f"User {user_id} clicked Check Subscription but already subscribed (no change needed). ")
        else:
            expected_text = "❌ You are not subscribed yet. Please join our channel:"
            if current_text != expected_text:
                await callback_query.message.edit_text(
                    expected_text,
                    reply_markup=join_channel_keyboard()
                )
                logger.info(f"User {user_id} is not subscribed (callback). ")
            else:
                await callback_query.answer("You are still not subscribed. Please join the channel.", show_alert=False)
                logger.info(f"User {user_id} clicked Check Subscription but still not subscribed (no change needed). ")
    except Exception as e:
        logger.error(f"User {user_id} failed to check subscription (callback): {e}", exc_info=True)
        await callback_query.answer("❌ Something went wrong. Please try again.", show_alert=True)

@app.on_callback_query(filters.regex(r"^share_(.+)$"))
async def share_callback(client, callback_query):
    user_id = callback_query.from_user.id
    video_uuid = callback_query.data.split('_', 1)[1]
    
    try:
        # Validate UUID format
        try:
            uuid.UUID(video_uuid)
        except ValueError:
            logger.warning(f"User {user_id} attempted to share with invalid UUID format: {video_uuid}.")
            await callback_query.answer("❌ Invalid video ID.", show_alert=True)
            return

        share_link = f"https://t.me/{config.BOT_USERNAME[1:]}?start={video_uuid}"
        await callback_query.answer()
        logger.info(f"User {user_id} requested share link for video {video_uuid}.")
        await callback_query.message.reply(
            f"🔗 <b>Share & Earn!</b>\nShare this video with your friends!\n<code>{html.escape(share_link)}</code>",
            quote=True
        )
        logger.info(f"User {user_id}: Share link for video {video_uuid} sent successfully.")
    except Exception as e:
        logger.error(f"User {user_id} failed to send share link for video {video_uuid}: {e}", exc_info=True)
        await callback_query.answer("❌ Something went wrong. Please try again.", show_alert=True)

# --- Admin Commands ---
@app.on_message(filters.command("broadcast") & filters.private & filters.user(config.ADMIN_IDS) & filters.reply)
async def broadcast_cmd(client, message: Message):
    user_id = message.from_user.id # Added user_id for logging
    replied_message = message.reply_to_message
    logger.info(f"Admin {user_id} initiated broadcast.")
    try:
        users = list(users_collection.find({}, {'user_id': 1}))
        total_users = len(users)
        broadcast_msg = await message.reply(f"📣 <b>Broadcasting</b> to <b>{total_users}</b> users...")
        logger.info(f"Admin {user_id} initiating broadcast to {total_users} users.")
        
        success = 0
        blocked = 0
        failed = 0
        
        for user in users:
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
                await asyncio.sleep(e.value + 1)  # Wait a bit longer than required
                try: # Nested try for retry
                    await replied_message.copy(user['user_id']) # Retry after waiting
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
                    f"Broadcasting...\n\n"
                    f"Progress: {success + blocked + failed}/{total_users}\n"
                    f"Successful: {success}\n"
                    f"Blocked Users: {blocked}\n"
                    f"Unsuccessful: {failed}"
                )
            await asyncio.sleep(0.5) # Increased delay to 0.5 seconds
        
        await broadcast_msg.edit_text(
            f"Broadcast Completed\n\n"
            f"Total Users: {total_users}\n"
            f"Successful: {success}\n"
            f"Blocked Users: {blocked}\n"
            f"Unsuccessful: {failed}"
        )
        logger.info(f"Broadcast completed by admin {user_id}. Success: {success}, Blocked: {blocked}, Failed: {failed}.")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to complete broadcast: {e}", exc_info=True)
        await message.reply("❌ An error occurred during broadcast. Check logs for details.")

@app.on_message(filters.command("addcategory") & filters.private & filters.user(config.ADMIN_IDS))
async def addcategory_cmd(client, message: Message):
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} requested to add category.")
    try:
        args = message.text.split()
        if len(args) < 2:
            logger.warning(f"Admin {user_id} used addcategory with insufficient arguments.")
            await message.reply(
                "Usage: /addcategory <category_name>\n"
                "Category name can only contain letters, numbers, underscores, and hyphens."
            )
            return
        
        name = args[1]
        # Input sanitization and validation for category name is done in validate_category_name
        success, msg = add_category(name)
        if success:
            logger.info(f"Admin {user_id} successfully added category '{name}'.")
        else:
            logger.warning(f"Admin {user_id} failed to add category '{name}': {msg}")
        await message.reply(msg)
    except Exception as e:
        logger.error(f"Admin {user_id} failed to add category: {e}", exc_info=True)
        await message.reply("❌ An error occurred while adding category. Please try again.")

@app.on_message(filters.command("deletecategory") & filters.private & filters.user(config.ADMIN_IDS))
async def deletecategory_cmd(client, message: Message):
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} requested to delete category.")
    try:
        if not is_admin(message.from_user.id):
            logger.warning(f"Non-admin user {user_id} attempted to use deletecategory command.")
            await message.reply_text("❌ Only admins can use this command.")
            return

        categories = get_categories()
        if not categories:
            logger.warning(f"Admin {user_id} tried to delete category but no categories exist.")
            await message.reply_text("No categories to delete.")
            return

        buttons = []
        for category in categories:
            sanitized_category = html.escape(category)
            buttons.append([InlineKeyboardButton(sanitized_category, callback_data=f"confirmdelcat_{category}")])

        await message.reply_text(
            """Select a category to delete:

⚠️ All videos in the selected category will be deleted permanently. This action cannot be undone. Click on a category name below to confirm deletion.""",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        logger.info(f"Admin {user_id}: Delete category options sent.")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to send delete category options: {e}", exc_info=True)
        await message.reply("❌ An error occurred while preparing delete category options. Please try again.")

@app.on_callback_query(filters.regex(r"^confirmdelcat_(.+)$"))
async def confirm_delcat_callback(client, callback_query):
    user_id = callback_query.from_user.id
    category_raw = callback_query.data[14:] # Extract raw category name
    logger.info(f"Admin {user_id} confirmed deletion of category: {category_raw}.")
    try:
        if not is_admin(user_id):
            await callback_query.answer("❌ Not authorized.", show_alert=True)
            logger.warning(f"Non-admin user {user_id} attempted to confirm category deletion.")
            return
        
        # Sanitize category name before processing
        category = html.escape(category_raw)

        # Log the admin action before execution
        logger.warning(f"Admin {user_id} is confirming deletion of category: {category}")

        success, msg, deleted_count = delete_category(category)
        
        if success:
            formatted_msg = f"✅ Category '{html.escape(category)}' deleted, and {deleted_count} videos removed permanently. Use /addcategory to create new categories."
            await callback_query.message.edit_text(formatted_msg)
            logger.info(f"Admin {user_id} successfully deleted category {category} with {deleted_count} videos.")
        else:
            await callback_query.answer(msg, show_alert=True)
            logger.error(f"Admin {user_id} failed to delete category {category}: {msg}")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to confirm category deletion: {e}", exc_info=True)
        await callback_query.answer("❌ An error occurred during category deletion. Please try again.", show_alert=True)

@app.on_message(filters.command("addtoken") & filters.private & filters.user(config.ADMIN_IDS))
async def addtoken_cmd(client, message: Message):
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} requested to add token.")
    try:
        args = message.text.split()
        if len(args) < 3:
            logger.warning(f"Admin {user_id} used addtoken with insufficient arguments: {message.text}")
            await message.reply("Usage: /addtoken <user_id> <count>")
            return
            
        target_user_id = int(args[1]) # Renamed to avoid conflict with admin user_id
        count = int(args[2])
            
        if target_user_id <= 0:
            logger.warning(f"Admin {user_id} provided invalid target user ID: {target_user_id}.")
            await message.reply("User ID must be a positive integer.")
            return
                
        if count <= 0:
            logger.warning(f"Admin {user_id} provided invalid token count: {count}.")
            await message.reply("Token count must be a positive integer.")
            return
                
        if count > 10:  # Reasonable limit
            logger.warning(f"Admin {user_id} attempted to add more than 10 tokens ({count}).")
            await message.reply("Cannot add more than 10 tokens at once.")
            return
                
        # Check if user exists
        user = users_collection.find_one({'user_id': target_user_id})
        if not user:
            logger.warning(f"Admin {user_id} attempted to add tokens to non-existent user {target_user_id}.")
            await message.reply("User not found in database.")
            return
                
        for _ in range(count):
            added = add_token(target_user_id)
            if not added: # Check if add_token failed
                logger.error(f"Admin {user_id} failed to add one of {count} tokens to user {target_user_id}.")
                await message.reply("❌ Failed to add some tokens. Check logs for details.")
                return # Exit if any token addition fails
                
        logger.info(f"Admin {user_id} added {count} tokens to user {target_user_id}.")
        await message.reply(f"Added {count} tokens to user {target_user_id}.")
    except ValueError:
        logger.warning(f"Admin {user_id} provided invalid input for addtoken: {message.text}")
        await message.reply("User ID and count must be valid integers.")
    except Exception as e:
        logger.error(f"Admin {user_id} error adding tokens: {e}", exc_info=True)
        await message.reply("❌ Failed to add tokens. Please try again.")

# --- Batch Add Videos ---
batch_add_state = {}

def format_size(size_bytes):
    """Convert bytes to human readable format"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} TB"

@app.on_message(filters.command("batchadd") & filters.private & filters.user(config.ADMIN_IDS))
async def batchadd_cmd(client, message: Message):
    user_id = message.from_user.id
    try:
        await message.reply("DEBUG: Entered /batchadd handler")
        if user_id not in config.ADMIN_IDS:
            await message.reply("DEBUG: Not an admin")
            return
        try:
            db.command("ping")
            await message.reply("DEBUG: MongoDB connection OK")
        except Exception as db_exc:
            await message.reply(f"DEBUG: MongoDB connection failed: {db_exc}")
            return
        if not get_categories():
            await message.reply("DEBUG: No categories found, adding default")
            add_category(config.DEFAULT_CATEGORY)
        else:
            await message.reply(f"DEBUG: Categories found: {get_categories()}")
        batch_add_state[user_id] = {
            'batch_mode': True,
            'current_category': config.DEFAULT_CATEGORY
        }
        await message.reply("DEBUG: batch_add_state set")
        await message.reply(
            "Send me videos to add. Type /done when finished.\n"
            "Current category: " + config.DEFAULT_CATEGORY
        )
    except Exception as e:
        tb = traceback.format_exc()
        await message.reply(f"❌ Exception in /batchadd:\n<code>{tb}</code>")

@app.on_message(filters.command("done") & filters.private & filters.user(config.ADMIN_IDS))
async def done_cmd(client, message: Message):
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} exited batch add mode.")
    try:
        if user_id not in config.ADMIN_IDS:
            logger.warning(f"Non-admin user {user_id} attempted to use done command.")
            return
        
        if batch_add_state.get(user_id, {}).get('batch_mode'):
            batch_add_state[user_id]['batch_mode'] = False
            # Clear specific user's state to prevent memory leak
            if user_id in batch_add_state:
                del batch_add_state[user_id]
            await message.reply("Batch add mode disabled.")
            logger.info(f"Admin {user_id}: Batch add mode disabled.")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to disable batch add mode: {e}", exc_info=True)
        await message.reply("❌ An error occurred while ending batch add mode. Please try again.")

@app.on_message(filters.video & filters.private & filters.user(config.ADMIN_IDS))
async def handle_video(client, message: Message):
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} sent a video for batch adding.")

    try:
        if user_id not in batch_add_state or not batch_add_state[user_id].get('batch_mode'):
            logger.warning(f"Admin {user_id} sent video outside of batch add mode, ignoring.")
            return

        category = batch_add_state[user_id].get('current_category', config.DEFAULT_CATEGORY)
        if not category:
            logger.warning(f"Admin {user_id} tried to add video but no category set.")
            await message.reply_text("⚠️ Please set a category first using /category.")
            return

        # Validate category name from batch_add_state
        is_valid_category, validation_msg = validate_category_name(category)
        if not is_valid_category:
            await message.reply_text(f"❌ Invalid category selected: {validation_msg}. Please select a valid category using /category.")
            logger.error(f"Admin {user_id} attempted to add video to invalid category '{category}': {validation_msg}")
            return

        if not message.video:
            logger.warning(f"Admin {user_id} sent non-video file in batch add mode.")
            await message.reply_text("❌ Please send a video file.")
            return

        file_id = message.video.file_id
        file_unique_id = message.video.file_unique_id
        file_size = message.video.file_size

        # Check for duplicate video using file_unique_id
        if media_collection.find_one({"file_unique_id": file_unique_id}):
            logger.warning(f"Admin {user_id} attempted to add duplicate video: {file_unique_id}.")
            await message.reply_text("⚠️ This video has already been added.")
            return

        # Forward video to the video channel
        video_uuid = str(uuid.uuid4())
        # Robust settings retrieval, including auto_delete
        settings = settings_collection.find_one({'_id': 'settings'}) or {'protect_content': True, 'auto_delete': True}
        protect_content = settings.get('protect_content', True)

        forwarded_message = await client.send_video(
            chat_id=config.VIDEO_CHANNEL_ID,
            video=file_id,
            caption=f"Category: {category}\nSize: {format_size(file_size)}\nUUID: {video_uuid}", # Use actual video_uuid
            protect_content=protect_content # Get protect_content from settings
        )
        message_id_in_channel = forwarded_message.id

        video_data = {
            "uuid": video_uuid, # Use the generated uuid
            "file_id": file_id,
            "file_unique_id": file_unique_id,
            "category": category,
            "size_bytes": file_size,
            "timestamp": get_current_time(),
            "message_id": message_id_in_channel, # Store the message_id in the channel
            "banned": False # Initialize banned status for new videos
        }
        media_collection.insert_one(video_data)
        logger.info(f"Video {video_uuid} (file ID: {file_id}) added to category {category} by admin {user_id}.")
        await message.reply_text(
            f"✅ File {html.escape(message.video.file_name)} Added to {html.escape(category)}\n"
            f"📁 Category: {html.escape(category)}\n"
            f"📊 Size: {format_size(file_size)}\n"
            f"🆔 File ID: {file_id}"
        )
    except Exception as e:
        logger.error(f"Admin {user_id} error adding video: {e}", exc_info=True)
        await message.reply("❌ Failed to add video. Please try again.")

@app.on_message(filters.command("category") & filters.private & filters.user(config.ADMIN_IDS))
async def set_category_cmd(client, message: Message):
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} requested to set category.")
    try:
        if not is_admin(user_id):
            logger.warning(f"Non-admin user {user_id} attempted to use set_category_cmd.")
            await message.reply_text("❌ Only admins can use this command.")
            return

        # Check if batch_mode is active
        if user_id not in batch_add_state or not batch_add_state[user_id].get('batch_mode', False):
            logger.warning(f"Admin {user_id} tried to set category outside of batch add mode.")
            await message.reply_text("❌ Error: Start batch mode with /batchadd first.")
            return

        categories = get_categories()
        if not categories:
            logger.warning(f"Admin {user_id} tried to set category but no categories available.")
            await message.reply_text("⚠️ No categories available to set. Use /addcategory to create one.")
            return

        buttons = []
        for category in categories:
            buttons.append([InlineKeyboardButton(category, callback_data=f"setcat_{category}")])

        await message.reply_text(
            "Select a category for batch adding videos:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        logger.info(f"Admin {user_id}: Set category options sent.")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to send set category options: {e}", exc_info=True)
        await message.reply("❌ An error occurred while preparing set category options. Please try again.")

@app.on_callback_query(filters.regex(r"^setcat_(.+)$"))
async def setcat_callback(client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    logger.info(f"Admin {user_id} selected category for batch adding: {callback_query.data[7:]}.")
    try:
        # Extract category name, handling potential spaces or special characters safely
        # The regex in the filter ensures it matches the format, this just extracts the group
        match = re.match(r"^setcat_(.+)$", callback_query.data)
        if not match:
            await callback_query.answer("❌ Invalid category data.", show_alert=True)
            logger.warning(f"Admin {user_id} received invalid category data in setcat_callback: {callback_query.data}.")
            return
        category_name = match.group(1)

        if not is_admin(user_id):
            await callback_query.answer("❌ Only admins can use this command.", show_alert=True)
            logger.warning(f"Non-admin user {user_id} attempted to set batch category.")
            return

        if user_id not in batch_add_state or not batch_add_state[user_id].get('batch_mode', False):
            await callback_query.answer("❌ Error: Batch mode not active.", show_alert=True)
            logger.warning(f"Admin {user_id} tried to set category but batch mode not active.")
            return

        if category_name not in get_categories():
            await callback_query.answer("❌ Invalid category.", show_alert=True)
            logger.warning(f"Admin {user_id} tried to set invalid category: '{category_name}'.")
            return

        batch_add_state[user_id]['current_category'] = category_name
        await callback_query.message.edit_text(f"✅ Category set to '{html.escape(category_name)}' for batch adding. Send videos now or use /done to finish.")
        logger.info(f"Admin {user_id} successfully set batch category to '{category_name}'.")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to set batch category: {e}", exc_info=True)
        await callback_query.answer("❌ An error occurred while setting category. Please try again.", show_alert=True)

@app.on_message(filters.command("stats") & filters.private & filters.user(config.ADMIN_IDS))
async def stats_cmd(client, message: Message):
    user_id = message.from_user.id # Added user_id for logging
    logger.info(f"Admin {user_id} requested stats.")
    try:
        total_users = users_collection.count_documents({})
        total_videos = media_collection.count_documents({})
        total_categories = categories_collection.count_documents({})
        await message.reply(f"Total Users: {total_users}\nTotal Videos: {total_videos}\nTotal Categories: {total_categories}")
        logger.info(f"Admin {user_id} retrieved stats: Users={total_users}, Videos={total_videos}, Categories={total_categories}.")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to retrieve stats: {e}", exc_info=True)
        await message.reply("❌ An error occurred while fetching stats. Please try again.")

@app.on_message(filters.command("checkchannel") & filters.private & filters.user(config.ADMIN_IDS))
async def check_channel_cmd(client, message: Message):
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} requested channel check for ID: {config.CHANNEL_ID}")
    try:
        channel = await client.get_chat(int(config.CHANNEL_ID))
        bot_member = await client.get_chat_member(int(config.CHANNEL_ID), client.me.id)

        status_text = (
            f"✅ Channel accessible!\n"
            f"Title: {channel.title}\n"
            f"ID: {channel.id}\n"
            f"Bot Status: {bot_member.status}"
        )
        await message.reply(status_text)
        logger.info(f"Admin {user_id} channel check successful for {config.CHANNEL_ID}. Bot status: {bot_member.status}.")
    except pyrogram.errors.exceptions.bad_request_400.ChannelInvalid as e:
        error_message = f"❌ ChannelInvalid error checking channel {config.CHANNEL_ID}: {e}. Ensure bot is admin and CHANNEL_ID is correct."
        logger.error(f"Admin {user_id} channel check failed: {error_message}", exc_info=True)
        await message.reply(error_message)
    except Exception as e:
        error_message = f"❌ Error checking channel {config.CHANNEL_ID}: {e}"
        logger.error(f"Admin {user_id} channel check failed: {error_message}", exc_info=True)
        await message.reply(error_message)

# --- Auto-Delete & Protect Content ---
@app.on_message(filters.command('toggle_auto_delete') & filters.private & filters.user(config.ADMIN_IDS))
async def toggle_auto_delete(client, message):
    user_id = message.from_user.id # Added user_id for logging
    logger.info(f"Admin {user_id} requested to toggle auto-delete.")
    try:
        s = settings_collection.find_one({'_id': 'settings'}) or {'auto_delete': True}
        new_status = not s.get('auto_delete', True)
        settings_collection.update_one({'_id': 'settings'}, {'$set': {'auto_delete': new_status}}, upsert=True)
        await message.reply(f"Auto-delete feature is now {'enabled' if new_status else 'disabled'}.")
        logger.info(f"Admin {user_id} toggled auto-delete to {'enabled' if new_status else 'disabled'}.")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to toggle auto-delete: {e}", exc_info=True)
        await message.reply("❌ An error occurred while toggling auto-delete. Please try again.")

@app.on_message(filters.command('toggle_protect') & filters.private & filters.user(config.ADMIN_IDS))
async def toggle_protect(client, message):
    user_id = message.from_user.id # Added user_id for logging
    logger.info(f"Admin {user_id} requested to toggle content protection.")
    try:
        s = settings_collection.find_one({'_id': 'settings'}) or {'protect_content': True}
        new_status = not s.get('protect_content', True)
        settings_collection.update_one({'_id': 'settings'}, {'$set': {'protect_content': new_status}}, upsert=True)
        await message.reply(f"Content protection is now {'enabled' if new_status else 'disabled'}.")
        logger.info(f"Admin {user_id} toggled content protection to {'enabled' if new_status else 'disabled'}.")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to toggle content protection: {e}", exc_info=True)
        await message.reply("❌ An error occurred while toggling content protection. Please try again.")

@app.on_message(filters.regex("^Join Channel$") & filters.private)
async def join_channel_btn(client, message: Message):
    user_id = message.from_user.id # Added user_id for logging
    logger.info(f"User {user_id} clicked Join Channel button.")
    try:
        await message.reply("📢 <b>Join our channel to watch videos!</b>", reply_markup=join_channel_keyboard())
        logger.info(f"User {user_id}: Join channel message sent.")
    except Exception as e:
        logger.error(f"User {user_id} failed to send join channel message: {e}", exc_info=True)
        await handle_error(client, message, e)

@app.on_message(filters.regex("^Check Subscription$") & filters.private)
async def check_sub_btn(client, message: Message):
    user_id = message.from_user.id
    logger.info(f"User {user_id} clicked Check Subscription button (from main keyboard). ")
    
    try:
        is_member = await check_subscription_cached(client, user_id)
        current_text = message.text

        if is_member:
            expected_text = "🎉 <b>Success!</b> You are subscribed! You can now watch videos."
            if current_text != expected_text:
                await message.reply(
                    expected_text,
                    reply_markup=await get_main_keyboard(user_id)
                )
                logger.info(f"User {user_id} confirmed subscription (from main keyboard). ")
            else:
                await message.reply("You are already subscribed!", reply_markup=await get_main_keyboard(user_id))
                logger.info(f"User {user_id} clicked Check Subscription but already subscribed (no change needed from main keyboard). ")
        else:
            expected_text = "❌ You are not subscribed yet. Please join our channel:"
            if current_text != expected_text:
                await message.reply(
                    expected_text,
                    reply_markup=join_channel_keyboard()
                )
                logger.info(f"User {user_id} not subscribed (from main keyboard). ")
            else:
                await message.reply("You are still not subscribed. Please join the channel.", reply_markup=join_channel_keyboard())
                logger.info(f"User {user_id} clicked Check Subscription but still not subscribed (no change needed from main keyboard). ")
    except Exception as e:
        logger.error(f"User {user_id} failed to check subscription from button: {e}", exc_info=True)
        await handle_error(client, message, e)

# --- Database Cleanup ---
async def cleanup_expired_data():
    """Clean up expired tokens and old history entries."""
    while True:
        try:
            now = datetime.utcnow()
            
            # Clean up expired tokens
            tokens_collection.update_many(
                {},
                {'$pull': {'tokens': {'expires_at': {'$lt': now}}}}
            )
            
            # Clean up old history (older than 30 days)
            # This is handled by $slice in save_history, but this provides a fallback for older entries.
            month_ago = now - timedelta(days=30)
            history_collection.update_many(
                {},
                {'$pull': {'history': {'viewed_at': {'$lt': month_ago}}}}
            )
            
            # Remove empty history documents
            history_collection.delete_many({'history': {'$size': 0}})
            
            # Remove token documents with empty 'tokens' array
            tokens_collection.delete_many({'tokens': {'$size': 0}})
            
            # Clean up expired active_menus
            expired_users = [uid for uid, menu_data in active_menus.items() if get_current_time() - menu_data['timestamp'] > config.MENU_TIMEOUT]
            for user_id_to_clear in expired_users:
                # No need to call cleanup_expired_menu here as it's for message deletion
                # The goal here is to remove from active_menus dict
                del active_menus[user_id_to_clear]
                logger.info(f"Cleaned up expired active menu for user {user_id_to_clear} from memory.")

            logger.info("Database cleanup and active_menus cleanup completed")
        except Exception as e:
            logger.error(f"Error in database cleanup: {e}", exc_info=True)
        
        # Run every 24 hours
        await asyncio.sleep(86400)

# --- Main ---
async def verify_and_cleanup_media():
    """Periodically verifies if media files still exist in the channel and cleans up invalid entries."""
    while True:
        logger.info("Starting media verification and cleanup.")
        try:
            all_media = list(media_collection.find({}))
            for media_item in all_media:
                video_uuid = media_item.get('uuid')
                message_id_in_channel = media_item.get('message_id')
                
                if not message_id_in_channel:
                    logger.warning(f"Media item {video_uuid} has no message_id in channel. Deleting.")
                    media_collection.delete_one({'uuid': video_uuid})
                    continue

                try:
                    # Attempt to get the message from the channel
                    await app.get_messages(config.VIDEO_CHANNEL_ID, message_id_in_channel)
                except (MessageIdInvalid, ValueError):
                    logger.warning(f"Video {video_uuid} (message_id: {message_id_in_channel}) no longer exists in channel. Deleting from DB.")
                    media_collection.delete_one({'uuid': video_uuid})
                except Exception as e:
                    logger.error(f"Error verifying media {video_uuid}: {e}")

            logger.info("Media verification and cleanup completed.")
        except Exception as e:
            logger.error(f"Error in media verification cleanup task: {e}", exc_info=True)
        
        # Run every 6 hours
        await asyncio.sleep(6 * 3600)

if __name__ == '__main__':
    async def main():
        await app.start()
        logger.info("Bot started!")
        # Add a small delay to ensure client is fully initialized
        await asyncio.sleep(2) # Wait for 2 seconds
        # Start cleanup task
        app.loop.create_task(cleanup_expired_data())
        # Start media verification and cleanup task
        app.loop.create_task(verify_and_cleanup_media())
        await app.idle()  # This will block until the bot is stopped
        logger.info("Bot stopping...")
        await app.stop()

    app.loop.run_until_complete(main()) 
