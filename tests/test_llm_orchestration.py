import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.llm_orchestration import (
    ActionFormatError,
    _failure_matches_issue,
    _initial_prompt,
    _parse_action,
    _parse_actions,
    run_repro_loop,
)
from src.providers import ProviderResponse
from src.run_script import ScriptResult
from src.verify import VerificationResult


class ActionParsingTests(unittest.TestCase):
    def test_parses_multiline_write(self):
        action = _parse_action("```text\nwrite\nprint('repro')\n```")

        self.assertEqual(action, {"type": "write", "code": "print('repro')"})

    def test_accepts_bare_actions_and_ignores_fenced_search_output(self):
        response = (
            "search _pytest/_code/code.py\n"
            "```text\n"
            "_pytest/_code/code.py\n"
            "```"
        )
        self.assertEqual(
            _parse_action(response),
            {"type": "search", "pattern": "_pytest/_code/code.py"},
        )
        self.assertEqual(
            _parse_action("read src/_pytest/_code/code.py 600 680"),
            {
                "type": "read",
                "path": "src/_pytest/_code/code.py",
                "start": "600",
                "end": "680",
            },
        )

    def test_accepts_multiple_concatenated_fenced_actions(self):
        response = (
            "```text\nsearch def .*repr\n```"
            "```text\nread src/_pytest/_code/code.py 1 20\n```"
            "```text\nwrite\nprint('repro')\n```"
        )
        self.assertEqual(
            [action["type"] for action in _parse_actions(response)],
            ["search", "read", "write"],
        )

    def test_recovers_an_unclosed_write_fence_from_truncated_reply(self):
        response = "```write\nprint('complete enough')\n"
        self.assertEqual(
            _parse_action(response),
            {"type": "write", "code": "print('complete enough')"},
        )

    def test_internalerror_repr_issue_gets_a_concrete_repro_plan(self):
        prompt = _initial_prompt(
            "INTERNALERROR when exception in __repr__\nMinimal code to reproduce"
        )
        self.assertIn("src/_pytest/reports.py", prompt)
        self.assertIn("Do not use more than two turns", prompt)
        self.assertIn("if that output contains `INTERNALERROR`", prompt)

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
            debug_path = Path(cache_dir) / "attempt.debug.log"
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
                    debug_log_path=str(debug_path),
                )
                second = run_repro_loop(
                    "pytest-dev__pytest-7168",
                    "The operation raises RuntimeError.",
                    "test-image",
                )
            debug_text = debug_path.read_text(encoding="utf-8")

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
        self.assertIn('"event": "llm_request"', debug_text)
        self.assertIn('"event": "llm_response"', debug_text)
        self.assertIn("raise RuntimeError('broken')", debug_text)
        self.assertIn('"event": "action_result"', debug_text)
        self.assertIn('"event": "verification"', debug_text)

    def test_multiple_actions_in_one_reply_execute_before_verification(self):
        response = ProviderResponse(
            (
                "```text\nsearch def repr\n```"
                "```text\nread src/module.py 1 10\n```"
                "```text\nwrite\nprint('standalone')\n```"
                "```text\nrun\n```"
            ),
            "gemini",
            40,
            20,
        )
        verification = VerificationResult(
            "pytest-dev__pytest-7168",
            True,
            "verified",
            ScriptResult(1, "RuntimeError"),
            ScriptResult(0, ""),
        )
        with tempfile.TemporaryDirectory() as cache_dir:
            with patch("src.llm_orchestration.LLM_CACHE_DIR", Path(cache_dir)), patch(
                "src.llm_orchestration.chat", return_value=response
            ), patch("src.llm_orchestration._search", return_value="search result"), patch(
                "src.llm_orchestration._read", return_value="file content"
            ), patch(
                "src.llm_orchestration.run_script",
                return_value=ScriptResult(
                    1,
                    '  File "/work/repo/src/module.py", line 1\nRuntimeError: broken',
                ),
            ), patch(
                "src.llm_orchestration.verify", return_value=verification
            ) as verifier:
                result = run_repro_loop(
                    "pytest-dev__pytest-7168",
                    "A RuntimeError is raised.",
                    "test-image",
                )

        self.assertTrue(result["passed"])
        self.assertEqual(result["steps"], 1)
        self.assertEqual(result["script"], "print('standalone')")
        self.assertEqual(
            [entry["action"] for entry in result["actions"]],
            ["search", "read", "write", "run"],
        )
        self.assertTrue(all("result" in entry for entry in result["actions"]))
        verifier.assert_called_once()


if __name__ == "__main__":
    unittest.main()
