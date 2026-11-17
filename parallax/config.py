"""Project configuration (`parallax.toml`) and where Parallax keeps its state."""
from __future__ import annotations

import hashlib
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

SAMPLE_TOML = """\
[project]
check = "python -m unittest discover -s tests"
lint  = "python -m compileall -q ."
main  = "main"

[scopes]
builder    = ["src/**"]
challenger = ["tests/**"]
exclusive  = ["pyproject.toml", "uv.lock"]

[policy]
merge = "auto"
pair  = "behavior"
max_repair_rounds = 2
mutants = 3

[seats.codex]
model  = "gpt-6-astra"
effort = "xhigh"

[seats.claude]
model  = "fable"
effort = "high"
"""

CONFIG_NAME = "parallax.toml"


class ConfigError(Exception):
    """A missing, unreadable or invalid `parallax.toml`. The message names the key or file."""


@dataclass(frozen=True)
class SeatConfig:
    name: str
    adapter: str
    model: str
    effort: str


@dataclass(frozen=True)
class Config:
    root: Path
    check: str
    lint: str
    main: str
    check_timeout: int
    seat_timeout: int
    count_pattern: str
    builder_scope: tuple[str, ...]
    challenger_scope: tuple[str, ...]
    merge: str
    pair: str
    max_repair_rounds: int
    mutants: int
    seats: tuple[SeatConfig, ...]

    @property
    def run_dir(self) -> Path:
        return self.root / ".parallax" / "run"


def _table(doc: dict, key: str, required: bool = True) -> dict:
    value = doc.get(key)
    if value is None:
        if required:
            raise ConfigError(f"{CONFIG_NAME}: missing table [{key}]")
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{CONFIG_NAME}: [{key}] must be a table")
    return value


def _str(table: dict, where: str, key: str, default: str | None = None) -> str:
    value = table.get(key, default)
    if value is None:
        raise ConfigError(f"{CONFIG_NAME}: missing {where}.{key}")
    if not isinstance(value, str):
        raise ConfigError(f"{CONFIG_NAME}: {where}.{key} must be a string")
    return value


def _int(table: dict, where: str, key: str, default: int) -> int:
    value = table.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ConfigError(f"{CONFIG_NAME}: {where}.{key} must be a non-negative integer")
    return value


def _patterns(table: dict, key: str, required: bool) -> tuple[str, ...]:
    value = table.get(key)
    if value is None:
        if required:
            raise ConfigError(f"{CONFIG_NAME}: missing scopes.{key}")
        return ()
    if not isinstance(value, list) or not all(isinstance(p, str) and p for p in value):
        raise ConfigError(f"{CONFIG_NAME}: scopes.{key} must be a list of path patterns")
    return tuple(value)


def load_config(root: Path) -> Config:
    path = Path(root) / CONFIG_NAME
    try:
        doc = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"{CONFIG_NAME} not found in {root}") from None
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{CONFIG_NAME} could not be read: {exc}") from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{CONFIG_NAME} is not valid TOML: {exc}") from None

    project = _table(doc, "project")
    scopes = _table(doc, "scopes")
    policy = _table(doc, "policy", required=False)
    seats_table = _table(doc, "seats", required=False)

    merge = _str(policy, "policy", "merge", "auto")
    if merge != "auto":
        raise ConfigError(f'{CONFIG_NAME}: policy.merge must be "auto" in v0, not {merge!r}')
    pair = _str(policy, "policy", "pair", "behavior")
    if pair != "behavior":
        raise ConfigError(f'{CONFIG_NAME}: policy.pair must be "behavior" in v0, not {pair!r}')

    if len(seats_table) != 2:
        raise ConfigError(f"{CONFIG_NAME}: [seats] must name exactly two seats, found {len(seats_table)}")
    seats = []
    for name, seat in seats_table.items():
        if not isinstance(seat, dict):
            raise ConfigError(f"{CONFIG_NAME}: [seats.{name}] must be a table")
        where = f"seats.{name}"
        seats.append(SeatConfig(name=name, adapter=_str(seat, where, "adapter", name),
                                model=_str(seat, where, "model"), effort=_str(seat, where, "effort")))

    return Config(
        root=Path(root),
        check=_str(project, "project", "check"),
        lint=_str(project, "project", "lint", ""),
        main=_str(project, "project", "main", "main"),
        check_timeout=_int(project, "project", "check_timeout", 600),
        seat_timeout=_int(project, "project", "seat_timeout", 1800),
        count_pattern=_str(project, "project", "count_pattern", r"Ran (\d+) tests?"),
        builder_scope=_patterns(scopes, "builder", True) + _patterns(scopes, "exclusive", False),
        challenger_scope=_patterns(scopes, "challenger", True),
        merge=merge,
        pair=pair,
        max_repair_rounds=_int(policy, "policy", "max_repair_rounds", 2),
        mutants=_int(policy, "policy", "mutants", 3),
        seats=tuple(seats),
    )


def state_home() -> Path:
    """Where seat clones, scratch clones and artifacts live: PARALLAX_HOME, else ~/.parallax.

    Never %LOCALAPPDATA% or %APPDATA%: a process started from a packaged app has new
    folders there redirected, and Codex's sandbox then fails every command (error 267).
    """
    override = os.environ.get("PARALLAX_HOME")
    return Path(override) if override else Path.home() / ".parallax"


def repo_key(root: Path) -> str:
    """A short, stable name for a project in the state home, insensitive to path case."""
    return hashlib.sha256(str(Path(root).resolve()).lower().encode("utf-8")).hexdigest()[:12]
