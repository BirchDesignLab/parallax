"""The receipt: the verification summary stamped on a landed commit as git trailers."""
from __future__ import annotations

import re
from typing import Mapping, Sequence


def probe_count(output: str, pattern: str) -> int | None:
    """The number the pattern's first group captures in the check output; None when it does not appear.

    The last match wins: a test runner prints its summary at the end, after any nested output.
    """
    found = list(re.finditer(pattern, output))
    if not found:
        return None
    try:
        return int(found[-1].group(1))
    except (IndexError, ValueError, TypeError):
        return None


def verdict(kind: str, failed_crossings: int, rulings: int, limitations: Sequence[str]) -> str:
    if kind == "chore":
        return "solo"
    if limitations:
        return "limited"
    if rulings > 0:
        return "ruled"
    if failed_crossings > 0:
        return "resolved"
    return "consensus"


def checks_line(count: int | None, mutants: Mapping[str, str], waived: Sequence[str] = ()) -> str:
    """`14 probes passed, 3 of 3 mutants caught`; `check passed, ...` when the count is unknown.

    Waived mutants count as not caught. With no mutants at all, only the first half is given.
    """
    head = "check passed" if count is None else f"{count} probes passed"
    if not mutants:
        return head
    caught = sum(1 for mid, state in mutants.items() if state == "killed" and mid not in waived)
    return f"{head}, {caught} of {len(mutants)} mutants caught"


def trailers(task: str, contract_sha: str | None, built_by: str, challenged_by: str | None,
             checks: str, verdict: str, limitations: Sequence[str]) -> str:
    lines = [f"Parallax-Task: {task}"]
    if contract_sha is not None:
        lines.append(f"Parallax-Contract: {contract_sha}")
    lines.append(f"Built-by: {built_by}")
    if challenged_by is not None:
        lines.append(f"Challenged-by: {challenged_by}")
    lines.append(f"Checks: {checks}")
    lines.append(f"Verdict: {verdict}")
    # A trailer is one line; a line break inside a limitation would end it early.
    lines.extend(f"Limitation: {' '.join(text.split())}" for text in limitations)
    return "\n".join(lines)
