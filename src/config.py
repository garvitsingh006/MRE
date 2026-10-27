from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = PROJECT_ROOT / "cache"
DATASET_CACHE_DIR = CACHE_DIR / "datasets"
SHORTLIST_PATH = PROJECT_ROOT / "shortlist.json"
REPROS_DIR = PROJECT_ROOT / "repros"
RUNS_DIR = PROJECT_ROOT / "runs"

DATASET_NAME = "princeton-nlp/SWE-bench_Lite"
DATASET_SPLIT = "test"
REPOSITORY_CONTAINER_PATH = "/work/repo"
REPRO_CONTAINER_PATH = "/work/repro.py"

ALLOWED_REPOSITORIES = frozenset(
    {
        "pallets/flask",
        "psf/requests",
        "pytest-dev/pytest",
        "pylint-dev/pylint",
        "sympy/sympy",
        "django/django",
    }
)

PYTHON_VERSION_BY_REPOSITORY = {
    repository: "3.8"
    for repository in ALLOWED_REPOSITORIES
}

DOCKER_BINARY = "docker"
EXECUTION_TIMEOUT_SECONDS = 60
DOCKER_COMMAND_TIMEOUT_SECONDS = 120
IMAGE_BUILD_TIMEOUT_SECONDS = 1800
MEMORY_LIMIT = "2g"
CPU_LIMIT = "2"
PID_LIMIT = 256
OUTPUT_TAIL_LINES = 60
