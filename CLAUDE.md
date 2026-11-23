# Parallax

A Python conductor that pairs two agent CLIs on one task: one builds, the other writes probes blind, and the result lands on main with a receipt. Spec: `docs/superpowers/specs/2026-11-16-parallax-design.md`. Build plan: `docs/superpowers/plans/2026-11-16-parallax-v0.md` (tick its checkboxes as tasks land).

## Where files go

Developer direction 2026-11-17, after parallel agents collided in shared temp folders and one wiped %TEMP%.

**Never write to %TEMP%, a session scratchpad, or any temp directory.** Everything stays in this repo:

| What | Home |
|---|---|
| Anything reusable: briefs, handoffs, decisions, findings | `docs/` (committed) |
| Scripts of any kind, including one-off probes and checks | `scripts/` in a subfolder (`scripts/probes/`), committed |
| Working scratch: command output dumps, agent working files, test-run folders, probe raw output | `.superpowers/` (ignored). Promote anything later work depends on into `docs/` first |

Each agent in a parallel fan-out writes scratch only under its own `.superpowers/agents/<label>/`. Tests need nothing special: `tests/__init__.py` points `tempfile` and `PARALLAX_HOME` at a per-run folder under `.superpowers/tmp/tests/` and removes it afterwards.

The one exception is by design, not scratch: Parallax's runtime state home is `~/.parallax` (spec, "Keeping the blind honest"), and `scripts/probes/` fixtures that test that layout live in `~/.parallax-probe`.

**Deleting:** never run a recursive delete (`shutil.rmtree`, `remove_tree`, `rm -rf`, `Remove-Item -Recurse`) on a path computed by walking up parents. Delete only a folder you created, after asserting its name prefix and its parent. Every brief and subagent prompt repeats this rule.

## Delegation

Work runs in rounds of plan tasks that do not depend on each other, with disjoint file ownership (no worktrees).

- **Codex:** the developer pastes briefs written to `docs/briefs/codex-task-<n>.md` into their Codex app. Present each brief in chat as a copy-paste block too. Recommend `gpt-6.2-astra` at `high` (developer ruling: design-grade Codex work is astra high or xhigh).
  - Codex's app runs in its default sandbox, as a separate Windows user: local `git clone` fails there and `folders.is_private` sees a different account, so any test that clones (gitops, crossing, conductor) fails for Codex though it passes for us. Every brief tells Codex: if tests fail with sandbox clone or permission errors, ask for elevated access and rerun them, rather than reporting the failures.
  - Developer ruling 2026-11-17: keep the default sandbox with per-command escalation for now; switching Codex to Full access (machine-wide, no prompts) is on the table if the escalation prompts get annoying.
  - Tasks whose tests Codex cannot run go to a Claude subagent instead (Task 9 did).
- **Claude subagents:** set `model` **and** `effort` on every dispatch; an unset agent inherits the session's model and effort, which is the expensive default. Fable is never a subagent model.
  - Sonnet 5.5 `medium`: one fully specified plan task with its tests.
  - Sonnet 5.5 `high`: a task heavy on Windows behavior or needing judgment across files.
  - Opus 5.5 `medium`: review or synthesis when the controller asks for a second read.
  - Haiku 5.5: listing, grepping, extracting.
- Every brief names the exact files the agent may create, forbids state-changing git, asks for exact test output and a list of choices the plan did not dictate, and carries the scratch and delete rules above.
- **The controller (the main Claude session)** reviews every task's code, fixes what it finds, ticks the plan, and makes one commit per task. Nobody else runs state-changing git.

## Working rules

- Python 3.12, standard library only. Tests: `python -m unittest discover -s tests -t . -v`.
- Remote: `origin` is `github.com/BirchDesignLab/parallax`, which will be public. Push only when the developer asks.
- Public hygiene (developer ruling 2026-11-23): commits are authored as `THobbs23` with the GitHub noreply address set in this repo's git config, never a personal email. No personal email, local account name or home-folder path in any tracked file: write `~` for the home folder.
- History was rewritten once, on 2026-11-23, before the first push (`scripts/history/`). A commit hash quoted in an old commit message may be a pre-rewrite hash: `docs/history/2026-11-23-commit-map.txt` maps old to new.
- After either CLI updates, rerun `python scripts/probes/seat_smoke.py` (exits non-zero on any failed expectation) and `python scripts/probes/job_object_seats.py`.
