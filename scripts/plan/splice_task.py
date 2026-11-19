"""Replace one `### Task N` section of the v0 plan with a draft file.

Usage: python scripts/plan/splice_task.py <task number> <draft.md>

The section runs from its `### Task N:` heading to the next `### ` heading or the end of the
file. The draft must start with the same heading. Writes the plan in place with LF endings.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PLAN = Path(__file__).resolve().parents[2] / "docs/superpowers/plans/2026-11-16-parallax-v0.md"


def splice(number: str, draft: Path) -> None:
    text = PLAN.read_text(encoding="utf-8")
    new = draft.read_text(encoding="utf-8").replace("\r\n", "\n").rstrip("\n") + "\n"
    heading = re.compile(rf"^### Task {re.escape(number)}:.*$", re.M)
    if not heading.match(new):
        raise SystemExit(f"{draft} does not start with '### Task {number}:'")
    found = list(heading.finditer(text))
    if len(found) != 1:
        raise SystemExit(f"expected one '### Task {number}:' heading in the plan, found {len(found)}")
    start = found[0].start()
    nxt = re.compile(r"^### ", re.M).search(text, found[0].end())
    end = nxt.start() if nxt else len(text)
    tail = text[end:]
    PLAN.write_text(text[:start] + new + ("\n" + tail if tail else ""), encoding="utf-8", newline="\n")
    print(f"Task {number}: replaced {end - start} characters with {len(new)}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    splice(sys.argv[1], Path(sys.argv[2]))
