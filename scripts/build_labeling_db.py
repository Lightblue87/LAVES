#!/usr/bin/env python3
"""Build the FeedLabelCheck labeling rules SQLite database from VO (EG) Nr. 767/2009."""

from __future__ import annotations

import argparse
import hashlib
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA = """
PRAGMA journal_mode = DELETE;

CREATE TABLE IF NOT EXISTS dlg_feed_materials (
    number TEXT PRIMARY KEY,          -- z.B. "01.02.01"
    group_num INTEGER NOT NULL,       -- Gruppenziffer
    group_name_de TEXT NOT NULL,
    name_de TEXT NOT NULL,
    description_de TEXT,
    differentiation_de TEXT,          -- Differenzierungsmerkmale (in v.H.)
    requirements_de TEXT,             -- Anforderungen (in v.H.)
    labeling_de TEXT,                 -- Angaben zur Kennzeichnung
    process_de TEXT,                  -- Zusätzliche Angaben zum Herstellungsprozess
    remarks_de TEXT,                  -- Bemerkungen
    edition TEXT NOT NULL DEFAULT '15'
);

CREATE INDEX IF NOT EXISTS idx_dlg_feed_materials_group ON dlg_feed_materials(group_num);
CREATE INDEX IF NOT EXISTS idx_dlg_feed_materials_name ON dlg_feed_materials(name_de);

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

CREATE TABLE IF NOT EXISTS additive_section_headers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    header     TEXT    NOT NULL,
    lang       TEXT    NOT NULL DEFAULT 'multi',
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS additive_exclusions (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    prefix TEXT NOT NULL
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
            "complete pet food,complete feed,alimento completo,aliment complet,volledig diervoeder,"
            "Diät-Alleinfuttermittel,Diaet-Alleinfuttermittel,Diät Alleinfuttermittel,"
            "complete nutrition,100% complete nutrition"
        ),
    ),
    (
        "complementary_feed",
        "Ergänzungsfuttermittel",
        "Mischfuttermittel mit hohem Anteil bestimmter Stoffe",
        (
            "Ergänzungsfuttermittel,Ergaenzungsfuttermittel,Ergänzungsfutter,"
            "Ergänzungsfutermittel,Ergaenzungsfutermittel,Ergänzungsfuttermitel,"
            "Ergaenzungsfuttermitel,Raufutterergänzung,Raufutterergaenzung,"
            "complementary pet food,complementary feed,supplementary feed,supplementary feed for,"
            "alimento complementare,aliment complémentaire,aliment complementaire,"
            "aanvullend diervoeder,mieszanka paszowa uzupelniajaca,"
            "mieszanka paszowa uzupełniająca,alimento complementar,doplnkove krmivo,"
            "doplňkové krmivo,kompletteringsfoder"
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
# Additive parser config data
# ---------------------------------------------------------------------------

# (header, lang, sort_order) — longest/most specific first (lower sort_order = higher priority)
ADDITIVE_SECTION_HEADERS: list[tuple[str, str, int]] = [
    ("Ernährungsphysiologische Zusatzstoffe/kg", "de", 0),
    ("Ernährungsphysiologische Zusatzstoffe", "de", 1),
    ("Zootechnische Zusatzstoffe/kg", "de", 2),
    ("Zootechnische Zusatzstoffe", "de", 3),
    ("Technologische Zusatzstoffe/kg", "de", 4),
    ("Technologische Zusatzstoffe", "de", 5),
    ("Sensorische Zusatzstoffe/kg", "de", 6),
    ("Sensorische Zusatzstoffe", "de", 7),
    ("Zusatzstoff(e):", "de", 8),
    ("Zusatzstoffe/kg:", "de", 9),
    ("Zusatzstoffe:", "de", 10),
    ("Zusatzstoffe", "de", 11),
    ("Zusatzstoff:", "de", 12),
    ("Zusatzstoff", "de", 13),
    ("Zusatzstoffe je kg:", "de", 14),
    ("Zusatzstoffe je kg", "de", 15),
    ("nutritional additives", "en", 16),
    ("zootechnical additives", "en", 17),
    ("technological additives", "en", 18),
    ("sensory additives", "en", 19),
    ("additives per kg:", "en", 20),
    ("additives per kg", "en", 21),
    ("additives:", "en", 22),
]

# Prefixes of analytical constituents that must NOT be treated as Zusatzstoffe
ADDITIVE_EXCLUSION_PREFIXES: list[str] = [
    "rohprotein",
    "rohfett",
    "rohfaser",
    "rohasche",
    "feuchtegehalt",
    "feuchtigkeit",
    "feuchte",
    "natrium",
    "phosphor",
    "stärke",
    "zucker",
    "kalium",
    "chlorid",
    "linolsaure",
    "linolsäure",
    "crude protein",
    "crude fat",
    "crude fibre",
    "crude ash",
    "moisture",
    "metabolisierbare",
    "umsetzbare",
    "omega",
]

# ---------------------------------------------------------------------------
# Feed Materials Catalog – VO (EU) Nr. 68/2013 (Einzelfuttermittelkatalog)
# Tuple: (catalog_number, chapter, chapter_name_de, name_de,
#          description_de, mandatory_declarations_de, restrictions_de)
# ---------------------------------------------------------------------------

_CHAP = {
     1: "Getreidekörner und daraus gewonnene Erzeugnisse",
     2: "Ölsaaten, Ölfrüchte und daraus gewonnene Erzeugnisse",
     3: "Körnerleguminosen und daraus gewonnene Erzeugnisse",
     4: "Knollen, Wurzeln und daraus gewonnene Erzeugnisse",
     5: "Andere Saaten und Früchte und daraus gewonnene Erzeugnisse",
     6: "Grünfutter und Raufutter und daraus gewonnene Erzeugnisse",
     7: "Andere Pflanzen, Algen und daraus gewonnene Erzeugnisse",
     8: "Milcherzeugnisse und daraus gewonnene Erzeugnisse",
     9: "Erzeugnisse von Landtieren und daraus gewonnene Erzeugnisse",
    10: "Fisch, andere Wassertiere und daraus gewonnene Erzeugnisse",
    11: "Mineralstoffe und daraus gewonnene Erzeugnisse",
    12: "Erzeugnisse aus Mikroorganismen",
    13: "Verschiedene Erzeugnisse",
}

# (catalog_number, chapter_int, name_de, description_de,
#  mandatory_declarations_de)  — offiziell aus VO (EU) Nr. 68/2013
FEED_MATERIALS: list[tuple[str, int, str, str, str]] = [
    # ──────────────────────────────────────────────────────────── Kap 1
    ("1.1.1", 1, "Gerste", "Körner von Hordeum vulgare L. Kann pansengeschützt sein", ""),
    ("1.1.2", 1, "Gerste, gepufft", "Erzeugnis, das durch Behandlung in feuchter, warmer Atmosphäre und unter Druck aus gemahlenen oder gebrochenen Gerstenkörnern gewonnen wird", "Stärke"),
    ("1.1.3", 1, "Gerste, geröstet", "Erzeugnis, das bei der Röstung von Gerste entsteht, und das teilweise geröstet und nur gering verfärbt ist", "Stärke, wenn &gt; 10 % Rohprotein, wenn &gt; 15 %"),
    ("1.1.4", 1, "Gerstenflocken", "Erzeugnis, das durch Dämpfen oder Infrarot-Mikronisierung und Walzen von entspelzter Gerste gewonnen wird und das geringe Mengen an Spelzen enthalten kann. Kann pansengeschützt sein", "Stärke"),
    ("1.1.5", 1, "Gerstenfasern", "Erzeugnis, das bei der Gewinnung von Gerstenstärke anfällt und aus Teilen des Mehlkörpers und überwiegend Fasern besteht", "Rohfaser Rohprotein, wenn &gt; 10 %"),
    ("1.1.6", 1, "Gerstenschalen", "Erzeugnis, das bei der Gewinnung von Ethanol aus Stärke nach Trockenvermahlung, Sieben und Schälen der Gerstenkörner anfällt", "Rohfaser Rohprotein, wenn &gt; 10 %"),
    ("1.1.7", 1, "Gerstenfuttermehl", "Erzeugnis, das bei der Verarbeitung der gesiebten entspelzten Gerste zu Graupen, Grieß oder Mehl anfällt und überwiegend aus Teilen des Mehlkörpers sowie aus feinen Bestandteilen der äußeren Schalen und geringen Anteilen an Siebrückständen besteht", "Rohfaser Stärke"),
    ("1.1.8", 1, "Gerstenprotein", "Erzeugnis, das beim Abtrennen von Stärke und Kleie aus Gerste anfällt und überwiegend aus Protein besteht", "Rohprotein"),
    ("1.1.9", 1, "Gerstenproteinfuttermittel", "Erzeugnis, das nach dem Abtrennen von Stärke aus Gerste gewonnen wird. Es besteht überwiegend aus Protein und Teilen des Mehlkörpers", "Feuchte, wenn &lt; 45 % oder &gt; 60 % Wenn Feuchte &lt; 45 %: —"),
    ("1.1.10", 1, "Gerstenpresssaft", "Erzeugnis aus Gerste, das nach der Extraktion von Protein und Stärke im Nassverfahren gewonnen wird", "Rohprotein"),
    ("1.1.11", 1, "Gerstenkleie", "Erzeugnis, das bei der Herstellung von Mehl aus gesiebten entspelzten Gerstenkörnern anfällt und überwiegend aus Teilen der äußeren Schalen, im Übrigen aus sonstigen Kornbestandteilen besteht, die vom Mehlkörper weitgehend befreit sind", "Rohfaser"),
    ("1.1.12", 1, "Flüssige Gerstenstärke", "Sekundäre Stärkefraktion, die bei der Stärkegewinnung aus Gerste anfällt", "Wenn Feuchte &lt; 50 %: —"),
    ("1.1.13", 1, "Braugerstensiebrückstände", "Erzeugnis, das beim Sieben anfällt (Fraktionieren nach Größe) und aus vor der Mälzung ausgesonderten, zu kleinen Gerstenkörnern und Körnerteilen besteht", "Rohfaser Rohasche, wenn &gt; 2,2 %"),
    ("1.1.14", 1, "Braugersten- und Malzabrieb", "Erzeugnis, das aus Teilen von Gerstenkörnern und Malz besteht, die bei der Malzherstellung abgetrennt wurden", "Rohfaser"),
    ("1.1.15", 1, "Braugerstenspelzen", "Erzeugnis, das bei der Reinigung von Braugerste anfällt und aus Spelz- und Feinstbestandteilen besteht", "Rohfaser"),
    ("1.1.16", 1, "Gerstendickschlempe, feucht", "Erzeugnis, das bei der Gewinnung von Ethanol aus Gerste anfällt und die festen Futtermittel-Bestandteile aus der Destillation enthält", "Feuchte, wenn &lt; 65 % oder &gt; 88 % Wenn Feuchte &lt; 65 %: —"),
    ("1.1.17", 1, "Gerstendünnschlempe, feucht", "Erzeugnis, das bei der Gewinnung von Ethanol aus Gerste anfällt und die löslichen Futtermittel-Bestandteile aus der Destillation enthält", "Feuchte, wenn &lt; 45 % oder &gt; 70 % Wenn Feuchte &lt; 45 %: —"),
    ("1.1.18", 1, "Malz ( 13 )", "Erzeugnis aus gekeimten Getreidekörnern, getrocknet, gemahlen und/oder extrahiert", ""),
    ("1.1.19", 1, "Malzkeime ( 13 )", "Erzeugnis der Mälzerei, das bei der Keimung des Getreides und der anschließenden Reinigung des Malzes anfällt, und aus Wurzelfasern, Getreidestaub, Schalen und kleinen gemälzten Körnerbruchstücken besteht. Kann auch vermahlen sein", ""),
    ("1.2.1", 1, "Mais ( 14 )", "Körner von Zea mays L. ssp. mays . Kann pansengeschützt sein", ""),
    ("1.2.2", 1, "Maisflocken", "Erzeugnis, das durch Dämpfen oder Infrarot-Mikronisierung und Walzen von entlieschtem Mais gewonnen wird und das geringe Mengen an Lieschblättern enthalten kann.", "Stärke"),
    ("1.2.3", 1, "Maisfuttermehl", "Erzeugnis der Maismehl- oder Maisgrießherstellung, das überwiegend aus Teilen der Schale und anderen Kornbestandteilen besteht, die vom Mehlkörper nicht so weitgehend befreit sind wie bei der Maiskleie. Es kann geringere Anteile an Bruchstücken der Maiskeime enthalten", "Rohfaser Stärke"),
    ("1.2.4", 1, "Maiskleie", "Erzeugnis, das bei der Maismehl- oder Maisgrießherstellung gewonnen wird und überwiegend aus der Maisschale, im Übrigen aus Teilen der Maiskeime und des Mehlkörpers besteht", "Rohfaser"),
    ("1.2.5", 1, "Maiskolbenspindeln", "Kern des Maiskolbens, bestehend aus Maisspindeln, Körnern und Lieschblättern", "Rohfaser Stärke"),
    ("1.2.6", 1, "Maissiebrückstände", "Nach Anlieferung des Erzeugnisses durch Sieben aussortierte Bestandteile von Maiskörnern", ""),
    ("1.2.7", 1, "Maisfasern", "Erzeugnis, das bei der Maisstärkegewinnung gewonnen wird und überwiegend aus Fasern besteht", "Feuchte, wenn &lt; 50 % oder &gt; 70 % Wenn Feuchte &lt; 50 %: —"),
    ("1.2.8", 1, "Maiskleber", "Erzeugnis, das bei der Maisstärkegewinnung gewonnen wird und überwiegend aus Kleber besteht, der beim Abtrennen der Stärke anfällt", "Feuchte, wenn &lt; 70 % oder &gt; 90 % Wenn Feuchte &lt; 70 %: —"),
    ("1.2.9", 1, "Maiskleberfutter", "Erzeugnis, das bei der Maisstärkegewinnung gewonnen wird und überwiegend aus Kleie und Maisquellwasser besteht. Das Erzeugnis kann außerdem Bruchmais und Rückstände aus der Gewinnung von Öl aus Maiskeimen enthalten. Andere Erzeugnisse der Stärkegewinnung und der Raffination oder Fermentierung von Stärkeerzeugnissen können zugesetzt werden", "Feuchte, wenn &lt; 40 % oder &gt; 65 % Wenn Feuchte &lt; 40 %: —"),
    ("1.2.10", 1, "Maiskeime", "Erzeugnis, das bei der Maismehl-, Maisgrieß- oder Maisstärkeherstellung gewonnen wird und überwiegend aus Maiskeimen, Schalen und Mehlkörperteilen besteht", "Feuchte, wenn &lt; 40 % oder &gt; 60 % Wenn Feuchte &lt; 40 %: —"),
    ("1.2.11", 1, "Maiskeimkuchen", "Erzeugnis, das bei der Ölgewinnung durch Pressen von Maiskeimen gewonnen wird, denen noch Teile des Mehlkörpers und der Schale anhaften können", "Rohprotein Rohfett"),
    ("1.2.12", 1, "Maiskeimextraktionsschrot", "Erzeugnis, das bei der Ölgewinnung durch Extraktion von Maiskeimen gewonnen wird", "Rohprotein"),
    ("1.2.13", 1, "Maiskeimrohöl", "Erzeugnis, das aus Maiskeimen gewonnenen wird", "Rohfett"),
    ("1.2.14", 1, "Mais, gepufft", "Erzeugnis, das durch Behandlung unter feuchten, warmen Bedingungen und unter Druck aus gemahlenem Mais oder Bruchmais gewonnen wird", "Stärke"),
    ("1.2.15", 1, "Maisquellwasser", "Konzentrierte, flüssige Fraktion, die nach dem Einweichen von Maiskörnern gewonnen wird", "Feuchte, wenn &lt; 45 % oder &gt; 65 % Wenn Feuchte &lt; 45 %: —"),
    ("1.2.16", 1, "Zuckermais-Silage", "Nebenerzeugnis der Zuckermaisverarbeitung, das aus gehäckselten und entwässerten oder gepressten Maisspindeln, Lieschblättern und Körnerteilen besteht und durch Häckseln von Spindeln, Schalen, Lieschblättern und Körnerteilen von Zuckermais gewonnen wird", "Rohfaser"),
    ("1.2.17", 1, "Maisschrot, entkeimt", "Erzeugnis, das durch Entkeimen von Maisschrot gewonnen wird. Es besteht überwiegend aus Teilen des Mehlkörpers und kann geringere Anteile an Maiskeimen und Stückchen der äußeren Schale enthalten", "Rohfaser Stärke"),
    ("1.3.1", 1, "Hirse", "Körner von Panicum miliaceum L.", ""),
    ("1.4.1", 1, "Hafer", "Körner von Avena sativa L. und anderen kultivierten Haferarten", ""),
    ("1.4.2", 1, "Hafer, entspelzt", "Entspelzte Haferkörner, auch dampfbehandelt", ""),
    ("1.4.3", 1, "Haferflocken", "Erzeugnis, das durch Dämpfen oder Infrarot-Mikronisierung und Walzen entspelzten Hafers gewonnen wird und geringe Mengen an Spelzen enthalten kann", "Stärke"),
    ("1.4.4", 1, "Haferschneidmehl", "Erzeugnis, das bei der Verarbeitung des gesiebten, entspelzten Hafers zu Hafergrütze und Mehl anfällt, und überwiegend aus Haferkleie und zum geringeren Teil aus Mehlkörper besteht", "Rohfaser Stärke"),
    ("1.4.5", 1, "Haferkleie", "Erzeugnis, das bei der Herstellung von Mehl aus gesiebten Körnern entspelzten Hafers anfällt und überwiegend aus Bruchstücken der äußeren Schalenteile und sonstigen Kornbestandteilen besteht, die vom Mehlkörper weitgehend befreit sind", "Rohfaser"),
    ("1.4.6", 1, "Haferspelzen", "Erzeugnis, das beim Entspelzen der Haferkörner entsteht", "Rohfaser"),
    ("1.4.7", 1, "Hafer, gepufft", "Erzeugnis, das durch Behandlung unter feuchten, warmen Bedingungen und unter Druck aus gemahlenen und gebrochenen Haferkörnern gewonnen wird", "Stärke"),
    ("1.4.8", 1, "Hafergrütze", "Gereinigte, entspelzte Haferkörner", "Rohfaser Stärke"),
    ("1.4.9", 1, "Hafermehl aus ungeschälter Saat", "Erzeugnis, das durch Mahlen der Haferkörner entsteht", "Rohfaser Stärke"),
    ("1.4.10", 1, "Hafermehl aus geschälter Saat", "Hafererzeugnis mit hohem Stärkegehalt, nach dem Schälen", "Rohfaser"),
    ("1.4.11", 1, "Haferfuttermehl", "Erzeugnis, das bei der Verarbeitung des gesiebten, entspelzten Hafers zu Hafergrütze und Mehl anfällt, und überwiegend aus Haferkleie und zum geringeren Teil aus Mehlkörper besteht", "Rohfaser"),
    ("1.5.1", 1, "Quinoasaat-Extraktionsschrot", "Gereinigte ganze Samen der Quinoapflanze ( Chenopodium quinoa Willd.), bei denen das in den äußeren Schichten enthaltene Saponin entfernt worden ist", ""),
    ("1.6.1", 1, "Bruchreis", "Gebrochene Körner von Oryza Sativa L., die drei Viertel oder weniger der durchschnittlichen Länge ganzer Körner haben. Der Reis kann parboiled sein", "Stärke"),
    ("1.6.2", 1, "Reis, geschliffen", "Geschälter Reis, bei dem Keimling und Kleie beim Schleifen nahezu vollständig entfernt wurden. Der Reis kann parboiled sein", "Stärke"),
    ("1.6.3", 1, "Quellreis", "Erzeugnis, das durch Vorverkleistern aus geschliffenen Reiskörnern oder Bruchreis gewonnen wurde", "Stärke"),
    ("1.6.4", 1, "Reis, extrudiert", "Durch Extrudieren von Reismehl gewonnenes Erzeugnis", "Stärke"),
    ("1.6.5", 1, "Reisflocken", "Erzeugnis, das durch Flockieren von Reiskörnern oder Bruchreis (vorverkleistert) hergestellt wird", "Stärke"),
    ("1.6.6", 1, "Reis, geschält", "Rohreis ( Oryza Sativa L.), von dem nur die Spelzen entfernt worden sind. Kann auch parboiled sein. Durch das Schälen und die Handhabung kann Kleie verloren gehen", "Stärke Rohfaser"),
    ("1.6.7", 1, "Futterreis, gemahlen", "Erzeugnis, das beim Mahlen von Futterreis gewonnen wird und aus unreifen, grünen oder kreidigen Körnern, die beim Schleifen von geschältem Reis durch Absieben ausgesondert wurden, oder aus normalen, geschälten gelben oder fleckigen Körnern besteht", "Stärke"),
    ("1.6.8", 1, "Reismehl", "Erzeugnis, das beim Vermahlen von geschliffenem Reis anfällt. Der Reis kann parboiled sein", "Stärke"),
    ("1.6.9", 1, "Reismehl von geschältem Reis", "Erzeugnis, das beim Vermahlen von geschältem Reis anfällt. Der Reis kann parboiled sein", "Stärke Rohfaser"),
    ("1.6.10", 1, "Reiskleie", "Erzeugnis, das beim Schleifen von Reis anfällt und überwiegend aus den äußeren Schichten des Korns (Fruchtwand, Samenschale, Kern, Aleuronschicht) und Teilen des Keimlings besteht. Der Reis kann parboiled oder extrudiert sein", "Rohfaser"),
    ("1.6.11", 1, "Reiskleie, kalkhaltig", "Erzeugnis, das beim Schleifen von Reis anfällt und überwiegend aus den äußeren Schichten des Korns (Fruchtwand, Samenschale, Kern, Aleuronschicht) und Teilen des Keimlings besteht. Es kann bis zu 23 % des Verarbeitungshilfsstoffs Calciumcarbonat enthalten. Der Reis kann parboiled sein", "Rohfaser Calciumcarbonat"),
    ("1.6.12", 1, "Reiskleie, entfettet", "Reiskleie, die bei der Ölextraktion anfällt. Kann pansengeschützt sein", "Rohfaser"),
    ("1.6.13", 1, "Reiskleie-Öl", "Öl, das aus der stabilisierten Reiskleie extrahiert wird", "Rohfett"),
    ("1.6.14", 1, "Reisfuttermehl", "Erzeugnis, das durch Trocken- oder Nassmahlen und Absieben bei der Gewinnung von Mehl und Stärke aus Reis anfällt, und hauptsächlich aus Stärke, Protein, Fett und Faser besteht. Der Reis kann parboiled sein. Kann bis zu 0,25 % Natrium und bis zu 0,25 % Sulfat enthalten", "Stärke, wenn &gt; 20 % Rohprotein, wenn &gt; 10 % Rohfett, wenn &gt; 5 % Rohfaser"),
    ("1.6.15", 1, "Reisfuttermehl, kalkhaltig", "Erzeugnis, das beim Schleifen von Reis anfällt und überwiegend aus Teilen der Aleuronschicht und des Mehlkörpers besteht. Es kann bis zu 23 % des Verarbeitungshilfsstoffs Calciumcarbonat enthalten. Der Reis kann parboiled sein.", "Stärke Rohprotein Rohfett Rohfaser Calciumcarbonat"),
    ("1.6.17", 1, "Reiskeime", "Erzeugnis, das beim Schleifen von Reis anfällt und überwiegend aus dem Keim besteht", "Rohfett Rohprotein"),
    ("1.6.18", 1, "Reiskeimkuchen", "Rückstand, der beim Zerkleinern der Reiskeime zur Ölgewinnung durch Pressen anfällt", "Rohprotein Rohfett Rohfaser"),
    ("1.6.20", 1, "Reisprotein", "Erzeugnis, das bei der Gewinnung von Reisstärke durch Nassmahlen, Absieben, Trennen, Konzentrieren und Trocknen anfällt", "Rohprotein"),
    ("1.6.21", 1, "Reisfuttermehl, flüssig", "Konzentriertes, flüssiges Erzeugnis, das beim Nassmahlen und Absieben von Reis anfällt", "Stärke"),
    ("1.6.22", 1, "Reis, gepufft", "Erzeugnis, das durch Expandieren von Reiskörnern oder Bruchreis hergestellt wird", "Stärke"),
    ("1.6.23", 1, "Reis, fermentiert", "Erzeugnis, das durch Fermentierung von Reis entsteht.", "Stärke"),
    ("1.6.24", 1, "Reiskörner mit Missbildungen, geschliffen/kreidige Reiskörner, geschliffen", "Erzeugnis, das beim Schleifen von Reis anfällt und überwiegend aus missgebildeten Körnern und/oder kreidigen Körnern und/oder beschädigten Körnern (ganz oder gebrochen) besteht. Kann auch angekocht sein.", "Stärke"),
    ("1.6.25", 1, "Unreifer Reis, geschliffen", "Erzeugnis, das beim Schleifen von Reis anfällt und überwiegend aus unreifen und/oder kreidigen Körnern besteht", "Stärke"),
    ("1.7.1", 1, "Roggen", "Körner von Secale cereale L.", ""),
    ("1.7.2", 1, "Roggenfuttermehl", "Erzeugnis, das bei der Herstellung von Mehl aus gesiebtem Roggen anfällt, und überwiegend aus Teilen des Mehlkörpers, feinen Bruchstücken der äußeren Schale und wenigen sonstigen Kornbestandteilen besteht", "Stärke Rohfaser"),
    ("1.7.3", 1, "Roggenfutterkleie", "Erzeugnis, das bei der Herstellung von Mehl aus gesiebtem Roggen anfällt, und überwiegend aus Bruchstücken der äußeren Schale, im Übrigen aus Kornbruchstücken besteht, die vom Mehlkörper nicht so weitgehend befreit sind wie bei der Roggenkleie", "Stärke Rohfaser"),
    ("1.7.4", 1, "Roggenkleie", "Erzeugnis, das bei der Herstellung von Mehl aus gesiebtem Roggen anfällt, und überwiegend aus Bruchstücken der äußeren Schale, im Übrigen aus Kornbestandteilen besteht, die vom Mehlkörper weitgehend befreit sind", "Stärke Rohfaser"),
    ("1.8.1", 1, "Sorghum [Milokorn]", "Körner von Sorghum bicolor (L.) Moench", ""),
    ("1.8.2", 1, "Weißer Sorghum", "Körner von weißem Sorghum", ""),
    ("1.8.3", 1, "Sorghumkleberfutter", "Getrocknetes Erzeugnis, das beim Abtrennen von Sorghumstärke anfällt, und überwiegend aus Kleie und geringen Anteilen an Kleber besteht. Das Erzeugnis kann auch getrocknete Rückstände aus dem Quellwasser sowie zugesetzte Keime enthalten", "Rohprotein"),
    ("1.9.1", 1, "Dinkel", "Körner von Dinkel, Triticum spelta L., Triticum dicoccum Schrank, Triticum monococcum", ""),
    ("1.9.2", 1, "Dinkelkleie", "Erzeugnis aus der Dinkelmehlgewinnung, das überwiegend aus der äußeren Schale und geringeren Anteilen an Bruchstücken der Dinkelkeime und des Mehlkörpers besteht", "Rohfaser"),
    ("1.9.3", 1, "Dinkelspelzen", "Erzeugnis, das beim Entspelzen der Dinkelkörner anfällt", "Rohfaser"),
    ("1.9.4", 1, "Dinkelfuttermehl", "Erzeugnis, das bei der Verarbeitung des gesiebten, entspelzten Dinkels zu Mehl anfällt und überwiegend aus Bruchstücken des Mehlkörpers und feinen Teilen der äußeren Schale sowie geringeren Anteilen an Siebrückständen besteht", "Rohfaser Stärke"),
    ("1.10.1", 1, "Triticale", "Körner der Hybride Triticum × Secale L.", ""),
    ("1.11.1", 1, "Weizen", "Körner von Triticum aestivum L., Triticum durum Desf. und anderen kultivierten Weizenarten. Kann pansengeschützt sein", ""),
    ("1.11.2", 1, "Weizenwurzelfasern", "Erzeugnis der Mälzerei, das bei der Keimung des Weizens und der anschließenden Reinigung des Malzes anfällt, und aus Wurzelfasern, Getreidestaub, Schalen und kleinen gemälzten Körnerbruchstücken besteht", ""),
    ("1.11.3", 1, "Weizen, vorverkleistert", "Erzeugnis, das durch Behandlung unter feuchten, warmen Bedingungen und unter Druck aus gemahlenen Weizenkörnern oder Bruchweizen gewonnen wird", "Stärke"),
    ("1.11.4", 1, "Weizenfuttermehl", "Erzeugnis, das bei der Herstellung von Mehl aus gesiebtem Weizen oder entspelztem Dinkel anfällt und überwiegend aus Teilen des Mehlkörpers und feinen Bruchstücken der Schale und wenigen Siebrückständen besteht", "Rohfaser Stärke"),
    ("1.11.5", 1, "Weizenflocken", "Erzeugnis, das durch Dämpfen oder Infrarot-Mikronisierung und Walzen entspelzten Weizens gewonnen wird und das geringe Mengen an Spelzen enthalten kann. Kann pansengeschützt sein", "Rohfaser Stärke"),
    ("1.11.6", 1, "Weizenfutter", "Erzeugnis, das bei der Herstellung von Mehl oder Malz aus gesiebtem Weizen oder entspelztem Dinkel anfällt und überwiegend aus Teilen der äußeren Schale und Kornbestandteilen besteht, die vom Mehlkörper nicht so weitgehend befreit sind wie bei der Weizenkleie", "Rohfaser"),
    ("1.11.7", 1, "Weizenkleie ( 15 )", "Erzeugnis, das bei der Herstellung von Mehl oder Malz aus gesiebtem Weizen oder entspelztem Dinkel anfällt und überwiegend aus Teilen der äußeren Schale, im Übrigen aus Kornbestandteilen besteht, die vom Mehlkörper weitgehend befreit sind", "Rohfaser"),
    ("1.11.8", 1, "Weizenmalzmehl, fermentiert", "Erzeugnis, das durch Mälzen und Fermentieren von Weizen und Weizenkleie gewonnen und anschließend getrocknet und vermahlen wird", "Stärke Rohfaser"),
    ("1.11.10", 1, "Weizenfasern", "Erzeugnis, das bei der Weizenverarbeitung gewonnen wird und überwiegend aus Fasern besteht", "Feuchte, wenn &lt; 60 % oder &gt; 80 % Wenn Feuchte &lt; 60 %: —"),
    ("1.11.11", 1, "Weizenkeime", "Erzeugnis der Mehlgewinnung, das im Wesentlichen aus gewalzten oder nicht gewalzten Weizenkeimen besteht, denen noch Teile des Mehlkörpers und der Schale anhaften können", "Rohprotein Rohfett"),
    ("1.11.12", 1, "Weizenkeime, fermentiert", "Erzeugnis der Fermentation von Weizenkeimen mit inaktivierten Mikroorganismen", "Rohprotein Rohfett"),
    ("1.11.13", 1, "Weizenkeimkuchen", "Erzeugnis, das bei der Ölgewinnung durch Pressen von Weizenkeimen ( Triticum aestivum L., Triticum durum Desf. und anderen kultivierten Weizenarten) und entspelztem Dinkel ( Triticum spelta L., Triticum dicoccum Schrank, Triticum monococcum L.) anfällt, denen noch Teile des Mehlkörpers und des Keims anhaften können", "Rohprotein"),
    ("1.11.15", 1, "Weizenprotein", "Bei der Gewinnung von Stärke oder der Herstellung von Ethanol aus Weizen extrahiertes Protein, das zum Teil hydrolysiert sein kann", "Rohprotein"),
    ("1.11.16", 1, "Weizenkleberfutter", "Erzeugnis der Weizenstärke- und -Weizenklebergewinnung, das aus Kleie besteht, von der die Keime teilweise entfernt worden sind. Weizenpresssaft, Bruchweizen und andere Erzeugnisse der Stärkegewinnung und der Raffination oder Fermentierung von Stärkeerzeugnissen können zugesetzt werden", "Feuchte, wenn &lt; 45 % oder &gt; 60 % Wenn Feuchte &lt; 45 %: —"),
    ("1.11.18", 1, "Weizenkleber", "Weizenprotein mit hoher Viskoselastizität in Wasser, Proteingehalt (N × 6,25) mindestens 80 %, höchstens 2 % Asche in der Trockensubstanz", "Rohprotein"),
    ("1.11.19", 1, "Flüssige Weizenstärke", "Erzeugnis, das bei der Gewinnung von Stärke/Glukose und Kleber aus Weizen anfällt", "Feuchte, wenn &lt; 65 % oder &gt; 85 % Wenn Feuchte &lt; 65 %: —"),
    ("1.11.20", 1, "Proteinhaltige Weizenstärke, teilentzuckert", "Erzeugnis, das bei der Weizenstärkegewinnung anfällt und überwiegend aus verzuckerter Stärke, den löslichen Proteinen und anderen löslichen Bestandteilen des Mehlkörpers besteht", "Rohprotein Stärke Gesamtzuckergehalt berechnet als Saccharose"),
    ("1.11.21", 1, "Weizenpresssaft", "Erzeugnis aus Weizen, das nach der Extraktion von Protein und Stärke im Nassverfahren verbleibt. Kann hydrolysiert sein", "Feuchte, wenn &lt; 55 % oder &gt; 85 % Wenn Feuchte &lt; 55 %: —"),
    ("1.11.22", 1, "Weizenhefekonzentrat", "Flüssiges Nebenerzeugnis, das nach Umwandlung der Weizenstärke in Alkohol durch Fermentierung entsteht", "Feuchte, wenn &lt; 60 % oder &gt; 80 % Wenn Feuchte &lt; 60 %: —"),
    ("1.11.23", 1, "Brauweizensiebrückstände", "Erzeugnis, das beim Sieben anfällt (Fraktionieren nach Größe) und aus zu kleinen Weizenkörnern und vor der Mälzung ausgesonderten Körnerteilen besteht", "Rohfaser"),
    ("1.11.24", 1, "Brauweizen- und Malzabrieb", "Erzeugnis, das aus Teilen von Weizenkörnern und Malz besteht, die bei der Malzherstellung abgetrennt wurden", "Rohfaser"),
    ("1.11.25", 1, "Brauweizenspelzen", "Erzeugnis, das bei der Reinigung von Brauweizen anfällt und aus Bruchstücken von Spelzen und Abrieb besteht", "Rohfaser"),
    ("1.12.2", 1, "Getreidemehl ( 16 )", "Durch das Vermahlen von Getreidekörnern gewonnenes Mehl", "Stärke Rohfaser"),
    ("1.12.3", 1, "Getreideprotein-konzentrat ( 16 )", "Konzentriertes und getrocknetes Erzeugnis, das durch Hefegärung nach dem Abtrennen der Stärke aus Getreide gewonnen wird", "Rohprotein"),
    ("1.12.4", 1, "Getreidekörner-Siebrückstände ( 16 )", "Erzeugnis, das beim Sieben anfällt (Fraktionieren nach Größe) und aus vor der Weiterverarbeitung ausgesonderten kleinen Körnern und Körnerteilen besteht, die auch gekeimt sein können. Das Erzeugnis enthält mehr Rohfaser (z. B. Spelzen) als die nicht fraktionierten Körner", "Rohfaser"),
    ("1.12.5", 1, "Getreidekeime ( 16 )", "Erzeugnis der Mehl- und Stärkegewinnung, das überwiegend aus gewalzten oder nicht gewalzten Getreidekeimen besteht, denen noch Teile des Mehlkörpers und der äußeren Schale anhaften können", "Rohprotein Rohfett"),
    ("1.12.6", 1, "Destillationsrückstände aus Getreide, Sirup ( 16 )", "Getreideerzeugnis, das beim Verdampfen der Rückstände aus der Gärung und Destillation von Getreidemaische zur Herstellung von Alkohol gewonnen wird", "Feuchte, wenn &lt; 45 % oder &gt; 70 % Wenn Feuchte &lt; 45 %: —"),
    ("1.12.7", 1, "Feuchte Getreideschlempe ( 16 )", "Erzeugnis, das als feste Fraktion durch Zentrifugieren oder Filtrieren der Rückstände von fermentierten und destillierten Getreidekörnern aus der Alkoholherstellung gewonnen wird", "Feuchte, wenn &lt; 65 % oder &gt; 88 % Wenn Feuchte &lt; 65 %: —"),
    ("1.12.8", 1, "Eingedampfte Dünnschlempe ( 16 )", "Feuchtes Erzeugnis aus der Alkoholherstellung, das bei der Fermentation und Destillation von Getreidemaische und Zuckersirup nach Entfernen von Kleie und Kleber gewonnen wird. Kann auch abgestorbene Zellen und/oder Teile der für die Fermentation eingesetzten Mikroorganismen enthalten.", "Feuchte, wenn &lt; 65 % oder &gt; 88 % Wenn Feuchte &lt; 65 %: —"),
    ("1.12.9", 1, "Schlempe ( 16 )", "Erzeugnis der Alkoholherstellung, das bei der Fermentation und Destillation von Maische aus Getreidekörnern und/oder anderen stärke- und zuckerhaltigen Erzeugnissen gewonnen wird. Kann auch abgestorbene Zellen und/oder Teile der für die Fermentation eingesetzten Mikroorganismen enthalten. Kann 2 % Sulfat enthalten. Kann pansengeschützt sein", "Feuchte, wenn &lt; 60 % oder &gt; 80 % Wenn Feuchte &lt; 60 %: —"),
    ("1.12.10", 1, "Getreidetrockenschlempe", "Erzeugnis der Alkoholdestillation, das durch Trocknen der Reste fermentierter Getreidekörner gewonnen wird; kann pansengeschützt sein", "Rohprotein"),
    ("1.12.11", 1, "Getreidetrockenschlempe, dunkel ( 16 ) [Schlempe, getrocknet] ( 16 )", "Erzeugnis der Alkoholdestillation, das durch Trocknen der festen Reste fermentierter Getreidekörner gewonnen wird und dem Trubsirup (Pot-ale-Sirup) oder Destillationsreste zugesetzt worden sind. Kann pansengeschützt sein", "Rohprotein"),
    ("1.12.12", 1, "Biertreber ( 16 )", "Brauereierzeugnis, das aus Resten gemälzten und nicht gemälzten Getreides und anderen stärkehaltigen Erzeugnissen besteht und Hopfenbestandteile enthalten kann. Wird gewöhnlich in feuchtem Zustand, aber auch getrocknet vermarktet. Kann bis zu 0,3 % Dimethylpolysiloxan, bis zu 1,5 % Enzyme und bis zu 1,8 % Bentonit enthalten", "Feuchte, wenn &lt; 65 % oder &gt; 88 % Wenn Feuchte &lt; 65 %: —"),
    ("1.12.13", 1, "Draff (Treber) ( 16 )", "Festes Erzeugnis, das bei der Herstellung von Whisky aus Getreide anfällt und aus Resten der Extraktion des gemälzten Getreides mit Heißwasser besteht. Wird üblicherweise in feuchter Form nach Abtrennen des Extrakts durch Absetzen vermarktet", "Feuchte, wenn &lt; 65 % oder &gt; 88 % Wenn Feuchte &lt; 65 %: —"),
    ("1.12.14", 1, "Maischefiltertreber", "Festes Erzeugnis, das bei der Herstellung von Bier, Malzextrakt und Whisky-Spirituosen anfällt. Es besteht aus den Resten der Heißwasser-Extraktion von gemahlenem Malz und u. U. anderen zucker- oder stärkereichen Zusätzen. Wird üblicherweise in feuchter Form nach Abtrennen des Extrakts durch Abpressen vermarktet", "Feuchte, wenn &lt; 65 % oder &gt; 88 % Wenn Feuchte &lt; 65 %: —"),
    ("1.12.15", 1, "Pot ale (Trub)", "Reste, die bei der Herstellung von Malt-Whisky nach dem ersten Destillat in der Brennblase verbleiben", "Rohprotein, wenn &gt; 10 %"),
    ("1.12.16", 1, "Pot-ale-Sirup (Trubsirup)", "Erzeugnis, das bei der Herstellung von Malt-Whisky durch Eindampfen des Trubs aus dem ersten Destillat anfällt", "Feuchte, wenn &lt; 45 % oder &gt; 70 % Wenn Feuchte &lt; 45 %: Rohprotein"),
    # ──────────────────────────────────────────────────────────── Kap 2
    ("2.1.1", 2, "Babassu-Kuchen", "Erzeugnis, das bei der Ölgewinnung durch Pressen von Nüssen der Babassu-Palme der Gattung Orbignya anfällt", "Rohprotein Rohfett Rohfaser"),
    ("2.2.1", 2, "Leindottersaat", "Samen von Camelina sativa (L.) Crantz", ""),
    ("2.2.2", 2, "Leindotterkuchen", "Erzeugnis, das bei der Ölgewinnung durch Pressen von Leindottersamen anfällt", "Rohprotein Rohfett Rohfaser"),
    ("2.2.3", 2, "Leindotter-Extraktionsschrot", "Erzeugnis, das bei der Ölgewinnung durch Extraktion aus Leindotterkuchen anfällt und einer geeigneten Wärmebehandlung unterzogen wurde", "Rohprotein"),
    ("2.3.1", 2, "Kakaoschalen", "Äußere Schalen der getrockneten und gerösteten Samen der Kakaopflanze Theobroma cacao L.", "Rohfaser"),
    ("2.3.2", 2, "Kakaofruchtschalen", "Erzeugnis, das bei der Verarbeitung von Kakaosamen anfällt", "Rohfaser Rohprotein"),
    ("2.3.3", 2, "Kakao-Extraktionsschrot aus teilgeschälter Saat", "Erzeugnis, das bei der Ölgewinnung durch Extraktion der teilweise geschälten, getrockneten und gerösteten Samen der Kakaopflanze Theobroma cacao L. anfällt", "Rohprotein Rohfaser"),
    ("2.4.1", 2, "Kokoskuchen", "Erzeugnis, das bei der Ölgewinnung durch Pressen des getrockneten Kerns (Endosperm) und der Samenschale (Integument) des Samens der Kokospalme ( Cocos nucifera L.) anfällt", "Rohprotein Rohfett Rohfaser"),
    ("2.4.2", 2, "Kokoskuchen, hydrolysiert", "Erzeugnis, das bei der Ölgewinnung durch Pressen und enzymatische Hydrolysierung des getrockneten Kerns (Endosperm) und der Samenschale (Integument) des Samens der Kokospalme ( Cocos nucifera L.) anfällt", "Rohprotein Rohfett Rohfaser"),
    ("2.4.3", 2, "Kokos-Extraktionsschrot", "Erzeugnis, das bei der Ölgewinnung durch Extraktion des getrockneten Kerns (Endosperm) und der Samenschale (Integument) des Samens der Kokospalme anfällt", "Rohprotein"),
    ("2.5.1", 2, "Baumwollsaat", "Entlinterte Samen der Baumwollpflanze Gossypium ssp.; Erzeugnis kann pansengeschützt sein", ""),
    ("2.5.2", 2, "Baumwoll-Extraktionsschrot aus teilgeschälter Saat", "Erzeugnis, das bei der Ölgewinnung durch Extraktion der entlinterten und teilweise geschälten Samen der Baumwollpflanze anfällt. (Höchstgehalt an Rohfaser: 22,5 % in der Trockenmasse). Kann pansengeschützt sein", "Rohprotein Rohfaser"),
    ("2.5.3", 2, "Baumwollsaatkuchen", "Erzeugnis, das bei der Ölgewinnung durch Pressen der entlinterten Samen der Baumwollpflanze anfällt", "Rohprotein Rohfaser Rohfett"),
    ("2.6.1", 2, "Erdnusskuchen aus teilenthülster Saat", "Erzeugnis, das bei der Ölgewinnung durch Pressen der teilweise von den Hülsen befreiten Samen der Erdnuss ( Arachis hypogaea L. und andere Arachis -Arten) anfällt (Höchstgehalt an Rohfaser: 16 % in der Trockenmasse)", "Rohprotein Rohfett Rohfaser"),
    ("2.6.2", 2, "Erdnuss-Extraktionsschrot aus teilenthülster Saat", "Erzeugnis, das bei der Ölgewinnung durch Extraktion des Kuchens aus teilweise von den Hülsen befreiten Erdnusssamen anfällt (Höchstgehalt an Rohfaser: 16 % in der Trockenmasse)", "Rohprotein Rohfaser"),
    ("2.6.3", 2, "Erdnusskuchen aus enthülster Saat", "Erzeugnis, das bei der Ölgewinnung durch Pressen der von den Hülsen befreiten Erdnusssamen anfällt", "Rohprotein Rohfett Rohfaser"),
    ("2.6.4", 2, "Erdnuss-Extraktionsschrot aus enthülster Saat", "Erzeugnis, das bei der Ölgewinnung durch Extraktion des Kuchens aus enthülsten Erdnusssamen anfällt", "Rohprotein Rohfaser"),
    ("2.7.1", 2, "Kapok-Kuchen", "Erzeugnis, das bei der Ölgewinnung durch Pressen der Samen von Kapok ( Ceiba pentadra (L.) Gaertn.) anfällt", "Rohprotein Rohfaser"),
    ("2.8.1", 2, "Leinsaat", "Samen des Leins ( Linum usitatissimum L.) (botanische Reinheit mindestens 93 %), ganz, gewalzt oder gemahlen; kann pansengeschützt sein", ""),
    ("2.8.2", 2, "Leinkuchen", "Erzeugnis, das bei der Ölgewinnung durch Pressen der Leinsaat anfällt (botanische Reinheit mindestens 93 %)", "Rohprotein Rohfett Rohfaser"),
    ("2.8.3", 2, "Lein-Extraktionsschrot", "Erzeugnis, das bei der Ölgewinnung durch Extraktion aus Leinkuchen, der einer geeigneten Wärmebehandlung unterzogen wurde, anfällt. Kann pansengeschützt sein", "Rohprotein"),
    ("2.8.4", 2, "Leinkuchenfutter", "Erzeugnis, das bei der Ölgewinnung durch Pressen der Leinsaat anfällt (botanische Reinheit mindestens 93 %). Kann bis zu 1 % Bleicherde und Filterhilfsstoffe (z. B. Kieselerde, amorphe Silicate und Siliciumdioxid, Phyllosilicate und Zellulose- oder Holzfaser) und Rohlecithine aus der integrierten Ölpressung und -raffination enthalten", "Rohprotein Rohfett Rohfaser"),
    ("2.8.5", 2, "Lein-Extraktionsschrotfutter", "Erzeugnis, das bei der Ölgewinnung durch Extraktion aus Leinkuchen, der einer geeigneten Wärmebehandlung unterzogen wurde, anfällt. Kann bis zu 1 % Bleicherde und Filterhilfsstoffe (z. B. Kieselerde, amorphe Silicate und Siliciumdioxid, Phyllosilicate und Zellulose- oder Holzfaser) und Rohlecithine aus der integrierten Ölpressung und -raffination enthalten. Kann pansengeschützt sein", "Rohprotein"),
    ("2.9.1", 2, "Senfkleie", "Erzeugnis aus der Verarbeitung von Senf ( Brassica juncea L.), das aus Teilen der äußeren Schale und des Korns besteht", "Rohfaser"),
    ("2.9.2", 2, "Senfsaat-Extraktionsschrot", "Erzeugnis, das durch die Extraktion von flüchtigem Senföl aus Senfsaat gewonnen wird", "Rohprotein"),
    ("2.10.1", 2, "Nigersaat", "Samen der Nigerpflanze, Guizotia abyssinica (L.f.) Cass.", ""),
    ("2.10.2", 2, "Nigersaatkuchen", "Erzeugnis, das bei der Ölgewinnung durch Pressen von Nigersaat anfällt (salzsäureunlösliche Asche: höchstens 3,4 %)", "Rohprotein Rohfett Rohfaser"),
    ("2.11.1", 2, "Olivenpülpe", "Erzeugnis, das bei der Ölgewinnung durch Extraktion nach dem Pressen von Oliven ( Olea europaea L). anfällt, die so weit wie möglich von Kernteilen befreit sind", "Rohprotein Rohfaser Rohfett"),
    ("2.11.2", 2, "Oliven-Extraktionsschrotfutter, entfettet", "Erzeugnis, das bei der Olivenölgewinnung durch Extraktion aus Olivenölkuchen anfällt, der einer geeigneten Wärmebehandlung unterzogen wurde und der so weit wie möglich von Kernteilen befreit ist. Kann bis zu 1 % Bleicherde und Filterhilfsstoffe (z. B. Kieselerde, amorphe Silicate und Siliciumdioxid, Phyllosilicate und Zellulose- oder Holzfaser) und Rohlecithine aus der integrierten Ölpressung und -raffination enthalten.", "Rohprotein Rohfaser"),
    ("2.11.3", 2, "Oliven-Extraktionsschrot, entfettet", "Erzeugnis, das bei der Olivenölgewinnung durch Extraktion aus Olivenölkuchen anfällt, der einer geeigneten Wärmebehandlung unterzogen wurde und der so weit wie möglich von Kernteilen befreit ist.", "Rohprotein Rohfaser"),
    ("2.12.1", 2, "Palmkernkuchen", "Erzeugnis, das bei der Ölgewinnung durch Pressen der Kerne von Ölpalmen ( Elaeis guineensis Jacq. und Elaeis melanococca ) anfällt, bei denen die Steinschale so weit wie möglich entfernt worden ist", "Rohprotein Rohfaser Rohfett"),
    ("2.12.2", 2, "Palmkern-Extraktionsschrot", "Erzeugnis, das bei der Ölgewinnung durch Extraktion von Palmkernen anfällt, bei denen die Steinschale so weit wie möglich entfernt worden ist", "Rohprotein Rohfaser"),
    ("2.13.1", 2, "Kürbiskernsaat", "Samen von Cucurbita pepo L. und anderen Pflanzen der Gattung Cucurbita", ""),
    ("2.13.2", 2, "Kürbiskernkuchen", "Erzeugnis, das bei der Ölgewinnung durch Pressen der Samen von Cucurbita pepo und anderen Pflanzen der Gattung Cucurbita entsteht", "Rohprotein Rohfett"),
    ("2.14.1", 2, "Rapssaat ( 17 )", "Samen von Raps Brassica napus L. ssp. oleifera (Metzg.) Sinsk., von indischem Sarson Brassica napus L. var. glauca (Roxb.) O.E. Schulz und von Raps Brassica rapa ssp. oleifera (Metzg.) Sinsk. Botanische Reinheit mindestens 94 %; kann pansengeschützt sein", ""),
    ("2.14.2", 2, "Rapskuchen", "Erzeugnis, das bei der Ölgewinnung durch Pressen von Rapssaat anfällt. Kann pansengeschützt sein", "Rohprotein Rohfett Rohfaser"),
    ("2.14.3", 2, "Raps-Extraktionsschrot", "Erzeugnis, das bei der Ölgewinnung durch Extraktion aus Rapskuchen, der einer geeigneten Wärmebehandlung unterzogen wurde, anfällt. Kann pansengeschützt sein", "Rohprotein"),
    ("2.14.4", 2, "Rapssaat, extrudiert", "Erzeugnis, das aus ganzen Rapskörnern gewonnen wird; durch Behandlung unter feuchten, warmen Bedingungen und unter Druck wird die Verkleisterung der Stärke verbessert. Kann pansengeschützt sein", "Rohprotein Rohfett"),
    ("2.14.5", 2, "Rapssaatproteinkonzentrat", "Erzeugnis, das bei der Ölgewinnung durch Abtrennen des Proteinanteils von Rapskuchen oder Rapssaat gewonnen wird", "Rohprotein"),
    ("2.14.6", 2, "Rapskuchenfutter", "Erzeugnis, das bei der Ölgewinnung durch Pressen von Rapssaat anfällt. Kann bis zu 1 % Bleicherde und Filterhilfsstoffe (z. B. Kieselerde, amorphe Silicate und Siliciumdioxid, Phyllosilicate und Zellulose- oder Holzfaser) und Rohlecithine aus der integrierten Ölpressung und -raffination enthalten. Kann pansengeschützt sein", "Rohprotein Rohfett Rohfaser"),
    ("2.14.7", 2, "Raps-Extraktionsschrotfutter", "Erzeugnis, das bei der Ölgewinnung durch Extraktion aus Rapskuchen, der einer geeigneten Wärmebehandlung unterzogen wurde, anfällt. Kann bis zu 1 % Bleicherde und Filterhilfsstoffe (z. B. Kieselerde, amorphe Silicate und Siliciumdioxid, Phyllosilicate und Zellulose- oder Holzfaser) und Rohlecithine aus der integrierten Ölpressung und -raffination enthalten. Kann pansengeschützt sein", "Rohprotein"),
    ("2.15.1", 2, "Saflorsaat", "Samen der Saflorpflanze Carthamus tinctorius L.", ""),
    ("2.15.2", 2, "Saflor-Extraktionsschrot aus teilgeschälter Saat", "Erzeugnis, das bei der Ölgewinnung durch Extraktion teilweise geschälter Saflorsaat gewonnen wird", "Rohprotein Rohfaser"),
    ("2.15.3", 2, "Saflorschalen", "Erzeugnis, das durch Schälen der Saflorsamen gewonnen wird", "Rohfaser"),
    ("2.16.1", 2, "Sesamsaat", "Samen von Sesamum indicum L.", ""),
    ("2.17.1", 2, "Sesamsaat, teilenthülst", "Erzeugnis, das bei der Ölgewinnung durch Entfernen eines Teils der Hülsen gewonnen wird", "Rohprotein Rohfaser"),
    ("2.17.2", 2, "Sesamhülsen", "Erzeugnis, das durch Enthülsen der Sesamsamen anfällt", "Rohfaser"),
    ("2.17.3", 2, "Sesamkuchen", "Erzeugnis, das bei der Ölgewinnung durch Pressen der Samen der Sesampflanze anfällt (salzsäureunlösliche Asche: höchstens 5 %)", "Rohprotein Rohfaser Rohfett"),
    ("2.18.1", 2, "Soja(bohnen), getoastet", "Sojabohnen, Glycine max . (L.) Merr., die einer geeigneten Wärmebehandlung unterzogen wurden (Ureaseaktivität: höchstens 0,4 mg N/g/Min.). Kann pansengeschützt sein", ""),
    ("2.18.2", 2, "Soja(bohnen)kuchen", "Erzeugnis, das bei der Ölgewinnung durch Pressen von Sojasaat anfällt.", "Rohprotein Rohfett Rohfaser"),
    ("2.18.3", 2, "Soja(bohnen)-Extraktionsschrot", "Erzeugnis, das bei der Ölgewinnung durch Extraktion von Sojabohnen und geeignete Wärmebehandlung anfällt (Ureaseaktivität: höchstens 0,4 mg N/g/Min.). Kann pansengeschützt sein", "Rohprotein Rohfaser wenn &gt; 8 % in der Trockenmasse"),
    ("2.18.4", 2, "Soja(bohnen)-Extraktionsschrot aus geschälter Saat", "Erzeugnis, das bei der Ölgewinnung durch Extraktion geschälter Sojabohnen und geeignete Wärmebehandlung anfällt. (Ureaseaktivität: höchstens 0,5 mg N/g/Min.). Kann pansengeschützt sein", "Rohprotein"),
    ("2.18.5", 2, "Soja(bohnen)schalen", "Erzeugnis, das beim Schälen von Sojabohnen anfällt", "Rohfaser"),
    ("2.18.6", 2, "Sojabohnen, extrudiert", "Erzeugnis, das aus Sojabohnen gewonnen wird und bei dem die Verkleisterung der Stärke durch Behandlung unter feuchten, warmen Bedingungen und unter Druck verbessert ist. Kann pansengeschützt sein", "Rohprotein Rohfett"),
    ("2.18.7", 2, "Soja(bohnen)proteinkonzentrat", "Erzeugnis aus geschälten, entfetteten Sojabohnen, das fermentiert oder noch weiter extrahiert wurde, um den Anteil löslicher Nicht-Proteinbestandteile zu verringern", "Rohprotein"),
    ("2.18.8", 2, "Sojabohnenpülpe [Sojabohnenpaste]", "Erzeugnis, das bei der Extraktion von Sojabohnen für die Lebensmittelherstellung anfällt", "Rohprotein"),
    ("2.18.9", 2, "Sojabohnen-Pressschnitzel", "Erzeugnis, das bei der Verarbeitung von Sojabohnen anfällt", "Rohprotein Rohfett"),
    ("2.18.10", 2, "Nebenerzeugnis der Sojabohnenverarbeitung", "Erzeugnis, das bei der Verarbeitung von Sojabohnen für die Lebensmittelherstellung anfällt", "Rohprotein"),
    ("2.18.11", 2, "Soja(bohnen)", "Sojabohnen, Glycine max . (L.) Merr.", "Ureaseaktivität wenn &gt; 0,4 mg N/g × min."),
    ("2.18.12", 2, "Sojabohnenflocken", "Erzeugnis, das durch Dämpfen oder Infrarot-Mikronisierung und Walzen geschälter Sojabohnen gewonnen wird (Ureaseaktivität: höchstens 0,4 mg N/g/Min.)", "Rohprotein"),
    ("2.18.13", 2, "Soja(bohnen)-Extraktionsschrotfutter", "Erzeugnis, das bei der Ölgewinnung durch Extraktion von Sojabohnen und geeigneter Wärmebehandlung anfällt (Ureaseaktivität: höchstens 0,4 mg N/g/Min.). Kann bis zu 1 % Bleicherde und Filterhilfsstoffe (z. B. Kieselerde, amorphe Silicate und Siliciumdioxid, Phyllosilicate und Zellulose- oder Holzfaser) und Rohlecithine aus der integrierten Ölpressung und -raffination enthalten. Kann pansengeschützt sein", "Rohprotein Rohfaser wenn &gt; 8 % in der Trockenmasse"),
    ("2.18.14", 2, "Soja(bohnen)-Extraktionsschrotfutter aus geschälter Saat", "Erzeugnis, das bei der Ölgewinnung durch Extraktion von geschälten Sojabohnen und geeigneter Wärmebehandlung anfällt. (Ureaseaktivität: höchstens 0,5 mg N/g/Min.). Kann bis zu 1 % Bleicherde und Filterhilfsstoffe (z. B. Kieselerde, amorphe Silicate und Siliciumdioxid, Phyllosilicate und Zellulose- oder Holzfaser) und Rohlecithine aus der integrierten Ölpressung und -raffination enthalten. Kann pansengeschützt sein", "Rohprotein"),
    ("2.19.1", 2, "Sonnenblumensaat", "Früchte der Sonnenblume Helianthus annuus L. Kann pansengeschützt sein", ""),
    ("2.19.2", 2, "Sonnenblumenkuchen", "Erzeugnis, das bei der Ölgewinnung durch Pressen von Sonnenblumensaat anfällt.", "Rohprotein Rohfett Rohfaser"),
    ("2.19.3", 2, "Sonnenblumen-Extraktionsschrot", "Erzeugnis, das bei der Ölgewinnung durch Extraktion von Sonnenblumenkuchen, der einer geeigneten Wärmebehandlung unterzogen wurde, anfällt. Kann pansengeschützt sein", "Rohprotein"),
    ("2.19.4", 2, "Sonnenblumen-Extraktionsschrot aus geschälter Saat", "Erzeugnis, das bei der Ölgewinnung durch Extraktion und geeignete Wärmebehandlung von Sonnenblumenkuchen aus ganz oder teilweise geschälter Saat anfällt. Höchstgehalt an Rohfaser: 27,5 % in der Trockenmasse", "Rohprotein Rohfaser"),
    ("2.19.5", 2, "Sonnenblumenschalen", "Erzeugnis, das durch Schälen der Sonnenblumenkerne anfällt", "Rohfaser"),
    ("2.19.6", 2, "Sonnenblumen-Extraktionsschrotfutter", "Erzeugnis, das bei der Ölgewinnung durch Extraktion von Sonnenblumenkuchen, der einer geeigneten Wärmebehandlung unterzogen wurde, anfällt. Kann bis zu 1 % Bleicherde und Filterhilfsstoffe (z. B. Kieselerde, amorphe Silicate und Siliciumdioxid, Phyllosilicate und Zellulose- oder Holzfaser) und Rohlecithine aus der integrierten Ölpressung und -raffination enthalten. Kann pansengeschützt sein", "Rohprotein"),
    ("2.19.7", 2, "Sonnenblumen-Extraktionsschrotfutter aus geschälter Saat", "Erzeugnis, das bei der Ölgewinnung durch Extraktion und geeignete Wärmebehandlung von Sonnenblumenkuchen aus ganz oder teilweise geschälter Saat anfällt. Kann bis zu 1 % Bleicherde und Filterhilfsstoffe (z. B. Kieselerde, amorphe Silicate und Siliciumdioxid, Phyllosilicate und Zellulose- oder Holzfaser) und Rohlecithine aus der integrierten Ölpressung und -raffination enthalten. Höchstgehalt an Rohfaser: 27,5 % in der Trockenmasse", "Rohprotein Rohfaser"),
    ("2.20.1", 2, "Pflanzliche Öle und Fette ( 18 )", "Aus Pflanzen gewonnene Öle und Fette (außer Rizinusöl); Erzeugnisse können entschleimt, raffiniert und/oder gehärtet sein", "Feuchte, wenn &gt; 1 %"),
    ("2.21.1", 2, "Rohlecithine", "Erzeugnis, das beim Entschleimen des Rohöls von Ölsaaten und Ölfrüchten mit Wasser gewonnen wird. Beim Entschleimen des Rohöls können Zitronensäure, Phosphorsäure oder Natriumhydroxid zugesetzt werden", ""),
    ("2.22.1", 2, "Hanfsaat", "Kontrollierte Samen von Hanf, Cannabis sativa L., deren maximaler THC-Gehalt dem EU-Recht entspricht", ""),
    ("2.22.2", 2, "Hanfkuchen", "Erzeugnis, das bei der Ölgewinnung durch Pressen der Hanfsaat anfällt", "Rohprotein Rohfaser"),
    ("2.22.3", 2, "Hanföl", "Erzeugnis, das bei der Ölgewinnung durch Pressen der Hanfpflanze und der Hanfsaat gewonnen wird", "Rohprotein Rohfett Rohfaser"),
    ("2.23.1", 2, "Mohnsaat", "Samen von Papaver somniferum L.", ""),
    ("2.23.2", 2, "Mohn-Extraktionsschrot", "Erzeugnis, das bei der Ölgewinnung durch Extraktion des Kuchens aus Mohnsaat anfällt", "Rohprotein"),
    # ──────────────────────────────────────────────────────────── Kap 3
    ("3.1.1", 3, "Bohnen, getoastet", "Samen von Phaseolus spp. oder Vigna spp., die einer geeigneten Wärmebehandlung unterzogen wurden. Erzeugnis kann pansengeschützt sein", ""),
    ("3.1.2", 3, "Bohnenproteinkonzentrat", "Erzeugnis, das bei der Stärkegewinnung aus dem abgetrennten Bohnenfruchtwasser gewonnen wird", "Rohprotein"),
    ("3.2.1", 3, "Johannisbrot, getrocknet", "Getrocknete Früchte des Johannisbrotbaums, Ceratonia siliqua L.", "Rohfaser"),
    ("3.2.3", 3, "Johannisbrotschrot, getrocknet", "Erzeugnis, das durch Schroten der von ihren Kernen befreiten, getrockneten Früchte (Hülsen) des Johannisbrotbaums gewonnen wird", "Rohfaser"),
    ("3.2.4", 3, "Johannisbrotschrot, getrocknet und mikronisiert", "Erzeugnis, das durch Mikronisieren der von ihren Kernen befreiten, getrockneten Früchte des Johannisbrotbaums gewonnen wird", "Rohfaser Gesamtzuckergehalt, berechnet als Saccharose"),
    ("3.2.5", 3, "Johannisbrotkeime", "Keime der Johannisbrotkerne", "Rohprotein"),
    ("3.2.6", 3, "Johannisbrotkeimkuchen", "Erzeugnis, das bei der Ölgewinnung durch Pressen von Johannisbrotkeimen anfällt", "Rohprotein"),
    ("3.2.7", 3, "Johannisbrot(kerne)", "Kerne des Johannisbrotbaums", "Rohfaser"),
    ("3.3.1", 3, "Kichererbsen", "Samen von Cicer arietinum L.", ""),
    ("3.4.1", 3, "Ervilie", "Samen von Ervum ervilia L.", ""),
    ("3.5.1", 3, "Bockshornkleesaat", "Samen von Bockshornklee, Trigonella foenum-graecum", ""),
    ("3.6.1", 3, "Guarschrot", "Erzeugnis, das nach der Extraktion des Pflanzenschleims von Samen der Guarbohne, Cyamopsis tetragonoloba (L.) Taub., anfällt", "Rohprotein"),
    ("3.6.2", 3, "Guarkeimschrot", "Erzeugnis, das nach der Extraktion des Pflanzenschleims von Keimen der Guarbohnensamen anfällt", "Rohprotein"),
    ("3.7.1", 3, "Ackerbohnen", "Samen von Vicia faba (L.) ssp. faba var. equina Pers . und var. minuta (Alef.) Mansf.", ""),
    ("3.7.2", 3, "Ackerbohnenflocken", "Erzeugnis, das durch Dämpfen oder Infrarot-Mikronisierung und Walzen geschälter Ackerbohnen gewonnen wird", "Stärke Rohprotein"),
    ("3.7.3", 3, "Ackerbohnenschalen", "Erzeugnis, das durch Schälen der Ackerbohnen gewonnen wird und überwiegend aus den äußeren Schalen besteht", "Rohfaser Rohprotein"),
    ("3.7.4", 3, "Ackerbohnen, geschält", "Erzeugnis, das durch Schälen der Ackerbohnen gewonnen wird und überwiegend aus den Bohnenkernen besteht", "Rohprotein Rohfaser"),
    ("3.7.5", 3, "Ackerbohnenprotein", "Erzeugnis, das durch Mahlen und Windsichten von Ackerbohnen gewonnen wird", "Rohprotein"),
    ("3.8.1", 3, "Linsen", "Samen von Lens culinaris a.o. Medik.", ""),
    ("3.8.2", 3, "Linsenschalen", "Erzeugnis, das beim Schälen der Linsen anfällt", "Rohfaser"),
    ("3.9.1", 3, "Süßlupinen", "Samen von bitterstoffarmen Lupinus ssp.", ""),
    ("3.9.2", 3, "Süßlupinen, geschält", "Geschälte Lupinensaat", "Rohprotein"),
    ("3.9.3", 3, "Lupinenschalen", "Erzeugnis, das beim Schälen der Lupinensaat anfällt und überwiegend aus den äußeren Schalen besteht", "Rohprotein Rohfaser"),
    ("3.9.4", 3, "Lupinenpülpe", "Erzeugnis, das nach der Extraktion von Lupinenbestandteilen anfällt", "Rohfaser"),
    ("3.9.5", 3, "Lupinenfuttermehl", "Erzeugnis, das bei der Herstellung von Mehl aus Lupinensaat gewonnen wird und vorwiegend aus Bestandteilen der Kotyledonen besteht und Schalen nur in geringerer Menge enthält", "Rohprotein Rohfaser"),
    ("3.9.6", 3, "Lupinenprotein", "Erzeugnis, das bei der Stärkegewinnung aus dem abgetrennten Lupinenfruchtwasser oder nach Mahlen und Windsichten gewonnen wird", "Rohprotein"),
    ("3.9.7", 3, "Lupinenproteinschrot", "Erzeugnis aus Lupinen durch Verarbeitung zu einem Schrot mit hohem Proteingehalt", "Rohprotein"),
    ("3.10.1", 3, "Mung-Bohnen", "Samen von Vigna radiata L.", ""),
    ("3.11.1", 3, "Erbsen", "Samen von Pisum ssp.; können pansengeschützt sein", ""),
    ("3.11.2", 3, "Erbsenkleie", "Erzeugnis aus der Herstellung von Erbsenschrot. Es besteht vorwiegend aus Erbsenschalen, die beim Schälen und Reinigen von Erbsen anfallen", "Rohfaser"),
    ("3.11.3", 3, "Erbsenflocken", "Erzeugnis, das durch Dämpfen oder Infrarot-Mikronisierung und Walzen geschälter Erbsen gewonnen wird", "Stärke"),
    ("3.11.4", 3, "Erbsenmehl", "Erzeugnis, das durch Mahlen der Erbsen gewonnen wird", "Rohprotein"),
    ("3.11.5", 3, "Erbsenschalen", "Erzeugnis aus der Herstellung von Erbsenschrot aus Erbsen. Es besteht vorwiegend aus Erbsenschalen, die beim Schälen und Reinigen von Erbsen anfallen, und geringeren Anteilen des Endosperms", "Rohfaser"),
    ("3.11.6", 3, "Erbsen, geschält", "Geschälte Erbsen", "Rohprotein Rohfaser"),
    ("3.11.7", 3, "Erbsenfuttermehl", "Erzeugnis, das bei der Herstellung von Mehl aus Erbsen gewonnen wird und vorwiegend aus Bestandteilen der Kotyledonen und einem geringen Anteil an Schalen besteht", "Rohprotein Rohfaser"),
    ("3.11.8", 3, "Erbsensiebrückstände", "Nach dem Sieben verbleibende und vor der Weiterverarbeitung ausgesonderte Erbsenbestandteile", "Rohfaser"),
    ("3.11.9", 3, "Erbsenprotein", "Erzeugnis, das bei der Stärkegewinnung aus dem abgetrennten Erbsenfruchtwasser oder nach Mahlen und Windsichten gewonnen wird; kann teilhydrolysiert sein", "Rohprotein"),
    ("3.11.10", 3, "Erbsenpülpe", "Erzeugnis, das durch Nassextraktion von Stärke und Protein aus Erbsen gewonnen wird, und vorwiegend aus inneren Fasern und Stärke besteht", "Feuchte, wenn &lt; 70 % oder &gt; 85 % Stärke Rohfaser Salzsäureunlösliche Asche, wenn &gt; 3,5 % in der Trockenmasse"),
    ("3.11.11", 3, "Erbsen-Presssaft", "Erzeugnis, das durch Nassextraktion von Stärke und Protein aus Erbsen gewonnen wird, und vorwiegend aus löslichen Proteinen und Oligosacchariden besteht", "Feuchte, wenn &lt; 60 % oder &gt; 85 % Gesamtzuckergehalt Rohprotein"),
    ("3.11.12", 3, "Erbsenfaser", "Erzeugnis, das durch Extraktion nach dem Mahlen und Sieben der enthülsten Erbsen gewonnen wird", "Rohfaser"),
    ("3.12.1", 3, "Wicken", "Samen von Vicia sativa L. var. sativa und anderen Varietäten", ""),
    ("3.13.1", 3, "Platterbse", "Samen von Lathyrus sativus L., die einer geeigneten Wärmebehandlung unterzogen wurden", "Verfahren der Wärmebehandlung"),
    ("3.14.1", 3, "Wicklinse", "Samen von Vicia monanthos Desf.", ""),
    # ──────────────────────────────────────────────────────────── Kap 4
    ("4.1.1", 4, "Zuckerrüben", "Beta vulgaris L. ssp. vulgaris var. altissima Doell", ""),
    ("4.1.2", 4, "Zuckerrüben-Kleinteile", "Frisches Erzeugnis aus der Zuckerherstellung, das vorwiegend aus gereinigten Rübenbruchstücken besteht und auch Anteile an Rübenblättern enthalten kann", "Salzsäureunlösliche Asche, wenn &gt; 5 % in der Trockenmasse Feuchte, wenn &lt; 50 %"),
    ("4.1.3", 4, "(Rüben-)Zucker [Saccharose]", "Mit Hilfe von Wasser aus Zuckerrüben extrahierter Zucker", "Saccharose"),
    ("4.1.4", 4, "(Zucker-) Rübenmelasse", "Erzeugnis, das bei der Gewinnung oder Raffination von Zucker aus Zuckerrüben anfällt Kann bis zu 0,5 % Schaumverhüter enthalten. Kann bis zu 0,5 % Antibelagmittel enthalten. Kann bis zu 2 % Sulfat enthalten. Kann bis zu 0,25 % Sulfit enthalten.", "Gesamtzuckergehalt, berechnet als Saccharose Feuchte, wenn &gt; 28 %"),
    ("4.1.5", 4, "(Zucker-) Rübenmelasse, teilentzuckert und/oder entbetainisiert", "Erzeugnis, das bei der weiteren Extraktion mit Hilfe von Wasser von Zucker und/oder Betain aus der Zuckerrübenmelasse anfällt Kann bis zu 2 % Sulfat enthalten. Kann bis zu 0,25 % Sulfit enthalten.", "Gesamtzuckergehalt, berechnet als Saccharose Feuchte, wenn &gt; 28 %"),
    ("4.1.6", 4, "Isomaltulose-Melasse", "Nicht kristallisierte Fraktion, die bei der Gewinnung von Isomaltulose durch enzymatische Umwandlung von Saccharose aus Zuckerrüben anfällt", "Feuchte, wenn &gt; 40 %"),
    ("4.1.7", 4, "(Zucker-) Rübennassschnitzel", "Erzeugnis aus der Zuckerherstellung, das aus mit Hilfe von Wasser entzuckerten Zuckerrübenschnitzeln besteht. Feuchtigkeitsgehalt mindestens 82 %. Der Zuckergehalt ist gering und sinkt durch (Milchsäure-)Vergärung gegen Null", "Salzsäureunlösliche Asche, wenn &gt; 5 % in der Trockenmasse Feuchte, wenn &lt; 82 % oder &gt; 92 %"),
    ("4.1.8", 4, "(Zucker-) Rübenpressschnitzel", "Erzeugnis aus der Zuckerherstellung, das aus mit Hilfe von Wasser entzuckerten Zuckerrübenschnitzeln besteht, die mechanisch abgepresst wurden. Feuchtigkeitsgehalt: höchstens 82 %. Der Zuckergehalt ist gering und sinkt durch (Milchsäure-)Vergärung gegen Null. Kann bis zu 1 % Sulfat enthalten.", "Salzsäureunlösliche Asche, wenn &gt; 5 % in der Trockenmasse Feuchte, wenn &lt; 65 % oder &gt; 82 %"),
    ("4.1.9", 4, "(Zucker-) Rübenpressschnitzel, melassiert", "Erzeugnis aus der Zuckerherstellung, das aus mit Hilfe von Wasser entzuckerten Zuckerrübenschnitzeln besteht, die mechanisch abgepresst und mit Melasse versetzt wurden. Feuchtigkeitsgehalt höchstens 82 %. Der Zuckergehalt nimmt bedingt durch die (Milchsäure-)Vergärung ab. Kann bis zu 1 % Sulfat enthalten.", "Salzsäureunlösliche Asche, wenn &gt; 5 % in der Trockenmasse Feuchte, wenn &lt; 65 % oder &gt; 82 %"),
    ("4.1.10", 4, "(Zucker-) Rübentrockenschnitzel", "Erzeugnis aus der Zuckerherstellung, das aus mit Hilfe von Wasser entzuckerten Zuckerrübenschnitzeln besteht, die mechanisch abgepresst und getrocknet wurden. Kann bis zu 2 % Sulfat enthalten.", "Salzsäureunlösliche Asche, wenn &gt; 3,5 % in der Trockenmasse Gesamtzuckergehalt, berechnet als Saccharose, wenn &gt; 10,5 %"),
    ("4.1.11", 4, "(Zucker-) Rübenmelasseschnitzel, getrocknet", "Erzeugnis aus der Zuckerherstellung, das aus mit Hilfe von Wasser entzuckerten Zuckerrübenschnitzeln besteht, die mechanisch abgepresst, getrocknet und mit Melasse versetzt wurden. Kann bis zu 0,5 % Schaumverhüter enthalten. Kann bis zu 2 % Sulfat enthalten.", "Salzsäureunlösliche Asche, wenn &gt; 3,5 % in der Trockenmasse Gesamtzuckergehalt, berechnet als Saccharose"),
    ("4.1.12", 4, "Zuckerrübensirup", "Erzeugnis, das aus der Verarbeitung von Zucker und/oder Melasse gewonnen wird. Kann bis zu 0,5 % Sulfat enthalten. Kann bis zu 0,25 % Sulfit enthalten.", "Gesamtzuckergehalt, berechnet als Saccharose Feuchte, wenn &gt; 35 %"),
    ("4.1.13", 4, "(Zucker-) Rübenkochschnitzel", "Erzeugnis, das bei der Herstellung von Sirup aus Zuckerrüben anfällt und abgepresst oder getrocknet sein kann", "Getrocknet Salzsäureunlösliche Asche, wenn &gt; 3,5 % in der Trockenmasse Gepresst Salzsäureunlösliche Asche, wenn &gt; 5 % in der Trockenmasse Feuchte, wenn &lt; 50 %"),
    ("4.1.14", 4, "Fructo-Oligosaccharide", "Erzeugnis, das durch einen enzymatischen Prozess aus Rübenzucker gewonnen wird", "Feuchte, wenn &gt; 28 %"),
    ("4.2.1", 4, "Rote-Bete-Saft", "Presssaft aus Rote Bete ( Beta vulgaris convar. crassa var. Conditiva ), der anschließend konzentriert und pasteurisiert wird, ohne dass das Gemüsetypische in Geschmack und Geruch verloren geht", "Feuchte, wenn &lt; 50 % oder &gt; 60 % Salzsäureunlösliche Asche, wenn &gt; 3,5 % in der Trockenmasse"),
    ("4.3.1", 4, "Karotten/Mohrrüben", "Wurzeln der gelben oder roten Karotte Daucus carota L.", ""),
    ("4.3.2", 4, "Karottenschalen, gedämpft", "Feuchtes Erzeugnis aus der Karottenverarbeitung, das aus den mit Dampf von den Karotten entfernten Schalen besteht, und dem zusätzlich verkleisterte Karottenstärke zugesetzt sein kann. Feuchtigkeitsgehalt: höchstens 97 %.", "Stärke Rohfaser Salzsäureunlösliche Asche, wenn &gt; 3,5 % in der Trockenmasse Feuchte, wenn &lt; 87 % oder &gt; 97 %"),
    ("4.3.3", 4, "Karottenschabsel", "Feuchtes Erzeugnis, das bei der mechanischen Abtrennung während der Verarbeitung von Karotten anfällt und vorwiegend aus getrockneten Karotten und Karottenresten besteht. Das Erzeugnis kann hitzebehandelt sein. Feuchtigkeitsgehalt: höchstens 97 %.", "Stärke Rohfaser Salzsäureunlösliche Asche, wenn &gt; 3,5 % in der Trockenmasse Feuchte, wenn &lt; 87 % oder &gt; 97 %"),
    ("4.3.4", 4, "Karottenflocken", "Erzeugnis, das durch Flockieren gelber oder roter Karotten und anschließendes Trocknen entsteht", ""),
    ("4.3.5", 4, "Karotten, getrocknet", "Getrocknete gelbe oder rote Karotten, unabhängig von der Angebotsform", "Rohfaser"),
    ("4.3.6", 4, "Karottenfutter, getrocknet", "Erzeugnis aus getrocknetem Fruchtfleisch und getrockneten Schalen", "Rohfaser"),
    ("4.4.1", 4, "Zichorienwurzeln", "Wurzeln von Cichorium intybus L.", ""),
    ("4.4.2", 4, "Zichorienkleinteile", "Frisches Erzeugnis aus der Zichorienverarbeitung. Es besteht vorwiegend aus gereinigten Zichorienbruchstücken und Blattteilen", "Salzsäureunlösliche Asche, wenn &gt; 3,5 % in der Trockenmasse Feuchte, wenn &lt; 50 %"),
    ("4.4.3", 4, "Zichoriensaat", "Samen von Cichorium intybus L.", ""),
    ("4.4.4", 4, "Zichorienpülpe, gepresst", "Erzeugnis, das bei der Gewinnung von Inulin aus den Wurzeln von Cichorium intybus L. anfällt und aus extrahierten und mechanisch abgepressten Zichorienteilen besteht. Wasser und (lösliche) Kohlehydrate wurden teilweise aus den Zichorien entfernt. Kann bis zu 1 % Sulfat und 0,2 % Sulfit enthalten", "Rohfaser Salzsäureunlösliche Asche, wenn &gt; 3,5 % in der Trockenmasse Feuchte, wenn &lt; 65 % oder &gt; 82 %"),
    ("4.4.5", 4, "Zichorienpülpe, getrocknet", "Erzeugnis, das bei der Gewinnung von Inulin aus den Wurzeln von Cichorium intybus L. anfällt; es besteht aus extrahierten und mechanisch abgepressten und anschließend getrockneten Zichorienteilen. Die (löslichen) Kohlehydrate der Zichorien wurden teilweise extrahiert. Kann bis zu 2 % Sulfat und 0,5 % Sulfit enthalten", "Rohfaser Salzsäureunlösliche Asche, wenn &gt; 3,5 % in der Trockenmasse"),
    ("4.4.6", 4, "Zichorienpulver", "Erzeugnis, das durch Zerkleinern, Trocknen und Mahlen der Wurzeln von Zichorien gewonnen wird. Kann bis zu 1 % Trennmittel enthalten", "Rohfaser Salzsäureunlösliche Asche, wenn &gt; 3,5 % in der Trockenmasse"),
    ("4.4.7", 4, "Zichorienmelasse", "Erzeugnis, das durch Pressen von Zichorien bei der Gewinnung von Inulin und Oligofructose entsteht. Zichorienmelasse besteht aus organischem Pflanzenmaterial und Mineralien. Kann bis zu 0,5 % Schaumverhüter enthalten", "Rohprotein Rohasche Feuchte, wenn &lt; 20 % oder &gt; 30 %"),
    ("4.4.8", 4, "Zichorienvinasse", "Nebenerzeugnis, das beim Pressen der Zichorien nach dem Abtrennen von Inulin und Oligofructose und der Elution durch Ionenaustausch entsteht. Zichorienvinasse besteht aus organischem Pflanzenmaterial und Mineralien. Kann bis zu 1 % Schaumverhüter enthalten", "Rohprotein Rohasche Feuchte, wenn &lt; 30 % oder &gt; 40 %"),
    ("4.4.9", 4, "Zichorien-Inulin", "Inulin ist ein aus den Wurzeln von Cichorium intybus L. extrahiertes Fructan. Rohes Zichorien-Inulin kann bis zu 1 % Sulfat und 0,5 % Sulfit enthalten", ""),
    ("4.4.10", 4, "Oligofructosesirup", "Erzeugnis, das durch partielle Hydrolyse von Inulin aus Cichorium intybus L. gewonnen wird. Roher Oligofructosesirup kann bis zu 1 % Sulfat und 0,5 % Sulfit enthalten", "Feuchte, wenn &lt; 20 % oder &gt; 30 %"),
    ("4.4.11", 4, "Oligofructose, getrocknet", "Erzeugnis, das durch partielle Hydrolyse von Inulin aus Cichorium intybus L. und anschließende Trocknung gewonnen wird", ""),
    ("4.5.1", 4, "Knoblauch, getrocknet", "Weißliches bis gelbliches Pulver aus reinem, gemahlenem Knoblauch, Allium sativum L.", ""),
    ("4.6.1", 4, "Maniok [Tapioca] [Kassava]", "Wurzelknollen von Manihot esculenta Crantz, unabhängig von der Angebotsform", "Feuchte, wenn &lt; 60 % oder &gt; 70 %"),
    ("4.6.2", 4, "Maniok, getrocknet", "Getrocknete Maniokwurzeln, unabhängig von der Angebotsform", "Stärke Salzsäureunlösliche Asche, wenn &gt; 3,5 % in der Trockenmasse"),
    ("4.7.1", 4, "Zwiebelpülpe", "Feuchtes Erzeugnis, das bei der Verarbeitung von Zwiebeln (Gattung Allium ) anfällt und aus Schalen und ganzen Zwiebeln besteht. Wenn das Erzeugnis aus der Herstellung von Zwiebelöl stammt, enthält es vorwiegend gekochte Zwiebelreste", "Rohfaser Salzsäureunlösliche Asche, wenn &gt; 3,5 % in der Trockenmasse"),
    ("4.7.2", 4, "Zwiebeln, gebraten", "Geschälte und gewürfelte Zwiebelstücke, die im Anschluss gebraten werden", "Rohfaser Salzsäureunlösliche Asche, wenn &gt; 3,5 % in der Trockenmasse Rohfett"),
    ("4.7.3", 4, "Zwiebelschlempe", "Trockenes Erzeugnis, das bei der Verarbeitung frischer Zwiebeln anfällt. Es wird durch Extraktion mit Hilfe von Alkohol und/oder Wasser gewonnen; der Wasser- oder Alkoholanteil wird abgetrennt und sprühgetrocknet. Es besteht überwiegend aus Kohlehydraten", "Rohfaser"),
    ("4.8.1", 4, "Kartoffeln", "Knollen von Solanum tuberosum L.", "Feuchte, wenn &lt; 72 % oder &gt; 88 %"),
    ("4.8.2", 4, "Kartoffeln, geschält", "Kartoffeln, die unter Verwendung von Dampf geschält wurden", "Stärke Rohfaser Salzsäureunlösliche Asche, wenn &gt; 3,5 % in der Trockenmasse"),
    ("4.8.3", 4, "Kartoffelschalen, gedämpft", "Feuchtes Erzeugnis aus der Kartoffelverarbeitung, das aus den Schalen der mit Dampf geschälten Kartoffeln besteht, und dem zusätzlich verkleisterte Kartoffelstärke zugesetzt sein kann. Kann auch püriert sein", "Feuchte, wenn &lt; 82 % oder &gt; 93 % Stärke Rohfaser Salzsäureunlösliche Asche, wenn &gt; 3,5 % in der Trockenmasse"),
    ("4.8.4", 4, "Kartoffelstücke, roh", "Erzeugnis, das bei der Zubereitung von Kartoffelerzeugnissen für den menschlichen Verzehr anfällt und geschält sein kann", "Feuchte, wenn &lt; 72 % oder &gt; 88 % Stärke Rohfaser Salzsäureunlösliche Asche, wenn &gt; 3,5 % in der Trockenmasse"),
    ("4.8.5", 4, "Kartoffelschabsel", "Feuchtes Erzeugnis, das bei der Kartoffelverarbeitung mechanisch abgetrennt wird und vorwiegend aus getrockneten Kartoffeln und Kartoffelresten besteht. Das Erzeugnis kann wärmebehandelt sein", "Feuchte, wenn &lt; 82 % oder &gt; 93 % Stärke Rohfaser Salzsäureunlösliche Asche, wenn &gt; 3,5 % in der Trockenmasse"),
    ("4.8.6", 4, "Kartoffeln, püriert", "Kartoffelerzeugnis, das zunächst gebrüht oder gekocht und dann püriert wird", "Stärke Rohfaser Salzsäureunlösliche Asche, wenn &gt; 3,5 % in der Trockenmasse"),
    ("4.8.7", 4, "Kartoffelflocken", "Erzeugnis, das durch Walzentrocknung gewaschener, geschälter oder ungeschälter gedämpfter Kartoffeln gewonnen wird", "Stärke Rohfaser Salzsäureunlösliche Asche, wenn &gt; 3,5 % in der Trockenmasse"),
    ("4.8.8", 4, "Kartoffelpülpe", "Erzeugnis aus der Kartoffelstärkegewinnung, das aus extrahierten vermahlenen Kartoffeln besteht", "Feuchte, wenn &lt; 77 % oder &gt; 88 %"),
    ("4.8.9", 4, "Kartoffelpülpe, getrocknet", "Getrocknetes Erzeugnis aus der Kartoffelstärkegewinnung, das aus extrahierten vermahlenen Kartoffeln besteht", ""),
    ("4.8.10", 4, "Kartoffeleiweiß", "Erzeugnis der Stärkegewinnung, das vorwiegend aus Eiweißbestandteilen besteht, die beim Abtrennen der Stärke anfallen", "Rohprotein"),
    ("4.8.11", 4, "Kartoffeleiweiß, hydrolysiert", "Protein, das durch eine kontrollierte enzymatische Hydrolyse der Kartoffelproteine gewonnen wird", "Rohprotein"),
    ("4.8.12", 4, "Kartoffeleiweiß, fermentiert", "Erzeugnis, das durch Fermentation von Kartoffeleiweiß und anschließende Sprühtrocknung gewonnen wird", "Rohprotein"),
    ("4.8.13", 4, "Kartoffeleiweiß, fermentiert, flüssig", "Flüssiges Erzeugnis, das durch Fermentation von Kartoffeleiweiß gewonnen wird", "Rohprotein"),
    ("4.8.14", 4, "Kartoffelwasser, eingedickt", "Eingedicktes Erzeugnis, das bei der Kartoffelstärkegewinnung anfällt und aus den Rückständen nach dem teilweisen Entzug von Faser, Protein und Stärke aus der Kartoffelpülpe und Verdunsten eines Teils des Wassers besteht", "Feuchte, wenn &lt; 50 % oder &gt; 60 % Wenn Feuchte &lt; 50 %: —"),
    ("4.8.15", 4, "Kartoffelgranulat", "Getrocknete Kartoffeln (Kartoffeln nach Waschen, Schälen, Zerkleinern (Zerschneiden, Flockieren usw.) und Wasserentzug)", ""),
    ("4.9.1", 4, "Süßkartoffeln", "Knollen von Ipomoea batatas L., unabhängig von der Angebotsform", "Feuchte, wenn &lt; 57 % oder &gt; 78 %"),
    ("4.10.1", 4, "Topinambur", "Knollen von Helianthus tuberosus L., unabhängig von der Angebotsform", "Feuchte, wenn &lt; 75 % oder &gt; 80 %"),
    # ──────────────────────────────────────────────────────────── Kap 5
    ("5.1.1", 5, "Eicheln", "Ganze Früchte der Stieleiche, Quercus robur L., der Steineiche, Quercus petraea (Matt.) Liebl., der Korkeiche, Quercus suber L., und anderer Eichenarten", ""),
    ("5.1.2", 5, "Eicheln, geschält", "Erzeugnis, das durch Schälen der Eicheln gewonnen wird", "Rohprotein Rohfaser"),
    ("5.2.1", 5, "Mandeln", "Ganze oder zerkleinerte Früchte von Prunus dulcis , mit oder ohne Mandelhäutchen", ""),
    ("5.2.2", 5, "Mandelhäutchen", "Häutchen der geschälten Mandeln, die mechanisch vom Kern getrennt und vermahlen werden", "Rohfaser"),
    ("5.2.3", 5, "Mandelkernkuchen", "Erzeugnis, das bei der Ölgewinnung durch Pressen der Mandelkerne anfällt", "Rohprotein Rohfaser"),
    ("5.3.1", 5, "Anissaat", "Samen von Pimpinella anisum", ""),
    ("5.4.1", 5, "Apfelpülpe, getrocknet [Apfeltrester, getrocknet]", "Erzeugnis, das bei der Gewinnung von Saft aus Malus domestica oder der Herstellung von Apfelwein anfällt, und vorwiegend aus Fruchtfleisch und getrockneten Schalen besteht. Kann entpektinisiert sein", "Rohfaser"),
    ("5.4.2", 5, "Apfelpülpe, gepresst [Apfeltrester, gepresst]", "Feuchtes Erzeugnis, das bei der Gewinnung von Apfelsaft oder der Herstellung von Apfelwein anfällt, und vorwiegend aus abgepresstem Fruchtfleisch und abgepressten Schalen besteht. Kann entpektinisiert sein", "Rohfaser"),
    ("5.4.3", 5, "Apfelmelasse", "Erzeugnis, das nach der Gewinnung von Pektin aus Apfeltrester anfällt, kann entpektinisiert sein", "Rohprotein Rohfaser Rohöle und -fette, wenn &gt; 10 %"),
    ("5.5.1", 5, "Zuckerrübensaat", "Samen der Zuckerrübe", ""),
    ("5.6.1", 5, "Buchweizen", "Körner von Fagopyrum esculentum", ""),
    ("5.6.2", 5, "Buchweizenschälkleie", "Erzeugnis, das durch Mahlen der Buchweizenkörner entsteht", "Rohfaser"),
    ("5.6.3", 5, "Buchweizenfuttermehl", "Erzeugnis, das bei der Herstellung von Mehl aus gesiebtem Buchweizen anfällt, und im Wesentlichen aus Teilen des Mehlkörpers, feinen Teilen der äußeren Schalen und wenigen sonstigen Kornbestandteilen besteht. Es darf höchstens 10 % Rohfaser enthalten", "Rohfaser Stärke"),
    ("5.7.1", 5, "Rotkohlsaat", "Samen von Brassica oleracea var. capitata f. Rubra", ""),
    ("5.8.1", 5, "Kanariengrassaat", "Samen von Phalaris canariensis", ""),
    ("5.9.1", 5, "Kümmelsaat", "Samen von Carum carvi L.", ""),
    ("5.12.1", 5, "Kastanienbruchstücke", "Erzeugnis der Mehlgewinnung aus Kastanien, das überwiegend aus Teilen des Mehlkörpers, feinen Schalenteilen und einigen Resten von Kastanien ( Castanea spp.) besteht", "Rohprotein Rohfaser"),
    ("5.13.1", 5, "Zitrustrester", "Erzeugnis, das bei der Gewinnung von Saft durch Pressen von Zitrusfrüchten, Citrus ssp., anfällt. Kann entpektinisiert sein", "Rohfaser"),
    ("5.13.2", 5, "Zitrustrester, getrocknet", "Erzeugnis, das beim Auspressen von Zitrusfrüchten oder der Gewinnung von Zitrusfruchtsaft anfällt und anschließend getrocknet wird. Kann entpektinisiert sein", "Rohfaser"),
    ("5.14.1", 5, "Rotkleesaat", "Samen von Trifolium pratense L.", ""),
    ("5.14.2", 5, "Weißkleesaat", "Samen von Trifolium repens L.", ""),
    ("5.15.1", 5, "Kaffeehäutchen", "Erzeugnis, das durch Schälen der Samen der Coffea -Pflanze entsteht", "Rohfaser"),
    ("5.16.1", 5, "Kornblumensaat", "Samen von Centaurea cyanus L.", ""),
    ("5.17.1", 5, "Gurkensaat", "Samen von Cucumis sativus L.", ""),
    ("5.18.1", 5, "Zypressensaat", "Samen von Cupressus L.", ""),
    ("5.19.1", 5, "Dattelfrüchte", "Früchte von Phoenix dactylifera L., können auch getrocknet sein", ""),
    ("5.19.2", 5, "Dattelkerne", "Ganze Samen der Dattelpflanze", "Rohfaser"),
    ("5.20.1", 5, "Fenchelsaat", "Samen von Foeniculum vulgare Mill.", ""),
    ("5.21.1", 5, "Feigenfrucht", "Früchte von Ficus carica L., können auch getrocknet sein", ""),
    ("5.22.1", 5, "Fruchtkerne ( 19 )", "Essbare Samen von Nüssen oder Obst", ""),
    ("5.22.2", 5, "Obsttrester ( 19 )", "Erzeugnis, das bei der Gewinnung von Saft aus Früchten und von Obstpüree anfällt; kann entpektinisiert sein", "Rohfaser"),
    ("5.22.3", 5, "Obsttrester, getrocknet ( 19 )", "Erzeugnis, das bei der Gewinnung von Obstsaft und Obstpüree anfällt und anschließend getrocknet wird. Kann entpektinisiert sein", "Rohfaser"),
    ("5.23.1", 5, "Gartenkresse", "Samen von Lepidium sativum L.", "Rohfaser"),
    ("5.24.1", 5, "Graspflanzensaat", "Samen von Gräsern der Familien Poaceae , Cyperaceae und Juncaceae", ""),
    ("5.25.1", 5, "Traubenkerne", "Vom Traubentrester getrennte Kerne von Vitis L., die nicht entölt sind", "Rohfett Rohfaser"),
    ("5.25.2", 5, "Traubenkern-Extraktionsschrot", "Erzeugnis, das bei der Extraktion des Öls von Traubenkernen anfällt", "Rohfaser"),
    ("5.25.3", 5, "Traubentrockentrester", "Traubenmaische, die unmittelbar nach der Alkoholextraktion getrocknet wurde und soweit wie möglich von Stielen und Kernen befreit ist", "Rohfaser"),
    ("5.25.4", 5, "Traubenkern-Presssaft", "Erzeugnis, das aus Traubenkernen nach der Herstellung von Traubensaft gewonnen wird und im Wesentlichen Kohlenhydrate enthält. Kann auch konzentriert sein", "Rohfaser"),
    ("5.26.1", 5, "Haselnüsse", "Ganze oder zerkleinerte Früchte von Corylis L. spp., mit oder ohne Häutchen", ""),
    ("5.26.2", 5, "Haselnuss-Expeller", "Erzeugnis, das bei der Ölgewinnung durch Pressen der Haselnusskerne anfällt", "Rohprotein Rohfaser"),
    ("5.27.1", 5, "Pektin", "Pektin wird durch wässrige Extraktion aus geeignetem Pflanzenmaterial natürlicher Arten gewonnen, in der Regel Zitrusfrüchte oder Äpfel. Als organische Fällungsmittel dürfen nur Methanol, Ethanol und Propan-2-ol verwendet werden. Kann bezogen auf die Trockenmasse einzeln oder zusammen bis zu 1 % Methanol, Ethanol und Propan-2-ol enthalten. Pektin setzt sich hauptsächlich zusammen aus partiellen Methylestern der Polygalacturonsäure und deren Natrium-, Kalium-, Calcium- oder Ammoniumsalzen", ""),
    ("5.28.1", 5, "Perillasaat", "Samen von Perilla frutescens L. und Müllereierzeugnisse", ""),
    ("5.29.1", 5, "Pinienkerne", "Samen von Pinus L. spp.", ""),
    ("5.30.1", 5, "Pistazien", "Samen von Pistacia vera L.", ""),
    ("5.31.1", 5, "Spitzwegerich-Saat", "Samen von Plantago L. spp.", ""),
    ("5.32.1", 5, "Rettichsaat", "Samen von Raphanus sativus L.", ""),
    ("5.33.1", 5, "Spinatsaat", "Samen von Spinacia oleracea L.", ""),
    ("5.34.1", 5, "Distelsaat", "Samen von Carduus marianus L.", ""),
    ("5.35.1", 5, "Tomatenpülpe", "Erzeugnis, das bei der Gewinnung von Tomatensaft durch Pressen von Tomaten der Varietät Solanum lycopersicum L. anfällt, und vorwiegend aus Tomatenschalen und -kernen besteht", "Rohfaser"),
    ("5.36.1", 5, "Schafgarbensaat", "Samen von Achillea millefolium L.", ""),
    ("5.37.1", 5, "Aprikosenkern-Expeller", "Erzeugnis, das bei der Ölgewinnung durch Pressen der Aprikosenkerne ( Prunus armeniaca L.) anfällt. Kann Blausäure enthalten", "Rohprotein Rohfaser"),
    ("5.38.1", 5, "Schwarzkümmel-Expeller", "Erzeugnis, das bei der Ölgewinnung durch Pressen der Samen des Schwarzen Kümmels ( Bunium persicum L.) anfällt", "Rohprotein Rohfaser"),
    ("5.39.1", 5, "Borretschsamen-Expeller", "Erzeugnis, das bei der Ölgewinnung durch Pressen der Borretschsamen ( Borago officinalis L.) anfällt", "Rohprotein Rohfaser"),
    ("5.40.1", 5, "Nachtkerzen-Expeller", "Erzeugnis, das bei der Ölgewinnung durch Pressen der Nachtkerzensamen ( Oenothera L.) anfällt", "Rohprotein Rohfaser"),
    ("5.41.1", 5, "Granatapfel-Expeller", "Erzeugnis, das bei der Ölgewinnung durch Pressen der Granatapfelsamen ( Punica granatum L.) anfällt", "Rohprotein Rohfaser"),
    ("5.42.1", 5, "Walnusskern-Expeller", "Erzeugnis, das bei der Ölgewinnung durch Pressen der Walnusskerne ( Juglans regia L.) anfällt.", "Rohprotein Rohfaser"),
    # ──────────────────────────────────────────────────────────── Kap 6
    ("6.1.1", 6, "Rübenblätter", "Blätter von Beta spp.", ""),
    ("6.2.1", 6, "Getreidepflanzen ( 20 )", "Ganze Pflanzen von Getreidearten oder Teile davon. Sie können getrocknet, frisch oder siliert sein", ""),
    ("6.3.1", 6, "Getreidestroh ( 20 )", "Stroh von Getreide", ""),
    ("6.3.2", 6, "Getreidestroh, behandelt ( 20 ) , ( 21 )", "Erzeugnis, das bei einer geeigneten Behandlung von Getreidestroh anfällt", "Natrium, bei Behandlung mit NaOH"),
    ("6.4.1", 6, "Kleegrünmehl", "Durch Trocknen und Mahlen von Klee der Varietät Trifolium spp. gewonnenes Erzeugnis, das jedoch bis zu 20 % Luzerne ( Medicago sativa L. und Medicago var. Martyn) oder andere Futterpflanzen enthalten kann, die zur gleichen Zeit wie der Klee getrocknet und gemahlen wurden", "Rohprotein Rohfaser Salzsäureunlösliche Asche, wenn &gt; 3,5 % in der Trockenmasse"),
    ("6.5.1", 6, "Futterpflanzenmehl ( 22 ) [Gras-Grünmehl] ( 22 ) , [Grünmehl] ( 22 ) ,", "Erzeugnis, das durch Trocknen, Mahlen und ggf. Kompaktieren von Futterpflanzen gewonnen wird", "Rohprotein Rohfaser Salzsäureunlösliche Asche, wenn &gt; 3,5 % in der Trockenmasse"),
    ("6.6.1", 6, "Gras, feldgetrocknet [Heu]", "Alle Grassorten, auf dem Feld getrocknet", "Salzsäureunlösliche Asche, wenn &gt; 3,5 % in der Trockenmasse"),
    ("6.6.2", 6, "Gras, hochtemperaturgetrocknet", "Erzeugnis, das aus Gras (alle Sorten) gewonnen und künstlich getrocknet (alle Formen) wird", "Rohprotein Faser Salzsäureunlösliche Asche, wenn &gt; 3,5 % in der Trockenmasse"),
    ("6.6.3", 6, "Gras-, Kräuter-, Leguminosenpflanzen [Grünfutter]", "Frische, silierte oder getrocknete Ackerkulturen wie Gras-, Leguminosen- oder Kräuterpflanzen, die gemeinhin als Silage, Heulage, Heu oder Grünfutter bezeichnet werden", "Salzsäureunlösliche Asche, wenn &gt; 3,5 % in der Trockenmasse"),
    ("6.7.1", 6, "Hanfmehl", "Erzeugnis, das durch Vermahlen der getrockneten Blätter von Cannabis sativa L. gewonnen wird", "Rohprotein"),
    ("6.7.2", 6, "Hanffaser", "Grünliches, getrocknetes und faseriges Erzeugnis, das bei der Verarbeitung von Hanf gewonnen wird", ""),
    ("6.8.1", 6, "Ackerbohnenstroh", "Stroh der Ackerbohne", ""),
    ("6.9.1", 6, "Leinsaatstroh", "Stroh von Leinsaat ( Linum usitatissimum L.)", ""),
    ("6.10.1", 6, "Luzerne [Alfalfa]", "Pflanzen oder Pflanzenteile von Medicago sativa L. und Medicago var. Martyn", "Salzsäureunlösliche Asche, wenn &gt; 3,5 % in der Trockenmasse"),
    ("6.10.2", 6, "Luzerne, feldgetrocknet [Alfalfa, feldgetrocknet]", "Luzerne, feldgetrocknet", "Salzsäureunlösliche Asche, wenn &gt; 3,5 % in der Trockenmasse"),
    ("6.10.3", 6, "Luzerne, hochtemperaturgetrocknet [Alfalfa, hochtemperaturgetrocknet]", "Luzerne, künstlich getrocknet (alle Formen)", "Rohprotein Rohfaser Salzsäureunlösliche Asche, wenn &gt; 3,5 % in der Trockenmasse"),
    ("6.10.4", 6, "Luzerne, extrudiert [Alfalfa, extrudiert]", "Extrudierte Alfalfa-Pellets", ""),
    ("6.10.5", 6, "Luzernemehl ( 23 ) [Alfalfamehl]", "Erzeugnis, das durch Trocknen und Vermahlen von Luzerne gewonnen wird, und bis zu 20 % Klee oder andere Futterpflanzen enthalten kann, die zur gleichen Zeit wie die Luzerne getrocknet und gemahlen wurden", "Rohprotein Rohfaser Salzsäureunlösliche Asche, wenn &gt; 3,5 % in der Trockenmasse"),
    ("6.10.6", 6, "Luzernetrester [Alfalfatrester]", "Getrocknetes Erzeugnis, das beim Pressen von Saft aus Luzernen anfällt", "Rohprotein Rohfaser"),
    ("6.10.7", 6, "Luzerneproteinkonzentrat [Alfalfaproteinkonzentrat]", "Erzeugnis, das bei der künstlichen Trocknung von Fraktionen des Luzernepresssaftes anfällt und das zum Ausfällen der Proteine durch Zentrifugation abgetrennt und wärmebehandelt wurde", "Rohprotein Karotin"),
    ("6.10.8", 6, "Luzerne-Presssaft", "Erzeugnis, das nach der Extraktion der Proteine aus Luzernesaft gewonnen wird und getrocknet sein kann", "Rohprotein"),
    ("6.11.1", 6, "Maissilage", "Silierte Pflanzen oder Pflanzenteile von Zea mays L. ssp. mays", ""),
    ("6.12.1", 6, "Erbsenstroh", "Stroh von Pisum ssp.", ""),
    # ──────────────────────────────────────────────────────────── Kap 7
    ("7.1.1", 7, "Algen ( 24 )", "Algen, lebend oder verarbeitet, frisch, gekühlt oder tiefgefroren. Kann bis zu 0,1 % Schaumverhüter enthalten.", "Rohprotein Rohfett Rohasche"),
    ("7.1.2", 7, "Trockenalgen ( 24 )", "Erzeugnis, das durch Trocknen von Algen gewonnen wird und zur Verringerung des Jodgehalts gewaschen sein kann. Kann bis zu 0,1 % Schaumverhüter enthalten.", "Rohprotein Rohfett Rohasche"),
    ("7.1.3", 7, "Algen-Extraktionsschrot ( 24 )", "Erzeugnis, das bei der Ölgewinnung durch Extraktion von Algen anfällt. Kann bis zu 0,1 % Schaumverhüter enthalten.", "Rohprotein Rohfett Rohasche"),
    ("7.1.4", 7, "Algenöl ( 24 )", "Erzeugnis, das bei der Ölgewinnung aus Algen durch Extraktion anfällt. Kann bis zu 0,1 % Schaumverhüter enthalten.", "Rohfett Feuchte, wenn &gt; 1 %"),
    ("7.1.5", 7, "Algenextrakt ( 24 ) [Algenfraktion] ( 24 )", "Wässriger oder alkoholischer Extrakt von Algen, der vorwiegend Kohlehydrate enthält. Kann bis zu 0,1 % Schaumverhüter enthalten.", ""),
    ("7.2.6", 7, "Seealgenmehl", "Erzeugnis, das durch Trocknen und Zerkleinern von Makro-Algen, insbesondere Braunalgen, anfällt und zur Verringerung des Jodgehalts gewaschen sein kann. Kann bis zu 0,1 % Schaumverhüter enthalten.", "Rohasche"),
    ("7.3.1", 7, "Rinden ( 25 )", "Gereinigte und getrocknete Rinden von Bäumen oder Sträuchern", "Rohfaser"),
    ("7.4.1", 7, "Blüten ( 25 ) , getrocknet", "Alle Teile von getrockneten Blüten essbarer Pflanzen und ihre Fraktionen", "Rohfaser"),
    ("7.5.1", 7, "Brokkoli, getrocknet", "Erzeugnis, das durch Trocknen nach Waschen, Zerkleinern (Zerschneiden, Flockieren usw.) und Wasserentzug) aus Brassica oleracea L. gewonnen wird", ""),
    ("7.6.1", 7, "Zuckerrohrmelasse", "Erzeugnis, das bei der Gewinnung oder Raffination von Zucker aus Saccharum L. anfällt. Kann bis zu 0,5 % Schaumverhüter enthalten. Kann bis zu 0,5 % Antibelagmittel enthalten. Kann bis zu 3,5 % Sulfat enthalten. Kann bis zu 0,25 % Sulfit enthalten.", "Gesamtzuckergehalt, berechnet als Saccharose Feuchte, wenn &gt; 30 %"),
    ("7.6.2", 7, "Zuckerrohrmelasse, teilentzuckert", "Erzeugnis, das bei der weiteren Extraktion von Saccharose mit Hilfe von Wasser aus der Zuckerrohrmelasse anfällt", "Gesamtzuckergehalt, berechnet als Saccharose Feuchte, wenn &gt; 28 %"),
    ("7.6.3", 7, "(Rohr-)Zucker [Saccharose]", "Mit Hilfe von Wasser aus Zuckerrohr extrahierter Zucker", "Saccharose"),
    ("7.6.4", 7, "Zuckerrohr-Bagasse", "Erzeugnis, das durch die Extraktion von Zucker mit Hilfe von Wasser aus Zuckerrohr anfällt, und vorwiegend aus Fasern besteht", "Rohfaser"),
    ("7.7.1", 7, "Blätter, getrocknet ( 25 )", "Getrocknete Blätter essbarer Pflanzen und ihre Fraktionen", "Rohfaser"),
    ("7.8.1", 7, "Lignocellulose ( 25 )", "Erzeugnis, das durch mechanische Bearbeitung von rohem gewachsenem, getrocknetem Holz anfällt und vorwiegend aus Lignocellulose besteht", "Rohfaser"),
    ("7.9.1", 7, "Süßholz", "Wurzeln von Glycyrrhiza L.", ""),
    ("7.10.1", 7, "Minze", "Erzeugnis, das durch Trocknen der oberirdischen Teile von Pflanzen der Arten Mentha apicata , Mentha piperita oder Mentha viridis L., unabhängig von der Angebotsform, gewonnen wird", ""),
    ("7.11.1", 7, "Spinat, getrocknet", "Erzeugnis, das durch Trocknen von Spinacia oleracea L., unabhängig von der Angebotsform, gewonnen wird", ""),
    ("7.12.1", 7, "Mohave-Palmlilie", "Pulver aus Yucca schidigera Roezl", "Rohfaser"),
    ("7.13.1", 7, "Pflanzliche Kohle [Holzkohle]", "Erzeugnis, das durch Verkohlung von Pflanzenmasse gewonnen wird", "Rohfaser"),
    ("7.14.1", 7, "Holz ( 25 )", "Nicht chemisch behandeltes reifes Holz oder Holzfasern", "Rohfaser"),
    # ──────────────────────────────────────────────────────────── Kap 8
    ("8.1.1", 8, "Butter und Buttererzeugnisse", "Butter und Erzeugnisse, die aus der Erzeugung oder Verarbeitung von Butter gewonnen werden (z. B. Butterserum), sofern nicht an anderer Stelle aufgeführt", "Rohprotein Rohfett Lactose Feuchte, wenn &gt; 6 %"),
    ("8.2.1", 8, "Buttermilch/Buttermilchpulver ( 26 )", "Erzeugnis, das bei der Verbutterung von Sahne oder bei ähnlichen Prozessen anfällt und konzentriert und/oder getrocknet sein kann. Bei Bestimmung als Einzelfutter gilt Folgendes: —", "Kann bis zu 0,5 % Phosphate enthalten, z. B. Polyphosphate (wie etwa Natriumhexametaphosphat) oder Diphosphate (wie etwa Tetranatriumpyrophosphat), die eingesetzt werden, um die Viskosität zu verringern und bei der Verarbeitung Proteine zu stabilisieren;"),
    ("8.3.1", 8, "Kasein", "Erzeugnis, das durch Trocknen des aus Magermilch oder Buttermilch durch Säuren oder Lab gefällten Kaseins gewonnen wird", "Rohprotein Feuchte, wenn &gt; 10 %"),
    ("8.4.1", 8, "Kaseinat", "Erzeugnis, das durch Neutralisieren und Trocknen aus Quark oder Kasein gewonnen wird", "Rohprotein Feuchte, wenn &gt; 10 %"),
    ("8.5.1", 8, "Käse und Käseerzeugnisse", "Käse und Erzeugnisse aus Käse und anderen Erzeugnissen auf Milchbasis", "Rohprotein Rohfett"),
    ("8.6.1", 8, "Kolostrum/Kolostrumpulver", "Flüssiges Sekret, das von den Milchdrüsen von zur Milcherzeugung gehaltenen Tieren in den ersten fünf Tagen nach dem Abkalben gebildet wird. Kann auch konzentriert und/oder getrocknet sein", "Rohprotein"),
    ("8.7.1", 8, "Milch-Nebenerzeugnisse", "Erzeugnisse, die bei der Herstellung von Milcherzeugnissen anfallen (u. a. ehemalige Lebensmittel aus Milch, Zentrifugen- oder Separatorenschlamm, Weißwasser, Milchmineralstoffe). Bei Bestimmung als Einzelfutter gilt Folgendes: —", "Kann bis zu 0,5 % Phosphate enthalten, z. B. Polyphosphate (wie etwa Natriumhexametaphosphat) oder Diphosphate (wie etwa Tetranatriumpyrophosphat), die eingesetzt werden, um die Viskosität zu verringern und bei der Verarbeitung Proteine zu stabilisieren;"),
    ("8.8.1", 8, "Fermentierte Milcherzeugnisse", "Erzeugnisse, die durch Fermentation von Milch gewonnen werden (Joghurt usw.)", "Rohprotein Rohfett"),
    ("8.9.1", 8, "Lactose", "Aus Milch oder Molke durch Reinigung und Trocknen abgetrennter Zucker", "Lactose Feuchte, wenn &gt; 5 %"),
    ("8.10.1", 8, "Milch/Milchpulver ( 26 )", "Durch ein- oder mehrmaliges Melken gewonnenes Milchdrüsensekret; kann auch konzentriert und/oder getrocknet sein", "Rohprotein Rohfett Feuchte, wenn &gt; 5 %"),
    ("8.11.1", 8, "Magermilch/Magermilchkonzentrat/Magermilchpulver ( 26 )", "Milch, deren Fettgehalt durch Abscheiden reduziert wurde. Kann auch konzentriert und/oder getrocknet sein", "Rohprotein Feuchte, wenn &gt; 5 %"),
    ("8.12.1", 8, "Milchfett", "Erzeugnis, das durch Entrahmen von Milch gewonnen wird", "Rohfett"),
    ("8.13.1", 8, "Milcheiweißpulver", "Erzeugnis, das durch Trocknen der Eiweißbestandteile entsteht, die aus Milch durch chemische oder physikalische Behandlung gewonnen werden", "Rohprotein Feuchte, wenn &gt; 8 %"),
    ("8.14.1", 8, "Kondensierte und evaporierte Milch und deren Erzeugnisse", "Kondensierte und evaporierte Milch und Erzeugnisse, die bei der Herstellung oder Verarbeitung dieser Erzeugnisse anfallen", "Rohprotein Rohfett Feuchte, wenn &gt; 5 %"),
    ("8.15.1", 8, "Milchpermeat/Milchpermeatpulver ( 26 )", "Erzeugnis, das bei der Ultra-, Nano- oder Mikrofiltration von Milch anfällt (Membrandurchgang) und dem ein Teil der Lactose entzogen sein kann. Verfahren der Umkehrosmose und Konzentrierung und/oder Trocknung können angewandt werden", "Rohasche Rohprotein Lactose Feuchte, wenn &gt; 8 %"),
    ("8.16.1", 8, "Milchretentat/Milchretentatpulver ( 26 )", "Erzeugnis, das bei der Ultra-, Nano- oder Mikrofiltration von Milch anfällt (durch Membran zurückgehalten); kann auch konzentriert und/oder getrocknet sein", "Rohprotein Rohasche Lactose Feuchte, wenn &gt; 8 %"),
    ("8.17.1", 8, "Molke/Molkenpulver ( 26 )", "Erzeugnis, das bei der Herstellung von Käse, Quark oder Kasein oder ähnlichen Prozessen anfällt; kann auch konzentriert und/oder getrocknet sein Bei Bestimmung als Einzelfutter gilt Folgendes: —", "Kann bis zu 0,5 % Phosphate enthalten, z. B. Polyphosphate (wie etwa Natriumhexametaphosphat) oder Diphosphate (wie etwa Tetranatriumpyrophosphat), die eingesetzt werden, um die Viskosität zu verringern und bei der Verarbeitung Proteine zu stabilisieren;"),
    ("8.18.1", 8, "Molke/Molkenpulver, lactosearm ( 26 )", "Molke, der ein Teil der Lactose entzogen wurde; kann auch konzentriert und/oder getrocknet sein Bei Bestimmung als Einzelfutter gilt Folgendes: —", "Kann bis zu 0,5 % Phosphate enthalten, z. B. Polyphosphate (wie etwa Natriumhexametaphosphat) oder Diphosphate (wie etwa Tetranatriumpyrophosphat), die eingesetzt werden, um die Viskosität zu verringern und bei der Verarbeitung Proteine zu stabilisieren;"),
    ("8.19.1", 8, "Molkeneiweiß/Molkeneiweißpulver ( 26 )", "Erzeugnis, das durch Trocknen der Molkeneiweißbestandteile entsteht, die aus Milch durch chemische oder physikalische Behandlung gewonnen werden; kann auch konzentriert und/oder getrocknet sein Bei Bestimmung als Einzelfutter gilt Folgendes: —", "Kann bis zu 0,5 % Phosphate enthalten, z. B. Polyphosphate (wie etwa Natriumhexametaphosphat) oder Diphosphate (wie etwa Tetranatriumpyrophosphat), die eingesetzt werden, um die Viskosität zu verringern und bei der Verarbeitung Proteine zu stabilisieren;"),
    ("8.20.1", 8, "Molke/Molkenpulver, mineralstoffarm, lactosearm ( 26 )", "Molke, der ein Teil der Lactose und Mineralstoffe entzogen wurde; kann auch konzentriert und/oder getrocknet sein Bei Bestimmung als Einzelfutter gilt Folgendes: —", "Kann bis zu 0,5 % Phosphate enthalten, z. B. Polyphosphate (wie etwa Natriumhexametaphosphat) oder Diphosphate (wie etwa Tetranatriumpyrophosphat), die eingesetzt werden, um die Viskosität zu verringern und bei der Verarbeitung Proteine zu stabilisieren;"),
    ("8.21.1", 8, "Molkenpermeat/Molkenpermeatpulver ( 26 )", "Erzeugnis, das bei der Ultra-, Nano- oder Mikrofiltration von Molke anfällt (Membrandurchgang) und dem die Lactose teilweise entzogen sein kann. Verfahren der Umkehrosmose und Konzentrierung und/oder Trocknung können angewandt werden. Bei Bestimmung als Einzelfutter gilt Folgendes: —", "Kann bis zu 0,5 % Phosphate enthalten, z. B. Polyphosphate (wie etwa Natriumhexametaphosphat) oder Diphosphate (wie etwa Tetranatriumpyrophosphat), die eingesetzt werden, um die Viskosität zu verringern und bei der Verarbeitung Proteine zu stabilisieren;"),
    ("8.22.1", 8, "Molkenretentat/Molkenretentatpulver ( 26 )", "Erzeugnis, das bei der Ultra-, Nano- oder Mikrofiltration von Molke anfällt (durch Membran zurückgehalten); kann auch konzentriert und/oder getrocknet sein. Bei Bestimmung als Einzelfutter gilt Folgendes: —", "Kann bis zu 0,5 % Phosphate enthalten, z. B. Polyphosphate (wie etwa Natriumhexametaphosphat) oder Diphosphate (wie etwa Tetranatriumpyrophosphat), die eingesetzt werden, um die Viskosität zu verringern und bei der Verarbeitung Proteine zu stabilisieren;"),
    # ──────────────────────────────────────────────────────────── Kap 9
    ("9.1.1", 9, "Tierische Nebenprodukte ( 27 )", "Warmblütige Landtiere oder Teile davon, frisch, gefroren, gekocht, säurebehandelt oder getrocknet", "Rohprotein Rohfett Feuchte, wenn &gt; 8 %"),
    ("9.2.1", 9, "Tierfett ( 28 )", "Erzeugnis, das aus Fett warmblütiger Landtiere besteht. Bei Extraktion mit Lösungsmitteln kann das Erzeugnis bis zu 0,1 % Hexan enthalten", "Rohfett Feuchte, wenn &gt; 1 %"),
    ("9.3.1", 9, "Imkerei-Nebenerzeugnisse", "Honig, Bienenwachs, Gelée Royal, Propolis, Pollen, verarbeitet oder naturbelassen", "Gesamtzuckergehalt berechnet als Saccharose"),
    ("9.4.1", 9, "Verarbeitetes tierisches Protein ( 28 )", "Erzeugnis, das durch Erhitzen, Trocknen und Mahlen von Körperteilen warmblütiger Landtiere gewonnen wird und dessen Fett teilweise extrahiert oder physikalisch entzogen sein kann. Bei Extraktion mit Lösungsmitteln kann das Erzeugnis bis zu 0,1 % Hexan enthalten", "Rohprotein Rohfett Rohasche Feuchte, wenn &gt; 8 %"),
    ("9.5.1", 9, "Proteine aus der Gelatinegewinnung ( 28 )", "Genusstaugliche, getrocknete tierische Proteine, die bei der Gelatineherstellung gewonnen werden", "Rohprotein Rohfett Rohasche Feuchte, wenn &gt; 8 %"),
    ("9.6.1", 9, "Hydrolysierte Tierproteine ( 28 )", "Hydrolysierte Proteine, die unter Einwirkung von Wärme und/oder Druck oder durch chemische, mikrobiologische oder enzymatische Hydrolyse tierischen Proteins gewonnen werden", "Rohprotein Feuchte, wenn &gt; 8 %"),
    ("9.7.1", 9, "Blutmehl ( 28 )", "Erzeugnis, das durch Wärmebehandlung von Blut geschlachteter warmblütiger Tiere gewonnen wird", "Rohprotein Feuchte, wenn &gt; 8 %"),
    ("9.8.1", 9, "Bluterzeugnisse ( 27 )", "Erzeugnisse, die aus Blut oder Fraktionen von Blut geschlachteter warmblütiger Tiere gewonnen werden, u. a. getrocknetes/gefrorenes/flüssiges Plasma, getrocknetes Vollblut, getrocknete/gefrorene/flüssige Erythrozyten oder Fraktionen davon und Mischungen", "Rohprotein Feuchte, wenn &gt; 8 %"),
    ("9.9.1", 9, "Catering-Rückfluss (wiederverwertete Küchenabfälle und Speisereste)", "Alle aus Restaurants, Catering-Einrichtungen und Küchen, einschließlich Groß- und Haushaltsküchen, stammenden Lebensmittelreste, die Material tierischen Ursprungs enthalten, einschließlich gebrauchtes Speiseöl", "Rohprotein Rohfett Rohasche Feuchte, wenn &gt; 8 %"),
    ("9.10.1", 9, "Kollagen ( 28 )", "Eiweißbasiertes Erzeugnis aus den Knochen, Häuten, Fellen und Sehnen von Tieren", "Rohprotein Feuchte, wenn &gt; 8 %"),
    ("9.11.1", 9, "Federnmehl", "Erzeugnis, das durch Trocknen und Mahlen von Federn geschlachteter Tiere gewonnen wird und hydrolysiert sein kann", "Rohprotein Feuchte, wenn &gt; 8 %"),
    ("9.12.1", 9, "Gelatine ( 28 )", "Natürliches, lösliches Protein, gelierend oder nichtgelierend, das durch die teilweise Hydrolyse von Kollagen aus Knochen, Häuten und Fellen, Sehnen und Bändern von Tieren gewonnen wird", "Rohprotein Feuchte, wenn &gt; 8 %"),
    ("9.13.1", 9, "Grieben ( 28 )", "Erzeugnis, das bei der Gewinnung von Talg, Schmalz oder sonstigen extrahierten oder physikalisch entzogenen tierischen Fetten anfällt, in frischem, gefrorenem oder getrockneten Zustand. Bei Extraktion mit Lösungsmitteln kann das Erzeugnis bis zu 0,1 % Hexan enthalten", "Rohprotein Rohfett Rohasche Feuchte, wenn &gt; 8 %"),
    ("9.14.1", 9, "Erzeugnisse tierischen Ursprungs ( 27 )", "Ehemalige Lebensmittel, die tierische Erzeugnisse enthalten, behandelt oder unbehandelt, beispielsweise frisch, gefroren oder getrocknet", "Rohprotein Rohfett Feuchte, wenn &gt; 8 %"),
    ("9.15.1", 9, "Eier", "Ganze Hühnereier von Gallus gallus L., mit oder ohne Schale", ""),
    ("9.15.2", 9, "Eiklar", "Erzeugnis, das durch Trennen von Schale und Dotter von Eiern gewonnen wird, pasteurisiert und möglicherweise denaturiert", "Rohprotein Gegebenenfalls Methode der Denaturierung"),
    ("9.15.3", 9, "Eiprodukte, getrocknet", "Erzeugnisse, die aus getrockneten und pasteurisierten Eiern ohne Schale oder aus einem Gemisch mit unterschiedlichen Anteilen von getrocknetem Eiklar oder getrocknetem Eidotter bestehen", "Rohprotein Rohfett Feuchte, wenn &gt; 5 %"),
    ("9.15.4", 9, "Eipulver, gezuckert", "Getrocknete ganze Eier oder Eistücke, denen Zucker zugesetzt wird", "Rohprotein Rohfett Feuchte, wenn &gt; 5 %"),
    ("9.15.5", 9, "Eierschalen, getrocknet", "Erzeugnis, das nach der Trennung von Eiklar und Dotter von Geflügeleiern anfällt; die Schalen sind getrocknet", "Rohasche"),
    ("9.16.1", 9, "Wirbellose Landtiere ( 27 )", "Wirbellose Landtiere, ganz oder Teile davon, in allen Entwicklungsstufen, ausgenommen human- oder tierpathogene Arten, behandelt oder unbehandelt, beispielsweise frisch, gefroren oder getrocknet", ""),
    ("9.17.1", 9, "Chondroitinsulfat", "Erzeugnis, das durch Extraktion aus Sehnen, Knochen und anderen tierischen knorpelhaltigen Geweben und weichen Bindegeweben gewonnen wird", "Natrium"),
    # ──────────────────────────────────────────────────────────── Kap 10
    ("10.1.1", 10, "Wirbellose Wassertiere ( 29 )", "Wirbellose Meeres- oder Süßwassertiere, ganz oder Teile davon, in allen Entwicklungsstufen, ausgenommen human- oder tierpathogene Arten, behandelt oder unbehandelt, beispielsweise frisch, gefroren oder getrocknet", ""),
    ("10.2.1", 10, "Nebenprodukte von Wassertieren ( 29 )", "Erzeugnisse, die aus Betrieben oder Anlagen stammen, die Erzeugnisse für den menschlichen Verzehr zubereiten oder herstellen, behandelt oder unbehandelt, beispielsweise frisch, gefroren oder getrocknet", "Rohprotein Rohfett Rohasche"),
    ("10.3.1", 10, "Krustentiermehl", "Erzeugnis, das durch Erhitzen, Pressen und Trocknen von Krustentieren, auch freilebenden und Zuchtgarnelen, gewonnen wird", "Rohprotein Rohfett Rohasche, wenn &gt; 20 % Feuchte, wenn &gt; 8 %"),
    ("10.4.1", 10, "Fisch ( 30 )", "Fisch oder Fischteile, frisch, gefroren, gekocht, säurebehandelt oder getrocknet", "Rohprotein Feuchte, wenn &gt; 8 %"),
    ("10.4.2", 10, "Fischmehl ( 30 )", "Erzeugnis, das durch Erhitzen, Pressen und Trocknen ganzer Fische oder von Fischteilen anfällt, und dem vor dem Trocknen wieder Fischpresssaft zugesetzt worden sein kann", "Rohprotein Rohfett Rohasche, wenn &gt; 20 % Feuchte, wenn &gt; 8 %"),
    ("10.4.3", 10, "Fischpresssaft", "Erzeugnis, das bei der Gewinnung von Fischmehl anfällt und durch Säurekonservierung oder Trocknung abgetrennt und stabilisiert worden ist", "Rohprotein Rohfett Feuchte, wenn &gt; 5 %"),
    ("10.4.4", 10, "Fischeiweiß, hydrolysiert", "Erzeugnis, das durch Säurehydrolyse von Fisch oder Fischteilen gewonnen und häufig durch Trocknen konzentriert wird", "Rohprotein Rohfett Rohasche, wenn &gt; 20 % Feuchte, wenn &gt; 8 %"),
    ("10.4.5", 10, "Grätenmehl", "Erzeugnis, das durch Erhitzen, Pressen und Trocknen von Fischteilen anfällt und vorwiegend aus Gräten besteht", "Rohasche"),
    ("10.4.6", 10, "Fischöl", "Öl von Fischen oder Fischteilen, das zum Wasserentzug zentrifugiert wird (gegebenenfalls mit Angaben zur Tierart, z. B. Lebertran von Dorsch)", "Rohfett Feuchte, wenn &gt; 1 %"),
    ("10.4.7", 10, "Fischöl, gehärtet", "Öl, das durch Härtung von Fischöl gewonnen wird", "Feuchte, wenn &gt; 1 %"),
    ("10.5.1", 10, "Krillöl", "Öl, das durch Kochen und Pressen von Krill des Meeresplanktons gewonnen und zum Wasserentzug zentrifugiert wird", "Feuchte, wenn &gt; 1 %"),
    ("10.5.2", 10, "Krilleiweißkonzentrat, hydrolysiert", "Erzeugnis, das durch enzymatische Hydrolyse von Krill oder Krillteilen gewonnen und häufig durch Trocknen konzentriert wird", "Rohprotein Rohfett Rohasche, wenn &gt; 20 % Feuchte, wenn &gt; 8 %"),
    ("10.6.1", 10, "Mehl aus Meereswürmern", "Erzeugnis, das durch Erhitzen und Trocknen von im Meer lebenden Ringelwürmern, auch Nereis virens M. Sars, oder Teilen davon gewonnen wird", "Fett Rohasche, wenn &gt; 20 % Feuchte, wenn &gt; 8 %"),
    ("10.7.1", 10, "Mehl aus marinem Zooplankton", "Erzeugnis, das durch Erhitzen, Pressen und Trocknen marinen Zooplanktons, beispielsweise von Krill, gewonnen wird", "Rohprotein Rohfett Rohasche, wenn &gt; 20 % Feuchte, wenn &gt; 8 %"),
    ("10.7.2", 10, "Öl aus marinem Zooplankton", "Öl, das durch Kochen und Pressen marinen Zooplanktons gewonnen und zum Wasserentzug zentrifugiert wird", "Feuchte, wenn &gt; 1 %"),
    ("10.8.1", 10, "Weichtiermehl", "Erzeugnis, das durch Erhitzen und Trocknen von Weichtieren, auch Tintenfische und Muscheln, oder Teilen davon gewonnen wird", "Rohprotein Rohfett Rohasche, wenn &gt; 20 % Feuchte, wenn &gt; 8 %"),
    ("10.9.1", 10, "Tintenfischmehl", "Erzeugnis, das durch Erhitzen, Pressen und Trocknen von Tintenfischen oder von Tintenfischteilen gewonnen wird", "Rohprotein Rohfett Rohasche, wenn &gt; 20 % Feuchte, wenn &gt; 8 %"),
    # ──────────────────────────────────────────────────────────── Kap 11
    ("11.1.1", 11, "Calciumcarbonat ( 31 ) [Kalkstein]", "Erzeugnis, das durch Mahlen calciumcarbonathaltiger (CaCO 3 ) Erzeugnisse wie Kalkstein oder durch Ausfällen aus sauren Lösungen gewonnen wird. Kann bis zu 0,25 % Propylenglycol enthalten. Kann bis zu 0,1 % Mahlhilfen enthalten", "Calcium, salzsäureunlösliche Asche, wenn &gt; 5 %"),
    ("11.1.2", 11, "Kohlensaurer Muschelkalk", "Aus den Schalen von Meeresweichtieren, beispielsweise Austern oder Muscheln gewonnenes Erzeugnis nativer Herkunft, gemahlen oder gekörnt", "Calcium, salzsäureunlösliche Asche, wenn &gt; 5 %"),
    ("11.1.3", 11, "Calcium-Magnesiumcarbonat", "Natürliches Gemisch aus Calciumcarbonat (CaCO 3 ) und Magnesiumcarbonat (MgCO 3 ). Kann bis zu 0,1 % Mahlhilfen enthalten", "Calcium, Magnesium, salzsäureunlösliche Asche, wenn &gt; 5 %"),
    ("11.1.4", 11, "Kohlensaurer Algenkalk (Maerl-Kalk)", "Aus Kalkalgen gewonnenes Erzeugnis nativer Herkunft, gemahlen oder gekörnt", "Calcium, salzsäureunlösliche Asche, wenn &gt; 5 %"),
    ("11.1.5", 11, "Lithothamnium", "Aus Kalkalgen ( Phymatolithon calcareum (Pall.)) gewonnenes Erzeugnis nativer Herkunft, gemahlen oder gekörnt", "Calcium, salzsäureunlösliche Asche, wenn &gt; 5 %"),
    ("11.1.6", 11, "Calciumchlorid", "Calciumchlorid (CaCl 2 ). Kann bis zu 0,2 % Bariumsulfat enthalten", "Calcium, salzsäureunlösliche Asche, wenn &gt; 5 %"),
    ("11.1.7", 11, "Calciumhydroxid", "Calciumhydroxid (Ca(OH) 2 ). Kann bis zu 0,1 % Mahlhilfen enthalten", "Calcium, salzsäureunlösliche Asche, wenn &gt; 5 %"),
    ("11.1.8", 11, "Calciumsulfat, wasserfrei", "Calciumsulfat (CaSO 4 ), wasserfrei, das durch Vermahlen von Calciumsulfat, wasserfrei, oder Dehydratisierung von Calciumsulfat-Dihydrat gewonnen wird", "Calcium, salzsäureunlösliche Asche, wenn &gt; 5 %"),
    ("11.1.9", 11, "Calciumsulfat-Hemihydrat", "Calciumsulfat-Hemihydrat (CaSO 4 × ½ H 2 O), das durch Entfernen eines Teils des Wassers aus Calciumsulfat-Dihydrat gewonnen wird", "Calcium, salzsäureunlösliche Asche, wenn &gt; 5 %"),
    ("11.1.10", 11, "Calciumsulfat-Dihydrat", "Calciumsulfat-Dihydrat (CaSO 4 × 2 H 2 O), das durch Vermahlen von Calciumsulfat-Dihydrat oder Rehydratisierung von Calciumsulfat-Hemihydrat gewonnen wird", "Calcium, salzsäureunlösliche Asche, wenn &gt; 5 %"),
    ("11.1.11", 11, "Calciumsalze organischer Säuren ( 32 )", "Calciumsalze genusstauglicher organischer Säuren mit mindestens 4 Kohlenstoffatomen", "Calcium, organische Säure"),
    ("11.1.12", 11, "Calciumoxid", "Calciumoxid (CaO), das durch Kalzinierung (Brennen) von Kalkstein nativer Herkunft gewonnen wird. Kann bis zu 0,1 % Mahlhilfen enthalten", "Calcium, salzsäureunlösliche Asche, wenn &gt; 5 %"),
    ("11.1.13", 11, "Calciumgluconat", "Calciumsalz von Gluconsäure, Ca(C 6 H 11 O 7 ) 2 , und dessen Hydrate", "Calcium, salzsäureunlösliche Asche, wenn &gt; 5 %"),
    ("11.1.15", 11, "Calciumsulfat/Calciumcarbonat", "Erzeugnis, das bei der Gewinnung von Natriumcarbonat anfällt", "Calcium, salzsäureunlösliche Asche, wenn &gt; 5 %"),
    ("11.1.16", 11, "Calciumpidolat", "L-Calciumpidolat (C 5 H 6 CaNO 3 ). Kann bis zu 1,5 % Glutaminsäure und verwandte Stoffe enthalten", "Calcium, salzsäureunlösliche Asche, wenn &gt; 5 %"),
    ("11.1.17", 11, "Calciumcarbonat-Magnesiumoxid", "Erzeugnis, das durch Erhitzen natürlicher, Calcium und Magnesium enthaltender Stoffe wie Dolomit gewonnen wird. Kann bis zu 0,1 % Mahlhilfen enthalten", "Calcium, Magnesium"),
    ("11.2.1", 11, "Magnesiumoxid", "Kalziniertes Magnesiumoxid (MgO) mit einem Gehalt von mindestens 70 % MgO", "Magnesium, salzsäureunlösliche Asche, wenn &gt; 15 %"),
    ("11.2.2", 11, "Magnesiumsulfat-Heptahydrat", "Magnesiumsulfat (MgSO 4 × 7 H 2 O)", "Magnesium, Schwefel, salzsäureunlösliche Asche, wenn &gt; 15 %"),
    ("11.2.3", 11, "Magnesiumsulfat-Monohydrat", "Magnesiumsulfat (MgSO 4 × H 2 O)", "Magnesium, Schwefel, salzsäureunlösliche Asche, wenn &gt; 15 %"),
    ("11.2.4", 11, "Magnesiumsulfat, wasserfrei", "Wasserfreies Magnesiumsulfat (MgSO 4 )", "Magnesium, Schwefel, salzsäureunlösliche Asche, wenn &gt; 10 %"),
    ("11.2.5", 11, "Magnesiumpropionat", "Magnesiumpropionat (C 6 H 10 MgO 4 )", "Magnesium"),
    ("11.2.6", 11, "Magnesiumchlorid", "Magnesiumchlorid (MgCl 2 ) oder Lösung, die durch Eindampfen von Meerwasser nach Ablagerung von Natriumchlorid gewonnen wird", "Magnesium, Chlor, salzsäureunlösliche Asche, wenn &gt; 10 %"),
    ("11.2.7", 11, "Magnesiumcarbonat", "Natürliches Magnesiumcarbonat (MgCO 3 )", "Magnesium, salzsäureunlösliche Asche, wenn &gt; 10 %"),
    ("11.2.8", 11, "Magnesiumhydroxid", "Magnesiumhydroxid (Mg(OH) 2 )", "Magnesium, salzsäureunlösliche Asche, wenn &gt; 10 %"),
    ("11.2.9", 11, "Kaliummagnesiumsulfat", "Kaliummagnesiumsulfat", "Magnesium, Kalium, salzsäureunlösliche Asche, wenn &gt; 10 %"),
    ("11.2.10", 11, "Magnesiumsalze organischer Säuren ( 32 )", "Magnesiumsalze genusstauglicher organischer Säuren mit mindestens 4 Kohlenstoffatomen", "Magnesium, organische Säure"),
    ("11.3.1", 11, "Dicalciumphosphat ( 33 ) [Calciumhydrogenorthophosphat]", "Calciummonohydrogenphosphat aus Knochen oder anorganischen Quellen (CaHPO 4 × H 2 O) Ca/P &gt; 1,2 Kann bis zu 3 % Chlorid enthalten, ausgedrückt als NaCl", "Calcium, Gesamtphosphorgehalt, in 2 %iger Zitronensäure unlöslicher Phosphor, wenn &gt; 10 %, salzsäureunlösliche Asche, wenn &gt; 5 %"),
    ("11.3.2", 11, "Monodicalciumphosphat", "Erzeugnis, das chemisch gewonnen wird und aus Mono- und Dicalciumphosphat besteht (CaHPO 4 Ca(H 2 PO 4 ) 2 × H 2 O) 0,8&lt; Ca/P &lt; 1,3", "Gesamtphosphorgehalt, Calcium, in 2 %iger Zitronensäure unlöslicher Phosphor, wenn &gt; 10 %"),
    ("11.3.3", 11, "Monocalciumphosphat [Calciumtetrahydrogendiorthophosphat]", "Calcium-bis-dihydrogenphosphat (Ca(H 2 PO 4 ) 2 × H 2 O) Ca/P &gt; 0,9", "Gesamtphosphorgehalt, Calcium, in 2 %iger Zitronensäure unlöslicher Phosphor, wenn &gt; 10 %"),
    ("11.3.4", 11, "Tricalciumphosphat [Tricalcium orthophosphat]", "Tricalciumphosphat aus Knochen oder anorganischen Quellen (Ca 3 (PO 4 ) 2 × H 2 O) Ca/P &gt; 1,3", "Calcium, Gesamtphosphorgehalt, in 2 %iger Zitronensäure unlöslicher Phosphor, wenn &gt; 10 %"),
    ("11.3.5", 11, "Calcium-Magnesiumphosphat", "Calcium-Magnesiumphosphat", "Calcium, Magnesium, Gesamtphosphorgehalt, in 2 %iger Zitronensäure unlöslicher Phosphor, wenn &gt; 10 %"),
    ("11.3.6", 11, "Phosphat, entfluoriert", "Natürliches Phosphat, gebrannt und weitergehend thermisch behandelt zum Entfernen von Verunreinigungen", "Gesamtphosphorgehalt, Calcium, Natrium in 2 %iger Zitronensäure unlöslicher Phosphor, wenn &gt; 10 %, salzsäureunlösliche Asche, wenn &gt; 5 %"),
    ("11.3.7", 11, "Dicalciumpyrophosphat [Dicalciumdiphosphat]", "Dicalciumpyrophosphat", "Gesamtphosphorgehalt, Calcium, in 2 %iger Zitronensäure unlöslicher Phosphor, wenn &gt; 10 %"),
    ("11.3.8", 11, "Magnesiumphosphat", "Erzeugnis, das aus einbasischem und/oder zwei- und dreibasischem Magnesiumphosphat besteht", "Gesamtphosphorgehalt, Magnesium, in 2 %iger Zitronensäure unlöslicher Phosphor, wenn &gt; 10 %, salzsäureunlösliche Asche, wenn &gt; 10 %"),
    ("11.3.9", 11, "Natrium-Calcium-Magnesium-Phosphat", "Erzeugnis aus Natrium-Calcium-Magnesium-Phosphat", "Gesamtphosphorgehalt, Magnesium, Calcium, Natrium, in 2 %iger Zitronensäure unlöslicher Phosphor, wenn &gt; 10 %"),
    ("11.3.10", 11, "Mononatriumphosphat [Natriumdihydrogenorthophosphat]", "Mononatriumphosphat (NaH 2 PO 4 × H 2 O)", "Gesamtphosphorgehalt, Natrium, in 2 %iger Zitronensäure unlöslicher Phosphor, wenn &gt; 10 %"),
    ("11.3.11", 11, "Dinatriumphosphat [Dinatriumhydrogenorthophosphat]", "Dinatriumphosphat (Na 2 HPO 4 × H 2 O)", "Gesamtphosphorgehalt, Natrium, in 2 %iger Zitronensäure unlöslicher Phosphor, wenn &gt; 10 %"),
    ("11.3.12", 11, "Trinatriumphosphat [Trinatriumorthophosphat]", "Trinatriumphosphat (Na 3 PO 4 )", "Gesamtphosphorgehalt, Natrium, in 2 %iger Zitronensäure unlöslicher Phosphor, wenn &gt; 10 %"),
    ("11.3.13", 11, "Natriumpyrophosphat [Tetranatriumdiphosphat]", "Natriumpyrophosphat (Na 4 P 2 O 7 )", "Gesamtphosphorgehalt, Natrium, in 2 %iger Zitronensäure unlöslicher Phosphor, wenn &gt; 10 %"),
    ("11.3.14", 11, "Monokaliumphosphat [Kaliumdihydrogenorthophosphat]", "Monokaliumphosphat (KH 2 PO 4 × H 2 O)", "Gesamtphosphorgehalt, Kalium, in 2 %iger Zitronensäure unlöslicher Phosphor, wenn &gt; 10 %"),
    ("11.3.15", 11, "Dikaliumphosphat [Dikaliumhydrogenorthophosphat]", "Dikaliumphosphat (K 2 HPO 4 × H 2 O)", "Gesamtphosphorgehalt, Kalium, in 2 %iger Zitronensäure unlöslicher Phosphor, wenn &gt; 10 %"),
    ("11.3.16", 11, "Calcium-Natrium-Phosphat", "Calcium-Natrium-Phosphat (CaNaPO 4 )", "Gesamtphosphorgehalt, Calcium, Natrium, in 2 %iger Zitronensäure unlöslicher Phosphor, wenn &gt; 10 %"),
    ("11.3.17", 11, "Monoammoniumphosphat [Ammoniumdihydrogenorthophosphat]", "Monoammoniumphosphat (NH 4 H 2 PO 4 )", "Gesamtstickstoffgehalt, Gesamtphosphorgehalt, in 2 %iger Zitronensäure unlöslicher Phosphor, wenn &gt; 10 %"),
    ("11.3.18", 11, "Diammoniumphosphat [Diammoniumhydrogenorthophosphat]", "Diammoniumphosphat ((NH 4 ) 2 HPO 4 )", "Gesamtstickstoffgehalt Gesamtphosphorgehalt In 2 %iger Zitronensäure unlöslicher Phosphor, wenn &gt; 10 %"),
    ("11.3.19", 11, "Natriumtripolyphosphat [Pentanatriumtriphosphat]", "Natriumtripolyphosphat (Na 5 P 3 O 9 )", "Gesamtphosphorgehalt, Natrium, in 2 %iger Zitronensäure unlöslicher Phosphor, wenn &gt; 10 %"),
    ("11.3.20", 11, "Natrium-Magnesium-Phosphat", "Natrium-Magnesium-Phosphat (MgNaPO 4 )", "Gesamtphosphorgehalt, Magnesium, Natrium, in 2 %iger Zitronensäure unlöslicher Phosphor, wenn &gt; 10 %"),
    ("11.3.21", 11, "Magnesiumhypophosphit", "Magnesiumhypophosphit (Mg(H 2 PO 2 ) 2 × 6H 2 O", "Magnesium Gesamtphosphorgehalt In 2 %iger Zitronensäure unlöslicher Phosphor, wenn &gt; 10 %"),
    ("11.3.22", 11, "Knochenfuttermehl, entleimt", "Entfettete, entleimte, sterilisierte, gemahlene Knochen", "Gesamtphosphorgehalt, Calcium, salzsäureunlösliche Asche, wenn &gt; 10 %"),
    ("11.3.23", 11, "Knochenasche", "Mineralische Rückstände der Veraschung, Verbrennung oder Vergasung tierischer Nebenprodukte", "Gesamtphosphorgehalt, Calcium, salzsäureunlösliche Asche, wenn &gt; 10 %"),
    ("11.3.24", 11, "Calciumpolyphosphat", "Heterogene Gemische von Calciumsalzen kondensierter Polyphosphorsäuren der allgemeinen Formel H n + 2 P n O 3n + 1 , wobei „n“ mindestens 2 ist", "Gesamtphosphorgehalt, Calcium, in 2 %iger Zitronensäure unlöslicher Phosphor, wenn &gt; 10 %"),
    ("11.3.25", 11, "Calciumdihydrogendiphosphat", "Mono-Calciumdihydrogenpyrophosphat (CaH 2 P 2 O 7 )", "Gesamtphosphorgehalt, Calcium, in 2 %iger Zitronensäure unlöslicher Phosphor, wenn &gt; 10 %"),
    ("11.3.26", 11, "Saures Magnesiumpyrophosphat", "Saures Magnesiumpyrophosphat (MgH 2 P 2 O 7 ). Hergestellt aus reiner Phosphorsäure und reinem Magnesiumhydroxid oder Magnesiumoxid durch Verdampfen von Wasser und Kondensation des Orthophosphats zu Diphosphat", "Gesamtphosphorgehalt, Magnesium, in 2 %iger Zitronensäure unlöslicher Phosphor, wenn &gt; 10 %"),
    ("11.3.27", 11, "Dinatriumdihydrogendiphosphat", "Dinatriumdihydrogendiphosphat (Na 2 H 2 P 7 O 7 )", "Gesamtphosphorgehalt, Calcium, in 2 %iger Zitronensäure unlöslicher Phosphor, wenn &gt; 10 %"),
    ("11.3.28", 11, "Trinatriumdiphosphat", "Trinatrium-Monohydrogendiphosphat (wasserfrei: Na 3 HP 2 O 7 ; Monohydrat: Na 3 HP 2 O 7 × H 2 O)", "Gesamtphosphorgehalt, Natrium, in 2 %iger Zitronensäure unlöslicher Phosphor, wenn &gt; 10 %"),
    ("11.3.29", 11, "Natriumpolyphosphat [Natriumhexametaphosphat]", "Heterogene Gemische von Natriumsalzen kondensierter linearer Polyphosphorsäuren der allgemeinen Formel H n + 2 P n O 3n + 1 , wobei „n“ mindestens 2 ist", "Gesamtphosphorgehalt, Natrium, in 2 %iger Zitronensäure unlöslicher Phosphor, wenn &gt; 10 %"),
    ("11.3.30", 11, "Trikaliumphosphat", "Trikalium-Monophosphat (wasserfrei: K 3 PO 4 ; als Hydrat: K 3 PO 4 × n H 2 O (n = 1 oder 3)).", "Gesamtphosphorgehalt, Kalium, in 2 %iger Zitronensäure unlöslicher Phosphor, wenn &gt; 10 %"),
    ("11.3.31", 11, "Tetrakaliumdiphosphat", "Tetrakaliumpyrophospat (K 4 P 2 O 7 )", "Gesamtphosphorgehalt, Calcium, in 2 %iger Zitronensäure unlöslicher Phosphor, wenn &gt; 10 %"),
    ("11.3.32", 11, "Pentakaliumtriphosphat", "Pentakaliumtripolyphosphat (K 5 P 3 O 10 )", "Gesamtphosphorgehalt, Calcium, in 2 %iger Zitronensäure unlöslicher Phosphor, wenn &gt; 10 %"),
    ("11.3.33", 11, "Kaliumpolyphosphat", "Heterogene Gemische von Kaliumsalzen kondensierter linearer Polyphosphorsäuren der allgemeinen Formel H n + 2 P n O 3n + 1 , wobei „n“ mindestens 2 ist", "Gesamtphosphorgehalt, Kalium, in 2 %iger Zitronensäure unlöslicher Phosphor, wenn &gt; 10 %"),
    ("11.3.34", 11, "Calciumnatriumpolyphosphat", "Calciumnatriumpolyphosphat", "Gesamtphosphorgehalt, Calcium, Natrium, in 2 %iger Zitronensäure unlöslicher Phosphor, wenn &gt; 10 %"),
    ("11.4.1", 11, "Natriumchlorid ( 31 )", "Natriumchlorid (NaCl) oder Erzeugnis, das durch Verdampfen und Kristallisieren von Salzlake (Vakuumsalz), Verdampfen von Meerwasser (Meersalz) oder durch Vermahlen von Steinsalz gewonnen wird", "Natrium, salzsäureunlösliche Asche, wenn &gt; 10 %"),
    ("11.4.2", 11, "Natriumbicarbonat [Natriumhydrogencarbonat]", "Natriumbicarbonat (NaHCO 3 )", "Natrium, salzsäureunlösliche Asche, wenn &gt; 10 %"),
    ("11.4.3", 11, "Natrium-/Ammonium(bi)carbonat [Natrium-/Ammonium(hydrogen)carbonat]", "Erzeugnis, das bei der Gewinnung von Natriumcarbonat und Natriumbicarbonat anfällt und Spuren von Ammoniumbicarbonat (höchstens 5 %) enthält", "Natrium, salzsäureunlösliche Asche, wenn &gt; 10 %"),
    ("11.4.4", 11, "Natriumcarbonat", "Natriumcarbonat (Na 2 CO 3 )", "Natrium, salzsäureunlösliche Asche, wenn &gt; 10 %"),
    ("11.4.5", 11, "Natriumsesquicarbonat [Trinatriumhydrogendicarbonat]", "Natriumsesquicarbonat (Na 3 H(CO 3 ) 2 )", "Natrium, salzsäureunlösliche Asche, wenn &gt; 10 %"),
    ("11.4.6", 11, "Natriumsulfat", "Natriumsulfat (Na 2 SO 4 ). Kann bis zu 0,3 % Methionin enthalten", "Natrium, salzsäureunlösliche Asche, wenn &gt; 10 %"),
    ("11.4.7", 11, "Natriumsalze organischer Säuren ( 32 )", "Natriumsalze genusstauglicher organischer Säuren mit mindestens 4 Kohlenstoffatomen", "Natrium, organische Säure"),
    ("11.5.1", 11, "Kaliumchlorid", "Kaliumchlorid (KCl) oder Erzeugnis, das durch Vermahlen natürlicher, kaliumchloridhaltiger Stoffe gewonnen wird", "Kalium, salzsäureunlösliche Asche, wenn &gt; 10 %"),
    ("11.5.2", 11, "Kaliumsulfat", "Kaliumsulfat (K 2 SO 4 )", "Kalium, salzsäureunlösliche Asche, wenn &gt; 10 %"),
    ("11.5.3", 11, "Kaliumcarbonat", "Kaliumcarbonat (K 2 CO 3 )", "Kalium, salzsäureunlösliche Asche, wenn &gt; 10 %"),
    ("11.5.4", 11, "Kaliumbicarbonat [Kaliumhydrogencarbonat]", "Kaliumbicarbonat (KHCO 3 )", "Kalium, salzsäureunlösliche Asche, wenn &gt; 10 %"),
    ("11.5.5", 11, "Kaliumsalze organischer Säuren ( 32 )", "Kaliumsalze genusstauglicher organischer Säuren mit mindestens 4 Kohlenstoffatomen", "Kalium, organische Säure"),
    ("11.6.1", 11, "Schwefelblüte", "Pulver aus natürlichen Schwefellagerstätten. Es fällt auch bei der Erdölraffination nach den gängigen Verfahren der Schwefelproduzenten an", "Schwefel"),
    ("11.7.1", 11, "Attapulgit", "Natürlich vorkommendes Magnesium-Aluminium-Silicium-Mineral", "Magnesium"),
    ("11.7.2", 11, "Quarz", "Natürlich vorkommendes Mineral, das durch Vermahlen quarzhaltiger Stoffe gewonnen wird. Kann bis zu 0,1 % Mahlhilfen enthalten.", ""),
    ("11.7.3", 11, "Cristobalit", "Kristalline Form und Modifikation von Siliciumdioxid (SiO 2 ,Quarz). Kann bis zu 0,1 % Mahlhilfen enthalten.", ""),
    ("11.8.1", 11, "Ammoniumsulfat", "Ammoniumsulfat ((NH 4 ) 2 SO 4 ), das durch chemische Synthese gewonnen wird", "Stickstoffgehalt, ausgedrückt als Rohprotein, Schwefel"),
    ("11.8.2", 11, "Ammoniumsulfat, Lösung", "Ammoniumsulfat in wässriger Lösung mit einem Gehalt an Ammoniumsulfat von mindestens 35 %", "Stickstoffgehalt, ausgedrückt als Rohprotein"),
    ("11.8.3", 11, "Ammoniumsalze organischer Säuren ( 32 )", "Ammoniumsalze genusstauglicher organischer Säuren mit mindestens 4 Kohlenstoffatomen", "Stickstoffgehalt, ausgedrückt als Rohprotein, organische Säure"),
    ("11.8.4", 11, "Ammoniumlaktat", "Ammoniumlaktat (CH 3 CHOHCOONH 4 ). Umfasst das Ammoniumlaktat, das bei der Fermentation von Molke mit Lactobacillus delbrueckii ssp. Bulgaricus , Lactococcus lactis ssp., Leuconostoc mesenteroides , Streptococcus thermophilus , Lactobacillus spp. oder Bifidobacterium spp. anfällt; enthält mindestens 44 % Stickstoff, ausgedrückt als Rohprotein Kann bis zu 0,8 % Phosphor, 0,9 % Kalium, 0,7 % Magnesium, 0,3 % Natrium, 0,3 % Sulfate, 0,1 % Chloride, 5 % Zucker und 0,1 % Silicon-Schaumverhüter enthalten", "Stickstoffgehalt, ausgedrückt als Rohprotein, Rohasche"),
    ("11.8.5", 11, "Ammoniumacetat", "Ammoniumacetat (CH 3 COONH 4 ) in wässriger Lösung mit einem Gehalt an Ammoniumacetat von mindestens 55 %", "Stickstoffgehalt, ausgedrückt als Rohprotein"),
    # ──────────────────────────────────────────────────────────── Kap 12
    ("12.1.1", 12, "Eiweiß aus Methylophilus methylotrophus", "Eiweißfermentationserzeugnis, das aus in einer Nährlösung auf Methanol-Basis vermehrten Bakterien Methylophilus methylotrophus (Stamm NCIMB 10.515) ( 34 ) gewonnen wird; Rohproteingehalt mindestens 68 %, Reflexionszahl mindestens 50", "Rohprotein Rohasche Rohfett"),
    ("12.1.2", 12, "Eiweiß aus Methylococcus capsulatus (Bath), Alca ligenes acidovorans , Bacillus brevis und Bacillus firmus", "Eiweißfermentationserzeugnis, das auf Erdgas (ca. 91 % Methan, 5 % Ethan, 2 % Propan, 0,5 % Isobutan, 0,5 % n-Butan), Ammonium und Mineralsalzen unter Verwendung von Methylococcus capsulatus (Bath) (Stamm NCIMB 11132), Alcaligenes acidovorans (Stamm NCIMB 12387), Bacillus brevis (Stamm NCIMB 13288) und Bacillus firmus (Stamm NCIMB 13280) ( 34 ) gezüchtet ist; Rohprotein mindestens 65 %", "Rohprotein Rohasche Rohfett"),
    ("12.1.3", 12, "Bakterielles Eiweiß aus Escherichia coli", "Eiweißerzeugnis, Nebenerzeugnis aus der Herstellung von Aminosäuren durch Vermehrung von Escherichia coli K12 ( 34 ) in Nährlösungen pflanzlichen oder chemischen Ursprungs, aus Ammoniak oder Mineralsalzen; kann hydrolysiert sein", "Rohprotein"),
    ("12.1.4", 12, "Bakterielles Eiweiß aus Corynebacterium glutamicum", "Eiweißerzeugnis, Nebenerzeugnis aus der Herstellung von Aminosäuren durch Vermehrung von Corynebacterium glutamicum ( 34 ) in Nährlösungen pflanzlichen oder chemischen Ursprungs, aus Ammoniak oder Mineralsalzen; kann hydrolysiert sein", "Rohprotein"),
    ("12.1.5", 12, "Hefen und Teile der Hefen [Bierhefe] [Hefeprodukt]", "Alle Hefen und deren Teile, die aus Saccharomyces cerevisiae , Saccharomyces carlsbergiensis , Kluyveromyces lactis , Kluyveromyces fragilis , Torulaspora delbrueckii , Candida utilis/Pichia jadinii , Saccharomyces uvarum , Saccharomyces ludwigii oder Brettanomyces ssp. ( 34 ) ( 35 ) in meist pflanzlichen Nährlösungen gewonnen werden, beispielsweise Melasse, Zuckersirup, Alkohol, Brennereirückstände, Getreide und stärkehaltige Erzeugnisse, Obstsaft, Molke, Milchsäure, Zucker, hydrolysierte Pflanzenfasern und Fermentationsnährstoffe wie Ammoniak oder Mineralsalze", "Feuchte, wenn &lt; 75 % oder &gt; 97 % Wenn Feuchte &lt; 75 %: Rohprotein"),
    ("12.1.6", 12, "Mycel-Silage aus der Herstellung von Penicillin", "Mycel (Stickstoffverbindungen), flüssiges Nebenerzeugnis aus der Penicillinherstellung mit Penicillium chrysogenum (Stamm ATCC 48271) ( 34 ) auf verschieden Quellen von Kohlenhydraten und ihren Hydrolysaten, das mit Hilfe von Lactobacillus brevis , L. plantarum , L. sake , L. collinoides und Streptococcus lactis zur Inaktivierung des Penicillins siliert und danach erhitzt worden ist; Stickstoff, ausgedrückt als Rohprotein, mindestens 7 %", "Stickstoffgehalt, ausgedrückt als Rohprotein Rohasche"),
    ("12.1.7", 12, "Hefen aus der Biodiesel-Herstellung", "Alle Hefen und deren Teile, die aus Yarrowia lipolytica ( 34 ) , ( 35 ) auf Nährlösungen von Pflanzenölen sowie Entschleimungsrückständen und Glycerinfraktionen aus der Herstellung von Biokraftstoffen gewonnen werden", "Feuchte, wenn &lt; 75 % oder &gt; 97 % Wenn Feuchte &lt; 75 %: Rohprotein"),
    ("12.2.1", 12, "Vinasse [eingedickte Melassenschlempe]", "Nebenerzeugnisse der industriellen Verarbeitung von Mosten/Würzen aus den Gärprozessen bei der Herstellung von u. a. Alkohol, organischen Säuren, Hefe. Sie bestehen aus der dickflüssigen Fraktion, die nach Abtrennen der Gärmoste/-würzen anfällt. Sie können auch abgestorbene Zellen und/oder deren Teile von den für die Fermentation eingesetzten Mikroorganismen enthalten. Die Nährlösungen sind meist pflanzlichen Ursprungs, beispielsweise Melasse, Zuckersirup, Alkohol, Brennereirückstände, Getreide und stärkehaltige Erzeugnisse, Obstsaft, Molke, Milchsäure, Zucker, hydrolysierte Pflanzenfasern und Fermentationsnährstoffe wie Ammoniak oder Mineralsalze", "Rohprotein Gegebenenfalls Nährlösung und Produktionsprozess"),
    ("12.2.2", 12, "Nebenerzeugnisse der Herstellung von L-Glutaminsäure", "Nebenerzeugnisse aus der Herstellung von L-Glutaminsäure durch Fermentation von Saccharose, Melasse, Stärkeerzeugnissen und ihren Hydrolysaten, Ammoniumsalzen und anderen Stickstoffverbindungen mit Corynebacterium melassecola ( 34 )", "Rohprotein"),
    ("12.2.3", 12, "Nebenerzeugnisse der Herstellung von L-Lysin-Monohydrochlorid mit Brevibacterium lactofermentum", "Nebenerzeugnisse aus der Herstellung von L-Lysin-Monohydrochlorid durch Fermentation von Saccharose, Melasse, Stärkeerzeugnissen und ihren Hydrolysaten, Ammoniumsalzen und anderen Stickstoffverbindungen mit Brevibacterium lactofermentum ( 34 )", "Rohprotein"),
    ("12.2.4", 12, "Nebenerzeugnisse der Herstellung von Aminosäuren mit Corynebacterium glutamicum", "Nebenerzeugnisse aus der Herstellung von Aminosäuren durch Fermentation einer Nährlösung pflanzlichen oder chemischen Ursprungs, Ammoniak oder Mineralsalzen mit Corynebacterium glutamicum ( 34 )", "Rohprotein Rohasche"),
    ("12.2.5", 12, "Nebenerzeugnisse der Herstellung von Aminosäuren mit Escherichia coli K12", "Nebenerzeugnisse aus der Herstellung von Aminosäuren durch Fermentation einer Nährlösung pflanzlichen oder chemischen Ursprungs, Ammoniak oder Mineralsalzen mit Escherichia coli K12 ( 34 )", "Rohprotein Rohasche"),
    ("12.2.6", 12, "Nebenerzeugnis der Herstellung von Enzymen mit Aspergillus niger", "Nebenerzeugnis der Fermentation von Weizen und Malz mit Aspergillus niger ( 34 ) zur Herstellung von Enzymen", "Rohprotein"),
    # ──────────────────────────────────────────────────────────── Kap 13
    ("13.1.1", 13, "Erzeugnisse der Back- und Teigwarenindustrie", "Erzeugnisse, die bei der und durch die Herstellung von Brot, Feingebäck, Keksen oder Teigwaren anfallen. Sie können auch getrocknet sein", "Stärke Gesamtzuckergehalt, berechnet als Saccharose Rohfett, wenn &gt; 5 %"),
    ("13.1.2", 13, "Erzeugnisse der Konditoreiwarenindustrie", "Erzeugnisse, die bei der Herstellung von Konditoreiwaren und Kuchen anfallen. Sie können auch getrocknet sein", "Stärke Gesamtzuckergehalt, berechnet als Saccharose Rohfett, wenn &gt; 5 %"),
    ("13.1.3", 13, "Erzeugnisse der Herstellung von Frühstückscerealien", "Stoffe oder Erzeugnisse, die dazu bestimmt sind oder bei denen nach vernünftigem Ermessen davon auszugehen ist, dass sie in verarbeitetem, teilweise verarbeitetem oder unverarbeitetem Zustand von Menschen verzehrt werden können. Sie können auch getrocknet sein", "Rohprotein, wenn &gt; 10 % Rohfaser Rohöle/-fette, wenn &gt; 10 % Stärke, wenn &gt; 30 % Gesamtzucker, berechnet als Saccharose, wenn &gt; 10 %"),
    ("13.1.4", 13, "Erzeugnisse der Süßwarenindustrie", "Erzeugnisse, die bei der und durch die Herstellung von Süßwaren, einschließlich Schokolade, anfallen. Sie können auch getrocknet sein", "Stärke Rohfett, wenn &gt; 5 % Gesamtzuckergehalt, berechnet als Saccharose"),
    ("13.1.5", 13, "Erzeugnisse der Speiseeisindustrie", "Erzeugnisse, die bei der Herstellung von Speiseeis anfallen. Sie können auch getrocknet sein", "Stärke Gesamtzuckergehalt, berechnet als Saccharose Rohfett"),
    ("13.1.6", 13, "Erzeugnisse aus der Verarbeitung von frischem Obst und Gemüse ( 36 )", "Erzeugnisse, die bei der Verarbeitung von frischem Obst und Gemüse anfallen (u. a. Schalen, ganze Obst-/Gemüsestücke und Mischungen). Sie können auch getrocknet oder gefroren sein", "Stärke Rohfaser Rohfett, wenn &gt; 5 % Salzsäureunlösliche Asche, wenn &gt; 3,5 %"),
    ("13.1.7", 13, "Erzeugnisse aus der Verarbeitung von Pflanzen ( 36 )", "Erzeugnisse, die beim Einfrieren oder Trocknen ganzer Pflanzen oder von Pflanzenteilen anfallen", "Rohfaser"),
    ("13.1.8", 13, "Erzeugnisse aus der Verarbeitung von Gewürzen und Würzmitteln ( 36 )", "Erzeugnisse, die beim Einfrieren oder Trocknen von Gewürzen und Würzmitteln oder Teilen davon anfallen", "Rohprotein, wenn &gt; 10 % Rohfaser Rohöle/-fette, wenn &gt; 10 % Stärke, wenn &gt; 30 % Gesamtzucker, berechnet als Saccharose, wenn &gt; 10 %"),
    ("13.1.9", 13, "Erzeugnisse aus der Verarbeitung von Kräutern ( 36 )", "Erzeugnisse, die beim Schroten, Mahlen, Einfrieren oder Trocknen von Kräutern oder Teilen davon anfallen", "Rohfaser"),
    ("13.1.10", 13, "Erzeugnis der Kartoffelverarbeitungsindustrie", "Erzeugnisse, die bei der Verarbeitung von Kartoffeln anfallen, und getrocknet oder gefroren sein können", "Stärke Rohfaser Rohfett, wenn &gt; 5 % Salzsäureunlösliche Asche, wenn &gt; 3,5 %"),
    ("13.1.11", 13, "Erzeugnisse und Nebenerzeugnisse aus der Soßenzubereitung", "Stoffe aus der Soßenzubereitung, die dazu bestimmt sind oder bei denen nach vernünftigem Ermessen davon auszugehen ist, dass sie in verarbeitetem, teilweise verarbeitetem oder unverarbeitetem Zustand von Menschen verzehrt werden können. Sie können auch getrocknet sein", "Rohfett"),
    ("13.1.12", 13, "Erzeugnisse und Nebenerzeugnisse aus der Snacks-Industrie", "Erzeugnisse und Nebenerzeugnisse aus der Snacks-Industrie, die bei der und durch die Herstellung würziger Snacks (Kartoffelchips und Snacks auf Kartoffel- und/oder Getreidebasis, direkt extrudiert, auf Teigbasis und pelletiert) und Knabberartikel aus Nüssen anfallen", "Rohfett"),
    ("13.1.13", 13, "Erzeugnisse aus der Herstellung gebrauchsfertiger Lebensmittel", "Erzeugnisse, die bei der Herstellung direkt verzehrfertiger Lebensmittel anfallen. Sie können auch getrocknet sein", "Rohfett, wenn &gt; 5 %"),
    ("13.1.14", 13, "Pflanzen-Nebenerzeugnisse aus der Spirituosenherstellung", "Feste Erzeugnisse aus Pflanzen (auch Beeren und Saaten wie Anis), die nach dem Einmaischen dieser Pflanzen in einer alkoholischen Lösung und/oder nach Verdampfen/Destillation des Alkohols bei der Zubereitung von Aromen in der Spirituosenherstellung anfallen. Die Alkoholrückstände in diesen Erzeugnissen müssen durch Destillation beseitigt werden", "Rohprotein, wenn &gt; 10 % Rohfaser Rohöle/-fette, wenn &gt; 10 %"),
    ("13.1.15", 13, "Futterbier", "Erzeugnis, das beim Bierbrauen anfällt und als Getränk für den menschlichen Verzehr nicht verkauft werden kann", "Alkoholgehalt"),
    ("13.2.1", 13, "Karamellisierter Zucker", "Erzeugnis, das durch das kontrollierte Erhitzen von Zuckern aller Art entsteht", "Gesamtzuckergehalt, berechnet als Saccharose"),
    ("13.2.2", 13, "Traubenzucker", "Traubenzucker entsteht durch die Hydrolyse von Stärke und besteht aus gereinigter, kristallisierter Glucose, mit oder ohne Kristallwasser", "Gesamtzuckergehalt, berechnet als Saccharose"),
    ("13.2.3", 13, "Fructose", "Fructose wird als gereinigtes kristallines Pulver angeboten. Sie wird aus Glucose in Glucosesirup durch Glucoseisomerase und Saccharose-Inversion gewonnen", "Gesamtzuckergehalt, berechnet als Saccharose"),
    ("13.2.4", 13, "Glucosesirup", "Glucosesirup ist eine gereinigte und konzentrierte wässrige Lösung nutritiver Saccharide, die durch Hydrolyse von Stärke gewonnen wird", "Gesamtzuckergehalt Feuchte, wenn &gt; 30 %"),
    ("13.2.5", 13, "Glucosemelasse", "Erzeugnis, das bei der Raffination von Glucosesirup anfällt", "Gesamtzuckergehalt"),
    ("13.2.6", 13, "Xylose", "Aus Holz extrahierter Zucker", ""),
    ("13.2.7", 13, "Lactulose", "Halbsynthetische Disaccharide (4-O-D-Galactopyranosyl-D-Fructose), die durch Isomerisierung von Glucose in Fructose aus Lactose gewonnen werden und in wärmebehandelter Milch und wärmebehandelten Milcherzeugnissen enthalten sind", "Lactulose"),
    ("13.2.8", 13, "Glucosamin (Chitosamin)", "Aminozucker (Einfachzucker), die in den Polysacchariden Chitosan und Chitin enthalten sind. Sie werden durch Hydrolyse des Außenskeletts von Krustentieren und anderen Gliederfüßern oder durch Fermentation von Getreide wie Mais oder Weizen gewonnen", "Gegebenenfalls Natrium oder Kalium Soweit zutreffend „von Wassertieren“ oder „aus Fermentation“"),
    ("13.3.1", 13, "Stärke ( 37 )", "Stärke", "Stärke"),
    ("13.3.2", 13, "Quellstärke ( 37 )", "Erzeugnis, das aus Stärke besteht, die durch Wärmebehandlung aufgeschlossen ist", "Stärke"),
    ("13.3.3", 13, "Stärkemischung ( 37 )", "Erzeugnis, das aus nativen und/oder modifizierten Lebensmittelstärken unterschiedlichen pflanzlichen Ursprungs besteht", "Stärke"),
    ("13.3.4", 13, "Filterkuchen aus der Stärkehydrolyse ( 37 )", "Erzeugnis der Filterung der Flüssigkeit bei der Stärkehydrolyse, das aus Protein, Stärke, Polysacchariden, Fett, Öl und Filtrierhilfsstoffen (z. B. Kieselerde, Holzfaser) besteht", "Feuchte, wenn &lt; 25 % oder &gt; 45 % Wenn Feuchte &lt; 25 %: —"),
    ("13.3.5", 13, "Dextrine", "Dextrin besteht aus teil-säurehydrolysierter Stärke", ""),
    ("13.3.6", 13, "Maltodextrin", "Maltodextrin ist teil-hydrolysierte Stärke", ""),
    ("13.4.1", 13, "Polydextrose", "Lose gebundene Polymere der Glucose, die durch die Wärmebehandlung von D-Glucose entstehen", ""),
    ("13.5.1", 13, "Polyole", "Erzeugnis, das durch Hydrierung oder Fermentation gewonnen wird und aus reduzierten Mono-, Di- oder Oligosacchariden oder Polysacchariden besteht", ""),
    ("13.5.2", 13, "Isomalt", "Zuckeralkohol, der durch enzymatische Spaltung und anschließende Hydrierung aus Saccharose gewonnen wird", ""),
    ("13.5.3", 13, "Mannitol", "Erzeugnis, das durch Hydrierung oder Fermentation gewonnen wird und aus reduzierter Glucose und/oder Fructose besteht", ""),
    ("13.5.4", 13, "Xylitol", "Erzeugnis, das durch Hydrierung und Fermentation von Xylose gewonnen wird", ""),
    ("13.5.5", 13, "Sorbitol", "Erzeugnis, das durch Hydrierung von Glucose gewonnen wird", ""),
    ("13.6.1", 13, "Fettsäuren aus der chemischen Raffination ( 38 )", "Erzeugnis, das bei der Entsäuerung von Ölen und Fetten pflanzlichen oder tierischen Ursprungs mit Laugen gewonnen und anschließend angesäuert und von der wässrigen Phase getrennt wird; es enthält freie Fettsäuren, Öle oder Fette und natürliche Komponenten von Samen, Früchten oder tierischem Gewebe wie Mono- und Diglyceride, Lecithin und Fasern", "Rohfett Feuchte, wenn &gt; 1 %"),
    ("13.6.2", 13, "Fettsäuren, mit Glycerin verestert ( 39 )", "Durch Veresterung von Glycerin mit Fettsäuren entstehende Glyceride. Können bis zu 50 ppm Nickel aus der Hydrierung enthalten", "Feuchte, wenn &gt; 1 % Rohfett Nickel, wenn &gt; 20 ppm"),
    ("13.6.3", 13, "Mono-, Di- und Triglyceride von Fettsäuren ( 39 )", "Erzeugnis, das aus Gemischen der Mono-, Di- und Triester von Glycerin mit Fettsäuren besteht. Es kann geringe Mengen an freien Fettsäuren und Glycerin enthalten. Kann bis zu 50 ppm Nickel aus der Hydrierung enthalten", "Rohfett Nickel, wenn &gt; 20 ppm"),
    ("13.6.4", 13, "Salze von Fettsäuren ( 39 )", "Erzeugnis, das bei der Reaktion von Fettsäuren mit mindestens 4 Kohlenstoffatomen mit den Hydroxiden, Oxiden oder Salzen von Calcium, Magnesium, Natrium oder Kalium entsteht. Kann bis zu 50 ppm Nickel aus der Hydrierung enthalten", "Rohfett (nach der Hydrolyse) Feuchte Ca (bzw. Na, K oder Mg) Nickel, wenn &gt; 20 ppm"),
    ("13.6.5", 13, "Fettsäuredestillate aus der physikalischen Raffination ( 38 )", "Erzeugnis, das bei der Entsäuerung von Ölen und Fetten pflanzlichen oder tierischen Ursprungs durch Destillation gewonnen wird; es enthält freie Fettsäuren, Öle oder Fette und natürliche Komponenten von Samen, Früchten oder tierischem Gewebe wie Mono- und Diglyceride, Sterole und Tocopherole", "Rohfett Feuchte, wenn &gt; 1 %"),
    ("13.6.6", 13, "Rohe Fettsäuren aus der Fettspaltung ( 38 )", "Durch Spaltung von Öl und Fett gewonnenes Erzeugnis. Besteht aus rohen Fettsäuren C 6 — C 24 , aliphatisch, unverzweigt, monocarbon, gesättigt und ungesättigt. Kann bis zu 50 ppm Nickel aus der Hydrierung enthalten", "Rohfett Feuchte, wenn &gt; 1 % Nickel, wenn &gt; 20 ppm"),
    ("13.6.7", 13, "Reine destillierte Fettsäuren aus der Fettspaltung ( 38 )", "Erzeugnis, das durch Destillation roher Fettsäuren aus der Spaltung von Öl und Fett gewonnen wird und unter Umständen hydriert ist. Besteht aus reinen destillierten Fettsäuren C 6 — C 24 , aliphatisch, unverzweigt, monocarbon, gesättigt und ungesättigt. Kann bis zu 50 ppm Nickel aus der Hydrierung enthalten", "Rohfett Feuchte, wenn &gt; 1 % Nickel, wenn &gt; 20 ppm"),
    ("13.6.8", 13, "Soapstock [Seifenstock] ( 38 )", "Erzeugnis, das bei der Entsäuerung pflanzlicher Öle und Fette mit Hilfe wässriger Lösungen von Calcium-, Magnesium-, Natrium oder Kaliumhydroxid gewonnen wird; es enthält Salze freier Fettsäuren, Öle oder Fette und natürliche Komponenten von Samen, Früchten oder tierischem Gewebe wie Mono- und Diglyceride, Lecithin und Fasern", "Feuchte, wenn &lt; 40 und &gt; 50 % Ca (bzw. Na, K oder Mg)"),
    ("13.6.9", 13, "Mono- und Diglyceride von mit organischen Säuren veresterten Fettsäuren ( 39 ) , ( 40 )", "Mono- und Diglyceride von Fettsäuren mit mindestens 4 Kohlenstoffatomen, die mit organischen Säuren verestert wurden", "Rohfett"),
    ("13.6.10", 13, "Zuckerester von Fettsäuren ( 39 )", "Ester der Saccharose und Fettsäuren", "Gesamtzuckergehalt, berechnet als Saccharose Rohfett"),
    ("13.6.11", 13, "Zuckerglyceride von Fettsäuren ( 39 )", "Mischungen aus Zuckerestern und Mono- und Diglyceriden von Fettsäuren", "Gesamtzuckergehalt, berechnet als Saccharose Rohfett"),
    ("13.8.1", 13, "Glycerin, roh", "Nebenprodukt aus —", "der oleochemischen Fettverarbeitung bei der Spaltung von Öl/Fett in Fettsäuren und Glycerin, gefolgt vom Aufkonzentrieren des Glycerins zu Rohglycerin, oder Umesterung (kann bis zu 0,5 % Methanol enthalten) der natürlichen Öle/Fette zu Fettsäuremethylester und Rohglycerin, gefolgt vom Aufkonzentrieren des Glycerins zu Rohglycerin ( sweet water );"),
    ("13.8.2", 13, "Glycerin", "Erzeugnis aus —", "der oleochemischen Fettverarbeitung bei a) der Spaltung von Öl/Fett, gefolgt vom Aufkonzentrieren des Glycerins und der Raffination durch Destillation (siehe Teil B, Glossar der Verfahren, Nr. 20) oder Ionenaustausch; b) der Umesterung der natürlichen Öle/Fette zu Fettsäuremethylester und Rohglycerin, gefolgt vom Aufkonzentrieren des Glycerins zu Rohglycerin und der Raffination durch Destillation oder Ionenaustausch;"),
    ("13.9.1", 13, "Methylsulphonylmethan", "Organische Schwefelverbindung ((CH 3 ) 2 SO 2 ), die in identischer Form zu der in Pflanzen natürlich vorkommenden Form synthetisch hergestellt wird", "Schwefel"),
    ("13.10.1", 13, "Torf", "Erzeugnis, das bei der natürlichen Zersetzung von Pflanzen (vor allem Torfmoose) in anaerober und oligotropher Atmosphäre entsteht", "Rohfaser"),
    ("13.10.2", 13, "Leonardit", "Natürlich vorkommende mineralische Verbindung phenolischer Kohlenwasserstoffe, auch bekannt als Humat, die durch Zersetzung organischer Materie im Laufe von Jahrmillionen entsteht", "Rohfaser"),
    ("13.11.1", 13, "Propylenglycol [1,2-Propandiol] [Propan-1,2-diol]", "Organische Verbindung (Diol oder zweiwertiger Alkohol) mit der Formel C 3 H 8 O 2 . Es ist eine viskose, leicht süßlich riechende, hygroskopische Flüssigkeit, die mit Wasser, Aceton und Chloroform mischbar ist. Kann bis zu 0,3 % Di-Propylenglycol enthalten.", "Propylenglycol"),
    ("13.11.2", 13, "Monoester von Propylenglycol und Fettsäuren ( 39 )", "Monoester von Propylenglycol und Fettsäuren, allein oder in Gemischen mit den Diestern", "Propylenglycol Rohfett"),
]


def _build_feed_materials() -> list[tuple]:
    """Return rows for INSERT INTO feed_materials."""
    return [
        (
            num, chapter, _CHAP[chapter], name_de, desc_de, decl, "", "68/2013"
        )
        for num, chapter, name_de, desc_de, decl in FEED_MATERIALS
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


# ---------------------------------------------------------------------------
# DLG Positivliste für Einzelfuttermittel (15. Auflage, 2023)
# ---------------------------------------------------------------------------

DLG_PDF_URL = (
    "https://www.dlg.org/fileadmin/downloads/Landwirtschaft/Tierhaltung/"
    "Futtermittel/Positivliste_fuer_Einzelfuttermittel/2023/"
    "15-Auflage-Positivliste-230530.pdf"
)
DLG_EDITION = "15"

DLG_GROUPS: dict[int, str] = {
    1:  "Getreidekörner, deren Erzeugnisse und Nebenerzeugnisse",
    2:  "Ölsaaten und Ölfrüchte sowie sonstige ölliefernde Pflanzen, deren Erzeugnisse und Nebenerzeugnisse",
    3:  "Körnerleguminosen, deren Erzeugnisse und Nebenerzeugnisse",
    4:  "Knollen und Wurzeln, deren Erzeugnisse und Nebenerzeugnisse",
    5:  "Nebenerzeugnisse des Gärungsgewerbes und der Destillation einschließlich der fermentativen Alkoholherstellung für Bioenergiezwecke",
    6:  "Andere Samen und Früchte, deren Erzeugnisse und Nebenerzeugnisse",
    7:  "Wirtschaftseigene Grobfuttermittel und Grünfutterprodukte",
    8:  "Andere Pflanzen, deren Erzeugnisse und Nebenerzeugnisse",
    9:  "Milcherzeugnisse",
    10: "Fisch sowie andere Meerestiere, deren Erzeugnisse und Nebenerzeugnisse",
    11: "Mineralstoffe",
    12: "Verschiedene Einzelfuttermittel",
    13: "Ehemalige Lebensmittel, Erzeugnisse und Nebenerzeugnisse der Lebensmittelherstellung",
    14: "Proteinerzeugnisse aus Mikroorganismen",
    17: "Ammoniumsalze",
    18: "Andere NPN-Verbindungen (außer Ammoniumsalze)",
    19: "Erzeugnisse und Nebenerzeugnisse von Landtieren",
    20: "Eierzeugnisse",
}

_FOOTNOTE_RE = re.compile(r'\s*\d+\)\s*$')
_DLG_NUM_RE  = re.compile(r'^\d{2}\.\d{2}\.\d{2}$')


def _clean(s: str | None) -> str:
    if not s:
        return ""
    return re.sub(r'\s+', ' ', s).strip()


def parse_dlg_pdf(pdf_path: Path) -> list[tuple]:
    """Parse DLG Positivliste PDF and return rows for dlg_feed_materials INSERT.

    Returns list of 11-tuples:
      (number, group_num, group_name_de, name_de, description_de,
       differentiation_de, requirements_de, labeling_de, process_de,
       remarks_de, edition)
    Returns empty list if pdfplumber is unavailable or parsing fails.
    """
    try:
        import pdfplumber  # optional dependency – not in requirements-pipeline.txt by default
    except ImportError:
        print("[DLG] pdfplumber not installed – skipping DLG Positivliste", flush=True)
        return []

    rows: list[tuple] = []
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            # Data starts at page 23 (0-indexed: 22)
            for page in pdf.pages[22:]:
                tables = page.extract_tables()
                if not tables:
                    continue
                for table in tables:
                    for row in table:
                        if not row or len(row) < 3:
                            continue
                        num = _clean(row[0])
                        if not _DLG_NUM_RE.match(num):
                            continue
                        name     = _FOOTNOTE_RE.sub('', _clean(row[1]))
                        desc     = _clean(row[2])
                        diff     = _clean(row[3]) if len(row) > 3 else ""
                        req      = _clean(row[4]) if len(row) > 4 else ""
                        labeling = _clean(row[5]) if len(row) > 5 else ""
                        process  = _clean(row[6]) if len(row) > 6 else ""
                        remarks  = _clean(row[7]) if len(row) > 7 else ""
                        g        = int(num.split('.')[0])
                        rows.append((
                            num, g, DLG_GROUPS.get(g, ""),
                            name, desc, diff, req, labeling, process, remarks,
                            DLG_EDITION,
                        ))
    except Exception as exc:
        print(f"[DLG] Parsing failed: {exc} – DLG data will be empty", flush=True)
        return []

    print(f"[DLG] Parsed {len(rows)} entries from {pdf_path.name}", flush=True)
    return rows


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
        r"\b(LOT|L|Charge|Chargen-Nr\.?|Chargennummer|Los|Losnummer|Los-Nr\.?|Partie|Partienummer|Partie-Nr\.?|Partie\s+Nr\.?)(?!\w)\s?[:\-]?\s?[A-Z0-9\-\/]*\d[A-Z0-9\-\/]*\b",
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
        "Mindesthaltbar bis",
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
        r"\b(MHD|BBD|mindestens haltbar bis|mindesthaltbar bis|haltbar bis|verwendbar bis)"
        r"[:\s]*\d{1,2}[\.\/\-]\d{1,2}[\.\/\-]\d{2,4}\b",
        # MM/YYYY format without day: "MHD 03/2028", "MHD: 01-2027"
        # Common on box edges and sticker prints (e.g. EDEKA Schleck Snack)
        r"\b(MHD|BBD|mindestens haltbar bis|mindesthaltbar bis|haltbar bis|verwendbar bis)"
        r"[:\s]*\d{1,2}[\/\-]\d{4}\b",
        # English / international: EXP / BBE + concrete date
        # Covers "EXP: 29.11.2026" and "BBE 01.03.2027" on multilingual EU labels
        r"\b(EXP|BBE|best before|use before|use by|expiry|expiration)"
        r"[:\s.]*\d{1,2}[\.\/\-]\d{1,2}[\.\/\-]\d{2,4}\b",
        # EXP MM/YYYY: "EXP 03/2028"
        r"\b(EXP|BBE|best before|use before|use by)"
        r"[:\s.]*\d{1,2}[\/\-]\d{4}\b",
    ]
    # Keywords: section labels → probablyFound (0.7); date regex → found (1.0)
    rows += _kw("art16_002", _mhd_kw, weight=0.7)
    rows += _kw("art16_002", _mhd_kw_en, weight=0.7, language="en")
    rows += _kw("art16_002", _mhd_kw_other, weight=0.7, language="other")
    rows += _rx("art16_002", _mhd_rx)

    # art16_003 – Tierart (single_feed, optional)
    _animal_de_rx = [
        r"\bfür\s+(?:[A-Za-zÄÖÜäöüß\-]+\s+){0,4}(Hunde|Hund|Katzen|Katze|Rinder|Kälber|Kaelber|Wiederkäuer|Wiederkaeuer|Schweine|Geflügel|Gefluegel|Pferde|Fische|Kaninchen|Schafe|Ziegen|Nager|Nagetiere|Meerschweinchen|Zwergkaninchen|Hamster|Kleintiere)\b",
        r"\b(Hunde|Hund|Katzen|Katze|Rinder|Kälber|Kaelber|Schweine|Geflügel|Gefluegel|Pferde|Fische|Kaninchen|Schafe|Ziegen|Nager|Nagetiere|Meerschweinchen|Zwergkaninchen|Hamster)\s+(?:adult|ausgewachsen|ausgewachsene|senior|junior)\b",
    ]
    _animal_en_rx = [
        r"\bfor\s+(?:[A-Za-z\-]+\s+){0,4}(dogs?|cats?|cattle|calves|ruminants?|pigs?|poultry|horses?|fish|rabbits?|rodents?|hamsters?|guinea\s+pigs?)\b",
    ]
    _animal_other_rx = [
        r"\bper\s+(?:[A-Za-zÀ-ÿ\-]+\s+){0,4}(cani|gatti|cavalli|roditori|conigli)\b",
        r"\bpour\s+(?:[A-Za-zÀ-ÿ\-]+\s+){0,4}(chiens|chats|chevaux|rongeurs|lapins)\b",
        r"\bvoor\s+(?:[A-Za-zÀ-ÿ\-]+\s+){0,4}(honden|katten|paarden|knaagdieren|konijnen)\b",
        r"\bdla\s+(?:[A-Za-zÀ-ÿ\-]+\s+){0,4}(psów|psow|kotów|kotow|koni|gryzoni)\b",
        r"\bpara\s+(?:[A-Za-zÀ-ÿ\-]+\s+){0,4}(cavalos|caballos|perros|gatos)\b",
    ]
    # Concrete species declaration → found (1.0)
    rows += _kw("art16_003", [
        "für Hunde", "für Katzen", "für Rinder", "für Kälber", "für Schweine",
        "für Geflügel", "für Pferde", "für Fische", "für Kaninchen",
        "für Schafe", "für Ziegen", "für Wiederkäuer", "für Wiederkaeuer",
        "für Hund", "für Katze",
        # Rodents / small animals — common in DE retail (new images: Vitakraft, EDEKA Muckel)
        "für Nager", "für Nagetiere", "für Meerschweinchen",
        "für Zwergkaninchen", "für Hamster", "für Kleintiere",
        "Zwergkaninchen und Meerschweinchen",
    ])
    # Section labels → probablyFound (0.7)
    rows += _kw("art16_003", ["Tierart:", "Tierkategorie:"], weight=0.7)
    # Compound species words → probablyFound (0.8)
    rows += _kw("art16_003", [
        "Katzenfutter", "Hundefutter", "Rinderfutter", "Geflügelfutter",
        "Pferdefutter", "Kaninchenfutter", "Katzenahrung", "Hundenahrung",
        "Wiederkäuerfutter", "Nagerfutter", "Meerschweinchenfutter",
        "Kleintiernahrung",
    ], weight=0.8)
    rows += _rx("art16_003", _animal_de_rx)
    rows += _kw("art16_003", [
        "for dogs", "for cats", "for cattle", "for calves", "for pigs",
        "for poultry", "for horses", "for horse", "for fish", "for rabbits",
        "for rodents", "for hamsters", "for guinea pigs", "for ruminants",
        "animal species:", "feeding recommendation:",
    ], language="en")
    rows += _rx("art16_003", _animal_en_rx, language="en")
    rows += _kw("art16_003", [
        "per cani", "per gatti", "per cavalli", "pour chiens", "pour chats",
        "pour chevaux", "voor honden", "voor katten", "voor paarden",
        "dla psów", "dla kotów", "dla koni", "para cavalos", "para caballos",
        # Rodent species in other EU languages
        "pour rongeurs", "pour lapins", "per roditori", "per conigli",
        "voor knaagdieren", "voor konijnen", "dla gryzoni",
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
        "für Schafe", "für Ziegen", "für Wiederkäuer", "für Wiederkaeuer",
        "für Hund", "für Katze", "Hunde und Katzen",
        # Rodents / small animals
        "für Nager", "für Nagetiere", "für Meerschweinchen",
        "für Zwergkaninchen", "für Hamster", "für Kleintiere",
        "Zwergkaninchen und Meerschweinchen",
    ]
    _tierart_labels = ["Tierart:", "Tierkategorie:"]
    _tierart_compound = [
        "Katzenfutter", "Hundefutter", "Rinderfutter", "Geflügelfutter",
        "Pferdefutter", "Kaninchenfutter", "Katzenahrung", "Hundenahrung",
        "Wiederkäuerfutter", "Nagerfutter", "Meerschweinchenfutter",
        "Kleintiernahrung",
    ]
    for _, suffix in _COMPOUND_FEEDS:
        rows += _kw(f"art17_001_{suffix}", _tierart_concrete)           # found (1.0)
        rows += _kw(f"art17_001_{suffix}", _tierart_labels, weight=0.7) # probablyFound
        rows += _kw(f"art17_001_{suffix}", _tierart_compound, weight=0.8)  # probablyFound
        rows += _rx(f"art17_001_{suffix}", _animal_de_rx)
        rows += _kw(f"art17_001_{suffix}", [
            "for dogs", "for cats", "for cattle", "for calves", "for pigs",
            "for poultry", "for horses", "for horse", "for fish", "for rabbits",
            "for rodents", "for hamsters", "for guinea pigs", "for ruminants",
        ], language="en")
        rows += _kw(f"art17_001_{suffix}", ["feeding recommendation:"],
                    weight=0.7, language="en")
        rows += _rx(f"art17_001_{suffix}", _animal_en_rx, language="en")
        rows += _kw(f"art17_001_{suffix}", [
            "per cani", "per gatti", "per cavalli", "pour chiens", "pour chats",
            "pour chevaux", "voor honden", "voor katten", "voor paarden",
            "dla psów", "dla kotów", "dla koni", "para cavalos", "para caballos",
            "pour rongeurs", "pour lapins", "per roditori", "per conigli",
            "voor knaagdieren", "voor konijnen", "dla gryzoni",
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

def build(out_path: Path, dlg_pdf_path: Path | None = None) -> int:
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

    # --- dlg_feed_materials (DLG Positivliste) ---
    dlg_rows = parse_dlg_pdf(dlg_pdf_path) if dlg_pdf_path and dlg_pdf_path.exists() else []
    if dlg_rows:
        con.executemany(
            """
            INSERT INTO dlg_feed_materials
                (number, group_num, group_name_de, name_de, description_de,
                 differentiation_de, requirements_de, labeling_de, process_de,
                 remarks_de, edition)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            dlg_rows,
        )
    dlg_count = len(dlg_rows)

    # --- additive_section_headers ---
    con.executemany(
        "INSERT INTO additive_section_headers (header, lang, sort_order) VALUES (?, ?, ?)",
        ADDITIVE_SECTION_HEADERS,
    )

    # --- additive_exclusions ---
    con.executemany(
        "INSERT INTO additive_exclusions (prefix) VALUES (?)",
        [(p,) for p in ADDITIVE_EXCLUSION_PREFIXES],
    )

    # --- labeling_metadata (initial, without sha256) ---
    metadata_initial = [
        ("labeling_db_version", "2026-05-26"),
        ("labeling_source_regulation", "VO (EG) Nr. 767/2009"),
        ("labeling_source_celex", "02009R0767-20181226"),
        ("labeling_source_version_date", "2018-12-26"),
        ("labeling_created_at", now_iso),
        ("labeling_rule_count", str(rule_count)),
        ("dlg_positivliste_edition", DLG_EDITION),
        ("dlg_positivliste_count", str(dlg_count)),
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
    parser.add_argument(
        "--dlg-pdf",
        type=Path,
        default=None,
        help="Path to DLG Positivliste PDF (optional; skips DLG data if not provided)",
    )
    args = parser.parse_args()

    rule_count = build(args.out, dlg_pdf_path=args.dlg_pdf)
    print(f"Wrote {args.out}, {rule_count} rules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
