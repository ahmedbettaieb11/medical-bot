"""Estimates how an event changes demand for medicine categories in Tunisia.

No sales data is public in Tunisia, so these are RELATIVE estimates (direction + size +
confidence), built from transparent rules instead of unit numbers:
  1. DISEASES: which product categories each disease moves, and how much (1 = slight ... 3 = strong).
  2. The event: severity, where it happens, trend, season.
  3. The evidence: official source? several outlets? case counts given?
Every estimate lists the reasons behind it.

Run it directly to see estimates for example events and the events in the database:
    python demand.py
"""

import json
import re
import unicodedata
from datetime import datetime

# Set to True once a pharmacist has reviewed the DISEASES table below. Until then,
# confidence is never shown as "high".
MAPPING_VALIDATED = False

UP, DOWN = 1, -1

# Each disease: words that identify it (in Gemini's French disease name, without accents),
# the months it is usually in season in Tunisia (None = not seasonal), and the product
# categories it moves: (category, direction, impact 1-3).
# More specific diseases come first ("grippe aviaire" before "grippe").
DISEASES = [
    {"key": "grippe aviaire", "words": ["aviaire", "h5n1"], "season": None, "products": [
        ("Masques de protection", UP, 1),
        ("Antiviraux (oséltamivir)", UP, 1),
    ]},
    {"key": "COVID-19", "words": ["covid", "coronavirus", "sars-cov"], "season": None, "products": [
        ("Tests rapides antigéniques", UP, 3),
        ("Antipyrétiques / antalgiques (paracétamol)", UP, 3),
        ("Masques de protection", UP, 2),
        ("Antitussifs et produits ORL", UP, 2),
        ("Gel hydroalcoolique", UP, 2),
        ("Oxymètres de pouls", UP, 1),
    ]},
    {"key": "bronchiolite", "words": ["bronchiolite", "vrs", "respiratoire syncytial"],
     "season": [11, 12, 1, 2], "products": [
        ("Sérum physiologique (lavage nasal)", UP, 3),
        ("Antipyrétiques pédiatriques (paracétamol)", UP, 2),
        ("Mouche-bébés", UP, 1),
    ]},
    {"key": "grippe", "words": ["grippe", "grippal", "influenza", "infections respiratoires"],
     "season": [11, 12, 1, 2, 3], "products": [
        ("Antipyrétiques / antalgiques (paracétamol)", UP, 3),
        ("Antitussifs et sirops", UP, 2),
        ("Décongestionnants et produits ORL", UP, 2),
        ("Vaccins antigrippaux", UP, 2),
        ("Antiviraux (oséltamivir)", UP, 1),
        ("Vitamine C et compléments immunité", UP, 1),
    ]},
    {"key": "rougeole", "words": ["rougeole"], "season": [1, 2, 3, 4, 5], "products": [
        ("Vaccin ROR (rougeole-oreillons-rubéole)", UP, 3),
        ("Antipyrétiques (paracétamol)", UP, 2),
        ("Vitamine A", UP, 2),
    ]},
    {"key": "varicelle", "words": ["varicelle"], "season": [1, 2, 3, 4, 5], "products": [
        ("Antipyrétiques (paracétamol; pas d'AINS)", UP, 2),
        ("Antiprurigineux et émollients", UP, 2),
        ("Antiseptiques cutanés", UP, 1),
    ]},
    {"key": "coqueluche", "words": ["coqueluche"], "season": None, "products": [
        ("Vaccins coqueluche (dTcaP)", UP, 3),
        ("Macrolides (azithromycine)", UP, 2),
    ]},
    {"key": "méningite", "words": ["meningite", "meningocoq"], "season": None, "products": [
        ("Vaccins méningocoque", UP, 3),
        ("Antibiotiques injectables (ceftriaxone)", UP, 2),
        ("Chimioprophylaxie (rifampicine, ciprofloxacine)", UP, 2),
    ]},
    {"key": "choléra", "words": ["cholera"], "season": None, "products": [
        ("Solutés de réhydratation orale (SRO)", UP, 3),
        ("Solutés de perfusion (Ringer lactate)", UP, 3),
        ("Désinfection de l'eau (chlore)", UP, 3),
        ("Antibiotiques (doxycycline, azithromycine)", UP, 2),
        ("Vaccin oral anticholérique", UP, 2),
    ]},
    {"key": "typhoïde", "words": ["typhoide"], "season": None, "products": [
        ("Antibiotiques (ciprofloxacine, azithromycine)", UP, 2),
        ("Vaccin typhoïde", UP, 2),
        ("Solutés de réhydratation orale (SRO)", UP, 1),
    ]},
    {"key": "hépatite A", "words": ["hepatite a", "hepatite virale a"], "season": None, "products": [
        ("Vaccin hépatite A", UP, 2),
        ("Tests de dépistage hépatite A", UP, 1),
        ("Antiseptiques et désinfectants", UP, 1),
    ]},
    {"key": "intoxication alimentaire", "words": ["intoxication", "toxi-infection", "botulisme"],
     "season": [6, 7, 8, 9], "products": [
        ("Solutés de réhydratation orale (SRO)", UP, 2),
        ("Antidiarrhéiques (racécadotril, diosmectite)", UP, 2),
        ("Antiémétiques", UP, 1),
    ]},
    {"key": "gastro-entérite", "words": ["gastro", "diarrh", "rotavirus", "norovirus"],
     "season": [6, 7, 8, 9, 12, 1, 2], "products": [
        ("Solutés de réhydratation orale (SRO)", UP, 3),
        ("Antidiarrhéiques (racécadotril, diosmectite)", UP, 3),
        ("Probiotiques", UP, 2),
        ("Antispasmodiques", UP, 2),
        ("Antiémétiques", UP, 1),
    ]},
    {"key": "canicule", "words": ["canicule", "chaleur", "insolation"], "season": [6, 7, 8, 9], "products": [
        ("Solutés de réhydratation orale (SRO)", UP, 2),
        ("Protection solaire", UP, 2),
        ("Soins des brûlures et après-soleil", UP, 1),
    ]},
    {"key": "piqûres de scorpion", "words": ["scorpion"], "season": [5, 6, 7, 8, 9], "products": [
        ("Sérum antiscorpionique", UP, 3),
        ("Antalgiques", UP, 1),
    ]},
    {"key": "rage", "words": ["rage"], "season": None, "products": [
        ("Vaccin antirabique", UP, 3),
        ("Immunoglobulines antirabiques", UP, 3),
    ]},
    {"key": "leishmaniose", "words": ["leishmani"], "season": None, "products": [
        ("Antimoniate de méglumine (Glucantime)", UP, 2),
        ("Répulsifs anti-insectes", UP, 1),
    ]},
    {"key": "maladies transmises par les moustiques",
     "words": ["west nile", "nil occidental", "dengue", "paludisme", "malaria", "chikungunya", "moustique"],
     "season": [7, 8, 9, 10], "products": [
        ("Répulsifs anti-moustiques", UP, 3),
        ("Moustiquaires et diffuseurs", UP, 2),
        ("Antipyrétiques (paracétamol; pas d'AINS)", UP, 2),
    ]},
    {"key": "allergies saisonnières", "words": ["allergi", "pollen", "rhinite"], "season": [3, 4, 5, 6],
     "products": [
        ("Antihistaminiques", UP, 3),
        ("Corticoïdes nasaux", UP, 2),
        ("Collyres antiallergiques", UP, 2),
    ]},
    {"key": "conjonctivite", "words": ["conjonctivite"], "season": None, "products": [
        ("Collyres antiseptiques et antibiotiques", UP, 3),
        ("Sérum physiologique (lavage oculaire)", UP, 2),
    ]},
    {"key": "gale", "words": ["gale"], "season": None, "products": [
        ("Scabicides (perméthrine, benzoate de benzyle)", UP, 3),
        ("Antihistaminiques (démangeaisons)", UP, 1),
    ]},
    {"key": "poux", "words": ["poux", "pediculose"], "season": [9, 10, 11], "products": [
        ("Produits anti-poux", UP, 3),
    ]},
    {"key": "mpox", "words": ["mpox", "variole du singe", "monkeypox"], "season": None, "products": [
        ("Antiseptiques cutanés", UP, 1),
        ("Gants et matériel de protection", UP, 1),
    ]},
    {"key": "pénurie de médicament", "words": ["penurie", "rupture"], "season": None, "products": [
        ("Médicament concerné (disponibilité)", DOWN, 3),
        ("Génériques et alternatives thérapeutiques", UP, 2),
    ]},
    {"key": "campagne de vaccination", "words": ["vaccination"], "season": None, "products": [
        ("Vaccins concernés (circuit public)", UP, 3),
        ("Antipyrétiques (fièvre post-vaccinale)", UP, 1),
    ]},
]

SEVERITY_FACTOR = {"low": 0.5, "medium": 1.0, "high": 1.5}
TREND_FACTOR = {"rising": 1.2, "falling": 0.8}
NEIGHBOURS = {"libye", "algerie"}
OFFICIAL_SOURCES = {"ONMNE", "WHO Disease Outbreak News"}

# Final score → size of the change. Below the last threshold, the change is negligible.
LEVELS = [(4.0, "strong"), (2.0, "moderate"), (0.8, "slight")]
ARROWS = {"strong": 3, "moderate": 2, "slight": 1}


def _plain(text):
    """Lowercase, no accents: 'Rougeole à Sfax' → 'rougeole a sfax'."""
    text = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def find_disease(name):
    """The DISEASES entry matching Gemini's disease name, or None."""
    plain = _plain(name)
    for disease in DISEASES:
        if any(re.search(rf"\b{re.escape(w)}", plain) for w in disease["words"]):
            return disease
    return None


def _scope(event):
    """Where the event happens → (factor, description)."""
    country = _plain(event["country"])
    places = json.loads(event["governorates"] or "[]")
    if "tunisie" in country or places:
        if not places or any(_plain(p) == "tunisie" for p in places):
            return 1.2, "national (Tunisia)"
        return 1.0, f"local ({', '.join(places)})"
    if any(n in country for n in NEIGHBOURS):
        return 0.5, f"neighbouring country ({event['country']})"
    return 0.2, f"abroad ({event['country'] or '?'})"


def estimate(event, articles):
    """Demand estimate for one event (a database row) and the articles reporting it.

    Returns a dict:
      disease      — the matched disease name, or None if it isn't in the table yet
      products     — [{"category", "direction" (+1/-1), "level" ("slight"/"moderate"/"strong")}]
      confidence   — "low" / "medium" / "high"
      reasons      — what the size of the change is based on
      evidence     — what the confidence is based on
      notes        — warnings worth reading (season, unvalidated mapping...)
    """
    disease = find_disease(event["disease"])
    result = {"disease": disease["key"] if disease else None, "products": [],
              "confidence": "low", "reasons": [], "evidence": [], "notes": []}

    # 1. Size of the change: impact of the disease × severity × where × trend.
    severity = SEVERITY_FACTOR.get(event["severity"], 0.5)
    scope, where = _scope(event)
    trend = TREND_FACTOR.get(event["trend"], 1.0)
    result["reasons"] = [f"severity {event['severity']}", where]
    if event["trend"] in TREND_FACTOR:
        result["reasons"].append(f"trend {event['trend']}")

    if disease is None:
        if scope < 0.5:  # far abroad: no direct effect on Tunisian demand, whatever the disease
            result["notes"].append("No noticeable change expected in Tunisia (event far away).")
        else:
            result["notes"].append(f"'{event['disease']}' is not in the disease → product table yet.")
        return result

    for category, direction, impact in disease["products"]:
        score = impact * severity * scope * trend
        level = next((name for minimum, name in LEVELS if score >= minimum), None)
        if level:
            result["products"].append({"category": category, "direction": direction, "level": level})
    if not result["products"]:
        result["notes"].append("No noticeable change expected in Tunisia (event too small or too far away).")

    # Season: the usual seasonal rise is already partly expected by the market.
    month = datetime.fromisoformat(event["first_seen"]).month
    if disease["season"]:
        if month in disease["season"]:
            result["notes"].append("In season: part of this rise is the usual seasonal peak.")
        else:
            result["notes"].append("Out of season: unusual, stocks are probably not prepared.")

    # 2. Confidence: how solid is the information?
    points = 0
    sources = {a["source"] for a in articles}
    if sources & OFFICIAL_SOURCES:
        points += 2  # an official report counts double
        result["evidence"].append("official source")
    if len(sources) >= 2:
        points += 1
        result["evidence"].append(f"{len(sources)} different outlets")
    else:
        result["evidence"].append("single outlet")
    if event["cases"] is not None or event["deaths"] is not None:
        points += 1
        result["evidence"].append("case numbers reported")
    else:
        result["evidence"].append("no case numbers")
    result["confidence"] = ["low", "low", "medium", "high", "high"][points]
    if not MAPPING_VALIDATED:
        if result["confidence"] == "high":
            result["confidence"] = "medium"
        result["notes"].append("Disease → product table not yet validated by a pharmacist.")
    return result


if __name__ == "__main__":
    import database

    def fake(disease, country, places, severity, trend, cases, month, sources):
        event = {"disease": disease, "country": country, "governorates": json.dumps(places),
                 "severity": severity, "trend": trend, "cases": cases, "deaths": None,
                 "first_seen": f"2026-{month:02d}-15T10:00:00+00:00"}
        return event, [{"source": s} for s in sources]

    examples = [
        fake("rougeole", "Tunisie", ["Sfax"], "high", "rising", 140, 3, ["La Presse", "Mosaïque FM"]),
        fake("grippe saisonnière", "Tunisie", ["Tunisie"], "medium", "rising", None, 1, ["ONMNE"]),
        fake("gastro-entérite", "Tunisie", ["Kairouan"], "medium", "stable", 60, 11, ["Babnet"]),
        fake("choléra", "Libye", [], "high", "rising", 300, 8, ["WHO Disease Outbreak News", "La Presse"]),
        fake("Ebola", "Kenya", [], "low", "unknown", 1, 10, ["Mosaïque FM"]),
    ]
    database.init_db()
    with database.connect() as conn:
        real = [(e, database.get_event_articles(e["id"]))
                for e in conn.execute("SELECT * FROM events ORDER BY id").fetchall()]

    for title, events in [("EXAMPLES (made up)", examples), ("REAL EVENTS IN THE DATABASE", real)]:
        print(f"\n===== {title} =====")
        for event, articles in events:
            est = estimate(event, articles)
            print(f"\n🩺 {event['disease']} — {event['country']} {json.loads(event['governorates'])}"
                  f" — severity {event['severity']}")
            for p in est["products"]:
                arrow = ("⬆️" if p["direction"] == UP else "⬇️") * ARROWS[p["level"]]
                print(f"   {arrow} {p['category']} ({p['level']})")
            print(f"   confidence: {est['confidence']} ({', '.join(est['evidence'])})")
            print(f"   based on: {', '.join(est['reasons'])}")
            for note in est["notes"]:
                print(f"   ℹ️  {note}")
