# MRE verifier: issue symptoms versus expected outcomes

## Why `psf__requests-2148` was rejected incorrectly

The issue asks Requests to **wrap** a raw `socket.error` in the Requests-level `ConnectionError` exception. The old code reports a raw socket error. Under Python 3, `socket.error` is an alias for `OSError`, and the reset appears as `ConnectionResetError`. The previous verifier searched **every** `*Error` type in the free-text issue report and demanded to see one in the failing output. It treated the *desired, post-fix* `ConnectionError` as a *pre-fix* symptom requirement.

## What this patch does

- `verifier_signatures.json` records manually curated **expected buggy-side exception types** separately from the SWE-bench problem statement. The reference patch is not consulted to make these signatures.
- The verifier checks the **terminal exception** in the buggy traceback against that signature (instead of matching arbitrary exception names in issue prose).
- No signature means `REVIEW`: before/after behavior is observed, but symptom relevance is not established. `REVIEW` has exit code 2 and is counted separately from `PASS` in the batch script.
- A wrong signature remains `FAIL`; passing before, failing after, missing repo frames, cheap errors, and timeouts are still rejected.
- The current four curated signatures are grounded in the issue reports and the bug symptoms being tested. If you add a new issue, review its bug report and define the **pre-fix** symptom before counting it as verified. Don't infer signatures by reading the gold patch or adjusting expectations solely to make a failed run green.

## Install

From the `MRE` project root, extract `MRE_Day1_Symptom_Matching_Fix.zip` into `.` with `-Force` (or copy files manually). Preserve your existing `repros` and unrelated files.

```powershell
python -m unittest discover -s tests -v
python -m src.verify psf__requests-2148 repros/requests-2148.py
python -m scripts.day1_batch_verify
```

Expected based on previously supplied logs (not re-run in Docker here): the Requests example now passes with a matched `ConnectionResetError`, and your batch can report four `PASS` and six `NOT_TESTED` if no other files changed.

## Known limits

This is **not proof of semantic bug relevance**. A crafted script might forge traceback text, and matching one exception name may still reproduce a different defect. The source traceback check is also heuristic; assert-based behavioral bugs need a separate policy. Human spot-checks remain necessary for all accepted examples.
