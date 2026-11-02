"""Generate the external-agent pack for a project.

The goal is that any capable coding agent — Claude Code, Codex CLI, Cursor,
Cline, Windsurf, Aider — can open the folder and immediately know:

* what the project is;
* which engine API to use;
* how to generate assets;
* how to publish live progress into the Reasonable Engine editor;
* how to validate and hand off the work.
"""

from __future__ import annotations

from pathlib import Path

from reasonable.core.paths import atomic_write_text

from .prompts import (
    EXTERNAL_CONNECTION_GUIDE,
    SHORT_AGENT_TEMPLATE,
    build_agent_tasks,
    build_external_guide,
    skills_for_project,
)

PACK_VERSION = 1


def generate_agent_pack(project) -> list[Path]:
    """Write/refresh all external-agent documents. Returns created paths."""
    root = Path(project.root)
    written: list[Path] = []

    def write(relative: str, text: str) -> None:
        path = root / relative
        atomic_write_text(path, text.rstrip() + "\n")
        written.append(path)

    write("AGENT_GUIDE.md", build_external_guide(project))
    write("EXTERNAL_AGENT.md", EXTERNAL_CONNECTION_GUIDE)
    short = SHORT_AGENT_TEMPLATE.format(name=project.name)
    write("AGENTS.md", short)
    write("CLAUDE.md", "# Claude Code\n\n" + short)
    write(".github/copilot-instructions.md", short)
    write(
        ".cursor/rules/reasonable-engine.mdc",
        """---
description: Reasonable Engine project rules
alwaysApply: true
---

""" + short,
    )
    wanted = skills_for_project(project)
    for filename, content in wanted.items():
        write(f"skills/{filename}", content)
    # Remove skills left from another interface-level selection so the project
    # never accumulates tools it does not use.
    skills_dir = root / "skills"
    if skills_dir.is_dir():
        for path in skills_dir.glob("*.md"):
            if path.name not in wanted:
                try:
                    path.unlink()
                except OSError:
                    pass
    if not (root / "AGENT_TASKS.md").exists():
        write("AGENT_TASKS.md", build_agent_tasks(project))
    else:
        written.append(root / "AGENT_TASKS.md")
    write(
        ".reasonable/agent_pack.json",
        '{\n  "pack_version": %d,\n  "engine_version": "%s",\n  "mode": "%s"\n}\n'
        % (PACK_VERSION, project.manifest.get("engine_version", ""), project.mode),
    )
    return written


def connection_checklist(project) -> list[tuple[str, bool, str]]:
    """Human-readable checklist rendered by the editor."""
    root = Path(project.root)
    checks = [
        ("AGENT_GUIDE.md создан", (root / "AGENT_GUIDE.md").exists(), "Полная инструкция для агента"),
        ("Навыки skills/ на месте", any((root / "skills").glob("*.md")) if (root / "skills").is_dir() else False, "Игровой и UI-опыт"),
        ("CLI re.bat / re.sh", (root / "re.bat").exists() or (root / "re.sh").exists(), "Обновление прогресса и экспорт"),
        ("progress/state.json", (root / "progress" / "state.json").exists(), "Живой прогресс в редакторе"),
        ("Указатели для агентов", (root / "AGENTS.md").exists() or (root / "CLAUDE.md").exists(), "Claude Code, Codex, Cursor, Cline"),
        ("Встроенный движок", (root / "_engine" / "reasonable" / "runtime").exists(), "Проект самодостаточен"),
    ]
    return checks


def external_readme(project) -> str:
    return f"""# Внешний агент · {project.name}

1. Откройте папку проекта в Claude Code / Codex / Cursor / Cline / Windsurf.
2. Напишите первую задачу в разделе «ИИ-агент» и скопируйте готовый промпт:

   > Прочитай AGENT_GUIDE.md и skills/. Изучи project.json и progress/state.json.
   > Выполни первую задачу, обновляя прогресс через re.bat. Доведи проект
   > до запускаемого состояния и выполни re.bat validate.

3. Следите за разделом «ИИ-агент» в Reasonable Engine — он обновляется
   автоматически. Кнопки «Проверить», «Запустить» и «Экспорт» работают всегда.

CLI: `re.bat status`, `re.bat plan ...`, `re.bat progress 30 "..."`,
`re.bat validate`, `re.bat sprite ...`, `re.bat export ...`.

Полная инструкция: `AGENT_GUIDE.md` и `EXTERNAL_AGENT.md`.
"""
