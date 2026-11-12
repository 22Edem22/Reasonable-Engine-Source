"""Guards for the RU/EN translation table.

These checks catch the two mistakes that are invisible at runtime: a
placeholder exists in one language but not the other, and a call site refers to
a key that no longer exists (``t()`` silently returns the key text).
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

from reasonable.core.i18n import TRANSLATIONS

ROOT = Path(__file__).resolve().parent.parent
CYRILLIC = re.compile(r"[\u0400-\u04FF]")
KEY_RE = re.compile(r"[a-z0-9_]+\.[a-z0-9_.]+")


def _pair(value) -> tuple[str | None, str | None]:
    if isinstance(value, dict):
        return value.get("ru"), value.get("en")
    if isinstance(value, (tuple, list)) and len(value) == 2:
        return value[0], value[1]
    return None, None


class TranslationTableTests(unittest.TestCase):
    def test_placeholders_match_between_languages(self) -> None:
        mismatches: list[str] = []
        for key, value in TRANSLATIONS.items():
            ru, en = _pair(value)
            if ru is None or en is None:
                continue
            ru_fields = sorted(re.findall(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", ru))
            en_fields = sorted(re.findall(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", en))
            if ru_fields != en_fields:
                mismatches.append(f"{key}: ru={ru_fields} en={en_fields}")
        self.assertEqual(mismatches, [], "Placeholder mismatch:\n" + "\n".join(mismatches))

    def test_table_has_no_duplicate_keys(self) -> None:
        source = (ROOT / "reasonable/core/i18n.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        table = None
        for node in ast.walk(tree):
            if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "TRANSLATIONS":
                table = node.value
        self.assertIsNotNone(table, "TRANSLATIONS assignment not found")
        keys = [ast.literal_eval(key) for key in table.keys]
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        self.assertEqual(duplicates, [], f"Duplicate translation keys: {duplicates}")

    def test_new_keys_use_ascii_prefixes(self) -> None:
        """Legacy ``tools.<russian text>`` keys are tolerated; nothing new is."""
        legacy: list[str] = []
        bad: list[str] = []
        for key in TRANSLATIONS:
            if KEY_RE.fullmatch(key):
                continue
            if key.startswith("tools.") and CYRILLIC.search(key):
                legacy.append(key)
                continue
            bad.append(key)
        self.assertEqual(bad, [], f"Non-standard translation keys: {bad}")

    def test_literal_call_sites_have_keys(self) -> None:
        used: dict[str, str] = {}
        pattern = re.compile(r"(?<![\w.])t\(\s*[\"']([^\"']+)[\"']")
        for path in (ROOT / "reasonable").rglob("*.py"):
            if path.name == "i18n.py" or "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for match in pattern.finditer(text):
                used.setdefault(match.group(1), str(path.relative_to(ROOT)))
        missing = {key: where for key, where in used.items() if key not in TRANSLATIONS}
        self.assertEqual(missing, {}, f"Missing translation keys: {missing}")


if __name__ == "__main__":
    unittest.main()
