import unittest
from dataclasses import replace
from unittest import mock
from parallax import briefs, decisions, gitops
from parallax.conductor import Conductor, _Stop
from parallax.ledger import Journal, parse_lines
from tests.conductor_kit import (CLAMP_OK, FILE, MUTANTS, PROBES, WEAK_PROBES, builds, kit_conductor, make_project,
                                 probes, responds)
from tests.test_cli import call
from tests.test_conductor_batch import proposes, reviews
from tests.test_conductor_crossed import MISSING, NOTE, card, contested, last, ruled_cards, the
from tests.test_conductor_frozen import (ONE, THREE, blocks, journal_bytes, lose_folder, on_main, rewrite_main,
                                         seated)
from tests.test_conductor_landing import seats
from tests.test_conductor_reading import agreeing, disagreeing, resumed
from tests.test_conductor_ruled import refusal, rule
from tests.test_conductor_settled import TASK, TASK_FILE, answers, rewrite, run, told
from tests.test_decisions import ROLE_READINGS, ROLE_REVEALS

# Task 19.9. Landing publishes a task's journal records to main's ledger, advances main, and only then forgets
# them. A run that dies between the two leaves the task in both: every reader counts the ledger's copy once, and
# the next run only cleans up. Copies of a confirmed-v1 task that differ block every reader. A ruling is a
# precedent for another task only while every history with confirmed-v1 records reads as its writer left it.
NEXT, NEXT_FILE = "clamp-002", "tasks/clamp-002.md"
LEDGER = ".parallax/ledger.jsonl"
TWO_COPIES = f"{TASK} has different ledger and journal records"
NO_PRECEDENT = f"{TASK}'s rulings cannot be precedents: "
LANDED = [{"task": TASK, "status": "landed", "pending": []}]

def copies(root, c, task=TASK):
    """The task's records in main's ledger and in the journal file, as each store holds them."""
    ledger = parse_lines(gitops.show_file(root, "main", LEDGER) or "")
    return [e for e in ledger if e.get("task") == task], c.journal.events(task)

def killed_before_cleanup(test, c, root, task_file=TASK_FILE, task=TASK):
    """Run until main has advanced, then die where the journal would forget the task: its records are now in
    main's ledger and in the journal, record for record."""
    before = gitops.rev(root, "main")
    with mock.patch.object(Journal, "drop_task", side_effect=RuntimeError("killed before cleanup")) as forget:
        with test.assertRaisesRegex(RuntimeError, "killed before cleanup"):
            c.run(root / task_file)
    forget.assert_called_once_with(task)
    test.assertNotEqual(gitops.rev(root, "main"), before)
    ledger, journal = copies(root, c, task)
    test.assertTrue(journal)
    test.assertEqual(journal, ledger)

def precedents(history):
    """The precedents a stream gives, by the rule that predates this slice, written out."""
    made = [e for e in history if e["type"] == "ruling.made" and e["scope"] == "project"]
    return [{"id": f"P-{n}", "question": e["question"], "ruling": e["text"], "while": e["while"], "task": e["task"]}
            for n, e in enumerate(made, 1)]

def in_force(found):
    return "".join(f"- {p['id']}: {p['question']} -> {p['ruling']}\n" for p in found)

def precedents_read(seat):
    """The whole precedents section of the seat's reading brief, up to the next section."""
    [request] = [r for r in seat.calls if r.stage == "reading"]
    return "## Precedents" + request.brief.split("## Precedents", 1)[1].split("\n\n## ", 1)[0]

def cleaned_up(test, root, c, status, detail):
    """The next run of the task calls no seat, appends nothing, moves nothing on main and forgets the journal's
    copy, and only that."""
    head, ledger = gitops.rev(root, "main"), gitops.show_file(root, "main", LEDGER)
    others = [e for e in c.journal.events() if e.get("task") != TASK]
    c2, codex, claude = resumed(root, c)
    with mock.patch.object(Journal, "append", side_effect=AssertionError("the cleanup run appended")):
        outcome = run(c2, root)
    test.assertEqual((told(outcome), codex.calls, claude.calls), ((status, detail), [], []))
    test.assertEqual((gitops.rev(root, "main"), gitops.show_file(root, "main", LEDGER)), (head, ledger))
    test.assertEqual(c.journal.events(), others)
    return outcome

def run_next(c, root):
    return told(c.run(root / NEXT_FILE, builder="codex"))

def no_precedent(test, root, c, t, detail):
    """Another task that asks for the precedents is refused with the history's diagnostic."""
    with test.assertRaises(_Stop) as stop:
        resumed(root, c)[0]._precedents(replace(t, id=NEXT))
    test.assertEqual((stop.exception.outcome.status, stop.exception.outcome.task, stop.exception.outcome.detail),
                     ("blocked", NEXT, NO_PRECEDENT + detail))


class Tail(unittest.TestCase):
    """A landing or a drop killed after main advanced and before the journal forgot the task."""

    def test_a_landed_task_still_in_the_journal_is_counted_once_and_the_next_run_only_cleans_up(self):
        root, c, t, settled, codex, claude = contested(self)
        question = card(c, THREE)["question"]
        self.assertEqual(rule(root, THREE, "b", "--note", NOTE)[0], 0)     # a check ruling: scoped to the project
        fixed = responds("concede", files={FILE: CLAMP_OK}, mutants=MUTANTS)
        c2, codex2, claude2 = seated(root, c, {"respond": [fixed]}, {})
        killed_before_cleanup(self, c2, root)
        head, history = gitops.rev(root, "main"), on_main(root)
        self.assertEqual(history[-1]["type"], "task.integrated")
        # Every reader counts the task once, from the ledger.
        self.assertEqual(c.events(TASK), history)
        expected = precedents(history)
        self.assertEqual([(p["id"], p["question"], p["ruling"]) for p in expected][1:], [("P-2", question, NOTE)])
        self.assertEqual(len(expected), 2)
        self.assertEqual(c.status(), LANDED)
        self.assertEqual((call("status", "--repo", str(root)), rule(root, THREE, "a")),
                         ((0, f"{TASK}  landed\n", ""), (1, "", f"parallax: {THREE} is already ruled\n")))
        # The next task reads each ruling once, under its number: the whole section of each brief, and its contract.
        codex3, claude3 = agreeing()
        c3, codex3, claude3 = seated(root, c, codex3.script, claude3.script)
        self.assertEqual(c3.run(root / NEXT_FILE, stop_after="contract").status, "stopped")
        self.assertEqual((precedents_read(codex3), precedents_read(claude3)), (briefs._precedents(expected),) * 2)
        contract = (root / ".parallax/run" / NEXT / "contract-v1.md").read_text(encoding="utf-8")
        self.assertEqual(contract.split("## Precedents in force\n")[1], in_force(expected))
        rows = [*LANDED, {"task": NEXT, "status": "in_progress", "pending": []}]
        self.assertEqual(c.status(), rows)
        # The next run of the landed task finishes the cleanup, here with the task's folder lost. The other
        # task's records stay, and nothing a reader sees changes.
        other = c.journal.events(NEXT)
        self.assertTrue(other)
        lose_folder(self, root, c, t)
        outcome = cleaned_up(self, root, c, "landed", f"landed {head[:12]}")
        self.assertEqual((outcome.commit, t.dir.exists(), c.journal.events()), (head, False, other))
        self.assertEqual((c.events(TASK), decisions.precedents(c.events()), c.status()), (history, expected, rows))

    def test_a_task_opened_before_the_marker_is_counted_once_too_and_the_next_landing_numbers_it_once(self):
        root = make_project(); codex, claude = disagreeing()
        codex.script["build"], claude.script["probe"] = [builds()], [probes()]
        c = kit_conductor(root, codex, claude)
        self.assertEqual(c.run(root / TASK_FILE).status, "needs_ruling")
        c.rule(ONE, "a")
        killed_before_cleanup(self, c, root)
        history = on_main(root)
        self.assertEqual(c.events(TASK), history)
        [precedent] = precedents(history)
        self.assertEqual((decisions.precedents(c.events()), c.status()), ([precedent], LANDED))
        # Copies of such a task that differ are read as before this slice: both, and no reader blocks.
        whole = journal_bytes(c)
        rewrite(c, lambda events: events.pop())
        self.assertEqual((c.status(), len(decisions.precedents(c.events()))),
                         ([{"task": TASK, "status": "in_progress", "pending": []}], 2))
        with self.assertRaisesRegex(ValueError, f"^{ONE} is already ruled$"):
            c.rule(ONE, "a")
        c.journal.path.write_bytes(whole)
        # Another task lands while the first is still in the journal: PRECEDENTS.md numbers the ruling once.
        codex2, claude2 = seats([builds(CLAMP_OK + "# next\n")], [probes(PROBES + "# next\n")])
        c2, codex2, claude2 = seated(root, c, codex2.script, claude2.script)
        self.assertEqual(run_next(c2, root)[0], "landed")
        self.assertEqual(gitops.show_file(root, "main", ".parallax/PRECEDENTS.md"), decisions.render_precedents([precedent]))
        rows = [*LANDED, {"task": NEXT, "status": "landed", "pending": []}]
        self.assertEqual((copies(root, c), c.status()), ((history, history), rows))
        head = gitops.rev(root, "main")
        landed = gitops.git(root, "log", "-1", "--format=%H", f"--grep=^Parallax-Task: {TASK}$", "main")
        self.assertEqual(cleaned_up(self, root, c, "landed", f"landed {landed[:12]}").commit, landed)
        self.assertEqual((decisions.precedents(c.events()), c.status(), gitops.rev(root, "main")),
                         ([precedent], rows, head))

    def test_a_dropped_task_still_in_the_journal_is_counted_once_and_the_next_run_only_cleans_up(self):
        root, c, t, settled = refusal()
        self.assertEqual(rule(root, ONE, "drop")[0], 0)
        killed_before_cleanup(self, resumed(root, c)[0], root)
        history = on_main(root)
        self.assertEqual((history[-1]["type"], c.events(TASK)), ("task.dropped", history))
        self.assertEqual((call("status", "--repo", str(root)), rule(root, ONE, "drop")),
                         ((0, f"{TASK}  dropped\n", ""), (1, "", f"parallax: {ONE} is already ruled\n")))
        cleaned_up(self, root, c, "dropped", f"{TASK} was dropped")
        self.assertEqual(call("status", "--repo", str(root)), (0, f"{TASK}  dropped\n", ""))

    def test_a_landing_numbers_the_precedents_as_the_next_reader_will(self):
        # Two tasks from before the marker, both live, each with a project ruling. The one ruled second lands
        # first: its records move to the ledger, ahead of the task still in the journal.
        root = make_project(); codex, claude = disagreeing()
        codex.script["build"], claude.script["probe"] = [builds()], [probes()]
        c = kit_conductor(root, codex, claude)
        self.assertEqual(c.run(root / TASK_FILE, builder="codex").status, "needs_ruling")
        codex2, claude2 = disagreeing()
        c2, codex2, claude2 = seated(root, c, codex2.script, claude2.script)
        self.assertEqual(c2.run(root / NEXT_FILE, builder="codex").status, "needs_ruling")
        c.rule(f"D-{NEXT}-1", "a"); c.rule(ONE, "a")
        self.assertEqual([p["task"] for p in decisions.precedents(c.events())], [NEXT, TASK])
        killed_before_cleanup(self, c, root)
        expected = [("P-1", TASK), ("P-2", NEXT)]
        written = decisions.render_precedents(decisions.precedents(c.events()))
        self.assertEqual([(p["id"], p["task"]) for p in decisions.precedents(c.events())], expected)
        self.assertEqual(gitops.show_file(root, "main", ".parallax/PRECEDENTS.md"), written)
        cleaned_up(self, root, c, "landed", f"landed {gitops.rev(root, 'main')[:12]}")
        self.assertEqual(([(p["id"], p["task"]) for p in decisions.precedents(c.events())],
                          gitops.show_file(root, "main", ".parallax/PRECEDENTS.md")), (expected, written))


class Guards(unittest.TestCase):
    """One landing killed before cleanup for the class. Each case edits a copy and puts both back."""

    @classmethod
    def setUpClass(cls):
        cls.root, c, cls.t, cls.settled, codex, claude = contested(cls())
        assert rule(cls.root, THREE, "b", "--note", NOTE)[0] == 0
        fixed = responds("concede", files={FILE: CLAMP_OK}, mutants=MUTANTS)
        cls.c = seated(cls.root, c, {"respond": [fixed]}, {})[0]
        killed_before_cleanup(cls(), cls.c, cls.root)
        cls.journal = journal_bytes(cls.c)
        cls.ledger = parse_lines(gitops.show_file(cls.root, "main", LEDGER))

    def cases(self, tampered, *ruling):
        """Each (change, where, detail): after `change` is made to the journal's copy, the ledger's or both,
        every reader refuses with `detail`, neither store changes, and no task gets a precedent."""
        root, c = self.root, self.c
        for number, (change, where, detail) in enumerate(tampered):
            with self.subTest(case=number, where=where, detail=detail):
                try:
                    if where in ("ledger", "both"):
                        rewrite_main(root, change)
                    if where in ("journal", "both"):
                        rewrite(c, change)
                    stores = copies(root, c)
                    blocks(self, root, c, detail, *ruling)
                    no_precedent(self, root, c, self.t, detail)
                    self.assertEqual(copies(root, c), stores)
                finally:
                    self.put_back(where != "journal")
        self.assertEqual(c.status(), LANDED)

    def put_back(self, ledger):
        self.c.journal.path.write_bytes(self.journal)
        if ledger:
            rewrite_main(self.root, lambda events: events.__setitem__(slice(None), self.ledger))

    def test_copies_that_differ_in_any_record_block_every_reader(self):
        def reworded(events):
            the("ruling.made", dispute=THREE)(events)["text"] = "The upper bound is exclusive."

        def swapped(events):
            events[-1], events[-2] = events[-2], events[-1]

        def truthy(events):
            the("contract.frozen", version=1)(events)["version"] = True          # True == 1, and is not 1

        differ = [(lambda events: events.pop(), "journal", TWO_COPIES),
                  (lambda events: events.pop(0), "journal", TWO_COPIES),
                  (reworded, "journal", TWO_COPIES),
                  (swapped, "journal", TWO_COPIES),
                  (lambda events: events.append(dict(events[-1])), "journal", TWO_COPIES),
                  (truthy, "journal", TWO_COPIES),
                  (reworded, "ledger", TWO_COPIES),
                  (lambda events: events.pop(), "ledger", TWO_COPIES)]
        # Read together these two would pass for one history, and the cleanup would forget the whole copy: a
        # journal cut to its opening after a whole ledger, and a ledger cut to its last record before a whole journal.
        as_one = [(lambda events: events.__delitem__(slice(1, None)), "journal", TWO_COPIES),
                  (lambda events: events.__delitem__(slice(0, -1)), "ledger", TWO_COPIES)]
        self.cases(differ, THREE, "a")
        self.cases(as_one, THREE, "a")
        self.cases(as_one, ONE, "a")

    def test_copies_whose_records_differ_only_in_key_order_are_one_history(self):
        root, c = self.root, self.c
        try:
            rewrite(c, lambda events: events.__setitem__(slice(None), [dict(reversed(list(e.items()))) for e in events]))
            self.assertNotEqual(journal_bytes(c), self.journal)
            self.assertEqual((c.status(), c.events(TASK)), (LANDED, on_main(root)))
        finally:
            self.put_back(False)

    def test_two_rulings_for_one_card_in_one_history_block_though_the_copies_agree(self):
        def again(dispute):
            def change(events):
                ruling = the("ruling.made", dispute=dispute)(events)
                events.insert(events.index(ruling) + 1, dict(ruling))
            return change

        self.cases([(again(ONE), "both", f"{ONE} has more than one ruling.made"),
                    (again(THREE), "both", f"{THREE} has more than one ruling.made")], THREE, "a")

    def test_a_landed_history_that_does_not_read_gives_the_next_task_no_precedent(self):
        root, c = self.root, self.c
        marker = (f"claude's reveal.done is a confirmed-v1 record, but {TASK} was not opened confirmed-v1",
                  f"codex's reveal.done is a confirmed-v1 record, but {TASK} was not opened confirmed-v1")
        for number, (change, details) in enumerate((
                (lambda events: events.remove(the("contract.frozen", version=2)(events)), (MISSING,)),
                (lambda events: the("task.opened")(events).pop("batch_protocol"), marker),
                (lambda events: events.remove(the("task.opened")(events)),
                 (f"{TASK} has confirmed-v1 records and no task.opened",)))):
            with self.subTest(case=number):
                try:
                    c.journal.path.write_bytes(b"")         # the cleanup finished: only main's ledger holds the task
                    rewrite_main(root, change)
                    [row] = c.status()
                    self.assertEqual(row["status"], "blocked")
                    self.assertIn(row["detail"], details)
                    if number == 0:                         # through a second task's run: no seat is called
                        codex, claude = agreeing()
                        c2, codex, claude = seated(root, c, codex.script, claude.script)
                        self.assertEqual(told(c2.run(root / NEXT_FILE, stop_after="contract")),
                                         ("blocked", NO_PRECEDENT + MISSING))
                        self.assertEqual((codex.calls, claude.calls), ([], []))
                    no_precedent(self, root, c, self.t, row["detail"])
                finally:
                    self.put_back(True)


class Precedents(unittest.TestCase):
    """Another task's rulings are precedents only while its history reads as its writer left it."""

    def source(self):
        """A confirmed-v1 task with a ruling scoped to the project and contract v1 frozen, still live."""
        root, c, t, settled = ruled_cards(self)
        self.assertEqual(told(c.run(root / TASK_FILE, stop_after="contract")), ("stopped", "stopped after the contract was frozen"))
        self.assertEqual([p["id"] for p in decisions.precedents(c.events())], ["P-1"])
        return root, c

    @staticmethod
    def unruled(events):
        """The history loses both rulings: no precedent is left to number, and the freeze follows unruled cards."""
        events[:] = [e for e in events if e["type"] != "ruling.made"]

    def refused(self, root, c, codex, claude, detail, calls=0, stop_after="contract"):
        """The second task's run is blocked with the source's diagnostic, and calls no seat it had not called.
        Its seats hold the steps a run that is not refused would take up to `stop_after`, and a run that raises
        fails the test."""
        journal, head = journal_bytes(c), gitops.rev(root, "main")
        try:
            outcome = c.run(root / NEXT_FILE, builder="codex", stop_after=stop_after)
        except Exception as error:
            raise AssertionError(f"the run raised {error!r}") from error
        self.assertEqual(told(outcome), ("blocked", NO_PRECEDENT + detail))
        self.assertEqual((len(codex.calls), len(claude.calls), journal_bytes(c), gitops.rev(root, "main")),
                         (calls, calls, journal, head))

    def killed(self, c, root, method):
        with mock.patch.object(Conductor, method, side_effect=RuntimeError(f"killed at {method}")) as stage:
            with self.assertRaisesRegex(RuntimeError, f"killed at {method}"):
                c.run(root / NEXT_FILE, builder="codex")
        self.assertEqual(stage.call_count, 1)

    def test_a_reading_is_not_asked_for_under_a_ruling_of_a_history_that_does_not_read(self):
        opening = f"{TASK}'s task.opened has batch_protocol confirmed-v1 and no "
        for change, detail in (
                (self.unruled, None),
                (lambda events: the("ruling.made", dispute=ONE)(events).update(text="Anything."), None),
                # The opening lost its marker, a field `_task_of` reads, or went missing: the records still say
                # confirmed-v1, and are not read as an older task's.
                (lambda events: the("task.opened")(events).pop("batch_protocol"), None),
                (lambda events: the("task.opened")(events).pop("title"), opening + "title"),
                (lambda events: the("task.opened")(events).update(builder=None), opening + "builder"),
                (lambda events: events.remove(the("task.opened")(events)),
                 f"{TASK} has confirmed-v1 records and no task.opened")):
            with self.subTest(detail=detail):
                root, c = self.source()
                rewrite(c, change)
                try:
                    [row] = c.status()
                except Exception as error:
                    raise AssertionError(f"status raised {error!r}") from error
                self.assertEqual((row["status"], row.get("detail")), ("blocked", detail or row.get("detail")))
                codex, claude = agreeing()
                c2, codex, claude = seated(root, c, codex.script, claude.script)
                c2._open(NEXT, (root / NEXT_FILE).read_text(encoding="utf-8"), "codex")
                self.refused(root, c2, codex, claude, row["detail"])

    def test_a_ruling_from_before_the_marker_is_a_precedent_unchecked(self):
        # A project ruling in main's ledger with no opening and no confirmed-v1 record: read as it always was.
        root = make_project(); codex, claude = agreeing()
        c = kit_conductor(root, codex, claude)
        old = {"ts": "2026-11-01T00:00:00Z", "type": "ruling.made", "task": "old-001", "dispute": "D-old-001-1",
               "kind": "reading", "question": "What if lo > hi?", "choice": "a", "text": "Raise ValueError.",
               "scope": "project", "while": "", "limitation": ""}
        (root / LEDGER).parent.mkdir(parents=True, exist_ok=True)
        (root / LEDGER).write_text("", encoding="utf-8")
        rewrite_main(root, lambda events: events.append(old))
        self.assertEqual(c.run(root / TASK_FILE, stop_after="contract").status, "stopped")
        self.assertEqual(precedents_read(codex), briefs._precedents(precedents([old])))

    def test_a_packet_does_not_pin_a_ruling_of_a_history_that_does_not_read(self):
        root, c = self.source()
        c2, codex, claude = seated(
            root, c, {"reading": [answers(ROLE_READINGS["builder"])], "reveal": [answers(ROLE_REVEALS["builder"])],
                      "batch_propose": [proposes()]},
            {"reading": [answers(ROLE_READINGS["challenger"])], "reveal": [answers(ROLE_REVEALS["challenger"])],
             "batch_review": [reviews()]})
        c2._open(NEXT, (root / NEXT_FILE).read_text(encoding="utf-8"), "codex", batch=True)
        self.killed(c2, root, "_batch_packet")
        rewrite(c, self.unruled)
        self.refused(root, c2, codex, claude, c.status()[0]["detail"], calls=2)

    def test_a_contract_is_not_frozen_under_a_ruling_of_a_history_that_does_not_read(self):
        root, c = self.source()
        codex, claude = agreeing()
        c2, codex, claude = seated(root, c, codex.script, claude.script)
        self.killed(c2, root, "_freeze")
        rewrite(c, self.unruled)
        self.refused(root, c2, codex, claude, c.status()[0]["detail"], calls=2)

    def test_a_landing_does_not_write_a_ruling_of_a_history_that_does_not_read_into_the_precedents(self):
        root, c = self.source()
        codex, claude = seats([builds()], [probes()])
        c2, codex, claude = seated(root, c, codex.script, claude.script)
        self.killed(c2, root, "_integrate")
        rewrite(c, self.unruled)
        self.refused(root, c2, codex, claude, c.status()[0]["detail"], calls=3, stop_after=None)


class Boundary(unittest.TestCase):
    def test_a_waiver_names_the_mutant_its_own_tasks_crossing_reserved(self):
        root, c, t, settled = ruled_cards(self)
        c2, codex, claude = seated(root, c, {"build": [builds()]},
                                   {"probe": [probes(WEAK_PROBES)], "respond": [responds("contest")]})
        self.assertEqual(told(run(c2, root)), ("needs_ruling", f"needs a ruling on {THREE}"))
        self.assertEqual(last("crossing.done")(c2.events(TASK))["mutant_of"], {THREE: "m1"})
        # Another task's crossing record claims the same ID for another mutant, later in the journal.
        c2.journal.append("crossing.done", "other-001", mutant_of={THREE: "m9"})
        self.assertEqual(rule(root, THREE, "b")[0], 0)
        self.assertEqual(last("ruling.made")(c2.events(TASK))["limitation"], "mutant m1 waived")
        [row, other] = c2.status()
        self.assertEqual(row, {"task": TASK, "status": "in_progress", "pending": []})


if __name__ == "__main__":
    unittest.main()
