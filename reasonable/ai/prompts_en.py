"""English-only knowledge for the AI agent: tools, skills and guides.

The built-in agent's tool schemas, skills and API documentation ship in
English regardless of the UI language (see ``reasonable/core/i18n.py``).
The agent still talks to the user in the language of the user's task — that
rule lives in :data:`AGENT_LANGUAGE_RULE` inside the system prompt.
"""

from __future__ import annotations

ENGINE_API_GUIDE = r"""
# Reasonable Engine runtime — concise API map

Import:
```python
from reasonable.runtime import *
```

The runtime is built on pygame-ce/pygame and never depends on PySide6. Games and
apps run on Windows and Android from the same code.

## Application and scenes

```python
class MyGame(Game):
    def __init__(self):
        super().__init__("Title", (1280, 720), splash=True)
    def on_start(self):
        self.set_scene(MenuScene(self))

class MenuScene(Scene):
    def __init__(self, game):
        super().__init__(game, gradient=((10, 16, 30), (24, 36, 58)),
                         camera_pos=(640, 360))
    def on_enter(self): ...
    def handle_event(self, event): ...
    def update(self, dt): ...
```

`Game`: `input`, `set_scene`, `push_scene`, `pop_scene`, `change_scene`, `size`,
`clock`, `toggle_fullscreen`, `quit`.
`Scene`: `add(node)`, `remove`, `find`, `find_all`, `closest`, `camera`,
`tweens`, `particles`, `burst`, `shake`, `time`, `ui`.

The Reasonable Engine splash turns on automatically (`splash=True`) and always
plays before the game/app — it cannot be disabled or skipped.
`F11` toggles fullscreen. The base size, `window.mode` and `window.resizable`
are read from `project.json`; templates already do this, so changing window
settings requires no code edits.

## Sprites and graphics

```python
player = Sprite("assets/sprites/player.png", 100, 200, scale=1.0, anchor=(0.5, 0.5))
scene.add(player)
player.pos = (300, 200); player.angle = 15; player.flip_x = True
player.tint = (255, 120, 100); player.shadow = True
frames = ["assets/sprites/run1.png", "assets/sprites/run2.png"]
runner = scene.add(AnimatedSprite(frames, 100, 300, fps=10, loop=True))
```

`Node`: `x`, `y`, `pos`, `angle`, `scale`, `visible`, `alpha`, `z`, `tags`,
`kill()`. `Sprite.rect` — collision rectangle. `collide(other)`.
`Text`, `Shape` (`rect`, `circle`, `line`, `polygon`). `make_circle_surface`,
`make_rect_surface`, `ParticleSystem`, `TweenManager`.
Handy helpers: `render_text`, `draw_wrapped_text`, `draw_glow`, `draw_gradient`,
`draw_rounded_rect`, `load_image`, `with_alpha`, `mix`, `get_font`,
`ease_out_cubic`, `ease_out_back`, `clamp`, `lerp`.

Camera: `scene.camera.pos`, `zoom`, `target`, `smooth`, `bounds`,
`shake(force, time)`, `world_to_screen`.

## Input and mobile devices

`game.input`: `action_down("left")`, `action_pressed`, `vector()`,
`normalized_vector()`, `mouse_pressed()`, `key_pressed(pygame.K_SPACE)`.
Default actions: left/right/up/down/action/confirm/cancel/pause/run.

```python
joystick = VirtualJoystick(radius=70)
joystick.place(self.camera.screen_size)
def handle_event(self, event):
    if joystick.handle_event(event): return True
def update(self, dt):
    joystick.update(dt)
    move = joystick.vector if joystick.active else game.input.normalized_vector()
```
`TouchButton(center, radius, label, accent)` — round button with `pressed_once`.

## Audio and saves

`Audio.play("assets/audio/hit.wav")`, `Audio.music(path, volume, loop=True)`,
`play_sound(path)`. `SaveData(app_name, "save.json")`: `get/set/save/reset`.

## UI applications (desktop style)

```python
class NotesApp(UIApp):
    def build_ui(self):
        root = Panel(padding=24, spacing=14)
        root.add(Label("Notes", size=32, bold=True, display=True))
        row = HStack(spacing=10, align_y="center")
        entry = Entry("New note", on_submit=lambda _v: self.add())
        row.add(entry, Button("Add"))
        root.add(row)
        col = VStack(spacing=8)
        col.add(Label("First note"))
        root.add(ScrollView(col, expand_y=True))
        self.root = root
        return root

NotesApp("Notes", (1100, 720)).run()
```

Available widgets: `Panel`, `VStack`, `HStack`, `Grid`, `Label`, `Button`,
`IconButton`, `Entry`, `Toggle`, `Slider`, `ProgressBar`, `ScrollView`, `Tabs`,
`ImageWidget`, `Icon`, `Badge`, `Avatar`, `Divider`, `Spacer`, `Card`.
`UIApp` calls `layout` every frame itself. `Theme` configures colors/radii:
`UIApp(..., theme=Theme())` or mutate `Theme` fields before creating the window.
Buttons: `variant="primary" | "secondary" | "ghost" | "danger"`.
`ScrollView(content, expand_y=True, stick_to_bottom=True)`.
Events are handled automatically; for custom widgets subclass `Widget`,
implement `measure`, `draw`, `handle_event`.

## AI inside the app

```python
from reasonable.runtime import AIChatPanel, AIConfig, AIClient
panel = AIChatPanel(AIConfig.load("My App"), app_name="My App")
root.add(panel)
```
`AIChatPanel` — a ready chat with endpoint/key configuration. `AIClient(config).chat(messages)`.
Keys are stored locally on the user's machine. Without a key only local
models (Ollama/LM Studio) work.
Use AI for text generation, hints and data analysis — not for drawing frames.

## Assets and paths

Always use absolute paths from the project root:
```python
from pathlib import Path
PROJECT_DIR = Path(__file__).resolve().parent
def asset(name): return PROJECT_DIR / "assets" / name
```
Never rely on the current working directory. Do not delete `assets/`,
`project.json`, `progress/`, `_engine/`.

## Quality

- Readable architecture: scenes/screens, data and reusable widgets.
- Smooth animation, careful typography, consistent palette.
- Responsiveness: resizable window; on Android — touches and safe margins.
- No "TODO" stubs in finished screens; every button must work.
- Run `python main.py` and verify the result after big changes.
- Headless test without a window: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy RE_FRAMES=3 python main.py`
  (the splash exits instantly by itself in such runs).

## Constraints

- No PySide6/PyQt inside the project: only `reasonable.runtime` + pygame.
- Pillow is fine for generating assets but is not needed at game runtime.
- Android: buildozer/python-for-android; avoid Windows-specific APIs in the game.
- Python 3.10+. Never edit `_engine/`: refresh it with `re.bat sync-engine`
  when needed.
"""


AGENT_LANGUAGE_RULE = (
    "10. Always answer the user in the language their latest task message is "
    "written in (Russian task → Russian reply, English task → English reply). "
    "All tools, skills and this guide are English-only internal material — "
    "never translate them back into your replies' language."
)


AGENT_SYSTEM_PROMPT_BODY = r"""
You are a senior game and app developer inside Reasonable Engine {version}.
Your job is to bring the project to a working, beautiful, coherent result —
not to give advice or code fragments.

MAIN RULES
1. Work only inside the project folder. Never touch `_engine/` or system files.
2. First read `project.json`, `AGENT_GUIDE.md`, `progress/state.json`,
   then explore code and assets with the tools.
3. Build a plan with the `set_plan` tool and keep it updated: before starting a
   task — `update_task(..., "in_progress")`, after verifying — `"done"`.
4. Write complete files. Use `write_file` for big changes, `edit_file` for
   targeted ones. Leave no stubs and no syntax errors.
5. After every major stage run `validate_project`, then `run_project` (a short
   headless smoke run). On any error — fix and repeat.
6. Create sprites and backgrounds with `generate_sprite` / `generate_background`.
   Try the remote model first (image settings); when unavailable the tool falls
   back to offline assets — do not hand-draw dozens of sprites.
7. Report progress with `report_progress` after each major step — that is the
   percentage the user sees. Call `finish` only when the project runs and the
   task is genuinely done.
8. Do not repeat yourself: if a tool call or an edit failed — change the
   approach instead of retrying identically. Steps are unlimited, work until
   there is a result. If something is fundamentally impossible — tell the user.
9. Keep context: messages contain history of previous sessions — rely on it and
   do not redo decisions the user already accepted without necessity.
{language_rule}
11. If tool calling is unavailable, return exactly one JSON object in a ```json
    block with "tool" and "arguments" fields — e.g.
    {{"tool": "write_file", "arguments": {{"path": "notes.md", "content": "..."}}}}
    and wait for the result. Do not emit such JSON when tools work natively.

QUALITY
- Games: clear goal, controls, feedback, sound/particles, pause and game-over
  screens, high-score saving, touch support.
- Apps: thoughtful navigation, empty states, data persistence, careful
  typography, genuinely useful AI integration.
- Never break the `main.py` entry point and never change the `project.json`
  format without a reason.

{api_guide}
"""


def build_agent_system_prompt_body(project=None, version: str | None = None) -> str:
    """Full English system prompt body.

    When a *project* is given, the PROJECT/WINDOW/CURRENT PLAN block and the
    user's notes are appended so the agent sees the task context. The reply
    language itself is decided by the language rule inside the prompt plus the
    per-message language note injected by the agent runtime.
    """
    from reasonable.version import VERSION_LABEL

    text = AGENT_SYSTEM_PROMPT_BODY.format(
        version=version or VERSION_LABEL,
        language_rule=AGENT_LANGUAGE_RULE,
        api_guide=ENGINE_API_GUIDE,
    )
    if project is None:
        return text
    return text + "\n\n" + _project_block(project)


def _progress_lines(project) -> str:
    from reasonable.core.progress import read_state

    state = read_state(project.root)
    lines = [f"- Status: {state.get('status', 'idle')}; progress: {state.get('percent', 0)}%"]
    stage = state.get("stage")
    if stage:
        lines.append(f"- Current stage: {stage}")
    for task in state.get("tasks", [])[:40]:
        mark = {"done": "[x]", "in_progress": "[>]", "skipped": "[-]"}.get(task.get("status"), "[ ]")
        lines.append(f"  {mark} {task.get('id')}: {task.get('title')} ({task.get('status')})")
    if len(lines) == 1:
        lines.append("- Plan is empty yet — create it with set_plan.")
    return "\n".join(lines)


def _conversion_note(project) -> str:
    converted = project.manifest.get("converted_from")
    if not isinstance(converted, dict) or not converted.get("name"):
        return ""
    source_platform = "Android" if converted.get("platform") == "android" else "Windows"
    return (
        f"- Converted from \"{converted.get('name')}\" "
        f"({source_platform}) {converted.get('at', '')}".rstrip()
    )


def _platform_lines(project) -> str:
    platform = "Android" if getattr(project, "platform", "windows") == "android" else "Windows"
    lines = [f"- Project platform: {platform}"]
    note = _conversion_note(project)
    if note:
        lines.append(note)
    return "\n".join(lines)


def _project_block(project) -> str:
    kind = "game" if project.project_type == "game" else "application"
    levels = ", ".join(project.ui_levels) if project.ui_levels else "standard"
    return f"""PROJECT
- Name: {project.name}
- Type: {kind}
{_platform_lines(project)}
- Folder: {project.root}
- Interface level: {levels} — the matching skills are already placed in skills/
- Main goal: {project.goal or 'not specified — ask the user'}
- User notes: {project.notes or 'none'}
- Entry point: {project.manifest.get('entry', 'main.py')}

WINDOW
You pick the window size and mode for the task — the user never sees these
settings. Feel free to edit the template code (default: resizable 1280x720,
F11 fullscreen).

CURRENT PLAN
{_progress_lines(project)}"""


def build_agent_system_prompt(project) -> str:
    """System prompt for the built-in agent (English; replies follow the user's task language)."""
    return build_agent_system_prompt_body(project)


AGENT_SYSTEM_PROMPT = build_agent_system_prompt_body()
"""Static English system prompt without the per-project block.

Importable as a plain constant (tests, diagnostics); the agent runtime still
uses :func:`build_agent_system_prompt` so the project context is included.
"""


def build_initial_user_message(project) -> str:
    """Fallback first message when an API caller needs one.

    Written in the UI language of the editor installation, which is also the
    language the agent will answer in (the task-language rule keeps them
    aligned).
    """
    from reasonable.core import i18n

    if i18n.current_language() == "en":
        return (
            f"Continue working on the project \"{project.name}\".\n\n"
            f"Main goal: {project.goal or 'clarify with the user.'}\n"
            f"Notes: {project.notes or 'none'}\n\n"
            "Study the project, propose the next concrete step and complete it."
        )
    return (
        f"Продолжи работу над проектом «{project.name}».\n\n"
        f"Главная цель: {project.goal or 'уточни у пользователя.'}\n"
        f"Заметки: {project.notes or 'нет'}\n\n"
        "Изучи проект, предложи следующий конкретный шаг и выполни его."
    )


SKILLS: dict[str, str] = {
    "engine-basics.md": r"""# Skill: Reasonable Engine basics

- Runtime: `from reasonable.runtime import *`; pygame-compatible, no Qt.
- `Game` + `Scene` for games; `UIApp` + widgets for apps.
- All resources via absolute path from `Path(__file__).parent / "assets"`.
- The splash starts automatically; do not draw your own instead of it.
- `F11` — fullscreen; touches arrive as mouse events in the UI.
- Verify: `python main.py`, then `re.bat validate`.
- Never edit `_engine/`; refresh it with `re.bat sync-engine`.

Scene template:
```python
class Play(Scene):
    def __init__(self, game):
        super().__init__(game, gradient=((8,12,22),(22,34,54)), camera_pos=(640,360))
    def update(self, dt):
        super().update(dt)
    def draw_background(self, surface):
        surface.fill((10, 15, 26))
```
""",
    "game-development.md": r"""# Skill: game development

1. Define the core loop: goal → action → feedback → reward.
2. Build a vertical slice first: player, controls, one mechanic, one enemy/goal,
   HUD, pause, game over, restart. Content comes after.
3. Controls: keyboard + mouse; on Android — `VirtualJoystick` and `TouchButton`.
4. Feedback: particles (`scene.burst`), camera shake, flashes, sound, smooth
   tweens, damage popups.
5. HUD: score, health, hints; readable contrast, safe margins 24–40 px.
6. Persistence: `SaveData("Name", "save.json")` — high score/progress.
7. Verify: headless run, zero console errors, 60 FPS at 1280x720.
8. Leave no dead buttons and no empty screens.

Structure: `main.py` (entry), `scenes/`, `entities/`, `ui/`, `data/`.
A tiny game may live in one file, but it must stay readable.
""",
    "app-development.md": r"""# Skill: beautiful applications

- `UIApp` + `Panel/VStack/HStack/ScrollView`. Dark theme, large headings,
  one accent color, calm spacing 16/24/32.
- Mandatory states: empty list, loading, error, success.
- Navigation: sidebar or tabs; the active item must be obvious.
- Persist data in `data.json` next to the project (atomically, tmp+replace).
- AI: `AIChatPanel` for chat or `AIClient` for one-off requests. Add a
  task-specific system prompt; never send secrets.
- Test narrow windows: hide secondary panels, prevent text overlap. On Android
  rely entirely on touch.
- Animation: hover, press, panel reveals; no layout jitter.
""",
    "sprites-and-assets.md": r"""# Skill: sprites and assets

Tools (built-in agent) or CLI (external agent):

```bat
re.bat sprite "green slime enemy, cute" assets/sprites/slime.png --style flat --size 256
re.bat bg "neon city at night" assets/background.png --width 1280 --height 720
```

Rules:
- One object per sprite, strong silhouette, transparent background (the tool
  removes chromakey and trims margins).
- One consistent style: pick `flat`, `pixel`, `painterly` or `icon` and stick to it.
- Names: `player.png`, `enemy_slime.png`, `star.png`, `bg_forest.png`.
- For UI use engine icons (`draw_icon`) and vector shapes; do not generate
  icons as text.
- Inspect results visually (open the PNG). If the object is cropped or the
  background remains — retry with a more precise prompt.
- Backgrounds: wide, no text, with depth; must not hurt HUD readability.
""",
    "progress-and-handoff.md": r"""# Skill: progress and handoff

The Reasonable Engine editor reads project files live:

- `progress/state.json` — status, percent, stage, tasks;
- `progress/events.jsonl` — event feed.

Write only through the CLI so the JSON never breaks:

```bat
re.bat plan "Menu" "Game loop" "Polish"
re.bat task t1 in_progress
re.bat progress 35 "Building the game loop"
re.bat event "Settings screen added"
re.bat task t1 done
re.bat done "Project is ready to run"
re.bat validate
```

Rules:
- Update progress before long stretches of work and after every stage.
- Never report 100% until `re.bat validate` passes and the project launches.
- If another agent continues the work, leave notes in `AGENT_TASKS.md`:
  what is done, what is next, which files must not be touched.
- Do not edit `state.json` by hand.
""",
    "android-and-export.md": r"""# Skill: Android and export

- Android builds use pygame-ce + python-for-android/buildozer.
- Buildozer does not work on Windows: you need Linux/WSL or GitHub Actions.
- In the editor: **File → Export → Android package**. It produces a ZIP with
  `buildozer.spec`, `main.py`, assets and instructions.
- Required in-game: touch controls (joystick/buttons), safe margins, portrait or
  landscape orientation from `project.json`, no right-click or keyboard reliance.
- Avoid Windows paths, `os.startfile`, `winreg`, subprocesses and heavy imports
  at runtime.
- Text must fit narrow screens; test both 720x1280 and 1280x720.
- Windows export: **File → Export → Windows folder** (self-contained folder with
  the runtime and a `.bat`), optionally a PyInstaller `.exe`.
""",
    "ui-simple-tkinter.md": r"""# Skill: simple interface (tkinter)

The "Simple" level — ordinary Windows desktop programs: utilities, forms,
lists, settings. Standard tkinter only, tidy look, dark engine theme with the
`#D97757` accent.

When to choose it:
- utilities and workhorses: converters, schedulers, control panels;
- forms with fields, tables and buttons;
- programs where speed and simplicity matter more than game graphics.

Rules:
- The Reasonable Engine splash plays before the tkinter window opens (the
  `simple` template already does this) — keep it, do not draw your own.
- Window: do not hard-lock `geometry` without need; set a sensible size and
  `minsize`. Window title = project name.
- Styling: `ttk.Style` with a dark theme; large buttons, 10–16 px padding,
  readable fonts (`Segoe UI`, size 10–12).
- Data: `data.json` next to the project, atomic writes (tmp + replace).
- Every action must really work: add, edit, delete, save. No stubs.
- Do not mix pygame rendering into a tkinter window or vice versa.

Skeleton:
```python
import json, tkinter as tk
from tkinter import ttk
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
DATA = PROJECT_DIR / "data.json"

class App(tk.Tk):
    def __init__(self, title: str):
        super().__init__()
        self.title(title)
        self.geometry("760x520")
        self.minsize(560, 380)
        self.configure(bg="#101216")
        header = ttk.Label(self, text=title, font=("Segoe UI", 14, "bold"))
        header.pack(padx=16, pady=(14, 6), anchor="w")
        # list, add-form, buttons — assemble them for the project's task
```
""",
    "ui-standard-widgets.md": r"""# Skill: standard interface (engine widgets)

The "Standard" level — the ready-made Reasonable Engine UI kit: dark theme,
widgets, scrolling, tabs. The default choice for apps and game menus.

Use:
```python
from reasonable.runtime import (
    UIApp, Panel, VStack, HStack, Grid, Label, Button, IconButton, Entry,
    Toggle, Slider, ProgressBar, ScrollView, Tabs, ImageWidget, Badge, Card,
)

class App(UIApp):
    def build_ui(self):
        root = Panel(padding=24, spacing=16)
        root.add(Label("Heading", size=28, bold=True))
        row = HStack(spacing=12)
        self.input = Entry("Enter a value", on_submit=self.apply)
        row.add(self.input, Button("Apply", self.apply, height=46))
        root.add(row)
        self.list_view = ScrollView(VStack(spacing=8), expand_y=True)
        root.add(self.list_view)
        return root
```

Rules:
- One accent color; panels `Panel(panel_alt=...)`; radii come from `Theme`.
- Lists — `ScrollView` + row widgets; rows have a title, secondary text and an
  action. An empty state is mandatory ("Nothing here yet").
- Buttons: `variant="primary"` for the main action, `secondary`/`ghost` for the
  rest; `danger` for deletion.
- Input: `Entry(on_submit=...)` plus a button; do not rely on Enter alone.
- Never access `event.pos` on mouse-wheel events — the engine guards it, but do
  not write such code yourself; subclass `Widget.handle_event` and use only
  attributes guaranteed to exist on that event type.
- Save data atomically into `data.json`; the AI assistant goes into `AIChatPanel`.
""",
    "ui-advanced-scenes.md": r"""# Skill: advanced interface (scenes and graphics)

The "Advanced" level — custom graphics and game rendering: scenes, camera,
particles, tweens, custom widgets. The choice for games and visually rich apps.

Tools:
- `Game` + `Scene`: menu/game/pause screens; `game.set_scene`, `push_scene`.
- Camera: `scene.camera.pos/zoom/target/smooth/bounds`, `shake(force, time)`.
- Effects: `scene.burst(...)`, `ParticleSystem`, `TweenManager`, `draw_glow`,
  `draw_gradient`, `draw_rounded_rect`, `draw_wrapped_text`.
- Nodes: `Sprite`, `AnimatedSprite`, `Text`, `Shape`; `node.tween(...)`.
- Input: `game.input`, `VirtualJoystick`, `TouchButton` for touch.
- Saves: `SaveData("Name", "save.json")`.

Rules:
- Draw the HUD above the scene: contrast, safe margins 24–40 px, font size ≥ 16.
- Cache static Surfaces; never create a Surface every frame.
- Animate via tweens/particles, not blinking; 60 FPS at 1280×720.
- Screens: menu → game → pause → lose/win → restart; everything works.
- Recipes for complex screens live in the `game` template.
""",
}


EXTERNAL_CONNECTION_GUIDE = """# Connecting an external AI agent

1. Open the project folder in your AI agent (Claude Code, Codex CLI, Cursor,
   Cline, Windsurf, Aider…).
2. Paste the ready prompt from the "AI agent" panel in Reasonable Engine.
3. Watch the progress in the same panel — the agent updates it itself via `re.bat`.

Everything else (instructions, skills, engine API) the agent reads from the
project files: `AGENT_GUIDE.md`, `skills/`, `AGENTS.md`, `CLAUDE.md`.
"""


# ---------------------------------------------------------------------------
# External-agent documents (English-only, like every other agent material).
# ---------------------------------------------------------------------------

UI_LEVEL_LABELS_EN = {
    "simple": "simple (tkinter)",
    "standard": "standard (engine widgets)",
    "advanced": "advanced (scenes and graphics)",
}


EXTERNAL_GUIDE_TEMPLATE = r"""# AGENT_GUIDE — {name}

> Full instructions for an external AI agent. Read it completely before your
> first edit. The project was created in **Reasonable Engine {version}**;
> mode: {mode} agent.

## 1. What this project is

- **Name:** {name}
- **Type:** {kind}
- **Platform:** {platform}
- **Interface level:** {levels} — the matching skills are already in `skills/`
{conversion_note}
- **Main goal:** {goal}
- **Window:** size and mode are the agent's choice per task; the user never
  sees these settings. Baseline: a resizable 1280x720 window, F11 for
  fullscreen.
- **Entry point:** `{entry}`
- **Folder:** `{root}`

User notes:

```
{notes}
```

## 2. Your role

You are an autonomous developer. Bring the project to a state where it runs,
looks coherent and fully fulfils the goal. Do not limit yourself to advice and
code fragments: change files, create assets, verify the result.

Without this engine the project cannot be made as good: widgets, splash,
camera, particles, saves, asset generation and launch validation are built in.
Use them (`reasonable.runtime`, `skills/`) instead of hand-rolled analogues.

## 3. Mandatory work cycle

1. **Study:** `project.json`, this file, `progress/state.json`, `main.py`,
   `assets/`, `skills/`. Do not start writing code until you understand the
   current state.
2. **Plan:** `re.bat plan "..." "..."` (or `re.sh`). Tasks must be concrete and
   verifiable.
3. **Track statuses:** `re.bat task t1 in_progress`, then `done` after checking.
4. **Write code in small stages.** After each stage run the project:
   `python main.py` (or the headless check below).
5. **Verify:** `re.bat validate`; fix errors until there are none.
6. **Report progress:** `re.bat progress 45 "Game loop ready"` and
   `re.bat event "Pause screen added"`. The editor shows this to the user.
7. **Finish:** `re.bat done "What was done, how to run"` only after a
   successful check.

Headless check (Windows PowerShell / cmd):

```bat
set SDL_VIDEODRIVER=dummy
set SDL_AUDIODRIVER=dummy
set RE_FRAMES=5
python main.py
```

(The splash ends instantly by itself during headless runs.)

## 4. Rules

- Work only inside the project folder. Do not modify `_engine/`,
  `progress/*.json` by hand or system files.
- Do not delete `project.json`, `assets/` or the entry point without need.
- No PySide6/PyQt; the project must run on pygame.
- Never commit or hardcode secrets and API keys. The user key lives outside the
  project; local models work without a key.
- Leave no `TODO`, stubs, dead buttons or broken imports.
- Keep the existing code style; comments only where they earn their place, in
  Russian or English.
- For large files make targeted edits; do not overwrite someone else's work.

## 5. Tools

### Project CLI

```bat
re.bat status
re.bat events
re.bat plan "Task 1" "Task 2"
re.bat task t1 in_progress
re.bat task t1 done
re.bat progress 40 "Stage"
re.bat event "Message"
re.bat validate
re.bat run
re.bat sprite "green slime, cute" assets/sprites/slime.png --style flat --size 256
re.bat bg "neon city" assets/background.png --width 1280 --height 720
re.bat export windows
re.bat export android
re.bat sync-engine
re.bat done "Summary"
```

### Built-in agent (when the user works in the editor)

It can read/write files, run commands, generate sprites and backgrounds, and
change the plan and progress. It will see your file changes; do not run
destructive operations at the same time as it does.

### Sprite generation

Always generate assets into `assets/`. Styles: `flat`, `pixel`, `painterly`,
`icon`. One object per image, transparent background, strong silhouette.
Verify PNGs visually or by size/alpha. Never embed base64 images in code.

## 6. Skills

Read the relevant files before working:

{skills}

## 7. Architecture and quality

- Game: `Game` + `Scene`, input, HUD, pause, lose/win, restart, saving,
  particles/animations, touch support.
- App: `UIApp` + widgets, navigation, empty states, data persistence, adaptive
  layout, genuinely useful AI assistant.
- The Reasonable Engine splash is already built in — do not replace it.
- All asset paths resolve from `Path(__file__).resolve().parent`, not cwd.
- Target platforms: Windows and Android. Check narrow screens and touches.
- Performance: 60 FPS at 1280x720; avoid creating a Surface every frame without
  a cache; cap particle counts.

## 8. Engine API

{api_guide}

## 9. Handing off work

Before finishing, update `AGENT_TASKS.md`: what is done, what remains, which
files matter. Then:

```bat
re.bat validate
re.bat done "Short summary for the user"
```

If another agent continues, it will read `AGENT_GUIDE.md`,
`progress/state.json` and `AGENT_TASKS.md`.
"""


AGENT_TASKS_TEMPLATE = """# AGENT_TASKS — {name}

Updated manually or by the agent. Machine progress: `progress/state.json`.
Commands: `re.bat status`, `re.bat plan ...`, `re.bat task ...`.

## Current plan

{plan_rows}

## Log

- {created_at}: project created in Reasonable Engine.

## Notes for the next agent

- What is done:
- What is next:
- Files that must not break: `main.py`, `project.json`, `assets/`.
"""


SHORT_AGENT_TEMPLATE = """# {name} — instructions for AI agents

This project was created in **Reasonable Engine**. Before your first edit,
read `AGENT_GUIDE.md` completely, then `progress/state.json` and the files in
`skills/`.

In short:

- Runtime: `reasonable.runtime` (pygame), not PySide6.
- Entry point: `main.py`; assets: `assets/`.
- Plan and progress: `re.bat plan/task/progress/event`; checks: `re.bat validate`.
- Write complete working code, generate sprites into `assets/`, never touch
  `_engine/`.
- Reply to the user in the language of their task (Russian task -> Russian
  reply, English task -> English reply); all engine docs here are English-only.
- Finish only after a successful run and `re.bat done "..."`.

Full rules, engine API and skills: [AGENT_GUIDE.md](AGENT_GUIDE.md).
"""


EXTERNAL_README_TEMPLATE = """# External agent . {name}

1. Open the project folder in Claude Code / Codex / Cursor / Cline / Windsurf.
2. Write the first task in the "AI agent" section and copy the ready prompt:

   > Read AGENT_GUIDE.md and skills/. Study project.json and
   > progress/state.json. Complete the first task, updating progress via
   > re.bat. Bring the project to a runnable state and pass re.bat validate.
   > Always answer the user in the language of their task.

3. Watch the "AI agent" section in Reasonable Engine - it updates
   automatically. The "Check", "Run" and "Export" buttons always work.

CLI: `re.bat status`, `re.bat plan ...`, `re.bat progress 30 "..."`,
`re.bat validate`, `re.bat sprite ...`, `re.bat export ...`.

Full instructions: `AGENT_GUIDE.md` and `EXTERNAL_AGENT.md`.
"""
