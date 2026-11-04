"""Splash-first project launcher used by the editor, player and CLI.

The splash is enforced by the engine process, not by project code. Running a
project through this module plays the intro even if its ``main.py`` was edited
to call pygame directly or passed ``splash=False``; the process-wide
``splash_played()`` marker then prevents the intro from playing twice when the
project itself uses :class:`reasonable.runtime.App`.

Usage::

    python -m reasonable.runtime.launch path/to/main.py
"""

from __future__ import annotations

import json
import os
import runpy
import sys
from pathlib import Path


def _window_size(entry: Path) -> tuple[int, int]:
    try:
        data = json.loads((entry.parent / "project.json").read_text(encoding="utf-8"))
        window = data.get("window") if isinstance(data, dict) else {}
        return (
            max(320, int((window or {}).get("width") or 1280)),
            max(240, int((window or {}).get("height") or 720)),
        )
    except (OSError, ValueError, TypeError):
        return (1280, 720)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("Reasonable Engine: pass the project's main.py path.", file=sys.stderr)
        return 2
    entry = Path(args[0]).expanduser()
    if not entry.is_file():
        print(f"Reasonable Engine: entry point not found: {entry}", file=sys.stderr)
        return 2
    entry = entry.resolve()
    root = entry.parent
    previous_cwd = Path.cwd()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    os.chdir(root)
    try:
        from .splash import play_splash

        if not play_splash(_window_size(entry)):
            return 0
        sys.argv = [str(entry), *args[1:]]
        runpy.run_path(str(entry), run_name="__main__")
    finally:
        os.chdir(previous_cwd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
