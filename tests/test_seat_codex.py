import json, os, sys, tempfile, unittest
from pathlib import Path
from parallax import seats
from parallax.config import load_config
from parallax.schemas import PROBE
from parallax.seats.base import SeatRequest
from parallax.seats.codex import CodexSeat, windows_sandbox_setting
from tests.test_config import SAMPLE_TOML, project

FAKE = [sys.executable, str(Path(__file__).parent / "fakes" / "fake_codex.py")]

class Codex(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config(project(SAMPLE_TOML))
        self.tmp = Path(tempfile.mkdtemp(prefix="plx codex "))
        self.home = self.tmp / "codex home"; self.home.mkdir()
        (self.home / "config.toml").write_text('model = "gpt-6-astra"\n[windows]\nsandbox = "elevated"\n', encoding="utf-8")
        self.cwd = self.tmp / "seat clone"; self.cwd.mkdir()
        os.environ["FAKE_CODEX_RECORD"] = str(self.tmp / "record.json")
        os.environ["CLAUDE_CODE_USER_EMAIL"] = "someone@example.invalid"
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in ("FAKE_CODEX_RECORD", "FAKE_CODEX_MODE", "CLAUDE_CODE_USER_EMAIL")])
        self.seat = CodexSeat(self.cfg.seats[0], self.cfg, launcher=FAKE, codex_home=self.home)

    def request(self, writable=True, session=None):
        return SeatRequest("probe", "the brief", self.cwd, PROBE, writable, session, self.tmp / "out dir")

    def calls(self):
        return json.loads((self.tmp / "record.json").read_text())

    def test_new_session_command_line_is_exact(self):
        result = self.seat.run(self.request())
        out = str(self.tmp / "out dir")
        self.assertEqual(self.calls()[0]["argv"], [
            "exec", "-m", "gpt-6-astra", "-c", 'model_reasoning_effort="xhigh"', "--ignore-user-config",
            "-c", 'windows.sandbox="elevated"', "--sandbox", "workspace-write", "-C", str(self.cwd), "--color", "never", "--json",
            "--output-schema", os.path.join(out, "schema.json"), "-o", os.path.join(out, "last.json"), "-"])
        self.assertEqual(self.calls()[0]["stdin"], "the brief")
        self.assertEqual(Path(self.calls()[0]["cwd"]), self.cwd)
        self.assertLessEqual(set(self.calls()[0]["env"]), {"OPENAI_API_KEY", "CODEX_HOME"})    # nothing of Claude's leaks into the seat
        self.assertTrue(result.ok)
        self.assertEqual((result.output, result.session), ({"summary": "probed", "blocked": "", "files": []}, "01a1e764-ff34-76b3-ba77-7b4c3f751503"))
        self.assertEqual(result.usage, {"input": 31830, "cached": 15488, "output": 295})
        self.assertIn("command_execution", result.events)
        for name in ("brief.md", "schema.json", "events.jsonl", "output.json"):
            self.assertTrue((self.tmp / "out dir" / name).exists(), name)
        self.assertEqual((self.seat.name, self.seat.model, self.seat.effort), ("codex", "gpt-6-astra", "xhigh"))

    def test_read_only_and_resume(self):
        self.seat.run(self.request(writable=False))
        self.assertIn("read-only", self.calls()[0]["argv"])
        self.seat.run(self.request(session="abc-123"))
        argv = self.calls()[1]["argv"]
        self.assertEqual(argv[:2], ["exec", "resume"])
        self.assertIn('sandbox_mode="workspace-write"', argv)
        self.assertNotIn("--sandbox", argv); self.assertNotIn("-C", argv)
        self.assertEqual(argv[-2:], ["abc-123", "-"])

    def test_sandbox_setting_is_omitted_when_the_human_has_none(self):
        (self.home / "config.toml").write_text('model = "x"\n', encoding="utf-8")
        self.assertIsNone(windows_sandbox_setting(self.home))
        self.assertIsNone(windows_sandbox_setting(self.tmp / "missing"))
        CodexSeat(self.cfg.seats[0], self.cfg, launcher=FAKE, codex_home=self.home).run(self.request())
        self.assertFalse(any("windows.sandbox" in a for a in self.calls()[0]["argv"]))

    def test_failures_are_reported_not_raised(self):
        for mode, needle in (("always_fails", "codex exited 2"), ("not_json", "last.json"), ("wrong_shape", "blocked")):
            os.environ["FAKE_CODEX_MODE"] = mode
            result = self.seat.run(self.request())
            self.assertFalse(result.ok, mode); self.assertIn(needle, result.error, mode)

    def test_a_launch_failure_is_retried_once(self):
        os.environ["FAKE_CODEX_MODE"] = "launch_failure"
        self.assertTrue(self.seat.run(self.request()).ok)
        self.assertEqual(len(self.calls()), 2)

    def test_discard_and_registry(self):
        self.seat.discard("abc-123", self.cwd)
        self.assertEqual(self.calls()[0]["argv"], ["delete", "--force", "abc-123"])
        self.assertIsInstance(seats.ADAPTERS["codex"](self.cfg.seats[0], self.cfg), CodexSeat)   # make_seats also needs the claude adapter (Task 14)

    def test_discard_forgets_the_folder_codex_recorded_and_nothing_else(self):
        config = self.home / "config.toml"
        keep = ('model = "gpt-6-astra"\n\n[windows]\nsandbox = "elevated"\n\n'
                "[projects.'c:\\git\\a real project']\ntrust_level = \"trusted\"\n")
        mine = f"\n[projects.'{str(self.cwd).lower()}']\ntrust_level = \"trusted\"\n"
        config.write_text(keep + mine, encoding="utf-8")
        self.seat.discard("abc-123", self.cwd)
        self.assertEqual(config.read_text(encoding="utf-8"), keep + "\n")
        self.seat.discard("abc-123", self.cwd)                                  # no entry left: still fine
        self.assertEqual(config.read_text(encoding="utf-8"), keep + "\n")
        config.unlink()
        self.seat.discard("abc-123", self.cwd)                                  # no file: still fine
