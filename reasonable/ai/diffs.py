"""Compact file diffs for independent agent audits.

The completion auditor used to receive the full current text of every changed
file. That is both expensive and redundant: the auditor only needs to see what
changed. This module builds a bounded unified diff against the pre-run
snapshot, so an audit stays cheap without hiding the actual edit.

When no snapshot exists (for example a caller disabled snapshots), the helper
falls back to the old content behaviour so the auditor is never left blind.
"""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any, Iterable

from reasonable.core.history import snapshot_text

DEFAULT_FILE_LIMIT = 2600
DEFAULT_TOTAL_LIMIT = 12000
DEFAULT_FALLBACK_LIMIT = 5000
BINARY_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".ico",
    ".wav",
    ".ogg",
    ".mp3",
    ".ttf",
    ".otf",
    ".zip",
    ".exe",
}


def _normalise(text: str | None) -> str:
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n")


def unified_diff(
    old: str | None,
    new: str | None,
    path: str,
    *,
    context: int = 2,
) -> str:
    """Unified diff with a small amount of surrounding context."""
    before = _normalise(old)
    after = _normalise(new)
    if before == after:
        return ""
    lines = difflib.unified_diff(
        before.splitlines(),
        after.splitlines(),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        n=max(0, int(context)),
        lineterm="",
    )
    return "\n".join(lines)


def _trim(text: str, limit: int, marker: str) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[: max(0, limit)] + f"\n... [{marker}] ...", True


def changed_files_payload(
    project: Any,
    snapshot_id: str | None,
    changed_files: Iterable[dict[str, Any]],
    *,
    file_limit: int = DEFAULT_FILE_LIMIT,
    total_limit: int = DEFAULT_TOTAL_LIMIT,
    fallback_limit: int = DEFAULT_FALLBACK_LIMIT,
) -> list[dict[str, Any]]:
    """Build the audit payload: diffs when possible, bounded content otherwise.

    Each entry has ``path``, ``action`` and either ``diff`` or ``content``.
    The result respects a total character budget so a single huge generated
    file cannot push the task itself out of the auditor's context.
    """
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    remaining = max(0, int(total_limit))
    use_diffs = bool(str(snapshot_id or "").strip())
    for item in changed_files:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").replace("\\", "/").strip()
        if not path or path in seen:
            continue
        seen.add(path)
        action = str(item.get("action") or "edit")
        if Path(path).suffix.lower() in BINARY_SUFFIXES:
            # A text diff of a PNG is noise; the auditor only needs to know it
            # was generated or removed.
            entries.append(
                {
                    "path": path,
                    "action": action,
                    "note": "binary asset",
                    "size": item.get("size"),
                }
            )
            continue
        try:
            current = project.read_text(path)
        except Exception:
            current = None

        if not use_diffs:
            # No baseline: keep the previous behaviour instead of guessing.
            text = _normalise(current)
            text, truncated = _trim(text, min(file_limit, fallback_limit), "content truncated")
            if not text:
                continue
            budget = min(len(text), remaining)
            text, budget_cut = _trim(text, budget, "budget exhausted")
            truncated = truncated or budget_cut
            remaining -= len(text)
            entries.append(
                {
                    "path": path,
                    "action": action,
                    "content": text,
                    "truncated": truncated,
                }
            )
            if remaining <= 0:
                break
            continue

        before = snapshot_text(project, str(snapshot_id), path)
        if before is None and current is None:
            continue
        diff = unified_diff(before, current, path)
        if not diff:
            continue
        diff, truncated = _trim(diff, min(file_limit, remaining), "diff truncated")
        remaining -= len(diff)
        entries.append(
            {
                "path": path,
                "action": action,
                "diff": diff,
                "truncated": truncated,
            }
        )
        if remaining <= 0:
            break
    return entries
