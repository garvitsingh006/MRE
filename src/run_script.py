import argparse
import json
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional, Union

from src.build_env import DockerCommandError, run_docker_command
from src.config import (
    CPU_LIMIT,
    DOCKER_BINARY,
    DOCKER_COMMAND_TIMEOUT_SECONDS,
    EXECUTION_TIMEOUT_SECONDS,
    MEMORY_LIMIT,
    OUTPUT_TAIL_LINES,
    PID_LIMIT,
    REPOSITORY_CONTAINER_PATH,
    REPRO_CONTAINER_PATH,
)


@dataclass
class ScriptResult:
    exit_code: int
    output: str
    timed_out: bool = False


def _last_lines(output: str, line_count: int = OUTPUT_TAIL_LINES) -> str:
    lines = output.splitlines()
    return "\n".join(lines[-line_count:])


def _decode_timeout_output(output: Optional[Union[str, bytes]]) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output


def run_script(
    image: str,
    repro_script: Union[str, Path],
    patch: Optional[str] = None,
) -> ScriptResult:
    """Run one script in a new network-isolated container and remove it afterward."""
    with tempfile.TemporaryDirectory(prefix="mre-repro-") as script_directory:
        if isinstance(repro_script, Path):
            script_path = repro_script.resolve(strict=True)
        else:
            script_path = Path(script_directory) / "repro.py"
            script_path.write_text(repro_script, encoding="utf-8")

        container_result = run_docker_command(
            [
                "run",
                "--detach",
                "--rm",
                "--network=none",
                "--memory={}".format(MEMORY_LIMIT),
                "--cpus={}".format(CPU_LIMIT),
                "--pids-limit={}".format(PID_LIMIT),
                "--workdir={}".format(REPOSITORY_CONTAINER_PATH),
                image,
                "python",
                "-c",
                "import time; time.sleep(3600)",
            ],
            timeout=DOCKER_COMMAND_TIMEOUT_SECONDS,
        )
        container_id = container_result.stdout.strip()
        if not container_id:
            raise DockerCommandError("Docker did not return a container ID.")

        try:
            run_docker_command(
                [
                    "cp",
                    str(script_path),
                    "{}:{}".format(container_id, REPRO_CONTAINER_PATH),
                ],
                timeout=DOCKER_COMMAND_TIMEOUT_SECONDS,
            )

            if patch is not None:
                run_docker_command(
                    [
                        "exec",
                        "--interactive",
                        container_id,
                        "git",
                        "apply",
                        "--whitespace=nowarn",
                        "-",
                    ],
                    timeout=DOCKER_COMMAND_TIMEOUT_SECONDS,
                    input_text=patch,
                )

            command = [
                DOCKER_BINARY,
                "exec",
                "--workdir={}".format(REPOSITORY_CONTAINER_PATH),
                container_id,
                "python",
                REPRO_CONTAINER_PATH,
            ]
            try:
                completed = subprocess.run(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=False,
                    timeout=EXECUTION_TIMEOUT_SECONDS,
                    check=False,
                )
                # Docker/Linux output is UTF-8; never decode it using the
                # Windows console's cp1252 locale.
                output = _decode_timeout_output(completed.stdout)
                return ScriptResult(
                    exit_code=completed.returncode,
                    output=_last_lines(output),
                )
            except FileNotFoundError as exc:
                raise RuntimeError(
                    "Docker CLI was not found. Install Docker and ensure 'docker' is on PATH."
                ) from exc
            except subprocess.TimeoutExpired as exc:
                output = _decode_timeout_output(exc.stdout)
                timeout_message = (
                    "Reproduction exceeded the {}-second timeout.".format(
                        EXECUTION_TIMEOUT_SECONDS
                    )
                )
                if output:
                    output += "\n"
                output += timeout_message
                return ScriptResult(
                    exit_code=124,
                    output=_last_lines(output),
                    timed_out=True,
                )
        finally:
            cleanup = run_docker_command(
                ["rm", "--force", container_id],
                timeout=DOCKER_COMMAND_TIMEOUT_SECONDS,
                check=False,
            )
            if cleanup.returncode:
                raise DockerCommandError(
                    "Could not remove temporary container {}: {}".format(
                        container_id, cleanup.stdout
                    )
                )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a Python reproduction in an isolated cached Docker image."
    )
    parser.add_argument("image")
    parser.add_argument("script", type=Path)
    parser.add_argument("--patch", type=Path)
    args = parser.parse_args()

    patch_text = args.patch.read_text(encoding="utf-8") if args.patch else None
    result = run_script(
        args.image,
        args.script,
        patch=patch_text,
    )
    print(json.dumps(asdict(result), indent=2))
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
