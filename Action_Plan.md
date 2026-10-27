# MRE Generator: 3-Day Hackathon Action Plan

Oct 27, 2026 · @Someone

## Goal and scope

Build a Docker-based tool that takes a Python bug report and outputs a short script that fails on the buggy commit and passes on the fixed one, in 3 days, on free LLM APIs.

- **Input:** an issue from SWE-bench Lite (issue text plus buggy commit). The fix patch is a hidden answer key, used only by the verifier and never shown to the model.
- **Output:** a repro script plus a verification report (fails before, passes after, with logs).
- **In scope:** pure-Python repos, bug issues only, about 10 curated test issues, one simple web page to run them.
- **Out of scope:** arbitrary repo URLs, the maintainer extension, RAG, race-condition, platform or GPU bugs. Minimizing the script is a stretch goal.

Pitch line: we validate on already-fixed bugs because that is the only honest way to measure whether a repro is correct.

## Tonight: four sanity checks (about 1 hour)

Do these before writing any real code. Each one can kill or reshape the plan, and each is cheap to test.

1. **Hugging Face call and cost check**
   - [x] Create a token at huggingface.co/settings/tokens.
   - [ ] Call `https://router.huggingface.co/v1/chat/completions` with the OpenAI client (`base_url` set to `https://router.huggingface.co/v1`, `api_key` set to your token). Docker's docs use `Qwen/Qwen3-Coder-480B-A35B-Instruct` as an example model; confirm it works for your account, or pick another coding model from the HF models page filtered by inference provider.
   - [ ] Send a prompt of about 3,000 tokens, then open the HF billing page and note the cost.
   - **Pass:** you get a reply and know the cost per call. **Fail:** error or credit exhausted, which means HF is your fallback, not your main provider.
2. **A second free provider**
   - [ ] Get a Groq key and a Google AI Studio (Gemini) key.
   - [ ] Send the same prompt to each and write down the rate limits shown in their consoles.
   - **Pass:** at least one provider answers reliably. Keep the model name in an environment variable so you can swap it.
3. **Docker basics and isolation**
   - [ ] `docker run --rm python:3.11-slim python -c "print('ok')"` prints ok.
   - [ ] `docker run --rm python:3.11-slim pip install requests` succeeds (network on).
   - [ ] `docker run --rm --network none python:3.11-slim python -c "import urllib.request; urllib.request.urlopen('http://example.com')"` fails (network off).
   - **Pass:** all three behave as described. The last one proves LLM-written code can be run with no internet.
4. **Test-case shortlist from SWE-bench Lite**
   - [x] `pip install datasets`, then load `princeton-nlp/SWE-bench_Lite` (split `test`). Fields I expect, from memory, so verify: `instance_id`, `repo`, `base_commit`, `problem_statement`, `patch`, `test_patch`, `FAIL_TO_PASS`, `version`.
   - [x] Filter to pure-Python repos (from memory, verify: flask, requests, pytest, pylint, sympy, django). Skip anything needing compiled extensions.
   - [x] Shortlist 10 instances whose `problem_statement` contains a traceback or a clear one-line symptom. Save their `instance_id` values in `shortlist.json`.
   - **Pass:** 10 candidates saved.

## Day 1: build the verifier by hand, with no LLM

The goal is a command that takes an instance ID and a repro script and prints PASS or FAIL for "fails before, passes after". If this works with a human-written script, the hardest infrastructure is done.

- [ ] Write `build_env.py`: for an instance, build a Docker image from `python:3.x-slim` plus `git`, clone the repo, check out `base_commit` into `/work/repo`, run `pip install -e .` (network on during build only). Pick the Python version that fits the repo's era; if the install fails, drop that instance from the shortlist rather than fighting it.
- [ ] Write `run_script.py`: start a container from that image with `--network none --memory 2g --cpus 2 --pids-limit 256 --rm`, copy the script to `/work/repro.py` (outside the repo), run it with a 60-second timeout, and return exit code plus the last 60 lines of output.
- [ ] Add the "fixed" mode: in a fresh container, run `git apply` with the instance's `patch` (the gold fix), then run the same script.
- [ ] Write `verify.py` that calls both modes and applies the rules in the Verifier rules section below.
- [ ] Hand-write a repro for 2 shortlisted issues from their problem statements and confirm the verifier says PASS for a correct one and FAIL for a deliberately wrong one (for example `assert False`).
- [ ] Cache built images by `repo` + `version` so each environment is built once.

**End of day check:** at least 5 of your 10 shortlisted instances build and verify with a hand-written script. If fewer, replace the ones that fail to build now, not on day 3.

## Day 2: the LLM repro loop

The model only sees the issue text and the buggy repo. Your code does everything deterministic; the model only decides what to look at and what script to write.

- [ ] Write a provider-agnostic client: one function `chat(messages)` that reads `PROVIDER`, `MODEL` and the API key from environment variables, uses the OpenAI-compatible endpoint, and falls back to the next provider on rate-limit errors.
- [ ] Define a plain-text action format instead of native tool calling, because free providers differ in tool-call support. The model replies with one fenced block per turn, in one of four forms:
  - `search <regex>`: your code runs ripgrep in the repo and returns at most 30 matching lines.
  - `read <path> <start> <end>`: returns at most 120 lines.
  - `write <python code>`: saves the repro script.
  - `run`: executes the script in the no-network container and returns the last 40 lines of output.
- [ ] Prompt contents: the problem statement truncated to about 1,500 tokens, the rules (write a standalone script, no editing the repo, must raise or assert on the buggy behavior, must exit 0 once fixed), and the action format.
- [ ] Loop limits: at most 8 steps, at most 4 `run` actions, stop early when a `run` shows a failure whose error looks like the reported symptom.
- [ ] When the loop ends, pass the last script to `verify.py`. Only the verifier decides success, never the model.
- [ ] Log every attempt to `runs/<instance_id>.json`: steps, tokens used, script, verifier result, failure reason.
- [ ] Run your 5 verified instances from day 1, fix the prompt for the common failure (usually wrong imports or the wrong error), then run all 10.

**End of day check:** the loop runs end to end on at least 3 instances, with or without a correct result.

## Day 3: measure, build the page, prepare the backup demo

Spend the morning on honest numbers and the afternoon on the page. Judges trust a measured 4 out of 10 more than an unmeasured claim.

- [ ] Run all 10 instances up to 2 attempts each, and write down: reproduced yes or no, number of steps, tokens used, and the failure reason for each miss (build failed, wrong error, rate limit, loop stuck).
- [ ] Compute the success rate and list the failure causes. Put them on a results slide as they are, including the misses.
- [ ] Build the page with the stack you know: a React form with a dropdown of your curated instance IDs and a Run button, a FastAPI (or Express) backend that streams the log with server-sent events, and a result panel showing the script, the before/after verifier badges and the logs.
- [ ] Cache each successful run's full log and result as JSON so the demo can replay instantly if an API is rate-limited or the network fails.
- [ ] Record a 2-minute screen video of one good end-to-end run as a backup.
- [ ] Stretch only if everything above is done: an open-bug mode that skips the "passes after" check and labels the result "unverified", and a last pass that asks the model to shorten the script and re-verifies.

## Verifier rules

A repro counts only if it fails for the right reason on the buggy commit and passes on the fixed one. These checks are heuristics that catch most fake successes; they are not proof.

1. **Fails before:** on the buggy commit the script exits non-zero.
2. **Passes after:** after applying the gold patch to a fresh checkout, the same script exits 0.
3. **No cheap failures:** reject if the failure is `ImportError`, `ModuleNotFoundError` or `SyntaxError`. These usually mean the model's own mistake, not the bug.
4. **Failure is inside the repo:** the traceback or assertion must involve at least one frame from the repo's source files, not only the script itself.
5. **Symptom match when available:** if the issue contains an exception type or message, the failure should mention the same exception type.
6. **Clean runs:** each check runs in a fresh container from the cached image, so the model cannot pass by editing the repo.
7. **Bug issues only:** skip feature requests. A new function added by the fix would make any script that calls it "fail before, pass after" for the wrong reason.

Known gap: a script can still fail before and pass after for a reason unrelated to the reported bug. Spot-check every success by reading the script before you show it to anyone.

## Token and rate-limit rules

Free tiers allow only a handful of full runs per day, so every call must be small and every result cached.

Limits as seen in search results on 2026-10-27 (re-verify in each console, they change without notice):

| Provider | Free allowance | What it means for you |
| --- | --- | --- |
| Hugging Face (free account) | Under $0.10 of Inference Providers credit per month, no pay-as-you-go | About one run or less (my estimate). Use as a fallback only. |
| Groq, gpt-oss-120b | 30 requests/min, 1,000 requests/day, 8,000 tokens/min, 200,000 tokens/day | One call with a context over 8,000 tokens can be rejected. Roughly 4 to 8 full runs per day (my estimate). |
| Google Gemini API | Free tier exists; check AI Studio for current limits | Likely your highest-volume option; test it tonight. |

Rules:

- Keep every prompt under about 4,000 tokens: truncate the issue, truncate file reads, truncate command output.
- Keep a counter of tokens used per provider per day and stop before you hit the limit.
- Cache every model response keyed by (instance, step, prompt hash) so a re-run costs nothing.
- Develop on 2 or 3 easy instances; run all 10 only when the prompt is stable.
- Keep the fallback chain in config, for example Gemini, then Groq, then Hugging Face, and log which provider served each call.

## Docker safety and fallbacks

Local Docker is acceptable here because only you run it, on curated issues. It is not safe to expose to strangers.

Safety rules:

- Run LLM-written code only with `--network none`; allow network only during the image build.
- Always set `--memory`, `--cpus`, `--pids-limit`, a timeout, and `--rm`.
- Never mount your home folder or the Docker socket into a container.
- Do not accept arbitrary repo or issue URLs in the demo. Issue text is untrusted input and can contain instructions aimed at the model.
- Keep API keys in environment variables on the host, never inside an image or container.

If something breaks:

| Problem | Fallback |
| --- | --- |
| An instance won't build | Drop it and take the next one from the dataset; don't spend more than 30 minutes per instance. |
| Free API rate-limited during the demo | Replay the cached run, and say clearly that it is a replay. |
| Model won't follow the action format | Shorten the prompt, show one worked example, lower the temperature, or switch provider. |
| Success rate is low (under 3 of 10) | Present it honestly: the pipeline, the verifier and the failure analysis are the contribution. |
| Day 2 ends with no working loop | Hard-code the LLM call as a single prompt (issue to script, no search or read steps), run it through the verifier, and demo that. |

## Definition of done and demo checklist

You are done when a stranger can watch one issue go from bug report to verified repro, and you can state your measured success rate.

- [ ] Verifier works: fails before, passes after, with the cheap-failure checks.
- [ ] LLM loop runs on your 10 curated issues, with logs saved.
- [ ] Success rate and failure causes written down, misses included.
- [ ] Web page runs one issue live and shows script, badges and logs.
- [ ] Cached replay and a 2-minute backup video ready.
- [ ] One slide that states the limits plainly: pure-Python, bug issues, validated on already-fixed bugs, SWE-bench issues may be memorized by models.

## Sources

Figures below come from search results seen on 2026-10-27 and were not re-checked against the live pages; confirm them in each provider's console.

- [Inference Providers pricing, Hugging Face](https://huggingface.co/docs/inference-providers/pricing)
- [Free LLM API Comparison 2026, Novita](https://blogs.novita.ai/free-llm-api-comparison-2026/)
- [Hugging Face provider setup, Docker docs](https://docs.docker.com/ai/docker-agent/providers/huggingface/)
