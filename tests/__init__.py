"""Test-run setup: every file a test writes stays inside this repo, in the ignored `.superpowers/` folder.

Nothing goes to %TEMP% (parallel agent sessions share it, and one wiped it on 2026-11-17).
Each test run gets its own folder, `.superpowers/tmp/tests/run-<pid>-<time>/`, so parallel runs
never touch each other's files, and removes only that folder when it ends. Tests that create
folders with `tempfile` land there because `tempfile.tempdir` points there, and the state home
(`PARALLAX_HOME`) points there too.

GIT_CEILING_DIRECTORIES stops git from walking up out of a test folder into this repo: a test
folder without its own `.git` must never be mistaken for part of Parallax's own repository.
"""
import atexit
import os
import tempfile
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_TESTS_TMP = _REPO / ".superpowers" / "tmp" / "tests"
RUN_DIR = _TESTS_TMP / f"run-{os.getpid()}-{time.strftime('%Y%m%d-%H%M%S')}"
RUN_DIR.mkdir(parents=True, exist_ok=False)

tempfile.tempdir = str(RUN_DIR)
os.environ["TMP"] = os.environ["TEMP"] = os.environ["TMPDIR"] = str(RUN_DIR)  # for child processes
os.environ["PARALLAX_HOME"] = str(RUN_DIR / "state-home")
os.environ["GIT_CEILING_DIRECTORIES"] = str(_TESTS_TMP)


def _remove_run_dir() -> None:
    # Remove only this run's own folder, after checking it is exactly where it was made.
    if RUN_DIR.parent == _TESTS_TMP and RUN_DIR.name.startswith("run-"):
        from parallax.gitops import remove_tree
        remove_tree(RUN_DIR)


if not os.environ.get("PARALLAX_KEEP_TEST_FILES"):
    atexit.register(_remove_run_dir)
