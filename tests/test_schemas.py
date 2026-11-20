import unittest
from parallax.schemas import BUILD, READING, RESPOND, REVEAL, REVEAL_AMENDING, REVEAL_CONFIRMED, WITNESS, validate

GOOD = {"interface": "f(x)", "decisions": [{"question": "q", "answer": "a", "why": "w"}], "predicted_failures": []}

class Validate(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(validate(GOOD, READING), [])
        self.assertEqual(validate({"summary": "s", "blocked": "", "mutants": [{"id": "m1", "description": "d", "files": ["a.py"]}],
                                  "files": [{"path": "a.py", "change": "add", "purpose": "p"}]}, BUILD), [])

    def test_problems_name_their_location(self):
        cases = [({**GOOD, "decisions": [{"question": "q", "answer": "a"}]}, "$.decisions[0]", "why"),
                 ({k: v for k, v in GOOD.items() if k != "interface"}, "$", "interface"),
                 ({**GOOD, "extra": 1}, "$", "extra"),
                 ({**GOOD, "predicted_failures": [3]}, "$.predicted_failures[0]", "string"),
                 ("nope", "$", "object")]
        for value, where, what in cases:
            problems = validate(value, READING)
            self.assertTrue(any(where in p and what in p for p in problems), (value, problems))

    def test_enum(self):
        bad = {"answers": [{"dispute": "D-1", "stance": "maybe", "cite": "", "why": ""}], "blocked": "", "mutants": []}
        self.assertTrue(any("stance" in p for p in validate(bad, RESPOND)))

    def test_build_needs_files_and_a_known_change(self):
        build = {"summary": "s", "blocked": "", "mutants": [], "files": []}
        self.assertEqual(validate(build, BUILD), [])
        self.assertTrue(any("files" in p for p in validate({k: v for k, v in build.items() if k != "files"}, BUILD)))
        renamed = {**build, "files": [{"path": "a.py", "change": "rename", "purpose": "p"}]}
        self.assertTrue(any("change" in p for p in validate(renamed, BUILD)))

    def test_booleans_are_not_integers(self):
        self.assertTrue(validate({"index": True}, {"type": "object", "properties": {"index": {"type": "integer"}}, "required": ["index"], "additionalProperties": False}))

    def test_reveal_verdicts_need_every_witness_field_as_a_string(self):
        empty = {"scenario": "", "observation": "", "theirs": "", "mine": "", "decided_by": ""}
        def reveal_with(witness):
            return {"interface_ok": True, "interface_objection": "", "interface_replacement": "",
                    "verdicts": [{"index": 0, "agree": True, "counter": "", "why": "", "witness": witness}]}
        self.assertEqual(validate(reveal_with(empty), REVEAL), [])
        for field in WITNESS["required"]:
            with self.subTest(missing=field):
                problems = validate(reveal_with({k: v for k, v in empty.items() if k != field}), REVEAL)
                self.assertTrue(any(field in p and "witness" in p for p in problems), problems)
        problems = validate(reveal_with({**empty, "mine": 5}), REVEAL)
        self.assertTrue(any("mine" in p and "string" in p for p in problems), problems)
        bare = {"interface_ok": True, "interface_objection": "", "interface_replacement": "",
                "verdicts": [{"index": 0, "agree": True, "counter": "", "why": ""}]}
        self.assertEqual(validate(bare, REVEAL), ["$.verdicts[0]: missing 'witness'"])

    def test_reveal_needs_a_string_replacement_and_the_prior_shape_has_none(self):
        empty = {"scenario": "", "observation": "", "theirs": "", "mine": "", "decided_by": ""}
        current = {"interface_ok": True, "interface_objection": "", "interface_replacement": "",
                   "verdicts": [{"index": 0, "agree": True, "counter": "", "why": "", "witness": empty}]}
        prior = {k: v for k, v in current.items() if k != "interface_replacement"}
        self.assertEqual(validate(current, REVEAL), [])
        self.assertTrue(any("interface_replacement" in p for p in validate(prior, REVEAL)))
        problems = validate({**current, "interface_replacement": 5}, REVEAL)
        self.assertTrue(any("interface_replacement" in p and "string" in p for p in problems), problems)
        self.assertEqual(validate(prior, REVEAL_AMENDING), [])
        self.assertIn("$: unexpected property 'interface_replacement'", validate(current, REVEAL_AMENDING))

    def test_the_confirmed_reveal_adds_a_conflicts_list_and_the_others_are_unchanged(self):
        empty = {"scenario": "", "observation": "", "theirs": "", "mine": "", "decided_by": ""}
        current = {"interface_ok": True, "interface_objection": "", "interface_replacement": "",
                   "verdicts": [{"index": 0, "agree": True, "counter": "", "why": "", "witness": empty}]}
        good = {"source": "challenger/0", "target": "builder/0", "reason": "r"}
        flagged = {**current, "conflicts": [good]}
        self.assertEqual(validate(flagged, REVEAL_CONFIRMED), [])
        self.assertEqual(validate({**current, "conflicts": []}, REVEAL_CONFIRMED), [])
        self.assertEqual(validate(current, REVEAL_CONFIRMED), ["$: missing 'conflicts'"])
        for field in ("source", "target", "reason"):
            with self.subTest(field=field):
                missing = {k: v for k, v in good.items() if k != field}
                self.assertEqual(validate({**current, "conflicts": [missing]}, REVEAL_CONFIRMED),
                                 [f"$.conflicts[0]: missing '{field}'"])
                self.assertEqual(validate({**current, "conflicts": [{**good, field: 5}]}, REVEAL_CONFIRMED),
                                 [f"$.conflicts[0].{field}: expected string"])
        self.assertEqual(validate({**current, "conflicts": [{**good, "x": 1}]}, REVEAL_CONFIRMED),
                         ["$.conflicts[0]: unexpected property 'x'"])
        self.assertEqual(validate({**current, "conflicts": {}}, REVEAL_CONFIRMED), ["$.conflicts: expected array"])
        self.assertEqual(validate({**current, "conflicts": ["x"]}, REVEAL_CONFIRMED), ["$.conflicts[0]: expected object"])
        self.assertIn("$: unexpected property 'conflicts'", validate(flagged, REVEAL))
        # The confirmed shape is REVEAL plus one closed, required field.
        self.assertEqual(list(REVEAL_CONFIRMED["properties"]),
                         ["interface_ok", "interface_objection", "interface_replacement", "verdicts", "conflicts"])
        self.assertEqual(REVEAL_CONFIRMED["required"], list(REVEAL_CONFIRMED["properties"]))
        self.assertIs(REVEAL_CONFIRMED["additionalProperties"], False)
        for name, schema in REVEAL["properties"].items():
            self.assertEqual(REVEAL_CONFIRMED["properties"][name], schema, name)
        self.assertEqual(list(REVEAL["properties"]),
                         ["interface_ok", "interface_objection", "interface_replacement", "verdicts"])
        self.assertEqual(list(REVEAL_AMENDING["properties"]), ["interface_ok", "interface_objection", "verdicts"])
