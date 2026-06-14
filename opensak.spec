# opensak.spec — PyInstaller build spec
# Used by GitHub Actions CI/CD.
#
# Build locally:
#   pyinstaller opensak.spec
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

# reverse_geocoder (GeoNames CSV) and pycountry (ISO JSON) ship data files and
# are imported lazily inside geocoder.py, so PyInstaller's static graph misses
# them — bundle their data and force the imports below.
geocode_datas = collect_data_files("reverse_geocoder") + collect_data_files("pycountry")

# Platform-specific icon
if sys.platform == "win32":
    ICON = str(Path("assets/icons/opensak.ico"))
elif sys.platform == "darwin":
    ICON = str(Path("assets/icons/opensak.icns"))
else:
    ICON = str(Path("assets/icons/opensak.png"))

a = Analysis(
    ["run.py"],
    pathex=["."],
    binaries=[],
    datas=[
        ("assets/icons/opensak.png",  "assets/icons/"),
        ("assets/icons/opensak.ico",  "assets/icons/"),
        ("assets/icons/opensak.icns", "assets/icons/"),
        ("src/opensak/lang/",          "opensak/lang/"),
    ] + geocode_datas,
    hiddenimports=[
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineCore",
        "sqlalchemy.dialects.sqlite",
        "reverse_geocoder",
        "pycountry",
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
    exclude_binaries=True,
    name="opensak",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="opensak",
)

# macOS .app bundle
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="OpenSAK.app",
        icon=ICON,
        bundle_identifier="dk.opensak.app",
        info_plist={
            "CFBundleDisplayName":        "OpenSAK",
            "CFBundleShortVersionString": "1.0.0",
            "CFBundleVersion":            "1.0.0",
            "NSHighResolutionCapable":    True,
            "NSRequiresAquaSystemAppearance": False,
        },
    )
