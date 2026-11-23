import json, os, subprocess, sys, unittest
from pathlib import Path
from unittest import mock
import parallax
from parallax import cli, gitops
from parallax.conductor import Conductor
from parallax.ledger import Journal, parse_lines
from parallax.seats.stub import StubSeat
from tests.conductor_kit import FILE, PROBES, builds, interface_section, kit_conductor, make_project, probes, responds
from tests.test_batch import (A_POLICY, AGREE, ALIAS_REVEALS, ASSENT, NO_ASSENT, QUESTION, UNKNOWN, all_agreed,
                              one_dispute, shown_digests)
from tests.test_conductor_batch import PUBLIC, crashes, proposes, reviews
from tests.test_conductor_frozen import THREE, TWO, contract, freezes, on_main, rewrite_main, seated
from tests.test_conductor_reading import resumed
from tests.test_conductor_ruled import rule, ruled
from tests.test_conductor_settled import (TASK, TASK_FILE, TWO_PENDING, TWO_PENDING_REVIEW, answers, printed, run,
                                          settlements, told)
from tests.test_conductor_tail import NEXT, NEXT_FILE, precedents_read
from tests.test_decisions import ROLE_READINGS, ROLE_REVEALS, role_reveals

BATCH = ("batch.proposed", "batch.reviewed")

# Task 19.10. The pre-plan's acceptance cases (docs/designs/2026-11-19-task-19-codex-preplan.md, "Acceptance
# fixtures"), run through `run`, `rule` and the CLI. Since Task 19.11 `run` opens each new behavior
# task confirmed-v1 itself.
#
# Every seat reply here is a fixture input written for the test from the findings of the recorded runs: the
# private replies of those runs were removed at landing. The witnesses, attestations and interface wording are
# new, not recorded.
EMPTY = {"scenario": "", "observation": "", "theirs": "", "mine": "", "decided_by": ""}
ONE = "D-clamp-001-1"
FROZEN = ("stopped", "stopped after the contract was frozen")

def decision(question, answer, why):
    return {"question": question, "answer": answer, "why": why}

def agree(index):
    return {"index": index, "agree": True, "counter": "", "why": "", "witness": dict(EMPTY)}

def object_(index, counter, why, scenario, observation, theirs, mine, decided_by=""):
    return {"index": index, "agree": False, "counter": counter, "why": why,
            "witness": {"scenario": scenario, "observation": observation, "theirs": theirs, "mine": mine,
                        "decided_by": decided_by}}

def stages(seat):
    return [req.stage for req in seat.calls]

def project(readings, reveals, propose=None, review=None):
    """A project and stub seats that hold one reading and one reveal each and, when given, the builder's
    proposal and the challenger's review. The project's first task is built by codex, the first seat."""
    root = make_project()
    codex = StubSeat("codex", {"reading": [answers(readings["builder"])], "reveal": [answers(reveals["builder"])],
                               **({"batch_propose": [propose]} if propose else {})})
    claude = StubSeat("claude", {"reading": [answers(readings["challenger"])], "reveal": [answers(reveals["challenger"])],
                                 **({"batch_review": [review]} if review else {})})
    return root, kit_conductor(root, codex, claude), codex, claude

def to_contract(root, c):
    """A fresh conductor with no seat steps left runs to the freeze: its outcome, contract v1 and the calls made."""
    c2, codex, claude = resumed(root, c)
    try:
        outcome = c2.run(root / TASK_FILE, stop_after="contract")
    except Exception as error:
        raise AssertionError(f"the run raised {error!r}") from error
    path = root / ".parallax/run" / TASK / "contract-v1.md"
    return told(outcome), (path.read_text(encoding="utf-8") if path.exists() else None), codex.calls + claude.calls


# ---------------------------------------------------------------------------------------------------------
# 11-19, a fresh confirmed-v1 task. Codex builds with six decisions, Claude challenges with ten. Claude objects
# to three of Codex's, Codex to one of Claude's, the other twelve are agreed, and Claude objects to the
# interface with a complete replacement and flags that its predicate depends on it.
STRICT = "Raise ValueError when hi < lo."
INCLUSIVE = "Evaluate lo <= hi first. Raise ValueError when false."
NOV19_INTERFACE = "clamplib.clamp(x, lo, hi) -> x, lo or hi; raises ValueError when hi < lo"
UNSPECIFIED = ("What does the error message say?", "Unspecified.")
ORDER = ("In what order is x compared with the bounds?", "x < lo, then hi < x.")
LT_CALL = "x = Lt(1); clamp(x, Lt(0), Lt(2)), where Lt defines only __lt__ and compares the wrapped values"
NOV19_REPLACEMENT = ("Files: clamplib/__init__.py (modify)\n"
                     "Import: from clamplib import clamp\n"
                     "Signature: clamp(x, lo, hi), returning one of the objects passed as x, lo or hi\n"
                     "Errors: ValueError for rejected bounds; any exception an operand comparison raises propagates")
NOV19_BUILDER = [
    # builder/0 and builder/2 are disputed, and each also holds a promise both seats keep: the unspecified
    # message, and the order of the two comparisons against x.
    decision("What if lo > hi?", f"{STRICT} The message is unspecified.", "a reversed range is a caller error"),
    decision("What if a bound is NaN?", "No check: the comparisons decide.", "NaN compares false"),
    decision("Which comparisons are made, and in what order?", "Only hi < lo on the bounds; then x < lo, then hi < x.",
             "one strict comparison, lower bound first"),
    decision("What is returned when x is inside the range?", "x itself.", "identity"),
    decision("Are the bounds inclusive?", "Yes: x equal to a bound is returned.", "lo..hi includes both ends"),
    decision("May the bounds be of another type than x?", "Yes, when they compare with it.", "duck typing"),
]
NOV19_CHALLENGER = [
    decision("When are the bounds rejected?", INCLUSIVE, "NaN bounds must not pass"),
    decision("What is returned when x is below lo?", "lo itself.", "identity"),
    decision("What is returned when x is above hi?", "hi itself.", "identity"),
    decision("What if lo == hi?", "Return x when it equals them, else the bound.", "a one-point range is valid"),
    decision("What if x is NaN?", "Return x.", "both comparisons are false"),
    decision("Is any argument converted?", "No.", "the objects passed come back"),
    decision("Are keyword arguments accepted?", "Yes: x, lo and hi.", "plain parameters"),
    decision("Is anything else exported?", "No.", "one function"),
    decision("Does clamp mutate its arguments?", "No.", "it only compares"),
    decision("What happens if an operand comparison raises?", "The exception propagates.", "caller types own it"),
]
NOV19_READINGS = {"builder": {"interface": NOV19_INTERFACE, "decisions": NOV19_BUILDER, "predicted_failures": []},
                  "challenger": {"interface": NOV19_REPLACEMENT, "decisions": NOV19_CHALLENGER,
                                 "predicted_failures": []}}
NAN_CALL = "clamp(8, float('nan'), 5)"
NOV19_REVEALS = {
    "challenger": {"interface_ok": False,
                   "interface_objection": "the interface must say that comparison exceptions propagate",
                   "interface_replacement": NOV19_REPLACEMENT,
                   "conflicts": [{"source": "challenger/0", "target": "builder/interface",
                                  "reason": "evaluating lo <= hi can raise for types the interface must admit"}],
                   "verdicts": [object_(0, f"{INCLUSIVE} The message is unspecified.", "NaN bounds must raise", NAN_CALL,
                                        "result or exception", "returns 5", "raises ValueError"),
                                object_(1, "A NaN bound raises ValueError.", "lo <= hi is false for NaN",
                                        "clamp(8, 1, float('nan'))", "result or exception", "returns 8",
                                        "raises ValueError"),
                                object_(2, "lo <= hi on the bounds; then x < lo, then hi < x.",
                                        "one inclusive comparison, the same order", LT_CALL,
                                        "result or exception", "returns the original x", "raises TypeError"),
                                agree(3), agree(4), agree(5)]},
    # Codex reports the same call and observation Claude did, on the other reading's row: two authors, one case.
    "builder": {"interface_ok": True, "interface_objection": "", "interface_replacement": "", "conflicts": [],
                "verdicts": [object_(0, STRICT, "strict comparisons only", NAN_CALL, "result or exception",
                                     "raises ValueError", "returns 5"),
                             *[agree(i) for i in range(1, 10)]]},
}
NOV19_CONFLICT = NOV19_REVEALS["challenger"]["conflicts"]
NOV19_MEMBERS = ["builder/0", "builder/1", "builder/2", "challenger/0", "builder/interface"]
NOV19_QUESTION = "Which predicate rejects the bounds?"
NOV19_COMMON = (
    [{"slot": "interface", "question": "What interface should the contract use?", "text": NOV19_REPLACEMENT,
      "sources": ["builder/interface"]}]
    + [{"slot": f"p/{n}", "question": d["question"], "text": d["answer"], "sources": [key]}
       for n, (key, d) in enumerate([(f"builder/{i}", NOV19_BUILDER[i]) for i in (3, 4, 5)]
                                    + [(f"challenger/{i}", NOV19_CHALLENGER[i]) for i in range(1, 10)])]
    # The two promises both seats keep from inside disputed answers: common terms whose source is disputed.
    + [{"slot": "p/12", "question": UNSPECIFIED[0], "text": UNSPECIFIED[1], "sources": ["builder/0"]},
       {"slot": "p/13", "question": ORDER[0], "text": ORDER[1], "sources": ["builder/2"]}])
NOV19_WITNESSES = [
    {"source": "builder/0", "scenario": NAN_CALL, "observation": "result or exception", "a": "returns 5",
     "b": "raises ValueError"},
    {"source": "builder/1", "scenario": "clamp(8, 1, float('nan'))", "observation": "result or exception",
     "a": "returns 8", "b": "raises ValueError"},
    {"source": "builder/2", "scenario": LT_CALL, "observation": "result or exception", "a": "returns the original x",
     "b": "raises TypeError"},
    {"source": "challenger/0", "scenario": NAN_CALL, "observation": "result or exception", "a": "returns 5",
     "b": "raises ValueError"},
]
NOV19_FALLBACK = {"known": True, "members": NOV19_MEMBERS,
                  "question": "What complete interface and bounds predicate should clamplib have?"}
NOV19_PROPOSAL = {
    "packet_sha": "", "decision": "propose", "common": NOV19_COMMON,
    "choices": [{"slot": "c/0", "target": "policy", "question": NOV19_QUESTION, "members": NOV19_MEMBERS,
                 "a": {"interface": "", "policy": STRICT}, "b": {"interface": "", "policy": INCLUSIVE},
                 "witnesses": NOV19_WITNESSES}],
    "withdrawn": [], "assent": ASSENT, "votes": [{"slot": "c/0", "sign": ["a"], "reason": "strict comparisons only"}],
    "preferences": [{"slot": "c/0", "answer": "a"}], "fallback": NOV19_FALLBACK, "refusal_reason": "", "affected": []}
NOV19_REVIEW = {"packet_sha": "", "proposal_sha": "", "decision": "attest", "assent": ASSENT,
                "votes": [{"slot": "c/0", "sign": ["b"], "reason": "NaN bounds must raise"}],
                "fallback_complete": True, "refusal_reason": "", "affected": []}
NOV19_OTHER = "Raise ValueError when hi < lo.\nRaise ValueError when lo or hi is NaN."

# Written by hand from the fixture above: both votes with their reasons, each source under its owner with the
# other seat's position and reason, the four original witnesses under their authors (builder/0's and
# challenger/0's are the same call, reported by each seat), the type that defines only `<`, and the four
# predictions both seats confirmed. The replacement
# interface has line breaks, so the card shows it as one quoted literal.
NOV19_CARD = f"""Dispute D-clamp-001-1 (reading)

Which predicate rejects the bounds?

a) codex (builder):
| Raise ValueError when hi < lo.
b) claude (challenger):
| Evaluate lo <= hi first. Raise ValueError when false.
other) Supply the policy with --note.

Votes:
- codex (builder) signs a: strict comparisons only
- claude (challenger) signs b: NaN bounds must raise

Sources:
- builder/0: What if lo > hi?
  codex (builder): Raise ValueError when hi < lo. The message is unspecified.
    why: a reversed range is a caller error
  claude (challenger): Evaluate lo <= hi first. Raise ValueError when false. The message is unspecified.
    why: NaN bounds must raise
  witness from claude (challenger): clamp(8, float('nan'), 5) (result or exception): codex (builder) returns 5; claude (challenger) raises ValueError
- builder/1: What if a bound is NaN?
  codex (builder): No check: the comparisons decide.
    why: NaN compares false
  claude (challenger): A NaN bound raises ValueError.
    why: lo <= hi is false for NaN
  witness from claude (challenger): clamp(8, 1, float('nan')) (result or exception): codex (builder) returns 8; claude (challenger) raises ValueError
- builder/2: Which comparisons are made, and in what order?
  codex (builder): Only hi < lo on the bounds; then x < lo, then hi < x.
    why: one strict comparison, lower bound first
  claude (challenger): lo <= hi on the bounds; then x < lo, then hi < x.
    why: one inclusive comparison, the same order
  witness from claude (challenger): {LT_CALL} (result or exception): codex (builder) returns the original x; claude (challenger) raises TypeError
- challenger/0: When are the bounds rejected?
  claude (challenger): Evaluate lo <= hi first. Raise ValueError when false.
    why: NaN bounds must not pass
  codex (builder): Raise ValueError when hi < lo.
    why: strict comparisons only
  witness from codex (builder): clamp(8, float('nan'), 5) (result or exception): codex (builder) returns 5; claude (challenger) raises ValueError
- builder/interface: What interface should the contract use?
  codex (builder): {NOV19_INTERFACE}
  claude (challenger): !"{NOV19_REPLACEMENT.replace(chr(10), chr(92) + "n")}"
    why: the interface must say that comparison exceptions propagate

Predictions both seats confirmed:
- builder/0: clamp(8, float('nan'), 5) (result or exception): a) returns 5 b) raises ValueError
- builder/1: clamp(8, 1, float('nan')) (result or exception): a) returns 8 b) raises ValueError
- builder/2: {LT_CALL} (result or exception): a) returns the original x b) raises TypeError
- challenger/0: clamp(8, float('nan'), 5) (result or exception): a) returns 5 b) raises ValueError

parallax rule D-clamp-001-1 a
"""
NOV19_DECISIONS = [(term["question"], term["text"], "agreed") for term in NOV19_COMMON[1:]]

def packet_of(c):
    return next(e for e in c.events(TASK) if e["type"] == "batch.proposed")["packet"]

def reading_keys(packet, agree, owner=None):
    return [row["key"] for row in packet["sources"]
            if row["kind"] == "reading" and row["agree"] is agree and owner in (None, row["owner"])]

def nov19():
    return project(NOV19_READINGS, NOV19_REVEALS, proposes(NOV19_PROPOSAL), reviews(NOV19_REVIEW))


class Nov19(unittest.TestCase):
    def test_a_fresh_task_opens_one_card_for_five_sources_and_each_ruling_freezes_its_policy_once(self):
        for choice, note, text, absent in (("a", (), STRICT, (INCLUSIVE, "<=")), ("b", (), INCLUSIVE, (STRICT,)),
                                           ("other", ("--note", NOV19_OTHER), NOV19_OTHER, (INCLUSIVE, "<="))):
            with self.subTest(choice=choice):
                root, c, codex, claude = nov19()
                outcome = run(c, root)
                self.assertEqual(told(outcome), ("needs_ruling", f"needs a ruling on {ONE}"))
                self.assertEqual((stages(codex), stages(claude)),
                                 (["reading", "reveal", "batch_propose"], ["reading", "reveal", "batch_review"]))
                [settled] = settlements(c)
                [row] = settled["choices"]
                # One public ID for five sources.
                self.assertEqual((settled["mode"], row["id"], row["members"], row["allowed"], row["resolution"]),
                                 ("confirmed", ONE, NOV19_MEMBERS, ["a", "b", "other"], "pending"))
                # What the seats were shown: twelve agreed readings, Claude's three objections and Codex's one,
                # the interface objected to, and Claude's keyed conflict.
                packet = packet_of(c)
                self.assertEqual((len(reading_keys(packet, True)), reading_keys(packet, False, "builder"),
                                  reading_keys(packet, False, "challenger")),
                                 (12, ["builder/0", "builder/1", "builder/2"], ["challenger/0"]))
                self.assertEqual(([row["agree"] for row in packet["sources"] if row["kind"] == "interface"],
                                  packet["conflicts"]), ([False], {"builder": [], "challenger": NOV19_CONFLICT}))
                # The twelve agreements, then the two promises kept from inside disputed answers.
                self.assertEqual((settled["common"], [term["sources"] for term in settled["common"][-2:]]),
                                 (NOV19_COMMON, [["builder/0"], ["builder/2"]]))
                self.assertEqual((row["witnesses"], row["card_text"]), (NOV19_WITNESSES, NOV19_CARD))
                self.assertEqual([d["id"] for d in outcome.cards], [ONE])
                self.assertEqual(c.status(), [{"task": TASK, "status": "needs_ruling", "pending": [ONE]}])
                self.assertEqual(rule(root, ONE, choice, *note)[0], 0)
                [made] = ruled(c)
                self.assertEqual((made["dispute"], made["choice"], made["text"], made["scope"], made["members"],
                                  made["value"]),
                                 (ONE, choice, text, "project", NOV19_MEMBERS, {"interface": "", "policy": text}))
                told_, frozen, calls = to_contract(root, c)
                self.assertEqual((told_, calls), (FROZEN, []))
                # Exactly one interface, the twelve agreed terms, the two kept promises, and the selected policy
                # once. The builder's interface, which held the losing predicate, is nowhere.
                self.assertEqual(frozen, contract(NOV19_REPLACEMENT, *NOV19_DECISIONS,
                                                  (NOV19_QUESTION, text, f"ruled {ONE}")))
                self.assertEqual((frozen.count(text), frozen.count(f"  A: {UNSPECIFIED[1]} (agreed)"),
                                  frozen.count(f"  A: {ORDER[1]} (agreed)")), (1, 1, 1))
                for words in (*absent, NOV19_INTERFACE):
                    self.assertNotIn(words, frozen)
                self.assertEqual(len(ruled(c)), 1)


# ---------------------------------------------------------------------------------------------------------
# 11-17. Codex builds and validates the bounds with lo <= hi, so a NaN bound raises: its interface says so, and
# so do two of its decisions. Claude challenges with the strict lo > hi. Claude accepts every one of Codex's
# decisions and its interface. Codex objects to two of Claude's: the predicate, with three objects of a type
# that defines only `<`, and what equal bounds return, with the int and float identity. The three runs below
# use these same readings and reveals.
N17_VALIDATION = "Check lo <= hi before anything else. Raise ValueError when false."
N17_NAN_BOUND = "Raise ValueError: lo <= hi is false."
N17_STRICT = "Raise ValueError when lo > hi."
N17_IDENTITY = "x itself when x equals the bounds."
N17_EQUAL = "The result equals the bound and may be the bound object."
N17_SURVIVING = "clamplib.clamp(x, lo, hi) -> x, lo or hi"
N17_INTERFACE = N17_SURVIVING + "; checks lo <= hi first, so a NaN bound raises ValueError"
N17_BUILDER = [
    decision("What if lo == hi?", "Valid: a one-point range.", "inclusive bounds"),
    decision("What is validated first?", N17_VALIDATION, "fail early"),
    decision("What if a bound is NaN?", N17_NAN_BOUND, "follows from the validation"),
    decision("What if x is NaN?", "Return x.", "both comparisons are false"),
]
N17_CHALLENGER = [
    decision("What if lo > hi?", N17_STRICT, "one strict comparison"),
    decision("What is returned when lo == hi?", N17_EQUAL, "equality is all a caller can see"),
    decision("What if x is NaN?", "Return x.", "NaN compares false"),
]
N17_READINGS = {"builder": {"interface": N17_INTERFACE, "decisions": N17_BUILDER, "predicted_failures": []},
                "challenger": {"interface": N17_SURVIVING, "decisions": N17_CHALLENGER, "predicted_failures": []}}
N17_REVEALS = {
    "challenger": {"interface_ok": True, "interface_objection": "", "interface_replacement": "", "conflicts": [],
                   "verdicts": [agree(i) for i in range(4)]},
    "builder": {"interface_ok": True, "interface_objection": "", "interface_replacement": "", "conflicts": [],
                "verdicts": [object_(0, N17_VALIDATION, "the inclusive check also rejects NaN bounds", LT_CALL,
                                     "result or exception", "returns the original x", "raises TypeError"),
                             object_(1, N17_IDENTITY, "identity, not equality", "clamp(5, 5.0, 5.0)",
                                     "type of the result", "may be float", "is int"),
                             agree(2)]},
}
# What survives whichever predicate is chosen: the signature and return structure, and two decisions.
N17_TERMS = [
    {"slot": "interface", "question": "What interface should the contract use?", "text": N17_SURVIVING,
     "sources": ["builder/interface"]},
    {"slot": "p/0", "question": "What if lo == hi?", "text": "Valid: a one-point range.", "sources": ["builder/0"]},
    {"slot": "p/1", "question": "What if x is NaN?", "text": "Return x.", "sources": ["builder/3", "challenger/2"]},
]
N17_COMMON_LINES = [("What if lo == hi?", "Valid: a one-point range.", "agreed"),
                    ("What if x is NaN?", "Return x.", "agreed")]
N17_EQUALITY_WITNESS = {"source": "challenger/1", "scenario": "clamp(5, 5.0, 5.0)", "observation": "type of the result",
                        "a": "is int", "b": "may be float"}
N17_EQUALITY = {"slot": "c/0", "target": "policy", "question": "What is returned when x equals both bounds?",
                "members": ["challenger/1"], "a": {"interface": "", "policy": N17_IDENTITY},
                "b": {"interface": "", "policy": N17_EQUAL}, "witnesses": [N17_EQUALITY_WITNESS]}
EQUALITY_LINE = ("What is returned when x equals both bounds?", N17_IDENTITY, "both seats signed a")
N17_REVIEW = {"packet_sha": "", "proposal_sha": "", "decision": "attest", "assent": ASSENT, "votes": [],
              "fallback_complete": True, "refusal_reason": "", "affected": []}
# Both seats stand by their acceptances. Claude's strict predicate retires into the validation it accepted: the
# disputed challenger/0 is a source of that common term, beside builder/1. The accepted NaN-bound error stays.
# One choice is left, what equal bounds return, and both seats sign its a.
N17_STAND = {"packet_sha": "", "decision": "propose",
             "common": N17_TERMS + [
                 {"slot": "p/2", "question": "What is validated first?", "text": N17_VALIDATION,
                  "sources": ["builder/1", "challenger/0"]},
                 {"slot": "p/3", "question": "What if a bound is NaN?", "text": N17_NAN_BOUND, "sources": ["builder/2"]}],
             "choices": [N17_EQUALITY], "withdrawn": [], "assent": ASSENT,
             "votes": [{"slot": "c/0", "sign": ["a"], "reason": "identity is observable"}],
             "preferences": [{"slot": "c/0", "answer": "a"}],
             "fallback": {"known": True, "members": ["challenger/0", "challenger/1"],
                          "question": "Which predicate rejects the bounds, and what do equal bounds return?"},
             "refusal_reason": "", "affected": []}
N17_STAND_REVIEW = {**N17_REVIEW, "votes": [{"slot": "c/0", "sign": ["a"], "reason": "I accepted the one-point range"}]}
# The partition with everything that depends on the predicate taken out of the common terms: the validation,
# the NaN-bound error and the builder's interface, each an acceptance Claude withdraws, move into the predicate
# choice, whose columns say what each predicate means for NaN bounds. Both columns fit what stays common.
N17_A = "Check lo <= hi before anything else. Raise ValueError when false, so a NaN bound raises."
N17_B = "Raise ValueError when lo > hi. Nothing is promised for a NaN bound."
N17_WITHDRAWALS = (("builder/1", "the validation is the inclusive predicate itself"),
                   ("builder/2", "the NaN-bound error holds only under the inclusive predicate"),
                   ("builder/interface", "the interface states the inclusive check"))
N17_WITHDRAWN = [{"role": "challenger", "source": key, "destinations": ["c/1"], "reason": reason}
                 for key, reason in N17_WITHDRAWALS]
N17_LT = {"source": "challenger/0", "scenario": LT_CALL, "observation": "result or exception",
          "a": "raises TypeError", "b": "returns the original x"}
N17_PREDICATE_MEMBERS = ["challenger/0", "builder/1", "builder/2", "builder/interface"]
N17_PREDICATE = {"slot": "c/1", "target": "policy", "question": "Which predicate rejects the bounds?",
                 "members": N17_PREDICATE_MEMBERS, "a": {"interface": "", "policy": N17_A},
                 "b": {"interface": "", "policy": N17_B}, "witnesses": [N17_LT]}

def n17_votes(first, second, reasons=("identity is observable", "the predicate")):
    return [{"slot": "c/0", "sign": list(first), "reason": reasons[0]},
            {"slot": "c/1", "sign": list(second), "reason": reasons[1]}]

N17_HELD = {**N17_STAND, "common": N17_TERMS, "withdrawn": N17_WITHDRAWN, "choices": [N17_EQUALITY, N17_PREDICATE],
            "votes": n17_votes("a", "a"),
            "preferences": [{"slot": "c/0", "answer": "a"}, {"slot": "c/1", "answer": "a"}],
            "fallback": {"known": True, "members": ["challenger/0", "challenger/1", "builder/1", "builder/2",
                                                    "builder/interface"],
                         "question": "What interface, predicate and equal-bounds result should clamplib have?"}}
N17_HELD_REVIEW = {**N17_REVIEW, "votes": n17_votes("a", "b", ("identity is observable", "only < is required"))}
BATCHED = (["reading", "reveal", "batch_propose"], ["reading", "reveal", "batch_review"])

def n17(propose, review):
    root, c, codex, claude = project(N17_READINGS, N17_REVEALS, proposes(propose), reviews(review))
    try:
        outcome = c.run(root / TASK_FILE, stop_after="contract")
    except Exception as error:
        raise AssertionError(f"the run raised {error!r}") from error
    return root, c, codex, claude, outcome

def contract_v1(root):
    return (root / ".parallax/run" / TASK / "contract-v1.md").read_text(encoding="utf-8")

def precedents_of(c):
    return [e for e in c.events() if e["type"] == "ruling.made" and e["scope"] == "project"]

def source_block(card, key):
    """The lines a card shows under one source: from its `- <key>:` line up to the next source or section."""
    lines = card.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"- {key}: "))
    end = next(i for i in range(start + 1, len(lines)) if not lines[i].startswith("  "))
    return lines[start:end]


class Nov17(unittest.TestCase):
    def test_both_seats_standing_by_their_acceptances_freeze_with_no_card(self):
        root, c, codex, claude, outcome = n17(N17_STAND, N17_STAND_REVIEW)
        self.assertEqual((told(outcome), outcome.cards, (stages(codex), stages(claude))), (FROZEN, (), BATCHED))
        # The batch was reached with two objections, both Codex's, and nothing else disputed.
        packet = packet_of(c)
        self.assertEqual((reading_keys(packet, False), len(reading_keys(packet, True))),
                         (["challenger/0", "challenger/1"], 5))
        [settled] = settlements(c)
        self.assertEqual([(r["slot"], r["resolution"], r["selected"], r["id"], r["allowed"]) for r in settled["choices"]],
                         [("c/0", "mutual", "a", "", [])])
        self.assertEqual((ruled(c), precedents_of(c), [e for e in c.events(TASK) if e["type"] == "dispute.opened"]),
                         ([], [], []))
        frozen = contract_v1(root)
        self.assertEqual(frozen, contract(N17_SURVIVING, *N17_COMMON_LINES,
                                          ("What is validated first?", N17_VALIDATION, "agreed"),
                                          ("What if a bound is NaN?", N17_NAN_BOUND, "agreed"), EQUALITY_LINE))
        # One validation clause, one identity commitment, and nothing of the strict counter or the equal-bound one.
        self.assertEqual((frozen.count(N17_VALIDATION), frozen.count(N17_IDENTITY)), (1, 1))
        for words in (N17_STRICT, "lo > hi", N17_EQUAL, N17_INTERFACE):
            self.assertNotIn(words, frozen)

    def test_both_seats_signing_both_take_the_builders_preference(self):
        # The builder signs both answers of both choices and prefers b in each. The challenger signs both of the
        # first, so the preference decides it, and only a of the second, so the preference does not.
        proposal = {**N17_HELD, "votes": n17_votes("ab", "ab"),
                    "preferences": [{"slot": "c/0", "answer": "b"}, {"slot": "c/1", "answer": "b"}]}
        review = {**N17_REVIEW, "votes": n17_votes("ab", "a", ("either reads the task", "I accepted the validation"))}
        root, c, codex, claude, outcome = n17(proposal, review)
        self.assertEqual((told(outcome), outcome.cards, ruled(c)), (FROZEN, (), []))
        self.assertEqual([(r["slot"], r["resolution"], r["selected"]) for r in settlements(c)[0]["choices"]],
                         [("c/0", "tie_break", "b"), ("c/1", "mutual", "a")])
        self.assertEqual(contract_v1(root), contract(
            N17_SURVIVING, *N17_COMMON_LINES,
            ("What is returned when x equals both bounds?", N17_EQUAL,
             "both seats signed both; the builder preferred b"),
            ("Which predicate rejects the bounds?", N17_A, "both seats signed a")))

    def test_the_strict_advocate_holding_opens_one_card_and_b_leaves_no_inclusive_term(self):
        root, c, codex, claude, outcome = n17(N17_HELD, N17_HELD_REVIEW)
        self.assertEqual((told(outcome), (stages(codex), stages(claude))),
                         (("needs_ruling", f"needs a ruling on {ONE}"), BATCHED))
        # The same starting evidence as the run with no card: the same two objections.
        self.assertEqual(reading_keys(packet_of(c), False), ["challenger/0", "challenger/1"])
        [settled] = settlements(c)
        equality, predicate = settled["choices"]
        self.assertEqual((equality["resolution"], equality["selected"], equality["id"], equality["witnesses"],
                          equality["a"]["policy"]), ("mutual", "a", "", [N17_EQUALITY_WITNESS], N17_IDENTITY))
        self.assertEqual((predicate["id"], predicate["members"], predicate["witnesses"], settled["withdrawn"]),
                         (ONE, N17_PREDICATE_MEMBERS, [N17_LT], N17_WITHDRAWN))
        # The card shows each withdrawn acceptance under its own source, once, with its reason, and the
        # prediction on three objects of the type that defines only `<`.
        card = predicate["card_text"]
        for key, reason in N17_WITHDRAWALS:
            line = f"  withdrawn by claude (challenger), now in c/1: {reason}"
            self.assertEqual((source_block(card, key).count(line), card.splitlines().count(line)), (1, 1), key)
        self.assertEqual(card.splitlines().count(
            f"- challenger/0: {LT_CALL} (result or exception): a) raises TypeError b) returns the original x"), 1)
        self.assertEqual([d["id"] for d in outcome.cards], [ONE])
        self.assertEqual(rule(root, ONE, "b")[0], 0)
        [made] = ruled(c)
        self.assertEqual((made["choice"], made["text"], made["scope"]), ("b", N17_B, "project"))
        told_, frozen, calls = to_contract(root, c)
        self.assertEqual((told_, calls), (FROZEN, []))
        self.assertEqual(frozen, contract(N17_SURVIVING, *N17_COMMON_LINES, EQUALITY_LINE,
                                          ("Which predicate rejects the bounds?", N17_B, f"ruled {ONE}")))
        # No inclusive comparison and no unconditional NaN-bound error is left anywhere, in the interface or
        # the decisions; the signed NaN-bound commitment is there exactly once, and equal bounds keep x's identity.
        for words in ("<=", "Raise ValueError: lo", "a NaN bound raises", N17_EQUAL):
            self.assertNotIn(words, frozen)
        self.assertEqual((frozen.count("Nothing is promised for a NaN bound."), frozen.count(N17_IDENTITY)), (1, 1))


# ---------------------------------------------------------------------------------------------------------
# The direct path. With Task 19.1's readings (two builder decisions, one challenger decision, one interface),
# complete agreement, an interface objection alone and one reading objection alone each settle with no batch
# call. Two objections, or any conflict flag, ask the builder and then the challenger.
CLIP_OBJECTION = {"interface_ok": False, "interface_objection": "callers want the short name clip",
                  "interface_replacement": "clamp(x, lo, hi); clip = clamp"}
FLAG = [{"source": "builder/0", "target": "builder/1", "reason": "raising first changes what is returned"}]
READ_REVEAL = (["reading", "reveal"], ["reading", "reveal"])
GENERIC_REFUSAL = {"packet_sha": "", "decision": "refuse", "common": [], "choices": [], "withdrawn": [],
                   "assent": NO_ASSENT, "votes": [], "preferences": [], "fallback": UNKNOWN,
                   "refusal_reason": "the terms are entangled", "affected": []}
GENERIC_REVIEW = {"packet_sha": "", "proposal_sha": "", "decision": "refuse", "assent": NO_ASSENT, "votes": [],
                  "fallback_complete": False, "refusal_reason": "no boundary was given", "affected": []}

def public_then(c, seen, step):
    """`step`, after noting the stage, whether the call may write, and every public record the task has so far."""
    def watched(req):
        seen.append((req.stage, req.writable, [e["type"] for e in c.journal.events(TASK) if e["type"] in PUBLIC]))
        return step(req)
    return watched


class DirectPath(unittest.TestCase):
    def test_agreement_and_a_single_objection_settle_with_a_reading_and_a_reveal_from_each_seat(self):
        for name, reveals, card in (("agreement", all_agreed(), None),
                                    ("interface alone", all_agreed(**CLIP_OBJECTION), "interface"),
                                    ("one reading", one_dispute(), "reading")):
            with self.subTest(case=name):
                root, c, codex, claude = project(ROLE_READINGS, reveals)
                try:
                    outcome = c.run(root / TASK_FILE, stop_after="contract")
                except Exception as error:
                    raise AssertionError(f"the run raised {error!r}") from error
                self.assertEqual((stages(codex), stages(claude)), READ_REVEAL)
                [settled] = settlements(c)
                self.assertEqual((settled["mode"], [e["type"] for e in c.events(TASK) if e["type"] in BATCH]),
                                 ("direct", []))
                if card is None:
                    self.assertEqual((told(outcome), outcome.cards, len(freezes(c))), (FROZEN, (), 1))
                    continue
                self.assertEqual((told(outcome), [(d["id"], d["kind"], d["allowed"]) for d in outcome.cards]),
                                 (("needs_ruling", f"needs a ruling on {ONE}"), [(ONE, card, ["a", "b", "other"])]))
                # A fresh process resumes the pending card from the record alone, then freezes with no call.
                c2, codex2, claude2 = resumed(root, c)
                again = run(c2, root)
                self.assertEqual((told(again), again.cards, codex2.calls + claude2.calls),
                                 (told(outcome), outcome.cards, []))
                self.assertEqual(rule(root, ONE, "b")[0], 0)
                told_, frozen, calls = to_contract(root, c)
                self.assertEqual((told_, calls, len(freezes(c)), len(ruled(c))), (FROZEN, [], 1, 1))

    def test_two_objections_or_any_flag_ask_the_builder_then_the_challenger_before_any_card(self):
        for name, reveals in (("two readings", ROLE_REVEALS),
                              ("a reading and the interface", one_dispute(**CLIP_OBJECTION)),
                              ("one reading the builder flags", role_reveals(builder={"verdicts": [AGREE], "conflicts": FLAG})),
                              ("one reading the challenger flags", one_dispute(conflicts=FLAG)),
                              ("a flag and no objection", all_agreed(conflicts=FLAG))):
            with self.subTest(case=name):
                root, c, codex, claude = project(ROLE_READINGS, reveals)
                seen = []
                codex.script["batch_propose"] = [public_then(c, seen, proposes(GENERIC_REFUSAL))]
                claude.script["batch_review"] = [public_then(c, seen, reviews(GENERIC_REVIEW))]
                outcome = run(c, root)
                # One read-only proposal, then one read-only review, with no public record at either call.
                self.assertEqual(seen, [("batch_propose", False, []), ("batch_review", False, [])])
                self.assertEqual((stages(codex), stages(claude)), BATCHED)
                proposed = next(e for e in c.events(TASK) if e["type"] == "batch.proposed")
                self.assertEqual(shown_digests(claude.calls[-1].brief), [proposed["packet_sha"], proposed["sha"]])
                [settled] = settlements(c)
                self.assertEqual((settled["mode"], outcome.status, outcome.cards, c.status()[0]["pending"]),
                                 ("blocked", "blocked", (), []))
                # Blocked for the reason scripted: the builder refused and gave no boundary.
                self.assertEqual((settled["detail"], settled["affected"], settled["choices"]),
                                 ("the builder gave no fallback", [], []))
                self.assertEqual(outcome.detail,
                                 "the confirmed settlement is blocked: the builder gave no fallback; affected: unknown")


# ---------------------------------------------------------------------------------------------------------
# The ladder: a two-choice batch (the bound predicate and a structural alias) interrupted at every durable step,
# then ruled, frozen, contested, amended and landed, and its one project ruling read by the next task.
OLD = {"ts": "2026-11-01T00:00:00Z", "type": "ruling.made", "task": "old-001", "dispute": "D-old-001-1",
       "kind": "reading", "question": "May clamp convert its arguments?", "choice": "a", "text": "No.",
       "scope": "project", "while": "", "limitation": ""}
WHILE = "the bounds are numbers"
NOTE = "The upper bound is inclusive."
# The build the ruled contract asks for: policy a (raise when hi < lo, so a NaN bound is not rejected and
# clamp(8, float('nan'), 5) returns 5, the prediction both seats confirmed on the card) and the alias.
LADDER_OK = ("def clamp(x, lo, hi):\n    if hi < lo:\n        raise ValueError(\"lo > hi\")\n"
             "    if x < lo:\n        return lo\n    if hi < x:\n        return hi\n    return x\n\nclip = clamp\n")
# The first build: wrong above the upper bound when lo is 1, and still right on the policy's witness.
LADDER_BAD = LADDER_OK.replace("    if hi < x:\n        return hi\n", "    if hi < x:\n        return x if lo == 1 else hi\n")
# Each mutant is the whole file with one thing wrong and the alias kept, so no mutant dies on the import: no
# lower clamping, no upper clamping, and the inclusive validity check (policy b, which the witness tells apart).
LADDER_MUTANTS = {"m1": LADDER_OK.replace("    if x < lo:\n        return lo\n", ""),
                  "m2": LADDER_OK.replace("    if hi < x:\n        return hi\n", ""),
                  "m3": LADDER_OK.replace("    if hi < lo:\n", "    if not lo <= hi:\n")}
LADDER_PROBES = PROBES + ("    def test_alias(self):\n        from clamplib import clip\n        self.assertIs(clip, clamp)\n"
                          "    def test_a_nan_bound_is_not_rejected(self):\n"
                          "        self.assertEqual(clamp(8, float(\"nan\"), 5), 5)\n")
IN_PROGRESS = [{"task": TASK, "status": "in_progress", "pending": []}]
BOTH_PENDING = [{"task": TASK, "status": "needs_ruling", "pending": [ONE, TWO]}]
NEEDS_BOTH = ("needs_ruling", f"needs a ruling on {ONE}, {TWO}")
# The next task: its own interface and decisions that fit together, every one agreed.
NEXT_READINGS = {
    "builder": {"interface": "clamplib.clamp_all(values, lo, hi) -> list", "predicted_failures": [], "decisions": [
        decision("What is returned?", "A new list, each value clamped with clamp.", "one rule for one value"),
        decision("What if values is empty?", "An empty list.", "nothing to clamp")]},
    "challenger": {"interface": "clamplib.clamp_all(values, lo, hi) -> list", "predicted_failures": [], "decisions": [
        decision("Is the input mutated?", "No.", "a new list is returned")]},
}
NEXT_REVEALS = {
    "builder": {"interface_ok": True, "interface_objection": "", "interface_replacement": "", "conflicts": [],
                "verdicts": [agree(0)]},
    "challenger": {"interface_ok": True, "interface_objection": "", "interface_replacement": "", "conflicts": [],
                   "verdicts": [agree(0), agree(1)]},
}

def ladder_project():
    """A project with one old project ruling on main, and seats scripted up to the builder's proposal; the
    challenger's review is left to the caller."""
    root = make_project()
    rewrite_main(root, lambda events: events.append(dict(OLD)))
    codex = StubSeat("codex", {"reading": [answers(ROLE_READINGS["builder"])], "reveal": [answers(ALIAS_REVEALS["builder"])],
                               "batch_propose": [proposes(TWO_PENDING)]})
    claude = StubSeat("claude", {"reading": [answers(ROLE_READINGS["challenger"])],
                                 "reveal": [answers(ALIAS_REVEALS["challenger"])]})
    return root, kit_conductor(root, codex, claude), codex, claude

def status(c):
    """The task's row; main's old ruling has a row of its own."""
    return [row for row in c.status() if row["task"] == TASK]

def card_bytes(root):
    folder = root / ".parallax/run" / TASK / "cards"
    return {p.name: p.read_bytes() for p in sorted(folder.glob("*"))} if folder.exists() else {}

def contract_bytes(root, version=1):
    return (root / ".parallax/run" / TASK / f"contract-v{version}.md").read_bytes()

def killed(test, c, root, message):
    with test.assertRaises(RuntimeError) as caught:
        c.run(root / TASK_FILE)
    test.assertEqual(str(caught.exception), message)

def dies_at(c, type, torn):
    """`c`'s journal dies when it is asked to append a `type` record: before writing anything, or, with `torn`,
    after writing the record without its newline."""
    real = c.journal.append

    def append(record, task, **fields):
        if record == type:
            if torn:
                with c.journal.path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(json.dumps({"ts": "x", "type": record, "task": task, **fields}))
            raise RuntimeError(f"killed at {type}")
        return real(record, task, **fields)
    return mock.patch.object(c.journal, "append", append)

def dies_writing(c, target):
    real = Conductor._write

    def write(path, text):
        if Path(path) == target:
            raise RuntimeError(f"killed before {target.name}")
        return real(path, text)
    return mock.patch.object(c, "_write", side_effect=write)

def rule_dies(root, torn, *args):
    """The CLI's rule in a process that dies at the ruling's append: with `torn` after writing the record
    without its newline, otherwise just after the whole line is written."""
    real = Journal.append

    def append(self, record, task, **fields):
        if record != "ruling.made":
            return real(self, record, task, **fields)
        if torn:
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps({"ts": "x", "type": record, "task": task, **fields}))
        else:
            real(self, record, task, **fields)
        raise RuntimeError("killed at the ruling")
    with mock.patch.object(Journal, "append", append):
        return rule(root, *args)

def not_rulable(test, root, c):
    """Before the settlement is published no ID can be ruled, though a checkpoint, or a card file written by
    hand, is there: the CLI refuses and nothing is appended. The hand-written file is taken away again."""
    card = root / ".parallax/run" / TASK / "cards" / f"{ONE}.md"
    card.parent.mkdir(parents=True, exist_ok=True)
    card.write_text(f"Dispute {ONE} (reading)\n", encoding="utf-8", newline="\n")
    journal = c.journal.path.read_bytes()
    code, out, err = rule(root, ONE, "a")
    test.assertEqual((code, out, c.journal.path.read_bytes(), status(c)), (1, "", journal, IN_PROGRESS), err)
    card.unlink()


class Ladder(unittest.TestCase):
    def control(self):
        """The same task with no interruption: its card files and contract v1, as bytes."""
        root, c, codex, claude = ladder_project()
        claude.script["batch_review"] = [reviews(TWO_PENDING_REVIEW)]
        self.assertEqual(told(run(c, root)), NEEDS_BOTH)
        cards = card_bytes(root)
        self.assertEqual((rule(root, ONE, "a", "--while", WHILE)[0], rule(root, TWO, "b")[0]), (0, 0))
        self.assertEqual(to_contract(root, c)[0], FROZEN)
        return cards, contract_bytes(root)

    def test_every_interruption_resumes_to_the_same_contract_and_the_ruling_is_the_next_tasks_precedent(self):
        control_cards, control_contract = self.control()
        root, c, codex, claude = ladder_project()
        # 1. The builder's proposal is recorded and the challenger's process dies: nothing is public.
        claude.script["batch_review"] = [crashes]
        killed(self, c, root, "the seat process died")
        opening = c.events(TASK)[0]
        self.assertEqual((opening["type"], opening["builder"], opening["batch_protocol"]),
                         ("task.opened", "codex", "confirmed-v1"))
        self.assertEqual(([e["type"] for e in c.events(TASK) if e["type"] in BATCH], settlements(c), status(c)),
                         (["batch.proposed"], [], IN_PROGRESS))
        not_rulable(self, root, c)
        # 2. Only the review is owed. It is recorded, and the run dies before the settlement is written.
        c2, codex2, claude2 = seated(root, c, {}, {"batch_review": [reviews(TWO_PENDING_REVIEW)]})
        with dies_at(c2, "reading.settled", torn=False):
            killed(self, c2, root, "killed at reading.settled")
        self.assertEqual((stages(codex2), stages(claude2)), ([], ["batch_review"]))
        self.assertEqual(([e["type"] for e in c.events(TASK) if e["type"] in BATCH], settlements(c), status(c)),
                         (["batch.proposed", "batch.reviewed"], [], IN_PROGRESS))
        not_rulable(self, root, c)
        # 3. No call is owed from here on. The settlement is torn: still nothing is public.
        c3, codex3, claude3 = resumed(root, c)
        with dies_at(c3, "reading.settled", torn=True):
            killed(self, c3, root, "killed at reading.settled")
        self.assertFalse(c.journal.path.read_text(encoding="utf-8").endswith("\n"))
        self.assertEqual((settlements(c), status(c), card_bytes(root)), ([], IN_PROGRESS, {}))
        # 4. The settlement is written and the run dies before the first card file: the whole list is public.
        folder = root / ".parallax/run" / TASK / "cards"
        c4, codex4, claude4 = resumed(root, c)
        with dies_writing(c4, folder / f"{ONE}.md"):
            killed(self, c4, root, f"killed before {ONE}.md")
        self.assertEqual((len(settlements(c)), status(c), card_bytes(root)), (1, BOTH_PENDING, {}))
        journal = c.journal.path.read_bytes()
        # 5. It dies between the two card files.
        c5, codex5, claude5 = resumed(root, c)
        with dies_writing(c5, folder / f"{TWO}.md"):
            killed(self, c5, root, f"killed before {TWO}.md")
        self.assertEqual((status(c), list(card_bytes(root))), (BOTH_PENDING, [f"{ONE}.md"]))
        # 6. The next run writes the other card and stops for both. The two files are the settlement's own
        # card texts and the control's bytes, and the CLI prints both cards in order, then the pause.
        c6, codex6, claude6 = resumed(root, c)
        outcome = run(c6, root)
        self.assertEqual((told(outcome), [(d["id"], d["allowed"]) for d in outcome.cards]),
                         (NEEDS_BOTH, [(ONE, ["a", "b", "other"]), (TWO, ["a", "b", "other"])]))
        texts = {f"{row['id']}.md": row["card_text"] for row in settlements(c)[0]["choices"]}
        self.assertEqual((list(texts), card_bytes(root), c.journal.path.read_bytes()),
                         ([f"{ONE}.md", f"{TWO}.md"], {name: text.encode("utf-8") for name, text in texts.items()},
                          journal))
        self.assertEqual(card_bytes(root), control_cards)
        self.assertEqual(printed(cli._report, outcome),
                         (2, "".join(f"\n{text}\n" for text in texts.values())
                          + f"{TASK}: needs_ruling  needs a ruling on {ONE}, {TWO}\n"))
        for name, text in texts.items():
            self.assertIn("\nother) Supply ", text)
            self.assertTrue(text.endswith(f"\nparallax rule {name[:-3]} a\n"), text)
        self.assertEqual([seat.calls for seat in (codex3, claude3, codex4, claude4, codex5, claude5, codex6, claude6)],
                         [[]] * 8)
        # 7. A ruling torn before its newline is no ruling; the retry records it once, and only the other card
        # is pending.
        self.assertEqual(rule_dies(root, True, ONE, "a", "--while", WHILE),
                         (1, "", "parallax: killed at the ruling\n"))
        self.assertEqual((ruled(c), status(c)), ([], BOTH_PENDING))
        self.assertEqual(rule(root, ONE, "a", "--while", WHILE)[0], 0)
        self.assertEqual(([e["dispute"] for e in ruled(c)], status(c)),
                         ([ONE], [{"task": TASK, "status": "needs_ruling", "pending": [TWO]}]))
        # 8. A process that dies just after the ruling's newline has ruled: the retry is refused and appends nothing.
        self.assertEqual(rule_dies(root, False, TWO, "b"), (1, "", "parallax: killed at the ruling\n"))
        journal = c.journal.path.read_bytes()
        self.assertEqual(rule(root, TWO, "b"), (1, "", f"parallax: {TWO} is already ruled\n"))
        self.assertEqual(c.journal.path.read_bytes(), journal)
        self.assertEqual([(e["dispute"], e["choice"], e["scope"], e["while"]) for e in ruled(c)],
                         [(ONE, "a", "project", WHILE), (TWO, "b", "task", "")])
        self.assertEqual(status(c), IN_PROGRESS)
        # Contract v1 is the uninterrupted control's, byte for byte, frozen with no call. It holds the alias
        # interface that was ruled, policy a, and the old precedent.
        told_, frozen, calls = to_contract(root, c)
        self.assertEqual((told_, calls, contract_bytes(root)), (FROZEN, [], control_contract))
        self.assertEqual(interface_section(frozen), "clamp(x, lo, hi); clip = clamp")
        self.assertIn(f"- Q: {QUESTION}\n  A: {A_POLICY} (ruled {ONE})\n", frozen)
        self.assertIn(f"- P-1: {OLD['question']} -> No.\n", frozen)
        # A build that is wrong above the upper bound, contested by both seats: the ordinary upper-bound probe
        # fails. A check ruling scoped to the task, contract v2, the builder's repair, a clean crossing with
        # every mutant caught, and the landing.
        c7, codex7, claude7 = seated(
            root, c, {"build": [builds(LADDER_BAD, mutants=LADDER_MUTANTS)], "respond": [responds("contest")]},
            {"probe": [probes(LADDER_PROBES)], "respond": [responds("contest")]})
        outcome = run(c7, root)
        self.assertEqual((told(outcome), [d.kind for d in outcome.disputes]),
                         (("needs_ruling", f"needs a ruling on {THREE}"), ["check"]))
        self.assertIn("test_high", outcome.disputes[0].evidence)
        self.assertNotIn("test_a_nan_bound_is_not_rejected", outcome.disputes[0].evidence)
        self.assertEqual(rule(root, THREE, "b", "--note", NOTE, "--scope", "task")[0], 0)
        fixed = responds("concede", files={FILE: LADDER_OK}, mutants=LADDER_MUTANTS)
        c8, codex8, claude8 = seated(root, c, {"respond": [fixed]}, {})
        outcome = run(c8, root)
        self.assertEqual(told(outcome)[0], "landed", told(outcome))
        history = on_main(root)
        self.assertEqual([e["version"] for e in history if e["type"] == "contract.frozen"], [1, 2])
        self.assertEqual(len([e for e in history if e["type"] == "reading.settled"]), 1)
        crossings = [e for e in history if e["type"] == "crossing.done"]
        self.assertEqual(([e["passed"] for e in crossings], crossings[-1]["mutants"]),
                         ([False, True], {"m1": "killed", "m2": "killed", "m3": "killed"}))
        self.assertEqual(gitops.show_file(root, "main", FILE), LADDER_OK)
        [check] = [e for e in history if e["type"] == "ruling.made" and e["dispute"] == THREE]
        self.assertEqual((check["kind"], check["choice"], check["text"], check["scope"]), ("check", "b", NOTE, "task"))
        # The new project ruling is P-2, once, with its root question, text and condition; the alias ruling and
        # the check ruling are scoped to the task and are no precedent. The file is written out here by hand.
        self.assertEqual(gitops.show_file(root, "main", ".parallax/PRECEDENTS.md"),
                         "# Precedents\n\n"
                         f"- **P-1** (old-001) {OLD['question']} -> No.\n"
                         f"- **P-2** ({TASK}) {QUESTION} -> {A_POLICY} (while: {WHILE})\n")
        # The next task, with Codex building again, reads both in each seat's reading brief and freezes them
        # in its contract. Each expected line is written out by hand; the doubled period is the brief's own.
        c9, codex9, claude9 = seated(
            root, c, {"reading": [answers(NEXT_READINGS["builder"])], "reveal": [answers(NEXT_REVEALS["builder"])]},
            {"reading": [answers(NEXT_READINGS["challenger"])], "reveal": [answers(NEXT_REVEALS["challenger"])]})
        self.assertEqual(told(c9.run(root / NEXT_FILE, builder="codex", stop_after="contract")), FROZEN)
        first = c9.events(NEXT)[0]
        [settled] = [e for e in c9.events(NEXT) if e["type"] == "reading.settled"]
        self.assertEqual((first["builder"], first["batch_protocol"], settled["mode"]), ("codex", "confirmed-v1", "direct"))
        brief_rows = [f"- P-1 (from task old-001): {OLD['question']} Ruling: No..",
                      f"- P-2 (from task {TASK}): {QUESTION} Ruling: {A_POLICY}. Holds while: {WHILE}."]
        for seat in (codex9, claude9):
            [request] = [req for req in seat.calls if req.stage == "reading"]
            self.assertEqual([line for line in precedents_read(seat).splitlines() if line.startswith("- P-")], brief_rows)
            for line in brief_rows:
                self.assertEqual(request.brief.splitlines().count(line), 1)
        next_contract = (root / ".parallax/run" / NEXT / "contract-v1.md").read_text(encoding="utf-8")
        self.assertEqual(next_contract.split("## Precedents in force\n", 1)[1],
                         f"- P-1: {OLD['question']} -> No.\n- P-2: {QUESTION} -> {A_POLICY} (while: {WHILE})\n")


# ---------------------------------------------------------------------------------------------------------
# One writer. A ruling is one append under the run lock, and a second process is a second interpreter: the
# real `python -m parallax rule`, started while this process holds the lock, and again after this process ruled.
def other_process(root, *args):
    """`python -m parallax rule <args> --repo <root>` in a process of its own: (exit code, stdout, stderr)."""
    done = subprocess.run([sys.executable, "-m", "parallax", "rule", *args, "--repo", str(root)],
                          cwd=Path(parallax.__file__).resolve().parents[1], capture_output=True, text=True,
                          encoding="utf-8", timeout=120)
    return done.returncode, done.stdout, done.stderr


class OneWriter(unittest.TestCase):
    def test_a_second_process_rules_nothing_while_the_first_holds_the_lock_or_after_it_has_ruled(self):
        root, c, codex, claude = project(ROLE_READINGS, one_dispute())
        self.assertEqual(told(run(c, root)), ("needs_ruling", f"needs a ruling on {ONE}"))
        journal = c.journal.path.read_bytes()
        held = c._lock(ONE)                                   # this process is the first writer
        self.assertIsInstance(held, Path)
        try:
            self.assertEqual(other_process(root, ONE, "b"),
                             (1, "", f"parallax: cannot rule now: another parallax run is active (pid {os.getpid()})\n"))
            self.assertEqual((c.journal.path.read_bytes(), ruled(c)), (journal, []))
            c._rule(ONE, "a", "", None, "", "")               # the first writer's ruling, under its lock
        finally:
            c._unlock(held)
        [made] = ruled(c)
        journal = c.journal.path.read_bytes()
        self.assertTrue(journal.endswith(b"\n"))
        # The lock is free again, and the card is ruled: the second process's retry is refused and appends nothing.
        self.assertEqual(other_process(root, ONE, "b"), (1, "", f"parallax: {ONE} is already ruled\n"))
        self.assertEqual((c.journal.path.read_bytes(), ruled(c), made["choice"]), (journal, [made], "a"))
        self.assertFalse((root / ".parallax/run/lock").exists())


# ---------------------------------------------------------------------------------------------------------
# A settlement whose opening is gone. `status` and `rule` refuse that history, and a run must not give it a new
# opening: a marked one would make its card rulable again (Codex's review of the 19.11 plan, finding 1).
class LostOpening(unittest.TestCase):
    def test_a_run_gives_no_new_opening_to_a_settlement_that_lost_its_own(self):
        root, c, codex, claude = project(ROLE_READINGS, one_dispute())
        self.assertEqual(told(run(c, root)), ("needs_ruling", f"needs a ruling on {ONE}"))
        path = c.journal.path
        events = parse_lines(path.read_text(encoding="utf-8"))
        self.assertEqual([e["type"] for e in events].count("task.opened"), 1)
        path.write_text("".join(json.dumps(e) + "\n" for e in events if e["type"] != "task.opened"),
                        encoding="utf-8", newline="\n")
        journal, calls = path.read_bytes(), (len(codex.calls), len(claude.calls))
        detail = f"{TASK} has confirmed-v1 records and no task.opened"
        self.assertEqual([(row["status"], row["detail"]) for row in status(c)], [("blocked", detail)])
        self.assertEqual(told(run(c, root)), ("blocked", detail))           # the same task, not a later one
        self.assertEqual(rule(root, ONE, "a"), (1, "", f"parallax: {TASK}'s reading.settled has no task.opened\n"))
        self.assertEqual((path.read_bytes(), len(codex.calls), len(claude.calls)), (journal, *calls))
