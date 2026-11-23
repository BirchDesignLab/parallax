# Concepts

The idea behind Parallax, the alternatives it was chosen over, and the terms the rest of the documentation uses.

## The problem

An agent that writes a change and then tests it is checking its own understanding against itself. If it misread the task, the code and the tests share the misreading, and the run is green. A second copy of the same model helps less than it seems to: it tends to misread in the same place.

Asking a human to review everything does not scale, and asking a human to carry prompts between two agents turns the human into the integration layer.

## The idea

Two different models make less correlated mistakes than two copies of one. Parallax uses that in one specific way. It does not give each agent half of the project. It splits every task into two sides:

- One seat, the **builder**, writes the change.
- The other seat, the **challenger**, writes the checks that will judge it, from a frozen contract, without ever seeing the builder's code.

The two outputs meet for the first time at the **crossing**. If independently written checks pass on independently written code, that agreement is evidence the change does what the contract says. If they do not, the failure is specific: a probe, an input, an expected and an actual result.

The name is the astronomer's method. One object seen from two positions appears to shift against the background, and the size of the shift is information you cannot get from either position alone.

## Why a green run means something here

A check that could never have failed proves nothing. Parallax makes the checks earn their result twice:

1. **They are written blind.** The challenger works from the contract alone, so its probes cannot be shaped around what the code happens to do.
2. **They are shown able to fail.** The builder also writes a small number of **mutants**: deliberately broken copies of the change. At the crossing the probes run against each mutant, and every mutant must fail. A mutant that survives is evidence the probes are too weak, and it goes back as a dispute.

## Only disagreement reaches you

Before any code is written, each seat writes down how it reads the task, alone. The readings are hashed, then revealed, and each seat reviews the other's. Where they agree, nothing is asked. Where they still differ after the settlement step, you get a card with both answers, both reasons, and a concrete case on which the answers produce different results.

That is the only routine interruption. You are not asked to approve merges, relay messages or resolve conflicts. A ruling can be scoped to the whole project, in which case it becomes a precedent and the question is not asked again while its conditions hold.

## Approaches it was chosen over

| Approach | What it is | Why not |
|---|---|---|
| Foreman | One agent plans, both execute separate tasks, changes are merged | Most throughput, but every change is still checked only by its author, and separate tasks collide in shared files |
| Tournament | Both agents build every task and the better result wins | Good for hard problems, but pays twice for one result |
| Hotline | Two live sessions message each other | Chatty, and each agent's view contaminates the other's |
| **Parallax** | Builder and blind challenger on every task, evidence-only disputes, rulings that persist | Chosen. The second agent's work is the tests, which have to be written anyway, so little is paid twice |

Both models picked this approach independently when each wrote a proposal without seeing the other's.

## What would make it a failure

The design names the ways it could run and still be worthless. They explain most of its rules:

- Agents talk to each other freely, anchor on each other, and the independence is gone. So seats never message each other; everything one learns about the other arrives from the conductor.
- A model acts as manager. So the conductor is ordinary code with no model in it.
- A green run is called agreement when the checks could not have failed. So mutants.
- The human carries prompts between agents or resolves merges by hand. So the conductor does all git work and prints cards that end with the command that answers them.
- An agent writes outside its assigned paths and nobody notices. So every changed path is checked against the role's patterns and against the inventory the seat declared.

## Terms

| Term | Meaning |
|---|---|
| Seat | An agent CLI the conductor can launch. There are two: `claude` and `codex` |
| Conductor | The Python program that runs everything. It contains no model |
| Task | One change to make, described in a short spec file |
| Reading | A seat's written interpretation of a task, made before any code |
| Contract | The frozen interface and decisions both sides work from |
| Builder, challenger | The seat that writes the change, and the seat that writes the probes. They swap every task |
| Probe | An automated check written by the challenger from the contract alone |
| Mutant | A deliberately broken copy of the change. Probes must catch it |
| Crossing | The moment the builder's change and the challenger's probes first meet |
| Dispute | A disagreement backed by evidence |
| Ruling | The human's decision on a dispute |
| Precedent | A project-scoped ruling, kept and included in later briefs |
| Receipt | The verification summary stamped on the landing commit |
| Ledger | The append-only record of every event |

## See also

- [Documentation index](README.md)
- [The life of a task](life-of-a-task.md)
- [Rulings and precedents](rulings.md)
- [Receipts and the ledger](receipts.md)
- [Keeping the blind](blind.md)
- [Commands](cli.md)
- [parallax.toml](configuration.md)
- [Architecture](architecture.md)
- [Field notes](field-notes.md)
- [FAQ](faq.md)
