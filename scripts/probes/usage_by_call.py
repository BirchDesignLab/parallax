"""Print every usage-bearing event of a project's ledger, in order, with the seat session it ran in.

Why: the 2026-11-23 live runs suggested that a call resuming a seat session reports the
session's cumulative usage, which the conductor then sums per call. A cumulative counter
shows here as per-seat numbers that never fall while the session stays the same.

Usage: python scripts/probes/usage_by_call.py <project folder> [task id]
Read-only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    ledger = Path(argv[1]) / ".parallax" / "ledger.jsonl"
    only = argv[2] if len(argv) > 2 else None
    for line in ledger.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        usage = event.get("usage")
        if not isinstance(usage, dict) or (only and event.get("task") != only):
            continue
        print(f"{event.get('task', ''):12} {event.get('type', ''):18} {event.get('seat', ''):7} "
              f"in={usage.get('input', 0):>8} cached={usage.get('cached', 0):>8} out={usage.get('output', 0):>7} "
              f"session={str(event.get('session', ''))[:13]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
