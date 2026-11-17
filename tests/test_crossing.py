import dataclasses, sys, time, unittest
from pathlib import Path
from parallax import gitops
from parallax.config import load_config
from parallax.crossing import cross, validate_mutants
from tests.helpers import make_repo, write

TOML = (f'[project]\ncheck = \'"{sys.executable}" -m unittest discover -s tests -t .\'\n'
        '[scopes]\nbuilder = ["clamplib/**"]\nchallenger = ["tests/**"]\n'
        '[seats.codex]\nmodel = "m"\neffort = "e"\n[seats.claude]\nmodel = "m"\neffort = "e"\n')
OK = 'def clamp(x, lo, hi):\n    if lo > hi:\n        raise ValueError("lo > hi")\n    return max(lo, min(x, hi))\n'
NO_UPPER = OK.replace("max(lo, min(x, hi))", "max(lo, x)")
NO_LOWER = OK.replace("max(lo, min(x, hi))", "min(x, hi)")
HANGS = "while True:\n    pass\n"
PROBES = ('import unittest\nfrom clamplib import clamp\n\nclass ClampProbes(unittest.TestCase):\n'
          '    def test_inside(self):\n        self.assertEqual(clamp(5, 1, 10), 5)\n'
          '    def test_low(self):\n        self.assertEqual(clamp(-3, 1, 10), 1)\n'
          '    def test_high(self):\n        self.assertEqual(clamp(99, 1, 10), 10)\n')
WEAK = PROBES.split("    def test_high")[0]
FILE = "clamplib/__init__.py"

class Crossing(unittest.TestCase):
    def arrange(self, source=OK, probes=PROBES, mutants=None, timeout=120):
        repo = make_repo({"parallax.toml": TOML, FILE: "", "tests/__init__.py": "",
                          "tests/test_baseline.py": "import unittest\n\nclass Baseline(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n"})
        self.cfg = dataclasses.replace(load_config(repo), check_timeout=timeout)
        base = gitops.rev(repo, "main")
        builder, challenger, work = (repo.parent / n for n in ("b", "c", "w"))
        for dest in (builder, challenger, work):
            gitops.clone_at(repo, dest, "main")
        write(builder, {FILE: source}); b = gitops.snapshot(builder, "b")
        write(challenger, {"tests/test_clamp.py": probes}); c = gitops.snapshot(challenger, "c")
        gitops.fetch(work, builder, b); gitops.fetch(work, challenger, c)
        self.mutants_dir = repo.parent / "mutants"
        listed = []
        for name, text in (mutants or {}).items():
            write(self.mutants_dir, {f"{name}/{FILE}": text})
            listed.append({"id": name, "description": name, "files": [FILE]})
        self.builder = builder
        return work, base, b, c, listed

    def test_good_work_passes_and_every_mutant_is_killed(self):
        work, base, b, c, listed = self.arrange(mutants={"m1": NO_UPPER, "m2": NO_LOWER})
        result = cross(work, base, b, c, self.cfg, self.mutants_dir, listed)
        self.assertEqual((result.passed, result.count, result.mutants, result.clean), (True, 4, {"m1": "killed", "m2": "killed"}, True))
        self.assertEqual((work / FILE).read_text(encoding="utf-8"), OK)       # real files restored after the mutants

    def test_weak_probes_let_a_mutant_survive(self):
        work, base, b, c, listed = self.arrange(probes=WEAK, mutants={"m1": NO_UPPER, "m2": NO_LOWER})
        result = cross(work, base, b, c, self.cfg, self.mutants_dir, listed)
        self.assertEqual((result.passed, result.mutants, result.clean), (True, {"m1": "survived", "m2": "killed"}, False))

    def test_failing_check_skips_the_mutants(self):
        work, base, b, c, listed = self.arrange(source=NO_UPPER, mutants={"m1": NO_LOWER})
        result = cross(work, base, b, c, self.cfg, self.mutants_dir, listed)
        self.assertEqual((result.passed, result.mutants, result.clean), (False, {}, False))
        self.assertIn("test_high", result.output)

    def test_a_mutant_that_hangs_counts_as_killed(self):
        work, base, b, c, listed = self.arrange(mutants={"m1": HANGS}, timeout=5)
        started = time.time()
        result = cross(work, base, b, c, self.cfg, self.mutants_dir, listed)
        self.assertEqual(result.mutants, {"m1": "killed"})
        self.assertLess(time.time() - started, 60)

    def test_crossing_twice_in_the_same_clone_works(self):
        work, base, b, c, listed = self.arrange(mutants={"m1": NO_UPPER})
        cross(work, base, b, c, self.cfg, self.mutants_dir, listed)
        self.assertTrue(cross(work, base, b, c, self.cfg, self.mutants_dir, listed).clean)

class MutantValidation(unittest.TestCase):
    def test_problems(self):
        c = Crossing(); work, base, b, _, listed = c.arrange(mutants={"m1": NO_UPPER, "m2": OK})
        cfg = dataclasses.replace(c.cfg, mutants=3)
        listed.append({"id": "m3", "description": "ghost", "files": ["clamplib/missing.py"]})
        listed.append({"id": "m4", "description": "stray", "files": ["tests/test_clamp.py"]})
        problems = " | ".join(validate_mutants(c.builder, c.mutants_dir, listed, cfg))
        for needle in ("m2", "identical", "m3", "clamplib/missing.py", "m4", "tests/test_clamp.py", "expected 3 mutants, got 1"):
            self.assertIn(needle, problems)

    def test_fine(self):
        c = Crossing(); _, _, _, _, listed = c.arrange(mutants={"m1": NO_UPPER, "m2": NO_LOWER})
        self.assertEqual(validate_mutants(c.builder, c.mutants_dir, listed, dataclasses.replace(c.cfg, mutants=2)), [])
