import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.llm_orchestration import (
    ActionFormatError,
    _failure_matches_issue,
    _parse_action,
    run_repro_loop,
)
from src.providers import ProviderResponse
from src.run_script import ScriptResult
from src.verify import VerificationResult


class ActionParsingTests(unittest.TestCase):
    def test_parses_multiline_write(self):
        action = _parse_action("```text\nwrite\nprint('repro')\n```")

        self.assertEqual(action, {"type": "write", "code": "print('repro')"})

    def test_parses_read_and_rejects_parent_paths(self):
        action = _parse_action("```text\nread src/module.py 2 12\n```")
        self.assertEqual(action["type"], "read")
        self.assertEqual(action["path"], "src/module.py")
        with self.assertRaises(ActionFormatError):
            _parse_action("```text\nread ../outside.py 1 4\n```")

    def test_read_range_and_script_syntax_are_validated(self):
        with self.assertRaises(ActionFormatError):
            _parse_action("```text\nread src/module.py 1 121\n```")
        with self.assertRaises(SyntaxError):
            _parse_action("```text\nwrite\nthis is not valid python!\n```")

    def test_symptom_match_prefers_named_exception(self):
        self.assertFalse(
            _failure_matches_issue(
                "The operation raises RuntimeError for this input.",
                "ValueError: unexpected result",
            )
        )
        self.assertTrue(
            _failure_matches_issue(
                "The operation raises RuntimeError for this input.",
                "RuntimeError: unexpected result",
            )
        )


class LangGraphLoopTests(unittest.TestCase):
    def test_loop_runs_and_verifies_script_with_cached_chat_responses(self):
        responses = [
            ProviderResponse(
                "```text\nwrite\nraise RuntimeError('broken')\n```",
                "gemini",
                40,
                10,
            ),
            ProviderResponse("```text\nrun\n```", "gemini", 20, 5),
        ]
        verification = VerificationResult(
            "pytest-dev__pytest-7168",
            True,
            "verified",
            ScriptResult(1, "RuntimeError"),
            ScriptResult(0, ""),
        )
        with tempfile.TemporaryDirectory() as cache_dir:
            with patch("src.llm_orchestration.LLM_CACHE_DIR", Path(cache_dir)), patch(
                "src.llm_orchestration.chat", side_effect=responses
            ) as model, patch(
                "src.llm_orchestration.run_script",
                return_value=ScriptResult(
                    1,
                    '  File "/work/repo/src/module.py", line 1\nRuntimeError: broken',
                ),
            ), patch(
                "src.llm_orchestration.verify", return_value=verification
            ) as verifier:
                first = run_repro_loop(
                    "pytest-dev__pytest-7168",
                    "The operation raises RuntimeError.",
                    "test-image",
                )
                second = run_repro_loop(
                    "pytest-dev__pytest-7168",
                    "The operation raises RuntimeError.",
                    "test-image",
                )

        self.assertTrue(first["passed"])
        self.assertEqual(first["steps"], 2)
        self.assertEqual(first["run_actions"], 1)
        self.assertEqual(first["tokens_used"], 75)
        self.assertEqual(model.call_count, 2)
        self.assertEqual(verifier.call_count, 2)
        self.assertEqual(first["script"], "raise RuntimeError('broken')")
        self.assertTrue(second["passed"])
        self.assertEqual(second["tokens_used"], 0)
        self.assertTrue(second["actions"][0]["cached"])


if __name__ == "__main__":
    unittest.main()
