import os
import asyncio
import uuid
import base64
import random
import logging
from datetime import datetime, timedelta
from pyrogram import Client, filters
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, Message, InlineQueryResultArticle, InputTextMessageContent, CallbackQuery, InputMediaVideo
)
from pyrogram.errors import UserIsBlocked, ChatInvalid, MessageIdInvalid, FloodWait, PeerIdInvalid
from pyrogram.enums import ChatMemberStatus
from pymongo import MongoClient, ASCENDING, ReturnDocument
import aiohttp
from aiohttp import ClientTimeout
from collections import defaultdict
import re
import html
import urllib.parse # Added for URL encoding
from shortzy import Shortzy # Import the Shortzy library

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Configuration ---
class BotConfig:
    BOT_TOKEN = '7770483831:AAE2zVM2n4B4o1FnTipudnrQeb8k2k1t_1Y'
    API_ID = 29800015
    API_HASH = 'c8f37108be31ab9ea2818bfe533fbb6f'
    BOT_USERNAME = '@Pyasirandbot' # Ensure this is your bot's actual username without the 't.me/' or 'https://t.me/' prefix
    MONGO_URI = 'mongodb+srv://Pyasipriya:00pEcao9sYhNC5VQ@cluster0.2dfenf7.mongodb.net/spicybot?retryWrites=true&w=majority&appName=Cluster0'
    MONGO_DB_NAME = 'spicybot'
    VIDEO_CHANNEL_ID = -1002621716446
    BUY_BOT_URL = 'https://t.me/hanielxsupportbot'
    ADMIN_IDS = [6612030110]
    TUTORIAL_LINK_2 = 'https://t.me/urlshortenertutorial'
    TOKEN_EXPIRY = 86400  # 24 hours in seconds (for regular tokens, not premium)
    NEW_USER_TOKENS = 1
    REFERRAL_BONUS = 1
    REFRESH_BONUS = 1
    MENU_TIMEOUT = 3600 # 1 hour in seconds, for soft expiry check, now less critical
    PREMIUM_TRIAL_PRICE_INR = 69
    PREMIUM_MONTH_PRICE_INR = 169
    SUPPORT_BOT_USERNAME = 'hanielxsupportbot' # Support bot username for inline button
    FREE_USER_SAVE_LIMIT = 100 # Maximum saved videos for free users
    FORCE_SUB_CHANNEL_ID = -1002622483638  # New: Channel ID for force subscription
    FORCE_SUB_CHANNEL_LINK = "https://t.me/SpicyNyraa" # New: Link to the force subscribe channel

try:
    config = BotConfig()
    if not all([config.BOT_TOKEN, config.API_ID, config.API_HASH, config.MONGO_URI, config.BOT_USERNAME, config.FORCE_SUB_CHANNEL_ID, config.FORCE_SUB_CHANNEL_LINK]):
        raise ValueError("One or more essential configuration variables are not set. Please check BOT_TOKEN, API_ID, API_HASH, MONGO_URI, BOT_USERNAME, FORCE_SUB_CHANNEL_ID, FORCE_SUB_CHANNEL_LINK.")
except Exception as e:
    raise RuntimeError(f"Failed to load bot configuration: {e}")

# --- MongoDB Setup ---
client = MongoClient(config.MONGO_URI)
db = client[config.MONGO_DB_NAME]
users_collection = db['users']
tokens_collection = db['tokens']
media_collection = db['media']
history_collection = db['history'] # General history, no longer used for prev/next navigation
categories_collection = db['categories']
settings_collection = db['settings'] # This collection will now store shortener config

# Create indexes
users_collection.create_index([("user_id", ASCENDING)], unique=True)
tokens_collection.create_index([("user_id", ASCENDING)], unique=True) # Ensure this index exists
media_collection.create_index([("uuid", ASCENDING)], unique=True)
media_collection.create_index([("category", ASCENDING)])
media_collection.create_index([("file_unique_id", ASCENDING)], unique=True)
media_collection.create_index([("size_bytes", ASCENDING)])
history_collection.create_index([("user_id", ASCENDING)], unique=True)
categories_collection.create_index([("name", ASCENDING)], unique=True)

# --- Pyrogram Client ---
app = Client("/data/spicynyraa", api_id=config.API_ID, api_hash=config.API_HASH, bot_token=config.BOT_TOKEN)

# --- GLOBAL SET FOR TRACKING ASYNC TASKS ---
active_tasks = set()

# --- Admin State for Shortener Setup ---
# Stores the current step for each admin in the /setshortener flow
admin_shortener_setup_state = defaultdict(dict) 

# --- Admin State for Delete Video ---
admin_delete_video_state = defaultdict(bool)

# --- Admin State for Category Rename ---
admin_rename_category_state = defaultdict(dict)


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
        active_tasks.clear()
        logger.info("Active tasks set cleared.")

# --- Admin Check Utility ---
def is_admin(user_id: int) -> bool:
    """Checks if the given user ID belongs to an administrator."""
    return user_id in config.ADMIN_IDS

# --- Force Subscribe Check ---
async def check_membership(client: Client, user_id: int) -> bool:
    """
    Checks if the user is a member of the force subscribe channel.
    Returns True if a member (or admin), False otherwise.
    """
    if is_admin(user_id):
        return True # Admins bypass force subscribe

    try:
        member = await client.get_chat_member(config.FORCE_SUB_CHANNEL_ID, user_id)
        if member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            logger.info(f"User {user_id} is a member of force sub channel {config.FORCE_SUB_CHANNEL_ID}.")
            return True
        else:
            logger.info(f"User {user_id} is NOT a member of force sub channel {config.FORCE_SUB_CHANNEL_ID}. Status: {member.status}")
            return False
    except PeerIdInvalid:
        logger.error(f"Force subscribe channel ID {config.FORCE_SUB_CHANNEL_ID} is invalid. Please check config.")
        return True # Treat as member if channel ID is invalid to avoid blocking all users
    except Exception as e:
        logger.error(f"Error checking membership for user {user_id} in channel {config.FORCE_SUB_CHANNEL_ID}: {e}", exc_info=True)
        return False # Default to false on error

async def send_force_subscribe_message(client: Client, chat_id: int):
    """Sends a message prompting the user to join the force subscribe channel."""
    logger.info(f"Sending force subscribe message to user {chat_id}.")
    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Join Channel", url=config.FORCE_SUB_CHANNEL_LINK)]
    ])
    await client.send_message(
        chat_id,
        "<b>⚠️ You must join our channel to use this bot.</b>\n\n"
        "Please join the channel below and then try again. Once you join, click the '🎞️ Get Video' button or send /start again.",
        reply_markup=reply_markup
    )

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
        
    # Parse the template_url to extract base_site and api_key for Shortzy
    try:
        parsed_url = urllib.parse.urlparse(template_url)
        base_site = parsed_url.netloc # e.g., 'get2short.com'
        
        # Extract API key from query parameters
        query_params = urllib.parse.parse_qs(parsed_url.query)
        api_key_list = query_params.get('api')
        
        if not api_key_list:
            logger.warning("No 'api' key found in the template_url query parameters. Cannot initialize Shortzy. Returning original URL.")
            return long_url
        
        api_key = api_key_list[0] # Take the first API key if multiple are present
        
        # Shortzy expects base_site without http/https prefix
        if base_site.startswith("http://"):
            base_site = base_site[len("http://"):]
        elif base_site.startswith("https://"):
            base_site = base_site[len("https://"):]

        # If there's a path in the base_site, Shortzy might expect just the domain.
        # Let's try with just the netloc first.
        base_site = parsed_url.netloc

        # Initialize Shortzy client
        shortzy_client = Shortzy(api_key=api_key, base_site=base_site)
        logger.info(f"Initialized Shortzy with base_site: {base_site}, api_key: {'*' * len(api_key)}")

        # Shorten the URL
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
    If is_admin_granted is True, this token signifies premium access.
    """
    now = datetime.utcnow()
    expires_at = now + timedelta(seconds=duration_seconds)
    token = {
        'token_id': str(uuid.uuid4()),
        'created_at': now,
        'expires_at': expires_at,
        'is_admin_granted': is_admin_granted # New field to distinguish premium tokens
    }
    try:
        tokens_collection.update_one(
            {'user_id': user_id},
            {'$push': {'tokens': token}},
            upsert=True
        )
        logger.info(f"Token added for user {user_id}. Admin granted: {is_admin_granted}, expires at {expires_at}")
        return token
    except Exception as e:
        logger.error(f"Error adding token for user {user_id}: {e}", exc_info=True)
        return None

def is_premium_user(user_id: int) -> bool:
    """Checks if a user is a premium user (has an active admin-granted token)."""
    now = datetime.utcnow()
    doc = tokens_collection.find_one({'user_id': user_id})
    if not doc or 'tokens' not in doc:
        return False
    
    for token in doc['tokens']:
        # Premium status is tied to tokens explicitly granted by an admin
        if token.get('is_admin_granted', False) and token.get('expires_at') and token['expires_at'] > now:
            return True
    return False

def user_has_token(user_id: int) -> bool:
    """Checks if a user has any valid tokens (admin-granted or not) for general access."""
    now = datetime.utcnow()
    doc = tokens_collection.find_one({'user_id': user_id})
    if not doc or 'tokens' not in doc:
        return False
        
    for token in doc['tokens']:
        if token.get('expires_at') and token['expires_at'] > now:
            return True
    return False

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

    # If the user was premium and is now not premium, send a notification
    if last_known_premium_status and not current_premium_status:
        try:
            await client.send_message(user_id, "⚠️ <b>Your Premium Access Has Expired!</b> 💔\n\nYour premium token has expired. You are no longer a premium user. Enjoy regular features or purchase new premium access! 🛒")
            logger.info(f"Notified user {user_id} about premium expiry.")
        except (UserIsBlocked, ChatInvalid):
            logger.warning(f"Could not notify user {user_id} about premium expiry; user blocked or chat invalid.")
        except Exception as e:
            logger.error(f"Failed to send premium expiry notification to user {user_id}: {e}")

    # Update the last_premium_check_status in the database
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
                # Referral bonus token is NOT an admin-granted premium token
                add_token(referrer_id, config.REFERRAL_BONUS * 86400, is_admin_granted=False)
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
                        # Referral bonus token from video share is NOT an admin-granted premium token
                        add_token(referrer_id, config.REFERRAL_BONUS * 86400, is_admin_granted=False)
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
    """
    Saves a video viewing entry to a user's general history (limited to 100 entries)
    AND updates the last viewed video for the specific category.
    """
    now = datetime.utcnow()
    entry = {'video_uuid': video_uuid, 'category': category, 'viewed_at': now}
    try:
        # Update general history (for profile view count, etc.)
        history_collection.update_one(
            {'user_id': user_id},
            {'$push': {'history': {'$each': [entry], '$slice': -100}}},
            upsert=True
        )
        logger.info(f"General history saved for user {user_id}, video {video_uuid}. History size limited to 100.")

        # Update last viewed video for this specific category
        users_collection.update_one(
            {'user_id': user_id},
            {'$set': {f'last_viewed_per_category.{category}': video_uuid}},
            upsert=True # Ensure the user document exists
        )
        logger.info(f"Last viewed video for category '{category}' updated to '{video_uuid}' for user {user_id}.")

    except Exception as e:
        logger.error(f"Error saving history/last viewed for user {user_id}, video {video_uuid}: {e}", exc_info=True)

def get_last_video_from_history(user_id: int) -> dict | None:
    """
    Retrieves the last viewed video from a user's general history (the one before the current latest).
    This function is primarily for general history purposes, not for prev/next navigation in categories.
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

async def send_and_replace_message(client: Client, chat_id: int, message_id_to_edit_or_delete: int, new_message_type: str, video_data: dict = None, reply_markup: InlineKeyboardMarkup = None, text_content: str = None) -> tuple[bool, Message | str]:
    """
    Deletes the old message (if provided) and sends a new one.
    This function is designed to replace one message with another, regardless of type.
    Updates the active_video_message tracking.
    Returns (success: bool, sent_message: Message | error_message: str)
    """
    sent_message = None
    success = False
    error_message = ""

    settings = settings_collection.find_one({'_id': 'settings'}) or {}
    protect_content_for_user = settings.get('protect_content', True)

    try:
        # Always attempt to delete the old message first when replacing with a different type of content
        if message_id_to_edit_or_delete:
            try:
                await client.delete_messages(chat_id, message_id_to_edit_or_delete)
                logger.info(f"Deleted old message {message_id_to_edit_or_delete} in chat {chat_id} before sending new.")
            except MessageIdInvalid:
                logger.warning(f"Old message {message_id_to_edit_or_delete} for deletion in chat {chat_id} was already invalid or deleted.")
            except Exception as e:
                logger.error(f"Failed to delete old message {message_id_to_edit_or_delete} in chat {chat_id}: {e}")
        
        # Now send the new message
        if new_message_type == "video" and video_data:
            caption_text = None
            if video_data.get('custom_caption'):
                caption_text = video_data['custom_caption']
            elif video_data.get('category'):
                caption_text = f"Category: {html.escape(video_data['category'])}"
            
            try:
                # Try to send by copying from channel (if possible)
                sent_message = await client.copy_message(
                    chat_id=chat_id,
                    from_chat_id=config.VIDEO_CHANNEL_ID,
                    message_id=video_data.get('message_id'),
                    caption=caption_text,
                    protect_content=protect_content_for_user,
                    reply_markup=reply_markup
                )
                success = True
            except Exception as e:
                logger.warning(f"Failed to copy video from channel by message_id: {e}. Falling back to file_id.")
                # Fallback: send by file_id
                try:
                    sent_message = await client.send_video(
                        chat_id,
                        video_data['file_id'],
                        caption=caption_text,
                        reply_markup=reply_markup,
                        protect_content=protect_content_for_user
                    )
                    success = True
                except FloodWait as fw:
                    logger.warning(f"FloodWait encountered when sending video by file_id: {fw.value}s. Retrying after delay.")
                    await client.send_message(chat_id, f"⚠️ Flood control triggered! Waiting for {fw.value} seconds before sending video. ⏳")
                    await asyncio.sleep(fw.value + 1)
                    try:
                        sent_message = await client.send_video(
                            chat_id,
                            video_data['file_id'],
                            caption=caption_text,
                            reply_markup=reply_markup,
                            protect_content=protect_content_for_user
                        )
                        success = True
                    except Exception as e2:
                        logger.error(f"Failed to send video by file_id after FloodWait: {e2}")
                        error_message = f"❌ <b>Failed to send message.</b>\nReason: {e2}\nPlease try again later. 😥"
                        success = False
                except Exception as e2:
                    logger.error(f"Failed to send video by file_id: {e2}")
                    error_message = f"❌ <b>Failed to send message.</b>\nReason: {e2}\nPlease try again later. 😥"
                    success = False
        elif new_message_type == "text" and text_content:
            try:
                sent_message = await client.send_message(
                    chat_id,
                    text_content,
                    reply_markup=reply_markup
                )
                success = True
            except FloodWait as fw:
                logger.warning(f"FloodWait encountered when sending text: {fw.value}s. Retrying after delay.")
                await client.send_message(chat_id, f"⚠️ Flood control triggered! Waiting for {fw.value} seconds before sending text message. ⏳")
                await asyncio.sleep(fw.value + 1)
                try:
                    sent_message = await client.send_message(
                        chat_id,
                        text_content,
                        reply_markup=reply_markup
                    )
                    success = True
                except Exception as e2:
                    logger.error(f"Failed to send text after FloodWait: {e2}")
                    error_message = f"❌ <b>Failed to send message.</b>\nReason: {e2}\nPlease try again later. 😥"
                    success = False
            except Exception as e:
                logger.error(f"Failed to send text message: {e}")
                error_message = f"❌ <b>Failed to send message.</b>\nReason: {e}\nPlease try again later. 😥"
                success = False
        else:
            error_message = "Invalid new_message_type or missing data for sending."
            logger.error(error_message)

    except Exception as e:
        logger.error(f"An unexpected error occurred in send_and_replace_message: {e}", exc_info=True)
        error_message = f"❌ <b>An unexpected error occurred.</b>\nReason: {e}\nPlease try again later. 😥"
        success = False

    if success and isinstance(sent_message, Message):
        set_active_video_message(chat_id, sent_message.id, chat_id) # Always update the active message, even if ID is same
        logger.info(f"Message {sent_message.id} of type {new_message_type} sent and active video message updated for user {chat_id}.")
        return True, sent_message
    else:
        logger.error(f"Failed to send message in send_and_replace_message: {error_message}")
        return False, error_message

# --- Keyboards ---
async def get_main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    """Main keyboard for the bot."""
    buttons = [
        [KeyboardButton("🎞️ Get Video"), KeyboardButton("👤 Profile")],
        [KeyboardButton("🔗 Refer & Earn"), KeyboardButton("💰 Buy Token")],
        [KeyboardButton("🔄 Refresh Token"), KeyboardButton("🔖 Saved Videos")] # Added Saved Videos button
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
    """Keyboard for selecting video categories, including Saved Videos."""
    cats = get_categories()
    if not cats:
        return InlineKeyboardMarkup([[InlineKeyboardButton("😔 No Categories Available", callback_data="no_cat")]])
    
    # Existing category buttons
    buttons = [[InlineKeyboardButton(f"🎬 {html.escape(cat)}", callback_data=f"cat_{cat}")] for cat in cats]
    # Add "Saved Videos" button
    buttons.append([InlineKeyboardButton("🔖 Saved Videos", callback_data="cat_saved_videos")])
    return InlineKeyboardMarkup(buttons)

def video_nav_keyboard(video_uuid: str, category: str, user_id: int, is_saved: bool = False) -> InlineKeyboardMarkup:
    """
    Keyboard for navigating videos, with button arrangements based on whether it's a saved video.
    The 'Download' button is now always shown.
    """
    buttons = []

    # Row 1: Previous and Next
    buttons.append([
        InlineKeyboardButton("⬅️ Previous", callback_data=f"prev|{video_uuid}|{category}"),
        InlineKeyboardButton("➡️ Next", callback_data=f"next|{video_uuid}|{category}")
    ])

    # Row 2: Categories, Share, and Download (always visible)
    row_2_buttons = [
        InlineKeyboardButton("🗂️ Change Category", callback_data="change_cat"),
        InlineKeyboardButton("📲 Share", callback_data=f"share_{video_uuid}"),
        InlineKeyboardButton("⬇️ Download", callback_data=f"download_{video_uuid}") # Always visible
    ]
    buttons.append(row_2_buttons)

    # Row 3: Bookmark or Remove and Bookmark based on is_saved
    row_3_buttons = []
    if is_saved:
        row_3_buttons.append(InlineKeyboardButton("🗑️ Remove", callback_data=f"remove_saved_{video_uuid}"))
    # The user's format implies bookmark is always present,
    # and for saved videos, it's on the same row as remove.
    row_3_buttons.append(InlineKeyboardButton("💾 Bookmark", callback_data=f"bookmark_{video_uuid}"))
    
    # Only add row 3 if there are buttons in it
    if row_3_buttons:
        buttons.append(row_3_buttons)

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

        # If user is currently premium (via admin-granted token), they don't need a free token refresh
        if is_premium_user(user_id):
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
            
        # Add a regular (non-premium) token
        added_token = add_token(user_id, config.REFRESH_BONUS * 86400, is_admin_granted=False)
        if added_token:
            logger.info(f"Token added for user {user_id} via refresh. Premium status unaffected.")
            return True, f"🎉 <b>Success!</b> You got {config.REFRESH_BONUS} token. Each token lasts 24 hours. Enjoy! 🍿"
        else:
            return False, "❌ <b>Something went wrong!</b>\nFailed to add token. Please try again later. 🛠️"
    except Exception as e:
        logger.error(f"Token refresh failed for user {user_id}: {e}", exc_info=True)
        return False, "❌ <b>Something went wrong!</b>\nPlease try again later. 🤷‍♀️"

# --- Rate Limiting ---
RATE_LIMIT_WINDOW = 120  # 2 minutes
RATE_LIMIT_MAX = 60  # 60 requests per 2 minutes

async def is_rate_limited(user_id: int) -> bool:
    """
    Checks if a user is rate-limited based on their recent requests.
    Stores request timestamps in MongoDB for persistence.
    """
    if is_admin(user_id):
        return False
        
    now = datetime.utcnow()
    window_start = now - timedelta(seconds=RATE_LIMIT_WINDOW)
    
    try:
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

# --- Handlers ---
@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    username_safe = html.escape(message.from_user.username) if message.from_user.username else ""
    first_name_safe = html.escape(message.from_user.first_name) if message.from_user.first_name else "there"
    max_retries = 3

    for attempt in range(max_retries):
        try:
            # Force Subscribe Check
            if not await check_membership(client, user_id):
                await send_force_subscribe_message(client, user_id)
                return # Stop processing if not a member

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
                    'referral_count': 0,
                    'bookmarked_videos': [],
                    'last_premium_check_status': False, # Track last premium status for notifications
                    'last_viewed_per_category': {} # New field to store last viewed video per category
                })
                # New user token is NOT an admin-granted premium token
                add_token(user_id, config.NEW_USER_TOKENS * 86400, is_admin_granted=False)
                logger.info(f"New user registered: {user_id} and received {config.NEW_USER_TOKENS} token.")

            # Check and notify about premium status change (if they just lost premium)
            create_tracked_task(check_premium_status_and_notify(client, user_id))

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
                    deep_link_data = video_uuid_from_link
                elif deep_link_arg.startswith('ref_'):
                    deep_link_type = 'referral'
                    deep_link_data = deep_link_arg
                elif deep_link_arg.startswith('saved_video_'): # Handle direct link to a saved video from /savedvideos
                    deep_link_type = 'view_saved_video'
                    video_uuid_from_link = deep_link_arg[12:]
                    deep_link_data = video_uuid_from_link

            if is_new_user:
                if deep_link_type == 'referral':
                    referrer_id = handle_referral(user_id, deep_link_data)
                    if referrer_id:
                        await message.reply(
                            f"👋 Congratulations, {first_name_safe}! 🎉 You've received {config.NEW_USER_TOKENS} token 🌶️. To watch spicy content, click on the '🎞️ Get Video' button. Need help? Tap /help. ✨", 
                            reply_markup=await get_main_keyboard(user_id)
                        )
                        await client.send_message(referrer_id, f"🎉 **Referral Bonus!** Your friend, {first_name_safe}, joined through your link! You've received {config.REFERRAL_BONUS} token. Awesome! 🤩")
                elif deep_link_type == 'video_share' and referrer_id_from_video_link and referrer_id_from_video_link != user_id:
                    referrer_user_obj = users_collection.find_one({'user_id': referrer_id_from_video_link})
                    if referrer_user_obj:
                        await message.reply(
                            f"👋 Congratulations, {first_name_safe}! 🎉 You've received {config.NEW_USER_TOKENS} token 🌶️. To watch spicy content, click on the '🎞️ Get Video' button. Need help? Tap /help. ✨", 
                            reply_markup=await get_main_keyboard(user_id)
                        )
                        await client.send_message(referrer_id_from_video_link, f"🎉 **Referral Bonus!** Your friend, {first_name_safe}, joined through your shared video link! You've received {config.REFERRAL_BONUS} token. Awesome! 🤩")
                    else:
                        logger.warning(f"Referrer {referrer_id_from_video_link} not found for new user {user_id} via video share. Still sending new user welcome.")
                        await message.reply(
                            f"👋 Congratulations, {first_name_safe}! 🎉 You've received {config.NEW_USER_TOKENS} token 🌶️. To watch spicy content, click on the '🎞️ Get Video' button. Need help? Tap /help. ✨", 
                            reply_markup=await get_main_keyboard(user_id)
                        )
                else:
                    # New user with no referral/video deep link
                    await message.reply(
                        f"👋 Congratulations, {first_name_safe}! 🎉 You've received {config.NEW_USER_TOKENS} token 🌶️. To watch spicy content, click on the '🎞️ Get Video' button. Need help? Tap /help. ✨", 
                        reply_markup=await get_main_keyboard(user_id)
                    )
            elif not deep_link_type:
                # Existing user, no deep link
                await message.reply(
                    f"👋 Welcome back, {first_name_safe}! 🌶️ To watch spicy content, click on the '🎞️ Get Video' button. Need help? Tap /help. ✨", 
                    reply_markup=await get_main_keyboard(user_id)
                )

            if deep_link_type == 'token_refresh':
                success, msg = await handle_token_refresh(user_id, deep_link_data)
                await message.reply(msg)
                if success:
                    await message.reply(
                        "🎉 <b>Success!</b> Click on '🎞️ Get Video' to watch spicy content.",
                        reply_markup=await get_main_keyboard(user_id)
                    )
            elif deep_link_type == 'video_share' or deep_link_type == 'view_saved_video':
                logger.info(f"User {user_id} attempting to view shared/saved video {video_uuid_from_link}")
                            
                try:
                    uuid.UUID(video_uuid_from_link)
                except ValueError:
                    logger.warning(f"User {user_id} attempted to view shared/saved video with invalid UUID format: {video_uuid_from_link}.")
                    await message.reply("Invalid video link format. 🐛", reply_markup=await get_main_keyboard(user_id))
                    break

                video_found_in_db = media_collection.find_one({'uuid': video_uuid_from_link})
                if not video_found_in_db:
                    logger.warning(f"User {user_id} attempted to view non-existent shared/saved video UUID {video_uuid_from_link}.")
                    await message.reply("Invalid video link. 😔", reply_markup=await get_main_keyboard(user_id))
                    break

                if is_new_user and referrer_id_from_video_link:
                    handle_referral(user_id, deep_link_arg)
                
                if not user_has_token(user_id): # This checks for general tokens for video access
                    await message.reply("You need a token to watch this video. Please get a token first! 🧐", reply_markup=await get_main_keyboard(user_id))
                    await send_token_earning_options(client, message)
                    break
                else:
                    success, result_or_msg = await handle_shared_video(client, user_id, video_uuid_from_link)
                    if not success:
                        await message.reply(result_or_msg, reply_markup=await get_main_keyboard(user_id))
                        break

                    video = result_or_msg
                    
                    # For /start deep links, we want to replace the /start message itself
                    message_id_to_edit_or_delete = message.id
                    
                    # Pass is_saved=True if it came from a saved video link
                    is_saved_video_link = (deep_link_type == 'view_saved_video')
                    sent_success, sent_message_or_error = await send_and_replace_message(
                        client,
                        message.chat.id,
                        message_id_to_edit_or_delete=message_id_to_edit_or_delete,
                        new_message_type="video",
                        video_data=video,
                        reply_markup=video_nav_keyboard(video['uuid'], video['category'], user_id, is_saved=is_saved_video_link)
                    )
                    
                    if sent_success:
                        save_history(user_id, video['uuid'], video['category'])
                        logger.info(f"User {user_id} sent shared/saved video {video_uuid_from_link} as new menu.")
                    else:
                        await message.reply(sent_message_or_error)
                break
            
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

@app.on_message(filters.command("help") & filters.private)
async def help_cmd(client: Client, message: Message):
    """Handles the /help command."""
    user_id = message.from_user.id
    # Force Subscribe Check
    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    user_mention_safe = html.escape(message.from_user.first_name) if message.from_user.first_name else "there"
    # Check and notify about premium status change
    create_tracked_task(check_premium_status_and_notify(client, user_id))

    await message.reply(
        f"👋 dear {user_mention_safe}! This is how to use Spicy Nyraa Bot! 📚\n\n"
        "- Use '🎞️ Get Video' to watch spicy content. 🔥\n"
        "- Each token gives you 24 hours access. ⏳\n"
        "- Earn tokens by referral, refreshing ads, or buying them. 💰\n"
        "- Use '👤 Profile' to check your stats. 📈\n"
        "- Use '🔖 Saved Videos' to view your bookmarked videos. ❤️\n\n"
        "Enjoy your spicy journey! 🌶️",
        reply_markup=await get_main_keyboard(user_id)
    )

@app.on_message(filters.command("profile") & filters.private)
async def profile_cmd(client: Client, message: Message):
    """Handles the /profile command to show user statistics."""
    user_id = message.from_user.id
    logger.info(f"User {user_id} requested profile.")
    
    # Force Subscribe Check
    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    # Check and notify about premium status change
    create_tracked_task(check_premium_status_and_notify(client, user_id))

    if await is_rate_limited(user_id):
        await handle_error(client, message, FloodWait(10))
        logger.warning(f"User {user_id} hit rate limit in profile_cmd.")
        return

    user = users_collection.find_one({'user_id': user_id})
    tokens_doc = tokens_collection.find_one({'user_id': user_id})
    
    # Only count non-admin granted tokens for 'Tokens' display, or perhaps total active tokens
    # For simplicity, count all active tokens for "Tokens"
    tokens_count = 0
    if tokens_doc and 'tokens' in tokens_doc:
        now = datetime.utcnow()
        tokens_count = sum(1 for token in tokens_doc['tokens'] if token.get('expires_at') and token['expires_at'] > now)

    referral_count = user.get('referral_count', 0) if user else 0
    referred_by = user.get('referred_by', None) if user else None
    bookmarked_videos = user.get('bookmarked_videos', [])
    
    # Determine user status and save limit
    is_premium = is_premium_user(user_id) # Uses the new logic
    user_status = "Premium User 💎" if is_premium else "Free User ✨"
    
    if is_premium:
        save_limit_display = f"{len(bookmarked_videos)}/Unlimited"
    else:
        save_limit_display = f"{len(bookmarked_videos)}/{config.FREE_USER_SAVE_LIMIT}"


    views_doc = history_collection.find_one({'user_id': user_id})
    view_count = len(views_doc['history']) if views_doc and 'history' in views_doc else 0
    ref_link = f"https://t.me/{config.BOT_USERNAME[1:]}?start=ref_{user_id}"
    
    await message.reply(
        f"👤 <b>Your Profile</b> ✨\n\n"
        f"<b>Status:</b> {user_status}\n" # Display user status here
        f"<b>Tokens:</b> {tokens_count} 🪙\n" # Displays count of all active tokens
        f"<b>Video Views:</b> {view_count} 🎞️\n"
        f"<b>Saved Videos:</b> {save_limit_display} ❤️\n" # Display saved video count/limit
        f"<b>Referrals:</b> {referral_count} 👥\n"
        f"<b>Referral Link:</b> <code>{html.escape(ref_link)}</code> 🔗\n"
        f"{(f'Referred by: {referred_by} 👋') if referred_by else ''}",
        reply_markup=referral_keyboard(ref_link)
    )

@app.on_message(filters.regex("^🎞️ Get Video$") & filters.private)
async def get_video(client: Client, message: Message):
    """Handles the 'Get Video' button request."""
    user_id = message.from_user.id
    chat_id = message.chat.id
    logger.info(f"User {user_id} requested Get Video.")
    
    # Force Subscribe Check
    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    # Check and notify about premium status change
    create_tracked_task(check_premium_status_and_notify(client, user_id))

    if await is_rate_limited(user_id):
        await handle_error(client, message, FloodWait(10))
        logger.warning(f"User {user_id} hit rate limit in get_video.")
        return
        
    if not user_has_token(user_id):
        logger.info(f"User {user_id} has no tokens, prompting earning options.")
        await send_token_earning_options(client, message)
        return
    
    # When 'Get Video' is clicked, we want to replace the current message (e.g., the main keyboard message)
    # with the category selection menu.
    message_id_to_edit_or_delete = message.id # Use the ID of the message that triggered this handler

    cats = get_categories()
    if not cats:
        # If no categories, we still want to delete the original message if it was a button click
        if message_id_to_edit_or_delete:
            try:
                await client.delete_messages(chat_id, message_id_to_edit_or_delete)
            except MessageIdInvalid:
                pass
            except Exception as e:
                logger.warning(f"Failed to delete old message {message_id_to_edit_or_delete} for user {user_id}: {e}")

        await message.reply("😔 No categories available. Please ask an admin to add some! 🛠️")
        logger.info(f"No categories found for user {user_id}.")
        return

    logger.info(f"User {user_id} prompted to choose category.")
    
    sent_success, sent_message_or_error = await send_and_replace_message(
        client,
        chat_id,
        message_id_to_edit_or_delete=message_id_to_edit_or_delete, # Pass the message ID to be edited/deleted
        new_message_type="text",
        text_content="🎬 <b>Choose a Category:</b>",
        reply_markup=category_keyboard()
    )

    if not sent_success:
        await message.reply(sent_message_or_error)
        logger.error(f"User {user_id} failed to send category selection message: {sent_message_or_error}")

@app.on_callback_query(filters.regex(r"^cat_(.+)$"))
async def select_category(client: Client, callback_query: CallbackQuery):
    """Handles category selection callback."""
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id
    category = callback_query.data[4:]
    logger.info(f"User {user_id} selected category: {category}.")
    
    # Force Subscribe Check
    if not await check_membership(client, user_id):
        await callback_query.answer("You must join our channel first!", show_alert=True)
        await send_force_subscribe_message(client, user_id)
        return

    # Check and notify about premium status change
    create_tracked_task(check_premium_status_and_notify(client, user_id))

    if await is_rate_limited(user_id):
        await callback_query.answer("⚠️ Too many category changes. Wait 1 min. ⏳", show_alert=True)
        logger.warning(f"User {user_id} hit rate limit in select_category.")
        return
        
    current_active_tracked_message = active_video_message.get(user_id)
    # Check if the callback is from the currently tracked message.
    # If not, it means the menu might have expired or a new interaction started.
    if not current_active_tracked_message or current_active_tracked_message.get('message_id') != callback_query.message.id:
        logger.warning(f"User {user_id} tried to select category but current menu expired or callback not from active menu. Callback Message ID: {callback_query.message.id}, Active Menu ID: {current_active_tracked_message.get('message_id') if current_active_tracked_message else 'None'}")
        await callback_query.answer("Menu expired. Click '🎞️ Get Video' to restart. ⏰", show_alert=True)
        # If the callback message is different from the tracked one, delete it to clean up.
        if current_active_tracked_message and callback_query.message.id != current_active_tracked_message.get('message_id'):
            try:
                await client.delete_messages(callback_query.message.chat.id, callback_query.message.id)
            except MessageIdInvalid:
                pass
            except Exception as e:
                logger.warning(f"Failed to delete non-active menu message for user {user_id}: {e}")
        clear_active_video_message(user_id) # Clear the state, forcing a fresh start
        await client.send_message(chat_id, "Your menu has expired. Please click '🎞️ Get Video' to get a new one. ⏰")
        return

    # Handle "saved_videos" category selection directly
    if category == "saved_videos":
        user = users_collection.find_one({'user_id': user_id})
        if not user or not user.get('bookmarked_videos'):
            await callback_query.answer("You haven't saved any videos yet. ❤️", show_alert=True)
            await callback_query.message.edit_text(
                "You haven't saved any videos yet. ❤️",
                reply_markup=category_keyboard() 
            )
            return

        bookmarked_videos = user['bookmarked_videos']
        
        # Filter out videos whose data might be missing from media_collection before selecting
        existing_bookmarked_videos = []
        for bookmark in bookmarked_videos:
            video_data = get_video_by_uuid(bookmark['uuid'])
            if video_data:
                existing_bookmarked_videos.append(bookmark)
            else:
                logger.warning(f"Saved video {bookmark['uuid']} for user {user_id} not found in media_collection. Removing from bookmarks.")
                # Remove directly from DB to clean up
                users_collection.update_one(
                    {'user_id': user_id},
                    {'$pull': {'bookmarked_videos': {'uuid': bookmark['uuid']}}}
                )
                
        if not existing_bookmarked_videos:
            await callback_query.answer("You haven't saved any valid videos yet. ❤️", show_alert=True)
            await callback_query.message.edit_text(
                "You haven't saved any valid videos yet. ❤️",
                reply_markup=category_keyboard()
            )
            return

        # Select the most recent one from the *existing* bookmarked videos
        latest_bookmark = max(existing_bookmarked_videos, key=lambda x: x.get('bookmarked_at', datetime.min))
        video_uuid = latest_bookmark['uuid']
        video = get_video_by_uuid(video_uuid) 

        if not video:
            # Fallback if somehow still no video (should be rare)
            await callback_query.answer("Saved video not found after selection. It may have been removed. 😔", show_alert=True)
            users_collection.update_one(
                {'user_id': user_id},
                {'$pull': {'bookmarked_videos': {'uuid': video_uuid}}}
            )
            return

        # Send the video directly, editing the category selection message
        sent_success, sent_message_or_error = await send_and_replace_message(
            client,
            chat_id,
            message_id_to_edit_or_delete=callback_query.message.id, # Edit the current message
            new_message_type="video",
            video_data=video,
            reply_markup=video_nav_keyboard(video['uuid'], "saved_videos", user_id, is_saved=True)
        )
        
        if sent_success:
            save_history(user_id, video['uuid'], "saved_videos")
            await callback_query.answer()
        else:
            await callback_query.answer("❌ Failed to load saved video. Please try again. 😥", show_alert=True)
            clear_active_video_message(user_id)
        return # Important: Exit after handling saved_videos category

    # Original logic for other categories
    if category not in get_categories():
        logger.warning(f"User {user_id} selected invalid category '{category}'.")
        await callback_query.answer("Category not found. Try again! 🧐", show_alert=True)
        await callback_query.message.edit_text(
            "Category not found. Try another! 🧐",
            reply_markup=category_keyboard()
        )
        return
    
    # Try to get the last viewed video for this category
    user_doc = users_collection.find_one({'user_id': user_id})
    last_viewed_uuid = user_doc.get('last_viewed_per_category', {}).get(category)
    video = None
    if last_viewed_uuid:
        video = get_video_by_uuid(last_viewed_uuid)
        if not video:
            logger.warning(f"Last viewed video {last_viewed_uuid} for category '{category}' not found. Getting random.")
            video = get_random_video(category)
    else:
        video = get_random_video(category)

    if not video:
        logger.warning(f"No videos found in category '{category}' for user {user_id}.")
        await callback_query.answer("No videos in this category. Try another! 😔", show_alert=True)
        await callback_query.message.edit_text(
            "No videos in this category. Try another! 😔",
            reply_markup=category_keyboard()
        )
        return
    
    # Edit the existing message with the new video
    sent_success, sent_message_or_error = await send_and_replace_message(
        client,
        chat_id,
        message_id_to_edit_or_delete=callback_query.message.id, # Edit the current message
        new_message_type="video",
        video_data=video,
        reply_markup=video_nav_keyboard(video['uuid'], category, user_id)
    )
    
    if sent_success:
        save_history(user_id, video['uuid'], video['category']) # This now updates last_viewed_per_category
        logger.info(f"User {user_id} selected category {category} and new video {video['uuid']} sent.")
        await callback_query.answer()
    else:
        logger.error(f"User {user_id} failed to send video after category selection: {sent_message_or_error}. Clearing active video message.")
        await callback_query.answer("❌ Failed to load video. Please try again. 😥", show_alert=True)
        clear_active_video_message(user_id)

@app.on_callback_query(filters.regex(r"^next\|")) # Updated regex to match new format
async def next_video(client: Client, callback_query: CallbackQuery):
    """Handles 'Next' video navigation."""
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id
    logger.info(f"User {user_id} requested next video.")
    
    # Force Subscribe Check
    if not await check_membership(client, user_id):
        await callback_query.answer("You must join our channel first!", show_alert=True)
        await send_force_subscribe_message(client, user_id)
        return

    # Check and notify about premium status change
    create_tracked_task(check_premium_status_and_notify(client, user_id))

    try:
        parts = callback_query.data.split('|') # Updated split delimiter
        if len(parts) != 3: # Added check for valid parts length
            logger.error(f"Invalid callback data for next_video: {callback_query.data}")
            await callback_query.answer("Invalid request. Please try again.", show_alert=True)
            return
        action, current_uuid, category = parts # Unpack parts
        
        if await is_rate_limited(user_id):
            await callback_query.answer("⚠️ Browse too quickly. Wait 1 min. ⏳", show_alert=True)
            logger.warning(f"User {user_id} hit rate limit in next_video.")
            return

        current_active_tracked_message = active_video_message.get(user_id)
        if not current_active_tracked_message or current_active_tracked_message.get('message_id') != callback_query.message.id:
            logger.warning(f"User {user_id} tried to navigate next but menu expired or callback not from active menu. Callback Message ID: {callback_query.message.id}, Active Menu ID: {current_active_tracked_message.get('message_id') if current_active_tracked_message else 'None'}")
            await callback_query.answer("Menu expired. Click '🎞️ Get Video' to restart. ⏰", show_alert=True)
            if current_active_tracked_message and callback_query.message.id != current_active_tracked_message.get('message_id'):
                try:
                    await client.delete_messages(callback_query.message.chat.id, callback_query.message.id)
                except MessageIdInvalid:
                    pass
                except Exception as e:
                    logger.warning(f"Failed to delete non-active menu message for user {user_id}: {e}")
            clear_active_video_message(user_id)
            await client.send_message(chat_id, "Your menu has expired. Please click '🎞️ Get Video' to get a new one. ⏰")
            return

        # Handle "saved_videos" category
        if category == "saved_videos":
            user = users_collection.find_one({'user_id': user_id})
            bookmarked_videos = user.get('bookmarked_videos', [])
            
            # Filter out videos whose data might be missing from media_collection
            existing_bookmarked_videos = []
            for bookmark in bookmarked_videos:
                video_data = get_video_by_uuid(bookmark['uuid'])
                if video_data:
                    existing_bookmarked_videos.append(bookmark)
                else:
                    logger.warning(f"Saved video {bookmark['uuid']} for user {user_id} not found in media_collection during next_video. Removing from bookmarks.")
                    users_collection.update_one(
                        {'user_id': user_id},
                        {'$pull': {'bookmarked_videos': {'uuid': bookmark['uuid']}}}
                    )

            if not existing_bookmarked_videos:
                await callback_query.answer("You have no saved videos. ❤️", show_alert=True)
                return
            
            # Randomly select a video from the *existing* bookmarked videos
            selected_bookmark = random.choice(existing_bookmarked_videos)
            video_uuid = selected_bookmark['uuid']
            video = get_video_by_uuid(video_uuid)
            
            if not video:
                # This should ideally not happen after filtering and re-getting, but for safety:
                await callback_query.answer("Saved video not found. It may have been removed. 😔", show_alert=True)
                users_collection.update_one(
                    {'user_id': user_id},
                    {'$pull': {'bookmarked_videos': {'uuid': video_uuid}}}
                )
                return
        else:
            # Regular category behavior: always get a new random video
            if category not in get_categories(): # Re-check if category is valid for non-saved videos
                logger.warning(f"User {user_id} used invalid category '{category}' for next video (non-saved).")
                await callback_query.answer("Category not found. Try 'Change Category'! 🧐", show_alert=True)
                return

            video = get_random_video(category)
            if not video:
                await callback_query.answer("No more videos in this category. Try another! 😔", show_alert=True)
                return
        
        # Edit the existing message with the new video
        sent_success, sent_message_or_error = await send_and_replace_message(
            client,
            chat_id,
            message_id_to_edit_or_delete=callback_query.message.id, # Edit the current message
            new_message_type="video",
            video_data=video,
            reply_markup=video_nav_keyboard(video['uuid'], category, user_id, is_saved=(category == "saved_videos"))
        )
        
        if sent_success:
            save_history(user_id, video['uuid'], category) # This now updates last_viewed_per_category
            await callback_query.answer()
        else:
            await callback_query.answer("❌ Failed to load next video. Please try again. 😥", show_alert=True)
            clear_active_video_message(user_id)
    except Exception as e:
        logger.error(f"User {user_id} error in next_video: {e}", exc_info=True)
        await callback_query.answer("Something went wrong. Please try again. 🤷‍♀️", show_alert=True)

@app.on_callback_query(filters.regex(r"^prev\|")) # Updated regex to match new format
async def prev_video(client: Client, callback_query: CallbackQuery):
    """Handles 'Previous' video navigation, showing the last viewed video in the current category."""
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id
    logger.info(f"User {user_id} requested previous video.")
    
    # Force Subscribe Check
    if not await check_membership(client, user_id):
        await callback_query.answer("You must join our channel first!", show_alert=True)
        await send_force_subscribe_message(client, user_id)
        return

    # Check and notify about premium status change
    create_tracked_task(check_premium_status_and_notify(client, user_id))

    try:
        parts = callback_query.data.split('|') # Updated split delimiter
        if len(parts) != 3: # Added check for valid parts length
            logger.error(f"Invalid callback data for prev_video: {callback_query.data}")
            await callback_query.answer("Invalid request. Please try again.", show_alert=True)
            return
        action, current_uuid, category = parts # Unpack parts

        if await is_rate_limited(user_id):
            await callback_query.answer("⚠️ Browse too quickly. Wait 1 min. ⏳", show_alert=True)
            logger.warning(f"User {user_id} hit rate limit in prev_video.")
            return

        current_active_tracked_message = active_video_message.get(user_id)
        if not current_active_tracked_message or current_active_tracked_message.get('message_id') != callback_query.message.id:
            logger.warning(f"User {user_id} tried to navigate previous but menu expired or callback not from active menu. Callback Message ID: {callback_query.message.id}, Active Menu ID: {current_active_tracked_message.get('message_id') if current_active_tracked_message else 'None'}")
            await callback_query.answer("Menu expired. Click '🎞️ Get Video' to restart. ⏰", show_alert=True)
            if current_active_tracked_message and callback_query.message.id != current_active_tracked_message.get('message_id'):
                try:
                    await client.delete_messages(callback_query.message.chat.id, callback_query.message.id)
                except MessageIdInvalid:
                    pass
                except Exception as e:
                    logger.warning(f"Failed to delete non-active menu message for user {user_id}: {e}")
            clear_active_video_message(user_id)
            await client.send_message(chat_id, "Your menu has expired. Please click '🎞️ Get Video' to get a new one. ⏰")
            return

        # Retrieve the last viewed video for the CURRENT category from user's document
        user_doc = users_collection.find_one({'user_id': user_id})
        last_viewed_uuid_in_category = user_doc.get('last_viewed_per_category', {}).get(category)
        
        found_video = None
        if last_viewed_uuid_in_category:
            found_video = get_video_by_uuid(last_viewed_uuid_in_category)
        
        if not found_video:
            logger.warning(f"User {user_id} has no previous video for category '{category}'.")
            await callback_query.answer(
                f"No previous video found for category '{html.escape(category)}'. 🧐",
                show_alert=True
            )
            return
            
        # Determine if the previous video was from the 'saved_videos' category to pass is_saved=True
        is_saved_for_prev = (category == "saved_videos")
            
        # Edit the existing message with the new video
        sent_success, sent_message_or_error = await send_and_replace_message(
            client,
            chat_id,
            message_id_to_edit_or_delete=callback_query.message.id, # Edit the current message
            new_message_type="video",
            video_data=found_video,
            reply_markup=video_nav_keyboard(found_video['uuid'], category, user_id, is_saved=is_saved_for_prev)
        )
        
        if sent_success:
            # We don't call save_history here because 'prev' is just showing the last one, not a new view.
            logger.info(f"User {user_id} navigated to previous video {found_video['uuid']} in category {found_video['category']}.")
            await callback_query.answer()
        else:
            logger.error(f"User {user_id} failed to send previous video: {sent_message_or_error}.")
            await callback_query.answer("❌ Failed to load prev video. Please try again. 😥", show_alert=True)
            clear_active_video_message(user_id)
    except Exception as e:
        logger.error(f"User {user_id} error in prev_video: {e}", exc_info=True)
        await callback_query.answer(
            "An unexpected error occurred. Try again. 🤷‍♀️",
            show_alert=True
        )

@app.on_callback_query(filters.regex(r"^change_cat$"))
async def change_category(client: Client, callback_query: CallbackQuery):
    """Handles 'Change Category' request."""
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id
    logger.info(f"User {user_id} requested to change category.")
    
    # Force Subscribe Check
    if not await check_membership(client, user_id):
        await callback_query.answer("You must join our channel first!", show_alert=True)
        await send_force_subscribe_message(client, user_id)
        return

    # Check and notify about premium status change
    create_tracked_task(check_premium_status_and_notify(client, user_id))

    try:
        current_active_tracked_message = active_video_message.get(user_id)
        if not current_active_tracked_message or current_active_tracked_message.get('message_id') != callback_query.message.id:
            logger.warning(f"User {user_id} tried to change category but menu expired or callback not from active menu. Callback Message ID: {callback_query.message.id}, Active Menu ID: {current_active_tracked_message.get('message_id') if current_active_tracked_message else 'None'}")
            await callback_query.answer("Menu expired. Click '🎞️ Get Video' to restart. ⏰", show_alert=True)
            if current_active_tracked_message and callback_query.message.id != current_active_tracked_message.get('message_id'):
                try:
                    await client.delete_messages(callback_query.message.chat.id, callback_query.message.id)
                except MessageIdInvalid:
                    pass
                except Exception as e:
                    logger.warning(f"Failed to delete non-active menu message for user {user_id}: {e}")
            clear_active_video_message(user_id)
            await client.send_message(chat_id, "Your menu has expired. Please click '🎞️ Get Video' to get a new one. ⏰")
            return
        
        # When changing category from a video, we typically want to replace the video message
        # with the text-based category selection menu. So, deleting the old and sending new is appropriate.
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

@app.on_message(filters.regex("^👤 Profile$") & filters.private)
async def profile_btn(client: Client, message: Message):
    """Handles 'Profile' button click."""
    user_id = message.from_user.id
    logger.info(f"User {user_id} clicked Profile button.")
    # Force Subscribe Check
    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return
    try:
        await profile_cmd(client, message)
        logger.info(f"User {user_id}: Profile command triggered from button.")
    except Exception as e:
        logger.error(f"User {user_id} failed to trigger profile command from button: {e}", exc_info=True)
        await handle_error(client, message, e)

@app.on_message(filters.regex("^🔗 Refer & Earn$") & filters.private)
async def refer_btn(client: Client, message: Message):
    """Handles 'Refer & Earn' button click."""
    user_id = message.from_user.id
    logger.info(f"User {user_id} clicked Refer & Earn button.")
    
    # Force Subscribe Check
    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    # Check and notify about premium status change
    create_tracked_task(check_premium_status_and_notify(client, user_id))

    try:
        if await is_rate_limited(user_id):
            await handle_error(client, message, FloodWait(10))
            logger.warning(f"User {user_id} hit rate limit in refer_btn.")
            return

        ref_link = f"https://t.me/{config.BOT_USERNAME[1:]}?start=ref_{user_id}"
        await message.reply(f"🔗 <b>Share & Earn!</b>\nWhen a new user joins through this link, you'll receive {config.REFERRAL_BONUS} token. It's a win-win! 🎉\n\n<code>{html.escape(ref_link)}</code>\n\nShare this link to new users only to get the token! 📢", reply_markup=referral_keyboard(ref_link))
        logger.info(f"User {user_id}: Referral link sent successfully.")
    except Exception as e:
        logger.error(f"User {user_id} failed to send referral link: {e}", exc_info=True)
        await handle_error(client, message, e)

@app.on_message(filters.regex("^💰 Buy Token$") & filters.private)
async def buy_token_btn(client: Client, message: Message):
    """Handles 'Buy Token' button click."""
    user_id = message.from_user.id
    logger.info(f"User {user_id} clicked Buy Token button.")
    
    # Force Subscribe Check
    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    # Check and notify about premium status change
    create_tracked_task(check_premium_status_and_notify(client, user_id))

    try:
        await message.reply("💳 Need more tokens? You can buy them from our support bot! Click the button below to proceed. 👇", reply_markup=buy_token_keyboard())
        logger.info(f"User {user_id}: Buy token message sent successfully.")
    except Exception as e:
        logger.error(f"User {user_id} failed to send buy token message: {e}", exc_info=True)
        await handle_error(client, message, e)

@app.on_message(filters.regex("^🔄 Refresh Token$") & filters.private)
async def refresh_token_btn(client: Client, message: Message):
    """Handles 'Refresh Token' button click."""
    user_id = message.from_user.id
    logger.info(f"User {user_id} requested token refresh. Handler entered.")

    # Force Subscribe Check
    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    temp_msg = None
    try:
        # Check and notify about premium status change (especially important if they just lost premium)
        create_tracked_task(check_premium_status_and_notify(client, user_id))

        if await is_rate_limited(user_id):
            await message.reply_text("⚠️ You're refreshing too quickly. Please wait a minute and try again. ⏳")
            logger.warning(f"User {user_id} hit rate limit in refresh_token_btn.")
            return

        temp_msg = await message.reply("⏳ Please wait while we prepare your token... ✨")
        logger.info(f"User {user_id}: 'Please wait...' message sent. Checking for existing token.")

        # If user is currently premium (via admin-granted token), they don't need a free token refresh
        if is_premium_user(user_id):
            if temp_msg:
                await temp_msg.delete()
            await message.reply("💡 You already have active premium access. No need to refresh yet! Enjoy the videos! 🥳")
            logger.info(f"User {user_id} attempted token refresh but already has valid premium access. Exiting.")
            return

        logger.info(f"User {user_id}: User does not have valid premium access. Generating ad_code and attempting to shorten URL.")
        ad_code = str_to_b64(f"{user_id}:{get_current_time() + config.TOKEN_EXPIRY}")
        long_url = f"https://t.me/{config.BOT_USERNAME[1:]}?start=token_{ad_code}"
        
        # Use the updated get_shortener_config_and_shorten_url
        ad_url = await get_shortener_config_and_shorten_url(long_url) 
        logger.info(f"User {user_id}: get_shortener_config_and_shorten_url call completed. Result: {ad_url}")
        
        if temp_msg:
            await temp_msg.delete()

        disable_preview = False
        # If the returned URL is the original long Telegram URL, disable web page preview
        if ad_url == long_url:
            logger.warning(f"User {user_id} URL shortening failed for refresh_token_btn. Using long URL: {ad_url}")
            disable_preview = True

        user_mention_safe = html.escape(message.from_user.first_name) if message.from_user.first_name else "there"
        await message.reply_text(
            f"💡 <b>Information</b>\nHere's how to get your token! 🚀\n\n"
            f"Hey 💕 <b>{user_mention_safe}</b>,\n\nYour Ads token is expired. Please refresh your token by clicking the button below and try again. 👇\n\n<b>Token Timeout:</b> 24 hours ⏰\n\n<b>What is a token?</b>\nThis is an ads token. If you pass 1 ad, you can use the bot for 24 hours after passing the ad. It's that simple! ✨\n\n<tg-spoiler>‼️ APPLE/IPHONE USERS: Copy the token link and open it in a Chrome browser for best experience. 🍎</tg-spoiler>",
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
    
    # Force Subscribe Check
    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    try:
        # Check and notify about premium status change
        create_tracked_task(check_premium_status_and_notify(client, user_id))

        if await is_rate_limited(user_id):
            await message.reply_text("⚠️ You're requesting token options too quickly. Please wait a minute and try again. ⏳")
            logger.warning(f"User {user_id} hit rate limit in send_token_earning_options.")
            return

        ad_code = str_to_b64(f"{user_id}:{get_current_time() + config.TOKEN_EXPIRY}")
        long_url = f"https://t.me/{config.BOT_USERNAME[1:]}?start=token_{ad_code}"
        
        # Use the updated get_shortener_config_and_shorten_url
        ad_url = await get_shortener_config_and_shorten_url(long_url) 
        
        disable_preview = False
        # If the returned URL is the original long Telegram URL, disable web page preview
        if ad_url == long_url:
            logger.warning(f"User {user_id} URL shortening failed for send_token_earning_options. Using long URL: {ad_url}")
            disable_preview = True

        await message.reply(
            "❌ <b>No Tokens Left!</b> 😔\nUse any of these methods to gain tokens and continue watching spicy content! 👇",
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
    
    # Force Subscribe Check
    if not await check_membership(client, user_id):
        await callback_query.answer("You must join our channel first!", show_alert=True)
        await send_force_subscribe_message(client, user_id)
        return

    # Check and notify about premium status change
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
        await callback_query.message.reply(
            f"🔗 <b>Share this video and earn!</b> 🎁\nWhen a new user joins through this link, you'll receive {config.REFERRAL_BONUS} token. It's a win-win! 🎉\n\n<code>{html.escape(share_link)}</code>\n\nShare this link to new users only to get the token! 📢",
            quote=True,
            disable_web_page_preview=True
        )
        logger.info(f"User {user_id}: Share link for video {video_uuid} sent successfully with referral data.")
    except Exception as e:
        logger.error(f"User {user_id} failed to send share link for video {video_uuid}: {e}", exc_info=True)
        await callback_query.answer("❌ Something went wrong. Please try again. 🤷‍♀️", show_alert=True)

@app.on_callback_query(filters.regex(r"^download_(.+)$"))
async def download_video_callback(client: Client, callback_query: CallbackQuery):
    """Handles 'Download' video callback for premium users."""
    user_id = callback_query.from_user.id
    video_uuid = callback_query.data.split('_', 1)[1]
    chat_id = callback_query.message.chat.id

    logger.info(f"User {user_id} requested download for video {video_uuid}.")

    # Force Subscribe Check
    if not await check_membership(client, user_id):
        await callback_query.answer("You must join our channel first!", show_alert=True)
        await send_force_subscribe_message(client, user_id)
        return

    # Check and notify about premium status change BEFORE checking is_premium_user
    create_tracked_task(check_premium_status_and_notify(client, user_id))

    try:
        if not is_premium_user(user_id): # This check correctly determines visibility
            logger.info(f"Non-premium user {user_id} attempted to download video {video_uuid}.")
            support_bot_link = f"https://t.me/{config.SUPPORT_BOT_USERNAME}"
            reply_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("💬 Support Bot", url=support_bot_link, callback_data="support_link_clicked")]
            ])
            await callback_query.answer("⚠️ Premium feature only! ✨", show_alert=True)
            await client.send_message(
                chat_id,
                f"To access the Download button, DM our support bot to purchase a 7-day trial for ₹{config.PREMIUM_TRIAL_PRICE_INR} or 1-month premium access for ₹{config.PREMIUM_MONTH_PRICE_INR}. 💎",
                reply_markup=reply_markup
            )
            return

        video = get_video_by_uuid(video_uuid)
        if not video:
            logger.warning(f"Premium user {user_id} requested download for non-existent video {video_uuid}.")
            await callback_query.answer("Video not found. It might have been removed. 😔", show_alert=True)
            return

        # Send the raw video file without any captions or extra buttons
        await client.send_video(
            chat_id,
            video=video['file_id'],
            caption=None, # Removed caption as per user request
            protect_content=False # Ensure content can be forwarded/saved by user
        )
        await callback_query.answer("Download initiated! 🚀")
        logger.info(f"Premium user {user_id} successfully received download for video {video_uuid}.")

    except Exception as e:
        logger.error(f"Error handling download for user {user_id}, video {video_uuid}: {e}", exc_info=True)
        await callback_query.answer("❌ Failed to send video for download. Please try again later. 😥", show_alert=True)


@app.on_callback_query(filters.regex(r"^bookmark_(.+)$"))
async def bookmark_video_callback(client: Client, callback_query: CallbackQuery):
    """Handles 'Bookmark' video callback."""
    user_id = callback_query.from_user.id
    video_uuid = callback_query.data.split('_', 1)[1]

    logger.info(f"User {user_id} requested to bookmark video {video_uuid}.")
    
    # Force Subscribe Check
    if not await check_membership(client, user_id):
        await callback_query.answer("You must join our channel first!", show_alert=True)
        await send_force_subscribe_message(client, user_id)
        return

    # Check and notify about premium status change
    create_tracked_task(check_premium_status_and_notify(client, user_id))

    try:
        user = users_collection.find_one({'user_id': user_id})
        if not user:
            await callback_query.answer("User not found. Please restart the bot.", show_alert=True)
            return

        bookmarked_videos = user.get('bookmarked_videos', [])
        
        # Check if already bookmarked
        if any(v['uuid'] == video_uuid for v in bookmarked_videos):
            await callback_query.answer("This video is already bookmarked! ❤️", show_alert=True)
            return

        is_premium = is_premium_user(user_id) # Uses the new logic
        
        # Check free user limit
        if not is_premium and len(bookmarked_videos) >= config.FREE_USER_SAVE_LIMIT:
            await callback_query.answer(f"You've reached your limit of {config.FREE_USER_SAVE_LIMIT} saved videos! Upgrade to Premium for unlimited saves. ✨", show_alert=True)
            return

        # Add the video with timestamp for ordering
        bookmarked_videos.append({'uuid': video_uuid, 'bookmarked_at': datetime.utcnow()})
        
        users_collection.update_one(
            {'user_id': user_id},
            {'$set': {'bookmarked_videos': bookmarked_videos}}
        )
        
        await callback_query.answer("Video bookmarked successfully! ❤️")
        logger.info(f"User {user_id} bookmarked video {video_uuid}.")

    except Exception as e:
        logger.error(f"Error handling bookmark for user {user_id}, video {video_uuid}: {e}", exc_info=True)
        await callback_query.answer("❌ Failed to bookmark video. Please try again later. 😥", show_alert=True)

@app.on_message(filters.regex("^🔖 Saved Videos$") & filters.private)
async def saved_videos_btn(client: Client, message: Message):
    """Handles 'Saved Videos' button click."""
    user_id = message.from_user.id
    chat_id = message.chat.id
    logger.info(f"User {user_id} clicked Saved Videos button.")

    # Force Subscribe Check
    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    # Check and notify about premium status change
    create_tracked_task(check_premium_status_and_notify(client, user_id))

    if await is_rate_limited(user_id):
        await handle_error(client, message, FloodWait(10))
        logger.warning(f"User {user_id} hit rate limit in saved_videos_btn.")
        return

    user = users_collection.find_one({'user_id': user_id})
    if not user or not user.get('bookmarked_videos'):
        await message.reply("You haven't saved any videos yet. ❤️ Click 'Get Video' and then 'Bookmark' your favorites! ✨", reply_markup=await get_main_keyboard(user_id))
        return

    bookmarked_videos_data = user.get('bookmarked_videos', [])

    # Filter/truncate based on premium status
    if not is_premium_user(user_id) and len(bookmarked_videos_data) > config.FREE_USER_SAVE_LIMIT:
        bookmarked_videos_data.sort(key=lambda x: x.get('bookmarked_at', datetime.min), reverse=True)
        bookmarked_videos_data = bookmarked_videos_data[:config.FREE_USER_SAVE_LIMIT]
        users_collection.update_one(
            {'user_id': user_id},
            {'$set': {'bookmarked_videos': bookmarked_videos_data}}
        )
        logger.info(f"User {user_id}'s bookmarked videos truncated to {config.FREE_USER_SAVE_LIMIT} as premium expired or was never premium.")

    # Filter out videos whose data might be missing from media_collection
    existing_bookmarked_videos = []
    for bookmark in bookmarked_videos_data:
        video_data = get_video_by_uuid(bookmark['uuid'])
        if video_data:
            existing_bookmarked_videos.append(bookmark)
        else:
            logger.warning(f"Saved video {bookmark['uuid']} for user {user_id} not found in media_collection during saved_videos_btn. Removing from bookmarks.")
            users_collection.update_one(
                {'user_id': user_id},
                {'$pull': {'bookmarked_videos': {'uuid': bookmark['uuid']}}}
            )
            
    if not existing_bookmarked_videos:
        await message.reply("You haven't saved any valid videos yet. ❤️ Click 'Get Video' and then 'Bookmark' your favorites! ✨", reply_markup=await get_main_keyboard(user_id))
        return

    # Get the most recent valid bookmarked video to display directly
    latest_bookmark = max(existing_bookmarked_videos, key=lambda x: x.get('bookmarked_at', datetime.min))
    video_uuid = latest_bookmark['uuid']
    video = get_video_by_uuid(video_uuid) 

    if not video:
        # Fallback if somehow still no video, should be rare now
        await message.reply("Failed to load your latest saved video. It may have been removed. 😔", reply_markup=await get_main_keyboard(user_id))
        users_collection.update_one(
            {'user_id': user_id},
            {'$pull': {'bookmarked_videos': {'uuid': video_uuid}}} # Clean up if still an issue
        )
        return

    # When 'Saved Videos' is clicked, we want to replace the current message (e.g., the main keyboard message)
    # with the video message.
    message_id_to_edit_or_delete = message.id # Use the ID of the message that triggered this handler

    sent_success, sent_message_or_error = await send_and_replace_message(
        client,
        chat_id,
        message_id_to_edit_or_delete=message_id_to_edit_or_delete, # Pass the message ID to be edited/deleted
        new_message_type="video",
        video_data=video,
        reply_markup=video_nav_keyboard(video['uuid'], "saved_videos", user_id, is_saved=True) # Pass is_saved=True
    )

    if sent_success:
        save_history(user_id, video['uuid'], "saved_videos")
        logger.info(f"User {user_id} displayed latest saved video {video_uuid}.")
    else:
        await message.reply(sent_message_or_error)
        logger.error(f"User {user_id} failed to send latest saved video: {sent_message_or_error}")


@app.on_callback_query(filters.regex(r"^remove_saved_(.+)$"))
async def remove_saved_video_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    video_uuid = callback_query.data.split('_', 2)[2]
    chat_id = callback_query.message.chat.id
    logger.info(f"User {user_id} requested to remove saved video {video_uuid}.")

    # Force Subscribe Check
    if not await check_membership(client, user_id):
        await callback_query.answer("You must join our channel first!", show_alert=True)
        await send_force_subscribe_message(client, user_id)
        return

    # Check and notify about premium status change
    create_tracked_task(check_premium_status_and_notify(client, user_id))

    try:
        # Remove video from user's saved list
        result = users_collection.update_one(
            {'user_id': user_id},
            {'$pull': {'bookmarked_videos': {'uuid': video_uuid}}}
        )
        
        if result.modified_count > 0:
            await callback_query.answer("Video removed from saved videos. 🗑️")
            # Check for remaining saved videos
            user = users_collection.find_one({'user_id': user_id})
            bookmarked_videos = user.get('bookmarked_videos', [])
            
            # Filter out any videos that no longer exist in media_collection before processing
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
            
            if existing_bookmarked_videos:
                # Show the next most recent saved video
                latest_bookmark = max(existing_bookmarked_videos, key=lambda x: x.get('bookmarked_at', datetime.min))
                next_video_uuid = latest_bookmark['uuid']
                next_video = get_video_by_uuid(next_video_uuid)
                
                if next_video:
                    sent_success, sent_message_or_error = await send_and_replace_message(
                        client,
                        chat_id,
                        message_id_to_edit_or_delete=callback_query.message.id, # Edit the current message
                        new_message_type="video",
                        video_data=next_video,
                        reply_markup=video_nav_keyboard(next_video['uuid'], "saved_videos", user_id, is_saved=True)
                    )
                    if sent_success:
                        save_history(user_id, next_video['uuid'], "saved_videos")
                    else:
                        await client.send_message(chat_id, "❌ Failed to load next saved video. Please try again. 😥")
                else:
                    await client.send_message(chat_id, "The next saved video was not found. It may have been removed. 😔")
            else:
                # No saved videos left, replace with a text message
                await send_and_replace_message(
                    client,
                    chat_id,
                    message_id_to_edit_or_delete=callback_query.message.id, # Edit the current message
                    new_message_type="text",
                    text_content="You have no more saved videos. ❤️ Click 'Get Video' to find new ones!",
                    reply_markup=await get_main_keyboard(user_id)
                )
        else:
            await callback_query.answer("Video not found in your saved videos. 🧐", show_alert=True)
    except Exception as e:
        logger.error(f"Error removing saved video for user {user_id}, video {video_uuid}: {e}", exc_info=True)
        await callback_query.answer("❌ Failed to remove video. Please try again. 😥", show_alert=True)


# The view_saved_video_callback is effectively deprecated by the new direct display logic for "Saved Videos"
# but kept here in case future functionality explicitly links to individual saved videos from somewhere else.
@app.on_callback_query(filters.regex(r"^view_saved_video_(.+)$"))
async def view_saved_video_callback(client: Client, callback_query: CallbackQuery):
    """Handles viewing a specific saved video."""
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id
    video_uuid = callback_query.data.split('_', 3)[3] # Correctly parse UUID

    logger.info(f"User {user_id} requested to view saved video {video_uuid}.")

    # Force Subscribe Check
    if not await check_membership(client, user_id):
        await callback_query.answer("You must join our channel first!", show_alert=True)
        await send_force_subscribe_message(client, user_id)
        return

    # Check and notify about premium status change
    create_tracked_task(check_premium_status_and_notify(client, user_id))

    if await is_rate_limited(user_id):
        await callback_query.answer("⚠️ You're Browse too quickly. Please wait a minute and try again. ⏳", show_alert=True)
        return

    if not user_has_token(user_id):
        await callback_query.answer("You need a token to watch this video. Please get a token first! 🧐", show_alert=True)
        # Optionally, send earning options after the answer
        await send_token_earning_options(client, callback_query.message)
        return

    video = get_video_by_uuid(video_uuid)
    if not video:
        await callback_query.answer("Video not found or has been removed. 😔", show_alert=True)
        # Remove from saved list if it's no longer available
        users_collection.update_one(
            {'user_id': user_id},
            {'$pull': {'bookmarked_videos': {'uuid': video_uuid}}}
        )
        return

    # Edit the existing message with the new video
    sent_success, sent_message_or_error = await send_and_replace_message(
        client,
        chat_id,
        message_id_to_edit_or_delete=callback_query.message.id, # Edit the current message
        new_message_type="video",
        video_data=video,
        reply_markup=video_nav_keyboard(video['uuid'], "saved_videos", user_id, is_saved=True) # Ensure is_saved is true for this path
    )

    if sent_success:
        save_history(user_id, video['uuid'], "saved_videos")
        await callback_query.answer()
        logger.info(f"User {user_id} viewed saved video {video_uuid}.")
    else:
        await callback_query.answer("❌ Failed to load saved video. Please try again. 😥", show_alert=True)
        logger.error(f"User {user_id} failed to load saved video {video_uuid}: {sent_message_or_error}")


@app.on_callback_query(filters.regex(r"^unavailable_(.+)$"))
async def unavailable_video_callback(client: Client, callback_query: CallbackQuery):
    """Handles clicks on unavailable videos in the saved list."""
    user_id = callback_query.from_user.id
    video_uuid = callback_query.data.split('_', 1)[1]
    
    # Force Subscribe Check
    if not await check_membership(client, user_id):
        await callback_query.answer("You must join our channel first!", show_alert=True)
        await send_force_subscribe_message(client, user_id)
        return

    await callback_query.answer("This video is no longer available. It may have been removed. 😔", show_alert=True)
    # Optionally remove from saved list if confirmed unavailable.
    users_collection.update_one(
        {'user_id': user_id},
        {'$pull': {'bookmarked_videos': {'uuid': video_uuid}}}
    )
    logger.info(f"User {user_id} clicked unavailable video {video_uuid}. Removed from bookmarks.")

@app.on_callback_query(filters.regex(r"^confirm_clear_all_saved$"))
async def confirm_clear_all_saved_callback(client: Client, callback_query: CallbackQuery):
    """Asks for confirmation before clearing all saved videos."""
    user_id = callback_query.from_user.id
    logger.info(f"User {user_id} requested to confirm clearing all saved videos.")
    
    # Force Subscribe Check
    if not await check_membership(client, user_id):
        await callback_query.answer("You must join our channel first!", show_alert=True)
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

@app.on_callback_query(filters.regex(r"^clear_all_saved_videos$"))
async def clear_all_saved_videos_callback(client: Client, callback_query: CallbackQuery):
    """Clears all saved videos for the user."""
    user_id = callback_query.from_user.id
    logger.info(f"User {user_id} confirmed clearing all saved videos.")

    # Force Subscribe Check
    if not await check_membership(client, user_id):
        await callback_query.answer("You must join our channel first!", show_alert=True)
        await send_force_subscribe_message(client, user_id)
        return

    try:
        users_collection.update_one(
            {'user_id': user_id},
            {'$set': {'bookmarked_videos': []}}
        )
        # Edit the message to confirm clearance
        await callback_query.message.edit_text("🗑️ All your saved videos have been cleared! ✨")
        await callback_query.answer("All saved videos cleared.")
        logger.info(f"User {user_id} successfully cleared all saved videos.")
    except Exception as e:
        logger.error(f"Error clearing all saved videos for user {user_id}: {e}", exc_info=True)
        await callback_query.answer("❌ Failed to clear saved videos. Please try again. 😥", show_alert=True)
        await callback_query.message.edit_text("❌ Failed to clear saved videos. Please try again. 😥")

@app.on_callback_query(filters.regex(r"^cancel_clear_saved$"))
async def cancel_clear_saved_callback(client: Client, callback_query: CallbackQuery):
    """Cancels clearing all saved videos."""
    user_id = callback_query.from_user.id
    logger.info(f"User {user_id} cancelled clearing all saved videos.")
    
    # Force Subscribe Check
    if not await check_membership(client, user_id):
        await callback_query.answer("You must join our channel first!", show_alert=True)
        await send_force_subscribe_message(client, user_id)
        return

    await callback_query.message.edit_text("Operation cancelled. Your saved videos are safe! ✅")
    await callback_query.answer("Operation cancelled.")

# --- Admin Commands ---
@app.on_message(filters.command("broadcast") & filters.private & filters.user(config.ADMIN_IDS) & filters.reply)
async def broadcast_cmd(client: Client, message: Message):
    """Admin command to broadcast a replied message to all users."""
    user_id = message.from_user.id
    replied_message = message.reply_to_message
    logger.info(f"Admin {user_id} initiated broadcast.")
    try:
        users = list(users_collection.find({}, {'user_id': 1}))
        total_users = len(users)
        broadcast_msg = await message.reply(f"📣 <b>Broadcasting</b> to <b>{total_users}</b> users... Please wait! 🚀")
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
                "Category name can only contain letters, numbers, underscores, and hyphens. 📝"
            )
            return
        
        name = args[1]
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

@app.on_message(filters.command("deletecategory") & filters.private & filters.user(config.ADMIN_IDS))
async def deletecategory_cmd(client: Client, message: Message):
    """Admin command to delete a video category."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} requested to delete category.")
    try:
        categories = get_categories()
        if not categories:
            logger.warning(f"Admin {user_id} tried to delete category but no categories exist.")
            await message.reply_text("😔 No categories to delete. Add some first! ➕")
            return

        buttons = []
        for category in categories:
            buttons.append([InlineKeyboardButton(f"🗑️ {html.escape(category)}", callback_data=f"confirmdelcat_{category}")])

        await message.reply_text(
            """Select a category to delete:

⚠️ All videos in the selected category will be deleted permanently. This action cannot be undone. Click on a category name below to confirm deletion.🚨""",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        logger.info(f"Admin {user_id}: Delete category options sent.")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to send delete category options: {e}", exc_info=True)
        await message.reply("❌ An error occurred while preparing delete category options. Please try again. 🐛")

@app.on_callback_query(filters.regex(r"^confirmdelcat_(.+)$"))
async def confirm_delcat_callback(client: Client, callback_query: CallbackQuery):
    """Handles confirmation for category deletion."""
    user_id = callback_query.from_user.id
    category_raw = callback_query.data[14:]
    logger.info(f"Admin {user_id} confirmed deletion of category: {category_raw}.")
    try:
        if not is_admin(user_id):
            await callback_query.answer("❌ Not authorized. 🚫", show_alert=True)
            logger.warning(f"Non-admin user {user_id} attempted to confirm category deletion.")
            return
        
        category = category_raw

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

@app.on_message(filters.command("addtoken") & filters.private & filters.user(config.ADMIN_IDS))
async def addtoken_cmd(client: Client, message: Message):
    """Admin command to add tokens to a specific user and grant premium access."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} requested to add token (premium).")
    try:
        args = message.text.split()
        if len(args) < 3:
            logger.warning(f"Admin {user_id} used addtoken with insufficient arguments: {message.text}")
            await message.reply("Usage: <code>/addtoken &lt;user_id&gt; &lt;duration_days&gt;</code>\nDuration is in days. 📝")
            return
            
        target_user_id = int(args[1])
        duration_days = int(args[2])
            
        if target_user_id <= 0:
            logger.warning(f"Admin {user_id} provided invalid target user ID: {target_user_id}.")
            await message.reply("User ID must be a positive integer. 🔢")
            return
                
        if duration_days <= 0:
            logger.warning(f"Admin {user_id} provided invalid duration: {duration_days}.")
            await message.reply("Duration must be a positive integer (days). 🔢")
            return
                
        if duration_days > 365:
            logger.warning(f"Admin {user_id} attempted to add more than 365 days of premium access ({duration_days}).")
            await message.reply("Cannot add more than 365 days of premium access at once. Max 365 days per command. 🚫")
            return
                
        user_doc = users_collection.find_one({'user_id': target_user_id})
        if not user_doc:
            logger.warning(f"Admin {user_id} attempted to add tokens to non-existent user {target_user_id}.")
            await message.reply("User not found in database. 🧐")
            return
        
        # Grant premium by adding an admin-granted token
        added_token_info = add_token(target_user_id, duration_seconds=duration_days * 86400, is_admin_granted=True)
        
        if not added_token_info:
            await message.reply("❌ Failed to grant premium access. Please try again. 🐛")
            return

        expiry_date = added_token_info['expires_at']
        logger.info(f"Admin {user_id} granted {duration_days} days of premium access to user {target_user_id}. Expires: {expiry_date}")
        await message.reply(f"✅ Granted <b>{duration_days}</b> days of premium access to user <b>{target_user_id}</b>. New expiry: {expiry_date.strftime('%Y-%m-%d %H:%M:%S UTC')}. 🎉")
        
        # Notify the target user
        try:
            await client.send_message(target_user_id, f"🎉 <b>Congratulations!</b> You have been granted <b>{duration_days}</b> days of premium access by an admin! Your premium access now expires on <b>{expiry_date.strftime('%Y-%m-%d %H:%M:%S UTC')}</b>. Enjoy exclusive features! 💎")
            # Update their last_premium_check_status to True since they are now premium
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

# --- Batch Add Videos ---
batch_add_state = {}

def format_size(size_bytes: int) -> str:
    """Converts bytes to a human-readable format (e.g., KB, MB, GB)."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} PB"

@app.on_message(filters.command("batchadd") & filters.private & filters.user(config.ADMIN_IDS))
async def batchadd_cmd(client: Client, message: Message):
    """Admin command to enter batch video adding mode and choose category."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} initiated batch add mode.")
    try:
        categories = get_categories()
        if not categories:
            await message.reply("⚠️ No categories exist. Please create at least one category using /addcategory before starting batch add. ➕")
            logger.warning(f"Admin {user_id} tried to start batch add with no categories.")
            return

        batch_add_state[user_id] = {
            'batch_mode': False,
            'current_category': None,
            'count': 0
        }
        
        buttons = []
        for category in categories:
            buttons.append([InlineKeyboardButton(f"🗂️ {html.escape(category)}", callback_data=f"batchselcat_{category}")])

        await message.reply(
            "🎬 <b>Choose a Category for Batch Adding:</b>",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        logger.info(f"Admin {user_id}: Prompted to choose category for batch add.")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to initiate batch add mode: {e}", exc_info=True)
        await message.reply("❌ An error occurred while starting batch add mode. Please try again. 🐛")

@app.on_callback_query(filters.regex(r"^batchselcat_(.+)$"))
async def batch_select_category_callback(client: Client, callback_query: CallbackQuery):
    """Handles callback for selecting the category in batch add mode."""
    user_id = callback_query.from_user.id
    logger.info(f"Admin {user_id} selected category for batch adding: {callback_query.data[12:]}.")
    try:
        if not is_admin(user_id):
            await callback_query.answer("❌ Not authorized. 🚫", show_alert=True)
            logger.warning(f"Non-admin user {user_id} attempted to select batch category.")
            return

        if user_id not in batch_add_state:
            await callback_query.answer("❌ Error: Batch mode session expired or not active. Please use /batchadd again. 🚫", show_alert=True)
            logger.warning(f"Admin {user_id} tried to select category but batch mode not initialized.")
            return

        category_name = callback_query.data[12:]

        if category_name not in get_categories():
            await callback_query.answer(f"❌ Invalid category '<b>{html.escape(category_name)}</b>'. 🧐", show_alert=True)
            await callback_query.message.edit_text(
                "Category not found. Please try again! 🧐",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"🗂️ {html.escape(cat)}", callback_data=f"batchselcat_{cat}")] for cat in get_categories()])
            )
            logger.warning(f"Admin {user_id} tried to set invalid category for batch: '{category_name}'.")
            return

        batch_add_state[user_id]['batch_mode'] = True
        batch_add_state[user_id]['current_category'] = category_name
        batch_add_state[user_id]['count'] = 0
        
        await callback_query.message.edit_text(
            f"✅ You are now in batch add mode for category: <b>{html.escape(category_name)}</b>! 🎉\n"
            "Send me videos to add. Type /done when finished. ✅\n"
            "You can use /category to change the current batch category without exiting batch mode. 🔄"
        )
        await callback_query.answer(f"Category set to '{html.escape(category_name)}'")
        logger.info(f"Admin {user_id} successfully started batch add mode for category '{category_name}'.")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to set batch category in callback: {e}", exc_info=True)
        await callback_query.answer("❌ An error occurred while setting category. Please try again. 🐛", show_alert=True)

@app.on_message(filters.command("done") & filters.private & filters.user(config.ADMIN_IDS))
async def done_cmd(client: Client, message: Message):
    """Admin command to exit batch video adding mode."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} exited batch add mode.")
    try:
        if user_id in batch_add_state and batch_add_state[user_id].get('batch_mode'):
            total_added = batch_add_state[user_id].get('count', 0)
            del batch_add_state[user_id]
            await message.reply(f"Batch add mode disabled. Added <b>{total_added}</b> videos. 🎉")
            logger.info(f"Admin {user_id}: Batch add mode disabled. Total videos added: {total_added}.")
        else:
            await message.reply("You are not currently in batch add mode. Use /batchadd to start. 🚀")
            logger.warning(f"Admin {user_id} tried to use /done but not in batch mode.")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to disable batch add mode: {e}", exc_info=True)
        await message.reply("❌ An error occurred while ending batch add mode. Please try again. 🐛")

@app.on_message(filters.video & filters.private & filters.user(config.ADMIN_IDS))
async def handle_video_batch_add_or_delete(client: Client, message: Message):
    """
    Handles incoming video messages for either batch adding mode or delete video mode.
    Prioritizes delete video mode if active.
    """
    user_id = message.from_user.id
    
    # --- Handle /deletevideo mode ---
    if user_id in admin_delete_video_state and admin_delete_video_state[user_id]:
        logger.info(f"Admin {user_id} sent a video for deletion.")
        try:
            if not message.video:
                await message.reply_text("❌ Please send a video file to delete. 🎥")
                return

            file_unique_id = message.video.file_unique_id
            video_to_delete = media_collection.find_one({"file_unique_id": file_unique_id})

            if not video_to_delete:
                await message.reply_text("❌ Video not found in the database. Please ensure you sent the original video file. 🧐")
                return

            video_uuid = video_to_delete['uuid']
            message_id_in_channel = video_to_delete.get('message_id')

            # Delete from media_collection
            media_collection.delete_one({'uuid': video_uuid})
            logger.info(f"Video {video_uuid} deleted from media_collection.")

            # Remove from all users' bookmarked_videos
            users_collection.update_many(
                {},
                {'$pull': {'bookmarked_videos': {'uuid': video_uuid}}}
            )
            logger.info(f"Video {video_uuid} removed from all users' bookmarked_videos.")

            # Remove from all users' history_collection
            history_collection.update_many(
                {},
                {'$pull': {'history': {'video_uuid': video_uuid}}}
            )
            logger.info(f"Video {video_uuid} removed from all users' history_collection.")

            # Remove from all users' last_viewed_per_category
            # This requires iterating through users and their last_viewed_per_category map
            all_users_with_last_viewed = users_collection.find({'last_viewed_per_category': {'$exists': True}})
            for user_doc in all_users_with_last_viewed:
                user_id_to_update = user_doc['user_id']
                updated_last_viewed = {}
                changed = False
                for cat, vid_uuid in user_doc['last_viewed_per_category'].items():
                    if vid_uuid == video_uuid:
                        changed = True
                    else:
                        updated_last_viewed[cat] = vid_uuid
                if changed:
                    users_collection.update_one(
                        {'user_id': user_id_to_update},
                        {'$set': {'last_viewed_per_category': updated_last_viewed}}
                    )
                    logger.info(f"Video {video_uuid} removed from last_viewed_per_category for user {user_id_to_update}.")


            # Delete from channel
            if message_id_in_channel:
                try:
                    await client.delete_messages(config.VIDEO_CHANNEL_ID, message_id_in_channel)
                    logger.info(f"Video message {message_id_in_channel} deleted from channel {config.VIDEO_CHANNEL_ID}.")
                except MessageIdInvalid:
                    logger.warning(f"Video message {message_id_in_channel} already deleted or invalid in channel {config.VIDEO_CHANNEL_ID}.")
                except Exception as channel_delete_e:
                    logger.error(f"Failed to delete video message {message_id_in_channel} from channel {config.VIDEO_CHANNEL_ID}: {channel_delete_e}", exc_info=True)
                    await message.reply_text(f"⚠️ Video deleted from database, but failed to delete from channel. Reason: {channel_delete_e}")

            await message.reply_text(f"✅ Video (UUID: <code>{video_uuid}</code>) and its data have been deleted from the database and channel. 🗑️")

        except Exception as e:
            logger.error(f"Admin {user_id} error deleting video: {e}", exc_info=True)
            await message.reply("❌ An error occurred while deleting the video. Please try again. 🐛")
        finally:
            del admin_delete_video_state[user_id] # Always clear state after attempt
        return # Exit after handling delete video

    # --- Handle batch add mode (original logic) ---
    logger.info(f"Admin {user_id} sent a video for batch adding.")

    try:
        if user_id not in batch_add_state or not batch_add_state[user_id].get('batch_mode'):
            logger.warning(f"Admin {user_id} sent video outside of batch add mode, ignoring.")
            return

        category = batch_add_state[user_id].get('current_category')
        if not category:
            logger.warning(f"Admin {user_id} tried to add video but no category set in batch state.")
            await message.reply_text("⚠️ Please set a category first using /category. 🗂️")
            return

        is_valid_category_name, validation_msg = validate_category_name(category)
        if not is_valid_category_name:
            await message.reply_text(f"❌ Invalid category '<b>{html.escape(category)}</b>' set in batch mode: {validation_msg}. Please select a valid category using /category. 🐛")
            logger.error(f"Admin {user_id} attempted to add video to invalid category name '{category}': {validation_msg}")
            return

        if category not in get_categories(): 
            await message.reply_text(f"❌ Category '<b>{html.escape(category)}</b>' does not exist. Please create it first with /addcategory or select an existing one with /category. 🧐")
            logger.error(f"Admin {user_id} attempted to add video to non-existent category '{category}'.")
            return

        if not message.video:
            logger.warning(f"Admin {user_id} sent non-video file in batch add mode.")
            await message.reply_text("❌ Please send a video file. 🎥")
            return

        file_id = message.video.file_id
        file_unique_id = message.video.file_unique_id
        file_size = message.video.file_size
        custom_caption = message.caption # Get the caption provided by the admin

        if media_collection.find_one({"file_unique_id": file_unique_id}):
            logger.warning(f"Admin {user_id} attempted to add duplicate video: {file_unique_id}.")
            await message.reply_text("⚠️ This video has already been added. Skipping.⏩")
            return

        video_uuid = str(uuid.uuid4())
        
        # Determine caption for forwarding to channel
        channel_caption = custom_caption if custom_caption else f"Category: {html.escape(category)}\nSize: {format_size(file_size)}\nUUID: {video_uuid}"

        try:
            forwarded_message = await client.send_video(
                chat_id=config.VIDEO_CHANNEL_ID,
                video=file_id,
                caption=channel_caption, # Use custom caption or default
                protect_content=False
            )
            message_id_in_channel = forwarded_message.id
        except FloodWait as fw:
            wait_time = fw.value
            logger.warning(f"FloodWait encountered when forwarding video to channel: {wait_time}s. Notifying admin and retrying after delay.")
            await message.reply_text(f"⚠️ Flood control triggered! Waiting for <b>{wait_time}</b> seconds before resuming video upload. Next video will be uploaded in approximately <b>{int((wait_time + 5) / 60) + 1}</b> minutes. ⏳") # Add a buffer for calculation
            await asyncio.sleep(wait_time + 1) # Wait and retry
            try:
                forwarded_message = await client.send_video(
                    chat_id=config.VIDEO_CHANNEL_ID,
                    video=file_id,
                    caption=channel_caption,
                    protect_content=False
                )
                message_id_in_channel = forwarded_message.id
            except Exception as forward_e_retry:
                logger.error(f"Failed to forward video {file_unique_id} to channel after FloodWait retry: {forward_e_retry}", exc_info=True)
                await message.reply_text("❌ Failed to forward video to channel after retry. Please check bot's permissions. 🐛")
                return
        except Exception as forward_e:
            logger.error(f"Failed to forward video {file_unique_id} to channel {config.VIDEO_CHANNEL_ID}: {forward_e}", exc_info=True)
            await message.reply_text("❌ Failed to forward video to channel. Please check bot's permissions. 🐛")
            return

        video_data = {
            "uuid": video_uuid,
            "file_id": file_id,
            "file_unique_id": file_unique_id,
            "category": category,
            "size_bytes": file_size,
            "timestamp": get_current_time(),
            "message_id": message_id_in_channel,
            "banned": False,
            "custom_caption": custom_caption # Store the custom caption
        }
        media_collection.insert_one(video_data)
        batch_add_state[user_id]['count'] = batch_add_state[user_id].get('count', 0) + 1
        logger.info(f"Video {video_uuid} (file ID: {file_id}) added to category {category} by admin {user_id}. Message ID in channel: {message_id_in_channel}")
        
        # Reply to admin with details, including custom caption if present
        admin_reply_caption = f"✅ File <code>{html.escape(message.video.file_name or 'unnamed_video')}</code> Added to <b>{html.escape(category)}</b>! 🎉\n"
        if custom_caption:
            admin_reply_caption += f"📝 Custom Caption: <i>{html.escape(custom_caption)}</i>\n"
        admin_reply_caption += (
            f"📁 Category: {html.escape(category)}\n"
            f"📊 Size: {format_size(file_size)}\n"
            f"🆔 File ID: <code>{file_id}</code>\n"
            f"Videos added in this batch: <b>{batch_add_state[user_id]['count']}</b> 🔢"
        )
        await message.reply_text(admin_reply_caption)

    except Exception as e:
        logger.error(f"Admin {user_id} error adding video: {e}", exc_info=True)
        await message.reply("❌ Failed to add video. Please try again. 🐛")

@app.on_message(filters.command("category") & filters.private & filters.user(config.ADMIN_IDS))
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
            buttons.append([InlineKeyboardButton(f"🗂️ {html.escape(category)}", callback_data=f"setcat_{category}")])

        await message.reply_text(
            "Select a category for batch adding videos: 👇",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        logger.info(f"Admin {user_id}: Set category options sent.")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to send set category options: {e}", exc_info=True)
        await message.reply("❌ An error occurred while preparing set category options. Please try again. 🐛")

@app.on_callback_query(filters.regex(r"^setcat_(.+)$"))
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
        category_name = match.group(1)

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
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"🗂️ {html.escape(cat)}", callback_data=f"setcat_{cat}")] for cat in get_categories()])
            )
            logger.warning(f"Admin {user_id} tried to set invalid category: '{category_name}'.")
            return

        batch_add_state[user_id]['current_category'] = category_name
        await callback_query.message.edit_text(f"✅ Category set to '<b>{html.escape(category_name)}</b>' for batch adding. Send videos now or use /done to finish. 🎥")
        await callback_query.answer(f"Category set to '{html.escape(category_name)}'")
        logger.info(f"Admin {user_id} successfully set batch category to '{category_name}'.")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to set batch category: {e}", exc_info=True)
        await callback_query.answer("❌ An error occurred while setting category. Please try again. 🐛", show_alert=True)

@app.on_message(filters.command("stats") & filters.private & filters.user(config.ADMIN_IDS))
async def stats_cmd(client: Client, message: Message):
    """Admin command to display bot statistics."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} requested stats.")
    try:
        total_users = users_collection.count_documents({})
        total_videos = media_collection.count_documents({})
        total_categories = categories_collection.count_documents({})
        await message.reply(f"📊 <b>Bot Statistics</b> 📈\n\n<b>Total Users:</b> {total_users} 👥\n<b>Total Videos:</b> {total_videos} 🎞️\n<b>Total Categories:</b> {total_categories} 🗂️")
        logger.info(f"Admin {user_id} retrieved stats: Users={total_users}, Videos={total_videos}, Categories={total_categories}.")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to retrieve stats: {e}", exc_info=True)
        await message.reply("❌ An error occurred while fetching stats. Please try again. 🐛")

# --- New Admin Commands ---

@app.on_message(filters.command("deletevideo") & filters.private & filters.user(config.ADMIN_IDS))
async def deletevideo_cmd(client: Client, message: Message):
    """Admin command to initiate video deletion mode."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} initiated /deletevideo command.")
    admin_delete_video_state[user_id] = True
    await message.reply("Send the <b>video file from the database</b> to delete it. This must be the original video file, not a forwarded one. 🎥")

@app.on_message(filters.command("categoryrename") & filters.private & filters.user(config.ADMIN_IDS))
async def categoryrename_cmd(client: Client, message: Message):
    """Admin command to initiate category renaming flow."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} initiated /categoryrename command.")
    admin_rename_category_state[user_id] = {'step': 'await_old_name'}
    await message.reply("Please send the <b>current name</b> of the category you want to rename. 📝")

@app.on_message(filters.text & filters.private & filters.user(config.ADMIN_IDS))
async def handle_admin_text_input(client: Client, message: Message):
    """Handles admin's text input for various multi-step commands."""
    user_id = message.from_user.id

    # --- Handle /setshortener input ---
    if user_id in admin_shortener_setup_state and admin_shortener_setup_state[user_id].get('step') == 'await_template_url':
        template_url = message.text.strip()
        
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
            del admin_shortener_setup_state[user_id] # Clear state
            await message.reply("✅ Shortener API Template URL Set Successfully!")
            logger.info(f"Admin {user_id} successfully set shortener template URL: {template_url}")
        except Exception as e:
            logger.error(f"Error saving shortener template URL for admin {user_id}: {e}", exc_info=True)
            await message.reply("❌ Failed to save shortener configuration. Please try again. 🐛")
            del admin_shortener_setup_state[user_id] # Clear state on error
        return # Exit after handling shortener input

    # --- Handle /categoryrename input ---
    if user_id in admin_rename_category_state:
        current_step = admin_rename_category_state[user_id].get('step')
        
        if current_step == 'await_old_name':
            old_name = message.text.strip()
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
            new_name = message.text.strip()
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
                # 1. Rename in categories_collection
                categories_collection.update_one({'name': old_name}, {'$set': {'name': new_name}})
                logger.info(f"Category '{old_name}' renamed to '{new_name}' in categories_collection.")

                # 2. Update category field in media_collection
                media_collection.update_many({'category': old_name}, {'$set': {'category': new_name}})
                logger.info(f"Updated media_collection documents from '{old_name}' to '{new_name}'.")

                # 3. Update category field in users' bookmarked_videos (array of objects)
                # Use arrayFilters to update elements within the array
                users_collection.update_many(
                    {'bookmarked_videos.category': old_name}, # Filter for documents that have the old category in their bookmarks
                    {'$set': {'bookmarked_videos.$[elem].category': new_name}},
                    array_filters=[{'elem.category': old_name}]
                )
                logger.info(f"Updated bookmarked_videos in users_collection from '{old_name}' to '{new_name}'.")

                # 4. Update category field in users' history (array of objects)
                history_collection.update_many(
                    {'history.category': old_name}, # Filter for documents that have the old category in their history
                    {'$set': {'history.$[elem].category': new_name}},
                    array_filters=[{'elem.category': old_name}]
                )
                logger.info(f"Updated history in history_collection from '{old_name}' to '{new_name}'.")

                # 5. Update category key in users' last_viewed_per_category (map/object)
                # This requires iterating through users to handle the dynamic key rename
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
                del admin_rename_category_state[user_id] # Clear state
            return # Exit after handling rename input
    
    # If the message is not part of any ongoing admin multi-step command, ignore it.
    # This prevents non-command text from admins triggering unintended actions.
    logger.debug(f"Admin {user_id} sent text message '{message.text}' not part of any active multi-step command. Ignoring.")


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
        await message.reply(f"Auto-delete feature (for videos *sent into the channel*) is now {'<b>enabled</b> ✅' if new_status else '<b>disabled</b> 🚫'}.")
        logger.info(f"Admin {user_id} toggled auto-delete to {'enabled' if new_status else 'disabled'}.")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to toggle auto-delete: {e}", exc_info=True)
        await message.reply("❌ An error occurred while toggling auto-delete. Please try again. 🐛")

@app.on_message(filters.command('toggle_protect') & filters.private & filters.user(config.ADMIN_IDS))
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

# --- Database Cleanup (No longer deletes messages from chats) ---
async def cleanup_expired_data():
    """Periodically cleans up expired tokens and handles bookmark truncation for non-premium users."""
    while True:
        try:
            now = datetime.utcnow()
            
            # 1. Clean up expired tokens for all users
            # The $pull operator directly removes elements from the 'tokens' array
            # where 'expires_at' is less than the current time.
            tokens_collection.update_many(
                {},
                {'$pull': {'tokens': {'expires_at': {'$lt': now}}}}
            )
            logger.info("Expired tokens cleanup completed.")
            
            # 2. Handle bookmark truncation for users who are *not* currently premium
            # We need to iterate through users to check their live premium status
            # after tokens have been cleaned up.
            all_users = users_collection.find({})
            for user in all_users:
                user_id = user['user_id']
                
                # Check if the user is currently premium based on current tokens
                is_currently_premium = is_premium_user(user_id) # This call now uses the updated logic

                bookmarked_videos = user.get('bookmarked_videos', [])
                
                # If user is not premium and has too many bookmarks, truncate them
                if not is_currently_premium and len(bookmarked_videos) > config.FREE_USER_SAVE_LIMIT:
                    # Sort by bookmarked_at (most recent first) and keep only the latest allowed
                    bookmarked_videos.sort(key=lambda x: x.get('bookmarked_at', datetime.min), reverse=True)
                    truncated_bookmarks = bookmarked_videos[:config.FREE_USER_SAVE_LIMIT]
                    
                    users_collection.update_one(
                        {'user_id': user_id},
                        {'$set': {'bookmarked_videos': truncated_bookmarks}}
                    )
                    logger.info(f"User {user_id}'s bookmarked videos truncated to {config.FREE_USER_SAVE_LIMIT}.")
                
                # The "no longer premium" message is handled at user interaction points
                # via `check_premium_status_and_notify`.

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
        
        await asyncio.sleep(86400) # Run once every 24 hours

async def verify_and_cleanup_media():
    """Periodically verifies if media files still exist in the channel and logs missing/inaccessible entries, but does NOT delete anything."""
    while True:
        logger.info("Starting media verification and cleanup task.")
        try:
            all_media = list(media_collection.find({}))
            for media_item in all_media:
                video_uuid = media_item.get('uuid')
                message_id_in_channel = media_item.get('message_id')
                
                if not message_id_in_channel:
                    logger.warning(f"Media item {video_uuid} has no message_id in channel. (Would delete, but deletion is disabled)")
                    continue

                try:
                    await app.get_messages(config.VIDEO_CHANNEL_ID, message_id_in_channel)
                    logger.debug(f"Verified media {video_uuid} (message_id: {message_id_in_channel}) exists in channel.")
                except (MessageIdInvalid, ValueError):
                    logger.warning(f"Video {video_uuid} (message_id: {message_id_in_channel}) no longer exists in channel. (Would delete, but deletion is disabled)")
                    continue
                except Exception as e:
                    logger.error(f"Error verifying media {video_uuid} in channel {config.VIDEO_CHANNEL_ID}: {e}", exc_info=True)
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
        
        await asyncio.sleep(6 * 3600) # Run every 6 hours

async def health_check():
    print("Session file exists:", os.path.exists("/data/spicynyraa.session"))
    try:
        me = await app.get_me()
        print(f"Bot username: {me.username}")
        member = await app.get_chat_member(config.VIDEO_CHANNEL_ID, me.id)
        print(f"Bot status in channel: {member.status}")
        # Try to fetch a real message_id if possible, else 1
        msg = await app.get_messages(config.VIDEO_CHANNEL_ID, 1)
        print("Fetched message:", msg)
        # Also check the force subscribe channel
        force_sub_member = await app.get_chat_member(config.FORCE_SUB_CHANNEL_ID, me.id)
        print(f"Bot status in force subscribe channel ({config.FORCE_SUB_CHANNEL_ID}): {force_sub_member.status}")
    except Exception as e:
        print("Health check failed:", e)

async def main_bot_logic():
    """
    Main function to start the bot and schedule background tasks.
    This function will be run once by app.run().
    """
    logger.info("Starting bot and scheduling background tasks...")
    
    # Start the Pyrogram client
    await app.start()
    await health_check()  # Run health check after starting app
    logger.info("Bot has connected to Telegram.")

    # Schedule background tasks
    create_tracked_task(cleanup_expired_data())
    create_tracked_task(verify_and_cleanup_media())

    logger.info("Background tasks initiated. Bot is now fully operational.")

    # Keep the bot alive
    await asyncio.Event().wait()


if __name__ == "__main__":
    logger.info("Script started. Entering main execution block.")
    try:
        # Pyrogram's app.run() is a blocking call that starts the bot and
        # runs the provided coroutine (main_bot_logic) within its own event loop.
        # It then handles long polling internally.
        app.run(main_bot_logic())
    except KeyboardInterrupt:
        logger.info("Bot stopped by KeyboardInterrupt (Ctrl+C). Shutting down...")
        # Pyrogram's app.run() usually handles app.stop() on Ctrl+C.
        # Ensure any custom cleanup is performed here if needed outside app.stop().
    except Exception as e:
        logger.critical(f"An unhandled error occurred during bot startup or main execution: {e}", exc_info=True)
    finally:
        logger.info("Application exiting.")
        # Any final cleanup can go here
