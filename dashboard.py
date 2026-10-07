"""The web dashboard: everything the bot has found, in one page.

Run it on your computer with:  streamlit run dashboard.py
(It only reads the database; it never changes it or sends alerts.)
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

import demand

DB_FILE = "medical_bot.db"
SEVERITY_ICONS = {"high": "🔴 High", "medium": "🟠 Medium", "low": "🟡 Low", "none": "⚪ None"}
TREND_ICONS = {"rising": "📈 Rising", "stable": "➡️ Stable", "falling": "📉 Falling", "unknown": "—"}
LEVEL_RANK = {"slight": 1, "moderate": 2, "strong": 3}

st.set_page_config(page_title="Medical Alert Bot — Tunisia", page_icon="🩺", layout="wide")


@st.cache_data(ttl=600)  # re-read the database at most every 10 minutes
def load():
    # "mode=ro" opens the database read-only, so the dashboard can never change it.
    conn = sqlite3.connect(f"file:{DB_FILE}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    events = [dict(e) for e in conn.execute("SELECT * FROM events ORDER BY last_seen DESC")]
    articles = [dict(a) for a in conn.execute("SELECT * FROM articles ORDER BY id DESC")]
    conn.close()
    return events, articles


def where(event):
    return ", ".join(json.loads(event["governorates"] or "[]")) or event["country"] or "?"


def arrows(product):
    return ("⬆️" if product["direction"] == demand.UP else "⬇️") * demand.ARROWS[product["level"]]


events, articles = load()
articles_by_event = {}
for a in reversed(articles):  # oldest first within each event
    if a["event_id"]:
        articles_by_event.setdefault(a["event_id"], []).append(a)
for e in events:
    e["articles"] = articles_by_event.get(e["id"], [])
    e["estimate"] = demand.estimate(e, e["articles"])

# ---------- Sidebar: filters ----------
st.sidebar.header("Filters")
days = st.sidebar.selectbox("Events seen in the last", [7, 30, 90, 365], index=1,
                            format_func=lambda d: f"{d} days")
severities = st.sidebar.multiselect("Severity", ["high", "medium", "low"], default=["high", "medium", "low"],
                                    format_func=SEVERITY_ICONS.get)
tunisia_only = st.sidebar.checkbox("Tunisia only", value=False)
st.sidebar.caption("Estimates are relative (direction, size, confidence), not unit sales. "
                   "The disease → product table has not yet been validated by a pharmacist.")

since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
shown = [e for e in events
         if e["last_seen"] >= since and e["severity"] in severities
         and (not tunisia_only or "tunisie" in demand._plain(e["country"]))]

# ---------- Header ----------
st.title("🩺 Medical Alert Bot — Tunisia")
last_update = max((a["fetched_at"] for a in articles), default=None)
if last_update:
    st.caption(f"Last data update: {last_update[:16].replace('T', ' ')} UTC · "
               f"{len(articles)} health articles read since the start")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Events shown", len(shown))
c2.metric("High severity", sum(e["severity"] == "high" for e in shown))
c3.metric("Medium severity", sum(e["severity"] == "medium" for e in shown))
c4.metric("In Tunisia", sum("tunisie" in demand._plain(e["country"]) for e in shown))

tab_products, tab_events, tab_articles = st.tabs(["💊 Products to watch", "🦠 Events", "📰 All articles"])

# ---------- Tab 1: products expected to move, across all shown events ----------
with tab_products:
    st.subheader("Product categories expected to move")
    rows = {}
    for e in shown:
        for p in e["estimate"]["products"]:
            key = (p["category"], p["direction"])
            row = rows.setdefault(key, {"Product category": p["category"], "level": 0, "Change": "",
                                        "Because of": [], "Confidence": []})
            if LEVEL_RANK[p["level"]] > row["level"]:
                row["level"], row["Change"] = LEVEL_RANK[p["level"]], f"{arrows(p)} {p['level']}"
            row["Because of"].append(f"{e['disease']} ({where(e)})")
            row["Confidence"].append(e["estimate"]["confidence"])
    if rows:
        table = pd.DataFrame(sorted(rows.values(), key=lambda r: -r["level"]))
        table["Because of"] = table["Because of"].map(", ".join)
        table["Confidence"] = table["Confidence"].map(
            lambda c: max(c, key=["low", "medium", "high"].index))
        st.dataframe(table.drop(columns="level"), hide_index=True, width="stretch")
        st.caption("When several events affect the same product, the strongest expected change is shown.")
    else:
        st.info("No product category is expected to move noticeably for the events shown. "
                "Events far from Tunisia usually have no direct effect on demand here.")

# ---------- Tab 2: one card per event ----------
with tab_events:
    if not shown:
        st.info("No events match these filters.")
    for e in shown:
        est = e["estimate"]
        title = (f"{SEVERITY_ICONS.get(e['severity'], e['severity'])} · "
                 f"**{(e['disease'] or 'Health event').capitalize()}** — {where(e)}")
        with st.expander(title, expanded=e["severity"] == "high"):
            numbers = [f"**{e['cases']}** cases" if e["cases"] is not None else None,
                       f"**{e['deaths']}** deaths" if e["deaths"] is not None else None,
                       TREND_ICONS.get(e["trend"], ""),
                       f"first seen {e['first_seen'][:10]}, last {e['last_seen'][:10]}",
                       f"{len(e['articles'])} article(s)"]
            st.markdown(" · ".join(n for n in numbers if n))
            st.write(e["summary_fr"] or "")

            st.markdown(f"**💊 Demand outlook** (confidence: {est['confidence']})")
            for p in est["products"]:
                st.markdown(f"- {arrows(p)} {p['category']} — {p['level']}")
            details = [f"Based on: {', '.join(est['reasons'])}"]
            if est["evidence"]:
                details.append(f"Evidence: {', '.join(est['evidence'])}")
            st.caption(" · ".join(details + est["notes"]))

            st.markdown("**📰 Articles**")
            for a in e["articles"]:
                st.markdown(f"- {a['source']}: [{a['title']}]({a['url']})")

# ---------- Tab 3: every article, including the ones the AI rejected ----------
with tab_articles:
    st.caption("Every health article the bot collected, with the AI's verdict and reason.")
    table = pd.DataFrame([{
        "Date": (a["fetched_at"] or "")[:10],
        "Source": a["source"],
        "Title": a["title"],
        "Relevant": {1: "✅", 0: "⛔"}.get(a["relevant"], "⏳ not read yet"),
        "Severity": SEVERITY_ICONS.get(a["severity"], ""),
        "AI's reason": a["ai_reason"] or "",
        "Link": a["url"],
    } for a in articles])
    if table.empty:
        st.info("No articles yet.")
    else:
        st.dataframe(table, hide_index=True, width="stretch",
                     column_config={"Link": st.column_config.LinkColumn("Link", display_text="open")})
