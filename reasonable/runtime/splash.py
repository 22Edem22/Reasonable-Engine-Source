"""The animated Reasonable Engine intro played before every project.

It is drawn entirely with primitives and bundled fonts, so it works offline in
exported Windows builds and on Android. Duration ~2.8 s, skippable after 0.85 s.
"""

from __future__ import annotations

import hashlib
import math
import os
import random
import time
from pathlib import Path

import pygame

from reasonable.branding import SPLASH_TAGLINE
from .utils import (
    color,
    draw_glow,
    draw_gradient,
    draw_icon,
    ease_in_out_cubic,
    ease_out_back,
    ease_out_cubic,
    ease_out_expo,
    get_font,
    mix,
    render_text,
    with_alpha,
)


DESIGN_LANDSCAPE = (1280, 720)
DESIGN_PORTRAIT = (720, 1280)
TOTAL_DURATION = 2.8
ACCENT = pygame.Color("#FF6B4A")


# The intro splash is part of Reasonable Engine branding and always plays.
# End users cannot disable or skip it: every project.json flag and every
# RE_SKIP_* environment variable was removed deliberately. The ONLY bypass is
# the developer key below: the engine developer sets RE_SPLASH_DEV_TOKEN to a
# personal secret whose SHA-256 matches this constant. The hash ships with the
# bytecode-only runtime, so the token itself never leaves the developer.
DEV_TOKEN_HASH = "fd0575fca0f9344e27a35b70c539137200281c9a3ad8bacd11a0a5b1cccf6230"


def developer_splash_bypass() -> bool:
    """True only for the engine developer's personal splash key."""
    token = os.environ.get("RE_SPLASH_DEV_TOKEN", "")
    if not token:
        return False
    return hashlib.sha256(token.encode("utf-8")).hexdigest() == DEV_TOKEN_HASH


def _is_headless() -> bool:
    """Headless test/agent runs have no visible window.

    The splash still executes (branding code path stays identical), but it
    finishes instantly so validation stays fast. Real users never run with a
    dummy video driver, so this is invisible to them.
    """
    return os.environ.get("SDL_VIDEODRIVER", "").strip().lower() == "dummy"
ACCENT_2 = pygame.Color("#35D6C4")
ACCENT_3 = pygame.Color("#FFC857")
WHITE = pygame.Color("#F4F7FB")
MUTED = pygame.Color("#8A9AB3")
DARK = pygame.Color("#070B12")


def _fit_font(text: str, max_width: int, max_size: int, *, bold: bool = True, ratio: float = 0.12) -> tuple[pygame.font.Font, int, int]:
    size = max_size
    while size > 16:
        font = get_font(size, bold=bold, display=True)
        spacing = max(1, int(size * ratio))
        width = sum(font.size(char)[0] for char in text) + spacing * max(0, len(text) - 1)
        if width <= max_width:
            return font, spacing, width
        size -= 2
    font = get_font(size, bold=bold, display=True)
    spacing = max(1, int(size * ratio))
    width = sum(font.size(char)[0] for char in text) + spacing * max(0, len(text) - 1)
    return font, spacing, width


class SplashAnimator:
    def __init__(self, width: int = 1280, height: int = 720, accent=ACCENT, seed: int = 7) -> None:
        self.width = width
        self.height = height
        self.landscape = width >= height
        self.accent = color(accent)
        self.center = pygame.Vector2(width / 2, height * (0.40 if self.landscape else 0.37))
        self.radius = min(width, height) * (0.19 if self.landscape else 0.19)
        self.word_y = self.center.y + self.radius * (1.70 if self.landscape else 1.92)
        self.random = random.Random(seed)
        self.stars = [
            (
                self.random.uniform(0, width),
                self.random.uniform(0, height),
                self.random.uniform(0.3, 1.8),
                self.random.uniform(0.25, 1.0),
                self.random.uniform(0, math.tau),
            )
            for _ in range(76)
        ]
        self.shards = [
            (
                self.random.uniform(0, math.tau),
                self.random.uniform(1.6, 3.4),
                self.random.uniform(0.03, 0.14),
                self.random.choice([self.accent, ACCENT_2, ACCENT_3, WHITE]),
                self.random.uniform(0.03, 0.1),
            )
            for _ in range(18)
        ]
        self.burst = [
            (
                self.random.uniform(0, math.tau),
                self.random.uniform(30, 190),
                self.random.uniform(1.0, 3.2),
                self.random.choice([self.accent, ACCENT_2, ACCENT_3]),
                self.random.uniform(0.25, 0.9),
            )
            for _ in range(38)
        ]
        self.base = self._build_base()
        self.title_font, self.title_spacing, self.title_width = _fit_font(
            "REASONABLE", int(width * 0.88), 98 if self.landscape else 64
        )
        self.title_size = self.title_font.get_height()
        self.sub_font, self.sub_spacing, self.sub_width = _fit_font(
            "ENGINE", int(width * 0.5), 24 if self.landscape else 18, ratio=0.5
        )
        self.tagline_font = get_font(15 if self.landscape else 13, bold=True)
        self.hint_font = get_font(12, bold=False)

    # ------------------------------------------------------------------
    def _build_base(self) -> pygame.Surface:
        base = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        draw_gradient(base, base.get_rect(), (6, 9, 15), (12, 18, 30))
        # atmospheric glows: ember below-left, aurora above-right
        draw_glow(base, (self.width * 0.14, self.height * 0.78), int(min(self.width, self.height) * 0.68), self.accent, 66, 9)
        draw_glow(base, (self.width * 0.83, self.height * 0.16), int(min(self.width, self.height) * 0.56), ACCENT_2, 50, 9)
        draw_glow(base, (self.width * 0.5, self.height * 0.4), int(min(self.width, self.height) * 0.46), (80, 111, 175), 46, 8)
        draw_glow(base, (self.width * 0.5, self.height * 0.94), int(self.width * 0.38), ACCENT_3, 17, 6)
        # concentric technical rings; clipped before the wordmark so they never
        # draw a line through the logo text
        rings = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        for radius_factor, alpha in ((1.62, 18), (1.86, 11), (2.25, 8)):
            pygame.draw.circle(
                rings,
                (150, 178, 220, alpha),
                (int(self.center.x), int(self.center.y)),
                int(self.radius * radius_factor),
                1,
            )
        clip_bottom = max(0, int(self.word_y - 24))
        if clip_bottom > 0:
            rings.set_clip(pygame.Rect(0, 0, self.width, clip_bottom))
        base.blit(rings, (0, 0))
        step = 34 if self.landscape else 30
        dot = pygame.Surface((2, 2), pygame.SRCALPHA)
        dot.fill((150, 175, 210, 18))
        for y in range(0, self.height, step):
            for x in range(0, self.width, step):
                base.blit(dot, (x, y))
        # tiny sparkles add life to the large empty planes
        rng = random.Random(41)
        for _ in range(18 if self.landscape else 14):
            sx = rng.uniform(0.06, 0.94) * self.width
            sy = rng.uniform(0.06, 0.9) * self.height
            if abs(sx - self.center.x) < self.radius * 2.2 and abs(sy - self.center.y) < self.radius * 2.2:
                continue
            size = rng.choice((1, 1, 1, 2))
            pygame.draw.line(base, (205, 225, 245, rng.randint(25, 70)), (sx - size * 2, sy), (sx + size * 2, sy))
            pygame.draw.line(base, (205, 225, 245, rng.randint(25, 70)), (sx, sy - size * 2), (sx, sy + size * 2))
        return base

    # ------------------------------------------------------------------
    def _alpha_surface(self, text: str, font: pygame.font.Font, color_value, alpha: int) -> pygame.Surface:
        image = font.render(text, True, color(color_value))
        image.set_alpha(alpha)
        return image

    def _draw_ring(self, surface: pygame.Surface, radius: float, progress: float, rotation: float, dots: int, dot_radius: float, colors, gaps=((0.12, 0.2), (0.52, 0.58), (0.8, 0.84)), alpha: int = 255) -> None:
        for index in range(dots):
            fraction = index / dots
            if any(start <= fraction <= end for start, end in gaps):
                continue
            angle = rotation + fraction * math.tau
            x = self.center.x + math.cos(angle) * radius
            y = self.center.y + math.sin(angle) * radius
            t = fraction
            c = mix(colors[0], colors[1], (math.sin(t * math.tau + 0.7) + 1) / 2)
            c = with_alpha(c, int(alpha * (0.55 + 0.45 * math.sin(t * math.pi * 2 + 1.3) ** 2)))
            pygame.draw.circle(surface, c, (int(x), int(y)), max(1, int(dot_radius)))

    def _draw_star(self, surface: pygame.Surface, center, radius: float, rotation: float, scale: float, alpha: int) -> None:
        size = int(radius * 2.8)
        layer = pygame.Surface((size, size), pygame.SRCALPHA)
        cx, cy = size // 2, size // 2
        points = []
        for index in range(16):
            angle = rotation - math.pi / 2 + index * math.pi / 8
            r = radius * scale * (1.0 if index % 4 == 0 else (0.52 if index % 2 == 0 else 0.22))
            points.append((cx + math.cos(angle) * r, cy + math.sin(angle) * r))
        pygame.draw.polygon(layer, with_alpha(self.accent, alpha), points)
        # inner highlight
        inner = []
        for index in range(8):
            angle = rotation - math.pi / 2 + index * math.pi / 4
            r = radius * scale * (0.62 if index % 2 == 0 else 0.18)
            inner.append((cx + math.cos(angle) * r, cy + math.sin(angle) * r))
        pygame.draw.polygon(layer, with_alpha(WHITE, int(alpha * 0.8)), inner)
        pygame.draw.circle(layer, with_alpha(ACCENT_3, int(alpha * 0.9)), (cx, cy), max(1, int(radius * 0.12 * scale)))
        surface.blit(layer, (int(center[0] - cx), int(center[1] - cy)))

    def _draw_spaced_word(
        self,
        surface: pygame.Surface,
        text: str,
        font: pygame.font.Font,
        spacing: int,
        center_x: float,
        top_y: float,
        local_time: float,
        start: float,
        per_char: float,
        fade: float,
        color_value=WHITE,
        rise: float = 12,
    ) -> None:
        widths = [font.size(char)[0] for char in text]
        total = sum(widths) + spacing * max(0, len(text) - 1)
        x = center_x - total / 2
        for index, char in enumerate(text):
            char_alpha = max(0.0, min(1.0, (local_time - start - index * per_char) / max(0.001, fade)))
            if char_alpha > 0:
                eased = ease_out_cubic(char_alpha)
                offset_y = (1 - eased) * rise
                image = font.render(char, True, color(color_value))
                image.set_alpha(int(255 * eased))
                surface.blit(image, (int(x), int(top_y + offset_y)))
            x += widths[index] + spacing

    def _draw_center(self, surface: pygame.Surface, t: float) -> None:
        appear = ease_out_cubic((t - 0.10) / 0.55)
        flourish = ease_out_back(max(0.0, min(1.0, (t - 0.58) / 0.45)))
        alpha = int(255 * appear)
        if alpha <= 0:
            return
        # rotating rings
        self._draw_ring(surface, self.radius * 1.33, 1, t * 0.35, 88, 1.3, (ACCENT_2, (120, 160, 230)), alpha=int(alpha * 0.45))
        self._draw_ring(surface, self.radius, 1, -t * 0.6 + 0.4, 108, 2.1, (self.accent, ACCENT_2), alpha=int(alpha * 0.95), gaps=((0.0, 0.045), (0.3, 0.33), (0.61, 0.65), (0.86, 0.9)))
        self._draw_ring(surface, self.radius * 0.93, 1, -t * 0.6 + 0.4, 108, 1.0, (ACCENT_3, self.accent), alpha=int(alpha * 0.4), gaps=((0.0, 0.045), (0.3, 0.33), (0.61, 0.65), (0.86, 0.9)))
        # orbit dot
        angle = -t * 0.9 + 1.2
        dot = pygame.Vector2(self.center.x + math.cos(angle) * self.radius * 1.33, self.center.y + math.sin(angle) * self.radius * 1.33)
        pygame.draw.circle(surface, with_alpha(ACCENT_2, int(alpha * 0.8)), dot, 4)
        pygame.draw.circle(surface, with_alpha(ACCENT_2, int(alpha * 0.18)), dot, 12)
        # central glow
        glow_alpha = int(70 * appear * flourish)
        draw_glow(surface, self.center, int(self.radius * 1.4 * max(0.5, flourish)), self.accent, glow_alpha, 7)
        # shards converging
        for angle, distance, delay, shard_color, thickness in self.shards:
            local = max(0.0, min(1.0, (t - 0.08 - delay) / 0.52))
            if local <= 0:
                continue
            eased = ease_out_expo(local)
            radial = self.radius * distance * (1 - eased) + self.radius * 1.05
            pos = pygame.Vector2(
                self.center.x + math.cos(angle) * radial,
                self.center.y + math.sin(angle) * radial,
            )
            tail = pygame.Vector2(math.cos(angle), math.sin(angle)) * 26 * (1 - eased * 0.7)
            shard_alpha = int(alpha * (1 - eased))
            pygame.draw.line(
                surface,
                with_alpha(shard_color, shard_alpha),
                pos,
                pos + tail,
                max(1, int(thickness * 8 * (1 - eased) + 1)),
            )
        # burst ring
        burst_t = max(0.0, min(1.0, (t - 0.64) / 0.62))
        if 0 < burst_t < 1:
            burst_radius = self.radius * (1.0 + 1.25 * ease_out_expo(burst_t))
            ring_alpha = int(150 * (1 - burst_t) * appear)
            pygame.draw.circle(surface, with_alpha(self.accent, ring_alpha), self.center, int(burst_radius), max(1, int(2 * (1 - burst_t))))
        # particles
        if t > 0.62:
            particle_t = t - 0.62
            for angle, speed, size, particle_color, delay in self.burst:
                if particle_t < delay:
                    continue
                local = min(1.0, (particle_t - delay) / 0.85)
                radius = speed * ease_out_cubic(local) * (self.radius / 110)
                p = pygame.Vector2(self.center.x + math.cos(angle) * radius, self.center.y + math.sin(angle) * radius)
                a = int(220 * (1 - local) * appear)
                pygame.draw.circle(surface, with_alpha(particle_color, a), p, max(1, int(size * (1 - local * 0.7))))
        # central star
        star_scale = max(0.0, flourish) * (0.82 + 0.08 * math.sin(t * 2.2))
        if star_scale > 0:
            self._draw_star(surface, self.center, self.radius * 0.58, math.sin(t * 0.4) * 0.12, star_scale, int(alpha * min(1, flourish * 1.2)))

    def _draw_text(self, surface: pygame.Surface, t: float) -> None:
        title_top = self.word_y
        if t > 0.82:
            self._draw_spaced_word(
                surface,
                "REASONABLE",
                self.title_font,
                self.title_spacing,
                self.width / 2,
                title_top,
                t,
                start=0.82,
                per_char=0.034,
                fade=0.30,
                color_value=WHITE,
                rise=14,
            )
        sub_top = title_top + self.title_font.get_height() + (8 if self.landscape else 4)
        if t > 1.04:
            local = ease_out_cubic((t - 1.04) / 0.42)
            alpha = int(255 * local)
            sub = self.sub_font.render("ENGINE", True, color(ACCENT_3))
            sub.set_alpha(alpha)
            rect = sub.get_rect(center=(self.width / 2, sub_top + sub.get_height() / 2))
            surface.blit(sub, rect)
            line_len = self.width * 0.075 * local
            y = rect.centery
            for direction in (-1, 1):
                x1 = rect.centerx + direction * (self.sub_width / 2 + 18)
                x2 = x1 + direction * line_len
                pygame.draw.line(surface, with_alpha(ACCENT_3, int(150 * local)), (x1, y), (x2, y), 1)
        if t > 1.24:
            local = ease_out_cubic((t - 1.24) / 0.45)
            alpha = int(255 * local)
            tagline = self.tagline_font.render(SPLASH_TAGLINE, True, color(MUTED))
            spacing = 2
            widths = [self.tagline_font.size(char)[0] for char in SPLASH_TAGLINE]
            total = sum(widths) + spacing * (len(SPLASH_TAGLINE) - 1)
            x = self.width / 2 - total / 2
            y = sub_top + self.sub_font.get_height() + (22 if self.landscape else 16) + (1 - local) * 6
            for char, width in zip(SPLASH_TAGLINE, widths):
                glyph = self.tagline_font.render(char, True, color(MUTED))
                glyph.set_alpha(alpha)
                surface.blit(glyph, (int(x), int(y)))
                x += width + spacing
        if not self.landscape and t > 1.55:
            local = ease_out_cubic((t - 1.55) / 0.45)
            footer_font = get_font(11, bold=False)
            footer = footer_font.render("2D  •  WINDOWS  •  ANDROID", True, color(MUTED))
            footer.set_alpha(int(95 * local))
            rect = footer.get_rect(center=(self.width // 2, self.height - 66))
            surface.blit(footer, rect)
            line_w = int(self.width * 0.16 * local)
            pygame.draw.line(surface, with_alpha(MUTED, int(40 * local)), (self.width // 2 - line_w, self.height - 42), (self.width // 2 + line_w, self.height - 42), 1)

    def _draw_background_motion(self, surface: pygame.Surface, t: float) -> None:
        # slow moving stars / dust
        for x, y, speed, size, phase in self.stars:
            px = x + math.sin(t * 0.22 + phase) * 10
            py = (y - t * speed * 14) % self.height
            alpha = int(45 + 70 * (0.5 + 0.5 * math.sin(t * 1.2 + phase)))
            pygame.draw.circle(surface, with_alpha((180, 203, 235), alpha), (int(px), int(py)), max(1, int(size)))
        # a moving comet trail gives the background life without distracting
        travel = (t / TOTAL_DURATION)
        comet_x = self.width * (0.1 + travel * 0.8)
        comet_y = self.height * (0.18 + math.sin(travel * 3.1) * 0.04)
        trail = pygame.Surface((220, 42), pygame.SRCALPHA)
        for index in range(80):
            alpha = int(18 * (1 - index / 80))
            pygame.draw.circle(trail, with_alpha(ACCENT_2, alpha), (210 - index * 2.4, 21), max(1, int(2.2 * (index / 80 + 0.4))))
        surface.blit(trail, (comet_x - 210, comet_y - 21))

    def draw(self, t: float) -> pygame.Surface:
        surface = self.base.copy()
        self._draw_background_motion(surface, t)
        fade_in = max(0.0, min(1.0, t / 0.22))
        self._draw_center(surface, t)
        # dark overlay before the reveal keeps the composition calm
        if t < 0.25:
            veil = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
            veil.fill((0, 0, 0, int(190 * (1 - fade_in))))
            surface.blit(veil, (0, 0))
        self._draw_text(surface, t)
        fade_out = max(0.0, min(1.0, (t - (TOTAL_DURATION - 0.34)) / 0.34))
        if fade_out > 0:
            veil = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
            veil.fill((0, 0, 0, int(255 * fade_out)))
            surface.blit(veil, (0, 0))
        return surface


def play_splash(
    size: tuple[int, int] | None = None,
    *,
    accent="#FF6B4A",
    skippable: bool = True,
    total_duration: float = TOTAL_DURATION,
) -> bool:
    """Play the intro. Returns False if the window was closed.

    ``skippable`` is accepted for call compatibility but intentionally ignored:
    the intro always plays in full for end users. Only the engine developer's
    personal key (``RE_SPLASH_DEV_TOKEN``) or a headless dummy-driver run
    finishes the intro early.
    """
    if developer_splash_bypass():
        return True
    if not pygame.get_init():
        pygame.init()
    if not pygame.font.get_init():
        pygame.font.init()
    if pygame.display.get_surface() is None:
        width, height = size or (1280, 720)
        pygame.display.set_mode((int(width), int(height)), pygame.RESIZABLE)
    screen = pygame.display.get_surface()
    if screen is None:
        return False
    pygame.display.set_caption("Reasonable Engine")
    headless = _is_headless()
    display_width, display_height = screen.get_size()
    if display_width >= display_height:
        design_width, design_height = DESIGN_LANDSCAPE
    else:
        design_width, design_height = DESIGN_PORTRAIT
    # Keep the design close to the actual aspect ratio.
    if display_width and display_height:
        aspect = display_width / display_height
        if aspect > 2.0:
            design_width, design_height = 1600, 720
        elif aspect < 0.48:
            design_width, design_height = 720, 1560
    animator = SplashAnimator(design_width, design_height, accent)
    clock = pygame.time.Clock()
    started = time.perf_counter()
    while True:
        now = time.perf_counter()
        elapsed = now - started
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            if event.type == pygame.VIDEORESIZE:
                screen = pygame.display.set_mode((max(480, event.w), max(320, event.h)), pygame.RESIZABLE)
                display_width, display_height = screen.get_size()
        if elapsed >= total_duration:
            break
        # Headless runs render a couple of frames and finish instantly.
        frame_time = total_duration - 0.25 if headless else elapsed
        frame = animator.draw(frame_time)
        if (frame.get_width(), frame.get_height()) != (display_width, display_height):
            frame = pygame.transform.smoothscale(frame, (display_width, display_height))
        screen.blit(frame, (0, 0))
        pygame.display.flip()
        if headless:
            break
        clock.tick(60)
    pygame.event.pump()
    return True


def save_splash_preview(path: str | Path, time_seconds: float = 1.9, size: tuple[int, int] = DESIGN_LANDSCAPE) -> Path:
    """Render a still of the intro (used by docs/tests, no display required)."""
    if not pygame.get_init():
        pygame.init()
    if not pygame.font.get_init():
        pygame.font.init()
    animator = SplashAnimator(size[0], size[1])
    frame = animator.draw(time_seconds)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(frame, str(path))
    return path
