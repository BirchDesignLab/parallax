import unittest
from parallax.decisions import (Dispute, Point, default_scope, precedents, render_card, render_contract,
                                render_precedents, ruling_text, settle)

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
    def test_agreements_become_points_and_disagreements_become_disputes(self):
        interface, points, disputes = settle("clamp-001", "codex", "claude", READINGS, REVEALS)
        self.assertEqual(interface, "clamplib.clamp(x, lo, hi)")
        self.assertEqual(points, [Point("NaN input?", "return NaN", "agreed")])
        self.assertEqual(disputes, [
            Dispute("D-clamp-001-1", "reading", "What if lo > hi?", "raise ValueError", "swap the bounds",
                    "codex (builder)", "claude (challenger)"),
            Dispute("D-clamp-001-2", "reading", "Strings?", "compare as given", "raise TypeError",
                    "codex (builder)", "claude (challenger)"),
        ])

    def test_interface_objection_is_numbered_last_and_start_is_honored(self):
        reveals = {**REVEALS, "claude": {**REVEALS["claude"], "interface_ok": False, "interface_objection": "name them lo and hi"}}
        _, _, disputes = settle("clamp-001", "codex", "claude", READINGS, reveals, start=5)
        self.assertEqual([d.id for d in disputes], ["D-clamp-001-5", "D-clamp-001-6", "D-clamp-001-7"])
        self.assertEqual((disputes[-1].kind, disputes[-1].a, disputes[-1].b),
                         ("interface", "clamplib.clamp(x, lo, hi)", "name them lo and hi"))

    def test_missing_verdict_is_an_error(self):
        reveals = {**REVEALS, "codex": {**REVEALS["codex"], "verdicts": REVEALS["codex"]["verdicts"][:1]}}
        with self.assertRaisesRegex(ValueError, "codex gave no verdict on claude decision 1"):
            settle("clamp-001", "codex", "claude", READINGS, reveals)

class Rulings(unittest.TestCase):
    d = Dispute("D-t-1", "reading", "q", "A", "B", "codex (builder)", "claude (challenger)")

    def test_ruling_text(self):
        self.assertEqual((ruling_text(self.d, "a", ""), ruling_text(self.d, "b", "x"), ruling_text(self.d, "other", "C")), ("A", "B", "C"))
        check = Dispute("D-t-2", "check", "q", "A", "B", "x", "y")
        for dispute, choice, note in ((self.d, "other", ""), (self.d, "c", ""), (check, "other", "note")):
            with self.assertRaises(ValueError):
                ruling_text(dispute, choice, note)

    def test_scope_defaults(self):
        self.assertEqual([default_scope(k) for k in ("reading", "interface", "check", "mutant", "unresolved")],
                         ["project", "project", "project", "task", "task"])

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
