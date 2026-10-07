"""Sends messages to your Telegram chat, using the token and chat ID saved in .env."""

import html
import json
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


SEVERITY_LABELS = {"high": "🔴 HIGH", "medium": "🟠 MEDIUM", "low": "🟡 LOW"}
TREND_LABELS = {"rising": "📈 rising", "stable": "➡️ stable", "falling": "📉 falling"}


def format_event(event, articles):
    """Build the alert text for one event, from the event and all the articles reporting it."""
    e = html.escape  # makes titles with < > & safe for Telegram's HTML mode
    where = ", ".join(json.loads(event["governorates"] or "[]")) or event["country"] or "?"
    header = "🔄 <b>UPDATE</b> · " if event["alerted_severity"] else ""
    lines = [
        f"{header}🩺 <b>{e((event['disease'] or 'Health event').capitalize())}</b> — {e(where)}",
        f"Severity: {SEVERITY_LABELS.get(event['severity'], event['severity'])}",
    ]
    numbers = []
    if event["cases"] is not None:
        numbers.append(f"{event['cases']} cases")
    if event["deaths"] is not None:
        numbers.append(f"{event['deaths']} deaths")
    if event["trend"] in TREND_LABELS:
        numbers.append(TREND_LABELS[event["trend"]])
    if numbers:
        lines.append(" · ".join(numbers))
    lines += ["", e(event["summary_fr"] or ""), ""]
    if len(articles) > 1:
        sources = sorted({a["source"] for a in articles})
        lines.append(f"📰 Reported by {len(articles)} articles ({e(', '.join(sources))}). Latest:")
    latest = articles[-1]
    lines += [
        f"📰 {e(latest['source'])}: <i>{e(latest['title'])}</i>",
        f'<a href="{e(latest["url"])}">Read the article</a>',
    ]
    return "\n".join(lines)
