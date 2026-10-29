
from datasets import load_dataset
import json

dataset = load_dataset(
    "princeton-nlp/SWE-bench_Lite",
    split="test"
)

target_id = "pytest-dev__pytest-7168"

matches = [
    row for row in dataset
    if row["instance_id"] == target_id
]

if not matches:
    raise ValueError(f"Instance not found: {target_id}")

record = matches[0]

print("INSTANCE ID:", record["instance_id"])
print("REPOSITORY:", record["repo"])
print("BASE COMMIT:", record["base_commit"])
print("VERSION:", record["version"])

print("\n========== PROBLEM STATEMENT ==========\n")
print(record["problem_statement"])

print("\n========== TEST PATCH ==========\n")
print(record["test_patch"])

print("\n========== FIX PATCH (REFERENCE ANSWER) ==========\n")
print(record["patch"])

# Save the complete record for inspection
with open("pytest-7168-record.json", "w", encoding="utf-8") as f:
    json.dump(record, f, indent=2, ensure_ascii=False)

print("\nSaved to pytest-7168-record.json")
