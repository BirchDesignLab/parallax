"""Claude Code CLI seat: `claude -p` with a stream-json result, no shell tool, confined to its folder."""
from __future__ import annotations

import json
import shutil
import uuid
from collections.abc import Sequence
from pathlib import Path

from parallax.config import Config, SeatConfig
from parallax.procs import run_command
from parallax.schemas import validate
from parallax.seats.base import SeatRequest, SeatResult, seat_env


def _count(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _last_result(events: str) -> dict | None:
    """The last `"type": "result"` event. Other lines, including merged stderr, are skipped."""
    found = None
    for line in events.splitlines():
        try:
            event = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if isinstance(event, dict) and event.get("type") == "result":
            found = event
    return found


def _usage(result: dict | None) -> dict:
    tokens = result.get("usage") if result else None
    if not isinstance(tokens, dict):
        tokens = {}
    cached = _count(tokens.get("cache_read_input_tokens"))
    return {"input": _count(tokens.get("input_tokens")) + cached + _count(tokens.get("cache_creation_input_tokens")),
            "cached": cached, "output": _count(tokens.get("output_tokens"))}


class ClaudeSeat:
    def __init__(self, seat: SeatConfig, cfg: Config, launcher: Sequence[str] | None = None):
        self.name, self.model, self.effort = seat.name, seat.model, seat.effort
        self.cfg = cfg
        self.launcher = list(launcher) if launcher is not None else [shutil.which("claude")]

    def run(self, req: SeatRequest) -> SeatResult:
        session = req.session or str(uuid.uuid4())
        usage = {"input": 0, "cached": 0, "output": 0}
        events = ""
        try:
            req.out_dir.mkdir(parents=True, exist_ok=True)
            (req.out_dir / "brief.md").write_text(req.brief, encoding="utf-8", newline="\n")
            (req.out_dir / "schema.json").write_text(json.dumps(req.schema), encoding="utf-8", newline="\n")
            output_path = req.out_dir / "output.json"
            # A reused artifact folder must never supply a previous turn's result.
            output_path.unlink(missing_ok=True)
            (req.out_dir / "events.jsonl").write_text("", encoding="utf-8", newline="\n")
            if not self.launcher or self.launcher[0] is None:
                raise FileNotFoundError("claude executable was not found")
            tools = "Read,Write,Edit,Glob,Grep" if req.writable else "Read,Glob,Grep"
            cmd = [*self.launcher, "-p", "--model", self.model, "--effort", self.effort,
                   "--safe-mode", "--restricted", "--tools", tools,
                   "--permission-mode", "acceptEdits", "--permission-prompts", "none",
                   "--output-format", "stream-json", "--verbose",
                   "--json-schema", json.dumps(req.schema)]
            cmd += ["--session-id", session] if req.session is None else ["--resume", session]

            ran = run_command(cmd, cwd=req.cwd, timeout=self.cfg.seat_timeout,
                              input=req.brief, env=seat_env("claude"))
            events = ran.output
            (req.out_dir / "events.jsonl").write_text(events, encoding="utf-8", newline="\n")
            result = _last_result(events)
            usage = _usage(result)
            if result is not None and isinstance(result.get("session_id"), str):
                session = result["session_id"]
            if ran.timed_out:
                return SeatResult(None, session, events, usage, f"timed out after {self.cfg.seat_timeout}s")
            if result is None:
                return SeatResult(None, session, events, usage, f"claude exited {ran.code}: {events[-400:]}")
            if result.get("is_error"):
                text = result.get("result")
                return SeatResult(None, session, events, usage,
                                  text if isinstance(text, str) and text else "claude reported an error")

            output = result.get("structured_output")
            if not isinstance(output, dict):
                text = result.get("result")
                if not isinstance(text, str):
                    return SeatResult(None, session, events, usage, "result has no structured output")
                try:
                    output = json.loads(text)
                except (ValueError, RecursionError):
                    return SeatResult(None, session, events, usage, "result is not valid JSON")
            problems = validate(output, req.schema)
            if problems:
                return SeatResult(None, session, events, usage, "; ".join(problems))
            output_path.write_text(json.dumps(output), encoding="utf-8", newline="\n")
            return SeatResult(output, session, events, usage)
        except (OSError, ValueError) as exc:
            return SeatResult(None, session, events, usage, str(exc))

    def discard(self, session: str, cwd: Path) -> None:
        # Cleanup only: the conductor calls this after main has advanced and while voiding,
        # with nothing to catch an error, so a failed purge must never raise.
        if not self.launcher or self.launcher[0] is None:
            return
        try:
            run_command([*self.launcher, "purge", "-y", str(cwd)],
                        cwd=cwd if Path(cwd).is_dir() else Path.home(),
                        timeout=self.cfg.seat_timeout, env=seat_env("claude"))
        except Exception:
            pass
