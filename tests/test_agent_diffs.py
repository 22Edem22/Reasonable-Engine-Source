"""Audit payloads prefer diffs over re-sending whole changed files."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from reasonable.ai.agent import Agent
from reasonable.ai.diffs import changed_files_payload, unified_diff
from reasonable.core.history import create_snapshot, snapshot_text
from reasonable.core.project import Project, default_manifest
from reasonable.core.settings import Settings


class DiffPayloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "project"
        self.root.mkdir(parents=True)
        self.project = Project.create(
            self.root,
            default_manifest("Diffs", goal="Audit cheaply"),
            scaffold=False,
        )
        (self.root / "main.py").write_text("print('ok')\n", encoding="utf-8")
        self.settings = Settings(path=self.root / "settings.json")

    def _snapshot(self) -> str:
        return str(create_snapshot(self.project, label="before", reason="agent")["id"])

    def test_unified_diff_shows_only_the_change(self) -> None:
        diff = unified_diff("a\nb\nc\n", "a\nB\nc\n", "main.py")
        self.assertIn("-b", diff)
        self.assertIn("+B", diff)
        self.assertIn("--- a/main.py", diff)
        self.assertIn("+++ b/main.py", diff)

    def test_snapshot_reads_the_old_text_and_rejects_traversal(self) -> None:
        snapshot_id = self._snapshot()
        self.assertEqual(snapshot_text(self.project, snapshot_id, "main.py"), "print('ok')\n")
        self.assertIsNone(snapshot_text(self.project, snapshot_id, "../settings.json"))
        self.assertIsNone(snapshot_text(self.project, snapshot_id, "missing.py"))

    def test_edited_file_is_sent_as_a_diff_not_full_content(self) -> None:
        snapshot_id = self._snapshot()
        (self.root / "main.py").write_text("print('changed')\n", encoding="utf-8")
        payload = changed_files_payload(
            self.project,
            snapshot_id,
            [{"path": "main.py", "action": "edit"}],
        )
        self.assertEqual(len(payload), 1)
        entry = payload[0]
        self.assertIn("+print('changed')", entry["diff"])
        self.assertIn("-print('ok')", entry["diff"])
        self.assertNotIn("content", entry)
        self.assertFalse(entry["truncated"])

    def test_created_and_deleted_files_are_represented(self) -> None:
        snapshot_id = self._snapshot()
        (self.root / "new_file.py").write_text("x = 1\n", encoding="utf-8")
        (self.root / "main.py").unlink()
        payload = changed_files_payload(
            self.project,
            snapshot_id,
            [
                {"path": "new_file.py", "action": "create"},
                {"path": "main.py", "action": "delete"},
            ],
        )
        by_path = {item["path"]: item for item in payload}
        self.assertIn("+x = 1", by_path["new_file.py"]["diff"])
        self.assertIn("-print('ok')", by_path["main.py"]["diff"])

    def test_total_budget_is_respected(self) -> None:
        snapshot_id = self._snapshot()
        (self.root / "big.py").write_text("y\n" * 4000, encoding="utf-8")
        payload = changed_files_payload(
            self.project,
            snapshot_id,
            [{"path": "big.py", "action": "create"}],
            file_limit=500,
            total_limit=600,
        )
        self.assertEqual(len(payload), 1)
        self.assertLessEqual(len(payload[0]["diff"]), 700)
        self.assertTrue(payload[0]["truncated"])

    def test_binary_asset_is_not_diffed_as_text(self) -> None:
        snapshot_id = self._snapshot()
        assets = self.root / "assets"
        assets.mkdir(exist_ok=True)
        (assets / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        payload = changed_files_payload(
            self.project,
            snapshot_id,
            [{"path": "assets/logo.png", "action": "generate", "size": 8}],
        )
        self.assertEqual(payload[0]["note"], "binary asset")
        self.assertNotIn("diff", payload[0])

    def test_without_a_snapshot_the_payload_falls_back_to_content(self) -> None:
        payload = changed_files_payload(
            self.project,
            "",
            [{"path": "main.py", "action": "edit"}],
        )
        self.assertEqual(payload[0]["path"], "main.py")
        self.assertIn("print('ok')", payload[0]["content"])

    def test_agent_supervisor_uses_diffs_when_a_snapshot_exists(self) -> None:
        snapshot_id = self._snapshot()
        (self.root / "main.py").write_text("print('changed')\n", encoding="utf-8")
        agent = Agent(
            self.project,
            self.settings,
            persist_messages=False,
            seed_history=False,
            create_snapshot=False,
            sync_history=False,
            require_ready=False,
        )
        agent.snapshot = {"id": snapshot_id}
        agent.tools._changes["main.py"] = {
            "path": "main.py",
            "action": "edit",
        }
        payload = agent._supervisor_payload("Add a menu", "Done.")
        self.assertIn("diff", payload["changed_files"][0])
        self.assertIn("+print('changed')", payload["changed_files"][0]["diff"])
        self.assertNotIn("content", payload["changed_files"][0])


if __name__ == "__main__":
    unittest.main()
