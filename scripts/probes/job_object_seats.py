"""Probe: do both seat CLIs still work when launched through parallax.procs.run_command?

run_command (Task 8) starts every process suspended inside a Windows Job Object that kills the
whole tree on timeout or exit, and does not allow breakaway. A program that creates a child with
CREATE_BREAKAWAY_FROM_JOB then fails to start it. Codex's Windows sandbox launches commands as
another user; if it needs breakaway, every sandboxed command would fail under the conductor.
This checks a sandboxed Codex command and a Claude file edit, each run through run_command.

Cost: one tiny Codex prompt and one tiny Claude (haiku) prompt.
Side effects: a private folder under ~/.parallax-probe, removed at the end; Codex adds a trust
entry for it to ~/.codex/config.toml.

Usage:
    python scripts/probes/job_object_seats.py
"""
import json
import os
import shutil
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from parallax import folders, gitops  # noqa: E402
from parallax.procs import run_command  # noqa: E402

_SCRUB = ("CLAUDE", "ANTHROPIC", "OPENAI", "CODEX")
_KEEP = {"claude": {"ANTHROPIC_API_KEY"}, "codex": {"OPENAI_API_KEY", "CODEX_HOME"}}


def seat_env(kind: str) -> dict[str, str]:
    return {k: v for k, v in os.environ.items()
            if not k.upper().startswith(_SCRUB) or k.upper() in _KEEP[kind]}


def main() -> int:
    codex, claude = shutil.which("codex"), shutil.which("claude")
    if not codex or not claude:
        print(f"missing CLI: codex={codex} claude={claude}")
        return 1
    parent = Path.home() / ".parallax-probe"
    task = parent / ("plx-job-" + uuid.uuid4().hex[:8])
    folders.make_private(task)
    failures = []
    try:
        repo = task / "repo"
        repo.mkdir()
        (repo / "README.md").write_text("job probe\n")
        gitops.git(repo, "init", "-q", "-b", "main")
        gitops.git(repo, "add", "-A")
        gitops.git(repo, "-c", "user.name=probe", "-c", "user.email=probe@example.invalid",
                   "commit", "-q", "-m", "fixture")
        seat = task / "seat"
        gitops.clone_at(repo, seat, "HEAD")

        r = run_command([codex, "exec", "-m", "gpt-6.2-astra", "-c", 'model_reasoning_effort="low"',
                         "--ignore-user-config", "-c", 'windows.sandbox="elevated"',
                         "--sandbox", "workspace-write", "-C", str(seat), "--ephemeral",
                         "--color", "never", "--json", "-"],
                        seat, 300, env=seat_env("codex"),
                        input="Run this PowerShell once, then reply with only the word done: "
                              "whoami; [System.IO.File]::WriteAllText((Join-Path (Get-Location) 'job.txt'), 'hi')")
        commands = []
        for line in r.output.splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            item = row.get("item") or {}
            if row.get("type") == "item.completed" and item.get("type") == "command_execution":
                commands.append((item.get("exit_code"), str(item.get("aggregated_output")).strip()[:120]))
        print(f"codex: exit {r.code}, timed out {r.timed_out}, commands {commands}")
        ok = r.code == 0 and any(code == 0 and "codexsandbox" in out.lower() for code, out in commands) \
            and (seat / "job.txt").exists()
        print(f"  [{'ok  ' if ok else 'FAIL'}] sandboxed command ran inside the job")
        if not ok:
            failures.append("codex")
            print("  output tail:", r.output[-800:].replace("\n", " | "))

        r = run_command([claude, "-p", "--model", "haiku", "--safe-mode", "--restricted",
                         "--tools", "Write", "--permission-mode", "acceptEdits", "--permission-prompts", "none",
                         "--no-session-persistence", "--output-format", "json"],
                        seat, 300, env=seat_env("claude"),
                        input="Create a file named claude_job.txt in the current directory containing exactly: hi. "
                              "Then reply with only the word done.")
        print(f"claude: exit {r.code}, timed out {r.timed_out}")
        ok = r.code == 0 and (seat / "claude_job.txt").exists()
        print(f"  [{'ok  ' if ok else 'FAIL'}] file edit worked inside the job")
        if not ok:
            failures.append("claude")
            print("  output tail:", r.output[-800:].replace("\n", " | "))
    finally:
        # Remove only the folder this run created, and only if it is where we made it.
        assert task.parent == parent and task.name.startswith("plx-job-"), task
        print(f"removed probe folder: {gitops.remove_tree(task)}")
    print(f"{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
