"""Minimal, dependency-free clients for OpenAI-compatible and Anthropic APIs.

Only the Python standard library is used so external agents and exported apps can
talk to models without installing an SDK. The client is intentionally defensive:
free endpoints often return HTML errors, rate limits, or slightly malformed
tool arguments.
"""

from __future__ import annotations

import json
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Iterable


class AIError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, detail: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.detail = detail


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str = ""


@dataclass
class ChatResult:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def parse_tool_arguments(raw: str) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    raw = _strip_fences(str(raw or ""))
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        if isinstance(value, dict):
            return value
        return {"value": value}
    except Exception:
        # Some models add comments or trailing commas. Try a very small repair.
        repaired = raw
        for old, new in ((",}", "}"), (",]", "]"), ("\n", " ")):
            repaired = repaired.replace(old, new)
        try:
            value = json.loads(repaired)
            if isinstance(value, dict):
                return value
        except Exception:
            pass
        return {"_raw_arguments": raw, "_parse_error": True}


def _join_url(base: str, suffix: str) -> str:
    base = (base or "").strip().rstrip("/")
    if not base:
        raise AIError("Не задан Base URL.")
    if base.endswith(suffix):
        return base
    return base + suffix


class HTTPTransport:
    def __init__(self, timeout: float = 120.0, retries: int = 2) -> None:
        self.timeout = timeout
        self.retries = retries

    def request(
        self,
        url: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "ReasonableEngine/0.1 (+https://reasonable-engine.local)",
            **(headers or {}),
        }
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            request = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                context = ssl.create_default_context()
                with urllib.request.urlopen(request, timeout=self.timeout, context=context) as response:
                    raw = response.read().decode("utf-8", errors="replace")
                    if not raw.strip():
                        return {}
                    try:
                        parsed = json.loads(raw)
                        if isinstance(parsed, dict):
                            return parsed
                        return {"data": parsed}
                    except ValueError:
                        raise AIError(
                            "Сервер вернул не JSON. Возможно, endpoint указан неверно.",
                            detail=raw[:800],
                        )
            except urllib.error.HTTPError as error:
                body = error.read().decode("utf-8", errors="replace")
                last_error = AIError(
                    self._friendly_http_error(error.code, body),
                    status=error.code,
                    detail=body[:2000],
                )
                if error.code in {429, 500, 502, 503, 504} and attempt < self.retries:
                    time.sleep(2.2 + attempt * 2.5)
                    continue
                raise last_error
            except urllib.error.URLError as error:
                reason = error.reason
                if isinstance(reason, (TimeoutError, socket.timeout)):
                    message = "Таймаут соединения с ИИ-сервером. Попробуйте ещё раз или другую модель."
                elif isinstance(reason, ConnectionRefusedError) or "refused" in str(reason).lower():
                    message = (
                        "Не удалось подключиться к локальному ИИ-серверу. "
                        "Проверьте, что Ollama/LM Studio запущен и порт совпадает."
                    )
                else:
                    message = f"Сетевая ошибка: {reason}"
                last_error = AIError(message, detail=str(reason))
                if attempt < self.retries:
                    time.sleep(1.5)
                    continue
                raise last_error
            except (TimeoutError, socket.timeout):
                last_error = AIError(
                    "ИИ-сервер не ответил вовремя. Бесплатные модели иногда перегружены — попробуйте позже."
                )
                if attempt < self.retries:
                    time.sleep(1.5)
                    continue
                raise last_error
            except OSError as error:
                last_error = AIError(f"Ошибка сети: {error}", detail=str(error))
                if attempt < self.retries:
                    time.sleep(1.5)
                    continue
                raise last_error
        raise last_error or AIError("Неизвестная ошибка сети")

    @staticmethod
    def _friendly_http_error(code: int, body: str) -> str:
        detail = ""
        try:
            payload = json.loads(body)
            if isinstance(payload, dict):
                error = payload.get("error", payload)
                if isinstance(error, dict):
                    detail = str(error.get("message") or error.get("detail") or "")
                else:
                    detail = str(error)
        except Exception:
            detail = body[:300]
        hints = {
            400: "Сервер отклонил запрос (400). Проверьте модель и поддержку инструментов.",
            401: "Ключ API не принят (401). Проверьте ключ в настройках.",
            402: "На счету провайдера закончились средства (402) или лимит бесплатных кредитов.",
            403: "Доступ запрещён (403). Возможно, ключ не имеет доступа к этой модели или региону.",
            404: "Endpoint или модель не найдены (404). Проверьте Base URL и название модели.",
            413: "Слишком большой запрос (413). Уменьшите контекст.",
            422: "Провайдер не понял запрос (422). Попробуйте другую модель.",
            429: "Лимит запросов исчерпан (429). Подождите или выберите другой провайдер/модель.",
            500: "Ошибка на стороне ИИ-провайдера (500).",
            502: "Плохой ответ шлюза ИИ (502).",
            503: "ИИ-сервис временно недоступен (503).",
            504: "Шлюз ИИ не ответил вовремя (504).",
        }
        base = hints.get(code, f"HTTP {code} от ИИ-сервера.")
        return f"{base} {detail}".strip()


class AIClient:
    def __init__(self, config: dict[str, Any], *, timeout: float = 120.0, retries: int = 2) -> None:
        self.config = config
        self.kind = config.get("kind", "openai")
        self.base_url = str(config.get("base_url", "")).strip()
        self.api_key = str(config.get("api_key", "")).strip()
        self.model = str(config.get("model", "")).strip()
        self.headers = dict(config.get("headers") or {})
        self.timeout = timeout
        self.retries = retries
        self.http = HTTPTransport(timeout=timeout, retries=retries)

    # ------------------------------------------------------------------
    def _auth_headers(self) -> dict[str, str]:
        headers = dict(self.headers)
        if self.kind == "anthropic":
            if self.api_key:
                headers["x-api-key"] = self.api_key
            headers["anthropic-version"] = "2023-06-01"
            headers["Content-Type"] = "application/json"
        else:
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _chat_url(self) -> str:
        if self.kind == "anthropic":
            return _join_url(self.base_url, "/messages")
        base = self.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return base + "/chat/completions"

    def _models_url(self) -> str:
        base = self.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            base = base[: -len("/chat/completions")]
        if self.kind == "anthropic":
            return base + "/models"
        return base + "/models"

    # ------------------------------------------------------------------
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        temperature: float = 0.65,
        max_tokens: int = 8192,
    ) -> ChatResult:
        if not self.base_url:
            raise AIError("Не задан Base URL провайдера.")
        if not self.model:
            raise AIError("Не выбрана модель ИИ.")
        if self.kind == "anthropic":
            return self._chat_anthropic(messages, tools, temperature, max_tokens)
        return self._chat_openai(messages, tools, temperature, max_tokens)

    def _chat_openai(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        temperature: float,
        max_tokens: int,
    ) -> ChatResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "parameters": tool.get("parameters", {"type": "object", "properties": {}}),
                    },
                }
                for tool in tools
            ]
            payload["tool_choice"] = "auto"
        # Some OpenAI-compatible endpoints reject unsupported parameters; retry
        # without them if we get a specific 400.
        try:
            data = self.http.request(
                self._chat_url(), method="POST", headers=self._auth_headers(), payload=payload
            )
        except AIError as error:
            if error.status == 400 and tools:
                payload.pop("tools", None)
                payload.pop("tool_choice", None)
                data = self.http.request(
                    self._chat_url(), method="POST", headers=self._auth_headers(), payload=payload
                )
            elif error.status == 400 and "temperature" in error.detail.lower():
                payload.pop("temperature", None)
                data = self.http.request(
                    self._chat_url(), method="POST", headers=self._auth_headers(), payload=payload
                )
            else:
                raise
        choices = data.get("choices") or []
        if not choices:
            message = "Провайдер вернул пустой ответ."
            if data.get("error"):
                message += f" {data['error']}"
            raise AIError(message, detail=json.dumps(data, ensure_ascii=False)[:1500])
        message = choices[0].get("message") or {}
        content = message.get("content") or ""
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part) for part in content
            )
        calls: list[ToolCall] = []
        for index, call in enumerate(message.get("tool_calls") or []):
            function = call.get("function") or {}
            name = str(function.get("name") or "")
            raw_args = function.get("arguments") or "{}"
            arguments = parse_tool_arguments(raw_args)
            calls.append(
                ToolCall(
                    id=str(call.get("id") or f"call_{index}_{int(time.time())}"),
                    name=name,
                    arguments=arguments,
                    raw_arguments=raw_args if isinstance(raw_args, str) else json.dumps(raw_args),
                )
            )
        usage = data.get("usage") or {}
        return ChatResult(
            content=str(content).strip() if content else "",
            tool_calls=calls,
            usage=usage if isinstance(usage, dict) else {},
            raw=data,
        )

    def _chat_anthropic(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        temperature: float,
        max_tokens: int,
    ) -> ChatResult:
        system_parts: list[str] = []
        converted: list[dict[str, Any]] = []
        pending_tool_results: list[dict[str, Any]] = []

        for message in messages:
            role = message.get("role")
            if role == "system":
                system_parts.append(str(message.get("content") or ""))
                continue
            if role == "tool":
                pending_tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": message.get("tool_call_id", ""),
                        "content": str(message.get("content") or ""),
                    }
                )
                continue
            if pending_tool_results:
                converted.append({"role": "user", "content": pending_tool_results})
                pending_tool_results = []
            if role == "assistant":
                blocks: list[dict[str, Any]] = []
                text = str(message.get("content") or "").strip()
                if text:
                    blocks.append({"type": "text", "text": text})
                for call in message.get("tool_calls") or []:
                    function = call.get("function", {})
                    raw_args = function.get("arguments") or "{}"
                    arguments = parse_tool_arguments(raw_args)
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": call.get("id", ""),
                            "name": function.get("name", ""),
                            "input": arguments,
                        }
                    )
                if blocks:
                    converted.append({"role": "assistant", "content": blocks})
            elif role == "user":
                converted.append({"role": "user", "content": str(message.get("content") or "")})
        if pending_tool_results:
            converted.append({"role": "user", "content": pending_tool_results})

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": converted,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        if tools:
            payload["tools"] = [
                {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "input_schema": tool.get("parameters", {"type": "object", "properties": {}}),
                }
                for tool in tools
            ]
        data = self.http.request(
            self._chat_url(), method="POST", headers=self._auth_headers(), payload=payload
        )
        content_parts: list[str] = []
        calls: list[ToolCall] = []
        for block in data.get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                content_parts.append(str(block.get("text") or ""))
            elif block.get("type") == "tool_use":
                arguments = block.get("input") or {}
                calls.append(
                    ToolCall(
                        id=str(block.get("id") or f"tool_{len(calls)}"),
                        name=str(block.get("name") or ""),
                        arguments=arguments if isinstance(arguments, dict) else {"value": arguments},
                        raw_arguments=json.dumps(arguments, ensure_ascii=False),
                    )
                )
        usage = data.get("usage") or {}
        return ChatResult(
            content="\n".join(part for part in content_parts if part).strip(),
            tool_calls=calls,
            usage=usage if isinstance(usage, dict) else {},
            raw=data,
        )

    # ------------------------------------------------------------------
    def list_models(self) -> list[str]:
        try:
            data = self.http.request(self._models_url(), headers=self._auth_headers())
        except AIError:
            raise
        items = data.get("data") or data.get("models") or []
        models: list[str] = []
        if isinstance(items, list):
            for item in items:
                if isinstance(item, str):
                    models.append(item)
                elif isinstance(item, dict):
                    model_id = item.get("id") or item.get("name") or item.get("model")
                    if model_id:
                        models.append(str(model_id))
        # Some endpoints return a plain list (wrapped as {"data": ...} by the transport).
        return sorted(dict.fromkeys(models), key=str.lower)

    def test_connection(self) -> str:
        try:
            models = self.list_models()
            if models:
                sample = ", ".join(models[:3])
                return f"Соединение работает. Доступно моделей: {len(models)} ({sample}…)"
        except AIError:
            # Listing models is optional on some OpenAI-compatible servers.
            pass
        result = self.chat(
            [
                {"role": "system", "content": "Отвечай предельно кратко."},
                {"role": "user", "content": "Ответь одним словом: работает"},
            ],
            temperature=0,
            max_tokens=20,
        )
        text = result.content or "пустой ответ"
        return f"Соединение работает. Ответ модели: {text[:80]}"


def fetch_models(config: dict[str, Any]) -> list[str]:
    return AIClient(config, timeout=45, retries=0).list_models()


def test_provider(config: dict[str, Any]) -> str:
    return AIClient(config, timeout=60, retries=1).test_connection()
