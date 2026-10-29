MRE DAY 1 - WINDOWS PATCH + UTF-8 FIX

WHAT WAS FIXED
- Docker patch input is now sent as raw UTF-8 bytes, avoiding Windows LF to CRLF rewriting.
- Docker stdout/stderr is decoded as UTF-8 with replacement so cp1252 errors are avoided.
- Adds regression tests for byte-safe patch input and output decoding.
- Adds visible progress messages to the real Docker smoke test.

APPLY TO YOUR CURRENT PROJECT
PowerShell (Docker test not running):
  Expand-Archive -Path .\MRE_Day1_Windows_Docker_Fix.zip -DestinationPath . -Force
  python -m unittest discover -s tests -v
  python -m scripts.day1_docker_smoke

Use Expand-Archive from within the project directory after copying this ZIP there.
Do not delete your .venv or existing Docker images.

A passing unit test does not prove a working Docker integration.
