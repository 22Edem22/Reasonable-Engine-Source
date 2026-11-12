"""Parallel multi-agent development led by a non-editing master agent.

The master agent reads the project, splits the user's task into independent work
items and delegates them to specialist agents:

* ``code``   — edits a strictly scoped set of project files;
* ``assets`` — writes only the listed files under ``assets/``.

Independent items run in parallel. The master then validates the whole project,
runs a smoke test and performs an independent completion audit. If something is
missing, it creates a focused repair item and repeats. The master itself never
edits files — it plans, dispatches and checks.

Any failure in planning or orchestration safely falls back to the proven
single-agent loop, so the user never loses the ability to finish a task.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable

from reasonable.core import chatlog, i18n
from reasonable.core.history import create_snapshot, update_snapshot
from reasonable.core.i18n import tr as _tr
from reasonable.core.paths import atomic_write_json, now_iso, read_json
from reasonable.core.progress import (
    finish_progress,
    read_state,
    record_event,
    set_plan,
    set_status,
    update_task,
)

from .agent import (
    Agent,
    AgentCancelled,
    AgentEvent,
    SUPERVISOR_PROMPT,
    TokenBudget,
    _extract_json_object,
    _looks_degenerate,
)
from .client import AIClient, AIError, ChatResult
from .diffs import changed_files_payload
from .prompts import build_initial_user_message
from .tools import AgentTools, SITE_TOOL_NAMES, TOOL_SCHEMAS

log = logging.getLogger(__name__)

# Specialists must not run finish/plan/progress/validation themselves: the
# master owns the global state and checks the combined result after the merge.
_SPECIALIST_TOOLS = [
    schema
    for schema in TOOL_SCHEMAS
    if schema.get("name")
    not in {
        "finish",
        "set_plan",
        "update_task",
        "report_progress",
        "validate_project",
        "run_project",
    }
]

PLANNER_PROMPT = """You are the lead architect of a parallel development team.
You never edit files yourself. Split the user's task into independent work items
that specialist agents can execute concurrently without touching the same files.

Return exactly one JSON object:
{
  "summary": "one short sentence",
  "tasks": [
    {"id": "code-1", "role": "code", "title": "short title",
     "files": ["main.py"], "depends_on": [],
     "instructions": "precise implementation brief"},
    {"id": "assets-1", "role": "assets", "title": "short title",
     "files": ["assets/sprites/player.png"], "depends_on": ["code-1"],
     "instructions": "what to draw"}
  ]
}

Rules:
- 2 to {max_tasks} tasks. A small task may use one task; prefer one task when
  the work is a small feature that fits in one coherent change.
- role is only "code" or "assets".
- Code tasks must have disjoint file lists. If two features need the same file,
  merge them into one task.
- depends_on lists task ids that must finish first. Use it only when a task
  truly needs another task's output but writes different files (for example a
  scene or test that uses a class created by an earlier task). The captain
  passes the finished task's report to the waiting specialist.
- Dependencies must form a DAG: no cycles, no self-references, no unknown ids.
- Independent means "can be finished without seeing the other task's output".
  Prefer merging over a dependency when the same code is involved: a test, a
  screen, or a module that imports code created by another task is NOT
  independent. Never split "create the code" and "test/use the code" into
  parallel tasks without a depends_on edge.
- Assets tasks may only target files under assets/.
- Do not create review/validate/run/test/finish tasks — the lead agent does
  that after all specialists finish.
- Each instruction must be complete enough for a specialist that does not see
  the other tasks: what to build, where, and how it connects to the whole.
- The starter example is a base, not the specification. Follow the user task.
- Reply with JSON only, no markdown fences."""

FINAL_PROMPT = """You are the lead agent writing the final report to the user.
Use the supplied work results and verification. Reply in {language}.
Be concise and factual: what was built, where the files are, how to run it, any
honest caveat. Never claim that a missing item was completed."""


@dataclass
class Member:
    """A durable specialist in the captain's team.

    Unlike the old per-task agent, a member keeps its identity, its own model
    session and a compact memory of the work it already did. When another task
    of the same role arrives, the member is woken again with that memory and
    with the reports of the teammates it depended on.
    """

    id: str
    role: str
    name: str
    agent: Agent | None = None
    tasks: list[str] = field(default_factory=list)
    memory: list[str] = field(default_factory=list)
    busy: bool = False
    created_at: float = field(default_factory=time.time)

    def remember(self, text: str, limit: int = 8) -> None:
        value = " ".join(str(text or "").split())
        if not value:
            return
        self.memory.append(value[:1200])
        self.memory = self.memory[-limit:]

    def memory_text(self, limit: int = 3500) -> str:
        text = "\n".join(f"- {item}" for item in self.memory)
        return text[-limit:] if len(text) > limit else text


class Orchestrator:
    """Captain: plans a dependency DAG, dispatches durable specialists, audits."""

    def __init__(
        self,
        project,
        settings=None,
        *,
        message: str | None = None,
        on_event: Callable[[AgentEvent], None] | None = None,
        cancel: threading.Event | None = None,
        chat_id: str | None = None,
        hidden_message: bool = False,
        analysis: bool = False,
        reply_language: str | None = None,
        persist_messages: bool = True,
        confirm_write: Callable[[str, str], bool] | None = None,
    ) -> None:
        from reasonable.core.settings import Settings

        self.project = project
        self.settings = settings or Settings()
        self.message = message
        self.on_event = on_event
        self.cancel = cancel or threading.Event()
        self.confirm_write = confirm_write
        self._write_denied = False
        self.chat_id = chat_id
        self.hidden_message = bool(hidden_message)
        self.analysis = bool(analysis)
        self.reply_language = reply_language
        self.persist_messages = bool(persist_messages)
        agent_settings = self.settings.data.get("agent", {}) or {}
        self.workers = max(2, min(6, int(agent_settings.get("parallel_workers", 3) or 3)))
        self.max_rounds = max(1, min(5, int(agent_settings.get("parallel_rounds", 3) or 3)))
        try:
            self.specialist_timeout_minutes = max(
                0, min(240, int(agent_settings.get("specialist_timeout_minutes", 15) or 0))
            )
        except (TypeError, ValueError):
            self.specialist_timeout_minutes = 15
        try:
            self.specialist_max_steps = max(
                0, min(200, int(agent_settings.get("specialist_max_steps", 60) or 0))
            )
        except (TypeError, ValueError):
            self.specialist_max_steps = 60
        try:
            self.max_run_minutes = max(
                0, min(600, int(agent_settings.get("max_run_minutes", 90) or 0))
            )
        except (TypeError, ValueError):
            self.max_run_minutes = 90
        self._run_deadline = 0.0
        try:
            budget_limit = int(agent_settings.get("run_token_budget", 0) or 0)
        except (TypeError, ValueError):
            budget_limit = 0
        self.budget = TokenBudget(budget_limit)
        self.config = dict(self.settings.get_provider_config())
        if self.chat_id and (
            "opencode.ai" in str(self.config.get("base_url") or "").lower()
            or self.config.get("id") == "opencode"
        ):
            headers = dict(self.config.get("headers") or {})
            headers["x-opencode-session"] = f"reasonable-{self.chat_id}"
            self.config["headers"] = headers
        self.client = AIClient(self.config, timeout=180, retries=2, cancel=self.cancel)
        self.image_config = self.settings.image_config()
        self.finished = False
        self.final_text = ""
        self.last_error = ""
        self.incomplete_reason = ""
        self.snapshot: dict | None = None
        self.changes: list[dict] = []
        self._event_lock = threading.Lock()
        # Team roster. A member is reused only when it is idle, so two parallel
        # tasks never share one Agent instance.
        self._members: list[Member] = []
        self._member_lock = threading.Lock()
        self._member_seq = 0

    # ------------------------------------------------------------------
    def emit(self, kind: str, text: str = "", **data: Any) -> None:
        if self.on_event is None:
            return
        with self._event_lock:
            try:
                self.on_event(AgentEvent(kind, text, data))
            except Exception:
                pass

    def _emit_stream_delta(self, text: str) -> None:
        if text:
            self.emit("delta", text)

    def _confirm_write(self, action: str, path: str) -> bool:
        if self.confirm_write is None:
            return True
        allowed = bool(self.confirm_write(action, path))
        if not allowed:
            self._write_denied = True
        return allowed

    def _call_model(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.2,
    ) -> ChatResult:
        if self.cancel.is_set():
            raise AgentCancelled("The work was stopped by the user.")
        started = time.perf_counter()
        try:
            result = self.client.chat(messages, None, temperature=temperature)
        except Exception:
            self.emit(
                "usage",
                usage=Agent._usage_payload(None, time.perf_counter() - started),
            )
            if self.cancel.is_set():
                raise AgentCancelled("The work was stopped by the user.")
            raise
        usage = Agent._usage_payload(result.usage, time.perf_counter() - started)
        self.budget.add(usage)
        self.emit("usage", usage=usage)
        return result

    # ------------------------------------------------------------------
    def run(self, user_message: str | None = None) -> str:
        if self.cancel.is_set():
            return ""
        task = (user_message or self.message or build_initial_user_message(self.project)).strip()
        self._run_deadline = (
            time.monotonic() + self.max_run_minutes * 60
            if self.max_run_minutes > 0
            else 0.0
        )
        if self.analysis or self.workers <= 1:
            return self._fallback(task)
        if self.persist_messages and task:
            try:
                chatlog.append_message(
                    self.project.root,
                    "user",
                    task,
                    chat_id=self.chat_id,
                    hidden=self.hidden_message,
                )
            except Exception:
                pass
        try:
            self.emit("status", _tr("Master agent: planning the work…", "Главный агент: планирую работу…"))
            resumed = self._load_journal(task)
            if resumed:
                plan = resumed["plan"]
                done = {
                    str(item.get("id")): item
                    for item in resumed.get("results") or []
                    if isinstance(item, dict) and item.get("id")
                }
                self.snapshot = resumed.get("snapshot") or None
                self.emit(
                    "status",
                    _tr(
                        "Master agent: resuming the interrupted run ({done} item(s) already done)…",
                        "Главный агент: продолжаю прерванный запуск (готово пунктов: {done})…",
                        done=len(done),
                    ),
                )
                self._apply_plan(plan)
                for task_id in done:
                    try:
                        update_task(self.project.root, str(task_id), "done")
                    except Exception:
                        pass
                results = self._execute(plan, task, done=done)
            else:
                plan = self._plan(task)
                if plan is None:
                    return self._fallback(task)
                self._start_snapshot(task)
                if self.budget.exceeded:
                    return self._stop_for_budget(task)
                self._apply_plan(plan)
                self._journal_save(task, plan, [])
                results = self._execute(plan, task)
            if self._deadline_exceeded():
                return self._stop_for_time(task, results)
            if self._write_denied:
                final = _tr(
                    "The user did not approve the changes, so the run stopped before modifying files.",
                    "Пользователь не подтвердил изменения, поэтому запуск остановлен до правки файлов.",
                )
                self._collect_changes(results)
                self.final_text = final
                self.incomplete_reason = final
                self.emit("assistant", final)
                set_status(self.project.root, "idle", final[:300], event_type="agent")
                self._finish_snapshot(task, False)
                return final
            verification = self._verify()
            if self.budget.exceeded:
                return self._stop_for_budget(task, results)
            review = self._review(task, plan, results, verification)

            rounds = 0
            while (
                not review.get("complete")
                and rounds < self.max_rounds
                and not self.cancel.is_set()
                and not self.budget.exceeded
                and not self._deadline_exceeded()
            ):
                rounds += 1
                self.emit(
                    "status",
                    _tr(
                        "Master agent: fix round {round}…",
                        "Главный агент: круг исправлений {round}…",
                        round=rounds,
                    ),
                )
                fix = self._fix_task(task, review, results)
                # Send the repair to a member that already worked on the code:
                # it keeps the file context instead of starting from zero.
                fix["_reuse"] = True
                results.append(self._run_specialist(fix, task))
                verification = self._verify()
                review = self._review(task, plan, results, verification)

            complete = bool(review.get("complete")) and bool(verification.get("ok"))
            self._collect_changes(results)
            final = self._final_text(task, plan, results, verification, review, complete)
            self.final_text = final
            self.finished = complete
            if not complete:
                self.incomplete_reason = "; ".join(review.get("missing") or []) or _tr(
                    "The independent check did not confirm completion.",
                    "Независимая проверка не подтвердила выполнение.",
                )
                set_status(self.project.root, "idle", final[:300], event_type="agent")
            else:
                finish_progress(self.project.root, final[:300])
            self.emit("assistant", final)
            if self.persist_messages and final:
                try:
                    chatlog.append_message(
                        self.project.root,
                        "assistant",
                        final,
                        chat_id=self.chat_id,
                    )
                except Exception:
                    pass
            self._finish_snapshot(task, complete)
            return final
        except AgentCancelled:
            return ""
        except AIError as exc:
            self.last_error = exc.message
            self.emit("error", exc.message, error_kind="other")
            set_status(self.project.root, "error", exc.message[:300], event_type="error")
            return ""
        except Exception:
            # A planning/execution failure must never lose the task: continue
            # in the proven single-agent mode on the same project.
            log.exception("Parallel orchestrator failed; falling back to one agent")
            self.emit(
                "status",
                _tr(
                    "The parallel team hit an internal error — continuing in the reliable single-agent mode.",
                    "Параллельная команда столкнулась с внутренней ошибкой — продолжаю в надёжном обычном режиме.",
                ),
            )
            return self._fallback(task)
        finally:
            self._clear_journal()

    # ------------------------------------------------------------------
    def _fallback(self, task: str) -> str:
        self.emit(
            "status",
            _tr(
                "Master agent: switching to the reliable single-agent mode…",
                "Главный агент: перехожу в надёжный обычный режим…",
            ),
        )
        agent = Agent(
            self.project,
            self.settings,
            on_event=self.on_event,
            cancel=self.cancel,
            chat_id=self.chat_id,
            hidden_message=self.hidden_message,
            analysis=self.analysis,
            reply_language=self.reply_language,
            persist_messages=self.persist_messages,
            create_snapshot=self.snapshot is None,
            confirm_write=self.confirm_write,
            expect_writes=not self.analysis,
            max_seconds=self.max_run_minutes * 60,
        )
        text = agent.run(task)
        self.last_error = agent.last_error
        self.incomplete_reason = agent.incomplete_reason
        self.finished = agent.finished
        self.final_text = agent.final_text or text
        return text

    # -- run journal ---------------------------------------------------
    def _journal_path(self):
        return self.project.root / ".reasonable" / "orchestrator_run.json"

    def _journal_save(
        self,
        task: str,
        plan: dict[str, Any],
        results: list[dict[str, Any]],
    ) -> None:
        try:
            payload = {
                "version": 1,
                "task": str(task or "")[:8000],
                "saved_at": now_iso(),
                "plan": plan,
                "results": results,
                "snapshot": self.snapshot,
            }
            path = self._journal_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(path, payload)
        except Exception:
            pass

    def _load_journal(self, task: str):
        path = self._journal_path()
        try:
            if time.time() - path.stat().st_mtime > 86_400:
                return None
        except OSError:
            return None
        data = read_json(path, {})
        if not isinstance(data, dict):
            return None
        try:
            version = int(data.get("version") or 0)
        except (TypeError, ValueError):
            return None
        if version != 1:
            return None
        if str(data.get("task") or "").strip() != str(task or "").strip():
            return None
        plan = data.get("plan")
        if not isinstance(plan, dict) or not isinstance(plan.get("tasks"), list):
            return None
        results = data.get("results")
        if not isinstance(results, list):
            results = []
        return {
            "plan": plan,
            "results": [item for item in results if isinstance(item, dict)],
            "snapshot": data.get("snapshot")
            if isinstance(data.get("snapshot"), dict)
            else None,
        }

    def _clear_journal(self) -> None:
        try:
            self._journal_path().unlink()
        except OSError:
            pass

    def _deadline_exceeded(self) -> bool:
        return bool(self._run_deadline and time.monotonic() > self._run_deadline)

    def _stop_for_time(
        self, task: str, results: list[dict[str, Any]] | None = None
    ) -> str:
        """End a parallel run that exceeded its wall-clock budget."""
        self._collect_changes(results or [])
        final = _tr(
            "The run exceeded its {minutes}-minute limit and stopped before the final check. "
            "Changed files and the snapshot were kept — continue in a new run or raise the limit in settings.",
            "Запуск превысил лимит {minutes} мин и остановился до финальной проверки. "
            "Изменённые файлы и снимок сохранены — продолжите новым запуском или увеличьте лимит в настройках.",
            minutes=self.max_run_minutes,
        )
        self.final_text = final
        self.incomplete_reason = final
        self.finished = False
        self.emit("assistant", final)
        set_status(self.project.root, "idle", final[:300], event_type="agent")
        self._finish_snapshot(task, False)
        return final

    def _stop_for_budget(self, task: str, results: list[dict[str, Any]] | None = None) -> str:
        """End a parallel run honestly when its shared token budget is gone."""
        self._collect_changes(results or [])
        final = _tr(
            "The run used its token budget ({used} of {limit}) and stopped before the final check. "
            "Changed files were kept and a snapshot was created — continue in a new run or raise the budget in settings.",
            "Запуск израсходовал бюджет токенов ({used} из {limit}) и остановился до финальной проверки. "
            "Изменённые файлы сохранены, снимок создан — продолжите новым запуском или увеличьте бюджет в настройках.",
            used=self.budget.used,
            limit=self.budget.limit,
        )
        self.final_text = final
        self.incomplete_reason = final
        self.finished = False
        self.emit("assistant", final)
        set_status(self.project.root, "idle", final[:300], event_type="agent")
        self._finish_snapshot(task, False)
        return final

    # ------------------------------------------------------------------
    def _context(self) -> dict[str, Any]:
        try:
            main_text = self.project.read_text("main.py")[:7000]
        except Exception:
            main_text = ""
        state = read_state(self.project.root)
        scenes: list[dict[str, Any]] = []
        try:
            from reasonable.core.scene import list_scenes, load_scene

            for summary in list_scenes(self.project.root)[:6]:
                scene = load_scene(self.project.root, summary["id"])
                objects = scene.get("objects") or []
                scenes.append(
                    {
                        "id": summary["id"],
                        "title": summary["title"],
                        "size": scene.get("size"),
                        "objects": [
                            {
                                "name": item.get("name"),
                                "kind": item.get("kind"),
                                "role": item.get("role"),
                                "marker": bool(item.get("marker")),
                            }
                            for item in objects[:24]
                            if isinstance(item, dict)
                        ],
                    }
                )
        except Exception:
            pass
        return {
            "project": {
                "name": self.project.name,
                "type": self.project.project_type,
                "goal": self.project.goal,
                "notes": self.project.notes,
                "platform": self.project.platform,
                "ui_levels": self.project.ui_levels,
                "files": self.project.list_files(limit=80),
            },
            "main_py": main_text,
            "plan": state.get("tasks") or [],
            "scenes": scenes,
        }

    def _plan(self, task: str) -> dict[str, Any] | None:
        messages = [
            {
                "role": "system",
                "content": PLANNER_PROMPT.replace("{max_tasks}", str(self.workers + 2)),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "user_task": task,
                        "reply_language": i18n.current_language(),
                        "project_context": self._context(),
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        try:
            result = self._call_model(messages, temperature=0.15)
        except Exception:
            return None
        data = _extract_json_object(result.content)
        if not isinstance(data, dict):
            return None
        tasks = self._normalise_tasks(data.get("tasks"))
        if not tasks:
            return None
        return {"summary": str(data.get("summary") or ""), "tasks": tasks}

    def _normalise_tasks(self, raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list):
            return []
        tasks: list[dict[str, Any]] = []
        used_ids: set[str] = set()
        for index, item in enumerate(raw[: self.workers + 2], start=1):
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "code").lower()
            if role not in {"code", "assets"}:
                continue
            files = []
            for path in item.get("files") or []:
                text = str(path).replace("\\", "/").strip()
                while text.startswith("./"):
                    text = text[2:]
                if text:
                    files.append(text)
            if role == "code":
                files = [path for path in files if not path.startswith("assets/")]
            if not files:
                files = ["assets"] if role == "assets" else ["main.py"]
            if role == "assets":
                files = [path if path.startswith("assets") else f"assets/{path}" for path in files]
            depends_on: list[str] = []
            for dependency in item.get("depends_on") or []:
                text = str(dependency).strip()
                if text and text not in depends_on:
                    depends_on.append(text)
            task_id = str(item.get("id") or f"{role}-{index}")
            base_id = task_id
            suffix = 2
            while task_id in used_ids:
                task_id = f"{base_id}-{suffix}"
                suffix += 1
            used_ids.add(task_id)
            tasks.append(
                {
                    "id": task_id,
                    "role": role,
                    "title": str(item.get("title") or _tr("Work item {index}", "Задача {index}", index=index)),
                    "files": list(dict.fromkeys(files)),
                    "depends_on": depends_on,
                    "instructions": str(item.get("instructions") or item.get("title") or ""),
                }
            )
        tasks = [task for task in tasks if not self._verification_only(task)]
        tasks, dependency_aliases = self._merge_dependencies(tasks)
        tasks, conflict_aliases = self._merge_conflicts(tasks)
        aliases = {**dependency_aliases, **conflict_aliases}
        known = {str(task["id"]) for task in tasks}
        for task in tasks:
            resolved: list[str] = []
            for dependency in task.get("depends_on") or []:
                value = self._resolve_alias(aliases, str(dependency))
                if value in known and value != str(task["id"]) and value not in resolved:
                    resolved.append(value)
            task["depends_on"] = resolved
        return self._break_cycles(tasks)

    @staticmethod
    def _resolve_alias(aliases: dict[str, str], value: str) -> str:
        seen: set[str] = set()
        while value in aliases and value not in seen:
            seen.add(value)
            value = aliases[value]
        return value

    @staticmethod
    def _merge_dependencies(
        tasks: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        """Merge a task into another one when it uses files that task creates.

        File-disjoint work is not necessarily independent: a test module that
        imports the module from the previous task cannot run in parallel with
        it. The planner is told this, but models still split such work, so the
        dependency is detected from the mentioned file names.
        """
        merged = list(tasks)
        aliases: dict[str, str] = {}
        changed = True
        while changed:
            changed = False
            result: list[dict[str, Any]] = []
            for task in merged:
                text = f"{task.get('title') or ''} {task.get('instructions') or ''}".lower()
                target = None
                if task.get("role") == "code":
                    for existing in result:
                        if existing.get("role") != "code":
                            continue
                        for path in existing.get("files") or []:
                            name = str(path).replace("\\", "/").rsplit("/", 1)[-1].lower()
                            if name and name in text:
                                target = existing
                                break
                        if target is not None:
                            break
                if target is None:
                    result.append(task)
                else:
                    aliases[str(task["id"])] = str(target["id"])
                    inherited = [
                        str(dep)
                        for dep in task.get("depends_on") or []
                        if str(dep) != str(target["id"])
                    ]
                    target["depends_on"] = list(
                        dict.fromkeys(list(target.get("depends_on") or []) + inherited)
                    )
                    target["files"] = list(
                        dict.fromkeys(list(target.get("files") or []) + list(task.get("files") or []))
                    )
                    target["title"] = f"{target.get('title')} + {task.get('title')}"
                    target["instructions"] = (
                        f"{target.get('instructions')}\n\n{task.get('instructions')}"
                    )
                    changed = True
            merged = result
        return merged, aliases

    @staticmethod
    def _verification_only(task: dict[str, Any]) -> bool:
        """True for planner items that only run checks instead of writing code.

        The lead agent validates and runs the merged project itself, so such
        items would only duplicate work and race with the specialists.
        """
        text = f"{task.get('title') or ''} {task.get('instructions') or ''}".lower()
        checks = (
            "validate_project",
            "run_project",
            "run the test",
            "run test",
            "run tests",
            "проверь",
            "проверить",
            "запусти",
            "запустить",
            "валид",
            "заверш",
            "finish",
        )
        actions = (
            "create",
            "add",
            "implement",
            "write",
            "fix",
            "change",
            "edit",
            "update",
            "созда",
            "добав",
            "реализ",
            "напиш",
            "исправ",
            "измен",
            "обнов",
        )
        return any(marker in text for marker in checks) and not any(
            marker in text for marker in actions
        )

    @staticmethod
    def _merge_conflicts(
        tasks: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        merged: list[dict[str, Any]] = []
        aliases: dict[str, str] = {}
        for task in tasks:
            conflict = None
            for existing in merged:
                if existing["role"] != task["role"]:
                    continue
                if set(existing["files"]) & set(task["files"]):
                    conflict = existing
                    break
            if conflict is None:
                merged.append(task)
            else:
                aliases[str(task["id"])] = str(conflict["id"])
                inherited = [
                    str(dep)
                    for dep in task.get("depends_on") or []
                    if str(dep) != str(conflict["id"])
                ]
                conflict["depends_on"] = list(
                    dict.fromkeys(list(conflict.get("depends_on") or []) + inherited)
                )
                conflict["files"] = list(dict.fromkeys(conflict["files"] + task["files"]))
                conflict["title"] += " + " + task["title"]
                conflict["instructions"] += "\n\n" + task["instructions"]
        return merged, aliases

    @staticmethod
    def _break_cycles(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Guarantee that the dependency graph can always make progress.

        A model can still emit a cycle despite the prompt. Rather than stalling
        the whole task, drop the dependencies of one node in the cycle and log
        nothing user-facing: the work still happens, just without that edge.
        """
        by_id = {str(task["id"]): task for task in tasks}
        while True:
            indegree = {key: 0 for key in by_id}
            for task in by_id.values():
                for dependency in task.get("depends_on") or []:
                    if dependency in indegree:
                        indegree[str(task["id"])] += 1
            ready = [key for key, value in indegree.items() if value == 0]
            seen: set[str] = set()
            while ready:
                node = ready.pop()
                seen.add(node)
                for task in by_id.values():
                    if node in (task.get("depends_on") or []) and str(task["id"]) not in seen:
                        indegree[str(task["id"])] -= 1
                        if indegree[str(task["id"])] == 0:
                            ready.append(str(task["id"]))
            if len(seen) == len(by_id):
                return tasks
            stuck = next(key for key in by_id if key not in seen)
            by_id[stuck]["depends_on"] = []

    def _apply_plan(self, plan: dict[str, Any]) -> None:
        set_plan(
            self.project.root,
            [
                {
                    "id": task["id"],
                    "title": task["title"],
                    "status": "pending",
                    "role": task.get("role"),
                    "depends_on": task.get("depends_on") or [],
                }
                for task in plan["tasks"]
            ],
        )
        record_event(
            self.project.root,
            "plan",
            _tr(
                "Master agent split the task into {count} parallel items.",
                "Главный агент разделил задачу на {count} параллельных пунктов.",
                count=len(plan["tasks"]),
            ),
            {"tasks": plan["tasks"]},
        )

    # ------------------------------------------------------------------
    # Team: durable members and dependency mail
    # ------------------------------------------------------------------
    def _acquire_member(self, role: str, *, reuse: bool = False) -> Member:
        created = False
        with self._member_lock:
            candidates = [
                member
                for member in self._members
                if member.role == role and not member.busy
            ]
            if reuse and candidates:
                candidates.sort(key=lambda member: (-len(member.tasks), member.id))
            member = candidates[0] if candidates else None
            if member is None:
                self._member_seq += 1
                member = Member(
                    id=f"m{self._member_seq}",
                    role=role,
                    name=f"{role}-{self._member_seq}",
                )
                self._members.append(member)
                created = True
            member.busy = True
            roster = [item.name for item in self._members]
        if created:
            # Never hold the roster lock while calling into the UI.
            self.emit(
                "team",
                _tr(
                    "Team member “{name}” joined as {role}.",
                    "В команду вошёл агент «{name}» ({role}).",
                    name=member.name,
                    role=role,
                ),
                member=member.name,
                role=role,
                roster=roster,
            )
        return member

    def _release_member(self, member: Member, report: str = "") -> None:
        with self._member_lock:
            if report:
                member.remember(report)
            member.busy = False

    @staticmethod
    def _dependency_message(result: dict[str, Any]) -> dict[str, Any]:
        files = [
            str(item.get("path"))
            for item in result.get("files_changed") or []
            if item.get("path")
        ]
        return {
            "from": str(result.get("id") or ""),
            "title": str(result.get("title") or ""),
            "report": str(result.get("report") or "").strip()[:1200],
            "files": files[:8],
            "error": str(result.get("error") or ""),
        }

    def _member_task_prompt(
        self,
        task: dict[str, Any],
        original_task: str,
        member: Member,
    ) -> str:
        parts: list[str] = []
        memory = member.memory_text()
        if memory:
            parts.append(
                "DURABLE MEMBER MEMORY — your earlier work in this project:\n"
                + memory
            )
        inbox = task.get("_inbox") or []
        if inbox:
            lines = []
            for message in inbox[:6]:
                body = message.get("report") or message.get("error") or "no report"
                files = ", ".join(message.get("files") or [])
                suffix = f" Files: {files}." if files else ""
                lines.append(
                    f"- from {message.get('from')} “{message.get('title')}”: "
                    f"{body}{suffix}"
                )
            parts.append(
                "MESSAGES FROM COMPLETED TEAMMATES (context only; do not redo "
                "their work):\n" + "\n".join(lines)
            )
        parts.append("Original user task:\n" + original_task)
        parts.append("Your work item:\n" + str(task.get("instructions") or ""))
        parts.append(
            "Write scope (the only files you may change): "
            + ", ".join(str(path) for path in task.get("files") or [])
        )
        if memory or inbox:
            parts.append(
                "CONTINUATION RULE: this is a repair/continuation of earlier work, "
                "not a new project. Do not start with a full exploration. Read only "
                "the files and ranges named above (at most two targeted reads), then "
                "make a real edit. Do not repeat the phrase “I'll start by exploring”."
            )
        parts.append("Implement it now with tools and report the result.")
        return "\n\n".join(parts)

    def _specialist_prompt(self, role: str) -> str:
        return (
            "ROLE OVERRIDES — these replace the global rules 3, 5 and 7 above.\n"
            "You are a specialist in a team led by a captain. The captain owns "
            "the global plan, progress, validation, run and finish.\n"
            "The following tools are NOT available in this role and every call "
            "to them is rejected: finish, set_plan, update_task, report_progress, "
            "validate_project, run_project. Do not try them.\n\n"
            f"MULTI-AGENT SPECIALIST ROLE ({role})\n"
            "Work only on the item in the user message. The write scope there "
            "lists the only files you may change; you may read the whole project "
            "with list/read/search tools and use run_command for local checks.\n"
            "Work until the item is implemented, then reply with a short factual "
            "report of files changed and remaining concerns."
        )

    def _specialist_schemas(self) -> list[dict[str, Any]]:
        if self.project.project_type in {"site", "other"}:
            return _SPECIALIST_TOOLS
        return [
            schema
            for schema in _SPECIALIST_TOOLS
            if schema.get("name") not in SITE_TOOL_NAMES
        ]

    def _run_specialist(self, task: dict[str, Any], original_task: str) -> dict[str, Any]:
        label = str(task.get("title") or task.get("id") or "specialist")
        role = str(task.get("role") or "code")
        member = self._acquire_member(role, reuse=bool(task.get("_reuse")))
        label_prefix = f"{member.name}: {label}"
        report = ""
        error = ""
        agent = member.agent

        def forward(event: AgentEvent) -> None:
            # Token usage and generation time are real even when the work
            # happens inside a specialist. Dropping them here made the chat
            # counter look frozen during long parallel runs.
            if event.kind == "usage":
                self.budget.add(event.data.get("usage") or {})
                self.emit("usage", usage=event.data.get("usage") or {})
                return
            if event.kind == "assistant":
                text = (event.text or "").strip()
                if text:
                    prefix = _tr(
                        "Specialist “{label}”",
                        "Специалист «{label}»",
                        label=member.name,
                    )
                    self.emit("assistant", f"{prefix}:\n{text}")
                return
            if event.kind == "tool_start":
                tool = str(event.data.get("tool") or "")
                self.emit(
                    "tool_start",
                    event.text or tool,
                    tool=tool,
                    arguments=event.data.get("arguments") or {},
                    call_id=event.data.get("call_id") or "",
                    agent=member.name,
                    agent_label=label_prefix,
                )
                return
            if event.kind == "tool_result":
                self.emit(
                    "tool_result",
                    event.text or str(event.data.get("tool") or ""),
                    tool=str(event.data.get("tool") or ""),
                    success=event.data.get("success", True),
                    result=event.data.get("result") or "",
                    call_id=event.data.get("call_id") or "",
                    agent=member.name,
                    agent_label=label_prefix,
                )
                return
            if event.kind == "status":
                self.emit("status", f"{label_prefix} - {event.text}")
            elif event.kind == "error":
                self.emit("status", f"{label_prefix} - {event.text}")
            # Tool results and changes stay inside the specialist; the master
            # emits the final changes card and answer.

        try:
            self.emit(
                "status",
                _tr(
                    "Agent “{name}” is working on “{label}”…",
                    "Агент «{name}» работает над «{label}»…",
                    name=member.name,
                    label=label,
                ),
            )
            try:
                update_task(self.project.root, str(task["id"]), "in_progress")
            except Exception:
                pass
            if agent is None:
                agent = Agent(
                    self.project,
                    self.settings,
                    on_event=forward,
                    cancel=self.cancel,
                    chat_id=(f"{self.chat_id}:{member.id}" if self.chat_id else None),
                    hidden_message=False,
                    analysis=False,
                    reply_language=self.reply_language or i18n.current_language(),
                    persist_messages=False,
                    extra_system_prompt=self._specialist_prompt(role),
                    write_scope=tuple(task["files"]),
                    seed_history=False,
                    create_snapshot=False,
                    supervisor=False,
                    require_ready=False,
                    tool_schemas_override=self._specialist_schemas(),
                    sync_history=False,
                    budget=self.budget,
                    confirm_write=self._confirm_write if self.confirm_write else None,
                    max_seconds=self.specialist_timeout_minutes * 60,
                    max_steps_override=self.specialist_max_steps,
                    expect_writes=True,
                    cache_profile=False,
                )
                member.agent = agent
            # A fix round continues the previous conversation, so the agent
            # does not re-read the whole project; a genuinely new task gets
            # fresh evidence.
            continuing = bool(task.get("_reuse")) and bool(
                getattr(agent, "messages", None)
            )
            if not continuing:
                reset = getattr(agent.tools, "reset_evidence", None)
                if callable(reset):
                    reset()
            agent.tools.write_scope = tuple(task["files"]) or None
            agent.on_event = forward

            member.tasks.append(str(task["id"]))
            report = agent.run(
                self._member_task_prompt(task, original_task, member),
                continue_conversation=continuing,
            )
            error = agent.last_error
            incomplete = getattr(agent, "incomplete_reason", "") or ""
            if not error and incomplete:
                # The item was stopped by a step/time/write guard; it must not
                # be shown as done in the plan.
                error = incomplete
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        finally:
            self._release_member(member, report if not error else "")

        result = {
            "id": str(task["id"]),
            "role": role,
            "title": str(task["title"]),
            "report": report,
            "error": error,
            "member": member.name,
            "files_changed": (
                list(agent.tools.changed_files) if agent is not None else []
            ),
            "changed_count": (
                agent.tools.files_changed if agent is not None else 0
            ),
        }
        try:
            update_task(
                self.project.root,
                str(task["id"]),
                "done" if not error else "skipped",
            )
        except Exception:
            pass
        self.emit(
            "status",
            _tr(
                "Agent “{name}” finished “{label}”.",
                "Агент «{name}» завершил «{label}».",
                name=member.name,
                label=label,
            ),
        )
        return result

    def _execute(
        self,
        plan: dict[str, Any],
        task: str,
        done: dict[str, dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        tasks = [dict(item) for item in plan.get("tasks") or []]
        done = dict(done or {})
        results: list[dict[str, Any]] = [dict(item) for item in done.values()]
        if not tasks:
            return results
        pending = {
            str(item["id"]): item for item in tasks if str(item["id"]) not in done
        }
        wave = 0
        while pending and not self.cancel.is_set() and not self._deadline_exceeded():
            ready = [
                item
                for item in pending.values()
                if all(str(dep) in done for dep in (item.get("depends_on") or []))
            ]
            if not ready:
                # The DAG validator should prevent this, but a stalled task is
                # worse than an unnecessary parallel wave.
                ready = list(pending.values())
            wave += 1
            self.emit(
                "status",
                _tr(
                    "Captain: wave {wave} — {count} agent(s) in parallel…",
                    "Капитан: волна {wave} — агентов параллельно: {count}…",
                    wave=wave,
                    count=len(ready),
                ),
            )
            for item in ready:
                item["_inbox"] = [
                    self._dependency_message(done[str(dep)])
                    for dep in (item.get("depends_on") or [])
                    if str(dep) in done
                ]
            workers = max(1, min(self.workers, len(ready)))
            with ThreadPoolExecutor(
                max_workers=workers, thread_name_prefix="reasonable-agent"
            ) as pool:
                futures = {
                    pool.submit(self._run_specialist, item, task): item
                    for item in ready
                }
                for future in as_completed(futures):
                    item = futures[future]
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = {
                            "id": str(item.get("id")),
                            "role": str(item.get("role")),
                            "title": str(item.get("title")),
                            "report": "",
                            "error": f"{type(exc).__name__}: {exc}",
                            "files_changed": [],
                            "changed_count": 0,
                        }
                    done[str(item["id"])] = result
                    pending.pop(str(item["id"]), None)
                    results.append(result)
                    self._journal_save(task, plan, results)
        return results

    # ------------------------------------------------------------------
    def _verify(self) -> dict[str, Any]:
        self.emit("status", _tr("Master agent: checking the merged project…", "Главный агент: проверяю общий проект…"))
        tools = AgentTools(self.project, image_config=self.image_config)
        try:
            validation_raw = tools.call("validate_project")
        except Exception as exc:
            validation_raw = json.dumps({"ok": False, "error": str(exc)})
        try:
            validation = json.loads(validation_raw)
        except ValueError:
            validation = {"ok": False, "raw": validation_raw}
        run_raw = ""
        run: dict[str, Any] = {}
        if validation.get("ok") and not validation.get("has_errors"):
            try:
                run_raw = tools.call("run_project", {"frames": 8})
                run = json.loads(run_raw)
            except Exception as exc:
                run_raw = json.dumps({"ok": False, "error": str(exc)})
                run = {"ok": False, "error": str(exc)}
        ok = bool(validation.get("ok")) and not validation.get("has_errors")
        if ok:
            ok = bool(run.get("ok")) and int(run.get("returncode", 1)) == 0
        missing: list[str] = []
        for issue in validation.get("issues") or []:
            if isinstance(issue, dict) and issue.get("level") == "error":
                missing.append(str(issue.get("message") or "validation error"))
        if run and not run.get("ok"):
            missing.append(str(run.get("error") or "the project did not run cleanly"))
        return {
            "ok": ok,
            "validation": validation,
            "validation_raw": validation_raw,
            "run": run,
            "run_raw": run_raw,
            "missing": missing,
        }

    def _changed_payload(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: dict[str, dict[str, Any]] = {}
        for result in results:
            for item in result.get("files_changed") or []:
                path = str(item.get("path") or "")
                if path:
                    seen[path] = dict(item)
        payload: list[dict[str, Any]] = []
        for path, item in list(seen.items())[:8]:
            payload.append(dict(item))
        if not payload:
            return []
        # The audit only needs what changed; re-sending whole files made every
        # repair round pay for the same code again.
        return changed_files_payload(
            self.project,
            str((self.snapshot or {}).get("id") or ""),
            payload,
            file_limit=2200,
            total_limit=10000,
        )

    def _review(
        self,
        task: str,
        plan: dict[str, Any],
        results: list[dict[str, Any]],
        verification: dict[str, Any],
    ) -> dict[str, Any]:
        self.emit(
            "status",
            _tr("Master agent: independent completion audit…", "Главный агент: независимая проверка результата…"),
        )
        payload = {
            "user_task": task,
            "reply_language": i18n.current_language(),
            "plan": plan.get("tasks") or [],
            "results": [
                {
                    "id": item.get("id"),
                    "role": item.get("role"),
                    "title": item.get("title"),
                    "report": str(item.get("report") or "")[:2500],
                    "error": item.get("error") or "",
                    "changed_count": item.get("changed_count") or 0,
                }
                for item in results
            ],
            "changed_files": self._changed_payload(results),
            "validation": verification.get("validation"),
            "validation_raw": str(verification.get("validation_raw") or "")[:2500],
            "run": verification.get("run"),
            "run_raw": str(verification.get("run_raw") or "")[:2500],
        }
        messages = [
            {"role": "system", "content": SUPERVISOR_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        try:
            result = self._call_model(messages, temperature=0.0)
            data = _extract_json_object(result.content) or {}
        except Exception:
            data = {}
        # If the audit endpoint is temporarily unavailable or returns prose
        # instead of JSON, do not invent a failure: trust the concrete
        # validation/run evidence and finish, exactly like the single agent.
        if not data:
            return {
                "complete": bool(verification.get("ok")),
                "missing": list(verification.get("missing") or []),
                "next": "",
            }
        model_complete = bool(data.get("complete"))
        missing = [
            str(item).strip()
            for item in (data.get("missing") or [])
            if str(item).strip()
        ][:8]
        if not verification.get("ok"):
            model_complete = False
            missing.extend(verification.get("missing") or [])
            missing = list(dict.fromkeys(missing))[:8]
        if not missing and not model_complete:
            missing = [_tr("The requested behaviour is not confirmed by validation.", "Запрошенное поведение не подтверждено проверкой.")]
        return {
            "complete": model_complete and bool(verification.get("ok")),
            "missing": missing,
            "next": str(data.get("next") or data.get("instruction") or "").strip(),
        }

    def _fix_task(
        self,
        task: str,
        review: dict[str, Any],
        results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        code_files = [
            str(item.get("path"))
            for result in results
            for item in result.get("files_changed") or []
            if str(item.get("path") or "").endswith((".py", ".json"))
            and not str(item.get("path") or "").startswith("assets/")
        ]
        files = list(dict.fromkeys(code_files)) or ["*.py"]
        if not any("*" in item for item in files):
            # Keep room for new helper files while still protecting assets.
            files.append("*.py")
        instructions = (
            "Fix the remaining issues in the user's task. Original task:\n"
            f"{task}\n\n"
            "The independent audit found:\n"
            + "\n".join(f"- {item}" for item in review.get("missing") or [])
            + "\n\nNext action: "
            + (review.get("next") or "implement and verify the missing items.")
        )
        return {
            "id": f"fix-{uuid.uuid4().hex[:6]}",
            "role": "code",
            "title": _tr("Repair round", "Круг исправлений"),
            "files": files,
            "instructions": instructions,
        }

    def _final_text(
        self,
        task: str,
        plan: dict[str, Any],
        results: list[dict[str, Any]],
        verification: dict[str, Any],
        review: dict[str, Any],
        complete: bool,
    ) -> str:
        language = _tr("Russian", "русский") if i18n.current_language() == "ru" else "English"
        payload = {
            "user_task": task,
            "complete": complete,
            "missing": review.get("missing") or [],
            "verification_ok": bool(verification.get("ok")),
            "work_items": [
                {
                    "title": item.get("title"),
                    "role": item.get("role"),
                    "report": str(item.get("report") or "")[:1200],
                    "error": item.get("error") or "",
                }
                for item in results
            ],
        }
        streaming = bool(
            (self.settings.data.get("agent", {}) or {}).get("stream", False)
        )
        if streaming:
            self.client.stream = True
            self.client.stream_callback = self._emit_stream_delta
        try:
            result = self._call_model(
                [
                    {"role": "system", "content": FINAL_PROMPT.format(language=language)},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                temperature=0.2,
            )
            text = (result.content or "").strip()
            if text and not _looks_degenerate(text):
                return text
        except Exception:
            pass
        finally:
            if streaming:
                self.client.stream = False
                self.client.stream_callback = None
        if complete:
            return _tr("Done. The project has been built and verified.", "Готово. Проект собран и проверен.")
        return _tr(
            "The project was updated, but the final check still reports: ",
            "Проект обновлён, но финальная проверка сообщает: ",
        ) + "; ".join(review.get("missing") or [])

    # ------------------------------------------------------------------
    def _start_snapshot(self, task: str) -> None:
        try:
            self.snapshot = create_snapshot(
                self.project,
                label=task[:110],
                reason="agent",
            )
            self.emit(
                "snapshot",
                _tr("Project snapshot created", "Создан снимок проекта"),
                snapshot=self.snapshot,
            )
        except Exception:
            self.snapshot = None

    def _finish_snapshot(self, task: str, complete: bool) -> None:
        if self.snapshot:
            try:
                updated = update_snapshot(
                    self.project,
                    str(self.snapshot.get("id")),
                    changed_files=self.changes,
                    outcome="done" if complete else "incomplete",
                    final_text=(self.final_text or "")[:4000],
                )
                if updated is not None:
                    self.snapshot = updated
            except Exception:
                pass
        self.emit(
            "changes",
            _tr(
                "Files changed: {count}",
                "Изменено файлов: {count}",
                count=len(self.changes),
            )
            if self.changes
            else _tr("No project files changed", "Файлы проекта не изменились"),
            files=self.changes,
            snapshot=self.snapshot,
            outcome="done" if complete else "incomplete",
        )

    # ------------------------------------------------------------------
    def _collect_changes(self, results: list[dict[str, Any]]) -> None:
        seen: dict[str, dict] = {}
        for result in results:
            for item in result.get("files_changed") or []:
                path = str(item.get("path") or "")
                if path:
                    seen[path] = dict(item)
        self.changes = list(seen.values())
