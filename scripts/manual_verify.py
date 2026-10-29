import argparse

from src.config import REPROS_DIR
from src.verify import verify


INSTANCE_ID = "pytest-dev__pytest-7168"
REPRO_PATH = REPROS_DIR / "pytest-7168.py"


def main() -> int:
    argparse.ArgumentParser(
        description="Verify the pytest-7168 reproduction and reject assert False."
    ).parse_args()

    correct_script = REPRO_PATH.read_text(encoding="utf-8")
    correct_result = verify(INSTANCE_ID, correct_script)
    print("Correct reproduction: {}".format("PASS" if correct_result.passed else "FAIL"))
    print(correct_result.reason)
    if not correct_result.passed:
        return 1

    incorrect_result = verify(INSTANCE_ID, "assert False\n")
    print(
        "Deliberately incorrect reproduction: {}".format(
            "REJECTED" if not incorrect_result.passed else "INCORRECTLY ACCEPTED"
        )
    )
    print(incorrect_result.reason)
    return 0 if not incorrect_result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
