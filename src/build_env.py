import hashlib
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Sequence

from src.config import (
    DOCKER_BINARY,
    DOCKER_COMMAND_TIMEOUT_SECONDS,
    IMAGE_BUILD_TIMEOUT_SECONDS,
    PYTHON_VERSION_BY_REPOSITORY,
    REPOSITORY_CONTAINER_PATH,
)
from src.metadata import load_instance


_COMMIT_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")


class DockerCommandError(RuntimeError):
    pass


def run_docker_command(
    arguments: Sequence[str],
    timeout: int,
    input_text: Optional[str] = None,
    check: bool = True,
) -> subprocess.CompletedProcess:
    command = [DOCKER_BINARY, *arguments]
    try:
        result = subprocess.run(
            command,
            input=input_text,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Docker CLI was not found. Install Docker and ensure 'docker' is on PATH."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        raise TimeoutError(
            "Docker command timed out after {} seconds: {}\n{}".format(
                timeout, " ".join(command), output
            )
        ) from exc

    if check and result.returncode:
        raise DockerCommandError(
            "Docker command failed with exit code {}: {}\n{}".format(
                result.returncode, " ".join(command), result.stdout
            )
        )
    return result


def _image_tag(repository: str, version: str, base_commit: str) -> str:
    key = "\0".join((repository.lower(), version, base_commit.lower()))
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]
    repository_label = repository.lower().replace("/", "-")
    return "mre-{}-{}".format(repository_label, digest)


def build_environment(instance_id: str) -> str:
    """Build or reuse the pinned buggy checkout image for a SWE-bench instance."""
    instance = load_instance(instance_id)
    repository = str(instance["repo"]).lower()
    version = str(instance["version"])
    base_commit = str(instance["base_commit"])

    if not _COMMIT_PATTERN.fullmatch(base_commit):
        raise ValueError(
            "Instance {!r} has an invalid base commit.".format(instance_id)
        )

    python_version = PYTHON_VERSION_BY_REPOSITORY.get(repository)
    if python_version is None:
        raise ValueError(
            "No Python image version is configured for {!r}.".format(repository)
        )

    image = _image_tag(repository, version, base_commit)
    cached = run_docker_command(
        ["image", "inspect", image],
        timeout=DOCKER_COMMAND_TIMEOUT_SECONDS,
        check=False,
    )
    if cached.returncode == 0:
        return image

    dockerfile = """\
FROM python:{python_version}-slim
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
RUN apt-get update \\
    && apt-get install -y --no-install-recommends git \\
    && rm -rf /var/lib/apt/lists/*
RUN git clone --quiet --no-tags https://github.com/{repository}.git {repository_path} \\
&& git -C {repository_path} checkout --quiet --detach {base_commit} \\
&& python -m pip install --no-cache-dir --editable {repository_path}
WORKDIR {repository_path}
""".format(
        python_version=python_version,
        repository=repository,
        base_commit=base_commit,
        repository_path=REPOSITORY_CONTAINER_PATH,
    )

    with tempfile.TemporaryDirectory(prefix="mre-docker-build-") as build_context:
        dockerfile_path = Path(build_context) / "Dockerfile"
        dockerfile_path.write_text(dockerfile, encoding="utf-8")
        run_docker_command(
            [
                "build",
                "--network=default",
                "--tag",
                image,
                "--file",
                str(dockerfile_path),
                build_context,
            ],
            timeout=IMAGE_BUILD_TIMEOUT_SECONDS,
        )

    return image


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Build or reuse the Docker image for a shortlisted SWE-bench instance."
    )
    parser.add_argument("instance_id")
    args = parser.parse_args()

    print(build_environment(args.instance_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
