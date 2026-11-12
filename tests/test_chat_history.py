"""Regression tests for durable chat history across project reopens."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication

    PYSIDE_AVAILABLE = True
except ImportError:  # pragma: no cover - editor is optional for headless CI
    PYSIDE_AVAILABLE = False

from reasonable.ai.agent import Agent, AgentEvent
from reasonable.ai.client import ChatResult
from reasonable.core import chatlog
from reasonable.core.project import Project, default_manifest
from reasonable.core.settings import Settings


class ChatlogRoleTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_assistant_and_error_roles_survive_a_roundtrip(self) -> None:
        chatlog.append_message(self.root, "user", "Сделай меню")
        chatlog.append_message(self.root, "assistant", "Меню готово")
        chatlog.append_message(self.root, "error", "Сервер недоступен")
        chatlog.append_message(self.root, "system", "Работа остановлена")

        history = chatlog.load_chat(self.root)
        self.assertEqual(
            [item["role"] for item in history],
            ["user", "assistant", "error", "system"],
        )
        self.assertEqual(history[2]["text"], "Сервер недоступен")

    def test_identical_consecutive_messages_are_not_duplicated(self) -> None:
        chatlog.append_message(self.root, "user", "Продолжай")
        chatlog.append_message(self.root, "assistant", "Готово")
        chatlog.append_message(self.root, "assistant", "Готово")
        self.assertEqual(
            [item["text"] for item in chatlog.load_chat(self.root)],
            ["Продолжай", "Готово"],
        )


class AgentPersistenceFlagTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "project"
        self.root.mkdir(parents=True)
        self.project = Project.create(
            self.root,
            default_manifest("Chat", goal="Check",),
            scaffold=False,
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_agent_can_skip_persistence_when_the_editor_owns_the_history(self) -> None:
        agent = Agent(
            self.project,
            Settings(path=self.root / "settings.json"),
            persist_messages=False,
        )
        agent._persist_chat("hello")
        self.assertEqual(chatlog.load_chat(self.root), [])

    def test_agent_writes_the_default_history(self) -> None:
        agent = Agent(self.project, Settings(path=self.root / "settings.json"))
        agent.final_text = "All done"
        agent._persist_chat("do it")
        self.assertEqual(
            [(item["role"], item["text"]) for item in chatlog.load_chat(self.root)],
            [("user", "do it"), ("assistant", "All done")],
        )


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
class ChatPanelHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "project"
        self.root.mkdir(parents=True)
        self.project = Project.create(
            self.root,
            default_manifest("Chat", goal="Check"),
            scaffold=False,
        )
        self.settings = Settings(path=self.root / "settings.json")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_assistant_and_error_bubbles_are_saved_and_restored(self) -> None:
        from reasonable.editor.chat import ChatPanel, MessageBubble

        panel = ChatPanel(self.project, self.settings)
        panel._run_chat_id = chatlog.active_chat_id(self.root)
        panel._remember("user", "Первая задача")
        panel._on_event(AgentEvent("assistant", "Первый ответ"))
        panel._on_event(AgentEvent("error", "Ошибка сети"))

        history = chatlog.load_chat(self.root)
        self.assertEqual(
            [(item["role"], item["text"]) for item in history],
            [
                ("user", "Первая задача"),
                ("assistant", "Первый ответ"),
                ("error", "Ошибка сети"),
            ],
        )

        reopened = ChatPanel(self.project, self.settings)
        bubbles = reopened.stream_host.findChildren(MessageBubble)
        self.assertEqual(
            [(bubble.role, bubble.full_text) for bubble in bubbles],
            [
                ("user", "Первая задача"),
                ("assistant", "Первый ответ"),
                ("error", "Ошибка сети"),
            ],
        )
        from PySide6.QtCore import QEvent

        for bubble in bubbles:
            self.assertEqual(bubble.toolTip(), "")
            self.assertTrue(bubble.time_label.isHidden())
            self.assertRegex(bubble.time_label.text(), r"\d{2}:\d{2}")

        fresh = reopened._append("user", "Ещё одно сообщение")
        self.assertRegex(fresh.time_label.text(), r"\d{2}:\d{2}")
        self.assertTrue(fresh.time_label.isHidden())
        before = fresh.sizeHint().height()
        fresh.eventFilter(fresh.body, QEvent(QEvent.Type.Enter))
        self.app.processEvents()
        self.assertFalse(fresh.time_label.isHidden())
        # The caption lives in the header row, so hovering must not resize the
        # bubble and shift the conversation under the pointer.
        self.assertEqual(fresh.sizeHint().height(), before)

    def test_agent_run_with_skipped_persistence_keeps_ui_messages(self) -> None:
        from reasonable.editor.chat import ChatPanel

        panel = ChatPanel(self.project, self.settings)
        panel._run_chat_id = chatlog.active_chat_id(self.root)
        agent = Agent(
            self.project,
            self.settings,
            chat_id=panel._run_chat_id,
            persist_messages=False,
        )
        agent.final_text = "Ответ"
        panel._remember("user", "Задача")
        agent._persist_chat("Задача")
        panel._remember("assistant", "Ответ")
        self.assertEqual(
            [item["text"] for item in chatlog.load_chat(self.root)],
            ["Задача", "Ответ"],
        )


if __name__ == "__main__":
    unittest.main()
