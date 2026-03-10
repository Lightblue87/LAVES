# -*- mode: python ; coding: utf-8 -*-
#
# LAVES_updater.spec – builds laves_toast_qt.exe (updater)
# =========================================================
#
# Bundles laves_toast_qt.py + laves_updater_v6.py into a single executable.
# zusatzstoffe.json is NOT bundled – the updater downloads fresh PDFs from
# BVL and writes the JSON to Data/zusatzstoffe.json next to the exe at runtime.
#
# Expected location after deployment:
#   <install>/Data/laves_toast_qt.exe
#
# The exe detects that its parent directory is named "Data", escapes one level
# up to the project root, and resolves all paths from there:
#   BASE_DIR  = <install>/
#   DATA_DIR  = <install>/Data/
#   PDF_DIR   = <install>/Data/_bvl_pdfs/
#   OUT_JSON  = <install>/Data/zusatzstoffe.json
#
# Build
# -----
#   pip install -r requirements.txt
#   pyinstaller LAVES_updater.spec
#
# Output:  dist/laves_toast_qt.exe  (single self-contained file)
# Deploy:  copy dist/laves_toast_qt.exe  →  <install>/Data/laves_toast_qt.exe

from PyInstaller.building.api import PYZ, EXE
from PyInstaller.building.build_main import Analysis

a = Analysis(
    ["Data/laves_toast_qt.py"],
    # Add Data/ to the search path so that "import laves_updater_v6" resolves
    # at build time (laves_updater_v6.py sits next to laves_toast_qt.py).
    pathex=["Data"],
    binaries=[],
    # No datas: zusatzstoffe.json is written by the updater at runtime.
    datas=[],
    hiddenimports=[
        # laves_updater_v6 is imported at module level in laves_toast_qt.py so
        # PyInstaller normally finds it via static analysis; listed here as a
        # safety net in case the import is obscured.
        "laves_updater_v6",
        # PySide6 plugins
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        # pdfminer sub-modules (not always auto-detected by PyInstaller)
        "pdfminer.high_level",
        "pdfminer.layout",
        "pdfminer.converter",
        "pdfminer.pdfpage",
        "pdfminer.pdfinterp",
        "pdfminer.pdfdocument",
        "pdfminer.pdfparser",
        "pdfminer.cmapdb",
        "pdfminer.encodingdb",
        "pdfminer.fontmetrics",
        # requests + urllib3 (used for PDF download)
        "requests",
        "urllib3",
        "urllib3.util.retry",
        "requests.adapters",
        "charset_normalizer",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

# --onefile: everything embedded in one binary, easy to place in Data/
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="laves_toast_qt",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,             # GUI application – no console window on Windows
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
