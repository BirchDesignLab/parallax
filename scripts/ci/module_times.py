"""Measure how long each test module took in a CI run, from the run's log.

    gh run view <run id> --log > .superpowers/agents/controller/run.log
    python scripts/ci/module_times.py .superpowers/agents/controller/run.log

Each shard runs `unittest -v`, which prints one line per test as it finishes, and GitHub
stamps every log line with a time. The time a test took is the gap since the line before
it in the same job; a module's time is the sum over its tests. Prints the modules with
their seconds, slowest first, as lines ready to paste into SECONDS in run_tests.py.
"""
import re
import sys
from collections import defaultdict
from datetime import datetime

LINE = re.compile(r"^(?P<job>[^\t]*)\t[^\t]*\t\ufeff?(?P<stamp>\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d+)Z (?P<text>.*)$")
TEST = re.compile(r"\((tests\.\w+)\.[\w.]+\)")


def main() -> int:
    seconds: dict[str, float] = defaultdict(float)
    last: dict[str, datetime] = {}
    pending: dict[str, str] = {}
    for raw in open(sys.argv[1], encoding="utf-8", errors="replace"):
        match = LINE.match(raw.rstrip("\n"))
        if not match:
            continue
        job, text = match["job"], match["text"]
        stamp = datetime.fromisoformat(match["stamp"][:26])
        named = TEST.search(text)
        if named:
            pending[job] = named.group(1)
        # A test's result is on its own line (" ... ok"), or on a later one when it printed output.
        if job in pending and re.search(r"\.\.\. (ok|FAIL|ERROR|skipped|expected failure)", text) or text.strip() in ("ok", "FAIL", "ERROR"):
            if job in pending and job in last:
                seconds[pending[job]] += (stamp - last[job]).total_seconds()
            pending.pop(job, None)
            last[job] = stamp
        elif job not in last:
            last[job] = stamp
    for module, spent in sorted(seconds.items(), key=lambda item: -item[1]):
        print(f'    "{module}": {round(spent)},')
    print(f"# total {round(sum(seconds.values()))}s over {len(seconds)} modules", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
