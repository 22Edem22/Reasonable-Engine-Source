"""Tiny audio helper with lazy initialisation so headless tests never fail."""

from __future__ import annotations

from pathlib import Path

import pygame

try:
    from reasonable.core.i18n import tr as _tr
except Exception:  # exported builds may run without the bundled core package
    def _tr(en: str, ru: str, **values) -> str:
        return en


class Audio:
    _initialized = False
    _enabled = True

    @classmethod
    def init(cls) -> None:
        if cls._initialized:
            return
        cls._initialized = True
        try:
            pygame.mixer.init()
        except pygame.error:
            cls._enabled = False

    @classmethod
    def play(cls, path: str | Path, volume: float = 0.8) -> bool:
        cls.init()
        if not cls._enabled:
            return False
        try:
            sound = pygame.mixer.Sound(str(path))
            sound.set_volume(max(0.0, min(1.0, volume)))
            sound.play()
            return True
        except Exception as exc:
            print(_tr("[Reasonable] Sound was not played: {error}", "[Reasonable] Звук не воспроизведён: {error}", error=exc))
            return False

    @classmethod
    def music(cls, path: str | Path, volume: float = 0.55, loop: bool = True) -> bool:
        cls.init()
        if not cls._enabled:
            return False
        try:
            pygame.mixer.music.load(str(path))
            pygame.mixer.music.set_volume(max(0.0, min(1.0, volume)))
            pygame.mixer.music.play(-1 if loop else 0)
            return True
        except Exception as exc:
            print(_tr("[Reasonable] Music was not started: {error}", "[Reasonable] Музыка не запущена: {error}", error=exc))
            return False

    @classmethod
    def stop_music(cls) -> None:
        if cls._enabled:
            try:
                pygame.mixer.music.stop()
            except pygame.error:
                pass


def play_sound(path, volume: float = 0.8) -> bool:
    return Audio.play(path, volume)
