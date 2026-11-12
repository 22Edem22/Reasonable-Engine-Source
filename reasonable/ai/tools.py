"""Tools available to the built-in AI agent.

Every tool is sandboxed to the project folder. Results are compact JSON strings so
models with small context windows stay usable. The tool layer is also used by the
CLI (for example ``re validate``) and by tests.
"""

from __future__ import annotations

import fnmatch
import ast
import html
import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from reasonable.core.paths import atomic_write_text, is_relative_to, python_command
from reasonable.core.site import SITE_DIR, site_root, validate_site
from reasonable.core.progress import (
    finish_progress,
    read_events,
    read_state,
    record_event,
    set_plan,
    set_progress,
    update_task,
)
from reasonable.core.project import IGNORED_DIRS, Project, SCRATCH_PATTERN, TEXT_SUFFIXES
from reasonable.core.i18n import tr


def _t(en: str, ru: str, **values) -> str:
    """User-facing tool message in the UI language.

    Tool schemas themselves stay English-only (they are AI-facing material);
    only messages returned to the user through the chat panel are localized.
    """
    return tr(en, ru, **values)

def _is_scratch_path(relative: str) -> bool:
    """Root-level verification scratch files such as _check.py or _probe.py."""
    value = str(relative or "").strip().strip("/")
    return bool(value) and "/" not in value and bool(SCRATCH_PATTERN.match(value))


def _has_launch_code(source: str) -> bool:
    """True when a module has code that runs after its definitions.

    A file with only imports, constants, functions and classes is a library,
    not an application entry point: the splash plays and the window closes.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return True
    runtime_nodes = (ast.Expr, ast.If, ast.While, ast.For, ast.Try, ast.With)
    return any(isinstance(node, runtime_nodes) for node in tree.body)


MAX_WRITE_BYTES = 600_000
MAX_READ_BYTES = 400_000
# A single read_file call never returns more than this many lines, even when
# the model asks for a huge range of a generated file.
MAX_READ_LINES = 4_000
# Files larger than this are still range-readable, but counting all their
# lines would mean reading the whole file; report an unknown total instead.
MAX_COUNT_BYTES = 8_000_000
PROTECTED = {"project.json", "main.py", "progress/state.json", "progress/events.jsonl"}
# The manifest is the one file the agent must never rewrite: a valid-JSON but
# structurally broken project.json makes the project unopenable. The system
# prompt already tells the model not to touch it (see prompts_en.py).
PROTECTED_WRITE = {"project.json"}


def _kill_process_tree(process: subprocess.Popen) -> None:
    """Terminate a command and every child it spawned.

    ``Popen.kill`` only stops the shell on Windows, so a long-running
    ``pip install`` or a test runner survived a tool timeout and kept holding
    files. ``taskkill /T`` (Windows) and a process-group signal (POSIX) stop
    the whole tree.
    """
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=5,
            )
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
        return
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def _site_theme_css(palette: str, mode: str, radius: int) -> str:
    """A dependency-free responsive design system for website projects."""
    palettes = {
        "warm": ("#d97757", "#b85a3c", "#f4dfd6", "#2a211d"),
        "cool": ("#4f7cff", "#355fd4", "#dde6ff", "#1a2236"),
        "mono": ("#6b7280", "#4b5563", "#e5e7eb", "#1f2328"),
        "forest": ("#3f8f6b", "#2d6f51", "#dcefe5", "#17261f"),
    }
    accent, strong, soft, dark_soft = palettes.get(palette, palettes["warm"])
    light = (
        "--bg:#f7f5f1; --surface:#ffffff; --surface-soft:#efece6; "
        "--text:#191b1f; --muted:#5f6570; --line:#d9d4cb; "
        f"--accent:{accent}; --accent-strong:{strong}; --accent-soft:{soft}; "
        "--shadow:0 18px 40px rgba(24,22,19,.10);"
    )
    dark = (
        "--bg:#121417; --surface:#1a1d21; --surface-soft:#20242a; "
        "--text:#eef0f3; --muted:#a5adb8; --line:#30353d; "
        f"--accent:{accent}; --accent-strong:{strong}; --accent-soft:{dark_soft}; "
        "--shadow:0 18px 40px rgba(0,0,0,.35);"
    )
    if mode == "dark":
        scheme = "dark"
        light = dark
        dark_block = ""
    elif mode == "auto":
        scheme = "light dark"
        dark_block = "@media (prefers-color-scheme: dark) { :root { %s } }" % dark
    else:
        scheme = "light"
        dark_block = ""
    template = """/* Generated by site_theme — edit variables, not the rules below. */
:root { color-scheme: __SCHEME__; __LIGHT__ --radius: __RADIUS__px;
  --font: "Segoe UI", "Inter", system-ui, -apple-system, sans-serif;
  --mono: "Cascadia Code", "JetBrains Mono", Consolas, monospace; }
__DARK__
*, *::before, *::after { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body { margin: 0; background: var(--bg); color: var(--text); font: 17px/1.65 var(--font);
  -webkit-font-smoothing: antialiased; }
img, svg { display: block; max-width: 100%; }
a { color: var(--accent-strong); text-underline-offset: 3px; }
a:hover { color: var(--accent); }
:focus-visible { outline: 3px solid var(--accent); outline-offset: 3px; }
h1, h2, h3 { margin: 0 0 .6em; line-height: 1.15; letter-spacing: -.02em; }
h1 { font-size: clamp(2.4rem, 5.4vw, 4.2rem); font-weight: 750; }
h2 { font-size: clamp(1.7rem, 3vw, 2.4rem); font-weight: 700; }
h3 { font-size: 1.15rem; font-weight: 700; }
p { margin: 0 0 1em; }
code, pre { font-family: var(--mono); font-size: .9em; }
pre { overflow-x: auto; padding: 12px 14px; border: 1px solid var(--line);
  border-radius: 10px; background: var(--surface-soft); }
.container { width: min(100% - 40px, 1120px); margin-inline: auto; }
.skip-link { position: absolute; left: 12px; top: -60px; z-index: 20; padding: 8px 14px;
  border: 1px solid var(--line); border-radius: 8px; background: var(--surface); }
.skip-link:focus { top: 12px; }
.site-header { position: sticky; top: 0; z-index: 10; border-bottom: 1px solid var(--line);
  background: color-mix(in srgb, var(--bg) 88%, transparent); backdrop-filter: blur(12px); }
.header-inner { display: flex; align-items: center; justify-content: space-between;
  min-height: 68px; gap: 18px; }
.brand { color: var(--text); font-size: 1.05rem; font-weight: 750; text-decoration: none; }
.site-nav { display: flex; align-items: center; gap: 20px; }
.site-nav a { color: var(--muted); font-size: .95rem; text-decoration: none; }
.site-nav a:hover { color: var(--text); }
.nav-toggle { display: none; }
.button { display: inline-flex; align-items: center; justify-content: center; gap: 8px;
  min-height: 46px; padding: 0 20px; border: 1px solid transparent; border-radius: 999px;
  background: var(--accent); color: #fff; font-weight: 650; text-decoration: none; }
.button:hover { background: var(--accent-strong); color: #fff; }
.button-ghost { background: transparent; color: var(--text); border-color: var(--line); }
.button-ghost:hover { background: var(--surface); color: var(--text); }
.button-small { min-height: 38px; padding: 0 15px; font-size: .9rem; }
.hero { max-width: 880px; padding: clamp(64px, 10vw, 132px) 0 clamp(48px, 7vw, 96px); }
.eyebrow { color: var(--accent-strong); font-size: .74rem; font-weight: 700;
  letter-spacing: .14em; text-transform: uppercase; }
.lead { max-width: 62ch; color: var(--muted); font-size: clamp(1.05rem, 1.7vw, 1.3rem); }
.hero-actions { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 28px; }
.section { padding: clamp(44px, 7vw, 88px) 0; }
.section-head { max-width: 62ch; margin-bottom: 28px; }
.section-head p { color: var(--muted); }
.grid { display: grid; gap: 18px; }
.grid-2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.grid-3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.card { padding: 24px; border: 1px solid var(--line); border-radius: var(--radius);
  background: var(--surface); box-shadow: var(--shadow); }
.card p:last-child { margin-bottom: 0; color: var(--muted); }
.split { display: grid; grid-template-columns: 1.2fr .8fr; gap: 28px; align-items: start; }
.callout { padding: 22px; border: 1px solid var(--line); border-radius: var(--radius);
  background: var(--surface); }
.cta { display: flex; align-items: center; justify-content: space-between; gap: 22px;
  padding: clamp(24px, 4vw, 40px); border: 1px solid var(--line);
  border-radius: calc(var(--radius) + 6px); background: var(--accent-soft); }
.site-footer { margin-top: 40px; padding: 26px 0; border-top: 1px solid var(--line); }
.footer-inner { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 16px;
  color: var(--muted); font-size: .9rem; }
input, textarea, select { width: 100%; padding: 11px 13px; color: var(--text);
  background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
  font: inherit; }
label { display: block; margin-bottom: 6px; font-weight: 600; }
.muted { color: var(--muted); }
.stack > * + * { margin-top: 14px; }
@media (max-width: 820px) {
  .grid-3, .grid-2, .split { grid-template-columns: 1fr; }
  .nav-toggle { display: inline-flex; align-items: center; min-height: 38px; padding: 0 14px;
    border: 1px solid var(--line); border-radius: 999px; background: var(--surface);
    color: var(--text); font: inherit; cursor: pointer; }
  .site-nav { position: absolute; inset: 68px 12px auto; display: none; flex-direction: column;
    align-items: stretch; gap: 4px; padding: 14px; border: 1px solid var(--line);
    border-radius: 14px; background: var(--surface); box-shadow: var(--shadow); }
  .site-nav.is-open { display: flex; }
  .cta { flex-direction: column; align-items: flex-start; }
}
@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  *, *::before, *::after { transition-duration: .01ms !important; animation-duration: .01ms !important; }
}
"""
    return (
        template.replace("__SCHEME__", scheme)
        .replace("__LIGHT__", light)
        .replace("__RADIUS__", str(max(0, min(32, int(radius)))))
        .replace("__DARK__", dark_block)
    )


class ToolError(RuntimeError):
    pass


def _schema(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required or [],
            "additionalProperties": False,
        },
    }


TOOL_SCHEMAS: list[dict[str, Any]] = [
    _schema(
        "list_files",
        "List the project's files and folders. Use at the start of a job.",
        {
            "path": {"type": "string", "description": "Folder relative to the project root", "default": "."},
            "depth": {"type": "integer", "description": "Traversal depth", "default": 3, "minimum": 1, "maximum": 8},
        },
    ),
    _schema(
        "read_file",
        "Read a project text file. For large files use start_line/end_line.",
        {
            "path": {"type": "string", "description": "Path relative to the project root"},
            "start_line": {"type": "integer", "default": 1, "minimum": 1},
            "end_line": {"type": "integer", "description": "Last line, inclusive", "default": 800},
        },
        ["path"],
    ),
    _schema(
        "write_file",
        "Create or fully replace a file. Prefer edit_file for targeted changes.",
        {
            "path": {"type": "string", "description": "Path relative to the project root"},
            "content": {"type": "string", "description": "Full file contents"},
        },
        ["path", "content"],
    ),
    _schema(
        "edit_file",
        "Replace an exact fragment of a file. old_text must occur exactly once (or pass replace_all).",
        {
            "path": {"type": "string"},
            "old_text": {"type": "string", "description": "Exact existing fragment"},
            "new_text": {"type": "string", "description": "Replacement fragment"},
            "replace_all": {"type": "boolean", "default": False},
        },
        ["path", "old_text", "new_text"],
    ),
    _schema(
        "append_file",
        "Append text to the end of a file. Use this to finish a file written in parts "
        "instead of leaving placeholder markers. Include newlines in content if needed.",
        {
            "path": {"type": "string", "description": "Path relative to the project root"},
            "content": {"type": "string", "description": "Text to append exactly as given"},
        },
        ["path", "content"],
    ),
    _schema(
        "site_page",
        "Create a complete HTML page with title, description, viewport, stylesheet "
        "and optional script. Use for every new page of a website project.",
        {
            "path": {"type": "string", "description": "Page path under site/, e.g. about.html"},
            "title": {"type": "string"},
            "body": {"type": "string", "description": "Inner HTML of <body>"},
            "description": {"type": "string", "default": ""},
            "stylesheet": {"type": "string", "default": "styles.css"},
            "script": {"type": "string", "default": ""},
            "lang": {"type": "string", "default": "en"},
        },
        ["path", "title", "body"],
    ),
    _schema(
        "site_theme",
        "Write a responsive CSS design system (tokens, typography, layout, cards, "
        "buttons, forms, dark mode) for a website project.",
        {
            "path": {"type": "string", "default": "styles.css"},
            "palette": {"type": "string", "enum": ["warm", "cool", "mono", "forest"], "default": "warm"},
            "mode": {"type": "string", "enum": ["light", "dark", "auto"], "default": "auto"},
            "radius": {"type": "integer", "default": 14, "minimum": 0, "maximum": 32},
        },
    ),
    _schema(
        "validate_site",
        "Check the website: pages, local links and assets, title, viewport, lang, "
        "alt text, duplicate ids and placeholder text.",
        {},
    ),
    _schema(
        "delete_path",
        "Delete a file or folder inside the project. Protected files cannot be deleted.",
        {
            "path": {"type": "string"},
            "recursive": {"type": "boolean", "description": "Delete the folder with all its contents", "default": False},
        },
        ["path"],
    ),
    _schema(
        "search_text",
        "Find a string or regex in the project's text files.",
        {
            "query": {"type": "string"},
            "path": {"type": "string", "default": "."},
            "regex": {"type": "boolean", "default": False},
            "limit": {"type": "integer", "default": 60, "minimum": 1, "maximum": 200},
        },
        ["query"],
    ),
    _schema(
        "run_command",
        "Run a command inside the project folder (e.g. python -m pytest or python -m py_compile main.py).",
        {
            "command": {"type": "string"},
            "timeout": {"type": "integer", "default": 120, "minimum": 5, "maximum": 300},
        },
        ["command"],
    ),
    _schema(
        "run_project",
        "Run the project headless for a few frames and return any errors. Use after major changes.",
        {
            "frames": {"type": "integer", "default": 8, "minimum": 1, "maximum": 600},
            "timeout": {"type": "integer", "default": 90, "minimum": 10, "maximum": 240},
            "autoplay": {
                "type": "boolean",
                "default": True,
                "description": "For games, inject right/jump/dash input during the headless run to catch movement and collision errors.",
            },
            "screenshots": {
                "type": "integer",
                "default": 0,
                "minimum": 0,
                "maximum": 6,
                "description": "Save this many rendered frames (PNG) for visual inspection with inspect_image; blank frames fail the run.",
            },
        },
    ),
    _schema(
        "validate_project",
        "Validate structure, project.json and the syntax of every Python file in the project.",
        {},
    ),
    _schema(
        "generate_sprite",
        "Ask the configured external image model for a sprite (one object, transparent background). "
        "Requires an image model with an /images/generations endpoint. Without one it fails honestly; "
        "use draw_sprite instead of retrying.",
        {
            "prompt": {"type": "string", "description": "What to draw, in English or Russian"},
            "path": {"type": "string", "description": "For example assets/sprites/player.png"},
            "style": {"type": "string", "enum": ["flat", "pixel", "painterly", "icon"], "default": "flat"},
            "size": {"type": "integer", "default": 256, "minimum": 64, "maximum": 1024},
        },
        ["prompt", "path"],
    ),
    _schema(
        "draw_sprite",
        "Draw any sprite yourself from a description and save it as a PNG under assets/. "
        "Use this when no image model is configured or when you need a specific object the model "
        "would miss. There are no subject templates: you decide every shape and color. "
        "Coordinates use a 0..100 space (x grows right, y grows down), independent of output size. "
        "Keep one palette, one outline color and one level of detail across all assets in the project. "
        "Pixel mode: pass rows of characters in `pixels` and a character-to-color `palette`; "
        "characters '.', '_' and space are transparent. Shape mode: pass a list of primitives in "
        "`shapes`; each item has `type` (ellipse, circle, rect, rounded_rect, polygon, polyline, "
        "line, arc), geometry, `fill`, optional `outline`/`outline_width` and `opacity`. "
        "`fill` can be a color string or a gradient object {type: linear|radial, from, to, angle, center, radius, stops}. "
        "Shapes are drawn in list order, later items on top. Call inspect_image afterwards and fix mistakes.",
        {
            "path": {"type": "string", "description": "For example assets/sprites/heart.png"},
            "mode": {"type": "string", "enum": ["shapes", "pixels"], "description": "Inferred from pixels/shapes when omitted"},
            "size": {"type": "integer", "default": 256, "minimum": 16, "maximum": 1024},
            "pixels": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Pixel mode rows of equal length, e.g. ['..XX..', '.XOOX.', '..XX..']",
            },
            "palette": {
                "type": "object",
                "additionalProperties": {"type": "string"},
                "description": "Pixel mode: one character per color, e.g. {'X': '#3a2418', 'O': '#ff6b4a'}",
            },
            "shapes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["ellipse", "circle", "rect", "rounded_rect", "polygon", "polyline", "line", "arc"]},
                        "center": {"type": "array", "items": {"type": "number"}, "description": "[x, y] in 0..100"},
                        "radius": {"type": ["number", "array"], "description": "Number or [rx, ry] in 0..100"},
                        "box": {"type": "array", "items": {"type": "number"}, "description": "[x0, y0, x1, y1] in 0..100"},
                        "points": {"type": "array", "items": {"type": "array", "items": {"type": "number"}}},
                        "start": {"type": "number", "description": "Line/arc start angle in degrees"},
                        "end": {"type": "number", "description": "Arc end angle in degrees"},
                        "width": {"type": "number", "description": "Line or arc width in 0..100 units"},
                        "fill": {"type": ["string", "object"], "description": "Color string or gradient object"},
                        "outline": {"type": "string"},
                        "outline_width": {"type": "number"},
                        "opacity": {"type": "number", "minimum": 0, "maximum": 1, "default": 1},
                    },
                    "required": ["type"],
                },
            },
            "background": {"type": "string", "description": "Optional solid background color; default transparent"},
            "trim": {"type": "boolean", "default": True, "description": "Trim empty margins and center the subject"},
        },
        ["path"],
    ),
    _schema(
        "generate_background",
        "Generate a scene background and save it into assets/.",
        {
            "prompt": {"type": "string"},
            "path": {"type": "string", "description": "For example assets/backgrounds/forest.png"},
            "width": {"type": "integer", "default": 1280, "minimum": 320, "maximum": 1920},
            "height": {"type": "integer", "default": 720, "minimum": 240, "maximum": 1080},
        },
        ["prompt", "path"],
    ),
    _schema(
        "inspect_image",
        "Inspect a PNG: size, transparency, object bounds and dominant colors.",
        {"path": {"type": "string"}},
        ["path"],
    ),
    _schema(
        "set_plan",
        "Replace the work plan with a list of concrete tasks.",
        {
            "tasks": {
                "type": "array",
                "items": {"type": "string"},
                "description": "3–8 concrete tasks in order",
            }
        },
        ["tasks"],
    ),
    _schema(
        "update_task",
        "Update the status of a plan task.",
        {
            "task": {"type": "string", "description": "Task id (t1), number or title"},
            "status": {"type": "string", "enum": ["pending", "in_progress", "done", "skipped"]},
        },
        ["task", "status"],
    ),
    _schema(
        "report_progress",
        "Update the percentage, stage and user-visible message in the editor.",
        {
            "percent": {"type": "number", "minimum": 0, "maximum": 100},
            "stage": {"type": "string"},
            "message": {"type": "string"},
        },
        ["percent"],
    ),
    _schema(
        "get_progress",
        "Read the current progress, plan and recent project events.",
        {},
    ),
    _schema(
        "finish",
        "Finish the job: 100%, all tasks done, final message.",
        {"message": {"type": "string"}},
        ["message"],
    ),
]

# The "Improve project" chat only needs to inspect the project. Keeping a
# separate schema list means the model cannot accidentally edit files or
# start a run while it is preparing suggestions for the user.
ANALYSIS_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "list_files",
        "read_file",
        "search_text",
        "validate_project",
        "validate_site",
        "inspect_image",
        "get_progress",
    }
)
ANALYSIS_TOOL_SCHEMAS: list[dict[str, Any]] = [
    schema for schema in TOOL_SCHEMAS if schema.get("name") in ANALYSIS_TOOL_NAMES
]

SITE_TOOL_NAMES = frozenset({"site_page", "site_theme", "validate_site"})


def tool_schemas_for(project_type: str, *, analysis: bool = False) -> list[dict[str, Any]]:
    """Tools advertised for a project type.

    Website tools are only useful (and only advertised) for site projects and
    the universal ``other`` mode, which deliberately receives every tool.
    """
    schemas = ANALYSIS_TOOL_SCHEMAS if analysis else TOOL_SCHEMAS
    if project_type in {"site", "other"}:
        return list(schemas)
    return [schema for schema in schemas if schema.get("name") not in SITE_TOOL_NAMES]


class AgentTools:
    def __init__(
        self,
        project: Project,
        *,
        image_config: dict | None = None,
        write_scope: tuple[str, ...] | None = None,
        confirm_write: Callable[[str, str], bool] | None = None,
    ) -> None:
        self.project = project
        self.image_config = image_config or {}
        # Specialist agents work on disjoint files. The scope is enforced for
        # every mutating tool; reads still see the whole project.
        self.write_scope = tuple(write_scope or ()) or None
        # Optional user gate: called once before the first mutating tool.
        # ``None`` means "headless or explicitly trusted" and allows the write.
        self.confirm_write = confirm_write
        self.write_denied = False
        # Work evidence used to decide whether ``finish`` is allowed. Installing
        # a library or reading files does not count as completing the task.
        self.files_changed = 0
        self.install_commands = 0
        self.validation_attempts = 0
        self.validation_passed = False
        self.run_attempts = 0
        self.run_passed = False
        self.last_validation_errors: list[str] = []
        self.last_run_error = ""
        # Human-readable audit trail of every project file the agent touched.
        # The editor shows it after a run and stores it in the history snapshot,
        # so a bad edit can be inspected before it is rolled back.
        self._changes: dict[str, dict[str, Any]] = {}
        self._scratch_writes: dict[str, int] = {}

    @property
    def changed_files(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._changes.values()]

    def reset_evidence(self) -> None:
        """Start a fresh task on the same tools instance.

        Durable team members reuse one ``AgentTools`` for several work items;
        without this reset the second task would inherit the first task's
        changed-file list and validation flags.
        """
        self._changes.clear()
        self._scratch_writes.clear()
        self.files_changed = 0
        self.install_commands = 0
        self.validation_attempts = 0
        self.validation_passed = False
        self.run_attempts = 0
        self.run_passed = False
        self.last_validation_errors = []
        self.last_run_error = ""

    def _note_scratch_write(self, relative: str) -> None:
        if not _is_scratch_path(relative):
            return
        count = self._scratch_writes.get(relative, 0) + 1
        self._scratch_writes[relative] = count
        if count > 3:
            raise ToolError(
                _t(
                    "This is the {count}th write to the temporary file {path}. You are stuck in a verification loop; "
                    "use run_project with screenshots/autoplay, fix the actual project files, and delete this scratch file.",
                    "Это уже {count}-я запись во временный файл {path}. Вы застряли в цикле проверок; "
                    "используйте run_project со скриншотами/автопрогоном, правьте файлы проекта и удалите этот временный файл.",
                    count=count,
                    path=relative,
                )
            )

    def _record_change(self, path: Path, action: str, **extra: Any) -> None:
        try:
            relative = self._relative(path)
        except (ValueError, OSError):
            return
        if not relative:
            return
        previous = self._changes.get(relative)
        if previous is None:
            entry: dict[str, Any] = {"path": relative, "action": action}
            self._changes[relative] = entry
        else:
            entry = previous
            # A delete always wins; a generated asset keeps its own label.
            if action == "delete" or previous.get("action") not in {"create", "generate"}:
                entry["action"] = action
        entry.update({key: value for key, value in extra.items() if value is not None})
        if path.is_file():
            try:
                entry["size"] = path.stat().st_size
            except OSError:
                pass

    def _screenshot_report(self, directory: Path | None) -> list[dict[str, Any]]:
        if directory is None or not directory.is_dir():
            return []
        result: list[dict[str, Any]] = []
        try:
            from PIL import Image
        except Exception:
            Image = None  # type: ignore[assignment]
        for path in sorted(directory.glob("*.png")):
            item: dict[str, Any] = {"path": self.project.rel(path)}
            if Image is not None:
                try:
                    image = Image.open(path).convert("RGB")
                    extrema = image.getextrema()
                    item["size"] = image.size
                    item["blank"] = all(high <= 8 for _low, high in extrema)
                except Exception:
                    item["blank"] = None
            result.append(item)
        return result

    def readiness(self) -> dict[str, Any]:
        missing: list[str] = []
        if self.files_changed <= 0:
            missing.append("no project file has been modified yet")
        if not self.validation_passed:
            missing.append("validate_project has not passed without errors")
        if not self.run_passed:
            missing.append("run_project has not finished successfully")
        scratch = self.project.scratch_files()
        if scratch:
            missing.append(
                "temporary verification files must be removed: "
                + ", ".join(path.name for path in scratch[:6])
            )
        return {
            "files_changed": self.files_changed,
            "changed_files": self.changed_files,
            "validation_passed": self.validation_passed,
            "run_passed": self.run_passed,
            "install_commands": self.install_commands,
            "ready": not missing,
            "missing": missing,
        }

    # -- helpers ----------------------------------------------------------
    def _path(self, relative: str, *, allow_protected: bool = True, write: bool = False) -> Path:
        if not str(relative).strip():
            raise ToolError(_t("Empty path.", "Пустой путь."))
        path = self.project.ensure_inside(relative)
        parts = path.relative_to(self.project.root).parts
        if parts and parts[0] == "_engine":
            raise ToolError(_t("The built-in engine folder _engine/ is read-only. Use re.bat sync-engine instead.", "Нельзя изменять встроенный движок _engine/. Используйте re.bat sync-engine."))
        rel = "/".join(parts)
        if not allow_protected and rel in PROTECTED:
            raise ToolError(_t("Protected file: {rel}", "Файл защищён: {rel}", rel=rel))
        if write and self.write_scope is not None:
            allowed = False
            for scope in self.write_scope:
                scope = str(scope).strip().strip("/")
                if not scope:
                    continue
                if (
                    rel == scope
                    or rel.startswith(scope + "/")
                    or ("*" in scope or "?" in scope or "[" in scope)
                    and fnmatch.fnmatch(rel, scope)
                ):
                    allowed = True
                    break
            if not allowed:
                raise ToolError(
                    _t(
                        "This specialist may only change: {scope}",
                        "Этот специалист может менять только: {scope}",
                        scope=", ".join(self.write_scope),
                    )
                )
        return path

    def _relative(self, path: Path) -> str:
        return self.project.rel(path)

    def _ok(self, **payload: Any) -> str:
        payload.setdefault("ok", True)
        return json.dumps(payload, ensure_ascii=False)

    def _fail(self, message: str, **payload: Any) -> str:
        payload.update({"ok": False, "error": message})
        return json.dumps(payload, ensure_ascii=False)

    def _allow_write(self, action: str, path: str) -> bool:
        if self.confirm_write is None:
            return True
        try:
            allowed = bool(self.confirm_write(action, path))
        except Exception:
            allowed = False
        if not allowed:
            self.write_denied = True
            raise ToolError(
                _t(
                    "The user did not approve this change.",
                    "Пользователь не подтвердил изменение.",
                )
            )
        return True

    # -- dispatch ---------------------------------------------------------
    def call(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        arguments = arguments or {}
        handler: Callable[..., str] | None = getattr(self, f"tool_{name}", None)
        if handler is None:
            return self._fail(_t("Unknown tool: {name}", "Неизвестный инструмент: {name}", name=name))
        try:
            return handler(**arguments)
        except TypeError as exc:
            return self._fail(_t("Invalid arguments for {name}: {exc}", "Неверные аргументы для {name}: {exc}", exc=exc, name=name))
        except ToolError as exc:
            return self._fail(str(exc))
        except Exception as exc:
            return self._fail(f"{type(exc).__name__}: {exc}")

    # -- exploration ------------------------------------------------------
    def tool_list_files(self, path: str = ".", depth: int = 3) -> str:
        base = self._path(path or ".", allow_protected=True)
        if not base.exists():
            raise ToolError(_t("Folder not found: {path}", "Папка не найдена: {path}", path=path))
        if base.is_file():
            return self._ok(path=self._relative(base), size=base.stat().st_size)
        depth = max(1, min(8, int(depth)))
        rows: list[str] = []
        root_depth = len(base.parts)
        for item in sorted(base.rglob("*"), key=lambda p: (p.is_file(), str(p).lower())):
            parts = item.relative_to(base).parts
            if len(parts) > depth:
                continue
            if any(part in IGNORED_DIRS for part in parts):
                continue
            if any(part == "__pycache__" for part in parts):
                continue
            suffix = "/" if item.is_dir() else ""
            size = f"  {item.stat().st_size} B" if item.is_file() else ""
            rows.append("  " * (len(parts) - 1) + item.name + suffix + size)
            if len(rows) >= 700:
                rows.append(_t("... (truncated)", "… (обрезано)"))
                break
        return self._ok(path=self._relative(base), entries=rows)

    def tool_read_file(self, path: str, start_line: int = 1, end_line: int = 800) -> str:
        file_path = self._path(path)
        if not file_path.is_file():
            raise ToolError(_t("File not found: {path}", "Файл не найден: {path}", path=path))
        size = file_path.stat().st_size
        if file_path.suffix.lower() not in TEXT_SUFFIXES and size > MAX_READ_BYTES:
            raise ToolError(_t("Not a text file. Use inspect_image for images.", "Это не текстовый файл. Используйте inspect_image для изображений."))
        start = max(1, int(start_line))
        end = max(start, int(end_line))
        clipped = (end - start + 1) > MAX_READ_LINES
        if clipped:
            end = start + MAX_READ_LINES - 1
        count_all = size <= MAX_COUNT_BYTES
        collected: list[str] = []
        total = 0
        # Streaming the range instead of rejecting the file keeps a large
        # generated scene or data file inspectable. Reading a slice used to be
        # impossible: the size check fired before the line range was applied.
        with file_path.open("r", encoding="utf-8", errors="replace") as handle:
            for total, line in enumerate(handle, 1):
                if total < start:
                    continue
                if total <= end:
                    collected.append(line.rstrip("\r\n"))
                elif not count_all:
                    break
        content = "\n".join(collected)
        truncated = clipped
        if len(content) > MAX_READ_BYTES:
            content = content[:MAX_READ_BYTES] + "\n… (truncated)"
            truncated = True
        payload: dict[str, Any] = {
            "path": self._relative(file_path),
            "start_line": start,
            "end_line": min(end, total) if total else start,
            "content": content,
        }
        if count_all:
            payload["total_lines"] = total
        if truncated:
            payload["truncated"] = True
        return self._ok(**payload)

    def tool_search_text(self, query: str, path: str = ".", regex: bool = False, limit: int = 60) -> str:
        base = self._path(path or ".")
        limit = max(1, min(200, int(limit)))
        pattern = None
        if regex:
            try:
                pattern = re.compile(query, re.IGNORECASE)
            except re.error as exc:
                raise ToolError(_t("Bad regular expression: {exc}", "Плохое регулярное выражение: {exc}", exc=exc))
        matches: list[dict[str, Any]] = []
        candidates = [base] if base.is_file() else base.rglob("*")
        for file_path in candidates:
            if len(matches) >= limit:
                break
            if not file_path.is_file() or file_path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            try:
                parts = file_path.relative_to(self.project.root).parts
            except ValueError:
                continue
            if any(part in IGNORED_DIRS for part in parts):
                continue
            try:
                if file_path.stat().st_size > 500_000:
                    continue
                lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for number, line in enumerate(lines, start=1):
                hit = bool(pattern.search(line)) if pattern else (query.lower() in line.lower())
                if hit:
                    matches.append({"path": self._relative(file_path), "line": number, "text": line[:300]})
                    if len(matches) >= limit:
                        break
        return self._ok(query=query, count=len(matches), matches=matches)

    # -- editing ----------------------------------------------------------
    def tool_write_file(self, path: str, content: str) -> str:
        if len(content.encode("utf-8")) > MAX_WRITE_BYTES:
            raise ToolError(_t("File too large. Split it into several files.", "Слишком большой файл. Разделите его на несколько."))
        file_path = self._path(path, write=True)
        rel = self._relative(file_path)
        if rel in PROTECTED_WRITE:
            raise ToolError(_t("project.json is managed by the editor and cannot be rewritten. Change project settings instead.", "project.json управляется редактором, переписывать его нельзя. Меняйте настройки проекта."))
        if (
            file_path == self.project.entry
            and self.project.project_type in {"game", "app"}
            and not _has_launch_code(content)
        ):
            raise ToolError(
                _t(
                    "This write would leave main.py without launch code, so the game would open and close immediately. "
                    "Add `if __name__ == \"__main__\": main()` at the end (and never finish a file with definitions only).",
                    "Эта запись оставит main.py без запуска: игра откроется и сразу закроется. "
                    "Добавьте `if __name__ == \"__main__\": main()` в конец (файл не должен заканчиваться только определениями).",
                )
            )
        self._allow_write("write", rel)
        self._note_scratch_write(rel)
        if file_path.suffix.lower() == ".json":
            try:
                json.loads(content)
            except ValueError as exc:
                raise ToolError(_t("Invalid JSON: {exc}", "Некорректный JSON: {exc}", exc=exc))
        existed = file_path.exists()
        file_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(file_path, content)
        if not _is_scratch_path(rel):
            self.files_changed += 1
        self.validation_passed = False
        self.run_passed = False
        self._record_change(file_path, "edit" if existed else "create")
        return self._ok(path=rel, bytes=len(content.encode("utf-8")), message=_t("File written.", "Файл записан."))

    def tool_edit_file(self, path: str, old_text: str, new_text: str, replace_all: bool = False) -> str:
        if not old_text:
            raise ToolError(_t("old_text must not be empty.", "old_text не может быть пустым."))
        file_path = self._path(path, write=True)
        if not file_path.is_file():
            raise ToolError(_t("File not found: {path}", "Файл не найден: {path}", path=path))
        rel = self._relative(file_path)
        if rel in PROTECTED_WRITE:
            raise ToolError(_t("project.json is managed by the editor and cannot be rewritten. Change project settings instead.", "project.json управляется редактором, переписывать его нельзя. Меняйте настройки проекта."))
        self._allow_write("edit", rel)
        self._note_scratch_write(rel)
        text = file_path.read_text(encoding="utf-8")
        count = text.count(old_text)
        if count == 0:
            raise ToolError(_t("old_text fragment not found. Re-read the file first.", "Фрагмент old_text не найден. Прочитайте файл заново."))
        if count > 1 and not replace_all:
            raise ToolError(_t("Fragment occurs {count} times. Add more context or pass replace_all=true.", "Фрагмент встречается {count} раз. Уточните контекст или передайте replace_all=true.", count=count))
        updated = text.replace(old_text, new_text) if replace_all else text.replace(old_text, new_text, 1)
        if (
            file_path == self.project.entry
            and self.project.project_type in {"game", "app"}
            and not _has_launch_code(updated)
        ):
            raise ToolError(
                _t(
                    "This edit would remove the launch code from main.py, so the game would open and close immediately. "
                    "Keep `if __name__ == \"__main__\": main()` or a top-level launch call at the end.",
                    "Эта правка удалит запуск из main.py: игра откроется и сразу закроется. "
                    "Оставьте `if __name__ == \"__main__\": main()` или вызов запуска в конце файла.",
                )
            )
        atomic_write_text(file_path, updated)
        if not _is_scratch_path(rel):
            self.files_changed += 1
        self.validation_passed = False
        self.run_passed = False
        self._record_change(file_path, "edit", replacements=count if replace_all else 1)
        return self._ok(
            path=rel,
            replacements=count if replace_all else 1,
            message=_t("File edited.", "Файл изменён."),
        )

    def tool_append_file(self, path: str, content: str) -> str:
        """Append to a file without rewriting its existing part.

        Large generated files used to be split into chunks that the model then
        forgot to finish (the ``# @@CHUNK@@`` failure). Appending keeps the
        already written prefix intact and costs only the new text.
        """
        if not content:
            raise ToolError(_t("Content must not be empty.", "Содержимое не может быть пустым."))
        if len(content.encode("utf-8")) > MAX_WRITE_BYTES:
            raise ToolError(_t("Chunk too large. Split it into several appends.", "Слишком большая порция. Разбейте её на несколько дописываний."))
        file_path = self._path(path, write=True)
        rel = self._relative(file_path)
        if rel in PROTECTED_WRITE:
            raise ToolError(_t("project.json is managed by the editor and cannot be rewritten. Change project settings instead.", "project.json управляется редактором, переписывать его нельзя. Меняйте настройки проекта."))
        self._allow_write("append", rel)
        self._note_scratch_write(rel)
        existed = file_path.is_file()
        file_path.parent.mkdir(parents=True, exist_ok=True)
        previous = ""
        if existed:
            try:
                previous = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                raise ToolError(_t("Could not read the file: {exc}", "Не удалось прочитать файл: {exc}", exc=exc))
        combined = previous + content
        if file_path.suffix.lower() == ".json":
            try:
                json.loads(combined)
            except ValueError as exc:
                raise ToolError(_t("Appending would make invalid JSON: {exc}", "После дописывания JSON станет некорректным: {exc}", exc=exc))
        atomic_write_text(file_path, combined)
        if not _is_scratch_path(rel):
            self.files_changed += 1
        self.validation_passed = False
        self.run_passed = False
        self._record_change(
            file_path,
            "edit" if existed else "create",
            appended=len(content.encode("utf-8")),
        )
        return self._ok(
            path=rel,
            appended=len(content.encode("utf-8")),
            total=len(combined.encode("utf-8")),
            message=_t("Text appended.", "Текст дописан."),
        )

    def tool_delete_path(self, path: str, recursive: bool = False) -> str:
        file_path = self._path(path, allow_protected=False, write=True)
        rel = self._relative(file_path)
        if rel in {"assets", "progress", "_engine"}:
            raise ToolError(_t("This folder is protected.", "Эта папка защищена."))
        self._allow_write("delete", rel)
        if file_path.is_dir():
            if not recursive and any(file_path.iterdir()):
                raise ToolError(_t("Folder is not empty. Pass recursive=true.", "Папка не пуста. Укажите recursive=true."))
        was_directory = file_path.is_dir()
        self.project.delete_path(path)
        self.files_changed += 1
        self.validation_passed = False
        self.run_passed = False
        self._record_change(file_path, "delete", directory=was_directory)
        return self._ok(path=rel, message=_t("Deleted.", "Удалено."))

    # -- execution --------------------------------------------------------
    def tool_run_command(self, command: str, timeout: int = 120) -> str:
        command = command.strip()
        if not command:
            raise ToolError(_t("Empty command.", "Пустая команда."))
        lowered = command.lower()
        forbidden = ("format ", "shutdown", "rm -rf /", "del /s /q c:", "remove-item -recurse c:\\")
        if any(item in lowered for item in forbidden):
            raise ToolError(_t("Command blocked as unsafe.", "Команда заблокирована как небезопасная."))
        install_markers = (
            "pip install",
            "pip3 install",
            "pip uninstall",
            "uv pip install",
            "conda install",
            "npm install",
            "winget install",
            "choco install",
        )
        package_install = any(marker in lowered for marker in install_markers)
        if package_install:
            self.install_commands += 1
        timeout = max(5, min(300, int(timeout)))
        popen_kwargs: dict[str, Any] = {}
        if os.name == "nt":
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        else:
            popen_kwargs["start_new_session"] = True
        try:
            process = subprocess.Popen(
                command,
                cwd=str(self.project.root),
                env=self.project.run_env(),
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                **popen_kwargs,
            )
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                _kill_process_tree(process)
                try:
                    stdout, stderr = process.communicate(timeout=5)
                except Exception:
                    stdout, stderr = "", ""
                return self._fail(
                    _t(
                        "Command did not finish within {timeout} s and was stopped with its child processes.",
                        "Команда не завершилась за {timeout} сек. и была остановлена вместе с дочерними процессами.",
                        timeout=timeout,
                    )
                )
        except OSError as exc:
            return self._fail(_t("Could not start the command: {exc}", "Не удалось запустить команду: {exc}", exc=exc))
        output = (stdout or "") + ("\n" + stderr if stderr else "")
        return self._ok(
            command=command,
            returncode=process.returncode,
            package_install=package_install,
            output=output[-9000:],
        )

    def _run_plain_project(self, timeout: int = 90) -> str:
        """Run site/other projects through their ``--check`` entry mode."""
        entry = self.project.entry
        if not entry.exists():
            raise ToolError(
                _t(
                    "Entry point {name} not found.",
                    "Точка входа {name} не найдена.",
                    name=entry.name,
                )
            )
        env = self.project.run_env()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        timeout = max(10, min(240, int(timeout)))
        started = time.perf_counter()
        command = [*python_command(), str(entry), "--check"]
        self.run_attempts += 1
        try:
            result = subprocess.run(
                command,
                cwd=str(self.project.root),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            self.run_passed = False
            self.last_run_error = _t(
                "The project check did not finish within {timeout} s.",
                "Проверка проекта не завершилась за {timeout} сек.",
                timeout=timeout,
            )
            return self._fail(self.last_run_error)
        except OSError as exc:
            self.run_passed = False
            self.last_run_error = f"{type(exc).__name__}: {exc}"
            return self._fail(self.last_run_error)
        elapsed = time.perf_counter() - started
        output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
        self.run_passed = result.returncode == 0
        self.last_run_error = (
            "" if self.run_passed else (result.stderr or result.stdout or "")[-1200:]
        )
        return self._ok(
            returncode=result.returncode,
            seconds=round(elapsed, 2),
            output=output[-9000:],
            message=(
                _t("The project check passed.", "Проверка проекта пройдена.")
                if self.run_passed
                else _t("The project check failed.", "Проверка проекта не пройдена.")
            ),
            readiness=self.readiness(),
        )

    def tool_run_project(
        self,
        frames: int = 8,
        timeout: int = 90,
        autoplay: bool = True,
        screenshots: int = 0,
    ) -> str:
        if self.project.project_type in {"site", "other"}:
            return self._run_plain_project(timeout)
        entry = self.project.entry
        if not entry.exists():
            raise ToolError(_t("Entry point main.py not found.", "Точка входа main.py не найдена."))
        if self.project.project_type in {"game", "app"} and not self.project.has_launch_block():
            self.run_passed = False
            self.last_run_error = _t(
                "The entry point has no launch code; the project would open and close immediately. "
                "Add `if __name__ == \"__main__\": main()` at the end of main.py and run again.",
                "В точке входа нет запуска: проект откроется и сразу закроется. "
                "Добавьте `if __name__ == \"__main__\": main()` в конец main.py и запустите снова.",
            )
            return self._fail(self.last_run_error)
        env = self.project.run_env()
        env["SDL_VIDEODRIVER"] = "dummy"
        env["SDL_AUDIODRIVER"] = "dummy"
        env["RE_FRAMES"] = str(max(1, min(600, int(frames))))
        if autoplay and self.project.project_type == "game":
            env["RE_AUTOPLAY"] = "1"
        screenshot_dir = None
        screenshot_limit = max(0, min(6, int(screenshots or 0)))
        if screenshot_limit:
            screenshot_dir = (
                self.project.root
                / ".reasonable"
                / "screenshots"
                / time.strftime("%Y%m%d-%H%M%S")
            )
            env["RE_SCREENSHOTS"] = str(screenshot_dir)
            env["RE_SCREENSHOT_FRAMES"] = str(screenshot_limit)
        timeout = max(10, min(240, int(timeout)))
        started = time.perf_counter()
        command = self.project.run_command(splash_wrapper=True)
        self.run_attempts += 1
        try:
            result = subprocess.run(
                command,
                cwd=str(self.project.root),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            self.run_passed = False
            self.last_run_error = _t("Project did not exit within {timeout} s.", "Проект не завершился за {timeout} сек.", timeout=timeout)
            return self._fail(self.last_run_error + _t(" Check infinite loops or blocking dialogs.", " Проверьте бесконечные циклы/диалоги."))
        elapsed = time.perf_counter() - started
        output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
        screenshot_report = self._screenshot_report(screenshot_dir)
        if screenshot_limit:
            if not screenshot_report:
                self.run_passed = False
                self.last_run_error = _t(
                    "No screenshots were captured. The project may not draw anything or exits before the first frame.",
                    "Скриншоты не получены: проект ничего не рисует или завершается до первого кадра.",
                )
                return self._fail(self.last_run_error + "\n" + output[-4000:])
            if self.project.project_type in {"game", "app"} and all(
                item.get("blank") for item in screenshot_report
            ):
                self.run_passed = False
                self.last_run_error = _t(
                    "Every captured frame is blank/black. The application window is not showing its UI.",
                    "Все сохранённые кадры пустые/чёрные: приложение не показывает интерфейс.",
                )
                return self._fail(self.last_run_error + "\n" + output[-4000:])
        if autoplay and self.project.project_type == "game" and "RE_AUTOPLAY_IDLE" in output:
            self.run_passed = False
            self.last_run_error = _t(
                "The game window did not change for 120 frames during autoplay: it is stuck on a menu or frozen. "
                "Make the first menu reachable by Enter and ensure the game actually starts.",
                "Экран игры не менялся 120 кадров во время автопрогона: игра застряла в меню или зависла. "
                "Сделайте так, чтобы меню запускалось по Enter и игра действительно начиналась.",
            )
            return self._fail(self.last_run_error + "\n" + output[-4000:])
        self.run_passed = result.returncode == 0
        self.last_run_error = "" if self.run_passed else (result.stderr or result.stdout or "")[-1200:]
        return self._ok(
            returncode=result.returncode,
            seconds=round(elapsed, 2),
            output=output[-9000:],
            screenshots=screenshot_report,
            message=_t("The project ran without exceptions.", "Проект запустился без исключений.") if result.returncode == 0 else _t("The project exited with an error.", "Проект завершился с ошибкой."),
            readiness=self.readiness(),
        )

    def _site_target(self, path: str) -> Path:
        raw = str(path or "").strip().replace("\\", "/").lstrip("/")
        if not raw:
            raise ToolError(_t("Empty path.", "Пустой путь."))
        prefix = SITE_DIR + "/"
        if raw.startswith(prefix):
            raw = raw[len(prefix) :]
        target = self._path(prefix + raw, write=True)
        root = site_root(self.project.root).resolve()
        if not is_relative_to(target, root):
            raise ToolError(_t("Pages must stay inside site/.", "Страницы должны находиться внутри site/."))
        return target

    def _site_reference(self, value: str, *, default: str = "") -> str:
        text = str(value or "").strip().replace("\\", "/")
        if not text:
            return default
        if text.startswith(("/", "http://", "https://", "//", "data:", "javascript:")):
            raise ToolError(_t("Use a relative file name for site assets.", "Для ассетов сайта используйте относительное имя файла."))
        if ".." in Path(text).parts:
            raise ToolError(_t("Asset paths cannot leave site/.", "Путь к ассету не может выходить из site/."))
        return text

    def tool_site_page(
        self,
        path: str,
        title: str,
        body: str,
        description: str = "",
        stylesheet: str = "styles.css",
        script: str = "",
        lang: str = "en",
    ) -> str:
        target = self._site_target(path)
        if target.suffix.lower() not in {".html", ".htm"}:
            raise ToolError(_t("A site page must be an .html file.", "Страница сайта должна быть файлом .html."))
        title = str(title or "").strip()
        if not title:
            raise ToolError(_t("A page needs a non-empty title.", "У страницы должен быть непустой заголовок."))
        self._allow_write("write", self._relative(target))
        lang_value = re.sub(r"[^A-Za-z0-9_-]", "", str(lang or "en")) or "en"
        css = self._site_reference(stylesheet, default="styles.css")
        js = self._site_reference(script, default="")
        head = [
            "<!doctype html>",
            f'<html lang="{lang_value}">',
            "<head>",
            '  <meta charset="utf-8">',
            '  <meta name="viewport" content="width=device-width, initial-scale=1">',
            f"  <title>{html.escape(title)}</title>",
        ]
        if description:
            head.append(
                f'  <meta name="description" content="{html.escape(str(description), quote=True)}">'
            )
        if css:
            head.append(f'  <link rel="stylesheet" href="{html.escape(css, quote=True)}">')
        head.extend(["</head>", "<body>", str(body or "").rstrip()])
        if js:
            head.append(f'  <script src="{html.escape(js, quote=True)}" defer></script>')
        head.extend(["</body>", "</html>", ""])
        document = "\n".join(head)
        existed = target.is_file()
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(target, document)
        self.files_changed += 1
        self.validation_passed = False
        self.run_passed = False
        self._record_change(target, "edit" if existed else "create", kind="page")
        return self._ok(
            path=self._relative(target),
            bytes=len(document.encode("utf-8")),
            message=_t("Page written.", "Страница записана."),
        )

    def tool_site_theme(
        self,
        path: str = "styles.css",
        palette: str = "warm",
        mode: str = "auto",
        radius: int = 14,
    ) -> str:
        target = self._site_target(path)
        if target.suffix.lower() != ".css":
            raise ToolError(_t("The theme must be a .css file.", "Тема должна быть файлом .css."))
        self._allow_write("write", self._relative(target))
        css = _site_theme_css(str(palette or "warm"), str(mode or "auto"), int(radius))
        existed = target.is_file()
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(target, css)
        self.files_changed += 1
        self.validation_passed = False
        self.run_passed = False
        self._record_change(target, "edit" if existed else "create", kind="theme")
        return self._ok(
            path=self._relative(target),
            palette=palette,
            mode=mode,
            bytes=len(css.encode("utf-8")),
            message=_t("Design system written.", "Дизайн-система записана."),
        )

    def tool_validate_site(self) -> str:
        issues = validate_site(self.project.root)
        errors = [issue for issue in issues if issue.get("level") == "error"]
        self.validation_attempts += 1
        self.validation_passed = not errors
        self.last_validation_errors = (
            [str(issue.get("message") or "") for issue in errors] if errors else []
        )
        return self._ok(
            issues=issues,
            has_errors=bool(errors),
            readiness=self.readiness(),
        )

    def tool_validate_project(self) -> str:
        issues = self.project.validate()
        errors = [issue for issue in issues if issue.level == "error"]
        self.validation_attempts += 1
        self.validation_passed = not errors
        self.last_validation_errors = [issue.message for issue in errors]
        return self._ok(
            issues=[
                {"level": issue.level, "message": issue.message, "path": issue.path}
                for issue in issues
            ],
            has_errors=bool(errors),
            readiness=self.readiness(),
        )

    # -- assets -----------------------------------------------------------
    def tool_generate_sprite(self, prompt: str, path: str, style: str = "flat", size: int = 256) -> str:
        from reasonable.ai.sprites import generate_sprite

        target = self._path(path, write=True)
        assets = self.project.root / "assets"
        if not is_relative_to(target, assets):
            raise ToolError(_t("Save sprites only under assets/.", "Спрайты сохраняйте только в assets/."))
        self._allow_write("generate", self._relative(target))
        result = generate_sprite(
            prompt,
            target,
            style=style,
            size=size,
            image_config=self.image_config,
            context=self.project.goal or self.project.name,
        )
        record_event(self.project.root, "asset", _t("Sprite generated: {path}", "Спрайт сгенерирован: {path}", path=self._relative(target)))
        self.files_changed += 1
        self._record_change(target, "generate", kind="sprite", prompt=prompt)
        return self._ok(**result)

    def tool_draw_sprite(
        self,
        path: str,
        mode: str = "",
        size: int = 256,
        pixels: list[str] | None = None,
        palette: dict[str, Any] | None = None,
        shapes: list[dict[str, Any]] | None = None,
        background: str | None = None,
        trim: bool = True,
    ) -> str:
        from reasonable.ai.drawing import draw_sprite

        target = self._path(path, write=True)
        assets = self.project.root / "assets"
        if not is_relative_to(target, assets):
            raise ToolError(_t("Save sprites only under assets/.", "Спрайты сохраняйте только в assets/."))
        self._allow_write("generate", self._relative(target))
        result = draw_sprite(
            target,
            mode=mode or None,
            size=size,
            pixels=pixels,
            palette=palette,
            shapes=shapes,
            background=background,
            trim=trim,
        )
        record_event(self.project.root, "asset", _t("Sprite drawn: {path}", "Спрайт нарисован: {path}", path=self._relative(target)))
        self.files_changed += 1
        self._record_change(target, "generate", kind="sprite", prompt=mode)
        return self._ok(**result)

    def tool_generate_background(
        self,
        prompt: str,
        path: str,
        width: int = 1280,
        height: int = 720,
    ) -> str:
        from reasonable.ai.sprites import generate_background

        target = self._path(path, write=True)
        assets = self.project.root / "assets"
        if not is_relative_to(target, assets):
            raise ToolError(_t("Save backgrounds only under assets/.", "Фоны сохраняйте только в assets/."))
        self._allow_write("generate", self._relative(target))
        result = generate_background(
            prompt,
            target,
            width=width,
            height=height,
            image_config=self.image_config,
            context=self.project.goal or self.project.name,
        )
        record_event(self.project.root, "asset", _t("Background created: {path}", "Фон создан: {path}", path=self._relative(target)))
        self.files_changed += 1
        self._record_change(target, "generate", kind="background", prompt=prompt)
        return self._ok(**result)

    def tool_inspect_image(self, path: str) -> str:
        file_path = self._path(path)
        if not file_path.is_file():
            raise ToolError(_t("File not found: {path}", "Файл не найден: {path}", path=path))
        try:
            from PIL import Image
        except ImportError:
            raise ToolError(_t("Pillow is not installed.", "Pillow не установлен."))
        try:
            image = Image.open(file_path).convert("RGBA")
        except Exception as exc:
            raise ToolError(_t("Could not open image: {exc}", "Не удалось открыть изображение: {exc}", exc=exc))
        alpha = image.getchannel("A")
        bbox = alpha.getbbox()
        small = image.copy()
        small.thumbnail((96, 96))
        # Pillow 14 removes Image.getdata(); get_flattened_data is the forward
        # compatible reader (Pillow 11+). Keep a fallback for Pillow 10.
        reader = getattr(small, "get_flattened_data", None) or small.getdata
        pixels = list(reader())
        colors: dict[tuple[int, int, int], int] = {}
        opaque = 0
        for r, g, b, a in pixels:
            if a > 30:
                opaque += 1
            if a < 40:
                continue
            key = (r // 32 * 32, g // 32 * 32, b // 32 * 32)
            colors[key] = colors.get(key, 0) + 1
        palette = [
            "#%02x%02x%02x" % key
            for key, _count in sorted(colors.items(), key=lambda item: item[1], reverse=True)[:6]
        ]
        total = max(1, small.width * small.height)
        return self._ok(
            path=self._relative(file_path),
            size=image.size,
            mode=image.mode,
            alpha_bbox=bbox,
            opaque_percent=round(opaque / total * 100, 1),
            dominant_colors=palette,
        )

    # -- progress ---------------------------------------------------------
    def tool_get_progress(self) -> str:
        state = read_state(self.project.root)
        events = read_events(self.project.root, limit=20)
        return self._ok(state=state, events=events)

    def tool_set_plan(self, tasks: list[str]) -> str:
        if not isinstance(tasks, list) or not tasks:
            raise ToolError(_t("A non-empty list of tasks is required.", "Нужен непустой список задач."))
        state = set_plan(self.project.root, [str(item) for item in tasks][:12])
        return self._ok(tasks=state.get("tasks", []), message=_t("Plan updated.", "План обновлён."))

    def tool_update_task(self, task: str, status: str) -> str:
        state = update_task(self.project.root, task, status)
        return self._ok(tasks=state.get("tasks", []), message=_t("Task updated.", "Задача обновлена."))

    def tool_report_progress(self, percent: float, stage: str = "", message: str = "") -> str:
        ready = self.readiness()
        requested = float(percent)
        capped = requested
        note = ""
        if requested >= 100 and not ready["ready"]:
            capped = 99
            note = _t(" 100% is reserved until validation and a successful run.", " 100% зарезервировано до успешной проверки и запуска проекта.")
        state = set_progress(
            self.project.root,
            capped,
            stage=stage or None,
            message=((message or "") + note).strip() or None,
            status="running" if capped < 100 else "done",
        )
        return self._ok(
            percent=state.get("percent"),
            stage=state.get("stage"),
            message=state.get("message"),
            readiness=ready,
        )

    def tool_finish(self, message: str) -> str:
        ready = self.readiness()
        if not ready["ready"]:
            missing = "; ".join(ready["missing"])
            return self._fail(
                _t(
                    "Too early to finish. Still missing: {missing}. Keep going: "
                    "edit the project files, run validate_project, fix every error "
                    "and then run_project. Installing a library or reading files is "
                    "not a completed task.",
                    "Завершать работу рано. Не выполнено: {missing}. Продолжай: "
                    "измени файлы проекта, запусти validate_project, исправь ошибки "
                    "и запусти run_project. Установка библиотеки или чтение файлов "
                    "не считается выполненной задачей.",
                    missing=missing,
                ),
                readiness=ready,
            )
        state = finish_progress(
            self.project.root,
            message or _t("Project ready", "Проект готов"),
            require_done=True,
        )
        return self._ok(percent=state.get("percent"), message=message, readiness=ready)
