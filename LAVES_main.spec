# -*- mode: python ; coding: utf-8 -*-
#
# LAVES_main.spec – builds LAVES.exe (main application)
# ======================================================
#
# Expected deployment layout after building BOTH spec files:
#
#   <install>/
#   ├── LAVES.exe                  ← this build
#   ├── _internal/                 ← PyInstaller support files (onedir)
#   └── Data/
#       ├── laves_toast_qt.exe     ← copy from: dist/laves_toast_qt.exe
#       └── zusatzstoffe.json      ← copy from: Data/zusatzstoffe.json (initial)
#
# zusatzstoffe.json is NOT bundled inside the exe; it lives on disk in Data/ so
# that laves_toast_qt.exe can update it at runtime without touching the exe.
#
# Build
# -----
#   pip install -r requirements.txt
#   pyinstaller LAVES_main.spec
#
# Output:  dist/LAVES/LAVES.exe  (plus _internal/ next to it)

from PyInstaller.building.api import PYZ, EXE, COLLECT
from PyInstaller.building.build_main import Analysis

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    # No datas: zusatzstoffe.json is NOT bundled.
    # It must be placed manually in <install>/Data/ before first run.
    datas=[],
    hiddenimports=[
        # PySide6 plugins that PyInstaller may not auto-detect
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "PySide6.QtPrintSupport",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,     # --onedir: Qt DLLs live alongside the exe
    name="LAVES",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,             # GUI application – no console window on Windows
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="LAVES",              # output directory: dist/LAVES/
)
