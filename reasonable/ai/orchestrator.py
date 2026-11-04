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
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from reasonable.core import chatlog, i18n
from reasonable.core.history import create_snapshot, update_snapshot
from reasonable.core.i18n import tr as _tr
from reasonable.core.progress import (
    finish_progress,
    read_state,
    record_event,
    set_plan,
    set_status,
    update_task,
)

from .agent import Agent, AgentEvent, SUPERVISOR_PROMPT, _extract_json_object
from .client import AIClient, AIError, ChatResult
from .prompts import build_initial_user_message
from .tools import AgentTools, TOOL_SCHEMAS

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
     "files": ["main.py"], "instructions": "precise implementation brief"},
    {"id": "assets-1", "role": "assets", "title": "short title",
     "files": ["assets/sprites/player.png"], "instructions": "what to draw"}
  ]
}

Rules:
- 2 to {max_tasks} tasks. A small task may use one task.
- role is only "code" or "assets".
- Code tasks must have disjoint file lists. If two features need the same file,
  merge them into one task.
- Assets tasks may only target files under assets/.
- Do not create review/validate/finish tasks — the lead agent does that.
- Each instruction must be complete enough for a specialist that does not see
  the other tasks: what to build, where, and how it connects to the whole.
- The starter example is a base, not the specification. Follow the user task.
- Reply with JSON only, no markdown fences."""

FINAL_PROMPT = """You are the lead agent writing the final report to the user.
Use the supplied work results and verification. Reply in {language}.
Be concise and factual: what was built, where the files are, how to run it, any
honest caveat. Never claim that a missing item was completed."""


class Orchestrator:
    """Master planner + parallel specialists with a final quality audit."""

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
    ) -> None:
        from reasonable.core.settings import Settings

        self.project = project
        self.settings = settings or Settings()
        self.message = message
        self.on_event = on_event
        self.cancel = cancel or threading.Event()
        self.chat_id = chat_id
        self.hidden_message = bool(hidden_message)
        self.analysis = bool(analysis)
        self.reply_language = reply_language
        self.persist_messages = bool(persist_messages)
        agent_settings = self.settings.data.get("agent", {}) or {}
        self.workers = max(2, min(6, int(agent_settings.get("parallel_workers", 3) or 3)))
        self.max_rounds = max(1, min(5, int(agent_settings.get("parallel_rounds", 3) or 3)))
        self.config = dict(self.settings.get_provider_config())
        if self.chat_id and (
            "opencode.ai" in str(self.config.get("base_url") or "").lower()
            or self.config.get("id") == "opencode"
        ):
            headers = dict(self.config.get("headers") or {})
            headers["x-opencode-session"] = f"reasonable-{self.chat_id}"
            self.config["headers"] = headers
        self.client = AIClient(self.config, timeout=180, retries=2)
        self.image_config = self.settings.image_config()
        self.finished = False
        self.final_text = ""
        self.last_error = ""
        self.incomplete_reason = ""
        self.snapshot: dict | None = None
        self.changes: list[dict] = []
        self._event_lock = threading.Lock()

    # ------------------------------------------------------------------
    def emit(self, kind: str, text: str = "", **data: Any) -> None:
        if self.on_event is None:
            return
        with self._event_lock:
            try:
                self.on_event(AgentEvent(kind, text, data))
            except Exception:
                pass

    def _call_model(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.2,
    ) -> ChatResult:
        started = time.perf_counter()
        try:
            result = self.client.chat(messages, None, temperature=temperature)
        except Exception:
            self.emit(
                "usage",
                usage=Agent._usage_payload(None, time.perf_counter() - started),
            )
            raise
        self.emit(
            "usage",
            usage=Agent._usage_payload(result.usage, time.perf_counter() - started),
        )
        return result

    # ------------------------------------------------------------------
    def run(self, user_message: str | None = None) -> str:
        task = (user_message or self.message or build_initial_user_message(self.project)).strip()
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
            plan = self._plan(task)
            if plan is None:
                return self._fallback(task)
            self._start_snapshot(task)
            self._apply_plan(plan)
            results = self._execute(plan, task)
            verification = self._verify()
            review = self._review(task, plan, results, verification)

            rounds = 0
            while (
                not review.get("complete")
                and rounds < self.max_rounds
                and not self.cancel.is_set()
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
        except AIError as exc:
            self.last_error = exc.message
            self.emit("error", exc.message, error_kind="other")
            set_status(self.project.root, "error", exc.message[:300], event_type="error")
            return ""
        except Exception:
            # A planning/execution failure must never lose the task: continue
            # in the proven single-agent mode on the same project.
            return self._fallback(task)

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
        )
        text = agent.run(task)
        self.last_error = agent.last_error
        self.incomplete_reason = agent.incomplete_reason
        self.finished = agent.finished
        self.final_text = agent.final_text or text
        return text

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
            tasks.append(
                {
                    "id": str(item.get("id") or f"{role}-{index}"),
                    "role": role,
                    "title": str(item.get("title") or _tr("Work item {index}", "Задача {index}", index=index)),
                    "files": list(dict.fromkeys(files)),
                    "instructions": str(item.get("instructions") or item.get("title") or ""),
                }
            )
        return self._merge_conflicts(tasks)

    @staticmethod
    def _merge_conflicts(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
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
                conflict["files"] = list(dict.fromkeys(conflict["files"] + task["files"]))
                conflict["title"] += " + " + task["title"]
                conflict["instructions"] += "\n\n" + task["instructions"]
        return merged

    def _apply_plan(self, plan: dict[str, Any]) -> None:
        set_plan(
            self.project.root,
            [
                {"id": task["id"], "title": task["title"], "status": "pending"}
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
    def _specialist_prompt(self, task: dict[str, Any]) -> str:
        scope = ", ".join(task["files"])
        return (
            "MULTI-AGENT SPECIALIST ROLE\n"
            f"You are the {task['role']} specialist. Work only on this item:\n"
            f"{task['instructions']}\n\n"
            f"Write scope (the only files you may change): {scope}.\n"
            "You may read the whole project with read/list/search tools.\n"
            "Do not call finish, set_plan, update_task, report_progress, "
            "validate_project or run_project: the lead agent owns global progress "
            "and validates the merged result after all specialists finish.\n"
            "Work until this item is implemented, then reply with a short factual "
            "report of files changed and remaining concerns."
        )

    def _run_specialist(self, task: dict[str, Any], original_task: str) -> dict[str, Any]:
        label = str(task.get("title") or task.get("id") or "specialist")
        self.emit(
            "status",
            _tr("Agent “{label}” is working…", "Агент «{label}» работает…", label=label),
        )
        update_task(self.project.root, str(task["id"]), "in_progress")
        label_prefix = f"{task['role']}: {label}"

        def forward(event: AgentEvent) -> None:
            if event.kind == "status":
                self.emit("status", f"{label_prefix} — {event.text}")
            elif event.kind == "error":
                self.emit("status", f"{label_prefix} — {event.text}")
            # Tool/assistant/changes events stay inside the specialist; the
            # master emits the final changes card and answer.

        agent = Agent(
            self.project,
            self.settings,
            on_event=forward,
            cancel=self.cancel,
            hidden_message=False,
            analysis=False,
            reply_language=self.reply_language or i18n.current_language(),
            persist_messages=False,
            extra_system_prompt=self._specialist_prompt(task),
            write_scope=tuple(task["files"]),
            seed_history=False,
            create_snapshot=False,
            supervisor=False,
            require_ready=False,
            tool_schemas_override=_SPECIALIST_TOOLS,
            sync_history=False,
        )
        try:
            report = agent.run(
                "Original user task:\n"
                f"{original_task}\n\n"
                "Your work item:\n"
                f"{task['instructions']}\n\n"
                "Implement it now with tools and report the result."
            )
            error = agent.last_error
        except Exception as exc:
            report = ""
            error = f"{type(exc).__name__}: {exc}"
        result = {
            "id": str(task["id"]),
            "role": str(task["role"]),
            "title": str(task["title"]),
            "report": report,
            "error": error,
            "files_changed": list(agent.tools.changed_files),
            "changed_count": agent.tools.files_changed,
        }
        update_task(self.project.root, str(task["id"]), "done" if not error else "skipped")
        self.emit(
            "status",
            _tr(
                "Agent “{label}” finished.",
                "Агент «{label}» завершил работу.",
                label=label,
            ),
        )
        return result

    def _execute(self, plan: dict[str, Any], task: str) -> list[dict[str, Any]]:
        tasks = list(plan.get("tasks") or [])
        results: list[dict[str, Any]] = []
        if not tasks:
            return results
        workers = max(1, min(self.workers, len(tasks)))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="reasonable-agent") as pool:
            futures = {
                pool.submit(self._run_specialist, item, task): item for item in tasks
            }
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as exc:
                    item = futures[future]
                    results.append(
                        {
                            "id": str(item.get("id")),
                            "role": str(item.get("role")),
                            "title": str(item.get("title")),
                            "report": "",
                            "error": f"{type(exc).__name__}: {exc}",
                            "files_changed": [],
                            "changed_count": 0,
                        }
                    )
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
                run_raw = tools.call("run_project", frames=8)
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
            entry = dict(item)
            try:
                entry["content"] = self.project.read_text(path)[:4500]
            except Exception:
                entry["content"] = ""
            payload.append(entry)
        return payload

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
        try:
            result = self._call_model(
                [
                    {"role": "system", "content": FINAL_PROMPT.format(language=language)},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                temperature=0.2,
            )
            text = (result.content or "").strip()
            if text:
                return text
        except Exception:
            pass
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
