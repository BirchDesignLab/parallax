"""Run one shard of the test suite, so CI can run the shards side by side.

    python scripts/ci/run_tests.py --shard 2 --of 4
    python scripts/ci/run_tests.py --list --of 4      (print the split, run nothing)

The test modules (tests/test_*.py) are split into `--of` groups. The split is the same on
every machine: modules are taken largest file first and each goes to the group that is
lightest so far, with file size standing in for run time. Every module lands in exactly
one group, so the shards together run the whole suite; `--list` shows the split.

The shard runs as `python -m unittest -v --durations 15 <modules>`, one line per test, from
the repository root. The exit code is unittest's.
"""
import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def split(of: int) -> list[list[str]]:
    """The test modules in `of` groups, balanced by file size."""
    files = sorted((REPO / "tests").glob("test_*.py"), key=lambda p: (-p.stat().st_size, p.name))
    groups: list[list[str]] = [[] for _ in range(of)]
    weights = [0] * of
    for path in files:
        lightest = weights.index(min(weights))
        groups[lightest].append(f"tests.{path.stem}")
        weights[lightest] += path.stat().st_size
    return [sorted(group) for group in groups]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one shard of the test suite.")
    parser.add_argument("--shard", type=int, help="which group to run, from 1")
    parser.add_argument("--of", type=int, required=True, help="how many groups the suite is split into")
    parser.add_argument("--list", action="store_true", help="print the split and run nothing")
    args = parser.parse_args()
    if args.of < 1:
        parser.error("--of must be at least 1")
    groups = split(args.of)
    if args.list:
        for number, group in enumerate(groups, 1):
            print(f"shard {number} of {args.of}: {' '.join(group)}")
        return 0
    if args.shard is None or not 1 <= args.shard <= args.of:
        parser.error(f"--shard must be between 1 and {args.of}")
    modules = groups[args.shard - 1]
    print(f"shard {args.shard} of {args.of}: {' '.join(modules) or '(no modules)'}", flush=True)
    if not modules:
        return 0
    return subprocess.run([sys.executable, "-m", "unittest", "-v", "--durations", "15", *modules], cwd=REPO).returncode


if __name__ == "__main__":
    sys.exit(main())
