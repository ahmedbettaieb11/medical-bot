"""One-time setup: finds your Telegram chat ID, saves it in .env, and sends a test message.

Run it with:  python setup_telegram.py
"""

import os
import sys

import requests
from dotenv import load_dotenv, set_key

ENV_FILE = ".env"

load_dotenv(ENV_FILE)
token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

if not token or token == "paste-your-token-here":
    sys.exit("❌ No token found. Open .env and paste your BotFather token after TELEGRAM_BOT_TOKEN=")

api = f"https://api.telegram.org/bot{token}"

# 1. Check the token is valid by asking Telegram "who is this bot?"
me = requests.get(f"{api}/getMe", timeout=20).json()
if not me.get("ok"):
    sys.exit("❌ Telegram rejected the token. Copy it again from BotFather (no spaces, no quotes).")
print(f"✅ Token works. Your bot is @{me['result']['username']}")

# 2. Look at the messages people have sent the bot, to find your chat ID
updates = requests.get(f"{api}/getUpdates", timeout=20).json().get("result", [])
chats = [u["message"]["chat"] for u in updates if "message" in u]
if not chats:
    sys.exit("❌ The bot hasn't received any message yet. Open your bot in Telegram, "
             "press Start (or send 'hi'), then run this script again.")

chat = chats[-1]
chat_id = str(chat["id"])
print(f"✅ Found your chat ID: {chat_id} ({chat.get('first_name', '')})")

# 3. Save the chat ID into .env so the bot remembers it
set_key(ENV_FILE, "TELEGRAM_CHAT_ID", chat_id, quote_mode="never")
print("✅ Saved it in .env")

# 4. Send a test message
sent = requests.post(
    f"{api}/sendMessage",
    data={"chat_id": chat_id, "text": "🩺 Medical Alert Bot is connected! Test message from Python."},
    timeout=20,
).json()
if sent.get("ok"):
    print("✅ Test message sent. Check Telegram!")
else:
    print(f"❌ Sending failed: {sent.get('description')}")
