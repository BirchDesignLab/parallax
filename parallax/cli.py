"""The `parallax` command line: init, run, rule, status, demo."""
from __future__ import annotations

import argparse
import contextlib
import secrets
import sys
from collections.abc import Sequence
from pathlib import Path

from parallax import demo, gitops, seats
from parallax.conductor import Conductor, Outcome
from parallax.config import CONFIG_NAME, SAMPLE_TOML, ConfigError, load_config, state_home
from parallax.decisions import render_card
from parallax.gitops import GitError

# Exit codes by outcome status; anything else (e.g. "stopped") counts as a stop that needs attention.
_EXIT = {"landed": 0, "needs_ruling": 2, "parked": 3, "blocked": 3, "dropped": 3}


class _Parser(argparse.ArgumentParser):
    """Usage errors exit 1, like every other error: exit code 2 means only that a task needs a ruling."""

    def error(self, message: str):
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="parallax", description="Pair two agent CLIs on one task.")
    sub = parser.add_subparsers(dest="command", required=True, metavar="{init,run,rule,status,demo}")

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
    p = sub.add_parser("demo", help="build a throwaway project and run the v0 demonstration")
    p.add_argument("--dir", metavar="PATH", help="project folder (default: a new folder under the state home)")
    p.add_argument("--stub", action="store_true", help="use scripted seats: spends nothing")
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


def _report(outcome: Outcome) -> int:
    for dispute in outcome.disputes:
        print()
        print(render_card(dispute), end="")
        print()
    for card in outcome.cards:                 # a confirmed-v1 settlement's card, as recorded
        print()
        print(card["card_text"], end="")
        print()
    print(f"{outcome.task}: {outcome.status}" + (f"  {outcome.detail}" if outcome.detail else ""))
    return _EXIT.get(outcome.status, 3)


def _run(args, root: Path) -> int:
    cfg = load_config(root)
    conductor = Conductor(cfg, seats.make_seats(cfg), say=print)
    # A relative task path is the project's: `run tasks/x.md --repo <project>` works from anywhere.
    task_file = Path(args.task_file)
    if not task_file.is_absolute():
        task_file = root / task_file
    return _report(conductor.run(task_file, builder=args.builder))


def _demo(args) -> int:
    # Not tempfile: %TEMP% sits under %LOCALAPPDATA%, which a packaged app redirects (see state_home),
    # and mkdtemp makes the folder owner-only.
    where = Path(args.dir) if args.dir else state_home() / "demos" / f"clamp-{secrets.token_hex(4)}"
    where = where.resolve()         # git runs inside the project, so a relative path would not clone
    if not (where / CONFIG_NAME).exists():
        demo.make_fixture(where, args.stub)
    print(f"demo project: {where}")
    cfg = load_config(where)
    if args.stub and any(s.adapter != "stub" for s in cfg.seats):
        raise ValueError(f"{where} was made for the real seats; run `parallax demo --dir ...` without --stub")
    with demo.stub_adapter() if args.stub else contextlib.nullcontext():
        conductor = Conductor(cfg, seats.make_seats(cfg), say=print)
        outcome = conductor.run(where / demo.TASK_FILE)
    code = _report(outcome)
    again = f'python -m parallax demo --dir "{where}"' + (" --stub" if args.stub else "")
    if outcome.status == "landed":
        print()
        print("Receipt (the landing commit's message):")
        # A rerun after landing gets no commit back; find the landing by its trailer, not main's tip.
        # Task ids are [A-Za-z0-9._-]: only the dot means anything to a regex.
        commit = outcome.commit or gitops.git(where, "log", "-1", "--format=%H", "-E",
                                              f"--grep=^Parallax-Task: {outcome.task.replace('.', '[.]')}$", cfg.main)
        print(gitops.git(where, "log", "-1", "--format=%B", commit))
    elif outcome.status == "needs_ruling":
        for dispute in outcome.disputes:
            print(f'rule with: python -m parallax rule {dispute.id} a --repo "{where}"   (or b)')
        for card in outcome.cards:
            print(_rule_hint(card, where))
        print(f"then run: {again}")
    elif outcome.status in ("blocked", "parked"):
        print(f"after fixing the cause, run: {again}")
    return code


def _rule_hint(card: dict, where: Path) -> str:
    """How to rule on a confirmed-v1 card: its first allowed command, then the others it allows."""
    first, *others = [f"{command} --note TEXT" if command == "other" else command for command in card["allowed"]]
    return f'rule with: python -m parallax rule {card["id"]} {first} --repo "{where}"   (or {", ".join(others)})'


def _rule(args, root: Path) -> int:
    conductor = Conductor(load_config(root), {}, say=print)
    conductor.rule(args.dispute, args.choice, note=args.note, scope=args.scope,
                   while_=args.while_, limitation=args.limitation)
    print(f"recorded {args.dispute}: {args.choice}")
    print("continue with: parallax run TASK_FILE")
    return 0


def _status(root: Path) -> int:
    for row in Conductor(load_config(root), {}, say=print).status():
        print("  ".join([row["task"], row["status"], *([" ".join(row["pending"])] if row["pending"] else []),
                         *([row["detail"]] if row.get("detail") else [])]))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(getattr(args, "repo", ".")).resolve()     # git runs inside the project: a relative root would not clone
    try:
        if args.command == "demo":
            return _demo(args)
        if args.command == "init":
            return _init(root)
        if args.command == "run":
            return _run(args, root)
        if args.command == "rule":
            return _rule(args, root)
        return _status(root)
    except FileNotFoundError as exc:
        print(f"parallax: file not found: {exc.filename}", file=sys.stderr)
        return 1
    except (ConfigError, GitError, ValueError, RuntimeError) as exc:
        print(f"parallax: {exc}", file=sys.stderr)
        return 1
