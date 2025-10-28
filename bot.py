import os
import asyncio
import uuid
import base64
import logging
from datetime import datetime, timedelta
from pyrogram import Client, filters
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, Message, InputMediaVideo, CallbackQuery, WebAppInfo
)
from pyrogram.errors import UserIsBlocked, ChatInvalid, MessageIdInvalid, FloodWait, PeerIdInvalid, RPCError, FileIdInvalid, FileReferenceExpired, ChatAdminRequired
from pyrogram.enums import ChatMemberStatus
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
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import hmac
import hashlib
from urllib.parse import unquote, parse_qs
import json
from pydantic import BaseModel


# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Configuration #demo ---
class BotConfig:
    BOT_TOKEN = '8336714943:AAEDF5NRMs4MKIlu__ZoEi8VVfz0xwCIJFA'
    API_ID = 29800015
    API_HASH = 'c8f37108be31ab9ea2818bfe533fbb6f'
    BOT_USERNAME = '@SpicyNyraa_bot'
    MONGO_URI = 'mongodb+srv://Pyasipriya:00pEcao9sYhNC5VQ@cluster0.2dfenf7.mongodb.net/spicybot?retryWrites=true&w=majority&appName=Cluster0'
    MONGO_DB_NAME = 'spicybot'
    BUY_BOT_URL = 'https://t.me/SpicyNyraaSupport_bot'
    OWNER_ID = 6612030110
    TUTORIAL_LINK_2 = 'https://t.me/urlshortenertutorial'
    TOKEN_EXPIRY = 86400
    NEW_USER_TOKENS = 2
    REFERRAL_BONUS = 1
    REFRESH_BONUS = 1
    PREMIUM_TRIAL_PRICE_INR = 69
    PREMIUM_MONTH_PRICE_INR = 199
    FREE_USER_SAVE_LIMIT = 100
    MENU_EXPIRY_MINUTES = 30
    REFRESH_TOKEN_LINK_EXPIRY_SECONDS = 900
    # --- New Feature Configuration ---
    FREE_VIDEOS_LIMIT = 20
    FREE_BATCHES_LIMIT = 1  # Number of free batches a user can watch per reset period
    FREE_LIMIT_RESET_HOURS = 24
    TOKEN_ACCESS_HOURS = 24
    # --- Mini App Configuration ---
    MINI_APP_URL = "ab-tu-dekh-beta-li3u.vercel.app"

try:
    config = BotConfig()
    if not all([config.BOT_TOKEN, config.API_ID, config.API_HASH, config.MONGO_URI, config.BOT_USERNAME]):
        raise ValueError("One or more essential configuration variables are not set. Please check all config variables.")
except Exception as e:
    raise RuntimeError(f"Failed to load bot configuration: {e}")

# --- Batch Add Constants ---
BATCH_UPLOAD_LIMIT = 20
BATCH_COOLDOWN_SECONDS = 60

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
video_batches_collection = db['video_batches']
force_sub_channels_collection = db['force_sub_channels']
data_channel_collection = db['data_channel']


# --- NEW: Async MongoDB Client for FastAPI ---
async_client = AsyncIOMotorClient(config.MONGO_URI)
async_db = async_client[config.MONGO_DB_NAME]
async_users_collection = async_db['users']
async_media_collection = async_db['media']
async_categories_collection = async_db['categories']
async_tokens_collection = async_db['tokens']


# Create indexes
users_collection.create_index([("user_id", ASCENDING)], unique=True)
tokens_collection.create_index([("user_id", ASCENDING)], unique=True)
media_collection.create_index([("uuid", ASCENDING)], unique=True)
media_collection.create_index([("category", ASCENDING)])
media_collection.create_index([("file_unique_id", ASCENDING)], unique=True)
media_collection.create_index([("category", ASCENDING), ("sequence_number", ASCENDING)])
history_collection.create_index([("user_id", ASCENDING)], unique=True)
categories_collection.create_index([("name", ASCENDING)], unique=True)
refresh_tokens_used_collection.create_index([("ad_code", ASCENDING)], unique=True)
video_batches_collection.create_index([("batch_id", ASCENDING)], unique=True)
force_sub_channels_collection.create_index([("channel_id", ASCENDING)], unique=True)
data_channel_collection.create_index([("_id", ASCENDING)])


# --- Session Management with MongoDB ---
def get_session_string():
    session_doc = settings_collection.find_one({'_id': 'pyrogram_session'})
    return session_doc.get('session_string') if session_doc else None

def set_session_string(session_string):
    settings_collection.update_one(
        {'_id': 'pyrogram_session'},
        {'$set': {'session_string': session_string}},
        upsert=True
    )
    logger.info("Pyrogram session string has been saved to the database.")

# --- Pyrogram Client Initialization ---
logger.info("Initializing Pyrogram client...")
app = Client(
    name="spicynyraa_session",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN
)

# --- NEW: FastAPI App Initialization ---
fastapi_app = FastAPI()

origins = [
    config.MINI_APP_URL,
]

fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- GLOBAL SET FOR TRACKING ASYNC TASKS ---
active_tasks = set()

# --- Admin State Management ---
admin_shortener_setup_state = defaultdict(dict)
admin_delete_video_state = defaultdict(bool)
admin_rename_category_state = defaultdict(dict)
admin_batch_link_state = defaultdict(list)
owner_add_admin_state = defaultdict(dict)
admin_delete_user_state = defaultdict(dict)
batch_add_state = {}
admin_fsub_state = defaultdict(dict)
admin_data_channel_state = defaultdict(dict)


# --- Message Tracking and Immediate Deletion ---
active_video_message = {}

# --- Navigation Spam Control ---
processing_navigation_lock = set()

# --- Dynamic Admin Management ---
BOT_ADMINS = set()
DATA_CHANNEL_ID = None
FORCE_SUB_CHANNELS = []

async def load_admins_from_db():
    global BOT_ADMINS
    settings_doc = settings_collection.find_one({'_id': 'bot_settings'})
    db_admins = settings_doc.get('admins', []) if settings_doc else []
    BOT_ADMINS = set(db_admins)
    BOT_ADMINS.add(config.OWNER_ID)
    logger.info(f"Loaded admins from DB. Current admins: {BOT_ADMINS}")

async def load_data_channel_id():
    global DATA_CHANNEL_ID
    data_doc = data_channel_collection.find_one({'_id': 'data_channel'})
    if data_doc:
        DATA_CHANNEL_ID = data_doc.get('channel_id')
        logger.info(f"Loaded data channel ID: {DATA_CHANNEL_ID}")
    else:
        DATA_CHANNEL_ID = None
        logger.warning("No data channel ID found in DB.")

async def load_force_sub_channels():
    global FORCE_SUB_CHANNELS
    FORCE_SUB_CHANNELS = list(force_sub_channels_collection.find({}))
    logger.info(f"Loaded {len(FORCE_SUB_CHANNELS)} force subscribe channels.")

def is_admin(user_id: int) -> bool:
    return user_id in BOT_ADMINS

def is_owner(user_id: int) -> bool:
    return user_id == config.OWNER_ID

async def admin_filter(_, __, message: Message):
    return is_admin(message.from_user.id)

admin_only = filters.create(admin_filter)

async def owner_filter(_, __, message: Message):
    return is_owner(message.from_user.id)

owner_only = filters.create(owner_filter)


def create_tracked_task(coro):
    task = asyncio.create_task(coro)
    active_tasks.add(task)
    task.add_done_callback(active_tasks.discard)
    logger.debug(f"Task {task.get_name()} created and tracked. Total active tasks: {len(active_tasks)}")
    return task

# --- Force Subscribe Check ---
async def check_membership(client: Client, user_id: int) -> bool:
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
            return True
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
    logger.info(f"Sending force subscribe message to user {chat_id}.")

    if not FORCE_SUB_CHANNELS:
        await client.send_message(chat_id, "No force subscribe channels are configured. Please contact an admin.")
        return

    buttons = []
    for channel_info in FORCE_SUB_CHANNELS:
        buttons.append([InlineKeyboardButton(channel_info.get('name', f"Channel {channel_info['channel_id']}"), url=channel_info.get('link', 'https://t.me/telegram'))])
    buttons.append([InlineKeyboardButton("🔄 Try Again", callback_data="check_join_status")])

    reply_markup = InlineKeyboardMarkup(buttons)

    text_to_send = custom_text
    if not text_to_send:
        text_to_send = (
            "<b>⚠️ You must join our channels to use this bot.</b>\n\n"
            "Please join the channels below and then try again. Once you join, click the '🔄 Try Again' button or send /start again."
        )

    await client.send_message(
        chat_id,
        text_to_send,
        reply_markup=reply_markup
    )

# --- Utility Functions ---
def str_to_b64(string: str) -> str:
    return base64.urlsafe_b64encode(string.encode('utf-8')).decode('utf-8')

def b64_to_str(b64: str) -> str:
    try:
        return base64.urlsafe_b64decode(b64.encode('utf-8')).decode('utf-8')
    except Exception as e:
        logger.error(f"Failed to decode base64 string: {e}")
        return ""

def get_current_time() -> int:
    return int(datetime.utcnow().timestamp())

async def get_shortener_config_and_shorten_url(long_url: str) -> str:
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
    now = datetime.utcnow()
    doc = tokens_collection.find_one({'user_id': user_id})
    if not doc or 'tokens' not in doc:
        return False

    for token in doc['tokens']:
        if token.get('is_admin_granted', False) and token.get('expires_at') and token['expires_at'] > now:
            return True
    return False

def user_has_token(user_id: int) -> bool:
    now = datetime.utcnow()
    doc = tokens_collection.find_one({'user_id': user_id})
    if not doc or 'tokens' not in doc:
        return False

    for token in doc['tokens']:
        if token.get('expires_at') and token['expires_at'] > now:
            return True
    return False

# --- Free Usage Limit Management ---
async def send_limit_reached_message(client: Client, chat_id: int):
    user_id = chat_id
    ad_code = str_to_b64(f"{user_id}:{get_current_time()}")
    long_url = f"https://t.me/{config.BOT_USERNAME[1:]}?start=token_{ad_code}"
    ad_url = await get_shortener_config_and_shorten_url(long_url)

    text = (
        "You've reached the end of your free preview for today... 😉\n\n"
        "The full, uninterrupted stream is waiting for you. Get your <b>24-Hour Unlimited Access Pass</b> now."
    )
    reply_markup = generate_token_earning_keyboard(ad_url)
    await client.send_message(chat_id, text, reply_markup=reply_markup)

async def check_and_update_free_usage(user_id: int) -> bool:
    if is_premium_user(user_id) or user_has_token(user_id):
        return True

    now = datetime.utcnow()
    user_doc = users_collection.find_one({'user_id': user_id})
    if not user_doc:
        users_collection.insert_one({'user_id': user_id, 'free_usage': {'count': 0, 'reset_at': now + timedelta(hours=config.FREE_LIMIT_RESET_HOURS)}})
        user_doc = users_collection.find_one({'user_id': user_id})

    free_usage = user_doc.get('free_usage', {})
    count = free_usage.get('count', 0)
    reset_at = free_usage.get('reset_at')

    if not reset_at or now >= reset_at:
        count = 0
        new_reset_at = now + timedelta(hours=config.FREE_LIMIT_RESET_HOURS)
        users_collection.update_one(
            {'user_id': user_id},
            {'$set': {'free_usage': {'count': 0, 'reset_at': new_reset_at}}},
            upsert=True
        )
        logger.info(f"Reset free video limit for user {user_id}. Next reset at {new_reset_at}.")

    if count < config.FREE_VIDEOS_LIMIT:
        users_collection.update_one(
            {'user_id': user_id},
            {'$inc': {'free_usage.count': 1}},
            upsert=True
        )
        logger.info(f"User {user_id} used a free view. Count is now {count + 1}/{config.FREE_VIDEOS_LIMIT}.")
        return True
    else:
        logger.warning(f"User {user_id} has reached their free video limit.")
        return False

async def check_and_update_free_batch_usage(user_id: int) -> bool:
    if is_premium_user(user_id) or user_has_token(user_id):
        return True

    now = datetime.utcnow()
    user_doc = users_collection.find_one({'user_id': user_id})
    if not user_doc or 'free_batch_usage' not in user_doc:
        users_collection.update_one(
            {'user_id': user_id},
            {'$set': {'free_batch_usage': {'count': 0, 'reset_at': now + timedelta(hours=config.FREE_LIMIT_RESET_HOURS)}}},
            upsert=True
        )
        user_doc = users_collection.find_one({'user_id': user_id})

    free_usage = user_doc.get('free_batch_usage', {})
    count = free_usage.get('count', 0)
    reset_at = free_usage.get('reset_at')

    if not reset_at or now >= reset_at:
        count = 0
        new_reset_at = now + timedelta(hours=config.FREE_LIMIT_RESET_HOURS)
        users_collection.update_one(
            {'user_id': user_id},
            {'$set': {'free_batch_usage': {'count': 0, 'reset_at': new_reset_at}}},
            upsert=True
        )
        logger.info(f"Reset free batch limit for user {user_id}. Next reset at {new_reset_at}.")

    if count < config.FREE_BATCHES_LIMIT:
        users_collection.update_one(
            {'user_id': user_id},
            {'$inc': {'free_batch_usage.count': 1}},
            upsert=True
        )
        logger.info(f"User {user_id} used a free batch view. Count is now {count + 1}/{config.FREE_BATCHES_LIMIT}.")
        return True
    else:
        logger.warning(f"User {user_id} has reached their free batch limit.")
        return False

# --- Premium Status Check and Notification ---
async def check_premium_status_and_notify(client: Client, user_id: int):
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
    if not name:
        return False, "Category name cannot be empty."
    if len(name) > 64:
        return False, "Category name cannot be longer than 64 characters."
    return True, ""

def get_categories() -> list[str]:
    categories = [c['name'] for c in categories_collection.find({})]
    return sorted(list(set(categories)))

def add_category(name: str) -> tuple[bool, str]:
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
    video = media_collection.find_one(
        {'category': category},
        sort=[('sequence_number', ASCENDING)]
    )
    return video

def get_video_by_uuid(uuid_: str) -> dict | None:
    return media_collection.find_one({'uuid': uuid_})

def get_video_and_position(video_uuid: str, category: str, is_saved: bool, user_id: int = None) -> tuple[dict | None, int, int]:
    if is_saved and user_id is not None:
        user_doc = users_collection.find_one({'user_id': user_id})
        bookmarked_videos = user_doc.get('bookmarked_videos', [])

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

    else:
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
            if 'sequence_number' not in video:
                logger.warning(f"Video {video['uuid']} in category {category} is missing 'sequence_number' but is being retrieved for navigation. This indicates a potential data inconsistency or failed migration.")
            return video, current_video_index + 1, total_videos
        return None, 0, 0

def get_video_and_position_batch(batch_id: str, current_index: int) -> tuple[dict | None, int, int]:
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

def get_next_video_chronological(current_uuid: str, category: str) -> tuple[dict | None, bool]:
    current_video = media_collection.find_one({'uuid': current_uuid, 'category': category})
    if not current_video or 'sequence_number' not in current_video:
        logger.warning(f"Current video {current_uuid} not found or missing sequence_number for next chronological lookup. Attempting to get first video.")
        return get_first_video_by_sequence_number(category), True

    current_sequence = current_video['sequence_number']

    next_video = media_collection.find_one(
        {'category': category, 'sequence_number': {'$gt': current_sequence}},
        sort=[('sequence_number', ASCENDING)]
    )

    if next_video:
        logger.debug(f"Found next video {next_video['uuid']} with sequence {next_video['sequence_number']} after {current_sequence}.")
        return next_video, False
    else:
        logger.info(f"End of videos reached for category '{category}'. Looping to first video.")
        return get_first_video_by_sequence_number(category), True

def get_previous_video_chronological(current_uuid: str, category: str) -> dict | None:
    current_video = media_collection.find_one({'uuid': current_uuid, 'category': category})
    if not current_video or 'sequence_number' not in current_video:
        logger.warning(f"Current video {current_uuid} not found or missing sequence_number for previous chronological lookup. Attempting to get last video.")
        return media_collection.find_one(
            {'category': category},
            sort=[('sequence_number', DESCENDING)]
        )

    current_sequence = current_video['sequence_number']

    prev_video = media_collection.find_one(
        {'category': category, 'sequence_number': {'$lt': current_sequence}},
        sort=[('sequence_number', DESCENDING)]
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
    user_doc = users_collection.find_one({'user_id': user_id})
    if not user_doc or not user_doc.get('bookmarked_videos'):
        return None

    bookmarked_videos = user_doc['bookmarked_videos']

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

    if current_video_index == -1:
        logger.warning(f"Current saved video {current_uuid} not found in filtered list for user {user_id}. Returning first saved video in category {category}.")
        return get_video_by_uuid(filtered_saved_videos[0]['uuid'])

    next_index = (current_video_index + 1) % len(filtered_saved_videos)
    next_video_uuid = filtered_saved_videos[next_index]['uuid']

    return get_video_by_uuid(next_video_uuid)

def get_previous_saved_video_chronological(user_id: int, current_uuid: str, category: str) -> dict | None:
    user_doc = users_collection.find_one({'user_id': user_id})
    if not user_doc or not user_doc.get('bookmarked_videos'):
        return None

    bookmarked_videos = user_doc['bookmarked_videos']

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

    if current_video_index == -1:
        logger.warning(f"Current saved video {current_uuid} not found in filtered list for user {user_id}. Returning last saved video in category {category}.")
        return get_video_by_uuid(filtered_saved_videos[-1]['uuid'])

    prev_index = (current_video_index - 1 + len(filtered_saved_videos)) % len(filtered_saved_videos)
    prev_video_uuid = filtered_saved_videos[prev_index]['uuid']

    return get_video_by_uuid(prev_video_uuid)


def save_history(user_id: int, video_uuid: str, category: str):
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
    active_video_message[user_id] = {
        'message_id': message_id,
        'chat_id': chat_id,
        'timestamp': datetime.utcnow()
    }
    logger.info(f"Active video message set for user {user_id}: message_id={message_id}, chat_id={chat_id}")

def clear_active_video_message(user_id: int):
    if user_id in active_video_message:
        del active_video_message[user_id]
        logger.info(f"Active video message cleared for user {user_id}.")

# --- Real-time self-healing functions ---
def rearrange_sequences_after_deletion(category: str, deleted_sequence_number: int):
    logger.info(f"Rearranging sequences for category '{category}' after deleting sequence {deleted_sequence_number}.")
    try:
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
    logger.info(f"Attempting to delete broken video {video_uuid} from DB and channel.")
    if not DATA_CHANNEL_ID:
        logger.error("DATA_CHANNEL_ID is not set. Cannot delete from channel.")
        return False

    try:
        result = media_collection.delete_one({'uuid': video_uuid})
        if result.deleted_count > 0:
            logger.info(f"Successfully deleted video {video_uuid} from media_collection.")

            if category and sequence_number is not None:
                rearrange_sequences_after_deletion(category, sequence_number)
            else:
                logger.warning(f"Skipping sequence rearrangement for {video_uuid}: category or sequence_number missing.")

            users_collection.update_many(
                {},
                {'$pull': {'bookmarked_videos': {'uuid': video_uuid}}}
            )
            logger.info(f"Removed video {video_uuid} from all users' bookmarked_videos.")

            history_collection.update_many(
                {},
                {'$pull': {'history': {'video_uuid': video_uuid}}}
            )
            logger.info(f"Removed video {video_uuid} from all users' history.")

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
    sent_message = None
    settings = settings_collection.find_one({'_id': 'settings'}) or {}
    protect_content_for_user = settings.get('protect_content', True)

    if new_message_type == "video" and not DATA_CHANNEL_ID:
        logger.error("DATA_CHANNEL_ID is not set. Cannot send videos.")
        return False, "Video storage channel is not configured. Please contact an admin."

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
                            if len(parts) == 4 and (parts[0] == 'next' or parts[0] == 'prev'):
                                is_saved_from_markup = bool(int(parts[3]))
                                break
                    if is_saved_from_markup:
                        break
            _, current_position, total_videos = get_video_and_position(
                video_data['uuid'], video_data.get('category'), is_saved_from_markup, chat_id
            )

        custom_caption = video_data.get('custom_caption')
        category_caption = f"Category: {html.escape(video_data['category'])}" if video_data.get('category') else ""

        position_caption = ""
        if total_videos > 0 and current_position > 0:
            position_caption = f"#{current_position} of {total_videos}\n"

        caption_text = f"{position_caption}{custom_caption or category_caption}".strip()

    if force_new_message and message_id_to_edit_or_delete:
        try:
            await client.delete_messages(chat_id, message_id_to_edit_or_delete)
            logger.info(f"Deleted old message {message_id_to_edit_or_delete} in chat {chat_id} before sending new.")
        except MessageIdInvalid:
            logger.warning(f"Old message {message_id_to_edit_or_delete} for deletion was already invalid.")
        except Exception as e:
            logger.error(f"Failed to delete old message {message_id_to_edit_or_delete}: {e}")

    if new_message_type == "video" and video_data:
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
                await delete_broken_video_from_db_and_channel(client, video_data['uuid'], video_data.get('category'), video_data.get('sequence_number'), video_data.get('message_id'))
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
                        await delete_broken_video_from_db_and_channel(client, video_data['uuid'], video_data.get('category'), video_data.get('sequence_number'), video_data.get('message_id'))
                        return False, "Video was unavailable and self-healing failed."
                except Exception as e2:
                    logger.error(f"Fallback send_video also failed for {video_data['uuid']}: {e2}. The video might be broken.", exc_info=True)
                    await client.send_message(chat_id, "Oops! This video is unavailable and has been removed. Trying the next one... 🔄")
                    await delete_broken_video_from_db_and_channel(client, video_data['uuid'], video_data.get('category'), video_data.get('sequence_number'), video_data.get('message_id'))
                    return False, "Video was unavailable by all methods."

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

    if isinstance(sent_message, Message):
        set_active_video_message(chat_id, sent_message.id, chat_id)
        return True, sent_message
    else:
        error_message = "Failed to send or edit the message due to an unexpected error."
        logger.error(error_message)
        return False, error_message


# --- Keyboards ---
async def get_main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton("📱 Open App"), KeyboardButton("🎞️ Get Video")],
        [KeyboardButton("👤 Profile"), KeyboardButton("🔗 Refer & Earn")],
        [KeyboardButton("💰 Buy Token"), KeyboardButton("🔄 Refresh Token")],
        [KeyboardButton("🔖 Saved Videos")]
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def generate_token_earning_keyboard(ad_url: str, is_pending_content: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("👆 Click Here To Refresh Token", url=ad_url)],
        [InlineKeyboardButton("🔗 Refer & Earn", callback_data="refer_and_earn_inline")],
        [InlineKeyboardButton("❓ How To Open Links?", url=config.TUTORIAL_LINK_2)],
        [InlineKeyboardButton("💳 Buy Token", url=config.BUY_BOT_URL)],
    ]
    if is_pending_content:
        buttons.append([InlineKeyboardButton("🔄 Refresh", callback_data="reload_pending_content")])
    return InlineKeyboardMarkup(buttons)

def category_keyboard() -> InlineKeyboardMarkup:
    cats = get_categories()
    if not cats:
        return InlineKeyboardMarkup([[InlineKeyboardButton("😔 No Categories Available", callback_data="no_cat")]])

    buttons = []
    row = []
    for i, cat in enumerate(cats):
        row.append(InlineKeyboardButton(f"🎬 {html.escape(cat)}", callback_data=f"cat_{str_to_b64(cat)}"))
        if (i + 1) % 3 == 0:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    return InlineKeyboardMarkup(buttons)

def video_nav_keyboard(
    video_uuid: str,
    category: str,
    user_id: int,
    is_saved: bool = False,
    is_batch: bool = False,
    batch_id: str = None,
    batch_index: int = -1,
    is_shared_link: bool = False,
    is_grace_period: bool = False
) -> InlineKeyboardMarkup:
    buttons = []

    if is_grace_period:
        buttons.append([
            InlineKeyboardButton("⬅️ Previous", callback_data=f"grace_nav|{video_uuid}|{str_to_b64(category)}"),
            InlineKeyboardButton("➡️ Next", callback_data=f"grace_nav|{video_uuid}|{str_to_b64(category)}")
        ])
    elif is_shared_link:
        buttons.append([
            InlineKeyboardButton("⬅️ Previous", callback_data="shared_nav"),
            InlineKeyboardButton("➡️ Next", callback_data="shared_nav")
        ])
    elif is_batch:
        buttons.append([
            InlineKeyboardButton("⬅️ Previous", callback_data=f"prev_batch|{batch_id}|{batch_index}"),
            InlineKeyboardButton("➡️ Next", callback_data=f"next_batch|{batch_id}|{batch_index}")
        ])
    else:
        buttons.append([
            InlineKeyboardButton("⬅️ Previous", callback_data=f"prev|{video_uuid}|{str_to_b64(category)}|{int(is_saved)}"),
            InlineKeyboardButton("➡️ Next", callback_data=f"next|{video_uuid}|{str_to_b64(category)}|{int(is_saved)}")
        ])

    row_2_buttons = []
    if is_saved:
        row_2_buttons.append(InlineKeyboardButton("🗑️ Remove", callback_data=f"remove_saved_{video_uuid}"))
    else:
        row_2_buttons.append(InlineKeyboardButton("💾 Bookmark", callback_data=f"bookmark_{video_uuid}"))

    row_2_buttons.append(InlineKeyboardButton("📲 Share", callback_data=f"share_{video_uuid}"))
    row_2_buttons.append(InlineKeyboardButton("⬇️ Download", callback_data=f"download_{video_uuid}"))
    buttons.append(row_2_buttons)

    row_3_buttons = []
    if is_batch or is_shared_link or is_grace_period:
        row_3_buttons.append(InlineKeyboardButton("👀 Watch More", callback_data="watch_more"))
    elif is_saved:
        row_3_buttons.append(InlineKeyboardButton("⬅️ Back", callback_data="back_to_saved_cats"))
    else:
        row_3_buttons.append(InlineKeyboardButton("🗂️ Change Category", callback_data="change_cat"))

    if row_3_buttons:
        buttons.append(row_3_buttons)

    return InlineKeyboardMarkup(buttons)

def referral_keyboard(ref_link: str) -> InlineKeyboardMarkup:
    return None

def get_premium_only_text() -> str:
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
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Buy Premium Access", url=config.BUY_BOT_URL)]
    ])

def saved_category_keyboard(user_id: int) -> InlineKeyboardMarkup:
    user_doc = users_collection.find_one({'user_id': user_id})
    if not user_doc or not user_doc.get('bookmarked_videos'):
        return InlineKeyboardMarkup([[InlineKeyboardButton("😔 No Saved Videos Yet", callback_data="no_saved_videos")]])

    bookmarked_videos = user_doc['bookmarked_videos']

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
        row.append(InlineKeyboardButton(f"🗂️ {html.escape(cat)}", callback_data=f"view_saved_cat_{str_to_b64(cat)}"))
        if (i + 1) % 2 == 0:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    return InlineKeyboardMarkup(buttons)

# --- Video Sharing ---
async def handle_shared_video(client: Client, user_id: int, video_uuid: str) -> tuple[bool, dict | str]:
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

        added_token = add_token(user_id, config.REFRESH_BONUS * 86400, is_admin_granted=False)
        if added_token:
            refresh_tokens_used_collection.insert_one({'ad_code': ad_code, 'used_at': datetime.utcnow()})
            logger.info(f"Token added for user {user_id} via refresh. Premium status unaffected. Ad code {ad_code} marked as used.")
            return True, "✅ <b>Access Granted.</b> Your 24-hour unlimited pass is now active. Nothing will interrupt you. Enjoy the stream."
        else:
            return False, "❌ <b>Something went wrong!</b>\nFailed to add token. Please try again later. 🛠️"
    except Exception as e:
        logger.error(f"Token refresh failed for user {user_id}: {e}", exc_info=True)
        return False, "❌ <b>Something went wrong!</b>\nPlease try again later. 🤷‍♀️"

# --- Rate Limiting ---
RATE_LIMIT_WINDOW = 120
RATE_LIMIT_MAX = 60

async def is_rate_limited(user_id: int) -> bool:
    if is_admin(user_id):
        return False

    now = datetime.utcnow()
    window_start = now - timedelta(seconds=RATE_LIMIT_WINDOW)

    try:
        tokens_collection.update_one(
            {'user_id': user_id},
            {'$pull': {'rate_limits': {'timestamp': {'$lt': window_start}}}},
            upsert=True
        )

        tokens_collection.update_one(
            {'user_id': user_id},
            {'$push': {'rate_limits': {'timestamp': now}}}
        )

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
    if isinstance(error, FloodWait):
        logger.warning(f"FloodWait: {error.value} seconds for user {message.from_user.id}")
        await message.reply_text(f"⚠️ <b>Too Many Requests!</b>\nPlease wait <b>{error.value}</b> seconds before trying again. ⏳")
    else:
        logger.error(f"An unexpected error occurred for user {message.from_user.id}: {error}", exc_info=True)
        await message.reply_text(f"❌ <b>An unexpected error occurred.</b>\nPlease try again later. 🥺")

# =====================================================================================
# ======================== MINI APP (FASTAPI) BACKEND CODE ============================
# =====================================================================================

async def verify_telegram_init_data(request: Request) -> dict:
    try:
        init_data_str = request.headers.get("X-Telegram-Init-Data")
        if not init_data_str:
            logger.error("API call received without X-Telegram-Init-Data header.")
            raise HTTPException(status_code=401, detail="Unauthorized: Missing Telegram Init Data")

        params = dict(parse_qs(init_data_str))
        hash_from_telegram = params.pop('hash', [None])[0]

        if not hash_from_telegram:
            raise HTTPException(status_code=401, detail="Unauthorized: Hash not found in Init Data")

        data_check_string = "\n".join(f"{k}={v[0]}" for k, v in sorted(params.items()))

        secret_key = hmac.new("WebAppData".encode(), config.BOT_TOKEN.encode(), hashlib.sha256).digest()

        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

        if calculated_hash != hash_from_telegram:
            logger.error(f"API call with invalid hash. Calculated: {calculated_hash}, Received: {hash_from_telegram}")
            raise HTTPException(status_code=403, detail="Forbidden: Invalid data signature")

        user_data_json = params.get('user', [None])[0]
        if not user_data_json:
            raise HTTPException(status_code=401, detail="Unauthorized: User data not found in Init Data")

        user_data = json.loads(unquote(user_data_json))
        user_id = user_data.get('id')

        if not user_id:
            raise HTTPException(status_code=401, detail="Unauthorized: User ID not found in user data")

        logger.info(f"API call verified for user_id: {user_id}")
        return {"user_id": user_id}

    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Bad Request: Invalid JSON in user data")
    except Exception as e:
        logger.error(f"An unexpected error occurred during initData verification: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal Server Error")

class BookmarkRequest(BaseModel):
    video_uuid: str

@fastapi_app.get("/api/profile")
async def get_api_profile(auth: dict = Depends(verify_telegram_init_data)):
    user_id = auth["user_id"]
    user_doc = await async_users_collection.find_one({'user_id': user_id})
    tokens_doc = await async_tokens_collection.find_one({'user_id': user_id})

    if not user_doc:
        raise HTTPException(status_code=404, detail="User not found")

    now = datetime.utcnow()
    tokens_count = sum(1 for token in tokens_doc.get('tokens', []) if token.get('expires_at') and token['expires_at'] > now)

    is_premium = False
    for token in tokens_doc.get('tokens', []):
        if token.get('is_admin_granted', False) and token.get('expires_at') and token['expires_at'] > now:
            is_premium = True
            break

    return {
        "status": "Premium" if is_premium else "Free",
        "tokens": tokens_count,
        "referrals": user_doc.get('referral_count', 0)
    }

@fastapi_app.get("/api/categories")
async def get_api_categories(auth: dict = Depends(verify_telegram_init_data)):
    cursor = async_categories_collection.find({}, {'name': 1, '_id': 0})
    categories = [doc['name'] async for doc in cursor]
    return sorted(categories)

@fastapi_app.get("/api/feed/{category}")
async def get_api_feed(category: str, page: int = 1, limit: int = 20, auth: dict = Depends(verify_telegram_init_data)):
    if page < 1:
        raise HTTPException(status_code=400, detail="Page number must be 1 or greater.")
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=400, detail="Limit must be between 1 and 100.")

    skip_count = (page - 1) * limit
    cursor = async_media_collection.find(
        {'category': category, 'banned': {'$ne': True}},
        {'uuid': 1, 'custom_caption': 1, '_id': 0}
    ).sort('sequence_number', ASCENDING).skip(skip_count).limit(limit)

    videos = await cursor.to_list(length=limit)
    return videos

@fastapi_app.get("/api/get-stream-url/{video_uuid}")
async def get_api_stream_url(video_uuid: str, auth: dict = Depends(verify_telegram_init_data)):
    user_id = auth["user_id"]

    if not user_has_token(user_id) and not is_premium_user(user_id):
         raise HTTPException(status_code=403, detail="Access Denied: Token required")

    video_doc = await async_media_collection.find_one({'uuid': video_uuid})
    if not video_doc:
        raise HTTPException(status_code=404, detail="Video not found")

    file_id = video_doc.get('file_id')
    if not file_id:
        raise HTTPException(status_code=500, detail="Video data is incomplete")

    if not DATA_CHANNEL_ID:
        logger.error("DATA_CHANNEL_ID is not set. Cannot stream videos.")
        raise HTTPException(status_code=503, detail="Service Unavailable: Video storage channel not configured.")

    try:
        file_obj = [obj async for obj in app.get_file(file_id)][0]
        if not file_obj or not file_obj.file_path:
            raise HTTPException(status_code=500, detail="Could not retrieve file path from Telegram.")
        download_link = f"https://api.telegram.org/file/bot{config.BOT_TOKEN}/{file_obj.file_path}"
        return JSONResponse(content={"url": download_link})
    except FileReferenceExpired:
        logger.warning(f"FileReferenceExpired for API stream {video_uuid}. Attempting self-heal.")
        try:
            message_id_in_channel = video_doc.get('message_id')
            if not message_id_in_channel: raise ValueError("No message_id for healing.")

            healed_message = await app.get_messages(DATA_CHANNEL_ID, message_id_in_channel)
            if not healed_message or not healed_message.video: raise ValueError("Failed to fetch healed message.")

            new_file_id = healed_message.video.file_id
            await async_media_collection.update_one({'uuid': video_uuid}, {'$set': {'file_id': new_file_id}})
            logger.info(f"DB updated with new file_id for {video_uuid} via API self-heal. Retrying.")

            file_obj = [obj async for obj in app.get_file(new_file_id)][0]
            if not file_obj or not file_obj.file_path:
                raise HTTPException(status_code=500, detail="Could not retrieve file path from Telegram after healing.")
            download_link = f"https://api.telegram.org/file/bot{config.BOT_TOKEN}/{file_obj.file_path}"
            return JSONResponse(content={"url": download_link})
        except Exception as heal_e:
            logger.error(f"API self-healing failed for {video_uuid}: {heal_e}")
            raise HTTPException(status_code=503, detail="Service Unavailable: Could not retrieve video stream.")
    except Exception as e:
        logger.error(f"Error generating download link for API stream {video_uuid}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal Server Error")

@fastapi_app.get("/api/video/{video_uuid}")
async def get_api_video_details(video_uuid: str, auth: dict = Depends(verify_telegram_init_data)):
    video_doc = await async_media_collection.find_one({'uuid': video_uuid})
    if not video_doc:
        raise HTTPException(status_code=404, detail="Video not found")

    return {
        "uuid": video_doc.get("uuid"),
        "custom_caption": video_doc.get("custom_caption"),
        "category": video_doc.get("category"),
    }

@fastapi_app.get("/api/saved")
async def get_api_saved_videos(auth: dict = Depends(verify_telegram_init_data)):
    user_id = auth["user_id"]

    pipeline = [
        {'$match': {'user_id': user_id}},
        {'$unwind': '$bookmarked_videos'},
        {'$lookup': {
            'from': 'media',
            'localField': 'bookmarked_videos.uuid',
            'foreignField': 'uuid',
            'as': 'video_details'
        }},
        {'$unwind': '$video_details'},
        {'$project': {
            '_id': 0,
            'uuid': '$video_details.uuid',
            'custom_caption': '$video_details.custom_caption',
            'category': '$video_details.category',
            'bookmarked_at': '$bookmarked_videos.bookmarked_at'
        }},
        {'$sort': {'bookmarked_at': DESCENDING}}
    ]

    saved_videos_cursor = async_users_collection.aggregate(pipeline)
    saved_videos = await saved_videos_cursor.to_list(length=None)

    return saved_videos

@fastapi_app.post("/api/bookmark")
async def toggle_api_bookmark(request: BookmarkRequest, auth: dict = Depends(verify_telegram_init_data)):
    user_id = auth["user_id"]
    video_uuid = request.video_uuid

    user_doc = await async_users_collection.find_one({'user_id': user_id})
    if not user_doc:
        raise HTTPException(status_code=404, detail="User not found")

    bookmarked_videos = user_doc.get('bookmarked_videos', [])
    is_already_bookmarked = any(v['uuid'] == video_uuid for v in bookmarked_videos)

    if is_already_bookmarked:
        await async_users_collection.update_one(
            {'user_id': user_id},
            {'$pull': {'bookmarked_videos': {'uuid': video_uuid}}}
        )
        return JSONResponse(content={"status": "removed"}, status_code=200)
    else:
        is_premium = is_premium_user(user_id)
        if not is_premium and len(bookmarked_videos) >= config.FREE_USER_SAVE_LIMIT:
            raise HTTPException(status_code=403, detail=f"Bookmark limit of {config.FREE_USER_SAVE_LIMIT} reached for free users.")

        video_data = await async_media_collection.find_one({'uuid': video_uuid})
        if not video_data:
            raise HTTPException(status_code=404, detail="Video to bookmark not found.")

        new_bookmark = {
            'uuid': video_uuid,
            'bookmarked_at': datetime.utcnow(),
            'category': video_data.get('category')
        }
        await async_users_collection.update_one(
            {'user_id': user_id},
            {'$push': {'bookmarked_videos': new_bookmark}}
        )
        return JSONResponse(content={"status": "added"}, status_code=201)

# =====================================================================================
# ============================= END OF MINI APP BACKEND ===============================
# =====================================================================================


# --- Handlers ---
@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    first_name_safe = html.escape(message.from_user.first_name) if message.from_user.first_name else "there"

    try:
        args = message.text.split()
        deep_link_arg = args[1] if len(args) > 1 else None

        user = users_collection.find_one({'user_id': user_id})
        is_new_user = not user
        if is_new_user:
            username_safe = html.escape(message.from_user.username) if message.from_user.username else ""
            users_collection.insert_one({
                'user_id': user_id, 'username': username_safe, 'first_name': first_name_safe,
                'last_name': html.escape(message.from_user.last_name) if message.from_user.last_name else None,
                'joined_date': datetime.utcnow(), 'referral_count': 0, 'bookmarked_videos': [],
                'last_premium_check_status': False, 'last_viewed_per_category': {}, 'pending_command': None,
                'free_usage': {'count': 0, 'reset_at': datetime.utcnow() + timedelta(hours=config.FREE_LIMIT_RESET_HOURS)},
                'free_batch_usage': {'count': 0, 'reset_at': datetime.utcnow() + timedelta(hours=config.FREE_LIMIT_RESET_HOURS)},
                'grace_period_active': True
            })
            add_token(user_id, config.NEW_USER_TOKENS * 86400, is_admin_granted=False)
            logger.info(f"New user registered: {user_id} and received {config.NEW_USER_TOKENS} token.")

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
        
        user = users_collection.find_one({'user_id': user_id})

        # --- Grace Period Check for New Users with a Video Link ---
        is_in_grace_period = user.get('grace_period_active', False)
        if is_in_grace_period and deep_link_arg and deep_link_arg.startswith('video_'):
            loading_msg = await message.reply("Loading your request, please wait...")
            video_uuid = deep_link_arg.split('_')[1]
            success, result = await handle_shared_video(client, user_id, video_uuid)
            if success:
                video = result
                await send_and_replace_message(
                    client, message.chat.id, message.id, "video", video_data=video,
                    reply_markup=video_nav_keyboard(video['uuid'], video['category'], user_id, is_grace_period=True),
                    force_new_message=True
                )
                users_collection.update_one({'user_id': user_id}, {'$set': {'grace_period_active': False}})
                logger.info(f"New user {user_id} received grace period video {video_uuid}. Grace period is now used.")
            else:
                await message.reply(result)
            
            await loading_msg.delete()
            return

        # --- Standard Membership Check (for everyone else) ---
        has_joined = await check_membership(client, user_id)
        if not has_joined:
            if deep_link_arg:
                users_collection.update_one({'user_id': user_id}, {'$set': {'pending_command': deep_link_arg}})

            custom_text = None
            if is_new_user:
                part1 = f"🎉 Congratulations {first_name_safe}!\n\nYou've just received {config.NEW_USER_TOKENS} free token 🎁 to start your journey!\n\n"
                part2 = "To watch the video you requested, you just need to join our channels first. Once you've joined, tap the '🔄 Try Again' button below, and I'll take you straight to your video! 🚀" if deep_link_arg else "Please join our channels to continue. Once you've joined, tap the '🔄 Try Again' button below! 🚀"
                custom_text = part1 + part2

            await send_force_subscribe_message(client, user_id, custom_text=custom_text)
            return

        if await is_rate_limited(user_id):
            raise FloodWait(10)
        create_tracked_task(check_premium_status_and_notify(client, user_id))

        if deep_link_arg:
            loading_msg = await message.reply("Loading your request, please wait...")
            try:
                deep_link_type, deep_link_data = None, None
                if deep_link_arg.startswith('token_'):
                    deep_link_type, deep_link_data = 'token_refresh', deep_link_arg[6:]
                elif deep_link_arg.startswith('video_'):
                    deep_link_type, deep_link_data = 'video_share', deep_link_arg.split('_')[1]
                elif deep_link_arg.startswith('ref_'):
                    pass
                elif deep_link_arg.startswith('batch_'):
                    deep_link_type, deep_link_data = 'batch', deep_link_arg[6:]

                if deep_link_type == 'token_refresh':
                    success, msg = await handle_token_refresh(user_id, deep_link_data)
                    await message.reply(msg)
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
                    if not user_has_token(user_id):
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
                            save_history(user_id, video['uuid'], video['category'])
                            await client.send_message(
                                message.chat.id,
                                "🫣Tap \"watch more\" to watch your favorite category",
                                reply_markup=await get_main_keyboard(user_id)
                            )

                elif deep_link_type == 'batch':
                    if not (is_premium_user(user_id) or user_has_token(user_id)):
                        if not await check_and_update_free_batch_usage(user_id):
                            await send_limit_reached_message(client, message.chat.id)
                            return

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
                                await client.send_message(
                                    message.chat.id,
                                    "🫣Tap \"watch more\" to watch your favorite category",
                                    reply_markup=await get_main_keyboard(user_id)
                                )
            finally:
                if loading_msg: await loading_msg.delete()
        elif is_new_user:
            await message.reply(
                f"🎉 Congratulations {first_name_safe}!\n"
                f"You got {config.NEW_USER_TOKENS} token 🎁 to start your journey!\n\n"
                f"🔥 Tap ‘🎞️ Get Video’ now and dive straight into your favorite category 🚀",
                reply_markup=await get_main_keyboard(user_id)
            )
        else:
            await message.reply(f"👋 Welcome back, {first_name_safe}! 🌶️\n\nReady for more? Tap '🎞️ Get Video' to dive in.", reply_markup=await get_main_keyboard(user_id))

    except FloodWait as e:
        await handle_error(client, message, e)
    except Exception as e:
        logger.error(f"User {user_id} encountered an unexpected error in start command: {e}", exc_info=True)
        await handle_error(client, message, e)

@app.on_callback_query(filters.regex(r"^check_join_status$"))
async def check_join_status_callback(client: Client, callback_query: CallbackQuery):
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

        mock_message = callback_query.message
        mock_message.text = f"/start {pending_command}" if pending_command else "/start"
        mock_message.from_user = callback_query.from_user
        create_tracked_task(start_cmd(client, mock_message))
    else:
        await callback_query.answer("⚠️ You still need to join all channels to proceed.", show_alert=True)

@app.on_callback_query(filters.regex(r"^reload_pending_content$"))
async def reload_pending_content_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id

    if not await check_membership(client, user_id):
        await callback_query.answer("You must join our channels first!", show_alert=True)
        await send_force_subscribe_message(client, user_id)
        return

    if not user_has_token(user_id):
        await callback_query.answer("You still haven't received a token. Please complete the task first.", show_alert=True)
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

@app.on_callback_query(filters.regex(r"^shared_nav$"))
async def shared_nav_callback(client: Client, callback_query: CallbackQuery):
    await callback_query.answer(
        "No more videos in this link. Click on 'Watch More' to explore other categories.",
        show_alert=True
    )

@app.on_callback_query(filters.regex(r"^grace_nav\|(.+)\|(.+)$"))
async def grace_period_nav_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    logger.info(f"User {user_id} clicked nav button after grace period video.")

    has_joined = await check_membership(client, user_id)
    if not has_joined:
        try:
            await callback_query.message.delete()
        except Exception as e:
            logger.warning(f"Could not delete grace period video for user {user_id}: {e}")
        
        custom_text = "To continue watching, please join our main and backup channels. This ensures you never lose access. Once you've joined, tap 'Try Again' below, and I'll take you straight to the next video! 🚀"
        await send_force_subscribe_message(client, user_id, custom_text=custom_text)
        await callback_query.answer()
        return

    await callback_query.answer("✅ Membership confirmed! Loading next video...")
    
    parts = callback_query.data.split('|')
    current_uuid = parts[1]
    category = b64_to_str(parts[2])

    video, did_loop = get_next_video_chronological(current_uuid, category)
    if not video:
        await callback_query.message.reply("Could not find the next video in this category.")
        return

    await send_and_replace_message(
        client,
        callback_query.message.chat.id,
        message_id_to_edit_or_delete=callback_query.message.id,
        new_message_type="video",
        video_data=video,
        reply_markup=video_nav_keyboard(video['uuid'], category, user_id, is_saved=False),
        force_new_message=False
    )
    save_history(user_id, video['uuid'], category)

@app.on_callback_query(filters.regex(r"^watch_more$"))
async def watch_more_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id
    logger.info(f"User {user_id} clicked 'Watch More'.")

    try:
        await callback_query.message.delete()
        clear_active_video_message(user_id)

        cats_keyboard = category_keyboard()
        if cats_keyboard.inline_keyboard[0][0].callback_data == "no_cat":
            await client.send_message(chat_id, "😔 No categories are available right now. Please check back later!")
            return

        sent_message = await client.send_message(
            chat_id,
            "🎬 <b>Choose a Category to explore more content:</b>",
            reply_markup=cats_keyboard
        )
        set_active_video_message(user_id, sent_message.id, chat_id)
        await callback_query.answer()

    except Exception as e:
        logger.error(f"Error in watch_more_callback for user {user_id}: {e}", exc_info=True)
        await callback_query.answer("An error occurred. Please try again!", show_alert=True)

@app.on_message(filters.command("help") & filters.private)
async def help_cmd(client: Client, message: Message):
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
        f"👋 Hey {user_mention_safe}! Here's how to use the bot: 📚\n\n"
        "- **📱 Open App**: Launch the new, fast, full-screen video browser.\n"
        "- **🎞️ Get Video**: The classic button to browse and watch content.\n"
        "- **👤 Profile**: Check your status, tokens, and referral stats.\n"
        "- **🔗 Refer & Earn**: Get your unique link to invite friends and earn free tokens.\n"
        "- **💰 Buy Token**: Upgrade to Premium for the best experience.\n"
        "- **🔄 Refresh Token**: Get a new 24-hour token by completing a simple task.\n"
        "- **🔖 Saved Videos**: Access all your bookmarked videos.\n\n"
        "If you have any issues, feel free to contact our support. Enjoy! 🌶️",
        reply_markup=reply_markup
    )

@app.on_message(filters.command("profile") & filters.private)
async def profile_cmd(client: Client, message: Message):
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
                'pending_command': None
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
        bookmarked_videos = user.get('bookmarked_videos', [])

        is_premium = is_premium_user(user_id)
        user_status = "💎 Premium User" if is_premium else "✨ Free User"

        if is_premium:
            save_limit_display = f"{len(bookmarked_videos)} / Unlimited"
        else:
            save_limit_display = f"{len(bookmarked_videos)} / {config.FREE_USER_SAVE_LIMIT}"

        ref_link = f"https://t.me/{config.BOT_USERNAME[1:]}?start=ref_{user_id}"

        profile_text = (
            f"👤 <b>Your Profile</b>\n\n"
            f"📌 Status: {user_status}\n"
            f"🪙 Active Tokens: {tokens_count}\n"
            f"❤️ Saved Videos: {save_limit_display}\n"
            f"👥 Total Referrals: {referral_count}\n"
            f"───────────────────────\n"
            f"🔗 Your Referral Link:\n{html.escape(ref_link)}\n"
            f"───────────────────────\n\n"
            f"💡 Share this link with friends to earn free tokens! 🎁"
        )

        await message.reply(profile_text, reply_markup=await get_main_keyboard(user_id))
        logger.info(f"User {user_id}: Profile sent successfully.")
    except Exception as e:
        logger.error(f"User {user_id} failed to send profile: {e}", exc_info=True)
        await handle_error(client, message, e)


@app.on_message(filters.regex("^🎞️ Get Video$") & filters.private)
async def get_video(client: Client, message: Message):
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

    wait_msg = await message.reply("Just a moment, checking your access...")
    if not user_has_token(user_id):
        await wait_msg.delete()
        logger.info(f"User {user_id} has no tokens, prompting earning options.")
        await send_token_earning_options(client, message)
        return
    await wait_msg.delete()

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
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id
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
        return

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
        video = get_first_video_by_sequence_number(category_name)

    if not video:
        logger.warning(f"No videos found in category '{category_name}' for user {user_id}.")
        await callback_query.answer("No videos in this category. Try another! 😔", show_alert=True)
        await temp_msg.delete()
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
        reply_markup=video_nav_keyboard(video['uuid'], category_name, user_id, is_saved=False),
        force_new_message=True
    )

    if sent_success:
        save_history(user_id, video['uuid'], category_name)
        await callback_query.answer()
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

@app.on_callback_query(filters.regex(r"^view_saved_cat_(.+)$"))
async def view_saved_category_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id
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

    filtered_saved_videos = []
    for bookmark in bookmarked_videos:
        video_data = get_video_by_uuid(bookmark['uuid'])
        if video_data and video_data.get('category') == selected_category:
            filtered_saved_videos.append(bookmark)

    filtered_saved_videos.sort(key=lambda x: x.get('bookmarked_at', datetime.min))

    if not filtered_saved_videos:
        await callback_query.answer(f"You haven't saved any videos from the '{html.escape(selected_category)}' category yet. ❤️", show_alert=True)
        await send_and_replace_message(
            client,
            chat_id,
            message_id_to_edit_or_delete=callback_query.message.id,
            new_message_type="text",
            text_content="🗂️ <b>Select a Category from your Saved Videos:</b>",
            reply_markup=saved_category_keyboard(user_id)
        )
        return

    first_saved_video_uuid = filtered_saved_videos[0]['uuid']
    video_to_display = get_video_by_uuid(first_saved_video_uuid)

    if not video_to_display:
        await callback_query.answer("The first video in this saved category was not found. It may have been removed. 😔", show_alert=True)
        users_collection.update_one(
            {'user_id': user_id},
            {'$pull': {'bookmarked_videos': {'uuid': first_saved_video_uuid}}}
        )
        await send_and_replace_message(
            client,
            chat_id,
            message_id_to_edit_or_delete=callback_query.message.id,
            new_message_type="text",
            text_content="🗂️ <b>Select a Category from your Saved Videos:</b>",
            reply_markup=saved_category_keyboard(user_id)
        )
        return

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
        save_history(user_id, video_to_display['uuid'], selected_category)
        await callback_query.answer()
        logger.info(f"User {user_id} viewed first saved video {video_to_display['uuid']} in category {selected_category}.")
    else:
        await callback_query.answer("❌ Failed to load video. Please try again.😥", show_alert=True)
        clear_active_video_message(user_id)


@app.on_callback_query(filters.regex(r"^(next|prev)\|(.+)\|(.+)\|(\d+)$"))
async def navigate_video(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id

    if user_id in processing_navigation_lock:
        await callback_query.answer("don't spam again", show_alert=True)
        return
    processing_navigation_lock.add(user_id)

    try:
        chat_id = callback_query.message.chat.id
        parts = callback_query.data.split('|')
        if len(parts) != 4:
            logger.error(f"Invalid callback data for navigate_video: {callback_query.data}")
            await callback_query.answer("Invalid request. Please try again.", show_alert=True)
            return

        action, current_uuid, category_encoded, is_saved_flag_str = parts
        category = b64_to_str(category_encoded)
        is_saved = bool(int(is_saved_flag_str))

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

            if current_active_tracked_message and current_active_tracked_message.get('message_id') != callback_query.message.id:
                logger.warning(f"User {user_id} clicked old menu button. Callback Message ID: {callback_query.message.id}, Active Menu ID: {current_active_tracked_message.get('message_id')}")
                await callback_query.answer("This menu is outdated. Please use the latest one. 🔄", show_alert=True)
                return

            video = None
            did_loop = False
            if is_saved:
                if action == "next":
                    video = get_next_saved_video_chronological(user_id, current_uuid, category)
                elif action == "prev":
                    video = get_previous_saved_video_chronological(user_id, current_uuid, category)

                if not video:
                    await callback_query.answer("No more saved videos in this category. Looping to the beginning/end. ❤️", show_alert=True)
                    return

            else:
                if category not in get_categories():
                    logger.warning(f"User {user_id} used invalid category '{category}' for navigation (non-saved).")
                    await callback_query.answer("Category not found. Try 'Change Category'! 🧐", show_alert=True)
                    return

                if action == "next":
                    video, did_loop = get_next_video_chronological(current_uuid, category)
                elif action == "prev":
                    video = get_previous_video_chronological(current_uuid, category)

                if not video:
                    await callback_query.answer(f"No more {action} videos in this category. Try another! 😔", show_alert=True)
                    return

            sent_success, sent_message_or_error = await send_and_replace_message(
                client,
                chat_id,
                message_id_to_edit_or_delete=callback_query.message.id,
                new_message_type="video",
                video_data=video,
                reply_markup=video_nav_keyboard(video['uuid'], category, user_id, is_saved=is_saved),
                force_new_message=False
            )

            if sent_success:
                save_history(user_id, video['uuid'], category)
                logger.info(f"User {user_id} navigated to {action} video {video['uuid']} in category {category}.")
                await callback_query.answer()
                if did_loop:
                    await client.send_message(
                        chat_id,
                        f"You've just finished the entire <b>{html.escape(category)}</b> collection. 🔥",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("👀 Watch More", callback_data="watch_more")]])
                    )
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
        if user_id in processing_navigation_lock:
            processing_navigation_lock.remove(user_id)

@app.on_callback_query(filters.regex(r"^(next_batch|prev_batch)\|(.+)\|(\d+)$"))
async def navigate_batch_video(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id

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
        
        if action == "next_batch":
            if current_index == total_videos - 1:
                await callback_query.message.delete()
                await client.send_message(
                    chat_id,
                    "You've just finished the entire collection. 🔥\n\nTap below to dive into a new category and continue your journey.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("👀 Watch More", callback_data="watch_more")]])
                )
                await callback_query.answer()
                return
            new_index = (current_index + 1)
        else: # prev_batch
            new_index = (current_index - 1 + total_videos) % total_videos

        next_video_uuid = video_uuids[new_index]
        video = get_video_by_uuid(next_video_uuid)

        if not video:
            await callback_query.answer("The next video in this batch is unavailable.", show_alert=True)
            return

        await send_and_replace_message(
            client, chat_id, callback_query.message.id, "video", video_data=video,
            reply_markup=video_nav_keyboard(video['uuid'], video['category'], user_id, is_batch=True, batch_id=batch_id, batch_index=new_index),
            force_new_message=False, is_batch=True, batch_id=batch_id, batch_index=new_index
        )
        await callback_query.answer()

    except Exception as e:
        logger.error(f"Error in navigate_batch_video for user {user_id}: {e}", exc_info=True)
        await callback_query.answer("An error occurred.", show_alert=True)
    finally:
        if user_id in processing_navigation_lock:
            processing_navigation_lock.remove(user_id)

@app.on_callback_query(filters.regex(r"^change_cat$"))
async def change_category(client: Client, callback_query: CallbackQuery):
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
        await message.reply(
            f"🔗 <b>Share & Earn!</b>\nWhen a new user joins through this link, you'll receive {config.REFERRAL_BONUS} token. It's a win-win! 🎉\n\n<code>{html.escape(ref_link)}</code>\n\nShare this link to new users only to get the token! 📢",
            reply_markup=await get_main_keyboard(user_id)
        )
        logger.info(f"User {user_id}: Referral link sent successfully.")
    except Exception as e:
        logger.error(f"User {user_id} failed to send referral link: {e}", exc_info=True)
        await handle_error(client, message, e)

@app.on_callback_query(filters.regex(r"^refer_and_earn_inline$"))
async def refer_and_earn_inline_callback(client: Client, callback_query: CallbackQuery):
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
    user_id = message.from_user.id
    logger.info(f"User {user_id} clicked Buy Token button.")

    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    create_tracked_task(check_premium_status_and_notify(client, user_id))

    try:
        await message.reply(get_premium_only_text(), reply_markup=buy_token_keyboard())
        logger.info(f"User {user_id}: Buy token message sent successfully.")
    except Exception as e:
        logger.error(f"User {user_id} failed to send buy token message: {e}", exc_info=True)
        await handle_error(client, message, e)

@app.on_message(filters.regex("^🔄 Refresh Token$") & filters.private)
async def refresh_token_btn(client: Client, message: Message):
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
        ad_code = str_to_b64(f"{user_id}:{get_current_time()}")
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
        await message.reply_text(
            f"💡 <b>Information</b>\nHere's how to get your token! 🚀\n\n"
            f"Hey 💕 <b>{user_mention_safe}</b>,\n\nYour Ads token is expired. Please refresh your token by clicking the button below and try again. 👇\n\n<b>Token Timeout:</b> {config.TOKEN_ACCESS_HOURS} hours ⏰\n\n<b>What is a token?</b>\nThis is an ads token. If you pass 1 ad, you can use the bot for {config.TOKEN_ACCESS_HOURS} hours after passing the ad. It's that simple! ✨\n\n<tg-spoiler>‼️ APPLE/IPHONE USERS: Copy the token link and open it in a Chrome browser for best experience. 🍎</tg-spoiler>",
            disable_web_page_preview = disable_preview,
            reply_markup=generate_token_earning_keyboard(ad_url)
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

async def send_token_earning_options(client: Client, message: Message, is_pending_content: bool = False):
    user_id = message.from_user.id
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
        long_url = f"https://t.me/{config.BOT_USERNAME[1:]}?start=token_{ad_code}"
        ad_url = await get_shortener_config_and_shorten_url(long_url)

        text = "❌ <b>No Tokens Left!</b> 😔\nUse any of these methods to gain tokens and continue watching spicy content! 👇"
        if is_pending_content:
            text = (
                "❌ <b>Token Required To View Content!</b>\n\n"
                "Once You Have Successfully Passed The Ads Verification, Click The Refresh Button Below To View The Content You Requested."
            )

        reply_markup = generate_token_earning_keyboard(ad_url, is_pending_content)

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

@app.on_callback_query(filters.regex(r"^share_(.+)$"))
async def share_callback(client: Client, callback_query: CallbackQuery):
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
            await client.send_video(
                chat_id,
                video=video['file_id'],
                caption=None,
                protect_content=False
            )
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

                await client.send_video(
                    chat_id,
                    video=new_file_id,
                    caption=None,
                    protect_content=False
                )
                await callback_query.answer("Download initiated! 🚀")
                logger.info(f"Premium user {user_id} successfully received download for video {video_uuid} after self-healing.")
            except Exception as heal_e:
                logger.error(f"Self-healing failed during download for video {video['uuid']}: {heal_e}", exc_info=True)
                await callback_query.answer("❌ Failed to send video for download. Please try again later. 😥", show_alert=True)
                return

    except Exception as e:
        logger.error(f"Error handling download for user {user_id}, video {video_uuid}: {e}", exc_info=True)
        await callback_query.answer("❌ Failed to send video for download. Please try again later. 😥", show_alert=True)


@app.on_callback_query(filters.regex(r"^bookmark_(.+)$"))
async def bookmark_video_callback(client: Client, callback_query: CallbackQuery):
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

    if not user_has_token(user_id):
        logger.info(f"User {user_id} has no tokens, prompting earning options for saved videos.")
        await send_token_earning_options(client, message)
        return

    user = users_collection.find_one({'user_id': user_id})
    if not user or not user.get('bookmarked_videos'):
        await message.reply("You haven't saved any videos yet. ❤️ Click 'Get Video' and then 'Bookmark' your favorites! ✨", reply_markup=await get_main_keyboard(user_id))
        return

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
                            force_new_message=False
                        )
                        if not sent_success:
                            await client.send_message(chat_id, "❌ Failed to load next saved video. Please try again. 😥")
                    else:
                        await client.send_message(chat_id, "The next saved video was not found. It may have been removed.😔")
                else:
                    await send_and_replace_message(
                        client,
                        chat_id,
                        message_id_to_edit_or_delete=callback_query.message.id,
                        new_message_type="text",
                        text_content="You have no more saved videos in this category. ❤️ Select another category or click '🎞️ Get Video' to find new ones!",
                        reply_markup=saved_category_keyboard(user_id)
                    )
            else:
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

@app.on_callback_query(filters.regex(r"^view_saved_video_(.+)$"))
async def view_saved_video_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id
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

    wait_msg = await callback_query.message.reply("Just a moment, checking your access...")
    if not user_has_token(user_id):
        await wait_msg.delete()
        await callback_query.answer("You need a token to watch this video. Please get a token first! 🧐", show_alert=True)
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
        force_new_message=False
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
    user_id = callback_query.from_user.id
    logger.info(f"User {user_id} cancelled clearing all saved videos.")

    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    await callback_query.message.edit_text("Operation cancelled. Your saved videos are safe! ✅")
    await callback_query.answer("Operation cancelled.")

@app.on_callback_query(filters.regex(r"^back_to_saved_cats$"))
async def back_to_saved_cats_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id
    logger.info(f"User {user_id} clicked 'Back' to saved categories menu.")

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

@app.on_message(filters.regex("^📱 Open App$") & filters.private)
async def open_app_btn(client: Client, message: Message):
    user_id = message.from_user.id
    logger.info(f"User {user_id} clicked 'Open App' button.")

    if not await check_membership(client, user_id):
        await send_force_subscribe_message(client, user_id)
        return

    if not user_has_token(user_id) and not is_premium_user(user_id):
        logger.info(f"User {user_id} has no tokens, cannot open Mini App.")
        await send_token_earning_options(client, message)
        return

    await message.reply(
        text="Click the button below to launch the full-screen video experience!",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🚀 Launch App", web_app=WebAppInfo(url=config.MINI_APP_URL))]]
        )
    )

# --- Admin Commands ---
@app.on_message(filters.command("getlink") & filters.private & admin_only & filters.reply)
async def get_link_cmd(client: Client, message: Message):
    admin_id = message.from_user.id
    replied_message = message.reply_to_message
    logger.info(f"Admin {admin_id} initiated /getlink.")

    if not DATA_CHANNEL_ID:
        await message.reply("❌ Data channel is not configured. Please set it with /setdata.")
        return

    if not (replied_message.video and replied_message.forward_from_chat and replied_message.forward_from_chat.id == DATA_CHANNEL_ID):
        await message.reply("❌ Please reply to a video that was forwarded directly from the data channel.")
        return

    try:
        file_unique_id = replied_message.video.file_unique_id
        video_doc = media_collection.find_one({"file_unique_id": file_unique_id})

        if not video_doc:
            await message.reply("❌ This video was not found in the bot's database.")
            return

        video_uuid = video_doc['uuid']
        share_link = f"https://t.me/{config.BOT_USERNAME[1:]}?start=video_{video_uuid}_{admin_id}"

        await message.reply(
            f"✅ Promotional link generated:\n\n<code>{html.escape(share_link)}</code>"
        )
    except Exception as e:
        logger.error(f"Error in /getlink for admin {admin_id}: {e}", exc_info=True)
        await message.reply("An error occurred while generating the link.")

@app.on_message(filters.command("broadcast") & filters.private & admin_only & filters.reply)
async def broadcast_cmd(client: Client, message: Message):
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

@app.on_message(filters.command("addcategory") & filters.private & admin_only)
async def addcategory_cmd(client: Client, message: Message):
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

        name = args[1].strip()
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

@app.on_message(filters.command("deletecategory") & filters.private & admin_only)
async def deletecategory_cmd(client: Client, message: Message):
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
    user_id = callback_query.from_user.id
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

@app.on_message(filters.command("addtoken") & filters.private & admin_only)
async def addtoken_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} requested to add token (premium).")
    try:
        args = message.text.split()
        if len(args) < 3:
            logger.warning(f"Admin {user_id} used addtoken with insufficient arguments: {message.text}")
            await message.reply("Usage: <code>/addtoken &lt;user_id&gt; &lt;duration_days&gt;</code>\nDuration is in days. 📝")
            return

        target_user_id = int(args[1])

        if target_user_id <= 0:
            logger.warning(f"Admin {user_id} provided invalid target user ID: {target_user_id}.")
            await message.reply("User ID must be a positive integer. 🔢")
            return

        duration_days = int(args[2])
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

@app.on_message(filters.command("removetoken") & filters.private & admin_only)
async def removetoken_cmd(client: Client, message: Message):
    admin_user_id = message.from_user.id
    logger.info(f"Admin {admin_user_id} requested to remove tokens.")
    try:
        args = message.text.split()
        if len(args) < 2:
            logger.warning(f"Admin {admin_user_id} used removetoken with insufficient arguments: {message.text}")
            await message.reply("Usage: <code>/removetoken &lt;user_id&gt;</code> 📝")
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

        result = tokens_collection.delete_one({'user_id': target_user_id})

        if result.deleted_count > 0:
            users_collection.update_one(
                {'user_id': target_user_id},
                {'$set': {'last_premium_check_status': False}}
            )
            logger.info(f"Admin {admin_user_id} removed all tokens for user {target_user_id}.")
            await message.reply(f"✅ All tokens and premium access for user <b>{target_user_id}</b> have been revoked.")

            try:
                await client.send_message(target_user_id, "⚠️ Your premium access and all active tokens have been revoked by an administrator.")
            except (UserIsBlocked, ChatInvalid):
                logger.warning(f"Could not notify user {target_user_id} about token removal; user blocked or chat invalid.")
            except Exception as notify_e:
                logger.error(f"Failed to notify user {target_user_id} about token removal: {notify_e}")
        else:
            await message.reply(f"User <b>{target_user_id}</b> had no active tokens to remove.")
            logger.info(f"Admin {admin_user_id} attempted to remove tokens, but user {target_user_id} had none.")

    except ValueError:
        logger.warning(f"Admin {admin_user_id} provided invalid input for removetoken: {message.text}")
        await message.reply("User ID must be a valid integer. 🔢")
    except Exception as e:
        logger.error(f"Admin {admin_user_id} error removing tokens: {e}", exc_info=True)
        await message.reply("❌ Failed to remove tokens. Please try again. 🐛")

# --- Batch Add Videos ---

async def process_batch_queue(user_id: int, client: Client):
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

    while queue and batch_add_state.get(user_id, {}).get('batch_mode'):
        message = queue.popleft()
        category = state['current_category']

        try:
            file_unique_id = message.video.file_unique_id
            if media_collection.find_one({"file_unique_id": file_unique_id}):
                await message.reply_text("⚠️ This video has already been added. Skipping.")
                continue

            sent_video_message = await client.send_video(
                chat_id=DATA_CHANNEL_ID, video=message.video.file_id,
                caption=f"Added by admin {user_id} for category {category}"
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

@app.on_message(filters.command("batchadd") & filters.private & admin_only)
async def batchadd_cmd(client: Client, message: Message):
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

@app.on_callback_query(filters.regex(r"^batchselcat_(.+)$"))
async def batch_select_category_callback(client: Client, callback_query: CallbackQuery):
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

@app.on_message(filters.command("done") & filters.private & admin_only)
async def done_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} exited batch add mode.")
    try:
        if user_id in batch_add_state and batch_add_state[user_id].get('batch_mode'):
            state = batch_add_state[user_id]
            total_added = state.get('videos_this_session', 0)
            remaining_in_queue = len(state.get('video_queue', []))
            del batch_add_state[user_id]

            reply_text = f"Batch add mode disabled. Added <b>{total_added}</b> videos in this session. 🎉"
            if remaining_in_queue > 0:
                reply_text += f"\n⚠️ <b>{remaining_in_queue}</b> videos were still in the queue and have not been processed."

            await message.reply(reply_text)
            logger.info(f"Admin {user_id}: Batch add mode disabled. Total videos added: {total_added}. Remaining in queue: {remaining_in_queue}.")
        else:
            await message.reply("You are not currently in batch add mode. Use /batchadd to start. 🚀")
            logger.warning(f"Admin {user_id} tried to use /done but not in batch mode.")
    except Exception as e:
        logger.error(f"Admin {user_id} failed to disable batch add mode: {e}", exc_info=True)
        await message.reply("❌ An error occurred while ending batch add mode. Please try again. 🐛")

@app.on_message(filters.video & filters.private & admin_only)
async def handle_video_for_admin_modes(client: Client, message: Message):
    user_id = message.from_user.id

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
                await message.reply_text(f"✅ Video (UUID: <code>{video_to_delete['uuid']}</code>) deleted.")
            else:
                await message.reply_text(f"❌ Failed to delete video (UUID: <code>{video_to_delete['uuid']}</code>).")
        except Exception as e:
            logger.error(f"Admin {user_id} error deleting video: {e}", exc_info=True)
            await message.reply("❌ An error occurred while deleting the video.")
        finally:
            del admin_delete_video_state[user_id]
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
        await message.reply_text(f"✅ Video queued for category <b>{html.escape(state['current_category'])}</b>. Position in queue: {len(state['video_queue'])}.")

        if not state.get('is_processing'):
            logger.info(f"Starting batch processing task for admin {user_id} as it was not running.")
            state['is_processing'] = True
            create_tracked_task(process_batch_queue(user_id, client))
        else:
            logger.info(f"Batch processing task for admin {user_id} is already running.")
        return

    logger.warning(f"Admin {user_id} sent video outside of any active admin mode, ignoring.")


@app.on_message(filters.command("category") & filters.private & admin_only)
async def set_category_cmd(client: Client, message: Message):
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
    user_id = callback_query.from_user.id
    logger.info(f"Admin {user_id} selected category for batch adding: {callback_query.data[7:]}.")
    try:
        match = re.match(r"^setcat_(.+)$", callback_query.data)
        if not match:
            await callback_query.answer("❌ Invalid category data. 🐛", show_alert=True)
            logger.warning(f"Admin {user_id} received invalid category data in setcat_callback: {callback_query.data}.")
            return
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
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"🗂️ {html.escape(cat)}", callback_data=f"setcat_{str_to_b64(cat)}")] for cat in get_categories()])
            )
            logger.warning(f"Admin {user_id} tried to set invalid category: '{category_name}'.")
            return

        last_video_in_category = media_collection.find_one(
            {'category': category_name},
            sort=[('sequence_number', DESCENDING)]
        )
        next_sequence_for_batch = 1
        if last_video_in_category and 'sequence_number' in last_video_in_category:
            next_sequence_for_batch = last_video_in_category['sequence_number'] + 1

        batch_add_state[user_id]['current_category'] = category_name
        batch_add_state[user_id]['next_sequence'] = next_sequence_for_batch

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

@app.on_message(filters.command("stats") & filters.private & admin_only)
async def stats_cmd(client: Client, message: Message):
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

@app.on_message(filters.command("addadmin") & filters.private & owner_only)
async def add_admin_cmd(client: Client, message: Message):
    owner_add_admin_state[message.from_user.id] = {'step': 'await_user_id'}
    await message.reply("Please send the <b>User ID</b> of the user you want to add as an admin. 📝")

@app.on_message(filters.command("removeadmin") & filters.private & owner_only)
async def remove_admin_cmd(client: Client, message: Message):
    buttons = []
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

@app.on_message(filters.command("deleteuser") & filters.private & admin_only)
async def deleteuser_cmd(client: Client, message: Message):
    admin_user_id = message.from_user.id
    logger.info(f"Admin {admin_user_id} initiated /deleteuser command.")
    admin_delete_user_state[admin_user_id] = {'step': 'await_user_id'}
    await message.reply("Please send the <b>User ID</b> of the user you want to permanently delete from the database. 📝\n\n⚠️ This action is irreversible and will delete all their data, including tokens and history.")

@app.on_callback_query(filters.regex(r"^rem_admin_(\d+)$"))
async def remove_admin_callback(client: Client, callback_query: CallbackQuery):
    if not is_owner(callback_query.from_user.id):
        await callback_query.answer("You are not authorized to perform this action.", show_alert=True)
        return

    try:
        admin_id_to_remove = int(callback_query.data.split("_")[2])
        if admin_id_to_remove in BOT_ADMINS:
            BOT_ADMINS.remove(admin_id_to_remove)
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

@app.on_message(filters.command("setshortener") & filters.private & admin_only)
async def set_shortener_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} initiated /setshortener command.")
    admin_shortener_setup_state[user_id]['step'] = 'await_template_url'
    await message.reply(
        "Please send the <b>full template URL</b> for your URL shortener API.\n\n"
        "It must include `http://` or `https://` and contain `{long_url}` as a placeholder for the URL to be shortened, and an `api=` parameter with your API key.\n\n"
        "<b>Example:</b> `https://get2short.com/st?api=YOUR_API_KEY&url={long_url}`\n\n"
        "If your shortener doesn't use `api=` in the URL, provide the full API endpoint URL that accepts the long URL as a parameter (e.g., `https://api.shortener.com/shorten?url={long_url}&key=YOUR_API_KEY`)."
    )

@app.on_message(filters.command("deletevideo") & filters.private & admin_only)
async def deletevideo_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} initiated /deletevideo command.")
    if not DATA_CHANNEL_ID:
        await message.reply("❌ Video storage channel is not configured. Please set it using /setdata first.")
        return
    admin_delete_video_state[user_id] = True
    await message.reply("Send the <b>video file from the database</b> to delete it. This must be the original video file, not a forwarded one. 🎥")

@app.on_message(filters.command("batchvideoadd") & filters.private & admin_only)
async def batch_video_add_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    if not DATA_CHANNEL_ID:
        await message.reply("❌ Video storage channel is not configured. Please set it using /setdata first.")
        return
    admin_batch_link_state[user_id] = []
    await message.reply(
        "You are now in <b>Batch Video Link Creation Mode</b>.\n\n"
        "1. Forward videos from your database channel to me.\n"
        "2. When you are finished, send /createbatchlink to generate the shareable link."
    )

@app.on_message(filters.command("createbatchlink") & filters.private & admin_only)
async def create_batch_link_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in admin_batch_link_state or not admin_batch_link_state[user_id]:
        await message.reply("You haven't added any videos to the batch. Forward some videos first, then use this command.")
        return

    video_uuids = admin_batch_link_state[user_id]
    batch_id = str(uuid.uuid4())

    video_batches_collection.insert_one({
        "batch_id": batch_id,
        "video_uuids": video_uuids,
        "created_by": user_id,
        "created_at": datetime.utcnow()
    })

    share_link = f"https://t.me/{config.BOT_USERNAME[1:]}?start=batch_{batch_id}"

    await message.reply(
        f"✅ Batch link created successfully for <b>{len(video_uuids)}</b> videos!\n\n"
        f"Share this link:\n`{share_link}`"
    )
    del admin_batch_link_state[user_id]

@app.on_message(filters.command("categoryrename") & filters.private & admin_only)
async def categoryrename_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    logger.info(f"Admin {user_id} initiated /categoryrename command.")
    admin_rename_category_state[user_id] = {'step': 'await_old_name'}
    await message.reply("Please send the <b>current name</b> of the category you want to rename. 📝")

@app.on_message(filters.command("setfsub") & filters.private & admin_only)
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

@app.on_callback_query(filters.regex(r"^addfsub_step1$"))
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

@app.on_callback_query(filters.regex(r"^viewfsub_(-?\d+)$"))
async def view_fsub_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if not is_admin(user_id):
        await callback_query.answer("❌ Not authorized.", show_alert=True)
        return
    
    channel_id = int(callback_query.data.split('_')[1])
    channel_info = next((c for c in FORCE_SUB_CHANNELS if c['channel_id'] == channel_id), None)

    if not channel_info:
        await callback_query.answer("Channel not found in configuration.", show_alert=True)
        await set_fsub_cmd(client, callback_query.message)
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

@app.on_callback_query(filters.regex(r"^removefsub_(-?\d+)$"))
async def remove_fsub_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if not is_admin(user_id):
        await callback_query.answer("❌ Not authorized.", show_alert=True)
        return
    
    channel_id = int(callback_query.data.split('_')[1])
    
    result = force_sub_channels_collection.delete_one({'channel_id': channel_id})
    if result.deleted_count > 0:
        await load_force_sub_channels()
        await callback_query.answer("Channel removed successfully!", show_alert=True)
        await set_fsub_cmd(client, callback_query.message)
        logger.info(f"Admin {user_id} removed force sub channel: {channel_id}")
    else:
        await callback_query.answer("Channel not found in database.", show_alert=True)
        await set_fsub_cmd(client, callback_query.message)

@app.on_callback_query(filters.regex(r"^back_to_fsub_list$"))
async def back_to_fsub_list_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if not is_admin(user_id):
        await callback_query.answer("❌ Not authorized.", show_alert=True)
        return
    
    await set_fsub_cmd(client, callback_query.message)
    await callback_query.answer()

@app.on_message(filters.command("setdata") & filters.private & admin_only)
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

@app.on_callback_query(filters.regex(r"^setdatachannel_step1$"))
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

@app.on_callback_query(filters.regex(r"^removedatachannel$"))
async def remove_data_channel_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if not is_admin(user_id):
        await callback_query.answer("❌ Not authorized.", show_alert=True)
        return
    
    result = data_channel_collection.delete_one({'_id': 'data_channel'})
    if result.deleted_count > 0:
        await load_data_channel_id()
        await callback_query.answer("Data channel removed successfully!", show_alert=True)
        await set_data_cmd(client, callback_query.message)
        logger.info(f"Admin {user_id} removed data channel.")
    else:
        await callback_query.answer("No data channel found to remove.", show_alert=True)
        await set_data_cmd(client, callback_query.message)


@app.on_message(filters.text & filters.private)
async def handle_text_input(client: Client, message: Message):
    user_id = message.from_user.id
    text_input = message.text.strip()

    if is_owner(user_id):
        if user_id in owner_add_admin_state and owner_add_admin_state[user_id].get('step') == 'await_user_id':
            try:
                user_id_to_add = int(text_input)
                if user_id_to_add in BOT_ADMINS:
                    await message.reply("This user is already an admin.")
                    return

                BOT_ADMINS.add(user_id_to_add)
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

    if is_admin(user_id):
        if user_id in admin_delete_user_state and admin_delete_user_state[user_id].get('step') == 'await_user_id':
            try:
                user_id_to_delete = int(text_input)

                if is_owner(user_id_to_delete):
                    await message.reply("❌ You cannot delete the bot owner.")
                    return

                if is_admin(user_id_to_delete):
                    await message.reply("❌ You cannot delete another admin. Please remove them from admin status first using /removeadmin.")
                    return

                user_deleted = users_collection.delete_one({'user_id': user_id_to_delete})
                tokens_deleted = tokens_collection.delete_one({'user_id': user_id_to_delete})
                history_deleted = history_collection.delete_one({'user_id': user_id_to_delete})

                if user_deleted.deleted_count > 0:
                    await message.reply(f"✅ Successfully deleted user {user_id_to_delete} from the database.\n"
                                      f"- User record deleted: {user_deleted.deleted_count > 0}\n"
                                      f"- Tokens record deleted: {tokens_deleted.deleted_count > 0}\n"
                                      f"- History record deleted: {history_deleted.deleted_count > 0}")
                    logger.info(f"Admin {user_id} successfully deleted user {user_id_to_delete}.")
                else:
                    await message.reply(f"🤷 User {user_id_to_delete} not found in the database.")
                    logger.warning(f"Admin {user_id} tried to delete non-existent user {user_id_to_delete}.")

            except ValueError:
                await message.reply("Invalid User ID. Please send a valid integer ID.")
            except Exception as e:
                await message.reply(f"An error occurred: {e}")
                logger.error(f"Error in /deleteuser flow: {e}")
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

            if current_step == 'await_old_name':
                old_name = text_input
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
        
        if user_id in admin_fsub_state and admin_fsub_state[user_id].get('step') == 'await_channel_id':
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
                    'added_at': datetime.utcnow()
                })
                await load_force_sub_channels()
                await message.reply(f"✅ Channel '<b>{html.escape(channel_name)}</b>' (<code>{channel_id}</code>) added to force subscribe list.")
                logger.info(f"Admin {user_id} added force sub channel: {channel_id}")

            except Exception as e:
                await message.reply(f"An error occurred: {e}")
                logger.error(f"Error in /setfsub flow: {e}")
            finally:
                del admin_fsub_state[user_id]
            return

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
                    me = await client.get_me()
                    member = await client.get_chat_member(channel_id, me.id)
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
                    {'$set': {'channel_id': channel_id, 'name': channel_name, 'set_by': user_id, 'set_at': datetime.utcnow()}},
                    upsert=True
                )
                await load_data_channel_id()
                await message.reply(f"✅ Video storage channel set to '<b>{html.escape(channel_name)}</b>' (<code>{channel_id}</code>).")
                logger.info(f"Admin {user_id} set data channel: {channel_id}")

            except Exception as e:
                await message.reply(f"An error occurred: {e}")
                logger.error(f"Error in /setdata flow: {e}")
            finally:
                del admin_data_channel_state[user_id]
            return

    logger.debug(f"User {user_id} sent text message '{message.text}' not part of any active multi-step command. Ignoring.")


@app.on_message(filters.command('toggle_auto_delete') & filters.private & admin_only)
async def toggle_auto_delete(client: Client, message: Message):
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

@app.on_message(filters.command('toggle_protect') & filters.private & admin_only)
async def toggle_protect(client: Client, message: Message):
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

async def cleanup_expired_data():
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
                        "Your menu has expired due to inactivity. Please click '🎞️ Get Video' to get a new one. ⏰"
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

async def verify_and_cleanup_media():
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
                    await app.get_messages(DATA_CHANNEL_ID, message_id_in_channel)
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

async def health_check():
    try:
        me = await app.get_me()
        logger.info(f"Bot username: {me.username}")

        if DATA_CHANNEL_ID:
            try:
                member = await app.get_chat_member(DATA_CHANNEL_ID, me.id)
                logger.info(f"Bot status in data channel ({DATA_CHANNEL_ID}): {member.status}")
            except Exception as e:
                logger.error(f"Health check failed for data channel {DATA_CHANNEL_ID}: {e}", exc_info=True)
        else:
            logger.warning("No data channel configured. Skipping data channel health check.")

        if FORCE_SUB_CHANNELS:
            for channel_info in FORCE_SUB_CHANNELS:
                try:
                    force_sub_member = await app.get_chat_member(channel_info['channel_id'], me.id)
                    logger.info(f"Bot status in force subscribe channel ({channel_info['channel_id']}): {force_sub_member.status}")
                except Exception as e:
                    logger.error(f"Health check failed for force subscribe channel {channel_info['channel_id']}: {e}", exc_info=True)
        else:
            logger.warning("No force subscribe channels configured. Skipping force sub health check.")

    except Exception as e:
        logger.error(f"Overall health check failed: {e}", exc_info=True)

@fastapi_app.on_event("startup")
async def startup_event():
    logger.info("FastAPI server is starting up...")

    await app.start()
    logger.info("Pyrogram client started.")

    SESSION_STRING = get_session_string()
    if not SESSION_STRING:
        logger.info("Saving session string to DB for future runs...")
        new_session_string = await app.export_session_string()
        set_session_string(new_session_string)

    await load_admins_from_db()
    await load_data_channel_id()
    await load_force_sub_channels()
    await health_check()
    create_tracked_task(cleanup_expired_data())
    create_tracked_task(verify_and_cleanup_media())
    create_tracked_task(cleanup_expired_menus())
    logger.info("Background tasks initiated. Bot is now fully operational.")


@fastapi_app.on_event("shutdown")
async def shutdown_event():
    logger.info("FastAPI server is shutting down...")
    await app.stop()
    logger.info("Pyrogram client stopped.")
