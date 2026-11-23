import os, tempfile, unittest
from pathlib import Path
from parallax import demo, seats
from parallax.conductor import Conductor
from parallax.config import load_config
from tests.helpers import run_git
from tests.test_cli import call

def events(where):
    """The demo task's records, read as `status` reads them."""
    return Conductor(load_config(where), {}, say=lambda s: None).events("clamp-001")

class Demo(unittest.TestCase):
    def test_stub_demo_pauses_for_a_ruling_then_lands_with_a_receipt(self):
        where = Path(tempfile.mkdtemp(prefix="plx demo ")) / "clamp demo"
        code, out, _ = call("demo", "--dir", str(where), "--stub")
        self.assertEqual(code, 2)
        self.assertIn("Dispute D-clamp-001-1 (reading)", out)
        # Task 19.11: the demo's task is confirmed-v1. Its one objection settles directly, with no batch call,
        # and the demo prints the commands the card allows.
        history = events(where)
        self.assertEqual((history[0].get("batch_protocol"), [e["mode"] for e in history if e["type"] == "reading.settled"],
                          [e["type"] for e in history if e["type"] in ("batch.proposed", "batch.reviewed", "dispute.opened")]),
                         ("confirmed-v1", ["direct"], []))
        self.assertIn(f'\nrule with: python -m parallax rule D-clamp-001-1 a --repo "{where.resolve()}"   '
                      "(or b, other --note TEXT)\n", out)
        self.assertEqual(call("rule", "D-clamp-001-1", "a", "--repo", str(where))[0], 0)
        code, out, _ = call("demo", "--dir", str(where), "--stub")
        self.assertEqual(code, 0)
        for part in ("clamp-001: landed", "Built-by: codex gpt-6.2-astra/xhigh", "Challenged-by: claude fable/high", "Verdict: ruled"):
            self.assertIn(part, out)
        self.assertEqual(run_git(where, "status", "--porcelain"), "")
        self.assertIn("def clamp", (where / "clamplib/__init__.py").read_text(encoding="utf-8"))
        self.assertIn("raise ValueError", (where / "clamplib/__init__.py").read_text(encoding="utf-8"))   # ruling a was carried out

    def test_ruling_b_is_carried_out_from_a_relative_dir_and_a_rerun_shows_the_same_receipt(self):
        parent = Path(tempfile.mkdtemp(prefix="plx demo "))
        here = os.getcwd()
        os.chdir(parent)
        self.addCleanup(os.chdir, here)
        where = parent / "clamp demo"
        self.assertEqual(call("demo", "--dir", "clamp demo", "--stub")[0], 2)
        self.assertEqual(call("rule", "D-clamp-001-1", "b", "--repo", "clamp demo")[0], 0)
        code, out, _ = call("demo", "--dir", "clamp demo", "--stub")
        self.assertEqual(code, 0, out)
        self.assertIn("lo, hi = hi, lo", (where / "clamplib/__init__.py").read_text(encoding="utf-8"))
        self.assertIn("Verdict: ruled", out)
        (where / "later.txt").write_text("x\n", encoding="utf-8")         # main moves on after landing
        run_git(where, "add", "later.txt")
        run_git(where, "commit", "-q", "-m", "Later work")
        code, out, _ = call("demo", "--dir", "clamp demo", "--stub")
        self.assertEqual(code, 0, out)
        self.assertIn("Parallax-Task: clamp-001", out)
        self.assertNotIn("Later work", out)

    def test_a_ruling_the_stubs_cannot_carry_out_blocks_and_run_takes_a_relative_repo(self):
        from parallax import demo
        parent = Path(tempfile.mkdtemp(prefix="plx demo "))
        here = os.getcwd()
        os.chdir(parent)
        self.addCleanup(os.chdir, here)
        demo.make_fixture(parent / "clamp demo", stub=True)
        with demo.stub_adapter():                                      # plain `run`, from outside, with a relative --repo:
            code, out, _ = call("run", "tasks/clamp-001.md", "--repo", "clamp demo")   # the seat clones are made here
        self.assertEqual(code, 2, out)
        self.assertEqual(call("rule", "D-clamp-001-1", "other", "--note", "return lo", "--repo", "clamp demo")[0], 0)
        with demo.stub_adapter():
            code, out, _ = call("run", "tasks/clamp-001.md", "--repo", "clamp demo")
        self.assertEqual(code, 3, out)
        self.assertIn("scripted demo seats can carry out only ruling a", out)
        self.assertEqual(run_git(parent / "clamp demo", "log", "--format=%s"), "Demo project")   # nothing landed

    def test_a_demo_opened_by_the_version_before_and_interrupted_before_its_reveal_resumes_as_it_was_opened(self):
        where = Path(tempfile.mkdtemp(prefix="plx demo ")) / "clamp demo"
        demo.make_fixture(where, stub=True)
        with demo.stub_adapter():
            cfg = load_config(where)
            c = Conductor(cfg, seats.make_seats(cfg), say=lambda s: None)
            t = c._open("clamp-001", demo.TASK_TEXT, None)     # as the version before opened it: no batch_protocol
            c._readings(t)                                     # both readings sealed; killed before the reveal
        self.assertEqual([e["type"] for e in events(where) if e["type"] not in ("checkout.created",)],
                         ["task.opened", "reading.sealed", "reading.sealed"])
        code, out, _ = call("demo", "--dir", str(where), "--stub")
        self.assertEqual(code, 2, out)
        history = events(where)
        self.assertNotIn("batch_protocol", history[0])
        self.assertEqual(([("batch_protocol" in e) for e in history if e["type"] == "reveal.done"],
                          [e["type"] for e in history if e["type"] in ("reading.settled", "dispute.opened")]),
                         ([False, False], ["dispute.opened"]))
        # Its card is the one that version wrote, and the demo offers a (or b).
        self.assertIn("\na) codex (builder): raise ValueError\nb) claude (challenger): swap the bounds\n", out)
        self.assertIn(f'\nrule with: python -m parallax rule D-clamp-001-1 a --repo "{where.resolve()}"   (or b)\n', out)
        self.assertEqual(call("rule", "D-clamp-001-1", "b", "--repo", str(where))[0], 0)
        code, out, _ = call("demo", "--dir", str(where), "--stub")
        self.assertEqual(code, 0, out)
        self.assertIn("Verdict: ruled", out)
        self.assertIn("lo, hi = hi, lo", (where / "clamplib/__init__.py").read_text(encoding="utf-8"))
