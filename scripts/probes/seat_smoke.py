"""Probe: can both agent CLIs do what Parallax needs, headless, on this machine?

The design (docs/superpowers/specs/2026-11-16-parallax-design.md) lists
behaviors it relies on but had not verified. This script checks each one
against the real CLIs and prints what it found, so the build plan can name
exact flags and event shapes instead of guessing. Rerun it when either CLI
updates.

Cases (run all, or name some on the command line):
  claude_auth      is the standalone CLI signed in (with and without our env)?
  codex_env        which tools a sandboxed Codex command can see, per sandbox mode
  codex_acl        which folder permissions let a Codex seat work, stay blind,
                   and leave files this account can read
  claude_schema    structured output via --json-schema; shape of the result
  claude_confined  unattended edits in cwd with file tools only; reads outside
                   the folder refused; no shell tool available
  claude_resume    a second headless call continues the first one's session
  codex_write      workspace-write in a git worktree outside the repo, with
                   --output-schema; can it read or write another worktree?
  codex_resume     `codex exec resume` continues a session headless
  together         both CLIs running at the same moment

Cost: a handful of tiny prompts on each subscription.
Side effects:
- A fixture folder per run (path printed at the end). `--clean` removes them all.
- Persisted sessions for the two resume cases, which the script removes
  (`codex delete --force`, `claude purge -y` on the temp worktree).
- Codex appends a `[projects.'<folder>'] trust_level = "trusted"` entry to the
  human's ~/.codex/config.toml for every new folder it runs in, even with
  --ignore-user-config. This probe does not remove those.

Usage:
    python scripts/probes/seat_smoke.py [case ...]
    python scripts/probes/seat_smoke.py --clean
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

CLAUDE = shutil.which("claude")
CODEX = shutil.which("codex")
CODEX_PIN = ["-m", "gpt-6-astra", "-c", 'model_reasoning_effort="low"']
# Finding (2026-11-16): --ignore-user-config alone drops `[windows] sandbox =
# "elevated"`, after which every command is "rejected: blocked by policy".
# Re-supplying that one key keeps the seat lean and able to run commands.
CODEX_LEAN = ["--ignore-user-config", "-c", 'windows.sandbox="elevated"']
_SCRUB_PREFIXES = ("CLAUDE", "ANTHROPIC", "OPENAI", "CODEX")
_KEEP = {"claude": {"ANTHROPIC_API_KEY"}, "codex": {"OPENAI_API_KEY", "CODEX_HOME"}}


def seat_env(kind: str) -> dict[str, str]:
    """Environment for a seat: ours minus other agents' variables.

    Finding (2026-11-16): launched from inside a Claude Code desktop session, a
    nested `claude -p` inherits host-auth variables and fails with "OAuth
    session expired and could not be refreshed". The same inherited set also
    carries the account email, which a Codex seat has no business seeing.
    """
    return {k: v for k, v in os.environ.items()
            if not k.upper().startswith(_SCRUB_PREFIXES) or k.upper() in _KEEP[kind]}


@dataclass
class Fixture:
    root: Path
    repo: Path
    wt_a: Path
    wt_b: Path
    secret: Path
    out: Path
    canary: str


@dataclass
class Result:
    name: str
    code: int
    out: str
    err: str
    secs: float


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def lock_down(path: Path) -> None:
    """Give an empty folder a protected ACL naming only this account, SYSTEM and Administrators.

    Finding (2026-11-16), which this recipe answers:
    - A folder that merely inherits the profile's ACL is READABLE by Codex's
      sandbox user, so one seat could read the other seat's folder.
    - A folder with an owner-only ACL (what tempfile.mkdtemp makes) is not
      readable by the sandbox, but files the sandbox creates in its own such
      folder are then unreadable and undeletable by this account.
    Naming this account explicitly, inheritably, and nobody else, gives both:
    the other seat's folder is closed to the sandbox, and whatever the sandbox
    writes in its own folder (to which Codex adds its own entries) stays ours.
    """
    if os.name != "nt":
        return
    me = subprocess.run(["whoami"], capture_output=True, text=True, check=True).stdout.strip()
    subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{me}:(OI)(CI)F",
                    "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F"],
                   capture_output=True, text=True, check=True)


def make_fixture() -> Fixture:
    # PARALLAX_SMOKE_ROOT lets the fixture live where real seat clones will
    # (for example %LOCALAPPDATA%\parallax), to check the sandbox there too.
    #
    # Finding (2026-11-16): tempfile.mkdtemp gives the folder an owner-only
    # ACL on Windows. Files that Codex's sandbox user then creates inside it
    # are owned by that user, and this account can neither read nor delete
    # them. A folder made with plain mkdir inherits the profile's ACL, which
    # names this account explicitly. So: mkdtemp by default (to keep showing
    # the trap), plain mkdir when PARALLAX_SMOKE_ROOT is set.
    parent = os.environ.get("PARALLAX_SMOKE_ROOT")
    if parent:
        Path(parent).mkdir(parents=True, exist_ok=True)
        root = Path(parent) / ("parallax-smoke-" + uuid.uuid4().hex[:8])
        root.mkdir()
    else:
        root = Path(tempfile.mkdtemp(prefix="parallax-smoke-"))
    repo = root / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "src" / "__init__.py").write_text("")
    (repo / "tests" / "__init__.py").write_text("")
    (repo / "README.md").write_text("smoke fixture\n")
    git(repo, "init", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=parallax-smoke", "-c", "user.email=smoke@example.invalid",
        "commit", "-m", "fixture")
    wt_a = root / "wt-a"
    wt_b = root / "wt-b"
    for wt in (wt_a, wt_b):
        wt.mkdir()
        if not os.environ.get("PARALLAX_SMOKE_NO_LOCK"):   # set it to reproduce the unlocked runs
            lock_down(wt)
    git(repo, "worktree", "add", "-b", "seat-a", str(wt_a))
    git(repo, "worktree", "add", "-b", "seat-b", str(wt_b))
    canary = "CANARY-" + uuid.uuid4().hex[:12]
    secret = wt_b / "SECRET.txt"
    secret.write_text(canary + "\n")
    out = root / "out"
    out.mkdir()
    return Fixture(root, repo, wt_a, wt_b, secret, out, canary)


def run(fx: Fixture, name: str, argv: list[str], cwd: Path, stdin_text: str,
        timeout: int = 420) -> Result:
    start = time.time()
    kind = "claude" if argv[0] == CLAUDE else "codex"
    try:
        proc = subprocess.run(argv, cwd=cwd, input=stdin_text, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=timeout,
                              env=seat_env(kind))
        code, out, err = proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired as exc:
        raw = exc.stdout or ""
        out = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
        code, err = -999, "TIMEOUT"
    (fx.out / f"{name}.stdout.txt").write_text(out, encoding="utf-8")
    (fx.out / f"{name}.stderr.txt").write_text(err, encoding="utf-8")
    result = Result(name, code, out, err, time.time() - start)
    print(f"\n=== {name}: exit {code} in {result.secs:.0f}s ===")
    return result


def jsonl(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return rows


def show(label: str, value, width: int = 320) -> None:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=True)
    text = text.replace("\r", " ").replace("\n", " | ")
    print(f"  {label}: {text[:width]}")


def show_claude_result(doc) -> None:
    if isinstance(doc, list):
        show("stdout is a JSON list of", [d.get("type") for d in doc if isinstance(d, dict)])
        doc = doc[-1] if doc else {}
    if not isinstance(doc, dict):
        show("stdout not a JSON object", str(doc))
        return
    show("keys", sorted(doc.keys()))
    for key in ("type", "subtype", "is_error", "result", "structured_output", "session_id",
                "num_turns", "total_cost_usd", "permission_denials"):
        if key in doc:
            show(key, doc[key])
    if "usage" in doc:
        show("usage", doc["usage"])
    if "modelUsage" in doc:
        show("modelUsage", doc["modelUsage"])


def summarize_claude_stream(rows: list[dict]) -> None:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get("type")) + ("/" + str(row["subtype"]) if "subtype" in row else "")
        counts[key] = counts.get(key, 0) + 1
    show("event types", counts)
    for row in rows:
        if row.get("type") == "system" and row.get("subtype") == "init":
            show("init keys", sorted(row.keys()))
            for key in ("model", "permissionMode", "tools", "cwd"):
                if key in row:
                    show(f"init.{key}", row[key])
        content = (row.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                show("tool_use", {"name": block.get("name"), "input": block.get("input")})
            elif block.get("type") == "tool_result":
                show("tool_result", {"is_error": block.get("is_error"),
                                     "content": str(block.get("content"))[:200]})
    for row in rows:
        if row.get("type") == "result":
            show_claude_result(row)


def summarize_codex_stream(rows: list[dict]) -> str | None:
    counts: dict[str, int] = {}
    thread_id = None
    for row in rows:
        item = row.get("item") or {}
        key = str(row.get("type")) + ("/" + str(item.get("type")) if item else "")
        counts[key] = counts.get(key, 0) + 1
        if row.get("type") == "thread.started":
            thread_id = row.get("thread_id")
    show("event types", counts)
    seen_item_keys: dict[str, list[str]] = {}
    for row in rows:
        item = row.get("item") or {}
        if row.get("type") != "item.completed" or not item:
            continue
        kind = str(item.get("type"))
        seen_item_keys.setdefault(kind, sorted(item.keys()))
        if kind == "command_execution":
            show("command", {"command": item.get("command"), "exit_code": item.get("exit_code"),
                             "status": item.get("status"),
                             "output": str(item.get("aggregated_output"))[:160]})
        elif kind == "agent_message":
            show("agent_message", str(item.get("text")))
        elif kind != "reasoning":
            show(f"item {kind}", item)
    show("item keys by type", seen_item_keys)
    for row in rows:
        if row.get("type") == "turn.completed":
            show("usage", row.get("usage"))
        if row.get("type") in ("error", "turn.failed"):
            show("ERROR event", row)
    return thread_id


def parse_json(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


# ----------------------------------------------------------------- cases

def claude_schema(fx: Fixture) -> None:
    schema = {"type": "object", "properties": {"answer": {"type": "string"}},
              "required": ["answer"], "additionalProperties": False}
    r = run(fx, "claude_schema",
            [CLAUDE, "-p", "--model", "fable", "--effort", "high", "--safe-mode",
             "--no-session-persistence", "--output-format", "json",
             "--json-schema", json.dumps(schema)],
            fx.wt_a, "Reply with answer set to the single word ok.")
    doc = parse_json(r.out)
    if doc is None:
        show("stdout", r.out)
        show("stderr", r.err)
    else:
        show_claude_result(doc)


def claude_confined(fx: Fixture) -> None:
    # Design after the first smoke run: seats run nothing, so the Claude seat
    # gets file tools only. Expect: the file is created, the read of the other
    # worktree is refused, and no shell tool is listed in the init event.
    prompt = (
        "Do these three things in order, then stop.\n"
        "1. Create a file named hello_claude.txt in the current directory containing exactly: hi\n"
        f"2. Try to read the file {fx.secret} and note whether you were allowed to.\n"
        "3. Try to run the shell command: whoami\n"
        "Then report one short line per step saying what happened."
    )
    r = run(fx, "claude_confined",
            [CLAUDE, "-p", "--model", "haiku", "--safe-mode", "--restricted",
             "--tools", "Read,Write,Edit,Glob,Grep",
             "--permission-mode", "acceptEdits", "--permission-prompts", "none",
             "--no-session-persistence", "--output-format", "stream-json", "--verbose"],
            fx.wt_a, prompt)
    hello = fx.wt_a / "hello_claude.txt"
    show("hello_claude.txt exists", hello.exists())
    if hello.exists():
        show("hello_claude.txt content", hello.read_text())
    show("canary leaked into stdout", fx.canary in r.out)
    rows = jsonl(r.out)
    if rows:
        summarize_claude_stream(rows)
    else:
        show("stdout", r.out)
        show("stderr", r.err)


def claude_resume(fx: Fixture) -> None:
    sid = str(uuid.uuid4())
    r1 = run(fx, "claude_resume_1",
             [CLAUDE, "-p", "--model", "haiku", "--safe-mode", "--session-id", sid,
              "--output-format", "json"],
             fx.wt_a, "Remember this word: pineapple. Reply with just: ok")
    d1 = parse_json(r1.out)
    show_claude_result(d1) if d1 is not None else show("stdout", r1.out + r1.err)
    r2 = run(fx, "claude_resume_2",
             [CLAUDE, "-p", "--model", "haiku", "--safe-mode", "--resume", sid,
              "--output-format", "json"],
             fx.wt_a, "What word did I ask you to remember? Reply with just the word.")
    d2 = parse_json(r2.out)
    show_claude_result(d2) if d2 is not None else show("stdout", r2.out + r2.err)
    show("requested session id", sid)
    show("remembered", "pineapple" in r2.out.lower())


def codex_write(fx: Fixture) -> None:
    schema_path = fx.out / "codex_write.schema.json"
    schema_path.write_text(json.dumps({
        "type": "object",
        "properties": {"created": {"type": "boolean"}, "python_ran": {"type": "boolean"}},
        "required": ["created", "python_ran"],
        "additionalProperties": False}))
    last = fx.out / "codex_write.last.json"
    # This prompt used to ask Codex to read and write files in the OTHER seat's
    # folder, to test the sandbox. On 2026-11-16 OpenAI's safety system flagged
    # such prompts ("possible cybersecurity risk") and failed the turn. That is
    # a guardrail on the human's account, so the probe no longer asks a model
    # to cross a folder boundary. Isolation is judged from the folders'
    # permissions instead (see `principals` and the codex_acl case).
    prompt = (
        "Do these steps in order, then stop.\n"
        "1. Create a file named hello_codex.txt in the current directory containing exactly: hi\n"
        "2. Run: python -m unittest --help\n"
        "Answer in the required JSON. created: whether step 1 worked. "
        "python_ran: whether step 2 printed unittest's help."
    )
    r = run(fx, "codex_write",
            [CODEX, "exec", *CODEX_PIN, *CODEX_LEAN, "--sandbox", "workspace-write",
             "-C", str(fx.wt_a), "--ephemeral", "--color", "never", "--json",
             "--output-schema", str(schema_path), "-o", str(last), "-"],
            fx.wt_a, prompt)
    hello = fx.wt_a / "hello_codex.txt"
    show("hello_codex.txt exists", hello.exists())
    # The conductor must be able to commit and clean up what a seat wrote.
    try:
        show("this account can read what codex wrote", repr(hello.read_text(encoding="utf-8")))
    except OSError as exc:
        show("this account can read what codex wrote", f"NO: {exc}")
    try:
        hello.unlink()
        show("this account can delete what codex wrote", True)
    except OSError as exc:
        show("this account can delete what codex wrote", f"NO: {exc}")
    show("permissions on the seat's own folder", principals(fx.wt_a))
    show("permissions on the other folder", principals(fx.wt_b))
    show("last message file", last.read_text(encoding="utf-8") if last.exists() else "(missing)")
    rows = jsonl(r.out)
    if rows:
        summarize_codex_stream(rows)
    else:
        show("stdout", r.out)
    show("stderr tail", r.err[-600:])


def codex_resume(fx: Fixture) -> str | None:
    r1 = run(fx, "codex_resume_1",
             [CODEX, "exec", *CODEX_PIN, *CODEX_LEAN, "--sandbox", "workspace-write",
              "-C", str(fx.wt_a), "--color", "never", "--json", "-"],
             fx.wt_a, "Remember this word: pineapple. Reply with just: ok")
    thread_id = summarize_codex_stream(jsonl(r1.out))
    show("thread id", str(thread_id))
    if not thread_id:
        show("stderr tail", r1.err[-600:])
        return None
    last = fx.out / "codex_resume.last.txt"
    r2 = run(fx, "codex_resume_2",
             [CODEX, "exec", "resume", *CODEX_PIN, *CODEX_LEAN,
              "-c", 'sandbox_mode="workspace-write"', "--json", "-o", str(last), thread_id, "-"],
             fx.wt_a,
             "What word did I ask you to remember? Reply with just the word. "
             "Also create a file named resumed.txt in the current directory containing: yes")
    resumed_thread = summarize_codex_stream(jsonl(r2.out))
    show("resumed thread id", str(resumed_thread))
    show("last message", last.read_text(encoding="utf-8") if last.exists() else "(missing)")
    show("resumed.txt exists in wt-a", (fx.wt_a / "resumed.txt").exists())
    show("stderr tail", r2.err[-600:])
    return thread_id


def together(fx: Fixture) -> None:
    results: dict[str, Result] = {}

    def claude() -> None:
        results["claude"] = run(
            fx, "together_claude",
            [CLAUDE, "-p", "--model", "haiku", "--safe-mode", "--no-session-persistence",
             "--output-format", "json"],
            fx.wt_a, "Reply with just: ok")

    def codex() -> None:
        results["codex"] = run(
            fx, "together_codex",
            [CODEX, "exec", *CODEX_PIN, *CODEX_LEAN, "--sandbox", "read-only",
             "-C", str(fx.wt_b), "--ephemeral", "--color", "never", "--json", "-"],
            fx.wt_b, "Reply with just: ok")

    threads = [threading.Thread(target=claude), threading.Thread(target=codex)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for name, r in results.items():
        show(f"{name} exit / seconds", f"{r.code} / {r.secs:.0f}")


def claude_auth(fx: Fixture) -> None:
    """Is the standalone CLI signed in? Prints key names and a few safe fields only."""
    for label, env in (("scrubbed env", seat_env("claude")), ("inherited env", dict(os.environ))):
        done = subprocess.run([CLAUDE, "auth", "status", "--json"], capture_output=True,
                              text=True, env=env)
        doc = parse_json(done.stdout)
        if isinstance(doc, dict):
            show(f"{label}: keys", sorted(doc.keys()))
            show(f"{label}: safe fields", {k: v for k, v in doc.items() if k in (
                "loggedIn", "authMethod", "apiProvider", "subscriptionType", "tokenSource")})
        else:
            show(label, f"exit {done.returncode}: {done.stdout[:200]} {done.stderr[:200]}")


def codex_env(fx: Fixture) -> None:
    """What can a sandboxed Codex command see? Tool resolution decides whether a
    seat can run the project's check command at all."""
    python = shutil.which("python") or "python"
    script = (
        "whoami; "
        "Get-Command python,py,git,node,uv -ErrorAction SilentlyContinue | "
        "ForEach-Object { $_.Name + ' => ' + $_.Source }; "
        "'PATH entries: ' + ($env:PATH -split ';').Count; "
        "$env:PATH -split ';' | Where-Object { $_ -match 'Python|nvm|Git' }; "
        f"'python exe visible: ' + (Test-Path '{python}'); "
        f"'secret visible: ' + (Test-Path '{fx.secret}')"
    )
    prompt = ("Run this exact PowerShell command once, then reply with only the word done:\n"
              + script)
    variants = {
        "lean_readonly": [*CODEX_LEAN, "--sandbox", "read-only"],
        "lean_write": [*CODEX_LEAN, "--sandbox", "workspace-write"],
        "userconfig_write": ["--sandbox", "workspace-write"],
    }
    for label, flags in variants.items():
        r = run(fx, f"codex_env_{label}",
                [CODEX, "exec", *CODEX_PIN, *flags, "-C", str(fx.wt_a), "--ephemeral",
                 "--color", "never", "--json", "-"],
                fx.wt_a, prompt)
        for row in jsonl(r.out):
            item = row.get("item") or {}
            if row.get("type") == "item.completed" and item.get("type") == "command_execution":
                show("exit", item.get("exit_code"))
                show("output", str(item.get("aggregated_output")), width=1400)
        if r.err.strip():
            show("stderr tail", r.err[-300:])


def codex_acl(fx: Fixture) -> None:
    """Which folder permissions let a Codex seat work, stay blind, and leave files we can read?

    The other seat's folder is always locked down. The seat's own folder is a
    clone whose parent's permissions vary (see the comment in the loop).
    For each: can sandboxed commands start (and after how many tries), can the
    sandbox read the other folder, and can this account read and delete a file
    the sandbox created with a shell command?
    """
    schema_path = fx.out / "codex_acl.schema.json"
    schema_path.write_text(json.dumps({
        "type": "object",
        "properties": {"tries": {"type": "integer"}, "whoami": {"type": "string"},
                       "wrote": {"type": "boolean"}},
        "required": ["tries", "whoami", "wrote"],
        "additionalProperties": False}))
    # Findings so far (2026-11-16): a seat folder locked down directly, and a
    # non-git folder run with --skip-git-repo-check, both fail every command
    # with "CreateProcessWithLogonW failed: 267". So each variant below is a
    # real clone, and differs only in what its PARENT folder's permissions are:
    #   plain               parent inherits the profile's permissions
    #   inherit_locked      parent locked down (this account, SYSTEM, Administrators)
    #   inherit_owner_only  parent made with mode 0o700 (owner only), as mkdtemp does
    #
    # Under %LOCALAPPDATA%\parallax, clones failed with 267 whatever the parent's
    # permissions, though the folders' ACLs had the same shape as a working
    # worktree under %TEMP%. So a variant is now "<where>:<parent>:<kind>":
    #   where   temp | appdata      (%TEMP% or %LOCALAPPDATA%\parallax)
    #   parent  owner | plain | locked
    #   kind    worktree | clone
    #
    # Results (2026-11-16), each run once or twice:
    #   temp:owner:worktree, temp:owner:clone   commands run; the locked sibling was refused
    #                                           ("Access is denied"); but this account could
    #                                           not READ files the sandbox created (it could
    #                                           delete them)
    #   appdata:*                               every command fails with 267 (redirected folder)
    #   home:locked:clone, home:plain:clone     commands run; this account can read and
    #                                           delete what the sandbox created
    # The arrangement the design uses is therefore home:locked:clone, the default here.
    default = "home:locked:clone"
    wanted = os.environ.get("PARALLAX_SMOKE_ACL", default).split(",")
    for variant in wanted:
        where, parent_kind, kind = variant.split(":")
        # Finding (2026-11-16): the "appdata" failures were not about permissions.
        # Claude's desktop app is an MSIX package, and a process started from it
        # has new folders under %LOCALAPPDATA% redirected into the package's
        # private LocalCache. Codex's sandbox user, outside the package, is then
        # told to start in a folder that does not exist for it (error 267).
        # %TEMP% and the home folder are not redirected. "home" tests the latter.
        base = {"temp": Path(tempfile.gettempdir()),
                "appdata": Path(os.environ["LOCALAPPDATA"]) / "parallax",
                "home": Path.home() / ".parallax-probe"}[where]
        base.mkdir(parents=True, exist_ok=True)
        parent = base / ("plx-acl-" + uuid.uuid4().hex[:8])
        if parent_kind == "owner":
            os.mkdir(parent, 0o700)
        else:
            parent.mkdir()
        if parent_kind == "locked":
            lock_down(parent)
        own = parent / "own"
        if kind == "worktree":
            git(fx.repo, "worktree", "add", "-b", "acl-" + uuid.uuid4().hex[:6], str(own))
        else:
            subprocess.run(["git", "clone", "--quiet", "-c", "core.autocrlf=false", str(fx.repo), str(own)],
                           check=True, capture_output=True, text=True)
            git(own, "remote", "remove", "origin")
        other = base / (parent.name + "-other")
        other.mkdir()
        lock_down(other)
        print(f"\n--- variant {variant}: own = {own}")
        variant = variant.replace(":", "_")
        (own / "existing.txt").write_text("already here\n")
        # The model is not asked about `other` (see the note in codex_write).
        prompt = (
            "Do these steps in order, then stop.\n"
            "1. Run: whoami   If the command fails to start, run it again, up to 4 times in total.\n"
            "2. Run this PowerShell: [System.IO.File]::WriteAllText((Join-Path (Get-Location) "
            "'made_by_shell.txt'), 'hi')   If it fails to start, try it once more.\n"
            "3. Run: Get-Content existing.txt\n"
            "Answer in the required JSON. tries: how many times you ran whoami. whoami: its output, "
            "or the error. wrote: whether step 2 worked."
        )
        last = fx.out / f"codex_acl_{variant}.last.json"
        r = run(fx, f"codex_acl_{variant}",
                [CODEX, "exec", *CODEX_PIN, *CODEX_LEAN, "--sandbox", "workspace-write",
                 "-C", str(own), "--ephemeral", "--color", "never",
                 "--json", "--output-schema", str(schema_path), "-o", str(last), "-"],
                own, prompt)
        show("last message", last.read_text(encoding="utf-8") if last.exists() else "(missing)")
        for row in jsonl(r.out):
            item = row.get("item") or {}
            if row.get("type") == "item.completed" and item.get("type") == "command_execution":
                show("command exit / output", f"{item.get('exit_code')} / {str(item.get('aggregated_output'))[:90]}")
        made = own / "made_by_shell.txt"
        show("made_by_shell.txt exists", made.exists())
        if made.exists():
            try:
                show("this account can read it", repr(made.read_text(encoding="utf-8")))
            except OSError as exc:
                show("this account can read it", f"NO: {exc}")
            try:
                made.unlink()
                show("this account can delete it", True)
            except OSError as exc:
                show("this account can delete it", f"NO: {exc}")
        # Isolation, judged without a model: Codex adds its sandbox entries to the
        # folder it works in. A sibling that lists only this account, SYSTEM and
        # Administrators has no entry the sandbox user could use.
        show("permissions on the seat's own folder", principals(own))
        show("permissions on the other folder", principals(other))


def principals(path: Path) -> list[str]:
    """Who is named in a folder's ACL, as icacls prints them (Windows only)."""
    if os.name != "nt":
        return []
    done = subprocess.run(["icacls", str(path)], capture_output=True, text=True)
    names = []
    for line in done.stdout.splitlines():
        entry = line.replace(str(path), "").strip()
        if ":(" in entry:
            names.append(entry.split(":(")[0])
    return sorted(set(names))


def clean() -> int:
    """Remove every fixture this probe left behind, in all three locations it has used."""
    def force(func, path, _exc):
        os.chmod(path, stat.S_IWRITE)
        func(path)

    bases = [Path(tempfile.gettempdir()), Path(os.environ.get("LOCALAPPDATA", "")) / "parallax",
             Path.home() / ".parallax-probe"]
    removed = failed = 0
    for base in bases:
        if not base.is_dir():
            continue
        for item in list(base.glob("parallax-smoke-*")) + list(base.glob("plx-acl-*")):
            shutil.rmtree(item, onerror=force) if item.is_dir() else None
            if item.exists():
                failed += 1
                print(f"  could not remove {item}")
            else:
                removed += 1
        if base != bases[0] and base.is_dir() and not any(base.iterdir()):
            base.rmdir()
    print(f"removed {removed} leftover fixture folder(s); {failed} could not be removed")
    return 1 if failed else 0


CASES = {
    "claude_auth": claude_auth,
    "codex_acl": codex_acl,
    "codex_env": codex_env,
    "claude_schema": claude_schema,
    "claude_confined": claude_confined,
    "claude_resume": claude_resume,
    "codex_write": codex_write,
    "codex_resume": codex_resume,
    "together": together,
}


def main() -> int:
    if sys.argv[1:] == ["--clean"]:
        return clean()
    wanted = sys.argv[1:] or list(CASES)
    unknown = [name for name in wanted if name not in CASES]
    if unknown:
        print(f"unknown case(s): {unknown}; choose from {list(CASES)}")
        return 2
    if not CLAUDE or not CODEX:
        print(f"missing CLI: claude={CLAUDE} codex={CODEX}")
        return 1
    fx = make_fixture()
    print(f"fixture: {fx.root}")
    inherited = sorted(k for k in os.environ if k.upper().startswith(("CLAUDE", "CODEX", "ANTHROPIC", "OPENAI")))
    print(f"agent-related env var names inherited by seats: {inherited}")
    codex_thread = None
    for name in wanted:
        try:
            value = CASES[name](fx)
            if name == "codex_resume":
                codex_thread = value
        except Exception as exc:  # keep going: one broken case must not hide the rest
            print(f"  CASE CRASHED: {type(exc).__name__}: {exc}")
    print("\n=== cleanup ===")
    if codex_thread:
        done = subprocess.run([CODEX, "delete", "--force", codex_thread],
                              capture_output=True, text=True)
        show("codex delete", f"exit {done.returncode} {done.stdout.strip()} {done.stderr.strip()}")
    if "claude_resume" in wanted:
        done = subprocess.run([CLAUDE, "purge", "-y", str(fx.wt_a)], capture_output=True, text=True)
        show("claude purge", f"exit {done.returncode} {done.stdout.strip()} {done.stderr.strip()}")
    print(f"\nraw output kept in: {fx.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
