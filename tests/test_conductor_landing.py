import dataclasses, threading, unittest
import types as types_
from pathlib import Path
from parallax.gitops import rev
from parallax.ledger import Journal, parse_lines
from parallax.seats.base import SeatResult
from parallax.seats.stub import StubSeat
from tests.conductor_kit import (CLAMP_OK, FILE, MUTANTS, builds, kit_conductor, make_project, probes, reading, reveal, types)
from tests.helpers import commit, run_git, write

TASK = "tasks/clamp-001.md"

def seats(build_steps, probe_steps):
    return (StubSeat("codex", {"reading": [reading()], "reveal": [reveal()], "build": build_steps}),
            StubSeat("claude", {"reading": [reading()], "reveal": [reveal()], "probe": probe_steps}))

class Landing(unittest.TestCase):
    def test_clean_crossing_lands_with_a_consensus_receipt(self):
        root = make_project()
        barrier = threading.Barrier(2, timeout=30)
        def together(step):
            def run(req):
                barrier.wait()                       # fails unless both seats are working at the same moment
                return step(req)
            return run
        codex, claude = seats([together(builds())], [together(probes())])
        c = kit_conductor(root, codex, claude)
        before = rev(root, "main")
        out = c.run(root / TASK)
        self.assertEqual((out.status, out.commit), ("landed", rev(root, "main")))
        self.assertEqual(run_git(root, "rev-list", "--count", f"{before}..main"), "1")
        message = run_git(root, "log", "-1", "--format=%B", "main")
        self.assertTrue(message.startswith("clamp-001: Add clamp(x, lo, hi) to clamplib: returns x limited to the\n"))
        for line in ("Parallax-Task: clamp-001", "Built-by: codex stub-model/none", "Challenged-by: claude stub-model/none",
                     "Checks: 5 probes passed, 3 of 3 mutants caught", "Verdict: consensus"):
            self.assertIn(line, message)
        self.assertRegex(message, r"Parallax-Contract: sha256:[0-9a-f]{64}")
        self.assertEqual(sorted(run_git(root, "show", "--name-only", "--format=", "main").splitlines()),
                         [".parallax/PRECEDENTS.md", ".parallax/contracts/clamp-001.md", ".parallax/ledger.jsonl", FILE, "tests/test_clamp.py"])
        self.assertEqual((root / FILE).read_text(encoding="utf-8"), CLAMP_OK)
        self.assertEqual(run_git(root, "log", "-1", "--format=%an", "main"), "Test Human")
        self.assertTrue(any("codex" in line and " in / " in line and " out" in line for line in c.said), c.said)

    def test_landing_moves_the_events_into_the_ledger_and_cleans_up(self):
        root = make_project(); codex, claude = seats([builds()], [probes()])
        c = kit_conductor(root, codex, claude)
        c.run(root / TASK)
        ledger = parse_lines((root / ".parallax/ledger.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(ledger[-1]["type"], "task.integrated")
        self.assertEqual((ledger[-1]["verdict"], ledger[-1]["checks"]), ("consensus", "5 probes passed, 3 of 3 mutants caught"))
        self.assertEqual(Journal(root / ".parallax/run/journal.jsonl").events("clamp-001"), [])
        self.assertEqual(types(c)[-1], "task.integrated")                   # events() now reads them from the ledger on main
        self.assertEqual(c.status(), [{"task": "clamp-001", "status": "landed", "pending": []}])
        self.assertFalse(codex.calls[-1].cwd.exists())
        self.assertEqual((codex.discarded, claude.discarded), (["codex-s1"], ["claude-s1"]))
        self.assertEqual(run_git(root, "branch", "--list", "parallax/*"), "")
        self.assertEqual(run_git(root, "status", "--porcelain"), "")

    def test_attempts_resume_the_reading_sessions_and_are_writable(self):
        root = make_project(); codex, claude = seats([builds()], [probes()])
        kit_conductor(root, codex, claude).run(root / TASK)
        build, probe = codex.calls[-1], claude.calls[-1]
        self.assertEqual((build.stage, build.writable, build.session), ("build", True, "codex-s1"))
        self.assertEqual((probe.stage, probe.writable, probe.session), ("probe", True, "claude-s1"))

class Rejections(unittest.TestCase):
    def run_with(self, build_steps, probe_steps):
        root = make_project(); codex, claude = seats(build_steps, probe_steps)
        c = kit_conductor(root, codex, claude)
        return c, c.run(root / TASK), codex, claude

    def test_an_exclusive_path_is_closed_to_the_challenger_even_inside_its_own_patterns(self):
        root = make_project(); codex, claude = seats([builds()], [])
        c = kit_conductor(root, codex, claude)
        c.cfg = dataclasses.replace(c.cfg, exclusive_scope=("tests/conftest.py",))     # also matched by tests/**
        def undo(req):
            (req.cwd / "tests/conftest.py").unlink()
            return probes()(req)
        claude.script["probe"] = [probes(extra={"tests/conftest.py": "x = 1\n"}), undo]
        self.assertEqual(c.run(root / TASK).status, "landed")
        rejected = [e for e in c.events("clamp-001") if e["type"] == "attempt.rejected"]
        self.assertEqual([(e["seat"], e["reason"]) for e in rejected],
                         [("claude", "you changed files reserved for the builder: tests/conftest.py")])
        self.assertNotIn("tests/conftest.py", run_git(c.cfg.root, "show", "--name-only", "--format=", "main"))

    def test_the_ledger_names_a_clone_by_its_folder_and_never_by_a_full_path(self):
        c, out, _, _ = self.run_with([builds()], [probes()])
        self.assertEqual(out.status, "landed")
        ledger = run_git(c.cfg.root, "show", "main:.parallax/ledger.jsonl")
        names = [e["path"] for e in c.events("clamp-001") if e["type"] == "checkout.created"]
        self.assertEqual(sorted(n.split("-")[0] for n in names), ["claude", "codex"])
        for name in names:
            self.assertEqual(name, Path(name).name)                       # a folder name, no separators
        self.assertNotIn(str(c.home).replace("\\", "\\\\"), ledger)       # as JSON would escape it
        self.assertNotIn(c.home.as_posix(), ledger)
        # A record written before this rule holds the full path and still reads.
        t = types_.SimpleNamespace(id="old", dir=Path("C:/state/key/old"))
        c.events = lambda task: [{"type": "checkout.created", "seat": "codex", "path": str(Path("C:/elsewhere/codex-1"))},
                                 {"type": "checkout.created", "seat": "codex", "path": "codex-2"}]
        self.assertEqual(c._clones_of(t, "codex"), [str(Path("C:/elsewhere/codex-1")), str(Path("C:/state/key/old/codex-2"))])
        self.assertEqual(c._named(t, [str(t.dir / "claude-9"), str(t.dir / "cross"), "D:/x/y"]), ["claude-9", "cross", "y"])

    def test_out_of_scope_edit_is_rejected_then_accepted_once_undone(self):
        def undo(req):
            (req.cwd / "tests/sneaky.py").unlink()
            return builds()(req)
        c, out, codex, _ = self.run_with([builds(extra={"tests/sneaky.py": "x = 1\n"}), undo], [probes()])
        self.assertEqual(out.status, "landed")
        rejected = [e for e in c.events("clamp-001") if e["type"] == "attempt.rejected"]
        self.assertIn("you changed files outside your paths: tests/sneaky.py", rejected[0]["reason"])
        retry = codex.calls[-1]
        self.assertEqual(retry.session, "codex-s1"); self.assertIn("tests/sneaky.py", retry.brief)
        self.assertNotIn("tests/sneaky.py", run_git(c.cfg.root, "show", "--name-only", "--format=", "main"))

    def test_second_rejection_blocks(self):
        bad = builds(extra={"tests/sneaky.py": "x = 1\n"})
        _, out, _, _ = self.run_with([bad, bad], [probes()])
        self.assertEqual(out.status, "blocked"); self.assertIn("tests/sneaky.py", out.detail)

    def test_lint_failure_goes_back_to_the_seat(self):
        c, out, _, claude = self.run_with([builds()], [probes(extra={"tests/test_broken.py": "def oops(:\n"}),
                                                       probes(extra={"tests/test_broken.py": "X = 1\n"})])
        self.assertEqual(out.status, "landed")
        self.assertIn("lint failed", [e for e in c.events("clamp-001") if e["type"] == "attempt.rejected"][0]["reason"])
        self.assertIn("lint failed", claude.calls[-1].brief)

    def test_too_few_mutants_is_rejected(self):
        two = {k: MUTANTS[k] for k in ("m1", "m2")}
        c, out, _, _ = self.run_with([builds(mutants=two), builds()], [probes()])
        self.assertEqual(out.status, "landed")
        self.assertIn("expected 3 mutants, got 2", [e for e in c.events("clamp-001") if e["type"] == "attempt.rejected"][0]["reason"])

    def test_seat_reporting_blocked_stops_the_task(self):
        _, out, _, _ = self.run_with([lambda r: {"summary": "", "blocked": "the contract contradicts itself", "mutants": [], "files": []}], [probes()])
        self.assertEqual(out.status, "blocked"); self.assertIn("the contract contradicts itself", out.detail)

class BlindAndResume(unittest.TestCase):
    def test_a_build_that_peeked_is_voided_and_redone_in_a_new_clone_and_session(self):
        root = make_project()
        codex, claude = seats([], [probes()])
        c = kit_conductor(root, codex, claude)
        def peeking(req):
            builds()(req)
            name = [e["path"] for e in c.events("clamp-001") if e["type"] == "checkout.created" and e["seat"] == "claude"][0]
            other = str(req.cwd.parent / name)                  # the record holds the folder name only
            return SeatResult({"summary": "", "blocked": "", "mutants": [], "files": []}, req.session,
                              "dir " + other.replace("\\", "/") + "/tests", {"input": 0, "cached": 0, "output": 0})
        codex.script["build"] = [peeking, builds()]
        self.assertEqual(c.run(root / TASK).status, "landed")
        self.assertIn("attempt.voided", types(c))
        first, second = [r for r in codex.calls if r.stage == "build"]
        self.assertIsNone(second.session)
        self.assertNotEqual(first.cwd, second.cwd)
        self.assertIn("codex-s1", codex.discarded)

    def test_a_crash_mid_attempt_reruns_only_that_attempt(self):
        root = make_project()
        def crash(req):
            write(req.cwd, {FILE: "half written"})
            raise RuntimeError("boom")
        codex, claude = seats([crash, builds()], [probes()])
        c = kit_conductor(root, codex, claude)
        with self.assertRaises(RuntimeError):
            c.run(root / TASK)
        with open(root / ".parallax/run/journal.jsonl", "a", encoding="utf-8") as handle:
            handle.write('{"ts": "x", "type": "attempt.fin')                 # the process died mid-write
        self.assertEqual(c.run(root / TASK).status, "landed")
        self.assertEqual(len([r for r in claude.calls if r.stage == "probe"]), 1)
        self.assertEqual(len([r for r in claude.calls if r.stage == "reading"]), 1)

class MovingMain(unittest.TestCase):
    def test_lands_on_top_of_a_commit_the_human_made_meanwhile(self):
        root = make_project()
        def build_while_human_commits(req):
            commit(root, {"notes.txt": "human\n"}, "human work")
            return builds()(req)
        codex, claude = seats([build_while_human_commits], [probes()])
        out = kit_conductor(root, codex, claude).run(root / TASK)
        self.assertEqual(out.status, "landed")
        self.assertEqual(run_git(root, "log", "-2", "--format=%s", "main").splitlines()[1], "human work")
        self.assertTrue((root / "notes.txt").exists())

    def test_parks_when_the_human_has_edits_in_the_way_then_lands_later(self):
        root = make_project()
        def build_while_human_edits(req):
            write(root, {FILE: "# the human is editing this\n"})
            return builds()(req)
        codex, claude = seats([build_while_human_edits], [probes()])
        c = kit_conductor(root, codex, claude)
        before = rev(root, "main")
        out = c.run(root / TASK)
        self.assertEqual(out.status, "parked"); self.assertIn("parallax/ready/clamp-001", out.detail)
        self.assertEqual(rev(root, "main"), before)
        self.assertEqual((root / FILE).read_text(encoding="utf-8"), "# the human is editing this\n")
        self.assertEqual(c.status()[0]["status"], "parked")
        run_git(root, "checkout", "--", FILE)
        self.assertEqual(c.run(root / TASK).status, "landed")
        self.assertEqual((root / FILE).read_text(encoding="utf-8"), CLAMP_OK)
        self.assertEqual((len(codex.calls), len(claude.calls)), (3, 3))        # nothing was asked of the seats again
