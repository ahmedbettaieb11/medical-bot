"""The bot's main run: collect → save new health articles → AI reads them → alert on Telegram.

Run it with:  python main.py
Each run only alerts about articles it hasn't seen before.
"""

import time

import analyze
import database
import sources
import telegram_alert

MAX_ANALYSES_PER_RUN = 30  # keeps us well inside Gemini's free tier; leftovers wait for the next run
MAX_ALERTS_PER_RUN = 15    # leftovers are sent on the next run, so Telegram is never flooded
ALERT_SEVERITIES = ("medium", "high")  # "low" (minor or far-away events) only goes to the dashboard


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

    print("\n🤖 AI reading new articles...")
    to_analyze = database.get_unanalyzed()
    analyzed = 0
    for article in to_analyze[:MAX_ANALYSES_PER_RUN]:
        result = analyze.analyze_article(article)
        if result is None:
            print("⏸️  Stopping AI analysis for this run; the rest will be analysed next run.")
            break
        database.save_analysis(article["id"], result)
        analyzed += 1
        verdict = f"✅ {result['severity']}" if result["relevant"] else "⛔ not relevant"
        print(f"   {verdict}: {article['title'][:80]}")
        time.sleep(2)  # stay well under the free tier's per-minute limit
    print(f"🤖 {analyzed} articles analysed")
    if len(to_analyze) > analyzed:
        print(f"   ({len(to_analyze) - analyzed} more waiting for the next run)")

    pending = database.get_unalerted(ALERT_SEVERITIES)
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
