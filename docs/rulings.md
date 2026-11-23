# Rulings and precedents

When the two seats disagree in a way they cannot settle with evidence, the human gets a ruling card. This page covers what counts as a dispute, the four routes from the reveals to a card, how to read a card and answer it with `parallax rule`, how an answer persists as a precedent, and the disputes that a failed crossing opens.

<p align="center"><img src="assets/routes.svg" alt="Four routes from the reveals. Nothing in dispute: the contract freezes and no card is made. One objection: one card with both answers, both reasons and the case that splits them. Several objections or two provisions in conflict: one more exchange in which the builder proposes one account and the challenger reviews it, and a card only where each seat holds a different answer. A refused proposal: one card to replace or drop. If the seats cannot agree on what a ruling would replace, the task is blocked." width="100%"></p>

## What a dispute is

A dispute needs evidence. Opinions do not open disputes.

- **Before the build,** the evidence is a witness. A seat that disagrees with the other's reading gives a counteranswer and one concrete scenario: what to observe, what the other answer predicts there, and what its own answer predicts. The conductor rejects a witness that predicts the same result under both answers, and sends it back to the seat. A seat may say the other answer makes no commitment on the case.
- **After the crossing,** the evidence is a failing check, a mutant that survived, or a contract line that was not met.

The human is asked only what the seats cannot settle, and is not asked again while the conditions of a ruling still hold.

## The four routes

After both reveals are in, the conductor looks at how much the seats disagree, and that decides the route.

### Direct

No seat flagged a conflict between provisions, and at most one provision is objected to. The conductor settles from the reveals without another seat call.

- No objection: everything agreed, no card.
- One objection, to a reading decision or to the interface: one card with the original positions and their evidence, with the choices `a`, `b` and `other`.

### Confirmed batch

Any conflict flag sends the task here. Without a flag, it takes at least two objections, at least one of them to a reading decision. Several objections are often one question asked several times, so the seats get one more exchange before the human does.

1. The builder proposes one account of the whole task, in a read-only call: the terms both seats can sign as written, any agreement that is now withdrawn because it moved into a choice, and each remaining choice with its two answers (`a` is the builder's, `b` the challenger's), at least one witness per choice, and a vote and preference per choice.
2. The challenger reviews exactly those terms, word for word, in a separate read-only call. It attests or refuses.
3. For each choice, one answer signed by both seats stands. If both sign both answers, the builder's recorded preference stands. If the builder signs only `a` and the challenger only `b`, the choice becomes a card.

A challenger that holds `a` against the builder's `b` is not a valid vote. It must refuse instead.

A card from this route can cover several provisions at once. It shows the covered provisions, the original evidence, each seat's vote and reason, and the predictions both seats confirmed.

### Refusal

A seat can refuse the proposal. The task gets one card, offering `other` or `drop`, only when all of these hold:

- the builder identified a fallback boundary: which provisions a ruling would have to replace;
- the challenger confirmed that boundary is complete;
- it covers every disputed or named affected provision, both ends of every flagged conflict and any withdrawn agreement.

The card shows the reasons for the refusal, the provisions to replace, and the terms that survive word for word. The human supplies one replacement, or drops the task.

### Blocked

If the boundary is incomplete or the challenger did not confirm it, no card is made and the settlement is blocked. `parallax status` shows the reason and the provisions affected. There is no card to rule on.

### Settlement is recorded once

One `reading.settled` record, appended to the journal as a single line, publishes every card's id and text together. The card files are written from it, and every later step reads that record. Each pending card takes exactly one ruling. Nothing is built until every card is ruled and the contract is frozen from the result.

## Anatomy of a card

This card is from the stub demo's task, where the seats disagreed about `lo > hi`:

```text
Dispute D-clamp-001-1 (reading)

What if lo > hi?

a) codex (builder):
| raise ValueError
b) claude (challenger):
| swap the bounds
other) Supply the policy with --note.

Sources:
- builder/0: What if lo > hi?
  codex (builder): raise ValueError
    why: caller error
  claude (challenger): swap the bounds
    why: Treat the bounds in either order so the same interval is accepted.
  witness from claude (challenger): clamp(5, 10, 1) (what the call returns or raises): codex (builder) raises ValueError; claude (challenger) returns 5

parallax rule D-clamp-001-1 a
```

From the top:

- **The header** is the dispute id and its kind. Ids are `D-<task>-<n>`. The kind is `reading` for a behavior question, `interface` for the interface, `refusal` for a refused proposal, and `check`, `mutant` or `unresolved` for disputes after a crossing.
- **The question** is stated on its own, so it reads clearly out of context.
- **The columns.** `a` is the builder's answer and `b` the challenger's, each quoted line by line with `|` so the text appears exactly as written. A text with characters a terminal would not show as themselves is printed as one escaped line.
- **The `other` line** says what your own answer must be: here a policy, supplied with `--note`.
- **Sources** list each provision the card covers, by key. `builder/0` is the builder's first decision. `challenger/<n>` is the challenger's, and `builder/interface` is the builder's interface. For each, you see both positions with their reasons, and the witness: its author, the scenario, what is observed, and what each answer returns there.
- **The last line** is the command that records the first choice. A card from the confirmed batch route also lists each seat's vote and reason, and the predictions both seats confirmed.

The same text is written to `.parallax/run/<task>/cards/<id>.md`, printed by `run`, and recorded in the settlement. Absolute paths in a card are replaced with `<outside>/<file name>`.

## Answering with `rule`

```powershell
python -m parallax rule D-clamp-001-1 a --repo "<project folder>"
```

The command is `parallax rule <dispute> <choice>`, with these options:

| Option | Meaning |
|---|---|
| `--note TEXT` | Your own answer for `other`, or a reason. What each card takes is listed below. |
| `--scope task\|project` | Whether the answer binds this task only, or later tasks too. |
| `--while TEXT` | The condition under which the answer holds, for example "while there is a single user". |
| `--limitation TEXT` | Accept the change with a stated limitation, written on the receipt. See [Limitations and waivers](#limitations-and-waivers). |
| `--repo PATH` | The project folder, when not running from it. |

A card accepts only the choices it lists:

| Card | Choices |
|---|---|
| `reading` or `interface`, from the direct or confirmed batch route | `a`, `b`, `other` |
| `refusal` | `other`, `drop` |
| `check`, after a crossing | `a`, `b` |
| `mutant`, after a crossing | `a`, `b` |
| `unresolved`, after the repair rounds | `a`, `b`, `drop` |

What `--note` takes depends on the card:

- Where the card covers a policy, `other` takes the policy text.
- Where it covers the interface, `other` takes the complete interface, since an interface ruling replaces the whole interface.
- Where it covers both, `other` takes one JSON object with exactly two string fields, `interface` and `policy`, neither blank. The card's `other` line says which of the three applies.
- On a card from a settlement (direct, confirmed batch or refusal), `a` and `b` take no note: the card's column is the ruling.
- On a `check` or `unresolved` card, a note replaces the default text of the ruling, which is "<seat> (<role>) is right."
- On a `refusal` or `unresolved` card, a note given with `drop` is the recorded reason.

A ruling is refused if the card already has one, if the choice is not on the card, or if the text is not valid UTF-8. A successful `rule` prints `recorded <dispute>: <choice>` and exits 0. Then run the same task again:

```powershell
python -m parallax run tasks/clamp-001.md
```

`rule` takes the same lock as `run`, so it refuses while a run is active.

`drop` ends the task. Only the record lands: the task's ledger events and the precedents, in a commit titled `<task>: dropped`, with no receipt trailers. The outcome is `dropped`, with exit code 3.

## Scope and defaults

A ruling has a scope: this task, or the whole project. Only project-scoped rulings become precedents.

| Ruling | Default scope |
|---|---|
| A policy answer (a behavior question) | project |
| An interface ruling | task |
| A combined interface-and-policy ruling | task |
| A refusal ruling | task |
| A `check` ruling after a crossing | project |
| A `mutant` or `unresolved` ruling | task, always |
| `drop` | task, always |

`--scope` overrides a default, except on the rows marked "always". Each project-scoped ruling supplies one precedent.

A task opened by an earlier version of Parallax finishes under the rules it was opened with. A behavior task opened before the confirmed route keeps one standalone card per objection. A whole-interface opening keeps complete replacements and its task-scope interface default. An opening from before that keeps interface amendments and its project-scope interface default. Existing cards, rulings and their ids carry forward.

## Precedents

A project-scoped ruling is a precedent. Precedents are numbered `P-1`, `P-2`, and so on, in the order they were ruled, and each keeps its question, its ruling, its `--while` condition and the task it came from. They are written to `.parallax/PRECEDENTS.md` in each landing commit:

```text
# Precedents

- **P-1** (clamp-001) What if lo > hi? -> raise ValueError
```

Precedents in force go into the reading briefs, and into the contract's "Precedents in force" section that the build and probe briefs carry. A seat is told to use the ruling as its answer and to cite its id in `why` (for example "per P-1"). On a confirmed task, the settlement packet pins the precedents alongside the readings, so the settlement and the contract agree on what was in force.

The conductor includes every project-scoped precedent. The `--while` condition is text the seats read. A seat that believes a precedent no longer applies must not ignore it: it adds a decision whose question names the precedent id and says why it may no longer apply, which sends the question back to the human. That is the only way a settled question returns.

## The conductor never waits

The conductor never blocks at a prompt. When it needs a ruling it writes the card to disk, prints it, and exits with code 2. `parallax rule` records the answer, and `parallax run` picks up where it stopped. Because the card is a file and the answer is a command, any front end can present the card.

| Exit code | Outcome |
|---|---|
| 0 | The task landed |
| 2 | A ruling is needed: the cards were printed |
| 3 | Parked, blocked or dropped |
| 1 | An error, such as a bad config or a git failure |

After the cards, `run` prints a last line such as `clamp-001: needs_ruling  needs a ruling on D-clamp-001-1`. `parallax status` lists each task, its state and the ids it waits on.

## Disputes after a failed crossing

A crossing that is not clean opens disputes from its evidence. The seats go first: each concedes and repairs, or contests and cites the contract. Only if nobody concedes does the question become a card. [The life of a task](life-of-a-task.md#when-the-crossing-fails) describes that exchange. These are the cards.

**Check.** The question is "The check fails. Whose reading of the contract is right?" Its columns are each seat's cited contract line and reason, and the evidence is the end of the check output. Ruling `a` means the builder is right, so the challenger repairs. Ruling `b` means the challenger is right, so the builder repairs. The ruling's text, the default or your `--note`, is added to the contract as a decision, which freezes as the next contract version. The repair brief carries the ruling, and the conductor crosses again.

**Mutant.** The question is "Mutant m2 survived: ... Must the probes catch it?" Ruling `a` ("Yes: it breaks the contract") makes the challenger tighten its probes. Ruling `b` waives the mutant: nothing is repaired, and the waived mutant no longer stops a crossing from being clean.

**Unresolved.** If two repair rounds have not made the crossing clean, the human gets the unresolved tradeoff: `a` says the probes are wrong, `b` says the code is wrong, and `drop` ends the task. Each ruling on this card allows one further repair and crossing.

A repair after a ruling is followed by a crossing even if it changed nothing, so a loop that makes no progress ends at the repair limit and then with the human.

### Limitations and waivers

Main never receives a failing check. Accepting a limitation does not override a failure. It amends the contract and the probes to say what is no longer promised, then the crossing runs again and has to pass.

- `--limitation TEXT` on a ruling after a crossing adds a decision to the contract, "What is no longer promised?", with your text. The losing side repairs against the amended contract. The text is written on the receipt as a `Limitation:` trailer, and the verdict becomes `limited`.
- A mutant the probes cannot catch may be waived: rule `b` on its card. Its limitation starts with `mutant <id> waived`, followed by your note if you gave one, and appears on the receipt. A waived mutant counts as not caught in the `Checks:` line, so `3 of 3` becomes `2 of 3`.

Either way the limitation is on the receipt. See [Receipts and the ledger](receipts.md).

## See also

- [Documentation index](README.md)
- [Concepts](concepts.md)
- [The life of a task](life-of-a-task.md)
- [Receipts and the ledger](receipts.md)
- [Keeping the blind](blind.md)
- [Commands](cli.md)
- [parallax.toml](configuration.md)
- [Architecture](architecture.md)
- [Field notes](field-notes.md)
- [FAQ](faq.md)
