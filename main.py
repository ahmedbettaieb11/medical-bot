"""The bot's main run: collect → save new health articles → alert on Telegram.

Run it with:  python main.py
Each run only alerts about articles it hasn't seen before.
"""

import time

import database
import sources
import telegram_alert

MAX_ALERTS_PER_RUN = 15  # leftovers are sent on the next run, so Telegram is never flooded


def main():
    database.init_db()

    print("📥 Reading sources...")
    articles = sources.collect_health_articles()

    new_count = 0
    for a in articles:
        if database.save_article(a["url"], a["title"], a["summary"], a["source"],
                                 a["language"], a["published"], ", ".join(a["keywords"])):
            new_count += 1
    print(f"\n💾 {len(articles)} health articles found, {new_count} new (the rest were already saved)")

    pending = database.get_unalerted()
    sent = 0
    for article in pending[:MAX_ALERTS_PER_RUN]:
        if not telegram_alert.send_message(telegram_alert.format_article(article)):
            print("⏸️  Stopping alerts for this run; unsent articles will be retried next run.")
            break
        database.mark_alerted(article["id"])
        sent += 1
        time.sleep(1)  # Telegram allows about one message per second
    print(f"📨 {sent} alerts sent to Telegram")
    if len(pending) > MAX_ALERTS_PER_RUN:
        print(f"   ({len(pending) - MAX_ALERTS_PER_RUN} more waiting; they'll go out on the next run)")


if __name__ == "__main__":
    main()
