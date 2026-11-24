# Configuration reference

Every table and key in `parallax.toml` that Parallax reads, with its type, default and meaning, followed by the seats, the write scopes, and a complete annotated example.

`parallax.toml` sits at the project root. `parallax init` writes a sample (see [cli.md](cli.md#init)). The file is parsed with Python's `tomllib`, so it must be valid TOML in UTF-8. `run`, `rule` and `status` read it, and a missing or invalid file is a `ConfigError`: the message names the file or the key, and the command exits with code 1.

## Overview

| Table | Required | Purpose |
|---|---|---|
| `[project]` | yes | The check and lint commands, the main branch, timeouts. |
| `[scopes]` | yes | Which paths each role may write. |
| `[policy]` | no | Merge and pairing policy, repair rounds, mutant count. |
| `[seats.<name>]` | yes, exactly two | The two agent CLIs: adapter, model, effort. |

A key Parallax does not know is an error that names it, for example `unknown key project.lnit`, so a misspelled key cannot fall back to its default unnoticed.

## [project]

| Key | Type | Default | Meaning |
|---|---|---|---|
| `check` | string | none (required) | The command that decides whether a tree is good. Exit code 0 passes, anything else fails. |
| `lint` | string | `""` | A quick command run on a seat's clone after each attempt. Empty means no lint. |
| `main` | string | `"main"` | The branch results land on. |
| `check_timeout` | integer, seconds | `600` | Time limit for each run of `check` or `lint`. |
| `seat_timeout` | integer, seconds | `1800` | Time limit for each seat call. |
| `count_pattern` | string, regex | `Ran (\d+) tests?` | How the probe count is read from the check's output. |

Integers must be non-negative. A boolean is rejected.

### check

`check` is run through the shell, with the working directory set to a clone of the tree being judged and `PYTHONDONTWRITEBYTECODE=1` in its environment. Its output (stdout and stderr together) is kept in `.parallax\run\<task>\crossings\<n>\check.txt`. A timeout counts as failure, and the whole process tree is killed.

Parallax runs it at these points:

- On the builder's change with the challenger's probes applied (the crossing).
- Once more for each mutant, with that mutant's files swapped in. A mutant is caught when the check fails and survives when it passes.
- On the landing tree, current main plus the task's changes, immediately before main moves.
- For a chore, once on the builder's change.

The check must therefore run the probes. Probe files are placed where the challenger's scope says (for example `tests\`), and the check has to find them there.

### lint

`lint` runs on a seat's clone after each attempt, after the scope check. A failure goes back to that seat as a rejection with the tail of the output. A second rejection of the same attempt blocks the task. Anything lint writes is discarded: the clone is reset to the snapshot afterwards. Lint uses `check_timeout`.

### count_pattern

The first capture group is read as an integer, and the last match in the output wins. The result is the number in the receipt's `Checks` trailer, for example `84 probes passed`. If the pattern does not match, or the group is not an integer, the trailer says `check passed` with no count. The default matches `unittest`'s summary line. For a runner with a different summary, supply a pattern with one group around the number, for example `(\d+) passed` for output that ends `84 passed in 3.2s`.

### TOML quoting on Windows

Commands with backslashes or quotes read best as TOML literal strings, in single quotes, which keep every character as written:

```toml
check = '"C:\Python312\python.exe" -m unittest discover -s tests -t .'
```

## [scopes]

The paths each role may write. Every changed path is checked against the writing seat's patterns after each attempt. A path outside them rejects the attempt. See [blind.md](blind.md) for how this fits the rest of the confinement.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `builder` | list of strings | none (required) | Paths the builder may write. |
| `challenger` | list of strings | none (required) | Paths the challenger may write. |
| `exclusive` | list of strings | `[]` | Paths both roles might need, such as manifests and lockfiles. They belong to the builder: added to its paths and closed to the challenger. |

Each entry must be a nonempty string. The effective builder scope is `builder` followed by `exclusive`. The challenger's scope is `challenger`, minus anything `exclusive` matches: a challenger attempt that changes such a path is rejected with `you changed files reserved for the builder`, even where a challenger pattern also matches it. Parallax does not otherwise check that the `builder` and `challenger` lists are disjoint, so keep those two apart yourself.

The seats only edit files. The conductor does all git work and makes the commits.

### Pattern syntax

Patterns match the whole repository-relative path, with forward slashes, case-sensitively.

| Pattern | Matches |
|---|---|
| `src/**` | Any file under `src\`, at any depth. |
| `tests/**` | Any file under `tests\`, at any depth. |
| `pyproject.toml` | That one file at the project root. |
| `*.md` | Markdown files at the project root only. `*` does not cross `/`. |
| `**/*.md` | Markdown files at any depth, including the root. |
| `docs/*.md` | Markdown files directly in `docs\`. |

`**` matches any run of characters including `/`, and `**/` matches zero or more directories. `*` matches any run of characters except `/`. Every other character is literal: `?` and `[...]` have no special meaning.

### Where scopes apply

- The builder's attempt, and the files named in its mutants. Each mutant file must be in the builder's scope.
- The challenger's attempt.
- A chore's builder, which is held to the scope `**`: any path. Lint and the check still apply.

## [policy]

The whole table is optional.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `merge` | string | `"auto"` | Only `"auto"` is accepted: main moves forward automatically once the gates pass. Any other value is an error. |
| `pair` | string | `"behavior"` | Only `"behavior"` is accepted: every behavior change is pair-verified, and a `Kind: chore` task is built by one seat. Any other value is an error. |
| `max_repair_rounds` | integer | `2` | Repair rounds allowed after a failed crossing before the task escalates to you. |
| `mutants` | integer | `3` | How many valid mutants the builder must supply. |

`max_repair_rounds`: when the number of failed crossings reaches one more than this value, plus one for each earlier ruling on an unresolved card, Parallax opens an unresolved card instead of repairing again. With the default of 2, the third failed crossing opens it.

`mutants`: a mutant is a deliberately broken copy of the change. The builder's work is rejected if fewer than this many mutants are valid: a plain id, files inside the builder's scope, files present in the mutant's folder, and content that differs from the real code. Every mutant must fail the check at the crossing. With `0`, the builder is not asked for mutants, and the `Checks` trailer carries only the probe count.

## [seats]

A seat is an agent CLI Parallax can launch. `[seats]` must contain exactly two tables, one per seat. Any other count is an error. In v0 more than two seats are not supported.

```toml
[seats.codex]
model  = "gpt-6.2-astra"
effort = "xhigh"

[seats.claude]
model  = "fable"
effort = "high"
```

| Key | Type | Default | Meaning |
|---|---|---|---|
| `adapter` | string | the seat's table name | Which adapter drives the seat: `claude` or `codex`. |
| `model` | string | none (required) | Model name, passed to the CLI as written. |
| `effort` | string | none (required) | Reasoning effort, passed to the CLI as written. |

The table name (`codex` and `claude` above) is the seat's name. It is what `run --builder` takes, and it appears in the ledger and the receipt. Because `adapter` defaults to the name, a seat named `claude` uses the `claude` adapter without saying so.

Parallax does not validate `model` or `effort`. The CLI accepts or rejects them. Model and effort are set explicitly on every launch and recorded in the receipt, as in `Built-by: codex gpt-6.2-astra/xhigh`.

The order of the two tables matters in one place: with no `--builder`, the first task is built by the first seat listed, and the builder then alternates.

### Adapters

| Adapter | Drives | Notes |
|---|---|---|
| `claude` | `claude -p` (Claude Code) | Found on `PATH`. |
| `codex` | `codex exec` (Codex CLI) | Found on `PATH`. |
| `stub` | Scripted replies | Not available from `parallax.toml`. See below. |

What each adapter passes, from the code:

| | `claude` | `codex` |
|---|---|---|
| Model and effort | `--model <model> --effort <effort>` | `-m <model> -c model_reasoning_effort="<effort>"` |
| Personal config | `--safe-mode` | `--ignore-user-config` |
| Writing call | tools `Read,Write,Edit,Glob,Grep` | `--sandbox workspace-write` |
| Read-only call | tools `Read,Glob,Grep` | `--sandbox read-only` |
| Confinement | `--restricted`, no shell tool, permission prompts off | the sandbox above, working directory set to the seat's own clone |
| Output | `--output-format stream-json`, validated against a JSON schema | `--json --output-schema`, validated against a JSON schema |

The Codex adapter also re-supplies the `[windows] sandbox` setting from `config.toml` in `CODEX_HOME` (default `~\.codex`), since `--ignore-user-config` would otherwise drop it. Both adapters launch the CLI with other agents' environment variables removed.

An unknown `adapter` is an error that names the seat: `seats.<name>.adapter: unknown adapter '<value>'`.

### The stub adapter

`stub` replays scripted outputs, so a whole task can be run without spending a token. The test suite uses it, and so does `parallax demo --stub`, which registers it for the length of the demo. It is not a general option for `parallax.toml`: with `adapter = "stub"`, `parallax run` stops with the unknown-adapter error, because nothing registers the adapter outside the demo and the tests.

## Files Parallax keeps

Inside the project:

| Path | Committed | Contents |
|---|---|---|
| `parallax.toml` | yes | This file. |
| `.parallax\ledger.jsonl` | yes | The record of decisions: readings, contracts, attempts, crossings, disputes, rulings, receipts. Landing moves a task's events here in the same commit as the code. |
| `.parallax\PRECEDENTS.md` | yes | Project-scoped rulings, included in later briefs. |
| `.parallax\contracts\<task>.md` | yes | The frozen contract of each landed task. |
| `.parallax\.gitignore` | yes | Contains `run/`. |
| `.parallax\run\` | no | The run lock, the journal of tasks in flight, pending cards, check output. |

Outside the project, seat clones and artifacts live in the state home: `PARALLAX_HOME`, or `~\.parallax` when it is unset. See [cli.md](cli.md#parallax_home).

## Complete example

```toml
# parallax.toml, at the project root.

[project]
# Decides whether a tree is good. Runs through the shell in a clone of the tree.
# Exit code 0 passes. It must run the challenger's probes (here, tests\).
check = "python -m unittest discover -s tests"

# Quick sanity check run on a seat's clone after each attempt. Optional.
lint = "python -m compileall -q ."

# The branch results land on. Default: "main".
main = "main"

# Seconds allowed for one run of check or lint. Default: 600.
check_timeout = 600

# Seconds allowed for one seat call. Default: 1800.
seat_timeout = 1800

# How the probe count in the receipt is read from the check's output.
# One capture group around the number; the last match wins. This is the default.
count_pattern = 'Ran (\d+) tests?'

[scopes]
# Paths the builder may write.
builder = ["src/**"]

# Paths the challenger may write. The probes go here.
challenger = ["tests/**"]

# Files either role might need. Added to the builder's paths.
exclusive = ["pyproject.toml", "uv.lock"]

[policy]
# Only "auto" is accepted in v0.
merge = "auto"

# Only "behavior" is accepted in v0.
pair = "behavior"

# Repair rounds after a failed crossing before the task escalates to you.
max_repair_rounds = 2

# Mutants the builder must supply for every behavior task.
mutants = 3

# Exactly two seats. The first one listed builds the first task.
[seats.codex]
model  = "gpt-6.2-astra"
effort = "xhigh"

[seats.claude]
model  = "fable"
effort = "high"
```

With this file, a task `tasks\clamp-001.md` is run with:

```powershell
python -m parallax run tasks\clamp-001.md
```

## Not implemented

- `merge` other than `"auto"`, and `pair` other than `"behavior"`. Both keys are read, and any other value is rejected.
- More or fewer than two seats.
- The `stub` adapter in a project's own `parallax.toml`. It exists for the demo and the tests only.

## See also

- [Documentation index](README.md)
- [Concepts](concepts.md)
- [The life of a task](life-of-a-task.md)
- [Rulings and precedents](rulings.md)
- [Receipts and the ledger](receipts.md)
- [Keeping the blind](blind.md)
- [Commands](cli.md)
- [Architecture](architecture.md)
- [Field notes](field-notes.md)
- [FAQ](faq.md)
