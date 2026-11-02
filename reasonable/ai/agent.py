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
from reasonable.core.history import create_snapshot, update_snapshot
from reasonable.core.i18n import tr as _tr
from reasonable.core.progress import record_event, set_progress, set_status
from reasonable.core.settings import Settings

from .client import AIClient, AIError, ChatResult, ToolCall
from .prompts import build_agent_system_prompt, build_initial_user_message
from .tools import TOOL_SCHEMAS, AgentTools


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
    ) -> None:
        self.project = project
        self.settings = settings or Settings()
        self.on_event = on_event
        self.cancel = cancel or threading.Event()
        self.config = provider_config or self.settings.get_provider_config()
        self.client = AIClient(self.config, timeout=180, retries=2)
        self.image_config = image_config or self.settings.image_config()
        self.tools = AgentTools(project, image_config=self.image_config)
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

    def _continuation_nudge(self, readiness: dict[str, Any]) -> str:
        # Sent to the model: AI-facing material stays English-only.
        missing = "; ".join(readiness.get("missing") or [])
        return (
            "The work is not finished yet. Do not stop and do not write a final report. "
            f"Not done: {missing}. "
            "Keep editing the project files, then call validate_project, fix "
            "all errors and call run_project. Only after a successful launch call finish. "
            "Installing a library with pip or reading files is not a result."
        )

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

            history = recent_messages(self.project.root, limit=20)
        except Exception:
            return
        if not history:
            return
        seed: list[dict[str, Any]] = []
        for item in history:
            content = str(item.get("text") or "").strip()
            if not content:
                continue
            role = "assistant" if item.get("role") == "assistant" else "user"
            seed.append({"role": role, "content": content})
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
        try:
            from ..core.chatlog import append_message

            if user_message and user_message.strip():
                append_message(self.project.root, "user", user_message)
            final = (self.final_text or self.incomplete_reason or "").strip()
            if final:
                append_message(self.project.root, "assistant", final)
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
        self.messages = [{"role": "system", "content": build_agent_system_prompt(self.project)}]
        task_text = user_message or build_initial_user_message(self.project)
        # Tools and skills are English-only, but the agent must talk to the
        # user in the language of exactly this task message.
        note = i18n.task_language_note(task_text)
        self.messages.append(
            {
                "role": "user",
                "content": f"{note}\n\n{task_text}",
            }
        )
        # Every run is reversible: the snapshot is taken before the first tool
        # call and its metadata is extended with the files that changed.
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
                    result = self.client.chat(
                        self.messages,
                        TOOL_SCHEMAS,
                        temperature=temperature,
                    )
                except AIError as exc:
                    # Retry once without tools: some free endpoints reject the
                    # tools field but still answer, and the fallback JSON protocol
                    # in the system prompt can keep the agent productive.
                    if step == 1 and exc.status in {400, 404, 422}:
                        self.emit("status", _tr("The provider rejected the tools — trying the text mode…", "Провайдер не принял инструменты — пробую текстовый режим…"))
                        result = self.client.chat(self.messages, None, temperature=temperature)
                    else:
                        raise

                if result.usage:
                    self.emit("usage", usage=result.usage)

                calls = list(result.tool_calls)
                if not calls:
                    fallback = _parse_fallback_tool(result.content)
                    if fallback is not None:
                        name, arguments = fallback
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
                    readiness = self.tools.readiness()
                    if readiness["ready"]:
                        message = result.content.strip() or _tr("Done.", "Готово.")
                        # Finalize the shared progress state even when the model
                        # ends with plain text instead of calling finish.
                        self.tools.tool_finish(message)
                        self.final_text = message
                        self.finished = True
                        break
                    # A model that stops calling tools before doing any work is
                    # the classic "installed pip and declared victory" failure.
                    # Nudge it back to real edits instead of accepting the text.
                    if self._nudges < 3:
                        self._nudges += 1
                        self.emit("status", _tr("The work is not finished — continuing and asking the agent to complete it…", "Работа не завершена — продолжаю и прошу агента доделать…"))
                        self.messages.append({"role": "user", "content": self._continuation_nudge(readiness)})
                        continue
                    self.incomplete_reason = _tr(
                        "The agent stopped without changing the project or passing validation. "
                        "Clarify the task or run it again.",
                        "Агент остановился, не изменив проект и не пройдя проверку. "
                        "Уточните задачу или запустите его снова.",
                    )
                    break

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
                    output = self.tools.call(call.name, call.arguments)
                    # Loop protection: the same tool with the same arguments
                    # over and over means the model is stuck.
                    self._track_tool_call(call.name, output)
                    if self._stuck_after_repeats():
                        self.incomplete_reason = _tr(
                            "The agent repeated the same action without any result, so it was stopped. "
                            "Describe the task differently or continue from this point.",
                            "Агент повторял одно и то же действие без результата, поэтому был остановлен. "
                            "Опишите задачу по-другому или продолжите с этого места.",
                        )
                        set_status(
                            self.project.root,
                            "idle",
                            self.incomplete_reason[:300],
                            event_type="agent",
                        )
                        self.emit("incomplete", self.incomplete_reason)
                        return self.final_text
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

            if not self.finished and not self.cancel.is_set():
                readiness = self.tools.readiness()
                if not self.incomplete_reason:
                    if readiness["ready"]:
                        self.incomplete_reason = _tr(
                            "The agent stopped, but the project already passes validation. "
                            "You can run the agent again for polishing.",
                            "Агент остановился, но проект уже проходит проверку. "
                            "Можно запустить агента ещё раз для полировки.",
                        )
                    else:
                        self.incomplete_reason = _tr(
                            "The agent stopped early. Not done: ",
                            "Агент остановился раньше времени. Не выполнено: ",
                        ) + "; ".join(readiness["missing"])
                set_status(
                    self.project.root,
                    "idle",
                    self.incomplete_reason[:300],
                    event_type="agent",
                )
                self.emit("incomplete", self.incomplete_reason)
            if self.finished:
                self.emit("done", self.final_text or _tr("Done.", "Готово."))
            return self.final_text
        except AgentCancelled as exc:
            self.emit("cancelled", str(exc))
            set_status(self.project.root, "idle", _tr("The work was stopped by the user.", "Работа остановлена пользователем."), event_type="agent")
            return ""
        except AIError as exc:
            self.last_error = exc.message
            self.emit("error", exc.message, detail=exc.detail)
            set_status(self.project.root, "error", exc.message[:300], event_type="error")
            return ""
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            self.emit("error", self.last_error)
            set_status(self.project.root, "error", self.last_error[:300], event_type="error")
            return ""
        finally:
            self._persist_chat(user_message)
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
