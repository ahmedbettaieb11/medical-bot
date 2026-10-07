"""Asks Google's Gemini AI to read an article and pull out the health facts in it.

Run it directly to test it on the latest saved articles (nothing is saved or sent):
    python analyze.py
"""

import html
import json
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# Tried in order: if the first model is overloaded, the next one is used.
# (Checked 2026-10-06: these work on the free tier; gemini-2.5-* is closed to new users.)
MODELS = ["gemini-3.5-flash-lite", "gemini-3.5-flash"]
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

INSTRUCTIONS = """You analyse news for a service that warns pharmaceutical companies in Tunisia
about disease outbreaks and health events that change demand for medicines.

Read the article (it may be in Arabic, French or English) and fill in the fields.

"relevant" is true only if the article reports a disease or health event that could change
demand for medicines or health products in Tunisia: outbreaks, rising case counts, seasonal
epidemics (flu, gastroenteritis...), food poisoning, vaccination campaigns, medicine shortages,
heat waves. Outbreaks abroad are relevant too (they can affect Tunisia indirectly: imported
cases, travel, stock-piling, supply chains), e.g. "first Ebola death in Kenya".
"relevant" is false for: job offers and recruitment, health-sector administration, insurance
payments (CNAM), digitalisation, conferences and awareness days, charity operations, and
single individual cases of a non-contagious or non-spreading condition.

Only report what the article says. Do not guess numbers: use null when the article gives none.
Write every text field in correct French: translate Arabic terms (e.g. تسمم غذائي = "intoxication
alimentaire"), never transliterate them and never mix Arabic words into the French text.
Always keep the French accents (é, è, à, ç): write "choléra", "été enregistrés".

You may also get a list of events already being tracked. If the article reports one of them
(same disease, same place, same outbreak, even with new numbers or from another outlet), put its
number in "same_event_as". Otherwise (a new event, or the same disease somewhere else) use null."""

# The exact shape of the answer we want back (Gemini is forced to follow it).
ANSWER_SHAPE = {
    "type": "object",
    "properties": {
        "relevant": {"type": "boolean"},
        "reason": {"type": "string", "description": "One short sentence: why relevant or not."},
        "disease": {"type": "string", "nullable": True,
                    "description": "Disease or health event in French, e.g. 'grippe', 'rougeole', 'canicule'."},
        "governorates": {"type": "array", "items": {"type": "string"},
                         "description": "Tunisian governorates concerned, in French (e.g. 'Sfax'). "
                                        "Use 'Tunisie' if national. Empty if outside Tunisia."},
        "country": {"type": "string", "description": "Country where the event happens, in French."},
        "cases": {"type": "integer", "nullable": True, "description": "Number of cases reported."},
        "deaths": {"type": "integer", "nullable": True, "description": "Number of deaths reported."},
        "severity": {"type": "string", "enum": ["none", "low", "medium", "high"],
                     "description": "high = outbreak spreading or many cases/deaths in Tunisia; "
                                    "medium = clear local cluster or official warning in Tunisia, "
                                    "or a serious outbreak in a neighbouring country (Libya, Algeria); "
                                    "low = minor, an outbreak further abroad, or yearly statistics / "
                                    "chronic disease figures (cancer, diabetes...); none = not relevant."},
        "trend": {"type": "string", "enum": ["rising", "stable", "falling", "unknown"]},
        "summary_fr": {"type": "string", "description": "One-sentence summary in French."},
        "same_event_as": {"type": "integer", "nullable": True,
                          "description": "Number of the tracked event this article reports, or null."},
    },
    "required": ["relevant", "reason", "disease", "governorates", "country", "cases", "deaths",
                 "severity", "trend", "summary_fr", "same_event_as"],
}


def ask_gemini(model, prompt):
    """Send one request to Gemini. Returns the parsed answer, or raises an error."""
    response = requests.post(
        API_URL.format(model=model),
        headers={"x-goog-api-key": API_KEY},
        json={
            "systemInstruction": {"parts": [{"text": INSTRUCTIONS}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": ANSWER_SHAPE,
                "temperature": 0,  # same article → same answer
            },
        },
        timeout=60,
    )
    response.raise_for_status()
    parts = response.json()["candidates"][0]["content"]["parts"]
    answer = json.loads(parts[-1]["text"])
    # Just in case: turn leftover HTML codes (chol&eacute;ra) into normal letters (choléra).
    for key, value in answer.items():
        if isinstance(value, str):
            answer[key] = html.unescape(value)
        elif isinstance(value, list):
            answer[key] = [html.unescape(v) for v in value]
    return answer


def describe_events(events):
    """Short list of tracked events for the prompt, e.g. '#3: grippe — Sfax, Tunisie (12 cas). ...'"""
    lines = []
    for e in events:
        where = ", ".join(json.loads(e["governorates"] or "[]") + [e["country"] or ""]).strip(", ")
        lines.append(f"#{e['id']}: {e['disease']} — {where} — {e['summary_fr']}")
    return "\n".join(lines)


def analyze_article(article, recent_events=()):
    """Return Gemini's analysis of one article (a dict), or None if Gemini couldn't be reached.

    `article` needs: title, summary, source.
    `recent_events`: events already tracked (database rows); Gemini says if the article is one of them.
    """
    if not API_KEY:
        print("❌ GEMINI_API_KEY missing in .env")
        return None
    prompt = (f"Source: {article['source']}\n"
              f"Title: {article['title']}\n"
              f"Summary: {article['summary'] or '(none)'}")
    if recent_events:
        prompt += "\n\nEvents already being tracked:\n" + describe_events(recent_events)

    # Busy or rate-limited models are common on the free tier, so we wait and retry.
    for attempt, wait in enumerate([5, 20, None], start=1):
        for model in MODELS:
            try:
                result = ask_gemini(model, prompt)
                result["model"] = model
                # Ignore an event number Gemini made up (not in the list we gave it).
                if result.get("same_event_as") not in {e["id"] for e in recent_events}:
                    result["same_event_as"] = None
                return result
            except requests.HTTPError as error:
                status = error.response.status_code
                if status not in (429, 500, 503):  # anything else (bad key...) won't fix itself
                    print(f"❌ Gemini error {status}: {error.response.text[:200]}")
                    return None
                print(f"⚠️  {model} busy (error {status}), trying another way...")
            except (requests.RequestException, KeyError, IndexError, ValueError) as error:
                print(f"⚠️  {model}: unusable answer ({error.__class__.__name__})")
        if wait:
            time.sleep(wait)
    print("❌ Gemini unavailable for now; this article will be analysed on the next run.")
    return None


if __name__ == "__main__":
    import database

    with database.connect() as conn:
        latest = conn.execute("SELECT * FROM articles ORDER BY id DESC LIMIT 8").fetchall()

    for row in latest:
        print(f"\n📰 [{row['source']}] {row['title']}")
        result = analyze_article(row)
        if result is None:
            continue
        mark = "✅ RELEVANT" if result["relevant"] else "⛔ not relevant"
        print(f"   {mark} — {result['reason']}")
        if result["relevant"]:
            print(f"   disease: {result['disease']} | where: {', '.join(result['governorates']) or result['country']}"
                  f" | cases: {result['cases']} | deaths: {result['deaths']}")
            print(f"   severity: {result['severity']} | trend: {result['trend']}")
            print(f"   {result['summary_fr']}")
        time.sleep(2)  # stay well under the free tier's per-minute limit
