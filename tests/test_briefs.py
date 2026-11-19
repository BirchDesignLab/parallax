import json, re, unittest
from parallax import briefs
from parallax.config import load_config
from tests.test_config import SAMPLE_TOML, project

CONTRACT = "# Contract: clamp-001 (v1)\n## Interface\nclamplib.clamp(x, lo, hi)\n"
PRECEDENT = {"id": "P-1", "question": "What if lo > hi?", "ruling": "raise ValueError", "while": "", "task": "t0"}
OTHER = {"interface": "clamplib.clamp(x, lo, hi)", "decisions": [{"question": "NaN?", "answer": "return NaN", "why": "ieee"}], "predicted_failures": []}
EVIDENCE = [{"id": "D-clamp-001-2", "kind": "check", "text": "FAIL: test_high\nAssertionError: 11 != 10"}]
ABSOLUTE = re.compile(r"(?i)(?<![a-z])[a-z]:[\\/]|/Users/|/home/")

class Briefs(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config(project(SAMPLE_TOML))
        self.all = {
            "reading": briefs.reading("Add clamp.", "builder", self.cfg, [PRECEDENT]),
            "reveal": briefs.reveal("challenger", OTHER),
            "build": briefs.build(CONTRACT, self.cfg),
            "probe": briefs.probe(CONTRACT, self.cfg),
            "respond": briefs.respond("builder", CONTRACT, EVIDENCE, self.cfg, ruling="The challenger is right."),
            "solo": briefs.solo("Fix the README typo.", self.cfg),
            "retry": briefs.retry("you changed files outside your paths: tests/sneaky.py"),
        }

    def test_reveal_asks_for_a_witness_and_never_to_agree_to_a_contradicted_answer(self):
        text = self.all["reveal"]
        for part in ("`witness` (object)", "`scenario`", "`observation`", "`theirs`", "`mine`", "`decided_by`",
                     "exactly `no commitment`", "copy its question verbatim",
                     "Agree when you accept the builder's whole answer as written",
                     "Never agree to an answer you believe is contradicted"):
            self.assertIn(part, text)

    def test_rejected_appends_the_reason_and_scrubs_paths(self):
        text = briefs.rejected("# Reveal\nbody", r"verdict 0: missing scenario (see C:\Users\x\clone)")
        self.assertTrue(text.startswith("# Reveal\nbody"))
        self.assertIn("## Your last reply was rejected", text)
        self.assertIn("verdict 0: missing scenario", text)
        self.assertIsNone(ABSOLUTE.search(text))

    def test_every_brief_carries_the_rules_and_no_absolute_path(self):
        for name, text in self.all.items():
            if name != "retry":
                self.assertIn(briefs.RULES, text, name)
            self.assertIsNone(ABSOLUTE.search(text), name)
            self.assertNotIn(str(self.cfg.root), text, name)

    def test_reading(self):
        text = self.all["reading"]
        for part in ("Add clamp.", "You will be the builder.", "P-1", "raise ValueError", "src/**", "tests/**"):
            self.assertIn(part, text)

    def test_reveal_shows_the_other_reading_and_asks_for_a_verdict_per_index(self):
        self.assertIn(json.dumps(OTHER, indent=2), self.all["reveal"])
        self.assertIn("index 0", self.all["reveal"])

    def test_build(self):
        text = self.all["build"]
        for part in (CONTRACT, "Write only under: src/**, pyproject.toml, uv.lock", ".parallax-mutants/<id>/", "3 mutants", "Do not write tests."):
            self.assertIn(part, text)

    def test_probe(self):
        text = self.all["probe"]
        for part in (CONTRACT, "Write only under: tests/**", "The implementation is not in this folder. Do not write it."):
            self.assertIn(part, text)

    def test_respond_carries_ids_evidence_and_ruling(self):
        text = self.all["respond"]
        for part in ("D-clamp-001-2", "AssertionError: 11 != 10", "The challenger is right.", "Write only under: src/**, pyproject.toml, uv.lock"):
            self.assertIn(part, text)
        self.assertIn("Write only under: tests/**", briefs.respond("challenger", CONTRACT, EVIDENCE, self.cfg))

    def test_reading_says_what_lands_for_either_role_even_with_no_mutants(self):
        no_mutants = load_config(project(SAMPLE_TOML.replace("mutants = 3", "mutants = 0")))
        self.assertEqual(no_mutants.mutants, 0)
        for cfg in (self.cfg, no_mutants):
            for role in briefs.ROLES:
                text = briefs.reading("Add clamp.", role, cfg, [])
                for part in (".parallax-mutants/", ".parallax-scratch/", "never land", "## What lands"):
                    self.assertIn(part, text, (role, cfg.mutants, part))

    def test_writing_briefs_ask_for_the_files_list(self):
        for name in ("build", "probe", "respond", "solo"):
            self.assertIn("`files` (list)", self.all[name], name)
            self.assertIn("## What lands", self.all[name], name)
        self.assertIn("repeat your full list unchanged", self.all["respond"])
        for name in ("build", "probe", "solo", "reading"):
            self.assertNotIn("repeat your full list unchanged", self.all[name], name)

    def test_only_the_challenger_is_asked_to_object_to_files_that_should_not_land(self):
        self.assertIn("should not be on main", briefs.reveal("challenger", OTHER))
        self.assertNotIn("should not be on main", briefs.reveal("builder", OTHER))

    def test_retry_names_the_reason(self):
        self.assertIn("tests/sneaky.py", self.all["retry"])

    # Not in the plan: crossing output and seat-written readings can carry absolute paths
    # (tracebacks from the scratch clone, a seat naming its own clone). Briefs must strip them.
    def test_absolute_paths_in_inputs_are_removed(self):
        trace = ('Traceback (most recent call last):\n'
                 '  File "C:\\Users\\me\\.parallax\\abc123\\clamp-001\\cross\\tests\\test_clamp.py", line 9, in test_high\n'
                 'see /home/me/.parallax/x/y.py and C:/Users/me/plx cfg/z.py')
        texts = [briefs.respond("challenger", CONTRACT, [{"id": "D-1", "kind": "check", "text": trace}], self.cfg),
                 briefs.reveal("builder", {**OTHER, "interface": "C:\\Users\\me\\.parallax\\k\\t\\codex-1a2b3c4d\\clamplib\\__init__.py"}),
                 briefs.retry("lint failed: *** Error compiling 'D:\\plx\\codex-1a2b3c4d\\src\\a.py'")]
        for text in texts:
            self.assertIsNone(ABSOLUTE.search(text), text)
            self.assertNotIn(".parallax", text.replace(".parallax-mutants", "").replace(".parallax-scratch", ""))
        self.assertIn('File "<outside>/test_clamp.py", line 9', texts[0])
        self.assertIn("https://example.com/a", briefs.solo("See https://example.com/a", self.cfg))
