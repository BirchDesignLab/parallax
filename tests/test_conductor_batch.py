import copy, json, shutil, unittest
from unittest import mock
from parallax import batch, briefs, decisions, folders, schemas
from parallax.conductor import _Stop
from parallax.ledger import parse_lines, sha256_text
from parallax.schemas import validate
from parallax.seats.base import SeatResult
from parallax.seats.stub import StubSeat
from tests.conductor_kit import kit_conductor, make_project
from tests.test_batch import (AGREE, CHOICE, FALLBACK, INTERFACE_TERM, PROPOSAL, REFUSE, REFUSED_PROPOSAL,
                              RETURNED_TERM, REVIEW, json_blocks, one_dispute, shown_digests)
from tests.test_decisions import NAN_WITNESS, ROLE_READINGS, ROLE_REVEALS, conflict, role_reveals
from tests.test_conductor_reading import resumed

# Task 19.3. Readings and reveals are Task 19.1's role-keyed fixture: builder/0 and challenger/0 are disputed,
# so the route is a batch. The builder is codex unless a test says otherwise.
TASK = "clamp-001"
MARK = {"batch_protocol": "confirmed-v1"}
USAGE = {"batch_propose": {"input": 11, "cached": 5, "output": 3}, "batch_review": {"input": 7, "cached": 0, "output": 2}}
PUBLIC = {"dispute.opened", "ruling.made", "contract.frozen", "reading.settled"}
SETTLED = {"mode": "confirmed", "common": [INTERFACE_TERM, RETURNED_TERM], "withdrawn": [],
           "choices": [{**CHOICE, "resolution": "pending", "selected": ""}],
           "refusal_reason": "", "affected": [], "detail": ""}
PATH_REASON = r'see "C:\Users\me\notes\why.txt"'

def answered(make):
    """A seat step whose output `make(req)` is validated like the stub's own, with this stage's usage."""
    def step(req):
        output = make(req)
        problems = validate(output, req.schema)
        return SeatResult(None if problems else output, req.session, "", USAGE[req.stage],
                          "; ".join(problems) if problems else None)
    return step

def proposes(base=PROPOSAL, **fields):
    """A builder that answers the packet it was shown: `base` bound to that packet's digest."""
    return answered(lambda req: {**copy.deepcopy(base), **fields, "packet_sha": shown_digests(req.brief)[0]})

def reviews(base=REVIEW, **fields):
    """A challenger that answers the packet and proposal it was shown."""
    def make(req):
        packet_sha, proposal_sha = shown_digests(req.brief)
        return {**copy.deepcopy(base), **fields, "packet_sha": packet_sha, "proposal_sha": proposal_sha}
    return answered(make)

def crashes(req):
    raise RuntimeError("the seat process died")

def sealed(reveals=ROLE_REVEALS, readings=ROLE_READINGS, propose=(), review=(), builder="codex"):
    """A project whose task has both readings sealed and, unless `reveals` is None, both marked reveals.

    The readings go through the stub seats. Reveals are recorded as Task 19.4's reveal step will
    record them: a stored artifact and a marked `reveal.done`. `propose` and `review` are the steps
    left for the builder's and the challenger's batch calls. Returns the builder's and challenger's stubs.
    """
    root = make_project()
    challenger = "claude" if builder == "codex" else "codex"
    stubs = {builder: StubSeat(builder, {"reading": [lambda req: copy.deepcopy(readings["builder"])],
                                         "batch_propose": list(propose)}),
             challenger: StubSeat(challenger, {"reading": [lambda req: copy.deepcopy(readings["challenger"])],
                                               "batch_review": list(review)})}
    c = kit_conductor(root, stubs["codex"], stubs["claude"])
    t = c._open(TASK, (root / "tasks/clamp-001.md").read_text(encoding="utf-8"), builder)
    c._readings(t)
    if reveals is not None:
        record_reveals(c, t, reveals)
    return root, c, t, stubs[builder], stubs[challenger]

def record_reveals(c, t, reveals, marks=None):
    for seat in t.seats:
        record_reveal(c, t, seat, reveals[t.role(seat)], (marks or {}).get(seat, MARK))

def record_reveal(c, t, seat, reveal, mark=MARK):
    sha = c._store(c._artifact_dir(t, seat, "reveal"), copy.deepcopy(reveal))
    c.journal.append("reveal.done", t.id, seat=seat, sha=sha, usage={"input": 1, "cached": 0, "output": 1}, **mark)

def confirm(c, t):
    """The settlement, or the outcome the step stopped with."""
    try:
        return c._confirm(t)
    except _Stop as stop:
        return stop.outcome

def stopped(c, t):
    """The outcome the step stopped with. Settling instead, or raising anything else, fails the test."""
    try:
        settlement = c._confirm(t)
    except _Stop as stop:
        return stop.outcome
    except Exception as error:
        raise AssertionError(f"the step raised {error!r} instead of stopping") from error
    raise AssertionError(f"the step settled instead of stopping: {settlement}")

def again(root, c, text=None, task=TASK):
    """A restarted conductor on the same project and home, its task reopened, with seats that have no steps."""
    c2, codex, claude = resumed(root, c)
    t = c2._open(task, text or (root / "tasks/clamp-001.md").read_text(encoding="utf-8"), None)
    return c2, t, {"codex": codex, "claude": claude}[t.builder], {"codex": codex, "claude": claude}[t.challenger]

def stages(seat):
    return [req.stage for req in seat.calls]

def batch_events(c, task=TASK):
    return [e for e in c.events(task) if e["type"].startswith("batch.")]

def expected_packet(c, t, readings=ROLE_READINGS, reveals=ROLE_REVEALS, precedents=()):
    """The packet built independently from the test's own inputs and the recorded shas."""
    inputs = {t.role(seat): {"reading": c._last(t.id, "reading.sealed", seat=seat)["sha"],
                             "reveal": c._last(t.id, "reveal.done", seat=seat)["sha"]} for seat in t.seats}
    return batch.packet(t.text, list(precedents), readings, reveals, inputs,
                        {"builder": t.builder, "challenger": t.challenger})

def rewrite(c, type, match=None, drop=False, **fields):
    """Change (or with `drop`, remove) the journal's `type` events matching `match`, as a hand edit would."""
    path = c.journal.path
    kept = []
    for event in parse_lines(path.read_text(encoding="utf-8")):
        if event["type"] == type and all(event.get(k) == v for k, v in (match or {}).items()):
            if drop:
                continue
            event.update(fields)
        kept.append(event)
    path.write_text("".join(json.dumps(e) + "\n" for e in kept), encoding="utf-8", newline="\n")

def repacked(c, change):
    """Rewrite the proposal checkpoint's packet with `change(packet)`, its packet_sha recomputed."""
    packet = copy.deepcopy(batch_events(c)[0]["packet"])
    change(packet)
    rewrite(c, "batch.proposed", packet=packet, packet_sha=batch.digest(packet))

def evidence(c, t):
    """Every byte of the journal and the task's artifacts."""
    files = {p.relative_to(t.dir).as_posix(): p.read_bytes() for p in (t.dir / "artifacts").rglob("*") if p.is_file()}
    return c.journal.path.read_bytes(), files

def opening_sha(t):
    return batch.digest({"task": t.id, "base": t.base, "seats": {"builder": t.builder, "challenger": t.challenger}})


class Fresh(unittest.TestCase):
    def test_a_batch_route_asks_the_builder_then_the_challenger_read_only(self):
        for builder in ("codex", "claude"):
            with self.subTest(builder=builder):
                at_review = []

                def review_step(req):
                    # The proposal is durable when the challenger runs, and nothing after it is.
                    events = c.events(TASK)
                    [proposed] = [e for e in events if e["type"] == "batch.proposed"]
                    at_review.append((c._stored(t, t.builder, "batch_propose", proposed["sha"]),
                                      [e["type"] for e in events if e["type"] in PUBLIC | {"batch.reviewed"}]))
                    return reviews()(req)

                root, c, t, bstub, cstub = sealed(propose=[proposes()], review=[review_step], builder=builder)
                self.assertEqual(confirm(c, t), SETTLED)
                self.assertEqual((stages(bstub), stages(cstub)), (["reading", "batch_propose"], ["reading", "batch_review"]))
                packet = expected_packet(c, t)
                propose_req, review_req = bstub.calls[-1], cstub.calls[-1]
                self.assertEqual(propose_req.brief, briefs.propose(packet, batch.digest(packet)))
                for seat, request, schema in ((t.builder, propose_req, schemas.PROPOSAL),
                                              (t.challenger, review_req, schemas.REVIEW)):
                    self.assertEqual((request.writable, request.cwd, request.session, request.schema),
                                     (False, c._clone_of(t, seat), c._sealed(t, seat)["session"], schema))
                proposed, reviewed = batch_events(c)
                self.assertEqual(list(proposed), ["ts", "type", "task", "batch_protocol", "seat", "opening", "packet",
                                                  "packet_sha", "sha", "usage"])
                self.assertEqual(list(reviewed), ["ts", "type", "task", "batch_protocol", "seat", "packet_sha",
                                                  "proposal_sha", "sha", "usage"])
                proposal = c._stored(t, t.builder, "batch_propose", proposed["sha"])
                review = c._stored(t, t.challenger, "batch_review", reviewed["sha"])
                self.assertEqual(
                    (proposed["batch_protocol"], proposed["seat"], proposed["opening"], proposed["packet"],
                     proposed["packet_sha"], proposed["sha"], proposed["usage"]),
                    ("confirmed-v1", t.builder, opening_sha(t), packet, batch.digest(packet), batch.digest(proposal),
                     USAGE["batch_propose"]))
                self.assertEqual(
                    (reviewed["batch_protocol"], reviewed["seat"], reviewed["packet_sha"], reviewed["proposal_sha"],
                     reviewed["sha"], reviewed["usage"]),
                    ("confirmed-v1", t.challenger, proposed["packet_sha"], proposed["sha"], batch.digest(review),
                     USAGE["batch_review"]))
                self.assertEqual(at_review, [(proposal, [])])
                # The challenger was shown exactly the packet and the accepted proposal the checkpoint names.
                self.assertEqual(json_blocks(review_req.brief), [packet, proposal])
                self.assertEqual(shown_digests(review_req.brief), [batch.digest(packet), batch.digest(proposal)])
                self.assertFalse(PUBLIC & {e["type"] for e in c.events(TASK)})
                self.assertFalse((root / ".parallax/run/clamp-001/cards").exists())

    def test_a_direct_route_settles_with_no_calls(self):
        root, c, t, bstub, cstub = sealed(one_dispute())
        settled = confirm(c, t)
        self.assertEqual((settled["mode"], [ch["members"] for ch in settled["choices"]]), ("direct", [["builder/0"]]))
        self.assertEqual((stages(bstub), stages(cstub), batch_events(c)), (["reading"], ["reading"], []))
        self.assertFalse(PUBLIC & {e["type"] for e in c.events(TASK)})

    def test_answers_that_scrub_to_the_same_words_block_a_direct_route(self):
        # The witness tells the two answers apart, but the answers themselves differ only in a directory.
        readings = {**ROLE_READINGS, "builder": {**ROLE_READINGS["builder"], "decisions": [
            {"question": "What if lo > hi?", "answer": r'Raise the error in "C:\a\errors.txt".', "why": "w"},
            ROLE_READINGS["builder"]["decisions"][1]]}}
        reveals = one_dispute(verdicts=[{**AGREE, "index": 1},
                                        {"index": 0, "agree": False, "counter": r'Raise the error in "D:\b\errors.txt".',
                                         "why": "w", "witness": NAN_WITNESS}])
        root, c, t, bstub, cstub = sealed(reveals, readings)
        outcome = stopped(c, t)
        self.assertEqual((outcome.status, outcome.detail),
                         ("blocked", "direct builder/0: a and b are the same after scrubbing"))
        self.assertEqual((stages(bstub), stages(cstub)), (["reading"], ["reading"]))

    def test_each_reveal_must_be_a_valid_marked_confirmed_reveal_before_any_call(self):
        legacy = {k: v for k, v in ROLE_REVEALS["challenger"].items() if k != "conflicts"}
        collapsing = {"scenario": "clamp(8, 9, 5)", "observation": "the log line written",
                      "theirs": r'logs "C:\left\clamp.log"', "mine": r'logs "D:\right\clamp.log"', "decided_by": ""}
        prefix = "{}'s recorded reveal is not a confirmed-v1 reveal: "
        cases = [  # (reveals, readings, marks, diagnostic)
            ({**ROLE_REVEALS, "challenger": legacy}, ROLE_READINGS, None, prefix.format("claude") + "$: missing 'conflicts'"),
            (role_reveals(builder={"conflicts": [conflict("builder/9", "builder/0")]}), ROLE_READINGS, None,
             prefix.format("codex") + "conflict 0: unknown source builder/9"),
            (role_reveals(challenger={"interface_ok": False, "interface_objection": "", "interface_replacement": "x"}),
             ROLE_READINGS, None,
             prefix.format("claude") + "interface_objection must say why you object when interface_ok is false"),
            (role_reveals(builder={"verdicts": []}), ROLE_READINGS, None,
             prefix.format("codex") + "verdicts must give exactly one index for each of 0..0, got []"),
            # The display values are checked too, even on a batch route.
            (role_reveals(challenger={"verdicts": [ROLE_REVEALS["challenger"]["verdicts"][0],
                                                   {**ROLE_REVEALS["challenger"]["verdicts"][1], "witness": collapsing}]}),
             ROLE_READINGS, None,
             prefix.format("claude") + 'after scrubbing: verdict 0: the witness predicts the same result under both '
             'answers (logs "<outside>/clamp.log"); give a scenario where the two answers commit to different results, '
             'or agree if you accept their whole answer'),
            (all_interface(r'Read "D:\right\schema.json"'),
             {**ROLE_READINGS, "builder": {**ROLE_READINGS["builder"], "interface": r'Read "C:\left\schema.json"'}}, None,
             prefix.format("claude") + "after scrubbing: interface_replacement is the same as the builder's interface; "
             "give the interface you want, or set interface_ok to true"),
        ]
        for seat in ("codex", "claude"):
            for mark in ({}, {"batch_protocol": None}, {"batch_protocol": "confirmed-v2"}):
                cases.append((ROLE_REVEALS, ROLE_READINGS, {seat: mark},
                              f"{seat}'s reveal.done is not marked batch_protocol confirmed-v1"))
        for reveals, readings, marks, detail in cases:
            with self.subTest(detail=detail, marks=marks):
                root, c, t, bstub, cstub = sealed(None, readings, propose=[proposes()], review=[reviews()])
                record_reveals(c, t, reveals, marks)
                self.assertEqual(stopped(c, t).detail, detail)
                self.assertEqual((stages(bstub), stages(cstub), batch_events(c)), (["reading"], ["reading"], []))

    def test_the_recorded_inputs_must_be_usable_and_in_order(self):
        def bad_reading(c, t):
            sha = c._store(c._artifact_dir(t, "codex", "reading"), {"decisions": [], "predicted_failures": []})
            c.journal.append("reading.sealed", TASK, seat="codex", sha=sha, session="codex-s9", usage={})
            record_reveals(c, t, ROLE_REVEALS)

        def not_json(c, t):
            record_reveals(c, t, ROLE_REVEALS)
            out = c._artifact_dir(t, "claude", "reveal")
            (out / "output.json").write_text("{not json", encoding="utf-8", newline="\n")
            c.journal.append("reveal.done", TASK, seat="claude", sha=sha256_text("{not json"), usage={}, **MARK)

        def resealed_after(c, t):
            record_reveals(c, t, ROLE_REVEALS)
            sealed_event = c._sealed(t, "codex")
            c.journal.append("reading.sealed", TASK, seat="codex", sha=sealed_event["sha"], session="codex-s9", usage={})

        cases = [  # (spoil the task before any batch call, diagnostic)
            (bad_reading, "codex's sealed reading is not a valid reading: $: missing 'interface'"),
            (not_json, "the recorded reveal of claude is not valid JSON"),
            (resealed_after, "the recorded reveals do not follow both sealed readings"),
            (lambda c, t: (record_reveals(c, t, ROLE_REVEALS), rewrite(c, "reveal.done", {"seat": "claude"}, sha=None)),
             "claude's reveal.done has no sha"),
            (lambda c, t: (record_reveals(c, t, ROLE_REVEALS), rewrite(c, "reading.sealed", {"seat": "codex"}, sha=None)),
             "codex's reading.sealed has no sha"),
            (lambda c, t: (record_reveals(c, t, ROLE_REVEALS), rewrite(c, "reading.sealed", {"seat": "codex"}, session=None)),
             "codex's sealed reading has no session to resume"),
            (lambda c, t: record_reveal(c, t, "codex", ROLE_REVEALS["builder"]),
             "claude has no sealed reading and reveal to settle"),
        ]
        for spoil, detail in cases:
            with self.subTest(detail=detail):
                root, c, t, bstub, cstub = sealed(None, propose=[proposes()], review=[reviews()])
                spoil(c, t)
                before = evidence(c, t)
                self.assertEqual(stopped(c, t).detail, detail)
                self.assertEqual((stages(bstub), stages(cstub), evidence(c, t)), (["reading"], ["reading"], before))

    def test_a_void_and_a_fresh_seal_before_both_reveals_still_settle(self):
        root, c, t, bstub, cstub = sealed(None, propose=[proposes()], review=[reviews()])
        first = c._sealed(t, "codex")
        c.journal.append("reading.voided", TASK, seat="codex", hits=["x"])
        c.journal.append("reading.sealed", TASK, seat="codex", sha=first["sha"], session="codex-s9", usage={})
        record_reveals(c, t, ROLE_REVEALS)
        self.assertEqual(confirm(c, t), SETTLED)
        self.assertEqual(bstub.calls[-1].session, "codex-s9")


def all_interface(replacement):
    """Every reading verdict agrees; the challenger objects to the interface with `replacement`."""
    return one_dispute(verdicts=[AGREE, {**AGREE, "index": 1}], interface_ok=False,
                       interface_objection="read the shared schema", interface_replacement=replacement)


class Replies(unittest.TestCase):
    def test_each_reply_is_checked_and_recorded_as_its_accepted_value(self):
        root, c, t, bstub, cstub = sealed(
            propose=[proposes(votes=[{"slot": "c/0", "sign": ["a"], "reason": PATH_REASON}])],
            review=[reviews(votes=[{"slot": "c/0", "sign": ["b"], "reason": r'per "D:\specs\nan.md"'}])])
        confirm(c, t)
        proposed, reviewed = batch_events(c)
        proposal = c._stored(t, "codex", "batch_propose", proposed["sha"])
        review = c._stored(t, "claude", "batch_review", reviewed["sha"])
        self.assertEqual((proposal["votes"][0]["reason"], review["votes"][0]["reason"]),
                         ('see "<outside>/why.txt"', 'per "<outside>/nan.md"'))
        self.assertEqual(json_blocks(cstub.calls[-1].brief)[1], proposal)

    def test_the_proposal_checkpoint_holds_the_accepted_value_before_the_review(self):
        def interrupted(req):
            raise RuntimeError("the review call stopped the step")
        root, c, t, bstub, cstub = sealed(
            propose=[proposes(votes=[{"slot": "c/0", "sign": ["a"], "reason": PATH_REASON}])], review=[interrupted])
        # Whatever stops the step after the proposal, its checkpoint already holds the accepted value.
        with self.assertRaises(Exception):
            c._confirm(t)
        (proposed,) = batch_events(c)
        proposal = c._stored(t, "codex", "batch_propose", proposed["sha"])
        self.assertEqual(proposal["votes"][0]["reason"], 'see "<outside>/why.txt"')
        self.assertEqual(proposed["sha"], batch.digest(proposal))

    def test_the_check_runs_on_the_accepted_value(self):
        # Two columns that differ only in a directory are the same words once scrubbed: rejected, then corrected.
        a = {"interface": "", "policy": r'Raise the error named in "C:\Users\me\a\errors.txt".'}
        b = {"interface": "", "policy": r'Raise the error named in "D:\other\errors.txt".'}
        root, c, t, bstub, cstub = sealed(propose=[proposes(choices=[{**CHOICE, "a": a, "b": b}]), proposes()],
                                          review=[reviews()])
        self.assertEqual(confirm(c, t), SETTLED)
        self.assertIn("choice c/0: a and b are the same", bstub.calls[2].brief)

    def test_a_bad_reply_is_retried_once(self):
        root, c, t, bstub, cstub = sealed(propose=[proposes(votes=[]), proposes()],
                                          review=[answered(lambda req: {}), reviews()])
        self.assertEqual(confirm(c, t), SETTLED)
        first, second = bstub.calls[1:]
        self.assertEqual(second.brief, briefs.rejected(
            first.brief, "missing vote for c/0\npreference for c/0 must be an answer you sign"))
        # A schema failure retries the same request; a semantic one appends its reason.
        self.assertEqual(cstub.calls[1].brief, cstub.calls[2].brief)
        proposed, _ = batch_events(c)
        self.assertEqual(c._stored(t, "codex", "batch_propose", proposed["sha"])["votes"], PROPOSAL["votes"])
        root, c, t, bstub, cstub = sealed(propose=[proposes()], review=[reviews(votes=[]), reviews()])
        self.assertEqual(confirm(c, t), SETTLED)
        self.assertEqual(cstub.calls[2].brief, briefs.rejected(cstub.calls[1].brief, "missing vote for c/0"))

    def test_two_bad_replies_block_before_the_checkpoint(self):
        root, c, t, bstub, cstub = sealed(propose=[proposes(votes=[])] * 2)
        outcome = stopped(c, t)
        detail = "codex failed at batch_propose: missing vote for c/0\npreference for c/0 must be an answer you sign"
        self.assertEqual((outcome.status, outcome.detail), ("blocked", detail))
        self.assertEqual([e["stage"] for e in c.events(TASK) if e["type"] == "seat.failed"], ["batch_propose"])
        self.assertEqual((batch_events(c), stages(cstub)), ([], ["reading"]))
        root, c, t, bstub, cstub = sealed(propose=[proposes()], review=[reviews(votes=[])] * 2)
        outcome = stopped(c, t)
        self.assertEqual((outcome.status, outcome.detail), ("blocked", "claude failed at batch_review: missing vote for c/0"))
        self.assertEqual([e["type"] for e in batch_events(c)], ["batch.proposed"])

    def test_a_refusal_is_a_successful_reply_and_uses_no_retry(self):
        refuse = {**REFUSE, "affected": ["challenger/0"], "refusal_reason": "the B column misstates my bounds predicate"}
        root, c, t, bstub, cstub = sealed(propose=[proposes()], review=[reviews(refuse)])
        settled = confirm(c, t)
        self.assertEqual((settled["mode"], settled["refusal_reason"]),
                         ("refusal", "challenger: the B column misstates my bounds predicate"))
        self.assertEqual((stages(cstub), [e["type"] for e in batch_events(c)]),
                         (["reading", "batch_review"], ["batch.proposed", "batch.reviewed"]))
        self.assertNotIn("seat.failed", [e["type"] for e in c.events(TASK)])
        # A builder that refuses is answered by a refusing challenger, and that settles too.
        root, c, t, bstub, cstub = sealed(propose=[proposes(REFUSED_PROPOSAL)], review=[reviews(REFUSE)])
        settled = confirm(c, t)
        self.assertEqual((settled["mode"], settled["affected"]), ("refusal", ["builder/0", "builder/1", "challenger/0"]))

    def test_a_refusal_with_an_incomplete_fallback_settles_blocked_and_resumes_with_no_calls(self):
        blocked = {"mode": "blocked", "common": [], "withdrawn": [], "choices": [],
                   "refusal_reason": "challenger: the identity promise is also at stake", "affected": ["builder/1"],
                   "detail": "the fallback leaves out builder/1"}
        root, c, t, bstub, cstub = sealed(propose=[proposes(fallback=FALLBACK)], review=[reviews(REFUSE)])
        self.assertEqual(confirm(c, t), blocked)
        before = evidence(c, t)
        c2, t2, b2, ch2 = again(root, c)
        self.assertEqual(confirm(c2, t2), blocked)
        self.assertEqual((b2.calls, ch2.calls, evidence(c2, t2)), ([], [], before))
        self.assertFalse(PUBLIC & {e["type"] for e in c2.events(TASK)})

    def test_naming_the_other_seats_clone_blocks_either_call(self):
        def leaking(inner, other):
            def step(req):
                result = inner(req)
                leak = json.dumps({"command": f"type {c._clone_of(t, other)}\\tests\\x.py"})
                return SeatResult(result.output, result.session, leak, result.usage, result.error)
            return step

        root, c, t, bstub, cstub = sealed(review=[reviews()])
        bstub.script["batch_propose"] = [leaking(proposes(), "claude")]
        outcome = stopped(c, t)
        self.assertIn("codex failed at batch_propose: named the other seat's folder", outcome.detail)
        self.assertEqual((batch_events(c), stages(cstub)), ([], ["reading"]))
        root, c, t, bstub, cstub = sealed(propose=[proposes()])
        cstub.script["batch_review"] = [leaking(reviews(), "codex")]
        outcome = stopped(c, t)
        self.assertIn("claude failed at batch_review: named the other seat's folder", outcome.detail)
        self.assertEqual([e["type"] for e in batch_events(c)], ["batch.proposed"])

    def test_a_folder_that_is_no_longer_private_blocks_the_review(self):
        root, c, t, bstub, cstub = sealed(propose=[proposes()], review=[crashes])
        with self.assertRaises(RuntimeError):
            c._confirm(t)
        c2, t2, b2, ch2 = again(root, c)
        ch2.script["batch_review"] = [reviews()]
        with mock.patch.object(folders, "is_private", return_value=False):
            outcome = stopped(c2, t2)
        self.assertEqual((outcome.status, outcome.detail), ("blocked", "the task's state folder is no longer private"))
        self.assertEqual((b2.calls, ch2.calls, [e["type"] for e in batch_events(c2)]), ([], [], ["batch.proposed"]))


class Restart(unittest.TestCase):
    def test_with_no_checkpoint_the_builder_proposes_again(self):
        root, c, t, bstub, cstub = sealed(propose=[crashes])
        with self.assertRaises(RuntimeError):
            c._confirm(t)
        self.assertEqual(batch_events(c), [])
        c2, t2, b2, ch2 = again(root, c)
        b2.script["batch_propose"], ch2.script["batch_review"] = [proposes()], [reviews()]
        self.assertEqual(confirm(c2, t2), SETTLED)
        self.assertEqual((stages(b2), stages(ch2)), (["batch_propose"], ["batch_review"]))
        self.assertEqual([e["type"] for e in batch_events(c2)], ["batch.proposed", "batch.reviewed"])

    def test_with_a_proposal_checkpoint_only_the_challenger_runs(self):
        votes = [{"slot": "c/0", "sign": ["a"], "reason": PATH_REASON}]
        root, c, t, bstub, cstub = sealed(propose=[proposes(votes=votes)], review=[crashes])
        with self.assertRaises(RuntimeError):
            c._confirm(t)
        shown = cstub.calls[-1].brief
        self.assertIn('see \\"<outside>/why.txt\\"', shown)
        c2, t2, b2, ch2 = again(root, c)
        ch2.script["batch_review"] = [reviews()]
        expected = {**SETTLED, "choices": [{**CHOICE, "resolution": "pending", "selected": ""}]}
        self.assertEqual(confirm(c2, t2), expected)
        self.assertEqual((stages(b2), stages(ch2)), ([], ["batch_review"]))
        # After the restart the challenger sees the same bytes: the pinned packet and the accepted proposal.
        self.assertEqual(ch2.calls[0].brief, shown)
        self.assertEqual([e["type"] for e in batch_events(c2)], ["batch.proposed", "batch.reviewed"])

    def test_with_both_checkpoints_neither_seat_runs(self):
        mutual = {**SETTLED, "choices": [{**CHOICE, "resolution": "mutual", "selected": "a"}]}
        root, c, t, bstub, cstub = sealed(propose=[proposes()],
                                          review=[reviews(votes=[{"slot": "c/0", "sign": ["a", "b"], "reason": "both"}])])
        self.assertEqual(confirm(c, t), mutual)
        before = evidence(c, t)
        c2, t2, b2, ch2 = again(root, c)
        self.assertEqual(confirm(c2, t2), mutual)
        self.assertEqual((b2.calls, ch2.calls, evidence(c2, t2)), ([], [], before))
        self.assertEqual([e["type"] for e in batch_events(c2)], ["batch.proposed", "batch.reviewed"])

    def test_the_pinned_packet_keeps_its_precedents(self):
        def ruling(task, n, question):
            return dict(dispute=f"D-{task}-{n}", kind="reading", question=question, choice="a", text=f"{question} A.",
                        scope="project", limitation="", **{"while": ""})

        root, c, t, bstub, cstub = sealed(None, propose=[proposes()], review=[crashes])
        c.journal.append("ruling.made", "other-001", **ruling("other-001", 1, "Earlier?"))
        c.journal.append("ruling.made", TASK, **ruling(TASK, 9, "Own?"))      # this task's own: never in force
        record_reveals(c, t, ROLE_REVEALS)
        with self.assertRaises(RuntimeError):
            c._confirm(t)
        snapshot = [{"id": "P-1", "question": "Earlier?", "ruling": "Earlier? A.", "while": "", "task": "other-001"}]
        packet = expected_packet(c, t, precedents=snapshot)
        self.assertEqual(json_blocks(bstub.calls[-1].brief)[0]["precedents"], snapshot)
        c.journal.append("ruling.made", "other-002", **ruling("other-002", 1, "Later?"))
        self.assertEqual(len(decisions.precedents(c.events())), 3)
        c2, t2, b2, ch2 = again(root, c)
        ch2.script["batch_review"] = [reviews()]
        self.assertEqual(confirm(c2, t2), SETTLED)
        self.assertEqual(json_blocks(ch2.calls[0].brief)[0], packet)
        self.assertEqual(shown_digests(ch2.calls[0].brief)[0], batch.digest(packet))

    def test_a_packet_reloaded_with_sorted_keys_still_resumes(self):
        for review_done in (False, True):
            with self.subTest(review_done=review_done):
                root, c, t, bstub, cstub = sealed(propose=[proposes()], review=[reviews() if review_done else crashes])
                if review_done:
                    confirm(c, t)
                else:
                    with self.assertRaises(RuntimeError):
                        c._confirm(t)
                sha = batch_events(c)[0]["packet_sha"]
                rewrite(c, "batch.proposed", packet=json.loads(batch.canonical(batch_events(c)[0]["packet"])))
                self.assertEqual(batch_events(c)[0]["packet_sha"], sha)
                c2, t2, b2, ch2 = again(root, c)
                ch2.script["batch_review"] = [reviews()]
                self.assertEqual(confirm(c2, t2), SETTLED)
                self.assertEqual(stages(ch2), [] if review_done else ["batch_review"])

    def test_a_checkpoint_that_no_longer_matches_blocks(self):
        def nested_zero(packet):
            packet["sources"][0]["agree"] = 0

        def other_inputs(packet):
            packet["inputs"]["challenger"]["reveal"] = "sha256:" + "0" * 64

        def duplicate(c, type):
            event = next(e for e in batch_events(c) if e["type"] == type)
            c.journal.append(type, TASK, **{k: v for k, v in event.items() if k not in ("ts", "type", "task")})

        def review_first(c):
            path = c.journal.path
            events = parse_lines(path.read_text(encoding="utf-8"))
            p = next(i for i, e in enumerate(events) if e["type"] == "batch.proposed")
            r = next(i for i, e in enumerate(events) if e["type"] == "batch.reviewed")
            events[p], events[r] = events[r], events[p]
            path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8", newline="\n")

        proposal = "the batch.proposed checkpoint "
        review = "the batch.reviewed checkpoint "
        cases = [  # (break the state after a complete run, the diagnostic, task text on restart)
            (lambda c, t: repacked(c, nested_zero), proposal + "does not match today's sources", None),
            (lambda c, t: repacked(c, lambda p: p.update(extra="x")), proposal + "has a packet with other fields", None),
            (lambda c, t: repacked(c, other_inputs), proposal + "does not match today's inputs", None),
            (lambda c, t: repacked(c, lambda p: p.update(precedents=[{}])), proposal + "has malformed precedents", None),
            (lambda c, t: rewrite(c, "batch.proposed", packet={**batch_events(c)[0]["packet"], "task": "x"}),
             proposal + "has a packet that does not match its packet_sha", None),
            (lambda c, t: None, proposal + "does not match today's task", "Add clamp to clamplib.\n"),
            (lambda c, t: rewrite(c, "batch.proposed", seat="claude"), proposal + "was not written by the builder codex", None),
            (lambda c, t: rewrite(c, "batch.proposed", batch_protocol=None),
             proposal + "is not marked batch_protocol confirmed-v1", None),
            (lambda c, t: rewrite(c, "batch.proposed", sha=None), proposal + "has no sha", None),
            (lambda c, t: rewrite(c, "batch.proposed", usage={"input": "11"}), proposal + "has malformed usage", None),
            (lambda c, t: rewrite(c, "batch.proposed", opening="sha256:" + "0" * 64),
             proposal + "belongs to another opening", None),
            (lambda c, t: record_reveal(c, t, "claude", ROLE_REVEALS["challenger"]),
             proposal + "comes before a recorded reveal", None),
            (lambda c, t: c.journal.append("reading.sealed", TASK, seat="codex", sha=c._sealed(t, "codex")["sha"],
                                           session="codex-s9", usage={}),
             "the recorded reveals do not follow both sealed readings", None),
            (lambda c, t: duplicate(c, "batch.proposed"), "clamp-001 has 2 batch.proposed checkpoints", None),
            (lambda c, t: rewrite(c, "batch.reviewed", batch_protocol="v0"),
             review + "is not marked batch_protocol confirmed-v1", None),
            (lambda c, t: rewrite(c, "batch.reviewed", seat="codex"), review + "was not written by the challenger claude", None),
            (lambda c, t: rewrite(c, "batch.reviewed", packet_sha="sha256:" + "1" * 64), review + "names a different packet", None),
            (lambda c, t: rewrite(c, "batch.reviewed", proposal_sha="sha256:" + "2" * 64),
             review + "names a different proposal", None),
            (lambda c, t: duplicate(c, "batch.reviewed"), "clamp-001 has 2 batch.reviewed checkpoints", None),
            (lambda c, t: rewrite(c, "batch.proposed", drop=True), review + "has no batch.proposed before it", None),
            (lambda c, t: review_first(c), review + "has no batch.proposed before it", None),
        ]
        for spoil, detail, text in cases:
            with self.subTest(detail=detail):
                root, c, t, bstub, cstub = sealed(propose=[proposes()], review=[reviews()])
                confirm(c, t)
                spoil(c, t)
                before = evidence(c, t)
                c2, t2, b2, ch2 = again(root, c, text)
                outcome = stopped(c2, t2)
                self.assertEqual((outcome.status, outcome.detail), ("blocked", detail))
                self.assertEqual((b2.calls, ch2.calls, evidence(c2, t2)), ([], [], before))

    def test_a_stored_reply_must_be_exactly_what_the_fresh_path_stores(self):
        unscrubbed = {"slot": "c/0", "sign": ["a"], "reason": PATH_REASON}

        def proposal_of(c, t):
            return c._stored(t, "codex", "batch_propose", batch_events(c)[0]["sha"])

        def review_of(c, t):
            return c._stored(t, "claude", "batch_review", batch_events(c)[1]["sha"])

        def replace(c, t, stub, type, text):
            """Write `text` as the checkpoint's artifact and point the checkpoint at its sha."""
            out = stub.calls[1].out_dir / "output.json"
            out.write_text(text, encoding="utf-8", newline="\n")
            rewrite(c, type, sha=sha256_text(text))

        def spoilers(stage, type, reply_of, what):
            def stub_of(bstub, cstub):
                return bstub if stage == "batch_propose" else cstub
            seat = "codex" if stage == "batch_propose" else "claude"
            prefix = f"the {type} checkpoint holds a {what} "
            semantic = {"batch_propose": dict(votes=[]), "batch_review": dict(votes=[])}[stage]
            semantic_error = ("missing vote for c/0\npreference for c/0 must be an answer you sign"
                              if stage == "batch_propose" else "missing vote for c/0")
            return [
                (lambda c, t, b, ch: (stub_of(b, ch).calls[1].out_dir / "output.json").unlink(),
                 f"the recorded {stage} of {seat} is missing from the state folder"),
                (lambda c, t, b, ch: (stub_of(b, ch).calls[1].out_dir / "output.json").write_text(
                    batch.canonical(reply_of(c, t)) + " ", encoding="utf-8", newline="\n"),
                 f"the recorded {stage} of {seat} is missing from the state folder"),
                (lambda c, t, b, ch: replace(c, t, stub_of(b, ch), type, "{not json"),
                 f"the recorded {stage} of {seat} is not valid JSON"),
                (lambda c, t, b, ch: replace(c, t, stub_of(b, ch), type,
                                             batch.canonical({**reply_of(c, t), "decision": "maybe"})),
                 prefix + "that does not match its schema: $.decision: expected one of "
                 + ("['propose', 'refuse']" if stage == "batch_propose" else "['attest', 'refuse']")),
                (lambda c, t, b, ch: replace(c, t, stub_of(b, ch), type,
                                             batch.canonical({**reply_of(c, t), **semantic})),
                 f"the {type} checkpoint holds a {what} that no longer passes its checks: {semantic_error}"),
                (lambda c, t, b, ch: replace(c, t, stub_of(b, ch), type,
                                             batch.canonical({**reply_of(c, t), "votes": [unscrubbed]})),
                 prefix + "that is not its accepted value"),
                (lambda c, t, b, ch: replace(c, t, stub_of(b, ch), type, json.dumps(reply_of(c, t))),
                 prefix + "whose canonical digest is not its sha"),
            ]

        groups = [("proposal, before the review", False, spoilers("batch_propose", "batch.proposed", proposal_of, "proposal")),
                  ("proposal, after the review", True, spoilers("batch_propose", "batch.proposed", proposal_of, "proposal")),
                  ("review", True, spoilers("batch_review", "batch.reviewed", review_of, "review"))]
        for group, review_done, cases in groups:
            for spoil, detail in cases:
                with self.subTest(group=group, detail=detail):
                    root, c, t, bstub, cstub = sealed(propose=[proposes()], review=[reviews() if review_done else crashes])
                    if review_done:
                        confirm(c, t)
                    else:
                        with self.assertRaises(RuntimeError):
                            c._confirm(t)
                    spoil(c, t, bstub, cstub)
                    before = evidence(c, t)
                    c2, t2, b2, ch2 = again(root, c)
                    ch2.script["batch_review"] = [reviews()]
                    outcome = stopped(c2, t2)
                    self.assertEqual((outcome.status, outcome.detail), ("blocked", detail))
                    self.assertEqual((b2.calls, ch2.calls, evidence(c2, t2)), ([], [], before))

    def test_a_consistent_packet_on_a_direct_route_is_not_a_proposal(self):
        root, c, t, bstub, cstub = sealed(one_dispute())
        packet = expected_packet(c, t, reveals=one_dispute())
        c.journal.append("batch.proposed", TASK, seat="codex", opening=opening_sha(t), packet=packet,
                         packet_sha=batch.digest(packet), sha="sha256:" + "3" * 64, usage={}, **MARK)
        before = evidence(c, t)
        outcome = stopped(c, t)
        self.assertEqual(outcome.detail, "the batch.proposed checkpoint is on a direct route")
        self.assertEqual((stages(bstub), stages(cstub), evidence(c, t)), (["reading"], ["reading"], before))

    def test_a_checkpoint_from_another_opening_is_refused(self):
        # Two openings of the same text with the same seats build the same packet and the same proposal bytes.
        root, c, t, bstub, cstub = sealed(propose=[proposes()], review=[crashes])
        with self.assertRaises(RuntimeError):
            c._confirm(t)
        bstub.script["reading"] = [lambda req: copy.deepcopy(ROLE_READINGS["builder"])]
        cstub.script["reading"] = [lambda req: copy.deepcopy(ROLE_READINGS["challenger"])]
        # Task 19.9: clamp-002's reading takes the precedents, which are refused while another history holds
        # confirmed-v1 records under an opening without the marker, as this module's fixture does. Mark it.
        events = parse_lines(c.journal.path.read_text(encoding="utf-8"))
        self.assertEqual((events[0]["type"], events[0]["task"]), ("task.opened", TASK))
        events[0]["batch_protocol"] = "confirmed-v1"
        c.journal.path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8", newline="\n")
        t2 = c._open("clamp-002", t.text, "codex")
        c._readings(t2)
        record_reveals(c, t2, ROLE_REVEALS)
        proposed = batch_events(c)[0]
        c.journal.append("batch.proposed", "clamp-002",
                         **{k: v for k, v in proposed.items() if k not in ("ts", "type", "task")})
        source = bstub.calls[1].out_dir
        shutil.copytree(source, t2.dir / "artifacts" / f"99-codex-batch_propose")
        self.assertEqual(c._stored(t2, "codex", "batch_propose", proposed["sha"]),
                         c._stored(t, "codex", "batch_propose", proposed["sha"]))
        cstub.script["batch_review"] = [reviews()]
        calls = (len(bstub.calls), len(cstub.calls))
        outcome = stopped(c, t2)
        self.assertEqual(outcome.detail, "the batch.proposed checkpoint belongs to another opening")
        self.assertEqual((len(bstub.calls), len(cstub.calls)), calls)


if __name__ == "__main__":
    unittest.main()
