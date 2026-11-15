"""Luma-Wave: device-aware Windows audio visualizer."""
from __future__ import annotations

import ctypes
import json
import math
import os
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pyaudiowpatch as pyaudio
from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction, QColor, QCursor, QGuiApplication, QIcon, QImage, QImageReader,
    QIntValidator, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDialog,
    QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton,
    QRadioButton, QScrollArea, QSlider, QSystemTrayIcon, QVBoxLayout, QWidget,
)

APP_NAME = "Luma-Wave"
CONFIG_FILE = Path(os.environ.get("APPDATA", Path.home())) / "LumaWave" / "settings-v2.json"
FFT_SIZE = 4096
BUFFER_SIZE = 4096

DEFAULT_COLORS = ["#7890d7", "#dc8c64", "#b478c8", "#64c8dc", "#a0d2a0"]

COLOR_PRESETS: dict[str, list[str]] = {
    "Neon Cyber": ["#00f5d4", "#00bbf9", "#9b5de5", "#f15bb5", "#fee440"],
    "Sunset Drive": ["#ff4d6d", "#ff758f", "#ff9e00", "#ffd166", "#c77dff"],
    "Ocean Aurora": ["#00f5d4", "#00d2ff", "#3a86ff", "#4361ee", "#7209b7"],
    "Synthwave": ["#ff2a85", "#ff70a6", "#9d4edd", "#5e60ce", "#4ea8de"],
    "Toxic Lime": ["#ccff00", "#80ffdb", "#00f5d4", "#00bbf9", "#5390d9"],
    "Monochrome Ice": ["#e0fbfc", "#98c1d9", "#69a2b0", "#3d5a80", "#bde0fe"],
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
    color_mode: str = "screen"
    color_preset: str = "Neon Cyber"
    color_flow: bool = True
    manual_colors: list[str] = field(default_factory=lambda: list(DEFAULT_COLORS))
    ambient_style: str = "silk_3d"
    ambient_top: bool = False
    ambient_bottom: bool = False
    ambient_left: bool = False
    ambient_right: bool = False
    ambient_opacity: int = 32
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


def get_windows_wallpaper_path() -> str | None:
    buf = ctypes.create_unicode_buffer(512)
    if ctypes.windll.user32.SystemParametersInfoW(0x0073, len(buf), buf, 0):
        if buf.value and os.path.isfile(buf.value):
            return buf.value
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop") as key:
            val, _ = winreg.QueryValueEx(key, "WallPaper")
            if val and os.path.isfile(val):
                return val
    except OSError:
        pass
    return None


def _extract_colors_from_image(img: QImage, count: int = 5, contrast_boost: bool = False) -> list[str]:
    if img.isNull():
        return list(DEFAULT_COLORS)
    img = img.scaled(48, 28, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)
    img = img.convertToFormat(QImage.Format.Format_RGB32)
    w, h = img.width(), img.height()
    if w <= 0 or h <= 0:
        return list(DEFAULT_COLORS)

    y_start = int(h * 0.15)
    y_end = max(y_start + 1, int(h * 0.85))
    x_pad = int(w * 0.10)

    total_luma = 0.0
    total_px = 0
    for y in range(y_start, y_end):
        for x in range(x_pad, max(x_pad + 1, w - x_pad)):
            c = QColor(img.pixel(x, y))
            total_luma += (0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()) / 255.0
            total_px += 1
    screen_luma = total_luma / max(1, total_px)

    colors: list[str] = []
    span_w = max(1, w - 2 * x_pad)
    for i in range(count):
        x0 = x_pad + int(i * span_w / count)
        x1 = max(x0 + 1, x_pad + int((i + 1) * span_w / count))
        r_sum = g_sum = b_sum = n = 0
        for y in range(y_start, y_end):
            for x in range(x0, x1):
                c = QColor(img.pixel(x, y))
                r_sum += c.red()
                g_sum += c.green()
                b_sum += c.blue()
                n += 1
        avg_r, avg_g, avg_b = r_sum // max(n, 1), g_sum // max(n, 1), b_sum // max(n, 1)
        qc = QColor(avg_r, avg_g, avg_b)
        h_val, s_val, _v_val, _ = qc.getHsvF()
        if h_val < 0:
            h_val = (0.56 + i * 0.08) % 1.0
        if contrast_boost:
            if screen_luma < 0.48:
                target_v = 0.94
                target_s = min(1.0, max(0.55, s_val + 0.30))
            else:
                target_v = 0.44
                target_s = min(1.0, max(0.70, s_val + 0.35))
            hue = (h_val + (i - 2) * 0.055) % 1.0
            qc.setHsvF(hue, target_s, target_v)
        else:
            qc.setHsvF(max(0.0, h_val), min(1.0, max(0.35, s_val)), min(1.0, max(0.65, _v_val)))
        colors.append(qc.name())
    return colors


_WALLPAPER_CACHE: tuple[str, float, list[str]] | None = None


def extract_wallpaper_colors(count: int = 5) -> list[str]:
    global _WALLPAPER_CACHE
    path = get_windows_wallpaper_path()
    if not path:
        return list(DEFAULT_COLORS)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0.0
    if _WALLPAPER_CACHE and _WALLPAPER_CACHE[0] == path and _WALLPAPER_CACHE[1] == mtime:
        return list(_WALLPAPER_CACHE[2])
    reader = QImageReader(path)
    reader.setDecideFormatFromContent(True)
    img = reader.read()
    if img.isNull():
        img = QImage(path)
    cols = _extract_colors_from_image(img, count=count, contrast_boost=False)
    _WALLPAPER_CACHE = (path, mtime, cols)
    return list(cols)


def extract_screen_colors(monitor_index: int = 0, count: int = 5) -> list[str]:
    screens = QGuiApplication.screens()
    if not screens:
        return list(DEFAULT_COLORS)
    idx = min(max(0, monitor_index), len(screens) - 1)
    scr = screens[idx]
    geo = scr.geometry()
    gx, gy = int(geo.width() * 0.25), int(geo.height() * 0.25)
    gw, gh = max(64, int(geo.width() * 0.5)), max(64, int(geo.height() * 0.5))
    pix = scr.grabWindow(0, gx, gy, gw, gh)
    return _extract_colors_from_image(pix.toImage(), count=count, contrast_boost=True)


def interpolate_palette(colors: list[QColor], t: float, alpha: int = 230) -> QColor:
    if not colors:
        return QColor(120, 144, 215, alpha)
    if len(colors) == 1:
        c = QColor(colors[0])
        c.setAlpha(alpha)
        return c
    t = max(0.0, min(1.0, t)) * (len(colors) - 1)
    idx = min(int(t), len(colors) - 2)
    frac = t - idx
    c1, c2 = colors[idx], colors[idx + 1]
    return QColor(
        int(c1.red() + (c2.red() - c1.red()) * frac),
        int(c1.green() + (c2.green() - c1.green()) * frac),
        int(c1.blue() + (c2.blue() - c1.blue()) * frac),
        alpha,
    )


class AudioEngine:
    """Captures a selected WASAPI output's loopback signal without recording a mic."""

    def __init__(self) -> None:
        self.pa: pyaudio.PyAudio | None = None
        self.stream = None
        self.device_label = "Not started"
        self.error = ""
        self.sample_rate = 48000
        self.channels = 2
        self._samples = np.zeros(FFT_SIZE, dtype=np.float32)
        self._lock = threading.Lock()

    @staticmethod
    def loopback_devices() -> list[dict]:
        pa = pyaudio.PyAudio()
        try:
            return [dict(item) for item in pa.get_loopback_device_info_generator()]
        finally:
            pa.terminate()

    def start(self, requested_device: str) -> None:
        self.stop()
        self.error = ""
        self.pa = pyaudio.PyAudio()
        try:
            devices = [dict(item) for item in self.pa.get_loopback_device_info_generator()]
            if not devices:
                raise RuntimeError("No WASAPI loopback devices were found.")
            chosen = next((d for d in devices if str(d["index"]) == requested_device), None)
            if chosen is None:
                chosen = dict(self.pa.get_default_wasapi_loopback())
            self.sample_rate = int(chosen.get("defaultSampleRate", 48000))
            self.channels = max(1, int(chosen.get("maxInputChannels", 2)))
            self.device_label = chosen["name"].replace(" [Loopback]", "")
            self.stream = self.pa.open(
                format=pyaudio.paFloat32,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                input_device_index=chosen["index"],
                frames_per_buffer=BUFFER_SIZE,
                stream_callback=self._callback,
            )
            self.stream.start_stream()
        except Exception as exc:
            self.error = f"Audio unavailable: {exc}"
            self.stop(keep_error=True)

    def _callback(self, data, frame_count, time_info, status):
        try:
            values = np.frombuffer(data, dtype=np.float32)
            if self.channels > 1:
                values = values.reshape(-1, self.channels).mean(axis=1)
            with self._lock:
                self._samples = np.concatenate((self._samples, values))[-FFT_SIZE:]
        except Exception as exc:
            self.error = f"Audio callback failed: {exc}"
        return (None, pyaudio.paContinue)

    def spectrum(self, bands: int) -> np.ndarray:
        with self._lock:
            samples = self._samples.copy()
        if not np.any(samples):
            return np.zeros(bands, dtype=np.float32)
        fft = np.abs(np.fft.rfft(samples * np.hanning(len(samples))))
        frequencies = np.fft.rfftfreq(len(samples), 1 / self.sample_rate)
        edges = np.geomspace(40, min(16000, self.sample_rate / 2), bands + 1)
        values = np.zeros(bands, dtype=np.float32)
        for index in range(bands):
            region = fft[(frequencies >= edges[index]) & (frequencies < edges[index + 1])]
            if len(region):
                values[index] = float(np.log1p(region.max()) / 8.2)
        return np.clip(values, 0, 1)

    def stop(self, keep_error: bool = False) -> None:
        if self.stream:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception:
                pass
        if self.pa:
            try:
                self.pa.terminate()
            except Exception:
                pass
        self.stream = self.pa = None
        if not keep_error:
            self.error = ""


class Visualizer(QWidget):
    palette_changed = Signal(list)

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._initialized = False
        self.settings = settings
        self.audio = AudioEngine()
        self.values = np.zeros(64, dtype=np.float32)
        self.ambient_values = np.zeros(24, dtype=np.float32)
        self.active_colors: list[QColor] = []
        self.target_colors: list[QColor] = []
        self.test_until = 0.0
        self.cursor_local = None
        self._screen_tick = 0
        self._color_phase = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.apply_settings(settings, persist=False)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(16)

    def _bars_per_side(self) -> int:
        step = max(2, self.settings.bar_width + self.settings.bar_gap)
        half_w = max(0, (self.width() - self.settings.center_gap) // 2)
        return max(4, min(96, half_w // step))

    def refresh_palette(self, smooth: bool = False) -> list[str]:
        mode = self.settings.color_mode
        if mode == "screen":
            hex_list = extract_screen_colors(self.settings.monitor, 5)
        elif mode in ("wallpaper", "auto"):
            hex_list = extract_wallpaper_colors(5)
        else:
            hex_list = list(self.settings.manual_colors) or list(DEFAULT_COLORS)
        self.target_colors = [QColor(h) for h in hex_list]
        if not smooth or len(self.active_colors) != len(self.target_colors):
            self.active_colors = [QColor(c) for c in self.target_colors]
        self.palette_changed.emit(hex_list)
        return hex_list

    def _palette_at(self, t: float, alpha: int = 230) -> QColor:
        if self.settings.color_flow:
            t = (t + self._color_phase) % 1.0
        return interpolate_palette(self.active_colors, t, alpha)

    def _cursor_boost(self, x: float, y: float, radius: float = 170.0) -> float:
        if not self.settings.cursor_react or self.cursor_local is None:
            return 0.0
        dx = x - self.cursor_local.x()
        dy = y - self.cursor_local.y()
        dist_sq = dx * dx + dy * dy
        if dist_sq >= radius * radius:
            return 0.0
        return (1.0 - math.sqrt(dist_sq) / radius) ** 2

    def apply_settings(self, settings: Settings, persist: bool = True, restart_audio: bool = True) -> None:
        old = self.settings if self._initialized else None
        self.settings = settings
        self._initialized = True

        if old is None or old.always_on_top != settings.always_on_top:
            flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus
            if settings.always_on_top:
                flags |= Qt.WindowType.WindowStaysOnTopHint
            self.setWindowFlags(flags)

        if old is None or old.monitor != settings.monitor:
            screens = QGuiApplication.screens()
            index = min(max(0, settings.monitor), max(0, len(screens) - 1))
            rect = screens[index].availableGeometry()
            self.setGeometry(rect)

        if (
            old is None
            or old.color_mode != settings.color_mode
            or old.manual_colors != settings.manual_colors
            or old.monitor != settings.monitor
        ):
            self.refresh_palette()

        needed = self._bars_per_side()
        if len(self.values) != needed:
            self.values = np.zeros(needed, dtype=np.float32)

        if restart_audio or old is None or old.audio_device != settings.audio_device or self.audio.stream is None:
            self.audio.start(settings.audio_device)

        if persist:
            save_settings(settings)

        if settings.enabled:
            if not self.isVisible():
                self.show()
        elif self.isVisible():
            self.hide()
        self.update()

    def test_bars(self) -> None:
        self.test_until = time.monotonic() + 6.0

    def tick(self) -> None:
        if not self.settings.enabled:
            if self.isVisible():
                self.hide()
            return
        if not self.isVisible():
            self.show()
        n = len(self.values)
        is_demo = self.settings.test_mode or time.monotonic() < self.test_until
        if is_demo:
            phase = time.monotonic() * 3.2
            target = np.array([
                (0.22 + 0.72 * abs(math.sin(phase + i * 0.24))) * (1.0 - 0.55 * (i / max(1, n - 1)))
                for i in range(n)
            ], dtype=np.float32)
            amb_target = np.array([
                0.22 + 0.65 * (0.5 + 0.5 * math.sin(phase * 0.8 + i * 0.42))
                for i in range(len(self.ambient_values))
            ], dtype=np.float32)
        else:
            target = self.audio.spectrum(n)
            raw_amb = self.audio.spectrum(len(self.ambient_values))
            amb_target = np.convolve(np.pad(raw_amb, 1, mode="edge"), [0.25, 0.5, 0.25], mode="valid")

        self.values += (target - self.values) * 0.24
        self.ambient_values += (amb_target - self.ambient_values) * 0.14
        if self.settings.cursor_react:
            self.cursor_local = self.mapFromGlobal(QCursor.pos())
        else:
            self.cursor_local = None
        if self.settings.color_flow:
            self._color_phase = (self._color_phase + 0.0022) % 1.0
        if self.settings.color_mode == "screen":
            self._screen_tick += 1
            if self._screen_tick >= 90:
                self._screen_tick = 0
                self.refresh_palette(smooth=True)
        if len(self.active_colors) == len(self.target_colors):
            for idx, (cur, tgt) in enumerate(zip(self.active_colors, self.target_colors)):
                if cur != tgt:
                    self.active_colors[idx] = QColor(
                        int(cur.red() + (tgt.red() - cur.red()) * 0.18),
                        int(cur.green() + (tgt.green() - cur.green()) * 0.18),
                        int(cur.blue() + (tgt.blue() - cur.blue()) * 0.18),
                    )
        self.update()

    def _draw_ambient_edges(self, painter: QPainter) -> None:
        s = self.settings
        if not (s.ambient_top or s.ambient_bottom or s.ambient_left or s.ambient_right):
            return
        alpha_max = int(255 * max(0.08, min(1.0, s.ambient_opacity / 100.0)))
        depth_max = max(24, s.ambient_depth)
        w, h = float(self.width()), float(self.height())
        pts = len(self.ambient_values)
        now = time.monotonic()
        strands = 12
        base_thick = max(0.8, float(s.ambient_thickness) * 0.65)

        def build_gradient(vertical: bool, alpha: int) -> QLinearGradient:
            grad = QLinearGradient(0.0, 0.0, 0.0, h) if vertical else QLinearGradient(0.0, 0.0, w, 0.0)
            stops = max(2, len(self.active_colors))
            for idx in range(stops):
                t = idx / (stops - 1)
                grad.setColorAt(t, interpolate_palette(self.active_colors, t, alpha))
            return grad

        def draw_edge(inward_sign: int, vertical: bool) -> None:
            edge_len = h if vertical else w
            base_pos = 0.0 if inward_sign > 0 else (w if vertical else h)
            style = s.ambient_style

            if style == "silk_3d":
                if not vertical:
                    glow = QLinearGradient(0.0, base_pos, 0.0, base_pos + inward_sign * depth_max * 0.75)
                    glow_rect = (0.0, min(base_pos, base_pos + inward_sign * depth_max * 0.75), w, depth_max * 0.75)
                else:
                    glow = QLinearGradient(base_pos, 0.0, base_pos + inward_sign * depth_max * 0.75, 0.0)
                    glow_rect = (min(base_pos, base_pos + inward_sign * depth_max * 0.75), 0.0, depth_max * 0.75, h)

                c_glow = self._palette_at(0.45, int(alpha_max * 0.18))
                glow.setColorAt(0.0, c_glow)
                glow.setColorAt(1.0, QColor(c_glow.red(), c_glow.green(), c_glow.blue(), 0))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(glow)
                painter.drawRect(*glow_rect)

                painter.setBrush(Qt.BrushStyle.NoBrush)
                for k in range(strands):
                    frac = k / max(1, strands - 1)
                    fade = 1.0 - 0.72 * abs(frac - 0.30)
                    strand_alpha = max(14, int(alpha_max * fade))
                    grad = build_gradient(vertical, strand_alpha)
                    pen = QPen(grad, base_thick * (1.25 if k in (2, 3) else 0.85))
                    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                    painter.setPen(pen)

                    coords: list[tuple[float, float]] = []
                    phase_shift = now * 0.55 + k * 0.28
                    amp_scale = 0.35 + 0.65 * (1.0 - frac * 0.48)
                    for i in range(pts):
                        t = i / max(1, pts - 1)
                        env = 0.30 + 0.70 * math.sin(t * math.pi)
                        audio_v = float(self.ambient_values[i])
                        wave = 0.5 + 0.5 * math.sin(t * 5.5 + phase_shift)
                        px = base_pos if vertical else t * w
                        py = t * h if vertical else base_pos
                        stretch = 1.0 + 0.85 * self._cursor_boost(px, py)
                        amp = (0.08 + audio_v * 0.92) * depth_max * amp_scale * (0.55 + 0.45 * wave) * env * stretch
                        if not vertical:
                            coords.append((t * w, base_pos + inward_sign * amp))
                        else:
                            coords.append((base_pos + inward_sign * amp, t * h))

                    path = QPainterPath()
                    path.moveTo(coords[0][0], coords[0][1])
                    for i in range(len(coords) - 1):
                        mx = (coords[i][0] + coords[i + 1][0]) * 0.5
                        my = (coords[i][1] + coords[i + 1][1]) * 0.5
                        path.quadTo(coords[i][0], coords[i][1], mx, my)
                    path.lineTo(coords[-1][0], coords[-1][1])
                    painter.drawPath(path)

            elif style in ("bars", "needle_bars", "led_dots"):
                painter.setPen(Qt.PenStyle.NoPen)
                bw = max(2, min(6, int(base_thick * 1.4))) if style == "needle_bars" else max(6, int(base_thick * 4))
                gap = max(3, bw // 2)
                step = bw + gap
                count = max(12, int(edge_len // step))
                for i in range(count):
                    t = i / max(1, count - 1)
                    idx = min(pts - 1, int(abs(t * 2.0 - 1.0) * (pts - 1)))
                    pos = i * step + gap * 0.5
                    px = base_pos if vertical else pos
                    py = pos if vertical else base_pos
                    stretch = 1.0 + 0.85 * self._cursor_boost(px, py)
                    amp = max(4.0, float(self.ambient_values[idx]) * depth_max * stretch)
                    painter.setBrush(self._palette_at(t, alpha_max))
                    if style == "led_dots":
                        dot = max(3, bw // 2)
                        cell = dot + 3
                        dots = max(1, int(amp // cell))
                        for d in range(dots):
                            dist = 4 + d * cell
                            if not vertical:
                                y = (base_pos + dist) if inward_sign > 0 else (base_pos - dist - dot)
                                painter.drawRoundedRect(int(pos), int(y), bw, dot, 2, 2)
                            else:
                                x = (base_pos + dist) if inward_sign > 0 else (base_pos - dist - dot)
                                painter.drawRoundedRect(int(x), int(pos), dot, bw, 2, 2)
                    else:
                        r = min(bw / 2.0, 4.0)
                        if not vertical:
                            y = base_pos if inward_sign > 0 else (base_pos - amp)
                            painter.drawRoundedRect(int(pos), int(y), bw, int(amp), r, r)
                        else:
                            x = base_pos if inward_sign > 0 else (base_pos - amp)
                            painter.drawRoundedRect(int(x), int(pos), int(amp), bw, r, r)

            elif style == "area_peaks":
                painter.setPen(Qt.PenStyle.NoPen)
                for layer in range(2):
                    scale = 1.0 if layer == 0 else 0.55
                    alpha = int(alpha_max * (0.55 if layer == 0 else 0.85))
                    path = QPainterPath()
                    if not vertical:
                        path.moveTo(0.0, base_pos)
                        for i in range(pts):
                            t = i / max(1, pts - 1)
                            idx = min(pts - 1, int(abs(t * 2.0 - 1.0) * (pts - 1)))
                            stretch = 1.0 + 0.85 * self._cursor_boost(t * w, base_pos)
                            amp = max(4.0, float(self.ambient_values[idx]) * depth_max * scale * stretch)
                            path.lineTo(t * w, base_pos + inward_sign * amp)
                        path.lineTo(w, base_pos)
                    else:
                        path.moveTo(base_pos, 0.0)
                        for i in range(pts):
                            t = i / max(1, pts - 1)
                            idx = min(pts - 1, int(abs(t * 2.0 - 1.0) * (pts - 1)))
                            stretch = 1.0 + 0.85 * self._cursor_boost(base_pos, t * h)
                            amp = max(4.0, float(self.ambient_values[idx]) * depth_max * scale * stretch)
                            path.lineTo(base_pos + inward_sign * amp, t * h)
                        path.lineTo(base_pos, h)
                    path.closeSubpath()
                    painter.setBrush(build_gradient(vertical, alpha))
                    painter.drawPath(path)

        if s.ambient_top:
            draw_edge(1, False)
        if s.ambient_bottom:
            draw_edge(-1, False)
        if s.ambient_left:
            draw_edge(1, True)
        if s.ambient_right:
            draw_edge(-1, True)
        painter.setPen(Qt.PenStyle.NoPen)

    def _draw_circular_visualizer(self, painter: QPainter) -> None:
        s = self.settings
        if s.circle_style == "none":
            return
        cx, cy = self.width() / 2.0, self.height() / 2.0
        r_in = float(max(30, s.circle_radius))
        reach = float(max(15, s.circle_scale))
        thick = float(max(1, s.circle_thickness))
        op = max(0.05, min(1.0, s.circle_opacity / 100.0))
        n = len(self.values)
        now = time.monotonic()

        if s.circle_style == "radial_bars":
            count = 72
            for i in range(count):
                idx = int((abs((i / count) * 2.0 - 1.0)) * (n - 1))
                val = float(self.values[idx])
                angle = (i / count) * 2.0 * math.pi - math.pi / 2.0
                px_e = cx + math.cos(angle) * r_in
                py_e = cy + math.sin(angle) * r_in
                stretch = 1.0 + 0.85 * self._cursor_boost(px_e, py_e)
                length = 4.0 + val * reach * stretch
                t_col = i / count
                color = self._palette_at(t_col, int(255 * op))
                pen = QPen(color, thick, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                x1 = cx + math.cos(angle) * r_in
                y1 = cy + math.sin(angle) * r_in
                x2 = cx + math.cos(angle) * (r_in + length)
                y2 = cy + math.sin(angle) * (r_in + length)
                painter.drawLine(int(x1), int(y1), int(x2), int(y2))
            painter.setPen(Qt.PenStyle.NoPen)

        elif s.circle_style == "dot_ring":
            count = 60
            rings = 8
            for i in range(count):
                idx = int((abs((i / count) * 2.0 - 1.0)) * (n - 1))
                val = float(self.values[idx])
                active_dots = max(1, int(val * rings))
                angle = (i / count) * 2.0 * math.pi - math.pi / 2.0
                t_col = i / count
                for d in range(active_dots):
                    alpha = int(255 * op * (1.0 - d / (rings + 1)))
                    painter.setBrush(interpolate_palette(self.active_colors, t_col, alpha))
                    dist = r_in + (d / rings) * reach
                    px = cx + math.cos(angle) * dist
                    py = cy + math.sin(angle) * dist
                    painter.drawEllipse(int(px - 2), int(py - 2), 4, 4)

        elif s.circle_style in ("wave_rings", "mesh_3d"):
            painter.setBrush(Qt.BrushStyle.NoBrush)
            pts = 80
            strands = 14 if s.circle_style == "mesh_3d" else 7
            for k in range(strands):
                frac = k / max(1, strands - 1)
                alpha = int((245 if s.circle_style == "mesh_3d" else 225) * op * (1.0 - 0.68 * frac))
                w_pen = max(0.8, thick * (0.55 if s.circle_style == "mesh_3d" else 0.65) * (1.2 if k == 0 else 0.85))
                pen = QPen(interpolate_palette(self.active_colors, frac, alpha), w_pen)
                painter.setPen(pen)
                coords: list[tuple[float, float]] = []
                for i in range(pts):
                    idx = int((abs((i / pts) * 2.0 - 1.0)) * (n - 1))
                    val = float(self.values[idx])
                    angle = (i / pts) * 2.0 * math.pi
                    stretch = 1.0 + 0.75 * self._cursor_boost(cx + math.cos(angle) * r_in, cy + math.sin(angle) * r_in)
                    if s.circle_style == "mesh_3d":
                        ripple = 0.5 + 0.5 * math.sin(angle * 3.0 + now * 0.65 + k * 0.24)
                        r = r_in + (0.12 + val * 0.88) * reach * (1.0 - frac * 0.55) * (0.68 + 0.32 * ripple) * stretch
                    else:
                        ripple = 0.5 + 0.5 * math.sin(angle * 4.0 + now * 1.1 + k * 0.45)
                        r = r_in + (0.15 + val * 0.85) * reach * (1.0 - frac * 0.35) * (0.55 + 0.45 * ripple) * stretch
                    coords.append((cx + math.cos(angle) * r, cy + math.sin(angle) * r))
                path = QPainterPath()
                start_mx = (coords[-1][0] + coords[0][0]) * 0.5
                start_my = (coords[-1][1] + coords[0][1]) * 0.5
                path.moveTo(start_mx, start_my)
                for i in range(pts):
                    nxt = coords[(i + 1) % pts]
                    mx = (coords[i][0] + nxt[0]) * 0.5
                    my = (coords[i][1] + nxt[1]) * 0.5
                    path.quadTo(coords[i][0], coords[i][1], mx, my)
                path.closeSubpath()
                painter.drawPath(path)
            painter.setPen(Qt.PenStyle.NoPen)

        elif s.circle_style == "halo":
            bass = float(np.mean(self.values[:max(2, n // 4)]))
            for k in range(5):
                frac = k / 4.0
                r = r_in + (0.2 + bass * 0.8) * reach * (0.4 + frac * 0.85)
                alpha = int(115 * op * (1.0 - frac * 0.8))
                pen = QPen(interpolate_palette(self.active_colors, frac, alpha), 14.0 - k * 2.0)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(int(cx - r), int(cy - r), int(2 * r), int(2 * r))
            painter.setPen(Qt.PenStyle.NoPen)

    def _draw_main_visualizer(self, painter: QPainter) -> None:
        s = self.settings
        if s.main_style == "none":
            return
        n = len(self.values)
        step = s.bar_width + s.bar_gap
        half_gap = s.center_gap / 2.0
        center = self.width() / 2.0
        radius = min(s.corner_radius, s.bar_width / 2.0)
        op = max(0.05, min(1.0, s.main_opacity / 100.0))

        if s.main_style == "bars":
            for i in range(n):
                val = float(self.values[i])
                offset_from_center = half_gap + (n - 1 - i) * step
                color = self._palette_at(i / max(1, n - 1), int(255 * op))
                painter.setBrush(color)
                for x in (center - offset_from_center - s.bar_width, center + offset_from_center):
                    if 0 <= x + s.bar_width and x <= self.width():
                        stretch = 1.0 + 0.85 * self._cursor_boost(x + s.bar_width * 0.5, self.height() - 40)
                        height = max(4.0, val * s.bar_height * stretch)
                        path = QPainterPath()
                        path.addRoundedRect(x, self.height() - height - 8, s.bar_width, height, radius, radius)
                        painter.drawPath(path)

        elif s.main_style == "mirrored_bars":
            mid_y = self.height() - s.bar_height * 0.55 - 16
            painter.setBrush(interpolate_palette(self.active_colors, 0.5, int(100 * op)))
            painter.drawRect(0, int(mid_y - 1), self.width(), 2)
            for i in range(n):
                val = float(self.values[i])
                half_h = max(3.0, val * s.bar_height * 0.5)
                offset_from_center = half_gap + (n - 1 - i) * step
                color = interpolate_palette(self.active_colors, i / max(1, n - 1), int(255 * op))
                painter.setBrush(color)
                for x in (center - offset_from_center - s.bar_width, center + offset_from_center):
                    if 0 <= x + s.bar_width and x <= self.width():
                        path = QPainterPath()
                        path.addRoundedRect(x, mid_y - half_h, s.bar_width, half_h * 2.0, radius, radius)
                        painter.drawPath(path)

        elif s.main_style == "led_dots":
            dot_h = max(4, min(12, s.bar_width // 2))
            dot_gap = max(3, dot_h // 2)
            cell = dot_h + dot_gap
            for i in range(n):
                val = float(self.values[i])
                total_dots = max(1, int((val * s.bar_height) / cell))
                offset_from_center = half_gap + (n - 1 - i) * step
                color = interpolate_palette(self.active_colors, i / max(1, n - 1), int(255 * op))
                painter.setBrush(color)
                for x in (center - offset_from_center - s.bar_width, center + offset_from_center):
                    if 0 <= x + s.bar_width and x <= self.width():
                        for d in range(total_dots):
                            y = self.height() - 10 - (d + 1) * cell
                            painter.drawRoundedRect(int(x), int(y), s.bar_width, dot_h, min(3, radius), min(3, radius))

        elif s.main_style == "needle_bars":
            w_thin = max(2, min(5, s.bar_width // 4))
            step_thin = w_thin + max(3, s.bar_gap // 2)
            count = max(8, int((self.width() - s.center_gap) // (2 * step_thin)))
            for i in range(count):
                idx = min(n - 1, int(i * n / count))
                val = float(self.values[idx])
                h_bar = max(4.0, val * s.bar_height)
                offset = half_gap + (count - 1 - i) * step_thin
                painter.setBrush(interpolate_palette(self.active_colors, i / max(1, count - 1), int(255 * op)))
                for x in (center - offset - w_thin, center + offset):
                    if 0 <= x + w_thin and x <= self.width():
                        painter.drawRoundedRect(int(x), int(self.height() - h_bar - 8), w_thin, int(h_bar), 1, 1)

        elif s.main_style in ("smooth_ribbon", "area_peaks"):
            w, h = float(self.width()), float(self.height())
            layers = 4 if s.main_style == "smooth_ribbon" else 2
            pts = max(24, n * 2)
            for layer in range(layers):
                frac = layer / max(1, layers - 1)
                scale = 1.0 - frac * 0.42
                alpha = int((200 if s.main_style == "area_peaks" else (215 - frac * 90)) * op)
                coords: list[tuple[float, float]] = []
                for p in range(pts):
                    t = p / max(1, pts - 1)
                    sym = abs(t * 2.0 - 1.0)
                    idx = min(n - 1, int(sym * (n - 1)))
                    val = float(self.values[idx])
                    y = h - 8.0 - max(4.0, val * s.bar_height * scale)
                    coords.append((t * w, y))
                path = QPainterPath()
                path.moveTo(0.0, h)
                path.lineTo(coords[0][0], coords[0][1])
                for p in range(len(coords) - 1):
                    if s.main_style == "smooth_ribbon":
                        mx = (coords[p][0] + coords[p + 1][0]) * 0.5
                        my = (coords[p][1] + coords[p + 1][1]) * 0.5
                        path.quadTo(coords[p][0], coords[p][1], mx, my)
                    else:
                        path.lineTo(coords[p + 1][0], coords[p + 1][1])
                path.lineTo(coords[-1][0], coords[-1][1])
                path.lineTo(w, h)
                path.closeSubpath()
                grad = QLinearGradient(0.0, 0.0, w, 0.0)
                for c_idx in range(max(2, len(self.active_colors))):
                    ct = c_idx / max(1, len(self.active_colors) - 1)
                    grad.setColorAt(ct, interpolate_palette(self.active_colors, (ct + frac * 0.2) % 1.0, alpha))
                painter.setBrush(grad)
                painter.drawPath(path)

        elif s.main_style == "silk_3d":
            w, h = float(self.width()), float(self.height())
            pts = max(36, n * 2)
            strands = 16
            now = time.monotonic()
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for k in range(strands):
                frac = k / max(1, strands - 1)
                alpha = int(255 * op * (1.0 - 0.62 * abs(frac - 0.25)))
                grad = QLinearGradient(0.0, 0.0, w, 0.0)
                for c_idx in range(max(2, len(self.active_colors))):
                    ct = c_idx / max(1, len(self.active_colors) - 1)
                    grad.setColorAt(ct, interpolate_palette(self.active_colors, ct, alpha))
                pen = QPen(grad, 1.7 if k in (2, 3) else 1.05)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                coords: list[tuple[float, float]] = []
                for p in range(pts):
                    t = p / max(1, pts - 1)
                    sym = abs(t * 2.0 - 1.0)
                    idx = min(n - 1, int(sym * (n - 1)))
                    val = float(self.values[idx])
                    phase = now * 0.6 + k * 0.22 + t * 4.5
                    wave = 0.65 + 0.35 * math.sin(phase)
                    depth_scale = 1.0 - frac * 0.55
                    y = h - 10.0 - max(4.0, val * s.bar_height * depth_scale * wave)
                    coords.append((t * w, y))
                path = QPainterPath()
                path.moveTo(coords[0][0], coords[0][1])
                for p in range(len(coords) - 1):
                    mx = (coords[p][0] + coords[p + 1][0]) * 0.5
                    my = (coords[p][1] + coords[p + 1][1]) * 0.5
                    path.quadTo(coords[p][0], coords[p][1], mx, my)
                path.lineTo(coords[-1][0], coords[-1][1])
                painter.drawPath(path)
            painter.setPen(Qt.PenStyle.NoPen)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        self._draw_ambient_edges(painter)
        self._draw_circular_visualizer(painter)
        self._draw_main_visualizer(painter)

        painter.end()

    def closeEvent(self, event) -> None:
        self.audio.stop()
        event.accept()


class NoWheelFilter(QObject):
    """Prevents sliders, spinboxes, and combos from hijacking scroll-area wheel events."""

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Wheel:
            event.ignore()
            return True
        return super().eventFilter(obj, event)


STYLESHEET = """
QDialog {
    background-color: #11131a;
    color: #e4e6eb;
    font-family: "Segoe UI", sans-serif;
    font-size: 13px;
}
QScrollArea, QWidget#scrollContent {
    background-color: #11131a;
    border: none;
}
QScrollBar:vertical {
    background: #141720;
    width: 8px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #2f3548;
    border-radius: 4px;
    min-height: 28px;
}
QScrollBar::handle:vertical:hover {
    background: #434b66;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QLabel#titleLabel {
    color: #f1f3f8;
    font-size: 17px;
    font-weight: 600;
}
QLabel#subtitleLabel {
    color: #82899b;
    font-size: 11px;
}
QLabel {
    color: #c8cdd8;
}
QSlider::groove:horizontal {
    height: 5px;
    background: #252936;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: #5b7cfa;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #e4e8f5;
    border: 2px solid #5b7cfa;
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}
QSlider::handle:horizontal:hover {
    background: #ffffff;
}
QLineEdit#numBox, QComboBox {
    background-color: #181b25;
    color: #eceef4;
    border: 1px solid #2b3040;
    border-radius: 6px;
    padding: 3px 6px;
    min-height: 22px;
}
QLineEdit#numBox:focus, QComboBox:focus {
    border: 1px solid #5b7cfa;
}
QComboBox QAbstractItemView {
    background-color: #181b25;
    color: #eceef4;
    selection-background-color: #364575;
}
QCheckBox, QRadioButton {
    color: #d6dae5;
    spacing: 8px;
}
QPushButton {
    background-color: #1b1f2b;
    color: #dce0ea;
    border: 1px solid #2d3345;
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #232838;
    border-color: #3f475e;
}
QPushButton:pressed {
    background-color: #161923;
}
QPushButton#applyBtn {
    background-color: #4f6ef7;
    color: #ffffff;
    border: 1px solid #5f7cf8;
    font-weight: 600;
}
QPushButton#applyBtn:hover {
    background-color: #5e7bf9;
}
"""


class SettingsDialog(QDialog):
    applied = Signal(Settings)

    def __init__(self, current: Settings, visualizer: Visualizer) -> None:
        super().__init__()
        self.visualizer = visualizer
        self.wheel_filter = NoWheelFilter(self)
        self.manual_colors = list(current.manual_colors) if len(current.manual_colors) == 5 else list(DEFAULT_COLORS)
        self._suppress_live = True
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(180)
        self._save_timer.timeout.connect(self._persist_current)
        self.setWindowTitle("Luma-Wave Settings")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setMinimumSize(560, 620)
        self.setStyleSheet(STYLESHEET)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title_lbl = QLabel("Luma-Wave")
        title_lbl.setObjectName("titleLabel")
        sub_lbl = QLabel("Audio Spectrum & Ambient Edge Overlay")
        sub_lbl.setObjectName("subtitleLabel")
        title_box.addWidget(title_lbl)
        title_box.addWidget(sub_lbl)
        header.addLayout(title_box)
        header.addStretch()
        self.power_btn = QPushButton()
        self.power_btn.setCheckable(True)
        self.power_btn.setChecked(current.enabled)
        self._style_power_btn()
        self.power_btn.toggled.connect(self._on_power_toggled)
        header.addWidget(self.power_btn)
        test_btn = QPushButton("Test 6s")
        test_btn.clicked.connect(visualizer.test_bars)
        header.addWidget(test_btn)
        root.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content.setObjectName("scrollContent")
        cards_layout = QVBoxLayout(content)
        cards_layout.setContentsMargins(0, 0, 8, 0)
        cards_layout.setSpacing(10)

        vis_card, vis_lay = self._make_card("Main Visualizer")
        vis_form = QFormLayout()
        self.main_style = QComboBox()
        self.main_style.installEventFilter(self.wheel_filter)
        for label, key in (
            ("Classic Symmetrical Bars", "bars"),
            ("Mirrored Center Waveform", "mirrored_bars"),
            ("LED Matrix Dots", "led_dots"),
            ("Thin Needle Spectrum", "needle_bars"),
            ("Layered Smooth Ribbon", "smooth_ribbon"),
            ("3D Silk Ribbon", "silk_3d"),
            ("Stacked Gradient Peaks", "area_peaks"),
            ("Off", "none"),
        ):
            self.main_style.addItem(label, key)
        self.main_style.setCurrentIndex(max(0, self.main_style.findData(current.main_style)))
        vis_form.addRow("Style:", self.main_style)
        vis_lay.addLayout(vis_form)
        self.s_width, self.n_width = self._add_slider_row(vis_lay, "Bar Thickness", 2, 60, current.bar_width)
        self.s_gap, self.n_gap = self._add_slider_row(vis_lay, "Bar Spacing", 0, 45, current.bar_gap)
        self.s_height, self.n_height = self._add_slider_row(vis_lay, "Max Height", 40, 650, current.bar_height)
        self.s_radius, self.n_radius = self._add_slider_row(vis_lay, "Corner Roundness", 0, 30, current.corner_radius)
        self.s_cgap, self.n_cgap = self._add_slider_row(vis_lay, "Center Gap", 0, 600, current.center_gap)
        self.s_main_op, self.n_main_op = self._add_slider_row(vis_lay, "Opacity (%)", 10, 100, current.main_opacity)
        cards_layout.addWidget(vis_card)

        amb_card, amb_lay = self._make_card("Ambient Edge Waves")
        amb_form = QFormLayout()
        self.ambient_style = QComboBox()
        self.ambient_style.installEventFilter(self.wheel_filter)
        for label, key in (
            ("3D Silk Ribbon", "silk_3d"),
            ("Spectrum Bars", "bars"),
            ("LED Matrix Dots", "led_dots"),
            ("Thin Needle Spectrum", "needle_bars"),
            ("Stacked Gradient Peaks", "area_peaks"),
        ):
            self.ambient_style.addItem(label, key)
        self.ambient_style.setCurrentIndex(max(0, self.ambient_style.findData(current.ambient_style)))
        amb_form.addRow("Edge Style:", self.ambient_style)
        amb_lay.addLayout(amb_form)
        edge_row = QHBoxLayout()
        edge_row.setContentsMargins(0, 4, 0, 4)
        self.chk_top = QCheckBox("Top"); self.chk_top.setChecked(current.ambient_top)
        self.chk_bottom = QCheckBox("Bottom"); self.chk_bottom.setChecked(current.ambient_bottom)
        self.chk_left = QCheckBox("Left"); self.chk_left.setChecked(current.ambient_left)
        self.chk_right = QCheckBox("Right"); self.chk_right.setChecked(current.ambient_right)
        self.chk_all = QCheckBox("All")
        self._syncing_edges = False
        for cb in (self.chk_top, self.chk_bottom, self.chk_left, self.chk_right):
            cb.setMinimumHeight(24)
            cb.toggled.connect(self._on_edge_changed)
            edge_row.addWidget(cb)
        self.chk_all.setMinimumHeight(24)
        self.chk_all.toggled.connect(self._on_all_edges_toggled)
        edge_row.addWidget(self.chk_all)
        edge_row.addStretch()
        self._on_edge_changed()
        amb_lay.addLayout(edge_row)
        self.s_amb_op, self.n_amb_op = self._add_slider_row(amb_lay, "Opacity (%)", 10, 95, current.ambient_opacity)
        self.s_amb_dep, self.n_amb_dep = self._add_slider_row(amb_lay, "Wave Reach (px)", 25, 350, current.ambient_depth)
        self.s_amb_thick, self.n_amb_thick = self._add_slider_row(amb_lay, "Line Thickness (px)", 1, 8, current.ambient_thickness)
        cards_layout.addWidget(amb_card)

        cir_card, cir_lay = self._make_card("Circular Visualizer")
        cir_form = QFormLayout()
        self.circle_style = QComboBox()
        self.circle_style.installEventFilter(self.wheel_filter)
        for label, key in (
            ("Off", "none"),
            ("Radial Bars", "radial_bars"),
            ("Segmented Dot Ring", "dot_ring"),
            ("Concentric Wave Rings", "wave_rings"),
            ("3D Mesh Rings", "mesh_3d"),
            ("Pulse Halo", "halo"),
        ):
            self.circle_style.addItem(label, key)
        self.circle_style.setCurrentIndex(max(0, self.circle_style.findData(current.circle_style)))
        cir_form.addRow("Style:", self.circle_style)
        cir_lay.addLayout(cir_form)
        self.s_cir_r, self.n_cir_r = self._add_slider_row(cir_lay, "Inner Radius (px)", 40, 450, current.circle_radius)
        self.s_cir_s, self.n_cir_s = self._add_slider_row(cir_lay, "Wave Reach (px)", 20, 350, current.circle_scale)
        self.s_cir_thick, self.n_cir_thick = self._add_slider_row(cir_lay, "Line / Bar Width (px)", 1, 16, current.circle_thickness)
        self.s_cir_op, self.n_cir_op = self._add_slider_row(cir_lay, "Opacity (%)", 10, 100, current.circle_opacity)
        cards_layout.addWidget(cir_card)

        col_card, col_lay = self._make_card("Color & Theme")
        col_form = QFormLayout()
        self.color_mode = QComboBox()
        self.color_mode.installEventFilter(self.wheel_filter)
        for label, key in (
            ("Auto (Active Screen Contrast)", "screen"),
            ("Auto (Desktop Wallpaper)", "wallpaper"),
            ("Preset / Custom", "manual"),
        ):
            self.color_mode.addItem(label, key)
        mode_key = "wallpaper" if current.color_mode == "auto" else current.color_mode
        self.color_mode.setCurrentIndex(max(0, self.color_mode.findData(mode_key)))
        self.color_mode.currentIndexChanged.connect(self._refresh_color_buttons)
        col_form.addRow("Color Source:", self.color_mode)

        self.color_preset = QComboBox()
        self.color_preset.installEventFilter(self.wheel_filter)
        for name in COLOR_PRESETS:
            self.color_preset.addItem(name, name)
        self.color_preset.addItem("Custom", "Custom")
        self.color_preset.setCurrentIndex(max(0, self.color_preset.findData(current.color_preset)))
        self.color_preset.currentIndexChanged.connect(self._on_preset_selected)
        col_form.addRow("Theme Preset:", self.color_preset)
        col_lay.addLayout(col_form)

        self.chk_flow = QCheckBox("Animated Color Flow")
        self.chk_flow.setChecked(current.color_flow)
        col_lay.addWidget(self.chk_flow)

        swatch_row = QHBoxLayout()
        swatch_row.setSpacing(8)
        self.color_btns: list[QPushButton] = []
        for idx in range(5):
            btn = QPushButton(f"Color {idx + 1}")
            btn.setMinimumHeight(32)
            btn.clicked.connect(lambda _=False, i=idx: self._pick_color(i))
            self.color_btns.append(btn)
            swatch_row.addWidget(btn)
        col_lay.addLayout(swatch_row)
        self._refresh_color_buttons()
        cards_layout.addWidget(col_card)

        dev_card, dev_lay = self._make_card("Audio & Display")
        form = QFormLayout()
        form.setSpacing(8)
        self.audio = QComboBox()
        self.audio.installEventFilter(self.wheel_filter)
        self.audio.addItem("System default output (recommended)", "default")
        try:
            for item in AudioEngine.loopback_devices():
                self.audio.addItem(item["name"].replace(" [Loopback]", ""), str(item["index"]))
        except Exception as exc:
            self.audio.addItem(f"Device scan failed: {exc}", "default")
        self.audio.setCurrentIndex(max(0, self.audio.findData(current.audio_device)))
        form.addRow("Output Device:", self.audio)

        self.monitor = QComboBox()
        self.monitor.installEventFilter(self.wheel_filter)
        for index, screen in enumerate(QGuiApplication.screens()):
            rect = screen.availableGeometry()
            self.monitor.addItem(f"Display {index + 1} — {rect.width()} × {rect.height()}", index)
        self.monitor.setCurrentIndex(min(current.monitor, max(0, self.monitor.count() - 1)))
        form.addRow("Target Display:", self.monitor)

        self.topmost = QCheckBox("Keep visualizer above applications")
        self.topmost.setChecked(current.always_on_top)
        self.chk_cursor = QCheckBox("Cursor interactive (stretch waves on hover)")
        self.chk_cursor.setChecked(current.cursor_react)
        self.demo = QCheckBox("Demo bars (does not use audio)")
        self.demo.setChecked(current.test_mode)
        form.addRow("Overlay:", self.topmost)
        form.addRow("Interaction:", self.chk_cursor)
        form.addRow("Diagnostics:", self.demo)
        dev_lay.addLayout(form)

        self.status_lbl = QLabel(self._status_text())
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setStyleSheet("color: #8ab4f8; font-size: 12px;")
        dev_lay.addWidget(self.status_lbl)
        cards_layout.addWidget(dev_card)

        cards_layout.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        footer = QHBoxLayout()
        reset_btn = QPushButton("Reset Defaults")
        reset_btn.clicked.connect(self._reset_defaults)
        auto_lbl = QLabel("Changes apply & save live")
        auto_lbl.setStyleSheet("color: #7d8599; font-size: 11px;")
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        footer.addWidget(reset_btn)
        footer.addSpacing(10)
        footer.addWidget(auto_lbl)
        footer.addStretch()
        footer.addWidget(close_btn)
        root.addLayout(footer)

        self._wire_live_updates()
        self.visualizer.palette_changed.connect(self._apply_swatch_colors)
        self._suppress_live = False

    @staticmethod
    def _make_card(title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("card")
        card.setStyleSheet("QFrame#card { background-color: #161923; border: 1px solid #242938; border-radius: 10px; }")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 10, 14, 12)
        lay.setSpacing(8)
        lbl = QLabel(title)
        lbl.setStyleSheet("color: #9ba5bd; font-size: 12px; font-weight: 600;")
        lay.addWidget(lbl)
        return card, lay

    def _add_slider_row(self, parent: QVBoxLayout, label: str, lo: int, hi: int, val: int) -> tuple[QSlider, QLineEdit]:
        row = QHBoxLayout()
        lbl = QLabel(f"{label}:")
        lbl.setMinimumWidth(140)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(lo, hi)
        slider.setValue(val)
        slider.installEventFilter(self.wheel_filter)
        box = QLineEdit(str(val))
        box.setObjectName("numBox")
        box.setValidator(QIntValidator(lo, hi, box))
        box.setFixedWidth(58)
        box.setAlignment(Qt.AlignmentFlag.AlignCenter)

        def on_slider(v: int) -> None:
            if box.text() != str(v):
                box.setText(str(v))

        def on_box_edit() -> None:
            txt = box.text().strip()
            if txt.isdigit():
                v = max(lo, min(hi, int(txt)))
                if slider.value() != v:
                    slider.setValue(v)

        slider.valueChanged.connect(on_slider)
        box.editingFinished.connect(on_box_edit)
        row.addWidget(lbl)
        row.addWidget(slider, 1)
        row.addWidget(box)
        parent.addLayout(row)
        return slider, box

    def _on_edge_changed(self) -> None:
        if self._syncing_edges:
            return
        self._syncing_edges = True
        all_on = all(c.isChecked() for c in (self.chk_top, self.chk_bottom, self.chk_left, self.chk_right))
        self.chk_all.setChecked(all_on)
        self._syncing_edges = False

    def _on_all_edges_toggled(self, checked: bool) -> None:
        if self._syncing_edges:
            return
        self._syncing_edges = True
        for c in (self.chk_top, self.chk_bottom, self.chk_left, self.chk_right):
            c.setChecked(checked)
        self._syncing_edges = False

    def _style_power_btn(self) -> None:
        on = self.power_btn.isChecked()
        self.power_btn.setText("Visualizer: ON" if on else "Visualizer: OFF")
        if on:
            self.power_btn.setStyleSheet(
                "QPushButton { background-color: #163329; color: #5ce0a8; border: 1px solid #26614d; border-radius: 6px; padding: 6px 12px; font-weight: 600; }"
                "QPushButton:hover { background-color: #1d4235; }"
            )
        else:
            self.power_btn.setStyleSheet(
                "QPushButton { background-color: #2b1d24; color: #e88b9c; border: 1px solid #593341; border-radius: 6px; padding: 6px 12px; font-weight: 600; }"
                "QPushButton:hover { background-color: #38252e; }"
            )

    def _on_power_toggled(self) -> None:
        self._style_power_btn()
        self._on_live_change()

    def _apply_swatch_colors(self, palette: list[str]) -> None:
        mode = self.color_mode.currentData() if hasattr(self, "color_mode") else "screen"
        is_manual = (mode == "manual")
        key = (tuple(palette), is_manual)
        if getattr(self, "_last_swatch_key", None) == key:
            return
        self._last_swatch_key = key
        for idx, btn in enumerate(self.color_btns):
            hex_c = palette[idx] if idx < len(palette) else DEFAULT_COLORS[idx]
            qc = QColor(hex_c)
            text_c = "#101218" if qc.lightness() > 135 else "#f4f6fc"
            btn.setEnabled(is_manual)
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {hex_c}; color: {text_c}; "
                f"border: 1px solid #353b4f; border-radius: 6px; font-weight: 600; }}"
            )

    def _on_preset_selected(self) -> None:
        name = self.color_preset.currentData()
        if name in COLOR_PRESETS:
            self.manual_colors = list(COLOR_PRESETS[name])
            self.color_mode.setCurrentIndex(max(0, self.color_mode.findData("manual")))
        self._refresh_color_buttons()

    def _refresh_color_buttons(self) -> None:
        mode = self.color_mode.currentData() if hasattr(self, "color_mode") else "screen"
        if mode == "screen":
            palette = extract_screen_colors(self.monitor.currentData() if hasattr(self, "monitor") else 0, 5)
        elif mode == "wallpaper":
            palette = extract_wallpaper_colors(5)
        else:
            palette = self.manual_colors
        self._apply_swatch_colors(palette)

    def _wire_live_updates(self) -> None:
        for slider in (
            self.s_width, self.s_gap, self.s_height, self.s_radius, self.s_cgap, self.s_main_op,
            self.s_amb_op, self.s_amb_dep, self.s_amb_thick,
            self.s_cir_r, self.s_cir_s, self.s_cir_thick, self.s_cir_op,
        ):
            slider.valueChanged.connect(self._on_live_change)
        for combo in (
            self.main_style, self.ambient_style, self.circle_style,
            self.color_mode, self.color_preset, self.audio, self.monitor,
        ):
            combo.currentIndexChanged.connect(self._on_live_change)
        for chk in (
            self.chk_top, self.chk_bottom, self.chk_left, self.chk_right,
            self.chk_flow, self.chk_cursor, self.topmost, self.demo,
        ):
            chk.toggled.connect(self._on_live_change)

    def _on_live_change(self, *_args) -> None:
        if self._suppress_live:
            return
        self._apply(persist=False)
        self._save_timer.start()

    def _persist_current(self) -> None:
        save_settings(self._build_settings())

    def _pick_color(self, idx: int) -> None:
        chosen = QColorDialog.getColor(QColor(self.manual_colors[idx]), self, f"Pick Color {idx + 1}")
        if chosen.isValid():
            self.manual_colors[idx] = chosen.name()
            self._refresh_color_buttons()
            self._on_live_change()

    def _status_text(self) -> str:
        if self.visualizer.audio.error:
            return f"Warning: {self.visualizer.audio.error}"
        return f"Listening to: {self.visualizer.audio.device_label}"

    def _build_settings(self) -> Settings:
        return Settings(
            enabled=self.power_btn.isChecked(),
            audio_device=self.audio.currentData(),
            monitor=self.monitor.currentData(),
            main_style=self.main_style.currentData(),
            bar_width=self.s_width.value(),
            bar_gap=self.s_gap.value(),
            bar_height=self.s_height.value(),
            corner_radius=self.s_radius.value(),
            center_gap=self.s_cgap.value(),
            main_opacity=self.s_main_op.value(),
            color_mode=self.color_mode.currentData(),
            color_preset=self.color_preset.currentData(),
            color_flow=self.chk_flow.isChecked(),
            manual_colors=list(self.manual_colors),
            ambient_style=self.ambient_style.currentData(),
            ambient_top=self.chk_top.isChecked(),
            ambient_bottom=self.chk_bottom.isChecked(),
            ambient_left=self.chk_left.isChecked(),
            ambient_right=self.chk_right.isChecked(),
            ambient_opacity=self.s_amb_op.value(),
            ambient_depth=self.s_amb_dep.value(),
            ambient_thickness=self.s_amb_thick.value(),
            circle_style=self.circle_style.currentData(),
            circle_radius=self.s_cir_r.value(),
            circle_scale=self.s_cir_s.value(),
            circle_thickness=self.s_cir_thick.value(),
            circle_opacity=self.s_cir_op.value(),
            cursor_react=self.chk_cursor.isChecked(),
            always_on_top=self.topmost.isChecked(),
            test_mode=self.demo.isChecked(),
        )

    def _apply(self, persist: bool = True) -> None:
        settings = self._build_settings()
        self.visualizer.apply_settings(settings, persist=persist, restart_audio=False)
        self.status_lbl.setText(self._status_text())
        self.applied.emit(settings)

    def _reset_defaults(self) -> None:
        d = Settings()
        self._suppress_live = True
        self.power_btn.setChecked(d.enabled)
        self._style_power_btn()
        self.main_style.setCurrentIndex(max(0, self.main_style.findData(d.main_style)))
        self.s_width.setValue(d.bar_width)
        self.s_gap.setValue(d.bar_gap)
        self.s_height.setValue(d.bar_height)
        self.s_radius.setValue(d.corner_radius)
        self.s_cgap.setValue(d.center_gap)
        self.s_main_op.setValue(d.main_opacity)
        self.color_mode.setCurrentIndex(max(0, self.color_mode.findData(d.color_mode)))
        self.color_preset.setCurrentIndex(max(0, self.color_preset.findData(d.color_preset)))
        self.chk_flow.setChecked(d.color_flow)
        self.manual_colors = list(DEFAULT_COLORS)
        self._refresh_color_buttons()
        self.ambient_style.setCurrentIndex(max(0, self.ambient_style.findData(d.ambient_style)))
        self.chk_all.setChecked(False)
        self.s_amb_op.setValue(d.ambient_opacity)
        self.s_amb_dep.setValue(d.ambient_depth)
        self.s_amb_thick.setValue(d.ambient_thickness)
        self.circle_style.setCurrentIndex(max(0, self.circle_style.findData(d.circle_style)))
        self.s_cir_r.setValue(d.circle_radius)
        self.s_cir_s.setValue(d.circle_scale)
        self.s_cir_thick.setValue(d.circle_thickness)
        self.s_cir_op.setValue(d.circle_opacity)
        self.chk_cursor.setChecked(d.cursor_react)
        self.topmost.setChecked(d.always_on_top)
        self.demo.setChecked(d.test_mode)
        self._suppress_live = False
        self._apply(persist=True)


class Tray:
    def __init__(self, app: QApplication, visualizer: Visualizer) -> None:
        self.app, self.visualizer = app, visualizer
        self.dialog: SettingsDialog | None = None
        self.icon = QSystemTrayIcon(self._make_icon(), app)
        self.icon.setToolTip("Luma-Wave — audio visualizer")
        menu = QMenu()
        self.toggle_action = QAction("Turn Off Visualizer" if visualizer.settings.enabled else "Turn On Visualizer", menu)
        self.toggle_action.triggered.connect(self.toggle_visualizer)
        settings = QAction("Settings…", menu); settings.triggered.connect(self.open_settings)
        test = QAction("Test bars", menu); test.triggered.connect(visualizer.test_bars)
        quit_action = QAction("Exit", menu); quit_action.triggered.connect(app.quit)
        menu.addAction(self.toggle_action); menu.addAction(settings); menu.addAction(test); menu.addSeparator(); menu.addAction(quit_action)
        self.icon.setContextMenu(menu)
        self.icon.activated.connect(self._on_activated)
        self.icon.show()

    def toggle_visualizer(self) -> None:
        s = self.visualizer.settings
        s.enabled = not s.enabled
        self.visualizer.apply_settings(s, persist=True, restart_audio=False)
        self.toggle_action.setText("Turn Off Visualizer" if s.enabled else "Turn On Visualizer")
        if self.dialog is not None and self.dialog.isVisible():
            self.dialog._suppress_live = True
            self.dialog.power_btn.setChecked(s.enabled)
            self.dialog._style_power_btn()
            self.dialog._suppress_live = False

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.DoubleClick, QSystemTrayIcon.ActivationReason.Trigger):
            self.open_settings()

    @staticmethod
    def _make_icon() -> QIcon:
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        for index, height in enumerate((10, 18, 26, 15, 22)):
            painter.setBrush(QColor.fromHsv(225 - index * 12, 190, 255))
            painter.drawRoundedRect(3 + index * 6, 29 - height, 4, height, 2, 2)
        painter.end()
        return QIcon(pixmap)

    def open_settings(self) -> None:
        if self.dialog is not None and self.dialog.isVisible():
            self.dialog.raise_()
            self.dialog.activateWindow()
            return
        self.dialog = SettingsDialog(self.visualizer.settings, self.visualizer)
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    is_first_run = not CONFIG_FILE.exists()
    visualizer = Visualizer(load_settings())
    tray = Tray(app, visualizer)
    visualizer.show()
    if is_first_run:
        QTimer.singleShot(0, tray.open_settings)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
