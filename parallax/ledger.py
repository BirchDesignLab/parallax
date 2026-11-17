"""Durable JSON-lines journals and the committed ledger."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path


class LedgerCorrupt(Exception):
    """A journal or ledger contains a bad event before its torn tail."""


# Share the lock across instances so two Journals for one path also cooperate.
_lock = threading.Lock()


def sha256_text(text: str) -> str:
    data = text.replace("\r\n", "\n").encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _parse_records(lines: list[str] | list[bytes]) -> list[dict]:
    # Every event is written with its newline in one fsynced write, so whatever
    # follows the last newline is a torn write, never an event, even when it
    # happens to parse: append() truncates it, and counting it here would let a
    # step look done and then vanish. Every complete line must be a valid event.
    events = []
    for index, line in enumerate(lines[:-1]):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise LedgerCorrupt(f"Invalid event on line {index + 1}: {exc}") from None
        if not isinstance(event, dict):
            raise LedgerCorrupt(f"Event on line {index + 1} must be a JSON object")
        events.append(event)
    return events


def parse_lines(text: str) -> list[dict]:
    """Ignore the torn tail after the last newline; raise LedgerCorrupt for any bad complete line."""
    return _parse_records(text.split("\n"))


def _read_events(path: Path) -> list[dict]:
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return []
    # Decode each record separately: a torn UTF-8 character in the tail must
    # not prevent recovery of the complete events before it.
    return _parse_records(data.split(b"\n"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _truncate_tail(path: Path) -> None:
    try:
        handle = path.open("r+b")
    except FileNotFoundError:
        return
    with handle:
        data = handle.read()
        end = data.rfind(b"\n") + 1
        if end != len(data):
            handle.truncate(end)


def _append_lines(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


class Journal:
    path: Path

    def __init__(self, path: Path, clock: Callable[[], str] = _utc_now):
        self.path = Path(path)
        self._clock = clock

    def append(self, type: str, task: str, **fields) -> dict:
        with _lock:
            event = {"ts": self._clock(), "type": type, "task": task, **fields}
            line = json.dumps(event) + "\n"
            _truncate_tail(self.path)
            _append_lines(self.path, line)
            return event

    def events(self, task: str | None = None) -> list[dict]:
        with _lock:
            events = _read_events(self.path)
            return events if task is None else [e for e in events if e.get("task") == task]

    def drop_task(self, task: str) -> None:
        with _lock:
            events = [e for e in _read_events(self.path) if e.get("task") != task]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", newline="\n",
                    dir=self.path.parent, prefix=self.path.name + ".", suffix=".tmp",
                    delete=False,
                ) as handle:
                    temporary = Path(handle.name)
                    for event in events:
                        handle.write(json.dumps(event) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)


def publish(events: Sequence[dict], ledger_file: Path) -> None:
    text = "".join(json.dumps(event) + "\n" for event in events)
    with _lock:
        _append_lines(Path(ledger_file), text)
