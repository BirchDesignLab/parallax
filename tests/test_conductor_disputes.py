import unittest
from parallax.gitops import rev
from parallax.seats.stub import StubSeat
from tests.conductor_kit import (CLAMP_BAD, CLAMP_OK, COMPARISON, FILE, INTERFACE_A, INTERFACE_B, MUTANTS, PROBES,
                                 WEAK_PROBES, builds, interface_section, kit_conductor, make_project, probes,
                                 reading, responds, reveal, types)
from tests.helpers import run_git

TASK = "tasks/clamp-001.md"
NAN_PROBE = PROBES + "    def test_nan(self):\n        with self.assertRaises(ValueError):\n            clamp(float('nan'), 1, 10)\n"

def seats(build_steps, probe_steps, codex_responds=(), claude_responds=()):
    return (StubSeat("codex", {"reading": [reading()], "reveal": [reveal()], "build": build_steps, "respond": list(codex_responds)}),
            StubSeat("claude", {"reading": [reading()], "reveal": [reveal()], "probe": probe_steps, "respond": list(claude_responds)}))

def message(root):
    return run_git(root, "log", "-1", "--format=%B", "main")

class Repairs(unittest.TestCase):
    def test_builder_concedes_and_repairs(self):
        root = make_project()
        codex, claude = seats([builds(CLAMP_BAD)], [probes()],
                              codex_responds=[responds("concede", files={FILE: CLAMP_OK}, mutants=MUTANTS)],
                              claude_responds=[responds("contest")])
        c = kit_conductor(root, codex, claude)
        self.assertEqual(c.run(root / TASK).status, "landed")
        self.assertIn("Verdict: resolved", message(root))
        respond = codex.calls[-1]
        self.assertEqual((respond.stage, respond.writable, respond.session), ("respond", True, "codex-s1"))
        self.assertIn("test_high", respond.brief)                              # the failing check's output is the evidence
        self.assertEqual([e["passed"] for e in c.events("clamp-001") if e["type"] == "crossing.done"], [False, True])
        self.assertNotIn("dispute.opened", types(c))                           # settled between the seats: no card, no human

    def test_surviving_mutant_asks_only_the_challenger(self):
        root = make_project()
        codex, claude = seats([builds()], [probes(WEAK_PROBES)],
                              claude_responds=[responds("concede", files={"tests/test_clamp.py": PROBES})])
        c = kit_conductor(root, codex, claude)
        self.assertEqual(c.run(root / TASK).status, "landed")
        self.assertIn("Verdict: resolved", message(root))
        self.assertEqual([r.stage for r in codex.calls], ["reading", "reveal", "build"])
        self.assertIn("m1", claude.calls[-1].brief)
        self.assertIn("-    return max(lo, min(x, hi))", claude.calls[-1].brief)    # the diff of the real file against the mutant

    def test_a_repair_uses_the_builders_fresh_mutants(self):
        root = make_project()
        fresh = {"n1": MUTANTS["m1"], "n2": MUTANTS["m2"], "n3": MUTANTS["m3"]}
        codex, claude = seats([builds(CLAMP_BAD)], [probes()],
                              codex_responds=[responds("concede", files={FILE: CLAMP_OK}, mutants=fresh)],
                              claude_responds=[responds("contest")])
        c = kit_conductor(root, codex, claude)
        c.run(root / TASK)
        self.assertEqual(sorted([e for e in c.events("clamp-001") if e["type"] == "crossing.done"][-1]["mutants"]), ["n1", "n2", "n3"])

    def test_a_contesting_seat_cannot_change_files(self):
        root = make_project()
        codex, claude = seats([builds(CLAMP_BAD)], [probes()],
                              codex_responds=[responds("concede", files={FILE: CLAMP_OK}, mutants=MUTANTS)],
                              claude_responds=[responds("contest", files={"tests/test_clamp.py": "import unittest\n"})])
        c = kit_conductor(root, codex, claude)
        self.assertEqual(c.run(root / TASK).status, "landed")
        self.assertEqual((root / "tests/test_clamp.py").read_text(encoding="utf-8"), PROBES)

class Rulings(unittest.TestCase):
    def deadlock(self, codex_after=(), claude_after=()):
        root = make_project()
        codex, claude = seats([builds(CLAMP_BAD)], [probes()],
                              codex_responds=[responds("contest"), *codex_after],
                              claude_responds=[responds("contest"), *claude_after])
        c = kit_conductor(root, codex, claude)
        return root, c, c.run(root / TASK), codex, claude

    def test_both_contest_then_the_human_rules_for_the_challenger(self):
        root, c, out, codex, _ = self.deadlock(codex_after=[responds("concede", files={FILE: CLAMP_OK}, mutants=MUTANTS)])
        self.assertEqual((out.status, [d.kind for d in out.disputes]), ("needs_ruling", ["check"]))
        card = (root / f".parallax/run/clamp-001/cards/{out.disputes[0].id}.md").read_text(encoding="utf-8")
        self.assertIn("test_high", card)
        c.rule(out.disputes[0].id, "b", note="The upper bound is inclusive.")
        self.assertEqual(c.run(root / TASK).status, "landed")
        self.assertIn("Verdict: ruled", message(root))
        self.assertIn("The upper bound is inclusive.", codex.calls[-1].brief)
        self.assertIn("contract-v2.md", [p.name for p in (root / ".parallax/run/clamp-001").iterdir()])
        self.assertIn("A: The upper bound is inclusive. (ruled", (root / ".parallax/contracts/clamp-001.md").read_text(encoding="utf-8"))

    def test_a_limitation_is_written_on_the_receipt(self):
        root = make_project()
        codex, claude = seats([builds()], [probes(NAN_PROBE)], codex_responds=[responds("contest")],
                              claude_responds=[responds("contest"), responds("concede", files={"tests/test_clamp.py": PROBES})])
        c = kit_conductor(root, codex, claude)
        out = c.run(root / TASK)
        c.rule(out.disputes[0].id, "a", limitation="NaN is not supported")
        self.assertEqual(c.run(root / TASK).status, "landed")
        self.assertIn("Verdict: limited\nLimitation: NaN is not supported", message(root))

    def test_a_contested_mutant_can_be_waived(self):
        root = make_project()
        codex, claude = seats([builds()], [probes(WEAK_PROBES)], claude_responds=[responds("contest")])
        c = kit_conductor(root, codex, claude)
        out = c.run(root / TASK)
        self.assertEqual((out.status, [d.kind for d in out.disputes]), ("needs_ruling", ["mutant"]))
        c.rule(out.disputes[0].id, "b", note="covered by an integration test")
        self.assertEqual(c.run(root / TASK).status, "landed")
        text = message(root)
        self.assertIn("Checks: 4 probes passed, 2 of 3 mutants caught", text)
        self.assertIn("Verdict: limited\nLimitation: mutant m1 waived: covered by an integration test", text)

    def test_a_whole_interface_ruling_survives_the_contract_amendment(self):
        # The contested-check path of test_both_contest_then_the_human_rules_for_the_challenger,
        # on a task whose interface was replaced whole before contract v1.
        # B adds the public alias clip, so the build, the repair, every mutant and the probes carry it.
        root = make_project()
        clip = "\nclip = clamp\n"
        mutants = {name: text + clip for name, text in MUTANTS.items()}
        clip_probes = (PROBES.replace("from clamplib import clamp\n", "from clamplib import clamp, clip\n")
                       + "    def test_clip(self):\n        self.assertIs(clip, clamp)\n")
        codex = StubSeat("codex", {"reading": [reading(COMPARISON, interface=INTERFACE_A)], "reveal": [reveal()],
                                   "build": [builds(CLAMP_BAD + clip, mutants=mutants)],
                                   "respond": [responds("contest"),
                                               responds("concede", files={FILE: CLAMP_OK + clip}, mutants=mutants)]})
        claude = StubSeat("claude", {"reading": [reading(interface=INTERFACE_B)], "reveal": [
            reveal((True, ""), interface_ok=False, objection="callers want the short name clip", replacement=INTERFACE_B)],
                                     "probe": [probes(clip_probes)], "respond": [responds("contest")]})
        c = kit_conductor(root, codex, claude, whole=True)      # a Task 18 opening: its interface card is a dispute
        out = c.run(root / TASK)
        self.assertEqual([d.kind for d in out.disputes], ["interface"])
        c.rule(out.disputes[0].id, "b")
        out = c.run(root / TASK)
        self.assertEqual((out.status, [d.kind for d in out.disputes]), ("needs_ruling", ["check"]))
        check = out.disputes[0].id
        c.rule(check, "b", note="The upper bound is inclusive.")
        self.assertEqual(c.run(root / TASK).status, "landed")
        v1, v2 = ((root / f".parallax/run/clamp-001/contract-v{n}.md").read_text(encoding="utf-8") for n in (1, 2))
        shared = f"- Q: {COMPARISON['question']}\n  A: {COMPARISON['answer']} (agreed)\n"
        for text in (v1, v2):
            self.assertEqual(interface_section(text), INTERFACE_B)
            self.assertIn(shared, text)
            self.assertNotIn("Amended:", text)
        self.assertNotIn("The upper bound is inclusive.", v1)
        self.assertIn(f"A: The upper bound is inclusive. (ruled {check})", v2)
        self.assertIn("clip = clamp", (root / FILE).read_text(encoding="utf-8"))
        self.assertIn("def test_clip", (root / "tests/test_clamp.py").read_text(encoding="utf-8"))

class Exhaustion(unittest.TestCase):
    def stuck(self):
        root = make_project()
        useless = responds("concede", files={FILE: CLAMP_BAD + "# tried\n"}, mutants=MUTANTS)
        more = [responds("concede", files={FILE: CLAMP_BAD + f"# tried {i}\n"}, mutants=MUTANTS) for i in range(4)]
        codex, claude = seats([builds(CLAMP_BAD)], [probes()], codex_responds=[useless, *more], claude_responds=[responds("contest")] * 6)
        c = kit_conductor(root, codex, claude)
        return root, c, c.run(root / TASK), codex

    def test_three_failed_crossings_reach_the_human(self):
        root, c, out, _ = self.stuck()
        self.assertEqual((out.status, [d.kind for d in out.disputes]), ("needs_ruling", ["unresolved"]))
        self.assertEqual([e["passed"] for e in c.events("clamp-001") if e["type"] == "crossing.done"], [False, False, False])

    def test_drop_lands_only_the_record(self):
        root, c, out, _ = self.stuck()
        before = rev(root, "main")
        c.rule(out.disputes[0].id, "drop")
        self.assertEqual(c.run(root / TASK).status, "dropped")
        self.assertEqual(sorted(run_git(root, "show", "--name-only", "--format=", "main").splitlines()),
                         [".parallax/PRECEDENTS.md", ".parallax/ledger.jsonl"])
        self.assertEqual(run_git(root, "log", "-1", "--format=%s", "main"), "clamp-001: dropped")
        self.assertEqual((root / FILE).read_text(encoding="utf-8"), "")
        self.assertEqual(c.status(), [{"task": "clamp-001", "status": "dropped", "pending": []}])
        self.assertNotEqual(rev(root, "main"), before)

    def test_a_ruling_buys_exactly_one_more_round(self):
        root, c, out, codex = self.stuck()
        c.rule(out.disputes[0].id, "b", note="Fix the upper bound.")
        again = c.run(root / TASK)
        self.assertEqual((again.status, [d.kind for d in again.disputes]), ("needs_ruling", ["unresolved"]))
        self.assertEqual(len([e for e in c.events("clamp-001") if e["type"] == "crossing.done"]), 4)
        self.assertIn("Fix the upper bound.", codex.calls[-1].brief)

class Chores(unittest.TestCase):
    def test_a_chore_is_built_by_one_seat_and_stamped_solo(self):
        root = make_project()
        def edit(req):
            (req.cwd / "README.md").write_text("better wording\n", encoding="utf-8")
            return {"summary": "reworded", "blocked": "",
                    "files": [{"path": "README.md", "change": "modify", "purpose": "the wording fix"}]}
        codex, claude = StubSeat("codex", {"solo": [edit]}), StubSeat("claude", {})
        c = kit_conductor(root, codex, claude)
        self.assertEqual(c.run(root / "tasks/docs-001.md").status, "landed")
        self.assertEqual(claude.calls, [])
        text = message(root)
        self.assertEqual(text.splitlines()[0], "docs-001: Fix the README wording.")
        self.assertIn("Built-by: codex stub-model/none\nChecks: check passed\nVerdict: solo", text)
        self.assertNotIn("Challenged-by", text); self.assertNotIn("Parallax-Contract", text)
        self.assertEqual((root / "README.md").read_text(encoding="utf-8"), "better wording\n")
