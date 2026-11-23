"""Point commit hashes quoted in tracked files at the rewritten history.

Why (2026-11-23): `rewrite_history.py` changed every commit's hash, and the docs quote
commits by short hash. This replaces each hex word of 7 to 40 characters that is a prefix
of exactly one OLD hash in the commit map with the same-length prefix of its NEW hash.
A hex word that matches no old commit (a hash from another repository, a digest) is left.

Usage: python scripts/history/remap_hashes.py <commit-map> [--write]
Without --write it only reports. Run from the repository root.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

_HEX = re.compile(rb"(?<![0-9A-Za-z])[0-9a-f]{7,40}(?![0-9A-Za-z])")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    write = "--write" in argv[2:]
    table = [line.split() for line in Path(argv[1]).read_bytes().splitlines()]
    self_path = Path(argv[1]).as_posix()
    total = 0
    for name in subprocess.run(["git", "ls-files", "-z"], check=True, capture_output=True).stdout.split(b"\0"):
        path = Path(name.decode())
        if not name or path.as_posix() == self_path:
            continue
        data = path.read_bytes()
        if b"\0" in data:
            continue
        changed = 0

        def swap(match: re.Match) -> bytes:
            nonlocal changed
            word = match.group()
            hits = [new for old, new in table if old.startswith(word)]
            if len(hits) != 1:
                return word
            changed += 1
            return hits[0][:len(word)]

        updated = _HEX.sub(swap, data)
        if changed:
            total += changed
            print(f"{changed:4} {path.as_posix()}")
            if write:
                path.write_bytes(updated)
    print(f"{total} references {'rewritten' if write else 'found'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
