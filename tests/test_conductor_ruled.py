import json, unittest
from parallax import batch, decisions
from parallax.decisions import Dispute
from tests.test_batch import ALIAS_FALLBACK
from tests.test_cli import call
from tests.test_conductor_batch import proposes, reviews
from tests.test_conductor_reading import resumed
from tests.test_conductor_settled import (ALIAS_REFUSE, INDENTED_READINGS, NEEDS_ONE, TASK, marked, run, settlements,
                                          told, two_cards)

# Task 19.6. A confirmed-v1 settlement's public rows are ruled through the seat-free `rule`: the task is the
# one whose reading.settled holds the ID, checked as run checks it; the command must be one the card allows;
# what is stored is exactly `batch.ruling`'s record, and every reader refuses a stored ruling that is not.
# Run still stops after the settlement once every card is ruled (freezing is Task 19.7).
ONE, TWO = "D-clamp-001-1", "D-clamp-001-2"
STOPPED = ("stopped", "stopped after the confirmed settlement")
# Policy first: the two names may come in either order.
WHOLE = '{"policy": "Raise ValueError when hi < lo.", "interface": "clamp(x, lo, hi) -> number"}'

def rule(root, dispute, *args):
    """The CLI's rule: (exit code, stdout, stderr), or ("raised", the exception) if one escapes the CLI."""
    try:
        return call("rule", dispute, *args, "--repo", str(root))
    except Exception as error:
        return "raised", repr(error)

def ruled(c):
    return [e for e in c.events(TASK) if e["type"] == "ruling.made"]

def stored(event):
    return {field: event[field] for field in event if field not in ("ts", "type", "task")}

def refusal():
    """A published refusal: one combined card allowing other and drop."""
    root, c, t, codex, claude = marked(propose=proposes(fallback=ALIAS_FALLBACK), review=reviews(ALIAS_REFUSE),
                                       readings=INDENTED_READINGS)
    outcome = run(c, root)
    assert told(outcome) == NEEDS_ONE, told(outcome)
    return root, c, t, settlements(c)[0]


class Rule(unittest.TestCase):
    def test_a_card_ruled_through_the_cli_leaves_only_its_sibling_pending_after_a_restart(self):
        root, c, t, settled = two_cards(self)
        first, second = settled["choices"]
        self.assertEqual(rule(root, ONE, "b"), (0, f"recorded {ONE}: b\ncontinue with: parallax run TASK_FILE\n", ""))
        [event] = ruled(c)
        self.assertEqual(stored(event), {
            "dispute": ONE, "kind": "reading", "question": first["question"], "choice": "b",
            "text": first["b"]["policy"], "scope": "project", "while": "", "limitation": "",
            "batch_protocol": "confirmed-v1", "settlement_sha": settled["settlement_sha"], "slot": "c/0",
            "members": first["members"], "value": first["b"]})
        self.assertEqual(list(stored(event)), list(batch.RULING_FIELDS))
        c2, codex, claude = resumed(root, c)
        outcome = run(c2, root)
        self.assertEqual((told(outcome), outcome.cards), (("needs_ruling", f"needs a ruling on {TWO}"), (second,)))
        self.assertEqual(c2.status(), [{"task": TASK, "status": "needs_ruling", "pending": [TWO]}])
        self.assertEqual(rule(root, TWO, "a")[0], 0)
        self.assertEqual((stored(ruled(c)[1])["scope"], stored(ruled(c)[1])["text"], stored(ruled(c)[1])["value"]),
                         ("task", second["a"]["interface"], second["a"]))
        c3, codex3, claude3 = resumed(root, c)
        self.assertEqual(told(run(c3, root)), STOPPED)
        self.assertEqual(c3.status(), [{"task": TASK, "status": "in_progress", "pending": []}])
        self.assertEqual((codex.calls, claude.calls, codex3.calls, claude3.calls), ([], [], [], []))

    def test_a_repeat_ruling_fails_with_no_append(self):
        root, c, t, settled = two_cards(self)
        self.assertEqual(rule(root, ONE, "a")[0], 0)
        journal = c.journal.path.read_bytes()
        self.assertEqual(rule(root, ONE, "b"), (1, "", f"parallax: {ONE} is already ruled\n"))
        self.assertEqual(c.journal.path.read_bytes(), journal)

    def test_only_a_command_and_note_the_card_allows_is_recorded(self):
        root, c, t, settled = two_cards(self)
        journal = c.journal.path.read_bytes()
        cases = [((ONE, "drop"), f"{ONE} allows a, b, other, not 'drop'"),
                 ((ONE, "other"), "choice 'other' needs a note"),
                 ((ONE, "other", "--note", "  \n"), "choice 'other' needs a note"),
                 ((ONE, "a", "--note", "strict"), "choice 'a' takes no note: the card's a column is the ruling"),
                 (("builder/0", "a"), "unknown dispute builder/0"),
                 (("c/0", "a"), "unknown dispute c/0"),
                 (("D-clamp-001-3", "a"), "unknown dispute D-clamp-001-3")]
        for args, detail in cases:
            with self.subTest(args=args):
                self.assertEqual(rule(root, *args), (1, "", f"parallax: {detail}\n"))
                self.assertEqual(c.journal.path.read_bytes(), journal)
        with self.assertRaises(ValueError) as caught:
            c.rule(ONE, "a", scope="everywhere")
        self.assertEqual(str(caught.exception), "scope must be 'task' or 'project', not 'everywhere'")
        self.assertEqual(c.journal.path.read_bytes(), journal)

    def test_other_records_the_note_as_the_cards_target_with_its_scope(self):
        root, c, t, settled = two_cards(self)
        policy = "Raise ValueError unless lo <= hi.\n  NaN bounds raise too.\n"
        self.assertEqual(rule(root, ONE, "other", "--note", policy, "--while", "lo and hi are numbers")[0], 0)
        self.assertEqual(rule(root, TWO, "other", "--note", "clip(x, lo, hi)", "--scope", "project")[0], 0)
        first, second = (stored(e) for e in ruled(c))
        self.assertEqual((first["text"], first["value"], first["scope"], first["while"]),
                         (policy, {"interface": "", "policy": policy}, "project", "lo and hi are numbers"))
        self.assertEqual((second["text"], second["value"], second["scope"]),
                         ("clip(x, lo, hi)", {"interface": "clip(x, lo, hi)", "policy": ""}, "project"))
        c2, codex, claude = resumed(root, c)
        self.assertEqual(told(run(c2, root)), STOPPED)

    def test_a_refusal_takes_one_combined_note(self):
        root, c, t, settled = refusal()
        [row] = settled["choices"]
        journal = c.journal.path.read_bytes()
        bad = ["clamp(x, lo, hi)", '{"interface": "clamp(x, lo, hi)"}', '{"interface": "clamp(x, lo, hi)", "policy": " "}',
               '{"interface": "f", "policy": "p", "why": "w"}', '["clamp(x, lo, hi)", "raise"]',
               '{"interface": 1, "policy": "p"}', '{"interface": "f", "policy": "first", "policy": "last"}']
        combined = ('parallax: a combined note must be one JSON object with exactly the string fields "interface" and '
                    '"policy", neither blank\n')
        for note in bad:
            with self.subTest(note=note):
                self.assertEqual(rule(root, ONE, "other", "--note", note), (1, "", combined))
        for choice in ("a", "b"):
            with self.subTest(choice=choice):
                self.assertEqual(rule(root, ONE, choice), (1, "", f"parallax: {ONE} allows other, drop, not '{choice}'\n"))
        self.assertEqual(c.journal.path.read_bytes(), journal)
        self.assertEqual(rule(root, ONE, "other", "--note", WHOLE, "--scope", "project")[0], 0)
        value = {"interface": "clamp(x, lo, hi) -> number", "policy": "Raise ValueError when hi < lo."}
        text = "Interface:\nclamp(x, lo, hi) -> number\nPolicy:\nRaise ValueError when hi < lo."
        [event] = ruled(c)
        self.assertEqual((event["kind"], event["value"], list(event["value"]), event["text"], event["scope"],
                          event["members"]), ("refusal", value, ["interface", "policy"], text, "project", row["members"]))
        # One P-number for one ruling, however many source terms it replaces.
        self.assertEqual(decisions.precedents(c.events()), [{"id": "P-1", "question": row["question"], "ruling": text,
                                                              "while": "", "task": TASK}])
        c2, codex, claude = resumed(root, c)
        self.assertEqual(told(run(c2, root)), STOPPED)

    def test_a_ruling_whose_words_are_not_utf_8_text_is_refused(self):
        # A JSON escape can carry a lone surrogate into a note no UTF-8 contract or precedent file can hold.
        root, c, t, settled = refusal()
        journal = c.journal.path.read_bytes()
        self.assertEqual(rule(root, ONE, "other", "--note", r'{"interface": "f", "policy": "\ud800"}'),
                         (1, "", "parallax: the ruling's text is not UTF-8 text\n"))
        self.assertEqual(rule(root, ONE, "other", "--note", WHOLE, "--while", "\ud800"),
                         (1, "", "parallax: the ruling's while is not UTF-8 text\n"))
        self.assertEqual(c.journal.path.read_bytes(), journal)
        arrow = "clamp(x, lo, hi) → number"
        self.assertEqual(rule(root, ONE, "other", "--note", json.dumps({"interface": arrow, "policy": "Raise."},
                                                                      ensure_ascii=False))[0], 0)
        self.assertEqual(ruled(c)[0]["value"], {"interface": arrow, "policy": "Raise."})

    def test_a_refusal_override_defaults_to_task_and_drop_is_always_task(self):
        for args, scope, text in (((), "task", None), (("--scope", "project", "--note", "  out of scope  "), "task",
                                                       "out of scope")):
            with self.subTest(args=args):
                root, c, t, settled = refusal()
                self.assertEqual(rule(root, ONE, "drop", *args)[0], 0)
                [event] = ruled(c)
                self.assertEqual((event["value"], event["text"], event["scope"]),
                                 ({"interface": "", "policy": ""}, text or "Drop this task.", scope))
                self.assertEqual(decisions.precedents(c.events()), [])
                self.assertEqual(c.status(), [{"task": TASK, "status": "in_progress", "pending": []}])
        root, c, t, settled = refusal()
        self.assertEqual(rule(root, ONE, "other", "--note", WHOLE)[0], 0)
        self.assertEqual(ruled(c)[0]["scope"], "task")

    def test_a_stored_ruling_rule_would_not_write_blocks_every_reader(self):
        root, c, t, settled = two_cards(self)
        first, second = settled["choices"]
        good = batch.ruling(settled, first, "a")
        cases = [
            ("kind", {**good, "kind": "interface"}, "has a kind its card does not give"),
            ("question", {**good, "question": "What if lo > hi?"}, "has a question its card does not give"),
            ("choice", {**good, "choice": "drop"}, f"is not one rule writes: {ONE} allows a, b, other, not 'drop'"),
            ("value", {**good, "value": first["b"]}, "has a value its card does not give"),
            ("text", {**good, "text": first["b"]["policy"]}, "has a text its card does not give"),
            ("scope", {**good, "scope": "global"}, "is not one rule writes: scope must be 'task' or 'project', not 'global'"),
            ("slot", {**good, "slot": "c/1"}, "has a slot its card does not give"),
            ("members", {**good, "members": first["members"][::-1]}, "has a members its card does not give"),
            ("limitation", {k: v for k, v in good.items() if k != "limitation"},
             "is not one rule writes: note, while and limitation must be text"),
            ("extra field", {**good, "note": "x"}, f"has the fields {', '.join([*batch.RULING_FIELDS, 'note'])}, "
                                                    f"not {', '.join(batch.RULING_FIELDS)}"),
            ("blank other", {**good, "choice": "other", "value": {"interface": "", "policy": " "}, "text": " "},
             "is not one rule writes: choice 'other' needs a note"),
            ("other value", {**good, "choice": "other", "value": {"interface": "f", "policy": "p"}, "text": "p"},
             "has a value its card does not give"),
            ("other value not an object", {**good, "choice": "other", "value": "p", "text": "p"},
             "is not one rule writes: note, while and limitation must be text"),
            ("not UTF-8", {**good, "choice": "other", "value": {"interface": "", "policy": "\ud800"}, "text": "\ud800"},
             "is not one rule writes: the ruling's text is not UTF-8 text"),
            ("field order", dict(reversed(list(good.items()))),
             f"has the fields {', '.join(reversed(batch.RULING_FIELDS))}, not {', '.join(batch.RULING_FIELDS)}"),
        ]
        for name, fields, problem in cases:
            with self.subTest(name):
                root, c, t, settled = two_cards(self)
                c.journal.append("ruling.made", TASK, **fields)
                detail = f"{ONE}'s ruling.made {problem}"
                c2, codex, claude = resumed(root, c)
                journal = c2.journal.path.read_bytes()
                self.assertEqual(told(run(c2, root)), ("blocked", detail))
                self.assertEqual(c2.status(), [{"task": TASK, "status": "blocked", "pending": [], "detail": detail,
                                                "affected": []}])
                self.assertEqual(rule(root, TWO, "a"), (1, "", f"parallax: {detail}\n"))
                self.assertEqual((codex.calls, claude.calls, c2.journal.path.read_bytes()), ([], [], journal))

    def test_a_card_id_two_tasks_claim_or_an_unopened_task_holds_is_not_ruled(self):
        root, c, t, settled = two_cards(self)
        c.journal.append("reading.settled", "clamp-002", choices=[{"id": ONE}, {"id": "D-clamp-002-1"}])
        journal = c.journal.path.read_bytes()
        self.assertEqual(rule(root, ONE, "a"), (1, "", f"parallax: {ONE} is a card of more than one task's "
                                                       "reading.settled: clamp-001, clamp-002\n"))
        self.assertEqual(rule(root, "D-clamp-002-1", "a"),
                         (1, "", "parallax: clamp-002's reading.settled has no task.opened\n"))
        self.assertEqual(c.journal.path.read_bytes(), journal)

    def test_a_card_under_an_unmarked_opening_is_not_ruled_nor_a_legacy_card_beside_it(self):
        root, c, t, settled = two_cards(self)
        events = c.journal.path.read_text(encoding="utf-8").splitlines(keepends=True)
        opened = json.loads(events[0])
        del opened["batch_protocol"]
        c.journal.path.write_text(json.dumps(opened) + "\n" + "".join(events[1:]), encoding="utf-8")
        # A legacy card on the same task: no settlement holds its ID, and run refuses the task all the same.
        card = Dispute("D-clamp-001-9", "reading", "What if lo > hi?", "Raise ValueError when hi < lo.",
                       "Raise ValueError unless lo <= hi.", "codex (builder)", "claude (challenger)")
        c.journal.append("dispute.opened", TASK, **card.to_fields())
        journal = c.journal.path.read_bytes()
        [row] = c.status()
        self.assertEqual(row["status"], "blocked")
        self.assertIn("was not opened confirmed-v1", row["detail"])
        for dispute in (ONE, "D-clamp-001-9"):
            with self.subTest(dispute=dispute):
                self.assertEqual(rule(root, dispute, "a"), (1, "", f"parallax: {row['detail']}\n"))
        self.assertEqual(c.journal.path.read_bytes(), journal)


class Numbering(unittest.TestCase):
    def test_card_ids_count_in_the_task_numbering_ruled_or_not(self):
        root, c, t, settled = two_cards(self)
        self.assertEqual(c._next_dispute_number(t), 3)
        self.assertEqual(rule(root, ONE, "a")[0], 0)
        self.assertEqual(c._next_dispute_number(t), 3)

    def test_a_project_reading_ruling_is_one_precedent_and_an_interface_ruling_none(self):
        root, c, t, settled = two_cards(self)
        first, second = settled["choices"]
        self.assertEqual(rule(root, ONE, "b", "--while", "lo and hi are numbers")[0], 0)
        self.assertEqual(rule(root, TWO, "a")[0], 0)
        precedents = decisions.precedents(c.events())
        self.assertEqual(precedents, [{"id": "P-1", "question": first["question"], "ruling": first["b"]["policy"],
                                       "while": "lo and hi are numbers", "task": TASK}])
        self.assertIn(f"**P-1** ({TASK}) {first['question']} -> {first['b']['policy']} (while: lo and hi are numbers)",
                      decisions.render_precedents(precedents))
