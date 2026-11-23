import json, os, re, unittest
from pathlib import Path
from unittest import mock
from parallax import batch, folders, gitops
from parallax.conductor import Conductor
from parallax.config import load_config, repo_key
from parallax.ledger import parse_lines, sha256_text
from parallax.seats.stub import StubSeat
from tests.conductor_kit import CLAMP_BAD, builds, probes, responds
from tests.test_batch import A_POLICY, B_POLICY, FALLBACK, QUESTION, REFUSE, TWO_CHOICES, TWO_REVIEW, changed
from tests.test_cli import call
from tests.test_conductor_batch import proposes, reviews
from tests.test_conductor_reading import resumed
from tests.test_conductor_settled import (ALIAS_REVEALS, MUTUAL, MUTUAL_REVIEW, TASK, TASK_FILE, ZERO, marked,
                                          private_reads, rewrite, run, settlements, told, two_cards)
from tests.test_conductor_ruled import WHOLE, refusal, rule

# Task 19.7. Past its rulings a confirmed-v1 task freezes its contract from the settlement alone: the common
# terms, then each choice's selected column or ruled value, each term once, with batch_protocol and the
# settlement's digest on the freeze. A refusal ruled `drop` lands its record first. Before the build the
# task's folder and clones are made again if they are gone, so a task resumed after publication with neither
# reaches the build and lands. A failed crossing stops at its card, which `rule` refuses until Task 19.8.
# Every reader checks each freeze from events alone, down to the sha of the contract they give, so a task only
# main's ledger holds is checked too.
ONE, TWO, THREE = "D-clamp-001-1", "D-clamp-001-2", "D-clamp-001-3"
FROZEN = ("stopped", "stopped after the contract was frozen")
TASK_TEXT = "Add clamp(x, lo, hi) to clamplib: returns x limited to the range lo..hi.\n"
RETURNED = ("What is returned?", "One of the objects passed.", "agreed")
CLIP = "clamp(x, lo, hi); clip = clamp"
FREEZE_FIELDS = ["version", "sha", "interface_protocol", "batch_protocol", "settlement_sha"]
NOT_GIVEN = "contract v1 is not the contract its settlement and rulings give"
# Both choices of Task 19.3's two-choice batch settled with no card: both seats sign both predicates and the
# builder prefers b (a tie-break), and both sign the alias b (mutual).
TIES = changed(TWO_CHOICES, votes=[{"slot": "c/0", "sign": ["a", "b"], "reason": "either predicate works"},
                                   {"slot": "c/1", "sign": ["a", "b"], "reason": "either name works"}],
               preferences=[{"slot": "c/0", "answer": "b"}, {"slot": "c/1", "answer": "a"}])
TIES_REVIEW = changed(TWO_REVIEW, votes=[{"slot": "c/0", "sign": ["a", "b"], "reason": "either predicate works"},
                                         {"slot": "c/1", "sign": ["b"], "reason": "callers want clip"}])
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "task19-7"
_GIT = re.compile(r"\b[0-9a-f]{40}\b")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_CLONE = re.compile(r"\b(?:codex|claude)-[0-9a-f]{8}\b")
# The phases the two seats run at once, whose events may be recorded in any order the threads allow.
_AT_ONCE = (("reading.sealed",), ("reveal.done",), ("attempt.started", "attempt.finished"))

def contract(interface, *decisions):
    """Contract v1 of clamp-001 as rendered: this task's rulings are decisions, so no precedent is in force."""
    lines = "".join(f"- Q: {question}\n  A: {answer} ({source})\n" for question, answer, source in decisions)
    return (f"# Contract: clamp-001 (v1)\n\n## Task\n{TASK_TEXT}\n\n## Interface\n{interface}\n\n"
            f"## Decisions\n{lines}\n## Precedents in force\nnone\n")

def contract_path(root):
    return root / ".parallax/run" / TASK / "contract-v1.md"

def frozen(c, root):
    """A fresh conductor's run, stopped after the contract, and the contract file it froze."""
    c2, codex, claude = resumed(root, c)
    try:
        outcome = c2.run(root / TASK_FILE, stop_after="contract")
    except Exception as error:
        raise AssertionError(f"the run raised {error!r}") from error
    path = contract_path(root)
    return outcome, (path.read_text(encoding="utf-8") if path.exists() else None), codex.calls + claude.calls

def restore(case):
    """Put a class's settlement back as it was published: its journal bytes, and no contract file, so no case
    can pass on a file an earlier case wrote."""
    case.c.journal.path.write_bytes(case.journal)
    contract_path(case.root).unlink(missing_ok=True)

def public_files(root):
    """Every file under the task's public run folder (its cards and contracts), by name."""
    folder = root / ".parallax/run" / TASK
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}

def journal_bytes(c):
    return c.journal.path.read_bytes() if c.journal.path.exists() else b""

def blocks(test, root, c, detail, *ruling):
    """Every reader refuses with `detail` (`rule` too, when a ruling is given), and none calls a seat or changes
    the journal, a card or a contract."""
    journal, files = journal_bytes(c), public_files(root)
    c2, codex, claude = resumed(root, c)
    test.assertEqual(told(run(c2, root)), ("blocked", detail))
    test.assertEqual(c2.status(), [{"task": TASK, "status": "blocked", "pending": [], "detail": detail, "affected": []}])
    if ruling:
        test.assertEqual(rule(root, *ruling), (1, "", f"parallax: {detail}\n"))
    test.assertEqual((codex.calls, claude.calls, journal_bytes(c), public_files(root)), ([], [], journal, files))

def spied(seat, calls):
    """Record each `discard` of `seat` as (seat, session, folder), in order, and still make it."""
    real = seat.discard

    def discard(session, cwd):
        calls.append((seat.name, session, str(cwd)))
        return real(session, cwd)
    seat.discard = discard

def freezes(c):
    return [e for e in c.events(TASK) if e["type"] == "contract.frozen"]

def stored(event):
    return {field: event[field] for field in event if field not in ("ts", "type", "task")}

def seated(root, c, codex_script, claude_script):
    """A fresh conductor on the same project and state home, with these scripts."""
    codex, claude = StubSeat("codex", codex_script), StubSeat("claude", claude_script)
    return Conductor(load_config(root), {"codex": codex, "claude": claude}, say=lambda s: None, home=c.home), codex, claude

def lose_folder(test, root, c, t):
    """Delete the task's state folder, its clones inside it, as a lost or cleaned machine would."""
    test.assertEqual((t.dir.parent, t.dir.name), (c.home / repo_key(root), TASK))
    test.assertTrue(gitops.remove_tree(t.dir))

def on_main(root):
    return [e for e in parse_lines(gitops.show_file(root, "main", ".parallax/ledger.jsonl")) if e.get("task") == TASK]

def rewrite_main(root, change):
    """Commit a hand edit of main's ledger: `change` mutates the list of events in place."""
    path = root / ".parallax/ledger.jsonl"
    events = parse_lines(path.read_text(encoding="utf-8"))
    change(events)
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8", newline="\n")
    gitops.git(root, "add", ".parallax/ledger.jsonl")
    gitops.commit_staged(root, "edit the ledger by hand", gitops.identity(root))

def normalized(value, *folders):
    """`value` with what differs between runs replaced: every timestamp by `<ts>`, and the given folders, clone
    names, git commit ids and sha256 digests by placeholders numbered by first appearance (the opening's base
    commit reaches every digest that follows it)."""
    names: dict[str, str] = {}

    def name(kind, token):
        if token not in names:
            names[token] = f"<{kind}-{sum(1 for v in names.values() if v.startswith(f'<{kind}-')) + 1}>"
        return names[token]

    def scrub(item):
        if isinstance(item, dict):
            return {k: "<ts>" if k == "ts" else scrub(v) for k, v in item.items()}
        if isinstance(item, (list, tuple)):
            return [scrub(v) for v in item]
        if isinstance(item, str):
            for i, folder in enumerate(folders, 1):
                if str(folder) in item:
                    item = item.replace(str(folder), f"<folder-{i}>").replace("\\", "/")
            item = _CLONE.sub(lambda m: name("clone", m.group()), item)
            item = _DIGEST.sub(lambda m: name("sha", m.group()), item)
            return _GIT.sub(lambda m: name("git", m.group()), item)
        return item
    return scrub(value)

def in_seat_order(history):
    """`history` with each phase the two seats run at once put in one order, and nothing else moved.

    The seats' readings, their reveals and their attempts run on two threads, so a legal run may record them in
    any interleaving: one seat may finish its attempt before the other starts. Each such phase must hold its
    events once per seat, in order for that seat (ValueError otherwise), and is written by event, then by seat,
    builder first. Everything the conductor does in sequence (checkouts, rulings, the freeze) keeps its place.
    """
    opened = next(e for e in history if e["type"] == "task.opened")
    seats = [opened["builder"], opened["challenger"]]
    out, at = [], 0
    while at < len(history):
        phase = next((p for p in _AT_ONCE if history[at]["type"] in p), None)
        if phase is None:
            out.append(history[at])
            at += 1
            continue
        end = at
        while end < len(history) and history[end]["type"] in phase:
            end += 1
        block = history[at:end]
        for seat in seats:
            if [e["type"] for e in block if e.get("seat") == seat] != list(phase):
                raise ValueError(f"{seat} does not have exactly {', '.join(phase)} in this phase")
        if len(block) != len(phase) * len(seats):
            raise ValueError(f"a {phase[0]} phase holds an event of no seat")
        out += sorted(block, key=lambda e: (phase.index(e["type"]), seats.index(e["seat"])))
        at = end
    return out

def kept(test, name, record):
    """Compare `record` with the normalized history and CLI results kept in tests/fixtures/task19-7/<name>, a
    comparison fixture for another implementation. Its placeholders are not valid ids or digests: to replay it
    through a reader, give each a valid value and recompute the digests that depend on it.
    PARALLAX_WRITE_FIXTURES=1 writes the file first (only to create or deliberately update it)."""
    path = FIXTURES / name
    if os.environ.get("PARALLAX_WRITE_FIXTURES") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    test.assertEqual(json.loads(path.read_text(encoding="utf-8")), record)


class Kept(unittest.TestCase):
    """The kept histories' normalization alone: only what the seats do at once is reordered."""

    def test_only_the_phases_the_seats_run_at_once_are_put_in_seat_order(self):
        def e(type, seat=None, **more):
            return {"type": type, **({"seat": seat} if seat else {}), **more}

        opened = e("task.opened", builder="codex", challenger="claude")
        s, f = "attempt.started", "attempt.finished"
        both = [opened, e(s, "codex"), e(s, "claude"), e(f, "codex"), e(f, "claude")]
        # Every legal schedule of two attempts, one seat finishing before the other starts among them.
        for schedule in ([(s, "codex"), (f, "codex"), (s, "claude"), (f, "claude")],
                         [(s, "claude"), (f, "claude"), (s, "codex"), (f, "codex")],
                         [(s, "claude"), (s, "codex"), (f, "claude"), (f, "codex")],
                         [(s, "codex"), (s, "claude"), (f, "claude"), (f, "codex")]):
            with self.subTest(schedule=schedule):
                self.assertEqual(in_seat_order([opened] + [e(*x) for x in schedule]), both)
        for type in ("reading.sealed", "reveal.done"):
            with self.subTest(type=type):
                self.assertEqual(in_seat_order([opened, e(type, "claude"), e(type, "codex")]),
                                 [opened, e(type, "codex"), e(type, "claude")])
        # What the conductor does in sequence keeps its order, so a swap there changes the kept history.
        for first, second in ((e("ruling.made", dispute=TWO), e("ruling.made", dispute=ONE)),
                              (e("checkout.created", "claude"), e("checkout.created", "codex"))):
            with self.subTest(first=first):
                self.assertEqual(in_seat_order([opened, first, second]), [opened, first, second])
        # A phase that is not each seat's events once, in order, is not a history this normalization knows.
        for bad in ([e(s, "codex"), e(s, "codex")], [e(f, "codex"), e(s, "codex"), e(s, "claude"), e(f, "claude")],
                    [e(s, "codex"), e(f, "codex")]):
            with self.subTest(bad=bad):
                try:
                    got = in_seat_order([opened] + bad)
                except ValueError:
                    got = "refused"
                self.assertEqual(got, "refused")


class Terms(unittest.TestCase):
    """`batch.contract_terms` alone: what no checked settlement reaches through run, refused all the same."""
    ROW = {"slot": "c/0", "target": "policy", "question": QUESTION, "id": ONE, "resolution": "pending", "selected": "",
           "a": {"interface": "", "policy": A_POLICY}, "b": {"interface": "", "policy": B_POLICY}}
    INTERFACE = {"slot": "interface", "question": "What interface should the contract use?", "text": "clamp(x, lo, hi)",
                 "sources": ["builder/interface"]}

    def test_a_missing_ruling_a_drop_and_any_count_of_interfaces_but_one_are_refused(self):
        alias = {**self.ROW, "target": "interface", "a": {"interface": "clamp(x, lo, hi)", "policy": ""},
                 "b": {"interface": CLIP, "policy": ""}}
        cases = [({"common": [self.INTERFACE], "choices": [self.ROW]}, {}, f"{ONE} has no ruling"),
                 ({"common": [self.INTERFACE], "choices": [self.ROW]}, {ONE: {"choice": "drop", "value": self.ROW["a"]}},
                  f"{ONE} drops the task"),
                 ({"common": [self.INTERFACE], "choices": [alias]}, {ONE: {"choice": "b", "value": alias["b"]}},
                  "the settlement gives 2 interfaces, not one"),
                 ({"common": [], "choices": [self.ROW]}, {ONE: {"choice": "a", "value": self.ROW["a"]}},
                  "the settlement gives 0 interfaces, not one")]
        for settled, rulings, detail in cases:
            with self.subTest(detail=detail):
                try:
                    batch.contract_terms(settled, rulings)
                    got = "no error"
                except ValueError as error:
                    got = str(error)
                except Exception as error:                   # any other exception fails, not errors, the test
                    got = repr(error)
                self.assertEqual(got, detail)


class TwoCards(unittest.TestCase):
    """One published two-card settlement (a policy and an interface) for the class; each test starts from its
    journal bytes, so the expensive git settlement is built once."""

    @classmethod
    def setUpClass(cls):
        cls.root, cls.c, cls.t, cls.settled = two_cards(unittest.TestCase())
        cls.journal = cls.c.journal.path.read_bytes()

    def setUp(self):
        restore(self)

    def test_the_rulings_freeze_one_interface_and_each_policy_once(self):
        multiline = "Raise ValueError unless lo <= hi.\nPolicy: NaN bounds raise too.\n"
        cases = [((("a",), ("b",)), contract(CLIP, RETURNED, (QUESTION, A_POLICY, f"ruled {ONE}"))),
                 ((("b",), ("a",)), contract("clamp(x, lo, hi)", RETURNED, (QUESTION, B_POLICY, f"ruled {ONE}"))),
                 # Task 19.12: the same letter on both cards. Each card's letter picks its own column.
                 ((("a",), ("a",)), contract("clamp(x, lo, hi)", RETURNED, (QUESTION, A_POLICY, f"ruled {ONE}"))),
                 ((("b",), ("b",)), contract(CLIP, RETURNED, (QUESTION, B_POLICY, f"ruled {ONE}"))),
                 ((("other", "--note", multiline), ("other", "--note", "clip(x, lo, hi)")),
                  contract("clip(x, lo, hi)", RETURNED, (QUESTION, multiline, f"ruled {ONE}")))]
        for (first, second), expected in cases:
            with self.subTest(first=first, second=second):
                restore(self)
                self.assertEqual((rule(self.root, ONE, *first)[0], rule(self.root, TWO, *second)[0]), (0, 0))
                outcome, text, calls = frozen(self.c, self.root)
                self.assertEqual((told(outcome), text, calls), (FROZEN, expected, []))
                [freeze] = freezes(self.c)
                self.assertEqual(list(stored(freeze)), FREEZE_FIELDS)
                self.assertEqual((freeze["version"], freeze["interface_protocol"], freeze["batch_protocol"],
                                  freeze["settlement_sha"]), (1, "whole", "confirmed-v1", self.settled["settlement_sha"]))
                # Frozen once: a second run reuses it with no append.
                journal = self.c.journal.path.read_bytes()
                self.assertEqual(told(frozen(self.c, self.root)[0]), FROZEN)
                self.assertEqual(self.c.journal.path.read_bytes(), journal)

    def test_a_standalone_card_before_the_freeze_blocks_every_reader(self):
        # A check card, which only a failed crossing opens, written by hand while both settlement cards wait.
        # Task 19.8 checks that it follows a frozen contract, so no reader shows it beside the settlement's.
        self.c.journal.append("dispute.opened", TASK, id=THREE, kind="check", question="Which result is right?",
                              a="The build's.", b="The probe's.", a_label="codex (builder)",
                              b_label="claude (challenger)", evidence="")
        blocks(self, self.root, self.c, f"{THREE}'s dispute.opened comes before the contract is frozen", ONE, "a")

    def test_the_contract_is_the_one_the_packet_pinned_whatever_changed_since(self):
        # The task file edited and another task's project ruling made, both after publication: the contract
        # still holds the task text and the precedents the two seats settled under.
        self.assertEqual((rule(self.root, ONE, "a")[0], rule(self.root, TWO, "b")[0]), (0, 0))
        task_file = self.root / TASK_FILE
        self.addCleanup(task_file.write_text, TASK_TEXT, encoding="utf-8", newline="\n")
        task_file.write_text(TASK_TEXT + "Also add clip.\n", encoding="utf-8", newline="\n")
        self.c.journal.append("ruling.made", "other-001", dispute="D-other-001-1", kind="reading",
                              question="What is rounded?", choice="a", text="Nothing.", scope="project",
                              **{"while": ""}, limitation="")
        outcome, text, calls = frozen(self.c, self.root)
        self.assertEqual((told(outcome), text, calls),
                         (FROZEN, contract(CLIP, RETURNED, (QUESTION, A_POLICY, f"ruled {ONE}")), []))
        [freeze] = freezes(self.c)
        self.assertEqual(freeze["sha"], sha256_text(text))

    def test_a_freeze_that_does_not_follow_from_the_settlement_blocks_every_reader(self):
        self.assertEqual((rule(self.root, ONE, "a")[0], rule(self.root, TWO, "b")[0]), (0, 0))
        self.assertEqual(told(frozen(self.c, self.root)[0]), FROZEN)
        good, written = self.c.journal.path.read_bytes(), contract_path(self.root).read_bytes()

        def the_freeze(events):
            return next(e for e in events if e["type"] == "contract.frozen")

        def edit(change):
            return lambda events: change(the_freeze(events))

        def move(before):
            def apply(events):
                freeze = the_freeze(events)
                events.remove(freeze)
                events.insert(next(i for i, e in enumerate(events) if before(e)), freeze)
            return apply

        def substitute(events):
            # Another contract in the file, with its own sha on the freeze: the file and the record agree with
            # each other and with the settlement's digest, but not with what the settlement and rulings give.
            other = contract("clamp(x, lo, hi)", RETURNED)
            contract_path(self.root).write_text(other, encoding="utf-8", newline="\n")
            the_freeze(events)["sha"] = sha256_text(other)

        cases = [(edit(lambda e: e.pop("batch_protocol")), "contract v1 is not bound to the reading.settled record"),
                 (edit(lambda e: e.update(settlement_sha=ZERO)), "contract v1 is not bound to the reading.settled record"),
                 (move(lambda e: e["type"] == "reading.settled"), "contract v1 comes before the reading.settled record"),
                 (move(lambda e: e["type"] == "ruling.made" and e["dispute"] == TWO),
                  f"contract v1 is frozen before {TWO} is ruled"),
                 (edit(lambda e: e.update(version=2)), "contract v2 is not version 1"),
                 (edit(lambda e: e.pop("version")), "contract vNone is not version 1"),
                 (edit(lambda e: e.update(version=True)), "contract vTrue is not version 1"),
                 (edit(lambda e: e.update(version=1.0)), "contract v1.0 is not version 1"),
                 (lambda events: events.append(dict(events[-1])), "contract v1 is not version 2"),
                 # A second version, numbered and bound as the writer would: nothing since v1 amends the contract.
                 (lambda events: events.append({**events[-1], "version": 2}),
                  "contract v2 follows no ruling that amends the contract"),
                 (edit(lambda e: e.pop("sha")), NOT_GIVEN),
                 (edit(lambda e: e.update(sha=ZERO)), NOT_GIVEN),
                 (substitute, NOT_GIVEN)]
        for number, (change, detail) in enumerate(cases):
            with self.subTest(case=number, detail=detail):
                self.c.journal.path.write_bytes(good)
                contract_path(self.root).write_bytes(written)
                rewrite(self.c, change)
                blocks(self, self.root, self.c, detail, ONE, "b")


class Refusal(unittest.TestCase):
    """One published refusal (one combined card allowing other and drop) for the class, reset per test."""

    @classmethod
    def setUpClass(cls):
        cls.root, cls.c, cls.t, cls.settled = refusal()
        cls.journal = cls.c.journal.path.read_bytes()

    def setUp(self):
        restore(self)

    def test_a_refusal_freezes_its_kept_terms_verbatim_and_the_ruled_value_once(self):
        self.assertEqual(rule(self.root, ONE, "other", "--note", WHOLE)[0], 0)
        outcome, text, calls = frozen(self.c, self.root)
        [row] = self.settled["choices"]
        self.assertEqual((told(outcome), calls), (FROZEN, []))
        self.assertEqual(text, contract("clamp(x, lo, hi) -> number",
                                        # Kept as written: the question's leading space, the answer's indent and break.
                                        (" What is returned?", "One of the objects passed:\n    x, lo or hi\n", "agreed"),
                                        (row["question"], "Raise ValueError when hi < lo.", f"ruled {ONE}")))

    def test_a_freeze_after_a_drop_blocks_every_reader(self):
        self.assertEqual(rule(self.root, ONE, "drop")[0], 0)
        self.c.journal.append("contract.frozen", TASK, version=1, sha=ZERO, interface_protocol="whole",
                              batch_protocol="confirmed-v1", settlement_sha=self.settled["settlement_sha"])
        blocks(self, self.root, self.c, "contract v1 freezes a dropped task", ONE, "other", "--note", WHOLE)


class Automatic(unittest.TestCase):
    def test_an_automatic_row_freezes_its_selected_column_and_says_how_it_was_settled(self):
        cases = [(dict(propose=proposes(MUTUAL), review=reviews(MUTUAL_REVIEW)),
                  contract("clamp(x, lo, hi)", RETURNED, (QUESTION, A_POLICY, "both seats signed a"))),
                 (dict(reveals=ALIAS_REVEALS, propose=proposes(TIES), review=reviews(TIES_REVIEW)),
                  contract(CLIP, RETURNED, (QUESTION, B_POLICY, "both seats signed both; the builder preferred b")))]
        for fixture, expected in cases:
            with self.subTest(expected=expected):
                root, c, t, codex, claude = marked(**fixture)
                outcome = c.run(root / TASK_FILE, stop_after="contract")
                self.assertEqual(told(outcome), FROZEN)
                self.assertEqual([row["id"] for row in settlements(c)[0]["choices"]], [""] * len(settlements(c)[0]["choices"]))
                self.assertEqual(contract_path(root).read_text(encoding="utf-8"), expected)

    def test_a_contract_that_is_not_utf_8_text_blocks_before_anything_is_written(self):
        # An automatic row has no card, so nothing has encoded its text yet: a lone surrogate in the policy both
        # seats signed reaches the contract.
        policy = A_POLICY + chr(0xD800)
        proposal = changed(MUTUAL, choices=[{**MUTUAL["choices"][0], "a": {"interface": "", "policy": policy}}])
        root, c, t, codex, claude = marked(propose=proposes(proposal), review=reviews(MUTUAL_REVIEW))
        detail = "the contract cannot be frozen: it is not UTF-8 text"
        self.assertEqual(told(run(c, root)), ("blocked", detail))
        self.assertEqual([row["a"]["policy"] for row in settlements(c)[0]["choices"]], [policy])
        self.assertEqual((freezes(c), contract_path(root).exists()), ([], False))
        # Another run blocks the same way, before either seat starts. Status freezes nothing, so it cannot say.
        c2, codex2, claude2 = resumed(root, c)
        journal = c2.journal.path.read_bytes()
        self.assertEqual(told(run(c2, root)), ("blocked", detail))
        self.assertEqual((codex2.calls, claude2.calls, c2.journal.path.read_bytes()), ([], [], journal))
        self.assertEqual((freezes(c), contract_path(root).exists()), ([], False))

    def test_a_freeze_of_a_blocked_settlement_blocks_every_reader(self):
        root, c, t, codex, claude = marked(propose=proposes(fallback=FALLBACK), review=reviews(REFUSE))
        self.assertEqual(run(c, root).status, "blocked")
        [settled] = settlements(c)
        self.assertEqual((settled["mode"], settled["choices"]), ("blocked", []))
        # No card is left unruled, because a blocked settlement has none: the freeze is refused all the same.
        c.journal.append("contract.frozen", TASK, version=1, sha=ZERO, interface_protocol="whole",
                         batch_protocol="confirmed-v1", settlement_sha=settled["settlement_sha"])
        blocks(self, root, c, "contract v1 freezes a blocked settlement")


class Resume(unittest.TestCase):
    """Task 19.7's exit criterion: a published settlement resumed with no task folder or clones reaches the
    build and lands, and a refusal drop lands before either is needed. Each test lands, drops or runs a build
    and a crossing, which moves main or replaces the task folder and writes attempts, so each builds its own
    project."""

    def test_a_published_settlement_with_no_task_folder_or_clones_reaches_the_build_and_lands(self):
        root, c, t, settled = two_cards(self)
        self.assertEqual((rule(root, ONE, "a")[0], rule(root, TWO, "b")[0]), (0, 0))
        sealed = {e["seat"]: e["session"] for e in c.events(TASK) if e["type"] == "reading.sealed"}
        old = {e["seat"]: e["path"] for e in c.events(TASK) if e["type"] == "checkout.created"}
        lose_folder(self, root, c, t)
        c2, codex, claude = seated(root, c, {"build": [builds()]}, {"probe": [probes()]})
        discards = []
        spied(codex, discards), spied(claude, discards)
        with private_reads():                                # after publication nothing private is read again
            outcome = run(c2, root)
        self.assertEqual(told(outcome)[0], "landed", told(outcome))
        self.assertEqual(outcome.detail, f"landed {outcome.commit[:12]}")
        self.assertEqual(([r.stage for r in codex.calls], [r.stage for r in claude.calls]), (["build"], ["probe"]))
        # New clones, so new sessions: the old ones went with the folder and are discarded.
        self.assertEqual([r.session for r in codex.calls + claude.calls], [None, None])
        history = on_main(root)
        new = {e["seat"]: e["path"] for e in history if e["type"] == "checkout.created"}
        built = {e["seat"]: e["session"] for e in history if e["type"] == "attempt.finished"}
        self.assertEqual((sorted(new), [old[seat] == new[seat] for seat in sorted(new)]), (["claude", "codex"], [False, False]))
        # Each reading session is discarded with its lost clone when the clone is made again, and at landing
        # each build session with the new clone. The folder tells them apart: both stubs name a session s1.
        self.assertEqual(discards, [("codex", sealed["codex"], old["codex"]), ("claude", sealed["claude"], old["claude"]),
                                    ("codex", built["codex"], new["codex"]), ("claude", built["claude"], new["claude"])])
        types = [e["type"] for e in history]
        after = types[types.index("ruling.made"):]
        self.assertEqual([x for x in after if x in ("ruling.made", "contract.frozen", "checkout.created")],
                         ["ruling.made", "ruling.made", "contract.frozen", "checkout.created", "checkout.created"])
        self.assertEqual(types[-1], "task.integrated")
        self.assertEqual(gitops.show_file(root, "main", f".parallax/contracts/{TASK}.md"),
                         contract(CLIP, RETURNED, (QUESTION, A_POLICY, f"ruled {ONE}")))
        # The landed task replays from main's ledger alone: its cards are ruled and its freeze is bound.
        status, again = call("status", "--repo", str(root)), rule(root, ONE, "b")
        self.assertEqual((status, again), ((0, f"{TASK}  landed\n", ""), (1, "", f"parallax: {ONE} is already ruled\n")))
        self.assertFalse(t.dir.exists())
        kept(self, "resumed-and-landed.json", normalized(
            {"history": in_seat_order(history), "cli": [[["status"], *status], [["rule", ONE, "b"], *again]]}, c.home / repo_key(root), root))
        # The same ledger with only its freeze unbound, no journal and no folder: every reader refuses it.
        rewrite_main(root, lambda events: next(e for e in events if e["type"] == "contract.frozen").update(settlement_sha=ZERO))
        blocks(self, root, c, "contract v1 is not bound to the reading.settled record", ONE, "b")
        self.assertEqual((c.journal.events(TASK), t.dir.exists()), ([], False))

    def test_with_its_folder_kept_the_build_resumes_each_reading_session_in_its_clone(self):
        root, c, t, settled = two_cards(self)
        self.assertEqual((rule(root, ONE, "a")[0], rule(root, TWO, "b")[0]), (0, 0))
        sealed = {e["seat"]: e["session"] for e in c.events(TASK) if e["type"] == "reading.sealed"}
        clones = [e for e in c.events(TASK) if e["type"] == "checkout.created"]
        c2, codex, claude = seated(root, c, {"build": [builds()]}, {"probe": [probes()]})
        self.assertEqual(run(c2, root).status, "landed")
        self.assertEqual([(r.session, str(r.cwd)) for r in codex.calls + claude.calls],
                         [(sealed["codex"], clones[0]["path"]), (sealed["claude"], clones[1]["path"])])
        self.assertEqual([e["type"] for e in on_main(root)].count("checkout.created"), 2)

    def test_a_refusal_drop_lands_its_record_with_no_contract_folder_or_clone(self):
        root, c, t, settled = refusal()
        reason = "The predicate is not ours to choose."
        self.assertEqual(rule(root, ONE, "drop", "--note", reason)[0], 0)
        lose_folder(self, root, c, t)
        c2, codex, claude = resumed(root, c)
        made, private, clone_at = [], folders.make_private, gitops.clone_at

        def make_private(path):
            made.append(("private", Path(path)))
            return private(path)

        def clone(repo, path, *rest):
            made.append(("clone", Path(path)))
            return clone_at(repo, path, *rest)

        with private_reads(), mock.patch.object(folders, "make_private", side_effect=make_private), \
                mock.patch.object(gitops, "clone_at", side_effect=clone):
            outcome = run(c2, root)
        self.assertEqual(told(outcome)[0], "dropped", told(outcome))
        # The landing checkout is the only clone, made inside a task folder closed to other accounts first.
        self.assertEqual(made, [("private", t.dir), ("clone", t.dir / "land")])
        self.assertEqual((contract_path(root).exists(), gitops.show_file(root, "main", f".parallax/contracts/{TASK}.md")),
                         (False, None))
        self.assertEqual(outcome.detail, f"dropped {outcome.commit[:12]}")
        self.assertEqual((codex.calls, claude.calls), ([], []))
        history = on_main(root)
        types = [e["type"] for e in history]
        self.assertEqual(types[types.index("ruling.made"):], ["ruling.made", "task.dropped"])
        self.assertEqual(history[-1]["reason"], reason)
        self.assertEqual((c2.journal.events(TASK), t.dir.exists()), ([], False))
        self.assertEqual(told(run(c2, root)), ("dropped", f"{TASK} was already dropped"))
        status, again = call("status", "--repo", str(root)), rule(root, ONE, "other", "--note", WHOLE)
        self.assertEqual((status, again), ((0, f"{TASK}  dropped\n", ""), (1, "", f"parallax: {ONE} is already ruled\n")))
        kept(self, "dropped.json", normalized(
            {"history": in_seat_order(history), "cli": [[["status"], *status], [["rule", ONE, "other", "--note", WHOLE], *again]]},
            c.home / repo_key(root), root))

    def test_an_interrupted_drop_lands_its_record_once(self):
        root, c, t, settled = refusal()
        self.assertEqual(rule(root, ONE, "drop")[0], 0)
        c2, codex, claude = resumed(root, c)
        with mock.patch.object(Conductor, "_integrate", side_effect=RuntimeError("killed before landing")):
            with self.assertRaises(RuntimeError):
                c2.run(root / TASK_FILE)
        self.assertEqual([e["type"] for e in c.journal.events(TASK)][-1], "task.dropped")
        c3, codex3, claude3 = resumed(root, c)
        self.assertEqual(run(c3, root).status, "dropped")
        self.assertEqual([e["type"] for e in on_main(root)].count("task.dropped"), 1)
        self.assertEqual(on_main(root)[-1]["reason"], "Drop this task.")

    def test_a_failed_crossing_stops_at_its_card(self):
        root, c, t, settled = two_cards(self)
        self.assertEqual((rule(root, ONE, "a")[0], rule(root, TWO, "b")[0]), (0, 0))
        lose_folder(self, root, c, t)
        c2, codex, claude = seated(root, c, {"build": [builds(CLAMP_BAD)], "respond": [responds("contest")]},
                                   {"probe": [probes()], "respond": [responds("contest")]})
        with mock.patch.object(folders, "make_private", wraps=folders.make_private) as made:
            outcome = run(c2, root)
        # The folder is made again closed to every other account, as `_open` makes it. Asked for, not only
        # observed: inside an owner-only state home a folder `git clone` makes would inherit the same rights.
        self.assertEqual(made.call_args_list, [mock.call(t.dir)])
        self.assertTrue(folders.is_private(t.dir))
        self.assertEqual(told(outcome), ("needs_ruling", f"needs a ruling on {THREE}"))
        self.assertEqual([d.kind for d in outcome.disputes], ["check"])
        self.assertEqual(c2.status(), [{"task": TASK, "status": "needs_ruling", "pending": [THREE]}])
        journal = c2.journal.path.read_bytes()
        # Another run stops at the same card: no seat is called and nothing is crossed again.
        c3, codex3, claude3 = resumed(root, c)
        self.assertEqual(told(run(c3, root)), ("needs_ruling", f"needs a ruling on {THREE}"))
        self.assertEqual((codex3.calls, claude3.calls, c3.journal.path.read_bytes()), ([], [], journal))
