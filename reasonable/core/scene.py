"""Project scene documents used by the visual scene editor.

A scene is a plain JSON file under ``scenes/`` in the project, so both the
editor and the pygame runtime can read it without any hidden state::

    scenes/main.json
    {
      "version": 1,
      "name": "main",
      "size": [1280, 720],
      "background": "#141821",
      "grid": 32,
      "objects": [
        {"id": "obj-1", "name": "Player", "kind": "rect",
         "x": 120, "y": 260, "w": 48, "h": 64, "rotation": 0,
         "z": 0, "color": "#D97757", "visible": true}
      ]
    }

Supported object kinds: ``rect``, ``circle``, ``text`` and ``image``.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Iterable

from .i18n import tr
from .paths import atomic_write_json, read_json, slugify

SCENE_DIR = "scenes"
DEFAULT_SCENE = "main"
SCENE_SUFFIX = ".json"

OBJECT_KINDS = ("rect", "circle", "text", "image", "panel")
SCENE_TEMPLATES = ("empty", "level", "menu", "app")
DEFAULT_SIZE = (960, 540)
GRID_STEP = 32
PALETTE = (
    "#D97757",
    "#7FA3C7",
    "#8DB8A0",
    "#C9AD73",
    "#B08BC4",
    "#D7DBE0",
)


def scene_dir(project_root: Path) -> Path:
    return Path(project_root) / SCENE_DIR


def scene_path(project_root: Path, name: str = DEFAULT_SCENE) -> Path:
    safe = "".join(char for char in str(name or DEFAULT_SCENE) if char.isalnum() or char in "-_") or DEFAULT_SCENE
    return scene_dir(project_root) / f"{safe}{SCENE_SUFFIX}"


def new_scene(size: Iterable[int] = DEFAULT_SIZE, name: str = DEFAULT_SCENE) -> dict[str, Any]:
    width, height = _size(size, DEFAULT_SIZE)
    return {
        "version": 1,
        "name": str(name or DEFAULT_SCENE),
        "size": [width, height],
        "background": "#141821",
        "grid": GRID_STEP,
        "objects": [],
    }


def new_object(
    kind: str = "rect",
    *,
    index: int = 1,
    x: float = 0,
    y: float = 0,
    w: float = 64,
    h: float = 64,
    color: str | None = None,
    text: str = "",
    asset: str = "",
    name: str | None = None,
    z: int = 0,
) -> dict[str, Any]:
    kind = kind if kind in OBJECT_KINDS else "rect"
    default_name = name or tr("Object {index}", "Объект {index}", index=index)
    obj = {
        "id": f"obj-{uuid.uuid4().hex[:10]}",
        "name": str(default_name),
        "kind": kind,
        "x": float(x),
        "y": float(y),
        "w": float(w),
        "h": float(h),
        "rotation": 0.0,
        "z": int(z),
        "color": color or PALETTE[(max(1, index) - 1) % len(PALETTE)],
        "visible": True,
    }
    if kind == "panel":
        obj["radius"] = 14.0
    if kind == "text":
        obj["text"] = str(text or default_name)
        obj["w"] = max(80.0, float(w))
        obj["h"] = max(24.0, float(h))
    if kind == "image":
        obj["asset"] = str(asset or "")
    return obj


def normalize_scene(data: Any, *, size: Iterable[int] = DEFAULT_SIZE, name: str = DEFAULT_SCENE) -> dict[str, Any]:
    """Return a valid scene even if the file on disk is partial or damaged."""
    scene = new_scene(size, name)
    if not isinstance(data, dict):
        return scene
    scene["name"] = str(data.get("name") or scene["name"])
    scene["size"] = list(_size(data.get("size"), scene["size"]))
    template = str(data.get("template") or "")
    if template in SCENE_TEMPLATES:
        scene["template"] = template
    background = data.get("background")
    if isinstance(background, str) and background.strip():
        scene["background"] = background.strip()
    try:
        grid = int(data.get("grid") or GRID_STEP)
    except (TypeError, ValueError):
        grid = GRID_STEP
    scene["grid"] = max(4, min(256, grid))

    objects: list[dict[str, Any]] = []
    raw_objects = data.get("objects")
    if isinstance(raw_objects, list):
        for index, raw in enumerate(raw_objects, start=1):
            if not isinstance(raw, dict):
                continue
            kind = str(raw.get("kind") or "rect")
            kind = kind if kind in OBJECT_KINDS else "rect"
            obj = new_object(
                kind,
                index=index,
                name=str(raw.get("name") or ""),
                x=_number(raw.get("x"), 0),
                y=_number(raw.get("y"), 0),
                w=max(1.0, _number(raw.get("w"), 64)),
                h=max(1.0, _number(raw.get("h"), 64)),
                color=str(raw.get("color") or PALETTE[(index - 1) % len(PALETTE)]),
                text=str(raw.get("text") or ""),
                asset=str(raw.get("asset") or ""),
                z=int(_number(raw.get("z"), 0)),
            )
            obj["id"] = str(raw.get("id") or obj["id"])
            obj["rotation"] = _number(raw.get("rotation"), 0)
            obj["visible"] = bool(raw.get("visible", True))
            if "radius" in raw:
                obj["radius"] = max(0.0, _number(raw.get("radius"), 0))
            if raw.get("marker"):
                obj["marker"] = True
                role = str(raw.get("role") or "").strip().lower()
                if role:
                    obj["role"] = role
            objects.append(obj)
    scene["objects"] = objects
    return scene


def load_scene(project_root: Path, name: str = DEFAULT_SCENE, *, size: Iterable[int] = DEFAULT_SIZE) -> dict[str, Any]:
    """Load a scene by file id, preserving the human title stored inside."""
    path = scene_path(project_root, name)
    raw = read_json(path, None)
    title = str((raw or {}).get("name") or name) if isinstance(raw, dict) else str(name)
    return normalize_scene(raw, size=size, name=title)


def save_scene(project_root: Path, scene: dict[str, Any], name: str | None = None) -> Path:
    """Save a scene.

    ``name`` is the file id (``level-1``). The display title is kept in the
    ``name`` field of the JSON so files can have readable names independent of
    their slug.
    """
    display = str(scene.get("name") or name or DEFAULT_SCENE).strip() or DEFAULT_SCENE
    data = normalize_scene(scene, name=display)
    path = scene_path(project_root, str(name or display))
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, data)
    return path


def scene_id(title: str) -> str:
    """Stable, filesystem-safe id for a scene title."""
    value = slugify(str(title or ""), "scene")
    return value[:48] or "scene"


def list_scenes(project_root: Path) -> list[dict[str, str]]:
    """All scenes in the project, with their display titles."""
    directory = scene_dir(project_root)
    rows: list[dict[str, str]] = []
    try:
        paths = sorted(directory.glob(f"*{SCENE_SUFFIX}"))
    except OSError:
        paths = []
    for path in paths:
        raw = read_json(path, {})
        title = str((raw or {}).get("name") or path.stem) if isinstance(raw, dict) else path.stem
        rows.append({"id": path.stem, "title": title})
    rows.sort(key=lambda row: (row["id"] != DEFAULT_SCENE, row["title"].lower()))
    return rows


def _unique_scene_id(project_root: Path, title: str) -> str:
    base = scene_id(title)
    candidate = base
    index = 2
    while scene_path(project_root, candidate).exists():
        candidate = f"{base}-{index}"
        index += 1
    return candidate


def template_objects(template: str, size: Iterable[int]) -> list[dict[str, Any]]:
    """Starter object sets that read well in both the editor and the game."""
    width, height = _size(size, DEFAULT_SIZE)
    template = template if template in SCENE_TEMPLATES else "empty"
    if template == "menu":
        return [
            new_object(
                "text",
                index=1,
                name="Game title",
                x=width * 0.18,
                y=height * 0.28,
                w=width * 0.64,
                h=72,
                color="#F0F2F5",
                text=tr("YOUR GAME", "ВАША ИГРА"),
            ),
            new_object(
                "text",
                index=2,
                name="Menu hint",
                x=width * 0.26,
                y=height * 0.44,
                w=width * 0.48,
                h=30,
                color="#9AA1AB",
                text=tr("Press Play to start", "Нажмите «Играть», чтобы начать"),
            ),
        ]
    if template == "app":
        if height > width:
            # Portrait/mobile layout: no side panels, full-width cards.
            objects = [
                new_object("rect", index=1, name=tr("Background", "Фон"), x=0, y=0, w=width, h=height, color="#0F1117", z=-40),
                new_object("text", index=2, name=tr("App title", "Название приложения"), x=24, y=28, w=width - 48, h=40, color="#F0F2F5", text=tr("MY APP", "МОЁ ПРИЛОЖЕНИЕ")),
                new_object("text", index=3, name=tr("Page title", "Заголовок страницы"), x=24, y=92, w=width - 48, h=38, color="#F0F2F5", text=tr("Plan for today", "План на сегодня")),
                new_object("panel", index=4, name=tr("Progress card", "Карточка прогресса"), x=24, y=150, w=width - 48, h=76, color="#1C202A", z=-5),
                new_object("text", index=5, name=tr("Progress label", "Прогресс"), x=42, y=170, w=width - 84, h=24, color="#9AA1AB", text=tr("PROGRESS", "ПРОГРЕСС")),
            ]
            for index in range(1, 5):
                objects.append(
                    new_object(
                        "panel",
                        index=5 + index,
                        name=tr("Task card {index}", "Карточка задачи {index}", index=index),
                        x=24,
                        y=248 + (index - 1) * 92,
                        w=width - 48,
                        h=76,
                        color="#1B1F28",
                        z=-5,
                    )
                )
                objects.append(
                    new_object(
                        "text",
                        index=9 + index,
                        name=tr("Task title {index}", "Заголовок задачи {index}", index=index),
                        x=46,
                        y=266 + (index - 1) * 92,
                        w=width - 92,
                        h=26,
                        color="#D7DBE0",
                        text=tr("Task {index}", "Задача {index}", index=index),
                    )
                )
            objects.append(
                new_object("panel", index=15, name=tr("Input field", "Поле ввода"), x=24, y=height - 100, w=width - 120, h=48, color="#20242D", z=-5)
            )
            objects.append(
                new_object("text", index=16, name=tr("Assistant button", "Кнопка помощника"), x=width - 80, y=height - 98, w=52, h=44, color="#D97757", text="+", z=-4)
            )
            return objects
        sidebar = min(280, width * 0.24)
        right = min(360, width * 0.28)
        card_x = sidebar + 28
        card_w = max(240, width - sidebar - right - 56)
        objects = [
            new_object("rect", index=1, name=tr("Background", "Фон"), x=0, y=0, w=width, h=height, color="#0F1117", z=-40),
            new_object("panel", index=2, name=tr("Sidebar", "Боковая панель"), x=0, y=0, w=sidebar, h=height, color="#151821", z=-30),
            new_object("text", index=3, name=tr("App title", "Название приложения"), x=28, y=28, w=sidebar - 56, h=30, color="#F0F2F5", text=tr("MY APP", "МОЁ ПРИЛОЖЕНИЕ")),
            new_object("text", index=4, name=tr("Today", "Сегодня"), x=28, y=86, w=sidebar - 56, h=24, color="#D97757", text=tr("Today", "Сегодня")),
            new_object("text", index=5, name=tr("All tasks", "Все задачи"), x=28, y=122, w=sidebar - 56, h=24, color="#9AA1AB", text=tr("All tasks", "Все задачи")),
            new_object("text", index=6, name=tr("Statistics", "Статистика"), x=28, y=158, w=sidebar - 56, h=24, color="#9AA1AB", text=tr("Statistics", "Статистика")),
            new_object("panel", index=7, name=tr("Progress card", "Карточка прогресса"), x=22, y=height - 150, w=sidebar - 44, h=96, color="#1C202A", z=-10),
            new_object("text", index=8, name=tr("Progress label", "Прогресс"), x=38, y=height - 134, w=sidebar - 76, h=22, color="#9AA1AB", text=tr("PROGRESS", "ПРОГРЕСС")),
            new_object("text", index=9, name=tr("Page title", "Заголовок страницы"), x=card_x, y=30, w=card_w, h=44, color="#F0F2F5", text=tr("Plan for today", "План на сегодня")),
            new_object("text", index=10, name=tr("Page subtitle", "Подзаголовок"), x=card_x, y=78, w=card_w, h=24, color="#9AA1AB", text=tr("What needs to be done?", "Что нужно сделать?")),
        ]
        for index in range(1, 4):
            objects.append(
                new_object(
                    "panel",
                    index=10 + index,
                    name=tr("Task card {index}", "Карточка задачи {index}", index=index),
                    x=card_x,
                    y=112 + (index - 1) * 86,
                    w=card_w,
                    h=72,
                    color="#1B1F28",
                    z=-5,
                )
            )
            objects.append(
                new_object(
                    "text",
                    index=13 + index,
                    name=tr("Task title {index}", "Заголовок задачи {index}", index=index),
                    x=card_x + 22,
                    y=126 + (index - 1) * 86,
                    w=card_w - 44,
                    h=26,
                    color="#D7DBE0",
                    text=tr("Task {index}", "Задача {index}", index=index),
                )
            )
        objects.append(
            new_object("panel", index=20, name=tr("Assistant panel", "Панель помощника"), x=width - right, y=0, w=right, h=height, color="#13161D", z=-30)
        )
        objects.append(
            new_object("text", index=21, name=tr("Assistant title", "Помощник"), x=width - right + 24, y=28, w=right - 48, h=30, color="#F0F2F5", text=tr("Assistant", "Помощник")),
        )
        objects.append(
            new_object("panel", index=22, name=tr("Input field", "Поле ввода"), x=width - right + 24, y=height - 74, w=right - 48, h=46, color="#20242D", z=-5),
        )
        return objects
    if template != "level":
        return []

    objects = [
        new_object(
            "circle",
            index=1,
            name=tr("Planet left", "Планета слева"),
            x=width * 0.06,
            y=height * 0.18,
            w=180,
            h=180,
            color="#1B2635",
            z=-30,
        ),
        new_object(
            "circle",
            index=2,
            name=tr("Planet right", "Планета справа"),
            x=width * 0.78,
            y=height * 0.58,
            w=140,
            h=140,
            color="#242030",
            z=-30,
        ),
        new_object(
            "circle",
            index=3,
            name=tr("Moon", "Луна"),
            x=width * 0.82,
            y=height * 0.10,
            w=88,
            h=88,
            color="#C9AD73",
            z=-20,
        ),
    ]
    # Hidden markers are read by the sample game. They stay faintly visible in
    # the editor so a level can be laid out without cluttering the game.
    star_names = [tr("Star {index}", "Звезда {index}", index=index) for index in range(1, 7)]
    markers = [
        ("player", tr("Player start", "Старт игрока"), width * 0.5 - 28, height * 0.72 - 28, 56, 56),
        ("star", star_names[0], width * 0.18, height * 0.30, 32, 32),
        ("star", star_names[1], width * 0.36, height * 0.22, 32, 32),
        ("star", star_names[2], width * 0.58, height * 0.20, 32, 32),
        ("star", star_names[3], width * 0.78, height * 0.32, 32, 32),
        ("star", star_names[4], width * 0.30, height * 0.56, 32, 32),
        ("star", star_names[5], width * 0.66, height * 0.58, 32, 32),
        ("slime", tr("Slime {index}", "Слизень {index}", index=1), width * 0.12, height * 0.44, 44, 44),
        ("slime", tr("Slime {index}", "Слизень {index}", index=2), width * 0.86, height * 0.64, 44, 44),
    ]
    for index, (role, name, x, y, w, h) in enumerate(markers, start=4):
        marker = new_object(
            "rect",
            index=index,
            name=name,
            x=x,
            y=y,
            w=w,
            h=h,
            color="#7FA3C7",
            z=40,
        )
        marker["visible"] = False
        marker["marker"] = True
        marker["role"] = role
        objects.append(marker)
    return objects


def create_scene(
    project_root: Path,
    title: str,
    *,
    size: Iterable[int] = DEFAULT_SIZE,
    template: str = "empty",
    identifier: str | None = None,
) -> dict[str, Any]:
    """Create and save a new scene, returning its summary and document."""
    display = str(title or "").strip() or tr("New scene", "Новая сцена")
    scene = new_scene(size, display)
    scene["template"] = template if template in SCENE_TEMPLATES else "empty"
    scene["objects"] = template_objects(scene["template"], scene["size"])
    scene_id_value = str(identifier or "").strip()
    if scene_id_value and not scene_path(project_root, scene_id_value).exists():
        identifier = scene_id_value
    else:
        identifier = _unique_scene_id(project_root, display)
    save_scene(project_root, scene, identifier)
    return {"id": identifier, "title": display, "scene": scene}


def duplicate_scene(project_root: Path, name: str, title: str = "") -> dict[str, Any] | None:
    if not scene_exists(project_root, name):
        return None
    scene = load_scene(project_root, name)
    display = str(title or "").strip() or f"{scene.get('name') or name} (copy)"
    scene["name"] = display
    identifier = _unique_scene_id(project_root, display)
    save_scene(project_root, scene, identifier)
    return {"id": identifier, "title": display, "scene": scene}


def rename_scene(project_root: Path, name: str, title: str) -> bool:
    if not scene_exists(project_root, name):
        return False
    scene = load_scene(project_root, name)
    display = str(title or "").strip()
    if not display:
        return False
    scene["name"] = display
    save_scene(project_root, scene, name)
    return True


def delete_scene(project_root: Path, name: str) -> bool:
    path = scene_path(project_root, name)
    try:
        path.unlink()
        return True
    except OSError:
        return False


def ensure_scene(
    project_root: Path,
    *,
    project_type: str = "game",
    size: Iterable[int] = DEFAULT_SIZE,
    template: str | None = None,
) -> dict[str, Any]:
    """Make sure a project has at least one scene, creating a sensible starter."""
    scenes = list_scenes(project_root)
    if scenes:
        return scenes[0]
    if template is None:
        template = "level" if project_type == "game" else "empty"
    title = tr("Main scene", "Главная сцена")
    created = create_scene(
        project_root,
        title,
        size=size,
        template=template,
        identifier=DEFAULT_SCENE,
    )
    return {"id": created["id"], "title": created["title"]}


def scene_exists(project_root: Path, name: str = DEFAULT_SCENE) -> bool:
    return scene_path(project_root, name).is_file()


def next_index(scene: dict[str, Any]) -> int:
    return len(scene.get("objects") or []) + 1


def _number(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _size(value: Any, default: Iterable[int]) -> tuple[int, int]:
    try:
        width, height = int(value[0]), int(value[1])
    except (TypeError, ValueError, IndexError, KeyError):
        width, height = int(default[0]), int(default[1])
    return max(160, width), max(120, height)
