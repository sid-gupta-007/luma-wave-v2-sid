"""Auto-bump patch version in lumawave/__init__.py on commit unless manually changed."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

INIT_FILE = Path("lumawave/__init__.py")


def main() -> int:
    diff = subprocess.check_output(
        ["git", "diff", "--cached", "--", str(INIT_FILE)],
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if any(line.startswith("+APP_VERSION") for line in diff.splitlines()):
        return 0

    text = INIT_FILE.read_text(encoding="utf-8")
    match = re.search(r'(APP_VERSION\s*=\s*")(\d+)\.(\d+)\.(\d+)(")', text)
    if not match:
        return 0

    major, minor, patch = int(match.group(2)), int(match.group(3)), int(match.group(4))
    old_ver = f"{major}.{minor}.{patch}"
    new_ver = f"{major}.{minor}.{patch + 1}"
    updated = text[: match.start()] + f'{match.group(1)}{new_ver}{match.group(5)}' + text[match.end() :]
    INIT_FILE.write_text(updated, encoding="utf-8")
    subprocess.check_call(["git", "add", str(INIT_FILE)])
    print(f"Auto-bumped APP_VERSION: {old_ver} -> {new_ver}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

