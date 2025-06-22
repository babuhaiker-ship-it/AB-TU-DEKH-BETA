import os
import asyncio
import uuid
import base64
import random
import logging
from datetime import datetime, timedelta, timezone # Import timezone
from pyrogram import Client, filters
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, Message, InlineQueryResultArticle, InputTextMessageContent, CallbackQuery
)
from pyrogram.errors import (
    UserIsBlocked, ChatInvalid, MessageIdInvalid, FloodWait, RPCError, BadRequest, PeerIdInvalid, ChannelInvalid
)
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
    """Centralized configuration for the bot."""
    BOT_TOKEN = '7213744072:AAGBVd48RO44umuw3XZO-zVD6HX7ZYQzS84'
    API_ID = 29800015
    API_HASH = 'c8f37108be31ab9ea2818bfe533fbb6f'
    BOT_USERNAME = '@Spicynyraabot' # Ensure this starts with @
    MONGO_URI = 'mongodb+srv://Pyasipriya:00pEcao9sYhNC5VQ@cluster0.2dfenf7.mongodb.net/spicybot?retryWrites=true&w=majority&appName=Cluster0'
    MONGO_DB_NAME = 'spicybot'
    VIDEO_CHANNEL_ID = -1002621716446 # Ensure this is correct and bot is admin with posting rights
    BUY_BOT_URL = 'https://t.me/hanielxsupportbot'
    ADMIN_IDS = [6612030110] # List of admin user IDs
    URL_SHORTENER = 'https://api.linkshortify.com/st'
    SHORTENER_API_KEY = '5cd923c490f64017cffa6e3bb6cc724560a8cfc6'
    TUTORIAL_LINK_2 = 'https://t.me/urlshortenertutorial'
    TOKEN_EXPIRY = 86400  # 24 hours in seconds (1 token = 24 hours)
    DEFAULT_CATEGORY = 'default'

    # Customization options for token bonuses
    NEW_USER_TOKENS = 1
    REFERRAL_BONUS = 1
    REFRESH_BONUS = 1

    # Menu timeout for cleaning up inline menus
    MENU_TIMEOUT = 3600 # 1 hour in seconds

try:
    config = BotConfig()
    # Basic validation for essential configs
    if not all([config.BOT_TOKEN, config.API_ID, config.API_HASH, config.MONGO_URI, config.SHORTENER_API_KEY, config.BOT_USERNAME]):
        raise ValueError("One or more essential configuration variables are not set. Please check BOT_TOKEN, API_ID, API_HASH, MONGO_URI, SHORTENER_API_KEY, BOT_USERNAME.")
    if not config.BOT_USERNAME.startswith('@'):
        raise ValueError("BOT_USERNAME must start with '@'.")
    if not isinstance(config.VIDEO_CHANNEL_ID, int):
        raise ValueError("VIDEO_CHANNEL_ID must be an integer (e.g., -1001234567890).")
except Exception as e:
    logger.critical(f"Failed to load bot configuration: {e}")
    # Re-raise to prevent bot from starting with invalid config
    raise RuntimeError(f"Bot configuration error: {e}")

# --- MongoDB Setup ---
try:
    client = MongoClient(config.MONGO_URI)
    db = client[config.MONGO_DB_NAME]
    users_collection = db['users']
    tokens_collection = db['tokens']
    media_collection = db['media']
    history_collection = db['history']
    categories_collection = db['categories']
    settings_collection = db['settings']

    # Create indexes for efficient querying
    users_collection.create_index([("user_id", ASCENDING)], unique=True)
    tokens_collection.create_index([("user_id", ASCENDING)], unique=True)
    media_collection.create_index([("uuid", ASCENDING)], unique=True)
    media_collection.create_index([("category", ASCENDING)])
    media_collection.create_index([("file_unique_id", ASCENDING)], unique=True)
    media_collection.create_index([("size_bytes", ASCENDING)])
    history_collection.create_index([("history.viewed_at", ASCENDING)])
    history_collection.create_index([("user_id", ASCENDING)], unique=True)
    categories_collection.create_index([("name", ASCENDING)], unique=True)
    logger.info("MongoDB collections and indexes initialized.")
except Exception as e:
    logger.critical(f"Failed to connect to MongoDB or create indexes: {e}")
    raise RuntimeError(f"MongoDB connection error: {e}")

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
        logger.error(f"Failed to decode base64 string: {b64}. Error: {e}")
        return ""

def get_current_time() -> int:
    """Returns the current UTC timestamp as an integer."""
    # Use datetime.now(timezone.utc) for timezone-aware objects as recommended
    return int(datetime.now(timezone.utc).timestamp())

async def shorten_url(long_url: str) -> str:
    """Shortens a given URL using the configured URL shortener service."""
    logger.info(f"Attempting to shorten URL: {long_url}")
    try:
        async with aiohttp.ClientSession(timeout=ClientTimeout(total=10)) as session:
            async with session.post(config.URL_SHORTENER, json={
                'api': config.SHORTENER_API_KEY,
                'url': long_url
            }) as resp:
                logger.info(f"URL shortener API response status: {resp.status}")
                if resp.status == 200:
                    data = await resp.json()
                    if data and data.get('shortenedUrl'):
                        logger.info(f"URL shortened successfully to: {data['shortenedUrl']}")
                        return data['shortenedUrl']
                    else:
                        logger.warning(f"URL shortening API returned 200 but no shortenedUrl or invalid data: {data} for URL: {long_url}")
                else:
                    response_text = await resp.text()
                    logger.warning(f"URL shortening API returned non-200 status {resp.status} for {long_url}. Response: {response_text}")
        logger.warning(f"URL shortening failed for {long_url} after API call (no valid shortened URL).")
        return long_url # Fallback to original URL
    except aiohttp.ClientError as ce:
        logger.error(f"Aiohttp client error during URL shortening for {long_url}: {ce}", exc_info=True)
        return long_url # Fallback to original URL
    except Exception as e:
        logger.error(f"General error shortening URL {long_url}: {e}", exc_info=True)
        return long_url # Fallback to original URL

# --- Token Management ---
def get_valid_tokens(user_id: int) -> list:
    """Retrieves a list of valid (non-expired) tokens for a user."""
    doc = tokens_collection.find_one({'user_id': user_id})
    if not doc or not doc.get('tokens'):
        return []
    now = datetime.now(timezone.utc) # Use timezone-aware object
    # Filter tokens that have not expired
    return [t for t in doc['tokens'] if t['expires_at'] > now]

def add_token(user_id: int, duration_seconds: int = config.TOKEN_EXPIRY):
    """Adds a new token for a user with a specified duration."""
    now = datetime.now(timezone.utc) # Use timezone-aware object
    expires = now + timedelta(seconds=duration_seconds)
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
        logger.info(f"Token added for user {user_id}. Expires at: {expires}")
        return token
    except Exception as e:
        logger.error(f"Error adding token for user {user_id}: {e}", exc_info=True)
        return None

def get_and_cleanup_tokens(user_id: int) -> list:
    """Removes expired tokens from the database and returns the list of valid tokens."""
    now = datetime.now(timezone.utc) # Use timezone-aware object
    
    try:
        # Atomically remove expired tokens and fetch the updated document
        # $pull removes all elements from an array that match a specified condition
        updated_doc = tokens_collection.find_one_and_update(
            {'user_id': user_id},
            {'$pull': {'tokens': {'expires_at': {'$lt': now}}}},
            upsert=True, # Ensure the document exists or is created
            return_document=ReturnDocument.AFTER # Return the document after the update
        )
        
        # If after pulling, the tokens array is empty, we might want to clean up the document entirely
        # This is handled by the periodic cleanup, but can also be done here if needed.
        
        return updated_doc.get('tokens', []) if updated_doc else []
    except Exception as e:
        logger.error(f"Error cleaning up and fetching tokens for user {user_id}: {e}", exc_info=True)
        # Fallback to just finding if update fails
        doc = tokens_collection.find_one({'user_id': user_id})
        return doc.get('tokens', []) if doc else []

def user_has_token(user_id: int) -> bool:
    """Checks if a user has any valid tokens."""
    return len(get_and_cleanup_tokens(user_id)) > 0

# --- Referral System ---
def handle_referral(new_user_id: int, ref_code: str) -> int | None:
    """Handles a new user joining via a referral link, rewarding the referrer."""
    referrer_id = None
    if ref_code.startswith('ref_'):
        try:
            referrer_id = int(ref_code[4:])
        except ValueError:
            logger.warning(f"Invalid referrer ID format in ref_code: {ref_code}")
            return None
    elif ref_code.startswith('video_'): # Handle video share referrals
        try:
            # Format: video_[video_id]_[referrer_id]
            parts = ref_code.split('_')
            if len(parts) == 3:
                referrer_id = int(parts[2])
        except (ValueError, IndexError):
            logger.warning(f"Invalid referrer ID format or structure in video share ref_code: {ref_code}")
            return None

    if referrer_id and referrer_id != new_user_id:
        ref_user = users_collection.find_one({'user_id': referrer_id})
        if ref_user:
            add_token(referrer_id, config.REFERRAL_BONUS * 86400) # Give referrer a token (24 hours per bonus token)
            users_collection.update_one({'user_id': referrer_id}, {'$inc': {'referral_count': 1}}, upsert=True)
            users_collection.update_one({'user_id': new_user_id}, {'$set': {'referred_by': referrer_id}}, upsert=True)
            logger.info(f"User {new_user_id} successfully referred by {referrer_id}.")
            return referrer_id
    return None

# --- Category Management ---
def validate_category_name(name: str) -> tuple[bool, str]:
    """
    Validates a category name.
    Returns (is_valid, error_message)
    """
    if not name:
        return False, "Category name cannot be empty."
    if not re.match(r'^[a-zA-Z0-9_-]+$', name):
        return False, "Category name can only contain letters, numbers, underscores, and hyphens."
    if len(name) > 32:
        return False, "Category name cannot be longer than 32 characters."
    return True, ""

def get_categories() -> list[str]:
    """Gets all category names, ensuring the default category exists."""
    categories_cursor = categories_collection.find({})
    categories = [c['name'] for c in categories_cursor]
    
    # Ensure default category exists
    if config.DEFAULT_CATEGORY not in categories:
        add_category(config.DEFAULT_CATEGORY)
        # Re-fetch categories to include the newly added default category
        categories_cursor = categories_collection.find({})
        categories = [c['name'] for c in categories_cursor]
        logger.info(f"Ensured default category '{config.DEFAULT_CATEGORY}' exists.")
        
    return sorted(list(set(categories))) # Ensure unique and sorted

def add_category(name: str) -> tuple[bool, str]:
    """
    Adds a new category.
    Returns (success, message)
    """
    try:
        # Validate name format
        valid, error = validate_category_name(name)
        if not valid:
            return False, error
            
        # Check if category already exists (case-sensitive)
        if categories_collection.find_one({'name': name}):
            return False, f"Category '<b>{html.escape(name)}</b>' already exists."
            
        # Add category to database
        categories_collection.insert_one({
            'name': name,
            'created_at': datetime.now(timezone.utc) # Use timezone-aware object
        })
        logger.info(f"Category '{name}' added successfully.")
        return True, f"✅ Category '<b>{html.escape(name)}</b>' added successfully."
    except Exception as e:
        logger.error(f"Error adding category '{name}': {e}", exc_info=True)
        return False, "❌ Failed to add category. Please try again."

def delete_category(name: str) -> tuple[bool, str, int]:
    """
    Deletes a category and its associated videos.
    Returns (success, message, deleted_count)
    """
    try:
        # Prevent deleting the default category
        if name == config.DEFAULT_CATEGORY:
            return False, "❌ Cannot delete the default category.", 0
            
        # Check if category exists
        if not categories_collection.find_one({'name': name}):
            return False, f"❌ Category '<b>{html.escape(name)}</b>' does not exist.", 0
            
        # Delete all videos belonging to this category
        result = media_collection.delete_many({'category': name})
        deleted_count = result.deleted_count
        
        # Delete the category itself
        categories_collection.delete_one({'name': name})
        logger.info(f"Category '{name}' and {deleted_count} associated videos deleted.")
        return True, f"✅ Category '<b>{html.escape(name)}</b>' and {deleted_count} videos deleted permanently.", deleted_count
    except Exception as e:
        logger.error(f"Error deleting category '{name}': {e}", exc_info=True)
        return False, "❌ Failed to delete category. Please try again.", 0

# --- Video Navigation ---
def get_random_video(category: str) -> dict | None:
    """Retrieves a random video from the specified category."""
    # Find active videos (not banned) in the given category
    videos = list(media_collection.find({'category': category, 'banned': False}))
    if not videos:
        return None
    return random.choice(videos)

def get_video_by_uuid(uuid_: str) -> dict | None:
    """Retrieves a video by its UUID."""
    return media_collection.find_one({'uuid': uuid_})

def save_history(user_id: int, video_uuid: str, category: str):
    """Saves a video viewing entry to a user's history, limiting to the last 100 entries."""
    now = datetime.now(timezone.utc) # Use timezone-aware object
    entry = {'video_uuid': video_uuid, 'category': category, 'viewed_at': now}
    try:
        # Use $push with $slice to keep only the last 100 entries
        history_collection.update_one(
            {'user_id': user_id},
            {'$push': {'history': {'$each': [entry], '$slice': -100}}}, 
            upsert=True
        )
        logger.info(f"History saved for user {user_id}, video {video_uuid}. History limited to 100 entries.")
    except Exception as e:
        logger.error(f"Error saving history for user {user_id}, video {video_uuid}: {e}", exc_info=True)

def get_last_video(user_id: int) -> dict | None:
    """
    Retrieves the last viewed video from a user's history, excluding the *current* one.
    This effectively gets the video viewed *before* the current one.
    """
    doc = history_collection.find_one({'user_id': user_id})
    if doc and doc.get('history') and len(doc['history']) > 1:
        # Returns the second to last element, which is the previous video
        # The last element is the currently viewed video.
        return doc['history'][-2] 
    return None

# --- Menu State Management ---
# Stores active menu message IDs, their chat IDs, and timestamps for timeout
active_menus = {} 

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
    """
    Clean up an expired menu by deleting the message.
    Requires `client` and `chat_id` to perform message deletion.
    """
    try:
        menu = active_menus.get(user_id)
        if menu and menu.get('message_id') and chat_id:
            try:
                await client.delete_messages(chat_id, menu['message_id'])
                logger.info(f"Deleted expired menu message {menu['message_id']} for user {user_id} in chat {chat_id}")
            except MessageIdInvalid:
                logger.warning(f"Attempted to delete expired menu message {menu['message_id']} for user {user_id} in chat {chat_id}, but message was already deleted or invalid.")
            except Exception as e:
                logger.error(f"Failed to delete expired menu message {menu['message_id']} for user {user_id} in chat {chat_id}: {e}", exc_info=True)
        clear_active_menu(user_id)
    except Exception as e:
        logger.error(f"Error in cleanup_expired_menu for user {user_id}: {e}", exc_info=True)

async def is_menu_active(client: Client, user_id: int, chat_id: int) -> bool:
    """
    Check if a user has an active menu and clean up if expired.
    Returns True if an active, non-expired menu exists for the user.
    """
    if user_id not in active_menus:
        return False
        
    menu = active_menus[user_id]
    if get_current_time() - menu['timestamp'] > config.MENU_TIMEOUT:
        logger.info(f"Menu for user {user_id} expired. Attempting cleanup.")
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
        # This fallback should ideally not be hit if DEFAULT_CATEGORY is ensured
        return InlineKeyboardMarkup([[InlineKeyboardButton("No Categories Available", callback_data="no_cat")]])
    
    # Create buttons, escaping category names for display
    buttons = [[InlineKeyboardButton(html.escape(cat), callback_data=f"cat_{cat}")] for cat in cats]
    return InlineKeyboardMarkup(buttons)

def video_nav_keyboard(video_uuid: str, category: str, user_id: int) -> InlineKeyboardMarkup:
    """
    Keyboard for navigating between videos, including 'Previous', 'Next',
    'Change Category', and 'Share' buttons.
    The 'Share' button's deep link carries video ID and user ID for referral tracking.
    """
    # The actual share link is constructed on the fly when the share callback is triggered.
    # The callback_data only needs the video_uuid.
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Previous", callback_data=f"prev_{video_uuid}_{category}"),
            InlineKeyboardButton("Next", callback_data=f"next_{video_uuid}_{category}")
        ],
        [InlineKeyboardButton("Change Category", callback_data="change_cat")],
        [InlineKeyboardButton("Share", callback_data=f"share_{video_uuid}")] 
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
    
    # No token check here; it's handled in start_cmd before calling this.
    
    save_history(user_id, video_uuid, video['category'])
    return True, video

# --- Token Refresh ---
async def handle_token_refresh(user_id: int, ad_code: str) -> tuple[bool, str]:
    """
    Handles token refresh requests from users.
    Returns (success: bool, message: str)
    """
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
            logger.error(f"User {user_id} provided invalid token refresh code format: {decoded} from {ad_code}")
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
    except MessageIdInvalid:
        logger.warning(f"Could not auto-delete message {message.id} as it was already deleted or invalid.")
    except Exception as e:
        logger.error(f"Failed to auto-delete message {message.id}: {e}", exc_info=True)

async def send_video_with_auto_delete(client: Client, chat_id: int, video_data: dict, reply_markup: InlineKeyboardMarkup = None) -> tuple[bool, Message | str]:
    """
    Sends a video message with optional auto-delete and content protection.
    Returns (success: bool, sent_message: Message | error_message: str)
    """
    settings = settings_collection.find_one({'_id': 'settings'}) or {}
    protect_content = settings.get('protect_content', True)
    auto_delete = settings.get('auto_delete', True)
    
    try:
        sent_message = await client.send_video(
            chat_id,
            video_data['file_id'],
            caption=f"Category: {html.escape(video_data['category'])}",
            reply_markup=reply_markup,
            protect_content=protect_content
        )
        
        if auto_delete:
            asyncio.create_task(schedule_auto_delete(sent_message))
        
        return True, sent_message
    except (UserIsBlocked, ChatInvalid, PeerIdInvalid, ChannelInvalid) as e:
        logger.error(f"Failed to send video to chat {chat_id} due to chat/user issue: {e}", exc_info=True)
        return False, "❌ <b>Failed to send video.</b>\nIt seems I cannot send messages to this chat or the user has blocked me."
    except BadRequest as e:
        logger.error(f"Failed to send video to chat {chat_id} due to bad request: {e}", exc_info=True)
        error_message = str(e).lower()
        if "file too large" in error_message:
            return False, "❌ <b>Failed to send video.</b>\nThis video file is too large (Telegram limit is 2 GB)."
        elif "content protection" in error_message:
            return False, "❌ <b>Failed to send video.</b>\nIssue with content protection. Please contact support."
        return False, f"❌ <b>Failed to send video.</b>\nAn invalid request was made. Details: `{e}`"
    except FloodWait as e:
        logger.warning(f"FloodWait encountered when sending video to {chat_id}: {e.value} seconds.")
        return False, f"⚠️ <b>Too Many Requests!</b>\nPlease wait <b>{e.value}</b> seconds before trying again."
    except RPCError as e:
        logger.error(f"RPC error when sending video to {chat_id}: {e}", exc_info=True)
        return False, f"❌ <b>Failed to send video.</b>\nA Telegram server error occurred. Please try again later. Details: `{e}`"
    except Exception as e:
        logger.error(f"An unexpected error occurred sending video to chat {chat_id}: {e}", exc_info=True)
        return False, "❌ <b>An unexpected error occurred while sending the video.</b>\nPlease try again later."

# --- Rate Limiting ---
RATE_LIMIT_WINDOW = 60  # 60 seconds (1 minute)
RATE_LIMIT_MAX = 5     # Max 5 requests per minute

# Dictionary to store user request timestamps
# {user_id: [timestamp1, timestamp2, ...]}
user_request_timestamps = defaultdict(list)

async def is_rate_limited(user_id: int) -> bool:
    """
    Checks if a user is rate-limited based on their recent requests.
    This uses in-memory tracking for quick checks.
    """
    if is_admin(user_id):  # Admins are exempt from rate limiting
        return False
        
    now = datetime.now(timezone.utc).timestamp() # Use timezone-aware object
    
    # Clean up old timestamps outside the window
    user_request_timestamps[user_id] = [
        t for t in user_request_timestamps[user_id] if now - t < RATE_LIMIT_WINDOW
    ]
    
    # Add current request timestamp
    user_request_timestamps[user_id].append(now)
    
    if len(user_request_timestamps[user_id]) > RATE_LIMIT_MAX:
        logger.warning(f"User {user_id} is rate limited. Current requests: {len(user_request_timestamps[user_id])}, Max: {RATE_LIMIT_MAX}")
        return True
    return False

# --- Error Handling ---
async def handle_error(client: Client, message: Message | CallbackQuery, error: Exception):
    """Generic error handler for bot commands and callbacks."""
    if isinstance(error, FloodWait):
        logger.warning(f"FloodWait: {error.value} seconds for user {message.from_user.id}")
        await message.reply_text(f"⚠️ <b>Too Many Requests!</b>\nPlease wait <b>{error.value}</b> seconds before trying again.")
    elif isinstance(error, (UserIsBlocked, ChatInvalid, PeerIdInvalid, ChannelInvalid)):
        logger.warning(f"User {message.from_user.id} chat invalid or blocked: {error}")
        # No need to reply here, as the message might not go through
    elif isinstance(error, BadRequest):
        logger.error(f"BadRequest for user {message.from_user.id}: {error}", exc_info=True)
        await message.reply_text(f"❌ <b>A bad request was made.</b>\nThis usually means invalid parameters. Please try again or contact support if it persists. Details: `{error}`")
    elif isinstance(error, RPCError):
        logger.error(f"RPCError for user {message.from_user.id}: {error}", exc_info=True)
        await message.reply_text(f"❌ <b>A Telegram server error occurred.</b>\nPlease try again later. Details: `{error}`")
    else:
        logger.error(f"An unexpected error occurred for user {message.from_user.id}: {error}", exc_info=True)
        if isinstance(message, Message):
            await message.reply_text(f"❌ <b>An unexpected error occurred.</b>\nPlease try again later.")
        else: # CallbackQuery
            await message.answer("❌ An unexpected error occurred. Please try again later.", show_alert=True)

# --- Handlers ---
@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    username_safe = html.escape(message.from_user.username or "")
    first_name_safe = html.escape(message.from_user.first_name or "there")
    
    logger.info(f"User {user_id} issued /start command. Arguments: {message.text.split()}")

    if await is_rate_limited(user_id):
        await handle_error(client, message, FloodWait(config.RATE_LIMIT_WINDOW))
        return

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
            'joined_date': datetime.now(timezone.utc), # Use timezone-aware object
            'referral_count': 0
        })
        add_token(user_id, config.NEW_USER_TOKENS * 86400) # Give new user initial token (24 hours per token)
        logger.info(f"New user registered: {user_id} and received {config.NEW_USER_TOKENS} token.")

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

    # Handle welcome/referral messages for new users first, if applicable
    if is_new_user:
        if deep_link_type == 'referral':
            referrer_id = handle_referral(user_id, deep_link_data)
            if referrer_id:
                await message.reply(f"🥳 <b>Congratulations {first_name_safe}!</b> You have received {config.NEW_USER_TOKENS} token to continue.")
                try:
                    await client.send_message(referrer_id, f"🎉 <b>Referral Bonus!</b> Your friend, {first_name_safe}, joined through your link! You've received {config.REFERRAL_BONUS} token.")
                except Exception as e:
                    logger.error(f"Failed to send referral bonus message to {referrer_id}: {e}")
            else: # New user from referral link, but referrer not found/invalid
                await message.reply(f"👋 dear {first_name_safe} This is Spicy Nyraa Bot. To watch spicy content, click on the Get Video button. Need help? Tap /help.", reply_markup=await get_main_keyboard(user_id))
        elif deep_link_type == 'video_share' and referrer_id_from_video_link:
            # Handle referral bonus for video shares for new users
            referrer_id = handle_referral(user_id, deep_link_arg)
            await message.reply(f"🥳 <b>Congratulations {first_name_safe}!</b> You have received {config.NEW_USER_TOKENS} token to continue.")
            if referrer_id:
                try:
                    await client.send_message(referrer_id, f"🎉 <b>Referral Bonus!</b> Your friend, {first_name_safe}, joined through your shared video link! You've received {config.REFERRAL_BONUS} token.")
                except Exception as e:
                    logger.error(f"Failed to send video share referral bonus message to {referrer_id}: {e}")
        else: # New user, no specific deep link or invalid deep link
            await message.reply(f"👋 dear {first_name_safe} This is Spicy Nyraa Bot. To watch spicy content, click on the Get Video button. Need help? Tap /help.", reply_markup=await get_main_keyboard(user_id))
    elif not deep_link_type: # Returning user, no deep link
        await message.reply(f"👋 dear {first_name_safe} This is Spicy Nyraa Bot. To watch spicy content, click on the Get Video button. Need help? Tap /help.", reply_markup=await get_main_keyboard(user_id))

    # Now, handle the specific deep link action for both new and returning users
    if deep_link_type == 'token_refresh':
        success, msg = await handle_token_refresh(user_id, deep_link_data)
        await message.reply(msg, reply_markup=await get_main_keyboard(user_id))
        if success:
            logger.info(f"User {user_id} successfully processed token refresh from deep link.")
        else:
            logger.warning(f"User {user_id} failed to process token refresh from deep link: {msg}")

    elif deep_link_type == 'video_share':
        logger.info(f"User {user_id} attempting to view shared video {video_uuid_from_link}")
                    
        try:
            uuid.UUID(video_uuid_from_link) # Validate UUID format
        except ValueError:
            logger.warning(f"User {user_id} attempted to view shared video with invalid UUID format: {video_uuid_from_link}.")
            await message.reply("❌ Invalid video link format.", reply_markup=await get_main_keyboard(user_id))
            return # Exit handler

        # Check if video exists
        video_found_in_db = media_collection.find_one({'uuid': video_uuid_from_link})
        if not video_found_in_db:
            logger.warning(f"User {user_id} attempted to view non-existent shared video UUID {video_uuid_from_link}.")
            await message.reply("❌ Invalid video link.", reply_markup=await get_main_keyboard(user_id))
            return # Exit handler

        if not user_has_token(user_id):
            logger.info(f"User {user_id} needs a token to watch shared video {video_uuid_from_link}.")
            await message.reply("You need a token to watch this video. Please get a token first!", reply_markup=await get_main_keyboard(user_id))
            await send_token_earning_options(client, message)
            return # Exit handler, don't try to send video now
        else:
            # User has token, proceed to send the video.
            success, result_or_msg = await handle_shared_video(client, user_id, video_uuid_from_link)
            if not success:
                await message.reply(result_or_msg, reply_markup=await get_main_keyboard(user_id))
                return # Exit handler

            video = result_or_msg # Now `result_or_msg` is the video object if successful
            
            # If an old menu is active, attempt to delete it before sending the new one
            if await is_menu_active(client, user_id, message.chat.id):
                old_menu = active_menus.get(user_id)
                if old_menu and old_menu.get('chat_id') and old_menu.get('message_id'):
                    try:
                        await client.delete_messages(old_menu['chat_id'], old_menu['message_id'])
                        logger.info(f"Deleted old menu message {old_menu['message_id']} for user {user_id} before sending shared video.")
                    except Exception as e:
                        logger.warning(f"User {user_id} failed to delete old menu message {old_menu['message_id']}: {e}")
                clear_active_menu(user_id) # Ensure state is cleared after attempted deletion

            sent_success, sent_message_or_error = await send_video_with_auto_delete(
                client,
                message.chat.id,
                video,
                reply_markup=video_nav_keyboard(video['uuid'], video['category'], user_id)
            )
            if sent_success:
                set_active_menu(user_id, sent_message_or_error.id, message.chat.id)
                logger.info(f"User {user_id} sent shared video {video_uuid_from_link}.")
            else:
                await message.reply(sent_message_or_error, reply_markup=await get_main_keyboard(user_id))
    
    logger.info(f"Start command processed for user {user_id}.")


@app.on_message(filters.command("help") & filters.private)
async def help_cmd(client: Client, message: Message):
    """Handles the /help command."""
    user_id = message.from_user.id
    user_mention_safe = html.escape(message.from_user.first_name or "there")

    if await is_rate_limited(user_id):
        await handle_error(client, message, FloodWait(config.RATE_LIMIT_WINDOW))
        return

    logger.info(f"User {user_id} requested help.")
    await message.reply(
        f"👋 dear {user_mention_safe}, this is how to use Spicy Nyraa Bot:\n\n"
        "- Use <b>Get Video</b> to watch spicy content.\n"
        "- Each token gives you <b>24 hours</b> access.\n"
        "- Earn tokens by <b>referral</b>, <b>refreshing</b>, or <b>buying</b>.\n"
        "- Use <b>Profile</b> to check your stats and referral link.",
        reply_markup=await get_main_keyboard(user_id)
    )

@app.on_message(filters.command("profile") & filters.private)
async def profile_cmd(client: Client, message: Message):
    """Handles the /profile command to show user statistics."""
    user_id = message.from_user.id
    logger.info(f"User {user_id} requested profile.")
    
    if await is_rate_limited(user_id):
        await handle_error(client, message, FloodWait(config.RATE_LIMIT_WINDOW))
        return

    user = users_collection.find_one({'user_id': user_id})
    if not user:
        # This shouldn't happen often if start command handles new users, but as a fallback
        await message.reply("Your profile could not be found. Please try /start.")
        logger.warning(f"User {user_id} profile not found in DB during /profile command.")
        return

    tokens = get_and_cleanup_tokens(user_id)
    referral_count = user.get('referral_count', 0)
    referred_by = user.get('referred_by', None)
    
    views_doc = history_collection.find_one({'user_id': user_id})
    # Count only distinct videos for 'views' if desired, otherwise len(history) is fine.
    # For simplicity, len(history) is used as it tracks interactions.
    view_count = len(views_doc['history']) if views_doc and 'history' in views_doc else 0
    ref_link = f"https://t.me/{config.BOT_USERNAME[1:]}?start=ref_{user_id}"
    
    referrer_info = ""
    if referred_by:
        referrer_user = users_collection.find_one({'user_id': referred_by})
        if referrer_user:
            referrer_name = html.escape(referrer_user.get('first_name', f"User {referred_by}"))
            referrer_info = f"\n<b>Referred by:</b> {referrer_name} ({referred_by})"
        else:
            referrer_info = f"\n<b>Referred by:</b> {referred_by} (User Not Found)"

    await message.reply(
        f"👤 <b>Your Profile</b>\n\n"
        f"<b>Tokens:</b> {len(tokens)}\n"
        f"<b>Video Views:</b> {view_count}\n"
        f"<b>Referrals:</b> {referral_count}\n"
        f"<b>Referral Link:</b> <code>{html.escape(ref_link)}</code>"
        f"{referrer_info}",
        reply_markup=referral_keyboard(ref_link)
    )
    logger.info(f"User {user_id} profile details sent.")

@app.on_message(filters.regex("^Get Video$") & filters.private)
async def get_video(client: Client, message: Message):
    """Handles the 'Get Video' button request."""
    user_id = message.from_user.id
    chat_id = message.chat.id
    logger.info(f"User {user_id} requested Get Video.")
    
    if await is_rate_limited(user_id):
        await handle_error(client, message, FloodWait(config.RATE_LIMIT_WINDOW))
        return
        
    if not user_has_token(user_id):
        logger.info(f"User {user_id} has no tokens, prompting earning options.")
        await send_token_earning_options(client, message)
        return
    
    if await is_menu_active(client, user_id, chat_id):
        logger.warning(f"User {user_id} tried to open new menu but active menu already open in chat {chat_id}.")
        await message.reply("⚠️ <b>Menu Already Open</b>\nScroll up, your video menu is already open. If you can't find it, wait for it to expire or try pressing another button.")
        return
    
    cats = get_categories()
    if not cats: # This should ideally not happen if default category is always ensured
        add_category(config.DEFAULT_CATEGORY) # Re-ensure just in case
        cats = [config.DEFAULT_CATEGORY]
        logger.info(f"Default category '{config.DEFAULT_CATEGORY}' ensured for user {user_id} during Get Video.")
    
    logger.info(f"User {user_id} prompted to choose category for video.")
    await message.reply("🎬 <b>Choose a Category:</b>", reply_markup=category_keyboard())

@app.on_callback_query(filters.regex(r"^cat_(.+)"))
async def select_category(client: Client, callback_query: CallbackQuery):
    """Handles category selection callback."""
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id
    category = callback_query.data[4:] # Extract category from callback_data
    logger.info(f"User {user_id} selected category: '{category}'.")
    
    try:
        if await is_rate_limited(user_id):
            await callback_query.answer("⚠️ You're changing categories too quickly. Please wait a minute and try again.", show_alert=True)
            return
            
        # Check for active menu - only allow if no menu is active, or if the current message is the menu
        current_menu_message_id = active_menus.get(user_id, {}).get('message_id')
        if current_menu_message_id and current_menu_message_id != callback_query.message.id:
            logger.warning(f"User {user_id} tried to select category but already has active menu from another message {current_menu_message_id}.")
            await callback_query.answer("You already have an active menu. Please use that one or wait for it to expire.", show_alert=True)
            return

        # Ensure category exists and sanitize input (for display and logic)
        available_categories = get_categories()
        if category not in available_categories:
            category = config.DEFAULT_CATEGORY # Fallback to default if invalid/non-existent
            logger.warning(f"User {user_id} selected invalid category '{category}', falling back to default.")
            await callback_query.answer(f"Category '{html.escape(category)}' not found. Falling back to '{config.DEFAULT_CATEGORY}'.", show_alert=True)
        
        video = get_random_video(category)
        if not video:
            logger.warning(f"No videos found in category '{category}' for user {user_id}.")
            await callback_query.answer("No videos in this category. Try another!", show_alert=True)
            await callback_query.message.edit_text(
                "No videos in this category. Try another!",
                reply_markup=category_keyboard()
            )
            return
        
        sent_success, sent_message_or_error = await send_video_with_auto_delete(
            client,
            chat_id,
            video,
            reply_markup=video_nav_keyboard(video['uuid'], category, user_id)
        )
        
        if sent_success:
            save_history(user_id, video['uuid'], category)
            set_active_menu(user_id, sent_message_or_error.id, chat_id)
            try:
                await callback_query.message.delete() # Delete the category selection message
                logger.info(f"Deleted category selection message for user {user_id}.")
            except MessageIdInvalid:
                logger.warning(f"Failed to delete category selection message {callback_query.message.id} for user {user_id}: MessageIdInvalid.")
            logger.info(f"User {user_id} selected category {category} and video {video['uuid']} sent.")
        else:
            logger.error(f"User {user_id} failed to send video after category selection: {sent_message_or_error}")
            await callback_query.answer("❌ Failed to send video. Please try again.", show_alert=True)
            await callback_query.message.edit_text(
                sent_message_or_error, # Show error in place of categories
                reply_markup=category_keyboard() # Keep category selection open
            )
    except Exception as e:
        logger.error(f"User {user_id} error in select_category callback: {e}", exc_info=True)
        await callback_query.answer("❌ Something went wrong. Please try again.", show_alert=True)

@app.on_callback_query(filters.regex(r"^next_(.+)_(.+)$"))
async def next_video(client: Client, callback_query: CallbackQuery):
    """Handles 'Next' video navigation."""
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id
    
    try:
        # Extract current_uuid and category from callback_data
        parts = callback_query.data.split('_')
        if len(parts) != 3:
            logger.warning(f"User {user_id} received malformed next_video callback data: {callback_query.data}")
            await callback_query.answer("Invalid request. Please try again.", show_alert=True)
            return

        # current_uuid = parts[1] # Not strictly needed for 'next' but can be for debugging
        category = parts[2]
        logger.info(f"User {user_id} requested next video in category: '{category}'.")
        
        if await is_rate_limited(user_id):
            await callback_query.answer("⚠️ You're Browse too quickly. Please wait a minute and try again.", show_alert=True)
            return

        # Check for active menu and if the callback is from the *correct* message
        if not await is_menu_active(client, user_id, chat_id) or active_menus.get(user_id, {}).get('message_id') != callback_query.message.id:
            logger.warning(f"User {user_id} tried to navigate next but menu expired or not active/from incorrect message.")
            await callback_query.answer("Menu expired or not active. Please click Get Video to restart.", show_alert=True)
            return

        # Ensure category exists and sanitize input (for display and logic)
        if category not in get_categories():
            category = config.DEFAULT_CATEGORY # Fallback to default
            logger.warning(f"User {user_id} used invalid category '{category}' for next video, falling back to default.")
        
        video = get_random_video(category)
        
        if not video:
            logger.warning(f"No next video found in category '{category}' for user {user_id}.")
            await callback_query.answer("No more videos in this category. Try another!", show_alert=True)
            return
        
        # Delete the old video message before sending the new one
        try:
            await callback_query.message.delete()
            logger.info(f"Deleted old video message {callback_query.message.id} for user {user_id} before sending next video.")
        except MessageIdInvalid:
            logger.warning(f"Failed to delete old message {callback_query.message.id} for user {user_id} (MessageIdInvalid).")
        except Exception as e:
            logger.error(f"Error deleting old message {callback_query.message.id} for user {user_id}: {e}", exc_info=True)

        sent_success, sent_message_or_error = await send_video_with_auto_delete(
            client,
            chat_id,
            video,
            reply_markup=video_nav_keyboard(video['uuid'], category, user_id)
        )
        
        if sent_success:
            save_history(user_id, video['uuid'], category)
            set_active_menu(user_id, sent_message_or_error.id, chat_id) # Update active menu to the new message
            logger.info(f"User {user_id} navigated to next video {video['uuid']} in category {category}.")
        else:
            logger.error(f"User {user_id} failed to send next video: {sent_message_or_error}")
            await callback_query.answer(sent_message_or_error, show_alert=True)
            # If sending new video failed, clear active menu so user can restart
            clear_active_menu(user_id)
    except Exception as e:
        logger.error(f"User {user_id} error in next_video callback: {e}", exc_info=True)
        await callback_query.answer("❌ Something went wrong. Please try again.", show_alert=True)

@app.on_callback_query(filters.regex(r"^prev_(.+)_(.+)$"))
async def prev_video(client: Client, callback_query: CallbackQuery):
    """Handles 'Previous' video navigation."""
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id
    
    try:
        # Extract current_uuid from callback data to find the one before it
        parts = callback_query.data.split('_')
        if len(parts) != 3:
            logger.warning(f"User {user_id} received malformed prev_video callback data: {callback_query.data}")
            await callback_query.answer("Invalid request. Please try again.", show_alert=True)
            return
        current_video_uuid_in_menu = parts[1] # This is the UUID of the video currently displayed

        logger.info(f"User {user_id} requested previous video from current UUID: {current_video_uuid_in_menu}.")
        
        if await is_rate_limited(user_id):
            await callback_query.answer("⚠️ You're Browse too quickly. Please wait a minute and try again.", show_alert=True)
            return

        # Check for active menu and if the callback is from the *correct* message
        if not await is_menu_active(client, user_id, chat_id) or active_menus.get(user_id, {}).get('message_id') != callback_query.message.id:
            logger.warning(f"User {user_id} tried to navigate previous but menu expired or not active/from incorrect message.")
            await callback_query.answer("Menu expired or not active. Please click Get Video to restart.", show_alert=True)
            return

        history_doc = history_collection.find_one({'user_id': user_id})
        
        if not history_doc or not history_doc.get('history'):
            logger.warning(f"User {user_id} has no history for previous video navigation.")
            await callback_query.answer("No previous videos available in your history. Try 'Get Video' to start!", show_alert=True)
            return
            
        history_entries = history_doc['history']
        
        # Find the index of the current video in history
        current_video_index = -1
        for i, entry in enumerate(reversed(history_entries)):
            if entry['video_uuid'] == current_video_uuid_in_menu:
                current_video_index = len(history_entries) - 1 - i
                break

        if current_video_index == -1:
            logger.warning(f"User {user_id} current video {current_video_uuid_in_menu} not found in history for previous navigation.")
            await callback_query.answer("Could not find the current video in your history. Please try 'Next' or 'Change Category'.", show_alert=True)
            return

        # Find the previous *distinct* video in history
        found_video = None
        found_category = None
        # Iterate backwards from the element before the current one
        for i in reversed(range(current_video_index)):
            prev_entry = history_entries[i]
            # Ensure it's not the same as the current video being viewed (if somehow duplicated in history)
            if prev_entry['video_uuid'] == current_video_uuid_in_menu:
                continue 
            
            video_from_db = media_collection.find_one({'uuid': prev_entry['video_uuid'], 'banned': False})
            if video_from_db:
                found_video = video_from_db
                found_category = prev_entry['category']
                break
        
        if not found_video:
            logger.warning(f"User {user_id} could not find any valid previous video in history before {current_video_uuid_in_menu}.")
            await callback_query.answer(
                "Could not find any valid previous videos in your history. Some videos might have been deleted or banned.",
                show_alert=True
            )
            return
            
        # Delete the old video message before sending the new one
        try:
            await callback_query.message.delete()
            logger.info(f"Deleted old video message {callback_query.message.id} for user {user_id} before sending previous video.")
        except MessageIdInvalid:
            logger.warning(f"Failed to delete old message {callback_query.message.id} for user {user_id} (MessageIdInvalid).")
        except Exception as e:
            logger.error(f"Error deleting old message {callback_query.message.id} for user {user_id}: {e}", exc_info=True)
        
        sent_success, sent_message_or_error = await send_video_with_auto_delete(
            client,
            chat_id,
            found_video,
            reply_markup=video_nav_keyboard(found_video['uuid'], found_category, user_id)
        )
        
        if sent_success:
            save_history(user_id, found_video['uuid'], found_category) # Save the new (previous) view to history
            set_active_menu(user_id, sent_message_or_error.id, chat_id) # Update active menu to the new message
            logger.info(f"User {user_id} navigated to previous video {found_video['uuid']} in category {found_category}.")
        else:
            logger.error(f"User {user_id} failed to send previous video: {sent_message_or_error}")
            await callback_query.answer(sent_message_or_error, show_alert=True)
            clear_active_menu(user_id) # Clear active menu if sending new video failed
    except Exception as e:
        logger.error(f"User {user_id} error in prev_video callback: {e}", exc_info=True)
        await callback_query.answer(
            "❌ An unexpected error occurred while trying to go to the previous video. Please try again.",
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
        current_menu_message_id = active_menus.get(user_id, {}).get('message_id')
        if current_menu_message_id and current_menu_message_id != callback_query.message.id:
            logger.warning(f"User {user_id} tried to change category but already has active menu from another message {current_menu_message_id}.")
            await callback_query.answer("You already have an active menu. Please use that one or wait for it to expire.", show_alert=True)
            return

        categories = get_categories()
        if not categories:
            await callback_query.answer("No categories available. Please try again later.", show_alert=True)
            logger.warning(f"User {user_id} attempted to change category but no categories found.")
            return

        await callback_query.message.edit_text("🎬 <b>Choose a Category:</b>", reply_markup=category_keyboard())
        await callback_query.answer("Choose a category.") # Acknowledge the callback
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
            await handle_error(client, message, FloodWait(config.RATE_LIMIT_WINDOW))
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
        await message.reply("🛍️ Buy tokens from our support bot:", reply_markup=buy_token_keyboard())
        logger.info(f"User {user_id}: Buy token message sent successfully.")
    except Exception as e:
        logger.error(f"User {user_id} failed to send buy token message: {e}", exc_info=True)
        await handle_error(client, message, e)

@app.on_message(filters.regex("^Refresh Token$") & filters.private)
async def refresh_token_btn(client: Client, message: Message):
    """Handles 'Refresh Token' button click."""
    user_id = message.from_user.id
    logger.info(f"User {user_id} requested token refresh.")

    temp_msg = None
    try:
        if await is_rate_limited(user_id):
            await message.reply_text("⚠️ You're refreshing too quickly. Please wait a minute and try again.")
            return

        temp_msg = await message.reply("Please wait while I prepare your refresh link...")
        logger.info(f"User {user_id}: 'Please wait...' message sent. Checking for existing token.")

        if user_has_token(user_id):
            if temp_msg: await temp_msg.delete()
            await message.reply("💡 You already have an active token. No need to refresh yet!")
            logger.info(f"User {user_id} attempted token refresh but already has valid tokens. Exiting.")
            return

        logger.info(f"User {user_id}: User does not have valid token. Generating ad_code and attempting to shorten URL.")
        # The timestamp in ad_code defines when the *ad link itself* expires, not the token.
        # It's a security measure to prevent indefinite use of old refresh links.
        ad_code = str_to_b64(f"{user_id}:{get_current_time() + config.TOKEN_EXPIRY}") # Link valid for TOKEN_EXPIRY seconds
        long_url = f"https://telegram.dog/{config.BOT_USERNAME[1:]}?start=token_{ad_code}"
        ad_url = await shorten_url(long_url)
        logger.info(f"User {user_id}: shorten_url call completed. Result: {ad_url}")
        
        if temp_msg: await temp_msg.delete()

        disable_preview = False
        # If URL shortening failed, the ad_url will be the long Telegram link.
        # Disable web page preview for these internal Telegram deep links.
        if ad_url.startswith(f"https://telegram.dog/{config.BOT_USERNAME[1:]}"):
            logger.warning(f"User {user_id} URL shortening failed for refresh_token_btn. Using long URL: {ad_url}")
            disable_preview = True 

        user_mention_safe = html.escape(message.from_user.first_name or "there")
        await message.reply_text(
            f"💡 <b>Information</b>\nHere are the details you requested...\n\n"
            f"Hey 💕 <b>{user_mention_safe}</b>\n\nYour Ads token might be expired. Refresh your token by clicking the button below.\n\n"
            f"<b>Token Timeout:</b> 24 hours per refresh token\n\n"
            f"<b>What is a token?</b>\nThis is an ads token. If you pass 1 ad, you can use the bot for 24 hours after passing the ad.\n\n"
            f"<b>APPLE/IPHONE USERS:</b> Copy the token link and open it in Chrome browser (or any other external browser).",
            disable_web_page_preview=disable_preview,
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
            return

        ad_code = str_to_b64(f"{user_id}:{get_current_time() + config.TOKEN_EXPIRY}")
        long_url = f"https://telegram.dog/{config.BOT_USERNAME[1:]}?start=token_{ad_code}"
        ad_url = await shorten_url(long_url)
        
        disable_preview = False
        if ad_url.startswith(f"https://telegram.dog/{config.BOT_USERNAME[1:]}"):
            disable_preview = True

        await message.reply(
            "❌ <b>No Tokens Left!</b>\nUse any of these methods to gain tokens:\n\n"
            f"<b>Token Timeout:</b> 24 hours per refresh token\n\n"
            f"<b>What is a token?</b>\nThis is an ads token. If you pass 1 ad, you can use the bot for 24 hours after passing the ad.\n\n"
            f"<b>APPLE/IPHONE USERS:</b> Copy the token link and open it in Chrome browser (or any other external browser).",
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
    logger.info(f"User {user_id} requested share link for video {video_uuid}.")
    
    try:
        if await is_rate_limited(user_id):
            await callback_query.answer("⚠️ You're requesting too quickly. Please wait a minute and try again.", show_alert=True)
            return

        try:
            uuid.UUID(video_uuid) # Validate UUID format
        except ValueError:
            logger.warning(f"User {user_id} attempted to share with invalid UUID format: {video_uuid}.")
            await callback_query.answer("❌ Invalid video ID.", show_alert=True)
            return

        # The share link format: https://t.me/botname?start=video_UUID_USERID
        share_payload = f"video_{video_uuid}_{user_id}"
        share_link = f"https://t.me/{config.BOT_USERNAME[1:]}?start={share_payload}"
        
        await callback_query.answer("Share link generated!") # Acknowledge the callback

        await callback_query.message.reply(
            f"🔗 <b>Share this video and earn!</b>\nWhen a <b>new user</b> joins through this link, you'll receive {config.REFERRAL_BONUS} token.\n\n<code>{html.escape(share_link)}</code>\n\nShare this link to <b>new users only</b> to get the token!",
            quote=True, # Reply to the message containing the share button
            disable_web_page_preview=True # Disable preview to make the link cleaner
        )
        logger.info(f"User {user_id}: Share link for video {video_uuid} sent successfully with referral data.")
    except Exception as e:
        logger.error(f"User {user_id} failed to send share link for video {video_uuid}: {e}", exc_info=True)
        await callback_query.answer("❌ Something went wrong. Please try again.", show_alert=True)

# --- Admin Commands ---
def format_size(size_bytes: int) -> str:
    """Converts bytes to a human-readable format (e.g., KB, MB, GB)."""
    if size_bytes is None:
        return "N/A"
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

    if not replied_message:
        await message.reply("❌ Please reply to the message you want to broadcast.")
        return

    try:
        users = list(users_collection.find({}, {'user_id': 1}))
        total_users = len(users)
        
        if total_users == 0:
            await message.reply("ℹ️ No users found in the database to broadcast to.")
            return

        broadcast_msg = await message.reply(f"📣 <b>Broadcasting</b> to <b>{total_users}</b> users...")
        logger.info(f"Admin {user_id} initiating broadcast to {total_users} users.")
        
        success_count = 0
        blocked_count = 0
        failed_count = 0
        
        for user_doc in users:
            target_user_id = user_doc['user_id']
            try:
                await replied_message.copy(target_user_id)
                success_count += 1
            except UserIsBlocked:
                blocked_count += 1
                logger.info(f"User {target_user_id} blocked the bot during broadcast.")
            except (ChatInvalid, PeerIdInvalid, ChannelInvalid):
                failed_count += 1
                logger.error(f"Invalid chat/peer ID for user {target_user_id} during broadcast.")
            except FloodWait as e:
                logger.warning(f"User {target_user_id} hit FloodWait during broadcast: {e.value} seconds. Pausing broadcast.")
                await asyncio.sleep(e.value + 1) # Wait a bit longer than required
                try:
                    await replied_message.copy(target_user_id)
                    success_count += 1
                    logger.info(f"Broadcast retry successful for user {target_user_id}.")
                except Exception as retry_e:
                    failed_count += 1
                    logger.error(f"Broadcast retry failed for user {target_user_id}: {retry_e}")
            except Exception as e:
                failed_count += 1
                logger.error(f"Broadcast failed for user {target_user_id}: {e}")
            
            # Update progress message periodically
            if (success_count + blocked_count + failed_count) % 25 == 0 or (success_count + blocked_count + failed_count) == total_users:
                try:
                    await broadcast_msg.edit_text(
                        f"📣 <b>Broadcasting in progress...</b>\n\n"
                        f"<b>Progress:</b> {success_count + blocked_count + failed_count}/{total_users}\n"
                        f"<b>Successful:</b> {success_count}\n"
                        f"<b>Blocked Users:</b> {blocked_count}\n"
                        f"<b>Failed:</b> {failed_count}"
                    )
                except MessageIdInvalid:
                    logger.warning(f"Broadcast progress message {broadcast_msg.id} could not be updated (MessageIdInvalid).")
                except Exception as edit_e:
                    logger.error(f"Error updating broadcast progress message: {edit_e}")
            await asyncio.sleep(0.1) # Small delay to avoid hitting limits for the bot itself
        
        await broadcast_msg.edit_text(
            f"✅ <b>Broadcast Completed!</b>\n\n"
            f"<b>Total Users:</b> {total_users}\n"
            f"<b>Successful:</b> {success_count}\n"
            f"<b>Blocked Users:</b> {blocked_count}\n"
            f"<b>Failed:</b> {failed_count}"
        )
        logger.info(f"Broadcast completed by admin {user_id}. Success: {success_count}, Blocked: {blocked_count}, Failed: {failed_count}.")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to complete broadcast: {e}", exc_info=True)
        if broadcast_msg:
            try:
                await broadcast_msg.edit_text("❌ An error occurred during broadcast. Check logs for details.")
            except Exception as edit_e:
                logger.error(f"Error updating broadcast error message: {edit_e}")
        else:
            await message.reply("❌ An error occurred during broadcast. Check logs for details.")

@app.on_message(filters.command("addcategory") & filters.private & filters.user(config.ADMIN_IDS))
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
                "Category name can only contain letters, numbers, underscores, and hyphens."
            )
            return
        
        name = args[1].strip() # Strip whitespace
        success, msg = add_category(name)
        await message.reply(msg) # Reply with the success/failure message from add_category
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
        # Filter out the default category from the deletion list
        deletable_categories = [c for c in categories if c != config.DEFAULT_CATEGORY]

        if not deletable_categories:
            logger.warning(f"Admin {user_id} tried to delete category but no deletable categories exist.")
            await message.reply_text("ℹ️ No categories available to delete (or only the default category exists).")
            return

        buttons = []
        for category in deletable_categories:
            buttons.append([InlineKeyboardButton(html.escape(category), callback_data=f"confirmdelcat_{category}")])

        await message.reply_text(
            """⚠️ <b>Select a category to delete:</b>\n\nAll videos in the selected category will be deleted permanently. <b>This action cannot be undone.</b> Click on a category name below to confirm deletion.""",
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
    category_to_delete = callback_query.data[14:] # Extract raw category name
    logger.info(f"Admin {user_id} confirmed deletion of category: '{category_to_delete}'.")
    
    try:
        if not is_admin(user_id):
            await callback_query.answer("❌ Not authorized.", show_alert=True)
            return
        
        # Double check to prevent deleting default category, even if button wasn't shown
        if category_to_delete == config.DEFAULT_CATEGORY:
            await callback_query.answer("❌ Cannot delete the default category.", show_alert=True)
            await callback_query.message.edit_text("❌ Cannot delete the default category.")
            logger.warning(f"Admin {user_id} attempted to delete default category via callback.")
            return

        success, msg, deleted_count = delete_category(category_to_delete)
        
        if success:
            formatted_msg = f"✅ Category '<b>{html.escape(category_to_delete)}</b>' deleted, and {deleted_count} videos removed permanently. Use /addcategory to create new categories."
            await callback_query.message.edit_text(formatted_msg)
            logger.info(f"Admin {user_id} successfully deleted category '{category_to_delete}' with {deleted_count} videos.")
        else:
            await callback_query.answer(msg, show_alert=True)
            await callback_query.message.edit_text(f"❌ Failed to delete category: {msg}") # Update message as well
            logger.error(f"Admin {user_id} failed to delete category '{category_to_delete}': {msg}")
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
            
        try:
            target_user_id = int(args[1])
            count = int(args[2])
        except ValueError:
            await message.reply("User ID and count must be valid integers.")
            logger.warning(f"Admin {user_id} provided non-integer input for addtoken: {message.text}")
            return
            
        if target_user_id <= 0:
            logger.warning(f"Admin {user_id} provided invalid target user ID: {target_user_id}.")
            await message.reply("User ID must be a positive integer.")
            return
                
        if count <= 0:
            logger.warning(f"Admin {user_id} provided invalid token count: {count}.")
            await message.reply("Token count must be a positive integer.")
            return
                
        if count > 100:  # Set a reasonable limit for bulk addition
            logger.warning(f"Admin {user_id} attempted to add more than 100 tokens ({count}).")
            await message.reply("Cannot add more than 100 tokens at once to prevent abuse or errors. Please use a smaller count.")
            return
                
        user_exists = users_collection.find_one({'user_id': target_user_id})
        if not user_exists:
            logger.warning(f"Admin {user_id} attempted to add tokens to non-existent user {target_user_id}.")
            await message.reply("User not found in database. Please ensure the user has started the bot at least once.")
            return
                
        successful_additions = 0
        for _ in range(count):
            added = add_token(target_user_id, config.TOKEN_EXPIRY) # Add full 24-hour tokens
            if added:
                successful_additions += 1
            else:
                logger.error(f"Admin {user_id} failed to add one of {count} tokens to user {target_user_id}.")
                # Continue loop, but log the failure
                
        if successful_additions == count:
            logger.info(f"Admin {user_id} added {count} tokens to user {target_user_id}.")
            await message.reply(f"✅ Added {count} tokens to user <b>{target_user_id}</b>.")
        elif successful_additions > 0:
            logger.warning(f"Admin {user_id} partially added {successful_additions}/{count} tokens to user {target_user_id}.")
            await message.reply(f"⚠️ Added {successful_additions} out of {count} tokens to user <b>{target_user_id}</b>. Some failed due to an internal error.")
        else:
            await message.reply("❌ Failed to add any tokens. Check logs for details.")
    except Exception as e:
        logger.error(f"Admin {user_id} error adding tokens: {e}", exc_info=True)
        await message.reply("❌ Failed to add tokens due to an unexpected error. Please try again.")

# --- Batch Add Videos ---
# State for admin's batch video adding mode
batch_add_state = {} # {user_id: {'batch_mode': bool, 'current_category': str | None, 'count': int}}

@app.on_message(filters.command("batchadd") & filters.private & filters.user(config.ADMIN_IDS))
async def batchadd_cmd(client: Client, message: Message):
    """Admin command to enter batch video adding mode and select category."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} initiated batch add mode.")
    try:
        # Initialize default category if none exists
        if not get_categories():
            # This call already logs if it's added.
            add_category(config.DEFAULT_CATEGORY) 
        
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
            "🚀 <b>Welcome to Batch Add Mode!</b>\n\nPlease select a category to add videos to. Once a category is set, simply send videos to me.",
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
            await message.reply(f"✅ Batch add mode disabled. Added <b>{total_added}</b> videos.")
            logger.info(f"Admin {user_id}: Batch add mode disabled. Total videos added: {total_added}.")
        else:
            await message.reply("ℹ️ You are not currently in batch add mode.")
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
            logger.warning(f"Admin {user_id} sent video outside of batch add mode, ignoring and informing.")
            await message.reply_text("ℹ️ You are not in batch add mode. Use /batchadd to start adding videos.")
            return

        category = batch_add_state[user_id].get('current_category')
        if not category:
            logger.warning(f"Admin {user_id} tried to add video but no category selected in batch mode.")
            await message.reply_text("⚠️ No category selected for batch adding. Please select one using /category or start /batchadd again.")
            return

        # Ensure the selected category actually exists in DB (even if name is valid)
        if category not in get_categories(): 
            await message.reply_text(f"❌ Category '<b>{html.escape(category)}</b>' does not exist. Please create it first with /addcategory or select an existing one with /category.")
            logger.error(f"Admin {user_id} attempted to add video to non-existent category '{category}'.")
            return

        if not message.video: 
            # This check is somewhat redundant with filters.video but good for defensive programming
            logger.warning(f"Admin {user_id} sent non-video file but filters passed it. Message ID: {message.id}.")
            await message.reply_text("❌ Please send a video file.")
            return

        file_id = message.video.file_id
        file_unique_id = message.video.file_unique_id
        file_size = message.video.file_size
        file_name = message.video.file_name or "unnamed_video"

        if media_collection.find_one({"file_unique_id": file_unique_id}):
            logger.warning(f"Admin {user_id} attempted to add duplicate video (file_unique_id: {file_unique_id}).")
            await message.reply_text("⚠️ This video has already been added.")
            return

        video_uuid = str(uuid.uuid4())
        settings = settings_collection.find_one({'_id': 'settings'}) or {'protect_content': True, 'auto_delete': True}
        protect_content = settings.get('protect_content', True)

        try:
            forwarded_message = await client.send_video(
                chat_id=config.VIDEO_CHANNEL_ID,
                video=file_id,
                caption=f"Category: <b>{html.escape(category)}</b>\nSize: <b>{format_size(file_size)}</b>\nUUID: <code>{video_uuid}</code>",
                protect_content=protect_content
            )
            message_id_in_channel = forwarded_message.id

            video_data = {
                "uuid": video_uuid,
                "file_id": file_id,
                "file_unique_id": file_unique_id,
                "category": category,
                "size_bytes": file_size,
                "timestamp": get_current_time(), # Store as Unix timestamp for easier comparison if needed
                "message_id": message_id_in_channel,
                "banned": False # Default to not banned
            }
            media_collection.insert_one(video_data)
            batch_add_state[user_id]['count'] = batch_add_state[user_id].get('count', 0) + 1
            logger.info(f"Video {video_uuid} (file_unique_id: {file_unique_id}) added to category '{category}' by admin {user_id}.")
            await message.reply_text(
                f"✅ File <code>{html.escape(file_name)}</code> Added to <b>{html.escape(category)}</b>\n"
                f"📁 Category: <b>{html.escape(category)}</b>\n"
                f"📊 Size: <b>{format_size(file_size)}</b>\n"
                f"🆔 File ID: <code>{file_id}</code>\n"
                f"Videos added in this batch: <b>{batch_add_state[user_id]['count']}</b>"
            )
        except (ChannelInvalid, PeerIdInvalid) as e:
            logger.error(f"Admin {user_id} failed to send video to channel {config.VIDEO_CHANNEL_ID} due to invalid chat ID or permissions: {e}", exc_info=True)
            await message.reply_text(f"❌ Failed to send video to the channel. Error: Invalid channel ID or bot lacks permissions. Please check the <code>VIDEO_CHANNEL_ID</code> in config and ensure the bot is an admin with 'Post Messages' and 'Send Media' rights. Details: <code>{html.escape(str(e))}</code>")
        except BadRequest as e:
            logger.error(f"Admin {user_id} failed to send video due to bad request: {e}", exc_info=True)
            error_message_lower = str(e).lower()
            if "file too large" in error_message_lower:
                await message.reply_text(f"❌ Failed to add video: The video file is too large. Telegram's limit is 2 GB. Details: <code>{html.escape(str(e))}</code>")
            elif "content protection" in error_message_lower:
                await message.reply_text(f"❌ Failed to add video: Issue with content protection. Ensure bot has necessary admin rights in the channel (e.g., 'Add Admins') or try disabling <code>protect_content</code>. Details: <code>{html.escape(str(e))}</code>")
            else:
                await message.reply_text(f"❌ Failed to add video due to a bad request. This might be an invalid file type or other Telegram API limitation. Details: <code>{html.escape(str(e))}</code>")
        except FloodWait as e:
            logger.warning(f"Admin {user_id} hit FloodWait while sending video: {e.value} seconds. Advising to wait.")
            await message.reply_text(f"⚠️ Telegram is asking me to slow down. Please wait {e.value} seconds before sending more videos.")
        except RPCError as e:
            logger.error(f"Admin {user_id} encountered an RPC error while sending video: {e}", exc_info=True)
            await message.reply_text(f"❌ Failed to add video due to a Telegram API (RPC) error. This is usually a temporary issue. Details: <code>{html.escape(str(e))}</code>")
        except Exception as e:
            logger.error(f"Admin {user_id} unhandled error adding video: {e}", exc_info=True)
            await message.reply_text(f"❌ Failed to add video due to an unexpected error. Please check logs and try again. Details: <code>{html.escape(str(e))}</code>")

    except Exception as e: # This handles any unexpected errors in the outer try block of the handler
        logger.error(f"Admin {user_id} unexpected error in handle_video_batch_add: {e}", exc_info=True)
        await message.reply("❌ An unexpected error occurred while processing your video. Please try again.")

@app.on_message(filters.command("category") & filters.private & filters.user(config.ADMIN_IDS))
async def set_category_cmd(client: Client, message: Message):
    """Admin command to set the current category for batch adding."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} requested to set category for batch add.")
    try:
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
    except Exception as e: 
        logger.error(f"Admin {user_id} failed to send set category options: {e}", exc_info=True)
        await message.reply("❌ An error occurred while preparing set category options. Please try again.")

@app.on_callback_query(filters.regex(r"^setcat_(.+)$"))
async def setcat_callback(client: Client, callback_query: CallbackQuery):
    """Handles callback for setting the batch add category."""
    user_id = callback_query.from_user.id
    
    try:
        match = re.match(r"^setcat_(.+)$", callback_query.data)
        if not match:
            await callback_query.answer("❌ Invalid category data.", show_alert=True)
            logger.warning(f"Admin {user_id} received invalid category data in setcat_callback: {callback_query.data}.")
            return
        category_name = match.group(1)
        logger.info(f"Admin {user_id} selected category for batch adding: '{category_name}'.")

        if not is_admin(user_id):
            await callback_query.answer("❌ Only admins can use this command.", show_alert=True)
            logger.warning(f"Non-admin user {user_id} attempted to set batch category.")
            return

        if user_id not in batch_add_state or not batch_add_state[user_id].get('batch_mode', False):
            await callback_query.answer("❌ Error: Batch mode not active.", show_alert=True)
            logger.warning(f"Admin {user_id} tried to set category but batch mode not active.")
            return

        # Double-check if the category actually exists in the database
        if category_name not in get_categories():
            await callback_query.answer(f"❌ Invalid category '<b>{html.escape(category_name)}</b>'. This category does not exist.", show_alert=True)
            logger.warning(f"Admin {user_id} tried to set non-existent category: '{category_name}'.")
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
        
        # Get count of banned videos
        banned_videos = media_collection.count_documents({'banned': True})

        # Get total size of all videos
        pipeline = [
            {'$group': {'_id': None, 'total_size': {'$sum': '$size_bytes'}}}
        ]
        result = list(media_collection.aggregate(pipeline))
        total_storage_used = result[0]['total_size'] if result else 0

        await message.reply(
            f"📊 <b>Bot Statistics</b>\n\n"
            f"<b>Total Users:</b> {total_users}\n"
            f"<b>Total Videos:</b> {total_videos}\n"
            f"<b>Banned Videos:</b> {banned_videos}\n"
            f"<b>Total Categories:</b> {total_categories}\n"
            f"<b>Total Storage Used:</b> {format_size(total_storage_used)}"
        )
        logger.info(f"Admin {user_id} retrieved stats: Users={total_users}, Videos={total_videos}, Categories={total_categories}, Banned={banned_videos}, Storage={format_size(total_storage_used)}.")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to retrieve stats: {e}", exc_info=True)
        await message.reply("❌ An error occurred while fetching stats. Please try again.")

@app.on_message(filters.command("banvideo") & filters.private & filters.user(config.ADMIN_IDS))
async def banvideo_cmd(client: Client, message: Message):
    """Admin command to ban a video by its UUID."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} requested to ban video.")
    try:
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.reply("Usage: <code>/banvideo &lt;video_uuid&gt;</code>")
            return
        
        video_uuid_to_ban = args[1].strip()
        
        try:
            uuid.UUID(video_uuid_to_ban) # Validate UUID format
        except ValueError:
            await message.reply("❌ Invalid UUID format. Please provide a valid video UUID.")
            return

        video = media_collection.find_one({'uuid': video_uuid_to_ban})
        if not video:
            await message.reply(f"❌ Video with UUID <code>{html.escape(video_uuid_to_ban)}</code> not found.")
            return
            
        if video.get('banned'):
            await message.reply(f"ℹ️ Video with UUID <code>{html.escape(video_uuid_to_ban)}</code> is already banned.")
            return

        media_collection.update_one({'uuid': video_uuid_to_ban}, {'$set': {'banned': True}})
        logger.info(f"Admin {user_id} banned video {video_uuid_to_ban}.")

        # Optionally delete the video from the channel too
        message_id_in_channel = video.get('message_id')
        if message_id_in_channel:
            try:
                await client.delete_messages(config.VIDEO_CHANNEL_ID, message_id_in_channel)
                await message.reply(f"✅ Video <code>{html.escape(video_uuid_to_ban)}</code> banned and deleted from channel.")
                logger.info(f"Video {video_uuid_to_ban} also deleted from channel {config.VIDEO_CHANNEL_ID}.")
            except MessageIdInvalid:
                await message.reply(f"✅ Video <code>{html.escape(video_uuid_to_ban)}</code> banned. Could not delete from channel (message already gone or invalid ID).")
                logger.warning(f"Video {video_uuid_to_ban} banned, but message {message_id_in_channel} not found in channel for deletion.")
            except Exception as e:
                await message.reply(f"✅ Video <code>{html.escape(video_uuid_to_ban)}</code> banned. Failed to delete from channel: <code>{html.escape(str(e))}</code>")
                logger.error(f"Failed to delete video {video_uuid_to_ban} from channel: {e}", exc_info=True)
        else:
            await message.reply(f"✅ Video <code>{html.escape(video_uuid_to_ban)}</code> banned. (No channel message ID found).")

    except Exception as e:
        logger.error(f"Admin {user_id} failed to ban video: {e}", exc_info=True)
        await message.reply("❌ An error occurred while trying to ban the video. Please try again.")

@app.on_message(filters.command("unbanvideo") & filters.private & filters.user(config.ADMIN_IDS))
async def unbanvideo_cmd(client: Client, message: Message):
    """Admin command to unban a video by its UUID."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} requested to unban video.")
    try:
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.reply("Usage: <code>/unbanvideo &lt;video_uuid&gt;</code>")
            return
        
        video_uuid_to_unban = args[1].strip()
        
        try:
            uuid.UUID(video_uuid_to_unban) # Validate UUID format
        except ValueError:
            await message.reply("❌ Invalid UUID format. Please provide a valid video UUID.")
            return

        video = media_collection.find_one({'uuid': video_uuid_to_unban})
        if not video:
            await message.reply(f"❌ Video with UUID <code>{html.escape(video_uuid_to_unban)}</code> not found.")
            return
            
        if not video.get('banned'):
            await message.reply(f"ℹ️ Video with UUID <code>{html.escape(video_uuid_to_unban)}</code> is not currently banned.")
            return

        media_collection.update_one({'uuid': video_uuid_to_unban}, {'$set': {'banned': False}})
        logger.info(f"Admin {user_id} unbanned video {video_uuid_to_unban}.")
        await message.reply(f"✅ Video <code>{html.escape(video_uuid_to_unban)}</code> unbanned.")

    except Exception as e:
        logger.error(f"Admin {user_id} failed to unban video: {e}", exc_info=True)
        await message.reply("❌ An error occurred while trying to unban the video. Please try again.")

# --- Auto-Delete & Protect Content Settings ---
@app.on_message(filters.command('toggle_auto_delete') & filters.private & filters.user(config.ADMIN_IDS))
async def toggle_auto_delete_setting(client: Client, message: Message):
    """Admin command to toggle auto-deletion of sent videos."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} requested to toggle auto-delete setting.")
    try:
        # Get current setting, default to True if not found
        s = settings_collection.find_one({'_id': 'settings'}) or {'auto_delete': True}
        current_status = s.get('auto_delete', True)
        new_status = not current_status
        settings_collection.update_one({'_id': 'settings'}, {'$set': {'auto_delete': new_status}}, upsert=True)
        await message.reply(f"Auto-delete feature is now {'<b>enabled</b>' if new_status else '<b>disabled</b>'} for user-facing videos.")
        logger.info(f"Admin {user_id} toggled auto-delete to {'enabled' if new_status else 'disabled'}.")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to toggle auto-delete setting: {e}", exc_info=True)
        await message.reply("❌ An error occurred while toggling auto-delete. Please try again.")

@app.on_message(filters.command('toggle_protect') & filters.private & filters.user(config.ADMIN_IDS))
async def toggle_protect_setting(client: Client, message: Message):
    """Admin command to toggle content protection for sent videos."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} requested to toggle content protection setting.")
    try:
        # Get current setting, default to True if not found
        s = settings_collection.find_one({'_id': 'settings'}) or {'protect_content': True}
        current_status = s.get('protect_content', True)
        new_status = not current_status
        settings_collection.update_one({'_id': 'settings'}, {'$set': {'protect_content': new_status}}, upsert=True)
        await message.reply(f"Content protection is now {'<b>enabled</b>' if new_status else '<b>disabled</b>'} for user-facing videos.")
        logger.info(f"Admin {user_id} toggled content protection to {'enabled' if new_status else 'disabled'}.")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to toggle content protection setting: {e}", exc_info=True)
        await message.reply("❌ An error occurred while toggling content protection. Please try again.")

# --- Database Cleanup & Verification Tasks ---
async def cleanup_expired_data():
    """Periodically cleans up expired tokens, old history entries, and expired active menus."""
    while True:
        try:
            now = datetime.now(timezone.utc) # Use timezone-aware object
            
            # 1. Clean up expired tokens: remove individual tokens that have expired
            tokens_collection.update_many(
                {},
                {'$pull': {'tokens': {'expires_at': {'$lt': now}}}}
            )
            logger.info("Expired individual tokens cleanup completed.")
            
            # 2. Remove token documents entirely if their 'tokens' array becomes empty
            tokens_collection.delete_many({'tokens': {'$size': 0}})
            logger.info("Empty token documents cleanup completed.")

            # 3. Clean up old history entries (e.g., older than 30 days)
            # The $slice in save_history limits to 100, but this ensures very old entries (if any slipped) are removed.
            month_ago = now - timedelta(days=30)
            history_collection.update_many(
                {},
                {'$pull': {'history': {'viewed_at': {'$lt': month_ago}}}}
            )
            logger.info("Old history entries cleanup completed.")
            
            # 4. Remove empty history documents
            history_collection.delete_many({'history': {'$size': 0}})
            logger.info("Empty history documents cleanup completed.")
            
            # 5. Clean up expired active_menus from in-memory dictionary
            expired_users_menus = []
            # Iterate over a copy of the dictionary to allow modification during iteration
            for user_id_menu, menu_data in list(active_menus.items()): 
                if get_current_time() - menu_data['timestamp'] > config.MENU_TIMEOUT:
                    expired_users_menus.append((user_id_menu, menu_data.get('chat_id')))
            
            for user_id_to_clear, chat_id_to_clear in expired_users_menus:
                # Call cleanup_expired_menu to delete message and clear state
                await cleanup_expired_menu(app, user_id_to_clear, chat_id_to_clear) 
                logger.info(f"Cleaned up expired active menu for user {user_id_to_clear} from memory and attempted message deletion.")

            logger.info("Database and active_menus cleanup cycle completed.")
        except Exception as e:
            logger.error(f"Error in database cleanup task: {e}", exc_info=True)
        
        # Run every 24 hours (86400 seconds)
        await asyncio.sleep(86400) 

async def verify_and_cleanup_media():
    """Periodically verifies if media files still exist in the channel and cleans up invalid entries."""
    while True:
        logger.info("Starting media verification and cleanup task.")
        try:
            # Wait until the client is started before proceeding with API calls
            if not app.is_connected:
                logger.info("Waiting for Pyrogram client to connect before media verification...")
                await asyncio.sleep(5) # Wait for 5 seconds and re-check

            all_media = list(media_collection.find({}))
            total_media_items = len(all_media)
            deleted_media_count = 0

            logger.info(f"Verifying {total_media_items} media items in channel {config.VIDEO_CHANNEL_ID}.")

            for media_item in all_media:
                video_uuid = media_item.get('uuid')
                message_id_in_channel = media_item.get('message_id')
                
                if not message_id_in_channel:
                    logger.warning(f"Media item {video_uuid} has no 'message_id' in channel. Deleting from DB.")
                    media_collection.delete_one({'uuid': video_uuid})
                    deleted_media_count += 1
                    continue

                try:
                    # Attempt to get the message from the channel
                    await app.get_messages(config.VIDEO_CHANNEL_ID, message_id_in_channel)
                    # If successful, the message exists in the channel
                except (MessageIdInvalid, ValueError): # MessageIdInvalid for Pyrogram, ValueError for invalid ID format
                    logger.warning(f"Video {video_uuid} (message_id: {message_id_in_channel}) no longer exists in channel or is invalid. Deleting from DB.")
                    media_collection.delete_one({'uuid': video_uuid})
                    deleted_media_count += 1
                except (ChannelInvalid, PeerIdInvalid) as e:
                    logger.error(f"Media verification failed for channel {config.VIDEO_CHANNEL_ID} due to invalid channel ID or permissions. Skipping verification for now. Error: {e}")
                    # If bot can't access channel, skip verification for this cycle
                    break # Break out of the loop and try again later
                except FloodWait as e:
                    logger.warning(f"FloodWait encountered during media verification: {e.value} seconds. Pausing and retrying.")
                    await asyncio.sleep(e.value + 5) # Wait and then continue the loop from where it left off (implicitly by `for` loop)
                except RPCError as e:
                    logger.error(f"RPC error during media verification for {video_uuid}: {e}. Skipping for this item.")
                    # Continue to next item if RPC error is specific to this one
                except Exception as e:
                    logger.error(f"Unexpected error during media verification for {video_uuid}: {e}", exc_info=True)
                    # Continue to next item

            logger.info(f"Media verification and cleanup task completed. Deleted {deleted_media_count} invalid media entries.")
        except Exception as e:
            logger.error(f"Error in overall media verification cleanup task: {e}", exc_info=True)
        
        # Run every 6 hours (6 * 3600 seconds)
        await asyncio.sleep(6 * 3600)

# --- Main Bot Execution ---
if __name__ == '__main__':
    logger.info("Bot starting up...")

    async def main_startup():
        """Main asynchronous function to start the Pyrogram client and schedule tasks."""
        try:
            await app.start()
            logger.info("Pyrogram client started successfully.")
            
            # Schedule periodic background tasks
            asyncio.create_task(cleanup_expired_data())
            asyncio.create_task(verify_and_cleanup_media())
            
            logger.info("Background tasks scheduled.")
            
            # Keep the bot running indefinitely, handling messages and callbacks
            # Replaced app.idle() with asyncio.Event().wait()
            await asyncio.Event().wait() 
        except Exception as e:
            logger.critical(f"Fatal error during bot startup or idle: {e}", exc_info=True)
        finally:
            if app.is_connected:
                await app.stop()
                logger.info("Pyrogram client stopped.")
            logger.info("Bot execution finished.")

    # Run the main asynchronous function
    asyncio.run(main_startup())

