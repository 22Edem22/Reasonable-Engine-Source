"""Load editor scenes (``scenes/*.json``) in the pygame runtime.

The scene editor writes plain JSON, so a game can spawn the same objects the
designer placed in the viewport::

    from reasonable.runtime import add_scene_objects

    class Level(Scene):
        def on_enter(self):
            add_scene_objects(self, "scenes/main.json")

Only pygame and the standard library are used, so this module works in
exported Windows and Android builds.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import pygame

from .graphics import Shape, Sprite, Text
from .utils import color


def load_scene_data(path: str | Path) -> dict[str, Any]:
    """Read a scene JSON file and return a safe dictionary."""
    target = Path(path)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": 1, "size": [960, 540], "objects": []}
    if not isinstance(data, dict):
        return {"version": 1, "size": [960, 540], "objects": []}
    if not isinstance(data.get("objects"), list):
        data["objects"] = []
    return data


def scene_background(data: dict[str, Any], default=(10, 13, 18)):
    value = data.get("background")
    if isinstance(value, str):
        try:
            return color(value)
        except (ValueError, TypeError):
            pass
    return default


def build_scene_objects(
    data: dict[str, Any],
    *,
    base_dir: str | Path | None = None,
) -> list[Any]:
    """Turn scene records into runtime nodes, ordered by layer."""
    base = Path(base_dir) if base_dir is not None else Path(".")
    nodes: list[Any] = []
    for record in data.get("objects") or []:
        if not isinstance(record, dict):
            continue
        kind = str(record.get("kind") or "rect")
        x = _number(record.get("x"), 0.0)
        y = _number(record.get("y"), 0.0)
        width = max(1.0, _number(record.get("w"), 64.0))
        height = max(1.0, _number(record.get("h"), 64.0))
        rotation = _number(record.get("rotation"), 0.0)
        fill = _color(record.get("color"), (217, 119, 87))
        z = int(_number(record.get("z"), 0))
        node = None

        if kind == "image":
            asset = str(record.get("asset") or "")
            if asset:
                path = Path(asset)
                if not path.is_absolute():
                    path = base / path
                if path.is_file():
                    try:
                        source = pygame.image.load(str(path))
                    except pygame.error:
                        source = None
                    if source is not None:
                        scale_x = width / max(1, source.get_width())
                        scale_y = height / max(1, source.get_height())
                        node = Sprite(source, anchor=(0.0, 0.0), angle=rotation, z=z)
                        node.x = x
                        node.y = y
                        node.scale.update(scale_x, scale_y)
        elif kind == "text":
            size = max(8, int(height * 0.62))
            node = Text(
                str(record.get("text") or record.get("name") or ""),
                x,
                y,
                size=size,
                color_value=fill,
                anchor="topleft",
                z=z,
            )
        else:
            node = Shape(
                "circle" if kind == "circle" else "rect",
                x + width / 2,
                y + height / 2,
                size=(width, height),
                fill=fill,
                z=z,
                radius=int(_number(record.get("radius"), 0)) if kind == "panel" else 0,
            )

        if node is not None:
            node.name = str(record.get("name") or "")
            node.visible = bool(record.get("visible", True))
            nodes.append(node)

    nodes.sort(key=lambda item: getattr(item, "z", 0))
    return nodes


def add_scene_objects(scene, source, *, base_dir: str | Path | None = None) -> list[Any]:
    """Add every object from a scene file (or dict) to a ``Scene``."""
    if isinstance(source, dict):
        data = source
    else:
        data = load_scene_data(source)
        if base_dir is None:
            base_dir = Path(source).resolve().parent.parent
    nodes = build_scene_objects(data, base_dir=base_dir)
    if nodes:
        scene.add(*nodes)
    return nodes


def _number(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _color(value, default: Iterable[int]):
    try:
        return color(value)
    except (ValueError, TypeError):
        return color(default)
