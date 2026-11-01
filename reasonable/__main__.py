"""Launch the Reasonable Engine editor with ``python -m reasonable``."""

from __future__ import annotations

import sys


def _run() -> int:
    if "--version" in sys.argv or "-V" in sys.argv:
        from reasonable.version import VERSION, VERSION_NAME

        print(f"Reasonable Engine {VERSION} «{VERSION_NAME}»")
        return 0
    try:
        from reasonable.editor import main
    except ImportError as exc:
        print(
            "Reasonable Engine: не удалось загрузить редактор.\n"
            f"Причина: {exc}\n\n"
            "Установите зависимости:\n"
            "  python -m pip install -r requirements.txt\n",
            file=sys.stderr,
        )
        return 1
    return main()


if __name__ == "__main__":
    raise SystemExit(_run())
