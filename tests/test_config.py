import os, tempfile, unittest
from pathlib import Path
from parallax.config import SAMPLE_TOML, ConfigError, load_config, repo_key, state_home

MINIMAL = ('[project]\ncheck = "x"\n[scopes]\nbuilder = ["a/**"]\nchallenger = ["b/**"]\n'
           '[seats.codex]\nmodel = "m"\neffort = "e"\n[seats.claude]\nmodel = "m"\neffort = "e"\n')

def project(text):
    root = Path(tempfile.mkdtemp(prefix="plx cfg "))
    if text is not None:
        (root / "parallax.toml").write_text(text, encoding="utf-8")
    return root

class LoadConfig(unittest.TestCase):
    def test_spec_sample_loads_with_exact_values(self):
        cfg = load_config(project(SAMPLE_TOML))
        self.assertEqual(cfg.check, "python -m unittest discover -s tests")
        self.assertEqual(cfg.lint, "python -m compileall -q .")
        self.assertEqual(cfg.builder_scope, ("src/**", "pyproject.toml", "uv.lock"))
        self.assertEqual(cfg.challenger_scope, ("tests/**",))
        self.assertEqual((cfg.merge, cfg.pair, cfg.max_repair_rounds, cfg.mutants), ("auto", "behavior", 2, 3))
        self.assertEqual([(s.name, s.adapter, s.model, s.effort) for s in cfg.seats],
                         [("codex", "codex", "gpt-6.2-astra", "xhigh"), ("claude", "claude", "fable", "high")])

    def test_defaults(self):
        cfg = load_config(project(MINIMAL))
        self.assertEqual((cfg.main, cfg.lint, cfg.merge, cfg.pair), ("main", "", "auto", "behavior"))
        self.assertEqual((cfg.max_repair_rounds, cfg.mutants, cfg.check_timeout, cfg.seat_timeout), (2, 3, 600, 1800))
        self.assertEqual(cfg.count_pattern, r"Ran (\d+) tests?")
        self.assertEqual(cfg.run_dir, cfg.root / ".parallax" / "run")

    def test_adapter_can_differ_from_seat_name(self):
        cfg = load_config(project(MINIMAL.replace('[seats.codex]\n', '[seats.codex]\nadapter = "stub"\n')))
        self.assertEqual(cfg.seats[0].adapter, "stub")

    def test_each_problem_is_named(self):
        cases = {
            None: "parallax.toml",
            MINIMAL.replace('check = "x"\n', ""): "check",
            MINIMAL.replace('builder = ["a/**"]\n', ""): "builder",
            MINIMAL.split("[seats.claude]")[0]: "exactly two seats",
            MINIMAL + '[policy]\nmerge = "manual"\n': "merge",
            MINIMAL + '[policy]\npair = "all"\n': "pair",
            "not = [valid": "parallax.toml",
        }
        for text, needle in cases.items():
            with self.subTest(needle=needle), self.assertRaises(ConfigError) as caught:
                load_config(project(text))
            self.assertIn(needle, str(caught.exception))

class Homes(unittest.TestCase):
    def test_state_home_honors_override(self):
        os.environ["PARALLAX_HOME"] = r"C:\some where\plx"
        try:
            self.assertEqual(state_home(), Path(r"C:\some where\plx"))
        finally:
            del os.environ["PARALLAX_HOME"]

    def test_state_home_defaults_to_the_home_folder_not_app_data(self):
        saved = os.environ.pop("PARALLAX_HOME", None)
        try:
            self.assertEqual(state_home(), Path.home() / ".parallax")
        finally:
            if saved is not None:
                os.environ["PARALLAX_HOME"] = saved

    def test_repo_key_is_stable_and_short(self):
        root = project(MINIMAL)
        self.assertEqual(repo_key(root), repo_key(Path(str(root).upper())))
        self.assertRegex(repo_key(root), r"^[0-9a-f]{12}$")
