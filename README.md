# Luma-Wave V2

This version makes the Windows output loopback device and the target monitor explicit.

Run locally:

```powershell
python app.py
```

Use the tray icon's **Settings** panel to choose the same output device that VLC or the browser is using, choose a display, and run **Test bars** before relying on audio capture.

Build a distributable Windows executable:

```powershell
pyinstaller --noconfirm --clean LumaWave.spec
```

Always build from `LumaWave.spec`. It removes foreign ICU DLLs (`icuuc.dll`, `icudt*.dll`) that PyInstaller can pick up from PATH. Qt has to use the copy in Windows (`System32\icuuc.dll`). If a foreign one gets bundled, startup fails with "DLL load failed while importing QtCore". Don't use the old one-line `pyinstaller ... app.py` command, because it skips this filtering.
