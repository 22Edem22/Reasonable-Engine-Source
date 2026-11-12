"""__APP_TITLE__ — a plain Python project.

Works on Windows and Linux:

    python main.py
    python main.py --check

No pygame and no engine splash are used here. Replace this skeleton with the
real program; keep `--check` working so the editor can verify it.
"""

from __future__ import annotations

import argparse
import sys


def run() -> int:
    print("__APP_TITLE__ is ready. Edit main.py to build the real project.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="__APP_TITLE__")
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify that the project imports and starts, then exit",
    )
    args = parser.parse_args(argv)
    if args.check:
        print("OK")
        return 0
    try:
        return run()
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
