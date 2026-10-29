# Two additional Day 1 reproduction candidates

These are **proposed**, not yet verified by real Docker tests. They are each tied to a distinct SWE-bench Lite instance and deliberately use **natural tracebacks in repository code** instead of fake assertions to satisfy the verifier.

Place the `repros` folder contents in your existing `C:\Users\Aditya\Desktop\MRE\repros`. Existing files are unaffected.

From the repository root, with `.venv` activated and Docker Desktop running:

```powershell
python -m src.verify django__django-13028 repros/django-13028.py
python -m src.verify psf__requests-2148 repros/requests-2148.py
python -m scripts.day1_batch_verify
```

### Django #13028

Original bug: a Django model instance with an ordinary Boolean field named `filterable=False` is incorrectly rejected as an unfilterable ORM expression when supplied as the right-hand side of a QuerySet filter. The script constructs a filter with two minimal models and an in-memory SQLite configuration. No tables need to be created because the QuerySet is not evaluated.

Original report: https://code.djangoproject.com/ticket/31664
PR: https://github.com/django/django/pull/13028

### Requests #2148

Original bug: `Response.iter_content()` allows a raw `socket.error` to escape instead of wrapping it in `requests.exceptions.ConnectionError`. The script injects a deterministic socket error via a local fake stream, without using networking, and catches the expected library exception.

PR: https://github.com/psf/requests/pull/2148

### How to interpret results

`PASS` means your custom verifier saw nonzero before and zero after applying the benchmark fix **and** its heuristic traceback checks passed. `FAIL` requires inspection: the script may be invalid, or the verifier may be too restrictive. An image build or installation exception is an environment problem, not proof that the bug doesn't exist. The initial Docker images might take several minutes to build; later test runs reuse images.

Do not count these as additional verified instances until they pass on your machine. Do not leak their gold patches or fixed implementations to an LLM during Day 2.
