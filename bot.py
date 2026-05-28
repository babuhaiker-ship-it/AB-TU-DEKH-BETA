import os
import asyncio
import uuid
import base64
import logging
from datetime import datetime, timedelta, timezone
import urllib.parse
from shortzy import Shortzy

# --- Asyncio Compatibility for Python 3.14+ ---
try:
    asyncio.get_running_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, Message,
    InputMediaVideo, CallbackQuery, WebAppInfo
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

# --- Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Config ---
class BotConfig:
    def __init__(self):
        self.BOT_TOKEN = os.environ.get('BOT_TOKEN')
        self.BOT_USERNAME = os.environ.get('BOT_USERNAME', '@YourBot')
        self.MONGO_URI = os.environ.get('MONGO_URI')
        self.MONGO_DB_NAME = os.environ.get('MONGO_DB_NAME')
        self.BUY_BOT_URL = os.environ.get('BUY_BOT_URL', 'https://t.me/PayBot')
        self.OWNER_ID = int(os.environ.get('OWNER_ID', 6612030110))
        self.TOKEN_EXPIRY = int(os.environ.get('TOKEN_EXPIRY', 21600))
        self.DAILY_FREE_VIDEOS = int(os.environ.get('DAILY_FREE_VIDEOS', 1))
        self.FREE_VIDEO_RESET_HOURS = int(os.environ.get('FREE_VIDEO_RESET_HOURS', 24))
        self.REFERRAL_BONUS = int(os.environ.get('REFERRAL_BONUS', 1))
        self.MENU_EXPIRY_MINUTES = int(os.environ.get('MENU_EXPIRY_MINUTES', 10))
        self.WEBAPP_URL = os.environ.get('WEBAPP_URL', 'https://webapp.com')

config = BotConfig()

# --- DB Setup ---
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

# --- Bot & App ---
bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)
app = FastAPI()

# --- Global States ---
active_menus = {}
nav_locks = set()
BOT_ADMINS = {config.OWNER_ID}
DATA_CHANNEL_ID = None
FSUB_CHANNELS = []
SHORTENER_OFF = False
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
    batch_vids = State()
    cat_rename_old = State()
    cat_rename_new = State()
    add_admin = State()
    rem_admin = State()
    del_user = State()
    set_data = State()
    view_token_uid = State()

async def load_settings():
    global BOT_ADMINS, DATA_CHANNEL_ID, FSUB_CHANNELS, SHORTENER_OFF, PROTECT_CONTENT
    s = settings_collection.find_one({'_id': 'bot_settings'})
    if s:
        BOT_ADMINS = set(s.get('admins', [])) | {config.OWNER_ID}
        SHORTENER_OFF = s.get('shortener_disabled', False)
        PROTECT_CONTENT = s.get('protect_content', True)
    d = data_channel_collection.find_one({'_id': 'data_channel'})
    if d: DATA_CHANNEL_ID = d.get('channel_id')
    FSUB_CHANNELS = list(force_sub_channels_collection.find({}))

def is_admin(uid): return uid in BOT_ADMINS

# --- Utils ---
def str_to_b64(s): return base64.urlsafe_b64encode(s.encode()).decode()
def b64_to_str(b):
    try: return base64.urlsafe_b64decode(b.encode()).decode()
    except Exception: return ""
def get_now(): return datetime.now(timezone.utc)

async def get_short_url(long_url):
    if SHORTENER_OFF: return long_url
    c = settings_collection.find_one({'_id': 'shortener_config'})
    if not c: return long_url
    try:
        t_url = c['template_url']
        api = urllib.parse.parse_qs(urllib.parse.urlparse(t_url).query).get('api', [None])[0]
        sz = Shortzy(api_key=api)
        res = await sz.convert(long_url)
        return res if res and res.startswith("http") else long_url
    except Exception: return long_url

# --- Membership & Access Logic ---
async def check_fsub(uid):
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
    kb.row(InlineKeyboardButton(text="🔄 Check Again", callback_data="check_fsub"))
    await bot.send_message(chat_id, "<b>⚠️ Please join our channels to continue.</b>", reply_markup=kb.as_markup())

def add_prem(uid, seconds, admin=False):
    exp = get_now() + timedelta(seconds=seconds)
    tokens_collection.update_one({'user_id': uid}, {'$push': {'tokens': {'token_id': str(uuid.uuid4()), 'expires_at': exp, 'is_admin': admin, 'created_at': get_now()}}}, upsert=True)

def has_prem(uid):
    doc = tokens_collection.find_one({'user_id': uid})
    return any(t.get('expires_at') > get_now() for t in doc['tokens']) if doc and 'tokens' in doc else False

async def get_token_kb(uid):
    ac = str_to_b64(f"{uid}:{int(get_now().timestamp())}")
    uname = config.BOT_USERNAME[1:] if config.BOT_USERNAME.startswith('@') else config.BOT_USERNAME
    url = await get_short_url(f"https://t.me/{uname}?start=token_{ac}")
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🔓 Unlock Access", url=url))
    kb.row(InlineKeyboardButton(text="💎 Get VIP", url=config.BUY_BOT_URL))
    return kb.as_markup()

def can_view(uid, next_v_uuid=None):
    if has_prem(uid): return True
    u = users_collection.find_one({'user_id': uid})
    if not u: return False
    if next_v_uuid:
        h = history_collection.find_one({'user_id': uid, 'history.v_uuid': next_v_uuid})
        if h: return True
    usage = u.get('free_usage', {})
    if not usage or get_now() > usage.get('reset_at', datetime.min.replace(tzinfo=timezone.utc)):
        users_collection.update_one({'user_id': uid}, {'$set': {'free_usage': {'count': 0, 'reset_at': get_now() + timedelta(hours=config.FREE_VIDEO_RESET_HOURS)}}})
        return True
    return usage.get('count', 0) < config.DAILY_FREE_VIDEOS

def use_free(uid, v_uuid):
    if not has_prem(uid):
        h = history_collection.find_one({'user_id': uid, 'history.v_uuid': v_uuid})
        if not h:
            users_collection.update_one({'user_id': uid}, {'$inc': {'free_usage.count': 1}})

def save_history(uid, v_uuid, cat, batch_id=None):
    history_collection.update_one({'user_id': uid}, {'$push': {'history': {'v_uuid': v_uuid, 'cat': cat, 'at': get_now(), 'batch': batch_id}}}, upsert=True)

# --- Messaging & Self-Healing Media ---
async def send_v(chat_id, edit_id, v_data, kb, force=False):
    if not DATA_CHANNEL_ID: return False
    cap = f"Category: {v_data.get('category')}\n{v_data.get('custom_caption', '')}"

    if not edit_id and chat_id in active_menus:
        try: await bot.delete_message(chat_id, active_menus[chat_id]['msg_id'])
        except Exception: pass
        del active_menus[chat_id]

    try:
        sent = None
        if not force and edit_id:
            try:
                sent = await bot.edit_message_media(chat_id, edit_id, media=InputMediaVideo(media=v_data['file_id'], caption=cap), reply_markup=kb)
            except Exception: pass

        if not sent:
            if force and edit_id:
                try: await bot.delete_message(chat_id, edit_id)
                except Exception: pass
            try:
                sent = await bot.copy_message(chat_id, DATA_CHANNEL_ID, v_data['message_id'], caption=cap, reply_markup=kb, protect_content=PROTECT_CONTENT)
            except Exception:
                sent = await bot.send_video(chat_id, v_data['file_id'], caption=cap, reply_markup=kb, protect_content=PROTECT_CONTENT)

        active_menus[chat_id] = {'msg_id': sent.message_id, 'ts': get_now(), 'v_uuid': v_data['uuid']}
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
    b.row(KeyboardButton(text="👤 Profile"), KeyboardButton(text="🔖 Bookmarks"))
    if has_prem(uid): b.row(KeyboardButton(text="📱 Mini App", web_app=WebAppInfo(url=config.WEBAPP_URL)))
    return b.as_markup(resize_keyboard=True)

def v_kb(v_uuid, cat, uid, saved=False, batch_id=None, pos=0):
    b = InlineKeyboardBuilder()
    cp = "def" if cat == "default" else str_to_b64(cat)
    nav = []
    if pos > 0: nav.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"prev|{v_uuid}|{cp}|{int(saved)}|{batch_id or ''}"))
    nav.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"next|{v_uuid}|{cp}|{int(saved)}|{batch_id or ''}"))
    b.row(*nav)
    b.row(InlineKeyboardButton(text="👎", callback_data=f"vote|down|{v_uuid}"), InlineKeyboardButton(text="👍", callback_data=f"vote|up|{v_uuid}"))
    b.row(InlineKeyboardButton(text="🗑️ Remove" if saved else "💾 Save", callback_data=f"save|{v_uuid}" if not saved else f"unsave|{v_uuid}"),
          InlineKeyboardButton(text="📲 Share", callback_data=f"share|{v_uuid}"), InlineKeyboardButton(text="⬇️ Get File", callback_data=f"dl|{v_uuid}"))
    b.row(InlineKeyboardButton(text="🗂️ Categories", callback_data="show_cats"))
    return b.as_markup()

def cat_kb(saved=False):
    b = InlineKeyboardBuilder()
    c_list = sorted([x['name'] for x in categories_collection.find({})])
    for c in ["default"] + c_list:
        b.row(InlineKeyboardButton(text=c, callback_data=f"{'s' if saved else ''}cat|{str_to_b64(c)}"))
    return b.as_markup()

# --- User Handlers ---
@router.message(Command("start"))
async def start(m: Message, command: CommandObject, state: FSMContext):
    uid, arg = m.from_user.id, command.args
    await state.clear()
    if not users_collection.find_one({'user_id': uid}):
        users_collection.insert_one({'user_id': uid, 'joined': get_now(), 'refs': 0, 'bookmarks': []})
        if arg and arg.startswith('ref_'):
            try:
                rid = int(arg[4:])
                if rid != uid:
                    add_prem(rid, config.REFERRAL_BONUS * 3600)
                    users_collection.update_one({'user_id': rid}, {'$inc': {'refs': 1}})
            except Exception: pass
    if not await check_fsub(uid):
        if arg: users_collection.update_one({'user_id': uid}, {'$set': {'pending': arg}})
        return await send_fsub_msg(uid)
    if arg:
        if arg.startswith('token_'):
            if refresh_tokens_used_collection.find_one({'token': arg}):
                return await m.reply("❌ This token has already been used.")
            try:
                data = b64_to_str(arg[6:]).split(':')
                if int(data[0]) == uid:
                    add_prem(uid, config.TOKEN_EXPIRY)
                    refresh_tokens_used_collection.insert_one({'token': arg, 'uid': uid, 'at': get_now()})
                    await m.reply("✅ Access Unlocked!")
                    p = (users_collection.find_one_and_update({'user_id': uid}, {'$unset': {'pending': ""}}) or {}).get('pending')
                    if p: await start(m, CommandObject(args=p), state)
            except Exception: pass
        elif arg.startswith('video_'):
            v = media_collection.find_one({'uuid': arg[6:]})
            if v and can_view(uid, v['uuid']):
                if await send_v(uid, None, v, v_kb(v['uuid'], v['category'], uid), True):
                    use_free(uid, v['uuid']); save_history(uid, v['uuid'], v['category'])
            else: await m.reply("⚠️ Limit reached!", reply_markup=await get_token_kb(uid))
        elif arg.startswith('batch_'):
            bid = arg[6:]
            b = video_batches_collection.find_one({'batch_id': bid})
            if b:
                v = media_collection.find_one({'uuid': b['video_uuids'][0]})
                users_collection.update_one({'user_id': uid}, {'$set': {'active_batch': {'id': bid, 'vids': b['video_uuids'], 'pos': 0}}})
                await send_v(uid, None, v, v_kb(v['uuid'], v['category'], uid, batch_id=bid, pos=0), True)
    else: await m.reply("👋 <b>Welcome!</b> Choose an option below:", reply_markup=await main_kb(uid))

@router.message(F.text == "🎞️ Get Video")
async def get_vid(m: Message):
    uid = m.from_user.id
    if not await check_fsub(uid): return await send_fsub_msg(uid)
    if not can_view(uid): return await m.reply("⚠️ Limit reached!", reply_markup=await get_token_kb(uid))
    v = list(media_collection.aggregate([{'$sample': {'size': 1}}]))[0]
    if v:
        users_collection.update_one({'user_id': uid}, {'$set': {'active_session': {'vids': [v['uuid']], 'pos': 0, 'cat': 'default'}}})
        if await send_v(uid, None, v, v_kb(v['uuid'], v['category'], uid, pos=0), True):
            use_free(uid, v['uuid']); save_history(uid, v['uuid'], v['category'])

@router.message(F.text == "👤 Profile")
async def profile(m: Message):
    uid = m.from_user.id
    u = users_collection.find_one({'user_id': uid})
    prem = has_prem(uid)
    text = f"👤 <b>Profile</b>\n\n🆔 ID: <code>{uid}</code>\n💎 Status: {'Premium' if prem else 'Free'}\n👥 Refs: {u.get('refs', 0)}\n🔖 Saved: {len(u.get('bookmarks', []))}"
    await m.reply(text)

@router.message(F.text == "🔖 Bookmarks")
async def bookmarks(m: Message):
    uid = m.from_user.id
    u = users_collection.find_one({'user_id': uid})
    if not u or not u.get('bookmarks'): return await m.reply("📂 Library is empty.")
    await m.reply("📂 Select category:", reply_markup=cat_kb(saved=True))

@router.callback_query(F.data == "show_cats")
async def show_cats(cb: CallbackQuery):
    await cb.message.edit_text("📂 Select category:", reply_markup=cat_kb())

@router.callback_query(F.data.startswith("cat|"))
async def cat_sel(cb: CallbackQuery):
    uid, cat = cb.from_user.id, b64_to_str(cb.data.split('|')[1])
    v = media_collection.find_one({'category': cat}, sort=[('sequence_number', 1)])
    if v:
        users_collection.update_one({'user_id': uid}, {'$set': {'active_session': {'vids': [v['uuid']], 'pos': 0, 'cat': cat}}})
        await send_v(uid, cb.message.message_id, v, v_kb(v['uuid'], cat, uid, pos=0))
    else: await cb.answer("No videos found.")

@router.callback_query(F.data.startswith("scat|"))
async def scat_sel(cb: CallbackQuery):
    uid, cat = cb.from_user.id, b64_to_str(cb.data.split('|')[1])
    u = users_collection.find_one({'user_id': uid})
    vids = [m['uuid'] for m in u.get('bookmarks', []) if (media_collection.find_one({'uuid': m['uuid']}) or {}).get('category') == cat]
    if vids:
        v = media_collection.find_one({'uuid': vids[0]})
        users_collection.update_one({'user_id': uid}, {'$set': {'active_session': {'vids': vids, 'pos': 0, 'cat': cat, 'saved': True}}})
        await send_v(uid, cb.message.message_id, v, v_kb(v['uuid'], cat, uid, saved=True, pos=0))
    else: await cb.answer("No saved videos here.")

@router.callback_query(F.data.regexp(r"^(next|prev)\|"))
async def nav(cb: CallbackQuery):
    uid = cb.from_user.id
    if uid in nav_locks: return await cb.answer("Wait...")
    nav_locks.add(uid)
    try:
        parts = cb.data.split('|')
        action, curr_uuid, cat_b64, saved, bid = parts[0], parts[1], parts[2], bool(int(parts[3])), parts[4]
        cat = "default" if cat_b64 == "def" else b64_to_str(cat_b64)

        u = users_collection.find_one({'user_id': uid})
        sess_key = 'active_batch' if bid else 'active_session'
        sess = u.get(sess_key, {'vids': [curr_uuid], 'pos': 0})

        v = None
        if action == "next":
            next_v = None
            if sess['pos'] + 1 < len(sess['vids']):
                next_v = media_collection.find_one({'uuid': sess['vids'][sess['pos']+1]})
            elif not bid and not saved:
                next_v = media_collection.find_one({'category': cat, 'sequence_number': {'$gt': (media_collection.find_one({'uuid': curr_uuid}) or {}).get('sequence_number', 0)}}, sort=[('sequence_number', 1)])

            if next_v:
                if not can_view(uid, next_v['uuid']):
                    await cb.message.reply("⚠️ Limit reached!", reply_markup=await get_token_kb(uid))
                    return await cb.answer()
                v = next_v
                if sess['pos'] + 1 >= len(sess['vids']): sess['vids'].append(v['uuid'])
                sess['pos'] += 1
        elif action == "prev" and sess['pos'] > 0:
            v = media_collection.find_one({'uuid': sess['vids'][sess['pos']-1]})
            sess['pos'] -= 1

        if v:
            if await send_v(uid, cb.message.message_id, v, v_kb(v['uuid'], cat, uid, saved=saved, batch_id=bid, pos=sess['pos'])):
                users_collection.update_one({'user_id': uid}, {'$set': {sess_key: sess}})
                if action == "next": use_free(uid, v['uuid']); save_history(uid, v['uuid'], cat, batch_id=bid)
        else: await cb.answer("End of list.")
        await cb.answer()
    finally: nav_locks.remove(uid)

@router.callback_query(F.data.startswith("save|"))
async def save_vid(cb: CallbackQuery):
    users_collection.update_one({'user_id': cb.from_user.id}, {'$addToSet': {'bookmarks': {'uuid': cb.data[5:], 'at': get_now()}}})
    await cb.answer("Saved!")

@router.callback_query(F.data.startswith("unsave|"))
async def unsave_vid(cb: CallbackQuery):
    users_collection.update_one({'user_id': cb.from_user.id}, {'$pull': {'bookmarks': {'uuid': cb.data[7:]}}})
    await cb.answer("Removed.")

@router.callback_query(F.data.startswith("vote|"))
async def vote_cb(cb: CallbackQuery):
    vote, v_uuid = cb.data.split('|')[1:]
    media_collection.update_one({'uuid': v_uuid}, {'$inc': {f'votes.{vote}': 1}})
    await cb.answer("Voted!")

@router.callback_query(F.data.startswith("share|"))
async def share_cb(cb: CallbackQuery):
    v_uuid = cb.data[6:]
    await cb.message.reply(f"🔗 <b>Share Link:</b>\n<code>https://t.me/{config.BOT_USERNAME[1:]}?start=video_{v_uuid}</code>")
    await cb.answer()

@router.callback_query(F.data.startswith("dl|"))
async def dl_cb(cb: CallbackQuery):
    if not has_prem(cb.from_user.id): return await cb.answer("💎 Premium required for direct files!", show_alert=True)
    v = media_collection.find_one({'uuid': cb.data[3:]})
    if v:
        try: await bot.send_video(cb.from_user.id, v['file_id'], caption="✅ Here is your file.", protect_content=False)
        except Exception: await cb.answer("Error sending file.")
    await cb.answer()

@router.callback_query(F.data == "check_fsub")
async def check_fsub_cb(cb: CallbackQuery, state: FSMContext):
    if await check_fsub(cb.from_user.id):
        await cb.message.delete()
        u = users_collection.find_one({'user_id': cb.from_user.id})
        await start(cb.message, CommandObject(args=u.get('pending')), state)
    else: await cb.answer("Not joined yet!", show_alert=True)

# --- Admin Handlers ---
@router.message(Command("help"))
async def help_cmd(m: Message):
    if is_admin(m.from_user.id):
        text = "🛠️ <b>Admin Commands</b>\n\n/stats - Bot Stats\n/broadcast - Send message to all\n/addtoken [uid] [days] - Grant Premium\n/removetoken [uid] - Revoke Premium\n/addcategory - Create Category\n/deletecategory - Remove Category\n/categoryrename - Rename Category\n/deletevideo [uuid] - Delete Video\n/batchvideoadd - Create Batch Link\n/addadmin [uid] - Add Admin\n/removeadmin [uid] - Remove Admin\n/setfsub - Set Join Channels\n/setdata - Set Data Channel\n/toggle_protect - Toggle content protection\n/shortener_status - View shortener config"
        await m.reply(text)

@router.message(Command("stats"))
async def stats_cmd(m: Message):
    if is_admin(m.from_user.id): await m.reply(f"📊 <b>Bot Stats</b>\n\nUsers: {users_collection.count_documents({})}\nVideos: {media_collection.count_documents({})}")

async def send_broadcast(msg, uid):
    try:
        await msg.copy_to(uid)
        return True
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        return await send_broadcast(msg, uid)
    except Exception:
        return False

@router.message(Command("broadcast"))
async def br_cmd(m: Message, state: FSMContext):
    if is_admin(m.from_user.id): await m.reply("Send message to broadcast:"); await state.set_state(AdminStates.broadcast)

@router.message(AdminStates.broadcast)
async def proc_br(m: Message, state: FSMContext):
    await state.clear(); count, fail = 0, 0
    status = await m.reply("🚀 Starting broadcast...")
    async for u in users_collection.find({}):
        if await send_broadcast(m, u['user_id']): count += 1
        else: fail += 1
        if (count + fail) % 50 == 0:
            try: await status.edit_text(f"🚀 Broadcasting... {count} success, {fail} failed.")
            except Exception: pass
        await asyncio.sleep(0.05) # Flood prevention
    await status.edit_text(f"✅ Sent to {count} users. Failed: {fail}")

@router.message(Command(["addtoken", "addpremium"]))
async def add_t_cmd(m: Message, command: CommandObject, state: FSMContext):
    if not is_admin(m.from_user.id): return
    if command.args:
        try: uid, days = map(int, command.args.split()); add_prem(uid, days*86400, True); await m.reply(f"Added {days} days to {uid}")
        except Exception: await m.reply("Format: /addtoken [uid] [days]")
    else: await m.reply("Send User ID:"); await state.set_state(AdminStates.token_uid)

@router.message(AdminStates.token_uid)
async def t_uid_p(m: Message, state: FSMContext):
    try: await state.update_data(u=int(m.text)); await m.reply("Days:"); await state.set_state(AdminStates.token_days)
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
async def del_vid_cmd(m: Message, state: FSMContext):
    if is_admin(m.from_user.id): await m.reply("Video UUID:"); await state.set_state(AdminStates.del_vid)

@router.message(AdminStates.del_vid)
async def proc_del_vid(m: Message, state: FSMContext):
    await state.clear(); media_collection.delete_one({'uuid': m.text}); await m.reply("Deleted.")

@router.message(Command("batchvideoadd"))
async def batch_cmd(m: Message, state: FSMContext):
    if is_admin(m.from_user.id): await m.reply("UUIDs (space separated):"); await state.set_state(AdminStates.batch_vids)

@router.message(AdminStates.batch_vids)
async def proc_batch(m: Message, state: FSMContext):
    await state.clear(); bid = str(uuid.uuid4())[:8]
    batches_col.insert_one({'batch_id': bid, 'video_uuids': m.text.split(), 'at': get_now()})
    uname = config.BOT_USERNAME[1:] if config.BOT_USERNAME.startswith('@') else config.BOT_USERNAME
    await m.reply(f"Batch Link: <code>https://t.me/{uname}?start=batch_{bid}</code>")

@router.message(Command("categoryrename"))
async def ren_cmd(m: Message, state: FSMContext):
    if is_admin(m.from_user.id): await m.reply("Old Name:"); await state.set_state(AdminStates.cat_rename_old)

@router.message(AdminStates.cat_rename_old)
async def proc_ren_old(m: Message, state: FSMContext):
    await state.update_data(o=m.text); await m.reply("New Name:"); await state.set_state(AdminStates.cat_rename_new)

@router.message(AdminStates.cat_rename_new)
async def proc_ren_new(m: Message, state: FSMContext):
    d = await state.get_data(); await state.clear()
    old, new = d['o'], m.text
    categories_collection.update_one({'name': old}, {'$set': {'name': new}})
    media_collection.update_many({'category': old}, {'$set': {'category': new}})
    # Robust update across all users
    users_collection.update_many({'bookmarks.cat': old}, {'$set': {'bookmarks.$[elem].cat': new}}, array_filters=[{'elem.cat': old}])
    history_collection.update_many({'history.cat': old}, {'$set': {'history.$[elem].cat': new}}, array_filters=[{'elem.cat': old}])
    await m.reply("Updated.")

@router.message(Command("addadmin"))
async def add_adm_cmd(m: Message, state: FSMContext):
    if m.from_user.id == config.OWNER_ID: await m.reply("User ID:"); await state.set_state(AdminStates.add_admin)

@router.message(AdminStates.add_admin)
async def proc_add_adm(m: Message, state: FSMContext):
    try:
        settings_collection.update_one({'_id': 'bot_settings'}, {'$addToSet': {'admins': int(m.text)}}, upsert=True)
        await load_settings(); await m.reply("Added.")
    except: await m.reply("Invalid ID.")
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
    if is_admin(m.from_user.id): await m.reply("Channel ID:"); await state.set_state(AdminStates.fsub_id)

@router.message(AdminStates.fsub_id)
async def proc_fs_id(m: Message, state: FSMContext):
    try: await state.update_data(i=int(m.text)); await m.reply("Link:"); await state.set_state(AdminStates.fsub_link)
    except: await m.reply("Invalid ID."); await state.clear()

@router.message(AdminStates.fsub_link)
async def proc_fs_link(m: Message, state: FSMContext):
    d = await state.get_data(); await state.clear()
    force_sub_channels_collection.insert_one({'channel_id': d['i'], 'link': m.text, 'name': 'Channel'})
    await load_settings(); await m.reply("Added.")

@router.message(Command("setdata"))
async def set_data_cmd(m: Message, state: FSMContext):
    if is_admin(m.from_user.id): await m.reply("Data Channel ID:"); await state.set_state(AdminStates.set_data)

@router.message(AdminStates.set_data)
async def proc_set_data(m: Message, state: FSMContext):
    try:
        data_channel_collection.update_one({'_id': 'data_channel'}, {'$set': {'channel_id': int(m.text)}}, upsert=True)
        await load_settings(); await m.reply("Updated.")
    except: await m.reply("Error.")
    await state.clear()

@router.message(Command("viewtoken"))
async def view_t_cmd(m: Message, state: FSMContext):
    if is_admin(m.from_user.id): await m.reply("User ID:"); await state.set_state(AdminStates.view_token_uid)

@router.message(AdminStates.view_token_uid)
async def proc_view_t(m: Message, state: FSMContext):
    try:
        doc = tokens_collection.find_one({'user_id': int(m.text)})
        await m.reply(f"Tokens for {m.text}: {doc}")
    except: await m.reply("Error.")
    await state.clear()

# --- Background Tasks ---
async def cleanup():
    while True:
        try:
            for uid, data in list(active_menus.items()):
                if get_now() - data['ts'] > timedelta(minutes=config.MENU_EXPIRY_MINUTES):
                    try: await bot.delete_message(uid, data['msg_id'])
                    except Exception: pass
                    del active_menus[uid]
        except Exception: pass
        await asyncio.sleep(60)

async def monitor_ssrb_verifications():
    while True:
        try:
            for v in ssrb_verifications_collection.find({'is_consumed_by_atdb': False, 'verified': True}):
                uid = v['user_id']
                add_prem(uid, config.TOKEN_EXPIRY)
                ssrb_verifications_collection.update_one({'_id': v['_id']}, {'$set': {'is_consumed_by_atdb': True}})
                try: await bot.send_message(uid, "✅ Verification Successful! Access Granted.")
                except Exception: pass
            ssrb_verifications_collection.delete_many({'expires_at': {'$lt': get_now()}})
        except Exception as e: logger.error(f"Monitor error: {e}")
        await asyncio.sleep(30)

# --- App Start ---
@app.on_event("startup")
async def startup():
    await load_settings()
    asyncio.create_task(dp.start_polling(bot))
    asyncio.create_task(cleanup())
    asyncio.create_task(monitor_ssrb_verifications())

@app.get("/")
async def root(): return Response("OK")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
