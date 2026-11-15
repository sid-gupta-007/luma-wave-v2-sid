from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import APP_NAME, APP_VERSION
from .config import save_settings
from .settings_ui import SettingsDialog
from .updater import Updater
from .visualizer import Visualizer


class Tray:
    def __init__(self, app: QApplication, visualizer: Visualizer) -> None:
        self.app, self.visualizer = app, visualizer
        self.dialog: SettingsDialog | None = None
        self.updater = Updater()
        self.updater.check_finished.connect(self._on_update_checked)
        self.updater.install_failed.connect(self._on_update_failed)

        app_icon = self._make_icon()
        app.setWindowIcon(app_icon)
        self.icon = QSystemTrayIcon(app_icon, app)
        self.icon.setToolTip(f"{APP_NAME} v{APP_VERSION} — audio visualizer")
        menu = QMenu()
        self.toggle_action = QAction("Turn Off Visualizer" if visualizer.settings.enabled else "Turn On Visualizer", menu)
        self.toggle_action.triggered.connect(self.toggle_visualizer)
        settings = QAction("Settings…", menu)
        settings.triggered.connect(self.open_settings)
        test = QAction("Test bars", menu)
        test.triggered.connect(visualizer.test_bars)
        self.update_action = QAction("Check for Update…", menu)
        self.update_action.triggered.connect(self.check_for_update)
        quit_action = QAction("Exit", menu)
        quit_action.triggered.connect(app.quit)

        menu.addAction(self.toggle_action)
        menu.addAction(settings)
        menu.addAction(test)
        menu.addSeparator()
        menu.addAction(self.update_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.icon.setContextMenu(menu)
        self.icon.activated.connect(self._on_activated)
        self.icon.show()
        QTimer.singleShot(2500, lambda: self.updater.check_async(silent=True))

    def check_for_update(self) -> None:
        self.update_action.setEnabled(False)
        self.update_action.setText("Checking for Update…")
        self.updater.check_async(silent=False)

    def _on_update_checked(self, status: str, tag: str, zip_url: str, silent: bool) -> None:
        self.update_action.setEnabled(True)
        self.update_action.setText("Check for Update…")
        parent = self.dialog if (self.dialog is not None and self.dialog.isVisible()) else None
        if status == "found":
            if silent and tag == self.visualizer.settings.skipped_version:
                return
            reply = QMessageBox.question(
                parent,
                "Update Available",
                f"{APP_NAME} {tag} is available (you have v{APP_VERSION}).\n\nDownload and install the update automatically?",
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.update_action.setEnabled(False)
                self.update_action.setText("Updating…")
                self.updater.download_and_install_async(
                    zip_url,
                    lambda: QTimer.singleShot(0, self.app.quit),
                )
            else:
                self.visualizer.settings.skipped_version = tag
                save_settings(self.visualizer.settings)
        elif silent:
            return
        elif status == "current":
            QMessageBox.information(parent, "Up to Date", f"You are running the latest version ({tag}).")
        else:
            QMessageBox.information(
                parent,
                "No Internet Connection",
                "You appear to be offline. Please turn on your internet connection and check again.",
            )

    def _on_update_failed(self, message: str) -> None:
        self.update_action.setEnabled(True)
        self.update_action.setText("Check for Update…")
        parent = self.dialog if (self.dialog is not None and self.dialog.isVisible()) else None
        QMessageBox.warning(parent, "Update Error", message)

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
        ico_path = Path(__file__).resolve().parent / "assets" / "app.ico"
        if ico_path.exists():
            icon = QIcon(str(ico_path))
            if not icon.isNull():
                return icon
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
        self.dialog = SettingsDialog(self.visualizer.settings, self.visualizer, on_check_updates=self.check_for_update)
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
