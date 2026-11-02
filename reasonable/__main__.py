"""Launch the Reasonable Engine editor with ``python -m reasonable``."""

from __future__ import annotations

import sys


def _run() -> int:
    if "--version" in sys.argv or "-V" in sys.argv:
        from reasonable.version import VERSION_LABEL

        print(f"Reasonable Engine {VERSION_LABEL}")
        return 0
    try:
        from reasonable.editor import main
    except ImportError as exc:
        try:
            from reasonable.core.i18n import tr as _tr
        except Exception:  # i18n itself failed to import — English fallback
            _tr = None
        if _tr is not None:
            text = (
                _tr("Reasonable Engine: could not load the editor.\n",
                   "Reasonable Engine: не удалось загрузить редактор.\n")
                + _tr("Cause: ", "Причина: ") + f"{exc}\n\n"
                + _tr("Install the dependencies:\n", "Установите зависимости:\n")
                + "  python -m pip install -r requirements.txt\n"
            )
        else:
            text = (
                "Reasonable Engine: could not load the editor.\n"
                f"Cause: {exc}\n\n"
                "Install the dependencies:\n"
                "  python -m pip install -r requirements.txt\n"
            )
        print(text, file=sys.stderr)
        return 1
    return main()


if __name__ == "__main__":
    raise SystemExit(_run())
