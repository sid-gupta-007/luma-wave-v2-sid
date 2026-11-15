from __future__ import annotations

import ctypes
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QImageReader

from .config import DEFAULT_COLORS

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
            if screen_luma < 0.70:
                target_v = 0.98
                target_s = min(1.0, max(0.68, s_val + 0.35))
            else:
                target_v = 0.38
                target_s = min(1.0, max(0.75, s_val + 0.35))
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


