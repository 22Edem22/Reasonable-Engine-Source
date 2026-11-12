"""Measure what the built-in agent actually sends to a provider — and costs.

This is a deterministic, offline benchmark: it replays a long tool-calling run
against the real trimming/compaction code, captures every request payload the
agent would send, and models provider prompt caching as a longest-common-prefix
of consecutive requests.

Why it exists
-------------
OpenCode Go bills cached input roughly 50x cheaper than fresh input
(DeepSeek V4.1 Flash: $0.003 vs $0.15 per 1M tokens). Trimming one message per
step therefore looks harmless in a token counter but multiplies the real bill.
The benchmark reports:

* prompt tokens per request,
* how many of them hit the cache,
* the number of "cache breaks",
* the modeled OpenCode allowance (dollars).

Run it from the repository root:

    python tools/token_bench.py
    python tools/token_bench.py --steps 120 --json
    python tools/token_bench.py --cache-first
    python tools/token_bench.py --price-in 0.30 --price-out 1.20   # peak hours

The numbers are an estimate: the model's real tokenizer and the provider's
cache block granularity differ. They are stable enough to compare two versions
of the agent and to guard against regressions.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reasonable.ai.agent import Agent  # noqa: E402
from reasonable.ai.prompts import (  # noqa: E402
    build_agent_system_prompt,
    build_initial_user_message,
)
from reasonable.core.project import Project, default_manifest  # noqa: E402
from reasonable.core.settings import Settings  # noqa: E402

# USD per 1M tokens. Off-peak OpenCode Go prices; --peak switches the flash row.
PRICES = {
    "deepseek-v4.1-flash": (0.15, 0.003, 0.60),
    "deepseek-v4.1-flash-peak": (0.30, 0.006, 1.20),
    "deepseek-v4-pro": (0.66, 0.022, 1.98),
    "glm-5.3-flash": (0.15, 0.03, 0.50),
}


def _payload_chars(item: dict) -> int:
    chars = len(str(item.get("content") or ""))
    if item.get("tool_calls"):
        chars += len(json.dumps(item["tool_calls"], ensure_ascii=False))
    return chars


def _common_prefix_chars(previous: list[dict], current: list[dict]) -> int:
    total = 0
    for old, new in zip(previous, current):
        if old == new:
            total += _payload_chars(old)
        else:
            break
    return total


def _make_project(root: Path) -> Project:
    project = Project.create(
        root,
        default_manifest("Token bench", goal="Measure the agent's request cost"),
        scaffold=False,
    )
    (root / "main.py").write_text(
        "\n".join(f"def step_{i}():\n    return {i}" for i in range(120)) + "\n",
        encoding="utf-8",
    )
    (root / "game.py").write_text("print('ok')\n", encoding="utf-8")
    return project


def run(
    steps: int,
    tool_chars: int,
    out_tokens: int,
    headroom: float,
    context_tokens: int = 48_000,
    context_chars: int = 120_000,
    context_messages: int = 36,
) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "project"
        root.mkdir(parents=True)
        project = _make_project(root)
        settings = Settings(path=root / "settings.json")
        settings.data["agent"]["compaction"] = False
        settings.data["agent"]["context_tokens"] = context_tokens
        settings.data["agent"]["context_chars"] = context_chars
        settings.data["agent"]["context_messages"] = context_messages
        agent = Agent(
            project,
            settings,
            persist_messages=False,
            seed_history=False,
            create_snapshot=False,
            sync_history=False,
            require_ready=False,
        )
        agent._trim_headroom = headroom
        agent._context_tokens = context_tokens
        agent._context_chars = context_chars
        system = build_agent_system_prompt(project)
        agent.messages = [{"role": "system", "content": system}]
        agent.messages.append(
            {
                "role": "user",
                "content": "Implement the task.\n\n"
                + build_initial_user_message(project),
            }
        )
        agent._task_message = agent.messages[-1]
        schema_tokens = int(agent._tool_schema_chars / 3.6) if agent._tool_schema_chars else 0

        records: list[dict] = []
        previous: list[dict] = []
        for index in range(steps):
            agent.messages.append(
                {
                    "role": "assistant",
                    "content": f"Step {index}: reading a file.",
                    "tool_calls": [
                        {
                            "id": f"call_{index}",
                            "type": "function",
                            "function": {
                                "name": "read_file",
                                "arguments": json.dumps({"path": "main.py"}),
                            },
                        }
                    ],
                }
            )
            agent.messages.append(
                {
                    "role": "tool",
                    "tool_call_id": f"call_{index}",
                    "name": "read_file",
                    "content": "x" * tool_chars,
                }
            )
            agent._trim_history()
            snapshot = list(agent.messages)

            prompt_tokens = agent._estimate_messages_tokens(snapshot)
            prefix_chars = _common_prefix_chars(previous, snapshot)
            cached_tokens = min(prompt_tokens, int((prefix_chars + agent._tool_schema_chars) / 3.6))
            cached_tokens = min(cached_tokens, prompt_tokens)
            records.append(
                {
                    "step": index + 1,
                    "messages": len(snapshot),
                    "prompt_tokens": prompt_tokens,
                    "cached_tokens": cached_tokens,
                    "new_tokens": max(0, prompt_tokens - cached_tokens),
                }
            )
            previous = snapshot

    total_prompt = sum(r["prompt_tokens"] for r in records)
    total_cached = sum(r["cached_tokens"] for r in records)
    total_new = sum(r["new_tokens"] for r in records)
    total_out = out_tokens * len(records)
    breaks = sum(
        1
        for r in records
        if r["prompt_tokens"] and r["cached_tokens"] / r["prompt_tokens"] < 0.80
    )
    return {
        "steps": len(records),
        "headroom": headroom,
        "schema_tokens": schema_tokens,
        "total_prompt": total_prompt,
        "total_cached": total_cached,
        "total_new": total_new,
        "total_out": total_out,
        "cache_ratio": (total_cached / total_prompt) if total_prompt else 0.0,
        "cache_breaks": breaks,
        "peak_prompt": max((r["prompt_tokens"] for r in records), default=0),
        "records": records,
    }


def _cost(result: dict, prices: tuple[float, float, float]) -> dict:
    price_in, price_cached, price_out = prices
    fresh = result["total_new"] / 1_000_000 * price_in
    cached = result["total_cached"] / 1_000_000 * price_cached
    out = result["total_out"] / 1_000_000 * price_out
    return {
        "fresh": fresh,
        "cached": cached,
        "output": out,
        "total": fresh + cached + out,
    }


def _print(label: str, result: dict, cost: dict) -> None:
    print(
        f"{label:<18} requests={result['steps']:>3}  "
        f"prompt={result['total_prompt']:>9,}  "
        f"cached={result['cache_ratio'] * 100:>5.1f}%  "
        f"breaks={result['cache_breaks']:>3}  "
        f"peak={result['peak_prompt']:>7,}  "
        f"cost=${cost['total']:.4f}"
    )
    print(
        f"{'':<18} fresh=${cost['fresh']:.4f}  cached=${cost['cached']:.4f}  "
        f"output=${cost['output']:.4f}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", type=int, default=60)
    parser.add_argument("--tool-chars", type=int)
    parser.add_argument("--out-tokens", type=int, default=300)
    parser.add_argument("--context-tokens", type=int)
    parser.add_argument("--context-chars", type=int)
    parser.add_argument("--context-messages", type=int)
    parser.add_argument(
        "--cache-first",
        action="store_true",
        help="model the DeepSeek V4.1 cache profile: 100k context, 160 messages, 4.5k tool output",
    )
    parser.add_argument("--model", default="deepseek-v4.1-flash", choices=sorted(PRICES))
    parser.add_argument("--price-in", type=float)
    parser.add_argument("--price-cached", type=float)
    parser.add_argument("--price-out", type=float)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    prices = PRICES[args.model]
    if args.cache_first:
        tool_chars = args.tool_chars or 4_500
        context_tokens = args.context_tokens or 110_000
        context_chars = args.context_chars or 460_000
        context_messages = args.context_messages or 160
    else:
        tool_chars = args.tool_chars or 6_000
        context_tokens = args.context_tokens or 48_000
        context_chars = args.context_chars or 120_000
        context_messages = args.context_messages or 36
    if args.price_in is not None or args.price_cached is not None or args.price_out is not None:
        prices = (
            prices[0] if args.price_in is None else args.price_in,
            prices[1] if args.price_cached is None else args.price_cached,
            prices[2] if args.price_out is None else args.price_out,
        )

    before = run(
        args.steps,
        tool_chars,
        args.out_tokens,
        headroom=1.0,
        context_tokens=context_tokens,
        context_chars=context_chars,
        context_messages=context_messages,
    )
    after = run(
        args.steps,
        tool_chars,
        args.out_tokens,
        headroom=0.65,
        context_tokens=context_tokens,
        context_chars=context_chars,
        context_messages=context_messages,
    )
    before_cost = _cost(before, prices)
    after_cost = _cost(after, prices)

    if args.json:
        payload = {
            "model": args.model,
            "prices": {
                "input": prices[0],
                "cached": prices[1],
                "output": prices[2],
            },
            "before": {**before, "cost": before_cost},
            "after": {**after, "cost": after_cost},
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(f"Token benchmark - {args.model}, {args.steps} requests, "
          f"{tool_chars} chars of tool output per step")
    print(f"Modeled prices per 1M tokens: input ${prices[0]}, "
          f"cached ${prices[1]}, output ${prices[2]}")
    _print("trim to limit", before, before_cost)
    _print("trim with headroom", after, after_cost)
    if before_cost["total"] > 0:
        saved = 1 - after_cost["total"] / before_cost["total"]
        print(f"\nEstimated saving: {saved * 100:.1f}%")
    print(f"Cache breaks: {before['cache_breaks']} -> {after['cache_breaks']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
