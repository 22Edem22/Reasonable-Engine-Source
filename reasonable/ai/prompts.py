"""Prompts, skills and documentation shared by both agent modes.

The built-in agent and external agents receive the same knowledge about the
engine, the same quality bar and the same progress protocol. Keeping this in one
module prevents the two modes from drifting apart.

All agent-facing material (tool schemas, skills, guides) ships in English
regardless of the UI language — see :mod:`reasonable.ai.prompts_en` and
``reasonable/core/i18n.py``. The agent still replies to the user in the
language of the user's task (:data:`AGENT_LANGUAGE_RULE`).
"""

from __future__ import annotations

from .prompts_en import (  # noqa: F401  (re-exported for existing imports)
    AGENT_LANGUAGE_RULE,
    AGENT_SYSTEM_PROMPT,
    AGENT_SYSTEM_PROMPT_BODY,
    AGENT_TASKS_TEMPLATE,
    ENGINE_API_GUIDE,
    EXTERNAL_CONNECTION_GUIDE,
    EXTERNAL_GUIDE_TEMPLATE,
    EXTERNAL_README_TEMPLATE,
    SHORT_AGENT_TEMPLATE,
    SKILLS,
    UI_LEVEL_LABELS_EN,
    build_agent_system_prompt,
    build_agent_system_prompt_body,
    build_improvement_prompt,
    build_initial_user_message,
)


def skills_for_project(project) -> dict[str, str]:
    """Only the skills this project actually needs — no extra files.

    Base knowledge + a type-specific skill + one skill per selected interface
    level. A pure-tkinter project never receives the advanced-scenes skill and
    a game never receives the tkinter skill unless the user picked that level.
    """
    result: dict[str, str] = {}
    for name in ("engine-basics.md", "sprites-and-assets.md", "progress-and-handoff.md", "android-and-export.md"):
        if name in SKILLS:
            result[name] = SKILLS[name]
    type_skill = "game-development.md" if project.project_type == "game" else "app-development.md"
    if type_skill in SKILLS:
        result[type_skill] = SKILLS[type_skill]
    for level in project.ui_levels:
        skill = {"simple": "ui-simple-tkinter.md", "standard": "ui-standard-widgets.md", "advanced": "ui-advanced-scenes.md"}.get(level)
        if skill and skill in SKILLS:
            result[skill] = SKILLS[skill]
    return result


def _conversion_note(project) -> str:
    converted = project.manifest.get("converted_from")
    if not isinstance(converted, dict) or not converted.get("name"):
        return ""
    source_platform = "Android" if converted.get("platform") == "android" else "Windows"
    return (
        f"- Converted from \"{converted.get('name')}\" "
        f"({source_platform}) {converted.get('at', '')}".rstrip()
    )


def build_external_guide(project) -> str:
    kind = "game" if project.project_type == "game" else "application"
    mode = "built-in" if project.mode == "builtin" else "external"
    platform = "Android" if getattr(project, "platform", "windows") == "android" else "Windows"
    skills = "\n".join(f"- [`skills/{name}`](skills/{name})" for name in skills_for_project(project))
    levels = ", ".join(UI_LEVEL_LABELS_EN.get(level, level) for level in project.ui_levels)
    from reasonable.version import VERSION_LABEL

    return EXTERNAL_GUIDE_TEMPLATE.format(
        name=project.name,
        version=VERSION_LABEL,
        mode=mode,
        kind=kind,
        platform=platform,
        levels=levels,
        conversion_note=_conversion_note(project),
        goal=project.goal or "not specified",
        entry=project.manifest.get("entry", "main.py"),
        root=project.root,
        notes=project.notes or "none",
        skills=skills,
        api_guide=ENGINE_API_GUIDE,
    )


def build_agent_tasks(project) -> str:
    from reasonable.core.progress import read_state

    state = read_state(project.root)
    rows = []
    for task in state.get("tasks", []):
        mark = {"done": "[x]", "in_progress": "[>]", "skipped": "[-]"}.get(task.get("status"), "[ ]")
        rows.append(f"- {mark} **{task.get('title')}** — `{task.get('id')}` ({task.get('status')})")
    return AGENT_TASKS_TEMPLATE.format(
        name=project.name,
        plan_rows=chr(10).join(rows) or "- The plan is empty.",
        created_at=project.manifest.get("created_at", ""),
    )
