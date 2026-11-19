"""`parallax demo`: a throwaway project with one underspecified task, and scripted seats to run it free."""
from __future__ import annotations

import contextlib
import re
import sys
from collections.abc import Iterator
from pathlib import Path

from parallax import gitops, seats
from parallax.gitops import GitError
from parallax.seats.base import Seat
from parallax.seats.stub import StubSeat

TASK_TEXT = "Add clamp(x, lo, hi) to clamplib: returns x limited to the range lo..hi.\n"
TASK_FILE = "tasks/clamp-001.md"

_FILE = "clamplib/__init__.py"
# The two readings of lo > hi: codex's (ruling `a`) raises, claude's counter (ruling `b`) swaps.
_RAISE = '        raise ValueError("lo > hi")\n'
_SWAP = "        lo, hi = hi, lo\n"
_COUNTER = "swap the bounds"


def _clamp(on_reversed: str) -> str:
    return f"def clamp(x, lo, hi):\n    if lo > hi:\n{on_reversed}    return max(lo, min(x, hi))\n"


def _mutants(on_reversed: str) -> dict[str, str]:
    good = _clamp(on_reversed)
    return {"m1": good.replace("max(lo, min(x, hi))", "max(lo, x)"),
            "m2": good.replace("max(lo, min(x, hi))", "min(x, hi)"),
            "m3": _clamp(_SWAP if on_reversed == _RAISE else _RAISE)}


_PROBES = ('import unittest\nfrom clamplib import clamp\n\n\nclass ClampProbes(unittest.TestCase):\n'
           '    def test_inside(self):\n        self.assertEqual(clamp(5, 1, 10), 5)\n\n'
           '    def test_low(self):\n        self.assertEqual(clamp(-3, 1, 10), 1)\n\n'
           '    def test_high(self):\n        self.assertEqual(clamp(99, 1, 10), 10)\n\n')
_REVERSED = {_RAISE: '    def test_reversed(self):\n        with self.assertRaises(ValueError):\n            clamp(5, 10, 1)\n',
             _SWAP: '    def test_reversed(self):\n        self.assertEqual(clamp(5, 10, 1), 5)\n'
                    '        self.assertEqual(clamp(0, 10, 1), 1)\n'}


_ANSWER = re.compile(r"^- Q: What if lo > hi\?\n  A: (.*) \((?:[^()\n]*)\)$", re.MULTILINE)


def _ruled(req) -> str | None:
    """The reading the frozen contract in the brief settled on: `_RAISE`, `_SWAP`, or None for any
    other answer (a ruling `other`), which these scripts cannot carry out and must not fake."""
    found = _ANSWER.findall(req.brief)
    answers = {"raise ValueError": _RAISE, _COUNTER: _SWAP}
    return answers.get(found[0]) if len(found) == 1 else None


_CANNOT = ("the scripted demo seats can carry out only ruling a (raise ValueError) or b (swap the bounds); "
           "run the demo again in a new folder")
_BASELINE = ("import unittest\n\n\nclass Baseline(unittest.TestCase):\n"
             "    def test_ok(self):\n        self.assertTrue(True)\n")


def _toml(stub: bool) -> str:
    # Literal (single-quoted) TOML strings keep the interpreter's backslashes as they are.
    adapter = 'adapter = "stub"\n' if stub else ""
    return (f"[project]\ncheck = '\"{sys.executable}\" -m unittest discover -s tests -t .'\n"
            f"lint = '\"{sys.executable}\" -m compileall -q .'\n"
            '[scopes]\nbuilder = ["clamplib/**"]\nchallenger = ["tests/**"]\n'
            f'[seats.codex]\n{adapter}model = "gpt-6.2-astra"\neffort = "xhigh"\n'
            f'[seats.claude]\n{adapter}model = "fable"\neffort = "high"\n')


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")


def make_fixture(dest: Path, stub: bool) -> Path:
    """Create the demo project at `dest`, commit it on `main`, and return `dest`."""
    dest = Path(dest)
    if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
        raise ValueError(f"{dest} exists and is not an empty folder")
    dest.mkdir(parents=True, exist_ok=True)
    gitops.git(dest, "init", "--quiet", "-b", "main")
    gitops.git(dest, "config", "core.autocrlf", "false")
    try:
        gitops.identity(dest)
    except GitError:
        gitops.git(dest, "config", "user.name", "Parallax Demo")
        gitops.git(dest, "config", "user.email", "demo@localhost")
    _write(dest, {
        "parallax.toml": _toml(stub),
        _FILE: "",
        "tests/__init__.py": "",
        "tests/test_baseline.py": _BASELINE,
        TASK_FILE: TASK_TEXT,
        ".parallax/.gitignore": "run/\n",
        ".parallax/ledger.jsonl": "",
    })
    gitops.git(dest, "add", "-A")
    gitops.git(dest, "commit", "--quiet", "-m", "Demo project")
    return dest


def stub_seats() -> dict[str, Seat]:
    """Scripted seats: codex builds, claude probes, and they disagree about lo > hi.

    Codex's reading says a reversed range raises ValueError; claude would swap the bounds.
    That is a `reading` dispute. Once the human rules `a` or `b`, the build and probes follow
    the contract, every mutant is caught, and the task lands with verdict `ruled`. These
    scripts cannot carry out a ruling `other`, so they report themselves blocked instead.
    """
    def reading(*decisions):
        return lambda req: {"interface": "clamplib.clamp(x, lo, hi) -> number",
                            "decisions": list(decisions), "predicted_failures": []}

    empty = {"scenario": "", "observation": "", "theirs": "", "mine": "", "decided_by": ""}
    reversed_bounds = {"scenario": "clamp(5, 10, 1)", "observation": "what the call returns or raises",
                       "theirs": "raises ValueError", "mine": "returns 5", "decided_by": ""}

    def reveal(*verdicts):
        why = "Treat the bounds in either order so the same interval is accepted."
        return lambda req: {"interface_ok": True, "interface_objection": "",
                            "verdicts": [{"index": i, "agree": agree, "counter": counter,
                                          "why": "" if agree else why,
                                          "witness": dict(empty if agree else reversed_bounds)}
                                         for i, (agree, counter) in enumerate(verdicts)]}

    def build(req):
        ruled = _ruled(req)
        if ruled is None:
            return {"summary": "", "blocked": _CANNOT, "mutants": [], "files": []}
        mutants = _mutants(ruled)
        _write(req.cwd, {_FILE: _clamp(ruled), **{f".parallax-mutants/{n}/{_FILE}": t for n, t in mutants.items()}})
        return {"summary": "built", "blocked": "",
                "mutants": [{"id": n, "description": n, "files": [_FILE]} for n in mutants],
                "files": [{"path": _FILE, "change": "modify", "purpose": "clamp"}]}

    def probe(req):
        ruled = _ruled(req)
        if ruled is None:
            return {"summary": "", "blocked": _CANNOT, "files": []}
        _write(req.cwd, {"tests/test_clamp.py": _PROBES + _REVERSED[ruled]})
        return {"summary": "probed", "blocked": "",
                "files": [{"path": "tests/test_clamp.py", "change": "add", "purpose": "probes"}]}

    decision = {"question": "What if lo > hi?", "answer": "raise ValueError", "why": "caller error"}
    return {
        "codex": StubSeat("codex", {"reading": [reading(decision)], "reveal": [reveal()], "build": [build]},
                          model="gpt-6.2-astra", effort="xhigh"),
        "claude": StubSeat("claude", {"reading": [reading()], "reveal": [reveal((False, _COUNTER))],
                                      "probe": [probe]}, model="fable", effort="high"),
    }


@contextlib.contextmanager
def stub_adapter() -> Iterator[dict[str, Seat]]:
    """Register `stub_seats()` under the `stub` adapter for the length of the block, then put back
    whatever was registered before, so nothing leaks into later runs or tests."""
    stubs = stub_seats()
    sentinel = object()
    previous = seats.ADAPTERS.get("stub", sentinel)
    seats.ADAPTERS["stub"] = lambda seat_cfg, cfg: stubs[seat_cfg.name]
    try:
        yield stubs
    finally:
        if previous is sentinel:
            seats.ADAPTERS.pop("stub", None)
        else:
            seats.ADAPTERS["stub"] = previous
