"""A scripted seat: no subprocesses, network calls or implicit model work."""
from __future__ import annotations

import json
from pathlib import Path

from parallax.schemas import validate
from parallax.seats.base import SeatRequest, SeatResult


class StubSeat:
    def __init__(self, name: str, script: dict[str, list], model: str = "stub-model", effort: str = "none"):
        self.name = name
        self.script = script
        self.model = model
        self.effort = effort
        self.calls: list[SeatRequest] = []
        self.discarded: list[str] = []
        self._sessions = 0

    def run(self, req: SeatRequest) -> SeatResult:
        self.calls.append(req)
        if not self.script.get(req.stage):
            raise AssertionError(f"stub {self.name} has no {req.stage} step left")
        step = self.script[req.stage].pop(0)
        session = req.session
        if session is None:
            self._sessions += 1
            session = f"{self.name}-s{self._sessions}"

        req.out_dir.mkdir(parents=True, exist_ok=True)
        # A crashing step must not leave a previous call's successful output behind.
        (req.out_dir / "output.json").write_text("null", encoding="utf-8", newline="\n")
        (req.out_dir / "events.jsonl").write_text("", encoding="utf-8", newline="\n")
        (req.out_dir / "brief.md").write_text(req.brief, encoding="utf-8", newline="\n")
        (req.out_dir / "schema.json").write_text(json.dumps(req.schema), encoding="utf-8", newline="\n")

        # Script exceptions deliberately propagate: tests can simulate interrupted work.
        output = step(req)
        if isinstance(output, SeatResult):
            result = output
        else:
            problems = validate(output, req.schema)
            if not isinstance(output, dict) and not problems:
                problems.append("$: expected object")
            result = SeatResult(None if problems else output, session, "",
                                {"input": 0, "cached": 0, "output": 0},
                                "; ".join(problems) if problems else None)
        (req.out_dir / "events.jsonl").write_text(result.events, encoding="utf-8", newline="\n")
        (req.out_dir / "output.json").write_text(json.dumps(result.output), encoding="utf-8", newline="\n")
        return result

    def discard(self, session: str, cwd: Path) -> None:
        self.discarded.append(session)
