"""Removing absolute paths from text a seat or the human will read.

Check output, lint output and seat readings can carry absolute paths (a scratch clone, a seat's
clone, the state home). Briefs, contracts and dispute cards pass through `scrub_paths`, which turns
each one into `<outside>/<file name>` instead of failing: a URL or a route like `GET /users` in a
task must never stop a run.
"""
from __future__ import annotations

import re

# Where an absolute path starts: a drive letter, a UNC share, or a POSIX home folder.
_ABS_START = re.compile(r"(?i)(?<![a-z])[a-z]:[\\/]|(?<![\w\\])\\\\[^\\/\s]|(?<![\w.~-])/(?:Users|home)/")
_ABS_END = re.compile(r"""[\s"'`<>|,;()\[\]{}]""")
_FILE_NAME = re.compile(r"^[\w.-]*\w\.\w+$")


def scrub_paths(text: str) -> str:
    """Replace every absolute path with `<outside>/<file name>` (or `<outside>`)."""
    out, pos = [], 0
    while (m := _ABS_START.search(text, pos)) is not None:
        start = m.start()
        quote = text[start - 1] if start and text[start - 1] in "\"'`" else ""
        if quote:
            end = text.find(quote, m.end())
            end = len(text) if end < 0 else end
        else:
            stop = _ABS_END.search(text, m.end())
            end = stop.start() if stop else len(text)
        name = re.split(r"[\\/]+", text[start:end].rstrip("\\/.:"))[-1]
        out.append(text[pos:start])
        out.append(f"<outside>/{name}" if _FILE_NAME.match(name) else "<outside>")
        pos = end
    out.append(text[pos:])
    return "".join(out)
