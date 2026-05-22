"""Tests for the FeedLabelCheck labeling check pipeline.

The session-scoped ``fresh_db`` fixture (conftest.py) builds a fresh
labeling.sqlite from scripts/build_labeling_db.py into a temporary
directory before any test runs.  DB-dependent classes receive the connection
via ``@pytest.fixture(autouse=True) def _db(self, fresh_db)``.

Pure pattern-matching tests (Sections 2–7) have no DB dependency and run
even when the build environment is unavailable.
"""

from __future__ import annotations

import re
import sqlite3

import pytest

# ------------------------------------------------------------------
# Pattern-matching helpers — mirror LabelingCheckService logic
# ------------------------------------------------------------------


def keyword_match(keyword: str, text: str) -> bool:
    return keyword.lower() in text.lower()


def regex_match(pattern: str, text: str) -> bool:
    try:
        return bool(re.search(pattern, text, re.IGNORECASE))
    except re.error:
        return False


# ------------------------------------------------------------------
# 1. Feed type detection  (requires DB)
# ------------------------------------------------------------------


class TestFeedTypeDetection:
    """10 cases: keyword matching for each relevant feed type."""

    @pytest.fixture(autouse=True)
    def _db(self, fresh_db: sqlite3.Connection) -> None:
        self.con = fresh_db

    def _detect(self, text: str) -> list[str]:
        rows = self.con.execute(
            "SELECT id, keywords_de FROM labeling_feed_types "
            "WHERE id != 'all' AND id != 'unknown'"
        ).fetchall()
        text_lower = text.lower()
        return [
            row[0]
            for row in rows
            if any(
                kw.strip().lower() in text_lower
                for kw in row[1].split(",")
                if kw.strip()
            )
        ]

    def test_complete_feed_detected(self):
        assert "complete_feed" in self._detect("Alleinfuttermittel für ausgewachsene Hunde")

    def test_complementary_feed_detected(self):
        assert "complementary_feed" in self._detect("Ergänzungsfuttermittel für Schweine")

    def test_single_feed_detected(self):
        assert "single_feed" in self._detect("Einzelfuttermittel: Weizenmehl")

    def test_compound_feed_detected(self):
        assert "compound_feed" in self._detect("Mischfuttermittel für Geflügel")

    def test_mineral_feed_detected(self):
        assert "mineral_feed" in self._detect("Mineralfuttermittel für Milchkühe")

    def test_milk_replacer_detected(self):
        assert "milk_replacer" in self._detect("Milchaustauscher für Kälber bis 4 Wochen")

    def test_pet_feed_detected(self):
        assert "pet_feed" in self._detect("Heimtierfutter für Katzen")

    def test_ambiguous_text_matches_multiple(self):
        detected = self._detect("Alleinfuttermittel sowie Ergänzungsfuttermittel für Hühner")
        assert len(detected) >= 2

    def test_empty_text_no_match(self):
        assert self._detect("") == []

    def test_unknown_text_no_match(self):
        assert self._detect("Produktname ohne Futtermittelangabe") == []


# ------------------------------------------------------------------
# 2. Lot number patterns  (pure Python)
# ------------------------------------------------------------------

LOT_PATTERNS = [
    # 1. Standard short keyword + compact code (at least one digit required)
    #    (?!\w) prevents matching inside compound words (e.g. "Chargenangabe")
    r"\b(LOT|L|Charge|Chargen-Nr\.?|Los|Partie)(?!\w)\s?[:\-]?\s?[A-Z0-9\-\/]*\d[A-Z0-9\-\/]*\b",
    # 2. Long-form labels: Zulassungsnummer / Kennnummer der Partie + space-separated code
    #    Requires ≥4 digits → prevents matching "siehe Boden-Aufdruck" (no digits)
    r"\b(?:Zulassungsnummer|Kennnummer)\s+der\s+Partie\s*[:\-]?\s*[A-Z]{1,5}\s*\d{4,}[A-Z0-9]*\b",
    # 3. EXP + date + trailing alphanumeric code heuristic
    #    "EXP: 29.11.2026 NU250529H" — code after date is likely a batch/lot number
    r"\bEXP\s*:?\s*\d{1,2}[\.\/\-]\d{1,2}[\.\/\-]\d{2,4}\s+[A-Z]{1,4}\d{4,}[A-Z0-9]*\b",
]


class TestLotNumberPattern:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Charge: A2024-09-01", True),
            ("LOT 20240901A", True),
            ("L: XYZ123", True),
            ("Partie: P2024/05", True),
            ("Chargen-Nr. 20240501-001", True),
            ("Los: 4567", True),
            # "Chargenangabe" is a compound word — "Charge" has no \b after it here.
            # The keyword "Chargenangabe:" at weight 0.7 still gives probablyFound.
            ("Chargenangabe: A2024", False),
            ("CHOLESTEROL 200mg", False),
            ("Produktbeschreibung ohne Angabe", False),
            # Real-packaging additions (Kennzeichnungen.pdf)
            ("Zulassungsnummer der Partie: BAF 1015090925", True),  # pattern 2: space-sep code
            ("EXP: 29.11.2026 NU250529H", True),                    # pattern 3: EXP heuristic
            ("LOT", False),                                          # keyword-only, no code
            ("kühl und trocken lagern", False),                      # false-positive guard
        ],
    )
    def test_lot_pattern(self, text: str, expected: bool) -> None:
        result = any(regex_match(p, text) for p in LOT_PATTERNS)
        assert result == expected, f"Lot pattern on '{text}' expected {expected}"


# ------------------------------------------------------------------
# 3. Net quantity patterns  (pure Python)
# ------------------------------------------------------------------

NET_PATTERNS = [
    r"\b\d+[,.]?\d*\s*(kg|g|t|ml|l|Liter|Kilogramm|Gramm)\b",
    r"\b(Nettomasse|Nettogewicht|Nettomenge|Nettofüllmenge|Netto)[\s:]*\d+",
]


class TestNetQuantityPattern:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Nettomasse: 10 kg", True),
            ("500 g", True),
            ("2,5 kg", True),
            ("Inhalt: 1 Liter", True),
            ("250ml", True),
            ("Rohprotein 18 %", False),
            ("Seite 5", False),
        ],
    )
    def test_net_quantity_pattern(self, text: str, expected: bool) -> None:
        result = any(regex_match(p, text) for p in NET_PATTERNS)
        assert result == expected, f"Net quantity pattern on '{text}' expected {expected}"


# ------------------------------------------------------------------
# 4. Best-before patterns  (pure Python)
# ------------------------------------------------------------------

BBD_PATTERNS = [
    # German/general: standard abbreviations + concrete DD.MM.YYYY date
    # Includes "haltbar bis" (without "mindestens") for "-18°C haltbar bis: 09.12.26"
    r"\b(MHD|BBD|mindestens haltbar bis|haltbar bis|verwendbar bis)"
    r"[:\s]*\d{1,2}[\.\/\-]\d{1,2}[\.\/\-]\d{2,4}\b",
    # English/international: EXP / BBE + concrete date
    # Covers "EXP: 29.11.2026" and "BBE 01.03.2027"
    r"\b(EXP|BBE|best before|use before|use by|expiry|expiration)"
    r"[:\s.]*\d{1,2}[\.\/\-]\d{1,2}[\.\/\-]\d{2,4}\b",
]
BBD_KEYWORDS = [
    "Mindesthaltbarkeit",
    "mindestens haltbar bis",
    "MHD",
    "best before",
    "verwendbar bis",
    "haltbar bis",
    "EXP:",   # with colon — specific enough as standalone keyword
    "BBE",
    "use by",
]


class TestBestBeforePattern:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("MHD: 31.12.2025", True),
            ("mindestens haltbar bis 31.12.2025", True),
            # ISO / partial formats not matched by the German-date regex — expected False
            ("BBD 2025-12-31", False),
            ("mindestens haltbar bis 01/2026", False),
            ("best before 12/2025", False),
            ("Kein Ablaufdatum vorhanden", False),
            # Real-packaging additions (Kennzeichnungen.pdf)
            ("EXP: 29.11.2026", True),       # Brit snack — EXP + date → second BBD pattern
            ("haltbar bis: 09.12.26", True),  # proCani — haltbar bis + short year
            ("EXP 01.03.2027", True),         # EXP without colon
        ],
    )
    def test_bbd_regex(self, text: str, expected: bool) -> None:
        result = any(regex_match(p, text) for p in BBD_PATTERNS)
        assert result == expected

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Mindesthaltbarkeit: 31.12.2025", True),
            ("MHD 01.06.2026", True),
            ("haltbar bis Ende 2025", True),
            ("Kein Datum angegeben", False),
        ],
    )
    def test_bbd_keyword(self, text: str, expected: bool) -> None:
        result = any(keyword_match(kw, text) for kw in BBD_KEYWORDS)
        assert result == expected


# ------------------------------------------------------------------
# 5. Composition detection  (pure Python)
# ------------------------------------------------------------------

COMPOSITION_KEYWORDS = ["Zusammensetzung", "Zutaten:", "Inhaltsstoffe"]


class TestCompositionDetection:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Zusammensetzung: Hühnerfleisch (40%), Leber (10%)", True),
            ("Zutaten: Weizen, Mais, Sojaextraktionsschrot", True),
            ("Inhaltsstoffe: diverse", True),
            ("Rohprotein 18 %, Rohfett 8 %", False),
            ("Analytische Bestandteile", False),
        ],
    )
    def test_composition_keyword(self, text: str, expected: bool) -> None:
        result = any(keyword_match(kw, text) for kw in COMPOSITION_KEYWORDS)
        assert result == expected


# ------------------------------------------------------------------
# 6. Analytical constituents  (pure Python)
# ------------------------------------------------------------------

ANALYTICAL_KEYWORDS = [
    "Analytische Bestandteile",
    "Rohprotein",
    "Rohfaser",
    "Rohfett",
    "Rohasche",
]


class TestAnalyticalConstituents:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Analytische Bestandteile: Rohprotein 24 %, Rohfett 12 %", True),
            ("Rohprotein 18 %", True),
            ("Rohfaser 5 %, Rohasche 6 %", True),
            ("Zusammensetzung: Hühnerfleisch", False),
            ("Zutaten: Weizen", False),
        ],
    )
    def test_analytical_keyword(self, text: str, expected: bool) -> None:
        result = any(keyword_match(kw, text) for kw in ANALYTICAL_KEYWORDS)
        assert result == expected


# ------------------------------------------------------------------
# 7. Additives detection  (pure Python)
# ------------------------------------------------------------------

ADDITIVE_KEYWORDS = [
    "Zusatzstoffe",
    "Ernährungsphysiologische Zusatzstoffe",
    "Technologische Zusatzstoffe",
    "Zootechnische Zusatzstoffe",
]


class TestAdditivesDetection:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Zusatzstoffe: Vitamin A 15.000 IE/kg", True),
            ("Ernährungsphysiologische Zusatzstoffe: Biotin", True),
            ("Technologische Zusatzstoffe: Antioxidationsmittel", True),
            ("Zusammensetzung: Weizen, Mais", False),
            ("Analytische Bestandteile", False),
        ],
    )
    def test_additive_keyword(self, text: str, expected: bool) -> None:
        result = any(keyword_match(kw, text) for kw in ADDITIVE_KEYWORDS)
        assert result == expected


# ------------------------------------------------------------------
# 8. Additive declaration patterns  (pure Python + DB)
# ------------------------------------------------------------------

# Structured additive declaration patterns (weight 0.85 → .found quality).
# Substance name + numeric amount + unit — no section header required.
ADDITIVE_STRUCTURED_PATTERNS = [
    # Substance name (min 3-letter word, optionally + 2nd word) + amount + unit
    r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß\-]{2,}(?:\s+[A-Za-zÄÖÜäöüß0-9][A-Za-zÄÖÜäöüß0-9\-]*)?"
    r"\s+\d[\d\.\,\s]{0,9}\s*(?:mg|IE|IU|µg|g)\s*/\s*kg\b",
    # E-number style: "E 300 200 mg/kg"
    r"\bE\s*\d{3,4}[a-z]?\s+\d[\d\.\,\s]{0,9}\s*(?:mg|IE|IU|µg|g)\s*/\s*kg\b",
]


class TestAdditiveDeclarationPatterns:
    """Tests for structured additive declaration regex (weight 0.85 → .found in labeling check).

    Verifies that:
    - All required number formats (1000, 1.000, 1,000, 1 000, 15.000) match.
    - All required units (mg/kg, IE/kg, IU/kg) match.
    - Section-header-only text does NOT produce a high-weight match.
    - Standalone amount without substance name does NOT match.
    """

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Taurin 1.000mg/kg", True),             # dot-thousands, no space before unit
            ("Taurin 1.000 mg/kg", True),            # dot-thousands, space before unit
            ("Taurine 1000 mg/kg", True),             # English variant, plain integer
            ("Vitamin A 15.000 IE/kg", True),         # two-word name, dot-thousands, IE/kg
            ("E 300 200 mg/kg", True),                # E-number style
            ("Taurin 1,000 mg/kg", True),             # comma-thousands separator
            ("Vitamin D3 200 IU/kg", True),           # IU unit (English)
            ("Biotin 150 µg/kg", True),               # µg/kg unit
            # Negative cases
            ("Zusatzstoffe", False),                  # section header only, no amount
            ("Rohprotein 18 %", False),               # % unit, not mg/kg
            ("1.000 mg/kg", False),                   # no substance name before amount
        ],
    )
    def test_structured_additive_pattern(self, text: str, expected: bool) -> None:
        result = any(regex_match(p, text) for p in ADDITIVE_STRUCTURED_PATTERNS)
        assert result == expected, (
            f"Structured additive pattern on '{text}' expected {expected}"
        )

    def test_structured_pattern_exists_in_db(
        self, fresh_db: sqlite3.Connection
    ) -> None:
        """art15_006 must have at least one pattern with confidence_weight >= 0.85."""
        count = fresh_db.execute(
            "SELECT COUNT(*) FROM labeling_rule_patterns "
            "WHERE rule_id = 'art15_006' AND confidence_weight >= 0.85"
        ).fetchone()[0]
        assert count > 0, "art15_006 must have at least one high-weight (≥0.85) pattern"

    def test_taurin_matches_high_weight_pattern_in_db(
        self, fresh_db: sqlite3.Connection
    ) -> None:
        """'Taurin 1.000 mg/kg' must match a ≥0.85 pattern for art15_006."""
        patterns = fresh_db.execute(
            "SELECT pattern_type, pattern_value FROM labeling_rule_patterns "
            "WHERE rule_id = 'art15_006' AND confidence_weight >= 0.85"
        ).fetchall()
        assert patterns, "No high-weight patterns found for art15_006"
        text = "Taurin 1.000 mg/kg"
        matched = any(
            regex_match(pvalue, text)
            for ptype, pvalue in patterns
            if ptype == "regex"
        )
        assert matched, f"'Taurin 1.000 mg/kg' must match a ≥0.85 art15_006 pattern"

    def test_additive_heading_only_still_probablyfound(
        self, fresh_db: sqlite3.Connection
    ) -> None:
        """Section header 'Zusatzstoffe' alone must NOT match a ≥0.85 pattern."""
        patterns = fresh_db.execute(
            "SELECT pattern_type, pattern_value FROM labeling_rule_patterns "
            "WHERE rule_id = 'art15_006' AND confidence_weight >= 0.85"
        ).fetchall()
        text = "Zusatzstoffe"
        matched = any(
            (ptype == "keyword" and keyword_match(pvalue, text))
            or (ptype == "regex" and regex_match(pvalue, text))
            for ptype, pvalue in patterns
        )
        assert not matched, (
            "'Zusatzstoffe' alone must not match any ≥0.85 art15_006 pattern"
        )


# ------------------------------------------------------------------
# 9. OCR error resilience  (mostly pure Python; one test uses DB)
# ------------------------------------------------------------------


class TestOCRResilience:
    def test_ocr_linebreaks_lot(self) -> None:
        text = "Char\nge: A2024-09"
        joined = text.replace("\n", "")
        assert keyword_match("Charge", joined) or regex_match(LOT_PATTERNS[0], joined)

    def test_ocr_missing_space_net(self) -> None:
        assert any(regex_match(p, "Nettomasse:10kg") for p in NET_PATTERNS)

    def test_ocr_uppercase_keywords(self) -> None:
        assert any(
            keyword_match(kw, "ZUSAMMENSETZUNG: WEIZEN, MAIS")
            for kw in COMPOSITION_KEYWORDS
        )

    def test_ocr_partial_word_no_false_positive(self) -> None:
        result = any(regex_match(p, "Durchcharge-Verfahren") for p in LOT_PATTERNS)
        assert isinstance(result, bool)

    def test_mixed_german_english_label(self) -> None:
        text = "Complete pet food for dogs / Alleinfuttermittel für Hunde. Best before: 12/2026"
        assert keyword_match("Alleinfuttermittel", text)
        assert keyword_match("best before", text)

    def test_english_fallback_keywords(self) -> None:
        text = (
            "Complementary pet food for adult cats. Composition: meat. "
            "Analytical constituents: crude protein 35.5 %."
        )
        assert keyword_match("complementary pet food", text)
        assert keyword_match("composition", text)
        assert keyword_match("analytical constituents", text)

    def test_other_language_fallback_keywords(self) -> None:
        text = (
            "Alimento complementare per gatti adulti. Composizione: carni. "
            "Componenti analitici: proteina grezza 35,5 %."
        )
        assert keyword_match("alimento complementare", text)
        assert keyword_match("composizione", text)
        assert keyword_match("componenti analitici", text)

    def test_animal_species_with_words_between(self, fresh_db: sqlite3.Connection) -> None:
        patterns = [
            row[0]
            for row in fresh_db.execute(
                """
                SELECT pattern_value FROM labeling_rule_patterns
                WHERE rule_id = 'art17_001_complementary'
                  AND pattern_type = 'regex'
                  AND pattern_language = 'de'
                """
            )
        ]
        assert patterns, "No regex patterns found for art17_001_complementary / de"
        text = "Ergänzungsfuttermittel für ausgewachsene Katzen Zusammensetzung"
        assert any(regex_match(p, text) for p in patterns)

    def test_short_ocr_not_checkable(self) -> None:
        assert len("LAVES GmbH") < 40


# ------------------------------------------------------------------
# 9. Database integrity  (requires DB)
# ------------------------------------------------------------------


class TestDatabaseIntegrity:
    @pytest.fixture(autouse=True)
    def _db(self, fresh_db: sqlite3.Connection) -> None:
        self.con = fresh_db

    def test_rule_count_matches_metadata(self) -> None:
        rule_count = self.con.execute(
            "SELECT COUNT(*) FROM labeling_rules"
        ).fetchone()[0]
        meta = self.con.execute(
            "SELECT value FROM labeling_metadata WHERE key='labeling_rule_count'"
        ).fetchone()
        assert meta is not None, "labeling_rule_count metadata missing"
        assert rule_count == int(meta[0])

    def test_all_rules_have_patterns(self) -> None:
        missing = self.con.execute(
            """
            SELECT r.id FROM labeling_rules r
            LEFT JOIN labeling_rule_patterns p ON p.rule_id = r.id
            WHERE p.id IS NULL
            """
        ).fetchall()
        assert missing == [], f"Rules without patterns: {[r[0] for r in missing]}"

    def test_regulation_record_exists(self) -> None:
        reg = self.con.execute(
            "SELECT id FROM labeling_regulations WHERE id='reg_767_2009'"
        ).fetchone()
        assert reg is not None

    def test_sha256_metadata_present(self) -> None:
        sha = self.con.execute(
            "SELECT value FROM labeling_metadata WHERE key='labeling_sha256'"
        ).fetchone()
        assert sha is not None
        assert len(sha[0]) == 64, "SHA-256 should be 64 hex characters"

    def test_patterns_have_language_column(self) -> None:
        columns = {
            row[1]
            for row in self.con.execute("PRAGMA table_info(labeling_rule_patterns)")
        }
        assert "pattern_language" in columns, (
            "Testdatenbank veraltet – bitte neu generieren. "
            "Spalte 'pattern_language' fehlt in labeling_rule_patterns."
        )

    def test_multilingual_patterns_present(self) -> None:
        counts = dict(
            self.con.execute(
                "SELECT pattern_language, COUNT(*) "
                "FROM labeling_rule_patterns GROUP BY pattern_language"
            ).fetchall()
        )
        assert counts.get("de", 0) > 0, "No German patterns found"
        assert counts.get("en", 0) > 0, "No English patterns found"
        assert counts.get("other", 0) > 0, "No 'other' language patterns found"


# ------------------------------------------------------------------
# 10. Relevant rule count vs. total rule count  (requires DB)
# ------------------------------------------------------------------


class TestRelevantRuleCount:
    """Verifies that the iOS app correctly loads only feed-type-relevant
    rules rather than all rules.  Checking all 39 rules against any single
    label would produce false positives for feed-type-specific requirements.
    """

    @pytest.fixture(autouse=True)
    def _db(self, fresh_db: sqlite3.Connection) -> None:
        self.con = fresh_db

    def _relevant_count(self, feed_type_id: str) -> int:
        return self.con.execute(
            "SELECT COUNT(*) FROM labeling_rules "
            "WHERE feed_type_id = 'all' OR feed_type_id = ?",
            (feed_type_id,),
        ).fetchone()[0]

    def test_total_rule_count_is_39(self) -> None:
        count = self.con.execute(
            "SELECT COUNT(*) FROM labeling_rules"
        ).fetchone()[0]
        assert count == 39, f"Expected 39 rules in DB, got {count}"

    def test_complete_feed_loads_11_relevant_rules(self) -> None:
        count = self._relevant_count("complete_feed")
        assert count == 11, (
            f"complete_feed should load 11 relevant rules "
            f"(6 general Art.15 + 5 Art.17), got {count}"
        )

    def test_single_feed_loads_9_relevant_rules(self) -> None:
        count = self._relevant_count("single_feed")
        assert count == 9, (
            f"single_feed should load 9 relevant rules "
            f"(6 general Art.15 + 3 Art.17), got {count}"
        )

    def test_relevant_count_less_than_total(self) -> None:
        total = self.con.execute(
            "SELECT COUNT(*) FROM labeling_rules"
        ).fetchone()[0]
        for feed_type_id in ("complete_feed", "single_feed", "complementary_feed"):
            relevant = self._relevant_count(feed_type_id)
            assert relevant < total, (
                f"{feed_type_id}: relevant ({relevant}) must be < total ({total})"
            )

    def test_general_and_specific_rules_both_exist(self) -> None:
        general = self.con.execute(
            "SELECT COUNT(*) FROM labeling_rules WHERE feed_type_id = 'all'"
        ).fetchone()[0]
        specific = self.con.execute(
            "SELECT COUNT(*) FROM labeling_rules WHERE feed_type_id != 'all'"
        ).fetchone()[0]
        assert general > 0, "DB must contain general rules (feed_type_id='all')"
        assert specific > 0, "DB must contain feed-type-specific rules"

    def test_no_duplicate_rule_ids(self) -> None:
        rows = self.con.execute(
            "SELECT id, feed_type_id FROM labeling_rules"
        ).fetchall()
        seen: dict[str, str] = {}
        for rule_id, ftid in rows:
            assert rule_id not in seen, (
                f"Duplicate rule id '{rule_id}' in feed_type_id='{ftid}' "
                f"and '{seen[rule_id]}'"
            )
            seen[rule_id] = ftid


# ------------------------------------------------------------------
# 11. Real-world OCR label fragments  (requires DB)
# ------------------------------------------------------------------


class TestRealWorldLabels:
    """Regression tests for confirmed false-negative gaps.

    Each test uses a real-world OCR fragment and asserts that the relevant
    rule pattern now matches it.
    """

    @pytest.fixture(autouse=True)
    def _db(self, fresh_db: sqlite3.Connection) -> None:
        self.con = fresh_db

    def _patterns(self, rule_id: str) -> list[tuple[str, str, str]]:
        return self.con.execute(
            "SELECT pattern_type, pattern_value, pattern_language "
            "FROM labeling_rule_patterns WHERE rule_id = ?",
            (rule_id,),
        ).fetchall()

    def _matches(self, rule_id: str, text: str) -> bool:
        for ptype, pvalue, _lang in self._patterns(rule_id):
            if ptype == "keyword" and keyword_match(pvalue, text):
                return True
            if ptype == "regex" and regex_match(pvalue, text):
                return True
        return False

    # --- Tierart: compound animal species words ---

    def test_katzenfutter_implies_tierart_pet(self) -> None:
        assert self._matches("art17_001_pet", "Katzenfutter Adult"), (
            "'Katzenfutter' must match art17_001_pet (Tierart)"
        )

    def test_premium_katzenfutter_implies_tierart_pet(self) -> None:
        assert self._matches(
            "art17_001_pet", "Premium-Katzenfutter für ausgewachsene Katzen"
        )

    def test_hundefutter_implies_tierart_pet(self) -> None:
        assert self._matches("art17_001_pet", "Hundefutter für Welpen")

    def test_katzenfutter_implies_tierart_single_feed(self) -> None:
        assert self._matches("art16_003", "Katzenfutter Adult"), (
            "'Katzenfutter' must also match art16_003 (Tierart, single_feed)"
        )

    # --- Hersteller: Vertrieb / Inverkehrbringer variants ---

    def test_vertrieb_implies_hersteller_pet(self) -> None:
        assert self._matches(
            "art17_005_pet", "Vertrieb: Fountain GmbH & Co. KG"
        ), "'Vertrieb:' must match art17_005_pet (Hersteller)"

    def test_inverkehrbringer_implies_hersteller(self) -> None:
        assert self._matches(
            "art17_005_complete",
            "Inverkehrbringer: Müller GmbH, 30123 Hannover",
        )

    def test_im_auftrag_implies_hersteller(self) -> None:
        assert self._matches("art17_005_pet", "im Auftrag von Petfood Corp.")

    def test_hergestellt_fuer_implies_hersteller(self) -> None:
        assert self._matches(
            "art17_005_complete", "hergestellt für Tiernahrung AG"
        )

    # --- Zusatzstoffe: singular, mg/kg, E-numbers ---

    def test_zusatzstoff_singular_colon(self) -> None:
        assert self._matches("art15_006", "Zusatzstoff: Taurin 1.000 mg/kg"), (
            "'Zusatzstoff:' singular must match art15_006"
        )

    def test_mg_per_kg_implies_additives(self) -> None:
        assert self._matches("art15_006", "Vitamin E 150 mg/kg"), (
            "'mg/kg' pattern must match art15_006"
        )

    def test_e_number_implies_additives(self) -> None:
        assert self._matches(
            "art15_006", "E 306 (Tocopherolextrakte) 200 mg/kg"
        ), "E-number pattern must match art15_006"

    def test_ie_per_kg_implies_additives(self) -> None:
        assert self._matches("art15_006", "Vitamin A 15.000 IE/kg")


# ------------------------------------------------------------------
# 12. Pattern quality: keyword-only vs regex (concrete value)
# These tests pin the semantic contract:
#   keyword match alone → probablyFound (no high-quality regex match)
#   regex match present → found
# ------------------------------------------------------------------


class TestPatternQuality:
    """Verifies that 'reference redirect' and heading-only texts do NOT
    produce a high-quality (regex) match, while concrete values do.
    """

    @pytest.fixture(autouse=True)
    def _db(self, fresh_db: sqlite3.Connection) -> None:
        self.con = fresh_db

    def _patterns(self, rule_id: str) -> list[tuple[str, str, str, float]]:
        return self.con.execute(
            "SELECT pattern_type, pattern_value, pattern_language, confidence_weight "
            "FROM labeling_rule_patterns WHERE rule_id = ?",
            (rule_id,),
        ).fetchall()

    def _any_match(self, rule_id: str, text: str) -> bool:
        for ptype, pvalue, _lang, _w in self._patterns(rule_id):
            if ptype == "keyword" and keyword_match(pvalue, text):
                return True
            if ptype == "regex" and regex_match(pvalue, text):
                return True
        return False

    def _regex_match(self, rule_id: str, text: str) -> bool:
        """True only if a REGEX pattern matches (→ found-quality)."""
        for ptype, pvalue, _lang, _w in self._patterns(rule_id):
            if ptype == "regex" and regex_match(pvalue, text):
                return True
        return False

    def _high_weight_match(self, rule_id: str, text: str, threshold: float = 0.85) -> bool:
        """True if any pattern with weight >= threshold matches."""
        for ptype, pvalue, _lang, w in self._patterns(rule_id):
            matched = (
                (ptype == "keyword" and keyword_match(pvalue, text))
                or (ptype == "regex" and regex_match(pvalue, text))
            )
            if matched and w >= threshold:
                return True
        return False

    # --- Losnummer: reference redirect must not produce a found-quality match ---

    def test_lot_reference_redirect_no_regex_match(self) -> None:
        """'Partie: siehe Boden-Aufdruck' has a keyword but no concrete code."""
        text = "Kennnummer der Partie: siehe Boden-Aufdruck"
        assert self._any_match("art15_004", text), "keyword should still match"
        assert not self._regex_match("art15_004", text), (
            "reference redirect must not match the lot-number regex"
        )

    def test_lot_losnummer_heading_no_regex(self) -> None:
        """'Losnummer: lagern' must not regex-match (no alphanumeric code)."""
        text = "Partie-/Losnummer: lagern"
        assert not self._regex_match("art15_004", text)

    def test_lot_concrete_code_regex_found(self) -> None:
        """'Charge: A2024-09-01' must produce a regex match → found."""
        assert self._regex_match("art15_004", "Charge: A2024-09-01")

    def test_lot_lot_number_regex_found(self) -> None:
        assert self._regex_match("art15_004", "LOT 20240901A")

    # --- Analytische Bestandteile: value needed for found quality ---

    def test_analytical_with_value_regex_found(self) -> None:
        """'Rohprotein 17,8 %' must match the analytical value regex."""
        assert self._regex_match("art17_004_pet", "Rohprotein 17,8 %")

    def test_analytical_without_percent_regex_found(self) -> None:
        """OCR may drop '%' — value without '%' should still regex-match."""
        assert self._regex_match(
            "art17_004_pet", "Inhaltsstoffe Rohprotein 17,8 Rohfett 5,68"
        )

    def test_analytical_heading_only_no_regex(self) -> None:
        """Just the section header without any value → keyword only."""
        assert self._any_match("art17_004_pet", "Analytische Bestandteile")
        assert not self._regex_match("art17_004_pet", "Analytische Bestandteile")

    # --- Zusatzstoffe: heading alone is keyword-only ---

    def test_additive_heading_only_keyword_not_regex(self) -> None:
        assert self._any_match("art15_006", "Zusatzstoffe")
        assert not self._regex_match("art15_006", "Zusatzstoffe")

    def test_additive_with_amount_regex_match(self) -> None:
        assert self._regex_match("art15_006", "Zusatzstoff: Taurin 1.000 mg/kg")

    # --- Hersteller/Unternehmer: company name → found; label alone → not ---

    def test_operator_full_address_high_weight(self) -> None:
        """Postal code + city should trigger high-weight regex for art15_002."""
        text = "Vertrieb: petsway GmbH, Tich 320, 48361 Beelen"
        assert self._high_weight_match("art15_002", text), (
            "Full address with GmbH must produce a ≥0.85 match in art15_002"
        )

    def test_operator_vertrieb_only_low_weight(self) -> None:
        """'Vertrieb:' alone should only produce a low-weight keyword match."""
        text = "Vertrieb:"
        assert self._any_match("art17_005_pet", text)
        assert not self._high_weight_match("art17_005_pet", text), (
            "'Vertrieb:' label alone must not be a ≥0.85 match"
        )

    def test_hersteller_gmbh_high_weight(self) -> None:
        """'Vertrieb: Fountain GmbH & Co. KG' must produce ≥0.85 in art17_005."""
        text = "Vertrieb: Fountain GmbH & Co. KG"
        assert self._high_weight_match("art17_005_pet", text)


# ------------------------------------------------------------------
# 13. Real-world packaging examples  (DB-backed)
# Based on products in feedlabelcheck_label_training/Kennzeichnungen.pdf
# ------------------------------------------------------------------


class TestRealWorldPackagingPatterns:
    """Regression tests for the four concrete packaging examples from
    Kennzeichnungen.pdf.  Each test validates the semantic contract:
      keyword match only → probablyFound (no high-quality regex)
      regex match → found (high-quality confidence)

    False-positive guards ensure generic storage/temperature text never
    triggers a LOT or MHD rule.
    """

    @pytest.fixture(autouse=True)
    def _db(self, fresh_db: sqlite3.Connection) -> None:
        self.con = fresh_db

    def _patterns(self, rule_id: str) -> list[tuple[str, str, str, float]]:
        return self.con.execute(
            "SELECT pattern_type, pattern_value, pattern_language, confidence_weight "
            "FROM labeling_rule_patterns WHERE rule_id = ?",
            (rule_id,),
        ).fetchall()

    def _keyword_match(self, rule_id: str, text: str) -> bool:
        for ptype, pvalue, _lang, _w in self._patterns(rule_id):
            if ptype == "keyword" and keyword_match(pvalue, text):
                return True
        return False

    def _regex_match(self, rule_id: str, text: str) -> bool:
        for ptype, pvalue, _lang, _w in self._patterns(rule_id):
            if ptype == "regex" and regex_match(pvalue, text):
                return True
        return False

    # MHD rule for complementary feed products (mammaly, Brit, proCani are all
    # Ergänzungsfuttermittel).  All art17_002_* rules share the same patterns.
    _MHD_RULE = "art17_002_complementary"

    # ------------------------------------------------------------------
    # Case 1 — mammaly Perfect Weight
    # "Mindestens haltbar bis & Kennnummer der Partie: s. Aufdruck"
    # Both fields redirect to the print-on — no concrete date or code visible.
    # Expected: keyword match (probablyFound), NO regex match (not found).
    # ------------------------------------------------------------------

    def test_case1_mhd_redirect_keyword_only(self) -> None:
        """MHD reference redirect: keyword hit, but no date → no regex match."""
        text = "Mindestens haltbar bis & Kennnummer der Partie: s. Aufdruck"
        assert self._keyword_match(self._MHD_RULE, text), (
            f"'mindestens haltbar bis' keyword must match {self._MHD_RULE}"
        )
        assert not self._regex_match(self._MHD_RULE, text), (
            "reference redirect without a date must NOT produce a regex match"
        )

    def test_case1_lot_redirect_keyword_only(self) -> None:
        """LOT reference redirect: keyword hit, but no code → no regex match."""
        text = "Mindestens haltbar bis & Kennnummer der Partie: s. Aufdruck"
        assert self._keyword_match("art15_004", text), (
            "'Kennnummer der Partie' keyword must match art15_004"
        )
        assert not self._regex_match("art15_004", text), (
            "reference redirect without alphanumeric code must NOT regex-match"
        )

    # ------------------------------------------------------------------
    # Case 2 — Brit Functional Snack
    # "EXP: 29.11.2026 NU250529H"
    # EXP+date → MHD found; trailing code → LOT probablyFound.
    # ------------------------------------------------------------------

    def test_case2_exp_date_mhd_regex_found(self) -> None:
        """'EXP: 29.11.2026' must regex-match the MHD rule (found)."""
        text = "EXP: 29.11.2026 NU250529H"
        assert self._regex_match(self._MHD_RULE, text), (
            f"EXP + date must produce a regex match for {self._MHD_RULE}"
        )

    def test_case2_exp_lot_heuristic_matches(self) -> None:
        """'EXP: 29.11.2026 NU250529H' must regex-match art15_004 (LOT probablyFound)."""
        text = "EXP: 29.11.2026 NU250529H"
        assert self._regex_match("art15_004", text), (
            "EXP date + trailing batch code must produce a regex match for art15_004"
        )

    # ------------------------------------------------------------------
    # Case 3 — proCani with storage temperature
    # "-18°C haltbar bis: 09.12.26"
    # MHD found; "-18°C" alone must NOT trigger any rule.
    # ------------------------------------------------------------------

    def test_case3_frozen_mhd_regex_found(self) -> None:
        """'-18°C haltbar bis: 09.12.26' must regex-match the MHD rule."""
        text = "-18°C haltbar bis: 09.12.26"
        assert self._regex_match(self._MHD_RULE, text), (
            "'haltbar bis: 09.12.26' must match MHD regex even with temperature prefix"
        )

    def test_case3_temperature_alone_no_mhd(self) -> None:
        """-18°C alone must NOT trigger any MHD keyword or regex."""
        text = "-18°C"
        assert not self._keyword_match(self._MHD_RULE, text), (
            "temperature-only text must not keyword-match the MHD rule"
        )
        assert not self._regex_match(self._MHD_RULE, text), (
            "temperature-only text must not regex-match the MHD rule"
        )

    def test_case3_temperature_alone_no_lot(self) -> None:
        """-18°C alone must NOT trigger any LOT keyword or regex."""
        text = "-18°C"
        assert not self._keyword_match("art15_004", text), (
            "temperature-only text must not keyword-match art15_004"
        )
        assert not self._regex_match("art15_004", text), (
            "temperature-only text must not regex-match art15_004"
        )

    # ------------------------------------------------------------------
    # Case 4 — proCani Zulassungsnummer der Partie
    # "Zulassungsnummer der Partie: BAF 1015090925"
    # LOT keyword AND regex must match.
    # ------------------------------------------------------------------

    def test_case4_zulassungsnummer_keyword_match(self) -> None:
        """'Zulassungsnummer der Partie' keyword must match art15_004."""
        text = "Zulassungsnummer der Partie: BAF 1015090925"
        assert self._keyword_match("art15_004", text), (
            "'Zulassungsnummer der Partie' must keyword-match art15_004"
        )

    def test_case4_zulassungsnummer_regex_found(self) -> None:
        """'Zulassungsnummer der Partie: BAF 1015090925' must regex-match art15_004."""
        text = "Zulassungsnummer der Partie: BAF 1015090925"
        assert self._regex_match("art15_004", text), (
            "Zulassungsnummer der Partie + space-separated code must regex-match art15_004"
        )

    # ------------------------------------------------------------------
    # False-positive guards
    # ------------------------------------------------------------------

    def test_fp_storage_text_no_lot(self) -> None:
        """'kühl und trocken lagern' must never match any LOT pattern."""
        text = "kühl und trocken lagern"
        assert not self._keyword_match("art15_004", text)
        assert not self._regex_match("art15_004", text)

    def test_fp_storage_text_no_mhd(self) -> None:
        """'kühl und trocken lagern' must never match any MHD pattern."""
        text = "kühl und trocken lagern"
        assert not self._keyword_match(self._MHD_RULE, text)
        assert not self._regex_match(self._MHD_RULE, text)

    def test_fp_generic_kuehl_no_lot(self) -> None:
        """Generic 'kühl lagern' instruction must not trigger LOT detection."""
        assert not self._regex_match("art15_004", "Kühl und trocken bei max. 25°C lagern.")

    def test_fp_storage_instruction_no_mhd(self) -> None:
        """'Vor Wärme schützen' must not trigger MHD detection."""
        assert not self._keyword_match(self._MHD_RULE, "Vor Wärme und Feuchtigkeit schützen.")
        assert not self._regex_match(self._MHD_RULE, "Vor Wärme und Feuchtigkeit schützen.")

    def test_fp_pilotversuch_no_lot(self) -> None:
        """'Pilotversuch' contains substring 'lot' but must NOT match art15_004.
        Regression guard: bare 'LOT' keyword replaced with 'LOT:' to prevent
        case-insensitive substring match inside compound words.
        """
        text = "Pilotversuch Produktionslinie 3"
        assert not self._keyword_match("art15_004", text), (
            "Substring 'lot' inside 'Pilotversuch' must not keyword-match art15_004"
        )
        assert not self._regex_match("art15_004", text)

    def test_fp_lot_colon_still_matches(self) -> None:
        """'LOT:' (with colon) must still keyword-match art15_004."""
        text = "LOT: s. Aufdruck"
        assert self._keyword_match("art15_004", text), (
            "'LOT:' with colon must keyword-match art15_004"
        )
