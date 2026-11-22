import contextlib, json, unittest
from pathlib import Path
from unittest import mock
from parallax import batch, decisions, gitops
from parallax.conductor import LEDGER, Conductor
from parallax.ledger import publish
from parallax.seats.stub import StubSeat
from tests.conductor_kit import kit_conductor, make_project
from tests.helpers import commit
from tests.test_cli import call

# Task 19.3: the recorded 11-19 history, five cards opened by the Task 17 binary and five project B rulings,
# replays unchanged on this binary. The fixture is the public record of that run, extracted by
# scripts/fixtures/extract_clamp_11_19.py. No grouping runs on recorded evidence.
FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "clamp_11_19.json").read_text(encoding="utf-8"))
EVENTS = FIXTURE["events"]
OPENED = [e for e in EVENTS if e["type"] == "dispute.opened"]
RULED = [e for e in EVENTS if e["type"] == "ruling.made"]
IDS = [e["id"] for e in OPENED]
RULING_FIELDS = ["ts", "type", "task", "dispute", "kind", "question", "choice", "text", "scope", "while", "limitation"]

@contextlib.contextmanager
def never_batched():
    """Fail if anything enters the batch step, or builds a batch packet in memory, on recorded history."""
    with mock.patch.object(Conductor, "_certified", side_effect=AssertionError("the batch step ran on recorded history")),             mock.patch.object(batch, "packet", side_effect=AssertionError("a batch packet was built on recorded history")):
        yield

def without_ts(event):
    return {k: v for k, v in event.items() if k != "ts"}

def precedents_of(rulings):
    return [{"id": f"P-{n}", "question": r["question"], "ruling": r["text"], "while": r["while"], "task": r["task"]}
            for n, r in enumerate(rulings, 1)]


class RecordedHistory(unittest.TestCase):
    def test_the_fixture_is_the_recorded_run(self):
        self.assertEqual([e["type"] for e in EVENTS],
                         ["task.opened"] + ["dispute.opened"] * 5 + ["ruling.made"] * 5 + ["task.integrated"])
        self.assertEqual(IDS, [f"D-clamp-001-{n}" for n in range(1, 6)])
        self.assertFalse({"interface_protocol", "batch_protocol"} & set(EVENTS[0]))
        self.assertEqual([e["kind"] for e in OPENED], ["reading"] * 4 + ["interface"])
        self.assertEqual([(r["dispute"], r["choice"], r["scope"]) for r in RULED], [(i, "b", "project") for i in IDS])
        self.assertTrue(FIXTURE["precedents_md"].rstrip().endswith("Everything else in the interface stands."))

    def test_the_pending_journal_rules_normally_and_keeps_p1_to_p5(self):
        root = make_project()
        repo = ["--repo", str(root)]
        journal = root / ".parallax" / "run" / "journal.jsonl"
        publish(EVENTS[:6], journal)
        with never_batched():
            self.assertEqual(call("status", *repo)[1].split(), ["clamp-001", "needs_ruling", *IDS])
            for dispute in IDS[:2]:
                self.rule_appends_the_recorded_ruling(repo, journal, dispute)
            # A restart reads only the journal: the two ruled cards are gone, the other three wait.
            self.assertEqual(call("status", *repo)[1].split(), ["clamp-001", "needs_ruling", *IDS[2:]])
            before = journal.read_bytes()
            code, _, err = call("rule", IDS[1], "b", *repo)
            self.assertEqual((code, journal.read_bytes()), (1, before))
            self.assertIn(f"{IDS[1]} is already ruled", err)
            for dispute in IDS[2:]:
                self.rule_appends_the_recorded_ruling(repo, journal, dispute)
            self.assertEqual(call("status", *repo)[1].split(), ["clamp-001", "in_progress"])
        c = kit_conductor(root, StubSeat("codex", {}), StubSeat("claude", {}))
        self.assertEqual([without_ts(e) for e in c.journal.events()], [without_ts(e) for e in EVENTS[:6] + RULED])
        self.assertEqual(decisions.precedents(c.events()), precedents_of(RULED))
        self.assertEqual(decisions.render_precedents(decisions.precedents(c.events())), FIXTURE["precedents_md"])

    def rule_appends_the_recorded_ruling(self, repo, journal, dispute):
        """`rule <dispute> b` with no scope appends exactly the recorded ruling, timestamp aside, and nothing else."""
        before = journal.read_bytes()
        self.assertEqual(call("rule", dispute, "b", *repo)[0], 0)
        after = journal.read_bytes()
        self.assertTrue(after.startswith(before))
        [line] = after[len(before):].decode("utf-8").splitlines()
        new = json.loads(line)
        self.assertEqual(list(new), RULING_FIELDS)
        self.assertEqual(without_ts(new), without_ts(next(r for r in RULED if r["dispute"] == dispute)))

    def test_the_landed_ledger_replays_unchanged(self):
        root = make_project()
        publish(EVENTS, root / LEDGER)
        commit(root, {}, "the recorded 11-19 ledger")
        ledger, working = gitops.show_file(root, "main", LEDGER), (root / LEDGER).read_bytes()
        journal = root / ".parallax" / "run" / "journal.jsonl"
        codex, claude = StubSeat("codex", {}), StubSeat("claude", {})
        c = kit_conductor(root, codex, claude)
        with never_batched():
            outcome = c.run(root / "tasks/clamp-001.md")
            self.assertEqual((outcome.status, outcome.detail), ("landed", "clamp-001 has already landed"))
            self.assertEqual(c.status(), [{"task": "clamp-001", "status": "landed", "pending": []}])
            code, _, err = call("rule", IDS[0], "b", "--repo", str(root))
            self.assertEqual(code, 1)
            self.assertIn(f"{IDS[0]} is already ruled", err)
        self.assertEqual((codex.calls, claude.calls), ([], []))
        self.assertTrue(not journal.exists() or journal.read_bytes() == b"")
        self.assertEqual((gitops.show_file(root, "main", LEDGER), (root / LEDGER).read_bytes()), (ledger, working))
        self.assertEqual(decisions.precedents(c.events()), precedents_of(RULED))
        self.assertEqual(decisions.render_precedents(decisions.precedents(c.events())), FIXTURE["precedents_md"])


if __name__ == "__main__":
    unittest.main()
