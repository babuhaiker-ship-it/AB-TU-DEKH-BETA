import os
import asyncio
import uuid
import base64
import random
import logging
from datetime import datetime, timedelta
from pyrogram import Client, filters
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, Message, InlineQueryResultArticle, InputTextMessageContent, CallbackQuery
)
from pyrogram.errors import UserIsBlocked, ChatInvalid, MessageIdInvalid, FloodWait, RPCError, BadRequest, PeerIdInvalid, ChannelInvalid
from pymongo import MongoClient, ASCENDING, ReturnDocument
import aiohttp
from aiohttp import ClientTimeout
from collections import defaultdict
import re
import html

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Configuration ---
class BotConfig:
    BOT_TOKEN = '7965872423:AAHkSMHJVveM1ROKlPJGgsP_GcLb8iNvCic'
    API_ID = 29800015
    API_HASH = 'c8f37108be31ab9ea2818bfe533fbb6f'
    BOT_USERNAME = '@Testingnyraa_bot'
    MONGO_URI = 'mongodb+srv://Pyasipriya:00pEcao9sYhNC5VQ@cluster0.2dfenf7.mongodb.net/spicybot?retryWrites=true&w=majority&appName=Cluster0'
    MONGO_DB_NAME = 'spicybot'
    VIDEO_CHANNEL_ID = -1002621716446 # Ensure this is correct and bot is admin with posting rights
    BUY_BOT_URL = 'https://t.me/hanielxsupportbot'
    ADMIN_IDS = [6612030110]
    URL_SHORTENER = 'https://api.linkshortify.com/st'
    SHORTENER_API_KEY = '5cd923c490f64017cffa6e3bb6cc724560a8cfc6'
    TUTORIAL_LINK_2 = 'https://t.me/urlshortenertutorial'
    TOKEN_EXPIRY = 86400  # 24 hours in seconds
    DEFAULT_CATEGORY = 'default'
    # Customization options
    NEW_USER_TOKENS = 1
    REFERRAL_BONUS = 1
    REFRESH_BONUS = 1
    MENU_TIMEOUT = 3600 # Added MENU_TIMEOUT config

try:
    config = BotConfig()
    # Basic validation for essential configs
    if not all([config.BOT_TOKEN, config.API_ID, config.API_HASH, config.MONGO_URI, config.SHORTENER_API_KEY, config.BOT_USERNAME]):
        raise ValueError("One or more essential configuration variables are not set. Please check BOT_TOKEN, API_ID, API_HASH, MONGO_URI, SHORTENER_API_KEY, BOT_USERNAME in your environment variables.")
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
history_collection.create_index([("history.viewed_at", ASCENDING)])
history_collection.create_index([("user_id", ASCENDING)], unique=True)
categories_collection.create_index([("name", ASCENDING)], unique=True)

# --- Pyrogram Client ---
app = Client("spicynyraa", api_id=config.API_ID, api_hash=config.API_HASH, bot_token=config.BOT_TOKEN)

# --- Admin Check Utility ---
def is_admin(user_id: int) -> bool:
    """Checks if the given user ID belongs to an administrator."""
    return user_id in config.ADMIN_IDS

# --- Utility Functions ---
def str_to_b64(string: str) -> str:
    """Encodes a string to URL-safe base64."""
    return base64.urlsafe_b64encode(string.encode()).decode()

def b64_to_str(b64: str) -> str:
    """Decodes a URL-safe base64 string."""
    try:
        return base64.urlsafe_b64decode(b64.encode()).decode()
    except Exception as e:
        logger.error(f"Failed to decode base64 string: {e}")
        return ""

def get_current_time() -> int:
    """Returns the current UTC timestamp as an integer."""
    return int(datetime.utcnow().timestamp())

async def shorten_url(long_url: str) -> str:
    """Shortens a given URL using the configured URL shortener service."""
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
def get_valid_tokens(user_id: int) -> list:
    """Retrieves a list of valid (non-expired) tokens for a user."""
    doc = tokens_collection.find_one({'user_id': user_id})
    if not doc:
        return []
    now = datetime.utcnow()
    return [t for t in doc['tokens'] if t['expires_at'] > now]

def add_token(user_id: int, duration=config.TOKEN_EXPIRY):
    """Adds a new token for a user with a specified duration."""
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

def get_and_cleanup_tokens(user_id: int) -> list:
    """Removes expired tokens from the database and returns the list of valid tokens."""
    now = datetime.utcnow()
    
    # Remove expired tokens
    try:
        tokens_collection.update_one(
            {'user_id': user_id},
            {'$pull': {'tokens': {'expires_at': {'$lt': now}}}},
            upsert=True # Ensure the document exists for future updates
        )
    except Exception as e:
        logger.error(f"Error cleaning up expired tokens for user {user_id}: {e}", exc_info=True)
        
    # Fetch the document after cleanup
    doc = tokens_collection.find_one({'user_id': user_id})
    return doc.get('tokens', []) if doc else []

def user_has_token(user_id: int) -> bool:
    """Checks if a user has any valid tokens."""
    return len(get_and_cleanup_tokens(user_id)) > 0

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
                add_token(referrer_id, config.REFERRAL_BONUS * 86400) # Give referrer a token
                users_collection.update_one({'user_id': referrer_id}, {'$inc': {'referral_count': 1}}, upsert=True)
                users_collection.update_one({'user_id': new_user_id}, {'$set': {'referred_by': referrer_id}}, upsert=True)
                logger.info(f"User {new_user_id} successfully referred by {referrer_id}.")
                return referrer_id
    elif ref_code.startswith('video_'): # Handle video share referrals
        try:
            # Format: video_[video_id]_[referrer_id]
            parts = ref_code.split('_')
            if len(parts) == 3:
                # video_id = parts[1] # Not directly used for referral, but good for debugging
                referrer_id = int(parts[2])
                
                if referrer_id != new_user_id:
                    ref_user = users_collection.find_one({'user_id': referrer_id})
                    if ref_user:
                        add_token(referrer_id, config.REFERRAL_BONUS * 86400) # Give referrer a token
                        users_collection.update_one({'user_id': referrer_id}, {'$inc': {'referral_count': 1}}, upsert=True)
                        users_collection.update_one({'user_id': new_user_id}, {'$set': {'referred_by': referrer_id}}, upsert=True)
                        logger.info(f"User {new_user_id} successfully referred by {referrer_id} via video share.")
                        return referrer_id
        except ValueError:
            logger.warning(f"Invalid referrer ID format in video share ref_code: {ref_code}")
        except IndexError:
            logger.warning(f"Invalid video share ref_code format: {ref_code}")

    return None


# --- Category Management ---
def validate_category_name(name: str) -> tuple[bool, str]:
    """Validates a category name.
    Returns (is_valid, error_message)"""
    if not name:
        return False, "Category name cannot be empty."
    if not re.match(r'^[a-zA-Z0-9_-]+$', name):
        return False, "Category name can only contain letters, numbers, underscores, and hyphens."
    if len(name) > 32:
        return False, "Category name cannot be longer than 32 characters."
    return True, ""

def get_categories() -> list[str]:
    """Gets all category names, ensuring the default category exists."""
    categories = [c['name'] for c in categories_collection.find({})]
    if not categories or config.DEFAULT_CATEGORY not in categories:
        add_category(config.DEFAULT_CATEGORY)
        categories = [config.DEFAULT_CATEGORY] + [c['name'] for c in categories_collection.find({'name': {'$ne': config.DEFAULT_CATEGORY}})] # Re-fetch to ensure default is included correctly if newly added
    return sorted(list(set(categories))) # Ensure unique and sorted

def add_category(name: str) -> tuple[bool, str]:
    """Adds a new category.
    Returns (success, message)"""
    try:
        # Validate name
        valid, error = validate_category_name(name)
        if not valid:
            return False, error
            
        # Check if exists
        if categories_collection.find_one({'name': name}):
            return False, f"Category '{html.escape(name)}' already exists."
            
        # Add category
        categories_collection.insert_one({
            'name': name,
            'created_at': datetime.utcnow()
        })
        logger.info(f"Category '{name}' added")
        return True, f"Category '{html.escape(name)}' added successfully."
    except Exception as e:
        logger.error(f"Error adding category '{name}': {e}")
        return False, "Failed to add category. Please try again."

def delete_category(name: str) -> tuple[bool, str, int]:
    """Deletes a category and its associated videos.
    Returns (success, message, deleted_count)"""
    try:
        # Don't allow deleting default category
        if name == config.DEFAULT_CATEGORY:
            return False, "Cannot delete the default category.", 0
            
        # Check if exists
        if not categories_collection.find_one({'name': name}):
            return False, f"Category '{html.escape(name)}' does not exist.", 0
            
        # Delete videos in category
        result = media_collection.delete_many({'category': name})
        deleted_count = result.deleted_count
        
        # Delete category
        categories_collection.delete_one({'name': name})
        logger.info(f"Category '{name}' and {deleted_count} videos deleted")
        return True, f"Category '{html.escape(name)}' and {deleted_count} videos deleted.", deleted_count
    except Exception as e:
        logger.error(f"Error deleting category '{name}': {e}")
        return False, "Failed to delete category. Please try again.", 0

# --- Video Navigation ---
def get_random_video(category: str) -> dict | None:
    """Retrieves a random video from the specified category."""
    videos = list(media_collection.find({'category': category}))
    if not videos:
        return None
    return random.choice(videos)

def get_video_by_uuid(uuid_: str) -> dict | None:
    """Retrieves a video by its UUID."""
    return media_collection.find_one({'uuid': uuid_})

def save_history(user_id: int, video_uuid: str, category: str):
    """Saves a video viewing entry to a user's history, limiting to the last 100 entries."""
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

def get_last_video(user_id: int) -> dict | None:
    """Retrieves the last viewed video from a user's history."""
    doc = history_collection.find_one({'user_id': user_id})
    if doc and doc.get('history'):
        return doc['history'][-2] if len(doc['history']) > 1 else None # -2 for previous, -1 for current
    return None

# --- Menu State Management ---
active_menus = {} # Stores active menu message IDs and timestamps
MENU_TIMEOUT = config.MENU_TIMEOUT  # Use configured timeout

def set_active_menu(user_id: int, message_id: int, chat_id: int):
    """Set an active menu for a user."""
    active_menus[user_id] = {
        'message_id': message_id,
        'timestamp': get_current_time(),
        'chat_id': chat_id
    }
    logger.info(f"Active menu set for user {user_id}: message_id={message_id}, chat_id={chat_id}")

def clear_active_menu(user_id: int):
    """Clear a user's active menu state."""
    if user_id in active_menus:
        del active_menus[user_id]
        logger.info(f"Active menu cleared for user {user_id}.")

async def cleanup_expired_menu(client: Client, user_id: int, chat_id: int):
    """Clean up an expired menu by deleting the message."""
    try:
        menu = active_menus.get(user_id)
        if menu and chat_id and menu.get('message_id'):
            try:
                await client.delete_messages(chat_id, menu['message_id'])
                logger.info(f"Deleted expired menu message {menu['message_id']} for user {user_id} in chat {chat_id}")
            except MessageIdInvalid:
                logger.warning(f"Attempted to delete expired menu message {menu['message_id']} for user {user_id} in chat {chat_id}, but message was already deleted or invalid.")
            except Exception as e:
                logger.error(f"Failed to delete expired menu message {menu['message_id']} for user {user_id} in chat {chat_id}: {e}")
        clear_active_menu(user_id)
    except Exception as e:
        logger.error(f"Error in cleanup_expired_menu for user {user_id}: {e}")

async def is_menu_active(client: Client, user_id: int, chat_id: int) -> bool:
    """Check if a user has an active menu and clean up if expired."""
    if user_id not in active_menus:
        return False
        
    menu = active_menus[user_id]
    if get_current_time() - menu['timestamp'] > MENU_TIMEOUT:
        await cleanup_expired_menu(client, user_id, chat_id)
        return False
        
    return True

# --- Keyboards ---
async def get_main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    """Main keyboard for the bot."""
    buttons = [
        [KeyboardButton("Get Video"), KeyboardButton("Profile")],
        [KeyboardButton("Refer & Earn"), KeyboardButton("Buy Token")],
        [KeyboardButton("Refresh Token")]
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def token_earning_keyboard(ad_url: str) -> InlineKeyboardMarkup:
    """Keyboard for token earning options."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Click Here To Refresh Token", url=ad_url)],
        [InlineKeyboardButton("How To Open Links?", url=config.TUTORIAL_LINK_2)],
        [InlineKeyboardButton("Buy Token", url=config.BUY_BOT_URL)]
    ])

def category_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for selecting video categories."""
    cats = get_categories()
    if not cats:
        # Fallback if no categories are found, although add_category ensures default exists
        return InlineKeyboardMarkup([[InlineKeyboardButton("No Categories Available", callback_data="no_cat")]])
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(html.escape(cat), callback_data=f"cat_{cat}")] for cat in cats]
    )

def video_nav_keyboard(video_uuid: str, category: str, user_id: int) -> InlineKeyboardMarkup:
    """
    Keyboard for navigating between videos, including a 'Share' button
    with a deep link that carries video ID and user ID.
    """
    share_link_data = f"{video_uuid}_{user_id}" # Format: video_UUID_USERID
    encoded_share_data = str_to_b64(share_link_data)
    
    # The actual share URL will be generated in the callback query for flexibility
    # For the button, we use a simple callback to trigger the share link generation
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Previous", callback_data=f"prev_{video_uuid}_{category}"),
            InlineKeyboardButton("Next", callback_data=f"next_{video_uuid}_{category}")
        ],
        [InlineKeyboardButton("Change Category", callback_data="change_cat")],
        [InlineKeyboardButton("Share", callback_data=f"share_{video_uuid}")] # Pass only video_uuid, user_id is implicit
    ])


def referral_keyboard(ref_link: str) -> InlineKeyboardMarkup:
    """Keyboard for displaying a referral link."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Copy Referral Link", url=ref_link)]
    ])

def buy_token_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for buying tokens."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Buy Token", url=config.BUY_BOT_URL)]
    ])

# --- Video Sharing ---
async def handle_shared_video(client: Client, user_id: int, video_uuid: str) -> tuple[bool, dict | str]:
    """
    Handles a user attempting to view a video shared via a deep link.
    Returns (success: bool, result: dict | str), where result is video data on success, or an error message on failure.
    """
    video = get_video_by_uuid(video_uuid)
    if not video:
        logger.warning(f"User {user_id} attempted to view non-existent shared video {video_uuid}.")
        return False, "Oops, invalid link. Try again!"
    
    if video.get('banned'):
        logger.warning(f"User {user_id} attempted to view banned video {video_uuid}.")
        return False, "❌ This content is no longer available."
    
    # No token check here, as per new logic.
    # The calling function (start_cmd) will handle token checks and display options.
    
    save_history(user_id, video_uuid, video['category'])
    return True, video

# --- Token Refresh ---
async def handle_token_refresh(user_id: int, ad_code: str) -> tuple[bool, str]:
    """Handles token refresh requests from users."""
    try:
        if await is_rate_limited(user_id):
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
    """Schedules a message to be automatically deleted after a delay."""
    try:
        await asyncio.sleep(delay)
        await message.delete()
        logger.info(f"Auto-deleted message {message.id} from chat {message.chat.id}")
    except Exception as e:
        logger.error(f"Failed to auto-delete message {message.id}: {e}")

async def send_video_with_auto_delete(client: Client, chat_id: int, video_data: dict, reply_markup: InlineKeyboardMarkup = None) -> tuple[bool, Message | str]:
    """
    Sends a video message with optional auto-delete and content protection.
    Returns (success: bool, sent_message: Message | error_message: str)
    """
    settings = settings_collection.find_one({'_id': 'settings'}) or {}
    protect_content = settings.get('protect_content', True)
    auto_delete = settings.get('auto_delete', True)
    
    try:
        sent = await client.send_video(
            chat_id,
            video_data['file_id'],
            caption=f"Category: {html.escape(video_data['category'])}",
            reply_markup=reply_markup,
            protect_content=protect_content
        )
        
        if auto_delete:
            asyncio.create_task(schedule_auto_delete(sent))
        
        return True, sent
    except Exception as e:
        logger.error(f"Failed to send video to chat {chat_id}: {e}")
        return False, "❌ <b>Failed to send video.</b>\nPlease try again later."

# --- Rate Limiting ---
RATE_LIMIT_WINDOW = 120  # 2 minutes
RATE_LIMIT_MAX = 60  # 60 requests per 2 minutes

async def is_rate_limited(user_id: int) -> bool:
    """
    Checks if a user is rate-limited based on their recent requests.
    Stores request timestamps in MongoDB for persistence.
    """
    if is_admin(user_id):  # Skip rate limiting for admins
        return False
        
    now = datetime.utcnow()
    window_start = now - timedelta(seconds=RATE_LIMIT_WINDOW)
    
    try:
        # Atomically update and count: pull old entries, push new one, then check count
        result = tokens_collection.find_one_and_update(
            {'user_id': user_id},
            {
                '$pull': {'rate_limits': {'timestamp': {'$lt': window_start}}},
                '$push': {'rate_limits': {'timestamp': now}}
            },
            upsert=True,
            return_document=ReturnDocument.AFTER
        )
        
        current_requests = len(result.get('rate_limits', [])) if result else 0
        
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
    """Generic error handler for bot commands."""
    if isinstance(error, FloodWait):
        logger.warning(f"FloodWait: {error.value} seconds for user {message.from_user.id}")
        await message.reply_text(f"⚠️ <b>Too Many Requests!</b>\nPlease wait <b>{error.value}</b> seconds before trying again.")
    else:
        logger.error(f"An unexpected error occurred for user {message.from_user.id}: {error}", exc_info=True)
        await message.reply_text(f"❌ <b>An unexpected error occurred.</b>\nPlease try again later.")

# --- Handlers ---
@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    username_safe = html.escape(message.from_user.username) if message.from_user.username else ""
    first_name_safe = html.escape(message.from_user.first_name) if message.from_user.first_name else "there"
    max_retries = 3

    for attempt in range(max_retries):
        try:
            if await is_rate_limited(user_id):
                raise FloodWait(10)
        
            user = users_collection.find_one({'user_id': user_id})
            args = message.text.split()
            
            is_new_user = False
            if not user:
                is_new_user = True
                users_collection.insert_one({
                    'user_id': user_id,
                    'username': username_safe,
                    'first_name': first_name_safe,
                    'last_name': html.escape(message.from_user.last_name) if message.from_user.last_name else None,
                    'joined_date': datetime.utcnow(),
                    'referral_count': 0
                })
                add_token(user_id, config.NEW_USER_TOKENS * 86400) # Give new user initial token
                logger.info(f"New user registered: {user_id} and received {config.NEW_USER_TOKENS} token.")

            # Variables to track deep link type and associated data
            deep_link_type = None
            deep_link_data = None
            video_uuid_from_link = None
            referrer_id_from_video_link = None

            if len(args) > 1:
                deep_link_arg = args[1]
                if deep_link_arg.startswith('token_'):
                    deep_link_type = 'token_refresh'
                    deep_link_data = deep_link_arg[6:]
                elif deep_link_arg.startswith('video_'):
                    deep_link_type = 'video_share'
                    parts = deep_link_arg.split('_')
                    if len(parts) >= 2:
                        video_uuid_from_link = parts[1]
                    if len(parts) == 3:
                        try:
                            referrer_id_from_video_link = int(parts[2])
                        except ValueError:
                            logger.warning(f"Invalid referrer ID in video deep link for user {user_id}: {deep_link_arg}")
                    deep_link_data = video_uuid_from_link # Store the UUID for later use
                elif deep_link_arg.startswith('ref_'):
                    deep_link_type = 'referral'
                    deep_link_data = deep_link_arg # Store the whole ref code

            # Handle welcome/referral messages for new users first, regardless of deep link type
            if is_new_user:
                if deep_link_type == 'referral':
                    referrer_id = handle_referral(user_id, deep_link_data)
                    if referrer_id:
                        await message.reply(f"🥳 **Congratulations {first_name_safe}!** You have received {config.NEW_USER_TOKENS} token to continue.")
                        await client.send_message(referrer_id, f"🎉 **Referral Bonus!** Your friend, {first_name_safe}, joined through your link! You've received {config.REFERRAL_BONUS} token.")
                elif deep_link_type == 'video_share' and referrer_id_from_video_link and referrer_id_from_video_link != user_id:
                    # Referral bonus for new user via video share (already handled in handle_referral but also included here for direct messaging)
                    referrer_user_obj = users_collection.find_one({'user_id': referrer_id_from_video_link})
                    if referrer_user_obj:
                        # handle_referral (called below if deep_link_type is 'video_share') already adds token and updates count
                        await message.reply(f"🥳 **Congratulations {first_name_safe}!** You have received {config.NEW_USER_TOKENS} token to continue.")
                        await client.send_message(referrer_id_from_video_link, f"🎉 **Referral Bonus!** Your friend, {first_name_safe}, joined through your shared video link! You've received {config.REFERRAL_BONUS} token.")
                    else:
                        logger.warning(f"Referrer {referrer_id_from_video_link} not found for new user {user_id} via video share. Still sending new user welcome.")
                        await message.reply(f"🥳 **Congratulations {first_name_safe}!** You have received {config.NEW_USER_TOKENS} token to continue.")
                else: # New user, but no specific referral deep link or video link referral
                    await message.reply(f"👋 dear {first_name_safe} This is Spicy Nyraa Bot. To watch spicy content, click on the Get Video button. Need help? Tap /help.", reply_markup=await get_main_keyboard(user_id))
            elif not deep_link_type: # Returning user, no deep link
                await message.reply(f"👋 dear {first_name_safe} This is Spicy Nyraa Bot. To watch spicy content, click on the Get Video button. Need help? Tap /help.", reply_markup=await get_main_keyboard(user_id))

            # Now, handle the specific deep link action for both new and returning users
            if deep_link_type == 'token_refresh':
                success, msg = await handle_token_refresh(user_id, deep_link_data)
                await message.reply(msg)
                if success:
                    await message.reply(
                        "🎉 <b>Success!</b> Click on Get Video to watch spicy content.",
                        reply_markup=await get_main_keyboard(user_id)
                    )
                # No return here, as we already handled new user message.
                # The user will get the token refresh message and then can use the bot.
            elif deep_link_type == 'video_share':
                logger.info(f"User {user_id} attempting to view shared video {video_uuid_from_link}")
                            
                try:
                    uuid.UUID(video_uuid_from_link) # Validate UUID format
                except ValueError:
                    logger.warning(f"User {user_id} attempted to view shared video with invalid UUID format: {video_uuid_from_link}.")
                    await message.reply("Invalid video link format.", reply_markup=await get_main_keyboard(user_id))
                    break # Exit retry loop

                # Check if video exists
                video_found_in_db = media_collection.find_one({'uuid': video_uuid_from_link})
                if not video_found_in_db:
                    logger.warning(f"User {user_id} attempted to view non-existent shared video UUID {video_uuid_from_link}.")
                    await message.reply("Invalid video link.", reply_markup=await get_main_keyboard(user_id))
                    break # Exit retry loop

                # Process video referral if applicable (already done for new users above, but good to call for robustness)
                if is_new_user and referrer_id_from_video_link:
                    handle_referral(user_id, deep_link_arg) # Use the original deep_link_arg for handle_referral
                
                if not user_has_token(user_id):
                    # User needs a token. Prompt to get token, then tell them to click Get Video.
                    await message.reply("You need a token to watch this video. Please get a token first!", reply_markup=await get_main_keyboard(user_id))
                    await send_token_earning_options(client, message)
                    break # Exit retry loop, don't try to send video now
                else:
                    # User has token, proceed to send the video.
                    success, result_or_msg = await handle_shared_video(client, user_id, video_uuid_from_link)
                    if not success:
                        await message.reply(result_or_msg, reply_markup=await get_main_keyboard(user_id))
                        break # Exit retry loop

                    video = result_or_msg # Now `result_or_msg` is the video object if successful
                    
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
                                reply_markup=video_nav_keyboard(video['uuid'], video['category'], user_id) # Pass user_id for share button
                            )
                            if sent_success:
                                set_active_menu(user_id, sent_message_or_error.id, message.chat.id)
                                await message.reply("🎉 <b>Success!</b> Video updated in your active menu.")
                                logger.info(f"User {user_id} updated menu with shared video {video_uuid_from_link}.")
                            else:
                                await message.reply(sent_message_or_error)

                        except Exception as e:
                            logger.error(f"User {user_id} failed to update menu with shared video: {e}", exc_info=True)
                            await handle_error(client, message, e)
                    else:
                        # Send as new message
                        sent_success, sent_message_or_error = await send_video_with_auto_delete(
                            client,
                            message.chat.id,
                            video,
                            reply_markup=video_nav_keyboard(video['uuid'], video['category'], user_id) # Pass user_id for share button
                        )
                        if sent_success:
                            set_active_menu(user_id, sent_message_or_error.id, message.chat.id)
                            logger.info(f"User {user_id} sent shared video {video_uuid_from_link} as new menu.")
                        else:
                            await message.reply(sent_message_or_error)
                break # Exit retry loop after handling shared video
            
            break  # Exit the retry loop on successful execution
            
        except FloodWait as e:
            wait_time = e.value
            logger.warning(f"User {user_id} hit FloodWait: Waiting for {wait_time} seconds (attempt {attempt + 1}/{max_retries}).")
            await asyncio.sleep(wait_time + 1)  # Wait a bit longer than required
            if attempt < max_retries - 1:
                continue  # Retry
            else:
                logger.error(f"User {user_id} failed to process /start after {max_retries} retries due to FloodWait.")
                await handle_error(client, message, e)  # Max retries reached, propagate error
                break # Exit loop as max retries reached
        except Exception as e:
            logger.error(f"User {user_id} encountered an unexpected error in start command: {e}", exc_info=True)
            await handle_error(client, message, e)

@app.on_message(filters.command("help") & filters.private)
async def help_cmd(client: Client, message: Message):
    """Handles the /help command."""
    user_id = message.from_user.id
    user_mention_safe = html.escape(message.from_user.first_name) if message.from_user.first_name else "there"
    await message.reply(
        f"👋 dear {user_mention_safe} this is how to use spicy nyraa.\n\n"
        "- Use Get Video to watch spicy content.\n"
        "- Each token gives you 24 hours access.\n"
        "- Earn tokens by referral, refresh, or buy.\n"
        "- Use /profile to check your stats.",
        reply_markup=await get_main_keyboard(user_id)
    )

@app.on_message(filters.command("profile") & filters.private)
async def profile_cmd(client: Client, message: Message):
    """Handles the /profile command to show user statistics."""
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
    
    views_doc = history_collection.find_one({'user_id': user_id})
    view_count = len(views_doc['history']) if views_doc and 'history' in views_doc else 0
    ref_link = f"https://t.me/{config.BOT_USERNAME[1:]}?start=ref_{user_id}"
    
    await message.reply(
        f"👤 <b>Your Profile</b>\n\n"
        f"<b>Tokens:</b> {len(tokens)}\n"
        f"<b>Video Views:</b> {view_count}\n"
        f"<b>Referrals:</b> {referral_count}\n"
        f"<b>Referral Link:</b> <code>{html.escape(ref_link)}</code>\n"
        f"{(f'Referred by: {referred_by}') if referred_by else ''}",
        reply_markup=referral_keyboard(ref_link)
    )

@app.on_message(filters.regex("^Get Video$") & filters.private)
async def get_video(client: Client, message: Message):
    """Handles the 'Get Video' button request."""
    user_id = message.from_user.id
    chat_id = message.chat.id
    logger.info(f"User {user_id} requested Get Video.")
    
    if await is_rate_limited(user_id):
        await handle_error(client, message, FloodWait(10))
        logger.warning(f"User {user_id} hit rate limit in get_video.")
        return
        
    if not user_has_token(user_id):
        logger.info(f"User {user_id} has no tokens, prompting earning options.")
        await send_token_earning_options(client, message)
        return
    
    if await is_menu_active(client, user_id, chat_id):
        logger.warning(f"User {user_id} tried to open new menu but active menu already open.")
        await message.reply("⚠️ <b>Menu Already Open</b>\nScroll up, your menu is already open.")
        return
    
    cats = get_categories()
    if not cats: # This should ideally not happen if default category is always ensured
        add_category(config.DEFAULT_CATEGORY)
        cats = [config.DEFAULT_CATEGORY]
        logger.info(f"Default category '{config.DEFAULT_CATEGORY}' created for user {user_id}.")
    logger.info(f"User {user_id} prompted to choose category.")
    await message.reply("🎬 <b>Choose a Category:</b>", reply_markup=category_keyboard())

@app.on_callback_query(filters.regex(r"^cat_(.+)"))
async def select_category(client: Client, callback_query: CallbackQuery):
    """Handles category selection callback."""
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id
    category = callback_query.data[4:] # Extract category from callback_data
    logger.info(f"User {user_id} selected category: {category}.")
    
    if await is_rate_limited(user_id):
        await callback_query.answer("⚠️ You're changing categories too quickly. Please wait a minute and try again.", show_alert=True)
        logger.warning(f"User {user_id} hit rate limit in select_category.")
        return
        
    # Check for active menu - only allow if no menu is active, or if the current message is the menu
    if await is_menu_active(client, user_id, chat_id):
        # If the callback is from the existing menu message, it's fine.
        # Otherwise, if it's a new message, inform the user.
        if active_menus.get(user_id, {}).get('message_id') != callback_query.message.id:
            logger.warning(f"User {user_id} tried to select category but already has active menu from another message.")
            await callback_query.answer("You already have an active menu. Please use that one or wait for it to expire.", show_alert=True)
            return

    # Ensure category exists and sanitize input
    if category not in get_categories():
        category = config.DEFAULT_CATEGORY # Fallback
        logger.warning(f"User {user_id} selected invalid category '{category}', falling back to default.")
    
    video = get_random_video(category)
    if not video:
        logger.warning(f"No videos found in category '{category}' for user {user_id}.")
        await callback_query.answer("No videos in this category. Try another!", show_alert=True)
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
            reply_markup=video_nav_keyboard(video['uuid'], category, user_id) # Pass user_id for share button
        )
        
        if sent_success:
            save_history(user_id, video['uuid'], category)
            set_active_menu(user_id, sent_message_or_error.id, chat_id)
            await callback_query.message.delete()
            logger.info(f"User {user_id} selected category {category} and video {video['uuid']} sent.")
        else:
            logger.error(f"User {user_id} failed to send video after category selection: {sent_message_or_error}")
            await callback_query.message.edit_text(
                sent_message_or_error,
                reply_markup=category_keyboard()
            )
    except Exception as e:
        logger.error(f"User {user_id} error sending video after category selection: {e}", exc_info=True)
        await callback_query.answer("❌ Something went wrong. Please try again.", show_alert=True)

@app.on_callback_query(filters.regex(r"^next_(.+)_(.+)$"))
async def next_video(client: Client, callback_query: CallbackQuery):
    """Handles 'Next' video navigation."""
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id
    logger.info(f"User {user_id} requested next video.")
    try:
        _, current_uuid, category = callback_query.data.split('_')
        
        if await is_rate_limited(user_id):
            await callback_query.answer("⚠️ You're Browse too quickly. Please wait a minute and try again.", show_alert=True)
            logger.warning(f"User {user_id} hit rate limit in next_video.")
            return

        # Ensure category exists and sanitize input
        if category not in get_categories():
            category = config.DEFAULT_CATEGORY
            logger.warning(f"User {user_id} used invalid category '{category}' for next video, falling back to default.")

        video = get_random_video(category)
        
        if not video:
            logger.warning(f"No next video found in category '{category}' for user {user_id}.")
            await callback_query.answer("No videos in this category. Try another!", show_alert=True)
            return
        
        if not await is_menu_active(client, user_id, chat_id) or active_menus.get(user_id, {}).get('message_id') != callback_query.message.id:
            logger.warning(f"User {user_id} tried to navigate next but menu expired or not active/from incorrect message.")
            await callback_query.answer("Menu expired or not active. Please click Get Video to restart.", show_alert=True)
            return
        
        try:
            sent_success, sent_message_or_error = await send_video_with_auto_delete(
                client,
                chat_id,
                video,
                reply_markup=video_nav_keyboard(video['uuid'], category, user_id) # Pass user_id for share button
            )
            
            if sent_success:
                save_history(user_id, video['uuid'], category)
                set_active_menu(user_id, sent_message_or_error.id, chat_id)
                await callback_query.message.delete()
                logger.info(f"User {user_id} navigated to next video {video['uuid']} in category {category}.")
            else:
                logger.error(f"User {user_id} failed to send next video: {sent_message_or_error}")
                await callback_query.answer(sent_message_or_error, show_alert=True)
        except MessageIdInvalid:
            logger.warning(f"User {user_id} encountered MessageIdInvalid while sending next video, sending as new message.")
            # If edit fails, send as new message
            sent_success, sent_message_or_error = await send_video_with_auto_delete(
                client,
                chat_id,
                video,
                reply_markup=video_nav_keyboard(video['uuid'], category, user_id) # Pass user_id for share button
            )
            if sent_success:
                save_history(user_id, video['uuid'], category)
                set_active_menu(user_id, sent_message_or_error.id, chat_id)
                logger.info(f"User {user_id} sent next video {video['uuid']} as new message.")
            else:
                logger.error(f"User {user_id} failed to send next video as new message: {sent_message_or_error}")
                await callback_query.answer(sent_message_or_error, show_alert=True)
    except Exception as e:
        logger.error(f"User {user_id} error in next_video: {e}", exc_info=True)
        await callback_query.answer("Something went wrong. Please try again.", show_alert=True)

@app.on_callback_query(filters.regex(r"^prev_(.+)_(.+)$"))
async def prev_video(client: Client, callback_query: CallbackQuery):
    """Handles 'Previous' video navigation."""
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id
    logger.info(f"User {user_id} requested previous video.")
    try:
        _, current_uuid, _ = callback_query.data.split('_') # We extract current_uuid, category is just a hint here
        
        if await is_rate_limited(user_id):
            await callback_query.answer("⚠️ You're Browse too quickly. Please wait a minute and try again.", show_alert=True)
            logger.warning(f"User {user_id} hit rate limit in prev_video.")
            return

        history_doc = history_collection.find_one({'user_id': user_id})
        
        if not history_doc or not history_doc.get('history') or len(history_doc['history']) < 2:
            logger.warning(f"User {user_id} has no previous video history (or only one entry).")
            await callback_query.answer(
                "No previous videos available in your history. Try 'Get Video' to start!",
                show_alert=True
            )
            return
            
        history_entries = history_doc['history']
        
        # Find the previous distinct video in history
        found_video = None
        found_category = None
        for i in reversed(range(len(history_entries) - 1)): # Iterate backwards, excluding the current video
            prev_entry = history_entries[i]
            if prev_entry['video_uuid'] == current_uuid:
                continue # Skip the current video
            
            video = media_collection.find_one({'uuid': prev_entry['video_uuid']})
            if video:
                found_video = video
                found_category = prev_entry['category']
                break
        
        if not found_video:
            logger.warning(f"User {user_id} could not find any valid previous video in history.")
            await callback_query.answer(
                "Could not find any valid previous videos in your history. Some videos might have been deleted.",
                show_alert=True
            )
            return
            
        if not await is_menu_active(client, user_id, chat_id) or active_menus.get(user_id, {}).get('message_id') != callback_query.message.id:
            logger.warning(f"User {user_id} tried to navigate previous but menu expired or not active/from incorrect message.")
            await callback_query.answer("Menu expired or not active. Please click Get Video to restart.", show_alert=True)
            return
            
        try:
            await callback_query.message.delete()
            logger.info(f"User {user_id} deleted old menu message for previous video navigation.")
        except Exception as e:
            logger.error(f"User {user_id} failed to delete old menu message for prev_video: {e}")
        
        sent_success, sent_message_or_error = await send_video_with_auto_delete(
            client,
            chat_id,
            found_video,
            reply_markup=video_nav_keyboard(found_video['uuid'], found_category, user_id) # Pass user_id for share button
        )
        
        if sent_success:
            save_history(user_id, found_video['uuid'], found_category)
            set_active_menu(user_id, sent_message_or_error.id, chat_id)
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
async def change_category(client: Client, callback_query: CallbackQuery):
    """Handles 'Change Category' request."""
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id
    logger.info(f"User {user_id} requested to change category.")
    try:
        # Before showing categories, ensure no other menu is active from a different message
        if await is_menu_active(client, user_id, chat_id) and active_menus.get(user_id, {}).get('message_id') != callback_query.message.id:
            logger.warning(f"User {user_id} tried to change category but already has active menu from another message.")
            await callback_query.answer("You already have an active menu. Please use that one or wait for it to expire.", show_alert=True)
            return

        await callback_query.message.edit_text("🎬 <b>Choose a Category:</b>", reply_markup=category_keyboard())
        logger.info(f"User {user_id}: Change category menu sent.")
    except Exception as e:
        logger.error(f"User {user_id} failed to send change category menu: {e}", exc_info=True)
        await callback_query.answer("❌ Something went wrong. Please try again.", show_alert=True)

@app.on_message(filters.regex("^Profile$") & filters.private)
async def profile_btn(client: Client, message: Message):
    """Handles 'Profile' button click."""
    user_id = message.from_user.id
    logger.info(f"User {user_id} clicked Profile button.")
    try:
        await profile_cmd(client, message)
        logger.info(f"User {user_id}: Profile command triggered from button.")
    except Exception as e:
        logger.error(f"User {user_id} failed to trigger profile command from button: {e}", exc_info=True)
        await handle_error(client, message, e)

@app.on_message(filters.regex("^Refer & Earn$") & filters.private)
async def refer_btn(client: Client, message: Message):
    """Handles 'Refer & Earn' button click."""
    user_id = message.from_user.id
    logger.info(f"User {user_id} clicked Refer & Earn button.")
    
    try:
        if await is_rate_limited(user_id):
            await handle_error(client, message, FloodWait(10))
            logger.warning(f"User {user_id} hit rate limit in refer_btn.")
            return

        ref_link = f"https://t.me/{config.BOT_USERNAME[1:]}?start=ref_{user_id}"
        await message.reply(f"🔗 <b>Share & Earn!</b>\nWhen a new user joins through this link, you'll receive {config.REFERRAL_BONUS} token.\n\n<code>{html.escape(ref_link)}</code>", reply_markup=referral_keyboard(ref_link))
        logger.info(f"User {user_id}: Referral link sent successfully.")
    except Exception as e:
        logger.error(f"User {user_id} failed to send referral link: {e}", exc_info=True)
        await handle_error(client, message, e)

@app.on_message(filters.regex("^Buy Token$") & filters.private)
async def buy_token_btn(client: Client, message: Message):
    """Handles 'Buy Token' button click."""
    user_id = message.from_user.id
    logger.info(f"User {user_id} clicked Buy Token button.")
    try:
        await message.reply("Buy tokens from our support bot.", reply_markup=buy_token_keyboard())
        logger.info(f"User {user_id}: Buy token message sent successfully.")
    except Exception as e:
        logger.error(f"User {user_id} failed to send buy token message: {e}", exc_info=True)
        await handle_error(client, message, e)

@app.on_message(filters.regex("^Refresh Token$") & filters.private)
async def refresh_token_btn(client: Client, message: Message):
    """Handles 'Refresh Token' button click."""
    user_id = message.from_user.id
    logger.info(f"User {user_id} requested token refresh. Handler entered.")

    temp_msg = None
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

        user_mention_safe = html.escape(message.from_user.first_name) if message.from_user.first_name else "there"
        await message.reply_text(
            f"💡 <b>Information</b>\nHere are the details you requested...\n\n"
            f"Hey 💕 <b>{user_mention_safe}</b>\n\nYour Ads token is expired, refresh your token and try again.\n\n<b>Token Timeout:</b> 24 hour\n\n<b>What is token?</b>\nThis is an ads token. If you pass 1 ad, you can use the bot for 24 hour after passing the ad.\n\nAPPLE/IPHONE USERS COPY TOKEN LINK AND OPEN IN CHROME BROWSER",
            disable_web_page_preview = disable_preview,
            reply_markup=token_earning_keyboard(ad_url)
        )
        logger.info(f"User {user_id}: Refresh token message sent. Handler finished.")
    except Exception as e:
        logger.error(f"User {user_id} failed in refresh_token_btn: {e}", exc_info=True)
        if temp_msg:
            try:
                await temp_msg.delete()
                logger.info(f"User {user_id}: Deleted 'Please wait...' message due to error.")
            except Exception as delete_e:
                logger.warning(f"User {user_id}: Failed to delete 'Please wait...' message during error handling: {delete_e}")
        await handle_error(client, message, e)

async def send_token_earning_options(client: Client, message: Message):
    """Sends messages to a user detailing how to earn tokens."""
    user_id = message.from_user.id
    logger.info(f"User {user_id} is being sent token earning options.")
    try:
        if await is_rate_limited(user_id):
            await message.reply_text("⚠️ You're requesting token options too quickly. Please wait a minute and try again.")
            logger.warning(f"User {user_id} hit rate limit in send_token_earning_options.")
            return

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


@app.on_callback_query(filters.regex(r"^share_(.+)$"))
async def share_callback(client: Client, callback_query: CallbackQuery):
    """Handles 'Share' video callback to generate a shareable link with user_id."""
    user_id = callback_query.from_user.id
    video_uuid = callback_query.data.split('_', 1)[1]
    
    try:
        try:
            uuid.UUID(video_uuid) # Validate UUID format
        except ValueError:
            logger.warning(f"User {user_id} attempted to share with invalid UUID format: {video_uuid}.")
            await callback_query.answer("❌ Invalid video ID.", show_alert=True)
            return

        # The share link format: https://t.me/botname?start=video_UUID_USERID
        share_payload = f"video_{video_uuid}_{user_id}"
        share_link = f"https://t.me/{config.BOT_USERNAME[1:]}?start={share_payload}"
        
        await callback_query.answer()
        logger.info(f"User {user_id} requested share link for video {video_uuid}.")
        await callback_query.message.reply(
            f"🔗 <b>Share this video and earn!</b>\nWhen a new user joins through this link, you'll receive {config.REFERRAL_BONUS} token.\n\n<code>{html.escape(share_link)}</code>\n\nShare this link to new users only to get the token!",
            quote=True,
            disable_web_page_preview=True # Disable preview to make the link cleaner
        )
        logger.info(f"User {user_id}: Share link for video {video_uuid} sent successfully with referral data.")
    except Exception as e:
        logger.error(f"User {user_id} failed to send share link for video {video_uuid}: {e}", exc_info=True)
        await callback_query.answer("❌ Something went wrong. Please try again.", show_alert=True)


# --- Admin Commands ---
def format_size(size_bytes: int) -> str:
    """Converts bytes to a human-readable format (e.g., KB, MB, GB)."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} PB" # For extremely large files

@app.on_message(filters.command("broadcast") & filters.private & filters.user(config.ADMIN_IDS) & filters.reply)
async def broadcast_cmd(client: Client, message: Message):
    """Admin command to broadcast a replied message to all users."""
    user_id = message.from_user.id
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
                    f"Broadcasting...\n\n"
                    f"Progress: {success + blocked + failed}/{total_users}\n"
                    f"Successful: {success}\n"
                    f"Blocked Users: {blocked}\n"
                    f"Unsuccessful: {failed}"
                )
            await asyncio.sleep(0.5)
        
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
async def addcategory_cmd(client: Client, message: Message):
    """Admin command to add a new video category."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} requested to add category.")
    try:
        args = message.text.split(maxsplit=1) # Split only once to handle category names with spaces (if allowed by validate)
        if len(args) < 2:
            logger.warning(f"Admin {user_id} used addcategory with insufficient arguments.")
            await message.reply(
                "Usage: <code>/addcategory &lt;category_name&gt;</code>\n"
                "Category name can only contain letters, numbers, underscores, and hyphens."
            )
            return
        
        name = args[1]
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
async def deletecategory_cmd(client: Client, message: Message):
    """Admin command to delete a video category."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} requested to delete category.")
    try:
        categories = get_categories()
        if not categories:
            logger.warning(f"Admin {user_id} tried to delete category but no categories exist.")
            await message.reply_text("No categories to delete.")
            return

        buttons = []
        for category in categories:
            buttons.append([InlineKeyboardButton(html.escape(category), callback_data=f"confirmdelcat_{category}")])

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
async def confirm_delcat_callback(client: Client, callback_query: CallbackQuery):
    """Handles confirmation for category deletion."""
    user_id = callback_query.from_user.id
    category_raw = callback_query.data[14:] # Extract raw category name
    logger.info(f"Admin {user_id} confirmed deletion of category: {category_raw}.")
    try:
        if not is_admin(user_id):
            await callback_query.answer("❌ Not authorized.", show_alert=True)
            logger.warning(f"Non-admin user {user_id} attempted to confirm category deletion.")
            return
        
        category = category_raw # Use raw name for deletion since function validates it.

        logger.warning(f"Admin {user_id} is confirming deletion of category: {category}")

        success, msg, deleted_count = delete_category(category)
        
        if success:
            formatted_msg = f"✅ Category '{html.escape(category)}' deleted, and {deleted_count} videos removed permanently. Use /addcategory to create new categories."
            await callback_query.message.edit_text(formatted_msg)
            logger.info(f"Admin {user_id} successfully deleted category {category} with {deleted_count} videos.")
        else:
            await callback_query.answer(msg, show_alert=True)
            await callback_query.message.edit_text(f"Failed to delete category: {msg}") # Update message as well
            logger.error(f"Admin {user_id} failed to delete category {category}: {msg}")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to confirm category deletion: {e}", exc_info=True)
        await callback_query.answer("❌ An error occurred during category deletion. Please try again.", show_alert=True)

@app.on_message(filters.command("addtoken") & filters.private & filters.user(config.ADMIN_IDS))
async def addtoken_cmd(client: Client, message: Message):
    """Admin command to add tokens to a specific user."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} requested to add token.")
    try:
        args = message.text.split()
        if len(args) < 3:
            logger.warning(f"Admin {user_id} used addtoken with insufficient arguments: {message.text}")
            await message.reply("Usage: <code>/addtoken &lt;user_id&gt; &lt;count&gt;</code>")
            return
            
        target_user_id = int(args[1])
        count = int(args[2])
            
        if target_user_id <= 0:
            logger.warning(f"Admin {user_id} provided invalid target user ID: {target_user_id}.")
            await message.reply("User ID must be a positive integer.")
            return
                
        if count <= 0:
            logger.warning(f"Admin {user_id} provided invalid token count: {count}.")
            await message.reply("Token count must be a positive integer.")
            return
                
        if count > 100:  # Increased a reasonable limit
            logger.warning(f"Admin {user_id} attempted to add more than 100 tokens ({count}).")
            await message.reply("Cannot add more than 100 tokens at once.")
            return
                
        user = users_collection.find_one({'user_id': target_user_id})
        if not user:
            logger.warning(f"Admin {user_id} attempted to add tokens to non-existent user {target_user_id}.")
            await message.reply("User not found in database.")
            return
                
        successful_additions = 0
        for _ in range(count):
            added = add_token(target_user_id)
            if added:
                successful_additions += 1
            else:
                logger.error(f"Admin {user_id} failed to add one of {count} tokens to user {target_user_id}.")
                # Don't exit immediately, try to add remaining if possible
                
        if successful_additions == count:
            logger.info(f"Admin {user_id} added {count} tokens to user {target_user_id}.")
            await message.reply(f"Added {count} tokens to user {target_user_id}.")
        elif successful_additions > 0:
            logger.warning(f"Admin {user_id} partially added {successful_additions}/{count} tokens to user {target_user_id}.")
            await message.reply(f"Added {successful_additions} out of {count} tokens to user {target_user_id}. Some failed.")
        else:
            await message.reply("❌ Failed to add any tokens. Check logs for details.")
    except ValueError:
        logger.warning(f"Admin {user_id} provided invalid input for addtoken: {message.text}")
        await message.reply("User ID and count must be valid integers.")
    except Exception as e:
        logger.error(f"Admin {user_id} error adding tokens: {e}", exc_info=True)
        await message.reply("❌ Failed to add tokens. Please try again.")

# --- Batch Add Videos ---
batch_add_state = {}

@app.on_message(filters.command("batchadd") & filters.private & filters.user(config.ADMIN_IDS))
async def batchadd_cmd(client: Client, message: Message):
    """Admin command to enter batch video adding mode and select category."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} initiated batch add mode.")
    try:
        # Initialize default category if none exists
        if not get_categories():
            add_category(config.DEFAULT_CATEGORY)
            logger.info(f"Default category '{config.DEFAULT_CATEGORY}' created by admin {user_id}.")
        
        batch_add_state[user_id] = {
            'batch_mode': True,
            'current_category': None, # No default category set initially
            'count': 0
        }
        
        # Immediately prompt for category selection
        categories = get_categories()
        if not categories:
            await message.reply_text("⚠️ No categories available. Use /addcategory to create one before adding videos.")
            return
            
        buttons = []
        for category in categories:
            buttons.append([InlineKeyboardButton(html.escape(category), callback_data=f"setcat_{category}")])

        await message.reply_text(
            "Welcome to Batch Add Mode!\n\nPlease select a category to add videos to:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        logger.info(f"Admin {user_id}: Batch add mode enabled, prompting category selection.")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to initiate batch add mode: {e}", exc_info=True)
        await message.reply("❌ An error occurred while starting batch add mode. Please try again.")

@app.on_message(filters.command("done") & filters.private & filters.user(config.ADMIN_IDS))
async def done_cmd(client: Client, message: Message):
    """Admin command to exit batch video adding mode."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} exited batch add mode.")
    try:
        if user_id in batch_add_state and batch_add_state[user_id].get('batch_mode'):
            total_added = batch_add_state[user_id].get('count', 0)
            del batch_add_state[user_id] # Clear specific user's state
            await message.reply(f"Batch add mode disabled. Added {total_added} videos.")
            logger.info(f"Admin {user_id}: Batch add mode disabled. Total videos added: {total_added}.")
        else:
            await message.reply("You are not currently in batch add mode.")
            logger.warning(f"Admin {user_id} tried to use /done but not in batch mode.")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to disable batch add mode: {e}", exc_info=True)
        await message.reply("❌ An error occurred while ending batch add mode. Please try again.")

@app.on_message(filters.video & filters.private & filters.user(config.ADMIN_IDS))
async def handle_video_batch_add(client: Client, message: Message):
    """Handles incoming video messages for batch adding mode."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} sent a video for batch adding.")

    try: 
        if user_id not in batch_add_state or not batch_add_state[user_id].get('batch_mode'):
            logger.warning(f"Admin {user_id} sent video outside of batch add mode, ignoring.")
            return # Ignore if not in batch mode

        category = batch_add_state[user_id].get('current_category')
        if not category:
            logger.warning(f"Admin {user_id} tried to add video but no category selected in batch mode.")
            await message.reply_text("⚠️ No category selected for batch adding. Please select one using /category or start /batchadd again.")
            return

        is_valid_category, validation_msg = validate_category_name(category)
        if not is_valid_category: # This checks if the category name itself is valid, not if it exists
            await message.reply_text(f"❌ Invalid category '{html.escape(category)}' set in batch mode: {validation_msg}. Please select a valid category using /category.")
            logger.error(f"Admin {user_id} attempted to add video to invalid category name '{category}': {validation_msg}")
            return

        if category not in get_categories(): # Check if the category actually exists in DB
            await message.reply_text(f"❌ Category '{html.escape(category)}' does not exist. Please create it first with /addcategory or select an existing one with /category.")
            logger.error(f"Admin {user_id} attempted to add video to non-existent category '{category}'.")
            return

        if not message.video: # This filter should already handle this, but defensive programming
            logger.warning(f"Admin {user_id} sent non-video file in batch add mode.")
            await message.reply_text("❌ Please send a video file.")
            return

        file_id = message.video.file_id
        file_unique_id = message.video.file_unique_id
        file_size = message.video.file_size

        if media_collection.find_one({"file_unique_id": file_unique_id}):
            logger.warning(f"Admin {user_id} attempted to add duplicate video: {file_unique_id}.")
            await message.reply_text("⚠️ This video has already been added.")
            return

        video_uuid = str(uuid.uuid4())
        settings = settings_collection.find_one({'_id': 'settings'}) or {'protect_content': True, 'auto_delete': True}
        protect_content = settings.get('protect_content', True)

        try:
            forwarded_message = await client.send_video(
                chat_id=config.VIDEO_CHANNEL_ID,
                video=file_id,
                caption=f"Category: {html.escape(category)}\nSize: {format_size(file_size)}\nUUID: {video_uuid}",
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
            batch_add_state[user_id]['count'] = batch_add_state[user_id].get('count', 0) + 1
            logger.info(f"Video {video_uuid} (file ID: {file_id}) added to category {category} by admin {user_id}.")
            await message.reply_text(
                f"✅ File <code>{html.escape(message.video.file_name or 'unnamed_video')}</code> Added to <b>{html.escape(category)}</b>\n"
                f"📁 Category: {html.escape(category)}\n"
                f"📊 Size: {format_size(file_size)}\n"
                f"🆔 File ID: <code>{file_id}</code>\n"
                f"Videos added in this batch: {batch_add_state[user_id]['count']}"
            )
        except (ChannelInvalid, PeerIdInvalid) as e:
            logger.error(f"Admin {user_id} failed to send video to channel {config.VIDEO_CHANNEL_ID} due to invalid chat ID or permissions: {e}", exc_info=True)
            await message.reply_text(f"❌ Failed to send video to the channel. Error: Invalid channel ID or bot lacks permissions. Please check the `VIDEO_CHANNEL_ID` in config and ensure the bot is an admin with 'Post Messages' and 'Send Media' rights. Details: `{e}`")
        except BadRequest as e:
            logger.error(f"Admin {user_id} failed to send video due to bad request (e.g., file too large, invalid file, content protection issues): {e}", exc_info=True)
            error_message = str(e)
            if "file too large" in error_message.lower():
                await message.reply_text(f"❌ Failed to add video: The video file is too large. Telegram's limit is 2 GB. Details: `{error_message}`")
            elif "content protection" in error_message.lower():
                await message.reply_text(f"❌ Failed to add video: Issue with content protection. Ensure bot has necessary admin rights in the channel (e.g., 'Add Admins') or try disabling `protect_content`. Details: `{error_message}`")
            else:
                await message.reply_text(f"❌ Failed to add video due to a bad request. This might be an invalid file type or other Telegram API limitation. Details: `{error_message}`")
        except FloodWait as e:
            logger.warning(f"Admin {user_id} hit FloodWait while sending video: {e.value} seconds. Advising to wait.")
            await message.reply_text(f"⚠️ Telegram is asking me to slow down. Please wait {e.value} seconds before sending more videos.")
        except RPCError as e:
            logger.error(f"Admin {user_id} encountered an RPC error while sending video: {e}", exc_info=True)
            await message.reply_text(f"❌ Failed to add video due to a Telegram API (RPC) error. This is usually a temporary issue. Details: `{e}`")
        except Exception as e:
            logger.error(f"Admin {user_id} unhandled error adding video: {e}", exc_info=True)
            await message.reply_text(f"❌ Failed to add video due to an unexpected error. Please check logs and try again. Details: `{e}`")

    except Exception as e: # This is the missing except block for the outer try in handle_video_batch_add
        logger.error(f"Admin {user_id} error in handle_video_batch_add: {e}", exc_info=True)
        await message.reply("❌ An unexpected error occurred while processing your video. Please try again.")

@app.on_message(filters.command("category") & filters.private & filters.user(config.ADMIN_IDS))
async def set_category_cmd(client: Client, message: Message):
    """Admin command to set the current category for batch adding."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} requested to set category for batch add.")
    try: # Added try block here
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
            buttons.append([InlineKeyboardButton(html.escape(category), callback_data=f"setcat_{category}")])

        await message.reply_text(
            "Select a category for batch adding videos:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        logger.info(f"Admin {user_id}: Set category options sent.")
    except Exception as e: # Corresponding except block
        logger.error(f"Admin {user_id} failed to send set category options: {e}", exc_info=True)
        await message.reply("❌ An error occurred while preparing set category options. Please try again.")

@app.on_callback_query(filters.regex(r"^setcat_(.+)$"))
async def setcat_callback(client: Client, callback_query: CallbackQuery):
    """Handles callback for setting the batch add category."""
    user_id = callback_query.from_user.id
    logger.info(f"Admin {user_id} selected category for batch adding: {callback_query.data[7:]}.")
    try:
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
            await callback_query.answer(f"❌ Invalid category '{html.escape(category_name)}'.", show_alert=True)
            logger.warning(f"Admin {user_id} tried to set invalid category: '{category_name}'.")
            return

        batch_add_state[user_id]['current_category'] = category_name
        await callback_query.message.edit_text(f"✅ Category set to '<b>{html.escape(category_name)}</b>' for batch adding. Send videos now or use /done to finish.")
        await callback_query.answer(f"Category set to '{html.escape(category_name)}'") # Also answer the callback
        logger.info(f"Admin {user_id} successfully set batch category to '{category_name}'.")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to set batch category: {e}", exc_info=True)
        await callback_query.answer("❌ An error occurred while setting category. Please try again.", show_alert=True)

@app.on_message(filters.command("stats") & filters.private & filters.user(config.ADMIN_IDS))
async def stats_cmd(client: Client, message: Message):
    """Admin command to display bot statistics."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} requested stats.")
    try:
        total_users = users_collection.count_documents({})
        total_videos = media_collection.count_documents({})
        total_categories = categories_collection.count_documents({})
        await message.reply(f"<b>Total Users:</b> {total_users}\n<b>Total Videos:</b> {total_videos}\n<b>Total Categories:</b> {total_categories}")
        logger.info(f"Admin {user_id} retrieved stats: Users={total_users}, Videos={total_videos}, Categories={total_categories}.")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to retrieve stats: {e}", exc_info=True)
        await message.reply("❌ An error occurred while fetching stats. Please try again.")

# --- Auto-Delete & Protect Content Settings ---
@app.on_message(filters.command('toggle_auto_delete') & filters.private & filters.user(config.ADMIN_IDS))
async def toggle_auto_delete(client: Client, message: Message):
    """Admin command to toggle auto-deletion of sent videos."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} requested to toggle auto-delete.")
    try:
        s = settings_collection.find_one({'_id': 'settings'}) or {'auto_delete': True}
        new_status = not s.get('auto_delete', True)
        settings_collection.update_one({'_id': 'settings'}, {'$set': {'auto_delete': new_status}}, upsert=True)
        await message.reply(f"Auto-delete feature is now {'<b>enabled</b>' if new_status else '<b>disabled</b>'}.")
        logger.info(f"Admin {user_id} toggled auto-delete to {'enabled' if new_status else 'disabled'}.")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to toggle auto-delete: {e}", exc_info=True)
        await message.reply("❌ An error occurred while toggling auto-delete. Please try again.")

@app.on_message(filters.command('toggle_protect') & filters.private & filters.user(config.ADMIN_IDS))
async def toggle_protect(client: Client, message: Message):
    """Admin command to toggle content protection for sent videos."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} requested to toggle content protection.")
    try:
        s = settings_collection.find_one({'_id': 'settings'}) or {'protect_content': True}
        new_status = not s.get('protect_content', True)
        settings_collection.update_one({'_id': 'settings'}, {'$set': {'protect_content': new_status}}, upsert=True)
        await message.reply(f"Content protection is now {'<b>enabled</b>' if new_status else '<b>disabled</b>'}.")
        logger.info(f"Admin {user_id} toggled content protection to {'enabled' if new_status else 'disabled'}.")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to toggle content protection: {e}", exc_info=True)
        await message.reply("❌ An error occurred while toggling content protection. Please try again.")

# --- Database Cleanup ---
async def cleanup_expired_data():
    """Periodically cleans up expired tokens, old history entries, and expired active menus."""
    while True:
        try:
            now = datetime.utcnow()
            
            # Clean up expired tokens
            tokens_collection.update_many(
                {},
                {'$pull': {'tokens': {'expires_at': {'$lt': now}}}}
            )
            logger.info("Expired tokens cleanup completed.")
            
            # Clean up old history (older than 30 days if not handled by $slice)
            month_ago = now - timedelta(days=30)
            history_collection.update_many(
                {},
                {'$pull': {'history': {'viewed_at': {'$lt': month_ago}}}}
            )
            logger.info("Old history entries cleanup completed.")
            
            # Remove empty history documents (those with no entries left)
            history_collection.delete_many({'history': {'$size': 0}})
            logger.info("Empty history documents cleanup completed.")
            
            # Remove token documents with empty 'tokens' array
            tokens_collection.delete_many({'tokens': {'$size': 0}})
            logger.info("Empty token documents cleanup completed.")
            
            # Clean up expired active_menus from in-memory dictionary
            expired_users_menus = []
            for user_id_menu, menu_data in list(active_menus.items()): # Iterate over a copy
                if get_current_time() - menu_data['timestamp'] > config.MENU_TIMEOUT:
                    expired_users_menus.append((user_id_menu, menu_data.get('chat_id')))
            
            for user_id_to_clear, chat_id_to_clear in expired_users_menus:
                await cleanup_expired_menu(app, user_id_to_clear, chat_id_to_clear) # Pass app instance and chat_id
                logger.info(f"Cleaned up expired active menu for user {user_id_to_clear} from memory and attempted message deletion.")

            logger.info("Database and active_menus cleanup cycle completed.")
        except Exception as e:
            logger.error(f"Error in database cleanup task: {e}", exc_info=True)
        
        # Run every 24 hours
        await asyncio.sleep(86400) # 24 hours

async def verify_and_cleanup_media():
    """Periodically verifies if media files still exist in the channel and cleans up invalid entries."""
    while True:
        logger.info("Starting media verification and cleanup task.")
        try:
            # Wait until the client is started before proceeding
            while not app.is_connected:
                logger.info("Waiting for Pyrogram client to connect...")
                await asyncio.sleep(5) # Wait for 5 seconds before checking again

            all_media = list(media_collection.find({}))
            for media_item in all_media:
                video_uuid = media_item.get('uuid')
                message_id_in_channel = media_item.get('message_id')
                
                if not message_id_in_channel:
                    logger.warning(f"Media item {video_uuid} has no message_id in channel. Deleting from DB.")
                    media_collection.delete_one({'uuid': video_uuid})
                    continue

                try:
                    # Attempt to get the message from the channel
                    await app.get_messages(config.VIDEO_CHANNEL_ID, message_id_in_channel)
                except (MessageIdInvalid, ValueError):
                    logger.warning(f"Video {video_uuid} (message_id: {message_id_in_channel}) no longer exists in channel. Deleting from DB.")
                    media_collection.delete_one({'uuid': video_uuid})
                except Exception as e:
                    logger.error(f"Error verifying media {video_uuid} in channel {config.VIDEO_CHANNEL_ID}: {e}")

            logger.info("Media verification and cleanup task completed.")
        except Exception as e:
            logger.error(f"Error in media verification cleanup task: {e}", exc_info=True)
        
        # Run every 6 hours
        await asyncio.sleep(6 * 3600)

# --- Main ---
if __name__ == '__main__':
    logger.info("Bot starting...")
    # It's better to run Pyrogram client inside an async function
    # and then use asyncio.run() or loop.run_until_complete()
    # to run that async function.

    async def main():
        try:
            await app.start()
            logger.info("Pyrogram client started successfully.")
            
            # Now schedule the tasks since the client is connected
            asyncio.create_task(cleanup_expired_data())
            asyncio.create_task(verify_and_cleanup_media())
            
            # Keep the bot running indefinitely
            await app.idle() 
        except Exception as e:
            logger.critical(f"Fatal error during bot startup: {e}", exc_info=True)
        finally:
            if app.is_connected:
                await app.stop()
                logger.info("Pyrogram client stopped.")
            logger.info("Bot stopped.")

    # Run the main asynchronous function
    asyncio.run(main())

