"""The bot's main run: collect → save new health articles → AI reads them and groups them
into events → alert on Telegram.

Run it with:  python main.py
Each event is alerted once; again only if it becomes more severe.
"""

import time

import analyze
import database
import sources
import telegram_alert

MAX_ANALYSES_PER_RUN = 30  # keeps us well inside Gemini's free tier; leftovers wait for the next run
MAX_ALERTS_PER_RUN = 15    # leftovers are sent on the next run, so Telegram is never flooded
ALERT_MIN_SEVERITY = "medium"  # "low" (minor or far-away events) only goes to the dashboard


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
        result = analyze.analyze_article(article, database.get_recent_events())
        if result is None:
            print("⏸️  Stopping AI analysis for this run; the rest will be analysed next run.")
            break
        database.save_analysis(article["id"], result)
        analyzed += 1
        verdict = "⛔ not relevant"
        if result["relevant"]:
            event_id = database.link_to_event(article["id"], result["same_event_as"])
            joined = f"joins event #{event_id}" if result["same_event_as"] else f"new event #{event_id}"
            verdict = f"✅ {result['severity']}, {joined}"
        print(f"   {verdict}: {article['title'][:80]}")
        time.sleep(2)  # stay well under the free tier's per-minute limit
    print(f"🤖 {analyzed} articles analysed")
    if len(to_analyze) > analyzed:
        print(f"   ({len(to_analyze) - analyzed} more waiting for the next run)")

    # One alert per event (not per article); a new alert only if the event got more severe.
    pending = database.get_events_to_alert(ALERT_MIN_SEVERITY)
    sent = 0
    for event in pending[:MAX_ALERTS_PER_RUN]:
        articles = database.get_event_articles(event["id"])
        if not telegram_alert.send_message(telegram_alert.format_event(event, articles)):
            print("⏸️  Stopping alerts for this run; unsent events will be retried next run.")
            break
        database.mark_event_alerted(event["id"], event["severity"])
        sent += 1
        time.sleep(1)  # Telegram allows about one message per second
    print(f"📨 {sent} alerts sent to Telegram")
    if len(pending) > MAX_ALERTS_PER_RUN:
        print(f"   ({len(pending) - MAX_ALERTS_PER_RUN} more waiting; they'll go out on the next run)")


if __name__ == "__main__":
    main()
