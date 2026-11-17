import os, tempfile, unittest, uuid
from pathlib import Path
from parallax import folders, gitops
from parallax.config import load_config, state_home
from parallax.schemas import PROBE
from parallax.seats.base import SeatRequest
from tests.helpers import make_repo
from tests.test_config import SAMPLE_TOML

@unittest.skipUnless(os.environ.get("PARALLAX_LIVE") == "1", "set PARALLAX_LIVE=1 to call the real CLIs")
class Live(unittest.TestCase):
    def exercise(self, seat):
        task_folder = state_home() / "live-test" / uuid.uuid4().hex[:8]       # where real seats work: private, under the home folder
        folders.make_private(task_folder)
        self.addCleanup(gitops.remove_tree, task_folder)
        clone = task_folder / "seat"
        gitops.clone_at(make_repo(), clone, "main")
        out = Path(tempfile.mkdtemp(prefix="plx live "))
        first = seat.run(SeatRequest("probe", "Create a file named made.txt containing: hi. Then answer with summary 'done' and blocked ''.",
                                     clone, PROBE, True, None, out / "1"))
        self.assertTrue(first.ok, first.error)
        self.assertEqual((clone / "made.txt").read_text(encoding="utf-8").strip(), "hi")   # this account can read what the seat wrote
        self.assertTrue(folders.is_private(task_folder))
        second = seat.run(SeatRequest("probe", "What file did you just create? Put its name in summary; blocked ''.",
                                      clone, PROBE, False, first.session, out / "2"))
        self.assertTrue(second.ok, second.error)
        self.assertIn("made.txt", second.output["summary"])
        seat.discard(first.session, clone)

    def test_codex(self):
        from parallax.seats.codex import CodexSeat
        root = make_repo({"parallax.toml": SAMPLE_TOML})
        cfg = load_config(root)
        self.exercise(CodexSeat(cfg.seats[0], cfg))
