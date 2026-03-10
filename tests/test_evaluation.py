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
        content = open(report_file, encoding="utf-8").read()
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
