import copy, json, unittest
from parallax import briefs, decisions, gitops, redact, schemas
from parallax.conductor import Conductor
from parallax.config import load_config, repo_key
from parallax.ledger import parse_lines, sha256_text
from parallax.schemas import validate
from parallax.seats.stub import StubSeat
from tests.conductor_kit import kit_conductor, make_project
from tests.helpers import write
from tests.test_conductor_batch import MARK, evidence, record_reveal
from tests.test_conductor_reading import resumed
from tests.test_decisions import NAN_WITNESS, ROLE_READINGS, ROLE_REVEALS, conflict, without

# Task 19.4. The readings and reveals are Task 19.1's role-keyed fixture. A marked task is opened with
# `_open(..., batch=True)`, which only tests do until Task 19.7. The builder is codex unless a test says otherwise.
TASK = "clamp-001"
TASK_FILE = "tasks/clamp-001.md"
CHORE, CHORE_FILE = "docs-001", "tasks/docs-001.md"     # make_project's chore
STOPPED = ("stopped", "stopped after the confirmed reveals")
UNMARKED_REVEALS = {role: without(ROLE_REVEALS[role], "conflicts") for role in ROLE_REVEALS}
# A witness whose two predictions differ only in a directory: the same words once scrubbed.
PATH_WITNESS = {**NAN_WITNESS, "theirs": r'returns "C:\Users\me\a\out.txt"', "mine": r'returns "D:\other\out.txt"'}
MARKED = "but clamp-001 was opened confirmed-v1"
UNMARKED = "but clamp-001 was not opened confirmed-v1"

def stored(reading):
    """A reading as the conductor reads it back: its canonical, key-sorted JSON."""
    return json.loads(json.dumps(reading, sort_keys=True))

def canonical(output):
    """The text the conductor stores for an output."""
    return json.dumps(output, sort_keys=True, indent=2)

def answers(reply):
    return lambda req: copy.deepcopy(reply)

def project(batch=True, builder="codex", reveals=ROLE_REVEALS, builder_reveal=None, challenger_reveal=None):
    """A project whose task is opened (confirmed-v1 unless `batch` is false), with stub seats.

    Each seat reads its role's reading and has one reveal step, `reveals` for its role, unless
    `builder_reveal` or `challenger_reveal` gives that seat's reveal steps. Returns the builder's and challenger's stubs.
    """
    root = make_project()
    challenger = "claude" if builder == "codex" else "codex"
    steps = {"builder": builder_reveal or [answers(reveals["builder"])],
             "challenger": challenger_reveal or [answers(reveals["challenger"])]}
    stubs = {seat: StubSeat(seat, {"reading": [answers(ROLE_READINGS[role])], "reveal": list(steps[role])})
             for seat, role in ((builder, "builder"), (challenger, "challenger"))}
    c = kit_conductor(root, stubs["codex"], stubs["claude"])
    t = c._open(TASK, (root / TASK_FILE).read_text(encoding="utf-8"), builder, batch=batch)
    return root, c, t, stubs[builder], stubs[challenger]

def seeded(task=TASK, drop=(), after=(), **fields):
    """A fresh project whose journal holds only a realistic task.opened for `task` (with `fields` set and `drop`
    removed), then the `after` events, appended directly: no task folder, checkout or other event exists."""
    root = make_project()
    codex, claude = StubSeat("codex", {}), StubSeat("claude", {})
    c = kit_conductor(root, codex, claude)
    opened = {"kind": "behavior", "base": gitops.rev(root, c.cfg.main), "builder": "codex", "challenger": "claude",
              "title": task, "interface_protocol": "whole", **fields}
    c.journal.append("task.opened", task, **{k: v for k, v in opened.items() if k not in drop})
    for type, extra in after:
        c.journal.append(type, task, **extra)
    return root, c, codex, claude

def ran(c, root, task_file=TASK_FILE):
    """(status, detail) of a run. A run that raises fails the test instead of erroring it."""
    try:
        o = c.run(root / task_file)
    except Exception as error:
        raise AssertionError(f"the run raised {error!r}") from error
    return o.status, o.detail

def stages(seat):
    return [req.stage for req in seat.calls]

def types(c):
    return [e["type"] for e in c.events(TASK)]

def rewrite(c, change):
    """Rewrite the journal as a hand edit would: `change` mutates the list of events in place."""
    path = c.journal.path
    events = parse_lines(path.read_text(encoding="utf-8"))
    change(events)
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8", newline="\n")

def edit(c, event, change):
    """Rewrite the one recorded event equal to `event` in place: `change` mutates it."""
    rewrite(c, lambda events: [change(e) for e in events if e == event])

def respoil(c, t, event, stage, text):
    """Replace the artifact `event` (a reading.sealed or reveal.done) points at with `text`, and repoint `event`."""
    seat = event["seat"]
    out = next(p / "output.json" for p in (t.dir / "artifacts").iterdir() if p.name.endswith(f"-{seat}-{stage}")
               and sha256_text((p / "output.json").read_text(encoding="utf-8")) == event["sha"])
    out.write_text(text, encoding="utf-8", newline="\n")
    edit(c, event, lambda e: e.update(sha=sha256_text(text)))

def reseal(c, t, seat):
    """A second reading.sealed for `seat` with the same sha, session and usage as its first."""
    s = c._sealed(t, seat)
    c.journal.append("reading.sealed", t.id, seat=seat, sha=s["sha"], session=s["session"], usage=s["usage"])

def card(kind, **extra):
    return lambda c, t: c.journal.append("dispute.opened", TASK, id="D-clamp-001-1", kind=kind, question="q", **extra)


class Opening(unittest.TestCase):
    def test_a_marked_opening_carries_both_markers_and_the_default_opening_neither_new(self):
        root, c, t, bstub, cstub = project()
        opened = c.events(TASK)[0]
        self.assertEqual(list(opened)[-2:], ["interface_protocol", "batch_protocol"])
        self.assertEqual((opened["interface_protocol"], opened["batch_protocol"], t.batch, t.whole),
                         ("whole", "confirmed-v1", True, True))
        root, c, t, bstub, cstub = project(batch=False)
        opened = c.events(TASK)[0]
        self.assertNotIn("batch_protocol", opened)
        self.assertEqual((opened["interface_protocol"], t.batch), ("whole", False))

    def test_a_run_opens_an_unmarked_task(self):
        root = make_project()
        stubs = {seat: StubSeat(seat, {"reading": [answers(ROLE_READINGS[role])], "reveal": [answers(UNMARKED_REVEALS[role])]})
                 for seat, role in (("codex", "builder"), ("claude", "challenger"))}
        c = kit_conductor(root, stubs["codex"], stubs["claude"])
        ran(c, root)
        opened = c.events(TASK)[0]
        self.assertEqual((opened["builder"], opened.get("interface_protocol"), "batch_protocol" in opened),
                         ("codex", "whole", False))

    def test_only_a_behavior_task_can_be_opened_marked(self):
        root = make_project()
        write(root, {"tasks/tidy-001.md": "kind: chore\nTidy the README.\n"})
        c = kit_conductor(root, StubSeat("codex", {}), StubSeat("claude", {}))
        try:
            c._open("tidy-001", (root / "tasks/tidy-001.md").read_text(encoding="utf-8"), "codex", batch=True)
        except Exception as error:
            caught = error
        else:
            self.fail("a chore was opened confirmed-v1")
        self.assertEqual((type(caught), str(caught)), (ValueError, "only a behavior task can be opened confirmed-v1"))
        self.assertEqual(c.events("tidy-001"), [])

    def test_an_opening_this_version_cannot_read_blocks_before_any_state_exists(self):
        cases = [
            ({"batch_protocol": "confirmed-v2"}, (),
             "has batch_protocol 'confirmed-v2', which this version of parallax does not know"),
            ({"batch_protocol": None}, (), "has batch_protocol None, which this version of parallax does not know"),
            (MARK, ("interface_protocol",), "has batch_protocol confirmed-v1 without interface_protocol whole"),
            ({**MARK, "interface_protocol": "amending"}, (),
             "has interface_protocol 'amending', which this version of parallax does not know"),
            ({"interface_protocol": None}, (), "has interface_protocol None, which this version of parallax does not know"),
            ({**MARK, "kind": "chore"}, (), "has batch_protocol confirmed-v1 on a chore task"),
        ]
        for fields, drop, detail in cases:
            with self.subTest(detail=detail):
                root, c, codex, claude = seeded(drop=drop, **fields)
                state = c.home / repo_key(root) / TASK
                journal = c.journal.path.read_bytes()
                self.assertFalse(state.exists())
                self.assertEqual(ran(c, root), ("blocked", f"clamp-001's task.opened {detail}"))
                self.assertEqual((codex.calls, claude.calls, c.journal.path.read_bytes(), state.exists()),
                                 ([], [], journal, False))

    def test_a_record_from_the_other_batch_protocol_blocks_before_any_state_exists(self):
        cases = [
            (CHORE, CHORE_FILE, {"kind": "chore"}, ("batch.reviewed", {"seat": "claude", "sha": "sha256:x"}),
             "claude's batch.reviewed is a confirmed-v1 record, but docs-001 was not opened confirmed-v1"),
            (TASK, TASK_FILE, {}, ("reveal.done", {"seat": "claude", "sha": "sha256:x", **MARK}),
             f"claude's reveal.done is a confirmed-v1 record, {UNMARKED}"),
            (TASK, TASK_FILE, MARK, ("reveal.done", {"seat": "claude", "sha": "sha256:x"}),
             f"claude's reveal.done is not marked batch_protocol confirmed-v1, {MARKED}"),
        ]
        for task, task_file, fields, event, detail in cases:
            with self.subTest(detail=detail):
                root, c, codex, claude = seeded(task, after=[event], **fields)
                state = c.home / repo_key(root) / task
                journal = c.journal.path.read_bytes()
                self.assertEqual(ran(c, root, task_file), ("blocked", detail))
                self.assertEqual((codex.calls, claude.calls, c.journal.path.read_bytes(), state.exists()),
                                 ([], [], journal, False))


class Reveals(unittest.TestCase):
    def test_a_marked_task_asks_for_confirmed_reveals_and_marks_them(self):
        for builder in ("codex", "claude"):
            with self.subTest(builder=builder):
                root, c, t, bstub, cstub = project(builder=builder)
                self.assertEqual(ran(c, root), STOPPED)
                self.assertEqual(types(c), ["task.opened", "checkout.created", "checkout.created", "reading.sealed",
                                            "reading.sealed", "reveal.done", "reveal.done"])
                inputs = {}
                for stub, role, other in ((bstub, "builder", "challenger"), (cstub, "challenger", "builder")):
                    self.assertEqual(stages(stub), ["reading", "reveal"])
                    request = stub.calls[1]
                    self.assertIs(request.schema, schemas.REVEAL_CONFIRMED)
                    self.assertFalse(request.writable)
                    self.assertEqual(request.session, c._sealed(t, stub.name)["session"])
                    self.assertEqual(request.brief, briefs.reveal(role, stored(ROLE_READINGS[other]), whole=True,
                                                                  own_reading=stored(ROLE_READINGS[role])))
                    done = c._last(TASK, "reveal.done", seat=stub.name)
                    self.assertEqual(list(done), ["ts", "type", "task", "seat", "sha", "usage", "batch_protocol"])
                    self.assertEqual(done["batch_protocol"], "confirmed-v1")
                    text = canonical(ROLE_REVEALS[role])
                    self.assertEqual((request.out_dir / "output.json").read_bytes(), text.encode("utf-8"))
                    self.assertEqual(done["sha"], sha256_text(text))
                    inputs[role] = {"reading": c._sealed(t, stub.name)["sha"], "reveal": done["sha"]}
                # What Task 19.5's settlement will read: 19.3's input check accepts the pair as recorded.
                readings, reveals, refs, last = c._confirm_inputs(t, c.events(TASK))
                self.assertEqual((readings, reveals, refs, last),
                                 ({r: stored(ROLE_READINGS[r]) for r in ROLE_READINGS}, ROLE_REVEALS, inputs, 6))

    def test_an_unmarked_task_reveals_as_before(self):
        root, c, t, bstub, cstub = project(batch=False, reveals=UNMARKED_REVEALS)
        ran(c, root)
        for stub, role, other in ((bstub, "builder", "challenger"), (cstub, "challenger", "builder")):
            request = stub.calls[1]
            self.assertIs(request.schema, schemas.REVEAL)
            self.assertEqual(request.brief, briefs.reveal(role, stored(ROLE_READINGS[other]), whole=True))
            self.assertNotIn("batch_protocol", c._last(TASK, "reveal.done", seat=stub.name))
        self.assertIn("dispute.opened", types(c))

    def test_a_reveal_the_settlement_would_refuse_is_corrected_inside_the_retry(self):
        good = ROLE_REVEALS["challenger"]
        path_verdict = {**good["verdicts"][1], "witness": PATH_WITNESS}
        cases = [
            ({**good, "conflicts": [conflict("builder/9", "builder/0")]}, "conflict 0: unknown source builder/9"),
            ({**good, "verdicts": [good["verdicts"][0], path_verdict]},
             "after scrubbing: " + decisions.witness_problem(redact.scrub_values(path_verdict))),
            ({**good, "interface_ok": False, "interface_objection": "name it value"},
             "interface_replacement must hold the complete interface you want when interface_ok is false"),
        ]
        for bad, reason in cases:
            with self.subTest(reason=reason):
                root, c, t, bstub, cstub = project(challenger_reveal=[answers(bad), answers(good)])
                self.assertEqual(ran(c, root), STOPPED)
                self.assertEqual(stages(cstub), ["reading", "reveal", "reveal"])
                self.assertEqual(cstub.calls[2].brief, briefs.rejected(cstub.calls[1].brief, reason))
                done = c._last(TASK, "reveal.done", seat="claude")
                self.assertEqual((done["batch_protocol"], c._stored(t, "claude", "reveal", done["sha"])),
                                 ("confirmed-v1", good))
                self.assertNotIn("seat.failed", types(c))

    def test_two_refused_reveals_block_with_no_reveal_recorded(self):
        bad = {**ROLE_REVEALS["challenger"], "conflicts": [conflict("builder/0", "builder/0")]}
        reason = decisions.conflict_problem(bad, decisions.source_keys(ROLE_READINGS))
        root, c, t, bstub, cstub = project(challenger_reveal=[answers(bad), answers(bad)])
        self.assertEqual(ran(c, root), ("blocked", f"claude failed at reveal: {reason}"))
        failed = c._last(TASK, "seat.failed")
        self.assertEqual((failed["seat"], failed["stage"], failed["error"]), ("claude", "reveal", reason))
        self.assertIsNone(c._last(TASK, "reveal.done", seat="claude"))

    def test_a_restart_after_one_real_reveal_asks_only_the_missing_seat(self):
        root, c, t, bstub, cstub = project()
        c._readings(t)
        c._reveal_one(t, "codex", {t.role(s): c._reading(t, s) for s in t.seats})
        codex = StubSeat("codex", {})
        claude = StubSeat("claude", {"reveal": [answers(ROLE_REVEALS["challenger"])]})
        c2 = Conductor(load_config(root), {"codex": codex, "claude": claude}, say=lambda s: None, home=c.home)
        self.assertEqual(ran(c2, root), STOPPED)
        self.assertEqual((stages(codex), stages(claude)), ([], ["reveal"]))
        self.assertEqual(claude.calls[0].session, c2._sealed(t, "claude")["session"])
        self.assertEqual(c2._confirm_inputs(t, c2.events(TASK))[1], ROLE_REVEALS)

    def test_a_marked_task_resumes_after_its_reveals_with_no_calls(self):
        root, c, t, bstub, cstub = project()
        ran(c, root)
        c2, codex, claude = resumed(root, c)
        before = evidence(c2, t)
        self.assertEqual(ran(c2, root), STOPPED)
        self.assertEqual((codex.calls, claude.calls, evidence(c2, t)), ([], [], before))
        self.assertEqual(c2.status(), [{"task": TASK, "status": "in_progress", "pending": []}])


class Guards(unittest.TestCase):
    def recorded(self, recorded_seat="claude", reveal=None, mark=MARK, batch=True):
        """Both readings sealed and `recorded_seat`'s reveal recorded; the other seat's reveal is still owed."""
        root, c, t, bstub, cstub = project(batch=batch)
        c._readings(t)
        record_reveal(c, t, recorded_seat, reveal or ROLE_REVEALS[t.role(recorded_seat)], mark)
        return root, c, t, {"codex": bstub, "claude": cstub} if t.builder == "codex" else {"codex": cstub, "claude": bstub}

    def assertBlocksWithNoCall(self, root, c, t, stubs, detail):
        calls = {seat: len(stub.calls) for seat, stub in stubs.items()}
        before = evidence(c, t)
        self.assertEqual(ran(c, root), ("blocked", detail))
        self.assertEqual(({seat: len(stub.calls) for seat, stub in stubs.items()}, evidence(c, t)), (calls, before))

    def test_a_recorded_reveal_is_checked_before_its_peer_is_asked(self):
        for seat, role in (("claude", "challenger"), ("codex", "builder")):
            with self.subTest(seat=seat, case="valid"):
                root, c, t, stubs = self.recorded(seat)
                self.assertEqual(ran(c, root), STOPPED)
                self.assertEqual((stages(stubs[seat]), stages(stubs[t.other(seat)])), (["reading"], ["reading", "reveal"]))
        challenger = ROLE_REVEALS["challenger"]
        path_verdict = {**challenger["verdicts"][1], "witness": PATH_WITNESS}
        t18 = without(challenger, "conflicts")
        cases = [
            ("claude", {**challenger, "conflicts": [conflict("builder/0", "challenger/7")]}, None,
             "claude's recorded reveal is not a confirmed-v1 reveal: conflict 0: unknown target challenger/7"),
            ("claude", {**challenger, "verdicts": [challenger["verdicts"][1]]}, None,
             "claude's recorded reveal is not a confirmed-v1 reveal: "
             "verdicts must give exactly one index for each of 0..1, got [0]"),
            ("claude", t18, None, "claude's recorded reveal is not a confirmed-v1 reveal: "
             + "; ".join(validate(t18, schemas.REVEAL_CONFIRMED))),
            ("claude", {**challenger, "verdicts": [challenger["verdicts"][0], path_verdict]}, None,
             "claude's recorded reveal is not a confirmed-v1 reveal: after scrubbing: "
             + decisions.witness_problem(redact.scrub_values(path_verdict))),
            ("codex", {**ROLE_REVEALS["builder"], "conflicts": [conflict("builder/0", "builder/0")]}, None,
             "codex's recorded reveal is not a confirmed-v1 reveal: "
             + decisions.conflict_problem({"conflicts": [conflict("builder/0", "builder/0")]},
                                          decisions.source_keys(ROLE_READINGS))),
            ("claude", challenger, "{", "the recorded reveal of claude is not valid JSON"),
        ]
        for seat, reveal, text, detail in cases:
            with self.subTest(detail=detail):
                root, c, t, stubs = self.recorded(seat, reveal)
                if text is not None:
                    respoil(c, t, c._last(TASK, "reveal.done", seat=seat), "reveal", text)
                self.assertBlocksWithNoCall(root, c, t, stubs, detail)
        with self.subTest(detail="no sha"):
            root, c, t, stubs = self.recorded()
            edit(c, c._last(TASK, "reveal.done", seat="claude"), lambda e: e.pop("sha"))
            self.assertBlocksWithNoCall(root, c, t, stubs, "claude's reveal.done has no sha")

    def test_the_seals_a_recorded_reveal_rests_on_are_checked_before_any_call(self):
        bad = without(stored(ROLE_READINGS["builder"]), "predicted_failures")
        cases = [
            ("codex resealed after the reveal", lambda c, t: reseal(c, t, "codex"),
             "the recorded reveals do not follow both sealed readings"),
            ("claude resealed after the reveal", lambda c, t: reseal(c, t, "claude"),
             "the recorded reveals do not follow both sealed readings"),
            ("seal without sha", lambda c, t: edit(c, c._sealed(t, "codex"), lambda e: e.pop("sha")),
             "codex's reading.sealed has no sha"),
            ("reading not JSON", lambda c, t: respoil(c, t, c._sealed(t, "codex"), "reading", "{"),
             "the recorded reading of codex is not valid JSON"),
            ("reading not a reading", lambda c, t: respoil(c, t, c._sealed(t, "codex"), "reading", canonical(bad)),
             f"codex's sealed reading is not a valid reading: {'; '.join(validate(bad, schemas.READING))}"),
        ]
        for name, spoil, detail in cases:
            with self.subTest(name):
                root, c, t, stubs = self.recorded()
                spoil(c, t)
                self.assertBlocksWithNoCall(root, c, t, stubs, detail)
        with self.subTest("a reveal recorded before its peer's seal"):
            root, c, t, bstub, cstub = project()
            c._read(t, "claude")
            record_reveal(c, t, "claude", ROLE_REVEALS["challenger"])
            self.assertBlocksWithNoCall(root, c, t, {"codex": bstub, "claude": cstub},
                                        "codex has no sealed reading before the recorded reveals")
        with self.subTest("a complete pair the settlement would refuse"):
            root, c, t, stubs = self.recorded("codex")
            spoilt = {**ROLE_REVEALS["challenger"], "conflicts": [conflict("builder/0", "challenger/7")]}
            record_reveal(c, t, "claude", spoilt)
            self.assertBlocksWithNoCall(root, c, t, stubs, "claude's recorded reveal is not a confirmed-v1 reveal: "
                                        "conflict 0: unknown target challenger/7")
        with self.subTest("a reseal before both reveals passes"):
            root, c, t, bstub, cstub = project()
            c._readings(t)
            reseal(c, t, "codex")
            record_reveal(c, t, "claude", ROLE_REVEALS["challenger"])
            self.assertEqual(ran(c, root), STOPPED)
            self.assertEqual((stages(bstub), stages(cstub)), (["reading", "reveal"], ["reading"]))

    def test_an_owed_reveal_needs_its_sealed_session_before_any_call(self):
        for name, change in (("null", lambda e: e.update(session=None)), ("absent", lambda e: e.pop("session"))):
            with self.subTest(owed="one", session=name):
                root, c, t, stubs = self.recorded()
                edit(c, c._sealed(t, "codex"), change)
                self.assertBlocksWithNoCall(root, c, t, stubs, "codex's sealed reading has no session to resume")
            with self.subTest(owed="both", session=name):
                root, c, t, bstub, cstub = project()
                c._readings(t)
                edit(c, c._sealed(t, "claude"), change)
                self.assertBlocksWithNoCall(root, c, t, {"codex": bstub, "claude": cstub},
                                            "claude's sealed reading has no session to resume")

    def test_a_record_from_the_other_batch_protocol_blocks_before_any_call(self):
        def both(*adds):
            return lambda c, t: [add(c, t) for add in adds]
        settled = lambda c, t: c.journal.append("reading.settled", TASK)                       # noqa: E731
        proposed = lambda c, t: c.journal.append("batch.proposed", TASK, seat="codex", **MARK)  # noqa: E731
        reviewed = lambda c, t: c.journal.append("batch.reviewed", TASK, seat="claude")          # noqa: E731
        cases = [
            (True, lambda c, t: record_reveal(c, t, "claude", ROLE_REVEALS["challenger"], {}),
             f"claude's reveal.done is not marked batch_protocol confirmed-v1, {MARKED}"),
            (True, lambda c, t: record_reveal(c, t, "claude", ROLE_REVEALS["challenger"], {"batch_protocol": "confirmed-v2"}),
             f"claude's reveal.done is not marked batch_protocol confirmed-v1, {MARKED}"),
            (True, lambda c, t: c.journal.append("batch.proposed", TASK, seat="codex"),
             f"codex's batch.proposed is not marked batch_protocol confirmed-v1, {MARKED}"),
            (True, reviewed, f"claude's batch.reviewed is not marked batch_protocol confirmed-v1, {MARKED}"),
            (True, card("reading"), "D-clamp-001-1 is a standalone reading card on a confirmed-v1 task"),
            (True, card("interface"), "D-clamp-001-1 is a standalone interface card on a confirmed-v1 task"),
            (True, both(lambda c, t: c.journal.append("contract.frozen", TASK, version=1, sha="sha256:x",
                                                      interface_protocol="whole"),
                        card("interface", interface_protocol="whole")),
             "D-clamp-001-1 is a standalone interface card on a confirmed-v1 task"),
            (True, both(card("reading"), reviewed), "D-clamp-001-1 is a standalone reading card on a confirmed-v1 task"),
            (True, both(reviewed, card("reading")),
             f"claude's batch.reviewed is not marked batch_protocol confirmed-v1, {MARKED}"),
            (False, lambda c, t: record_reveal(c, t, "claude", UNMARKED_REVEALS["challenger"]),
             f"claude's reveal.done is a confirmed-v1 record, {UNMARKED}"),
            (False, proposed, f"codex's batch.proposed is a confirmed-v1 record, {UNMARKED}"),
            (False, settled, f"reading.settled is a confirmed-v1 record, {UNMARKED}"),
            (False, lambda c, t: c.journal.append("contract.frozen", TASK, version=1, sha="sha256:x", **MARK),
             f"contract.frozen is a confirmed-v1 record, {UNMARKED}"),
            (False, both(settled, proposed), f"reading.settled is a confirmed-v1 record, {UNMARKED}"),
            (False, both(proposed, settled), f"codex's batch.proposed is a confirmed-v1 record, {UNMARKED}"),
        ]
        for batch, add, detail in cases:
            with self.subTest(detail=detail, batch=batch):
                root, c, t, bstub, cstub = project(batch=batch)
                c._readings(t)
                add(c, t)
                c2, codex, claude = resumed(root, c)
                before = evidence(c2, t)
                self.assertEqual(ran(c2, root), ("blocked", detail))
                self.assertEqual((codex.calls, claude.calls, evidence(c2, t)), ([], [], before))

    def test_a_legacy_card_on_an_unmarked_task_and_a_marked_reveal_on_a_marked_task_pass_the_check(self):
        root, c, t, bstub, cstub = project(batch=False)
        c.journal.append("dispute.opened", TASK, id="D-clamp-001-1", kind="reading", question="q")
        c._check_protocol(t)
        root, c, t, bstub, cstub = project()
        c._readings(t)
        record_reveal(c, t, "claude", ROLE_REVEALS["challenger"])
        c._check_protocol(t)
