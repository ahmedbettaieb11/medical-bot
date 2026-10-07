"""Sends messages to your Telegram chat, using the token and chat ID saved in .env."""

import html
import json
import os
import time

import requests
from dotenv import load_dotenv

import demand

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


def format_estimate(est):
    """The demand outlook part of an alert (list of lines, ending with an empty line)."""
    e = html.escape
    lines = [f"💊 <b>Demand outlook</b> (estimate · confidence: {est['confidence']})"]
    for p in est["products"]:
        arrow = ("⬆️" if p["direction"] == demand.UP else "⬇️") * demand.ARROWS[p["level"]]
        lines.append(f"{arrow} {e(p['category'])} — {p['level']}")
    details = [f"Based on: {', '.join(est['reasons'])}"]
    if est["evidence"]:
        details.append(f"Evidence: {', '.join(est['evidence'])}")
    details += est["notes"]
    lines += [f"<i>{e(d)}</i>" for d in details]
    return lines + [""]


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
    lines += format_estimate(demand.estimate(event, articles))
    if len(articles) > 1:
        sources = sorted({a["source"] for a in articles})
        lines.append(f"📰 Reported by {len(articles)} articles ({e(', '.join(sources))}). Latest:")
    latest = articles[-1]
    lines += [
        f"📰 {e(latest['source'])}: <i>{e(latest['title'])}</i>",
        f'<a href="{e(latest["url"])}">Read the article</a>',
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    # Sends a made-up example alert, to see what alerts look like:  python telegram_alert.py
    example_event = {
        "disease": "rougeole", "country": "Tunisie", "governorates": '["Sfax"]', "severity": "high",
        "trend": "rising", "cases": 140, "deaths": 2, "first_seen": "2026-03-15T10:00:00+00:00",
        "summary_fr": "EXEMPLE FICTIF : 140 cas de rougeole et deux décès annoncés à Sfax.",
        "alerted_severity": None,
    }
    example_articles = [
        {"source": "La Presse", "title": "Exemple : 25 cas de rougeole à Sfax", "url": "https://example.com/1"},
        {"source": "Mosaïque FM", "title": "Exemple : 140 cas de rougeole à Sfax", "url": "https://example.com/2"},
    ]
    text = "🧪 <b>TEST — not a real alert</b>\n\n" + format_event(example_event, example_articles)
    print("✅ Test alert sent to Telegram" if send_message(text) else "❌ Test alert not sent")
