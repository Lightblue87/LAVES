#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
zusatzstoff_pruefung_widget.py – ZusatzstoffPruefungWidget für LAVES.

Implementiert die neue Zusatzstoffprüfung: Eingabe von Partiemenge und
Zusatzstoffen mit Prozentanteil, Berechnung der Stoffmasse und Grenzwertprüfung.
"""

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QCompleter, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget,
)

from laves_eval import (
    Additive,
    extract_individual_species,
    match_additive_records,
    derive_e_number_for_substance,
    format_range,
    evaluate_single_value,
)


# =========================================================
# Interne UI-Hilfsfunktionen (analog zu main.py)
# =========================================================

def _make_editable_combobox(items: List[str]) -> QComboBox:
    cb = QComboBox()
    cb.setEditable(True)
    cb.addItems(items)
    completer = QCompleter(items)
    completer.setCaseSensitivity(Qt.CaseInsensitive)
    completer.setFilterMode(Qt.MatchContains)
    cb.setCompleter(completer)
    return cb


def _refill_editable_combobox(
    cb: QComboBox, items: List[str], set_text: Optional[str] = None
):
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


# =========================================================
# ZusatzstoffPruefungWidget
# =========================================================

class ZusatzstoffPruefungWidget(QWidget):
    """Widget für die Zusatzstoffprüfung.

    Der Nutzer gibt eine Partiemenge und beliebig viele Zusatzstoffe mit
    Prozentanteil ein.  Die App berechnet die Stoffmasse und prüft, ob die
    resultierende Konzentration innerhalb der zulässigen Höchstgehalte liegt.
    """

    def __init__(self, additives: List[Additive], idx: Dict[str, Any]):
        super().__init__()
        self.additives = additives
        self.idx = idx
        self._busy_rows: set = set()

        # ── Partiemenge ───────────────────────────────────────────────────
        self.txt_partie = QLineEdit()
        self.txt_partie.setPlaceholderText("Partiemenge (Zahl)")

        self.cbo_partie_unit = QComboBox()
        self.cbo_partie_unit.addItems(["g", "kg", "t"])
        self.cbo_partie_unit.setCurrentText("kg")

        # ── Kontext: Tierart-Kategorie, Tierart, Alter ────────────────────
        self.cbo_tierart_cat = QComboBox()
        tierart_categories = sorted(
            {
                a.extra.get("tierart_kategorie")
                for a in additives
                if a.extra.get("tierart_kategorie")
            }
            | {"Alle Kategorien"}
        )
        self.cbo_tierart_cat.addItems(tierart_categories)
        self.cbo_tierart_cat.setCurrentText("Alle Kategorien")

        self.cbo_species = QComboBox()
        all_species: set = {"Alle Tierarten"}
        for a in additives:
            all_species.update(extract_individual_species(a.species))
        self.cbo_species.addItems(sorted(all_species))
        self.cbo_species.setCurrentText("Alle Tierarten")

        self.cbo_age = QComboBox()
        self.age_map: Dict[str, int] = {"Kein Altersfilter": 0}
        for m in idx["age_options"]:
            self.age_map[f"≤ {m} Monate"] = int(m)
        self.cbo_age.addItems(self.age_map.keys())
        self.cbo_age.setCurrentText("Kein Altersfilter")

        # ── Zusatzstoff-Tabelle ───────────────────────────────────────────
        self.tbl = QTableWidget(1, 3)
        self.tbl.setHorizontalHeaderLabels(
            ["Zulassungsnummer", "Stoffname", "Anteil in %"]
        )
        self.tbl.horizontalHeader().setStretchLastSection(True)
        self.tbl.setColumnWidth(0, 160)
        self.tbl.setColumnWidth(1, 340)

        # ── Buttons ───────────────────────────────────────────────────────
        self.btn_add = QPushButton("+ Zeile")
        self.btn_add.clicked.connect(self.add_row)
        self.btn_del = QPushButton("– Zeile")
        self.btn_del.clicked.connect(self.delete_row)
        self.btn_check = QPushButton("Prüfen")
        self.btn_check.clicked.connect(self.on_check)

        # ── Ergebnisbereich ───────────────────────────────────────────────
        self.out = QTextEdit()
        self.out.setReadOnly(True)
        self.out.setMinimumHeight(260)

        # ── Layout ────────────────────────────────────────────────────────
        top = QGridLayout()

        hunit = QHBoxLayout()
        hunit.addWidget(self.txt_partie)
        hunit.addWidget(self.cbo_partie_unit)
        top.addWidget(QLabel("Partiemenge:"), 0, 0)
        top.addLayout(hunit, 0, 1, 1, 3)

        top.addWidget(QLabel("Tierart-Kat.:"), 1, 0)
        top.addWidget(self.cbo_tierart_cat, 1, 1)
        top.addWidget(QLabel("Tierart:"), 1, 2)
        top.addWidget(self.cbo_species, 1, 3)
        top.addWidget(QLabel("Alter:"), 2, 0)
        top.addWidget(self.cbo_age, 2, 1)

        hbtn = QHBoxLayout()
        hbtn.addWidget(self.btn_add)
        hbtn.addWidget(self.btn_del)
        hbtn.addStretch(1)
        hbtn.addWidget(self.btn_check)

        v = QVBoxLayout()
        v.addLayout(top)
        v.addWidget(self.tbl)
        v.addLayout(hbtn)
        v.addWidget(QLabel("Auswertung:"))
        v.addWidget(self.out)
        self.setLayout(v)

        # ── Signals ───────────────────────────────────────────────────────
        self.cbo_tierart_cat.currentTextChanged.connect(self.on_tierart_cat_changed)

        # ── Initialzustand ────────────────────────────────────────────────
        for r in range(self.tbl.rowCount()):
            self._setup_row(r)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _current_age(self) -> int:
        return self.age_map.get(self.cbo_age.currentText(), 0)

    def on_tierart_cat_changed(self):
        category = self.cbo_tierart_cat.currentText()
        if category in ("Alle Kategorien", "Alle Tierarten"):
            available_species: set = {"Alle Tierarten"}
            for additive in self.additives:
                available_species.update(extract_individual_species(additive.species))
            species_list = sorted(available_species)
        else:
            available_species = {"Alle Tierarten"}
            for additive in self.additives:
                if additive.extra.get("tierart_kategorie") == category:
                    available_species.update(
                        extract_individual_species(additive.species, category=category)
                    )
            species_list = sorted(available_species)

        self.cbo_species.blockSignals(True)
        current_text = self.cbo_species.currentText()
        self.cbo_species.clear()
        self.cbo_species.addItems(species_list)
        if current_text in species_list:
            self.cbo_species.setCurrentText(current_text)
        elif species_list:
            self.cbo_species.setCurrentIndex(0)
        self.cbo_species.blockSignals(False)

    # ------------------------------------------------------------------
    # Tabellen-Zeilen
    # ------------------------------------------------------------------

    def _setup_row(self, r: int):
        cb_e = _make_editable_combobox(self.idx["all_e_numbers"])
        cb_s = _make_editable_combobox(self.idx["all_substances"])

        cb_e.currentTextChanged.connect(lambda _t, row=r: self._on_e_changed(row))
        cb_e.activated.connect(lambda _i, row=r: self._on_e_changed(row))
        cb_s.currentTextChanged.connect(lambda _t, row=r: self._on_s_changed(row))
        cb_s.activated.connect(lambda _i, row=r: self._on_s_changed(row))

        self.tbl.setCellWidget(r, 0, cb_e)
        self.tbl.setCellWidget(r, 1, cb_s)
        self.tbl.setItem(r, 2, QTableWidgetItem(""))

        cb_e.blockSignals(True)
        cb_e.setCurrentIndex(-1)
        cb_e.setEditText("")
        cb_e.blockSignals(False)

        cb_s.blockSignals(True)
        cb_s.setCurrentIndex(-1)
        cb_s.setEditText("")
        cb_s.blockSignals(False)

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

    # ------------------------------------------------------------------
    # Busy-Row-Schutz (verhindert rekursive Signalschleifen)
    # ------------------------------------------------------------------

    def _begin_row(self, r: int) -> bool:
        if r in self._busy_rows:
            return False
        self._busy_rows.add(r)
        return True

    def _end_row(self, r: int):
        self._busy_rows.discard(r)

    # ------------------------------------------------------------------
    # Autocomplete: E-Nummer ↔ Stoffname
    # ------------------------------------------------------------------

    def _on_e_changed(self, r: int):
        if not self._begin_row(r):
            return
        try:
            cb_e = self.tbl.cellWidget(r, 0)
            cb_s = self.tbl.cellWidget(r, 1)
            if cb_e is None or cb_s is None:
                return

            e = (cb_e.currentText() or "").strip().upper()
            if not e:
                _refill_editable_combobox(
                    cb_s, self.idx["all_substances"], set_text=""
                )
                cb_s.setCurrentIndex(-1)
                return

            recs = match_additive_records(
                self.idx,
                e,
                species=self.cbo_species.currentText(),
                age_months=self._current_age(),
                tierart_kategorie=self.cbo_tierart_cat.currentText(),
            )

            if not recs:
                subs_global = self.idx["e_to_all_substances"].get(e, [])
                _refill_editable_combobox(
                    cb_s,
                    subs_global if subs_global else self.idx["all_substances"],
                    set_text=(subs_global[0] if len(subs_global) == 1 else ""),
                )
                return

            subs = sorted({(x.substance or "").strip() for x in recs if x.substance})
            _refill_editable_combobox(
                cb_s,
                subs if subs else self.idx["all_substances"],
                set_text=(subs[0] if len(subs) == 1 else ""),
            )
        finally:
            self._end_row(r)

    def _on_s_changed(self, r: int):
        if not self._begin_row(r):
            return
        try:
            cb_e = self.tbl.cellWidget(r, 0)
            cb_s = self.tbl.cellWidget(r, 1)
            if cb_e is None or cb_s is None:
                return

            sub = (cb_s.currentText() or "").strip()
            if not sub:
                cb_e.blockSignals(True)
                cb_e.setCurrentIndex(-1)
                cb_e.setEditText("")
                cb_e.blockSignals(False)
                return

            e_number = derive_e_number_for_substance(
                self.idx,
                sub,
                species=self.cbo_species.currentText(),
                age_months=self._current_age(),
                tierart_kategorie=self.cbo_tierart_cat.currentText(),
            )
            if e_number:
                cb_e.blockSignals(True)
                cb_e.setEditText(e_number)
                cb_e.blockSignals(False)
        finally:
            self._end_row(r)

    # ------------------------------------------------------------------
    # Prüflogik
    # ------------------------------------------------------------------

    def on_check(self):
        # ── 1. Partiemenge einlesen und normalisieren ─────────────────────
        try:
            partie_raw = float(self.txt_partie.text().replace(",", "."))
        except Exception:
            QMessageBox.warning(
                self, "Fehler", "Partiemenge muss eine positive Zahl sein."
            )
            return

        if partie_raw <= 0:
            QMessageBox.warning(
                self, "Fehler", "Partiemenge muss größer als 0 sein."
            )
            return

        unit = self.cbo_partie_unit.currentText()
        if unit == "g":
            partie_kg = partie_raw / 1000.0
        elif unit == "t":
            partie_kg = partie_raw * 1000.0
        else:
            partie_kg = partie_raw

        sp = self.cbo_species.currentText()
        age = self._current_age()
        tierart_cat = self.cbo_tierart_cat.currentText()

        # ── 2. Tabellenzeilen einlesen ────────────────────────────────────
        rows = []
        for r in range(self.tbl.rowCount()):
            cb_e = self.tbl.cellWidget(r, 0)
            cb_s = self.tbl.cellWidget(r, 1)
            pct_item = self.tbl.item(r, 2)
            if cb_e is None:
                continue

            e = (cb_e.currentText() or "").strip().upper()
            sub = ((cb_s.currentText() if cb_s else "") or "").strip()
            pct_text = ((pct_item.text() if pct_item else "") or "").strip()

            # Leere Zeilen ignorieren
            if not e and not sub:
                continue

            # Prozentwert ist Pflicht, wenn ein Stoff eingetragen ist
            if not pct_text:
                QMessageBox.warning(
                    self,
                    "Fehler",
                    f"Zeile {r + 1}: Bitte Anteil in % eingeben.",
                )
                return

            try:
                pct = float(pct_text.replace(",", "."))
            except Exception:
                QMessageBox.warning(
                    self, "Fehler", f"Zeile {r + 1}: Ungültiger Prozentwert."
                )
                return

            if pct < 0:
                QMessageBox.warning(
                    self,
                    "Fehler",
                    f"Zeile {r + 1}: Prozentwert darf nicht negativ sein.",
                )
                return

            rows.append({"row": r + 1, "e": e, "sub": sub, "pct": pct})

        if not rows:
            self.out.setHtml("<i>Keine auswertbaren Zeilen eingegeben.</i>")
            return

        # ── 3. Prüfung pro Stoff ──────────────────────────────────────────
        html_blocks = []
        for row in rows:
            e, sub, pct = row["e"], row["sub"], row["pct"]
            header = (f"{e} {sub}".strip()) if e else sub

            # Berechnungen
            stoff_kg = partie_kg * (pct / 100.0)
            stoff_g = stoff_kg * 1000.0
            stoff_mg = stoff_kg * 1_000_000.0
            # Konzentration in mg/kg (= pct * 10_000, aber über Partiemenge gerechnet)
            konzentration_mg_kg = stoff_mg / partie_kg

            mass_info = (
                f"Anteil: {pct:g}% | "
                f"Masse: {stoff_g:g} g ({stoff_kg:g} kg) | "
                f"Konzentration: {konzentration_mg_kg:g} mg/kg"
            )

            recs = match_additive_records(
                self.idx,
                e,
                species=sp,
                age_months=age,
                substance_query=sub,
                tierart_kategorie=tierart_cat,
            )

            # Kein passender Grenzwert für diese Tierart / dieses Alter
            if not recs:
                if e:
                    all_recs = [
                        a for a in self.additives
                        if (a.e_number or "").upper() == e
                    ]
                else:
                    all_recs = [
                        a for a in self.additives
                        if sub.casefold() == (a.substance or "").casefold()
                    ]
                species_list = sorted({
                    rx.species
                    for rx in all_recs
                    if rx.species and rx.species not in ("Alle Tierarten", sp)
                })
                species_txt = ", ".join(species_list) if species_list else "–"
                html_blocks.append(
                    f'<b><span style="color:#f9a825">⚠ {header}</span></b><br>'
                    f'{mass_info}<br>'
                    f'Für die Tierart „{sp}" wurde kein passender Grenzwert gefunden.<br>'
                    f'Grenzwerte liegen vor für: {species_txt}'
                )
                continue

            # Mehrdeutig
            if len(recs) > 1:
                details = "<br>".join(
                    " ".join(filter(None, [r.e_number, r.substance]))
                    + f" → {format_range(r)}"
                    for r in recs
                )
                html_blocks.append(
                    f'<b><span style="color:#f9a825">⚠ {header}: Mehrdeutig – '
                    f'bitte genauer eingrenzen.</span></b><br>'
                    f'{mass_info}<br>{details}'
                )
                continue

            # Grenzwertprüfung
            ok, lines = evaluate_single_value(konzentration_mg_kg, recs[0])
            color = (
                "#2e7d32" if ok is True
                else ("#f9a825" if ok is None else "#c62828")
            )
            html_blocks.append(
                f'<b><span style="color:{color}">{header}</span></b><br>'
                f'{mass_info}<br>'
                + "<br>".join(lines)
            )

        self.out.setHtml("<br><hr><br>".join(html_blocks))
