"""Stores articles in a SQLite database (a single file: medical_bot.db).

Run it directly to create the database and check it works:  python database.py
"""

import hashlib
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone

DB_FILE = "medical_bot.db"


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
                alerted     INTEGER NOT NULL DEFAULT 0,  -- 1 once sent to Telegram
                keywords    TEXT  -- health keywords that matched, e.g. "grippe, vaccin"
            )
        """)
        # Databases created before the keywords column existed: add it.
        columns = [row["name"] for row in conn.execute("PRAGMA table_info(articles)")]
        if "keywords" not in columns:
            conn.execute("ALTER TABLE articles ADD COLUMN keywords TEXT")


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


def get_unalerted():
    """Articles saved but not yet sent to Telegram, oldest first."""
    with connect() as conn:
        return conn.execute("SELECT * FROM articles WHERE alerted = 0 ORDER BY id").fetchall()


def mark_alerted(article_id):
    with connect() as conn:
        conn.execute("UPDATE articles SET alerted = 1 WHERE id = ?", (article_id,))


if __name__ == "__main__":
    init_db()
    with connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    print(f"✅ Database ready: {DB_FILE} ({count} articles stored)")
