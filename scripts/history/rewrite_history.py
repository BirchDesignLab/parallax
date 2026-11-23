"""Rewrite a repository's whole history into a NEW repository, changing author emails and scrubbing text.

Why (2026-11-23): before the first push to a repository that will be public, every commit
carried a personal email address and a few old briefs carried a local account name in paths.
`git filter-repo` was not installed and the project is standard library only, so this does
the same job through `git fast-export` and `git fast-import`.

It never touches the source repository. It writes:
  <out>/repo        the rewritten repository (non-bare, nothing checked out)
  <out>/commit-map  one line per commit: "<old sha> <new sha>"

Usage:
  python scripts/history/rewrite_history.py --source . --out .superpowers/rewrite \
      --email OLD=NEW [--email OLD=NEW ...] [--replace REGEX=TEXT ...] \
      [--exclude PATH ...] [--refs main]

--exclude (second run, 2026-11-23: working notes left the public history) removes a path
from every commit; a commit that touched only excluded paths disappears, and its line is
missing from the commit map.

--email changes author, committer and tagger emails that equal OLD.
--replace applies a regular expression (bytes, case-insensitive) to every blob and every
commit message. The personal values are arguments so that this file holds none of them.

`<out>` must not exist yet; the script creates it and deletes nothing.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

_PERSON = re.compile(rb"^(author|committer|tagger) (.*)<([^>]*)> (\d+ [+-]\d{4})\n$", re.S)


def pairs(values: list[str], what: str) -> list[tuple[str, str]]:
    found = []
    for value in values:
        old, sep, new = value.partition("=")
        if not sep or not old:
            raise SystemExit(f"--{what} needs OLD=NEW, got {value!r}")
        found.append((old, new))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--email", action="append", default=[])
    parser.add_argument("--replace", action="append", default=[])
    parser.add_argument("--exclude", action="append", default=[], help="a path to leave out of every commit")
    parser.add_argument("--refs", default="--all", help="what to export: --all, or one branch name")
    args = parser.parse_args()

    source, out = Path(args.source).resolve(), Path(args.out).resolve()
    emails = {old.encode(): new.encode() for old, new in pairs(args.email, "email")}
    patterns = [(re.compile(old.encode(), re.I), new.encode()) for old, new in pairs(args.replace, "replace")]
    out.mkdir(parents=True)                       # fails if it exists: never write into an old run
    repo = out / "repo"
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)

    marks = out / "marks"
    # With pathspecs fast-export leaves the excluded paths out of every commit and drops
    # the commits that touched nothing else.
    limits = ["--", ".", *(f":(exclude){path}" for path in args.exclude)] if args.exclude else []
    export = subprocess.Popen(["git", "-C", str(source), "fast-export", args.refs, "--show-original-ids",
                               "--signed-tags=strip", "--reencode=yes", *limits], stdout=subprocess.PIPE)
    load = subprocess.Popen(["git", "-C", str(repo), "fast-import", "--quiet", f"--export-marks={marks}"],
                            stdin=subprocess.PIPE)
    stream, sink = export.stdout, load.stdin
    originals: dict[bytes, bytes] = {}            # mark -> old sha, commits only
    counts = {"emails": 0, "texts": 0}
    mark, in_commit = None, False
    while line := stream.readline():
        if line.startswith(b"data "):
            data = stream.read(int(line[5:]))
            for pattern, new in patterns:
                data, n = pattern.subn(new, data)
                counts["texts"] += n
            sink.write(b"data %d\n" % len(data))
            sink.write(data)
            continue
        if line.startswith((b"commit ", b"blob", b"tag ", b"reset ")):
            in_commit, mark = line.startswith(b"commit "), None
        elif line.startswith(b"mark :"):
            mark = line[5:].strip()
        elif line.startswith(b"original-oid ") and in_commit and mark:
            originals[mark] = line.split()[1]
        elif (person := _PERSON.match(line)) and person.group(3) in emails:
            line = b"%s %s<%s> %s\n" % (person.group(1), person.group(2), emails[person.group(3)], person.group(4))
            counts["emails"] += 1
        sink.write(line)
    sink.close()
    if export.wait() or load.wait():
        print("fast-export or fast-import failed", file=sys.stderr)
        return 1

    new = dict(line.split() for line in marks.read_bytes().splitlines())
    rows = [b"%s %s\n" % (old, new[m]) for m, old in originals.items()]
    (out / "commit-map").write_bytes(b"".join(rows))
    print(f"{len(rows)} commits rewritten into {repo}")
    print(f"{counts['emails']} person lines changed, {counts['texts']} text replacements")
    return 0


if __name__ == "__main__":
    sys.exit(main())
