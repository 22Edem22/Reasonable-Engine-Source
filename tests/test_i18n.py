"""Tests for the bilingual UI layer and the English-only agent material."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from reasonable.core import i18n


class LanguageResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._old_home = os.environ.get("REASONABLE_HOME")
        self._old_lang = os.environ.get("REASONABLE_LANG")
        os.environ["REASONABLE_HOME"] = self._tmp.name
        os.environ.pop("REASONABLE_LANG", None)
        i18n.set_override(None)
        i18n.invalidate_cache() if hasattr(i18n, "invalidate_cache") else None
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        if self._old_home is None:
            os.environ.pop("REASONABLE_HOME", None)
        else:
            os.environ["REASONABLE_HOME"] = self._old_home
        if self._old_lang is None:
            os.environ.pop("REASONABLE_LANG", None)
        else:
            os.environ["REASONABLE_LANG"] = self._old_lang
        i18n.set_override(None)

    def _write_settings(self, language: str) -> None:
        path = Path(self._tmp.name) / "settings.json"
        path.write_text(json.dumps({"ui": {"language": language}}), encoding="utf-8")

    def test_default_is_russian(self) -> None:
        self.assertEqual(i18n.current_language(), "ru")

    def test_settings_language_is_honoured(self) -> None:
        self._write_settings("en")
        # Bypass the settings cache if present.
        if hasattr(i18n, "clear_caches"):
            i18n.clear_caches()
        elif hasattr(i18n, "_CACHED_SETTINGS_LANGUAGE"):
            i18n._CACHED_SETTINGS_LANGUAGE = None
            i18n._CACHED_SETTINGS_PATH = None
        self.assertEqual(i18n.current_language(), "en")

    def test_env_overrides_settings(self) -> None:
        self._write_settings("en")
        os.environ["REASONABLE_LANG"] = "ru"
        if hasattr(i18n, "clear_caches"):
            i18n.clear_caches()
        self.assertEqual(i18n.current_language(), "ru")

    def test_normalize_language(self) -> None:
        for value in ("RU", "russian", "ru-RU", "Русский"):
            self.assertEqual(i18n.normalize_language(value), "ru", value)
        for value in ("EN", "english", "en-US", "English"):
            self.assertEqual(i18n.normalize_language(value), "en", value)
        self.assertEqual(i18n.normalize_language(None), "ru")
        self.assertEqual(i18n.normalize_language("klingon"), "ru")


class TranslationTests(unittest.TestCase):
    def tearDown(self) -> None:
        i18n.set_override(None)

    def test_t_switches_by_language(self) -> None:
        key = next(iter(i18n.TRANSLATIONS))
        table = i18n.TRANSLATIONS[key]
        if "ru" not in table or "en" not in table:
            self.skipTest("pair missing")
        i18n.set_override("ru")
        ru = i18n.t(key)
        i18n.set_override("en")
        en = i18n.t(key)
        self.assertEqual(ru, table["ru"])
        self.assertEqual(en, table["en"])

    def test_missing_key_falls_back_to_key_text(self) -> None:
        i18n.set_override("en")
        self.assertEqual(i18n.t("some.unknown.key"), "some.unknown.key")

    def test_interpolation(self) -> None:
        i18n.set_override("en")
        out = i18n.t("external.readme_header", name="Space Cat")
        self.assertIn("Space Cat", out)
        self.assertIn("External agent", out)
        i18n.set_override("ru")
        out_ru = i18n.t("external.readme_header", name="Космический кот")
        self.assertIn("Космический кот", out_ru)
        self.assertIn("Внешний агент", out_ru)


class DetectUserLanguageTests(unittest.TestCase):
    def test_cyrillic_task_is_russian(self) -> None:
        self.assertEqual(i18n.detect_user_language("Сделай игру про кота"), "ru")

    def test_latin_task_is_english(self) -> None:
        self.assertEqual(i18n.detect_user_language("Make a game about a cat"), "en")

    def test_empty_defaults_to_russian(self) -> None:
        self.assertEqual(i18n.detect_user_language(""), "ru")


class InstallerLanguageTests(unittest.TestCase):
    """The installer writes an ASCII marker; the app merges it into settings.json."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._old_home = os.environ.get("REASONABLE_HOME")
        self._old_lang = os.environ.get("REASONABLE_LANG")
        os.environ["REASONABLE_HOME"] = self._tmp.name
        os.environ.pop("REASONABLE_LANG", None)
        i18n.set_override(None)
        i18n.invalidate_cache()
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        if self._old_home is None:
            os.environ.pop("REASONABLE_HOME", None)
        else:
            os.environ["REASONABLE_HOME"] = self._old_home
        if self._old_lang is None:
            os.environ.pop("REASONABLE_LANG", None)
        else:
            os.environ["REASONABLE_LANG"] = self._old_lang
        i18n.set_override(None)
        i18n.invalidate_cache()

    def _marker_path(self) -> Path:
        return Path(self._tmp.name) / i18n.INSTALLER_LANGUAGE_MARKER

    def _write_marker(self, language: str) -> None:
        self._marker_path().write_text(language, encoding="ascii")

    def test_marker_is_read_when_settings_have_no_language(self) -> None:
        self._write_marker("en")
        self.assertEqual(i18n.read_installer_language(), "en")
        self.assertEqual(i18n.current_language(), "en")

    def test_explicit_settings_language_wins_over_marker(self) -> None:
        self._write_marker("en")
        (Path(self._tmp.name) / "settings.json").write_text(
            json.dumps({"ui": {"language": "ru"}}), encoding="utf-8"
        )
        i18n.invalidate_cache()
        self.assertEqual(i18n.current_language(), "ru")

    def test_settings_load_consumes_marker(self) -> None:
        from reasonable.core.settings import Settings

        self._write_marker("en")
        settings = Settings()
        self.assertEqual(settings.language(), "en")
        self.assertFalse(self._marker_path().exists())
        stored = json.loads((Path(self._tmp.name) / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["ui"]["language"], "en")
        # The choice survives restarts without the marker.
        self.assertEqual(Settings().language(), "en")

    def test_missing_marker_defaults_to_russian(self) -> None:
        self.assertEqual(i18n.read_installer_language(), "")
        self.assertEqual(i18n.current_language(), "ru")


class AgentMaterialEnglishOnlyTests(unittest.TestCase):
    """Skills, tool schemas and guides fed to the AI must be English-only."""

    def test_skills_are_english(self) -> None:
        from reasonable.ai.prompts import SKILLS

        self.assertTrue(SKILLS)
        for name, text in SKILLS.items():
            self.assertFalse(
                any("\u0410" <= ch <= "\u044f" for ch in text),
                f"skill {name} contains Cyrillic",
            )

    def test_system_prompt_mentions_user_language_rule(self) -> None:
        from reasonable.ai.prompts import AGENT_SYSTEM_PROMPT

        lowered = AGENT_SYSTEM_PROMPT.lower()
        self.assertIn("language", lowered)
        self.assertNotIn("по-русски", AGENT_SYSTEM_PROMPT)

    def test_tool_schemas_have_no_cyrillic(self) -> None:
        from reasonable.ai.tools import TOOL_SCHEMAS

        blob = json.dumps(TOOL_SCHEMAS, ensure_ascii=False)
        self.assertFalse(
            any("\u0410" <= ch <= "\u044f" for ch in blob),
            "TOOL_SCHEMAS must be English-only",
        )


if __name__ == "__main__":
    unittest.main()
