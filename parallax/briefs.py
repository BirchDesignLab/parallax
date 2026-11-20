"""The briefs: the only instructions a seat ever gets.

A brief is what one seat sees, so it is where the blind is kept or broken. Before the
reveal a brief carries only the task, the contract, the seat's own role and the
precedents; the other seat's reading arrives only in `reveal`, and its work only as
crossing evidence in `respond`. Every brief is passed through `_scrub`, so no absolute
path (a seat's clone, the state home, a traceback from a scratch clone) ever reaches a seat.

Each brief is meant to stand alone: a fresh seat call is expensive, so a brief says
everything the step needs, including the exact output fields.
"""
from __future__ import annotations

import json
import re
from typing import Sequence

from parallax import batch, redact
from parallax.config import Config
from parallax.decisions import INTERFACE_QUESTION, source_keys
from parallax.redact import scrub_paths as _scrub

RULES = ("Work only in this folder. Do not look outside it. Do not run git. You cannot run the project's "
         "tests here; the conductor runs them and will send you any failure.")

MUTANTS_DIR = ".parallax-mutants"
SCRATCH_DIR = ".parallax-scratch"
ROLES = ("builder", "challenger")

WHAT_LANDS = f"""## What lands

Only files that belong in the project after this task land on main. Two folders in this folder are for Parallax's working files and never land: `{MUTANTS_DIR}/<id>/`, where the builder puts its mutants and nowhere else, and `{SCRATCH_DIR}/`, for any scratch notes or scripts. Do not put copies, notes, scripts or output made only to carry out this task anywhere else. Files the task itself calls for, such as fixtures, examples or docs, are deliverables like any other."""

FILES_FIELD = (f"- `files` (list): every file you have changed since this task began, as it now stands against the "
               f"project's starting point, one entry each with `path` (relative, forward slashes), `change` (`add`, "
               f"`modify` or `delete`; a rename is a delete and an add) and `purpose` (why it belongs on main). Include "
               f"changes from your earlier attempts that you kept. Leave out anything you reverted, and leave out "
               f"`{MUTANTS_DIR}/` and `{SCRATCH_DIR}/`. The conductor compares this list with your actual changes and "
               f"rejects your work if they differ.")


# The reveal's sentences that confirmed-v1 rewords or adds to (Task 19.1).
WITNESS_END = "When you agree, all five are empty strings."
OPEN_PLAIN = ("Points you both accept are settled. Points you hold against each other go to the human, who sees the "
              "witness, both answers and both reasons.")
OPEN_CONFIRMED = ("On the direct path, accepted points stand and the human rules on the single remaining objection, "
                  "if any. In a batch, both seats review the accepted terms and objections together and identify any "
                  "endorsement that would have to change.")
CLOSE_PLAIN = ("Never agree to an answer you believe is contradicted: agreement puts that answer into the contract "
               "as written.")
CLOSE_CONFIRMED = ("Never agree to an answer you believe is contradicted: agreement can put that answer into the "
                   "contract as written. Give your verdict and flag the provisions that conflict.")
CONFLICTS_FIELD = (
    "- `conflicts` (list): pairs of provisions that you believe cannot both stand as written. Each entry has "
    "`source` and `target`, two different keys from the table above, and `reason`, one sentence saying what in "
    "the source would contradict or change the target. Use as `target` a provision you believe should stand, or "
    "`builder/interface` when the source would change the interface; the target may turn out to be disputed by "
    "the other seat. Give one entry per source and target pair. Flag a conflict even when you accept the source. "
    "A flag does not replace a verdict: still give every verdict as asked. Both seats review the provisions "
    "together if either seat flags a conflict, if two or more reading decisions are disputed, or if a reading "
    "decision and the builder's interface are both disputed. Return an empty list when you see no conflict.")


def _block(text: str, lang: str = "") -> str:
    """Fence `text` with more backticks than it contains, so it cannot close the fence early."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    body = text if text.endswith("\n") else text + "\n"
    return f"{fence}{lang}\n{body}{fence}"


def _role(role: str) -> str:
    if role not in ROLES:
        raise ValueError(f"role must be 'builder' or 'challenger', not {role!r}")
    return role


def _other(role: str) -> str:
    return "challenger" if _role(role) == "builder" else "builder"


def _scope(role: str, cfg: Config) -> str:
    return ", ".join(cfg.builder_scope if _role(role) == "builder" else cfg.challenger_scope)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _join(*parts: str) -> str:
    return _scrub("\n\n".join(p.strip("\n") for p in parts if p)) + "\n"


def _precedents(precedents: Sequence[dict]) -> str:
    if not precedents:
        return "## Precedents\n\nNo precedents are in force."
    lines = ["## Precedents",
             "",
             "These are earlier rulings by the human. They are in force for this project. When one answers a "
             "question in this task, use its ruling as your answer and cite its id (for example \"per P-1\") in "
             "`why`. If you believe one no longer applies to this task, do not ignore it: add a decision whose "
             "question names the precedent id and says why it may no longer apply. That sends it back to the human.",
             ""]
    for p in precedents:
        holds = f" Holds while: {p['while']}." if p.get("while") else ""
        source = f" (from task {p['task']})" if p.get("task") else ""
        lines.append(f"- {p['id']}{source}: {p['question']} Ruling: {p['ruling']}.{holds}")
    return "\n".join(lines)


def _mutant_steps(n: int) -> str:
    if n == 0:
        return "## Mutants\n\nThis project asks for no mutants. Return an empty `mutants` list."
    ids = ", ".join(f"m{i}" for i in range(1, n + 1))
    return f"""## Mutants

After the real implementation is done, write {_plural(n, "mutant")}. A mutant is a deliberately broken copy of your change. The challenger's tests must catch every one, so each mutant shows whether those tests are strong enough.

- Put each mutant in its own folder `{MUTANTS_DIR}/<id>/`, using the ids {ids}.
- Inside that folder, place a full copy of every file the mutant changes, at the same relative path it has in the project. Example: a mutant m1 of `src/pkg/core.py` is the whole file at `{MUTANTS_DIR}/m1/src/pkg/core.py`.
- Each mutant makes one small behavior change that the contract forbids: the kind of mistake a careful implementation could plausibly make (an off-by-one, a swapped bound, a missed edge case, a wrong error). It must differ from your real file, and every file it holds must be inside your write paths.
- Make each mutant break a different contract point where you can.
- Do not change your real files to make a mutant. Do not put anything else in `{MUTANTS_DIR}/`.
- The conductor moves this folder out before committing your work; it never lands in the project."""


_INTERFACE_WHOLE = (
    "- `interface` (string): the exact interface you expect: every file to create, change or delete on main "
    "(not Parallax's working files), with paths relative to this folder; the import or entry point; and every "
    "public name with its full signature and calling conventions. Say what forms a result or an error can take, "
    "including errors raised by code the caller supplies. Put the conditions that select an outcome, and the "
    "order of checks, in `decisions`, not here.")
_DECISIONS_WHOLE = (
    "- `decisions` (list): one entry for each behavior guarantee or open choice (edge cases, error handling, "
    "types, naming, behavior at limits). Record each guarantee once, including requirements the task or an "
    "applicable precedent fixes. When one choice decides several consequences, write one entry whose answer "
    "states them all; keep policies that can be chosen independently in separate entries. Each entry has "
    "`question` (the question, stated on its own so it reads clearly out of context), `answer` (what the code "
    "should do, written so it could go straight into a contract) and `why` (your reason, citing any precedent "
    "id you applied). Return an empty list when there is no behavior or open choice to record.")
_INTERFACE_PRIOR = (
    "- `interface` (string): the exact interface you expect: every file to create, change or delete on main "
    "(not Parallax's working files), and every public name in it with its full signature, parameters, return "
    "value and errors raised. Use paths relative to this folder.")
_DECISIONS_PRIOR = (
    "- `decisions` (list): one entry for each question the task leaves open (edge cases, error handling, types, "
    "naming, behavior at limits). Each entry has `question` (the question, stated on its own so it reads clearly "
    "out of context), `answer` (what the code should do, written so it could go straight into a contract) and "
    "`why` (your reason, citing any precedent id you applied). If the task is fully clear, return an empty list.")


def reading(task_text: str, role: str, cfg: Config, precedents: Sequence[dict], whole: bool = True) -> str:
    """Step 2, the sealed reading. Carries nothing from the other seat. whole=False is the brief tasks opened
    before the complete-interface protocol saw."""
    role = _role(role)
    interface_line, decisions_line = ((_INTERFACE_WHOLE, _DECISIONS_WHOLE) if whole
                                      else (_INTERFACE_PRIOR, _DECISIONS_PRIOR))
    return _join(
        f"""# Reading: {role}

{RULES}

Do not change any file in this step. Read the task below and the existing code in this folder, then write down how you read the task, before any code is written.

You will be the {role}. Another seat is writing its own reading of the same task at the same time; you will see it afterwards and say where you agree.

How the work will be split once the contract is frozen:
- The builder implements the change, plus a few deliberately broken copies (mutants), which go in `{MUTANTS_DIR}/` and never land. The builder will write only under: {_scope("builder", cfg)}.
- The challenger writes automated tests (probes) from the contract alone, without seeing the implementation. The challenger will write only under: {_scope("challenger", cfg)}.
- The contract is made from the points both readings agree on, plus the human's rulings where they differ. Anything the contract leaves open is a place where the two sides can disagree later, so be thorough now.""",
        "## The task\n\n" + _block(task_text),
        _precedents(precedents),
        WHAT_LANDS,
        f"""## What to return

Reply with JSON that has exactly these fields:

{interface_line}
{decisions_line}
- `predicted_failures` (list of strings): where an implementation is most likely to go wrong, one item per risk, each concrete enough to write a test for.""",
    )


def _join_scrubbed(*parts: str) -> str:
    """Like `_join`, for parts that are already clean: no whole-text scrub, so serialized JSON stays intact."""
    return "\n\n".join(p.strip("\n") for p in parts if p) + "\n"


def reveal(own_role: str, other_reading: dict, whole: bool = True, own_reading: dict | None = None) -> str:
    """Step 3. The only brief that shows the other seat's reading, and only after both are sealed.

    `own_reading` (confirmed-v1 only, needs whole=True) adds the provision keys and the `conflicts` field."""
    if own_reading is not None and not whole:
        raise ValueError("own_reading needs whole=True")
    own_role = _role(own_role)
    other = _other(own_role)
    decisions = other_reading.get("decisions") or []
    if decisions:
        per_index = (f"The {other}'s reading has {_plural(len(decisions), 'decision')}, numbered from index 0"
                     + (f" to index {len(decisions) - 1}." if len(decisions) > 1 else ".")
                     + " Return exactly one verdict for each index, in order.")
    else:
        per_index = f"The {other}'s reading has no decisions. Return an empty `verdicts` list."
    fields = ("`interface_ok` (boolean), `interface_objection` (string) and `interface_replacement` (string)" if whole
              else "`interface_ok` (boolean) and `interface_objection` (string)")
    if own_role == "challenger" and whole:
        interface = ("The builder's interface stands unless you object. Set `interface_ok` to true to accept it, with "
                     "`interface_objection` and `interface_replacement` as empty strings. To object, set `interface_ok` "
                     "to false, say why in one or two sentences in `interface_objection`, and put in "
                     "`interface_replacement` a complete interface that a caller can use on its own. Carry forward each "
                     "unaffected file, import, public name, signature, calling convention, result form and error form, "
                     "not only the part you would change. If the human agrees, it replaces the builder's interface as "
                     "written. Object only when the interface is wrong or ambiguous, not over style. Also object when "
                     "the interface states a condition or an order of checks that belongs in a decision. Before you "
                     "remove one, find where the task or a sealed decision states the behavior you mean to keep. If "
                     "removing it would lose a guarantee, name the gap in `interface_objection` and keep that guarantee "
                     "in `interface_replacement`. If the only issue is where a guarantee is written and removing it "
                     "would lose it, accept the builder's interface. If another change warrants a replacement, carry "
                     "the guarantee into that replacement. Object too if the interface names a file that should not be "
                     "on main, such as a working copy, scratch file or mutant code.")
    elif own_role == "challenger":
        interface = ("The builder's interface stands unless you object. Set `interface_ok` to true to accept it. "
                     "To object, set `interface_ok` to false and put in `interface_objection` the exact change you "
                     "want, in one or two sentences: if the human agrees, it is added to the interface as written. "
                     "Object only when the interface is wrong or ambiguous, not over style. Also object if the interface "
                     "names a file that should not be on main, such as a working copy, scratch file or mutant code.")
    elif whole:
        interface = ("You are the builder, so your own interface stands. Set `interface_ok` to true and "
                     "`interface_objection` and `interface_replacement` to empty strings.")
    else:
        interface = ("You are the builder, so your own interface stands. Set `interface_ok` to true and "
                     "`interface_objection` to an empty string.")
    head = f"""# Reveal: {own_role}

{RULES}

Do not change any file in this step. Your reading is sealed. Below is the {other}'s reading of the same task, written separately from yours. Go through it point by point."""
    what_to_return = f"""## What to return

Reply with JSON that has exactly these fields:

- {fields}. {interface}
- `verdicts` (list). {per_index} Each verdict has:
  - `index` (integer): the position of the decision in the {other}'s `decisions` list, starting at 0.
  - `agree` (boolean): true if you accept the {other}'s answer as it stands.
  - `counter` (string): when you disagree, your answer to the same question, written so it could go straight into a contract; empty when you agree.
  - `why` (string): your reason when you disagree; may be empty when you agree.
  - `witness` (object): when you disagree, one concrete scenario and what each answer commits to on the same observation. `scenario` is the setup and actions, as concrete as a test: literal inputs, and a sequence of steps when one call cannot show it. `observation` is what to inspect (a returned value and its type, an exception type, output, a file, state). `theirs` is what the {other}'s answer commits to there, or exactly `no commitment` when it leaves that observation open. `mine` is what your counter commits to there. `decided_by` is empty, or the question of another decision, copied verbatim from either reading, that supports your objection. When you agree, all five are empty strings.

{OPEN_PLAIN} Agree when you accept the {other}'s whole answer as written, including when you have no competing requirement and can grant that answer. Differences in wording, emphasis or justification alone are agreement. For a disagreement, give one concrete scenario and say what each answer commits to on the same observation. If their answer leaves that observation open and you require an outcome, put exactly `no commitment` in `theirs`, state your requirement in `counter` and its observable result in `mine`. If another decision supports your objection, copy its question verbatim from either reading into `decided_by` and keep this verdict in disagreement. {CLOSE_PLAIN}"""
    if own_reading is None:
        return _join(head, f"## The {other}'s reading\n\n" + _block(json.dumps(other_reading, indent=2), "json"),
                     what_to_return)
    # Confirmed-v1: the same brief with four changes. Both JSON blocks are built from scrubbed values and
    # skip the whole-text scrub, which would run on JSON-escaped text.
    for part in (WITNESS_END, OPEN_PLAIN, CLOSE_PLAIN):
        assert what_to_return.count(part) == 1, part
    what_to_return = (what_to_return.replace(WITNESS_END, WITNESS_END + "\n" + CONFLICTS_FIELD)
                      .replace(OPEN_PLAIN, OPEN_CONFIRMED).replace(CLOSE_PLAIN, CLOSE_CONFIRMED))
    readings = ({"builder": own_reading, "challenger": other_reading} if own_role == "builder"
                else {"builder": other_reading, "challenger": own_reading})
    questions = [d["question"] for role in ROLES for d in readings[role]["decisions"]] + [INTERFACE_QUESTION]
    entries = [{"key": key, "question": _scrub(question)}
               for key, question in zip(source_keys(readings), questions)]
    key_intro = (f"## Provision keys\n\nEach provision in the two readings has a key. Use these keys, exactly as "
                 f"written, in `conflicts`. Two provisions with the same question still have different keys. You are "
                 f"the {own_role}. Numbered keys starting with `{own_role}/` identify your sealed decisions in reading "
                 f"order. `builder/interface` identifies the builder's complete interface.")
    return _join_scrubbed(
        _scrub(head),
        _scrub(f"## The {other}'s reading") + "\n\n" + _block(json.dumps(redact.scrub_values(other_reading), indent=2), "json"),
        _scrub(key_intro) + "\n\n" + _block(json.dumps(entries, indent=2), "json"),
        _scrub(what_to_return))


def build(contract: str, cfg: Config) -> str:
    """Step 6, the builder's half of the braid. Contract only; the probes stay unseen."""
    return _join(
        f"""# Build

{RULES}

You are the builder. Implement the contract below exactly.

Write only under: {_scope("builder", cfg)}. The exceptions are the two working folders described under What lands: `{MUTANTS_DIR}/` for your mutants and `{SCRATCH_DIR}/` for scratch.

Do not write tests. The challenger is writing tests from the same contract, separately; you will not see them. Afterwards the conductor combines your change with those tests and runs the project's check, then runs the tests against each of your mutants.""",
        "## The contract\n\n" + _block(contract),
        WHAT_LANDS,
        _mutant_steps(cfg.mutants),
        """## What to return

Reply with JSON that has exactly these fields:

- `summary` (string): what you changed, file by file, in a few sentences.
- `blocked` (string): empty when you finished. If the contract cannot be implemented as written, say exactly why here and change as little as possible.
- `mutants` (list): one entry per mutant, each with `id` (its folder name, such as m1), `description` (what behavior it breaks and which contract point forbids that) and `files` (the relative paths it changes, with forward slashes and without the `""" + MUTANTS_DIR + """/<id>/` prefix, such as `src/pkg/core.py`).
""" + FILES_FIELD,
    )


def probe(contract: str, cfg: Config) -> str:
    """Step 6, the challenger's half of the braid. Contract only; the implementation stays unseen."""
    return _join(
        f"""# Probe

{RULES}

You are the challenger. Write automated tests (probes) for the contract below, working from the contract alone.

Write only under: {_scope("challenger", cfg)}, plus `{SCRATCH_DIR}/` for scratch.

The implementation is not in this folder. Do not write it. Do not write a stand-in, fake or copy of it either; import it by the names and paths the contract gives, as if it were already there.""",
        "## The contract\n\n" + _block(contract),
        WHAT_LANDS,
        f"""## How to write the probes

- Cover every point of the contract: each part of the interface and each decision, including the edge cases and errors it names.
- Be exact. The builder will hand in deliberately broken copies of its change (mutants), each making one small behavior change the contract forbids. Your probes must fail on every one of them, so check precise values, boundaries and error types.
- Test only what the contract promises. A probe that demands something the contract does not say will be disputed, and the contract decides.
- Follow the project's existing test layout and framework; look at the tests already in this folder. The conductor runs the project's check command, `{cfg.check}`, so name and place the files where that command finds them.""",
        """## What to return

Reply with JSON that has exactly these fields:

- `summary` (string): the probes you wrote, file by file, and which contract points each covers.
- `blocked` (string): empty when you finished. If the contract is too unclear to test at some point, say exactly where here.
""" + FILES_FIELD,
    )


def respond(role: str, contract: str, evidence: Sequence[dict], cfg: Config, ruling: str = "") -> str:
    """Step 8, after the crossing. Evidence comes from the crossing, so the blind is already over."""
    role = _role(role)
    other = _other(role)
    items, kinds = [], {e["kind"] for e in evidence}
    for e in evidence:
        what = ("The project's check failed with your work and the other side's work combined. Its output:"
                if e["kind"] == "check" else
                "A mutant survived: the probes passed on it. Its description, then the change it makes:")
        items.append(f"### Dispute {e['id']} ({e['kind']})\n\n{what}\n\n" + _block(e["text"]))
    ids = ", ".join(e["id"] for e in evidence)
    guide = []
    if "check" in kinds:
        guide.append("For a failed check, decide whether your side or the other side departs from the contract. "
                     "Concede only if yours does.")
    if "mutant" in kinds:
        guide.append("For a surviving mutant, conceding means adding or tightening probes so that the mutant fails; "
                     "contesting means the contract does not forbid what the mutant does.")
    guide = " ".join(guide)
    if ruling:
        decide = f"""## The human's ruling

{_block(ruling)}

The ruling is final. Repair your side now so that it follows the ruling and the contract. For each dispute id ({ids}), answer `concede`, with `cite` naming the contract line or ruling you followed and `why` saying what you changed."""
    else:
        decide = f"""## What to do

For each dispute id ({ids}), choose one:

- `concede`: your side is wrong. Repair your own side now, in this step, within your write paths.
- `contest`: your side follows the contract. Put the contract line that supports you, quoted exactly, in `cite`, and explain in `why`. Change no file for a dispute you contest.

{guide}

If you contest every dispute, change nothing at all: any change you make is discarded. If both sides contest, the human rules and the contract is amended."""
    if role == "builder" and cfg.mutants:
        mutants = (f"## Mutants\n\nYour earlier mutants have been moved out of this folder. If you change any file, "
                   f"write {_plural(cfg.mutants, 'mutant')} again against your new code, as before: each in "
                   f"`{MUTANTS_DIR}/<id>/` (ids m1, m2, ...) holding a full copy of every file it changes at the same "
                   f"relative path, each a small behavior change the contract forbids, and list them in `mutants`. "
                   f"If you change nothing, return an empty `mutants` list.")
    else:
        mutants = "## Mutants\n\nReturn an empty `mutants` list."
    return _join(
        f"""# Respond: {role}

{RULES}

You are the {role}. Your work and the {other}'s work were combined and checked against the contract below. The problems found are listed under their dispute ids.

Write only under: {_scope(role, cfg)}, plus the working folders described under What lands.""",
        "## The contract\n\n" + _block(contract),
        "## The evidence\n\n" + "\n\n".join(items),
        decide,
        mutants,
        WHAT_LANDS,
        """## What to return

Reply with JSON that has exactly these fields:

- `answers` (list): one entry per dispute id, each with `dispute` (the id), `stance` (`concede` or `contest`), `cite` (the contract line or ruling you rely on) and `why` (your reason, and what you changed if anything).
- `blocked` (string): empty when you finished; otherwise exactly what stops you.
- `mutants` (list): as described under Mutants, each entry with `id`, `description` and `files` (relative paths without the mutant folder prefix).
""" + FILES_FIELD + " If you contest every dispute, repeat your full list unchanged.",
    )


def solo(task_text: str, cfg: Config) -> str:
    """A chore: one seat, no challenger, no contract."""
    return _join(
        f"""# Solo task

{RULES}

Do the task below. It is a chore that should not change the project's behavior, so no other seat checks it. You may change any file in this folder that the task needs, and nothing more.

When you finish, the conductor runs the project's check command, `{cfg.check}`, and it must still pass. Keep existing behavior and tests intact.""",
        "## The task\n\n" + _block(task_text),
        WHAT_LANDS,
        """## What to return

Reply with JSON that has exactly these fields:

- `summary` (string): what you changed, file by file.
- `blocked` (string): empty when you finished; otherwise exactly what stops you.
""" + FILES_FIELD,
    )


SCRUB_NOTE = ("Absolute paths in your reply are replaced with `<outside>/<file name>` before it is checked and "
              "recorded, so never rely on one to tell two answers apart.")
PROPOSE_INTRO = (
    "Do not change any file in this step. Both readings are sealed and both reveals are in. Together they leave "
    "more than one point in dispute, or a seat flagged a conflict, so no card goes to the human yet. You propose "
    "how the contract settles. Then the challenger checks your proposal word for word, in its own session, and "
    "either attests it or refuses it. " + SCRUB_NOTE)
PROPOSE_GUIDE = """## What to propose

- **Trace every source** in the packet's `sources`, including every guarantee inside a disputed answer, to the exact common text or choice values that carry it. Each key goes into at least one common term (`common`) or choice (`choices`). A disputed source can settle entirely into common text that both seats can sign, or keep a residual common promise and also feed a choice. Treat citations (`decided_by`) as leads, not as groupings. Use packet keys exactly as written, each at most once in any one list.
- **`common`** holds the terms both seats can sign as written: the complete interface under slot `interface` (unless the interface is itself a choice), and each decision under slots `p/0`, `p/1`, ... in order. Each term has a question, its text, and at least one source key in `sources`.
- **`choices`** holds what is still open, one entry per independent choice, under slots `c/0`, `c/1`, ... in order. `target` is `policy` for a decision, `interface` for the complete interface, or `combined` when the interface and a decision cannot be chosen separately. Each choice has a root question and at least one member key. Column `a` is the builder's position and column `b` the challenger's. Fill `policy` for a policy choice, `interface` for an interface choice, and both for a combined one; put exactly the empty string in each unused field. Give at least one witness per choice: a concrete scenario and observation where `a` and `b` commit to different results, with a member key as its `source`. A structural witness may use an import or a call. Make separate choices only if every combination of their answers is a valid contract.
- **Exactly one producer gives the interface**: the common `interface` term, or one `interface` or `combined` choice. `builder/interface` is among its sources.
- **Withdrawals.** If an agreed source moves into a choice, it loses its standing as an unconditional promise. Give each role whose endorsement changes its own `withdrawn` entry: the `role`, the `source`, every choice slot it moves to (`destinations`, in choice order) and a `reason`.
- **`assent`.** Set all five to true when you vouch for the whole proposal: `coverage` (every source and every guarantee inside it is carried), `shared_terms` (the common terms say what both seats promised), `withdrawals` (every withdrawn endorsement is listed), `columns_and_witnesses` (each column states its side and each witness predicts what each column commits to), `all_combinations` (every combination of separate choices is a valid contract).
- **`votes` and `preferences`.** One vote per choice: `sign` lists each answer you can sign (`a`, `b` or both) once, with a reason. One preference per choice: the answer you prefer among those you sign. An answer both seats can sign settles without the human. When both seats can sign both, your preference decides. When you hold `a` and the challenger holds `b`, the choice goes to the human as one card.
- **`fallback`**, in case the challenger refuses your proposal. A known fallback names whole source keys, and a root question that asks the human for the entire replacement of those sources. Include every source that is disputed, flagged in a conflict, withdrawn, or otherwise affected. Everything you leave out must be an agreed term that survives word for word. If you cannot say, set `known` to false, with no members and an empty question.
- **Refusing.** Refuse if any choice has no answer you can sign, if you cannot propose terms the challenger could check, or if you cannot vouch for the claims above. Set `decision` to `refuse` and give `refusal_reason`. Leave `common`, `choices`, `withdrawn`, `votes` and `preferences` empty, and set every `assent` flag to false. Name every `affected` key you can identify; with a known fallback, name at least one. With an unknown fallback you may still name the affected keys you can identify, or leave `affected` empty if you can identify none."""
PROPOSE_FIELDS = """## What to return

Reply with JSON that has exactly these fields:

- `packet_sha` (string): `{packet_sha}`, copied exactly.
- `decision` (string): `propose` or `refuse`.
- `common` (list): each entry with `slot`, `question`, `text` and `sources` (a list of keys).
- `choices` (list): each entry with `slot`, `target`, `question`, `members` (a list of keys), `a` and `b` (each an object with `interface` and `policy`) and `witnesses` (a list, each with `source`, `scenario`, `observation`, `a` and `b`).
- `withdrawn` (list): each entry with `role`, `source`, `destinations` (a list of choice slots) and `reason`.
- `assent` (object): `coverage`, `shared_terms`, `withdrawals`, `columns_and_witnesses` and `all_combinations`, each a boolean.
- `votes` (list): each entry with `slot`, `sign` (a list of `a` and `b`) and `reason`.
- `preferences` (list): each entry with `slot` and `answer` (`a` or `b`).
- `fallback` (object): `known` (boolean), `members` (a list of keys) and `question` (string).
- `refusal_reason` (string): empty when you propose.
- `affected` (list of keys): empty when you propose."""
REVIEW_INTRO = (
    "Do not change any file in this step. Both readings are sealed and both reveals are in. The builder has "
    "proposed how the contract settles, from the packet below. Check the proposal word for word, then attest it "
    "or refuse it. No card goes to the human until you answer. " + SCRUB_NOTE)
REVIEW_GUIDE = """## How to review

- **Trace every source** in the packet, including every guarantee inside a disputed answer, to the exact common text or choice values that carry it. Check whose endorsement each withdrawal changes and every destination it names, each standing promise in `common`, both columns against their witnesses, and every combination of separate choices.
- **Attest** only if you can vouch for the proposal exactly as written. Set `decision` to `attest` and all five `assent` flags to true: `coverage` (every source and every guarantee inside it is carried), `shared_terms` (the common terms say what both seats promised), `withdrawals` (every withdrawn endorsement is listed), `columns_and_witnesses` (each column states its side and each witness predicts what each column commits to), `all_combinations` (every combination of separate choices is a valid contract). Give one vote per choice: `sign` lists each answer you can sign (`a`, `b` or both) once, with a reason. An answer both seats can sign settles without the human. When you hold `b` and the builder holds `a`, the choice goes to the human as one card. Never hold `a` against the builder's `b`: that reverses the columns, so refuse instead. When you attest, `refusal_reason` is empty and `affected` is an empty list.
- **Refuse** if any word must change, if you can sign neither answer of a choice, or if you cannot vouch for the claims above. Set `decision` to `refuse`, say why in `refusal_reason`, leave `votes` empty and set every `assent` flag to false. Name every `affected` key you can identify; you may leave `affected` empty only when `fallback_complete` is false. A refused proposal can only be refused, even when you confirm its fallback.
- **`fallback_complete`**, independently of your decision. Start from every whole packet term outside the fallback's members. Set it true only if the builder's fallback is known, its question asks the human for the entire replacement, and every term outside it can survive word for word. Check disputed sources, both ends of each conflict, withdrawn sources and any collateral promise. Report an omitted term honestly.
- **Assess the proposal and the fallback separately.** If the proposal is sound and only the fallback is incomplete, attest with `fallback_complete` false and `affected` empty: the proposal settles and the fallback is never used. If you refuse, name the affected sources; an incomplete fallback then makes the conductor block rather than ask the human for an incomplete replacement."""
REVIEW_FIELDS = """## What to return

Reply with JSON that has exactly these fields:

- `packet_sha` (string): `{packet_sha}`, copied exactly.
- `proposal_sha` (string): `{proposal_sha}`, copied exactly.
- `decision` (string): `attest` or `refuse`.
- `assent` (object): `coverage`, `shared_terms`, `withdrawals`, `columns_and_witnesses` and `all_combinations`, each a boolean.
- `votes` (list): each entry with `slot`, `sign` (a list of `a` and `b`) and `reason`.
- `fallback_complete` (boolean).
- `refusal_reason` (string): empty when you attest.
- `affected` (list of keys): empty when you attest."""


def _json_part(heading: str, value: dict) -> str:
    # The block is batch.canonical of the accepted value, so the digest printed above it is the digest of the
    # parsed block, and a value reloaded from a stored artifact renders the same bytes.
    clean = redact.scrub_values(value)
    return (_scrub(heading) + f"\n\nIts digest is `{batch.digest(clean)}`.\n\n" + _block(batch.canonical(clean), "json"))


def propose(packet: dict, packet_sha: str) -> str:
    if batch.digest(redact.scrub_values(packet)) != packet_sha:
        raise ValueError("packet_sha is not the digest of the packet")
    return _join_scrubbed(
        _scrub(f"# Confirm: builder\n\n{RULES}\n\n{PROPOSE_INTRO}"),
        _json_part("## The packet", packet),
        _scrub(PROPOSE_GUIDE),
        _scrub(PROPOSE_FIELDS.format(packet_sha=packet_sha)))


def review(packet: dict, packet_sha: str, proposal: dict, proposal_sha: str) -> str:
    if batch.digest(redact.scrub_values(packet)) != packet_sha:
        raise ValueError("packet_sha is not the digest of the packet")
    if batch.digest(redact.scrub_values(proposal)) != proposal_sha:
        raise ValueError("proposal_sha is not the digest of the proposal")
    return _join_scrubbed(
        _scrub(f"# Confirm: challenger\n\n{RULES}\n\n{REVIEW_INTRO}"),
        _json_part("## The packet", packet),
        _json_part("## The builder's proposal", proposal),
        _scrub(REVIEW_GUIDE),
        _scrub(REVIEW_FIELDS.format(packet_sha=packet_sha, proposal_sha=proposal_sha)))


def rejected(brief: str, reason: str) -> str:
    """`brief`, kept whole byte for byte, followed by why the conductor rejected the last reply."""
    suffix = f"""## Your last reply was rejected

The conductor rejected your last reply for this reason:

{_block(_scrub(reason))}

Fix exactly that and reply again, with JSON in the same format as asked above."""
    separator = "\n" if brief.endswith("\n") else "\n\n"
    return brief + separator + suffix + "\n"


def retry(reason: str) -> str:
    """Sent in the same session after the conductor rejects an attempt."""
    return _join(
        f"""# Retry

The conductor rejected your last attempt for this reason:

{_block(reason)}

Fix exactly that, keep the rest of your work, and finish the same step. Undo any change outside your write paths. Reply again with JSON in the same format as before.

{RULES}""",
    )
