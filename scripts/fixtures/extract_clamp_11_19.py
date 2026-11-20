"""Extract the public record of the recorded 11-19 clamp run into an offline test fixture.

Source: the landed demo project ~/.parallax/demos/clamp-250950f5 (Task 17 binary, five cards,
five project B rulings). Only events with no private paths are kept: task.opened, the five
dispute.opened, the five ruling.made and task.integrated, verbatim and in order, plus the
landed PRECEDENTS.md text. Task 19.3's historical replay baseline reads the fixture, so the
tests run on any machine.

Run: python scripts/fixtures/extract_clamp_11_19.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from parallax.redact import scrub_paths  # noqa: E402

SOURCE = Path.home() / ".parallax" / "demos" / "clamp-250950f5"
TARGET = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "clamp_11_19.json"
KEEP = ("task.opened", "dispute.opened", "ruling.made", "task.integrated")


def strings(value):
    """Every decoded string anywhere in `value`."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from strings(item)


def main() -> None:
    events = [json.loads(line) for line in (SOURCE / ".parallax" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
              if line.strip()]
    kept = [e for e in events if e["type"] in KEEP]
    markdown = (SOURCE / ".parallax" / "PRECEDENTS.md").read_text(encoding="utf-8")
    private = [s for s in strings([kept, markdown]) if scrub_paths(s) != s]
    assert not private, f"absolute path in fixture: {private[:3]}"
    assert [e["type"] for e in kept] == ["task.opened"] + ["dispute.opened"] * 5 + ["ruling.made"] * 5 + ["task.integrated"]
    fixture = {"source": "~/.parallax/demos/clamp-250950f5, landed 2026-11-19",
               "events": kept,
               "precedents_md": markdown}
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps(fixture, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {TARGET} ({len(kept)} events)")


if __name__ == "__main__":
    main()
