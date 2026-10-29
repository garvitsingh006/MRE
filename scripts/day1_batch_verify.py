"""Run hand-written repros through the real Docker verifier, record failures.

Run from repo root: python -m scripts.day1_batch_verify
Only IDs for which repros/<repoissue>-<number>.py exists are tested.

No Docker operation is mocked. Environment/build errors are reported
separately from a verifier rejection; they are never counted as PASS.
"""
import json
import traceback
from datetime import datetime, timezone
from pathlib import Path

from src.config import PROJECT_ROOT, SHORTLIST_PATH, RUNS_DIR, REPROS_DIR
from src.verify import verify


def repro_path_for(instance_id):
    # e.g. sympy__sympy-12454 -> repros/sympy-12454.py
    return REPROS_DIR / (instance_id.split("__", 1)[-1] + ".py")


def main():
    ids = json.loads(SHORTLIST_PATH.read_text(encoding="utf-8"))
    results = []
    for instance_id in ids:
        repro_path = repro_path_for(instance_id)
        if not repro_path.is_file():
            print("SKIP  | {} | No hand-written repro at {}".format(instance_id, repro_path.relative_to(PROJECT_ROOT)), flush=True)
            results.append({"instance_id": instance_id, "status": "NOT_TESTED", "reason": "repro missing"})
            continue
        print("RUN   | {} | {}".format(instance_id, repro_path.relative_to(PROJECT_ROOT)), flush=True)
        try:
            outcome = verify(instance_id, repro_path.read_text(encoding="utf-8"))
            status = "REVIEW" if outcome.review_required else ("PASS" if outcome.passed else "FAIL")
            results.append({"instance_id": instance_id, "status": status, "details": outcome.to_dict()})
            print("{}  | {} | {}".format(status, instance_id, outcome.reason), flush=True)
        except Exception as exc:
            results.append({"instance_id": instance_id, "status": "INFRA_ERROR", "reason": "{}: {}".format(type(exc).__name__, exc)})
            print("ERROR | {} | {}: {}".format(instance_id, type(exc).__name__, exc), flush=True)

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    destination = RUNS_DIR / "day1_batch_results.json"
    document = {"created_utc": datetime.now(timezone.utc).isoformat(), "results": results}
    destination.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    counts = {name: sum(row["status"] == name for row in results) for name in ("PASS", "REVIEW", "FAIL", "INFRA_ERROR", "NOT_TESTED")}
    print("\nResults: {} | {}".format(destination.relative_to(PROJECT_ROOT), counts))
    return 1 if counts["FAIL"] or counts["INFRA_ERROR"] else (2 if counts["REVIEW"] else 0)


if __name__ == "__main__":
    raise SystemExit(main())
