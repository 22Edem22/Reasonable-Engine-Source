"""Small drawing, color and font helpers shared by the runtime and splash."""

from __future__ import annotations

import functools
import math
import os
from pathlib import Path
from typing import Iterable, Sequence

import pygame

try:
    from reasonable.core.i18n import tr as _tr
except Exception:  # exported builds may run without the bundled core package
    def _tr(en: str, ru: str, **values) -> str:
        return en

from reasonable.core.paths import resource_path

try:
    from pygame import gfxdraw
except Exception:  # pragma: no cover - gfxdraw is optional on some builds
    gfxdraw = None


UI_FONT = resource_path("assets/fonts/Inter-Variable.ttf")
DISPLAY_FONT = resource_path("assets/fonts/Unbounded-Variable.ttf")

WHITE = pygame.Color("#F4F7FB")
MUTED = pygame.Color("#8A9AB3")
ACCENT = pygame.Color("#FF6B4A")
ACCENT_2 = pygame.Color("#35D6C4")
ACCENT_3 = pygame.Color("#FFC857")
BG = pygame.Color("#080C14")
PANEL = pygame.Color("#111A28")
BORDER = pygame.Color("#223047")
DANGER = pygame.Color("#FF5D73")
SUCCESS = pygame.Color("#4ADE80")


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def inv_lerp(a: float, b: float, value: float) -> float:
    if b == a:
        return 0.0
    return clamp((value - a) / (b - a))


def smoothstep(t: float) -> float:
    t = clamp(t)
    return t * t * (3 - 2 * t)


def ease_out_cubic(t: float) -> float:
    return 1 - (1 - clamp(t)) ** 3


def ease_in_out_cubic(t: float) -> float:
    t = clamp(t)
    return 4 * t * t * t if t < 0.5 else 1 - ((-2 * t + 2) ** 3) / 2


def ease_out_back(t: float) -> float:
    t = clamp(t)
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def ease_out_expo(t: float) -> float:
    t = clamp(t)
    return 1 if t >= 1 else 1 - pow(2, -10 * t)


def ease_in_out_sine(t: float) -> float:
    return -(math.cos(math.pi * clamp(t)) - 1) / 2


EASINGS = {
    "linear": lambda t: clamp(t),
    "smooth": smoothstep,
    "out_cubic": ease_out_cubic,
    "in_out_cubic": ease_in_out_cubic,
    "out_back": ease_out_back,
    "out_expo": ease_out_expo,
    "in_out_sine": ease_in_out_sine,
}


def color(value) -> pygame.Color:
    if isinstance(value, pygame.Color):
        return value
    if isinstance(value, str):
        try:
            return pygame.Color(value)
        except ValueError:
            return pygame.Color("#FF00FF")
    return pygame.Color(*value)


def with_alpha(value, alpha: int) -> pygame.Color:
    c = color(value)
    return pygame.Color(c.r, c.g, c.b, max(0, min(255, int(alpha))))


def mix(a, b, t: float) -> pygame.Color:
    ca, cb = color(a), color(b)
    t = clamp(t)
    return pygame.Color(
        int(lerp(ca.r, cb.r, t)),
        int(lerp(ca.g, cb.g, t)),
        int(lerp(ca.b, cb.b, t)),
        int(lerp(ca.a, cb.a, t)),
    )


@functools.lru_cache(maxsize=64)
def get_font(size: int, bold: bool = False, display: bool = False) -> pygame.font.Font:
    if not pygame.font.get_init():
        pygame.font.init()
    size = max(6, int(size))
    path = DISPLAY_FONT if display else UI_FONT
    font = None
    if path.exists():
        try:
            font = pygame.font.Font(str(path), size)
        except Exception:
            font = None
    if font is None:
        names = ["Segoe UI", "Arial", "DejaVu Sans"]
        for name in names:
            try:
                matched = pygame.font.match_font(name, bold=bold)
            except Exception:
                matched = None
            if matched:
                try:
                    font = pygame.font.Font(matched, size)
                    break
                except Exception:
                    continue
        if font is None:
            font = pygame.font.Font(None, size)
    try:
        font.set_bold(bool(bold))
    except Exception:
        pass
    return font


def render_text(
    text: str,
    size: int = 20,
    text_color=WHITE,
    *,
    bold: bool = False,
    display: bool = False,
    shadow: bool = False,
    shadow_color=(0, 0, 0, 130),
    letter_spacing: int = 0,
) -> pygame.Surface:
    font = get_font(size, bold, display)
    text = str(text)
    if letter_spacing:
        glyphs = [font.render(ch, True, color(text_color)) for ch in text]
        width = sum(g.get_width() for g in glyphs) + letter_spacing * max(0, len(glyphs) - 1)
        height = max((g.get_height() for g in glyphs), default=font.get_height())
        result = pygame.Surface((max(1, width), max(1, height + 4)), pygame.SRCALPHA)
        x = 0
        for glyph in glyphs:
            result.blit(glyph, (x, 2))
            x += glyph.get_width() + letter_spacing
    else:
        result = font.render(text, True, color(text_color))
    if shadow:
        base = pygame.Surface((result.get_width() + 8, result.get_height() + 10), pygame.SRCALPHA)
        shade = font.render(text, True, color(shadow_color)) if not letter_spacing else None
        if letter_spacing:
            temp = get_font(size, bold, display).render(text, True, color(shadow_color))
            shade = pygame.transform.smoothscale(temp, (result.get_width(), result.get_height())) if result.get_width() else temp
        if shade:
            base.blit(shade, (4, 6))
        base.blit(result, (4, 2))
        return base
    return result


@functools.lru_cache(maxsize=512)
def _rounded_cache(
    width: int,
    height: int,
    fill: tuple,
    radius: int,
    border_color: tuple | None,
    border_width: int,
    shadow: bool,
    supersample: int = 3,
) -> pygame.Surface:
    width, height = max(1, int(width)), max(1, int(height))
    radius = int(min(radius, min(width, height) // 2))
    pad = 16 if shadow else 0
    w, h = (width + pad * 2) * supersample, (height + pad * 2) * supersample
    surface = pygame.Surface((w, h), pygame.SRCALPHA)
    rect = pygame.Rect(pad * supersample, pad * supersample, width * supersample, height * supersample)
    r = radius * supersample
    if shadow:
        shadow_surface = pygame.Surface((w, h), pygame.SRCALPHA)
        for i in range(5, 0, -1):
            alpha = int(5 + (5 - i) * 4)
            shadow_rect = rect.inflate(i * 6 * supersample, i * 6 * supersample)
            shadow_rect.move_ip(0, (i + 2) * supersample)
            pygame.draw.rect(
                shadow_surface,
                (0, 0, 0, alpha),
                shadow_rect,
                border_radius=r + i * 3,
            )
        surface.blit(shadow_surface, (0, 0))
    pygame.draw.rect(surface, fill, rect, border_radius=r)
    if border_color and border_width > 0:
        pygame.draw.rect(
            surface,
            border_color,
            rect,
            width=max(1, border_width * supersample),
            border_radius=r,
        )
    return pygame.transform.smoothscale(surface, (width + pad * 2, height + pad * 2))


def draw_rounded_rect(
    surface: pygame.Surface,
    rect: pygame.Rect | tuple,
    fill,
    radius: int = 14,
    *,
    border=None,
    border_width: int = 1,
    shadow: bool = False,
) -> pygame.Rect:
    rect = pygame.Rect(rect)
    fill_c = color(fill)
    border_c = tuple(color(border)) if border is not None else None
    key = (
        rect.width,
        rect.height,
        tuple(fill_c),
        int(radius),
        border_c,
        int(border_width),
        bool(shadow),
    )
    rendered = _rounded_cache(*key)
    pad = 16 if shadow else 0
    surface.blit(rendered, (rect.x - pad, rect.y - pad))
    return rect


def draw_gradient(
    surface: pygame.Surface,
    rect: pygame.Rect | tuple,
    top_color,
    bottom_color,
    *,
    horizontal: bool = False,
) -> None:
    rect = pygame.Rect(rect)
    if rect.width <= 0 or rect.height <= 0:
        return
    top, bottom = color(top_color), color(bottom_color)
    length = rect.width if horizontal else rect.height
    length = max(1, length)
    if horizontal:
        for x in range(length):
            t = x / max(1, length - 1)
            line = mix(top, bottom, t)
            pygame.draw.line(surface, line, (rect.x + x, rect.y), (rect.x + x, rect.bottom))
    else:
        for y in range(length):
            t = y / max(1, length - 1)
            line = mix(top, bottom, t)
            pygame.draw.line(surface, line, (rect.x, rect.y + y), (rect.right, rect.y + y))


def gradient_surface(size: tuple[int, int], top_color, bottom_color) -> pygame.Surface:
    result = pygame.Surface(size, pygame.SRCALPHA)
    draw_gradient(result, result.get_rect(), top_color, bottom_color)
    return result


def draw_glow(surface: pygame.Surface, center, radius: int, glow_color, alpha: int = 60, layers: int = 5) -> None:
    """Draw a soft radial glow.

    The falloff is rendered at low resolution and smoothly upscaled. This avoids
    the visible concentric banding of naive layered circles and is much faster.
    """
    radius = int(radius)
    if radius <= 1 or alpha <= 0:
        return
    cx, cy = int(center[0]), int(center[1])
    scale = 6
    small_radius = max(2, radius // scale)
    small = pygame.Surface((small_radius * 2, small_radius * 2), pygame.SRCALPHA)
    steps = max(24, layers * 8)
    for step in range(steps, 0, -1):
        r = small_radius * step / steps
        # outer rings are faint, inner rings approach the requested alpha
        strength = (1 - step / (steps + 1)) ** 1.45
        a = int(alpha * strength)
        if a <= 0 or r <= 0:
            continue
        pygame.draw.circle(small, with_alpha(glow_color, a), (small_radius, small_radius), max(1, int(r)))
    big = pygame.transform.smoothscale(small, (radius * 2, radius * 2))
    surface.blit(big, (cx - radius, cy - radius))


def draw_shadow_text(
    surface: pygame.Surface,
    text: str,
    position: tuple[int, int],
    size: int = 22,
    text_color=WHITE,
    *,
    anchor: str = "topleft",
    bold: bool = False,
    display: bool = False,
    letter_spacing: int = 0,
    shadow: bool = True,
) -> pygame.Rect:
    image = render_text(
        text,
        size,
        text_color,
        bold=bold,
        display=display,
        shadow=shadow,
        letter_spacing=letter_spacing,
    )
    offset = (0, 0)
    if shadow:
        offset = (4, 2)
    rect = image.get_rect()
    setattr(rect, anchor, (int(position[0] + offset[0]), int(position[1] + offset[1])))
    surface.blit(image, rect)
    return rect


def wrap_text(font: pygame.font.Font, text: str, max_width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in str(text).split("\n"):
        if not paragraph:
            lines.append("")
            continue
        words = paragraph.split(" ")
        current = ""
        for word in words:
            candidate = word if not current else f"{current} {word}"
            if font.size(candidate)[0] <= max_width or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def draw_wrapped_text(
    surface: pygame.Surface,
    text: str,
    rect: pygame.Rect | tuple,
    size: int = 18,
    text_color=WHITE,
    *,
    line_height: float = 1.35,
    bold: bool = False,
    align: str = "left",
    display: bool = False,
) -> int:
    rect = pygame.Rect(rect)
    font = get_font(size, bold, display)
    lines = wrap_text(font, text, rect.width)
    y = rect.y
    step = int(size * line_height)
    for line in lines:
        if y + step > rect.bottom + step:
            break
        image = font.render(line, True, color(text_color))
        if align == "center":
            x = rect.centerx - image.get_width() // 2
        elif align == "right":
            x = rect.right - image.get_width()
        else:
            x = rect.x
        surface.blit(image, (x, y))
        y += step
    return y - rect.y


def load_image(path, *, alpha: bool = True) -> pygame.Surface:
    if isinstance(path, pygame.Surface):
        return path
    if path is None:
        return placeholder_surface("?")
    path_obj = Path(path)
    if not path_obj.is_absolute():
        path_obj = Path(os.getcwd()) / path_obj
    try:
        image = pygame.image.load(str(path_obj))
        return image.convert_alpha() if alpha else image.convert()
    except Exception as exc:
        print(_tr("[Reasonable] Could not load the image {path}: {error}", "[Reasonable] Не удалось загрузить изображение {path}: {error}", path=path, error=exc))
        return placeholder_surface(Path(str(path)).suffix.replace(".", "") or "?")


@functools.lru_cache(maxsize=128)
def placeholder_surface(label: str = "?") -> pygame.Surface:
    surface = pygame.Surface((64, 64), pygame.SRCALPHA)
    surface.fill((70, 30, 70, 180))
    pygame.draw.line(surface, (255, 60, 220), (0, 0), (64, 64), 3)
    pygame.draw.line(surface, (255, 60, 220), (64, 0), (0, 64), 3)
    image = render_text(label[:2], 20, (255, 210, 255), bold=True)
    surface.blit(image, image.get_rect(center=(32, 32)))
    return surface


def tint_surface(surface: pygame.Surface, tint_color, alpha: int = 255) -> pygame.Surface:
    tinted = surface.copy()
    tinted.fill((*color(tint_color)[:3], max(0, min(255, alpha))), special_flags=pygame.BLEND_RGBA_MULT)
    return tinted


def draw_icon(surface: pygame.Surface, name: str, rect: pygame.Rect, color_value=WHITE, width: int = 2) -> None:
    """Tiny vector icon set used by the in-app UI (no icon-font dependency)."""
    rect = pygame.Rect(rect)
    c = color(color_value)
    x, y, w, h = rect.x, rect.y, rect.width, rect.height
    cx, cy = rect.center
    width = max(1, int(width))
    if name == "play":
        pygame.draw.polygon(surface, c, [(x + w * 0.28, y + h * 0.16), (x + w * 0.28, y + h * 0.84), (x + w * 0.85, cy)])
    elif name == "spark":
        points = []
        for i in range(16):
            angle = -math.pi / 2 + i * math.pi / 8
            radius = (min(w, h) * 0.48) if i % 2 == 0 else (min(w, h) * 0.16)
            points.append((cx + math.cos(angle) * radius, cy + math.sin(angle) * radius))
        pygame.draw.polygon(surface, c, points)
    elif name == "send":
        pygame.draw.polygon(surface, c, [(x + w * 0.12, y + h * 0.18), (x + w * 0.9, cy), (x + w * 0.12, y + h * 0.82), (x + w * 0.28, cy)])
    elif name == "settings":
        pygame.draw.circle(surface, c, (cx, cy), int(min(w, h) * 0.29), width)
        pygame.draw.circle(surface, c, (cx, cy), int(min(w, h) * 0.09), width)
        for i in range(8):
            angle = i * math.pi / 4
            x1 = cx + math.cos(angle) * min(w, h) * 0.36
            y1 = cy + math.sin(angle) * min(w, h) * 0.36
            x2 = cx + math.cos(angle) * min(w, h) * 0.48
            y2 = cy + math.sin(angle) * min(w, h) * 0.48
            pygame.draw.line(surface, c, (x1, y1), (x2, y2), width)
    elif name == "back":
        pygame.draw.lines(surface, c, False, [(x + w * 0.62, y + h * 0.18), (x + w * 0.28, cy), (x + w * 0.62, y + h * 0.82)], width)
    elif name == "plus":
        pygame.draw.line(surface, c, (x + w * 0.2, cy), (x + w * 0.8, cy), width)
        pygame.draw.line(surface, c, (cx, y + h * 0.2), (cx, y + h * 0.8), width)
    elif name == "close":
        pygame.draw.line(surface, c, (x + w * 0.25, y + h * 0.25), (x + w * 0.75, y + h * 0.75), width)
        pygame.draw.line(surface, c, (x + w * 0.75, y + h * 0.25), (x + w * 0.25, y + h * 0.75), width)
    elif name == "chat":
        pygame.draw.rect(surface, c, (x + w * 0.12, y + h * 0.18, w * 0.76, h * 0.53), width=width, border_radius=int(min(w, h) * 0.14))
        pygame.draw.lines(surface, c, False, [(x + w * 0.3, y + h * 0.7), (x + w * 0.22, y + h * 0.88), (x + w * 0.48, y + h * 0.7)], width)
    elif name == "home":
        pygame.draw.lines(surface, c, False, [(x + w * 0.14, y + h * 0.5), (cx, y + h * 0.16), (x + w * 0.86, y + h * 0.5)], width)
        pygame.draw.lines(surface, c, False, [(x + w * 0.24, y + h * 0.48), (x + w * 0.24, y + h * 0.86), (x + w * 0.76, y + h * 0.86), (x + w * 0.76, y + h * 0.48)], width)
    elif name == "check":
        pygame.draw.lines(surface, c, False, [(x + w * 0.16, cy), (x + w * 0.43, y + h * 0.7), (x + w * 0.84, y + h * 0.3)], width)
    elif name == "chevron_right":
        pygame.draw.lines(surface, c, False, [(x + w * 0.38, y + h * 0.2), (x + w * 0.68, cy), (x + w * 0.38, y + h * 0.8)], width)
    elif name == "image":
        pygame.draw.rect(surface, c, (x + w * 0.12, y + h * 0.16, w * 0.76, h * 0.68), width=width, border_radius=int(min(w, h) * 0.1))
        pygame.draw.circle(surface, c, (x + w * 0.35, y + h * 0.36), max(1, int(min(w, h) * 0.07)))
        pygame.draw.lines(surface, c, False, [(x + w * 0.18, y + h * 0.74), (x + w * 0.44, y + h * 0.48), (x + w * 0.62, y + h * 0.66), (x + w * 0.72, y + h * 0.57), (x + w * 0.84, y + h * 0.72)], width)
    elif name == "stop":
        pygame.draw.rect(surface, c, (x + w * 0.25, y + h * 0.25, w * 0.5, h * 0.5), border_radius=2)
    elif name == "refresh":
        pygame.draw.arc(surface, c, (x + w * 0.18, y + h * 0.18, w * 0.64, h * 0.64), 0.4, 5.3, width)
        pygame.draw.polygon(surface, c, [(x + w * 0.75, y + h * 0.16), (x + w * 0.86, y + h * 0.34), (x + w * 0.63, y + h * 0.34)])


def ellipsis(text: str, font: pygame.font.Font, max_width: int) -> str:
    if font.size(text)[0] <= max_width:
        return text
    while text and font.size(text + "…")[0] > max_width:
        text = text[:-1]
    return text + "…"
