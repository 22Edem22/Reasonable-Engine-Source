"""Error categories that can trigger an automatic "Continue" for the agent.

A repeated server-side failure does not mean the task is impossible: the model
may resume where it stopped once the provider recovers. The editor offers a
manual "Continue" button for those errors and lets the user opt into sending it
automatically. Only transient/server-side categories belong here: repeated
authentication or bad-request errors would just waste requests.
"""

from __future__ import annotations

# Ordered list of categories shown in the settings dialog.
AUTO_CONTINUE_KINDS: tuple[str, ...] = (
    "server",
    "rate_limit",
    "timeout",
    "network",
    "bad_response",
)

_REQUEST_STATUSES = {400, 401, 402, 403, 404, 408, 409, 413, 422}


def http_error_kind(status: int) -> str:
    """Category for an HTTP response from the AI provider."""
    if status == 408:
        return "timeout"
    if status == 429:
        return "rate_limit"
    if 500 <= status <= 599:
        return "server"
    return "request"


def classify_agent_error(status: int | None = None, kind: str = "") -> str:
    """Return a stable category for a failed AI request.

    ``kind`` comes from :class:`reasonable.ai.client.AIError`; the HTTP status
    is a fallback for unexpected responses and older call sites.
    """
    if kind in AUTO_CONTINUE_KINDS:
        return kind
    if status is not None:
        if status == 408:
            return "timeout"
        if status == 429:
            return "rate_limit"
        if 500 <= int(status) <= 599:
            return "server"
        if status in _REQUEST_STATUSES:
            return "other"
    if kind in {"request", "config", "other"}:
        return "other"
    return "other"


def is_auto_continue_kind(kind: str) -> bool:
    return kind in AUTO_CONTINUE_KINDS
