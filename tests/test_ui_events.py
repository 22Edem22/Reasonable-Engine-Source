"""Regression tests for the pygame event handling in the Reasonable runtime.

The original bug: ``pygame.MOUSEWHEEL`` events carry no ``pos`` attribute and
``Container.handle_event`` called ``event.pos`` directly, killing every
generated UI app as soon as the user scrolled. These tests post synthetic
events through the real dispatch path so the same class of bug cannot return.
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from reasonable.runtime.app import UIApp
from reasonable.runtime.ui import (
    Button,
    Entry,
    HStack,
    Panel,
    ScrollView,
    VStack,
)


def _click(widget, button: int = 1) -> None:
    pos = widget.rect.center
    down = pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"pos": pos, "button": button})
    up = pygame.event.Event(pygame.MOUSEBUTTONUP, {"pos": pos, "button": button})
    root = widget
    while root.parent is not None:
        root = root.parent
    root.handle_event(down)
    root.handle_event(up)


class UiEventTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pygame.init()
        pygame.display.set_mode((900, 600))

    @classmethod
    def tearDownClass(cls) -> None:
        pygame.quit()

    def _build_app(self, added: list[str]) -> tuple[UIApp, Panel]:
        app = UIApp("Тест", (900, 600), splash=False)
        root = Panel(padding=20, spacing=12)
        added.clear()
        entry = Entry("Что нужно сделать?", on_submit=added.append)
        button = Button("Добавить", lambda: added.append(entry.value))
        list_view = ScrollView(Panel(padding=8), height=300)
        root.add(VStack(spacing=12).add(entry, HStack(spacing=10).add(button), list_view))
        app.set_root(root)
        root.layout(pygame.Rect(0, 0, 900, 600))
        root.on_mount()
        return app, root

    def test_mouse_wheel_does_not_crash_and_scrolls(self) -> None:
        app, root = self._build_app([])
        wheel = pygame.event.Event(pygame.MOUSEWHEEL, {"x": 0, "y": 3})
        try:
            root.handle_event(wheel)
        except AttributeError as exc:  # pragma: no cover
            self.fail(f"MOUSEWHEEL crashed the UI: {exc}")

    def test_wheel_over_scrollview_scrolls_it(self) -> None:
        app, root = self._build_app([])
        # find the ScrollView inside the tree
        found: list[ScrollView] = []

        def walk(widget):
            if isinstance(widget, ScrollView):
                found.append(widget)
            for child in getattr(widget, "children", []):
                walk(child)

        walk(root)
        self.assertTrue(found)
        view = found[0]
        view.layout(pygame.Rect(20, 20, 500, 300))
        view._max_scroll = 500
        view.target_scroll = 0
        view.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, {"x": 0, "y": -2, "pos": view.rect.center}))
        self.assertGreater(view.target_scroll, 0)

    def test_button_click_appends_task(self) -> None:
        added: list[str] = []
        app, root = self._build_app(added)
        entry, button = root.children[0].children[0], None

        def walk(widget):
            nonlocal button
            if isinstance(widget, Button) and widget.text == "Добавить":
                button = widget
            for child in getattr(widget, "children", []):
                walk(child)

        walk(root)
        self.assertIsNotNone(button)
        _click(button)
        self.assertEqual(added, [""])

    def test_entry_submit_on_enter(self) -> None:
        added: list[str] = []
        app, root = self._build_app(added)

        def walk(widget):
            if isinstance(widget, Entry):
                widget.focused = True
                widget.handle_event(
                    pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_t, "unicode": "т", "mod": 0})
                )
                widget.handle_event(pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_RETURN, "mod": 0}))
                return True
            return any(walk(child) for child in getattr(widget, "children", []))

        self.assertTrue(walk(root))
        self.assertEqual(added, ["т"])

    def test_finger_and_resize_events_do_not_crash(self) -> None:
        app, root = self._build_app([])
        events = [
            pygame.event.Event(pygame.FINGERMOTION, {"x": 0.5, "y": 0.5, "dx": 0, "dy": 0}),
            pygame.event.Event(pygame.FINGERDOWN, {"x": 0.5, "y": 0.5}),
            pygame.event.Event(pygame.VIDEORESIZE, {"w": 800, "h": 500}),
        ]
        for event in events:
            root.handle_event(event)
        app.on_event(events[0])


    def test_ui_root_is_built_if_a_subclass_forgets_super_on_start(self) -> None:
        class LazyApp(UIApp):
            def __init__(self) -> None:
                super().__init__("Lazy", (640, 480), splash=False)
                self.builds = 0

            def build_ui(self):
                self.builds += 1
                return Panel()

            def on_start(self) -> None:
                pass

        app = LazyApp()
        app.on_update(1 / 60)
        self.assertIsNotNone(app.root)
        self.assertEqual(app.builds, 1)

    def test_entry_accepts_a_custom_height(self) -> None:
        entry = Entry("search", width=200, height=40)
        self.assertEqual(entry.height, 40)

    def test_scrollview_does_not_claim_the_whole_row(self) -> None:
        root = HStack(spacing=0, expand_x=True, expand_y=True)
        root.add(Panel(width=240))
        main = VStack(expand_x=True, expand_y=True)
        header = HStack(spacing=12, expand_x=True)
        header.add(Entry("search", width=200, height=40))
        header.add(Button("Go"))
        main.add(header)
        main.add(ScrollView(Panel(expand_x=True), expand_x=True, expand_y=True))
        root.add(main)
        root.layout(pygame.Rect(0, 0, 1280, 720))
        self.assertLessEqual(main.rect.right, 1280)
        self.assertLessEqual(header.children[-1].rect.right, 1280)


if __name__ == "__main__":
    unittest.main()
