from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
import zipfile
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from . import APP_VERSION, GITHUB_REPO


def parse_version(tag: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", tag)
    return tuple(int(n) for n in nums[:3]) if nums else (0,)


class Updater(QObject):
    """Checks GitHub Releases and performs in-place self-updates for frozen builds."""

    check_finished = Signal(str, str, str)
    install_failed = Signal(str)

    def check_async(self) -> None:
        def worker() -> None:
            url = f"https://api.github.com/repos/{GITHUB_REPO}/releases?per_page=8"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": f"LumaWave/{APP_VERSION}"})
                with urllib.request.urlopen(req, timeout=6) as resp:
                    releases = json.loads(resp.read().decode("utf-8"))
                best_tag = ""
                best_ver = parse_version(APP_VERSION)
                best_zip = ""
                for rel in releases:
                    if rel.get("draft"):
                        continue
                    tag = str(rel.get("tag_name", ""))
                    ver = parse_version(tag)
                    if ver > best_ver:
                        zip_url = ""
                        for asset in rel.get("assets", []):
                            name = str(asset.get("name", "")).lower()
                            if name.endswith(".zip"):
                                zip_url = str(asset.get("browser_download_url", ""))
                                break
                        if zip_url:
                            best_ver = ver
                            best_tag = tag
                            best_zip = zip_url
                if best_tag and best_zip:
                    self.check_finished.emit("found", best_tag, best_zip)
                else:
                    self.check_finished.emit("current", f"v{APP_VERSION}", "")
            except Exception:
                self.check_finished.emit("offline", "", "")

        threading.Thread(target=worker, daemon=True).start()

    def download_and_install_async(self, zip_url: str, on_ready_to_quit) -> None:
        if not getattr(sys, "frozen", False):
            self.install_failed.emit("Auto-update only applies to the packaged LumaWave.exe build. Use 'git pull' when running from source.")
            return

        app_dir = Path(sys.executable).resolve().parent
        exe_name = Path(sys.executable).name

        def worker() -> None:
            stage = Path(tempfile.gettempdir()) / "lumawave_update"
            try:
                if stage.exists():
                    shutil.rmtree(stage, ignore_errors=True)
                stage.mkdir(parents=True, exist_ok=True)
                zip_path = stage / "update.zip"
                extract_dir = stage / "extracted"

                req = urllib.request.Request(zip_url, headers={"User-Agent": f"LumaWave/{APP_VERSION}"})
                with urllib.request.urlopen(req, timeout=60) as resp, open(zip_path, "wb") as out:
                    shutil.copyfileobj(resp, out)

                with zipfile.ZipFile(zip_path, "r") as zf:
                    zf.extractall(extract_dir)

                # Handle zips that either wrap files in a top folder or place LumaWave.exe at root
                src_dir = extract_dir
                if not (src_dir / exe_name).exists():
                    children = [p for p in extract_dir.iterdir() if p.is_dir()]
                    if len(children) == 1 and (children[0] / exe_name).exists():
                        src_dir = children[0]

                if not (src_dir / exe_name).exists():
                    raise RuntimeError("Downloaded archive does not contain LumaWave.exe.")

                bat_path = stage / "apply_update.bat"
                pid = os.getpid()
                bat_content = (
                    "@echo off\r\n"
                    f"set \"PID={pid}\"\r\n"
                    ":waitloop\r\n"
                    "tasklist /FI \"PID eq %PID%\" 2>NUL | find /I \"%PID%\" >NUL\r\n"
                    "if not errorlevel 1 (\r\n"
                    "  timeout /t 1 /nobreak >NUL\r\n"
                    "  goto waitloop\r\n"
                    ")\r\n"
                    f"robocopy \"{src_dir}\" \"{app_dir}\" /E /IS /IT /R:5 /W:1 >NUL\r\n"
                    f"start \"\" \"{app_dir / exe_name}\"\r\n"
                    f"rmdir /s /q \"{stage}\" 2>NUL\r\n"
                )
                bat_path.write_text(bat_content, encoding="utf-8")

                flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
                subprocess.Popen(["cmd.exe", "/c", str(bat_path)], creationflags=flags)
                on_ready_to_quit()
            except Exception as exc:
                self.install_failed.emit(f"Update failed: {exc}")

        threading.Thread(target=worker, daemon=True).start()

