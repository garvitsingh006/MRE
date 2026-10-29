# Day 1 testing — Windows PowerShell

This testing copy contains three focused changes to the uploaded repository:

1. `repros/pytest-7168.py` is now an executable, standalone reproduction of the actual `saferepr()` bug. The original only defined an unused `test()` function and exited 0.
2. `src/verify.py` rejects timed-out runs explicitly.
3. `tests/test_day1_additional.py` adds seven unit tests; `scripts/day1_docker_smoke.py` exercises real Docker using the bundled local issue record.

Run all commands **from the repository root**. No LLM or API key is required for Day 1.

## A. Normal Python tests (no Docker)

```powershell
python --version
python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw "Unit tests failed" }

# Optional, if pytest is installed:
python -m pytest -q tests

# Sanity check ONLY: runs against your locally installed pytest, likely already fixed.
python repros/pytest-7168.py
if ($LASTEXITCODE -ne 0) { throw "Native repro smoke failed" }
```

Expected: 15/15 unit tests pass. The last command is not an end-to-end proof because your local pytest is not the pinned buggy commit.

## B. Docker smoke test (real buggy versus fixed repo)

Start Docker Desktop and ensure Docker is in Linux-container mode. Then:

```powershell
docker info
if ($LASTEXITCODE -ne 0) { throw "Docker Desktop is not running" }

docker run --rm python:3.11-slim python -c "print('ok')"
if ($LASTEXITCODE -ne 0) { throw "Basic Docker run failed" }

# This test must fail because networking is disabled:
docker run --rm --network none python:3.11-slim python -c "import urllib.request; urllib.request.urlopen('http://example.com', timeout=5)"
if ($LASTEXITCODE -eq 0) { throw "Security failure: no-network probe unexpectedly connected" }

# This uses pytest-7168-record.json in this repo, so no Hugging Face download is required.
# The Docker image build DOES need internet access to clone the pinned GitHub repository.
python -m scripts.day1_docker_smoke
if ($LASTEXITCODE -ne 0) { throw "Day 1 Docker integration failed" }
```

Expected final output:

```
Correct reproduction: PASS
Deliberately incorrect reproduction: FAIL
DAY 1 DOCKER SMOKE: PASS (correct accepted; wrong rejected)
```

The correct run should have nonzero exit on the buggy checkout, zero exit on the fixed checkout, and a traceback with a `/work/repo/` source frame. The incorrect `assert False` must be rejected. The smoke test really builds/runs Docker; only calls to obtain metadata from Hugging Face are replaced by reading the included local record.

The **Docker image is cached** by repository, version and commit; it should be reused on repeat runs. The first build may require substantial download time.

## C. Direct project commands (need Hugging Face SWE-bench metadata)

Once dependencies and dataset access work, the original CLI can be tested too:

```powershell
python -m src.build_env pytest-dev__pytest-7168
python -m src.verify pytest-dev__pytest-7168 repros/pytest-7168.py
python -m scripts.manual_verify
```

`scripts/verify.py` is just a placeholder; use `python -m src.verify` instead. The local-record smoke in B tests the same actual build/runner/verification functions without dataset access.

## D. Day 1 acceptance checklist

- [ ] Python unit tests pass.
- [ ] Docker starts a basic Python container.
- [ ] Docker `--network none` blocks outbound network.
- [ ] Correct standalone `pytest-7168` repro fails before and passes after the reference patch.
- [ ] Deliberately incorrect script is rejected.
- [ ] Verify 2 different real issues, then build and manually verify at least 5 of the 10 shortlisted instances.

**Current status:** Unit tests passed in an external Python environment (15/15); Docker could not be exercised there because the Docker CLI was unavailable. Neither five instances nor two valid real reproductions are yet established.

## Troubleshooting

- `docker: command not found` / daemon error: install/start Docker Desktop, enable Linux containers and reopen PowerShell.
- `pip` or `git clone` fails during image build: that is a build dependency/network issue; do not count it as a verified repro.
- A repro exits 0 on the buggy commit: the script did not demonstrate the reported bug.
- Git patch cannot apply: double-check the exact pinned base commit; never silently treat a patch error as a verification failure or success.
- `datasets` missing: only the direct commands in C need it; use B first.
- Do **not** execute LLM-generated reproduction scripts natively; run those in the isolated Docker runner as specified by the plan.


### Windows Docker patch/encoding correction (28 Oct 2026)

The Docker command wrapper now sends git patches as UTF-8 **bytes** (not
Windows text-mode stdin) and decodes Docker output with UTF-8 replacement.
This prevents Windows CRLF conversion from invalidating the gold patch and
prevents `UnicodeDecodeError` caused by the default cp1252 locale.

You **do not need to rebuild or delete** the cached `mre-pytest-dev-pytest-*`
image. The image is the buggy baseline; patch application happens in a new
throwaway container on each run. Rerun:

```powershell
python -m unittest discover -s tests -v
python -m scripts.day1_docker_smoke
```

A complete result requires the true Docker run: correct reproduction PASS,
deliberately incorrect reproduction FAIL. A unit-test pass alone is not enough.
