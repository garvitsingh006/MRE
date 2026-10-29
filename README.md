# MRE Generator — HackCBS 9.0

A Docker-based tool that takes a Python bug report from [SWE-bench Lite](https://huggingface.co/datasets/princeton-nlp/SWE-bench_Lite) and automatically generates a **Minimal Reproduction Example (MRE)** — a short script that fails on the buggy commit and passes on the fixed one.

## How it works

1. An LLM is given the issue text and the buggy repo (no fix patch).
2. It iteratively searches the codebase, reads files, writes a repro script, and runs it — all inside an isolated Docker container.
3. The verifier checks: does the script **fail before** the fix and **pass after**?

Validation is done against already-fixed bugs from SWE-bench Lite — the only honest way to measure whether a repro is correct.

## Project structure

```
├── src/
│   ├── build_env.py        # Builds/caches Docker images for each SWE-bench instance
│   ├── run_script.py       # Runs a repro script in a network-isolated container
│   ├── verify.py           # Verifier: fails-before + passes-after checks
│   ├── llm_orchestration.py# LLM action loop (search / read / write / run)
│   ├── dataset.py          # SWE-bench dataset loading
│   ├── metadata.py         # Instance metadata helpers
│   ├── providers.py        # OpenAI-compatible Gemini/Groq client with fallback
│   └── config.py           # Paths, Docker limits, allowed repos
├── scripts/
│   ├── verify.py           # CLI: verify a hand-written repro
│   └── manual_verify.py    # Manual verification helper
├── repros/                 # Hand-written or generated repro scripts
├── runs/                   # Per-instance run logs (JSON)
├── cache/                  # Cached dataset and Docker images
├── tests/
│   └── test_verify.py
├── main.py                 # Shortlist builder (filters SWE-bench Lite to 10 instances)
└── shortlist.json          # 10 curated instance IDs
```

## Supported repositories

- `pallets/flask`
- `psf/requests`
- `pytest-dev/pytest`
- `pylint-dev/pylint`
- `sympy/sympy`
- `django/django`

## Prerequisites

- Python 3.10+
- Docker (with `docker` on PATH)
- API key for at least one LLM provider: **Google Gemini** or **Groq**

## Setup

```bash
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in at least one provider key:

```env
PROVIDER=gemini          # gemini | groq
MODEL=gemini-2.5-flash
GEMINI_API_KEY=<your_gemini_key>
GROQ_API_KEY=<your_groq_key>
GEMINI_MODEL=gemini-2.5-flash
GROQ_MODEL=openai/gpt-oss-120b
```

The selected `PROVIDER` is tried first. If it returns HTTP 429 and the other
provider has a key configured, the client tries that provider. `MODEL` applies
to the selected provider; `GEMINI_MODEL` and `GROQ_MODEL` optionally override
each provider independently. Keep API keys only in the host `.env`; they are
not passed to Docker. LLM responses are cached under `cache/`, and daily usage
is recorded in `cache/llm_usage.json`. Optionally set
`GEMINI_DAILY_TOKEN_LIMIT` and/or `GROQ_DAILY_TOKEN_LIMIT` to conservative
limits from your provider consoles; a call is stopped before its estimated
input plus maximum response could exceed the configured budget.

## Usage

### 1. Build the shortlist

```bash
python main.py
```

Filters SWE-bench Lite to 10 curated instances with clear bug symptoms and saves their IDs to `shortlist.json`.

### 2. Build a Docker environment for an instance

```bash
python -m src.build_env <instance_id>
```

Clones the repo, checks out the buggy commit, and caches the image.

### 3. Verify a repro script

```bash
python -m src.verify <instance_id> repros/my_repro.py
```

Prints `PASS` or `FAIL` with a full JSON report.

### 4. Run the LLM loop (Day 2+)

```bash
python -m src.repro_runner <instance_id>
```

Runs the LLM action loop and saves the result to `runs/<instance_id>.json`.
Repeated invocations append an attempt to that JSON log. A timestamped
`runs/<instance_id>.<timestamp>.debug.log` captures prompts, raw model
responses, parsed actions, tool output, verifier results, and tracebacks for
debugging. The CLI output includes that debug-log path. Each run uses at most
8 LangGraph turns and 4 network-isolated script executions.

## Verifier rules

A repro passes only if **all** of the following hold:

| Rule | Description |
|------|-------------|
| Fails before | Script exits non-zero on the buggy commit |
| Passes after | Script exits 0 after applying the gold patch |
| No cheap failures | Rejects `ImportError`, `ModuleNotFoundError`, `SyntaxError` |
| Repo frame in traceback | At least one frame must be from `/work/repo/` |
| Symptom match | If the issue names an exception type, the failure must mention it |

## Docker safety

- LLM-written code runs with `--network none` — no internet access.
- Limits: `--memory 2g --cpus 2 --pids-limit 256` with a 60-second timeout.
- Containers are removed after each run (`--rm`).
- API keys are never baked into images.

## LLM action format

The model may reply with plain text actions or multiple fenced action blocks.
Actions are executed in order, and search results are restricted to Python
source files:

```
search <regex>          → ripgrep in repo, ≤30 matching lines
read <repo-relative path> <start> <end> → file contents, ≤120 lines
write                    → next lines contain the complete repro script
run                     → executes the script, returns last 40 lines
```

Loop limits: 8 steps max, 4 `run` actions max.

## License

Built for HackCBS 9.0. Not intended for production use.
