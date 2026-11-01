"""__APP_TITLE__ — пустой проект Reasonable Engine.

Это минимальная, но рабочая точка входа: окно открывается, заставка играет,
а на экране видна подсказка. Дальше можно писать код самому или попросить
ИИ-агента добавить сцены, интерфейс и ассеты.

Запуск:  python main.py
F11 — полноэкранный режим, Esc — выход.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    # PyInstaller build: project files (project.json, data.json) sit next to
    # the executable; bundled data lives inside the PyInstaller bundle.
    PROJECT_DIR = Path(sys.executable).resolve().parent
    BUNDLE_DIR = Path(__file__).resolve().parent
else:
    PROJECT_DIR = Path(__file__).resolve().parent
    BUNDLE_DIR = PROJECT_DIR
for _candidate in (PROJECT_DIR / "_engine", PROJECT_DIR, BUNDLE_DIR):
    if (_candidate / "reasonable").is_dir() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))


def _project_file(relative: str) -> Path:
    """Locate a project file in both source and frozen (exe) modes."""
    candidate = PROJECT_DIR / relative
    if candidate.exists():
        return candidate
    return BUNDLE_DIR / relative

import pygame  # noqa: E402

from reasonable.runtime import Game, render_text  # noqa: E402

APP_NAME = __APP_NAME_REPR__


def window_settings() -> tuple[tuple[int, int], bool, bool]:
    """Read window preferences from project.json with safe defaults."""
    data = {}
    try:
        data = json.loads(_project_file("project.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    window = data.get("window") if isinstance(data, dict) else {}
    window = window if isinstance(window, dict) else {}
    try:
        width = max(320, int(window.get("width") or __WINDOW_WIDTH__))
        height = max(240, int(window.get("height") or __WINDOW_HEIGHT__))
    except (TypeError, ValueError):
        width, height = __WINDOW_WIDTH__, __WINDOW_HEIGHT__
    resizable = bool(window.get("resizable", __WINDOW_RESIZABLE__))
    fullscreen = str(window.get("mode") or "windowed").lower() == "fullscreen"
    if not window.get("mode"):
        fullscreen = __WINDOW_FULLSCREEN__
    return (width, height), resizable, fullscreen


WINDOW_SIZE, WINDOW_RESIZABLE, WINDOW_FULLSCREEN = window_settings()

HINT = "Пустой проект. Измените main.py или попросите ИИ-агента о следующем шаге."


class Project(Game):
    """Minimal running application to build on."""

    def __init__(self) -> None:
        super().__init__(
            APP_NAME,
            WINDOW_SIZE,
            resizable=WINDOW_RESIZABLE,
            fullscreen=WINDOW_FULLSCREEN,
        )

    def on_event(self, event: pygame.event.Event) -> None:
        super().on_event(event)
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.quit()

    def on_draw(self, surface: pygame.Surface) -> None:
        surface.fill(self.background)
        image = render_text(HINT, 20, (154, 161, 171))
        surface.blit(image, image.get_rect(center=(surface.get_width() // 2, surface.get_height() // 2)))


def main() -> None:
    Project().run()


if __name__ == "__main__":
    main()
