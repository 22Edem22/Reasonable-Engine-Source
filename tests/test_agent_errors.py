"""Tests for the server-error categories used by chat auto-continue."""

from __future__ import annotations

import unittest

from reasonable.core.agent_errors import (
    AUTO_CONTINUE_KINDS,
    classify_agent_error,
    http_error_kind,
    is_auto_continue_kind,
)


class AgentErrorTests(unittest.TestCase):
    def test_http_status_maps_to_transient_categories(self) -> None:
        self.assertEqual(http_error_kind(429), "rate_limit")
        for status in (500, 502, 503, 504):
            self.assertEqual(http_error_kind(status), "server", status)
        self.assertEqual(http_error_kind(408), "timeout")
        self.assertEqual(http_error_kind(401), "request")
        self.assertEqual(http_error_kind(404), "request")

    def test_classification_keeps_known_kinds(self) -> None:
        for kind in AUTO_CONTINUE_KINDS:
            self.assertEqual(classify_agent_error(None, kind), kind)
            self.assertTrue(is_auto_continue_kind(kind))

    def test_classification_falls_back_to_status(self) -> None:
        self.assertEqual(classify_agent_error(500), "server")
        self.assertEqual(classify_agent_error(503), "server")
        self.assertEqual(classify_agent_error(429), "rate_limit")
        self.assertEqual(classify_agent_error(401), "other")
        self.assertEqual(classify_agent_error(500, "request"), "server")

    def test_non_transient_kinds_are_not_auto_continued(self) -> None:
        for kind in ("request", "config", "other", ""):
            self.assertFalse(is_auto_continue_kind(kind))
            self.assertEqual(classify_agent_error(None, kind), "other")


if __name__ == "__main__":
    unittest.main()
