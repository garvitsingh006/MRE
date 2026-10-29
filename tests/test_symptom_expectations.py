"""Regression tests for distinct buggy-vs-desired exception semantics."""
import unittest
from src.run_script import ScriptResult
from src.verify import evaluate_results, _curated_buggy_exceptions, _terminal_exception_type

REPO_TRACE = (
    'Traceback (most recent call last):\n'
    '  File "/work/repro.py", line 7, in <module>\n'
    '  File "/work/repo/requests/models.py", line 637, in generate\n'
    '    for chunk in self.raw.stream(chunk_size):\n'
    '  File "/work/repro.py", line 3, in stream\n'
    '    raise socket.error(104, "Connection reset by peer")\n'
    'ConnectionResetError: [Errno 104] Connection reset by peer\n'
)


class TestExpectedBuggySignatures(unittest.TestCase):
    def test_requests_false_negative_from_desired_exception_is_prevented(self):
        outcome = evaluate_results(
            'psf__requests-2148',
            'socket.error should be converted into ConnectionError',
            ScriptResult(1, REPO_TRACE), ScriptResult(0, ''),
            expected_buggy_exceptions=_curated_buggy_exceptions('psf__requests-2148'),
        )
        self.assertTrue(outcome.passed)
        self.assertFalse(outcome.review_required)
        self.assertEqual(outcome.observed_exception, 'ConnectionResetError')

    def test_wrong_terminal_exception_is_still_rejected(self):
        outcome = evaluate_results(
            'psf__requests-2148',
            'Desired ConnectionError',
            ScriptResult(1, REPO_TRACE.replace('ConnectionResetError:', 'RuntimeError:')),
            ScriptResult(0, ''), expected_buggy_exceptions=['ConnectionResetError'],
        )
        self.assertFalse(outcome.passed)
        self.assertIn('curated pre-fix', outcome.reason)

    def test_unconfigured_bug_is_flagged_for_manual_review(self):
        result = evaluate_results(
            'some__issue', 'Desired ConnectionError',
            ScriptResult(1, REPO_TRACE), ScriptResult(0, ''),
        )
        self.assertTrue(result.passed)
        self.assertTrue(result.review_required)

    def test_after_not_fixed_is_rejected_even_with_matching_symptom(self):
        result = evaluate_results(
            'psf__requests-2148', '...',
            ScriptResult(1, REPO_TRACE), ScriptResult(1, REPO_TRACE),
            expected_buggy_exceptions=['ConnectionResetError'],
        )
        self.assertFalse(result.passed)

    def test_qualified_exception_name_is_parsed(self):
        self.assertEqual(
            _terminal_exception_type('django.db.utils.NotSupportedError: invalid\n'),
            'NotSupportedError',
        )

    def test_terminal_exception_not_satisfied_by_nested_exception(self):
        output = REPO_TRACE + '\nDuring handling of the above exception, another exception occurred:\nRuntimeError: unrelated\n'
        self.assertEqual(_terminal_exception_type(output), 'RuntimeError')


if __name__ == '__main__':
    unittest.main()
