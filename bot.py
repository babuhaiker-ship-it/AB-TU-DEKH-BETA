# Spicy Nyraa Bot - Main Script
import os
import sys
import time
import asyncio
import uuid
import base64
import random
import logging
from datetime import datetime, timedelta, UTC
from typing import List, Union, Dict, Optional, Any, Tuple
from pyrogram.client import Client
from pyrogram import filters
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, 
    KeyboardButton, Message, CallbackQuery, User
)
from pyrogram.errors import (
    UserIsBlocked, ChatInvalid, MessageIdInvalid, UserNotParticipant,
    FloodWait, MessageTooLong, MessageIdInvalid, MessageNotModified,
    PeerIdInvalid, RPCError
)
from pymongo import MongoClient, ASCENDING
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
import aiohttp
from aiohttp import ClientTimeout, ClientError, ClientConnectionError
import re
import html
from pyrogram.enums import ChatMemberStatus, ParseMode
import traceback
import json
from functools import wraps

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Configuration ---

class BotConfig:
    BOT_TOKEN = '7646433933:AAHWR5sSuyTrAendlSJwKV-WeM4rEIyDHaE'
    API_ID = 29800015
    API_HASH = 'c8f37108be31ab9ea2818bfe533fbb6f'
    MONGO_URI = 'mongodb+srv://Pyasipriya:00pEcao9sYhNC5VQ@cluster0.2dfenf7.mongodb.net/spicybot?retryWrites=true&w=majority&appName=Cluster0'
    MONGO_DB_NAME = 'spicybot'
    VIDEO_CHANNEL_ID = -2621716446
    BUY_BOT_URL = 'https://t.me/hanielxsupportbot'
    ADMIN_IDS = {6612030110}
    URL_SHORTENER = 'https://api.linkshortify.com/st'
    SHORTENER_API_KEY = '5cd923c490f64017cffa6e3bb6cc724560a8cfc6'
    BOT_USERNAME = '@SpicyNyraa_bot'
    TUTORIAL_LINK_2 = 'https://t.me/urlshortenertutorial'
    TOKEN_EXPIRY = 86400  # 24 hours in seconds
    DEFAULT_CATEGORY = 'default'
    NEW_USER_TOKENS = 3
    REFERRAL_BONUS = 1
    REFRESH_BONUS = 1
    MENU_TIMEOUT = 1800
    AUTO_DELETE_TIME = 1200  # 20 minutes
    AUTO_DEL_SUCCESS_MSG = "✅ Message auto-deleted successfully!"
    
    # MongoDB connection retry settings
    MONGO_MAX_RETRIES = 5
    MONGO_RETRY_DELAY = 5  # seconds
    MONGO_CONNECT_TIMEOUT = 30000  # 30 seconds
    MONGO_SOCKET_TIMEOUT = 60000   # 1 minute
    
    # API client settings
    API_MAX_RETRIES = 3
    API_RETRY_DELAY = 1  # seconds
    API_TIMEOUT = 30  # seconds for HTTP requests
    
    # Rate limiting settings - moved from global variables
    RATE_LIMIT_WINDOW = 60  # 1 minute
    RATE_LIMIT_MAX = 30    # requests per minute
    
    # Error handling settings
    MAX_ERROR_RETRY = 3
    ERROR_RETRY_DELAY = 5  # seconds
    
    # Operational mode
    LIMITED_MODE = False  # Set to True when MongoDB is unavailable

try:
    config = BotConfig()
    logger.info(f"DEBUG: Configured BOT_TOKEN: {config.BOT_TOKEN}") # Temporary debug line
    if not all([
        config.BOT_TOKEN, config.API_ID, config.API_HASH, config.MONGO_URI,
        config.SHORTENER_API_KEY
    ]):
        raise ValueError("One or more essential configuration variables are not set. Please check BOT_TOKEN, API_ID, API_HASH, MONGO_URI, SHORTENER_API_KEY in your environment variables.")
except Exception as e:
    raise RuntimeError(f"Failed to load bot configuration: {e}")

# --- MongoDB Setup with Retry Logic ---
def setup_mongodb():
    retries = 0
    while retries < config.MONGO_MAX_RETRIES:
        try:
            client = MongoClient(
                config.MONGO_URI,
                serverSelectionTimeoutMS=config.MONGO_CONNECT_TIMEOUT,
                socketTimeoutMS=config.MONGO_SOCKET_TIMEOUT
            )
            # Test the connection
            client.admin.command('ping')
            db = client[config.MONGO_DB_NAME]
            
            # Initialize collections
            collections = {
                'users': db['users'],
                'tokens': db['tokens'],
                'media': db['media'],
                'history': db['history'],
                'categories': db['categories'],
                'settings': db['settings']
            }
            
            # Create indexes
            collections['users'].create_index([("user_id", ASCENDING)], unique=True)
            collections['tokens'].create_index([("user_id", ASCENDING)], unique=True)
            collections['media'].create_index([("uuid", ASCENDING)], unique=True)
            collections['media'].create_index([("category", ASCENDING)])
            
            logger.info("Successfully connected to MongoDB")
            return client, db, collections
            
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            retries += 1
            if retries < config.MONGO_MAX_RETRIES:
                logger.warning(f"MongoDB connection attempt {retries} failed: {e}. Retrying in {config.MONGO_RETRY_DELAY} seconds...")
                time.sleep(config.MONGO_RETRY_DELAY)
            else:
                logger.error("Failed to connect to MongoDB after maximum retries", exc_info=True)
                raise
        except Exception as e:
            logger.error(f"Unexpected error while connecting to MongoDB: {e}", exc_info=True)
            raise

# Initialize MongoDB connection
try:
    mongo_client, db, collections = setup_mongodb()
    users_collection = collections['users']
    tokens_collection = collections['tokens']
    media_collection = collections['media']
    history_collection = collections['history']
    categories_collection = collections['categories']
    settings_collection = collections['settings']
except Exception as e:
    logger.critical("Failed to initialize MongoDB. Running in LIMITED MODE with reduced functionality.", exc_info=True)
    # Set limited mode flag
    config.LIMITED_MODE = True
    # Initialize empty collections to allow limited functionality
    users_collection = {}
    tokens_collection = {}
    media_collection = {}
    history_collection = {}
    categories_collection = {}
    settings_collection = {}
# Only create indexes if we're not in LIMITED_MODE
if not hasattr(config, 'LIMITED_MODE') or not config.LIMITED_MODE:
    try:
        media_collection.create_index([("file_unique_id", ASCENDING)], unique=True)
        media_collection.create_index([("size_bytes", ASCENDING)])
        history_collection.create_index([("history.viewed_at", ASCENDING)]) # Added index for history viewed_at
        history_collection.create_index([("user_id", ASCENDING)], unique=True)
        categories_collection.create_index([("name", ASCENDING)], unique=True)
        logger.info("MongoDB indexes created successfully")
    except Exception as e:
        logger.error(f"Failed to create MongoDB indexes: {e}", exc_info=True)

# --- Pyrogram Client ---
app = Client("spicynyraa", api_id=config.API_ID, api_hash=config.API_HASH, bot_token=config.BOT_TOKEN)

# --- Admin Check Utility ---
def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS

# --- Utility Functions ---
def str_to_b64(string: str) -> str:
    return base64.urlsafe_b64encode(string.encode()).decode()

def b64_to_str(b64: str) -> Union[str, None]:
    try:
        return base64.urlsafe_b64decode(b64.encode()).decode()
    except Exception as e:
        logger.error(f"Failed to decode base64 string: {e}")
        return None

def get_current_time() -> int:
    return int(datetime.now(UTC).timestamp())

async def shorten_url(long_url: str) -> str:
    logger.info(f"Attempting to shorten URL: {long_url}")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(config.URL_SHORTENER, json={
                'api': config.SHORTENER_API_KEY,
                'url': long_url
            }, timeout=ClientTimeout(total=10)) as resp:
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
    now = datetime.now(UTC)
    return [t for t in doc['tokens'] if t['expires_at'] > now]

def add_token(user_id: int, duration: Union[int, None] = None) -> Union[dict, None]:
    if duration is None:
        duration = config.TOKEN_EXPIRY
    now = datetime.now(UTC)
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
        return [{'token_id': 'admin', 'created_at': datetime.now(UTC), 'expires_at': datetime.now(UTC) + timedelta(days=365)}]
    now = datetime.now(UTC)
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
            'created_at': datetime.now(UTC)
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
    now = datetime.now(UTC)
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

async def cleanup_expired_menu(client: Client, user_id: int, chat_id: Union[int, None] = None):
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

async def is_menu_active(client: Client, user_id: int, chat_id: Union[int, None] = None) -> bool:
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

async def get_main_keyboard(user_id: Union[int, None] = None) -> ReplyKeyboardMarkup:
    """Async version of main_keyboard that uses cached subscription check"""
    buttons: List[List[Union[KeyboardButton, str]]] = [
        [KeyboardButton("Get Video"), KeyboardButton("Profile")],
        [KeyboardButton("Refer & Earn"), KeyboardButton("Buy Token")],
        [KeyboardButton("Refresh Token")]
    ]
    
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

# --- Video Sharing ---
async def handle_shared_video(client: Client, user_id: int, video_uuid: str) -> tuple[bool, Union[dict, str, InlineKeyboardMarkup]]:
    video = get_video_by_uuid(video_uuid)
    if not video:
        logger.warning(f"User {user_id} attempted to view non-existent shared video {video_uuid}.")
        return False, "Oops, invalid link. Try again!"
    
    if video.get('banned'): # Check for banned status
        logger.warning(f"User {user_id} attempted to view banned video {video_uuid}.")
        return False, "❌ This content is no longer available."
    
    if not user_has_token(user_id):
        # Pass user_id explicitly to send_token_earning_options
        # send_token_earning_options now returns InlineKeyboardMarkup or str
        result = await send_token_earning_options(client, user_id=user_id)
        if isinstance(result, InlineKeyboardMarkup):
            return False, result # Return the keyboard
        else:
            return False, result # Return the error string
        
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

async def send_video_with_auto_delete(client: Client, chat_id: int, video_data: dict, reply_markup: Union[InlineKeyboardMarkup, ReplyKeyboardMarkup, None] = None) -> tuple[bool, Union[Message, str, None]]:
    settings = settings_collection.find_one({'_id': 'settings'}) or {}
    protect_content = settings.get('protect_content', True)
    auto_delete = settings.get('auto_delete', True)
    
    try:
        sent = None
        if reply_markup: # Only pass reply_markup if it's not None
            sent = await client.send_video(
                chat_id,
                video_data['file_id'],
                caption=f"Category: {video_data['category']}",
                reply_markup=reply_markup,
                protect_content=protect_content
            )
        else:
            sent = await client.send_video(
                chat_id,
                video_data['file_id'],
                caption=f"Category: {video_data['category']}",
                protect_content=protect_content
            )
        
        if auto_delete and sent: # Check if sent message is not None before scheduling auto-delete
            asyncio.create_task(schedule_auto_delete(sent))
        
        return True, sent # Return success and the sent message object
    except Exception as e:
        logger.error(f"Failed to send video to chat {chat_id}: {e}")
        return False, "❌ <b>Failed to send video.</b>\nPlease try again later." # Return failure and an error message

# --- Rate Limiting ---
# In-memory defaultdict for rate limiting (will be replaced by MongoDB)
# rate_limits = defaultdict(list)
RATE_LIMIT_WINDOW = 60  # 1 minute window
RATE_LIMIT_MAX = 30  # 30 requests per minute - more reasonable for production

async def is_rate_limited(user_id: int) -> bool:
    if is_admin(user_id):  # Skip rate limiting for admins
        return False
        
    now = datetime.now(UTC)
    window_start = now - timedelta(seconds=RATE_LIMIT_WINDOW)
    
    try:
        # Use more efficient single update operation
        result = tokens_collection.find_one_and_update(
            {'user_id': user_id},
            {
                '$pull': {'rate_limits': {'timestamp': {'$lt': window_start}}},
                '$push': {'rate_limits': {'timestamp': now}}
            },
            upsert=True,
            return_document=True
        )
        
        if not result:
            logger.error(f"Failed to update rate limits for user {user_id}")
            return False
            
        current_requests = len(result.get('rate_limits', []))
        
        if current_requests > RATE_LIMIT_MAX:
            logger.warning(f"User {user_id} is rate limited. Requests in last {RATE_LIMIT_WINDOW}s: {current_requests}/{RATE_LIMIT_MAX}")
            return True
            
        return False
        
    except Exception as e:
        logger.error(f"Error in is_rate_limited for user {user_id}: {e}", exc_info=True)
        # Default to not rate-limiting if there's a database error to prevent bot from stopping
        return False

# --- Error Handling ---
async def handle_error(client: Client, message: Message, error: Exception):
    try:
        if isinstance(error, UserNotParticipant):
            return
        elif isinstance(error, FloodWait):
            logger.warning(f"FloodWait: {error.value} seconds")
            wait_time = int(error.value) if isinstance(error.value, int) or (isinstance(error.value, str) and error.value.isdigit()) else 10
            await message.reply_text(
                f"⚠️ <b>Too Many Requests!</b>\n"
                f"Please wait <b>{wait_time}</b> seconds before trying again.",
                disable_notification=True
            )
        elif isinstance(error, ChatInvalid):
            logger.error(f"ChatInvalid error for message {message.id}: {error}")
            await message.reply_text(
                "❌ <b>Unable to process request.</b>\n"
                "Please make sure the bot has proper permissions.",
                disable_notification=True
            )
        elif isinstance(error, MessageIdInvalid):
            logger.error(f"MessageIdInvalid error for message {message.id}: {error}")
            # Don't send a reply as the message likely doesn't exist
            return
        else:
            error_id = str(uuid.uuid4())[:8]
            logger.error(f"Error ID {error_id}: An error occurred: {error}", exc_info=True)
            await message.reply_text(
                f"❌ <b>An unexpected error occurred.</b>\n"
                f"Error ID: {error_id}\n"
                f"Please try again later or contact support with this Error ID if the problem persists.",
                disable_notification=True
            )
    except Exception as e:
        # Last resort error handling
        logger.critical(f"Failed to handle error properly: Original error: {error}, Handler error: {e}", exc_info=True)

# --- Handlers ---
@app.on_message(filters.command("start") & filters.private)
async def start_command(client, message: Message):
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
                    'joined_date': datetime.now(UTC),
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
                            f"🎉 Success! You got {config.REFRESH_BONUS} token. Each token lasts 24 hours.",
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
                    # Check if result_or_msg is an InlineKeyboardMarkup or just a string (error_msg)
                    if isinstance(result_or_msg, InlineKeyboardMarkup):
                        await message.reply("❌ No Tokens Left!\nUse any of these methods to gain tokens:", reply_markup=result_or_msg)
                    elif isinstance(result_or_msg, str):
                        await message.reply(result_or_msg)
                    return
                
                video = result_or_msg # Now video is definitely a dict if success is True due to handle_shared_video return type

                if await is_menu_active(client, user_id, message.chat.id):
                    try:
                        old_menu = active_menus.get(user_id)
                        if old_menu and old_menu.get('chat_id'):
                            try:
                                await client.delete_messages(old_menu['chat_id'], old_menu['message_id'])
                                logger.info(f"User {user_id} deleted old menu message {old_menu['message_id']} for shared video update.")
                            except Exception as e:
                                logger.warning(f"User {user_id} failed to delete old menu message {old_menu['message_id']}: {e}")
                        
                        if isinstance(video, dict): # Ensure video is a dict before passing to send_video_with_auto_delete
                            sent_success, sent_message_or_error = await send_video_with_auto_delete(
                                client,
                                message.chat.id,
                                video, 
                                reply_markup=video_nav_keyboard(video['uuid'], video['category'])
                            )
                            if sent_success and sent_message_or_error and isinstance(sent_message_or_error, Message): # Explicit check for Message object
                                save_history(user_id, video['uuid'], video['category'])
                                set_active_menu(user_id, sent_message_or_error.id)
                                await message.reply("🎉 <b>Success!</b> Video updated in your active menu.")
                                logger.info(f"User {user_id} updated menu with shared video {video_uuid}.")
                            else:
                                # sent_message_or_error is an error string here
                                await message.reply_text(str(sent_message_or_error))
                        else:
                            await message.reply_text("❌ Failed to retrieve video details for shared link.")
                    except Exception as e:
                        logger.error(f"User {user_id} failed to update menu with shared video: {e}", exc_info=True)
                        await handle_error(client, message, e)
                else:
                    if isinstance(video, dict): # Ensure video is a dict before passing to send_video_with_auto_delete
                        sent_success, sent_message_or_error = await send_video_with_auto_delete(
                            client,
                            message.chat.id,
                            video,
                            reply_markup=video_nav_keyboard(video['uuid'], video['category'])
                        )
                        if sent_success and sent_message_or_error and isinstance(sent_message_or_error, Message): # Explicit check for Message object
                            save_history(user_id, video['uuid'], video['category'])
                            set_active_menu(user_id, sent_message_or_error.id)
                            logger.info(f"User {user_id} sent shared video {video_uuid} as new menu.")
                        else:
                            # sent_message_or_error is an error string here
                            await message.reply_text(str(sent_message_or_error))
                    else:
                        await message.reply_text("❌ Failed to retrieve video details for shared link.")
            if not user:
                user_mention_safe = html.escape(message.from_user.first_name) if message.from_user.first_name else "there"
                await message.reply(
                    f"👋 Welcome, {user_mention_safe}! 🎉\nI'm your Spicy Nyraa Bot! To dive into our exclusive content, simply tap the 'Get Video' button below. If you need any assistance, just type /help.",
                    reply_markup=await get_main_keyboard(user_id)
                )
            else:
                await message.reply(
                    "👋 Welcome back! 🎉\nReady for more spicy content? Just hit the 'Get Video' button below to continue the fun!",
                    reply_markup=await get_main_keyboard(user_id)
                )
            break
        except FloodWait as e:
            wait_time = int(e.value) if isinstance(e.value, int) or (isinstance(e.value, str) and str(e.value).isdigit()) else 10
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

@app.on_message(filters.command("help") & filters.private)
async def help_cmd(client, message: Message):
    user_id = message.from_user.id
    # Sanitize message.from_user.mention explicitly
    user_mention_safe = html.escape(message.from_user.first_name) if message.from_user.first_name else "there"
    await message.reply(
        f"👋 Hello, {user_mention_safe}! Here's a quick guide on how to use Spicy Nyraa Bot:\n\n"
        "🎬 Get Video: Tap this button to discover and watch our exclusive spicy content!\n"
        "🔑 Tokens: Each token provides you with 24 hours of unlimited access.\n"
        "💰 Earn Tokens: Get more tokens by referring friends, refreshing your token, or purchasing them.\n"
        "📢 Join Channel: Make sure you're subscribed to our official channel to access videos.\n"
        "📊 Your Profile: Use /profile to check your token balance, video views, and referral stats.\n\n"
        "Enjoy your experience! ✨",
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
    ref_link = f"https://t.me/{(await client.get_me()).username}?start=ref_{user_id}"
    
    # Sanitize user's first name and username for HTML (already present, verifying and ensuring usage)
    sanitized_first_name = html.escape(message.from_user.first_name if message.from_user.first_name else '')
    sanitized_username = html.escape(message.from_user.username if message.from_user.username else '')

    await message.reply(f"👤 Your Profile\n\nTokens: {len(tokens)}\nVideo Views: {view_count}\nReferrals: {referral_count}\nReferral Link: <code>{ref_link}</code>\n{(f'Referred by: {referred_by}') if referred_by else ''}", reply_markup=referral_keyboard(ref_link))

@app.on_message(filters.regex("^Get Video$") & filters.private)
async def get_video(client, message: Message):
    user_id = message.from_user.id
    logger.info(f"User {user_id} requested Get Video.")
    
    if await is_rate_limited(user_id):
        await handle_error(client, message, FloodWait(10))
        logger.warning(f"User {user_id} hit rate limit in get_video.")
        return

    if not user_has_token(user_id):
        logger.info(f"User {user_id} has no tokens, prompting earning options.")
        result = await send_token_earning_options(client, user_id=user_id)
        if isinstance(result, InlineKeyboardMarkup):
            await message.reply("❌ No Tokens Left!\nUse any of these methods to gain tokens:", reply_markup=result)
        else:
            await message.reply(result)
        return
    
    chat_id = message.chat.id # Get chat_id here
    if await is_menu_active(client, user_id, chat_id):
        logger.warning(f"User {user_id} tried to open new menu but active menu already open.")
        await message.reply("⚠️ Menu Already Open\nScroll up, your menu is already open.")
        return
    
    cats = get_categories()
    if not cats:
        add_category(config.DEFAULT_CATEGORY)
        cats = [config.DEFAULT_CATEGORY]
        logger.info(f"Default category '{config.DEFAULT_CATEGORY}' created for user {user_id}.")
    logger.info(f"User {user_id} prompted to choose category.")
    await message.reply("🎬 Choose a Category:", reply_markup=category_keyboard())

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
    if await is_menu_active(client, user_id, chat_id):
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
        
        if sent_success and sent_message_or_error and isinstance(sent_message_or_error, Message):
            save_history(user_id, video['uuid'], sanitized_category)
            set_active_menu(user_id, sent_message_or_error.id)
            await callback_query.message.delete()
            logger.info(f"User {user_id} selected category {sanitized_category} and video {video['uuid']} sent.")
        else:
            logger.error(f"User {user_id} failed to send video after category selection: {sent_message_or_error}")
            await callback_query.message.edit_text(
                str(sent_message_or_error),
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
            logger.warning(f"User {user_id} used invalid category '{category}', falling back to default.")

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
                chat_id,
                video,
                reply_markup=video_nav_keyboard(video['uuid'], sanitized_category)
            )
            
            if sent_success and sent_message_or_error and isinstance(sent_message_or_error, Message):
                save_history(user_id, video['uuid'], sanitized_category)
                set_active_menu(user_id, sent_message_or_error.id)
                await callback_query.message.delete()
                logger.info(f"User {user_id} navigated to next video {video['uuid']} in category {sanitized_category}.")
            else:
                logger.error(f"User {user_id} failed to send next video: {sent_message_or_error}")
                await callback_query.answer(str(sent_message_or_error), show_alert=True)
        except pyrogram.errors.MessageIdInvalid:
            logger.warning(f"User {user_id} encountered MessageIdInvalid while sending next video, sending as new message.")
            # If edit fails, send as new message
            sent_success, sent_message_or_error = await send_video_with_auto_delete(
                client,
                chat_id,
                video,
                reply_markup=video_nav_keyboard(video['uuid'], sanitized_category)
            )
            if sent_success and sent_message_or_error and isinstance(sent_message_or_error, Message):
                save_history(user_id, video['uuid'], sanitized_category)
                set_active_menu(user_id, sent_message_or_error.id)
                logger.info(f"User {user_id} sent next video {video['uuid']} as new message.")
            else:
                logger.error(f"User {user_id} failed to send next video as new message: {sent_message_or_error}")
                await callback_query.answer(str(sent_message_or_error), show_alert=True)
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
                    found_category = prev_entry.get('category', config.DEFAULT_CATEGORY) # Use the category from history for navigation, with fallback
        
        if not found_video:
            logger.warning(f"User {user_id} could not find valid previous video in history after efficient lookup.")
            # Fallback to full reverse iteration if efficient lookup fails
            for entry in reversed(history_entries):
                if entry['video_uuid'] == current_uuid:
                    continue # Skip the current video
                
                video = media_collection.find_one({'uuid': entry['video_uuid']})
                if video:
                    found_video = video
                    found_category = entry.get('category', config.DEFAULT_CATEGORY) # Use the category from history for navigation, with fallback
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
            chat_id,
            found_video,
            reply_markup=video_nav_keyboard(found_video['uuid'], found_category if found_category is not None else config.DEFAULT_CATEGORY)
        )
        
        if sent_success and sent_message_or_error and isinstance(sent_message_or_error, Message):
            save_history(user_id, found_video['uuid'], found_category if found_category is not None else config.DEFAULT_CATEGORY)
            set_active_menu(user_id, sent_message_or_error.id)
            logger.info(f"User {user_id} navigated to previous video {found_video['uuid']} in category {found_category if found_category is not None else config.DEFAULT_CATEGORY}.")
        else:
            logger.error(f"User {user_id} failed to send previous video: {sent_message_or_error}")
            await callback_query.answer(
                str(sent_message_or_error),
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

        ref_link = f"https://t.me/{(await client.get_me()).username}?start=ref_{user_id}"
        await message.reply(f"🔗 <b>Share & Earn!</b>\nShare this video with your friends!\n<code>{html.escape(ref_link)}</code>", reply_markup=referral_keyboard(ref_link))
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
        long_url = f"https://telegram.dog/{client.me.username}?start=token_{ad_code}" # Use client.me.username safely
        ad_url = await shorten_url(long_url)
        logger.info(f"User {user_id}: shorten_url call completed. Result: {ad_url}")
        
        await temp_msg.delete()

        disable_preview = False
        if ad_url.startswith(f"https://telegram.dog/{client.me.username}"): # Use client.me.username safely
            logger.warning(f"User {user_id} URL shortening failed for refresh_token_btn. Using long URL: {ad_url}")
            disable_preview = True # Disable preview for long Telegram links

        # Sanitize user mention
        user_mention_safe = html.escape(message.from_user.first_name) if message.from_user.first_name else "there"
        await message.reply_text(
            f"💡 Information\nHere are the details you requested...\n\n"
            f"Hey 💕 {user_mention_safe}\n\nYour Ads token is expired, refresh your token and try again.\n\nToken Timeout: 24 hour\n\nWhat is token?\nThis is an ads token. If you pass 1 ad, you can use the bot for 24 hour after passing the ad.\n\nAPPLE/IPHONE USERS COPY TOKEN LINK AND OPEN IN CHROME BROWSER",
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

async def send_token_earning_options(client: Client, user_id: int) -> Union[InlineKeyboardMarkup, str]:
    logger.info(f"User {user_id} is being sent token earning options.")
    try:
        if await is_rate_limited(user_id):
            return "⚠️ You're requesting token options too quickly. Please wait a minute and try again."

        ad_code = str_to_b64(f"{user_id}:{get_current_time() + config.TOKEN_EXPIRY}")
        long_url = f"https://telegram.dog/{(await client.get_me()).username}?start=token_{ad_code}"
        ad_url = await shorten_url(long_url)
        
        disable_preview = False
        if ad_url.startswith(f"https://telegram.dog/{client.me.username}"): # Use client.me.username safely
            logger.warning(f"User {user_id} URL shortening failed for send_token_earning_options. Using long URL: {ad_url}")
            disable_preview = True

        # Construct and return the keyboard. The calling handler will send it.
        keyboard = token_earning_keyboard(ad_url)
        return keyboard
    except Exception as e:
        logger.error(f"User {user_id} failed to send token earning options: {e}", exc_info=True)
        return "❌ Failed to send token earning options." # Return error string

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
            f"🔗 Share & Earn!\nShare this video with your friends!\n<code>{html.escape(share_link)}</code>",
            quote=True
        )
        logger.info(f"User {user_id}: Share link for video {video_uuid} sent successfully.")
    except Exception as e:
        logger.error(f"User {user_id} failed to send share link for video {video_uuid}: {e}", exc_info=True)
        await callback_query.answer("❌ Something went wrong. Please try again.", show_alert=True)

# --- Admin Commands ---
@app.on_message(filters.command("broadcast") & filters.private & filters.user(list(config.ADMIN_IDS)))
async def broadcast_cmd(client, message: Message):
    user_id = message.from_user.id # Added user_id for logging
    replied_message = message.reply_to_message
    logger.info(f"Admin {user_id} initiated broadcast.")
    try:
        users = list(users_collection.find({}, {'user_id': 1}))
        total_users = len(users)
        broadcast_msg = await message.reply(f"📣 Broadcasting to {total_users} users...")
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
                logger.warning(f"User {user['user_id']} hit FloodWait during broadcast: {e.value} seconds. Pausing broadcast.") # Cast to int
                wait_time = int(e.value) if isinstance(e.value, int) or (isinstance(e.value, str) and str(e.value).isdigit()) else 10
                await asyncio.sleep(wait_time + 1)  # Ensure e.value is an integer
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

@app.on_message(filters.command("addcategory") & filters.private & filters.user(list(config.ADMIN_IDS)))
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

@app.on_message(filters.command("deletecategory") & filters.private & filters.user(list(config.ADMIN_IDS)))
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
            buttons.append([InlineKeyboardButton(category, callback_data=f"confirmdelcat_{category}")])

        await message.reply_text(
            """Select a category to delete:\n\n⚠️ All videos in the selected category will be deleted permanently. This action cannot be undone. Click on a category name below to confirm deletion.""",
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

@app.on_message(filters.command("addtoken") & filters.private & filters.user(list(config.ADMIN_IDS)))
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

@app.on_message(filters.command("batchadd") & filters.private & filters.user(list(config.ADMIN_IDS)))
async def batchadd_cmd(client, message: Message):
    user_id = message.from_user.id
    await message.reply_text("DEBUG: Entered /batchadd handler") # Bot reply
    logger.debug("Entered /batchadd handler") # Console log
    logger.info(f"Admin {user_id} requested to enter batch add mode.")
    try:
        if user_id not in config.ADMIN_IDS:
            await message.reply("DEBUG: Not an admin (should not happen due to filter)")
            return

        categories = get_categories()
        await message.reply_text(f"DEBUG: Categories found: {categories}") # Bot reply
        logger.debug(f"Categories found: {categories}") # Console log
        if not categories:
            add_category(config.DEFAULT_CATEGORY)
            categories = get_categories()
            logger.info(f"Admin {user_id}: No categories found, added default category '{config.DEFAULT_CATEGORY}'.")

        batch_add_state[user_id] = {
            'batch_mode': True,
            'current_category': None  # Initialize to None, user needs to select
        }
        await message.reply_text("DEBUG: batch_add_state set") # Bot reply
        logger.debug("batch_add_state set") # Console log

        buttons = []
        for category in categories:
            buttons.append([InlineKeyboardButton(category, callback_data=f"setcat_{category}")])

        await message.reply(
            f"Current category: None (Please select from available categories below)",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        logger.info(f"Admin {user_id}: Prompted to select category for batch add.")

    except Exception as e:
        logger.error(f"Admin {user_id} failed to enter batch add mode: {e}", exc_info=True)
        await message.reply(f"❌ An error occurred while entering batch add mode. Please try again.")

@app.on_message(filters.command("done") & filters.private & filters.user(list(config.ADMIN_IDS)))
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
        else:
            await message.reply("Batch add mode is not currently active.")
            logger.warning(f"Admin {user_id} tried to use /done but batch mode was not active.")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to disable batch add mode: {e}", exc_info=True)
        await message.reply("❌ An error occurred while ending batch add mode. Please try again.")

@app.on_message(filters.video & filters.private & filters.user(list(config.ADMIN_IDS)))
async def handle_video(client, message: Message):
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} sent a video for batch adding.")

    try:
        if user_id not in batch_add_state or not batch_add_state[user_id].get('batch_mode'):
            logger.warning(f"Admin {user_id} sent video outside of batch add mode, ignoring.")
            await message.reply_text("You are not in batch add mode. Use /batchadd to start.")
            return

        category = batch_add_state[user_id].get('current_category')
        if not category:
            logger.warning(f"Admin {user_id} tried to add video but no category selected in batch mode.")
            await message.reply_text("⚠️ Please select a category first using the inline keyboard provided after /batchadd, or use /category to set it.")
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
            protect_content=protect_content
        )
        message_id_in_channel = forwarded_message.id

        video_data = {
            "uuid": video_uuid,
            "file_id": file_id,
            "file_unique_id": file_unique_id,
            "category": category,
            "size_bytes": file_size,
            "timestamp": get_current_time(),
            "message_id": message_id_in_channel,
            "banned": False
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
        await message.reply(f"❌ Failed to add video: {e}. Please check bot's permissions in the video channel or try again.")

@app.on_message(filters.command("category") & filters.private & filters.user(list(config.ADMIN_IDS)))
async def set_category_cmd(client, message: Message):
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} requested to set category.")
    try:
        if not is_admin(user_id):
            logger.warning(f"Non-admin user {user_id} attempted to use set_category_cmd.")
            await message.reply_text("❌ Only admins can use this command.")
            return

        # This command is now primarily for setting category within batch mode.
        # It can also be called outside batch mode, in which case it will just show categories.
        # Check if batch_mode is active
        if user_id not in batch_add_state or not batch_add_state[user_id].get('batch_mode', False):
            await message.reply_text("You are not in batch add mode. Use /batchadd to start and then select a category.")
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
        category_name = callback_query.data[7:]

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
        await callback_query.message.edit_text(f"✅ Category '{html.escape(category_name)}' selected. Send me videos to add. Type /done when finished.") # Updated message
        logger.info(f"Admin {user_id} successfully set batch category to '{category_name}'.")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to set batch category: {e}", exc_info=True)
        await callback_query.answer("❌ An error occurred while setting category. Please try again.", show_alert=True)

@app.on_message(filters.command("stats") & filters.private & filters.user(list(config.ADMIN_IDS)))
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

@app.on_message(filters.command("checkchannel") & filters.private & filters.user(list(config.ADMIN_IDS)))
async def check_channel_cmd(client, message: Message):
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} requested channel check for ID: {config.VIDEO_CHANNEL_ID}")
    try:
        channel = await client.get_chat(int(config.VIDEO_CHANNEL_ID))
        bot_member = await client.get_chat_member(int(config.VIDEO_CHANNEL_ID), client.me.id)

        status_text = (
            f"✅ Channel accessible!\n"
            f"Title: {channel.title}\n"
            f"ID: {channel.id}\n"
            f"Bot Status: {bot_member.status}"
        )
        await message.reply(status_text)
        logger.info(f"Admin {user_id} channel check successful for {config.VIDEO_CHANNEL_ID}. Bot status: {bot_member.status}.")
    except pyrogram.errors.exceptions.bad_request_400.ChannelInvalid as e:
        error_message = f"❌ ChannelInvalid error checking channel {config.VIDEO_CHANNEL_ID}: {e}. Ensure bot is admin and VIDEO_CHANNEL_ID is correct."
        logger.error(f"Admin {user_id} channel check failed: {error_message}", exc_info=True)
        await message.reply(error_message)
    except Exception as e:
        error_message = f"❌ Error checking channel {config.VIDEO_CHANNEL_ID}: {e}"
        logger.error(f"Admin {user_id} channel check failed: {error_message}", exc_info=True)
        await message.reply(error_message)

# --- Auto-Delete & Protect Content ---
@app.on_message(filters.command('toggle_auto_delete') & filters.private & filters.user(list(config.ADMIN_IDS)))
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

@app.on_message(filters.command('toggle_protect') & filters.private & filters.user(list(config.ADMIN_IDS)))
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

# --- Database Cleanup ---
async def cleanup_expired_data():
    """Clean up expired tokens and old history entries."""
    while True:
        try:
            now = datetime.now(UTC)
            
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
                except (MessageIdInvalid, ValueError): # Corrected to MessageIdInvalid
                    logger.warning(f"Video {video_uuid} (message_id: {message_id_in_channel}) no longer exists in channel. Deleting from DB.")
                    media_collection.delete_one({'uuid': video_uuid})
                except Exception as e:
                    logger.error(f"Error verifying media {video_uuid}: {e}")

            logger.info("Media verification and cleanup completed.")
        except Exception as e:
            logger.error(f"Error in media verification cleanup task: {e}", exc_info=True)
        
        # Run every 6 hours
        await asyncio.sleep(6 * 3600)

# --- Main ---
async def background_task_wrapper(task_func, task_name):
    """Wrapper to ensure background tasks keep running and are restarted on failure"""
    while True:
        try:
            await task_func()
        except Exception as e:
            logger.error(f"Error in {task_name}, restarting in 60 seconds: {e}", exc_info=True)
            await asyncio.sleep(60)  # Wait before restarting

async def main_loop():
    restart_delay = 1
    max_restart_delay = 300  # 5 minutes
    
    while True:
        try:
            logger.info("Attempting to start bot client...")
            await app.start()
            logger.info("Bot client started successfully!")
            
            # Log bot's own information after successful start
            me = await app.get_me()
            logger.info(f"Bot Info: ID={me.id}, Username={me.username}, First Name={me.first_name}")

            # Schedule background tasks with wrapper for resilience
            logger.info("Scheduling background tasks...")
            cleanup_task = asyncio.create_task(background_task_wrapper(cleanup_expired_data, "cleanup_expired_data"))
            media_verify_task = asyncio.create_task(background_task_wrapper(verify_and_cleanup_media, "verify_and_cleanup_media"))
            logger.info("Background tasks scheduled with auto-restart wrapper.")
            
            logger.info("Bot is now idle, listening for updates...")
            await idle()
            
            # If we get here, it means idle() completed normally
            logger.info("Bot stopping gracefully...")
            await app.stop()
            
            # Cancel background tasks gracefully
            cleanup_task.cancel()
            media_verify_task.cancel()
            try:
                await cleanup_task
                await media_verify_task
            except asyncio.CancelledError:
                pass
                
            break  # Exit the loop if everything shut down gracefully
            
        except Exception as e:
            logger.critical(f"Critical error in main_loop, attempting restart in {restart_delay} seconds: {e}", exc_info=True)
            try:
                await app.stop()
            except Exception:
                pass
            
            await asyncio.sleep(restart_delay)
            # Exponential backoff for restart delays
            restart_delay = min(restart_delay * 2, max_restart_delay)

if __name__ == '__main__':
    asyncio.run(main_loop())
