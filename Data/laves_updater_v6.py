"""
laves_updater_v6.py
===================
BVL Futtermittelzusatzstoff-Parser – vollständig rekonstruiert + Spalten-Fixes
für sonstige_zootechnische_zusatzstoffe (Schema A) und antioxidantien (Schema C).

Schemas:
  A  = VO 1831/2003 Hauptlisten  (zootechnisch, Enzyme, Spurenelemente …)
  A1 = VO 1831/2003 Einzelzulassungen mit "Analysemethode"-Spalte
  B  = RL 70/524 Nährstoffe (Aminosäuren, Vitamine – alte Liste)
  C  = RL 70/524 Technologie (Antioxidantien, Bindemittel, Emulgatoren …)
  S  = Silierzusatzstoffe (Freitext, kein Standardschema)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pdfminer.high_level import extract_pages as pm_extract_pages
from pdfminer.layout import LAParams, LTTextBox, LTTextLine

# ─────────────────────────────────────────────────────────────────────────────
# Pfade
# ─────────────────────────────────────────────────────────────────────────────
try:
    _here = Path(__file__).resolve().parent
except NameError:
    _here = Path(sys.argv[0]).resolve().parent if sys.argv and sys.argv[0] else Path.cwd()

if getattr(sys, "frozen", False):
    # When bundled inside laves_toast_qt.exe, sys.executable points to that exe.
    # Use its parent directory so OUT_JSON is written to a persistent location
    # alongside the executable rather than to a temporary _MEIPASS directory.
    BASE_DIR = Path(sys.executable).resolve().parent
    if BASE_DIR.name.lower() == "data":
        BASE_DIR = BASE_DIR.parent
elif _here.name.lower() == "data":
    # Running from source inside the Data/ subdirectory → escape to project root.
    BASE_DIR = _here.parent
else:
    BASE_DIR = _here

DATA_DIR = BASE_DIR / "Data"
PDF_DIR  = DATA_DIR / "_bvl_pdfs"
OUT_JSON = DATA_DIR / "zusatzstoffe.json"

# ─────────────────────────────────────────────────────────────────────────────
# pdfminer LAParams
# ─────────────────────────────────────────────────────────────────────────────
LAPARAMS = LAParams(
    line_overlap=0.5,
    char_margin=2.0,
    line_margin=0.5,
    word_margin=0.1,
    all_texts=True,
)

# ─────────────────────────────────────────────────────────────────────────────
# Spalten-Definitionen
# ─────────────────────────────────────────────────────────────────────────────

# Schema A  (VO 1831/2003 Hauptlisten: Aminosäuren, Vitamine, Aromastoffe …)
# Kalibriert aus 1831__aminosaeuren.pdf:
#   kenn≈39–53  name≈95–166  zusammensetzung≈195–231  tierart≈371–387
#   höchstalter≈438  min≈487  max≈541  sonstiges≈582  geltung≈757
SCHEMA_A_COLS: List[Tuple[str, float, float]] = [
    ("kennnummer",       20,     79),   # vitamine hat Namen bei x≈81.1 → Grenze auf 79
    ("name",             79,    180),   # Name bei x~81-166 (je nach Seite)
    ("zusammensetzung", 180,    375),
    ("tierart",         375,    430),
    ("hoechstalter",    430,    480),
    ("min",             480,    535),
    ("max",             535,    625),
    ("sonstiges",       625,    745),
    ("geltung",         745,    840),
]

# Schema A1 (VO 1831/2003 Einzelzulassungen mit Inhaber + Analysemethode)
# Kalibriert aus 1831__sonstige_zootechnische_zusatzstoffe.pdf:
#   kenn≈30  inhaber≈85  name≈143  name_en≈175  zusammensetzung≈222
#   tierart≈380  höchstalter≈435  min≈452  max≈548  sonstiges≈608  geltung≈746
SCHEMA_A1_COLS: List[Tuple[str, float, float]] = [
    ("kennnummer",       20,    83),
    ("inhaber",          83,   128),
    ("name",            128,   175),
    ("name_en",         175,   222),
    ("zusammensetzung", 222,   380),
    ("tierart",         380,   435),
    ("hoechstalter",    435,   452),
    ("min",             452,   548),
    ("max",             548,   608),
    ("sonstiges",       608,   746),
    ("geltung",         746,   840),
]

# Schema C  (RL 70/524 Technologie)
# Kalibriert aus 70524__antioxidantien.pdf:
#   kenn≈45  name≈89  chemisch≈188  tierart≈252  höchstalter≈366
#   min≈429  max≈495  sonstiges≈567  geltung≈659  reeval≈751
SCHEMA_C_COLS: List[Tuple[str, float, float]] = [
    ("kennnummer",       20,    88),
    ("name",             88,   188),
    ("chemisch",        188,   260),
    ("tierart",         260,   368),
    ("hoechstalter",    368,   428),
    ("min",             428,   492),
    ("max",             492,   565),
    ("sonstiges",       565,   657),
    ("geltung",         657,   750),
    ("reevaluierung",   750,   840),
]

# Schema B  (RL 70/524 Nährstoffe: Aminosäuren, Vitamine)
SCHEMA_B_COLS: List[Tuple[str, float, float]] = [
    ("kennnummer",       20,    80),
    ("name",             80,   190),
    ("chemisch",        190,   320),
    ("tierart",         320,   420),
    ("hoechstalter",    420,   480),
    ("min",             480,   545),
    ("max",             545,   610),
    ("sonstiges",       610,   720),
    ("geltung",         720,   800),
    ("reevaluierung",   800,   840),
]

# Schema B2  (RL 70/524 Nährstoffe, altes Format: 70524__aminosaeuren, spurenelemente)
# Kalibriert aus 70524__futtermittel_zusatzstoffe_aminosaeuren.pdf:
#   nr≈33  name≈66  chemisch≈172  nährsubstrat≈272  charakteristika≈357
#   tierart≈442  sonderbestimmungen≈513  geltung≈665  reevaluierung≈757
SCHEMA_B2_COLS: List[Tuple[str, float, float]] = [
    ("kennnummer",       20,    62),
    ("name",             62,   168),
    ("chemisch",        168,   268),
    ("zusammensetzung", 268,   430),   # nährsubstrat + charakteristika zusammen
    ("tierart",         430,   510),
    ("sonstiges",       510,   658),   # sonderbestimmungen
    ("geltung",         658,   750),
    ("reevaluierung",   750,   840),
]

# ─────────────────────────────────────────────────────────────────────────────
# Kennnummer-Regex
# ─────────────────────────────────────────────────────────────────────────────
# Schema A/A1: z.B. 4d1, 4d3, 4d800, 4d161g, 4d1703, 1m03
KENN_A_RE = re.compile(
    r"^("
    r"\d[a-z]{1,2}\d{1,5}[a-z]{0,2}(?:\([a-z0-9]+\))?|"   # 4d1, 2a161bi, 3c322i (mittl. Buchst.)
    r"\d[a-z]{0,2}\d{1,5}[a-z]{1,2}(?:\([a-z0-9]+\))?|"   # 51756i, 2b620i (nur nachgest. Buchst.)
    r"\d[a-z]{0,2}\([a-z]{1,3}\)\s*\d{1,5}[a-z]{0,2}|"    # 2a(ii)165, 2a(ii) 167
    r"\d{4,5}|"                                              # 51776 (reine Zahl ≥4 Stellen, kein kurzes Artefakt)
    r"noch\s+\d[a-z]{1,2}\d{1,5}[a-z]{0,2}|"               # noch 3a825 (mittl. Buchst.)
    r"noch\s+\d[a-z]{0,2}\d{1,5}[a-z]{1,2})$",             # noch … (nachgest. Buchst.)
    re.I,
)
# Schema C/B: E 310*, E 320, 3.3.1.1 …
KENN_C_RE = re.compile(
    r"^(E\s*\d{1,4}\*?|noch\s+E\s*\d{1,4}\*?|\d+\.\d+(?:\.\d+)*(?:\.\*)?|\*)$",
    re.I,
)
# \d{1,4} statt \d{3,4}: deckt auch einstellige Spurenelement-Kennnummern ab (E 1, E 2 ...)
# "noch …" Marker
NOCH_RE = re.compile(r"^\(?(noch)\s+", re.I)

# ─────────────────────────────────────────────────────────────────────────────
# Schema-Erkennung
# ─────────────────────────────────────────────────────────────────────────────

def detect_schema(tokens: List[Tuple[float, float, str]]) -> str:
    """
    Erkennt das Tabellenschema anhand der Tokens der ersten beiden Seiten.
    Reihenfolge ist wichtig: spezifischere Checks zuerst.
    """
    all_text = " ".join(t[2].lower() for t in tokens)

    # Schema A/A1: VO 1831/2003 – erkennbar an "zulassungsinhabers" / "inhabers"
    # "sungs-" entfernt: trifft zu breit (auch "Zusammensetzung"-Splits im 70524 Kokzidiostatika-PDF).
    # "zulassungs-" (mit Bindestrich) als spezifisches Zeilenumbruch-Artefakt von "Zulassungsinhabers".
    # Das muss VOR Schema C geprüft werden, da A1 auch "analysemethode" hat.
    has_inhaber = ("zulassungsinhabers" in all_text or "inhabers" in all_text
                   or "zulassungs-" in all_text)
    if has_inhaber:
        # A1 hat zusätzlich "analysemethode" als eigene Spalte + "charakterisierung"
        if ("analysemethode" in all_text and
                ("charakterisierung" in all_text or "zusammensetzung des zusatzstoffs" in all_text)):
            return "A1"
        # Sonderfall 70524 Kokzidiostatika: hat "Zulassungsinhaber"-Spalte (→ has_inhaber=True)
        # ABER ist eigentlich Schema C (hat "EG-Nr." + "chemische Bezeichnung" als Spalten).
        # Erkennbar: "eg-nr" im Text (als EG-Nr.-Spaltenheader) UND "chemische".
        # 1831-Schema-A-Dokumente haben kein "EG-Nr." als Spalte (nur "Kenn-nummer").
        if "eg-nr" in all_text and "chemische" in all_text:
            return "C"
        return "A"

    # Silierzusatzstoffe: eigenes Schema
    if "silierzusatzstoffe" in all_text or (
            "siliermittel" in all_text and "eg-nr" in all_text):
        return "S"

    # Schema C: RL 70/524 Technologie (Antioxidantien, Bindemittel, Emulgatoren …)
    # Hat "chemische bezeichnung" als Spalte, KEIN "analysemethode"-Inhaber-Block
    if ("chemische" in all_text and
            ("mindestgehalt" in all_text or "mindest-" in all_text) and
            "analysemethode" not in all_text):
        return "C"

    # Schema B: Aminosäuren, Vitamine (alt, RL 70/524 Nährstoffe)
    # B2: 70524-Format mit "nährsubstrat"/"charakteristika"-Spalten (kein min/max)
    if any(kw in all_text for kw in ["nährsubstrat", "charakteristika",
                                      "eg-nr", "reevaluier"]):
        # B2 hat keine "mindestgehalt"-Spalte, aber "nährsubstrat"
        if "nährsubstrat" in all_text:
            return "B2"
        return "B"

    # Fallback: Schema A
    return "A"


def get_cols_for_schema(schema: str) -> List[Tuple[str, float, float]]:
    if schema == "A":
        return SCHEMA_A_COLS
    elif schema == "A1":
        return SCHEMA_A1_COLS
    elif schema == "C":
        return SCHEMA_C_COLS
    elif schema == "B2":
        return SCHEMA_B2_COLS
    else:
        return SCHEMA_B_COLS


def is_kennnummer(text: str, schema: str) -> bool:
    t = text.strip()
    if schema in ("A", "A1"):
        return bool(KENN_A_RE.match(t))
    elif schema in ("C", "B", "B2"):
        return bool(KENN_C_RE.match(t))
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Dynamische Schema-C-Kalibrierung
# ─────────────────────────────────────────────────────────────────────────────

_C_ANCHORS = [
    ("kennnummer",   ["eg-nr", "eg-nr.", "nr."]),   # "nr." wird durch x-Filter in calibrate_schema_c abgesichert
    ("name",         ["zusatzstoff"]),
    ("chemisch",     ["chemische"]),
    ("tierart",      ["tierart"]),
    ("hoechstalter", ["höchstalter"]),
    ("min",          ["mindest"]),
    ("max",          ["höchst"]),
    ("sonstiges",    ["sonstige"]),
    ("geltung",      ["geltungsdauer"]),
    ("reevaluierung",["status", "reevaluier"]),
]


def calibrate_schema_c(tokens: List[Tuple[float, float, str]]) -> List[Tuple[str, float, float]]:
    """Kalibriert Schema-C-Spalten dynamisch aus den Header-Tokens."""
    anchor_x: Dict[str, float] = {}
    for x, _y, txt in tokens:
        tl = txt.lower().strip()
        for col_name, kws in _C_ANCHORS:
            if col_name not in anchor_x:
                if any(tl.startswith(kw) or kw in tl for kw in kws):
                    # Kennnummer-Anker: nur kurze Tokens (echte Spaltenköpfe wie "Nr.", "EG-Nr.")
                    # Verhindert, dass Lauftext wie "Nr. 2015/724" (12 Zeichen) als Anker dient.
                    if col_name == "kennnummer" and len(tl) > 10:
                        continue
                    anchor_x[col_name] = x

    if len(anchor_x) < 5:
        return SCHEMA_C_COLS  # Fallback

    ordered = sorted(anchor_x.items(), key=lambda kv: kv[1])
    col_xs = [v for _, v in ordered]
    cols: List[Tuple[str, float, float]] = []
    for i, (name, x) in enumerate(ordered):
        x0 = (col_xs[i - 1] + x) / 2 if i > 0 else max(0, x - 30)
        x1 = (x + col_xs[i + 1]) / 2 if i < len(ordered) - 1 else x + 100
        cols.append((name, round(x0, 1), round(x1, 1)))
    return cols


# ─────────────────────────────────────────────────────────────────────────────
# Dynamische Schema-A1-Kalibrierung (seitenweise)
# ─────────────────────────────────────────────────────────────────────────────

_A1_ANCHORS = [
    ("kennnummer",    ["kenn-", "kennnummer"]),
    ("inhaber",       ["inhabers", "sungs-", "zulassungsinhabers"]),
    ("name",          ["englischer name", "englischer", "[englischer",
                       "(handels"]),    # "(handelsbezeichnung)" / "(handelsbe-" / "(handelsbezeich-"
    ("zusammensetzung",["analyse", "zusammensetzung, chem", "beschreibung"]),
    ("tierart",       ["tierkategorie", "tierart"]),
    ("hoechstalter",  ["höchstalter"]),                         # nur Vollwort (nicht "höchst-", das kann auch Höchstgehalt sein)
    ("min",           ["mindestgehalt", "mindest-"]),
    ("max",           ["höchstgehalt", "höchstgeh-", "höchst-"]),  # "höchst-" = Zeilenumbruch von Höchstgehalt
    ("sonstiges",     ["sonstige bestimmungen", "sonstige"]),
    ("geltung",       ["geltungsdauer"]),
]

# PUA-Zeichen bereinigen (pdfminer-Artefakte aus Symbol-Fonts wie eckige Klammern)
_PUA_RE = re.compile(r"[\ue000-\uf8ff]")


def calibrate_schema_a1(
    tokens: List[Tuple[float, float, str]],
) -> Optional[List[Tuple[str, float, float]]]:
    """
    Kalibriert Schema-A1-Spalten aus Header-Tokens einer Seite.
    Gibt None zurück wenn zu wenige Anker gefunden.
    """
    anchor_x: Dict[str, float] = {}
    for x, y, txt in tokens:
        # PUA-Zeichen entfernen (z.B. \uf05b für '[')
        tl = _PUA_RE.sub("", txt).lower().strip()
        for col_name, kws in _A1_ANCHORS:
            if col_name not in anchor_x:
                if any(tl.startswith(kw) or tl == kw for kw in kws):
                    anchor_x[col_name] = x

    # "name" fehlt → aus inhaber + zusammensetzung interpolieren (z.B. bei verkürzten Headerzeilen)
    if "name" not in anchor_x and "inhaber" in anchor_x and "zusammensetzung" in anchor_x:
        gap = anchor_x["zusammensetzung"] - anchor_x["inhaber"]
        anchor_x["name"] = anchor_x["inhaber"] + gap * 0.35

    # "name" UND "inhaber" fehlen → name mittig zwischen kennnummer und zusammensetzung
    # (z.B. trennmittel: Header "Zusatzstoff" wird nicht erkannt, aber kenn + zusamm sind da)
    if ("name" not in anchor_x and "inhaber" not in anchor_x
            and "kennnummer" in anchor_x and "zusammensetzung" in anchor_x):
        gap = anchor_x["zusammensetzung"] - anchor_x["kennnummer"]
        anchor_x["name"] = anchor_x["kennnummer"] + gap * 0.50

    # Mindestens 6 Anker für zuverlässige Kalibrierung
    if len(anchor_x) < 6:
        return None

    # "max" fehlt → aus min + sonstiges interpolieren
    if "max" not in anchor_x and "min" in anchor_x and "sonstiges" in anchor_x:
        gap = anchor_x["sonstiges"] - anchor_x["min"]
        anchor_x["max"] = anchor_x["min"] + gap * 0.55

    if "max" not in anchor_x:
        return None

    ordered = sorted(anchor_x.items(), key=lambda kv: kv[1])
    col_xs = [v for _, v in ordered]
    cols: List[Tuple[str, float, float]] = []
    for i, (name, x) in enumerate(ordered):
        x0 = (col_xs[i - 1] + x) / 2 if i > 0 else max(0, x - 30)
        x1 = (x + col_xs[i + 1]) / 2 if i < len(ordered) - 1 else x + 120
        cols.append((name, round(x0, 1), round(x1, 1)))
    return cols

def _col_for_x(x: float, cols: List[Tuple[str, float, float]]) -> Optional[str]:
    for name, x0, x1 in cols:
        if x0 <= x < x1:
            return name
    return None


class PageData:
    """Hält alle Tokens einer PDF-Seite, klassifiziert nach Spalte."""

    def __init__(self, page_no: int, schema: str,
                 custom_cols: Optional[List[Tuple[str, float, float]]] = None):
        self.page_no = page_no
        self.schema  = schema
        self.cols    = custom_cols or get_cols_for_schema(schema)
        # tokens: List of (y0, x0, col_name, text)
        self.tokens: List[Tuple[float, float, str, str]] = []

    def add_token(self, x: float, y: float, text: str) -> None:
        col = _col_for_x(x, self.cols)
        if col is None:
            return
        self.tokens.append((y, x, col, text))

    def build_rows(self) -> List[Dict[str, str]]:
        """
        Gruppiert Tokens in Records anhand der Kennnummer-Spalte.
        Zwei-Pass-Ansatz:
          1. Alle Kennnummer-Tokens mit y-Position sammeln.
          2. Jeden Token der Row zuordnen, deren Kennnummer am nächsten
             unterhalb oder leicht oberhalb (≤ Y_ABOVE pt) liegt –
             aber nicht der übernächsten.
        """
        if not self.tokens:
            return []

        Y_ABOVE = 8.0   # Token darf bis zu 8pt oberhalb der Kennnummer liegen

        # Pass 1: Kennnummern extrahieren, sortiert top→bottom (y absteigend)
        kenn_list: List[Tuple[float, str]] = []  # (y, kenn_clean)
        # Aufgeteilte Name-Reste aus kombinierten Tokens
        extra_name_tokens: List[Tuple[float, float, str, str]] = []

        for y, x, col, text in self.tokens:
            # Schema C/B/B2: Kennnummer-Präfix auch aus der name-Spalte extrahieren.
            # Beispiel: "3.1 Canthaxanthin," liegt bei x=87.9 in der name-Spalte
            # (kalibr. Grenze ~83), ist aber tatsächlich eine Kennnummer + Name.
            if col == "name" and self.schema in ("C", "B", "B2"):
                t_n = text.strip()
                if not is_kennnummer(t_n, self.schema):
                    parts_n = t_n.split(None, 1)
                    if parts_n and is_kennnummer(parts_n[0], self.schema):
                        kenn_list.append((y, parts_n[0]))
                        # Originaler Token bleibt in self.tokens für _clean_name
                        # (mit Kennnummer-Präfix, der dort herausgestrichen wird)
                continue
            if col != "kennnummer":
                continue
            t = text.strip()
            # Manchmal kombiniert pdfminer Kennnummer+Name in einem Token:
            # "2a161bi  Lutein-/ Zeaxan-" oder "3.2.3.*  L-Lysin-"
            # → versuche Kennnummer am Anfang zu extrahieren
            # Bei Schema A1: Rest gehört zum Inhaber (nicht zum Produktnamen)
            if not is_kennnummer(t, self.schema) and not NOCH_RE.match(t):
                parts = t.split()
                for end in range(1, min(4, len(parts))):
                    candidate = " ".join(parts[:end])
                    if is_kennnummer(candidate, self.schema):
                        name_rest = " ".join(parts[end:]).strip()
                        t = candidate
                        if name_rest:
                            # A1: combined-Token enthält kenn+inhaber, nicht kenn+name
                            rest_col = "inhaber" if self.schema == "A1" else "name"
                            extra_name_tokens.append((y, x, rest_col, name_rest))
                        break
                else:
                    continue  # kein Kennnummer-Präfix gefunden
            if is_kennnummer(t, self.schema):
                kenn_list.append((y, t))
            elif NOCH_RE.match(t):
                clean = re.sub(r"^\(?\s*noch\s+", "", t, flags=re.I).rstrip(")").strip()
                kenn_list.append((y, clean))

        # Extra Name-Tokens in self.tokens injizieren
        if extra_name_tokens:
            self.tokens = self.tokens + extra_name_tokens

        if not kenn_list:
            return []

        # Gezielte Bereinigung: wenn ein "*"-Fußnotenmarker und eine echte Kennnummer
        # auf exakt gleicher y-Position liegen, entferne das "*".
        # Beispiel: "*" (x=57) neben "3.1 Canthaxanthin," (x=87) auf gleicher Zeile →
        # kenn_list enthält ("*", y=410.5) UND ("3.1", y=410.5) → entferne "*".
        # Wichtig: KEIN allgemeines Dedup – zwei echte Kennnummern bleiben immer beide.
        _y_has_real: set = {y_k for y_k, k in kenn_list if k != "*"}
        kenn_list = [(y_k, k) for y_k, k in kenn_list
                     if not (k == "*" and y_k in _y_has_real)]

        # Sortiere top→bottom (y descending)
        kenn_list.sort(key=lambda k: -k[0])

        # Grenzen: Row i bekommt Tokens von y_lower[i] bis y_upper[i]
        # y_upper[i] = kenn_list[i][0] + Y_ABOVE  (etwas oberhalb der Kennnummer)
        # y_lower[i] = kenn_list[i+1][0] + 0.1    (knapp über nächster Kennnummer)
        #            = 0 für letzte Row
        n = len(kenn_list)
        y_upper = [kenn_list[i][0] + Y_ABOVE for i in range(n)]
        y_lower = [kenn_list[i + 1][0] + 0.1 if i + 1 < n else 0.0 for i in range(n)]

        # Initialisiere Row-Dicts
        rows_data: List[Dict[str, List[str]]] = [
            {"kennnummer": [k]} for _, k in kenn_list
        ]

        # Pass 2: jeden Nicht-Kennnummer-Token der richtigen Row zuordnen
        # Sortiere top→bottom (y DESC), innerhalb gleicher Zeile links→rechts (x ASC).
        # Spalten-Bleed (z.B. "Zusammensetzung des Zusatzstoffs:" aus Zusammensetzungs-Spalte
        # in die Name-Spalte) wird in _clean_name durch den Bleed-Skip-Loop gefiltert.
        sorted_tokens = sorted(
            [(y, x, col, text) for y, x, col, text in self.tokens if col != "kennnummer"],
            key=lambda r: (-r[0], r[1])   # y DESC, x ASC
        )
        for y_tok, x_tok, col, text in sorted_tokens:

            for i in range(n):
                if y_lower[i] <= y_tok <= y_upper[i]:
                    rows_data[i].setdefault(col, []).append(text)
                    break

        # Zu String-Dicts zusammenführen
        rows = []
        for rd in rows_data:
            rows.append({k: "\n".join(v).strip() for k, v in rd.items()})
        return rows


def _collect_tokens(layout: Any, pd: PageData) -> None:
    for el in layout:
        if isinstance(el, LTTextBox):
            for line in el:
                if isinstance(line, LTTextLine):
                    t = line.get_text().strip()
                    if t:
                        pd.add_token(round(line.x0, 1), round(line.y0, 1), t)


# ─────────────────────────────────────────────────────────────────────────────
# PDF-Extraktion
# ─────────────────────────────────────────────────────────────────────────────

def extract_page_data(
    path: Path,
) -> Tuple[List[PageData], str]:
    """Liest PDF, erkennt Schema, gibt PageData-Liste zurück."""

    # Erste 2 Seiten für Schema-Erkennung vorab scannen
    raw_tokens: List[Tuple[float, float, str]] = []
    for pno, layout in enumerate(pm_extract_pages(str(path), laparams=LAPARAMS), 1):
        if pno > 2:
            break
        for el in layout:
            if isinstance(el, LTTextBox):
                for line in el:
                    if isinstance(line, LTTextLine):
                        t = line.get_text().strip()
                        if t:
                            raw_tokens.append((line.x0, line.y0, t))

    schema = detect_schema(raw_tokens)
    print(f"  → Schema {schema} erkannt")

    custom_cols: Optional[List[Tuple[str, float, float]]] = None
    if schema == "C":
        custom_cols = calibrate_schema_c(raw_tokens)
        if custom_cols != SCHEMA_C_COLS:
            print(f"  → Schema C kalibriert: {len(custom_cols)} Spalten, "
                  f"kenn={custom_cols[0][1]:.0f}–{custom_cols[0][2]:.0f}")
    elif schema == "A1":
        print(f"  → Schema A1 (VO 1831 Einzelzulassung): {len(SCHEMA_A1_COLS)} Spalten")

    pages: List[PageData] = []
    for page_no, layout in enumerate(pm_extract_pages(str(path), laparams=LAPARAMS), 1):
        # Schema A1: seitenweise Kalibrierung aus Header-Tokens
        page_cols = custom_cols
        if schema == "A1":
            page_tokens: List[Tuple[float, float, str]] = []
            for el in layout:
                if isinstance(el, LTTextBox):
                    for line in el:
                        if isinstance(line, LTTextLine):
                            t = line.get_text().strip()
                            if t:
                                page_tokens.append((line.x0, line.y0, t))
            cal = calibrate_schema_a1(page_tokens)
            if cal is not None:
                page_cols = cal
        pd = PageData(page_no, schema, page_cols)
        if schema == "A1" and page_cols is not None:
            # Tokens bereits gesammelt → direkt einfügen
            for x, y, t in page_tokens:
                pd.add_token(round(x, 1), round(y, 1), t)
        else:
            _collect_tokens(layout, pd)
        pages.append(pd)

    return pages, schema


# ─────────────────────────────────────────────────────────────────────────────
# Name-Bereinigung
# ─────────────────────────────────────────────────────────────────────────────

# Muster die einen Namen-Stop markieren (nur innerhalb des Textes, nicht am Anfang)
_NAME_INNER_STOP_RE = re.compile(
    r"^(Zusammensetzung|Analysemethode|Charakterisierung|-{3,})",
    re.I | re.M,
)


def _clean_name(raw: str) -> Optional[str]:
    """
    Bereinigt den Rohtext aus der name-Spalte zum echten Produktnamen.
    Strategie:
      1. Zeilen sammeln bis zum ersten Stop-Marker
         (Stop: Zusammensetzung, Analysemethode, Charakterisierung, ---)
         NICHT gestoppt durch "Zubereitung aus" (das kann selbst der Name sein)
      2. Bindestrich-Zeilenenden zusammenführen
      3. Englische Namen in [] entfernen
    """
    if not raw:
        return None

    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    if not lines:
        return None

    # Schema C/B/B2: Kennnummer-Präfix von der ersten Zeile entfernen
    # z.B. "3.1 Canthaxanthin," → "Canthaxanthin,"
    _kenn_c_pfx = re.match(r"^(\d+\.\d+(?:\.\d+)*\*?\s+)(.*)", lines[0], re.S)
    if _kenn_c_pfx and _kenn_c_pfx.group(2).strip():
        lines[0] = _kenn_c_pfx.group(2).strip()

    # Führende Bleed-Zeilen überspringen:
    # "Zusammensetzung des Zusatzstoffs:" kann durch Spaltenüberlauf als erste Zeile
    # in der name-Spalte auftauchen (echter Name folgt danach).
    # Alle bekannten Stop-Marker am Anfang entfernen, bis echter Namenstext kommt.
    _leading_stop = re.compile(
        r"^(Zusammensetzung\s+des|Analysemethode|Charakterisierung|-{3,})",
        re.I,
    )
    while lines and _leading_stop.match(lines[0]):
        lines.pop(0)
    if not lines:
        return None

    # Zeilen bis zum Stop-Marker sammeln
    # Englische Namen in [...] vollständig überspringen (auch mehrzeilig)
    parts: List[str] = []
    in_english_block = False
    seen_english_block = False  # nach erstem []-Block stoppen wir
    for line in lines:
        if _NAME_INNER_STOP_RE.match(line):
            break
        # Einzelne Gedankenstriche überspringen (Tabellenfüller)
        if line in ("—", "–", "-"):
            continue
        # Beschreibungstext nach dem eigentlichen Namen stoppen:
        # 1. Zeile beginnt mit Artikel/Hilfsverb: "das in …", "die als …", "wird aus …"
        # 2. Zeile enthält "wird als" (z.B. "Ponceau 4R wird als Stoff beschrieben")
        # 3. Zeile beginnt mit "beschrieben" (Fortsetzung einer Beschreibung)
        if parts and (
            re.match(r"^(das\s|die\s|der\s|ein\s|eine\s|wird\s|ist\s|sind\s|beschrieben)", line, re.I)
            or re.search(r"\bwird\s+als\b", line, re.I)
        ):
            # Sonderfall: "PRÄFIX wird als Stoff …" – Präfix kann kompletterer Name sein
            # z.B. parts=["Ponceau"], line="Ponceau 4R wird als Stoff …" → Präfix="Ponceau 4R"
            _wm = re.match(r"^(.*?)\s+wird\s+als\b", line, re.I)
            if _wm:
                _pfx = _wm.group(1).strip()
                if _pfx and len(_pfx) > len(" ".join(parts)):
                    parts[:] = [_pfx]   # in-place ersetzen damit die Variable erhalten bleibt
            break
        # Englischen Namen in [] überspringen – block beginnt mit [ oder \uf05b
        if re.match(r"^[\[\uf05b]", line):
            in_english_block = True
            seen_english_block = True
        if in_english_block:
            # Block endet wenn ] oder \uf05d in der Zeile vorkommt
            if re.search(r"[\]\uf05d]", line):
                in_english_block = False
            continue
        # Nach einem abgeschlossenen englischen Block: stoppen
        # (restliche Zeilen sind oft Wiederholungen aus dem PDF-Layout)
        # Nur wenn bereits echter Namenstext gesammelt – falls Englisch zuerst erscheint,
        # soll der deutsche Name danach noch aufgenommen werden können.
        if seen_english_block and not in_english_block and parts:
            break
        parts.append(line)

    if not parts:
        return None

    # Zeilen zusammenführen: Bindestrich-Ende → direkt verbinden, sonst Leerzeichen
    joined = parts[0]
    for part in parts[1:]:
        # Bindestrich am Ende der vorherigen Zeile (auch mit Leerzeichen davor: "L-Lysin- ")
        prev = joined.rstrip()
        if prev.endswith("-"):
            # Direkt zusammenführen, dabei evtl. Leerzeichen vor dem Bindestrich entfernen
            joined = prev + part.lstrip()
        elif prev.endswith(","):
            joined = prev + " " + part
        else:
            joined = prev + " " + part

    text = joined.strip()

    # Leerzeichen nach Bindestrich entfernen (PDF-Zeilenumbruch-Artefakt: "L-Lysin- Mono-")
    text = re.sub(r"-\s+([A-ZÄÖÜ])", lambda m: "-" + m.group(1), text)
    text = re.sub(r"-\s+([a-zäöü])", lambda m: "-" + m.group(1), text)

    # Englischen Namen in eckigen Klammern entfernen
    # Auch Unicode-Varianten =[  =] (aus Symbol-Schriftarten)
    text = re.sub(r"\s*[\[\uf05b].*?[\]\uf05d]", "", text, flags=re.S).strip()
    # Reste ohne öffnende Klammer: "… mate]", "… chelate]", "… octahydrate]"
    text = re.sub(r"\s+\S{3,15}[\]\uf05d]\s*$", "", text).strip()
    # Rest-Klammern am Ende entfernen
    text = re.sub(r"[\]\uf05d]\s*$", "", text).strip()

    # Handelsbezeichnung in runden Klammern (am Zeilenende) entfernen
    text = re.sub(r"\s*\([A-Z][^)]{3,}\)\s*$", "", text).strip()

    # Artefakte: "oder E 312 Alle Futtermittel"
    if re.search(r"\b(Alle\s+Futtermittel|Tierkategorie|Mindest|Höchst)\b", text, re.I):
        return None

    # Restliche Trennlinien entfernen
    text = re.sub(r"-{3,}", "", text).strip()

    # Trailing Komma entfernen
    text = text.rstrip(",").strip()

    # Führende Aufzählungszeichen entfernen: "— L-Lysin" → "L-Lysin"
    text = re.sub(r"^[—–\-]\s+", "", text).strip()

    # Englische Begriffe am Ende abschneiden (nach einem deutschen Hauptnamen)
    # Muster: "Kaliumdiformiat [Potassium diformate]" → "Kaliumdiformiat"
    # Bereits durch Klammer-Regex oben behandelt.
    # Aber: "Ammoniumchlorid ammonium chlori-de" → Unicode-Reste
    # Bereinige alle ... Reste (Unicode-Klammern)
    text = re.sub(r"\s*\uf05b.*?\uf05d", "", text, flags=re.S).strip()
    text = re.sub(r"\s*\uf05b.*$", "", text, flags=re.S).strip()  # unclosed

    return text if len(text) >= 3 else None


# ─────────────────────────────────────────────────────────────────────────────
# Zahl-Extraktion
# ─────────────────────────────────────────────────────────────────────────────

_NUM_RE = re.compile(r"\b(\d[\d\s]*(?:[.,]\d+)?)\s*(?:×\s*10\^?(\d+))?\b")

# Fußnoten-Ziffern direkt an Zahlen (z.B. "120003)" = 12000 mit Fußnote 3)
_FOOTNOTE_RE = re.compile(r"(\d+)([1-9]\))")


def _strip_footnotes(text: str) -> str:
    """Entfernt angehängte Fußnoten-Ziffern: '120003)' → '12000'."""
    return _FOOTNOTE_RE.sub(lambda m: m.group(1), text)


def _extract_numbers(text: Optional[str]) -> List[float]:
    """
    Extrahiert Zahlen aus Spaltentext.
    Ignoriert:
    - Listenaufzählungen ("2. Der Gehalt…" → kein Wert)
    - Fußnoten-Anhänge ("120003)" → 12000)
    - Sehr große Zahlen die wahrscheinlich Artefakte sind (> 500000)
    """
    if not text:
        return []
    # Fußnoten-Ziffern entfernen bevor wir parsen
    text = _strip_footnotes(text)
    # Listenaufzählungen am Zeilenanfang ignorieren ("1. ", "2. ", etc.)
    text = re.sub(r"^\d+\.\s", " ", text, flags=re.M)
    nums = []
    for m in _NUM_RE.finditer(text):
        base_str = m.group(1).replace(" ", "").replace(",", ".")
        try:
            val = float(base_str)
        except ValueError:
            continue
        exp = m.group(2)
        if exp:
            val *= 10 ** int(exp)
        # Artefakt-Filter: unrealistisch große Werte ignorieren
        if val > 200_000:
            continue
        nums.append(val)
    return nums


# ─────────────────────────────────────────────────────────────────────────────
# Geltungsdatum-Parsing
# ─────────────────────────────────────────────────────────────────────────────

_DATE_RE    = re.compile(r"(\d{2}\.\d{2}\.\d{4})")
_RL_RE      = re.compile(
    r"(?:VO|DVO|Verordnung)\s*\(?(?:EU|EG|EWG)\)?\s*(?:Nr\.)?\s*([\d/]+)",
    re.I,
)


def _parse_geltung(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    m = _DATE_RE.search(text)
    return m.group(1) if m else None


def _parse_rl(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    m = _RL_RE.search(text)
    return m.group(0).strip() if m else None


# ─────────────────────────────────────────────────────────────────────────────
# Header-Erkennung
# ─────────────────────────────────────────────────────────────────────────────

_HEADER_WORDS = {
    "kennnummer", "kennnummern", "kennzahl", "zusatzstoffs", "zusatzstoff",
    "zulassungsinhabers", "zusammensetzung", "chemische", "tierart",
    "höchstalter", "mindestgehalt", "höchstgehalt", "sonstige",
    "geltungsdauer", "rechtsgrundlage", "analysemethode",
    "eg-nr", "nummer", "mg/kg", "kbe/kg",
}

_VERSION_RE = re.compile(r"^vers\.\s*\d+", re.I)


def _is_header_row(row: Dict[str, str]) -> bool:
    kenn = row.get("kennnummer", "").lower().strip()
    if kenn in _HEADER_WORDS or kenn.startswith("kenn"):
        return True
    # "Vers. 13", "Vers. 78" etc.
    if _VERSION_RE.match(kenn):
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Row → Record
# ─────────────────────────────────────────────────────────────────────────────

def _row_to_record(
    row: Dict[str, str],
    schema: str,
    source_file: str,
    source_page: int,
) -> Optional[Dict[str, Any]]:

    kenn_raw = row.get("kennnummer", "").strip()
    kenn_first = kenn_raw.splitlines()[0].strip()

    # "noch …" und "(noch …)" → echte Kennnummer extrahieren
    kenn_first = re.sub(r"^\(?\s*noch\s+", "", kenn_first, flags=re.I).rstrip(")")
    kenn_clean = kenn_first.strip()

    if not kenn_clean or kenn_clean == "*":
        return None

    # Name aus name-Spalte bereinigen
    name_raw = row.get("name", "")
    name = _clean_name(name_raw)

    # Fallback 1: name_en-Spalte (englischer Name / Handelsbezeichnung) → noch kein Name
    if not name and schema in ("A", "A1"):
        name_en = row.get("name_en", "")
        if name_en:
            candidate = _clean_name(name_en)
            if candidate and len(candidate) >= 4:
                name = candidate

    # Fallback 2: erste sinnvolle Zeilen der zusammensetzung-Spalte (mit Bindestrich-Join)
    if not name and schema in ("A", "A1"):
        zusatz = row.get("zusammensetzung", "")
        # Zeilen bis zum Stop-Marker sammeln und mit Bindestrich-Join verbinden
        parts: List[str] = []
        for line in zusatz.splitlines():
            line = line.strip()
            if not line:
                continue
            # Stop-Marker: ab hier beginnt Zusammensetzungs-Text
            if re.match(r"(Zusammensetzung|Zubereitung|Analysemethode|Charakterisierung|-{3}|\[)", line, re.I):
                break
            # Unicode-Klammern: englischer Name → Stop
            if "\uf05b" in line:
                break
            parts.append(line)
        if parts:
            # Bindestrich-Join
            joined = parts[0]
            for p in parts[1:]:
                if joined.endswith("-"):
                    joined = joined + p
                else:
                    joined = joined + " " + p
            candidate = _clean_name(joined)
            if candidate and len(candidate) >= 4:
                name = candidate

    # Tierart
    tier_raw = row.get("tierart", "")
    # Bei B2 enthält die Tierart-Spalte oft kombinierte Tokens mit Sonderbestimmungen:
    # "Alle Tierarten  Angabe auf Etikett oder..." → nur Teil vor "Angabe"/"−"
    if schema == "B2" and tier_raw:
        tier_lines = []
        for line in tier_raw.splitlines():
            line = line.strip()
            if re.match(r"^(Angabe|−|–|Bezeichnung|Gehalt|Anerkennung)", line, re.I):
                break
            # Trenne bei Doppelspace (pdfminer-Zeichen für Spaltenübergang)
            if "  " in line:
                line = line.split("  ")[0].strip()
            if line:
                tier_lines.append(line)
        tier_raw = "\n".join(tier_lines)
    tier = tier_raw.strip() or None

    # Min / Max
    min_col = row.get("min", "")
    max_col = row.get("max", "")

    def _parse_dose_col(col_text: str) -> Optional[float]:
        """
        Extrahiert den Dosiswert aus einer Min/Max-Spalte.
        - "100"                  → 100
        - "3 000 mg Fe/kg"       → 3000
        - "100: allein oder …"   → 100  (Teil vor Doppelpunkt)
        - "—\n150"               → 150  (erste Zeile mit Zahl)
        - "1. In der Gebrauchsanweisung…"  → None  (Listentext)
        Ignoriert Fußnoten, Fließtext und E-Nummern.
        """
        if not col_text:
            return None

        # Fließtext-Indikatoren: Wenn die erste nicht-leere Zeile so anfängt → None
        _FLIESSTEXT_RE = re.compile(
            r"^(In\s+der|Der\s+|Die\s+|Das\s+|Zus[äa]tz|Vormi|Futter|gemäß|Lager|"
            r"zusammen|allein|oder\s+E\s|die\s+Mischung|Für\s+|Bei\s+)",
            re.I,
        )

        lines = col_text.splitlines()
        for raw_line in lines:
            line = raw_line.strip()
            if not line or line in ("—", "-", "–", "—\n"):
                continue
            # Listenaufzählung "1. …" / "1.Text" → Sonstiges-Text, abbrechen
            if re.match(r"^\d+\.", line):
                break
            # Fließtext-Zeilen überspringen
            if _FLIESSTEXT_RE.match(line):
                continue
            # E-Nummern-Zeilen (Schema C: "zusammen mit E 311") überspringen
            if re.search(r"\bE\s+\d{3}", line):
                continue
            # "%" ohne vorangehende Zahl: "12 %" aus Header → überspringen
            # Aber "3 000 mg/kg Alleinfuttermittel" enthält kein %
            if re.match(r"^\d+\s*%", line):
                continue
            # Doppelpunkt: "100: allein oder…" → nur Teil vor Doppelpunkt
            if ":" in line:
                candidate = line.split(":")[0].strip()
                nums = _extract_numbers(candidate)
                if nums:
                    return nums[0]
                # kein Wert vor ":" → ganze Zeile versuchen (z.B. "mg Fe/kg: 40")
            nums = _extract_numbers(line)
            if nums:
                return nums[0]
        return None

    min_val = _parse_dose_col(min_col)
    max_val = _parse_dose_col(max_col)

    # Höchstalter
    # Format: "6 Wochen", "12 Monate", "6 Wochen ab…", "—", etc.
    # Extrahiert nur die Zahl in Tagen normalisiert (z.B. "6 Wochen" → 42)
    hoechstalter_col = row.get("hoechstalter", "")
    hoechstalter_age = None
    if hoechstalter_col:
        def _parse_hoechstalter(text: str) -> Optional[float]:
            """
            Extrahiert Alter aus "X Wochen", "X Monate", "X Tage" etc.
            Rückgabe: Alter in Tagen (float) oder None
            Format-Beispiele:
            - "6 Wochen" → 42.0
            - "12 Monate" → 365.0
            - "6 Wochen ab…" → 42.0
            - "—" → None
            """
            if not text or text.strip() in ("—", "-", "–"):
                return None
            lines = text.splitlines()
            for line in lines:
                line = line.strip()
                if not line or line in ("—", "-", "–"):
                    continue
                # Zahlen und Einheit extrahieren: "6 Wochen" → (6, "wochen")
                m = re.search(r'(\d+(?:\s+\d{3})*(?:[.,]\d+)?)\s*(wochen?|monate?|tage?|jahre?|tag|woche|monat|jahr)', line, re.I)
                if m:
                    num_str = m.group(1).replace(" ", "")  # "1 000" → "1000"
                    unit = m.group(2).lower()
                    try:
                        num = float(num_str.replace(",", "."))
                        # Konvertierung zu Tagen
                        if "tag" in unit:
                            return num
                        elif "woche" in unit:
                            return num * 7
                        elif "monat" in unit:
                            return num * 30.5
                        elif "jahr" in unit:
                            return num * 365
                    except ValueError:
                        continue
            return None
        hoechstalter_age = _parse_hoechstalter(hoechstalter_col)

    # Geltung / Rechtsgrundlage
    gelt_col = row.get("geltung", "")
    geltung  = _parse_geltung(gelt_col)
    rl       = _parse_rl(gelt_col)

    return {
        "kennnummer":       kenn_clean,
        "schema":           schema,
        "name":             name or "",
        "tierarten":        tier,
        "hoechstalter_tage": hoechstalter_age,  # Alter in Tagen
        "min_mg_kg":        min_val,
        "max_mg_kg":        max_val,
        "charakteristika":  row.get("zusammensetzung", row.get("chemisch", "")).strip() or None,
        "geltung_bis":      geltung,
        "rechtsgrundlage":  rl,
        "source_file":      source_file,
        "source_page":      source_page,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Silierzusatzstoffe-Parser (Schema S)
# ─────────────────────────────────────────────────────────────────────────────

_ENZYM_RE = re.compile(
    r"(alpha|endo|beta|exo|glucan|xylan|cellul|amylas|proteas|lactas|phosphat|"
    r"bacillus|lactobacillus|enterococcus|saccharomyces|aspergillus|trichoderma|"
    r"pediococcus|streptococcus|lactococcus|propionibacterium|lactiplantibacillus)",
    re.I,
)


def _parse_silier_pdf(
    path: Path, pages: List[PageData]
) -> List[Dict[str, Any]]:
    records = []
    seen: set = set()
    counter = 0
    cols = get_cols_for_schema("A")  # Näherung für Freitext-Spalten

    for pd in pages:
        sorted_tok = sorted(pd.tokens, key=lambda t: (-t[0], t[1]))
        for y, x, col, text in sorted_tok:
            if x < 80 or x > 570:
                continue
            if not _ENZYM_RE.search(text):
                continue
            name = text.strip()
            if len(name) < 8 or name in seen:
                continue
            seen.add(name)
            counter += 1
            records.append({
                "kennnummer":       f"S{counter:03d}",
                "schema":           "S",
                "name":             name,
                "tierarten":        None,
                "hoechstalter_tage": None,
                "min_mg_kg":        None,
                "max_mg_kg":        None,
                "charakteristika":  None,
                "geltung_bis":      None,
                "rechtsgrundlage":  None,
                "source_file":      path.name,
                "source_page":     pd.page_no,
            })
    return records


# ─────────────────────────────────────────────────────────────────────────────
# Hauptparser
# ─────────────────────────────────────────────────────────────────────────────

def parse_pdf(path: Path) -> List[Dict[str, Any]]:
    pages, schema = extract_page_data(path)
    if not pages:
        return []

    if schema == "S":
        return _parse_silier_pdf(path, pages)

    raw_records: List[Dict[str, Any]] = []
    for pd in pages:
        rows = pd.build_rows()
        for row in rows:
            try:
                if _is_header_row(row):
                    continue
                rec = _row_to_record(row, schema, path.name, pd.page_no)
                if rec:
                    raw_records.append(rec)
            except Exception as exc:
                print(f"  [WARN] {path.name} S.{pd.page_no}: {exc}")

    print(f"  → {len(raw_records)} Rohdatensätze")
    return raw_records


# ─────────────────────────────────────────────────────────────────────────────
# Merge: mehrere Tierarten-Zeilen zu einem Record zusammenführen
# ─────────────────────────────────────────────────────────────────────────────

def merge_records(recs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Fasst Records mit gleicher Kennnummer zusammen.
    Tierarten werden zu einer Liste, min/max/geltung aus erstem Datensatz.
    """
    merged: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []

    for rec in recs:
        k = rec["kennnummer"]
        if k not in merged:
            merged[k] = {**rec, "tierarten": []}
            order.append(k)
        # Tierart anhängen (falls nicht schon vorhanden)
        tier = rec.get("tierarten")
        if tier and tier not in merged[k]["tierarten"]:
            merged[k]["tierarten"].append(tier)
        # Geltung aus nicht-None bevorzugen
        if not merged[k]["geltung_bis"] and rec.get("geltung_bis"):
            merged[k]["geltung_bis"] = rec["geltung_bis"]
        if not merged[k]["rechtsgrundlage"] and rec.get("rechtsgrundlage"):
            merged[k]["rechtsgrundlage"] = rec["rechtsgrundlage"]

    result = []
    for k in order:
        r = merged[k]
        # Tierarten-Liste → String
        r["tierarten"] = "; ".join(r["tierarten"]) if r["tierarten"] else None
        result.append(r)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Kategorisierung der Tierarten
# ─────────────────────────────────────────────────────────────────────────────

def categorize_records(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Fügt tierart_kategorie und tierart_spezifisch zu jedem Record hinzu."""

    TIERART_CATEGORIES = {
        'alle tierarten': 'Alle Tierarten',
        'alle tierkategorien': 'Alle Tierarten',
        'mastschwein': 'Schweine',
        'zuchtsau': 'Schweine',
        'ferkel': 'Schweine',
        'schwein': 'Schweine',
        'sau': 'Schweine',
        'milchkuh': 'Rinder',
        'wiederkäuer': 'Rinder',
        'mastkalb': 'Rinder',
        'mastrin': 'Rinder',
        'kälber': 'Rinder',
        'kalb': 'Rinder',
        'rind': 'Rinder',
        'wiederkä': 'Rinder',
        'kuh': 'Rinder',
        'bulle': 'Rinder',
        'masttruthühner': 'Geflügel',
        'mastgeflügel': 'Geflügel',
        'legehennen': 'Geflügel',
        'masthühner': 'Geflügel',
        'truthühn': 'Geflügel',
        'truthahn': 'Geflügel',
        'legehuh': 'Geflügel',
        'masthuh': 'Geflügel',
        'junghen': 'Geflügel',
        'geflüg': 'Geflügel',
        'geflügel': 'Geflügel',
        'ziervog': 'Geflügel',
        'vogel': 'Geflügel',
        'ente': 'Geflügel',
        'gans': 'Geflügel',
        'huhn': 'Geflügel',
        'henne': 'Geflügel',
        'lege': 'Geflügel',
        'zierfisch': 'Fische/Krebstiere',
        'forelle': 'Fische/Krebstiere',
        'garnele': 'Fische/Krebstiere',
        'fisch': 'Fische/Krebstiere',
        'fische': 'Fische/Krebstiere',
        'krebs': 'Fische/Krebstiere',
        'lachs': 'Fische/Krebstiere',
        'kaninchen': 'Heimtiere',
        'katze': 'Heimtiere',
        'hund': 'Heimtiere',
        'pferd': 'Pferde/Equiden',
        'pony': 'Pferde/Equiden',
        'esel': 'Pferde/Equiden',
        'equiden': 'Pferde/Equiden',
        'schaf': 'Schafe/Ziegen',
        'lamm': 'Schafe/Ziegen',
        'ziege': 'Schafe/Ziegen',
        'bock': 'Schafe/Ziegen',
    }

    for record in data:
        tierart = record.get('tierarten')

        # Kategorisierung
        if not tierart:
            record['tierart_kategorie'] = None
            record['tierart_spezifisch'] = False
        else:
            tierart_lower = tierart.lower().strip()

            # "Alle Tierarten" Varianten
            if 'alle tierart' in tierart_lower:
                record['tierart_kategorie'] = 'Alle Tierarten'
                record['tierart_spezifisch'] = 'außer' in tierart_lower  # True wenn "außer" Filter
            else:
                # Längere Matches zuerst
                kategorie_found = None
                for key, category in sorted(TIERART_CATEGORIES.items(), key=lambda x: -len(x[0])):
                    if key in tierart_lower or tierart_lower.startswith(key):
                        kategorie_found = category
                        break

                if kategorie_found:
                    record['tierart_kategorie'] = kategorie_found
                    record['tierart_spezifisch'] = kategorie_found != 'Alle Tierarten'
                else:
                    record['tierart_kategorie'] = 'Sonstige'
                    record['tierart_spezifisch'] = True

    return data


# ─────────────────────────────────────────────────────────────────────────────
# Qualitätsprüfung
# ─────────────────────────────────────────────────────────────────────────────

def check_quality(data: List[Dict[str, Any]]) -> None:
    total   = len(data)
    if total == 0:
        print("Qualität: 0 Records – nichts zu prüfen.")
        return
    ok_name = sum(1 for r in data if r["name"])
    ok_tier = sum(1 for r in data if r["tierarten"])
    ok_max  = sum(1 for r in data if r["max_mg_kg"])
    ok_gel  = sum(1 for r in data if r["geltung_bis"])
    ok_cat  = sum(1 for r in data if r.get("tierart_kategorie"))
    ok_spez = sum(1 for r in data if r.get("tierart_spezifisch"))
    empty_names = [r for r in data if not r["name"]]

    print(f"\n{'='*60}")
    print(f"Qualität: {total} Records gesamt")
    print(f"  Name vorhanden:          {ok_name}/{total}  ({100*ok_name//total}%)")
    print(f"  Tierart vorhanden:       {ok_tier}/{total}  ({100*ok_tier//total}%)")
    print(f"  Max vorhanden:           {ok_max}/{total}   ({100*ok_max//total}%)")
    print(f"  Geltung vorhanden:       {ok_gel}/{total}  ({100*ok_gel//total}%)")
    print(f"  Kategorie vorhanden:     {ok_cat}/{total}  ({100*ok_cat//total}%)")
    print(f"  Artspezifisch:           {ok_spez}/{total}  ({100*ok_spez//total}%)")

    # Kategorie-Verteilung
    categories = {}
    for r in data:
        cat = r.get("tierart_kategorie")
        if cat:
            categories[cat] = categories.get(cat, 0) + 1
    if categories:
        print(f"\n  Kategorien:")
        for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
            print(f"    {cat:20s}: {count:3d}")

    if empty_names:
        print(f"\n  Leere Namen ({len(empty_names)}):")
        for r in empty_names[:20]:
            print(f"    {r['kennnummer']:<12} {r['source_file'][:55]}")


# ─────────────────────────────────────────────────────────────────────────────
# Hauptprogramm
# ─────────────────────────────────────────────────────────────────────────────

def main(pdf_dir: Path = PDF_DIR) -> None:
    pdfs = sorted(pdf_dir.glob("*.pdf"))

    if not pdfs:
        print("Keine PDFs gefunden.")
        return

    all_records: List[Dict[str, Any]] = []
    for pdf in pdfs:
        print(f"\n[PARSE] {pdf.name}")
        try:
            recs = parse_pdf(pdf)
            all_records.extend(recs)
        except Exception as exc:
            print(f"  [ERROR] {exc}")

    merged = merge_records(all_records)

    # Kategorisierung hinzufügen
    merged = categorize_records(merged)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    print(f"\n→ {len(merged)} Records gespeichert in {OUT_JSON}")

    check_quality(merged)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-dir", type=Path, default=PDF_DIR,
                    help="Verzeichnis mit BVL-PDFs")
    args = ap.parse_args()
    main(args.pdf_dir)
