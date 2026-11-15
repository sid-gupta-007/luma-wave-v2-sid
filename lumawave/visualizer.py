from __future__ import annotations

import math
import time

import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from .audio import AudioEngine
from .colors import extract_screen_colors, extract_wallpaper_colors, interpolate_palette
from .config import DEFAULT_COLORS, Settings, save_settings


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
        self._device_tick = 0
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
        s = self.settings
        need_main = s.main_style != "none" or s.circle_style != "none"
        need_ambient = s.ambient_style != "none" and (s.ambient_top or s.ambient_bottom or s.ambient_left or s.ambient_right)
        is_demo = s.test_mode or time.monotonic() < self.test_until
        if is_demo:
            phase = time.monotonic() * 3.2
            target = np.array([
                (0.22 + 0.72 * abs(math.sin(phase + i * 0.24))) * (1.0 - 0.55 * (i / max(1, n - 1)))
                for i in range(n)
            ], dtype=np.float32) if need_main else np.zeros(n, dtype=np.float32)
            amb_target = np.array([
                0.22 + 0.65 * (0.5 + 0.5 * math.sin(phase * 0.8 + i * 0.42))
                for i in range(len(self.ambient_values))
            ], dtype=np.float32) if need_ambient else np.zeros(len(self.ambient_values), dtype=np.float32)
        else:
            self._device_tick += 1
            if self._device_tick >= 120:
                self._device_tick = 0
                self.audio.check_device_async()
            target = self.audio.spectrum(n) if need_main else np.zeros(n, dtype=np.float32)
            if need_ambient:
                raw_amb = self.audio.spectrum(len(self.ambient_values))
                amb_target = np.convolve(np.pad(raw_amb, 1, mode="edge"), [0.25, 0.5, 0.25], mode="valid")
            else:
                amb_target = np.zeros(len(self.ambient_values), dtype=np.float32)

        self.values += (target - self.values) * 0.24
        self.ambient_values += (amb_target - self.ambient_values) * 0.14
        if s.cursor_react:
            self.cursor_local = self.mapFromGlobal(QCursor.pos())
        else:
            self.cursor_local = None
        if s.color_flow:
            self._color_phase = (self._color_phase + 0.0022) % 1.0
        if s.color_mode == "screen":
            self._screen_tick += 1
            if self._screen_tick >= 60:
                self._screen_tick = 0
                self.refresh_palette(smooth=True)
        if len(self.active_colors) == len(self.target_colors):
            for idx, (cur, tgt) in enumerate(zip(self.active_colors, self.target_colors)):
                if cur != tgt:
                    self.active_colors[idx] = QColor(
                        int(cur.red() + (tgt.red() - cur.red()) * 0.35),
                        int(cur.green() + (tgt.green() - cur.green()) * 0.35),
                        int(cur.blue() + (tgt.blue() - cur.blue()) * 0.35),
                    )
        self.update()

    def _draw_ambient_edges(self, painter: QPainter) -> None:
        s = self.settings
        if s.ambient_style == "none" or not (s.ambient_top or s.ambient_bottom or s.ambient_left or s.ambient_right):
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


