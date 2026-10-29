import argparse
import json
import re
import sys
import traceback
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


def _debug_path(instance_id: str, started_at: datetime) -> Path:
    _attempt_path(instance_id)
    timestamp = started_at.strftime("%Y%m%dT%H%M%S%fZ")
    return RUNS_DIR / "{}.{}.debug.log".format(instance_id, timestamp)


def _write_debug(path: Path, event: str, details: Dict[str, Any]) -> None:
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **details,
    }
    with path.open("a", encoding="utf-8") as debug_file:
        debug_file.write(json.dumps(record, indent=2, ensure_ascii=False))
        debug_file.write("\n\n")


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
    started_at = datetime.now(timezone.utc)
    debug_path = _debug_path(instance_id, started_at)
    attempt: Dict[str, Any] = {
        "instance_id": instance_id,
        "started_at": started_at.isoformat(),
        "debug_log": str(debug_path),
    }
    debug_path.parent.mkdir(parents=True, exist_ok=True)
    _write_debug(
        debug_path,
        "run_started",
        {"instance_id": instance_id, "attempt_log": str(path)},
    )
    try:
        _write_debug(debug_path, "loading_instance", {"instance_id": instance_id})
        instance = load_instance(instance_id)
        _write_debug(
            debug_path,
            "building_environment",
            {"repository": instance.get("repo"), "version": instance.get("version")},
        )
        image = build_environment(instance_id)
        _write_debug(debug_path, "environment_ready", {"image": image})
        result = run_repro_loop(
            instance_id,
            str(instance["problem_statement"]),
            image,
            debug_log_path=str(debug_path),
        )
        attempt.update(result)
    except Exception as exc:
        _write_debug(
            debug_path,
            "run_error",
            {
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            },
        )
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
    _write_debug(
        debug_path,
        "run_completed",
        {
            "passed": attempt.get("passed"),
            "failure_reason": attempt.get("failure_reason"),
            "steps": attempt.get("steps"),
            "run_actions": attempt.get("run_actions"),
            "tokens_used": attempt.get("tokens_used"),
        },
    )
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