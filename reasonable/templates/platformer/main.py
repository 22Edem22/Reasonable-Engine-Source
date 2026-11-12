"""Platformer starter for Reasonable Engine.

A small, proven base: one level, tile collisions, camera, double jump, dash,
coins, spikes, a goal and a clean entry point. Extend it instead of writing a
game loop and physics from scratch.

Run:  python main.py
Keys: A/D or arrows — move, Space/W/Up — jump (double), Shift/X — dash,
      R — restart, Esc — quit.
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
for _candidate in (PROJECT_DIR / "_engine", PROJECT_DIR):
    if (_candidate / "reasonable").is_dir() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

import pygame  # noqa: E402

try:  # Branding when launched directly; the launcher already plays it once.
    from reasonable.runtime import play_splash  # noqa: E402
except Exception:  # pragma: no cover - starter must run without the engine
    play_splash = None


def _settings() -> tuple[int, int, str]:
    try:
        data = json.loads((PROJECT_DIR / "project.json").read_text(encoding="utf-8"))
        window = data.get("window") or {}
        return (
            max(480, int(window.get("width") or 1280)),
            max(360, int(window.get("height") or 720)),
            str(window.get("title") or data.get("name") or "Platformer"),
        )
    except (OSError, ValueError, TypeError):
        return 1280, 720, "Platformer"


WIDTH, HEIGHT, TITLE = _settings()
TILE = 40
GRAVITY = 2100.0
MOVE_SPEED = 340.0
JUMP_SPEED = 690.0

SKY_TOP = (18, 24, 34)
SKY_BOTTOM = (10, 13, 19)
ACCENT = (217, 119, 87)
GOLD = (226, 193, 118)
WHITE = (232, 235, 240)
MUTED = (150, 158, 172)
GREEN = (126, 190, 154)
DANGER = (208, 112, 116)

LEVEL = [
    "############################################################",
    "#..........................................................#",
    "#...................o......................................#",
    "#.........####.............###..............o.............#",
    "#.................o........................####...........#",
    "#..........###...........####.....................o.......#",
    "#....................o....................................#",
    "#......o......................^^^.........................#",
    "#..S.......####.....................................E.....#",
    "############################################################",
]
ROWS = len(LEVEL)
COLS = max(len(row) for row in LEVEL)
LEVEL_W = COLS * TILE
LEVEL_H = ROWS * TILE


def font(size: int, bold: bool = False) -> pygame.font.Font:
    return pygame.font.SysFont("arial,dejavusans,verdana", size, bold=bold)


def draw_text(surface, text, size, color, pos, anchor="topleft", bold=False):
    image = font(size, bold).render(str(text), True, color)
    rect = image.get_rect(**{anchor: pos})
    surface.blit(image, rect)
    return rect


def tile_at(col: int, row: int) -> str:
    if 0 <= row < ROWS and 0 <= col < len(LEVEL[row]):
        return LEVEL[row][col]
    return "#" if row >= ROWS else "."


def solid_rects(rect: pygame.Rect) -> list[pygame.Rect]:
    """Solid tiles intersecting rect.

    Right/bottom use floor division so a body resting exactly on a tile edge
    still sees the tile below instead of hovering one pixel above it.
    """
    col0 = max(0, rect.left // TILE)
    col1 = min(COLS - 1, rect.right // TILE)
    row0 = max(0, rect.top // TILE)
    row1 = min(ROWS - 1, rect.bottom // TILE)
    result = []
    for row in range(row0, row1 + 1):
        for col in range(col0, col1 + 1):
            if tile_at(col, row) == "#":
                cell = pygame.Rect(col * TILE, row * TILE, TILE, TILE)
                if cell.colliderect(rect):
                    result.append(cell)
    return result


def hazard_at(rect: pygame.Rect) -> bool:
    if rect.top > LEVEL_H + TILE:
        return True
    col0 = max(0, rect.left // TILE)
    col1 = min(COLS - 1, rect.right // TILE)
    row0 = max(0, rect.top // TILE)
    row1 = min(ROWS - 1, rect.bottom // TILE)
    return any(tile_at(col, row) == "^" for row in range(row0, row1 + 1) for col in range(col0, col1 + 1))


class Player:
    def __init__(self, col: int, row: int) -> None:
        self.w = int(TILE * 0.68)
        self.h = int(TILE * 0.92)
        self.x = float(col * TILE + (TILE - self.w) / 2)
        self.y = float(row * TILE + TILE - self.h)
        self.vx = 0.0
        self.vy = 0.0
        self.on_ground = False
        self.jumps = 1
        self.facing = 1
        self.dash_time = 0.0
        self.dash_cooldown = 0.0

    @property
    def rect(self) -> pygame.Rect:
        return pygame.Rect(int(self.x), int(self.y), self.w, self.h)

    def update(self, dt: float, keys) -> None:
        left = keys[pygame.K_a] or keys[pygame.K_LEFT]
        right = keys[pygame.K_d] or keys[pygame.K_RIGHT]
        move = int(bool(right)) - int(bool(left))
        if move:
            self.facing = move
        if self.dash_time > 0:
            self.dash_time = max(0.0, self.dash_time - dt)
            self.vx = self.facing * 720.0
            self.vy = 0.0
        else:
            self.vx = move * MOVE_SPEED
            self.vy = min(1100.0, self.vy + GRAVITY * dt)
        if self.dash_cooldown > 0:
            self.dash_cooldown = max(0.0, self.dash_cooldown - dt)

        # X axis.
        self.x += self.vx * dt
        rect = self.rect
        for solid in solid_rects(rect):
            if self.vx > 0:
                rect.right = solid.left
            elif self.vx < 0:
                rect.left = solid.right
            self.x = float(rect.x)
            self.vx = 0.0
        self.x = max(0.0, min(float(LEVEL_W - self.w), self.x))

        # Y axis.
        self.y += self.vy * dt
        rect = self.rect
        self.on_ground = False
        for solid in solid_rects(rect):
            if self.vy > 0:
                rect.bottom = solid.top
                self.on_ground = True
            elif self.vy < 0:
                rect.top = solid.bottom
            self.y = float(rect.y)
            self.vy = 0.0
        if self.vy >= 0 and not self.on_ground:
            probe = pygame.Rect(rect.x, rect.bottom, rect.width, 2)
            for solid in solid_rects(probe):
                if solid.top >= rect.bottom - 1:
                    self.y = float(solid.top - self.h)
                    self.vy = 0.0
                    self.on_ground = True
                    break
        if self.on_ground:
            self.jumps = 1

    def jump(self) -> None:
        if self.on_ground:
            self.vy = -JUMP_SPEED
            self.on_ground = False
        elif self.jumps > 0:
            self.jumps -= 1
            self.vy = -JUMP_SPEED * 0.92

    def dash(self) -> None:
        if self.dash_cooldown <= 0.0 and self.dash_time <= 0.0:
            self.dash_time = 0.16
            self.dash_cooldown = 0.7


class Game:
    def __init__(self) -> None:
        pygame.init()
        try:
            pygame.mixer.init(22050, -16, 1, 512)
        except Exception:
            pass
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
        pygame.display.set_caption(TITLE)
        self.clock = pygame.time.Clock()
        self.player = Player(3, 8)
        self.coins = {(col, row) for row in range(ROWS) for col in range(COLS) if tile_at(col, row) == "o"}
        self.total_coins = max(1, len(self.coins))
        self.collected = 0
        self.goal = pygame.Rect(0, 0, TILE, TILE)
        for row in range(ROWS):
            for col in range(COLS):
                if tile_at(col, row) == "E":
                    self.goal = pygame.Rect(col * TILE, row * TILE, TILE, TILE)
        self.camera_x = 0.0
        self.offset_y = max(0, (HEIGHT - LEVEL_H) // 2)
        self.time = 0.0
        self.complete = False
        self.deaths = 0
        self._jump_latch = False
        self._dash_latch = False
        self._frames = 0
        self._limit = self._frame_limit()

    @staticmethod
    def _frame_limit() -> int:
        try:
            return max(0, int(os.environ.get("RE_FRAMES", "0") or 0))
        except (TypeError, ValueError):
            return 0

    def restart(self) -> None:
        self.player = Player(3, 8)
        self.collected = 0
        self.time = 0.0
        self.complete = False
        self._jump_latch = False
        self._dash_latch = False

    def update(self, dt: float) -> None:
        keys = pygame.key.get_pressed()
        self.player.update(dt, keys)
        if self.player.on_ground:
            self.time += dt
        jump = bool(keys[pygame.K_SPACE] or keys[pygame.K_w] or keys[pygame.K_UP])
        dash = bool(keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT] or keys[pygame.K_x])
        if jump and not self._jump_latch:
            self.player.jump()
        if dash and not self._dash_latch:
            self.player.dash()
        self._jump_latch = jump
        self._dash_latch = dash

        rect = self.player.rect
        for coin in list(self.coins):
            cell = pygame.Rect(coin[0] * TILE + TILE // 4, coin[1] * TILE + TILE // 4, TILE // 2, TILE // 2)
            if rect.colliderect(cell):
                self.coins.discard(coin)
                self.collected += 1
        if hazard_at(rect):
            self.deaths += 1
            self.restart()
        if rect.colliderect(self.goal):
            self.complete = True

        target = self.player.x + self.player.w / 2 - WIDTH / 2
        target = max(0.0, min(float(LEVEL_W - WIDTH), target))
        self.camera_x += (target - self.camera_x) * min(1.0, dt * 7.0)

    def draw(self) -> None:
        surface = self.screen
        for y in range(HEIGHT):
            t = y / max(1, HEIGHT - 1)
            color = tuple(int(SKY_TOP[i] * (1 - t) + SKY_BOTTOM[i] * t) for i in range(3))
            pygame.draw.line(surface, color, (0, y), (WIDTH, y))
        offset = int(self.camera_x)
        offset_y = self.offset_y
        for row in range(ROWS):
            for col in range(COLS):
                char = tile_at(col, row)
                x, y = col * TILE - offset, row * TILE + offset_y
                if x < -TILE or x > WIDTH:
                    continue
                if char == "#":
                    pygame.draw.rect(surface, (52, 61, 58), (x, y, TILE, TILE))
                    pygame.draw.rect(surface, (74, 88, 80), (x, y, TILE, 6))
                elif char == "^":
                    pygame.draw.polygon(surface, DANGER, [(x + 6, y + TILE), (x + TILE // 2, y + 8), (x + TILE - 6, y + TILE)])
        for col, row in self.coins:
            pygame.draw.circle(surface, GOLD, (col * TILE - offset + TILE // 2, row * TILE + offset_y + TILE // 2), 8)
        pygame.draw.rect(surface, GREEN, self.goal.move(-offset, offset_y), border_radius=6)
        rect = self.player.rect.move(-offset, offset_y)
        pygame.draw.rect(surface, ACCENT, rect, border_radius=5)
        pygame.draw.circle(surface, WHITE, (rect.centerx + self.player.facing * 5, rect.y + 10), 4)
        draw_text(surface, f"Монеты: {self.collected}/{self.total_coins}", 20, WHITE, (20, 18), bold=True)
        draw_text(surface, f"Время: {self.time:.1f}", 20, MUTED, (20, 46), bold=True)
        draw_text(surface, "A/D — бег · Space — прыжок (дважды) · Shift — дэш · R — рестарт", 15, MUTED, (WIDTH // 2, HEIGHT - 24), anchor="center")
        if self.complete:
            overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            overlay.fill((6, 8, 12, 170))
            surface.blit(overlay, (0, 0))
            draw_text(surface, "Уровень пройден!", 54, GOLD, (WIDTH // 2, HEIGHT // 2 - 30), anchor="center", bold=True)
            draw_text(surface, "R — ещё раз · Esc — выход", 22, WHITE, (WIDTH // 2, HEIGHT // 2 + 34), anchor="center")
        pygame.display.flip()

    def run(self) -> None:
        running = True
        while running:
            dt = min(0.05, self.clock.tick(60) / 1000.0)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    elif event.key == pygame.K_r:
                        self.restart()
            self.update(dt)
            self.draw()
            self._frames += 1
            if self._limit and self._frames >= self._limit:
                running = False
        pygame.quit()


def main() -> None:
    if play_splash is not None:
        try:
            if not play_splash((WIDTH, HEIGHT)):
                return
        except Exception:
            pass
    try:
        Game().run()
    except Exception:
        import traceback

        traceback.print_exc()
        try:
            pygame.quit()
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
