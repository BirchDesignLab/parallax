import json, os, re, unittest
from pathlib import Path
from unittest import mock
from parallax import gitops, receipt
from parallax.conductor import Conductor
from parallax.config import repo_key
from parallax.ledger import sha256_text
from tests.conductor_kit import CLAMP_BAD, CLAMP_OK, FILE, MUTANTS, PROBES, WEAK_PROBES, builds, probes, responds
from tests.helpers import run_git
from tests.test_batch import A_POLICY, QUESTION
from tests.test_cli import call
from tests.test_conductor_batch import proposes, reviews
from tests.test_conductor_disputes import NAN_PROBE, message
from tests.test_conductor_reading import resumed
from tests.test_conductor_settled import MUTUAL, MUTUAL_REVIEW, TASK, TASK_FILE, ZERO, marked, rewrite, run, told, two_cards
from tests.test_conductor_ruled import rule
from tests.test_conductor_frozen import (CLIP, ONE, RETURNED, THREE, TWO, blocks, contract, freezes, in_seat_order,
                                         normalized, on_main, rewrite_main, seated)

# Task 19.8. After a failed crossing a confirmed-v1 task opens the cards any task opens (check, mutant,
# unresolved), numbered above its settlement's, and `rule` rules them as on any task. Every reader checks that
# the crossing before a card opens it and that its ruling is one `rule` writes. A ruling that amends the
# contract freezes the next version from the settlement's base plus every amendment since v1, bound to the
# settlement and checked down to its sha, and may not be skipped. The receipt counts each ruling once.
FOUR, FIVE, SIX, SEVEN = (f"D-clamp-001-{n}" for n in (4, 5, 6, 7))
NOTE = "The upper bound is inclusive."
AGAIN = "Inclusive means clamp(99, 1, 10) is 10."
PROMISED = "What is no longer promised?"
BOUND = {"interface_protocol": "whole", "batch_protocol": "confirmed-v1"}
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "task19-8"
BASE = (RETURNED, (QUESTION, A_POLICY, f"ruled {ONE}"))
MISSING = "contract v2 is missing after a ruling that amends the contract"
NOT_UTF8 = "has a text, while or limitation that is not UTF-8 text"
_ELAPSED = re.compile(r"(?m)^(Ran \d+ tests? in )\d+\.\d+s$")

def versioned(version, *more):
    """Contract `version` of the two-card task ruled a and b: v1's terms, then what later rulings added."""
    return contract(CLIP, *BASE, *more).replace("(v1)", f"(v{version})")

def ruled_cards(test):
    """A two-card settlement with both cards ruled (a, then b), ready to freeze and build."""
    root, c, t, settled = two_cards(test)
    test.assertEqual((rule(root, ONE, "a")[0], rule(root, TWO, "b")[0]), (0, 0))
    return root, c, t, settled

def contested(test, codex_after=(), claude_after=()):
    """A bad build both seats contest: the run stops at one check card, D-clamp-001-3."""
    root, c, t, settled = ruled_cards(test)
    c2, codex, claude = seated(root, c, {"build": [builds(CLAMP_BAD)], "respond": [responds("contest"), *codex_after]},
                               {"probe": [probes()], "respond": [responds("contest"), *claude_after]})
    outcome = run(c2, root)
    test.assertEqual((told(outcome), [d.kind for d in outcome.disputes]),
                     (("needs_ruling", f"needs a ruling on {THREE}"), ["check"]))
    return root, c2, t, settled, codex, claude

def card(c, dispute):
    return next(e for e in c.events(TASK) if e["type"] == "dispute.opened" and e["id"] == dispute)

def contract_file(root, version):
    return (root / ".parallax/run" / TASK / f"contract-v{version}.md").read_text(encoding="utf-8")

def versions(history):
    return [e["version"] for e in history if e["type"] == "contract.frozen"]

def killed_before_the_repair(test, c, root):
    """Run until the amended contract is frozen, then die where the loser's repair would start."""
    with mock.patch.object(Conductor, "_repairs", side_effect=RuntimeError("killed before the repair")) as repairs:
        with test.assertRaisesRegex(RuntimeError, "killed before the repair"):
            c.run(root / TASK_FILE)
    test.assertEqual(repairs.call_count, 1)

def the(kind, **match):
    """Find the first `kind` event with these fields in a list of events."""
    def find(events):
        return next(e for e in events if e["type"] == kind and all(e.get(k) == v for k, v in match.items()))
    return find

def last(kind):
    def find(events):
        return next(e for e in reversed(events) if e["type"] == kind)
    return find

def cases(test, root, c, start, tampered, *ruling):
    """From the journal bytes `start`, each (change, detail): every reader refuses the changed journal with it."""
    for number, (change, detail) in enumerate(tampered):
        with test.subTest(case=number, detail=detail):
            c.journal.path.write_bytes(start)
            rewrite(c, change)
            blocks(test, root, c, detail, *ruling)
    c.journal.path.write_bytes(start)

def in_order(history):
    """`in_seat_order`, and the two responses the seats made at once (to one crossing, under the same rulings)
    put builder first. A seat that answers alone (a repair) keeps its place."""
    opened = next(e for e in history if e["type"] == "task.opened")
    seats = [opened["builder"], opened["challenger"]]
    out = []
    for event in in_seat_order(history):
        last = out[-1] if out else None
        if (event["type"] == "response.done" and last is not None and last["type"] == "response.done"
                and (last.get("round"), last.get("ruling")) == (event.get("round"), event.get("ruling"))
                and seats.index(last["seat"]) > seats.index(event["seat"])):
            out.insert(len(out) - 1, event)
        else:
            out.append(event)
    return out

def timeless(history):
    """`history` without the one token of a card's check output that the clock decides: the seconds unittest
    reports. The count, the failure and the result stay."""
    return [{**e, "evidence": _ELAPSED.sub(r"\1<seconds>s", e["evidence"])} if e["type"] == "dispute.opened" else e
            for e in history]

def kept(test, name, record):
    """As Task 19.7's `kept`, under tests/fixtures/task19-8/."""
    path = FIXTURES / name
    if os.environ.get("PARALLAX_WRITE_FIXTURES") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    test.assertEqual(json.loads(path.read_text(encoding="utf-8")), record)


class Kept(unittest.TestCase):
    def test_responses_made_at_once_are_put_builder_first_and_a_repair_keeps_its_place(self):
        def e(type, seat=None, **more):
            return {"type": type, **({"seat": seat} if seat else {}), **more}

        opened = e("task.opened", builder="codex", challenger="claude")
        ruling, repair = e("ruling.made", dispute=THREE), e("response.done", "codex", round=1, ruling=[THREE])
        both = [opened, e("response.done", "codex", round=1, ruling=[]), e("response.done", "claude", round=1, ruling=[]),
                ruling, repair]
        for first, second in (("codex", "claude"), ("claude", "codex")):
            with self.subTest(first=first):
                self.assertEqual(in_order([opened, e("response.done", first, round=1, ruling=[]),
                                           e("response.done", second, round=1, ruling=[]), ruling, repair]), both)
        # Responses to different crossings, or under different rulings, were not made at once.
        for other in ({"round": 2, "ruling": []}, {"round": 1, "ruling": [THREE]}):
            with self.subTest(other=other):
                apart = [opened, e("response.done", "claude", round=1, ruling=[]), e("response.done", "codex", **other)]
                self.assertEqual(in_order(apart), apart)

    def test_only_the_seconds_of_a_check_output_are_taken_out_of_a_card(self):
        def opened(seconds, count=5):
            return {"type": "dispute.opened", "id": THREE, "evidence":
                    f".F...\nAssertionError: 11 != 10\n\nRan {count} tests in {seconds}s\n\nFAILED (failures=1)\n"}

        fast, slow = timeless([opened("0.001")]), timeless([opened("12.345")])
        self.assertEqual(fast, slow)
        self.assertEqual(fast[0]["evidence"],
                         ".F...\nAssertionError: 11 != 10\n\nRan 5 tests in <seconds>s\n\nFAILED (failures=1)\n")
        self.assertNotEqual(fast, timeless([opened("0.001", count=6)]))
        # Nothing else is a card's check output.
        response = {"type": "response.done", "evidence": "Ran 5 tests in 0.001s"}
        self.assertEqual(timeless([response]), [response])


class Ruled(unittest.TestCase):
    """A failed crossing's card on a confirmed-v1 task, ruled through the CLI, and what the run then does."""

    def test_a_check_ruling_freezes_contract_v2_and_the_loser_repairs(self):
        root, c, t, settled, codex, claude = contested(self)
        question = card(c, THREE)["question"]
        self.assertEqual(rule(root, THREE, "b", "--note", NOTE)[0], 0)
        [ruling] = [e for e in c.events(TASK) if e["type"] == "ruling.made" and e["dispute"] == THREE]
        self.assertEqual({k: v for k, v in ruling.items() if k not in ("ts", "type", "task")},
                         {"dispute": THREE, "kind": "check", "question": question, "choice": "b", "text": NOTE,
                          "scope": "project", "while": "", "limitation": ""})
        # The run dies after contract v2 is frozen. A fresh conductor reuses it: only the builder's repair is left.
        killed_before_the_repair(self, c, root)
        self.assertEqual(versions(c.events(TASK)), [1, 2])
        fixed = responds("concede", files={FILE: CLAMP_OK}, mutants=MUTANTS)
        c2, codex2, claude2 = seated(root, c, {"respond": [fixed]}, {})
        with mock.patch.object(receipt, "verdict", wraps=receipt.verdict) as verdict:
            outcome = run(c2, root)
        self.assertEqual(told(outcome)[0], "landed", told(outcome))
        expected = versioned(2, (question, NOTE, f"ruled {THREE}"))
        self.assertEqual((contract_file(root, 1), contract_file(root, 2)), (versioned(1), expected))
        history = on_main(root)
        frozen = [e for e in history if e["type"] == "contract.frozen"]
        self.assertEqual([{k: v for k, v in e.items() if k not in ("ts", "type", "task")} for e in frozen],
                         [{"version": n, "sha": sha256_text(text), **BOUND, "settlement_sha": settled["settlement_sha"]}
                          for n, text in ((1, versioned(1)), (2, expected))])
        self.assertEqual(gitops.show_file(root, "main", f".parallax/contracts/{TASK}.md"), expected)
        # The builder lost: its repair is a respond call whose brief gives the ruling as the human's.
        [repair] = codex2.calls
        self.assertEqual((repair.stage, claude2.calls), ("respond", []))
        self.assertIn(f"## The human's ruling\n\n```\n{NOTE}\n```\n", repair.brief)
        # The receipt: one failed crossing, and three rulings by the human, each counted once, though the first
        # card stands for two members of the settlement.
        self.assertEqual(verdict.call_args_list, [mock.call("behavior", 1, 3, [])])
        self.assertEqual(len(next(e for e in history if e["type"] == "ruling.made" and e["dispute"] == ONE)["members"]), 2)
        self.assertIn("Verdict: ruled", message(root))
        # Each seat call is charged once, on the event that records it.
        charged = [(e["type"], e["seat"]) for e in history if "usage" in e]
        self.assertEqual(sorted(set(charged)), sorted(
            (kind, seat) for kind, seats in (("reading.sealed", "both"), ("reveal.done", "both"),
                                             ("batch.proposed", "codex"), ("batch.reviewed", "claude"),
                                             ("attempt.finished", "both"), ("response.done", "both"))
            for seat in (("codex", "claude") if seats == "both" else (seats,))))
        self.assertEqual(len(charged), 11)
        self.assertEqual((c2._tokens(t, "codex"), c2._tokens(t, "claude")), ("codex 11 in / 3 out", "claude 7 in / 2 out"))
        # The landed task replays from main's ledger alone, its crossing card and v2 included.
        status, again = call("status", "--repo", str(root)), rule(root, THREE, "a")
        self.assertEqual((status, again), ((0, f"{TASK}  landed\n", ""), (1, "", f"parallax: {THREE} is already ruled\n")))
        self.assertEqual(told(run(resumed(root, c)[0], root)), ("landed", f"{TASK} has already landed"))
        kept(self, "crossed-and-landed.json", normalized(
            {"history": timeless(in_order(history)), "cli": [[["status"], *status], [["rule", THREE, "a"], *again]]},
            c.home / repo_key(root), root))
        # A ledger that lost only contract v2 is refused: the repair it records needed the amended contract.
        rewrite_main(root, lambda events: events.remove(the("contract.frozen", version=2)(events)))
        blocks(self, root, c2, MISSING, THREE, "a")

    def test_a_second_check_ruling_freezes_contract_v3_with_both_answers_in_order(self):
        still_bad = responds("concede", files={FILE: CLAMP_BAD + "# tried\n"}, mutants=MUTANTS)
        fixed = responds("concede", files={FILE: CLAMP_OK}, mutants=MUTANTS)
        root, c, t, settled, codex, claude = contested(self, codex_after=[still_bad, responds("contest"), fixed],
                                                       claude_after=[responds("contest")])
        question = card(c, THREE)["question"]
        self.assertEqual(rule(root, THREE, "b", "--note", NOTE)[0], 0)
        # The repair leaves the check failing, and both seats contest again: a second check card.
        self.assertEqual(told(run(c, root)), ("needs_ruling", f"needs a ruling on {FOUR}"))
        self.assertEqual(rule(root, FOUR, "b", "--note", AGAIN, "--scope", "task")[0], 0)
        outcome = run(c, root)
        self.assertEqual(told(outcome)[0], "landed", told(outcome))
        first, second = (question, NOTE, f"ruled {THREE}"), (question, AGAIN, f"ruled {FOUR}")
        self.assertEqual([contract_file(root, n) for n in (2, 3)], [versioned(2, first), versioned(3, first, second)])
        history = on_main(root)
        self.assertEqual([(e["version"], e["sha"]) for e in history if e["type"] == "contract.frozen"],
                         [(1, sha256_text(versioned(1))), (2, sha256_text(versioned(2, first))),
                          (3, sha256_text(versioned(3, first, second)))])
        self.assertEqual(gitops.show_file(root, "main", f".parallax/contracts/{TASK}.md"), versioned(3, first, second))
        self.assertEqual(call("status", "--repo", str(root)), (0, f"{TASK}  landed\n", ""))

    def test_a_limitation_is_one_more_term_and_is_written_on_the_receipt(self):
        root, c, t, settled = ruled_cards(self)
        fixed = responds("concede", files={"tests/test_clamp.py": PROBES})
        c2, codex, claude = seated(root, c, {"build": [builds()], "respond": [responds("contest")]},
                                   {"probe": [probes(NAN_PROBE)], "respond": [responds("contest"), fixed]})
        self.assertEqual(told(run(c2, root)), ("needs_ruling", f"needs a ruling on {THREE}"))
        question = card(c2, THREE)["question"]
        self.assertEqual(rule(root, THREE, "a", "--limitation", "NaN is not supported")[0], 0)
        self.assertEqual(run(c2, root).status, "landed")
        ruling = next(e for e in on_main(root) if e["type"] == "ruling.made" and e["dispute"] == THREE)
        # With no note the answer is the default, naming the side that was right.
        self.assertEqual(ruling["text"], "codex (builder) is right.")
        self.assertEqual(gitops.show_file(root, "main", f".parallax/contracts/{TASK}.md"),
                         versioned(2, (question, "codex (builder) is right.", f"ruled {THREE}"),
                                   (PROMISED, "NaN is not supported", f"ruled {THREE}")))
        self.assertIn("Verdict: limited\nLimitation: NaN is not supported", message(root))

    def test_a_waived_mutant_lands_under_contract_v1_with_its_limitation_on_the_receipt(self):
        # As on any task: with the mutant waived the crossing is clean, so nothing is repaired or amended.
        root, c, t, settled = ruled_cards(self)
        c2, codex, claude = seated(root, c, {"build": [builds()]},
                                   {"probe": [probes(WEAK_PROBES)], "respond": [responds("contest")]})
        outcome = run(c2, root)
        self.assertEqual((told(outcome), [d.kind for d in outcome.disputes]),
                         (("needs_ruling", f"needs a ruling on {THREE}"), ["mutant"]))
        # A mutant card is one the crossing mapped to its mutant.
        cases(self, root, c2, c2.journal.path.read_bytes(), [
            (lambda events: last("crossing.done")(events).update(mutant_of={}),
             f"the crossing before {THREE} opens no such mutant card")], ONE, "b")
        self.assertEqual(rule(root, THREE, "b", "--note", "covered by an integration test",
                              "--limitation", "only on Windows")[0], 0)
        waiver = "mutant m1 waived: covered by an integration test; only on Windows"
        ruling = last("ruling.made")
        self.assertEqual((ruling(c2.events(TASK))["text"], ruling(c2.events(TASK))["limitation"]),
                         (card(c2, THREE)["b"], waiver))
        # A waiver is the task's own, keeps the card's column as its text, and names the mutant it waives.
        other = f"{THREE}'s ruling.made "
        cases(self, root, c2, c2.journal.path.read_bytes(), [
            (lambda events: ruling(events).update(scope="project"), other + "has a scope its card does not allow"),
            (lambda events: ruling(events).update(text="It does not matter."),
             other + "has a text that is not the column of its card it chose"),
            (lambda events: ruling(events).update(limitation=""), other + "has a limitation that does not waive mutant m1"),
            (lambda events: ruling(events).update(limitation="mutant m2 waived"),
             other + "has a limitation that does not waive mutant m1"),
            (lambda events: ruling(events).update(limitation="mutant m1 waived for now"),
             other + "has a limitation that does not waive mutant m1"),
            (lambda events: ruling(events).update(limitation="mutant m1 waived: "),
             other + "has a limitation that does not waive mutant m1")], THREE, "a")
        self.assertEqual(run(c2, root).status, "landed")
        self.assertEqual(gitops.show_file(root, "main", f".parallax/contracts/{TASK}.md"), versioned(1))
        self.assertEqual(versions(on_main(root)), [1])
        text = message(root)
        self.assertIn("Checks: 4 probes passed, 2 of 3 mutants caught", text)
        self.assertIn(f"Verdict: limited\nLimitation: {waiver}", text)
        self.assertEqual(call("status", "--repo", str(root)), (0, f"{TASK}  landed\n", ""))

    def test_an_unresolved_card_ruled_drop_lands_only_the_record(self):
        root, c, t, settled = ruled_cards(self)
        useless = [responds("concede", files={FILE: CLAMP_BAD + f"# tried {i}\n"}, mutants=MUTANTS) for i in range(5)]
        c2, codex, claude = seated(root, c, {"build": [builds(CLAMP_BAD)], "respond": useless},
                                   {"probe": [probes()], "respond": [responds("contest")] * 6})
        outcome = run(c2, root)
        self.assertEqual((told(outcome), [d.kind for d in outcome.disputes]),
                         (("needs_ruling", f"needs a ruling on {SIX}"), ["unresolved"]))
        # Three failed crossings each reserved an ID above the settlement's two (3, 4 and 5), so the card takes
        # the next: the sixth. No other number is an unresolved card, nor is the next number after a crossing that
        # reserved nothing, and no crossing but the last gives a card.
        unresolved, crossing = the("dispute.opened"), last("crossing.done")
        opened = c2.journal.path.read_bytes()
        cases(self, root, c2, opened, [
            (lambda events: unresolved(events).update(id=SEVEN), f"the crossing before {SEVEN} opens no such unresolved card"),
            (lambda events: unresolved(events).update(id=FIVE), f"the crossing before {FIVE} opens no such unresolved card"),
            (lambda events: (crossing(events).update(evidence=[]), unresolved(events).update(id=FIVE)),
             f"the crossing before {FIVE} opens no such unresolved card"),
            (lambda events: unresolved(events).update(kind="check", id=THREE),
             f"the crossing before {THREE} opens no such check card")], ONE, "b")
        # The last crossing's own reservation would be its check card.
        rewrite(c2, lambda events: unresolved(events).update(kind="check", id=FIVE))
        self.assertEqual(c2.status(), [{"task": TASK, "status": "needs_ruling", "pending": [FIVE]}])
        c2.journal.path.write_bytes(opened)
        self.assertEqual(rule(root, SIX, "drop")[0], 0)
        # A drop with a limitation would amend the contract, were the task not dropped: no version follows it.
        def forge(events):
            events[-1].update(limitation="clamp is abandoned")
            events.append({**next(e for e in events if e["type"] == "contract.frozen"), "version": 2})
        cases(self, root, c2, c2.journal.path.read_bytes(), [(forge, "contract v2 freezes a dropped task")], ONE, "b")
        self.assertEqual(run(c2, root).status, "dropped")
        history = on_main(root)
        self.assertEqual([e["type"] for e in history][-2:], ["ruling.made", "task.dropped"])
        self.assertEqual((versions(history), history[-1]["reason"]), ([1], "Drop this task."))
        # Only the record landed: no code, no probes and no contract.
        self.assertEqual(sorted(run_git(root, "show", "--name-only", "--format=", "main").splitlines()),
                         [".parallax/PRECEDENTS.md", ".parallax/ledger.jsonl"])
        self.assertEqual(c2.journal.events(TASK), [])
        c3, codex3, claude3 = resumed(root, c2)
        self.assertEqual((told(run(c3, root)), codex3.calls, claude3.calls),
                         (("dropped", f"{TASK} was already dropped"), [], []))
        self.assertEqual((call("status", "--repo", str(root)), rule(root, SIX, "a")),
                         ((0, f"{TASK}  dropped\n", ""), (1, "", f"parallax: {SIX} is already ruled\n")))

    def test_a_settlement_with_no_card_and_a_clean_crossing_lands_by_consensus(self):
        # The receipt counts human rulings: an automatic row is none.
        root, c, t, codex, claude = marked(propose=proposes(MUTUAL), review=reviews(MUTUAL_REVIEW))
        self.assertEqual(c.run(root / TASK_FILE, stop_after="contract").status, "stopped")
        c2, codex2, claude2 = seated(root, c, {"build": [builds()]}, {"probe": [probes()]})
        with mock.patch.object(receipt, "verdict", wraps=receipt.verdict) as verdict:
            self.assertEqual(run(c2, root).status, "landed")
        self.assertEqual(verdict.call_args_list, [mock.call("behavior", 0, 0, [])])
        self.assertIn("Verdict: consensus", message(root))


class Guards(unittest.TestCase):
    """One contested crossing for the class: its check card ruled, then contract v2 frozen and the run cut
    short before the repair. Each case starts from one of those journal bytes, and no test lands the task."""

    @classmethod
    def setUpClass(cls):
        test = unittest.TestCase()
        cls.root, cls.c, cls.t, cls.settled, codex, claude = contested(test)
        cls.opened = cls.c.journal.path.read_bytes()                  # the card is open, not ruled
        test.assertEqual(rule(cls.root, THREE, "b", "--note", NOTE)[0], 0)
        cls.ruled = cls.c.journal.path.read_bytes()
        killed_before_the_repair(test, cls.c, cls.root)
        cls.amended = cls.c.journal.path.read_bytes()
        test.assertEqual(versions(cls.c.events(TASK)), [1, 2])

    def check(self, start, tampered, *ruling):
        cases(self, self.root, self.c, start, tampered, *(ruling or (ONE, "b")))

    def test_a_card_the_crossing_before_it_does_not_open_blocks_every_reader(self):
        opened, first, crossing = the("dispute.opened"), the("contract.frozen"), the("crossing.done")

        def moved(before):
            def change(events):
                dispute = opened(events)
                events.remove(dispute)
                events.insert(events.index(first(events)) + (0 if before else 1), dispute)
            return change

        unread = f"{THREE}'s dispute.opened does not read as a card"
        self.check(self.opened, [
            (moved(before=True), f"{THREE}'s dispute.opened comes before the contract is frozen"),
            (moved(before=False), f"the crossing before {THREE} opens no such check card"),
            (lambda events: crossing(events).update(passed=True), f"the crossing before {THREE} opens no such check card"),
            (lambda events: opened(events).update(id=FOUR), f"the crossing before {FOUR} opens no such check card"),
            (lambda events: events.append(dict(opened(events))), f"{THREE} is the ID of more than one card"),
            (lambda events: opened(events).update(id=ONE), f"{ONE} is the ID of more than one card"),
            (lambda events: opened(events).update(kind="reading"),
             f"{THREE} is a standalone reading card on a confirmed-v1 task"),
            (lambda events: opened(events).update(kind="rumour"),
             f"{THREE} is a standalone rumour card on a confirmed-v1 task"),
            (lambda events: opened(events).pop("a_label"), unread),
            (lambda events: opened(events).update(question=7), unread),
            (lambda events: opened(events).update(id=[THREE]), f"['{THREE}']'s dispute.opened does not read as a card"),
            (lambda events: opened(events).pop("id"), "None's dispute.opened does not read as a card")])

    def test_a_crossing_ruling_rule_would_not_write_blocks_every_reader(self):
        ruling = the("ruling.made", dispute=THREE)

        def edit(change):
            return lambda events: change(ruling(events))

        other = f"{THREE}'s ruling.made "
        tampered = [
            (lambda events: events.append(dict(ruling(events))), f"{THREE} has more than one ruling.made"),
            (edit(lambda e: e.update(batch_protocol="confirmed-v1", settlement_sha=self.settled["settlement_sha"])),
             other + "does not have exactly the fields of a ruling on a crossing card"),
            (edit(lambda e: e.pop("limitation")), other + "does not have exactly the fields of a ruling on a crossing card"),
            (edit(lambda e: e.update(kind="unresolved")), other + "has a kind or question its card does not give"),
            (edit(lambda e: e.update(question="Another question?")), other + "has a kind or question its card does not give"),
            (edit(lambda e: e.update(choice="other")), other + "makes a choice its card does not allow"),
            (edit(lambda e: e.update(choice="drop")), other + "makes a choice its card does not allow"),
            (edit(lambda e: e.update(text=["a list"])), other + NOT_UTF8),
            (edit(lambda e: e.update(text="\ud800")), other + NOT_UTF8),
            (edit(lambda e: e.update(**{"while": "\ud800"})), other + NOT_UTF8),
            (edit(lambda e: e.update(text="")), other + "has a text that is blank or padded"),
            (edit(lambda e: e.update(text=NOTE + " ")), other + "has a text that is blank or padded"),
            (edit(lambda e: e.update(scope="everyone")), other + "has a scope its card does not allow"),
            (edit(lambda e: e.update(dispute=FOUR)), f"{FOUR}'s ruling.made rules no card of the reading.settled record"),
            (edit(lambda e: e.update(dispute=[THREE])),
             f"['{THREE}']'s ruling.made rules no card of the reading.settled record")]
        # `rule` on the crossing card itself checks the history before it answers `already ruled`; so does
        # `rule` on a settlement card.
        self.check(self.ruled, tampered[:-2], THREE, "a")
        self.check(self.ruled, tampered[-2:] + tampered[:1])

    def test_rule_writes_no_ruling_a_contract_or_precedent_file_cannot_hold(self):
        self.c.journal.path.write_bytes(self.opened)
        for flag in ("--note", "--while", "--limitation"):
            with self.subTest(flag=flag):
                self.assertEqual(rule(self.root, THREE, "b", flag, "\ud800"),
                                 (1, "", f"parallax: {THREE}'s ruling {NOT_UTF8}\n"))
                self.assertEqual(self.c.journal.path.read_bytes(), self.opened)

    def test_a_later_version_that_does_not_follow_from_its_rulings_blocks_every_reader(self):
        second, opened, crossing = the("contract.frozen", version=2), the("dispute.opened"), the("crossing.done")

        def a_second_card_waits(events):
            # Reserved and opened as the writer would, beside the ruled one: v2 itself is unchanged and correct.
            crossing(events)["evidence"].append(FOUR)
            events.insert(events.index(opened(events)) + 1, {**opened(events), "id": FOUR})

        self.check(self.amended, [
            (lambda events: second(events).update(sha=ZERO), "contract v2 is not the contract its settlement and rulings give"),
            (lambda events: second(events).pop("settlement_sha"), "contract v2 is not bound to the reading.settled record"),
            (lambda events: second(events).update(version=3), "contract v3 is not version 2"),
            # A third version, numbered and bound as the writer would: no ruling since v2 amends the contract.
            (lambda events: events.append({**second(events), "version": 3}),
             "contract v3 follows no ruling that amends the contract"),
            (a_second_card_waits, f"contract v2 is frozen before {FOUR} is ruled")])
        # Nor does a second version before the card is ruled.
        self.check(self.opened, [
            (lambda events: events.append({**the("contract.frozen")(events), "version": 2}),
             "contract v2 follows no ruling that amends the contract")])

    def test_a_ruled_repair_or_another_crossing_without_the_amended_contract_blocks_every_reader(self):
        # The ruling amends the contract, so the writer freezes v2 before either.
        response, crossing = the("response.done", seat="codex"), the("crossing.done")
        self.check(self.ruled, [
            (lambda events: events.append({**response(events), "ruling": [THREE]}), MISSING),
            (lambda events: events.append({**crossing(events), "n": 2}), MISSING)], THREE, "a")
        # A response under no ruling is not a repair, and the journal may end at the ruling.
        self.c.journal.path.write_bytes(self.ruled)
        rewrite(self.c, lambda events: events.append(dict(response(events))))
        self.assertEqual(self.c.status(), [{"task": TASK, "status": "in_progress", "pending": []}])
        self.c.journal.path.write_bytes(self.ruled)
        self.assertEqual(self.c.status(), [{"task": TASK, "status": "in_progress", "pending": []}])
