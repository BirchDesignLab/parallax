# Architecture

This page describes how Parallax is built: the modules, the path one `parallax run` takes through them, where state lives, how seats are driven, how a run resumes, and how the code is tested. It is written against the code as of 2026-11-23; the design it implements is in [the design spec](superpowers/specs/2026-11-16-parallax-design.md).

## What it is made of

Parallax is one Python package (`parallax`, plus `parallax.seats`) with no dependencies outside the standard library. A single class, `Conductor` in `parallax/conductor.py`, carries a task from a task file to a landing commit. It calls two seats, which are adapters around the `claude` and `codex` command lines, and it does every other piece of work itself: git, running the project's checks, scope checks, hashing, writing the ledger and rendering cards. No model runs inside the conductor.

Everything the conductor knows about a task is an event in an append-only journal. There is no stored "current step"; each step looks for its own completion event and skips itself if it finds one. That is the whole resume mechanism (see [Resuming](#resuming)).

## Module map

| Module | What it owns |
|---|---|
| `parallax/__init__.py` | The package version. |
| `parallax/__main__.py` | Entry point for `python -m parallax`; calls `cli.main`. |
| `parallax/cli.py` | The `init`, `run`, `rule`, `status` and `demo` subcommands, argument parsing, rendering of outcomes and cards, and the exit codes (0 landed, 2 needs a ruling, 3 parked, blocked or dropped, 1 error). |
| `parallax/config.py` | Loads and validates `parallax.toml` into a frozen `Config`; holds the sample config written by `init`; `state_home()` (`PARALLAX_HOME`, else `~/.parallax`) and `repo_key()` (a 12-character hash that names a project inside the state home). |
| `parallax/conductor.py` | The `Conductor` class and its `Outcome` result. Opening a task, sealed readings, reveals, settlement, rulings, contract, braid, crossing, disputes and repairs, chores, landing, cleanup, the run lock, and every seat call (`_call`: privacy check, audit, voiding, retry). Also replays recorded histories to check them (`_published`, `_settlement`). |
| `parallax/batch.py` | The confirmed settlement protocol as pure functions: the canonical packet both seats see, the checks on a builder's proposal and a challenger's review, the settlement record (`direct_settlement`, `confirmed_settlement`), card text, rulings on a card (`ruling`, `ruling_problem`) and the terms a frozen contract takes from a settlement (`contract_terms`). Also canonical JSON and digests. |
| `parallax/decisions.py` | Pure helpers for disputes and contracts: the `Point` and `Dispute` records, `settle` (the original one-card-per-objection settlement, kept for tasks opened by earlier versions), `route` (direct or batch), witness and interface checks, conflict checks, precedents, and rendering of contracts, precedents and cards. |
| `parallax/briefs.py` | Every instruction a seat receives, as text: reading, reveal, proposal, review, build, probe, respond, solo, and the retry and rejection wrappers. Each brief is passed through the path scrubber. This is where the blind is kept or broken. |
| `parallax/schemas.py` | The JSON schemas for each seat output (reading, reveal, proposal, review, build, probe, solo, respond) and `validate`, a checker for the schema subset those use. |
| `parallax/crossing.py` | `validate_mutants` (checks the builder's mutants), `cross` (combine both seats' commits in a scratch clone, run the check, then run the check once per mutant) and the `CrossingResult` it returns. |
| `parallax/gitops.py` | Every git operation: seat clones (`clone_at`), snapshots, net deltas, applying a seat's range onto another tree, the landing commit, and `advance_main`. Also `remove_tree`, the retrying delete for Windows file locks. Seats never run git. |
| `parallax/ledger.py` | `Journal` (append-only JSON lines with a torn-tail rule), `publish` (append events to the committed ledger) and `sha256_text`. |
| `parallax/folders.py` | Private folders on Windows: `make_private` and `is_private`, using `icacls` so that only the current account, SYSTEM and Administrators have access. Falls back to mode `0o700` off Windows. |
| `parallax/procs.py` | `run_command`: runs a command with a timeout and kills its whole process tree. On Windows the process starts suspended, is put in a Job Object that kills on close, then resumed. Only the project's `check` and `lint` strings go through a shell. |
| `parallax/scopes.py` | Case-sensitive glob matching for write scopes (`matches`, `outside`), with `*` and `**`. |
| `parallax/audit.py` | `forbidden_hits`: finds forbidden paths in a seat's event stream after Windows path normalization. |
| `parallax/delivery.py` | Delivery accounting: `check` compares the files a seat declared with the net change it actually made, and rejects any mismatch. |
| `parallax/receipt.py` | The receipt: `probe_count`, `verdict`, `checks_line` and `trailers` (the git trailers stamped on the landing commit). |
| `parallax/redact.py` | `scrub_paths` and `scrub_values`: replace absolute paths with `<outside>/<file name>` in text a seat or the human will read. |
| `parallax/demo.py` | The throwaway `clamp` project, the underspecified task, and scripted stub seats for `parallax demo --stub`. |
| `parallax/seats/__init__.py` | `make_seats(cfg)` and the `ADAPTERS` registry. `claude` and `codex` are registered here. |
| `parallax/seats/base.py` | `SeatRequest`, `SeatResult`, the `Seat` protocol, and `seat_env` (the scrubbed environment a seat runs in). |
| `parallax/seats/claude.py` | `ClaudeSeat`: drives `claude -p`. |
| `parallax/seats/codex.py` | `CodexSeat`: drives `codex exec`, including per-call usage and cleanup of trust entries. |
| `parallax/seats/stub.py` | `StubSeat`: replays scripted outputs, no subprocesses. |

## How one `parallax run` flows through the modules

`python -m parallax run tasks/<id>.md` enters at `cli.main`, which calls `cli._run`: `load_config`, `seats.make_seats`, then `Conductor.run`. From there:

1. **Lock and check for prior landing.** `Conductor.run` takes `.parallax/run/lock` (`_lock`) and calls `_run`. If the task has no journal events and main's ledger already records it as landed or dropped, `_run` returns that outcome without doing anything. `_one_history` refuses a task whose ledger and journal copies disagree.
2. **Open.** `_open` records `task.opened` once: the kind (a first line of `Kind: chore` makes a chore, anything else a behavior task), the base commit (the tip of `main`), and the roles. Roles alternate by the number of tasks already opened, unless `--builder` names one. It then makes the task's state folder private (`folders.make_private`) and gives each seat its own clone (`_new_clone`, which calls `gitops.clone_at` and records `checkout.created`). A chore goes to `_solo` instead and has one clone, for the builder.
3. **Sealed readings.** `_readings` runs `_read` for each seat that has no `reading.sealed`, in parallel (`_parallel`). Each call is `briefs.reading` with `schemas.READING`, read-only, in the seat's own clone. The output is stored in canonical form and its hash goes into `reading.sealed` along with the seat's session id.
4. **Reveal.** `_reveal` runs `_reveal_one` for each seat, in parallel. Each seat resumes its own session and receives the other seat's reading (`briefs.reveal`, `schemas.REVEAL_CONFIRMED`). The reply is checked inside the retry loop (`_reveal_problem`, `decisions.witness_problem`, `decisions.conflict_problem`) and recorded as `reveal.done`.
5. **Settlement.** `_settle` calls `_publish`, which calls `_certified`. It builds the packet (`_batch_packet`, `batch.packet`) and asks `decisions.route`. On the direct route, `batch.direct_settlement` settles with no seat call. On the batch route, `_propose` asks the builder for a proposal (`briefs.propose`, `schemas.PROPOSAL`, checked by `batch.proposal_problem`, recorded as `batch.proposed`) and `_review_proposal` asks the challenger to attest or refuse it (`briefs.review`, `schemas.REVIEW`, `batch.review_problem`, `batch.reviewed`). `batch.confirmed_settlement` turns the pair into a settlement. `_publish` appends one `reading.settled` record, replays it through `_settlement` first, and writes a card file per pending card under `.parallax/run/<task>/cards/`. Tasks opened by an earlier version go through `decisions.settle` and `dispute.opened` instead.
6. **Rulings.** `_rulings` stops the run with `Outcome("needs_ruling", ...)` while any card is unruled. `parallax rule` calls `Conductor.rule`, which takes the same lock and appends `ruling.made` (`_rule_card` and `batch.ruling` for settlement cards, `_rule` for the older standalone cards). Running the task again continues.
7. **Contract.** `_contract` calls `_freeze_settled`: `_settled_contract` renders the contract from the settlement and rulings (`batch.contract_terms`, `decisions.render_contract`), writes `.parallax/run/<task>/contract-v1.md`, and records `contract.frozen` with its hash.
8. **Braid.** `_checkouts` restores any missing folder or clone, then `_braid` runs `_attempt` for the builder and challenger in parallel. Each attempt records `attempt.started`, sends `briefs.build` (`schemas.BUILD`) or `briefs.probe` (`schemas.PROBE`) with write access, and then `_validate` checks the result: changed paths against the role's scope (`scopes.outside`), the builder's mutants (`crossing.validate_mutants`), a snapshot commit (`gitops.snapshot`), declared files against the net change (`delivery.check`), and the project's `lint` command. A rejection goes back to the seat once; a second rejection blocks the task. Success records `attempt.finished` with the commit.
9. **Crossing.** `_crossing` gathers both commits into a scratch clone (`<task folder>/cross`) and calls `crossing.cross`, which checks out the builder's commit, applies the challenger's range on top (`gitops.apply_range`), runs the project's `check`, then runs it again once per mutant with the mutant's files swapped in. A mutant is killed when the check fails or times out. The result is recorded as `crossing.done`, and the check output is written to `.parallax/run/<task>/crossings/<n>/check.txt`.
10. **Verdict.** `_clean` asks whether the check passed and every mutant was killed or waived. If so, the run goes to landing. If not, `_after_failed_crossing` takes over: it stops for any pending card, carries out rulings (`_amend_contract`, `_repairs`), checks the repair limit (`max_repair_rounds`, default 2, after which an `unresolved` card is opened), asks the seats to concede or contest (`_respond`, `briefs.respond`, `schemas.RESPOND`), and opens a card per evidence item if nobody conceded. The loop in `_run` crosses again after each repair.
11. **Integrate.** `_land` computes the verdict and checks line (`receipt.verdict`, `receipt.checks_line`), builds the trailers (`receipt.trailers`) and calls `_integrate`. That clones current `main` into `<task folder>/land`, applies each seat's range, appends the journal's events to `.parallax/ledger.jsonl` (`ledger.publish`), writes `.parallax/contracts/<task>.md` and `.parallax/PRECEDENTS.md`, and stages everything. Before committing it checks that every staged path was declared by a seat or is one of its own records, and it runs the project's `check` on that tree. It then commits with the human's configured git identity (`gitops.commit_staged`), verifies the commit's tree is the tree it staged, and moves `main` with `gitops.advance_main`. If `main` moved in the meantime it tries again, up to three times. If `main` is checked out with uncommitted changes in the way, the result is parked on `parallax/ready/<task>` and the outcome is `parked`.
12. **Cleanup.** `_finish` removes the task's events from the journal (`Journal.drop_task`), asks each seat adapter to `discard` its session, deletes the task's state folder and any park branch.

A chore skips steps 3 to 10. `_solo` makes one builder call, validated with a scope of `**` and the lint command, runs the check once in the scratch clone, then goes to `_integrate`. Its receipt has verdict `solo` and no `Parallax-Contract` or `Challenged-by` trailer.

## State and where it lives

State is in three places: files committed in the project, files in the project that git ignores, and files outside the repo.

```
<project>/
  parallax.toml                       committed: config
  .parallax/
    .gitignore                        committed: contains "run/"
    ledger.jsonl                      committed: decisions of landed tasks
    contracts/<task>.md               committed: the frozen contract, written at landing
    PRECEDENTS.md                     committed: project-scoped rulings, rewritten at landing
    run/                              git-ignored
      lock                            pid of the active run
      journal.jsonl                   events of tasks in flight
      <task>/
        contract-v<n>.md
        cards/<id>.md                 pending cards
        crossings/<n>/check.txt

<state home>/                         PARALLAX_HOME, else ~/.parallax; outside the repo
  <repo key>/<task>/                  private to the human's account, SYSTEM and Administrators
    <seat>-<8 hex>/                   one clone per seat (a new one after a voided attempt)
    artifacts/<nn>-<seat>-<stage>/    brief.md, schema.json, events.jsonl, output.json
    artifacts/codex-usage.json        the Codex thread's last running total
    mutants/<id>/                     the builder's mutants, moved out of its clone
    cross/                            scratch clone where the crossing runs
    land/                             scratch clone where the landing commit is built
  demos/                              projects made by `parallax demo`
```

| Path | Committed | Notes |
|---|---|---|
| `parallax.toml`, `.parallax/.gitignore` | Yes | Written by `parallax init`. |
| `.parallax/ledger.jsonl`, `.parallax/contracts/`, `.parallax/PRECEDENTS.md` | Yes | Written into the landing commit, so the history of decisions travels with the code. |
| `.parallax/run/` | No, git-ignored | The journal, lock, rendered contracts, cards and check output of tasks in flight. |
| `<state home>/...` | Outside the repo | Seat clones, artifacts, mutants and the scratch clones. Removed when the task lands. |

The ledger and the journal share one event format (JSON lines, each with `ts`, `type` and `task`). While a task runs its events are in the journal. At landing, `ledger.publish` appends them to the ledger in the landing commit, and `_finish` then drops them from the journal. `Conductor.events()` reads the ledger as committed on `main` (`git show`, not the working copy) followed by the journal, counting each task once.

The state home is kept out of `%LOCALAPPDATA%` and `%APPDATA%` on purpose: a process started from a packaged app has new folders there redirected, and Codex's sandbox then cannot find them. `~/.parallax` and `PARALLAX_HOME` avoid that. The task folder is made private before anything goes into it, and `_call` checks `folders.is_private` before every seat call.

Two things sit outside both places. Codex adds a trust entry for each folder it runs in to `~/.codex/config.toml`; the Codex adapter removes the entries for a task's folders when it discards the session. Each seat's session lives in its own CLI's store until `discard` deletes it (`codex delete --force <session>`, `claude purge -y <folder>`).

## The seat adapter interface

The interface is three types in `parallax/seats/base.py`.

- `SeatRequest`: `stage` (reading, reveal, build, probe, respond and so on), `brief` (the full instruction text), `cwd` (the seat's clone), `schema` (the JSON schema its answer must match), `writable`, `session` (a session id to resume, or `None` to start one) and `out_dir` (a fresh artifact folder for this call).
- `SeatResult`: `output` (the parsed answer or `None`), `session`, `events` (the CLI's event stream as text), `usage` (`input`, `cached`, `output` token counts) and `error`. `ok` is true when there is no error and an output.
- `Seat`, a protocol: attributes `name`, `model` and `effort`, a `run(req) -> SeatResult` method and a `discard(session, cwd)` method that deletes the session and any trust entry, and must never raise.

`seats.make_seats` builds one seat per `[seats.<name>]` table in `parallax.toml`. The table's `adapter` key picks the adapter and defaults to the seat's name. Config validation requires exactly two seats.

Both real adapters write `brief.md`, `schema.json` and `events.jsonl` to `out_dir`, send the brief on stdin through `procs.run_command` (so a timeout, `seat_timeout`, default 1800 seconds, kills the whole tree), validate the answer against the schema with `schemas.validate`, and write `output.json`. Both run in an environment from `seat_env`, which removes every variable starting with `CLAUDE`, `ANTHROPIC`, `OPENAI` or `CODEX` except the one or two the seat needs (`ANTHROPIC_API_KEY` for Claude; `OPENAI_API_KEY` and `CODEX_HOME` for Codex). A Claude seat started from inside a Claude Code session otherwise fails to authenticate.

### Claude

`ClaudeSeat.run` builds this command line, adding the session flag last:

```
claude -p --model <model> --effort <effort>
       --safe-mode --restricted --tools <tools>
       --permission-mode acceptEdits --permission-prompts none
       --output-format stream-json --verbose
       --json-schema <schema>
       --session-id <new uuid>        (first call)   or   --resume <session>
```

| Flag | Why |
|---|---|
| `-p`, `--permission-mode acceptEdits`, `--permission-prompts none` | Headless: the seat cannot stop to ask, so edits inside its folder are accepted. |
| `--model`, `--effort` | Set explicitly on every launch and recorded, because the receipt names them. |
| `--safe-mode` | No personal plugins, hooks or MCP servers, so the brief is the only instruction. |
| `--restricted` | File tools are confined to the working directory. A read outside it is refused and appears in the event stream. |
| `--tools Read,Write,Edit,Glob,Grep` (writable stages) or `Read,Glob,Grep` (read-only stages) | No shell at all. The conductor runs every check, so a seat has nothing to run. |
| `--output-format stream-json --verbose` | The event stream the audit scans, ending in a `result` event with usage and the session id. |
| `--json-schema` | The answer arrives as `structured_output`. If it is absent the adapter tries to parse `result` as JSON. |
| `--session-id`, `--resume` | A seat keeps one session for the length of a task. |

Usage comes from the `result` event: `input` is `input_tokens` plus cache reads plus cache creation, `cached` is cache reads. Claude reports these per call. `discard` runs `claude purge -y <folder>`.

### Codex

`CodexSeat.run` builds this command line. Brackets mark parts that depend on the call:

```
codex exec [resume]
      -m <model> -c model_reasoning_effort="<effort>"
      --ignore-user-config
      [-c windows.sandbox="<value from ~/.codex/config.toml>"]
      first call:   --sandbox <workspace-write|read-only> -C <clone> --color never
      resumed call: -c sandbox_mode="<workspace-write|read-only>"
      --json --output-schema <schema.json> -o <last.json>
      [<session id>]  -
```

| Flag | Why |
|---|---|
| `-m`, `-c model_reasoning_effort=...` | Pins model and effort. The event stream does not report them, so the conductor records what it pinned. |
| `--ignore-user-config` | The brief is the only instruction. |
| `-c windows.sandbox=...` | With `--ignore-user-config` alone, every sandboxed command is rejected. The adapter reads only the `[windows] sandbox` setting from the human's config, when it exists, and passes it back. |
| `--sandbox workspace-write` or `read-only`, `-C <clone>` | The sandbox limits where the seat writes. Read-only stages (readings, reveals, proposals, reviews) never get write access. |
| `-c sandbox_mode=...` on `resume` | `codex exec resume` accepts no `--sandbox` flag. |
| `--json` | The event stream: `thread.started`, `item.completed`, `turn.completed`. |
| `--output-schema`, `-o` | The final message is shaped by the schema and captured in `last.json`. |
| `-` | The brief is read from stdin. |

If the first launch exits non-zero before any `thread.started` event (the spec records a transient sandbox launch failure), the adapter tries once more.

**Usage is reported per call by differencing.** Codex's `turn.completed` usage is the thread's running total, so a resumed call reports every earlier call too. The adapter keeps the last total it saw for each thread in `artifacts/codex-usage.json` in the task folder, so it survives a restart, and reports each call's difference (`_spent`). A call that dies without a `turn.completed` reports nothing, and its spend lands on the next call. Events already written to a ledger keep the figures they were written with.

`discard` runs `codex delete --force <session>` and removes the `[projects.'<folder>']` entries Codex added to `config.toml`.

### Stub

`StubSeat` takes a script: a dict from stage name to a list of steps. Each call pops the next step for its stage and calls it with the request. A step returns an output dict, which is validated against the request's schema, or a `SeatResult`. A step may write files into `req.cwd`, as a real seat would, or raise to simulate an interrupted run. A call with no step left raises `AssertionError`. It makes no subprocess calls and spends nothing. `StubSeat` is not in the default `ADAPTERS`; `demo.stub_adapter()` and the tests register it for the length of a block.

## Resuming

A run does not track a current step. `_run` calls the steps in order, and each step starts by looking for its own completion event and returns at once if it finds one. The events are those from `Conductor.events()`: the committed ledger on `main` plus the journal. A run that crashed, paused for a ruling, or stopped on a blocked seat resumes by running the same task file again.

| Step | Completion event | If missing |
|---|---|---|
| Open | `task.opened` | Recorded now. A recorded opening is never changed. |
| Readings | `reading.sealed` per seat | The seat is called again, in a new session. |
| Reveal | `reveal.done` per seat | The seat is called again, resuming its sealed session. |
| Settlement | `reading.settled`, with `batch.proposed` and `batch.reviewed` as checkpoints | A completed checkpoint is verified and reused, never asked again. |
| Rulings | `ruling.made` for every card | The run stops with `needs_ruling`. |
| Contract | `contract.frozen`, checked against the file's hash | Rendered and frozen again. |
| Attempts | `attempt.finished` per role | See below. |
| Crossing | `crossing.done` whose two commits match the seats' current heads | Run again. |
| Landing | `task.integrated` in main's ledger | Run again. |

Stored outputs are checked, not trusted: the stored reading must hash to the sealed value, and a contract file that is missing or no longer matches its recorded hash blocks the task.

**An attempt that started and never finished.** `_attempt` records `attempt.started` before it calls the seat. If a later run finds an `attempt.started` for that role and no `attempt.finished`, it throws away what the attempt left in the seat's clone (`git reset --hard` and `git clean -fdx`), records a new `attempt.started`, and runs the call again. The seat resumes its existing session. Responses to a failed crossing (`_respond`) clean the clone the same way before each call.

Other recovery behavior:

- **Torn writes.** Each event is written with its newline in one fsynced write. `Journal.append` first truncates anything after the last newline, and readers ignore it. A bad event before the last newline raises `LedgerCorrupt`.
- **Stale lock.** `_lock` writes the process id into `.parallax/run/lock`. A lock whose process is gone is removed. A live one makes the run return `blocked`.
- **Died after main moved.** `_land` first asks `_landed_on_main`. If main's ledger already records the task, it only finishes the cleanup that was missed.
- **Missing clone.** `_checkouts` makes a new clone for a seat that has no finished attempt and discards the old session, so the seat starts fresh.
- **Voided attempts.** A seat whose event stream names the other seat's folder is voided: `attempt.voided` (or `reading.voided`) is recorded, its session and clone are deleted, and the rerun is a new session in a new clone from the contract alone. A second void blocks the task.
- **Seat failures.** `_call` retries a bad or failed result once. A second failure records `seat.failed` and blocks the task.

`parallax status` derives its rows from the same events: a task still in the journal is `needs_ruling` if a card is unruled, `parked` if its last event is `task.parked`, `blocked` if its records fail the replay checks, else `in_progress`; a task only in the ledger is `landed` or `dropped`.

## How it is tested

The command is:

```
python -m unittest discover -s tests -t . -v
```

The suite has 407 tests in 32 modules, as measured on 2026-11-23, and it runs on scripted seats and spends no tokens. It takes about half an hour to run. By file count, 12 modules (`tests/test_conductor_*.py`) exercise the `Conductor` end to end; the remaining 20 cover the other modules (`batch`, `briefs`, `cli`, `config`, `crossing`, `decisions`, `delivery`, `demo`, `folders`, `gitops`, `ledger`, `procs`, `receipt`, `schemas`, `scopes` and `audit` together, and the three seat adapters), a replay of a recorded ledger, and the live test.

- **Stub seats.** The conductor tests drive the real `Conductor` against real git repositories, with `StubSeat` standing in for both CLIs. `tests/conductor_kit.py` builds a project and provides script steps (readings, reveals, builds that write files and mutants into the clone, probes, responses). This is how every branch is covered: disagreement, each settlement path, ruling, a failed crossing, a surviving mutant, repair, a voided attempt, and resuming after an interruption at each step (a step that raises simulates the kill).
- **Fake CLIs.** `tests/fakes/fake_claude.py` and `tests/fakes/fake_codex.py` stand in for the two executables. They record their arguments, stdin, working directory and the agent-related environment variables they received, then replay the stream shapes the real CLIs produced, including failure modes (an expired login, a missing result, a launch failure, non-JSON output, a wrong shape). `test_seat_claude.py` and `test_seat_codex.py` use them to pin the exact command lines, session resumption, how failures are reported, and, for Codex, the retry of a launch failure, per-call usage and cleanup of trust entries.
- **Recorded history.** `tests/fixtures/` holds the event history of a real run, extracted by `scripts/fixtures/extract_clamp_11_19.py`, and normalized histories with their expected CLI results. Tests replay the first through the current conductor to check that records written by an earlier version still read the same, and compare the others against the files.
- **Isolation.** `tests/__init__.py` points `tempfile` and `PARALLAX_HOME` at a per-run folder inside the repo and removes it afterwards, so a test never touches a real state home. `tests/test_folders.py` and `tests/test_procs.py` exercise real Windows permissions and process-tree killing.
- **Live test.** `tests/test_live_seats.py` calls the real CLIs and is skipped unless `PARALLAX_LIVE=1`. It has two tests, one per CLI: write a file, then resume the session and ask about it.
- **Probes.** `scripts/probes/` holds scripts that check what the design depends on in the real CLIs. They are not part of the unit-test run.
  - `seat_smoke.py` runs one case per behavior the design relies on (sign-in, structured output, confinement of file tools, folder permissions, session resume, both CLIs at once), prints `[ok  ]` or `[FAIL]` per expectation and exits non-zero if any fails.
  - `job_object_seats.py` checks that both CLIs still work when launched through `procs.run_command`.
  - `usage_by_call.py` prints every usage-bearing event of a project's ledger, which is how the cumulative Codex usage was found.
  - `clamp_bound_check.py`, `clamp_disputes.py` and `codex_thread_model.py` are analysis scripts from earlier runs.

  Rerun `seat_smoke.py` and `job_object_seats.py` after either CLI updates. They spend a few small prompts on each subscription.

The demo (`python -m parallax demo`) is the end-to-end check with the real CLIs. It reports which path the run took.

## Design constraints

- **Standard library only.** `pyproject.toml` declares no dependencies and requires Python 3.12 or later. Windows APIs (`ctypes` for Job Objects, `icacls` for permissions) are reached without third-party packages.
- **Windows 11 is the target.** The Job Object handling in `procs`, the permission recipe in `folders`, the retrying `remove_tree` and the Codex sandbox setting are all written for it. There are POSIX fallbacks in `procs` and `folders`, but nothing is tested elsewhere.
- **No model in the conductor.** Every decision it makes is a rule over recorded events: routing, settlement checks, scope checks, delivery accounting, verdicts. The only model calls are seat calls, and they go through the adapter interface above.
- **Seats edit files; the conductor does the rest.** A seat never runs git and never runs the project's tools. The conductor checks every changed path against the role's scope, makes the commits (snapshots under an internal identity that never reaches `main`, the landing commit under the human's), runs `lint` after each attempt, and runs `check` at the crossing and again on top of current `main` before landing. This is also forced by the environment: Codex's sandbox on the target machine cannot run Python.
- **The blind is arranged and audited.** Separate clones in a private folder, tool restrictions where each CLI offers them, readings and attempts hashed before they are shown, and a scan of each event stream for the other seat's paths. The audit is best effort and the docs do not claim more.
- **Local only.** The conductor never pushes. It moves `main` in the project's own repository.
- **Delivery accounting.** Every landed seat change matched its accepted inventory; relevance is not independently reviewed.

## See also

- [Documentation index](README.md)
- [Concepts](concepts.md)
- [The life of a task](life-of-a-task.md)
- [Rulings and precedents](rulings.md)
- [Receipts and the ledger](receipts.md)
- [Keeping the blind](blind.md)
- [Commands](cli.md)
- [parallax.toml](configuration.md)
- [Field notes](field-notes.md)
- [FAQ](faq.md)
