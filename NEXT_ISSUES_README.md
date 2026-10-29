# MRE Day 1 — additional real SWE-bench issues

This ZIP adds files to your existing **Windows-fixed** MRE repository; it does NOT replace the existing src/ code or tests.

## First: metadata check

Your earlier bundled `pytest-dev__pytest-7168` record is authentic (SWE-bench Lite), and the real bug is pytest issue #7145, fixed by PR #7168.

SymPy `sympy__sympy-12454` is also a real SWE-bench Lite instance. It references original issue #12452, fixed by PR #12454. On the old commit, `zeros(4,2).is_upper` raises IndexError. The main repro asserts that the zero matrix is upper triangular; the optional hessenberg script tests another behavior fixed in the same PR.

These NEW scripts have been syntax-checked and compared against public issue descriptions, but have NOT been run against the pinned historical Docker image here. Do not count them as verified until your own Docker run says PASS.

## PowerShell commands (from project root, .venv activated)

```powershell
# This is needed for additional issues. The original bundled smoke test mocked metadata loading.
python -m pip install datasets

# Verify all 10 shortlist IDs are in the official configured SWE-bench Lite split.
python -m scripts.day1_audit_shortlist

# Test the NEW SymPy issue with real Docker; may require first-time image build.
python -m src.verify sympy__sympy-12454 repros/sympy-12454.py

# Optional: test the related second behavior; does NOT count as another SWE-bench issue.
python -m src.verify sympy__sympy-12454 repros/sympy-12454-hessenberg.py

# Batch-test every shortlist case having a matching file in repros/, including pytest and SymPy.
python -m scripts.day1_batch_verify
```

## Interpretation

- PASS = nonzero on original bug; zero after gold fix; verifier's traceback and symptom checks pass.
- FAIL = a repro was executed but rejected; inspect its JSON result, don't equate it with a fake dataset issue.
- INFRA_ERROR = couldn't build, fetch dataset, or run (not evidence of bug validity).
- NOT_TESTED = no hand-written reproduction script exists yet.

The batch writes `runs/day1_batch_results.json`.

## Important limitations

1. `src/config.py` pins ALL allowed repos to `python:3.8-slim`. Some historical installations may need another compatible Python version or pinned dependencies.
2. The simple `pip install -e` environment builder is not an official SWE-bench environment recipe. A target build that fails is not automatically an invalid issue.
3. The custom `src/verify.py` uses heuristic traceback and exception matching. `FAIL` may mean the verifier rejects an otherwise genuine reproduction; manually review the logs.
4. The gold patch is used only by the verifier. Do not leak it into any Day 2 LLM prompt.
5. `pallets__flask-4045` adds input-validation behavior and is a poor first choice for this project's 'buggy crashes/fixed doesn't' rule. `psf__requests-1963` and `-2148` are real issues but their original contexts involve networking: avoid them as early offline smoke tests.
6. Each separate instance ID counts once toward the five-instance Day 1 goal. Two repros for one ID do not count twice.

Upstream references:
- https://huggingface.co/datasets/princeton-nlp/SWE-bench_Lite
- https://github.com/pytest-dev/pytest/issues/7145
- https://github.com/pytest-dev/pytest/pull/7168
- https://github.com/sympy/sympy/issues/12452
- https://github.com/sympy/sympy/pull/12454
