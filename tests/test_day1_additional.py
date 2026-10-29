"""Additional Day-1 tests that do not require Docker or network access."""

import unittest
from unittest.mock import call, patch

from src.run_script import ScriptResult, _last_lines
from src.verify import evaluate_results, verify


REPO_ERROR = (
    'Traceback (most recent call last):\n'
    '  File "/work/repo/src/_pytest/_io/saferepr.py", line 23, in foo\n'
    'RuntimeError: attribute access is broken\n'
)


class AdditionalDay1Tests(unittest.TestCase):
    def test_full_verifier_wires_same_script_and_gold_patch(self):
        record = {
            "repo": "pytest-dev/pytest",
            "base_commit": "a" * 40,
            "version": "5.4",
            "patch": "gold-diff",
            "problem_statement": "RuntimeError while formatting repr",
        }
        before = ScriptResult(1, REPO_ERROR)
        after = ScriptResult(0, "fixed")
        with patch("src.verify.load_instance", return_value=record), patch(
            "src.verify.build_environment", return_value="the-image"
        ) as builder, patch(
            "src.verify.run_script", side_effect=[before, after]
        ) as runner:
            result = verify("pytest-dev__pytest-7168", "print('a')")
        self.assertTrue(result.passed)
        builder.assert_called_once_with("pytest-dev__pytest-7168")
        self.assertEqual(
            runner.call_args_list,
            [call("the-image", "print('a')"), call("the-image", "print('a')", patch="gold-diff")],
        )

    def test_buggy_zero_exit_is_rejected(self):
        result = evaluate_results("x", "RuntimeError", ScriptResult(0, ""), ScriptResult(0, ""))
        self.assertFalse(result.passed)
        self.assertIn("exited successfully", result.reason)

    def test_wrong_exception_is_rejected(self):
        before = ScriptResult(1, REPO_ERROR.replace("RuntimeError", "ValueError"))
        result = evaluate_results("x", "RuntimeError", before, ScriptResult(0, ""), expected_buggy_exceptions=["RuntimeError"])
        self.assertFalse(result.passed)
        self.assertIn("curated pre-fix", result.reason)

    def test_failure_without_repo_frame_is_rejected(self):
        before = ScriptResult(1, '  File "/work/repro.py", line 1\nRuntimeError: issue\n')
        result = evaluate_results("x", "RuntimeError", before, ScriptResult(0, ""))
        self.assertFalse(result.passed)
        self.assertIn("/work/repo", result.reason)

    def test_before_timeout_is_not_accepted_as_a_bug(self):
        before = ScriptResult(124, REPO_ERROR, timed_out=True)
        result = evaluate_results("x", "RuntimeError", before, ScriptResult(0, ""))
        self.assertFalse(result.passed)
        self.assertIn("timed out", result.reason)

    def test_after_timeout_is_rejected(self):
        after = ScriptResult(124, "timeout", timed_out=True)
        result = evaluate_results("x", "RuntimeError", ScriptResult(1, REPO_ERROR), after)
        self.assertFalse(result.passed)
        self.assertIn("timed out", result.reason)


    def test_docker_patch_is_passed_as_exact_utf8_bytes(self):
        import subprocess
        from src.build_env import run_docker_command

        patch_text = "@@ -1 +1 @@\n-old\n+new\n# unicode: café\n"
        with patch("src.build_env.subprocess.run") as docker:
            docker.return_value = subprocess.CompletedProcess(
                ["docker", "exec"], 0, b"ok\n"
            )
            result = run_docker_command(
                ["exec", "container", "git", "apply", "-"],
                timeout=30,
                input_text=patch_text,
            )
        self.assertEqual(docker.call_args.kwargs["input"], patch_text.encode("utf-8"))
        self.assertEqual(docker.call_args.kwargs["text"], False)
        self.assertEqual(result.stdout, "ok\n")

    def test_windows_invalid_cp1252_output_does_not_crash(self):
        import subprocess
        from src.build_env import run_docker_command

        # 0x81 is undefined in cp1252; Docker logs should remain printable.
        with patch("src.build_env.subprocess.run") as docker:
            docker.return_value = subprocess.CompletedProcess(
                ["docker", "ps"], 0, b"status: \x81\xe2\x9c\x93\n"
            )
            result = run_docker_command(["ps"], timeout=30)
        self.assertIn("status:", result.stdout)
        self.assertIn("✓", result.stdout)
        self.assertIn("\ufffd", result.stdout)

    def test_repro_execution_decodes_non_cp1252_bytes(self):
        import subprocess
        from src.run_script import run_script

        def completed(stdout=b"", returncode=0):
            return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout)

        with patch("src.run_script.subprocess.run") as docker:
            docker.side_effect = [
                completed(b"container-id\n"),
                completed(),
                completed(b"hi: \x81\xe2\x9c\x93\n", 1),
                completed(),
            ]
            result = run_script("image", "print('hi')")
        self.assertEqual(result.exit_code, 1)
        self.assertIn("✓", result.output)
        self.assertIn("\ufffd", result.output)
        self.assertIs(docker.call_args_list[2].kwargs["text"], False)

    def test_output_tail_keeps_last_60_lines(self):
        text = "\n".join("line-" + str(i) for i in range(100))
        lines = _last_lines(text).splitlines()
        self.assertEqual(len(lines), 60)
        self.assertEqual(lines[0], "line-40")
        self.assertEqual(lines[-1], "line-99")


if __name__ == "__main__":
    unittest.main()
