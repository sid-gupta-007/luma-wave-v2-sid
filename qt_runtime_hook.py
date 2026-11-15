"""Register PySide6's private DLL directory before the application imports Qt.

PyInstaller's Windows loader adds ``_internal`` but not necessarily its
``PySide6`` child.  QtCore.pyd then risks binding to an unrelated Qt DLL on
PATH, which surfaces as "The specified procedure could not be found".
"""
import os
import sys

if getattr(sys, "frozen", False):
    pyside_dir = os.path.join(sys._MEIPASS, "PySide6")
    if os.path.isdir(pyside_dir):
        os.add_dll_directory(pyside_dir)
