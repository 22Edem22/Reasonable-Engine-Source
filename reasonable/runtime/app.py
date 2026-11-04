"""Application loop shared by games and desktop-style UI applications."""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

import pygame

try:
    from reasonable.core.i18n import tr as _tr
except Exception:  # exported builds may run without the bundled core package
    def _tr(en: str, ru: str, **values) -> str:
        return en

from reasonable.core.paths import resource_path
from .input import Input
from .scene import Scene
from .splash import play_splash, splash_played
from .utils import BG, color, draw_gradient, get_font, render_text, with_alpha


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _is_android() -> bool:
    return sys.platform == "android" or "ANDROID_ARGUMENT" in os.environ or "ANDROID_PRIVATE" in os.environ


class App:
    """Base application: window, fixed timestep-ish loop, events and splash."""

    def __init__(
        self,
        title: str = "Reasonable Engine",
        size: tuple[int, int] = (960, 540),
        *,
        background=(8, 12, 20),
        fps: int = 60,
        flags: int = pygame.RESIZABLE,
        splash: bool = True,
        splash_skippable: bool = True,
        splash_accent="#FF6B4A",
        icon: str | None = None,
        resizable: bool | None = None,
        fullscreen: bool = False,
    ) -> None:
        self.title = title
        self.size = (int(size[0]), int(size[1]))
        self.background = background
        self.fps = fps
        if resizable is not None:
            flags = (flags | pygame.RESIZABLE) if resizable else (flags & ~pygame.RESIZABLE)
        self.flags = flags
        # The splash is part of the engine's identity. ``splash=False`` is
        # accepted only for source compatibility and intentionally ignored:
        # project code must not be able to remove the intro.
        self.splash = True
        self.splash_skippable = splash_skippable
        self.splash_accent = splash_accent
        self.icon = icon
        self.start_fullscreen = bool(fullscreen)
        self.screen: pygame.Surface | None = None
        self.clock = pygame.time.Clock()
        self.running = False
        self.debug = _env_flag("RE_DEBUG")
        self.time = 0.0
        self.frame_count = 0
        self._windowed_size = self.size
        self._fullscreen = False

    # ------------------------------------------------------------------
    def on_start(self) -> None:
        pass

    def on_event(self, event: pygame.event.Event) -> None:
        pass

    def on_update(self, dt: float) -> None:
        pass

    def on_draw(self, surface: pygame.Surface) -> None:
        pass

    def on_resize(self, size: tuple[int, int]) -> None:
        self.size = size

    def on_exit(self) -> None:
        pass

    # ------------------------------------------------------------------
    def set_title(self, title: str) -> None:
        self.title = title
        pygame.display.set_caption(title)

    def quit(self) -> None:
        self.running = False

    def toggle_fullscreen(self) -> None:
        self.set_fullscreen(not self._fullscreen)

    def set_fullscreen(self, enabled: bool) -> None:
        """Switch between the base window and true fullscreen.

        Games can call this from their own settings screen; ``F11`` and the
        ``RE_FULLSCREEN`` environment variable use the same path.
        """
        enabled = bool(enabled)
        if enabled == self._fullscreen:
            return
        if enabled:
            surface = pygame.display.get_surface()
            if surface is not None:
                self._windowed_size = surface.get_size()
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
            self._fullscreen = True
        else:
            self.screen = pygame.display.set_mode(self._windowed_size, self.flags)
            self._fullscreen = False
        if self.screen is not None:
            self.size = self.screen.get_size()
        self.on_resize(self.size)

    def capture(self, path: str | Path = "screenshot.png") -> Path:
        if not pygame.display.get_surface():
            raise RuntimeError(_tr("The window is not created yet", "Окно ещё не создано"))
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        pygame.image.save(pygame.display.get_surface(), str(path))
        return path

    # ------------------------------------------------------------------
    def run(self) -> None:
        pygame.init()
        mobile = _is_android()
        forced_fullscreen = self.start_fullscreen and not _env_flag("RE_WINDOWED")
        if mobile or _env_flag("RE_FULLSCREEN") or forced_fullscreen:
            flags = pygame.FULLSCREEN
        else:
            flags = self.flags
        try:
            pygame.display.set_mode(self.size, flags)
        except pygame.error:
            pygame.display.set_mode(self.size)
        self._fullscreen = bool(mobile or _env_flag("RE_FULLSCREEN") or forced_fullscreen)
        pygame.display.set_caption(self.title)
        self._set_icon()
        self.screen = pygame.display.get_surface()
        if self.screen:
            self.size = self.screen.get_size()

        # The intro always plays: there is no user-facing way to skip it.
        # Only the engine developer (personal key) or headless test runs can
        # bypass it, and both are handled inside play_splash.
        if not splash_played():
            if not play_splash(self.size, accent=self.splash_accent, skippable=self.splash_skippable):
                pygame.quit()
                return
        self.screen = pygame.display.get_surface()
        if self.screen:
            self.size = self.screen.get_size()
        pygame.display.set_caption(self.title)

        self.clock = pygame.time.Clock()
        self.running = True
        self.on_start()
        limit_frames = None
        if os.environ.get("RE_FRAMES"):
            try:
                limit_frames = max(1, int(os.environ["RE_FRAMES"]))
            except ValueError:
                limit_frames = None

        try:
            last_event_error = ""
            while self.running:
                dt = min(0.05, self.clock.tick(self.fps) / 1000.0)
                self.time += dt
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        self.running = False
                        break
                    if event.type == pygame.VIDEORESIZE and not self._fullscreen:
                        new_size = (max(420, event.w), max(280, event.h))
                        self.screen = pygame.display.set_mode(new_size, flags)
                        self.size = new_size
                        self._windowed_size = new_size
                        self.on_resize(new_size)
                        continue
                    if event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
                        self.toggle_fullscreen()
                        continue
                    try:
                        self.on_event(event)
                    except (KeyboardInterrupt, SystemExit):
                        raise
                    except Exception as exc:
                        # A single broken event from project code must not kill
                        # the whole application: log it once and keep going.
                        traceback_line = traceback.format_exc()
                        if traceback_line != last_event_error:
                            last_event_error = traceback_line
                            print(_tr("[Reasonable] Event handling error: {error}", "[Reasonable] Ошибка обработки события: {error}", error=exc), file=sys.stderr)
                            print(traceback_line, file=sys.stderr)
                if not self.running:
                    break
                self.on_update(dt)
                surface = pygame.display.get_surface()
                if surface is None:
                    break
                self.on_draw(surface)
                pygame.display.flip()
                self.frame_count += 1
                if limit_frames is not None and self.frame_count >= limit_frames:
                    break
        finally:
            try:
                self.on_exit()
            finally:
                pygame.quit()

    def _set_icon(self) -> None:
        candidates = [self.icon] if self.icon else []
        candidates += [str(resource_path("assets/brand/logo_512.png")), str(resource_path("assets/brand/logo.ico"))]
        for candidate in candidates:
            if not candidate:
                continue
            path = Path(candidate)
            if path.exists():
                try:
                    pygame.display.set_icon(pygame.image.load(str(path)))
                    return
                except Exception:
                    continue


class Game(App):
    """Scene-based game application.

    Subclass this and set an initial scene in ``on_start``. Use ``self.input``
    for keyboard/mouse/touch state and ``self.set_scene`` for transitions.
    """

    def __init__(self, title: str = "Game", size: tuple[int, int] = (960, 540), **kwargs) -> None:
        super().__init__(title, size, **kwargs)
        self.input = Input()
        self.scene: Scene | None = None
        self._scene_stack: list[Scene] = []

    def set_scene(self, scene: Scene, *, keep_previous: bool = False) -> Scene:
        if self.scene is not None:
            try:
                self.scene.on_exit()
            except Exception as exc:
                print(f"[Reasonable] on_exit error: {exc}")
            if keep_previous:
                self._scene_stack.append(self.scene)
        scene.game = self
        scene.camera.resize(self.size)
        if scene.ui is not None and hasattr(scene.ui, "layout"):
            scene.ui.layout(pygame.Rect(0, 0, *self.size))
        self.scene = scene
        try:
            scene.on_enter()
        except Exception as exc:
            print(f"[Reasonable] on_enter error: {exc}")
        return scene

    def change_scene(self, scene: Scene) -> Scene:
        return self.set_scene(scene)

    def push_scene(self, scene: Scene) -> Scene:
        return self.set_scene(scene, keep_previous=True)

    def pop_scene(self) -> Scene | None:
        if not self._scene_stack:
            return None
        if self.scene:
            self.scene.on_exit()
        scene = self._scene_stack.pop()
        scene.game = self
        scene.camera.resize(self.size)
        scene.on_enter()
        self.scene = scene
        return scene

    def on_event(self, event: pygame.event.Event) -> None:
        self.input.feed(event)
        if self.scene is None:
            return
        if self.scene.ui is not None and hasattr(self.scene.ui, "handle_event"):
            from .ui import blur_entries, touch_to_mouse

            if event.type in (pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN):
                blur_entries()
            ui_event = touch_to_mouse(event)
            if ui_event is not None and self.scene.ui.handle_event(ui_event):
                return
        self.scene.handle_event(event)

    def on_update(self, dt: float) -> None:
        if self.scene is not None:
            self.scene.update(dt)
        self.input.clear_frame()

    def on_draw(self, surface: pygame.Surface) -> None:
        if self.scene is None:
            surface.fill(self.background)
            message = _tr("No scene created", "Сцена не создана")
            image = render_text(message, 22, (200, 210, 230))
            surface.blit(image, image.get_rect(center=(surface.get_width() // 2, surface.get_height() // 2)))
            return
        self.scene.draw(surface)

    def on_resize(self, size: tuple[int, int]) -> None:
        super().on_resize(size)
        if self.scene is not None:
            self.scene.on_resize(size)

    def on_exit(self) -> None:
        if self.scene is not None:
            self.scene.on_exit()


class UIApp(App):
    """Desktop-style application with the built-in widget toolkit."""

    def __init__(self, title: str = "Reasonable App", size: tuple[int, int] = (1180, 760), *, theme=None, **kwargs) -> None:
        kwargs.setdefault("flags", pygame.RESIZABLE)
        kwargs.setdefault("splash", True)
        super().__init__(title, size, **kwargs)
        from .ui import Theme, set_active_theme

        self.theme = theme or Theme()
        set_active_theme(self.theme)
        self.root = None
        self._background_surface: pygame.Surface | None = None
        self._background_size = None

    def build_ui(self):
        """Return the root widget (usually a Panel/VStack)."""
        return None

    def on_start(self) -> None:
        root = self.build_ui()
        if root is not None:
            self.set_root(root)

    def set_root(self, widget) -> None:
        self.root = widget
        self.root.layout(pygame.Rect(0, 0, *self.size))
        try:
            self.root.on_mount()
        except Exception:
            pass

    def on_event(self, event: pygame.event.Event) -> None:
        if self.root is None:
            return
        from .ui import blur_entries, touch_to_mouse

        if event.type in (pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN):
            blur_entries()
        ui_event = touch_to_mouse(event)
        if ui_event is not None:
            self.root.handle_event(ui_event)

    def on_update(self, dt: float) -> None:
        if self.root is not None:
            self.root.layout(pygame.Rect(0, 0, *self.size))
            self.root.update(dt)

    def on_draw(self, surface: pygame.Surface) -> None:
        size = surface.get_size()
        if self._background_surface is None or self._background_size != size:
            # The gradient and the ambient glows never change while the window
            # keeps its size, so bake them into one surface once instead of
            # rebuilding two large glows on every frame.
            background = pygame.Surface(size)
            try:
                background = background.convert()
            except pygame.error:
                pass
            draw_gradient(background, background.get_rect(), self.theme.bg, self.theme.bg_bottom)
            from .utils import draw_glow

            draw_glow(background, (size[0] * 0.16, size[1] * 0.08), int(min(size) * 0.44), self.theme.accent, 18, 5)
            draw_glow(background, (size[0] * 0.9, size[1] * 0.92), int(min(size) * 0.5), self.theme.accent_2, 12, 5)
            self._background_surface = background
            self._background_size = size
        surface.blit(self._background_surface, (0, 0))
        if self.root is not None:
            self.root.draw(surface)
        if self.debug:
            font = get_font(16)
            image = font.render(f"FPS {self.clock.get_fps():.0f}", True, (255, 255, 255))
            surface.blit(image, (12, 12))

    def on_resize(self, size: tuple[int, int]) -> None:
        super().on_resize(size)
        self._background_surface = None
        if self.root is not None:
            self.root.layout(pygame.Rect(0, 0, *size))
