import contextlib, copy, io, json, unittest
from pathlib import Path
from unittest import mock
from parallax import batch, cli, conductor, decisions
from parallax.conductor import Conductor, Outcome
from parallax.config import repo_key
from parallax.ledger import parse_lines
from parallax.seats.stub import StubSeat
from tests.conductor_kit import interface_section, kit_conductor, make_project, reading, reveal
from tests.test_batch import (ALIAS_FALLBACK, ALIAS_REVEALS, FALLBACK, INPUTS, INTERFACE_TERM, MOVED, PROPOSAL, REFUSE,
                              REFUSED_PROPOSAL, REVIEW, SEATS, TWO_CHOICES, TWO_REVIEW, WITHDRAWAL, changed,
                              one_dispute)
from tests.test_cli import call
from tests.test_conductor_batch import evidence, proposes, reviews
from tests.test_conductor_marked import seeded
from tests.test_conductor_reading import contract_text, open_unmarked, resumed
from tests.test_decisions import ROLE_READINGS, ROLE_REVEALS

# Task 19.5. A marked task (opened with `_open(..., batch=True)`, which only tests do until Task 19.7) runs
# through its reveals, settles, publishes one reading.settled, and stops at its pending cards or after the
# settlement. The builder is codex. Task 19.3's fixtures give one pending policy choice (CHOICE) by default.
TASK = "clamp-001"
TASK_FILE = "tasks/clamp-001.md"
ENVELOPE = ["ts", "type", "task"]
FIELDS = ["batch_protocol", "interface_protocol", "mode", "packet_sha", "proposal_sha", "review_sha", "direct_packet",
          "common", "withdrawn", "proposal", "review", "choices", "refusal_reason", "affected", "detail", "settlement_sha"]
ROW_FIELDS = ["slot", "target", "kind", "question", "members", "a", "b", "witnesses", "resolution", "selected", "id",
              "allowed", "card_text"]
# Written by hand from Task 19.1's role-keyed readings and reveals and Task 19.3's PROPOSAL and REVIEW: each
# position under the seat that holds it, with its reason; each original witness under its author, with its
# citation; both votes and their reasons; and the prediction both seats confirmed.
CARD = """Dispute D-clamp-001-1 (reading)

Which predicate rejects the bounds?

a) codex (builder):
| Raise ValueError when hi < lo.
b) claude (challenger):
| Raise ValueError unless lo <= hi.
other) Supply the policy with --note.

Votes:
- codex (builder) signs a: strict comparisons
- claude (challenger) signs b: NaN bounds must raise

Sources:
- builder/0: What if lo > hi?
  codex (builder): Raise ValueError when hi < lo.
    why: caller error
  claude (challenger): Raise ValueError unless lo <= hi.
    why: NaN bounds
  witness from claude (challenger): clamp(8, float('nan'), 5) (result or exception): codex (builder) returns 5; claude (challenger) raises ValueError
- challenger/0: What if lo > hi?
  claude (challenger): Raise ValueError unless lo <= hi.
    why: NaN bounds too
  codex (builder): Raise ValueError when hi < lo.
    why: strict only
  witness from codex (builder): clamp(1, Lt(0), Lt(2)) with objects defining only __lt__ (result or exception): codex (builder) returns 1; claude (challenger) raises TypeError
    decided by: What is returned?

Predictions both seats confirmed:
- builder/0: clamp(8, float('nan'), 5) (result or exception): a) returns 5 b) raises ValueError

parallax rule D-clamp-001-1 a
"""
# The agreed builder/1 moved into the choice: the common terms keep only the interface, and the choice asks
# both questions, one policy keeping the original-object guarantee and the other allowing an equal copy.
MOVED_QUESTION = "Which predicate rejects the bounds, and must the result be one of the objects passed?"
MOVED_A = "Raise ValueError when hi < lo. Return one of the objects passed, never a copy."
MOVED_B = "Raise ValueError unless lo <= hi. An equal copy may be returned."
MOVED_PROPOSAL = changed(PROPOSAL, common=[INTERFACE_TERM], withdrawn=[WITHDRAWAL], choices=[
    {**MOVED, "question": MOVED_QUESTION, "a": {"interface": "", "policy": MOVED_A},
     "b": {"interface": "", "policy": MOVED_B}}])
# CARD for MOVED_PROPOSAL: its question and columns, builder/1 under its owner with its agreement shown as
# original, and the challenger's withdrawal with its reason and destination.
MOVED_CARD = (CARD.replace("\nWhich predicate rejects the bounds?\n", f"\n{MOVED_QUESTION}\n")
              .replace("\n| Raise ValueError when hi < lo.\n", f"\n| {MOVED_A}\n")
              .replace("\n| Raise ValueError unless lo <= hi.\n", f"\n| {MOVED_B}\n")
              .replace("""    decided by: What is returned?

Predictions""", """    decided by: What is returned?
- builder/1: What is returned?
  codex (builder), originally agreed by both seats: One of the objects passed.
    why: identity
  withdrawn by claude (challenger), now in c/0: identity now depends on the predicate

Predictions"""))
# The refusal of a fallback holding both disputed readings and the agreed interface, written by hand: every
# replaced source by key (the agreed interface superseded, under its owner), the surviving term by key with
# its question and its text exactly (indentation and the final line break kept), what the one replacement
# covers, and the combined form's JSON template.
REFUSAL_CARD = """Dispute D-clamp-001-1 (refusal)

What complete interface and bounds predicate should clamplib have?

The seats did not settle these terms. Replace all of them with one ruling, or drop the task.

Reasons:
challenger: the predicate decides what the interface must accept

Replaced by the ruling:
- builder/0: What if lo > hi?
  codex (builder): Raise ValueError when hi < lo.
    why: caller error
  claude (challenger): Raise ValueError unless lo <= hi.
    why: NaN bounds
  witness from claude (challenger): clamp(8, float('nan'), 5) (result or exception): codex (builder) returns 5; claude (challenger) raises ValueError
- challenger/0: What if lo > hi?
  claude (challenger): Raise ValueError unless lo <= hi.
    why: NaN bounds too
  codex (builder): Raise ValueError when hi < lo.
    why: strict only
  witness from codex (builder): clamp(1, Lt(0), Lt(2)) with objects defining only __lt__ (result or exception): codex (builder) returns 1; claude (challenger) raises TypeError
    decided by: What is returned?
- builder/interface: What interface should the contract use?
  codex (builder), agreed by both seats, superseded: clamp(x, lo, hi)

Kept as written:
- builder/1:
  question:
  |  What is returned?
  text:
  | One of the objects passed:
  |     x, lo or hi
  |

The ruling covers: builder/0, challenger/0, builder/interface
other) Supply both in one --note holding a JSON object: {"interface": "...", "policy": "..."}
drop) Drop this task.

parallax rule D-clamp-001-1 other --note TEXT
"""
NEEDS_ONE = ("needs_ruling", "needs a ruling on D-clamp-001-1")
FROZEN = ("stopped", "stopped after the contract was frozen")
# Both choices of Task 19.3's two-choice batch held apart: two pending cards, a policy and an interface.
TWO_PENDING = changed(TWO_CHOICES, votes=[{"slot": "c/0", "sign": ["a"], "reason": "strict comparisons"},
                                          {"slot": "c/1", "sign": ["a"], "reason": "one name is enough"}],
                      preferences=[{"slot": "c/0", "answer": "a"}, {"slot": "c/1", "answer": "a"}])
TWO_PENDING_REVIEW = changed(TWO_REVIEW, votes=[{"slot": "c/0", "sign": ["b"], "reason": "NaN bounds must raise"},
                                                {"slot": "c/1", "sign": ["b"], "reason": "callers want clip"}])
# The same two choices with c/0 settled by both seats: an automatic row, then one public card for c/1.
AUTO_THEN_PENDING_REVIEW = changed(TWO_REVIEW, votes=[{"slot": "c/0", "sign": ["a"], "reason": "strict is fine"},
                                                      {"slot": "c/1", "sign": ["b"], "reason": "callers want clip"}])
MUTUAL = changed(PROPOSAL, votes=[{**PROPOSAL["votes"][0], "sign": ["a"]}])
MUTUAL_REVIEW = changed(REVIEW, votes=[{**REVIEW["votes"][0], "sign": ["a"]}])
BLOCKED = ("the confirmed settlement is blocked: the fallback leaves out builder/1; affected: builder/1")
RECORD = "the reading.settled record "
ZERO = "sha256:" + "0" * 64
# The combined refusal: the challenger names the consumed predicate, not the surviving identity term.
ALIAS_REFUSE = changed(REFUSE, affected=["builder/0"], fallback_complete=True,
                       refusal_reason="the predicate decides what the interface must accept")
# The surviving builder/1 with indentation, a line break and a final newline, all of which a ruling keeps.
INDENTED_READINGS = copy.deepcopy(ROLE_READINGS)
INDENTED_READINGS["builder"]["decisions"][1]["answer"] = "One of the objects passed:\n    x, lo or hi\n"

def quoted_witness(scenario):
    """One direct dispute whose challenger witness has `scenario`."""
    reveals = copy.deepcopy(one_dispute())
    for verdict in reveals["challenger"]["verdicts"]:
        if verdict["index"] == 0:
            verdict["witness"]["scenario"] = scenario
    return reveals

# An unclosed quoted path and a space: trimming and scrubbing it disagree in order, so the writer and replay
# must derive the row the same way.
QUOTED_REVEALS = quoted_witness('read "C:\\dir\\file.txt ')
# Two backslashes, a POSIX path and a space: the first scrub exposes a share path (the backslashes before
# `<outside>`), so only a value scrubbed until it stops changing is stable.
TWICE = 'read "' + "\\" * 2 + '/home/me/file.txt '
TWICE_REVEALS = quoted_witness(TWICE)

def answers(reply):
    return lambda req: copy.deepcopy(reply)

def marked(reveals=ROLE_REVEALS, propose=None, review=None, readings=ROLE_READINGS):
    """A project whose task is opened confirmed-v1, with stub seats that read, reveal and run the batch calls."""
    root = make_project()
    codex = StubSeat("codex", {"reading": [answers(readings["builder"])], "reveal": [answers(reveals["builder"])],
                               "batch_propose": [propose or proposes()]})
    claude = StubSeat("claude", {"reading": [answers(readings["challenger"])],
                                 "reveal": [answers(reveals["challenger"])], "batch_review": [review or reviews()]})
    c = kit_conductor(root, codex, claude)
    t = c._open(TASK, (root / TASK_FILE).read_text(encoding="utf-8"), "codex", batch=True)
    return root, c, t, codex, claude

def two_cards(test):
    root, c, t, codex, claude = marked(reveals=ALIAS_REVEALS, propose=proposes(TWO_PENDING),
                                       review=reviews(TWO_PENDING_REVIEW))
    test.assertEqual(told(run(c, root)), ("needs_ruling", "needs a ruling on D-clamp-001-1, D-clamp-001-2"))
    return root, c, t, settlements(c)[0]

def run(c, root):
    """The outcome of a run. A run that raises fails the test instead of erroring it."""
    try:
        return c.run(root / TASK_FILE)
    except Exception as error:
        raise AssertionError(f"the run raised {error!r}") from error

def told(outcome):
    return outcome.status, outcome.detail

def settlements(c):
    return [e for e in c.events(TASK) if e["type"] == "reading.settled"]

def card_path(root, dispute):
    return root / ".parallax/run" / TASK / "cards" / f"{dispute}.md"

def private_reads():
    """Fails any read of a stored seat output: what a restart after publication may not do."""
    return mock.patch.object(Conductor, "_stored", side_effect=AssertionError("a private artifact was read"))

def rewrite(c, change):
    """Rewrite the journal as a hand edit would: `change` mutates the list of events in place."""
    path = c.journal.path
    events = parse_lines(path.read_text(encoding="utf-8"))
    change(events)
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8", newline="\n")

def resealed(event):
    """`event` (a reading.settled) with its settlement_sha recomputed, as a forger would."""
    body = {k: v for k, v in event.items() if k not in ("ts", "type", "task", "settlement_sha")}
    event["settlement_sha"] = batch.digest({"task": event["task"], **body})

def edit_settled(change, reseal=True):
    def apply(events):
        for event in events:
            if event["type"] == "reading.settled":
                change(event)
                if reseal:
                    resealed(event)
    return apply

def of(events, kind):
    return next(e for e in events if e["type"] == kind)

def rechained(change):
    """A forger's edit of the settlement's copied proposal or review (`change(settled)`), with every hash that
    depends on them repaired: the review's predecessor, both checkpoint shas, the record's shas and its digest."""
    def apply(events):
        settled, proposed, reviewed = of(events, "reading.settled"), of(events, "batch.proposed"), of(events, "batch.reviewed")
        change(settled)
        proposal_sha = batch.digest(settled["proposal"])
        settled["review"]["proposal_sha"] = proposal_sha
        review_sha = batch.digest(settled["review"])
        proposed["sha"] = reviewed["proposal_sha"] = settled["proposal_sha"] = proposal_sha
        reviewed["sha"] = settled["review_sha"] = review_sha
        resealed(settled)
    return apply

def direct_packet_edit(change):
    """A forger's edit of a direct settlement's packet, with its packet_sha and digest repaired."""
    def apply(settled):
        change(settled["direct_packet"])
        settled["packet_sha"] = batch.digest(settled["direct_packet"])
    return edit_settled(apply)

def ruling(settled, row, choice="a", **extra):
    """A ruling.made bound to `settled` for `row`, seeded as Task 19.6 will write one."""
    fields = {"dispute": row["id"], "kind": row["kind"], "question": row["question"], "choice": choice,
              "text": row[choice]["policy"] or row[choice]["interface"], "scope": "project", "while": "",
              "limitation": "", "batch_protocol": "confirmed-v1", "settlement_sha": settled["settlement_sha"],
              "slot": row["slot"], "members": row["members"], "value": row[choice]}
    return {**fields, **extra}

def printed(call_, *args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = call_(*args)
    return code, out.getvalue()


class Publish(unittest.TestCase):
    def assert_blocked_on_restart(self, root, c, detail, cards=("D-clamp-001-1",)):
        """A restart after `c`'s run: run and status block with `detail`, no ID, no call, no append, no card."""
        for name in cards:
            card_path(root, name).unlink(missing_ok=True)
        c2, codex2, claude2 = resumed(root, c)
        journal = c2.journal.path.read_bytes()
        outcome = run(c2, root)
        self.assertEqual((told(outcome), outcome.cards), (("blocked", detail), ()))
        self.assertEqual(c2.status(), [{"task": TASK, "status": "blocked", "pending": [], "detail": detail,
                                        "affected": []}])
        self.assertEqual((codex2.calls, claude2.calls, c2.journal.path.read_bytes()), ([], [], journal))
        self.assertFalse(any(card_path(root, name).exists() for name in cards))

    def test_a_marked_run_publishes_one_settlement_and_its_card(self):
        root, c, t, codex, claude = marked()
        outcome = run(c, root)
        self.assertEqual(told(outcome), NEEDS_ONE)
        self.assertEqual(([req.stage for req in codex.calls], [req.stage for req in claude.calls]),
                         (["reading", "reveal", "batch_propose"], ["reading", "reveal", "batch_review"]))
        events = c.events(TASK)
        self.assertEqual([e["type"] for e in events][-3:], ["batch.proposed", "batch.reviewed", "reading.settled"])
        [settled] = settlements(c)
        proposed, reviewed = events[-3], events[-2]
        self.assertEqual(list(settled), ENVELOPE + FIELDS)
        self.assertEqual((settled["batch_protocol"], settled["interface_protocol"], settled["mode"]),
                         ("confirmed-v1", "whole", "confirmed"))
        self.assertEqual((settled["packet_sha"], settled["proposal_sha"], settled["review_sha"], settled["direct_packet"]),
                         (proposed["packet_sha"], proposed["sha"], reviewed["sha"], {}))
        self.assertEqual((batch.digest(settled["proposal"]), batch.digest(settled["review"])),
                         (proposed["sha"], reviewed["sha"]))
        body = {k: settled[k] for k in FIELDS[:-1]}
        self.assertEqual(settled["settlement_sha"], batch.digest({"task": TASK, **body}))
        [row] = settled["choices"]
        self.assertEqual(list(row), ROW_FIELDS)
        self.assertEqual((row["kind"], row["resolution"], row["selected"], row["id"], row["allowed"], row["card_text"]),
                         ("reading", "pending", "", "D-clamp-001-1", ["a", "b", "other"], CARD))
        self.assertEqual(card_path(root, "D-clamp-001-1").read_bytes(), CARD.encode("utf-8"))
        self.assertEqual(outcome.cards, (row,))
        self.assertEqual(c.status(), [{"task": TASK, "status": "needs_ruling", "pending": ["D-clamp-001-1"]}])

    def test_a_restart_after_publication_repeats_the_cards_with_no_calls_or_appends(self):
        root, c, t, codex, claude = marked()
        first = run(c, root)
        c2, codex2, claude2 = resumed(root, c)
        before = evidence(c2, t)
        second = run(c2, root)
        self.assertEqual((told(second), second.cards), (NEEDS_ONE, first.cards))
        self.assertEqual((codex2.calls, claude2.calls, evidence(c2, t)), ([], [], before))

    def test_a_crash_before_the_settlement_newline_publishes_nothing_and_a_restart_publishes_once(self):
        root, c, t, codex, claude = marked()
        real = c.journal.append

        def torn(type, task, **fields):
            if type == "reading.settled":
                with c.journal.path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(json.dumps({"ts": "x", "type": type, "task": task, **fields}))
                raise RuntimeError("killed before the newline")
            return real(type, task, **fields)

        with mock.patch.object(c.journal, "append", torn), self.assertRaises(RuntimeError):
            c.run(root / TASK_FILE)
        self.assertFalse(c.journal.path.read_text(encoding="utf-8").endswith("\n"))
        c2, codex2, claude2 = resumed(root, c)
        self.assertEqual((settlements(c2), c2.status()), ([], [{"task": TASK, "status": "in_progress", "pending": []}]))
        self.assertFalse(card_path(root, "D-clamp-001-1").exists())
        self.assertEqual(told(run(c2, root)), NEEDS_ONE)
        self.assertEqual((codex2.calls, claude2.calls, len(settlements(c2))), ([], [], 1))
        self.assertTrue(c2.journal.path.read_text(encoding="utf-8").endswith("\n"))
        self.assertEqual(card_path(root, "D-clamp-001-1").read_bytes(), CARD.encode("utf-8"))

    def test_a_crash_after_the_settlement_newline_restores_the_cards_without_private_artifacts(self):
        root, c, t, codex, claude = marked()
        target, real = card_path(root, "D-clamp-001-1"), Conductor._write

        def write(path, text):
            if Path(path) == target:
                raise RuntimeError("killed before the card")
            return real(path, text)

        with mock.patch.object(c, "_write", side_effect=write), self.assertRaises(RuntimeError) as caught:
            c.run(root / TASK_FILE)
        self.assertEqual(str(caught.exception), "killed before the card")
        self.assertEqual(len(settlements(c)), 1)
        self.assertTrue(c.journal.path.read_text(encoding="utf-8").endswith("\n"))
        self.assertFalse(target.exists())
        (t.dir / "artifacts").rename(t.dir / "artifacts-away")       # the restart may not read one
        c2, codex2, claude2 = resumed(root, c)
        journal = c2.journal.path.read_bytes()
        with private_reads() as stored:
            self.assertEqual(c2.status(), [{"task": TASK, "status": "needs_ruling", "pending": ["D-clamp-001-1"]}])
            self.assertEqual(told(run(c2, root)), NEEDS_ONE)
        stored.assert_not_called()
        self.assertEqual((codex2.calls, claude2.calls, c2.journal.path.read_bytes()), ([], [], journal))
        self.assertEqual(target.read_bytes(), CARD.encode("utf-8"))

    def test_a_restart_restores_a_missing_card_and_rewrites_an_edited_one(self):
        root, c, t, settled = two_cards(self)
        first, second = settled["choices"]
        card_path(root, "D-clamp-001-1").unlink()
        card_path(root, "D-clamp-001-2").write_text("edited\n", encoding="utf-8", newline="\n")
        c2, codex2, claude2 = resumed(root, c)
        journal = c2.journal.path.read_bytes()
        with private_reads() as stored:
            self.assertEqual(told(run(c2, root)), ("needs_ruling", "needs a ruling on D-clamp-001-1, D-clamp-001-2"))
        stored.assert_not_called()
        self.assertEqual((card_path(root, "D-clamp-001-1").read_bytes(), card_path(root, "D-clamp-001-2").read_bytes()),
                         (first["card_text"].encode("utf-8"), second["card_text"].encode("utf-8")))
        self.assertEqual((codex2.calls, claude2.calls, c2.journal.path.read_bytes()), ([], [], journal))

    def test_a_settlement_that_does_not_match_its_certificate_blocks_before_any_reader_shows_an_id(self):
        def review_sha(events):
            of(events, "batch.reviewed")["sha"] = ZERO

        def duplicate(events):
            events.append(copy.deepcopy(of(events, "reading.settled")))

        def reseal_after(events):
            events.append({**copy.deepcopy(of(events, "reading.sealed")), "ts": "later"})

        def first_row(change):
            return edit_settled(lambda e: change(e["choices"][0]))

        def other_reveal(events):
            for event in events:
                if event["type"] == "reveal.done" and event["seat"] == "claude":
                    event["sha"] = "sha256:" + "2" * 64

        cases = [
            (edit_settled(lambda e: e.update(settlement_sha=ZERO), reseal=False), RECORD + "does not match its settlement_sha"),
            (first_row(lambda row: row.update(card_text="Dispute D-clamp-001-1 (reading)\n\nrule a\n")),
             RECORD + "does not follow from its certificate"),
            (first_row(lambda row: row.update(id="D-clamp-001-7")), RECORD + "does not follow from its certificate"),
            (first_row(lambda row: row.update(allowed=["a", "b"])), RECORD + "does not follow from its certificate"),
            (edit_settled(lambda e: e.update(proposal_sha="sha256:" + "1" * 64)),
             RECORD + "names a different proposal than its checkpoints"),
            (review_sha, RECORD + "names a different review than its batch.reviewed checkpoint"),
            (edit_settled(lambda e: e["review"]["votes"][0].update(reason="edited")),
             RECORD + "holds a review that does not match its review_sha"),
            (edit_settled(lambda e: e.update(extra="x")), RECORD + "has other fields"),
            (edit_settled(lambda e: e.update(mode="direct")), RECORD + "is direct, but the task has batch checkpoints"),
            (other_reveal, RECORD + "settles other seats or inputs than the recorded seals and reveals"),
            (duplicate, "clamp-001 has 2 reading.settled records"),
            (reseal_after, RECORD + "comes before a seal, reveal or batch checkpoint"),
        ]
        for spoil, detail in cases:
            with self.subTest(detail=detail):
                root, c, t, codex, claude = marked()
                run(c, root)
                rewrite(c, spoil)
                self.assert_blocked_on_restart(root, c, detail)

    def test_the_publication_prefix_must_be_the_one_the_publisher_accepts(self):
        # Each edit leaves every hash valid, or repairs it; only the order, authorship or binding of the prefix changes.
        def reviewed_first(events):
            event = of(events, "batch.reviewed")
            events.remove(event)
            events.insert(events.index(of(events, "batch.proposed")), event)

        def early_proposal(events):
            # Between the two reveals, whichever seat revealed last: the check must use the later reveal.
            event = of(events, "batch.proposed")
            events.remove(event)
            events.insert(max(i for i, e in enumerate(events) if e["type"] == "reveal.done"), event)
            at, reveals = events.index(event), [i for i, e in enumerate(events) if e["type"] == "reveal.done"]
            assert len(reveals) == 2 and reveals[0] < at < reveals[1], (reveals, at)

        def edit(kind, **fields):
            return lambda events: of(events, kind).update(fields)

        def reseal_between(events):
            sealed = copy.deepcopy([e for e in events if e["type"] == "reading.sealed" and e["seat"] == "codex"][-1])
            events.insert(events.index(of(events, "batch.proposed")), {**sealed, "ts": "between"})

        def missing_seal(events):
            # The builder's seal is gone and the packet names no reading for it, as a lookup that found nothing
            # would; the packet's sha is repaired everywhere it is named, then the reply chain and the record.
            events.remove(next(e for e in events if e["type"] == "reading.sealed" and e["seat"] == "codex"))
            proposed, reviewed = of(events, "batch.proposed"), of(events, "batch.reviewed")
            proposed["packet"]["inputs"]["builder"]["reading"] = None
            packet_sha = proposed["packet_sha"] = reviewed["packet_sha"] = batch.digest(proposed["packet"])

            def repoint(settled):
                settled["packet_sha"] = settled["proposal"]["packet_sha"] = settled["review"]["packet_sha"] = packet_sha

            rechained(repoint)(events)

        def unnamed_seal(events):
            next(e for e in events if e["type"] == "reading.sealed" and e["seat"] == "codex").pop("sha")

        cases = [
            (reviewed_first, "the batch.reviewed checkpoint has no batch.proposed before it"),
            (early_proposal, "the batch.proposed checkpoint comes before a recorded reveal"),
            (edit("batch.proposed", opening=ZERO), "the batch.proposed checkpoint belongs to another opening"),
            (edit("batch.proposed", seat="claude"), "the batch.proposed checkpoint was not written by the builder codex"),
            (edit("batch.reviewed", seat="codex"), "the batch.reviewed checkpoint was not written by the challenger claude"),
            (edit("batch.proposed", usage="many"), "the batch.proposed checkpoint has malformed usage"),
            (edit("batch.reviewed", usage={"input": "1"}), "the batch.reviewed checkpoint has malformed usage"),
            (edit("batch.reviewed", packet_sha=ZERO), "the batch.reviewed checkpoint names a different packet"),
            (edit("batch.reviewed", proposal_sha=ZERO), "the batch.reviewed checkpoint names a different proposal"),
            (reseal_between, "the recorded reveals do not follow both sealed readings"),
            (missing_seal, "codex has no sealed reading and reveal to settle"),
            (unnamed_seal, "codex's reading.sealed has no sha"),
        ]
        for spoil, detail in cases:
            with self.subTest(detail=detail):
                root, c, t, codex, claude = marked()
                run(c, root)
                rewrite(c, spoil)
                self.assert_blocked_on_restart(root, c, detail)

    def test_a_packet_or_reply_the_publisher_would_refuse_blocks_even_with_its_hashes_repaired(self):
        def refusal_on_direct(t):
            # A reviewed refusal forged onto a genuinely direct packet: every hash and the whole record derived.
            def apply(events):
                settled = of(events, "reading.settled")
                packet, packet_sha = settled["direct_packet"], settled["packet_sha"]
                proposal = changed(REFUSED_PROPOSAL, packet_sha=packet_sha)
                review = changed(REFUSE, packet_sha=packet_sha, proposal_sha=batch.digest(proposal))
                certificate = {"packet_sha": packet_sha, "proposal_sha": batch.digest(proposal),
                               "review_sha": batch.digest(review), "direct_packet": {}, "proposal": proposal,
                               "review": review}
                body = conductor._settlement_body(t, batch.confirmed_settlement(packet, proposal, review), packet, certificate)
                marker = {"ts": "forged", "task": TASK, "batch_protocol": "confirmed-v1", "packet_sha": packet_sha,
                          "usage": {}}
                at = events.index(settled)
                events[at:at + 1] = [
                    {**marker, "type": "batch.proposed", "seat": "codex", "opening": conductor._opening_sha(t), "packet": packet,
                     "sha": certificate["proposal_sha"]},
                    {**marker, "type": "batch.reviewed", "seat": "claude", "proposal_sha": certificate["proposal_sha"],
                     "sha": certificate["review_sha"]},
                    {"ts": "forged", "type": "reading.settled", "task": TASK, **body}]
            return apply

        unscrubbed = rechained(lambda s: s["review"]["votes"][0].update(reason=r"see C:\Users\me\notes.txt"))
        cases = [
            (one_dispute(), refusal_on_direct, RECORD + "is refusal, but its packet is on a direct route"),
            (one_dispute(), lambda t: direct_packet_edit(
                lambda p: p.update(sources=[row for row in p["sources"] if row["kind"] != "interface"])),
             RECORD + "holds a packet that is not well formed: sources must hold one builder interface row, not 0"),
            (one_dispute(), lambda t: direct_packet_edit(lambda p: p.pop("precedents")),
             RECORD + "holds a packet that has other fields"),
            # The counter is the challenger's verdict, which the packet also holds in its reveals.
            (one_dispute(), lambda t: direct_packet_edit(lambda p: p["sources"][0].update(counter="Return lo.")),
             RECORD + "holds a packet that does not follow from its own readings and reveals"),
            (ROLE_REVEALS, lambda t: unscrubbed, RECORD + "holds a review that is not its accepted value"),
        ]
        for reveals, spoil, detail in cases:
            with self.subTest(detail=detail):
                root, c, t, codex, claude = marked(reveals=reveals)
                run(c, root)
                rewrite(c, spoil(t))
                self.assert_blocked_on_restart(root, c, detail)

    def test_a_certificate_forged_with_every_hash_repaired_must_still_pass_both_checks(self):
        prefix = RECORD + "holds a certificate that no longer passes its checks: "
        cases = [
            # The valid proposal stays; only the attesting review loses its votes.
            (rechained(lambda s: s["review"].update(votes=[])), prefix + "missing vote for c/0"),
            (rechained(lambda s: s["proposal"].update(votes=[])),
             prefix + "missing vote for c/0\npreference for c/0 must be an answer you sign"),
            # Both checks pass, but no card file can hold the reason: the record cannot follow from it.
            (rechained(lambda s: s["review"]["votes"][0].update(reason="NaN bounds must raise " + chr(0xD800))),
             RECORD + "does not follow from its certificate: the card for c/0 is not UTF-8 text"),
        ]
        for spoil, detail in cases:
            with self.subTest(detail=detail):
                root, c, t, codex, claude = marked()
                run(c, root)
                rewrite(c, spoil)
                self.assert_blocked_on_restart(root, c, detail)

    def test_a_direct_route_publishes_its_packet_with_no_batch_call(self):
        root, c, t, codex, claude = marked(reveals=one_dispute())
        outcome = run(c, root)
        self.assertEqual(told(outcome), NEEDS_ONE)
        self.assertEqual(([req.stage for req in codex.calls], [req.stage for req in claude.calls]),
                         (["reading", "reveal"], ["reading", "reveal"]))
        [settled] = settlements(c)
        self.assertEqual((settled["mode"], settled["proposal_sha"], settled["review_sha"], settled["proposal"],
                          settled["review"], settled["packet_sha"]),
                         ("direct", "", "", {}, {}, batch.digest(settled["direct_packet"])))
        self.assertNotIn("batch.proposed", [e["type"] for e in c.events(TASK)])
        [row] = settled["choices"]
        self.assertNotIn("Votes:", row["card_text"])
        self.assertNotIn("Predictions both seats confirmed", row["card_text"])     # its witness is the source's
        # The columns are the source texts exactly, as a ruling records them: the fixtures' padding included.
        self.assertIn("\na) codex (builder):\n| Raise ValueError when hi < lo. \nb) claude (challenger):\n"
                      "|  Raise ValueError unless lo <= hi. \nother) Supply the policy with --note.\n", row["card_text"])
        self.assertIn("\n  claude (challenger): Raise ValueError unless lo <= hi.\n    why: NaN bounds\n", row["card_text"])
        rewrite(c, edit_settled(lambda e: e["direct_packet"].update(task="edited")))
        c2, codex2, claude2 = resumed(root, c)
        self.assertEqual(told(run(c2, root)),
                         ("blocked", RECORD + "has a direct_packet that does not match its packet_sha"))

    def test_a_published_prefix_is_checked_before_any_private_state_exists(self):
        root, c, codex, claude = seeded(batch_protocol="confirmed-v1",
                                        after=[("reading.settled", {"batch_protocol": "confirmed-v1", "mode": "confirmed",
                                                                    "settlement_sha": ZERO})])
        journal = c.journal.path.read_bytes()
        detail = RECORD + "does not match its settlement_sha"
        self.assertEqual((told(run(c, root)), c.journal.path.read_bytes()), (("blocked", detail), journal))
        self.assertFalse((c.home / repo_key(root) / TASK).exists())
        self.assertEqual(c.status(), [{"task": TASK, "status": "blocked", "pending": [], "detail": detail, "affected": []}])
        self.assertEqual((codex.calls, claude.calls), ([], []))

    def test_a_published_settlement_needs_no_checkout_or_private_folder(self):
        root, c, t, codex, claude = marked()
        run(c, root)

        def no_checkouts(events):
            events[:] = [e for e in events if e["type"] != "checkout.created"]

        rewrite(c, no_checkouts)
        t.dir.rename(t.dir.with_name(t.dir.name + "-away"))
        card_path(root, "D-clamp-001-1").unlink()                    # the public card is a view: it comes back
        c2, codex2, claude2 = resumed(root, c)
        journal = c2.journal.path.read_bytes()
        with private_reads() as stored:
            self.assertEqual(c2.status(), [{"task": TASK, "status": "needs_ruling", "pending": ["D-clamp-001-1"]}])
            self.assertEqual(told(run(c2, root)), NEEDS_ONE)
        stored.assert_not_called()
        self.assertEqual((codex2.calls, claude2.calls, c2.journal.path.read_bytes()), ([], [], journal))
        self.assertFalse(t.dir.exists())
        self.assertEqual(card_path(root, "D-clamp-001-1").read_bytes(), CARD.encode("utf-8"))

    def test_a_direct_witness_that_trimming_and_scrubbing_see_differently_publishes_and_restarts(self):
        for name, reveals in (("quoted", QUOTED_REVEALS), ("scrubbed twice", TWICE_REVEALS)):
            with self.subTest(name):
                root, c, t, codex, claude = marked(reveals=reveals)
                first = run(c, root)
                self.assertEqual(told(first), NEEDS_ONE)
                [settled] = settlements(c)
                [witness] = [v["witness"] for v in settled["direct_packet"]["reveals"]["challenger"]["verdicts"]
                             if v["index"] == 0]
                [source] = [s for s in settled["direct_packet"]["sources"] if s["witness"]]
                self.assertEqual((settled["mode"], witness["scenario"], source["witness"]["scenario"]),
                                 ("direct", 'read "<outside>', 'read "<outside>'))
                self.assertIn('\n  witness from claude (challenger): read "<outside> (result or exception): ',
                              first.cards[0]["card_text"])
                card = card_path(root, "D-clamp-001-1").read_bytes()
                c2, codex2, claude2 = resumed(root, c)
                journal = c2.journal.path.read_bytes()
                second = run(c2, root)
                self.assertEqual((told(second), second.cards), (NEEDS_ONE, first.cards))
                self.assertEqual((codex2.calls, claude2.calls, c2.journal.path.read_bytes(),
                                  card_path(root, "D-clamp-001-1").read_bytes()), ([], [], journal, card))

    def test_a_review_reason_scrubbed_twice_is_stored_as_its_accepted_value_and_restarts(self):
        root, c, t, codex, claude = marked(review=reviews(changed(REVIEW, votes=[{**REVIEW["votes"][0], "reason": TWICE}])))
        first = run(c, root)
        self.assertEqual(told(first), NEEDS_ONE)
        events = c.events(TASK)
        self.assertEqual([sum(e["type"] == kind for e in events)
                          for kind in ("batch.proposed", "batch.reviewed", "reading.settled")], [1, 1, 1])
        [settled] = settlements(c)
        self.assertEqual((settled["review"], settled["review"]["votes"][0]["reason"]),
                         (batch.accepted(settled["review"]), 'read "<outside>'))
        expected = CARD.replace("signs b: NaN bounds must raise\n", 'signs b: read "<outside>\n')
        self.assertEqual((first.cards[0]["card_text"], card_path(root, "D-clamp-001-1").read_bytes()),
                         (expected, expected.encode("utf-8")))
        c2, codex2, claude2 = resumed(root, c)
        journal = c2.journal.path.read_bytes()
        second = run(c2, root)
        self.assertEqual((told(second), second.cards), (NEEDS_ONE, first.cards))
        self.assertEqual((codex2.calls, claude2.calls, c2.journal.path.read_bytes()), ([], [], journal))

    def test_a_packet_is_already_public_so_scrubbing_it_again_changes_nothing(self):
        # The task and precedent text too, not only the rows: the seats see the packet, and replay hashes it.
        precedent = {"id": "D-other-1", "question": TWICE, "ruling": "a", "while": "", "task": "other"}
        built = batch.packet(TWICE, [precedent], ROLE_READINGS, TWICE_REVEALS, INPUTS, SEATS)
        self.assertEqual((built["task"], built["precedents"][0]["question"]), ('read "<outside>', 'read "<outside>'))
        self.assertEqual(batch.public(built), built)

    def test_the_publisher_appends_only_a_settlement_its_readers_accept(self):
        root, c, t, codex, claude = marked()
        with mock.patch.object(conductor, "_packet_problem", return_value="was refused by replay"):
            self.assertEqual(told(run(c, root)), ("blocked", RECORD + "holds a packet that was refused by replay"))
        self.assertEqual(settlements(c), [])
        self.assertFalse(card_path(root, "D-clamp-001-1").exists())

    def test_a_card_no_file_can_hold_blocks_before_the_settlement_is_appended(self):
        def voting(reason):
            return reviews(changed(REVIEW, votes=[{**REVIEW["votes"][0], "reason": reason}]))

        with self.subTest("a lone surrogate"):
            root, c, t, codex, claude = marked(review=voting("NaN bounds must raise " + chr(0xD800)))
            self.assertEqual(told(run(c, root)), (
                "blocked", "the confirmed settlement cannot be published: the card for c/0 is not UTF-8 text"))
            self.assertEqual(settlements(c), [])
            self.assertFalse(card_path(root, "D-clamp-001-1").parent.exists())
        with self.subTest("a character outside ASCII"):
            root, c, t, codex, claude = marked(review=voting("NaN bounds must raise ≠"))
            self.assertEqual(told(run(c, root)), NEEDS_ONE)
            self.assertIn("- claude (challenger) signs b: NaN bounds must raise ≠\n",
                          card_path(root, "D-clamp-001-1").read_text(encoding="utf-8"))

    def test_each_seat_is_checked_just_before_its_own_artifacts_in_seat_order(self):
        # Task 19.4's order: the builder's seal and reading, then the challenger's.
        root, c, t, codex, claude = marked()
        c._readings(t)

        def spoil(events):
            for event in events:
                if event["type"] == "reading.sealed" and event["seat"] == "codex":
                    event["sha"] = ZERO                                 # a reading that was never stored
                elif event["type"] == "reading.sealed":
                    del event["sha"]

        rewrite(c, spoil)
        c2, codex2, claude2 = resumed(root, c)
        journal = c2.journal.path.read_bytes()
        self.assertEqual(told(run(c2, root)), ("blocked", "the recorded reading of codex is missing from the state folder"))
        self.assertEqual((codex2.calls, claude2.calls, c2.journal.path.read_bytes()), ([], [], journal))


class Pending(unittest.TestCase):
    def test_with_one_card_ruled_every_reader_shows_only_the_other(self):
        root, c, t, settled = two_cards(self)
        first, second = settled["choices"]
        self.assertEqual([(row["id"], row["kind"], row["slot"]) for row in settled["choices"]],
                         [("D-clamp-001-1", "reading", "c/0"), ("D-clamp-001-2", "interface", "c/1")])
        c.journal.append("ruling.made", TASK, **ruling(settled, first))
        c2, codex, claude = resumed(root, c)
        journal = c2.journal.path.read_bytes()
        outcome = run(c2, root)
        self.assertEqual((told(outcome), outcome.cards), (("needs_ruling", "needs a ruling on D-clamp-001-2"), (second,)))
        with self.assertRaises(Exception) as caught:
            c2._rulings(c2._task_of(TASK, "", c2.events(TASK)[0]))
        self.assertEqual(caught.exception.outcome.cards, (second,))
        self.assertEqual(c2.status(), [{"task": TASK, "status": "needs_ruling", "pending": ["D-clamp-001-2"]}])
        self.assertEqual(printed(cli._report, outcome),
                         (2, f"\n{second['card_text']}\nclamp-001: needs_ruling  needs a ruling on D-clamp-001-2\n"))
        self.assertIn("a) codex (builder):\n| clamp(x, lo, hi)\nb) claude (challenger):\n| clamp(x, lo, hi); clip = clamp\n"
                      "other) Supply the complete interface with --note.\n\nVotes:\n"
                      "- codex (builder) signs a: one name is enough\n- claude (challenger) signs b: callers want clip\n",
                      second["card_text"])
        self.assertEqual(printed(cli._status, root), (0, "clamp-001  needs_ruling  D-clamp-001-2\n"))
        self.assertEqual((codex.calls, claude.calls, c2.journal.path.read_bytes()), ([], [], journal))

    def test_a_ruling_the_settlement_does_not_publish_or_bind_blocks_every_reader_before_any_card_is_written(self):
        cases = [
            (lambda s, rows: [ruling(s, rows[0], settlement_sha=ZERO)],
             "D-clamp-001-1's ruling.made is not bound to the reading.settled record"),
            (lambda s, rows: [{k: v for k, v in ruling(s, rows[0]).items() if k != "batch_protocol"}],
             "D-clamp-001-1's ruling.made is not bound to the reading.settled record"),
            (lambda s, rows: [ruling(s, rows[1], dispute="D-clamp-001-3")],
             "D-clamp-001-3's ruling.made rules no card of the reading.settled record"),
            (lambda s, rows: [ruling(s, rows[0]), ruling(s, rows[0], choice="b")],
             "D-clamp-001-1 has more than one ruling.made"),
        ]
        for seed, detail in cases:
            with self.subTest(detail=detail):
                root, c, t, settled = two_cards(self)
                for fields in seed(settled, settled["choices"]):
                    c.journal.append("ruling.made", TASK, **fields)
                card_path(root, "D-clamp-001-1").unlink()
                card_path(root, "D-clamp-001-2").write_bytes(b"sentinel\n")
                c2, codex, claude = resumed(root, c)
                journal = c2.journal.path.read_bytes()
                outcome = run(c2, root)
                self.assertEqual((told(outcome), outcome.cards), (("blocked", detail), ()))
                self.assertEqual(c2.status(), [{"task": TASK, "status": "blocked", "pending": [], "detail": detail,
                                                "affected": []}])
                self.assertEqual((codex.calls, claude.calls, c2.journal.path.read_bytes()), ([], [], journal))
                self.assertFalse(card_path(root, "D-clamp-001-1").exists())
                self.assertEqual(card_path(root, "D-clamp-001-2").read_bytes(), b"sentinel\n")

    def test_a_ruling_before_the_settlement_blocks_before_any_call_or_append(self):
        detail = "D-clamp-001-1's ruling.made comes before the reading.settled record"
        with self.subTest("inside a published history"):
            root, c, t, settled = two_cards(self)
            fields = ruling(settled, settled["choices"][0])

            def early(events):
                at = next(i for i, e in enumerate(events) if e["type"] == "reading.settled")
                events.insert(at, {"ts": "early", "type": "ruling.made", "task": TASK, **fields})

            rewrite(c, early)
            c2, codex, claude = resumed(root, c)
            self.assertEqual(told(run(c2, root)), ("blocked", detail))
        with self.subTest("ending an unpublished history"):
            root, c, t, codex, claude = marked()
            c._readings(t)
            c._reveal(t)
            c.journal.append("ruling.made", TASK, dispute="D-clamp-001-1", kind="reading", question="q", choice="a",
                             text="a", scope="project", **{"while": ""}, limitation="", batch_protocol="confirmed-v1",
                             settlement_sha=ZERO)
            c2, codex2, claude2 = resumed(root, c)
            journal = c2.journal.path.read_bytes()
            self.assertEqual(told(run(c2, root)), ("blocked", detail))
            self.assertEqual(c2.status(), [{"task": TASK, "status": "blocked", "pending": [], "detail": detail,
                                            "affected": []}])
            self.assertEqual((codex2.calls, claude2.calls, c2.journal.path.read_bytes()), ([], [], journal))

    def test_a_blocked_settlement_shows_its_detail_and_keys_and_no_id(self):
        root, c, t, codex, claude = marked(propose=proposes(fallback=FALLBACK), review=reviews(REFUSE))
        self.assertEqual(told(run(c, root)), ("blocked", BLOCKED))
        [settled] = settlements(c)
        self.assertEqual((settled["mode"], settled["choices"], settled["affected"]), ("blocked", [], ["builder/1"]))
        row = {"task": TASK, "status": "blocked", "pending": [], "detail": BLOCKED, "affected": ["builder/1"]}
        c2, codex2, claude2 = resumed(root, c)
        before = evidence(c2, t)
        outcome = run(c2, root)
        self.assertEqual((told(outcome), outcome.cards, c2.status()), (("blocked", BLOCKED), (), [row]))
        self.assertEqual((codex2.calls, claude2.calls, evidence(c2, t)), ([], [], before))
        self.assertEqual(printed(cli._status, root), (0, f"clamp-001  blocked  {BLOCKED}\n"))
        self.assertFalse((root / ".parallax/run" / TASK / "cards").exists())
        # A ruling on a blocked settlement rules no card: it has none.
        c2.journal.append("ruling.made", TASK, dispute="D-clamp-001-1", batch_protocol="confirmed-v1",
                          settlement_sha=settled["settlement_sha"])
        detail = "D-clamp-001-1's ruling.made rules no card of the reading.settled record"
        self.assertEqual(told(run(c2, root)), ("blocked", detail))
        self.assertEqual(c2.status(), [{"task": TASK, "status": "blocked", "pending": [], "detail": detail,
                                        "affected": []}])

    def test_a_refusal_publishes_one_card_with_every_replaced_and_surviving_term(self):
        root, c, t, codex, claude = marked(propose=proposes(fallback=ALIAS_FALLBACK), review=reviews(ALIAS_REFUSE),
                                           readings=INDENTED_READINGS)
        outcome = run(c, root)
        self.assertEqual(told(outcome), NEEDS_ONE)
        [row] = outcome.cards
        self.assertEqual((row["kind"], row["target"], row["resolution"], row["allowed"], row["members"], row["card_text"]),
                         ("refusal", "combined", "refused", ["other", "drop"],
                          ["builder/0", "challenger/0", "builder/interface"], REFUSAL_CARD))
        self.assertEqual(settlements(c)[0]["choices"], [row])
        self.assertEqual(card_path(root, "D-clamp-001-1").read_bytes(), REFUSAL_CARD.encode("utf-8"))
        self.assertEqual(printed(cli._report, outcome),
                         (2, f"\n{REFUSAL_CARD}\nclamp-001: needs_ruling  needs a ruling on D-clamp-001-1\n"))

    def test_a_withdrawn_agreement_shows_its_owner_and_the_withdrawal(self):
        root, c, t, codex, claude = marked(propose=proposes(MOVED_PROPOSAL))
        outcome = run(c, root)
        self.assertEqual(told(outcome), NEEDS_ONE)
        [settled] = settlements(c)
        [row] = settled["choices"]
        self.assertEqual((settled["withdrawn"], row["members"], row["card_text"]),
                         ([WITHDRAWAL], ["builder/0", "challenger/0", "builder/1"], MOVED_CARD))
        self.assertEqual([term["sources"] for term in settled["common"]], [["builder/interface"]])
        self.assertEqual(card_path(root, "D-clamp-001-1").read_bytes(), MOVED_CARD.encode("utf-8"))
        self.assertEqual(printed(cli._report, outcome),
                         (2, f"\n{MOVED_CARD}\nclamp-001: needs_ruling  needs a ruling on D-clamp-001-1\n"))

    def test_each_column_value_has_one_reading_on_the_card(self):
        # A `| ` line per line keeps indentation, blank lines and trailing spaces; a hidden character puts the
        # whole value in one `|! ` JSON string literal instead, so no carriage return reaches the terminal.
        cases = [("", ["|"]), ("\n", ["|", "|"]), ("|x", ["| |x"]), ("x  ", ["| x  "]), ("x\\r", ["| x\\r"]),
                 ("x\r", ['|! "x\\r"']), ("x\r\n", ['|! "x\\r\\n"']), ("a‮b", ['|! "a\\u202eb"']),
                 ("!x", ["| !x"])]
        for value, lines in cases:
            with self.subTest(value=value):
                self.assertEqual(batch._block(value), lines)
        # Evidence on one line is trimmed; evidence that would span lines, hides a character or starts with the
        # marker is shown as `!` and its literal, untrimmed.
        for value, shown in ((" x \n", "x"), ("a\nb", '!"a\\nb"'), ("a\rb ", '!"a\\rb "'), ("!x", '!"!x"')):
            with self.subTest(value=value):
                self.assertEqual(batch._inline(value), shown)
        a_policy = "Raise ValueError when hi < lo.\r"
        proposal = changed(PROPOSAL, choices=[{**PROPOSAL["choices"][0], "a": {"interface": "", "policy": a_policy}}],
                           votes=[{**PROPOSAL["votes"][0], "reason": "strict (\\x)\rcomparisons"}])
        root, c, t, codex, claude = marked(propose=proposes(proposal))
        outcome = run(c, root)
        self.assertEqual(told(outcome), NEEDS_ONE)
        expected = (CARD.replace("\n| Raise ValueError when hi < lo.\n", '\n|! "Raise ValueError when hi < lo.\\r"\n')
                    .replace("signs a: strict comparisons\n", 'signs a: !"strict (\\\\x)\\rcomparisons"\n'))
        [row] = settlements(c)[0]["choices"]
        self.assertEqual((row["a"]["policy"], row["card_text"], card_path(root, "D-clamp-001-1").read_bytes()),
                         (a_policy, expected, expected.encode("utf-8")))
        code, out = printed(cli._report, outcome)
        self.assertEqual((code, out), (2, f"\n{expected}\nclamp-001: needs_ruling  needs a ruling on D-clamp-001-1\n"))
        self.assertNotIn("\r", out)

    def test_status_reads_the_journal_once(self):
        root, c, t, settled = two_cards(self)
        c2, codex, claude = resumed(root, c)
        with mock.patch.object(c2.journal, "events", wraps=c2.journal.events) as reads:
            rows = c2.status()
        self.assertEqual((rows, reads.call_count),
                         ([{"task": TASK, "status": "needs_ruling", "pending": ["D-clamp-001-1", "D-clamp-001-2"]}], 1))

    def test_an_automatic_row_gets_no_id_and_the_next_public_row_is_numbered_from_one(self):
        root, c, t, codex, claude = marked(reveals=ALIAS_REVEALS, propose=proposes(TWO_PENDING),
                                           review=reviews(AUTO_THEN_PENDING_REVIEW))
        self.assertEqual(told(run(c, root)), NEEDS_ONE)
        [settled] = settlements(c)
        self.assertEqual([(row["slot"], row["resolution"], row["id"], row["allowed"], row["card_text"] == "")
                          for row in settled["choices"]],
                         [("c/0", "mutual", "", [], True), ("c/1", "pending", "D-clamp-001-1", ["a", "b", "other"], False)])
        self.assertEqual(sorted(p.name for p in card_path(root, "x").parent.iterdir()), ["D-clamp-001-1.md"])

    def test_with_nothing_pending_a_marked_run_freezes_its_contract(self):
        # Task 19.7: past the settlement a marked run freezes its contract, once, with no further call.
        root, c, t, codex, claude = marked(propose=proposes(MUTUAL), review=reviews(MUTUAL_REVIEW))
        outcome = c.run(root / TASK_FILE, stop_after="contract")
        self.assertEqual((told(outcome), outcome.cards), (FROZEN, ()))
        [settled] = settlements(c)
        self.assertEqual([(row["resolution"], row["selected"], row["id"]) for row in settled["choices"]],
                         [("mutual", "a", "")])
        c2, codex2, claude2 = resumed(root, c)
        before = evidence(c2, t)
        self.assertEqual(told(c2.run(root / TASK_FILE, stop_after="contract")), FROZEN)
        self.assertEqual((codex2.calls, claude2.calls, evidence(c2, t)), ([], [], before))
        self.assertEqual([e["type"] for e in c2.events(TASK)].count("contract.frozen"), 1)
        self.assertEqual(c2.status(), [{"task": TASK, "status": "in_progress", "pending": []}])

    def test_with_every_card_ruled_a_marked_run_freezes_its_contract(self):
        root, c, t, settled = two_cards(self)
        for row in settled["choices"]:
            c.journal.append("ruling.made", TASK, **ruling(settled, row))
        c2, codex, claude = resumed(root, c)
        journal = c2.journal.path.read_bytes()
        outcome = c2.run(root / TASK_FILE, stop_after="contract")
        self.assertEqual((told(outcome), outcome.cards), (FROZEN, ()))
        self.assertEqual(c2.status(), [{"task": TASK, "status": "in_progress", "pending": []}])
        self.assertEqual((codex.calls, claude.calls), ([], []))
        # The journal as it was, then exactly one appended event: the freeze.
        after = c2.journal.path.read_bytes()
        self.assertEqual(after[:len(journal)], journal)
        self.assertEqual([e["type"] for e in parse_lines(after[len(journal):].decode("utf-8"))], ["contract.frozen"])

    def test_a_standalone_card_on_a_marked_task_blocks_status_and_the_legacy_rule(self):
        root, c, t, codex, claude = marked()
        run(c, root)
        card = decisions.Dispute("D-clamp-001-9", "reading", "What if lo > hi?", "Raise ValueError when hi < lo.",
                                 "Raise ValueError unless lo <= hi.", "codex (builder)", "claude (challenger)")
        c.journal.append("dispute.opened", TASK, **card.to_fields())
        detail = "D-clamp-001-9 is a standalone reading card on a confirmed-v1 task"
        self.assertEqual(c.status(), [{"task": TASK, "status": "blocked", "pending": [], "detail": detail,
                                       "affected": []}])
        journal = c.journal.path.read_bytes()
        self.assertEqual(call("rule", "D-clamp-001-9", "a", "--repo", str(root)), (1, "", f"parallax: {detail}\n"))
        self.assertEqual(c.journal.path.read_bytes(), journal)

    def test_a_standalone_check_card_on_a_marked_task_gets_no_legacy_ruling(self):
        card = decisions.Dispute("D-clamp-001-9", "check", "Does test_clamp_nan pass?", "It passes.", "It fails.",
                                 "codex (builder)", "claude (challenger)")
        spoiled = edit_settled(lambda e: e.update(settlement_sha=ZERO), reseal=False)
        cases = [(None, "D-clamp-001-9 is a standalone check card on a confirmed-v1 task"),
                 (spoiled, RECORD + "does not match its settlement_sha")]
        for spoil, detail in cases:
            with self.subTest(detail=detail):
                root, c, t, codex, claude = marked()
                run(c, root)
                c.journal.append("dispute.opened", TASK, **card.to_fields())
                if spoil:
                    rewrite(c, spoil)
                journal = c.journal.path.read_bytes()
                self.assertEqual(call("rule", "D-clamp-001-9", "a", "--repo", str(root)), (1, "", f"parallax: {detail}\n"))
                self.assertEqual(c.journal.path.read_bytes(), journal)

    def test_the_demo_prints_each_card_and_the_commands_it_allows(self):
        root = make_project()
        cards = ({"id": "D-clamp-001-1", "allowed": ["a", "b", "other"], "card_text": "first card\n"},
                 {"id": "D-clamp-001-2", "allowed": ["other", "drop"], "card_text": "refusal card\n"})
        outcome = Outcome("needs_ruling", TASK, "needs a ruling on D-clamp-001-1, D-clamp-001-2", cards=cards)
        with mock.patch.object(Conductor, "run", return_value=outcome):
            code, out, err = call("demo", "--dir", str(root), "--stub")
        where = root.resolve()
        self.assertEqual((code, out, err), (2, (
            f"demo project: {where}\n\nfirst card\n\n\nrefusal card\n\n"
            "clamp-001: needs_ruling  needs a ruling on D-clamp-001-1, D-clamp-001-2\n"
            f'rule with: python -m parallax rule D-clamp-001-1 a --repo "{where}"   (or b, other --note TEXT)\n'
            f'rule with: python -m parallax rule D-clamp-001-2 other --note TEXT --repo "{where}"   (or drop)\n'
            f'then run: python -m parallax demo --dir "{where}" --stub\n'), ""))


DECISIONS = [{"question": "What does clamp do when lo > hi?", "answer": "Swap the bounds.", "why": "be forgiving"},
             {"question": "What does clamp return for NaN x?", "answer": "NaN.", "why": "propagate"}]


class LegacyControl(unittest.TestCase):
    def test_an_unmarked_task_that_would_batch_when_marked_keeps_the_legacy_cards_and_amendment(self):
        root = make_project()
        codex = StubSeat("codex", {"reading": [reading(*DECISIONS)], "reveal": [reveal(replacement=None)]})
        claude = StubSeat("claude", {"reading": [reading()], "reveal": [
            reveal((False, "swap the bounds"), (False, "swap the bounds"), interface_ok=False,
                   objection="return an int", replacement=None)]})
        c = kit_conductor(root, codex, claude)
        open_unmarked(c, root)                      # Task 17: no interface_protocol, no batch_protocol
        tripwire = mock.patch.object(Conductor, "_certified", side_effect=AssertionError("reached the confirmed-v1 route"))
        with tripwire:
            first = run(c, root)
            self.assertEqual(first.status, "needs_ruling")
            ids = [d.id for d in first.disputes]
            self.assertEqual([(d.id, d.kind) for d in first.disputes],
                             [("D-clamp-001-1", "reading"), ("D-clamp-001-2", "reading"), ("D-clamp-001-3", "interface")])
            cards = {i: card_path(root, i).read_bytes() for i in ids}
            again, codex2, claude2 = resumed(root, c)
            second = run(again, root)
            self.assertEqual(([d.id for d in second.disputes], {i: card_path(root, i).read_bytes() for i in ids}),
                             (ids, cards))
            for dispute in ids:                     # the seat-free CLI path, as a human rules
                self.assertEqual(call("rule", dispute, "b", "--repo", str(root))[0], 0)
            out = again.run(root / TASK_FILE, stop_after="contract")
        self.assertEqual(told(out), ("stopped", "stopped after the contract was frozen"))
        self.assertEqual(interface_section(contract_text(root)), "clamplib.clamp(x, lo, hi) -> number\nAmended: return an int")
        kinds = [e["type"] for e in again.events(TASK)]
        self.assertFalse({"batch.proposed", "batch.reviewed", "reading.settled"} & set(kinds))
        self.assertEqual((codex2.calls, claude2.calls), ([], []))
        self.assertEqual(kinds.count("ruling.made"), 3)
