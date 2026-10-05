"""Reads the news sources and keeps only health-related articles.

Run it directly to preview what it finds (nothing is saved or sent):  python sources.py
"""

import html
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin

import feedparser
import requests

# Identify ourselves honestly to the websites we read.
HEADERS = {"User-Agent": "MedicalAlertBotTN/0.1 (personal health-monitoring project)"}
DELAY_SECONDS = 2  # polite pause between two websites
MAX_AGE_DAYS = 14  # older articles are ignored, so a newly added source doesn't send old news

# RSS feeds checked on 2026-10-05: all respond and their robots.txt allows reading them.
FEEDS = [
    {"source": "La Presse", "language": "fr", "url": "https://www.lapresse.tn/feed/"},
    {"source": "Kapitalis", "language": "fr", "url": "https://kapitalis.com/tunisie/feed/"},
    {"source": "Business News", "language": "fr", "url": "https://businessnews.com.tn/feed/"},
    {"source": "Mosaïque FM", "language": "fr", "url": "https://www.mosaiquefm.net/fr/rss"},
    {"source": "Mosaïque FM", "language": "ar", "url": "https://www.mosaiquefm.net/ar/rss"},
    {"source": "Babnet", "language": "ar", "url": "https://www.babnet.net/feed.php"},
]

WHO_DON_API = "https://www.who.int/api/news/diseaseoutbreaknews"

# ONMNE's site is WordPress. Its RSS feed is broken, but WordPress's data API works.
# Category 427 holds spam posts injected into the site (e.g. "The Founding of YouTube"), so we skip it.
ONMNE_SITE = "https://www.onmne.tn"
ONMNE_SPAM_CATEGORIES = {427}

# Phase 1 uses simple keywords to decide if an article is about health.
# (Phase 2 replaces this with an AI model that actually reads the article.)
FRENCH_KEYWORDS = [
    "épidémie", "épidémique", "pandémie", "maladie", "virus", "viral", "grippe", "covid",
    "choléra", "rougeole", "méningite", "hépatite", "tuberculose", "dengue", "paludisme",
    "fièvre", "rage", "brucellose", "leishmaniose", "intoxication", "toxi-infection",
    "gastro-entérite", "diarrhée", "contagion", "contagieux", "infection", "vaccin",
    "vaccination", "variole", "mpox", "varicelle", "coqueluche", "bronchiolite",
    "conjonctivite", "oreillons", "scarlatine", "gale", "zoonose", "nil occidental",
    "onmne", "ministère de la santé", "santé publique", "médicament", "médicaments",
    "pénurie de médicaments", "pharmacie", "allergie", "canicule",
]
# Arabic words get prefixes attached (ال، و، ب، لل...), and some keywords allow endings
# (e.g. مرض → مرضى). Each keyword is a small pattern, written after normalize_arabic():
# no diacritics, and أ/إ/آ written as ا. Short words like "سل" (tuberculosis) and "جرب"
# (scabies) must be whole words, so "السلة" (basketball) and "جربة" (Djerba) don't match.
ARABIC_KEYWORDS = [
    r"وباء", r"اوبئة", r"وبائ\w*", r"جائحة", r"فيروس\w*", r"مرض\w*", r"امراض",
    r"انفلونزا", r"نزلة (?:ال)?وافدة", r"نزلة برد", r"كوفيد", r"كورونا", r"كوليرا", r"حصبة",
    r"بوصفير", r"التهاب\w*", r"داء", r"سل", r"حمى", r"ملاريا", r"ضنك", r"ليشمانيا",
    r"تسمم\w*", r"اسهال", r"عدوى", r"تلقيح", r"لقاح\w*", r"تطعيم", r"جدري", r"سعال", r"جرب",
    r"وزارة الصحة", r"صحة (?:ال)?عمومية", r"حالات? (?:ال)?اصابة", r"دواء", r"ادوية",
    r"صيدلي\w*", r"صيدليات", r"حساسية",
]

_french_pattern = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in FRENCH_KEYWORDS) + r")(?:s|x)?\b", re.IGNORECASE
)
_ARABIC_LETTER = r"[\u0621-\u064A]"
_arabic_pattern = re.compile(
    rf"(?<!{_ARABIC_LETTER})(?:[وفبلك]?ال|لل|[وفبلك])?(" + "|".join(ARABIC_KEYWORDS)
    + rf")(?!{_ARABIC_LETTER})"
)


def normalize_arabic(text):
    """Remove Arabic diacritics (e.g. the shadda in الصّحة) and unify the forms of alef."""
    text = re.sub(r"[\u064B-\u0652\u0640]", "", text)
    return re.sub(r"[أإآ]", "ا", text)


def health_keywords_found(text):
    """Return the health keywords found in the text (empty list = not health-related)."""
    found = {m.group(1).lower() for m in _french_pattern.finditer(text)}
    found.update(m.group(1) for m in _arabic_pattern.finditer(normalize_arabic(text)))
    return sorted(found)


def is_recent(published):
    """True if the date is within MAX_AGE_DAYS (or if we can't read the date, to be safe)."""
    try:
        date = parsedate_to_datetime(published)  # RSS style: "Mon, 05 Oct 2026 15:31:41 +0100"
    except (TypeError, ValueError):
        try:
            date = datetime.fromisoformat(published.replace("Z", "+00:00"))  # "2026-10-05T15:31:41"
        except (AttributeError, ValueError):
            return True
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - date <= timedelta(days=MAX_AGE_DAYS)


def clean_html(raw):
    """Strip HTML tags from an RSS summary and shorten it."""
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw or ""))
    text = " ".join(text.split())
    return text[:500]


def read_feed(feed):
    """Download one RSS feed and return its articles as a list of dicts."""
    response = requests.get(feed["url"], headers=HEADERS, timeout=30)
    response.raise_for_status()
    parsed = feedparser.parse(response.content)
    articles = []
    for entry in parsed.entries:
        title = clean_html(entry.get("title", ""))
        url = entry.get("link", "")
        if not title or not url:
            continue
        articles.append({
            "url": url,
            "title": title,
            "summary": clean_html(entry.get("summary", "")),
            "source": feed["source"],
            "language": feed["language"],
            "published": entry.get("published", ""),
        })
    return articles


def read_who_outbreak_news():
    """WHO Disease Outbreak News (all countries; collect_health_articles keeps Tunisia only)."""
    params = {
        "$top": "20",
        "$orderby": "PublicationDate desc",
        "$select": "Title,PublicationDate,UrlName,Summary,Overview",
    }
    response = requests.get(WHO_DON_API, params=params, headers=HEADERS, timeout=30)
    response.raise_for_status()
    articles = []
    for item in response.json().get("value", []):
        text = " ".join(str(item.get(k) or "") for k in ("Title", "Summary", "Overview")).lower()
        articles.append({
            "mentions_tunisia": "tunisia" in text or "tunisie" in text,
            "url": f"https://www.who.int/emergencies/disease-outbreak-news/item/{item['UrlName']}",
            "title": item["Title"],
            "summary": clean_html(item.get("Summary")),
            "source": "WHO Disease Outbreak News",
            "language": "en",
            "published": item.get("PublicationDate", ""),
        })
    return articles


def read_onmne():
    """Latest posts from ONMNE (Observatoire National des Maladies Nouvelles et Émergentes)."""
    params = {
        "rest_route": "/wp/v2/posts",
        "per_page": "20",
        "_fields": "date,link,title,excerpt,categories",
    }
    response = requests.get(ONMNE_SITE + "/", params=params, headers=HEADERS, timeout=30)
    response.raise_for_status()
    articles = []
    for post in response.json():
        if ONMNE_SPAM_CATEGORIES & set(post.get("categories", [])):
            continue
        articles.append({
            "url": urljoin(ONMNE_SITE, post["link"]),
            "title": clean_html(post["title"]["rendered"]),
            "summary": clean_html(post.get("excerpt", {}).get("rendered")),
            "source": "ONMNE",
            "language": "fr",
            "published": post.get("date", ""),
            # Every ONMNE post names ONMNE and the Ministry, even job ads, so they prove nothing here.
            "ignore_keywords": {"onmne", "ministère de la santé"},
        })
    return articles


def collect_health_articles():
    """Read every source and return only the health-related articles.

    If one source fails (site down, slow...), we report it and carry on with the others.
    """
    health_articles = []
    readers = [(f"{f['source']} ({f['language']})", lambda f=f: read_feed(f)) for f in FEEDS]
    readers.append(("ONMNE", read_onmne))
    readers.append(("WHO Disease Outbreak News", read_who_outbreak_news))

    for name, reader in readers:
        try:
            articles = reader()
        except Exception as error:
            print(f"⚠️  {name}: could not read ({error})")
            continue

        kept = old = 0
        for article in articles:
            ignore = article.pop("ignore_keywords", set())
            if not is_recent(article["published"]):
                article.pop("mentions_tunisia", None)
                old += 1
                continue
            # WHO outbreak news is always about health; we only keep the ones about Tunisia.
            if "mentions_tunisia" in article:
                keywords = ["WHO: Tunisia"] if article.pop("mentions_tunisia") else []
            else:
                keywords = health_keywords_found(article["title"] + " " + article["summary"])
                keywords = [k for k in keywords if k not in ignore]
            if keywords:
                article["keywords"] = keywords
                health_articles.append(article)
                kept += 1
        too_old = f" ({old} older than {MAX_AGE_DAYS} days skipped)" if old else ""
        print(f"✅ {name}: {len(articles)} articles read, {kept} about health{too_old}")
        time.sleep(DELAY_SECONDS)

    return health_articles


if __name__ == "__main__":
    found = collect_health_articles()
    print(f"\n🩺 {len(found)} health articles found:\n")
    for a in found:
        print(f"- [{a['source']}] {a['title']}")
        print(f"    keywords: {', '.join(a['keywords'])}")
        print(f"    {a['url']}")
