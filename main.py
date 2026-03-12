#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
from typing import Optional, List, Dict, Any

from PySide6.QtCore import Qt, QProcess
from PySide6.QtWidgets import (
    QApplication, QComboBox, QCompleter, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPushButton, QTabWidget, QTextEdit,
    QVBoxLayout, QWidget,
)
from PySide6.QtGui import QPalette, QColor, QFont
from PySide6.QtWidgets import QStyleFactory

# Pure evaluation logic lives in laves_eval – no Qt dependency there.
from laves_eval import (
    Additive,
    load_additives,
    build_indexes,
    extract_individual_species,
    match_additive_records,
    derive_e_number_for_substance,
    format_range,
    evaluate_single_value,
    validate_database,
    setup_logging,
)

from zusatzstoff_pruefung_widget import ZusatzstoffPruefungWidget

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

        self.cbo_tierart_cat = QComboBox()
        tierart_categories = sorted({
            a.extra.get("tierart_kategorie")
            for a in additives
            if a.extra.get("tierart_kategorie")
        } | {"Alle Kategorien"})
        self.cbo_tierart_cat.addItems(tierart_categories)
        self.cbo_tierart_cat.setCurrentText("Alle Kategorien")

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
        form.addRow("Alter:", self.cbo_age)
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
        self.cbo_e.currentTextChanged.connect(self.on_e_changed)
        self.cbo_sub.currentTextChanged.connect(self.on_s_changed)

        self.update_context()

    def current_age(self) -> int:
        return self.age_map.get(self.cbo_age.currentText(), 0)

    def on_tierart_cat_changed(self):
        category = self.cbo_tierart_cat.currentText()
        if category in ("Alle Kategorien", "Alle Tierarten"):
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
        if not e:
            return self.idx["all_substances"]
        recs = match_additive_records(
            self.idx, e,
            species=self.cbo_species.currentText(),
            age_months=self.current_age(),
            tierart_kategorie=self.cbo_tierart_cat.currentText(),
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

            recs = match_additive_records(
                self.idx, e_exact,
                species=self.cbo_species.currentText(),
                age_months=self.current_age(),
                tierart_kategorie=self.cbo_tierart_cat.currentText(),
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

            e_number = derive_e_number_for_substance(
                self.idx, sub,
                species=self.cbo_species.currentText(),
                age_months=self.current_age(),
                tierart_kategorie=self.cbo_tierart_cat.currentText(),
            )
            if e_number:
                self.cbo_e.setEditText(e_number)
        finally:
            self._syncing = False

    def on_check(self):
        e_input = self.cbo_e.currentText().strip()
        sub = self.cbo_sub.currentText().strip()

        if not e_input and not sub:
            QMessageBox.warning(self, "Fehler", "Bitte E-Nummer oder Stoff eingeben.")
            return

        try:
            val = float(self.txt_value.text().replace(",", "."))
        except Exception:
            QMessageBox.warning(self, "Fehler", "Laborwert muss eine Zahl sein.")
            return

        sp = self.cbo_species.currentText()
        e = e_input.upper()

        recs = match_additive_records(
            self.idx, e,
            species=sp,
            age_months=self.current_age(),
            substance_query=sub,
            tierart_kategorie=self.cbo_tierart_cat.currentText(),
        )

        if not recs:
            if e:
                all_recs = [a for a in self.additives if (a.e_number or "").upper() == e]
            else:
                all_recs = [
                    a for a in self.additives
                    if sub.casefold() == (a.substance or "").casefold()
                ]
            species_list = sorted({
                r.species for r in all_recs
                if r.species and r.species not in ("Alle Tierarten", sp)
            })
            species_txt = ", ".join(species_list) if species_list else "–"
            identifier = e or sub
            hint = (
                f"⚠ Für die Tierart „{sp}“ existiert kein Eintrag für {identifier}."
                f"<br>Grenzwerte liegen vor für: {species_txt}"
            )
            self._set_out(hint, ok=None)
            return

        if len(recs) > 1:
            msg = "<br>".join([
                " ".join(filter(None, [r.e_number, r.substance])) + f" → {format_range(r)}"
                for r in recs
            ])
            self._set_out("Mehrdeutig – bitte genauer eingrenzen.<br>" + msg, ok=None)
            return

        ok, lines = evaluate_single_value(val, recs[0])
        self._set_out("\n".join(lines), ok=ok)

# =========================================================
# Hauptfenster mit Empty-View & Auto-Reload
# =========================================================

class MainWindow(QMainWindow):
    def __init__(self, additives: List[Additive], base_dir: str):
        super().__init__()
        self.additives = additives
        self.base_dir  = base_dir
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
            tabs.addTab(ZusatzstoffPruefungWidget(self.additives, idx), "Zusatzstoffprüfung")

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

        new_additives = []
        if add_path:
            try:
                new_additives = load_additives(add_path)
            except Exception as e:
                QMessageBox.warning(self, "Ladefehler", f"Zusatzstoffe:\n{e}")

        self.additives = new_additives

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

    # Set up logging (file + console) as early as possible.
    data_dir = os.path.join(base_dir, "Data")
    setup_logging(os.path.join(data_dir, "laves_evaluation.log"))

    add_path = None
    for cand in [
        os.path.join(base_dir, "zusatzstoffe.json"),
        os.path.join(base_dir, "Data", "zusatzstoffe.json"),
        os.path.join(base_dir, "data", "zusatzstoffe.json"),
    ]:
        if os.path.isfile(cand):
            add_path = cand
            break

    additives = []

    if add_path:
        try:
            additives = load_additives(add_path)
        except Exception as e:
            QMessageBox.warning(None, "Warnung", f"Fehler beim Laden der Zusatzstoffe:\n{e}")

    # Validate database at startup and write report next to the data file.
    if additives:
        report_dir = os.path.dirname(add_path) if add_path else data_dir
        validate_database(
            additives,
            report_path=os.path.join(report_dir, "validation_report.txt"),
        )

    win = MainWindow(additives, base_dir)
    win.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()