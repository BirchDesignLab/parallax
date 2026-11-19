import json, os, unittest
from pathlib import Path
from unittest import mock
from parallax import decisions, folders, schemas
from parallax.conductor import Conductor
from parallax.config import load_config
from parallax.ledger import sha256_text
from parallax.seats.base import SeatResult
from parallax.seats.stub import StubSeat
from tests.conductor_kit import DECISION, EMPTY_WITNESS, kit_conductor, make_project, reading, reveal, types

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
        card = (root / ".parallax/run/clamp-001/cards/D-clamp-001-1.md").read_text(encoding="utf-8")
        for part in ("Witness, written by claude:", "Scenario: clamp(5, 10, 1)",
                     "Under a (codex), claude predicts: raises ValueError",
                     "Under b (claude), claude predicts: returns 5", "b) claude (challenger): swap the bounds",
                     "  a) codex: caller error"):
            self.assertIn(part, card)
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

    def test_a_witness_is_shown_but_never_enters_the_contract_or_precedents(self):
        root = make_project(); codex, claude = disagreeing()
        odd = {"scenario": "clamp(5, 10, 1)", "observation": "WITNESS-ONLY-7f3", "theirs": "raises ValueError",
               "mine": "returns 5", "decided_by": ""}
        claude.script["reveal"] = [reveal((False, "swap the bounds", odd))]
        c = kit_conductor(root, codex, claude)
        c.run(root / TASK, stop_after="contract")
        [opened] = [e for e in c.events("clamp-001") if e["type"] == "dispute.opened"]
        self.assertIn("WITNESS-ONLY-7f3", opened["evidence"])
        self.assertIn("WITNESS-ONLY-7f3", (root / ".parallax/run/clamp-001/cards/D-clamp-001-1.md").read_text(encoding="utf-8"))
        c.rule("D-clamp-001-1", "b")
        self.assertEqual(c.run(root / TASK, stop_after="contract").status, "stopped")
        contract = (root / ".parallax/run/clamp-001/contract-v1.md").read_text(encoding="utf-8")
        self.assertIn("A: swap the bounds (ruled D-clamp-001-1)", contract)
        self.assertNotIn("WITNESS-ONLY-7f3", contract)
        self.assertEqual([p["ruling"] for p in decisions.precedents(c.events())], ["swap the bounds"])

    def test_an_agreeing_reveal_costs_no_extra_call(self):
        root = make_project(); codex, claude = agreeing()
        c = kit_conductor(root, codex, claude)
        self.assertEqual(c.run(root / TASK, stop_after="contract").status, "stopped")
        self.assertIn("contract.frozen", types(c))
        self.assertEqual(([r.stage for r in codex.calls], [r.stage for r in claude.calls]),
                         (["reading", "reveal"], ["reading", "reveal"]))


class Failures(unittest.TestCase):
    def test_bad_output_is_retried_once_then_blocks_and_a_rerun_resumes(self):
        root = make_project(); codex, claude = agreeing()
        codex.script["reading"] = [lambda r: {"interface": "x"}] * 2 + [reading(DECISION)]
        c = kit_conductor(root, codex, claude)
        out = c.run(root / TASK, stop_after="contract")
        self.assertEqual(out.status, "blocked")
        self.assertRegex(out.detail, r"codex failed at reading: .*decisions")
        first, second = [r for r in codex.calls if r.stage == "reading"][:2]
        self.assertEqual(first.brief, second.brief)          # an adapter failure retries the same request
        self.assertIn("seat.failed", types(c))
        self.assertEqual(c.run(root / TASK, stop_after="contract").status, "stopped")
        self.assertEqual(len([r for r in claude.calls if r.stage == "reading"]), 1)     # claude's sealed reading was reused

    def sealed_session(self, c, seat):
        return next(e["session"] for e in c.events("clamp-001") if e["type"] == "reading.sealed" and e["seat"] == seat)

    def test_a_witness_that_shows_no_difference_is_retried_with_the_reason(self):
        root = make_project(); codex, claude = disagreeing()
        same = {"scenario": "clamp(5, 10, 1)", "observation": "result", "theirs": "returns 5", "mine": "returns 5", "decided_by": ""}
        claude.script["reveal"] = [reveal((False, "swap the bounds", same)), reveal((False, "swap the bounds"))]
        c = kit_conductor(root, codex, claude)
        out = c.run(root / TASK, stop_after="contract")
        self.assertEqual((out.status, [d.id for d in out.disputes]), ("needs_ruling", ["D-clamp-001-1"]))
        first, second = [r for r in claude.calls if r.stage == "reveal"]
        self.assertNotIn("Your last reply was rejected", first.brief)
        self.assertIn("verdict 0: the witness predicts the same result under both answers (returns 5)", second.brief)
        self.assertEqual(second.brief.count("Your last reply was rejected"), 1)
        self.assertEqual((first.session, second.session), (self.sealed_session(c, "claude"),) * 2)

    def test_every_witness_problem_is_reported_in_index_order(self):
        root = make_project(); codex, claude = disagreeing()
        codex.script["reading"] = [reading(DECISION, {"question": "NaN?", "answer": "return NaN", "why": "ieee"})]
        same = {"scenario": "s", "observation": "o", "theirs": "t", "mine": "t", "decided_by": ""}
        bad = lambda req: {"interface_ok": True, "interface_objection": "", "verdicts": [
            {"index": 1, "agree": False, "counter": "c", "why": "", "witness": same},
            {"index": 0, "agree": False, "counter": "c", "why": "", "witness": EMPTY_WITNESS}]}
        claude.script["reveal"] = [bad, reveal((True, ""), (True, ""))]
        kit_conductor(root, codex, claude).run(root / TASK, stop_after="contract")
        second = [r for r in claude.calls if r.stage == "reveal"][1]
        self.assertIn("verdict 0: a disagreement needs a witness with scenario, observation, theirs and mine; "
                      "missing scenario, observation, theirs, mine\n"
                      "verdict 1: the witness predicts the same result under both answers (t)", second.brief)

    def test_the_index_check_comes_before_the_witness_check(self):
        root = make_project(); codex, claude = disagreeing()
        codex.script["reading"] = [reading(DECISION, {"question": "NaN?", "answer": "return NaN", "why": "ieee"})]
        dup = lambda req: {"interface_ok": True, "interface_objection": "", "verdicts": [
            {"index": 0, "agree": False, "counter": "c", "why": "", "witness": EMPTY_WITNESS}] * 2}
        claude.script["reveal"] = [dup, reveal((True, ""), (True, ""))]
        kit_conductor(root, codex, claude).run(root / TASK, stop_after="contract")
        reason = [r for r in claude.calls if r.stage == "reveal"][1].brief.split("Your last reply was rejected")[1]
        self.assertIn("verdicts must give exactly one index for each of 0..1, got [0, 0]", reason)
        self.assertNotIn("witness", reason)

    def test_a_witness_that_stays_empty_blocks(self):
        root = make_project(); codex, claude = disagreeing()
        claude.script["reveal"] = [reveal((False, "swap the bounds", EMPTY_WITNESS))] * 2
        out = kit_conductor(root, codex, claude).run(root / TASK, stop_after="contract")
        self.assertEqual(out.status, "blocked")
        self.assertIn("claude failed at reveal: verdict 0: a disagreement needs a witness", out.detail)

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


OLD_REVEAL = schemas._obj(interface_ok=schemas._B, interface_objection=schemas._S,
                          verdicts=schemas._list(schemas._obj(index=schemas._I, agree=schemas._B,
                                                              counter=schemas._S, why=schemas._S)))

def legacy_reveal(*verdicts):
    return lambda req: {"interface_ok": True, "interface_objection": "",
                        "verdicts": [{"index": i, "agree": a, "counter": c, "why": "older reason"}
                                     for i, (a, c) in enumerate(verdicts)]}

class Upgrade(unittest.TestCase):
    """A task paused before Task 17, with witnessless reveals sealed, resumes under it without a seat call."""
    CARD = ".parallax/run/clamp-001/cards/D-clamp-001-1.md"

    def paused(self):
        root = make_project()
        codex = StubSeat("codex", {"reading": [reading(DECISION)], "reveal": [reveal()]})
        claude = StubSeat("claude", {"reading": [reading()], "reveal": [legacy_reveal((False, "swap the bounds"))]})
        c = kit_conductor(root, codex, claude)
        with mock.patch("parallax.schemas.REVEAL", OLD_REVEAL), mock.patch("parallax.decisions.witness_problem", lambda v: None):
            self.assertEqual(c.run(root / TASK, stop_after="contract").status, "needs_ruling")
        return root, c

    def rewrite(self, root, change):
        path = root / ".parallax/run/journal.jsonl"
        events = [change(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line]
        path.write_text("".join(json.dumps(e) + "\n" for e in events if e is not None), encoding="utf-8", newline="\n")

    def resumed(self, root, c):
        codex, claude = StubSeat("codex", {}), StubSeat("claude", {})
        again = Conductor(load_config(root), {"codex": codex, "claude": claude}, say=lambda s: None, home=c.home)
        return again, codex, claude

    def test_reveals_sealed_before_the_upgrade_open_a_reasons_only_card(self):
        root, c = self.paused()
        (root / self.CARD).unlink()
        self.rewrite(root, lambda e: None if e["type"] == "dispute.opened" else e)
        again, codex, claude = self.resumed(root, c)
        out = again.run(root / TASK, stop_after="contract")
        self.assertEqual((out.status, [d.id for d in out.disputes]), ("needs_ruling", ["D-clamp-001-1"]))
        self.assertEqual(out.disputes[0].evidence, "Reasons:\n  a) codex: caller error\n  b) claude: older reason")
        self.assertNotIn("Witness", (root / self.CARD).read_text(encoding="utf-8"))
        self.assertEqual((codex.calls, claude.calls), ([], []))

    def test_a_card_opened_before_the_upgrade_is_kept_then_ruled_and_frozen(self):
        old = decisions.Dispute("D-clamp-001-1", "reading", "What if lo > hi?", "raise ValueError", "swap the bounds",
                                "codex (builder)", "claude (challenger)")
        for legacy in ({"evidence": ""}, {}):              # the historical empty value, and the older form without it
            with self.subTest(legacy=legacy):
                root, c = self.paused()
                self.rewrite(root, lambda e: ({k: v for k, v in e.items() if k != "evidence"} | legacy)
                             if e["type"] == "dispute.opened" else e)
                (root / self.CARD).write_text(decisions.render_card(old), encoding="utf-8", newline="\n")
                before = (root / self.CARD).read_bytes()
                again, codex, claude = self.resumed(root, c)
                out = again.run(root / TASK, stop_after="contract")
                self.assertEqual((out.status, [d.id for d in out.disputes]), ("needs_ruling", ["D-clamp-001-1"]))
                self.assertEqual(decisions.render_card(out.disputes[0]).encode("utf-8"), before)
                self.assertEqual((root / self.CARD).read_bytes(), before)
                self.assertEqual(sum(e["type"] == "dispute.opened" for e in again.events("clamp-001")), 1)
                again.rule("D-clamp-001-1", "b")
                self.assertEqual(again.run(root / TASK, stop_after="contract").status, "stopped")
                self.assertIn("A: swap the bounds (ruled D-clamp-001-1)",
                              (root / ".parallax/run/clamp-001/contract-v1.md").read_text(encoding="utf-8"))
                self.assertEqual((codex.calls, claude.calls), ([], []))
