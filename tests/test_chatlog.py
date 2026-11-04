import json
import tempfile
import unittest
from pathlib import Path

from reasonable.core.chatlog import (
    active_chat_id,
    append_message,
    clear_chat,
    create_chat,
    delete_chat,
    list_chats,
    load_chat,
    recent_messages,
    set_active_chat,
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

    def test_multiple_chats_keep_separate_histories(self) -> None:
        first = create_chat(self.root, "Первый чат")
        append_message(self.root, "user", "Сделай меню")
        append_message(self.root, "assistant", "Меню готово")
        second = create_chat(self.root, "Второй чат")
        append_message(self.root, "user", "Добавь звук")

        self.assertEqual(active_chat_id(self.root), second["id"])
        self.assertEqual(
            [item["text"] for item in load_chat(self.root, first["id"])],
            ["Сделай меню", "Меню готово"],
        )
        self.assertEqual(
            [item["text"] for item in load_chat(self.root, second["id"])],
            ["Добавь звук"],
        )
        self.assertEqual(
            [chat["title"] for chat in list_chats(self.root) if chat["title"]],
            ["Первый чат", "Второй чат"],
        )

        set_active_chat(self.root, first["id"])
        self.assertEqual(active_chat_id(self.root), first["id"])
        self.assertEqual(
            [item["text"] for item in recent_messages(self.root, limit=1)],
            ["Меню готово"],
        )

    def test_hidden_messages_stay_in_context_but_are_marked(self) -> None:
        chat = create_chat(self.root, "Улучшения")
        append_message(self.root, "user", "secret review prompt", chat_id=chat["id"], hidden=True)
        append_message(self.root, "assistant", "Видимый ответ", chat_id=chat["id"])
        history = load_chat(self.root, chat["id"])
        self.assertTrue(history[0]["hidden"])
        self.assertFalse(history[1]["hidden"])

    def test_delete_chat_switches_to_a_neighbor_and_keeps_one(self) -> None:
        first = create_chat(self.root, "Первый")
        second = create_chat(self.root, "Второй")
        append_message(self.root, "user", "текст", chat_id=second["id"])
        count_before = len(list_chats(self.root))

        after = delete_chat(self.root, second["id"])
        self.assertEqual(after["id"], first["id"])
        self.assertEqual(active_chat_id(self.root), first["id"])
        self.assertEqual(len(list_chats(self.root)), count_before - 1)

        while len(list_chats(self.root)) > 1:
            delete_chat(self.root, active_chat_id(self.root))
        self.assertEqual(len(list_chats(self.root)), 1)
        last = list_chats(self.root)[0]
        delete_chat(self.root, last["id"])
        self.assertEqual(len(list_chats(self.root)), 1)
        self.assertEqual(load_chat(self.root), [])

    def test_legacy_single_chat_file_is_migrated(self) -> None:
        path = self.root / ".reasonable" / "chat.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                [
                    {"ts": "2026-01-01T10:00:00", "role": "user", "text": "Старая задача"},
                    {"ts": "2026-01-01T10:01:00", "role": "assistant", "text": "Старый ответ"},
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        history = load_chat(self.root)
        self.assertEqual([item["text"] for item in history], ["Старая задача", "Старый ответ"])
        self.assertFalse(any(item.get("hidden") for item in history))
        self.assertEqual(list_chats(self.root)[0]["title"], "Старая задача")

        append_message(self.root, "user", "Новая задача")
        raw = json.loads(path.read_text(encoding="utf-8"))
        self.assertIsInstance(raw, dict)
        self.assertEqual(raw["version"], 2)
        self.assertEqual(len(raw["chats"]), 1)

if __name__ == "__main__":
    unittest.main()
