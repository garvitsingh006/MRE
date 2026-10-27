import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from src.build_env import build_environment
from src.run_script import ScriptResult, run_script
from src.verify import evaluate_results


class VerificationRulesTests(unittest.TestCase):
    def test_correct_pytest_reproduction_passes(self):
        before = ScriptResult(
            1,
            'Traceback (most recent call last):\n'
            '  File "/work/repo/src/_pytest/_io/saferepr.py", line 20, in _format_repr_exception\n'
            "RuntimeError: attribute access failed\n",
        )
        after = ScriptResult(0, "<[ValueError raised in repr()] Unrepresentable object>")

        result = evaluate_results(
            "pytest-dev__pytest-7168",
            "The repro raises RuntimeError while formatting an unrepresentable object.",
            before,
            after,
        )

        self.assertTrue(result.passed)

    def test_deliberately_incorrect_assertion_is_rejected(self):
        before = ScriptResult(
            1,
            'Traceback (most recent call last):\n'
            '  File "/work/repro.py", line 1, in <module>\n'
            "    assert False\n"
            "AssertionError\n",
        )
        after = ScriptResult(1, "AssertionError")

        result = evaluate_results(
            "pytest-dev__pytest-7168",
            "The issue reports RuntimeError.",
            before,
            after,
        )

        self.assertFalse(result.passed)
        self.assertIn("does not include", result.reason)

    def test_rejects_import_failures(self):
        before = ScriptResult(
            1,
            '  File "/work/repo/src/package.py", line 1\n'
            "ModuleNotFoundError: No module named 'missing'\n",
        )
        after = ScriptResult(0, "")

        result = evaluate_results("sample", "", before, after)

        self.assertFalse(result.passed)
        self.assertIn("disallowed ModuleNotFoundError", result.reason)

    def test_rejects_nonzero_exit_after_patch(self):
        before = ScriptResult(
            1,
            '  File "/work/repo/src/package.py", line 1\nRuntimeError: reported failure\n',
        )
        after = ScriptResult(1, "AssertionError")

        result = evaluate_results("sample", "RuntimeError", before, after)

        self.assertFalse(result.passed)
        self.assertIn("did not pass", result.reason)


class IsolatedRunnerTests(unittest.TestCase):
    @staticmethod
    def completed(stdout="", returncode=0):
        return subprocess.CompletedProcess(
            args=[],
            returncode=returncode,
            stdout=stdout,
        )

    @patch("src.run_script.subprocess.run")
    def test_runner_uses_limits_network_isolation_and_applies_patch(self, mock_run):
        mock_run.side_effect = [
            self.completed("container-id\n"),
            self.completed(),
            self.completed(),
            self.completed("script output\n"),
            self.completed(),
        ]

        result = run_script("cached-image", "print('ok')", patch="diff --git a/a b/a\n")

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.output, "script output")
        create_command = mock_run.call_args_list[0].args[0]
        self.assertIn("--network=none", create_command)
        self.assertIn("--memory=2g", create_command)
        self.assertIn("--cpus=2", create_command)
        self.assertIn("--pids-limit=256", create_command)
        self.assertIn("--rm", create_command)
        self.assertEqual(mock_run.call_args_list[2].kwargs["input"], "diff --git a/a b/a\n")

    @patch("src.run_script.subprocess.run")
    def test_runner_reports_script_timeout(self, mock_run):
        mock_run.side_effect = [
            self.completed("container-id\n"),
            self.completed(),
            subprocess.TimeoutExpired(["docker", "exec"], 60, output="still running"),
            self.completed(),
        ]

        result = run_script("cached-image", "while True: pass")

        self.assertEqual(result.exit_code, 124)
        self.assertTrue(result.timed_out)
        self.assertIn("60-second timeout", result.output)


class BuildEnvironmentTests(unittest.TestCase):
    @patch("src.build_env.run_docker_command")
    @patch("src.build_env.load_instance")
    def test_build_uses_pinned_repository_commit(self, mock_load, mock_docker):
        commit = "a" * 40
        mock_load.return_value = {
            "repo": "pytest-dev/pytest",
            "version": "5.4",
            "base_commit": commit,
        }

        def fake_docker(arguments, **kwargs):
            self.assertIn("timeout", kwargs)
            if arguments[:2] == ["image", "inspect"]:
                return subprocess.CompletedProcess(arguments, 1, "not found")

            dockerfile_path = arguments[arguments.index("--file") + 1]
            dockerfile = Path(dockerfile_path).read_text(encoding="utf-8")
            self.assertIn("https://github.com/pytest-dev/pytest.git", dockerfile)
            self.assertIn("checkout --quiet --detach {}".format(commit), dockerfile)
            self.assertIn("pip install --no-cache-dir --editable /work/repo", dockerfile)
            return subprocess.CompletedProcess(arguments, 0, "")

        mock_docker.side_effect = fake_docker
        image = build_environment("pytest-dev__pytest-7168")

        self.assertIn("mre-pytest-dev-pytest-", image)
        self.assertEqual(mock_docker.call_count, 2)

    @patch("src.build_env.run_docker_command")
    @patch("src.build_env.load_instance")
    def test_build_reuses_cached_image(self, mock_load, mock_docker):
        mock_load.return_value = {
            "repo": "pytest-dev/pytest",
            "version": "5.4",
            "base_commit": "a" * 40,
        }
        mock_docker.return_value = subprocess.CompletedProcess([], 0, "cached")

        image = build_environment("pytest-dev__pytest-7168")

        self.assertTrue(image.startswith("mre-pytest-dev-pytest-"))
        mock_docker.assert_called_once()


if __name__ == "__main__":
    unittest.main()