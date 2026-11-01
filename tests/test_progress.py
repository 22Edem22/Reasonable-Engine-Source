import tempfile
import unittest
from pathlib import Path

from reasonable.core.progress import (
    activity_is_live,
    derived_percent,
    ensure_state,
    finish_progress,
    read_events,
    read_state,
    record_event,
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
        self.assertEqual(derived_percent(state), 75.0)

    def test_task_updates_lift_stored_percent(self) -> None:
        set_plan(self.root, ["Раз", "Два", "Три", "Четыре"])
        self.assertEqual(read_state(self.root)["percent"], 0)
        update_task(self.root, "t1", "done")
        state = read_state(self.root)
        self.assertEqual(state["percent"], 25.0)
        # An explicitly reported percent is never lowered by task updates.
        set_progress(self.root, 80)
        update_task(self.root, "t2", "done")
        state = read_state(self.root)
        self.assertEqual(state["percent"], 80.0)


if __name__ == "__main__":
    unittest.main()
