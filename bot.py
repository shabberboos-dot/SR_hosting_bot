import atexit
import html
from datetime import datetime, timedelta
import hashlib
import hmac
import json
import logging
from logging.handlers import RotatingFileHandler
import mimetypes
import os
import re
import shutil
import signal
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from flask import Flask
from threading import Thread
import psutil
import requests
import telebot
from telebot import types
from telebot import apihelper
from dotenv import load_dotenv

# --- .env ফাইল থেকে কনফিগারেশন লোড ---
load_dotenv()

# --- Flask Keep Alive ---
app = Flask(__name__)

@app.route("/")
def home():
    return "🚀 Shiyam Bot Host is Running!"

@app.route("/health")
def health():
    return {"status": "ok", "time": datetime.now().isoformat()}

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()
    print("✅ Flask Keep-Alive server started.")

# ==========================================================
# 🔧 কনফিগারেশন — এখানে আপনার তথ্য বসান
# ==========================================================

# 👇 এখানে আপনার বট টোকেন পেস্ট করুন
# Telegram-এ @BotFather → /mybots → আপনার bot → API Token থেকে পাবেন
# ফরম্যাট: 123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ
TOKEN = (os.environ.get("BOT_TOKEN") or "8998977328:AAGZv3aVCSyCojl6Yf-iiKCOhkbJLkiKlxg").strip()

# 👇 এখানে আপনার চ্যাট আইডি পেস্ট করুন (মালিক/Owner এর Telegram numeric ID)
# @userinfobot-এ মেসেজ দিলে "Id: XXXXX" দেখাবে সেটা এখানে বসান
_OWNER_DEFAULT = 8746661403

# 👇 এখানে অ্যাডমিনের চ্যাট আইডি পেস্ট করুন (দ্বিতীয় অ্যাডমিন লাগলে)
# একই আইডি দিলেও চলবে
_ADMIN_DEFAULT = 8746661403

# 👇 এখানে আপনার Telegram username পেস্ট করুন (@ সহ) — উদাহরণ: @shiyam7444
YOUR_USERNAME = os.environ.get("USERNAME", "@BDT_NX_DEVELOPER").strip()

# 👇 এখানে আপনার Updates চ্যানেলের লিংক পেস্ট করুন
# উদাহরণ: https://t.me/shiyam744
UPDATE_CHANNEL = os.environ.get("UPDATE_CHANNEL", "https://t.me/shiyam744").strip()

# 👇 এখানে আপনার Binance Pay ID পেস্ট করুন
# Binance App → Pay → Receive → আপনার Pay ID
BINANCE_PAY_ID = os.environ.get("BINANCE_PAY_ID", "248391029").strip()

# 👇 এখানে ১ USDT = কত টাকা সেটা লিখুন (শুধু সংখ্যা)
USDT_BDT_RATE = float(os.environ.get("USDT_BDT_RATE", "120"))

# 👇 Binance API ব্যবহার করলে এখানে key বসান, না করলে খালি রাখুন
BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY", "").strip()
BINANCE_SECRET_KEY = os.environ.get("BINANCE_SECRET_KEY", "").strip()


# --- Safe int parsing ---
def _safe_int(env_key, default):
    val = (os.environ.get(env_key) or "").strip()
    if not val:
        val = str(default)
    try:
        return int(val)
    except (ValueError, TypeError):
        raise SystemExit(f"❌ {env_key} একটি সংখ্যা হতে হবে, পেয়েছি: {val!r}")


OWNER_ID = _safe_int("OWNER_ID", _OWNER_DEFAULT)
ADMIN_ID = _safe_int("ADMIN_ID", _ADMIN_DEFAULT)


# --- TOKEN validation ---
if not TOKEN or ":" not in TOKEN or len(TOKEN) < 30:
    raise SystemExit(
        "❌ BOT_TOKEN সেট করা হয়নি বা ভুল ফরম্যাটে আছে!\n"
        "👉 Environment variable 'BOT_TOKEN' সেট করুন।\n"
        "👉 সঠিক ফরম্যাট: 123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ"
    )

# ==========================================================
# কনফিগারেশন শেষ
# ==========================================================

# --- Folder Setup ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_BOTS_DIR = os.path.join(BASE_DIR, "upload_bots")
IROTECH_DIR = os.path.join(BASE_DIR, "inf")
DATABASE_PATH = os.path.join(IROTECH_DIR, "bot_data.db")
LOGS_DIR = os.path.join(IROTECH_DIR, "logs")

os.makedirs(UPLOAD_BOTS_DIR, exist_ok=True)
os.makedirs(IROTECH_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

# --- File Limits ---
FREE_USER_LIMIT = 0
SUBSCRIBED_USER_LIMIT = 15
ADMIN_LIMIT = 999
OWNER_LIMIT = float("inf")

# --- Telebot Timeout Config ---
apihelper.CONNECT_TIMEOUT = 60
apihelper.READ_TIMEOUT = 60
apihelper.SESSION_TIME_TO_LIVE = 5 * 60

# --- Initialize Bot ---
bot = telebot.TeleBot(TOKEN, threaded=True, num_threads=6)

# --- Data Structures ---
bot_scripts = {}
user_subscriptions = {}
user_files = {}
active_users = set()
admin_ids = {ADMIN_ID, OWNER_ID}
bot_locked = False
user_selected_plan = {}
last_start_time = {}
user_command_count = {}
file_index_map = {}

# --- Logging Setup ---
log_handler = RotatingFileHandler(
    os.path.join(LOGS_DIR, "bot.log"),
    maxBytes=5 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8"
)
log_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))

logging.basicConfig(level=logging.INFO, handlers=[log_handler, logging.StreamHandler()])
logger = logging.getLogger(__name__)
logging.getLogger("telebot").setLevel(logging.WARNING)
logging.getLogger("werkzeug").setLevel(logging.WARNING)

# --- Module/Package Mapping ---
TELEGRAM_MODULES = {
    "telebot": "pyTelegramBotAPI",
    "telegram": "python-telegram-bot",
    "python_telegram_bot": "python-telegram-bot",
    "aiogram": "aiogram",
    "pyrogram": "pyrogram",
    "telethon": "telethon",
    "discord": "discord.py",
    "discord.py": "discord.py",
    "nextcord": "nextcord",
    "hikari": "hikari",
    "flask": "Flask",
    "django": "Django",
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "requests": "requests",
    "aiohttp": "aiohttp",
    "httpx": "httpx",
    "bs4": "beautifulsoup4",
    "beautifulsoup4": "beautifulsoup4",
    "selenium": "selenium",
    "pillow": "Pillow",
    "PIL": "Pillow",
    "numpy": "numpy",
    "pandas": "pandas",
    "matplotlib": "matplotlib",
    "cv2": "opencv-python",
    "opencv": "opencv-python",
    "psutil": "psutil",
    "sqlite3": "sqlite3",
    "mysql": "mysql-connector-python",
    "pymongo": "pymongo",
    "redis": "redis",
    "celery": "celery",
    "asyncio": "asyncio",
    "websockets": "websockets",
    "jinja2": "Jinja2",
    "markdown": "markdown",
    "yaml": "PyYAML",
    "toml": "toml",
    "dotenv": "python-dotenv",
}

# ============================================
# 🎨 বাটন ফাংশনসমূহ
# ============================================

def create_professional_main_menu(user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(
            "🌟 𝐖𝐄𝐋𝐂𝐎𝐌𝐄 𝐓𝐎 𝐒𝐇𝐈𝐘𝐀𝐌 𝐇𝐎𝐒𝐓 🌟",
            callback_data="welcome",
            url="https://t.me/shiyam744"
        )
    )
    markup.add(
        types.InlineKeyboardButton("📤 𝐔𝐩𝐥𝐨𝐚𝐝 𝐅𝐢𝐥𝐞", callback_data="upload_file"),
        types.InlineKeyboardButton("📁 𝐌𝐚𝐧𝐚𝐠𝐞 𝐅𝐢𝐥𝐞𝐬", callback_data="manage_files")
    )
    markup.add(
        types.InlineKeyboardButton("💎 𝐕𝐢𝐞𝐰 𝐏𝐥𝐚𝐧𝐬", callback_data="view_plans"),
        types.InlineKeyboardButton("⚡ 𝐒𝐩𝐞𝐞𝐝 & 𝐏𝐢𝐧𝐠", callback_data="speed_ping")
    )
    markup.add(
        types.InlineKeyboardButton("📊 𝐁𝐨𝐭 𝐒𝐭𝐚𝐭𝐬", callback_data="bot_stats"),
        types.InlineKeyboardButton("💻 𝐓𝐞𝐫𝐦𝐢𝐧𝐚𝐥", callback_data="terminal")
    )
    markup.add(
        types.InlineKeyboardButton("👑 𝐂𝐨𝐧𝐭𝐚𝐜𝐭 𝐎𝐰𝐧𝐞𝐫", callback_data="contact_owner", url="https://t.me/shiyam7444"),
        types.InlineKeyboardButton("❓ 𝐇𝐞𝐥𝐩", callback_data="help")
    )
    if user_id in admin_ids:
        markup.add(types.InlineKeyboardButton("🛡️ 𝐀𝐝𝐦𝐢𝐧 𝐏𝐚𝐧𝐞𝐥", callback_data="admin_panel"))
    return markup

def create_file_management_buttons(owner_id, fname, is_running):
    key = f"{owner_id}_{fname}"
    file_index_map[key] = (owner_id, fname)

    markup = types.InlineKeyboardMarkup(row_width=2)
    if is_running:
        markup.add(types.InlineKeyboardButton("🟢 𝐑𝐮𝐧𝐧𝐢𝐧𝐠 ✅", callback_data="status_running"))
        markup.add(types.InlineKeyboardButton("⏹️ 𝐒𝐭𝐨𝐩", callback_data=f"stop_{key}"))
    else:
        markup.add(types.InlineKeyboardButton("🔴 𝐒𝐭𝐨𝐩𝐩𝐞𝐝 ❌", callback_data="status_stopped"))
        markup.add(types.InlineKeyboardButton("▶️ 𝐒𝐭𝐚𝐫𝐭", callback_data=f"start_{key}"))
    markup.add(
        types.InlineKeyboardButton("✏️ 𝐄𝐝𝐢𝐭", callback_data=f"edit_{key}"),
        types.InlineKeyboardButton("📊 𝐋𝐨𝐠𝐬", callback_data=f"logs_{key}")
    )
    markup.add(types.InlineKeyboardButton("🗑️ 𝐃𝐞𝐥𝐞𝐭𝐞", callback_data=f"del_{key}"))
    markup.add(types.InlineKeyboardButton("🔙 𝐁𝐚𝐜𝐤 𝐭𝐨 𝐅𝐢𝐥𝐞𝐬", callback_data="back_to_files"))
    return markup

def create_plan_card_buttons(plan_id, plan_name, price_usdt):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton(
        f"🛒 𝐁𝐮𝐲 {plan_name.upper()} - {price_usdt} USDT",
        callback_data=f"buy_binance_{plan_id}"
    ))
    markup.add(types.InlineKeyboardButton("📋 𝐕𝐢𝐞𝐰 𝐃𝐞𝐭𝐚𝐢𝐥𝐬", callback_data=f"plan_details_{plan_id}"))
    return markup

def create_professional_admin_panel():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("➕ 𝐀𝐝𝐝 𝐏𝐥𝐚𝐧", callback_data="add_plan_init"),
        types.InlineKeyboardButton("🗑️ 𝐌𝐚𝐧𝐚𝐠𝐞 𝐏𝐥𝐚𝐧𝐬", callback_data="manage_plans")
    )
    markup.add(
        types.InlineKeyboardButton("💎 𝐀𝐝𝐝 𝐒𝐮𝐛𝐬𝐜𝐫𝐢𝐩𝐭𝐢𝐨𝐧", callback_data="add_subscription"),
        types.InlineKeyboardButton("❌ 𝐑𝐞𝐦𝐨𝐯𝐞 𝐒𝐮𝐛", callback_data="remove_subscription")
    )
    markup.add(
        types.InlineKeyboardButton("👑 𝐀𝐝𝐝 𝐀𝐝𝐦𝐢𝐧", callback_data="add_admin"),
        types.InlineKeyboardButton("➖ 𝐑𝐞𝐦𝐨𝐯𝐞 𝐀𝐝𝐦𝐢𝐧", callback_data="remove_admin")
    )
    markup.add(
        types.InlineKeyboardButton("📣 𝐁𝐫𝐨𝐚𝐝𝐜𝐚𝐬𝐭", callback_data="broadcast"),
        types.InlineKeyboardButton("🔐 𝐋𝐨𝐜𝐤/𝐔𝐧𝐥𝐨𝐜𝐤", callback_data="toggle_lock")
    )
    markup.add(types.InlineKeyboardButton("🔙 𝐁𝐚𝐜𝐤 𝐭𝐨 𝐌𝐞𝐧𝐮", callback_data="back_to_menu"))
    return markup

def create_colorful_file_list(user_id, file_list):
    markup = types.InlineKeyboardMarkup(row_width=1)
    for idx, (file_name, file_type) in enumerate(sorted(file_list)):
        is_running = is_bot_running(user_id, file_name)
        status_icon = "🟢" if is_running else "🔴"
        status_text = "Running" if is_running else "Stopped"
        type_icon = {'py': '🐍', 'js': '📜', 'sh': '⚡', 'rb': '💎', 'go': '🐹'}.get(file_type, '📄')
        key = f"i_{user_id}_{idx}"
        file_index_map[key] = (user_id, file_name)
        button_text = f"{status_icon} {type_icon} {file_name} ({file_type}) - {status_text}"
        markup.add(types.InlineKeyboardButton(button_text, callback_data=f"file_{key}"))
    markup.add(types.InlineKeyboardButton("🔙 𝐁𝐚𝐜𝐤 𝐭𝐨 𝐌𝐞𝐧𝐮", callback_data="back_to_menu"))
    return markup

# --- Database Setup ---
DB_LOCK = threading.Lock()

def init_db():
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS subscriptions
                     (user_id INTEGER PRIMARY KEY, plan_name TEXT, expiry TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS user_files
                     (user_id INTEGER, file_name TEXT, file_type TEXT,
                      PRIMARY KEY (user_id, file_name))""")
        c.execute("""CREATE TABLE IF NOT EXISTS active_users
                     (user_id INTEGER PRIMARY KEY)""")
        c.execute("""CREATE TABLE IF NOT EXISTS admins
                     (user_id INTEGER PRIMARY KEY)""")
        c.execute("""CREATE TABLE IF NOT EXISTS plans
                     (plan_id INTEGER PRIMARY KEY AUTOINCREMENT,
                      name TEXT, file_limit INTEGER, price TEXT,
                      duration INTEGER, buy_link TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS pending_payments
                     (user_id INTEGER, plan_id INTEGER, paid_amount REAL,
                      PRIMARY KEY (user_id, plan_id))""")
        c.execute("""CREATE TABLE IF NOT EXISTS used_txids
                     (tx_id TEXT PRIMARY KEY)""")
        c.execute("""CREATE TABLE IF NOT EXISTS bot_settings
                     (key TEXT PRIMARY KEY, value TEXT)""")
        c.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (OWNER_ID,))
        if ADMIN_ID != OWNER_ID:
            c.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (ADMIN_ID,))
        conn.commit()
        conn.close()
        logger.info("✅ Database initialized.")
    except Exception as e:
        logger.error(f"❌ DB init error: {e}")

init_db()

# --- Settings helpers ---
def get_setting(key, default=None):
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute("SELECT value FROM bot_settings WHERE key=?", (key,))
        row = c.fetchone()
        conn.close()
        return row[0] if row else default
    except Exception:
        return default

def set_setting(key, value):
    try:
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)", (key, str(value)))
            conn.commit()
            conn.close()
    except Exception as e:
        logger.error(f"set_setting {key}: {e}")

def load_state_from_db():
    global active_users, admin_ids, user_subscriptions, user_files, bot_locked
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()

        c.execute("SELECT user_id FROM active_users")
        active_users = {row[0] for row in c.fetchall()}

        c.execute("SELECT user_id FROM admins")
        admin_ids = {row[0] for row in c.fetchall()}
        admin_ids.add(OWNER_ID)
        admin_ids.add(ADMIN_ID)

        c.execute("SELECT user_id, plan_name, expiry FROM subscriptions")
        user_subscriptions = {}
        for uid, pname, exp in c.fetchall():
            try:
                user_subscriptions[uid] = {"plan_name": pname, "expiry": datetime.fromisoformat(exp)}
            except Exception:
                pass

        c.execute("SELECT user_id, file_name, file_type FROM user_files")
        user_files = {}
        for uid, fn, ft in c.fetchall():
            user_files.setdefault(uid, []).append((fn, ft))

        conn.close()

        # lock state
        bot_locked = get_setting("bot_locked", "False") == "True"

        logger.info(f"✅ State loaded: {len(active_users)} users, {len(admin_ids)} admins, "
                    f"{len(user_subscriptions)} subs, "
                    f"{sum(len(v) for v in user_files.values())} files, locked={bot_locked}")
    except Exception as e:
        logger.error(f"❌ load_state_from_db: {e}")

load_state_from_db()

def rebuild_user_files_from_disk():
    try:
        for uid_str in os.listdir(UPLOAD_BOTS_DIR):
            if not uid_str.isdigit():
                continue
            uid = int(uid_str)
            folder = os.path.join(UPLOAD_BOTS_DIR, uid_str)
            if not os.path.isdir(folder):
                continue
            for fname in os.listdir(folder):
                if fname.endswith(('.py', '.js', '.sh')):
                    full = os.path.join(folder, fname)
                    if not any(fn == fname for fn, _ in user_files.get(uid, [])):
                        ft = detect_file_type(full) or 'py'
                        save_user_file(uid, fname, ft)
        logger.info("✅ Disk sync complete.")
    except Exception as e:
        logger.error(f"❌ rebuild_user_files_from_disk: {e}")

# --- Helper Functions ---

def check_rate_limit(user_id):
    now = time.time()
    if user_id not in user_command_count:
        user_command_count[user_id] = []
    user_command_count[user_id] = [t for t in user_command_count[user_id] if now - t < 60]
    if len(user_command_count[user_id]) >= 10:
        return False
    user_command_count[user_id].append(now)
    return True

def cleanup_rate_limit_data():
    while True:
        time.sleep(3600)
        try:
            now = time.time()
            for uid in list(user_command_count.keys()):
                user_command_count[uid] = [t for t in user_command_count[uid] if now - t < 60]
                if not user_command_count[uid]:
                    del user_command_count[uid]
            if len(file_index_map) > 5000:
                file_index_map.clear()
        except Exception as e:
            logger.error(f"cleanup_rate_limit_data: {e}")

threading.Thread(target=cleanup_rate_limit_data, daemon=True).start()

def get_user_folder(user_id):
    user_folder = os.path.join(UPLOAD_BOTS_DIR, str(user_id))
    os.makedirs(user_folder, exist_ok=True)
    return user_folder

def get_user_file_limit(user_id):
    if user_id == OWNER_ID:
        return OWNER_LIMIT
    if user_id in admin_ids:
        return ADMIN_LIMIT
    if user_id in user_subscriptions and user_subscriptions[user_id]["expiry"] > datetime.now():
        return SUBSCRIBED_USER_LIMIT
    return FREE_USER_LIMIT

def get_user_file_count(user_id):
    return len(user_files.get(user_id, []))

def is_bot_running(script_owner_id, file_name):
    script_key = f"{script_owner_id}_{file_name}"
    script_info = bot_scripts.get(script_key)
    if script_info and script_info.get("process"):
        try:
            proc = psutil.Process(script_info["process"].pid)
            is_running = proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
            if not is_running:
                bot_scripts.pop(script_key, None)
            return is_running
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            bot_scripts.pop(script_key, None)
            return False
        except Exception:
            bot_scripts.pop(script_key, None)
            return False
    return False

def kill_process_tree(process_info):
    try:
        process = process_info.get("process")
        if process and hasattr(process, "pid") and process.pid:
            try:
                parent = psutil.Process(process.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                return
            for child in parent.children(recursive=True):
                try:
                    child.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            try:
                parent.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except Exception as e:
        logger.error(f"❌ kill_process_tree: {e}")

def detect_file_type(file_path):
    try:
        with open(file_path, 'rb') as f:
            content = f.read(2048)
        if b'#!/usr/bin/env python' in content or b'#!/usr/bin/python' in content:
            return 'py'
        if b'import ' in content and (b'def ' in content or b'class ' in content):
            return 'py'
        if b'#!/usr/bin/env node' in content:
            return 'js'
        if b'require(' in content or b'module.exports' in content:
            return 'js'
        if b'console.log' in content and (b'function' in content or b'const ' in content):
            return 'js'
        if b'#!/bin/bash' in content or b'#!/bin/sh' in content:
            return 'sh'
        ext = os.path.splitext(file_path)[1].lower()
        if ext == '.py':
            return 'py'
        elif ext == '.js':
            return 'js'
        elif ext in ('.sh', '.bash'):
            return 'sh'
        elif ext == '.rb':
            return 'rb'
        elif ext == '.go':
            return 'go'
        if content.startswith(b'#!'):
            shebang = content.split(b'\n')[0].decode('utf-8', errors='ignore')
            if 'python' in shebang:
                return 'py'
            if 'node' in shebang:
                return 'js'
            if 'bash' in shebang or 'sh' in shebang:
                return 'sh'
        return None
    except Exception:
        return None

def auto_install_dependencies(file_path, file_name):
    ext = os.path.splitext(file_name)[1].lower()
    installed, failed = [], []
    if ext == '.py':
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            imports = re.findall(r'^(?:from|import)\s+([a-zA-Z_][a-zA-Z0-9_]*)', content, re.MULTILINE)
            imports += re.findall(r'import\s+([a-zA-Z_][a-zA-Z0-9_]*)', content)
            std = {'sys', 'os', 'time', 'datetime', 'json', 're', 'math', 'random',
                   'collections', 'itertools', 'functools', 'threading', 'subprocess',
                   'socket', 'ssl', 'hashlib', 'base64', 'zipfile', 'shutil', 'tempfile',
                   'typing', 'dataclasses', 'enum', 'abc', 'contextlib', 'io', 'asyncio'}
            for mod in set(imports):
                if mod in std:
                    continue
                pkg = TELEGRAM_MODULES.get(mod.lower(), mod)
                try:
                    subprocess.run([sys.executable, "-m", "pip", "install", pkg],
                                   capture_output=True, timeout=90)
                    installed.append(pkg)
                except Exception:
                    failed.append(pkg)
        except Exception as e:
            logger.error(f"Auto install error: {e}")
    elif ext == '.js':
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            imports = re.findall(r'require\([\'"]([^\'"]+)[\'"]\)', content)
            imports += re.findall(r'import\s+.*?from\s+[\'"]([^\'"]+)[\'"]', content)
            for mod in set(imports):
                if mod.startswith('.'):
                    continue
                try:
                    subprocess.run(['npm', 'install', mod], capture_output=True, timeout=90)
                    installed.append(mod)
                except Exception:
                    failed.append(mod)
        except Exception:
            pass
    return installed, failed

def parse_price_to_usdt(price_str):
    price_clean = str(price_str).upper().strip()
    numbers = re.findall(r"[-+]?\d*\.\d+|\d+", price_clean)
    if not numbers:
        return 0.0, price_str
    val = float(numbers[0])
    if "BDT" in price_clean or "TAKA" in price_clean or "TK" in price_clean:
        usdt_val = round(val / USDT_BDT_RATE, 2)
        return usdt_val, f"{price_str} (~{usdt_val} USDT)"
    return round(val, 2), f"{val} USDT"

def escape_md(text):
    for ch in ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '!']:
        text = str(text).replace(ch, f"\\{ch}")
    return text

def _safe_edit(chat_id, msg_id, text, **kwargs):
    try:
        bot.edit_message_text(text, chat_id, msg_id, **kwargs)
    except Exception:
        pass

def _safe_send(chat_id, text, **kwargs):
    try:
        bot.send_message(chat_id, text, **kwargs)
    except Exception as e:
        logger.warning(f"_safe_send fail: {e}")

# --- Script Runner ---
def run_script_smart(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply):
    script_key = f"{script_owner_id}_{file_name}"
    chat_id = message_obj_for_reply.chat.id

    try:
        file_type = detect_file_type(script_path)
        if not file_type:
            bot.reply_to(message_obj_for_reply,
                f"❌ **`{file_name}` ফাইলের টাইপ ডিটেক্ট করা যায়নি!**\n"
                f"শুধু `.py`, `.js`, `.sh` ফাইল সাপোর্ট করে।", parse_mode="Markdown")
            return

        # Already running?
        if is_bot_running(script_owner_id, file_name):
            bot.reply_to(message_obj_for_reply, f"⚠️ `{escape_md(file_name)}` already running!", parse_mode="Markdown")
            return

        log_file_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")

        try:
            status_msg = bot.reply_to(message_obj_for_reply,
                f"⏳ **ডিপেন্ডেন্সি চেক করা হচ্ছে...**\n📄 File: `{file_name}`", parse_mode="Markdown")
        except Exception:
            status_msg = None

        def _install_and_run():
            try:
                installed, failed = auto_install_dependencies(script_path, file_name)
                if installed and status_msg:
                    _safe_edit(chat_id, status_msg.message_id,
                        f"✅ **ইনস্টল:** `{', '.join(installed)}`\n🚀 **স্ক্রিপ্ট রান হচ্ছে...**",
                        parse_mode="Markdown")

                log_file = open(log_file_path, "w", encoding="utf-8", errors="ignore")

                if file_type == 'py':
                    cmd = [sys.executable, script_path]
                elif file_type == 'js':
                    cmd = ["node", script_path]
                elif file_type == 'sh':
                    cmd = ["bash", script_path]
                else:
                    if status_msg:
                        _safe_edit(chat_id, status_msg.message_id,
                            f"❌ **`{file_type}` সাপোর্ট করা হয় না!**", parse_mode="Markdown")
                    log_file.close()
                    return

                process = subprocess.Popen(
                    cmd, cwd=user_folder,
                    stdout=log_file, stderr=log_file,
                    stdin=subprocess.DEVNULL,
                )

                bot_scripts[script_key] = {
                    "process": process, "log_file": log_file, "file_name": file_name,
                    "script_owner_id": script_owner_id, "start_time": datetime.now(),
                    "user_folder": user_folder, "type": file_type, "script_key": script_key,
                    "file_path": script_path, "restart_count": 0,
                    "max_restarts": 3, "auto_restart": True
                }

                if status_msg:
                    _safe_edit(chat_id, status_msg.message_id,
                        f"🚀 **স্ক্রিপ্ট চালু হয়েছে!**\n📄 File: `{file_name}`\n"
                        f"🆔 PID: `{process.pid}`\n📊 Type: `{file_type.upper()}`",
                        parse_mode="Markdown")

                threading.Thread(target=monitor_script_with_restart,
                    args=(script_key, message_obj_for_reply), daemon=True).start()
                if status_msg:
                    threading.Thread(target=stream_live_logs,
                        args=(script_key, chat_id, status_msg.message_id + 1), daemon=True).start()

            except Exception as e:
                logger.error(f"_install_and_run: {e}")
                try:
                    bot.reply_to(message_obj_for_reply, f"❌ **Error:** {str(e)}", parse_mode="Markdown")
                except Exception:
                    pass

        threading.Thread(target=_install_and_run, daemon=True).start()

    except Exception as e:
        try:
            bot.reply_to(message_obj_for_reply, f"❌ **Error:** {str(e)}", parse_mode="Markdown")
        except Exception:
            pass
        logger.error(f"Script run error: {e}")

def monitor_script_with_restart(script_key, message_obj_for_reply):
    max_restarts = 3
    restart_count = 0
    chat_id = message_obj_for_reply.chat.id

    while restart_count < max_restarts:
        if script_key not in bot_scripts:
            break
        script_info = bot_scripts[script_key]
        process = script_info.get("process")

        if process and process.poll() is not None:
            exit_code = process.poll()

            # স্বাভাবিক exit হলে restart না
            if exit_code == 0:
                _safe_send(chat_id,
                    f"✅ `{escape_md(script_info['file_name'])}` স্বাভাবিকভাবে শেষ হয়েছে।",
                    parse_mode="Markdown")
                try:
                    script_info["log_file"].close()
                except Exception:
                    pass
                bot_scripts.pop(script_key, None)
                break

            restart_count += 1
            script_info["restart_count"] = restart_count

            if restart_count <= max_restarts:
                _safe_send(chat_id,
                    f"🔄 **ক্র্যাশ!** `{escape_md(script_info['file_name'])}`\n"
                    f"রিস্টার্ট {restart_count}/{max_restarts}",
                    parse_mode="Markdown")

                try:
                    try:
                        script_info["log_file"].close()
                    except Exception:
                        pass

                    log_file = open(os.path.join(script_info["user_folder"],
                        f"{os.path.splitext(script_info['file_name'])[0]}.log"),
                        "a", encoding="utf-8", errors="ignore")

                    ft = script_info.get("type", "py")
                    sp = script_info["file_path"]
                    if ft == 'py':
                        cmd = [sys.executable, sp]
                    elif ft == 'js':
                        cmd = ["node", sp]
                    else:
                        cmd = ["bash", sp]

                    new_process = subprocess.Popen(cmd, cwd=script_info["user_folder"],
                        stdout=log_file, stderr=log_file, stdin=subprocess.DEVNULL)

                    script_info["process"] = new_process
                    script_info["log_file"] = log_file
                    bot_scripts[script_key] = script_info

                    _safe_send(chat_id,
                        f"✅ **রিস্টার্ট!** `{escape_md(script_info['file_name'])}` PID `{new_process.pid}`",
                        parse_mode="Markdown")
                except Exception as e:
                    _safe_send(chat_id,
                        f"❌ **রিস্টার্ট ব্যর্থ!** {escape_md(str(e))}", parse_mode="Markdown")
                    break
        else:
            time.sleep(5)
            continue
        time.sleep(10)

    if script_key in bot_scripts:
        _safe_send(chat_id,
            f"⛔ **বন্ধ!** `{escape_md(bot_scripts[script_key]['file_name'])}`", parse_mode="Markdown")
        try:
            bot_scripts[script_key]["log_file"].close()
        except Exception:
            pass
        bot_scripts.pop(script_key, None)

def stream_live_logs(script_key, chat_id, msg_id):
    try:
        script_info = bot_scripts.get(script_key)
        if not script_info:
            return
        log_path = os.path.join(script_info["user_folder"],
            f"{os.path.splitext(script_info['file_name'])[0]}.log")

        # log file আসার জন্য অপেক্ষা (max 5 min)
        waited = 0
        while not os.path.exists(log_path) and script_key in bot_scripts:
            time.sleep(10)
            waited += 10
            if waited > 300:
                return

        last_pos = 0
        last_content = ""
        while script_key in bot_scripts:
            try:
                if os.path.exists(log_path):
                    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                        f.seek(last_pos)
                        new_content = f.read()
                        if new_content:
                            last_pos = f.tell()
                            preview = new_content[-1000:]
                            if preview != last_content:
                                last_content = preview
                                safe = html.escape(preview)
                                try:
                                    bot.edit_message_text(
                                        f"📊 <b>Live Logs</b>\n<pre>{safe}</pre>",
                                        chat_id, msg_id, parse_mode="HTML")
                                except telebot.apihelper.ApiTelegramException as e:
                                    if "429" in str(e):
                                        time.sleep(15)
                                except Exception:
                                    pass
            except Exception:
                pass
            time.sleep(10)
    except Exception:
        pass

def safe_extract_zip(zip_ref, target_dir):
    target_dir = os.path.abspath(target_dir)
    for member in zip_ref.namelist():
        member_path = os.path.abspath(os.path.join(target_dir, member))
        if not member_path.startswith(target_dir + os.sep):
            raise Exception(f"Unsafe path in zip: {member}")
    zip_ref.extractall(target_dir)

def handle_zip_upload(zip_path, user_id, user_folder, message):
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            safe_extract_zip(zip_ref, user_folder)
        main_files = []
        for root, dirs, files in os.walk(user_folder):
            for f in files:
                if f.endswith(('.py', '.js', '.sh')):
                    main_files.append(os.path.join(root, f))
        if not main_files:
            bot.reply_to(message, "❌ **জিপে `.py`, `.js`, বা `.sh` নেই!**", parse_mode="Markdown")
            return
        priority_files = ['main.py', 'bot.py', 'index.js', 'main.js', 'index.py', 'app.py']
        selected_file = None
        for f in main_files:
            if os.path.basename(f) in priority_files:
                selected_file = f
                break
        if not selected_file:
            selected_file = main_files[0]
        file_name = os.path.basename(selected_file)
        run_script_smart(selected_file, user_id, user_folder, file_name, message)
        file_type = detect_file_type(selected_file) or 'py'
        save_user_file(user_id, file_name, file_type)
    except zipfile.BadZipFile:
        bot.reply_to(message, "❌ **ইনভ্যালিড জিপ!**", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ **Zip error:** {str(e)}", parse_mode="Markdown")

# --- Database Operations ---
def save_user_file(user_id, file_name, file_type="py"):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO user_files (user_id, file_name, file_type) VALUES (?, ?, ?)",
                  (user_id, file_name, file_type))
        conn.commit()
        conn.close()
        user_files.setdefault(user_id, [])
        user_files[user_id] = [(fn, ft) for fn, ft in user_files[user_id] if fn != file_name]
        user_files[user_id].append((file_name, file_type))

def remove_user_file_db(user_id, file_name):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute("DELETE FROM user_files WHERE user_id = ? AND file_name = ?", (user_id, file_name))
        conn.commit()
        conn.close()
        if user_id in user_files:
            user_files[user_id] = [f for f in user_files[user_id] if f[0] != file_name]

def add_active_user(user_id):
    active_users.add(user_id)
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO active_users (user_id) VALUES (?)", (user_id,))
        conn.commit()
        conn.close()

def save_subscription(user_id, plan_name, expiry):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO subscriptions (user_id, plan_name, expiry) VALUES (?, ?, ?)",
                  (user_id, plan_name, expiry.isoformat()))
        conn.commit()
        conn.close()
        user_subscriptions[user_id] = {"plan_name": plan_name, "expiry": expiry}

def remove_subscription_db(user_id):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute("DELETE FROM subscriptions WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        user_subscriptions.pop(user_id, None)

def add_plan_db(name, file_limit, price, duration, buy_link):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute("INSERT INTO plans (name, file_limit, price, duration, buy_link) VALUES (?, ?, ?, ?, ?)",
                  (name, file_limit, price, duration, buy_link))
        conn.commit()
        conn.close()

def get_all_plans():
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT plan_id, name, file_limit, price, duration, buy_link FROM plans")
    plans = c.fetchall()
    conn.close()
    return plans

def get_plan_by_id(plan_id):
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT plan_id, name, file_limit, price, duration, buy_link FROM plans WHERE plan_id = ?", (plan_id,))
    plan = c.fetchone()
    conn.close()
    return plan

def delete_plan_db(plan_id):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute("DELETE FROM plans WHERE plan_id = ?", (plan_id,))
        conn.commit()
        conn.close()

def get_pending_payment(user_id, plan_id):
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT paid_amount FROM pending_payments WHERE user_id=? AND plan_id=?", (user_id, plan_id))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0.0

def update_pending_payment(user_id, plan_id, amount):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO pending_payments (user_id, plan_id, paid_amount) VALUES (?, ?, ?)",
                  (user_id, plan_id, amount))
        conn.commit()
        conn.close()

def clear_pending_payment(user_id, plan_id):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute("DELETE FROM pending_payments WHERE user_id=? AND plan_id=?", (user_id, plan_id))
        conn.commit()
        conn.close()

def is_txid_used(tx_id):
    tx_id_norm = str(tx_id).strip().lower()
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT tx_id FROM used_txids WHERE tx_id=?", (tx_id_norm,))
    row = c.fetchone()
    conn.close()
    return row is not None

def add_used_txid(tx_id):
    tx_id_norm = str(tx_id).strip().lower()
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO used_txids (tx_id) VALUES (?)", (tx_id_norm,))
        conn.commit()
        conn.close()

# --- Binance Pay ---
def check_binance_payment(pay_order_id):
    if not BINANCE_API_KEY or not BINANCE_SECRET_KEY:
        return False, 0.0, "Binance API Key configured নেই। Admin manually approve করবে।"
    endpoint = "https://api.binance.com/sapi/v1/pay/transactions"
    timestamp = int(time.time() * 1000)
    query_string = f"timestamp={timestamp}"
    signature = hmac.new(BINANCE_SECRET_KEY.encode(), query_string.encode(), hashlib.sha256).hexdigest()
    url = f"{endpoint}?{query_string}&signature={signature}"
    headers = {"X-MBX-APIKEY": BINANCE_API_KEY}
    try:
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code == 200:
            data = res.json()
            transactions = data.get("data", []) if isinstance(data, dict) else data
            for item in transactions:
                order_id_str = str(item.get("orderId", "") or item.get("transactionId", ""))
                if order_id_str.strip() == str(pay_order_id).strip():
                    return True, float(item.get("amount", 0.0)), f"{item.get('amount')} {item.get('currency', 'USDT')}"
            return False, 0.0, "Order ID পাওয়া যায়নি।"
        return False, 0.0, f"Binance Error {res.status_code}"
    except Exception as e:
        return False, 0.0, f"Error: {str(e)}"

# --- Core Logic ---
def _logic_send_welcome(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    user_name = message.from_user.first_name
    if bot_locked and user_id not in admin_ids:
        bot.send_message(chat_id, "⚠️ **Bot is temporarily locked.**")
        return
    add_active_user(user_id)
    if user_id == OWNER_ID:
        user_status = "👑 **Owner**"
    elif user_id in admin_ids:
        user_status = "🛡️ **Admin**"
    elif user_id in user_subscriptions and user_subscriptions[user_id]["expiry"] > datetime.now():
        sub = user_subscriptions[user_id]
        days_left = (sub["expiry"] - datetime.now()).days
        user_status = f"💎 **{sub.get('plan_name', 'Premium')} Active** ({days_left} Days left)"
    else:
        user_status = "🆓 **No Active Plan**"
    markup = create_professional_main_menu(user_id)
    welcome_msg = (
        f"✨ **Welcome, {escape_md(user_name)}!** ✨\n\n"
        f"🆔 **ID:** `{user_id}`\n"
        f"🔰 **Status:** {user_status}\n"
        f"📁 **Files:** `{get_user_file_count(user_id)}` / `{get_user_file_limit(user_id)}`\n"
        f"🔄 **Running:** `{sum(1 for k in bot_scripts if k.startswith(f'{user_id}_'))}`\n\n"
        f"💡 **Host Python (.py), Node.js (.js), Shell (.sh) bots 24/7.**\n"
        f"👇 *Select an option:*"
    )
    bot.send_message(chat_id, welcome_msg, reply_markup=markup, parse_mode="Markdown")

def _logic_view_plans(message_or_call):
    if hasattr(message_or_call, 'message') and hasattr(message_or_call.message, 'chat'):
        chat_id = message_or_call.message.chat.id
    elif hasattr(message_or_call, 'chat'):
        chat_id = message_or_call.chat.id
    else:
        return
    plans = get_all_plans()
    if not plans:
        _safe_send(chat_id, "ℹ️ **No plans available.**", parse_mode="Markdown")
        return
    _safe_send(chat_id, "💳 **Available Hosting Plans:**", parse_mode="Markdown")
    for plan in plans:
        try:
            plan_id, name, limit, price, duration, _ = plan
            usdt_price, formatted_price = parse_price_to_usdt(price)
            card_text = (
                f"📦 **Plan:** `{escape_md(name)}`\n━━━━━━━━━━━━━━━━━━━\n"
                f"📁 **Limit:** `{limit} Files`\n⏱️ **Duration:** `{duration} Days`\n"
                f"💰 **Price:** `{escape_md(formatted_price)}`\n👉 **Pay:** `{usdt_price} USDT`\n"
                f"━━━━━━━━━━━━━━━━━━━"
            )
            markup = create_plan_card_buttons(plan_id, name, usdt_price)
            bot.send_message(chat_id, card_text, reply_markup=markup, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Plan send failed: {e}")
            break

def _logic_upload_file(message):
    user_id = message.from_user.id
    if bot_locked and user_id not in admin_ids:
        bot.reply_to(message, "⚠️ **Bot locked.**")
        return
    has_active_plan = False
    plan_name = "None"
    if user_id in admin_ids or user_id == OWNER_ID:
        has_active_plan = True
        plan_name = "Admin / Owner Unlimited"
    elif user_id in user_subscriptions and user_subscriptions[user_id]["expiry"] > datetime.now():
        has_active_plan = True
        plan_name = user_subscriptions[user_id].get("plan_name", "Premium Plan")
    if not has_active_plan:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("💳 View Plans & Buy", callback_data="view_plans_cb"))
        bot.reply_to(message, "❌ **No active plan!**\n\nSubscribe first.",
                     reply_markup=markup, parse_mode="Markdown")
        return
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(f"✅ Continue with {plan_name}", callback_data="confirm_plan_upload"))
    bot.reply_to(message, f"🔰 **Active Plan:** `{escape_md(plan_name)}`\n\nSend `.py`, `.js`, `.sh`, or `.zip` file.",
                 reply_markup=markup, parse_mode="Markdown")

def _logic_check_files(message):
    user_id = message.from_user.id
    user_files_list = user_files.get(user_id, [])
    if not user_files_list:
        bot.reply_to(message, "📂 **Your Files:**\n*(No files uploaded yet)*", parse_mode="Markdown")
        return
    markup = create_colorful_file_list(user_id, user_files_list)
    bot.reply_to(message, "📁 **Manage Your Files:**", reply_markup=markup, parse_mode="Markdown")

def _send_stats(chat_id):
    try:
        cpu_percent = psutil.cpu_percent()
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
    except Exception:
        cpu_percent, memory, disk = 0, None, None
    stats_msg = f"""
📊 **Bot Statistics**

👥 Users: `{len(active_users)}`
🛡️ Admins: `{len(admin_ids)}`
📁 Files: `{sum(len(files) for files in user_files.values())}`
🔄 Running: `{len(bot_scripts)}`
💻 CPU: `{cpu_percent}%`
"""
    if memory:
        stats_msg += f"🧠 RAM: `{memory.percent}%` ({memory.used // (1024**3)}GB / {memory.total // (1024**3)}GB)\n"
    if disk:
        stats_msg += f"💾 Disk: `{disk.percent}%`\n"
    stats_msg += f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    _safe_send(chat_id, stats_msg, parse_mode="Markdown")

# --- Document Upload ---
@bot.message_handler(content_types=["document"])
def handle_file_upload_doc(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    doc = message.document
    if not check_rate_limit(user_id):
        bot.reply_to(message, "⏳ **অনেক বেশি রিকোয়েস্ট!**")
        return
    if bot_locked and user_id not in admin_ids:
        bot.reply_to(message, "⚠️ **Bot locked.**")
        return
    if user_id not in admin_ids and user_id != OWNER_ID:
        if user_id not in user_subscriptions or user_subscriptions[user_id]["expiry"] <= datetime.now():
            bot.reply_to(message, "❌ **No active plan!**", parse_mode="Markdown")
            return
    file_name = doc.file_name
    file_ext = os.path.splitext(file_name)[1].lower()
    if file_ext not in [".py", ".js", ".sh", ".zip"]:
        bot.reply_to(message, "⚠️ **Supported:** `.py`, `.js`, `.sh`, `.zip`", parse_mode="Markdown")
        return

    current_limit = get_user_file_limit(user_id)
    current_count = get_user_file_count(user_id)
    if current_count >= current_limit:
        bot.reply_to(message, f"❌ **File limit reached!** ({current_count}/{current_limit})", parse_mode="Markdown")
        return

    try:
        status_msg = bot.reply_to(message, f"⏳ **Downloading `{escape_md(file_name)}`...**", parse_mode="Markdown")
        file_info = bot.get_file(doc.file_id)
        file_content = bot.download_file(file_info.file_path)
        user_folder = get_user_folder(user_id)
        file_path = os.path.join(user_folder, file_name)
        with open(file_path, "wb") as f:
            f.write(file_content)
        _safe_edit(chat_id, status_msg.message_id, f"✅ **Uploaded `{escape_md(file_name)}`!**", parse_mode="Markdown")
        if file_ext == ".zip":
            handle_zip_upload(file_path, user_id, user_folder, message)
        else:
            save_user_file(user_id, file_name, file_ext[1:])
            run_script_smart(file_path, user_id, user_folder, file_name, message)
    except Exception as e:
        bot.reply_to(message, f"❌ **Error:** {str(e)}")

# --- Commands ---
@bot.message_handler(commands=["start"])
def start_cmd(message):
    user_id = message.from_user.id
    if not check_rate_limit(user_id):
        bot.reply_to(message, "⏳ **অনেক বেশি রিকোয়েস্ট!**")
        return
    now = time.time()
    if user_id in last_start_time and now - last_start_time[user_id] < 2:
        return
    last_start_time[user_id] = now
    _logic_send_welcome(message)

@bot.message_handler(commands=["help"])
def help_cmd(message):
    if not check_rate_limit(message.from_user.id):
        bot.reply_to(message, "⏳ **অনেক বেশি রিকোয়েস্ট!**")
        return
    help_text = f"""
🤖 **Shiyam Bot Host - Guide**

📌 **Commands:**
/start /help /menu /files /plan /stats /stopall

📤 **Upload:**
1️⃣ Subscribe (View Plans)
2️⃣ Upload File
3️⃣ Send .py / .js / .sh / .zip

⚙️ **Features:**
• ✅ Auto dependency install
• ✅ Auto-restart on crash (3x)
• ✅ Live log streaming
• ✅ Smart file detection

💰 **Payment:**
Binance Pay ID: `{escape_md(BINANCE_PAY_ID)}`

❓ **Contact:** {escape_md(YOUR_USERNAME)}
📢 **Channel:** {escape_md(UPDATE_CHANNEL)}
"""
    bot.reply_to(message, help_text, parse_mode="Markdown")

@bot.message_handler(commands=["menu"])
def menu_cmd(message):
    if not check_rate_limit(message.from_user.id):
        return
    markup = create_professional_main_menu(message.from_user.id)
    bot.send_message(message.chat.id, "📋 **Main Menu:**", reply_markup=markup)

@bot.message_handler(commands=["files"])
def files_cmd(message):
    if not check_rate_limit(message.from_user.id):
        return
    _logic_check_files(message)

@bot.message_handler(commands=["plan"])
def plan_cmd(message):
    if not check_rate_limit(message.from_user.id):
        return
    _logic_view_plans(message)

@bot.message_handler(commands=["stats"])
def stats_cmd(message):
    if not check_rate_limit(message.from_user.id):
        return
    _send_stats(message.chat.id)

@bot.message_handler(commands=["stopall"])
def stopall_cmd(message):
    user_id = message.from_user.id
    if not check_rate_limit(user_id):
        return
    stopped = 0
    for key in list(bot_scripts.keys()):
        if key.startswith(f"{user_id}_") or user_id in admin_ids:
            kill_process_tree(bot_scripts[key])
            try:
                bot_scripts[key]["log_file"].close()
            except Exception:
                pass
            bot_scripts.pop(key, None)
            stopped += 1
    bot.reply_to(message, f"🛑 **Stopped {stopped} scripts!**", parse_mode="Markdown")

# ============================================
# 🔥 CALLBACK HANDLER
# ============================================
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    global bot_locked

    user_id = call.from_user.id
    data = call.data

    if not check_rate_limit(user_id):
        bot.answer_callback_query(call.id, "⏳ অনেক রিকোয়েস্ট!", show_alert=True)
        return

    if bot_locked and user_id not in admin_ids:
        if data not in ("help", "view_plans", "view_plans_cb", "back_to_menu", "bot_stats", "speed_ping"):
            bot.answer_callback_query(call.id, "⚠️ Bot is locked by Admin!", show_alert=True)
            return

    def parse_file_key(k):
        if k in file_index_map:
            return file_index_map[k]
        parts = k.split("_", 2)
        if len(parts) == 3 and parts[0] == "i":
            try:
                owner_id = int(parts[1])
                idx = int(parts[2])
                files = sorted(user_files.get(owner_id, []))
                if 0 <= idx < len(files):
                    return owner_id, files[idx][0]
            except (ValueError, IndexError):
                pass
        parts = k.split("_", 1)
        if len(parts) == 2 and parts[0].isdigit():
            return int(parts[0]), parts[1]
        return None, None

    if data == "upload_file":
        bot.answer_callback_query(call.id)
        _logic_upload_file(call.message)
    elif data == "manage_files":
        bot.answer_callback_query(call.id)
        _logic_check_files(call.message)
    elif data == "view_plans":
        bot.answer_callback_query(call.id)
        _logic_view_plans(call)
    elif data == "speed_ping":
        bot.answer_callback_query(call.id)
        t0 = time.time()
        msg = bot.send_message(call.message.chat.id, "⚡ Measuring...")
        ping = round((time.time() - t0) * 1000, 1)
        _safe_edit(call.message.chat.id, msg.message_id,
            f"⚡ **Latency:** `{ping}ms`\n📊 **Status:** Active", parse_mode="Markdown")
    elif data == "bot_stats":
        bot.answer_callback_query(call.id)
        _send_stats(call.message.chat.id)
    elif data == "terminal":
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "💻 **Terminal Ready**\nUse `/stopall` to stop all scripts.", parse_mode="Markdown")
    elif data == "help":
        bot.answer_callback_query(call.id)
        help_cmd(call.message)
    elif data == "admin_panel":
        if user_id not in admin_ids:
            bot.answer_callback_query(call.id, "❌ Access denied!", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        markup = create_professional_admin_panel()
        bot.send_message(call.message.chat.id, "🛡️ **Admin Panel:**", reply_markup=markup)
    elif data.startswith("file_"):
        key = data[5:]
        owner_id, fname = parse_file_key(key)
        if owner_id is None:
            bot.answer_callback_query(call.id, "❌ File not found!", show_alert=True)
            return
        if user_id != owner_id and user_id not in admin_ids:
            bot.answer_callback_query(call.id, "❌ Access denied!", show_alert=True)
            return
        is_running = is_bot_running(owner_id, fname)
        markup = create_file_management_buttons(owner_id, fname, is_running)
        _safe_edit(call.message.chat.id, call.message.message_id,
            f"📄 **File:** `{escape_md(fname)}`\n🚦 **Status:** `{'🟢 Running' if is_running else '🔴 Stopped'}`",
            reply_markup=markup, parse_mode="Markdown")
    elif data.startswith("start_"):
        key = data[6:]
        owner_id, fname = parse_file_key(key)
        if owner_id is None:
            bot.answer_callback_query(call.id, "❌ File not found!", show_alert=True)
            return
        if user_id != owner_id and user_id not in admin_ids:
            bot.answer_callback_query(call.id, "❌ Access denied!", show_alert=True)
            return
        user_folder = get_user_folder(owner_id)
        file_path = os.path.join(user_folder, fname)
        if os.path.exists(file_path):
            run_script_smart(file_path, owner_id, user_folder, fname, call.message)
            bot.answer_callback_query(call.id, "✅ Script started!")
        else:
            bot.answer_callback_query(call.id, "❌ File not found!", show_alert=True)
    elif data.startswith("stop_"):
        key = data[5:]
        owner_id, fname = parse_file_key(key)
        if owner_id is None:
            bot.answer_callback_query(call.id, "❌ File not found!", show_alert=True)
            return
        if user_id != owner_id and user_id not in admin_ids:
            bot.answer_callback_query(call.id, "❌ Access denied!", show_alert=True)
            return
        skey = f"{owner_id}_{fname}"
        if skey in bot_scripts:
            kill_process_tree(bot_scripts[skey])
            try:
                bot_scripts[skey]["log_file"].close()
            except Exception:
                pass
            bot_scripts.pop(skey, None)
            bot.answer_callback_query(call.id, "🛑 Stopped!")
            bot.send_message(call.message.chat.id, f"🛑 **Stopped `{escape_md(fname)}`**", parse_mode="Markdown")
        else:
            bot.answer_callback_query(call.id, "❌ Not running!", show_alert=True)
    elif data.startswith("del_"):
        key = data[4:]
        owner_id, fname = parse_file_key(key)
        if owner_id is None:
            bot.answer_callback_query(call.id, "❌ File not found!", show_alert=True)
            return
        if user_id != owner_id and user_id not in admin_ids:
            bot.answer_callback_query(call.id, "❌ Access denied!", show_alert=True)
            return
        skey = f"{owner_id}_{fname}"
        if skey in bot_scripts:
            kill_process_tree(bot_scripts[skey])
            try:
                bot_scripts[skey]["log_file"].close()
            except Exception:
                pass
            bot_scripts.pop(skey, None)
        remove_user_file_db(owner_id, fname)
        user_folder = get_user_folder(owner_id)
        file_path = os.path.join(user_folder, fname)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
        log_path = os.path.join(user_folder, f"{os.path.splitext(fname)[0]}.log")
        if os.path.exists(log_path):
            try:
                os.remove(log_path)
            except Exception:
                pass
        bot.answer_callback_query(call.id, "🗑️ Deleted!")
        bot.send_message(call.message.chat.id, f"🗑️ **Deleted `{escape_md(fname)}`**", parse_mode="Markdown")
    elif data.startswith("edit_"):
        key = data[5:]
        owner_id, fname = parse_file_key(key)
        if owner_id is None:
            bot.answer_callback_query(call.id, "❌ File not found!", show_alert=True)
            return
        if user_id != owner_id and user_id not in admin_ids:
            bot.answer_callback_query(call.id, "❌ Access denied!", show_alert=True)
            return
        user_folder = get_user_folder(owner_id)
        file_path = os.path.join(user_folder, fname)
        if not os.path.exists(file_path):
            bot.answer_callback_query(call.id, "❌ File not found!", show_alert=True)
            return
        skey = f"{owner_id}_{fname}"
        if skey in bot_scripts:
            kill_process_tree(bot_scripts[skey])
            try:
                bot_scripts[skey]["log_file"].close()
            except Exception:
                pass
            bot_scripts.pop(skey, None)
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            current_code = f.read()[:1000]
        bot.answer_callback_query(call.id)
        safe_code = html.escape(current_code)
        msg = bot.send_message(call.message.chat.id,
            f"✏️ <b>Editing</b> <code>{html.escape(fname)}</code>\n\nCurrent (first 1000):\n<pre>{safe_code}</pre>\n\n📝 Send new code:",
            parse_mode="HTML")
        bot.register_next_step_handler(msg, lambda m: save_edited_file(m, owner_id, fname))
    elif data.startswith("logs_"):
        key = data[5:]
        owner_id, fname = parse_file_key(key)
        if owner_id is None:
            bot.answer_callback_query(call.id, "❌ File not found!", show_alert=True)
            return
        if user_id != owner_id and user_id not in admin_ids:
            bot.answer_callback_query(call.id, "❌ Access denied!", show_alert=True)
            return
        user_folder = get_user_folder(owner_id)
        log_path = os.path.join(user_folder, f"{os.path.splitext(fname)[0]}.log")
        if os.path.exists(log_path):
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                log_content = f.read()[-3000:]
            safe = html.escape(log_content) if log_content else "No logs yet."
            bot.send_message(call.message.chat.id,
                f"📊 <b>Logs for</b> <code>{html.escape(fname)}</code>\n<pre>{safe}</pre>",
                parse_mode="HTML")
        else:
            bot.answer_callback_query(call.id, "❌ No log file!", show_alert=True)
    elif data == "view_plans_cb":
        bot.answer_callback_query(call.id)
        _logic_view_plans(call)
    elif data == "confirm_plan_upload":
        bot.answer_callback_query(call.id, "✅ Verified!")
        bot.send_message(call.message.chat.id, "🚀 **Send your file!**", parse_mode="Markdown")
    elif data.startswith("plan_details_"):
        plan_id = int(data.split("_")[2])
        plan = get_plan_by_id(plan_id)
        if plan:
            _, name, limit, price, duration, buy_link = plan
            usdt_price, formatted_price = parse_price_to_usdt(price)
            bot.send_message(call.message.chat.id,
                f"📋 **Plan:** `{escape_md(name)}`\n📁 Limit: `{limit}`\n"
                f"⏱️ Duration: `{duration} Days`\n💰 Price: `{escape_md(formatted_price)}`\n"
                f"💳 USDT: `{usdt_price}`\n🔗 Link: {buy_link}", parse_mode="Markdown")
    elif data.startswith("buy_binance_"):
        plan_id = int(data.split("_")[2])
        plan = get_plan_by_id(plan_id)
        if not plan:
            bot.answer_callback_query(call.id, "❌ Plan not found!")
            return
        bot.answer_callback_query(call.id)
        _, name, limit, price, duration, _ = plan
        usdt_price, formatted_price = parse_price_to_usdt(price)
        already_paid = get_pending_payment(user_id, plan_id)
        due_amount = max(0.0, round(usdt_price - already_paid, 2))
        pay_msg = (f"💛 **Binance Pay**\n\n📌 **Plan:** `{escape_md(name)}`\n"
                   f"💰 **Total:** `{usdt_price} USDT` ({escape_md(formatted_price)})\n")
        if already_paid > 0:
            pay_msg += f"✅ Paid: `{already_paid} USDT`\n⚠️ Due: `{due_amount} USDT`\n\n"
        else:
            pay_msg += f"⏱️ Duration: `{duration} Days`\n\n"
        pay_msg += (f"📤 **How to pay:**\n"
                    f"1️⃣ Binance App → Pay → Send\n"
                    f"2️⃣ Send `{due_amount} USDT` to:\n"
                    f"🔸 **Pay ID:** `{escape_md(BINANCE_PAY_ID)}`\n\n"
                    f"3️⃣ Submit Order ID below:")
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔍 Submit TxID", callback_data=f"submit_txid_{plan_id}"))
        bot.send_message(call.message.chat.id, pay_msg, reply_markup=markup, parse_mode="Markdown")
    elif data.startswith("submit_txid_"):
        plan_id = int(data.split("_")[2])
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id,
            "📩 **Enter your Binance Order/Tx ID:**", parse_mode="Markdown")
        bot.register_next_step_handler(msg, lambda m: process_binance_txid(m, plan_id))
    elif data == "add_plan_init" and user_id in admin_ids:
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id,
            "📝 `Name | FileLimit | Price | DurationDays | BuyLink`\n\n"
            "Example:\n`Premium | 15 | 5 USDT | 30 | https://t.me/shiyam744`", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_add_plan)
    elif data == "manage_plans" and user_id in admin_ids:
        bot.answer_callback_query(call.id)
        plans = get_all_plans()
        if not plans:
            bot.send_message(call.message.chat.id, "📭 No plans.")
            return
        markup = types.InlineKeyboardMarkup()
        for p in plans:
            markup.add(types.InlineKeyboardButton(f"🗑️ Delete {p[1]}", callback_data=f"del_plan_{p[0]}"))
        bot.send_message(call.message.chat.id, "🗑️ **Delete a Plan:**", reply_markup=markup)
    elif data.startswith("del_plan_") and user_id in admin_ids:
        pid = int(data.split("_")[2])
        delete_plan_db(pid)
        bot.answer_callback_query(call.id, "✅ Plan deleted!")
    elif data == "add_subscription" and user_id in admin_ids:
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id,
            "💎 `UserID PlanName Days`\nExample: `123456789 Premium 30`", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_add_subscription)
    elif data == "remove_subscription" and user_id in admin_ids:
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id, "❌ Enter User ID:", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_remove_subscription)
    elif data == "toggle_lock" and user_id in admin_ids:
        bot_locked = not bot_locked
        set_setting("bot_locked", bot_locked)
        bot.answer_callback_query(call.id, f"Bot Locked: {bot_locked}")
        bot.send_message(call.message.chat.id,
            f"🔐 **Bot `{'Locked' if bot_locked else 'Unlocked'}`**", parse_mode="Markdown")
    elif data == "add_admin" and user_id == OWNER_ID:
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id, "👑 Enter User ID to add as Admin:", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_add_admin)
    elif data == "remove_admin" and user_id == OWNER_ID:
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id, "👑 Enter User ID to remove:", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_remove_admin)
    elif data == "broadcast" and user_id in admin_ids:
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id, "📣 Enter broadcast message:", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_broadcast)
    elif data == "back_to_files":
        bot.answer_callback_query(call.id)
        _logic_check_files(call.message)
    elif data == "back_to_menu":
        bot.answer_callback_query(call.id)
        markup = create_professional_main_menu(user_id)
        _safe_edit(call.message.chat.id, call.message.message_id,
            "📋 **Main Menu:**", reply_markup=markup)

# --- Step Handlers ---
def save_edited_file(message, owner_id, fname):
    if not message.text:
        bot.reply_to(message, "❌ Empty!")
        return
    new_code = message.text
    user_folder = get_user_folder(owner_id)
    file_path = os.path.join(user_folder, fname)
    backup_path = file_path + ".backup"
    if os.path.exists(file_path):
        try:
            shutil.copy2(file_path, backup_path)
        except Exception:
            pass
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(new_code)
    bot.reply_to(message, f"✅ `{escape_md(fname)}` updated!\n💾 Backup saved.", parse_mode="Markdown")

def process_binance_txid(message, plan_id):
    pay_order_id = message.text.strip() if message.text else ""
    user_id = message.from_user.id
    plan = get_plan_by_id(plan_id)
    if not plan:
        bot.reply_to(message, "❌ Plan not found!")
        return
    pid, name, limit, price, duration, _ = plan
    usdt_price, formatted_price = parse_price_to_usdt(price)
    if is_txid_used(pay_order_id):
        bot.reply_to(message, "❌ **This TxID was already used!**")
        return
    wait_msg = bot.reply_to(message, "⏳ **Verifying payment...**")
    is_valid, paid_amount, details = check_binance_payment(pay_order_id)
    if is_valid:
        add_used_txid(pay_order_id)
        already_paid = get_pending_payment(user_id, plan_id)
        total_paid = round(already_paid + paid_amount, 2)
        if total_paid < usdt_price:
            remaining = round(usdt_price - total_paid, 2)
            update_pending_payment(user_id, plan_id, total_paid)
            _safe_edit(message.chat.id, wait_msg.message_id,
                f"⚠️ **Partial Payment!**\n\nPlan: `{escape_md(name)}`\n"
                f"Total: `{usdt_price} USDT`\nPaid: `{total_paid}`\nDue: `{remaining}`\n\n"
                f"Send remaining `{remaining} USDT` to `{escape_md(BINANCE_PAY_ID)}`",
                parse_mode="Markdown")
            return
        clear_pending_payment(user_id, plan_id)
        expiry = datetime.now() + timedelta(days=duration)
        save_subscription(user_id, name, expiry)
        _safe_edit(message.chat.id, wait_msg.message_id,
            f"🎉 **Payment Verified!**\n\n💎 Plan: `{escape_md(name)}`\n"
            f"💰 Paid: `{total_paid} USDT`\n📅 Expiry: `{expiry.strftime('%Y-%m-%d')}`",
            parse_mode="Markdown")
        try:
            bot.send_message(OWNER_ID,
                f"🔔 **New Sub!**\n👤 `{user_id}`\n💎 `{escape_md(name)}`\n💰 `{total_paid} USDT`",
                parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Owner notification failed: {e}")
    else:
        safe_details = html.escape(details)
        _safe_edit(message.chat.id, wait_msg.message_id,
            f"❌ <b>Verification Failed!</b>\n\n⚠️ <code>{safe_details}</code>\n\n"
            f"Admin manually approve করবেন অথবা আবার চেষ্টা করুন।",
            parse_mode="HTML")

def process_add_plan(message):
    try:
        parts = [p.strip() for p in message.text.split("|")]
        if len(parts) < 5:
            raise Exception("5টি field দরকার")
        name, limit, price, duration, buy_link = parts[0], int(parts[1]), parts[2], int(parts[3]), parts[4]
        add_plan_db(name, limit, price, duration, buy_link)
        bot.reply_to(message, f"✅ Plan `{escape_md(name)}` added!", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Invalid: {e}")

def process_add_subscription(message):
    try:
        parts = message.text.split()
        uid, pname, days = int(parts[0]), parts[1], int(parts[2])
        exp = datetime.now() + timedelta(days=days)
        save_subscription(uid, pname, exp)
        bot.reply_to(message, f"✅ Sub added for `{uid}`", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ {e}")

def process_remove_subscription(message):
    try:
        uid = int(message.text.strip())
        remove_subscription_db(uid)
        bot.reply_to(message, f"✅ Removed for `{uid}`", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ {e}")

def process_add_admin(message):
    try:
        new_admin = int(message.text.strip())
        admin_ids.add(new_admin)
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (new_admin,))
            conn.commit()
            conn.close()
        bot.reply_to(message, f"✅ `{new_admin}` is Admin!", parse_mode="Markdown")
    except Exception:
        bot.reply_to(message, "❌ Invalid ID")

def process_remove_admin(message):
    try:
        admin_id = int(message.text.strip())
        if admin_id == OWNER_ID:
            bot.reply_to(message, "❌ Cannot remove Owner!")
            return
        admin_ids.discard(admin_id)
        with DB_LOCK:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute("DELETE FROM admins WHERE user_id = ?", (admin_id,))
            conn.commit()
            conn.close()
        bot.reply_to(message, f"✅ `{admin_id}` removed!", parse_mode="Markdown")
    except Exception:
        bot.reply_to(message, "❌ Invalid ID")

def process_broadcast(message):
    broadcast_msg = html.escape(message.text or "")
    count = 0
    for uid in list(active_users):
        try:
            bot.send_message(uid, f"📣 <b>Broadcast:</b>\n\n{broadcast_msg}", parse_mode="HTML")
            count += 1
            time.sleep(0.15)
        except Exception:
            pass
    bot.reply_to(message, f"✅ Sent to {count} users!")

# --- Reply Button Handlers ---
BUTTON_MAPPING = {
    "✨ 𝐔𝐩𝐝𝐚𝐭𝐞𝐬 𝐂𝐡𝐚𝐧𝐧𝐞𝐥 ✨": lambda m: bot.reply_to(m, f"📢 **Join:** {escape_md(UPDATE_CHANNEL)}"),
    "🚀 𝐔𝐩𝐥𝐨𝐚𝐝 𝐅𝐢𝐥𝐞": _logic_upload_file,
    "📁 𝐌𝐚𝐧𝐚𝐠𝐞 𝐅𝐢𝐥𝐞𝐬": _logic_check_files,
    "💳 𝐕𝐢𝐞𝐰 𝐏𝐥𝐚𝐧𝐬": _logic_view_plans,
    "⚡ 𝐒𝐩𝐞𝐞𝐝 & 𝐏𝐢𝐧𝐠": lambda m: bot.reply_to(m, "⚡ **Latency:** measuring... use inline menu for accurate ping."),
    "📊 𝐁𝐨𝐭 𝐒𝐭𝐚𝐭𝐬": lambda m: _send_stats(m.chat.id),
    "💻 𝐓𝐞𝐫𝐦𝐢𝐧𝐚𝐥 𝐂𝐦𝐝": lambda m: bot.reply_to(m, "💻 **Terminal Ready**\nUse `/stopall`.", parse_mode="Markdown"),
    "👑 𝐂𝐨𝐧𝐭𝐚𝐜𝐭 𝐎𝐰𝐧𝐞𝐫": lambda m: bot.reply_to(m, f"👑 {escape_md(YOUR_USERNAME)}"),
    "🛡️ 𝐀𝐝𝐦𝐢𝐧 𝐏𝐚𝐧𝐞𝐥": lambda m: bot.reply_to(m, "🛡️ **Admin Panel:**", reply_markup=create_professional_admin_panel()),
    "❓ 𝐇𝐞𝐥𝐩": lambda m: help_cmd(m)
}

@bot.message_handler(func=lambda m: m.text in BUTTON_MAPPING)
def handle_buttons(message):
    if not check_rate_limit(message.from_user.id):
        bot.reply_to(message, "⏳ **অনেক বেশি রিকোয়েস্ট!**")
        return
    try:
        BUTTON_MAPPING[message.text](message)
    except Exception as e:
        logger.error(f"Button handler error: {e}")

# --- Cleanup ---
def cleanup():
    for key in list(bot_scripts.keys()):
        try:
            kill_process_tree(bot_scripts[key])
            try:
                bot_scripts[key]["log_file"].close()
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"cleanup skip {key}: {e}")
    logger.info("🧹 Cleanup completed.")

atexit.register(cleanup)

# --- Main ---
if __name__ == "__main__":
    logger.info("🚀 Starting Shiyam Bot Host (final fixed version)...")
    keep_alive()
    threading.Thread(target=rebuild_user_files_from_disk, daemon=True).start()
    while True:
        try:
            bot.infinity_polling(
                timeout=60,
                long_polling_timeout=30,
                none_stop=True,
                allowed_updates=None
            )
        except KeyboardInterrupt:
            logger.info("⏹️ KeyboardInterrupt")
            break
        except Exception as e:
            logger.error(f"❌ Polling crash: {e}")
            time.sleep(5)