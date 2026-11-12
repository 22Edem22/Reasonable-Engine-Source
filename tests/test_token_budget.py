"""Cost and prompt-cache regressions for the built-in agent.

The provider bill is dominated by prompt-cache misses, not by the token
counter: a fresh input token is billed about 50x higher than a cached one.
These tests replay a long tool-calling run and guard the prompt-prefix
stability that keeps later requests on the cheap cached path.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from reasonable.ai.agent import Agent
from reasonable.core.project import Project, default_manifest
from reasonable.core.settings import Settings
from reasonable.core.usage import add_usage, format_cost, load_usage


class TokenBudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "project"
        self.root.mkdir(parents=True)
        self.project = Project.create(
            self.root,
            default_manifest("Budget", goal="Guard cache stability"),
            scaffold=False,
        )
        (self.root / "main.py").write_text("print('ok')\n", encoding="utf-8")
        self.settings = Settings(path=self.root / "settings.json")
        self.settings.data["agent"]["compaction"] = False

    def _agent(self) -> Agent:
        return Agent(
            self.project,
            self.settings,
            persist_messages=False,
            seed_history=False,
            create_snapshot=False,
            sync_history=False,
            require_ready=False,
        )

    @staticmethod
    def _payload_chars(item: dict) -> int:
        chars = len(str(item.get("content") or ""))
        if item.get("tool_calls"):
            import json

            chars += len(json.dumps(item["tool_calls"], ensure_ascii=False))
        return chars

    def _cache_ratio(self, agent: Agent, steps: int = 40) -> tuple[float, int]:
        agent.messages = [
            {"role": "system", "content": "SYSTEM"},
            {"role": "user", "content": "TASK"},
        ]
        agent._task_message = agent.messages[1]
        previous: list[dict] = []
        total = 0
        cached = 0
        breaks = 0
        for index in range(steps):
            agent.messages.append(
                {
                    "role": "assistant",
                    "content": f"Step {index}",
                    "tool_calls": [
                        {
                            "id": f"call_{index}",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": "{}"},
                        }
                    ],
                }
            )
            agent.messages.append(
                {
                    "role": "tool",
                    "tool_call_id": f"call_{index}",
                    "name": "read_file",
                    "content": "x" * 6000,
                }
            )
            agent._trim_history()
            snapshot = list(agent.messages)
            prompt = agent._estimate_messages_tokens(snapshot)
            prefix = 0
            for old, new in zip(previous, snapshot):
                if old == new:
                    prefix += self._payload_chars(old)
                else:
                    break
            hit = min(prompt, int((prefix + agent._tool_schema_chars) / 3.6))
            total += prompt
            cached += hit
            if prompt and hit / prompt < 0.80:
                breaks += 1
            previous = snapshot
        return (cached / total if total else 0.0), breaks

    def test_trimming_keeps_the_prompt_prefix_cacheable(self) -> None:
        ratio, breaks = self._cache_ratio(self._agent())
        self.assertGreaterEqual(ratio, 0.75)
        self.assertLessEqual(breaks, 10)

    def test_trimming_leaves_headroom_below_the_hard_budget(self) -> None:
        agent = self._agent()
        agent._context_tokens = 8_000
        agent.messages = [
            {"role": "system", "content": "SYSTEM"},
            {"role": "user", "content": "TASK"},
        ]
        agent._task_message = agent.messages[1]
        for index in range(12):
            agent.messages.append(
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": f"c{index}",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": "{}"},
                        }
                    ],
                }
            )
            agent.messages.append(
                {
                    "role": "tool",
                    "tool_call_id": f"c{index}",
                    "name": "read_file",
                    "content": "y" * 5000,
                }
            )
        agent._trim_history()
        used = agent._estimate_messages_tokens(agent.messages)
        # 0.65 headroom plus the pinned task/summary, never the full budget.
        self.assertLess(used, 8_000)

    def test_opencode_allowance_and_cache_are_normalized(self) -> None:
        usage = Agent._usage_payload(
            {
                "prompt_tokens": 71_710,
                "completion_tokens": 310,
                "total_tokens": 72_020,
                "prompt_tokens_details": {"cached_tokens": 71_300},
                "opencode": {
                    "allowance": 0.000456,
                    "list_cost": 0.000482,
                    "billing_source": "go",
                    "tokens": {"cache_read": 71_300, "cache_write_5m": 0},
                },
            },
            1.0,
        )
        self.assertEqual(usage["prompt_tokens"], 71_710)
        self.assertEqual(usage["cached_tokens"], 71_300)
        self.assertAlmostEqual(usage["allowance"], 0.000456)
        self.assertAlmostEqual(usage["list_cost"], 0.000482)

    def test_usage_totals_accumulate_the_real_charge(self) -> None:
        add_usage(self.root, prompt_tokens=10, completion_tokens=2, allowance=0.001)
        data = add_usage(
            self.root, prompt_tokens=20, completion_tokens=3, allowance=0.002
        )
        self.assertAlmostEqual(data["allowance"], 0.003)
        self.assertAlmostEqual(load_usage(self.root)["allowance"], 0.003)

    def test_cost_is_formatted_for_small_and_large_runs(self) -> None:
        self.assertEqual(format_cost(0), "$0")
        self.assertEqual(format_cost(0.000456), "$0.000456")
        self.assertEqual(format_cost(0.0123), "$0.0123")
        self.assertEqual(format_cost(12.345), "$12.35")

    def test_aux_model_is_used_only_when_configured(self) -> None:
        config = {
            "kind": "openai",
            "base_url": "http://localhost/v1",
            "model": "main-model",
            "api_key": "test",
        }
        plain = Agent(self.project, self.settings, provider_config=dict(config))
        self.assertIsNone(plain.aux_client)

        self.settings.data["agent"]["aux_model"] = "cheap-model"
        agent = Agent(self.project, self.settings, provider_config=dict(config))
        self.assertIsNotNone(agent.aux_client)
        self.assertEqual(agent.aux_client.model, "cheap-model")
        with agent._aux_client():
            self.assertIs(agent.client, agent.aux_client)
            self.assertTrue(agent._aux_active)
        self.assertIsNot(agent.client, agent.aux_client)
        self.assertFalse(agent._aux_active)


if __name__ == "__main__":
    unittest.main()
