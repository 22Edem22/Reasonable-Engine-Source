"""The small but expressive UI toolkit used by desktop-style apps.

Everything is drawn with pygame primitives, so the same interface works on
Windows and Android. The API is deliberately immediate-mode friendly but keeps
real widget objects for focus, hover and scrolling.

Example:
    app = UIApp("Notes", (1100, 720))
    root = Panel(padding=24)
    root.add(Label("Hello", size=32, bold=True))
    root.add(Button("Нажми меня", on_click=lambda: print("clicked")))
    app.set_root(root)
    app.run()
"""

from __future__ import annotations

import math
import os
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import pygame

try:
    from reasonable.core.i18n import tr as _tr
except Exception:  # exported builds may run without the bundled core package
    def _tr(en: str, ru: str, **values) -> str:
        return en

from .utils import (
    color,
    draw_gradient,
    draw_icon,
    draw_rounded_rect,
    draw_wrapped_text,
    ellipsis,
    get_font,
    load_image,
    mix,
    render_text,
    with_alpha,
)


# ----------------------------------------------------------------------------
# Theme
# ----------------------------------------------------------------------------


class Theme:
    def __init__(self, **overrides) -> None:
        self.bg = (15, 17, 21)
        self.bg_bottom = (12, 14, 18)
        self.panel = (23, 26, 32)
        self.panel_alt = (28, 32, 39)
        self.panel_hover = (35, 40, 48)
        self.border = (43, 48, 56)
        self.text = (231, 233, 236)
        self.muted = (154, 161, 171)
        self.faint = (111, 118, 128)
        self.accent = (217, 119, 87)
        self.accent_2 = (127, 163, 199)
        self.accent_3 = (201, 173, 115)
        self.danger = (201, 138, 144)
        self.success = (141, 184, 160)
        self.on_accent = (27, 17, 13)
        self.radius = 18
        self.radius_sm = 12
        self.button_height = 46
        self.font_size = 16
        self.hero = (31, 35, 42)
        for key, value in overrides.items():
            setattr(self, key, value)


_ACTIVE_THEME = Theme()


def set_active_theme(theme: Theme) -> None:
    global _ACTIVE_THEME
    _ACTIVE_THEME = theme


def get_theme() -> Theme:
    return _ACTIVE_THEME


# ----------------------------------------------------------------------------
# Focus and touch helpers
# ----------------------------------------------------------------------------


_FOCUSED_ENTRY = None


def event_pos(event: pygame.event.Event) -> tuple[int, int] | None:
    """Safely read a mouse position from any event.

    Some events never carry ``pos`` — notably MOUSEWHEEL, which only has
    ``x``/``y``. Accessing ``event.pos`` there crashes the whole app, so all
    widget code must go through this helper. For wheel events the current
    cursor position is used instead, which is what the user expects.
    """
    pos = getattr(event, "pos", None)
    if pos is not None:
        return pos
    try:
        return pygame.mouse.get_pos()
    except pygame.error:
        return None


def blur_entries() -> None:
    global _FOCUSED_ENTRY
    if _FOCUSED_ENTRY is not None:
        try:
            _FOCUSED_ENTRY.focused = False
        except Exception:
            pass
    _FOCUSED_ENTRY = None


def focus_entry(entry) -> None:
    global _FOCUSED_ENTRY
    if _FOCUSED_ENTRY is entry:
        entry.focused = True
        return
    if _FOCUSED_ENTRY is not None:
        _FOCUSED_ENTRY.focused = False
    _FOCUSED_ENTRY = entry
    entry.focused = True
    entry._blink = 0.0


def touch_to_mouse(event: pygame.event.Event) -> pygame.event.Event | None:
    """Map a finger event to a synthetic mouse event for UI widgets."""
    if event.type not in (
        pygame.FINGERDOWN,
        pygame.FINGERMOTION,
        pygame.FINGERUP,
    ):
        return event
    surface = pygame.display.get_surface()
    width, height = surface.get_size() if surface else (1, 1)
    pos = (int(event.x * width), int(event.y * height))
    if event.type == pygame.FINGERDOWN:
        return pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"pos": pos, "button": 1})
    if event.type == pygame.FINGERMOTION:
        return pygame.event.Event(pygame.MOUSEMOTION, {"pos": pos, "rel": (0, 0), "buttons": (1, 0, 0)})
    return pygame.event.Event(pygame.MOUSEBUTTONUP, {"pos": pos, "button": 1})


# ----------------------------------------------------------------------------
# Base widgets
# ----------------------------------------------------------------------------


class Widget:
    def __init__(
        self,
        *,
        width: int | None = None,
        height: int | None = None,
        padding: int = 0,
        expand_x: bool = False,
        expand_y: bool = False,
        align_x: str = "stretch",
        align_y: str = "stretch",
        visible: bool = True,
        enabled: bool = True,
    ) -> None:
        self.width = width
        self.height = height
        self.padding = padding
        self.expand_x = expand_x
        self.expand_y = expand_y
        self.align_x = align_x
        self.align_y = align_y
        self.visible = visible
        self.enabled = enabled
        self.hovered = False
        self.rect = pygame.Rect(0, 0, width or 0, height or 0)
        self.parent: Widget | None = None
        self.theme = get_theme()
        self.id = ""

    # -- layout -----------------------------------------------------------
    def measure(self, max_width: int, max_height: int) -> tuple[int, int]:
        return (self.width or 0, self.height or 0)

    def layout(self, rect: pygame.Rect | tuple) -> None:
        self.rect = pygame.Rect(rect)
        self.arrange()

    def arrange(self) -> None:
        pass

    # -- lifecycle --------------------------------------------------------
    def update(self, dt: float) -> None:
        pass

    def draw(self, surface: pygame.Surface) -> None:
        pass

    def on_mount(self) -> None:
        pass

    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.MOUSEMOTION:
            self.hovered = self.rect.collidepoint(event.pos)
        return False

    # -- helpers ----------------------------------------------------------
    def set_visible(self, value: bool) -> "Widget":
        self.visible = value
        return self

    def set_enabled(self, value: bool) -> "Widget":
        self.enabled = value
        return self

    def request_layout(self) -> None:
        parent = self.parent
        while parent is not None:
            parent = parent.parent


class Container(Widget):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.children: list[Widget] = []

    def add(self, *widgets: Widget) -> "Container":
        for widget in widgets:
            if widget is None:
                continue
            widget.parent = self
            self.children.append(widget)
        return self

    def remove(self, widget: Widget) -> None:
        if widget in self.children:
            self.children.remove(widget)
            widget.parent = None

    def clear(self) -> None:
        for child in self.children:
            child.parent = None
        self.children.clear()

    def on_mount(self) -> None:
        for child in self.children:
            child.on_mount()

    def update(self, dt: float) -> None:
        for child in self.children:
            if child.visible:
                child.update(dt)

    def handle_event(self, event: pygame.event.Event) -> bool:
        if not self.visible or not self.enabled:
            return False
        # Motion is broadcast so hover state can be cleared everywhere.
        if event.type == pygame.MOUSEMOTION:
            for child in self.children:
                child.handle_event(event)
            return False
        if event.type == pygame.MOUSEWHEEL:
            # Wheel events carry no `pos` on many pygame versions; use the
            # cursor position instead so scrolling never crashes.
            pos = event_pos(event)
            if pos is None or self.rect.collidepoint(pos):
                for child in reversed(self.children):
                    if child.visible and child.handle_event(event):
                        return True
            return False
        if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
            pos = getattr(event, "pos", None)
            if pos is None or not self.rect.collidepoint(pos):
                self.hovered = False
                return False
            for child in reversed(self.children):
                if child.visible and child.handle_event(event):
                    return True
            return False
        # keyboard / touch / other events go to children
        for child in reversed(self.children):
            if child.visible and child.handle_event(event):
                return True
        return False

    def draw_children(self, surface: pygame.Surface) -> None:
        for child in self.children:
            if child.visible:
                child.draw(surface)


class VStack(Container):
    def __init__(self, *, spacing: int = 12, padding: int = 0, **kwargs) -> None:
        super().__init__(padding=padding, **kwargs)
        self.spacing = spacing

    def measure(self, max_width: int, max_height: int) -> tuple[int, int]:
        inner_width = max(0, (self.width or max_width) - self.padding * 2)
        visible_children = [child for child in self.children if child.visible]
        widths, heights = [], []
        for child in visible_children:
            cw, ch = child.measure(inner_width, max(0, max_height - self.padding * 2))
            widths.append(cw)
            heights.append(child.height if child.height is not None else ch)
        natural_w = (max(widths) if widths else 0) + self.padding * 2
        natural_h = sum(heights) + self.spacing * max(0, len(visible_children) - 1) + self.padding * 2
        return (self.width or natural_w, self.height or natural_h)

    def arrange(self) -> None:
        if not self.children:
            return
        children = [child for child in self.children if child.visible]
        if not children:
            return
        inner = self.rect.inflate(-self.padding * 2, -self.padding * 2)
        if inner.width <= 0 or inner.height <= 0:
            return
        gap_total = self.spacing * (len(children) - 1)
        sizes: list[int] = []
        expands: list[int] = []
        measured_widths: list[int] = []
        for index, child in enumerate(children):
            cw, ch = child.measure(inner.width, inner.height)
            measured_widths.append(cw)
            base = child.height if child.height is not None else ch
            sizes.append(max(0, base))
            if child.expand_y:
                expands.append(index)
        used = sum(sizes) + gap_total
        extra = max(0, inner.height - used)
        if expands and extra > 0:
            share = extra // len(expands)
            for index in expands:
                sizes[index] += share
        y = inner.y
        for index, child in enumerate(children):
            height = sizes[index]
            if child.width is not None:
                width = min(child.width, inner.width)
            elif child.align_x == "stretch":
                width = inner.width
            else:
                width = min(measured_widths[index], inner.width)
            if child.align_x == "center" and child.width is None:
                x = inner.centerx - width // 2
            elif child.align_x == "right" and child.width is None:
                x = inner.right - width
            else:
                x = inner.x
            child.layout(pygame.Rect(x, y, max(1, width), max(1, height)))
            y += height + self.spacing

    def draw(self, surface: pygame.Surface) -> None:
        self.draw_children(surface)


class HStack(Container):
    def __init__(self, *, spacing: int = 12, padding: int = 0, **kwargs) -> None:
        super().__init__(padding=padding, **kwargs)
        self.spacing = spacing

    def measure(self, max_width: int, max_height: int) -> tuple[int, int]:
        inner_height = max(0, (self.height or max_height) - self.padding * 2)
        children = [child for child in self.children if child.visible]
        widths, heights = [], []
        for child in children:
            cw, ch = child.measure(max(0, max_width - self.padding * 2), inner_height)
            widths.append(child.width if child.width is not None else cw)
            heights.append(ch)
        natural_w = sum(widths) + self.spacing * max(0, len(children) - 1) + self.padding * 2
        natural_h = (max(heights) if heights else 0) + self.padding * 2
        return (self.width or natural_w, self.height or natural_h)

    def arrange(self) -> None:
        if not self.children:
            return
        children = [child for child in self.children if child.visible]
        if not children:
            return
        inner = self.rect.inflate(-self.padding * 2, -self.padding * 2)
        if inner.width <= 0 or inner.height <= 0:
            return
        sizes: list[int] = []
        expands: list[int] = []
        heights: list[int] = []
        for index, child in enumerate(children):
            cw, ch = child.measure(inner.width, inner.height)
            base = child.width if child.width is not None else cw
            sizes.append(max(0, base))
            heights.append(ch)
            if child.expand_x:
                expands.append(index)
        used = sum(sizes) + self.spacing * (len(children) - 1)
        extra = max(0, inner.width - used)
        if expands and extra > 0:
            share = extra // len(expands)
            for index in expands:
                sizes[index] += share
        x = inner.x
        for index, child in enumerate(children):
            width = sizes[index]
            if child.height is not None:
                height = min(child.height, inner.height)
                y = inner.y + (inner.height - height) // 2
            elif child.align_y == "stretch":
                height = inner.height
                y = inner.y
            else:
                height = min(heights[index], inner.height)
                y = inner.y + (inner.height - height) // 2 if child.align_y == "center" else inner.y
                if child.align_y == "bottom":
                    y = inner.bottom - height
            child.layout(pygame.Rect(x, y, max(1, width), max(1, height)))
            x += width + self.spacing

    def draw(self, surface: pygame.Surface) -> None:
        self.draw_children(surface)


class Panel(VStack):
    def __init__(
        self,
        *,
        background=None,
        border=None,
        radius: int | None = None,
        shadow: bool = True,
        gradient: tuple | None = None,
        padding: int = 20,
        spacing: int = 12,
        **kwargs,
    ) -> None:
        super().__init__(spacing=spacing, padding=padding, **kwargs)
        self.background = background if background is not None else self.theme.panel
        self.border = border if border is not None else self.theme.border
        self.radius = self.theme.radius if radius is None else radius
        self.shadow = shadow
        self.gradient = gradient

    def draw(self, surface: pygame.Surface) -> None:
        if not self.visible:
            return
        if self.gradient:
            # shadow is drawn first, then a gradient clipped to the rounded shape
            draw_rounded_rect(surface, self.rect, self.background, self.radius, shadow=self.shadow)
            width, height = self.rect.size
            gradient = pygame.Surface((max(1, width), max(1, height)), pygame.SRCALPHA)
            draw_gradient(gradient, gradient.get_rect(), self.gradient[0], self.gradient[1])
            mask = pygame.Surface((max(1, width), max(1, height)), pygame.SRCALPHA)
            pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=self.radius)
            gradient.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
            surface.blit(gradient, self.rect.topleft)
            self._draw_border(surface)
        else:
            draw_rounded_rect(
                surface,
                self.rect,
                self.background,
                self.radius,
                border=self.border,
                shadow=self.shadow,
            )
        self.draw_decorations(surface)
        self.draw_children(surface)

    def _draw_border(self, surface: pygame.Surface) -> None:
        if not self.border:
            return
        border = pygame.Surface(self.rect.size, pygame.SRCALPHA)
        pygame.draw.rect(
            border,
            color(self.border),
            border.get_rect(),
            width=1,
            border_radius=self.radius,
        )
        surface.blit(border, self.rect.topleft)

    def draw_decorations(self, surface: pygame.Surface) -> None:
        pass


class Card(Panel):
    def __init__(self, title: str | None = None, subtitle: str | None = None, *, child: Widget | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        if title:
            self.add(Label(title, size=15, bold=True))
        if subtitle:
            self.add(Label(subtitle, size=12, color=self.theme.muted))
        if child is not None:
            self.add(child)


class Grid(Container):
    def __init__(self, *, columns: int = 3, spacing: int = 12, padding: int = 0, **kwargs) -> None:
        super().__init__(padding=padding, **kwargs)
        self.columns = max(1, columns)
        self.spacing = spacing

    def _cell_width(self, max_width: int) -> int:
        inner = max_width - self.padding * 2
        return max(1, (inner - self.spacing * (self.columns - 1)) // self.columns)

    def measure(self, max_width: int, max_height: int) -> tuple[int, int]:
        cell_w = self._cell_width(max_width)
        rows = [self.children[i : i + self.columns] for i in range(0, len(self.children), self.columns)]
        height = self.padding * 2
        for row in rows:
            row_h = max((child.height or child.measure(cell_w, max_height)[1] for child in row), default=0)
            height += row_h
        height += self.spacing * max(0, len(rows) - 1)
        return (self.width or (max_width if self.expand_x else cell_w * self.columns + self.spacing * (self.columns - 1) + self.padding * 2), height)

    def arrange(self) -> None:
        cell_w = self._cell_width(self.rect.width)
        inner = self.rect.inflate(-self.padding * 2, -self.padding * 2)
        rows = [self.children[i : i + self.columns] for i in range(0, len(self.children), self.columns)]
        y = inner.y
        for row in rows:
            row_h = max((child.height or child.measure(cell_w, inner.height)[1] for child in row), default=0)
            x = inner.x
            for child in row:
                child.layout(pygame.Rect(x, y, cell_w, max(1, row_h)))
                x += cell_w + self.spacing
            y += row_h + self.spacing

    def draw(self, surface: pygame.Surface) -> None:
        self.draw_children(surface)


class Spacer(Widget):
    def __init__(self, size: int = 0, *, expand: bool = True, horizontal: bool = False) -> None:
        super().__init__(
            width=size if horizontal else None,
            height=size if not horizontal else None,
            expand_x=expand and horizontal,
            expand_y=expand and not horizontal,
            align_x="stretch",
            align_y="stretch",
        )


# ----------------------------------------------------------------------------
# Text and content widgets
# ----------------------------------------------------------------------------


class Label(Widget):
    def __init__(
        self,
        text: str = "",
        *,
        size: int | None = None,
        color_value=None,
        bold: bool = False,
        display: bool = False,
        align: str = "left",
        wrap: bool = True,
        line_height: float = 1.35,
        max_lines: int | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.text = str(text)
        self.size = size or self.theme.font_size
        self.color_value = color(color_value if color_value is not None else self.theme.text)
        self.bold = bold
        self.display = display
        self.align = align
        self.wrap = wrap
        self.line_height = line_height
        self.max_lines = max_lines
        self._font = get_font(self.size, self.bold, self.display)
        self._lines_cache: tuple | None = None

    def _lines(self, width: int) -> list[str]:
        from .utils import wrap_text

        if not self.wrap:
            return [self.text]
        return wrap_text(self._font, self.text, max(1, width))

    def measure(self, max_width: int, max_height: int) -> tuple[int, int]:
        from .utils import wrap_text

        if self.wrap:
            width = self.width or min(max_width, max(1, max((self._font.size(line)[0] for line in self.text.split("\n")), default=0)))
            width = max(30, min(width, max_width))
            lines = wrap_text(self._font, self.text, width)
        else:
            lines = [self.text]
            width = self._font.size(self.text)[0]
        if self.max_lines:
            lines = lines[: self.max_lines]
        height = int(self.size * self.line_height) * max(1, len(lines))
        return (self.width or width, self.height or height)

    def draw(self, surface: pygame.Surface) -> None:
        if not self.visible:
            return
        if not self.wrap:
            image = self._font.render(self.text, True, self.color_value)
            if self.align == "center":
                x = self.rect.centerx - image.get_width() // 2
            elif self.align == "right":
                x = self.rect.right - image.get_width()
            else:
                x = self.rect.x
            surface.blit(image, (x, self.rect.y))
            return
        draw_wrapped_text(
            surface,
            self.text,
            self.rect,
            self.size,
            self.color_value,
            line_height=self.line_height,
            bold=self.bold,
            align=self.align,
            display=self.display,
        )

    def set_text(self, text: str) -> "Label":
        self.text = str(text)
        return self


class Icon(Widget):
    def __init__(self, name: str, *, size: int = 22, color_value=None, **kwargs) -> None:
        super().__init__(width=size, height=size, **kwargs)
        self.name = name
        self.icon_size = size
        self.color_value = color_value or self.theme.text

    def measure(self, max_width: int, max_height: int) -> tuple[int, int]:
        return (self.icon_size, self.icon_size)

    def draw(self, surface: pygame.Surface) -> None:
        draw_icon(surface, self.name, self.rect, self.color_value, max(1, int(self.icon_size / 11)))


class Badge(Widget):
    def __init__(self, text: str, *, background=None, foreground=None, size: int = 12, **kwargs) -> None:
        super().__init__(height=26, align_x="left", **kwargs)
        self.text = text
        self.background = background or with_alpha(self.theme.accent, 28)
        self.foreground = foreground or self.theme.accent
        self.size = size

    def measure(self, max_width: int, max_height: int) -> tuple[int, int]:
        font = get_font(self.size, bold=True)
        return (self.width or font.size(self.text)[0] + 22, self.height or 26)

    def draw(self, surface: pygame.Surface) -> None:
        draw_rounded_rect(surface, self.rect, self.background, self.rect.height // 2)
        font = get_font(self.size, bold=True)
        image = font.render(self.text, True, self.foreground)
        surface.blit(image, image.get_rect(center=self.rect.center))


class Divider(Widget):
    def __init__(self, **kwargs) -> None:
        super().__init__(height=1, **kwargs)

    def draw(self, surface: pygame.Surface) -> None:
        pygame.draw.line(surface, self.theme.border, (self.rect.x, self.rect.centery), (self.rect.right, self.rect.centery))


class ProgressBar(Widget):
    def __init__(self, value: float = 0, *, height: int = 8, color_value=None, background=None, show_value: bool = False, **kwargs) -> None:
        super().__init__(height=height if not show_value else 30, **kwargs)
        self.value = max(0.0, min(100.0, float(value)))
        self._display = self.value
        self.bar_height = height
        self.color_value = color_value or self.theme.accent
        self.background = background or self.theme.panel_alt
        self.show_value = show_value

    def set_value(self, value: float) -> None:
        self.value = max(0.0, min(100.0, float(value)))

    def update(self, dt: float) -> None:
        self._display += (self.value - self._display) * min(1.0, dt * 8)

    def draw(self, surface: pygame.Surface) -> None:
        if not self.visible:
            return
        if self.show_value:
            font = get_font(13, bold=True)
            image = font.render(f"{self._display:.0f}%", True, self.theme.muted)
            surface.blit(image, image.get_rect(topright=(self.rect.right, self.rect.y)))
            bar_rect = pygame.Rect(self.rect.x, self.rect.y + 12, max(1, self.rect.width - 48), self.bar_height)
        else:
            bar_rect = pygame.Rect(self.rect.x, self.rect.centery - self.bar_height // 2, self.rect.width, self.bar_height)
        draw_rounded_rect(surface, bar_rect, self.background, self.bar_height // 2)
        fill_width = int(bar_rect.width * self._display / 100)
        if fill_width > 0:
            draw_rounded_rect(
                surface,
                pygame.Rect(bar_rect.x, bar_rect.y, max(self.bar_height, fill_width), bar_rect.height),
                self.color_value,
                self.bar_height // 2,
            )


class Avatar(Widget):
    def __init__(self, initials: str, *, size: int = 40, background=None, foreground=None, **kwargs) -> None:
        super().__init__(width=size, height=size, align_x="left", **kwargs)
        self.initials = initials[:2].upper()
        self.avatar_size = size
        self.background = background or self.theme.accent_2
        self.foreground = foreground or self.theme.bg

    def measure(self, max_width: int, max_height: int) -> tuple[int, int]:
        return (self.avatar_size, self.avatar_size)

    def draw(self, surface: pygame.Surface) -> None:
        pygame.draw.circle(surface, self.background, self.rect.center, self.rect.width // 2)
        font = get_font(max(10, int(self.rect.width * 0.36)), bold=True)
        image = font.render(self.initials, True, self.foreground)
        surface.blit(image, image.get_rect(center=self.rect.center))


class ImageWidget(Widget):
    def __init__(self, source=None, *, height: int | None = None, radius: int = 14, fit: str = "cover", **kwargs) -> None:
        super().__init__(height=height, **kwargs)
        self.source = source
        self.radius = radius
        self.fit = fit
        self._cache: pygame.Surface | None = None
        self._cache_key = None
        if source is not None:
            try:
                self._source_image = load_image(source)
            except Exception:
                self._source_image = None
        else:
            self._source_image = None

    def measure(self, max_width: int, max_height: int) -> tuple[int, int]:
        if self.height is not None:
            return (self.width or max_width, self.height)
        if self._source_image is not None and self._source_image.get_width() > 0:
            ratio = self._source_image.get_height() / self._source_image.get_width()
            width = self.width or max_width
            return (width, int(width * ratio))
        return (self.width or max_width, 120)

    def _rounded(self, image: pygame.Surface, size: tuple[int, int]) -> pygame.Surface:
        key = (image.get_size(), size, self.radius)
        if self._cache is not None and self._cache_key == key:
            return self._cache
        scaled = pygame.transform.smoothscale(image, size)
        mask = pygame.Surface(size, pygame.SRCALPHA)
        pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=self.radius)
        scaled = scaled.convert_alpha()
        scaled.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        self._cache = scaled
        self._cache_key = key
        return scaled

    def draw(self, surface: pygame.Surface) -> None:
        if not self.visible:
            return
        if self._source_image is None:
            draw_rounded_rect(surface, self.rect, self.theme.panel_alt, self.radius)
            draw_icon(surface, "image", self.rect.inflate(-self.rect.width // 2, -self.rect.height // 2), self.theme.faint)
            return
        source = self._source_image
        target_w, target_h = self.rect.size
        if target_w <= 0 or target_h <= 0:
            return
        src_ratio = source.get_width() / max(1, source.get_height())
        dst_ratio = target_w / max(1, target_h)
        if self.fit == "cover":
            if src_ratio > dst_ratio:
                new_h = source.get_height()
                new_w = int(new_h * dst_ratio)
                crop = pygame.Rect((source.get_width() - new_w) // 2, 0, new_w, new_h)
            else:
                new_w = source.get_width()
                new_h = int(new_w / dst_ratio)
                crop = pygame.Rect(0, (source.get_height() - new_h) // 2, new_w, new_h)
            cropped = source.subsurface(crop).copy()
            image = self._rounded(cropped, (target_w, target_h))
        else:
            image = self._rounded(source, (target_w, target_h))
        surface.blit(image, self.rect.topleft)


# ----------------------------------------------------------------------------
# Interactive widgets
# ----------------------------------------------------------------------------


class Button(Widget):
    def __init__(
        self,
        text: str = "",
        on_click: Callable[[], None] | None = None,
        *,
        variant: str = "primary",
        icon: str | None = None,
        height: int | None = None,
        **kwargs,
    ) -> None:
        # get_theme(), not self.theme: self does not exist yet before
        # super().__init__ runs, and a heightless Button used to crash the
        # whole app with AttributeError.
        super().__init__(height=height or get_theme().button_height, **kwargs)
        self.text = text
        self.on_click = on_click
        self.variant = variant
        self.icon = icon
        self._pressed = False
        self._hover = 0.0
        self._hover_target = 0.0
        self._font = get_font(14 if self.text else 16, bold=True)

    def _palette(self) -> tuple[Any, Any, Any]:
        theme = self.theme
        if self.variant == "primary":
            base = theme.accent
            text = theme.on_accent
            border = mix(theme.accent, (255, 255, 255), 0.13)
        elif self.variant == "danger":
            base = theme.danger
            text = theme.text
            border = mix(theme.danger, (255, 255, 255), 0.12)
        elif self.variant == "secondary":
            base = theme.panel_alt
            text = theme.text
            border = theme.border
        else:
            base = with_alpha(theme.text, 0)
            text = theme.muted
            border = with_alpha(theme.text, 0)
        return base, text, border

    def measure(self, max_width: int, max_height: int) -> tuple[int, int]:
        if self.width is not None:
            return (self.width, self.height or self.theme.button_height)
        if not self.text:
            return (self.height or 44, self.height or 44)
        base, _, _ = self._palette()
        width = 22 * 2 + self._font.size(self.text)[0]
        if self.icon:
            width += 26
        return (max(76, min(width, max_width)), self.height or self.theme.button_height)

    def handle_event(self, event: pygame.event.Event) -> bool:
        if not self.enabled or not self.visible:
            return False
        if event.type == pygame.MOUSEMOTION:
            self.hovered = self.rect.collidepoint(event.pos)
            self._hover_target = 1.0 if self.hovered else 0.0
            if self._pressed and not self.hovered:
                self._pressed = False
            return False
        pos = getattr(event, "pos", None)
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and pos and self.rect.collidepoint(pos):
            self._pressed = True
            return True
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            was = self._pressed
            self._pressed = False
            if was and pos and self.rect.collidepoint(pos):
                self._activate()
                return True
        return False

    def _activate(self) -> None:
        if not self.enabled:
            return
        if self.on_click:
            try:
                self.on_click()
            except Exception as exc:
                print(_tr("[Reasonable UI] Button error “{button}”: {error}", "[Reasonable UI] Ошибка кнопки «{button}»: {error}", button=self.text, error=exc))

    def _blend_factor(self) -> float:
        if not self.enabled:
            return 0.55
        if self._pressed:
            return -0.10
        if self._hover > 0.01:
            return self._hover * 0.12
        return 0.0

    def update(self, dt: float) -> None:
        self._hover += (self._hover_target - self._hover) * min(1.0, dt * 14)

    def draw(self, surface: pygame.Surface) -> None:
        if not self.visible:
            return
        base, text_color, border = self._palette()
        factor = self._blend_factor()
        if factor >= 0:
            fill = mix(base, (255, 255, 255), factor) if factor else base
        else:
            fill = mix(base, (0, 0, 0), -factor)
        rect = self.rect.copy()
        if self._pressed:
            rect.y += 1
        if not self.enabled:
            fill = with_alpha(fill, 120)
            text_color = with_alpha(text_color, 120)
        if self.variant == "primary":
            shadow = pygame.Surface((rect.width + 24, rect.height + 32), pygame.SRCALPHA)
            for i in range(5, 0, -1):
                pygame.draw.rect(
                    shadow,
                    with_alpha(self.theme.accent, 5),
                    pygame.Rect(12 - i * 4, 12 + i * 2, rect.width + i * 8, rect.height + i * 18),
                    border_radius=self.theme.radius_sm + i * 3,
                )
            surface.blit(shadow, (rect.x - 12, rect.y - 8))
        draw_rounded_rect(surface, rect, fill, self.theme.radius_sm, border=border)
        inner_x = rect.x
        text_image = self._font.render(self.text, True, color(text_color))
        content_width = text_image.get_width()
        if self.icon:
            icon_size = 18
            content_width += icon_size + 8
            icon_x = rect.centerx - content_width // 2
            draw_icon(
                surface,
                self.icon,
                pygame.Rect(icon_x, rect.centery - icon_size // 2, icon_size, icon_size),
                text_color,
                2,
            )
            text_x = icon_x + icon_size + 8
        else:
            text_x = rect.centerx - content_width // 2
        surface.blit(text_image, (text_x, rect.centery - text_image.get_height() // 2))

    def set_text(self, text: str) -> "Button":
        self.text = text
        return self


class IconButton(Button):
    def __init__(self, icon: str, on_click: Callable[[], None] | None = None, *, size: int = 42, **kwargs) -> None:
        super().__init__("", on_click, icon=icon, width=size, height=size, align_x="left", **kwargs)
        self.icon_only_size = size

    def measure(self, max_width: int, max_height: int) -> tuple[int, int]:
        return (self.width or self.icon_only_size, self.height or self.icon_only_size)

    def draw(self, surface: pygame.Surface) -> None:
        if not self.visible:
            return
        base, text_color, border = self._palette()
        factor = self._blend_factor()
        fill = mix(base, (255, 255, 255), max(0, factor)) if factor >= 0 else mix(base, (0, 0, 0), -factor)
        rect = self.rect.copy()
        if self.variant == "ghost":
            fill = with_alpha(self.theme.text, int(18 * (self._hover + 0.2))) if (self.hovered or self._hover > 0.02) else with_alpha(self.theme.text, 0)
            border = with_alpha(self.theme.text, 0)
        draw_rounded_rect(surface, rect, fill, self.theme.radius_sm, border=border)
        inset = max(10, rect.width // 4)
        draw_icon(surface, self.icon or "spark", rect.inflate(-inset * 2, -inset * 2), text_color, 2)


class Entry(Widget):
    def __init__(
        self,
        placeholder: str = "",
        *,
        value: str = "",
        password: bool = False,
        on_submit: Callable[[str], None] | None = None,
        on_change: Callable[[str], None] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(height=46, **kwargs)
        self.placeholder = placeholder
        self.value = value
        self.password = password
        self.on_submit = on_submit
        self.on_change = on_change
        self.focused = False
        self.caret = len(value)
        self._blink = 0.0
        self._font = get_font(15)
        self._scroll = 0

    def focus(self) -> None:
        focus_entry(self)

    def _display_value(self) -> str:
        return "•" * len(self.value) if self.password else self.value

    def _caret_pixel(self) -> int:
        display = self._display_value()
        return self._font.size(display[: self.caret])[0]

    def _index_at(self, x: int) -> int:
        display = self._display_value()
        best = 0
        best_distance = 10**9
        for index in range(len(display) + 1):
            distance = abs(self.rect.x + 14 + self._font.size(display[:index])[0] - x - self._scroll)
            if distance < best_distance:
                best_distance = distance
                best = index
        return best

    def _changed(self) -> None:
        if self.on_change:
            try:
                self.on_change(self.value)
            except Exception as exc:
                print(f"[Reasonable UI] on_change: {exc}")

    def handle_event(self, event: pygame.event.Event) -> bool:
        if not self.enabled:
            return False
        if event.type == pygame.MOUSEMOTION:
            self.hovered = self.rect.collidepoint(event.pos)
            return False
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                self.focus()
                self.caret = self._index_at(event.pos[0])
                return True
        if event.type == pygame.KEYDOWN and self.focused:
            ctrl = bool(getattr(event, "mod", 0) & pygame.KMOD_CTRL)
            if event.key == pygame.K_BACKSPACE:
                if ctrl:
                    while self.caret > 0 and self.value[self.caret - 1].isspace():
                        self.caret -= 1
                    while self.caret > 0 and not self.value[self.caret - 1].isspace():
                        self.caret -= 1
                elif self.caret > 0:
                    self.value = self.value[: self.caret - 1] + self.value[self.caret :]
                    self.caret -= 1
                self._changed()
                return True
            if event.key == pygame.K_DELETE:
                if self.caret < len(self.value):
                    self.value = self.value[: self.caret] + self.value[self.caret + 1 :]
                    self._changed()
                return True
            if event.key == pygame.K_LEFT:
                self.caret = max(0, self.caret - 1)
                return True
            if event.key == pygame.K_RIGHT:
                self.caret = min(len(self.value), self.caret + 1)
                return True
            if event.key == pygame.K_HOME:
                self.caret = 0
                return True
            if event.key == pygame.K_END:
                self.caret = len(self.value)
                return True
            if event.key == pygame.K_RETURN:
                if self.on_submit:
                    try:
                        self.on_submit(self.value)
                    except Exception as exc:
                        print(f"[Reasonable UI] on_submit: {exc}")
                return True
            if event.key == pygame.K_ESCAPE:
                self.focused = False
                return True
            if ctrl and event.key == pygame.K_v:
                self._paste()
                return True
            if event.unicode and event.unicode.isprintable() and not ctrl:
                if len(self.value) < 4000:
                    self.value = self.value[: self.caret] + event.unicode + self.value[self.caret :]
                    self.caret += len(event.unicode)
                    self._changed()
                return True
        return False

    def _paste(self) -> None:
        try:
            if not pygame.scrap.get_init():
                pygame.scrap.init()
            data = pygame.scrap.get(pygame.SCRAP_TEXT)
            if data:
                text = data.decode("utf-8", errors="ignore").replace("\x00", "").replace("\r", " ").replace("\n", " ")
                if text:
                    self.value = self.value[: self.caret] + text + self.value[self.caret :]
                    self.caret += len(text)
                    self._changed()
        except Exception as exc:
            print(_tr("[Reasonable UI] Clipboard is unavailable: {error}", "[Reasonable UI] Буфер обмена недоступен: {error}", error=exc))

    def update(self, dt: float) -> None:
        self._blink += dt
        if self.focused:
            display = self._display_value()
            caret_x = self._font.size(display[: self.caret])[0]
            width = max(1, self.rect.width - 28)
            if caret_x - self._scroll > width:
                self._scroll = caret_x - width
            if caret_x - self._scroll < 0:
                self._scroll = caret_x
            self._scroll = max(0, self._scroll)
        else:
            self._scroll = 0

    def draw(self, surface: pygame.Surface) -> None:
        if not self.visible:
            return
        border_color = self.theme.accent if self.focused else self.theme.border
        draw_rounded_rect(surface, self.rect, self.theme.panel_alt, self.theme.radius_sm, border=border_color)
        inner = self.rect.inflate(-26, 0)
        display = self._display_value()
        if not display:
            image = self._font.render(self.placeholder, True, self.theme.faint)
            surface.blit(image, (self.rect.x + 14, self.rect.centery - image.get_height() // 2))
        else:
            old_clip = surface.get_clip()
            surface.set_clip(inner)
            image = self._font.render(display, True, self.theme.text)
            surface.blit(image, (self.rect.x + 14 - self._scroll, self.rect.centery - image.get_height() // 2))
            if self.focused and int(self._blink * 2) % 2 == 0:
                caret_x = self.rect.x + 14 + self._caret_pixel() - self._scroll
                pygame.draw.line(surface, self.theme.accent, (caret_x, self.rect.y + 12), (caret_x, self.rect.bottom - 12), 2)
            surface.set_clip(old_clip)

    def set_value(self, value: str) -> "Entry":
        self.value = value
        self.caret = len(value)
        return self


class Toggle(Widget):
    def __init__(self, value: bool = False, on_change: Callable[[bool], None] | None = None, **kwargs) -> None:
        super().__init__(width=54, height=30, align_x="left", **kwargs)
        self.value = bool(value)
        self.on_change = on_change
        self._position = 1.0 if self.value else 0.0

    def measure(self, max_width: int, max_height: int) -> tuple[int, int]:
        return (54, 30)

    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.MOUSEMOTION:
            self.hovered = self.rect.collidepoint(event.pos)
            return False
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self.rect.collidepoint(event.pos):
            self.value = not self.value
            if self.on_change:
                try:
                    self.on_change(self.value)
                except Exception as exc:
                    print(f"[Reasonable UI] toggle: {exc}")
            return True
        return False

    def update(self, dt: float) -> None:
        target = 1.0 if self.value else 0.0
        self._position += (target - self._position) * min(1.0, dt * 14)

    def draw(self, surface: pygame.Surface) -> None:
        if not self.visible:
            return
        track = self.theme.accent if self.value else self.theme.panel_alt
        track = mix(track, (255, 255, 255), 0.06 if self.hovered else 0)
        draw_rounded_rect(surface, self.rect, track, self.rect.height // 2, border=self.theme.border if not self.value else None)
        knob_x = int(self.rect.x + 15 + (self.rect.width - 30) * self._position)
        pygame.draw.circle(surface, self.theme.text, (knob_x, self.rect.centery), 11)
        if self.value:
            draw_icon(surface, "check", pygame.Rect(knob_x - 6, self.rect.centery - 6, 12, 12), self.theme.accent, 2)


class Slider(Widget):
    def __init__(self, value: float = 0.5, on_change: Callable[[float], None] | None = None, *, show_value: bool = True, **kwargs) -> None:
        super().__init__(height=40, **kwargs)
        self.value = max(0.0, min(1.0, float(value)))
        self.on_change = on_change
        self.show_value = show_value
        self._dragging = False

    def _set_from_x(self, x: int) -> None:
        track_left = self.rect.x
        track_right = self.rect.right - (46 if self.show_value else 0)
        self.value = max(0.0, min(1.0, (x - track_left) / max(1, track_right - track_left)))
        if self.on_change:
            try:
                self.on_change(self.value)
            except Exception as exc:
                print(f"[Reasonable UI] slider: {exc}")

    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.MOUSEMOTION:
            self.hovered = self.rect.collidepoint(event.pos)
            if self._dragging:
                self._set_from_x(event.pos[0])
                return True
            return False
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and self.rect.collidepoint(event.pos):
            self._dragging = True
            self._set_from_x(event.pos[0])
            return True
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self._dragging:
            self._dragging = False
            return True
        return False

    def draw(self, surface: pygame.Surface) -> None:
        if not self.visible:
            return
        right = self.rect.right - (46 if self.show_value else 0)
        center_y = self.rect.centery
        pygame.draw.line(surface, self.theme.panel_alt, (self.rect.x, center_y), (right, center_y), 6)
        filled = int((right - self.rect.x) * self.value)
        if filled > 0:
            pygame.draw.line(surface, self.theme.accent, (self.rect.x, center_y), (self.rect.x + filled, center_y), 6)
        knob_x = self.rect.x + filled
        glow = self.theme.accent if (self.hovered or self._dragging) else self.theme.text
        pygame.draw.circle(surface, with_alpha(glow, 35), (knob_x, center_y), 14)
        pygame.draw.circle(surface, self.theme.text, (knob_x, center_y), 8)
        pygame.draw.circle(surface, self.theme.accent, (knob_x, center_y), 8, 2)
        if self.show_value:
            font = get_font(13, bold=True)
            image = font.render(f"{self.value:.0%}", True, self.theme.muted)
            surface.blit(image, image.get_rect(midright=(self.rect.right, center_y)))


class ScrollView(Container):
    def __init__(self, content: Widget | None = None, *, padding: int = 0, stick_to_bottom: bool = False, **kwargs) -> None:
        super().__init__(padding=padding, **kwargs)
        self.content = content
        if content is not None:
            self.add(content)
        self.scroll = 0.0
        self.target_scroll = 0.0
        self.stick_to_bottom = stick_to_bottom
        self._max_scroll = 0.0
        self._bar_dragging = False

    def add(self, *widgets: Widget) -> "ScrollView":
        super().add(*widgets)
        if self.content is None and widgets:
            self.content = widgets[0]
        return self

    def measure(self, max_width: int, max_height: int) -> tuple[int, int]:
        if self.height is not None:
            return (self.width or max_width, self.height)
        if self.content is not None:
            _, h = self.content.measure(max_width - self.padding * 2, 100000)
            return (self.width or max_width, h + self.padding * 2)
        return (self.width or max_width, self.height or 100)

    def layout(self, rect) -> None:
        super().layout(rect)
        self._layout_content()

    def _layout_content(self) -> None:
        if self.content is None:
            return
        inner = self.rect.inflate(-self.padding * 2, -self.padding * 2)
        if inner.height <= 0:
            return
        _, content_height = self.content.measure(inner.width, 100000)
        content_height = max(content_height, inner.height)
        self._max_scroll = max(0.0, content_height - inner.height)
        if self.stick_to_bottom and self.target_scroll >= self._max_scroll - 2:
            self.target_scroll = self._max_scroll
        self.target_scroll = max(0.0, min(self._max_scroll, self.target_scroll))
        self.content.layout(
            pygame.Rect(inner.x, int(inner.y - self.scroll), inner.width, int(content_height))
        )

    def update(self, dt: float) -> None:
        self.scroll += (self.target_scroll - self.scroll) * min(1.0, dt * 16)
        if abs(self.target_scroll - self.scroll) < 0.3:
            self.scroll = self.target_scroll
        if self.content is not None:
            self.content.update(dt)

    def scroll_to_bottom(self) -> None:
        self.target_scroll = 10**9

    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.MOUSEWHEEL:
            # Wheel events have no `pos`; fall back to the cursor position.
            pos = event_pos(event)
            if pos is None or self.rect.collidepoint(pos):
                self.target_scroll = max(0.0, min(self._max_scroll, self.target_scroll - event.y * 52))
                return True
            return False
        if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION) and hasattr(event, "pos"):
            if event.type == pygame.MOUSEMOTION:
                self.hovered = self.rect.collidepoint(event.pos)
                if self.content is not None:
                    self.content.handle_event(event)
                return False
            if not self.rect.collidepoint(event.pos):
                return False
            if self.content is not None and self.content.handle_event(event):
                return True
            return False
        if self.content is not None:
            return self.content.handle_event(event)
        return False

    def draw(self, surface: pygame.Surface) -> None:
        if not self.visible:
            return
        old_clip = surface.get_clip()
        surface.set_clip(self.rect.clip(old_clip) if old_clip else self.rect)
        if self.content is not None:
            self.content.draw(surface)
        surface.set_clip(old_clip)
        if self._max_scroll > 0:
            track_x = self.rect.right - 5
            track = pygame.Rect(track_x - 2, self.rect.y + 4, 4, max(1, self.rect.height - 8))
            draw_rounded_rect(surface, track, with_alpha(self.theme.border, 150), 2)
            ratio = self.rect.height / (self.rect.height + self._max_scroll)
            thumb_h = max(32, int(self.rect.height * ratio))
            travel = max(1, self.rect.height - thumb_h - 8)
            thumb_y = self.rect.y + 4 + int((self.scroll / self._max_scroll) * travel)
            draw_rounded_rect(surface, pygame.Rect(track.x, thumb_y, 4, thumb_h), self.theme.muted, 2)


class Tabs(Widget):
    def __init__(self, *, height: int | None = None, on_change: Callable[[int], None] | None = None, **kwargs) -> None:
        super().__init__(height=height, **kwargs)
        self.tabs: list[tuple[str, Widget]] = []
        self.active = 0
        self.bar_height = 48
        self.on_change = on_change

    def add_tab(self, title: str, widget: Widget) -> "Tabs":
        widget.parent = self
        self.tabs.append((title, widget))
        return self

    def measure(self, max_width: int, max_height: int) -> tuple[int, int]:
        content_h = 0
        if self.tabs:
            _, content_h = self.tabs[self.active][1].measure(max_width, max(0, max_height - self.bar_height))
        return (self.width or max_width, self.height or (self.bar_height + content_h))

    def layout(self, rect) -> None:
        super().layout(rect)
        content_rect = pygame.Rect(self.rect.x, self.rect.y + self.bar_height, self.rect.width, max(1, self.rect.height - self.bar_height))
        for _, widget in self.tabs:
            widget.layout(content_rect)

    def on_mount(self) -> None:
        for _, widget in self.tabs:
            widget.on_mount()

    def update(self, dt: float) -> None:
        if self.tabs:
            self.tabs[self.active][1].update(dt)

    def _tab_rects(self) -> list[pygame.Rect]:
        if not self.tabs:
            return []
        width = self.rect.width // len(self.tabs)
        rects = []
        for index in range(len(self.tabs)):
            rects.append(pygame.Rect(self.rect.x + index * width, self.rect.y, width, self.bar_height))
        rects[-1].width = self.rect.right - rects[-1].x
        return rects

    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.MOUSEMOTION:
            self.hovered = self.rect.collidepoint(event.pos)
            if self.tabs:
                self.tabs[self.active][1].handle_event(event)
            return False
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            for index, rect in enumerate(self._tab_rects()):
                if rect.collidepoint(event.pos):
                    if index != self.active:
                        self.active = index
                        if self.on_change:
                            try:
                                self.on_change(index)
                            except Exception:
                                pass
                    return True
        if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP) and hasattr(event, "pos"):
            if self.rect.collidepoint(event.pos) and event.pos[1] < self.rect.y + self.bar_height:
                return True
        if self.tabs:
            return self.tabs[self.active][1].handle_event(event)
        return False

    def draw(self, surface: pygame.Surface) -> None:
        if not self.visible:
            return
        draw_rounded_rect(surface, pygame.Rect(self.rect.x, self.rect.y, self.rect.width, self.bar_height), self.theme.panel_alt, self.theme.radius_sm, border=self.theme.border)
        mouse = pygame.mouse.get_pos()
        for index, (title, _) in enumerate(self.tabs):
            rect = self._tab_rects()[index].inflate(-8, -8)
            active = index == self.active
            if active:
                draw_rounded_rect(surface, rect, self.theme.panel, self.theme.radius_sm, border=None)
                pygame.draw.rect(surface, self.theme.accent, pygame.Rect(rect.x + 12, rect.bottom - 3, rect.width - 24, 3), border_radius=2)
            elif rect.collidepoint(mouse):
                draw_rounded_rect(surface, rect, with_alpha(self.theme.text, 10), self.theme.radius_sm)
            font = get_font(14, bold=active)
            image = font.render(title, True, self.theme.text if active else self.theme.muted)
            surface.blit(image, image.get_rect(center=rect.center))
        if self.tabs:
            self.tabs[self.active][1].draw(surface)


# ----------------------------------------------------------------------------
# Backwards-friendly aliases
# ----------------------------------------------------------------------------


Row = HStack
Column = VStack
Text = Label


def make_root(*children: Widget, padding: int = 24, spacing: int = 16) -> Panel:
    root = Panel(padding=padding, spacing=spacing, shadow=False)
    root.add(*children)
    return root
