"""Case-sensitive, repository-relative write scope matching."""
from __future__ import annotations

import re
from collections.abc import Sequence


def _pattern_regex(pattern: str) -> str:
    parts = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            parts.append("(?:.*/)?")
            index += 3
        elif pattern.startswith("**", index):
            parts.append(".*")
            index += 2
        elif pattern[index] == "*":
            parts.append("[^/]*")
            index += 1
        else:
            parts.append(re.escape(pattern[index]))
            index += 1
    return "".join(parts)


def matches(path: str, patterns: Sequence[str]) -> bool:
    """Whether an entire path matches any scope pattern."""
    return any(re.fullmatch(_pattern_regex(pattern), path, re.DOTALL) is not None
               for pattern in patterns)


def outside(paths: Sequence[str], patterns: Sequence[str]) -> list[str]:
    """Return paths outside the scopes, preserving their input order."""
    return [path for path in paths if not matches(path, patterns)]
