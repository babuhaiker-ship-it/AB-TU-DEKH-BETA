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
from pyrogram.errors import UserIsBlocked, ChatInvalid, MessageIdInvalid, FloodWait
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
    BOT_TOKEN = '7965872423:AAHkSMHJVveM1ROKlPJGgsP_GcLb8iNvCic' # Replaced with a dummy token for safety
    API_ID = 29800015
    API_HASH = 'c8f37108be31ab9ea2818bfe533fbb6f'
    BOT_USERNAME = '@Testingnyraa_bot'
    MONGO_URI = 'mongodb+srv://Pyasipriya:00pEcao9sYhNC5VQ@cluster0.2dfenf7.mongodb.net/spicybot?retryWrites=true&w=majority&appName=Cluster0'
    MONGO_DB_NAME = 'spicybot'
    VIDEO_CHANNEL_ID = -1002621716446
    BUY_BOT_URL = 'https://t.me/hanielxsupportbot'
    ADMIN_IDS = [6612030110]
    URL_SHORTENER = 'https://api.linkshortify.com/st'
    SHORTENER_API_KEY = '5cd923c490f64017cffa6e3bb6cc724560a8cfc6'
    TUTORIAL_LINK_2 = 'https://t.me/urlshortenertutorial'
    TOKEN_EXPIRY = 86400  # 24 hours in seconds
    NEW_USER_TOKENS = 1
    REFERRAL_BONUS = 1
    REFRESH_BONUS = 1
    MENU_TIMEOUT = 3600 # 1 hour in seconds, for soft expiry check, now less critical
    PREMIUM_TRIAL_PRICE_INR = 69
    PREMIUM_MONTH_PRICE_INR = 169
    SUPPORT_BOT_USERNAME = 'hanielxsupportbot' # Support bot username for inline button
    # --- New: Bookmark Limits ---
    FREE_USER_BOOKMARK_LIMIT = 100

try:
    config = BotConfig()
    if not all([config.BOT_TOKEN, config.API_ID, config.API_HASH, config.MONGO_URI, config.SHORTENER_API_KEY, config.BOT_USERNAME]):
        raise ValueError("One or more essential configuration variables are not set. Please check BOT_TOKEN, API_ID, API_HASH, MONGO_URI, SHORTENER_API_KEY, BOT_USERNAME.")
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
# --- New: Bookmarks Collection ---
bookmarks_collection = db['bookmarks']


# Create indexes
users_collection.create_index([("user_id", ASCENDING)], unique=True)
tokens_collection.create_index([("user_id", ASCENDING)], unique=True)
media_collection.create_index([("uuid", ASCENDING)], unique=True)
media_collection.create_index([("category", ASCENDING)])
media_collection.create_index([("file_unique_id", ASCENDING)], unique=True)
media_collection.create_index([("size_bytes", ASCENDING)])
history_collection.create_index([("user_id", ASCENDING)], unique=True)
categories_collection.create_index([("name", ASCENDING)], unique=True)
# --- New: Bookmarks Index ---
bookmarks_collection.create_index([("user_id", ASCENDING)])
bookmarks_collection.create_index([("user_id", ASCENDING), ("video_uuid", ASCENDING)], unique=True)
bookmarks_collection.create_index([("user_id", ASCENDING), ("timestamp", ASCENDING)]) # For sorting to get most recent 100

# Ensure 'premium_until' field for users collection
users_collection.create_index([("premium_until", ASCENDING)], expireAfterSeconds=0) # For automatic document expiration if needed for premium status

# --- Pyrogram Client ---
app = Client("spicynyraa", api_id=config.API_ID, api_hash=config.API_HASH, bot_token=config.BOT_TOKEN)

# --- GLOBAL SET FOR TRACKING ASYNC TASKS ---
active_tasks = set()

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

async def cancel_all_active_tasks():
    """
    Cancels all tasks currently being tracked in the_active_tasks set.
    Awaits their completion gracefully (or handles CancelledError).
    """
    if not active_tasks:
        logger.info("No active tasks to cancel.")
        return

    logger.info(f"Attempting to cancel {len(active_tasks)} active tasks...")
    tasks_to_cancel = list(active_tasks) 
    
    for task in tasks_to_cancel:
        if not task.done():
            task.cancel()
            logger.debug(f"Task {task.get_name()} cancellation requested.")
            
    try:
        await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
        logger.info("All active tasks cancelled or completed.")
    except Exception as e:
        logger.error(f"Error during asyncio.gather for task cancellation: {e}", exc_info=True)
    finally:
    # Clear the set only after gathering, even if exceptions occur, to ensure a clean state
        active_tasks.clear()
        logger.info("Active tasks set cleared.")

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

# --- Token and Premium Management ---
def get_and_cleanup_tokens(user_id: int) -> list:
    """Removes expired tokens from the database and returns the list of valid tokens."""
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

def add_token(user_id: int, duration_seconds: int = config.TOKEN_EXPIRY):
    """Adds a new token for a user with a specified duration and updates premium status."""
    now = datetime.utcnow()
    expires_at = now + timedelta(seconds=duration_seconds)
    token = {
        'token_id': str(uuid.uuid4()),
        'created_at': now,
        'expires_at': expires_at
    }
    try:
        tokens_collection.update_one(
            {'user_id': user_id},
            {'$push': {'tokens': token}},
            upsert=True
        )
        # Update user's premium_until status
        users_collection.update_one(
            {'user_id': user_id},
            {'$set': {'premium_until': expires_at}},
            upsert=True
        )
        logger.info(f"Token added for user {user_id}, premium_until set to {expires_at}")
        return token
    except Exception as e:
        logger.error(f"Error adding token for user {user_id}: {e}", exc_info=True)
        return None

def is_premium_user(user_id: int) -> bool:
    """Checks if a user is a premium user (has an active token)."""
    # This function now relies on the `premium_until` field.
    # We still keep `get_and_cleanup_tokens` for token count display,
    # but actual premium status check for features uses `premium_until`.
    user = users_collection.find_one({'user_id': user_id})
    if not user:
        return False
    
    premium_until = user.get('premium_until')
    if premium_until and premium_until > datetime.utcnow():
        return True
    
    # If premium_until is in the past or not set, check for valid tokens
    # and update premium_until if found. This acts as a fallback/sync.
    valid_tokens = get_and_cleanup_tokens(user_id)
    if valid_tokens:
        latest_expiry = max(t['expires_at'] for t in valid_tokens)
        if latest_expiry > datetime.utcnow():
            users_collection.update_one(
                {'user_id': user_id},
                {'$set': {'premium_until': latest_expiry}}
            )
            return True
    
    # Ensure premium_until is removed if no valid tokens
    users_collection.update_one(
        {'user_id': user_id},
        {'$unset': {'premium_until': ""}}
    )
    return False

def user_has_token(user_id: int) -> bool:
    """Checks if a user has any valid tokens (for non-premium features)."""
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
                add_token(referrer_id, config.REFERRAL_BONUS * 86400)
                users_collection.update_one({'user_id': referrer_id}, {'$inc': {'referral_count': 1}}, upsert=True)
                users_collection.update_one({'user_id': new_user_id}, {'$set': {'referred_by': referrer_id}}, upsert=True)
                logger.info(f"User {new_user_id} successfully referred by {referrer_id}.")
                return referrer_id
    elif ref_code.startswith('video_'):
        try:
            parts = ref_code.split('_')
            if len(parts) == 3:
                referrer_id = int(parts[2])
                
                if referrer_id != new_user_id:
                    ref_user = users_collection.find_one({'user_id': referrer_id})
                    if ref_user:
                        add_token(referrer_id, config.REFERRAL_BONUS * 86400)
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
    """Validates a category name. Returns (is_valid, error_message)"""
    if not name:
        return False, "Category name cannot be empty."
    if not re.match(r'^[a-zA-Z0-9_-]+$', name):
        return False, "Category name can only contain letters, numbers, underscores, and hyphens."
    if len(name) > 32:
        return False, "Category name cannot be longer than 32 characters."
    return True, ""

def get_categories() -> list[str]:
    """Gets all category names."""
    categories = [c['name'] for c in categories_collection.find({})]
    return sorted(list(set(categories)))

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
            'created_at': datetime.utcnow()
        })
        logger.info(f"Category '{name}' added")
        return True, f"Category '{html.escape(name)}' added successfully."
    except Exception as e:
        logger.error(f"Error adding category '{name}': {e}")
        return False, "Failed to add category. Please try again."

def delete_category(name: str) -> tuple[bool, str, int]:
    """Deletes a category and its associated videos. Returns (success, message, deleted_count)"""
    try:
        if not categories_collection.find_one({'name': name}):
            return False, f"Category '{html.escape(name)}' does not exist.", 0
            
        result = media_collection.delete_many({'category': name})
        deleted_count = result.deleted_count
        
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
            {'$push': {'history': {'$each': [entry], '$slice': -100}}},
            upsert=True
        )
        logger.info(f"History saved for user {user_id}, video {video_uuid}. History size limited to 100.")
    except Exception as e:
        logger.error(f"Error saving history for user {user_id}, video {video_uuid}: {e}", exc_info=True)

def get_last_video_from_history(user_id: int) -> dict | None:
    """
    Retrieves the last viewed video from a user's history (the one before the current latest).
    If there's only one entry, it returns that entry.
    """
    doc = history_collection.find_one({'user_id': user_id})
    if doc and doc.get('history'):
        history_list = doc['history']
        if len(history_list) >= 2:
            last_viewed_entry = history_list[-2]
        elif len(history_list) == 1:
            last_viewed_entry = history_list[-1]
        else:
            return None

        video_uuid = last_viewed_entry['video_uuid']
        video = media_collection.find_one({'uuid': video_uuid})
        if video:
            return video
    return None

# --- New: Bookmark Functions ---
def add_bookmark(user_id: int, video_uuid: str) -> tuple[bool, str]:
    """
    Adds a video to a user's bookmarks.
    Free users have a limit (config.FREE_USER_BOOKMARK_LIMIT). Premium users have unlimited.
    """
    now = datetime.utcnow()
    is_premium = is_premium_user(user_id)
    
    existing_bookmark = bookmarks_collection.find_one({'user_id': user_id, 'video_uuid': video_uuid})
    if existing_bookmark:
        return False, "This video is already bookmarked! 📖"

    if not is_premium:
        current_bookmarks_count = bookmarks_collection.count_documents({'user_id': user_id})
        if current_bookmarks_count >= config.FREE_USER_BOOKMARK_LIMIT:
            return False, f"You have reached your bookmark limit of {config.FREE_USER_BOOKMARK_LIMIT} videos. Upgrade to premium for unlimited saves! 💎"
            
    try:
        bookmarks_collection.insert_one({
            'user_id': user_id,
            'video_uuid': video_uuid,
            'timestamp': now
        })
        logger.info(f"User {user_id} bookmarked video {video_uuid}. Premium status: {is_premium}")
        return True, "Video bookmarked successfully! ✅"
    except Exception as e:
        logger.error(f"Error adding bookmark for user {user_id}, video {video_uuid}: {e}", exc_info=True)
        return False, "Failed to bookmark video. Please try again. 😥"

def remove_bookmark(user_id: int, video_uuid: str) -> tuple[bool, str]:
    """Removes a video from a user's bookmarks."""
    try:
        result = bookmarks_collection.delete_one({'user_id': user_id, 'video_uuid': video_uuid})
        if result.deleted_count > 0:
            logger.info(f"User {user_id} unbookmarked video {video_uuid}.")
            return True, "Video removed from bookmarks. 🗑️"
        else:
            return False, "This video was not found in your bookmarks. 🤔"
    except Exception as e:
        logger.error(f"Error removing bookmark for user {user_id}, video {video_uuid}: {e}", exc_info=True)
        return False, "Failed to remove bookmark. Please try again. 😥"

def get_bookmarked_videos(user_id: int) -> list[dict]:
    """
    Retrieves a user's bookmarked videos.
    If premium has expired, only the most recent 100 are displayed.
    """
    is_premium = is_premium_user(user_id) # This checks active premium
    user_doc = users_collection.find_one({'user_id': user_id})
    # Consider premium grace period, currently set to 1 day for simplicity.
    premium_was_active = user_doc and user_doc.get('premium_until') and user_doc['premium_until'] > datetime.utcnow() - timedelta(days=1)

    if is_premium or premium_was_active: # If premium is active or was recently active
        # Premium users get all their bookmarks
        bookmarks = list(bookmarks_collection.find({'user_id': user_id}).sort('timestamp', ASCENDING))
        logger.info(f"Premium user {user_id} retrieved {len(bookmarks)} bookmarks.")
    else:
        # Free users or expired premium users get only the most recent 100
        bookmarks = list(bookmarks_collection.find({'user_id': user_id}).sort('timestamp', -1).limit(config.FREE_USER_BOOKMARK_LIMIT))
        logger.info(f"Free/expired premium user {user_id} retrieved {len(bookmarks)} bookmarks (capped at {config.FREE_USER_BOOKMARK_LIMIT}).")

    video_uuids = [b['video_uuid'] for b in bookmarks]
    # Fetch video details for the bookmarked UUIDs
    bookmarked_videos_data = []
    for uuid_val in video_uuids:
        video_data = media_collection.find_one({'uuid': uuid_val})
        if video_data:
            bookmarked_videos_data.append(video_data)
        else:
            # Clean up broken bookmark entries (video no longer exists)
            bookmarks_collection.delete_one({'user_id': user_id, 'video_uuid': uuid_val})
            logger.warning(f"User {user_id} had a bookmark for non-existent video {uuid_val}. Bookmark removed.")

    # Ensure the order is consistent with how they were retrieved (e.g., oldest first for premium, newest first for free)
    # The current logic for sorting in find() already handles this.
    return bookmarked_videos_data

def get_bookmark_status(user_id: int, video_uuid: str) -> bool:
    """Checks if a video is bookmarked by a user."""
    return bookmarks_collection.find_one({'user_id': user_id, 'video_uuid': video_uuid}) is not None

# --- Message Tracking and Immediate Deletion ---
active_video_message = {} 

def set_active_video_message(user_id: int, message_id: int, chat_id: int):
    """Set the active message for a user, to be deleted on next action."""
    active_video_message[user_id] = {
        'message_id': message_id,
        'chat_id': chat_id
    }
    logger.info(f"Active video message set for user {user_id}: message_id={message_id}, chat_id={chat_id}")

def clear_active_video_message(user_id: int):
    """Clear a user's active message state."""
    if user_id in active_video_message:
        del active_video_message[user_id]
        logger.info(f"Active video message cleared for user {user_id}.")

async def send_and_replace_message(client: Client, chat_id: int, old_message_id: int, new_message_type: str, video_data: dict = None, text_content: str = None, reply_markup: InlineKeyboardMarkup = None) -> tuple[bool, Message | str]:
    """
    Deletes the old message (if provided) and sends a new video or text message.
    Updates the active_video_message tracking.
    Returns (success: bool, sent_message: Message | error_message: str)
    """
    if old_message_id:
        try:
            await client.delete_messages(chat_id, old_message_id)
            logger.info(f"Deleted old message {old_message_id} in chat {chat_id}.")
        except MessageIdInvalid:
            logger.warning(f"Old message {old_message_id} for deletion in chat {chat_id} was already invalid or deleted.")
        except Exception as e:
            logger.error(f"Failed to delete old message {old_message_id} in chat {chat_id}: {e}")
    
    sent_message = None
    success = False
    error_message = ""

    settings = settings_collection.find_one({'_id': 'settings'}) or {}
    protect_content_for_user = settings.get('protect_content', True) 

    try:
        if new_message_type == "video" and video_data:
            sent_message = await client.send_video(
                chat_id,
                video_data['file_id'],
                caption=f"Category: {html.escape(video_data['category'])}",
                reply_markup=reply_markup,
                protect_content=protect_content_for_user
            )
            success = True
        elif new_message_type == "text" and text_content:
            sent_message = await client.send_message(
                chat_id,
                text_content,
                reply_markup=reply_markup
            )
            success = True
        else:
            error_message = "Invalid new_message_type or missing data for sending."
            logger.error(error_message)

    except Exception as e:
        logger.error(f"Failed to send new message of type {new_message_type} to chat {chat_id}: {e}")
        error_message = f"❌ <b>Failed to send message.</b>\nReason: {e}\nPlease try again later. 😥"
        success = False

    if success and isinstance(sent_message, Message):
        set_active_video_message(chat_id, sent_message.id, chat_id)
        logger.info(f"New message {sent_message.id} of type {new_message_type} sent and active video message updated for user {chat_id}.")
        return True, sent_message
    else:
        logger.error(f"Failed to send new message in send_and_replace_message: {error_message}")
        return False, error_message

# --- Keyboards ---
async def get_main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    """Main keyboard for the bot."""
    buttons = [
        [KeyboardButton("🎞️ Get Video"), KeyboardButton("👤 Profile")],
        [KeyboardButton("🔗 Refer & Earn"), KeyboardButton("💰 Buy Token")],
        [KeyboardButton("🔄 Refresh Token"), KeyboardButton("🔖 Saved Videos")] # New: Saved Videos button
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def token_earning_keyboard(ad_url: str) -> InlineKeyboardMarkup:
    """Keyboard for token earning options."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👆 Click Here To Refresh Token", url=ad_url)],
        [InlineKeyboardButton("❓ How To Open Links?", url=config.TUTORIAL_LINK_2)],
        [InlineKeyboardButton("💳 Buy Token", url=config.BUY_BOT_URL)]
    ])

def category_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for selecting video categories."""
    cats = get_categories()
    if not cats:
        return InlineKeyboardMarkup([[InlineKeyboardButton("😔 No Categories Available", callback_data="no_cat")]])
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(f"🎬 {html.escape(cat)}", callback_data=f"cat_{cat}")] for cat in cats]
    )

def video_nav_keyboard(video_uuid: str, category: str, user_id: int) -> InlineKeyboardMarkup:
    """
    Keyboard for navigating between videos, including 'Share', 'Download', and 'Bookmark' buttons.
    The 'Download' button is shown only to premium users.
    The 'Bookmark' button changes based on whether the video is already bookmarked.
    """
    bookmark_text = "🔖 Remove Bookmark" if get_bookmark_status(user_id, video_uuid) else "🔖 Add Bookmark"
    bookmark_callback = f"remove_bookmark_{video_uuid}" if get_bookmark_status(user_id, video_uuid) else f"add_bookmark_{video_uuid}"

    buttons = [
        [
            InlineKeyboardButton("⬅️ Previous", callback_data=f"prev_{video_uuid}_{category}"),
            InlineKeyboardButton("➡️ Next", callback_data=f"next_{video_uuid}_{category}")
        ],
        [
            InlineKeyboardButton("🗂️ Change Category", callback_data="change_cat"),
            InlineKeyboardButton(bookmark_text, callback_data=bookmark_callback) # New: Bookmark button
        ],
        [InlineKeyboardButton("📲 Share", callback_data=f"share_{video_uuid}")]
    ]
    
    # Add Download button if user is premium
    if is_premium_user(user_id):
        buttons.append([InlineKeyboardButton("⬇️ Download", callback_data=f"download_{video_uuid}")])

    return InlineKeyboardMarkup(buttons)

# New: Keyboard for navigating saved videos
def saved_video_nav_keyboard(video_uuid: str, current_index: int, total_videos: int) -> InlineKeyboardMarkup:
    """
    Keyboard for navigating saved videos, including previous, next, and remove bookmark.
    """
    buttons = [
        [
            InlineKeyboardButton("⬅️ Previous", callback_data=f"saved_prev_{video_uuid}_{current_index}"),
            InlineKeyboardButton("➡️ Next", callback_data=f"saved_next_{video_uuid}_{current_index}")
        ],
        [
            InlineKeyboardButton("🔖 Remove Bookmark", callback_data=f"remove_bookmark_{video_uuid}")
        ],
        [InlineKeyboardButton("🔙 Back to Saved List", callback_data="show_saved_videos_list")]
    ]
    return InlineKeyboardMarkup(buttons)

def referral_keyboard(ref_link: str) -> InlineKeyboardMarkup:
    """Keyboard for displaying a referral link."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Copy Referral Link", url=ref_link)]
    ])

def buy_token_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for buying tokens."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Buy Token", url=config.BUY_BOT_URL)]
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
        return False, "Oops, invalid link. Try again! 😔"
    
    if video.get('banned'):
        logger.warning(f"User {user_id} attempted to view banned video {video_uuid}.")
        return False, "🚫 This content is no longer available."
    
    return True, video

# --- Token Refresh ---
async def handle_token_refresh(user_id: int, ad_code: str) -> tuple[bool, str]:
    """Handles token refresh requests from users."""
    try:
        if await is_rate_limited(user_id):
            return False, "⚠️ You're refreshing too quickly. Please wait a minute and try again."

        # The logic here assumes that getting a token always grants some form of access.
        # For simplicity, if premium_until is already set, we consider them "active"
        # and don't need a token refresh *from an ad*.
        if is_premium_user(user_id): # Check premium status directly
            logger.info(f"User {user_id} attempted token refresh but already has valid premium access.")
            return False, "💡 You already have active premium access. No need to refresh yet! Enjoy the videos! 🥳"
            
        decoded = b64_to_str(ad_code)
        if not decoded:
            logger.warning(f"User {user_id} provided invalid base64 for token refresh: {ad_code}")
            return False, "Oops, invalid link. Try again! 🧐"
        
        try:
            code_user_id, timestamp = map(int, decoded.split(':'))
        except ValueError:
            logger.error(f"User {user_id} provided invalid token refresh code format: {ad_code}")
            return False, "Invalid token refresh link format. 🐛"
            
        if code_user_id != user_id:
            logger.warning(f"User {user_id} attempted to use another user's token refresh link ({code_user_id}).")
            return False, "This token refresh link is not for you! 😠"
            
        if timestamp < get_current_time():
            logger.warning(f"User {user_id} attempted to use expired token refresh link.")
            return False, "This token refresh link has expired. ⏰"
            
        added_token = add_token(user_id, config.REFRESH_BONUS * 86400)
        if added_token:
            logger.info(f"Token added for user {user_id} via refresh. Premium status updated.")
            return True, f"🎉 <b>Success!</b> You got {config.REFRESH_BONUS} token. Each token lasts 24 hours. Enjoy! 🍿"
        else:
            return False, "❌ <b>Something went wrong!</b>\nFailed to add token. Please try again later. 🛠️"
    except Exception as e:
        logger.error(f"Token refresh failed for user {user_id}: {e}", exc_info=True)
        return False, "❌ <b>Something went wrong!</b>\nPlease try again later. 🤷‍♀️"

# --- Rate Limiting ---
RATE_LIMIT_WINDOW = 120  # 2 minutes
RATE_LIMIT_MAX = 60  # 60 requests per 2 minutes

user_request_timestamps = defaultdict(list)

async def is_rate_limited(user_id: int) -> bool:
    """
    Checks if a user is rate-limited based on their recent requests.
    Returns True if rate-limited, False otherwise.
    """
    now = time.time()
    
    # Remove timestamps older than the rate limit window
    user_request_timestamps[user_id] = [
        t for t in user_request_timestamps[user_id] if now - t < RATE_LIMIT_WINDOW
    ]
    
    # Check if the number of requests exceeds the maximum allowed
    if len(user_request_timestamps[user_id]) >= RATE_LIMIT_MAX:
        logger.warning(f"User {user_id} is rate-limited. Requests in window: {len(user_request_timestamps[user_id])}")
        return True
        
    # Add the current request timestamp
    user_request_timestamps[user_id].append(now)
    return False

# --- Handlers (incomplete from original, adding placeholders for the problematic part) ---

@app.on_message(filters.command("start"))
async def start_command_handler(client: Client, message: Message):
    """
    Handles the /start command.
    Greets the user, adds them to the database, and handles referrals.
    """
    user_id = message.from_user.id
    first_name = message.from_user.first_name
    
    logger.info(f"User {user_id} ({first_name}) started the bot.")

    user_data = users_collection.find_one({'user_id': user_id})

    # Check for referral link in /start payload
    ref_code = None
    if message.command and len(message.command) > 1:
        ref_code = message.command[1]

    if not user_data:
        # New user
        users_collection.insert_one({
            'user_id': user_id,
            'first_name': first_name,
            'username': message.from_user.username,
            'join_date': datetime.utcnow(),
            'referral_count': 0,
            'total_video_views': 0,
            'is_premium': False, # Initial state, will be updated by token
            'premium_until': None,
            'referred_by': None
        })
        
        # Add initial tokens for new users
        add_token(user_id, config.NEW_USER_TOKENS * 86400)
        await message.reply_text(
            f"👋 Welcome, <b>{html.escape(first_name)}</b>! 🎉\n\n"
            f"You've received {config.NEW_USER_TOKENS} free token to get started. Each token lasts 24 hours. "
            "Explore spicy content or refer friends to earn more tokens!",
            reply_markup=await get_main_keyboard(user_id)
        )
        logger.info(f"New user {user_id} registered and received initial tokens.")

        if ref_code:
            referrer_id = handle_referral(user_id, ref_code)
            if referrer_id:
                try:
                    await client.send_message(
                        referrer_id,
                        f"🎉 Your referral from <b>{html.escape(first_name)}</b> was successful! You've received {config.REFERRAL_BONUS} token. Thank you! 🤩"
                    )
                    logger.info(f"Referrer {referrer_id} notified of successful referral by {user_id}.")
                except (UserIsBlocked, ChatInvalid):
                    logger.warning(f"Could not notify referrer {referrer_id} (blocked/invalid chat).")
            else:
                logger.warning(f"Referral code '{ref_code}' for new user {user_id} was invalid or already processed.")
    else:
        # Returning user
        await message.reply_text(
            f"👋 Welcome back, <b>{html.escape(first_name)}</b>! What would you like to do today?",
            reply_markup=await get_main_keyboard(user_id)
        )
        logger.info(f"Returning user {user_id} greeted.")

@app.on_message(filters.regex("🎞️ Get Video"))
async def get_video_button_handler(client: Client, message: Message):
    """Handles the 'Get Video' button press, showing categories."""
    user_id = message.from_user.id
    logger.info(f"User {user_id} pressed 'Get Video'.")
    
    old_msg_id = active_video_message.get(user_id, {}).get('message_id')
    
    categories_kb = category_keyboard()
    if categories_kb.inline_keyboard[0][0].callback_data == "no_cat":
        await send_and_replace_message(
            client,
            user_id,
            old_msg_id,
            "text",
            text_content="😔 No video categories available yet. Please wait for an admin to add some!",
            reply_markup=None # No inline keyboard needed here
        )
    else:
        await send_and_replace_message(
            client,
            user_id,
            old_msg_id,
            "text",
            text_content="Please choose a category:",
            reply_markup=categories_kb
        )


@app.on_callback_query(filters.regex(r"^cat_(.+)$"))
async def category_callback_handler(client: Client, callback_query: CallbackQuery):
    """Handles category selection and sends a random video."""
    user_id = callback_query.from_user.id
    category = callback_query.matches[0].group(1)
    logger.info(f"User {user_id} selected category: {category}")

    if await is_rate_limited(user_id):
        await callback_query.answer("⚠️ You're requesting too many videos too quickly. Please wait a moment.", show_alert=True)
        return

    if not user_has_token(user_id):
        await callback_query.answer("😔 You don't have any active tokens. Please refresh or buy more!", show_alert=True)
        # Also send a message with earning options
        await send_and_replace_message(
            client,
            user_id,
            callback_query.message.id,
            "text",
            text_content="😔 Your tokens have expired or you don't have any. Please refresh or buy more!",
            reply_markup=token_earning_keyboard(await shorten_url(f"https://t.me/{config.BOT_USERNAME.lstrip('@')}?start=ad_{user_id}:{get_current_time() + 600}")) # Ad link valid for 10 minutes
        )
        return

    video = get_random_video(category)
    if not video:
        await callback_query.answer(f"😔 No videos found in the '{html.escape(category)}' category.", show_alert=True)
        # Allow them to change category again
        await send_and_replace_message(
            client,
            user_id,
            callback_query.message.id,
            "text",
            text_content="No videos found. Please try another category:",
            reply_markup=category_keyboard()
        )
        return
    
    save_history(user_id, video['uuid'], category) # Save viewing history

    success, result = await send_and_replace_message(
        client,
        user_id,
        callback_query.message.id,
        "video",
        video_data=video,
        reply_markup=video_nav_keyboard(video['uuid'], category, user_id)
    )

    if success:
        await callback_query.answer()
        # Increment total video views for the user
        users_collection.update_one({'user_id': user_id}, {'$inc': {'total_video_views': 1}}, upsert=True)
        logger.info(f"User {user_id} viewed video {video['uuid']}.")
    else:
        await callback_query.answer(f"Failed to send video: {result}", show_alert=True)
        # Attempt to show category keyboard again if video sending failed
        await send_and_replace_message(
            client,
            user_id,
            callback_query.message.id,
            "text",
            text_content="Failed to load video. Please try another category:",
            reply_markup=category_keyboard()
        )

@app.on_callback_query(filters.regex(r"^(next|prev)_(.+?)_(.+)$"))
async def video_navigation_callback_handler(client: Client, callback_query: CallbackQuery):
    """Handles 'Next' and 'Previous' video navigation."""
    user_id = callback_query.from_user.id
    action = callback_query.matches[0].group(1) # 'next' or 'prev'
    current_video_uuid = callback_query.matches[0].group(2)
    category = callback_query.matches[0].group(3)
    logger.info(f"User {user_id} clicked {action} for video {current_video_uuid} in category {category}.")

    if await is_rate_limited(user_id):
        await callback_query.answer("⚠️ You're navigating too quickly. Please wait a moment.", show_alert=True)
        return

    if not user_has_token(user_id):
        await callback_query.answer("😔 You don't have any active tokens. Please refresh or buy more!", show_alert=True)
        await send_and_replace_message(
            client,
            user_id,
            callback_query.message.id,
            "text",
            text_content="😔 Your tokens have expired or you don't have any. Please refresh or buy more!",
            reply_markup=token_earning_keyboard(await shorten_url(f"https://t.me/{config.BOT_USERNAME.lstrip('@')}?start=ad_{user_id}:{get_current_time() + 600}"))
        )
        return

    video_to_send = None
    if action == "next":
        video_to_send = get_random_video(category) # Get another random video from the same category
        while video_to_send and video_to_send['uuid'] == current_video_uuid: # Ensure it's not the same video
            video_to_send = get_random_video(category)
    elif action == "prev":
        video_to_send = get_last_video_from_history(user_id) # Get the previous video from history

    if not video_to_send:
        await callback_query.answer("No more videos in this direction or history is empty.", show_alert=True)
        return
        
    save_history(user_id, video_to_send['uuid'], category) # Save the new video to history

    success, result = await send_and_replace_message(
        client,
        user_id,
        callback_query.message.id,
        "video",
        video_data=video_to_send,
        reply_markup=video_nav_keyboard(video_to_send['uuid'], category, user_id)
    )

    if success:
        await callback_query.answer()
        users_collection.update_one({'user_id': user_id}, {'$inc': {'total_video_views': 1}}, upsert=True)
        logger.info(f"User {user_id} navigated to video {video_to_send['uuid']}.")
    else:
        await callback_query.answer(f"Failed to load video: {result}", show_alert=True)
        logger.error(f"Video navigation failed for user {user_id}: {result}")

@app.on_callback_query(filters.regex("change_cat"))
async def change_category_callback_handler(client: Client, callback_query: CallbackQuery):
    """Handles 'Change Category' button press."""
    user_id = callback_query.from_user.id
    logger.info(f"User {user_id} pressed 'Change Category'.")

    await callback_query.answer("Changing category...")
    
    old_msg_id = callback_query.message.id

    categories_kb = category_keyboard()
    if categories_kb.inline_keyboard[0][0].callback_data == "no_cat":
        await send_and_replace_message(
            client,
            user_id,
            old_msg_id,
            "text",
            text_content="😔 No video categories available yet. Please wait for an admin to add some!",
            reply_markup=None
        )
    else:
        await send_and_replace_message(
            client,
            user_id,
            old_msg_id,
            "text",
            text_content="Please choose a new category:",
            reply_markup=categories_kb
        )

@app.on_message(filters.regex("👤 Profile"))
async def profile_button_handler(client: Client, message: Message):
    """Handles the 'Profile' button press."""
    user_id = message.from_user.id
    user_data = users_collection.find_one({'user_id': user_id})
    
    if not user_data:
        await message.reply_text("Error: User profile not found. Please try /start again.")
        return

    first_name = html.escape(user_data.get('first_name', 'N/A'))
    username = html.escape(user_data.get('username', 'N/A'))
    join_date = user_data.get('join_date', datetime.utcnow()).strftime('%Y-%m-%d %H:%M UTC')
    referral_count = user_data.get('referral_count', 0)
    total_video_views = user_data.get('total_video_views', 0)
    
    valid_tokens = get_and_cleanup_tokens(user_id) # Cleanup expired tokens and get current count
    active_tokens_count = len(valid_tokens)

    premium_status_text = "Free User 🆓"
    premium_expiry = "N/A"
    
    if is_premium_user(user_id):
        premium_status_text = "Premium User 💎"
        premium_until = user_data.get('premium_until')
        if premium_until:
            time_left = premium_until - datetime.utcnow()
            days = time_left.days
            hours = time_left.seconds // 3600
            minutes = (time_left.seconds % 3600) // 60
            premium_expiry = f"{days} days, {hours} hours, {minutes} minutes remaining."
        else:
            premium_expiry = "Indefinite (error in expiry tracking, but premium active)."
    elif active_tokens_count > 0: # User has tokens but not marked as premium due to expiry logic
         premium_status_text = f"Token User (Temp. Premium) ⚡"
         if valid_tokens:
            latest_expiry = max(t['expires_at'] for t in valid_tokens)
            time_left = latest_expiry - datetime.utcnow()
            days = time_left.days
            hours = time_left.seconds // 3600
            minutes = (time_left.seconds % 3600) // 60
            premium_expiry = f"{days} days, {hours} hours, {minutes} minutes remaining."
    else:
        premium_status_text = "Free User 🆓"
        premium_expiry = "No active premium or tokens."
        

    profile_text = (
        f"<b>📊 Your Profile</b>\n\n"
        f"🆔 User ID: <code>{user_id}</code>\n"
        f"👤 Name: {first_name}\n"
        f"🔗 Username: @{username}\n"
        f"🗓️ Joined: {join_date}\n"
        f"🌟 Premium Status: {premium_status_text}\n"
        f"⏳ Premium Expires: {premium_expiry}\n"
        f"🎁 Referral Count: {referral_count}\n"
        f"🎬 Videos Viewed: {total_video_views}"
    )

    await message.reply_text(profile_text, reply_markup=await get_main_keyboard(user_id))
    logger.info(f"User {user_id} viewed their profile.")

@app.on_message(filters.regex("🔗 Refer & Earn"))
async def refer_and_earn_button_handler(client: Client, message: Message):
    """Handles the 'Refer & Earn' button press."""
    user_id = message.from_user.id
    ref_link = f"https://t.me/{config.BOT_USERNAME.lstrip('@')}?start=ref_{user_id}"
    
    await message.reply_text(
        "Invite your friends and earn tokens!\n\n"
        "Share this link with your friends. When they join using your link, "
        f"you will receive {config.REFERRAL_BONUS} token (each token lasts 24 hours).",
        reply_markup=referral_keyboard(ref_link)
    )
    logger.info(f"User {user_id} accessed 'Refer & Earn'.")

@app.on_message(filters.regex("💰 Buy Token"))
async def buy_token_button_handler(client: Client, message: Message):
    """Handles the 'Buy Token' button press."""
    user_id = message.from_user.id
    
    await message.reply_text(
        "You can buy tokens to get unlimited access to videos!\n\n"
        f"<b>Trial Pack:</b> {config.PREMIUM_TRIAL_PRICE_INR} INR for 1 day\n"
        f"<b>Monthly Pack:</b> {config.PREMIUM_MONTH_PRICE_INR} INR for 30 days\n\n"
        "Click the button below to buy tokens via our support bot.",
        reply_markup=buy_token_keyboard()
    )
    logger.info(f"User {user_id} accessed 'Buy Token'.")

@app.on_message(filters.regex("🔄 Refresh Token"))
async def refresh_token_button_handler(client: Client, message: Message):
    """Handles the 'Refresh Token' button press."""
    user_id = message.from_user.id
    
    if is_premium_user(user_id):
        await message.reply_text("💡 You already have active premium access. No need to refresh yet! Enjoy the videos! 🥳",
                                 reply_markup=await get_main_keyboard(user_id))
        return

    # Generate a unique ad link for token refresh, valid for 10 minutes
    ad_refresh_url = await shorten_url(f"https://t.me/{config.BOT_USERNAME.lstrip('@')}?start=ad_{user_id}:{get_current_time() + 600}")
    
    await message.reply_text(
        "Click the button below to refresh your token! You will get 1 token for 24 hours.\n\n"
        "<b>Note:</b> You can only refresh your token after your current token expires or if you don't have any active tokens.",
        reply_markup=token_earning_keyboard(ad_refresh_url)
    )
    logger.info(f"User {user_id} accessed 'Refresh Token'.")

@app.on_callback_query(filters.regex(r"^share_(.+)$"))
async def share_video_callback_handler(client: Client, callback_query: CallbackQuery):
    """Handles 'Share' button press for a video."""
    user_id = callback_query.from_user.id
    video_uuid = callback_query.matches[0].group(1)
    
    logger.info(f"User {user_id} clicked 'Share' for video {video_uuid}.")
    
    # Generate a deep link for sharing the specific video
    share_link = f"https://t.me/{config.BOT_USERNAME.lstrip('@')}?start=video_{video_uuid}_{user_id}"
    
    await callback_query.answer("Generating share link...")
    await callback_query.edit_message_caption(
        caption=f"{callback_query.message.caption}\n\n"
                f"Share this video with your friends!\n"
                f"<b>Share Link:</b> <code>{share_link}</code>",
        reply_markup=callback_query.message.reply_markup # Keep existing navigation buttons
    )
    
@app.on_callback_query(filters.regex(r"^download_(.+)$"))
async def download_video_callback_handler(client: Client, callback_query: CallbackQuery):
    """Handles 'Download' button press for a video."""
    user_id = callback_query.from_user.id
    video_uuid = callback_query.matches[0].group(1)

    logger.info(f"User {user_id} clicked 'Download' for video {video_uuid}.")

    if not is_premium_user(user_id):
        await callback_query.answer("🚫 This feature is for Premium Users only! Upgrade to download.", show_alert=True)
        return
    
    video = get_video_by_uuid(video_uuid)
    if not video:
        await callback_query.answer("Video not found for download.", show_alert=True)
        return

    try:
        # Send the video without protection, allowing download
        await client.send_video(
            user_id,
            video['file_id'],
            caption=f"⬇️ Here is your requested video for download: {html.escape(video['category'])}",
            protect_content=False # Allow download
        )
        await callback_query.answer("Video sent for download! Check your DMs. ✅", show_alert=True)
        logger.info(f"User {user_id} successfully received video {video_uuid} for download.")
    except Exception as e:
        logger.error(f"Failed to send video {video_uuid} for download to user {user_id}: {e}", exc_info=True)
        await callback_query.answer("Failed to send video for download. Please try again later. 😥", show_alert=True)

# --- New Bookmark Handlers ---
@app.on_message(filters.regex("🔖 Saved Videos"))
async def saved_videos_button_handler(client: Client, message: Message):
    """Handles the 'Saved Videos' button press."""
    user_id = message.from_user.id
    logger.info(f"User {user_id} pressed 'Saved Videos'.")
    
    await message.reply_text("Loading your saved videos... ⏳", reply_markup=await get_main_keyboard(user_id))
    
    await show_saved_videos_list(client, user_id, message.id, page=0)

async def show_saved_videos_list(client: Client, user_id: int, old_message_id: int = None, page: int = 0):
    """Displays a paginated list of bookmarked videos."""
    bookmarked_videos = get_bookmarked_videos(user_id)
    
    if not bookmarked_videos:
        await send_and_replace_message(
            client,
            user_id,
            old_message_id,
            "text",
            text_content="You haven't saved any videos yet! 🤷‍♀️",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎬 Get Video", callback_data="get_video")]])
        )
        return

    videos_per_page = 10
    total_pages = (len(bookmarked_videos) + videos_per_page - 1) // videos_per_page
    current_page = max(0, min(page, total_pages - 1))

    start_index = current_page * videos_per_page
    end_index = start_index + videos_per_page
    paginated_videos = bookmarked_videos[start_index:end_index]

    if not paginated_videos and current_page > 0: # If going to a page that's now empty (e.g. after deleting last video on page)
        current_page -= 1
        start_index = current_page * videos_per_page
        end_index = start_index + videos_per_page
        paginated_videos = bookmarked_videos[start_index:end_index]


    keyboard_buttons = []
    for i, video in enumerate(paginated_videos):
        # Using a direct callback to view a specific saved video by its UUID
        keyboard_buttons.append([InlineKeyboardButton(f"{i+1+start_index}. {html.escape(video.get('category', 'Unknown Category'))}", callback_data=f"view_saved_{video['uuid']}_{current_page}")])

    # Pagination controls
    pagination_buttons = []
    if current_page > 0:
        pagination_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"saved_list_page_{current_page - 1}"))
    pagination_buttons.append(InlineKeyboardButton(f"Page {current_page + 1}/{total_pages}", callback_data="ignore")) # No action
    if current_page < total_pages - 1:
        pagination_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"saved_list_page_{current_page + 1}"))
    
    if pagination_buttons:
        keyboard_buttons.append(pagination_buttons)

    # Add a back to main menu button
    keyboard_buttons.append([InlineKeyboardButton("🏡 Main Menu", callback_data="main_menu")])

    reply_markup = InlineKeyboardMarkup(keyboard_buttons)
    
    await send_and_replace_message(
        client,
        user_id,
        old_message_id,
        "text",
        text_content=f"Your Saved Videos (Page {current_page + 1} of {total_pages}):",
        reply_markup=reply_markup
    )

@app.on_callback_query(filters.regex(r"^saved_list_page_(\d+)$"))
async def saved_list_pagination_handler(client: Client, callback_query: CallbackQuery):
    """Handles pagination for the saved videos list."""
    user_id = callback_query.from_user.id
    page = int(callback_query.matches[0].group(1))
    logger.info(f"User {user_id} navigated to page {page} of saved videos list.")
    
    await callback_query.answer()
    await show_saved_videos_list(client, user_id, callback_query.message.id, page)


@app.on_callback_query(filters.regex(r"^view_saved_(.+)_(\d+)$"))
async def view_saved_video_callback_handler(client: Client, callback_query: CallbackQuery):
    """Views a specific saved video from the list."""
    user_id = callback_query.from_user.id
    video_uuid = callback_query.matches[0].group(1)
    current_list_page = int(callback_query.matches[0].group(2)) # Store for returning to list
    
    logger.info(f"User {user_id} viewing saved video {video_uuid}.")

    video = get_video_by_uuid(video_uuid)
    if not video:
        await callback_query.answer("This saved video could not be found or has been deleted.", show_alert=True)
        # Refresh the saved list
        await show_saved_videos_list(client, user_id, callback_query.message.id, page=current_list_page)
        return

    # For saved videos, premium status doesn't prevent viewing, only limit to 100 on list
    # No need to check for tokens for viewing saved videos
    
    # We create a specific keyboard for saved videos that allows "Next" and "Prev" within the saved list
    # and also a "Remove Bookmark" button.
    # To implement next/prev effectively, we need to know the *index* of this video in the user's *current*
    # bookmarked list (which might be limited to 100 for free users).
    
    bookmarked_videos = get_bookmarked_videos(user_id) # Get the ordered list
    try:
        video_index = next(i for i, v in enumerate(bookmarked_videos) if v['uuid'] == video_uuid)
    except StopIteration:
        # Video was somehow removed from bookmarks or not found in current list
        await callback_query.answer("Video not found in your saved list anymore.", show_alert=True)
        await show_saved_videos_list(client, user_id, callback_query.message.id, page=current_list_page)
        return

    reply_kb = saved_video_nav_keyboard(video_uuid, video_index, len(bookmarked_videos))

    success, result = await send_and_replace_message(
        client,
        user_id,
        callback_query.message.id,
        "video",
        video_data=video,
        reply_markup=reply_kb
    )

    if success:
        await callback_query.answer()
    else:
        await callback_query.answer(f"Failed to load saved video: {result}", show_alert=True)
        logger.error(f"Failed to send saved video {video_uuid} to user {user_id}: {result}")

@app.on_callback_query(filters.regex(r"^saved_(prev|next)_(.+)_(\d+)$"))
async def saved_video_nav_callback_handler(client: Client, callback_query: CallbackQuery):
    """Handles navigation for saved videos."""
    user_id = callback_query.from_user.id
    action = callback_query.matches[0].group(1) # 'prev' or 'next'
    current_video_uuid = callback_query.matches[0].group(2)
    current_index = int(callback_query.matches[0].group(3)) # Index of the current video in the list

    logger.info(f"User {user_id} clicked {action} for saved video {current_video_uuid} at index {current_index}.")

    bookmarked_videos = get_bookmarked_videos(user_id)
    if not bookmarked_videos:
        await callback_query.answer("Your saved videos list is empty.", show_alert=True)
        await show_saved_videos_list(client, user_id, callback_query.message.id) # Go back to empty list
        return

    next_index = current_index
    if action == 'next':
        next_index = (current_index + 1) % len(bookmarked_videos)
    elif action == 'prev':
        next_index = (current_index - 1 + len(bookmarked_videos)) % len(bookmarked_videos)

    if next_index == current_index and len(bookmarked_videos) == 1:
        await callback_query.answer("This is your only saved video.", show_alert=True)
        return

    next_video = bookmarked_videos[next_index]
    
    reply_kb = saved_video_nav_keyboard(next_video['uuid'], next_index, len(bookmarked_videos))

    success, result = await send_and_replace_message(
        client,
        user_id,
        callback_query.message.id,
        "video",
        video_data=next_video,
        reply_markup=reply_kb
    )

    if success:
        await callback_query.answer()
    else:
        await callback_query.answer(f"Failed to load saved video: {result}", show_alert=True)
        logger.error(f"Failed to navigate saved video for user {user_id}: {result}")


@app.on_callback_query(filters.regex(r"^(add|remove)_bookmark_(.+)$"))
async def bookmark_callback_handler(client: Client, callback_query: CallbackQuery):
    """Handles adding and removing bookmarks."""
    user_id = callback_query.from_user.id
    action = callback_query.matches[0].group(1) # 'add' or 'remove'
    video_uuid = callback_query.matches[0].group(2)
    
    logger.info(f"User {user_id} clicked {action} bookmark for video {video_uuid}.")

    if action == "add":
        success, message = add_bookmark(user_id, video_uuid)
    else: # action == "remove"
        success, message = remove_bookmark(user_id, video_uuid)

    await callback_query.answer(message, show_alert=True)

    # Re-send the current video message with updated bookmark button
    # First, get the current video data and its category to rebuild the keyboard
    current_video = get_video_by_uuid(video_uuid)
    if current_video:
        # Check if the callback originated from the main video view or saved video view
        # This is a heuristic based on the presence of "saved_prev" in the original message's reply markup
        is_from_saved_view = False
        if callback_query.message.reply_markup:
            for row in callback_query.message.reply_markup.inline_keyboard:
                for button in row:
                    if button.callback_data and button.callback_data.startswith("saved_prev_"):
                        is_from_saved_view = True
                        break
                if is_from_saved_view:
                    break

        if is_from_saved_view:
            # Need to re-render the saved video navigation keyboard
            bookmarked_videos = get_bookmarked_videos(user_id)
            try:
                video_index = next(i for i, v in enumerate(bookmarked_videos) if v['uuid'] == video_uuid)
            except StopIteration:
                # Video was removed, go back to saved list
                await show_saved_videos_list(client, user_id, callback_query.message.id)
                return

            reply_kb = saved_video_nav_keyboard(video_uuid, video_index, len(bookmarked_videos))
        else:
            # Re-render the regular video navigation keyboard
            reply_kb = video_nav_keyboard(video_uuid, current_video['category'], user_id)

        # Edit the existing message to update the bookmark button
        try:
            await callback_query.edit_message_reply_markup(reply_markup=reply_kb)
        except MessageIdInvalid:
            logger.warning(f"Failed to edit message {callback_query.message.id} for user {user_id} after bookmark action (MessageIdInvalid).")
        except Exception as e:
            logger.error(f"Error editing message {callback_query.message.id} for user {user_id} after bookmark action: {e}")
    else:
        logger.warning(f"Video {video_uuid} not found after bookmark action for user {user_id}. Cannot update message.")

@app.on_callback_query(filters.regex("show_saved_videos_list"))
async def back_to_saved_list_callback_handler(client: Client, callback_query: CallbackQuery):
    """Handles the 'Back to Saved List' button."""
    user_id = callback_query.from_user.id
    logger.info(f"User {user_id} clicked 'Back to Saved List'.")
    
    await callback_query.answer()
    await show_saved_videos_list(client, user_id, callback_query.message.id)

@app.on_callback_query(filters.regex("main_menu"))
async def main_menu_callback_handler(client: Client, callback_query: CallbackQuery):
    """Handles 'Main Menu' button click from inline keyboards."""
    user_id = callback_query.from_user.id
    logger.info(f"User {user_id} clicked 'Main Menu' from inline keyboard.")
    
    await callback_query.answer("Returning to main menu...")
    await send_and_replace_message(
        client,
        user_id,
        callback_query.message.id,
        "text",
        text_content="Welcome back! What would you like to do?",
        reply_markup=await get_main_keyboard(user_id)
    )

@app.on_callback_query(filters.regex("get_video"))
async def get_video_from_inline_handler(client: Client, callback_query: CallbackQuery):
    """Handles 'Get Video' button from inline, e.g., after empty saved list."""
    user_id = callback_query.from_user.id
    logger.info(f"User {user_id} clicked 'Get Video' from inline.")
    
    await callback_query.answer("Getting video categories...")
    
    old_msg_id = callback_query.message.id
    
    categories_kb = category_keyboard()
    if categories_kb.inline_keyboard[0][0].callback_data == "no_cat":
        await send_and_replace_message(
            client,
            user_id,
            old_msg_id,
            "text",
            text_content="😔 No video categories available yet. Please wait for an admin to add some!",
            reply_markup=None
        )
    else:
        await send_and_replace_message(
            client,
            user_id,
            old_msg_id,
            "text",
            text_content="Please choose a category:",
            reply_markup=categories_kb
        )

# --- Inline Search Handler (for sharing videos) ---
@app.on_inline_query()
async def inline_search_handler(client: Client, inline_query: InlineQuery):
    """
    Handles inline queries to allow users to search and share videos.
    For simplicity, this example just provides a static link to the bot.
    A full implementation would involve searching the media_collection.
    """
    query = inline_query.query.strip().lower()
    user_id = inline_query.from_user.id

    articles = []

    # Example: A simple prompt for now. In a real scenario, you'd search your video database.
    # To demonstrate a relevant result for the user's query:
    if query:
        # Here you would fetch videos from your media_collection based on the query.
        # For this example, let's just make a generic suggestion.
        title = f"Search for '{query}' in {config.BOT_USERNAME}"
        description = "Click to share this bot and find videos!"
        input_content = InputTextMessageContent(f"Check out {config.BOT_USERNAME} for amazing videos!")
        url = f"https://t.me/{config.BOT_USERNAME.lstrip('@')}" # Link to your bot
        
        articles.append(
            InlineQueryResultArticle(
                id=str(uuid.uuid4()),
                title=title,
                description=description,
                input_message_content=input_content,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Open Bot", url=url)]
                ])
            )
        )
    else:
        articles.append(
            InlineQueryResultArticle(
                id=str(uuid.uuid4()),
                title=f"Share {config.BOT_USERNAME}",
                description="Click to share this bot with your friends!",
                input_message_content=InputTextMessageContent(f"Come check out {config.BOT_USERNAME} for amazing videos!"),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Open Bot", url=f"https://t.me/{config.BOT_USERNAME.lstrip('@')}")]
                ])
            )
        )

    try:
        await inline_query.answer(
            results=articles,
            cache_time=5 # Cache results for 5 seconds
        )
    except FloodWait as e:
        logger.warning(f"FloodWait on inline query for user {user_id}: {e}")
    except Exception as e:
        logger.error(f"Error handling inline query for user {user_id}: {e}", exc_info=True)


# --- Admin Handlers ---
@app.on_message(filters.command("addcategory") & filters.user(config.ADMIN_IDS))
async def add_category_command(client: Client, message: Message):
    """Admin command to add a new video category."""
    if len(message.command) < 2:
        await message.reply_text("Usage: /addcategory <category_name>")
        return
    
    category_name = message.command[1].strip()
    success, msg = add_category(category_name)
    await message.reply_text(msg)
    if success:
        logger.info(f"Admin {message.from_user.id} added category '{category_name}'.")
    else:
        logger.warning(f"Admin {message.from_user.id} failed to add category '{category_name}': {msg}")

@app.on_message(filters.command("delcategory") & filters.user(config.ADMIN_IDS))
async def del_category_command(client: Client, message: Message):
    """Admin command to delete a video category and its videos."""
    if len(message.command) < 2:
        await message.reply_text("Usage: /delcategory <category_name>")
        return
    
    category_name = message.command[1].strip()
    success, msg, deleted_count = delete_category(category_name)
    await message.reply_text(msg)
    if success:
        logger.info(f"Admin {message.from_user.id} deleted category '{category_name}' and {deleted_count} videos.")
    else:
        logger.warning(f"Admin {message.from_user.id} failed to delete category '{category_name}': {msg}")

@app.on_message(filters.command("allcategories") & filters.user(config.ADMIN_IDS))
async def all_categories_command(client: Client, message: Message):
    """Admin command to list all existing categories."""
    categories = get_categories()
    if not categories:
        await message.reply_text("No categories exist yet.")
        return
    
    categories_list = "\n".join([f"- {html.escape(cat)}" for cat in categories])
    await message.reply_text(f"<b>Existing Categories:</b>\n{categories_list}")
    logger.info(f"Admin {message.from_user.id} requested all categories.")

@app.on_message(filters.command("addvideo") & filters.user(config.ADMIN_IDS))
async def add_video_command(client: Client, message: Message):
    """
    Admin command to add a video.
    Expected usage: Reply to a video with /addvideo <category_name>
    """
    if not message.reply_to_message or not message.reply_to_message.video:
        await message.reply_text("Please reply to a video with this command.")
        return
    
    if len(message.command) < 2:
        await message.reply_text("Usage: Reply to a video with /addvideo <category_name>")
        return

    category_name = message.command[1].strip()
    
    video = message.reply_to_message.video
    
    if not categories_collection.find_one({'name': category_name}):
        await message.reply_text(f"Category '{html.escape(category_name)}' does not exist. Please create it first using /addcategory.")
        return

    # Check if a video with the same file_unique_id already exists
    existing_video = media_collection.find_one({'file_unique_id': video.file_unique_id})
    if existing_video:
        await message.reply_text(f"This video already exists in the database (UUID: <code>{existing_video['uuid']}</code>, Category: {html.escape(existing_video['category'])}).", parse_mode="HTML")
        logger.warning(f"Admin {message.from_user.id} attempted to add duplicate video {video.file_unique_id}.")
        return

    video_data = {
        'uuid': str(uuid.uuid4()),
        'file_id': video.file_id,
        'file_unique_id': video.file_unique_id,
        'category': category_name,
        'duration': video.duration,
        'width': video.width,
        'height': video.height,
        'size_bytes': video.file_size,
        'added_by': message.from_user.id,
        'added_at': datetime.utcnow(),
        'banned': False # Flag for banning content
    }
    
    try:
        media_collection.insert_one(video_data)
        await message.reply_text(
            f"Video added successfully to category '{html.escape(category_name)}'!\n"
            f"UUID: <code>{video_data['uuid']}</code>",
            parse_mode="HTML"
        )
        logger.info(f"Admin {message.from_user.id} added video {video_data['uuid']} to category '{category_name}'.")
    except Exception as e:
        await message.reply_text(f"Failed to add video: {e}")
        logger.error(f"Admin {message.from_user.id} failed to add video to category '{category_name}': {e}", exc_info=True)


@app.on_message(filters.command("stats") & filters.user(config.ADMIN_IDS))
async def stats_command(client: Client, message: Message):
    """Admin command to show bot statistics."""
    total_users = users_collection.count_documents({})
    total_videos = media_collection.count_documents({})
    total_categories = categories_collection.count_documents({})
    
    premium_users_count = users_collection.count_documents({'premium_until': {'$gt': datetime.utcnow()}})
    
    # Aggregate total views
    pipeline = [
        {'$group': {'_id': None, 'total_views': {'$sum': '$total_video_views'}}}
    ]
    result = list(users_collection.aggregate(pipeline))
    total_views = result[0]['total_views'] if result else 0

    stats_text = (
        "<b>📊 Bot Statistics</b>\n\n"
        f"👥 Total Users: {total_users}\n"
        f"🎬 Total Videos: {total_videos}\n"
        f"🗂️ Total Categories: {total_categories}\n"
        f"💎 Premium Users: {premium_users_count}\n"
        f"👁️ Total Video Views: {total_views}\n"
    )
    await message.reply_text(stats_text)
    logger.info(f"Admin {message.from_user.id} requested bot stats.")

@app.on_message(filters.command("banvideo") & filters.user(config.ADMIN_IDS))
async def ban_video_command(client: Client, message: Message):
    """Admin command to ban a video by its UUID."""
    if len(message.command) < 2:
        await message.reply_text("Usage: /banvideo <video_uuid>")
        return
    
    video_uuid = message.command[1].strip()
    
    result = media_collection.update_one({'uuid': video_uuid}, {'$set': {'banned': True}})
    if result.modified_count > 0:
        await message.reply_text(f"Video with UUID <code>{video_uuid}</code> has been banned.", parse_mode="HTML")
        logger.info(f"Admin {message.from_user.id} banned video {video_uuid}.")
    else:
        await message.reply_text(f"Video with UUID <code>{video_uuid}</code> not found or already banned.", parse_mode="HTML")
        logger.warning(f"Admin {message.from_user.id} attempted to ban non-existent or already banned video {video_uuid}.")

@app.on_message(filters.command("unbanvideo") & filters.user(config.ADMIN_IDS))
async def unban_video_command(client: Client, message: Message):
    """Admin command to unban a video by its UUID."""
    if len(message.command) < 2:
        await message.reply_text("Usage: /unbanvideo <video_uuid>")
        return
    
    video_uuid = message.command[1].strip()
    
    result = media_collection.update_one({'uuid': video_uuid}, {'$set': {'banned': False}})
    if result.modified_count > 0:
        await message.reply_text(f"Video with UUID <code>{video_uuid}</code> has been unbanned.", parse_mode="HTML")
        logger.info(f"Admin {message.from_user.id} unbanned video {video_uuid}.")
    else:
        await message.reply_text(f"Video with UUID <code>{video_uuid}</code> not found or not banned.", parse_mode="HTML")
        logger.warning(f"Admin {message.from_user.id} attempted to unban non-existent or not banned video {video_uuid}.")

@app.on_message(filters.command("givepremium") & filters.user(config.ADMIN_IDS))
async def give_premium_command(client: Client, message: Message):
    """Admin command to give premium status to a user."""
    if len(message.command) < 3:
        await message.reply_text("Usage: /givepremium <user_id> <days>")
        return
    
    try:
        target_user_id = int(message.command[1])
        days = int(message.command[2])
    except ValueError:
        await message.reply_text("Invalid user ID or days. User ID must be a number, days must be a number.")
        return
    
    duration_seconds = days * 86400
    added_token = add_token(target_user_id, duration_seconds)
    
    if added_token:
        await message.reply_text(f"Premium status given to user {target_user_id} for {days} days.")
        logger.info(f"Admin {message.from_user.id} gave premium to user {target_user_id} for {days} days.")
        try:
            await client.send_message(
                target_user_id,
                f"🎉 Congratulations! You have received premium access for {days} days from an admin! Enjoy unlimited videos and downloads! 💎"
            )
        except (UserIsBlocked, ChatInvalid):
            logger.warning(f"Could not notify user {target_user_id} about premium (blocked/invalid chat).")
    else:
        await message.reply_text(f"Failed to give premium status to user {target_user_id}.")
        logger.error(f"Admin {message.from_user.id} failed to give premium to user {target_user_id}.")


@app.on_message(filters.command("removepremium") & filters.user(config.ADMIN_IDS))
async def remove_premium_command(client: Client, message: Message):
    """Admin command to remove premium status from a user."""
    if len(message.command) < 2:
        await message.reply_text("Usage: /removepremium <user_id>")
        return
    
    try:
        target_user_id = int(message.command[1])
    except ValueError:
        await message.reply_text("Invalid user ID. User ID must be a number.")
        return
    
    try:
        # Expire all tokens for the user and clear premium_until
        tokens_collection.delete_many({'user_id': target_user_id})
        users_collection.update_one(
            {'user_id': target_user_id},
            {'$unset': {'premium_until': "", 'is_premium': ""}}
        )
        await message.reply_text(f"Premium status removed from user {target_user_id}.")
        logger.info(f"Admin {message.from_user.id} removed premium from user {target_user_id}.")
        try:
            await client.send_message(
                target_user_id,
                "😔 Your premium access has been removed by an admin."
            )
        except (UserIsBlocked, ChatInvalid):
            logger.warning(f"Could not notify user {target_user_id} about premium removal (blocked/invalid chat).")
    except Exception as e:
        await message.reply_text(f"Failed to remove premium status from user {target_user_id}: {e}")
        logger.error(f"Admin {message.from_user.id} failed to remove premium from user {target_user_id}: {e}", exc_info=True)


@app.on_message(filters.command("setcontentprotection") & filters.user(config.ADMIN_IDS))
async def set_content_protection_command(client: Client, message: Message):
    """Admin command to toggle content protection (protect_content) for sent videos."""
    if len(message.command) < 2:
        await message.reply_text("Usage: /setcontentprotection <on|off>")
        return
    
    setting = message.command[1].strip().lower()
    
    if setting == "on":
        settings_collection.update_one({'_id': 'settings'}, {'$set': {'protect_content': True}}, upsert=True)
        await message.reply_text("Content protection for videos is now <b>ON</b> (users cannot forward/save).", parse_mode="HTML")
        logger.info(f"Admin {message.from_user.id} turned ON content protection.")
    elif setting == "off":
        settings_collection.update_one({'_id': 'settings'}, {'$set': {'protect_content': False}}, upsert=True)
        await message.reply_text("Content protection for videos is now <b>OFF</b> (users can forward/save).", parse_mode="HTML")
        logger.info(f"Admin {message.from_user.id} turned OFF content protection.")
    else:
        await message.reply_text("Invalid argument. Use 'on' or 'off'.")

# --- Startup and Shutdown ---
async def main():
    """Main function to start and run the bot."""
    logger.info("Bot starting...")
    await app.start()
    logger.info("Bot started successfully. Listening for messages...")

    # Handle deep links from /start command with payloads
    # This needs to be done after app.start() so Client is available
    @app.on_message(filters.command("start") & filters.private)
    async def start_handler_with_deep_link(client: Client, message: Message):
        if message.command and len(message.command) > 1:
            payload = message.command[1]
            if payload.startswith('video_'):
                try:
                    video_uuid = payload.split('_')[1]
                    logger.info(f"User {message.from_user.id} started with video deep link: {video_uuid}")
                    
                    success, result = await handle_shared_video(client, message.from_user.id, video_uuid)
                    if success:
                        video_data = result
                        # Send the video, similar to how category handler does
                        await send_and_replace_message(
                            client,
                            message.from_user.id,
                            None, # No old message to delete initially for start command
                            "video",
                            video_data=video_data,
                            reply_markup=video_nav_keyboard(video_data['uuid'], video_data['category'], message.from_user.id)
                        )
                        await message.reply_text(
                            "Here's the video you clicked on! What would you like to do next?",
                            reply_markup=await get_main_keyboard(message.from_user.id)
                        )
                    else:
                        await message.reply_text(
                            f"{result}\n\nWhat would you like to do next?",
                            reply_markup=await get_main_keyboard(message.from_user.id)
                        )
                except Exception as e:
                    logger.error(f"Error handling video deep link for user {message.from_user.id}: {e}", exc_info=True)
                    await message.reply_text(
                        "An error occurred while loading the video. Please try again or use the main menu.",
                        reply_markup=await get_main_keyboard(message.from_user.id)
                    )
            elif payload.startswith('ad_'):
                ad_code = payload[3:] # Extract the base64 encoded ad code
                logger.info(f"User {message.from_user.id} started with ad deep link: {ad_code}")
                success, msg = await handle_token_refresh(message.from_user.id, ad_code)
                await message.reply_text(
                    f"{msg}\n\nWhat would you like to do next?",
                    reply_markup=await get_main_keyboard(message.from_user.id)
                )
            else:
                # Fallback to the main start handler for unknown payloads or just /start
                await start_command_handler(client, message)
        else:
            # If no payload, call the regular start handler
            await start_command_handler(client, message)


    # Keep the bot running indefinitely
    await asyncio.Event().wait()

if __name__ == "__main__":
    import time # Moved here to be only imported when actually used by rate limiting
    try:
        create_tracked_task(main()) # Track the main bot task
        asyncio.get_event_loop().run_forever()
    except KeyboardInterrupt:
        logger.info("Bot stopped by KeyboardInterrupt.")
    except Exception as e:
        logger.critical(f"Unhandled exception in main bot loop: {e}", exc_info=True)
    finally:
        logger.info("Bot shutting down. Cancelling active tasks...")
        asyncio.get_event_loop().run_until_complete(cancel_all_active_tasks())
        if app.is_connected:
            asyncio.get_event_loop().run_until_complete(app.stop())
            logger.info("Pyrogram client stopped.")
        client.close()
        logger.info("MongoDB client closed.")
        logger.info("Bot shutdown complete.")
