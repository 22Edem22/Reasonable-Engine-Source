"""The Reasonable Engine intro played before every project.

Deliberately minimal — a dark screen, the logo and a quiet caption, in the
spirit of the intros of professional engines: nothing distracts from the
product that follows. It is drawn from the bundled logo asset, so it works
offline in exported Windows builds and on Android.
"""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

import pygame

from reasonable.branding import APP_NAME
from .utils import ease_in_out_cubic, ease_out_cubic, get_font, render_text


DESIGN_LANDSCAPE = (1280, 720)
DESIGN_PORTRAIT = (720, 1280)
TOTAL_DURATION = 1.8

BACKGROUND = pygame.Color("#0B0D10")
CAPTION = pygame.Color("#C9CED6")
MUTED = pygame.Color("#6F7680")

LOGO_RELATIVE = Path("assets/brand") / "logo_512.png"

# Fallback caption when reasonable.core.i18n is not bundled (exported builds).
SPLASH_CAPTIONS_FALLBACK = "СОЗДАВАЙ. ИГРАЙ. РАЗУМНО."


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


def _load_logo() -> pygame.Surface | None:
    """The engine logo asset; ships inside the vendored runtime."""
    try:
        from reasonable.core.paths import BRAND_DIR

        candidates = (BRAND_DIR / "logo_512.png", BRAND_DIR / "logo_256.png")
        for candidate in candidates:
            if candidate.is_file():
                return pygame.image.load(str(candidate)).convert_alpha()
    except Exception:
        pass
    # Resource lookup for frozen builds (PyInstaller data files).
    try:
        from reasonable.core.paths import resource_path

        candidate = Path(resource_path(str(LOGO_RELATIVE).replace("\\", "/")))
        if candidate.is_file():
            return pygame.image.load(str(candidate)).convert_alpha()
    except Exception:
        pass
    return None


class SplashAnimator:
    """Dark screen, centered logo, quiet caption — nothing else."""

    def __init__(self, width: int = 1280, height: int = 720, accent=None, seed: int = 7) -> None:
        self.width = width
        self.height = height
        self.landscape = width >= height
        self.logo = _load_logo()
        # The logo occupies about a third of the shorter side.
        base = min(width, height)
        target = int(base * 0.34)
        if self.logo is not None:
            side = min(self.logo.get_width(), self.logo.get_height())
            if side > 0:
                self.logo = pygame.transform.smoothscale(self.logo, (target, target))
        self.logo_center = pygame.Vector2(width / 2, height * (0.42 if self.landscape else 0.38))
        self.caption_font = get_font(max(18, int(base * 0.030)), bold=True)
        self.version_font = get_font(max(13, int(base * 0.020)), bold=False)
        self.caption = f"{APP_NAME.upper()} 1"
        try:  # i18n is optional in exported standalone builds
            from reasonable.core.i18n import splash_caption

            self.sub = splash_caption()
        except Exception:
            self.sub = SPLASH_CAPTIONS_FALLBACK

    # ------------------------------------------------------------------
    def draw(self, t: float) -> pygame.Surface:
        surface = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        surface.fill(BACKGROUND)

        # Logo: gentle fade + a whisper of scale, like Unity/Godot intros.
        appear = max(0.0, min(1.0, (t - 0.05) / 0.55))
        if appear > 0 and self.logo is not None:
            eased = ease_out_cubic(appear)
            scale = 0.94 + 0.06 * eased
            side = max(1, int(self.logo.get_width() * scale))
            image = pygame.transform.smoothscale(self.logo, (side, side))
            image.set_alpha(int(255 * eased))
            surface.blit(
                image,
                image.get_rect(center=(int(self.logo_center.x), int(self.logo_center.y))),
            )
        elif appear > 0:
            # Fallback: a clean wordmark when the logo asset is missing.
            mark = render_text(APP_NAME.upper(), max(24, self.width // 26), CAPTION, bold=True)
            mark.set_alpha(int(255 * ease_out_cubic(appear)))
            surface.blit(mark, mark.get_rect(center=(int(self.logo_center.x), int(self.logo_center.y))))

        # Caption below the logo.
        caption_in = max(0.0, min(1.0, (t - 0.38) / 0.5))
        if caption_in > 0:
            alpha = int(255 * ease_out_cubic(caption_in))
            text = self.caption_font.render(self.caption, True, CAPTION)
            text.set_alpha(alpha)
            y = self.logo_center.y + (self.logo.get_height() if self.logo else 64) * 0.5 + 34
            surface.blit(text, text.get_rect(center=(int(self.width / 2), int(y))))
            sub = self.version_font.render(self.sub, True, MUTED)
            sub.set_alpha(int(150 * ease_out_cubic(caption_in)))
            surface.blit(sub, sub.get_rect(center=(int(self.width / 2), int(y + text.get_height() + 12))))

        # Fade out at the end.
        fade_out = max(0.0, min(1.0, (t - (TOTAL_DURATION - 0.35)) / 0.35))
        if fade_out > 0:
            veil = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
            veil.fill((11, 13, 16, int(255 * ease_in_out_cubic(fade_out))))
            surface.blit(veil, (0, 0))
        return surface


def play_splash(
    size: tuple[int, int] | None = None,
    *,
    accent=None,
    skippable: bool = True,
    total_duration: float = TOTAL_DURATION,
) -> bool:
    """Play the intro. Returns False if the window was closed.

    ``accent`` and ``skippable`` are accepted for call compatibility but
    intentionally ignored: the intro always plays in full for end users. Only
    the engine developer's personal key (``RE_SPLASH_DEV_TOKEN``) or a
    headless dummy-driver run finishes the intro early.
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
    pygame.display.set_caption(APP_NAME)
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
    animator = SplashAnimator(design_width, design_height)
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
        # Headless runs render a single final frame and finish instantly.
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


def save_splash_preview(path: str | Path, time_seconds: float = 0.9, size: tuple[int, int] = DESIGN_LANDSCAPE) -> Path:
    """Render a still of the intro (used by docs/tests, no display required)."""
    if not pygame.get_init():
        pygame.init()
    if not pygame.font.get_init():
        pygame.font.init()
    animator = SplashAnimator(size[0], size[1])
    frame = animator.draw(min(time_seconds, TOTAL_DURATION))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(frame, str(path))
    return path
