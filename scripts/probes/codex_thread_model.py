"""Probe: which model and reasoning effort did a Codex thread actually use?

Why this exists: `codex exec --json` does not echo the model in its event
stream. A headless run that passes no -m flag therefore only tells us what
~/.codex/config.toml *should* have applied. Codex's local SQLite databases may
record what really ran. Parallax receipts name the model and effort of every
seat, so we need to know whether that can be confirmed after the fact or must
be pinned up front.

Usage:
    python scripts/probes/codex_thread_model.py <thread-id>

Read-only: opens ~/.codex/*.sqlite with mode=ro and prints only short
model/effort snippets and row counts, never whole rows.
"""
import re
import sqlite3
import sys
from pathlib import Path

PATTERN = re.compile(
    r"""(?:model(?:_slug|_name)?|reasoning[_ ]?effort|effort)["']?\s*[:=]\s*["']?([A-Za-z0-9._-]{2,40})""",
    re.I,
)


def scan(db: Path, thread: str) -> None:
    try:
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        print(f"{db.name}: cannot open ({exc})")
        return
    try:
        tables = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
        for table in tables:
            cols = [r[1] for r in con.execute(f'pragma table_info("{table}")')]
            if not cols:
                continue
            where = " or ".join(f'cast("{c}" as text) like ?' for c in cols)
            found: dict[str, int] = {}
            hits = 0
            try:
                rows = con.execute(
                    f'select * from "{table}" where {where} limit 5000',
                    [f"%{thread}%"] * len(cols),
                )
                for row in rows:
                    hits += 1
                    for value in row:
                        if isinstance(value, bytes):
                            value = value.decode("utf-8", "replace")
                        if isinstance(value, str):
                            for match in PATTERN.finditer(value):
                                key = match.group(0)[:80]
                                found[key] = found.get(key, 0) + 1
            except sqlite3.Error as exc:
                print(f"{db.name}.{table}: query failed ({exc})")
                continue
            if hits:
                print(f"{db.name}.{table}: {hits} rows mention the thread")
                for key, count in sorted(found.items(), key=lambda kv: -kv[1])[:15]:
                    print(f"    {count:5d}x  {key}")
    finally:
        con.close()


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    thread = sys.argv[1]
    home = Path.home() / ".codex"
    dbs = sorted(home.glob("*.sqlite"))
    if not dbs:
        print(f"no sqlite databases under {home}")
        return 1
    for db in dbs:
        scan(db, thread)
    return 0


if __name__ == "__main__":
    sys.exit(main())
