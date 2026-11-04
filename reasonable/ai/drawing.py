"""Draw sprites from a model-authored description.

This module never guesses what a sprite should look like. The model supplies a
pixel grid or a list of primitives in a 0..100 coordinate space; the renderer
only validates the description, draws it with supersampling, trims transparent
margins and saves a PNG.

Model-facing conventions (mirrored in the ``draw_sprite`` tool schema):

* pixel mode: ``pixels`` (rows of characters) plus ``palette`` (character → color);
* shape mode: ``shapes`` with ``ellipse``, ``circle``, ``rect``,
  ``rounded_rect``, ``polygon``, ``polyline``, ``line`` and ``arc``;
* colors: ``#RRGGBB``, ``#RRGGBBAA``, CSS names or an object
  ``{"type": "linear", "from": "...", "to": "...", "angle": 90}``;
* all coordinates and sizes are in the 0..100 space, independent of output size.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageColor, ImageDraw

from reasonable.core.i18n import tr as _tr


SUPPORTED_SHAPES = {
    "ellipse",
    "circle",
    "rect",
    "rectangle",
    "rounded_rect",
    "rounded_rectangle",
    "polygon",
    "polyline",
    "line",
    "arc",
}
TRANSPARENT_CHARS = {" ", ".", "_"}
MAX_GRID = 256


class DrawingError(ValueError):
    """Invalid drawing description."""


def _fail(message: str) -> DrawingError:
    return DrawingError(message)


def _color(value: Any, *, opacity: float = 1.0) -> tuple[int, int, int, int] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        raise _fail(_tr("A gradient cannot be used where a solid color is required.", "Градиент нельзя использовать там, где нужен сплошной цвет."))
    if isinstance(value, (list, tuple)):
        if len(value) not in (3, 4):
            raise _fail(_tr("A color array must contain 3 or 4 numbers.", "Массив цвета должен содержать 3 или 4 числа."))
        try:
            channels = [max(0, min(255, int(item))) for item in value]
        except (TypeError, ValueError):
            raise _fail(_tr("A color array must contain numbers from 0 to 255.", "Массив цвета должен содержать числа от 0 до 255."))
        if len(channels) == 3:
            channels.append(255)
        alpha = int(channels[3] * max(0.0, min(1.0, opacity)))
        return channels[0], channels[1], channels[2], alpha
    text = str(value).strip()
    if not text or text.lower() in {"none", "transparent", "null"}:
        return None
    try:
        rgb = ImageColor.getrgb(text)
    except (ValueError, TypeError):
        raise _fail(_tr("Unknown color: {value}", "Неизвестный цвет: {value}", value=text))
    if len(rgb) == 3:
        rgb = (*rgb, 255)
    alpha = int(rgb[3] * max(0.0, min(1.0, opacity)))
    return rgb[0], rgb[1], rgb[2], alpha


def _is_gradient(value: Any) -> bool:
    return isinstance(value, dict) and str(value.get("type") or "").lower() in {"linear", "radial"}


def _gradient_stops(spec: dict[str, Any]) -> list[tuple[float, tuple[int, int, int, int]]]:
    raw = spec.get("stops")
    stops: list[tuple[float, tuple[int, int, int, int]]] = []
    if isinstance(raw, list) and len(raw) >= 2:
        for item in raw:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                raise _fail(_tr("Gradient stops must be [position, color] pairs.", "Остановки градиента должны быть парами [позиция, цвет]."))
            try:
                position = max(0.0, min(1.0, float(item[0])))
            except (TypeError, ValueError):
                raise _fail(_tr("Gradient stop positions must be numbers.", "Позиции остановок градиента должны быть числами."))
            color = _color(item[1])
            if color is None:
                raise _fail(_tr("Gradient stops need solid colors.", "Остановкам градиента нужны сплошные цвета."))
            stops.append((position, color))
        stops.sort(key=lambda pair: pair[0])
        return stops
    first = _color(spec.get("from", spec.get("start", "#FFFFFF")))
    second = _color(spec.get("to", spec.get("end", "#000000")))
    if first is None or second is None:
        raise _fail(_tr("A gradient needs two colors.", "Градиенту нужны два цвета."))
    return [(0.0, first), (1.0, second)]


def _mix_stops(stops: list[tuple[float, tuple[int, int, int, int]]], t: float) -> tuple[int, int, int, int]:
    t = max(0.0, min(1.0, t))
    previous_position, previous_color = stops[0]
    for position, color in stops[1:]:
        if t <= position:
            span = max(1e-9, position - previous_position)
            amount = (t - previous_position) / span
            return tuple(
                int(previous_color[index] + (color[index] - previous_color[index]) * amount)
                for index in range(4)
            )
        previous_position, previous_color = position, color
    return previous_color


def _gradient_image(size: tuple[int, int], spec: dict[str, Any]) -> Image.Image:
    """Small gradient rendered once and smoothly upscaled."""
    stops = _gradient_stops(spec)
    sample = 96
    small = Image.new("RGBA", (sample, sample))
    pixels = small.load()
    kind = str(spec.get("type") or "linear").lower()
    if kind == "radial":
        center = _point(spec.get("center", [50, 50]))
        radius = _number(spec.get("radius", 50), default=50)
        radius = max(1.0, radius)
        for y in range(sample):
            for x in range(sample):
                dx = (x / sample * 100.0) - center[0]
                dy = (y / sample * 100.0) - center[1]
                t = math.hypot(dx, dy) / radius
                pixels[x, y] = _mix_stops(stops, t)
    else:
        angle = math.radians(float(spec.get("angle", 90)))
        dx, dy = math.cos(angle), math.sin(angle)
        extent = abs(dx) + abs(dy)
        if extent < 1e-9:
            extent = 1.0
        for y in range(sample):
            for x in range(sample):
                # 0 at one edge, 1 at the opposite edge, regardless of angle.
                u = (x + 0.5) / sample - 0.5
                v = (y + 0.5) / sample - 0.5
                t = 0.5 + (u * dx + v * dy) / extent
                pixels[x, y] = _mix_stops(stops, t)
    return small.resize(size, Image.Resampling.BILINEAR)


def _number(value: Any, *, default: float | None = None) -> float:
    if value is None:
        if default is None:
            raise _fail(_tr("A number is required.", "Требуется число."))
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        raise _fail(_tr("Expected a number, got: {value}", "Ожидалось число, получено: {value}", value=value))


def _point(value: Any) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise _fail(_tr("A point must be [x, y].", "Точка должна быть [x, y]."))
    return _number(value[0]), _number(value[1])


def _points(value: Any, *, minimum: int = 2) -> list[tuple[float, float]]:
    if not isinstance(value, (list, tuple)) or len(value) < minimum:
        raise _fail(_tr("At least {count} points are required.", "Нужно минимум {count} точек.", count=minimum))
    return [_point(item) for item in value]


def _box(value: Any) -> tuple[float, float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise _fail(_tr("A box must be [x0, y0, x1, y1].", "Рамка должна быть [x0, y0, x1, y1]."))
    return _number(value[0]), _number(value[1]), _number(value[2]), _number(value[3])


def _box_or_default(shape: dict[str, Any], default: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    raw = shape.get("box", shape.get("bbox"))
    return _box(raw) if raw is not None else default


def _scaled(value: float, scale: float) -> int:
    return int(round(value * scale))


def _scaled_points(points: Iterable[tuple[float, float]], scale: float) -> list[tuple[int, int]]:
    return [(_scaled(x, scale), _scaled(y, scale)) for x, y in points]


def _shape_geometry(shape: dict[str, Any], scale: float) -> dict[str, Any]:
    kind = str(shape.get("type") or "").strip().lower()
    if kind == "rectangle":
        kind = "rect"
    if kind == "rounded_rectangle":
        kind = "rounded_rect"
    if kind not in SUPPORTED_SHAPES:
        raise _fail(
            _tr(
                "Unknown shape type: {kind}. Use one of: {allowed}.",
                "Неизвестный тип фигуры: {kind}. Доступны: {allowed}.",
                kind=kind or "?",
                allowed=", ".join(sorted(SUPPORTED_SHAPES)),
            )
        )
    if kind == "circle":
        center = _point(shape.get("center", [50, 50]))
        radius = _number(shape.get("radius", 25))
        box = (center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius)
        return {"kind": "ellipse", "box": tuple(_scaled(v, scale) for v in box)}
    if kind == "ellipse":
        center = _point(shape.get("center", [50, 50]))
        raw_radius = shape.get("radius", shape.get("radii", 25))
        if isinstance(raw_radius, (list, tuple)):
            if len(raw_radius) != 2:
                raise _fail(_tr("An ellipse radius must be a number or [rx, ry].", "Радиус эллипса должен быть числом или [rx, ry]."))
            rx, ry = _number(raw_radius[0]), _number(raw_radius[1])
        else:
            rx = ry = _number(raw_radius)
        box = (center[0] - rx, center[1] - ry, center[0] + rx, center[1] + ry)
        return {"kind": "ellipse", "box": tuple(_scaled(v, scale) for v in box)}
    if kind in {"rect", "rounded_rect"}:
        box = _box_or_default(shape, (25, 25, 75, 75))
        result = {"kind": kind, "box": tuple(_scaled(v, scale) for v in box)}
        if kind == "rounded_rect":
            limit = max(0, min(abs(result["box"][2] - result["box"][0]), abs(result["box"][3] - result["box"][1])) // 2)
            result["radius"] = min(limit, max(0, _scaled(_number(shape.get("radius", 8)), scale)))
        return result
    if kind == "polygon":
        raw = shape.get("points")
        if isinstance(raw, list) and len(raw) >= 3:
            points = raw
        else:
            raise _fail(_tr("A polygon needs at least 3 points.", "Многоугольнику нужно минимум 3 точки."))
        return {"kind": "polygon", "points": _scaled_points(_points(points, minimum=3), scale)}
    if kind in {"line", "polyline"}:
        raw = shape.get("points")
        if raw is None and shape.get("start") is not None and shape.get("end") is not None:
            raw = [shape.get("start"), shape.get("end")]
        points = _points(raw)
        width = max(1, _scaled(_number(shape.get("width", shape.get("outline_width", 2)), default=2), scale))
        return {"kind": "line", "points": _scaled_points(points, scale), "width": width}
    # arc
    box = _box_or_default(shape, (20, 20, 80, 80))
    start = _number(shape.get("start", 0), default=0)
    end = _number(shape.get("end", 180), default=180)
    width = max(1, _scaled(_number(shape.get("width", shape.get("outline_width", 2)), default=2), scale))
    return {
        "kind": "arc",
        "box": tuple(_scaled(v, scale) for v in box),
        "start": start,
        "end": end,
        "width": width,
    }


def _draw_geometry(draw: ImageDraw.ImageDraw, geometry: dict[str, Any], fill: Any, outline: Any, width: int) -> None:
    kind = geometry["kind"]
    if kind == "ellipse":
        draw.ellipse(geometry["box"], fill=fill, outline=outline, width=width)
    elif kind == "rect":
        draw.rectangle(geometry["box"], fill=fill, outline=outline, width=width)
    elif kind == "rounded_rect":
        draw.rounded_rectangle(geometry["box"], radius=geometry["radius"], fill=fill, outline=outline, width=width)
    elif kind == "polygon":
        draw.polygon(geometry["points"], fill=fill, outline=outline)
        if outline and width > 0:
            draw.line(geometry["points"] + [geometry["points"][0]], fill=outline, width=width, joint="curve")
    elif kind == "line":
        draw.line(geometry["points"], fill=fill, width=geometry["width"], joint="curve")
    elif kind == "arc":
        draw.arc(geometry["box"], geometry["start"], geometry["end"], fill=fill, width=geometry["width"])


def _paint_shape(image: Image.Image, shape: dict[str, Any], scale: float) -> None:
    if not isinstance(shape, dict):
        raise _fail(_tr("Every shape must be an object.", "Каждая фигура должна быть объектом."))
    geometry = _shape_geometry(shape, scale)
    opacity = max(0.0, min(1.0, _number(shape.get("opacity", 1), default=1)))
    raw_fill = shape.get("fill", shape.get("color", "#FFFFFF"))
    outline = _color(shape.get("outline"))
    if geometry["kind"] in {"line", "arc"} and shape.get("fill") is None and shape.get("color") is None and outline is not None:
        # Lines and arcs have no interior; a lone outline is the stroke color.
        raw_fill, outline = shape.get("outline"), None
    outline_width = max(0, _scaled(_number(shape.get("outline_width", 0), default=0), scale))
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    if _is_gradient(raw_fill):
        mask = Image.new("L", image.size, 0)
        mask_draw = ImageDraw.Draw(mask)
        _draw_geometry(mask_draw, geometry, 255, None, 0)
        gradient = _gradient_image(image.size, raw_fill)
        layer.paste(gradient, (0, 0), mask)
    else:
        fill = _color(raw_fill)
        if fill is not None:
            _draw_geometry(draw, geometry, fill, None, 0)
    if outline is not None and outline_width > 0 and geometry["kind"] != "line":
        _draw_geometry(draw, geometry, None, outline, outline_width)
    if opacity < 1.0:
        alpha = layer.getchannel("A").point(lambda value: int(value * opacity))
        layer.putalpha(alpha)
    image.alpha_composite(layer)


def _fit_canvas(image: Image.Image, size: int, *, margin: int, resample: Image.Resampling) -> Image.Image:
    bbox = image.getbbox()
    if bbox:
        image = image.crop(bbox)
    max_dim = max(1, size - margin * 2)
    scale = min(max_dim / max(1, image.width), max_dim / max(1, image.height))
    new_size = (max(1, int(round(image.width * scale))), max(1, int(round(image.height * scale))))
    image = image.resize(new_size, resample)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(image, ((size - new_size[0]) // 2, (size - new_size[1]) // 2))
    return canvas


def _render_shapes(shapes: list[dict[str, Any]], size: int, background: str | None, trim: bool) -> tuple[Image.Image, int]:
    if not isinstance(shapes, list) or not shapes:
        raise _fail(_tr("Shape mode needs a non-empty shapes list.", "Режиму фигур нужен непустой список shapes."))
    work = min(2048, max(size * 4, size))
    image = Image.new("RGBA", (work, work), (0, 0, 0, 0))
    if background:
        color = _color(background)
        if color is not None:
            image.paste(color, (0, 0, work, work))
    scale = work / 100.0
    for shape in shapes:
        _paint_shape(image, shape, scale)
    if trim:
        # Keep a small breathing room around the subject; this makes separately
        # drawn assets feel like one visual set.
        image = _fit_canvas(image, size, margin=max(1, size // 24), resample=Image.Resampling.LANCZOS)
    elif image.size != (size, size):
        image = image.resize((size, size), Image.Resampling.LANCZOS)
    return image, len(shapes)


def _render_pixels(pixels: list[str], palette: dict[str, Any], size: int, background: str | None, trim: bool) -> tuple[Image.Image, tuple[int, int]]:
    if not isinstance(pixels, list) or not pixels:
        raise _fail(_tr("Pixel mode needs a non-empty pixels list.", "Режиму пикселей нужен непустой список pixels."))
    if len(pixels) > MAX_GRID:
        raise _fail(_tr("The pixel grid has too many rows (maximum {count}).", "В пиксельной сетке слишком много строк (максимум {count}).", count=MAX_GRID))
    rows = []
    for row in pixels:
        if not isinstance(row, str):
            raise _fail(_tr("Every pixel row must be a string.", "Каждая строка пикселей должна быть строкой."))
        if len(row) > MAX_GRID:
            raise _fail(_tr("A pixel row is too long (maximum {count}).", "Строка пикселей слишком длинная (максимум {count}).", count=MAX_GRID))
        rows.append(row)
    width = max(len(row) for row in rows)
    if width <= 0:
        raise _fail(_tr("The pixel grid is empty.", "Пиксельная сетка пуста."))
    if len({len(row) for row in rows}) > 1:
        raise _fail(_tr("All pixel rows must have the same length.", "Все строки пикселей должны быть одинаковой длины."))
    palette = palette if isinstance(palette, dict) else {}
    colors: dict[str, tuple[int, int, int, int] | None] = {}
    for key, value in palette.items():
        if not isinstance(key, str) or len(key) != 1:
            raise _fail(_tr("Palette keys must be single characters.", "Ключи палитры должны состоять из одного символа."))
        colors[key] = _color(value)
    for char in TRANSPARENT_CHARS:
        colors[char] = None
    missing = sorted({char for row in rows for char in row if char not in colors})
    if missing:
        raise _fail(
            _tr(
                "No palette color for characters: {chars}",
                "Нет цвета палитры для символов: {chars}",
                chars=" ".join(repr(char) for char in missing),
            )
        )
    image = Image.new("RGBA", (width, len(rows)), (0, 0, 0, 0))
    if background:
        color = _color(background)
        if color is not None and color[3] > 0:
            image.paste(color, (0, 0, width, len(rows)))
    for y, row in enumerate(rows):
        for x, char in enumerate(row):
            color = colors.get(char)
            if color is not None and color[3] > 0:
                image.putpixel((x, y), color)
    if trim and background is None:
        bbox = image.getbbox()
        if bbox:
            image = image.crop(bbox)
    if image.size != (size, size):
        image = _fit_canvas(image, size, margin=max(1, size // 24), resample=Image.Resampling.NEAREST)
    return image, (width, len(rows))


def draw_sprite(
    output_path: str | Path,
    *,
    mode: str | None = None,
    pixels: list[str] | None = None,
    palette: dict[str, Any] | None = None,
    shapes: list[dict[str, Any]] | None = None,
    size: int = 256,
    background: str | None = None,
    trim: bool = True,
) -> dict[str, Any]:
    """Render a sprite description and save it as a PNG.

    ``mode`` is inferred when omitted: ``pixels`` selects pixel mode, otherwise
    ``shapes``. The output is always RGBA; empty margins are trimmed by default.
    """
    try:
        size = max(16, min(1024, int(size)))
    except (TypeError, ValueError):
        raise _fail(_tr("The sprite size must be a number from 16 to 1024.", "Размер спрайта должен быть числом от 16 до 1024."))
    selected = (mode or ("pixels" if pixels else "shapes")).strip().lower()
    if selected not in {"pixels", "shapes"}:
        raise _fail(_tr("Unknown draw mode: {mode}. Use 'pixels' or 'shapes'.", "Неизвестный режим рисования: {mode}. Используйте 'pixels' или 'shapes'.", mode=mode))
    if selected == "pixels":
        image, grid = _render_pixels(pixels or [], palette or {}, size, background, bool(trim))
        details: dict[str, Any] = {"mode": "pixels", "grid": list(grid)}
    else:
        image, count = _render_shapes(shapes or [], size, background, bool(trim))
        details = {"mode": "shapes", "shape_count": count}
    target = Path(output_path)
    if not target.is_absolute():
        target = Path.cwd() / target
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, "PNG")
    return {
        "path": str(target),
        "size": size,
        "provider": "draw",
        "trimmed": bool(trim),
        **details,
        "message": _tr("The sprite was drawn from the description.", "Спрайт нарисован по описанию."),
    }
