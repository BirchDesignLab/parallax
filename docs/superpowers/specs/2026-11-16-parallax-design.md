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

In v0 the blind is arranged and audited, not guaranteed. Seats are treated as fallible, not hostile: the measures below stop an agent that wanders, not one that sets out to cheat, and no receipt claims more than that.

- **Placement.** Worktrees live outside the repo under random names. A seat is told only its own path.
- **Confinement.** Each seat is held as tightly as its CLI allows. Claude's file tools are restricted to its worktree and its shell is limited to an allowlist, by default only the project's check command. Codex runs in its `workspace-write` sandbox. Whether that sandbox can also refuse reads outside the worktree on Windows is not yet verified.
- **Seal.** Readings and attempts are hashed into the ledger before reveal, so nothing can be adjusted afterwards.
- **Audit.** Both CLIs emit an event stream of the commands and file reads a seat performed. After each attempt the conductor scans it for any path belonging to the other seat. This is best effort: a script that reads another worktree without naming it would get past.
- **Voiding.** A hit voids the attempt, and the contamination goes with it: the session, the worktree and everything the attempt produced are discarded. The rerun is a new session in a new worktree, starting from the contract alone.

Seats never message each other. Everything a seat learns about the other side arrives from the conductor at steps 3 and 8. A seat keeps one session for the length of a task, so a repair starts with its own context. The exceptions are a voided attempt, as above, and a new task, which always starts a new session.

### Who may write what

- Each role has path patterns in the project config, for example builder `src/**`, challenger `tests/**`. Files both would need (lockfiles, manifests) are listed as exclusive and belong to the builder for that task.
- Seats only edit files. The conductor does all git work: it checks every changed path against the seat's patterns, rejects the attempt if any falls outside, and makes the commits itself.
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

`.parallax/ledger.jsonl` in the project is the source of truth for decisions: readings, contracts, attempts, crossings, disputes, rulings, receipts. It is plain text so that either agent, the human, and git can all read it, and each integration commit includes the lines it added, so the history of decisions travels with the code. Logs, event streams and pending cards live in `.parallax/run/`, which git ignores.

Every step records its completion. `parallax run` works out the current step from the ledger, so a crash or a pause for a ruling resumes cleanly; an attempt that started but never finished is discarded and rerun.

### Seats

An adapter turns "run this brief in this folder and return output matching this schema" into a CLI invocation, and returns the parsed output, the session id, the event stream and the token usage. Model and effort are set explicitly on every launch and written to the ledger; the round-0 run showed Codex's event stream does not report them.

Seats launch without the human's personal plugins, hooks and MCP servers (`--safe-mode` for Claude, `--ignore-user-config` for Codex), so briefs are the only instructions and nothing else spends tokens.

A third adapter, `stub`, replays scripted outputs. The conductor's own tests use it, so the whole lifecycle is testable without spending a token.

### Project config

`parallax.toml` at the project root:

    [project]
    check = "python -m unittest discover -s tests"
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

- The v0 blind is arranged and audited, not guaranteed, and receipts say no more than that. Hard isolation (separate OS users or containers) is deferred.
- Main never receives a failing check; a limitation means amending the contract and probes first.
- The demo counts whether or not the two models happen to disagree.

## Verified and not yet verified

Verified on this machine during round 0:

- `codex exec` runs headless from a brief on stdin, read-only, with a JSONL event stream that lists every command it ran, which is what the audit needs.
- Without `-m`, Codex inherits the model and effort from `~/.codex/config.toml`: a flagless run reports `model: gpt-6-astra` and `reasoning effort: xhigh` in its startup header. `-m` with `-c model_reasoning_effort=...` pins both. Runs started with `--ephemeral` leave no local record of the model, so the conductor must log what it pinned.
- Two `codex exec` processes ran at the same time without trouble.
- Codex's Windows sandbox failed to start one process (`CreateProcessWithLogonW failed: 1056`) and recovered. Adapters must tolerate a transient launch failure.
- On Windows a file named `claude.md` is loaded by Claude Code as `CLAUDE.md`, that is, as instructions. Nothing the framework writes may be named after an agent's instruction file.

Not yet verified, and the first thing to test before building on it:

- Claude headless editing files unattended with `--safe-mode`, `--json-schema`, file tools restricted to the worktree, and a shell allowlist holding only the check command.
- Whether Codex's Windows sandbox can refuse reads outside its worktree.
- Codex writing files under `workspace-write` in a worktree outside the repo, with `--output-schema`.
- The shape of each CLI's event stream for file reads, as the audit needs.
- Resuming a session headless for a repair, on both CLIs.
- Both CLIs running at the same moment.

## Left to the builder

Exact CLI flags per adapter; the JSON schemas for readings, reveals, attempts and dispute answers; brief wording; ledger event names and fields; where worktrees live on disk; how mutants are represented (a full copy of each changed file is more robust than a patch); how the conductor moves main when the human has main checked out (fast-forward in place when clean, otherwise park the result on a branch and say so); retry and cleanup behavior on Windows file locks; module layout.

## After v0

Two or more tasks in flight with crossed roles, path leases, and separate ports, temp directories and test databases. Experiments as a dispute step. Assumptions as first-class claims: flip one, amend the probes, rerun every crossing, reopen what fails. A scoreboard of which seat should build what. A live view. More seats.
