"""Day-1 real-Docker smoke test using the bundled SWE-bench instance record.

Run from the repository root:
    python -m scripts.day1_docker_smoke

The two metadata loaders are patched to read the existing local JSON record.
The Docker build, isolated runs and gold-patch application are NOT mocked.
"""

import json
from pathlib import Path
from unittest.mock import patch

from src.config import PROJECT_ROOT
from src.verify import verify


RECORD = PROJECT_ROOT / "pytest-7168-record.json"
REPRO = PROJECT_ROOT / "repros" / "pytest-7168.py"


def check(record: dict, script: str):
    # Avoid a fresh Hugging Face dataset download. Real Docker operations remain active.
    with patch("src.verify.load_instance", return_value=record), patch(
        "src.build_env.load_instance", return_value=record
    ):
        return verify(record["instance_id"], script)


def show(label: str, result) -> None:
    print(f"\n{label}: {'PASS' if result.passed else 'FAIL'}")
    print(f"Reason: {result.reason}")
    print(f"Before: exit={result.before.exit_code}, timed_out={result.before.timed_out}")
    print(result.before.output[-3000:] or "(no output)")
    print(f"After: exit={result.after.exit_code}, timed_out={result.after.timed_out}")
    print(result.after.output[-3000:] or "(no output)")


def main() -> int:
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    repro = REPRO.read_text(encoding="utf-8")

    print("Checking bundled SWE-bench instance: " + record["instance_id"], flush=True)
    print("First run may build a Docker image; subsequent runs reuse it.", flush=True)
    print("Running real Docker before/after verification...", flush=True)
    correct = check(record, repro)
    show("Correct reproduction", correct)

    if not correct.passed:
        print("\nDAY 1: NOT VERIFIED. Diagnose the correct reproduction first.")
        return 1

    print("Testing rejection of an intentionally invalid reproduction...", flush=True)
    incorrect = check(record, "assert False\n")
    show("Deliberately incorrect reproduction", incorrect)
    if incorrect.passed:
        print("\nDAY 1: FAIL (invalid repro accepted)")
        return 1

    print("\nDAY 1 DOCKER SMOKE: PASS (correct accepted; wrong rejected)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
