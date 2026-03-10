#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import sys
import os
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple

from PySide6.QtCore import Qt, QDateTime, QProcess
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QCompleter, QFormLayout, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPushButton, QVBoxLayout, QWidget, QTabWidget,
    QTableWidget, QTableWidgetItem, QTextEdit, QFileDialog
)
from PySide6.QtGui import QPalette, QColor, QFont
from PySide6.QtWidgets import QStyleFactory

# =========================================================
# Datenmodell
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
# Loader
# =========================================================

def _to_float(x):
    if x in (None, ""):
        return None
    try:
        return float(str(x).replace(",", "."))
    except Exception:
        return None

def _to_int(x):
    if x in (None, ""):
        return None
    try:
        return int(x)
    except Exception:
        try:
            return int(float(str(x).replace(",", ".")))
        except Exception:
            return None

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

    items: List[Additive] = []

    def _as_list(x):
        if x is None:
            return []
        if isinstance(x, list):
            return x
        return [str(x)]

    for r in raw:
        if "e_number" in r or "substance" in r or "min_value" in r or "max_value" in r:
            items.append(Additive(
                e_number=str(r.get("e_number", "")).strip() or str(r.get("kennnummer","")).strip(),
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
                extra={k:v for k,v in r.items() if k not in {"e_number","substance","chemical","category","species","max_age_months","unit","min_value","max_value","notes","source_ref","has_combination_rule","combination_rule_ids","feed_type_allowed","feed_type_primary","status"}}
            ))
        elif "kennnummer" in r:
            min_v = r.get("min_mg_kg")
            max_v = r.get("max_mg_kg")
            einheit = r.get("einheit") or r.get("Maßeinheit") or r.get("masseinheit")
            unit = str(einheit).strip() if einheit else ("mg/kg" if (min_v is not None or max_v is not None) else None)

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
                source_ref=(f'{r.get("source_file","")}:S.{r.get("source_page")}' if r.get("source_file") else None),
                has_combination_rule=False,
                combination_rule_ids=None,
                feed_type_allowed=None,
                feed_type_primary=None,
                status=r.get("rechtsgrundlage") or r.get("geltung_bis"),
                extra={k:v for k,v in r.items() if k not in {"kennnummer","name","tierarten","zieltierarten","hoechstalter","hoechstalter_tage","min_mg_kg","max_mg_kg","einheit","Maßeinheit","masseinheit","notizen","geltung_bis","rechtsgrundlage","source_file","source_page"}}
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
                extra={k:v for k,v in r.items()}
            ))
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
# Indexe & Business-Logik
# =========================================================

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
    for a in additives:
        e = (a.e_number or "").upper()
        sub = (a.substance or "").strip()
        if e:
            e_to_all_substances.setdefault(e, set())
            if sub:
                e_to_all_substances[e].add(sub)
        if sub:
            sub_to_all_e_numbers.setdefault(sub.lower(), set())
            if e:
                sub_to_all_e_numbers[sub.lower()].add(e)

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
        "keyword_to_species_keys": {k: sorted(v) for k, v in keyword_to_species_keys.items()},
    }

CATEGORY_SPECIES_KEYWORDS: Dict[str, Dict[str, str]] = {
    "Schweine": {
        'schwein': 'Schweine', 'ferkel': 'Ferkel', 'sau': 'Sauen',
    },
    "Geflügel": {
        'masthuh': 'Masthühner', 'legehuh': 'Legehennen', 'junghen': 'Junghennen',
        'lege': 'Legehennen', 'henne': 'Hennen', 'huhn': 'Hühner',
        'truthahn': 'Truthühner', 'truthühn': 'Truthühner',
        'ente': 'Enten', 'gans': 'Gänse', 'ziervog': 'Ziervögel',
        'geflüg': 'Geflügel', 'vogel': 'Vögel',
    },
    "Rinder": {
        'rind': 'Rinder', 'kalb': 'Kälber', 'kuh': 'Kühe',
        'bulle': 'Bullen', 'mastrin': 'Mastrinder', 'milchkuh': 'Milchkühe',
        'wiederkä': 'Wiederkäuer',
    },
    "Schafe/Ziegen": {
        'schaf': 'Schafe', 'lamm': 'Lämmer', 'ziege': 'Ziegen',
        'bock': 'Böcke',
    },
    "Heimtiere": {
        'hund': 'Hunde', 'katze': 'Katzen', 'kaninchen': 'Kaninchen',
        'pferd': 'Pferde', 'pony': 'Ponys', 'esel': 'Esel',
    },
    "Fische/Krebstiere": {
        'fisch': 'Fische', 'krebs': 'Krebstiere', 'forelle': 'Forellen',
        'lachs': 'Lachs', 'garnele': 'Garnelen',
    },
    "Sonstige": {
        'strauß': 'Strauße', 'kaninchen': 'Kaninchen',
        'pferd': 'Pferde', 'hase': 'Hasen', 'zier': 'Ziervögel',
    },
}

_ALL_SPECIES_KEYWORDS: Dict[str, str] = {}
for _kws in CATEGORY_SPECIES_KEYWORDS.values():
    _ALL_SPECIES_KEYWORDS.update(_kws)

def extract_individual_species(tierarten_text: str, category: Optional[str] = None) -> set:
    if not tierarten_text:
        return set()

    text = str(tierarten_text).lower()
    text = text.replace('\n', ' ').replace('\r', ' ').replace(';', ' ')
    text = text.replace('-', ' ').replace('  ', ' ').strip()

    if category and category in CATEGORY_SPECIES_KEYWORDS:
        keywords = CATEGORY_SPECIES_KEYWORDS[category]
    else:
        keywords = _ALL_SPECIES_KEYWORDS

    species = set()
    for keyword, species_name in keywords.items():
        if keyword in text:
            species.add(species_name)

    return species

def match_additive_records(idx: Dict[str, Any], e_number: str, species: str,
                           age_months: int, substance_query: str = "",
                           feed_type: Optional[str] = None,
                           tierart_kategorie: Optional[str] = None,
                           only_artspezifisch: bool = False,
                           max_hoechstalter_tage: Optional[float] = None) -> List[Additive]:
    e_norm = (e_number or "").strip().upper()
    sub_q = (substance_query or "").strip().lower()
    species_map = idx["species_map"]
    candidates: List[Additive] = []

    def valid(rec: Additive):
        if rec.max_age_months is not None and age_months > rec.max_age_months:
            return False
        if sub_q and sub_q not in (rec.substance or "").lower():
            return False
        if feed_type and rec.feed_type_allowed and feed_type not in rec.feed_type_allowed:
            return False
        if tierart_kategorie and tierart_kategorie != "Alle Kategorien":
            if rec.extra.get("tierart_kategorie") != tierart_kategorie:
                return False
        if only_artspezifisch and not rec.extra.get("tierart_spezifisch", False):
            return False
        if max_hoechstalter_tage is not None:
            hoechstalter = rec.extra.get("hoechstalter_tage")
            if hoechstalter is None or hoechstalter > max_hoechstalter_tage:
                return False
        return True

    def resolve_species_keys(selected: str) -> List[str]:
        if not selected or selected == "Alle Tierarten":
            return list(species_map.keys())
        keys = set()
        if selected in species_map:
            keys.add(selected)
        for raw_sp in idx.get("keyword_to_species_keys", {}).get(selected, []):
            keys.add(raw_sp)
        keys.add("Alle Tierarten")
        return list(keys)

    seen_ids: set = set()

    def add_unique(rec: Additive):
        rid = id(rec)
        if rid not in seen_ids:
            seen_ids.add(rid)
            candidates.append(rec)

    if e_norm:
        for sp in resolve_species_keys(species):
            for rec in species_map.get(sp, {}).get(e_norm, []):
                if valid(rec):
                    add_unique(rec)
        return candidates

    if sub_q:
        for sp in resolve_species_keys(species):
            for recs in species_map.get(sp, {}).values():
                for rec in recs:
                    if valid(rec):
                        add_unique(rec)
        return candidates

    return []

def format_range(rec: Additive) -> str:
    parts = []
    if rec.min_value is not None:
        parts.append(f"≥ {rec.min_value:g}")
    if rec.max_value is not None:
        parts.append(f"≤ {rec.max_value:g}")
    return " und ".join(parts) if parts else "kein Grenzwert hinterlegt"

def evaluate_single_value(value: float, rec: Additive) -> Tuple[bool, List[str]]:
    msgs, ok = [], True
    unit = rec.unit or "—"
    if rec.min_value is not None and value < rec.min_value:
        ok = False
        msgs.append(f"Unterschreitung: {value:g} {unit} < {rec.min_value:g} {unit}")
    if rec.max_value is not None and value > rec.max_value:
        ok = False
        msgs.append(f"Überschreitung: {value:g} {unit} > {rec.max_value:g} {unit}")
    if ok:
        msgs.append("Ergebnis: KONFORM mit den hinterlegten Grenzwerten.")
    if rec.notes:
        msgs.append(f"Hinweise: {rec.notes}")
    if rec.source_ref:
        msgs.append(f"Quelle: {rec.source_ref}")
    if rec.unit is None:
        msgs.append("⚠ Einheit im Datensatz fehlt – bitte Quelle/Einheit prüfen.")
    if rec.status:
        msgs.append(f"Status: {rec.status}")
    return ok, msgs

# =========================================================
# UI Hilfsfunktionen
# =========================================================

def make_editable_combobox(items: List[str]) -> QComboBox:
    cb = QComboBox()
    cb.setEditable(True)
    cb.addItems(items)
    completer = QCompleter(items)
    completer.setCaseSensitivity(Qt.CaseInsensitive)
    completer.setFilterMode(Qt.MatchContains)
    cb.setCompleter(completer)
    return cb

def refill_editable_combobox(cb: QComboBox, items: List[str]):
    text = cb.currentText()
    cb.blockSignals(True)
    cb.clear()
    cb.addItems(items)
    comp = QCompleter(items)
    comp.setCaseSensitivity(Qt.CaseInsensitive)
    comp.setFilterMode(Qt.MatchContains)
    cb.setCompleter(comp)
    cb.setEditText(text)
    cb.blockSignals(False)

def exact_match_in_list(text: str, items: List[str]) -> Optional[str]:
    t = (text or "").strip()
    return next((x for x in items if x.casefold() == t.casefold()), None)

# =========================================================
# Einzelprüfung
# =========================================================

class EinzelpruefungWidget(QWidget):
    def __init__(self, additives: List[Additive], idx: Dict[str, Any]):
        super().__init__()
        self.additives, self.idx = additives, idx
        self._syncing = False

        self.cbo_species = QComboBox()
        all_species = {"Alle Tierarten"}
        for a in additives:
            all_species.update(extract_individual_species(a.species))
        self.cbo_species.addItems(sorted(all_species))
        self.cbo_species.setCurrentText("Alle Tierarten")

        self.cbo_age = QComboBox()
        self.age_map = {"Kein Altersfilter": 0}
        for m in idx["age_options"]:
            self.age_map[f"≤ {m} Monate"] = int(m)
        self.cbo_age.addItems(self.age_map.keys())
        self.cbo_age.setCurrentText("Kein Altersfilter")

        self.cbo_feed = QComboBox()
        feed_types = sorted({ft for a in additives for ft in (a.feed_type_allowed or [])} | {"(kein Filter)"})
        self.cbo_feed.addItems(feed_types)
        self.cbo_feed.setCurrentText("(kein Filter)")

        self.cbo_tierart_cat = QComboBox()
        tierart_categories = sorted({
            a.extra.get("tierart_kategorie")
            for a in additives
            if a.extra.get("tierart_kategorie")
        } | {"Alle Kategorien"})
        self.cbo_tierart_cat.addItems(tierart_categories)
        self.cbo_tierart_cat.setCurrentText("Alle Kategorien")

        self.chk_artspezifisch = QCheckBox("Nur artspezifische")
        self.chk_artspezifisch.setChecked(False)

        self.chk_age_limit = QCheckBox("Mit Altersgrenze")
        self.chk_age_limit.setChecked(False)
        self.txt_max_age = QLineEdit()
        self.txt_max_age.setPlaceholderText("Max. Tage (z.B. 42)")
        self.txt_max_age.setEnabled(False)
        self.chk_age_limit.stateChanged.connect(
            lambda: self.txt_max_age.setEnabled(self.chk_age_limit.isChecked())
        )

        self.cbo_e = make_editable_combobox(idx["all_e_numbers"])
        self.cbo_sub = make_editable_combobox(idx["all_substances"])

        self.cbo_e.setCurrentIndex(-1)
        self.cbo_e.setEditText("")
        self.cbo_sub.setCurrentIndex(-1)
        self.cbo_sub.setEditText("")

        self.txt_value = QLineEdit()
        self.txt_value.setPlaceholderText("Laborwert (Zahl)")
        self.cbo_unit = QComboBox()
        self.cbo_unit.addItems(idx.get("all_units", ["mg/kg"]))

        self.btn_check = QPushButton("Prüfen")
        self.btn_check.clicked.connect(self.on_check)
        self.out = QTextEdit()
        self.out.setReadOnly(True)
        self.out.setMinimumHeight(180)

        form = QFormLayout()
        form.addRow("Tierart-Kat.:", self.cbo_tierart_cat)
        form.addRow("Tierart:", self.cbo_species)
        form.addRow("", self.chk_artspezifisch)
        form.addRow("Alter:", self.cbo_age)
        form.addRow("", self.chk_age_limit)
        form.addRow("Max. Alter (Tage):", self.txt_max_age)
        form.addRow("Futtermittel-Typ:", self.cbo_feed)
        form.addRow("E-Nummer:", self.cbo_e)
        form.addRow("Stoff:", self.cbo_sub)
        hval = QHBoxLayout()
        hval.addWidget(self.txt_value)
        hval.addWidget(self.cbo_unit)
        form.addRow("Laborergebnis:", hval)

        v = QVBoxLayout()
        v.addLayout(form)
        v.addWidget(self.btn_check, alignment=Qt.AlignRight)
        v.addWidget(QLabel("Auswertung:"))
        v.addWidget(self.out)
        self.setLayout(v)

        self.cbo_tierart_cat.currentTextChanged.connect(self.on_tierart_cat_changed)
        self.cbo_species.currentTextChanged.connect(self.update_context)
        self.cbo_age.currentTextChanged.connect(self.update_context)
        self.cbo_feed.currentTextChanged.connect(self.update_context)
        self.cbo_tierart_cat.currentTextChanged.connect(self.update_context)
        self.chk_artspezifisch.stateChanged.connect(self.update_context)
        self.chk_age_limit.stateChanged.connect(self.update_context)
        self.txt_max_age.textChanged.connect(self.update_context)
        self.cbo_e.currentTextChanged.connect(self.on_e_changed)
        self.cbo_sub.currentTextChanged.connect(self.on_s_changed)

        self.update_context()

    def current_age(self) -> int:
        return self.age_map.get(self.cbo_age.currentText(), 0)

    def on_tierart_cat_changed(self):
        category = self.cbo_tierart_cat.currentText()
        if category == "Alle Kategorien":
            available_species = {"Alle Tierarten"}
            for additive in self.additives:
                available_species.update(extract_individual_species(additive.species))
            available_species = sorted(available_species)
        else:
            available_species = {"Alle Tierarten"}
            for additive in self.additives:
                if additive.extra.get("tierart_kategorie") == category:
                    available_species.update(
                        extract_individual_species(additive.species, category=category)
                    )
            available_species = sorted(available_species)

        self.cbo_species.blockSignals(True)
        current_text = self.cbo_species.currentText()
        self.cbo_species.clear()
        self.cbo_species.addItems(available_species)
        if current_text in available_species:
            self.cbo_species.setCurrentText(current_text)
        elif available_species:
            self.cbo_species.setCurrentIndex(0)
        self.cbo_species.blockSignals(False)

    def _set_out(self, text: str, ok: Optional[bool] = None):
        if ok is True:
            color = "#2e7d32"   # green  – value within limits
        elif ok is False:
            color = "#c62828"   # red    – value out of limits
        else:
            color = "#f9a825"   # yellow – warning (no data, ambiguous, …)
        lines = text.splitlines()
        if lines:
            lines[0] = f'<b><span style="color:{color}">{lines[0]}</span></b>'
        self.out.setHtml("<br>".join(lines))

    def update_context(self):
        if self._syncing:
            return
        self._syncing = True
        try:
            e = self.cbo_e.currentText().strip().upper()
            subs = self.filtered_substances(e)
            refill_editable_combobox(self.cbo_sub, subs)
        finally:
            self._syncing = False

    def filtered_substances(self, e: str) -> List[str]:
        sp = self.cbo_species.currentText()
        age = self.current_age()
        feed = None if self.cbo_feed.currentText() == "(kein Filter)" else self.cbo_feed.currentText()
        if not e:
            return self.idx["all_substances"]

        tierart_cat = self.cbo_tierart_cat.currentText()
        only_artspez = self.chk_artspezifisch.isChecked()
        max_age_days = None
        if self.chk_age_limit.isChecked():
            try:
                max_age_days = float(self.txt_max_age.text())
            except ValueError:
                pass

        recs = match_additive_records(
            self.idx, e, sp, age, "", feed,
            tierart_kategorie=tierart_cat,
            only_artspezifisch=only_artspez,
            max_hoechstalter_tage=max_age_days
        )
        if recs:
            return sorted({(r.substance or "").strip() for r in recs if r.substance})
        return self.idx["e_to_all_substances"].get(e, self.idx["all_substances"])

    def on_e_changed(self, _):
        if self._syncing:
            return
        self._syncing = True
        try:
            e_exact = exact_match_in_list(self.cbo_e.currentText(), self.idx["all_e_numbers"])
            if not e_exact:
                return

            sp = self.cbo_species.currentText()
            age = self.current_age()
            feed = None if self.cbo_feed.currentText() == "(kein Filter)" else self.cbo_feed.currentText()

            tierart_cat = self.cbo_tierart_cat.currentText()
            only_artspez = self.chk_artspezifisch.isChecked()
            max_age_days = None
            if self.chk_age_limit.isChecked():
                try:
                    max_age_days = float(self.txt_max_age.text())
                except ValueError:
                    pass

            recs = match_additive_records(
                self.idx, e_exact, sp, age, "", feed,
                tierart_kategorie=tierart_cat,
                only_artspezifisch=only_artspez,
                max_hoechstalter_tage=max_age_days
            )

            if not recs:
                subs = self.idx["e_to_all_substances"].get(e_exact, [])
            else:
                subs = sorted({(r.substance or "").strip() for r in recs if r.substance})

            refill_editable_combobox(self.cbo_sub, subs or self.idx["all_substances"])
            if len(subs) == 1:
                self.cbo_sub.setEditText(subs[0])

            if len(recs) == 1 and recs[0].unit:
                self.cbo_unit.setCurrentText(recs[0].unit)
        finally:
            self._syncing = False

    def on_s_changed(self, _):
        if self._syncing:
            return
        self._syncing = True
        try:
            sub = (self.cbo_sub.currentText() or "").strip()
            if not sub:
                refill_editable_combobox(self.cbo_sub, self.idx["all_substances"])
                self.cbo_sub.setCurrentIndex(-1)
                self.cbo_sub.setEditText("")
                self.cbo_e.setCurrentIndex(-1)
                self.cbo_e.setEditText("")
                return

            sp = self.cbo_species.currentText()
            age = self.current_age()
            feed = None if self.cbo_feed.currentText() == "(kein Filter)" else self.cbo_feed.currentText()

            tierart_cat = self.cbo_tierart_cat.currentText()
            only_artspez = self.chk_artspezifisch.isChecked()
            max_age_days = None
            if self.chk_age_limit.isChecked():
                try:
                    max_age_days = float(self.txt_max_age.text())
                except ValueError:
                    pass

            recs = match_additive_records(
                self.idx, "", sp, age, sub, feed,
                tierart_kategorie=tierart_cat,
                only_artspezifisch=only_artspez,
                max_hoechstalter_tage=max_age_days
            )
            if not recs:
                e_list = self.idx["sub_to_all_e_numbers"].get(sub.lower(), [])
            else:
                e_list = sorted({r.e_number.upper() for r in recs if r.e_number})

            if len(e_list) == 1:
                self.cbo_e.setEditText(e_list[0])
        finally:
            self._syncing = False

    def on_check(self):
        e_input = self.cbo_e.currentText().strip()
        if not e_input:
            QMessageBox.warning(self, "Fehler", "Bitte E-Nummer eingeben.")
            return

        e = e_input.upper()
        try:
            val = float(self.txt_value.text().replace(",", "."))
        except Exception:
            QMessageBox.warning(self, "Fehler", "Laborwert muss eine Zahl sein.")
            return

        sp = self.cbo_species.currentText()
        age = self.current_age()
        feed = None if self.cbo_feed.currentText() == "(kein Filter)" else self.cbo_feed.currentText()
        sub = self.cbo_sub.currentText().strip()

        tierart_cat = self.cbo_tierart_cat.currentText()
        only_artspez = self.chk_artspezifisch.isChecked()
        max_age_days = None
        if self.chk_age_limit.isChecked():
            try:
                max_age_days = float(self.txt_max_age.text())
            except ValueError:
                pass

        recs = match_additive_records(
            self.idx, e, sp, age, sub, feed,
            tierart_kategorie=tierart_cat,
            only_artspezifisch=only_artspez,
            max_hoechstalter_tage=max_age_days
        )

        if not recs:
            all_recs = [a for a in self.additives if (a.e_number or "").upper() == e]
            species_list = sorted({
                r.species for r in all_recs
                if r.species and r.species not in ("Alle Tierarten", sp)
            })
            species_txt = ", ".join(species_list) if species_list else "–"
            hint = (
                f"⚠ Für die Tierart „{sp}“ existiert kein Eintrag für {e}."
                f"<br>Grenzwerte liegen vor für: {species_txt}"
            )
            self._set_out(hint, ok=None)
            return

        if len(recs) > 1:
            msg = "<br>".join([f"{r.e_number} {r.substance or ''} → {format_range(r)}" for r in recs])
            self._set_out("Mehrdeutig – bitte genauer eingrenzen.<br>" + msg, ok=None)
            return

        ok, lines = evaluate_single_value(val, recs[0])
        self._set_out("\n".join(lines), ok=ok)

# =========================================================
# Kombinationsprüfung
# =========================================================

def find_applicable_combo_rules(rules: List[ComboRule], e_numbers: List[str],
                                species: str, e_to_category: Dict[str, set]) -> List[ComboRule]:
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

class KombiPruefungWidget(QWidget):
    def __init__(self, additives: List[Additive], idx: Dict[str, Any], rules: List[ComboRule]):
        super().__init__()
        self.additives, self.idx, self.rules = additives, idx, rules
        self._busy_rows: set[int] = set()

        self.cbo_species = QComboBox()
        all_species = {"Alle Tierarten"}
        for a in additives:
            all_species.update(extract_individual_species(a.species))
        self.cbo_species.addItems(sorted(all_species))
        self.cbo_species.setCurrentText("Alle Tierarten")

        self.cbo_age = QComboBox()
        self.age_map = {"Kein Altersfilter": 0}
        for m in idx["age_options"]:
            self.age_map[f"≤ {m} Monate"] = int(m)
        self.cbo_age.addItems(self.age_map.keys())
        self.cbo_age.setCurrentText("Kein Altersfilter")

        self.cbo_feed = QComboBox()
        feed_types = sorted({ft for a in additives for ft in (a.feed_type_allowed or [])} | {"(kein Filter)"})
        self.cbo_feed.addItems(feed_types)
        self.cbo_feed.setCurrentText("(kein Filter)")

        self.cbo_tierart_cat = QComboBox()
        tierart_categories = sorted({
            a.extra.get("tierart_kategorie")
            for a in additives
            if a.extra.get("tierart_kategorie")
        } | {"Alle Kategorien"})
        self.cbo_tierart_cat.addItems(tierart_categories)
        self.cbo_tierart_cat.setCurrentText("Alle Kategorien")

        self.chk_artspezifisch = QCheckBox("Nur artspezifische")
        self.chk_artspezifisch.setChecked(False)

        self.tbl = QTableWidget(1, 4)
        self.tbl.setHorizontalHeaderLabels(["E-Nummer", "Stoff", "Wert", "Einheit"])
        self.tbl.horizontalHeader().setStretchLastSection(True)

        self.btn_add = QPushButton("+ Zeile")
        self.btn_add.clicked.connect(self.add_row)
        self.btn_del = QPushButton("– Zeile")
        self.btn_del.clicked.connect(self.delete_row)
        self.btn_check = QPushButton("Kombination prüfen")
        self.btn_check.clicked.connect(self.on_check)
        self.btn_export = QPushButton("Bericht exportieren…")
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self.export_pdf)

        self.out = QTextEdit()
        self.out.setReadOnly(True)
        self.out.setMinimumHeight(240)

        top = QGridLayout()
        top.addWidget(QLabel("Tierart-Kat.:"), 0, 0)
        top.addWidget(self.cbo_tierart_cat, 0, 1)
        top.addWidget(QLabel("Tierart:"), 0, 2)
        top.addWidget(self.cbo_species, 0, 3)
        top.addWidget(QLabel("Alter:"), 0, 4)
        top.addWidget(self.cbo_age, 0, 5)
        top.addWidget(QLabel("Feed-Typ:"), 1, 0)
        top.addWidget(self.cbo_feed, 1, 1)
        top.addWidget(self.chk_artspezifisch, 1, 2, 1, 2)

        h = QHBoxLayout()
        h.addWidget(self.btn_add)
        h.addWidget(self.btn_del)
        h.addStretch(1)
        h.addWidget(self.btn_check)

        v = QVBoxLayout()
        v.addLayout(top)
        v.addWidget(self.tbl)
        v.addLayout(h)
        v.addWidget(QLabel("Auswertung:"))
        v.addWidget(self.out)
        h2 = QHBoxLayout()
        h2.addStretch(1)
        h2.addWidget(self.btn_export)
        v.addLayout(h2)
        self.setLayout(v)

        self.cbo_tierart_cat.currentTextChanged.connect(self.on_tierart_cat_changed)

        for r in range(self.tbl.rowCount()):
            self._setup_row(r)

        self._last_report = None

    def _refill(self, cb: QComboBox, items: List[str], set_text: Optional[str] = None):
        cb.blockSignals(True)
        cb.clear()
        cb.addItems(items)
        comp = QCompleter(items)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        cb.setCompleter(comp)
        if set_text is not None:
            cb.setEditText(set_text)
        cb.blockSignals(False)

    def _set_text(self, cb: QComboBox, text: str):
        cb.blockSignals(True)
        cb.setEditText(text)
        cb.blockSignals(False)

    def _clear_combo(self, cb: QComboBox, all_items: List[str]):
        self._refill(cb, all_items, set_text="")
        cb.setCurrentIndex(-1)

    def _begin_row(self, r: int) -> bool:
        if r in self._busy_rows:
            return False
        self._busy_rows.add(r)
        return True

    def _end_row(self, r: int):
        self._busy_rows.discard(r)

    def on_tierart_cat_changed(self):
        category = self.cbo_tierart_cat.currentText()
        if category == "Alle Kategorien":
            available_species = {"Alle Tierarten"}
            for additive in self.additives:
                available_species.update(extract_individual_species(additive.species))
            available_species = sorted(available_species)
        else:
            available_species = {"Alle Tierarten"}
            for additive in self.additives:
                if additive.extra.get("tierart_kategorie") == category:
                    available_species.update(
                        extract_individual_species(additive.species, category=category)
                    )
            available_species = sorted(available_species)

        self.cbo_species.blockSignals(True)
        current_text = self.cbo_species.currentText()
        self.cbo_species.clear()
        self.cbo_species.addItems(available_species)
        if current_text in available_species:
            self.cbo_species.setCurrentText(current_text)
        elif available_species:
            self.cbo_species.setCurrentIndex(0)
        self.cbo_species.blockSignals(False)

    def _setup_row(self, r):
        cb_e = make_editable_combobox(self.idx["all_e_numbers"])
        cb_s = make_editable_combobox(self.idx["all_substances"])
        cb_u = QComboBox()
        cb_u.addItems(self.idx.get("all_units", ["mg/kg"]))

        cb_e.currentTextChanged.connect(lambda _t, row=r: self._on_e_changed(row))
        cb_e.activated.connect(lambda _i, row=r: self._on_e_changed(row))
        cb_s.currentTextChanged.connect(lambda _t, row=r: self._on_s_changed(row))
        cb_s.activated.connect(lambda _i, row=r: self._on_s_changed(row))

        self.tbl.setCellWidget(r, 0, cb_e)
        self.tbl.setCellWidget(r, 1, cb_s)
        self.tbl.setItem(r, 2, QTableWidgetItem(""))
        self.tbl.setCellWidget(r, 3, cb_u)

        self._clear_combo(cb_e, self.idx["all_e_numbers"])
        self._clear_combo(cb_s, self.idx["all_substances"])

    def add_row(self):
        r = self.tbl.rowCount()
        self.tbl.insertRow(r)
        self._setup_row(r)

    def delete_row(self):
        row = self.tbl.currentRow()
        if row < 0:
            QMessageBox.information(self, "Hinweis", "Bitte eine Zeile markieren.")
            return
        self.tbl.removeRow(row)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.delete_row()
        else:
            super().keyPressEvent(event)

    def _on_e_changed(self, r):
        if not self._begin_row(r):
            return
        try:
            cb_e = self.tbl.cellWidget(r, 0)
            cb_s = self.tbl.cellWidget(r, 1)
            cb_u = self.tbl.cellWidget(r, 3)
            e = (cb_e.currentText() or "").strip().upper()

            if not e:
                self._clear_combo(cb_s, self.idx["all_substances"])
                return

            sp = self.cbo_species.currentText()
            age = self.age_map.get(self.cbo_age.currentText(), 0)
            feed = None if self.cbo_feed.currentText() == "(kein Filter)" else self.cbo_feed.currentText()
            tierart_cat = self.cbo_tierart_cat.currentText()
            only_artspez = self.chk_artspezifisch.isChecked()

            recs = match_additive_records(
                self.idx, e, sp, age, "", feed,
                tierart_kategorie=tierart_cat,
                only_artspezifisch=only_artspez
            )

            if not recs:
                subs_global = self.idx["e_to_all_substances"].get(e, [])
                if subs_global:
                    self._refill(cb_s, subs_global, set_text=(subs_global[0] if len(subs_global) == 1 else ""))
                else:
                    self._clear_combo(cb_s, self.idx["all_substances"])
                return

            subs = sorted({(x.substance or "").strip() for x in recs if x.substance})
            if subs:
                self._refill(cb_s, subs, set_text=(subs[0] if len(subs) == 1 else ""))
            else:
                subs_global = self.idx["e_to_all_substances"].get(e, [])
                if subs_global:
                    self._refill(cb_s, subs_global, set_text=(subs_global[0] if len(subs_global) == 1 else ""))
                else:
                    self._clear_combo(cb_s, self.idx["all_substances"])

            if len(recs) == 1 and recs[0].unit:
                cb_u.setCurrentText(recs[0].unit)
        finally:
            self._end_row(r)

    def _on_s_changed(self, r):
        if not self._begin_row(r):
            return
        try:
            cb_e = self.tbl.cellWidget(r, 0)
            cb_s = self.tbl.cellWidget(r, 1)
            sub = (cb_s.currentText() or "").strip()

            if not sub:
                self._set_text(cb_e, "")
                cb_e.setCurrentIndex(-1)
                self._clear_combo(cb_s, self.idx["all_substances"])
                return

            sp = self.cbo_species.currentText()
            age = self.age_map.get(self.cbo_age.currentText(), 0)
            feed = None if self.cbo_feed.currentText() == "(kein Filter)" else self.cbo_feed.currentText()
            tierart_cat = self.cbo_tierart_cat.currentText()
            only_artspez = self.chk_artspezifisch.isChecked()

            recs = match_additive_records(
                self.idx, "", sp, age, sub, feed,
                tierart_kategorie=tierart_cat,
                only_artspezifisch=only_artspez
            )

            if not recs:
                e_list = self.idx["sub_to_all_e_numbers"].get(sub.lower(), [])
                if len(e_list) == 1:
                    self._set_text(cb_e, e_list[0])
                return

            e_list = sorted({x.e_number.upper() for x in recs if x.e_number})
            if len(e_list) == 1:
                self._set_text(cb_e, e_list[0])
        finally:
            self._end_row(r)

    def on_check(self):
        rows = []
        for r in range(self.tbl.rowCount()):
            cb_e = self.tbl.cellWidget(r, 0)
            cb_s = self.tbl.cellWidget(r, 1)
            v_item = self.tbl.item(r, 2)
            cb_u = self.tbl.cellWidget(r, 3)
            if not cb_e or not v_item:
                continue
            e = (cb_e.currentText() or "").strip().upper()
            if not e:
                continue
            try:
                val = float((v_item.text() or "").replace(",", "."))
            except Exception:
                QMessageBox.warning(self, "Fehler", f"Ungültiger Wert in Zeile {r+1}")
                return
            rows.append({
                "row": r + 1,
                "e": e,
                "sub": (cb_s.currentText() or "").strip(),
                "val": val,
                "unit": cb_u.currentText().strip()
            })

        if not rows:
            self.out.setHtml("<i>Keine Eingaben.</i>")
            return

        sp = self.cbo_species.currentText()
        age = self.age_map.get(self.cbo_age.currentText(), 0)
        feed = None if self.cbo_feed.currentText() == "(kein Filter)" else self.cbo_feed.currentText()
        tierart_cat = self.cbo_tierart_cat.currentText()
        only_artspez = self.chk_artspezifisch.isChecked()

        html_blocks = []
        e_for_combo, val_for_combo = [], {}

        for row in rows:
            e, sub, val, unit = row["e"], row["sub"], row["val"], row["unit"]
            recs = match_additive_records(
                self.idx, e, sp, age, sub, feed,
                tierart_kategorie=tierart_cat,
                only_artspezifisch=only_artspez
            )
            header = f"{e} {sub}".strip()

            if not recs:
                all_recs = [a for a in self.additives if (a.e_number or "").upper() == e]
                species_list = sorted({
                    r.species for r in all_recs
                    if r.species and r.species not in ("Alle Tierarten", sp)
                })
                species_txt = ", ".join(species_list) if species_list else "–"
                html_blocks.append(
                    f'<b><span style="color:#f9a825">⚠ {header}: '
                    f'Für die Tierart „{sp}“ existiert kein Grenzwert.<br>'
                    f'Grenzwerte liegen vor für: {species_txt}</span></b>'
                )
                continue

            if len(recs) > 1:
                msg = "<br>".join([f"{r.e_number} {r.substance or ''} → {format_range(r)}" for r in recs])
                html_blocks.append(f'<b><span style="color:#c62828">{header}: Mehrdeutig.</span></b><br>{msg}')
                continue

            ok, lines = evaluate_single_value(val, recs[0])
            color = "#2e7d32" if ok else "#c62828"
            html_blocks.append(f'<b><span style="color:{color}">{header}</span></b><br>' +
                               "<br>".join(lines) + f"<br>Maßeinheit: {unit}")
            e_for_combo.append(e)
            val_for_combo[e] = val

        combo_rules = find_applicable_combo_rules(self.rules, e_for_combo, sp, self.idx["e_to_category"])
        if combo_rules:
            html_blocks.append("<hr><b>Kombinationsregeln:</b>")
            for rule in combo_rules:
                sum_val, contributors = 0.0, []
                for e in e_for_combo:
                    if rule.affected_e_numbers and e in [x.upper() for x in rule.affected_e_numbers]:
                        sum_val += val_for_combo.get(e, 0)
                        contributors.append(e)
                ok = sum_val <= rule.max_total_value + 1e-12
                color = "#2e7d32" if ok else "#c62828"
                html_blocks.append(
                    f'<b><span style="color:{color}">{("KONFORM" if ok else "NICHT konform")} – Regel {rule.rule_id}</span></b><br>'
                    f"{rule.description}<br>"
                    f"Summe ({', '.join(contributors)}) = {sum_val:g} {rule.unit} "
                    f"(Grenze ≤ {rule.max_total_value:g} {rule.unit})"
                )
        else:
            html_blocks.append("<hr><i>Keine Kombinationsregel gefunden.</i>")

        self.out.setHtml("<br>".join(html_blocks))
        self.btn_export.setEnabled(True)

    def export_pdf(self):
        if not self.out.toPlainText().strip():
            return
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        except ImportError:
            QMessageBox.warning(
                self, "Fehlende Bibliothek",
                "Das Paket 'reportlab' ist nicht installiert.\n"
                "Bitte installieren Sie es mit:\n\n  pip install reportlab"
            )
            return
        path, _ = QFileDialog.getSaveFileName(self, "Bericht speichern", "Auswertung.pdf", "PDF Dateien (*.pdf)")
        if not path:
            return
        try:
            doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=40, rightMargin=40, topMargin=60, bottomMargin=40)
            styles = getSampleStyleSheet()
            title = ParagraphStyle("title", parent=styles["Heading1"], alignment=1)
            small = ParagraphStyle("small", parent=styles["Normal"], fontSize=9)
            elems = [
                Paragraph("Laborauswertung Futtermittel-Zusatzstoffe (EG 1831/2003)", title),
                Spacer(1, 10),
                Paragraph(f"Tierart: {self.cbo_species.currentText()}  |  Alter: {self.cbo_age.currentText()}  |  Feed-Typ: {self.cbo_feed.currentText()}", small),
                Spacer(1, 10),
                Paragraph(self.out.toHtml(), small)
            ]
            doc.build(elems)
            QMessageBox.information(self, "Export", f"PDF gespeichert:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Export fehlgeschlagen", f"Fehler beim Erstellen der PDF:\n{e}")

# =========================================================
# Hauptfenster mit Empty-View & Auto-Reload
# =========================================================

class MainWindow(QMainWindow):
    def __init__(self, additives: List[Additive], combo_rules: List[ComboRule], base_dir: str):
        super().__init__()
        self.additives   = additives
        self.combo_rules = combo_rules
        self.base_dir    = base_dir
        self._toast_proc: Optional[QProcess] = None

        self.setWindowTitle("LAVES Laborauswertung – Zusatzstoffe (EG 1831/2003)")
        self.resize(1220, 760)

        self._build_tabs()

        bar = self.menuBar()
        m_data = bar.addMenu("Daten")
        act_update = m_data.addAction("Zusatzstoffe aktualisieren…")
        act_update.triggered.connect(self._open_updater)

    def _build_tabs(self):
        if self.centralWidget() is None:
            tabs = QTabWidget()
            self.setCentralWidget(tabs)
        else:
            tabs: QTabWidget = self.centralWidget()
            tabs.clear()

        has_data = len(self.additives) > 0

        if has_data:
            idx = build_indexes(self.additives)
            tabs.addTab(EinzelpruefungWidget(self.additives, idx), "Einzelprüfung")
            tabs.addTab(KombiPruefungWidget(self.additives, idx, self.combo_rules), "Kombinationsprüfung")

            try:
                combo_tab = tabs.widget(1)
                if hasattr(combo_tab, 'tbl'):
                    combo_tab.tbl.setColumnWidth(0, 110)
                    combo_tab.tbl.setColumnWidth(1, 340)
                    combo_tab.tbl.setColumnWidth(2, 120)
                    combo_tab.tbl.setColumnWidth(3, 140)
            except Exception:
                pass

        else:
            empty_widget = QWidget()
            lay = QVBoxLayout()
            lay.setAlignment(Qt.AlignCenter)
            lay.setSpacing(30)

            lbl = QLabel(
                "Keine lokale Datenbasis vorhanden\n\n"
                "Bitte aktualisieren Sie die Zusatzstoff-Datenbank über das Menü:\n"
                "Daten → Zusatzstoffe aktualisieren…"
            )
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setWordWrap(True)
            lbl.setStyleSheet("font-size: 16pt; color: #555555; line-height: 1.5;")

            btn = QPushButton("Daten jetzt aktualisieren")
            btn.setFixedSize(320, 60)
            btn.setStyleSheet("font-size: 15pt; padding: 12px;")
            btn.clicked.connect(self._open_updater)

            lay.addStretch(1)
            lay.addWidget(lbl)
            lay.addWidget(btn, alignment=Qt.AlignCenter)
            lay.addStretch(2)

            empty_widget.setLayout(lay)
            tabs.addTab(empty_widget, "Keine Daten geladen")

    def _open_updater(self):
        # Try compiled executable first (Windows deployment), then fall back to Python script
        toast_exe = os.path.join(self.base_dir, "Data", "laves_toast_qt.exe")
        toast_py  = os.path.join(self.base_dir, "Data", "laves_toast_qt.py")

        if os.path.isfile(toast_exe):
            program   = toast_exe
            arguments: List[str] = []
        elif os.path.isfile(toast_py):
            program   = sys.executable
            arguments = [toast_py]
        else:
            QMessageBox.critical(
                self, "Updater nicht gefunden",
                f"Datei nicht gefunden:\n{toast_exe}\n\n"
                "Bitte prüfen Sie, ob 'laves_toast_qt.exe' oder 'laves_toast_qt.py' "
                "im Ordner 'Data' liegt."
            )
            return

        self._toast_proc = QProcess(self)
        self._toast_proc.setProgram(program)
        self._toast_proc.setArguments(arguments)

        # Use start() (not startDetached()) so the finished signal fires and
        # reload_data() is called when the updater window closes.
        self._toast_proc.finished.connect(self._on_toast_finished)
        self._toast_proc.errorOccurred.connect(self._on_toast_error)
        self._toast_proc.start()

    def _on_toast_error(self, error):
        QMessageBox.warning(
            self, "Updater-Fehler",
            f"Fehler beim Start:\n{self._toast_proc.errorString()}"
        )

    def _on_toast_finished(self, exit_code, exit_status):
        if exit_code == 0:
            QMessageBox.information(
                self, "Update abgeschlossen",
                "Datenaktualisierung scheint erfolgreich gewesen zu sein.\nLade Daten neu …"
            )
            self.reload_data()
        else:
            QMessageBox.warning(
                self, "Update-Fehler",
                f"Updater beendete mit Code {exit_code}.\n"
                "Prüfen Sie bitte, ob die JSON-Dateien erstellt wurden."
            )
            self.reload_data()  # trotzdem versuchen neu zu laden

    def reload_data(self):
        base = self.base_dir

        add_path = None
        for cand in [
            os.path.join(base, "zusatzstoffe.json"),
            os.path.join(base, "Data", "zusatzstoffe.json"),
            os.path.join(base, "data", "zusatzstoffe.json"),
        ]:
            if os.path.isfile(cand):
                add_path = cand
                break

        cr_path = None
        for cand in [
            os.path.join(base, "kombiregeln.json"),
            os.path.join(base, "Data", "kombiregeln.json"),
            os.path.join(base, "data", "kombiregeln.json"),
        ]:
            if os.path.isfile(cand):
                cr_path = cand
                break

        new_additives = []
        if add_path:
            try:
                new_additives = load_additives(add_path)
            except Exception as e:
                QMessageBox.warning(self, "Ladefehler", f"Zusatzstoffe:\n{e}")

        new_combo_rules = []
        if cr_path:
            try:
                new_combo_rules = load_combo_rules(cr_path)
            except Exception as e:
                QMessageBox.warning(self, "Ladefehler", f"Kombinationsregeln:\n{e}")

        self.additives   = new_additives
        self.combo_rules = new_combo_rules

        self._build_tabs()

# =========================================================
# Theme & Start
# =========================================================

def apply_modern_theme(app: QApplication):
    app.setStyle(QStyleFactory.create("Fusion"))
    palette = QPalette()
    use_dark = False
    try:
        import platform, subprocess
        if platform.system() == "Darwin":
            mode = subprocess.check_output(["defaults", "read", "-g", "AppleInterfaceStyle"], stderr=subprocess.DEVNULL)
            use_dark = b"Dark" in mode
    except Exception:
        pass

    if use_dark:
        palette.setColor(QPalette.Window, QColor(37, 37, 38))
        palette.setColor(QPalette.WindowText, QColor(220, 220, 220))
        palette.setColor(QPalette.Base, QColor(45, 45, 48))
        palette.setColor(QPalette.Text, QColor(230, 230, 230))
    else:
        palette.setColor(QPalette.Window, QColor(250, 250, 250))
        palette.setColor(QPalette.WindowText, Qt.black)
        palette.setColor(QPalette.Base, QColor(255, 255, 255))
        palette.setColor(QPalette.Text, Qt.black)
    app.setPalette(palette)
    app.setFont(QFont("Arial", 11))

def main():
    app = QApplication(sys.argv)
    apply_modern_theme(app)

    if getattr(sys, "frozen", False):
        # When frozen, data files (zusatzstoffe.json, laves_toast_qt.exe) are
        # NOT bundled inside the executable – they live in a Data/ subdirectory
        # next to LAVES.exe.  Use sys.executable's parent as the base so that
        # Data/ is always resolved relative to the actual exe location.
        # Note: sys._MEIPASS must NOT be used here because in PyInstaller 6
        # --onedir mode _MEIPASS points to the _internal/ subdirectory, not
        # the directory where the exe was placed.
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    add_path = None
    for cand in [
        os.path.join(base_dir, "zusatzstoffe.json"),
        os.path.join(base_dir, "Data", "zusatzstoffe.json"),
        os.path.join(base_dir, "data", "zusatzstoffe.json"),
    ]:
        if os.path.isfile(cand):
            add_path = cand
            break

    cr_path = None
    for cand in [
        os.path.join(base_dir, "kombiregeln.json"),
        os.path.join(base_dir, "Data", "kombiregeln.json"),
        os.path.join(base_dir, "data", "kombiregeln.json"),
    ]:
        if os.path.isfile(cand):
            cr_path = cand
            break

    additives = []
    combo_rules = []

    if add_path:
        try:
            additives = load_additives(add_path)
        except Exception as e:
            QMessageBox.warning(None, "Warnung", f"Fehler beim Laden der Zusatzstoffe:\n{e}")

    if cr_path:
        try:
            combo_rules = load_combo_rules(cr_path)
        except Exception as e:
            QMessageBox.warning(None, "Warnung", f"Fehler beim Laden der Kombinationsregeln:\n{e}")

    win = MainWindow(additives, combo_rules, base_dir)
    win.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()