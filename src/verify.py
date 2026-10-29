"""Before/after verifier with explicit, pre-fix symptom expectations.

SWE-bench issue prose is unstructured. A type mentioned in the prose may be
expected *after* fixing the bug, not observed *before* it. Treat free text as
background context, never as an automatically generated hard failure predicate.
"""
import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from src.build_env import build_environment
from src.config import PROJECT_ROOT
from src.metadata import load_instance
from src.run_script import ScriptResult, run_script

_CHEAP_FAILURE_PATTERN = re.compile(r"\b(?:ImportError|ModuleNotFoundError|SyntaxError)\b")
_REPOSITORY_FRAME_PATTERN = re.compile(r'''(?m)\bFile ["']/(?:work/repo/)[^"']+\.py["']''')
# Read the terminal exception line (not just any type name somewhere in a traceback).
_EXCEPTION_LINE = re.compile(r"^\s*(?:[A-Za-z_][\w]*\.)*([A-Za-z_]\w*(?:Error|Exception))(?::|$)")
_SIGNATURES_PATH = PROJECT_ROOT / "verifier_signatures.json"


@dataclass
class VerificationResult:
    instance_id: str
    passed: bool
    reason: str
    before: ScriptResult
    after: ScriptResult
    # A before/after transition alone is evidence but not enough to establish
    # symptom relevance. Explicitly signal when human review is still required.
    review_required: bool = False
    observed_exception: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _terminal_exception_type(output: str) -> Optional[str]:
    for line in reversed(output.splitlines()):
        match = _EXCEPTION_LINE.match(line)
        if match:
            return match.group(1)
    return None


def _curated_buggy_exceptions(instance_id: str) -> Optional[Sequence[str]]:
    if not _SIGNATURES_PATH.is_file():
        return None
    records = json.loads(_SIGNATURES_PATH.read_text(encoding="utf-8"))
    entry = records.get(instance_id)
    if entry is None:
        return None
    names = entry.get("buggy_exception_types")
    if not isinstance(names, list) or not names or any(
        not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_]\w*", name)
        for name in names
    ):
        raise ValueError("Invalid buggy_exception_types for {}".format(instance_id))
    return names


def evaluate_results(
    instance_id: str,
    problem_statement: str,
    before: ScriptResult,
    after: ScriptResult,
    expected_buggy_exceptions: Optional[Sequence[str]] = None,
) -> VerificationResult:
    """Determine whether the script works; distinguish unreviewed bug relevance.

    `problem_statement` is retained for API compatibility and audit use, but
    cannot safely be parsed for expected pre-fix exception types.
    """
    def reject(reason: str) -> VerificationResult:
        return VerificationResult(instance_id, False, reason, before, after)

    if before.timed_out or after.timed_out:
        return reject("The reproduction timed out before or after the reference patch.")
    if before.exit_code == 0:
        return reject("The reproduction exited successfully on the buggy code.")
    if before.exit_code == 125 or before.exit_code == 126 or before.exit_code == 127:
        return reject("The buggy-run failed with a container/command execution error.")
    cheap_failure = _CHEAP_FAILURE_PATTERN.search(before.output)
    if cheap_failure:
        return reject("The buggy run failed with a disallowed {}.".format(cheap_failure.group(0)))
    if not _REPOSITORY_FRAME_PATTERN.search(before.output):
        return reject("The buggy-run traceback does not include a Python source file from /work/repo.")
    if after.exit_code != 0:
        return reject("The reproduction did not pass on the reference-patched code.")

    observed = _terminal_exception_type(before.output)
    if expected_buggy_exceptions is None:
        return VerificationResult(
            instance_id, True,
            "The reproduction fails before and passes after, but its bug symptom "
            "has not been checked against a curated pre-fix expectation.",
            before, after, review_required=True, observed_exception=observed,
        )
    if observed not in expected_buggy_exceptions:
        return reject(
            "Buggy-run terminal exception {!r} does not match curated pre-fix "
            "exception(s): {}.".format(observed, ", ".join(expected_buggy_exceptions))
        )
    return VerificationResult(
        instance_id, True,
        "The reproduction fails on buggy code, passes on the reference patch, "
        "and matches the curated pre-fix exception signature.",
        before, after, review_required=False, observed_exception=observed,
    )


def verify(instance_id: str, repro_script: str) -> VerificationResult:
    instance = load_instance(instance_id)
    image = build_environment(instance_id)
    before = run_script(image, repro_script)
    after = run_script(image, repro_script, patch=instance["patch"])
    return evaluate_results(
        instance_id,
        str(instance["problem_statement"]),
        before,
        after,
        expected_buggy_exceptions=_curated_buggy_exceptions(instance_id),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify a reproduction against buggy and reference-patched code."
    )
    parser.add_argument("instance_id")
    parser.add_argument("script", type=Path)
    args = parser.parse_args()
    result = verify(args.instance_id, args.script.read_text(encoding="utf-8"))
    verdict = "REVIEW" if result.review_required else ("PASS" if result.passed else "FAIL")
    print(verdict)
    print(json.dumps(result.to_dict(), indent=2))
    return 2 if result.review_required else (0 if result.passed else 1)


if __name__ == "__main__":
    raise SystemExit(main())
