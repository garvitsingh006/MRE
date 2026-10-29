import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from src.build_env import build_environment
from src.config import RUNS_DIR
from src.metadata import load_instance
from src.llm_orchestration import run_repro_loop


_INSTANCE_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


def _attempt_path(instance_id: str) -> Path:
    if not _INSTANCE_ID.fullmatch(instance_id) or instance_id in (".", ".."):
        raise ValueError("Invalid SWE-bench instance ID.")
    return RUNS_DIR / "{}.json".format(instance_id)


def _append_attempt(path: Path, attempt: Dict[str, Any]) -> None:
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(existing, dict) or not isinstance(existing.get("attempts"), list):
            raise ValueError("Existing run log has an invalid JSON structure: {}".format(path))
    else:
        existing = {"instance_id": attempt["instance_id"], "attempts": []}
    existing["attempts"].append(attempt)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def run_attempt(instance_id: str) -> Dict[str, Any]:
    path = _attempt_path(instance_id)
    attempt: Dict[str, Any] = {
        "instance_id": instance_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        instance = load_instance(instance_id)
        image = build_environment(instance_id)
        result = run_repro_loop(
            instance_id,
            str(instance["problem_statement"]),
            image,
        )
        attempt.update(result)
    except Exception as exc:
        attempt.update(
            {
                "passed": False,
                "failure_reason": str(exc),
                "error_type": type(exc).__name__,
            }
        )
        attempt["completed_at"] = datetime.now(timezone.utc).isoformat()
        _append_attempt(path, attempt)
        raise
    attempt["completed_at"] = datetime.now(timezone.utc).isoformat()
    _append_attempt(path, attempt)
    return attempt


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate and verify a SWE-bench reproduction with LangGraph."
    )
    parser.add_argument("instance_id")
    args = parser.parse_args()
    try:
        result = run_attempt(args.instance_id)
    except Exception as exc:
        print("Run failed: {}".format(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())