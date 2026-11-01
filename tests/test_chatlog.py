import tempfile
import unittest
from pathlib import Path

from reasonable.core.chatlog import (
    append_message,
    clear_chat,
    load_chat,
    recent_messages,
)


class ChatlogTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        # remove any stale file so each test starts empty
        clear_chat(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_append_and_load_roundtrip(self) -> None:
        append_message(self.root, "user", "Сделай меню")
        append_message(self.root, "assistant", "Меню готово")
        history = load_chat(self.root)
        self.assertEqual([item["role"] for item in history], ["user", "assistant"])
        self.assertEqual(history[0]["text"], "Сделай меню")
        self.assertEqual(history[1]["text"], "Меню готово")
        self.assertTrue(all(item.get("ts") for item in history))

    def test_recent_messages_limits(self) -> None:
        for index in range(8):
            append_message(self.root, "user", f"сообщение {index}")
        recent = recent_messages(self.root, limit=3)
        self.assertEqual([item["text"] for item in recent], ["сообщение 5", "сообщение 6", "сообщение 7"])

    def test_clear_chat(self) -> None:
        append_message(self.root, "user", "привет")
        clear_chat(self.root)
        self.assertEqual(load_chat(self.root), [])

    def test_history_file_lives_in_project(self) -> None:
        append_message(self.root, "user", "задача")
        self.assertTrue((self.root / ".reasonable" / "chat.json").is_file())


if __name__ == "__main__":
    unittest.main()
