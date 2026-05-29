import os
import asyncio
import uuid
import base64
import logging
import html
import urllib.parse
import re
from datetime import datetime, timedelta, timezone
from collections import deque
from shortzy import Shortzy

# --- Python 3.14+ Asyncio Compatibility ---
try:
    asyncio.get_running_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, Message,
    InputMediaVideo, CallbackQuery, WebAppInfo, ReplyKeyboardRemove
)
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandObject
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter, TelegramForbiddenError
from aiogram.enums import ChatMemberStatus, ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from pymongo import MongoClient, ASCENDING, DESCENDING, UpdateOne
import uvicorn
from fastapi import FastAPI, Response

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Configuration ---
class BotConfig:
    def __init__(self):
        self.BOT_TOKEN = os.environ.get('BOT_TOKEN')
        if not self.BOT_TOKEN:
             raise ValueError("BOT_TOKEN is required.")
        self.BOT_USERNAME = os.environ.get('BOT_USERNAME', '@YourBot')
        self.MONGO_URI = os.environ.get('MONGO_URI')
        if not self.MONGO_URI:
             raise ValueError("MONGO_URI is required.")
        self.MONGO_DB_NAME = os.environ.get('MONGO_DB_NAME', 'telegram_bot')
        self.BUY_BOT_URL = os.environ.get('BUY_BOT_URL', 'https://t.me/nyraapaybot?start')
        self.OWNER_ID = int(os.environ.get('OWNER_ID', 6612030110))
        self.TOKEN_EXPIRY = int(os.environ.get('TOKEN_EXPIRY', 21600))
        self.DAILY_FREE_VIDEOS = int(os.environ.get('DAILY_FREE_VIDEOS', 1))
        self.FREE_VIDEO_RESET_HOURS = int(os.environ.get('FREE_VIDEO_RESET_HOURS', 24))
        self.VERIFICATION_TOKEN_DURATION_HOURS = float(os.environ.get('VERIFICATION_TOKEN_DURATION_HOURS', 6.0))
        self.REFERRAL_BONUS_HOURS = int(os.environ.get('REFERRAL_BONUS_HOURS', 6))
        self.MENU_EXPIRY_MINUTES = int(os.environ.get('MENU_EXPIRY_MINUTES', 10))
        self.WEBAPP_URL = os.environ.get('WEBAPP_URL', 'https://your-webapp-url.com')
        self.FREE_USER_SAVE_LIMIT = int(os.environ.get('FREE_USER_SAVE_LIMIT', 10))

config = BotConfig()

# --- MongoDB Setup ---
client = MongoClient(config.MONGO_URI, tz_aware=True)
db = client[config.MONGO_DB_NAME]
users_collection = db['users']
tokens_collection = db['tokens']
media_collection = db['media']
history_collection = db['history']
categories_collection = db['categories']
settings_collection = db['settings']
video_batches_collection = db['video_batches']
force_sub_channels_collection = db['force_sub_channels']
data_channel_collection = db['data_channel']
ssrb_verifications_collection = db['ssrb_verifications']
refresh_tokens_used_collection = db['refresh_tokens_used']

# --- Database Indexes ---
users_collection.create_index([("user_id", ASCENDING)], unique=True)
media_collection.create_index([("uuid", ASCENDING)], unique=True)
media_collection.create_index([("file_unique_id", ASCENDING)])
media_collection.create_index([("category", ASCENDING), ("sequence_number", ASCENDING)])
history_collection.create_index([("user_id", ASCENDING)])
tokens_collection.create_index([("user_id", ASCENDING)], unique=True)

# --- Aiogram Setup ---
bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)
app = FastAPI()

# --- Global & Persistence States ---
active_video_message = {}
batch_add_state = {}
batch_link_state = {}
delete_mode_state = set()
nav_locks = set()
BOT_ADMINS = {config.OWNER_ID}
DATA_CHANNEL_ID = None
FSUB_CHANNELS = []
SHORTENER_DISABLED = False
PROTECT_CONTENT = True

class AdminStates(StatesGroup):
    broadcast = State()
    add_cat = State()
    del_cat = State()
    fsub_id = State()
    fsub_link = State()
    token_uid = State()
    token_days = State()
    rem_token_uid = State()
    del_vid = State()
    cat_rename_old = State()
    cat_rename_new = State()
    add_admin = State()
    rem_admin = State()
    del_user = State()
    set_data = State()
    view_token_uid = State()

# --- Utility Functions ---
def str_to_b64(string: str) -> str: return base64.urlsafe_b64encode(string.encode('utf-8')).decode('utf-8')
def b64_to_str(b64: str) -> str:
    try: return base64.urlsafe_b64decode(b64.encode('utf-8')).decode('utf-8')
    except: return ""

def get_now(): return datetime.now(timezone.utc)
def get_current_time(): return int(get_now().timestamp())

async def load_settings():
    global BOT_ADMINS, DATA_CHANNEL_ID, FSUB_CHANNELS, SHORTENER_DISABLED, PROTECT_CONTENT
    s = settings_collection.find_one({'_id': 'bot_settings'})
    if s:
        BOT_ADMINS = set(s.get('admins', [])) | {config.OWNER_ID}
        SHORTENER_DISABLED = s.get('shortener_disabled', False)
        PROTECT_CONTENT = s.get('protect_content', True)
    d = data_channel_collection.find_one({'_id': 'data_channel'})
    if d: DATA_CHANNEL_ID = d.get('channel_id')
    FSUB_CHANNELS = list(force_sub_channels_collection.find({}))

def is_admin(uid: int) -> bool: return uid in BOT_ADMINS

async def get_shortener_url(long_url: str) -> str:
    if SHORTENER_DISABLED: return long_url
    c = settings_collection.find_one({'_id': 'shortener_config'})
    if not c: return long_url
    try:
        parsed = urllib.parse.urlparse(c['template_url'])
        api = urllib.parse.parse_qs(parsed.query).get('api', [None])[0]
        sz = Shortzy(api_key=api, base_site=parsed.netloc)
        res = await sz.convert(long_url)
        return res if res and res.startswith("http") else long_url
    except Exception as e:
        logger.error(f"Shortzy error: {e}")
        return long_url

# --- Membership & Access Logic ---
async def check_membership(uid: int) -> bool:
    if is_admin(uid) or not FSUB_CHANNELS: return True
    for c in FSUB_CHANNELS:
        try:
            m = await bot.get_chat_member(c['channel_id'], uid)
            if m.status not in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]: return False
        except Exception: return False
    return True

async def send_fsub_msg(chat_id):
    kb = InlineKeyboardBuilder()
    for c in FSUB_CHANNELS: kb.row(InlineKeyboardButton(text=c.get('name', 'Join Channel'), url=c.get('link', 'https://t.me')))
    kb.row(InlineKeyboardButton(text="🔄 Try Again", callback_data="check_join_status"))
    await bot.send_message(chat_id, "<b>⚠️ Please join our channels to continue.</b>", reply_markup=kb.as_markup())

def add_prem(uid, seconds, admin=False):
    exp = get_now() + timedelta(seconds=seconds)
    tokens_collection.update_one({'user_id': uid}, {'$push': {'tokens': {'token_id': str(uuid.uuid4()), 'expires_at': exp, 'is_admin_granted': admin, 'created_at': get_now()}}}, upsert=True)
    tokens_collection.update_one({'user_id': uid}, {'$push': {'tokens': {'$each': [], '$slice': -20}}})

def has_prem(uid):
    doc = tokens_collection.find_one({'user_id': uid})
    if not doc or 'tokens' not in doc: return False
    now = get_now()
    return any(t.get('expires_at') > now for t in doc['tokens'])

async def get_token_kb(uid):
    ac = str_to_b64(f"{uid}:{get_current_time()}")
    uname = config.BOT_USERNAME[1:] if config.BOT_USERNAME.startswith('@') else config.BOT_USERNAME
    url = await get_shortener_url(f"https://t.me/{uname}?start=token_{ac}")
    kb = InlineKeyboardBuilder()
    if not SHORTENER_DISABLED: kb.row(InlineKeyboardButton(text="🔓 Unlock Access", url=url))
    kb.row(InlineKeyboardButton(text="✅ 𝐈'ｍ Ｈｕｍａｎ", url=f"https://t.me/SaveRestrict_Robot?start=verify_for_atdb_{uid}"))
    kb.row(InlineKeyboardButton(text="💎 Become a VIP", url=config.BUY_BOT_URL))
    return kb.as_markup()

def can_view(uid, next_v_uuid=None):
    if has_prem(uid): return True
    if next_v_uuid:
        h = history_collection.find_one({'user_id': uid, 'history.video_uuid': next_v_uuid})
        if h: return True
    u = users_collection.find_one({'user_id': uid})
    if not u: return False
    usage = u.get('free_usage', {})
    if not usage or get_now() > usage.get('reset_at', datetime.min.replace(tzinfo=timezone.utc)):
        users_collection.update_one({'user_id': uid}, {'$set': {'free_usage': {'count': 0, 'reset_at': get_now() + timedelta(hours=config.FREE_VIDEO_RESET_HOURS)}}})
        return True
    return usage.get('count', 0) < config.DAILY_FREE_VIDEOS

def use_free(uid, v_uuid):
    if not has_prem(uid):
        h = history_collection.find_one({'user_id': uid, 'history.video_uuid': v_uuid})
        if not h:
            users_collection.update_one({'user_id': uid}, {'$inc': {'free_usage.count': 1}})

def save_history(uid, v_uuid, cat, batch_id=None):
    # Maintaining schema video_uuid/category for compatibility
    history_collection.update_one({'user_id': uid}, {'$push': {'history': {'$each': [{'video_uuid': v_uuid, 'category': cat, 'viewed_at': get_now(), 'batch': batch_id}], '$slice': -100}}}, upsert=True)

# --- Messaging & Media Handling ---
async def send_v(chat_id, edit_id, v_data, kb, force=False):
    if not DATA_CHANNEL_ID: return False
    cap = f"Category: {html.escape(v_data.get('category', 'All'))}\n{v_data.get('custom_caption', '')}"

    if not edit_id and chat_id in active_video_message:
        try: await bot.delete_message(chat_id, active_video_message[chat_id]['message_id'])
        except: pass
        del active_video_message[chat_id]

    try:
        sent = None
        if not force and edit_id:
            try: sent = await bot.edit_message_media(chat_id, edit_id, media=InputMediaVideo(media=v_data['file_id'], caption=cap), reply_markup=kb)
            except: pass

        if not sent:
            if force and edit_id:
                try: await bot.delete_message(chat_id, edit_id)
                except: pass
            try:
                sent_msg = await bot.copy_message(chat_id, DATA_CHANNEL_ID, v_data['message_id'], caption=cap, reply_markup=kb, protect_content=PROTECT_CONTENT)
                sent = sent_msg
            except Exception:
                try:
                    sent = await bot.send_video(chat_id, v_data['file_id'], caption=cap, reply_markup=kb, protect_content=PROTECT_CONTENT)
                except: pass

        if sent:
            active_video_message[chat_id] = {'message_id': sent.message_id if hasattr(sent, 'message_id') else sent.id, 'ts': get_now(), 'v_uuid': v_data['uuid']}
            return True
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        return await send_v(chat_id, edit_id, v_data, kb, force)
    except Exception as e:
        logger.error(f"Send video error: {e}")
    return False

# --- Keyboards ---
async def main_kb(uid):
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="🎞️ Get Video"))
    b.row(KeyboardButton(text="👤 Profile"), KeyboardButton(text="🔖 Saved Videos"))
    if has_prem(uid): b.row(KeyboardButton(text="📱 Open Mini App", web_app=WebAppInfo(url=config.WEBAPP_URL)))
    return b.as_markup(resize_keyboard=True)

def v_kb(v_uuid, cat, uid, saved=False, batch_id=None, pos=0):
    b = InlineKeyboardBuilder()
    cp = "def" if cat == "default (all)" else str_to_b64(cat)
    nav = []
    if pos > 0: nav.append(InlineKeyboardButton(text="⬅️ Previous", callback_data=f"prev|{v_uuid}|{cp}|{int(saved)}|{batch_id or ''}"))
    nav.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"next|{v_uuid}|{cp}|{int(saved)}|{batch_id or ''}"))
    b.row(*nav)
    b.row(InlineKeyboardButton(text="👎", callback_data=f"vote|down|{v_uuid}"), InlineKeyboardButton(text="👍", callback_data=f"vote|up|{v_uuid}"))
    b.row(InlineKeyboardButton(text="🗑️ Remove" if saved else "💾 Bookmark", callback_data=f"remove_saved_{v_uuid}" if saved else f"bookmark_{v_uuid}"),
          InlineKeyboardButton(text="📲 Share", callback_data=f"share_{v_uuid}"), InlineKeyboardButton(text="⬇️ Get File", callback_data=f"dl_{v_uuid}"))
    b.row(InlineKeyboardButton(text="🗂️ Change Category", callback_data="change_cat"))
    return b.as_markup()

def cat_kb(saved=False):
    b = InlineKeyboardBuilder()
    cats = sorted([x['name'] for x in categories_collection.find({})])
    for c in ["default (all)"] + cats:
        prefix = "saved_cat_select" if saved else "cat_select"
        encoded_cat = str_to_b64(c)
        if len(f"{prefix}|{encoded_cat}") < 64:
             b.row(InlineKeyboardButton(text=c, callback_data=f"{prefix}|{encoded_cat}"))
    if saved: b.row(InlineKeyboardButton(text="🗑️ Clear All", callback_data="confirm_clear_all"))
    return b.as_markup()

# --- User Handlers ---
@router.message(Command("start"))
async def start_h(m: Message, command: CommandObject, state: FSMContext, override_uid: int = None):
    uid = override_uid or m.from_user.id
    arg = command.args
    await state.clear()
    if not users_collection.find_one({'user_id': uid}):
        users_collection.insert_one({'user_id': uid, 'joined_date': get_now(), 'referral_count': 0, 'bookmarked_videos': []})
        if arg and arg.startswith('ref_'):
            try:
                rid = int(arg[4:])
                if rid != uid and users_collection.find_one({'user_id': rid}):
                    add_prem(rid, config.REFERRAL_BONUS_HOURS * 3600)
                    users_collection.update_one({'user_id': rid}, {'$inc': {'referral_count': 1}})
            except: pass
    if not await check_membership(uid):
        if arg: users_collection.update_one({'user_id': uid}, {'$set': {'pending_command': arg}})
        await send_fsub_msg(uid); return

    if arg:
        if arg.startswith('token_'):
            if refresh_tokens_used_collection.find_one({'token': arg}):
                return await bot.send_message(uid, "❌ This access token has already been used.")
            try:
                data = b64_to_str(arg[6:]).split(':')
                if int(data[0]) == uid:
                    add_prem(uid, config.TOKEN_EXPIRY)
                    refresh_tokens_used_collection.insert_one({'token': arg, 'uid': uid, 'at': get_now()})
                    await bot.send_message(uid, "✅ <b>Access Granted!</b> Enjoy unlimited access.")
                    p = (users_collection.find_one_and_update({'user_id': uid}, {'$unset': {'pending_command': ""}}) or {}).get('pending_command')
                    if p: await start_h(m, CommandObject(prefix="/", command="start", args=p), state, override_uid=uid)
            except: pass
        elif arg.startswith('video_'):
            v_uuid = arg[6:].rsplit('_', 1)[0]
            v = media_collection.find_one({'uuid': v_uuid})
            if v and can_view(uid, v['uuid']):
                if await send_v(uid, None, v, v_kb(v['uuid'], v['category'], uid), True):
                    use_free(uid, v['uuid']); save_history(uid, v['uuid'], v['category'])
            else: await bot.send_message(uid, "⚠️ Limit reached!", reply_markup=await get_token_kb(uid))
        elif arg.startswith('batch_'):
            bid = arg[6:]
            b = video_batches_collection.find_one({'batch_id': bid})
            if b:
                v = media_collection.find_one({'uuid': b['video_uuids'][0]})
                users_collection.update_one({'user_id': uid}, {'$set': {'active_batch': {'id': bid, 'vids': b['video_uuids'], 'pos': 0}}})
                await send_v(uid, None, v, v_kb(v['uuid'], v['category'], uid, batch_id=bid, pos=0), True)
    else: await bot.send_message(uid, "👋 <b>Welcome!</b> Choose an option:", reply_markup=await main_kb(uid))

@router.message(F.text == "🎞️ Get Video")
async def get_v_h(m: Message):
    uid = m.from_user.id
    if not await check_membership(uid): return await send_fsub_msg(uid)
    if not can_view(uid): return await m.reply("⚠️ Limit reached!", reply_markup=await get_token_kb(uid))
    r = list(media_collection.aggregate([{'$match': {'sequence_number': {'$exists': True}, 'banned': {'$ne': True}}}, {'$sample': {'size': 1}}]))
    if r:
        v = r[0]
        users_collection.update_one({'user_id': uid}, {'$set': {'active_session': {'vids': [v['uuid']], 'pos': 0, 'category': 'default (all)'}}})
        if await send_v(uid, None, v, v_kb(v['uuid'], "default (all)", uid, pos=0), True):
            use_free(uid, v['uuid']); save_history(uid, v['uuid'], "default (all)")

@router.message(F.text == "👤 Profile")
async def profile_h(m: Message):
    uid = m.from_user.id
    u = users_collection.find_one({'user_id': uid})
    text = f"👤 <b>Profile</b>\n\n🆔 ID: <code>{uid}</code>\n💎 Status: {'Premium' if has_prem(uid) else 'Free'}\n👥 Refs: {u.get('referral_count', 0)}\n🔖 Saved: {len(u.get('bookmarked_videos', []))}"
    await m.reply(text)

@router.message(F.text == "🔖 Saved Videos")
async def saved_h(m: Message):
    uid = m.from_user.id
    u = users_collection.find_one({'user_id': uid})
    if not u or not u.get('bookmarked_videos'): return await bot.send_message(uid, "📂 Library is empty.")
    await bot.send_message(uid, "📂 <b>Select category:</b>", reply_markup=cat_kb(saved=True))

@router.callback_query(F.data == "change_cat")
async def change_cat_cb(cb: CallbackQuery):
    await cb.message.edit_text("📂 <b>Select category:</b>", reply_markup=cat_kb())

@router.callback_query(F.data.startswith("cat_select|"))
async def cat_sel_cb(cb: CallbackQuery):
    uid, cat = cb.from_user.id, b64_to_str(cb.data.split('|')[1])
    if cat == "default (all)":
        r = list(media_collection.aggregate([{'$match': {'sequence_number': {'$exists': True}, 'banned': {'$ne': True}}}, {'$sample': {'size': 1}}]))
        v = r[0] if r else None
    else:
        v = media_collection.find_one({'category': cat, 'banned': {'$ne': True}}, sort=[('sequence_number', ASCENDING)])

    if v:
        users_collection.update_one({'user_id': uid}, {'$set': {'active_session': {'vids': [v['uuid']], 'pos': 0, 'category': cat}}})
        await send_v(uid, cb.message.message_id, v, v_kb(v['uuid'], cat, uid, pos=0))
    else: await cb.answer("Empty category.")

@router.callback_query(F.data.startswith("saved_cat_select|"))
async def scat_sel_cb(cb: CallbackQuery):
    uid, cat = cb.from_user.id, b64_to_str(cb.data.split('|')[1])
    u = users_collection.find_one({'user_id': uid})
    uuids = [m['uuid'] for m in u.get('bookmarked_videos', [])]
    vids_data = list(media_collection.find({'uuid': {'$in': uuids}, 'category': cat}))
    found_uuids = [v['uuid'] for v in vids_data]
    if found_uuids:
        v = media_collection.find_one({'uuid': found_uuids[0]})
        users_collection.update_one({'user_id': uid}, {'$set': {'active_session': {'vids': found_uuids, 'pos': 0, 'category': cat, 'saved': True}}})
        await send_v(uid, cb.message.message_id, v, v_kb(v['uuid'], cat, uid, saved=True, pos=0))
    else: await cb.answer("No saved videos here.")

@router.callback_query(F.data.regexp(r"^(next|prev)\|"))
async def nav_cb(cb: CallbackQuery):
    uid = cb.from_user.id
    if uid in nav_locks: return await cb.answer("Wait...")
    nav_locks.add(uid)
    try:
        parts = cb.data.split('|')
        action, curr_uuid, cat_b64, saved, bid = parts[0], parts[1], parts[2], bool(int(parts[3])), parts[4]
        cat = "default (all)" if cat_b64 == "def" else b64_to_str(cat_b64)

        u = users_collection.find_one({'user_id': uid})
        sess_key = 'active_batch' if bid else 'active_session'
        sess = u.get(sess_key, {'vids': [curr_uuid], 'pos': 0})

        v = None
        if action == "next":
            next_v = None
            if sess['pos'] + 1 < len(sess['vids']):
                next_v = media_collection.find_one({'uuid': sess['vids'][sess['pos']+1]})
            elif not bid and not saved:
                if cat == "default (all)":
                    r = list(media_collection.aggregate([{'$match': {'sequence_number': {'$exists': True}, 'banned': {'$ne': True}}}, {'$sample': {'size': 1}}]))
                    next_v = r[0] if r else None
                else:
                    curr_v = media_collection.find_one({'uuid': curr_uuid})
                    next_v = media_collection.find_one({'category': cat, 'sequence_number': {'$gt': curr_v.get('sequence_number', 0) if curr_v else 0}, 'banned': {'$ne': True}}, sort=[('sequence_number', 1)])

            if next_v:
                if not can_view(uid, next_v['uuid']):
                    await bot.send_message(uid, "⚠️ Limit reached!", reply_markup=await get_token_kb(uid))
                    return await cb.answer()
                v = next_v
                if sess['pos'] + 1 >= len(sess['vids']): sess['vids'].append(v['uuid'])
                sess['pos'] += 1
        else: # prev
            if sess['pos'] > 0:
                v = media_collection.find_one({'uuid': sess['vids'][sess['pos']-1]})
                sess['pos'] -= 1

        if v:
            if await send_v(uid, cb.message.message_id, v, v_kb(v['uuid'], cat, uid, saved=saved, batch_id=bid, pos=sess['pos'])):
                users_collection.update_one({'user_id': uid}, {'$set': {sess_key: sess}})
                if action == "next": use_free(uid, v['uuid']); save_history(uid, v['uuid'], cat, batch_id=bid)
        else: await cb.answer("End of list.", show_alert=True)
        await cb.answer()
    finally: nav_locks.remove(uid)

@router.callback_query(F.data.startswith("bookmark_"))
async def bookmark_cb(cb: CallbackQuery):
    uid = cb.from_user.id
    if not has_prem(uid):
        u = users_collection.find_one({'user_id': uid})
        if len(u.get('bookmarked_videos', [])) >= config.FREE_USER_SAVE_LIMIT:
            return await cb.answer(f"❌ Free limit is {config.FREE_USER_SAVE_LIMIT} bookmarks. Upgrade to VIP!", show_alert=True)
    users_collection.update_one({'user_id': uid}, {'$addToSet': {'bookmarked_videos': {'uuid': cb.data[9:], 'at': get_now()}}})
    await cb.answer("Saved to bookmarks!", show_alert=True)

@router.callback_query(F.data.startswith("remove_saved_"))
async def remove_saved_cb(cb: CallbackQuery):
    users_collection.update_one({'user_id': cb.from_user.id}, {'$pull': {'bookmarked_videos': {'uuid': cb.data[13:]}}})
    await cb.answer("Removed.")
    await saved_h(cb)

@router.callback_query(F.data == "confirm_clear_all")
async def clear_all_conf(cb: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Yes, Clear All", callback_data="clear_all_now")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="back_to_saved_cats")]
    ])
    await cb.message.edit_text("<b>⚠️ Are you sure?</b> This will delete all your bookmarks.", reply_markup=kb)

@router.callback_query(F.data == "clear_all_now")
async def clear_all_now_cb(cb: CallbackQuery):
    users_collection.update_one({'user_id': cb.from_user.id}, {'$set': {'bookmarked_videos': []}})
    await cb.answer("Cleared!", show_alert=True)
    await cb.message.edit_text("📂 Library is empty.")

@router.callback_query(F.data == "back_to_saved_cats")
async def back_saved_cb(cb: CallbackQuery):
    await saved_h(cb)

@router.callback_query(F.data.startswith("vote|"))
async def vote_cb(cb: CallbackQuery):
    vote, v_uuid = cb.data.split('|')[1:]
    media_collection.update_one({'uuid': v_uuid}, {'$inc': {f'votes.{vote}': 1}})
    await cb.answer(f"Voted {vote}!", show_alert=False)

@router.callback_query(F.data.startswith("share_"))
async def share_cb(cb: CallbackQuery):
    v_uuid = cb.data[6:]
    uname = config.BOT_USERNAME[1:] if config.BOT_USERNAME.startswith('@') else config.BOT_USERNAME
    await bot.send_message(cb.from_user.id, f"🔗 <b>Share Link:</b>\n<code>https://t.me/{uname}?start=video_{v_uuid}</code>")
    await cb.answer()

@router.callback_query(F.data.startswith("dl_"))
async def dl_cb(cb: CallbackQuery):
    if not has_prem(cb.from_user.id): return await cb.answer("💎 Premium required!", show_alert=True)
    v = media_collection.find_one({'uuid': cb.data[3:]})
    if v:
        try: await bot.send_video(cb.from_user.id, v['file_id'], caption="✅ File delivered.", protect_content=False)
        except Exception: await cb.answer("Error.")
    await cb.answer()

@router.callback_query(F.data == "check_join_status")
async def check_join_cb(cb: CallbackQuery, state: FSMContext):
    if await check_membership(cb.from_user.id):
        await cb.message.delete()
        u = users_collection.find_one({'user_id': cb.from_user.id})
        await start_h(cb.message, CommandObject(prefix="/", command="start", args=u.get('pending_command')), state, override_uid=cb.from_user.id)
    else: await cb.answer("Join first!", show_alert=True)

# --- Admin Handlers ---
@router.message(Command("help"))
async def help_cmd(m: Message):
    if is_admin(m.from_user.id):
        text = "🛠️ <b>Admin Commands</b>\n\n/stats - Bot Stats\n/broadcast - Send message to all\n/addtoken [uid] [days] - Grant Premium\n/removetoken [uid] - Revoke Premium\n/addcategory - Create Category\n/deletecategory - Remove Category\n/categoryrename - Rename Category\n/deletevideo - Enter Delete Mode\n/batchadd - Enter Batch Add Mode\n/createbatchlink - Enter Batch Link Mode\n/addadmin [uid] - Add Admin\n/removeadmin [uid] - Remove Admin\n/setfsub - Set Join Channels\n/setdata - Set Data Channel\n/toggle_protect - Toggle protection\n/viewtoken [uid] - View tokens"
        await m.reply(text)

@router.message(Command("stats"))
async def stats_h(m: Message):
    if is_admin(m.from_user.id):
        u_count = users_collection.count_documents({})
        v_count = media_collection.count_documents({})
        c_count = categories_collection.count_documents({})
        text = f"📊 <b>Bot Stats</b>\n\nTotal Users: {u_count}\nTotal Videos: {v_count}\nCategories: {c_count}"
        await m.reply(text)

async def safe_copy(msg, uid):
    try:
        await bot.copy_message(chat_id=uid, from_chat_id=msg.chat.id, message_id=msg.message_id)
        return True
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        return await safe_copy(msg, uid)
    except: return False

@router.message(Command("broadcast"))
async def broadcast_h(m: Message, state: FSMContext):
    if is_admin(m.from_user.id):
        await m.reply("Send message to broadcast:"); await state.set_state(AdminStates.broadcast)

@router.message(AdminStates.broadcast)
async def process_broadcast(m: Message, state: FSMContext):
    await state.clear(); count, fail = 0, 0
    status = await m.reply("🚀 Broadcasting...")
    cursor = users_collection.find({})
    for u in cursor:
        if await safe_copy(m, u['user_id']): count += 1
        else: fail += 1
        if (count + fail) % 50 == 0:
            try: await status.edit_text(f"🚀 Progress: {count} success, {fail} failed.")
            except: pass
        await asyncio.sleep(0.05)
    await status.edit_text(f"✅ Finished. Success: {count}, Fail: {fail}")

@router.message(Command("batchadd"))
async def batch_add_cmd(m: Message):
    if not is_admin(m.from_user.id): return
    cats = sorted([x['name'] for x in categories_collection.find({})])
    if not cats: return await m.reply("Create a category first!")
    kb = InlineKeyboardBuilder()
    for c in cats:
        if len(f"batch_sel_cat|{str_to_b64(c)}") < 64:
             kb.row(InlineKeyboardButton(text=c, callback_data=f"batch_sel_cat|{str_to_b64(c)}"))
    await m.reply("🎬 <b>Select Category for Batch Add:</b>", reply_markup=kb.as_markup())

@router.callback_query(F.data.startswith("batch_sel_cat|"))
async def batch_sel_cat_cb(cb: CallbackQuery):
    uid, cat = cb.from_user.id, b64_to_str(cb.data.split('|')[1])
    last = media_collection.find_one({'category': cat}, sort=[('sequence_number', DESCENDING)])
    seq = (last['sequence_number'] + 1) if last else 1
    batch_add_state[uid] = {'cat': cat, 'seq': seq, 'queue': deque(), 'processing': False}
    await cb.message.edit_text(f"✅ Mode: <b>{cat}</b>. Start from seq <b>{seq}</b>.\nSend videos now. Type /done to finish.")

@router.message(Command("createbatchlink"))
async def create_batch_h(m: Message):
    if is_admin(m.from_user.id):
        batch_link_state[m.from_user.id] = []
        await m.reply("🎬 <b>Batch Link Mode</b>\nSend videos one by one. Type /done when finished.")

@router.message(F.video)
async def handle_video_admin(m: Message):
    uid = m.from_user.id
    if uid in batch_add_state:
        batch_add_state[uid]['queue'].append(m)
        await m.reply(f"Queued. Total: {len(batch_add_state[uid]['queue'])}")
        if not batch_add_state[uid]['processing']:
            asyncio.create_task(process_batch_queue(uid))
    elif uid in batch_link_state:
        v = media_collection.find_one({'file_unique_id': m.video.file_unique_id})
        if v:
            batch_link_state[uid].append(v['uuid'])
            await m.reply(f"✅ Video added to batch list. Total: {len(batch_link_state[uid])}")
        else: await m.reply("❌ Video not in DB. Use /batchadd first.")
    elif uid in delete_mode_state:
        v = media_collection.find_one_and_delete({'file_unique_id': m.video.file_unique_id})
        if v:
            users_collection.update_many({}, {'$pull': {'bookmarked_videos': {'uuid': v['uuid']}}})
            history_collection.update_many({}, {'$pull': {'history': {'video_uuid': v['uuid']}}})
            try: await bot.delete_message(DATA_CHANNEL_ID, v['message_id'])
            except: pass
            await m.reply("✅ Deleted from database and storage.")
        else: await m.reply("❌ Not found in database.")

async def process_batch_queue(uid):
    state = batch_add_state.get(uid)
    if not state or state['processing']: return
    state['processing'] = True
    while state['queue']:
        msg = state['queue'].popleft()
        try:
            v_uuid = str(uuid.uuid4())[:8]
            copied = await bot.copy_message(chat_id=DATA_CHANNEL_ID, from_chat_id=msg.chat.id, message_id=msg.message_id)
            media_collection.insert_one({
                'uuid': v_uuid, 'file_id': msg.video.file_id, 'file_unique_id': msg.video.file_unique_id,
                'message_id': copied.message_id, 'category': state['cat'], 'sequence_number': state['seq'],
                'created_at': get_now()
            })
            state['seq'] += 1
            await msg.reply(f"✅ Saved as seq {state['seq']-1}")
        except Exception as e:
            await msg.reply(f"❌ Error: {e}")
        await asyncio.sleep(1)
    state['processing'] = False

@router.message(Command(["done", "stop"]))
async def done_h(m: Message, state: FSMContext):
    uid = m.from_user.id
    await state.clear()
    if uid in batch_add_state:
        del batch_add_state[uid]
        await m.reply("✅ Batch add mode ended.")
    elif uid in batch_link_state:
        uuids = batch_link_state[uid]
        del batch_link_state[uid]
        if uuids:
            bid = str(uuid.uuid4())[:8]
            video_batches_collection.insert_one({'batch_id': bid, 'video_uuids': uuids, 'at': get_now()})
            uname = config.BOT_USERNAME[1:] if config.BOT_USERNAME.startswith('@') else config.BOT_USERNAME
            await m.reply(f"✅ Batch Created!\nLink: <code>https://t.me/{uname}?start=batch_{bid}</code>")
        else: await m.reply("❌ No videos collected.")
    elif uid in delete_mode_state:
        delete_mode_state.remove(uid)
        await m.reply("✅ Delete mode ended.")
    else: await m.reply("No active process to stop.")

@router.message(Command("categoryrename"))
async def ren_h(m: Message, state: FSMContext):
    if is_admin(m.from_user.id): await m.reply("Old name:"); await state.set_state(AdminStates.cat_rename_old)

@router.message(AdminStates.cat_rename_old)
async def proc_ren_old(m: Message, state: FSMContext):
    await state.update_data(o=m.text); await m.reply("New name:"); await state.set_state(AdminStates.cat_rename_new)

@router.message(AdminStates.cat_rename_new)
async def proc_ren_new(m: Message, state: FSMContext):
    d = await state.get_data(); await state.clear()
    old, new = d['o'], m.text
    categories_collection.update_one({'name': old}, {'$set': {'name': new}})
    media_collection.update_many({'category': old}, {'$set': {'category': new}})
    users_collection.update_many({'bookmarked_videos.cat': old}, {'$set': {'bookmarked_videos.$[elem].cat': new}}, array_filters=[{'elem.cat': old}])
    history_collection.update_many({'history.category': old}, {'$set': {'history.$[elem].category': new}}, array_filters=[{'elem.category': old}])
    await m.reply("✅ Updated.")

@router.message(Command(["addtoken", "addpremium"]))
async def add_t_cmd(m: Message, command: CommandObject, state: FSMContext):
    if not is_admin(m.from_user.id): return
    if command.args:
        try:
            parts = command.args.split()
            uid, days = int(parts[0]), int(parts[1])
            add_prem(uid, days*86400, True); await m.reply(f"✅ Added {days} days to {uid}")
        except: await m.reply("Format: /addtoken [uid] [days]")
    else: await m.reply("Send User ID:"); await state.set_state(AdminStates.token_uid)

@router.message(AdminStates.token_uid)
async def t_uid_p(m: Message, state: FSMContext):
    try:
        uid = int(m.text)
        await state.update_data(u=uid); await m.reply("Days:"); await state.set_state(AdminStates.token_days)
    except: await m.reply("Invalid ID."); await state.clear()

@router.message(AdminStates.token_days)
async def t_days_p(m: Message, state: FSMContext):
    d = await state.get_data(); await state.clear()
    try: add_prem(int(d['u']), int(m.text)*86400, True); await m.reply("Added.")
    except Exception: await m.reply("Error.")

@router.message(Command(["removetoken", "removepremium"]))
async def rem_t_cmd(m: Message, command: CommandObject, state: FSMContext):
    if not is_admin(m.from_user.id): return
    if command.args:
        try: uid = int(command.args); tokens_collection.delete_one({'user_id': uid}); await m.reply("Removed.")
        except Exception: pass
    else: await m.reply("User ID:"); await state.set_state(AdminStates.rem_token_uid)

@router.message(AdminStates.rem_token_uid)
async def rem_t_proc(m: Message, state: FSMContext):
    try: tokens_collection.delete_one({'user_id': int(m.text)}); await m.reply("Removed.")
    except: await m.reply("Error.")
    await state.clear()

@router.message(Command("addcategory"))
async def add_cat_cmd(m: Message, state: FSMContext):
    if is_admin(m.from_user.id): await m.reply("Category Name:"); await state.set_state(AdminStates.add_cat)

@router.message(AdminStates.add_cat)
async def proc_add_cat(m: Message, state: FSMContext):
    await state.clear(); categories_collection.insert_one({'name': m.text, 'at': get_now()}); await m.reply("Added.")

@router.message(Command("deletecategory"))
async def del_cat_cmd(m: Message, state: FSMContext):
    if is_admin(m.from_user.id): await m.reply("Category Name to delete:"); await state.set_state(AdminStates.del_cat)

@router.message(AdminStates.del_cat)
async def proc_del_cat(m: Message, state: FSMContext):
    await state.clear(); categories_collection.delete_one({'name': m.text}); await m.reply("Deleted.")

@router.message(Command("deletevideo"))
async def del_vid_cmd(m: Message):
    if is_admin(m.from_user.id):
        delete_mode_state.add(m.from_user.id)
        await m.reply("🗑️ <b>Delete Mode</b>\nSend videos to delete. Type /stop to finish.")

@router.message(Command("addadmin"))
async def add_adm_cmd(m: Message, state: FSMContext):
    if m.from_user.id == config.OWNER_ID: await m.reply("User ID:"); await state.set_state(AdminStates.add_admin)

@router.message(AdminStates.add_admin)
async def proc_add_adm(m: Message, state: FSMContext):
    try:
        settings_collection.update_one({'_id': 'bot_settings'}, {'$addToSet': {'admins': int(m.text)}}, upsert=True)
        await load_settings(); await m.reply("Added.")
    except: await m.reply("Error.")
    await state.clear()

@router.message(Command("removeadmin"))
async def rem_adm_cmd(m: Message, state: FSMContext):
    if m.from_user.id == config.OWNER_ID: await m.reply("User ID:"); await state.set_state(AdminStates.rem_admin)

@router.message(AdminStates.rem_admin)
async def proc_rem_adm(m: Message, state: FSMContext):
    try:
        settings_collection.update_one({'_id': 'bot_settings'}, {'$pull': {'admins': int(m.text)}})
        await load_settings(); await m.reply("Removed.")
    except: await m.reply("Error.")
    await state.clear()

@router.message(Command("deleteuser"))
async def del_usr_cmd(m: Message, state: FSMContext):
    if is_admin(m.from_user.id): await m.reply("User ID to delete:"); await state.set_state(AdminStates.del_user)

@router.message(AdminStates.del_user)
async def proc_del_usr(m: Message, state: FSMContext):
    try: users_collection.delete_one({'user_id': int(m.text)}); await m.reply("Deleted.")
    except: await m.reply("Error.")
    await state.clear()

@router.message(Command("setfsub"))
async def set_fsub_cmd(m: Message, state: FSMContext):
    if is_admin(m.from_user.id): await m.reply("Channel ID (or @username):"); await state.set_state(AdminStates.fsub_id)

@router.message(AdminStates.fsub_id)
async def proc_fs_id(m: Message, state: FSMContext):
    try:
        chat = await bot.get_chat(m.text)
        await state.update_data(i=chat.id); await m.reply(f"Chat: {chat.title}\nSend Invite Link:"); await state.set_state(AdminStates.fsub_link)
    except: await m.reply("Invalid Chat."); await state.clear()

@router.message(AdminStates.fsub_link)
async def proc_fs_link(m: Message, state: FSMContext):
    d = await state.get_data(); await state.clear()
    force_sub_channels_collection.insert_one({'channel_id': d['i'], 'link': m.text, 'name': 'Channel'})
    await load_settings(); await m.reply("Added.")

@router.message(Command("setdata"))
async def set_data_h(m: Message, state: FSMContext):
    if is_admin(m.from_user.id): await m.reply("Send Data Channel ID (or @username):"); await state.set_state(AdminStates.set_data)

@router.message(AdminStates.set_data)
async def proc_set_data(m: Message, state: FSMContext):
    try:
        chat = await bot.get_chat(m.text)
        data_channel_collection.update_one({'_id': 'data_channel'}, {'$set': {'channel_id': chat.id}}, upsert=True)
        await load_settings(); await m.reply(f"Data channel updated to {chat.title} ({chat.id})")
    except: await m.reply("Invalid Chat.")
    await state.clear()

@router.message(Command("viewtoken"))
async def view_t_cmd(m: Message, command: CommandObject, state: FSMContext):
    if not is_admin(m.from_user.id): return
    if command.args:
        try:
            uid = int(command.args)
            doc = tokens_collection.find_one({'user_id': uid})
            await m.reply(f"Tokens for {uid}: {doc}")
        except: await m.reply("Invalid ID.")
    else: await m.reply("User ID:"); await state.set_state(AdminStates.view_token_uid)

@router.message(AdminStates.view_token_uid)
async def proc_view_t(m: Message, state: FSMContext):
    try:
        uid = int(m.text)
        doc = tokens_collection.find_one({'user_id': uid})
        await m.reply(f"Tokens for {uid}: {doc}")
    except: await m.reply("Error.")
    await state.clear()

@router.message(Command("bypass_limit"))
async def bypass_cmd(m: Message, command: CommandObject):
    if is_admin(m.from_user.id) and command.args:
        try:
            uid = int(command.args)
            users_collection.update_one({'user_id': uid}, {'$set': {'free_usage.count': -9999}})
            await m.reply(f"Limit bypassed for {uid}")
        except: pass

@router.message(Command("toggle_protect"))
async def toggle_prot(m: Message):
    if is_admin(m.from_user.id):
        global PROTECT_CONTENT
        PROTECT_CONTENT = not PROTECT_CONTENT
        settings_collection.update_one({'_id': 'bot_settings'}, {'$set': {'protect_content': PROTECT_CONTENT}}, upsert=True)
        await m.reply(f"Protection: {'ON' if PROTECT_CONTENT else 'OFF'}")

# --- Background Tasks ---
async def cleanup():
    while True:
        try:
            now = get_now()
            for uid, data in list(active_video_message.items()):
                if now - data['ts'] > timedelta(minutes=config.MENU_EXPIRY_MINUTES):
                    try: await bot.delete_message(uid, data['message_id'])
                    except: pass
                    del active_video_message[uid]
        except Exception: pass
        await asyncio.sleep(60)

async def monitor_verifications():
    while True:
        try:
            cursor = ssrb_verifications_collection.find({'is_consumed_by_atdb': False, 'verified': True})
            for v in cursor:
                uid = v['user_id']
                add_prem(uid, config.TOKEN_EXPIRY)
                ssrb_verifications_collection.update_one({'_id': v['_id']}, {'$set': {'is_consumed_by_atdb': True}})
                try:
                    await bot.send_message(uid, "✅ Verification Successful! Access Granted.")
                    u = users_collection.find_one({'user_id': uid})
                    if u and u.get('pending_command'):
                         await bot.send_message(uid, "🔄 Click /start to resume your last request.")
                except Exception: pass
            ssrb_verifications_collection.delete_many({'expires_at': {'$lt': get_now()}})
        except Exception as e: logger.error(f"Monitor error: {e}")
        await asyncio.sleep(30)

# --- Server Start ---
@app.on_event("startup")
async def startup_event():
    await load_settings()
    asyncio.create_task(dp.start_polling(bot))
    asyncio.create_task(cleanup())
    asyncio.create_task(monitor_verifications())

@app.get("/")
async def root(): return Response("OK")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
