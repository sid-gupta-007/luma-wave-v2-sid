"""Luma-Wave desktop audio visualizer entry point."""
from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from lumawave.config import CONFIG_FILE, load_settings
from lumawave.tray import Tray
from lumawave.visualizer import Visualizer


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
