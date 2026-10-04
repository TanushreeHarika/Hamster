from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from evals import _call_openrouter
from hamster.config import Config
from hamster.openrouter import OpenRouterClient, StreamResult


class TestOpenRouterAuthorization(unittest.TestCase):
    def test_streaming_client_sends_configured_bearer_token(self) -> None:
        response = Mock()
        response.iter_lines.return_value = ["data: [DONE]"]
        config = Config(
            openrouter_api_key="test-key",
            max_tokens=100,
            max_failures=1,
            model="test/model",
        )

        with patch("hamster.openrouter.requests.post", return_value=response) as post:
            result = list(OpenRouterClient(config).stream_chat([]))

        self.assertTrue(any(isinstance(item, StreamResult) for item in result))
        self.assertEqual(
            post.call_args.kwargs["headers"]["Authorization"], "Bearer test-key"
        )

    def test_eval_client_sends_supplied_bearer_token(self) -> None:
        response = Mock()
        response.json.return_value = {"choices": []}

        with patch("evals.requests.post", return_value=response) as post:
            _call_openrouter("eval-test-key", "test/model", [])

        self.assertEqual(
            post.call_args.kwargs["headers"]["Authorization"],
            "Bearer eval-test-key",
        )


if __name__ == "__main__":
    unittest.main()
