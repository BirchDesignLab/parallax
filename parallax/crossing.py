"""The crossing: the builder's change meets the challenger's probes, then every mutant must be caught."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from parallax import gitops, scopes
from parallax.config import Config
from parallax.procs import run_command
from parallax.receipt import probe_count

_MUTANT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


@dataclass(frozen=True)
class CrossingResult:
    passed: bool
    timed_out: bool
    output: str
    count: int | None
    mutants: dict[str, str]  # id -> "killed" or "survived"; empty when the check itself failed

    @property
    def clean(self) -> bool:
        """Passed, and no mutant survived."""
        return self.passed and all(state == "killed" for state in self.mutants.values())


def _plain_relative(rel: object) -> bool:
    """A repository-relative path with forward slashes that cannot leave the folder it is joined to."""
    if not isinstance(rel, str) or not rel or rel.startswith("/") or "\\" in rel or ":" in rel:
        return False
    return all(part not in ("", ".", "..") for part in rel.split("/"))


def _at(root: Path, rel: str) -> Path:
    return Path(root).joinpath(*rel.split("/"))


def validate_mutants(clone: Path, mutants_dir: Path, mutants: Sequence[dict], cfg: Config) -> list[str]:
    """Problems with the builder's mutants, as sentences; empty when they are fine."""
    problems: list[str] = []
    seen: set[str] = set()
    valid = 0
    for mutant in mutants:
        mid, files = mutant.get("id"), mutant.get("files")
        if not isinstance(mid, str) or not _MUTANT_ID.fullmatch(mid):
            problems.append(f"mutant id {mid!r} is not a plain name (letters, digits, '.', '_', '-')")
            continue
        if mid in seen:
            problems.append(f"mutant {mid} is listed more than once")
            continue
        seen.add(mid)
        if not isinstance(files, list) or not files:
            problems.append(f"mutant {mid} lists no files")
            continue
        ok, differs = True, False
        for rel in files:
            if not _plain_relative(rel):
                problems.append(f"mutant {mid} lists {rel!r}, which is not a plain relative path")
                ok = False
            elif not scopes.matches(rel, cfg.builder_scope):
                problems.append(f"mutant {mid} changes {rel}, which is outside the builder's scope")
                ok = False
            elif not _at(Path(mutants_dir) / mid, rel).is_file():
                problems.append(f"mutant {mid} lists {rel}, but there is no such file in its folder")
                ok = False
            else:
                real = _at(clone, rel)
                if not real.is_file() or real.read_bytes() != _at(Path(mutants_dir) / mid, rel).read_bytes():
                    differs = True
        if ok and not differs:
            problems.append(f"mutant {mid} is identical to the real code")
            ok = False
        if ok:
            valid += 1
    if valid < cfg.mutants:
        problems.append(f"expected {cfg.mutants} mutants, got {valid}")
    return problems


def _check(work: Path, cfg: Config):
    # Without this, Python may reuse the real file's bytecode for a mutant of the same size
    # written in the same second, and the mutant would wrongly survive.
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    return run_command(cfg.check, work, cfg.check_timeout, env=env)


def _run_mutant(work: Path, mutants_dir: Path, mutant: dict, cfg: Config) -> str:
    mid, files = mutant["id"], mutant["files"]
    for rel in files:
        if not _plain_relative(rel):
            raise ValueError(f"mutant {mid} lists {rel!r}, which is not a plain relative path")
    originals: dict[str, bytes | None] = {}
    try:
        for rel in files:
            target = _at(work, rel)
            originals[rel] = target.read_bytes() if target.is_file() else None
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(_at(Path(mutants_dir) / mid, rel).read_bytes())
        result = _check(work, cfg)
    finally:
        for rel, data in originals.items():
            target = _at(work, rel)
            if data is None:
                target.unlink(missing_ok=True)
            else:
                target.write_bytes(data)
    return "killed" if result.timed_out or result.code != 0 else "survived"


def cross(work: Path, base: str, builder_head: str, challenger_head: str, cfg: Config,
          mutants_dir: Path, mutants: Sequence[dict]) -> CrossingResult:
    """Combine both seats' work in `work` (a clone that has both commits), run the check, then each mutant.

    Raises GitError if the challenger's changes do not apply on top of the builder's.
    """
    work = Path(work)
    gitops.git(work, "checkout", "--quiet", "--force", "--detach", builder_head)
    gitops.git(work, "clean", "-fdxq")
    gitops.apply_range(work, base, challenger_head)
    result = _check(work, cfg)
    count = probe_count(result.output, cfg.count_pattern)
    passed = result.code == 0 and not result.timed_out
    if not passed:
        return CrossingResult(False, result.timed_out, result.output, count, {})
    states = {mutant["id"]: _run_mutant(work, mutants_dir, mutant, cfg) for mutant in mutants}
    return CrossingResult(True, False, result.output, count, states)
