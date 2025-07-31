import os
import asyncio
import uuid
import base64
import logging
from datetime import datetime, timedelta
from pyrogram import Client, filters
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, Message, InputMediaVideo, CallbackQuery
)
from pyrogram.errors import UserIsBlocked, ChatInvalid, MessageIdInvalid, FloodWait, PeerIdInvalid, RPCError, FileIdInvalid, FileReferenceExpired, ChatAdminRequired
from pyrogram.enums import ChatMemberStatus
from pymongo import MongoClient, ASCENDING, DESCENDING, ReturnDocument, UpdateOne # Import UpdateOne for bulk operations
import aiohttp
from aiohttp import ClientTimeout
from collections import defaultdict
import re
import html
import urllib.parse
from shortzy import Shortzy

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Configuration ---
class BotConfig:
    BOT_TOKEN = '7646433933:AAGBHd4xGgfNiPrZ_Tn36so6DdDbK9J6d84'
    API_ID = 29800015
    API_HASH = 'c8f37108be31ab9ea2818bfe533fbb6f'
    BOT_USERNAME = '@SpicyNyraa_bot'
    MONGO_URI = 'mongodb+srv://Pyasipriya:00pEcao9sYhNC5VQ@cluster0.2dfenf7.mongodb.net/spicybot?retryWrites=true&w=majority&appName=Cluster0'
    MONGO_DB_NAME = 'spicybot'
    VIDEO_CHANNEL_ID = -1002621716446 # Your video storage channel ID
    BUY_BOT_URL = 'https://t.me/hanielxsupportbot'
    # OWNER_ID is the only hardcoded ID. All other admins are managed dynamically.
    OWNER_ID = 6612030110 # Replace with the actual Telegram User ID of the bot owner
    TUTORIAL_LINK_2 = 'https://t.me/urlshortenertutorial'
    TOKEN_EXPIRY = 86400  # 24 hours in seconds (for regular tokens, not premium)
    NEW_USER_TOKENS = 1
    REFERRAL_BONUS = 1
    REFRESH_BONUS = 1
    PREMIUM_TRIAL_PRICE_INR = 69
    PREMIUM_MONTH_PRICE_INR = 199
    FREE_USER_SAVE_LIMIT = 100 # Maximum saved videos for free users
    FORCE_SUB_CHANNEL_ID = -1002622483638
    FORCE_SUB_CHANNEL_LINK = "https://t.me/SpicyNyraa"
    MENU_EXPIRY_MINUTES = 60
    REFRESH_TOKEN_LINK_EXPIRY_SECONDS = 900 # 5 minutes for refresh token links to be valid

try:
    config = BotConfig()
    if not all([config.BOT_TOKEN, config.API_ID, config.API_HASH, config.MONGO_URI, config.BOT_USERNAME, config.FORCE_SUB_CHANNEL_ID, config.FORCE_SUB_CHANNEL_LINK, config.OWNER_ID]):
        raise ValueError("One or more essential configuration variables are not set. Please check BOT_TOKEN, API_ID, API_HASH, MONGO_URI, BOT_USERNAME, FORCE_SUB_CHANNEL_ID, FORCE_SUB_CHANNEL_LINK, OWNER_ID.")
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
refresh_tokens_used_collection = db['refresh_tokens_used']
admins_collection = db['admins'] # New collection for dynamic admins

# Create indexes
users_collection.create_index([("user_id", ASCENDING)], unique=True)
tokens_collection.create_index([("user_id", ASCENDING)], unique=True)
media_collection.create_index([("uuid", ASCENDING)], unique=True)
media_collection.create_index([("category", ASCENDING)])
media_collection.create_index([("file_unique_id", ASCENDING)], unique=True)
media_collection.create_index([("size_bytes", ASCENDING)])
# IMPORTANT: New index for sequential navigation within categories
media_collection.create_index([("category", ASCENDING), ("sequence_number", ASCENDING)])
history_collection.create_index([("user_id", ASCENDING)], unique=True)
categories_collection.create_index([("name", ASCENDING)], unique=True)
refresh_tokens_used_collection.create_index([("ad_code", ASCENDING)], unique=True)
refresh_tokens_used_collection.create_index([("used_at", ASCENDING)], expireAfterSeconds=config.REFRESH_TOKEN_LINK_EXPIRY_SECONDS * 2)
admins_collection.create_index([("user_id", ASCENDING)], unique=True) # Index for admins collection

# --- Pyrogram Client ---
app = Client("./spicynyraa", api_id=config.API_ID, api_hash=config.API_HASH, bot_token=config.BOT_TOKEN)

# --- GLOBAL SET FOR TRACKING ASYNC TASKS ---
active_tasks = set()

# --- Admin State for Shortener Setup ---
admin_shortener_setup_state = defaultdict(dict) 

# --- Admin State for Delete Video ---
admin_delete_video_state = defaultdict(bool)

# --- Admin State for Category Rename ---
admin_rename_category_state = defaultdict(dict)

# --- Owner State for Add/Remove Admin ---
owner_addadmin_state = defaultdict(bool) # True when awaiting user_id|username
owner_removeadmin_state = defaultdict(bool) # True when awaiting admin selection

# --- Message Tracking and Immediate Deletion ---
active_video_message = {} 


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

# --- Admin Check Utility ---
def is_owner(user_id: int) -> bool:
    """Checks if the given user ID belongs to the bot owner."""
    return user_id == config.OWNER_ID

def is_admin(user_id: int) -> bool:
    """Checks if the given user ID belongs to an administrator (including the owner)."""
    if is_owner(user_id):
        return True
    return admins_collection.find_one({'user_id': user_id}) is not None

# --- Force Subscribe Check ---
async def check_membership(client: Client, user_id: int) -> bool:
    """
    Checks if the user is a member of the force subscribe channel.
    Returns True if a member (or admin), False otherwise.
    """
    if is_admin(user_id): # Admins and Owners bypass
        return True

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
        return True # Allow access if force sub channel itself is invalid
    except Exception as e:
        logger.error(f"Error checking membership for user {user_id} in channel {config.FORCE_SUB_CHANNEL_ID}: {e}", exc_info=True)
        return False

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
    return base64.urlsafe_b64encode(string.encode('utf-8')).decode('utf-8')

def b64_to_str(b64: str) -> str:
    """Decodes a URL-safe base64 string."""
    try:
        return base64.urlsafe_b64decode(b64.encode('utf-8')).decode('utf-8')
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
    If is_admin_granted is True, this token signifies premium access.
    """
    now = datetime.utcnow()
    expires_at = now + timedelta(seconds=duration_seconds)
    token = {
        'token_id': str(uuid.uuid4()),
        'created_at': now,
        'expires_at': expires_at,
        'is_admin_granted': is_admin_granted
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

    if last_known_premium_status and not current_premium_status:
        try:
            await client.send_message(user_id, "⚠️ <b>Your Premium Access Has Expired!</b> 💔\n\nYour premium token has expired. You are no longer a premium user. Enjoy regular features or purchase new premium access! 🛒")
            users_collection.update_one(
                {'user_id': user_id},
                {'$set': {'last_premium_check_status': current_premium_status}}
            )
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

def get_first_video_by_sequence_number(category: str) -> dict | None:
    """
    Retrieves the first video in the specified category based on its sequence_number.
    """
    video = media_collection.find_one(
        {'category': category},
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
        
        filtered_saved_videos.sort(key=lambda x: x.get('bookmarked_at', datetime.min))
        
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
            {'category': category},
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
        {'category': category, 'sequence_number': {'$gt': current_sequence}},
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
        {'category': category, 'sequence_number': {'$lt': current_sequence}},
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
    
    filtered_saved_videos.sort(key=lambda x: x.get('bookmarked_at', datetime.min))

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
    
    filtered_saved_videos.sort(key=lambda x: x.get('bookmarked_at', datetime.min))

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


def save_history(user_id: int, video_uuid: str, category: str):
    """
    Saves a video viewing entry to a user's general history (limited to 100 entries)
    AND updates the last viewed video for the specific category.
    """
    now = datetime.utcnow()
    entry = {'video_uuid': video_uuid, 'category': category, 'viewed_at': now}
    try:
        history_collection.update_one(
            {'user_id': user_id},
            {'$push': {'history': {'$each': [entry], '$slice': -100}}},
            upsert=True
        )
        logger.info(f"General history saved for user {user_id}, video {video_uuid}. History size limited to 100.")

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

def set_active_video_message(user_id: int, message_id: int, chat_id: int):
    """Set the active message for a user, to be deleted on next action."""
    active_video_message[user_id] = {
        'message_id': message_id,
        'chat_id': chat_id,
        'timestamp': datetime.utcnow()
    }
    logger.info(f"Active video message set for user {user_id}: message_id={message_id}, chat_id={chat_id}")

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
                logger.info(f"Checking bot permissions to delete message {message_id_in_channel} from channel {config.VIDEO_CHANNEL_ID}.")
                try:
                    me = await client.get_me()
                    member = await client.get_chat_member(config.VIDEO_CHANNEL_ID, me.id)
                    
                    if member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER] and member.can_delete_messages:
                        await client.delete_messages(config.VIDEO_CHANNEL_ID, message_id_in_channel)
                        logger.info(f"Successfully deleted message {message_id_in_channel} from channel {config.VIDEO_CHANNEL_ID}.")
                    else:
                        logger.warning(f"Bot lacks 'Delete Messages' permission in channel {config.VIDEO_CHANNEL_ID}. Cannot delete message {message_id_in_channel}. DB entry removed.")
                except MessageIdInvalid:
                    logger.warning(f"Message {message_id_in_channel} already deleted or invalid in channel {config.VIDEO_CHANNEL_ID}. DB entry removed.")
                except FloodWait as fw:
                    logger.warning(f"FloodWait deleting message {message_id_in_channel}: {fw.value}s. Skipping channel deletion for now. DB entry removed.")
                except ChatAdminRequired:
                    logger.warning(f"Bot is not admin in channel {config.VIDEO_CHANNEL_ID}. Cannot delete message {message_id_in_channel}. DB entry removed.")
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

async def send_and_replace_message(client: Client, chat_id: int, message_id_to_edit_or_delete: int, new_message_type: str, video_data: dict = None, reply_markup: InlineKeyboardMarkup = None, text_content: str = None, force_new_message: bool = False, retry_count: int = 0) -> tuple[bool, Message | str]:
    """
    Attempts to edit an existing message or deletes the old message (if provided) and sends a new one.
    Includes self-healing logic for broken videos.
    Returns (success: bool, sent_message: Message | error_message: str)
    """
    MAX_RETRIES = 3 # Max attempts to find a valid video after encountering a broken one
    
    sent_message = None
    success = False
    error_message = ""

    settings = settings_collection.find_one({'_id': 'settings'}) or {}
    protect_content_for_user = settings.get('protect_content', True)

    # Determine if it's a saved video navigation based on the current reply_markup
    is_saved_from_markup = False
    if reply_markup:
        for row in reply_markup.inline_keyboard:
            for button in row:
                if button.callback_data and '|' in button.callback_data:
                    parts = button.callback_data.split('|')
                    # Check for 'next' or 'prev' callbacks and the is_saved flag
                    if len(parts) == 4 and (parts[0] == 'next' or parts[0] == 'prev'):
                        is_saved_from_markup = bool(int(parts[3]))
                        break
            if is_saved_from_markup:
                break

    try:
        if new_message_type == "video" and video_data:
            # Recalculate position for the current video_data
            video_to_display_with_pos, current_position, total_videos = get_video_and_position(
                video_data['uuid'], video_data.get('category'), is_saved_from_markup, chat_id
            )
            
            caption_text = None
            if video_data.get('custom_caption'):
                caption_text = video_data['custom_caption']
            elif video_data.get('category'):
                caption_text = f"Category: {html.escape(video_data['category'])}"
            
            if total_videos > 0 and current_position > 0: # Only show position if valid
                caption_text = f"#{current_position} of {total_videos}\n" + (caption_text if caption_text else "")

            # --- Attempt to Edit Existing Message (for video) ---
            if message_id_to_edit_or_delete and not force_new_message:
                try:
                    sent_message = await client.edit_message_media(
                        chat_id=chat_id,
                        message_id=message_id_to_edit_or_delete,
                        media=InputMediaVideo(
                            media=video_data['file_id'],
                            caption=caption_text
                        ),
                        reply_markup=reply_markup
                    )
                    success = True
                    logger.info(f"Edited message {message_id_to_edit_or_delete} in chat {chat_id} with new video {video_data['uuid']}.")
                except (MessageIdInvalid, FileIdInvalid, FileReferenceExpired, RPCError) as e:
                    logger.warning(f"Video edit failed for {video_data['uuid']} (Msg ID: {video_data.get('message_id')}) due to Telegram API error: {e}. Assuming broken video. Retries: {retry_count}/{MAX_RETRIES}")
                    
                    if retry_count < MAX_RETRIES:
                        await client.send_message(chat_id, "Oops! This video was unavailable and has been removed. Trying the next one... 🔄")
                        await delete_broken_video_from_db_and_channel(
                            client,
                            video_data['uuid'],
                            video_data.get('category'),
                            video_data.get('sequence_number'),
                            video_data.get('message_id')
                        )
                        
                        # Determine next video based on current navigation type
                        next_video = None
                        if is_saved_from_markup:
                            next_video = get_next_saved_video_chronological(chat_id, video_data['uuid'], video_data.get('category'))
                        else:
                            next_video = get_next_video_chronological(video_data['uuid'], video_data.get('category'))

                        if next_video:
                            logger.info(f"Attempting recursive call for next video {next_video['uuid']} after deleting broken one.")
                            # Recursively call send_and_replace_message for the next video
                            return await send_and_replace_message(
                                client,
                                chat_id,
                                message_id_to_edit_or_delete, # Try to edit the same message again
                                "video",
                                next_video,
                                # IMPORTANT: Generate new keyboard for the NEXT video
                                video_nav_keyboard(next_video['uuid'], next_video['category'], chat_id, is_saved=is_saved_from_markup),
                                force_new_message=False, # Try to edit again
                                retry_count=retry_count + 1
                            )
                        else:
                            logger.error(f"No valid next video found after deleting broken {video_data['uuid']}. Ending navigation.")
                            error_message = "❌ No more valid videos found in this category. 😔"
                            success = False
                    else:
                        logger.error(f"Max retries ({MAX_RETRIES}) reached for broken video {video_data['uuid']}. Ending navigation.")
                        error_message = "❌ Multiple videos unavailable. Please try changing category. 😥"
                        success = False
                except FloodWait as fw:
                    logger.warning(f"FloodWait encountered when editing video: {fw.value}s. Retrying after delay.")
                    await asyncio.sleep(fw.value + 1)
                    try:
                        sent_message = await client.edit_message_media(
                            chat_id=chat_id,
                            message_id=message_id_to_edit_or_delete,
                            media=InputMediaVideo(
                                media=video_data['file_id'],
                                caption=caption_text
                            ),
                            reply_markup=reply_markup
                        )
                        success = True
                        logger.info(f"Edited message {message_id_to_edit_or_delete} after FloodWait.")
                    except Exception as e2:
                        logger.error(f"Failed to edit video after FloodWait: {e2}")
                        error_message = f"❌ <b>Failed to update message.</b>\nReason: {e2}\nPlease try again later. 😥"
                        success = False
                except Exception as e:
                    logger.error(f"Failed to edit message {message_id_to_edit_or_delete} with new video: {e}", exc_info=True)
                    # Fallback to sending new message if edit fails for other reasons, but don't loop
                    error_message = f"❌ <b>Failed to update message.</b>\nReason: {e}\nPlease try again later. 😥"
                    success = False

        if not success or force_new_message: # If edit failed or forced new message
            if message_id_to_edit_or_delete:
                try:
                    await client.delete_messages(chat_id, message_id_to_edit_or_delete)
                    logger.info(f"Deleted old message {message_id_to_edit_or_delete} in chat {chat_id} before sending new.")
                except MessageIdInvalid:
                    logger.warning(f"Old message {message_id_to_edit_or_delete} for deletion in chat {chat_id} was already invalid or deleted.")
                except Exception as e:
                    logger.error(f"Failed to delete old message {message_id_to_edit_or_delete} in chat {chat_id}: {e}")
            
            if new_message_type == "video" and video_data:
                # --- Attempt to Send New Video Message ---
                try:
                    sent_message = await client.copy_message(
                        chat_id=chat_id,
                        from_chat_id=config.VIDEO_CHANNEL_ID,
                        message_id=video_data.get('message_id'),
                        caption=caption_text,
                        protect_content=protect_content_for_user,
                        reply_markup=reply_markup
                    )
                    success = True
                except (MessageIdInvalid, FileIdInvalid, FileReferenceExpired, RPCError) as e:
                    logger.warning(f"Video send failed for {video_data['uuid']} (Msg ID: {video_data.get('message_id')}) due to Telegram API error: {e}. Assuming broken video. Retries: {retry_count}/{MAX_RETRIES}")
                    
                    if retry_count < MAX_RETRIES:
                        await client.send_message(chat_id, "Oops! This video was unavailable and has been removed. Trying the next one... 🔄")
                        await delete_broken_video_from_db_and_channel(
                            client,
                            video_data['uuid'],
                            video_data.get('category'),
                            video_data.get('sequence_number'),
                            video_data.get('message_id')
                        )
                        
                        # Determine next video based on current navigation type
                        next_video = None
                        if is_saved_from_markup:
                            next_video = get_next_saved_video_chronological(chat_id, video_data['uuid'], video_data.get('category'))
                        else:
                            next_video = get_next_video_chronological(video_data['uuid'], video_data.get('category'))

                        if next_video:
                            logger.info(f"Attempting recursive call for next video {next_video['uuid']} after deleting broken one.")
                            # Recursively call send_and_replace_message for the next video
                            return await send_and_replace_message(
                                client,
                                chat_id,
                                message_id_to_edit_or_delete, # Try to edit the same message again (will force new message if fails)
                                "video",
                                next_video,
                                # IMPORTANT: Generate new keyboard for the NEXT video
                                video_nav_keyboard(next_video['uuid'], next_video['category'], chat_id, is_saved=is_saved_from_markup),
                                force_new_message=True, # Force new message if previous attempt was also a new message
                                retry_count=retry_count + 1
                            )
                        else:
                            logger.error(f"No valid next video found after deleting broken {video_data['uuid']}. Ending navigation.")
                            error_message = "❌ No more valid videos found in this category. 😔"
                            success = False
                    else:
                        logger.error(f"Max retries ({MAX_RETRIES}) reached for broken video {video_data['uuid']}. Ending navigation.")
                        error_message = "❌ Multiple videos unavailable. Please try changing category. 😥"
                        success = False
                except FloodWait as fw:
                    logger.warning(f"FloodWait encountered when sending video by message_id: {fw.value}s. Retrying after delay.")
                    await asyncio.sleep(fw.value + 1)
                    try:
                        sent_message = await client.copy_message(
                            chat_id=chat_id,
                            from_chat_id=config.VIDEO_CHANNEL_ID,
                            message_id=video_data.get('message_id'),
                            caption=caption_text,
                            protect_content=protect_content_for_user,
                            reply_markup=reply_markup
                        )
                        success = True
                    except Exception as e2:
                        logger.error(f"Failed to copy video after FloodWait: {e2}")
                        error_message = f"❌ <b>Failed to send message.</b>\nReason: {e2}\nPlease try again later. 😥"
                        success = False
                except Exception as e:
                    logger.error(f"Failed to copy video from channel by message_id: {e}. Falling back to file_id.", exc_info=True)
                    try:
                        sent_message = await client.send_video(
                            chat_id,
                            video_data['file_id'],
                            caption=caption_text,
                            reply_markup=reply_markup,
                            protect_content=protect_content_for_user
                        )
                        success = True
                    except (MessageIdInvalid, FileIdInvalid, FileReferenceExpired, RPCError) as e2:
                        logger.warning(f"Video send failed by file_id for {video_data['uuid']} due to Telegram API error: {e2}. Assuming broken video. Retries: {retry_count}/{MAX_RETRIES}")
                        
                        if retry_count < MAX_RETRIES:
                            await client.send_message(chat_id, "Oops! This video was unavailable and has been removed. Trying the next one... 🔄")
                            await delete_broken_video_from_db_and_channel(
                                client,
                                video_data['uuid'],
                                video_data.get('category'),
                                video_data.get('sequence_number'),
                                video_data.get('message_id')
                            )
                            
                            # Determine next video based on current navigation type
                            next_video = None
                            if is_saved_from_markup:
                                next_video = get_next_saved_video_chronological(chat_id, video_data['uuid'], video_data.get('category'))
                            else:
                                next_video = get_next_video_chronological(video_data['uuid'], video_data.get('category'))

                            if next_video:
                                logger.info(f"Attempting recursive call for next video {next_video['uuid']} after deleting broken one.")
                                # Recursively call send_and_replace_message for the next video
                                return await send_and_replace_message(
                                    client,
                                    chat_id,
                                    message_id_to_edit_or_delete, # Try to edit the same message again (will force new message if fails)
                                    "video",
                                    next_video,
                                    # IMPORTANT: Generate new keyboard for the NEXT video
                                    video_nav_keyboard(next_video['uuid'], next_video['category'], chat_id, is_saved=is_saved_from_markup),
                                    force_new_message=True, # Force new message if previous attempt was also a new message
                                    retry_count=retry_count + 1
                                )
                            else:
                                logger.error(f"No valid next video found after deleting broken {video_data['uuid']}. Ending navigation.")
                                error_message = "❌ No more valid videos found in this category. 😔"
                                success = False
                        else:
                            logger.error(f"Max retries ({MAX_RETRIES}) reached for broken video {video_data['uuid']}. Ending navigation.")
                            error_message = "❌ Multiple videos unavailable. Please try changing category. 😥"
                            success = False
                    except FloodWait as fw:
                        logger.warning(f"FloodWait encountered when sending video by file_id: {fw.value}s. Retrying after delay.")
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
        logger.error(f"An unexpected error occurred in send_and_replace_message: {e}", exc_info=True)
        error_message = f"❌ <b>An unexpected error occurred.</b>\nReason: {e}\nPlease try again later. 😥"
        success = False

    if success and isinstance(sent_message, Message):
        set_active_video_message(chat_id, sent_message.id, chat_id)
        logger.info(f"Message {sent_message.id} of type {new_message_type} sent/edited and active video message updated for user {chat_id}.")
        return True, sent_message
    else:
        logger.error(f"Failed to send/edit message in send_and_replace_message: {error_message}")
        return False, error_message

# --- Keyboards ---
async def get_main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    """Main keyboard for the bot."""
    buttons = [
        [KeyboardButton("🎞️ Get Video"), KeyboardButton("👤 Profile")],
        [KeyboardButton("🔗 Refer & Earn"), KeyboardButton("💰 Buy Token")],
        [KeyboardButton("🔄 Refresh Token"), KeyboardButton("🔖 Saved Videos")]
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def token_earning_keyboard(ad_url: str) -> InlineKeyboardMarkup:
    """Keyboard for token earning options."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👆 Click Here To Refresh Token", url=ad_url)],
        [InlineKeyboardButton("🔗 Refer & Earn", callback_data="refer_and_earn_inline")],
        [InlineKeyboardButton("❓ How To Open Links?", url=config.TUTORIAL_LINK_2)],
        [InlineKeyboardButton("💳 Buy Token", url=config.BUY_BOT_URL)],
    ])

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

def video_nav_keyboard(video_uuid: str, category: str, user_id: int, is_saved: bool = False) -> InlineKeyboardMarkup:
    """
    Keyboard for navigating videos, with button arrangements based on whether it's a saved video.
    The 'Download' button is now always shown.
    """
    buttons = []

    buttons.append([
        # Changed: Encode category name for callback data
        InlineKeyboardButton("⬅️ Previous", callback_data=f"prev|{video_uuid}|{str_to_b64(category)}|{int(is_saved)}"), 
        InlineKeyboardButton("➡️ Next", callback_data=f"next|{video_uuid}|{str_to_b64(category)}|{int(is_saved)}") 
    ])

    row_2_buttons = [
        InlineKeyboardButton("🗂️ Change Category", callback_data="change_cat"),
        InlineKeyboardButton("📲 Share", callback_data=f"share_{video_uuid}"),
        InlineKeyboardButton("⬇️ Download", callback_data=f"download_{video_uuid}")
    ]
    buttons.append(row_2_buttons)

    row_3_buttons = []
    if is_saved:
        row_3_buttons.append(InlineKeyboardButton("🗑️ Remove", callback_data=f"remove_saved_{video_uuid}"))
    row_3_buttons.append(InlineKeyboardButton("💾 Bookmark", callback_data=f"bookmark_{video_uuid}"))
    
    if row_3_buttons:
        buttons.append(row_3_buttons)

    return InlineKeyboardMarkup(buttons)

def referral_keyboard(ref_link: str) -> InlineKeyboardMarkup:
    """Keyboard for displaying a referral link."""
    # This function is now unused as per the new profile design, but kept for reference if needed elsewhere.
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Copy Referral Link", url=ref_link)]
    ])

def buy_token_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for buying tokens."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Buy Token", url=config.BUY_BOT_URL)]
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
            return False, "⚠️ You're refreshing too quickly. Please wait a minute and try again. ⏳"

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
            refresh_tokens_used_collection.insert_one({'ad_code': ad_code, 'used_at': datetime.utcnow()})
            return False, "This token refresh link has expired. ⏰"

        if refresh_tokens_used_collection.find_one({'ad_code': ad_code}):
            logger.warning(f"User {user_id} attempted to reuse token refresh link: {ad_code}")
            return False, "This token refresh link has already been used. Please generate a new one. 🔄"
            
        added_token = add_token(user_id, config.REFRESH_BONUS * 86400, is_admin_granted=False)
        if added_token:
            refresh_tokens_used_collection.insert_one({'ad_code': ad_code, 'used_at': datetime.utcnow()})
            logger.info(f"Token added for user {user_id} via refresh. Premium status unaffected. Ad code {ad_code} marked as used.")
            return True, f"🎉 <b>Success!</b> You got {config.REFRESH_BONUS} token. Each token lasts 24 hours. Enjoy! 🍿"
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
            if not await check_membership(client, user_id):
                await send_force_subscribe_message(client, user_id)
                return

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
                    'last_premium_check_status': False,
                    'last_viewed_per_category': {},
                })
                add_token(user_id, config.NEW_USER_TOKENS * 86400, is_admin_granted=False)
                logger.info(f"New user registered: {user_id} and received {config.NEW_USER_TOKENS} token.")

            create_tracked_task(check_premium_status_and_notify(client, user_id))

            deep_link_type = None
            video_uuid_from_link = None
            referrer_id_from_video_link = None
            deep_link_data = None # Initialize deep_link_data

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
                elif deep_link_arg.startswith('ref_'):
                    deep_link_type = 'referral'
                    deep_link_data = deep_link_arg
                elif deep_link_arg.startswith('saved_video_'):
                    deep_link_type = 'view_saved_video'
                    video_uuid_from_link = deep_link_arg[12:]

            if is_new_user:
                if deep_link_type == 'referral':
                    referrer_id = handle_referral(user_id, deep_link_data)
                    if referrer_id:
                        await message.reply(
                            f"👋 Congratulations, {first_name_safe}! 🎉 You've received {config.NEW_USER_TOKENS} token 🌶️. To watch spicy content, click on the '🎞️ Get Video' button. Need help? Tap /help. ✨", 
                            reply_markup=await get_main_keyboard(user_id)
                        )
                        await client.send_message(referrer_id, f"🎉 <b>Referral Bonus!</b> Your friend, {first_name_safe}, joined through your link! You've received {config.REFERRAL_BONUS} token. Awesome! 🤩")
                elif deep_link_type == 'video_share' and referrer_id_from_video_link and referrer_id_from_video_link != user_id:
                    referrer_user_obj = users_collection.find_one({'user_id': referrer_id_from_video_link})
                    if referrer_user_obj:
                        await message.reply(
                            f"👋 Congratulations, {first_name_safe}! 🎉 You've received {config.NEW_USER_TOKENS} token 🌶️. To watch spicy content, click on the '🎞️ Get Video' button. Need help? Tap /help. ✨", 
                            reply_markup=await get_main_keyboard(user_id)
                        )
                        await client.send_message(referrer_id_from_video_link, f"🎉 <b>Referral Bonus!</b> Your friend, {first_name_safe}, joined through your shared video link! You've received {config.REFERRAL_BONUS} token. Awesome! 🤩")
                    else:
                        logger.warning(f"Referrer {referrer_id_from_video_link} not found for new user {user_id} via video share. Still sending new user welcome.")
                        await message.reply(
                            f"👋 Congratulations, {first_name_safe}! 🎉 You've received {config.NEW_USER_TOKENS} token 🌶️. To watch spicy content, click on the '🎞️ Get Video' button. Need help? Tap /help. ✨", 
                            reply_markup=await get_main_keyboard(user_id)
                        )
                else:
                    await message.reply(
                        f"👋 Congratulations, {first_name_safe}! 🎉 You've received {config.NEW_USER_TOKENS} token 🌶️. To watch spicy content, click on the '🎞️ Get Video' button. Need help? Tap /help. ✨", 
                        reply_markup=await get_main_keyboard(user_id)
                    )
            elif not deep_link_type:
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
                
                if not user_has_token(user_id):
                    await message.reply("You need a token to watch this video. Please get a token first! 🧐", reply_markup=await get_main_keyboard(user_id))
                    await send_token_earning_options(client, message)
                    break
                else:
                    success, result_or_msg = await handle_shared_video(client, user_id, video_uuid_from_link)
                    if not success:
                        await message.reply(result_or_msg, reply_markup=await get_main_keyboard(user_id))
                        break

                    video = result_or_msg
                    
                    message_id_to_edit_or_delete = message.id
                    
                    is_saved_video_link = (deep_link_type == 'view_saved_video')
                    
                    # Get position for display
                    video_to_display_with_pos, current_position, total_videos = get_video_and_position(
                        video['uuid'], video['category'], is_saved_video_link, user_id
                    )

                    sent_success, sent_message_or_error = await send_and_replace_message(
                        client,
                        message.chat.id,
                        message_id_to_edit_or_delete=message_id_to_edit_or_delete,
                        new_message_type="video",
                        video_data=video,
                        reply_markup=video_nav_keyboard(video['uuid'], video['category'], user_id, is_saved=is_saved_video_link),
                        force_new_message=True # Always force new message for start deep links
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
    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    user_mention_safe = html.escape(message.from_user.first_name) if message.from_user.first_name else "there"
    create_tracked_task(check_premium_status_and_notify(client, user_id))

    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Support", url=config.BUY_BOT_URL)]
    ])

    await message.reply(
        f"👋 dear {user_mention_safe}! This is how to use Spicy Nyraa Bot! 📚\n\n"
        "- Use '🎞️ Get Video' to watch spicy content. 🔥\n"
        "- Each token gives you 24 hours access. ⏳\n"
        "- Earn tokens by referral, refreshing ads, or buying them. 💰\n"
        "- Use '👤 Profile' to check your stats. 📈\n"
        "- Use '🔖 Saved Videos' to view your bookmarked videos. ❤️\n\n"
        "Enjoy your spicy journey! 🌶️\n\n"
        "Any issue? DM here!",
        reply_markup=reply_markup
    )

@app.on_message(filters.command("profile") & filters.private)
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
                'joined_date': datetime.utcnow(),
                'referral_count': 0,
                'bookmarked_videos': [],
                'last_premium_check_status': False,
                'last_viewed_per_category': {},
            })
            user = users_collection.find_one({'user_id': user_id})
            if not user:
                raise Exception("Failed to create or retrieve user document for profile.")


        tokens_doc = tokens_collection.find_one({'user_id': user_id})
        
        tokens_count = 0
        if tokens_doc and 'tokens' in tokens_doc:
            now = datetime.utcnow()
            tokens_count = sum(1 for token in tokens_doc['tokens'] if token.get('expires_at') and token['expires_at'] > now)

        referral_count = user.get('referral_count', 0)
        # Removed referred_by as it's not displayed in the new format
        bookmarked_videos = user.get('bookmarked_videos', [])
        
        is_premium = is_premium_user(user_id)
        user_status = "Premium User 💎" if is_premium else "Free User ✨"
        
        # The prompt only asks for "Saved Videos: 3" without the limit, so simplifying this
        # If premium, it's unlimited, so just show the count.
        # If free, still show the count, the limit is implied by the "Free User" status.
        save_limit_display = f"{len(bookmarked_videos)}"


        # Removed views_doc and view_count calculation as per request
        # views_doc = history_collection.find_one({'user_id': user_id})
        # view_count = len(views_doc['history']) if views_doc and 'history' in views_doc else 0
        
        ref_link = f"https://t.me/{config.BOT_USERNAME[1:]}?start=ref_{user_id}"
        
        await message.reply(
            f"👤 <b>Your Profile</b> ✨\n\n"
            f"<b>Status:</b> {user_status}\n"
            f"<b>Tokens:</b> {tokens_count}\n"
            f"<b>Saved Videos:</b> {save_limit_display}\n"
            f"<b>Referrals:</b> {referral_count}\n"
            f"<b>Referral Link:</b> <code>{html.escape(ref_link)}</code> 🔗",
            # Removed referral_keyboard as per request
            reply_markup=None # No inline keyboard for profile anymore
        )
        logger.info(f"User {user_id}: Profile sent successfully.")
    except Exception as e:
        logger.error(f"User {user_id} failed to send profile: {e}", exc_info=True)
        await handle_error(client, message, e)


@app.on_message(filters.regex("^🎞️ Get Video$") & filters.private)
async def get_video(client: Client, message: Message):
    """Handles the 'Get Video' button request."""
    user_id = message.from_user.id
    chat_id = message.chat.id
    logger.info(f"User {user_id} requested Get Video.")
    
    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    create_tracked_task(check_premium_status_and_notify(client, user_id))

    if await is_rate_limited(user_id):
        await handle_error(client, message, FloodWait(10))
        logger.warning(f"User {user_id} hit rate limit in get_video.")
        return
        
    if not user_has_token(user_id):
        logger.info(f"User {user_id} has no tokens, prompting earning options.")
        await send_token_earning_options(client, message)
        return
    
    message_id_to_edit_or_delete = message.id

    cats = get_categories()
    if not cats:
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

    temp_msg = await client.send_message(chat_id, "⏳ Please wait, almost done... ✨")
    
    sent_success, sent_message_or_error = await send_and_replace_message(
        client,
        chat_id,
        message_id_to_edit_or_delete=temp_msg.id,
        new_message_type="text",
        text_content="🎬 <b>Choose a Category:</b>",
        reply_markup=category_keyboard()
    )

    if not sent_success:
        await message.reply(sent_message_or_error)
        logger.error(f"User {user_id} failed to send category selection message: {sent_message_or_error}")

@app.on_callback_query(filters.regex(r"^cat_(.+)$"))
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

    if await is_rate_limited(user_id):
        await callback_query.answer("⚠️ Too many category changes. Wait 1 min. ⏳", show_alert=True)
        logger.warning(f"User {user_id} hit rate limit in select_category.")
        return
        
    current_active_tracked_message = active_video_message.get(user_id)
    if current_active_tracked_message and \
       current_active_tracked_message.get('message_id') == callback_query.message.id and \
       datetime.utcnow() - current_active_tracked_message.get('timestamp', datetime.min) > timedelta(minutes=config.MENU_EXPIRY_MINUTES):
        
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
        try:
            await client.delete_messages(chat_id, callback_query.message.id)
            clear_active_video_message(user_id) # Clear old message state if it was an old button
        except MessageIdInvalid:
            pass
        except Exception as e:
            logger.warning(f"Failed to delete outdated menu message for user {user_id}: {e}")
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
    if last_viewed_uuid:
        video = get_video_by_uuid(last_viewed_uuid)
        if not video:
            logger.warning(f"Last viewed video {last_viewed_uuid} for user {user_id} in category {category_name} not found. Falling back to first video.")
            users_collection.update_one(
                {'user_id': user_id},
                {'$unset': {f'last_viewed_per_category.{category_name}': ""}}
            )
    
    if not video:
        video = get_first_video_by_sequence_number(category_name) # Use sequence number for first video

    if not video:
        logger.warning(f"No videos found in category '{category_name}' for user {user_id}.")
        await callback_query.answer("No videos in this category. Try another! 😔", show_alert=True)
        await temp_msg.delete()
        await callback_query.message.edit_text(
            "No videos in this category. Try another! 😔",
            reply_markup=category_keyboard()
        )
        return
    
    # Get position for display
    video_to_display_with_pos, current_position, total_videos = get_video_and_position(
        video['uuid'], category_name, False, user_id
    )

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
        await callback_query.answer("❌ Failed to load video. Please try again. 😥", show_alert=True)
        clear_active_video_message(user_id)
        await temp_msg.delete()

@app.on_callback_query(filters.regex(r"^view_saved_cat_(.+)$"))
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

    if await is_rate_limited(user_id):
        await callback_query.answer("⚠️ Browse too quickly. Wait 1 min. ⏳", show_alert=True)
        logger.warning(f"User {user_id} hit rate limit in view_saved_category_callback.")
        return

    # Check for menu expiry
    current_active_tracked_message = active_video_message.get(user_id)
    if current_active_tracked_message and \
       current_active_tracked_message.get('message_id') == callback_query.message.id and \
       datetime.utcnow() - current_active_tracked_message.get('timestamp', datetime.min) > timedelta(minutes=config.MENU_EXPIRY_MINUTES):
        
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
    
    filtered_saved_videos.sort(key=lambda x: x.get('bookmarked_at', datetime.min))

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
    
    # Get position for display
    video_to_display_with_pos, current_position, total_videos = get_video_and_position(
        video_to_display['uuid'], selected_category, True, user_id
    )

    sent_success, sent_message_or_error = await send_and_replace_message(
        client,
        chat_id,
        message_id_to_edit_or_delete=callback_query.message.id,
        new_message_type="video",
        video_data=video_to_display,
        reply_markup=video_nav_keyboard(video_to_display['uuid'], selected_category, user_id, is_saved=True),
        force_new_message=False # Try to edit the existing message
    )

    if sent_success:
        save_history(user_id, video_to_display['uuid'], selected_category)
        await callback_query.answer()
        logger.info(f"User {user_id} viewed first saved video {video_to_display['uuid']} in category {selected_category}.")
    else:
        await callback_query.answer("❌ Failed to load video. Please try again. 😥", show_alert=True)
        clear_active_video_message(user_id)


@app.on_callback_query(filters.regex(r"^(next|prev)\|(.+)\|(.+)\|(\d+)$")) # Updated regex to capture is_saved flag
async def navigate_video(client: Client, callback_query: CallbackQuery):
    """Handles 'Next' and 'Previous' video navigation."""
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id
    
    # Parse callback data: action (next/prev), current_uuid, category, is_saved_flag
    parts = callback_query.data.split('|')
    if len(parts) != 4:
        logger.error(f"Invalid callback data for navigate_video: {callback_query.data}")
        await callback_query.answer("Invalid request. Please try again.", show_alert=True)
        return

    action, current_uuid, category_encoded, is_saved_flag_str = parts
    # Changed: Decode category name from callback data
    category = b64_to_str(category_encoded)
    is_saved = bool(int(is_saved_flag_str)) # Convert '0' or '1' to boolean
    
    logger.info(f"User {user_id} requested {action} video in category '{category}', is_saved: {is_saved}.")
    
    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    create_tracked_task(check_premium_status_and_notify(client, user_id))

    try:
        if await is_rate_limited(user_id):
            await callback_query.answer("⚠️ Browse too quickly. Wait 1 min. ⏳", show_alert=True)
            logger.warning(f"User {user_id} hit rate limit in navigate_video.")
            return

        current_active_tracked_message = active_video_message.get(user_id)
        if current_active_tracked_message and \
           current_active_tracked_message.get('message_id') == callback_query.message.id and \
           datetime.utcnow() - current_active_tracked_message.get('timestamp', datetime.min) > timedelta(minutes=config.MENU_EXPIRY_MINUTES):
            
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

        video = None
        if is_saved:
            if action == "next":
                video = get_next_saved_video_chronological(user_id, current_uuid, category)
            elif action == "prev":
                video = get_previous_saved_video_chronological(user_id, current_uuid, category)

            if not video:
                await callback_query.answer("No more saved videos in this category. Looping to the beginning/end. ❤️", show_alert=True)
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

            if not video: # This case should ideally not be hit with looping logic
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

@app.on_callback_query(filters.regex(r"^change_cat$"))
async def change_category(client: Client, callback_query: CallbackQuery):
    """Handles 'Change Category' request."""
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id
    logger.info(f"User {user_id} requested to change category.")
    
    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    create_tracked_task(check_premium_status_and_notify(client, user_id))

    try:
        current_active_tracked_message = active_video_message.get(user_id)
        if current_active_tracked_message and \
           current_active_tracked_message.get('message_id') == callback_query.message.id and \
           datetime.utcnow() - current_active_tracked_message.get('timestamp', datetime.min) > timedelta(minutes=config.MENU_EXPIRY_MINUTES):
            
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

@app.on_message(filters.regex("^👤 Profile$") & filters.private)
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

@app.on_message(filters.regex("^🔗 Refer & Earn$") & filters.private)
async def refer_btn(client: Client, message: Message):
    """Handles 'Refer & Earn' button click."""
    user_id = message.from_user.id
    logger.info(f"User {user_id} clicked Refer & Earn button.")
    
    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    create_tracked_task(check_premium_status_and_notify(client, user_id))

    try:
        if await is_rate_limited(user_id):
            await handle_error(client, message, FloodWait(10))
            logger.warning(f"User {user_id} hit rate limit in refer_btn.")
            return

        ref_link = f"https://t.me/{config.BOT_USERNAME[1:]}?start=ref_{user_id}"
        await message.reply(f"🔗 <b>Share & Earn!</b>\nWhen a new user joins through this link, you'll receive {config.REFERRAL_BONUS} token. It's a win-win! 🎉\n\n<code>{html.escape(ref_link)}</code>\n\nShare this link to new users only to get the token! 📢", reply_markup=None) # Removed inline button
        logger.info(f"User {user_id}: Referral link sent successfully.")
    except Exception as e:
        logger.error(f"User {user_id} failed to send referral link: {e}", exc_info=True)
        await handle_error(client, message, e)

@app.on_callback_query(filters.regex(r"^refer_and_earn_inline$"))
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


@app.on_message(filters.regex("^💰 Buy Token$") & filters.private)
async def buy_token_btn(client: Client, message: Message):
    """Handles 'Buy Token' button click."""
    user_id = message.from_user.id
    logger.info(f"User {user_id} clicked Buy Token button.")
    
    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

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

    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    temp_msg = None
    try:
        create_tracked_task(check_premium_status_and_notify(client, user_id))

        if await is_rate_limited(user_id):
            await message.reply_text("⚠️ You're refreshing too quickly. Please wait a minute and try again. ⏳")
            logger.warning(f"User {user_id} hit rate limit in refresh_token_btn.")
            return

        temp_msg = await message.reply("⏳ Please wait while we prepare your token... ✨")
        logger.info(f"User {user_id}: 'Please wait...' message sent. Checking for existing token.")

        if is_premium_user(user_id):
            if temp_msg:
                await temp_msg.delete()
            await message.reply("💡 You already have active premium access. No need to refresh yet! Enjoy the videos! 🥳")
            logger.info(f"User {user_id} attempted token refresh but already has valid premium access. Exiting.")
            return

        logger.info(f"User {user_id}: User does not have valid premium access. Generating ad_code and attempting to shorten URL.")
        ad_code = str_to_b64(f"{user_id}:{get_current_time() + config.REFRESH_TOKEN_LINK_EXPIRY_SECONDS}")
        long_url = f"https://t.me/{config.BOT_USERNAME[1:]}?start=token_{ad_code}"
        
        ad_url = await get_shortener_config_and_shorten_url(long_url) 
        logger.info(f"User {user_id}: get_shortener_config_and_shorten_url call completed. Result: {ad_url}")
        
        if temp_msg:
            await temp_msg.delete()

        disable_preview = False
        if ad_url == long_url:
            logger.warning(f"User {user_id} URL shortening failed for refresh_token_btn. Using long URL: {ad_url}")
            disable_preview = True

        user_mention_safe = html.escape(message.from_user.first_name) if message.from_user.first_name else "there"
        
        # Calculate configured_hours dynamically
        configured_hours = config.TOKEN_EXPIRY // 3600 # Convert seconds to hours

        await message.reply_text(
            f"💡 <b>Information</b>\nHere's how to get your token! 🚀\n\n"
            f"Hey 💕 <b>{user_mention_safe}</b>,\n\nYour Ads token is expired. Please refresh your token by clicking the button below and try again. 👇\n\n"
            f"<b>Token Timeout:</b> {configured_hours} hours ⏰\n\n"
            f"<b>What is a token?</b>\nThis is an ads token. If you pass 1 ad, you can use the bot for {configured_hours} hours after passing the ad. It's that simple! ✨\n\n"
            f"<tg-spoiler>‼️ APPLE/IPHONE USERS: Copy the token link and open it in a Chrome browser for best experience. 🍎</tg-spoiler>",
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
    
    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    try:
        create_tracked_task(check_premium_status_and_notify(client, user_id))

        if await is_rate_limited(user_id):
            await message.reply_text("⚠️ You're requesting token options too quickly. Please wait a minute and try again. ⏳")
            logger.warning(f"User {user_id} hit rate limit in send_token_earning_options.")
            return

        ad_code = str_to_b64(f"{user_id}:{get_current_time() + config.REFRESH_TOKEN_LINK_EXPIRY_SECONDS}")
        long_url = f"https://t.me/{config.BOT_USERNAME[1:]}?start=token_{ad_code}"
        
        ad_url = await get_shortener_config_and_shorten_url(long_url) 
        
        disable_preview = False
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

    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    create_tracked_task(check_premium_status_and_notify(client, user_id))

    try:
        if not is_premium_user(user_id):
            logger.info(f"Non-premium user {user_id} attempted to download video {video_uuid}.")
            reply_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 Buy Token", url=config.BUY_BOT_URL)] 
            ])
            await callback_query.answer("⚠️ Premium feature only! ✨", show_alert=True)
            await client.send_message(
                chat_id,
                f"✨ Unlock Exclusive Downloads! ✨\n\n"
                f"Ready to download your favorite content? 🤩 Get blazing-fast, direct downloads with our Premium Access!\n\n"
                f"💎 Try a 7-day trial for just ₹{config.PREMIUM_TRIAL_PRICE_INR} or go all-in with 1-month premium access for ₹{config.PREMIUM_MONTH_PRICE_INR}! 🚀\n\n"
                f"Tap below to elevate your experience! 👇",
                reply_markup=reply_markup
            )
            return

        video = get_video_by_uuid(video_uuid)
        if not video:
            logger.warning(f"Premium user {user_id} requested download for non-existent video {video_uuid}.")
            await callback_query.answer("Video not found. It might have been removed. 😔", show_alert=True)
            return

        await client.send_video(
            chat_id,
            video=video['file_id'],
            caption=None,
            protect_content=False
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
        bookmarked_videos.append({'uuid': video_uuid, 'bookmarked_at': datetime.utcnow(), 'category': video_data.get('category')})
        
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


@app.on_callback_query(filters.regex(r"^remove_saved_(.+)$"))
async def remove_saved_video_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    # Split by '_' and then take the part after 'remove_saved_'
    video_uuid = callback_query.data.split('_', 2)[2] 
    chat_id = callback_query.message.chat.id
    logger.info(f"User {user_id} requested to remove saved video {video_uuid}.")

    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    create_tracked_task(check_premium_status_and_notify(client, user_id))

    try:
        current_active_tracked_message = active_video_message.get(user_id)
        if current_active_tracked_message and \
           current_active_tracked_message.get('message_id') == callback_query.message.id and \
           datetime.utcnow() - current_active_tracked_message.get('timestamp', datetime.min) > timedelta(minutes=config.MENU_EXPIRY_MINUTES):
            
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
                remaining_in_same_category.sort(key=lambda x: x.get('bookmarked_at', datetime.min))

                if remaining_in_same_category:
                    # Show the next video in the same category (chronologically by bookmark date)
                    # For simplicity, let's just show the first one in that category after removal
                    next_video_uuid = remaining_in_same_category[0]['uuid']
                    next_video = get_video_by_uuid(next_video_uuid)
                    
                    if next_video:
                        # Get position for display
                        video_to_display_with_pos, current_position, total_videos = get_video_and_position(
                            next_video['uuid'], current_category_of_removed_video, True, user_id
                        )
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
                        await client.send_message(chat_id, "The next saved video was not found. It may have been removed. 😔")
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
@app.on_callback_query(filters.regex(r"^view_saved_video_(.+)$"))
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
       datetime.utcnow() - current_active_tracked_message.get('timestamp', datetime.min) > timedelta(minutes=config.MENU_EXPIRY_MINUTES):
        
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

    if not user_has_token(user_id):
        await callback_query.answer("You need a token to watch this video. Please get a token first! 🧐", show_alert=True)
        await send_token_earning_options(client, callback_query.message)
        return

    video = get_video_by_uuid(video_uuid)
    if not video:
        await callback_query.answer("Video not found or has been removed. 😔", show_alert=True)
        users_collection.update_one(
            {'user_id': user_id},
            {'$pull': {'bookmarked_videos': {'uuid': video_uuid}}}
        )
        return
    
    # Get position for display
    video_to_display_with_pos, current_position, total_videos = get_video_and_position(
        video['uuid'], video['category'], True, user_id
    )

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
        save_history(user_id, video['uuid'], video['category'])
        await callback_query.answer()
        logger.info(f"User {user_id} viewed saved video {video_uuid}.")
    else:
        await callback_query.answer("❌ Failed to load saved video. Please try again.😥", show_alert=True)
        logger.error(f"User {user_id} failed to load saved video {video_uuid}: {sent_message_or_error}")


@app.on_callback_query(filters.regex(r"^unavailable_(.+)$"))
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

@app.on_callback_query(filters.regex(r"^confirm_clear_all_saved$"))
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

@app.on_callback_query(filters.regex(r"^clear_all_saved_videos$"))
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

@app.on_callback_query(filters.regex(r"^cancel_clear_saved$"))
async def cancel_clear_saved_callback(client: Client, callback_query: CallbackQuery):
    """Cancels clearing all saved videos."""
    user_id = callback_query.from_user.id
    logger.info(f"User {user_id} cancelled clearing all saved videos.")
    
    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    await callback_query.message.edit_text("Operation cancelled. Your saved videos are safe! ✅")
    await callback_query.answer("Operation cancelled.")

# --- Admin Commands ---
@app.on_message(filters.command("broadcast") & filters.private & filters.create(lambda _, __, msg: is_admin(msg.from_user.id)) & filters.reply)
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

@app.on_message(filters.command("addcategory") & filters.private & filters.create(lambda _, __, msg: is_admin(msg.from_user.id)))
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

@app.on_message(filters.command("deletecategory") & filters.private & filters.create(lambda _, __, msg: is_admin(msg.from_user.id)))
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

@app.on_callback_query(filters.regex(r"^confirmdelcat_(.+)$"))
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

@app.on_message(filters.command("addtoken") & filters.private & filters.create(lambda _, __, msg: is_admin(msg.from_user.id)))
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
        
        add_token_info = add_token(target_user_id, duration_seconds=duration_days * 86400, is_admin_granted=True)
        
        if not add_token_info:
            await message.reply("❌ Failed to grant premium access. Please try again. 🐛")
            return

        expiry_date = add_token_info['expires_at']
        logger.info(f"Admin {user_id} granted {duration_days} days of premium access to user {target_user_id}. Expires: {expiry_date}")
        await message.reply(f"✅ Granted <b>{duration_days}</b> days of premium access to user <b>{target_user_id}</b>. New expiry: {expiry_date.strftime('%Y-%m-%d %H:%M:%S UTC')}. 🎉")
        
        try:
            await client.send_message(target_user_id, f"🎉 <b>Congratulations!</b> You have been granted <b>{duration_days}</b> days of premium access by an admin! Your premium access now expires on <b>{expiry_date.strftime('%Y-%m-%d %H:%M:%S UTC')}</b>. Enjoy exclusive features! 💎")
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

@app.on_message(filters.command("batchadd") & filters.private & filters.create(lambda _, __, msg: is_admin(msg.from_user.id)))
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

        # Initialize batch_add_state for the user
        batch_add_state[user_id] = {
            'batch_mode': False,
            'current_category': None,
            'count': 0,
            'next_sequence': 1 # Initialize next_sequence here, will be updated on category selection
        }
        
        buttons = []
        for category in categories:
            # Changed: Encode category name for callback data
            buttons.append([InlineKeyboardButton(f"🗂️ {html.escape(category)}", callback_data=f"batchselcat_{str_to_b64(category)}")])

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
    # Changed: Decode category name from callback data
    category_name = b64_to_str(callback_query.data[12:]) 
    logger.info(f"Admin {user_id} selected category for batch adding: {category_name}.")
    try:
        if not is_admin(user_id):
            await callback_query.answer("❌ Not authorized. 🚫", show_alert=True)
            logger.warning(f"Non-admin user {user_id} attempted to select batch category.")
            return

        if user_id not in batch_add_state:
            await callback_query.answer("❌ Error: Batch mode session expired or not active. Please use /batchadd again. 🚫", show_alert=True)
            logger.warning(f"Admin {user_id} tried to select category but batch mode not initialized.")
            return

        if category_name not in get_categories():
            await callback_query.answer(f"❌ Invalid category '<b>{html.escape(category_name)}</b>'. 🧐", show_alert=True)
            await callback_query.message.edit_text(
                "Category not found. Please try again! 🧐",
                # Changed: Encode category name for callback data in error case
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"🗂️ {html.escape(cat)}", callback_data=f"batchselcat_{str_to_b64(cat)}")] for cat in get_categories()])
            )
            logger.warning(f"Admin {user_id} tried to set invalid category for batch: '{category_name}'.")
            return

        # Find the current highest sequence number for the selected category
        last_video_in_category = media_collection.find_one(
            {'category': category_name},
            sort=[('sequence_number', DESCENDING)]
        )
        next_sequence_for_batch = 1
        if last_video_in_category and 'sequence_number' in last_video_in_category:
            next_sequence_for_batch = last_video_in_category['sequence_number'] + 1
        
        batch_add_state[user_id]['batch_mode'] = True
        batch_add_state[user_id]['current_category'] = category_name
        batch_add_state[user_id]['count'] = 0
        batch_add_state[user_id]['next_sequence'] = next_sequence_for_batch # Set the starting sequence for this batch
        
        logger.info(f"Admin {user_id} starting batch add for category '{category_name}'. Next sequence will start from: {next_sequence_for_batch}")

        await callback_query.message.edit_text(
            f"✅ You are now in batch add mode for category: <b>{html.escape(category_name)}</b>! 🎉\n"
            f"The next video will be sequence <b>{next_sequence_for_batch}</b>.\n"
            "Send me videos to add. Type /done when finished. ✅\n"
            "You can use /category to change the current batch category without exiting batch mode. 🔄"
        )
        await callback_query.answer(f"Category set to '{html.escape(category_name)}'")
        logger.info(f"Admin {user_id} successfully started batch add mode for category '{category_name}'.")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to set batch category in callback: {e}", exc_info=True)
        await callback_query.answer("❌ An error occurred while setting category. Please try again. 🐛", show_alert=True)

@app.on_message(filters.command("done") & filters.private & filters.create(lambda _, __, msg: is_admin(msg.from_user.id)))
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

@app.on_message(filters.video & filters.private & filters.create(lambda _, __, msg: is_admin(msg.from_user.id)))
async def handle_video_batch_add_or_delete(client: Client, message: Message):
    """
    Handles incoming video messages for either batch adding mode or delete video mode.
    Prioritizes delete video mode if active.
    """
    user_id = message.from_user.id
    
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
            category_of_deleted_video = video_to_delete.get('category')
            sequence_number_of_deleted_video = video_to_delete.get('sequence_number')

            # Use the new centralized deletion function
            success = await delete_broken_video_from_db_and_channel(
                client,
                video_uuid,
                category_of_deleted_video,
                sequence_number_of_deleted_video,
                message_id_in_channel
            )

            if success:
                await message.reply_text(f"✅ Video (UUID: <code>{video_uuid}</code>) and its data have been deleted from the database. Attempted to delete from channel. 🗑️")
            else:
                await message.reply_text(f"❌ Failed to delete video (UUID: <code>{video_uuid}</code>). Check logs for details. 🐛")

        except Exception as e:
            logger.error(f"Admin {user_id} error deleting video: {e}", exc_info=True)
            await message.reply("❌ An error occurred while deleting the video. Please try again. 🐛")
        finally:
            del admin_delete_video_state[user_id]
        return

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
        custom_caption = message.caption

        if media_collection.find_one({"file_unique_id": file_unique_id}):
            logger.warning(f"Admin {user_id} attempted to add duplicate video: {file_unique_id}.")
            await message.reply_text("⚠️ This video has already been added. Skipping.⏩")
            return

        video_uuid = str(uuid.uuid4())
        
        # Use and increment the sequence number from batch_add_state
        next_sequence_number = batch_add_state[user_id]['next_sequence']
        batch_add_state[user_id]['next_sequence'] += 1 # Increment for the next video
        
        logger.info(f"Using sequence_number for category '{category}'. Next sequence will be: {next_sequence_number} (from batch state)")

        channel_caption = custom_caption if custom_caption else f"Category: {html.escape(category)}\nSize: {format_size(file_size)}\nUUID: {video_uuid}"

        try:
            forwarded_message = await client.send_video(
                chat_id=config.VIDEO_CHANNEL_ID,
                video=file_id,
                caption=channel_caption,
                protect_content=False
            )
            message_id_in_channel = forwarded_message.id
        except FloodWait as fw:
            logger.warning(f"FloodWait encountered when forwarding video to channel: {fw.value}s. Retrying after delay.")
            await asyncio.sleep(fw.value + 1)
            try:
                forwarded_message = await client.send_video(
                    chat_id=config.VIDEO_CHANNEL_ID,
                    video=file_id,
                    caption=channel_caption,
                    protect_content=False
                )
                message_id_in_channel = forwarded_message.id
            except Exception as forward_e_retry:
                logger.error(f"Failed to forward video {file_unique_id} to channel after FloodWait: {forward_e_retry}", exc_info=True)
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
            "timestamp": get_current_time(), # Keep timestamp for general info, but sequence_number for order
            "sequence_number": next_sequence_number, # NEW: Store sequence number
            "message_id": message_id_in_channel,
            "banned": False,
            "custom_caption": custom_caption
        }
        media_collection.insert_one(video_data)
        batch_add_state[user_id]['count'] = batch_add_state[user_id].get('count', 0) + 1
        logger.info(f"Video {video_uuid} (file ID: {file_id}) added to category {category} by admin {user_id} with sequence_number {next_sequence_number}. Message ID in channel: {message_id_in_channel}")
        
        admin_reply_caption = f"✅ File <code>{html.escape(message.video.file_name or 'unnamed_video')}</code> Added to <b>{html.escape(category)}</b>! 🎉\n"
        if custom_caption:
            admin_reply_caption += f"📝 Custom Caption: <i>{html.escape(custom_caption)}</i>\n"
        admin_reply_caption += (
            f"📁 Category: {html.escape(category)}\n"
            f"📊 Size: {format_size(file_size)}\n"
            f"🔢 Sequence: {next_sequence_number}\n" # Display sequence number
            f"Videos added in this batch: <b>{batch_add_state[user_id]['count']}</b> 🔢"
        )
        await message.reply_text(admin_reply_caption)

    except Exception as e:
        logger.error(f"Admin {user_id} error adding video: {e}", exc_info=True)
        await message.reply("❌ Failed to add video. Please try again. 🐛")

@app.on_message(filters.command("category") & filters.private & filters.create(lambda _, __, msg: is_admin(msg.from_user.id)))
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
        batch_add_state[user_id]['count'] = 0 # Reset count for the new category in this batch session

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

@app.on_message(filters.command("stats") & filters.private & filters.create(lambda _, __, msg: is_admin(msg.from_user.id)))
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

# --- New Admin Commands ---

@app.on_message(filters.command("setshortener") & filters.private & filters.create(lambda _, __, msg: is_admin(msg.from_user.id)))
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

@app.on_message(filters.command("deletevideo") & filters.private & filters.create(lambda _, __, msg: is_admin(msg.from_user.id)))
async def deletevideo_cmd(client: Client, message: Message):
    """Admin command to initiate video deletion mode."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} initiated /deletevideo command.")
    admin_delete_video_state[user_id] = True
    await message.reply("Send the <b>video file from the database</b> to delete it. This must be the original video file, not a forwarded one. 🎥")

@app.on_message(filters.command("categoryrename") & filters.private & filters.create(lambda _, __, msg: is_admin(msg.from_user.id)))
async def categoryrename_cmd(client: Client, message: Message):
    """Admin command to initiate category renaming flow."""
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} initiated /categoryrename command.")
    admin_rename_category_state[user_id] = {'step': 'await_old_name'}
    await message.reply("Please send the <b>current name</b> of the category you want to rename. 📝")

# --- Owner Commands ---
@app.on_message(filters.command("addadmin") & filters.private & filters.create(lambda _, __, msg: is_owner(msg.from_user.id)))
async def addadmin_cmd(client: Client, message: Message):
    """Owner command to add a new admin."""
    user_id = message.from_user.id
    logger.info(f"Owner {user_id} initiated /addadmin command.")
    owner_addadmin_state[user_id] = True
    await message.reply("Please send the User ID and Username (format: <code>user_id|username</code>) to add as admin. 📝\n\n<b>Example:</b> <code>123456789|john_doe</code>")

@app.on_message(filters.command("removeadmin") & filters.private & filters.create(lambda _, __, msg: is_owner(msg.from_user.id)))
async def removeadmin_cmd(client: Client, message: Message):
    """Owner command to remove an admin."""
    user_id = message.from_user.id
    logger.info(f"Owner {user_id} initiated /removeadmin command.")
    
    try:
        admins = list(admins_collection.find({}))
        if not admins:
            await message.reply("😔 No dynamic admins to remove. 🚫")
            return

        buttons = []
        for admin in admins:
            buttons.append([InlineKeyboardButton(f"❌ @{html.escape(admin['username'])} ({admin['user_id']})", callback_data=f"remove_admin_confirm_{admin['user_id']}")])

        owner_removeadmin_state[user_id] = True
        await message.reply(
            "Select an admin to remove: 👇\n\n"
            "⚠️ This action cannot be undone.",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        logger.info(f"Owner {user_id}: Remove admin options sent.")
    except Exception as e:
        logger.error(f"Owner {user_id} failed to send remove admin options: {e}", exc_info=True)
        await message.reply("❌ An error occurred while preparing remove admin options. Please try again. 🐛")

@app.on_callback_query(filters.regex(r"^remove_admin_confirm_(.+)$"))
async def remove_admin_confirm_callback(client: Client, callback_query: CallbackQuery):
    """Handles confirmation for removing an admin."""
    owner_id = callback_query.from_user.id
    admin_id_to_remove = int(callback_query.data.split('_')[-1])
    logger.info(f"Owner {owner_id} confirmed removal of admin {admin_id_to_remove}.")

    try:
        if not is_owner(owner_id):
            await callback_query.answer("❌ Not authorized. Only the owner can remove admins. 🚫", show_alert=True)
            logger.warning(f"Non-owner user {owner_id} attempted to remove admin.")
            return

        admin_to_remove_doc = admins_collection.find_one({'user_id': admin_id_to_remove})
        if not admin_to_remove_doc:
            await callback_query.answer("Admin not found in the database. 🧐", show_alert=True)
            await callback_query.message.edit_text("Admin not found or already removed. 🧐")
            return

        # Prevent owner from removing themselves
        if admin_id_to_remove == config.OWNER_ID:
            await callback_query.answer("❌ You cannot remove yourself (the owner) as an admin. 🚫", show_alert=True)
            return

        result = admins_collection.delete_one({'user_id': admin_id_to_remove})
        
        if result.deleted_count > 0:
            username = admin_to_remove_doc.get('username', 'N/A')
            await callback_query.message.edit_text(f"❌ Admin @{html.escape(username)} (<code>{admin_id_to_remove}</code>) removed successfully. 🗑️")
            await callback_query.answer(f"Admin @{username} removed.")
            logger.info(f"Owner {owner_id} successfully removed admin {admin_id_to_remove} (@{username}).")
        else:
            await callback_query.answer("Failed to remove admin. Admin not found or already removed. 🐛", show_alert=True)
            await callback_query.message.edit_text("Failed to remove admin. Admin not found or already removed. 🐛")
    except Exception as e:
        logger.error(f"Owner {owner_id} failed to remove admin {admin_id_to_remove}: {e}", exc_info=True)
        await callback_query.answer("❌ An error occurred during admin removal. Please try again. 🐛", show_alert=True)
    finally:
        del owner_removeadmin_state[owner_id] # Clear state after action


@app.on_message(filters.text & filters.private & filters.create(lambda _, __, msg: is_owner(msg.from_user.id)))
async def handle_owner_text_input(client: Client, message: Message):
    """Handles owner's text input for multi-step commands like addadmin."""
    user_id = message.from_user.id

    if user_id in owner_addadmin_state and owner_addadmin_state[user_id]:
        input_text = message.text.strip()
        parts = input_text.split('|', 1) # Split only on the first '|'

        if len(parts) != 2:
            await message.reply("❌ Invalid format. Please use: <code>user_id|username</code>")
            logger.warning(f"Owner {user_id} provided invalid format for addadmin: {input_text}")
            return

        try:
            target_user_id = int(parts[0].strip())
            target_username = parts[1].strip().replace('@', '') # Remove @ if present
            
            if not target_username:
                await message.reply("❌ Username cannot be empty. Please provide a valid username.")
                return

            if admins_collection.find_one({'user_id': target_user_id}):
                await message.reply(f"⚠️ User ID <code>{target_user_id}</code> is already an admin. ✅")
                logger.warning(f"Owner {user_id} attempted to add existing admin: {target_user_id}")
                del owner_addadmin_state[user_id]
                return

            admins_collection.insert_one({
                'user_id': target_user_id,
                'username': target_username,
                'added_by': user_id,
                'added_at': datetime.utcnow()
            })
            await message.reply(f"✅ Admin @{html.escape(target_username)} (<code>{target_user_id}</code>) added successfully! 🎉")
            logger.info(f"Owner {user_id} successfully added admin {target_user_id} (@{target_username}).")
            try:
                await client.send_message(target_user_id, "🎉 Congratulations! You have been added as an admin of the bot! You can now use admin commands. 🚀")
            except (UserIsBlocked, ChatInvalid):
                logger.warning(f"Could not notify new admin {target_user_id}; user blocked or chat invalid.")
            except Exception as notify_e:
                logger.error(f"Failed to notify new admin {target_user_id}: {notify_e}")

        except ValueError:
            await message.reply("❌ Invalid User ID. Please ensure it's a number. 🔢")
            logger.warning(f"Owner {user_id} provided non-integer user ID for addadmin: {parts[0]}")
        except Exception as e:
            logger.error(f"Owner {user_id} failed to add admin: {e}", exc_info=True)
            await message.reply("❌ An error occurred while adding admin. Please try again. 🐛")
        finally:
            del owner_addadmin_state[user_id] # Clear state after processing

    elif user_id in admin_shortener_setup_state and admin_shortener_setup_state[user_id].get('step') == 'await_template_url':
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
            del admin_shortener_setup_state[user_id]
            await message.reply("✅ Shortener API Template URL Set Successfully!")
            logger.info(f"Admin {user_id} successfully set shortener template URL: {template_url}")
        except Exception as e:
            logger.error(f"Error saving shortener template URL for admin {user_id}: {e}", exc_info=True)
            await message.reply("❌ Failed to save shortener configuration. Please try again. 🐛")
            del admin_shortener_setup_state[user_id]
        return

    elif user_id in admin_rename_category_state:
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
    
    logger.debug(f"Owner {user_id} sent text message '{message.text}' not part of any active multi-step command. Ignoring.")


# --- Auto-Delete & Protect Content Settings ---
@app.on_message(filters.command('toggle_auto_delete') & filters.private & filters.create(lambda _, __, msg: is_admin(msg.from_user.id)))
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

@app.on_message(filters.command('toggle_protect') & filters.private & filters.create(lambda _, __, msg: is_admin(msg.from_user.id)))
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
            now = datetime.utcnow()
            
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
                    bookmarked_videos.sort(key=lambda x: x.get('bookmarked_at', datetime.min), reverse=True)
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
        now = datetime.utcnow()
        expired_threshold = now - timedelta(minutes=config.MENU_EXPIRY_MINUTES)
        
        users_to_clear = []
        for user_id, menu_info in list(active_video_message.items()):
            if menu_info.get('timestamp') and menu_info['timestamp'] < expired_threshold:
                chat_id = menu_info['chat_id']
                message_id = menu_info['message_id']
                
                logger.info(f"Attempting to delete expired menu for user {user_id} (msg_id: {message_id}, chat_id: {chat_id}).")
                try:
                    await app.delete_messages(chat_id, message_id)
                    logger.info(f"Successfully deleted expired menu message {message_id} for user {user_id}.")
                    await app.send_message(
                        chat_id,
                        "Your menu has expired due to inactivity. Please click '🎞️ Get Video' to get a new one. ⏰"
                    )
                except MessageIdInvalid:
                    logger.info(f"Expired menu message {message_id} for user {user_id} already deleted or invalid.")
                    await app.send_message(
                        chat_id,
                        "Your menu has expired due0 to inactivity. Please click '🎞️ Get Video' to get a new one. ⏰"
                    )
                except Exception as e:
                    logger.error(f"Failed to delete expired menu message {message_id} for user {user_id}: {e}", exc_info=True)
                    try:
                        await app.send_message(
                            chat_id,
                            "Your menu has expired due to inactivity. Please click '🎞️ Get Video' to get a new one. ⏰"
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

async def cleanup_used_refresh_tokens():
    """Periodically cleans up old used refresh token entries."""
    while True:
        try:
            now = datetime.utcnow()
            delete_threshold = now - timedelta(seconds=config.REFRESH_TOKEN_LINK_EXPIRY_SECONDS * 2)
            result = refresh_tokens_used_collection.delete_many({'used_at': {'$lt': delete_threshold}})
            logger.info(f"Cleaned up {result.deleted_count} old used refresh token entries. (Used refresh tokens are kept for {config.REFRESH_TOKEN_LINK_EXPIRY_SECONDS * 2} seconds after use to prevent reuse.)")
        except asyncio.CancelledError:
            logger.info("cleanup_used_refresh_tokens task cancelled gracefully.")
            break
        except Exception as e:
            logger.error(f"Error in cleanup_used_refresh_tokens task: {e}", exc_info=True)
        
        await asyncio.sleep(config.REFRESH_TOKEN_LINK_EXPIRY_SECONDS)

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
        
        await asyncio.sleep(6 * 3600)

async def health_check():
    print("Session file exists:", os.path.exists("./spicynyraa.session"))
    try:
        me = await app.get_me()
        print(f"Bot username: {me.username}")
        member = await app.get_chat_member(config.VIDEO_CHANNEL_ID, me.id)
        print(f"Bot status in channel: {member.status}")
        msg = await app.get_messages(config.VIDEO_CHANNEL_ID, 1)
        print("Fetched message:", msg)
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
    
    await app.start()
    await health_check()
    logger.info("Bot has connected to Telegram.")

    create_tracked_task(cleanup_expired_data())
    create_tracked_task(verify_and_cleanup_media())
    create_tracked_task(cleanup_expired_menus())
    create_tracked_task(cleanup_used_refresh_tokens())

    logger.info("Background tasks initiated. Bot is now fully operational.")

    await asyncio.Event().wait()


if __name__ == "__main__":
    logger.info("Script started. Entering main execution block.")
    try:
        app.run(main_bot_logic())
    except KeyboardInterrupt:
        logger.info("Bot stopped by KeyboardInterrupt (Ctrl+C). Shutting down...")
    except Exception as e:
        logger.critical(f"An unhandled error occurred during bot startup or main execution: {e}", exc_info=True)
    finally:
        logger.info("Application exiting.")
