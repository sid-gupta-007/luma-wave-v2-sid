from __future__ import annotations

import json
import os
import sys
import winreg
from dataclasses import asdict, dataclass, field
from pathlib import Path

RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APPROVED_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
RUN_VALUE_NAME = "LumaWave"


def is_windows_startup_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, RUN_VALUE_NAME)
            if not val:
                return False
    except OSError:
        return False

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APPROVED_KEY_PATH, 0, winreg.KEY_READ) as akey:
            data, _ = winreg.QueryValueEx(akey, RUN_VALUE_NAME)
            if isinstance(data, (bytes, bytearray)) and len(data) > 0 and (data[0] & 0x01) != 0:
                return False
    except OSError:
        pass
    return True


def set_windows_startup(enabled: bool) -> None:
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                if getattr(sys, "frozen", False):
                    cmd = f'"{sys.executable}"'
                else:
                    entry = Path(__file__).resolve().parent.parent / "app.py"
                    cmd = f'"{sys.executable}" "{entry}"'
                winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(key, RUN_VALUE_NAME)
                except FileNotFoundError:
                    pass
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, APPROVED_KEY_PATH, 0, winreg.KEY_SET_VALUE) as akey:
            try:
                winreg.DeleteValue(akey, RUN_VALUE_NAME)
            except FileNotFoundError:
                pass
    except OSError:
        pass

CONFIG_FILE = Path(os.environ.get("APPDATA", Path.home())) / "LumaWave" / "settings-v2.json"

BUFFER_SIZE = 4096

DEFAULT_COLORS = ["#7890d7", "#dc8c64", "#b478c8", "#64c8dc", "#a0d2a0"]

COLOR_PRESETS: dict[str, list[str]] = {
    "Neon Cyber": ["#00f5d4", "#00bbf9", "#9b5de5", "#f15bb5", "#fee440"],
    "Sunset Drive": ["#ff4d6d", "#ff758f", "#ff9e00", "#ffd166", "#c77dff"],
    "Ocean Aurora": ["#00f5d4", "#00d2ff", "#3a86ff", "#4361ee", "#7209b7"],
    "Synthwave": ["#ff2a85", "#ff70a6", "#9d4edd", "#5e60ce", "#4ea8de"],
    "Toxic Lime": ["#ccff00", "#80ffdb", "#00f5d4", "#00bbf9", "#5390d9"],
    "Monochrome Ice": ["#e0fbfc", "#98c1d9", "#69a2b0", "#3d5a80", "#bde0fe"],
    "Crimson Phonk": ["#ff003c", "#ff4d6d", "#ff8500", "#b5179e", "#7209b7"],
}


@dataclass
class Settings:
    enabled: bool = True
    audio_device: str = "default"
    monitor: int = 0
    main_style: str = "bars"
    bar_width: int = 24
    bar_gap: int = 14
    bar_height: int = 320
    corner_radius: int = 12
    center_gap: int = 180
    main_opacity: int = 88
    color_mode: str = "wallpaper"
    color_preset: str = "Neon Cyber"
    color_flow: bool = True
    manual_colors: list[str] = field(default_factory=lambda: list(DEFAULT_COLORS))
    ambient_style: str = "none"
    ambient_top: bool = False
    ambient_bottom: bool = False
    ambient_left: bool = False
    ambient_right: bool = False
    ambient_opacity: int = 65
    ambient_depth: int = 65
    ambient_thickness: int = 2
    circle_style: str = "none"
    circle_radius: int = 120
    circle_scale: int = 95
    circle_thickness: int = 3
    circle_opacity: int = 85
    cursor_react: bool = True
    always_on_top: bool = True
    test_mode: bool = False
    skipped_version: str = ""


def load_settings() -> Settings:
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        valid = {k: v for k, v in raw.items() if k in Settings.__dataclass_fields__}
        return Settings(**valid)
    except (OSError, TypeError, ValueError):
        return Settings()


def save_settings(settings: Settings) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")


