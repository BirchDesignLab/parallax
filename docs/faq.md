# FAQ

Short answers to the questions people ask first. Each links to the page with the full account.

## Does it need both Claude Code and Codex?

For real runs, yes: both CLIs, both signed in. The point is that the two seats are different models. To see it work without either, run `python -m parallax demo --stub`, which uses scripted seats and spends nothing. The whole test suite runs the same way.

## Why not two copies of the same model?

Two copies tend to misread a task in the same place, so their agreement is weak evidence. Two different models make less correlated mistakes. See [Concepts](concepts.md).

## Does Parallax itself use a model?

No. The conductor is ordinary Python, standard library only. It launches the two CLIs, does all the git work and runs every check. Coordination spends no tokens.

## What does a run cost?

Whatever the two CLIs spend on your subscriptions. In the two real runs recorded on 2026-11-23, one small task used between roughly 180,000 and 950,000 input tokens per seat, much of it cached. The figures are in [Field notes](field-notes.md).

## How often will it interrupt me?

Only when the two seats still disagree after one settlement exchange, or when a failed crossing leaves a dispute the seats cannot settle between themselves within two repair rounds. A ruling scoped to the project becomes a precedent, so the same question is not asked again while its conditions hold. See [Rulings and precedents](rulings.md).

## Do I have to sit and wait for a card?

No. The conductor never waits at a prompt. When it needs a ruling it writes the card to disk, prints it and exits with code 2. Answer with `parallax rule` whenever you like, then run the same task again.

## What if I stop it halfway, or it crashes?

Run the same command again. Every step records its completion, and `run` works out the current step from the record. An attempt that started and never finished is discarded and rerun. See [The life of a task](life-of-a-task.md).

## Can the challenger really not see the builder's code?

It is prevented where each CLI can prevent it, and audited everywhere. Each seat works in its own clone inside a folder private to your account; Codex is sandboxed and Claude has file tools restricted to its folder and no shell. The audit of each seat's event stream is best effort, and the documentation says so: seats are treated as fallible, not hostile. See [Keeping the blind](blind.md).

## Does it merge without asking me?

Yes, once the gates pass: probes pass on the change, every mutant is caught, and the project's check command passes again on current main. Main never receives a failing check. The landing commit carries the receipt. See [Receipts and the ledger](receipts.md).

## What does it need from my project?

A git repository, one `parallax.toml` naming your check command and the paths each role may write, and tasks written as short spec files. See [parallax.toml](configuration.md) and [Commands](cli.md).

## What about a change that is not a behavior change?

Start the task file with `Kind: chore`. One seat builds it, there is no challenger, and the receipt's verdict is `solo` so nobody mistakes it for pair-verified work.

## Does it run on macOS or Linux?

It targets Windows 11 and has not been tested elsewhere. How each seat is confined depends on Windows folder permissions and on how each CLI's sandbox behaves there.

## Can it run several tasks at once?

Not yet. v0 runs one task at a time with two seats. Several tasks in flight with crossed roles is first on the list after v0.

## Is anything known to be wrong?

Two gaps are open and documented. The committed ledger records each seat clone's absolute path, which includes your account name; see [Receipts and the ledger](receipts.md). And `exclusive` scope paths are not removed from the challenger's scope; see [parallax.toml](configuration.md). The design document lists every place the code differs from the original design.

## Why is it called Parallax?

Parallax is how astronomers measure distance: look at one object from two positions and measure how far it appears to shift. Neither position alone can tell you. Here the two positions are two models, and the object is the change.

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
- [Field notes](field-notes.md)
