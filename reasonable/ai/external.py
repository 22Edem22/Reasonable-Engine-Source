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
    """Human-readable checklist rendered by the editor (labels via i18n)."""
    from reasonable.core import i18n

    root = Path(project.root)
    checks = [
        (i18n.t("external.check_guide"), (root / "AGENT_GUIDE.md").exists(),
         i18n.t("external.check_guide_hint")),
        (i18n.t("external.check_skills"), any((root / "skills").glob("*.md")) if (root / "skills").is_dir() else False,
         i18n.t("external.check_skills_hint")),
        (i18n.t("external.check_cli"), (root / "re.bat").exists() or (root / "re.sh").exists(),
         i18n.t("external.check_cli_hint")),
        (i18n.t("external.check_state"), (root / "progress" / "state.json").exists(),
         i18n.t("external.check_state_hint")),
        (i18n.t("external.check_pointers"), (root / "AGENTS.md").exists() or (root / "CLAUDE.md").exists(),
         i18n.t("external.check_pointers_hint")),
        (i18n.t("external.check_engine"), (root / "_engine" / "reasonable" / "runtime").exists(),
         i18n.t("external.check_engine_hint")),
    ]
    return checks


def external_readme(project) -> str:
    """README for projects handed to an external agent (English-only pack)."""
    from reasonable.core import i18n

    header = i18n.t("external.readme_header", name=project.name)
    body = (
        f"# External AI Agent \u00b7 {project.name}\n\n"
        "1. Open this project folder in Claude Code / Codex / Cursor / Cline / Windsurf.\n"
        "2. Write your first task in the \u00abAI agent\u00bb section of Reasonable Engine and copy the ready prompt:\n\n"
        "   > Read AGENT_GUIDE.md and skills/. Study project.json and progress/state.json.\n"
        "   > Complete the first task, publishing progress through re.bat. Bring the project\n"
        "   > to a runnable state and run re.bat validate.\n\n"
        "3. Watch the \u00abAI agent\u00bb section in Reasonable Engine \u2014 it updates automatically.\n"
        "   The \u201cCheck\u201d, \u201cRun\u201d and \u201cExport\u201d buttons always work.\n\n"
        "CLI: `re.bat status`, `re.bat plan ...`, `re.bat progress 30 \"...\"`,\n"
        "`re.bat validate`, `re.bat sprite ...`, `re.bat export ...`.\n\n"
        "Full instructions: `AGENT_GUIDE.md` and `EXTERNAL_AGENT.md`.\n"
    )
    return header + "\n\n" + body
