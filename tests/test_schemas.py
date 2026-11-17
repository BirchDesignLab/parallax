import unittest
from parallax.schemas import BUILD, READING, RESPOND, validate

GOOD = {"interface": "f(x)", "decisions": [{"question": "q", "answer": "a", "why": "w"}], "predicted_failures": []}

class Validate(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(validate(GOOD, READING), [])
        self.assertEqual(validate({"summary": "s", "blocked": "", "mutants": [{"id": "m1", "description": "d", "files": ["a.py"]}]}, BUILD), [])

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

    def test_booleans_are_not_integers(self):
        self.assertTrue(validate({"index": True}, {"type": "object", "properties": {"index": {"type": "integer"}}, "required": ["index"], "additionalProperties": False}))
