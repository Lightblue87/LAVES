#!/usr/bin/env python3
"""Build the LAVES labeling rules SQLite database from VO (EG) Nr. 767/2009."""

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
PRAGMA journal_mode = WAL;

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
        "Alleinfuttermittel,Allein-Futtermittel,Alleinfutter,Alleinfutter für,complete pet food",
    ),
    (
        "complementary_feed",
        "Ergänzungsfuttermittel",
        "Mischfuttermittel mit hohem Anteil bestimmter Stoffe",
        "Ergänzungsfuttermittel,Ergaenzungsfuttermittel,Ergänzungsfutter,complementary pet food",
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

def _kw(rule_id: str, keywords: list[str], weight: float = 1.0) -> list[tuple]:
    """Return keyword pattern rows for a rule."""
    return [
        (f"{rule_id}_kw_{i:03d}", rule_id, "keyword", kw, weight, 0)
        for i, kw in enumerate(keywords)
    ]


def _rx(rule_id: str, regexes: list[str], weight: float = 1.0) -> list[tuple]:
    """Return regex pattern rows for a rule."""
    return [
        (f"{rule_id}_rx_{i:03d}", rule_id, "regex", rx, weight, 0)
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

    # art15_002 – Verantwortlicher Unternehmer
    rows += _kw("art15_002", [
        "GmbH",
        "GmbH & Co",
        "AG ",
        " KG",
        " OHG",
        "e.K.",
        "Ltd.",
        "S.A.",
        "Straße",
        "Str.",
        "Weg ",
        "Platz ",
        "verantwortlich:",
        "Hersteller:",
        "Anschrift:",
    ])
    rows += _rx("art15_002", [
        r"\b\d{5}\s+[A-ZÄÖÜ][a-zäöüß]+\b",
    ])

    # art15_003 – Nettomenge
    rows += _rx("art15_003", [
        r"\b\d+[,.]?\d*\s*(kg|g|t|ml|l|Liter|Kilogramm|Gramm)\b",
        r"\b(Nettomasse|Nettogewicht|Nettomenge|Nettofüllmenge|Netto)[\s:]*\d+",
    ])

    # art15_004 – Losnummer
    rows += _kw("art15_004", [
        "Charge",
        "Los:",
        "Partie:",
        "Batch",
        "LOT ",
        "L:",
        "Ch.",
        "Chargennr",
        "Losnr",
        "Partienr",
    ])
    rows += _rx("art15_004", [
        r"\b(LOT|L|Charge|Chargen-Nr\.?|Los|Partie)\s?[:\-]?\s?[A-Z0-9\-\/]+\b",
    ])

    # art15_005 – Feuchtegehalt
    rows += _kw("art15_005", [
        "Feuchte",
        "Feuchtigkeit",
        "Wassergehalt",
        "Feuchtigkeitsgehalt",
        "moisture",
    ])
    rows += _rx("art15_005", [
        r"\b\d+[,.]?\d*\s*%\s*(Feuchte|Feuchtigkeit|Wasser)\b",
    ])

    # art15_006 – Zusatzstoffe
    rows += _kw("art15_006", [
        "Zusatzstoffe",
        "Ernährungsphysiologische Zusatzstoffe",
        "Technologische Zusatzstoffe",
        "Zootechnische Zusatzstoffe",
        "Sensorische Zusatzstoffe",
        "additives",
    ])

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
    _mhd_rx = [
        r"\b(MHD|BBD|mindestens haltbar bis)[:\s]*\d{1,2}[\.\/\-]\d{1,2}[\.\/\-]\d{2,4}\b",
    ]
    rows += _kw("art16_002", _mhd_kw)
    rows += _rx("art16_002", _mhd_rx)

    # art16_003 – Tierart (single_feed, optional)
    rows += _kw("art16_003", [
        "für Hunde", "für Katzen", "für Rinder", "für Kälber", "für Schweine",
        "für Geflügel", "für Pferde", "für Fische", "für Kaninchen",
        "für Schafe", "für Ziegen", "für Hund", "für Katze",
        "Tierart:", "Tierkategorie:",
    ])

    # art17_002_* – Mindesthaltbarkeit (all compound feeds)
    for _, suffix in _COMPOUND_FEEDS:
        rule_id = f"art17_002_{suffix}"
        rows += _kw(rule_id, _mhd_kw)
        rows += _rx(rule_id, _mhd_rx)

    # art17_001_* – Tierart
    _tierart_kw = [
        "für Hunde",
        "für Katzen",
        "für Rinder",
        "für Kälber",
        "für Schweine",
        "für Geflügel",
        "für Pferde",
        "für Fische",
        "für Kaninchen",
        "für Schafe",
        "für Ziegen",
        "für Hund",
        "für Katze",
        "Hunde und Katzen",
        "Tierart:",
        "Tierkategorie:",
    ]
    for _, suffix in _COMPOUND_FEEDS:
        rows += _kw(f"art17_001_{suffix}", _tierart_kw)

    # art17_003_* – Zusammensetzung
    _zusammen_kw = [
        "Zusammensetzung",
        "Zutaten:",
        "Inhaltsstoffe",
        "ingredients",
    ]
    for _, suffix in _COMPOUND_FEEDS:
        rows += _kw(f"art17_003_{suffix}", _zusammen_kw)

    # art17_004_* – Analytische Bestandteile
    _analyt_kw = [
        "Analytische Bestandteile",
        "Rohprotein",
        "Rohfaser",
        "Rohfett",
        "Rohasche",
        "Feuchtigkeit",
        "analytical constituents",
        "crude protein",
        "crude fibre",
    ]
    for _, suffix in _COMPOUND_FEEDS:
        rows += _kw(f"art17_004_{suffix}", _analyt_kw)

    # art17_005_* – Hersteller
    _hersteller_kw = [
        "Hergestellt von",
        "Hersteller:",
        "Hergestellt durch",
        "erzeugt von",
        "produziert von",
        "manufactured by",
    ]
    for _, suffix in _COMPOUND_FEEDS:
        rows += _kw(f"art17_005_{suffix}", _hersteller_kw)

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
            (id, rule_id, pattern_type, pattern_value, confidence_weight,
             is_negative_pattern)
        VALUES (?, ?, ?, ?, ?, ?)
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
        ("labeling_db_version", "2026-05-21"),
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
        description="Build the LAVES labeling rules SQLite database."
    )
    default_out = Path(__file__).parent.parent / "dist" / "laves_labeling.sqlite"
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
