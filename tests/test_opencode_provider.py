"""OpenCode Go provider: endpoint, session header and model list."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from reasonable.ai.agent import Agent
from reasonable.ai.client import AIClient
from reasonable.ai.providers import get_provider, merge_provider_config
from reasonable.core.project import Project, default_manifest
from reasonable.core.settings import Settings


class OpenCodeProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "project"
        self.root.mkdir(parents=True)
        self.settings = Settings(path=self.root / "settings.json")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_preset_uses_go_openai_endpoint_and_model_list(self) -> None:
        preset = get_provider("opencode")
        self.assertEqual(preset.display_name, "OpenCode Go")
        self.assertTrue(preset.requires_key)
        self.assertTrue(preset.base_url.endswith("/inference/go/openai/v1"))
        self.assertEqual(
            preset.models_url,
            "https://opencode.ai/inference/go/v1/models",
        )

        config = merge_provider_config(self.settings, "opencode")
        self.assertEqual(config["models_url"], preset.models_url)
        self.assertEqual(config["default_model"] if "default_model" in config else config["model"], preset.default_model)
        client = AIClient(config)
        self.assertEqual(
            client._chat_url(),
            "https://opencode.ai/inference/go/openai/v1/chat/completions",
        )
        self.assertEqual(client._models_url(), preset.models_url)

    def test_client_identifies_itself_and_sends_a_session(self) -> None:
        config = merge_provider_config(self.settings, "opencode")
        config["api_key"] = "oc_sk_test"
        client = AIClient(config)
        headers = client._auth_headers()
        self.assertTrue(headers["User-Agent"].startswith("ReasonableEngine/"))
        self.assertTrue(headers["x-opencode-session"])
        self.assertEqual(headers["Authorization"], "Bearer oc_sk_test")

    def test_custom_opencode_base_url_also_gets_the_session_header(self) -> None:
        client = AIClient(
            {
                "kind": "openai",
                "base_url": "https://opencode.ai/inference/go/openai/v1",
                "model": "deepseek-v4.1-flash",
                "api_key": "oc_sk_test",
            }
        )
        self.assertIn("x-opencode-session", client._auth_headers())

    def test_agent_reuses_the_chat_id_as_a_stable_session(self) -> None:
        self.settings.data["active_provider"] = "opencode"
        project = Project.create(
            self.root,
            default_manifest("Go", goal="Test"),
            scaffold=False,
        )
        agent = Agent(project, self.settings, chat_id="chat_abc123")
        self.assertEqual(
            agent.client.headers["x-opencode-session"],
            "reasonable-chat_abc123",
        )

    def test_non_opencode_providers_do_not_receive_the_session_header(self) -> None:
        client = AIClient(
            {
                "kind": "openai",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4.1-mini",
                "api_key": "sk-test",
            }
        )
        self.assertNotIn("x-opencode-session", client._auth_headers())


if __name__ == "__main__":
    unittest.main()
