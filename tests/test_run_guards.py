"""Guards that keep one agent run bounded and instantly cancellable."""

from __future__ import annotations

import threading
import unittest

from reasonable.ai.agent import TokenBudget
from reasonable.ai.client import AIError, HTTPTransport


class TokenBudgetTests(unittest.TestCase):
    def test_zero_limit_keeps_the_run_unlimited(self) -> None:
        budget = TokenBudget(0)
        budget.add({"total_tokens": 10_000_000})
        self.assertFalse(budget.exceeded)

    def test_usage_accumulates_and_trips_the_limit(self) -> None:
        budget = TokenBudget(100)
        budget.add({"total_tokens": 60})
        self.assertFalse(budget.exceeded)
        budget.add({"total_tokens": 40})
        self.assertTrue(budget.exceeded)
        self.assertEqual(budget.used, 100)

    def test_missing_or_broken_usage_is_ignored(self) -> None:
        budget = TokenBudget(10)
        budget.add(None)
        budget.add({"total_tokens": "not-a-number"})
        self.assertEqual(budget.used, 0)
        self.assertFalse(budget.exceeded)


class CancelledTransportTests(unittest.TestCase):
    def test_cancel_is_checked_before_the_request(self) -> None:
        cancel = threading.Event()
        cancel.set()
        transport = HTTPTransport(timeout=1, retries=2, cancel=cancel)
        with self.assertRaises(AIError) as context:
            transport.request("http://127.0.0.1:9/never")
        self.assertEqual(context.exception.kind, "cancelled")

    def test_sleep_stops_immediately_when_cancelled(self) -> None:
        cancel = threading.Event()
        transport = HTTPTransport(timeout=1, retries=2, cancel=cancel)
        cancel.set()
        with self.assertRaises(AIError):
            transport._sleep(30)


if __name__ == "__main__":
    unittest.main()
