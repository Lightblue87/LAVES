#!/usr/bin/env python3
"""Build the FeedLabelCheck labeling rules SQLite database from VO (EG) Nr. 767/2009."""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA = """
PRAGMA journal_mode = DELETE;

CREATE TABLE IF NOT EXISTS labeling_regulations (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, celex TEXT,
    version_date TEXT, source_url_html TEXT, source_url_pdf TEXT,
    language TEXT NOT NULL DEFAULT 'de', created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS labeling_feed_types (
    id TEXT PRIMARY KEY, name_de TEXT NOT NULL,
    description_de TEXT, keywords_de TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS labeling_rules (
    id TEXT PRIMARY KEY, regulation_id TEXT NOT NULL,
    feed_type_id TEXT NOT NULL, title_de TEXT NOT NULL,
    description_de TEXT NOT NULL, legal_basis TEXT NOT NULL,
    requirement_type TEXT NOT NULL, severity TEXT NOT NULL,
    is_mandatory INTEGER NOT NULL DEFAULT 1,
    display_order INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (regulation_id) REFERENCES labeling_regulations(id),
    FOREIGN KEY (feed_type_id) REFERENCES labeling_feed_types(id)
);

CREATE TABLE IF NOT EXISTS labeling_rule_patterns (
    id TEXT PRIMARY KEY, rule_id TEXT NOT NULL,
    pattern_type TEXT NOT NULL, pattern_value TEXT NOT NULL,
    pattern_language TEXT NOT NULL DEFAULT 'de',
    confidence_weight REAL NOT NULL DEFAULT 1.0,
    is_negative_pattern INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (rule_id) REFERENCES labeling_rules(id)
);

CREATE TABLE IF NOT EXISTS labeling_rule_examples (
    id TEXT PRIMARY KEY, rule_id TEXT NOT NULL,
    example_text_de TEXT NOT NULL, expected_result TEXT NOT NULL,
    FOREIGN KEY (rule_id) REFERENCES labeling_rules(id)
);

CREATE TABLE IF NOT EXISTS labeling_metadata (
    key TEXT PRIMARY KEY, value TEXT NOT NULL
);
"""

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

REGULATION = {
    "id": "reg_767_2009",
    "title": "VO (EG) Nr. 767/2009 über das Inverkehrbringen von Futtermitteln",
    "celex": "02009R0767-20181226",
    "version_date": "2018-12-26",
    "source_url_html": (
        "https://eur-lex.europa.eu/legal-content/DE/TXT/HTML/?uri=CELEX:02009R0767-20181226"
    ),
    "source_url_pdf": (
        "https://eur-lex.europa.eu/legal-content/DE/TXT/PDF/?uri=CELEX:02009R0767-20181226"
    ),
    "language": "de",
}

FEED_TYPES = [
    (
        "all",
        "Alle Futtermittel",
        "Allgemeine Regeln für alle Futtermittelarten",
        "futtermittel",
    ),
    (
        "single_feed",
        "Einzelfuttermittel",
        "Futtermittel pflanzlichen, tierischen oder mineralischen Ursprungs",
        "Einzelfuttermittel",
    ),
    (
        "complete_feed",
        "Alleinfuttermittel",
        "Mischfuttermittel für vollständige Ernährung",
        (
            "Alleinfuttermittel,Allein-Futtermittel,Alleinfutter,Alleinfutter für,"
            "complete pet food,complete feed,alimento completo,aliment complet,volledig diervoeder"
        ),
    ),
    (
        "complementary_feed",
        "Ergänzungsfuttermittel",
        "Mischfuttermittel mit hohem Anteil bestimmter Stoffe",
        (
            "Ergänzungsfuttermittel,Ergaenzungsfuttermittel,Ergänzungsfutter,"
            "complementary pet food,complementary feed,alimento complementare,aliment complémentaire,"
            "aanvullend diervoeder"
        ),
    ),
    (
        "compound_feed",
        "Mischfuttermittel",
        "Mischfuttermittel allgemein",
        "Mischfuttermittel,Mischfutter",
    ),
    (
        "mineral_feed",
        "Mineralfuttermittel",
        "Ergänzungsfuttermittel mit hohem Mineralstoffgehalt",
        "Mineralfuttermittel,Mineralfutter,Mineral-Futtermittel",
    ),
    (
        "milk_replacer",
        "Milchaustauscher",
        "Mischfuttermittel als Milchersatz für Jungtiere",
        "Milchaustauscher,Milch-Austauscher,Tränke,Aufzuchtmilch",
    ),
    (
        "pet_feed",
        "Heimtierfuttermittel",
        "Futtermittel für Heimtiere",
        (
            "Heimtierfutter,Haustierfutter,pet food,Tierfutter für,"
            "Nassfutter,Trockenfutter für Hund,Trockenfutter für Katze"
        ),
    ),
    (
        "unknown",
        "Unbekannt",
        "Futtermittelart nicht erkennbar",
        "",
    ),
]

# Rules for Art. 15 (feed_type_id = 'all')
_ART15_RULES = [
    {
        "id": "art15_001",
        "feed_type_id": "all",
        "title_de": "Futtermittelart",
        "description_de": (
            "Die Art des Futtermittels muss klar angegeben sein "
            "(z.B. Alleinfuttermittel, Ergänzungsfuttermittel, Einzelfuttermittel)."
        ),
        "legal_basis": "Art. 15 Abs. 1 lit. a VO (EG) Nr. 767/2009",
        "requirement_type": "feed_type",
        "severity": "critical",
        "is_mandatory": 1,
        "display_order": 10,
    },
    {
        "id": "art15_002",
        "feed_type_id": "all",
        "title_de": "Verantwortlicher Unternehmer",
        "description_de": (
            "Name/Firma und Anschrift des verantwortlichen Futtermittelunternehmers "
            "müssen angegeben sein."
        ),
        "legal_basis": "Art. 15 Abs. 1 lit. b VO (EG) Nr. 767/2009",
        "requirement_type": "operator",
        "severity": "critical",
        "is_mandatory": 1,
        "display_order": 20,
    },
    {
        "id": "art15_003",
        "feed_type_id": "all",
        "title_de": "Nettomenge",
        "description_de": (
            "Die Nettomasse oder das Nettovolumen muss angegeben sein "
            "(z.B. 10 kg, 500 g, 5 l)."
        ),
        "legal_basis": "Art. 15 Abs. 1 lit. d VO (EG) Nr. 767/2009",
        "requirement_type": "net_quantity",
        "severity": "critical",
        "is_mandatory": 1,
        "display_order": 30,
    },
    {
        "id": "art15_004",
        "feed_type_id": "all",
        "title_de": "Partie-/Losnummer",
        "description_de": (
            "Eine Referenz zur Identifikation der Partie oder Sendung "
            "(Losnummer, Chargennummer) muss angegeben sein."
        ),
        "legal_basis": "Art. 15 Abs. 1 lit. f VO (EG) Nr. 767/2009",
        "requirement_type": "lot_number",
        "severity": "critical",
        "is_mandatory": 1,
        "display_order": 40,
    },
    {
        "id": "art15_005",
        "feed_type_id": "all",
        "title_de": "Feuchtegehalt",
        "description_de": (
            "Der Feuchtegehalt muss angegeben werden, wenn er 14% überschreitet "
            "oder wenn er für die Beurteilung des Futtermittels wesentlich ist."
        ),
        "legal_basis": "Art. 15 Abs. 1 lit. g VO (EG) Nr. 767/2009",
        "requirement_type": "moisture",
        "severity": "warning",
        "is_mandatory": 0,
        "display_order": 50,
    },
    {
        "id": "art15_006",
        "feed_type_id": "all",
        "title_de": "Zusatzstoffe (Kennzeichnungspflicht)",
        "description_de": (
            "Wenn Zusatzstoffe deklarationspflichtig sind, müssen sie unter der "
            "Überschrift „Zusatzstoffe“ aufgeführt werden."
        ),
        "legal_basis": "Art. 15 Abs. 1 lit. h + Art. 22 VO (EG) Nr. 767/2009",
        "requirement_type": "additives",
        "severity": "warning",
        "is_mandatory": 0,
        "display_order": 60,
    },
]

# Rules for Art. 16 (single_feed)
_ART16_RULES = [
    {
        "id": "art16_001",
        "feed_type_id": "single_feed",
        "title_de": "Bezeichnung des Einzelfuttermittels",
        "description_de": (
            "Das Einzelfuttermittel muss mit seiner Bezeichnung gemäß Anhang IV "
            "VO (EG) Nr. 767/2009 oder einer anderweitig vorgeschriebenen Bezeichnung "
            "gekennzeichnet sein."
        ),
        "legal_basis": "Art. 16 Abs. 1 lit. a VO (EG) Nr. 767/2009",
        "requirement_type": "designation",
        "severity": "critical",
        "is_mandatory": 1,
        "display_order": 10,
    },
    {
        "id": "art16_002",
        "feed_type_id": "single_feed",
        "title_de": "Mindesthaltbarkeit",
        "description_de": (
            "Das Mindesthaltbarkeitsdatum muss angegeben werden, "
            "sofern die Haltbarkeit begrenzt ist."
        ),
        "legal_basis": "Art. 16 Abs. 1 lit. f VO (EG) Nr. 767/2009",
        "requirement_type": "best_before",
        "severity": "warning",
        "is_mandatory": 0,
        "display_order": 20,
    },
    {
        "id": "art16_003",
        "feed_type_id": "single_feed",
        "title_de": "Tierart oder Tierkategorie",
        "description_de": (
            "Die Tierart oder Tierkategorie muss angegeben werden, wenn das "
            "Futtermittel für eine bestimmte Tierart oder Tierkategorie bestimmt ist."
        ),
        "legal_basis": "Art. 16 Abs. 1 lit. d VO (EG) Nr. 767/2009",
        "requirement_type": "animal_species",
        "severity": "info",
        "is_mandatory": 0,
        "display_order": 30,
    },
]

# Template rules for Art. 17 (compound-type feeds)
# These are duplicated for each applicable feed type with a suffix.
_ART17_TEMPLATE = [
    {
        "base_id": "art17_001",
        "title_de": "Tierart oder Tierkategorie",
        "description_de": (
            "Die Tierart oder Tierkategorie, für die das Futtermittel bestimmt ist, "
            "muss angegeben sein."
        ),
        "legal_basis": "Art. 17 Abs. 1 lit. a VO (EG) Nr. 767/2009",
        "requirement_type": "animal_species",
        "severity": "critical",
        "is_mandatory": 1,
        "display_order": 10,
    },
    {
        "base_id": "art17_002",
        "title_de": "Mindesthaltbarkeit",
        "description_de": "Das Mindesthaltbarkeitsdatum muss angegeben werden.",
        "legal_basis": "Art. 17 Abs. 1 lit. b VO (EG) Nr. 767/2009",
        "requirement_type": "best_before",
        "severity": "critical",
        "is_mandatory": 1,
        "display_order": 20,
    },
    {
        "base_id": "art17_003",
        "title_de": "Zusammensetzung",
        "description_de": (
            "Die Zutaten müssen unter der Überschrift „Zusammensetzung“ "
            "aufgelistet sein."
        ),
        "legal_basis": "Art. 17 Abs. 1 lit. d VO (EG) Nr. 767/2009",
        "requirement_type": "composition",
        "severity": "critical",
        "is_mandatory": 1,
        "display_order": 30,
    },
    {
        "base_id": "art17_004",
        "title_de": "Analytische Bestandteile",
        "description_de": (
            "Die analytischen Bestandteile (mind. Rohprotein, Rohfett, Rohfaser, "
            "Rohasche) müssen deklariert sein."
        ),
        "legal_basis": "Art. 17 Abs. 1 lit. e VO (EG) Nr. 767/2009",
        "requirement_type": "analytical",
        "severity": "critical",
        "is_mandatory": 1,
        "display_order": 40,
    },
    {
        "base_id": "art17_005",
        "title_de": "Hersteller-Angaben",
        "description_de": (
            "Wenn der Hersteller vom verantwortlichen Unternehmer abweicht, "
            "müssen Name und Anschrift des Herstellers angegeben sein."
        ),
        "legal_basis": "Art. 17 Abs. 1 lit. h VO (EG) Nr. 767/2009",
        "requirement_type": "manufacturer",
        "severity": "info",
        "is_mandatory": 0,
        "display_order": 50,
    },
]

# (feed_type_id, suffix) for compound-type feeds
_COMPOUND_FEEDS = [
    ("complete_feed", "complete"),
    ("complementary_feed", "complementary"),
    ("compound_feed", "compound"),
    ("mineral_feed", "mineral"),
    ("milk_replacer", "milk"),
    ("pet_feed", "pet"),
]


def _build_art17_rules() -> list[dict]:
    rules = []
    for feed_type_id, suffix in _COMPOUND_FEEDS:
        for tmpl in _ART17_TEMPLATE:
            rule = {k: v for k, v in tmpl.items() if k != "base_id"}
            rule["id"] = f"{tmpl['base_id']}_{suffix}"
            rule["feed_type_id"] = feed_type_id
            rules.append(rule)
    return rules


ALL_RULES: list[dict] = _ART15_RULES + _ART16_RULES + _build_art17_rules()


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

def _kw(
    rule_id: str,
    keywords: list[str],
    weight: float = 1.0,
    language: str = "de",
) -> list[tuple]:
    """Return keyword pattern rows for a rule.

    The weight is encoded in the ID so multiple calls with different
    weights for the same rule/language don't produce duplicate PKs.
    """
    w_tag = f"w{int(round(weight * 100)):03d}"
    return [
        (f"{rule_id}_kw_{language}_{w_tag}_{i:03d}", rule_id, "keyword", kw, language, weight, 0)
        for i, kw in enumerate(keywords)
    ]


def _rx(
    rule_id: str,
    regexes: list[str],
    weight: float = 1.0,
    language: str = "de",
) -> list[tuple]:
    """Return regex pattern rows for a rule."""
    w_tag = f"w{int(round(weight * 100)):03d}"
    return [
        (f"{rule_id}_rx_{language}_{w_tag}_{i:03d}", rule_id, "regex", rx, language, weight, 0)
        for i, rx in enumerate(regexes)
    ]


def _build_patterns() -> list[tuple]:
    rows: list[tuple] = []

    # art15_001 – Futtermittelart
    rows += _kw("art15_001", [
        "Alleinfuttermittel",
        "Ergänzungsfuttermittel",
        "Einzelfuttermittel",
        "Mischfuttermittel",
        "Mineralfuttermittel",
        "Milchaustauscher",
        "Heimtierfutter",
        "pet food",
        "complete feed",
        "complementary feed",
    ])
    rows += _kw("art15_001", [
        "complete pet food",
        "complementary pet food",
        "single feed",
        "compound feed",
        "mineral feed",
        "milk replacer",
    ], language="en")
    rows += _kw("art15_001", [
        "alimento completo",
        "alimento complementare",
        "aliment complet",
        "aliment complémentaire",
        "volledig diervoeder",
        "aanvullend diervoeder",
        "karma pełnoporcjowa",
        "karma uzupełniająca",
    ], language="other")

    # art15_002 – Verantwortlicher Unternehmer
    # Concrete company/address indicators → found (1.0)
    rows += _kw("art15_002", [
        "GmbH", "GmbH & Co", "AG ", " KG", " OHG", "e.K.", "Ltd.", "S.A.",
        "Straße", "Str.", "Weg ", "Platz ",
    ])
    # Section labels only → probablyFound (0.7)
    rows += _kw("art15_002", [
        "verantwortlich:", "Hersteller:", "Anschrift:",
    ], weight=0.7)
    # English: concrete statements → found (1.0)
    rows += _kw("art15_002", [
        "manufactured by", "distributed by", "supplied by",
    ], language="en")
    # English: labels → probablyFound (0.7)
    rows += _kw("art15_002", [
        "responsible:", "address:",
    ], weight=0.7, language="en")
    rows += _kw("art15_002", [
        "fabriqué par", "fabrique par", "prodotto da", "distribuito da",
        "geproduceerd door",
    ], weight=0.85, language="other")
    rows += _kw("art15_002", [
        "responsable:", "distribué par", "distribue par",
        "responsabile:", "indirizzo:", "verantwoordelijk:", "adres:",
    ], weight=0.7, language="other")
    rows += _rx("art15_002", [
        r"\b\d{5}\s+[A-ZÄÖÜ][a-zäöüß]+\b",  # German postal code + city
    ])

    # art15_003 – Nettomenge
    rows += _rx("art15_003", [
        r"\b\d+[,.]?\d*\s*(kg|g|t|ml|l|Liter|Kilogramm|Gramm)\b",
        r"\b(Nettomasse|Nettogewicht|Nettomenge|Nettofüllmenge|Netto)[\s:]*\d+",
    ])
    rows += _kw("art15_003", [
        "net weight",
        "net contents",
        "net volume",
    ], weight=0.85, language="en")
    rows += _kw("art15_003", [
        "poids net",
        "contenu net",
        "peso netto",
        "nettogewicht",
        "netto inhoud",
    ], weight=0.85, language="other")

    # art15_004 – Losnummer
    # Keywords are section labels only → probablyFound (0.7)
    # Only the regex (which requires an actual alphanumeric code) → found (1.0)
    # Keywords: section labels → probablyFound (0.7)
    rows += _kw("art15_004", [
        "Charge:", "Los:", "Partie:", "Chargennr", "Losnr", "Partienr",
        "Chargenangabe:", "Kennnummer der Partie", "Losnummer:", "Chargennummer:",
        # Additional real-world variants (proCani, generic EU labels)
        "Zulassungsnummer der Partie",
        "Partienummer",
        "Partie-Nr.",
        "Partie Nr.",
        "Losnummer",   # without colon — complements existing "Losnummer:"
        "Los-Nr.",
        "LOT",         # common EU label abbreviation without code requirement
    ], weight=0.7)
    rows += _kw("art15_004", [
        "Reference number", "batch number", "lot number", "Batch:", "Lot:",
        "Batch No.",
    ], weight=0.7, language="en")
    rows += _kw("art15_004", [
        "numero di riferimento", "numero di lotto", "numéro de lot",
        "numero de lot", "referentienummer",
    ], weight=0.7, language="other")
    # Regex (weight 1.0, de):
    # Pattern 000: short keyword + compact code with at least one digit → found
    #   (?!\w) prevents matching inside compound words (e.g. "Chargenangabe")
    #   \d requirement prevents matching "Partie: siehe Boden-Aufdruck"
    # Pattern 001: long-form labels with space-separated code → found
    #   Covers "Zulassungsnummer der Partie: BAF 1015090925"
    #   Requires at least 4 digits to distinguish from "siehe Boden-Aufdruck" (no digits)
    rows += _rx("art15_004", [
        r"\b(LOT|L|Charge|Chargen-Nr\.?|Los|Partie)(?!\w)\s?[:\-]?\s?[A-Z0-9\-\/]*\d[A-Z0-9\-\/]*\b",
        r"\b(?:Zulassungsnummer|Kennnummer)\s+der\s+Partie\s*[:\-]?\s*"
        r"[A-Z]{1,5}\s*\d{4,}[A-Z0-9]*\b",
    ])
    # Regex 3: EXP + date + trailing alphanumeric code heuristic → probablyFound (0.7)
    # Covers "EXP: 29.11.2026 NU250529H" — the code after the date is likely a batch number
    rows += _rx("art15_004", [
        r"\bEXP\s*:?\s*\d{1,2}[\.\/\-]\d{1,2}[\.\/\-]\d{2,4}\s+[A-Z]{1,4}\d{4,}[A-Z0-9]*\b",
    ], weight=0.7, language="en")

    # art15_005 – Feuchtegehalt
    # Keywords: section labels → probablyFound (0.7); regex with value → found (1.0)
    rows += _kw("art15_005", [
        "Feuchte", "Feuchtigkeit", "Wassergehalt", "Feuchtigkeitsgehalt", "moisture",
    ], weight=0.7)
    rows += _kw("art15_005", [
        "moisture", "humidity", "water content",
    ], weight=0.7, language="en")
    rows += _kw("art15_005", [
        "humidité", "humidite", "umidità", "umidita", "vocht", "wilgotność",
    ], weight=0.7, language="other")
    rows += _rx("art15_005", [
        r"\b\d+[,.]?\d*\s*%\s*(Feuchte|Feuchtigkeit|Wasser)\b",
    ])

    # art15_006 – Zusatzstoffe
    # Section label keywords → probablyFound (0.7)
    rows += _kw("art15_006", [
        "Zusatzstoffe",
        "Zusatzstoff:",    # singular + colon
        "Zusatzstoff",     # singular
        "Ernährungsphysiologische Zusatzstoffe",
        "Technologische Zusatzstoffe",
        "Zootechnische Zusatzstoffe",
        "Sensorische Zusatzstoffe",
        "additives",
    ], weight=0.7)
    # Substance amount / E-number patterns → indirect evidence (0.75 → probablyFound)
    rows += _rx("art15_006", [
        r"\b\d+[,.]?\d*\s*(mg|IE|IU|µg|g)\s*/\s*kg\b",
        r"\bE\s*\d{3,4}[a-z]?\b",
    ], weight=0.75)
    # Structured declaration: substance name + amount + unit → found (0.85)
    # Matches: "Taurin 1.000 mg/kg", "Vitamin A 15.000 IE/kg", "E 300 200 mg/kg"
    # Number formats: integer (1000), thousands with dot (1.000), comma (1,000), space (1 000)
    # Units: mg/kg, IE/kg, IU/kg, µg/kg, g/kg
    rows += _rx("art15_006", [
        # Substance name (min 3-letter word, optionally + 2nd word like "Vitamin A" or "D3")
        r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß\-]{2,}(?:\s+[A-Za-zÄÖÜäöüß0-9][A-Za-zÄÖÜäöüß0-9\-]*)?"
        r"\s+\d[\d\.\,\s]{0,9}\s*(?:mg|IE|IU|µg|g)\s*/\s*kg\b",
        # E-number style: "E 300 200 mg/kg"
        r"\bE\s*\d{3,4}[a-z]?\s+\d[\d\.\,\s]{0,9}\s*(?:mg|IE|IU|µg|g)\s*/\s*kg\b",
    ], weight=0.85)
    rows += _kw("art15_006", [
        "additives", "nutritional additives", "technological additives",
        "sensory additives", "zootechnical additives",
    ], weight=0.7, language="en")
    rows += _kw("art15_006", [
        "additivi", "additifs", "toevoegingsmiddelen", "dodatki",
    ], weight=0.7, language="other")

    # art16_001 – Bezeichnung Einzelfuttermittel (Anhang IV names)
    rows += _kw("art16_001", [
        "Weizen",
        "Gerste",
        "Mais",
        "Hafer",
        "Roggen",
        "Triticale",
        "Soja",
        "Sonnenblume",
        "Raps",
        "Zuckerrübe",
        "Melasse",
        "Fischmehl",
        "Fleischmehl",
        "Molke",
        "Luzerne",
        "Heu",
        "Stroh",
    ])

    # art16_002 – Mindesthaltbarkeit (single_feed)
    _mhd_kw = [
        "Mindesthaltbarkeit",
        "mindestens haltbar bis",
        "MHD",
        "best before",
        "verwendbar bis",
        "haltbar bis",
        "Verbrauch bis",
        "zu verbrauchen bis",
    ]
    _mhd_kw_en = [
        "best before",
        "use before",
        "use by",
        "expiry date",
        "expiration date",
        "EXP:",   # "EXP:" (with colon) is specific enough as keyword
        "BBE",    # Best Before End — common on UK/EU products
    ]
    _mhd_kw_other = [
        "da consumarsi preferibilmente entro",
        "à consommer de préférence avant",
        "a consommer de preference avant",
        "ten minste houdbaar tot",
        "najlepiej spożyć przed",
    ]
    _mhd_rx = [
        # German / general: standard abbreviations + concrete date (DD.MM.YYYY etc.)
        # Includes "haltbar bis" (without "mindestens") for e.g. "-18°C haltbar bis: 09.12.26"
        r"\b(MHD|BBD|mindestens haltbar bis|haltbar bis|verwendbar bis)"
        r"[:\s]*\d{1,2}[\.\/\-]\d{1,2}[\.\/\-]\d{2,4}\b",
        # English / international: EXP / BBE + concrete date
        # Covers "EXP: 29.11.2026" and "BBE 01.03.2027" on multilingual EU labels
        r"\b(EXP|BBE|best before|use before|use by|expiry|expiration)"
        r"[:\s.]*\d{1,2}[\.\/\-]\d{1,2}[\.\/\-]\d{2,4}\b",
    ]
    # Keywords: section labels → probablyFound (0.7); date regex → found (1.0)
    rows += _kw("art16_002", _mhd_kw, weight=0.7)
    rows += _kw("art16_002", _mhd_kw_en, weight=0.7, language="en")
    rows += _kw("art16_002", _mhd_kw_other, weight=0.7, language="other")
    rows += _rx("art16_002", _mhd_rx)

    # art16_003 – Tierart (single_feed, optional)
    _animal_de_rx = [
        r"\bfür\s+(?:[A-Za-zÄÖÜäöüß\-]+\s+){0,4}(Hunde|Hund|Katzen|Katze|Rinder|Kälber|Kaelber|Schweine|Geflügel|Gefluegel|Pferde|Fische|Kaninchen|Schafe|Ziegen)\b",
        r"\b(Hunde|Hund|Katzen|Katze|Rinder|Kälber|Kaelber|Schweine|Geflügel|Gefluegel|Pferde|Fische|Kaninchen|Schafe|Ziegen)\s+(?:adult|ausgewachsen|ausgewachsene|senior|junior)\b",
    ]
    _animal_en_rx = [
        r"\bfor\s+(?:[A-Za-z\-]+\s+){0,4}(dogs?|cats?|cattle|calves|pigs?|poultry|horses?|fish|rabbits?)\b",
    ]
    _animal_other_rx = [
        r"\bper\s+(?:[A-Za-zÀ-ÿ\-]+\s+){0,4}(cani|gatti)\b",
        r"\bpour\s+(?:[A-Za-zÀ-ÿ\-]+\s+){0,4}(chiens|chats)\b",
        r"\bvoor\s+(?:[A-Za-zÀ-ÿ\-]+\s+){0,4}(honden|katten)\b",
        r"\bdla\s+(?:[A-Za-zÀ-ÿ\-]+\s+){0,4}(psów|psow|kotów|kotow)\b",
    ]
    # Concrete species declaration → found (1.0)
    rows += _kw("art16_003", [
        "für Hunde", "für Katzen", "für Rinder", "für Kälber", "für Schweine",
        "für Geflügel", "für Pferde", "für Fische", "für Kaninchen",
        "für Schafe", "für Ziegen", "für Hund", "für Katze",
    ])
    # Section labels → probablyFound (0.7)
    rows += _kw("art16_003", ["Tierart:", "Tierkategorie:"], weight=0.7)
    # Compound species words → probablyFound (0.8)
    rows += _kw("art16_003", [
        "Katzenfutter", "Hundefutter", "Rinderfutter", "Geflügelfutter",
        "Pferdefutter", "Kaninchenfutter", "Katzenahrung", "Hundenahrung",
    ], weight=0.8)
    rows += _rx("art16_003", _animal_de_rx)
    rows += _kw("art16_003", [
        "for dogs", "for cats", "for cattle", "for calves", "for pigs",
        "for poultry", "for horses", "for fish", "for rabbits",
        "animal species:", "feeding recommendation:",
    ], language="en")
    rows += _rx("art16_003", _animal_en_rx, language="en")
    rows += _kw("art16_003", [
        "per cani", "per gatti", "pour chiens", "pour chats",
        "voor honden", "voor katten", "dla psów", "dla kotów",
    ], language="other")
    rows += _rx("art16_003", _animal_other_rx, language="other")

    # art17_002_* – Mindesthaltbarkeit (all compound feeds)
    for _, suffix in _COMPOUND_FEEDS:
        rule_id = f"art17_002_{suffix}"
        rows += _kw(rule_id, _mhd_kw, weight=0.7)
        rows += _kw(rule_id, _mhd_kw_en, weight=0.7, language="en")
        rows += _kw(rule_id, _mhd_kw_other, weight=0.7, language="other")
        rows += _rx(rule_id, _mhd_rx)

    # art17_001_* – Tierart
    _tierart_concrete = [
        "für Hunde", "für Katzen", "für Rinder", "für Kälber", "für Schweine",
        "für Geflügel", "für Pferde", "für Fische", "für Kaninchen",
        "für Schafe", "für Ziegen", "für Hund", "für Katze", "Hunde und Katzen",
    ]
    _tierart_labels = ["Tierart:", "Tierkategorie:"]
    _tierart_compound = [
        "Katzenfutter", "Hundefutter", "Rinderfutter", "Geflügelfutter",
        "Pferdefutter", "Kaninchenfutter", "Katzenahrung", "Hundenahrung",
    ]
    for _, suffix in _COMPOUND_FEEDS:
        rows += _kw(f"art17_001_{suffix}", _tierart_concrete)           # found (1.0)
        rows += _kw(f"art17_001_{suffix}", _tierart_labels, weight=0.7) # probablyFound
        rows += _kw(f"art17_001_{suffix}", _tierart_compound, weight=0.8)  # probablyFound
        rows += _rx(f"art17_001_{suffix}", _animal_de_rx)
        rows += _kw(f"art17_001_{suffix}", [
            "for dogs", "for cats", "for cattle", "for calves", "for pigs",
            "for poultry", "for horses", "for fish", "for rabbits",
        ], language="en")
        rows += _kw(f"art17_001_{suffix}", ["feeding recommendation:"],
                    weight=0.7, language="en")
        rows += _rx(f"art17_001_{suffix}", _animal_en_rx, language="en")
        rows += _kw(f"art17_001_{suffix}", [
            "per cani", "per gatti", "pour chiens", "pour chats",
            "voor honden", "voor katten", "dla psów", "dla kotów",
        ], language="other")
        rows += _rx(f"art17_001_{suffix}", _animal_other_rx, language="other")

    # art17_003_* – Zusammensetzung (section labels → probablyFound 0.7)
    _zusammen_kw = [
        "Zusammensetzung", "Zutaten:", "Inhaltsstoffe", "ingredients",
    ]
    for _, suffix in _COMPOUND_FEEDS:
        rows += _kw(f"art17_003_{suffix}", _zusammen_kw, weight=0.7)
        rows += _kw(f"art17_003_{suffix}", [
            "composition", "ingredients",
        ], weight=0.7, language="en")
        rows += _kw(f"art17_003_{suffix}", [
            "composizione", "composition", "samenstelling", "skład", "sklad",
        ], weight=0.7, language="other")

    # art17_004_* – Analytische Bestandteile
    # Regex: constituent name + numeric value → found (1.0)
    _analyt_value_rx = [
        r"\b(Rohprotein|Rohfett|Rohfaser|Rohasche|Feuchtigkeit|Feuchte|Calcium)"
        r"\s+\d+[,.]?\d*\s*%?\b",
        r"\b(crude protein|crude fat|crude fibre|crude ash|moisture)"
        r"\s+\d+[,.]?\d*\s*%?\b",
    ]
    # Plain section label keywords → probablyFound (0.7)
    _analyt_kw = [
        "Analytische Bestandteile", "Rohprotein", "Rohfaser", "Rohfett",
        "Rohasche", "Feuchtigkeit", "analytical constituents",
        "crude protein", "crude fibre",
    ]
    for _, suffix in _COMPOUND_FEEDS:
        rows += _rx(f"art17_004_{suffix}", _analyt_value_rx)
        rows += _kw(f"art17_004_{suffix}", _analyt_kw, weight=0.7)
        rows += _kw(f"art17_004_{suffix}", [
            "analytical constituents", "crude protein", "crude fat",
            "crude fibre", "crude ash", "moisture",
        ], weight=0.7, language="en")
        rows += _kw(f"art17_004_{suffix}", [
            "componenti analitici", "constituants analytiques",
            "analytische bestanddelen", "składniki analityczne",
            "skladniki analityczne", "proteina grezza",
            "matieres grasses", "teneur en matières grasses",
        ], weight=0.7, language="other")

    # art17_005_* – Hersteller / Vertrieb
    # Declaration phrases + company type indicators combined → found (1.0)
    _hersteller_found = [
        "Hergestellt von", "Hergestellt durch", "erzeugt von", "produziert von",
        "hergestellt für", "im Auftrag von", "importiert durch", "importiert von",
        "GmbH", "GmbH & Co", " KG", " OHG", "AG ", "e.K.", "Ltd.", "S.A.",
    ]
    # Section labels only → probablyFound (0.7)
    _hersteller_labels = ["Hersteller:", "Vertrieb:", "Inverkehrbringer:"]
    for _, suffix in _COMPOUND_FEEDS:
        rows += _kw(f"art17_005_{suffix}", _hersteller_found)
        rows += _kw(f"art17_005_{suffix}", _hersteller_labels, weight=0.7)
        rows += _rx(f"art17_005_{suffix}", [
            r"\b\d{5}\s+[A-ZÄÖÜ][a-zäöüß]+\b",  # postal code + city → found
        ])
        rows += _kw(f"art17_005_{suffix}", [
            "manufactured by", "produced by", "distributed by",
            "imported by", "on behalf of",
        ], language="en")
        rows += _kw(f"art17_005_{suffix}", [
            "fabriqué par", "fabrique par", "prodotto da",
            "distribuito da", "geproduceerd door",
        ], language="other")

    return rows


# ---------------------------------------------------------------------------
# Examples
# ---------------------------------------------------------------------------

def _build_examples() -> list[tuple]:
    rows: list[tuple] = []
    idx = 0

    def ex(rule_id: str, text: str, result: str) -> tuple:
        nonlocal idx
        idx += 1
        return (f"ex_{idx:04d}", rule_id, text, result)

    # art15_003 – Nettomenge
    rows.append(ex("art15_003", "Nettomasse: 10 kg", "found"))
    rows.append(ex("art15_003", "Produktbeschreibung ohne Mengenangabe", "missing"))

    # art15_004 – Losnummer
    rows.append(ex("art15_004", "Charge: A2024-09-01", "found"))
    rows.append(ex("art15_004", "Produktname ohne Chargennummer", "missing"))

    # art17_003_complete – Zusammensetzung
    rows.append(ex(
        "art17_003_complete",
        "Zusammensetzung: Hühnerfleisch (40%), Leber (10%), Karotten",
        "found",
    ))
    rows.append(ex("art17_003_complete", "Rohprotein 8%", "missing"))

    return rows


# ---------------------------------------------------------------------------
# Main build function
# ---------------------------------------------------------------------------

def build(out_path: Path) -> int:
    """Build the database and return the number of rules inserted."""
    if out_path.exists():
        out_path.unlink()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    con = sqlite3.connect(out_path)
    con.executescript(SCHEMA)

    # --- labeling_regulations ---
    con.execute(
        """
        INSERT INTO labeling_regulations
            (id, title, celex, version_date, source_url_html, source_url_pdf,
             language, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            REGULATION["id"],
            REGULATION["title"],
            REGULATION["celex"],
            REGULATION["version_date"],
            REGULATION["source_url_html"],
            REGULATION["source_url_pdf"],
            REGULATION["language"],
            now_iso,
        ),
    )

    # --- labeling_feed_types ---
    con.executemany(
        "INSERT INTO labeling_feed_types (id, name_de, description_de, keywords_de) "
        "VALUES (?, ?, ?, ?)",
        FEED_TYPES,
    )

    # --- labeling_rules ---
    rules_to_insert = [
        (
            r["id"],
            "reg_767_2009",
            r["feed_type_id"],
            r["title_de"],
            r["description_de"],
            r["legal_basis"],
            r["requirement_type"],
            r["severity"],
            r["is_mandatory"],
            r["display_order"],
        )
        for r in ALL_RULES
    ]
    con.executemany(
        """
        INSERT INTO labeling_rules
            (id, regulation_id, feed_type_id, title_de, description_de,
             legal_basis, requirement_type, severity, is_mandatory, display_order)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rules_to_insert,
    )
    rule_count = len(rules_to_insert)

    # --- labeling_rule_patterns ---
    patterns = _build_patterns()
    con.executemany(
        """
        INSERT INTO labeling_rule_patterns
            (id, rule_id, pattern_type, pattern_value, pattern_language, confidence_weight,
             is_negative_pattern)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        patterns,
    )

    # --- labeling_rule_examples ---
    examples = _build_examples()
    con.executemany(
        """
        INSERT INTO labeling_rule_examples
            (id, rule_id, example_text_de, expected_result)
        VALUES (?, ?, ?, ?)
        """,
        examples,
    )

    # --- labeling_metadata (initial, without sha256) ---
    metadata_initial = [
        ("labeling_db_version", "2026-05-22"),
        ("labeling_source_regulation", "VO (EG) Nr. 767/2009"),
        ("labeling_source_celex", "02009R0767-20181226"),
        ("labeling_source_version_date", "2018-12-26"),
        ("labeling_created_at", now_iso),
        ("labeling_rule_count", str(rule_count)),
        ("labeling_sha256", ""),  # placeholder – updated after WAL checkpoint
    ]
    con.executemany(
        "INSERT INTO labeling_metadata (key, value) VALUES (?, ?)",
        metadata_initial,
    )

    con.commit()

    # WAL checkpoint
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()

    # Compute SHA-256 of the written file
    sha256 = hashlib.sha256(out_path.read_bytes()).hexdigest()

    # Update sha256 in metadata
    con2 = sqlite3.connect(out_path)
    con2.execute(
        "UPDATE labeling_metadata SET value = ? WHERE key = 'labeling_sha256'",
        (sha256,),
    )
    con2.commit()
    con2.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con2.close()

    return rule_count


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the FeedLabelCheck labeling rules SQLite database."
    )
    default_out = Path(__file__).parent.parent / "dist" / "labeling.sqlite"
    parser.add_argument(
        "--out",
        type=Path,
        default=default_out,
        help=f"Output path (default: {default_out})",
    )
    args = parser.parse_args()

    rule_count = build(args.out)
    print(f"Wrote {args.out}, {rule_count} rules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
