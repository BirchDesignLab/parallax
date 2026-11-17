"""Pure text detection of forbidden paths in seat output."""
from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path


def _normalize(text: str) -> str:
    return text.replace("\\\\", "\\").replace("\\", "/").lower()


def forbidden_hits(text: str, forbidden: Sequence[str | Path]) -> list[str]:
    """Return original forbidden entries found after Windows path normalization."""
    normalized = _normalize(text)
    hits = []
    for entry in forbidden:
        original = str(entry)
        pattern = re.escape(_normalize(original)) + r"(?![\w-])"
        if re.search(pattern, normalized) is not None:
            hits.append(original)
    return hits
