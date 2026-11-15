# LumaWaveV2

A lightweight desktop audio visualizer for **Windows 10 / 11 (64-bit)**. It captures system audio using WASAPI loopback and draws customizable spectrum and edge overlays without blocking your mouse clicks.

> Built as a v2 continuation of a friend's original LumaWave concept — adding per-device audio routing, multi-monitor selection, new visualizer styles, live-saving settings, and an auto-updater.

## Install & Run

### Option 1: Windows Installer (Recommended)
1. Download **`LumaWave-v1.1.0-Setup.exe`** from the [Releases](https://github.com/sid-gupta-007/luma-wave-v2-sid/releases) page.
2. Run the installer (it installs per-user into `%LOCALAPPDATA%\Programs\LumaWaveV2`, so it doesn't need admin permissions).
3. Launch **LumaWaveV2** from the Start Menu or Desktop shortcut.

### Option 2: Portable Zip
1. Download **`LumaWave-v1.1.0-Windows-x64.zip`** from [Releases](https://github.com/sid-gupta-007/luma-wave-v2-sid/releases).
2. **Extract the entire zip first** — keep `LumaWave.exe` and the `_internal` folder in the same directory. (Running `LumaWave.exe` directly from inside an unextracted zip preview will fail because it won't see `_internal`.)
3. Run **`LumaWave.exe`**.

> **SmartScreen note:** Because the app isn't code-signed yet, Windows SmartScreen may warn on first run. Click **More info → Run anyway** if you trust the download.

## What It Does

- **Audio & Monitor Routing:** Pick the exact Windows playback device (headphones, speakers, virtual cables) and the monitor you want the overlay on.
- **Visualizer Modes:**
  - **Main:** Classic Symmetrical Bars, Mirrored Center Waveform, LED Matrix Dots, Thin Needle Spectrum, Layered Smooth Ribbon, 3D Silk Ribbon, Stacked Gradient Peaks, or Off.
  - **4-Side Edge Waves:** Independent Top, Bottom, Left, and Right edge overlays with adjustable opacity, reach, and thickness.
  - **Circular:** Radial Bars, Segmented Dot Ring, Concentric Wave Rings, 3D Mesh Rings, and Pulse Halo.
- **Color Modes:** Match your active screen contrast, pull a 5-color palette from your Windows wallpaper, use built-in presets, or pick 5 custom colors with optional animated color flow.
- **Tray & Startup:** Lives in the system tray, saves changes live to `%APPDATA%\LumaWave\settings-v2.json`, and supports optional **Start with Windows**.
- **Updates:** Check manually from **Settings → Check for Updates** or the tray menu. Releases are verified against `SHA256SUMS.txt` before applying, and skipped versions won't keep nagging you.

## Verifying Downloads (Optional)

Every GitHub Release includes `SHA256SUMS.txt` and GitHub build provenance attestations:

```powershell
# Check SHA-256 hash against SHA256SUMS.txt
Get-FileHash .\LumaWave-v1.1.0-Setup.exe -Algorithm SHA256

# Or verify GitHub build provenance with GitHub CLI
gh attestation verify .\LumaWave-v1.1.0-Setup.exe --owner sid-gupta-007
```

## Run from Source

Requires **Windows 10 (1903+) / Windows 11 (64-bit)** and **Python 3.11+**.

```powershell
pip install -r requirements.txt
python app.py
```

## Build Yourself

Use `LumaWave.spec` (don't run `pyinstaller app.py` directly):

```powershell
pyinstaller --noconfirm --clean LumaWave.spec
```

`LumaWave.spec` bundles `lumawave/assets/app.ico` and strips any third-party ICU DLLs (`icuuc*`, `icudt*`, `icuin*`, `icuio*`) from `PATH` so `Qt6Core.dll` loads Windows' built-in `System32\icuuc.dll` instead of crashing on startup.

The packaged app is written to `dist\LumaWave\`. If you also have [Inno Setup 6](https://jrsoftware.org/isinfo.php) installed, you can build the installer with:

```powershell
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DAppVersion=1.1.0 installer.iss
```

## License

MIT — see [LICENSE](LICENSE).
