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

CREATE TABLE IF NOT EXISTS feed_materials (
    catalog_number TEXT PRIMARY KEY,
    chapter INTEGER NOT NULL,
    chapter_name_de TEXT NOT NULL,
    name_de TEXT NOT NULL,
    description_de TEXT,
    mandatory_declarations_de TEXT,
    restrictions_de TEXT,
    regulation TEXT NOT NULL DEFAULT '68/2013'
);

CREATE INDEX IF NOT EXISTS idx_feed_materials_chapter ON feed_materials(chapter);
CREATE INDEX IF NOT EXISTS idx_feed_materials_name ON feed_materials(name_de);

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

# ---------------------------------------------------------------------------
# Feed Materials Catalog – VO (EU) Nr. 68/2013 (Einzelfuttermittelkatalog)
# Tuple: (catalog_number, chapter, chapter_name_de, name_de,
#          description_de, mandatory_declarations_de, restrictions_de)
# ---------------------------------------------------------------------------

_CHAP = {
    1:  "Körner von Getreide und daraus gewonnene Erzeugnisse",
    2:  "Ölsaaten, Ölfrüchte und daraus gewonnene Erzeugnisse",
    3:  "Hülsenfruchtsaaten und daraus gewonnene Erzeugnisse",
    4:  "Knollen, Wurzeln und daraus gewonnene Erzeugnisse",
    5:  "Sonstige Samen und Früchte sowie daraus gewonnene Erzeugnisse",
    6:  "Grünfutter und Raufutter sowie daraus gewonnene Erzeugnisse",
    7:  "Sonstige Pflanzen und daraus gewonnene Erzeugnisse sowie Algen",
    8:  "Milch und Milcherzeugnisse sowie daraus gewonnene Erzeugnisse",
    9:  "Erzeugnisse von Landtieren und daraus gewonnene Erzeugnisse",
    10: "Fische, sonstige Wassertiere und daraus gewonnene Erzeugnisse",
    11: "Mineralstoffe und daraus gewonnene Erzeugnisse",
    12: "Sonstige Erzeugnisse",
}

# (catalog_number, chapter_int, name_de, description_de,
#  mandatory_declarations_de, restrictions_de)
FEED_MATERIALS: list[tuple[str, int, str, str, str, str]] = [
    # ------------------------------------------------------------------ Kap 1
    ("1.1.1",  1, "Gerste", "Körner von Hordeum vulgare L.", "Stärke", "Kann pansengeschützt sein"),
    ("1.1.2",  1, "Gerste, gepufft", "Erzeugnis aus gemahlenem oder gebrochenem Getreide durch feuchte Wärmebehandlung unter Druck", "Stärke", ""),
    ("1.1.3",  1, "Gerste, geröstet", "Teilweise geröstete Gerste mit niedrigem Farbindex", "Stärke", ""),
    ("1.1.4",  1, "Gerstenflocken", "Durch Dämpfen/Mikronisieren und Walzen gewonnenes Erzeugnis", "Stärke", ""),
    ("1.1.5",  1, "Gerstenfaser", "Erzeugnis aus der Gerstenstärkeherstellung", "Rohfaser", ""),
    ("1.1.6",  1, "Gerstenschalen", "Erzeugnis der Gersten-Ethanol-Stärkeherstellung", "Rohfaser", ""),
    ("1.1.7",  1, "Gerste-Futtermehl", "Nebenprodukt der Graupen-/Grieß-/Mehlherstellung", "Rohfaser, Stärke", ""),
    ("1.1.8",  1, "Gerstenprotein", "Erzeugnis aus Gerste nach Abtrennung von Stärke und Kleie", "Rohprotein", ""),
    ("1.1.9",  1, "Gerste-Proteinfutter", "Erzeugnis nach der Naßprotein- und Stärkegewinnung", "Rohprotein, Stärke", ""),
    ("1.1.10", 1, "Gerste-Schlempe, lösliche Bestandteile", "Erzeugnis aus Gerste nach Nass-Eiweiß- und Stärkeextraktion", "Rohprotein", ""),
    ("1.1.11", 1, "Gerstenkleie", "Nebenprodukt der Mehlherstellung", "Rohfaser", ""),
    ("1.1.12", 1, "Gerstestärke, flüssig", "Sekundäre Stärkefraktion", "Stärke (wenn Feuchte < 50 %)", ""),
    ("1.1.13", 1, "Mälzgerstesiebe", "Mechanisch gesiebte Unterkornfraktion aus der Mälzerei", "Rohfaser", ""),
    ("1.1.14", 1, "Mälzgerste und Malzfeinteile", "Kornfraktionen aus der Malzherstellung", "Rohfaser", ""),
    ("1.1.15", 1, "Mälzgerstenschalen", "Schalenfraktionen aus der Mälzereireinigung", "Rohfaser", ""),
    ("1.1.16", 1, "Gersteschlempe, feste Bestandteile, nass", "Feste Fraktion des Ethanol-Nebenprodukts", "Rohprotein", ""),
    ("1.1.17", 1, "Gersteschlempe, lösliche Bestandteile, nass", "Lösliche Fraktion des Ethanol-Nebenprodukts", "Rohprotein", ""),
    ("1.1.18", 1, "Malz", "Erzeugnis aus gekeimtem, getrocknetem Getreide", "", ""),
    ("1.1.19", 1, "Malzkeime", "Keime aus dem Mälzungsprozess", "", ""),
    ("1.2.1",  1, "Mais", "Körner von Zea mays L. ssp. mays", "", "Kann pansengeschützt sein"),
    ("1.2.2",  1, "Maisflocken", "Durch Dämpfen/Mikronisieren und Walzen gewonnenes Erzeugnis", "Stärke", ""),
    ("1.2.3",  1, "Mais-Futtermehl", "Nebenprodukt der Mehl-/Grießherstellung", "Rohfaser, Stärke", ""),
    ("1.2.4",  1, "Maiskleie", "Nebenprodukt der Mehl-/Grießherstellung", "Rohfaser", ""),
    ("1.2.5",  1, "Maisspindeln", "Zentraler Kolben eines Maiskolbens", "Rohfaser, Stärke", ""),
    ("1.2.6",  1, "Maissiebe", "Mechanisch abgetrennte Körner beim Eingang", "", ""),
    ("1.2.7",  1, "Maisfaser", "Erzeugnis der Maisstärkeherstellung", "Rohfaser", ""),
    ("1.2.8",  1, "Maiskleber", "Erzeugnis der Maisstärkeherstellung", "Rohprotein", ""),
    ("1.2.9",  1, "Maiskleberfutter", "Nebenprodukt der Stärkeherstellung", "Rohprotein, Stärke", ""),
    ("1.2.10", 1, "Maiskeime", "Nebenprodukt der Grieß-/Mehl-/Stärkeherstellung", "Rohprotein, Rohfett", ""),
    ("1.2.11", 1, "Maiskeimkuchen", "Pressrückstand der Ölgewinnung", "Rohprotein, Rohfett", ""),
    ("1.2.12", 1, "Maiskeimschrot", "Extraktionsrückstand", "Rohprotein", ""),
    ("1.2.13", 1, "Maiskeimöl, roh", "Extrahiertes Ölerzeugnis", "", "Feuchte > 1 %"),
    ("1.2.14", 1, "Mais, gepufft", "Erzeugnis aus gemahlenem/gebrochenem Mais durch feuchte Wärmebehandlung unter Druck", "Stärke", ""),
    ("1.2.15", 1, "Maisquellwasser", "Konzentrierte Einweichflüssigkeit", "Rohprotein", ""),
    ("1.2.16", 1, "Zuckermaissilage", "Siliertes Nebenprodukt der Verarbeitungsindustrie", "Rohfaser", ""),
    ("1.2.17", 1, "Mais, entkeimter Schrot", "Erzeugnis der Entkeimung", "Rohfaser, Stärke", ""),
    ("1.2.18", 1, "Maisgriess", "Gemahlener Hartteil des Mais", "Rohfaser, Stärke", ""),
    ("1.3.1",  1, "Hirse", "Körner von Panicum miliaceum L.", "", ""),
    ("1.4.1",  1, "Hafer", "Körner von Avena sativa L.", "", ""),
    ("1.4.2",  1, "Hafer, entspelzt", "Entspelztes Korn, gegebenenfalls dampfbehandelt", "", ""),
    ("1.4.3",  1, "Haferflocken", "Durch Dämpfen/Mikronisieren und Walzen gewonnenes Erzeugnis", "Stärke", ""),
    ("1.4.4",  1, "Hafer-Futtermehl", "Nebenprodukt der Aufbereitung", "Rohfaser, Stärke", ""),
    ("1.4.5",  1, "Haferkleie", "Nebenprodukt der Mehlherstellung", "Rohfaser", ""),
    ("1.4.6",  1, "Haferschalen", "Nebenprodukt der Entspelzung", "Rohfaser", ""),
    ("1.4.7",  1, "Hafer, gepufft", "Erzeugnis durch feuchte Wärmebehandlung unter Druck", "Stärke", ""),
    ("1.4.8",  1, "Hafergrütze", "Gereinigter Hafer mit entfernten Spelzen", "Rohfaser, Stärke", ""),
    ("1.4.9",  1, "Hafermehl", "Gemahlenes Haferkorn", "Rohfaser, Stärke", ""),
    ("1.4.10", 1, "Futter-Hafermehl", "Stärkereiche Fraktion nach Entspelzung", "Rohfaser", ""),
    ("1.4.11", 1, "Haferfutter", "Nebenprodukt der Aufbereitung", "Rohfaser", ""),
    ("1.5.1",  1, "Quinoasaat, extrahiert", "Gereinigtes Ganzkorn, Saponin entfernt", "", ""),
    ("1.6.1",  1, "Bruchreis", "Kornteile kleiner als 3/4 der Länge eines ganzen Korns", "Stärke", ""),
    ("1.6.2",  1, "Weißreis", "Entspelzter Reis, Kleie und Keime entfernt", "Stärke", ""),
    ("1.6.3",  1, "Vorgequollener Reis", "Durch Vorquellungsbehandlung gewonnenes Erzeugnis", "Stärke", ""),
    ("1.6.4",  1, "Extrudierter Reis", "Extrudat aus Reismehl", "Stärke", ""),
    ("1.6.5",  1, "Reisflocken", "Erzeugnis aus vorgequollenem Korn", "Stärke", ""),
    ("1.6.6",  1, "Entspelzter Reis", "Paddy-Reis, nur Spelzen entfernt", "Stärke, Rohfaser", ""),
    ("1.6.7",  1, "Futtermittelreis, gemahlen", "Gemahlenes grünes/mehliges/unreifes Korn", "Stärke", ""),
    ("1.6.8",  1, "Reismehl", "Gemahlener Weißreis", "Stärke", ""),
    ("1.6.9",  1, "Entspelzter Reis, Mehl", "Gemahlener entspelzter Reis", "Stärke, Rohfaser", ""),
    ("1.6.10", 1, "Reiskleie", "Äußere Schichten aus der Vermahlung", "Rohfaser", ""),
    ("1.6.11", 1, "Reiskleie mit Calciumcarbonat", "Vermahlungsnebenprodukt mit Verarbeitungshilfsstoff", "Rohfaser, Calciumcarbonat", ""),
    ("1.6.12", 1, "Entölte Reiskleie", "Extraktionsrückstand", "Rohfaser", "Kann pansengeschützt sein"),
    ("1.6.13", 1, "Reiskleieöl", "Extrahiertes Ölerzeugnis aus stabilisierter Kleie", "", ""),
    ("1.6.14", 1, "Reisfutterkleie", "Nebenprodukt der Vermahlung/Siebung", "Stärke, Rohprotein, Rohfett, Rohfaser", ""),
    ("1.6.15", 1, "Reisfutterkleie mit Calciumcarbonat", "Vermahlungsnebenprodukt mit Calciumcarbonat", "Stärke, Rohprotein, Rohfett, Rohfaser, Calciumcarbonat", ""),
    ("1.6.16", 1, "Reis", "Körner von Oryza sativa L.", "", "Kann pansengeschützt sein"),
    ("1.6.17", 1, "Reiskeime", "Keimanteil aus der Vermahlung", "Rohfett, Rohprotein", ""),
    ("1.6.18", 1, "Reiskeimkuchen", "Pressrückstand der Ölgewinnung", "Rohprotein, Rohfett, Rohfaser", ""),
    ("1.6.20", 1, "Reisprotein", "Nebenprodukt der Stärkeherstellung", "Rohprotein", ""),
    ("1.6.21", 1, "Reisfutter, flüssig", "Konzentriertes Nassmahlungsprodukt", "Stärke", ""),
    ("1.6.22", 1, "Reis, gepufft", "Expandiertes Kornerzeugnis", "Stärke", ""),
    ("1.6.23", 1, "Reis, fermentiert", "Fermentiertes Erzeugnis", "Stärke", ""),
    ("1.6.24", 1, "Missgebildeter und mehligkerniger Weißreis", "Vermahlungsnebenprodukt missgebildeter/beschädigter Körner", "Stärke", ""),
    ("1.6.25", 1, "Unreifer Weißreis", "Vermahlungsnebenprodukt unreifer Körner", "Stärke", ""),
    ("1.7.1",  1, "Roggen", "Körner von Secale cereale L.", "", ""),
    ("1.7.2",  1, "Roggen-Futtermehl", "Nebenprodukt der Mehlherstellung", "Stärke, Rohfaser", ""),
    ("1.7.3",  1, "Roggenfutter", "Nebenprodukt der Mehlherstellung", "Stärke, Rohfaser", ""),
    ("1.7.4",  1, "Roggenkleie", "Nebenprodukt der Mehlherstellung", "Stärke, Rohfaser", ""),
    ("1.8.1",  1, "Sorghum", "Körner/Samen von Sorghum bicolor (L.) Moench", "", ""),
    ("1.8.2",  1, "Weißer Sorghum", "Körner eines weißschaligen Sorghum-Kultivars", "", ""),
    ("1.8.3",  1, "Sorghum-Futter", "Getrocknetes Nebenprodukt der Stärketrennung", "Rohprotein", ""),
    ("1.9.1",  1, "Dinkel", "Körner von Triticum spelta L.", "", ""),
    ("1.9.2",  1, "Dinkelkleie", "Nebenprodukt der Mehlherstellung", "Rohfaser", ""),
    ("1.9.3",  1, "Dinkelschalen", "Nebenprodukt der Entspelzung", "Rohfaser", ""),
    ("1.9.4",  1, "Dinkel-Futtermehl", "Nebenprodukt der Aufbereitung", "Rohfaser, Stärke", ""),
    ("1.10.1", 1, "Triticale", "Körner von Triticum × Secale cereale L. Hybride", "", ""),
    ("1.11.1", 1, "Weizen", "Körner von Triticum aestivum L., Triticum durum Desf.", "", "Kann pansengeschützt sein"),
    ("1.11.2", 1, "Weizenkeimling", "Nebenprodukt des Mälzungsprozesses", "", ""),
    ("1.11.3", 1, "Weizen, vorgequollen", "Erzeugnis durch feuchte Wärmebehandlung unter Druck", "Stärke", ""),
    ("1.11.4", 1, "Weizen-Futtermehl", "Nebenprodukt der Mehlherstellung", "Rohfaser, Stärke", ""),
    ("1.11.5", 1, "Weizenflocken", "Durch Dämpfen/Mikronisieren und Walzen gewonnenes Erzeugnis", "Rohfaser, Stärke", "Kann pansengeschützt sein"),
    ("1.11.6", 1, "Weizenfutter", "Nebenprodukt der Mehl-/Mälzungsherstellung", "Rohfaser", ""),
    ("1.11.7", 1, "Weizenkleie", "Nebenprodukt der Mehl-/Mälzungsherstellung", "Rohfaser", ""),
    ("1.11.8", 1, "Malzierte, fermentierte Weizenteilchen", "Kombiniertes Mälzungs-/Fermentierungserzeugnis", "Stärke, Rohfaser", ""),
    ("1.11.10",1, "Weizenfaser", "Extrahiertes Weizenverarbeitungserzeugnis", "Rohfaser", ""),
    ("1.11.11",1, "Weizenkeime", "Erzeugnis der Mehlfabrikation", "Rohprotein, Rohfett", ""),
    ("1.11.12",1, "Weizenkeime, fermentiert", "Fermentiertes Keimerzeugnis", "Rohprotein, Rohfett", ""),
    ("1.11.13",1, "Weizenkeimkuchen", "Pressrückstand der Ölgewinnung", "Rohprotein", ""),
    ("1.11.15",1, "Weizenprotein", "Nebenprodukt der Stärke-/Ethanolherstellung", "Rohprotein", "Kann partiell hydrolysiert sein"),
    ("1.11.16",1, "Weizenkleberfutter", "Nebenprodukt der Stärke-/Kleberherstellung", "Rohprotein, Stärke", ""),
    ("1.11.18",1, "Weizenkleber (vital)", "Mindesteiweiß 80 % in der Trockenmasse", "Rohprotein", ""),
    ("1.11.19",1, "Weizenstärke, flüssig", "Nebenprodukt der Stärke-/Glucose-/Kleberherstellung", "Stärke", ""),
    ("1.11.20",1, "Proteinhaltiger Weizenstärkeanteil, teilverzuckert", "Nebenprodukt der Stärkeherstellung", "Rohprotein, Stärke, Gesamtzucker", ""),
    ("1.11.21",1, "Weizenquellwasser", "Erzeugnis nach Eiweiß-/Stärkeextraktion", "Rohprotein", ""),
    ("1.11.22",1, "Weizenhefenkonzentrat", "Fermentationsnebenprodukt nach Alkoholgewinnung", "Rohprotein", ""),
    ("1.11.23",1, "Mälzweizensiebreste", "Mechanisch gesiebte Unterkornfraktion", "Rohfaser", ""),
    ("1.11.24",1, "Mälzweizen und Malzfeinteile", "Kornfraktionen aus der Malzherstellung", "Rohfaser", ""),
    ("1.11.25",1, "Mälzweizenschalen", "Schalenfraktionen aus der Mälzereireinigung", "Rohfaser", ""),
    ("1.12.2", 1, "Getreidemehl", "Vermahlungsnebenprodukt", "Stärke, Rohfaser", ""),
    ("1.12.3", 1, "Getreideeiweiß-Konzentrat", "Fermentations-/Stärkeentzugsnebenprodukt", "Rohprotein", ""),
    ("1.12.4", 1, "Getreidesiebe", "Mechanisches Sieberzeugnis", "Rohfaser", ""),
    ("1.12.5", 1, "Getreidekeime", "Nebenprodukt der Vermahlung/Stärkeherstellung", "Rohprotein, Rohfett", ""),
    ("1.12.6", 1, "Getreide-Schlempekonzentrat", "Eingedickte Fermentationsschlempe", "Rohprotein", ""),
    ("1.12.7", 1, "Getreideschlempe, feste Bestandteile, nass", "Feste Fraktion aus Fermentation/Destillation", "Rohprotein", ""),
    ("1.12.8", 1, "Getreideschlempe, lösliche Bestandteile, konzentriert", "Alkoholfermentationsnebenprodukt", "Rohprotein", ""),
    ("1.12.9", 1, "Getreideschlempe mit löslichen Bestandteilen", "Getreideschlempe aus Fermentation/Destillation", "Rohprotein", "Kann pansengeschützt sein"),
    ("1.12.10",1, "Getreideschlempe, getrocknet", "Getrockneter Destillationsrückstand", "Rohprotein", "Kann pansengeschützt sein"),
    ("1.12.11",1, "Dunkle Getreideschlempe", "Destillationsrückstand mit Pot-ale-Zusatz", "Rohprotein", "Kann pansengeschützt sein"),
    ("1.12.12",1, "Biertreber", "Rückstand aus dem Brauvorgang", "Rohprotein", "Kann Zusatzstoffe enthalten"),
    ("1.12.13",1, "Maische-Treber (Whisky)", "Fester Rückstand der Whiskyherstellung", "Rohprotein", ""),
    ("1.12.14",1, "Läutertreber", "Rückstand aus Bier-/Malz-/Whiskyherstellung", "Rohprotein", ""),
    ("1.12.15",1, "Schlempe (destilliert)", "Verbleibendes Destillatprodukt nach erster Destillation", "Rohprotein", ""),
    ("1.12.16",1, "Schlempekonzentrat", "Eingedickte Schlempe aus erster Destillation", "Rohprotein", ""),
    # ------------------------------------------------------------------ Kap 2
    ("2.1.1",  2, "Babassukuchen", "Pressrückstand von Babassu-Kernen", "Rohprotein, Rohfett, Rohfaser", ""),
    ("2.2.1",  2, "Leindottersaat", "Samen von Camelina sativa L. Crantz", "", ""),
    ("2.2.2",  2, "Leindotterkuchen", "Pressrückstand", "Rohprotein, Rohfett, Rohfaser", ""),
    ("2.2.3",  2, "Leindotterschrot", "Extraktions-/Wärmebehandlungsrückstand", "Rohprotein", ""),
    ("2.3.1",  2, "Kakaoschalenschrot", "Getrocknete/geröstete Tegumente der Bohnen", "Rohfaser", ""),
    ("2.3.2",  2, "Kakaohülsen", "Verarbeitungsnebenprodukt", "Rohfaser, Rohprotein", ""),
    ("2.3.3",  2, "Kakaobohnenschrot, teilentschält", "Extraktions-/Röstungsnebenprodukt", "Rohprotein, Rohfaser", ""),
    ("2.4.1",  2, "Kopraskuchen", "Pressrückstand von Kokosnusskernen/-hülsen", "Rohprotein, Rohfett, Rohfaser", ""),
    ("2.4.2",  2, "Kopraskuchen, hydrolysiert", "Presse-/Enzymhydrolyse-Nebenprodukt", "Rohprotein, Rohfett, Rohfaser", ""),
    ("2.4.3",  2, "Kopraschrot (Kokosnussschrot)", "Extraktionsrückstand von Kokosnusskernen/-hülsen", "Rohprotein", ""),
    ("2.5.1",  2, "Baumwollsaat", "Samen von Gossypium spp.", "", "Kann pansengeschützt sein"),
    ("2.5.2",  2, "Baumwollsaatschrot, teilentschält", "Extraktionsrückstand, Fasern/Hülsen teilentfernt", "Rohprotein, Rohfaser", "Rohfaser max. 22,5 %"),
    ("2.5.3",  2, "Baumwollsaatkuchen", "Pressrückstand, Fasern entfernt", "Rohprotein, Rohfett, Rohfaser", "Kann pansengeschützt sein"),
    ("2.6.1",  2, "Erdnusskuchen, teilentschält", "Pressrückstand, teilweise entspelzt", "Rohprotein, Rohfett, Rohfaser", "Rohfaser max. 16 %"),
    ("2.6.2",  2, "Erdnussschrot, teilentschält", "Extraktionsrückstand, teilweise entspelzt", "Rohprotein, Rohfaser", "Rohfaser max. 16 %"),
    ("2.6.3",  2, "Erdnusskuchen, entschält", "Pressrückstand, entspelzt", "Rohprotein, Rohfett, Rohfaser", ""),
    ("2.6.4",  2, "Erdnussschrot, entschält", "Extraktionsrückstand, entspelzt", "Rohprotein, Rohfaser", ""),
    ("2.7.1",  2, "Kapok-Kuchen", "Pressrückstand", "Rohprotein, Rohfaser", ""),
    ("2.8.1",  2, "Leinsaat", "Samen von Linum usitatissimum L.", "", "Kann pansengeschützt sein; Botanische Reinheit mind. 93 %"),
    ("2.8.2",  2, "Leinsaatkuchen", "Pressrückstand", "Rohprotein, Rohfett, Rohfaser", ""),
    ("2.8.3",  2, "Leinsaatschrot", "Extraktions-/Wärmebehandlungsrückstand", "Rohprotein", "Kann pansengeschützt sein"),
    ("2.8.4",  2, "Leinsaatkuchen-Futter", "Pressrückstand mit Verarbeitungshilfsstoffen", "Rohprotein, Rohfett, Rohfaser", ""),
    ("2.8.5",  2, "Leinsaatschrot-Futter", "Extraktions-/Wärmebehandlungsrückstand mit Hilfsstoffen", "Rohprotein", ""),
    ("2.9.1",  2, "Senfkleie", "Äußere Schichten aus der Herstellung", "Rohfaser", ""),
    ("2.9.2",  2, "Senfschrot", "Rückstand nach Extraktion des flüchtigen Öls", "Rohprotein", ""),
    ("2.10.1", 2, "Nigerssaat", "Samen von Guizotia abyssinica", "", ""),
    ("2.10.2", 2, "Nigersaatkuchen", "Pressrückstand", "Rohprotein, Rohfett, Rohfaser", "Säureunlösliche Asche max. 3,4 %"),
    ("2.11.1", 2, "Oliventrester", "Erzeugnis aus gepressten Oliven", "Rohprotein, Rohfaser, Rohfett", ""),
    ("2.11.2", 2, "Entölter Oliventrester-Futter", "Extraktions-/Wärmebehandlungsrückstand mit Hilfsstoffen", "Rohprotein, Rohfaser", ""),
    ("2.11.3", 2, "Entölter Oliventrester", "Extraktions-/Wärmebehandlungsrückstand", "Rohprotein, Rohfaser", ""),
    ("2.12.1", 2, "Palmkernkuchen", "Pressrückstand von Palmkernen", "Rohprotein, Rohfaser, Rohfett", ""),
    ("2.12.2", 2, "Palmkernschrot", "Extraktionsrückstand von Palmkernen", "Rohprotein, Rohfaser", ""),
    ("2.13.1", 2, "Kürbis- und Zucchinisamen", "Samen von Cucurbita pepo L.", "", ""),
    ("2.13.2", 2, "Kürbissaatkuchen", "Pressrückstand", "Rohprotein, Rohfett", ""),
    ("2.14.1", 2, "Rapssaat", "Samen von Brassica napus L. ssp. oleifera", "", "Kann pansengeschützt sein; Botanische Reinheit mind. 94 %"),
    ("2.14.2", 2, "Rapskuchen", "Pressrückstand", "Rohprotein, Rohfett, Rohfaser", "Kann pansengeschützt sein"),
    ("2.14.3", 2, "Rapsextraktionsschrot", "Extraktions-/Wärmebehandlungsrückstand", "Rohprotein", "Kann pansengeschützt sein"),
    ("2.14.4", 2, "Rapssaat, extrudiert", "Erzeugnis durch feuchte Wärmebehandlung unter Druck", "Rohprotein, Rohfett", "Kann pansengeschützt sein"),
    ("2.14.5", 2, "Rapsprotein-Konzentrat", "Erzeugnis aus Proteinfraktionierung", "Rohprotein", ""),
    ("2.14.6", 2, "Rapskuchen-Futter", "Pressrückstand mit Verarbeitungshilfsstoffen", "Rohprotein, Rohfett, Rohfaser", ""),
    ("2.14.7", 2, "Rapsschrot-Futter", "Extraktionsrückstand mit Verarbeitungshilfsstoffen", "Rohprotein", ""),
    ("2.15.1", 2, "Safloersaat", "Samen von Carthamus tinctorius L.", "", ""),
    ("2.15.2", 2, "Saflörschrot, teilentschält", "Extraktionsrückstand, teilweise entspelzt", "Rohprotein, Rohfaser", ""),
    ("2.15.3", 2, "Saflor-Schalen", "Nebenprodukt der Entspelzung", "Rohfaser", ""),
    ("2.16.1", 2, "Sesamsaat", "Samen von Sesamum indicum L.", "", ""),
    ("2.17.1", 2, "Sesamsaat, teilentschält", "Teilentschältes Erzeugnis", "Rohprotein, Rohfaser", ""),
    ("2.17.2", 2, "Sesamschalen", "Nebenprodukt der Entspelzung", "Rohfaser", ""),
    ("2.17.3", 2, "Sesamkuchen", "Pressrückstand", "Rohprotein, Rohfaser, Rohfett", "Säureunlösliche Asche max. 5 %"),
    ("2.18.1", 2, "Sojabohnen, getoastet", "Wärmebehandelte Sojabohnen", "", "Kann pansengeschützt sein; Ureaseaktivität max. 0,4 mg N/g × min"),
    ("2.18.2", 2, "Sojakuchen", "Pressrückstand", "Rohprotein, Rohfett, Rohfaser", ""),
    ("2.18.3", 2, "Sojaextraktionsschrot", "Extraktions-/Wärmebehandlungsrückstand", "Rohprotein", "Rohfaser > 8 % i. d. TM; Ureaseaktivität max. 0,4 mg N/g × min"),
    ("2.18.4", 2, "Sojaextraktionsschrot, entschält", "Extraktions-/Wärmebehandlungsrückstand, entschält", "Rohprotein", "Kann pansengeschützt sein; Ureaseaktivität max. 0,5 mg N/g × min"),
    ("2.18.5", 2, "Sojabohnenschalen", "Nebenprodukt der Entspelzung", "Rohfaser", ""),
    ("2.18.6", 2, "Sojabohnen, extrudiert", "Erzeugnis durch feuchte Wärmebehandlung unter Druck", "Rohprotein, Rohfett", "Kann pansengeschützt sein"),
    ("2.18.7", 2, "Sojaeiweiß-Konzentrat", "Proteinfraktion nach Trennung", "Rohprotein", ""),
    ("2.18.8", 2, "Sojatrester", "Extraktionsnebenprodukt der Lebensmittelherstellung", "Rohprotein", ""),
    ("2.18.9", 2, "Sojamelasse", "Verarbeitungsnebenprodukt", "Rohprotein, Rohfett", ""),
    ("2.18.10",2, "Nebenerzeugnisse der Sojaverarbeitung", "Lebensmittelherstellungsnebenprodukt", "Rohprotein", ""),
    ("2.18.11",2, "Sojabohnen", "Sojabohnen (Glycine max L. Merr.)", "", "Ureaseaktivität > 0,4 mg N/g × min anzugeben"),
    ("2.18.12",2, "Sojaflocken", "Durch Dämpfen/Mikronisieren gewonnenes Erzeugnis", "Rohprotein", "Ureaseaktivität max. 0,4 mg N/g × min"),
    ("2.18.13",2, "Sojaextraktionsschrot-Futter", "Extraktionsrückstand mit Verarbeitungshilfsstoffen", "Rohprotein", "Rohfaser > 8 % i. d. TM"),
    ("2.18.14",2, "Sojaextraktionsschrot-Futter, entschält", "Extraktionsrückstand, entschält, mit Hilfsstoffen", "Rohprotein", ""),
    ("2.18.15",2, "Sojaprotein, fermentiert", "Mikrobielle Fermentationsnebenprodukt", "Rohprotein", ""),
    ("2.19.1", 2, "Sonnenblumensaat", "Samen von Helianthus annuus L.", "", "Kann pansengeschützt sein"),
    ("2.19.2", 2, "Sonnenblumenkuchen", "Pressrückstand", "Rohprotein, Rohfett, Rohfaser", ""),
    ("2.19.3", 2, "Sonnenblumenschrot", "Extraktions-/Wärmebehandlungsrückstand", "Rohprotein, Rohfaser", "Kann pansengeschützt sein"),
    ("2.19.4", 2, "Sonnenblumenschrot, entschält", "Extraktions-/Wärmebehandlungsrückstand, entschält", "Rohprotein, Rohfaser", "Rohfaser max. 27,5 %"),
    ("2.19.5", 2, "Sonnenblumenschalen", "Nebenprodukt der Entspelzung", "Rohfaser", ""),
    ("2.19.6", 2, "Sonnenblumenschrot-Futter", "Extraktionsrückstand mit Verarbeitungshilfsstoffen", "Rohprotein", ""),
    ("2.19.7", 2, "Sonnenblumenschrot-Futter, entschält", "Extraktionsrückstand, entschält, mit Hilfsstoffen", "Rohprotein, Rohfaser", "Rohfaser max. 27,5 %"),
    ("2.19.8", 2, "Sonnenblumenschrot, eiweißreich und zellulosearm", "Mahlerzeugnis mit hohem Eiweiß-/niedrigem Rohfasergehalt", "Rohprotein, Rohfaser", "Rohprotein mind. 45 %; Rohfaser max. 8 %"),
    ("2.19.9", 2, "Sonnenblumenschrot, zellulosereich", "Mahlerzeugnis mit hohem Rohfasergehalt", "Rohprotein, Rohfaser", "Rohfaser mind. 38 %; Rohprotein mind. 17 %"),
    ("2.20.1", 2, "Pflanzliche Öle und Fette", "Extrahiertes/verarbeitetes Erzeugnis aus Ölsaaten", "", "Feuchte > 1 %"),
    ("2.20.2", 2, "Pflanzliche Öle, gebraucht (aus Lebensmittelherstellung)", "Aus der Lebensmittelherstellung stammende Öle ohne Fleisch-/Fettkontakt", "", "Feuchte > 1 %"),
    ("2.21.1", 2, "Rohes Lecithin", "Nebenprodukt der Ölentrubung (Degumming)", "", ""),
    ("2.22.1", 2, "Hanfsaat", "Kontrollierte Samen von Cannabis sativa L.", "", "Einhaltung THC-Höchstgehalte gemäß VO (EG) Nr. 1782/2003"),
    ("2.22.2", 2, "Hanfkuchen", "Pressrückstand", "Rohprotein, Rohfaser", ""),
    ("2.22.3", 2, "Hanföl", "Gepresstes Pflanzen-/Samenöl", "", "Feuchte > 1 %"),
    ("2.23.1", 2, "Mohnsaat", "Samen von Papaver somniferum L.", "", ""),
    ("2.23.2", 2, "Mohnschrot", "Extraktionsrückstand", "Rohprotein", ""),
    # ------------------------------------------------------------------ Kap 3
    ("3.1.1",  3, "Bohnen, getoastet", "Wärmebehandelte Samenkörner", "", "Geeignete Wärmebehandlung erforderlich; Kann pansengeschützt sein"),
    ("3.1.2",  3, "Bohneneiweiß-Konzentrat", "Erzeugnis nach Stärketrennung", "Rohprotein", ""),
    ("3.2.1",  3, "Johannisbrotschoten", "Getrocknete Früchte von Ceratonia siliqua L.", "Rohfaser", ""),
    ("3.2.3",  3, "Johannisbrot, geschrotet", "Zerkleinerte getrocknete Frucht ohne Samen", "Rohfaser", ""),
    ("3.2.4",  3, "Johannisbrotpulver", "Mikronisierte getrocknete Frucht", "Rohfaser, Gesamtzucker", ""),
    ("3.2.5",  3, "Johannisbrotkeime", "Keimerzeugnis", "Rohprotein", ""),
    ("3.2.6",  3, "Johannisbrotkeimkuchen", "Pressrückstand der Ölgewinnung", "Rohprotein", ""),
    ("3.2.7",  3, "Johannisbrotsamen", "Samen inkl. Endosperm, Schale und Keim", "Rohfaser", ""),
    ("3.2.8",  3, "Johannisbrotsamen-Schalen", "Nebenprodukt der Entspelzung", "Rohfaser", ""),
    ("3.3.1",  3, "Kichererbsen", "Samen von Cicer arietinum L.", "", ""),
    ("3.4.1",  3, "Wicken (Ervil)", "Samen von Ervum ervilia L.", "", ""),
    ("3.5.1",  3, "Bockshornkleesamen", "Samen von Trigonella foenum-graecum", "", ""),
    ("3.6.1",  3, "Guarkernmehl", "Erzeugnis nach Schleimentzug", "Rohprotein", ""),
    ("3.6.2",  3, "Guarkernkeimmehl", "Keimnebenprodukt nach Schleimentzug", "Rohprotein", ""),
    ("3.7.1",  3, "Pferdebohnen (Ackerbohnen)", "Samen von Vicia faba L. ssp. faba", "", ""),
    ("3.7.2",  3, "Pferdebohnenflocken", "Gedämpftes/mikronisiertes und gewalztes Korn", "Stärke, Rohprotein", ""),
    ("3.7.3",  3, "Pferdebohnenschalen", "Äußere Hülle nach Entspelzung", "Rohfaser, Rohprotein", ""),
    ("3.7.4",  3, "Pferdebohnen, entschält", "Entspelztes Samenkorn", "Rohprotein, Rohfaser", ""),
    ("3.7.5",  3, "Pferdbohnen-Eiweiß", "Erzeugnis nach Mahlung/Windsichtung", "Rohprotein", ""),
    ("3.8.1",  3, "Linsen", "Samen von Lens culinaris Medik.", "", ""),
    ("3.8.2",  3, "Linsenschalen", "Nebenprodukt der Entspelzung", "Rohfaser", ""),
    ("3.9.1",  3, "Süße Lupinen", "Samen von Lupinus spp. mit niedrigem Bittergehalt", "", ""),
    ("3.9.2",  3, "Süße Lupinen, entschält", "Entspelztes Samenkorn", "Rohprotein", ""),
    ("3.9.3",  3, "Lupinenfilm (Schalen)", "Äußere Hülle nach Entspelzung", "Rohprotein, Rohfaser", ""),
    ("3.9.4",  3, "Lupinentrester", "Nebenprodukt der Komponentenextraktion", "Rohfaser", ""),
    ("3.9.5",  3, "Lupinen-Futtermehl", "Nebenprodukt der Mehlherstellung", "Rohprotein, Rohfaser", ""),
    ("3.9.6",  3, "Lupineneiweiß", "Erzeugnis aus Fruchtwassertrennung/Fraktionierung", "Rohprotein", "Kann partiell hydrolysiert sein"),
    ("3.9.7",  3, "Lupineneiweiß-Mehl", "Eiweißreiche Mehlverarbeitungsnebenprodukt", "Rohprotein", ""),
    ("3.10.1", 3, "Mungbohnen", "Bohnen von Vigna radiata L.", "", ""),
    ("3.11.1", 3, "Erbsen", "Samen von Pisum spp.", "", "Kann pansengeschützt sein"),
    ("3.11.2", 3, "Erbsenkleie (Schalen)", "Äußere Hülle nach Mehlherstellung", "Rohfaser", ""),
    ("3.11.3", 3, "Erbsenflocken", "Gedämpftes/mikronisiertes und gewalztes Korn", "Stärke", ""),
    ("3.11.4", 3, "Erbsenmehl", "Mahlungserzeugnis", "Rohprotein", ""),
    ("3.11.5", 3, "Erbsenschalen", "Äußere Hülle nach Mehlherstellung", "Rohfaser", ""),
    ("3.11.6", 3, "Erbsen, entschält", "Entspelztes Samenkorn", "Rohprotein, Rohfaser", ""),
    ("3.11.7", 3, "Erbsen-Futtermehl", "Nebenprodukt der Mehlherstellung", "Rohprotein, Rohfaser", ""),
    ("3.11.8", 3, "Erbsensiebe", "Mechanische Sieberzeugnis", "Rohfaser", ""),
    ("3.11.9", 3, "Erbseneiweiß", "Erzeugnis aus Fruchtwassertrennung/Fraktionierung", "Rohprotein", "Kann partiell hydrolysiert sein"),
    ("3.11.10",3, "Erbsentrester", "Nass-Extraktionsnebenprodukt der Stärke-/Eiweißgewinnung", "Stärke, Rohfaser", ""),
    ("3.11.11",3, "Erbsenquellwasser", "Nass-Extraktionsnebenprodukt", "Gesamtzucker, Rohprotein", ""),
    ("3.11.12",3, "Erbsenfaser", "Extraktions-/Mahlungs-/Siebungsnebenprodukt", "Rohfaser", ""),
    ("3.12.1", 3, "Saatwicken", "Samen von Vicia sativa L. var. sativa", "", ""),
    ("3.13.1", 3, "Platterbsen (Kicherling)", "Wärmebehandelte Samen", "", "Geeignete Wärmebehandlung erforderlich"),
    ("3.14.1", 3, "Einblütige Wicke", "Samen von Vicia monanthos Desf.", "", ""),
    # ------------------------------------------------------------------ Kap 4
    ("4.1.1",  4, "Zuckerrüben", "Wurzel von Beta vulgaris L. ssp. vulgaris", "", ""),
    ("4.1.2",  4, "Zuckerrübenköpfe und -schwänze", "Frisches Herstellungsnebenprodukt", "", ""),
    ("4.1.3",  4, "Zucker (aus Zuckerrüben)", "Wässriges Extraktionserzeugnis", "", ""),
    ("4.1.4",  4, "Zuckerrübenmelasse", "Sirupartiges Nebenprodukt der Herstellung/Raffinierung", "Gesamtzucker", ""),
    ("4.1.5",  4, "Zuckerrübenmelasse, teilentzuckert und/oder entbetainisiert", "Nebenprodukt nach weiterer Wasserextraktion", "Gesamtzucker", ""),
    ("4.1.6",  4, "Isomaltulosemelasse", "Enzymatisch konvertierte, nicht kristallisierte Fraktion", "", "Feuchte > 40 %"),
    ("4.1.7",  4, "Zuckerrübenschnitzel, nass", "Zuckerextraktions-Nass-Nebenprodukt", "", "Feuchte 82–92 %"),
    ("4.1.8",  4, "Zuckerrübenschnitzel, gepresst", "Extraktions-/Pressnebenprodukt", "", "Feuchte 65–82 %"),
    ("4.1.9",  4, "Zuckerrübenschnitzel, gepresst und melassiert", "Extraktions-/Pressnebenprodukt mit Melasseanteil", "", "Feuchte 65–82 %"),
    ("4.1.10", 4, "Zuckerrübenschnitzel, getrocknet", "Extraktions-/Press-/Trocknungsnebenprodukt", "Gesamtzucker", ""),
    ("4.1.11", 4, "Zuckerrübenschnitzel, getrocknet und melassiert", "Extraktions-/Press-/Trocknungsnebenprodukt mit Melasse", "Gesamtzucker", ""),
    ("4.1.12", 4, "Zuckersirup", "Verarbeitungserzeugnis", "Gesamtzucker", ""),
    ("4.1.13", 4, "Zuckerrüben-Stücke, gekocht", "Nebenprodukt der Speisesirupherstellung", "", ""),
    ("4.1.14", 4, "Fructooligosaccharide", "Enzymatisches Verarbeitungsnebenprodukt", "", ""),
    ("4.1.15", 4, "Zuckerrübenmelasse, betainreich, flüssig/getrocknet", "Extraktions-/Filtrierungsnebenprodukt mit hohem Betaingehalt", "Betaingehalt, Gesamtzucker", ""),
    ("4.1.16", 4, "Isomaltulose", "Kristallines enzymatisches Konversionserzeugnis", "", ""),
    ("4.2.1",  4, "Rote-Bete-Saft", "Erzeugnis aus Press-/Konzentrations-/Pasteurisierungsverfahren", "", ""),
    ("4.3.1",  4, "Möhren (Karotten)", "Wurzel von Daucus carota L.", "", ""),
    ("4.3.2",  4, "Möhrenschalen, gedämpft", "Dampfbehandelte Schalen aus der Verarbeitung", "", "Feuchte > 97 %"),
    ("4.3.3",  4, "Möhren-Schaber-Produkt", "Mechanisches Trennungsnebenprodukt", "", "Kann wärmebehandelt sein"),
    ("4.3.4",  4, "Möhrenflocken", "Trocknungs-/Flockungs-Verarbeitungserzeugnis", "", ""),
    ("4.3.5",  4, "Möhren, getrocknet", "Trocknungserzeugnis", "Rohfaser", ""),
    ("4.3.6",  4, "Möhrenfutter, getrocknet", "Getrocknetes Innen-/Außenschalenerzeugnis", "Rohfaser", ""),
    ("4.4.1",  4, "Chicorée-Wurzel", "Wurzeln von Cichorium intybus L.", "", ""),
    ("4.4.2",  4, "Chicorée-Köpfe und -schwänze", "Frisches Verarbeitungsnebenprodukt", "", ""),
    ("4.4.3",  4, "Chicorée-Samen", "Samen von Cichorium intybus L.", "", ""),
    ("4.4.4",  4, "Chicorée-Trester, gepresst", "Inulinherstellungs-Extraktions-/Pressnebenprodukt", "Rohfaser", ""),
    ("4.4.5",  4, "Chicorée-Trester, getrocknet", "Inulinherstellungs-Trocknungsnebenprodukt", "Rohfaser", ""),
    ("4.4.6",  4, "Chicorée-Wurzelpulver", "Zerkleinerungs-/Trocknungs-/Mahlerzeugnis", "Rohfaser", ""),
    ("4.4.7",  4, "Chicorée-Melasse", "Inulin-/Verarbeitungsnebenprodukt", "Rohprotein, Rohfaser", "Feuchte 20–30 %"),
    ("4.4.8",  4, "Chicorée-Vinasse", "Inulin-/Oligofructosetrennerzeugnis", "Rohprotein, Rohfaser", "Feuchte 30–40 %"),
    ("4.4.9",  4, "Inulin", "Wässriges Wurzelextraktionserzeugnis", "", ""),
    ("4.4.10", 4, "Oligofructose-Sirup", "Erzeugnis aus partieller Hydrolyse von Inulin", "", "Feuchte 20–30 %"),
    ("4.4.11", 4, "Oligofructose, getrocknet", "Erzeugnis aus partieller Hydrolyse/Trocknung von Inulin", "", ""),
    ("4.5.1",  4, "Knoblauch, getrocknet", "Weißes bis gelbliches Pulver von Allium sativum L.", "", ""),
    ("4.6.1",  4, "Maniok", "Wurzeln von Manihot esculenta Crantz", "", "Feuchte 60–70 %"),
    ("4.6.2",  4, "Maniok, getrocknet", "Getrocknetes Wurzelerzeugnis", "Stärke", ""),
    ("4.7.1",  4, "Zwiebeltrester", "Nebenprodukt der Verarbeitung", "Rohfaser", "Feuchte max. 97 %"),
    ("4.7.2",  4, "Zwiebeln, frittiert", "Geschälte/gebröckelte/frittierte Stücke", "Rohfaser, Rohfett", ""),
    ("4.7.3",  4, "Zwiebelextrakt, getrocknet", "Extraktions-/Sprühtrocknungsnebenprodukt", "Rohfaser", ""),
    ("4.8.1",  4, "Kartoffeln", "Knollen von Solanum tuberosum L.", "", "Feuchte 72–88 %"),
    ("4.8.2",  4, "Kartoffeln, geschält", "Dampfgeschältes Knollenerzeugnis", "Stärke, Rohfaser", ""),
    ("4.8.3",  4, "Kartoffelschalen, gedämpft", "Dampf-Schäl-Nebenprodukt", "", "Feuchte > 93 %"),
    ("4.8.4",  4, "Kartoffelschnitzel, roh", "Zubereitungsverarbeitungsnebenprodukt", "", "Feuchte > 88 %"),
    ("4.8.5",  4, "Kartoffelschaber-Produkt", "Mechanisches Trennungsnebenprodukt", "", "Feuchte > 93 %; Kann wärmebehandelt sein"),
    ("4.8.6",  4, "Kartoffeln, püriert", "Blanchiertes/gekochtes/püriertes Erzeugnis", "Stärke, Rohfaser", ""),
    ("4.8.7",  4, "Kartoffelflocken", "Walzentrocknungserzeugnis", "Stärke, Rohfaser", ""),
    ("4.8.8",  4, "Kartoffeltrester", "Extrahiertes gemahlenes Stärkeherstellungsnebenprodukt", "", "Feuchte 77–88 %"),
    ("4.8.9",  4, "Kartoffeltrester, getrocknet", "Stärkeherstellungs-Trocknungsnebenprodukt", "", ""),
    ("4.8.10", 4, "Kartoffeleiweiß", "Stärkeherstellungs-Eiweißtrennerzeugnis", "Rohprotein", ""),
    ("4.8.11", 4, "Kartoffeleiweiß, hydrolysiert", "Enzymatisches Hydrolyseeiweiß", "Rohprotein", ""),
    ("4.8.12", 4, "Kartoffeleiweiß, fermentiert", "Fermentiertes/sprühgetrocknetes Eiweißerzeugnis", "Rohprotein", ""),
    ("4.8.13", 4, "Kartoffeleiweiß, fermentiert, flüssig", "Flüssiges fermentiertes Eiweißerzeugnis", "Rohprotein", ""),
    ("4.8.14", 4, "Kartoffelsaft, konzentriert", "Eingedickte Stärkeherstellungskonzentrat", "Rohprotein", "Feuchte 50–60 %"),
    ("4.8.15", 4, "Kartoffelgranulat", "Wasch-/Schäl-/Trocknungs-/Reduktionserzeugnis", "", ""),
    ("4.9.1",  4, "Süßkartoffel", "Knollen von Ipomoea batatas L.", "", "Feuchte 57–78 %"),
    ("4.10.1", 4, "Topinambur", "Knollen von Helianthus tuberosus L.", "", "Feuchte 75–80 %"),
    # ------------------------------------------------------------------ Kap 5
    ("5.1.1",  5, "Eicheln", "Ganze Eichelfrucht", "", ""),
    ("5.1.2",  5, "Eicheln, entschält", "Entspelztes Erzeugnis", "Rohprotein, Rohfaser", ""),
    ("5.2.1",  5, "Mandeln", "Ganze oder gebrochene Frucht von Prunus dulcis", "", ""),
    ("5.2.2",  5, "Mandelschalen", "Nebenprodukt der Entspelzung", "Rohfaser", ""),
    ("5.2.3",  5, "Mandelkuchen", "Pressrückstand der Kernöl-Gewinnung", "Rohprotein, Rohfaser", ""),
    ("5.3.1",  5, "Anissamen", "Samen von Pimpinella anisum", "", ""),
    ("5.4.1",  5, "Apfeltrester, getrocknet", "Nebenprodukt der Saft-/Cider-Herstellung", "Rohfaser", "Kann entpektiniert sein"),
    ("5.4.2",  5, "Apfeltrester, gepresst", "Feuchtes Nebenprodukt der Saft-/Cider-Herstellung", "Rohfaser", "Kann entpektiniert sein"),
    ("5.4.3",  5, "Apfelmelasse", "Extraktionsnebenprodukt der Pektinherstellung", "Rohprotein, Rohfaser", ""),
    ("5.5.1",  5, "Zuckerrübensamen", "Samen der Zuckerrübe", "", ""),
    ("5.6.1",  5, "Buchweizen", "Samen von Fagopyrum esculentum", "", ""),
    ("5.6.2",  5, "Buchweizenspelzen und -kleie", "Nebenprodukt der Getreidevermahlung", "Rohfaser", ""),
    ("5.6.3",  5, "Buchweizen-Futtermehl", "Nebenprodukt der Mehlherstellung", "Rohfaser, Stärke", "Rohfaser max. 10 %"),
    ("5.7.1",  5, "Rotkohl-Samen", "Samen von Brassica oleracea var. capitata f. rubra", "", ""),
    ("5.8.1",  5, "Kanariengras-Samen", "Samen von Phalaris canariensis", "", ""),
    ("5.9.1",  5, "Kümmelsamen", "Samen von Carum carvi L.", "", ""),
    ("5.12.1", 5, "Kastanien, geschrotet", "Nebenprodukt der Mehlherstellung", "Rohprotein, Rohfaser", ""),
    ("5.13.1", 5, "Zitrustrester", "Pressnebenprodukt der Saftgewinnung", "Rohfaser", "Kann entpektiniert sein; Alkohol max. 1 %"),
    ("5.13.2", 5, "Zitrustrester, getrocknet", "Presse-/Saftherstellungs-Trocknungserzeugnis", "Rohfaser", "Kann entpektiniert sein; Alkohol max. 1 %"),
    ("5.14.1", 5, "Rotklee-Samen", "Samen von Trifolium pratense L.", "", ""),
    ("5.14.2", 5, "Weißklee-Samen", "Samen von Trifolium repens L.", "", ""),
    ("5.15.1", 5, "Kaffeeschalen", "Nebenprodukt der Entspelzung", "Rohfaser", ""),
    ("5.16.1", 5, "Kornblumensamen", "Samen von Centaurea cyanus L.", "", ""),
    ("5.17.1", 5, "Gurkensamen", "Samen von Cucumis sativus L.", "", ""),
    ("5.18.1", 5, "Zypressensamen", "Samen von Cupressus L.", "", ""),
    ("5.19.1", 5, "Dattelfrüchte", "Früchte von Phoenix dactylifera L.", "", "Kann getrocknet sein"),
    ("5.19.2", 5, "Dattelkerne", "Ganzer Samen", "Rohfaser", ""),
    ("5.20.1", 5, "Fenchelsamen", "Samen von Foeniculum vulgare Mill.", "", ""),
    ("5.21.1", 5, "Feigen", "Früchte von Ficus carica L.", "", "Kann getrocknet sein"),
    ("5.22.1", 5, "Fruchtkerne", "Innere essbare Samen", "", ""),
    ("5.22.2", 5, "Fruchttrester", "Saft-/Püreeherstellungsnebenprodukt", "Rohfaser", "Kann entpektiniert sein"),
    ("5.22.3", 5, "Fruchttrester, getrocknet", "Saft-/Püreeherstellungs-Trocknungsnebenprodukt", "Rohfaser", ""),
    ("5.23.1", 5, "Gartenkresse (Samen)", "Samen von Lepidium sativum L.", "Rohfaser", ""),
    ("5.24.1", 5, "Gräser-Samen", "Samen der Poaceae/Cyperaceae/Juncaceae", "", ""),
    ("5.25.1", 5, "Traubenkerne", "Abgetrenntes Kernprodukt", "Rohfett, Rohfaser", "Öl nicht entfernt"),
    ("5.25.2", 5, "Traubenkernschrot", "Extraktionsrückstand der Ölgewinnung", "Rohfaser", ""),
    ("5.25.3", 5, "Traubentrester", "Getrocknetes Alkoholextraktionsnebenprodukt", "Rohfaser", "Stiele/Kerne entfernt"),
    ("5.25.4", 5, "Traubenkern-Solubles", "Saftherstellungsnebenprodukt", "Rohfaser", ""),
    ("5.26.1", 5, "Haselnuss", "Ganze oder gebrochene Frucht von Corylus spp.", "", ""),
    ("5.26.2", 5, "Haselnusskuchen", "Pressrückstand des Kerns", "Rohprotein, Rohfaser", ""),
    ("5.27.1", 5, "Pektin", "Wässriges Extraktionserzeugnis", "", "Alkohol max. 1 %"),
    ("5.28.1", 5, "Perillaöl-Samen", "Samen von Perilla frutescens L.", "", ""),
    ("5.29.1", 5, "Piniensamen", "Samen von Pinus spp.", "", ""),
    ("5.30.1", 5, "Pistazienfrucht", "Frucht von Pistacia vera L.", "", ""),
    ("5.31.1", 5, "Wegerich-Samen", "Samen von Plantago spp.", "", ""),
    ("5.32.1", 5, "Radieschensamen", "Samen von Raphanus sativus L.", "", ""),
    ("5.33.1", 5, "Spinatsamen", "Samen von Spinacia oleracea L.", "", ""),
    ("5.34.1", 5, "Mariendistelsamen", "Samen von Carduus marianus L.", "", ""),
    ("5.35.1", 5, "Tomatentrester", "Nebenprodukt des Pressens von Solanum lycopersicum L.", "Rohfaser", ""),
    ("5.36.1", 5, "Schafgarbensamen", "Samen von Achillea millefolium L.", "", ""),
    ("5.37.1", 5, "Aprikosenkernkuchen", "Pressrückstand des Kerns", "Rohprotein, Rohfaser", "Kann Blausäure enthalten"),
    ("5.38.1", 5, "Schwarzkümmelkuchen", "Pressrückstand des Samens", "Rohprotein, Rohfaser", ""),
    ("5.39.1", 5, "Borretsaatkuchen", "Pressrückstand des Samens", "Rohprotein, Rohfaser", ""),
    ("5.40.1", 5, "Nachtkerzenöl-Saatkuchen", "Pressrückstand des Samens", "Rohprotein, Rohfaser", ""),
    ("5.41.1", 5, "Granatapfelkuchen", "Pressrückstand des Samens", "Rohprotein, Rohfaser", ""),
    ("5.42.1", 5, "Walnusskuchen", "Pressrückstand des Kerns", "Rohprotein, Rohfaser", ""),
    # ------------------------------------------------------------------ Kap 6
    ("6.1.1",  6, "Rübenblätter", "Blätter von Beta spp.", "", ""),
    ("6.2.1",  6, "Getreide-Ganzpflanzen", "Ganze Getreidepflanzen oder -teile", "", "Frisch/getrocknet/siliert"),
    ("6.3.1",  6, "Getreidestroh", "Strohprodukt von Getreide", "", ""),
    ("6.3.2",  6, "Getreidestroh, behandelt", "Behandeltes Stroh", "Natrium (bei NaOH-Behandlung)", ""),
    ("6.4.1",  6, "Kleegrünmehl", "Trocknungs-/Mahlprodukt aus Klee", "Rohprotein, Rohfaser", "Kann Luzerne/andere Pflanzen enthalten"),
    ("6.5.1",  6, "Grünfuttermehl", "Trocknungs-/Mahlprodukt aus Grünfutter", "Rohprotein, Rohfaser", "Grünfutterarten können angegeben werden"),
    ("6.6.1",  6, "Gras, feldgetrocknet", "Feldgetrocknetes Graserzeugnis", "", ""),
    ("6.6.2",  6, "Gras, heißluftgetrocknet", "Künstlich entwässertes Graserzeugnis", "Rohprotein, Rohfaser", ""),
    ("6.6.3",  6, "Gras; Kräuter; Leguminosenpflanzen", "Frisches/siliertes/getrocknetes Pflanzenerzeugnis", "", "Silage/Haylage/Heu/Grünfutter"),
    ("6.7.1",  6, "Hanfmehl", "Gemahlene getrocknete Blätter", "Rohprotein", ""),
    ("6.7.2",  6, "Hanffaser", "Faseriges getrocknetes Verarbeitungsnebenprodukt", "", "Grün gefärbt"),
    ("6.8.1",  6, "Pferdebohnenstroh", "Stroh der Pferdebohne", "", ""),
    ("6.9.1",  6, "Leinstroh", "Stroh der Leinpflanze", "", ""),
    ("6.10.1", 6, "Luzerne", "Pflanzenteile von Medicago spp.", "", ""),
    ("6.10.2", 6, "Luzerne, feldgetrocknet", "Feldgetrocknete Luzerne", "", ""),
    ("6.10.3", 6, "Luzerne, heißluftgetrocknet", "Künstlich entwässerte Luzerne", "Rohprotein, Rohfaser", ""),
    ("6.10.4", 6, "Luzerne, extrudiert", "Extrudiertes Pellet-Erzeugnis", "", ""),
    ("6.10.5", 6, "Luzernegrünmehl", "Trocknungs-/Mahlprodukt aus Luzerne", "Rohprotein, Rohfaser", "Kann Klee/andere Pflanzen enthalten"),
    ("6.10.6", 6, "Luzernetrester", "Preßsaft-Trocknungsnebenprodukt", "Rohprotein, Rohfaser", ""),
    ("6.10.7", 6, "Luzerneeiweiß-Konzentrat", "Preßsaft-Zentrifugations-/Hitzefällungserzeugnis", "Rohprotein, Carotin", ""),
    ("6.10.8", 6, "Luzernequellwasser", "Eiweißextraktions-Saft-Nebenprodukt", "Rohprotein", "Kann getrocknet sein"),
    ("6.11.1", 6, "Maissilage", "Silierte Maisganzpflanzenteile", "", ""),
    ("6.12.1", 6, "Erbsenstroh", "Stroh der Erbsenpflanze", "", ""),
    ("6.13.1", 6, "Rapsstroh", "Stroh der Rapspflanze", "", ""),
    # ------------------------------------------------------------------ Kap 7
    ("7.1.1",  7, "Algen", "Lebende/verarbeitete Algen", "Rohprotein, Rohfett, Rohasche", ""),
    ("7.1.2",  7, "Algen, getrocknet", "Getrocknetes Algenerzeugnis", "Rohprotein, Rohfett, Rohasche", ""),
    ("7.1.3",  7, "Algenmehl", "Extraktions-/Trocknungsnebenprodukt aus Algen", "Rohprotein, Rohfett, Rohasche", "Inaktiviert"),
    ("7.1.4",  7, "Algenöl", "Extrahiertes Ölerzeugnis aus Algen", "", "Feuchte > 1 %"),
    ("7.1.5",  7, "Algenextrakt", "Wässriges/alkoholisches Extraktionserzeugnis", "", ""),
    ("7.1.6",  7, "Seetangmehl", "Trocknungs-/Zerkleinerungsprodukt aus Makroalgen", "Rohasche", ""),
    ("7.3.1",  7, "Baumrinden", "Gereinigte getrocknete Baum-/Strauchrindenprodukte", "Rohfaser", ""),
    ("7.4.1",  7, "Blüten, getrocknet", "Getrocknete Blütenteile", "Rohfaser", ""),
    ("7.5.1",  7, "Brokkoli, getrocknet", "Wasch-/Trocknungserzeugnis", "", ""),
    ("7.6.1",  7, "Zuckerrohrmelasse", "Sirupartiges Herstellungs-/Raffinerieprodukt", "Gesamtzucker", "Feuchte > 30 %"),
    ("7.6.2",  7, "Zuckerrohrmelasse, teilentzuckert", "Wasserextraktions-Entzuckerungsnebenprodukt", "Gesamtzucker", "Feuchte > 28 %"),
    ("7.6.3",  7, "Rohrzucker", "Wässriges Zuckerextraktionserzeugnis", "", ""),
    ("7.6.4",  7, "Zuckerrohr-Bagasse", "Faser-Wasserextraktionsnebenprodukt", "Rohfaser", "Überwiegend aus Fasern"),
    ("7.7.1",  7, "Blätter, getrocknet", "Getrocknete essbare Pflanzenblätter", "Rohfaser", ""),
    ("7.8.1",  7, "Lignocellulose", "Mechanisches Holzverarbeitungsnebenprodukt", "Rohfaser", ""),
    ("7.8.2",  7, "Pulvercellulose", "Zersetzungs-/Trennungsnebenprodukt", "Rohfaser", "NDF mind. 87 %"),
    ("7.9.1",  7, "Süßholzwurzel", "Wurzel von Glycyrrhiza L.", "", ""),
    ("7.10.1", 7, "Pfefferminze", "Getrocknete oberirdische Pflanzenteile", "", "Mentha-Art anzugeben"),
    ("7.11.1", 7, "Spinat, getrocknet", "Getrocknetes Pflanzenerzeugnis von Spinacia oleracea", "", ""),
    ("7.12.1", 7, "Mojave-Yucca", "Pulverisiertes Yucca-Erzeugnis (Yucca schidigera)", "Rohfaser", ""),
    ("7.12.2", 7, "Yucca-Schidigera-Saft", "Schnitt-/Presserzeugnis des Stängels", "", ""),
    ("7.13.1", 7, "Pflanzenkohle", "Verkohlung organischer Materialien", "Rohfaser", ""),
    ("7.14.1", 7, "Holz", "Chemisch unbehandeltes Holz-/Fasererzeugnis", "Rohfaser", "Baumart kann angegeben werden"),
    ("7.15.1", 7, "Nachtschatten-Blattmehl", "Trocknungs-/Mahlblätter von Solanum glaucophyllum", "Rohfaser, Vitamin D3", ""),
    # ------------------------------------------------------------------ Kap 8
    ("8.1.1",  8, "Butter und Buttererzeugnisse", "Herstellungs-/Verarbeitungserzeugnis aus Butter", "Rohprotein, Rohfett, Laktose", ""),
    ("8.2.1",  8, "Buttermilch / Buttermilchpulver", "Buttererzeugungsnebenprodukt", "Rohprotein, Rohfett, Laktose", "Kann Zusatzstoffe enthalten"),
    ("8.3.1",  8, "Kasein", "Säure-/Lab-Fällungs-Trocknungserzeugnis", "Rohprotein", "Feuchte > 10 %"),
    ("8.4.1",  8, "Kaseinat", "Extraktions-/Neutralisations-/Trocknungserzeugnis", "Rohprotein", "Feuchte > 10 %"),
    ("8.5.1",  8, "Käse und Käseerzeugnisse", "Käse-/Milchbasiserzeugnis", "Rohprotein, Rohfett", ""),
    ("8.6.1",  8, "Kolostrum / Kolostrumpulver", "Milchdrüsensekret bis 5 Tage nach der Geburt", "Rohprotein", ""),
    ("8.7.1",  8, "Molkerei-Nebenerzeugnisse", "Milcherzeugnisherstellungsnebenprodukte", "Rohprotein, Rohfett, Gesamtzucker", ""),
    ("8.8.1",  8, "Fermentierte Milcherzeugnisse", "Milchfermentationserzeugnis", "Rohprotein, Rohfett", ""),
    ("8.9.1",  8, "Laktose", "Milch-/Molkenzuckertrennung/-trocknung", "", "Feuchte > 5 %"),
    ("8.10.1", 8, "Vollmilch / Vollmilchpulver", "Normale Milchdrüsensekretions-Erzeugnis", "Rohprotein, Rohfett", ""),
    ("8.11.1", 8, "Magermilch / Magermilchpulver", "Fettreduziertes Milcherzeugnis", "Rohprotein", ""),
    ("8.12.1", 8, "Milchfett", "Aus Magermilch gewonnenes Fetterzeugnis", "Rohfett", ""),
    ("8.13.1", 8, "Milcheiweiß-Pulver", "Extraktions-/Trocknungs-Eiweißerzeugnis", "Rohprotein", "Feuchte > 8 %"),
    ("8.14.1", 8, "Kondensmilch und ihre Erzeugnisse", "Kondensiertes/eingedickte Milcherzeugnis", "Rohprotein, Rohfett", ""),
    ("8.15.1", 8, "Milchpermeat / Milchpermeatpulver", "Filtrationsflüssigphasenerzeugnis", "Rohasche, Rohprotein, Laktose", ""),
    ("8.16.1", 8, "Milchretentat / Milchretenatpulver", "Filtrations-Membran-Rückhalteprodukt", "Rohprotein, Rohasche, Laktose", ""),
    ("8.17.1", 8, "Molke / Molkenpulver", "Käse-/Quarkherstellungsnebenprodukt", "Rohprotein, Laktose, Rohasche", "Kann Zusatzstoffe enthalten"),
    ("8.18.1", 8, "Entlaktosierte Molke / Entlaktosiertes Molkenpulver", "Teilentzuckertes Molkenerzeugnis", "Rohprotein, Laktose, Rohasche", ""),
    ("8.19.1", 8, "Molkeneiweiß / Molkeneiweißpulver", "Extraktions-/Trocknungs-Molkeneiweiß", "Rohprotein", ""),
    ("8.20.1", 8, "Demineralisierte, entlaktosierte Molke", "Teilentzuckertes/demineralisiertes Molkenerzeugnis", "Rohprotein, Laktose, Rohasche", ""),
    ("8.21.1", 8, "Molkenpermeat / Molkenpermeatpulver", "Filtrationsflüssigphasenerzeugnis aus Molke", "Rohasche, Rohprotein, Laktose", ""),
    ("8.22.1", 8, "Molkenretentat / Molkenretenatpulver", "Filtrations-Membran-Rückhalteprodukt aus Molke", "Rohprotein, Rohasche, Laktose", ""),
    # ------------------------------------------------------------------ Kap 9
    ("9.1.1",  9, "Tierische Nebenerzeugnisse", "Ganze oder Teile von warmblütigen Landtieren", "Rohprotein, Rohfett", "Gemäß VO (EG) Nr. 1069/2009 und VO (EU) Nr. 142/2011"),
    ("9.2.1",  9, "Tierisches Fett", "Fetterzeugnis von Landtieren", "Rohfett", "Feuchte > 1 %"),
    ("9.3.1",  9, "Bienenerzeugnisse", "Honig/Bienenwachs/Gelee Royale/Propolis/Pollen", "Gesamtzucker", ""),
    ("9.4.1",  9, "Verarbeitetes tierisches Eiweiß", "Erhitzungs-/Trocknungs-/Mahlnebenprodukt", "Rohprotein, Rohfett, Rohasche", ""),
    ("9.5.1",  9, "Gelatine-Eiweiß", "Gelatineherstellungs-Trocknungserzeugnis", "Rohprotein, Rohfett, Rohasche", ""),
    ("9.6.1",  9, "Hydrolysiertes tierisches Eiweiß", "Hydrolyse-Polypeptide/Peptide/Aminosäuren", "Rohprotein", ""),
    ("9.7.1",  9, "Blutmehl", "Wärmebehandeltes Schlachtblut", "Rohprotein", "Feuchte > 8 %"),
    ("9.8.1",  9, "Bluterzeugnisse", "Schlachtblut oder -blutfraktion", "Rohprotein", ""),
    ("9.9.1",  9, "Speisereste (Catering-Reststoffe)", "Lebensmittelabfälle tierischen Ursprungs", "Rohprotein, Rohfett, Rohasche", ""),
    ("9.10.1", 9, "Kollagen", "Eiweiß aus Knochen/Häuten/Sehnen", "Rohprotein", ""),
    ("9.11.1", 9, "Federmehl", "Trocknungs-/Mahlnebenprodukt aus Schlachtfedern", "Rohprotein", "Kann hydrolysiert sein"),
    ("9.12.1", 9, "Gelatine", "Natürliches lösliches Hydrolyse-Kollageneiweiß", "Rohprotein", ""),
    ("9.13.1", 9, "Grieben", "Talgherstellungsnebenprodukt", "Rohprotein, Rohfett, Rohasche", ""),
    ("9.14.1", 9, "Erzeugnisse tierischen Ursprungs (Lebensmittelnebenprodukte)", "Ehemaliges Lebensmittel tierischen Ursprungs", "Rohprotein, Rohfett", ""),
    ("9.15.1", 9, "Eier", "Ganze Hühnereier", "", "Mit/ohne Schale"),
    ("9.15.2", 9, "Eiklar (Albumin)", "Von Schale/Eigelb getrenntes Erzeugnis", "Rohprotein", "Pasteurisiert"),
    ("9.15.3", 9, "Eiprodukte, getrocknet", "Pasteurisiertes getrocknetes Eierzeugnis", "Rohprotein, Rohfett", ""),
    ("9.15.4", 9, "Eipulver, gezuckert", "Getrocknetes Ganz-/Teileierzeugnis mit Zucker", "Rohprotein, Rohfett, Gesamtzucker", ""),
    ("9.15.5", 9, "Eierschalen, getrocknet", "Getrocknetes Geflügelei-Schalenerzeugnis", "Rohasche", ""),
    ("9.16.1", 9, "Landlebende Wirbellose, lebend", "Lebende landlebende Wirbellose", "", "Alle Entwicklungsstadien; Ungefährliche Arten"),
    ("9.16.2", 9, "Landlebende Wirbellose, tot", "Tote landlebende Wirbellose", "Rohprotein, Rohfett, Rohasche", "Ungefährliche Arten"),
    # ----------------------------------------------------------------- Kap 10
    ("10.1.1", 10, "Aquatische Wirbellose", "Ganze oder Teile mariner oder Süßwasser-Wirbellosen", "Rohprotein, Rohfett, Rohasche", ""),
    ("10.2.1", 10, "Nebenerzeugnisse aus Wassertierverwertung", "Materialien aus der Verarbeitung für Lebensmittel", "Rohprotein, Rohfett, Rohasche", ""),
    ("10.3.1", 10, "Krustentiermehl", "Erhitzungs-/Press-/Trocknungserzeugnis", "Calcium", ""),
    ("10.4.1", 10, "Fische", "Frische, gefrorene, gekochte, gesäuerte oder getrocknete Fische", "Rohprotein", ""),
    ("10.4.2", 10, "Fischmehl", "Erhitzungs-/Press-/Trocknungserzeugnis", "Rohprotein, Rohfett", "Rohasche > 20 % anzugeben"),
    ("10.4.3", 10, "Fischlösliche Bestandteile", "Konzentriertes Nebenprodukt der Fischmehlherstellung", "Rohprotein, Rohfett", ""),
    ("10.4.4", 10, "Fischeiweiß, hydrolysiert", "Hydrolyse-Erzeugnis aus Fischen", "Rohprotein, Rohfett", ""),
    ("10.4.5", 10, "Fischknochenmehl", "Erhitzungs-/Press-/Trocknungserzeugnis aus Gräten", "Rohasche", ""),
    ("10.4.6", 10, "Fischöl", "Zentrifugiertes Ölerzeugnis", "Rohfett", "Feuchte > 1 %"),
    ("10.4.7", 10, "Fischöl, hydriert", "Hydriertes Fischöl", "", "Feuchte > 1 %"),
    ("10.4.8", 10, "Fischölstearin", "Gesättigte Fettfraktion aus Winterisierung", "Rohfett", "Feuchte > 1 %"),
    ("10.5.1", 10, "Krillöl", "Öl aus gekochtem, gepresstem Krill", "", "Feuchte > 1 %"),
    ("10.5.2", 10, "Krill-Eiweiß-Konzentrat, hydrolysiert", "Enzymatisches Hydrolyseerzeugnis aus Krill", "Rohprotein, Rohfett", ""),
    ("10.6.1", 10, "Meeresringwurm-Mehl", "Erhitzungs-/Trocknungserzeugnis", "Rohfett", ""),
    ("10.7.1", 10, "Meereszooplanktonmehl", "Erhitzungs-/Press-/Trocknungserzeugnis", "Rohprotein, Rohfett", ""),
    ("10.7.2", 10, "Meereszooplanktonöl", "Öl aus gekochtem, gepresstem Zooplankton", "", "Feuchte > 1 %"),
    ("10.8.1", 10, "Muschelmehl", "Erhitzungs-/Trocknungserzeugnis aus Weichtieren", "Rohprotein, Rohfett", ""),
    ("10.9.1", 10, "Tintenfischmehl", "Erhitzungs-/Press-/Trocknungserzeugnis", "Rohprotein, Rohfett", ""),
    ("10.10.1",10, "Seestern-Mehl", "Erhitzungs-/Press-/Trocknungserzeugnis aus Asteroidea", "Rohprotein, Rohfett", ""),
    # ----------------------------------------------------------------- Kap 11
    ("11.1.1", 11, "Calciumcarbonat", "Natürlich vorkommendes Calciumcarbonat", "Calcium", ""),
    ("11.1.2", 11, "Calciumcarbonat aus Meerestieren", "Aus marinen Organismen gewonnenes CaCO3", "Calcium", ""),
    ("11.1.3", 11, "Calcit", "Natürliche Calciumcarbonat-Mineralform", "Calcium", ""),
    ("11.1.4", 11, "Kalkstein (Kalksteinmehl)", "Gemahlener natürlicher Kalkstein", "Calcium", ""),
    ("11.1.5", 11, "Muschelschalen", "Gemahlene/zerkleinerte Muschelschalen", "Calcium", ""),
    ("11.1.6", 11, "Calciumchlorid", "Anorganisches Calciumsalz", "Calcium", ""),
    ("11.1.7", 11, "Calciumsulfat (Gips)", "Anorganisches Calciumsulfat", "Calcium", ""),
    ("11.1.8", 11, "Calciumhydroxid", "Anorganisches Calciumhydroxid", "Calcium", ""),
    ("11.1.9", 11, "Calciumoxid", "Gebrannter Kalk", "Calcium", ""),
    ("11.1.10",11, "Tricalciumphosphat", "Phosphat aus Kalkstein", "Calcium", ""),
    ("11.1.11",11, "Calcium-Magnesiumcarbonat", "Gemischtes Carbonatmineral (Dolomit)", "Calcium, Magnesium", ""),
    ("11.1.12",11, "Calciumformiat", "Organisches Calciumsalz der Ameisensäure", "Calcium", ""),
    ("11.1.13",11, "Calciumlactat", "Organisches Calciumsalz der Milchsäure", "Calcium", ""),
    ("11.1.14",11, "Calciumpropionat", "Organisches Calciumsalz der Propionsäure", "Calcium", ""),
    ("11.1.15",11, "Calciumacetat", "Organisches Calciumsalz der Essigsäure", "Calcium", ""),
    ("11.1.16",11, "Calciumgluconat", "Organisches Calciumsalz der Gluconsäure", "Calcium", ""),
    ("11.1.17",11, "Calciummalat", "Organisches Calciumsalz der Apfelsäure", "Calcium", ""),
    ("11.2.1", 11, "Magnesiumoxid", "Anorganisches Magnesiumoxid", "Magnesium", ""),
    ("11.2.2", 11, "Magnesiumsulfat", "Anorganisches Magnesiumsulfat", "Magnesium", ""),
    ("11.2.3", 11, "Magnesiumchlorid", "Anorganisches Magnesiumchlorid", "Magnesium", ""),
    ("11.2.4", 11, "Magnesiumcarbonat", "Anorganisches Magnesiumcarbonat", "Magnesium", ""),
    ("11.2.5", 11, "Magnesiumphosphat", "Anorganisches Magnesiumphosphat", "Magnesium", ""),
    ("11.2.6", 11, "Magnesiumhydroxid", "Anorganisches Magnesiumhydroxid", "Magnesium", ""),
    ("11.2.7", 11, "Magnesiumformiat", "Organisches Magnesiumsalz der Ameisensäure", "Magnesium", ""),
    ("11.2.8", 11, "Magnesiumpropionat", "Organisches Magnesiumsalz der Propionsäure", "Magnesium", ""),
    ("11.2.9", 11, "Magnesiumacetat", "Organisches Magnesiumsalz der Essigsäure", "Magnesium", ""),
    ("11.2.10",11, "Magnesiumlactat", "Organisches Magnesiumsalz der Milchsäure", "Magnesium", ""),
    ("11.2.11",11, "Magnesiumgluconat", "Organisches Magnesiumsalz der Gluconsäure", "Magnesium", ""),
    ("11.2.12",11, "Magnesiumaspartat", "Organisches Magnesiumsalz der Asparaginsäure", "Magnesium", ""),
    ("11.2.13",11, "Magnesiummalat", "Organisches Magnesiumsalz der Apfelsäure", "Magnesium", ""),
    ("11.3.1", 11, "Monocalciumphosphat", "Anorganisches Calciumphosphat (MCP)", "Calcium, Gesamtphosphor", ""),
    ("11.3.2", 11, "Dicalciumphosphat", "Anorganisches Calciumphosphat (DCP)", "Calcium, Gesamtphosphor", ""),
    ("11.3.3", 11, "Tricalciumphosphat (Phosphat)", "Anorganisches Tricalciumphosphat", "Calcium, Gesamtphosphor", ""),
    ("11.3.4", 11, "Monodicalciumphosphat", "Gemischtes anorganisches Calciumphosphat", "Calcium, Gesamtphosphor", ""),
    ("11.3.5", 11, "Defluoriertes Phosphat", "Defluoriertes Rohrphosphat", "Calcium, Gesamtphosphor", ""),
    ("11.3.6", 11, "Aluminiumcalciumphosphat", "Anorganisches Al/Ca-Phosphat", "Calcium, Gesamtphosphor, Aluminium", ""),
    ("11.3.7", 11, "Calciummagnesiumphosphat", "Anorganisches Ca/Mg-Phosphat", "Calcium, Magnesium, Gesamtphosphor", ""),
    ("11.3.8", 11, "Natriummonophosphat", "Anorganisches Natriumphosphat", "Natrium, Gesamtphosphor", ""),
    ("11.3.9", 11, "Dinatriumphosphat", "Anorganisches Natriumphosphat", "Natrium, Gesamtphosphor", ""),
    ("11.3.10",11, "Trinatriumphosphat", "Anorganisches Natriumphosphat", "Natrium, Gesamtphosphor", ""),
    ("11.3.11",11, "Kaliummonophosphat", "Anorganisches Kaliumphosphat", "Kalium, Gesamtphosphor", ""),
    ("11.3.12",11, "Calciummono-/dinatriumphosphat", "Gemischtes anorganisches Ca/Na-Phosphat", "Calcium, Natrium, Gesamtphosphor", ""),
    ("11.3.13",11, "Knochenmehl, dampfdruckbehandelt", "Dampfsterilisiertes Knochenerzeugnis", "Calcium, Gesamtphosphor", ""),
    ("11.3.14",11, "Knochenasche", "Kalziniertes Knochenmehl", "Calcium, Gesamtphosphor", ""),
    ("11.3.15",11, "Entleimte Knochenasche", "Leimextraktion und Kalzinierung", "Calcium, Gesamtphosphor", ""),
    ("11.3.16",11, "Calciumhydrogenphosphat", "Anorganisches Calciumhydrogenphosphat (DCP)", "Calcium, Gesamtphosphor", ""),
    ("11.3.17",11, "Magnesiumhydrogenphosphat", "Anorganisches Mg-Hydrogenphosphat", "Magnesium, Gesamtphosphor", ""),
    ("11.3.18",11, "Magnesiumphosphat, dibasisch", "Anorganisches Magnesiumphosphat", "Magnesium, Gesamtphosphor", ""),
    ("11.3.19",11, "Calciumnatriumphosphat", "Gemischtes anorganisches Ca/Na-Phosphat", "Calcium, Natrium, Gesamtphosphor", ""),
    ("11.3.20",11, "Phosphorsäure", "Hochkonzentrierte Phosphorsäure", "Gesamtphosphor", ""),
    ("11.4.1", 11, "Natriumchlorid (Salz)", "Natriumchlorid", "Natrium", ""),
    ("11.4.2", 11, "Natriumcarbonat", "Anorganisches Natriumcarbonat", "Natrium", ""),
    ("11.4.3", 11, "Natriumbicarbonat", "Anorganisches Natriumbicarbonat (Natron)", "Natrium", ""),
    ("11.4.4", 11, "Natriumsesquicarbonat", "Anorganisches Natriumsesquicarbonat (Trona)", "Natrium", ""),
    ("11.4.5", 11, "Natriumsulfat", "Anorganisches Natriumsulfat", "Natrium", ""),
    ("11.4.6", 11, "Natriumformiat", "Organisches Natriumsalz der Ameisensäure", "Natrium", ""),
    ("11.4.7", 11, "Natriumsulfit", "Anorganisches Natriumsulfit", "Natrium", ""),
    ("11.5.1", 11, "Kaliumchlorid", "Anorganisches Kaliumchlorid", "Kalium", ""),
    ("11.5.2", 11, "Kaliumsulfat", "Anorganisches Kaliumsulfat", "Kalium", ""),
    ("11.5.3", 11, "Kaliumcarbonat", "Anorganisches Kaliumcarbonat", "Kalium", ""),
    ("11.5.4", 11, "Kaliumpidolat", "Organisches Kaliumsalz der Pidolsäure", "Kalium", ""),
    ("11.5.5", 11, "Kaliumacetat", "Organisches Kaliumsalz der Essigsäure", "Kalium", ""),
    ("11.5.6", 11, "Kaliumformiat", "Organisches Kaliumsalz der Ameisensäure", "Kalium", ""),
    ("11.6.1", 11, "Schwefel", "Elementarer Schwefel", "Schwefel", ""),
    ("11.7.1", 11, "Attapulgit (Palygorskite)", "Natürliches Aluminiummagnesiumsilikat", "", ""),
    ("11.7.2", 11, "Quarz", "Natürliches kristallines Siliciumdioxid", "", ""),
    ("11.7.3", 11, "Cristobalit", "Natürliches kristallines Siliciumdioxid", "", ""),
    ("11.8.1", 11, "Ammoniumsulfat", "Anorganisches Ammoniumsulfat", "Stickstoff", ""),
    ("11.8.2", 11, "Ammoniumlactat", "Organisches Ammoniumsalz", "Stickstoff", ""),
    ("11.9.1", 11, "Flintgrit (Feuersteingrit)", "Feuersteinkörniges Material als Verdauungshilfe", "", "Korngröße anzugeben"),
    ("11.9.2", 11, "Rotstein (Grit)", "Rotkörniges Material als Verdauungshilfe", "", "Korngröße anzugeben"),
    # ----------------------------------------------------------------- Kap 12
    ("12.1.1", 12, "Erzeugnis aus Methylophilus methylotrophus", "Fermentation auf Methanol; Rohprotein mind. 68 %", "Rohprotein, Rohasche, Rohfett", ""),
    ("12.1.2", 12, "Erzeugnis aus Methylococcus capsulatus (Bath) u. a.", "Fermentation auf Erdgas mit Ammoniak; Rohprotein mind. 65 %", "Rohprotein, Rohasche, Rohfett", ""),
    ("12.1.3", 12, "Erzeugnis aus Escherichia coli", "Aminosäure-Produktionsnebenprodukt auf pflanzlichen/chemischen Substraten", "Rohprotein", ""),
    ("12.1.4", 12, "Erzeugnis aus Corynebacterium glutamicum", "Aminosäure-Fermentationsnebenprodukt", "Rohprotein", ""),
    ("12.1.5", 12, "Hefen (Brauereihefen)", "Saccharomyces spp. und verwandte Hefen auf pflanzlichen Substraten", "Rohprotein", ""),
    ("12.1.6", 12, "Myzelsilage aus Penicillin-Produktion", "Erzeugnis von Penicillium chrysogenum; Rohprotein mind. 7 %", "Rohprotein, Rohasche", ""),
    ("12.1.7", 12, "Hefen aus Biodiesel-Prozess", "Yarrowia lipolytica aus pflanzlichen Ölen", "Rohprotein", ""),
    ("12.1.8", 12, "Erzeugnis aus Lactobacillus-Arten", "Fermentation auf pflanzlichen Substraten", "Rohprotein, Rohasche", ""),
    ("12.1.9", 12, "Erzeugnis aus Trichoderma viride", "Fermentation auf pflanzlichen Substraten", "Rohprotein, Rohasche", ""),
    ("12.1.10",12, "Erzeugnis aus Bacillus subtilis", "Fermentation auf pflanzlichen Substraten", "Rohprotein, Rohasche", ""),
    ("12.1.11",12, "Erzeugnis aus Aspergillus oryzae", "Fermentation auf pflanzlichen Substraten", "Rohprotein, Rohasche", ""),
    ("12.1.12",12, "Hefeerzeugnisse", "Hefe-Teilprodukte aus Saccharomyces spp. und verwandten Hefen", "Rohprotein", ""),
    ("12.2.1", 12, "Vinasse (eingedampfte Schlempe)", "Industrielles Fermentationsverarbeitungsnebenprodukt", "Rohprotein", "Substrat und Produktionsprozess anzugeben"),
    ("12.2.2", 12, "Nebenerzeugnisse aus L-Glutaminsäure-Herstellung", "Fermentationsnebenprodukt von Corynebacterium melassecola", "Rohprotein", ""),
    ("12.2.3", 12, "Nebenerzeugnisse aus L-Lysin-Herstellung", "Fermentationsnebenprodukt von Brevibacterium lactofermentum", "Rohprotein", ""),
    ("12.2.4", 12, "Nebenerzeugnisse aus Aminosäure-Herstellung (Corynebacterium)", "Fermentationsnebenprodukt auf pflanzlichen/chemischen Substraten", "Rohprotein, Rohasche", ""),
    ("12.2.5", 12, "Nebenerzeugnisse aus Aminosäure-Herstellung (E. coli K12)", "Fermentationsnebenprodukt auf pflanzlichen/chemischen Substraten", "Rohprotein, Rohasche", ""),
    ("12.2.6", 12, "Nebenprodukt aus Enzymproduktion (Aspergillus niger)", "Fermentation auf Weizen und Malz", "Rohprotein", ""),
    ("12.2.7", 12, "Polyhydroxybutyrat aus Ralstonia eutropha", "Enthält 3-Hydroxybutyrat und 3-Hydroxyvalerat", "Rohprotein", ""),
]


def _build_feed_materials() -> list[tuple]:
    """Return rows for INSERT INTO feed_materials."""
    return [
        (
            num, chapter, _CHAP[chapter], name_de, desc_de, decl, restr, "68/2013"
        )
        for num, chapter, name_de, desc_de, decl, restr in FEED_MATERIALS
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
        "LOT:",        # EU label field label with colon — avoids substring false-positives
                       # (bare "LOT" would hit "Pilotversuch"; regex handles "LOT A123…")
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

    # --- feed_materials (VO (EU) Nr. 68/2013) ---
    con.executemany(
        """
        INSERT INTO feed_materials
            (catalog_number, chapter, chapter_name_de, name_de,
             description_de, mandatory_declarations_de, restrictions_de, regulation)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        _build_feed_materials(),
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
