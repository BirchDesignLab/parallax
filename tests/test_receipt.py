import unittest
from parallax.receipt import checks_line, probe_count, trailers, verdict

class Receipt(unittest.TestCase):
    def test_verdicts(self):
        self.assertEqual([verdict("behavior", 0, 0, []), verdict("behavior", 1, 0, []), verdict("behavior", 0, 1, []),
                          verdict("behavior", 2, 1, ["x"]), verdict("chore", 0, 0, [])],
                         ["consensus", "resolved", "ruled", "limited", "solo"])

    def test_probe_count(self):
        self.assertEqual(probe_count("....\nRan 14 tests in 0.01s\n\nOK", r"Ran (\d+) tests?"), 14)
        self.assertEqual(probe_count("Ran 1 test in 0.0s", r"Ran (\d+) tests?"), 1)
        self.assertIsNone(probe_count("all good", r"Ran (\d+) tests?"))

    def test_checks_line(self):
        killed = {"m1": "killed", "m2": "killed", "m3": "killed"}
        self.assertEqual(checks_line(14, killed), "14 probes passed, 3 of 3 mutants caught")
        self.assertEqual(checks_line(None, {**killed, "m2": "survived"}, waived=["m2"]), "check passed, 2 of 3 mutants caught")

    def test_trailers_match_the_spec_sample(self):
        self.assertEqual(
            trailers("clamp-001", "sha256:9f2c", "codex gpt-6.2-astra/xhigh", "claude fable/high",
                     "14 probes passed, 3 of 3 mutants caught", "consensus", []),
            "Parallax-Task: clamp-001\nParallax-Contract: sha256:9f2c\nBuilt-by: codex gpt-6.2-astra/xhigh\n"
            "Challenged-by: claude fable/high\nChecks: 14 probes passed, 3 of 3 mutants caught\nVerdict: consensus")

    def test_solo_and_limitations(self):
        self.assertEqual(trailers("docs-1", None, "codex gpt-6.2-astra/xhigh", None, "check passed", "solo", []),
                         "Parallax-Task: docs-1\nBuilt-by: codex gpt-6.2-astra/xhigh\nChecks: check passed\nVerdict: solo")
        self.assertTrue(trailers("t", "sha256:0", "a", "b", "c", "limited", ["NaN is not supported", "mutant m2 waived"])
                        .endswith("Verdict: limited\nLimitation: NaN is not supported\nLimitation: mutant m2 waived"))
