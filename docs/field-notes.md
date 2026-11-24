# Field notes

What happened when real models ran Parallax, what each run cost, and what each run changed. Every figure here was recorded on one Windows 11 machine and is dated. None of it is a benchmark.

The task in every run is the demo's: add `clamp(x, lo, hi)` to a small library. The spec is one sentence and deliberately says nothing about `lo > hi`, NaN or non-numbers.

## Run 1: four questions that were one question

2026-11-17. Codex building, Claude challenging.

The two models agreed that `lo > hi` raises `ValueError`. They split on four other reading questions: inclusive bounds, `lo == hi`, accepted types, and NaN bounds. Each split became its own card, so the human ruled four times. The task then landed at the first crossing with verdict `ruled`: 90 probes passed and 3 of 3 mutants were caught.

**What it changed.** The four cards were largely one question about the bounds, asked four times. That is a cost the human pays, and it was the protocol's doing, not the models'. The settlement step was built in response: when the seats disagree in several places, or one says two provisions conflict, the builder proposes a single account of the whole task and the challenger reviews exactly that proposal. Only a choice where each seat still holds a different answer becomes a card, and one card can cover several provisions.

## Run 2: the same task, nothing asked

2026-11-23. Codex CLI 0.170.0 with `gpt-6.2-astra` at `xhigh` building, Claude Code 2.1.311 with `fable` at `high` challenging. The first real run under the settlement.

- Codex objected to five of Claude's nine reading decisions. Claude objected to none of Codex's five.
- Codex flagged eight conflicts between provisions and Claude two.
- That routed the task to the confirmed batch. Codex's proposal gave seven common terms, no open choice and no withdrawal. Claude attested it.
- One settlement record was published, with no card. The contract froze from it.
- Build and probes ran in parallel. Crossing 1 passed: 84 probes, 3 of 3 mutants caught.
- The task landed with verdict `consensus`, about ten minutes after it opened.

Same task, same models, four rulings before and none now.

## Run 3: a task that contradicts itself

2026-11-23, same project, roles rotated: Claude building, Codex challenging. The task was written to contradict itself: "Values that cannot be compared with the bounds are skipped. The result always has one entry for each input value."

- Both seats read the contradiction the same way (a value that cannot be compared stays in its position, unchanged), so it raised no dispute.
- Claude proposed. Codex refused, because the proposal's interface had dropped the guarantee that the new probes are discovered by the project's unittest command.
- The seats agreed which provisions a ruling would replace, so one refusal card was published, offering `other` or `drop` and covering ten provisions.
- The human ruled `other` with one note holding an interface and a policy. The run had paused with exit code 2 and was resumed by a second `run` after the ruling.
- Crossing 1 failed the check. Each seat responded once: the builder's commit changed and the challenger's did not. Crossing 2 passed: 108 probes, 3 of 3 mutants caught.
- The task landed with verdict `ruled`, after about fourteen minutes of seat time.

**What it showed.** Two things, neither resolved yet:

1. A refusal over one narrow omission cost the human a ruling that restates the interface and the policy for ten provisions. The protocol did what it specifies. Whether a narrow refusal should go back to the seats for one repair exchange first is an open design question.
2. Neither seat treated a self-contradicting task as something to ask about. Both quietly picked the same reading. Agreement between two models is evidence, and here it was agreement on a guess.

## What it cost

Token use as each CLI reported it, per task, both seats.

| Run | Seat | Input tokens | Of which cached | Output tokens |
|---|---|---|---|---|
| 2 | Codex (builder) | 325,817 | 202,112 | 12,216 |
| 2 | Claude (challenger) | 177,139 | 57,295 | 30,191 |
| 3 | Claude (builder) | 758,156 | 400,552 | 29,620 |
| 3 | Codex (challenger) | 953,964 | 694,656 | 19,736 |

The conductor itself spends nothing: it is ordinary code.

### A correction worth keeping

The first figures recorded for Codex were about twice these. Codex reports token usage as a running total for the whole session, not per call, and the conductor was adding that running total once per call. The symptom was in the ledger: within a task, Codex's input and output never fell from one call to the next and its cached figure repeated exactly, while Claude's figures rose and fell call by call.

The Codex seat now reports each call's difference from the session's last total, and keeps that total on disk so the arithmetic survives a restart. `scripts/probes/usage_by_call.py` prints a project's usage per call, which is how the pattern was found. Events written to a ledger before the fix keep the figures they were written with.

## What real seats have not yet done

The stub suite covers each of these on scripted seats. None has run with real models:

- a settlement that leaves an A/B card,
- the direct settlement path (no conflict flag and at most one objection),
- a run killed mid-step and resumed.

## What the real CLIs were observed to do

The design depends on specific behavior of both CLIs: how each is confined, what its event stream carries, how a session resumes. Those observations are listed with dates in the [design document](superpowers/specs/2026-11-16-parallax-design.md) under "Verified and not yet verified". A few that shaped the code:

- Codex's sandbox limits where an agent writes, not what it reads. What it can read is decided by folder permissions, so each task's state folder is made private before anything is put in it.
- Claude under `--restricted` refuses a read outside its working directory and reports the refusal in its event stream. With only file tools granted, it has no shell at all.
- Inside the Codex sandbox, `python` does not resolve on this machine. Seats are therefore never relied on to run project tools; the conductor runs every check.
- Codex's sandbox can fail to start a process once and then recover, so the adapter retries a launch that never started a session.
- A file named `claude.md` is loaded by Claude Code as instructions on Windows. Nothing the conductor writes is named after an agent's instruction file.

`scripts/probes/seat_smoke.py` reproduces these and exits non-zero if any expectation fails. It is rerun, with `scripts/probes/job_object_seats.py`, whenever either CLI updates.

## See also

- [Documentation index](README.md)
- [Concepts](concepts.md)
- [The life of a task](life-of-a-task.md)
- [Rulings and precedents](rulings.md)
- [Receipts and the ledger](receipts.md)
- [Keeping the blind](blind.md)
- [Commands](cli.md)
- [parallax.toml](configuration.md)
- [Architecture](architecture.md)
- [FAQ](faq.md)
