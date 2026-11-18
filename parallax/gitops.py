"""Every git operation Parallax performs: seat clones, snapshots, combining work, landing on main.

Seats never run git; the conductor does all of it through this module.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import time
from pathlib import Path
from typing import Sequence

# Internal commits (seat snapshots) are made as this identity and never reach main.
_INTERNAL = ("-c", "user.name=Parallax", "-c", "user.email=parallax@localhost", "-c", "commit.gpgsign=false")


class GitError(RuntimeError):
    """A git command failed. `stderr` holds what git said."""

    def __init__(self, message: str, stderr: str = ""):
        super().__init__(message)
        self.stderr = stderr


class MainMoved(GitError):
    """The main branch is no longer where the task expected it to be."""


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _run(cwd: Path, args: Sequence[str], input: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, env=_env(),
                          input=None if input is None else input.encode("utf-8"),
                          stdin=subprocess.DEVNULL if input is None else None)


def _check(done: subprocess.CompletedProcess, args: Sequence[str]) -> bytes:
    if done.returncode != 0:
        stderr = done.stderr.decode("utf-8", errors="replace").strip()
        raise GitError(f"git {' '.join(args)} failed ({done.returncode}): {stderr}", stderr)
    return done.stdout


def _raw(cwd: Path, *args: str, input: str | None = None) -> bytes:
    return _check(_run(cwd, args, input), args)


def git(cwd: Path, *args: str) -> str:
    """Run git in `cwd` and return its stdout, stripped. GitError carrying stderr on non-zero exit."""
    return _raw(Path(cwd), *args).decode("utf-8", errors="replace").strip()


def rev(repo: Path, ref: str = "HEAD") -> str:
    return git(repo, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}")


def show_file(repo: Path, ref: str, path: str) -> str | None:
    """The file's text at `ref`, exactly as stored; None when the path does not exist there."""
    sha = rev(repo, ref)  # a bad ref is an error, not a missing file
    done = _run(Path(repo), ["cat-file", "blob", f"{sha}:{path}"])
    if done.returncode != 0:
        return None
    return done.stdout.decode("utf-8", errors="replace")


def identity(repo: Path) -> tuple[str, str]:
    """(user.name, user.email) as git resolves them in `repo`. GitError if either is unset."""
    values = []
    for key in ("user.name", "user.email"):
        try:
            value = git(repo, "config", "--get", key)
        except GitError as exc:
            raise GitError(f"git {key} is not set in {repo}; set it with: git config {key} ...",
                           exc.stderr) from None
        if not value:
            raise GitError(f"git {key} is empty in {repo}")
        values.append(value)
    return values[0], values[1]


def clone_at(repo: Path, dest: Path, ref: str) -> None:
    """Clone `repo` into `dest`, detached at `ref`, with no remote and no line-ending conversion."""
    repo, dest = Path(repo), Path(dest)
    sha = rev(repo, ref)
    # --no-hardlinks: a local clone otherwise hardlinks object files to the human's repo, so
    # permission changes Codex makes on its clone would reach those shared files.
    git(repo, "clone", "--quiet", "--no-checkout", "--no-hardlinks", "-c", "core.autocrlf=false", str(repo), str(dest))
    git(dest, "checkout", "--quiet", "--detach", sha)
    git(dest, "remote", "remove", "origin")


def remove_tree(path: Path) -> bool:
    """Delete a folder and everything in it. True when gone; False if still locked after 5 seconds. Never raises."""
    def writable_then_retry(func, target, _exc):
        # git marks pack files read-only on Windows.
        os.chmod(target, stat.S_IWRITE)
        func(target)

    path = Path(path)
    deadline = time.monotonic() + 5
    while True:
        try:
            if not os.path.lexists(path):
                return True
            if path.is_symlink() or path.is_junction():
                try:  # remove the link, never its target
                    os.unlink(path)
                except OSError:
                    os.rmdir(path)
            elif path.is_dir():
                shutil.rmtree(path, onexc=writable_then_retry)
            else:
                os.chmod(path, stat.S_IWRITE)
                path.unlink()
        except Exception:
            pass
        try:
            if not os.path.lexists(path):
                return True
        except Exception:
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)


def changed_paths(clone: Path) -> list[str]:
    """Paths that differ from HEAD: modified, deleted and untracked. Relative, forward slashes."""
    out = _raw(Path(clone), "status", "--porcelain=v1", "-z", "--untracked-files=all")
    entries = out.decode("utf-8", errors="replace").split("\0")
    paths: list[str] = []
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        code, rel = entry[:2], entry[3:]
        paths.append(rel)
        if "R" in code or "C" in code:
            # A rename or copy is followed by the path it came from.
            if i < len(entries) and entries[i]:
                if "R" in code:
                    paths.append(entries[i])
                i += 1
    return list(dict.fromkeys(paths))


_CHANGES = {"A": "add", "D": "delete", "M": "modify", "T": "modify"}


def delta(repo: Path, base: str, head: str | None = None) -> dict[str, str]:
    """Net change from `base` to `head` (a commit), or to the index when `head` is None.

    {relative path, forward slashes: "add" | "modify" | "delete"}. A rename is a delete plus an
    add; a mode-only change is "modify"; a file added and removed again is absent.
    """
    args = ["diff", *(["--cached"] if head is None else []), "--name-status", "--no-renames", "-z",
            base, *([head] if head is not None else []), "--"]
    out = _raw(Path(repo), *args).decode("utf-8", errors="replace").split("\0")
    changes: dict[str, str] = {}
    for i in range(0, len(out) - 1, 2):
        changes[out[i + 1]] = _CHANGES.get(out[i][:1], "modify")
    return changes


def snapshot(clone: Path, message: str, exclude: Sequence[str] = ()) -> str | None:
    """Commit everything in `clone` except the excluded top-level folders. None when there is nothing to commit."""
    clone = Path(clone)
    pathspec = [":/", *(f":(top,exclude){name}" for name in exclude)]
    git(clone, "add", "-A", "--", *pathspec)
    if _run(clone, ["diff", "--cached", "--quiet"]).returncode == 0:
        return None
    _raw(clone, *_INTERNAL, "commit", "--quiet", "--no-verify", "-F", "-", input=message)
    return rev(clone)


def fetch(into: Path, source: Path, sha: str) -> None:
    git(into, "fetch", "--quiet", str(source), sha)


def apply_range(clone: Path, base: str, head: str) -> None:
    """Stage the changes of base..head on top of what is already staged, without committing.

    On a conflict, the index and working tree are put back exactly as they were and GitError is raised.
    """
    clone = Path(clone)
    tree = git(clone, "write-tree")
    try:
        git(clone, *_INTERNAL, "cherry-pick", "--no-commit", f"{base}..{head}")
    except GitError as exc:
        _run(clone, ["cherry-pick", "--abort"])
        git(clone, "read-tree", "-u", "--reset", tree)
        raise GitError(f"changes {base[:12]}..{head[:12]} do not apply cleanly: {exc}", exc.stderr) from None


def commit_staged(clone: Path, message: str, author: tuple[str, str]) -> str:
    """An ordinary commit of what is staged (hooks and signing as the human configured them)."""
    name, email = author
    _raw(Path(clone), "-c", f"user.name={name}", "-c", f"user.email={email}",
         "commit", "--quiet", "-F", "-", input=message)
    return rev(clone)


def advance_main(repo: Path, main: str, source: Path, new: str, expected_old: str, park_branch: str) -> str:
    """Move `main` in the human's repo from `expected_old` to `new`, fetched from `source`.

    Returns "advanced", or "parked" when `main` is checked out and the human's
    uncommitted edits are in the way; then `new` is left on `park_branch` and
    their edits are untouched. Raises MainMoved if `main` is not at `expected_old`.
    """
    repo = Path(repo)
    fetch(repo, source, new)
    if rev(repo, main) != expected_old:
        raise MainMoved(f"{main} moved: expected {expected_old[:12]}, found {rev(repo, main)[:12]}")
    head = _run(repo, ["symbolic-ref", "--quiet", "HEAD"])
    current = head.stdout.decode("utf-8", errors="replace").strip() if head.returncode == 0 else None
    if current == f"refs/heads/{main}":
        try:
            git(repo, "merge", "--ff-only", "--quiet", new)
        except GitError:
            git(repo, "branch", "--force", park_branch, new)
            return "parked"
        return "advanced"
    try:
        git(repo, "update-ref", f"refs/heads/{main}", new, expected_old)
    except GitError:
        if rev(repo, main) != expected_old:
            raise MainMoved(f"{main} moved while it was being advanced") from None
        raise
    return "advanced"
