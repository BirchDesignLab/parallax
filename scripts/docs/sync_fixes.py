"""One-off (2026-11-23): bring the public pages and the spec in line with the five fixes
(clone names in the ledger, exclusive paths, unknown config keys, a missing task file, usage
exit code). Each replacement is asserted to match once. Kept for the record."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def line_sub(name, starts, new):
    """Replace the one line of `name` that starts with `starts`."""
    path = ROOT / name
    lines = path.read_text(encoding="utf-8").split(chr(10))
    hits = [i for i, line in enumerate(lines) if line.startswith(starts)]
    assert len(hits) == 1, (name, starts, len(hits))
    lines[hits[0]] = new
    path.write_text(chr(10).join(lines), encoding="utf-8", newline=chr(10))


line_sub("README.md", "- Two known gaps are open.",
         "- The committed ledger of a task landed before 2026-11-23 records each seat clone's full path, home folder included. Newer records hold only the clone's folder name. Check an older project's `.parallax/ledger.jsonl` before publishing it.")
line_sub("docs/faq.md", "Two gaps are open and documented.",
         "One thing to check on an older project: a task landed before 2026-11-23 recorded each seat clone's full path in the committed ledger, which includes your account name. Newer records hold only the clone's folder name. See [Receipts and the ledger](receipts.md). The design document lists every place the code differs from the original design.")
line_sub("docs/receipts.md", "**Known gap: the ledger records absolute paths.**",
         "**Clone paths in the ledger.** A `checkout.created` event records a seat clone by its folder name, such as `codex-1a2b3c4d`, and the conductor resolves it against the task's state folder. Audit hits in `reading.voided` and `attempt.voided` are recorded relative to that folder too. Tasks landed before 2026-11-23 recorded the clone's full path, which sits under your home folder: check an older `.parallax/ledger.jsonl` before you push that project to a public remote.")
line_sub("docs/cli.md", "argparse also exits with 2 on a usage error",
         "A usage error, such as an unknown flag or a `rule` choice outside `a`, `b`, `other` and `drop`, prints a usage message to stderr and exits 1, so exit code 2 only ever means a task needs a ruling. A task file that does not exist is also exit 1, with `parallax: file not found: <path>`.")
line_sub("docs/configuration.md", "Parallax does not warn about keys it does not recognize.",
         "A key Parallax does not know is an error that names it, for example `unknown key project.lnit`, so a misspelled key cannot fall back to its default unnoticed.")
line_sub("docs/configuration.md", "| `exclusive` | list of strings |",
         "| `exclusive` | list of strings | `[]` | Paths both roles might need, such as manifests and lockfiles. They belong to the builder: added to its paths and closed to the challenger. |")
line_sub("docs/configuration.md", "Each entry must be a nonempty string. The effective builder scope",
         "Each entry must be a nonempty string. The effective builder scope is `builder` followed by `exclusive`. The challenger's scope is `challenger`, minus anything `exclusive` matches: a challenger attempt that changes such a path is rejected with `you changed files reserved for the builder`, even where a challenger pattern also matches it. Parallax does not otherwise check that the `builder` and `challenger` lists are disjoint, so keep those two apart yourself.")
line_sub("docs/blind.md", "- **Exclusive paths.**",
         "- **Exclusive paths.** Files both roles would need, such as lockfiles and manifests, are listed as `exclusive` and belong to the builder. A challenger attempt that changes one is rejected, even where a challenger pattern also matches it.")

spec = "docs/superpowers/specs/2026-11-16-parallax-design.md"
line_sub(spec, "Recorded 2026-11-23, while the reference pages",
         "Recorded 2026-11-23, while the reference pages under `docs/` were written against the code. The code is the authority in each case. Four entries were gaps and were fixed the same day; they are kept here, marked, because the text above still reads the old way or says nothing.")
line_sub(spec, "**Known gaps**", "**Gaps, fixed 2026-11-23**")
line_sub(spec, "1. **The ledger records absolute clone paths.**",
         "1. **The ledger recorded absolute clone paths.** Each `checkout.created` event stored the seat clone's full path, and landing moves a task's events into `.parallax/ledger.jsonl`, which is committed, so a project's ledger carried a path under the human's home folder. Fixed: the event records the clone's folder name and the conductor resolves it against the task's state folder; audit hits in `reading.voided`, `attempt.voided` and a `seat.failed` raised by the audit are recorded relative to that folder. Events written earlier keep the full path and still read. No brief or card ever showed a seat that path, so the blind was not affected.")
line_sub(spec, "2. **`exclusive` does not exclude.**",
         "2. **`exclusive` did not exclude.** The code only added the `exclusive` patterns to the builder's scope, so a path matched by both `challenger` and `exclusive` could be written by either seat. Fixed: a challenger attempt that changes a path `exclusive` matches is rejected (`you changed files reserved for the builder`). The `builder` and `challenger` lists themselves are still not checked for overlap.")
line_sub(spec, "4. **Config keys this document does not show.**",
         "4. **Config keys this document does not show.** `[project]` also reads `check_timeout` (seconds, default 600, used for `check` and `lint`), `seat_timeout` (default 1800) and `count_pattern` (a regular expression that reads the probe count from the check's output; the default matches unittest's \"Ran N tests\" line). Each `[seats.<name>]` table also reads `adapter`, which defaults to the seat's name. `[policy] merge` accepts only `\"auto\"` and `pair` only `\"behavior\"`; any other value is an error. An unknown table or key was ignored without a warning; fixed 2026-11-23, it is now an error that names the key.")
line_sub(spec, "17. **Exit code 2 has two meanings.**",
         "17. **Exit code 2 had two meanings.** A task that needs a ruling exits 2, and so did a usage error from the argument parser. Fixed 2026-11-23: a usage error exits 1, and so does a task file that does not exist, which used to end in a traceback.")
print("synced")
