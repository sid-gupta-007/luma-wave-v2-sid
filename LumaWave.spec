# -*- mode: python ; coding: utf-8 -*-
import os


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[('lumawave/assets/app.ico', 'lumawave/assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['qt_runtime_hook.py'],
    excludes=[],
    noarchive=False,
    optimize=0,
)
# Qt6Core.dll links against Windows' system ICU (C:\Windows\System32\icuuc.dll,
# unversioned exports such as `ucnv_open`). PyInstaller can pick up a foreign
# ICU build from PATH (e.g. poppler's ICU 78 with `ucnv_open_78`), which then
# shadows the system copy and breaks with "DLL load failed while importing
# QtCore: The specified procedure could not be found". Never bundle ICU.
a.binaries = [
    b for b in a.binaries
    if not os.path.basename(b[0]).lower().startswith(('icuuc', 'icudt', 'icuin', 'icuio'))
]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='LumaWave',
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
    icon='lumawave/assets/app.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='LumaWave',
)
