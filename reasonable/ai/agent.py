"""Autonomous agent loop used by the editor.

The agent talks to any OpenAI-compatible or Anthropic model with native tool
calling, executes tools inside the project, and mirrors its state into
``progress/`` so the UI stays alive even if a step takes a while.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from reasonable.core import i18n
from reasonable.core.agent_errors import classify_agent_error
from reasonable.core.history import create_snapshot, update_snapshot
from reasonable.core.i18n import tr as _tr
from reasonable.core.progress import read_state, record_event, set_status
from reasonable.core.settings import Settings

from .client import AIClient, AIError, ChatResult, ToolCall
from .prompts import build_agent_system_prompt, build_initial_user_message
from .tools import ANALYSIS_TOOL_NAMES, ANALYSIS_TOOL_SCHEMAS, TOOL_SCHEMAS, AgentTools


@dataclass
class AgentEvent:
    kind: str
    text: str = ""
    data: dict[str, Any] = field(default_factory=dict)


EventCallback = Callable[[AgentEvent], None]
CancelFlag = threading.Event


class AgentCancelled(RuntimeError):
    pass


_FALLBACK_TOOL_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)

# A single tool result larger than this is truncated before it goes into the
# conversation. read_file defaults to 800 lines, which is easily 100k+ tokens
# for generated code; feeding that back on every step was one of the reasons a
# long run lost its task and kept repeating itself.
MAX_TOOL_RESULT_CHARS = 20_000


def _shorten_tool_output(text: str) -> str:
    value = str(text or "")
    if len(value) <= MAX_TOOL_RESULT_CHARS:
        return value
    head = MAX_TOOL_RESULT_CHARS - 2_500
    return (
        value[:head]
        + f"\n... [output truncated: {len(value)} characters total; "
        "request a smaller range with start_line/end_line] ...\n"
        + value[-2_000:]
    )


# Independent completion audit. This is AI-facing material and therefore
# English-only, like tools and skills. It runs as a separate request after the
# agent thinks it is done, so the model cannot simply agree with itself.
SUPERVISOR_PROMPT = """You are a strict, independent completion auditor for a software project.
You receive the user's original task, the agent's final report, the changed files
with their current code, validation/run results and the project's scenes.

Judge ONLY whether the user's exact request is implemented and works. Do not
reward unrelated polish, do not assume the agent's report is true, and do not
invent requirements that are not in the task. A starter example existing in the
project does NOT count as completing the task.

Respond with exactly one JSON object and nothing else:
{"complete": true, "missing": [], "next": ""}
or
{"complete": false, "missing": ["specific unmet item"], "next": "one concrete next action"}

Rules:
- complete=true only when the requested behaviour is present in the code and
  the available validation/run evidence does not contradict it.
- For a purely informational task, a correct answer in the final report is enough.
- Keep "missing" short and concrete; put the most useful next step in "next".
- Write the values of "missing" and "next" in the language given by
  "reply_language" (ru → Russian, en → English). JSON keys stay English.
- Never ask for secrets, never propose changes outside the project."""

# Older turns are compressed instead of being thrown away. The summary is
# AI-facing material, so it is English-only like the other prompts.
COMPACTION_PROMPT = """You compress the older part of an AI coding-agent conversation.
Return a compact factual summary that lets the agent continue without the original messages.

Keep: the user's goal, decisions and constraints, files created or edited, important
commands and their results, unresolved errors, the current plan, and the next step.
Drop: greetings, repeated reasoning, full file contents, successful command output,
and anything that is already superseded.

Write in English. Use short bullet points. Return only the summary, no preamble."""


def _extract_json_object(text: str) -> dict | None:
    """Best-effort JSON object extraction from a model reply."""
    value = (text or "").strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value)
        value = re.sub(r"\s*```$", "", value)
    start = value.find("{")
    end = value.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(value[start : end + 1])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _parse_fallback_tool(content: str) -> tuple[str, dict] | None:
    """Support models that emulate tool calls as a fenced JSON object."""
    for match in _FALLBACK_TOOL_RE.finditer(content or ""):
        try:
            payload = json.loads(match.group(1))
        except ValueError:
            continue
        if not isinstance(payload, dict):
            continue
        name = payload.get("tool") or payload.get("name")
        arguments = payload.get("arguments") or payload.get("input") or {}
        if isinstance(name, str) and isinstance(arguments, dict):
            return name, arguments
    return None


def _looks_degenerate(text: str) -> bool:
    """Catch a model that is stuck repeating the same words or lines.

    Some providers occasionally return a "thought loop" such as
    ``Ok. Go. Done. Write. Emit.`` repeated dozens of times. Showing that as
    the assistant's answer fills the chat and, worse, feeds the loop back into
    the next request. A reply is treated as degenerate when it is made of many
    short repeated lines or contains the same four-word phrase many times.
    Code blocks are ignored: generated code legitimately repeats patterns.
    """
    value = (text or "").strip()
    if not value or "```" in value:
        return False
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if len(lines) >= 6:
        unique = len(set(lines))
        if unique / len(lines) < 0.45:
            return True
        counts: dict[str, int] = {}
        for line in lines:
            counts[line] = counts.get(line, 0) + 1
        if max(counts.values()) >= 4:
            return True
        # A repeated block of consecutive lines is just as telling as a
        # repeated single line ("Ok. / Go. / Done." over and over).
        seen_blocks: set[tuple[str, ...]] = set()
        for index in range(len(lines) - 2):
            block = tuple(lines[index : index + 3])
            if block in seen_blocks:
                return True
            seen_blocks.add(block)
    words = re.findall(r"\S+", value.lower())
    if len(words) >= 40:
        grams: dict[tuple[str, ...], int] = {}
        for index in range(len(words) - 3):
            gram = tuple(words[index : index + 4])
            grams[gram] = grams.get(gram, 0) + 1
        if grams and max(grams.values()) >= 6:
            return True
    return False


def _assistant_message(result: ChatResult) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": result.content or ""}
    if result.tool_calls:
        message["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=False),
                },
            }
            for call in result.tool_calls
        ]
    return message


class Agent:
    def __init__(
        self,
        project,
        settings: Settings | None = None,
        *,
        on_event: EventCallback | None = None,
        cancel: CancelFlag | None = None,
        provider_config: dict[str, Any] | None = None,
        image_config: dict[str, Any] | None = None,
        chat_id: str | None = None,
        hidden_message: bool = False,
        analysis: bool = False,
        reply_language: str | None = None,
        persist_messages: bool = True,
        extra_system_prompt: str = "",
        write_scope: tuple[str, ...] | None = None,
        seed_history: bool = True,
        create_snapshot: bool = True,
        supervisor: bool | None = None,
        require_ready: bool = True,
        tool_schemas_override: list[dict[str, Any]] | None = None,
        sync_history: bool = True,
    ) -> None:
        self.project = project
        self.settings = settings or Settings()
        self.on_event = on_event
        self.cancel = cancel or threading.Event()
        self.chat_id = chat_id
        self.config = dict(provider_config or self.settings.get_provider_config())
        # OpenCode Go routes and caches a conversation by x-opencode-session.
        # Reuse the durable chat id so the id stays identical across runs; the
        # client supplies a fallback for one-off requests.
        if chat_id and (
            "opencode.ai" in str(self.config.get("base_url") or "").lower()
            or self.config.get("id") == "opencode"
        ):
            headers = dict(self.config.get("headers") or {})
            headers["x-opencode-session"] = f"reasonable-{chat_id}"
            self.config["headers"] = headers
        try:
            agent_cfg = self.settings.data.get("agent", {}) or {}
            self.config.setdefault(
                "max_output_tokens", int(agent_cfg.get("max_output_tokens", 16384) or 16384)
            )
        except (TypeError, ValueError):
            self.config["max_output_tokens"] = 16384
        try:
            self._context_window = max(
                4_000, int(self.config.get("context_window") or 128_000)
            )
        except (TypeError, ValueError):
            self._context_window = 128_000
        self.client = AIClient(self.config, timeout=180, retries=2)
        self.image_config = image_config or self.settings.image_config()
        self.tools = AgentTools(
            project,
            image_config=self.image_config,
            write_scope=write_scope,
        )
        self.extra_system_prompt = str(extra_system_prompt or "").strip()
        self.seed_history = bool(seed_history)
        self.create_snapshot = bool(create_snapshot)
        self.supervisor_override = supervisor
        self.require_ready = bool(require_ready)
        self.tool_schemas_override = tool_schemas_override
        self.sync_history = bool(sync_history)
        self.hidden_message = bool(hidden_message)
        self.analysis = bool(analysis)
        self.reply_language = reply_language
        # The editor UI persists exactly what it renders (user bubbles,
        # assistant replies, errors) as the run happens. Headless callers
        # (CLI, tests) let the agent write the durable history itself.
        self.persist_messages = bool(persist_messages)
        self.tool_schemas = (
            self.tool_schemas_override
            if self.tool_schemas_override is not None
            else (ANALYSIS_TOOL_SCHEMAS if self.analysis else TOOL_SCHEMAS)
        )
        # Advertising a tool is not enough: models sometimes call tools they
        # were told not to use. Specialists must not touch global plan/progress
        # or finish the whole project behind the orchestrator's back.
        self._allowed_tool_names = {
            str(schema.get("name"))
            for schema in self.tool_schemas
            if schema.get("name")
        }
        self.messages: list[dict[str, Any]] = []
        self.finished = False
        self.final_text = ""
        self.last_error = ""
        self.incomplete_reason = ""
        self.snapshot: dict[str, Any] | None = None
        self.changes: list[dict[str, Any]] = []
        self.outcome = ""
        self._nudges = 0
        self._install_nudged = False
        self._degenerate_repeats = 0
        self._truncated_repeats = 0
        self._task_message: dict[str, Any] | None = None
        self._context_chars = 120_000
        self._stall_limit = 0
        self._stall_signature: tuple | None = None
        self._stall_counter = 0
        self._stall_warned = False
        self._evidence_paths: set[str] = set()
        # Context compaction: real prompt tokens are unknown without the
        # model's tokenizer, so the ratio is calibrated from the provider's
        # reported prompt_tokens after every call.
        self._chars_per_token = 3.6
        self._context_tokens = 48_000
        self._compaction_enabled = False
        self._compaction_failures = 0
        self._summary = ""
        self._summary_message: dict[str, Any] | None = None
        self._pending_dropped: list[dict[str, Any]] = []
        try:
            self._tool_schema_chars = len(
                json.dumps(self.tool_schemas, ensure_ascii=False)
            )
        except (TypeError, ValueError):
            self._tool_schema_chars = 0
        self.supervisor_enabled = self._supervisor_setting()
        self._supervisor_signature: tuple | None = None
        self._supervisor_repeats = 0
        self._supervisor_runs = 0
        self._supervisor_last_missing: list[str] = []

    def _supervisor_setting(self) -> bool:
        if self.supervisor_override is not None:
            return bool(self.supervisor_override)
        try:
            agent = self.settings.data.get("agent", {})
            return bool((agent or {}).get("supervisor", True))
        except Exception:
            return True

    # ------------------------------------------------------------------
    def emit(self, kind: str, text: str = "", **data: Any) -> None:
        if self.on_event is None:
            return
        try:
            self.on_event(AgentEvent(kind, text, data))
        except Exception:
            pass

    def _check_cancel(self) -> None:
        if self.cancel.is_set():
            raise AgentCancelled(_tr("The agent was stopped by the user.", "Работа агента остановлена пользователем."))

    @staticmethod
    def _usage_payload(usage: dict[str, Any] | None, seconds: float) -> dict[str, Any]:
        """Normalize OpenAI/Anthropic/DeepSeek/OpenCode usage.

        Besides plain prompt/completion counts, providers report prompt-cache
        hits in different places. They are normalized here so the chat can show
        how much of the expensive prompt was actually read from cache.
        """
        raw = usage or {}

        def number(*keys: str) -> int:
            for key in keys:
                try:
                    value = int(raw.get(key) or 0)
                except (TypeError, ValueError):
                    value = 0
                if value:
                    return value
            return 0

        cached = number(
            "cached_tokens",
            "cache_read_input_tokens",
            "prompt_cache_hit_tokens",
            "cache_read_tokens",
        )
        if not cached:
            details = raw.get("prompt_tokens_details")
            if isinstance(details, dict):
                try:
                    cached = int(details.get("cached_tokens") or 0)
                except (TypeError, ValueError):
                    cached = 0
        opencode = raw.get("opencode")
        opencode_tokens = opencode.get("tokens") if isinstance(opencode, dict) else None
        if not cached and isinstance(opencode_tokens, dict):
            try:
                cached = int(opencode_tokens.get("cache_read") or 0)
            except (TypeError, ValueError):
                cached = 0

        cache_write = number(
            "cache_creation_input_tokens",
            "cache_write_tokens",
        )
        if not cache_write and isinstance(opencode_tokens, dict):
            try:
                cache_write = int(opencode_tokens.get("cache_write_5m") or 0) + int(
                    opencode_tokens.get("cache_write_1h") or 0
                )
            except (TypeError, ValueError):
                cache_write = 0

        prompt = number("prompt_tokens", "input_tokens")
        # Anthropic's input_tokens exclude cache reads/writes; OpenAI-style
        # prompt_tokens already include them.
        if "prompt_tokens" not in raw and raw.get("input_tokens") is not None:
            prompt += cached + cache_write
        completion = number("completion_tokens", "output_tokens")
        total = number("total_tokens", "total") or prompt + completion
        return {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": total,
            "cached_tokens": cached,
            "cache_write_tokens": cache_write,
            "seconds": round(max(0.0, float(seconds)), 3),
        }

    def _call_model(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        *,
        temperature: float,
    ) -> ChatResult:
        started = time.perf_counter()
        try:
            result = self.client.chat(messages, tools, temperature=temperature)
        except Exception:
            # Failed requests still consume time; keep the lifetime clock honest
            # even when the provider returns no usage payload.
            self.emit("usage", usage=self._usage_payload(None, time.perf_counter() - started))
            raise
        elapsed = time.perf_counter() - started
        self._calibrate_tokens(messages, tools, result.usage)
        # Emit even when the provider omits usage: generation time is still a
        # real cost and belongs in the lifetime counter.
        self.emit("usage", usage=self._usage_payload(result.usage, elapsed))
        return result

    @staticmethod
    def _message_chars(item: dict[str, Any]) -> int:
        chars = len(str(item.get("content") or ""))
        if item.get("tool_calls"):
            try:
                chars += len(json.dumps(item["tool_calls"], ensure_ascii=False))
            except (TypeError, ValueError):
                pass
        return chars

    def _estimate_messages_tokens(self, messages: list[dict[str, Any]]) -> int:
        chars = sum(self._message_chars(item) for item in messages)
        chars += int(getattr(self, "_tool_schema_chars", 0) or 0)
        ratio = max(1.5, float(getattr(self, "_chars_per_token", 3.6) or 3.6))
        return max(1, int(chars / ratio))

    def _calibrate_tokens(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        usage: dict[str, Any] | None,
    ) -> None:
        """Learn this model's characters-per-token ratio from real usage.

        A real tokenizer is model-specific and the engine must stay
        dependency-free, so the estimate is calibrated from the provider's
        ``prompt_tokens`` instead of staying a blind character count.
        """
        try:
            prompt_tokens = int((usage or {}).get("prompt_tokens") or 0)
        except (TypeError, ValueError):
            prompt_tokens = 0
        if prompt_tokens <= 0:
            return
        chars = sum(self._message_chars(item) for item in messages)
        if tools:
            try:
                chars += len(json.dumps(tools, ensure_ascii=False))
            except (TypeError, ValueError):
                pass
        if chars <= 0:
            return
        observed = chars / prompt_tokens
        if not 1.2 <= observed <= 9.0:
            return
        current = max(1.5, float(getattr(self, "_chars_per_token", 3.6) or 3.6))
        self._chars_per_token = max(1.5, min(9.0, current * 0.75 + observed * 0.25))

    def _compact_messages(self, messages: list[dict[str, Any]]) -> str:
        """Merge a chunk of old messages into the running summary."""
        if (
            not self._compaction_enabled
            or self._compaction_failures >= 2
            or not messages
        ):
            return ""
        self._check_cancel()
        parts: list[str] = []
        for item in messages[-80:]:
            role = str(item.get("role") or "")
            if role == "system":
                continue
            text = str(item.get("content") or "")
            if item.get("tool_calls"):
                names: list[str] = []
                for call in item.get("tool_calls") or []:
                    function = call.get("function") if isinstance(call, dict) else None
                    if isinstance(function, dict) and function.get("name"):
                        names.append(str(function["name"]))
                if names:
                    text = f"[called: {', '.join(names)}]\n{text}"
            limit = 1_200 if role == "tool" else 2_500
            text = text.strip()[:limit]
            if text:
                parts.append(f"{role.upper()}: {text}")
        payload = "\n\n".join(parts)
        if len(payload) < 3_000:
            return ""
        payload = payload[:60_000]
        user_content = ""
        previous = self._summary.strip()
        if previous:
            user_content += f"Previous summary:\n{previous}\n\n"
        user_content += "New conversation messages:\n" + payload
        self.emit(
            "status",
            _tr(
                "Compressing older conversation context…",
                "Сжимаю старый контекст разговора…",
            ),
        )
        try:
            result = self._call_model(
                [
                    {"role": "system", "content": COMPACTION_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                None,
                temperature=0.0,
            )
        except AgentCancelled:
            raise
        except Exception:
            self._compaction_failures += 1
            return ""
        self._check_cancel()
        summary = (result.content or "").strip()
        if (
            not summary
            or result.finish_reason in {"length", "max_tokens"}
            or _looks_degenerate(summary)
        ):
            self._compaction_failures += 1
            return ""
        self._compaction_failures = 0
        self._summary = summary[:6_000]
        self._summary_message = {
            "role": "user",
            "content": (
                "CONVERSATION SUMMARY (older context, do not reply):\n"
                + self._summary
            ),
        }
        return self._summary

    def _queue_dropped(self, dropped: list[dict[str, Any]]) -> None:
        if not dropped or not self._compaction_enabled or self._compaction_failures >= 2:
            return
        self._pending_dropped.extend(dropped)
        if len(self._pending_dropped) > 80:
            self._pending_dropped = self._pending_dropped[-80:]
        chars = sum(self._message_chars(item) for item in self._pending_dropped)
        # Small tool results should accumulate instead of triggering a summary
        # call for a handful of characters.
        if len(self._pending_dropped) < 40 and chars < 24_000:
            return
        if chars < 3_000 and len(self._pending_dropped) < 80:
            return
        chunk = self._pending_dropped
        self._pending_dropped = []
        self._compact_messages(chunk)

    def _trim_history(self) -> None:
        """Keep the task and a bounded, structurally valid recent window.

        The old implementation popped leading assistant/tool messages until it
        found a ``user`` message. In a normal tool-calling run the only user
        message is the original task, so after ~18 steps the whole window was
        discarded and the model was called with the system prompt only. It then
        made random tool calls forever because it no longer knew the task.
        Here the original task is pinned, older turns are compressed into a
        running summary when possible, and the recent window is trimmed from the
        front in complete assistant/tool groups. Both a token budget and a
        character budget keep one huge ``read_file`` from blowing the context.
        """
        if not self.messages:
            return
        try:
            agent_settings = self.settings.data.get("agent", {}) or {}
            limit = max(12, int(agent_settings.get("context_messages", 36) or 36))
            context_chars = max(
                20_000, int(agent_settings.get("context_chars", 120_000) or 120_000)
            )
        except (TypeError, ValueError):
            limit = 36
            context_chars = 120_000

        # Keep the exact message list while it fits. Rebuilding it reorders the
        # history note and the task, which invalidates the provider's prompt
        # cache for no reason.
        if len(self.messages) <= limit + 2:
            chars = sum(self._message_chars(item) for item in self.messages)
            if (
                chars <= context_chars
                and self._estimate_messages_tokens(self.messages) <= self._context_tokens
            ):
                return

        system = self.messages[0]
        pinned = self._task_message
        if pinned is None:
            # Tests and one-off callers sometimes set ``messages`` directly.
            pinned = next(
                (
                    item
                    for item in self.messages[1:]
                    if item.get("role") == "user"
                ),
                None,
            )
            self._task_message = pinned
        summary_message = self._summary_message
        if summary_message is not None and not any(
            item is summary_message for item in self.messages
        ):
            summary_message = None
        body = [
            item
            for item in self.messages[1:]
            if item is not pinned and item is not summary_message
        ]
        recent = body[-limit:]
        # A tool result without the assistant tool_call that produced it is an
        # invalid conversation for every provider.
        while recent and recent[0].get("role") == "tool":
            recent.pop(0)

        def over_budget() -> bool:
            prompt = [system]
            if pinned is not None and pinned is not system:
                prompt.append(pinned)
            if summary_message is not None:
                prompt.append(summary_message)
            prompt.extend(recent)
            chars = sum(self._message_chars(item) for item in prompt)
            tokens = self._estimate_messages_tokens(prompt)
            return tokens > self._context_tokens or chars > context_chars

        while over_budget() and len(recent) > 1:
            first = recent.pop(0)
            # Dropping an assistant tool_call also drops its results, otherwise
            # the next request contains orphaned tool messages.
            if first.get("role") == "assistant" and first.get("tool_calls"):
                while recent and recent[0].get("role") == "tool":
                    recent.pop(0)
            while recent and recent[0].get("role") == "tool":
                recent.pop(0)

        dropped = body[: len(body) - len(recent)]
        self._queue_dropped(dropped)
        summary_message = self._summary_message

        trimmed = [system]
        if pinned is not None and pinned is not system:
            trimmed.append(pinned)
        if summary_message is not None:
            trimmed.append(summary_message)
        trimmed.extend(recent)
        self.messages = trimmed

    def _supervisor_payload(self, task_text: str, final_text: str) -> dict[str, Any]:
        changed: list[dict[str, Any]] = []
        for item in self.tools.changed_files[:6]:
            path = str(item.get("path") or "")
            entry: dict[str, Any] = {
                "path": path,
                "action": str(item.get("action") or "edit"),
            }
            try:
                entry["content"] = self.project.read_text(path)[:5000]
            except Exception:
                entry["content"] = ""
            changed.append(entry)
        # The auditor also needs the entry point when the task touched other
        # files; it is the quickest way to see how the project starts.
        if not any(item.get("path") == "main.py" for item in changed):
            try:
                changed.append(
                    {
                        "path": "main.py",
                        "action": "unchanged",
                        "content": self.project.read_text("main.py")[:4000],
                    }
                )
            except Exception:
                pass
        scenes: list[dict[str, Any]] = []
        try:
            from ..core.scene import list_scenes, load_scene

            for summary in list_scenes(self.project.root)[:8]:
                scene = load_scene(self.project.root, summary["id"])
                objects = scene.get("objects") or []
                scenes.append(
                    {
                        "id": summary["id"],
                        "title": summary["title"],
                        "objects": len(objects),
                        "markers": [
                            str(obj.get("role") or obj.get("name") or "")
                            for obj in objects
                            if isinstance(obj, dict) and obj.get("marker")
                        ],
                        "names": [str(obj.get("name") or "") for obj in objects[:20] if isinstance(obj, dict)],
                    }
                )
        except Exception:
            pass
        readiness = self.tools.readiness()
        return {
            "user_task": task_text[:4000],
            "agent_final_report": (final_text or "")[:4000],
            "reply_language": i18n.current_language(),
            "project": {
                "name": self.project.name,
                "type": self.project.project_type,
                "goal": self.project.goal,
            },
            "changed_files": changed,
            "validation": {
                "passed": bool(readiness.get("validation_passed")),
                "run_passed": bool(readiness.get("run_passed")),
                "missing": list(readiness.get("missing") or []),
            },
            "scenes": scenes,
        }

    def _supervise_completion(
        self, task_text: str, final_text: str
    ) -> tuple[bool, str, bool]:
        """Independent audit of the user's exact task.

        Returns ``(complete, feedback, stalled)``. ``feedback`` is appended to
        the agent conversation when the task is incomplete; ``stalled`` means
        the auditor repeated the same verdict without any progress, so the run
        must end honestly instead of looping forever.
        """
        if not self.supervisor_enabled or self.analysis or not str(task_text or "").strip():
            return True, "", False
        self._supervisor_runs += 1
        self.emit(
            "status",
            _tr(
                "Independent check: did the agent do exactly the task?",
                "Независимая проверка: агент сделал именно то, что просили?",
            ),
        )
        payload = self._supervisor_payload(task_text, final_text)
        messages = [
            {"role": "system", "content": SUPERVISOR_PROMPT},
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False),
            },
        ]
        try:
            result = self._call_model(messages, None, temperature=0.0)
        except Exception:
            self.emit(
                "status",
                _tr(
                    "The independent check is unavailable — accepting the result.",
                    "Независимая проверка недоступна — принимаю результат.",
                ),
            )
            return True, "", False
        data = _extract_json_object(result.content)
        if data is None or "complete" not in data:
            return True, "", False
        if bool(data.get("complete")):
            self._supervisor_last_missing = []
            self.emit(
                "supervisor",
                _tr("Independent check passed.", "Независимая проверка пройдена."),
                complete=True,
            )
            return True, "", False

        missing = [
            str(item).strip()
            for item in (data.get("missing") or [])
            if str(item).strip()
        ][:8]
        next_step = str(data.get("next") or data.get("instruction") or "").strip()
        if not missing and not next_step:
            missing = [
                _tr(
                    "The task request is not verifiably implemented.",
                    "Запрос задачи не подтверждён реализацией.",
                )
            ]
        self._supervisor_last_missing = missing
        self.emit(
            "supervisor",
            _tr(
                "Independent check found unfinished items — continuing.",
                "Независимая проверка нашла невыполненные пункты — продолжаю.",
            ),
            complete=False,
            missing=missing,
        )
        readiness = self.tools.readiness()
        signature = (
            len(self.tools.changed_files),
            bool(readiness.get("validation_passed")),
            bool(readiness.get("run_passed")),
        )
        if signature == self._supervisor_signature:
            self._supervisor_repeats += 1
        else:
            self._supervisor_signature = signature
            self._supervisor_repeats = 0
        stalled = self._supervisor_repeats >= 2

        feedback = (
            # Sent to the model: AI-facing material stays English-only.
            "SUPERVISOR REVIEW — the task is not complete yet.\n"
            f"Original user task:\n{task_text[:2000]}\n\n"
            "Still missing:\n"
            + ("\n".join(f"- {item}" for item in missing) or "- verify the requested behaviour")
            + "\n\n"
            f"Next concrete action: {next_step or 'implement and verify the missing items with tools.'}\n\n"
            "Continue working. Do not call finish until these items are actually implemented "
            "and validation/run evidence supports them."
        )
        return False, feedback, stalled

    def _reset_loop_tracking(self) -> None:
        self._last_tool_signature = None
        self._repeat_count = 0

    def _auto_verify(self) -> tuple[str, str]:
        """Run validation (and a smoke run) without waiting for the model."""
        if self.analysis:
            return "", ""
        self.emit("tool_start", "validate_project", tool="validate_project", arguments={})
        try:
            validation = self.tools.call("validate_project")
        except Exception as exc:
            validation = f"validate_project failed: {exc}"
        self.emit(
            "tool_result",
            "validate_project",
            tool="validate_project",
            success=not validation.startswith("validate_project failed"),
            result=validation[:5000],
        )
        run = ""
        try:
            parsed = json.loads(validation)
            errors = bool(parsed.get("has_errors"))
            if not errors and self.tools.files_changed > 0:
                self.emit("tool_start", "run_project", tool="run_project", arguments={})
                run = self.tools.call("run_project")
                self.emit(
                    "tool_result",
                    "run_project",
                    tool="run_project",
                    success='"returncode": 0' in run or '"ok": true' in run.lower(),
                    result=run[:5000],
                )
        except (TypeError, ValueError):
            pass
        return validation, run

    def _recovery_prompt(
        self,
        readiness: dict[str, Any],
        validation: str = "",
        run: str = "",
        extra: str = "",
    ) -> str:
        missing = "; ".join(readiness.get("missing") or []) or "finish the requested task"
        parts = [
            "AUTONOMOUS RECOVERY — you stopped before the task was complete.",
            "Do not apologise, do not write a summary, do not stop.",
            f"Still missing: {missing}.",
        ]
        if validation:
            parts.append("validate_project result:\n" + validation[:1800])
        if run:
            parts.append("run_project result:\n" + run[:1800])
        if extra:
            parts.append(extra)
        parts.append(
            "Use tools now: read the failing files, write/edit real code, call "
            "validate_project, fix every error, call run_project, and only then finish. "
            "You are responsible for the whole result; keep going until it works."
        )
        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Loop protection
    # ------------------------------------------------------------------
    def _track_tool_call(self, name: str, output: str) -> None:
        """Remember identical tool results to detect endless repetition."""
        signature = (name, output[:400])
        if getattr(self, "_last_tool_signature", None) == signature:
            self._repeat_count = getattr(self, "_repeat_count", 0) + 1
        else:
            self._last_tool_signature = signature
            self._repeat_count = 0

    def _stuck_after_repeats(self, allowed: int = 6) -> bool:
        """True when the same tool call produced the same result too many times."""
        return getattr(self, "_repeat_count", 0) >= allowed

    # ------------------------------------------------------------------
    # Context and progress guards
    # ------------------------------------------------------------------
    def _tool_message(self, call: ToolCall, output: str) -> dict[str, Any]:
        return {
            "role": "tool",
            "tool_call_id": call.id,
            "name": call.name,
            "content": _shorten_tool_output(output),
        }

    def _remember_evidence(self, name: str, output: str) -> None:
        """Track which files the model has actually looked at.

        Exploration is progress even before the first edit, so it must reset
        the no-progress counter; otherwise a careful agent would be stopped
        while still reading a large project.
        """
        if name not in {"read_file", "list_files", "search_text", "inspect_image"}:
            return
        try:
            parsed = json.loads(output)
        except (TypeError, ValueError):
            return
        if not isinstance(parsed, dict):
            return
        path = parsed.get("path")
        if isinstance(path, str) and path:
            key = path
            if name == "read_file":
                # Reading different ranges of the same file is still progress.
                key = f"{path}:{parsed.get('start_line')}-{parsed.get('end_line')}"
            elif name == "search_text":
                key = f"search:{parsed.get('query') or ''}:{path}"
            self._evidence_paths.add(key)
        for match in parsed.get("matches") or []:
            if isinstance(match, dict) and isinstance(match.get("path"), str):
                self._evidence_paths.add(str(match["path"]))

    def _files_signature(self) -> tuple:
        """Cheap fingerprint of the changed files' actual contents."""
        rows: list[tuple[str, int, str]] = []
        for item in self.tools.changed_files[:12]:
            path = str(item.get("path") or "")
            if not path:
                continue
            try:
                data = (self.project.root / path).read_bytes()[:200_000]
            except OSError:
                data = b""
            rows.append(
                (path, len(data), hashlib.blake2b(data, digest_size=8).hexdigest())
            )
        return tuple(rows)

    def _progress_signature(self) -> tuple:
        readiness = self.tools.readiness()
        try:
            state = read_state(self.project.root)
            done = sum(
                1
                for task in state.get("tasks", [])
                if str(task.get("status") or "") == "done"
            )
        except Exception:
            done = 0
        return (
            self._files_signature(),
            bool(readiness.get("validation_passed")),
            bool(readiness.get("run_passed")),
            done,
            len(self._evidence_paths),
        )

    def _stop_incomplete(self, reason: str) -> None:
        self.incomplete_reason = reason
        set_status(self.project.root, "idle", reason[:300], event_type="agent")
        self.emit("incomplete", reason)

    def _track_stall(self) -> bool:
        """Stop a run that keeps spending tokens without changing anything.

        Returns ``True`` when the caller must end the loop. The first time the
        threshold is reached the model gets one explicit recovery prompt; only
        a second full window without progress ends the run honestly.
        """
        if self._stall_limit <= 0:
            return False
        signature = self._progress_signature()
        if signature == self._stall_signature:
            self._stall_counter += 1
        else:
            self._stall_signature = signature
            self._stall_counter = 0
            self._stall_warned = False
        if self._stall_counter < self._stall_limit:
            return False
        readiness = self.tools.readiness()
        if readiness.get("ready"):
            # Everything the engine can verify already passes. The agent may
            # still be polishing, so never end with a false "not completed";
            # ask it once to finish instead.
            if not self._stall_warned:
                self._stall_warned = True
                self._stall_counter = 0
                self.emit(
                    "status",
                    _tr(
                        "The project already passes the checks — asking the agent to finish…",
                        "Проект уже проходит проверки — прошу агента завершить…",
                    ),
                )
                self.messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Validation and the smoke run already pass. Do not keep "
                            "polishing indefinitely: call finish now with a short factual "
                            "report, or state the one concrete thing that is still missing."
                        ),
                    }
                )
            return False
        if not self._stall_warned:
            self._stall_warned = True
            self._stall_counter = 0
            self.emit(
                "status",
                _tr(
                    "No progress for {count} steps — asking the agent to change its approach…",
                    "Нет прогресса {count} шагов — прошу агента сменить подход…",
                    count=self._stall_limit,
                ),
            )
            # AI-facing material stays English-only.
            self.messages.append(
                {
                    "role": "user",
                    "content": (
                        "NO PROGRESS DETECTED. Your last steps did not change any file, "
                        "did not pass validation or a run, and did not inspect a new file. "
                        "Stop repeating the current action. Re-read the exact error, then "
                        "either edit a real file with write_file/edit_file or, if the task "
                        "is informational, answer it directly. Do not call the same tool "
                        "with the same arguments again."
                    ),
                }
            )
            return False
        missing = "; ".join(readiness.get("missing") or [])
        reason = _tr(
            "The agent spent {count} steps in a row without progress and was stopped. "
            "Still missing: {missing}. Try another model or make the task more specific.",
            "Агент потратил {count} шагов подряд без прогресса и был остановлен. "
            "Не выполнено: {missing}. Попробуйте другую модель или уточните задачу.",
            count=self._stall_limit,
            missing=missing
            or _tr(
                "the project still does not pass validation and a smoke run",
                "проект всё ещё не проходит проверку и пробный запуск",
            ),
        )
        self._stop_incomplete(reason)
        return True

    # ------------------------------------------------------------------
    # Durable chat history
    # ------------------------------------------------------------------
    def _seed_chat_history(self) -> None:
        """Prepend the saved conversation from previous sessions."""
        try:
            from ..core.chatlog import recent_messages

            history = recent_messages(self.project.root, limit=20, chat_id=self.chat_id)
        except Exception:
            return
        if not history:
            return
        seed: list[dict[str, Any]] = []
        for item in history:
            if item.get("hidden") and not self.analysis:
                # Hidden service prompts are context for the review run itself,
                # not for the user's follow-up tasks in the same chat.
                continue
            role = str(item.get("role") or "user")
            if role == "system":
                # Status notices ("run stopped", "snapshot failed") are for the
                # user's eyes, not context for the next task.
                continue
            content = str(item.get("text") or "").strip()
            if not content:
                continue
            seed.append(
                {
                    "role": "assistant" if role in {"assistant", "error"} else "user",
                    "content": content,
                }
            )
        if not seed:
            return
        # Keep the real system prompt first; the fresh user message stays last.
        # Sent to the model: AI-facing material stays English-only.
        history_note = {
            "role": "user",
            "content": (
                "Previous sessions of this project (context only, do not reply to it):\n"
                + "\n".join(
                    f"{'User' if m['role'] == 'user' else 'Agent'}: {m['content'][:600]}"
                    for m in seed
                )
            ),
        }
        # messages[0] is the system prompt; insert the history before the new message.
        insert_at = 1 if self.messages and self.messages[0].get("role") == "system" else 0
        self.messages.insert(insert_at, history_note)

    def _persist_chat(self, user_message: str | None) -> None:
        """Save this session's user message and the agent's answer."""
        if not self.persist_messages:
            return
        try:
            from ..core.chatlog import append_message

            if user_message and user_message.strip():
                append_message(
                    self.project.root,
                    "user",
                    user_message,
                    chat_id=self.chat_id,
                    hidden=self.hidden_message,
                )
            final = (self.final_text or self.incomplete_reason or "").strip()
            if final:
                append_message(self.project.root, "assistant", final, chat_id=self.chat_id)
        except Exception:
            pass


    # ------------------------------------------------------------------
    def _snapshot_label(self, user_message: str | None) -> str:
        text = " ".join(str(user_message or self.project.goal or "").split())
        if not text:
            return _tr("Before the AI agent run", "Перед запуском ИИ-агента")
        return text[:110]

    def _create_snapshot(self, user_message: str | None) -> None:
        """Keep the exact state the agent is about to change."""
        try:
            self.snapshot = create_snapshot(
                self.project,
                label=self._snapshot_label(user_message),
                reason="agent",
            )
            self.emit(
                "snapshot",
                _tr("Project snapshot created", "Создан снимок проекта"),
                snapshot=self.snapshot,
            )
        except Exception as exc:
            self.snapshot = None
            self.emit(
                "snapshot_error",
                _tr("Could not create the project snapshot: {error}", "Не удалось создать снимок проекта: {error}", error=exc),
            )

    def _sync_history(self) -> None:
        """Attach the changed-file audit trail to the pre-run snapshot."""
        self.changes = self.tools.changed_files
        if self.cancel.is_set():
            outcome = "cancelled"
        elif self.last_error:
            outcome = "error"
        elif self.finished:
            outcome = "done"
        elif self.incomplete_reason:
            outcome = "incomplete"
        else:
            outcome = "stopped"
        self.outcome = outcome
        if self.snapshot:
            try:
                updated = update_snapshot(
                    self.project,
                    str(self.snapshot.get("id")),
                    changed_files=self.changes,
                    outcome=outcome,
                    final_text=(self.final_text or "")[:4000],
                )
                if updated is not None:
                    self.snapshot = updated
            except Exception:
                pass
        if self.changes:
            labels = {
                "create": _tr("created", "создан"),
                "edit": _tr("modified", "изменён"),
                "delete": _tr("deleted", "удалён"),
                "generate": _tr("generated", "сгенерирован"),
            }
            fallback_label = _tr("modified", "изменён")
            preview = ", ".join(
                f"{item.get('path')} ({labels.get(str(item.get('action')), fallback_label)})"
                for item in self.changes[:6]
            )
            try:
                record_event(
                    self.project.root,
                    "changes",
                    _tr("The agent changed {count} files — {preview}", "Агент изменил файлов: {count} — {preview}", count=len(self.changes), preview=preview),
                    {"files": self.changes, "outcome": outcome},
                )
            except Exception:
                pass
        self.emit(
            "changes",
            _tr("Files changed: {count}", "Изменено файлов: {count}", count=len(self.changes)) if self.changes else _tr("No project files changed", "Файлы проекта не изменились"),
            files=self.changes,
            snapshot=self.snapshot,
            outcome=outcome,
        )

    # ------------------------------------------------------------------
    def run(self, user_message: str | None = None) -> str:
        self.finished = False
        self.final_text = ""
        self.last_error = ""
        self.incomplete_reason = ""
        self.snapshot = None
        self.changes = []
        self.outcome = ""
        self._nudges = 0
        self._install_nudged = False
        self._degenerate_repeats = 0
        self._truncated_repeats = 0
        self._task_message = None
        self._evidence_paths = set()
        self._stall_signature = None
        self._stall_counter = 0
        self._stall_warned = False
        self._summary = ""
        self._summary_message = None
        self._pending_dropped = []
        self._compaction_failures = 0
        self._chars_per_token = 3.6
        self.supervisor_enabled = self._supervisor_setting()
        self._supervisor_signature = None
        self._supervisor_repeats = 0
        self._supervisor_runs = 0
        self._supervisor_last_missing = []
        system_prompt = build_agent_system_prompt(self.project)
        if self.extra_system_prompt:
            system_prompt += "\n\n" + self.extra_system_prompt
        if self.analysis:
            system_prompt += (
                "\n\nANALYSIS MODE — READ ONLY\n"
                "This run must not change project files or progress. Use only list_files, "
                "read_file, search_text, validate_project, inspect_image and get_progress. "
                "Never call write_file, edit_file, delete_path, run_command, run_project, "
                "set_plan, update_task, report_progress or finish. When you have enough "
                "information, reply with the numbered improvement list and ask the user "
                "which items to implement."
            )
        self.messages = [{"role": "system", "content": system_prompt}]
        task_text = user_message or build_initial_user_message(self.project)
        # Tools and skills are English-only, but the agent must talk to the
        # user in the language of exactly this task message. Hidden review
        # tasks use the UI language explicitly because their prompt is English.
        # The agent follows the interface language chosen in settings, not the
        # language of the task text. A user with a Russian UI may paste an
        # English prompt and still expects Russian thinking, plans and replies.
        note = i18n.language_note(self.reply_language or i18n.current_language())
        self.messages.append(
            {
                "role": "user",
                "content": f"{note}\n\n{task_text}",
            }
        )
        # The original task survives every history trim. Without this anchor a
        # long tool-calling run eventually forgot what it was doing.
        self._task_message = self.messages[-1]
        # Every run is reversible: the snapshot is taken before the first tool
        # call and its metadata is extended with the files that changed. The
        # read-only improvement review changes nothing, so it needs no snapshot.
        if not self.analysis and self.create_snapshot:
            self._create_snapshot(user_message)
        # 0 = unlimited: the agent works until the task is really done. The
        # no-progress guard still stops a run that keeps spending tokens
        # without changing anything.
        agent_settings = self.settings.data.get("agent", {}) or {}
        try:
            max_steps = int(agent_settings.get("max_steps") or 0)
        except (TypeError, ValueError):
            max_steps = 0
        try:
            raw_stall = agent_settings.get("stall_steps", 0)
            stall_value = int(0 if raw_stall is None else raw_stall)
            # 8 was the old default that caused false "no progress" stops.
            if stall_value == 8:
                stall_value = 0
            self._stall_limit = max(0, min(50, stall_value))
        except (TypeError, ValueError):
            self._stall_limit = 0
        try:
            self._context_chars = max(
                20_000, int(agent_settings.get("context_chars", 120_000) or 120_000)
            )
        except (TypeError, ValueError):
            self._context_chars = 120_000
        self._compaction_enabled = bool(agent_settings.get("compaction", True))
        try:
            configured_tokens = int(agent_settings.get("context_tokens") or 0)
            if configured_tokens <= 0:
                configured_tokens = min(48_000, int(self._context_window * 0.6))
            self._context_tokens = max(
                2_000, min(int(self._context_window * 0.85), configured_tokens)
            )
        except (TypeError, ValueError):
            self._context_tokens = max(
                2_000, min(48_000, int(self._context_window * 0.6))
            )
        temperature = float(agent_settings.get("temperature", 0.3))
        # Restore the conversation from previous sessions so the agent
        # remembers what the user already asked and what was answered.
        if self.seed_history:
            self._seed_chat_history()
        set_status(self.project.root, "running", _tr("The agent is studying the project…", "Агент изучает проект…"), event_type="agent")
        record_event(self.project.root, "agent", _tr("The built-in agent started working.", "Встроенный агент начал работу."))
        self.emit("status", _tr("The agent is studying the project…", "Агент изучает проект…"))

        try:
            step = 0
            while True:
                step += 1
                self._check_cancel()
                if max_steps and step > max_steps:
                    self._stop_incomplete(
                        _tr(
                            "The agent reached the step limit ({max}) and stopped. "
                            "The result is not verified — continue the task or raise the limit.",
                            "Агент достиг лимита шагов ({max}) и остановился. "
                            "Результат не проверен — продолжите задачу или увеличьте лимит.",
                            max=max_steps,
                        )
                    )
                    break
                if step > 1 and self._track_stall():
                    break
                limit_label = _tr(" of {max}", " из {max}", max=max_steps) if max_steps else ""
                self.emit("step", _tr("Step {step}", "Шаг {step}", step=step) + limit_label, step=step, max_steps=max_steps)
                self._trim_history()
                try:
                    result = self._call_model(
                        self.messages,
                        self.tool_schemas,
                        temperature=temperature,
                    )
                except AIError as exc:
                    # Retry once without tools: some free endpoints reject the
                    # tools field but still answer, and the fallback JSON protocol
                    # in the system prompt can keep the agent productive.
                    if step == 1 and exc.status in {400, 404, 422}:
                        self.emit("status", _tr("The provider rejected the tools — trying the text mode…", "Провайдер не принял инструменты — пробую текстовый режим…"))
                        result = self._call_model(self.messages, None, temperature=temperature)
                    else:
                        raise

                if result.finish_reason in {"length", "max_tokens"}:
                    self._truncated_repeats += 1
                    if self._truncated_repeats >= 2:
                        self._stop_incomplete(
                            _tr(
                                "The model's reply was cut off by the output limit twice. "
                                "It cannot write the file in one piece — try another model or ask for a smaller change.",
                                "Ответ модели дважды обрезался лимитом вывода. "
                                "Она не может записать файл целиком — смените модель или попросите меньшее изменение.",
                            )
                        )
                        break
                    self.emit(
                        "status",
                        _tr(
                            "The reply was cut off by the output limit — asking for a smaller step…",
                            "Ответ обрезан лимитом вывода — прошу сделать шаг меньше…",
                        ),
                    )
                    self.messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Your previous reply was cut off by the output limit, so it was "
                                "discarded. Do not repeat it. Make a smaller step: write one file "
                                "at a time, use edit_file for targeted changes, and never put a "
                                "whole large file into a single tool call."
                            ),
                        }
                    )
                    continue
                self._truncated_repeats = 0

                calls = list(result.tool_calls)
                if not calls:
                    fallback = _parse_fallback_tool(result.content)
                    if fallback is not None:
                        name, arguments = fallback
                        if not self.analysis or name in ANALYSIS_TOOL_NAMES:
                            calls = [
                                ToolCall(
                                    id=f"fallback_{step}",
                                    name=name,
                                    arguments=arguments,
                                    raw_arguments=json.dumps(arguments, ensure_ascii=False),
                                )
                            ]
                            result.tool_calls = calls

                degenerate = bool(result.content) and _looks_degenerate(result.content)
                if degenerate and not calls:
                    self._degenerate_repeats += 1
                    if self._degenerate_repeats >= 2:
                        self._stop_incomplete(
                            _tr(
                                "The model kept returning a repetitive fragment instead of doing the work. Stop the run, switch to another model and try again.",
                                "Модель повторяла один и тот же фрагмент вместо работы. Остановите запуск, смените модель и попробуйте снова.",
                            )
                        )
                        break
                    self.emit(
                        "status",
                        _tr(
                            "The model returned a repetitive fragment — asking it to continue…",
                            "Модель вернула повторяющийся фрагмент — прошу продолжить…",
                        ),
                    )
                    # Discard the garbage instead of feeding it back into the
                    # next request, and make the retry more deterministic.
                    temperature = max(0.05, min(temperature, 0.45) - 0.15)
                    self.messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Your previous reply was a repetitive loop and was discarded. "
                                "Do not repeat words or lines. Continue the task now with one "
                                "concrete tool call."
                            ),
                        }
                    )
                    continue
                self._degenerate_repeats = 0
                if result.content and not degenerate:
                    self.emit("assistant", result.content)
                message = _assistant_message(result)
                if degenerate:
                    # Keep useful tool calls but never store the loop in history.
                    message["content"] = ""
                self.messages.append(message)

                if not calls:
                    if self.analysis:
                        message = (result.content or "").strip()
                        if message:
                            self.final_text = message
                            self.finished = True
                            break
                        # A review model occasionally returns an empty turn
                        # after reading files; ask once for the suggestions.
                        if self._nudges < 2:
                            self._nudges += 1
                            self.emit(
                                "status",
                                _tr("Preparing improvement suggestions…", "Готовлю предложения по улучшению…"),
                            )
                            self.messages.append(
                                {
                                    "role": "user",
                                    "content": "Return the final numbered improvement list now.",
                                }
                            )
                            continue
                        self.incomplete_reason = _tr(
                            "The agent could not prepare improvement suggestions. Try again.",
                            "Агент не смог подготовить предложения по улучшению. Попробуйте ещё раз.",
                        )
                        break
                    if not self.require_ready:
                        self.final_text = result.content.strip() or _tr(
                            "The work item is complete.",
                            "Задача специалиста выполнена.",
                        )
                        self.finished = True
                        break
                    readiness = self.tools.readiness()
                    answer = (result.content or "").strip()
                    # Not every task changes files: a question about the
                    # project is complete when answered. The auditor checks the
                    # answer against the request, so a lazy "done" without any
                    # work is still rejected and sent back as a recovery task.
                    if (
                        answer
                        and not readiness["ready"]
                        and int(readiness.get("files_changed") or 0) == 0
                        and self.supervisor_enabled
                    ):
                        complete, feedback, _stalled = self._supervise_completion(
                            task_text, answer
                        )
                        if complete:
                            self.final_text = answer
                            self.finished = True
                            set_status(
                                self.project.root,
                                "idle",
                                _tr("The answer is ready.", "Ответ готов."),
                                event_type="agent",
                            )
                            break
                        self.messages.append({"role": "user", "content": feedback})
                        continue
                    if readiness["ready"]:
                        message = result.content.strip() or _tr("Done.", "Готово.")
                        complete, feedback, stalled = self._supervise_completion(
                            task_text, message
                        )
                        if not complete:
                            if stalled:
                                feedback += (
                                    "\n\nAUTONOMOUS RECOVERY: the auditor repeated the same "
                                    "verdict without progress. Change the approach, read the "
                                    "relevant files again, run validate_project and implement "
                                    "the missing items with real edits."
                                )
                            self.messages.append({"role": "user", "content": feedback})
                            continue
                        # Finalize the shared progress state even when the model
                        # ends with plain text instead of calling finish.
                        self.tools.tool_finish(message)
                        self.final_text = message
                        self.finished = True
                        break
                    # A model that stops calling tools before doing any work is
                    # the classic "installed pip and declared victory" failure.
                    # Keep the agent in control: verify automatically and send
                    # the concrete errors back instead of ending the run.
                    self._nudges += 1
                    self.emit(
                        "status",
                        _tr(
                            "The work is not finished — checking the project and continuing…",
                            "Работа не завершена — проверяю проект и продолжаю…",
                        ),
                    )
                    validation, run_result = self._auto_verify()
                    readiness = self.tools.readiness()
                    self.messages.append(
                        {
                            "role": "user",
                            "content": self._recovery_prompt(
                                readiness, validation, run_result
                            ),
                        }
                    )
                    continue

                touched_files = False
                installed_package = False
                for call in calls:
                    self._check_cancel()
                    self.emit("tool_start", call.name, tool=call.name, arguments=call.arguments)
                    set_status(
                        self.project.root,
                        "running",
                        _tr("Tool: {name}", "Инструмент: {name}", name=call.name),
                        event_type="tool",
                    )
                    if call.arguments.get("_parse_error"):
                        # A cut-off or malformed JSON argument used to reach the
                        # tool as stray keyword arguments and fail with a
                        # meaningless TypeError. Tell the model exactly what to
                        # do instead of letting it retry the same huge call.
                        output = json.dumps(
                            {
                                "ok": False,
                                "error": (
                                    "Tool arguments were not valid JSON. The reply was probably "
                                    "cut off by the output limit. Retry with a smaller, complete "
                                    "call: one file at a time and prefer edit_file."
                                ),
                            },
                            ensure_ascii=False,
                        )
                        self.messages.append(self._tool_message(call, output))
                        self.emit(
                            "tool_result",
                            call.name,
                            tool=call.name,
                            success=False,
                            result=output[:5000],
                        )
                        continue
                    if call.name not in self._allowed_tool_names:
                        available = ", ".join(sorted(self._allowed_tool_names))
                        output = json.dumps(
                            {
                                "ok": False,
                                "error": (
                                    f"Tool '{call.name}' is not available in this role. "
                                    f"Use only: {available}. The lead agent owns global "
                                    "plan/progress, validation and finish."
                                ),
                            },
                            ensure_ascii=False,
                        )
                        self.messages.append(self._tool_message(call, output))
                        self.emit(
                            "tool_result",
                            call.name,
                            tool=call.name,
                            success=False,
                            result=output[:5000],
                        )
                        continue
                    if self.analysis and call.name not in ANALYSIS_TOOL_NAMES:
                        output = json.dumps(
                            {
                                "ok": False,
                                "error": "Read-only review mode: this tool is unavailable.",
                            },
                            ensure_ascii=False,
                        )
                    elif (
                        call.name == "finish"
                        and not self.analysis
                        and self.tools.readiness().get("ready")
                    ):
                        # Audit first: executing finish would already mark the
                        # project as done, which must not happen for a rejected
                        # completion.
                        message = call.arguments.get("message") or _tr("Project finished.", "Проект готов.")
                        complete, feedback, stalled = self._supervise_completion(
                            task_text, message
                        )
                        if complete:
                            output = self.tools.call(call.name, call.arguments)
                        else:
                            output = json.dumps(
                                {
                                    "ok": False,
                                    "error": "Independent completion check: the task is not complete yet.",
                                    "missing": list(self._supervisor_last_missing),
                                },
                                ensure_ascii=False,
                            )
                            self.messages.append(self._tool_message(call, output))
                            self.emit(
                                "tool_result",
                                call.name,
                                tool=call.name,
                                success=False,
                                result=output[:5000],
                            )
                            if stalled:
                                feedback += (
                                    "\n\nAUTONOMOUS RECOVERY: the auditor repeated the same "
                                    "verdict without progress. Change the approach, inspect "
                                    "the project with tools and implement the missing items."
                                )
                            self.messages.append({"role": "user", "content": feedback})
                            break
                    else:
                        output = self.tools.call(call.name, call.arguments)
                    # Loop protection: the same tool with the same arguments
                    # over and over means the model is stuck.
                    self._track_tool_call(call.name, output)
                    if self._stuck_after_repeats():
                        self.messages.append(self._tool_message(call, output))
                        self.messages.append(
                            {
                                "role": "user",
                                "content": self._recovery_prompt(
                                    self.tools.readiness(),
                                    extra=(
                                        f"You repeated {call.name} with the same result several "
                                        "times. Stop repeating it: inspect the error, choose a "
                                        "different tool or edit the code instead."
                                    ),
                                ),
                            }
                        )
                        self.emit(
                            "tool_result",
                            call.name,
                            tool=call.name,
                            success=True,
                            result=output[:5000],
                        )
                        self.emit(
                            "status",
                            _tr(
                                "The agent repeated an action — switching to a recovery plan…",
                                "Агент повторил действие — переключаюсь на план восстановления…",
                            ),
                        )
                        self._reset_loop_tracking()
                        break
                    self.messages.append(self._tool_message(call, output))
                    self._remember_evidence(call.name, output)
                    try:
                        parsed = json.loads(output)
                    except ValueError:
                        parsed = {"raw": output[:500]}
                    if call.name in {
                        "write_file",
                        "edit_file",
                        "delete_path",
                        "generate_sprite",
                        "draw_sprite",
                        "generate_background",
                    } and parsed.get("ok", True):
                        touched_files = True
                    if parsed.get("package_install"):
                        installed_package = True
                    self.emit(
                        "tool_result",
                        call.name,
                        tool=call.name,
                        success=bool(parsed.get("ok", True)),
                        result=output[:5000],
                    )
                    if call.name == "finish" and parsed.get("ok"):
                        self.finished = True
                        self.final_text = call.arguments.get("message") or _tr("Project finished.", "Проект готов.")
                        break
                if self.finished:
                    break
                if self.incomplete_reason:
                    break
                if (
                    installed_package
                    and not touched_files
                    and self.tools.files_changed == 0
                    and not self._install_nudged
                ):
                    self._install_nudged = True
                    self.emit("status", _tr("Installing a library is not a result. Asking the agent to continue working…", "Установка библиотеки — не результат. Прошу агента продолжить работу…"))
                    self.messages.append(
                        {
                            "role": "user",
                            "content": (
                                # Sent to the model: AI-facing material is English-only.
                                "Installing a library or a package is not a completed task. "
                                "Now write or edit the project files, implement the task, then "
                                "call validate_project and run_project. finish is forbidden before that."
                            ),
                        }
                    )

            if not self.finished and not self.cancel.is_set() and self.analysis:
                if not self.incomplete_reason:
                    self.incomplete_reason = _tr(
                        "The project review stopped early. Try again.",
                        "Проверка проекта остановилась раньше времени. Попробуйте ещё раз.",
                    )
                set_status(
                    self.project.root,
                    "idle",
                    self.incomplete_reason[:300],
                    event_type="agent",
                )
                self.emit("incomplete", self.incomplete_reason)
            if self.finished:
                if self.analysis:
                    set_status(
                        self.project.root,
                        "idle",
                        _tr("The project review is ready.", "Проверка проекта готова."),
                        event_type="agent",
                    )
                self.emit("done", self.final_text or _tr("Done.", "Готово."))
            return self.final_text
        except AgentCancelled as exc:
            self.emit("cancelled", str(exc))
            set_status(self.project.root, "idle", _tr("The work was stopped by the user.", "Работа остановлена пользователем."), event_type="agent")
            return ""
        except AIError as exc:
            self.last_error = exc.message
            self.emit(
                "error",
                exc.message,
                detail=exc.detail,
                status=exc.status,
                error_kind=classify_agent_error(exc.status, getattr(exc, "kind", "")),
            )
            set_status(self.project.root, "error", exc.message[:300], event_type="error")
            return ""
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            self.emit("error", self.last_error, error_kind="other")
            set_status(self.project.root, "error", self.last_error[:300], event_type="error")
            return ""
        finally:
            self._persist_chat(user_message)
            if not self.analysis and self.sync_history:
                self._sync_history()
            if self.cancel.is_set():
                set_status(self.project.root, "idle", _tr("The work was stopped by the user.", "Работа остановлена пользователем."), event_type="agent")


def run_agent_in_thread(
    project,
    settings: Settings | None = None,
    *,
    message: str | None = None,
    on_event: EventCallback | None = None,
    cancel: CancelFlag | None = None,
) -> tuple[Agent, threading.Thread]:
    """Convenience for GUI workers: start the agent on a daemon thread."""
    agent = Agent(project, settings, on_event=on_event, cancel=cancel)
    thread = threading.Thread(target=agent.run, args=(message,), daemon=True, name="ReasonableAgent")
    thread.start()
    return agent, thread
