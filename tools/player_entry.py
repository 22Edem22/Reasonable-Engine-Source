"""Entry point for ``ReasonablePlayer.exe``.

The player is a small bundled Python + pygame runtime. It runs a generated
project's entry file directly, so double-clicking a project never starts
another copy of the Reasonable Engine editor.

Usage:
    ReasonablePlayer.exe <path-to-main.py>
    ReasonablePlayer.exe --self-test
"""

from __future__ import annotations

import json
import os
import runpy
import sys
import traceback
from pathlib import Path

REPORT_ENV = "REASONABLE_PLAYER_SELF_TEST_REPORT"
LOG_NAME = "ReasonablePlayer.log"


def _log_path() -> Path:
    base = Path(os.environ.get("TEMP") or Path.home() / "AppData" / "Local" / "Temp")
    return base / LOG_NAME


def _tkinter_missing_hint(exc: BaseException, entry: Path) -> str | None:
    """Explain a ModuleNotFoundError raised inside the bundled player.

    ``ReasonablePlayer.exe`` embeds Python + pygame but intentionally has no
    tkinter (it is excluded in ReasonablePlayer.spec). Projects created on the
    «Простой (tkinter)» level therefore cannot run inside the player; without
    this hint the user only sees a raw ``ModuleNotFoundError`` traceback.
    """
    name = getattr(exc, "name", "") or ""
    if not isinstance(exc, ModuleNotFoundError):
        return None
    if name != "tkinter" and not name.startswith("tkinter."):
        return None
    return (
        f"Проект «{entry.parent.name}» использует tkinter — окно на уровне\n"
        "«Простой», а ReasonablePlayer.exe содержит только Python и pygame,\n"
        "без tkinter.\n\n"
        "Как запустить:\n"
        "1) Через редактор: откройте проект в Reasonable Engine и нажмите\n"
        "   «Запустить» — для tkinter-проектов движок сам выберет Python с\n"
        "   tkinter (из папки python\\ или системный).\n"
        "2) Вручную: python\\python.exe main.py (или python main.py, если\n"
        "   Python установлен).\n"
        "3) Установите Python с https://www.python.org/downloads/\n"
        "   (галочка «Add python.exe to PATH») и повторите запуск.\n\n"
        f"Файл проекта: {entry}"
    )


def _report_error(detail: str) -> None:
    """Write the traceback to a log and, when possible, show a dialog."""
    try:
        path = _log_path()
        path.write_text(detail, encoding="utf-8", errors="replace")
    except OSError:
        path = None
    if os.name == "nt":
        try:
            import ctypes

            message = detail[-1500:]
            if path is not None:
                message += f"\n\nПодробности: {path}"
            ctypes.windll.user32.MessageBoxW(
                0,
                message,
                "Reasonable Player — ошибка запуска",
                0x10,
            )
        except Exception:
            pass


def _self_test() -> int:
    report_path = Path(
        os.environ.get(REPORT_ENV)
        or (Path(os.environ.get("TEMP") or ".") / "reasonable-player-self-test.json")
    )
    checks: list[dict] = []
    error = ""
    try:
        import pygame

        checks.append({"name": "pygame import", "ok": True, "detail": pygame.version.ver})
        checks.append(
            {
                "name": "frozen",
                "ok": bool(getattr(sys, "frozen", False)),
                "detail": str(getattr(sys, "frozen", False)),
            }
        )
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
        surface = pygame.display.set_mode((64, 64))
        surface.fill((10, 20, 30))
        checks.append({"name": "display", "ok": surface.get_size() == (64, 64)})
        pygame.quit()
    except Exception:
        error = traceback.format_exc()
    ok = bool(checks) and all(item["ok"] for item in checks) and not error
    report = {
        "ok": ok,
        "executable": sys.executable,
        "python": sys.version,
        "checks": checks,
        "error": error,
    }
    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        ok = False
    return 0 if ok else 1


def _run_project(entry: Path) -> int:
    if not entry.is_file():
        _report_error(f"Не найден файл проекта:\n{entry}")
        return 3
    project_dir = entry.parent
    for candidate in (project_dir / "_engine", project_dir):
        if candidate.is_dir() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
    os.chdir(project_dir)
    sys.argv = [str(entry), *sys.argv[2:]]
    try:
        runpy.run_path(str(entry), run_name="__main__")
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else (0 if code is None else 1)
    except ModuleNotFoundError as exc:
        hint = _tkinter_missing_hint(exc, entry)
        if hint is not None:
            _report_error(hint)
            return 4
        _report_error(traceback.format_exc())
        return 1
    except Exception:
        _report_error(traceback.format_exc())
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--self-test" in args:
        return _self_test()
    if not args:
        _report_error(
            "ReasonablePlayer запускает проект, а не редактор.\n\n"
            "Откройте проект в Reasonable Engine и нажмите «Запустить», "
            "либо передайте путь к main.py:\n"
            "  ReasonablePlayer.exe C:\\path\\to\\project\\main.py"
        )
        return 2
    return _run_project(Path(args[0]).expanduser().resolve())


if __name__ == "__main__":
    raise SystemExit(main())
