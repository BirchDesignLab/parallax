import os, tempfile, unittest
from pathlib import Path
from unittest import mock
from parallax.gitops import rev
from parallax.seats.stub import StubSeat
from tests.conductor_kit import (CLAMP_OK, FILE, PROBES, builds, kit_conductor, make_project,
                                 probes, reading, responds, reveal)
from tests.helpers import commit, run_git, write

TASK = "tasks/clamp-001.md"
NAN_PROBE = PROBES + "    def test_nan(self):\n        with self.assertRaises(ValueError):\n            clamp(float('nan'), 1, 10)\n"

def seats(build_steps, probe_steps, codex_responds=(), claude_responds=()):
    return (StubSeat("codex", {"reading": [reading()], "reveal": [reveal()], "build": build_steps, "respond": list(codex_responds)}),
            StubSeat("claude", {"reading": [reading()], "reveal": [reveal()], "probe": probe_steps, "respond": list(claude_responds)}))

def landed_files(root):
    return run_git(root, "show", "--name-only", "--format=", "main").splitlines()

def rejections(c, task="clamp-001"):
    return [e["reason"] for e in c.events(task) if e["type"] == "attempt.rejected"]

def deleting(path, then):
    def step(req):
        (req.cwd / path).unlink()
        return then(req)
    return step

class Attempts(unittest.TestCase):
    def test_an_undeclared_builder_file_goes_back_to_the_builder(self):
        root = make_project()
        codex, claude = seats([builds(extra={"clamplib/notes.md": "todo\n"}, undeclared=("clamplib/notes.md",)),
                               deleting("clamplib/notes.md", builds())], [probes()])
        c = kit_conductor(root, codex, claude)
        self.assertEqual(c.run(root / TASK).status, "landed")
        self.assertIn("you changed clamplib/notes.md but did not list it in files", rejections(c)[0])
        self.assertIn("clamplib/notes.md", codex.calls[-1].brief)
        self.assertNotIn("clamplib/notes.md", landed_files(root))
        self.assertEqual(len([e for e in c.events("clamp-001") if e["type"] == "crossing.done"]), 1)

    def test_an_undeclared_challenger_file_goes_back_to_the_challenger(self):
        root = make_project()
        codex, claude = seats([builds()], [probes(extra={"tests/scratch.txt": "x\n"}, undeclared=("tests/scratch.txt",)),
                                           deleting("tests/scratch.txt", probes())])
        c = kit_conductor(root, codex, claude)
        self.assertEqual(c.run(root / TASK).status, "landed")
        self.assertIn("you changed tests/scratch.txt but did not list it in files", rejections(c)[0])
        self.assertNotIn("tests/scratch.txt", landed_files(root))

    def test_a_wrong_change_kind_is_rejected(self):
        root = make_project()
        wrong = [{"path": FILE, "change": "add", "purpose": "clamp"}]
        codex, claude = seats([builds(files=wrong), builds()], [probes()])
        c = kit_conductor(root, codex, claude)
        self.assertEqual(c.run(root / TASK).status, "landed")
        self.assertIn(f"{FILE} is listed as add but the change since the task began is modify", rejections(c)[0])

    def test_a_seat_cannot_declare_its_mutants(self):
        root = make_project()
        sneaky = [{"path": FILE, "change": "modify", "purpose": "clamp"},
                  {"path": f".parallax-mutants/m1/{FILE}", "change": "add", "purpose": "mutant"}]
        codex, claude = seats([builds(files=sneaky), builds()], [probes()])
        c = kit_conductor(root, codex, claude)
        self.assertEqual(c.run(root / TASK).status, "landed")
        self.assertIn(f".parallax-mutants/m1/{FILE} is a Parallax working file or record, not a deliverable", rejections(c)[0])

    def test_a_lint_rejected_snapshot_still_has_to_be_declared(self):
        root = make_project()
        codex, claude = seats([builds()], [probes(extra={"tests/test_broken.py": "def oops(:\n"}),
                                           probes(undeclared=("tests/test_broken.py",))])
        out = kit_conductor(root, codex, claude).run(root / TASK)
        self.assertEqual(out.status, "blocked")
        self.assertIn("you changed tests/test_broken.py but did not list it in files", out.detail)

    def test_a_declared_but_unneeded_file_still_lands(self):
        # The stated limit of accounting: a declared file is not judged for relevance.
        root = make_project()
        codex, claude = seats([builds(extra={"clamplib/_mutants.py": "# private copies\n"})], [probes()])
        self.assertEqual(kit_conductor(root, codex, claude).run(root / TASK).status, "landed")
        self.assertIn("clamplib/_mutants.py", landed_files(root))

    def test_the_accepted_list_is_recorded_with_the_head(self):
        root = make_project()
        codex, claude = seats([builds()], [probes()])
        c = kit_conductor(root, codex, claude)
        c.run(root / TASK)
        finished = {e["seat"]: e["files"] for e in c.events("clamp-001") if e["type"] == "attempt.finished"}
        self.assertEqual(finished["codex"], [{"path": FILE, "change": "modify", "purpose": "kit"}])
        self.assertEqual(finished["claude"], [{"path": "tests/test_clamp.py", "change": "add", "purpose": "kit"}])

class Responses(unittest.TestCase):
    def test_a_contesting_seat_must_repeat_its_full_list(self):
        root = make_project()
        codex, claude = seats([builds()], [probes(NAN_PROBE)], codex_responds=[responds("contest")],
                              claude_responds=[responds("contest", files=[]), responds("contest"),
                                               responds("concede", files={"tests/test_clamp.py": PROBES})])
        c = kit_conductor(root, codex, claude)
        out = c.run(root / TASK)
        self.assertEqual(out.status, "needs_ruling")
        self.assertIn("you changed tests/test_clamp.py but did not list it in files", rejections(c)[0])
        c.rule(out.disputes[0].id, "a", limitation="NaN is not supported")
        self.assertEqual(c.run(root / TASK).status, "landed")

    def test_a_partial_repair_must_still_declare_earlier_files(self):
        root = make_project()
        helper = {"tests/clamp_cases.py": "CASES = []\n"}
        codex, claude = seats([builds()], [probes(NAN_PROBE, extra=helper)], codex_responds=[responds("contest")],
                              claude_responds=[responds("contest"),
                                               responds("concede", files={"tests/test_clamp.py": PROBES}, undeclared=("tests/clamp_cases.py",)),
                                               responds("concede", files={"tests/test_clamp.py": PROBES})])
        c = kit_conductor(root, codex, claude)
        out = c.run(root / TASK)
        c.rule(out.disputes[0].id, "a", limitation="NaN is not supported")
        self.assertEqual(c.run(root / TASK).status, "landed")
        self.assertIn("you changed tests/clamp_cases.py but did not list it in files", rejections(c)[0])
        self.assertIn("tests/clamp_cases.py", landed_files(root))

class Landing(unittest.TestCase):
    def test_landing_blocks_a_change_no_seat_declared(self):
        root = make_project()
        codex, claude = seats([builds()], [probes()])
        c = kit_conductor(root, codex, claude)
        real = c._files
        c._files = lambda t, seat: [f for f in real(t, seat) if f["path"] != FILE]     # a gate bypass upstream
        before = rev(root, "main")
        out = c.run(root / TASK)
        self.assertEqual(out.status, "blocked")
        self.assertIn(f"landing would add changes no seat declared: {FILE}", out.detail)
        self.assertEqual(rev(root, "main"), before)
        self.assertEqual(c.status()[0]["status"], "in_progress")

    def test_a_commit_hook_that_changes_the_commit_blocks_landing(self):
        root = make_project()
        hooks = Path(tempfile.mkdtemp(prefix="plx hooks "))
        (hooks / "pre-commit").write_text("#!/bin/sh\necho hooked > hooked.txt\ngit add hooked.txt\n",
                                          encoding="utf-8", newline="\n")
        codex, claude = seats([builds()], [probes()])
        c = kit_conductor(root, codex, claude)
        before = rev(root, "main")
        env = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.hooksPath", "GIT_CONFIG_VALUE_0": hooks.as_posix()}
        with mock.patch.dict(os.environ, env):
            out = c.run(root / TASK)
        self.assertEqual(out.status, "blocked")
        self.assertIn("a commit hook changed the landing commit; main was not moved", out.detail)
        self.assertEqual(rev(root, "main"), before)

    def test_ordinary_check_output_does_not_block_landing(self):
        root = make_project()
        report = PROBES + "    def test_report(self):\n        open('report.txt', 'w').write('ran')\n"
        codex, claude = seats([builds()], [probes(report)])
        self.assertEqual(kit_conductor(root, codex, claude).run(root / TASK).status, "landed")
        self.assertNotIn("report.txt", landed_files(root))

    def test_a_change_main_already_has_is_not_a_violation(self):
        root = make_project()
        def build_while_human_lands_the_same(req):
            commit(root, {FILE: CLAMP_OK}, "human wrote clamp too")
            return builds()(req)
        codex, claude = seats([build_while_human_lands_the_same], [probes()])
        self.assertEqual(kit_conductor(root, codex, claude).run(root / TASK).status, "landed")
        self.assertEqual((root / FILE).read_text(encoding="utf-8"), CLAMP_OK)

    def test_a_task_started_before_accounting_lands_with_a_note(self):
        root = make_project()
        codex, claude = seats([builds()], [probes()])
        c = kit_conductor(root, codex, claude)
        c._files = lambda t, seat: None
        self.assertEqual(c.run(root / TASK).status, "landed")
        self.assertIn("clamp-001: landing without delivery accounting (the task started before it existed)", c.said)

class Chores(unittest.TestCase):
    def test_a_chore_is_accounted_too(self):
        root = make_project()
        def edit(req, junk=True):
            write(req.cwd, {"README.md": "better wording\n", **({"junk.txt": "x\n"} if junk else {})})
            return {"summary": "reworded", "blocked": "",
                    "files": [{"path": "README.md", "change": "modify", "purpose": "the wording fix"}]}
        def tidy(req):
            (req.cwd / "junk.txt").unlink()
            return edit(req, junk=False)
        codex, claude = StubSeat("codex", {"solo": [edit, tidy]}), StubSeat("claude", {})
        c = kit_conductor(root, codex, claude)
        self.assertEqual(c.run(root / "tasks/docs-001.md").status, "landed")
        self.assertIn("you changed junk.txt but did not list it in files", rejections(c, "docs-001")[0])
        self.assertNotIn("junk.txt", landed_files(root))
