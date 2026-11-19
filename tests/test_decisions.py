import unittest
from parallax.decisions import (Dispute, Point, default_scope, precedents, render_card, render_contract,
                                interface_problem, render_precedents, ruling_text, settle, witness_problem)

READINGS = {
    "codex": {"interface": "clamplib.clamp(x, lo, hi)", "predicted_failures": [],
              "decisions": [{"question": "What if lo > hi?", "answer": "raise ValueError", "why": "caller error"}]},
    "claude": {"interface": "clamplib.clamp(value, low, high)", "predicted_failures": [],
               "decisions": [{"question": "NaN input?", "answer": "return NaN", "why": "ieee"},
                             {"question": "Strings?", "answer": "raise TypeError", "why": "numbers only"}]},
}
REVEALS = {
    "claude": {"interface_ok": True, "interface_objection": "",
               "verdicts": [{"index": 0, "agree": False, "counter": "swap the bounds", "why": "forgiving"}]},
    "codex": {"interface_ok": True, "interface_objection": "",
              "verdicts": [{"index": 0, "agree": True, "counter": "", "why": ""},
                           {"index": 1, "agree": False, "counter": "compare as given", "why": "duck typing"}]},
}

class Settle(unittest.TestCase):
    def test_a_whole_objection_offers_the_replacement_and_says_why(self):
        reveals = {**REVEALS, "claude": {**REVEALS["claude"], "interface_ok": False,
                                         "interface_objection": " name them lo and hi ",
                                         "interface_replacement": "clamplib.clamp(x, lo, hi) -> number\n"}}
        d = settle("clamp-001", "codex", "claude", READINGS, reveals)[2][-1]
        self.assertEqual((d.kind, d.a, d.b), ("interface", "clamplib.clamp(x, lo, hi)", "clamplib.clamp(x, lo, hi) -> number"))
        self.assertEqual(d.evidence, "Why claude objects: name them lo and hi\n"
                                     "b and other replace the whole interface; for other, give the complete interface with --note.")

    def test_an_objection_without_a_replacement_key_stays_a_delta(self):
        reveals = {**REVEALS, "claude": {**REVEALS["claude"], "interface_ok": False, "interface_objection": "name them lo and hi"}}
        d = settle("clamp-001", "codex", "claude", READINGS, reveals)[2][-1]
        self.assertEqual((d.b, d.evidence), ("name them lo and hi", ""))

    def test_agreements_become_points_and_disagreements_become_disputes(self):
        interface, points, disputes = settle("clamp-001", "codex", "claude", READINGS, REVEALS)
        self.assertEqual(interface, "clamplib.clamp(x, lo, hi)")
        self.assertEqual(points, [Point("NaN input?", "return NaN", "agreed")])
        self.assertEqual(disputes, [
            Dispute("D-clamp-001-1", "reading", "What if lo > hi?", "raise ValueError", "swap the bounds",
                    "codex (builder)", "claude (challenger)",
                    "Reasons:\n  a) codex: caller error\n  b) claude: forgiving"),
            Dispute("D-clamp-001-2", "reading", "Strings?", "compare as given", "raise TypeError",
                    "codex (builder)", "claude (challenger)",
                    "Reasons:\n  a) codex: duck typing\n  b) claude: numbers only"),
        ])

    def test_interface_objection_is_numbered_last_and_start_is_honored(self):
        reveals = {**REVEALS, "claude": {**REVEALS["claude"], "interface_ok": False, "interface_objection": "name them lo and hi"}}
        _, _, disputes = settle("clamp-001", "codex", "claude", READINGS, reveals, start=5)
        self.assertEqual([d.id for d in disputes], ["D-clamp-001-5", "D-clamp-001-6", "D-clamp-001-7"])
        self.assertEqual((disputes[-1].kind, disputes[-1].a, disputes[-1].b),
                         ("interface", "clamplib.clamp(x, lo, hi)", "name them lo and hi"))
        self.assertEqual(disputes[-1].evidence, "")

    def test_missing_verdict_is_an_error(self):
        reveals = {**REVEALS, "codex": {**REVEALS["codex"], "verdicts": REVEALS["codex"]["verdicts"][:1]}}
        with self.assertRaisesRegex(ValueError, "codex gave no verdict on claude decision 1"):
            settle("clamp-001", "codex", "claude", READINGS, reveals)

class Interface(unittest.TestCase):
    def r(self, ok=False, objection="names differ", replacement="clamplib.clamp(value, low, high)"):
        return {"interface_ok": ok, "interface_objection": objection, "interface_replacement": replacement, "verdicts": []}

    def test_an_accepted_interface_is_not_checked_even_with_populated_fields(self):
        self.assertIsNone(interface_problem(self.r(ok=True, objection="", replacement=""), "i"))
        self.assertIsNone(interface_problem(self.r(ok=True), "i"))
        self.assertIsNone(interface_problem(self.r(ok=True, objection="", replacement="i"), "i"))

    def test_an_objection_needs_a_reason_and_a_different_complete_interface(self):
        self.assertEqual(interface_problem(self.r(objection=" "), "i"),
                         "interface_objection must say why you object when interface_ok is false")
        for blank in ("", " \n\t "):
            with self.subTest(replacement=blank):
                self.assertEqual(interface_problem(self.r(replacement=blank), "i"),
                                 "interface_replacement must hold the complete interface you want when interface_ok is false")
        self.assertEqual(interface_problem(self.r(replacement=" clamplib.clamp(x, lo, hi)\n"), "clamplib.clamp(x, lo, hi)"),
                         "interface_replacement is the same as the builder's interface; give the interface you want, "
                         "or set interface_ok to true")
        self.assertIsNone(interface_problem(self.r(), "clamplib.clamp(x, lo, hi)"))


class Rulings(unittest.TestCase):
    d = Dispute("D-t-1", "reading", "q", "A", "B", "codex (builder)", "claude (challenger)")

    def test_ruling_text(self):
        self.assertEqual((ruling_text(self.d, "a", ""), ruling_text(self.d, "b", "x"), ruling_text(self.d, "other", "C")), ("A", "B", "C"))
        check = Dispute("D-t-2", "check", "q", "A", "B", "x", "y")
        for dispute, choice, note in ((self.d, "other", ""), (self.d, "c", ""), (check, "other", "note")):
            with self.assertRaises(ValueError):
                ruling_text(dispute, choice, note)

    def test_scope_defaults(self):
        kinds = ("reading", "interface", "check", "mutant", "unresolved")
        self.assertEqual([default_scope(k) for k in kinds], ["project", "project", "project", "task", "task"])
        self.assertEqual([default_scope(k, whole_interface=True) for k in kinds],
                         ["project", "task", "project", "task", "task"])

    def test_precedents_are_project_rulings_in_order(self):
        events = [{"type": "ruling.made", "task": "t1", "dispute": "D-t1-1", "kind": "reading", "question": "q1", "choice": "a", "text": "r1", "scope": "project", "while": "", "limitation": ""},
                  {"type": "ruling.made", "task": "t1", "dispute": "D-t1-2", "kind": "mutant", "question": "q2", "choice": "b", "text": "r2", "scope": "task", "while": "", "limitation": "m2 waived"},
                  {"type": "crossing.done", "task": "t1"},
                  {"type": "ruling.made", "task": "t2", "dispute": "D-t2-1", "kind": "check", "question": "q3", "choice": "b", "text": "r3", "scope": "project", "while": "single user", "limitation": ""}]
        self.assertEqual(precedents(events), [
            {"id": "P-1", "question": "q1", "ruling": "r1", "while": "", "task": "t1"},
            {"id": "P-2", "question": "q3", "ruling": "r3", "while": "single user", "task": "t2"}])

class Rendering(unittest.TestCase):
    P = [{"id": "P-1", "question": "q1", "ruling": "r1", "while": "", "task": "t0"},
         {"id": "P-2", "question": "q3", "ruling": "r3", "while": "single user", "task": "t2"}]

    def test_contract(self):
        text = render_contract("clamp-001", 2, "Add clamp.", "clamplib.clamp(x, lo, hi)",
                               [Point("What if lo > hi?", "raise ValueError", "ruled D-clamp-001-1")], self.P)
        self.assertTrue(text.startswith("# Contract: clamp-001 (v2)\n"))
        for part in ("## Task\nAdd clamp.\n", "## Interface\nclamplib.clamp(x, lo, hi)\n",
                     "## Decisions\n- Q: What if lo > hi?\n  A: raise ValueError (ruled D-clamp-001-1)\n",
                     "## Precedents in force\n- P-1: q1 -> r1\n- P-2: q3 -> r3 (while: single user)\n"):
            self.assertIn(part, text)

    def test_empty_sections_say_none(self):
        text = render_contract("t", 1, "x", "i", [], [])
        self.assertIn("## Decisions\nnone\n", text)
        self.assertIn("## Precedents in force\nnone\n", text)

    def test_precedents_file(self):
        self.assertEqual(render_precedents(self.P),
                         "# Precedents\n\n- **P-1** (t0) q1 -> r1\n- **P-2** (t2) q3 -> r3 (while: single user)\n")
        self.assertEqual(render_precedents([]), "# Precedents\n\nnone yet\n")

    def test_card(self):
        card = render_card(Dispute("D-clamp-001-1", "reading", "What if lo > hi?", "raise ValueError", "swap the bounds",
                                   "codex (builder)", "claude (challenger)", evidence="FAIL: x"))
        for part in ("Dispute D-clamp-001-1 (reading)", "What if lo > hi?", "a) codex (builder): raise ValueError",
                     "b) claude (challenger): swap the bounds", "FAIL: x", "parallax rule D-clamp-001-1 a"):
            self.assertIn(part, card)

    def test_dispute_round_trips_through_an_event(self):
        d = Dispute("D-t-1", "check", "q", "A", "B", "x", "y", "ev")
        self.assertEqual(Dispute.from_event({"type": "dispute.opened", "task": "t", "ts": "now", **d.to_fields()}), d)

    def test_paths_are_scrubbed_not_rejected(self):
        # Added in review: rendering must never fail on a URL, a route, or check output full of paths.
        contract = render_contract("t-1", 1, r"Add GET /users (see https://x.io/a)", "f() -> int", [], [])
        self.assertIn("Add GET /users (see https://x.io/a)", contract)
        evidence = r'File "C:\Users\First Last\.parallax\k\t\cross\tests\test_a.py", line 3'
        card = render_card(Dispute("D-t-1", "check", "q", "A", "B", "x", "y", evidence))
        self.assertIn("<outside>/test_a.py", card)
        self.assertNotIn("First Last", card)


W = {"scenario": "clamp(5, 10, 1)", "observation": "result", "theirs": "raises ValueError", "mine": "returns 5", "decided_by": ""}
EMPTY = {"scenario": "", "observation": "", "theirs": "", "mine": "", "decided_by": ""}

def reveal_of(*verdicts):
    return {"interface_ok": True, "interface_objection": "", "verdicts": list(verdicts)}

class Witness(unittest.TestCase):
    def v(self, agree=False, **witness):
        return {"index": 2, "agree": agree, "counter": "c", "why": "", "witness": {**W, **witness}}

    def test_agreeing_verdicts_are_not_checked_whatever_the_witness_holds(self):
        self.assertIsNone(witness_problem({"index": 0, "agree": True, "counter": "", "why": ""}))
        self.assertIsNone(witness_problem(self.v(agree=True, theirs="same", mine="same")))

    def test_a_disagreement_needs_every_field(self):
        self.assertEqual(witness_problem(self.v(scenario=" ", mine="")),
                         "verdict 2: a disagreement needs a witness with scenario, observation, theirs and mine; missing scenario, mine")
        no_witness = {"index": 1, "agree": False, "counter": "c", "why": ""}
        self.assertEqual(witness_problem(no_witness),
                         "verdict 1: a disagreement needs a witness with scenario, observation, theirs and mine; "
                         "missing scenario, observation, theirs, mine")

    def test_identical_results_are_rejected(self):
        self.assertEqual(witness_problem(self.v(theirs="returns 5 ", mine=" returns 5")),
                         "verdict 2: the witness predicts the same result under both answers (returns 5); "
                         "give a scenario where the two answers commit to different results, "
                         "or agree if you accept their whole answer")

    def test_results_that_differ_only_in_case_or_spelling_are_accepted(self):
        for theirs, mine in (("returns undefined", "returns null"), ('prints "ok"', 'prints "OK"')):
            self.assertIsNone(witness_problem(self.v(theirs=theirs, mine=mine)))

    def test_a_cited_contradiction_reaches_the_card_in_either_role_assignment(self):
        # The D-2 shape: codex's identity rule is accepted, claude's lo == hi answer contradicts it,
        # and codex disputes that answer citing the identity rule's question verbatim.
        identity = {"question": "What happens when x equals a bound?",
                    "answer": "Return x itself, preserving its type.", "why": "identity matters"}
        equal = {"question": "What happens when lo equals hi?", "answer": "Return lo for any x.", "why": "simpler to state"}
        counter = "Return x when it compares equal to both bounds."
        readings = {"codex": {"interface": "i", "predicted_failures": [], "decisions": [identity]},
                    "claude": {"interface": "i", "predicted_failures": [], "decisions": [equal]}}
        reveals = {"claude": reveal_of({"index": 0, "agree": True, "counter": "", "why": "", "witness": EMPTY}),
                   "codex": reveal_of({"index": 0, "agree": False, "counter": counter,
                                       "why": "it contradicts the accepted identity rule",
                                       "witness": {"scenario": "clamp(5, 5.0, 5.0)", "observation": "the returned value and its type",
                                                   "theirs": "5.0 (float)", "mine": "5 (int)",
                                                   "decided_by": identity["question"]}})}
        expected = {
            "codex": ((counter, equal["answer"]),
                      "  Under a (codex), codex predicts: 5 (int)\n  Under b (claude), codex predicts: 5.0 (float)\n",
                      "  a) codex: it contradicts the accepted identity rule\n  b) claude: simpler to state"),
            "claude": ((equal["answer"], counter),
                       "  Under a (claude), codex predicts: 5.0 (float)\n  Under b (codex), codex predicts: 5 (int)\n",
                       "  a) claude: simpler to state\n  b) codex: it contradicts the accepted identity rule"),
        }
        for builder, challenger in (("codex", "claude"), ("claude", "codex")):
            with self.subTest(builder=builder):
                _, points, disputes = settle("t-1", builder, challenger, readings, reveals)
                self.assertEqual(points, [Point(identity["question"], identity["answer"], "agreed")])
                [d] = [d for d in disputes if d.question == equal["question"]]
                answers, predictions, reasons = expected[builder]
                self.assertEqual((d.a, d.b), answers)
                self.assertEqual(d.evidence,
                                 "Witness, written by codex:\n  Scenario: clamp(5, 5.0, 5.0)\n"
                                 "  Observe: the returned value and its type\n" + predictions +
                                 "  codex cites: What happens when x equals a bound?\nReasons:\n" + reasons)

    def test_no_commitment_follows_the_owner_in_either_role_assignment(self):
        silent = {"question": "What happens with NaN as lo or hi?", "answer": "Unspecified; probes will not test it.",
                  "why": "out of scope for this task"}
        requirement = "Raise ValueError, because lo <= hi is false."
        readings = {"codex": {"interface": "i", "predicted_failures": [], "decisions": []},
                    "claude": {"interface": "i", "predicted_failures": [], "decisions": [silent]}}
        reveals = {"claude": reveal_of(),
                   "codex": reveal_of({"index": 0, "agree": False, "counter": requirement, "why": "the bound check must hold",
                                       "witness": {"scenario": "clamp(0.5, float('nan'), 1.0)",
                                                   "observation": "what the call returns or raises",
                                                   "theirs": "no commitment", "mine": "raises ValueError", "decided_by": ""}})}
        for builder, challenger, a_line, b_line in (
                ("codex", "claude", "Under a (codex), codex predicts: raises ValueError",
                 "Under b (claude), codex predicts: no commitment"),
                ("claude", "codex", "Under a (claude), codex predicts: no commitment",
                 "Under b (codex), codex predicts: raises ValueError")):
            with self.subTest(builder=builder):
                [d] = settle("t-1", builder, challenger, readings, reveals)[2]
                self.assertEqual((d.a, d.b), (requirement, silent["answer"]) if builder == "codex" else (silent["answer"], requirement))
                self.assertIn("Witness, written by codex:", d.evidence)
                self.assertIn(a_line, d.evidence)
                self.assertIn(b_line, d.evidence)
                self.assertNotIn("cites:", d.evidence)
                self.assertIn("claude: out of scope for this task", d.evidence)
                self.assertIn("codex: the bound check must hold", d.evidence)

    def test_an_empty_reason_reads_none_given(self):
        readings = {"codex": {"interface": "i", "predicted_failures": [],
                              "decisions": [{"question": "q", "answer": "x", "why": ""}]},
                    "claude": {"interface": "i", "predicted_failures": [], "decisions": []}}
        reveals = {"codex": reveal_of(), "claude": reveal_of({"index": 0, "agree": False, "counter": "y", "why": "", "witness": W})}
        [d] = settle("t-1", "codex", "claude", readings, reveals)[2]
        self.assertTrue(d.evidence.endswith("Reasons:\n  a) codex: (none given)\n  b) claude: (none given)"))
