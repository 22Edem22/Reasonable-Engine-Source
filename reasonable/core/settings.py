"""User settings stored in %APPDATA%\\ReasonableEngine\\settings.json."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from .paths import app_data_dir, atomic_write_json, read_json, settings_path


DEFAULT_SETTINGS: dict[str, Any] = {
    "version": 2,
    # OpenRouter is a reasonable first choice because it offers free models
    # once the user adds a key. Anonymous gateway providers are not offered.
    "active_provider": "openrouter",
    "provider_overrides": {},
    "image": {
        "provider": "procedural",
        "base_url": "",
        "model": "pixel",
        "api_key": "",
        "fallback_to_procedural": True,
    },
    "agent": {
        # 0 means unlimited: the agent works until the task is done or the
        # user stops it. A step cap only produced «Работа не завершена» noise.
        "max_steps": 0,
        "temperature": 0.65,
        "context_messages": 36,
    },
    "ui": {
        "accent": "#FF6B4A",
        "sidebar_width": 232,
    },
    # The intro splash always plays; there is no preview.skip_splash option.
    # Empty means "inside the installed engine folder" (see default_projects_dir).
    "projects_dir": "",
    "recent_projects": [],
    "editor": {
        "open_last_project": False,
    },
}


def _deep_merge(base: dict, incoming: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class Settings:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or settings_path()
        self.data = copy.deepcopy(DEFAULT_SETTINGS)
        self.load()

    def load(self) -> None:
        loaded = read_json(self.path, {})
        if isinstance(loaded, dict):
            self.data = _deep_merge(DEFAULT_SETTINGS, loaded)
        else:
            self.data = copy.deepcopy(DEFAULT_SETTINGS)
        self._migrate()

    def _migrate(self) -> None:
        """Drop removed anonymous gateway providers and keep settings usable."""
        removed = {"pollinations"}
        if self.data.get("active_provider") in removed:
            self.data["active_provider"] = DEFAULT_SETTINGS["active_provider"]
        overrides = self.data.get("provider_overrides")
        if isinstance(overrides, dict):
            for provider_id in removed:
                overrides.pop(provider_id, None)
        image = self.data.setdefault("image", {})
        if image.get("provider") in removed:
            image["provider"] = "procedural"
            image["base_url"] = ""
            image["model"] = "pixel"
            image["api_key"] = ""
        if not str(self.data.get("projects_dir") or "").strip():
            self.data["projects_dir"] = ""
        # The step limit is gone: old installs keep working with unlimited steps.
        agent = self.data.setdefault("agent", {})
        try:
            if int(agent.get("max_steps") or 0) <= 60:
                agent["max_steps"] = 0
        except (TypeError, ValueError):
            agent["max_steps"] = 0
        self.data.pop("preview", None)

    def save(self) -> None:
        self.path = self.path or (app_data_dir() / "settings.json")
        atomic_write_json(self.path, self.data)

    # -- project locations ------------------------------------------------
    def projects_dir(self) -> Path:
        from .paths import default_projects_dir, ensure_projects_dir

        value = str(self.data.get("projects_dir") or "").strip()
        if value:
            return ensure_projects_dir(value)
        return ensure_projects_dir(default_projects_dir())

    def set_projects_dir(self, value: str | Path | None) -> None:
        text = str(value or "").strip()
        self.data["projects_dir"] = text
        self.save()

    # -- provider helpers -------------------------------------------------
    @property
    def active_provider(self) -> str:
        return self.data.get("active_provider", DEFAULT_SETTINGS["active_provider"])

    @active_provider.setter
    def active_provider(self, value: str) -> None:
        self.data["active_provider"] = value

    def provider_override(self, provider_id: str) -> dict:
        return self.data.setdefault("provider_overrides", {}).setdefault(provider_id, {})

    def update_provider(self, provider_id: str, **values: Any) -> None:
        override = self.provider_override(provider_id)
        for key, value in values.items():
            if value is None:
                continue
            override[key] = value
        self.save()

    def get_provider_config(self, provider_id: str | None = None) -> dict:
        from reasonable.ai.providers import merge_provider_config

        return merge_provider_config(self, provider_id or self.active_provider)

    def image_config(self) -> dict:
        from reasonable.ai.providers import get_image_provider, IMAGE_PROVIDERS

        data = dict(self.data.get("image", {}))
        preset = get_image_provider(data.get("provider", "procedural"))
        # If the user hasn't customised the endpoint, follow the preset.
        user_base = data.get("base_url")
        default_bases = {item.base_url for item in IMAGE_PROVIDERS}
        base_url = user_base if user_base and user_base not in default_bases else preset.base_url
        data.update(
            {
                "provider_name": preset.name,
                "base_url": base_url or preset.base_url,
                "model": data.get("model") or preset.default_model,
                "requires_key": preset.requires_key,
                "description": preset.description,
            }
        )
        return data

    def update_image(self, **values: Any) -> None:
        image = self.data.setdefault("image", {})
        image.update(values)
        self.save()

    # -- recents ----------------------------------------------------------
    def recent_projects(self) -> list[dict]:
        result = []
        for entry in self.data.get("recent_projects", []):
            path = Path(entry.get("path", ""))
            if path.is_dir():
                result.append(entry)
        return result

    def touch_recent(self, project_dir: Path, meta: dict) -> None:
        project_dir = Path(project_dir).resolve()
        recents = [
            entry
            for entry in self.data.get("recent_projects", [])
            if Path(entry.get("path", "")).resolve() != project_dir
        ]
        from .paths import now_iso

        recents.insert(
            0,
            {
                "path": str(project_dir),
                "name": meta.get("name") or project_dir.name,
                "type": meta.get("type", "game"),
                "last_opened": now_iso(),
                "goal": meta.get("goal", ""),
            },
        )
        existing = {Path(item.get("path", "")).resolve() for item in recents}
        for old in self.data.get("recent_projects", []):
            try:
                old_path = Path(old.get("path", "")).resolve()
            except OSError:
                continue
            if old_path not in existing:
                recents.append(old)
        self.data["recent_projects"] = recents[:16]
        self.save()

    def remove_recent(self, project_dir: Path) -> None:
        target = str(Path(project_dir).resolve()).lower()
        self.data["recent_projects"] = [
            item
            for item in self.data.get("recent_projects", [])
            if str(Path(item.get("path", "")).resolve()).lower() != target
        ]
        self.save()
