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
from telethon.errors import FloodWaitError
from telethon.tl.functions.messages import SetTypingRequest
from telethon.tl.types import SendMessageTypingAction, SendMessageUploadDocumentAction
import logging

# Import de la configuration

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
TOKEN = os.getenv("TOKEN")
ADMIN_IDS = os.getenv("ADMIN_IDS")

# Configuration
MAX_FILE_SIZE = 2000 * 1024 * 1024  # 2 GB
TEMP_DIR = "temp_files"
THUMBNAIL_DIR = "thumbnails"
USER_TIMEOUT = 600  # 10 minutes
PROGRESS_UPDATE_INTERVAL = 5  # secondes
MAX_THUMB_SIZE = 200 * 1024  # 200 KB

# Nouvelles limites
DAILY_LIMIT_GB = 1  # 1 GB par jour par utilisateur
DAILY_LIMIT_BYTES = DAILY_LIMIT_GB * 1024 * 1024 * 1024
COOLDOWN_SECONDS = 30  # 30 secondes entre les fichiers

# Configuration du logging
logging.basicConfig(
    format='[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s',
    level=logging.INFO
)

# Dictionnaire pour stocker les sessions utilisateur
user_sessions = {}

# Système de limites d'utilisation
user_usage = defaultdict(lambda: {'daily_bytes': 0, 'last_reset': None, 'last_file_time': None})
usage_file = "user_usage.json"

# Système de préférences utilisateur
sessions = {}  # Pour stocker les préférences utilisateur

DEFAULT_USERNAME = "@dino_renamebot"  # Mets ici ton vrai username

def clean_filename_text(text):
    """Nettoie le texte en supprimant tous les @username et hashtags"""
    if not text:
        return text
    # Supprimer tous les formats de @username
    text = re.sub(r'[\[\(\{]?@\w+[\]\)\}]?', '', text, flags=re.IGNORECASE)
    # Supprimer les hashtags
    text = re.sub(r'#\w+', '', text, flags=re.IGNORECASE)
    # Supprimer les espaces multiples
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def add_custom_text_to_filename(filename, custom_text=None, position='end'):
    """Ajoute un texte personnalisé au nom du fichier"""
    if not custom_text:
        return filename
    
    name, ext = os.path.splitext(filename)
    
    # Nettoyer d'abord le nom existant
    name = clean_filename_text(name)
    
    # Ajouter le texte personnalisé
    if position == 'end':
        name = f"{name} {custom_text}"
    else:  # start
        name = f"{custom_text} {name}"
    
    # Nettoyer les espaces multiples
    name = re.sub(r'\s+', ' ', name).strip()
    
    return f"{name}{ext}"

def add_default_username_to_filename(filename, username, position='end'):
    name, ext = os.path.splitext(filename)
    # Évite de l’ajouter plusieurs fois
    if username.lower() in name.lower():
        return filename
    if position == 'end':
        name = f"{name} {username}"
    else:
        name = f"{username} {name}"
    name = re.sub(r'\s+', ' ', name).strip()
    return f"{name}{ext}"

def save_user_preferences():
    """Sauvegarde les préférences utilisateur"""
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
        logging.error(f"Erreur sauvegarde préférences: {e}")

def load_user_preferences():
    """Charge les préférences utilisateur"""
    try:
        if os.path.exists('user_preferences.json'):
            with open('user_preferences.json', 'r') as f:
                prefs = json.load(f)
                for user_id_str, pref_data in prefs.items():
                    user_id = int(user_id_str)
                    sessions[user_id] = pref_data
    except Exception as e:
        logging.error(f"Erreur chargement préférences: {e}")

# Créer le dossier temporaire
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(THUMBNAIL_DIR, exist_ok=True)

# Initialiser le client Telethon
bot = TelegramClient('rename_bot', API_ID, API_HASH).start(bot_token=TOKEN)

def load_user_usage():
    """Charge les données d'utilisation depuis le fichier"""
    try:
        if os.path.exists(usage_file):
            with open(usage_file, 'r') as f:
                data = json.load(f)
                for user_id_str, usage_data in data.items():
                    user_id = int(user_id_str)
                    user_usage[user_id] = usage_data
    except Exception as e:
        logging.error(f"Erreur chargement usage: {e}")

def save_user_usage():
    """Sauvegarde les données d'utilisation dans le fichier"""
    try:
        data = {}
        for user_id, usage_data in user_usage.items():
            data[str(user_id)] = usage_data
        with open(usage_file, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logging.error(f"Erreur sauvegarde usage: {e}")

def reset_daily_usage_if_needed(user_id):
    """Réinitialise l'utilisation quotidienne si nécessaire"""
    now = datetime.now()
    last_reset = user_usage[user_id].get('last_reset')
    
    if last_reset:
        last_reset = datetime.fromisoformat(last_reset)
        if now.date() > last_reset.date():
            user_usage[user_id]['daily_bytes'] = 0
            user_usage[user_id]['last_reset'] = now.isoformat()
            logging.info(f"Reset quotidien pour user {user_id}")
    else:
        user_usage[user_id]['last_reset'] = now.isoformat()

def check_user_limits(user_id, file_size):
    """Vérifie les limites de l'utilisateur"""
    reset_daily_usage_if_needed(user_id)
    
    # Vérifier la limite quotidienne
    current_daily = user_usage[user_id]['daily_bytes']
    if current_daily + file_size > DAILY_LIMIT_BYTES:
        remaining = DAILY_LIMIT_BYTES - current_daily
        return False, f"Limite quotidienne atteinte! Utilisé: {human_readable_size(current_daily)}/{human_readable_size(DAILY_LIMIT_BYTES)}. Restant: {human_readable_size(remaining)}"
    
    # Vérifier le délai entre les fichiers
    last_file_time = user_usage[user_id].get('last_file_time')
    if last_file_time:
        last_file_time = datetime.fromisoformat(last_file_time)
        time_since_last = (datetime.now() - last_file_time).total_seconds()
        if time_since_last < COOLDOWN_SECONDS:
            remaining_cooldown = COOLDOWN_SECONDS - time_since_last
            return False, f"Attendez {int(remaining_cooldown)} secondes avant le prochain fichier"
    
    return True, "OK"

def update_user_usage(user_id, file_size):
    """Met à jour l'utilisation de l'utilisateur"""
    user_usage[user_id]['daily_bytes'] += file_size
    user_usage[user_id]['last_file_time'] = datetime.now().isoformat()
    save_user_usage()

def get_user_usage_info(user_id):
    """Retourne les informations d'utilisation de l'utilisateur"""
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
    """Nettoie tous les fichiers d'un utilisateur (sauf thumbnails)"""
    try:
        # Supprimer les fichiers temporaires de l'utilisateur
        for filename in os.listdir(TEMP_DIR):
            if filename.startswith(f"{user_id}_"):
                filepath = os.path.join(TEMP_DIR, filename)
                try:
                    if os.path.isfile(filepath):
                        os.remove(filepath)
                        logging.info(f"Fichier utilisateur supprimé: {filename}")
                except Exception as e:
                    logging.error(f"Erreur suppression fichier {filename}: {e}")
        
        # Nettoyer les sessions
        if user_id in user_sessions:
            if 'temp_path' in user_sessions[user_id]:
                try:
                    os.remove(user_sessions[user_id]['temp_path'])
                except:
                    pass
            del user_sessions[user_id]
            
        logging.info(f"Nettoyage complet effectué pour user {user_id}")
        return True
    except Exception as e:
        logging.error(f"Erreur nettoyage user {user_id}: {e}")
        return False

async def auto_cleanup_task():
    """Tâche de nettoyage automatique qui s'exécute toutes les heures"""
    while True:
        try:
            await asyncio.sleep(3600)  # 1 heure
            
            # Nettoyer les sessions expirées
            await clean_old_sessions()
            
            # Nettoyer les fichiers orphelins
            current_time = time.time()
            for filename in os.listdir(TEMP_DIR):
                filepath = os.path.join(TEMP_DIR, filename)
                if os.path.isfile(filepath):
                    file_age = current_time - os.path.getmtime(filepath)
                    if file_age > 3600:  # Plus d'1 heure
                        try:
                            os.remove(filepath)
                            logging.info(f"Fichier orphelin supprimé: {filename}")
                        except Exception as e:
                            logging.error(f"Erreur suppression orphelin {filename}: {e}")
            
            logging.info("Nettoyage automatique effectué")
            
        except Exception as e:
            logging.error(f"Erreur nettoyage automatique: {e}")
            await asyncio.sleep(300)  # Attendre 5 minutes en cas d'erreur

def human_readable_size(size_bytes):
    """Convertit une taille en bytes en format lisible"""
    if size_bytes == 0:
        return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return "{} {}".format(s, size_name[i])

def sanitize_filename(filename):
    """Nettoie le nom de fichier pour éviter les problèmes"""
    # Supprimer les caractères interdits
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # Supprimer les espaces en début/fin
    filename = filename.strip('. ')
    # Limiter la longueur
    name, ext = os.path.splitext(filename)
    if len(name) > 200:
        name = name[:200]
    return name + ext

def get_video_duration(file_path):
    """Obtenir la durée d'une vidéo avec ffprobe"""
    try:
        import subprocess
        import json
        
        # Si ffprobe n'est pas disponible, retourner None
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
    """Obtenir les dimensions d'une vidéo avec ffprobe"""
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
    """Callback pour afficher la progression"""
    now = time.time()
    
    if last_update_time is not None:
        if now - last_update_time[0] < PROGRESS_UPDATE_INTERVAL:
            return
        last_update_time[0] = now
    
    diff = now - start_time
    
    # Éviter la division par zéro au tout début
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
    
    try:
        await progress_msg.edit(text, parse_mode='html')
    except FloodWaitError as e:
        logging.warning(f"Rate limit hit in progress_callback. Sleeping for {e.seconds} seconds.")
        await asyncio.sleep(e.seconds)
    except Exception:
        # Ignorer les autres erreurs d'édition (par exemple, message non modifié)
        pass

async def clean_old_sessions():
    """Nettoie les sessions expirées"""
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

@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    """Handler amélioré pour la commande /start"""
    user_id = event.sender_id
    
    # Charger les données si pas déjà fait
    if not hasattr(start_handler, 'data_loaded'):
        load_user_usage()
        load_user_preferences()
        start_handler.data_loaded = True
    
    # Obtenir les informations d'utilisation
    usage_info = get_user_usage_info(user_id)
    
    # Vérifier si l'utilisateur a un texte personnalisé
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
• Cooldown: 30 seconds between files

<b>🎯 Commands:</b>
/start - Show this message
/settings - Configure bot settings ⚙️
/usage - Check your usage limits
/setthumb - Set custom thumbnail
/delthumb - Delete custom thumbnail
/cancel - Cancel current operation

<b>📤 Just send me a file to get started!</b>"""
    
    # Bouton Settings
    keyboard = [
        [Button.inline("⚙️ Settings", "show_settings")]
    ]
    
    await event.reply(welcome_text, parse_mode='html', buttons=keyboard)

@bot.on(events.NewMessage(pattern='/cancel'))
async def cancel_handler(event):
    """Handler pour annuler l'opération en cours"""
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
    """Handler pour vérifier le statut du bot"""
    active_sessions = len(user_sessions)
    
    # Vérifier l'espace disque (Windows compatible)
    if os.name == 'nt':  # Windows
        import shutil
        total, used, free = shutil.disk_usage(TEMP_DIR)
        free_space = free
    else:  # Linux/Mac
        stat = os.statvfs(TEMP_DIR)
        free_space = stat.f_bavail * stat.f_frsize
    
    # Vérifier ffmpeg
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
    """Handler pour vérifier l'utilisation de l'utilisateur"""
    user_id = event.sender_id
    usage_info = get_user_usage_info(user_id)
    
    # Créer une barre de progression
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
    """Handler pour la commande /settings"""
    await show_settings_menu(event)

async def show_settings_menu(event):
    """Affiche le menu des paramètres"""
    user_id = event.sender_id if hasattr(event, 'sender_id') else event.query.user_id
    
    # Charger les préférences si nécessaire
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
    """Handler pour nettoyer les fichiers de l'utilisateur (admin seulement)"""
    user_id = event.sender_id
    
    # Vérifier si l'utilisateur est admin
    admin_list = [int(x) for x in str(ADMIN_IDS).split(',') if x.strip()] if ADMIN_IDS else []
    
    if user_id not in admin_list:
        await event.reply("❌ <b>Access denied.</b> This command is for administrators only.", parse_mode='html')
        return
    
    # Nettoyer les fichiers de l'utilisateur
    success = await cleanup_user_files(user_id)
    
    if success:
        await event.reply("✅ <b>Cleanup completed!</b>\n\nAll user files have been cleaned (thumbnails preserved).", parse_mode='html')
    else:
        await event.reply("❌ <b>Cleanup failed.</b>\n\nSome files could not be deleted.", parse_mode='html')

@bot.on(events.NewMessage(pattern='/setthumb'))
async def setthumb_handler(event):
    """Handler pour définir une miniature"""
    user_id = event.sender_id
    
    # Stocker que l'utilisateur veut définir un thumbnail
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
    """Handler pour supprimer la miniature"""
    user_id = event.sender_id
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
    """Handler pour afficher la miniature actuelle"""
    user_id = event.sender_id
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
    """Handler pour les photos (thumbnails)"""
    user_id = event.sender_id
    
    # Vérifier si l'utilisateur est en mode set_thumbnail
    if user_id in user_sessions and user_sessions[user_id].get('action') == 'set_thumbnail':
        # Vérifier la taille
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
        
        # Sauvegarder la miniature
        thumb_path = os.path.join(THUMBNAIL_DIR, "{}.jpg".format(user_id))
        
        try:
            # Message de progression
            progress_msg = await event.reply("⏳ <b>Saving thumbnail...</b>", parse_mode='html')
            
            # Télécharger la photo
            await event.download_media(file=thumb_path)
            
            # Confirmer
            await progress_msg.edit(
                "✅ <b>Thumbnail saved successfully!</b>\n\n"
                "This thumbnail will be used for all your renamed files.\n"
                "Use /delthumb to remove it.",
                parse_mode='html'
            )
            
            # Nettoyer la session
            del user_sessions[user_id]
            
        except Exception as e:
            await progress_msg.edit(
                "❌ <b>Error saving thumbnail:</b> {}".format(str(e)),
                parse_mode='html'
            )
            if user_id in user_sessions:
                del user_sessions[user_id]

@bot.on(events.NewMessage(func=lambda e: e.file and not e.photo))
async def file_handler(event):
    """Handler principal pour les fichiers (pas les photos)"""
    user_id = event.sender_id
    
    # Nettoyer les anciennes sessions
    await clean_old_sessions()
    
    file = event.file
    
    # Vérifier la taille du fichier
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
    
    # Vérifier les limites de l'utilisateur
    limit_ok, limit_message = check_user_limits(user_id, file.size)
    if not limit_ok:
        await event.reply(
            "⚠️ <b>Usage Limit Reached!</b>\n\n{}\n\nUse /usage to check your limits.".format(limit_message),
            parse_mode='html'
        )
        return
    
    # Obtenir les informations du fichier
    file_name = file.name or "unnamed_file"
    file_size = human_readable_size(file.size)
    extension = os.path.splitext(file_name)[1] or ""
    mime_type = file.mime_type or "unknown"
    
    # Vérifier si c'est une vidéo
    is_video = mime_type.startswith('video/') or extension.lower() in ['.mp4', '.mkv', '.webm', '.avi', '.mov', '.flv']
    
    # Stocker les informations de session
    user_sessions[user_id] = {
        'message': event.message,
        'file_name': file_name,
        'timestamp': datetime.now(),
        'action': None,
        'is_video': is_video,
        'file_size': file.size  # Stocker la taille pour la mise à jour de l'utilisation
    }
    
    # Créer les boutons
    buttons = [
        [Button.inline("🖼️ Add Thumbnail", f"add_thumb_{user_id}")],
        [Button.inline("✏️ Rename Only", f"rename_only_{user_id}")],
        [Button.inline("❌ Cancel", f"cancel_{user_id}")]
    ]
    
    # Obtenir les informations d'utilisation pour l'affichage
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
    """Handler optimisé pour les boutons inline"""
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
        message += "Send me the username to add to all filenames (e.g. <code>@monchannel</code>).\n\nSend /cancel to abort."
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
            
            try:
                # ⚡ UPLOAD RAPIDE AVEC THUMBNAIL INTÉGRÉ
                await event.edit("⚡ <b>Processing with thumbnail...</b>", parse_mode='html')
                
                original_msg = user_sessions[user_id]['message']
                file_name = user_sessions[user_id]['file_name']
                file_size = user_sessions[user_id]['file_size']
                is_video = user_sessions[user_id].get('is_video', False)
                
                # Appliquer les modifications de nom si configurées
                clean_tags = sessions.get(user_id, {}).get('clean_tags', True)
                if clean_tags:
                    file_name = clean_filename_text(file_name)
                
                custom_text = sessions.get(user_id, {}).get('custom_text', '')
                text_position = sessions.get(user_id, {}).get('text_position', 'end')
                
                if custom_text:
                    file_name = add_custom_text_to_filename(file_name, custom_text, text_position)
                
                custom_username = sessions.get(user_id, {}).get('custom_username', '')
                if custom_username:
                    file_name = add_custom_text_to_filename(file_name, custom_username, text_position)
                
                sanitized_name = sanitize_filename(file_name)
                
                # Créer un fichier temporaire pour le traitement
                temp_filename = f"{user_id}_{int(time.time())}_{uuid.uuid4().hex[:8]}"
                temp_path = os.path.join(TEMP_DIR, temp_filename)
                
                # Télécharger le fichier avec progression
                await event.edit("⬇️ <b>Downloading...</b>", parse_mode='html')
                
                start_time = time.time()
                last_update_time = [start_time]
                
                async def download_progress(current, total):
                    now = time.time()
                    if now - last_update_time[0] < 3:  # Update toutes les 3 secondes
                        return
                    last_update_time[0] = now
                    
                    percentage = current * 100 / total
                    speed = current / (now - start_time)
                    eta = int((total - current) / speed) if speed > 0 else 0
                    
                    try:
                        await event.edit(
                            f"⬇️ <b>Downloading...</b>\n\n"
                            f"Progress: {percentage:.1f}%\n"
                            f"Speed: {human_readable_size(speed)}/s\n"
                            f"ETA: {eta}s",
                            parse_mode='html'
                        )
                    except:
                        pass
                
                path = await original_msg.download_media(
                    file=temp_path,
                    progress_callback=download_progress
                )
                
                if not path or not os.path.exists(path):
                    raise Exception("Failed to download file")
                
                if path != temp_path:
                    shutil.move(path, temp_path)
                
                # Pour les vidéos, intégrer le thumbnail avec FFmpeg
                if is_video and shutil.which("ffmpeg"):
                    await event.edit("🎬 <b>Adding thumbnail to video...</b>", parse_mode='html')
                    
                    output_path = temp_path + "_with_thumb.mp4"
                    
                    # Commande FFmpeg pour ajouter le thumbnail
                    cmd = [
                        'ffmpeg', '-i', temp_path,
                        '-i', thumb_path,
                        '-map', '0:v', '-map', '0:a',
                        '-map', '1:v', '-c', 'copy',
                        '-c:v:1', 'mjpeg', '-disposition:v:1', 'attached_pic',
                        output_path,
                        '-hide_banner', '-loglevel', 'error'
                    ]
                    
                    process = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    stdout, stderr = await process.communicate()
                    
                    if process.returncode == 0:
                        # Remplacer le fichier original par celui avec thumbnail
                        os.remove(temp_path)
                        temp_path = output_path
                    else:
                        logging.error(f"FFmpeg failed: {stderr.decode()}")
                        # Continuer sans thumbnail intégré
                
                # Pour les autres types de fichiers, utiliser le thumbnail comme preview
                # (Le thumbnail sera visible dans Telegram mais pas intégré dans le fichier)
                elif not is_video:
                    await event.edit("📄 <b>Processing document with thumbnail...</b>", parse_mode='html')
                
                # Upload du fichier avec thumbnail intégré
                await event.edit("📤 <b>Uploading with thumbnail...</b>", parse_mode='html')
                
                # Récupérer les attributs vidéo si c'est une vidéo
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
                
                # Attributs du fichier
                file_attributes = [DocumentAttributeFilename(sanitized_name)]
                if video_attributes:
                    file_attributes.extend(video_attributes)
                
                # Upload avec thumbnail intégré ou preview
                thumb_to_use = None
                if not is_video:
                    # Pour les documents, utiliser le thumbnail comme preview
                    thumb_to_use = thumb_path
                
                await bot.send_file(
                    event.chat_id,
                    temp_path,
                    caption="",
                    parse_mode='html',
                    file_name=sanitized_name,
                    thumb=thumb_to_use,  # Thumbnail pour preview (documents)
                    supports_streaming=is_video,
                    attributes=file_attributes
                )
                
                # Mise à jour de l'utilisation
                update_user_usage(user_id, file_size)
                
                # Nettoyage
                try:
                    os.remove(temp_path)
                except:
                    pass
                
                await event.delete()
                del user_sessions[user_id]
                
            except Exception as e:
                await event.edit(f"❌ <b>Error:</b> {str(e)}", parse_mode='html')
                # Nettoyage en cas d'erreur
                try:
                    if 'temp_path' in locals() and os.path.exists(temp_path):
                        os.remove(temp_path)
                except:
                    pass
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
            # Store message ID to ensure user replies to the correct message
            user_sessions[user_id]['reply_id'] = ask_msg.id
        else:
            await event.answer("❌ This is not for you or the session has expired.", alert=True)

    elif data == 'help':
        # Message d'aide détaillé
        help_text = """📚 <b>How to use this bot:</b>

1️⃣ Send me any file (document, video, audio)
2️⃣ Choose an action: 'Add Thumbnail' or 'Rename Only'.
3️⃣ **For Renaming:** Reply with the new filename (including extension).
4️⃣ **For Thumbnail:** Make sure you have set a thumbnail with /setthumb.

<b>💡 Tips:</b>
• Use descriptive filenames
• Keep the correct extension
• Avoid special characters like / \ : * ? " < > |
• Maximum file size: 2 GB

<b>⚡ Commands:</b>
/start - Show welcome message
/cancel - Cancel current operation
/status - Check bot status"""
        
        await event.respond(help_text, parse_mode='html')
        await event.answer("ℹ️ Help sent!")  # Petite notification

@bot.on(events.NewMessage(func=lambda e: e.text and e.is_private and not e.text.startswith('/')))
async def text_handler(event):
    """Handler pour les messages texte"""
    user_id = event.sender_id
    
    if user_id not in sessions:
        return
    
    # Si on attend un texte personnalisé
    if sessions[user_id].get('awaiting_custom_text'):
        custom_text = event.text.strip()
        
        if len(custom_text) > 50:
            await event.reply("❌ Text too long! Maximum 50 characters.")
            return
        
        # Sauvegarder le texte
        sessions[user_id]['custom_text'] = custom_text
        sessions[user_id]['awaiting_custom_text'] = False
        
        # Position par défaut
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
    # Si on attend un username personnalisé
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
    """Handler pour renommer les fichiers"""
    user_id = event.sender_id
    
    # Vérifier si c'est une réponse valide et si l'action est 'rename_only'
    if user_id not in user_sessions or user_sessions[user_id].get('action') != 'rename_only':
        return
    
    # Nettoyer les anciennes sessions
    await clean_old_sessions()
    
    # Vérifier si la session n'a pas expiré
    if user_id not in user_sessions:
        await event.reply("⏱ Session expired. Please send the file again.")
        return
    
    reply_to = await event.get_reply_message()
    # Ensure the user is replying to the "send me new name" message
    if reply_to.id != user_sessions[user_id].get('reply_id'):
        return
    
    new_name = event.text.strip()
    
    # Valider le nouveau nom
    if not new_name:
        await event.reply("❌ Please provide a valid filename.")
        return
    
    if "." not in new_name and "." in user_sessions[user_id]['file_name']:
        # Ajouter l'extension originale si oubliée
        original_ext = os.path.splitext(user_sessions[user_id]['file_name'])[1]
        new_name += original_ext
        await event.reply("ℹ️ Extension added automatically: <code>{}</code>".format(new_name), parse_mode='html')

    # Lancer le traitement du fichier pour le renommage sans miniature
    await process_file(event, user_id, new_name=new_name, use_thumb=False)

async def process_file(event, user_id, new_name=None, use_thumb=False):
    """Fonction générique pour traiter (télécharger et uploader) un fichier."""
    
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
        # Ajout du custom text si présent
        custom_text = sessions.get(user_id, {}).get('custom_text', '')
        text_position = sessions.get(user_id, {}).get('text_position', 'end')
        if custom_text:
            sanitized_name = add_custom_text_to_filename(sanitized_name, custom_text, text_position)
        # Ajout du username custom si présent
        custom_username = sessions.get(user_id, {}).get('custom_username', '')
        if custom_username:
            sanitized_name = add_custom_text_to_filename(sanitized_name, custom_username, text_position)
        
        # Message de progression
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
        
        # Récupérer les attributs vidéo si c'est une vidéo
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
        
        # SKIP FFmpeg - pas nécessaire pour renommage simple
        # Optimisation désactivée pour améliorer les performances
        
        await progress_msg.edit("📤 <b>Uploading file...</b>", parse_mode='html')
        
        start_time = time.time()
        last_update_time_upload = [start_time]
        
        async def upload_progress(current, total):
            await progress_callback(current, total, event, start_time, progress_msg, "Uploading", last_update_time_upload)
        
        thumb_to_use = None
        if use_thumb:
            thumb_path = os.path.join(THUMBNAIL_DIR, "{}.jpg".format(user_id))
            if os.path.exists(thumb_path):
                thumb_to_use = thumb_path
        
        # Ajouter l'attribut filename
        file_attributes = [DocumentAttributeFilename(sanitized_name)]
        
        # Ajouter les attributs vidéo si disponibles
        if video_attributes:
            file_attributes.extend(video_attributes)
        
        # Envoyer le fichier avec tous les attributs nécessaires
        await event.client.send_file(
            event.chat_id,
            upload_path,
            caption="",  # Caption vide
            file_name=sanitized_name,
            thumb=thumb_to_use,
            supports_streaming=is_video,  # Active le streaming pour les vidéos
            attributes=file_attributes,    # Inclut tous les attributs nécessaires
            force_document=False,          # Permet à Telegram de détecter le type
            progress_callback=upload_progress,
            part_size_kb=512  # Chunks optimisés pour de meilleures performances
        )
        
        await progress_msg.delete()
        
        # Mettre à jour l'utilisation de l'utilisateur après un traitement réussi
        if user_id in user_sessions and 'file_size' in user_sessions[user_id]:
            update_user_usage(user_id, user_sessions[user_id]['file_size'])
            logging.info(f"Usage updated for user {user_id}: +{human_readable_size(user_sessions[user_id]['file_size'])}")
        
    except FloodWaitError as e:
        if progress_msg:
             await progress_msg.edit("⏳ Rate limit hit. Please wait {} seconds.".format(e.seconds))
        else:
            await event.reply("⏳ Rate limit hit. Please wait {} seconds.".format(e.seconds))
    except Exception as e:
        error_msg = "❌ <b>Error:</b> {}\n\nPlease try again.".format(str(e))
        if progress_msg:
            await progress_msg.edit(error_msg, parse_mode='html')
        else:
            await event.reply(error_msg, parse_mode='html')
        
    finally:
        # Nettoyage amélioré
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

def main():
    """Fonction principale modifiée"""
    print("🤖 Bot started successfully!")
    print("📁 Temp directory: {}".format(TEMP_DIR))
    print("📊 Max file size: {}".format(human_readable_size(MAX_FILE_SIZE)))
    print("🎬 FFmpeg: {}".format("Available" if shutil.which("ffmpeg") else "Not available"))
    print("📈 Daily limit: {} per user".format(human_readable_size(DAILY_LIMIT_BYTES)))
    print("⏱ Cooldown: {} seconds between files".format(COOLDOWN_SECONDS))
    print("⚡ Fast thumbnail mode: ENABLED")
    
    # Charger les données
    load_user_usage()
    load_user_preferences()
    print("📊 User data loaded")
    
    # Envoyer un message aux admins si configuré
    async def notify_admins():
        if ADMIN_IDS:
            admin_list = [int(x) for x in str(ADMIN_IDS).split(',') if x.strip()]
            for admin_id in admin_list:
                try:
                    await bot.send_message(
                        admin_id, 
                        "🟢 <b>Bot started!</b>\n\nRename bot is now online and ready.\n\n📈 Daily limit: {}\n⏱ Cooldown: {}s\n⚡ Fast mode: ENABLED".format(
                            human_readable_size(DAILY_LIMIT_BYTES),
                            COOLDOWN_SECONDS
                        ),
                        parse_mode='html'
                    )
                except:
                    pass
    
    # Démarrer la tâche de nettoyage automatique
    async def start_cleanup():
        await auto_cleanup_task()
    
    # Notifier les admins et démarrer le nettoyage
    bot.loop.run_until_complete(notify_admins())
    bot.loop.create_task(start_cleanup())
    
    # Démarrer le bot
    print("\n✅ Bot is running! Press Ctrl+C to stop.\n")
    bot.run_until_disconnected()

if __name__ == '__main__':
    main()