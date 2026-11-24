"""Run one shard of the test suite, so CI can run the shards side by side.

    python scripts/ci/run_tests.py --shard 2 --of 4
    python scripts/ci/run_tests.py --list --of 4      (print the split, run nothing)

The test modules (tests/test_*.py) are split into `--of` groups. The split is the same on
every machine: modules are taken slowest first and each goes to the group that is lightest
so far. A module's weight is its measured run time in SECONDS below, or an estimate from
its file size when it has none. Every module lands in exactly one group, so the shards
together run the whole suite; `--list` shows the split.

The shard runs as `python -m unittest -v --durations 15 <modules>`, one line per test, from
the repository root. The exit code is unittest's.
"""
import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


# Seconds each module took on the GitHub Windows runner (run 45432827961, 2026-11-24),
# measured with scripts/ci/module_times.py. Refresh them from a later run the same way.
SECONDS = {
    "tests.test_conductor_batch": 212,
    "tests.test_conductor_tail": 206,
    "tests.test_conductor_settled": 191,
    "tests.test_conductor_reading": 186,
    "tests.test_conductor_disputes": 177,
    "tests.test_conductor_accounting": 172,
    "tests.test_conductor_crossed": 165,
    "tests.test_conductor_marked": 143,
    "tests.test_conductor_acceptance": 114,
    "tests.test_conductor_ruled": 99,
    "tests.test_conductor_landing": 98,
    "tests.test_conductor_frozen": 72,
    "tests.test_demo": 41,
    "tests.test_crossing": 19,
    "tests.test_cli": 18,
    "tests.test_gitops": 12,
    "tests.test_briefs": 12,
    "tests.test_batch": 10,
    "tests.test_procs": 7,
    "tests.test_history_11_19": 2,
    # The rest each ran in about a second or less.
    "tests.test_config": 1,
    "tests.test_decisions": 1,
    "tests.test_delivery": 1,
    "tests.test_folders": 1,
    "tests.test_ledger": 1,
    "tests.test_live_seats": 1,
    "tests.test_receipt": 1,
    "tests.test_schemas": 1,
    "tests.test_scopes_audit": 1,
    "tests.test_seat_claude": 1,
    "tests.test_seat_codex": 1,
    "tests.test_seats_stub": 1,
}
# A module with no measurement (a new one) is weighed by its size at this rate, roughly the
# slow conductor modules' seconds per byte, so a new module is assumed slow until measured.
SECONDS_PER_BYTE = 0.003


def weight(path: Path) -> float:
    """How long a test module is expected to run, in seconds."""
    return SECONDS.get(f"tests.{path.stem}", max(1.0, path.stat().st_size * SECONDS_PER_BYTE))


def split(of: int) -> list[list[str]]:
    """The test modules in `of` groups, balanced by expected run time."""
    files = sorted((REPO / "tests").glob("test_*.py"), key=lambda p: (-weight(p), p.name))
    groups: list[list[str]] = [[] for _ in range(of)]
    weights = [0.0] * of
    for path in files:
        lightest = weights.index(min(weights))
        groups[lightest].append(f"tests.{path.stem}")
        weights[lightest] += weight(path)
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
