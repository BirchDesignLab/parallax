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
            self.assertNotIn(".parallax", text.replace(".parallax-mutants", ""))
        self.assertIn('File "<outside>/test_clamp.py", line 9', texts[0])
        self.assertIn("https://example.com/a", briefs.solo("See https://example.com/a", self.cfg))
