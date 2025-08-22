#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import os
import time
from time import perf_counter
import math
import re
import uuid
import shutil
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict
from telethon import TelegramClient, events, Button
from telethon.tl.types import DocumentAttributeFilename, DocumentAttributeVideo, ReplyKeyboardForceReply
from telethon.errors import FloodWaitError, UserNotParticipantError, ChannelPrivateError
from telethon.tl.functions.messages import SetTypingRequest
from telethon.tl.types import SendMessageTypingAction, SendMessageUploadDocumentAction
from telethon.tl.functions.channels import GetParticipantRequest
import logging

# Import configuration
def get_env_or_config(attr, default=None):
    value = os.environ.get(attr)
    if value is not None:
        if attr == "API_ID":
            return int(value)
        return value
    try:
        from config import API_ID, API_HASH, TOKEN, ADMIN_IDS
        return locals()[attr]
    except Exception:
        return default

API_ID = get_env_or_config("API_ID")
API_HASH = get_env_or_config("API_HASH")
TOKEN = get_env_or_config("TOKEN")
ADMIN_IDS = get_env_or_config("ADMIN_IDS", "")
START_TIME = datetime.now(timezone.utc)




async def safe_edit(msg_obj, new_text, **kwargs):
    """
    Edit Telegram message only if content changed.
    Prevents 'EditMessageRequest: message not modified' error.
    """
    try:
        # Check if the message exists and has a 'message' attribute
        current_text = getattr(msg_obj, 'message', None)
        
        # If the text is identical, don't edit
        if current_text == new_text:
            return msg_obj
            
        # Check if the message still exists
        if not msg_obj or not hasattr(msg_obj, 'edit'):
            return msg_obj
            
        return await msg_obj.edit(new_text, **kwargs)
    except Exception as e:
        if "message not modified" in str(e).lower():
            # Silently ignore this error
            return msg_obj
        else:
            # Re-raise other errors
            raise



# 🔥 FORCE JOIN CHANNEL CONFIGURATION 🔥 (legacy single channel kept as fallback)
FORCE_JOIN_CHANNEL = "djd208"  # fallback if no channels configured in JSON

async def process_large_file_streaming(event, user_id, new_name, sess=None):
    """Re-send the original media with a new filename/caption without re-downloading.
    Mirrors the PDF bot's Edit Name behavior.
    """
    if sess is None and user_id not in user_sessions:
        return
    base_info = sess if sess is not None else user_sessions[user_id]
    original_msg = base_info.get('original_msg') or base_info.get('message')
    if not original_msg:
        return
    sanitized_name = sanitize_filename(new_name)
    
    # Apply user preferences (clean tags, custom text)
    try:
        if sessions.get(user_id, {}).get('clean_tags', True):
            sanitized_name = clean_filename_text(sanitized_name)
        custom_text = sessions.get(user_id, {}).get('custom_text', '')
        text_position = sessions.get(user_id, {}).get('text_position', 'end')
        if custom_text:
            sanitized_name = add_custom_text_to_filename(sanitized_name, custom_text, text_position)
    except Exception as e:
        logging.warning(f"Preference application failed in rename-only: {e}")
    
    # Caption matches rename-only UX
    caption = f"<code>{sanitized_name}</code>"
    
    # Determine if media is video to keep player (avoid forcing document)
    is_video = base_info.get('is_video', False)
    force_document = False if is_video else True
    
    logging.info(f"[RenameOnly] Resending media for user {user_id}: name='{sanitized_name}', is_video={is_video}, force_document={force_document}")
    
    try:
        await event.client.send_file(
            event.chat_id,
            original_msg.media,
            caption=caption,
            parse_mode='html',
            file_name=sanitized_name,
            supports_streaming=True,
            force_document=force_document
        )
        logging.info(f"[RenameOnly] send_file success for user {user_id}")
    except Exception as e:
        logging.error(f"[RenameOnly] send_file failed for user {user_id}: {e}")
        raise

# --- Admin parsing & force-join JSON (multi-channel) ---
def _parse_admin_ids(s: str):
    ids = set()
    for x in str(s or "").replace(" ", "").split(","):
        if not x:
            continue
        try:
            ids.add(int(x))
        except Exception:
            pass
    return ids

ADMIN_SET = _parse_admin_ids(ADMIN_IDS)
BASE_DIR = Path(__file__).resolve().parent
FJ_PATH = BASE_DIR / "force_join_channels.json"
fj_lock = asyncio.Lock()

def _ensure_fj_file():
    if not FJ_PATH.exists():
        FJ_PATH.write_text(json.dumps({"channels": []}, ensure_ascii=False, indent=2), encoding="utf-8")

def _normalize_channel(ref: str) -> str:
    ref = (ref or "").strip()
    if not ref:
        return ref
    if ref.startswith("@"):  # username
        return ref
    try:
        int(ref)  # allow -100...
        return ref
    except Exception:
        if "t.me/" in ref:
            tail = ref.split("t.me/", 1)[1].strip().strip("/")
            if tail and not tail.startswith("@"):  
                tail = "@" + tail
            return tail
        return ref if ref.startswith("@") else ("@" + ref)

async def load_fj_channels() -> list:
    _ensure_fj_file()
    try:
        data = json.loads(FJ_PATH.read_text(encoding="utf-8"))
        ch = data.get("channels", [])
        uniq, seen = [], set()
        for c in ch:
            nc = _normalize_channel(str(c))
            if nc and nc not in seen:
                seen.add(nc)
                uniq.append(nc)
        return uniq
    except Exception:
        return []

async def save_fj_channels(channels: list) -> None:
    _ensure_fj_file()
    FJ_PATH.write_text(json.dumps({"channels": channels}, ensure_ascii=False, indent=2), encoding="utf-8")

def get_forced_channels() -> list:
    """Get list of forced channels"""
    data = _load_json(FJ_PATH, {"channels": []})
    chans = []
    for ch in data.get("channels", []):
        c = str(ch).strip().lstrip("@").lstrip("#")
        if c and c not in chans:
            chans.append(c)
    data["channels"] = chans
    _save_json(FJ_PATH, data)
    return chans

def set_forced_channels(channels: list):
    """Set forced channels list"""
    norm = []
    for ch in channels:
        c = str(ch).strip().lstrip("@").lstrip("#")
        if c and c not in norm:
            norm.append(c)
    _save_json(FJ_PATH, {"channels": norm})

def add_forced_channels(channels: list) -> list:
    """Add channels to forced list"""
    current = set(get_forced_channels())
    for ch in channels:
        c = str(ch).strip().lstrip("@").lstrip("#")
        if c:
            current.add(c)
    set_forced_channels(list(current))
    return get_forced_channels()

def del_forced_channels(channels: list) -> list:
    """Remove channels from forced list"""
    current = set(get_forced_channels())
    for ch in channels:
        c = str(ch).strip().lstrip("@").lstrip("#")
        if c in current:
            current.remove(c)
    set_forced_channels(list(current))
    return get_forced_channels()

def _load_json(path, default):
    """Load JSON file"""
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default

def _save_json(path, data):
    """Save JSON file"""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Error saving {path.name}: {e}")

# Configuration
MAX_FILE_SIZE = 2000 * 1024 * 1024  # 2 GB
TEMP_DIR = "temp_files"
THUMBNAIL_DIR = "thumbnails"
DOWNLOAD_DIR = "downloads"  # New directory to store files
USER_TIMEOUT = 600  # 10 minutes
PROGRESS_UPDATE_INTERVAL = 5  # seconds
MAX_THUMB_SIZE = 200 * 1024  # 200 KB

# New limits
DAILY_LIMIT_GB = 2  # 2 GB per day per user
DAILY_LIMIT_BYTES = DAILY_LIMIT_GB * 1024 * 1024 * 1024
COOLDOWN_SECONDS = 30  # 30 seconds between files

# Logging configuration
logging.basicConfig(
    format='[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s',
    level=logging.INFO
)

# Create necessary directories
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(THUMBNAIL_DIR, exist_ok=True)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)  # New directory

# Initialize the Telethon client
bot = TelegramClient('rename_bot', API_ID, API_HASH).start(bot_token=TOKEN)

# Rename stats (JSON local)
RENAME_STATS_PATH = os.path.join(os.path.dirname(__file__), 'rename_stats.json')
_rename_lock = asyncio.Lock()

def _ensure_rename_stats_file():
    if not os.path.exists(RENAME_STATS_PATH):
        with open(RENAME_STATS_PATH, 'w', encoding='utf-8') as f:
            json.dump({"total_files_renamed": 0, "total_storage_bytes": 0}, f, ensure_ascii=False, indent=2)

async def load_rename_stats() -> dict:
    _ensure_rename_stats_file()
    try:
        with open(RENAME_STATS_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {"total_files_renamed": 0, "total_storage_bytes": 0}

async def add_rename_stat(file_size_bytes: int) -> None:
    _ensure_rename_stats_file()
    async with _rename_lock:
        try:
            with open(RENAME_STATS_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            data = {"total_files_renamed": 0, "total_storage_bytes": 0}
        data["total_files_renamed"] = int(data.get("total_files_renamed", 0)) + 1
        inc = int(file_size_bytes or 0)
        data["total_storage_bytes"] = int(data.get("total_storage_bytes", 0)) + max(0, inc)
        with open(RENAME_STATS_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

# Dictionary to store user sessions (legacy: single active)
user_sessions = {}
# Processing locks to avoid double-click race per (chat_id, msg_id)
PROCESSING_LOCKS = defaultdict(asyncio.Lock)

# Hybrid stateless cache of original messages to avoid get_messages issues in private chats
# Key: (chat_id, msg_id) -> Value: { 'message': Message, 'file_name': str, 'file_size': int, 'is_video': bool, 'mime_type': str, 'timestamp': datetime }
ORIGINAL_MESSAGES = {}
MESSAGE_CLEANUP_TIME = 3600  # seconds (1 hour)

async def cleanup_old_messages():
    """Remove cached message references older than MESSAGE_CLEANUP_TIME."""
    try:
        now = datetime.now()
        to_delete = []
        for key, data in list(ORIGINAL_MESSAGES.items()):
            ts = data.get('timestamp')
            if not ts:
                continue
            if (now - ts).total_seconds() > MESSAGE_CLEANUP_TIME:
                to_delete.append(key)
        for k in to_delete:
            ORIGINAL_MESSAGES.pop(k, None)
        if to_delete:
            logging.info(f"Cleaned {len(to_delete)} old message references")
    except Exception as e:
        logging.error(f"Error in cleanup_old_messages: {e}")

# =============================
# Per-user Thumbnail Queue/Worker
# =============================
THUMB_QUEUES = {}
THUMB_WORKERS = {}
THUMB_USER_LOCKS = defaultdict(asyncio.Lock)

class _SimpleEvent:
    def __init__(self, chat_id, client):
        self.chat_id = chat_id
        self.client = client
    async def reply(self, *args, **kwargs):
        return await self.client.send_message(self.chat_id, *args, **kwargs)

def ensure_thumb_worker(user_id: int):
    task = THUMB_WORKERS.get(user_id)
    if task and not task.done():
        return
    q = THUMB_QUEUES.setdefault(user_id, asyncio.Queue())
    THUMB_WORKERS[user_id] = asyncio.create_task(_thumb_worker(user_id, q))

async def _thumb_worker(user_id: int, q: asyncio.Queue):
    try:
        while True:
            job = await q.get()
            try:
                logging.info(f"[THUMB] Start job for user {user_id}; queue size before start: {q.qsize()} name={job.get('new_name')}")
                async with THUMB_USER_LOCKS[user_id]:
                    # Build a lightweight event wrapper for progress messages
                    evt = _SimpleEvent(job['chat_id'], bot)
                    await process_with_thumbnail(evt, user_id, job['new_name'], sess=job['sess'])
                logging.info(f"[THUMB] Finished job for user {user_id}; remaining in queue: {q.qsize()}")
                # After successful processing, cleanup cached original message
                try:
                    storage_key = (job.get('sess') or {}).get('storage_key')
                    if storage_key:
                        ORIGINAL_MESSAGES.pop(storage_key, None)
                except Exception:
                    pass
            except Exception as e:
                try:
                    await bot.send_message(job['chat_id'], f"❌ Error in queued thumbnail: {e}", parse_mode='html')
                except Exception:
                    pass
            finally:
                q.task_done()
            # If queue becomes empty, stop worker until next enqueue
            if q.empty():
                break
    finally:
        THUMB_WORKERS.pop(user_id, None)

# Usage limits system
user_usage = defaultdict(lambda: {'daily_bytes': 0, 'last_reset': None, 'last_file_time': None})
usage_file = "user_usage.json"

# User preferences system
sessions = {}  # To store user preferences

# HELPER FUNCTION TO GET LOCAL FILE PATH
def get_local_file_path(user_id, file_id, extension):
    """Returns the local path of a file"""
    user_dir = os.path.join(DOWNLOAD_DIR, str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    return os.path.join(user_dir, f"{file_id}{extension}")

# 🔥 FORCE JOIN CHANNEL FUNCTIONS 🔥 (multi-channel)
async def is_user_in_required_channels(user_id):
    """Return (ok, missing_list). Admins bypass. If no JSON channels, fallback to FORCE_JOIN_CHANNEL."""
    if user_id in ADMIN_SET:
        return True, []
    channels = get_forced_channels()
    if not channels:
        # Fallback to single channel config if set
        channels = [FORCE_JOIN_CHANNEL] if FORCE_JOIN_CHANNEL else []
        if not channels:
            return True, []
    missing = []
    for ch in channels:
        try:
            await bot(GetParticipantRequest(channel=ch, participant=user_id))
        except UserNotParticipantError:
            missing.append(ch)
        except ChannelPrivateError:
            logging.error(f"No access to channel {ch}")
            missing.append(ch)
        except Exception as e:
            logging.error(f"Channel verification error for {ch}: {e}")
            missing.append(ch)
    return (len(missing) == 0), missing

async def send_force_join_message(event, missing_channels=None):
    """Sends the message asking the user to join required channels"""
    channels = missing_channels or get_forced_channels() or ([FORCE_JOIN_CHANNEL] if FORCE_JOIN_CHANNEL else [])
    buttons = []
    for ch in channels:
        label = ch if str(ch).startswith('@') else f"{ch}"
        url = f"https://t.me/{label.lstrip('@')}"
        buttons.append([Button.url(f"📢 Join {label}", url)])
    buttons.append([Button.inline("✅ I have joined", "check_joined")])

    links = "\n".join(f"• {ch}" for ch in channels)
    message = (
        "🚫 <b>Access Denied!</b>\n\n"
        "To use this bot, you must first join these channels:\n"
        f"{links}\n\n"
        "✅ Click the buttons below to join.\n"
        "Once done, click \"I have joined\" to continue.\n\n"
        "<i>Thank you for your support! 💙</i>"
    )
    await event.reply(message, parse_mode='html', buttons=buttons)


# --- Admin helpers ---
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_SET


def uptime_str() -> str:
    delta = datetime.now(timezone.utc) - START_TIME
    d = delta.days
    h, rem = divmod(delta.seconds, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)


def format_bytes(num: float) -> str:
    try:
        n = float(num or 0)
    except Exception:
        n = 0.0
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024.0
        i += 1
    return f"{n:.2f} {units[i]}"


# --- Admin commands: /addfsub /delfsub /channels ---
@bot.on(events.NewMessage(pattern=r"/addfsub(?:\s+.*)?"))
async def addfsub_cmd(event):
    user_id = event.sender_id
    if not is_admin(user_id):
        await event.reply("🚫 Admins only.")
        return
    text = event.raw_text or event.text or ""
    parts = text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await event.reply(
            "Usage: /addfsub <@username|chat_id> [others…]\n"
            "Examples: /addfsub @myChannel  -100123456789  t.me/mychannel"
        )
        return
    raw = re.split(r"[,\s]+", parts[1].strip())
    chans = [x for x in (s.lstrip("@").lstrip("#") for s in raw) if x]
    new_list = add_forced_channels(chans)
    await event.reply("✅ Forced-sub channels updated:\n" + "\n".join(f"• @{c}" for c in new_list))


@bot.on(events.NewMessage(pattern=r"/delfsub(?:\s+.*)?"))
async def delfsub_cmd(event):
    user_id = event.sender_id
    if not is_admin(user_id):
        await event.reply("🚫 Admins only.")
        return
    text = event.raw_text or event.text or ""
    parts = text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        set_forced_channels([])
        await event.reply("✅ All forced-sub channels removed.")
        return
    raw = re.split(r"[,\s]+", parts[1].strip())
    chans = [x for x in (s.lstrip("@").lstrip("#") for s in raw) if x]
    new_list = del_forced_channels(chans)
    if new_list:
        await event.reply("✅ Remaining forced-sub channels:\n" + "\n".join(f"• @{c}" for c in new_list))
    else:
        await event.reply("✅ No forced-sub channels configured.")


@bot.on(events.NewMessage(pattern=r"/channels$"))
async def channels_cmd(event):
    user_id = event.sender_id
    if not is_admin(user_id):
        await event.reply("🚫 Admins only.")
        return
    chans = get_forced_channels()
    if not chans:
        await event.reply("ℹ️ No forced-sub channels configured.")
        return
    await event.reply("📋 Forced-sub channels:\n" + "\n".join(f"• @{c}" for c in chans))

def clean_filename_text(text):
    """Cleans the text by removing all @usernames and hashtags"""
    if not text:
        return text
    # Remove all @username formats
    text = re.sub(r'[\[\(\{]?@\w+[\]\)\}]?', '', text, flags=re.IGNORECASE)
    # Remove hashtags
    text = re.sub(r'#\w+', '', text, flags=re.IGNORECASE)
    # Remove multiple spaces
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def add_custom_text_to_filename(filename, custom_text=None, position='end'):
    """Adds a custom text to the filename"""
    if not custom_text:
        return filename
    
    name, ext = os.path.splitext(filename)
    
    # Clean up the existing name first
    name = clean_filename_text(name)
    
    # Add custom text
    if position == 'end':
        name = f"{name} {custom_text}"
    else:  # start
        name = f"{custom_text} {name}"
    
    # Clean up multiple spaces
    name = re.sub(r'\s+', ' ', name).strip()
    
    return f"{name}{ext}"

 

def save_user_preferences():
    """Saves user preferences"""
    try:
        prefs = {}
        for user_id, session in sessions.items():
            if 'custom_text' in session or 'text_position' in session or 'clean_tags' in session:
                prefs[str(user_id)] = {
                    'custom_text': session.get('custom_text', ''),
                    'text_position': session.get('text_position', 'end'),
                    'clean_tags': session.get('clean_tags', True)
                }
        
        with open('user_preferences.json', 'w') as f:
            json.dump(prefs, f, indent=2)
    except Exception as e:
        logging.error(f"Error saving preferences: {e}")

def load_user_preferences():
    """Loads user preferences"""
    try:
        if os.path.exists('user_preferences.json'):
            with open('user_preferences.json', 'r') as f:
                prefs = json.load(f)
                for user_id_str, pref_data in prefs.items():
                    user_id = int(user_id_str)
                    sessions[user_id] = pref_data
    except Exception as e:
        logging.error(f"Error loading preferences: {e}")




def load_user_usage():
    """Loads usage data from the file"""
    try:
        if os.path.exists(usage_file):
            with open(usage_file, 'r') as f:
                data = json.load(f)
                for user_id_str, usage_data in data.items():
                    user_id = int(user_id_str)
                    user_usage[user_id] = usage_data
    except Exception as e:
        logging.error(f"Error loading usage: {e}")

def save_user_usage():
    """Saves usage data to the file"""
    try:
        data = {}
        for user_id, usage_data in user_usage.items():
            data[str(user_id)] = usage_data
        with open(usage_file, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logging.error(f"Error saving usage: {e}")

def reset_daily_usage_if_needed(user_id):
    """Resets daily usage if needed"""
    now = datetime.now()
    last_reset = user_usage[user_id].get('last_reset')
    
    if last_reset:
        last_reset = datetime.fromisoformat(last_reset)
        if now.date() > last_reset.date():
            user_usage[user_id]['daily_bytes'] = 0
            user_usage[user_id]['last_reset'] = now.isoformat()
            logging.info(f"Daily reset for user {user_id}")
    else:
        user_usage[user_id]['last_reset'] = now.isoformat()

def check_user_limits(user_id, file_size):
    """Checks user limits"""
    reset_daily_usage_if_needed(user_id)
    
    # Check daily limit
    current_daily = user_usage[user_id]['daily_bytes']
    if current_daily + file_size > DAILY_LIMIT_BYTES:
        remaining = DAILY_LIMIT_BYTES - current_daily
        return False, f"Daily limit reached! Used: {human_readable_size(current_daily)}/{human_readable_size(DAILY_LIMIT_BYTES)}. Remaining: {human_readable_size(remaining)}"
    
    # Check cooldown between files
    last_file_time = user_usage[user_id].get('last_file_time')
    if last_file_time:
        last_file_time = datetime.fromisoformat(last_file_time)
        time_since_last = (datetime.now() - last_file_time).total_seconds()
        if time_since_last < COOLDOWN_SECONDS:
            remaining_cooldown = COOLDOWN_SECONDS - time_since_last
            return False, f"Please wait {int(remaining_cooldown)} seconds before the next file"
    
    return True, "OK"

def update_user_usage(user_id, file_size):
    """Updates user usage"""
    user_usage[user_id]['daily_bytes'] += file_size
    user_usage[user_id]['last_file_time'] = datetime.now().isoformat()
    save_user_usage()

def get_user_usage_info(user_id):
    """Returns user usage information"""
    reset_daily_usage_if_needed(user_id)
    daily_used = user_usage[user_id]['daily_bytes']
    daily_remaining = DAILY_LIMIT_BYTES - daily_used
    
    return {
        'daily_used': daily_used,
        'daily_remaining': daily_remaining,
        'daily_limit': DAILY_LIMIT_BYTES,
        'percentage': (daily_used / DAILY_LIMIT_BYTES) * 100
    }

async def cleanup_user_files(user_id):
    """Cleans up all user files (except thumbnails)"""
    try:
        # Delete user's temporary files
        for filename in os.listdir(TEMP_DIR):
            if filename.startswith(f"{user_id}_"):
                filepath = os.path.join(TEMP_DIR, filename)
                try:
                    if os.path.isfile(filepath):
                        os.remove(filepath)
                        logging.info(f"User file deleted: {filename}")
                except Exception as e:
                    logging.error(f"Error deleting file {filename}: {e}")
        
        # Clean up sessions
        if user_id in user_sessions:
            if 'temp_path' in user_sessions[user_id]:
                try:
                    os.remove(user_sessions[user_id]['temp_path'])
                except:
                    pass
            del user_sessions[user_id]

        # Legacy per-message sessions removed in stateless refactor
            
        logging.info(f"Full cleanup completed for user {user_id}")
        return True
    except Exception as e:
        logging.error(f"Error cleaning up user {user_id}: {e}")
        return False

# PERIODIC FILE LOCAL CLEANUP FUNCTION
async def cleanup_old_downloads():
    """Cleans up files older than 7 days"""
    try:
        current_time = time.time()
        for user_folder in os.listdir(DOWNLOAD_DIR):
            user_path = os.path.join(DOWNLOAD_DIR, user_folder)
            if os.path.isdir(user_path):
                for filename in os.listdir(user_path):
                    file_path = os.path.join(user_path, filename)
                    if os.path.isfile(file_path):
                        file_age = current_time - os.path.getmtime(file_path)
                        if file_age > 7 * 24 * 3600:  # 7 days
                            try:
                                os.remove(file_path)
                                logging.info(f"Deleted old file: {file_path}")
                            except:
                                pass
    except Exception as e:
        logging.error(f"Error in cleanup_old_downloads: {e}")

async def auto_cleanup_task():
    """Automatic cleanup task that runs every hour"""
    while True:
        try:
            await asyncio.sleep(3600)  # 1 hour
            
            # Clean up expired sessions
            await clean_old_sessions()
            
            # Clean up orphaned files
            current_time = time.time()
            for filename in os.listdir(TEMP_DIR):
                filepath = os.path.join(TEMP_DIR, filename)
                if os.path.isfile(filepath):
                    file_age = current_time - os.path.getmtime(filepath)
                    if file_age > 3600:  # More than 1 hour
                        try:
                            os.remove(filepath)
                            logging.info(f"Orphaned file deleted: {filename}")
                        except Exception as e:
                            logging.error(f"Error deleting orphaned {filename}: {e}")
            
            # Clean up old downloads
            await cleanup_old_downloads()
            
            logging.info("Automatic cleanup completed")
            
        except Exception as e:
            logging.error(f"Automatic cleanup error: {e}")
            await asyncio.sleep(300)  # Wait 5 minutes in case of error

def human_readable_size(size_bytes):
    """Converts bytes to a human-readable format"""
    if size_bytes == 0:
        return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return "{} {}".format(s, size_name[i])

def sanitize_filename(filename):
    """Cleans up the filename to avoid issues"""
    # Remove forbidden characters
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # Remove spaces at beginning/end
    filename = filename.strip('. ')
    # Limit length
    name, ext = os.path.splitext(filename)
    if len(name) > 200:
        name = name[:200]
    return name + ext



def get_video_duration(file_path):
    """Gets the duration of a video with ffprobe"""
    try:
        import subprocess
        import json
        
        # If ffprobe is not available, return None
        if not shutil.which("ffprobe"):
            return None
            
        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', file_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        if result.returncode == 0:
            data = json.loads(result.stdout)
            duration = float(data.get('format', {}).get('duration', 0))
            return int(duration)
    except:
        pass
    return None

def get_video_dimensions(file_path):
    """Gets the dimensions of a video with ffprobe"""
    try:
        import subprocess
        import json
        
        if not shutil.which("ffprobe"):
            return None, None
            
        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', '-select_streams', 'v:0', file_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        if result.returncode == 0:
            data = json.loads(result.stdout)
            streams = data.get('streams', [])
            if streams:
                width = streams[0].get('width', 0)
                height = streams[0].get('height', 0)
                return width, height
    except:
        pass
    return None, None

def get_video_attributes(file_path, sanitized_name):
    """Create optimized video attributes for streaming"""
    duration = get_video_duration(file_path)
    width, height = get_video_dimensions(file_path)
    
    # Default values if we cannot detect them
    if not width or not height:
        width, height = 1280, 720  # Default HD
    if not duration:
        duration = 0
    
    attributes = [
        DocumentAttributeFilename(sanitized_name),
        DocumentAttributeVideo(
            duration=duration,
            w=width,
            h=height,
            supports_streaming=True,  # ✅ CRUCIAL!
            round_message=False
        )
    ]
    
    return attributes

async def ensure_video_compatibility(file_path, progress_msg=None):
    """Optimized version - avoid conversion unless absolutely necessary"""
    
    # NEW: Check file size
    file_size = os.path.getsize(file_path)
    if file_size > 100 * 1024 * 1024:  # If > 100 MB
        # Do NOT convert large files
        return file_path
    
    # Proceed for smaller files...
    # Check codec with ffprobe
    if not shutil.which("ffprobe"):
        return file_path  # No ffprobe, keep the file as-is
    
    try:
        import subprocess
        import json
        
        # Get codec information
        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', file_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        if result.returncode == 0:
            data = json.loads(result.stdout)
            streams = data.get('streams', [])
            
            video_codec = None
            audio_codec = None
            
            for stream in streams:
                if stream['codec_type'] == 'video':
                    video_codec = stream.get('codec_name', '')
                elif stream['codec_type'] == 'audio':
                    audio_codec = stream.get('codec_name', '')
            
            # If already H264/AAC, no need to convert
            if video_codec == 'h264' and audio_codec == 'aac':
                return file_path
            
            # Otherwise, convert
            if progress_msg:
                await safe_edit(progress_msg, "Converting video for better compatibility...", parse_mode='html')
            
            output_path = file_path.replace('.', '_converted.')
            
            # FFmpeg command optimized for Telegram
            cmd = [
                'ffmpeg', '-i', file_path,
                '-c:v', 'libx264',           # Video codec H.264
                '-c:a', 'aac',               # Audio codec AAC
                '-preset', 'fast',           # Fast conversion
                '-movflags', '+faststart',   # 
                '-map', '0:v:0?',
                '-map', '0:a:0?',
                output_path
            ]
            
            subprocess.run(cmd, check=True, capture_output=True)
            
            # Remove original and return converted
            os.remove(file_path)
            return output_path
            
    except Exception as e:
        logging.warning(f"Video conversion failed: {e}")
        return file_path  # On error, keep the original

async def progress_callback(current, total, event, start_time, progress_msg, action="Downloading", last_update_time=None):
    """Callback to display progress"""
    now = time.time()
    
    # Avoid too frequent updates
    if last_update_time is not None:
        if now - last_update_time[0] < PROGRESS_UPDATE_INTERVAL:
            return
        last_update_time[0] = now
    
    diff = now - start_time
    
    # Avoid division by zero at the very beginning
    if diff == 0:
        diff = 1

    percentage = current * 100 / total
    speed = current / diff
    time_to_completion = round((total - current) / speed) if speed > 0 else 0
    
    progress_bar_length = 10
    completed_length = int(percentage / 10)
    progress_bar = '▓' * completed_length + '░' * (progress_bar_length - completed_length)
    
    text = """<b>{} File...</b>

<code>{}</code> {:.1f}%

📊 <b>Progress:</b> {} / {}
⚡ <b>Speed:</b> {}/s
⏱ <b>ETA:</b> {}s
""".format(
        action,
        progress_bar,
        percentage,
        human_readable_size(current),
        human_readable_size(total),
        human_readable_size(speed),
        time_to_completion
    )
    
    # Avoid redundant edits by checking the last text
    if hasattr(progress_msg, '_last_progress_text') and progress_msg._last_progress_text == text:
        return
    
    try:
        await safe_edit(progress_msg, text, parse_mode='html')
        # Store the last sent text
        progress_msg._last_progress_text = text
    except FloodWaitError as e:
        logging.warning(f"Rate limit hit in progress_callback. Sleeping for {e.seconds} seconds.")
        await asyncio.sleep(e.seconds)
    except Exception as e:
        # Silently ignore edit errors
        if "message not modified" not in str(e).lower():
            logging.debug(f"Progress callback error: {e}")
        pass

async def clean_old_sessions():
    """Cleans up expired sessions"""
    current_time = datetime.now()
    expired_users = []
    
    for user_id, data in user_sessions.items():
        if current_time - data['timestamp'] > timedelta(seconds=USER_TIMEOUT):
            expired_users.append(user_id)
    
    for user_id in expired_users:
        if 'temp_path' in user_sessions[user_id]:
            try:
                os.remove(user_sessions[user_id]['temp_path'])
            except:
                pass
        del user_sessions[user_id]

    # Legacy per-message session cleanup removed

# 🔥 HANDLER FOR THE "I HAVE JOINED" BUTTON 🔥
@bot.on(events.CallbackQuery(data="check_joined"))
async def check_joined_handler(event):
    user_id = event.query.user_id
    ok, missing = await is_user_in_required_channels(user_id)
    if ok:
        await event.answer("✅ Thank you! You can now use the bot.", alert=True)
        await event.delete()
        # Show welcome message
        await bot.send_message(user_id, "/start")
    else:
        await event.answer("❌ You haven't joined all channels yet!", alert=True)

@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    """Improved handler for the /start command"""
    user_id = event.sender_id
    
    # 🔥 FORCE JOIN CHECK 🔥
    ok, missing = await is_user_in_required_channels(user_id)
    if not ok:
        await send_force_join_message(event, missing)
        return
    
    # Load data if not already done
    if not hasattr(start_handler, 'data_loaded'):
        load_user_usage()
        load_user_preferences()
        start_handler.data_loaded = True
    
    # Get usage information
    usage_info = get_user_usage_info(user_id)
    
    # Check if user has a custom text
    custom_text = sessions.get(user_id, {}).get('custom_text', '')
    
    welcome_text = """👋 <b>Welcome to Advanced File Rename Bot!</b>

Send me any file and I'll help you rename it.

<b>📋 Features:</b>
• Support all file types (up to 2 GB)
• Custom text/username addition
• Fast thumbnail processing ⚡
• Auto-cleanup of @tags and #hashtags
• Video streaming support 🎬"""
    
    if custom_text:
        welcome_text += f"\n• Custom text: <code>{custom_text}</code>"
    
    welcome_text += f"""

<b>📊 Your Daily Usage:</b>
• Used: {human_readable_size(usage_info['daily_used'])} / {human_readable_size(usage_info['daily_limit'])} ({usage_info['percentage']:.1f}%)
• Remaining: {human_readable_size(usage_info['daily_remaining'])}
• Cooldown: {COOLDOWN_SECONDS} seconds between files

<b>🎯 Commands:</b>
/start - Show this message
/settings - Configure bot settings ⚙️
/usage - Check your usage limits
/status - Show bot status 📊
/setthumb - Set custom thumbnail
/delthumb - Delete custom thumbnail
/showthumb - Show current thumbnail
/cancel - Cancel current operation
/cleanup - Clean temporary files 🧹

<b>🔧 Admin Commands:</b>
/channels - Show force join channels
/addfsub - Add force join channel
/delfsub - Remove force join channel

<b>📤 Just send me a file to get started!</b>"""
    
    # Settings button
    keyboard = [
        [Button.inline("⚙️ Settings", "show_settings")]
    ]
    
    await event.reply(welcome_text, parse_mode='html', buttons=keyboard)

@bot.on(events.NewMessage(pattern='/cancel'))
async def cancel_handler(event):
    """Handler to cancel the current operation"""
    user_id = event.sender_id
    
    if user_id in user_sessions:
        if 'temp_path' in user_sessions[user_id]:
            try:
                os.remove(user_sessions[user_id]['temp_path'])
            except:
                pass
        del user_sessions[user_id]
        await event.reply("❌ <b>Operation cancelled.</b>", parse_mode='html')
    else:
        await event.reply("ℹ️ No active operation to cancel.")

@bot.on(events.NewMessage(pattern='/status'))
async def status_handler(event):
    """Enhanced status output similar to uploader bot."""
    active_sessions = len(PROCESSING_LOCKS)

    # Ping
    start = perf_counter()
    try:
        await bot.get_me()
    except Exception:
        pass
    ping_ms = (perf_counter() - start) * 1000

    # RAM/CPU (optional psutil)
    try:
        import psutil  # type: ignore
        vm = psutil.virtual_memory()
        ram_line = f"{vm.percent:.1f}% ({vm.used/1024/1024/1024:.2f} GB / {vm.total/1024/1024/1024:.2f} GB)"
        cpu_line = f"{psutil.cpu_percent(interval=0.1):.1f}%"
    except Exception:
        ram_line = "N/A"
        cpu_line = "N/A"

    # Disk usage
    try:
        import shutil as _sh
        total_b, used_b, free_b = _sh.disk_usage(os.getcwd())
        used_pct = used_b / total_b * 100 if total_b else 0.0
        slots = 12
        filled = max(0, min(slots, int((used_pct / 100) * slots)))
        bar = "[" + ("■" * filled) + ("□" * (slots - filled)) + "]"
        disk_block = (
            f"┎ DISK :\n"
            f"┃ {bar} {used_pct:.1f}%\n"
            f"┃ Used : {used_b/1024/1024/1024:.2f} GB\n"
            f"┃ Free : {free_b/1024/1024/1024:.2f} GB\n"
            f"┖ Total : {total_b/1024/1024/1024:.2f} GB\n"
        )
    except Exception:
        disk_block = "┎ DISK :\n┖ N/A\n"

    # Rename stats
    try:
        stats = await load_rename_stats()
        total_renamed = int(stats.get("total_files_renamed", 0))
        total_storage_used = float(stats.get("total_storage_bytes", 0.0))
    except Exception:
        total_renamed = 0
        total_storage_used = 0.0

    text = (
        "⌬ BOT STATISTICS :\n\n"
        f"┎ Bᴏᴛ Uᴘᴛɪᴍᴇ : {uptime_str()}\n"
        f"┃ Cᴜʀʀᴇɴᴛ Pɪɴɢ : {ping_ms:.3f}ms\n"
        f"┖ Aᴄᴛɪᴠᴇ Sᴇssɪᴏɴs: {active_sessions}\n\n"
        f"┎ RAM ( MEMORY ):\n"
        f"┖ {ram_line}\n\n"
        f"┎ CPU ( USAGE ) :\n"
        f"┖ {cpu_line}\n\n"
        f"{disk_block}"
        f"┎ RENAME STATISTICS :\n"
        f"┃ Files renamed : {total_renamed}\n"
        f"┖ Storage used : {format_bytes(total_storage_used)}\n"
    )
    await event.reply(text, parse_mode='html')

@bot.on(events.NewMessage(pattern='/usage'))
async def usage_handler(event):
    """Handler to check user usage"""
    user_id = event.sender_id
    
    # 🔥 FORCE JOIN CHECK 🔥
    ok, missing = await is_user_in_required_channels(user_id)
    if not ok:
        await send_force_join_message(event, missing)
        return
    
    usage_info = get_user_usage_info(user_id)
    
    # Create a progress bar
    progress_bar_length = 20
    completed_length = int((usage_info['percentage'] / 100) * progress_bar_length)
    progress_bar = '█' * completed_length + '░' * (progress_bar_length - completed_length)
    
    usage_text = """📊 <b>Your Usage Statistics</b>

<b>Daily Limit:</b> {}
<b>Used Today:</b> {} ({:.1f}%)
<b>Remaining:</b> {}

<code>{}</code>

<b>Next Reset:</b> Tomorrow at 00:00
<b>Cooldown:</b> {} seconds between files

<i>Keep track of your usage!</i>""".format(
        human_readable_size(usage_info['daily_limit']),
        human_readable_size(usage_info['daily_used']),
        usage_info['percentage'],
        human_readable_size(usage_info['daily_remaining']),
        progress_bar,
        COOLDOWN_SECONDS
    )
    
    await event.reply(usage_text, parse_mode='html')

@bot.on(events.NewMessage(pattern='/settings'))
async def settings_command(event):
    """Handler for the /settings command"""
    user_id = event.sender_id
    
    # 🔥 FORCE JOIN CHECK 🔥
    ok, missing = await is_user_in_required_channels(user_id)
    if not ok:
        await send_force_join_message(event, missing)
        return
    
    await show_settings_menu(event)

async def show_settings_menu(event):
    """Displays the settings menu"""
    user_id = event.sender_id if hasattr(event, 'sender_id') else event.query.user_id
    
    # Load preferences if necessary
    if user_id not in sessions:
        sessions[user_id] = {}
    
    custom_text = sessions.get(user_id, {}).get('custom_text', '')
    text_position = sessions.get(user_id, {}).get('text_position', 'end')
    clean_tags = sessions.get(user_id, {}).get('clean_tags', True)
    
    text = "⚙️ <b>Bot Settings</b>\n\n"
    
    if custom_text:
        text += f"📝 Custom text: <code>{custom_text}</code>\n"
        text += f"📍 Position: {text_position}\n"
    else:
        text += "📝 No custom text set\n"
    
    text += f"🧹 Auto-clean tags: {'Yes' if clean_tags else 'No'}\n\n"
    text += "Choose an option:"
    
    keyboard = [
        [Button.inline("➕ Add/Edit Custom Text", "add_custom_text")],
        [Button.inline("📍 Change Position", "change_text_position")],
        [Button.inline("🗑️ Remove Custom Text", "remove_custom_text")],
        [Button.inline("🧹 Toggle Clean Tags", "toggle_clean_tags")],
        [Button.inline("❌ Close", "close_settings")]
    ]
    
    if isinstance(event, events.NewMessage.Event):
        await event.reply(text, parse_mode='html', buttons=keyboard)
    else:
        await event.edit(text, parse_mode='html', buttons=keyboard)

@bot.on(events.NewMessage(pattern='/cleanup'))
async def cleanup_handler(event):
    """Handler to clean up user files (admin only)"""
    user_id = event.sender_id
    
    # Check if user is admin
    admin_list = [int(x) for x in str(ADMIN_IDS).split(',') if x.strip()] if ADMIN_IDS else []
    
    if user_id not in admin_list:
        await event.reply("❌ <b>Access denied.</b> This command is for administrators only.", parse_mode='html')
        return
    
    # Clean up user files
    success = await cleanup_user_files(user_id)
    
    if success:
        await event.reply("✅ <b>Cleanup completed!</b>\n\nAll user files have been cleaned (thumbnails preserved).", parse_mode='html')
    else:
        await event.reply("❌ <b>Cleanup failed.</b>\n\nSome files could not be deleted.", parse_mode='html')

@bot.on(events.NewMessage(pattern='/setthumb'))
async def setthumb_handler(event):
    """Handler to set a thumbnail"""
    user_id = event.sender_id
    
    # 🔥 FORCE JOIN CHECK 🔥
    ok, missing = await is_user_in_required_channels(user_id)
    if not ok:
        await send_force_join_message(event, missing)
        return
    
    # Store that the user wants to set a thumbnail
    user_sessions[user_id] = {
        'action': 'set_thumbnail',
        'timestamp': datetime.now()
    }
    
    # Check if user already has a thumbnail
    existing_thumb = os.path.join(THUMBNAIL_DIR, f"{user_id}.jpg")
    has_existing = os.path.exists(existing_thumb)
    
    message = "🖼️ <b>Send me a photo to set as thumbnail</b>\n\n"
    
    if has_existing:
        message += "⚠️ <b>Note:</b> You already have a thumbnail. The new one will replace it.\n\n"
    
    message += """Requirements:
- Must be a photo (not document)
- Size limit: 200 KB
- Format: JPEG/PNG

💡 <b>Tips for video thumbnails:</b>
- Use 16:9 aspect ratio for best results
- Bright, clear images work better
- Avoid text-heavy thumbnails

Send /cancel to abort."""
    
    await event.reply(message, parse_mode='html')

@bot.on(events.NewMessage(pattern='/delthumb'))
async def delthumb_handler(event):
    """Handler to delete the thumbnail"""
    user_id = event.sender_id
    
    # 🔥 FORCE JOIN CHECK 🔥
    ok, missing = await is_user_in_required_channels(user_id)
    if not ok:
        await send_force_join_message(event, missing)
        return
    
    thumb_path = os.path.join(THUMBNAIL_DIR, "{}.jpg".format(user_id))
    
    if os.path.exists(thumb_path):
        try:
            os.remove(thumb_path)
            await event.reply("✅ <b>Thumbnail deleted successfully!</b>", parse_mode='html')
        except Exception as e:
            await event.reply("❌ <b>Error deleting thumbnail:</b> {}".format(str(e)), parse_mode='html')
    else:
        await event.reply("❌ <b>No thumbnail found to delete.</b>", parse_mode='html')

@bot.on(events.NewMessage(pattern='/showthumb'))
async def showthumb_handler(event):
    """Handler to display the current thumbnail"""
    user_id = event.sender_id
    
    # 🔥 FORCE JOIN CHECK 🔥
    ok, missing = await is_user_in_required_channels(user_id)
    if not ok:
        await send_force_join_message(event, missing)
        return
    
    thumb_path = os.path.join(THUMBNAIL_DIR, "{}.jpg".format(user_id))
    
    if os.path.exists(thumb_path):
        await event.reply(
            file=thumb_path,
            message="🖼️ <b>Your current thumbnail:</b>",
            parse_mode='html'
        )
    else:
        await event.reply("❌ <b>No thumbnail set.</b>\n\nUse /setthumb to set one.", parse_mode='html')

@bot.on(events.NewMessage(func=lambda e: e.photo))
async def photo_handler(event):
    """Handler for photos (thumbnails)"""
    user_id = event.sender_id
    
    # Check if user is in set_thumbnail mode
    if user_id in user_sessions and user_sessions[user_id].get('action') == 'set_thumbnail':
        # Check size
        if event.file.size > MAX_THUMB_SIZE:
            await event.reply(
                "❌ <b>Photo too large!</b>\n\n"
                "Maximum size: {}\n"
                "Your photo: {}".format(
                    human_readable_size(MAX_THUMB_SIZE),
                    human_readable_size(event.file.size)
                ),
                parse_mode='html'
            )
            del user_sessions[user_id]
            return
        
        # Save the thumbnail
        thumb_path = os.path.join(THUMBNAIL_DIR, "{}.jpg".format(user_id))
        
        try:
            # Progress message
            progress_msg = await event.reply("⏳ <b>Saving thumbnail...</b>", parse_mode='html')
            
            # Download the photo
            await event.download_media(file=thumb_path)
            
            # Confirm
            await safe_edit(progress_msg,
                "✅ <b>Thumbnail saved successfully!</b>\n\n"
                "This thumbnail will be used for all your renamed files.\n"
                "Use /delthumb to remove it.",
                parse_mode='html'
            )
            
            # Clean up the session
            del user_sessions[user_id]
            
        except Exception as e:
            await safe_edit(progress_msg,
                "❌ <b>Error saving thumbnail:</b> {}".format(str(e)),
                parse_mode='html'
            )

@bot.on(events.NewMessage(func=lambda e: e.file and not e.photo))
async def file_handler(event):
    """Stateless handler for files (not photos)"""
    user_id = event.sender_id
    
    # Force-join
    ok, missing = await is_user_in_required_channels(user_id)
    if not ok:
        await send_force_join_message(event, missing)
        return
    
    file = event.file
    file_size_bytes = int(file.size) if getattr(file, 'size', None) else 0
    
    # Size check
    if file_size_bytes and file_size_bytes > MAX_FILE_SIZE:
        await event.reply(
            "❌ <b>File too large!</b>\n\n"
            f"Maximum: {human_readable_size(MAX_FILE_SIZE)}\n"
            f"Your file: {human_readable_size(file_size_bytes)}",
            parse_mode='html'
        )
        return
    
    # Limits check
    limit_ok, limit_message = check_user_limits(user_id, file_size_bytes)
    if not limit_ok:
        await event.reply(
            f"⚠️ <b>Limit Reached!</b>\n\n{limit_message}",
            parse_mode='html'
        )
        return
    
    file_name = file.name or "unnamed_file"
    extension = os.path.splitext(file_name)[1] or ""
    mime_type = file.mime_type or "unknown"
    is_video = mime_type.startswith('video/') or extension.lower() in ['.mp4', '.mkv', '.webm']
    file_size = human_readable_size(file_size_bytes)
    
    # Thumbnail presence
    thumb_path = os.path.join(THUMBNAIL_DIR, f"{user_id}.jpg")
    has_thumbnail = os.path.exists(thumb_path)
    
    # Encode chat and message
    msg_id = event.message.id
    chat_id = event.chat_id
    # Store original message in hybrid cache for reliability
    storage_key = (chat_id, msg_id)
    ORIGINAL_MESSAGES[storage_key] = {
        'message': event.message,
        'file_name': file_name,
        'file_size': file_size_bytes,
        'is_video': is_video,
        'mime_type': mime_type,
        'timestamp': datetime.now(),
    }
    # Fire-and-forget periodic cleanup
    asyncio.create_task(cleanup_old_messages())
    buttons = []
    if has_thumbnail:
        buttons.append([Button.inline("🖼️ Add Thumbnail", f"thumb|{chat_id}|{msg_id}")])
    else:
        buttons.append([Button.inline("🖼️ Set Thumbnail First", "no_thumb")])
    buttons.append([Button.inline("✏️ Rename Only", f"ren|{chat_id}|{msg_id}")])
    buttons.append([Button.inline("❌ Cancel", f"cancel|{chat_id}|{msg_id}")])
    
    info_text = f"""📁 <b>FILE INFORMATION</b>

◆ <b>Name:</b> <code>{file_name}</code>
◆ <b>Size:</b> {file_size}
◆ <b>Type:</b> {mime_type} {"🎬" if is_video else ""}

❓ <b>What do you want to do?</b>"""
    
    await event.reply(info_text, parse_mode='html', buttons=buttons)

@bot.on(events.CallbackQuery)
async def callback_handler(event):
    """Stateless handler for inline buttons and settings"""
    data = event.data.decode('utf-8')
    user_id = event.query.user_id
    
    # Settings menu and existing settings options
    if data == "show_settings":
        await show_settings_menu(event)
        return
    elif data == "add_custom_text":
        if user_id not in sessions:
            sessions[user_id] = {}
        sessions[user_id]['awaiting_custom_text'] = True
        current_text = sessions[user_id].get('custom_text', '')
        message = "📝 <b>Add Custom Text</b>\n\n"
        if current_text:
            message += f"Current: <code>{current_text}</code>\n\n"
        message += (
            "Send me any text to be added to your filenames.\n\n"
            "Examples:\n"
            "• [MyGroup]\n"
            "• Uploaded_by_Me\n"
            "• 2025_Series\n\n"
            "Send /cancel to abort."
        )
        if isinstance(event, events.NewMessage.Event):
            await event.reply(message, parse_mode='html')
        else:
            await event.edit(message, parse_mode='html')
        return
    elif data == "change_text_position":
        if user_id not in sessions:
            sessions[user_id] = {}
        current = sessions[user_id].get('text_position', 'end')
        new_pos = 'start' if current == 'end' else 'end'
        sessions[user_id]['text_position'] = new_pos
        save_user_preferences()
        await event.answer(f"Position changed to {new_pos}.", alert=True)
        await show_settings_menu(event)
        return
    elif data == "remove_custom_text":
        if user_id not in sessions:
            sessions[user_id] = {}
        sessions[user_id]['custom_text'] = ''
        save_user_preferences()
        await event.answer("Custom text removed.", alert=True)
        await show_settings_menu(event)
        return
    elif data == "toggle_clean_tags":
        if user_id not in sessions:
            sessions[user_id] = {}
        current = sessions[user_id].get('clean_tags', True)
        sessions[user_id]['clean_tags'] = not current
        save_user_preferences()
        await event.answer(f"Clean tags: {'On' if sessions[user_id]['clean_tags'] else 'Off'}", alert=True)
        await show_settings_menu(event)
        return
    elif data == "close_settings":
        await event.delete()
        return
    
    # New stateless actions
    if data == "no_thumb":
        await event.answer("❌ Please set a thumbnail first with /setthumb", alert=True)
        return
    
    if "|" in data:
        parts = data.split("|")
        action = parts[0]
        if len(parts) < 3:
            await event.answer("❌ Invalid action", alert=True)
            return
        chat_id = int(parts[1])
        msg_id = int(parts[2])
        lock_key = (chat_id, msg_id)
        
        storage_key = (chat_id, msg_id)
        stored_data = ORIGINAL_MESSAGES.get(storage_key)
        if not stored_data:
            await event.answer("❌ Session expired. Please send the file again.", alert=True)
            return
        original_msg = stored_data.get('message')
        if not original_msg or not getattr(original_msg, 'file', None):
            await event.answer("❌ Original file not found!", alert=True)
            return
        if getattr(original_msg, 'sender_id', None) != user_id:
            await event.answer("❌ Not your file!", alert=True)
            return
        
        async with PROCESSING_LOCKS.setdefault(lock_key, asyncio.Lock()):
            if action == "cancel":
                await event.edit("❌ <b>Cancelled.</b>", parse_mode='html')
                return
            elif action in ("ren", "thumb"):
                # Build prompt message and send a NEW message with ForceReply
                if action == "thumb":
                    try:
                        file_name = stored_data.get('file_name') or getattr(original_msg.file, 'name', 'Unknown')
                        file_size_bytes = int(stored_data.get('file_size') or 0)
                        mime_type = stored_data.get('mime_type') or getattr(getattr(original_msg, 'file', None), 'mime_type', 'unknown')
                        from pathlib import Path as _P
                        ext = _P(file_name).suffix.lstrip('.').upper() if file_name else ""
                        size_str = human_readable_size(file_size_bytes)
                        # stylize B to ʙ to match the requested style
                        size_str = size_str.replace('B', 'ʙ')
                        dc_id = None
                        try:
                            dc_id = getattr(getattr(getattr(original_msg, 'media', None), 'document', None), 'dc_id', None)
                        except Exception:
                            dc_id = None
                        dc_id = dc_id if dc_id is not None else '-'

                        media_info_text = (
                            "ᴍᴇᴅɪᴀ ɪɴꜰᴏ\n\n"
                            f"◈ ꜰɪʟᴇ ɴᴀᴍᴇ: {file_name}\n\n"
                            f"◈ ᴇxᴛᴇɴꜱɪᴏɴ: {ext}\n"
                            f"◈ ꜰɪʟᴇ ꜱɪᴢᴇ: {size_str}\n"
                            f"◈ ᴍɪᴍᴇ ᴛʏᴇᴩ: {mime_type}\n"
                            f"◈ ᴅᴄ ɪᴅ: {dc_id}\n\n"
                            "ᴘʟᴇᴀsᴇ ᴇɴᴛᴇʀ ᴛʜᴇ ɴᴇᴡ ғɪʟᴇɴᴀᴍᴇ ᴡɪᴛʜ ᴇxᴛᴇɴsɪᴏɴ ᴀɴᴅ ʀᴇᴘʟʏ ᴛʜɪs ᴍᴇssᴀɢᴇ.."
                        )
                    except Exception:
                        media_info_text = "📝 <b>Reply to this message with the new filename</b>"
                    prompt = await bot.send_message(
                        event.chat_id,
                        media_info_text,
                        parse_mode='html',
                        reply_to=original_msg.id,
                        buttons=Button.force_reply(selective=True)
                    )
                else:
                    basic_prompt = "📝 <b>Reply to this message with the new filename</b>"
                    prompt = await bot.send_message(
                        event.chat_id,
                        basic_prompt,
                        parse_mode='html',
                        reply_to=original_msg.id,
                        buttons=Button.force_reply(selective=True)
                    )

                user_sessions[user_id] = {
                    'action': 'thumb_stateless' if action == 'thumb' else 'rename_stateless',
                    'original_msg': original_msg,
                    'stored_data': stored_data,
                    'storage_key': storage_key,
                    'prompt_msg': prompt,
                    'timestamp': datetime.now()
                }
                return

@bot.on(events.NewMessage(func=lambda e: e.is_reply and e.text))
async def rename_reply_handler(event):
    """Handle replies for stateless rename flows"""
    user_id = event.sender_id
    
    if user_id not in user_sessions:
        return
    sess = user_sessions[user_id]
    action = sess.get('action')
    if action not in ['rename_stateless', 'thumb_stateless']:
        return
    
    # Ensure reply corresponds to prompt
    if event.reply_to_msg_id != getattr(sess.get('prompt_msg'), 'id', None):
        return
    
    new_name = (event.raw_text or event.text or "").strip()
    if not new_name:
        await event.reply("❌ Please provide a valid filename.")
        return
    
    original_msg = sess.get('original_msg')
    if not original_msg:
        del user_sessions[user_id]
        return
    
    # Add extension if missing
    if "." not in new_name:
        original_name = original_msg.file.name or ""
        ext = os.path.splitext(original_name)[1]
        if ext:
            new_name += ext
            await event.reply(f"ℹ️ Extension added: <code>{new_name}</code>", parse_mode='html')
    
    # Build final name
    sanitized_name = sanitize_filename(new_name)
    if sessions.get(user_id, {}).get('clean_tags', True):
        sanitized_name = clean_filename_text(sanitized_name)
    custom_text = sessions.get(user_id, {}).get('custom_text', '')
    text_position = sessions.get(user_id, {}).get('text_position', 'end')
    if custom_text:
        sanitized_name = add_custom_text_to_filename(sanitized_name, custom_text, text_position)
    
    try:
        if action == 'rename_stateless':
            await bot.send_file(
                event.chat_id,
                original_msg.media,
                caption=f"<code>{sanitized_name}</code>",
                parse_mode='html',
                file_name=sanitized_name,
                supports_streaming=True,
                force_document=not getattr(original_msg, 'video', False)
            )
            await event.reply("✅ File renamed successfully!")
            # Update rename stats (best-effort)
            try:
                await add_rename_stat(getattr(getattr(original_msg, 'file', None), 'size', 0) or 0)
            except Exception:
                pass
            
        elif action == 'thumb_stateless':
            # Build a minimal, self-contained session snapshot for queued processing
            sess_copy = {
                'action': 'thumb_stateless',
                'original_msg': sess.get('original_msg'),
                'stored_data': sess.get('stored_data'),
                'storage_key': sess.get('storage_key'),
                'timestamp': datetime.now(),
            }
            # Always enqueue; the worker will process immediately if this is the only job
            q = THUMB_QUEUES.setdefault(user_id, asyncio.Queue())
            worker_active = user_id in THUMB_WORKERS and THUMB_WORKERS[user_id] and not THUMB_WORKERS[user_id].done()
            size_before = q.qsize()
            await q.put({
                'chat_id': event.chat_id,
                'new_name': sanitized_name,
                'sess': sess_copy,
            })
            logging.info(f"[THUMB] Enqueued for user {user_id}; size_before={size_before} now={q.qsize()} name={sanitized_name}")
            ensure_thumb_worker(user_id)
            # Inform waiting only if there was already a job or a worker running
            if worker_active or size_before > 0:
                await event.reply("🕒 File queued… I will process it after the current file.")
            # Delete prompt now; worker will cleanup the cache after processing
            try:
                pm = sess.get('prompt_msg')
                if pm:
                    await pm.delete()
            except Exception:
                pass
            # End early; do not fall through to cleanup that removes cache
            if user_id in user_sessions:
                del user_sessions[user_id]
            return
    except Exception as e:
        await event.reply(f"❌ Error: {str(e)}")
    finally:
        # Clean up prompt message, cache entry, and clear short-lived session
        try:
            pm = sess.get('prompt_msg')
            if pm:
                await pm.delete()
        except Exception:
            pass
        # Note: cache cleanup for thumbnail path is handled in worker or after immediate processing above
        try:
            if action == 'rename_stateless':
                storage_key = sess.get('storage_key')
                if storage_key:
                    ORIGINAL_MESSAGES.pop(storage_key, None)
        except Exception:
            pass
        if user_id in user_sessions:
            del user_sessions[user_id]

async def process_file(event, user_id, new_name=None, use_thumb=False, sess=None):
    """Generic function to process (download and upload) a file."""
    
    # Prefer per-message session if provided
    if sess is None and user_id not in user_sessions:
        return

    progress_msg = None
    reencoded_path = None
    temp_path = None

    try:
        if new_name is None:
            base_info = sess if sess is not None else user_sessions[user_id]
            new_name = base_info['file_name']
        
        sanitized_name = sanitize_filename(new_name)
        # Add custom text if present
        custom_text = sessions.get(user_id, {}).get('custom_text', '')
        text_position = sessions.get(user_id, {}).get('text_position', 'end')
        if custom_text:
            sanitized_name = add_custom_text_to_filename(sanitized_name, custom_text, text_position)
        
        # Progress message
        if isinstance(event, events.CallbackQuery.Event):
             progress_msg = await event.edit("⏳ <b>Processing...</b>", parse_mode='html')
        else:
             progress_msg = await event.reply("⏳ <b>Processing...</b>", parse_mode='html')

        await bot(SetTypingRequest(
            event.chat_id, 
            SendMessageUploadDocumentAction(progress=0)
        ))
        
        base_info = sess if sess is not None else user_sessions[user_id]
        original_msg = base_info.get('original_msg') or base_info.get('message')
        if not original_msg:
            raise Exception("Missing original message in session")
        is_video = base_info.get('is_video', False)
        
        temp_filename = "{}_{}_{}".format(user_id, int(time.time()), uuid.uuid4().hex[:8])
        temp_path = os.path.join(TEMP_DIR, temp_filename)
        if sess is not None:
            sess['temp_path'] = temp_path
        else:
            user_sessions[user_id]['temp_path'] = temp_path
        
        start_time = time.time()
        last_update_time = [start_time]
        
        async def download_progress(current, total):
            await progress_callback(current, total, event, start_time, progress_msg, "Downloading", last_update_time)
        
        path = await original_msg.download_media(
            file=temp_path,
            progress_callback=download_progress
        )
        
        if not path or not os.path.exists(path):
            raise Exception("Failed to download file")
        
        if path != temp_path:
            shutil.move(path, temp_path)
        
        upload_path = temp_path
        
        # Check/convert for compatibility if it's a video
        if is_video:
            temp_path = await ensure_video_compatibility(temp_path, progress_msg)
            # Create optimized attributes
            video_attributes = get_video_attributes(temp_path, sanitized_name)
        else:
            video_attributes = []
        
        # SKIP FFmpeg - not necessary for simple renaming
        # Optimization disabled to improve performance
        
        await safe_edit(progress_msg, "📤 <b>Uploading file...</b>", parse_mode='html')
        
        start_time = time.time()
        last_update_time_upload = [start_time]
        
        async def upload_progress(current, total):
            await progress_callback(current, total, event, start_time, progress_msg, "Uploading", last_update_time_upload)
        
        thumb_to_use = None
        if use_thumb:
            thumb_path = os.path.join(THUMBNAIL_DIR, "{}.jpg".format(user_id))
            if os.path.exists(thumb_path):
                thumb_to_use = thumb_path
        
        # Add filename attribute
        file_attributes = [DocumentAttributeFilename(sanitized_name)]
        
        # Add video attributes if available
        if video_attributes:
            file_attributes.extend(video_attributes)
        
        # Create caption with filename
        caption = f"<code>{sanitized_name}</code>"
        
        # Send file with all necessary attributes
        await event.client.send_file(
            event.chat_id,
            upload_path,
            caption=caption,  # Caption with filename
            parse_mode='html',
            file_name=sanitized_name,
            thumb=thumb_to_use,
            supports_streaming=True,  # ✅ Always True for videos
            force_document=True,      # ✅ Always True to force document mode
            attributes=file_attributes,
            progress_callback=upload_progress,
            part_size_kb=512,  # Optimized chunks for better performance
            allow_cache=False  # ✅ Force Telegram to regenerate previews
        )
        
        await progress_msg.delete()
        
        # Update user usage after successful processing
        size_val = (sess or {}).get('file_size') if sess is not None else user_sessions.get(user_id, {}).get('file_size')
        if size_val is not None:
            update_user_usage(user_id, size_val)
            logging.info(f"Usage updated for user {user_id}: +{human_readable_size(size_val)}")
            try:
                await add_rename_stat(int(user_sessions[user_id]['file_size'] or 0))
            except Exception:
                pass
        
    except FloodWaitError as e:
        if progress_msg:
             await safe_edit(progress_msg, "⏳ Rate limit hit. Please wait {} seconds.".format(e.seconds))
        else:
            await event.reply("⏳ Rate limit hit. Please wait {} seconds.".format(e.seconds))
    except Exception as e:
        error_msg = "❌ <b>Error:</b> {}\n\nPlease try again.".format(str(e))
        if progress_msg:
            await safe_edit(progress_msg, error_msg, parse_mode='html')
        else:
            await event.reply(error_msg, parse_mode='html')
        
    finally:
        # Improved cleanup
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError as e:
                logging.error(f"Error deleting temp_path {temp_path}: {e}")
        
        if reencoded_path and os.path.exists(reencoded_path):
            try:
                os.remove(reencoded_path)
            except OSError as e:
                logging.error(f"Error deleting reencoded_path {reencoded_path}: {e}")

        # Only delete legacy session if we were operating on it
        if sess is None and user_id in user_sessions:
            del user_sessions[user_id]





async def process_with_thumbnail(event, user_id, new_name, sess=None):
    """Processes the file with thumbnail and new name"""
    
    if sess is None and user_id not in user_sessions:
        return
    
    progress_msg = None
    temp_path = None
    
    try:
        # Prepare name
        sanitized_name = sanitize_filename(new_name)
        
        # Apply configured modifications
        clean_tags = sessions.get(user_id, {}).get('clean_tags', True)
        if clean_tags:
            sanitized_name = clean_filename_text(sanitized_name)
        
        custom_text = sessions.get(user_id, {}).get('custom_text', '')
        text_position = sessions.get(user_id, {}).get('text_position', 'end')
        if custom_text:
            sanitized_name = add_custom_text_to_filename(sanitized_name, custom_text, text_position)
        

        # Ensure correct extension is kept/added (crucial for inline playback)
        try:
            if sess is not None:
                original_name = (sess.get('stored_data') or {}).get('file_name') or ''
                is_video_src = (sess.get('stored_data') or {}).get('is_video', False)
            else:
                original_name = user_sessions[user_id].get('file_name') or ''
                is_video_src = user_sessions[user_id].get('is_video', False)
            original_ext = os.path.splitext(original_name)[1]
            # Default to .mp4 for videos if extension is missing
            if not original_ext and is_video_src:
                original_ext = '.mp4'
            if original_ext and not sanitized_name.lower().endswith(original_ext.lower()):
                sanitized_name += original_ext
        except Exception:
            pass
        
        progress_msg = await event.reply("🖼️ <b>Processing with thumbnail...</b>", parse_mode='html')
        
        if sess is not None:
            original_msg = sess.get('original_msg')
            is_video = (sess.get('stored_data') or {}).get('is_video', False)
            file_size = (sess.get('stored_data') or {}).get('file_size', 0)
        else:
            original_msg = user_sessions[user_id]['message']
            is_video = user_sessions[user_id].get('is_video', False)
            file_size = user_sessions[user_id]['file_size']
        
        # Download the file
        temp_filename = f"{user_id}_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        temp_path = os.path.join(TEMP_DIR, temp_filename)
        
        await safe_edit(progress_msg, "📥 <b>Downloading file...</b>", parse_mode='html')
        
        start_time = time.time()
        async def download_progress(current, total):
            if time.time() - start_time > 2:
                percentage = current * 100 / total
                text = f"📥 <b>Downloading...</b> {percentage:.1f}%"
                
                # Avoid redundant edits
                if hasattr(progress_msg, '_last_progress_text') and progress_msg._last_progress_text == text:
                    return
                
                await safe_edit(progress_msg, text, parse_mode='html')
                progress_msg._last_progress_text = text
        
        path = await original_msg.download_media(
            file=temp_path,
            progress_callback=download_progress
        )
        
        if not path or not os.path.exists(path):
            raise Exception("Failed to download file")
        
        if path != temp_path:
            shutil.move(path, temp_path)
        
        # Get the thumbnail
        thumb_path = os.path.join(THUMBNAIL_DIR, f"{user_id}.jpg")
        
        # Check/convert for compatibility if it's a video
        if is_video:
            temp_path = await ensure_video_compatibility(temp_path, progress_msg)
            # Create optimized attributes
            file_attributes = get_video_attributes(temp_path, sanitized_name)
        else:
            file_attributes = [DocumentAttributeFilename(sanitized_name)]
        
        # Minimal caption (just the name like rename_only)
        caption = f"<code>{sanitized_name}</code>"
        
        await safe_edit(progress_msg, "📤 <b>Uploading with thumbnail...</b>", parse_mode='html')
        
        # Send with thumbnail
        await event.client.send_file(
            event.chat_id,
            temp_path,
            caption=caption,
            parse_mode='html',
            file_name=sanitized_name,
            thumb=thumb_path,
            supports_streaming=True,
            # IMPORTANT: send as video (not document) to keep inline player
            force_document=not is_video,
            attributes=file_attributes,
            allow_cache=False
        )
        
        await progress_msg.delete()
        
        # Update usage
        update_user_usage(user_id, file_size)
        try:
            await add_rename_stat(int(file_size or 0))
        except Exception:
            pass
        
        # Clean up
        try:
            os.remove(temp_path)
        except:
            pass
        
        # Delete prompt messages before cleaning up the session
        if sess is not None and 'media_info_msg' in sess:
            try:
                await sess['media_info_msg'].delete()
            except:
                pass
        if sess is not None and 'rename_prompt_msg' in sess:
            try:
                await sess['rename_prompt_msg'].delete()
            except:
                pass
        
        # Only delete legacy session if no per-message session was used
        if sess is None and user_id in user_sessions:
            del user_sessions[user_id]
        
    except Exception as e:
        error_msg = f"❌ <b>Error:</b> {str(e)}"
        if progress_msg:
            await safe_edit(progress_msg, error_msg, parse_mode='html')
        else:
            await event.reply(error_msg, parse_mode='html')
        
        # Clean up on error
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass

        # Delete prompt messages even on error
        if user_id in user_sessions:
            if 'media_info_msg' in user_sessions[user_id]:
                try:
                    await user_sessions[user_id]['media_info_msg'].delete()
                except:
                    pass
            if 'rename_prompt_msg' in user_sessions[user_id]:
                try:
                    await user_sessions[user_id]['rename_prompt_msg'].delete()
                except:
                    pass
            del user_sessions[user_id]

def main():
    """Main function modified"""
    print("🤖 Bot started successfully!")
    print("📁 Temp directory: {}".format(TEMP_DIR))
    print("📊 Max file size: {}".format(human_readable_size(MAX_FILE_SIZE)))
    print("🎬 FFmpeg: {}".format("Available" if shutil.which("ffmpeg") else "Not available"))
    print("📈 Daily limit: {} per user".format(human_readable_size(DAILY_LIMIT_BYTES)))
    print("⏱ Cooldown: {} seconds between files".format(COOLDOWN_SECONDS))
    print("⚡ Fast thumbnail mode: ENABLED")
    print(f"📢 Force Join Channel: @{FORCE_JOIN_CHANNEL}")
    
    # Load data
    load_user_usage()
    load_user_preferences()
    print("📊 User data loaded")
    
    # Send a message to all users who have interacted with the bot
    async def notify_all_users():
        # Get all user IDs from usage data
        all_users = list(user_usage.keys())
        
        # Add admin IDs if configured
        if ADMIN_IDS:
            admin_list = [int(x) for x in str(ADMIN_IDS).split(',') if x.strip()]
            for admin_id in admin_list:
                if admin_id not in all_users:
                    all_users.append(admin_id)
        
        # Remove duplicates
        all_users = list(set(all_users))
        
        # Send startup message to all users
        startup_message = (
            f"🟢 <b>Bot started!</b>\n\n"
            f"Rename bot is now online and ready.\n\n"
            f"📈 Daily limit: {human_readable_size(DAILY_LIMIT_BYTES)}\n"
            f"⏱ Cooldown: {COOLDOWN_SECONDS}s\n"
            f"⚡ Fast mode: ENABLED\n"
            f"📢 Force Join: @{FORCE_JOIN_CHANNEL}"
        )
        
        success_count = 0
        for user_id in all_users:
            try:
                await bot.send_message(
                    user_id, 
                    startup_message,
                    parse_mode='html'
                )
                success_count += 1
                # Small delay to avoid flood
                await asyncio.sleep(0.1)
            except Exception as e:
                logging.error(f"Failed to send startup message to user {user_id}: {e}")
                continue
        
        print(f"📢 Startup message sent to {success_count}/{len(all_users)} users")
    
    # Start automatic cleanup task
    async def start_cleanup():
        await auto_cleanup_task()
    
    # Notify all users and start cleanup
    bot.loop.run_until_complete(notify_all_users())
    bot.loop.create_task(start_cleanup())
    
    # Start the bot
    print("\n✅ Bot is running! Press Ctrl+C to stop.\n")
    bot.run_until_disconnected()

if __name__ == '__main__':
    main()