import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.repro_runner import _attempt_path, run_attempt


class ReproRunnerTests(unittest.TestCase):
    def test_run_attempt_appends_complete_attempt_logs(self):
        run_result = {
            "instance_id": "pytest-dev__pytest-7168",
            "steps": 2,
            "tokens_used": 20,
            "script": "assert True",
            "passed": True,
            "failure_reason": "",
        }
        with tempfile.TemporaryDirectory() as directory:
            with patch("src.repro_runner.RUNS_DIR", Path(directory)), patch(
                "src.repro_runner.load_instance",
                return_value={
                    "problem_statement": "Issue",
                    "repo": "pytest-dev/pytest",
                    "version": "test-version",
                },
            ), patch("src.repro_runner.build_environment", return_value="image"), patch(
                "src.repro_runner.run_repro_loop", return_value=run_result
            ) as repro_loop:
                first = run_attempt("pytest-dev__pytest-7168")
                second = run_attempt("pytest-dev__pytest-7168")

            log_path = Path(directory) / "pytest-dev__pytest-7168.json"
            log = json.loads(log_path.read_text(encoding="utf-8"))
            debug_path = Path(first["debug_log"])
            debug_exists = debug_path.is_file()
            debug_text = debug_path.read_text(encoding="utf-8")

        self.assertTrue(first["passed"])
        self.assertTrue(second["passed"])
        self.assertTrue(debug_exists)
        self.assertIn('"event": "run_started"', debug_text)
        self.assertIn('"event": "run_completed"', debug_text)
        self.assertEqual(
            repro_loop.call_args.kwargs["debug_log_path"],
            second["debug_log"],
        )
        self.assertEqual(len(log["attempts"]), 2)
        self.assertEqual(log["attempts"][0]["tokens_used"], 20)
        self.assertIn("completed_at", log["attempts"][0])

    def test_instance_id_cannot_escape_runs_directory(self):
        with self.assertRaises(ValueError):
            _attempt_path("..\\outside")


if __name__ == "__main__":
    unittest.main()
