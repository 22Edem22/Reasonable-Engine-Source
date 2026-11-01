"""Tiny JSON save system for games and apps."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from reasonable.core.paths import app_data_dir


class SaveData:
    def __init__(self, app_name: str = "MyApp", filename: str = "save.json") -> None:
        safe = "".join(ch for ch in app_name if ch.isalnum() or ch in " -_").strip() or "App"
        self.path = app_data_dir().parent / "ReasonableGames" / safe / filename
        self.data: dict[str, Any] = {}
        self.load()

    def load(self) -> dict[str, Any]:
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(self.data, dict):
                self.data = {}
        except (OSError, ValueError):
            self.data = {}
        return self.data

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value) -> None:
        self.data[key] = value

    def reset(self) -> None:
        self.data.clear()
        self.save()
