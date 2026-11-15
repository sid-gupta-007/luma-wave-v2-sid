# Luma-Wave (Windows)

A lightweight, real-time desktop audio visualizer for **Windows 10 / 11 (64-bit)** that captures system audio via WASAPI loopback and renders customizable spectrum overlays on your screen.

> Rebuilt and expanded from a friend's original Luma-Wave concept/build to add device & monitor routing, multiple visualizer modes, live-updating controls, and open-source packaging.

## Features

- **WASAPI Loopback & Multi-Monitor Support:** Pick the exact Windows audio output device (headphones, speakers, virtual cables) and target display from the Settings window.
- **Main Visualizer Styles:** Classic Symmetrical Bars, Mirrored Center Waveform, LED Matrix Dots, Thin Needle Spectrum, Layered Smooth Ribbon, 3D Silk Ribbon, Stacked Gradient Peaks, or Off.
- **Ambient Edge Waves (4-Side):** Enable audio-reactive overlays on any combination of **Top**, **Bottom**, **Left**, and **Right** edges with selectable styles (`3D Silk Ribbon`, `Spectrum Bars`, `LED Matrix Dots`, `Thin Needle Spectrum`, `Stacked Gradient Peaks`), opacity, reach, and line thickness.
- **Circular Visualizers:** Radial Bars, Segmented Dot Ring, Concentric Wave Rings, 3D Mesh Rings, and Pulse Halo.
- **Dynamic Color & Themes:**
  - **Auto (Active Screen Contrast):** Adapts colors to the brightness/contrast of your active screen.
  - **Auto (Desktop Wallpaper):** Extracts a 5-color palette from your Windows wallpaper.
  - **Presets & Custom:** One-click color presets, animated color flow, and 5 manual color pickers.
- **Interactive & Live Controls:**
  - Instant live preview with automatic saving (`%APPDATA%\LumaWave\settings-v2.json`).
  - Cursor-reactive wave stretching on hover (click-through, never blocks mouse clicks).
  - Universal **Visualizer: ON / OFF** toggle in the Settings header and system tray menu.

---

## Download & Run (Windows x64)

1. Go to the **Releases** page and download `LumaWave-Windows-x64.zip`.
2. Extract the entire zip folder (keep `LumaWave.exe` and the `_internal` folder together).
3. Run **`LumaWave.exe`**.
   - *Note:* Since the binary is unsigned, Windows SmartScreen may show a prompt on first launch—click **More info → Run anyway**.
4. Right-click (or click) the **Luma-Wave** icon in the system tray to open **Settings**, pick your audio output device, or toggle the visualizer on/off.

---

## Run from Source

Requires **Windows 10 (1903+) / Windows 11 (64-bit)** and **Python 3.11+**.

```powershell
pip install -r requirements.txt
python app.py
```

---

## Build the Windows Executable

Always build using `LumaWave.spec` (do **not** run `pyinstaller ... app.py` directly):

```powershell
pyinstaller --noconfirm --clean LumaWave.spec
```

`LumaWave.spec` filters out third-party ICU DLLs (`icuuc*`, `icudt*`, `icuin*`, `icuio*`) that PyInstaller may pick up from `PATH`, ensuring `Qt6Core.dll` loads Windows' built-in `System32\icuuc.dll` instead of failing with `DLL load failed while importing QtCore`.

The distributable build is output to `dist\LumaWave\`.
