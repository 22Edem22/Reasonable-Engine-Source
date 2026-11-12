import json
import tempfile
import unittest
from pathlib import Path

from reasonable.core.progress import (
    activity_is_live,
    derived_percent,
    ensure_state,
    events_path,
    finish_progress,
    read_events,
    read_state,
    record_event,
    scan_recent_files,
    set_plan,
    set_progress,
    set_status,
    update_task,
)


class ProgressTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_ensure_state_creates_files(self) -> None:
        state = ensure_state(self.root, "external")
        self.assertEqual(state["mode"], "external")
        self.assertTrue((self.root / "progress" / "state.json").exists())
        self.assertTrue((self.root / "progress" / "events.jsonl").exists())
        self.assertEqual(read_state(self.root)["status"], "idle")

    def test_events_are_appended_and_readable(self) -> None:
        record_event(self.root, "agent", "Первый шаг", {"n": 1})
        record_event(self.root, "tool", "Второй шаг", {"n": 2})
        events = read_events(self.root)
        self.assertEqual([event["message"] for event in events], ["Первый шаг", "Второй шаг"])
        self.assertEqual(events[1]["data"], {"n": 2})
        self.assertEqual(read_state(self.root)["last_event"], "Второй шаг")

    def test_large_journal_returns_only_the_tail(self) -> None:
        # The editor polls this file, so it must never read the whole journal.
        ensure_state(self.root)
        path = events_path(self.root)
        with path.open("a", encoding="utf-8") as handle:
            for index in range(4000):
                handle.write(
                    json.dumps(
                        {"ts": "2026-01-01T00:00:00", "type": "task", "message": f"Шаг {index}"},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        events = read_events(self.root, limit=25)
        self.assertEqual(len(events), 25)
        self.assertEqual(events[-1]["message"], "Шаг 3999")
        self.assertEqual(events[0]["message"], "Шаг 3975")

    def test_recent_files_skip_ignored_folders(self) -> None:
        ensure_state(self.root)
        (self.root / "src").mkdir()
        (self.root / "src" / "main.py").write_text("print(1)\n", encoding="utf-8")
        engine = self.root / "_engine" / "reasonable"
        engine.mkdir(parents=True)
        (engine / "huge.py").write_text("x = 1\n", encoding="utf-8")
        (self.root / "build").mkdir()
        (self.root / "build" / "out.bin").write_text("x", encoding="utf-8")

        paths = [row["path"] for row in scan_recent_files(self.root, limit=10)]
        self.assertEqual(paths, ["src/main.py"])

    def test_plan_and_task_updates(self) -> None:
        set_plan(self.root, ["Изучить проект", "Собрать меню", "Проверить запуск"])
        state = read_state(self.root)
        self.assertEqual([task["id"] for task in state["tasks"]], ["t1", "t2", "t3"])

        update_task(self.root, "t2", "in_progress")
        state = read_state(self.root)
        self.assertEqual(state["tasks"][1]["status"], "in_progress")

        update_task(self.root, "3", "done")
        state = read_state(self.root)
        self.assertEqual(state["tasks"][2]["status"], "done")

        update_task(self.root, "изучить", "done")
        state = read_state(self.root)
        self.assertEqual(state["tasks"][0]["status"], "done")

        with self.assertRaises(ValueError):
            update_task(self.root, "несуществующая", "done")

    def test_set_progress_clamps_and_marks_running(self) -> None:
        set_progress(self.root, 150, stage="Полировка", message="Почти готово")
        state = read_state(self.root)
        self.assertEqual(state["percent"], 100.0)
        self.assertEqual(state["status"], "running")
        self.assertEqual(state["stage"], "Полировка")

        set_progress(self.root, -5)
        self.assertEqual(read_state(self.root)["percent"], 0.0)

    def test_status_and_finish(self) -> None:
        set_plan(self.root, ["Раз", "Два"])
        update_task(self.root, "t1", "done")
        set_status(self.root, "error", "Ошибка сети", event_type="error")
        self.assertEqual(read_state(self.root)["status"], "error")

        finish_progress(self.root, "Готово")
        state = read_state(self.root)
        self.assertEqual(state["status"], "done")
        self.assertEqual(state["percent"], 100.0)
        self.assertTrue(all(task["status"] == "done" for task in state["tasks"]))
        self.assertTrue(activity_is_live(self.root))

    def test_derived_percent_prefers_reported_percent(self) -> None:
        self.assertEqual(derived_percent({"percent": 0, "tasks": []}), 0.0)
        self.assertEqual(derived_percent({"percent": 37, "tasks": []}), 37.0)
        self.assertEqual(derived_percent({"percent": 250}), 100.0)

    def test_derived_percent_counts_tasks_when_report_is_zero(self) -> None:
        state = {
            "percent": 0,
            "tasks": [
                {"id": "t1", "status": "done"},
                {"id": "t2", "status": "done"},
                {"id": "t3", "status": "in_progress"},
                {"id": "t4", "status": "pending"},
            ],
        }
        self.assertEqual(derived_percent(state), 50.0)
        state["tasks"][2]["status"] = "skipped"
        self.assertEqual(derived_percent(state), 50.0)

    def test_task_updates_lift_stored_percent(self) -> None:
        set_plan(self.root, ["Раз", "Два", "Три", "Четыре"])
        self.assertEqual(read_state(self.root)["percent"], 0)
        update_task(self.root, "t1", "done")
        state = read_state(self.root)
        self.assertEqual(state["percent"], 25.0)
        # The task plan is authoritative: a new plan resets a stale 100%.
        set_progress(self.root, 80)
        update_task(self.root, "t2", "done")
        state = read_state(self.root)
        self.assertEqual(state["percent"], 50.0)

    def test_a_new_plan_resets_a_stale_hundred_percent(self) -> None:
        set_progress(self.root, 100, stage="Готово")
        set_plan(self.root, ["Проверить интерфейс", "Убрать временные файлы"])
        state = read_state(self.root)
        self.assertEqual(state["percent"], 0.0)
        self.assertEqual(state["status"], "running")


if __name__ == "__main__":
    unittest.main()
