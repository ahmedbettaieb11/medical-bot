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
]


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
        # Databases created before these columns existed: add the missing ones.
        columns = [row["name"] for row in conn.execute("PRAGMA table_info(articles)")]
        for name, kind in NEW_COLUMNS:
            if name not in columns:
                conn.execute(f"ALTER TABLE articles ADD COLUMN {name} {kind}")


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


def get_unalerted(severities):
    """Relevant articles with one of these severities, not yet sent to Telegram, oldest first."""
    marks = ", ".join("?" * len(severities))
    with connect() as conn:
        return conn.execute(
            f"""SELECT * FROM articles
                WHERE alerted = 0 AND relevant = 1 AND severity IN ({marks})
                ORDER BY id""",
            list(severities),
        ).fetchall()


def mark_alerted(article_id):
    with connect() as conn:
        conn.execute("UPDATE articles SET alerted = 1 WHERE id = ?", (article_id,))


if __name__ == "__main__":
    init_db()
    with connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    print(f"✅ Database ready: {DB_FILE} ({count} articles stored)")
