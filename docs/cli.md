# Command line reference

Every `parallax` command, its arguments and flags, what it prints, and the exit codes it returns. The commands are `init`, `run`, `rule`, `status` and `demo`.

Run them as `python -m parallax <command>`. After `python -m pip install -e .` the same commands are also available as `parallax <command>`.

```powershell
python -m parallax --help
```

```text
usage: parallax [-h] {init,run,rule,status,demo} ...

Pair two agent CLIs on one task.
```

## Conventions

### Exit codes

`run` and `demo` end with the exit code of the task's outcome. The other commands return 0 on success and 1 on error.

| Code | Meaning | Printed status |
|---|---|---|
| 0 | The task landed on main. `init`, `rule` and `status` also return 0 on success. | `landed` |
| 1 | Error: a missing or invalid `parallax.toml`, a git error, a rejected argument value, or an unknown dispute. The message goes to stderr as `parallax: <message>`. | none |
| 2 | The task needs a ruling. One card is printed per open question. | `needs_ruling` |
| 3 | The task is parked, blocked or dropped. The detail on the last line says why. | `parked`, `blocked`, `dropped` |

argparse also exits with 2 on a usage error such as an unknown flag or a `rule` choice outside `a`, `b`, `other` and `drop`. That case prints a usage message to stderr and no task line, which tells it apart from a task that needs a ruling.

### `--repo`

`init`, `run`, `rule` and `status` take `--repo PATH`, the project root. The default is the current directory. The path is resolved to an absolute path before use, and the project's `parallax.toml` is read from it.

With `run`, a relative task path is read from the project, not from the current directory. This works from any folder:

```powershell
python -m parallax run tasks\clamp-001.md --repo C:\work\billing
```

An absolute task path is used as given.

### Task ids

A task's id is the task file's name without its last extension. `tasks\clamp-001.md` is task `clamp-001`, and `tasks\parser.v2.md` is task `parser.v2`. An id may use letters, digits, `.`, `_` and `-`, and must start with a letter or digit. Any other name is an error.

The id is used in dispute ids (`D-clamp-001-1`), in the receipt (`Parallax-Task: clamp-001`), and in the ledger.

### `Kind: chore`

A task is a behavior change unless the first non-blank line of its file is `Kind: chore` (case-insensitive). A behavior task goes through the full pair: readings, reveal, contract, build and probes, crossing, mutants. A chore is built by one seat, checked once, and lands with verdict `solo`. Use it for changes that do not alter behavior, such as docs and renames.

The task title, used in the commit subject, is the first remaining non-blank line with leading `#` characters and spaces removed. For a chore, the `Kind: chore` line is skipped first.

```text
Kind: chore
# Rename the retry helper

Rename `retry_once` to `retry_with_backoff` everywhere. No behavior change.
```

### `PARALLAX_HOME`

Parallax keeps seat clones, scratch clones, per-task folders and seat artifacts in a state home outside the project. The default is `~\.parallax`. Set the `PARALLAX_HOME` environment variable to use another folder:

```powershell
$env:PARALLAX_HOME = "D:\parallax-state"
python -m parallax run tasks\clamp-001.md
```

The variable is read when a command starts, by every command that uses the state home (`run`, `rule`, `status`, `demo`). Inside it, each project gets a subfolder named by a 12-character hash of its resolved path (lowercased, so case does not matter), and each task a folder under that. `demo` puts new projects in `demos\` under the state home.

Do not point it into `%LOCALAPPDATA%` or `%APPDATA%`. A process started from a packaged app gets new folders there redirected, and Codex's sandbox then fails every command.

The project's own `.parallax\` folder is separate. It holds the ledger and precedents, which are committed, and `run\`, which git ignores. See [configuration.md](configuration.md#files-parallax-keeps).

## init

Writes `parallax.toml` and the `.parallax\` folder into a project.

```text
usage: parallax init [-h] [--repo PATH]
```

| Argument | Meaning |
|---|---|
| `--repo PATH` | Project root. Default: current directory. |

`init` creates:

- `parallax.toml`, a sample configuration. See [configuration.md](configuration.md).
- `.parallax\.gitignore`, containing `run/`.
- `.parallax\ledger.jsonl`, empty. An existing ledger is left alone.

It does not run git. Edit `parallax.toml`, then commit these files.

`init` fails with exit code 1 if the folder does not exist or `parallax.toml` already exists there. It never overwrites an existing config.

```powershell
python -m parallax init --repo C:\work\billing
```

```text
wrote parallax.toml and .parallax/ in billing
edit parallax.toml, commit these files, then: parallax run TASK_FILE
```

## run

Runs a task, or resumes it where it stopped.

```text
usage: parallax run [-h] [--repo PATH] [--builder SEAT] TASK_FILE
```

| Argument | Meaning |
|---|---|
| `TASK_FILE` | Path to the task spec. A relative path is read from the project root. The file name gives the task id. |
| `--repo PATH` | Project root. Default: current directory. |
| `--builder SEAT` | Name of the seat that builds, as named in `[seats.<name>]` in `parallax.toml`. The other seat challenges. |

`run` reads `parallax.toml`, builds the two seats, and carries the task as far as it can go without a human: sealed readings, reveal, settlement, contract, build and probes in parallel, crossing, mutants, repairs, and landing on main with a receipt. See [life-of-a-task.md](life-of-a-task.md) for the steps.

It stops when the task lands, when it needs a ruling, or when it is blocked or parked. It never waits at a prompt. To resume, answer any cards with `rule`, fix whatever blocked the task, and run the same command again. Every step records its completion in the journal, so a resumed run skips what is done. An attempt that started but did not finish is discarded and rerun.

Choosing the builder:

- By default the builder alternates from task to task. The first task is built by the first seat listed in `parallax.toml`, the second by the other, and so on. The count is the number of other tasks already opened.
- `--builder` overrides this when the task is first opened. A task that is already open keeps the builder recorded at its opening, and `--builder` on a resumed run has no effect. An unknown seat name is an error (exit 1).

One run at a time per project. A second `run` while another is active ends as blocked (exit 3) with `another parallax run is active (pid N)`. A lock left by a process that no longer exists is removed.

Running a task that already landed is not an error: it prints `<task> has already landed` and exits 0. A task that was dropped prints `<task> was already dropped` and exits 3.

### What run prints

Progress lines, one per step, each starting with the task id. Then, if the task needs rulings, one card per open question, each ending with the `rule` command that answers it. Last, one status line:

```text
<task>: <status>  <detail>
```

The detail is omitted when there is none. The status is one of `landed`, `needs_ruling`, `parked`, `blocked` or `dropped`.

Cards are also saved as files under `.parallax\run\<task>\cards\`. Blocked and parked details name the cause: a seat that reported itself blocked, an attempt rejected twice, a check that failed on top of main, main moving while the task landed, or uncommitted changes on a checked-out main (the result is then left on the branch `parallax/ready/<task>`).

### Example: a task that lands

The second run of the stub demo, after its one card was ruled (2026-11-23). The stub seats spend nothing, so the token counts are zero.

```text
clamp-001: contract v1 frozen
clamp-001: codex's build 1 finished
clamp-001: claude's probe 1 finished
clamp-001: crossing 1: check passed, 3 of 3 mutants caught
clamp-001: landed 1a0a4035f05a; codex 0 in / 0 out, claude 0 in / 0 out
clamp-001: landed  landed 1a0a4035f05a
```

The exit code is 0. The `landed` progress line reports what each seat spent on the task.

### Example: a task that needs a ruling

```powershell
python -m parallax run tasks\clamp-001.md --repo C:\work\billing
echo $LASTEXITCODE
```

The run prints its progress lines, then a card for each open question, then the status line. A card names the question, shows both answers as `a)` and `b)`, shows the evidence, and ends with the command that answers it. From the stub demo:

```text
clamp-001: opened (behavior); builder codex, challenger claude
clamp-001: claude's reading sealed
clamp-001: codex's reading sealed
clamp-001: claude's reveal done
clamp-001: codex's reveal done
clamp-001: settlement published (direct)
clamp-001: needs a ruling on D-clamp-001-1

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

clamp-001: needs_ruling  needs a ruling on D-clamp-001-1
```

```text
2
```

Rule on the card with [`rule`](#rule), then run the task again.

## rule

Records a human ruling on a dispute card.

```text
usage: parallax rule [-h] [--repo PATH] [--note TEXT] [--scope {task,project}]
                     [--while TEXT] [--limitation TEXT]
                     DISPUTE {a,b,other,drop}
```

| Argument | Meaning |
|---|---|
| `DISPUTE` | The dispute id printed on the card, for example `D-clamp-001-1`. |
| `{a,b,other,drop}` | The choice. See below. |
| `--repo PATH` | Project root. Default: current directory. |
| `--note TEXT` | Your own words. Required with `other`. |
| `--scope {task,project}` | Whether the ruling binds only this task or later tasks too. Overrides the default for the card. |
| `--while TEXT` | The condition under which the ruling holds, for example `while there is a single user`. |
| `--limitation TEXT` | Accept the change with a stated limitation. The text is written on the receipt. |

`rule` only records the answer. It needs no seats and spends no tokens. It takes the project's run lock, so it fails with exit 1 while a `run` is active.

### Choices

| Choice | Meaning |
|---|---|
| `a` | Take the card's `a)` answer. |
| `b` | Take the card's `b)` answer. |
| `other` | Supply a different answer in `--note`. |
| `drop` | Drop the task. Its record lands on main; no code does. |

A card accepts only the choices it lists, and each card takes one ruling. Anything else is an error (exit 1) that names the allowed choices.

| Card | Accepts | `--note` |
|---|---|---|
| Reading (a policy question) | `a`, `b`, `other` | Required with `other`: the policy. |
| Interface | `a`, `b`, `other` | Required with `other`: the complete interface. |
| Combined (interface and policy together) | `a`, `b`, `other` | Required with `other`: one JSON object with the string fields `interface` and `policy`, both nonblank. |
| Refusal (the seats refused the proposed settlement) | `other`, `drop` | Required with `other`: the replacement text. |
| Check (the check still fails) | `a`, `b` | Optional. Replaces the default text recorded for the ruling. |
| Mutant (a mutant survived) | `a`, `b` | Optional. With `b`, which waives the mutant, it is appended to the waiver's limitation. |
| Unresolved (repair rounds used up) | `a`, `b`, `drop` | Optional. Replaces the default text. |

On a reading, interface, combined or refusal card of a settlement, a nonblank `--note` with `a` or `b` is rejected: the card's own column is the ruling. Choosing `b` on a mutant card waives that mutant and writes `mutant <id> waived` on the receipt as a limitation.

### Scope, `--while` and `--limitation`

A ruling is either task-scoped or project-scoped. A project-scoped ruling becomes a precedent in `.parallax\PRECEDENTS.md` and is included in later briefs, so the question is not asked again while its condition holds. See [rulings.md](rulings.md).

Defaults when `--scope` is omitted:

| Ruling | Default scope |
|---|---|
| Reading card | project |
| Check card | project |
| Interface, combined and refusal cards | task |
| Mutant and unresolved cards | task |
| `drop` | task |

Mutant, unresolved and `drop` rulings are always task-scoped; `--scope` does not change them.

`--while` is stored with the ruling and shown in the precedent as `(while: ...)`. It has an effect only on a project-scoped ruling, since only those become precedents.

`--limitation` is stored with the ruling. The task then lands with verdict `limited`, and the text appears as a `Limitation:` trailer on the commit. See [receipts.md](receipts.md).

### Output

```text
recorded <dispute>: <choice>
continue with: parallax run TASK_FILE
```

Exit code 0. It fails with 1 for an unknown dispute, a dispute that is already ruled, a choice the card does not allow, or `other` without a note.

### Example

Rule on the card above in favor of the builder's answer, and keep it as a project precedent for as long as the condition holds:

```powershell
python -m parallax rule D-clamp-001-1 a --while "callers pass ints" --repo C:\work\billing
```

```text
recorded D-clamp-001-1: a
continue with: parallax run TASK_FILE
```

Supply your own answer instead:

```powershell
python -m parallax rule D-clamp-001-1 other --note "Return lo when lo > hi." --repo C:\work\billing
```

Accept a change with a stated limitation:

```powershell
python -m parallax rule D-clamp-001-2 b --limitation "NaN bounds are not handled" --repo C:\work\billing
```

Then run the task again:

```powershell
python -m parallax run tasks\clamp-001.md --repo C:\work\billing
```

## status

Lists tasks and what each one waits on.

```text
usage: parallax status [-h] [--repo PATH]
```

| Argument | Meaning |
|---|---|
| `--repo PATH` | Project root. Default: current directory. |

`status` reads the ledger on main and the journal, writes nothing, and always returns 0 on success. It prints one line per task, in the order tasks were first recorded. Fields are separated by two spaces:

```text
<task>  <status>  <pending dispute ids>  <detail>
```

The pending ids appear only when there are any, and the detail only when there is one.

| Status | Meaning |
|---|---|
| `landed` | On main. |
| `dropped` | Dropped by a ruling. |
| `needs_ruling` | One or more cards are open; their ids follow. |
| `in_progress` | Started, with nothing waiting on you. |
| `parked` | Finished but not on main; the result is on a `parallax/ready/<task>` branch. |
| `blocked` | Cannot continue. The detail says why. |

```powershell
python -m parallax status --repo C:\work\billing
```

```text
clamp-001  landed
clamp-002  needs_ruling  D-clamp-002-1 D-clamp-002-2
retry-001  blocked  the confirmed settlement is blocked: ...
```

With no tasks, `status` prints nothing.

## demo

Builds a throwaway project and runs the v0 demonstration on it.

```text
usage: parallax demo [-h] [--dir PATH] [--stub]
```

| Argument | Meaning |
|---|---|
| `--dir PATH` | Project folder. Default: a new folder `demos\clamp-<8 hex digits>` under the state home. |
| `--stub` | Use scripted seats. Spends nothing and needs neither CLI. |

`demo` takes no `--repo`. If the folder has no `parallax.toml`, `demo` creates a git project there on branch `main`, with one task, `tasks\clamp-001.md`: "Add clamp(x, lo, hi) to clamplib: returns x limited to the range lo..hi." The task says nothing about `lo > hi`, so the seats disagree about it. A new `--dir` must not exist or must be empty. If the folder already has a `parallax.toml`, `demo` reuses it, which is how you resume.

It prints `demo project: <folder>` first, then runs the task exactly as `run` does, with the same progress lines, cards and final status line, and the same exit codes.

- On `landed`, it prints the landing commit's message, the receipt.
- On `needs_ruling`, it prints the `rule` command for each card, with `--repo` filled in, and the `demo` command to run afterward.
- On `blocked` or `parked`, it prints the `demo` command to run after fixing the cause.

Without `--stub`, the demo uses the real CLIs and spends tokens on both subscriptions. With `--stub`, the scripted seats can carry out ruling `a` or `b` but not `other`. Running `--stub` against a folder made for the real seats is an error (exit 1).

```powershell
python -m parallax demo --stub
```

The run stops with exit code 2 and prints the command to rule with:

```text
rule with: python -m parallax rule D-clamp-001-1 a --repo "<printed folder>"   (or b)
then run: python -m parallax demo --dir "<printed folder>" --stub
```

```powershell
python -m parallax rule D-clamp-001-1 a --repo "<printed folder>"
python -m parallax demo --dir "<printed folder>" --stub
```

The second run lands the change and prints the receipt under `Receipt (the landing commit's message):`.

## See also

- [Documentation index](README.md)
- [Concepts](concepts.md)
- [The life of a task](life-of-a-task.md)
- [Rulings and precedents](rulings.md)
- [Receipts and the ledger](receipts.md)
- [Keeping the blind](blind.md)
- [parallax.toml](configuration.md)
- [Architecture](architecture.md)
- [Field notes](field-notes.md)
- [FAQ](faq.md)
