import json, os, unittest
from pathlib import Path
from parallax import decisions, folders
from parallax.ledger import sha256_text
from parallax.seats.base import SeatResult
from parallax.seats.stub import StubSeat
from tests.conductor_kit import DECISION, kit_conductor, make_project, reading, reveal, types

TASK = "tasks/clamp-001.md"

def agreeing():
    return (StubSeat("codex", {"reading": [reading(DECISION)], "reveal": [reveal()]}),
            StubSeat("claude", {"reading": [reading()], "reveal": [reveal((True, ""))]}))

def disagreeing():
    return (StubSeat("codex", {"reading": [reading(DECISION)], "reveal": [reveal()]}),
            StubSeat("claude", {"reading": [reading()], "reveal": [reveal((False, "swap the bounds"))]}))

class ToContract(unittest.TestCase):
    def test_agreement_freezes_a_contract(self):
        root = make_project(); codex, claude = agreeing()
        c = kit_conductor(root, codex, claude)
        out = c.run(root / TASK, stop_after="contract")
        self.assertEqual(out.status, "stopped")
        self.assertEqual(types(c), ["task.opened", "checkout.created", "checkout.created", "reading.sealed", "reading.sealed",
                                    "reveal.done", "reveal.done", "contract.frozen"])
        opened = c.events("clamp-001")[0]
        self.assertEqual((opened["kind"], opened["builder"], opened["challenger"]), ("behavior", "codex", "claude"))
        self.assertEqual(opened["title"], "Add clamp(x, lo, hi) to clamplib: returns x limited to the range lo..hi.")
        contract = (root / ".parallax/run/clamp-001/contract-v1.md").read_text(encoding="utf-8")
        self.assertIn("- Q: What if lo > hi?\n  A: raise ValueError (agreed)", contract)
        self.assertEqual(c.events("clamp-001")[-1]["sha"], sha256_text(contract))

    def test_requests_are_blind_then_resumed(self):
        root = make_project(); codex, claude = agreeing()
        c = kit_conductor(root, codex, claude)
        c.run(root / TASK, stop_after="contract")
        first, second = codex.calls
        self.assertEqual((first.stage, first.writable, first.session), ("reading", False, None))
        self.assertEqual((second.stage, second.writable, second.session), ("reveal", False, "codex-s1"))
        self.assertNotEqual(first.cwd, claude.calls[0].cwd)
        self.assertNotIn(str(root), str(first.cwd))                       # the clone lives in the state home, not in the project
        self.assertEqual(first.cwd.parent, claude.calls[0].cwd.parent)    # both clones sit in the task's one folder
        self.assertTrue(folders.is_private(first.cwd.parent))             # which is closed to everyone but this account
        self.assertIn("What if lo > hi?", claude.calls[1].brief)          # claude's reveal shows codex's reading
        sealed = [e for e in c.events("clamp-001") if e["type"] == "reading.sealed" and e["seat"] == "codex"][0]
        self.assertEqual(sealed["sha"], sha256_text(json.dumps(reading(DECISION)(None), sort_keys=True, indent=2)))

    def test_builder_can_be_chosen(self):
        root = make_project(); codex, claude = agreeing()
        codex.script, claude.script = claude.script, codex.script
        c = kit_conductor(root, codex, claude)
        c.run(root / TASK, builder="claude", stop_after="contract")
        self.assertEqual(c.events("clamp-001")[0]["builder"], "claude")

    def test_disagreement_pauses_for_a_ruling_then_resumes_without_asking_again(self):
        root = make_project(); codex, claude = disagreeing()
        c = kit_conductor(root, codex, claude)
        out = c.run(root / TASK, stop_after="contract")
        self.assertEqual((out.status, [d.id for d in out.disputes]), ("needs_ruling", ["D-clamp-001-1"]))
        self.assertIn("swap the bounds", (root / ".parallax/run/clamp-001/cards/D-clamp-001-1.md").read_text(encoding="utf-8"))
        self.assertNotIn("contract.frozen", types(c))
        self.assertEqual(c.status(), [{"task": "clamp-001", "status": "needs_ruling", "pending": ["D-clamp-001-1"]}])
        self.assertEqual(c.run(root / TASK, stop_after="contract").status, "needs_ruling")      # still waiting
        c.rule("D-clamp-001-1", "b")
        self.assertEqual(c.run(root / TASK, stop_after="contract").status, "stopped")
        self.assertEqual((len(codex.calls), len(claude.calls)), (2, 2))
        contract = (root / ".parallax/run/clamp-001/contract-v1.md").read_text(encoding="utf-8")
        self.assertIn("A: swap the bounds (ruled D-clamp-001-1)", contract)

    def test_rule_rejects_nonsense(self):
        root = make_project(); codex, claude = disagreeing()
        c = kit_conductor(root, codex, claude)
        c.run(root / TASK, stop_after="contract")
        for args, message in ((("D-nope-1", "a"), "unknown dispute"), (("D-clamp-001-1", "other"), "note"), (("D-clamp-001-1", "z"), "")):
            with self.assertRaisesRegex(ValueError, message):
                c.rule(*args)
        c.rule("D-clamp-001-1", "other", note="clamp to lo")
        with self.assertRaisesRegex(ValueError, "already ruled"):
            c.rule("D-clamp-001-1", "a")

    def test_a_ruling_becomes_a_precedent_for_the_next_task_and_roles_alternate(self):
        root = make_project(); codex, claude = disagreeing()
        c = kit_conductor(root, codex, claude)
        c.run(root / TASK, stop_after="contract"); c.rule("D-clamp-001-1", "a", while_="inputs are numbers"); c.run(root / TASK, stop_after="contract")
        self.assertEqual(decisions.precedents(c.events()), [{"id": "P-1", "question": "What if lo > hi?", "ruling": "raise ValueError",
                                                             "while": "inputs are numbers", "task": "clamp-001"}])
        codex.script = {"reading": [reading()], "reveal": [reveal()]}
        claude.script = {"reading": [reading()], "reveal": [reveal()]}
        c.run(root / "tasks/clamp-002.md", stop_after="contract")
        self.assertEqual(c.events("clamp-002")[0]["builder"], "claude")
        self.assertIn("P-1", codex.calls[-2].brief)

    def test_interface_objection_is_a_dispute_and_an_amendment(self):
        root = make_project()
        codex = StubSeat("codex", {"reading": [reading()], "reveal": [reveal()]})
        claude = StubSeat("claude", {"reading": [reading()], "reveal": [reveal(interface_ok=False, objection="return an int")]})
        c = kit_conductor(root, codex, claude)
        out = c.run(root / TASK, stop_after="contract")
        self.assertEqual(out.disputes[0].kind, "interface")
        c.rule(out.disputes[0].id, "b"); c.run(root / TASK, stop_after="contract")
        self.assertIn("clamplib.clamp(x, lo, hi) -> number\nAmended: return an int",
                      (root / ".parallax/run/clamp-001/contract-v1.md").read_text(encoding="utf-8"))

class Failures(unittest.TestCase):
    def test_bad_output_is_retried_once_then_blocks_and_a_rerun_resumes(self):
        root = make_project(); codex, claude = agreeing()
        codex.script["reading"] = [lambda r: {"interface": "x"}] * 2 + [reading(DECISION)]
        c = kit_conductor(root, codex, claude)
        out = c.run(root / TASK, stop_after="contract")
        self.assertEqual(out.status, "blocked")
        self.assertRegex(out.detail, r"codex failed at reading: .*decisions")
        self.assertIn("seat.failed", types(c))
        self.assertEqual(c.run(root / TASK, stop_after="contract").status, "stopped")
        self.assertEqual(len([r for r in claude.calls if r.stage == "reading"]), 1)     # claude's sealed reading was reused

    def test_a_reading_that_peeked_is_voided_and_redone_from_scratch(self):
        root = make_project(); codex, claude = agreeing()
        c = kit_conductor(root, codex, claude)
        def peeking(req):
            other = [e["path"] for e in c.events("clamp-001") if e["type"] == "checkout.created" and e["seat"] == "codex"][0]
            return SeatResult(reading()(req), "claude-peek", f'{{"command": "type {other}\\\\clamplib"}}', {"input": 0, "cached": 0, "output": 0})
        claude.script["reading"] = [peeking, reading()]
        self.assertEqual(c.run(root / TASK, stop_after="contract").status, "stopped")
        self.assertIn("reading.voided", types(c))
        first, second = [r for r in claude.calls if r.stage == "reading"]
        self.assertIsNone(second.session)
        self.assertNotEqual(first.cwd, second.cwd)
        self.assertFalse(first.cwd.exists())
        self.assertEqual(claude.discarded, ["claude-peek"])

    def test_a_second_run_is_refused_while_one_is_active_and_a_stale_lock_is_replaced(self):
        root = make_project(); codex, claude = agreeing()
        c = kit_conductor(root, codex, claude)
        lock = root / ".parallax/run/lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(str(os.getpid()), encoding="utf-8")
        out = c.run(root / TASK, stop_after="contract")
        self.assertEqual(out.status, "blocked"); self.assertIn("another parallax run is active", out.detail)
        lock.write_text("999999999", encoding="utf-8")
        self.assertEqual(c.run(root / TASK, stop_after="contract").status, "stopped")
        self.assertFalse(lock.exists())

    def test_bad_task_ids_are_refused(self):
        root = make_project(); codex, claude = agreeing()
        (root / "tasks/bad name!.md").write_text("x\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            kit_conductor(root, codex, claude).run(root / "tasks/bad name!.md")

    def test_rule_waits_for_an_active_run(self):
        # Added in review: a ruling must not write to the journal while another run holds the lock.
        root = make_project(); codex, claude = disagreeing()
        c = kit_conductor(root, codex, claude)
        c.run(root / TASK, stop_after="contract")
        lock = root / ".parallax/run/lock"
        lock.write_text(str(os.getpid()), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "another parallax run is active"):
            c.rule("D-clamp-001-1", "a")
        lock.unlink()
        c.rule("D-clamp-001-1", "a")
        self.assertFalse(lock.exists())
