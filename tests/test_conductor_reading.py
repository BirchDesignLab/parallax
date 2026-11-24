import json, os, unittest
from pathlib import Path
from unittest import mock
from parallax import briefs, decisions, demo, folders, schemas
from parallax.conductor import Conductor
from parallax.config import load_config
from parallax.gitops import rev
from parallax.ledger import sha256_text
from parallax.seats.base import SeatResult
from parallax.seats.stub import StubSeat
from tests.conductor_kit import (COMPARISON, DECISION, EMPTY_WITNESS, INTERFACE_A, INTERFACE_B, INTERFACE_NOTE,
                                 interface_section, kit_conductor, make_project, reading, reveal, types)
from tests.helpers import commit

# Task 19.11: `run` opens a new behavior task confirmed-v1. This module tests the protocol before it (sealed
# readings, reveals, one card per objection, whole-interface rulings), so its conductor opens tasks as Task 18 did.
_kit_conductor = kit_conductor

def kit_conductor(root, codex, claude):
    return _kit_conductor(root, codex, claude, whole=True)

TASK = "tasks/clamp-001.md"

def agreeing():
    return (StubSeat("codex", {"reading": [reading(DECISION)], "reveal": [reveal()]}),
            StubSeat("claude", {"reading": [reading()], "reveal": [reveal((True, ""))]}))

def disagreeing():
    return (StubSeat("codex", {"reading": [reading(DECISION)], "reveal": [reveal()]}),
            StubSeat("claude", {"reading": [reading()], "reveal": [reveal((False, "swap the bounds"))]}))

def contract_text(root, version=1):
    return (root / f".parallax/run/clamp-001/contract-v{version}.md").read_text(encoding="utf-8")

def open_unmarked(c, root, task="clamp-001", builder="codex", challenger="claude"):
    """Record `task.opened` as it was written before Task 18, with no `interface_protocol`."""
    c.journal.append("task.opened", task, kind="behavior", base=rev(root, "main"), builder=builder,
                     challenger=challenger, title=task)

def resumed(root, c):
    """A fresh conductor on the same project and state home, with seats that have no steps left."""
    codex, claude = StubSeat("codex", {}), StubSeat("claude", {})
    again = Conductor(load_config(root), {"codex": codex, "claude": claude}, say=lambda s: None, home=c.home)
    return again, codex, claude

class ToContract(unittest.TestCase):
    def test_a_new_task_records_the_complete_interface_protocol(self):
        root = make_project(); codex, claude = agreeing()
        c = kit_conductor(root, codex, claude)
        c.run(root / TASK, stop_after="contract")
        self.assertEqual(c.events("clamp-001")[0]["interface_protocol"], "whole")

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


class WholeInterface(unittest.TestCase):
    OBJECTION = "callers want the short name clip"
    ALIASES = ("Alias: clip = clamp", "Alias: clamp_range = clamp")

    def test_a_b_and_other_each_leave_exactly_the_selected_interface_and_the_agreed_decision(self):
        for choice, note, expected in (("a", "", INTERFACE_A), ("b", "", INTERFACE_B),
                                       ("other", INTERFACE_NOTE, INTERFACE_NOTE)):
            with self.subTest(choice=choice):
                root = make_project()
                codex = StubSeat("codex", {"reading": [reading(COMPARISON, interface=INTERFACE_A)], "reveal": [reveal()]})
                claude = StubSeat("claude", {"reading": [reading(interface=INTERFACE_B)], "reveal": [
                    reveal((True, ""), interface_ok=False, objection=self.OBJECTION, replacement=INTERFACE_B)]})
                c = kit_conductor(root, codex, claude)
                [d] = c.run(root / TASK, stop_after="contract").disputes
                self.assertEqual((d.kind, d.a, d.b), ("interface", INTERFACE_A, INTERFACE_B))
                self.assertEqual(d.evidence, f"Why claude objects: {self.OBJECTION}\n"
                                             "b and other replace the whole interface; for other, give the complete "
                                             "interface with --note.")
                again, codex, claude = resumed(root, c)
                again.rule(d.id, choice, note=note)
                self.assertEqual(again.run(root / TASK, stop_after="contract").status, "stopped")
                text = contract_text(root)
                self.assertEqual(interface_section(text), expected)
                self.assertIn(f"- Q: {COMPARISON['question']}\n  A: {COMPARISON['answer']} (agreed)\n", text)
                for alias in self.ALIASES:
                    if alias not in expected:
                        self.assertNotIn(alias, text)
                self.assertNotIn("Amended:", text)
                self.assertEqual((codex.calls, claude.calls), ([], []))
                self.assertEqual((types(again).count("ruling.made"), types(again).count("contract.frozen")), (1, 1))
                [ruling] = [e for e in again.events("clamp-001") if e["type"] == "ruling.made"]
                marked = [e for e in again.events("clamp-001") if e["type"] in ("dispute.opened", "contract.frozen")]
                self.assertEqual([e.get("interface_protocol") for e in marked], ["whole", "whole"])
                self.assertEqual(ruling["scope"], "task")
                self.assertEqual(decisions.precedents(again.events()), [])

    def test_the_builders_interface_fields_have_no_effect(self):
        root = make_project()
        codex = StubSeat("codex", {"reading": [reading(interface=INTERFACE_A)], "reveal": [reveal(interface_ok=False)]})
        claude = StubSeat("claude", {"reading": [reading(interface=INTERFACE_B)], "reveal": [reveal()]})
        c = kit_conductor(root, codex, claude)
        self.assertEqual(c.run(root / TASK, stop_after="contract").status, "stopped")
        self.assertEqual(interface_section(contract_text(root)), INTERFACE_A)
        self.assertEqual(([r.stage for r in codex.calls], [r.stage for r in claude.calls]),
                         (["reading", "reveal"], ["reading", "reveal"]))

    def test_a_replacement_equal_to_the_builders_interface_is_retried_in_either_role_assignment(self):
        interfaces = {"codex": INTERFACE_A, "claude": INTERFACE_B}
        for builder, challenger in (("codex", "claude"), ("claude", "codex")):
            with self.subTest(builder=builder):
                root = make_project()
                scripts = {seat: {"reading": [reading(interface=interfaces[seat])]} for seat in interfaces}
                scripts[builder]["reveal"] = [reveal()]
                # The first replacement equals the builder's interface but not the challenger's own.
                scripts[challenger]["reveal"] = [
                    reveal(interface_ok=False, objection=self.OBJECTION, replacement=interfaces[builder] + "\n"),
                    reveal(interface_ok=False, objection=self.OBJECTION, replacement=INTERFACE_NOTE)]
                seats = {seat: StubSeat(seat, scripts[seat]) for seat in interfaces}
                c = kit_conductor(root, seats["codex"], seats["claude"])
                out = c.run(root / TASK, builder=builder, stop_after="contract")
                [d] = out.disputes
                self.assertEqual((d.a, d.b), (interfaces[builder], INTERFACE_NOTE))
                first, second = [r for r in seats[challenger].calls if r.stage == "reveal"]
                self.assertNotIn("Your last reply was rejected", first.brief)
                self.assertIn("interface_replacement is the same as the builder's interface; give the interface you want, "
                              "or set interface_ok to true", second.brief)
                self.assertEqual(len([r for r in seats[builder].calls if r.stage == "reveal"]), 1)

    def test_witness_and_interface_problems_are_reported_together_witness_first(self):
        root = make_project()
        codex = StubSeat("codex", {"reading": [reading(DECISION)], "reveal": [reveal()]})
        claude = StubSeat("claude", {"reading": [reading()], "reveal": [
            reveal((False, "swap the bounds", EMPTY_WITNESS), interface_ok=False, objection=self.OBJECTION),
            reveal((False, "swap the bounds"), interface_ok=False, objection=self.OBJECTION, replacement=INTERFACE_B)]})
        out = kit_conductor(root, codex, claude).run(root / TASK, stop_after="contract")
        self.assertEqual([(d.kind, d.b) for d in out.disputes], [("reading", "swap the bounds"), ("interface", INTERFACE_B)])
        reason = [r for r in claude.calls if r.stage == "reveal"][1].brief.split("## Your last reply was rejected")[1]
        self.assertIn("verdict 0: a disagreement needs a witness with scenario, observation, theirs and mine; "
                      "missing scenario, observation, theirs, mine\n"
                      "interface_replacement must hold the complete interface you want when interface_ok is false",
                      reason)

    def test_interface_rulings_keep_their_scope_and_only_project_rulings_reach_the_next_brief(self):
        root = make_project()
        for n in (3, 4):
            (root / f"tasks/clamp-00{n}.md").write_text(f"Add clamp variant {n} to clamplib.\n", encoding="utf-8")
        r2, r3 = "clamplib.clamp_all(values, lo, hi) -> list", "clamplib.clamp(x, lo, hi) -> float"
        codex, claude = StubSeat("codex", {}), StubSeat("claude", {})
        seats = {"codex": codex, "claude": claude}
        c = kit_conductor(root, codex, claude)
        # A project-scoped interface ruling already landed on main before the upgrade. The ledger holds
        # only this event, so role alternation (which counts task.opened events) is unaffected.
        old = {"ts": "2026-11-01T00:00:00Z", "type": "ruling.made", "task": "clamp-000", "dispute": "D-clamp-000-1",
               "kind": "interface", "question": "What interface should the contract use?", "choice": "b",
               "text": "return a number", "scope": "project", "while": "", "limitation": ""}
        commit(root, {".parallax/ledger.jsonl": json.dumps(old) + "\n"}, "Land clamp-000")
        self.assertEqual([(p["id"], p["task"]) for p in decisions.precedents(c.events())], [("P-1", "clamp-000")])
        open_unmarked(c, root)                                  # clamp-001 was opened before Task 18
        steps = (("clamp-001", "codex", reveal(interface_ok=False, objection="return an int", replacement=None), {}),
                 ("clamp-002", "claude", reveal(interface_ok=False, objection="a list helper", replacement=r2), {}),
                 ("clamp-003", "codex", reveal(interface_ok=False, objection="return a float", replacement=r3),
                  {"scope": "project", "while_": "single user"}))
        for name, builder, objecting, ruling in steps:
            with self.subTest(task=name):
                challenger = "claude" if builder == "codex" else "codex"
                seats[builder].script = {"reading": [reading()],
                                         "reveal": [reveal(replacement=None if name == "clamp-001" else "")]}
                seats[challenger].script = {"reading": [reading()], "reveal": [objecting]}
                [d] = c.run(root / f"tasks/{name}.md", stop_after="contract").disputes
                self.assertEqual((c.events(name)[0]["builder"], d.kind), (builder, "interface"))
                c.rule(d.id, "b", **ruling)
                self.assertEqual(c.run(root / f"tasks/{name}.md", stop_after="contract").status, "stopped")
        rulings = [e for e in c.events() if e["type"] == "ruling.made"]
        self.assertEqual([(e["task"], e["scope"], e["while"]) for e in rulings],
                         [("clamp-000", "project", ""), ("clamp-001", "project", ""), ("clamp-002", "task", ""),
                          ("clamp-003", "project", "single user")])
        self.assertEqual([(p["id"], p["task"], p["ruling"]) for p in decisions.precedents(c.events())],
                         [("P-1", "clamp-000", "return a number"), ("P-2", "clamp-001", "return an int"),
                          ("P-3", "clamp-003", r3)])
        codex.script = {"reading": [reading()], "reveal": [reveal()]}
        claude.script = {"reading": [reading()], "reveal": [reveal()]}
        self.assertEqual(c.run(root / "tasks/clamp-004.md", stop_after="contract").status, "stopped")
        for seat in (codex, claude):
            brief = [r for r in seat.calls if r.stage == "reading"][-1].brief
            self.assertIn("- P-1 (from task clamp-000): What interface should the contract use? Ruling: return a number.\n"
                          "- P-2 (from task clamp-001): What interface should the contract use? Ruling: return an int.\n"
                          f"- P-3 (from task clamp-003): What interface should the contract use? Ruling: {r3}. "
                          "Holds while: single user.", brief)
            self.assertNotIn(r2, brief)
            self.assertNotIn("P-4", brief)


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
        bad = lambda req: {"interface_ok": True, "interface_objection": "", "interface_replacement": "", "verdicts": [
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
        dup = lambda req: {"interface_ok": True, "interface_objection": "", "interface_replacement": "", "verdicts": [
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
            name = [e["path"] for e in c.events("clamp-001") if e["type"] == "checkout.created" and e["seat"] == "codex"][0]
            other = str(req.cwd.parent / name)                  # the record holds the folder name only
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
    """Tasks paused before Task 17 or Task 18 reuse sealed outputs and call only seats with outstanding work."""
    CARD = ".parallax/run/clamp-001/cards/D-clamp-001-1.md"

    def paused(self):
        root = make_project()
        codex = StubSeat("codex", {"reading": [reading(DECISION)], "reveal": [legacy_reveal()]})
        claude = StubSeat("claude", {"reading": [reading()], "reveal": [legacy_reveal((False, "swap the bounds"))]})
        c = kit_conductor(root, codex, claude)
        open_unmarked(c, root)
        with mock.patch("parallax.schemas.REVEAL_AMENDING", OLD_REVEAL), mock.patch("parallax.decisions.witness_problem", lambda v: None):
            self.assertEqual(c.run(root / TASK, stop_after="contract").status, "needs_ruling")
        return root, c

    def rewrite(self, root, change):
        path = root / ".parallax/run/journal.jsonl"
        events = [change(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line]
        path.write_text("".join(json.dumps(e) + "\n" for e in events if e is not None), encoding="utf-8", newline="\n")

    def test_reveals_sealed_before_the_upgrade_open_a_reasons_only_card(self):
        root, c = self.paused()
        (root / self.CARD).unlink()
        self.rewrite(root, lambda e: None if e["type"] == "dispute.opened" else e)
        again, codex, claude = resumed(root, c)
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
                again, codex, claude = resumed(root, c)
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

    def test_an_unmarked_task_finishes_its_reveals_under_the_prior_protocol_in_either_order(self):
        # Task 17's shape: a witnessed disagreement and an interface delta, with no replacement key.
        task17 = reveal((False, "swap the bounds"), interface_ok=False, objection="return an int", replacement=None)
        # A schema-valid Task 17 reply with an empty witness: Task 17's check must still reject it.
        empty17 = reveal((False, "swap the bounds", EMPTY_WITNESS), interface_ok=False, objection="return an int",
                         replacement=None)
        late = {"codex": [reveal(replacement=None)], "claude": [empty17, task17]}
        nothing = lambda req: {}
        for sealed, waiting in (("codex", "claude"), ("claude", "codex")):
            with self.subTest(sealed_first=sealed):
                root = make_project()
                scripts = {"codex": {"reading": [reading(DECISION)]}, "claude": {"reading": [reading()]}}
                scripts[sealed]["reveal"] = list(late[sealed])
                scripts[waiting]["reveal"] = [nothing, nothing]
                first = {seat: StubSeat(seat, scripts[seat]) for seat in ("codex", "claude")}
                c = kit_conductor(root, first["codex"], first["claude"])
                open_unmarked(c, root)
                self.assertEqual(c.run(root / TASK, stop_after="contract").status, "blocked")
                task_text = (root / TASK).read_text(encoding="utf-8")
                for seat, role in (("codex", "builder"), ("claude", "challenger")):
                    [r] = [r for r in first[seat].calls if r.stage == "reading"]
                    self.assertEqual(r.brief, briefs.reading(task_text, role, c.cfg, [], whole=False))
                again, codex, claude = resumed(root, c)
                seats = {"codex": codex, "claude": claude}
                seats[waiting].script = {"reveal": list(late[waiting])}
                out = again.run(root / TASK, stop_after="contract")
                self.assertEqual(seats[sealed].calls, [])
                calls = seats[waiting].calls
                self.assertEqual([r.stage for r in calls], ["reveal"] * len(late[waiting]))
                role, other = ("challenger", reading(DECISION)(None)) if waiting == "claude" else ("builder", reading()(None))
                other = json.loads(json.dumps(other, sort_keys=True))     # as the conductor reloads it from storage
                self.assertIs(calls[0].schema, schemas.REVEAL_AMENDING)
                self.assertEqual(calls[0].brief, briefs.reveal(role, other, whole=False))
                # The challenger's empty Task 17 witness was rejected, in whichever run it reached.
                challenger_seat = seats["claude"] if waiting == "claude" else first["claude"]
                initial, retry = [r for r in challenger_seat.calls if r.stage == "reveal"]
                self.assertIs(initial.schema, schemas.REVEAL_AMENDING)
                reason = retry.brief.split("## Your last reply was rejected", 1)[1]
                self.assertIn("verdict 0: a disagreement needs a witness", reason)
                self.assertNotIn("interface_replacement", reason)
                self.assertEqual([(d.kind, d.b, d.evidence) for d in out.disputes][1], ("interface", "return an int", ""))
                again.rule("D-clamp-001-1", "a"); again.rule("D-clamp-001-2", "b")
                self.assertEqual(again.run(root / TASK, stop_after="contract").status, "stopped")
                self.assertEqual(interface_section(contract_text(root)),
                                 "clamplib.clamp(x, lo, hi) -> number\nAmended: return an int")

    def test_a_legacy_interface_card_ruled_after_the_upgrade_still_amends_with_project_scope(self):
        for choice, note, delta in (("b", "", "return an int"), ("other", "return a float", "return a float")):
            with self.subTest(choice=choice):
                root = make_project()
                codex = StubSeat("codex", {"reading": [reading()], "reveal": [reveal(replacement=None)]})
                claude = StubSeat("claude", {"reading": [reading()], "reveal": [
                    reveal(interface_ok=False, objection="return an int", replacement=None)]})
                c = kit_conductor(root, codex, claude)
                open_unmarked(c, root)
                out = c.run(root / TASK, stop_after="contract")
                self.assertEqual([(d.kind, d.b, d.evidence) for d in out.disputes], [("interface", "return an int", "")])
                again, codex, claude = resumed(root, c)
                again.rule("D-clamp-001-1", choice, note=note)
                self.assertEqual(again.run(root / TASK, stop_after="contract").status, "stopped")
                text = contract_text(root)
                self.assertEqual(interface_section(text), f"clamplib.clamp(x, lo, hi) -> number\nAmended: {delta}")
                self.assertEqual(text.count("Amended:"), 1)
                self.assertEqual((codex.calls, claude.calls), ([], []))
                [ruling] = [e for e in again.events("clamp-001") if e["type"] == "ruling.made"]
                self.assertEqual(ruling["scope"], "project")

    def test_the_demo_seats_can_finish_an_unmarked_task(self):
        # An interrupted stub demo, reopened after the upgrade, still owes both reveals.
        root = make_project()
        stubs = demo.stub_seats()
        c = kit_conductor(root, stubs["codex"], stubs["claude"])
        open_unmarked(c, root)
        out = c.run(root / TASK, stop_after="contract")
        self.assertEqual([(d.kind, d.question, d.b) for d in out.disputes],
                         [("reading", "What if lo > hi?", "swap the bounds")])
        for seat in stubs.values():
            [call] = [r for r in seat.calls if r.stage == "reveal"]
            self.assertIs(call.schema, schemas.REVEAL_AMENDING)

    def test_only_the_challengers_recorded_reveal_must_match_the_protocol(self):
        # One reveal is sealed under `written`; the other seat fails twice, so the run blocks before
        # settlement. Then only the opening's marker flips to `now`, and the outstanding seat answers under it.
        nothing = lambda req: {}
        objecting = lambda protocol: reveal(interface_ok=False, objection="return an int",
                                            replacement="clamplib.clamp(x, lo, hi) -> int" if protocol == "whole" else None)
        accepting = lambda protocol: reveal(replacement="" if protocol == "whole" else None)
        answer = {"codex": accepting, "claude": objecting}
        b_under = {"whole": "clamplib.clamp(x, lo, hi) -> int", "amending": "return an int"}
        for written, now in (("amending", "whole"), ("whole", "amending")):
            for sealed, waiting in (("claude", "codex"), ("codex", "claude")):
                with self.subTest(written=written, sealed=sealed):
                    root = make_project()
                    scripts = {"codex": {"reading": [reading()]}, "claude": {"reading": [reading()]}}
                    scripts[sealed]["reveal"] = [answer[sealed](written)]
                    scripts[waiting]["reveal"] = [nothing, nothing]
                    c = kit_conductor(root, StubSeat("codex", scripts["codex"]), StubSeat("claude", scripts["claude"]))
                    if written == "amending":
                        open_unmarked(c, root)
                    self.assertEqual(c.run(root / TASK, stop_after="contract").status, "blocked")
                    self.rewrite(root, lambda e: ({k: v for k, v in e.items() if k != "interface_protocol"}
                                                  | ({"interface_protocol": "whole"} if now == "whole" else {}))
                                 if e["type"] == "task.opened" else e)
                    again, codex, claude = resumed(root, c)
                    {"codex": codex, "claude": claude}[waiting].script = {"reveal": [answer[waiting](now)]}
                    out = again.run(root / TASK, stop_after="contract")
                    if sealed == "claude":
                        # The challenger's reveal is from the other protocol: block, now and on every rerun.
                        detail = (f"claude's recorded reveal does not match clamp-001's interface protocol ({now}); "
                                  "it was written by another version of parallax")
                        self.assertEqual((out.status, out.detail), ("blocked", detail))
                        self.assertFalse((root / self.CARD).exists())
                        self.assertFalse({"dispute.opened", "contract.frozen"} & set(types(again)))
                        again, codex, claude = resumed(root, c)
                        out = again.run(root / TASK, stop_after="contract")
                        self.assertEqual((out.status, out.detail, codex.calls, claude.calls), ("blocked", detail, [], []))
                    else:
                        # Only the builder's reveal is from the other protocol, and its interface fields have no effect.
                        self.assertEqual([(d.kind, d.b) for d in out.disputes], [("interface", b_under[now])])

    def test_a_task_17_card_on_a_marked_task_blocks_the_run_and_the_ruling(self):
        root = make_project()
        codex = StubSeat("codex", {"reading": [reading()], "reveal": [reveal()]})
        claude = StubSeat("claude", {"reading": [reading()], "reveal": [
            reveal(interface_ok=False, objection="return an int", replacement="clamplib.clamp(x, lo, hi) -> int")]})
        c = kit_conductor(root, codex, claude)
        self.assertEqual(c.run(root / TASK, stop_after="contract").status, "needs_ruling")
        # The card Task 17 would open from the same sealed reveals: the reason as b, no evidence, no marker.
        old = decisions.Dispute("D-clamp-001-1", "interface", "What interface should the contract use?",
                                "clamplib.clamp(x, lo, hi) -> number", "return an int",
                                "codex (builder)", "claude (challenger)")
        self.rewrite(root, lambda e: {"ts": e["ts"], "type": e["type"], "task": e["task"], **old.to_fields()}
                     if e["type"] == "dispute.opened" else e)
        (root / self.CARD).write_text(decisions.render_card(old), encoding="utf-8", newline="\n")
        detail = ("D-clamp-001-1 does not match clamp-001's interface protocol (whole); "
                  "it was written by another version of parallax")
        again, codex, claude = resumed(root, c)
        out = again.run(root / TASK, stop_after="contract")
        self.assertEqual((out.status, out.detail), ("blocked", detail))
        with self.assertRaises(ValueError) as caught:
            again.rule("D-clamp-001-1", "b")
        self.assertEqual(str(caught.exception), detail)
        self.assertFalse({"ruling.made", "contract.frozen"} & set(types(again)))
        self.assertEqual((root / self.CARD).read_text(encoding="utf-8"), decisions.render_card(old))
        self.assertEqual((codex.calls, claude.calls), ([], []))

    def test_a_task_17_freeze_on_a_marked_task_blocks_before_build_or_probe(self):
        root = make_project()
        replacement = "clamplib.clamp(x, lo, hi) -> int"
        codex = StubSeat("codex", {"reading": [reading()], "reveal": [reveal()]})
        claude = StubSeat("claude", {"reading": [reading()], "reveal": [
            reveal(interface_ok=False, objection="return an int", replacement=replacement)]})
        c = kit_conductor(root, codex, claude)
        [d] = c.run(root / TASK, stop_after="contract").disputes
        c.rule(d.id, "b")
        # The v1 Task 17 would freeze from that ruling: the whole b under Amended:, its matching hash, no marker.
        text = decisions.render_contract("clamp-001", 1, (root / TASK).read_text(encoding="utf-8"),
                                         f"clamplib.clamp(x, lo, hi) -> number\nAmended: {replacement}", [], [])
        (root / ".parallax/run/clamp-001/contract-v1.md").write_text(text, encoding="utf-8", newline="\n")
        c.journal.append("contract.frozen", "clamp-001", version=1, sha=sha256_text(text))
        again, codex, claude = resumed(root, c)
        out = again.run(root / TASK)
        self.assertEqual((out.status, out.detail),
                         ("blocked", "contract v1 does not match clamp-001's interface protocol (whole); "
                                     "it was written by another version of parallax"))
        self.assertEqual((codex.calls, claude.calls), ([], []))
        self.assertEqual(types(again).count("contract.frozen"), 1)
        self.assertEqual(contract_text(root), text)
