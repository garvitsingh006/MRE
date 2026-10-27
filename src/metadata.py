from functools import lru_cache
from typing import Any, Dict

from src.config import ALLOWED_REPOSITORIES, DATASET_CACHE_DIR, DATASET_NAME, DATASET_SPLIT


@lru_cache(maxsize=1)
def _load_instances() -> Any:
    try:
        from datasets import load_dataset
    except ImportError as exc:
        raise RuntimeError(
            "The 'datasets' package is required to load SWE-bench metadata."
        ) from exc

    return load_dataset(
        DATASET_NAME,
        split=DATASET_SPLIT,
        cache_dir=str(DATASET_CACHE_DIR),
    )


def load_instance(instance_id: str) -> Dict[str, Any]:
    if not instance_id:
        raise ValueError("instance_id must not be empty")

    for row in _load_instances():
        if row.get("instance_id") != instance_id:
            continue

        repository = str(row.get("repo", "")).lower()
        if repository not in ALLOWED_REPOSITORIES:
            raise ValueError(
                "Instance {!r} belongs to repository {!r}, which is not allowed."
                .format(instance_id, repository)
            )

        required_fields = (
            "base_commit",
            "version",
            "patch",
            "problem_statement",
        )
        missing_fields = [field for field in required_fields if not row.get(field)]
        if missing_fields:
            raise ValueError(
                "Instance {!r} is missing required metadata: {}."
                .format(instance_id, ", ".join(missing_fields))
            )

        return dict(row)

    raise KeyError("SWE-bench instance {!r} was not found.".format(instance_id))
