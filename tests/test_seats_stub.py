import os, tempfile, unittest
from pathlib import Path
from parallax import seats
from parallax.config import ConfigError, load_config
from parallax.schemas import PROBE
from parallax.seats.base import SeatRequest, SeatResult, seat_env
from parallax.seats.stub import StubSeat
from tests.test_config import MINIMAL, project

def request(stage="probe", session=None, cwd=None):
    cwd = cwd or Path(tempfile.mkdtemp(prefix="plx seat "))
    return SeatRequest(stage, "brief text", cwd, PROBE, True, session, cwd / "out")

class Stub(unittest.TestCase):
    def test_replays_steps_in_order_and_records_calls(self):
        seat = StubSeat("codex", {"probe": [lambda r: {"summary": "one", "blocked": ""}, lambda r: {"summary": "two", "blocked": ""}]})
        first, second = seat.run(request()), seat.run(request())
        self.assertEqual((first.output["summary"], second.output["summary"]), ("one", "two"))
        self.assertTrue(first.ok)
        self.assertEqual(len(seat.calls), 2)
        with self.assertRaises(AssertionError):
            seat.run(request())

    def test_sessions(self):
        seat = StubSeat("codex", {"probe": [lambda r: {"summary": "", "blocked": ""}] * 3})
        a = seat.run(request())
        b = seat.run(request(session=a.session))
        c = seat.run(request())
        self.assertEqual((a.session, b.session, c.session), ("codex-s1", "codex-s1", "codex-s2"))

    def test_output_is_checked_against_the_schema(self):
        result = StubSeat("codex", {"probe": [lambda r: {"summary": "s"}]}).run(request())
        self.assertFalse(result.ok)
        self.assertIn("blocked", result.error)

    def test_a_step_can_edit_files_and_return_a_whole_result(self):
        def step(req):
            (req.cwd / "made.txt").write_text("x", encoding="utf-8")
            return SeatResult({"summary": "s", "blocked": ""}, "custom", "EVENTS", {"input": 1, "cached": 0, "output": 2})
        req = request()
        result = StubSeat("claude", {"probe": [step]}).run(req)
        self.assertTrue((req.cwd / "made.txt").exists())
        self.assertEqual((result.session, result.events), ("custom", "EVENTS"))

    def test_discard_is_recorded(self):
        seat = StubSeat("codex", {})
        seat.discard("codex-s1", Path("."))
        self.assertEqual(seat.discarded, ["codex-s1"])

class Registry(unittest.TestCase):
    def test_make_seats_uses_the_registry(self):
        cfg = load_config(project(MINIMAL.replace('model = "m"', 'adapter = "stub"\nmodel = "m"')))
        built = {"codex": StubSeat("codex", {}), "claude": StubSeat("claude", {})}
        seats.ADAPTERS["stub"] = lambda seat_cfg, cfg: built[seat_cfg.name]
        try:
            self.assertEqual(list(seats.make_seats(cfg)), ["codex", "claude"])
        finally:
            del seats.ADAPTERS["stub"]
        with self.assertRaises(ConfigError):
            seats.make_seats(cfg)

class Environment(unittest.TestCase):
    def test_other_agents_variables_are_removed(self):
        os.environ.update({"CLAUDE_CODE_USER_EMAIL": "x", "ANTHROPIC_BASE_URL": "x", "ANTHROPIC_API_KEY": "k",
                           "OPENAI_API_KEY": "k", "CODEX_HOME": "h", "CODEX_OTHER": "x", "PLX_KEEP": "1"})
        try:
            claude, codex = seat_env("claude"), seat_env("codex")
        finally:
            for key in ("CLAUDE_CODE_USER_EMAIL", "ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CODEX_HOME", "CODEX_OTHER", "PLX_KEEP"):
                del os.environ[key]
        self.assertEqual({k for k in claude if k.startswith(("CLAUDE", "ANTHROPIC", "OPENAI", "CODEX"))}, {"ANTHROPIC_API_KEY"})
        self.assertEqual({k for k in codex if k.startswith(("CLAUDE", "ANTHROPIC", "OPENAI", "CODEX"))}, {"OPENAI_API_KEY", "CODEX_HOME"})
        self.assertEqual(claude["PLX_KEEP"], "1")
