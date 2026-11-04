"""Autonomous agent loop used by the editor.

The agent talks to any OpenAI-compatible or Anthropic model with native tool
calling, executes tools inside the project, and mirrors its state into
``progress/`` so the UI stays alive even if a step takes a while.
"""

from __future__ import annotations

import json
import queue
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
from reasonable.core.progress import record_event, set_progress, set_status
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
        """Normalize OpenAI/Anthropic usage and attach the call duration."""
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

        prompt = number("prompt_tokens", "input_tokens")
        completion = number("completion_tokens", "output_tokens")
        total = number("total_tokens", "total") or prompt + completion
        return {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": total,
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
        # Emit even when the provider omits usage: generation time is still a
        # real cost and belongs in the lifetime counter.
        self.emit("usage", usage=self._usage_payload(result.usage, elapsed))
        return result

    def _trim_history(self) -> None:
        try:
            limit = max(12, int(self.settings.data.get("agent", {}).get("context_messages", 36)))
        except Exception:
            limit = 36
        if len(self.messages) <= limit + 1:
            return
        system = self.messages[0]
        recent = self.messages[-limit:]
        # Anthropic requires a tool_result to follow its tool_use; start at a
        # clean user message so trimming never creates an orphan.
        while recent and recent[0].get("role") in {"tool", "assistant"}:
            recent.pop(0)
        self.messages = [system] + recent

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
        # Every run is reversible: the snapshot is taken before the first tool
        # call and its metadata is extended with the files that changed. The
        # read-only improvement review changes nothing, so it needs no snapshot.
        if not self.analysis and self.create_snapshot:
            self._create_snapshot(user_message)
        # 0 = unlimited: the agent works until the task is really done. The
        # old 60-step cap only produced «Работа не завершена» noise.
        try:
            max_steps = int(self.settings.data.get("agent", {}).get("max_steps") or 0)
        except (TypeError, ValueError):
            max_steps = 0
        temperature = float(self.settings.data.get("agent", {}).get("temperature", 0.65))
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

                if result.content:
                    self.emit("assistant", result.content)
                self.messages.append(_assistant_message(result))

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
                            self.messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": call.id,
                                    "name": call.name,
                                    "content": output,
                                }
                            )
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
                        self.messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call.id,
                                "name": call.name,
                                "content": output,
                            }
                        )
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
                    self.messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "name": call.name,
                            "content": output,
                        }
                    )
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
