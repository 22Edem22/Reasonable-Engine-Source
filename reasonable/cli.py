"""Command line interface for Reasonable Engine projects.

Inside a generated project, ``re.bat`` / ``re.sh`` call this module. External
agents use it to update the live progress shown by the editor, generate assets,
validate, run and export projects.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from reasonable.version import VERSION_LABEL

from .core.paths import app_data_dir, slugify, unique_directory
from .core.progress import (
    finish_progress,
    read_events,
    read_state,
    record_event,
    set_plan,
    set_progress,
    set_status,
    update_task,
)
from .core.project import Project
from .core.settings import Settings


def _project(args: argparse.Namespace) -> Project:
    root = Path(args.project or os.getcwd()).expanduser().resolve()
    if root.is_file() and root.name == "project.json":
        root = root.parent
    return Project.load(root)


def _print(data) -> None:
    if isinstance(data, str):
        print(data)
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))


def _status_text(state: dict) -> str:
    tasks = state.get("tasks") or []
    done = sum(1 for task in tasks if task.get("status") == "done")
    lines = [
        f"Статус: {state.get('status', '—')}  ·  {state.get('percent', 0):.0f}%",
        f"Этап: {state.get('stage', '—')}",
    ]
    if state.get("message"):
        lines.append(f"Сообщение: {state['message']}")
    if tasks:
        lines.append(f"Задачи: {done}/{len(tasks)}")
        for task in tasks:
            mark = {"done": "✓", "in_progress": "›", "skipped": "–"}.get(task.get("status"), "·")
            lines.append(f"  {mark} {task.get('id', '')}  {task.get('title', '')}")
    lines.append(f"Обновлено: {state.get('updated_at', '—')}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_status(args: argparse.Namespace) -> int:
    project = _project(args)
    state = read_state(project.root)
    if args.json:
        _print({"project": project.manifest, "progress": state})
    else:
        print(f"{project.name}  ·  {'игра' if project.project_type == 'game' else 'приложение'}  ·  {project.mode}")
        print(_status_text(state))
        print(f"Папка: {project.root}")
    return 0


def cmd_events(args: argparse.Namespace) -> int:
    project = _project(args)
    events = read_events(project.root, limit=max(1, args.limit))
    if args.json:
        _print(events)
        return 0
    for event in events:
        stamp = str(event.get("ts", ""))[11:19]
        print(f"{stamp}  {event.get('type', 'event'):10s}  {event.get('message', '')}")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    project = _project(args)
    tasks = [item for item in args.tasks if item.strip()]
    if not tasks:
        print("Нужна хотя бы одна задача.", file=sys.stderr)
        return 2
    state = set_plan(project.root, tasks)
    if args.json:
        _print(state)
    else:
        print(f"План обновлён: {len(tasks)} задач.")
        for task in state.get("tasks", []):
            print(f"  {task['id']}  {task['title']}")
    record_event(project.root, "agent", "План работ обновлён через CLI.")
    return 0


def cmd_task(args: argparse.Namespace) -> int:
    project = _project(args)
    try:
        state = update_task(project.root, args.task, args.status)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.json:
        _print(state)
    else:
        print(f"Задача «{args.task}» → {args.status}.")
    return 0


def cmd_progress(args: argparse.Namespace) -> int:
    project = _project(args)
    state = set_progress(
        project.root,
        args.percent,
        stage=args.stage or None,
        message=args.message or None,
        status="done" if args.percent >= 100 else "running",
    )
    if args.json:
        _print(state)
    else:
        print(f"{state.get('percent', 0):.0f}%  {state.get('stage', '')}  {state.get('message', '')}".strip())
    return 0


def cmd_event(args: argparse.Namespace) -> int:
    project = _project(args)
    event = record_event(project.root, args.type, args.message)
    if args.json:
        _print(event)
    else:
        print(f"Событие записано: {args.message}")
    return 0


def cmd_done(args: argparse.Namespace) -> int:
    project = _project(args)
    state = finish_progress(project.root, args.message or "Проект готов")
    if args.json:
        _print(state)
    else:
        print(f"Готово: {state.get('message')}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    project = _project(args)
    issues = project.validate()
    errors = [issue for issue in issues if issue.level == "error"]
    if args.json:
        _print([{"level": issue.level, "message": issue.message, "path": issue.path} for issue in issues])
    else:
        for issue in issues:
            icon = {"error": "✗", "warning": "!", "ok": "✓"}.get(issue.level, "·")
            suffix = f"  [{issue.path}]" if issue.path else ""
            print(f"{icon} {issue.message}{suffix}")
    if errors:
        record_event(project.root, "validate", f"Найдено ошибок: {len(errors)}")
        return 1
    record_event(project.root, "validate", "Проверка пройдена")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    project = _project(args)
    if not project.entry.exists():
        print("Точка входа не найдена.", file=sys.stderr)
        return 2
    env = project.run_env()
    if args.headless:
        # Headless runs have no visible window; the splash finishes instantly.
        env.update({"SDL_VIDEODRIVER": "dummy", "SDL_AUDIODRIVER": "dummy"})
        env["RE_FRAMES"] = str(max(1, args.frames))
    try:
        process = subprocess.run(
            project.run_command(),
            cwd=str(project.root),
            env=env,
            timeout=args.timeout or None,
        )
    except subprocess.TimeoutExpired:
        print(f"Проект не завершился за {args.timeout} сек.", file=sys.stderr)
        return 3
    return process.returncode


def cmd_sprite(args: argparse.Namespace) -> int:
    project = _project(args)
    target = project.ensure_inside(args.output)
    assets = project.root / "assets"
    try:
        target.relative_to(assets)
    except ValueError:
        print("Сохраняйте спрайты в assets/.", file=sys.stderr)
        return 2
    from reasonable.ai.sprites import generate_sprite

    settings = Settings()
    config = settings.image_config()
    if args.provider:
        config["provider"] = args.provider
    try:
        result = generate_sprite(
            args.prompt,
            target,
            style=args.style,
            size=args.size,
            image_config=config,
            seed=args.seed,
        )
    except Exception as exc:
        print(f"Ошибка генерации: {exc}", file=sys.stderr)
        return 1
    record_event(project.root, "asset", f"Спрайт: {project.rel(target)} ({result.get('provider')})")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_bg(args: argparse.Namespace) -> int:
    project = _project(args)
    target = project.ensure_inside(args.output)
    assets = project.root / "assets"
    try:
        target.relative_to(assets)
    except ValueError:
        print("Сохраняйте фоны в assets/.", file=sys.stderr)
        return 2
    from reasonable.ai.sprites import generate_background

    config = Settings().image_config()
    if args.provider:
        config["provider"] = args.provider
    try:
        result = generate_background(
            args.prompt,
            target,
            width=args.width,
            height=args.height,
            image_config=config,
            seed=args.seed,
        )
    except Exception as exc:
        print(f"Ошибка генерации: {exc}", file=sys.stderr)
        return 1
    record_event(project.root, "asset", f"Фон: {project.rel(target)}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    project = _project(args)
    from reasonable.export import export_android, export_windows

    try:
        if args.target == "android":
            result = export_android(project, output=args.output)
        else:
            result = export_windows(project, output=args.output, mode=args.mode)
    except Exception as exc:
        print(f"Ошибка экспорта: {exc}", file=sys.stderr)
        return 1
    record_event(project.root, "export", f"Экспорт {args.target}: {result.get('path')}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    project = _project(args)
    path = project.sync_engine()
    print(f"Движок обновлён: {path}")
    record_event(project.root, "engine", "Обновлена встроенная копия движка.")
    return 0


def cmd_convert(args: argparse.Namespace) -> int:
    project = _project(args)
    from .core.convert import convert_project

    try:
        result = convert_project(
            project,
            args.to,
            name=args.name or None,
            output=args.dir or None,
            orientation=args.orientation,
            mode=args.mode,
            window_mode=args.window_mode,
            resizable=args.resizable,
            width=args.width,
            height=args.height,
            reset_progress=bool(args.reset_progress),
        )
    except Exception as exc:
        if args.json:
            _print({"ok": False, "error": str(exc)})
        else:
            print(f"Ошибка конвертации: {exc}", file=sys.stderr)
        return 1
    if args.json:
        _print(result)
    else:
        print(result["message"])
        for change in result.get("changes") or []:
            print(f"  · {change}")
        print(f"Открыть: {result['path']}")
    return 0


def cmd_pack(args: argparse.Namespace) -> int:
    project = _project(args)
    from reasonable.ai.external import generate_agent_pack

    paths = generate_agent_pack(project)
    print(f"Пакет агента обновлён: {len(paths)} файлов.")
    for path in paths:
        print(f"  {project.rel(path)}")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    from .core.project import default_manifest

    name = args.name.strip() or "Новый проект"
    parent = Path(args.dir or os.getcwd()).expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    root = unique_directory(parent, slugify(name, "project"))
    manifest = default_manifest(
        name,
        project_type=args.type,
        mode=args.mode,
        goal=args.goal or "",
        notes=args.notes or args.legacy_prompts or "",
        width=args.width,
        height=args.height,
        window_mode=args.window_mode,
        resizable=not args.fixed_size,
        orientation=args.orientation,
    )
    project = Project.create(root, manifest)
    print(f"Проект создан: {project.root}")
    print(f"Запуск: {project.root / 'run.bat'}  (или python main.py)")
    if project.mode == "external":
        print("Инструкция для внешнего агента: AGENT_GUIDE.md")
    return 0


def cmd_settings(args: argparse.Namespace) -> int:
    settings = Settings()
    if args.show:
        config = settings.get_provider_config()
        if config.get("api_key"):
            config["api_key"] = config["api_key"][:6] + "…"
        _print(config)
        return 0
    if args.provider:
        settings.active_provider = args.provider
        settings.save()
        print(f"Активный провайдер: {args.provider}")
        return 0
    print(f"Настройки: {settings.path}")
    print(f"Провайдер: {settings.active_provider}")
    return 0


def cmd_version(args: argparse.Namespace) -> int:
    print(f"Reasonable Engine {VERSION_LABEL}")
    print(f"Python {sys.version.split()[0]} · {sys.platform}")
    return 0


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="re",
        description="Reasonable Engine CLI — прогресс, ассеты, проверка и экспорт.",
    )
    parser.add_argument("--project", default=os.getcwd(), help="Папка проекта (по умолчанию текущая)")
    parser.add_argument("--version", action="store_true", help="Показать версию")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("status", help="Показать проект и прогресс")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("events", help="Последние события прогресса")
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_events)

    p = sub.add_parser("plan", help="Обновить план работ")
    p.add_argument("tasks", nargs="+", help="Названия задач")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("task", help="Обновить статус задачи")
    p.add_argument("task", help="id (t1), номер или название")
    p.add_argument("status", choices=("pending", "in_progress", "done", "skipped"))
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_task)

    p = sub.add_parser("progress", help="Обновить процент и этап")
    p.add_argument("percent", type=float)
    p.add_argument("message", nargs="?", default="")
    p.add_argument("--stage", default="")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_progress)

    p = sub.add_parser("event", help="Записать событие в ленту")
    p.add_argument("message")
    p.add_argument("--type", default="event")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_event)

    p = sub.add_parser("done", help="Завершить проект (100%%)")
    p.add_argument("message", nargs="?", default="")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_done)

    p = sub.add_parser("validate", help="Проверить структуру и синтаксис")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("run", help="Запустить проект")
    p.add_argument("--headless", action="store_true", help="Без окна, несколько кадров")
    p.add_argument("--frames", type=int, default=8)
    p.add_argument("--timeout", type=int, default=0)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("sprite", help="Сгенерировать спрайт")
    p.add_argument("prompt")
    p.add_argument("output", help="Например assets/sprites/player.png")
    p.add_argument("--style", default="flat", choices=("flat", "pixel", "painterly", "icon"))
    p.add_argument("--size", type=int, default=256)
    p.add_argument("--provider", default="", help="procedural | openai")
    p.add_argument("--seed", type=int, default=None)
    p.set_defaults(func=cmd_sprite)

    p = sub.add_parser("bg", help="Сгенерировать фон")
    p.add_argument("prompt")
    p.add_argument("output")
    p.add_argument("--width", type=int, default=1280)
    p.add_argument("--height", type=int, default=720)
    p.add_argument("--provider", default="")
    p.add_argument("--seed", type=int, default=None)
    p.set_defaults(func=cmd_bg)

    p = sub.add_parser("export", help="Экспортировать проект")
    p.add_argument("target", choices=("windows", "android"))
    p.add_argument("--output", default="")
    p.add_argument("--mode", default="folder", choices=("folder", "pyinstaller"))
    p.set_defaults(func=cmd_export)

    p = sub.add_parser(
        "convert",
        help="Создать новый проект с другой платформой или настройками",
    )
    p.add_argument("--to", required=True, choices=("windows", "android"), help="Новая платформа")
    p.add_argument("--name", default="", help="Новое название проекта")
    p.add_argument("--dir", default="", help="Папка, в которой создать новый проект")
    p.add_argument("--orientation", default="current", choices=("current", "landscape", "portrait"))
    p.add_argument("--mode", default="current", choices=("current", "builtin", "external"))
    p.add_argument("--window-mode", default="current", choices=("current", "windowed", "fullscreen"))
    p.add_argument("--resizable", default="current", choices=("current", "yes", "no"))
    p.add_argument("--width", type=int, default=None)
    p.add_argument("--height", type=int, default=None)
    p.add_argument("--reset-progress", action="store_true", help="Очистить план, прогресс и события")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_convert)

    p = sub.add_parser("sync-engine", help="Обновить _engine/ в проекте")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("pack", help="Обновить пакет инструкций для агента")
    p.set_defaults(func=cmd_pack)

    p = sub.add_parser("init", help="Создать проект из CLI")
    p.add_argument("--name", required=True)
    p.add_argument("--type", default="game", choices=("game", "app"))
    p.add_argument("--mode", default="builtin", choices=("builtin", "external"))
    p.add_argument("--goal", default="")
    p.add_argument("--notes", default="", help="Необязательные заметки и требования")
    p.add_argument("--prompts", dest="legacy_prompts", default="", help=argparse.SUPPRESS)
    p.add_argument("--dir", default="")
    p.add_argument("--width", type=int, default=1280)
    p.add_argument("--height", type=int, default=720)
    p.add_argument("--window-mode", default="windowed", choices=("windowed", "fullscreen"))
    p.add_argument("--fixed-size", action="store_true", help="Запретить изменение размера окна")
    p.add_argument("--orientation", default="landscape", choices=("landscape", "portrait"))
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("settings", help="Показать настройки ИИ")
    p.add_argument("--show", action="store_true")
    p.add_argument("--provider", default="")
    p.set_defaults(func=cmd_settings)

    p = sub.add_parser("version", help="Версия движка")
    p.set_defaults(func=cmd_version)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "version", False):
        return cmd_version(args)
    if not getattr(args, "command", None):
        parser.print_help()
        print(f"\nReasonable Engine {VERSION_LABEL} · настройки: {app_data_dir()}")
        return 0
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
