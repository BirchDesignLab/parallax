# Parallax

Claude Code and Codex each wrote a proposal without seeing the other's, then each reviewed the other's, and they arrived at the same core independently. The core: two different models make less correlated mistakes than two copies of one model, so each task is split into two sides. One agent builds it while the other, without seeing the code, writes the checks that will judge it. When they agree, that is evidence; when they disagree, that is either a bug or a hole in the spec, and it is the only thing that goes to the human.

Parallax is the plain-Python conductor that runs this. It contains no model: it drives `claude -p` and `codex exec` as "seats", does all the git work, runs every check, and lands the result on `main` with a receipt.

Design: `docs/superpowers/specs/2026-11-16-parallax-design.md`.

## Requirements

- Windows 11 (the target; nothing here is tested elsewhere)
- Python 3.12, standard library only
- git, with a user name and email set
- Claude Code and Codex CLIs, both signed in (only for real runs; the stub demo needs neither)

## Install

From this checkout, install it into the Python you will run it with:

```powershell
python -m pip install -e .
```

That gives `python -m parallax` (and a `parallax` command) from any folder. Without installing, `python -m parallax` works only from this checkout, or with `PYTHONPATH` set to it.

## Try it without spending anything

```powershell
python -m parallax demo --stub
```

This builds a throwaway git project in a new folder under the state home, `~/.parallax/demos/` (printed first), with one deliberately underspecified task: `clamp(x, lo, hi)`, which says nothing about `lo > hi`. Scripted seats disagree about it, so the run stops with a ruling card and exit code 2. The card shows both answers, each seat's reason, and a concrete call on which the answers differ. Rule on it with the command the run prints (`a` or `b`; the scripted seats cannot carry out an `other` ruling), then run the demo again on the same folder:

```powershell
python -m parallax rule D-clamp-001-1 a --repo "<printed folder>"
python -m parallax demo --dir "<printed folder>" --stub
```

The second run lands the change on `main` and prints the receipt. Use `--dir PATH` to choose the folder yourself. Without `--stub`, the demo uses the real CLIs and spends tokens on both subscriptions.

## Use it on a project

From the project's folder, or from anywhere with `--repo PATH` on each command (a relative task path is then read from the project, not the current folder):

1. `python -m parallax init` writes `parallax.toml` and `.parallax/`. Edit `parallax.toml`: the `check` and `lint` commands, the paths each role may write (`[scopes]`), and the two seats. Commit these files.
2. Write the task as a short spec in `tasks/<id>.md`. The id is the file name without `.md`. A task is a behavior change unless its first line is `Kind: chore`.
3. `python -m parallax run tasks/<id>.md` runs or resumes the task until it lands, needs a ruling, or is blocked. Exit codes: 0 landed, 2 needs a ruling, 3 parked, blocked or dropped, 1 error.
4. When it needs a ruling it prints one card per open question, each ending with the command that answers it. `python -m parallax rule <dispute> a|b|other|drop` records your answer; a card accepts only the choices it lists. `other` takes your own answer in `--note`. `--scope task|project` overrides whether the answer binds later tasks, `--while` states the condition under which it holds, and `--limitation` accepts the change with a stated limitation, which is written on the receipt. Each card takes one ruling. Then run the same task again.
5. `python -m parallax status` lists tasks and what each waits on.

Project-scoped rulings are kept as precedents in `.parallax/PRECEDENTS.md` and included in later briefs, so a settled question is not asked again while its conditions hold. A ruling on a behavior question is project-scoped by default; a ruling that chooses an interface, or replaces several provisions at once, applies to its task only.

## How a disagreement reaches you

Each seat first writes its reading of the task alone: the interface it expects and an answer to every open choice. Then each reviews the other's reading. Where a seat objects, it must give a concrete case and say what each answer does there. What happens next depends on how much they disagree:

- **Nothing in dispute:** the contract is frozen and the build starts. You are not asked.
- **One objection:** it becomes one card, with both answers, both reasons and the case that tells them apart.
- **Several objections, or a seat says two provisions conflict:** these are often one question asked several times, so the seats get one more exchange before you do. The builder proposes a single account of the whole task: what both already agree on, and each remaining choice with its two answers. The challenger reviews exactly that proposal. Where both sign the same answer it stands, and where both would accept either, the builder's preference stands. Only a choice where each holds a different answer becomes a card, and one card can cover several provisions.
- **A seat refuses the proposal:** if both agree on which provisions a ruling would have to replace, you get one card that asks for the replacement text (`other`) or lets you `drop` the task. If they cannot agree on that boundary, the task is blocked and `status` says why; no card is offered.

The settlement is recorded once, before any card can be ruled, and every later step reads that record. Nothing is built until every card is ruled and the contract is frozen from the result.

A task that was opened by an earlier version of Parallax finishes under the rules it was opened with: one card per objection.

## What a receipt means

A landing commit carries trailers: `Parallax-Task`, `Parallax-Contract`, `Built-by`, `Challenged-by`, `Checks`, `Verdict`, and `Limitation` when there is one. A chore's receipt has no contract and no challenger, so it omits `Parallax-Contract` and `Challenged-by`. The verdict is one of:

- `consensus`: clean at the first crossing.
- `resolved`: the seats settled a dispute between themselves.
- `ruled`: a human ruling was needed.
- `limited`: accepted with a stated limitation, which is written on the receipt.
- `solo`: not pair-verified (a chore, built by one seat).

Main never receives a failing check.

Every landed seat change matched its accepted inventory; relevance is not independently reviewed.

## How the blind is kept

The blind is enforced where each CLI can enforce it and audited everywhere. Seats are treated as fallible, not hostile.

- **Placement:** each seat works in its own clone of the project, with no git link to the other's, under a random name in the state folder (`PARALLAX_HOME`, else `~/.parallax`), outside the repo.
- **Confinement:** each task's folder in the state folder is made private to the human's account, SYSTEM and Administrators; Codex runs in its `workspace-write` sandbox and Claude gets file tools restricted to its own folder and no shell.
- **Seal:** readings and attempts are hashed into the ledger before the reveal, so nothing can be adjusted afterwards.
- **Audit:** after each call the conductor scans the seat's event stream for any path belonging to the other seat or to the state folder; this is best effort.
- **Voiding:** a hit voids the attempt, together with its session and clone, and the rerun is a new session in a new clone, starting from the contract alone.

## What is and is not verified

The spec's section "Verified and not yet verified" records what the real CLIs did on this machine, with the dates. `scripts/probes/seat_smoke.py` reproduces it and exits non-zero if any expectation fails; rerun it, and `scripts/probes/job_object_seats.py`, when either CLI updates. The test suite runs on scripted stub seats and spends nothing:

```powershell
python -m unittest discover -s tests -t . -v
```

Only `tests/test_live_seats.py` uses the real CLIs, and only when `PARALLAX_LIVE=1`. The stub suite proves the conductor's branches (disagreement, each settlement path, ruling, failed crossing, surviving mutant, repair, voided attempt, and resuming after an interruption at each step). That the real CLIs can carry one task to a receipt is shown by running `python -m parallax demo`, which reports which path it took. The first real run, on 2026-11-17, took the dispute path: the two models agreed that `lo > hi` raises `ValueError` but split on four other reading questions (inclusive bounds, `lo == hi`, accepted types, NaN bounds). After four rulings it landed at the first crossing with verdict `ruled`: 90 probes passed and 3 of 3 mutants were caught.

That run asked four separate questions that were largely one question about the bounds, which is what the settlement described above was built to fix. The settlement has so far run only on stub seats, including acceptance cases modeled on the disagreements of the 2026-11-17 and 2026-11-19 real runs. No real run has used it yet.
