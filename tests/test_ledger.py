import tempfile, threading, unittest
from pathlib import Path
from parallax.ledger import Journal, LedgerCorrupt, parse_lines, publish, sha256_text

class JournalTests(unittest.TestCase):
    def journal(self):
        ticks = iter(f"2026-11-16T00:{m:02d}:{s:02d}Z" for m in range(60) for s in range(60))
        return Journal(Path(tempfile.mkdtemp(prefix="plx led ")) / "run" / "journal.jsonl", clock=lambda: next(ticks))

    def test_append_then_read_in_order(self):
        j = self.journal()
        j.append("task.opened", "t1", base="abc")
        j.append("reading.sealed", "t1", seat="codex")
        j.append("task.opened", "t2", base="def")
        self.assertEqual(j.events()[0], {"ts": "2026-11-16T00:00:00Z", "type": "task.opened", "task": "t1", "base": "abc"})
        self.assertEqual([e["type"] for e in j.events("t1")], ["task.opened", "reading.sealed"])

    def test_missing_file_reads_as_empty(self):
        self.assertEqual(self.journal().events(), [])

    def test_torn_last_line_is_ignored_and_not_glued_onto(self):
        j = self.journal()
        j.append("task.opened", "t1")
        with open(j.path, "a", encoding="utf-8") as handle:
            handle.write('{"ts": "x", "type": "reading.se')
        self.assertEqual(len(j.events()), 1)
        j.append("reading.sealed", "t1")
        self.assertEqual([e["type"] for e in j.events()], ["task.opened", "reading.sealed"])

    def test_corrupt_earlier_line_raises(self):
        j = self.journal()
        j.append("task.opened", "t1")
        j.path.write_text("not json\n" + j.path.read_text(encoding="utf-8"), encoding="utf-8")
        with self.assertRaises(LedgerCorrupt):
            j.events()

    def test_drop_task_keeps_the_others(self):
        j = self.journal()
        j.append("task.opened", "t1"); j.append("task.opened", "t2"); j.append("reading.sealed", "t1")
        j.drop_task("t1")
        self.assertEqual([(e["task"], e["type"]) for e in j.events()], [("t2", "task.opened")])

    def test_two_threads_never_interleave(self):
        j = self.journal()
        workers = [threading.Thread(target=lambda n=n: [j.append("x", f"t{n}", i=i) for i in range(200)]) for n in (1, 2)]
        [w.start() for w in workers]; [w.join() for w in workers]
        self.assertEqual(len(j.events()), 400)

class LedgerFile(unittest.TestCase):
    def test_publish_accumulates(self):
        target = Path(tempfile.mkdtemp(prefix="plx led ")) / ".parallax" / "ledger.jsonl"
        publish([{"type": "a", "task": "t1"}], target)
        publish([{"type": "b", "task": "t1"}], target)
        self.assertEqual([e["type"] for e in parse_lines(target.read_text(encoding="utf-8"))], ["a", "b"])
        self.assertTrue(target.read_text(encoding="utf-8").endswith("\n"))

    def test_hash_ignores_line_ending_style(self):
        self.assertEqual(sha256_text("a\r\nb\n"), sha256_text("a\nb\n"))
        self.assertRegex(sha256_text("a"), r"^sha256:[0-9a-f]{64}$")
