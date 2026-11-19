import os, tempfile, unittest
from pathlib import Path
from tests.helpers import run_git
from tests.test_cli import call

class Demo(unittest.TestCase):
    def test_stub_demo_pauses_for_a_ruling_then_lands_with_a_receipt(self):
        where = Path(tempfile.mkdtemp(prefix="plx demo ")) / "clamp demo"
        code, out, _ = call("demo", "--dir", str(where), "--stub")
        self.assertEqual(code, 2)
        self.assertIn("Dispute D-clamp-001-1 (reading)", out)
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
