"""The `parallax` command line: init, run, rule, status."""
from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from parallax import seats
from parallax.conductor import Conductor
from parallax.config import CONFIG_NAME, SAMPLE_TOML, ConfigError, load_config
from parallax.decisions import render_card
from parallax.gitops import GitError

# Exit codes by outcome status; anything else (e.g. "stopped") counts as a stop that needs attention.
_EXIT = {"landed": 0, "needs_ruling": 2, "parked": 3, "blocked": 3, "dropped": 3}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="parallax", description="Pair two agent CLIs on one task.")
    sub = parser.add_subparsers(dest="command", required=True, metavar="{init,run,rule,status}")

    def repo(p):
        p.add_argument("--repo", default=".", metavar="PATH", help="project root (default: current directory)")

    p = sub.add_parser("init", help="write parallax.toml and the .parallax folder")
    repo(p)
    p = sub.add_parser("run", help="run or resume a task")
    p.add_argument("task_file", metavar="TASK_FILE")
    repo(p)
    p.add_argument("--builder", metavar="SEAT", help="seat that builds (default: from config)")
    p = sub.add_parser("rule", help="rule on a dispute")
    p.add_argument("dispute", metavar="DISPUTE")
    p.add_argument("choice", choices=["a", "b", "other", "drop"])
    repo(p)
    p.add_argument("--note", default="", metavar="TEXT")
    p.add_argument("--scope", choices=["task", "project"])
    p.add_argument("--while", dest="while_", default="", metavar="TEXT")
    p.add_argument("--limitation", default="", metavar="TEXT")
    p = sub.add_parser("status", help="list tasks and what they wait on")
    repo(p)
    return parser


def _init(root: Path) -> int:
    if not root.is_dir():
        raise ValueError(f"{root} is not a folder")
    if (root / CONFIG_NAME).exists():
        raise ValueError(f"{CONFIG_NAME} already exists")
    (root / ".parallax").mkdir(exist_ok=True)
    (root / CONFIG_NAME).write_text(SAMPLE_TOML, encoding="utf-8", newline="\n")
    (root / ".parallax" / ".gitignore").write_text("run/\n", encoding="utf-8", newline="\n")
    ledger = root / ".parallax" / "ledger.jsonl"
    if not ledger.exists():
        ledger.write_text("", encoding="utf-8")
    print(f"wrote {CONFIG_NAME} and .parallax/ in {root.name or root}")
    print("edit parallax.toml, commit these files, then: parallax run TASK_FILE")
    return 0


def _run(args, root: Path) -> int:
    cfg = load_config(root)
    conductor = Conductor(cfg, seats.make_seats(cfg), say=print)
    outcome = conductor.run(Path(args.task_file), builder=args.builder)
    for dispute in outcome.disputes:
        print()
        print(render_card(dispute), end="")
        print()
    print(f"{outcome.task}: {outcome.status}" + (f"  {outcome.detail}" if outcome.detail else ""))
    return _EXIT.get(outcome.status, 3)


def _rule(args, root: Path) -> int:
    conductor = Conductor(load_config(root), {}, say=print)
    conductor.rule(args.dispute, args.choice, note=args.note, scope=args.scope,
                   while_=args.while_, limitation=args.limitation)
    print(f"recorded {args.dispute}: {args.choice}")
    print("continue with: parallax run TASK_FILE")
    return 0


def _status(root: Path) -> int:
    for row in Conductor(load_config(root), {}, say=print).status():
        print("  ".join([row["task"], row["status"], *([" ".join(row["pending"])] if row["pending"] else [])]))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.repo)
    try:
        if args.command == "init":
            return _init(root)
        if args.command == "run":
            return _run(args, root)
        if args.command == "rule":
            return _rule(args, root)
        return _status(root)
    except (ConfigError, GitError, ValueError, RuntimeError) as exc:
        print(f"parallax: {exc}", file=sys.stderr)
        return 1
