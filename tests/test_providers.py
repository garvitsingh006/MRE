import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from httpx import Request, Response
from openai import RateLimitError

from src.providers import ProviderResponse, _check_daily_budget, chat


class ProviderClientTests(unittest.TestCase):
    def test_falls_back_to_groq_after_gemini_rate_limit_and_records_usage(self):
        response = RateLimitError(
            "rate limited",
            response=Response(429, request=Request("POST", "https://example.test")),
            body={"error": "rate limited"},
        )
        groq_response = ProviderResponse("answer", "groq", 12, 4)
        with tempfile.TemporaryDirectory() as directory:
            usage_path = Path(directory) / "usage.json"
            with patch.dict(
                os.environ,
                {
                    "PROVIDER": "gemini",
                    "GEMINI_API_KEY": "test-gemini-key",
                    "GROQ_API_KEY": "test-groq-key",
                    "MODEL": "preferred-model",
                },
                clear=True,
            ), patch("src.providers.load_dotenv"), patch(
                "src.providers.LLM_USAGE_PATH", usage_path
            ), patch(
                "src.providers._request", side_effect=[response, groq_response]
            ) as request:
                result = chat([{"role": "user", "content": "hello"}])

            ledger = json.loads(usage_path.read_text(encoding="utf-8"))

        self.assertEqual(result.provider, "groq")
        self.assertEqual(
            [call.args[0] for call in request.call_args_list],
            ["gemini", "groq"],
        )
        self.assertEqual(ledger["providers"]["groq"]["tokens"], 16)
        self.assertEqual(ledger["providers"]["groq"]["calls"], 1)

    def test_stops_before_configured_daily_budget(self):
        with patch.dict(
            os.environ,
            {"GROQ_DAILY_TOKEN_LIMIT": "1000"},
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "daily token limit"):
                _check_daily_budget(
                    "groq",
                    [{"role": "user", "content": "hello"}],
                    {"providers": {"groq": {"tokens": 0}}},
                )


if __name__ == "__main__":
    unittest.main()
