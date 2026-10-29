"""Check whether shortlist IDs exist in the configured official dataset.

Run: python -m scripts.day1_audit_shortlist
This script does not build images or validate repro scripts.
"""
import json
import sys
from pathlib import Path

from src.config import SHORTLIST_PATH, DATASET_NAME, DATASET_SPLIT


def main():
    try:
        from src.metadata import _load_instances
        records = _load_instances()
    except Exception as exc:
        print("Cannot load {} [{}]: {}".format(DATASET_NAME, DATASET_SPLIT, exc))
        print("Check internet access, or run: python -m pip install datasets")
        return 2

    requested = json.loads(SHORTLIST_PATH.read_text(encoding="utf-8"))
    index = {row["instance_id"]: row for row in records}
    print("Dataset: {} [{}] | {} records".format(DATASET_NAME, DATASET_SPLIT, len(index)))
    print("Note: present in dataset != human-verified valid bug != Docker verification PASS.\n")
    missing = 0
    for item in requested:
        row = index.get(item)
        if row is None:
            print("MISSING | {}".format(item))
            missing += 1
        else:
            headline = str(row.get("problem_statement", "")).splitlines()[0].strip()[:120]
            patch = str(row.get("patch", ""))
            first_diff_line = next((line for line in patch.splitlines() if line.startswith("diff --git ")), "")
            print("FOUND   | {}".format(item))
            print("          {}".format(headline))
            print("          {}".format(first_diff_line))
    print("\nShortlist: {} present / {} total".format(len(requested)-missing, len(requested)))
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
