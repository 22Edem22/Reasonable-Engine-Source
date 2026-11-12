"""Streaming assembly and its graceful fallback."""

from __future__ import annotations

import unittest

from reasonable.ai.client import AIClient, AIError


class StreamingChatTests(unittest.TestCase):
    def _client(self, chunks, **kwargs):
        client = AIClient(
            {
                "kind": "openai",
                "base_url": "http://localhost/v1",
                "model": "test-model",
                "api_key": "test",
            },
            stream=True,
            **kwargs,
        )
        client.http.iter_lines = lambda url, headers, payload: iter(chunks)
        return client

    def test_sse_content_tool_calls_and_usage_are_assembled(self) -> None:
        seen: list[str] = []
        chunks = [
            'data: {"choices":[{"delta":{"content":"Hel"}}]}',
            'data: {"choices":[{"delta":{"content":"lo"}}]}',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"read_file","arguments":"{\\"path\\":"}}]}}]}',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\\"main.py\\"}"}}]},"finish_reason":"tool_calls"}]}',
            'data: {"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}}',
            "data: [DONE]",
        ]
        client = self._client(chunks, stream_callback=seen.append)
        result = client.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(result.content, "Hello")
        self.assertEqual(seen, ["Hel", "lo"])
        self.assertEqual(result.finish_reason, "tool_calls")
        self.assertEqual(result.usage["total_tokens"], 15)
        self.assertEqual(len(result.tool_calls), 1)
        self.assertEqual(result.tool_calls[0].name, "read_file")
        self.assertEqual(result.tool_calls[0].arguments, {"path": "main.py"})

    def test_unsupported_stream_falls_back_to_the_regular_request(self) -> None:
        client = self._client([])

        def fail(url, headers, payload):
            raise AIError("no stream", status=400, kind="request")

        client.http.iter_lines = fail
        client.http.request = lambda url, method="POST", headers=None, payload=None: {
            "choices": [{"message": {"content": "plain answer"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        }
        result = client.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(result.content, "plain answer")


if __name__ == "__main__":
    unittest.main()
