#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
laves_eval.py – Pure evaluation logic for LAVES.

This module contains all data-loading, index-building, species-matching
and evaluation functions.  It has NO dependency on PySide6 / Qt so that
it can be imported and unit-tested without a display server.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# =========================================================
# Logging
# =========================================================

logger = logging.getLogger("laves_eval")


def setup_logging(log_path: Optional[str] = None, level: int = logging.DEBUG) -> logging.Logger:
    """Configure and return the laves_eval logger.

    Call this once at application start-up with the desired *log_path*.
    Subsequent calls with the same logger are no-ops (handlers are only
    added once).
    """
    if logger.handlers:
        return logger

    logger.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")

    if log_path:
        try:
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            fh = logging.FileHandler(log_path, encoding="utf-8")
            fh.setLevel(level)
            fh.setFormatter(fmt)
            logger.addHandler(fh)
        except Exception as exc:  # pragma: no cover
            logging.getLogger(__name__).warning(
                "Cannot open log file %s: %s", log_path, exc
            )

    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)          # console: warnings and above only
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    return logger


# =========================================================
# Data model
# =========================================================

@dataclass
class Additive:
    e_number: str
    substance: Optional[str]
    chemical: Optional[str]
    category: Optional[str]
    species: str
    max_age_months: Optional[int]
    unit: Optional[str]
    min_value: Optional[float]
    max_value: Optional[float]
    notes: Optional[str]
    source_ref: Optional[str]
    has_combination_rule: Optional[bool] = False
    combination_rule_ids: Optional[List[str]] = None
    feed_type_allowed: Optional[List[str]] = None
    feed_type_primary: Optional[str] = None
    status: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ComboRule:
    rule_id: str
    description: str
    affected_e_numbers: Optional[List[str]]
    affected_categories: Optional[List[str]]
    max_total_value: float
    unit: str
    species: List[str]
    source_refs: Optional[List[str]] = None
    confidence: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


# =========================================================
# Substance-name normalization & synonym helpers
# =========================================================

# Matches element/symbol prefixes used in older regulatory entries, e.g.:
#   "Selen-Se Natriumselenit*"  →  requires the "-Symbol" part (e.g. -Se, -Fe)
#   "Eisen -Fe Eisencarbonat*"  →  space before hyphen is allowed
# The -Symbol part is MANDATORY so that ordinary German words that happen to
# start with a capital letter (e.g. "Flüssige", "Organische") are NOT stripped.
_ELEM_PREFIX_RE = re.compile(
    r"^[A-ZÄÖÜ][a-zäöüß]+"   # German element name (capital + lowercase)
    r"\s*-[A-Z][a-z]{0,2}"    # required -Symbol  (e.g. -Se, -Fe, -J, -Cu)
    r"\s+"                     # trailing whitespace before substance name
)

# Matches leading Roman-numeral annotations like "(i)* ", "(ii)* ", "(iii)* "
_ANNOT_PREFIX_RE = re.compile(r"^\([ivxIVX]+\)\*?\s*")


def normalize_substance_name(name: str) -> str:
    """Return a canonical lowercase key for *name*.

    Handles:

    * trailing ``*`` characters (e.g. ``Natriumselenit*``)
    * leading element/symbol prefixes such as ``Selen-Se``, ``Eisen -Fe``
      that appear in older regulatory entries
    * leading Roman-numeral annotation prefixes like ``(i)*``, ``(ii)*``
    * extra surrounding whitespace

    The returned key is used to detect that substance names which differ only
    in historical notation (element prefix, trailing asterisk, annotation) are
    really the same canonical additive.

    Examples::

        normalize_substance_name("Natriumselenit")            == "natriumselenit"
        normalize_substance_name("Selen-Se Natriumselenit*")  == "natriumselenit"
        normalize_substance_name("Eisen -Fe Eisencarbonat*")  == "eisencarbonat"
        normalize_substance_name("(i)* Kaliumdihydrogen-orthophosphat")
            == "kaliumdihydrogen-orthophosphat"
    """
    if not name:
        return ""
    s = name.strip()
    # Remove trailing asterisk(s)
    s = s.rstrip("*").rstrip()
    # Remove leading annotations: (i)*, (ii)*, (iii)*, …
    s = _ANNOT_PREFIX_RE.sub("", s)
    # Remove leading element/symbol prefix, e.g. "Selen-Se ", "Eisen -Fe "
    s = _ELEM_PREFIX_RE.sub("", s)
    # Second pass: remove any stray trailing asterisk uncovered after prefix removal
    s = s.rstrip("*").rstrip()
    return s.lower()


def _dedup_species_key(species: str) -> str:
    """Return a normalised species key for synonym-grouping purposes.

    Species strings in the historical dataset sometimes contain 'Alle Tierarten'
    as part of a larger multi-line value (e.g. ``"Tierkategorien\\nAlle Tierarten
    oder"``), or use the standalone label ``"Tierkategorien"`` (the column
    heading from older regulatory tables, meaning *all species categories*).
    Both are treated as equivalent to the clean ``"Alle Tierarten"`` key so
    that historical duplicate records are properly collapsed with their modern
    counterparts.
    """
    if not species:
        return ""
    s_lower = species.strip().lower()
    if "alle tierarten" in s_lower:
        return "Alle Tierarten"
    # "Tierkategorien" alone (possibly with whitespace/newlines) is the
    # historical dataset's catch-all label equivalent to "Alle Tierarten".
    if s_lower in ("tierkategorien", "alle tierkategorien"):
        return "Alle Tierarten"
    return species


def _pick_primary_record(records: List[Additive]) -> Additive:
    """From a list of synonymous *records*, return the most informative one.

    Preference order:

    1. Records that have at least one limit value (``min_value`` or
       ``max_value`` is not ``None``).
    2. Among those (or all records when none have limits), prefer records
       whose ``e_number`` does *not* start with ``"E "`` (modern identifiers
       over historical "E X" notation).
    3. Otherwise return the first record in the list.
    """
    has_limits = [
        r for r in records
        if r.min_value is not None or r.max_value is not None
    ]
    pool = has_limits if has_limits else records
    modern = [
        r for r in pool
        if not (r.e_number or "").strip().upper().startswith("E ")
    ]
    return (modern or pool)[0]


def dedup_synonym_candidates(
    candidates: List[Additive],
    sub_query: str,
) -> List[Additive]:
    """Collapse synonym records that differ only in historical substance-name
    notation so that only the *primary* record for each canonical
    (substance, species) identity is returned.

    The function applies two complementary deduplication passes:

    **Pass 1 – canonical vs. loose match filter**
        A *canonical match* is a record whose
        :func:`normalize_substance_name` equals the normalized query.
        A *loose match* is a record that was found only because the query
        is a substring of the record's substance name (e.g. querying
        "Natriumselenit" hits "Polyoxyethylen-Sorbitan-Natriumselenat" via
        substring).  If any canonical matches exist, loose-match-only
        records are discarded.

    **Pass 2 – synonym grouping within (normalized-substance, species)**
        Records are grouped by ``(normalize_substance_name(substance),
        species)``.  Within each group:

        * *Different raw lowercase substance names* (true alias names, such
          as ``"Selen-Se Natriumselenit*"`` vs. ``"Natriumselenit"``): only
          the single *primary* record is kept.
        * *Same raw lowercase substance name but different E-numbers*:
          if some records have regulatory limits while others do not, only
          the records *with* limits are kept.  This removes orphan reference
          entries that are identical in name but carry no limit data.
          When all records have limits (or none do), all are kept so that
          genuine species/age-range ambiguity is preserved.

    Genuine ambiguity is always preserved:

    * Records with the same raw substance name, different species, and each
      having their own limits remain as separate entries.
    * Records with different normalized substance names are never merged.

    This function is a no-op when *candidates* has zero or one elements.
    """
    if len(candidates) <= 1:
        return candidates

    norm_q = normalize_substance_name(sub_query)

    # ── Pass 1: prefer canonical matches over loose substring matches ─────────
    canonical = [
        r for r in candidates
        if normalize_substance_name(r.substance or "") == norm_q
    ]
    pool = canonical if canonical else candidates

    # ── Pass 2: group by (normalized-substance, normalized-species) and dedup ─
    groups: Dict[Tuple[str, str], List[Additive]] = {}
    for rec in pool:
        key = (
            normalize_substance_name(rec.substance or ""),
            _dedup_species_key(rec.species or ""),
        )
        groups.setdefault(key, []).append(rec)

    result: List[Additive] = []
    for recs_in_group in groups.values():
        if len(recs_in_group) == 1:
            result.append(recs_in_group[0])
            continue

        raw_names = {(rec.substance or "").strip().lower() for rec in recs_in_group}

        if len(raw_names) > 1:
            # Different raw names normalizing to the same key → alias synonyms
            # (e.g. "Selen-Se Natriumselenit*" vs. "Natriumselenit").
            # Keep only the single primary record.
            result.append(_pick_primary_record(recs_in_group))
        else:
            # Same raw lowercase name, different E-numbers.
            # If some records have limits and others do not, discard the
            # limit-free reference entries (historical duplicates).
            with_limits = [
                r for r in recs_in_group
                if r.min_value is not None or r.max_value is not None
            ]
            if with_limits and len(with_limits) < len(recs_in_group):
                # At least one record with limits, at least one without:
                # keep only those with limits.
                result.extend(with_limits)
            else:
                # All have limits or all lack limits → genuine ambiguity,
                # keep all.
                result.extend(recs_in_group)

    return result


# =========================================================
# Loader helpers
# =========================================================

def _to_float(x: Any) -> Optional[float]:
    if x in (None, ""):
        return None
    try:
        return float(str(x).replace(",", "."))
    except Exception:
        return None


def _to_int(x: Any) -> Optional[int]:
    if x in (None, ""):
        return None
    try:
        return int(x)
    except Exception:
        try:
            return int(float(str(x).replace(",", ".")))
        except Exception:
            return None


# =========================================================
# Loaders
# =========================================================

def load_additives(path: str) -> List[Additive]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError as e:
        raise FileNotFoundError(f"Datei nicht gefunden: {path}") from e
    except json.JSONDecodeError as e:
        raise ValueError(f"Fehlerhafte JSON-Datei bei {path}: {e}") from e
    except Exception as e:
        raise Exception(f"Fehler beim Laden von {path}: {e}") from e

    logger.info("Lade Zusatzstoffe aus: %s", path)
    items: List[Additive] = []

    def _as_list(x: Any) -> List:
        if x is None:
            return []
        if isinstance(x, list):
            return x
        return [str(x)]

    for r in raw:
        if "e_number" in r or "substance" in r or "min_value" in r or "max_value" in r:
            items.append(Additive(
                e_number=str(r.get("e_number", "")).strip() or str(r.get("kennnummer", "")).strip(),
                substance=r.get("substance") or r.get("name"),
                chemical=r.get("chemical"),
                category=r.get("category"),
                species=r.get("species", "Alle Tierarten"),
                max_age_months=_to_int(r.get("max_age_months")),
                unit=r.get("unit"),
                min_value=_to_float(r.get("min_value")),
                max_value=_to_float(r.get("max_value")),
                notes=r.get("notes"),
                source_ref=r.get("source_ref"),
                has_combination_rule=bool(r.get("has_combination_rule", False)),
                combination_rule_ids=r.get("combination_rule_ids"),
                feed_type_allowed=r.get("feed_type_allowed"),
                feed_type_primary=r.get("feed_type_primary"),
                status=r.get("status"),
                extra={k: v for k, v in r.items() if k not in {
                    "e_number", "substance", "chemical", "category", "species",
                    "max_age_months", "unit", "min_value", "max_value", "notes",
                    "source_ref", "has_combination_rule", "combination_rule_ids",
                    "feed_type_allowed", "feed_type_primary", "status",
                }}
            ))
        elif "kennnummer" in r:
            min_v = r.get("min_mg_kg")
            max_v = r.get("max_mg_kg")
            einheit = r.get("einheit") or r.get("Maßeinheit") or r.get("masseinheit")
            # Only default to mg/kg when at least one limit is present;
            # records with no limits get unit=None so evaluation can be
            # properly blocked.
            unit = str(einheit).strip() if einheit else (
                "mg/kg" if (min_v is not None or max_v is not None) else None
            )

            species_raw = r.get("tierarten") or r.get("zieltierarten")
            if not species_raw or str(species_raw).strip() in ("", "—", "–", "-"):
                species_clean = "Alle Tierarten"
            elif isinstance(species_raw, list):
                species_clean = ", ".join(map(str, species_raw)).strip() or "Alle Tierarten"
            else:
                s = str(species_raw)
                s = s.replace("Alle Tierar-\nten", "Alle Tierarten")
                s = s.replace("Alle Tier-\narten", "Alle Tierarten")
                s = s.replace("Alle\nTierarten", "Alle Tierarten")
                species_clean = s.strip() or "Alle Tierarten"

            alter_tage = _to_float(r.get("hoechstalter_tage") or r.get("hoechstalter"))
            max_age = max(1, round(alter_tage / 30.44)) if alter_tage is not None else None

            items.append(Additive(
                e_number=str(r.get("kennnummer") or "").strip(),
                substance=(r.get("name") or None),
                chemical=None,
                category=None,
                species=species_clean,
                max_age_months=max_age,
                unit=unit,
                min_value=_to_float(min_v),
                max_value=_to_float(max_v),
                notes=r.get("notizen"),
                source_ref=(
                    f'{r.get("source_file", "")}:S.{r.get("source_page")}'
                    if r.get("source_file") else None
                ),
                has_combination_rule=False,
                combination_rule_ids=None,
                feed_type_allowed=None,
                feed_type_primary=None,
                status=r.get("rechtsgrundlage") or r.get("geltung_bis"),
                extra={k: v for k, v in r.items() if k not in {
                    "kennnummer", "name", "tierarten", "zieltierarten",
                    "hoechstalter", "hoechstalter_tage", "min_mg_kg", "max_mg_kg",
                    "einheit", "Maßeinheit", "masseinheit", "notizen",
                    "geltung_bis", "rechtsgrundlage", "source_file", "source_page",
                }}
            ))
        else:
            items.append(Additive(
                e_number=str(r.get("kennnummer") or r.get("e_number") or "").strip(),
                substance=r.get("name") or r.get("substance"),
                chemical=r.get("chemical"),
                category=r.get("category"),
                species=str(r.get("species") or r.get("tierarten") or "Alle Tierarten"),
                max_age_months=_to_int(r.get("max_age_months") or r.get("hoechstalter")),
                unit=r.get("unit") or r.get("einheit"),
                min_value=_to_float(r.get("min_value") or r.get("min_mg_kg")),
                max_value=_to_float(r.get("max_value") or r.get("max_mg_kg")),
                notes=r.get("notes") or r.get("notizen"),
                source_ref=r.get("source_ref"),
                has_combination_rule=bool(r.get("has_combination_rule", False)),
                combination_rule_ids=r.get("combination_rule_ids"),
                feed_type_allowed=r.get("feed_type_allowed"),
                feed_type_primary=r.get("feed_type_primary"),
                status=r.get("status") or r.get("rechtsgrundlage"),
                extra={k: v for k, v in r.items()}
            ))

    logger.info("Geladene Datensätze: %d", len(items))
    return items


def load_combo_rules(path: str) -> List[ComboRule]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return []

    rules = []
    for r in raw:
        rules.append(ComboRule(
            rule_id=str(r.get("rule_id")),
            description=r.get("description", ""),
            affected_e_numbers=r.get("affected_e_numbers"),
            affected_categories=r.get("affected_categories"),
            max_total_value=_to_float(r.get("max_total_value") or 0.0),
            unit=r.get("unit", "mg/kg"),
            species=r.get("species", ["Alle Tierarten"]),
            source_refs=r.get("source_refs"),
            confidence=r.get("confidence")
        ))
    return rules


# =========================================================
# Index & species helpers
# =========================================================

CATEGORY_SPECIES_KEYWORDS: Dict[str, Dict[str, str]] = {
    "Schweine": {
        "schwein": "Schweine", "ferkel": "Ferkel", "sau": "Sauen",
    },
    "Geflügel": {
        "masthuh": "Masthühner", "legehuh": "Legehennen", "junghen": "Junghennen",
        "lege": "Legehennen", "henne": "Hennen", "huhn": "Hühner",
        "truthahn": "Truthühner", "truthühn": "Truthühner",
        "ente": "Enten", "gans": "Gänse", "ziervog": "Ziervögel",
        "geflüg": "Geflügel", "vogel": "Vögel",
    },
    "Rinder": {
        "rind": "Rinder", "kalb": "Kälber", "kuh": "Kühe",
        "bulle": "Bullen", "mastrin": "Mastrinder", "milchkuh": "Milchkühe",
        "wiederkä": "Wiederkäuer",
    },
    "Schafe/Ziegen": {
        "schaf": "Schafe", "lamm": "Lämmer", "ziege": "Ziegen",
        "bock": "Böcke",
    },
    "Heimtiere": {
        "hund": "Hunde", "katze": "Katzen", "kaninchen": "Kaninchen",
        "pferd": "Pferde", "pony": "Ponys", "esel": "Esel",
    },
    "Fische/Krebstiere": {
        "fisch": "Fische", "krebs": "Krebstiere", "forelle": "Forellen",
        "lachs": "Lachs", "garnele": "Garnelen",
    },
    "Sonstige": {
        "strauß": "Strauße", "kaninchen": "Kaninchen",
        "pferd": "Pferde", "hase": "Hasen", "zier": "Ziervögel",
    },
}

_ALL_SPECIES_KEYWORDS: Dict[str, str] = {}
for _kws in CATEGORY_SPECIES_KEYWORDS.values():
    _ALL_SPECIES_KEYWORDS.update(_kws)


def extract_individual_species(
    tierarten_text: str, category: Optional[str] = None
) -> set:
    if not tierarten_text:
        return set()

    text = str(tierarten_text).lower()
    text = text.replace("\n", " ").replace("\r", " ").replace(";", " ")
    text = text.replace("-", " ").replace("  ", " ").strip()

    if category and category in CATEGORY_SPECIES_KEYWORDS:
        keywords = CATEGORY_SPECIES_KEYWORDS[category]
    else:
        keywords = _ALL_SPECIES_KEYWORDS

    species = set()
    for keyword, species_name in keywords.items():
        if keyword in text:
            species.add(species_name)
    return species


def build_indexes(additives: List[Additive]) -> Dict[str, Any]:
    species_map: Dict[str, Dict[str, List[Additive]]] = {}
    e_to_category: Dict[str, set] = {}
    all_species, ages = set(), set()

    for a in additives:
        sp = a.species or "Alle Tierarten"
        all_species.add(sp)
        species_map.setdefault(sp, {}).setdefault(a.e_number.upper(), []).append(a)
        if a.category:
            e_to_category.setdefault(a.e_number.upper(), set()).add(a.category)
        if a.max_age_months is not None:
            ages.add(a.max_age_months)

    e_to_all_substances: Dict[str, set] = {}
    sub_to_all_e_numbers: Dict[str, set] = {}
    norm_sub_to_e_numbers: Dict[str, set] = {}
    for a in additives:
        e = (a.e_number or "").upper()
        sub = (a.substance or "").strip()
        norm_sub = normalize_substance_name(sub)
        if e:
            e_to_all_substances.setdefault(e, set())
            if sub:
                e_to_all_substances[e].add(sub)
        if sub:
            sub_to_all_e_numbers.setdefault(sub.lower(), set())
            if e:
                sub_to_all_e_numbers[sub.lower()].add(e)
        if norm_sub and e:
            norm_sub_to_e_numbers.setdefault(norm_sub, set()).add(e)

    keyword_to_species_keys: Dict[str, set] = {}
    for a in additives:
        sp = a.species or "Alle Tierarten"
        for kw in extract_individual_species(sp):
            keyword_to_species_keys.setdefault(kw, set()).add(sp)

    return {
        "species_map": species_map,
        "e_to_category": e_to_category,
        "all_species": sorted(all_species | {"Alle Tierarten"}),
        "all_e_numbers": sorted({a.e_number.upper() for a in additives if a.e_number}),
        "all_substances": sorted({(a.substance or "").strip() for a in additives if a.substance}),
        "age_options": sorted(ages),
        "all_units": sorted({a.unit for a in additives if a.unit}),
        "e_to_all_substances": {k: sorted(v) for k, v in e_to_all_substances.items()},
        "sub_to_all_e_numbers": {k: sorted(v) for k, v in sub_to_all_e_numbers.items()},
        "norm_sub_to_e_numbers": {k: sorted(v) for k, v in norm_sub_to_e_numbers.items()},
        "keyword_to_species_keys": {k: sorted(v) for k, v in keyword_to_species_keys.items()},
    }


# =========================================================
# Record matching
# =========================================================

def match_additive_records(
    idx: Dict[str, Any],
    e_number: str,
    species: str,
    age_months: int,
    substance_query: str = "",
    feed_type: Optional[str] = None,
    tierart_kategorie: Optional[str] = None,
    only_artspezifisch: bool = False,
    max_hoechstalter_tage: Optional[float] = None,
) -> List[Additive]:
    e_norm = (e_number or "").strip().upper()
    sub_q = (substance_query or "").strip().lower()
    species_map = idx["species_map"]
    candidates: List[Additive] = []

    def valid(rec: Additive) -> bool:
        if rec.max_age_months is not None and age_months > rec.max_age_months:
            return False
        if sub_q and sub_q not in (rec.substance or "").lower():
            return False
        if feed_type and rec.feed_type_allowed and feed_type not in rec.feed_type_allowed:
            return False
        if tierart_kategorie and tierart_kategorie not in ("Alle Kategorien", "Alle Tierarten"):
            rec_cat = rec.extra.get("tierart_kategorie") or "Alle Tierarten"
            if rec_cat != tierart_kategorie and rec_cat != "Alle Tierarten":
                return False
        if only_artspezifisch and not rec.extra.get("tierart_spezifisch", False):
            return False
        if max_hoechstalter_tage is not None:
            hoechstalter = rec.extra.get("hoechstalter_tage")
            if hoechstalter is None or hoechstalter > max_hoechstalter_tage:
                return False
        return True

    def resolve_species_keys(selected: str) -> List[str]:
        """Return all species_map keys that match *selected*.

        'Alle Tierarten' always matches every species, so it is always
        included in the returned key list regardless of what the user
        selected.  Specific species are resolved both by exact key and
        through the keyword index.
        """
        if not selected or selected == "Alle Tierarten":
            return list(species_map.keys())
        keys: set = set()
        if selected in species_map:
            keys.add(selected)
        for raw_sp in idx.get("keyword_to_species_keys", {}).get(selected, []):
            keys.add(raw_sp)
        # Datasets tagged 'Alle Tierarten' must always match any species
        keys.add("Alle Tierarten")
        return list(keys)

    seen_ids: set = set()

    def add_unique(rec: Additive) -> None:
        rid = id(rec)
        if rid not in seen_ids:
            seen_ids.add(rid)
            candidates.append(rec)

    if e_norm:
        logger.debug(
            "match_additive_records: e=%s species=%s age=%s",
            e_norm, species, age_months,
        )
        for sp in resolve_species_keys(species):
            for rec in species_map.get(sp, {}).get(e_norm, []):
                if valid(rec):
                    add_unique(rec)
        logger.debug("  -> %d Treffer gefunden", len(candidates))
        return candidates

    if sub_q:
        for sp in resolve_species_keys(species):
            for recs in species_map.get(sp, {}).values():
                for rec in recs:
                    if valid(rec):
                        add_unique(rec)
        # Collapse synonym / alias records so that historical substance-name
        # variants (e.g. "Selen-Se Natriumselenit*" for modern "Natriumselenit")
        # do not produce false ambiguity.
        return dedup_synonym_candidates(candidates, sub_q)

    return []


def derive_e_number_for_substance(
    idx: Dict[str, Any],
    substance: str,
    species: str = "Alle Tierarten",
    age_months: int = 0,
    tierart_kategorie: Optional[str] = None,
) -> Optional[str]:
    """Return the unique E-number for *substance*, or ``None``.

    The function first resolves the substance via
    :func:`match_additive_records`.  If any records are found it
    collects the set of distinct E-numbers from those records.  As a
    fallback (e.g. when all records are filtered out by species / age
    constraints) it consults the ``sub_to_all_e_numbers`` index which
    is species-agnostic.  As a second fallback the normalized-substance
    index (``norm_sub_to_e_numbers``) is consulted so that queries using
    the canonical name of a historical alias can still be resolved.

    Returns the single E-number string when it can be derived
    unambiguously, ``None`` when the substance has no E-number or when
    it maps to more than one distinct E-number.
    """
    recs = match_additive_records(
        idx, "",
        species=species,
        age_months=age_months,
        substance_query=substance,
        tierart_kategorie=tierart_kategorie,
    )
    if recs:
        e_set = {r.e_number.upper() for r in recs if r.e_number}
    else:
        e_set = set(idx["sub_to_all_e_numbers"].get(substance.lower(), []))
        # Second fallback: look up via normalized substance name so that a
        # query like "Natriumselenit" can still resolve even when the
        # sub_to_all_e_numbers index only contains the historical alias.
        if not e_set:
            norm_key = normalize_substance_name(substance)
            e_set = set(idx.get("norm_sub_to_e_numbers", {}).get(norm_key, []))
    return next(iter(e_set)) if len(e_set) == 1 else None


# =========================================================
# Evaluation
# =========================================================

def format_range(rec: Additive) -> str:
    parts = []
    if rec.min_value is not None:
        parts.append(f"≥ {rec.min_value:g}")
    if rec.max_value is not None:
        parts.append(f"≤ {rec.max_value:g}")
    return " und ".join(parts) if parts else "kein Grenzwert hinterlegt"


def evaluate_single_value(
    value: float, rec: Additive
) -> Tuple[Optional[bool], List[str]]:
    """Evaluate *value* against the limits stored in *rec*.

    Returns a tuple ``(ok, messages)`` where *ok* is:

    * ``True``  – value is within all defined limits  (COMPLIANT)
    * ``False`` – value violates at least one limit   (NON-COMPLIANT)
    * ``None``  – evaluation not possible             (no limits or missing unit)

    A compliance result of ``True`` is **never** returned when the
    dataset contains no regulatory limits, or when the unit field is
    absent while limits are present.
    """
    msgs: List[str] = []
    has_min = rec.min_value is not None
    has_max = rec.max_value is not None

    logger.info(
        "Bewertung gestartet: e_number=%s value=%g min=%s max=%s unit=%s",
        rec.e_number, value, rec.min_value, rec.max_value, rec.unit,
    )

    # ── Guard 1: no limits at all ──────────────────────────────────────────
    if not has_min and not has_max:
        logger.warning(
            "Kein Grenzwert im Datensatz für %s – Bewertung nicht möglich.",
            rec.e_number,
        )
        msgs.append(
            "⚠ Keine Grenzwerte im Datensatz hinterlegt – "
            "Bewertung nicht möglich."
        )
        if rec.notes:
            msgs.append(f"Hinweise: {rec.notes}")
        if rec.source_ref:
            msgs.append(f"Quelle: {rec.source_ref}")
        if rec.status:
            msgs.append(f"Status: {rec.status}")
        return None, msgs

    # ── Guard 2: limits present but unit missing ───────────────────────────
    if rec.unit is None:
        logger.warning(
            "Einheit fehlt im Datensatz für %s – Bewertung abgebrochen.",
            rec.e_number,
        )
        msgs.append(
            "⚠ Einheit im Datensatz fehlt – Bewertung abgebrochen. "
            "Bitte Quelle/Einheit prüfen."
        )
        if rec.notes:
            msgs.append(f"Hinweise: {rec.notes}")
        if rec.source_ref:
            msgs.append(f"Quelle: {rec.source_ref}")
        if rec.status:
            msgs.append(f"Status: {rec.status}")
        return None, msgs

    # ── Actual limit comparison ────────────────────────────────────────────
    unit = rec.unit
    ok = True

    if has_min and value < rec.min_value:
        ok = False
        msgs.append(
            f"Unterschreitung: {value:g} {unit} < {rec.min_value:g} {unit}"
        )
    if has_max and value > rec.max_value:
        ok = False
        msgs.append(
            f"Überschreitung: {value:g} {unit} > {rec.max_value:g} {unit}"
        )

    if ok:
        logger.info(
            "Bewertungsergebnis: KONFORM – e_number=%s value=%g %s",
            rec.e_number, value, unit,
        )
        msgs.append("Ergebnis: KONFORM mit den hinterlegten Grenzwerten.")
    else:
        logger.info(
            "Bewertungsergebnis: NICHT KONFORM – e_number=%s value=%g %s",
            rec.e_number, value, unit,
        )

    # Always show the stored limits so the user can contextualise the result.
    limit_parts = []
    if has_min:
        limit_parts.append(f"Mindestwert: {rec.min_value:g} {unit}")
    if has_max:
        limit_parts.append(f"Höchstwert:  {rec.max_value:g} {unit}")
    msgs.append("Hinterlegte Grenzwerte: " + " | ".join(limit_parts))

    if rec.notes:
        msgs.append(f"Hinweise: {rec.notes}")
    if rec.source_ref:
        msgs.append(f"Quelle: {rec.source_ref}")
    if rec.status:
        msgs.append(f"Status: {rec.status}")

    return ok, msgs


# =========================================================
# Combination rules
# =========================================================

def find_applicable_combo_rules(
    rules: List[ComboRule],
    e_numbers: List[str],
    species: str,
    e_to_category: Dict[str, set],
) -> List[ComboRule]:
    e_set = {e.upper().strip() for e in e_numbers if e.strip()}
    applicable = []
    for r in rules:
        if "Alle Tierarten" not in r.species and species not in r.species:
            continue
        if r.affected_e_numbers and e_set & {x.upper() for x in r.affected_e_numbers}:
            applicable.append(r)
            continue
        if r.affected_categories:
            for e in e_set:
                if e_to_category.get(e, set()) & set(r.affected_categories):
                    applicable.append(r)
                    break
    return applicable


# =========================================================
# Database validation
# =========================================================

def validate_database(
    additives: List[Additive],
    report_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate all *additives* for structural and data-quality problems.

    Returns a dict with keys ``total_records``, ``issues`` (critical
    problems that prevent correct evaluation) and ``warnings``
    (non-critical inconsistencies).  If *report_path* is given the
    results are also written to that file.
    """
    issues: List[str] = []
    warnings: List[str] = []

    # Track (e_number_upper, species) pairs for duplicate detection
    seen_keys: Dict[Tuple[str, str], int] = {}

    for i, a in enumerate(additives):
        label = f"Datensatz {i} (kennnummer={a.e_number!r}, species={a.species!r})"

        # Missing e_number
        if not (a.e_number or "").strip():
            issues.append(f"{label}: Keine Kennnummer (e_number fehlt).")

        # No limits at all
        has_limits = a.min_value is not None or a.max_value is not None
        if not has_limits:
            warnings.append(
                f"{label}: Kein Grenzwert hinterlegt "
                f"(min_value=None, max_value=None)."
            )

        # Limits present but unit missing
        if has_limits and a.unit is None:
            issues.append(
                f"{label}: Grenzwert vorhanden, aber Einheit fehlt "
                f"(min={a.min_value}, max={a.max_value})."
            )

        # Duplicate (e_number, species) combination
        key = (a.e_number.upper(), a.species)
        if key in seen_keys:
            warnings.append(
                f"{label}: Doppelter Eintrag – "
                f"Kennnummer {a.e_number!r} / Tierart {a.species!r} "
                f"bereits als Datensatz {seen_keys[key]} vorhanden."
            )
        else:
            seen_keys[key] = i

        # Non-standard species value (not cleaned to "Alle Tierarten")
        sp_lower = (a.species or "").lower()
        if "alle tierarten" not in sp_lower and "\n" in (a.species or ""):
            warnings.append(
                f"{label}: Tierartfeld enthält Zeilenumbrüche – "
                f"möglicherweise nicht korrekt normalisiert."
            )

    report: Dict[str, Any] = {
        "total_records": len(additives),
        "issues": issues,
        "warnings": warnings,
    }

    logger.info(
        "Datenbankvalidierung: %d Datensätze, %d Probleme, %d Warnungen.",
        len(additives), len(issues), len(warnings),
    )

    if report_path:
        try:
            os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
            with open(report_path, "w", encoding="utf-8") as fout:
                fout.write("LAVES Datenbankvalidierungsbericht\n")
                fout.write("=" * 50 + "\n")
                fout.write(f"Gesamte Datensätze : {len(additives)}\n")
                fout.write(f"Kritische Probleme : {len(issues)}\n")
                fout.write(f"Warnungen          : {len(warnings)}\n\n")
                if issues:
                    fout.write("=== KRITISCHE PROBLEME ===\n")
                    for issue in issues:
                        fout.write(f"  {issue}\n")
                    fout.write("\n")
                if warnings:
                    fout.write("=== WARNUNGEN ===\n")
                    for warning in warnings:
                        fout.write(f"  {warning}\n")
                    fout.write("\n")
                if not issues and not warnings:
                    fout.write("Keine Probleme gefunden.\n")
            logger.info("Validierungsbericht geschrieben: %s", report_path)
        except Exception as exc:
            logger.error("Fehler beim Schreiben des Validierungsberichts: %s", exc)

    return report
