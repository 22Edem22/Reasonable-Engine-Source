"""Built-in AI assistant for exported apps and games.

Use ``AIChatPanel`` to drop a fully working assistant into an app, or use
``AIClient`` directly. Configuration defaults to OpenRouter; the in-app settings
form lets the end user supply any OpenAI-compatible endpoint. Keys are stored
locally on the user's machine, never in the exported project.
"""

from __future__ import annotations

import json
import os
import queue
import socket
import ssl
import threading
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import pygame

from reasonable.version import VERSION_LABEL

from .utils import color, draw_icon, ellipsis, get_font, wrap_text
from .ui import (
    Button,
    Entry,
    HStack,
    Icon,
    IconButton,
    Label,
    Panel,
    ScrollView,
    VStack,
    Widget,
    draw_rounded_rect,
    with_alpha,
)


try:
    from reasonable.core.i18n import tr as _tr
except Exception:  # exported builds may run without the bundled core package
    def _tr(en: str, ru: str, **values) -> str:
        template = en
        return template.format(**values) if values else template


DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "meta-llama/llama-3.3-70b-instruct:free"
# AI-facing material ships English-only; the "user's language" rule below is
# what makes the assistant answer in the language the end user actually types.
DEFAULT_SYSTEM_PROMPT = (
    "You are the built-in AI assistant of an app built with Reasonable Engine. "
    "Reply briefly, to the point and in the language the user writes in. "
    "If you lack data, ask one clarifying question."
)


def _app_config_path(app_name: str) -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif os.uname().sysname == "Darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    safe = "".join(ch for ch in app_name if ch.isalnum() or ch in " -_").strip() or "App"
    return root / "ReasonableEngine" / "apps" / safe / "ai.json"


@dataclass
class AIConfig:
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    api_key: str = ""
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    temperature: float = 0.6
    title: str = ""
    _local_path: Path | None = None

    @classmethod
    def load(cls, app_name: str = "Reasonable App", project_dir: str | Path | None = None) -> "AIConfig":
        config = cls(_local_path=_app_config_path(app_name))
        project_path = Path(project_dir or os.getcwd()) / "ai_config.json"
        for candidate in (project_path, config._local_path):
            try:
                if candidate and candidate.exists():
                    data = json.loads(candidate.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        for key in ("base_url", "model", "api_key", "system_prompt", "title"):
                            if data.get(key):
                                setattr(config, key, str(data[key]))
                        if data.get("temperature") is not None:
                            try:
                                config.temperature = float(data["temperature"])
                            except Exception:
                                pass
            except (OSError, ValueError):
                continue
        env_map = {
            "base_url": os.environ.get("REASONABLE_AI_BASE_URL"),
            "model": os.environ.get("REASONABLE_AI_MODEL"),
            "api_key": os.environ.get("REASONABLE_AI_KEY"),
            "system_prompt": os.environ.get("REASONABLE_AI_SYSTEM_PROMPT"),
        }
        for key, value in env_map.items():
            if value:
                setattr(config, key, value)
        return config

    def save_local(self) -> Path | None:
        if self._local_path is None:
            return None
        self._local_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "base_url": self.base_url,
            "model": self.model,
            "api_key": self.api_key,
            "system_prompt": self.system_prompt,
            "title": self.title,
            "temperature": self.temperature,
        }
        self._local_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return self._local_path

    def copy(self) -> "AIConfig":
        return AIConfig(
            base_url=self.base_url,
            model=self.model,
            api_key=self.api_key,
            system_prompt=self.system_prompt,
            temperature=self.temperature,
            title=self.title,
            _local_path=self._local_path,
        )


class AIClient:
    # Stable for the whole app session so OpenCode Go can reuse its routing
    # and prompt cache between messages.
    _OPENCODE_SESSION = f"reasonable-app-{uuid.uuid4().hex[:24]}"

    def __init__(self, config: AIConfig, *, timeout: float = 90.0) -> None:
        self.config = config
        self.timeout = timeout

    def _url(self) -> str:
        base = self.config.base_url.strip().rstrip("/")
        if not base:
            raise RuntimeError(_tr("The AI server address is not set.", "Не задан адрес ИИ-сервера."))
        if base.endswith("/chat/completions"):
            return base
        return base + "/chat/completions"

    def chat(self, messages: list[dict[str, str]]) -> str:
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": max(0.0, min(1.5, self.config.temperature)),
            "max_tokens": 1600,
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"ReasonableEngine/{VERSION_LABEL}",
        }
        if "opencode.ai" in self.config.base_url.lower():
            headers["x-opencode-session"] = self._OPENCODE_SESSION
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        request = urllib.request.Request(self._url(), data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout, context=ssl.create_default_context()) as response:
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            if error.code == 401:
                raise RuntimeError(_tr("The API key was rejected. Check the AI settings.", "Ключ API не принят. Проверьте настройки ИИ.")) from error
            if error.code == 429:
                raise RuntimeError(_tr("The free request limit is used up. Wait or add your own key.", "Лимит бесплатных запросов исчерпан. Подождите или укажите свой ключ.")) from error
            raise RuntimeError(_tr("The AI server returned error {code}. {detail}", "ИИ-сервер вернул ошибку {code}. {detail}", code=error.code, detail=detail[:220])) from error
        except urllib.error.URLError as error:
            if isinstance(error.reason, (TimeoutError, socket.timeout)):
                raise RuntimeError(_tr("The AI server did not respond in time.", "ИИ-сервер не ответил вовремя.")) from error
            raise RuntimeError(_tr("No connection to the AI server: {reason}", "Нет соединения с ИИ-сервером: {reason}", reason=error.reason)) from error
        except (TimeoutError, socket.timeout) as error:
            raise RuntimeError(_tr("The AI server did not respond in time.", "ИИ-сервер не ответил вовремя.")) from error
        try:
            parsed = json.loads(body)
            content = parsed["choices"][0]["message"]["content"]
        except Exception as error:
            raise RuntimeError(_tr("Could not parse the AI server response.", "Не удалось разобрать ответ ИИ-сервера.")) from error
        if isinstance(content, list):
            content = "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
        return str(content or "").strip()

    def chat_async(
        self,
        messages: list[dict[str, str]],
        on_success: Callable[[str], None],
        on_error: Callable[[str], None],
    ) -> threading.Thread:
        def worker() -> None:
            try:
                on_success(self.chat(messages))
            except Exception as exc:
                on_error(str(exc))

        thread = threading.Thread(target=worker, daemon=True, name="ReasonableAI")
        thread.start()
        return thread


class ChatBubble(Widget):
    def __init__(self, text: str, role: str = "assistant", **kwargs) -> None:
        super().__init__(**kwargs)
        self.text = str(text)
        self.role = role
        self.padding_x = 14
        self.padding_y = 10
        self._font = get_font(14)
        self._ideal: tuple[int, int] = (240, 40)

    def measure(self, max_width: int, max_height: int) -> tuple[int, int]:
        max_text_width = max(120, int(max_width * 0.84) - self.padding_x * 2)
        lines = wrap_text(self._font, self.text, max_text_width)
        text_width = max((self._font.size(line)[0] for line in lines), default=0)
        width = min(max_text_width, max(60, text_width)) + self.padding_x * 2
        height = max(34, len(lines) * int(14 * 1.4) + self.padding_y * 2)
        self._ideal = (width, height)
        return (width, height)

    def draw(self, surface: pygame.Surface) -> None:
        if not self.visible:
            return
        theme = self.theme
        if self.role == "user":
            bg = with_alpha(theme.accent, 26)
            border = with_alpha(theme.accent, 80)
            text_color = theme.text
        elif self.role == "error":
            bg = with_alpha(theme.danger, 24)
            border = with_alpha(theme.danger, 90)
            text_color = theme.danger
        elif self.role == "system":
            bg = with_alpha(theme.text, 8)
            border = with_alpha(theme.text, 20)
            text_color = theme.muted
        else:
            bg = theme.panel_alt
            border = theme.border
            text_color = theme.text
        radius = 14 if self.role != "user" else 14
        draw_rounded_rect(surface, self.rect, bg, radius, border=border)
        inner = self.rect.inflate(-self.padding_x * 2, -self.padding_y * 2)
        from .utils import draw_wrapped_text

        draw_wrapped_text(
            surface,
            self.text,
            inner,
            14,
            text_color,
            line_height=1.4,
            align="left",
        )


class AIChatPanel(Panel):
    """Ready-made assistant panel with safe local key storage."""

    def __init__(
        self,
        config: AIConfig | None = None,
        *,
        app_name: str = "Reasonable App",
        greeting: str | None = None,
        on_config_saved: Callable[[AIConfig], None] | None = None,
        **kwargs,
    ) -> None:
        kwargs.setdefault("gradient", None)
        super().__init__(**kwargs)
        self.app_name = app_name
        self.config = config or AIConfig.load(app_name)
        self.client = AIClient(self.config)
        self.messages: list[dict[str, str]] = []
        self._queue: queue.Queue = queue.Queue()
        self._busy = False
        self._on_config_saved = on_config_saved
        self._setup_visible = False

        header = HStack(spacing=10, align_y="center")
        header.add(
            Icon("spark", size=24, color_value=self.theme.accent),
            VStack(
                spacing=1,
                align_x="left",
            )
            .add(Label(self.config.title or _tr("AI assistant", "ИИ-ассистент"), size=16, bold=True))
            .add(Label(_tr("Online helper", "Онлайн-помощник"), size=11, color_value=self.theme.muted)),
        )
        spacer = Widget(expand_x=True)
        header.add(spacer)
        self.status_label = Label(
            self._short_model(self.config.model),
            size=11,
            color_value=self.theme.faint,
            wrap=False,
            width=112,
            align="right",
        )
        header.add(self.status_label)
        self.settings_button = IconButton("settings", self._open_setup, size=36, variant="ghost")
        header.add(self.settings_button)
        self.add(header)

        self.messages_stack = VStack(spacing=9)
        self.scroll = ScrollView(self.messages_stack, expand_y=True, stick_to_bottom=True)
        self.add(self.scroll)

        self.entry = Entry(_tr("Ask the AI…", "Спросите ИИ…"), on_submit=lambda _value=None: self.send())
        self.entry.expand_x = True
        self.send_button = IconButton("send", self.send, size=44, variant="primary")
        self.input_row = HStack(spacing=8, align_y="center").add(self.entry, self.send_button)
        self.add(self.input_row)

        self.setup_panel = self._build_setup()
        self.setup_panel.visible = False
        self.add(self.setup_panel)

        if greeting:
            self.add_message("assistant", greeting)
        self._refresh_status()

    # ------------------------------------------------------------------
    def _build_setup(self) -> Panel:
        panel = Panel(padding=16, spacing=10)
        panel.add(
            Label(_tr("AI connection", "Подключение ИИ"), size=16, bold=True),
            Label(
                _tr(
                    "Point to an OpenAI-compatible service (OpenRouter, Groq, Gemini, OpenAI) "
                    "or a local Ollama/LM Studio model.",
                    "Укажите OpenAI-совместимый сервис (OpenRouter, Groq, Gemini, OpenAI) "
                    "или локальную модель Ollama/LM Studio.",
                ),
                size=12,
                color_value=self.theme.muted,
            ),
        )
        self.setup_url = Entry("Base URL", value=self.config.base_url)
        self.setup_model = Entry(_tr("Model", "Модель"), value=self.config.model)
        self.setup_key = Entry(_tr("API key (optional)", "API-ключ (необязательно)"), value=self.config.api_key, password=True)
        panel.add(self.setup_url, self.setup_model, self.setup_key)
        buttons = HStack(spacing=8, align_y="center")
        buttons.add(SpacerWidget(expand_x=True))
        buttons.add(Button(_tr("Cancel", "Отмена"), self._close_setup, variant="ghost", height=38))
        buttons.add(Button(_tr("Save", "Сохранить"), self._save_setup, variant="primary", height=38))
        panel.add(buttons)
        panel.add(
            Label(
                _tr(
                    "The key is stored only on this computer. Free limits depend on the service.",
                    "Ключ сохраняется только на этом компьютере. Бесплатные лимиты зависят от сервиса.",
                ),
                size=10,
                color_value=self.theme.faint,
            )
        )
        return panel

    def _refresh_status(self) -> None:
        if self._busy:
            self.status_label.text = _tr("thinking…", "думает…")
            self.status_label.color_value = color(self.theme.accent_2)
        else:
            self.status_label.text = self._short_model(self.config.model)
            self.status_label.color_value = color(self.theme.faint)

    @staticmethod
    def _short_model(model: str) -> str:
        """Keep long provider ids from pushing the header buttons off-screen."""
        return ellipsis(str(model or ""), get_font(11), 108)

    def _open_setup(self) -> None:
        self.setup_url.set_value(self.config.base_url)
        self.setup_model.set_value(self.config.model)
        self.setup_key.set_value(self.config.api_key)
        self._setup_visible = True
        self.setup_panel.visible = True
        self.scroll.visible = False
        self.input_row.visible = False

    def _close_setup(self) -> None:
        self._setup_visible = False
        self.setup_panel.visible = False
        self.scroll.visible = True
        self.input_row.visible = True

    def _save_setup(self) -> None:
        base_url = self.setup_url.value.strip() or DEFAULT_BASE_URL
        model = self.setup_model.value.strip() or DEFAULT_MODEL
        config = self.config.copy()
        config.base_url = base_url
        config.model = model
        config.api_key = self.setup_key.value.strip()
        self.config = config
        self.client = AIClient(config)
        config.save_local()
        self._close_setup()
        self._refresh_status()
        self.add_message("system", _tr("AI settings saved.", "Настройки ИИ сохранены."))
        if self._on_config_saved:
            try:
                self._on_config_saved(config)
            except Exception:
                pass

    # ------------------------------------------------------------------
    def add_message(self, role: str, text: str) -> ChatBubble:
        bubble = ChatBubble(text, role)
        if role == "user":
            bubble.align_x = "right"
        elif role == "assistant":
            bubble.align_x = "left"
        else:
            bubble.align_x = "center"
        self.messages_stack.add(bubble)
        self.scroll.scroll_to_bottom()
        return bubble

    def ask(self, text: str) -> None:
        self.entry.set_value(text)
        self.send()

    def send(self) -> None:
        text = self.entry.value.strip()
        if not text or self._busy:
            return
        self.entry.set_value("")
        self.add_message("user", text)
        self.messages.append({"role": "user", "content": text})
        self._busy = True
        self._refresh_status()
        self.send_button.set_enabled(False)
        context = [{"role": "system", "content": self.config.system_prompt}] + self.messages[-16:]
        client = self.client

        def success(answer: str) -> None:
            self._queue.put(("ok", answer))

        def error(message: str) -> None:
            self._queue.put(("error", message))

        client.chat_async(context, success, error)

    def update(self, dt: float) -> None:
        super().update(dt)
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                self._busy = False
                self.send_button.set_enabled(True)
                self._refresh_status()
                if kind == "ok":
                    self.messages.append({"role": "assistant", "content": payload})
                    self.add_message("assistant", payload or "…")
                else:
                    self.add_message("error", payload)
        except queue.Empty:
            pass


class SpacerWidget(Widget):
    """Local spacer alias (kept private to avoid confusing imports)."""

    def __init__(self, expand_x: bool = True, expand_y: bool = False) -> None:
        super().__init__(expand_x=expand_x, expand_y=expand_y)
