import telebot
from telebot import types
import requests
import json
import time

# ==========================================
# CONFIGURATION
# ==========================================
BOT_TOKEN = '8227430826:AAFrqELQwziSEHhMAE9-yjyw77HHdFUkSsg'  # <--- Yahan apna Bot Token daalein
BACKUP_EXPIRY_TIME = 72 * 60 * 60  # 72 Ghante (3 Din) seconds mein

bot = telebot.TeleBot(BOT_TOKEN)

# ==========================================
# GLOBAL VARIABLES (Memory)
# ==========================================
user_db_urls = {}
user_device_nodes = {}
deleted_devices_backup = {} # Format: {chat_id: {device_id: {"data": [...], "timestamp": time}}}

# ==========================================
# KEYBOARD SETUP
# ==========================================
def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn_connect = types.KeyboardButton('🔗 Connect Firebase')
    btn_fetch = types.KeyboardButton('📊 Fetch Data')
    btn_set_node = types.KeyboardButton('⚙️ Set Device Node')
    btn_delete = types.KeyboardButton('🗑️ Delete Device')
    btn_recover = types.KeyboardButton('♻️ Recover Device')
    markup.add(btn_connect, btn_fetch, btn_set_node, btn_delete, btn_recover)
    return markup

# ==========================================
# START COMMAND
# ==========================================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_name = message.from_user.first_name
    welcome_text = (
        f"⚡ **SYSTEM INITIALIZED** ⚡\n\n"
        f"Welcome, **{user_name}**. I am your Smart Database Manager. 🤖\n\n"
        f"🔹 **Features:**\n"
        f"1. Connect your Firebase Database.\n"
        f"2. Fetch any node data instantly.\n"
        f"3. Delete a device safely.\n"
        f"4. Recover a deleted device (Backup valid for 3 days only).\n\n"
        f"*Status: Awaiting Connection... 🔴*"
    )
    bot.reply_to(message, welcome_text, parse_mode='Markdown', reply_markup=get_main_keyboard())

# ==========================================
# CONNECT FIREBASE LOGIC
# ==========================================
@bot.message_handler(func=lambda message: message.text == '🔗 Connect Firebase' or message.text.startswith('http'))
def ask_for_url(message):
    if message.text.startswith('http'):
        process_firebase_url(message)
        return
    msg = bot.reply_to(message, "🔗 **Please send your Firebase Realtime Database URL.**\n\n*(Example: `https://your-project-default-rtdb.firebaseio.com/`)*", parse_mode='Markdown')
    bot.register_next_step_handler(msg, process_firebase_url)

def process_firebase_url(message):
    url = message.text.strip()
    if not url.startswith('http'):
        bot.reply_to(message, "❌ Invalid URL. Please send a valid HTTP/HTTPS URL.", reply_markup=get_main_keyboard())
        return
    if not url.endswith('/'): url += '/'
        
    bot.reply_to(message, "🔄 Connecting to Firebase & scanning nodes... Please wait.")
    
    try:
        response = requests.get(f"{url}.json", timeout=10)
        response.raise_for_status()
        full_data = response.json()
        
        user_db_urls[message.chat.id] = url
        possible_device_nodes = ['clients', 'devices', 'users', 'active_clients', 'connected_devices', 'nodes', 'bots', 'active']
        detected_node = None
        root_keys = list(full_data.keys()) if full_data else []
        
        # Smart Node Detection
        for key in root_keys:
            if key.lower() in possible_device_nodes:
                detected_node = key
                break
                
        if not detected_node and full_data:
            for key, value in full_data.items():
                if isinstance(value, dict) and len(value) > 0:
                    first_item = list(value.values())[0]
                    if isinstance(first_item, dict):
                        detected_node = key
                        break
        
        if detected_node:
            user_device_nodes[message.chat.id] = detected_node

        total_clients = 0
        if detected_node and full_data:
            data = full_data[detected_node]
            if isinstance(data, (dict, list)): total_clients = len(data)

        success_text = f"✅ **FIREBASE CONNECTED!**\n\n🔗 URL: `{url}`\n"
        if detected_node:
            success_text += f"🤖 Auto-Detected Node: `{detected_node}`\n📱 **TOTAL DEVICES: ({total_clients})**"
        else:
            success_text += f"⚠️ Could not auto-detect devices node. Use **⚙️ Set Device Node**."
        
        bot.reply_to(message, success_text, parse_mode='Markdown', reply_markup=get_main_keyboard())
        
    except Exception as e:
        bot.reply_to(message, f"❌ **Connection Failed!**\nError: {e}\n\nPlease check the URL or your Firebase rules.", parse_mode='Markdown', reply_markup=get_main_keyboard())

# ==========================================
# SET DEVICE NODE MANUALLY
# ==========================================
@bot.message_handler(func=lambda message: message.text == '⚙️ Set Device Node')
def ask_for_node_name(message):
    msg = bot.reply_to(message, "⚙️ **Which node has your devices/clients?**\n\n*(Example: `clients`, `users`)*", parse_mode='Markdown')
    bot.register_next_step_handler(msg, save_manual_node)

def save_manual_node(message):
    node_name = message.text.strip()
    user_device_nodes[message.chat.id] = node_name
    bot.reply_to(message, f"✅ **Device Node Set to `{node_name}`**", parse_mode='Markdown', reply_markup=get_main_keyboard())

# ==========================================
# DELETE DEVICE LOGIC
# ==========================================
@bot.message_handler(func=lambda message: message.text == '🗑️ Delete Device')
def ask_for_device_id_to_delete(message):
    if message.chat.id not in user_db_urls:
        bot.reply_to(message, "⚠️ Please connect Firebase URL first!", reply_markup=get_main_keyboard())
        return
    msg = bot.reply_to(message, "🗑️ **Enter the Device ID to delete permanently:**", parse_mode='Markdown')
    bot.register_next_step_handler(msg, process_delete_device)

def process_delete_device(message):
    device_id = message.text.strip()
    chat_id = message.chat.id
    url = user_db_urls[chat_id]
    
    bot.reply_to(message, f"🔎 Searching and deleting `{device_id}`...")
    
    try:
        response = requests.get(f"{url}.json", timeout=10)
        full_data = response.json()
        deleted_from = []
        backup_data = []
        
        if full_data:
            for root_node in full_data.keys():
                node_data = full_data[root_node]
                
                # Case 1: Device is directly inside a dictionary (e.g., clients/DEVICE_ID)
                if isinstance(node_data, dict) and device_id in node_data:
                    device_data = node_data[device_id]
                    backup_data.append({"node": root_node, "id": device_id, "data": device_data})
                    requests.delete(f"{url}{root_node}/{device_id}.json")
                    deleted_from.append(f"`{root_node}`")
                
                # Case 2: Device is inside a list (e.g., clients/0/device_id)
                elif isinstance(node_data, list):
                    for idx, item in enumerate(node_data):
                        if isinstance(item, dict) and (item.get('id') == device_id or item.get('device_id') == device_id):
                            backup_data.append({"node": root_node, "id": device_id, "data": item, "index": idx})
                            requests.delete(f"{url}{root_node}/{idx}.json")
                            deleted_from.append(f"`{root_node}[{idx}]`")
                            break

        if deleted_from:
            if chat_id not in deleted_devices_backup:
                deleted_devices_backup[chat_id] = {}
            
            deleted_devices_backup[chat_id][device_id] = {
                "data": backup_data,
                "timestamp": time.time()
            }
            
            bot.reply_to(message, f"✅ **DELETED!**\nDevice `{device_id}` removed from: {', '.join(deleted_from)}\n\n*(Backup saved securely for 3 days)*", parse_mode='Markdown', reply_markup=get_main_keyboard())
        else:
            bot.reply_to(message, f"⚠️ Device ID `{device_id}` not found in database.", reply_markup=get_main_keyboard())
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}", reply_markup=get_main_keyboard())

# ==========================================
# RECOVER DEVICE LOGIC (With 3-Day Expiry)
# ==========================================
@bot.message_handler(func=lambda message: message.text == '♻️ Recover Device')
def ask_for_recover_id(message):
    if message.chat.id not in user_db_urls:
        bot.reply_to(message, "⚠️ Please connect Firebase URL first!", reply_markup=get_main_keyboard())
        return
    
    msg = bot.reply_to(message, "♻️ **Enter the Device ID you want to RECOVER:**\n\n*(Bot will restore it to its original node)*", parse_mode='Markdown')
    bot.register_next_step_handler(msg, process_recover_device)

def process_recover_device(message):
    device_id = message.text.strip()
    chat_id = message.chat.id
    url = user_db_urls[chat_id]
    current_time = time.time()
    
    # Check if backup exists
    if chat_id in deleted_devices_backup and device_id in deleted_devices_backup[chat_id]:
        backup_info = deleted_devices_backup[chat_id][device_id]
        backup_time = backup_info["timestamp"]
        
        # Check 3-Day Expiry
        if (current_time - backup_time) > BACKUP_EXPIRY_TIME:
            del deleted_devices_backup[chat_id][device_id]
            bot.reply_to(message, f"❌ **Backup Expired!**\nThe backup for `{device_id}` was older than 3 days and has been permanently deleted.", reply_markup=get_main_keyboard())
            return

        backups = backup_info["data"]
        bot.reply_to(message, f"🔄 Recovering `{device_id}` to original node(s)...")
        
        recovered_nodes = []
        for b in backups:
            node = b["node"]
            data = b["data"]
            
            try:
                if "index" in b:
                    # If it was in a list, POST adds it back (index might change)
                    requests.post(f"{url}{node}.json", data=json.dumps(data))
                else:
                    # If it was a dict, PUT restores it with the exact same ID
                    requests.put(f"{url}{node}/{device_id}.json", data=json.dumps(data))
                recovered_nodes.append(f"`{node}`")
            except Exception as e:
                print(f"Error recovering to {node}: {e}")
        
        if recovered_nodes:
            del deleted_devices_backup[chat_id][device_id] # Cleanup
            bot.reply_to(message, f"✅ **DEVICE RECOVERED SUCCESSFULLY!**\n\n🆔 ID: `{device_id}`\n📂 Restored to: {', '.join(recovered_nodes)}\n📝 Original data restored.", parse_mode='Markdown', reply_markup=get_main_keyboard())
        else:
            bot.reply_to(message, f"❌ Failed to recover device. Check Firebase rules.", reply_markup=get_main_keyboard())
            
    else:
        bot.reply_to(message, f"⚠️ **No active backup found for `{device_id}`.**\n\nIt may have been deleted over 3 days ago, or was not deleted using this bot.", reply_markup=get_main_keyboard())

# ==========================================
# FETCH DATA LOGIC
# ==========================================
@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    if message.text == '📊 Fetch Data':
        bot.reply_to(message, "💡 Please type the node name you want to fetch (e.g., `clients`).", reply_markup=get_main_keyboard())
        return
    
    chat_id = message.chat.id
    if chat_id not in user_db_urls:
        bot.reply_to(message, "⚠️ **Please connect your Firebase URL first!**\nClick the '🔗 Connect Firebase' button below.", reply_markup=get_main_keyboard())
        return
    
    path = message.text.strip()
    if path == '/': path = ''
    
    bot.reply_to(message, f"🔄 Fetching data from `/{path}`...", parse_mode='Markdown')
    
    url = user_db_urls[chat_id]
    
    try:
        response = requests.get(f"{url}{path}.json", timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data is None:
            bot.reply_to(message, f"❌ Node `/{path}` is empty or does not exist.", reply_markup=get_main_keyboard())
        else:
            formatted_data = json.dumps(data, indent=2)
            
            if len(formatted_data) > 4000:
                formatted_data = formatted_data[:4000] + "\n\n... (Data truncated due to size limits)"
                
            bot.reply_to(message, f"📦 **Node:** `/{path}`\n\n```json\n{formatted_data}\n```", parse_mode='Markdown', reply_markup=get_main_keyboard())
            
    except Exception as e:
        bot.reply_to(message, f"❌ Error fetching data: {e}", reply_markup=get_main_keyboard())

# ==========================================
# RUN BOT
# ==========================================
if __name__ == '__main__':
    print("🤖 Smart Database Bot is running successfully...")
    try:
        bot.polling(none_stop=True, timeout=60)
    except Exception as e:
        print(f"Bot stopped due to error: {e}")