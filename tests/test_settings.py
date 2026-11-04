import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from reasonable.core.settings import DEFAULT_SETTINGS, Settings


@contextmanager
def _no_projects_env():
    env = {key: value for key, value in os.environ.items() if key != "REASONABLE_PROJECTS"}
    with mock.patch.dict(os.environ, env, clear=True):
        yield


class SettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.path = self.root / "settings.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_defaults_use_openrouter_and_external_images(self) -> None:
        self.assertEqual(DEFAULT_SETTINGS["version"], 2)
        self.assertEqual(DEFAULT_SETTINGS["active_provider"], "openrouter")
        self.assertEqual(DEFAULT_SETTINGS["image"]["provider"], "openai")
        self.assertEqual(DEFAULT_SETTINGS["projects_dir"], "")

    def test_pollinations_settings_are_migrated(self) -> None:
        self.path.write_text(
            json.dumps(
                {
                    "active_provider": "pollinations",
                    "provider_overrides": {"pollinations": {"model": "openai"}},
                    "image": {
                        "provider": "pollinations",
                        "base_url": "https://image.pollinations.ai/prompt",
                        "model": "flux",
                        "api_key": "secret",
                    },
                }
            ),
            encoding="utf-8",
        )
        settings = Settings(self.path)
        self.assertEqual(settings.active_provider, "openrouter")
        self.assertNotIn("pollinations", settings.data["provider_overrides"])
        image = settings.image_config()
        self.assertEqual(image["provider"], "openai")
        self.assertEqual(image["model"], "gpt-image-1")
        self.assertEqual(image["base_url"], "https://api.openai.com/v1")
        self.assertEqual(settings.data["image"]["api_key"], "")

    def test_projects_dir_defaults_inside_install_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            install = Path(tmp) / "install"
            install.mkdir()
            with _no_projects_env(), mock.patch(
                "reasonable.core.paths.install_root", return_value=install
            ):
                settings = Settings(self.path)
                self.assertEqual(settings.projects_dir(), install / "Projects")
                self.assertTrue((install / "Projects").is_dir())

    def test_projects_dir_can_be_changed_and_persisted(self) -> None:
        target = self.root / "my projects"
        settings = Settings(self.path)
        settings.set_projects_dir(target)
        self.assertEqual(settings.projects_dir(), target.resolve())
        self.assertTrue(target.is_dir())

        reloaded = Settings(self.path)
        self.assertEqual(reloaded.data["projects_dir"], str(target))

    def test_projects_dir_can_be_reset_to_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            install = Path(tmp) / "install"
            install.mkdir()
            with _no_projects_env(), mock.patch(
                "reasonable.core.paths.install_root", return_value=install
            ):
                settings = Settings(self.path)
                settings.set_projects_dir(self.root / "custom")
                settings.set_projects_dir("")
                self.assertEqual(settings.projects_dir(), install / "Projects")

    def test_remove_recent_drops_entry(self) -> None:
        project = self.root / "project"
        project.mkdir()
        settings = Settings(self.path)
        settings.touch_recent(project, {"name": "Проект", "type": "game"})
        self.assertEqual(len(settings.recent_projects()), 1)
        settings.remove_recent(project)
        self.assertEqual(settings.recent_projects(), [])

    def test_auto_continue_errors_are_saved_and_sanitized(self) -> None:
        settings = Settings(self.path)
        self.assertEqual(settings.auto_continue_kinds(), [])
        settings.set_auto_continue("server", True)
        settings.set_auto_continue("timeout", True)
        settings.set_auto_continue("not-a-kind", True)
        settings.save()
        self.assertEqual(settings.auto_continue_kinds(), ["server", "timeout"])
        self.assertTrue(settings.is_auto_continue_enabled("server"))
        self.assertFalse(settings.is_auto_continue_enabled("network"))

        reloaded = Settings(self.path)
        self.assertEqual(reloaded.auto_continue_kinds(), ["server", "timeout"])
        reloaded.set_auto_continue("server", False)
        self.assertEqual(reloaded.auto_continue_kinds(), ["timeout"])

        reloaded.data.setdefault("agent", {})["auto_continue_errors"] = [
            "server",
            "unknown",
            "timeout",
        ]
        reloaded.save()
        again = Settings(self.path)
        self.assertEqual(again.auto_continue_kinds(), ["server", "timeout"])


if __name__ == "__main__":
    unittest.main()
