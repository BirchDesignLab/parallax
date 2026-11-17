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

This builds a throwaway git project in a new folder under the state home, `~/.parallax/demos/` (printed first), with one deliberately underspecified task: `clamp(x, lo, hi)`, which says nothing about `lo > hi`. Scripted seats disagree about it, so the run stops with a ruling card and exit code 2. Rule on it with the command the run prints, then run the demo again on the same folder:

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
4. When it needs a ruling it prints a card. `python -m parallax rule <dispute> a|b|other|drop` records your answer (`other` takes `--note`; see `--scope`, `--while` and `--limitation`), then run the same task again.
5. `python -m parallax status` lists tasks and what each waits on.

Rulings are kept as precedents in `.parallax/PRECEDENTS.md` and included in later briefs, so a settled question is not asked again while its conditions hold.

## What a receipt means

A landing commit carries trailers: `Parallax-Task`, `Parallax-Contract`, `Built-by`, `Challenged-by`, `Checks`, `Verdict`, and `Limitation` when there is one. A chore's receipt has no contract and no challenger, so it omits `Parallax-Contract` and `Challenged-by`. The verdict is one of:

- `consensus`: clean at the first crossing.
- `resolved`: the seats settled a dispute between themselves.
- `ruled`: a human ruling was needed.
- `limited`: accepted with a stated limitation, which is written on the receipt.
- `solo`: not pair-verified (a chore, built by one seat).

Main never receives a failing check.

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

Only `tests/test_live_seats.py` uses the real CLIs, and only when `PARALLAX_LIVE=1`. The stub suite proves the conductor's branches (disagreement, ruling, failed crossing, surviving mutant, repair, voided attempt, resume). That the real CLIs can carry one task to a receipt is shown by running `python -m parallax demo`, which reports which path it took; that end-to-end run is pending.
