import copy
import unittest
from parallax.decisions import (Dispute, Point, conflict_problem, default_scope, precedents, render_card, render_contract,
                                interface_problem, render_precedents, route, ruling_text, settle, source_keys,
                                sources, witness_problem)

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


# Task 19.1: readings and reveals keyed by role. Both readings ask "What if lo > hi?", so only the
# keys tell the two provisions apart. Some fields carry padding: rows copy reading fields verbatim and
# trim only the display witness and an objecting interface's counter and reason.
EMPTY_WITNESS = {"scenario": "", "observation": "", "theirs": "", "mine": "", "decided_by": ""}
ROLE_READINGS = {
    "builder": {"interface": "clamp(x, lo, hi)", "predicted_failures": [], "decisions": [
        {"question": "What if lo > hi?", "answer": "Raise ValueError when hi < lo. ", "why": " caller error"},
        {"question": " What is returned?", "answer": "One of the objects passed.", "why": "identity"}]},
    "challenger": {"interface": "clamp(value, lo, hi)", "predicted_failures": [], "decisions": [
        {"question": "What if lo > hi?", "answer": "Raise ValueError unless lo <= hi.", "why": "NaN bounds too"}]},
}
NAN_WITNESS = {"scenario": " clamp(8, float('nan'), 5) ", "observation": "result or exception ",
               "theirs": " returns 5", "mine": "raises ValueError\n", "decided_by": ""}
LT_WITNESS = {"scenario": "clamp(1, Lt(0), Lt(2)) with objects defining only __lt__",
              "observation": "result or exception", "theirs": "raises TypeError", "mine": "returns 1",
              "decided_by": " What is returned? "}
ROLE_REVEALS = {
    # The challenger's verdicts on the builder's two decisions, deliberately out of index order.
    "challenger": {"interface_ok": True, "interface_objection": "", "interface_replacement": "", "conflicts": [],
                   "verdicts": [{"index": 1, "agree": True, "counter": "", "why": "", "witness": EMPTY_WITNESS},
                                {"index": 0, "agree": False, "counter": " Raise ValueError unless lo <= hi. ",
                                 "why": " NaN bounds ", "witness": NAN_WITNESS}]},
    "builder": {"interface_ok": True, "interface_objection": "", "interface_replacement": "", "conflicts": [],
                "verdicts": [{"index": 0, "agree": False, "counter": "Raise ValueError when hi < lo.",
                              "why": "strict only", "witness": LT_WITNESS}]},
}
ROW_FIELDS = ["key", "kind", "owner", "question", "answer", "why", "agree", "counter", "counter_why", "witness",
              "original_witness"]
WITNESS_FIELDS = ["author", "scenario", "observation", "a", "b", "decided_by"]
ROWS = [
    {"key": "builder/0", "kind": "reading", "owner": "builder", "question": "What if lo > hi?",
     "answer": "Raise ValueError when hi < lo. ", "why": " caller error", "agree": False,
     "counter": " Raise ValueError unless lo <= hi. ", "counter_why": " NaN bounds ",
     "witness": {"author": "challenger", "scenario": "clamp(8, float('nan'), 5)", "observation": "result or exception",
                 "a": "returns 5", "b": "raises ValueError", "decided_by": ""},
     "original_witness": NAN_WITNESS},
    {"key": "builder/1", "kind": "reading", "owner": "builder", "question": " What is returned?",
     "answer": "One of the objects passed.", "why": "identity", "agree": True,
     "counter": "", "counter_why": "", "witness": {}, "original_witness": EMPTY_WITNESS},
    {"key": "challenger/0", "kind": "reading", "owner": "challenger", "question": "What if lo > hi?",
     "answer": "Raise ValueError unless lo <= hi.", "why": "NaN bounds too", "agree": False,
     "counter": "Raise ValueError when hi < lo.", "counter_why": "strict only",
     "witness": {"author": "builder", "scenario": "clamp(1, Lt(0), Lt(2)) with objects defining only __lt__",
                 "observation": "result or exception", "a": "returns 1", "b": "raises TypeError",
                 "decided_by": "What is returned?"},
     "original_witness": LT_WITNESS},
    {"key": "builder/interface", "kind": "interface", "owner": "builder",
     "question": "What interface should the contract use?", "answer": "clamp(x, lo, hi)", "why": "",
     "agree": True, "counter": "", "counter_why": "", "witness": {}, "original_witness": {}},
]

def role_reveals(builder=None, challenger=None):
    """ROLE_REVEALS with fields of either reveal replaced."""
    return {"builder": {**ROLE_REVEALS["builder"], **(builder or {})},
            "challenger": {**ROLE_REVEALS["challenger"], **(challenger or {})}}

def without(reveal, field):
    return {k: v for k, v in reveal.items() if k != field}


class Sources(unittest.TestCase):
    def raises(self, readings, reveals, message):
        with self.subTest(message=message), self.assertRaises(ValueError) as caught:
            sources(readings, reveals)
        self.assertEqual(str(caught.exception), message)

    def test_keys_are_owner_and_index_with_the_interface_last(self):
        self.assertEqual(source_keys(ROLE_READINGS), ["builder/0", "builder/1", "challenger/0", "builder/interface"])
        bare = {role: {**reading, "decisions": []} for role, reading in ROLE_READINGS.items()}
        self.assertEqual(source_keys(bare), ["builder/interface"])
        # Decimal order, not string order, and builder first whatever the dict's insertion order.
        eleven = {"challenger": {**ROLE_READINGS["challenger"], "decisions": []},
                  "builder": {**ROLE_READINGS["builder"],
                              "decisions": [{"question": f"q{i}", "answer": "a", "why": "w"} for i in range(11)]}}
        self.assertEqual(source_keys(eleven), [f"builder/{i}" for i in range(11)] + ["builder/interface"])

    def test_rows_are_keyed_ordered_oriented_and_verbatim(self):
        readings, reveals = copy.deepcopy(ROLE_READINGS), copy.deepcopy(ROLE_REVEALS)
        rows = sources(readings, reveals)
        self.assertEqual(rows, ROWS)
        self.assertEqual([list(row) for row in rows], [ROW_FIELDS] * 4)
        self.assertEqual([list(row["witness"]) for row in rows], [WITNESS_FIELDS, [], WITNESS_FIELDS, []])
        self.assertEqual((readings, reveals), (ROLE_READINGS, ROLE_REVEALS))   # inputs untouched
        self.assertIsNot(rows[0]["original_witness"], reveals["challenger"]["verdicts"][1]["witness"])

    def test_role_order_and_verdict_order_do_not_matter_and_identical_questions_keep_their_keys(self):
        reversed_readings = dict(reversed(list(ROLE_READINGS.items())))
        shuffled = role_reveals(challenger={"verdicts": list(reversed(ROLE_REVEALS["challenger"]["verdicts"]))})
        self.assertEqual(source_keys(reversed_readings), source_keys(ROLE_READINGS))
        for readings, reveals in ((reversed_readings, ROLE_REVEALS), (ROLE_READINGS, shuffled),
                                  (reversed_readings, dict(reversed(list(shuffled.items()))))):
            rows = sources(readings, reveals)
            self.assertEqual(rows, ROWS)
            self.assertEqual([r["key"] for r in rows if r["question"] == "What if lo > hi?"],
                             ["builder/0", "challenger/0"])

    def test_agreement_clears_the_display_and_a_witnessless_disagreement_keeps_its_counter(self):
        cases = [  # (verdict on builder decision 0, expected counter, counter_why, witness, original_witness)
            ({"index": 0, "agree": True, "counter": "stray", "why": "stray", "witness": NAN_WITNESS},
             "", "", {}, NAN_WITNESS),
            ({"index": 0, "agree": False, "counter": "c", "why": "w"}, "c", "w", {}, {}),
            ({"index": 0, "agree": False, "counter": "c", "why": "w",
              "witness": {**NAN_WITNESS, "scenario": " \n"}}, "c", "w", {}, {**NAN_WITNESS, "scenario": " \n"}),
        ]
        for verdict, counter, why, witness, original in cases:
            with self.subTest(verdict=verdict):
                reveals = role_reveals(challenger={"verdicts": [ROLE_REVEALS["challenger"]["verdicts"][0], verdict]})
                row = sources(ROLE_READINGS, reveals)[0]
                self.assertEqual((row["agree"], row["counter"], row["counter_why"], row["witness"],
                                  row["original_witness"]), (verdict["agree"], counter, why, witness, original))

    def test_only_the_challengers_interface_verdict_counts(self):
        objecting = role_reveals(challenger={"interface_ok": False, "interface_objection": " NaN bounds must raise ",
                                             "interface_replacement": " clamp(x, lo, hi), raising ValueError\n"})
        self.assertEqual(sources(ROLE_READINGS, objecting)[-1],
                         {**ROWS[-1], "agree": False, "counter": "clamp(x, lo, hi), raising ValueError",
                          "counter_why": "NaN bounds must raise"})
        # An accepting challenger's stray interface text is not copied, and the builder's opinion is ignored.
        stray = role_reveals(builder={"interface_ok": False, "interface_objection": "mine",
                                      "interface_replacement": "other"},
                             challenger={"interface_objection": "stray", "interface_replacement": "stray"})
        self.assertEqual(sources(ROLE_READINGS, stray)[-1], ROWS[-1])

    def test_older_reveal_shapes_are_refused_for_either_role(self):
        t18 = {role: without(reveal, "conflicts") for role, reveal in ROLE_REVEALS.items()}
        t17 = {role: without(reveal, "interface_replacement") for role, reveal in t18.items()}
        hybrid = {role: without(reveal, "interface_replacement") for role, reveal in ROLE_REVEALS.items()}
        for shape, field in ((t18, "conflicts"), (t17, "conflicts"), (hybrid, "interface_replacement")):
            for role in ("builder", "challenger"):
                other = "challenger" if role == "builder" else "builder"
                self.raises(ROLE_READINGS, {role: shape[role], other: ROLE_REVEALS[other]},
                            f"{role} reveal is not a confirmed-v1 reveal: missing {field}")
        # conflicts is checked in both reveals before interface_replacement in either.
        self.raises(ROLE_READINGS, {"builder": hybrid["builder"], "challenger": t18["challenger"]},
                    "challenger reveal is not a confirmed-v1 reveal: missing conflicts")

    def test_role_sets_are_checked_on_both_inputs(self):
        message = "readings and reveals must be keyed by builder and challenger"
        extra = {"observer": ROLE_READINGS["builder"]}
        for readings, reveals in (({"builder": ROLE_READINGS["builder"]}, ROLE_REVEALS),
                                  ({**ROLE_READINGS, **extra}, ROLE_REVEALS),
                                  (ROLE_READINGS, {"builder": ROLE_REVEALS["builder"]}),
                                  (ROLE_READINGS, {**ROLE_REVEALS, **extra}),
                                  (ROLE_READINGS, {"codex": ROLE_REVEALS["builder"], "claude": ROLE_REVEALS["challenger"]})):
            self.raises(readings, reveals, message)

    def test_every_verdict_check_has_its_message_and_order(self):
        builder_verdict = ROLE_REVEALS["builder"]["verdicts"][0]
        challenger_verdicts = ROLE_REVEALS["challenger"]["verdicts"]
        bad_index = [{**challenger_verdicts[0], "index": True}, challenger_verdicts[1]]
        cases = [
            (ROLE_READINGS, role_reveals(challenger={"verdicts": challenger_verdicts[1:]}),
             "challenger gave no verdict on builder decision 1"),
            (ROLE_READINGS, role_reveals(challenger={"verdicts": []}), "challenger gave no verdict on builder decision 0"),
            (ROLE_READINGS, role_reveals(builder={"verdicts": [builder_verdict, builder_verdict]}),
             "builder gave duplicate verdicts on challenger decision 0"),
            (ROLE_READINGS, role_reveals(builder={"verdicts": [{**builder_verdict, "index": 1}]}),
             "builder gave an invalid verdict index"),
            (ROLE_READINGS, role_reveals(builder={"verdicts": [{**builder_verdict, "index": -1}]}),
             "builder gave an invalid verdict index"),
            (ROLE_READINGS, role_reveals(challenger={"verdicts": bad_index}), "challenger gave an invalid verdict index"),
            (ROLE_READINGS, role_reveals(builder={"verdicts": [{**builder_verdict, "agree": 1}]}),
             "builder verdict agree must be a boolean"),
            (ROLE_READINGS, role_reveals(challenger={"verdicts": ["x"]}), "challenger verdict must be an object"),
            (ROLE_READINGS, role_reveals(builder={"verdicts": {}}), "decisions and verdicts must be lists"),
            ({**ROLE_READINGS, "challenger": {**ROLE_READINGS["challenger"], "decisions": {}}}, ROLE_REVEALS,
             "decisions and verdicts must be lists"),
            (ROLE_READINGS, role_reveals(challenger={"interface_ok": 1}), "interface_ok must be a boolean"),
            # Builder-owned rows are checked first, and the interface last.
            (ROLE_READINGS, role_reveals(builder={"verdicts": [{**builder_verdict, "agree": 1}]},
                                         challenger={"verdicts": bad_index}),
             "challenger gave an invalid verdict index"),
            (ROLE_READINGS, role_reveals(builder={"verdicts": [{**builder_verdict, "agree": 1}]},
                                         challenger={"interface_ok": 1}),
             "builder verdict agree must be a boolean"),
        ]
        for readings, reveals, message in cases:
            self.raises(readings, reveals, message)

    def test_settle_keeps_its_seat_named_messages(self):
        with self.assertRaises(ValueError) as caught:
            settle("clamp-001", "codex", "claude", READINGS, {**REVEALS, "claude": {**REVEALS["claude"], "verdicts": []}})
        self.assertEqual(str(caught.exception), "claude gave no verdict on codex decision 0")


def conflict(source, target, reason="r"):
    return {"source": source, "target": target, "reason": reason}


class Conflicts(unittest.TestCase):
    keys = ["builder/0", "builder/1", "challenger/0", "builder/interface"]

    def check(self, *conflicts):
        return conflict_problem({**ROLE_REVEALS["challenger"], "conflicts": list(conflicts)}, self.keys)

    def test_known_distinct_pairs_with_reasons_pass_in_either_direction(self):
        self.assertIsNone(self.check())
        self.assertIsNone(self.check(conflict("challenger/0", "builder/1"), conflict("builder/1", "challenger/0"),
                                     conflict("builder/0", "builder/interface"),
                                     conflict("builder/interface", "challenger/0")))

    def test_every_problem_is_reported_in_entry_order(self):
        self.assertEqual(
            self.check(conflict("challenger/9", "builder/0"), conflict("builder/0", "builder/7"),
                       conflict("builder/1", "builder/1"), conflict("challenger/0", "builder/1", reason=" \n"),
                       conflict("challenger/0", "builder/1"), conflict("", ""), conflict("Builder/0", "builder/1")),
            "conflict 0: unknown source challenger/9\n"
            "conflict 1: unknown target builder/7\n"
            "conflict 2: source and target are both builder/1\n"
            "conflict 3: reason must say why the two cannot both stand\n"
            "conflict 4: repeats conflict 3 (challenger/0 -> builder/1)\n"
            "conflict 5: unknown source (blank)\n"
            "conflict 5: unknown target (blank)\n"
            "conflict 6: unknown source Builder/0")

    def test_duplicate_reports_first_entry_and_keys_are_literal(self):
        self.assertEqual(
            self.check(conflict("builder/0", "challenger/0"),
                       conflict("builder/0", "challenger/0"),
                       conflict("builder/0", "challenger/0", " "),
                       conflict(" builder/0", "challenger/0 ")),
            "conflict 1: repeats conflict 0 (builder/0 -> challenger/0)\n"
            "conflict 2: reason must say why the two cannot both stand\n"
            "conflict 2: repeats conflict 0 (builder/0 -> challenger/0)\n"
            "conflict 3: unknown source  builder/0\n"
            "conflict 3: unknown target challenger/0 ")


def route_rows(reading_disputes, interface_objection, agreed):
    rows = [{"kind": "reading", "agree": True}] * agreed + [{"kind": "reading", "agree": False}] * reading_disputes
    return rows + [{"kind": "interface", "agree": not interface_objection}]

def flags(builder=(), challenger=()):
    return {"builder": {"conflicts": list(builder)}, "challenger": {"conflicts": list(challenger)}}


class Route(unittest.TestCase):
    def test_the_trigger_truth_table(self):
        flag = [conflict("challenger/0", "builder/1")]
        cases = [  # (reading disputes, interface objection, builder flags, challenger flags, route)
            (0, False, [], [], "direct"),
            (0, True, [], [], "direct"),
            (1, False, [], [], "direct"),
            (2, False, [], [], "batch"),
            (1, True, [], [], "batch"),
            (3, True, [], [], "batch"),
            (0, False, flag, [], "batch"),
            (0, False, [], flag, "batch"),
            (0, False, flag, flag, "batch"),
            (0, True, flag, [], "batch"),
            (1, False, flag, [], "batch"),
            (1, False, [], flag, "batch"),
        ]
        for disputes, objection, builder, challenger, expected in cases:
            for agreed in (0, 12):
                with self.subTest(disputes=disputes, objection=objection, builder=bool(builder),
                                  challenger=bool(challenger), agreed=agreed):
                    self.assertEqual(route(route_rows(disputes, objection, agreed), flags(builder, challenger)),
                                     expected)

    def test_route_reads_the_rows_sources_builds(self):
        self.assertEqual(route(sources(ROLE_READINGS, ROLE_REVEALS), ROLE_REVEALS), "batch")   # two reading disputes
        agree = {"index": 0, "agree": True, "counter": "", "why": "", "witness": EMPTY_WITNESS}
        one = role_reveals(builder={"verdicts": [agree]})
        unflagged = sources(ROLE_READINGS, one)
        self.assertEqual(route(unflagged, one), "direct")
        # The builder's own interface verdict is not an objection.
        both = role_reveals(builder={**one["builder"], "interface_ok": False, "interface_objection": "x"})
        self.assertEqual(route(sources(ROLE_READINGS, both), both), "direct")
        # A validated flag from either seat, or both, turns the same rows into a batch. The source is an
        # accepted provision and the target a disputed one.
        flag = [conflict("builder/1", "builder/0")]
        keys = source_keys(ROLE_READINGS)
        for builder, challenger in ((flag, []), ([], flag), (flag, flag)):
            with self.subTest(builder=bool(builder), challenger=bool(challenger)):
                flagged = role_reveals(builder={**one["builder"], "conflicts": builder},
                                       challenger={"conflicts": challenger})
                for role in ("builder", "challenger"):
                    self.assertIsNone(conflict_problem(flagged[role], keys))
                rows = sources(ROLE_READINGS, flagged)
                self.assertEqual(rows, unflagged)
                self.assertEqual(route(rows, flagged), "batch")
