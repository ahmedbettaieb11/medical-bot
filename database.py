"""Stores articles in a SQLite database (a single file: medical_bot.db).

Run it directly to create the database and check it works:  python database.py
"""

import hashlib
import json
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone

DB_FILE = "medical_bot.db"


# Columns added after the first version. The AI analysis columns (Phase 2) stay empty
# until Gemini has read the article.
NEW_COLUMNS = [
    ("keywords", "TEXT"),       # health keywords that matched, e.g. "grippe, vaccin"
    ("analyzed_at", "TEXT"),    # when Gemini read it (empty = not analysed yet)
    ("relevant", "INTEGER"),    # 1 = real health event, 0 = noise (job ad, conference...)
    ("ai_reason", "TEXT"),      # Gemini's one-sentence explanation
    ("disease", "TEXT"),
    ("governorates", "TEXT"),   # JSON list, e.g. ["Sfax", "Gabès"]
    ("country", "TEXT"),
    ("cases", "INTEGER"),
    ("deaths", "INTEGER"),
    ("severity", "TEXT"),       # none / low / medium / high
    ("trend", "TEXT"),          # rising / stable / falling / unknown
    ("summary_fr", "TEXT"),
    ("ai_model", "TEXT"),
    ("event_id", "INTEGER"),    # the outbreak this article is about (several articles → one event)
]

SEVERITY_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3}
EVENT_WINDOW_DAYS = 30  # a new article can join an event seen in the last 30 days


def connect():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row  # lets us read columns by name, e.g. row["title"]
    return conn


def init_db():
    """Create the articles table if it doesn't exist yet."""
    with connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                url         TEXT UNIQUE NOT NULL,
                fingerprint TEXT UNIQUE NOT NULL,  -- same story on another site = same fingerprint
                title       TEXT NOT NULL,
                summary     TEXT,
                source      TEXT NOT NULL,
                language    TEXT,
                published   TEXT,
                fetched_at  TEXT NOT NULL,
                alerted     INTEGER NOT NULL DEFAULT 0  -- 1 once sent to Telegram
            )
        """)
        # One row per real-world event (e.g. "measles in Sfax"), however many outlets report it.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                disease          TEXT,
                country          TEXT,
                governorates     TEXT,     -- JSON list, all places mentioned so far
                cases            INTEGER,  -- highest number reported so far
                deaths           INTEGER,
                severity         TEXT,     -- highest severity so far
                trend            TEXT,     -- from the latest article
                summary_fr       TEXT,     -- from the latest article
                first_seen       TEXT NOT NULL,
                last_seen        TEXT NOT NULL,
                article_count    INTEGER NOT NULL DEFAULT 1,
                alerted_severity TEXT      -- severity of the last Telegram alert (empty = never sent)
            )
        """)
        # Databases created before these columns existed: add the missing ones.
        columns = [row["name"] for row in conn.execute("PRAGMA table_info(articles)")]
        for name, kind in NEW_COLUMNS:
            if name not in columns:
                conn.execute(f"ALTER TABLE articles ADD COLUMN {name} {kind}")
        # Relevant articles analysed before events existed: give each its own event.
        for article in conn.execute(
                "SELECT * FROM articles WHERE relevant = 1 AND event_id IS NULL ORDER BY id").fetchall():
            event_id = _new_event(conn, article, article["analyzed_at"])
            if article["alerted"]:
                conn.execute("UPDATE events SET alerted_severity = severity WHERE id = ?", (event_id,))


def fingerprint(title):
    """Turn a title into a short code, ignoring case, accents and punctuation.

    "Grippe: 120 cas à Sfax!" and "grippe 120 cas a Sfax" get the same fingerprint,
    so the same story isn't saved (and alerted) twice.
    """
    text = unicodedata.normalize("NFKD", title.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s]", " ", text)
    text = " ".join(text.split())
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def save_article(url, title, summary, source, language, published, keywords=""):
    """Save an article. Returns True if it was new, False if we already had it."""
    with connect() as conn:
        cursor = conn.execute(
            """INSERT OR IGNORE INTO articles
               (url, fingerprint, title, summary, source, language, published, fetched_at,
                keywords)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (url, fingerprint(title), title, summary, source, language, published,
             datetime.now(timezone.utc).isoformat(timespec="seconds"), keywords),
        )
        return cursor.rowcount == 1


def get_unanalyzed():
    """Articles Gemini hasn't read yet, oldest first."""
    with connect() as conn:
        return conn.execute("SELECT * FROM articles WHERE analyzed_at IS NULL ORDER BY id").fetchall()


def save_analysis(article_id, result):
    """Store Gemini's answer (the dict returned by analyze.analyze_article) for one article."""
    with connect() as conn:
        conn.execute(
            """UPDATE articles SET analyzed_at = ?, relevant = ?, ai_reason = ?, disease = ?,
                   governorates = ?, country = ?, cases = ?, deaths = ?, severity = ?, trend = ?,
                   summary_fr = ?, ai_model = ?
               WHERE id = ?""",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"), int(result["relevant"]),
             result["reason"], result["disease"],
             json.dumps(result["governorates"], ensure_ascii=False), result["country"],
             result["cases"], result["deaths"], result["severity"], result["trend"],
             result["summary_fr"], result["model"], article_id),
        )


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_event(conn, article, when):
    cursor = conn.execute(
        """INSERT INTO events (disease, country, governorates, cases, deaths, severity, trend,
                               summary_fr, first_seen, last_seen)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (article["disease"], article["country"], article["governorates"], article["cases"],
         article["deaths"], article["severity"], article["trend"], article["summary_fr"], when, when),
    )
    conn.execute("UPDATE articles SET event_id = ? WHERE id = ?", (cursor.lastrowid, article["id"]))
    return cursor.lastrowid


def _bigger(a, b):
    """The larger of two numbers, ignoring missing ones."""
    numbers = [n for n in (a, b) if n is not None]
    return max(numbers) if numbers else None


def get_recent_events():
    """Events seen in the last EVENT_WINDOW_DAYS days, newest first (shown to Gemini for matching)."""
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM events WHERE last_seen >= datetime('now', ?) ORDER BY last_seen DESC",
            (f"-{EVENT_WINDOW_DAYS} days",),
        ).fetchall()


def link_to_event(article_id, event_id=None):
    """Attach an analysed, relevant article to an event: an existing one (event_id), or a new one.

    When joining an existing event, the event keeps the highest numbers and severity reported
    so far, all places mentioned, and the latest trend and summary.
    """
    with connect() as conn:
        article = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
        event = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone() if event_id else None
        if event is None:
            return _new_event(conn, article, _now())

        places = json.loads(event["governorates"] or "[]")
        places += [p for p in json.loads(article["governorates"] or "[]") if p not in places]
        severity = max(event["severity"], article["severity"], key=lambda s: SEVERITY_RANK.get(s, 0))
        conn.execute(
            """UPDATE events SET governorates = ?, cases = ?, deaths = ?, severity = ?,
                   trend = ?, summary_fr = ?, last_seen = ?, article_count = article_count + 1
               WHERE id = ?""",
            (json.dumps(places, ensure_ascii=False), _bigger(event["cases"], article["cases"]),
             _bigger(event["deaths"], article["deaths"]), severity,
             article["trend"] if article["trend"] != "unknown" else event["trend"],
             article["summary_fr"], _now(), event_id),
        )
        conn.execute("UPDATE articles SET event_id = ? WHERE id = ?", (event_id, article_id))
        return event_id


def get_events_to_alert(min_severity):
    """Events at or above min_severity whose severity went up since their last alert (or never alerted)."""
    with connect() as conn:
        events = conn.execute("SELECT * FROM events ORDER BY id").fetchall()
    rank = SEVERITY_RANK.get
    return [e for e in events
            if rank(e["severity"], 0) >= rank(min_severity)
            and rank(e["severity"], 0) > rank(e["alerted_severity"] or "none")]


def get_event_articles(event_id):
    """All articles about one event, oldest first."""
    with connect() as conn:
        return conn.execute("SELECT * FROM articles WHERE event_id = ? ORDER BY id", (event_id,)).fetchall()


def mark_event_alerted(event_id, severity):
    with connect() as conn:
        conn.execute("UPDATE events SET alerted_severity = ? WHERE id = ?", (severity, event_id))
        conn.execute("UPDATE articles SET alerted = 1 WHERE event_id = ?", (event_id,))


if __name__ == "__main__":
    init_db()
    with connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    print(f"✅ Database ready: {DB_FILE} ({count} articles stored)")
