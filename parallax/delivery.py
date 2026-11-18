"""Delivery accounting: a seat's declared list of files against what it actually changed.

Every landed seat change matched its accepted inventory; relevance is not independently
reviewed. A seat that lists a file nobody needs still lands it; a seat that changes a file
without listing it, or lists one it did not change, is sent back.
"""
from __future__ import annotations

import re

RESERVED = (".parallax/", ".parallax-mutants/", ".parallax-scratch/")
CLAIM = "Every landed seat change matched its accepted inventory; relevance is not independently reviewed."

_DRIVE = re.compile(r"^[A-Za-z]:")


def bad_path(path: str) -> bool:
    """Not a plain relative path with forward slashes."""
    if not path or "\\" in path or path.startswith("/") or _DRIVE.match(path):
        return True
    return any(segment in ("", ".", "..") for segment in path.split("/"))


def _reserved(path: str) -> bool:
    return path.startswith(RESERVED)


def check(files: list[dict], actual: dict[str, str]) -> list[str]:
    """Why the declared `files` do not match `actual` (the real net delta). Empty means they match."""
    reasons: list[str] = []
    declared: dict[str, str] = {}              # path -> declared change
    seen: set[str] = set()                     # lower-cased valid paths
    for row in files:
        path = row.get("path", "")
        if bad_path(path):
            reasons.append(f"bad path in files: {path}")
            continue
        if _reserved(path):
            reasons.append(f"{path} is a Parallax working file or record, not a deliverable")
            continue
        if path.lower() in seen:
            reasons.append(f"{path} is listed more than once in files")
            continue
        seen.add(path.lower())
        declared[path] = row.get("change", "")
        if not str(row.get("purpose", "")).strip():
            reasons.append(f"{path} has no purpose in files")
    for path in sorted(p for p in actual if _reserved(p)):
        reasons.append(f"you changed {path}, which belongs to the conductor")
    for path in sorted(set(declared) | {p for p in actual if not _reserved(p)}):
        if path not in actual:
            reasons.append(f"you listed {path} in files but it is unchanged since the task began")
        elif path not in declared:
            reasons.append(f"you changed {path} but did not list it in files")
        elif declared[path] != actual[path]:
            reasons.append(f"{path} is listed as {declared[path]} but the change since the task began is {actual[path]}")
    return reasons
