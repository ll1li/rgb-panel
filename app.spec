# PyInstaller spec for the RGB Panel desktop app.  Build:  uv run pyinstaller app.spec
# Output: dist\RGB Panel\RGB Panel.exe (one-folder build: starts fast, no temp extraction).
from PyInstaller.utils.hooks import collect_all

import glob
datas = [("panel.html", "."), ("labels.json", "."), ("app.ico", ".")]
datas += [(f"music/{n}.{ext}", "music") for n in ("sweden", "soviet", "america", "police") for ext in ("wav", "source.txt")
          if glob.glob(f"music/{n}.{ext}")]
binaries = []
hiddenimports = ["openrgb", "openrgb.utils", "openrgb.orgb", "openrgb.network", "effects", "panel", "anthem"]
for pkg in ("webview",):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["app.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "PIL", "PyInstaller"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RGB Panel",
    icon="app.ico",
    console=False,
    disable_windowed_traceback=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="RGB Panel")
