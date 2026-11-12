"""Scene graph, sprites, camera, particles and tweening for 2D games."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import pygame

try:
    from reasonable.core.i18n import tr as _tr
except Exception:  # exported builds may run without the bundled core package
    def _tr(en: str, ru: str, **values) -> str:
        return en

from .utils import (
    EASINGS,
    color,
    get_font,
    load_image,
    mix,
    render_text,
    tint_surface,
    with_alpha,
)


class Camera:
    def __init__(self, screen_size: tuple[int, int] = (960, 540), pos=(0, 0), zoom: float = 1.0) -> None:
        self.screen_size = pygame.Vector2(screen_size)
        self.pos = pygame.Vector2(pos)
        self.zoom = zoom
        self.target = None
        self.smooth = 0.12
        self.bounds: pygame.Rect | None = None
        self._shake = 0.0
        self._shake_time = 0.0
        self._shake_duration = 0.0
        self.offset = pygame.Vector2(0, 0)
        self.lookahead = 0.0

    def resize(self, size: tuple[int, int]) -> None:
        self.screen_size.update(size)

    def update(self, dt: float) -> None:
        if self.target is not None:
            goal = pygame.Vector2(self.target[0], self.target[1]) if not hasattr(self.target, "x") else pygame.Vector2(self.target.x, self.target.y)
            velocity = getattr(self.target, "velocity", None)
            if velocity is not None and self.lookahead:
                goal += pygame.Vector2(velocity) * self.lookahead
            alpha = 1 - (1 - max(0.0, min(1.0, self.smooth))) ** max(0.01, dt * 60)
            self.pos += (goal - self.pos) * alpha
        if self.bounds is not None:
            half_w = self.screen_size.x / max(0.01, self.zoom) / 2
            half_h = self.screen_size.y / max(0.01, self.zoom) / 2
            left = self.bounds.left + half_w
            right = self.bounds.right - half_w
            top = self.bounds.top + half_h
            bottom = self.bounds.bottom - half_h
            if left <= right:
                self.pos.x = max(left, min(right, self.pos.x))
            else:
                self.pos.x = self.bounds.centerx
            if top <= bottom:
                self.pos.y = max(top, min(bottom, self.pos.y))
            else:
                self.pos.y = self.bounds.centery
        if self._shake_time > 0:
            self._shake_time = max(0.0, self._shake_time - dt)
            progress = self._shake_time / max(0.001, self._shake_duration)
            amount = self._shake * progress
            self.offset.update(random.uniform(-amount, amount), random.uniform(-amount, amount))
        else:
            self.offset.update(0, 0)

    def shake(self, intensity: float = 8.0, duration: float = 0.25) -> None:
        self._shake = max(self._shake, intensity)
        self._shake_time = max(self._shake_time, duration)
        self._shake_duration = max(self._shake_duration, duration)
        if self._shake_time <= 0:
            self._shake_duration = duration

    def world_to_screen(self, position) -> pygame.Vector2:
        point = pygame.Vector2(position)
        return (point - self.pos) * self.zoom + self.screen_size / 2 + self.offset

    def screen_to_world(self, position) -> pygame.Vector2:
        point = pygame.Vector2(position)
        return (point - self.screen_size / 2 - self.offset) / max(0.001, self.zoom) + self.pos


class Node:
    def __init__(self, x: float = 0, y: float = 0, z: int = 0) -> None:
        self.x = float(x)
        self.y = float(y)
        self.z = z
        self.angle = 0.0
        self.scale = pygame.Vector2(1, 1)
        self.visible = True
        self.alpha = 255
        self.tags: set[str] = set()
        self.alive = True
        self.scene = None

    @property
    def pos(self) -> pygame.Vector2:
        return pygame.Vector2(self.x, self.y)

    @pos.setter
    def pos(self, value) -> None:
        self.x, self.y = float(value[0]), float(value[1])

    def set_pos(self, x: float, y: float) -> "Node":
        self.x, self.y = float(x), float(y)
        return self

    def add_tag(self, *tags: str) -> "Node":
        self.tags.update(tags)
        return self

    def has_tag(self, tag: str) -> bool:
        return tag in self.tags

    def kill(self) -> None:
        self.alive = False

    def update(self, dt: float) -> None:
        pass

    def draw(self, surface: pygame.Surface, camera: Camera) -> None:
        pass


class Sprite(Node):
    def __init__(
        self,
        image,
        x: float = 0,
        y: float = 0,
        *,
        scale: float | tuple[float, float] = 1.0,
        angle: float = 0.0,
        anchor: tuple[float, float] = (0.5, 0.5),
        z: int = 0,
        opacity: int = 255,
    ) -> None:
        super().__init__(x, y, z)
        self._source = load_image(image)
        self.image_path = image if isinstance(image, str) else None
        self.anchor = anchor
        if isinstance(scale, (int, float)):
            self.scale.update(float(scale), float(scale))
        else:
            self.scale.update(float(scale[0]), float(scale[1]))
        self.angle = float(angle)
        self.alpha = opacity
        self.flip_x = False
        self.flip_y = False
        self.tint = None
        self.shadow = False
        self.shadow_color = (0, 0, 0, 70)
        # Scaled/rotated/tinted variants are expensive to rebuild every frame.
        # A small bounded cache makes camera zoom and fade-ins cheap, which
        # matters most on Android. Keyed by every visual input, so property
        # changes produce a new entry instead of a stale image.
        self._draw_cache: dict[tuple, tuple[pygame.Surface, pygame.Surface | None]] = {}
        self._draw_cache_pixels = 0

    @property
    def image(self) -> pygame.Surface:
        return self._source

    @image.setter
    def image(self, value) -> None:
        self._source = load_image(value)
        self._draw_cache.clear()
        self._draw_cache_pixels = 0

    @property
    def width(self) -> float:
        return self._source.get_width() * abs(self.scale.x)

    @property
    def height(self) -> float:
        return self._source.get_height() * abs(self.scale.y)

    @property
    def rect(self) -> pygame.Rect:
        width = self.width
        height = self.height
        left = self.x - self.anchor[0] * width
        top = self.y - self.anchor[1] * height
        return pygame.Rect(round(left), round(top), round(width), round(height))

    def collide(self, other) -> bool:
        other_rect = getattr(other, "rect", other)
        return self.rect.colliderect(other_rect)

    def draw(self, surface: pygame.Surface, camera: Camera) -> None:
        if not self.visible:
            return
        tint_key = tuple(self.tint) if isinstance(self.tint, (list, tuple)) else self.tint
        shadow_key = (
            tuple(self.shadow_color)
            if isinstance(self.shadow_color, (list, tuple))
            else self.shadow_color
        )
        key = (
            self.flip_x,
            self.flip_y,
            tint_key,
            round(float(self.scale.x), 3),
            round(float(self.scale.y), 3),
            round(float(self.angle), 2),
            int(self.alpha),
            round(float(camera.zoom), 3),
            bool(self.shadow),
            shadow_key,
        )
        cached = self._draw_cache.get(key)
        if cached is None:
            cached = self._render_draw_image(camera.zoom)
            area = cached[0].get_width() * cached[0].get_height()
            if cached[1] is not None:
                area += cached[1].get_width() * cached[1].get_height()
            # Keep the cache small enough for mobile memory: eight entries and
            # roughly 16 megapixels of decoded surfaces in total.
            while self._draw_cache and (
                len(self._draw_cache) >= 8
                or self._draw_cache_pixels + area > 16_000_000
            ):
                old_key = next(iter(self._draw_cache))
                old_image, old_shadow = self._draw_cache.pop(old_key)
                self._draw_cache_pixels -= old_image.get_width() * old_image.get_height()
                if old_shadow is not None:
                    self._draw_cache_pixels -= old_shadow.get_width() * old_shadow.get_height()
            self._draw_cache[key] = cached
            self._draw_cache_pixels += area
        image, shadow = cached
        screen = camera.world_to_screen((self.x, self.y))
        rect = image.get_rect()
        setattr(rect, "center", (int(screen.x), int(screen.y)))
        if self.anchor != (0.5, 0.5):
            rect.left = int(screen.x - self.anchor[0] * image.get_width())
            rect.top = int(screen.y - self.anchor[1] * image.get_height())
        if shadow is not None:
            surface.blit(shadow, (rect.centerx - shadow.get_width() // 2, rect.bottom - shadow.get_height() // 2))
        surface.blit(image, rect)

    def _render_draw_image(
        self, zoom: float
    ) -> tuple[pygame.Surface, pygame.Surface | None]:
        image = self._source
        if self.flip_x or self.flip_y:
            image = pygame.transform.flip(image, self.flip_x, self.flip_y)
        if self.tint:
            image = tint_surface(image, self.tint, 255)
        effective_scale_x = self.scale.x * zoom
        effective_scale_y = self.scale.y * zoom
        if abs(effective_scale_x - 1) > 0.001 or abs(effective_scale_y - 1) > 0.001:
            width = max(1, int(abs(image.get_width() * effective_scale_x)))
            height = max(1, int(abs(image.get_height() * effective_scale_y)))
            image = pygame.transform.smoothscale(image, (width, height))
        if abs(self.angle) > 0.01:
            image = pygame.transform.rotozoom(image, -self.angle, 1.0)
        if self.alpha < 255:
            image = image.copy()
            image.set_alpha(int(self.alpha))
        shadow = None
        if self.shadow:
            shadow = pygame.Surface(
                (int(image.get_width() * 0.8), max(3, int(image.get_height() * 0.2))),
                pygame.SRCALPHA,
            )
            pygame.draw.ellipse(shadow, self.shadow_color, shadow.get_rect())
        return image, shadow


def make_circle_surface(
    radius: int,
    fill,
    *,
    border=None,
    border_width: int = 0,
    glow=None,
) -> pygame.Surface:
    size = radius * 2 + (8 if glow else 0)
    surface = pygame.Surface((size, size), pygame.SRCALPHA)
    center = (size // 2, size // 2)
    if glow:
        for layer in range(6, 0, -1):
            alpha = int(24 * (1 - layer / 7))
            pygame.draw.circle(surface, with_alpha(glow, alpha), center, int(radius * (1 + layer * 0.09)))
    pygame.draw.circle(surface, color(fill), center, radius)
    if border:
        pygame.draw.circle(surface, color(border), center, radius, max(1, border_width or 1))
    return surface


def make_rect_surface(
    width: int,
    height: int,
    fill,
    *,
    border=None,
    border_width: int = 0,
    radius: int = 0,
) -> pygame.Surface:
    surface = pygame.Surface((width + 8, height + 8), pygame.SRCALPHA)
    rect = pygame.Rect(4, 4, width, height)
    pygame.draw.rect(surface, color(fill), rect, border_radius=radius)
    if border:
        pygame.draw.rect(surface, color(border), rect, width=max(1, border_width or 1), border_radius=radius)
    return surface


class AnimatedSprite(Sprite):
    def __init__(
        self,
        frames: Sequence,
        x: float = 0,
        y: float = 0,
        *,
        fps: float = 10,
        loop: bool = True,
        autoplay: bool = True,
        **kwargs,
    ) -> None:
        self.frames = [load_image(frame) for frame in frames] or [load_image(None)]
        super().__init__(self.frames[0], x, y, **kwargs)
        self.fps = fps
        self.loop = loop
        self.playing = autoplay
        self.frame_index = 0
        self._elapsed = 0.0
        self.finished = False

    def play(self, fps: float | None = None, loop: bool | None = None) -> None:
        if fps is not None:
            self.fps = fps
        if loop is not None:
            self.loop = loop
        self.playing = True
        self.finished = False
        self._elapsed = 0

    def stop(self) -> None:
        self.playing = False

    def update(self, dt: float) -> None:
        if not self.playing or len(self.frames) <= 1 or self.fps <= 0:
            return
        self._elapsed += dt
        frame_time = 1.0 / self.fps
        while self._elapsed >= frame_time:
            self._elapsed -= frame_time
            next_index = self.frame_index + 1
            if next_index >= len(self.frames):
                if self.loop:
                    next_index = 0
                else:
                    next_index = len(self.frames) - 1
                    self.playing = False
                    self.finished = True
                    break
            self.frame_index = next_index
        self._source = self.frames[self.frame_index]


class Text(Node):
    def __init__(
        self,
        text: str,
        x: float = 0,
        y: float = 0,
        *,
        size: int = 24,
        color_value=(244, 247, 251),
        bold: bool = False,
        display: bool = False,
        shadow: bool = False,
        letter_spacing: int = 0,
        anchor: str = "topleft",
        z: int = 0,
    ) -> None:
        super().__init__(x, y, z)
        self.text = str(text)
        self.size = size
        self.color_value = color(color_value)
        self.bold = bold
        self.display = display
        self.shadow = shadow
        self.letter_spacing = letter_spacing
        self.anchor = anchor
        self._cache: pygame.Surface | None = None
        self._cache_key = None
        self._draw_cache: dict[tuple, pygame.Surface] = {}

    def set_text(self, text: str) -> "Text":
        if text != self.text:
            self.text = str(text)
            self._cache = None
        return self

    def _render(self) -> pygame.Surface:
        key = (self.text, self.size, tuple(self.color_value), self.bold, self.display, self.shadow, self.letter_spacing)
        if self._cache is None or key != self._cache_key:
            self._cache = render_text(
                self.text,
                self.size,
                self.color_value,
                bold=self.bold,
                display=self.display,
                shadow=self.shadow,
                letter_spacing=self.letter_spacing,
            )
            self._cache_key = key
            # Any change of text/colour invalidates the zoomed variants too.
            self._draw_cache.clear()
        return self._cache

    @property
    def width(self) -> int:
        return self._render().get_width()

    @property
    def height(self) -> int:
        return self._render().get_height()

    def draw(self, surface: pygame.Surface, camera: Camera) -> None:
        if not self.visible or not self.text:
            return
        image = self._render()
        zoom = round(float(camera.zoom), 3)
        cache_key = (zoom, int(self.alpha))
        cached = self._draw_cache.get(cache_key)
        if cached is None:
            cached = image
            if self.alpha < 255:
                cached = cached.copy()
                cached.set_alpha(self.alpha)
            if abs(zoom - 1) > 0.01:
                cached = pygame.transform.smoothscale(
                    cached,
                    (max(1, round(cached.get_width() * zoom)), max(1, round(cached.get_height() * zoom))),
                )
            if len(self._draw_cache) >= 4:
                self._draw_cache.pop(next(iter(self._draw_cache)))
            self._draw_cache[cache_key] = cached
        image = cached
        screen = camera.world_to_screen((self.x, self.y))
        rect = image.get_rect()
        setattr(rect, self.anchor, (int(screen.x), int(screen.y)))
        surface.blit(image, rect)


class Shape(Node):
    def __init__(
        self,
        shape: str,
        x: float = 0,
        y: float = 0,
        *,
        size: tuple[float, float] = (40, 40),
        fill=(255, 107, 74),
        border=None,
        border_width: int = 0,
        radius: int = 0,
        points: Sequence[tuple[float, float]] | None = None,
        z: int = 0,
    ) -> None:
        super().__init__(x, y, z)
        self.shape = shape
        self.size = pygame.Vector2(size)
        self.fill = fill
        self.border = border
        self.border_width = border_width
        self.radius = radius
        self.points = list(points or [])

    def draw(self, surface: pygame.Surface, camera: Camera) -> None:
        if not self.visible:
            return
        screen = camera.world_to_screen((self.x, self.y))
        zoom = camera.zoom
        width = self.size.x * abs(self.scale.x) * zoom
        height = self.size.y * abs(self.scale.y) * zoom
        fill = with_alpha(self.fill, self.alpha) if self.alpha < 255 else self.fill
        border = self.border
        if self.shape == "rect":
            rect = pygame.Rect(int(screen.x - width / 2), int(screen.y - height / 2), max(1, int(width)), max(1, int(height)))
            pygame.draw.rect(surface, fill, rect, border_radius=int(self.radius * zoom))
            if border:
                pygame.draw.rect(surface, border, rect, width=self.border_width, border_radius=int(self.radius * zoom))
        elif self.shape == "circle":
            pygame.draw.circle(surface, fill, (int(screen.x), int(screen.y)), max(1, int(min(width, height) / 2)))
            if border:
                pygame.draw.circle(surface, border, (int(screen.x), int(screen.y)), max(1, int(min(width, height) / 2)), self.border_width)
        elif self.shape == "line":
            pygame.draw.line(
                surface,
                fill,
                (screen.x - width / 2, screen.y - height / 2),
                (screen.x + width / 2, screen.y + height / 2),
                max(1, int(self.border_width or 2)),
            )
        elif self.shape == "polygon":
            pts = [(screen.x + px * zoom * self.scale.x, screen.y + py * zoom * self.scale.y) for px, py in self.points]
            if len(pts) >= 3:
                pygame.draw.polygon(surface, fill, pts)
                if border:
                    pygame.draw.polygon(surface, border, pts, self.border_width)


@dataclass
class _Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    max_life: float
    size: float
    color: pygame.Color
    gravity: float
    drag: float
    additive: bool
    angle: float = 0
    spin: float = 0
    shape: str = "circle"


class ParticleSystem(Node):
    def __init__(self, x: float = 0, y: float = 0, z: int = 50) -> None:
        super().__init__(x, y, z)
        self.particles: list[_Particle] = []
        self.emitting = False
        self.emit_rate = 28.0
        self.emit_accumulator = 0.0
        self.emit_defaults: dict[str, Any] = {}

    def burst(
        self,
        origin: tuple[float, float] | None = None,
        count: int = 24,
        *,
        colors: Iterable = ((255, 107, 74), (255, 200, 87), (53, 214, 196)),
        speed: tuple[float, float] = (40, 220),
        size: tuple[float, float] = (2, 5),
        life: tuple[float, float] = (0.25, 0.9),
        gravity: float = 0,
        drag: float = 0.98,
        angle: tuple[float, float] = (0, 360),
        additive: bool = True,
        shape: str = "circle",
        spread: float = 0,
    ) -> None:
        ox, oy = origin if origin is not None else (self.x, self.y)
        palette = [color(item) for item in colors]
        for _ in range(max(0, count)):
            theta = math.radians(random.uniform(*angle))
            if spread:
                theta = random.uniform(0, math.tau)
            velocity = random.uniform(*speed)
            lifespan = random.uniform(*life)
            self.particles.append(
                _Particle(
                    x=ox + random.uniform(-3, 3),
                    y=oy + random.uniform(-3, 3),
                    vx=math.cos(theta) * velocity,
                    vy=math.sin(theta) * velocity,
                    life=lifespan,
                    max_life=lifespan,
                    size=random.uniform(*size),
                    color=random.choice(palette),
                    gravity=gravity,
                    drag=drag,
                    additive=additive,
                    angle=random.uniform(0, 360),
                    spin=random.uniform(-360, 360),
                    shape=shape,
                )
            )

    def emit(self, rate: float = 24, **defaults) -> None:
        self.emitting = True
        self.emit_rate = rate
        self.emit_defaults = defaults

    def stop(self, fade: bool = True) -> None:
        self.emitting = False
        if not fade:
            self.particles.clear()

    def update(self, dt: float) -> None:
        if self.emitting:
            self.emit_accumulator += dt * self.emit_rate
            while self.emit_accumulator >= 1:
                self.emit_accumulator -= 1
                self.burst(count=1, **self.emit_defaults)
        alive = []
        for particle in self.particles:
            particle.life -= dt
            if particle.life <= 0:
                continue
            particle.vy += particle.gravity * dt
            damping = particle.drag ** (dt * 60)
            particle.vx *= damping
            particle.vy *= damping
            particle.x += particle.vx * dt
            particle.y += particle.vy * dt
            particle.angle += particle.spin * dt
            alive.append(particle)
        self.particles = alive[-1200:]

    def draw(self, surface: pygame.Surface, camera: Camera) -> None:
        if not self.visible:
            return
        for particle in self.particles:
            ratio = max(0.0, min(1.0, particle.life / max(0.001, particle.max_life)))
            screen = camera.world_to_screen((particle.x, particle.y))
            radius = max(0.6, particle.size * ratio * camera.zoom)
            c = with_alpha(particle.color, int(255 * ratio))
            if particle.additive:
                glow_radius = radius * 2.6
                glow = pygame.Surface((int(glow_radius * 2 + 2), int(glow_radius * 2 + 2)), pygame.SRCALPHA)
                pygame.draw.circle(glow, with_alpha(c, int(54 * ratio)), (int(glow_radius + 1), int(glow_radius + 1)), int(glow_radius))
                surface.blit(glow, (screen.x - glow_radius, screen.y - glow_radius))
            if particle.shape == "square":
                rect = pygame.Rect(0, 0, int(radius * 2), int(radius * 2))
                rect.center = (int(screen.x), int(screen.y))
                pygame.draw.rect(surface, c, rect)
            else:
                pygame.draw.circle(surface, c, (int(screen.x), int(screen.y)), max(1, int(radius)))


class TweenManager:
    def __init__(self) -> None:
        self._tweens: list[dict[str, Any]] = []
        self._timers: list[dict[str, Any]] = []

    def to(
        self,
        target: Any,
        attr: str,
        value: Any,
        duration: float = 0.4,
        *,
        easing: str = "out_cubic",
        delay: float = 0.0,
        loop: bool = False,
        yoyo: bool = False,
        on_complete: Callable[[], None] | None = None,
    ) -> "TweenManager":
        start = getattr(target, attr)
        self._tweens.append(
            {
                "target": target,
                "attr": attr,
                "start": start.copy() if isinstance(start, pygame.Vector2) else start,
                "end": value,
                "duration": max(0.001, duration),
                "elapsed": 0.0,
                "delay": delay,
                "easing": EASINGS.get(easing, EASINGS["out_cubic"]),
                "loop": loop,
                "yoyo": yoyo,
                "direction": 1,
                "on_complete": on_complete,
            }
        )
        return self

    def after(self, seconds: float, callback: Callable[[], None]) -> "TweenManager":
        self._timers.append({"time": seconds, "callback": callback})
        return self

    def update(self, dt: float) -> None:
        remaining_timers = []
        for timer in self._timers:
            timer["time"] -= dt
            if timer["time"] <= 0:
                try:
                    timer["callback"]()
                except Exception as exc:
                    print(_tr("[Reasonable] Timer error: {error}", "[Reasonable] Ошибка таймера: {error}", error=exc))
            else:
                remaining_timers.append(timer)
        self._timers = remaining_timers
        alive = []
        for tween in self._tweens:
            if tween["delay"] > 0:
                tween["delay"] -= dt
                alive.append(tween)
                continue
            tween["elapsed"] += dt * tween["direction"]
            progress = max(0.0, min(1.0, tween["elapsed"] / tween["duration"]))
            eased = tween["easing"](progress)
            start, end = tween["start"], tween["end"]
            if isinstance(start, pygame.Vector2):
                if isinstance(end, (tuple, list)):
                    end_vec = pygame.Vector2(end)
                else:
                    end_vec = pygame.Vector2(end, end)
                setattr(tween["target"], tween["attr"], start.lerp(end_vec, eased))
            elif isinstance(start, pygame.Color) or isinstance(end, pygame.Color):
                setattr(tween["target"], tween["attr"], mix(start, end, eased))
            elif isinstance(start, (int, float)) and isinstance(end, (int, float)):
                setattr(tween["target"], tween["attr"], start + (end - start) * eased)
            else:
                setattr(tween["target"], tween["attr"], end if eased >= 1 else start)
            done = tween["elapsed"] >= tween["duration"] if tween["direction"] > 0 else tween["elapsed"] <= 0
            if done:
                if tween["yoyo"]:
                    tween["direction"] *= -1
                    if tween["loop"]:
                        alive.append(tween)
                    elif tween["direction"] > 0:
                        if tween["on_complete"]:
                            tween["on_complete"]()
                    else:
                        alive.append(tween)
                    continue
                if tween["loop"]:
                    tween["elapsed"] = 0
                    alive.append(tween)
                    continue
                if tween["on_complete"]:
                    tween["on_complete"]()
                continue
            alive.append(tween)
        self._tweens = alive


def fit_camera_bounds(world: pygame.Rect) -> pygame.Rect:
    return world.copy()
