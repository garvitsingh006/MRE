## CLI entry point


import json
import re
from datasets import load_dataset

# 1. Load SWE-bench Lite test split
dataset = load_dataset(
    "princeton-nlp/SWE-bench_Lite",
    split="test"
)

# 2. Practical allowlist of Python-focused repositories
allowed_repos = {
    "pallets/flask",
    "psf/requests",
    "pytest-dev/pytest",
    "pylint-dev/pylint",
    "sympy/sympy",
    "django/django",
}

filtered = [
    row for row in dataset
    if row["repo"].lower() in allowed_repos
]

print("Total test instances:", len(dataset))
print("After repository filtering:", len(filtered))
print("Repositories found:", sorted({
    row["repo"] for row in filtered
}))

# 3. Find descriptions with explicit bug symptoms or tracebacks
traceback_pattern = re.compile(
    r"Traceback \(most recent call last\)|"
    r"File \"[^\"]+\", line \d+|"
    r"^\s*\w+(Error|Exception):",
    re.MULTILINE
)

symptom_pattern = re.compile(
    r"\b("
    r"raises?\s+\w*Error|"
    r"unexpectedly|incorrect(?:ly)?|"
    r"does not|doesn't|fails? to|"
    r"crashes?|returns?\s+(?:None|wrong|incorrect)|"
    r"should\s+(?:return|raise|not)|"
    r"AttributeError|TypeError|ValueError|"
    r"AssertionError|KeyError|ImportError"
    r")\b",
    re.IGNORECASE
)

candidates = []

for row in filtered:
    statement = row["problem_statement"]
    has_traceback = bool(traceback_pattern.search(statement))
    has_symptom = bool(symptom_pattern.search(statement))

    if has_traceback or has_symptom:
        candidates.append({
            "instance_id": row["instance_id"],
            "repo": row["repo"],
            "problem_statement": statement,
            "has_traceback": has_traceback,
            "has_symptom": has_symptom,
            "score": 2 * has_traceback + has_symptom,
        })

# Prefer tracebacks, then explicit symptom descriptions
candidates.sort(
    key=lambda x: (-x["score"], x["instance_id"])
)

# 4. Select 10 candidates
# Round-robin across repositories for diversity
from collections import defaultdict, deque

groups = defaultdict(deque)

for item in candidates:
    groups[item["repo"]].append(item)

shortlist = []

while len(shortlist) < 10:
    added = False

    for repo in sorted(groups):
        if groups[repo] and len(shortlist) < 10:
            shortlist.append(groups[repo].popleft())
            added = True

    if not added:
        break

if len(shortlist) < 10:
    raise RuntimeError(
        f"Only {len(shortlist)} candidates found. "
        "Review the filter or broaden the search."
    )

# 5. Save the IDs and review information
with open("shortlist.json", "w", encoding="utf-8") as f:
    json.dump(
        [item["instance_id"] for item in shortlist],
        f,
        indent=2
    )

# 6. Print candidates for manual review
for i, item in enumerate(shortlist, start=1):
    print(f"\n{i}. {item['instance_id']}")
    print("Repository:", item["repo"])
    print("Traceback:", item["has_traceback"])
    print("Symptom:", item["has_symptom"])
    print(
        "Problem:",
        re.sub(r"\s+", " ", item["problem_statement"])[:300]
    )

print("\nSaved", len(shortlist), "IDs to shortlist.json")
