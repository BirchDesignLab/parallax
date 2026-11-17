"""Codex CLI seat, with structured results and cleanup of per-folder trust entries."""
from __future__ import annotations

import json
import os
import shutil
import tomllib
from collections.abc import Sequence
from pathlib import Path

from parallax.config import Config, SeatConfig
from parallax.procs import run_command
from parallax.schemas import validate
from parallax.seats.base import SeatRequest, SeatResult, seat_env


def windows_sandbox_setting(codex_home: Path) -> str | None:
    """Read only the Windows sandbox setting; a missing config has no override."""
    try:
        with (codex_home / "config.toml").open("rb") as stream:
            config = tomllib.load(stream)
    except FileNotFoundError:
        return None
    windows = config.get("windows", {})
    setting = windows.get("sandbox") if isinstance(windows, dict) else None
    return setting if isinstance(setting, str) else None


def _event_metadata(events: str) -> tuple[str | None, dict, bool]:
    session = None
    usage = {"input": 0, "cached": 0, "output": 0}
    started = False
    for line in events.splitlines():
        try:
            event = json.loads(line)
        except (ValueError, RecursionError):
            continue
        # run_command merges stderr into stdout, including non-JSON diagnostics.
        if not isinstance(event, dict):
            continue
        if event.get("type") == "thread.started":
            started = True
            session = event.get("thread_id")
        elif event.get("type") == "turn.completed":
            tokens = event.get("usage")
            if not isinstance(tokens, dict):
                tokens = {}
            usage = {key: tokens.get(field, 0) for key, field in (
                ("input", "input_tokens"), ("cached", "cached_input_tokens"),
                ("output", "output_tokens"))}
    return session, usage, started


class CodexSeat:
    def __init__(self, seat: SeatConfig, cfg: Config, launcher: Sequence[str] | None = None,
                 codex_home: Path | None = None):
        self.name, self.model, self.effort = seat.name, seat.model, seat.effort
        self.cfg = cfg
        self.launcher = list(launcher) if launcher is not None else [shutil.which("codex")]
        self.codex_home = (Path(codex_home) if codex_home is not None
                           else Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex"))
        # Construction must not inspect the human's config; run reads it lazily.

    def run(self, req: SeatRequest) -> SeatResult:
        req.out_dir.mkdir(parents=True, exist_ok=True)
        (req.out_dir / "brief.md").write_text(req.brief, encoding="utf-8", newline="\n")
        schema_path = req.out_dir / "schema.json"
        schema_path.write_text(json.dumps(req.schema), encoding="utf-8", newline="\n")
        last_path = req.out_dir / "last.json"
        output_path = req.out_dir / "output.json"
        # A reused artifact folder must never supply a previous turn's result.
        output_path.unlink(missing_ok=True)
        (req.out_dir / "events.jsonl").write_text("", encoding="utf-8", newline="\n")
        session = None
        usage = {"input": 0, "cached": 0, "output": 0}
        events = ""
        try:
            if not self.launcher or self.launcher[0] is None:
                raise FileNotFoundError("codex executable was not found")
            mode = "workspace-write" if req.writable else "read-only"
            cmd = [*self.launcher, "exec"]
            if req.session is not None:
                cmd.append("resume")
            cmd += ["-m", self.model, "-c", f'model_reasoning_effort="{self.effort}"',
                    "--ignore-user-config"]
            sandbox = windows_sandbox_setting(self.codex_home)
            if sandbox is not None:
                cmd += ["-c", f"windows.sandbox={json.dumps(sandbox)}"]
            if req.session is None:
                cmd += ["--sandbox", mode, "-C", str(req.cwd), "--color", "never"]
            else:
                cmd += ["-c", f'sandbox_mode="{mode}"']
            cmd += ["--json", "--output-schema", str(schema_path), "-o", str(last_path)]
            if req.session is not None:
                cmd.append(req.session)
            cmd.append("-")

            for attempt in range(2):
                last_path.unlink(missing_ok=True)
                result = run_command(cmd, cwd=req.cwd, timeout=self.cfg.seat_timeout,
                                     input=req.brief, env=seat_env("codex"))
                events += result.output
                (req.out_dir / "events.jsonl").write_text(events, encoding="utf-8", newline="\n")
                session, usage, started = _event_metadata(result.output)
                if result.timed_out:
                    return SeatResult(None, session, events, usage,
                                      f"timed out after {self.cfg.seat_timeout}s")
                if result.code != 0:
                    if attempt == 0 and not started:
                        continue
                    return SeatResult(None, session, events, usage,
                                      f"codex exited {result.code}: {result.output[-400:]}")
                break

            try:
                output = json.loads(last_path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return SeatResult(None, session, events, usage, "last.json is missing")
            except (ValueError, UnicodeDecodeError, RecursionError):
                return SeatResult(None, session, events, usage, "last.json is not valid JSON")
            problems = validate(output, req.schema)
            if problems:
                return SeatResult(None, session, events, usage, "; ".join(problems))
            output_path.write_text(json.dumps(output), encoding="utf-8", newline="\n")
            return SeatResult(output, session, events, usage)
        except (OSError, ValueError) as exc:
            return SeatResult(None, session, events, usage, str(exc))

    def discard(self, session: str, cwd: Path) -> None:
        # Cleanup only: the conductor calls this after main has advanced and while voiding,
        # with nothing to catch an error, so a failed delete must never raise.
        if self.launcher and self.launcher[0] is not None:
            try:
                run_command([*self.launcher, "delete", "--force", session],
                            cwd=cwd if Path(cwd).is_dir() else Path.home(),
                            timeout=self.cfg.seat_timeout, env=seat_env("codex"))
            except Exception:
                pass
        try:
            self._forget_folder(cwd)
        except OSError:
            pass

    def _forget_folder(self, cwd: Path) -> None:
        path = self.codex_home / "config.toml"
        try:
            original = path.read_bytes()
        except FileNotFoundError:
            return
        header = f"[projects.'{cwd}']".casefold()
        kept = []
        removing = False
        for line in original.splitlines(keepends=True):
            text = line.decode("utf-8", errors="replace").strip()
            if text.casefold() == header:
                removing = True
                continue
            if removing and (not text or text.startswith("[")):
                removing = False
            if not removing:
                kept.append(line)
        updated = b"".join(kept)
        if updated != original:
            path.write_bytes(updated)
