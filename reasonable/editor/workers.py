"""Background workers used by the editor.

Qt must stay on the main thread, so every slow operation (AI calls, asset
generation, scaffolding, export) runs in a QThread and reports back through
signals.
"""

from __future__ import annotations

import threading
import traceback
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QThread, Signal

from reasonable.ai.agent import Agent, AgentEvent
from reasonable.core.project import Project


class Worker(QThread):
    """Run a plain function in a thread and emit its result."""

    done = Signal(object)
    failed = Signal(str, str)
    stage = Signal(str)

    def __init__(self, function: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self._function = function
        self._args = args
        self._kwargs = kwargs

    def run(self) -> None:  # noqa: D401
        try:
            result = self._function(*self._args, **self._kwargs)
        except Exception as exc:  # pragma: no cover - GUI path
            self.failed.emit(str(exc), traceback.format_exc())
            return
        self.done.emit(result)


class AgentWorker(QThread):
    event = Signal(object)
    done = Signal(str)
    incomplete = Signal(str)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, project: Project, settings, message: str | None = None) -> None:
        super().__init__()
        self.project = project
        self.settings = settings
        self.message = message
        self.cancel_flag = threading.Event()
        self.agent = Agent(
            project,
            settings,
            on_event=self._on_event,
            cancel=self.cancel_flag,
        )

    def _on_event(self, event: AgentEvent) -> None:
        self.event.emit(event)

    def stop(self) -> None:
        self.cancel_flag.set()

    def run(self) -> None:  # noqa: D401
        try:
            text = self.agent.run(self.message)
        except Exception as exc:  # pragma: no cover - defensive
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        if self.cancel_flag.is_set():
            self.cancelled.emit()
        elif getattr(self.agent, "last_error", ""):
            self.failed.emit(str(self.agent.last_error))
        elif getattr(self.agent, "incomplete_reason", "") and not getattr(self.agent, "finished", False):
            self.incomplete.emit(str(self.agent.incomplete_reason))
        else:
            self.done.emit(text)


class ScaffoldWorker(QThread):
    stage = Signal(str)
    done = Signal(object)
    failed = Signal(str, str)

    def __init__(self, root: Path, manifest: dict[str, Any]) -> None:
        super().__init__()
        self.root = root
        self.manifest = manifest

    def run(self) -> None:  # noqa: D401
        try:
            self.stage.emit("Создаю структуру проекта…")
            project = Project.create(self.root, self.manifest)
            self.stage.emit("Генерирую иконку, фон и стартовые спрайты…")
            self.done.emit(project)
        except Exception as exc:  # pragma: no cover - GUI path
            self.failed.emit(str(exc), traceback.format_exc())


class SpriteWorker(QThread):
    stage = Signal(str)
    done = Signal(object)
    failed = Signal(str, str)

    def __init__(
        self,
        prompt: str,
        target: Path,
        *,
        style: str,
        size: int,
        image_config: dict[str, Any],
        seed: int | None = None,
        background: bool = False,
        width: int = 1280,
        height: int = 720,
    ) -> None:
        super().__init__()
        self.prompt = prompt
        self.target = target
        self.style = style
        self.size = size
        self.image_config = image_config
        self.seed = seed
        self.background = background
        self.width = width
        self.height = height

    def run(self) -> None:  # noqa: D401
        try:
            from reasonable.ai.sprites import generate_background, generate_sprite

            self.stage.emit("Генерирую изображение…")
            if self.background:
                result = generate_background(
                    self.prompt,
                    self.target,
                    width=self.width,
                    height=self.height,
                    image_config=self.image_config,
                    seed=self.seed,
                )
            else:
                result = generate_sprite(
                    self.prompt,
                    self.target,
                    style=self.style,
                    size=self.size,
                    image_config=self.image_config,
                    seed=self.seed,
                )
            self.done.emit(result)
        except Exception as exc:  # pragma: no cover - GUI path
            self.failed.emit(str(exc), traceback.format_exc())


class ExportWorker(QThread):
    stage = Signal(str)
    progress = Signal(str, float, float)  # stage text, stage %, overall %
    done = Signal(object)
    failed = Signal(str, str)

    def __init__(
        self,
        project: Project,
        target: str,
        output: str,
        mode: str = "folder",
        exe_name: str = "",
    ) -> None:
        super().__init__()
        self.project = project
        self.target = target
        self.output = output
        self.mode = mode
        self.exe_name = exe_name

    def run(self) -> None:  # noqa: D401
        try:
            from reasonable.export import export_android, export_windows

            def on_progress(stage_text: str, stage_pct: float, overall_pct: float) -> None:
                self.progress.emit(stage_text, stage_pct, overall_pct)

            if self.target == "android":
                result = export_android(self.project, output=self.output or None, progress=on_progress)
            else:
                result = export_windows(
                    self.project,
                    output=self.output or None,
                    mode=self.mode,
                    exe_name=self.exe_name,
                    progress=on_progress,
                )
            self.done.emit(result)
        except Exception as exc:  # pragma: no cover - GUI path
            self.failed.emit(str(exc), traceback.format_exc())


class ConvertWorker(QThread):
    stage = Signal(str)
    done = Signal(object)
    failed = Signal(str, str)

    def __init__(self, project: Project, target: str, options: dict[str, Any]) -> None:
        super().__init__()
        self.project = project
        self.target = target
        self.options = options

    def run(self) -> None:  # noqa: D401
        try:
            from reasonable.core.convert import convert_project

            self.stage.emit("Копирую проект без кэшей и старых экспортов…")
            self.stage.emit("Применяю настройки и встраиваю движок…")
            result = convert_project(self.project, self.target, **self.options)
            self.stage.emit("Обновляю инструкции агента и прогресс…")
            self.done.emit(result)
        except Exception as exc:  # pragma: no cover - GUI path
            self.failed.emit(str(exc), traceback.format_exc())



class ProviderTestWorker(QThread):
    done = Signal(bool, str)
    failed = Signal(str, str)

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__()
        self.config = config

    def run(self) -> None:  # noqa: D401
        try:
            from reasonable.ai.client import AIClient

            client = AIClient(self.config, timeout=45, retries=1)
            result = client.chat(
                [
                    {
                        "role": "user",
                        "content": "Ответь ровно одним словом: работает",
                    }
                ],
                None,
                temperature=0,
            )
            answer = (result.content or "").strip()
            self.done.emit(True, answer or "Модель ответила пустым сообщением, но соединение работает.")
        except Exception as exc:
            self.failed.emit(str(exc), traceback.format_exc())
