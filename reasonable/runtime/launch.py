"""Splash-first project launcher used by the editor, player and CLI.

The splash is enforced by the engine process, not by project code. Running a
project through this module plays the intro even if its ``main.py`` was edited
to call pygame directly or passed ``splash=False``; the process-wide
``splash_played()`` marker then prevents the intro from playing twice when the
project itself uses :class:`reasonable.runtime.App`.

Usage::

    python -m reasonable.runtime.launch path/to/main.py
"""

from __future__ import annotations

import json
import os
import runpy
import sys
from pathlib import Path


_AUTOPLAY_STATE = {
    "frames": 0,
    "flips": 0,
    "unchanged": 0,
    "max_unchanged": 0,
    "last_hash": None,
    "idle": False,
}


def _install_autoplay() -> None:
    """Inject menu and movement input for headless game smoke runs.

    ``run_project`` used to only check that the process starts and exits, so a
    game frozen on its title screen looked healthy. This patch presses Enter to
    leave menus, holds right, jumps and dashes, and tracks rendered frames. If
    the picture does not change for two seconds it reports an idle game.
    """
    try:
        import pygame
    except Exception:
        return
    if getattr(pygame, "_reasonable_autoplay", False):
        return
    original_get = pygame.event.get
    original_pressed = pygame.key.get_pressed
    state = _AUTOPLAY_STATE
    state.update(
        frames=0, flips=0, unchanged=0, max_unchanged=0, last_hash=None, idle=False
    )
    dash_frames = {"left": 0}

    class _Keys:
        def __getitem__(self, key):
            if key in (pygame.K_RIGHT, pygame.K_d):
                return True
            if key in (pygame.K_LSHIFT, pygame.K_RSHIFT, pygame.K_x):
                return dash_frames["left"] > 0
            if key in (pygame.K_SPACE, pygame.K_w, pygame.K_UP, pygame.K_z):
                return state["frames"] % 42 < 18
            return False

    def key_event(kind, key):
        return pygame.event.Event(
            kind, key=key, mod=0, unicode="", scancode=0
        )

    def get_events(*args, **kwargs):
        events = list(original_get(*args, **kwargs))
        state["frames"] += 1
        frame = state["frames"]
        # Leave the title screen and keep moving through menu/result screens.
        if frame % 90 == 2:
            events.append(key_event(pygame.KEYDOWN, pygame.K_RETURN))
            events.append(key_event(pygame.KEYUP, pygame.K_RETURN))
        if frame % 42 == 0:
            events.append(key_event(pygame.KEYDOWN, pygame.K_SPACE))
        elif frame % 42 == 18:
            events.append(key_event(pygame.KEYUP, pygame.K_SPACE))
        if frame % 150 == 0:
            dash_frames["left"] = 10
            events.append(key_event(pygame.KEYDOWN, pygame.K_LSHIFT))
        elif dash_frames["left"] > 0:
            dash_frames["left"] -= 1
            if dash_frames["left"] == 0:
                events.append(key_event(pygame.KEYUP, pygame.K_LSHIFT))
        return events

    def check_frame(*_args, **_kwargs):
        surface = pygame.display.get_surface()
        if surface is None:
            return
        state["flips"] += 1
        try:
            small = pygame.transform.smoothscale(surface, (48, 27))
            digest = hash(pygame.image.tostring(small, "RGB"))
        except Exception:
            return
        if digest == state["last_hash"]:
            state["unchanged"] += 1
            state["max_unchanged"] = max(state["max_unchanged"], state["unchanged"])
            if state["unchanged"] == 120 and not state["idle"]:
                state["idle"] = True
                print(
                    "RE_AUTOPLAY_IDLE: the game screen did not change for 120 frames; "
                    "it is probably stuck on a menu or frozen.",
                    flush=True,
                )
                try:
                    pygame.event.post(pygame.event.Event(pygame.QUIT))
                except Exception:
                    pass
        else:
            state["last_hash"] = digest
            state["unchanged"] = 0

    original_flip = pygame.display.flip
    original_update = pygame.display.update

    def flip(*args, **kwargs):
        result = original_flip(*args, **kwargs)
        check_frame()
        return result

    def update(*args, **kwargs):
        result = original_update(*args, **kwargs)
        check_frame()
        return result

    pygame.event.get = get_events
    pygame.key.get_pressed = lambda: _Keys()
    pygame.display.flip = flip
    pygame.display.update = update
    pygame._reasonable_autoplay = True


def _print_autoplay_summary() -> None:
    try:
        import pygame
    except Exception:
        return
    if not getattr(pygame, "_reasonable_autoplay", False):
        return
    state = _AUTOPLAY_STATE
    print(
        "RE_AUTOPLAY_OK frames={frames} flips={flips} max_unchanged={max_unchanged} idle={idle}".format(
            **state
        ),
        flush=True,
    )


_SCREENSHOT_STATE = {"frames": 0, "saved": 0, "directory": None, "targets": set()}


def _install_screenshots(directory: str, count: int = 3) -> None:
    """Save a few rendered frames so the agent can inspect the real UI."""
    try:
        import pygame
    except Exception:
        return
    if getattr(pygame, "_reasonable_screenshots", False):
        return
    target_dir = Path(directory)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    count = max(1, min(8, int(count or 3)))
    candidates = [2, 20, 45, 90, 150, 240, 360, 600]
    state = _SCREENSHOT_STATE
    state.update(
        frames=0,
        saved=0,
        directory=str(target_dir),
        targets=set(candidates[:count]),
    )
    original_flip = pygame.display.flip
    original_update = pygame.display.update

    def capture() -> None:
        state["frames"] += 1
        if state["saved"] >= count or state["frames"] not in state["targets"]:
            return
        surface = pygame.display.get_surface()
        if surface is None:
            return
        path = target_dir / f"frame_{state['saved'] + 1:02d}.png"
        try:
            pygame.image.save(surface, str(path))
        except Exception:
            return
        state["saved"] += 1

    def flip(*args, **kwargs):
        result = original_flip(*args, **kwargs)
        capture()
        return result

    def update(*args, **kwargs):
        result = original_update(*args, **kwargs)
        capture()
        return result

    pygame.display.flip = flip
    pygame.display.update = update
    pygame._reasonable_screenshots = True


def _print_screenshot_summary() -> None:
    if not _SCREENSHOT_STATE["directory"]:
        return
    print(
        "RE_SCREENSHOTS_OK saved={saved} frames={frames} directory={directory}".format(
            **_SCREENSHOT_STATE
        ),
        flush=True,
    )



def _window_size(entry: Path) -> tuple[int, int]:
    try:
        data = json.loads((entry.parent / "project.json").read_text(encoding="utf-8"))
        window = data.get("window") if isinstance(data, dict) else {}
        return (
            max(320, int((window or {}).get("width") or 1280)),
            max(240, int((window or {}).get("height") or 720)),
        )
    except (OSError, ValueError, TypeError):
        return (1280, 720)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("Reasonable Engine: pass the project's main.py path.", file=sys.stderr)
        return 2
    entry = Path(args[0]).expanduser()
    if not entry.is_file():
        print(f"Reasonable Engine: entry point not found: {entry}", file=sys.stderr)
        return 2
    entry = entry.resolve()
    root = entry.parent
    previous_cwd = Path.cwd()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    os.chdir(root)
    try:
        from .splash import play_splash

        if not play_splash(_window_size(entry)):
            return 0
        if os.environ.get("RE_AUTOPLAY") == "1":
            _install_autoplay()
        screenshot_dir = os.environ.get("RE_SCREENSHOTS")
        if screenshot_dir:
            try:
                screenshot_count = int(os.environ.get("RE_SCREENSHOT_FRAMES", "3"))
            except (TypeError, ValueError):
                screenshot_count = 3
            _install_screenshots(screenshot_dir, screenshot_count)
        sys.argv = [str(entry), *args[1:]]
        try:
            runpy.run_path(str(entry), run_name="__main__")
        finally:
            if os.environ.get("RE_AUTOPLAY") == "1":
                _print_autoplay_summary()
            if screenshot_dir:
                _print_screenshot_summary()
    finally:
        os.chdir(previous_cwd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
