# PyInstaller spec for YaBizTracker 1.0.2
# QtWebEngine needs not only Python hidden imports, but also its native
# process, DLLs and resource files (resources.pak, locales, etc.).
from PyInstaller.utils.hooks import collect_all, collect_submodules

webengine_core = collect_all('PyQt6.QtWebEngineCore')
webengine_widgets = collect_all('PyQt6.QtWebEngineWidgets')
hiddenimports = (
    collect_submodules('PyQt6.QtWebEngineCore')
    + collect_submodules('PyQt6.QtWebEngineWidgets')
    + webengine_core[2]
    + webengine_widgets[2]
)

datas = [
    ('yabiztracker/map.html', 'yabiztracker'),
    ('icon.png', '.'),
    *webengine_core[0],
    *webengine_widgets[0],
]
binaries = [
    *webengine_core[1],
    *webengine_widgets[1],
]

# De-duplicate entries because PyQt6 hooks can expose the same Qt files
# through both WebEngineCore and WebEngineWidgets.
def _unique(items):
    seen = set()
    out = []
    for item in items:
        key = tuple(item) if isinstance(item, (list, tuple)) else item
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out

datas = _unique(datas)
binaries = _unique(binaries)
hiddenimports = sorted(set(hiddenimports))

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    a.binaries,
    a.datas,
    [],
    name='YaBizTracker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon='icon.ico',
)
