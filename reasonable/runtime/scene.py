"""Scene graph container and world helpers."""

from __future__ import annotations

import random
from typing import Callable, Iterable

import pygame

from .graphics import Camera, Node, ParticleSystem, TweenManager
from .utils import BG, draw_gradient


class Scene:
    def __init__(
        self,
        game=None,
        *,
        background=(8, 12, 20),
        gradient: tuple | None = None,
        camera_pos=(0, 0),
        camera_zoom: float = 1.0,
    ) -> None:
        self.game = game
        self.nodes: list[Node] = []
        self.camera = Camera(getattr(game, "size", (960, 540)), camera_pos, camera_zoom)
        self.tweens = TweenManager()
        self.particles = ParticleSystem(z=900)
        self.background = background
        self.gradient = gradient
        self.ui = None
        self.time = 0.0
        self._gradient_surface: pygame.Surface | None = None
        self._gradient_size = None

    # -- scene lifecycle ---------------------------------------------------
    def on_enter(self) -> None:
        pass

    def on_exit(self) -> None:
        pass

    def handle_event(self, event: pygame.event.Event) -> bool:
        return False

    def on_resize(self, size: tuple[int, int]) -> None:
        self.camera.resize(size)
        self._gradient_surface = None
        if self.ui is not None and hasattr(self.ui, "layout"):
            self.ui.layout(pygame.Rect(0, 0, *size))
        self.camera.update(0.016)

    # -- nodes -------------------------------------------------------------
    def add(self, *nodes: Node, z: int | None = None) -> Node | tuple[Node, ...]:
        added = []
        for node in nodes:
            if z is not None:
                node.z = z
            node.scene = self
            self.nodes.append(node)
            added.append(node)
        if len(added) == 1:
            return added[0]
        return tuple(added)

    def remove(self, node: Node) -> None:
        if node in self.nodes:
            self.nodes.remove(node)
            node.scene = None

    def clear(self, keep_particles: bool = False) -> None:
        self.nodes.clear()
        if not keep_particles:
            self.particles.particles.clear()

    def find(self, cls=None, tag: str | None = None, name: str | None = None) -> Node | None:
        for node in self.nodes:
            if cls is not None and not isinstance(node, cls):
                continue
            if tag is not None and tag not in node.tags:
                continue
            if name is not None and getattr(node, "name", None) != name:
                continue
            return node
        return None

    def find_all(self, cls=None, tag: str | None = None) -> list[Node]:
        result = []
        for node in self.nodes:
            if cls is not None and not isinstance(node, cls):
                continue
            if tag is not None and tag not in node.tags:
                continue
            result.append(node)
        return result

    def closest(self, position, tag: str | None = None, cls=None) -> Node | None:
        point = pygame.Vector2(position)
        candidates = self.find_all(cls=cls, tag=tag)
        if not candidates:
            return None
        return min(candidates, key=lambda node: (node.x - point.x) ** 2 + (node.y - point.y) ** 2)

    def distance(self, a: Node, b: Node) -> float:
        return pygame.Vector2(a.x - b.x, a.y - b.y).length()

    # -- frame -------------------------------------------------------------
    def update(self, dt: float) -> None:
        self.time += dt
        self.camera.update(dt)
        self.tweens.update(dt)
        for node in list(self.nodes):
            if not node.alive:
                continue
            node.update(dt)
        self.particles.update(dt)
        self.nodes = [node for node in self.nodes if node.alive]
        if self.ui is not None:
            self.ui.update(dt)
            self.ui.layout(pygame.Rect(0, 0, *self.camera.screen_size))

    def draw_background(self, surface: pygame.Surface) -> None:
        if callable(self.background):
            self.background(surface, self)
            return
        if self.gradient:
            size = surface.get_size()
            if self._gradient_surface is None or self._gradient_size != size:
                self._gradient_surface = pygame.Surface(size).convert()
                draw_gradient(self._gradient_surface, self._gradient_surface.get_rect(), self.gradient[0], self.gradient[1])
                self._gradient_size = size
            surface.blit(self._gradient_surface, (0, 0))
        else:
            surface.fill(self.background or BG)

    def draw(self, surface: pygame.Surface) -> None:
        self.draw_background(surface)
        for node in sorted(list(self.nodes), key=lambda item: item.z):
            if node.visible:
                node.draw(surface, self.camera)
        self.particles.draw(surface, self.camera)
        if self.ui is not None:
            self.ui.draw(surface)
        self.draw_debug(surface)

    def draw_debug(self, surface: pygame.Surface) -> None:
        game = self.game
        if game is not None and getattr(game, "debug", False):
            font = pygame.font.Font(None, 20)
            stats = f"{game.clock.get_fps():.0f} FPS  |  nodes: {len(self.nodes)}  |  particles: {len(self.particles.particles)}"
            image = font.render(stats, True, (240, 240, 240))
            surface.blit(image, (12, 12))

    # -- convenience effects ----------------------------------------------
    def burst(self, position, **kwargs) -> None:
        self.particles.burst(position, **kwargs)

    def shake(self, intensity: float = 8, duration: float = 0.25) -> None:
        self.camera.shake(intensity, duration)

    def flash(self, surface: pygame.Surface, color=(255, 255, 255), alpha: int = 80) -> None:
        overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        overlay.fill((*color[:3], alpha))
        surface.blit(overlay, (0, 0))


class GridScene(Scene):
    """Scene that draws a subtle grid; handy for editors and tech demos."""

    def __init__(self, game=None, *, grid_size: int = 64, grid_color=(20, 30, 46), **kwargs) -> None:
        super().__init__(game, **kwargs)
        self.grid_size = grid_size
        self.grid_color = grid_color

    def draw_background(self, surface: pygame.Surface) -> None:
        super().draw_background(surface)
        offset = self.camera.offset
        step = self.grid_size * self.camera.zoom
        start_x = int((-self.camera.pos.x * self.camera.zoom + self.camera.screen_size.x / 2 + offset.x) % step)
        start_y = int((-self.camera.pos.y * self.camera.zoom + self.camera.screen_size.y / 2 + offset.y) % step)
        for x in range(start_x, surface.get_width(), max(1, int(step))):
            pygame.draw.line(surface, self.grid_color, (x, 0), (x, surface.get_height()))
        for y in range(start_y, surface.get_height(), max(1, int(step))):
            pygame.draw.line(surface, self.grid_color, (0, y), (surface.get_width(), y))
