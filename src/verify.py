import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict

from src.build_env import build_environment
from src.metadata import load_instance
from src.run_script import ScriptResult, run_script


_CHEAP_FAILURE_PATTERN = re.compile(
    r"\b(?:ImportError|ModuleNotFoundError|SyntaxError)\b"
)
_REPOSITORY_FRAME_PATTERN = re.compile(
    r"""(?m)\bFile ["']/(?:work/repo/)[^"']+\.py["']"""
)
_EXCEPTION_TYPE_PATTERN = re.compile(
    r"\b([A-Z][A-Za-z0-9_]*(?:Error|Exception))\b"
)


@dataclass
class VerificationResult:
    instance_id: str
    passed: bool
    reason: str
    before: ScriptResult
    after: ScriptResult

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def evaluate_results(
    instance_id: str,
    problem_statement: str,
    before: ScriptResult,
    after: ScriptResult,
) -> VerificationResult:
    if before.exit_code == 0:
        return VerificationResult(
            instance_id,
            False,
            "The reproduction exited successfully on the buggy code.",
            before,
            after,
        )

    cheap_failure = _CHEAP_FAILURE_PATTERN.search(before.output)
    if cheap_failure:
        return VerificationResult(
            instance_id,
            False,
            "The buggy run failed with a disallowed {}.".format(
                cheap_failure.group(0)
            ),
            before,
            after,
        )

    if not _REPOSITORY_FRAME_PATTERN.search(before.output):
        return VerificationResult(
            instance_id,
            False,
            "The buggy-run traceback does not include a Python source file from /work/repo.",
            before,
            after,
        )

    expected_exception_types = set(
        _EXCEPTION_TYPE_PATTERN.findall(problem_statement)
    )
    if expected_exception_types and not any(
        re.search(r"\b{}\b".format(re.escape(exception_type)), before.output)
        for exception_type in expected_exception_types
    ):
        return VerificationResult(
            instance_id,
            False,
            "The buggy-run output does not contain an exception type from the issue.",
            before,
            after,
        )

    if after.exit_code != 0:
        return VerificationResult(
            instance_id,
            False,
            "The reproduction did not pass on the reference-patched code.",
            before,
            after,
        )

    return VerificationResult(
        instance_id,
        True,
        "The reproduction fails on the buggy code and passes on the reference patch.",
        before,
        after,
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
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify a reproduction against buggy and reference-patched code."
    )
    parser.add_argument("instance_id")
    parser.add_argument("script", type=Path)
    args = parser.parse_args()

    result = verify(
        args.instance_id,
        args.script.read_text(encoding="utf-8"),
    )
    print("PASS" if result.passed else "FAIL")
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
