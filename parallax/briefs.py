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

from parallax.config import Config
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


def reveal(own_role: str, other_reading: dict, whole: bool = True) -> str:
    """Step 3. The only brief that shows the other seat's reading, and only after both are sealed."""
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
    return _join(
        f"""# Reveal: {own_role}

{RULES}

Do not change any file in this step. Your reading is sealed. Below is the {other}'s reading of the same task, written separately from yours. Go through it point by point.""",
        f"## The {other}'s reading\n\n" + _block(json.dumps(other_reading, indent=2), "json"),
        f"""## What to return

Reply with JSON that has exactly these fields:

- {fields}. {interface}
- `verdicts` (list). {per_index} Each verdict has:
  - `index` (integer): the position of the decision in the {other}'s `decisions` list, starting at 0.
  - `agree` (boolean): true if you accept the {other}'s answer as it stands.
  - `counter` (string): when you disagree, your answer to the same question, written so it could go straight into a contract; empty when you agree.
  - `why` (string): your reason when you disagree; may be empty when you agree.
  - `witness` (object): when you disagree, one concrete scenario and what each answer commits to on the same observation. `scenario` is the setup and actions, as concrete as a test: literal inputs, and a sequence of steps when one call cannot show it. `observation` is what to inspect (a returned value and its type, an exception type, output, a file, state). `theirs` is what the {other}'s answer commits to there, or exactly `no commitment` when it leaves that observation open. `mine` is what your counter commits to there. `decided_by` is empty, or the question of another decision, copied verbatim from either reading, that supports your objection. When you agree, all five are empty strings.

Points you both accept are settled. Points you hold against each other go to the human, who sees the witness, both answers and both reasons. Agree when you accept the {other}'s whole answer as written, including when you have no competing requirement and can grant that answer. Differences in wording, emphasis or justification alone are agreement. For a disagreement, give one concrete scenario and say what each answer commits to on the same observation. If their answer leaves that observation open and you require an outcome, put exactly `no commitment` in `theirs`, state your requirement in `counter` and its observable result in `mine`. If another decision supports your objection, copy its question verbatim from either reading into `decided_by` and keep this verdict in disagreement. Never agree to an answer you believe is contradicted: agreement puts that answer into the contract as written.""",
    )


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


def rejected(brief: str, reason: str) -> str:
    """`brief` followed by why the conductor rejected the last reply."""
    return _join(brief, f"""## Your last reply was rejected

The conductor rejected your last reply for this reason:

{_block(reason)}

Fix exactly that and reply again, with JSON in the same format as asked above.""")


def retry(reason: str) -> str:
    """Sent in the same session after the conductor rejects an attempt."""
    return _join(
        f"""# Retry

The conductor rejected your last attempt for this reason:

{_block(reason)}

Fix exactly that, keep the rest of your work, and finish the same step. Undo any change outside your write paths. Reply again with JSON in the same format as before.

{RULES}""",
    )
