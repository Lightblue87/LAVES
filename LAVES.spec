# -*- mode: python ; coding: utf-8 -*-
#
# LAVES – PyInstaller build spec
# ================================
# Produces a ready-to-deploy directory tree under dist/LAVES/:
#
#   dist/LAVES/
#   ├── LAVES.exe                      (main application, --onedir)
#   ├── Data/
#   │   ├── laves_toast_qt.exe         (updater, --onefile single binary)
#   │   └── zusatzstoffe.json          (additive database)
#   └── <PySide6 / Qt DLLs …>
#
# LAVES.exe reads  Data/zusatzstoffe.json at startup.
# laves_toast_qt.exe (placed inside Data/) detects that its parent directory is
# named "Data", escapes one level up to the project root, and writes the
# refreshed JSON to Data/zusatzstoffe.json so LAVES.exe picks it up on reload.
#
# Build
# -----
#   pip install -r requirements.txt
#   pyinstaller LAVES.spec
#
# After the build, copy the updater single-file exe into the output tree:
#   Windows:  copy dist\laves_toast_qt\laves_toast_qt.exe dist\LAVES\Data\
#   macOS/Linux: cp dist/laves_toast_qt/laves_toast_qt dist/LAVES/Data/

from PyInstaller.building.api import PYZ, EXE, COLLECT
from PyInstaller.building.build_main import Analysis

# ── Shared hidden imports ────────────────────────────────────────────────────
HIDDEN = [
    # PySide6 – ensure plugins/platforms are pulled in
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    # pdfminer sub-modules (not always auto-detected)
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
    # requests + urllib3
    "requests",
    "urllib3",
    "urllib3.util.retry",
    "requests.adapters",
    "charset_normalizer",
]

# ============================================================================
# 1.  laves_toast_qt  (updater)
#     Built as --onefile so it is a single binary that lives in Data/.
#     laves_updater_v6 is imported at module level, so PyInstaller finds it
#     automatically; it is also listed as a hidden import for safety.
# ============================================================================
toast_a = Analysis(
    ["Data/laves_toast_qt.py"],
    pathex=["Data"],           # ensures "import laves_updater_v6" resolves
    binaries=[],
    datas=[],                  # updater writes the JSON; no need to bundle it
    hiddenimports=HIDDEN + ["laves_updater_v6"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

toast_pyz = PYZ(toast_a.pure)

# --onefile: all binaries/datas embedded in the exe itself
toast_exe = EXE(
    toast_pyz,
    toast_a.scripts,
    toast_a.binaries,
    toast_a.zipfiles,
    toast_a.datas,
    [],
    name="laves_toast_qt",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,             # GUI – no console window on Windows
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# ============================================================================
# 2.  LAVES  (main application)
#     Built as --onedir so PySide6 plugins/platforms sit alongside LAVES.exe
#     and data files in Data/ are easily accessible and updatable.
# ============================================================================
main_a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[
        # Bundle the additive database so the app works out-of-the-box.
        # The updater will overwrite this file with a fresh copy after download.
        ("Data/zusatzstoffe.json", "Data"),
        # Uncomment if a combo-rules file exists:
        # ("Data/kombiregeln.json", "Data"),
    ],
    hiddenimports=HIDDEN,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

main_pyz = PYZ(main_a.pure)

main_exe = EXE(
    main_pyz,
    main_a.scripts,
    [],
    exclude_binaries=True,     # --onedir: binaries live alongside the exe
    name="LAVES",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

main_coll = COLLECT(
    main_exe,
    main_a.binaries,
    main_a.zipfiles,
    main_a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="LAVES",              # output → dist/LAVES/
)
