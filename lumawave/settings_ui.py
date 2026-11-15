from __future__ import annotations

import json
import re
import threading
import urllib.request

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication, QIntValidator
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea,
    QSlider, QVBoxLayout, QWidget,
)

from . import APP_VERSION, GITHUB_REPO
from .audio import AudioEngine
from .colors import extract_screen_colors, extract_wallpaper_colors
from .config import (
    COLOR_PRESETS, DEFAULT_COLORS, Settings, is_windows_startup_enabled,
    save_settings, set_windows_startup,
)
from .visualizer import Visualizer


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
        self.setWindowTitle(f"Luma-Wave v{APP_VERSION} — Settings")
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
        sub_lbl = QLabel(f"v{APP_VERSION} • Audio Spectrum & Ambient Edge Overlay")
        sub_lbl.setObjectName("subtitleLabel")
        title_box.addWidget(title_lbl)
        title_box.addWidget(sub_lbl)
        header.addLayout(title_box)
        header.addStretch()
        self.power_btn = QPushButton()
        self.power_btn.setCheckable(True)
        self.power_btn.setAutoDefault(False)
        self.power_btn.setDefault(False)
        self.power_btn.setChecked(current.enabled)
        self._style_power_btn()
        self.power_btn.toggled.connect(self._on_power_toggled)
        header.addWidget(self.power_btn)
        test_btn = QPushButton("Test 6s")
        test_btn.setAutoDefault(False)
        test_btn.setDefault(False)
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
            btn.setAutoDefault(False)
            btn.setDefault(False)
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
        self.chk_startup = QCheckBox("Start with Windows (auto-launch on sign-in)")
        self.chk_startup.setChecked(is_windows_startup_enabled())
        self.chk_startup.toggled.connect(set_windows_startup)
        self.chk_cursor = QCheckBox("Cursor interactive (stretch waves on hover)")
        self.chk_cursor.setChecked(current.cursor_react)
        self.demo = QCheckBox("Demo bars (does not use audio)")
        self.demo.setChecked(current.test_mode)
        form.addRow("Overlay:", self.topmost)
        form.addRow("Startup:", self.chk_startup)
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
        reset_btn.setAutoDefault(False)
        reset_btn.setDefault(False)
        reset_btn.clicked.connect(self._reset_defaults)
        auto_lbl = QLabel("Changes apply & save live")
        auto_lbl.setStyleSheet("color: #7d8599; font-size: 11px;")
        close_btn = QPushButton("Close")
        close_btn.setAutoDefault(False)
        close_btn.setDefault(False)
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
        box.setFixedWidth(50)
        box.setAlignment(Qt.AlignmentFlag.AlignCenter)

        btn_down = QPushButton("−")
        btn_down.setAutoDefault(False)
        btn_down.setDefault(False)
        btn_down.setAutoRepeat(True)
        btn_down.setFixedSize(26, 28)
        btn_down.setStyleSheet("padding: 0px; font-weight: 700;")

        btn_up = QPushButton("+")
        btn_up.setAutoDefault(False)
        btn_up.setDefault(False)
        btn_up.setAutoRepeat(True)
        btn_up.setFixedSize(26, 28)
        btn_up.setStyleSheet("padding: 0px; font-weight: 700;")

        def on_slider(v: int) -> None:
            if box.text() != str(v):
                box.setText(str(v))

        def on_box_edit() -> None:
            txt = box.text().strip()
            if txt.isdigit():
                v = max(lo, min(hi, int(txt)))
                if box.text() != str(v):
                    box.setText(str(v))
                if slider.value() != v:
                    slider.setValue(v)

        btn_down.clicked.connect(lambda: slider.setValue(max(lo, slider.value() - 1)))
        btn_up.clicked.connect(lambda: slider.setValue(min(hi, slider.value() + 1)))
        slider.valueChanged.connect(on_slider)
        box.returnPressed.connect(on_box_edit)
        box.editingFinished.connect(on_box_edit)
        row.addWidget(lbl)
        row.addWidget(slider, 1)
        row.addWidget(btn_down)
        row.addWidget(box)
        row.addWidget(btn_up)
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
        self.chk_startup.setChecked(False)
        set_windows_startup(False)
        self.topmost.setChecked(d.always_on_top)
        self.demo.setChecked(d.test_mode)
        self._suppress_live = False
        self._apply(persist=True)


