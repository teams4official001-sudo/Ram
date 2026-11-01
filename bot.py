import telebot
from telebot import types
import requests
import json
import time

# ==========================================
# CONFIGURATION
# ==========================================
BOT_TOKEN = '8227430826:AAFrqELQwziSEHhMAE9-yjyw77HHdFUkSsg'  # <--- Yahan apna Bot Token daalein
BACKUP_EXPIRY_TIME = 72 * 60 * 60  # 3 Din (72 Ghante)

bot = telebot.TeleBot(BOT_TOKEN)

# ==========================================
# GLOBAL MEMORY
# ==========================================
user_db_urls = {}
user_device_nodes = {}
deleted_devices_backup = {} 

# ==========================================
# KEYBOARD SETUP
# ==========================================
def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn_connect = types.KeyboardButton('🔗 Connect Firebase')
    btn_delete = types.KeyboardButton('🗑️ Delete Device')
    btn_recover = types.KeyboardButton('♻️ Recover Device')
    btn_logout = types.KeyboardButton('🚪 Logout')
    markup.add(btn_connect, btn_delete, btn_recover, btn_logout)
    return markup

# ==========================================
# START COMMAND
# ==========================================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_name = message.from_user.first_name
    welcome_text = (
        f"⚡ **DATABASE MANAGER BOT** ⚡\n\n"
        f"Welcome, **{user_name}**! Main aapki Firebase Database ko manage karne mein madad karunga. 🤖\n\n"
        f"🔹 **Features:**\n"
        f"1. **🔗 Connect Firebase** - Apna database link karein.\n"
        f"2. **🗑️ Delete Device** - Kisi bhi Device ID ko delete karein.\n"
        f"3. **♻️ Recover Device** - Delete kiye gaye device ko wapas layein (3 din ke andar).\n\n"
        f"*Status: System Online* 🟢"
    )
    bot.reply_to(message, welcome_text, parse_mode='Markdown', reply_markup=get_main_keyboard())

# ==========================================
# CONNECT FIREBASE LOGIC
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
        msg = bot.send_message(chat_id, "🔗 **Please send your Firebase Realtime Database URL.**\n\n*(Example: `https://your-project-default-rtdb.firebaseio.com/`)*", parse_mode='Markdown')
        bot.register_next_step_handler(msg, process_firebase_url)
        
    elif call.data == "logout_fb":
        if chat_id in user_db_urls:
            del user_db_urls[chat_id]
            if chat_id in user_device_nodes: del user_device_nodes[chat_id]
            bot.answer_callback_query(call.id, "Logged out successfully.")
            bot.edit_message_text("🚪 **Logged Out Successfully!**\n\n(Aapke backups safe hain, aap dobara connect karke recover kar sakte hain).", chat_id=chat_id, message_id=call.message.message_id)
        else:
            bot.answer_callback_query(call.id, "No Firebase connected.")

def process_firebase_url(message):
    url = message.text.strip()
    if not url.startswith('http'):
        bot.reply_to(message, "❌ Invalid URL.", reply_markup=get_main_keyboard())
        return
    if not url.endswith('/'): url += '/'
        
    bot.reply_to(message, "🔄 Connecting to Firebase...")
    
    try:
        full_data = requests.get(f"{url}.json", timeout=10).json()
        user_db_urls[message.chat.id] = url
        
        # Auto Detect Node
        detected_node = None
        root_keys = list(full_data.keys()) if full_data else []
        for key in root_keys:
            if key.lower() in ['clients', 'devices', 'users', 'active_clients']:
                detected_node = key
                break
                
        if detected_node:
            user_device_nodes[message.chat.id] = detected_node
            total = len(full_data[detected_node])
            bot.reply_to(message, f"✅ **Connected!**\n\n🤖 Detected Node: `{detected_node}`\n📱 Total Devices: `{total}`", parse_mode='Markdown', reply_markup=get_main_keyboard())
        else:
            user_device_nodes[message.chat.id] = "clients"
            bot.reply_to(message, f"✅ **Connected!**\n\n⚠️ Could not auto-detect node. Will use `clients` by default.", parse_mode='Markdown', reply_markup=get_main_keyboard())
    except Exception as e:
        bot.reply_to(message, f"❌ **Connection Failed!**\nError: {e}", reply_markup=get_main_keyboard())

# ==========================================
# DELETE DEVICE LOGIC
# ==========================================
@bot.message_handler(func=lambda message: message.text == '🗑️ Delete Device')
def ask_for_device_id_to_delete(message):
    if message.chat.id not in user_db_urls:
        bot.reply_to(message, "⚠️ Please connect Firebase first!", reply_markup=get_main_keyboard())
        return
    msg = bot.reply_to(message, "🗑️ **Enter the Device ID to delete permanently:**", parse_mode='Markdown')
    bot.register_next_step_handler(msg, process_delete_device)

def process_delete_device(message):
    device_id = message.text.strip()
    chat_id = message.chat.id
    url = user_db_urls[chat_id]
    
    bot.reply_to(message, f"🔎 Searching and deleting `{device_id}`...")
    
    try:
        full_data = requests.get(f"{url}.json").json()
        deleted_from = []
        backup_data = []
        
        if full_data:
            for root_node in full_data.keys():
                node_data = full_data[root_node]
                if isinstance(node_data, dict) and device_id in node_data:
                    backup_data.append({"node": root_node, "id": device_id, "data": node_data[device_id]})
                    requests.delete(f"{url}{root_node}/{device_id}.json")
                    deleted_from.append(f"`{root_node}`")
                
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
            deleted_devices_backup[chat_id][device_id] = {"data": backup_data, "timestamp": time.time()}
            
            bot.reply_to(message, f"✅ **DELETED!**\nDevice `{device_id}` removed from: {', '.join(deleted_from)}\n\n*(Backup saved for 3 days)*", parse_mode='Markdown', reply_markup=get_main_keyboard())
        else:
            bot.reply_to(message, f"⚠️ Device ID `{device_id}` not found.", reply_markup=get_main_keyboard())
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}", reply_markup=get_main_keyboard())

# ==========================================
# RECOVER DEVICE LOGIC
# ==========================================
@bot.message_handler(func=lambda message: message.text == '♻️ Recover Device')
def ask_for_recover_id(message):
    if message.chat.id not in user_db_urls:
        bot.reply_to(message, "⚠️ Please connect Firebase first!", reply_markup=get_main_keyboard())
        return
    msg = bot.reply_to(message, "♻️ **Enter the Device ID to recover:**", parse_mode='Markdown')
    bot.register_next_step_handler(msg, process_recover_device)

def process_recover_device(message):
    device_id = message.text.strip()
    chat_id = message.chat.id
    url = user_db_urls[chat_id]
    current_time = time.time()
    
    if chat_id in deleted_devices_backup and device_id in deleted_devices_backup[chat_id]:
        backup_info = deleted_devices_backup[chat_id][device_id]
        
        if (current_time - backup_info["timestamp"]) > BACKUP_EXPIRY_TIME:
            del deleted_devices_backup[chat_id][device_id]
            bot.reply_to(message, f"❌ **Backup Expired!** (Older than 3 days)", reply_markup=get_main_keyboard())
            return

        bot.reply_to(message, f"🔄 Recovering `{device_id}`...")
        recovered_nodes = []
        
        for b in backup_info["data"]:
            node, data = b["node"], b["data"]
            try:
                if "index" in b:
                    requests.post(f"{url}{node}.json", data=json.dumps(data))
                else:
                    requests.put(f"{url}{node}/{device_id}.json", data=json.dumps(data))
                recovered_nodes.append(f"`{node}`")
            except Exception:
                pass
        
        if recovered_nodes:
            del deleted_devices_backup[chat_id][device_id]
            bot.reply_to(message, f"✅ **DEVICE RECOVERED!**\n\n🆔 ID: `{device_id}`\n📂 Restored to: {', '.join(recovered_nodes)}", parse_mode='Markdown', reply_markup=get_main_keyboard())
        else:
            bot.reply_to(message, f"❌ Failed to recover device.", reply_markup=get_main_keyboard())
    else:
        bot.reply_to(message, f"⚠️ **No active backup found.** It may have expired or wasn't deleted via this bot.", reply_markup=get_main_keyboard())

# ==========================================
# LOGOUT COMMAND (Keeps Backups Safe)
# ==========================================
@bot.message_handler(func=lambda message: message.text == '🚪 Logout')
def logout_all(message):
    chat_id = message.chat.id
    
    # Sirf URL aur Node delete karo, Backup mat chhedo
    if chat_id in user_db_urls: del user_db_urls[chat_id]
    if chat_id in user_device_nodes: del user_device_nodes[chat_id]
    
    bot.reply_to(message, "✅ **Logged out!**\n\nAapka Firebase disconnect ho gaya hai, lekin aapke backups safe hain. Aap dobara connect karke recover kar sakte hain.", reply_markup=get_main_keyboard())

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
    print("🤖 Database Manager Bot is running...")
    bot.polling(none_stop=True, timeout=60)