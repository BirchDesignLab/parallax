import json, os, sys, tempfile, unittest, uuid
from pathlib import Path
from parallax import seats
from parallax.config import load_config
from parallax.schemas import PROBE
from parallax.seats.base import SeatRequest
from parallax.seats.claude import ClaudeSeat
from tests.test_config import SAMPLE_TOML, project

FAKE = [sys.executable, str(Path(__file__).parent / "fakes" / "fake_claude.py")]

class Claude(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config(project(SAMPLE_TOML))
        self.tmp = Path(tempfile.mkdtemp(prefix="plx claude "))
        self.cwd = self.tmp / "seat clone"; self.cwd.mkdir()
        os.environ["FAKE_CLAUDE_RECORD"] = str(self.tmp / "record.json")
        os.environ["CLAUDE_CODE_SDK_HAS_HOST_AUTH_REFRESH"] = "1"
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in ("FAKE_CLAUDE_RECORD", "FAKE_CLAUDE_MODE", "CLAUDE_CODE_SDK_HAS_HOST_AUTH_REFRESH")])
        self.seat = ClaudeSeat(self.cfg.seats[1], self.cfg, launcher=FAKE)

    def request(self, writable=True, session=None):
        return SeatRequest("probe", "the brief", self.cwd, PROBE, writable, session, self.tmp / "out dir")

    def calls(self):
        return json.loads((self.tmp / "record.json").read_text())

    def test_new_session_command_line_is_exact(self):
        result = self.seat.run(self.request())
        argv = self.calls()[0]["argv"]
        new_id = argv[-1]
        uuid.UUID(new_id)
        self.assertEqual(argv, ["-p", "--model", "fable", "--effort", "high", "--safe-mode", "--restricted",
                                "--tools", "Read,Write,Edit,Glob,Grep", "--permission-mode", "acceptEdits",
                                "--permission-prompts", "none", "--output-format", "stream-json", "--verbose",
                                "--json-schema", json.dumps(PROBE), "--session-id", new_id])
        self.assertEqual((self.calls()[0]["stdin"], Path(self.calls()[0]["cwd"])), ("the brief", self.cwd))
        self.assertLessEqual(set(self.calls()[0]["env"]), {"ANTHROPIC_API_KEY"})             # the host-auth variables are gone
        self.assertTrue(result.ok)
        self.assertEqual((result.output, result.session), ({"summary": "probed", "blocked": "", "files": []}, new_id))
        self.assertEqual(result.usage, {"input": 9312, "cached": 9000, "output": 45})
        self.assertIn("tool_use", result.events)
        self.assertEqual((self.seat.name, self.seat.model, self.seat.effort), ("claude", "fable", "high"))

    def test_read_only_has_no_writing_tools_and_resume_reuses_the_session(self):
        self.seat.run(self.request(writable=False, session="11111111-1111-4111-8111-111111111111"))
        argv = self.calls()[0]["argv"]
        self.assertEqual(argv[argv.index("--tools") + 1], "Read,Glob,Grep")
        self.assertEqual(argv[-2:], ["--resume", "11111111-1111-4111-8111-111111111111"])
        self.assertNotIn("--session-id", argv)

    def test_output_may_arrive_as_text(self):
        os.environ["FAKE_CLAUDE_MODE"] = "text_json"
        self.assertEqual(self.seat.run(self.request()).output, {"summary": "probed", "blocked": "", "files": []})

    def test_failures_are_reported_not_raised(self):
        for mode, needle in (("auth", "Failed to authenticate"), ("no_result", "claude exited 1"), ("wrong_shape", "blocked")):
            os.environ["FAKE_CLAUDE_MODE"] = mode
            result = self.seat.run(self.request())
            self.assertFalse(result.ok, mode); self.assertIn(needle, result.error, mode)

    def test_discard_and_registry(self):
        self.seat.discard("whatever", self.cwd)
        self.assertEqual(self.calls()[0]["argv"], ["purge", "-y", str(self.cwd)])
        self.assertIsInstance(seats.make_seats(self.cfg)["claude"], ClaudeSeat)
