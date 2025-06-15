# Spicy Nyraa Bot - Main Script
import os
import asyncio
import uuid
import base64
import random
import logging
from datetime import datetime, timedelta
from pyrogram import Client, filters
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, Message, InlineQueryResultArticle, InputTextMessageContent
)
from pyrogram.errors import UserIsBlocked, ChatInvalid, MessageIdInvalid, UserNotParticipant, FloodWait
from pymongo import MongoClient, ASCENDING, ReturnDocument
import aiohttp
from config import *
from collections import defaultdict
import re
import html # Import the html module

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Configuration ---
import os

class BotConfig:
    BOT_TOKEN = os.getenv('BOT_TOKEN', '7646433933:AAF5iWb7rngRe1Tpxkc252hL0wm-FtZJA4U')
    API_ID = int(os.getenv('API_ID', 29800015))
    API_HASH = os.getenv('API_HASH', 'c8f37108be31ab9ea2818bfe533fbb6f')
    BOT_USERNAME = os.getenv('BOT_USERNAME', '@SpicyNyraa_bot')
    MONGO_URI = os.getenv('MONGO_URI', 'mongodb+srv://Pyasipriya:00pEcao9sYhNC5VQ@cluster0.2dfenf7.mongodb.net/spicybot?retryWrites=true&w=majority&appName=Cluster0')
    MONGO_DB_NAME = os.getenv('MONGO_DB_NAME', 'spicybot')
    CHANNEL_ID = int(os.getenv('CHANNEL_ID', -1001234567890))
    CHANNEL_INVITE_LINK = os.getenv('CHANNEL_INVITE_LINK', 'https://t.me/SpicyNyraa')
    VIDEO_CHANNEL_ID = int(os.getenv('VIDEO_CHANNEL_ID', -1002626689003))
    BUY_BOT_URL = os.getenv('BUY_BOT_URL', 'https://t.me/hanielxsupportbot')
    ADMIN_IDS = [int(i) for i in os.getenv('ADMIN_IDS', '6612030110').split(',')]
    URL_SHORTENER = os.getenv('URL_SHORTENER', 'https://api.linkshortify.com/st')
    SHORTENER_API_KEY = os.getenv('SHORTENER_API_KEY', '5cd923c490f64017cffa6e3bb6cc724560a8cfc6')
    TUTORIAL_LINK_2 = os.getenv('TUTORIAL_LINK_2', 'https://t.me/urlshortenertutorial')
    TOKEN_EXPIRY = int(os.getenv('TOKEN_EXPIRY', 86400))  # 24 hours in seconds
    DEFAULT_CATEGORY = os.getenv('DEFAULT_CATEGORY', 'default')
    # Customization options
    NEW_USER_TOKENS = int(os.getenv('NEW_USER_TOKENS', 3))
    REFERRAL_BONUS = int(os.getenv('REFERRAL_BONUS', 1))
    REFRESH_BONUS = int(os.getenv('REFRESH_BONUS', 1))

try:
    config = BotConfig()
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
users_collection.create_index([("user_id", ASCENDING)])
tokens_collection.create_index([("user_id", ASCENDING)])
media_collection.create_index([("uuid", ASCENDING)])
media_collection.create_index([("category", ASCENDING)])
media_collection.create_index([("file_unique_id", ASCENDING)])
media_collection.create_index([("size_bytes", ASCENDING)])
history_collection.create_index([("user_id", ASCENDING)])
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
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(config.URL_SHORTENER, json={
                'api': config.SHORTENER_API_KEY,
                'url': long_url
            }, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('shortenedUrl'):
                        return data['shortenedUrl']
        logger.warning(f"URL shortening failed for {long_url}")
        return long_url
    except Exception as e:
        logger.error(f"Error shortening URL: {e}")
        return long_url

# --- Token Management ---
def get_valid_tokens(user_id: int):
    doc = tokens_collection.find_one({'user_id': user_id})
    if not doc:
        return []
    now = datetime.utcnow()
    return [t for t in doc['tokens'] if t['expires_at'] > now]

def add_token(user_id: int, duration=config.TOKEN_EXPIRY):
    now = datetime.utcnow()
    expires = now + timedelta(seconds=duration)
    token = {
        'token_id': str(uuid.uuid4()),
        'created_at': now,
        'expires_at': expires
    }
    tokens_collection.update_one(
        {'user_id': user_id},
        {'$push': {'tokens': token}},
        upsert=True
    )
    return token

def get_and_cleanup_tokens(user_id: int):
    """
    Atomically removes expired tokens and returns the list of valid tokens.
    """
    now = datetime.utcnow()
    
    # Remove expired tokens and retrieve the updated document
    result = tokens_collection.find_one_and_update(
        {'user_id': user_id},
        {'$pull': {'tokens': {'expires_at': {'$lt': now}}}},
        return_document=ReturnDocument.AFTER, # Return the document after the update
        upsert=True # Create if not exists to ensure document is there for initial push
    )
    
    if result and result.get('tokens'):
        return result['tokens']
    return []

def user_has_token(user_id: int):
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
    try:
        member = await client.get_chat_member(config.CHANNEL_ID, user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception:
        return False

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
    history_collection.update_one(
        {'user_id': user_id},
        {'$push': {'history': {'video_uuid': video_uuid, 'category': category, 'viewed_at': now}}},
        upsert=True
    )

def get_last_video(user_id: int):
    doc = history_collection.find_one({'user_id': user_id})
    if doc and doc.get('history'):
        return doc['history'][-2] if len(doc['history']) > 1 else None
    return None

# --- Menu State Management ---
active_menus = {}
MENU_TIMEOUT = 1800  # 30 minutes

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
# Cache subscription status
subscription_cache = {}
SUBSCRIPTION_CACHE_TTL = 60  # 1 minutes

async def check_subscription_cached(client: Client, user_id: int) -> bool:
    """Check subscription status with caching"""
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
    except Exception:
        return False

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

def join_channel_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Join Channel", url=config.CHANNEL_INVITE_LINK)],
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
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Buy Token", url=config.BUY_BOT_URL)]
    ])

# --- Video Sharing ---
async def handle_shared_video(client, user_id, video_uuid, message_id=None):
    video = get_video_by_uuid(video_uuid)
    if not video:
        return False, "Oops, invalid link. Try again!"
    
    if not user_has_token(user_id):
        return False, await send_token_earning_options(client, message_id)
        
    if not await check_subscription(client, user_id):
        return False, "Join the channel to watch!", join_channel_keyboard()
    
    save_history(user_id, video_uuid, video['category'])
    return True, video

# --- Token Refresh ---
async def handle_token_refresh(user_id: int, ad_code: str):
    try:
        if is_rate_limited(user_id):
            return False, "⚠️ You're refreshing too quickly. Please wait a minute and try again."
            
        decoded = b64_to_str(ad_code)
        if not decoded:
            return False, "Oops, invalid link. Try again!"
        
        try:
            code_user_id, timestamp = map(int, decoded.split(':'))
        except ValueError:
            logger.error(f"Invalid token refresh code format: {ad_code}")
            return False, "Invalid token refresh link format."
            
        if code_user_id != user_id:
            return False, "This token refresh link is not for you."
            
        if timestamp < get_current_time():
            return False, "This token refresh link has expired."
            
        add_token(user_id)
        logger.info(f"Token added for user {user_id} via refresh")
        return True, "Congratulations! You got 1 token. Each token lasts 24 hours."
    except Exception as e:
        logger.error(f"Token refresh failed for user {user_id}: {e}")
        return False, "Something went wrong with token refresh. Please try again."

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
        return False, "Failed to send video. Please try again later." # Return failure and an error message

# --- Rate Limiting ---
# In-memory defaultdict for rate limiting (will be replaced by MongoDB)
# rate_limits = defaultdict(list)
RATE_LIMIT_WINDOW = 60  # 1 minute
RATE_LIMIT_MAX = 5  # 5 requests per minute

async def is_rate_limited(user_id: int) -> bool:
    now = datetime.utcnow()
    
    # Atomically remove old entries and get the current count
    rate_limit_doc = tokens_collection.find_one_and_update(
        {'user_id': user_id},
        {
            '$pull': {'rate_limits': {'timestamp': {'$lt': now - timedelta(seconds=RATE_LIMIT_WINDOW)}}},
            '$push': {'rate_limits': {'timestamp': now}}
        },
        return_document=ReturnDocument.AFTER, # Return the document after the update
        upsert=True
    )
    
    # Check limit based on the size of the 'rate_limits' array
    if rate_limit_doc and len(rate_limit_doc.get('rate_limits', [])) > RATE_LIMIT_MAX:
        return True
    return False

# --- Error Handling ---
async def handle_error(client: Client, message: Message, error: Exception):
    if isinstance(error, UserNotParticipant):
        return
    elif isinstance(error, FloodWait):
        logger.warning(f"FloodWait: {error.value} seconds")
        await message.reply_text(f"⚠️ Too many requests. Please wait {error.value} seconds.")
    else:
        logger.error(f"An error occurred: {error}", exc_info=True)
        await message.reply_text(f"❌ An unexpected error occurred. Please try again later.")

# --- Handlers ---
@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message: Message):
    user_id = message.from_user.id
    
    # Rate limiting
    if is_rate_limited(user_id):
        await handle_error(client, message, FloodWait(10))
        return
    
    try:
        user = users_collection.find_one({'user_id': user_id})
        args = message.text.split()
        
        # Handle first-time users and referrals
        if not user:
            users_collection.insert_one({
                'user_id': user_id,
                'username': message.from_user.username,
                'first_name': message.from_user.first_name,
                'last_name': message.from_user.last_name,
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
                    logger.info(f"User {user_id} referred by {referrer_id}")
        
        # Handle shared video or token refresh
        if len(args) > 1:
            arg = args[1]
            
            # Handle token refresh
            if arg.startswith('token_'):
                success, msg = await handle_token_refresh(user_id, arg[6:])
                await message.reply(msg)
                if success:
                    await message.reply(
                        "Click on Get Video to watch spicy content.",
                        reply_markup=await get_main_keyboard(user_id)
                    )
                return
                
            # Handle video share
            video_uuid = arg
            logger.info(f"User {user_id} attempting to view shared video {video_uuid}")
            
            if not media_collection.find_one({'uuid': video_uuid}):
                logger.warning(f"Invalid shared video UUID {video_uuid} attempted by user {user_id}")
                await handle_error(client, message, ValueError("Invalid video link"))
                return
                
            success, result = await handle_shared_video(client, user_id, video_uuid)
            if not success:
                if isinstance(result, tuple):
                    await message.reply(result[0], reply_markup=result[1])
                else:
                    await message.reply(result)
                return
                
            video = result
            if await is_menu_active(client, user_id, message.chat.id):
                try:
                    # Delete old menu first
                    old_menu = active_menus.get(user_id)
                    if old_menu and old_menu.get('chat_id'):
                        try:
                            await client.delete_messages(old_menu['chat_id'], old_menu['message_id'])
                            logger.info(f"Deleted old menu message {old_menu['message_id']} for user {user_id}")
                        except Exception as e:
                            logger.warning(f"Failed to delete old menu message: {e}")
                    
                    # Send new video
                    sent_success, sent_message_or_error = await send_video_with_auto_delete(
                        client,
                        message.chat.id,
                        video,
                        reply_markup=video_nav_keyboard(video['uuid'], video['category'])
                    )
                    if sent_success:
                        save_history(user_id, video['uuid'], video['category'])
                        set_active_menu(user_id, sent_message_or_error.id)
                        await message.reply("Video updated in your active menu.")
                        logger.info(f"Updated menu with shared video {video_uuid} for user {user_id}")
                    else:
                        await message.reply(sent_message_or_error)

                except Exception as e:
                    logger.error(f"Failed to update menu with shared video: {e}")
                    await handle_error(client, message, e)
            else:
                # Send as new message
                sent_success, sent_message_or_error = await send_video_with_auto_delete(
                    client,
                    message.chat.id,
                    video,
                    reply_markup=video_nav_keyboard(video['uuid'], video['category'])
                )
                if sent_success:
                    save_history(user_id, video['uuid'], video['category'])
                    set_active_menu(user_id, sent_message_or_error.id)
                    logger.info(f"Sent shared video {video_uuid} as new menu for user {user_id}")
                else:
                    await message.reply(sent_message_or_error)
        
        if not user:
            await message.reply(
                f"dear {message.from_user.mention} This is Spicy Nyraa Bot. To watch spicy content, click on the Get Video button. Need help? Tap /help.",
                reply_markup=await get_main_keyboard(user_id)
            )
        else:
            await message.reply(
                "This is Spicy Nyraa Bot. Click on Get Video to watch spicy content.",
                reply_markup=await get_main_keyboard(user_id)
            )
            
    except Exception as e:
        logger.error(f"Error in start command: {e}")
        await handle_error(client, message, e)

@app.on_message(filters.command("help") & filters.private)
async def help_cmd(client, message: Message):
    await message.reply(
        f"dear {message.from_user.mention} this is how to use spicy nyraa.\n\n"
        "- Use Get Video to watch spicy content.\n"
        "- Each token gives you 24 hours access.\n"
        "- Earn tokens by referral, refresh, or buy.\n"
        "- Join the channel to access videos.\n"
        "- Use /profile to check your stats.",
        reply_markup=await get_main_keyboard(message.from_user.id)
    )

@app.on_message(filters.command("profile") & filters.private)
async def profile_cmd(client, message: Message):
    user_id = message.from_user.id
    user = users_collection.find_one({'user_id': user_id})
    tokens = get_valid_tokens(user_id)
    referral_count = user.get('referral_count', 0) if user else 0
    referred_by = user.get('referred_by', None) if user else None
    views = history_collection.find_one({'user_id': user_id})
    view_count = len(views['history']) if views and 'history' in views else 0
    ref_link = f"https://t.me/{config.BOT_USERNAME[1:]}?start=ref_{user_id}"
    
    # Sanitize user's first name and username for HTML
    sanitized_first_name = html.escape(message.from_user.first_name if message.from_user.first_name else '')
    sanitized_username = html.escape(message.from_user.username if message.from_user.username else '')

    await message.reply(f"<b>Profile</b>\n\nTokens: <b>{len(tokens)}</b>\nVideo Views: <b>{view_count}</b>\nReferrals: <b>{referral_count}</b>\nReferral Link: <code>{ref_link}</code>\n{'Referred by: ' + str(referred_by) if referred_by else ''}", reply_markup=referral_keyboard(ref_link))

@app.on_message(filters.regex("^Get Video$") & filters.private)
async def get_video(client, message: Message):
    user_id = message.from_user.id
    if not await check_subscription_cached(client, user_id):
        await message.reply("Join the channel to watch!", reply_markup=join_channel_keyboard())
        return
    if not user_has_token(user_id):
        await send_token_earning_options(client, message)
        return
    if await is_menu_active(client, user_id, message.chat.id):
        await message.reply("Scroll up, your menu is already open.")
        return
    cats = get_categories()
    if not cats:
        add_category(config.DEFAULT_CATEGORY)
        cats = [config.DEFAULT_CATEGORY]
    await message.reply("Choose a category:", reply_markup=category_keyboard())

@app.on_callback_query(filters.regex(r"^cat_(.+)"))
async def select_category(client, callback_query):
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id
    
    if is_rate_limited(user_id):
        await callback_query.answer("⚠️ You're changing categories too quickly. Please wait a minute and try again.", show_alert=True)
        logger.warning(f"User {user_id} hit rate limit in select_category")
        return
        
    # Check for active menu
    if await is_menu_active(client, user_id, chat_id):
        await callback_query.message.reply(
            "You already have an active menu. Please use that one or wait for it to expire."
        )
        return
        
    category = callback_query.data[4:]
    
    # Ensure category exists
    if category not in get_categories():
        category = config.DEFAULT_CATEGORY
        logger.warning(f"Invalid category {category}, falling back to default")
    
    video = get_random_video(category)
    if not video:
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
            reply_markup=video_nav_keyboard(video['uuid'], category)
        )
        
        if sent_success:
            save_history(user_id, video['uuid'], category)
            set_active_menu(user_id, sent_message_or_error.id)
            await callback_query.message.delete()
            logger.info(f"User {user_id} selected category {category}")
        else:
            await callback_query.message.edit_text(
                sent_message_or_error,
                reply_markup=category_keyboard()
            )
    except Exception as e:
        logger.error(f"Error sending video: {e}")
        await callback_query.message.edit_text(
            "❌ Something went wrong. Please try again.",
            reply_markup=category_keyboard()
        )

@app.on_callback_query(filters.regex(r"^next_(.+)_(.+)$"))
async def next_video(client, callback_query):
    try:
        user_id = callback_query.from_user.id
        _, current_uuid, category = callback_query.data.split('_')
        video = get_random_video(category)
        
        if not video:
            await callback_query.answer("No videos in this category. Try another!", show_alert=True)
            return
        
        try:
            sent_success, sent_message_or_error = await send_video_with_auto_delete(
                client,
                callback_query.message.chat.id,
                video,
                reply_markup=video_nav_keyboard(video['uuid'], category)
            )
            
            if sent_success:
                save_history(user_id, video['uuid'], category)
                set_active_menu(user_id, sent_message_or_error.id)
                await callback_query.message.delete()
            else:
                await callback_query.answer(sent_message_or_error, show_alert=True)
        except MessageIdInvalid:
            # If edit fails, send as new message
            sent_success, sent_message_or_error = await send_video_with_auto_delete(
                client,
                callback_query.message.chat.id,
                video,
                reply_markup=video_nav_keyboard(video['uuid'], category)
            )
            if sent_success:
                save_history(user_id, video['uuid'], category)
                set_active_menu(user_id, sent_message_or_error.id)
            else:
                await callback_query.answer(sent_message_or_error, show_alert=True)
    except Exception as e:
        logger.error(f"Error in next_video: {e}")
        await callback_query.answer("Something went wrong. Please try again.", show_alert=True)

@app.on_callback_query(filters.regex(r"^prev_(.+)_(.+)$"))
async def prev_video(client, callback_query):
    try:
        user_id = callback_query.from_user.id
        _, current_uuid, category_hint = callback_query.data.split('_') # Use category_hint as it might not be the actual category of the prev video
        history_doc = history_collection.find_one({'user_id': user_id})
        
        if not history_doc or not history_doc.get('history'):
            await callback_query.answer(
                "No previous videos available in your history. Try 'Get Video' to start!",
                show_alert=True
            )
            return
            
        history_entries = history_doc['history']
        
        found_video = None
        found_category = None
        # Iterate in reverse to find the most recent valid previous video
        for entry in reversed(history_entries):
            # Skip the current video
            if entry['video_uuid'] == current_uuid:
                continue
            
            video = media_collection.find_one({'uuid': entry['video_uuid']})
            if video:
                found_video = video
                found_category = entry['category'] # Use the category from history for navigation
                break # Found a valid previous video
        
        if not found_video:
            await callback_query.answer(
                "Could not find any valid previous videos in your history. Some videos might have been deleted.",
                show_alert=True
            )
            return
            
        # Delete old menu before sending new one
        try:
            await callback_query.message.delete()
        except Exception as e:
            logger.error(f"Failed to delete old menu message for user {user_id}: {e}")
        
        sent_success, sent_message_or_error = await send_video_with_auto_delete(
            client,
            callback_query.message.chat.id,
            found_video,
            reply_markup=video_nav_keyboard(found_video['uuid'], found_category)
        )
        
        if sent_success:
            save_history(user_id, found_video['uuid'], found_category)
            set_active_menu(user_id, sent_message_or_error.id)
            logger.info(f"User {user_id} navigated to previous video {found_video['uuid']} in category {found_category}")
        else:
            await callback_query.answer(
                sent_message_or_error,
                show_alert=True
            )
    except Exception as e:
        logger.error(f"Error in prev_video for user {user_id}: {e}")
        await callback_query.answer(
            "An unexpected error occurred while trying to go to the previous video. Please try again.",
            show_alert=True
        )

@app.on_callback_query(filters.regex(r"^change_cat$"))
async def change_category(client, callback_query):
    await callback_query.message.edit_text("Choose a category:", reply_markup=category_keyboard())

@app.on_message(filters.regex("^Profile$") & filters.private)
async def profile_btn(client, message: Message):
    await profile_cmd(client, message)

@app.on_message(filters.regex("^Refer & Earn$") & filters.private)
async def refer_btn(client, message: Message):
    user_id = message.from_user.id
    ref_link = f"https://t.me/{config.BOT_USERNAME[1:]}?start=ref_{user_id}"
    await message.reply(f"Share this link to earn tokens!\n<code>{ref_link}</code>", reply_markup=referral_keyboard(ref_link))

@app.on_message(filters.regex("^Buy Token$") & filters.private)
async def buy_token_btn(client, message: Message):
    await message.reply("Buy tokens from our support bot.", reply_markup=buy_token_keyboard())

@app.on_message(filters.regex("^Refresh Token$") & filters.private)
async def refresh_token_btn(client, message: Message):
    user_id = message.from_user.id
    logger.info(f"User {user_id} requested token refresh")

    if is_rate_limited(user_id):
        await message.reply_text("⚠️ You're refreshing too quickly. Please wait a minute and try again.")
        logger.warning(f"User {user_id} hit rate limit in refresh_token_btn")
        return

    temp_msg = await message.reply("Please wait...")
    ad_code = str_to_b64(f"{user_id}:{str(get_current_time() + config.TOKEN_EXPIRY)}")
    ad_url = await shorten_url(f"https://telegram.dog/{client.username}?start=token_{ad_code}")
    await temp_msg.delete()

    disable_preview = False
    if ad_url.startswith(f"https://telegram.dog/{client.username}"):
        logger.warning(f"URL shortening failed for user {user_id}. Using long URL: {ad_url}")
        disable_preview = True # Disable preview for long Telegram links

    await message.reply_text(
        f"Hey 💕 <b>{message.from_user.mention}</b> \n\nYour Ads token is expired, refresh your token and try again. \n\n<b>Token Timeout:</b> 24 hour \n\n<b>What is token?</b> \nThis is an ads token. If you pass 1 ad, you can use the bot for 24 hour after passing the ad. \n\nAPPLE/IPHONE USERS COPY TOKEN LINK AND OPEN IN CHROME BROWSER</b>",
        disable_web_page_preview = disable_preview,
        reply_markup=token_earning_keyboard(ad_url)
    )

async def send_token_earning_options(client: Client, message: Message):
    user_id = message.from_user.id
    if is_rate_limited(user_id):
        await message.reply_text("⚠️ You're requesting token options too quickly. Please wait a minute and try again.")
        logger.warning(f"User {user_id} hit rate limit in send_token_earning_options")
        return

    ad_code = str_to_b64(f"{user_id}:{get_current_time() + config.TOKEN_EXPIRY}")
    long_url = f"https://telegram.dog/{config.BOT_USERNAME[1:]}?start=token_{ad_code}"
    ad_url = await shorten_url(long_url)
    
    disable_preview = False
    if ad_url.startswith(f"https://telegram.dog/{client.username}"):
        logger.warning(f"URL shortening failed for user {user_id} in send_token_earning_options. Using long URL: {ad_url}")
        disable_preview = True

    await message.reply(
        "You have no tokens left. Use any of these methods to gain tokens:",
        reply_markup=token_earning_keyboard(ad_url),
        disable_web_page_preview=disable_preview
    )

@app.on_callback_query(filters.regex("^check_sub$"))
async def check_sub_callback(client, callback_query):
    user_id = callback_query.from_user.id
    if is_rate_limited(user_id):
        await callback_query.answer("⚠️ You're checking too quickly. Please wait a minute and try again.", show_alert=True)
        logger.warning(f"User {user_id} hit rate limit in check_sub_callback")
        return

    is_member = await check_subscription_cached(client, user_id)  # Use cached version
    
    # Invalidate cache after explicit check
    if f"{user_id}" in subscription_cache:
        del subscription_cache[f"{user_id}"]

    if is_member:
        await callback_query.message.edit_text(
            "✅ You are subscribed! You can now watch videos.",
            reply_markup=await get_main_keyboard(user_id)
        )
    else:
        await callback_query.message.edit_text(
            "❌ You are not subscribed yet. Please join our channel:",
            reply_markup=join_channel_keyboard()
        )

@app.on_callback_query(filters.regex(r"^share_(.+)$"))
async def share_callback(client, callback_query):
    video_uuid = callback_query.data.split('_', 1)[1]
    share_link = f"https://t.me/{config.BOT_USERNAME[1:]}?start={video_uuid}"
    await callback_query.answer()
    await callback_query.message.reply(
        f"Share this video with your friends!\n<code>{share_link}</code>",
        quote=True
    )

# --- Admin Commands ---
@app.on_message(filters.command("broadcast") & filters.private & filters.user(config.ADMIN_IDS) & filters.reply)
async def broadcast_cmd(client, message: Message):
    replied_message = message.reply_to_message
    users = list(users_collection.find({}, {'user_id': 1}))
    total_users = len(users)
    broadcast_msg = await message.reply(f"Broadcasting to {total_users} users...")
    
    success = 0
    blocked = 0
    failed = 0
    
    for user in users:
        try:
            await replied_message.copy(user['user_id'])
            success += 1
        except UserIsBlocked:
            blocked += 1
            logger.info(f"User {user['user_id']} blocked the bot")
        except ChatInvalid:
            failed += 1
            logger.error(f"Invalid chat for user {user['user_id']}")
        except FloodWait as e:
            logger.warning(f"FloodWait: {e.value} seconds. Pausing broadcast.")
            await asyncio.sleep(e.value + 1)  # Wait a bit longer than required
            await replied_message.copy(user['user_id']) # Retry after waiting
            success += 1
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
    logger.info(f"Broadcast completed. Success: {success}, Blocked: {blocked}, Failed: {failed}")

@app.on_message(filters.command("addcategory") & filters.private & filters.user(config.ADMIN_IDS))
async def addcategory_cmd(client, message: Message):
    args = message.text.split()
    if len(args) < 2:
        await message.reply(
            "Usage: /addcategory <category_name>\n"
            "Category name can only contain letters, numbers, underscores, and hyphens."
        )
        return
    
    name = args[1]
    success, msg = add_category(name)
    await message.reply(msg)

@app.on_message(filters.command("deletecategory") & filters.private & filters.user(config.ADMIN_IDS))
async def deletecategory_cmd(client, message: Message):
    if not is_admin(message.from_user.id):
        await message.reply_text("❌ Only admins can use this command.")
        return

    categories = get_categories()
    if not categories:
        await message.reply_text("No categories to delete.")
        return

    buttons = []
    for category in categories:
        buttons.append([InlineKeyboardButton(category, callback_data=f"confirmdelcat_{category}")] ) # Changed callback to confirmdelcat_

    await message.reply_text(
        """Select a category to delete:

⚠️ All videos in the selected category will be deleted permanently. This action cannot be undone. Click on a category name below to confirm deletion.""",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

@app.on_callback_query(filters.regex(r"^confirmdelcat_(.+)$"))
async def confirm_delcat_callback(client, callback_query):
    user_id = callback_query.from_user.id
    if not is_admin(user_id):
        await callback_query.answer("❌ Not authorized.", show_alert=True)
        return
    
    category = callback_query.data[14:] # Extract category name after "confirmdelcat_"

    # Log the admin action before execution
    logger.warning(f"Admin {user_id} is confirming deletion of category: {category}")

    success, msg, deleted_count = delete_category(category)
    
    if success:
        formatted_msg = f"✅ Category '{category}' deleted, and {deleted_count} videos removed permanently. Use /addcategory to create new categories."
        await callback_query.message.edit_text(formatted_msg)
        logger.info(f"Admin {user_id} successfully deleted category {category} with {deleted_count} videos.")
    else:
        await callback_query.answer(msg, show_alert=True)
        logger.error(f"Admin {user_id} failed to delete category {category}: {msg}")

@app.on_message(filters.command("addtoken") & filters.private & filters.user(config.ADMIN_IDS))
async def addtoken_cmd(client, message: Message):
    args = message.text.split()
    if len(args) < 3:
        await message.reply("Usage: /addtoken <user_id> <count>")
        return
        
    try:
        user_id = int(args[1])
        count = int(args[2])
        
        if user_id <= 0:
            await message.reply("User ID must be a positive integer.")
            return
            
        if count <= 0:
            await message.reply("Token count must be a positive integer.")
            return
            
        if count > 10:  # Reasonable limit
            await message.reply("Cannot add more than 10 tokens at once.")
            return
            
        # Check if user exists
        user = users_collection.find_one({'user_id': user_id})
        if not user:
            await message.reply("User not found in database.")
            logger.warning(f"Admin {message.from_user.id} attempted to add tokens to non-existent user {user_id}.")
            return
            
        for _ in range(count):
            add_token(user_id)
            
        logger.info(f"Admin {message.from_user.id} added {count} tokens to user {user_id}.")
        await message.reply(f"Added {count} tokens to user {user_id}.")
    except ValueError:
        logger.warning(f"Admin {message.from_user.id} provided invalid input for addtoken: {message.text}")
        await message.reply("User ID and count must be valid integers.")
    except Exception as e:
        logger.error(f"Error adding tokens by admin {message.from_user.id}: {e}")
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
    if user_id not in config.ADMIN_IDS:
        return
    
    # Initialize default category if none exists
    if not get_categories():
        add_category(config.DEFAULT_CATEGORY)
        logger.info(f"Default category '{config.DEFAULT_CATEGORY}' created")
    
    batch_add_state[user_id] = {
        'batch_mode': True,
        'current_category': config.DEFAULT_CATEGORY
    }
    
    await message.reply(
        "Send me videos to add. Type /done when finished.\n"
        "Current category: " + config.DEFAULT_CATEGORY
    )

@app.on_message(filters.command("done") & filters.private & filters.user(config.ADMIN_IDS))
async def done_cmd(client, message: Message):
    user_id = message.from_user.id
    if user_id not in config.ADMIN_IDS:
        return
    
    if batch_add_state.get(user_id, {}).get('batch_mode'):
        batch_add_state[user_id]['batch_mode'] = False
        await message.reply("Batch add mode disabled.")

@app.on_message(filters.video & filters.private & filters.user(config.ADMIN_IDS))
async def handle_video(client, message: Message):
    user_id = message.from_user.id

    if user_id not in batch_add_state or not batch_add_state[user_id].get('batch_mode'):
        logger.warning(f"User {user_id} sent video outside of batch add mode.")
        return

    category = batch_add_state[user_id].get('current_category', config.DEFAULT_CATEGORY)
    if not category:
        await message.reply_text("⚠️ Please set a category first using /category.")
        return

    # Validate category name from batch_add_state
    is_valid_category, validation_msg = validate_category_name(category)
    if not is_valid_category:
        await message.reply_text(f"❌ Invalid category selected: {validation_msg}. Please select a valid category using /category.")
        logger.error(f"Admin {user_id} attempted to add video to invalid category '{category}': {validation_msg}")
        return

    if not message.video:
        await message.reply_text("❌ Please send a video file.")
        return

    file_id = message.video.file_id
    file_unique_id = message.video.file_unique_id
    file_size = message.video.file_size

    # Check for duplicate video using file_unique_id
    if media_collection.find_one({"file_unique_id": file_unique_id}):
        await message.reply_text("⚠️ This video has already been added.")
        return

    try:
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
            "message_id": message_id_in_channel # Store the message_id in the channel
        }
        media_collection.insert_one(video_data)
        logger.info(f"Video {file_id} added to category {category} by admin {user_id}")
        await message.reply_text(
            f"✅ File {message.video.file_name} Added to {category}\n"\
            f"📁 Category: {category}\n"
            f"📊 Size: {format_size(file_size)}\n"
            f"🆔 File ID: {file_id}"
        )
    except Exception as e:
        logger.error(f"Error adding video: {e}")
        await message.reply_text("❌ Failed to add video. Please try again.")

@app.on_message(filters.command("category") & filters.private & filters.user(config.ADMIN_IDS))
async def set_category_cmd(client, message: Message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        await message.reply_text("❌ Only admins can use this command.")
        return

    # Check if batch_mode is active
    if user_id not in batch_add_state or not batch_add_state[user_id].get('batch_mode', False):
        await message.reply_text("❌ Error: Start batch mode with /batchadd first.")
        return

    categories = get_categories()
    if not categories:
        await message.reply_text("⚠️ No categories available to set. Use /addcategory to create one.")
        return

    buttons = []
    for category in categories:
        buttons.append([InlineKeyboardButton(category, callback_data=f"setcat_{category}")])

    await message.reply_text(
        "Select a category for batch adding videos:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

@app.on_callback_query(filters.regex(r"^setcat_(.+)$"))
async def setcat_callback(client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    # Extract category name, handling potential spaces or special characters safely
    # The regex in the filter ensures it matches the format, this just extracts the group
    match = re.match(r"^setcat_(.+)$", callback_query.data)
    if not match:
        await callback_query.answer("❌ Invalid category data.", show_alert=True)
        return
    category_name = match.group(1)

    if not is_admin(user_id):
        await callback_query.answer("❌ Only admins can use this command.", show_alert=True)
        return

    if user_id not in batch_add_state or not batch_add_state[user_id].get('batch_mode', False):
        await callback_query.answer("❌ Error: Batch mode not active.", show_alert=True)
        return

    if category_name not in get_categories():
        await callback_query.answer("❌ Invalid category.", show_alert=True)
        return

    batch_add_state[user_id]['current_category'] = category_name
    await callback_query.message.edit_text(f"✅ Category set to '{category_name}' for batch adding. Send videos now or use /done to finish.")

@app.on_message(filters.command("stats") & filters.private & filters.user(config.ADMIN_IDS))
async def stats_cmd(client, message: Message):
    total_users = users_collection.count_documents({})
    total_videos = media_collection.count_documents({})
    total_categories = categories_collection.count_documents({})
    await message.reply(f"Total Users: {total_users}\nTotal Videos: {total_videos}\nTotal Categories: {total_categories}")

# --- Auto-Delete & Protect Content ---
@app.on_message(filters.command('toggle_auto_delete') & filters.private & filters.user(config.ADMIN_IDS))
async def toggle_auto_delete(client, message):
    s = settings_collection.find_one({'_id': 'settings'}) or {'auto_delete': True}
    new_status = not s.get('auto_delete', True)
    settings_collection.update_one({'_id': 'settings'}, {'$set': {'auto_delete': new_status}}, upsert=True)
    await message.reply(f"Auto-delete feature is now {'enabled' if new_status else 'disabled'}.")

@app.on_message(filters.command('toggle_protect') & filters.private & filters.user(config.ADMIN_IDS))
async def toggle_protect(client, message):
    s = settings_collection.find_one({'_id': 'settings'}) or {'protect_content': True}
    new_status = not s.get('protect_content', True)
    settings_collection.update_one({'_id': 'settings'}, {'$set': {'protect_content': new_status}}, upsert=True)
    await message.reply(f"Content protection is now {'enabled' if new_status else 'disabled'}.")

@app.on_message(filters.regex("^Join Channel$") & filters.private)
async def join_channel_btn(client, message: Message):
    await message.reply(
        "Please join our channel to watch videos:",
        reply_markup=join_channel_keyboard()
    )

@app.on_message(filters.regex("^Check Subscription$") & filters.private)
async def check_sub_btn(client, message: Message):
    user_id = message.from_user.id
    if await check_subscription_cached(client, user_id):
        await message.reply(
            "✅ You are subscribed! You can now watch videos.",
            reply_markup=await get_main_keyboard(user_id)
        )
    else:
        await message.reply(
            "❌ You are not subscribed yet. Please join our channel:",
            reply_markup=join_channel_keyboard()
        )

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
            month_ago = now - timedelta(days=30)
            history_collection.update_many(
                {},
                {'$pull': {'history': {'viewed_at': {'$lt': month_ago}}}}
            )
            
            # Remove empty history documents
            history_collection.delete_many({'history': {'$size': 0}})
            
            # Remove token documents with empty 'tokens' array
            tokens_collection.delete_many({'tokens': {'$size': 0}})
            
            logger.info("Database cleanup completed")
        except Exception as e:
            logger.error(f"Error in database cleanup: {e}")
        
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
                except (MessageIdInvalid, ValueError): # ValueError can happen if message_id is malformed
                    logger.warning(f"Video {video_uuid} (message_id: {message_id_in_channel}) no longer exists in channel. Deleting from DB.")
                    media_collection.delete_one({'uuid': video_uuid})
                except Exception as e:
                    logger.error(f"Error verifying media {video_uuid}: {e}")

            logger.info("Media verification and cleanup completed.")
        except Exception as e:
            logger.error(f"Error in media verification cleanup task: {e}")
        
        # Run every 6 hours
        await asyncio.sleep(6 * 3600)

# --- Main ---
if __name__ == '__main__':
    # Start cleanup task
    app.loop.create_task(cleanup_expired_data())
    # Start media verification and cleanup task
    app.loop.create_task(verify_and_cleanup_media())
    # Start bot
    app.run() 