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
        "provider": "openai",
        "base_url": "",
        "model": "gpt-image-1",
        "api_key": "",
    },
    "agent": {
        # 0 means unlimited: the agent works until the task is done or the
        # user stops it. A step cap only produced «Работа не завершена» noise.
        # The no-progress guard below still stops a genuinely stuck run.
        "max_steps": 0,
        # Agentic work needs deterministic tool calls, not creative writing.
        "temperature": 0.3,
        "context_messages": 36,
        # Character budget for the recent part of the conversation. A single
        # read_file can return hundreds of kilobytes; without a budget one
        # step would push the task itself out of the context window.
        "context_chars": 120_000,
        # Approximate prompt-token budget. 0 means "auto": about 60% of the
        # provider's context window, capped at 48k so a slow local model is
        # not drowned in context.
        "context_tokens": 0,
        # Cache-friendly context: "auto" boosts the window for large-context
        # DeepSeek models, "cache" always does, "balanced" keeps 48k.
        "context_mode": "auto",
        # Hard cap for one user-visible run, including parallel specialists.
        # Steps are unlimited by default, so without this a stuck agent could
        # spend the whole allowance. 0 keeps the old unlimited behaviour.
        "run_token_budget": 0,
        # Keep a journal of the current step so a crash or power loss can
        # resume the same task instead of paying for the whole run again.
        "resume_runs": True,
        # Show the answer while it is being generated. Off by default: many
        # OpenAI-compatible endpoints stream without a usage payload, which
        # makes the cost counter less accurate.
        "stream": False,
        # Ask once before the first file change of a run. Off by default:
        # snapshots make every run reversible already.
        "confirm_changes": False,
        # Specialist-only guards: a work item that keeps reading and running
        # commands without editing a file is stopped long before it can burn
        # hours of tokens. 0 disables a particular limit.
        "write_starvation_warn": 8,
        "write_starvation_stop": 20,
        "specialist_timeout_minutes": 15,
        "specialist_max_steps": 60,
        "max_run_minutes": 90,
        # Compress older turns into a short summary instead of dropping them.
        "compaction": True,
        # Optional hard stop when this many steps in a row changed nothing.
        # 0 (default) disables it: reading, checking and thinking are normal
        # parts of a task, and a false "no progress" stop is worse than a long
        # run. Repeated identical actions are still handled separately.
        "stall_steps": 0,
        # Whole-file tool calls can exceed 8192 tokens; the cut-off argument
        # used to fail on every retry.
        "max_output_tokens": 16384,
        # Error categories after which the chat may send "Продолжай" itself.
        # Empty by default: automatic continuation is an explicit opt-in.
        "auto_continue_errors": [],
        # Independent audit of the user's task before the agent declares success.
        "supervisor": True,
        # Optional cheaper model for mechanical calls (compaction + audit).
        # Empty keeps the main model. Example for OpenCode Go: deepseek-v4.1-flash.
        "aux_model": "",
        # Parallel development: a non-editing master plans work for several
        # scoped specialists, then validates and audits the merged result.
        "parallel": True,
        "parallel_workers": 3,
        "parallel_rounds": 3,
    },
    "ui": {
        "accent": "#FF6B4A",
        "sidebar_width": 232,
        # Chosen on the very first page of the Windows installer and written
        # into settings.json there; changeable later in the settings dialog.
        "language": "ru",
        # Set after the first launch quick start; the tour can be replayed
        # from the Help menu or the welcome page at any time.
        "tutorial_seen": False,
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
        self._decrypt_secrets()
        self._migrate()
        self._consume_installer_language()

    # -- secrets ----------------------------------------------------------
    def _decrypt_secrets(self) -> None:
        """Keep decrypted keys in memory; only the file is protected."""
        from .secrets import unprotect

        overrides = self.data.get("provider_overrides")
        if isinstance(overrides, dict):
            for item in overrides.values():
                if isinstance(item, dict) and item.get("api_key"):
                    item["api_key"] = unprotect(item["api_key"])
        image = self.data.get("image")
        if isinstance(image, dict) and image.get("api_key"):
            image["api_key"] = unprotect(image["api_key"])

    def _encrypted_payload(self) -> dict[str, Any]:
        from .secrets import protect

        payload = copy.deepcopy(self.data)
        overrides = payload.get("provider_overrides")
        if isinstance(overrides, dict):
            for item in overrides.values():
                if isinstance(item, dict) and item.get("api_key"):
                    item["api_key"] = protect(item["api_key"])
        image = payload.get("image")
        if isinstance(image, dict) and image.get("api_key"):
            image["api_key"] = protect(image["api_key"])
        return payload

    def _consume_installer_language(self) -> None:
        """Persist the language chosen in the installer, then drop its marker.

        Runs on every Settings load; the marker normally exists only on the
        first launch after (re)installation. The marker is deleted only after
        the language has been successfully written, so a failed save retries
        on the next start.
        """
        from .i18n import read_installer_language, remove_installer_language_marker

        language = read_installer_language()
        if not language:
            return
        self.data.setdefault("ui", {})["language"] = language
        self.save()
        remove_installer_language_marker()

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
        # The offline sprite template generator is gone. Keep old installs on
        # the external-model path instead of pointing at a removed provider.
        if image.get("provider") != "openai":
            image["provider"] = "openai"
            image["base_url"] = ""
            image["model"] = ""
            image["api_key"] = ""
        image.pop("fallback_to_procedural", None)
        if not str(self.data.get("projects_dir") or "").strip():
            self.data["projects_dir"] = ""
        # Language: older installs simply did not have ui.language — keep RU.
        from .i18n import normalize_language

        ui = self.data.setdefault("ui", {})
        ui["language"] = normalize_language(ui.get("language"))
        # The step limit is gone: old installs keep working with unlimited steps.
        agent = self.data.setdefault("agent", {})
        try:
            if int(agent.get("max_steps") or 0) <= 60:
                agent["max_steps"] = 0
        except (TypeError, ValueError):
            agent["max_steps"] = 0
        # 0.65 was the old default and made tool-calling turns needlessly
        # creative. Keep a deliberate custom value, migrate only the default.
        try:
            if abs(float(agent.get("temperature", 0.3)) - 0.65) < 0.001:
                agent["temperature"] = 0.3
        except (TypeError, ValueError):
            agent["temperature"] = 0.3
        try:
            raw_stall = agent.get("stall_steps", 0)
            value = int(0 if raw_stall is None else raw_stall)
            # 8 was the old default and produced false "no progress" stops
            # while the agent was still reading or checking the project.
            if value == 8:
                value = 0
            agent["stall_steps"] = max(0, min(50, value))
        except (TypeError, ValueError):
            agent["stall_steps"] = 0
        try:
            agent["context_chars"] = max(
                20_000, min(1_000_000, int(agent.get("context_chars", 120_000) or 120_000))
            )
        except (TypeError, ValueError):
            agent["context_chars"] = 120_000
        try:
            agent["context_tokens"] = max(
                0, min(200_000, int(agent.get("context_tokens", 0) or 0))
            )
        except (TypeError, ValueError):
            agent["context_tokens"] = 0
        try:
            agent["run_token_budget"] = max(
                0, min(10_000_000, int(agent.get("run_token_budget", 0) or 0))
            )
        except (TypeError, ValueError):
            agent["run_token_budget"] = 0
        try:
            steps = int(agent.get("specialist_max_steps", 60) or 0)
        except (TypeError, ValueError):
            steps = 60
        # 30 was the old default and stopped real work mid-task; keep a
        # deliberate smaller value, but migrate the old default to 60.
        if steps == 30:
            steps = 60
        agent["specialist_max_steps"] = max(0, min(200, steps))
        agent["compaction"] = bool(agent.get("compaction", True))
        agent["aux_model"] = str(agent.get("aux_model") or "").strip()[:160]
        try:
            agent["max_output_tokens"] = max(
                256, min(65_536, int(agent.get("max_output_tokens", 16384) or 16384))
            )
        except (TypeError, ValueError):
            agent["max_output_tokens"] = 16384
        # Keep only known error categories so an old or hand-edited settings
        # file cannot inject arbitrary values into the auto-continue flow.
        from .agent_errors import AUTO_CONTINUE_KINDS

        raw_auto = agent.get("auto_continue_errors")
        if not isinstance(raw_auto, list):
            raw_auto = []
        agent["auto_continue_errors"] = [
            kind for kind in AUTO_CONTINUE_KINDS if kind in raw_auto
        ]
        self.data.pop("preview", None)

    def save(self) -> None:
        self.path = self.path or (app_data_dir() / "settings.json")
        atomic_write_json(self.path, self._encrypted_payload())
        from .i18n import invalidate_cache

        invalidate_cache()

    # -- language ---------------------------------------------------------
    def language(self) -> str:
        from .i18n import normalize_language

        return normalize_language(self.data.get("ui", {}).get("language"))

    def set_language(self, value: str) -> None:
        """Remember the UI language (chosen in the installer or settings)."""
        from .i18n import invalidate_cache, normalize_language

        self.data.setdefault("ui", {})["language"] = normalize_language(value)
        self.save()
        invalidate_cache()

    # -- onboarding -------------------------------------------------------
    def _ui_data(self) -> dict:
        ui = self.data.get("ui")
        if not isinstance(ui, dict):
            ui = {}
            self.data["ui"] = ui
        return ui

    def tutorial_seen(self) -> bool:
        ui = self.data.get("ui")
        return bool(isinstance(ui, dict) and ui.get("tutorial_seen"))

    def mark_tutorial_seen(self) -> None:
        self._ui_data()["tutorial_seen"] = True
        self.save()

    def reset_tutorial(self) -> None:
        """Show the quick start again on the next launch."""
        self._ui_data()["tutorial_seen"] = False
        self.save()

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
        preset = get_image_provider(data.get("provider", "openai"))
        # If the user hasn't customised the endpoint, follow the preset.
        user_base = data.get("base_url")
        default_bases = {item.base_url for item in IMAGE_PROVIDERS}
        base_url = user_base if user_base and user_base not in default_bases else preset.base_url
        data.update(
            {
                "provider_name": preset.display_name,
                "base_url": base_url or preset.base_url,
                "model": data.get("model") or preset.default_model,
                "requires_key": preset.requires_key,
                "description": preset.display_description,
            }
        )
        return data

    def update_image(self, **values: Any) -> None:
        image = self.data.setdefault("image", {})
        image.update(values)
        self.save()

    # -- agent auto-continue ----------------------------------------------
    def auto_continue_kinds(self) -> list[str]:
        from .agent_errors import AUTO_CONTINUE_KINDS

        agent = self.data.get("agent", {})
        raw = agent.get("auto_continue_errors") if isinstance(agent, dict) else None
        if not isinstance(raw, list):
            return []
        return [kind for kind in AUTO_CONTINUE_KINDS if kind in raw]

    def is_auto_continue_enabled(self, kind: str) -> bool:
        return kind in self.auto_continue_kinds()

    # -- task supervisor --------------------------------------------------
    def supervisor_enabled(self) -> bool:
        agent = self.data.get("agent")
        return bool((agent or {}).get("supervisor", True))

    def set_supervisor(self, enabled: bool) -> None:
        self.data.setdefault("agent", {})["supervisor"] = bool(enabled)
        self.save()

    def set_auto_continue(self, kind: str, enabled: bool) -> None:
        from .agent_errors import AUTO_CONTINUE_KINDS

        if kind not in AUTO_CONTINUE_KINDS:
            return
        kinds = set(self.auto_continue_kinds())
        if enabled:
            kinds.add(kind)
        else:
            kinds.discard(kind)
        self.data.setdefault("agent", {})["auto_continue_errors"] = [
            item for item in AUTO_CONTINUE_KINDS if item in kinds
        ]

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
