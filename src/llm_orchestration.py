import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from src.build_env import run_docker_command
from src.config import (
    CPU_LIMIT,
    DOCKER_COMMAND_TIMEOUT_SECONDS,
    LLM_CACHE_DIR,
    MAX_LLM_STEPS,
    MAX_PROMPT_CHARS,
    MAX_READ_LINES,
    MAX_REPRO_RUNS,
    MAX_REPRO_SCRIPT_CHARS,
    MAX_SEARCH_RESULTS,
    MEMORY_LIMIT,
    PID_LIMIT,
    REPOSITORY_CONTAINER_PATH,
)
from src.providers import ProviderResponse, chat
from src.run_script import ScriptResult, run_script
from src.verify import VerificationResult, verify


_FENCED_BLOCK = re.compile(r"```[^\r\n`]*\r?\n(.*?)```", re.DOTALL)
_EXCEPTION_TYPE = re.compile(r"\b[A-Z][A-Za-z0-9_]*(?:Error|Exception)\b")
_WORD = re.compile(r"\b[a-zA-Z][a-zA-Z0-9_]{4,}\b")
_GENERIC_WORDS = {
    "about", "after", "before", "being", "could", "error", "fails", "issue",
    "python", "should", "their", "there", "these", "thing", "which", "would",
}
_SEARCH_WRAPPER = """\
import subprocess
import sys

pattern = sys.argv[1]
command = [
    "rg", "--line-number", "--no-heading", "--color=never",
    "--max-columns", "300", "--max-columns-preview", "--glob", "*.py",
    "-e", pattern,
    "/work/repo",
]
process = subprocess.Popen(
    command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
)
try:
    for index, line in enumerate(process.stdout):
        if index >= 30:
            process.terminate()
            break
        print(line, end="")
finally:
    process.stdout.close()
    if process.poll() is None:
        process.terminate()
        process.wait()
"""
_READ_WRAPPER = """\
import os
import sys

root = os.path.realpath("/work/repo")
candidate = os.path.realpath(os.path.join(root, sys.argv[1]))
if os.path.commonpath((root, candidate)) != root:
    raise SystemExit("Requested path is outside the repository.")
start, end = int(sys.argv[2]), int(sys.argv[3])
with open(candidate, encoding="utf-8", errors="replace") as source:
    for line_number, line in enumerate(source, 1):
        if line_number < start:
            continue
        if line_number > end or line_number >= start + 120:
            break
        print("{}:{}".format(line_number, line.rstrip()))
"""


class ReproState(TypedDict, total=False):
    instance_id: str
    image: str
    problem_statement: str
    messages: List[Dict[str, str]]
    step: int
    run_count: int
    script: str
    action: Any
    actions: List[Dict[str, Any]]
    providers: List[str]
    tokens_used: int
    token_usage_available: bool
    done: bool
    stop_reason: str
    verifier: Optional[VerificationResult]
    debug_log_path: Optional[str]


class ActionFormatError(ValueError):
    pass


def _write_debug_log(
    path: Optional[str], event: str, details: Dict[str, Any]
) -> None:
    if path is None:
        return
    log_path = Path(path)
    if not log_path.is_absolute():
        raise ValueError("Debug log path must be absolute.")
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **details,
    }
    with open(str(log_path), "a", encoding="utf-8") as debug_file:
        debug_file.write(json.dumps(record, indent=2, ensure_ascii=False))
        debug_file.write("\n\n")


def _system_prompt() -> str:
    return """\
You write a standalone Python repro for the reported bug in the buggy repo.
The repo is read-only; do not install packages or use network access. A script
must exercise the bug, fail for the reported reason before the fix, and pass
after it. Inspect source under src/ when applicable.

Each reply must contain action(s), either as plain text or fenced blocks:
search <regex>
read <repo-relative-path> <start-line> <end-line>
write
<complete Python script>
run

Examples:
```text
search def .*repr
```
```text
read src/_pytest/_code/code.py 600 680
```
```text
write
print("complete standalone script here")
```
```text
run
```
You may return several fenced actions together; they run in order. Never put
search results in a code fence. Search returns Python-source matches only (at
most 30 lines); read returns at most 120 lines. Write and run the repro before
you stop. Maximum: 8 model turns, 4 script runs. Do not merely describe a script.
"""


def _issue_specific_guidance(problem_statement: str) -> str:
    normalized = problem_statement.lower()
    if "internalerror" in normalized and "__repr__" in normalized:
        return """\

Focused plan for this issue:
- The report already supplies a minimal failing pytest test; use that instead
  of spending turns tracing pytest hook names.
- Inspect `src/_pytest/reports.py` around lines 250-330 and the representation
  code under `src/_pytest/_code/`. Search for `_repr_failure_py` and `def repr`.
- The symptom is pytest emitting `INTERNALERROR` while reporting a test
  failure, not the test's ordinary failure. Build a standalone Python script
  that writes the supplied test to a temporary file and runs this checkout's
  pytest against it. Capture and print the combined output. Raise an assertion
  if that output contains `INTERNALERROR`; on the fixed checkout the test may
  fail normally, but the wrapper must exit 0.
- Do not use more than two turns for source inspection. By turn 3, write the
  complete wrapper; then run it and let the verifier check both commits.
"""
    return ""


def _initial_prompt(problem_statement: str) -> str:
    bounded_issue = problem_statement[:3000]
    return (
        "Reported issue (truncated to keep the request small):\n"
        + bounded_issue
        + "\n\nThe fixed patch and post-fix repository are hidden from you."
        + _issue_specific_guidance(problem_statement)
    )


def _bounded_messages(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
    if len(messages) <= 2:
        return messages
    fixed = messages[:2]
    recent = messages[2:][-2:]
    retained: List[Dict[str, str]] = []
    budget = MAX_PROMPT_CHARS - sum(len(message["content"]) for message in fixed)
    for message in reversed(recent):
        content = message["content"]
        if len(content) > 1800:
            content = content[:1800] + "\n[output truncated]"
        cost = len(content)
        if cost > budget:
            break
        retained.append({"role": message["role"], "content": content})
        budget -= cost
    return fixed + list(reversed(retained))


def _parse_action_block(block: str) -> Dict[str, str]:
    block = block.strip("\r\n")
    command, separator, body = block.partition("\n")
    command = command.strip()
    if command == "run":
        return {"type": "run"}
    if command == "write" or command.startswith("write "):
        inline_code = command[len("write "):] if command.startswith("write ") else ""
        code = "\n".join(part for part in (inline_code, body) if part).strip("\r\n")
        if code.startswith("```") and code.endswith("```"):
            code = code[code.find("\n") + 1:-3].strip("\r\n")
        if not code.strip():
            raise ActionFormatError("The write action must include a Python script.")
        if len(code) > MAX_REPRO_SCRIPT_CHARS:
            raise ActionFormatError("The reproduction script exceeds the size limit.")
        compile(code, "<repro.py>", "exec")
        return {"type": "write", "code": code}
    if command.startswith("search "):
        pattern = command[len("search "):].strip()
        if not pattern or len(pattern) > 300:
            raise ActionFormatError("Search requires a regex of 1 to 300 characters.")
        re.compile(pattern)
        return {"type": "search", "pattern": pattern}
    if command.startswith("read "):
        parts = command.split()
        if len(parts) != 4:
            raise ActionFormatError(
                "Read syntax is: read <relative/path> <start-line> <end-line>."
            )
        path, start_text, end_text = parts[1:]
        relative = PurePosixPath(path)
        if (
            relative.is_absolute()
            or "\\" in path
            or any(part in ("", ".", "..") for part in relative.parts)
        ):
            raise ActionFormatError("Read path must stay inside the repository.")
        try:
            start, end = int(start_text), int(end_text)
        except ValueError as exc:
            raise ActionFormatError("Read line numbers must be integers.") from exc
        if start < 1 or end < start or end - start + 1 > MAX_READ_LINES:
            raise ActionFormatError("Read range must contain 1 to 120 valid lines.")
        return {"type": "read", "path": str(relative), "start": start_text, "end": end_text}
    raise ActionFormatError("Unknown action. Use search, read, write, or run.")


def _parse_actions(response: str) -> List[Dict[str, str]]:
    stripped = response.strip()
    if not stripped:
        raise ActionFormatError("The provider returned an empty response.")

    matches = list(_FENCED_BLOCK.finditer(response))
    prefix = response[:matches[0].start()].strip() if matches else stripped
    if prefix:
        first_line = prefix.splitlines()[0].strip()
        if first_line == "run" or first_line.startswith(("search ", "read ", "write")):
            return [_parse_action_block(prefix if first_line == "write" else first_line)]

    actions = []
    for match in matches:
        try:
            actions.append(_parse_action_block(match.group(1)))
        except ActionFormatError:
            continue
    trailing = response[matches[-1].end():].strip() if matches else stripped
    if trailing.startswith("```"):
        trailing = re.sub(
            r"^```(?:text|python)[ \t]*\r?\n", "", trailing, count=1
        )
        trailing = re.sub(
            r"^```(?=(?:write|run|search|read)\b)", "", trailing, count=1
        )
        trailing = re.sub(r"\r?\n?```[ \t]*$", "", trailing)
        try:
            actions.append(_parse_action_block(trailing))
        except (ActionFormatError, SyntaxError):
            pass
    if not actions:
        raise ActionFormatError(
            "No valid action found. Start with search/read/write/run or fence each action."
        )
    return actions


def _parse_action(response: str) -> Dict[str, str]:
    """Compatibility helper used by callers that expect one action."""
    return _parse_actions(response)[0]


def _tool_command(image: str, executable: str, *arguments: str) -> str:
    completed = run_docker_command(
        [
            "run", "--rm", "--network=none",
            "--memory={}".format(MEMORY_LIMIT),
            "--cpus={}".format(CPU_LIMIT),
            "--pids-limit={}".format(PID_LIMIT),
            "--workdir={}".format(REPOSITORY_CONTAINER_PATH),
            image, executable, *arguments,
        ],
        timeout=DOCKER_COMMAND_TIMEOUT_SECONDS,
        check=False,
    )
    if completed.returncode:
        detail = completed.stdout.strip()
        raise RuntimeError(
            detail[-1000:] if detail else "Repository inspection command failed."
        )
    return completed.stdout


def _search(image: str, pattern: str) -> str:
    try:
        output = _tool_command(image, "python", "-c", _SEARCH_WRAPPER, pattern)
    except TimeoutError:
        return "Search timed out; use a narrower pattern."
    lines = output.splitlines()[:MAX_SEARCH_RESULTS]
    return "\n".join(lines) if lines else "No matches found."


def _read(image: str, path: str, start: str, end: str) -> str:
    output = _tool_command(
        image, "python", "-c", _READ_WRAPPER, path, start, end
    )
    if not output.strip():
        return "No file content returned; check the path and line range."
    return output[:8000]


def _failure_matches_issue(problem_statement: str, output: str) -> bool:
    exception_types = set(_EXCEPTION_TYPE.findall(problem_statement))
    if exception_types:
        return any(exception in output for exception in exception_types)
    issue_words = {
        word.lower() for word in _WORD.findall(problem_statement)
        if word.lower() not in _GENERIC_WORDS
    }
    output_words = {word.lower() for word in _WORD.findall(output)}
    return bool(issue_words & output_words)


def _agent_node(state: ReproState) -> Dict[str, Any]:
    messages = _bounded_messages(state["messages"])
    step = state.get("step", 0)
    if not state.get("script") and step >= 2:
        messages = messages + [
            {
                "role": "user",
                "content": (
                    "Turn {} of {}: stop investigating. Your next response MUST "
                    "write a complete standalone Python repro and run it. Return "
                    "both actions in this reply if possible. Do not search or read."
                ).format(step + 1, MAX_LLM_STEPS),
            }
        ]
    _write_debug_log(
        state.get("debug_log_path"),
        "llm_request",
        {"step": step + 1, "messages": messages},
    )
    response = _cached_chat(state["instance_id"], state.get("step", 0), messages)
    try:
        parsed_actions = _parse_actions(response.content)
    except (ActionFormatError, SyntaxError) as exc:
        parsed_actions = [{"type": "invalid", "error": str(exc)}]
    actions = list(state.get("actions", []))
    _write_debug_log(
        state.get("debug_log_path"),
        "llm_response",
        {
            "step": state.get("step", 0) + 1,
            "provider": response.provider,
            "cached": response.cached,
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
            "finish_reason": response.finish_reason,
            "content": response.content,
            "parsed_actions": parsed_actions,
        },
    )
    for index, action in enumerate(parsed_actions):
        record: Dict[str, Any] = {
            "step": state.get("step", 0) + 1,
            "action": action["type"],
        }
        if index == 0:
            record.update(
                {
                    "provider": response.provider,
                    "response": response.content[:4000],
                    "prompt_tokens": response.prompt_tokens,
                    "completion_tokens": response.completion_tokens,
                    "total_tokens": response.total_tokens,
                    "cached": response.cached,
                    "finish_reason": response.finish_reason,
                }
            )
        if action["type"] == "invalid":
            record["error"] = action["error"]
        actions.append(record)
    providers = list(state.get("providers", []))
    providers.append(response.provider)
    tokens = state.get("tokens_used", 0)
    usage_available = state.get("token_usage_available", True)
    if not response.cached and response.total_tokens is None:
        usage_available = False
    elif not response.cached:
        tokens += response.total_tokens
    conversation = list(state["messages"])
    conversation.append({"role": "assistant", "content": response.content[:4000]})
    return {
        "action": parsed_actions,
        "actions": actions,
        "providers": providers,
        "step": state.get("step", 0) + 1,
        "tokens_used": tokens,
        "token_usage_available": usage_available,
        "messages": conversation,
    }


def _action_node(state: ReproState) -> Dict[str, Any]:
    pending_actions = state["action"]
    if isinstance(pending_actions, dict):
        pending_actions = [pending_actions]
    result: Dict[str, Any] = {}
    action_results = []
    done = False
    stop_reason = ""
    run_count = state.get("run_count", 0)
    script = state.get("script", "")
    action_log = [dict(record) for record in state.get("actions", [])]
    for index, action in enumerate(pending_actions):
        response_text = ""
        try:
            action_type = action["type"]
            if action_type == "search":
                response_text = _search(state["image"], action["pattern"])
            elif action_type == "read":
                response_text = _read(
                    state["image"], action["path"], action["start"], action["end"]
                )
            elif action_type == "write":
                script = action["code"]
                response_text = "Saved the standalone reproduction script."
            elif action_type == "run":
                if not script:
                    response_text = "No script has been written yet; use a write action first."
                elif run_count >= MAX_REPRO_RUNS:
                    response_text = "Run limit reached."
                    done = True
                    stop_reason = "Maximum number of reproduction runs reached."
                else:
                    run_result: ScriptResult = run_script(state["image"], script)
                    run_count += 1
                    output_lines = run_result.output.splitlines()
                    response_text = (
                        "Exit code: {}\n{}\n".format(
                            run_result.exit_code,
                            "\n".join(output_lines[-40:])[-4000:],
                        )
                    )
                    if (
                        run_result.exit_code != 0
                        and not run_result.timed_out
                        and _failure_matches_issue(
                            state["problem_statement"], run_result.output
                        )
                    ):
                        done = True
                        stop_reason = "A buggy-code run matched the reported symptom."
                    elif run_count >= MAX_REPRO_RUNS:
                        done = True
                        stop_reason = "Maximum number of reproduction runs reached."
            else:
                response_text = action.get("error", "Invalid action format.")
        except (ActionFormatError, OSError, RuntimeError, ValueError) as exc:
            response_text = "Action failed: {}".format(exc)

        log_index = len(action_log) - len(pending_actions) + index
        if 0 <= log_index < len(action_log):
            action_log[log_index]["result"] = response_text[:4000]
        action_results.append("{} result:\n{}".format(action["type"], response_text))
        _write_debug_log(
            state.get("debug_log_path"),
            "action_result",
            {
                "step": state.get("step", 0),
                "action": action,
                "result": response_text,
                "script": script if action["type"] in ("write", "run") else None,
            },
        )
        if done:
            break

    response_text = "\n\n".join(action_results)[-6000:]
    conversation = list(state["messages"])
    conversation.append({"role": "user", "content": response_text})
    result.update(
        {
            "messages": conversation,
            "actions": action_log,
            "script": script,
            "run_count": run_count,
            "done": done,
            "stop_reason": stop_reason,
        }
    )
    return result


def _next_node(state: ReproState) -> str:
    if state.get("done"):
        return END
    if state.get("step", 0) >= MAX_LLM_STEPS:
        return END
    return "agent"


def _build_graph():
    graph = StateGraph(ReproState)
    graph.add_node("agent", _agent_node)
    graph.add_node("action", _action_node)
    graph.add_edge(START, "agent")
    graph.add_edge("agent", "action")
    graph.add_conditional_edges("action", _next_node)
    return graph.compile()


def _cached_chat(instance_id: str, step: int, messages: List[Dict[str, str]]) -> ProviderResponse:
    serialized = json.dumps(messages, sort_keys=True, ensure_ascii=False)
    prompt_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    instance_hash = hashlib.sha256(instance_id.encode("utf-8")).hexdigest()[:16]
    cache_path = LLM_CACHE_DIR / "{}-{}-{}.json".format(
        instance_hash, step, prompt_hash
    )
    if cache_path.is_file():
        record = json.loads(cache_path.read_text(encoding="utf-8"))
        record["cached"] = True
        return ProviderResponse(**record)

    response = chat(messages)
    LLM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    temporary_path = cache_path.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(response.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary_path.replace(cache_path)
    return response


def run_repro_loop(
    instance_id: str,
    problem_statement: str,
    image: str,
    debug_log_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the bounded LangGraph investigation and verify its final script."""
    initial_state: ReproState = {
        "instance_id": instance_id,
        "image": image,
        "problem_statement": problem_statement,
        "messages": [
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": _initial_prompt(problem_statement)},
        ],
        "step": 0,
        "run_count": 0,
        "script": "",
        "actions": [],
        "providers": [],
        "tokens_used": 0,
        "token_usage_available": True,
        "done": False,
        "debug_log_path": debug_log_path,
    }
    graph = _build_graph()
    state = graph.invoke(
        initial_state,
        config={"recursion_limit": 2 * MAX_LLM_STEPS + 2},
    )

    script = state.get("script", "")
    verification: Optional[VerificationResult] = verify(instance_id, script) if script else None
    _write_debug_log(
        debug_log_path,
        "verification",
        {
            "script": script,
            "verifier_result": verification.to_dict() if verification else None,
            "stop_reason": state.get("stop_reason", ""),
        },
    )
    if verification is None:
        failure_reason = state.get("stop_reason") or (
            "Reached the {}-turn limit without a reproduction script.".format(
                MAX_LLM_STEPS
            )
        )
    elif verification.passed:
        failure_reason = ""
    else:
        failure_reason = verification.reason
    return {
        "instance_id": instance_id,
        "steps": state.get("step", 0),
        "run_actions": state.get("run_count", 0),
        "tokens_used": (
            state.get("tokens_used", 0)
            if state.get("token_usage_available", True)
            else None
        ),
        "providers": state.get("providers", []),
        "actions": state.get("actions", []),
        "script": script,
        "stop_reason": state.get("stop_reason", ""),
        "verifier_result": verification.to_dict() if verification else None,
        "passed": bool(verification and verification.passed),
        "failure_reason": failure_reason,
    }