import tempfile
import unittest
from pathlib import Path

from reasonable.core.history import (
    create_snapshot,
    delete_snapshot,
    get_snapshot,
    latest_snapshot,
    list_snapshots,
    restore_snapshot,
    snapshot_files,
    update_snapshot,
)


class HistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "project"
        self.root.mkdir()
        (self.root / "main.py").write_text("print('v1')\n", encoding="utf-8")
        (self.root / "project.json").write_text('{"name": "test"}\n', encoding="utf-8")
        (self.root / "assets").mkdir()
        (self.root / "assets" / "player.png").write_bytes(b"png-v1")
        (self.root / "_engine").mkdir()
        (self.root / "_engine" / "engine.py").write_text("engine\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_snapshot_round_trip(self) -> None:
        meta = create_snapshot(self.root, label="До агента", reason="agent", record=False)
        self.assertTrue(meta["id"])
        self.assertEqual(meta["reason"], "agent")
        self.assertTrue(Path(meta["path"]).is_dir())

        (self.root / "main.py").write_text("print('broken')\n", encoding="utf-8")
        (self.root / "new_file.py").write_text("new\n", encoding="utf-8")
        (self.root / "debug.log").write_text("runtime log\n", encoding="utf-8")

        result = restore_snapshot(self.root, meta["id"], safety=False)
        self.assertEqual(result["restored"], 3)
        self.assertEqual((self.root / "main.py").read_text(encoding="utf-8"), "print('v1')\n")
        self.assertFalse((self.root / "new_file.py").exists())
        # Logs and caches are not snapshotted, so they must survive a restore.
        self.assertTrue((self.root / "debug.log").is_file())
        # The vendored engine is never part of snapshots or restores.
        self.assertTrue((self.root / "_engine" / "engine.py").is_file())
        self.assertIn("main.py", snapshot_files(self.root, meta["id"]))

    def test_safety_snapshot_allows_undoing_restore(self) -> None:
        meta = create_snapshot(self.root, label="v1", record=False)
        (self.root / "main.py").write_text("print('v2')\n", encoding="utf-8")
        result = restore_snapshot(self.root, meta["id"], safety=True)
        safety = result["safety_snapshot"]
        self.assertIsNotNone(safety)
        self.assertEqual((self.root / "main.py").read_text(encoding="utf-8"), "print('v1')\n")

        restore_snapshot(self.root, safety["id"], safety=False)
        self.assertEqual((self.root / "main.py").read_text(encoding="utf-8"), "print('v2')\n")

    def test_list_update_and_delete(self) -> None:
        first = create_snapshot(self.root, label="Первый", record=False)
        second = create_snapshot(self.root, label="Второй", record=False)
        rows = list_snapshots(self.root)
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["id"] for row in rows}, {first["id"], second["id"]})

        update_snapshot(self.root, first["id"], changed_files=[{"path": "main.py", "action": "edit"}])
        reloaded = get_snapshot(self.root, first["id"])
        self.assertEqual(reloaded["changed_files"][0]["path"], "main.py")
        self.assertEqual(latest_snapshot(self.root)["id"], rows[0]["id"])

        self.assertTrue(delete_snapshot(self.root, first["id"]))
        self.assertIsNone(get_snapshot(self.root, first["id"]))
        self.assertIsNone(get_snapshot(self.root, "../outside"))
        self.assertEqual(snapshot_files(self.root, "../outside"), [])
        self.assertFalse(delete_snapshot(self.root, "../outside"))


if __name__ == "__main__":
    unittest.main()
