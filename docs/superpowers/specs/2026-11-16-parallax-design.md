# Parallax: design

Date: 2026-11-16. Status: draft for the human's approval. Codex read it cold and withheld its signature on one condition, which has been adopted. Nothing is built yet.

## What was asked

> let's cook up a generic framework to allow claude code and chatgpt codex to collaborate on projects in parallel. we're going to start in this folder and may keep it local unless we come up with something brilliant.

> i'm looking for WOW^11 here. get creative

That is all the human has said about what and why. Anything below that is not marked **Ruling** is a proposal from the two agents.

## Where this design came from

Claude Code and Codex each wrote a proposal without seeing the other's (`docs/round-0`), then each reviewed the other's (`docs/round-1`). They arrived at the same core independently, which is the main reason to trust it.

The core: two different models make less correlated mistakes than two copies of one model. So a project is not split into halves. Each task is split into two sides: one agent builds it while the other, without seeing the code, writes the checks that will judge it. When they agree, that is evidence. When they disagree, that is the valuable output: it is either a bug or a hole in the spec, and it is the only thing worth the human's attention.

## Goals

1. Claude Code and Codex work on one project at the same time without overwriting each other.
2. No behavior change reaches main verified only by the model that wrote it.
3. The human is asked only what the agents cannot settle with evidence, and is not asked again while the conditions of a ruling still hold.
4. Every change on main carries a receipt: who built it, who challenged it, what was checked, how any dispute ended.
5. Generic. A project plugs in with one config file. An agent CLI plugs in with one adapter.
6. Coordination spends no model tokens. The conductor is ordinary code.

## Not in v0

More than one task in flight; a dashboard; replaying work when an assumption changes; experiments as a dispute step; a scoreboard; messaging live interactive sessions; evidence that is not an automated check; more than two seats.

## Anti-goals

Ways this could run and still be a failure:

- Agents talk to each other freely. They anchor on each other and the independence is gone.
- A model acts as manager.
- A green run is called agreement when the checks could not have failed.
- The human carries prompts between agents or resolves merges by hand.
- An agent writes outside its worktree or its assigned paths and nobody notices.

## Constraints

- One Windows 11 machine, one human. Codex CLI 0.160.0, Claude Code 2.1.308, Python 3.12, git.
- Local only for now: no remote, no publishing.
- The framework's own code lives in this folder. Projects it runs on are separate folders that contain a `parallax.toml`.
- Seats run headless: `codex exec` and `claude -p`. Neither can stop to ask permission.
- Codex's sandbox limits where an agent writes, not what it reads. The operating system cannot keep one agent from reading the other's work, so blindness has to be arranged and audited (see "Keeping the blind honest").
- **Ruling:** design-grade Codex work runs on `gpt-6-astra` at high or xhigh. ("if it wasn't astra high or extra high it's probably not good")

## Approaches considered

| Approach | What it is | Why not, or why |
|---|---|---|
| Foreman | One agent plans, both execute separate tasks, changes are merged. | Most throughput, but every change is still checked only by its author, and separate tasks collide in shared files. |
| Tournament | Both agents build every task; the better result wins. | Good for hard problems. Pays twice for one result. Both agents set it aside as a later option. |
| Hotline | Two live sessions message each other (`codex queue`, Claude hooks). | Enjoyable to watch. Chatty, and each agent's view contaminates the other's. |
| **Parallax** | Builder and blind challenger on every task, evidence-only disputes, human rulings that persist. | Picked. Both agents chose it blind. The second agent's work is the tests, which have to be written anyway, so little is paid twice. |

## The design

### Terms

- **Seat**: an agent CLI the conductor can launch. v0 has two: `claude` and `codex`.
- **Conductor**: the Python program that runs everything. It contains no model.
- **Task**: one change to make, described in a short spec file.
- **Reading**: a seat's written interpretation of a task, made before any code.
- **Contract**: the frozen interface and decisions both sides work from.
- **Builder / challenger**: the seat that writes the change / the seat that writes the probes. They swap every task.
- **Probe**: an automated check written by the challenger from the contract alone.
- **Mutant**: a deliberately broken copy of the change. Probes must catch it.
- **Crossing**: the moment the builder's change and the challenger's probes first meet.
- **Dispute, ruling, precedent**: a disagreement backed by evidence; the human's decision on it; that decision kept and reused.
- **Receipt**: the verification summary stamped on the commit.
- **Ledger**: the append-only record of every event.

### One task, start to finish

1. **Open.** The conductor reads the task and assigns roles. Roles alternate from task to task.
2. **Sealed readings.** Each seat separately returns: the exact interface it expects (files, names, signatures), each ambiguity it sees in the spec with how it would resolve it, and where it expects an implementation to go wrong. The conductor records a hash of each reading before showing either to anyone.
3. **Reveal.** Each seat sees the other's reading and, point by point, adopts the other's answer or holds its own. Points both accept are settled. The builder's interface stands unless the challenger objects.
4. **Rulings.** Each point still held by both sides is a real ambiguity in the spec. Precedents are checked first; what remains goes to the human as a card: the question, the two answers, each side's reason. The answer becomes a precedent.
5. **Contract.** The conductor writes the contract from the settled points and records its hash.
6. **Braid.** In separate worktrees, at the same time: the builder writes the change plus a small number of mutants; the challenger writes probes from the contract. Neither sees the other's files.
7. **Crossing.** In a third, throwaway worktree the conductor combines the two and runs the project's check command. Then it runs the probes against each mutant; every mutant must fail.
8. **Verdict.** Probes pass and all mutants are caught: done. Otherwise each failure becomes a dispute (see "Disputes").
9. **Integrate.** On current main, the conductor re-runs the checks and moves main forward only if main is still where it expected. The commit carries the receipt.

**Ruling:** every behavior change goes through all nine steps. Chores that do not change behavior (docs, renames) are built by one seat and their receipt says `solo`. A task is treated as a behavior change unless its spec says otherwise.

**Ruling:** step 9 happens automatically once the gates pass. The human is not asked to approve merges.

### Keeping the blind honest

The blind is enforced where each CLI can enforce it and audited everywhere. Seats are treated as fallible, not hostile, and no receipt claims more than that.

- **Placement.** Each seat's worktree is a separate clone of the project with no git link to the other seat's. It sits under a random name in a state folder in the human's home folder (`~/.parallax` by default), outside the repo. A seat is told only its own path. Nothing a seat produces enters the project's own repo until the task lands. The state folder must not be under `%LOCALAPPDATA%` or `%APPDATA%`: a process started from a packaged app (Claude's desktop app is one) has new folders there silently redirected, and Codex's sandbox then cannot find them.
- **Confinement.** Each task's folder in the state folder is made private before anything is put in it: its permissions name only the human's account, SYSTEM and Administrators, and everything inside inherits that. Codex runs in its `workspace-write` sandbox, which on this machine runs commands as a separate Windows user. Codex adds entries for that user to the one clone it works in and to nothing else, so the other seat's clone, the scratch clones and the artifacts stay closed to it. A sandboxed read of a private sibling folder was refused ("Access is denied"), in `%TEMP%` and under the home folder. Claude gets file tools restricted to its own worktree and no shell at all. Under `--restricted` a read outside its folder is refused and reported in the event stream (verified 2026-11-17).
- **Seal.** Readings and attempts are hashed into the ledger before reveal, so nothing can be adjusted afterwards.
- **Audit.** Both CLIs emit an event stream of what a seat did. After each attempt the conductor scans it for any path belonging to the other seat or to the state folder. This is the second line of defense and it is best effort: a script that reads another worktree without naming it would get past.
- **Voiding.** A hit voids the attempt, and the contamination goes with it: the session, the worktree and everything the attempt produced are discarded. The rerun is a new session in a new worktree, starting from the contract alone.

Seats never message each other. Everything a seat learns about the other side arrives from the conductor at steps 3 and 8. A seat keeps one session for the length of a task, so a repair starts with its own context. The exceptions are a voided attempt, as above, and a new task, which always starts a new session.

### Who may write what

- Each role has path patterns in the project config, for example builder `src/**`, challenger `tests/**`. Files both would need (lockfiles, manifests) are listed as exclusive and belong to the builder for that task.
- Seats only edit files. The conductor does all git work: it checks every changed path against the seat's patterns, rejects the attempt if any falls outside, and makes the commits itself.
- The conductor also runs every check. Seats are not relied on to run project tools: on this machine Codex's sandbox cannot execute Python at all. A project may name a quick `lint` command, which the conductor runs on a seat's worktree after each attempt; a failure goes straight back to that seat and does not use up a repair round.
- **Ruling:** a seat edits and runs commands inside its own worktree without asking. How each seat is confined is described under "Keeping the blind honest".

### Disputes

A dispute needs evidence: a failing probe, a mutant that survived, or a contract line that was not met. Opinions do not open disputes.

1. Both seats receive the evidence. Each answers **concede** (and repairs its own side) or **contest** (and cites the contract).
2. After repairs the crossing runs again. Two repair rounds are allowed per task.
3. If both contest, the contract is ambiguous at that point: the human rules, the contract is amended, the losing side repairs.
4. If two rounds do not settle it, the human gets the unresolved tradeoff and may rule, accept the change with a limitation, or drop the task.

Main never receives a failing check. Accepting a limitation means the contract and the probes are amended to say what is no longer promised, and the crossing runs again and passes. A mutant the probes cannot catch may be waived by the human. Either way the limitation is written on the receipt.

### Rulings and precedents

A ruling is stored with its scope (this task, or the whole project) and, optionally, the condition under which it holds ("while there is a single user"). Precedents in force are included in every brief. A seat that believes a precedent no longer applies raises that as an ambiguity in its reading, which sends the question back to the human; this is the only way a settled question returns.

The conductor never blocks waiting at a prompt. When it needs a ruling it writes the card to disk, prints it, and exits; `parallax rule` records the answer and `parallax run` picks up where it stopped. Any front end can therefore present the card.

### Receipts

Trailers on the integration commit:

    Parallax-Task: clamp-001
    Parallax-Contract: sha256:9f2c...
    Built-by: codex gpt-6-astra/xhigh
    Challenged-by: claude fable/high
    Checks: 14 probes passed, 3 of 3 mutants caught
    Verdict: consensus

Verdict is one of `consensus` (clean at first crossing), `resolved` (settled by the seats after a dispute), `ruled` (a human ruling was needed), `limited` (accepted with a stated limitation), `solo` (not pair-verified).

### Ledger and resuming

`.parallax/ledger.jsonl` in the project is the source of truth for decisions: readings, contracts, attempts, crossings, disputes, rulings, receipts. It is plain text so that either agent, the human, and git can all read it. While a task is running its events go to a journal in `.parallax/run/`; landing moves them into the ledger as part of the integration commit, so the history of decisions travels with the code. The journal, check logs and pending cards live in `.parallax/run/`, which git ignores. Anything one seat must not see before the crossing (the other seat's worktree, its output and its event stream) is kept in the state folder outside the repo.

Every step records its completion. `parallax run` works out the current step from the ledger, so a crash or a pause for a ruling resumes cleanly; an attempt that started but never finished is discarded and rerun.

### Seats

An adapter turns "run this brief in this folder and return output matching this schema" into a CLI invocation, and returns the parsed output, the session id, the event stream and the token usage. Model and effort are set explicitly on every launch and written to the ledger; the round-0 run showed Codex's event stream does not report them.

Seats launch without the human's personal plugins, hooks and MCP servers (`--safe-mode` for Claude, `--ignore-user-config` for Codex), so briefs are the only instructions and nothing else spends tokens. Two things have to be put back. Codex needs its `[windows] sandbox` setting re-supplied, or every command is refused. And both seats are launched with other agents' environment variables removed: a Claude seat started from inside a Claude Code session otherwise fails to authenticate, and the inherited variables include the account email.

A third adapter, `stub`, replays scripted outputs. The conductor's own tests use it, so the whole lifecycle is testable without spending a token.

### Project config

`parallax.toml` at the project root:

    [project]
    check = "python -m unittest discover -s tests"
    lint  = "python -m compileall -q ."
    main  = "main"

    [scopes]
    builder    = ["src/**"]
    challenger = ["tests/**"]
    exclusive  = ["pyproject.toml", "uv.lock"]

    [policy]
    merge = "auto"
    pair  = "behavior"
    max_repair_rounds = 2
    mutants = 3

    [seats.codex]
    model  = "gpt-6-astra"
    effort = "xhigh"

    [seats.claude]
    model  = "fable"
    effort = "high"

### Commands

- `parallax init`: add the config and `.parallax/` to a project.
- `parallax run <task>`: run or resume a task until it lands or needs a ruling.
- `parallax rule <dispute> <choice>`: record a ruling.
- `parallax status`: where each task stands.
- `parallax demo`: build a throwaway project and run the v0 demonstration.

## v0

One task, end to end, with real seats, from one command. `parallax demo` creates a throwaway git project whose only task is deliberately underspecified: "`clamp(x, lo, hi)` returns x limited to the range lo..hi", which says nothing about `lo > hi`, NaN, or non-numbers. A demo run shows, in order: the two readings and where they differ; a ruling card if they do; the contract; both seats working at once; a crossing; the mutant check; any repair; main advanced with a receipt; the ledger; and what each seat spent.

Done means: the stub-seat test suite passes, and the demo completes with real seats on this machine. The demo does not have to produce a disagreement to count, since the two models may read the task the same way. Every branch (disagreement, ruling, failed crossing, surviving mutant, repair, voided attempt, resume) is proven with scripted stub seats. The demo proves the real CLIs can carry one task to a receipt, and reports which path it took.

## Decisions and whose they are

**The human's rulings (2026-11-16):** merge automatically after the gates; pair-verify every behavior change; seats work unprompted inside their own worktrees; the name is Parallax; Codex design work runs on gpt-6-astra at high or xhigh.

**Agreed by both agents independently:** sealed readings before code; builder and challenger with rotating roles; evidence-only disputes; a conductor with no model in it; the human sees only what the agents cannot settle; building everything twice is not the default.

**Conceded by Claude to Codex in review:** errors are less correlated, not uncorrelated; a green run needs the mutant check before it counts; rulings carry scope and conditions; shared files such as lockfiles need their own rule; evidence should eventually include what cannot be automated (after v0).

**Claude's calls, accepted by Codex on its cold read (`docs/round-2`):**

- The ledger file, not SQLite, is the source of truth. Codex had proposed SQLite owning durable state. A database for live scheduling state arrives with multi-task scheduling, where it earns its place.
- No agent-to-agent mailbox. Codex had proposed messages delivered at turn boundaries.
- Seats do not run git; the conductor commits for them.
- The builder writes the mutants.
- Python, standard library only.
- The Claude seat defaults to `fable` at `high`.

**Overturned by Codex on its cold read:** "one session per seat per task" had no exception. A challenger that peeked would be rerun in the same session, still remembering what it saw. A voided attempt now takes its session and artifacts with it. Codex made this its one condition for signing, and it is adopted.

**Claude's calls in answer to Codex's builder questions, for the human to check:**

- The blind is enforced only as far as each CLI enforces it, and audited beyond that; receipts say no more than that. Isolation beyond what the CLIs provide (separate OS users or containers of our own) is deferred.
- Main never receives a failing check; a limitation means amending the contract and probes first.
- The demo counts whether or not the two models happen to disagree.

**Changed by the smoke test (`scripts/probes/seat_smoke.py`), Claude's calls for the human to check:**

- Seat worktrees are separate clones in a state folder in the human's home folder (`~/.parallax`), not linked git worktrees. Linked worktrees would let one seat find the other through git, and seat commits would sit in the project's repo where the other seat could read them.
- Each task's folder there is made private (the human's account, SYSTEM and Administrators only) before use, and the conductor checks that the other seat's clone is still private before every seat call.
- When a task ends, the Codex seat removes the trust entries Codex added to the human's `~/.codex/config.toml` for that task's folders. This is the one place the framework edits a file outside its own folders.
- Seats do not run checks; the conductor does. Neither side can run the other's half before the crossing anyway, and Codex's sandbox cannot run Python here.
- Because seats run nothing, the Claude seat gets no shell at all, which is stronger than the allowlist first proposed.
- Pre-crossing artifacts live in the state folder, not in `.parallax/run/`.

## Verified and not yet verified

Verified on this machine during round 0:

- `codex exec` runs headless from a brief on stdin, read-only, with a JSONL event stream that lists every command it ran, which is what the audit needs.
- Without `-m`, Codex inherits the model and effort from `~/.codex/config.toml`: a flagless run reports `model: gpt-6-astra` and `reasoning effort: xhigh` in its startup header. `-m` with `-c model_reasoning_effort=...` pins both. Runs started with `--ephemeral` leave no local record of the model, so the conductor must log what it pinned.
- Two `codex exec` processes ran at the same time without trouble.
- Codex's Windows sandbox failed to start one process (`CreateProcessWithLogonW failed: 1056`) and recovered. Adapters must tolerate a transient launch failure.
- On Windows a file named `claude.md` is loaded by Claude Code as `CLAUDE.md`, that is, as instructions. Nothing the framework writes may be named after an agent's instruction file.

Verified by `scripts/probes/seat_smoke.py` on 2026-11-16:

- `codex exec --ignore-user-config -c windows.sandbox="elevated" --sandbox workspace-write` writes files in the folder it is started in. `--output-schema` shapes the final message and `-o` captures it. With `--ignore-user-config` alone, every command is "rejected: blocked by policy".
- That sandbox runs commands as the Windows user `CodexSandboxOffline`. What it can read is decided by folder permissions, not by the sandbox mode. An ordinary folder under the profile inherits an entry for `CodexSandboxUsers` and is readable by it: in one run it read a file in a sibling folder. A folder whose permissions name only the human's account, SYSTEM and Administrators was refused ("Access is denied").
- Under `%LOCALAPPDATA%`, every sandboxed command failed to start (`CreateProcessWithLogonW failed: 267`). The cause is not permissions: Claude's desktop app is a packaged app, so a folder this session creates under `%LOCALAPPDATA%` really lives in the package's private cache, and the sandbox user is told to start in a folder that does not exist for it. `%TEMP%` and the home folder are not redirected.
- With the seat's clone in a private folder under the home folder: sandboxed commands start, and the human's account can read and delete the files they create. Under a folder that is owner-only (what `tempfile.mkdtemp` makes), the human's account could delete such files but not read them, so that arrangement is ruled out.
- Codex appends a `[projects.'<folder>'] trust_level = "trusted"` entry to the human's `~/.codex/config.toml` for every new folder it runs in, even with `--ignore-user-config`.
- Asking a model to read or write another folder as a test trips OpenAI's safety system ("possible cybersecurity risk") and fails the turn. The probes no longer do that; isolation is judged from the folders' permissions.
- `codex exec resume <thread id>` continues a session headless. It takes no `--sandbox` flag, so `-c sandbox_mode="workspace-write"` is passed instead, and it works.
- Codex's event stream: `thread.started` carries the session id; `item.completed` of type `command_execution` carries each command with its output and exit code; `turn.completed` carries token usage.
- Inside the Codex sandbox `python`, `py` and `uv` do not resolve, though `git` and `node` do. They are installed under the human's profile.
- Claude accepts `--safe-mode --restricted --tools ... --permission-mode acceptEdits --permission-prompts none --output-format stream-json --verbose` together. The stream opens with a `system/init` event listing the tools and ends with a `result` event carrying `is_error`, `result`, `session_id` and `usage`.
- On 2026-11-16 the standalone Claude CLI was not signed in, so nothing past those flags could be checked that day. See 2026-11-17 below.
Verified by `scripts/probes/seat_smoke.py` on 2026-11-17, after the human signed the Claude CLI in, with the fixture laid out as the design lays out a task (one private task folder under the home folder holding the repo and one separate clone per seat). Every case passed and the probe exited 0:

- `claude auth status` reports `loggedIn: true` with the seat's scrubbed environment, so a seat needs no inherited host variables.
- `--json-schema` works: the result event carries the answer as an object under `structured_output`, and the same answer as a JSON string in `result`.
- `--restricted` confines the file tools to the working directory. A `Read` of the other seat's clone was refused; the stream carries a `system/permission_denied` event with `decision_reason` "--restricted: path outside the working directory" and the path in `message`, and the result event lists it under `permission_denials`. The tool result back to the model has `is_error: true`. The canary in that file never appeared. `--tools Read,Write,Edit,Glob,Grep` leaves no shell; a `Bash` call fails with "No such tool available".
- `--session-id <uuid>` then `--resume <uuid>` continues a session headless; the second call remembered a word from the first.
- Claude and Codex ran at the same moment without trouble.
- A sandboxed Codex command's `Test-Path` on the other seat's file, under the home folder, failed with "Access is denied". The other clone's permissions list no sandbox entry; Codex added `CodexSandboxUsers` and a per-run SID to its own clone only.
- Cost note: a fresh `fable` call spends about 24k cache-creation tokens on Claude Code's own system prompt before the brief (about $0.49 for a one-word answer); `haiku` spends the same tokens for under a cent. Briefs should be few and full rather than many and small.

Not yet verified: nothing the design relies on. Rerun the probe when either CLI updates; it exits non-zero if any expectation fails.

## Left to the builder

Exact CLI flags per adapter; the JSON schemas for readings, reveals, attempts and dispute answers; brief wording; ledger event names and fields; where worktrees live on disk; how mutants are represented (a full copy of each changed file is more robust than a patch); how the conductor moves main when the human has main checked out (fast-forward in place when clean, otherwise park the result on a branch and say so); retry and cleanup behavior on Windows file locks; module layout.

## After v0

Two or more tasks in flight with crossed roles, path leases, and separate ports, temp directories and test databases. Experiments as a dispute step. Assumptions as first-class claims: flip one, amend the probes, rerun every crossing, reopen what fails. A scoreboard of which seat should build what. A live view. More seats.
