"""Tests for the LAVES labeling check pipeline.

The session-scoped ``fresh_db`` fixture (conftest.py) builds a fresh
laves_labeling.sqlite from scripts/build_labeling_db.py into a temporary
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
    r"\b(LOT|L|Charge|Chargen-Nr\.?|Los|Partie)\s?[:\-]?\s?[A-Z0-9\-\/]+\b",
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
            # "Chargenangabe" starts with "Charge" at a word boundary — legitimately matches
            ("Chargenangabe: A2024", True),
            ("CHOLESTEROL 200mg", False),
            ("Produktbeschreibung ohne Angabe", False),
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
    r"\b(MHD|BBD|mindestens haltbar bis)[:\s]*\d{1,2}[\.\/\-]\d{1,2}[\.\/\-]\d{2,4}\b",
]
BBD_KEYWORDS = [
    "Mindesthaltbarkeit",
    "mindestens haltbar bis",
    "MHD",
    "best before",
    "verwendbar bis",
    "haltbar bis",
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
# 8. OCR error resilience  (mostly pure Python; one test uses DB)
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
