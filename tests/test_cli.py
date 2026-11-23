import contextlib, io, tempfile, unittest
from pathlib import Path
from parallax import cli, seats
from parallax.seats.stub import StubSeat
from tests.conductor_kit import DECISION, builds, make_project, probes, reading, reveal
from tests.helpers import run_git

def call(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()

class Cli(unittest.TestCase):
    def setUp(self):
        self.root = make_project()
        self.stubs = {
            "codex": StubSeat("codex", {"reading": [reading(DECISION)], "reveal": [reveal()], "build": [builds()]}),
            "claude": StubSeat("claude", {"reading": [reading()], "reveal": [reveal((False, "swap the bounds"))], "probe": [probes()]}),
        }
        seats.ADAPTERS["stub"] = lambda seat_cfg, cfg: self.stubs[seat_cfg.name]
        self.addCleanup(seats.ADAPTERS.pop, "stub", None)
        self.repo = ["--repo", str(self.root)]

    def test_run_pauses_with_a_card_then_rule_then_run_lands(self):
        code, out, _ = call("run", str(self.root / "tasks/clamp-001.md"), *self.repo)
        self.assertEqual(code, 2)
        # Task 19.11: a new task is confirmed-v1, so the card is its settlement's, printed as recorded.
        for part in ("clamp-001: settlement published (direct)\n", "\nDispute D-clamp-001-1 (reading)\n",
                     "\na) codex (builder):\n| raise ValueError\nb) claude (challenger):\n| swap the bounds\n"
                     "other) Supply the policy with --note.\n", "\nparallax rule D-clamp-001-1 a\n",
                     "\nclamp-001: needs_ruling  needs a ruling on D-clamp-001-1\n"):
            self.assertIn(part, out)
        code, out, _ = call("status", *self.repo)
        self.assertEqual((code, out.split()), (0, ["clamp-001", "needs_ruling", "D-clamp-001-1"]))
        code, out, _ = call("rule", "D-clamp-001-1", "a", "--while", "inputs are numbers", *self.repo)
        self.assertEqual(code, 0); self.assertIn("recorded D-clamp-001-1: a", out)
        code, out, _ = call("run", str(self.root / "tasks/clamp-001.md"), *self.repo)
        self.assertEqual(code, 0); self.assertIn("clamp-001: landed", out)
        self.assertIn("Verdict: ruled", run_git(self.root, "log", "-1", "--format=%B", "main"))
        self.assertIn("**P-1**", (self.root / ".parallax/PRECEDENTS.md").read_text(encoding="utf-8"))

    def test_errors_exit_1_with_a_message(self):
        code, _, err = call("rule", "D-nope-1", "a", *self.repo)
        self.assertEqual(code, 1); self.assertIn("parallax: unknown dispute D-nope-1", err)
        code, _, err = call("status", "--repo", tempfile.mkdtemp(prefix="plx empty "))
        self.assertEqual(code, 1); self.assertIn("parallax.toml", err)

    def test_blocked_exits_3(self):
        self.stubs["codex"].script["reading"] = [lambda r: {}] * 2
        code, out, _ = call("run", str(self.root / "tasks/clamp-001.md"), *self.repo)
        self.assertEqual(code, 3); self.assertIn("clamp-001: blocked", out)

    def test_init_writes_a_loadable_project_once(self):
        fresh = Path(tempfile.mkdtemp(prefix="plx init "))
        self.assertEqual(call("init", "--repo", str(fresh))[0], 0)
        self.assertEqual((fresh / ".parallax/.gitignore").read_text(encoding="utf-8"), "run/\n")
        self.assertTrue((fresh / ".parallax/ledger.jsonl").exists())
        from parallax.config import load_config
        self.assertEqual(load_config(fresh).mutants, 3)
        code, _, err = call("init", "--repo", str(fresh))
        self.assertEqual(code, 1); self.assertIn("already exists", err)
