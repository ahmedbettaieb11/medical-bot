"""Sends messages to your Telegram chat, using the token and chat ID saved in .env."""

import html
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()


def send_message(text):
    """Send a message (Telegram HTML formatting allowed). Returns True if it was delivered."""
    if not TOKEN or not CHAT_ID:
        print("❌ Telegram token or chat ID missing in .env (run: python setup_telegram.py)")
        return False
    # The connection sometimes drops for a moment, so we try up to 3 times before giving up.
    for attempt, wait in enumerate([3, 10, None], start=1):
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                data={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
                timeout=30,
            ).json()
        except requests.RequestException as error:
            print(f"⚠️  Could not reach Telegram (try {attempt}/3): {error.__class__.__name__}")
            if wait:
                time.sleep(wait)
            continue
        if not response.get("ok"):
            print(f"❌ Telegram refused the message: {response.get('description')}")
        return bool(response.get("ok"))
    return False


def format_article(article):
    """Build the alert text for one article from the database."""
    e = html.escape  # makes titles with < > & safe for Telegram's HTML mode
    summary = article["summary"] or ""
    if len(summary) > 250:
        summary = summary[:250].rsplit(" ", 1)[0] + "…"
    lines = [
        "🩺 <b>New health article</b>",
        "",
        f"<b>{e(article['title'])}</b>",
        "",
        f"📰 {e(article['source'])} ({e(article['language'] or '?')})",
    ]
    if article["published"]:
        lines.append(f"🕒 {e(article['published'])}")
    if article["keywords"]:
        lines.append(f"🔎 Matched: {e(article['keywords'])}")
    if summary:
        lines += ["", e(summary)]
    lines += ["", f'<a href="{e(article["url"])}">Read the article</a>']
    return "\n".join(lines)
