import re, sys, tempfile
from pathlib import Path
from parallax.conductor import Conductor
from parallax.config import load_config
from parallax.seats.stub import StubSeat
from tests.helpers import make_repo, write

FILE = "clamplib/__init__.py"
CLAMP_OK = 'def clamp(x, lo, hi):\n    if lo > hi:\n        raise ValueError("lo > hi")\n    return max(lo, min(x, hi))\n'
CLAMP_BAD = CLAMP_OK.replace("min(x, hi)", "min(x, hi + 1)")
MUTANTS = {"m1": CLAMP_OK.replace("max(lo, min(x, hi))", "max(lo, x)"),
           "m2": CLAMP_OK.replace("max(lo, min(x, hi))", "min(x, hi)"),
           "m3": CLAMP_OK.replace('        raise ValueError("lo > hi")\n', "        lo, hi = hi, lo\n")}
PROBES = ('import unittest\nfrom clamplib import clamp\n\nclass ClampProbes(unittest.TestCase):\n'
          '    def test_inside(self):\n        self.assertEqual(clamp(5, 1, 10), 5)\n'
          '    def test_low(self):\n        self.assertEqual(clamp(-3, 1, 10), 1)\n'
          '    def test_reversed(self):\n        with self.assertRaises(ValueError):\n            clamp(5, 10, 1)\n'
          '    def test_high(self):\n        self.assertEqual(clamp(99, 1, 10), 10)\n')
WEAK_PROBES = PROBES.split("    def test_high")[0]
DECISION = {"question": "What if lo > hi?", "answer": "raise ValueError", "why": "caller error"}
TOML = (f'[project]\ncheck = \'"{sys.executable}" -m unittest discover -s tests -t .\'\n'
        f'lint = \'"{sys.executable}" -m compileall -q .\'\n'
        '[scopes]\nbuilder = ["clamplib/**"]\nchallenger = ["tests/**"]\n'
        '[seats.codex]\nadapter = "stub"\nmodel = "stub-model"\neffort = "none"\n'
        '[seats.claude]\nadapter = "stub"\nmodel = "stub-model"\neffort = "none"\n')

def make_project() -> Path:
    return make_repo({
        "parallax.toml": TOML, FILE: "", "tests/__init__.py": "",
        "tests/test_baseline.py": "import unittest\n\nclass Baseline(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n",
        "tasks/clamp-001.md": "Add clamp(x, lo, hi) to clamplib: returns x limited to the range lo..hi.\n",
        "tasks/clamp-002.md": "Add clamp_all(values, lo, hi) to clamplib.\n",
        "tasks/docs-001.md": "Kind: chore\nFix the README wording.\n",
        ".parallax/.gitignore": "run/\n", ".parallax/ledger.jsonl": "",
    })

def kit_conductor(root: Path, codex: StubSeat, claude: StubSeat) -> Conductor:
    said = []
    conductor = Conductor(load_config(root), {"codex": codex, "claude": claude}, say=said.append,
                          home=Path(tempfile.mkdtemp(prefix="plx home ")))
    conductor.said = said
    return conductor

def reading(*decisions, interface="clamplib.clamp(x, lo, hi) -> number"):
    return lambda req: {"interface": interface, "decisions": list(decisions), "predicted_failures": []}

def reveal(*verdicts, interface_ok=True, objection=""):
    """Each verdict is (agree, counter) for the other seat's decision at that position."""
    return lambda req: {"interface_ok": interface_ok, "interface_objection": objection,
                        "verdicts": [{"index": i, "agree": agree, "counter": counter, "why": ""}
                                     for i, (agree, counter) in enumerate(verdicts)]}

def _mutant_list(mutants):
    return [{"id": name, "description": name, "files": [FILE]} for name in mutants]

def builds(source=CLAMP_OK, mutants=MUTANTS, extra=None):
    def step(req):
        write(req.cwd, {FILE: source, **{f".parallax-mutants/{n}/{FILE}": t for n, t in mutants.items()}, **(extra or {})})
        return {"summary": "built", "blocked": "", "mutants": _mutant_list(mutants)}
    return step

def probes(source=PROBES, extra=None):
    def step(req):
        write(req.cwd, {"tests/test_clamp.py": source, **(extra or {})})
        return {"summary": "probed", "blocked": ""}
    return step

def responds(stance, files=None, mutants=None):
    """Answer every dispute id in the brief with `stance`; write `files` first when given."""
    def step(req):
        mutants_now = mutants or {}
        write(req.cwd, {**(files or {}), **{f".parallax-mutants/{n}/{FILE}": t for n, t in mutants_now.items()}})
        ids = sorted(set(re.findall(r"D-[A-Za-z0-9._]+(?:-[A-Za-z0-9._]+)*-\d+", req.brief)))
        return {"answers": [{"dispute": i, "stance": stance, "cite": "", "why": ""} for i in ids],
                "blocked": "", "mutants": _mutant_list(mutants_now)}
    return step

def types(conductor: Conductor, task="clamp-001") -> list[str]:
    return [e["type"] for e in conductor.events(task)]
