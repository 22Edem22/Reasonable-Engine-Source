"""Input state for desktop and touch devices, plus optional on-screen joystick."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pygame

from .utils import color, draw_rounded_rect, with_alpha


DEFAULT_ACTIONS: dict[str, list[int]] = {
    "left": [pygame.K_a, pygame.K_LEFT],
    "right": [pygame.K_d, pygame.K_RIGHT],
    "up": [pygame.K_w, pygame.K_UP],
    "down": [pygame.K_s, pygame.K_DOWN],
    "action": [pygame.K_SPACE, pygame.K_j],
    "confirm": [pygame.K_RETURN, pygame.K_SPACE],
    "cancel": [pygame.K_ESCAPE],
    "pause": [pygame.K_ESCAPE, pygame.K_p],
    "run": [pygame.K_LSHIFT, pygame.K_RSHIFT],
}


class Input:
    def __init__(self, actions: dict[str, list[int]] | None = None) -> None:
        self.actions: dict[str, list[int]] = {key: list(value) for key, value in DEFAULT_ACTIONS.items()}
        if actions:
            for key, value in actions.items():
                self.actions[key] = list(value)
        self.keys_down: set[int] = set()
        self.keys_just: set[int] = set()
        self.keys_released: set[int] = set()
        self.mouse_pos: tuple[int, int] = (0, 0)
        self.mouse_delta: tuple[int, int] = (0, 0)
        self.mouse_buttons: set[int] = set()
        self.mouse_just: set[int] = set()
        self.mouse_released: set[int] = set()
        self.wheel = (0, 0)
        self.touches: dict[int, tuple[int, int]] = {}
        self.touch_just: set[int] = set()
        self.touch_released: set[int] = set()
        self._last_mouse = (0, 0)

    def feed(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN:
            if event.key not in self.keys_down:
                self.keys_just.add(event.key)
            self.keys_down.add(event.key)
        elif event.type == pygame.KEYUP:
            self.keys_down.discard(event.key)
            self.keys_just.discard(event.key)
            self.keys_released.add(event.key)
        elif event.type == pygame.MOUSEMOTION:
            new_pos = event.pos
            self.mouse_delta = (new_pos[0] - self._last_mouse[0], new_pos[1] - self._last_mouse[1])
            self._last_mouse = new_pos
            self.mouse_pos = new_pos
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button in (4, 5):
                self.wheel = (self.wheel[0], self.wheel[1] + (1 if event.button == 4 else -1))
            else:
                self.mouse_buttons.add(event.button)
                self.mouse_just.add(event.button)
                self.mouse_pos = event.pos
                self._last_mouse = event.pos
        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button not in (4, 5):
                self.mouse_buttons.discard(event.button)
                self.mouse_released.add(event.button)
                self.mouse_pos = event.pos
                self._last_mouse = event.pos
        elif event.type == pygame.MOUSEWHEEL:
            self.wheel = (self.wheel[0] + event.x, self.wheel[1] + event.y)
        elif event.type == pygame.FINGERDOWN:
            pos = self._finger_pos(event)
            self.touches[event.finger_id] = pos
            self.touch_just.add(event.finger_id)
            self.mouse_pos = pos
        elif event.type == pygame.FINGERMOTION:
            self.touches[event.finger_id] = self._finger_pos(event)
        elif event.type == pygame.FINGERUP:
            pos = self._finger_pos(event)
            self.mouse_pos = pos
            self.touches.pop(event.finger_id, None)
            self.touch_just.discard(event.finger_id)
            self.touch_released.add(event.finger_id)

    def _finger_pos(self, event) -> tuple[int, int]:
        surface = pygame.display.get_surface()
        width, height = surface.get_size() if surface else (1, 1)
        return int(event.x * width), int(event.y * height)

    def clear_frame(self) -> None:
        self.keys_just.clear()
        self.keys_released.clear()
        self.mouse_just.clear()
        self.mouse_released.clear()
        self.mouse_delta = (0, 0)
        self.wheel = (0, 0)
        self.touch_just.clear()
        self.touch_released.clear()

    # -- keyboard / actions ------------------------------------------------
    def key_down(self, key: int) -> bool:
        return key in self.keys_down

    def key_pressed(self, key: int) -> bool:
        return key in self.keys_just

    def action_down(self, name: str) -> bool:
        return any(key in self.keys_down for key in self.actions.get(name, ()))

    def action_pressed(self, name: str) -> bool:
        return any(key in self.keys_just for key in self.actions.get(name, ()))

    def action_released(self, name: str) -> bool:
        return any(key in self.keys_released for key in self.actions.get(name, ()))

    def axis(self, negative: str, positive: str) -> float:
        value = 0.0
        if self.action_down(negative):
            value -= 1.0
        if self.action_down(positive):
            value += 1.0
        return value

    def vector(self) -> pygame.Vector2:
        return pygame.Vector2(
            self.axis("left", "right"),
            self.axis("up", "down"),
        )

    def normalized_vector(self) -> pygame.Vector2:
        vector = self.vector()
        if vector.length_squared() > 1:
            vector = vector.normalize()
        return vector

    def any_key_pressed(self) -> bool:
        return bool(self.keys_just)

    # -- mouse -------------------------------------------------------------
    def mouse_down(self, button: int = 1) -> bool:
        return button in self.mouse_buttons

    def mouse_pressed(self, button: int = 1) -> bool:
        return button in self.mouse_just

    def mouse_up(self, button: int = 1) -> bool:
        return button in self.mouse_released

    def touch_down(self) -> bool:
        return bool(self.touches)


class VirtualJoystick:
    """A translucent analog stick for Android builds.

    Add it to a scene and handle events before the scene; read ``vector`` each
    frame. The joystick also accepts the left mouse button, which makes it easy
    to test on desktop.
    """

    def __init__(
        self,
        center: tuple[int, int] | None = None,
        radius: int = 74,
        accent=("#35D6C4"),
        knob_color=("#F4F7FB"),
    ) -> None:
        self.center = pygame.Vector2(center or (140, 0))
        self.radius = radius
        self.accent = color(accent)
        self.knob_color = color(knob_color)
        self.active = False
        self.knob = pygame.Vector2(0, 0)
        self.vector = pygame.Vector2(0, 0)
        self._touch_id: int | None = None
        self._mouse = False
        self.alpha = 0.0

    def place(self, screen_size: tuple[int, int], margin: int = 36) -> None:
        self.center.update(margin + self.radius, screen_size[1] - margin - self.radius)

    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type in (pygame.FINGERDOWN, pygame.MOUSEBUTTONDOWN):
            if event.type == pygame.FINGERDOWN:
                surface = pygame.display.get_surface()
                width, height = surface.get_size() if surface else (1, 1)
                pos = pygame.Vector2(event.x * width, event.y * height)
                pointer_id = event.finger_id
            else:
                if event.button != 1:
                    return False
                pos = pygame.Vector2(event.pos)
                pointer_id = -1
                self._mouse = True
            if pos.distance_to(self.center) <= self.radius * 1.55:
                self.active = True
                self._touch_id = pointer_id
                self._update_knob(pos)
                return True
        elif event.type in (pygame.FINGERMOTION, pygame.MOUSEMOTION):
            if not self.active:
                return False
            if event.type == pygame.FINGERMOTION:
                surface = pygame.display.get_surface()
                width, height = surface.get_size() if surface else (1, 1)
                pos = pygame.Vector2(event.x * width, event.y * height)
                pointer_id = event.finger_id
            else:
                pos = pygame.Vector2(event.pos)
                pointer_id = -1
            if pointer_id == self._touch_id:
                self._update_knob(pos)
                return True
        elif event.type in (pygame.FINGERUP, pygame.MOUSEBUTTONUP):
            if not self.active:
                return False
            releasing = (
                (event.type == pygame.FINGERUP and event.finger_id == self._touch_id)
                or (event.type == pygame.MOUSEBUTTONUP and self._mouse and event.button == 1)
            )
            if releasing:
                self.active = False
                self._touch_id = None
                self._mouse = False
                self.vector.update(0, 0)
                return True
        return False

    def _update_knob(self, pos: pygame.Vector2) -> None:
        delta = pos - self.center
        if delta.length() > self.radius:
            delta.scale_to_length(self.radius)
        self.knob.update(delta)
        self.vector.update(delta.x / self.radius, delta.y / self.radius)
        if self.vector.length_squared() < 0.01:
            self.vector.update(0, 0)

    def update(self, dt: float) -> None:
        target = 1.0 if self.active else 0.0
        self.alpha += (target - self.alpha) * min(1.0, dt * 12)

    def draw(self, surface: pygame.Surface) -> None:
        if self.alpha <= 0.02:
            return
        base_alpha = int(70 * self.alpha)
        pygame.draw.circle(surface, with_alpha((8, 12, 20), base_alpha), self.center, self.radius)
        pygame.draw.circle(
            surface,
            with_alpha(self.accent, int(120 * self.alpha)),
            self.center,
            self.radius,
            max(1, int(2 * self.alpha)),
        )
        pygame.draw.circle(
            surface,
            with_alpha(self.accent, int(22 * self.alpha)),
            self.center,
            int(self.radius * 0.55),
        )
        knob = self.center + self.knob
        pygame.draw.circle(surface, with_alpha(self.knob_color, int(190 * self.alpha)), knob, int(self.radius * 0.32))
        pygame.draw.circle(
            surface,
            with_alpha(self.accent, int(220 * self.alpha)),
            knob,
            int(self.radius * 0.32),
            max(1, int(2 * self.alpha)),
        )


@dataclass
class TouchButton:
    """Simple circular touch button for game HUDs."""

    center: tuple[int, int]
    radius: int = 42
    label: str = ""
    accent=("#FF6B4A")
    down: bool = False
    _pressed: bool = False
    _touch_id: int | None = field(default=None, repr=False)
    _mouse: bool = field(default=False, repr=False)

    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.FINGERDOWN:
            surface = pygame.display.get_surface()
            width, height = surface.get_size() if surface else (1, 1)
            pos = pygame.Vector2(event.x * width, event.y * height)
            if pos.distance_to(self.center) <= self.radius * 1.35:
                self.down = True
                self._pressed = True
                self._touch_id = event.finger_id
                return True
        elif event.type == pygame.FINGERUP and event.finger_id == self._touch_id:
            self.down = False
            self._pressed = False
            self._touch_id = None
            return True
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if pygame.Vector2(event.pos).distance_to(self.center) <= self.radius * 1.35:
                self.down = True
                self._pressed = True
                self._mouse = True
                return True
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self._mouse:
            self.down = False
            self._pressed = False
            self._mouse = False
            return True
        return False

    @property
    def pressed_once(self) -> bool:
        if self._pressed:
            self._pressed = False
            return True
        return False

    def draw(self, surface: pygame.Surface) -> None:
        accent = color(self.accent)
        alpha = 160 if self.down else 95
        pygame.draw.circle(surface, with_alpha((8, 12, 20), alpha), self.center, self.radius)
        pygame.draw.circle(surface, with_alpha(accent, 190), self.center, self.radius, 2)
        if self.label:
            from .utils import get_font

            font = get_font(int(self.radius * 0.7), bold=True)
            image = font.render(self.label, True, accent)
            surface.blit(image, image.get_rect(center=self.center))
