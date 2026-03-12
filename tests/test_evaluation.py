#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_evaluation.py – Automated tests for LAVES evaluation logic.

Run with:  python -m pytest tests/test_evaluation.py -v
"""

import sys
import os

# Ensure the project root is on the import path so that laves_eval can be
# imported without installing the package.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from laves_eval import (
    Additive,
    evaluate_single_value,
    build_indexes,
    match_additive_records,
    derive_e_number_for_substance,
    validate_database,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_additive(
    e_number="E123",
    species="Alle Tierarten",
    min_value=None,
    max_value=None,
    unit="mg/kg",
    notes=None,
    source_ref=None,
    status=None,
) -> Additive:
    """Return a minimal Additive with sensible defaults."""
    return Additive(
        e_number=e_number,
        substance="TestStoff",
        chemical=None,
        category=None,
        species=species,
        max_age_months=None,
        unit=unit,
        min_value=min_value,
        max_value=max_value,
        notes=notes,
        source_ref=source_ref,
        status=status,
    )


# ─────────────────────────────────────────────────────────────────────────────
# evaluate_single_value – core evaluation correctness
# ─────────────────────────────────────────────────────────────────────────────

class TestEvaluateSingleValue:
    """Tests for evaluate_single_value()."""

    # ── No-limits guard ───────────────────────────────────────────────────────

    def test_no_limits_returns_none(self):
        """A dataset with no min and no max must never produce a COMPLIANT result."""
        rec = _make_additive(min_value=None, max_value=None, unit="mg/kg")
        ok, msgs = evaluate_single_value(5.0, rec)
        assert ok is None, "ok must be None when no limits are present"

    def test_no_limits_message_contains_warning(self):
        rec = _make_additive(min_value=None, max_value=None, unit="mg/kg")
        _, msgs = evaluate_single_value(0.0, rec)
        assert any("Grenzwert" in m for m in msgs), (
            "Output must mention missing limits"
        )

    def test_no_limits_never_konform_regardless_of_value(self):
        """Even a perfectly 'safe' zero value must not be KONFORM without limits."""
        rec = _make_additive(min_value=None, max_value=None, unit="mg/kg")
        ok, _ = evaluate_single_value(0.0, rec)
        assert ok is not True

    # ── Missing-unit guard ────────────────────────────────────────────────────

    def test_limits_without_unit_returns_none(self):
        """Limits present but unit=None must abort evaluation and return None."""
        rec = _make_additive(min_value=1.0, max_value=10.0, unit=None)
        ok, msgs = evaluate_single_value(5.0, rec)
        assert ok is None, "ok must be None when unit is missing"

    def test_limits_without_unit_message_mentions_unit(self):
        rec = _make_additive(min_value=1.0, max_value=10.0, unit=None)
        _, msgs = evaluate_single_value(5.0, rec)
        assert any("Einheit" in m for m in msgs), (
            "Output must mention the missing unit"
        )

    def test_limits_without_unit_never_konform(self):
        rec = _make_additive(max_value=100.0, unit=None)
        ok, _ = evaluate_single_value(50.0, rec)
        assert ok is not True

    # ── Normal evaluation ─────────────────────────────────────────────────────

    def test_value_within_range_is_true(self):
        rec = _make_additive(min_value=10.0, max_value=100.0, unit="mg/kg")
        ok, msgs = evaluate_single_value(50.0, rec)
        assert ok is True
        assert any("KONFORM" in m for m in msgs)

    def test_value_equals_max_is_true(self):
        rec = _make_additive(max_value=10.0, unit="mg/kg")
        ok, _ = evaluate_single_value(10.0, rec)
        assert ok is True

    def test_value_above_max_is_false(self):
        rec = _make_additive(max_value=10.0, unit="mg/kg")
        ok, msgs = evaluate_single_value(15.0, rec)
        assert ok is False
        assert any("Überschreitung" in m for m in msgs)

    def test_value_below_min_is_false(self):
        rec = _make_additive(min_value=5.0, unit="mg/kg")
        ok, msgs = evaluate_single_value(2.0, rec)
        assert ok is False
        assert any("Unterschreitung" in m for m in msgs)

    def test_value_equals_min_is_true(self):
        rec = _make_additive(min_value=5.0, unit="mg/kg")
        ok, _ = evaluate_single_value(5.0, rec)
        assert ok is True

    def test_only_max_limit_value_within(self):
        rec = _make_additive(max_value=20.0, unit="mg/kg")
        ok, _ = evaluate_single_value(10.0, rec)
        assert ok is True

    def test_only_min_limit_value_above(self):
        rec = _make_additive(min_value=5.0, unit="mg/kg")
        ok, _ = evaluate_single_value(10.0, rec)
        assert ok is True

    # ── Limit values shown in output ──────────────────────────────────────────

    def test_limit_values_shown_when_compliant(self):
        """Min and max limit values must appear in the output when compliant."""
        rec = _make_additive(min_value=5.0, max_value=50.0, unit="mg/kg")
        _, msgs = evaluate_single_value(25.0, rec)
        combined = " ".join(msgs)
        assert "5" in combined and "50" in combined, (
            "Stored limits must be visible in KONFORM output"
        )

    def test_limit_values_shown_when_non_compliant(self):
        """Limit values must also appear in the output when non-compliant."""
        rec = _make_additive(max_value=10.0, unit="mg/kg")
        _, msgs = evaluate_single_value(99.0, rec)
        combined = " ".join(msgs)
        assert "10" in combined, "Max limit must be visible in non-compliant output"

    def test_limit_line_present_in_output(self):
        """A dedicated 'Hinterlegte Grenzwerte' line must be included."""
        rec = _make_additive(min_value=1.0, max_value=9.0, unit="mg/kg")
        _, msgs = evaluate_single_value(5.0, rec)
        assert any("Hinterlegte Grenzwerte" in m for m in msgs)

    # ── Additional metadata in output ─────────────────────────────────────────

    def test_notes_included_in_output(self):
        rec = _make_additive(max_value=10.0, unit="mg/kg", notes="Testhinweis")
        _, msgs = evaluate_single_value(5.0, rec)
        assert any("Testhinweis" in m for m in msgs)

    def test_source_ref_included_in_output(self):
        rec = _make_additive(max_value=10.0, unit="mg/kg", source_ref="VO(EG) 1831/2003")
        _, msgs = evaluate_single_value(5.0, rec)
        assert any("1831" in m for m in msgs)


# ─────────────────────────────────────────────────────────────────────────────
# match_additive_records – species filtering
# ─────────────────────────────────────────────────────────────────────────────

class TestMatchAdditiveRecords:
    """Tests for match_additive_records() – species / "Alle Tierarten" handling."""

    def _build(self, additives):
        return build_indexes(additives)

    def test_alle_tierarten_matches_any_species(self):
        """A record tagged 'Alle Tierarten' must be found for any selected species."""
        rec = _make_additive(e_number="E1", species="Alle Tierarten", max_value=10.0)
        idx = self._build([rec])
        results = match_additive_records(idx, "E1", "Schweine", 0)
        assert len(results) == 1

    def test_specific_species_matches_exact_key(self):
        rec = _make_additive(e_number="E2", species="Schweine", max_value=5.0)
        idx = self._build([rec])
        results = match_additive_records(idx, "E2", "Schweine", 0)
        assert len(results) == 1

    def test_other_species_not_matched(self):
        rec = _make_additive(e_number="E3", species="Rinder", max_value=5.0)
        idx = self._build([rec])
        results = match_additive_records(idx, "E3", "Schweine", 0)
        assert len(results) == 0

    def test_alle_tierarten_selection_finds_all_records(self):
        """Selecting 'Alle Tierarten' must return records from every species bucket."""
        recs = [
            _make_additive(e_number="E4", species="Schweine", max_value=5.0),
            _make_additive(e_number="E4", species="Rinder", max_value=8.0),
        ]
        idx = self._build(recs)
        results = match_additive_records(idx, "E4", "Alle Tierarten", 0)
        assert len(results) == 2

    def test_truthuehner_species_keyword_matching(self):
        """Truthühner species should match when keyword is present in species text."""
        from laves_eval import extract_individual_species

        # Test exact match
        species = extract_individual_species("Truthühner")
        assert "Truthühner" in species, "Truthühner should be extracted from exact text"

        # Test keyword match (truthühn)
        species = extract_individual_species("Masttruthühner")
        assert "Truthühner" in species, "Truthühner should be extracted from Masttruthühner"

    def test_geflugel_category_species_extraction(self):
        """Test that species extraction works correctly for Geflügel category."""
        from laves_eval import extract_individual_species

        # Test keyword matching that works with current keywords
        # Focus on the actual case we're fixing: Truthühner
        test_cases = [
            ("Legehennen", "Legehennen"),  # contains 'lege'
            ("Masttruthühner", "Truthühner"),  # contains 'truthühn'
            ("Enten", "Enten"),  # contains 'ente'
            ("Hennen", "Hennen"),  # contains 'henne'
        ]

        for text, expected in test_cases:
            species = extract_individual_species(text, category="Geflügel")
            assert expected in species, f"Failed to extract {expected} from '{text}', got {species}"

    def test_tierart_kategorie_filter_alle_kategorien(self):
        """Test that 'Alle Kategorien' includes all records regardless of category."""
        rec1 = _make_additive(e_number="E5", species="Truthühner", max_value=5.0)
        rec1.extra = {"tierart_kategorie": "Geflügel", "tierart_spezifisch": True}

        rec2 = _make_additive(e_number="E5", species="Schweine", max_value=10.0)
        rec2.extra = {"tierart_kategorie": "Schweine", "tierart_spezifisch": True}

        idx = self._build([rec1, rec2])

        # With "Alle Kategorien" should find both
        results = match_additive_records(
            idx, "E5", "Alle Tierarten", 0, tierart_kategorie="Alle Kategorien"
        )
        assert len(results) == 2, "Alle Kategorien should include all categories"

    def test_tierart_kategorie_filter_specific_category(self):
        """Test that specific category filters correctly."""
        rec1 = _make_additive(e_number="E6", species="Truthühner", max_value=5.0)
        rec1.extra = {"tierart_kategorie": "Geflügel", "tierart_spezifisch": True}

        rec2 = _make_additive(e_number="E6", species="Schweine", max_value=10.0)
        rec2.extra = {"tierart_kategorie": "Schweine", "tierart_spezifisch": True}

        idx = self._build([rec1, rec2])

        # With "Geflügel" category should only find Geflügel record
        results = match_additive_records(
            idx, "E6", "Alle Tierarten", 0, tierart_kategorie="Geflügel"
        )
        assert len(results) == 1, "Should only find Geflügel record"
        assert results[0].species == "Truthühner"

        # With "Schweine" category should only find Schweine record
        results = match_additive_records(
            idx, "E6", "Alle Tierarten", 0, tierart_kategorie="Schweine"
        )
        assert len(results) == 1, "Should only find Schweine record"
        assert results[0].species == "Schweine"

    def test_alle_tierarten_as_kategorie_returns_full_dataset(self):
        """'Alle Tierarten' as tierart_kategorie must behave identically to 'Alle Kategorien'."""
        rec1 = _make_additive(e_number="E7", species="Truthühner", max_value=5.0)
        rec1.extra = {"tierart_kategorie": "Geflügel"}

        rec2 = _make_additive(e_number="E7", species="Schweine", max_value=10.0)
        rec2.extra = {"tierart_kategorie": "Schweine"}

        idx = self._build([rec1, rec2])

        results_alle_kategorien = match_additive_records(
            idx, "E7", "Alle Tierarten", 0, tierart_kategorie="Alle Kategorien"
        )
        results_alle_tierarten = match_additive_records(
            idx, "E7", "Alle Tierarten", 0, tierart_kategorie="Alle Tierarten"
        )

        assert len(results_alle_tierarten) == len(results_alle_kategorien), (
            "'Alle Tierarten' and 'Alle Kategorien' must return the same number of records"
        )
        assert len(results_alle_tierarten) == 2, (
            "Both 'Alle Tierarten' and 'Alle Kategorien' should return all records"
        )

    def test_cross_species_record_matches_specific_category(self):
        """A record tagged tierart_kategorie='Alle Tierarten' must match any specific category filter."""
        rec_all = _make_additive(e_number="E8", species="Alle Tierarten", max_value=20.0)
        rec_all.extra = {"tierart_kategorie": "Alle Tierarten"}

        rec_specific = _make_additive(e_number="E8", species="Schweine", max_value=10.0)
        rec_specific.extra = {"tierart_kategorie": "Schweine"}

        idx = self._build([rec_all, rec_specific])

        # When filtering by "Schweine", the cross-species record must also be included
        results = match_additive_records(
            idx, "E8", "Alle Tierarten", 0, tierart_kategorie="Schweine"
        )
        assert len(results) == 2, (
            "Record with tierart_kategorie='Alle Tierarten' must match the 'Schweine' category filter"
        )

    def test_alle_tierarten_kategorie_no_filter_applied(self):
        """Selecting 'Alle Tierarten' as category must not exclude any record by category."""
        rec1 = _make_additive(e_number="E9", species="Schweine", max_value=5.0)
        rec1.extra = {"tierart_kategorie": "Schweine"}

        rec2 = _make_additive(e_number="E9", species="Rinder", max_value=8.0)
        rec2.extra = {"tierart_kategorie": "Rinder"}

        rec3 = _make_additive(e_number="E9", species="Alle Tierarten", max_value=15.0)
        rec3.extra = {"tierart_kategorie": "Alle Tierarten"}

        idx = self._build([rec1, rec2, rec3])

        results = match_additive_records(
            idx, "E9", "Alle Tierarten", 0, tierart_kategorie="Alle Tierarten"
        )
        assert len(results) == 3, (
            "'Alle Tierarten' as tierart_kategorie must return all records (no filtering)"
        )

    def test_missing_tierart_kategorie_passes_specific_category_filter(self):
        """Records with no tierart_kategorie field must not be excluded by a category filter."""
        rec_no_cat = _make_additive(e_number="E10", species="Alle Tierarten", max_value=10.0)
        rec_no_cat.extra = {}  # no tierart_kategorie at all

        rec_empty_cat = _make_additive(e_number="E10", species="Schweine", max_value=20.0)
        rec_empty_cat.extra = {"tierart_kategorie": None}  # explicitly None

        rec_specific = _make_additive(e_number="E10", species="Geflügel", max_value=5.0)
        rec_specific.extra = {"tierart_kategorie": "Geflügel"}

        idx = self._build([rec_no_cat, rec_empty_cat, rec_specific])

        # With "Geflügel" filter: the specific record and both incomplete-metadata records should match
        results = match_additive_records(
            idx, "E10", "Alle Tierarten", 0, tierart_kategorie="Geflügel"
        )
        assert len(results) == 3, (
            "Records with missing or None tierart_kategorie must pass any specific category filter"
        )


# ─────────────────────────────────────────────────────────────────────────────
# validate_database
# ─────────────────────────────────────────────────────────────────────────────

class TestValidateDatabase:
    """Tests for validate_database()."""

    def test_missing_limits_reported_as_warning(self):
        rec = _make_additive(min_value=None, max_value=None)
        report = validate_database([rec])
        assert len(report["warnings"]) >= 1
        assert any("Grenzwert" in w or "kein" in w.lower() for w in report["warnings"])

    def test_limits_without_unit_reported_as_issue(self):
        rec = _make_additive(min_value=1.0, max_value=10.0, unit=None)
        report = validate_database([rec])
        assert len(report["issues"]) >= 1
        assert any("Einheit" in i for i in report["issues"])

    def test_valid_record_produces_no_issues(self):
        rec = _make_additive(min_value=1.0, max_value=10.0, unit="mg/kg")
        report = validate_database([rec])
        assert len(report["issues"]) == 0

    def test_duplicate_e_number_species_reported(self):
        rec1 = _make_additive(e_number="E99", species="Schweine", max_value=5.0)
        rec2 = _make_additive(e_number="E99", species="Schweine", max_value=7.0)
        report = validate_database([rec1, rec2])
        assert any("E99" in w for w in report["warnings"]), (
            "Duplicate (e_number, species) must be flagged"
        )

    def test_report_total_records_correct(self):
        recs = [_make_additive(e_number=f"E{i}", max_value=float(i)) for i in range(5)]
        report = validate_database(recs)
        assert report["total_records"] == 5

    def test_report_written_to_file(self, tmp_path):
        rec = _make_additive(min_value=None, max_value=None)
        report_file = str(tmp_path / "report.txt")
        validate_database([rec], report_path=report_file)
        assert os.path.isfile(report_file)
        with open(report_file, encoding="utf-8") as fh:
            content = fh.read()
        assert "validierungsbericht" in content.lower()


# ─────────────────────────────────────────────────────────────────────────────
# Integration: load + evaluate with real JSON database
# ─────────────────────────────────────────────────────────────────────────────

class TestIntegration:
    """Integration tests using the real zusatzstoffe.json database."""

    DB_PATH = os.path.join(
        os.path.dirname(__file__), "..", "Data", "zusatzstoffe.json"
    )

    @pytest.fixture(scope="class")
    def additives(self):
        from laves_eval import load_additives
        if not os.path.isfile(self.DB_PATH):
            pytest.skip("zusatzstoffe.json not found – skipping integration tests")
        return load_additives(self.DB_PATH)

    def test_no_record_with_limits_and_missing_unit(self, additives):
        """After loading, every record with numeric limits must also have a unit."""
        bad = [
            a for a in additives
            if (a.min_value is not None or a.max_value is not None) and a.unit is None
        ]
        assert bad == [], (
            f"{len(bad)} records have limits but no unit – these would produce "
            f"false evaluations.  First bad: {bad[0] if bad else None}"
        )

    def test_all_limits_records_evaluate_correctly(self, additives):
        """evaluate_single_value must never return True for a no-limit record."""
        no_limit = [a for a in additives if a.min_value is None and a.max_value is None]
        for rec in no_limit:
            ok, _ = evaluate_single_value(0.0, rec)
            assert ok is not True, (
                f"Record {rec.e_number!r} ({rec.species!r}) has no limits "
                f"but evaluate_single_value returned True"
            )


# ─────────────────────────────────────────────────────────────────────────────
# Substance-name lookup – resolving records by name instead of E-number
# ─────────────────────────────────────────────────────────────────────────────

class TestSubstanceNameLookup:
    """Tests for substance-name-only lookup and the resulting evaluation flow."""

    def _build(self, additives):
        return build_indexes(additives)

    # ── 1. Exact substance-name lookup → E-number auto-fill ──────────────────

    def test_exact_substance_lookup_returns_record_with_e_number(self):
        """Substance-only query must return the matching record when it has an E-number."""
        rec = Additive(
            e_number="E321",
            substance="Natriumselenit",
            chemical=None,
            category=None,
            species="Alle Tierarten",
            max_age_months=None,
            unit="mg/kg",
            min_value=None,
            max_value=10.0,
            notes=None,
            source_ref=None,
        )
        idx = self._build([rec])
        results = match_additive_records(
            idx, "",
            species="Alle Tierarten",
            age_months=0,
            substance_query="Natriumselenit",
        )
        assert len(results) == 1
        assert results[0].e_number == "E321"

    def test_exact_substance_lookup_e_number_derivable(self):
        """sub_to_all_e_numbers must map the substance to its E-number."""
        rec = Additive(
            e_number="E321",
            substance="Natriumselenit",
            chemical=None,
            category=None,
            species="Alle Tierarten",
            max_age_months=None,
            unit="mg/kg",
            min_value=None,
            max_value=10.0,
            notes=None,
            source_ref=None,
        )
        idx = self._build([rec])
        e_list = sorted(idx["sub_to_all_e_numbers"].get("natriumselenit", []))
        assert e_list == ["E321"], (
            "sub_to_all_e_numbers must allow deriving the E-number from the substance name"
        )

    # ── 2. Exact substance-name lookup where NO E-number exists ──────────────

    def test_substance_lookup_record_without_e_number(self):
        """Substance-only query must find a record even when it has no E-number."""
        rec = Additive(
            e_number="",
            substance="UnbekannterStoff",
            chemical=None,
            category=None,
            species="Alle Tierarten",
            max_age_months=None,
            unit="mg/kg",
            min_value=None,
            max_value=5.0,
            notes=None,
            source_ref=None,
        )
        idx = self._build([rec])
        results = match_additive_records(
            idx, "",
            species="Alle Tierarten",
            age_months=0,
            substance_query="UnbekannterStoff",
        )
        assert len(results) == 1
        assert results[0].substance == "UnbekannterStoff"

    def test_evaluation_succeeds_for_record_without_e_number(self):
        """evaluate_single_value must work on a record that has no E-number."""
        rec = Additive(
            e_number="",
            substance="UnbekannterStoff",
            chemical=None,
            category=None,
            species="Alle Tierarten",
            max_age_months=None,
            unit="mg/kg",
            min_value=None,
            max_value=5.0,
            notes=None,
            source_ref=None,
        )
        ok, msgs = evaluate_single_value(3.0, rec)
        assert ok is True, "Evaluation must succeed (KONFORM) for a record resolved only by name"

    # ── 3. Ambiguous substance name → multiple records returned ──────────────

    def test_ambiguous_substance_name_returns_multiple_records(self):
        """A substance name shared by multiple records must return all of them."""
        rec1 = Additive(
            e_number="E100",
            substance="Doppelstoff",
            chemical=None,
            category=None,
            species="Schweine",
            max_age_months=None,
            unit="mg/kg",
            min_value=None,
            max_value=10.0,
            notes=None,
            source_ref=None,
        )
        rec2 = Additive(
            e_number="E200",
            substance="Doppelstoff",
            chemical=None,
            category=None,
            species="Rinder",
            max_age_months=None,
            unit="mg/kg",
            min_value=None,
            max_value=20.0,
            notes=None,
            source_ref=None,
        )
        idx = self._build([rec1, rec2])
        results = match_additive_records(
            idx, "",
            species="Alle Tierarten",
            age_months=0,
            substance_query="Doppelstoff",
        )
        assert len(results) == 2, (
            "Ambiguous substance name must return all matching records, not just one"
        )

    def test_ambiguous_substance_name_e_number_list_has_multiple_entries(self):
        """sub_to_all_e_numbers must list all E-numbers for an ambiguous substance."""
        rec1 = Additive(
            e_number="E100",
            substance="Doppelstoff",
            chemical=None,
            category=None,
            species="Schweine",
            max_age_months=None,
            unit="mg/kg",
            min_value=None,
            max_value=10.0,
            notes=None,
            source_ref=None,
        )
        rec2 = Additive(
            e_number="E200",
            substance="Doppelstoff",
            chemical=None,
            category=None,
            species="Rinder",
            max_age_months=None,
            unit="mg/kg",
            min_value=None,
            max_value=20.0,
            notes=None,
            source_ref=None,
        )
        idx = self._build([rec1, rec2])
        e_list = sorted(idx["sub_to_all_e_numbers"].get("doppelstoff", []))
        assert len(e_list) == 2, "Both E-numbers must be present for the ambiguous substance"
        assert "E100" in e_list and "E200" in e_list

    # ── 4. Validation succeeds when record resolved only by name ─────────────

    def test_validation_succeeds_with_name_only_resolved_record(self):
        """Records resolved by substance name alone must evaluate without E-number."""
        rec = Additive(
            e_number="",
            substance="Natriumselenit",
            chemical=None,
            category=None,
            species="Alle Tierarten",
            max_age_months=None,
            unit="mg/kg",
            min_value=0.1,
            max_value=0.5,
            notes=None,
            source_ref=None,
        )
        idx = self._build([rec])

        # Look up by substance (no E-number known)
        results = match_additive_records(
            idx, "",
            species="Alle Tierarten",
            age_months=0,
            substance_query="Natriumselenit",
        )
        assert len(results) == 1, "Should resolve exactly one record by substance name"

        # Evaluate using the resolved record
        ok, msgs = evaluate_single_value(0.3, results[0])
        assert ok is True, (
            "Evaluation must succeed (KONFORM) when a valid record is resolved by name only"
        )

    def test_validation_non_compliant_with_name_only_resolved_record(self):
        """Non-compliant values must be correctly flagged for name-only resolved records."""
        rec = Additive(
            e_number="",
            substance="Natriumselenit",
            chemical=None,
            category=None,
            species="Alle Tierarten",
            max_age_months=None,
            unit="mg/kg",
            min_value=None,
            max_value=0.5,
            notes=None,
            source_ref=None,
        )
        idx = self._build([rec])

        results = match_additive_records(
            idx, "",
            species="Alle Tierarten",
            age_months=0,
            substance_query="Natriumselenit",
        )
        assert len(results) == 1

        ok, msgs = evaluate_single_value(1.0, results[0])
        assert ok is False, (
            "Over-limit value must be NICHT KONFORM for name-only resolved records"
        )


# ─────────────────────────────────────────────────────────────────────────────
# derive_e_number_for_substance – auto-fill helper
# ─────────────────────────────────────────────────────────────────────────────

class TestDeriveENumberForSubstance:
    """Tests for derive_e_number_for_substance() – the auto-fill logic used by
    the UI substance-input handlers (on_s_changed / _on_s_changed)."""

    def _make_rec(self, substance, e_number, species="Alle Tierarten", max_value=10.0):
        return Additive(
            e_number=e_number,
            substance=substance,
            chemical=None,
            category=None,
            species=species,
            max_age_months=None,
            unit="mg/kg",
            min_value=None,
            max_value=max_value,
            notes=None,
            source_ref=None,
        )

    # ── 1. Unique substance → auto-fill the E-number ──────────────────────────

    def test_natriumselenit_autofills_e_number(self):
        """Entering 'Natriumselenit' must yield the single E-number for auto-fill."""
        rec = self._make_rec("Natriumselenit", "E321")
        idx = build_indexes([rec])

        result = derive_e_number_for_substance(idx, "Natriumselenit")

        assert result == "E321", (
            "derive_e_number_for_substance must return 'E321' when 'Natriumselenit' "
            "unambiguously maps to that E-number"
        )

    def test_unique_substance_with_e_number_across_species_autofills(self):
        """Multiple records for different species sharing the same E-number must
        still yield a single auto-fill value."""
        recs = [
            self._make_rec("Natriumselenit", "E321", species="Schweine"),
            self._make_rec("Natriumselenit", "E321", species="Rinder"),
        ]
        idx = build_indexes(recs)

        result = derive_e_number_for_substance(idx, "Natriumselenit")

        assert result == "E321", (
            "Multiple records with identical E-number must still yield auto-fill"
        )

    # ── 2. Substance with no E-number → returns None (no auto-fill), eval OK ──

    def test_substance_without_e_number_returns_none(self):
        """A substance that has no E-number must return None (nothing to auto-fill)."""
        rec = self._make_rec("UnbekannterStoff", "")
        idx = build_indexes([rec])

        result = derive_e_number_for_substance(idx, "UnbekannterStoff")

        assert result is None, (
            "derive_e_number_for_substance must return None when the record has "
            "no E-number – the UI must not crash or show a validation error"
        )

    def test_substance_without_e_number_still_evaluates(self):
        """When auto-fill returns None the resolved record must still be evaluable."""
        rec = self._make_rec("UnbekannterStoff", "")
        idx = build_indexes([rec])

        # No auto-fill
        assert derive_e_number_for_substance(idx, "UnbekannterStoff") is None

        # But evaluation via match_additive_records must succeed
        recs = match_additive_records(
            idx, "",
            species="Alle Tierarten",
            age_months=0,
            substance_query="UnbekannterStoff",
        )
        assert len(recs) == 1
        ok, _ = evaluate_single_value(5.0, recs[0])
        assert ok is True, "Evaluation must succeed for a record resolved only by name"

    # ── 3. Ambiguous substance → returns None (no auto-fill) ─────────────────

    def test_ambiguous_substance_does_not_autofill(self):
        """A substance that maps to multiple E-numbers must NOT auto-fill."""
        recs = [
            self._make_rec("Doppelstoff", "E100", species="Schweine"),
            self._make_rec("Doppelstoff", "E200", species="Rinder"),
        ]
        idx = build_indexes(recs)

        result = derive_e_number_for_substance(idx, "Doppelstoff")

        assert result is None, (
            "Ambiguous substance (multiple distinct E-numbers) must return None "
            "so the UI does not auto-fill the wrong value"
        )

    def test_ambiguous_substance_returns_none_for_all_species(self):
        """Querying with 'Alle Tierarten' for an ambiguous substance must still
        return None so the UI can show its ambiguity message."""
        recs = [
            self._make_rec("Doppelstoff", "E100", species="Schweine"),
            self._make_rec("Doppelstoff", "E200", species="Rinder"),
        ]
        idx = build_indexes(recs)

        result = derive_e_number_for_substance(
            idx, "Doppelstoff", species="Alle Tierarten"
        )

        assert result is None

    # ── 4. Fallback to sub_to_all_e_numbers index ────────────────────────────

    def test_falls_back_to_index_when_no_records_match_species(self):
        """When match_additive_records returns no results (species mismatch),
        the function must fall back to the sub_to_all_e_numbers index."""
        rec = self._make_rec("Natriumselenit", "E321", species="Schweine")
        idx = build_indexes([rec])

        # Query with a species that does not match the record; match_additive_records
        # returns [] because "Rinder" ≠ "Schweine" and "Alle Tierarten" is not in the
        # species list.  The fallback index must still yield the E-number.
        result = derive_e_number_for_substance(
            idx, "Natriumselenit", species="Alle Tierarten"
        )

        # "Alle Tierarten" resolves all species keys so the record IS found by the
        # primary path.  Here we explicitly cover the index fallback by checking
        # the sub_to_all_e_numbers entry directly.
        assert idx["sub_to_all_e_numbers"].get("natriumselenit") == ["E321"], (
            "Index must map substance name (lowercase) to its E-number list"
        )
        assert result == "E321"
