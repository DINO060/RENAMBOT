#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import os
import time
import math
import re
import uuid
import shutil
import json
from datetime import datetime, timedelta
from collections import defaultdict
from telethon import TelegramClient, events, Button
from telethon.tl.types import DocumentAttributeFilename, DocumentAttributeVideo
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
        from config import API_ID, API_HASH, BOT_TOKEN, ADMIN_IDS
        return locals()[attr]
    except Exception:
        return default

API_ID = get_env_or_config("API_ID")
API_HASH = get_env_or_config("API_HASH")
BOT_TOKEN = get_env_or_config("BOT_TOKEN")
ADMIN_IDS = get_env_or_config("ADMIN_IDS", "")


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

# Import configuration
#bAPI_ID = int(os.getenv("API_ID"))
#API_HASH = os.getenv("API_HASH")
#TOKEN = os.getenv("TOKEN")
#ADMIN_IDS = os.getenv("ADMIN_IDS")

# 🔥 FORCE JOIN CHANNEL CONFIGURATION 🔥
FORCE_JOIN_CHANNEL = "djd208"  # ⚠️ REPLACE WITH YOUR CHANNEL (without @)

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

# Dictionary to store user sessions
user_sessions = {}

# Usage limits system
user_usage = defaultdict(lambda: {'daily_bytes': 0, 'last_reset': None, 'last_file_time': None})
usage_file = "user_usage.json"

# User preferences system
sessions = {}  # To store user preferences

DEFAULT_USERNAME = "@dino_renamebot"  # Put your real username here

# HELPER FUNCTION TO GET LOCAL FILE PATH
def get_local_file_path(user_id, file_id, extension):
    """Returns the local path of a file"""
    user_dir = os.path.join(DOWNLOAD_DIR, str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    return os.path.join(user_dir, f"{file_id}{extension}")

# 🔥 FORCE JOIN CHANNEL FUNCTIONS 🔥
async def is_user_in_channel(user_id):
    """Checks if the user is a member of the channel"""
    # Admin exemption
    admin_list = [int(x) for x in str(ADMIN_IDS).split(',') if x.strip()] if ADMIN_IDS else []
    if user_id in admin_list:
        return True
    
    try:
        await bot(GetParticipantRequest(
            channel=FORCE_JOIN_CHANNEL,
            participant=user_id
        ))
        return True
    except UserNotParticipantError:
        return False
    except ChannelPrivateError:
        logging.error(f"Bot doesn't have access to channel {FORCE_JOIN_CHANNEL}")
        return True  # Let it pass to avoid blocking
    except Exception as e:
        logging.error(f"Channel verification error: {e}")
        return True  # In case of error, let it pass

async def send_force_join_message(event):
    """Sends the message asking the user to join the channel"""
    buttons = [
        [Button.url(f"📢 Join @{FORCE_JOIN_CHANNEL}", f"https://t.me/{FORCE_JOIN_CHANNEL}")],
        [Button.inline("✅ I have joined", "check_joined")]
    ]
    
    message = f"""🚫 <b>Access Denied!</b>

To use this bot, you must first join our official channel:
👉 @{FORCE_JOIN_CHANNEL}

✅ Click the button below to join.
Once done, click "I have joined" to continue.

<i>Thank you for your support! 💙</i>"""
    
    await event.reply(message, parse_mode='html', buttons=buttons)

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

def add_default_username_to_filename(filename, username, position='end'):
    name, ext = os.path.splitext(filename)
    # Avoid adding it multiple times
    if username.lower() in name.lower():
        return filename
    if position == 'end':
        name = f"{name} {username}"
    else:
        name = f"{username} {name}"
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

# Initialize the Telethon client
bot = TelegramClient('rename_bot', API_ID, API_HASH).start(bot_token=TOKEN)

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

# 🔥 HANDLER FOR THE "I HAVE JOINED" BUTTON 🔥
@bot.on(events.CallbackQuery(data="check_joined"))
async def check_joined_handler(event):
    user_id = event.query.user_id
    
    if await is_user_in_channel(user_id):
        await event.answer("✅ Thank you! You can now use the bot.", alert=True)
        await event.delete()
        # Show welcome message
        await bot.send_message(user_id, "/start")
    else:
        await event.answer("❌ You haven't joined the channel yet!", alert=True)

@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    """Improved handler for the /start command"""
    user_id = event.sender_id
    
    # 🔥 FORCE JOIN CHECK 🔥
    if not await is_user_in_channel(user_id):
        await send_force_join_message(event)
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
/setthumb - Set custom thumbnail
/delthumb - Delete custom thumbnail
/cancel - Cancel current operation

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
    """Handler to check bot status"""
    active_sessions = len(user_sessions)
    
    # Check disk space (Windows compatible)
    if os.name == 'nt':  # Windows
        import shutil
        total, used, free = shutil.disk_usage(TEMP_DIR)
        free_space = free
    else:  # Linux/Mac
        stat = os.statvfs(TEMP_DIR)
        free_space = stat.f_bavail * stat.f_frsize
    
    # Check ffmpeg
    ffmpeg_status = "✅ Available" if shutil.which("ffmpeg") else "❌ Not available"
    
    status_text = """🤖 <b>Bot Status</b>

✅ <b>Status:</b> Online
👥 <b>Active Sessions:</b> {}
💾 <b>Free Space:</b> {}
📊 <b>Max File Size:</b> {}
🎬 <b>FFmpeg:</b> {}
📈 <b>Daily Limit:</b> {} per user
⏱ <b>Cooldown:</b> {} seconds

<i>Bot is running smoothly!</i>""".format(
        active_sessions,
        human_readable_size(free_space),
        human_readable_size(MAX_FILE_SIZE),
        ffmpeg_status,
        human_readable_size(DAILY_LIMIT_BYTES),
        COOLDOWN_SECONDS
    )
    
    await event.reply(status_text, parse_mode='html')

@bot.on(events.NewMessage(pattern='/usage'))
async def usage_handler(event):
    """Handler to check user usage"""
    user_id = event.sender_id
    
    # 🔥 FORCE JOIN CHECK 🔥
    if not await is_user_in_channel(user_id):
        await send_force_join_message(event)
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
    if not await is_user_in_channel(user_id):
        await send_force_join_message(event)
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
    custom_username = sessions.get(user_id, {}).get('custom_username', '')
    
    text = "⚙️ <b>Bot Settings</b>\n\n"
    
    if custom_text:
        text += f"📝 Custom text: <code>{custom_text}</code>\n"
        text += f"📍 Position: {text_position}\n"
    else:
        text += "📝 No custom text set\n"
    if custom_username:
        text += f"👤 Username: <code>{custom_username}</code>\n"
    
    text += f"🧹 Auto-clean tags: {'Yes' if clean_tags else 'No'}\n\n"
    text += "Choose an option:"
    
    keyboard = [
        [Button.inline("➕ Add/Edit Custom Text", "add_custom_text")],
        [Button.inline("👤 Add/Edit Username", "add_custom_username")],
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
    if not await is_user_in_channel(user_id):
        await send_force_join_message(event)
        return
    
    # Store that the user wants to set a thumbnail
    user_sessions[user_id] = {
        'action': 'set_thumbnail',
        'timestamp': datetime.now()
    }
    
    await event.reply(
        "🖼️ <b>Send me a photo to set as thumbnail</b>\n\n"
        "Requirements:\n"
        "• Must be a photo (not document)\n"
        "• Size limit: 200 KB\n"
        "• Format: JPEG/PNG\n\n"
        "Send /cancel to abort.",
        parse_mode='html'
    )

@bot.on(events.NewMessage(pattern='/delthumb'))
async def delthumb_handler(event):
    """Handler to delete the thumbnail"""
    user_id = event.sender_id
    
    # 🔥 FORCE JOIN CHECK 🔥
    if not await is_user_in_channel(user_id):
        await send_force_join_message(event)
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
    if not await is_user_in_channel(user_id):
        await send_force_join_message(event)
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
            if user_id in user_sessions:
                del user_sessions[user_id]

@bot.on(events.NewMessage(func=lambda e: e.file and not e.photo))
async def file_handler(event):
    """Main handler for files (not photos)"""
    user_id = event.sender_id
    
    # 🔥 FORCE JOIN CHECK 🔥
    if not await is_user_in_channel(user_id):
        await send_force_join_message(event)
        return
    
    # Clean up old sessions
    await clean_old_sessions()
    
    file = event.file
    
    # Check file size
    if file.size > MAX_FILE_SIZE:
        await event.reply(
            "❌ <b>File too large!</b>\n\n"
            "Maximum size: {}\n"
            "Your file: {}".format(
                human_readable_size(MAX_FILE_SIZE),
                human_readable_size(file.size)
            ),
            parse_mode='html'
        )
        return
    
    # Check user limits
    limit_ok, limit_message = check_user_limits(user_id, file.size)
    if not limit_ok:
        await event.reply(
            "⚠️ <b>Usage Limit Reached!</b>\n\n{}\n\nUse /usage to check your limits.".format(limit_message),
            parse_mode='html'
        )
        return
    
    # Get file information
    file_name = file.name or "unnamed_file"
    file_size = human_readable_size(file.size)
    extension = os.path.splitext(file_name)[1] or ""
    mime_type = file.mime_type or "unknown"
    
    # Check if it's a video
    is_video = mime_type.startswith('video/') or extension.lower() in ['.mp4', '.mkv', '.webm', '.avi', '.mov', '.flv']
    
    # Store session information
    user_sessions[user_id] = {
        'message': event.message,
        'file_name': file_name,
        'timestamp': datetime.now(),
        'action': None,
        'is_video': is_video,
        'file_size': file.size  # Store size for usage update
    }
    
    # Create buttons
    buttons = [
        [Button.inline("🖼️ Add Thumbnail", f"add_thumb_{user_id}")],
        [Button.inline("✏️ Rename Only", f"rename_only_{user_id}")],
        [Button.inline("❌ Cancel", f"cancel_{user_id}")]
    ]
    
    # Get usage information for display
    usage_info = get_user_usage_info(user_id)
    
    info_text = """📁 <b>FILE INFORMATION</b>

◆ <b>Name:</b> <code>{}</code>
◆ <b>Size:</b> {}
◆ <b>Type:</b> {} {}
◆ <b>Extension:</b> {}

📊 <b>Your Usage:</b> {} / {} ({:.1f}%)

❓ <b>What do you want to do?</b>""".format(
        file_name,
        file_size,
        mime_type,
        "🎬 (Video)" if is_video else "",
        extension,
        human_readable_size(usage_info['daily_used']),
        human_readable_size(usage_info['daily_limit']),
        usage_info['percentage']
    )
    
    await event.reply(
        info_text, 
        parse_mode='html',
        buttons=buttons
    )

@bot.on(events.CallbackQuery)
async def callback_handler(event):
    """Optimized handler for inline buttons"""
    data = event.data.decode('utf-8')
    user_id = event.query.user_id
    
    # Settings menu
    if data == "show_settings":
        await show_settings_menu(event)
        return
    
    # Add custom text
    elif data == "add_custom_text":
        if user_id not in sessions:
            sessions[user_id] = {}
        sessions[user_id]['awaiting_custom_text'] = True
        
        current_text = sessions[user_id].get('custom_text', '')
        
        message = "📝 <b>Add Custom Text</b>\n\n"
        if current_text:
            message += f"Current: <code>{current_text}</code>\n\n"
        
        message += """Send me the text to add to all filenames.

Examples:
• <code>@mychannel</code>
• <code>2024</code>
• <code>[Premium]</code>
• <code>MyCollection</code>

Send /cancel to abort."""
        
        await event.edit(message, parse_mode='html')
        return
    
    # Change text position
    elif data == "change_text_position":
        current_pos = sessions.get(user_id, {}).get('text_position', 'end')
        
        keyboard = [
            [Button.inline("📍 At Start" + (" ✓" if current_pos == 'start' else ""), "set_position_start")],
            [Button.inline("📍 At End" + (" ✓" if current_pos == 'end' else ""), "set_position_end")],
            [Button.inline("🔙 Back", "show_settings")]
        ]
        
        await event.edit(
            "📍 <b>Text Position</b>\n\n"
            f"Current: <b>{current_pos.capitalize()}</b>\n\n"
            "Examples:\n"
            "• Start: <code>@channel Document.pdf</code>\n"
            "• End: <code>Document @channel.pdf</code>",
            parse_mode='html',
            buttons=keyboard
        )
        return
    
    # Set position
    elif data.startswith("set_position_"):
        position = data.replace("set_position_", "")
        if user_id not in sessions:
            sessions[user_id] = {}
        sessions[user_id]['text_position'] = position
        save_user_preferences()
        
        await event.answer(f"✅ Position set to {position}")
        await show_settings_menu(event)
        return
    
    # Remove custom text
    elif data == "remove_custom_text":
        if user_id in sessions and 'custom_text' in sessions[user_id]:
            old_text = sessions[user_id]['custom_text']
            del sessions[user_id]['custom_text']
            save_user_preferences()
            
            await event.edit(
                f"✅ <b>Custom text removed!</b>\n\n"
                f"Deleted: <code>{old_text}</code>",
                parse_mode='html'
            )
            await asyncio.sleep(2)
            await show_settings_menu(event)
        else:
            await event.answer("❌ No custom text to remove", alert=True)
        return
    
    # Toggle clean tags
    elif data == "toggle_clean_tags":
        if user_id not in sessions:
            sessions[user_id] = {}
        current = sessions[user_id].get('clean_tags', True)
        sessions[user_id]['clean_tags'] = not current
        save_user_preferences()
        
        status = "enabled" if not current else "disabled"
        await event.answer(f"✅ Auto-clean {status}")
        await show_settings_menu(event)
        return
    
    # Close settings
    elif data == "close_settings":
        await event.delete()
        return
    
    # Add/Edit Username
    elif data == "add_custom_username":
        if user_id not in sessions:
            sessions[user_id] = {}
        sessions[user_id]['awaiting_custom_username'] = True
        current_username = sessions[user_id].get('custom_username', '')
        message = "👤 <b>Add/Edit Username</b>\n\n"
        if current_username:
            message += f"Current: <code>{current_username}</code>\n\n"
        message += "Send me the username to add to all filenames (e.g. <code>@mychannel</code>).\n\nSend /cancel to abort."
        await event.edit(message, parse_mode='html')
        return
    
    if data.startswith('cancel_'):
        clicked_user_id = int(data.split('_')[1])
        if clicked_user_id == user_id and user_id in user_sessions:
            if 'temp_path' in user_sessions[user_id]:
                try:
                    os.remove(user_sessions[user_id]['temp_path'])
                except:
                    pass
            del user_sessions[user_id]
            await event.edit("❌ <b>Operation cancelled.</b>", parse_mode='html')
        else:
            await event.answer("❌ You can't cancel this operation.", alert=True)

    elif data.startswith('add_thumb_'):
        clicked_user_id = int(data.split('_')[2])
        if clicked_user_id == user_id and user_id in user_sessions:
            thumb_path = os.path.join(THUMBNAIL_DIR, f"{user_id}.jpg")
            if not os.path.exists(thumb_path):
                await event.answer("❌ No thumbnail set! Use /setthumb first.", alert=True)
                return
            
            # Get file info
            file_info = user_sessions[user_id]
            file_name = file_info['file_name']
            file_size = human_readable_size(file_info['file_size'])
            extension = os.path.splitext(file_name)[1] or "Unknown"
            original_msg = file_info['message']
            mime_type = original_msg.file.mime_type or "Unknown"
            dc_id = original_msg.file.dc_id if hasattr(original_msg.file, 'dc_id') else "N/A"
            
            # Display MEDIA INFO card
            info_card = f"""📁 <b>MEDIA INFO</b>

📁 <b>FILE NAME:</b> <code>{file_name}</code>
🧩 <b>EXTENSION:</b> <code>{extension}</code>
📦 <b>FILE SIZE:</b> {file_size}
🪄 <b>MIME TYPE:</b> {mime_type}
🧭 <b>DC ID:</b> {dc_id}

<b>PLEASE ENTER THE NEW FILENAME WITH EXTENSION AND REPLY THIS MESSAGE.</b>"""
            
            # Store action
            user_sessions[user_id]['action'] = 'add_thumbnail_rename'
            
            # Send message and store ID AND message object
            ask_msg = await event.edit(info_card, parse_mode='html')
            user_sessions[user_id]['reply_id'] = ask_msg.id
            user_sessions[user_id]['media_info_msg'] = ask_msg  # NEW: store message object
        else:
            await event.answer("❌ This is not for you or session expired.", alert=True)
            
    elif data.startswith('rename_only_'):
        clicked_user_id = int(data.split('_')[2])
        if clicked_user_id == user_id and user_id in user_sessions:
            user_sessions[user_id]['action'] = 'rename_only'
            ask_msg = await event.edit(
                "✏️ **Please send me the new filename** (including extension).",
                buttons=Button.inline("❌ Cancel", f"cancel_{user_id}")
            )
            # Store message ID AND message object
            user_sessions[user_id]['reply_id'] = ask_msg.id
            user_sessions[user_id]['rename_prompt_msg'] = ask_msg  # NEW
        else:
            await event.answer("❌ This is not for you or the session has expired.", alert=True)

    elif data == 'help':
        # Detailed help message
        help_text = """📚 <b>How to use this bot:</b>

1️⃣ Send me any file (document, video, audio)
2️⃣ Choose an action: 'Add Thumbnail' or 'Rename Only'.
3️⃣ **For Renaming:** Reply with the new filename (including extension).
4️⃣ **For Thumbnail:** Make sure you have set a thumbnail with /setthumb.

<b>💡 Tips:</b>
• Use descriptive filenames
• Keep the correct extension
• Avoid special characters like / \\ : * ? " < > |
• Maximum file size: 2 GB

<b>⚡ Commands:</b>
/start - Show welcome message
/cancel - Cancel current operation
/status - Check bot status"""
        
        await event.respond(help_text, parse_mode='html')
        await event.answer("ℹ️ Help sent!")  # Small notification

@bot.on(events.NewMessage(func=lambda e: e.text and e.is_private and not e.text.startswith('/')))
async def text_handler(event):
    """Handler for text messages"""
    user_id = event.sender_id
    
    if user_id not in sessions:
        return
    
    # If waiting for custom text
    if sessions[user_id].get('awaiting_custom_text'):
        custom_text = event.text.strip()
        
        if len(custom_text) > 50:
            await event.reply("❌ Text too long! Maximum 50 characters.")
            return
        
        # Save the text
        sessions[user_id]['custom_text'] = custom_text
        sessions[user_id]['awaiting_custom_text'] = False
        
        # Default position
        if 'text_position' not in sessions[user_id]:
            sessions[user_id]['text_position'] = 'end'
        
        save_user_preferences()
        
        await event.reply(
            f"✅ <b>Custom text saved!</b>\n\n"
            f"Text: <code>{custom_text}</code>\n"
            f"Position: {sessions[user_id]['text_position']}\n\n"
            f"This will be added to all renamed files.",
            parse_mode='html'
        )
        return
    # If waiting for custom username
    if sessions[user_id].get('awaiting_custom_username'):
        username = event.text.strip()
        if not username.startswith('@') or len(username) > 64:
            await event.reply("❌ Username must start with @ and be shorter than 64 characters.")
            return
        sessions[user_id]['custom_username'] = username
        sessions[user_id]['awaiting_custom_username'] = False
        save_user_preferences()
        await event.reply(
            f"✅ <b>Username saved!</b>\n\n"
            f"Username: <code>{username}</code>\n"
            f"This will be added to all renamed files.",
            parse_mode='html'
        )
        return

@bot.on(events.NewMessage(func=lambda e: e.is_reply))
async def rename_handler(event):
    """Improved handler for renaming files"""
    user_id = event.sender_id
    
    # Check if user has an active session
    if user_id not in user_sessions:
        return
    
    action = user_sessions[user_id].get('action')
    if action not in ['rename_only', 'add_thumbnail_rename']:
        return
    
    # Clean up old sessions
    await clean_old_sessions()
    
    # Check if session has expired
    if user_id not in user_sessions:
        await event.reply("⏱ Session expired. Please send the file again.")
        return
    
    reply_to = await event.get_reply_message()
    # Ensure user replies to the correct message
    if reply_to.id != user_sessions[user_id].get('reply_id'):
        return
    
    new_name = event.text.strip()
    
    # Validate new name
    if not new_name:
        await event.reply("❌ Please provide a valid filename.")
        return
    
    # Add extension if missing
    extension_added = False
    if "." not in new_name and "." in user_sessions[user_id]['file_name']:
        original_ext = os.path.splitext(user_sessions[user_id]['file_name'])[1]
        new_name += original_ext
        extension_added = True
        await event.reply(f"ℹ️ Extension added automatically: <code>{new_name}</code>", parse_mode='html')
    
    # Process based on action
    try:
        if action == 'rename_only':
            await fast_rename_only(event, user_id, new_name)
        elif action == 'add_thumbnail_rename':
            await process_with_thumbnail(event, user_id, new_name)
        
        # NEW: Delete MEDIA INFO message if present
        if 'media_info_msg' in user_sessions.get(user_id, {}):
            try:
                await user_sessions[user_id]['media_info_msg'].delete()
            except:
                pass  # Ignore if already deleted
        
        # NEW: Delete rename_only prompt message if present
        if 'rename_prompt_msg' in user_sessions.get(user_id, {}):
            try:
                await user_sessions[user_id]['rename_prompt_msg'].delete()
            except:
                pass  # Ignore if already deleted
                
    except Exception as e:
        # If an error occurs, handle it here
        if "Content of the message was not modified" not in str(e):
            raise

async def process_file(event, user_id, new_name=None, use_thumb=False):
    """Generic function to process (download and upload) a file."""
    
    if user_id not in user_sessions:
        # Session might have expired or been cancelled
        return

    progress_msg = None
    reencoded_path = None
    temp_path = None

    try:
        if new_name is None:
            new_name = user_sessions[user_id]['file_name']
        
        sanitized_name = sanitize_filename(new_name)
        # Add custom text if present
        custom_text = sessions.get(user_id, {}).get('custom_text', '')
        text_position = sessions.get(user_id, {}).get('text_position', 'end')
        if custom_text:
            sanitized_name = add_custom_text_to_filename(sanitized_name, custom_text, text_position)
        # Add custom username if present
        custom_username = sessions.get(user_id, {}).get('custom_username', '')
        if custom_username:
            sanitized_name = add_custom_text_to_filename(sanitized_name, custom_username, text_position)
        
        # Progress message
        if isinstance(event, events.CallbackQuery.Event):
             progress_msg = await event.edit("⏳ <b>Processing...</b>", parse_mode='html')
        else:
             progress_msg = await event.reply("⏳ <b>Processing...</b>", parse_mode='html')

        await bot(SetTypingRequest(
            event.chat_id, 
            SendMessageUploadDocumentAction(progress=0)
        ))
        
        original_msg = user_sessions[user_id]['message']
        is_video = user_sessions[user_id].get('is_video', False)
        
        temp_filename = "{}_{}_{}".format(user_id, int(time.time()), uuid.uuid4().hex[:8])
        temp_path = os.path.join(TEMP_DIR, temp_filename)
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
        
        # Get video attributes if it's a video
        video_attributes = []
        if is_video:
            duration = get_video_duration(temp_path)
            width, height = get_video_dimensions(temp_path)
            
            if duration or (width and height):
                video_attr = DocumentAttributeVideo(
                    duration=duration or 0,
                    w=width or 0,
                    h=height or 0,
                    supports_streaming=True
                )
                video_attributes.append(video_attr)
        
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
            supports_streaming=False,  # Force name display
            force_document=True,       # Force sending as document
            attributes=file_attributes,
            progress_callback=upload_progress,
            part_size_kb=512  # Optimized chunks for better performance
        )
        
        await progress_msg.delete()
        
        # Update user usage after successful processing
        if user_id in user_sessions and 'file_size' in user_sessions[user_id]:
            update_user_usage(user_id, user_sessions[user_id]['file_size'])
            logging.info(f"Usage updated for user {user_id}: +{human_readable_size(user_sessions[user_id]['file_size'])}")
        
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

        if user_id in user_sessions:
            del user_sessions[user_id]

async def fast_rename_only(event, user_id, new_name):
    """Ultra-fast file rename without re-upload or thumbnail logic."""
    if user_id not in user_sessions:
        return

    progress_msg = None
    try:
        # Clean up name
        sanitized_name = sanitize_filename(new_name)
        # Keep original extension if missing
        original_filename = user_sessions[user_id]['file_name']
        file_extension = os.path.splitext(original_filename)[1]
        if not sanitized_name.endswith(file_extension):
            sanitized_name += file_extension

        # Progress message
        progress_msg = await event.reply("⚡ <b>Renaming in progress...</b>", parse_mode='html')

        original_msg = user_sessions[user_id]['message']
        is_video = user_sessions[user_id].get('is_video', False)

        # Generate unique local path per user and file id
        file_id = original_msg.file.id
        local_path = get_local_file_path(user_id, file_id, file_extension)

        # Check if already in cache, otherwise download only once
        if os.path.exists(local_path):
            await safe_edit(progress_msg, "🚀 <b>File found locally!</b> No download needed.", parse_mode='html')
        else:
            await safe_edit(progress_msg, "📥 <b>Downloading file (1st time)...</b>", parse_mode='html')
            downloaded_path = await original_msg.download_media(file=local_path)
            if not downloaded_path or not os.path.exists(downloaded_path):
                raise Exception("Failed to download file")
            if downloaded_path != local_path:
                shutil.move(downloaded_path, local_path)

        # Create a renamed temporary copy
        temp_renamed_path = os.path.join(TEMP_DIR, f"{user_id}_{int(time.time())}_{sanitized_name}")
        shutil.copy2(local_path, temp_renamed_path)

        # File attributes (name)
        file_attributes = [DocumentAttributeFilename(sanitized_name)]
        # Video attribute if needed
        if is_video:
            duration = get_video_duration(temp_renamed_path)
            width, height = get_video_dimensions(temp_renamed_path)
            if duration or (width and height):
                video_attr = DocumentAttributeVideo(
                    duration=duration or 0,
                    w=width or 0,
                    h=height or 0,
                    supports_streaming=True
                )
                file_attributes.append(video_attr)

        # Caption
        caption = f"<code>{sanitized_name}</code>"

        await safe_edit(progress_msg, "📤 <b>Sending renamed file...</b>", parse_mode='html')

        await event.client.send_file(
            event.chat_id,
            temp_renamed_path,
            caption=caption,
            parse_mode='html',
            file_name=sanitized_name,
            supports_streaming=is_video,
            force_document=not is_video,
            attributes=file_attributes
        )
        await progress_msg.delete()

        # Update usage if tracking is enabled
        if 'file_size' in user_sessions[user_id]:
            update_user_usage(user_id, user_sessions[user_id]['file_size'])

        try:
            os.remove(temp_renamed_path)
        except:
            pass

        # Delete prompt messages before cleaning up the session
        if 'media_info_msg' in user_sessions.get(user_id, {}):
            try:
                await user_sessions[user_id]['media_info_msg'].delete()
            except:
                pass
        if 'rename_prompt_msg' in user_sessions.get(user_id, {}):
            try:
                await user_sessions[user_id]['rename_prompt_msg'].delete()
            except:
                pass
        
        del user_sessions[user_id]

    except Exception as e:
        error_msg = f"❌ <b>Error:</b> {str(e)}"
        if progress_msg:
            await safe_edit(progress_msg, error_msg, parse_mode='html')
        else:
            await event.reply(error_msg, parse_mode='html')
        if 'temp_renamed_path' in locals() and os.path.exists(temp_renamed_path):
            try:
                os.remove(temp_renamed_path)
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

async def process_with_thumbnail(event, user_id, new_name):
    """Processes the file with thumbnail and new name"""
    
    if user_id not in user_sessions:
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
        
        custom_username = sessions.get(user_id, {}).get('custom_username', '')
        if custom_username:
            sanitized_name = add_custom_text_to_filename(sanitized_name, custom_username, text_position)
        
        progress_msg = await event.reply("🖼️ <b>Processing with thumbnail...</b>", parse_mode='html')
        
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
        
        # Prepare attributes
        file_attributes = [DocumentAttributeFilename(sanitized_name)]
        
        if is_video:
            duration = get_video_duration(temp_path)
            width, height = get_video_dimensions(temp_path)
            
            if duration or (width and height):
                video_attr = DocumentAttributeVideo(
                    duration=duration or 0,
                    w=width or 0,
                    h=height or 0,
                    supports_streaming=True
                )
                file_attributes.append(video_attr)
        
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
            supports_streaming=is_video,
            force_document=not is_video,
            attributes=file_attributes
        )
        
        await progress_msg.delete()
        
        # Update usage
        update_user_usage(user_id, file_size)
        
        # Clean up
        try:
            os.remove(temp_path)
        except:
            pass
        
        # Delete prompt messages before cleaning up the session
        if 'media_info_msg' in user_sessions.get(user_id, {}):
            try:
                await user_sessions[user_id]['media_info_msg'].delete()
            except:
                pass
        if 'rename_prompt_msg' in user_sessions.get(user_id, {}):
            try:
                await user_sessions[user_id]['rename_prompt_msg'].delete()
            except:
                pass
        
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
    
    # Send a message to admins if configured
    async def notify_admins():
        if ADMIN_IDS:
            admin_list = [int(x) for x in str(ADMIN_IDS).split(',') if x.strip()]
            for admin_id in admin_list:
                try:
                    await bot.send_message(
                        admin_id, 
                        f"🟢 <b>Bot started!</b>\n\n"
                        f"Rename bot is now online and ready.\n\n"
                        f"📈 Daily limit: {human_readable_size(DAILY_LIMIT_BYTES)}\n"
                        f"⏱ Cooldown: {COOLDOWN_SECONDS}s\n"
                        f"⚡ Fast mode: ENABLED\n"
                        f"📢 Force Join: @{FORCE_JOIN_CHANNEL}",
                        parse_mode='html'
                    )
                except:
                    pass
    
    # Start automatic cleanup task
    async def start_cleanup():
        await auto_cleanup_task()
    
    # Notify admins and start cleanup
    bot.loop.run_until_complete(notify_admins())
    bot.loop.create_task(start_cleanup())
    
    # Start the bot
    print("\n✅ Bot is running! Press Ctrl+C to stop.\n")
    bot.run_until_disconnected()

if __name__ == '__main__':
    main()