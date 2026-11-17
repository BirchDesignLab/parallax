"""Seat requests, results and the environment shared by real adapters."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class SeatRequest:
    stage: str
    brief: str
    cwd: Path
    schema: dict
    writable: bool
    session: str | None
    out_dir: Path


@dataclass(frozen=True)
class SeatResult:
    output: dict | None
    session: str | None
    events: str
    usage: dict
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.output is not None


class Seat(Protocol):
    name: str
    model: str
    effort: str

    def run(self, req: SeatRequest) -> SeatResult: ...

    def discard(self, session: str, cwd: Path) -> None: ...


def seat_env(kind: str) -> dict[str, str]:
    """Copy the environment, removing agent settings except this seat's allowlist."""
    allowed = {
        "claude": {"ANTHROPIC_API_KEY"},
        "codex": {"OPENAI_API_KEY", "CODEX_HOME"},
    }
    kind = kind.lower()
    if kind not in allowed:
        raise ValueError(f"unknown seat kind {kind!r}")
    prefixes = ("CLAUDE", "ANTHROPIC", "OPENAI", "CODEX")
    return {key: value for key, value in os.environ.items()
            if not key.upper().startswith(prefixes) or key.upper() in allowed[kind]}
