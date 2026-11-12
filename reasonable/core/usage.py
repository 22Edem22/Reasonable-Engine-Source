"""Durable cumulative AI usage for a project.

The editor shows a live counter in the built-in agent chat. It must survive
restarts and new agent runs, so totals live next to the chat history:

    <project>/.reasonable/agent_usage.json

Only token counts, request count and generation seconds are stored — never
prompts or model replies.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from .i18n import t
from .paths import atomic_write_json, now_iso, read_json

FILE_NAME = "agent_usage.json"
_LOCK = threading.RLock()


def usage_path(project_dir: Path) -> Path:
    return Path(project_dir) / ".reasonable" / FILE_NAME


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0


def empty_usage() -> dict[str, Any]:
    return {
        "total_tokens": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cached_tokens": 0,
        "cache_write_tokens": 0,
        "allowance": 0.0,
        "list_cost": 0.0,
        "requests": 0,
        "seconds": 0.0,
        "updated": "",
    }


def load_usage(project_dir: Path) -> dict[str, Any]:
    data = read_json(usage_path(project_dir), None)
    result = empty_usage()
    if isinstance(data, dict):
        result.update(
            {
                "total_tokens": _safe_int(data.get("total_tokens")),
                "prompt_tokens": _safe_int(data.get("prompt_tokens")),
                "completion_tokens": _safe_int(data.get("completion_tokens")),
                "cached_tokens": _safe_int(data.get("cached_tokens")),
                "cache_write_tokens": _safe_int(data.get("cache_write_tokens")),
                "allowance": round(_safe_float(data.get("allowance")), 8),
                "list_cost": round(_safe_float(data.get("list_cost")), 8),
                "requests": _safe_int(data.get("requests")),
                "seconds": round(_safe_float(data.get("seconds")), 3),
                "updated": str(data.get("updated") or ""),
            }
        )
    return result


def add_usage(
    project_dir: Path,
    *,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int | None = None,
    cached_tokens: int = 0,
    cache_write_tokens: int = 0,
    allowance: float = 0.0,
    list_cost: float = 0.0,
    seconds: float = 0.0,
    requests: int = 1,
) -> dict[str, Any]:
    """Add one model call to the project's lifetime totals and persist it."""
    prompt = _safe_int(prompt_tokens)
    completion = _safe_int(completion_tokens)
    total = _safe_int(total_tokens)
    if total <= 0:
        total = prompt + completion
    with _LOCK:
        data = load_usage(project_dir)
        data["prompt_tokens"] += prompt
        data["completion_tokens"] += completion
        data["cached_tokens"] += _safe_int(cached_tokens)
        data["cache_write_tokens"] += _safe_int(cache_write_tokens)
        data["allowance"] = round(
            float(data.get("allowance") or 0.0) + _safe_float(allowance), 8
        )
        data["list_cost"] = round(
            float(data.get("list_cost") or 0.0) + _safe_float(list_cost), 8
        )
        data["total_tokens"] += total
        data["requests"] += _safe_int(requests)
        data["seconds"] = round(float(data.get("seconds") or 0.0) + _safe_float(seconds), 3)
        data["updated"] = now_iso()
        path = usage_path(project_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, data)
    return data


def format_duration(seconds: float) -> str:
    """Human duration rounded down to whole minutes/hours."""
    minutes = int(max(0.0, float(seconds or 0.0)) // 60)
    if minutes < 1:
        return t("chat.time_less_minute")
    if minutes < 60:
        return t("chat.time_minutes", minutes=minutes)
    hours, rest = divmod(minutes, 60)
    return t("chat.time_hours_minutes", hours=hours, minutes=rest)


def format_tokens(count: int) -> str:
    """Group digits with non-breaking spaces for a compact UI label."""
    return f"{max(0, int(count or 0)):,}".replace(",", "\u202f")


def format_cost(amount: float) -> str:
    """Small, honest dollar label for one project's lifetime AI spend.

    Sub-cent values keep enough digits to be useful; rounding everything to
    ``$0.00`` would hide the cost of short runs.
    """
    value = max(0.0, float(amount or 0.0))
    if value >= 1:
        return f"${value:,.2f}"
    if value >= 0.01:
        return f"${value:.4f}"
    if value > 0:
        return f"${value:.6f}"
    return "$0"
