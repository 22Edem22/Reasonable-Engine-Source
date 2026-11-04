"""__APP_TITLE__ — игра, созданная в Reasonable Engine.

Запуск:  python main.py

Управление:
  WASD / стрелки / экранный джойстик — движение
  Пробел / Shift — рывок (неуязвимость)
  Esc / P — пауза, R — заново, M — меню, F11 — полный экран
  Меню: стрелки + Enter или мышь

Это полноценный вертикальный срез: титульный экран, обучение, волны врагов,
комбо, бонусы, звук, сохранение рекорда и аккуратный экран результатов. Меняйте
код как угодно — размер и режим окна читаются из project.json.
"""

from __future__ import annotations

import array
import json
import math
import random
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    # PyInstaller build: project files (project.json, data.json) sit next to
    # the executable; bundled data lives inside the PyInstaller bundle.
    PROJECT_DIR = Path(sys.executable).resolve().parent
    BUNDLE_DIR = Path(__file__).resolve().parent
else:
    PROJECT_DIR = Path(__file__).resolve().parent
    BUNDLE_DIR = PROJECT_DIR
for _candidate in (PROJECT_DIR / "_engine", PROJECT_DIR, BUNDLE_DIR):
    if (_candidate / "reasonable").is_dir() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))


def _project_file(relative: str) -> Path:
    """Locate a project file in both source and frozen (exe) modes."""
    candidate = PROJECT_DIR / relative
    if candidate.exists():
        return candidate
    return BUNDLE_DIR / relative


# Importing the package installs the engine's warning filters before pygame
# pulls in deprecated pkg_resources on some builds.
import reasonable  # noqa: F401,E402

import pygame  # noqa: E402

from reasonable.runtime import (  # noqa: E402
    Game,
    ParticleSystem,
    SaveData,
    Scene,
    Sprite,
    VirtualJoystick,
    add_scene_objects,
    draw_glow,
    draw_rounded_rect,
    get_font,
    load_image,
    load_scene_data,
    with_alpha,
)

APP_NAME = __APP_NAME_REPR__


def window_settings() -> tuple[tuple[int, int], bool, bool]:
    """Read window preferences from project.json with safe defaults."""
    data = {}
    try:
        data = json.loads(_project_file("project.json").read_text(encoding="utf-8"))
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
ACCENT_SOFT = pygame.Color("#E8A184")
ACCENT_2 = pygame.Color("#7FA3C7")
GOLD = pygame.Color("#C9AD73")
WHITE = pygame.Color("#E7E9EC")
MUTED = pygame.Color("#9AA1AB")
DANGER = pygame.Color("#C98A90")
GREEN = pygame.Color("#8DB8A0")
BG_TOP = (15, 17, 22)
BG_BOTTOM = (9, 10, 14)

POWER_KINDS = ("shield", "magnet", "slow", "heart")
POWER_COLORS = {
    "shield": (127, 163, 199),
    "magnet": (201, 173, 115),
    "slow": (141, 184, 160),
    "heart": (201, 138, 144),
}
POWER_LABELS = {"shield": "S", "magnet": "M", "slow": "T", "heart": "+"}


# ---------------------------------------------------------------------------
# Procedural sound
# ---------------------------------------------------------------------------
class Sfx:
    """Tiny mono synthesiser: no asset files, works offline and on Android.

    The mixer is initialised in mono, so a sound is just a 16-bit sample
    buffer. Everything is wrapped in ``try/except`` — a machine without an
    audio device still gets a fully playable game.
    """

    def __init__(self) -> None:
        self.enabled = True
        self.ready = False
        self.rate = 22050
        self.channels = 1
        self.sounds: dict[str, pygame.mixer.Sound] = {}

    def init(self) -> None:
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(22050, -16, 1, 512)
            info = pygame.mixer.get_init()
            if not info:
                return
            self.rate, _, self.channels = info
            self.rate = int(self.rate)
            self.channels = int(self.channels or 1)
            self.ready = True
            self.sounds = {
                "click": self._sweep(700, 420, 0.07, 0.25, "square"),
                "star": self._sweep(780, 1320, 0.12, 0.22, "sine"),
                "combo": self._sweep(1040, 1560, 0.10, 0.18, "sine"),
                "dash": self._sweep(220, 880, 0.18, 0.20, "saw"),
                "hit": self._sweep(220, 70, 0.28, 0.32, "saw"),
                "power": self._sweep(520, 1040, 0.22, 0.24, "sine"),
                "wave": self._sweep(392, 784, 0.30, 0.22, "triangle"),
                "over": self._sweep(420, 90, 0.65, 0.30, "triangle"),
            }
        except Exception:
            self.ready = False
            self.sounds = {}

    def _sweep(self, start: float, end: float, duration: float, volume: float, wave: str) -> pygame.mixer.Sound:
        frames = max(1, int(self.rate * duration))
        samples = array.array("h")
        phase = 0.0
        for index in range(frames):
            progress = index / frames
            frequency = start + (end - start) * progress
            phase += (math.tau * frequency) / self.rate
            if wave == "square":
                value = 1.0 if math.sin(phase) >= 0 else -1.0
            elif wave == "saw":
                value = 2.0 * ((phase / math.tau) % 1.0) - 1.0
            elif wave == "triangle":
                value = 2.0 * abs(2.0 * ((phase / math.tau) % 1.0) - 1.0) - 1.0
            else:
                value = math.sin(phase)
            # Soft attack and a long release: avoids clicks at the ends.
            attack = min(1.0, progress / 0.08)
            release = min(1.0, (1.0 - progress) / 0.35)
            envelope = attack * release * (1.0 - 0.25 * progress)
            sample = int(max(-1.0, min(1.0, value * envelope * volume)) * 32767)
            for _ in range(self.channels):
                samples.append(sample)
        return pygame.mixer.Sound(buffer=samples.tobytes())

    def play(self, name: str, volume: float = 1.0) -> None:
        if not self.enabled or not self.ready:
            return
        sound = self.sounds.get(name)
        if sound is None:
            return
        try:
            sound.set_volume(max(0.0, min(1.0, volume)))
            sound.play()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Art helpers
# ---------------------------------------------------------------------------
def asset(relative: str):
    path = _project_file("assets/" + relative)
    if path.exists():
        return load_image(path)
    if "star" in relative:
        return make_star_surface(56)
    if "slime" in relative:
        return make_blob_surface(72, (141, 184, 160))
    if "player" in relative:
        return make_hero_surface(96)
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
    pygame.draw.arc(surface, (23, 26, 32), (size * 0.42, size * 0.56, size * 0.16, size * 0.12), 0.2, 2.9, 2)
    return surface


def make_hero_surface(size: int) -> pygame.Surface:
    surface = pygame.Surface((size, size), pygame.SRCALPHA)
    body = pygame.Rect(int(size * 0.2), int(size * 0.28), int(size * 0.6), int(size * 0.52))
    pygame.draw.ellipse(surface, (38, 45, 58), body.move(0, int(size * 0.1)))
    pygame.draw.ellipse(surface, (63, 134, 255), body)
    pygame.draw.ellipse(surface, (255, 209, 166), (int(size * 0.31), int(size * 0.08), int(size * 0.38), int(size * 0.38)))
    pygame.draw.arc(surface, (58, 36, 24), (int(size * 0.27), int(size * 0.04), int(size * 0.46), int(size * 0.32)), 3.14, 6.28, max(2, size // 22))
    pygame.draw.circle(surface, (20, 33, 61), (int(size * 0.43), int(size * 0.26)), max(2, size // 32))
    pygame.draw.circle(surface, (20, 33, 61), (int(size * 0.57), int(size * 0.26)), max(2, size // 32))
    return surface


def make_orb_surface(size: int, fill, label: str) -> pygame.Surface:
    surface = pygame.Surface((size, size), pygame.SRCALPHA)
    center = size // 2
    pygame.draw.circle(surface, (*fill, 60), (center, center), center)
    pygame.draw.circle(surface, (*fill, 220), (center, center), int(size * 0.38))
    pygame.draw.circle(surface, (255, 255, 255, 210), (int(size * 0.40), int(size * 0.34)), max(2, size // 10))
    font = get_font(max(10, int(size * 0.30)), bold=True)
    image = font.render(label, True, (16, 17, 21))
    surface.blit(image, image.get_rect(center=(center, center)))
    return surface


def draw_heart(surface: pygame.Surface, center, size: int, fill, filled: bool = True) -> None:
    cx, cy = center
    radius = size * 0.32
    pygame.draw.circle(surface, fill, (int(cx - radius), int(cy - radius * 0.35)), int(radius))
    pygame.draw.circle(surface, fill, (int(cx + radius), int(cy - radius * 0.35)), int(radius))
    pygame.draw.polygon(
        surface,
        fill,
        [(cx - radius * 1.9, cy - radius * 0.15), (cx + radius * 1.9, cy - radius * 0.15), (cx, cy + size * 0.95)],
    )
    if not filled:
        pygame.draw.circle(surface, (23, 26, 32), (int(cx - radius), int(cy - radius * 0.35)), int(radius * 0.55))
        pygame.draw.circle(surface, (23, 26, 32), (int(cx + radius), int(cy - radius * 0.35)), int(radius * 0.55))


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------
class Star(Sprite):
    def __init__(self, x: float, y: float) -> None:
        super().__init__(asset("sprites/star.png"), x, y, z=20)
        self.base_scale = 0.40
        self.scale.update(self.base_scale, self.base_scale)
        self.base_y = y
        self.phase = random.uniform(0, math.tau)
        self.spin = random.choice((-1, 1)) * random.uniform(45, 110)
        self.born = 0.0
        self.angle = random.uniform(0, 360)
        self.value = 10

    def update(self, dt: float) -> None:
        self.born += dt
        self.angle += self.spin * dt
        self.y = self.base_y + math.sin(self.born * 2.4 + self.phase) * 6
        pulse = 0.40 + math.sin(self.born * 3.1) * 0.035
        self.scale.update(pulse, pulse)


class Slime(Sprite):
    def __init__(self, x: float, y: float, speed: float, tint=None, scale: float = 1.0) -> None:
        image = asset("sprites/slime.png")
        if tint is not None:
            image = image.copy()
            image.fill((*tint, 255), special_flags=pygame.BLEND_RGBA_MULT)
        super().__init__(image, x, y, z=15)
        self.speed = speed
        self.phase = random.uniform(0, math.tau)
        self.wobble = 0.0
        self.base_scale = 0.46 * scale
        self.scale.update(self.base_scale, self.base_scale)
        self.shadow = True
        self.shadow_color = (0, 0, 0, 55)
        self.radius = 26 * scale

    def update(self, dt: float) -> None:
        self.wobble += dt * 4
        wobble = math.sin(self.wobble)
        self.scale.update(
            self.base_scale * (1 + wobble * 0.05),
            self.base_scale * (1 - wobble * 0.06),
        )


class PowerUp(Sprite):
    def __init__(self, x: float, y: float, kind: str) -> None:
        super().__init__(make_orb_surface(44, POWER_COLORS[kind], POWER_LABELS[kind]), x, y, z=18)
        self.kind = kind
        self.born = 0.0
        self.base_y = y

    def update(self, dt: float) -> None:
        self.born += dt
        self.y = self.base_y + math.sin(self.born * 3.4) * 5
        pulse = 1.0 + math.sin(self.born * 4.0) * 0.07
        self.scale.update(pulse, pulse)


class FloatingText:
    def __init__(self, text: str, x: float, y: float, fill=WHITE, size: int = 16) -> None:
        self.text = text
        self.x = x
        self.y = y
        self.fill = fill
        self.size = size
        self.life = 0.9
        self.age = 0.0

    def update(self, dt: float) -> bool:
        self.age += dt
        self.y -= 34 * dt
        return self.age < self.life

    def draw(self, surface: pygame.Surface, camera) -> None:
        alpha = int(255 * max(0.0, 1.0 - self.age / self.life))
        image = get_font(self.size, bold=True).render(self.text, True, self.fill)
        image.set_alpha(alpha)
        screen = camera.world_to_screen((self.x, self.y))
        surface.blit(image, image.get_rect(center=(int(screen.x), int(screen.y))))


# ---------------------------------------------------------------------------
# Scenes
# ---------------------------------------------------------------------------
class WorldScene(Scene):
    """Title menu, playable run, pause and results in one coherent scene."""

    def __init__(self, game: "SparkGame") -> None:
        super().__init__(
            game,
            background=BG_TOP,
            camera_pos=(game.size[0] / 2, game.size[1] / 2),
            camera_zoom=1.0,
        )
        self.game = game
        self.width, self.height = game.size
        self.state = "menu"
        self.mouse_pos = (-100, -100)
        self.menu_index = 0
        self.best = int(game.save.get("best", 0))
        self.total_stars = int(game.save.get("total_stars", 0))
        self.runs = int(game.save.get("runs", 0))
        self.sfx = game.sfx
        self.joystick = VirtualJoystick(radius=70)
        self.joystick.place((self.width, self.height), margin=42)
        self.particles = ParticleSystem(z=500)
        self.add(self.particles)
        self._background = asset("background.png") if _project_file("assets/background.png").exists() else None
        # The visual scene editor writes scenes/main.json. Its visible objects
        # become backdrop geometry; hidden markers define where the player,
        # stars and slimes start. Editing the scene therefore changes the game.
        self.level_data = load_scene_data(_project_file("scenes/main.json"))
        self.reset_run()
        self.state = "menu"
        self._build_dust()

    # -- setup ---------------------------------------------------------
    def _build_dust(self) -> None:
        self._dust = [
            [random.uniform(0, self.width), random.uniform(0, self.height), random.uniform(6, 22), random.uniform(0.3, 1.0)]
            for _ in range(52)
        ]
        self._menu_stars = [
            [
                random.uniform(0, self.width),
                random.uniform(0, self.height),
                random.uniform(1.0, 2.8),
                random.uniform(0.4, 1.6),
                random.uniform(0, math.tau),
            ]
            for _ in range(74)
        ]

    def reset_run(self) -> None:
        self.clear(keep_particles=False)
        self.add(self.particles)
        self.state = "playing"
        self.score = 0
        self.record_at_start = self.best
        self.hearts = 3
        self.max_hearts = 5
        self.invulnerable = 0.0
        self.player_flash = 0.0
        self.flash = 0.0
        self.spawn_timer = 0.0
        self.power_timer = 8.0
        self.play_time = 0.0
        self.stars_collected = 0
        self.combo = 0
        self.combo_timer = 0.0
        self.best_combo = 0
        self.wave = 1
        self.wave_timer = 0.0
        self.wave_banner = 0.0
        self.dash_cd = 0.0
        self.dash_time = 0.0
        self.dash_dir = pygame.Vector2(0, 0)
        self.shield_time = 0.0
        self.magnet_time = 0.0
        self.slow_time = 0.0
        self.hint_timer = 6.4
        self.floating: list[FloatingText] = []
        self.stars: list[Star] = []
        self.enemies: list[Slime] = []
        self.powerups: list[PowerUp] = []
        level = self._scaled_level_data()
        player_start, star_points, slime_points = self._level_markers(level)
        # Visible scene objects (planets, title text) become backdrop nodes.
        add_scene_objects(self, level, base_dir=PROJECT_DIR)
        player_x, player_y = player_start or (self.width / 2, self.height * 0.62)
        self.player = Sprite(asset("sprites/player.png"), player_x, player_y, z=30)
        self.player.shadow = True
        self.player.shadow_color = (0, 0, 0, 70)
        self.player.base_scale = 0.40
        self.player.scale.update(0.40, 0.40)
        self.add(self.player)
        for x, y in star_points:
            self.spawn_star_at(x, y)
        for x, y in slime_points[:3]:
            self.spawn_enemy_at(x, y)
        while len(self.stars) < 7:
            self.spawn_star(initial=True)

    def _scaled_level_data(self) -> dict:
        """Scene coordinates are authored for the scene size, not the window."""
        size = self.level_data.get("size") or [self.width, self.height]
        try:
            base_w = max(1.0, float(size[0]))
            base_h = max(1.0, float(size[1]))
        except (TypeError, ValueError, IndexError):
            return self.level_data
        sx = self.width / base_w
        sy = self.height / base_h
        if abs(sx - 1.0) < 0.001 and abs(sy - 1.0) < 0.001:
            return self.level_data
        data = dict(self.level_data)
        objects = []
        for record in self.level_data.get("objects") or []:
            if not isinstance(record, dict):
                continue
            scaled = dict(record)
            for key in ("x", "y", "w", "h"):
                if key in scaled:
                    scaled[key] = float(scaled.get(key) or 0) * (sx if key in ("x", "w") else sy)
            objects.append(scaled)
        data["objects"] = objects
        return data

    def _level_markers(self, level_data: dict | None = None):
        """Read hidden spawn markers from scenes/main.json."""
        level_data = level_data or self.level_data
        player_start = None
        stars: list[tuple[float, float]] = []
        slimes: list[tuple[float, float]] = []
        for record in level_data.get("objects") or []:
            if not isinstance(record, dict) or not record.get("marker"):
                continue
            role = str(record.get("role") or "").lower()
            name = str(record.get("name") or "").lower()
            x = float(record.get("x") or 0) + float(record.get("w") or 0) / 2
            y = float(record.get("y") or 0) + float(record.get("h") or 0) / 2
            if role == "player" or "player" in name or "старт" in name:
                player_start = (x, y)
            elif role == "star" or "star" in name or "звезда" in name:
                stars.append((x, y))
            elif role == "slime" or "slime" in name or "слиз" in name:
                slimes.append((x, y))
        return player_start, stars, slimes

    def start_game(self) -> None:
        self.reset_run()
        self.runs += 1
        self.sfx.play("click")
        self.wave_banner = 2.0
        self.game.save.set("runs", self.runs)
        self.game.save.save()

    def go_menu(self) -> None:
        self.state = "menu"
        self.menu_index = 0
        self.clear(keep_particles=False)
        self.add(self.particles)
        self.sfx.play("click")

    # -- spawning ------------------------------------------------------
    def spawn_star(self, initial: bool = False) -> None:
        margin = 90
        if initial:
            x = random.uniform(margin, self.width - margin)
            y = random.uniform(self.height * 0.16, self.height * 0.86)
        else:
            for _ in range(12):
                x = random.uniform(margin, self.width - margin)
                y = random.uniform(self.height * 0.14, self.height * 0.86)
                if pygame.Vector2(x - self.player.x, y - self.player.y).length() > 130:
                    break
        self.spawn_star_at(x, y)

    def spawn_star_at(self, x: float, y: float) -> None:
        star = Star(x, y)
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
        self.spawn_enemy_at(x, y)

    def spawn_enemy_at(self, x: float, y: float) -> None:
        base = random.uniform(68, 96) + min(90, self.wave * 6 + self.play_time * 0.8)
        elite = self.wave >= 4 and random.random() < 0.16
        tint = (196, 138, 144) if elite else None
        slime = Slime(x, y, base * (0.8 if elite else 1.0), tint=tint, scale=1.25 if elite else 1.0)
        if elite:
            slime.radius = 34
        self.enemies.append(slime)
        self.add(slime)

    def spawn_powerup(self) -> None:
        kind = random.choices(
            POWER_KINDS,
            weights=(3, 3, 2, 1),
            k=1,
        )[0]
        margin = 110
        power = PowerUp(
            random.uniform(margin, self.width - margin),
            random.uniform(self.height * 0.2, self.height * 0.8),
            kind,
        )
        self.powerups.append(power)
        self.add(power)

    # -- menu layout ---------------------------------------------------
    def _menu_buttons(self) -> list[tuple[str, pygame.Rect]]:
        labels = (
            ("play", "ИГРАТЬ"),
            ("howto", "КАК ИГРАТЬ"),
            ("sound", "ЗВУК: ВКЛ" if self.sfx.enabled else "ЗВУК: ВЫКЛ"),
            ("quit", "ВЫХОД"),
        )
        width = min(300, max(220, int(self.width * 0.24)))
        height = 50
        gap = 12
        total = len(labels) * height + (len(labels) - 1) * gap
        start_y = int(self.height * 0.50 - total / 2) + 44
        x = self.width // 2 - width // 2
        return [
            (key, pygame.Rect(x, start_y + index * (height + gap), width, height))
            for index, (key, _label) in enumerate(labels)
        ]

    def _menu_labels(self) -> dict[str, str]:
        return {
            "play": "ИГРАТЬ",
            "howto": "КАК ИГРАТЬ",
            "sound": "ЗВУК: ВКЛ" if self.sfx.enabled else "ЗВУК: ВЫКЛ",
            "quit": "ВЫХОД",
        }

    def _over_buttons(self) -> dict[str, pygame.Rect]:
        width, height = 230, 50
        y = int(self.height / 2 + 118)
        return {
            "again": pygame.Rect(self.width // 2 - width - 8, y, width, height),
            "menu": pygame.Rect(self.width // 2 + 8, y, width, height),
        }

    def _pause_buttons(self) -> dict[str, pygame.Rect]:
        width, height = 260, 48
        y = int(self.height / 2 - 28)
        return {
            "resume": pygame.Rect(self.width // 2 - width // 2, y, width, height),
            "sound": pygame.Rect(self.width // 2 - width // 2, y + height + 10, width, height),
            "menu": pygame.Rect(self.width // 2 - width // 2, y + (height + 10) * 2, width, height),
        }

    def _howto_button(self) -> pygame.Rect:
        width, height = 220, 48
        return pygame.Rect(self.width // 2 - width // 2, int(self.height * 0.82), width, height)

    # -- input ---------------------------------------------------------
    def _activate_menu(self, key: str) -> None:
        if key == "play":
            self.start_game()
        elif key == "howto":
            self.state = "howto"
            self.sfx.play("click")
        elif key == "sound":
            self.sfx.enabled = not self.sfx.enabled
            self.game.save.set("sound", self.sfx.enabled)
            self.game.save.save()
            self.sfx.play("click")
        elif key == "quit":
            self.game.quit()

    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.MOUSEMOTION:
            self.mouse_pos = event.pos
        self.joystick.handle_event(event)

        if event.type == pygame.KEYDOWN:
            if self.state == "menu":
                if event.key in (pygame.K_UP, pygame.K_w):
                    self.menu_index = (self.menu_index - 1) % 4
                    self.sfx.play("click", 0.35)
                    return True
                if event.key in (pygame.K_DOWN, pygame.K_s):
                    self.menu_index = (self.menu_index + 1) % 4
                    self.sfx.play("click", 0.35)
                    return True
                if event.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_KP_ENTER):
                    keys = ("play", "howto", "sound", "quit")
                    self._activate_menu(keys[self.menu_index])
                    return True
                if event.key == pygame.K_ESCAPE:
                    self.game.quit()
                    return True
            elif self.state == "howto":
                if event.key in (pygame.K_ESCAPE, pygame.K_RETURN, pygame.K_SPACE):
                    self.state = "menu"
                    self.sfx.play("click")
                    return True
            elif self.state == "playing":
                if event.key in (pygame.K_ESCAPE, pygame.K_p):
                    self.state = "paused"
                    self.sfx.play("click")
                    return True
                if event.key in (pygame.K_SPACE, pygame.K_LSHIFT, pygame.K_RSHIFT):
                    self.try_dash()
                    return True
            elif self.state == "paused":
                if event.key in (pygame.K_ESCAPE, pygame.K_p):
                    self.state = "playing"
                    self.sfx.play("click")
                    return True
                if event.key == pygame.K_m:
                    self.go_menu()
                    return True
            elif self.state == "over":
                if event.key in (pygame.K_r, pygame.K_RETURN, pygame.K_SPACE):
                    self.start_game()
                    return True
                if event.key in (pygame.K_m, pygame.K_ESCAPE):
                    self.go_menu()
                    return True

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            pos = event.pos
            if self.state == "menu":
                for index, (key, rect) in enumerate(self._menu_buttons()):
                    if rect.collidepoint(pos):
                        self.menu_index = index
                        self._activate_menu(key)
                        return True
            elif self.state == "howto":
                if self._howto_button().collidepoint(pos):
                    self.state = "menu"
                    self.sfx.play("click")
                    return True
            elif self.state == "paused":
                buttons = self._pause_buttons()
                if buttons["resume"].collidepoint(pos):
                    self.state = "playing"
                    self.sfx.play("click")
                    return True
                if buttons["sound"].collidepoint(pos):
                    self.sfx.enabled = not self.sfx.enabled
                    self.game.save.set("sound", self.sfx.enabled)
                    self.game.save.save()
                    self.sfx.play("click")
                    return True
                if buttons["menu"].collidepoint(pos):
                    self.go_menu()
                    return True
            elif self.state == "over":
                buttons = self._over_buttons()
                if buttons["again"].collidepoint(pos):
                    self.start_game()
                    return True
                if buttons["menu"].collidepoint(pos):
                    self.go_menu()
                    return True
        return False

    def try_dash(self) -> None:
        if self.state != "playing" or self.dash_cd > 0:
            return
        vector = self.game.input.normalized_vector()
        if self.joystick.active and self.joystick.vector.length_squared() > 0.02:
            vector = self.joystick.vector
        if vector.length_squared() < 0.04:
            vector = pygame.Vector2(0, -1)
        self.dash_dir = vector.normalize() if vector.length_squared() else pygame.Vector2(0, -1)
        self.dash_time = 0.16
        self.dash_cd = 2.0
        self.sfx.play("dash")
        self.shake(4, 0.12)
        self.particles.burst(
            (self.player.x, self.player.y + 22),
            count=24,
            colors=(ACCENT_2, WHITE),
            speed=(80, 260),
            size=(1.5, 3.5),
            life=(0.2, 0.55),
            angle=(220, 320),
            additive=True,
        )

    # -- resize --------------------------------------------------------
    def on_resize(self, size: tuple[int, int]) -> None:
        old_width, old_height = getattr(self, "width", size[0]), getattr(self, "height", size[1])
        super().on_resize(size)
        self.width, self.height = size
        if old_width and old_height:
            sx, sy = size[0] / old_width, size[1] / old_height
            for node in self.nodes:
                node.x *= sx
                node.y *= sy
                # Animated nodes remember their base position separately;
                # scale it too or they jump back after a resize/fullscreen.
                if hasattr(node, "base_y"):
                    node.base_y *= sy
        # The scene camera is centred on the play field. Without this the
        # camera keeps the old centre after F11/resize and every node (and
        # effect ring) is drawn with a large offset.
        self.camera.pos.update(size[0] / 2, size[1] / 2)
        self.camera.offset.update(0, 0)
        self.joystick.place(size, margin=36)
        self._build_dust()

    # -- update --------------------------------------------------------
    def update(self, dt: float) -> None:
        self.joystick.update(dt)
        self.flash = max(0.0, self.flash - dt * 3)
        if self.state == "playing":
            self.play_time += dt
            self.hint_timer = max(0.0, self.hint_timer - dt)
            self.wave_banner = max(0.0, self.wave_banner - dt)
            self.invulnerable = max(0.0, self.invulnerable - dt)
            self.player_flash = max(0.0, self.player_flash - dt)
            self.shield_time = max(0.0, self.shield_time - dt)
            self.magnet_time = max(0.0, self.magnet_time - dt)
            self.slow_time = max(0.0, self.slow_time - dt)
            self.dash_cd = max(0.0, self.dash_cd - dt)
            self.move_player(dt)
            self.update_stars(dt)
            self.update_enemies(dt)
            if self.state != "playing":
                super().update(dt)
                return
            self.update_powerups(dt)
            self.update_combo(dt)
            self.update_waves(dt)
            self.spawn_timer -= dt
            if self.spawn_timer <= 0:
                if len(self.enemies) < 24:
                    self.spawn_enemy()
                self.spawn_timer = max(0.55, 1.85 - self.wave * 0.075)
            self.power_timer -= dt
            if self.power_timer <= 0 and len(self.powerups) < 3:
                self.spawn_powerup()
                self.power_timer = random.uniform(9.0, 14.0)
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
        self.floating = [item for item in self.floating if item.update(dt)]
        super().update(dt)

    def update_combo(self, dt: float) -> None:
        if self.combo <= 0:
            return
        self.combo_timer -= dt
        if self.combo_timer <= 0:
            self.combo = 0

    def update_waves(self, dt: float) -> None:
        self.wave_timer += dt
        if self.wave_timer >= max(18.0, 32.0 - self.wave * 1.2) or self.stars_collected >= self.wave * 12:
            self.wave += 1
            self.wave_timer = 0.0
            self.wave_banner = 2.4
            self.hearts = min(self.max_hearts, self.hearts + (1 if self.wave % 3 == 0 else 0))
            self.sfx.play("wave")
            self.shake(6, 0.25)
            self.burst(
                (self.width / 2, 96),
                count=46,
                colors=(GOLD, WHITE, ACCENT_2),
                speed=(60, 260),
                size=(2, 5),
                life=(0.5, 1.3),
                additive=True,
            )

    def move_player(self, dt: float) -> None:
        vector = self.game.input.normalized_vector()
        if self.joystick.active and self.joystick.vector.length_squared() > 0.02:
            vector = self.joystick.vector
        speed = 335
        if self.dash_time > 0:
            self.dash_time = max(0.0, self.dash_time - dt)
            self.player.x += self.dash_dir.x * 920 * dt
            self.player.y += self.dash_dir.y * 920 * dt
            if random.random() < dt * 40:
                self.particles.burst(
                    (self.player.x, self.player.y),
                    count=1,
                    colors=(ACCENT_2, ACCENT_SOFT),
                    speed=(10, 60),
                    size=(1, 3),
                    life=(0.2, 0.5),
                    additive=True,
                )
        else:
            self.player.x += vector.x * speed * dt
            self.player.y += vector.y * speed * dt
        margin_x, margin_y = 46, 40
        self.player.x = max(margin_x, min(self.width - margin_x, self.player.x))
        self.player.y = max(margin_y, min(self.height - margin_y, self.player.y))
        if abs(vector.x) > 0.08:
            self.player.flip_x = vector.x < 0
        tilt = max(-8, min(8, vector.x * 7))
        self.player.angle += (tilt - self.player.angle) * min(1.0, dt * 12)
        if random.random() < dt * 9:
            self.particles.burst(
                (self.player.x, self.player.y + 26),
                count=1,
                colors=(GOLD, ACCENT),
                speed=(8, 30),
                size=(1, 2.5),
                life=(0.2, 0.55),
                angle=(240, 300),
                additive=True,
            )

    def update_stars(self, dt: float) -> None:
        player_pos = pygame.Vector2(self.player.x, self.player.y)
        for star in list(self.stars):
            if self.magnet_time > 0:
                direction = player_pos - pygame.Vector2(star.x, star.y)
                distance = direction.length()
                if distance < 260 and distance > 1:
                    direction = direction.normalize()
                    star.x += direction.x * 280 * dt
                    star.y += direction.y * 280 * dt
                    star.base_y = star.y
            if player_pos.distance_to((star.x, star.y)) < 38:
                self.collect_star(star)
        while len(self.stars) < 7 + min(4, self.wave // 2):
            self.spawn_star()

    def collect_star(self, star: Star) -> None:
        self.stars.remove(star)
        star.kill()
        self.stars_collected += 1
        self.total_stars += 1
        self.combo += 1
        self.combo_timer = 3.2
        self.best_combo = max(self.best_combo, self.combo)
        multiplier = 1 + min(4, self.combo // 5)
        points = star.value * multiplier
        self.score += points
        self.best = max(self.best, self.score)
        self.floating.append(FloatingText(f"+{points}", star.x, star.y - 12, GOLD, 17))
        if self.combo > 1 and self.combo % 5 == 0:
            self.floating.append(
                FloatingText(f"КОМБО x{multiplier}", self.player.x, self.player.y - 54, ACCENT_SOFT, 18)
            )
            self.sfx.play("combo", 0.8)
        else:
            self.sfx.play("star", 0.7)
        self.particles.burst(
            (star.x, star.y),
            count=26,
            colors=(GOLD, (255, 255, 255), ACCENT),
            speed=(50, 240),
            size=(1.5, 4),
            life=(0.25, 0.75),
            additive=True,
        )
        self.camera.shake(3, 0.10)
        if self.combo > 0 and self.combo % 10 == 0:
            self.hearts = min(self.max_hearts, self.hearts + 1)
            self.floating.append(
                FloatingText("+1 ЖИЗНЬ", self.width / 2, 118, GREEN, 18)
            )

    def update_enemies(self, dt: float) -> None:
        player_pos = pygame.Vector2(self.player.x, self.player.y)
        slow = 0.45 if self.slow_time > 0 else 1.0
        for enemy in list(self.enemies):
            direction = player_pos - pygame.Vector2(enemy.x, enemy.y)
            if direction.length_squared() > 1:
                direction = direction.normalize()
            enemy.x += direction.x * enemy.speed * slow * dt
            enemy.y += direction.y * enemy.speed * slow * dt
            enemy.flip_x = direction.x < 0
            if pygame.Vector2(enemy.x, enemy.y).distance_to(player_pos) < enemy.radius + 20:
                if self.dash_time > 0 or self.shield_time > 0:
                    self.destroy_enemy(enemy, by_shield=True)
                    continue
                if self.invulnerable <= 0:
                    self.hit_player()
                    break

    def destroy_enemy(self, enemy: Slime, *, by_shield: bool = False) -> None:
        if enemy in self.enemies:
            self.enemies.remove(enemy)
        enemy.kill()
        bonus = 5 * (2 if by_shield else 1)
        self.score += bonus
        self.best = max(self.best, self.score)
        self.floating.append(FloatingText(f"+{bonus}", enemy.x, enemy.y - 10, GREEN if by_shield else MUTED, 14))
        self.particles.burst(
            (enemy.x, enemy.y),
            count=22,
            colors=(ACCENT_2, GREEN, WHITE) if by_shield else (DANGER, GOLD),
            speed=(50, 230),
            size=(1.5, 4),
            life=(0.25, 0.7),
            additive=True,
        )

    def hit_player(self) -> None:
        self.hearts -= 1
        self.invulnerable = 1.25
        self.player_flash = 0.7
        self.flash = 0.9
        self.combo = 0
        self.sfx.play("hit")
        self.camera.shake(14, 0.4)
        self.particles.burst(
            (self.player.x, self.player.y),
            count=38,
            colors=(DANGER, ACCENT, (255, 255, 255)),
            speed=(70, 290),
            size=(2, 5),
            life=(0.3, 0.8),
        )
        if self.hearts <= 0:
            self.game_over()

    def update_powerups(self, dt: float) -> None:
        player_pos = pygame.Vector2(self.player.x, self.player.y)
        for power in list(self.powerups):
            if player_pos.distance_to((power.x, power.y)) < 40:
                self.collect_powerup(power)
        if len(self.powerups) > 4:
            oldest = self.powerups.pop(0)
            oldest.kill()

    def collect_powerup(self, power: PowerUp) -> None:
        self.powerups.remove(power)
        power.kill()
        self.sfx.play("power")
        self.floating.append(
            FloatingText(
                {
                    "shield": "ЩИТ",
                    "magnet": "МАГНИТ",
                    "slow": "ЗАМЕДЛЕНИЕ",
                    "heart": "+1 ЖИЗНЬ",
                }[power.kind],
                power.x,
                power.y - 20,
                POWER_COLORS[power.kind],
                17,
            )
        )
        if power.kind == "shield":
            self.shield_time = 9.0
        elif power.kind == "magnet":
            self.magnet_time = 7.0
        elif power.kind == "slow":
            self.slow_time = 6.0
        elif power.kind == "heart":
            self.hearts = min(self.max_hearts, self.hearts + 1)
        self.camera.shake(4, 0.12)
        self.particles.burst(
            (power.x, power.y),
            count=30,
            colors=(POWER_COLORS[power.kind], WHITE),
            speed=(60, 250),
            size=(1.5, 4),
            life=(0.3, 0.8),
            additive=True,
        )

    def game_over(self) -> None:
        self.state = "over"
        self.game.save.set("best", self.best)
        self.game.save.set("total_stars", self.total_stars)
        self.game.save.set("last_wave", self.wave)
        self.game.save.save()
        self.sfx.play("over")
        self.combo = 0
        self.particles.burst(
            (self.width / 2, self.height / 2),
            count=90,
            colors=(DANGER, GOLD, ACCENT_2),
            speed=(60, 400),
            size=(2, 6),
            life=(0.6, 1.6),
        )
        self.camera.shake(18, 0.65)

    # -- drawing -------------------------------------------------------
    def draw_background(self, surface: pygame.Surface) -> None:
        width, height = surface.get_size()
        # Vertical gradient baked per frame is cheap enough for a dark screen.
        for y in range(0, height, 4):
            t = y / max(1, height)
            fill = (
                int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t),
                int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t),
                int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t),
            )
            pygame.draw.rect(surface, fill, (0, y, width, 4))
        if self._background is not None and self.state != "menu":
            image = pygame.transform.smoothscale(self._background, (width, height))
            surface.blit(image, (0, 0))
            veil = pygame.Surface((width, height), pygame.SRCALPHA)
            veil.fill((10, 11, 14, 92))
            surface.blit(veil, (0, 0))
        else:
            draw_glow(
                surface,
                (width * 0.5, height * 0.34),
                int(min(width, height) * 0.72),
                ACCENT,
                30,
                6,
            )
            draw_glow(
                surface,
                (width * 0.86, height * 0.92),
                int(min(width, height) * 0.48),
                ACCENT_2,
                18,
                5,
            )
            # Soft vignette keeps the eye on the play field.
            vignette = pygame.Surface((width, height), pygame.SRCALPHA)
            for ring in range(5):
                inset = int(min(width, height) * 0.03 * ring)
                alpha = 26 - ring * 4
                pygame.draw.rect(
                    vignette,
                    (0, 0, 0, max(0, alpha)),
                    (inset, inset, width - inset * 2, height - inset * 2),
                    width=max(2, int(min(width, height) * 0.1)),
                    border_radius=40,
                )
            surface.blit(vignette, (0, 0))
        if self.state == "menu":
            for x, y, size, speed, phase in self._menu_stars:
                twinkle = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(self.time * speed + phase))
                alpha = int(90 + 150 * twinkle)
                pygame.draw.circle(
                    surface,
                    with_alpha((210, 220, 235), alpha),
                    (int(x), int(y)),
                    int(size),
                )
        for x, y, speed, size in self._dust:
            drift = (self.time * speed + x) % (width + 60) - 30
            alpha = int(40 + 60 * (0.5 + 0.5 * math.sin(self.time * 1.7 + x)))
            pygame.draw.circle(surface, with_alpha((185, 190, 198), alpha), (int(drift), int(y)), int(size))

    # -- HUD -----------------------------------------------------------
    def draw_hud(self, surface: pygame.Surface) -> None:
        width, height = surface.get_size()
        bar = pygame.Surface((width, 104), pygame.SRCALPHA)
        for y in range(104):
            alpha = int(140 * (1 - y / 104))
            pygame.draw.line(bar, (10, 11, 14, alpha), (0, y), (width, y))
        surface.blit(bar, (0, 0))

        draw_rounded_rect(
            surface,
            pygame.Rect(22, 20, 178, 58),
            with_alpha((23, 26, 32), 214),
            16,
            border=with_alpha((78, 83, 92), 110),
        )
        surface.blit(make_star_surface(30), (36, 32))
        score_image = get_font(27, bold=True).render(str(self.score), True, WHITE)
        surface.blit(score_image, (80, 29))
        best_image = get_font(11, bold=True).render(f"РЕКОРД {self.best}", True, MUTED)
        surface.blit(best_image, (82, 56))

        # wave + combo in the middle
        wave_text = get_font(13, bold=True).render(f"ВОЛНА {self.wave}", True, GOLD)
        surface.blit(wave_text, wave_text.get_rect(center=(width // 2, 32)))
        if self.combo > 1:
            multiplier = 1 + min(4, self.combo // 5)
            combo_text = get_font(16, bold=True).render(f"x{multiplier}  КОМБО {self.combo}", True, ACCENT_SOFT)
            surface.blit(combo_text, combo_text.get_rect(center=(width // 2, 56)))
            bar_width = min(180, 40 + self.combo * 5)
            draw_rounded_rect(
                surface,
                pygame.Rect(width // 2 - bar_width // 2, 74, bar_width, 4),
                with_alpha(ACCENT_SOFT, 160),
                2,
            )

        for index in range(self.max_hearts):
            heart_x = width - 50 - (self.max_hearts - 1 - index) * 36
            filled = index < self.hearts
            draw_heart(surface, (heart_x, 42), 14, DANGER if filled else (58, 62, 69), filled)

        # Dash gauge
        dash_width = 150
        draw_rounded_rect(
            surface,
            pygame.Rect(24, height - 30, dash_width, 6),
            with_alpha((255, 255, 255), 30),
            3,
        )
        ready = 1.0 - self.dash_cd / 2.0
        draw_rounded_rect(
            surface,
            pygame.Rect(24, height - 30, max(6, int(dash_width * ready)), 6),
            ACCENT_2 if self.dash_cd <= 0 else with_alpha(ACCENT_2, 100),
            3,
        )
        dash_label = get_font(10, bold=True).render(
            "РЫВОК ГОТОВ" if self.dash_cd <= 0 else "РЫВОК", True, MUTED
        )
        surface.blit(dash_label, (24, height - 48))

        # Active power-up timers
        effects = (
            ("shield", self.shield_time, "ЩИТ"),
            ("magnet", self.magnet_time, "МАГНИТ"),
            ("slow", self.slow_time, "ЗАМЕДЛЕНИЕ"),
        )
        x = 190
        for kind, timer, label in effects:
            if timer <= 0:
                continue
            badge = pygame.Rect(x, height - 40, 92, 24)
            draw_rounded_rect(surface, badge, with_alpha(POWER_COLORS[kind], 60), 12, border=with_alpha(POWER_COLORS[kind], 170))
            text = get_font(10, bold=True).render(f"{label} {timer:.0f}", True, POWER_COLORS[kind])
            surface.blit(text, text.get_rect(center=badge.center))
            x += 100

        if self.hint_timer > 0 and self.state == "playing":
            alpha = int(210 * min(1.0, self.hint_timer / 1.2))
            hint = get_font(13, bold=True).render(
                "WASD / джойстик — движение   ·   Пробел — рывок   ·   Esc — пауза", True, WHITE
            )
            hint.set_alpha(alpha)
            surface.blit(hint, hint.get_rect(center=(width // 2, height - 60)))

        if self.wave_banner > 0 and self.state == "playing":
            alpha = int(255 * min(1.0, self.wave_banner / 0.6))
            banner = get_font(38, bold=True).render(f"ВОЛНА {self.wave}", True, GOLD)
            banner.set_alpha(alpha)
            surface.blit(banner, banner.get_rect(center=(width // 2, height * 0.34)))

    def draw_menu(self, surface: pygame.Surface) -> None:
        width, height = surface.get_size()
        veil = pygame.Surface((width, height), pygame.SRCALPHA)
        veil.fill((7, 8, 11, 78))
        surface.blit(veil, (0, 0))

        title_font = get_font(60 if width > 900 else 42, bold=True)
        title = title_font.render(APP_NAME.upper(), True, WHITE)
        shadow = title.copy()
        shadow.fill((217, 119, 87, 90), special_flags=pygame.BLEND_RGBA_MULT)
        surface.blit(shadow, title.get_rect(center=(width // 2 + 3, int(height * 0.20) + 3)))
        surface.blit(title, title.get_rect(center=(width // 2, int(height * 0.20))))

        subtitle = get_font(15, bold=True).render(
            "Собирай звёзды · уклоняйся от слизней · держи комбо", True, MUTED
        )
        surface.blit(subtitle, subtitle.get_rect(center=(width // 2, int(height * 0.20) + 54)))

        best = get_font(13, bold=True).render(
            f"ЛУЧШИЙ РЕЗУЛЬТАТ  {self.best}    ·    СОБРАНО ЗВЁЗД  {self.total_stars}",
            True,
            GOLD,
        )
        surface.blit(best, best.get_rect(center=(width // 2, int(height * 0.20) + 86)))

        labels = self._menu_labels()
        for index, (key, rect) in enumerate(self._menu_buttons()):
            hovered = rect.collidepoint(self.mouse_pos) or index == self.menu_index
            primary = key == "play"
            if primary:
                fill = ACCENT if hovered else with_alpha(ACCENT, 220)
                text_color = (27, 17, 13)
                border = (235, 143, 111)
            else:
                fill = with_alpha((44, 48, 57), 235) if hovered else with_alpha((30, 33, 39), 220)
                text_color = WHITE if hovered else MUTED
                border = with_alpha((92, 98, 108), 140) if hovered else with_alpha((58, 62, 70), 130)
            draw_rounded_rect(surface, rect, fill, 14, border=border, shadow=primary)
            label = get_font(16, bold=True).render(labels[key], True, text_color)
            surface.blit(label, label.get_rect(center=rect.center))

        hint = get_font(11).render(
            "↑ ↓ — выбор   ·   Enter — подтвердить   ·   Мышь работает тоже", True, with_alpha(MUTED, 190)
        )
        surface.blit(hint, hint.get_rect(center=(width // 2, height - 30)))

    def draw_howto(self, surface: pygame.Surface) -> None:
        width, height = surface.get_size()
        veil = pygame.Surface((width, height), pygame.SRCALPHA)
        veil.fill((8, 9, 12, 224))
        surface.blit(veil, (0, 0))
        panel = pygame.Rect(int(width * 0.5) - min(420, int(width * 0.42)), int(height * 0.10), min(840, int(width * 0.84)), int(height * 0.66))
        draw_rounded_rect(surface, panel, (23, 26, 32), 22, border=(58, 54, 49), shadow=True)
        heading = get_font(28, bold=True).render("КАК ИГРАТЬ", True, WHITE)
        surface.blit(heading, heading.get_rect(center=(width // 2, panel.y + 44)))
        rows = (
            ("Движение", "WASD, стрелки или экранный джойстик"),
            ("Рывок", "Пробел или Shift — короткий неуязвимый рывок"),
            ("Звёзды", "Собирайте их подряд: каждый пятый даёт множитель"),
            ("Слизни", "Касание отнимает жизнь. Рывок или щит их уничтожает"),
            ("Бонусы", "Щит, магнит, замедление и дополнительная жизнь"),
            ("Волны", "Каждая волна быстрее и опаснее. Держитесь!"),
        )
        y = panel.y + 92
        for label, text in rows:
            chip = get_font(12, bold=True).render(label.upper(), True, GOLD)
            surface.blit(chip, (panel.x + 42, y))
            body = get_font(13).render(text, True, WHITE)
            surface.blit(body, (panel.x + 190, y - 3))
            y += 44
        button = self._howto_button()
        draw_rounded_rect(surface, button, ACCENT, 14, border=(235, 143, 111), shadow=True)
        label = get_font(15, bold=True).render("ПОНЯТНО", True, (27, 17, 13))
        surface.blit(label, label.get_rect(center=button.center))

    def draw_overlay(self, surface: pygame.Surface, title: str, subtitle: str, buttons: dict[str, str]) -> None:
        width, height = surface.get_size()
        veil = pygame.Surface((width, height), pygame.SRCALPHA)
        veil.fill((10, 11, 14, 205))
        surface.blit(veil, (0, 0))
        panel = pygame.Rect(width // 2 - min(390, width // 2 - 30), int(height * 0.5) - 210, min(780, width - 60), 420)
        draw_rounded_rect(surface, panel, (23, 26, 32), 26, border=(58, 54, 49), shadow=True)
        title_image = get_font(40 if width > 700 else 32, bold=True).render(title, True, WHITE)
        surface.blit(title_image, title_image.get_rect(center=(width // 2, panel.y + 78)))
        sub_image = get_font(15).render(subtitle, True, MUTED)
        surface.blit(sub_image, sub_image.get_rect(center=(width // 2, panel.y + 128)))

    def draw_pause(self, surface: pygame.Surface) -> None:
        self.draw_overlay(surface, "ПАУЗА", "Мир ждёт. Продолжайте, когда будете готовы.", {})
        buttons = self._pause_buttons()
        labels = {
            "resume": "ПРОДОЛЖИТЬ",
            "sound": "ЗВУК: ВКЛ" if self.sfx.enabled else "ЗВУК: ВЫКЛ",
            "menu": "В МЕНЮ",
        }
        for key, rect in buttons.items():
            primary = key == "resume"
            fill = ACCENT if primary else with_alpha((34, 38, 46), 240)
            border = (235, 143, 111) if primary else with_alpha((70, 75, 84), 160)
            draw_rounded_rect(surface, rect, fill, 14, border=border, shadow=primary)
            text = get_font(15, bold=True).render(
                labels[key], True, (27, 17, 13) if primary else WHITE
            )
            surface.blit(text, text.get_rect(center=rect.center))
        hint = get_font(11).render("Esc — продолжить   ·   M — в меню", True, MUTED)
        surface.blit(hint, hint.get_rect(center=(surface.get_width() // 2, surface.get_height() - 34)))

    def draw_game_over(self, surface: pygame.Surface) -> None:
        width, height = surface.get_size()
        combo = f"   ·   лучшее комбо: x{self.best_combo}" if self.best_combo > 1 else ""
        self.draw_overlay(
            surface,
            "ИГРА ОКОНЧЕНА",
            f"Волна {self.wave}   ·   звёзд собрано: {self.stars_collected}{combo}",
            {},
        )
        panel_y = int(height * 0.5) - 210
        score = get_font(52, bold=True).render(str(self.score), True, WHITE)
        surface.blit(score, score.get_rect(center=(width // 2, panel_y + 196)))
        new_record = self.score > self.record_at_start
        caption = get_font(12, bold=True).render(
            "НОВЫЙ РЕКОРД!" if new_record else f"РЕКОРД {self.best}",
            True,
            GOLD if new_record else MUTED,
        )
        surface.blit(caption, caption.get_rect(center=(width // 2, panel_y + 236)))
        stats = get_font(12).render(
            f"Время в игре: {int(self.play_time // 60):02d}:{int(self.play_time % 60):02d}   ·   всего звёзд: {self.total_stars}",
            True,
            MUTED,
        )
        surface.blit(stats, stats.get_rect(center=(width // 2, panel_y + 262)))

        buttons = self._over_buttons()
        labels = {"again": "ИГРАТЬ СНОВА", "menu": "В МЕНЮ"}
        for key, rect in buttons.items():
            primary = key == "again"
            fill = ACCENT if primary else with_alpha((34, 38, 46), 240)
            border = (235, 143, 111) if primary else with_alpha((70, 75, 84), 160)
            draw_rounded_rect(surface, rect, fill, 14, border=border, shadow=primary)
            text = get_font(14, bold=True).render(
                labels[key], True, (27, 17, 13) if primary else WHITE
            )
            surface.blit(text, text.get_rect(center=rect.center))
        hint = get_font(11).render("R — заново   ·   M — в меню", True, MUTED)
        surface.blit(hint, hint.get_rect(center=(width // 2, height - 30)))

    def draw(self, surface: pygame.Surface) -> None:
        if self.state in {"menu", "howto"}:
            # Menu screens show only the animated backdrop; gameplay nodes are
            # faded out completely instead of peeking through the buttons.
            self.draw_background(surface)
            if self.state == "menu":
                self.draw_menu(surface)
            else:
                self.draw_howto(surface)
            return
        super().draw(surface)
        self.draw_hud(surface)
        for item in self.floating:
            item.draw(surface, self.camera)
        self.joystick.draw(surface)
        player_screen = self.camera.world_to_screen((self.player.x, self.player.y))
        if self.shield_time > 0 and self.player.visible:
            pulse = 1.0 + math.sin(self.time * 6) * 0.08
            pygame.draw.circle(
                surface,
                with_alpha(ACCENT_2, 170),
                (int(player_screen.x), int(player_screen.y)),
                int(46 * pulse),
                2,
            )
        if self.player_flash > 0 and self.player.visible:
            pygame.draw.circle(
                surface,
                with_alpha(DANGER, 70),
                (int(player_screen.x), int(player_screen.y)),
                46,
                2,
            )
        if self.flash > 0:
            overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
            overlay.fill((255, 80, 80, int(80 * self.flash)))
            surface.blit(overlay, (0, 0))
        if self.state == "paused":
            self.draw_pause(surface)
        elif self.state == "over":
            self.draw_game_over(surface)


class SparkGame(Game):
    def __init__(self) -> None:
        # Mono mixer before pygame.init() so Sfx can build buffers directly.
        try:
            pygame.mixer.pre_init(22050, -16, 1, 512)
        except Exception:
            pass
        super().__init__(
            APP_NAME,
            WINDOW_SIZE,
            splash=True,
            splash_skippable=True,
            splash_accent="#D97757",
            background=BG_TOP,
            resizable=WINDOW_RESIZABLE,
            fullscreen=WINDOW_FULLSCREEN,
        )
        self.save = SaveData(APP_NAME, "save.json")
        self.sfx = Sfx()
        self.sfx.enabled = bool(self.save.get("sound", True))

    def on_start(self) -> None:
        self.sfx.init()
        self.set_scene(WorldScene(self))

    def on_exit(self) -> None:
        super().on_exit()
        try:
            self.save.save()
        except Exception:
            pass


def main() -> None:
    SparkGame().run()


if __name__ == "__main__":
    main()
