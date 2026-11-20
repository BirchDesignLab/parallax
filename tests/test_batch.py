import copy, json, re, unittest
from parallax import batch, briefs, schemas
from parallax.decisions import interface_problem, route, sources, witness_problem
from parallax.ledger import sha256_text
from parallax.schemas import validate
from tests.test_briefs import ABSOLUTE, PRECEDENT
from tests.test_decisions import EMPTY_WITNESS, ROLE_READINGS, ROLE_REVEALS, ROWS, conflict, role_reveals

# Task 19.2. The packet is built from Task 19.1's role-keyed fixture: builder/0 and challenger/0 are
# disputed, builder/1 and builder/interface are agreed, so the route is a batch.
INPUTS = {"builder": {"reading": "sha256:br", "reveal": "sha256:bv"},
          "challenger": {"reading": "sha256:cr", "reveal": "sha256:cv"}}
SEATS = {"builder": "codex", "challenger": "claude"}
TASK = "Add clamp(x, lo, hi) to clamplib."
PACKET = batch.packet(TASK, [PRECEDENT], ROLE_READINGS, ROLE_REVEALS, INPUTS, SEATS)
SHA = batch.digest(PACKET)
ASSENT = dict.fromkeys(batch.ASSENT_FIELDS, True)
NO_ASSENT = dict.fromkeys(batch.ASSENT_FIELDS, False)
QUESTION = "Which predicate rejects the bounds?"
A_POLICY = "Raise ValueError when hi < lo."
B_POLICY = "Raise ValueError unless lo <= hi."
INTERFACE_QUESTION = "What interface should the contract use?"
EMPTY_VALUE = {"interface": "", "policy": ""}
WITNESS = {"source": "builder/0", "scenario": "clamp(8, float('nan'), 5)", "observation": "result or exception",
           "a": "returns 5", "b": "raises ValueError"}
INTERFACE_TERM = {"slot": "interface", "question": INTERFACE_QUESTION, "text": "clamp(x, lo, hi)",
                  "sources": ["builder/interface"]}
RETURNED_TERM = {"slot": "p/0", "question": "What is returned?", "text": "One of the objects passed.",
                 "sources": ["builder/1"]}
CHOICE = {"slot": "c/0", "target": "policy", "question": QUESTION, "members": ["builder/0", "challenger/0"],
          "a": {"interface": "", "policy": A_POLICY}, "b": {"interface": "", "policy": B_POLICY},
          "witnesses": [WITNESS]}
FALLBACK = {"known": True, "members": ["builder/0", "challenger/0"], "question": QUESTION}
UNKNOWN = {"known": False, "members": [], "question": ""}
PROPOSAL = {"packet_sha": SHA, "decision": "propose", "common": [INTERFACE_TERM, RETURNED_TERM], "choices": [CHOICE],
            "withdrawn": [], "assent": ASSENT, "votes": [{"slot": "c/0", "sign": ["a"], "reason": "strict comparisons"}],
            "preferences": [{"slot": "c/0", "answer": "a"}], "fallback": FALLBACK, "refusal_reason": "",
            "affected": []}
PROPOSAL_SHA = batch.digest(PROPOSAL)
REVIEW = {"packet_sha": SHA, "proposal_sha": PROPOSAL_SHA, "decision": "attest", "assent": ASSENT,
          "votes": [{"slot": "c/0", "sign": ["b"], "reason": "NaN bounds must raise"}], "fallback_complete": True,
          "refusal_reason": "", "affected": []}
REFUSE = {"packet_sha": SHA, "proposal_sha": PROPOSAL_SHA, "decision": "refuse", "assent": NO_ASSENT, "votes": [],
          "fallback_complete": True, "refusal_reason": "the identity promise is also at stake",
          "affected": ["builder/1"]}
REFUSED_PROPOSAL = {**PROPOSAL, "decision": "refuse", "common": [], "choices": [], "votes": [], "preferences": [],
                    "assent": NO_ASSENT, "refusal_reason": "the predicate and identity are entangled",
                    "affected": ["builder/0", "builder/1", "challenger/0"],
                    "fallback": {**FALLBACK, "members": ["builder/0", "builder/1", "challenger/0"]}}
MOVED = {**CHOICE, "members": ["builder/0", "challenger/0", "builder/1"]}
WITHDRAWAL = {"role": "challenger", "source": "builder/1", "destinations": ["c/0"],
              "reason": "identity now depends on the predicate"}
RECORD_FIELDS = ["mode", "common", "withdrawn", "choices", "refusal_reason", "affected", "detail"]
CHOICE_FIELDS = ["slot", "target", "question", "members", "a", "b", "witnesses", "resolution", "selected"]
AGREE = {"index": 0, "agree": True, "counter": "", "why": "", "witness": EMPTY_WITNESS}

def changed(base, **fields):
    return {**copy.deepcopy(base), **fields}

def one_dispute(**challenger):
    """Reveals where the builder accepts challenger/0, so only builder/0 is disputed: a direct route."""
    return role_reveals(builder={"verdicts": [AGREE]}, challenger=challenger or None)

def all_agreed(**challenger):
    """Reveals where every reading verdict agrees."""
    return one_dispute(verdicts=[AGREE, {**AGREE, "index": 1}], **challenger)

def json_blocks(text):
    """Every fenced JSON block in a brief, parsed."""
    return [json.loads(body) for _, body in re.findall(r"^(`{3,})json\n(.*?)\n\1$", text, re.M | re.S)]

def shown_digests(text):
    return re.findall(r"Its digest is `(sha256:[0-9a-f]+)`\.", text)

def certified(case, packet, proposal, review, review_error=None):
    """The accepted proposal and review, bound to packet's digests and checked as 19.3's callbacks will check them."""
    packet_sha = batch.digest(packet)
    proposal = batch.accepted(changed(proposal, packet_sha=packet_sha))
    proposal_sha = batch.digest(proposal)
    review = batch.accepted(changed(review, packet_sha=packet_sha, proposal_sha=proposal_sha))
    case.assertEqual(validate(proposal, schemas.PROPOSAL), [])
    case.assertEqual(validate(review, schemas.REVIEW), [])
    case.assertIsNone(batch.proposal_problem(proposal, packet, packet_sha))
    case.assertEqual(batch.review_problem(review, proposal, packet, packet_sha, proposal_sha), review_error)
    return proposal, review

def object_nodes(schema):
    """Every object schema inside schema."""
    if schema.get("type") == "object":
        yield schema
        for child in schema["properties"].values():
            yield from object_nodes(child)
    elif schema.get("type") == "array":
        yield from object_nodes(schema["items"])


class Packet(unittest.TestCase):
    def test_the_packet_holds_the_rows_and_their_context(self):
        self.assertEqual(PACKET, {"task": TASK, "seats": SEATS, "precedents": [PRECEDENT], "inputs": INPUTS,
                                  "sources": ROWS, "challenger_interface": "clamp(value, lo, hi)",
                                  "predicted_failures": {"builder": [], "challenger": []},
                                  "conflicts": {"builder": [], "challenger": []},
                                  "reveals": {"builder": ROLE_REVEALS["builder"],
                                              "challenger": ROLE_REVEALS["challenger"]}})
        self.assertEqual(list(PACKET), ["task", "seats", "precedents", "inputs", "sources", "challenger_interface",
                                        "predicted_failures", "conflicts", "reveals"])

    def test_context_is_attributed_projected_and_copied(self):
        readings = {"builder": {**ROLE_READINGS["builder"], "predicted_failures": ["NaN x"]},
                    "challenger": {**ROLE_READINGS["challenger"], "predicted_failures": ["equal bounds", "inf"]}}
        cited = r'see "C:\Users\me\x\a.py"'
        reveals = role_reveals(builder={"conflicts": [conflict("builder/1", "builder/0", cited)],
                                        "interface_ok": False, "interface_objection": "mine",
                                        "interface_replacement": "other"},
                               challenger={"conflicts": [conflict("challenger/0", "builder/interface")]})
        precedent = {**PRECEDENT, "extra": "dropped"}
        inputs = {"challenger": {"reveal": "sha256:cv", "reading": "sha256:cr"},
                  "builder": {"reveal": "sha256:bv", "reading": "sha256:br"}}
        seats = {"challenger": "codex", "builder": "claude"}
        args = (TASK, [precedent], readings, reveals, inputs, seats)
        before = copy.deepcopy(args)
        built = batch.packet(*args)
        self.assertEqual(built["seats"], {"builder": "claude", "challenger": "codex"})
        self.assertEqual(list(built["seats"]), ["builder", "challenger"])
        self.assertEqual(built["precedents"], [PRECEDENT])
        self.assertEqual(list(built["precedents"][0]), ["id", "question", "ruling", "while", "task"])
        self.assertEqual([list(built["inputs"]), list(built["inputs"]["builder"])],
                         [["builder", "challenger"], ["reading", "reveal"]])
        self.assertEqual(built["predicted_failures"], {"builder": ["NaN x"], "challenger": ["equal bounds", "inf"]})
        self.assertEqual(built["conflicts"], {"builder": [conflict("builder/1", "builder/0", 'see "<outside>/a.py"')],
                                              "challenger": [conflict("challenger/0", "builder/interface")]})
        # The builder's interface opinion stays attributable context; only the challenger's decides the row.
        self.assertEqual((built["reveals"]["builder"]["interface_ok"], built["sources"][-1]["agree"]), (False, True))
        self.assertEqual(built["reveals"]["builder"]["conflicts"][0]["reason"], 'see "<outside>/a.py"')
        built["reveals"]["challenger"]["verdicts"][1]["witness"]["scenario"] = "changed"
        built["sources"][0]["original_witness"]["theirs"] = "changed"
        built["seats"]["builder"] = "changed"
        built["inputs"]["builder"]["reading"] = "changed"
        self.assertEqual(args, before)

    def test_the_seats_and_the_builders_interface_opinion_are_bound_by_the_digest(self):
        # Neither changes the source table, but both are part of what the seats were shown.
        swapped = batch.packet(TASK, [PRECEDENT], ROLE_READINGS, ROLE_REVEALS, INPUTS,
                               {"builder": "claude", "challenger": "codex"})
        opinion = batch.packet(TASK, [PRECEDENT], ROLE_READINGS,
                               role_reveals(builder={"interface_ok": False, "interface_objection": "mine",
                                                     "interface_replacement": "other"}), INPUTS, SEATS)
        for built in (swapped, opinion):
            with self.subTest(seats=built["seats"]):
                self.assertEqual(built["sources"], PACKET["sources"])
                self.assertNotEqual(batch.digest(built), SHA)

    def test_the_digest_is_the_canonical_json_sha(self):
        self.assertEqual(SHA, sha256_text(json.dumps(PACKET, sort_keys=True, indent=2)))
        self.assertEqual(batch.canonical(PACKET), json.dumps(PACKET, sort_keys=True, indent=2))
        self.assertEqual(batch.digest(dict(reversed(list(PACKET.items())))), SHA)
        self.assertNotEqual(batch.digest({**PACKET, "task": TASK + " "}), SHA)

    def test_every_string_is_scrubbed(self):
        task = r'Use \d+? from "C:\Users\me\.parallax\k\spec.md".'
        built = batch.packet(task, [], ROLE_READINGS, ROLE_REVEALS, INPUTS, SEATS)
        self.assertEqual(built["task"], r'Use \d+? from "<outside>/spec.md".')
        self.assertIsNone(ABSOLUTE.search(batch.canonical(built)))
        self.assertEqual(batch.accepted(built), built)          # scrubbing is idempotent

    def test_inputs_and_seats_must_name_both_roles_exactly(self):
        bad_inputs = [{"builder": INPUTS["builder"]}, {**INPUTS, "observer": INPUTS["builder"]},
                      {**INPUTS, "builder": {"reading": "sha256:br"}},
                      {**INPUTS, "builder": {**INPUTS["builder"], "extra": "x"}},
                      {**INPUTS, "builder": ["sha256:br", "sha256:bv"]},
                      {**INPUTS, "builder": {"reading": "sha256:br", "reveal": 5}},
                      {"codex": INPUTS["builder"], "claude": INPUTS["challenger"]},
                      # A reference the scrubber would rewrite could no longer name its artifact.
                      {**INPUTS, "builder": {"reading": r"C:\Users\me\.parallax\br.json", "reveal": "sha256:bv"}}]
        for inputs in bad_inputs:
            with self.subTest(inputs=inputs), self.assertRaises(ValueError) as caught:
                batch.packet(TASK, [], ROLE_READINGS, ROLE_REVEALS, inputs, SEATS)
            self.assertEqual(str(caught.exception),
                             "inputs must give the reading and reveal sha for builder and challenger")
        # Seat names the scrubber would rewrite could no longer match the opening, and two could collide.
        for seats in ({"builder": "codex"}, {**SEATS, "observer": "x"}, {**SEATS, "challenger": "codex"},
                      {**SEATS, "builder": ""}, {**SEATS, "builder": 1}, {**SEATS, "builder": r"C:\left\seat.exe"},
                      {"builder": r"C:\left\seat.exe", "challenger": r"D:\right\seat.exe"}):
            with self.subTest(seats=seats), self.assertRaises(ValueError) as caught:
                batch.packet(TASK, [], ROLE_READINGS, ROLE_REVEALS, INPUTS, seats)
            self.assertEqual(str(caught.exception), "seats must name two different seats for builder and challenger")


class Schemas(unittest.TestCase):
    def test_the_fixtures_fit_and_every_object_is_closed(self):
        self.assertEqual(batch.ASSENT_FIELDS,
                         ("coverage", "shared_terms", "withdrawals", "columns_and_witnesses", "all_combinations"))
        for value, schema in ((PROPOSAL, schemas.PROPOSAL), (REFUSED_PROPOSAL, schemas.PROPOSAL),
                              (REVIEW, schemas.REVIEW), (REFUSE, schemas.REVIEW)):
            self.assertEqual(validate(value, schema), [])
        self.assertEqual(list(schemas.PROPOSAL["properties"]),
                         ["packet_sha", "decision", "common", "choices", "withdrawn", "assent", "votes", "preferences",
                          "fallback", "refusal_reason", "affected"])
        self.assertEqual(list(schemas.REVIEW["properties"]),
                         ["packet_sha", "proposal_sha", "decision", "assent", "votes", "fallback_complete",
                          "refusal_reason", "affected"])
        self.assertEqual(list(schemas.PROPOSAL["properties"]["assent"]["properties"]),
                         ["coverage", "shared_terms", "withdrawals", "columns_and_witnesses", "all_combinations"])
        for schema in (schemas.PROPOSAL, schemas.REVIEW):
            for node in object_nodes(schema):
                self.assertEqual(node["required"], list(node["properties"]))
                self.assertIs(node["additionalProperties"], False)

    def test_enums_types_and_missing_fields_are_rejected(self):
        cases = [
            (changed(PROPOSAL, decision="attest"), schemas.PROPOSAL, "$.decision: expected one of ['propose', 'refuse']"),
            (changed(REVIEW, decision="propose"), schemas.REVIEW, "$.decision: expected one of ['attest', 'refuse']"),
            (changed(PROPOSAL, choices=[{**CHOICE, "target": "both"}]), schemas.PROPOSAL,
             "$.choices[0].target: expected one of ['policy', 'interface', 'combined']"),
            (changed(REVIEW, votes=[{"slot": "c/0", "sign": ["c"], "reason": "r"}]), schemas.REVIEW,
             "$.votes[0].sign[0]: expected one of ['a', 'b']"),
            (changed(PROPOSAL, preferences=[{"slot": "c/0", "answer": "c"}]), schemas.PROPOSAL,
             "$.preferences[0].answer: expected one of ['a', 'b']"),
            (changed(PROPOSAL, withdrawn=[{**WITHDRAWAL, "role": "human"}]), schemas.PROPOSAL,
             "$.withdrawn[0].role: expected one of ['builder', 'challenger']"),
            (changed(PROPOSAL, fallback={"known": True, "members": [], "question": "q", "target": "policy"}),
             schemas.PROPOSAL, "$.fallback: unexpected property 'target'"),
            (changed(PROPOSAL, choices=[{**CHOICE, "a": {"policy": A_POLICY}}]), schemas.PROPOSAL,
             "$.choices[0].a: missing 'interface'"),
            (changed(REVIEW, fallback_complete="yes"), schemas.REVIEW, "$.fallback_complete: expected boolean"),
        ]
        for value, schema, problem in cases:
            with self.subTest(problem=problem):
                self.assertEqual(validate(value, schema), [problem])


class ProposalChecks(unittest.TestCase):
    def check(self, proposal):
        return batch.proposal_problem(proposal, PACKET, SHA)

    def test_good_proposals_pass(self):
        between = {"slot": "p/1", "question": "Any other promise?", "text": "None.", "sources": ["builder/1"]}
        for proposal in (PROPOSAL, REFUSED_PROPOSAL,
                         changed(PROPOSAL, common=[RETURNED_TERM, INTERFACE_TERM, between]),
                         changed(REFUSED_PROPOSAL, affected=[], fallback=UNKNOWN)):
            with self.subTest(common=proposal["common"]):
                self.assertIsNone(self.check(proposal))

    def test_a_withdrawal_by_either_role_or_both_satisfies_a_moved_source(self):
        builder = {**WITHDRAWAL, "role": "builder"}
        for withdrawn in ([WITHDRAWAL], [builder], [WITHDRAWAL, builder]):
            with self.subTest(roles=[w["role"] for w in withdrawn]):
                self.assertIsNone(self.check(changed(PROPOSAL, choices=[MOVED], withdrawn=withdrawn)))

    def test_each_problem_has_its_message(self):
        vote = PROPOSAL["votes"][0]
        combined = {**CHOICE, "target": "combined", "a": {"interface": "clamp(x, lo, hi)", "policy": A_POLICY},
                    "b": {"interface": "clamp(x, lo, hi), raising ValueError", "policy": B_POLICY}}
        cases = [
            (changed(PROPOSAL, packet_sha="sha256:x"), "packet_sha differs from the packet"),
            (changed(PROPOSAL, common=[INTERFACE_TERM, {**RETURNED_TERM, "slot": "p/1"}]),
             "common slots must be interface (at most once) and p/0, p/1, ... in order; got interface, p/1"),
            (changed(PROPOSAL, common=[INTERFACE_TERM, INTERFACE_TERM, RETURNED_TERM]),
             "common slots must be interface (at most once) and p/0, p/1, ... in order; got interface, interface, p/0\n"
             "the interface has 2 producers; give exactly one common interface or interface choice"),
            (changed(PROPOSAL, choices=[{**CHOICE, "slot": "c/1"}], votes=[{**vote, "slot": "c/1"}],
                     preferences=[{"slot": "c/1", "answer": "a"}]),
             "choice slots must be c/0, c/1, ... in order; got c/1"),
            (changed(PROPOSAL, common=[INTERFACE_TERM, {**RETURNED_TERM, "sources": ["builder/1", "builder/9"]}]),
             "common p/0: unknown source builder/9"),
            (changed(PROPOSAL, choices=[{**CHOICE, "members": ["builder/0", "challenger/0", "builder/0"]}]),
             "choice c/0: repeats builder/0"),
            (changed(PROPOSAL, common=[INTERFACE_TERM, {**RETURNED_TERM, "sources": []}]),
             "common p/0: needs at least one source\nmissing disposition for builder/1"),
            (changed(PROPOSAL, common=[INTERFACE_TERM, {**RETURNED_TERM, "text": " "}]), "common p/0: text is empty"),
            (changed(PROPOSAL, choices=[{**CHOICE, "a": {"interface": "x", "policy": A_POLICY}}]),
             "choice c/0: a policy choice leaves a.interface empty"),
            (changed(PROPOSAL, choices=[{**CHOICE, "b": {"interface": " ", "policy": B_POLICY}}]),
             "choice c/0: a policy choice leaves b.interface empty"),
            (changed(PROPOSAL, choices=[{**CHOICE, "b": EMPTY_VALUE}]), "choice c/0: b.policy is empty"),
            (changed(PROPOSAL, choices=[{**CHOICE, "b": {"interface": "", "policy": f" {A_POLICY} "}}]),
             "choice c/0: a and b are the same"),
            (changed(PROPOSAL, choices=[combined]),
             "the interface has 2 producers; give exactly one common interface or interface choice"),
            (changed(PROPOSAL, common=[{**RETURNED_TERM, "sources": ["builder/1", "builder/interface"]}]),
             "the interface has 0 producers; give exactly one common interface or interface choice"),
            (changed(PROPOSAL, common=[{**INTERFACE_TERM, "sources": ["builder/1"]},
                                       {**RETURNED_TERM, "sources": ["builder/1", "builder/interface"]}]),
             "builder/interface must be a source of the interface"),
            (changed(PROPOSAL, choices=[{**CHOICE, "members": ["builder/0"]}]), "missing disposition for challenger/0"),
            (changed(PROPOSAL, choices=[MOVED]), "agreed builder/1 moved into c/0 needs a withdrawal"),
            (changed(PROPOSAL, withdrawn=[WITHDRAWAL]),
             "withdrawal 0: builder/1 is not an agreed source moved into a choice"),
            (changed(PROPOSAL, choices=[MOVED], withdrawn=[{**WITHDRAWAL, "destinations": []}]),
             "withdrawal 0: destinations must be exactly c/0"),
            (changed(PROPOSAL, choices=[MOVED], withdrawn=[WITHDRAWAL, {**WITHDRAWAL, "reason": ""}, WITHDRAWAL]),
             "withdrawal 1: repeats withdrawal 0\nwithdrawal 2: repeats withdrawal 0"),
            (changed(PROPOSAL, choices=[MOVED], withdrawn=[{**WITHDRAWAL, "reason": ""}]),
             "withdrawal 0: reason is empty"),
            (changed(PROPOSAL, choices=[{**CHOICE, "witnesses": []}]), "choice c/0 needs a witness"),
            (changed(PROPOSAL, choices=[{**CHOICE, "witnesses": [{**WITNESS, "source": "builder/1"}]}]),
             "choice c/0 witness 0: source builder/1 is not a member"),
            (changed(PROPOSAL, choices=[{**CHOICE, "witnesses": [{**WITNESS, "scenario": " ", "b": ""}]}]),
             "choice c/0 witness 0: missing scenario, b"),
            (changed(PROPOSAL, choices=[{**CHOICE, "witnesses": [{**WITNESS, "b": "returns 5 "}]}]),
             "choice c/0 witness 0: a and b predict the same result"),
            (changed(PROPOSAL, assent={**ASSENT, "shared_terms": False}), "assent.shared_terms must be true to propose"),
            (changed(PROPOSAL, votes=[]), "missing vote for c/0\npreference for c/0 must be an answer you sign"),
            (changed(PROPOSAL, votes=[vote, vote]), "repeated vote for c/0"),
            (changed(PROPOSAL, votes=[vote, {**vote, "slot": "c/5"}]), "vote for unknown slot c/5"),
            (changed(PROPOSAL, votes=[{**vote, "sign": ["a", "a"]}]), "vote for c/0 must sign a, b or both, once each"),
            (changed(PROPOSAL, votes=[{**vote, "reason": " "}]), "vote for c/0 needs a reason"),
            (changed(PROPOSAL, preferences=[{"slot": "c/0", "answer": "b"}]),
             "preference for c/0 must be an answer you sign"),
            (changed(PROPOSAL, preferences=[{"slot": "c/0", "answer": "a"}, {"slot": "c/0", "answer": "a"},
                                            {"slot": "c/7", "answer": "a"}]),
             "repeated preference for c/0\npreference for unknown slot c/7"),
            (changed(PROPOSAL, preferences=[]), "missing preference for c/0"),
            (changed(PROPOSAL, refusal_reason=" "), "refusal_reason must be empty when you propose"),
            (changed(PROPOSAL, affected=["builder/0"]), "affected must be empty when you propose"),
            (changed(PROPOSAL, fallback={**FALLBACK, "question": ""}),
             "fallback: a known fallback needs members and a question"),
            (changed(PROPOSAL, fallback={"known": False, "members": ["builder/0"], "question": ""}),
             "fallback: an unknown fallback has no members or question"),
            (changed(PROPOSAL, fallback={**FALLBACK, "members": ["builder/0", "challenger/4"]}),
             "fallback: unknown source challenger/4"),
        ]
        for proposal, message in cases:
            with self.subTest(message=message):
                self.assertEqual(self.check(proposal), message)

    def test_columns_are_compared_after_paths_are_scrubbed(self):
        # The caller checks the accepted value: two paths to the same file name display as the same words.
        a = {"interface": "", "policy": r'Raise the error named in "C:\Users\me\a\errors.txt".'}
        b = {"interface": "", "policy": r'Raise the error named in "D:\other\errors.txt".'}
        proposal = batch.accepted(changed(PROPOSAL, choices=[{**CHOICE, "a": a, "b": b}]))
        self.assertEqual(self.check(proposal), "choice c/0: a and b are the same")

    def test_problems_are_reported_in_a_stable_order(self):
        proposal = changed(PROPOSAL, packet_sha="sha256:x", votes=[],
                           choices=[{**CHOICE, "witnesses": [{**WITNESS, "b": "returns 5"}]}],
                           fallback={**FALLBACK, "question": ""})
        self.assertEqual(self.check(proposal), "packet_sha differs from the packet\n"
                                               "choice c/0 witness 0: a and b predict the same result\n"
                                               "missing vote for c/0\n"
                                               "preference for c/0 must be an answer you sign\n"
                                               "fallback: a known fallback needs members and a question")

    def test_a_refusal_carries_nothing_but_its_reason_and_extent(self):
        cases = [
            (changed(REFUSED_PROPOSAL, common=[RETURNED_TERM]), "common must be empty when you refuse"),
            (changed(REFUSED_PROPOSAL, votes=PROPOSAL["votes"]), "votes must be empty when you refuse"),
            (changed(REFUSED_PROPOSAL, assent={**NO_ASSENT, "coverage": True}),
             "assent.coverage must be false when you refuse"),
            (changed(REFUSED_PROPOSAL, refusal_reason=" "), "refusal_reason must say why you refuse"),
            (changed(REFUSED_PROPOSAL, affected=[]), "affected must name the sources your refusal concerns"),
            (changed(REFUSED_PROPOSAL, affected=["builder/0", "builder/0"]), "affected: repeats builder/0"),
            (changed(REFUSED_PROPOSAL, packet_sha="sha256:x"), "packet_sha differs from the packet"),
        ]
        for proposal, message in cases:
            with self.subTest(message=message):
                self.assertEqual(self.check(proposal), message)
        everything = changed(REFUSED_PROPOSAL, common=[RETURNED_TERM], choices=[CHOICE], withdrawn=[WITHDRAWAL],
                             votes=PROPOSAL["votes"], preferences=PROPOSAL["preferences"],
                             assent={**NO_ASSENT, "coverage": True, "withdrawals": True}, refusal_reason="",
                             affected=["builder/9"], fallback={**FALLBACK, "question": " "})
        self.assertEqual(self.check(everything), "common must be empty when you refuse\n"
                                                 "choices must be empty when you refuse\n"
                                                 "withdrawn must be empty when you refuse\n"
                                                 "votes must be empty when you refuse\n"
                                                 "preferences must be empty when you refuse\n"
                                                 "assent.coverage must be false when you refuse\n"
                                                 "assent.withdrawals must be false when you refuse\n"
                                                 "refusal_reason must say why you refuse\n"
                                                 "affected: unknown source builder/9\n"
                                                 "fallback: a known fallback needs members and a question")


class ReviewChecks(unittest.TestCase):
    def check(self, review, proposal=PROPOSAL):
        return batch.review_problem(review, proposal, PACKET, SHA, batch.digest(proposal))

    def test_good_reviews_pass(self):
        self.assertIsNone(self.check(REVIEW))
        self.assertIsNone(self.check(changed(REVIEW, fallback_complete=False)))
        self.assertIsNone(self.check(REFUSE))
        self.assertIsNone(self.check(changed(REFUSE, affected=[], fallback_complete=False)))
        refused = changed(REFUSE, proposal_sha=batch.digest(REFUSED_PROPOSAL))
        self.assertIsNone(self.check(refused, REFUSED_PROPOSAL))

    def test_each_problem_has_its_message(self):
        vote = REVIEW["votes"][0]
        holds_b = changed(PROPOSAL, votes=[{**PROPOSAL["votes"][0], "sign": ["b"]}],
                          preferences=[{"slot": "c/0", "answer": "b"}])
        cases = [
            (changed(REVIEW, packet_sha="sha256:x"), PROPOSAL, "packet_sha differs from the packet"),
            (changed(REVIEW, proposal_sha="sha256:x"), PROPOSAL, "proposal_sha differs from the recorded proposal"),
            (changed(REVIEW, proposal_sha=batch.digest(REFUSED_PROPOSAL)), REFUSED_PROPOSAL,
             "a refused proposal can only be reviewed with refuse"),
            (changed(REVIEW, assent={**ASSENT, "coverage": False}), PROPOSAL, "assent.coverage must be true to attest"),
            (changed(REVIEW, votes=[]), PROPOSAL, "missing vote for c/0"),
            (changed(REVIEW, votes=[vote, vote]), PROPOSAL, "repeated vote for c/0"),
            (changed(REVIEW, votes=[{**vote, "sign": []}]), PROPOSAL, "vote for c/0 must sign a, b or both, once each"),
            (changed(REVIEW, votes=[{**vote, "sign": ["a"]}], proposal_sha=batch.digest(holds_b)), holds_b,
             "vote for c/0 holds a while the builder holds b; refuse instead of reversing the columns"),
            # Only the first vote for a slot is compared with the builder's: the second is a repeat, nothing more.
            (changed(REVIEW, votes=[vote, {**vote, "sign": ["a"]}], proposal_sha=batch.digest(holds_b)), holds_b,
             "repeated vote for c/0"),
            (changed(REVIEW, refusal_reason="x"), PROPOSAL, "refusal_reason must be empty when you attest"),
            (changed(REVIEW, affected=["builder/0"]), PROPOSAL, "affected must be empty when you attest"),
            (changed(REFUSE, votes=[vote]), PROPOSAL, "votes must be empty when you refuse"),
            (changed(REFUSE, assent={**NO_ASSENT, "withdrawals": True}), PROPOSAL,
             "assent.withdrawals must be false when you refuse"),
            (changed(REFUSE, refusal_reason=""), PROPOSAL, "refusal_reason must say why you refuse"),
            (changed(REFUSE, affected=["builder/7"]), PROPOSAL, "affected: unknown source builder/7"),
            (changed(REFUSE, affected=[]), PROPOSAL, "affected must name the sources your refusal concerns"),
        ]
        for review, proposal, message in cases:
            with self.subTest(message=message):
                self.assertEqual(self.check(review, proposal), message)

    def test_an_attested_refusal_stops_after_the_digests(self):
        review = changed(REVIEW, packet_sha="sha256:x", proposal_sha="sha256:y", assent={**ASSENT, "coverage": False},
                         votes=[{"slot": "c/9", "sign": ["a"], "reason": "r"}])
        self.assertEqual(self.check(review, REFUSED_PROPOSAL), "packet_sha differs from the packet\n"
                                                               "proposal_sha differs from the recorded proposal\n"
                                                               "a refused proposal can only be reviewed with refuse")


# A batch with two choices: the bound predicate, and a structural alias the challenger asked for.
ALIAS_REVEALS = role_reveals(challenger={"interface_ok": False, "interface_objection": "callers want the short name clip",
                                         "interface_replacement": "clamp(x, lo, hi); clip = clamp"})
ALIAS_PACKET = batch.packet(TASK, [], ROLE_READINGS, ALIAS_REVEALS, INPUTS, SEATS)
ALIAS_CHOICE = {"slot": "c/1", "target": "interface", "question": "Should clamplib also export clip?",
                "members": ["builder/interface"], "a": {"interface": "clamp(x, lo, hi)", "policy": ""},
                "b": {"interface": "clamp(x, lo, hi); clip = clamp", "policy": ""},
                "witnesses": [{"source": "builder/interface", "scenario": "from clamplib import clip",
                               "observation": "whether the import succeeds", "a": "raises ImportError",
                               "b": "imports clamp"}]}
# The interface is disputed here too, so a complete fallback holds all three disputed keys.
ALIAS_FALLBACK = {"known": True, "members": ["builder/0", "challenger/0", "builder/interface"],
                  "question": "What complete interface and bounds predicate should clamplib have?"}
BUILDER_VOTES = [{"slot": "c/0", "sign": ["a"], "reason": "strict comparisons"},
                 {"slot": "c/1", "sign": ["a", "b"], "reason": "either name works"}]
REVIEW_VOTES = [{"slot": "c/0", "sign": ["b"], "reason": "NaN bounds must raise"},
                {"slot": "c/1", "sign": ["a", "b"], "reason": "either name works"}]
TWO_CHOICES = changed(PROPOSAL, common=[RETURNED_TERM], choices=[CHOICE, ALIAS_CHOICE], votes=BUILDER_VOTES[::-1],
                      preferences=[{"slot": "c/1", "answer": "b"}, {"slot": "c/0", "answer": "a"}],
                      fallback=ALIAS_FALLBACK)
TWO_REVIEW = changed(REVIEW, votes=REVIEW_VOTES)


class Settlement(unittest.TestCase):
    def test_opposed_votes_leave_one_pending_choice(self):
        proposal, review = certified(self, PACKET, PROPOSAL, REVIEW)
        settled = batch.confirmed_settlement(PACKET, proposal, review)
        self.assertEqual(settled, {"mode": "confirmed", "common": [INTERFACE_TERM, RETURNED_TERM], "withdrawn": [],
                                   "choices": [{**CHOICE, "resolution": "pending", "selected": ""}],
                                   "refusal_reason": "", "affected": [], "detail": ""})
        self.assertEqual(list(settled), RECORD_FIELDS)
        self.assertEqual(list(settled["choices"][0]), CHOICE_FIELDS)

    def test_votes_are_matched_by_slot_not_position(self):
        expected = {"mode": "confirmed", "common": [RETURNED_TERM], "withdrawn": [],
                    "choices": [{**CHOICE, "resolution": "pending", "selected": ""},
                                {**ALIAS_CHOICE, "resolution": "tie_break", "selected": "b"}],
                    "refusal_reason": "", "affected": [], "detail": ""}
        # Builder votes reversed, then only the reviewer's votes reversed.
        for builder_votes, review_votes in ((BUILDER_VOTES[::-1], REVIEW_VOTES), (BUILDER_VOTES, REVIEW_VOTES[::-1])):
            with self.subTest(builder=[v["slot"] for v in builder_votes], review=[v["slot"] for v in review_votes]):
                proposal, review = certified(self, ALIAS_PACKET, changed(TWO_CHOICES, votes=builder_votes),
                                             changed(TWO_REVIEW, votes=review_votes))
                self.assertEqual(batch.confirmed_settlement(ALIAS_PACKET, proposal, review), expected)
        proposal, review = certified(self, ALIAS_PACKET, TWO_CHOICES, TWO_REVIEW)
        # A proposal reloaded from its stored artifact has sorted keys; the record's field order is fixed.
        reloaded = json.loads(batch.canonical(proposal))
        settled = batch.confirmed_settlement(ALIAS_PACKET, reloaded, review)
        self.assertEqual(settled, expected)
        self.assertEqual([list(c) for c in settled["choices"]], [CHOICE_FIELDS] * 2)
        self.assertEqual(list(settled["common"][0]), ["slot", "question", "text", "sources"])
        self.assertEqual(list(settled["choices"][1]["witnesses"][0]), ["source", "scenario", "observation", "a", "b"])

    def test_shared_answers_settle_without_the_human(self):
        cases = [  # (builder signs, challenger signs, builder prefers, resolution, selected)
            (["a", "b"], ["b"], "a", "mutual", "b"),
            (["a"], ["a", "b"], "a", "mutual", "a"),
            (["b"], ["b"], "b", "mutual", "b"),
            (["b", "a"], ["a", "b"], "b", "tie_break", "b"),
            (["a", "b"], ["b", "a"], "a", "tie_break", "a"),
            (["a"], ["b"], "a", "pending", ""),
        ]
        for builder, challenger, prefer, resolution, selected in cases:
            with self.subTest(builder=builder, challenger=challenger, prefer=prefer):
                proposal, review = certified(
                    self, PACKET,
                    changed(PROPOSAL, votes=[{**PROPOSAL["votes"][0], "sign": builder}],
                            preferences=[{"slot": "c/0", "answer": prefer}]),
                    changed(REVIEW, votes=[{**REVIEW["votes"][0], "sign": challenger}]))
                [choice] = batch.confirmed_settlement(PACKET, proposal, review)["choices"]
                self.assertEqual((choice["resolution"], choice["selected"]), (resolution, selected))

    def test_combined_choices_zero_choices_and_withdrawals_are_carried(self):
        combined = {**CHOICE, "target": "combined", "members": ["builder/0", "challenger/0", "builder/interface"],
                    "a": {"interface": "clamp(x, lo, hi)", "policy": A_POLICY},
                    "b": {"interface": "clamp(x, lo, hi), raising ValueError", "policy": B_POLICY}}
        moved_interface = {**WITHDRAWAL, "source": "builder/interface", "reason": "the interface depends on it"}
        # The predicate-only fallback would leave out the withdrawn interface, so the builder gives none.
        proposal, review = certified(self, PACKET, changed(PROPOSAL, common=[RETURNED_TERM], choices=[combined],
                                                           withdrawn=[moved_interface], fallback=UNKNOWN),
                                     changed(REVIEW, fallback_complete=False))
        settled = batch.confirmed_settlement(PACKET, proposal, review)
        self.assertEqual((settled["choices"][0]["target"], settled["choices"][0]["a"], settled["withdrawn"]),
                         ("combined", combined["a"], [moved_interface]))
        settled_term = {"slot": "p/1", "question": QUESTION, "text": B_POLICY, "sources": ["builder/0", "challenger/0"]}
        proposal, review = certified(self, PACKET, changed(PROPOSAL, common=[INTERFACE_TERM, RETURNED_TERM, settled_term],
                                                           choices=[], votes=[], preferences=[]),
                                     changed(REVIEW, votes=[]))
        settled = batch.confirmed_settlement(PACKET, proposal, review)
        self.assertEqual((settled["mode"], settled["choices"], settled["common"][-1]), ("confirmed", [], settled_term))

    def test_an_agreed_source_feeding_two_choices_withdraws_into_both(self):
        identity = {"slot": "c/1", "target": "policy", "question": "What is returned on equal bounds?",
                    "members": ["builder/1"], "a": {"interface": "", "policy": "One of the objects passed."},
                    "b": {"interface": "", "policy": "x itself."},
                    "witnesses": [{"source": "builder/1", "scenario": "clamp(5, 5.0, 5.0)",
                                   "observation": "the returned value's type", "a": "float or int", "b": "int"}]}
        both = {**WITHDRAWAL, "destinations": ["c/0", "c/1"]}
        base = changed(PROPOSAL, common=[INTERFACE_TERM], choices=[MOVED, identity], withdrawn=[both],
                       votes=[{"slot": "c/0", "sign": ["a"], "reason": "r"}, {"slot": "c/1", "sign": ["b"], "reason": "r"}],
                       preferences=[{"slot": "c/0", "answer": "a"}, {"slot": "c/1", "answer": "b"}],
                       fallback={**FALLBACK, "members": ["builder/0", "builder/1", "challenger/0"],
                                 "question": "What bounds predicate and return identity should clamp have?"})
        self.assertEqual(batch.proposal_problem(changed(base, withdrawn=[{**both, "destinations": ["c/1", "c/0"]}]),
                                                PACKET, SHA),
                         "withdrawal 0: destinations must be exactly c/0, c/1")
        proposal, review = certified(self, PACKET, base,
                                     changed(REVIEW, votes=[{"slot": "c/0", "sign": ["b"], "reason": "r"},
                                                            {"slot": "c/1", "sign": ["b"], "reason": "r"}]))
        before = copy.deepcopy((proposal, review))
        settled = batch.confirmed_settlement(PACKET, proposal, review)
        self.assertEqual(settled["withdrawn"], [both])
        self.assertEqual([(c["resolution"], c["selected"]) for c in settled["choices"]], [("pending", ""), ("mutual", "b")])
        settled["withdrawn"][0]["destinations"].append("c/9")
        settled["choices"][0]["witnesses"][0]["a"] = "changed"
        settled["common"][0]["sources"].append("x")
        self.assertEqual((proposal, review), before)

    def test_reversed_columns_never_settle(self):
        proposal, review = certified(
            self, PACKET,
            changed(PROPOSAL, votes=[{**PROPOSAL["votes"][0], "sign": ["b"]}], preferences=[{"slot": "c/0", "answer": "b"}]),
            changed(REVIEW, votes=[{**REVIEW["votes"][0], "sign": ["a"]}]),
            review_error="vote for c/0 holds a while the builder holds b; refuse instead of reversing the columns")
        with self.assertRaises(ValueError) as caught:
            batch.confirmed_settlement(PACKET, proposal, review)
        self.assertEqual(str(caught.exception), "the votes for c/0 reverse the columns")

    def test_a_refusal_with_a_complete_fallback_opens_one_replacement_choice(self):
        # The fallback lists its members out of packet order; the replacement choice lists them in packet order.
        proposal, review = certified(self, PACKET,
                                     changed(PROPOSAL, fallback={**FALLBACK, "members": ["challenger/0", "builder/0"]}),
                                     changed(REFUSE, affected=["challenger/0"],
                                             refusal_reason="the B column misstates my bounds predicate"))
        settled = batch.confirmed_settlement(PACKET, proposal, review)
        self.assertEqual(settled, {
            "mode": "refusal",
            "common": [{"slot": "p/0", "question": " What is returned?", "text": "One of the objects passed.",
                        "sources": ["builder/1"]}, INTERFACE_TERM],
            "withdrawn": [],
            "choices": [{"slot": "c/0", "target": "policy", "question": QUESTION, "members": ["builder/0", "challenger/0"],
                         "a": EMPTY_VALUE, "b": EMPTY_VALUE, "witnesses": [], "resolution": "refused", "selected": ""}],
            "refusal_reason": "challenger: the B column misstates my bounds predicate", "affected": ["challenger/0"],
            "detail": ""})
        self.assertEqual(list(settled), RECORD_FIELDS)
        # A fallback that consumes the interface too is combined, and nothing survives.
        whole_question = "What complete interface and policy should replace the whole contract?"
        whole = changed(PROPOSAL, fallback={"known": True, "question": whole_question,
                                            "members": ["builder/0", "builder/1", "challenger/0", "builder/interface"]})
        proposal, review = certified(self, PACKET, whole, REFUSE)
        settled = batch.confirmed_settlement(PACKET, proposal, review)
        self.assertEqual((settled["mode"], settled["common"], settled["choices"][0]["target"],
                          settled["choices"][0]["question"]), ("refusal", [], "combined", whole_question))

    def test_settlement_certifies_the_accepted_words(self):
        # Reasons citing absolute paths: the proposal the review names, and the one settled, are the scrubbed ones.
        proposal, review = certified(
            self, PACKET,
            changed(PROPOSAL, votes=[{"slot": "c/0", "sign": ["a"], "reason": r'see "C:\Users\me\a\why.txt"'}]),
            changed(REVIEW, votes=[{"slot": "c/0", "sign": ["b"], "reason": r'see "D:\notes\because.md"'}]))
        self.assertEqual((proposal["votes"][0]["reason"], review["votes"][0]["reason"]),
                         ('see "<outside>/why.txt"', 'see "<outside>/because.md"'))
        self.assertEqual(review["proposal_sha"], batch.digest(proposal))
        self.assertEqual(json_blocks(briefs.review(PACKET, SHA, proposal, review["proposal_sha"]))[1], proposal)
        self.assertEqual(batch.confirmed_settlement(PACKET, proposal, review)["choices"][0]["resolution"], "pending")

    def test_both_refusals_are_summarized_one_line_per_seat(self):
        refused = changed(REFUSED_PROPOSAL, refusal_reason="the predicate\nchallenger: and identity are entangled")
        proposal, review = certified(self, PACKET, refused, changed(REFUSE, refusal_reason="agreed",
                                                                    affected=["challenger/0"]))
        settled = batch.confirmed_settlement(PACKET, proposal, review)
        self.assertEqual((settled["mode"], settled["refusal_reason"], settled["affected"]),
                         ("refusal", "builder: the predicate challenger: and identity are entangled\nchallenger: agreed",
                          ["builder/0", "builder/1", "challenger/0"]))
        self.assertEqual(len(settled["refusal_reason"].splitlines()), 2)

    def test_a_refusal_blocks_unless_the_fallback_covers_everything_affected(self):
        builder_flag = role_reveals(builder={"conflicts": [conflict("builder/1", "builder/0")]})
        challenger_flag = role_reveals(challenger={"conflicts": [conflict("builder/0", "builder/1")]})
        mentions_b0 = changed(REFUSE, affected=["builder/0"])
        both_known = {**FALLBACK, "members": ["builder/0", "builder/1", "challenger/0"]}
        cases = [  # (packet, proposal, review, detail, affected, refusal_reason)
            (PACKET, PROPOSAL, REFUSE, "the fallback leaves out builder/1", ["builder/1"], None),
            # Every disputed source must be replaced, even when no refusal names it.
            (PACKET, changed(PROPOSAL, fallback={**FALLBACK, "members": ["builder/1"]}), REFUSE,
             "the fallback leaves out builder/0, challenger/0", ["builder/1"], None),
            # Both ends of a conflict flagged by either seat.
            (batch.packet(TASK, [], ROLE_READINGS, builder_flag, INPUTS, SEATS), PROPOSAL, mentions_b0,
             "the fallback leaves out builder/1", ["builder/0"], None),
            (batch.packet(TASK, [], ROLE_READINGS, challenger_flag, INPUTS, SEATS), PROPOSAL, mentions_b0,
             "the fallback leaves out builder/1", ["builder/0"], None),
            # Every source the proposing builder withdrew.
            (PACKET, changed(PROPOSAL, choices=[MOVED], withdrawn=[WITHDRAWAL]), mentions_b0,
             "the fallback leaves out builder/1", ["builder/0"], None),
            # Both seats' affected keys, the builder's refusal not shadowing the challenger's.
            (PACKET, changed(REFUSED_PROPOSAL, affected=["builder/interface"], fallback=FALLBACK), REFUSE,
             "the fallback leaves out builder/1, builder/interface", ["builder/1", "builder/interface"],
             "builder: the predicate and identity are entangled\nchallenger: the identity promise is also at stake"),
            # An unknown fallback is reported before a missing confirmation, and that before missing members.
            (PACKET, changed(PROPOSAL, fallback=UNKNOWN), changed(REFUSE, fallback_complete=False),
             "the builder gave no fallback", ["builder/1"], None),
            (PACKET, PROPOSAL, changed(REFUSE, fallback_complete=False),
             "the challenger did not confirm the fallback is complete", ["builder/1"], None),
            (PACKET, changed(PROPOSAL, fallback=both_known), changed(REFUSE, fallback_complete=False),
             "the challenger did not confirm the fallback is complete", ["builder/1"], None),
        ]
        for packet, proposal, review, detail, affected, reason in cases:
            with self.subTest(detail=detail, affected=affected):
                proposal, review = certified(self, packet, proposal, review)
                settled = batch.confirmed_settlement(packet, proposal, review)
                self.assertEqual(settled, {"mode": "blocked", "common": [], "withdrawn": [], "choices": [],
                                           "refusal_reason": reason or "challenger: " + review["refusal_reason"],
                                           "affected": affected, "detail": detail})
                self.assertEqual(list(settled), RECORD_FIELDS)

    def test_settling_never_modifies_its_inputs(self):
        proposal, review = certified(self, PACKET, PROPOSAL, REVIEW)
        before = copy.deepcopy((PACKET, proposal, review))
        settled = batch.confirmed_settlement(PACKET, proposal, review)
        settled["common"][0]["text"] = "changed"
        settled["choices"][0]["a"]["policy"] = "changed"
        self.assertEqual((PACKET, proposal, review), before)


class Direct(unittest.TestCase):
    def direct(self, reveals):
        return batch.direct_settlement(batch.packet(TASK, [], ROLE_READINGS, reveals, INPUTS, SEATS))

    def test_a_builder_owned_dispute_becomes_one_pending_policy_choice(self):
        settled = self.direct(one_dispute())
        self.assertEqual(settled, {
            "mode": "direct",
            "common": [INTERFACE_TERM,
                       {"slot": "p/0", "question": " What is returned?", "text": "One of the objects passed.",
                        "sources": ["builder/1"]},
                       {"slot": "p/1", "question": "What if lo > hi?", "text": "Raise ValueError unless lo <= hi.",
                        "sources": ["challenger/0"]}],
            "withdrawn": [],
            "choices": [{"slot": "c/0", "target": "policy", "question": "What if lo > hi?", "members": ["builder/0"],
                         "a": {"interface": "", "policy": "Raise ValueError when hi < lo. "},
                         "b": {"interface": "", "policy": " Raise ValueError unless lo <= hi. "},
                         "witnesses": [WITNESS], "resolution": "pending", "selected": ""}],
            "refusal_reason": "", "affected": [], "detail": ""})
        self.assertEqual((list(settled), list(settled["choices"][0])), (RECORD_FIELDS, CHOICE_FIELDS))

    def test_a_challenger_owned_dispute_keeps_a_for_the_builder(self):
        agree = [AGREE, {**AGREE, "index": 1}]
        settled = self.direct(role_reveals(challenger={"verdicts": agree}))
        self.assertEqual(settled, {
            "mode": "direct",
            "common": [INTERFACE_TERM,
                       {"slot": "p/0", "question": "What if lo > hi?", "text": "Raise ValueError when hi < lo. ",
                        "sources": ["builder/0"]},
                       {"slot": "p/1", "question": " What is returned?", "text": "One of the objects passed.",
                        "sources": ["builder/1"]}],
            "withdrawn": [],
            "choices": [{
                "slot": "c/0", "target": "policy", "question": "What if lo > hi?", "members": ["challenger/0"],
                "a": {"interface": "", "policy": "Raise ValueError when hi < lo."},
                "b": {"interface": "", "policy": "Raise ValueError unless lo <= hi."},
                "witnesses": [{"source": "challenger/0",
                               "scenario": "clamp(1, Lt(0), Lt(2)) with objects defining only __lt__",
                               "observation": "result or exception", "a": "returns 1", "b": "raises TypeError"}],
                "resolution": "pending", "selected": ""}],
            "refusal_reason": "", "affected": [], "detail": ""})

    def test_an_interface_objection_alone_becomes_an_interface_choice(self):
        settled = self.direct(all_agreed(interface_ok=False, interface_objection="NaN bounds must raise",
                                         interface_replacement="clamp(x, lo, hi), raising ValueError"))
        self.assertEqual(settled, {
            "mode": "direct",
            "common": [{"slot": "p/0", "question": "What if lo > hi?", "text": "Raise ValueError when hi < lo. ",
                        "sources": ["builder/0"]},
                       {"slot": "p/1", "question": " What is returned?", "text": "One of the objects passed.",
                        "sources": ["builder/1"]},
                       {"slot": "p/2", "question": "What if lo > hi?", "text": "Raise ValueError unless lo <= hi.",
                        "sources": ["challenger/0"]}],
            "withdrawn": [],
            "choices": [{"slot": "c/0", "target": "interface", "question": INTERFACE_QUESTION,
                         "members": ["builder/interface"], "a": {"interface": "clamp(x, lo, hi)", "policy": ""},
                         "b": {"interface": "clamp(x, lo, hi), raising ValueError", "policy": ""},
                         "witnesses": [], "resolution": "pending", "selected": ""}],
            "refusal_reason": "", "affected": [], "detail": ""})

    def test_full_agreement_leaves_no_choice(self):
        settled = self.direct(all_agreed())
        self.assertEqual(settled, {
            "mode": "direct",
            "common": [INTERFACE_TERM,
                       {"slot": "p/0", "question": "What if lo > hi?", "text": "Raise ValueError when hi < lo. ",
                        "sources": ["builder/0"]},
                       {"slot": "p/1", "question": " What is returned?", "text": "One of the objects passed.",
                        "sources": ["builder/1"]},
                       {"slot": "p/2", "question": "What if lo > hi?", "text": "Raise ValueError unless lo <= hi.",
                        "sources": ["challenger/0"]}],
            "withdrawn": [], "choices": [], "refusal_reason": "", "affected": [], "detail": ""})
        self.assertEqual(list(settled), RECORD_FIELDS)

    def test_a_distinction_lost_to_scrubbing_never_reaches_a_direct_card(self):
        # Both pass the reveal checks on the raw words and route directly, but display as the same words.
        readings = {**ROLE_READINGS, "builder": {**ROLE_READINGS["builder"], "interface": r'Read "C:\left\schema.json"'}}
        interface = all_agreed(interface_ok=False, interface_objection="read the shared schema",
                               interface_replacement=r'Read "D:\right\schema.json"')
        collapsing = {"scenario": "clamp(8, 9, 5)", "observation": "the log line written",
                      "theirs": r'logs "C:\left\clamp.log"', "mine": r'logs "D:\right\clamp.log"', "decided_by": ""}
        witness = one_dispute(verdicts=[{**AGREE, "index": 1},
                                        {"index": 0, "agree": False, "counter": "Raise ValueError unless lo <= hi.",
                                         "why": "NaN bounds", "witness": collapsing}])
        cases = [(readings, interface, "direct builder/interface: a and b are the same after scrubbing"),
                 (ROLE_READINGS, witness, "direct builder/0: a and b predict the same result after scrubbing")]
        for readings, reveals, message in cases:
            with self.subTest(message=message):
                self.assertIsNone(interface_problem(reveals["challenger"], readings["builder"]["interface"]))
                for role in ("builder", "challenger"):
                    for verdict in reveals[role]["verdicts"]:
                        self.assertIsNone(witness_problem(verdict))
                self.assertEqual(route(sources(readings, reveals), reveals), "direct")
                with self.assertRaises(ValueError) as caught:
                    batch.direct_settlement(batch.packet(TASK, [], readings, reveals, INPUTS, SEATS))
                self.assertEqual(str(caught.exception), message)

    def test_an_empty_display_witness_gives_no_witness(self):
        # Pure-function case: fresh confirmed reveals always carry a witness on a disagreement.
        packet = batch.packet(TASK, [], ROLE_READINGS, one_dispute(), INPUTS, SEATS)
        packet["sources"][0]["witness"] = {}
        self.assertEqual(batch.direct_settlement(packet)["choices"][0]["witnesses"], [])

    def test_a_batch_route_cannot_settle_directly(self):
        flagged = one_dispute(conflicts=[conflict("builder/1", "builder/0")])
        for packet in (PACKET, batch.packet(TASK, [], ROLE_READINGS, flagged, INPUTS, SEATS)):
            with self.subTest(conflicts=packet["conflicts"]), self.assertRaises(ValueError) as caught:
                batch.direct_settlement(packet)
            self.assertEqual(str(caught.exception), "direct settlement needs a direct route")


class Briefs(unittest.TestCase):
    def test_the_proposal_brief_carries_the_packet_and_asks_for_every_field(self):
        text = briefs.propose(PACKET, SHA)
        self.assertTrue(text.startswith("# Confirm: builder\n\n" + briefs.RULES + "\n\n"))
        self.assertEqual(json_blocks(text), [PACKET])
        self.assertEqual(shown_digests(text), [SHA])
        self.assertIn(f"- `packet_sha` (string): `{SHA}`, copied exactly.", text)
        for field in schemas.PROPOSAL["properties"]:
            self.assertIn(f"\n- `{field}` (", text, field)
        for part in ("Absolute paths in your reply are replaced with `<outside>/<file name>` before it is checked",
                     "Trace every source", "Exactly one producer gives the interface",
                     "Column `a` is the builder's position and column `b` the challenger's",
                     "put exactly the empty string in each unused field",
                     "Make separate choices only if every combination of their answers is a valid contract",
                     "Give each role whose endorsement changes its own `withdrawn` entry",
                     "When both seats can sign both, your preference decides",
                     "a root question that asks the human for the entire replacement of those sources",
                     "Everything you leave out must be an agreed term that survives word for word",
                     "Refuse if any choice has no answer you can sign",
                     "Name every `affected` key you can identify; with a known fallback, name at least one.",
                     "With an unknown fallback you may still name the affected keys you can identify, or leave "
                     "`affected` empty if you can identify none."):
            self.assertIn(part, text)
        self.assertIsNone(ABSOLUTE.search(text))

    def test_the_review_brief_carries_the_packet_and_the_exact_proposal(self):
        text = briefs.review(PACKET, SHA, PROPOSAL, PROPOSAL_SHA)
        self.assertTrue(text.startswith("# Confirm: challenger\n\n" + briefs.RULES + "\n\n"))
        self.assertEqual(json_blocks(text), [PACKET, PROPOSAL])
        self.assertEqual(shown_digests(text), [SHA, PROPOSAL_SHA])
        self.assertLess(text.index("## The packet"), text.index("## The builder's proposal"))
        for line in (f"- `packet_sha` (string): `{SHA}`, copied exactly.",
                     f"- `proposal_sha` (string): `{PROPOSAL_SHA}`, copied exactly."):
            self.assertIn(line, text)
        for field in schemas.REVIEW["properties"]:
            self.assertIn(f"\n- `{field}` (", text, field)
        for part in ("Trace every source", "`coverage` (every source and every guarantee inside it is carried)",
                     "Never hold `a` against the builder's `b`",
                     "When you attest, `refusal_reason` is empty and `affected` is an empty list.",
                     "you may leave `affected` empty only when `fallback_complete` is false",
                     "A refused proposal can only be refused, even when you confirm its fallback.",
                     "Start from every whole packet term outside the fallback's members",
                     "its question asks the human for the entire replacement",
                     "If the proposal is sound and only the fallback is incomplete, attest with `fallback_complete` "
                     "false and `affected` empty",
                     "an incomplete fallback then makes the conductor block rather than ask the human for an "
                     "incomplete replacement"):
            self.assertIn(part, text)

    def test_the_shown_digests_name_the_shown_words_fresh_reloaded_or_retried(self):
        task = r'Use \d+? and ``` fences from "C:\Users\me\.parallax\k\spec.md".'
        packet = batch.packet(task, [PRECEDENT], ROLE_READINGS, ROLE_REVEALS, INPUTS, SEATS)
        packet_sha = batch.digest(packet)
        votes = [{"slot": "c/0", "sign": ["a"], "reason": r'see "C:\Users\me\notes\why.txt"'}]
        proposal = batch.accepted(changed(PROPOSAL, packet_sha=packet_sha, votes=votes))
        self.assertEqual(proposal["votes"][0]["reason"], 'see "<outside>/why.txt"')
        proposal_sha = batch.digest(proposal)
        fresh = briefs.review(packet, packet_sha, proposal, proposal_sha)
        reloaded = briefs.review(json.loads(batch.canonical(packet)), packet_sha,
                                 json.loads(batch.canonical(proposal)), proposal_sha)
        self.assertEqual(fresh, reloaded)
        self.assertEqual([batch.digest(block) for block in json_blocks(fresh)], shown_digests(fresh))
        self.assertEqual(shown_digests(fresh), [packet_sha, proposal_sha])
        self.assertEqual(json_blocks(fresh)[0]["task"], r'Use \d+? and ``` fences from "<outside>/spec.md".')
        # A semantic retry keeps the original brief byte for byte and scrubs only the reason it appends.
        retry = briefs.rejected(fresh, r'vote 0 cites "C:\Users\me\x.py"')
        self.assertTrue(retry.startswith(fresh + "\n## Your last reply was rejected\n"))
        self.assertEqual(json_blocks(retry)[:2], json_blocks(fresh))
        self.assertIn('vote 0 cites "<outside>/x.py"', retry)
        self.assertIsNone(ABSOLUTE.search(retry))

    def test_a_retry_keeps_the_whole_base_and_fences_only_its_own_reason(self):
        fresh = briefs.propose(PACKET, SHA)
        base = "\n" + fresh + "\n\n"
        # An unmatched quote before a path must not swallow the closing fence or the final instruction.
        reasons = (r'vote 0 cites "C:\Users\me\x.py and never closes', "choice c/0 needs a witness")
        retries = [briefs.rejected(base, reason) for reason in reasons]
        for retry, mine, other in ((retries[0], "vote 0 cites", reasons[1]), (retries[1], reasons[1], "vote 0 cites")):
            with self.subTest(reason=mine):
                self.assertTrue(retry.startswith(base))
                self.assertEqual(retry.count("## Your last reply was rejected"), 1)
                self.assertIn(mine, retry)
                self.assertNotIn(other, retry)
                self.assertTrue(retry.endswith("```\n\nFix exactly that and reply again, with JSON in the same format "
                                               "as asked above.\n"))
                self.assertIsNone(ABSOLUTE.search(retry))
        self.assertIn('vote 0 cites "<outside>\n```', retries[0])

    def test_a_brief_refuses_a_digest_that_does_not_name_its_words(self):
        for call, message in ((lambda: briefs.propose(PACKET, "sha256:x"), "packet_sha is not the digest of the packet"),
                              (lambda: briefs.review(PACKET, SHA, PROPOSAL, "sha256:x"),
                               "proposal_sha is not the digest of the proposal")):
            with self.subTest(message=message), self.assertRaises(ValueError) as caught:
                call()
            self.assertEqual(str(caught.exception), message)
