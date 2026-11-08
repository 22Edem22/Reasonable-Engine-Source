import tempfile
import unittest
from pathlib import Path

from reasonable.core import i18n
from reasonable.core.usage import add_usage, format_duration, format_tokens, load_usage, usage_path


class UsageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        i18n.set_override("ru")

    def tearDown(self) -> None:
        i18n.set_override(None)

    def test_totals_accumulate_across_runs(self) -> None:
        first = add_usage(
            self.root,
            prompt_tokens=100,
            completion_tokens=40,
            total_tokens=140,
            seconds=12.5,
        )
        second = add_usage(
            self.root,
            prompt_tokens=20,
            completion_tokens=10,
            total_tokens=30,
            seconds=7.5,
        )
        self.assertEqual(first["total_tokens"], 140)
        self.assertEqual(second["total_tokens"], 170)
        self.assertEqual(second["requests"], 2)
        self.assertEqual(second["seconds"], 20.0)
        self.assertTrue(usage_path(self.root).is_file())
        self.assertEqual(load_usage(self.root)["total_tokens"], 170)

    def test_total_is_derived_when_provider_omits_it(self) -> None:
        data = add_usage(self.root, prompt_tokens=7, completion_tokens=5)
        self.assertEqual(data["total_tokens"], 12)

    def test_cached_tokens_accumulate(self) -> None:
        add_usage(
            self.root,
            prompt_tokens=100,
            completion_tokens=10,
            cached_tokens=80,
            cache_write_tokens=5,
        )
        data = add_usage(
            self.root,
            prompt_tokens=50,
            completion_tokens=5,
            cached_tokens=40,
            cache_write_tokens=3,
        )
        self.assertEqual(data["cached_tokens"], 120)
        self.assertEqual(data["cache_write_tokens"], 8)
        self.assertEqual(load_usage(self.root)["cached_tokens"], 120)

    def test_duration_is_shown_in_minutes_and_hours(self) -> None:
        self.assertEqual(format_duration(20), "меньше минуты")
        self.assertEqual(format_duration(125), "2 мин")
        self.assertEqual(format_duration(3725), "1 ч 02 мин")

    def test_token_format_uses_grouping_without_commas(self) -> None:
        self.assertEqual(format_tokens(1234567), "1\u202f234\u202f567")


if __name__ == "__main__":
    unittest.main()
