"""Private folders: the only permissions on a task's folder in the state home.

Findings (2026-11-16) behind the recipe, from `scripts/probes/seat_smoke.py`:
- A folder that merely inherits the profile's ACL is readable by Codex's sandbox
  user, so one seat could read the other seat's folder.
- An owner-only folder (what `tempfile.mkdtemp` or mode 0o700 makes on Windows) is
  closed to the sandbox, but files the sandbox creates in it cannot be read by the
  human's account.
Naming this account, SYSTEM and Administrators explicitly and inheritably, and
nobody else, gives both.
"""
from __future__ import annotations

import csv
import functools
import os
import re
import subprocess
import uuid
from pathlib import Path

SYSTEM_SID = "S-1-5-18"
ADMINISTRATORS_SID = "S-1-5-32-544"
# SDDL trustees accepted in a private folder besides the current account:
# SYSTEM, Administrators, OWNER RIGHTS, CREATOR OWNER (aliases and SIDs).
_ALLOWED = {"SY", SYSTEM_SID, "BA", ADMINISTRATORS_SID, "OW", "S-1-3-4", "CO", "S-1-3-0"}
_DENY_TYPES = {"D", "OD", "XD"}


def make_private(path: Path) -> None:
    """Create `path` (and its parents) so that only this account, SYSTEM and Administrators may use it.

    Raises FileExistsError if `path` already exists: an existing folder may already
    hold things that were readable before it was locked down.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        path.mkdir(mode=0o700)
        os.chmod(path, 0o700)
        return
    path.mkdir()
    try:
        _run(["icacls", str(path), "/inheritance:r", "/grant:r", f"*{_current_sid()}:(OI)(CI)F",
              f"*{SYSTEM_SID}:(OI)(CI)F", f"*{ADMINISTRATORS_SID}:(OI)(CI)F"])
    except BaseException:
        # Never leave behind a folder that exists but is not private.
        try:
            path.rmdir()
        except OSError:
            pass
        raise


def is_private(path: Path) -> bool:
    """True when the folder's permissions allow nobody but this account, SYSTEM and Administrators."""
    path = Path(path)
    if not path.is_dir():
        return False
    if os.name != "nt":
        return path.stat().st_mode & 0o077 == 0
    dacl = _dacl(path)
    if dacl is None:
        return False
    mine = _own_trustees(_current_sid())
    for ace in re.findall(r"\(([^)]*)\)", dacl):
        fields = ace.split(";")
        if len(fields) < 6:
            return False
        kind, trustee = fields[0], fields[5]
        if kind in _DENY_TYPES:
            continue
        if trustee not in mine and trustee not in _ALLOWED:
            return False
    return True


def _own_trustees(sid: str) -> set[str]:
    """The ways SDDL may write this account: its SID, or `LA` when it is the built-in Administrator.

    SDDL prints the machine's built-in Administrator account (relative id 500) as the alias
    `LA`, not as its SID. Without this a folder made private by that account, as on a
    GitHub Actions Windows runner, would never read as private (found 2026-11-24).
    """
    return {sid, "LA"} if re.fullmatch(r"S-1-5-21-\d+-\d+-\d+-500", sid) else {sid}


def _dacl(path: Path) -> str | None:
    """The folder's DACL in SDDL, read with `icacls /save` so it does not depend on the display language."""
    # Saved beside the folder, not in %TEMP%: Parallax keeps every file it writes in the
    # project or the state home.
    saved = path.parent / f".{path.name}.acl-{uuid.uuid4().hex[:8]}.txt"
    try:
        _run(["icacls", str(path), "/save", str(saved)])
        text = saved.read_bytes().decode("utf-16-le", errors="replace").lstrip("﻿")
    finally:
        saved.unlink(missing_ok=True)
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return None
    # Line 1 is the folder's name, line 2 its security descriptor.
    match = re.search(r"D:([A-Z]*)((?:\([^)]*\))*)", lines[1])
    if not match or "NO_ACCESS_CONTROL" in lines[1]:
        return None
    return match.group(2)


@functools.lru_cache(maxsize=1)
def _current_sid() -> str:
    out = _run(["whoami", "/user", "/fo", "csv", "/nh"])
    rows = [row for row in csv.reader(out.splitlines()) if row]
    sid = rows[0][-1].strip() if rows else ""
    if not sid.startswith("S-1-"):
        raise RuntimeError(f"could not read the current account's SID from whoami: {out!r}")
    return sid


def _run(args: list[str]) -> str:
    done = subprocess.run(args, capture_output=True, stdin=subprocess.DEVNULL)
    out = done.stdout.decode("utf-8", errors="replace")
    if done.returncode != 0:
        err = done.stderr.decode("utf-8", errors="replace").strip() or out.strip()
        raise OSError(f"{args[0]} failed ({done.returncode}): {err}")
    return out
