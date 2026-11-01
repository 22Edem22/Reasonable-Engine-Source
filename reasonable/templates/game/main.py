"""__APP_TITLE__ — игра, созданная в Reasonable Engine.

Запуск:  python main.py
Управление: WASD / стрелки, мышь или экранный джойстик. Esc — пауза,
R — заново, F11 — полноэкранный режим. Размер и режим окна читаются из
project.json, поэтому их можно менять без правки кода.
"""

from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
for _candidate in (PROJECT_DIR / "_engine", PROJECT_DIR):
    if (_candidate / "reasonable").is_dir() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

import pygame

from reasonable.runtime import (
    Audio,
    Game,
    ParticleSystem,
    SaveData,
    Scene,
    Sprite,
    VirtualJoystick,
    color,
    draw_icon,
    draw_rounded_rect,
    draw_wrapped_text,
    get_font,
    load_image,
    render_text,
    with_alpha,
)

APP_NAME = __APP_NAME_REPR__


def window_settings() -> tuple[tuple[int, int], bool, bool]:
    """Read window preferences from project.json with safe defaults."""
    data = {}
    try:
        data = json.loads((PROJECT_DIR / "project.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    window = data.get("window") if isinstance(data, dict) else {}
    window = window if isinstance(window, dict) else {}
    try:
        width = max(320, int(window.get("width") or __WINDOW_WIDTH__))
        height = max(240, int(window.get("height") or __WINDOW_HEIGHT__))
    except (TypeError, ValueError):
        width, height = __WINDOW_WIDTH__, __WINDOW_HEIGHT__
    resizable = bool(window.get("resizable", __WINDOW_RESIZABLE__))
    fullscreen = str(window.get("mode") or "windowed").lower() == "fullscreen"
    if not window.get("mode"):
        fullscreen = __WINDOW_FULLSCREEN__
    return (width, height), resizable, fullscreen


WINDOW_SIZE, WINDOW_RESIZABLE, WINDOW_FULLSCREEN = window_settings()
ACCENT = pygame.Color("#D97757")
ACCENT_2 = pygame.Color("#7FA3C7")
GOLD = pygame.Color("#C9AD73")
WHITE = pygame.Color("#E7E9EC")
MUTED = pygame.Color("#9AA1AB")
DANGER = pygame.Color("#C98A90")


def asset(relative: str):
    path = PROJECT_DIR / "assets" / relative
    if path.exists():
        return load_image(path)
    if "star" in relative:
        return make_star_surface(56)
    if "slime" in relative:
        return make_blob_surface(72, (141, 184, 160))
    return make_blob_surface(84, (217, 119, 87))


def make_star_surface(size: int) -> pygame.Surface:
    surface = pygame.Surface((size, size), pygame.SRCALPHA)
    center = (size // 2, size // 2)
    points = []
    for index in range(16):
        angle = -math.pi / 2 + index * math.pi / 8
        radius = size * 0.46 if index % 2 == 0 else size * 0.18
        points.append((center[0] + math.cos(angle) * radius, center[1] + math.sin(angle) * radius))
    pygame.draw.polygon(surface, (95, 77, 45), points)
    inner = [(center[0] + (x - center[0]) * 0.86, center[1] + (y - center[1]) * 0.86) for x, y in points]
    pygame.draw.polygon(surface, (201, 173, 115), inner)
    pygame.draw.circle(surface, (255, 255, 255), center, max(2, size // 12))
    return surface


def make_blob_surface(size: int, fill) -> pygame.Surface:
    surface = pygame.Surface((size, size), pygame.SRCALPHA)
    pygame.draw.ellipse(surface, (23, 26, 32), (2, size * 0.2, size - 4, size * 0.74))
    pygame.draw.ellipse(surface, fill, (6, size * 0.24, size - 12, size * 0.66))
    pygame.draw.circle(surface, (255, 255, 255), (int(size * 0.36), int(size * 0.44)), max(3, size // 9))
    pygame.draw.circle(surface, (255, 255, 255), (int(size * 0.64), int(size * 0.44)), max(3, size // 9))
    pygame.draw.circle(surface, (23, 26, 32), (int(size * 0.37), int(size * 0.45)), max(1, size // 22))
    pygame.draw.circle(surface, (23, 26, 32), (int(size * 0.63), int(size * 0.45)), max(1, size // 22))
    return surface


class Star(Sprite):
    def __init__(self, x: float, y: float) -> None:
        super().__init__(asset("sprites/star.png"), x, y, z=20)
        self.scale.update(0.8, 0.8)
        self.base_y = y
        self.phase = random.uniform(0, math.tau)
        self.spin = random.choice((-1, 1)) * random.uniform(45, 110)
        self.born = 0.0
        self.angle = random.uniform(0, 360)

    def update(self, dt: float) -> None:
        self.born += dt
        self.angle += self.spin * dt
        self.y = self.base_y + math.sin(self.born * 2.4 + self.phase) * 7
        self.scale.update(0.8 + math.sin(self.born * 3.1) * 0.05, 0.8 + math.sin(self.born * 3.1) * 0.05)


class Slime(Sprite):
    def __init__(self, x: float, y: float, speed: float) -> None:
        super().__init__(asset("sprites/slime.png"), x, y, z=15)
        self.speed = speed
        self.phase = random.uniform(0, math.tau)
        self.wobble = 0.0
        self.shadow = True
        self.shadow_color = (0, 0, 0, 55)

    def update(self, dt: float) -> None:
        self.wobble += dt * 4
        self.scale.update(1 + math.sin(self.wobble) * 0.035, 1 - math.sin(self.wobble) * 0.045)


class WorldScene(Scene):
    def __init__(self, game: "SparkGame") -> None:
        super().__init__(
            game,
            background=(15, 17, 21),
            camera_pos=(game.size[0] / 2, game.size[1] / 2),
            camera_zoom=1.0,
        )
        self.game = game
        self.width, self.height = game.size
        self.state = "playing"
        self.score = 0
        self.best = int(game.save.get("best", 0))
        self.hearts = 3
        self.invulnerable = 0.0
        self.spawn_timer = 0.0
        self.play_time = 0.0
        self.flash = 0.0
        self.joystick = VirtualJoystick(radius=70)
        self.joystick.place((self.width, self.height), margin=42)
        self.particles = ParticleSystem(z=500)
        self.add(self.particles)
        self._background = asset("background.png") if (PROJECT_DIR / "assets" / "background.png").exists() else None
        self._dust = [
            [random.uniform(0, self.width), random.uniform(0, self.height), random.uniform(6, 22), random.uniform(0.3, 1.0)]
            for _ in range(46)
        ]
        self.reset()

    # ------------------------------------------------------------------
    def reset(self) -> None:
        self.clear(keep_particles=False)
        self.add(self.particles)
        self.score = 0
        self.hearts = 3
        self.invulnerable = 0.0
        self.spawn_timer = 0.0
        self.play_time = 0.0
        self.state = "playing"
        self.stars: list[Star] = []
        self.enemies: list[Slime] = []
        self.player = Sprite(asset("sprites/player.png"), self.width / 2, self.height * 0.62, z=30)
        self.player.shadow = True
        self.player.shadow_color = (0, 0, 0, 70)
        self.player.scale.update(0.92, 0.92)
        self.add(self.player)
        self.player_flash = 0.0
        for _ in range(7):
            self.spawn_star()
        self.hint_timer = 5.2

    def spawn_star(self) -> None:
        margin = 90
        star = Star(
            random.uniform(margin, self.width - margin),
            random.uniform(self.height * 0.18, self.height * 0.8),
        )
        self.stars.append(star)
        self.add(star)

    def spawn_enemy(self) -> None:
        side = random.choice(("left", "right", "top", "bottom"))
        margin = 60
        if side == "left":
            x, y = -margin, random.uniform(80, self.height - 80)
        elif side == "right":
            x, y = self.width + margin, random.uniform(80, self.height - 80)
        elif side == "top":
            x, y = random.uniform(80, self.width - 80), -margin
        else:
            x, y = random.uniform(80, self.width - 80), self.height + margin
        speed = random.uniform(72, 108) + min(70, self.play_time * 1.4)
        slime = Slime(x, y, speed)
        self.enemies.append(slime)
        self.add(slime)

    # ------------------------------------------------------------------
    def handle_event(self, event: pygame.event.Event) -> bool:
        if self.joystick.handle_event(event):
            return True
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                if self.state == "playing":
                    self.state = "paused"
                elif self.state == "paused":
                    self.state = "playing"
                return True
            if event.key in (pygame.K_r, pygame.K_RETURN) and self.state == "over":
                self.reset()
                return True
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.state == "over" and self.restart_rect().collidepoint(event.pos):
                self.reset()
                return True
            if self.state == "paused" and self.resume_rect().collidepoint(event.pos):
                self.state = "playing"
                return True
        return False

    def on_resize(self, size: tuple[int, int]) -> None:
        old_width, old_height = self.width, self.height
        super().on_resize(size)
        self.width, self.height = size
        if old_width and old_height:
            sx, sy = size[0] / old_width, size[1] / old_height
            for node in self.nodes:
                node.x *= sx
                node.y *= sy
        self.joystick.place(size, margin=36)

    def restart_rect(self) -> pygame.Rect:
        return pygame.Rect(self.width // 2 - 110, self.height // 2 + 58, 220, 52)

    def resume_rect(self) -> pygame.Rect:
        return pygame.Rect(self.width // 2 - 110, self.height // 2 - 26, 220, 52)

    # ------------------------------------------------------------------
    def update(self, dt: float) -> None:
        self.joystick.update(dt)
        if self.state == "playing":
            self.play_time += dt
            self.hint_timer = max(0.0, self.hint_timer - dt)
            self.invulnerable = max(0.0, self.invulnerable - dt)
            self.player_flash = max(0.0, self.player_flash - dt)
            self.move_player(dt)
            self.update_stars(dt)
            self.update_enemies(dt)
            self.spawn_timer -= dt
            if self.spawn_timer <= 0:
                self.spawn_enemy()
                self.spawn_timer = max(0.75, 2.0 - self.play_time * 0.012)
            if random.random() < dt * 8:
                self.particles.burst(
                    (random.uniform(0, self.width), self.height + 8),
                    count=1,
                    colors=(ACCENT_2, (127, 163, 199)),
                    speed=(30, 70),
                    size=(1, 2.4),
                    life=(1.2, 2.4),
                    angle=(250, 290),
                    additive=False,
                )
        self.flash = max(0.0, self.flash - dt * 3)
        super().update(dt)

    def move_player(self, dt: float) -> None:
        vector = self.game.input.normalized_vector()
        if self.joystick.active and self.joystick.vector.length_squared() > 0.02:
            vector = self.joystick.vector
        speed = 330
        self.player.x += vector.x * speed * dt
        self.player.y += vector.y * speed * dt
        margin_x, margin_y = 52, 42
        self.player.x = max(margin_x, min(self.width - margin_x, self.player.x))
        self.player.y = max(margin_y, min(self.height - margin_y, self.player.y))
        if abs(vector.x) > 0.08:
            self.player.flip_x = vector.x < 0
        tilt = max(-8, min(8, vector.x * 7))
        self.player.angle += (tilt - self.player.angle) * min(1.0, dt * 12)
        self.player.scale.x = abs(self.player.scale.x) or 0.92
        if random.random() < dt * 9:
            self.particles.burst(
                (self.player.x, self.player.y + 34),
                count=1,
                colors=(GOLD, ACCENT),
                speed=(8, 30),
                size=(1, 2.5),
                life=(0.2, 0.55),
                angle=(240, 300),
                additive=True,
            )

    def update_stars(self, dt: float) -> None:
        for star in list(self.stars):
            if pygame.Vector2(star.x, star.y).distance_to((self.player.x, self.player.y)) < 46:
                self.score += 1
                self.best = max(self.best, self.score)
                self.stars.remove(star)
                star.kill()
                self.particles.burst(
                    (star.x, star.y),
                    count=26,
                    colors=(GOLD, (255, 255, 255), ACCENT),
                    speed=(50, 240),
                    size=(1.5, 4),
                    life=(0.25, 0.75),
                    additive=True,
                )
                self.camera.shake(5, 0.16)
                self.spawn_star()
                if self.score % 10 == 0:
                    self.hearts = min(5, self.hearts + 1)
                    self.particles.burst(
                        (self.width / 2, 80),
                        count=40,
                        colors=(ACCENT_2, WHITE),
                        speed=(60, 260),
                        size=(2, 5),
                        life=(0.5, 1.2),
                    )

    def update_enemies(self, dt: float) -> None:
        player_pos = pygame.Vector2(self.player.x, self.player.y)
        for enemy in list(self.enemies):
            direction = player_pos - pygame.Vector2(enemy.x, enemy.y)
            if direction.length_squared() > 1:
                direction = direction.normalize()
            enemy.x += direction.x * enemy.speed * dt
            enemy.y += direction.y * enemy.speed * dt
            enemy.flip_x = direction.x < 0
            if self.invulnerable <= 0 and pygame.Vector2(enemy.x, enemy.y).distance_to(player_pos) < 52:
                self.hearts -= 1
                self.invulnerable = 1.15
                self.player_flash = 0.6
                self.flash = 0.8
                self.camera.shake(13, 0.4)
                self.particles.burst(
                    (self.player.x, self.player.y),
                    count=36,
                    colors=(DANGER, ACCENT, (255, 255, 255)),
                    speed=(70, 280),
                    size=(2, 5),
                    life=(0.3, 0.8),
                )
                self.enemies.remove(enemy)
                enemy.kill()
                if self.hearts <= 0:
                    self.game_over()
                break

    def game_over(self) -> None:
        self.state = "over"
        self.game.save.set("best", self.best)
        self.game.save.save()
        self.particles.burst(
            (self.width / 2, self.height / 2),
            count=80,
            colors=(DANGER, GOLD, ACCENT_2),
            speed=(60, 380),
            size=(2, 6),
            life=(0.6, 1.5),
        )
        self.camera.shake(18, 0.6)

    # ------------------------------------------------------------------
    def draw_background(self, surface: pygame.Surface) -> None:
        if self._background is not None:
            image = pygame.transform.smoothscale(self._background, surface.get_size())
            surface.blit(image, (0, 0))
            veil = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
            veil.fill((10, 11, 14, 86))
            surface.blit(veil, (0, 0))
        else:
            surface.fill((15, 17, 21))
            for index in range(7):
                radius = int(self.width * (0.1 + index * 0.06))
                pygame.draw.circle(
                    surface,
                    (22 + index * 4, 24 + index * 4, 29 + index * 5),
                    (int(self.width * 0.5), int(self.height * 0.42)),
                    radius,
                )
        for x, y, speed, size in self._dust:
            drift = (self.time * speed + x) % (self.width + 60) - 30
            alpha = int(40 + 60 * (0.5 + 0.5 * math.sin(self.time * 1.7 + x)))
            pygame.draw.circle(surface, with_alpha((185, 190, 198), alpha), (int(drift), int(y)), int(size))

    def draw_hud(self, surface: pygame.Surface) -> None:
        width, height = surface.get_size()
        bar = pygame.Surface((width, 96), pygame.SRCALPHA)
        for y in range(96):
            alpha = int(132 * (1 - y / 96))
            pygame.draw.line(bar, (10, 11, 14, alpha), (0, y), (width, y))
        surface.blit(bar, (0, 0))
        draw_rounded_rect(surface, pygame.Rect(24, 22, 156, 52), with_alpha((23, 26, 32), 210), 16, border=with_alpha((78, 83, 92), 110))
        star_icon = make_star_surface(30)
        surface.blit(star_icon, (38, 33))
        score_image = get_font(26, bold=True).render(str(self.score), True, WHITE)
        surface.blit(score_image, (82, 31))
        best_font = get_font(12, bold=True)
        best_image = best_font.render(f"РЕКОРД {self.best}", True, MUTED)
        surface.blit(best_image, (84, 50))
        for index in range(5):
            heart_x = width - 58 - index * 40
            filled = index < self.hearts
            draw_heart(surface, (heart_x, 44), 15, DANGER if filled else (58, 62, 69), filled)
        if self.hint_timer > 0:
            alpha = int(200 * min(1.0, self.hint_timer / 1.2))
            hint = get_font(14, bold=True).render(
                "WASD / джойстик  •  Esc — пауза  •  F11 — полный экран", True, WHITE
            )
            hint.set_alpha(alpha)
            surface.blit(hint, hint.get_rect(center=(width // 2, height - 34)))
        if self.state == "paused":
            self.draw_overlay(surface, "ПАУЗА", "Продолжайте, когда будете готовы", "ПРОДОЛЖИТЬ")
        elif self.state == "over":
            self.draw_overlay(surface, "ИГРА ОКОНЧЕНА", f"Собрано звёзд: {self.score}   •   Рекорд: {self.best}", "ИГРАТЬ СНОВА")

    def draw_overlay(self, surface: pygame.Surface, title: str, subtitle: str, button_text: str) -> None:
        width, height = surface.get_size()
        veil = pygame.Surface((width, height), pygame.SRCALPHA)
        veil.fill((10, 11, 14, 200))
        surface.blit(veil, (0, 0))
        panel = pygame.Rect(width // 2 - 260, height // 2 - 150, 520, 320)
        draw_rounded_rect(surface, panel, (23, 26, 32), 26, border=(58, 54, 49), shadow=True)
        title_image = render_text(title, 40 if width > 700 else 32, WHITE, bold=True, display=True)
        surface.blit(title_image, title_image.get_rect(center=(width // 2, panel.y + 82)))
        sub_image = get_font(15).render(subtitle, True, MUTED)
        surface.blit(sub_image, sub_image.get_rect(center=(width // 2, panel.y + 140)))
        rect = self.resume_rect() if self.state == "paused" else self.restart_rect()
        draw_rounded_rect(surface, rect, ACCENT, 16, border=(235, 143, 111), shadow=True)
        label = get_font(16, bold=True).render(button_text, True, (27, 17, 13))
        surface.blit(label, label.get_rect(center=rect.center))
        hint = get_font(12).render("R — начать заново" if self.state == "over" else "Esc — продолжить", True, MUTED)
        surface.blit(hint, hint.get_rect(center=(width // 2, panel.bottom - 28)))

    def draw(self, surface: pygame.Surface) -> None:
        super().draw(surface)
        self.draw_hud(surface)
        self.joystick.draw(surface)
        if self.player_flash > 0 and self.player.visible:
            pygame.draw.circle(surface, with_alpha(DANGER, 60), (int(self.player.x), int(self.player.y)), 46, 2)
        if self.flash > 0:
            overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
            overlay.fill((255, 80, 80, int(70 * self.flash)))
            surface.blit(overlay, (0, 0))
        if self.state == "playing" and self.hint_timer > 0:
            arrow_y = self.height - 74 + math.sin(self.time * 3) * 4
            draw_icon(surface, "chevron_right", pygame.Rect(self.width // 2 - 9, int(arrow_y), 18, 18), with_alpha(MUTED, 120), 2)


def draw_heart(surface: pygame.Surface, center, size: int, fill, filled: bool = True) -> None:
    cx, cy = center
    radius = size * 0.32
    pygame.draw.circle(surface, fill, (int(cx - radius), int(cy - radius * 0.35)), int(radius))
    pygame.draw.circle(surface, fill, (int(cx + radius), int(cy - radius * 0.35)), int(radius))
    pygame.draw.polygon(surface, fill, [(cx - radius * 1.9, cy - radius * 0.15), (cx + radius * 1.9, cy - radius * 0.15), (cx, cy + size * 0.95)])
    if not filled:
        pygame.draw.circle(surface, (23, 26, 32), (int(cx - radius), int(cy - radius * 0.35)), int(radius * 0.55))
        pygame.draw.circle(surface, (23, 26, 32), (int(cx + radius), int(cy - radius * 0.35)), int(radius * 0.55))


class SparkGame(Game):
    def __init__(self) -> None:
        super().__init__(
            APP_NAME,
            WINDOW_SIZE,
            splash=True,
            splash_skippable=True,
            splash_accent="#D97757",
            background=(15, 17, 21),
            resizable=WINDOW_RESIZABLE,
            fullscreen=WINDOW_FULLSCREEN,
        )
        self.save = SaveData(APP_NAME, "save.json")

    def on_start(self) -> None:
        self.set_scene(WorldScene(self))


def main() -> None:
    SparkGame().run()


if __name__ == "__main__":
    main()
