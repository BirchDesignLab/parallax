"""The conductor: carries one task from a task file through the pair's steps.

Every step is an event in the journal, and every step first looks for its own completion
event and skips itself when it finds one. That is the whole resume mechanism: a crash, a
pause for a ruling or a blocked seat all resume by running the same task file again.

Part 1: lock, open, sealed readings, reveal, settlement, rulings, contract.
Part 2: braid (parallel attempts), crossing, landing.
Part 3: disputes after a failed crossing, repairs, rulings' follow-ups, limits, drop, chores.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import secrets
import shutil
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from parallax import audit, batch, briefs, decisions, delivery, folders, gitops, receipt, redact, schemas, scopes
from parallax.config import Config, repo_key, state_home
from parallax.crossing import cross, validate_mutants
from parallax.decisions import Dispute, Point
from parallax.ledger import Journal, parse_lines, publish, sha256_text
from parallax.procs import run_command
from parallax.redact import scrub_paths
from parallax.schemas import validate
from parallax.seats.base import Seat, SeatRequest, SeatResult

_TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_CHORE = re.compile(r"(?i)^kind:\s*chore\s*$")
_STOP_AFTER = (None, "contract")
LEDGER = ".parallax/ledger.jsonl"
MUTANTS_DIR = ".parallax-mutants"
SCRATCH_DIR = ".parallax-scratch"
_LAND_TRIES = 3


@dataclass(frozen=True)
class Outcome:
    status: str                      # "landed" | "needs_ruling" | "parked" | "blocked" | "dropped" | "stopped"
    task: str
    detail: str = ""
    disputes: tuple[Dispute, ...] = ()
    commit: str | None = None


class _Stop(Exception):
    """Raised anywhere inside a run (including seat threads) to end it with `outcome`."""

    def __init__(self, outcome: Outcome):
        super().__init__(outcome.detail)
        self.outcome = outcome


@dataclass(frozen=True)
class _Task:
    """What `task.opened` fixed about a task, plus where its state lives."""
    id: str
    text: str
    kind: str
    title: str
    base: str
    builder: str
    challenger: str
    dir: Path                        # <home>/<repo key>/<task>, private
    whole: bool = False              # task.opened carried interface_protocol="whole"
    batch: bool = False              # task.opened carried batch_protocol="confirmed-v1" (Task 19.4)

    def role(self, seat: str) -> str:
        return "builder" if seat == self.builder else "challenger"

    def other(self, seat: str) -> str:
        return self.challenger if seat == self.builder else self.builder

    @property
    def seats(self) -> tuple[str, str]:
        return self.builder, self.challenger


def task_id(task_file: Path) -> str:
    name = Path(task_file).stem
    if _TASK_ID.fullmatch(name) is None:
        raise ValueError(f"invalid task id {name!r}: use letters, digits, '.', '_' and '-', starting with a letter or digit")
    return name


def _parse_task(text: str) -> tuple[str, str]:
    """(kind, title) from a task file's text."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    kind = "chore" if lines and _CHORE.match(lines[0]) else "behavior"
    rest = lines[1:] if kind == "chore" else lines
    title = rest[0].lstrip("# ").strip() if rest else ""
    return kind, title


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        # Never os.kill(pid, 0) here: on Windows signal 0 is CTRL_C_EVENT.
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        if pid > 0xFFFFFFFF:
            return False
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() == 5             # ERROR_ACCESS_DENIED: it exists
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True                                 # it opened, so assume it is there
            return code.value == 259                        # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _canonical(output: dict) -> str:
    return json.dumps(output, sort_keys=True, indent=2)


def _tail(text: str, n: int) -> str:
    """The last `n` characters of tool output, with absolute paths scrubbed."""
    return scrub_paths(text[-n:])


def _short_title(title: str) -> str:
    if len(title) <= 60:
        return title
    cut = title.rfind(" ", 0, 61)
    return (title[:cut] if cut > 0 else title[:60]).rstrip()


def _no_bytecode_env() -> dict[str, str]:
    return dict(os.environ, PYTHONDONTWRITEBYTECODE="1")


def _add_usage(a: Mapping[str, int], b: Mapping[str, int]) -> dict:
    return {k: a.get(k, 0) + b.get(k, 0) for k in {*a, *b}}


_BATCH_PROTOCOL = "confirmed-v1"
_PROPOSE, _REVIEW = "batch_propose", "batch_review"
_PRECEDENT_FIELDS = ("id", "question", "ruling", "while", "task")


def _route(packet: dict) -> str:
    return decisions.route(packet["sources"], {role: {"conflicts": packet["conflicts"][role]}
                                               for role in ("builder", "challenger")})


def _sha_ok(value) -> bool:
    return isinstance(value, str) and value.startswith("sha256:") and len(value) > len("sha256:")


def _usage_ok(usage) -> bool:
    return isinstance(usage, dict) and all(type(n) is int for n in usage.values())


def _opening_sha(t: _Task) -> str:
    """Binds a batch checkpoint to its opening: the packet holds the task text, not its ID, base or seats."""
    return batch.digest({"task": t.id, "base": t.base, "seats": {"builder": t.builder, "challenger": t.challenger}})


def _reveal_lines(role: str, reveal: dict, readings: dict, keys: list[str]) -> str | None:
    lines = [decisions.witness_problem(v) for v in sorted(reveal["verdicts"], key=lambda v: v["index"])]
    if role == "challenger":
        lines.append(decisions.interface_problem(reveal, readings["builder"]["interface"]))
    lines.append(decisions.conflict_problem(reveal, keys))
    return "\n".join(line for line in lines if line) or None


def _reveal_problem(role: str, reveal: dict, readings: dict, keys: list[str]) -> str | None:
    """Why a recorded reveal cannot enter a confirmed-v1 settlement, or None.

    The witness, interface and conflict checks run on the recorded words, then on the words the
    packet will show (scrubbed), so a distinction lost to scrubbing is caught before any call.
    """
    problems = validate(reveal, schemas.REVEAL_CONFIRMED)
    if problems:
        return "; ".join(problems)
    other = readings["challenger" if role == "builder" else "builder"]
    count = len(other["decisions"])
    indexes = sorted(v["index"] for v in reveal["verdicts"])
    if indexes != list(range(count)):
        return f"verdicts must give exactly one index for each of 0..{count - 1}, got {indexes}"
    raw = _reveal_lines(role, reveal, readings, keys)
    if raw:
        return raw
    shown = _reveal_lines(role, redact.scrub_values(reveal), redact.scrub_values(readings), keys)
    return f"after scrubbing: {shown}" if shown else None


def _precedents_ok(precedents) -> bool:
    return isinstance(precedents, list) and all(
        isinstance(p, dict) and set(p) == set(_PRECEDENT_FIELDS) and all(isinstance(v, str) for v in p.values())
        for p in precedents)


def _checkpoint_problem(event: dict, seat: str, role: str) -> str | None:
    """What is wrong with a batch checkpoint's envelope, or None."""
    if event.get("batch_protocol") != _BATCH_PROTOCOL:
        return f"is not marked batch_protocol {_BATCH_PROTOCOL}"
    if event.get("seat") != seat:
        return f"was not written by the {role} {seat}"
    if not _sha_ok(event.get("sha")) or not _sha_ok(event.get("packet_sha")):
        return "has no sha"
    if not _usage_ok(event.get("usage")):
        return "has malformed usage"
    return None


_BATCH_RECORDS = ("batch.proposed", "batch.reviewed", "reading.settled")


def _opening_problem(opened: dict) -> str | None:
    """Why this version cannot read a recorded task.opened, or None. A marker that is absent is an older opening."""
    if "interface_protocol" in opened and opened["interface_protocol"] != "whole":
        return f"has interface_protocol {opened['interface_protocol']!r}, which this version of parallax does not know"
    if "batch_protocol" not in opened:
        return None
    if opened["batch_protocol"] != _BATCH_PROTOCOL:
        return f"has batch_protocol {opened['batch_protocol']!r}, which this version of parallax does not know"
    if opened.get("interface_protocol") != "whole":
        return f"has batch_protocol {_BATCH_PROTOCOL} without interface_protocol whole"
    if opened.get("kind") != "behavior":
        return f"has batch_protocol {_BATCH_PROTOCOL} on a {opened.get('kind')} task"
    return None


def _batch_mismatch(t: _Task, event: dict) -> str | None:
    """Why `event` cannot belong to `t` under its batch protocol, or None.

    On a confirmed-v1 task every reveal and batch record carries the marker, and no standalone reading
    or interface card exists. On any other task no record carries it and no batch record exists.
    """
    what = f"{event['seat']}'s {event['type']}" if event.get("seat") else event["type"]
    if t.batch:
        if event["type"] == "dispute.opened" and event.get("kind") in ("reading", "interface"):
            return f"{event['id']} is a standalone {event['kind']} card on a {_BATCH_PROTOCOL} task"
        if event["type"] in ("reveal.done",) + _BATCH_RECORDS and event.get("batch_protocol") != _BATCH_PROTOCOL:
            return f"{what} is not marked batch_protocol {_BATCH_PROTOCOL}, but {t.id} was opened {_BATCH_PROTOCOL}"
        return None
    if "batch_protocol" in event or event["type"] in _BATCH_RECORDS:
        return f"{what} is a {_BATCH_PROTOCOL} record, but {t.id} was not opened {_BATCH_PROTOCOL}"
    return None


class Conductor:
    cfg: Config

    def __init__(self, cfg: Config, seats: Mapping[str, Seat], say: Callable[[str], None] = print,
                 home: Path | None = None):
        self.cfg = cfg
        self.seats = dict(seats)
        self.say = say
        self.home = Path(home) if home is not None else state_home()
        self.journal = Journal(cfg.run_dir / "journal.jsonl")
        self._artifact_lock = threading.Lock()

    # ----------------------------------------------------------------- public

    def run(self, task_file: Path, builder: str | None = None, stop_after: str | None = None) -> Outcome:
        task_file = Path(task_file)
        task = task_id(task_file)
        if stop_after not in _STOP_AFTER:
            raise ValueError(f"stop_after must be one of {_STOP_AFTER!r}, not {stop_after!r}")
        held = self._lock(task)
        if isinstance(held, Outcome):
            return held
        try:
            return self._run(task, task_file, builder, stop_after)
        except _Stop as stop:
            return stop.outcome
        finally:
            self._unlock(held)

    def rule(self, dispute_id: str, choice: str, note: str = "", scope: str | None = None,
             while_: str = "", limitation: str = "") -> None:
        # Take the run lock: a ruling written from another process while a run appends to the
        # same journal could interleave with, or be truncated by, that run's writes.
        held = self._lock(dispute_id)
        if isinstance(held, Outcome):
            raise RuntimeError(f"cannot rule now: {held.detail}")
        try:
            self._rule(dispute_id, choice, note, scope, while_, limitation)
        finally:
            self._unlock(held)

    def _rule(self, dispute_id: str, choice: str, note: str, scope: str | None,
              while_: str, limitation: str) -> None:
        events = self.events()
        opened = [e for e in events if e["type"] == "dispute.opened" and e.get("id") == dispute_id]
        if not opened:
            raise ValueError(f"unknown dispute {dispute_id}")
        if any(e["type"] == "ruling.made" and e.get("dispute") == dispute_id for e in events):
            raise ValueError(f"{dispute_id} is already ruled")
        dispute = Dispute.from_event(opened[-1])
        whole = (self._first(opened[-1]["task"], "task.opened") or {}).get("interface_protocol") == "whole"
        if dispute.kind == "interface" and (opened[-1].get("interface_protocol") == "whole") != whole:
            raise ValueError(self._mismatch(dispute_id, opened[-1]["task"], whole))
        if dispute.kind in ("check", "unresolved") and choice in ("a", "b"):
            text = note.strip() or f"{dispute.a_label if choice == 'a' else dispute.b_label} is right."
        elif dispute.kind == "unresolved" and choice == "drop":
            text = note.strip() or "Drop this task."
        else:
            text = decisions.ruling_text(dispute, choice, note)
        if dispute.kind == "mutant" and choice == "b":
            mutant = self._mutant_of(events).get(dispute_id, "?")
            waiver = f"mutant {mutant} waived" + (f": {note.strip()}" if note.strip() else "")
            limitation = f"{waiver}; {limitation}" if limitation.strip() else waiver
        if dispute.kind in ("mutant", "unresolved"):
            scope = "task"
        elif scope is None:
            scope = decisions.default_scope(dispute.kind, whole_interface=whole)
        if scope not in ("task", "project"):
            raise ValueError(f"scope must be 'task' or 'project', not {scope!r}")
        self.journal.append("ruling.made", opened[-1]["task"], dispute=dispute_id, kind=dispute.kind,
                            question=dispute.question, choice=choice, text=text, scope=scope,
                            **{"while": while_}, limitation=limitation)

    def events(self, task: str | None = None) -> list[dict]:
        """The ledger as committed on main, followed by the journal."""
        text = gitops.show_file(self.cfg.root, self.cfg.main, LEDGER)
        events = (parse_lines(text) if text else []) + self.journal.events()
        return events if task is None else [e for e in events if e.get("task") == task]

    def status(self) -> list[dict]:
        events = self.events()
        live = {e.get("task") for e in self.journal.events()}
        order: list[str] = []
        for event in events:
            if event.get("task") not in order:
                order.append(event.get("task"))
        rows = []
        for task in order:
            mine = [e for e in events if e.get("task") == task]
            if task in live:
                pending = [d.id for d in self._pending(mine)]
                if mine[-1]["type"] == "task.parked":
                    status = "parked"
                elif pending:
                    status = "needs_ruling"
                else:
                    status = "in_progress"
            else:
                pending = []
                status = "dropped" if any(e["type"] == "task.dropped" for e in mine) else "landed"
            rows.append({"task": task, "status": status, "pending": pending})
        return rows

    # ---------------------------------------------------------------- the run

    def _run(self, task: str, task_file: Path, builder: str | None, stop_after: str | None) -> Outcome:
        text = task_file.read_text(encoding="utf-8")
        if not self.journal.events(task):
            # Nothing in flight: a task already in the ledger is finished, not started again.
            ended = {e["type"] for e in self.events(task)}
            if "task.dropped" in ended:
                return Outcome("dropped", task, f"{task} was already dropped")
            if "task.integrated" in ended:
                return Outcome("landed", task, f"{task} has already landed")
        t = self._open(task, text, builder, check_protocol=True)
        if t.kind == "chore":
            return self._solo(t)
        self._readings(t)
        self._reveal(t)
        if t.batch:
            # Task 19.4 records confirmed reveals. Publishing their settlement is Task 19.5's.
            return Outcome("stopped", t.id, "stopped after the confirmed reveals")
        self._settle(t)
        self._rulings(t)
        self._contract(t)
        if stop_after == "contract":
            return Outcome("stopped", t.id, "stopped after the contract was frozen")
        self._braid(t)
        recross = False
        while True:
            # Each pass either lands, stops for the human, or records a new failed crossing,
            # and failed crossings are bounded by the repair limit, so this ends.
            done = self._crossing(t, force=recross)
            if self._clean(t, done):
                return self._land(t)
            outcome = self._after_failed_crossing(t, done)
            if outcome is not None:
                return outcome
            recross = True

    # Step 1
    def _lock(self, task: str) -> Path | Outcome:
        """Create `.parallax/run/lock` holding this pid, or say who holds it."""
        lock = self.cfg.run_dir / "lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                with open(lock, "x", encoding="utf-8") as handle:
                    handle.write(str(os.getpid()))
                return lock
            except FileExistsError:
                pass
            try:
                pid = int(lock.read_text(encoding="utf-8").strip() or "0")
            except (OSError, ValueError):
                pid = 0
            if pid and _pid_alive(pid):
                return Outcome("blocked", task, f"another parallax run is active (pid {pid})")
            lock.unlink(missing_ok=True)                    # stale: its process is gone
        return Outcome("blocked", task, "another parallax run took the lock")

    def _unlock(self, lock: Path) -> None:
        try:
            if lock.read_text(encoding="utf-8").strip() == str(os.getpid()):
                lock.unlink()
        except OSError:
            pass

    # Step 2
    def _open(self, task: str, text: str, builder: str | None, *, batch: bool = False,
              check_protocol: bool = False) -> _Task:
        """The task's opening, recorded now if it has none. `batch` marks a new opening confirmed-v1.

        Only tests pass `batch` until Task 19.7. A recorded opening is never changed. An opening this
        version cannot read blocks before the task's folder, a checkout or another event is created,
        and so, with `check_protocol` (as `run` passes it), does an event written under another protocol.
        """
        names = [s.name for s in self.cfg.seats]
        opened = self._first(task, "task.opened")
        if opened is None:
            kind, title = _parse_task(text)
            if builder is None:
                k = sum(1 for e in self.events() if e["type"] == "task.opened" and e["task"] != task)
                builder = names[k % 2]
            if builder not in names:
                raise ValueError(f"unknown seat {builder!r}; the seats are {', '.join(names)}")
            challenger = names[1 - names.index(builder)]
            if batch and kind != "behavior":
                raise ValueError(f"only a behavior task can be opened {_BATCH_PROTOCOL}")
            marker = {"batch_protocol": _BATCH_PROTOCOL} if batch else {}
            opened = self.journal.append("task.opened", task, kind=kind, base=gitops.rev(self.cfg.root, self.cfg.main),
                                         builder=builder, challenger=challenger, title=title or task,
                                         interface_protocol="whole", **marker)
            self.say(f"{task}: opened ({kind}); builder {builder}, challenger {challenger}")
        problem = _opening_problem(opened)
        if problem:
            raise _Stop(Outcome("blocked", task, f"{task}'s task.opened {problem}"))
        t = _Task(task, text, opened["kind"], opened["title"], opened["base"], opened["builder"],
                  opened["challenger"], self.home / repo_key(self.cfg.root) / task,
                  whole=opened.get("interface_protocol") == "whole",
                  batch=opened.get("batch_protocol") == _BATCH_PROTOCOL)
        for seat in t.seats:
            if seat not in self.seats:
                raise ValueError(f"no seat named {seat!r} was given to the conductor")
        if check_protocol:
            self._check_protocol(t)                         # both kinds, before any state exists
        if not t.dir.exists():
            folders.make_private(t.dir)
        for seat in (t.seats if t.kind == "behavior" else (t.builder,)):
            if self._clone_of(t, seat) is None:
                self._new_clone(t, seat)
        return t

    # Step 3
    def _readings(self, t: _Task) -> None:
        if t.batch:
            # A reveal recorded before a missing seal can never be settled: block before reading.
            self._marked_inputs(t, self.events(t.id), pair=False)
        todo = [seat for seat in t.seats if self._sealed(t, seat) is None]
        self._parallel([lambda seat=seat: self._read(t, seat) for seat in todo])

    def _read(self, t: _Task, seat: str) -> None:
        brief = briefs.reading(t.text, t.role(seat), self.cfg, decisions.precedents(self.events()), whole=t.whole)
        request = SeatRequest("reading", brief, self._clone_of(t, seat), schemas.READING, writable=False,
                              session=None, out_dir=self._artifact_dir(t, seat, "reading"))
        voids = []

        def void(request: SeatRequest, result: SeatResult, hits: list[str]) -> SeatRequest:
            # The contamination goes with the reading: its session and its clone.
            self.journal.append("reading.voided", t.id, seat=seat, hits=hits)
            if result.session:
                self.seats[seat].discard(result.session, request.cwd)
            self._remove_clone(t, seat, request.cwd)
            fresh = self._new_clone(t, seat)
            voids.append(hits)
            self.say(f"{t.id}: {seat}'s reading named the other seat's folder; voided")
            if len(voids) >= 2:
                raise _Stop(Outcome("blocked", t.id, f"{seat}'s reading was voided twice: it named {', '.join(hits)}"))
            return replace(request, brief=brief, cwd=fresh, session=None,
                           out_dir=self._artifact_dir(t, seat, "reading"))

        result, request = self._call(seat, request, task=t, void=void)
        sha = self._store(request.out_dir, result.output)
        self.journal.append("reading.sealed", t.id, seat=seat, sha=sha, session=result.session, usage=result.usage)
        self.say(f"{t.id}: {seat}'s reading sealed")

    # Step 4
    def _reveal(self, t: _Task) -> None:
        todo = [seat for seat in t.seats if self._last(t.id, "reveal.done", seat=seat) is None]
        readings = None
        if t.batch:
            # Never spend a reveal's call on a prefix the settlement would refuse, or without its session.
            readings = self._marked_inputs(t, self.events(t.id), pair=False)[0]
            for seat in todo:
                self._session_for_call(t, seat)
        self._parallel([lambda seat=seat: self._reveal_one(t, seat, readings) for seat in todo])

    def _reveal_one(self, t: _Task, seat: str, readings: dict | None = None) -> None:
        """`seat`'s reveal. On a marked task `readings` are both sealed readings by role, and `_reveal` has
        verified them and the sealed session this call resumes."""
        other_reading = self._reading(t, t.other(seat))
        count = len(other_reading["decisions"])

        def check(output: dict) -> str | None:
            indexes = sorted(v["index"] for v in output["verdicts"])
            if indexes != list(range(count)):
                return f"verdicts must give exactly one index for each of 0..{count - 1}, got {indexes}"
            problems = [decisions.witness_problem(v) for v in sorted(output["verdicts"], key=lambda v: v["index"])]
            if t.whole and t.role(seat) == "challenger":
                problems.append(decisions.interface_problem(output, other_reading["interface"]))
            return "\n".join(p for p in problems if p) or None

        schema = schemas.REVEAL if t.whole else schemas.REVEAL_AMENDING      # module attributes: tests patch them
        brief = briefs.reveal(t.role(seat), other_reading, whole=t.whole)
        marker = {}
        if t.batch:
            # Confirmed-v1: the checks the settlement makes run here, inside the retry, so the seat can correct them.
            role = t.role(seat)
            keys = decisions.source_keys(readings)
            check = lambda output: _reveal_problem(role, output, readings, keys)   # noqa: E731
            schema = schemas.REVEAL_CONFIRMED
            brief = briefs.reveal(role, readings[t.role(t.other(seat))], whole=True, own_reading=readings[role])
            marker = {"batch_protocol": _BATCH_PROTOCOL}
        request = SeatRequest("reveal", brief, self._clone_of(t, seat), schema, writable=False,
                              session=self._sealed(t, seat)["session"], out_dir=self._artifact_dir(t, seat, "reveal"))
        result, request = self._call(seat, request, task=t, check=check)
        sha = self._store(request.out_dir, result.output)
        self.journal.append("reveal.done", t.id, seat=seat, sha=sha, usage=result.usage, **marker)
        self.say(f"{t.id}: {seat}'s reveal done")

    # Step 5
    def _settle(self, t: _Task) -> None:
        readings = {seat: self._reading(t, seat) for seat in t.seats}
        reveals = self._reveals(t)
        _, _, disputes = decisions.settle(t.id, t.builder, t.challenger, readings, reveals)
        opened = {e["id"] for e in self.events(t.id) if e["type"] == "dispute.opened"}
        for dispute in disputes:
            if dispute.id not in opened:
                self._open_dispute(t, dispute)

    # Step 5b (Task 19.3): not yet reached by run
    def _confirm(self, t: _Task) -> dict:
        """Task 19.3: the settlement of the sealed readings and confirmed reveals. Publishes nothing.

        A direct route settles with no calls. A batch route asks the builder for a proposal, then the
        challenger for a review, each read-only and checkpointed; a completed checkpoint is verified and
        reused, never asked again. Every way to stop is `_Stop` with a blocked outcome, and verifying
        never changes the journal or an artifact.
        """
        events = self.events(t.id)
        readings, reveals, inputs, last_reveal = self._confirm_inputs(t, events)
        proposed, reviewed = self._batch_checkpoints(t, events, last_reveal)
        if proposed is None:
            in_force = [p for p in decisions.precedents(self.events()) if p["task"] != t.id]
            packet = self._batch_packet(t, in_force, readings, reveals, inputs)
            if _route(packet) == "direct":
                try:
                    return batch.direct_settlement(packet)
                except ValueError as exc:
                    raise _Stop(Outcome("blocked", t.id, str(exc))) from None
            proposal, proposed = self._propose(t, packet)
        else:
            packet, proposal = self._verified_proposal(t, proposed, readings, reveals, inputs)
        if reviewed is None:
            review = self._review_proposal(t, packet, proposal, proposed)
        else:
            review = self._verified_review(t, reviewed, proposed, packet, proposal)
        return batch.confirmed_settlement(packet, proposal, review)

    def _confirm_inputs(self, t: _Task, events: list[dict]) -> tuple[dict, dict, dict, int]:
        """Both sealed readings and both confirmed reveals, by role, their shas, and where the later reveal is.

        Each seat's effective seal and reveal are its last `reading.sealed` and `reveal.done`. Both seals
        must come before both reveals, so a reveal is never paired with a reading resealed after it.
        """
        return self._marked_inputs(t, events, pair=True)

    def _marked_inputs(self, t: _Task, events: list[dict], *, pair: bool) -> tuple[dict, dict, dict, int | None]:
        """`_confirm_inputs` when `pair`; otherwise the same checks on what a marked task has recorded so far.

        Unpaired, a seat may lack its reveal, and may lack its seal while no reveal is recorded, but a
        recorded reveal needs both effective seals before it. The readings and reveals returned are the
        ones present, and the index is None while no reveal is recorded.
        """
        def blocked(detail: str) -> _Stop:
            return _Stop(Outcome("blocked", t.id, detail))

        seals, reveals_done = {}, {}
        for i, event in enumerate(events):
            if event.get("seat") in t.seats and event["type"] == "reading.sealed":
                seals[event["seat"]] = (i, event)
            elif event.get("seat") in t.seats and event["type"] == "reveal.done":
                reveals_done[event["seat"]] = (i, event)
        for seat in t.seats:
            if pair and (seat not in seals or seat not in reveals_done):
                raise blocked(f"{seat} has no sealed reading and reveal to settle")
            if reveals_done and seat not in seals:
                raise blocked(f"{seat} has no sealed reading before the recorded reveals")
        if reveals_done and max(i for i, _ in seals.values()) > min(i for i, _ in reveals_done.values()):
            raise blocked("the recorded reveals do not follow both sealed readings")
        readings, reveals, inputs = {}, {}, {}
        for seat in t.seats:
            sealed = seals[seat][1] if seat in seals else None
            done = reveals_done[seat][1] if seat in reveals_done else None
            if sealed is not None and not _sha_ok(sealed.get("sha")):
                raise blocked(f"{seat}'s reading.sealed has no sha")
            if done is not None and not _sha_ok(done.get("sha")):
                raise blocked(f"{seat}'s reveal.done has no sha")
            if done is not None and done.get("batch_protocol") != _BATCH_PROTOCOL:
                raise blocked(f"{seat}'s reveal.done is not marked batch_protocol {_BATCH_PROTOCOL}")
            role = t.role(seat)
            if sealed is not None:
                readings[role] = self._artifact(t, seat, "reading", sealed["sha"])
                problems = validate(readings[role], schemas.READING)
                if problems:
                    raise blocked(f"{seat}'s sealed reading is not a valid reading: {'; '.join(problems)}")
            if done is not None:
                reveals[role] = self._artifact(t, seat, "reveal", done["sha"])
                inputs[role] = {"reading": sealed["sha"], "reveal": done["sha"]}
        if reveals:                                         # then both readings are present
            keys = decisions.source_keys(readings)
            for seat in t.seats:
                if t.role(seat) not in reveals:
                    continue
                problem = _reveal_problem(t.role(seat), reveals[t.role(seat)], readings, keys)
                if problem:
                    raise blocked(f"{seat}'s recorded reveal is not a confirmed-v1 reveal: {problem}")
        return readings, reveals, inputs, max((i for i, _ in reveals_done.values()), default=None)

    def _artifact(self, t: _Task, seat: str, stage: str, sha: str):
        """`_stored`, with an artifact that is not JSON as a blocked outcome rather than an exception."""
        try:
            return self._stored(t, seat, stage, sha)
        except ValueError:
            raise _Stop(Outcome("blocked", t.id, f"the recorded {stage} of {seat} is not valid JSON")) from None

    def _batch_packet(self, t: _Task, precedents: list, readings: dict, reveals: dict, inputs: dict) -> dict:
        try:
            return batch.packet(t.text, precedents, readings, reveals, inputs,
                                {"builder": t.builder, "challenger": t.challenger})
        except ValueError as exc:
            raise _Stop(Outcome("blocked", t.id, str(exc))) from None

    def _batch_checkpoints(self, t: _Task, events: list[dict], last_reveal: int) -> tuple[dict | None, dict | None]:
        """The task's batch.proposed and batch.reviewed: at most one each, after both reveals, in that order."""
        found = {}
        for kind in ("batch.proposed", "batch.reviewed"):
            matches = [i for i, e in enumerate(events) if e["type"] == kind]
            if len(matches) > 1:
                raise _Stop(Outcome("blocked", t.id, f"{t.id} has {len(matches)} {kind} checkpoints"))
            found[kind] = matches[0] if matches else None
        p, r = found["batch.proposed"], found["batch.reviewed"]
        if r is not None and (p is None or r < p):
            raise _Stop(Outcome("blocked", t.id, "the batch.reviewed checkpoint has no batch.proposed before it"))
        if p is not None and p < last_reveal:
            raise _Stop(Outcome("blocked", t.id, "the batch.proposed checkpoint comes before a recorded reveal"))
        return (events[p] if p is not None else None), (events[r] if r is not None else None)

    def _session_for_call(self, t: _Task, seat: str) -> str:
        session = self._sealed(t, seat).get("session")
        if not isinstance(session, str) or not session:
            raise _Stop(Outcome("blocked", t.id, f"{seat}'s sealed reading has no session to resume"))
        return session

    def _propose(self, t: _Task, packet: dict) -> tuple[dict, dict]:
        packet_sha = batch.digest(packet)
        seat = t.builder
        session = self._session_for_call(t, seat)
        request = SeatRequest(_PROPOSE, briefs.propose(packet, packet_sha), self._clone_of(t, seat), schemas.PROPOSAL,
                              writable=False, session=session, out_dir=self._artifact_dir(t, seat, _PROPOSE))
        result, request = self._call(
            seat, request, task=t, check=lambda raw: batch.proposal_problem(batch.accepted(raw), packet, packet_sha))
        proposal = batch.accepted(result.output)
        sha = self._store(request.out_dir, proposal)
        event = self.journal.append("batch.proposed", t.id, batch_protocol=_BATCH_PROTOCOL, seat=seat, opening=_opening_sha(t),
                                    packet=packet, packet_sha=packet_sha, sha=sha, usage=result.usage)
        self.say(f"{t.id}: {seat} proposed the settlement")
        return proposal, event

    def _verified_reply(self, t: _Task, seat: str, stage: str, sha: str, schema: dict, what: str, blocked) -> dict:
        """A checkpoint's stored reply, exactly as the fresh path would have stored it."""
        reply = self._artifact(t, seat, stage, sha)
        problems = validate(reply, schema)
        if problems:
            raise blocked(f"holds a {what} that does not match its schema: {'; '.join(problems)}")
        if batch.digest(reply) != sha:
            raise blocked(f"holds a {what} whose canonical digest is not its sha")
        if batch.canonical(reply) != batch.canonical(batch.accepted(reply)):
            raise blocked(f"holds a {what} that is not its accepted value")
        return reply

    def _verified_proposal(self, t: _Task, proposed: dict, readings: dict, reveals: dict,
                           inputs: dict) -> tuple[dict, dict]:
        """The packet and accepted proposal of a batch.proposed checkpoint, verified against today's inputs."""
        def blocked(problem: str) -> _Stop:
            return _Stop(Outcome("blocked", t.id, f"the batch.proposed checkpoint {problem}"))

        problem = _checkpoint_problem(proposed, t.builder, "builder")
        if problem:
            raise blocked(problem)
        if proposed.get("opening") != _opening_sha(t):
            raise blocked("belongs to another opening")
        pinned = proposed.get("packet")
        if not isinstance(pinned, dict) or batch.digest(pinned) != proposed["packet_sha"]:
            raise blocked("has a packet that does not match its packet_sha")
        if not _precedents_ok(pinned.get("precedents")):
            raise blocked("has malformed precedents")
        # The precedents are pinned: a ruling elsewhere since the proposal must not change the question.
        packet = self._batch_packet(t, pinned["precedents"], readings, reveals, inputs)
        if set(pinned) != set(packet):
            raise blocked("has a packet with other fields")
        for field in packet:                      # canonical JSON: key order is free, 0 is not False
            if batch.canonical(pinned[field]) != batch.canonical(packet[field]):
                raise blocked(f"does not match today's {field}")
        if batch.digest(packet) != proposed["packet_sha"]:
            raise blocked("has a packet that does not match its packet_sha")
        if _route(packet) != "batch":
            raise blocked("is on a direct route")
        proposal = self._verified_reply(t, t.builder, _PROPOSE, proposed["sha"], schemas.PROPOSAL, "proposal", blocked)
        problem = batch.proposal_problem(proposal, packet, proposed["packet_sha"])
        if problem:
            raise blocked(f"holds a proposal that no longer passes its checks: {problem}")
        return packet, proposal

    def _review_proposal(self, t: _Task, packet: dict, proposal: dict, proposed: dict) -> dict:
        packet_sha, proposal_sha = proposed["packet_sha"], proposed["sha"]
        seat = t.challenger
        session = self._session_for_call(t, seat)
        request = SeatRequest(_REVIEW, briefs.review(packet, packet_sha, proposal, proposal_sha), self._clone_of(t, seat),
                              schemas.REVIEW, writable=False, session=session, out_dir=self._artifact_dir(t, seat, _REVIEW))
        result, request = self._call(
            seat, request, task=t,
            check=lambda raw: batch.review_problem(batch.accepted(raw), proposal, packet, packet_sha, proposal_sha))
        review = batch.accepted(result.output)
        sha = self._store(request.out_dir, review)
        self.journal.append("batch.reviewed", t.id, batch_protocol=_BATCH_PROTOCOL, seat=seat, packet_sha=packet_sha,
                            proposal_sha=proposal_sha, sha=sha, usage=result.usage)
        self.say(f"{t.id}: {seat} reviewed the settlement")
        return review

    def _verified_review(self, t: _Task, reviewed: dict, proposed: dict, packet: dict, proposal: dict) -> dict:
        def blocked(problem: str) -> _Stop:
            return _Stop(Outcome("blocked", t.id, f"the batch.reviewed checkpoint {problem}"))

        problem = _checkpoint_problem(reviewed, t.challenger, "challenger")
        if problem:
            raise blocked(problem)
        if reviewed["packet_sha"] != proposed["packet_sha"]:
            raise blocked("names a different packet")
        if reviewed.get("proposal_sha") != proposed["sha"]:
            raise blocked("names a different proposal")
        review = self._verified_reply(t, t.challenger, _REVIEW, reviewed["sha"], schemas.REVIEW, "review", blocked)
        problem = batch.review_problem(review, proposal, packet, proposed["packet_sha"], proposed["sha"])
        if problem:
            raise blocked(f"holds a review that no longer passes its checks: {problem}")
        return review

    # Step 6
    def _rulings(self, t: _Task) -> None:
        pending = self._pending(self.events(t.id))
        if pending:
            ids = ", ".join(d.id for d in pending)
            self.say(f"{t.id}: needs a ruling on {ids}")
            raise _Stop(Outcome("needs_ruling", t.id, f"needs a ruling on {ids}", tuple(pending)))

    # Step 7
    def _contract(self, t: _Task) -> None:
        if self._first(t.id, "contract.frozen") is not None:
            return
        interface, points = self._contract_points(t)
        self._freeze(t, 1, interface, points)

    def _contract_points(self, t: _Task) -> tuple[str, list[Point]]:
        """The interface and decisions of contract v1: agreed points, then the ruled readings."""
        readings = {seat: self._reading(t, seat) for seat in t.seats}
        reveals = self._reveals(t)
        interface, points, disputes = decisions.settle(t.id, t.builder, t.challenger, readings, reveals)
        events = self.events(t.id)
        rulings = {e["dispute"]: e for e in events if e["type"] == "ruling.made"}
        points = list(points)
        for dispute in disputes:
            ruling = rulings[dispute.id]
            if dispute.kind == "reading":
                points.append(Point(dispute.question, ruling["text"], f"ruled {dispute.id}"))
            elif dispute.kind == "interface" and ruling["choice"] in ("b", "other"):
                interface = ruling["text"] if t.whole else f"{interface}\nAmended: {ruling['text']}"
        return interface, points

    @staticmethod
    def _mismatch(what: str, task: str, whole: bool) -> str:
        return (f"{what} does not match {task}'s interface protocol ({'whole' if whole else 'amending'}); "
                "it was written by another version of parallax")

    def _reveals(self, t: _Task) -> dict[str, dict]:
        """Both recorded reveals, by seat. Blocks when the challenger's was written under the other protocol."""
        reveals = {seat: self._stored(t, seat, "reveal", self._last(t.id, "reveal.done", seat=seat)["sha"])
                   for seat in t.seats}
        if ("interface_replacement" in reveals[t.challenger]) != t.whole:
            raise _Stop(Outcome("blocked", t.id, self._mismatch(f"{t.challenger}'s recorded reveal", t.id, t.whole)))
        return reveals

    def _check_protocol(self, t: _Task) -> None:
        """Blocks on the first recorded event written under another protocol than the task's opening.

        Interface cards and frozen contracts carry the interface protocol; `_batch_mismatch` covers the batch protocol.
        """
        for e in self.events(t.id):
            problem = _batch_mismatch(t, e)
            if problem:
                raise _Stop(Outcome("blocked", t.id, problem))
            if e["type"] == "dispute.opened" and e.get("kind") == "interface":
                what = e["id"]
            elif e["type"] == "contract.frozen":
                what = f"contract v{e['version']}"
            else:
                continue
            if (e.get("interface_protocol") == "whole") != t.whole:
                raise _Stop(Outcome("blocked", t.id, self._mismatch(what, t.id, t.whole)))

    def _freeze(self, t: _Task, version: int, interface: str, points: Sequence[Point]) -> None:
        # This task's own rulings are already decisions in the contract.
        in_force = [p for p in decisions.precedents(self.events()) if p["task"] != t.id]
        text = decisions.render_contract(t.id, version, t.text, interface, points, in_force)
        self._write(self._run_dir(t) / f"contract-v{version}.md", text)
        marker = {"interface_protocol": "whole"} if t.whole else {}
        self.journal.append("contract.frozen", t.id, version=version, sha=sha256_text(text), **marker)
        self.say(f"{t.id}: contract v{version} frozen")

    # Step 8
    def _braid(self, t: _Task) -> None:
        todo = [seat for seat in t.seats if self._last(t.id, "attempt.finished", role=t.role(seat)) is None]
        self._parallel([lambda seat=seat: self._attempt(t, seat) for seat in todo])

    def _attempt(self, t: _Task, seat: str) -> None:
        role = t.role(seat)
        n = 1 + sum(1 for e in self.events(t.id) if e["type"] == "attempt.finished" and e["role"] == role)
        clone = self._clone_of(t, seat)
        if self._last(t.id, "attempt.started", n=n, role=role) is not None:
            # An attempt that started but never finished: throw away whatever it left behind.
            gitops.git(clone, "reset", "--quiet", "--hard")
            gitops.git(clone, "clean", "-fdxq")
        self.journal.append("attempt.started", t.id, n=n, role=role, seat=seat)
        contract, _, _ = self._contract_text(t)
        if role == "builder":
            stage, brief, schema = "build", briefs.build(contract, self.cfg), schemas.BUILD
        else:
            stage, brief, schema = "probe", briefs.probe(contract, self.cfg), schemas.PROBE
        request = SeatRequest(stage, brief, clone, schema, writable=True, session=self._session(t, seat),
                              out_dir=self._artifact_dir(t, seat, stage))
        voids = []

        def void(request: SeatRequest, result: SeatResult, hits: list[str]) -> SeatRequest:
            self.journal.append("attempt.voided", t.id, n=n, role=role, seat=seat, hits=hits)
            session = result.session or request.session
            if session:
                self.seats[seat].discard(session, request.cwd)
            self._remove_clone(t, seat, request.cwd)
            fresh = self._new_clone(t, seat)
            voids.append(hits)
            self.say(f"{t.id}: {seat}'s {stage} named the other seat's folder; voided")
            if len(voids) >= 2:
                raise _Stop(Outcome("blocked", t.id, f"{seat}'s {stage} was voided twice: it named {', '.join(hits)}"))
            # A fresh session in a fresh clone, from the contract alone (never a retry brief).
            return replace(request, brief=brief, cwd=fresh, session=None, out_dir=self._artifact_dir(t, seat, stage))

        result, request = self._call(seat, request, task=t, void=void)
        usage = dict(result.usage)
        rejections = 0
        while True:
            if result.output["blocked"].strip():
                self.say(f"{t.id}: {seat} is blocked at {stage}: {result.output['blocked']}")
                raise _Stop(Outcome("blocked", t.id, f"{seat} is blocked at {stage}: {result.output['blocked']}"))
            mutants = result.output["mutants"] if role == "builder" else None
            reasons = self._validate(t, seat, request.cwd, mutants, f"{t.id} {role} {n}", result.output["files"])
            if not reasons:
                break
            reason = "; ".join(reasons)
            self.journal.append("attempt.rejected", t.id, n=n, role=role, seat=seat, reason=reason)
            rejections += 1
            self.say(f"{t.id}: {seat}'s {stage} rejected: {reason}")
            if rejections >= 2:
                raise _Stop(Outcome("blocked", t.id, f"{seat}'s {stage} was rejected twice: {reason}"))
            retry = SeatRequest(stage, briefs.retry(reason), request.cwd, schema, writable=True,
                                session=result.session, out_dir=self._artifact_dir(t, seat, stage))
            result, request = self._call(seat, retry, task=t, void=void)
            usage = _add_usage(usage, result.usage)
        self.journal.append("attempt.finished", t.id, n=n, role=role, seat=seat, commit=gitops.rev(request.cwd),
                            session=result.session, mutants=list(mutants or []), files=result.output["files"],
                            usage=usage)
        self.say(f"{t.id}: {seat}'s {stage} {n} finished")

    def _validate(self, t: _Task, seat: str, clone: Path, mutants: list[dict] | None, message: str,
                  files: list[dict], scope: Sequence[str] | None = None) -> list[str]:
        """Check a seat's work in its clone; when it passes, move mutants out and snapshot it.

        `mutants` is the builder's list to validate, or None when there are none to check
        (the challenger). `files` is the seat's declared list of everything it has changed since
        the task began; it must match the net change from the task base to the snapshot.
        Returns the reasons for rejecting the work; empty means it is committed in the clone.
        """
        if scope is None:
            scope = self.cfg.builder_scope if t.role(seat) == "builder" else self.cfg.challenger_scope
        changed = self._changed(clone)
        reasons = []
        outside = scopes.outside(changed, scope)
        if outside:
            reasons.append(f"you changed files outside your paths: {', '.join(outside)}")
        if mutants is not None:
            reasons.extend(validate_mutants(clone, clone / MUTANTS_DIR, mutants, self.cfg))
        if reasons:
            return reasons
        if mutants is not None:
            self._move_mutants(t, clone, mutants)
        gitops.snapshot(clone, message, exclude=[MUTANTS_DIR, SCRATCH_DIR])
        actual = gitops.delta(clone, t.base, "HEAD")
        outside = scopes.outside(list(actual), scope)
        reasons = ([f"you changed files outside your paths: {', '.join(outside)}"] if outside else [])
        reasons.extend(delivery.check(files, actual))
        if reasons:
            if mutants is not None:
                self._restore_mutants(t, clone, mutants)        # so a retry can keep them
            return reasons
        if self.cfg.lint:
            lint = run_command(self.cfg.lint, clone, self.cfg.check_timeout, env=_no_bytecode_env())
            # Put the clone back exactly as the snapshot left it: nothing lint writes is ever committed.
            gitops.git(clone, "reset", "--quiet", "--hard")
            gitops.git(clone, "clean", "-fdxq", "-e", SCRATCH_DIR)
            if lint.timed_out or lint.code != 0:
                if mutants is not None:
                    self._restore_mutants(t, clone, mutants)    # so a retry can keep them
                return [f"lint failed: {_tail(lint.output, 2000)}"]
        return []

    def _move_mutants(self, t: _Task, clone: Path, mutants: list[dict]) -> None:
        """Move `.parallax-mutants/<id>/` out of the builder's clone into `<task folder>/mutants/<id>/`."""
        store = t.dir / "mutants"
        store.mkdir(exist_ok=True)
        source = clone / MUTANTS_DIR
        for mutant in mutants:
            target = store / mutant["id"]
            if target.exists():
                self._remove_inside(store, target)
            shutil.move(str(source / mutant["id"]), str(target))
        if source.exists():
            self._remove_inside(clone, source)                  # anything unlisted never reaches a commit

    def _restore_mutants(self, t: _Task, clone: Path, mutants: list[dict]) -> None:
        for mutant in mutants:
            shutil.copytree(t.dir / "mutants" / mutant["id"], clone / MUTANTS_DIR / mutant["id"], dirs_exist_ok=True)

    # Step 9
    def _crossing(self, t: _Task, force: bool = False) -> dict:
        """Cross the seats' latest commits, unless the last crossing already did exactly that.

        `force` crosses again even then: a ruling's repair that changed nothing still costs a
        crossing, so the repair limit, and then the human, ends a loop that makes no progress.
        """
        builder, challenger = self._head(t, t.builder), self._head(t, t.challenger)
        last = self._last(t.id, "crossing.done")
        if not force and last is not None and (last["builder"], last["challenger"]) == (builder, challenger):
            return last
        n = 1 + sum(1 for e in self.events(t.id) if e["type"] == "crossing.done")
        work = t.dir / "cross"
        try:
            if not work.exists():
                gitops.clone_at(self.cfg.root, work, t.base)
            gitops.fetch(work, self._clone_of(t, t.builder), builder)
            gitops.fetch(work, self._clone_of(t, t.challenger), challenger)
        except gitops.GitError as exc:
            raise _Stop(Outcome("blocked", t.id, f"crossing {n}: could not gather the seats' commits "
                                                 f"(was a clone removed?): {scrub_paths(str(exc))}")) from None
        mutants = self._mutants(t)
        try:
            result = cross(work, t.base, builder, challenger, self.cfg, t.dir / "mutants", mutants)
        except gitops.GitError as exc:
            raise _Stop(Outcome("blocked", t.id, f"crossing {n}: the probes do not apply on the build: "
                                                 f"{scrub_paths(str(exc))}")) from None
        self._write(self._run_dir(t) / "crossings" / str(n) / "check.txt", result.output)
        evidence, mutant_of = self._reserve_evidence(t, result)
        done = self.journal.append("crossing.done", t.id, n=n, passed=result.passed, timed_out=result.timed_out,
                                   count=result.count, mutants=result.mutants, builder=builder,
                                   challenger=challenger, evidence=evidence, mutant_of=mutant_of)
        caught = sum(1 for s in result.mutants.values() if s == "killed")
        self.say(f"{t.id}: crossing {n}: check {'passed' if result.passed else 'failed'}"
                 + (f", {caught} of {len(result.mutants)} mutants caught" if result.passed else ""))
        return done

    def _reserve_evidence(self, t: _Task, result) -> tuple[list[str], dict[str, str]]:
        """Reserve dispute ids for this crossing's failures: one for a failed check, else one per
        unwaived surviving mutant. Returns (ids, {id: mutant id}) for the mutant ones."""
        start = self._next_dispute_number(t)
        if not result.passed:
            return [f"D-{t.id}-{start}"], {}
        waived = self._waived(t)
        survivors = [mid for mid, state in result.mutants.items() if state != "killed" and mid not in waived]
        ids = [f"D-{t.id}-{start + i}" for i in range(len(survivors))]
        return ids, dict(zip(ids, survivors))

    # After a crossing that is not clean
    def _after_failed_crossing(self, t: _Task, done: dict) -> Outcome | None:
        """Decide what follows failed crossing `done`. None means: cross again.

        In order, each part skipping itself when its events are already there:
        1. a pending dispute stops the run for the human;
        2. disputes opened after this crossing are all ruled: carry the rulings out (drop the
           task; amend the contract; the losing side repairs), then cross again;
        3. the repair rounds are used up: open an `unresolved` dispute;
        4. the answering seats respond to the evidence; if one conceded, cross again;
        5. nobody conceded: open a dispute per evidence item for the human.
        """
        events = self.events(t.id)
        self._rulings(t)                                                    # 1
        at = next(i for i, e in enumerate(events) if e["type"] == "crossing.done" and e["n"] == done["n"])
        tied = [Dispute.from_event(e) for e in events[at + 1:] if e["type"] == "dispute.opened"]
        if tied:                                                            # 2
            rulings = {e["dispute"]: e for e in events if e["type"] == "ruling.made"}
            drop = [d for d in tied if rulings[d.id]["choice"] == "drop"]
            if drop:
                return self._drop(t, rulings[drop[0].id])
            self._amend_contract(t)
            self._repairs(t, done, tied, rulings)
            return None
        failed = sum(1 for e in events if e["type"] == "crossing.done" and not self._clean(t, e))
        extra = sum(1 for e in events if e["type"] == "ruling.made" and e["kind"] == "unresolved")
        if failed >= 1 + self.cfg.max_repair_rounds + extra:               # 3
            output = self._check_output(t, done["n"])
            self._open_dispute(t, Dispute(
                f"D-{t.id}-{self._next_dispute_number(t)}", "unresolved",
                f"The check still fails after {done['n']} crossings. Who must change?",
                "The probes are wrong.", "The code is wrong.", *self._labels(t), _tail(output, 4000)))
            self._rulings(t)
        items = self._evidence_items(t, done)
        answering = list(t.seats) if not done["passed"] else [t.challenger]
        todo = [s for s in answering if self._response(t, done["n"], s, ()) is None]
        self._parallel([lambda s=s: self._respond(t, s, done, items) for s in todo])   # 4
        responses = {s: self._response(t, done["n"], s, ()) for s in answering}
        if any(self._conceded(t, done, s, r) for s, r in responses.items()):
            return None
        for item in items:                                                  # 5
            self._open_dispute(t, self._evidence_dispute(t, item, responses))
        self._rulings(t)
        raise AssertionError("unreachable: disputes were just opened")

    def _respond(self, t: _Task, seat: str, done: dict, items: Sequence[dict], ruling: str = "",
                 ruled: Sequence[str] = ()) -> None:
        """One respond call (with audit, validation and retry as for an attempt), then `response.done`."""
        role, n = t.role(seat), done["n"]
        clone = self._clone_of(t, seat)
        # Every accepted change is committed, so anything else in the clone is left from a crash.
        gitops.git(clone, "reset", "--quiet", "--hard")
        gitops.git(clone, "clean", "-fdxq")
        before = gitops.rev(clone)
        contract, _, _ = self._contract_text(t)
        brief = briefs.respond(role, contract, items, self.cfg, ruling=ruling)
        request = SeatRequest("respond", brief, clone, schemas.RESPOND, writable=True,
                              session=self._session(t, seat), out_dir=self._artifact_dir(t, seat, "respond"))
        voids = []

        def void(request: SeatRequest, result: SeatResult, hits: list[str]) -> SeatRequest:
            # As for an attempt, but the fresh clone starts at the seat's own last accepted commit.
            self.journal.append("attempt.voided", t.id, n=n, role=role, seat=seat, hits=hits, stage="respond")
            session = result.session or request.session
            if session:
                self.seats[seat].discard(session, request.cwd)
            fresh = self._new_clone(t, seat)
            gitops.fetch(fresh, request.cwd, before)
            gitops.git(fresh, "checkout", "--quiet", "--detach", before)
            self._remove_clone(t, seat, request.cwd)
            voids.append(hits)
            if len(voids) >= 2:
                raise _Stop(Outcome("blocked", t.id, f"{seat}'s respond was voided twice: it named {', '.join(hits)}"))
            return replace(request, brief=brief, cwd=fresh, session=None, out_dir=self._artifact_dir(t, seat, "respond"))

        result, request = self._call(seat, request, task=t, void=void)
        usage = dict(result.usage)
        rejections = 0
        while True:
            output = result.output
            if output["blocked"].strip():
                raise _Stop(Outcome("blocked", t.id, f"{seat} is blocked at respond: {output['blocked']}"))
            clone = request.cwd
            if not any(a["stance"] == "concede" for a in output["answers"]) and self._changed(clone, all_files=True):
                # A seat that contests every dispute may not change anything.
                gitops.git(clone, "reset", "--quiet", "--hard")
                gitops.git(clone, "clean", "-fdq")
            changed = bool(self._changed(clone))
            mutants = output["mutants"] if role == "builder" and changed else None
            reasons = self._validate(t, seat, clone, mutants, f"{t.id} {role} respond {n}", output["files"])
            if not reasons:
                break
            reason = "; ".join(reasons)
            self.journal.append("attempt.rejected", t.id, n=n, role=role, seat=seat, reason=reason, stage="respond")
            rejections += 1
            if rejections >= 2:
                raise _Stop(Outcome("blocked", t.id, f"{seat}'s respond was rejected twice: {reason}"))
            retry = SeatRequest("respond", briefs.retry(reason), clone, schemas.RESPOND, writable=True,
                                session=result.session, out_dir=self._artifact_dir(t, seat, "respond"))
            result, request = self._call(seat, retry, task=t, void=void)
            usage = _add_usage(usage, result.usage)
        self.journal.append("response.done", t.id, round=n, seat=seat, answers=output["answers"],
                            commit=gitops.rev(request.cwd), usage=usage, mutants=list(mutants or []),
                            session=result.session, ruling=list(ruled), files=output["files"])
        self.say(f"{t.id}: {seat} responded to crossing {n}")

    def _response(self, t: _Task, n: int, seat: str, ruled: Sequence[str]) -> dict | None:
        return self._last(t.id, "response.done", round=n, seat=seat, ruling=list(ruled))

    def _conceded(self, t: _Task, done: dict, seat: str, response: dict) -> bool:
        """Answered concede to a dispute and actually changed something."""
        head = done["builder"] if seat == t.builder else done["challenger"]
        return any(a["stance"] == "concede" for a in response["answers"]) and response["commit"] != head

    def _repairs(self, t: _Task, done: dict, tied: Sequence[Dispute], rulings: Mapping[str, dict]) -> None:
        """The losing side of each ruled dispute repairs, with the ruling in its brief."""
        items = {item["id"]: item for item in self._evidence_items(t, done)}
        work: dict[str, list[tuple[Dispute, dict]]] = {}
        for dispute in tied:
            ruling = rulings[dispute.id]
            if dispute.kind == "mutant" and ruling["choice"] == "b":
                continue                                            # waived: nothing to repair
            seat = t.challenger if ruling["choice"] == "a" else t.builder
            work.setdefault(seat, []).append((dispute, ruling))
        calls = []
        for seat, pairs in work.items():
            ruled = [d.id for d, _ in pairs]
            if self._response(t, done["n"], seat, ruled) is not None:
                continue
            evidence = [items.get(d.id) or {"id": d.id, "kind": "check", "text": d.evidence} for d, _ in pairs]
            text = "\n\n".join(r["text"] for _, r in pairs)
            calls.append(lambda seat=seat, evidence=evidence, text=text, ruled=ruled:
                         self._respond(t, seat, done, evidence, ruling=text, ruled=ruled))
        self._parallel(calls)

    def _amend_contract(self, t: _Task) -> None:
        """Freeze the next contract version when a ruling since the last one amends it."""
        events = self.events(t.id)
        frozen = [i for i, e in enumerate(events) if e["type"] == "contract.frozen"]
        if not any(self._amendment(e) for e in events[frozen[-1] + 1:]):
            return
        interface, points = self._contract_points(t)
        for e in events[frozen[0] + 1:]:
            points.extend(self._amendment(e))
        self._freeze(t, events[frozen[-1]]["version"] + 1, interface, points)

    @staticmethod
    def _amendment(event: dict) -> list[Point]:
        """What a ruling made after contract v1 adds to the contract: a check ruling's answer,
        and any limitation (what is no longer promised)."""
        if event["type"] != "ruling.made":
            return []
        points = []
        if event["kind"] == "check":
            points.append(Point(event["question"], event["text"], f"ruled {event['dispute']}"))
        if event.get("limitation"):
            points.append(Point("What is no longer promised?", event["limitation"], f"ruled {event['dispute']}"))
        return points

    def _drop(self, t: _Task, ruling: dict) -> Outcome:
        """Land only the record of the task: its ledger events and the precedents."""
        if self._ended_on_main(t, "task.dropped"):
            self._finish(t, f"parallax/ready/{t.id}")
            return Outcome("dropped", t.id, f"{t.id} was dropped")
        if self._last(t.id, "task.dropped") is None:
            self.journal.append("task.dropped", t.id, reason=ruling["text"])
        return self._integrate(t, [], {}, f"{t.id}: dropped", [], status="dropped")

    # Chores
    def _solo(self, t: _Task) -> Outcome:
        """A chore: one builder call, validated with scope ** and lint, then the check once."""
        seat = t.builder
        if self._last(t.id, "attempt.finished", role="builder") is None:
            clone = self._clone_of(t, seat)
            if self._last(t.id, "attempt.started", n=1, role="builder") is not None:
                gitops.git(clone, "reset", "--quiet", "--hard")
                gitops.git(clone, "clean", "-fdxq")
            self.journal.append("attempt.started", t.id, n=1, role="builder", seat=seat)
            request = SeatRequest("solo", briefs.solo(t.text, self.cfg), clone, schemas.SOLO, writable=True,
                                  session=None, out_dir=self._artifact_dir(t, seat, "solo"))
            result, request = self._call(seat, request, task=t)
            usage, rejections = dict(result.usage), 0
            while True:
                if result.output["blocked"].strip():
                    raise _Stop(Outcome("blocked", t.id, f"{seat} is blocked at solo: {result.output['blocked']}"))
                reasons = self._validate(t, seat, request.cwd, None, f"{t.id} solo", result.output["files"],
                                         scope=("**",))
                if not reasons:
                    break
                reason = "; ".join(reasons)
                self.journal.append("attempt.rejected", t.id, n=1, role="builder", seat=seat, reason=reason)
                rejections += 1
                if rejections >= 2:
                    raise _Stop(Outcome("blocked", t.id, f"{seat}'s solo was rejected twice: {reason}"))
                retry = SeatRequest("solo", briefs.retry(reason), request.cwd, schemas.SOLO, writable=True,
                                    session=result.session, out_dir=self._artifact_dir(t, seat, "solo"))
                result, request = self._call(seat, retry, task=t)
                usage = _add_usage(usage, result.usage)
            self.journal.append("attempt.finished", t.id, n=1, role="builder", seat=seat,
                                commit=gitops.rev(request.cwd), session=result.session, mutants=[],
                                files=result.output["files"], usage=usage)
        head = self._head(t, seat)
        last = self._last(t.id, "crossing.done")
        if last is None or last["builder"] != head:
            work = t.dir / "cross"
            try:
                if not work.exists():
                    gitops.clone_at(self.cfg.root, work, t.base)
                gitops.fetch(work, self._clone_of(t, seat), head)
                gitops.git(work, "checkout", "--quiet", "--force", "--detach", head)
                gitops.git(work, "clean", "-fdxq")
            except gitops.GitError as exc:
                raise _Stop(Outcome("blocked", t.id, f"could not check the chore: {scrub_paths(str(exc))}")) from None
            check = run_command(self.cfg.check, work, self.cfg.check_timeout, env=_no_bytecode_env())
            passed = check.code == 0 and not check.timed_out
            self._write(self._run_dir(t) / "crossings" / "1" / "check.txt", check.output)
            last = self.journal.append("crossing.done", t.id, n=1, passed=passed, timed_out=check.timed_out,
                                       count=receipt.probe_count(check.output, self.cfg.count_pattern), mutants={},
                                       builder=head, challenger=None, evidence=[], mutant_of={})
        if not last["passed"]:
            raise _Stop(Outcome("blocked", t.id, f"the check failed on the chore: "
                                                 f"{_tail(self._check_output(t, 1), 2000)}"))
        landed = self._landed_on_main(t)
        if landed is not None:
            self._finish(t, f"parallax/ready/{t.id}")
            return Outcome("landed", t.id, f"landed {landed[:12]}", commit=landed)
        integrated = self._last(t.id, "task.integrated")
        if integrated is None:
            integrated = self.journal.append("task.integrated", t.id, verdict=receipt.verdict("chore", 0, 0, []),
                                             checks="check passed", limitations=[])
        message = (f"{t.id}: {_short_title(t.title)}\n\n"
                   + receipt.trailers(t.id, None, self._seat_label(seat), None, integrated["checks"],
                                      integrated["verdict"], integrated["limitations"]))
        return self._integrate(t, [head], {}, message, self._declared(t, [seat]))

    # Disputes and evidence
    def _clean(self, t: _Task, done: dict, waived: set[str] | None = None) -> bool:
        """Passed, and every mutant was caught or waived."""
        waived = self._waived(t) if waived is None else waived
        return done["passed"] and all(s == "killed" or m in waived for m, s in done["mutants"].items())

    @staticmethod
    def _mutant_of(events: Sequence[dict]) -> dict[str, str]:
        """{dispute id: mutant id} over every crossing's reserved mutant evidence."""
        found: dict[str, str] = {}
        for e in events:
            if e["type"] == "crossing.done":
                found.update(e.get("mutant_of") or {})
        return found

    def _waived(self, t: _Task) -> set[str]:
        events = self.events(t.id)
        mutant_of = self._mutant_of(events)
        return {mutant_of[e["dispute"]] for e in events
                if e["type"] == "ruling.made" and e["kind"] == "mutant" and e["choice"] == "b"
                and e["dispute"] in mutant_of}

    def _next_dispute_number(self, t: _Task) -> int:
        """Continue the task's dispute numbering past every id opened or reserved."""
        pattern = re.compile(rf"D-{re.escape(t.id)}-(\d+)")
        used = [0]
        for e in self.events(t.id):
            ids = [e["id"]] if e["type"] == "dispute.opened" else e.get("evidence", []) if e["type"] == "crossing.done" else []
            used.extend(int(m.group(1)) for i in ids if (m := pattern.fullmatch(i)))
        return max(used) + 1

    def _labels(self, t: _Task) -> tuple[str, str]:
        return f"{t.builder} (builder)", f"{t.challenger} (challenger)"

    def _check_output(self, t: _Task, n: int) -> str:
        try:
            return (self._run_dir(t) / "crossings" / str(n) / "check.txt").read_text(encoding="utf-8")
        except OSError:
            return "(the check output of this crossing is missing)"

    def _evidence_items(self, t: _Task, done: dict) -> list[dict]:
        """`[{id, kind, text}]` for the crossing's reserved dispute ids; text has no absolute paths."""
        if not done["passed"]:
            return [{"id": i, "kind": "check", "text": _tail(self._check_output(t, done["n"]), 4000)}
                    for i in done["evidence"]]
        items = []
        builder_clone = self._clone_of(t, t.builder)
        for dispute_id, mid in (done.get("mutant_of") or {}).items():
            mutant = next((m for m in reversed(self._all_mutants(t)) if m["id"] == mid), {"description": mid, "files": []})
            diffs = []
            for rel in mutant["files"]:
                real = gitops.show_file(builder_clone, done["builder"], rel) or ""
                try:
                    fake = (t.dir / "mutants" / mid).joinpath(*rel.split("/")).read_text(encoding="utf-8")
                except OSError:
                    fake = ""
                diffs.extend(difflib.unified_diff(real.splitlines(True), fake.splitlines(True), f"a/{rel}", f"b/{rel}"))
            items.append({"id": dispute_id, "kind": "mutant",
                          "text": scrub_paths(f"{mutant['description']}\n\n{''.join(diffs)}")})
        return items

    def _all_mutants(self, t: _Task) -> list[dict]:
        return [m for e in self.events(t.id) if e.get("seat") == t.builder
                and e["type"] in ("attempt.finished", "response.done") for m in (e.get("mutants") or [])]

    def _evidence_dispute(self, t: _Task, item: dict, responses: Mapping[str, dict]) -> Dispute:
        def position(seat: str) -> str:
            response = responses.get(seat)
            answer = next((a for a in (response or {}).get("answers", []) if a["dispute"] == item["id"]), None)
            text = " ".join(x for x in ((answer or {}).get("cite", ""), (answer or {}).get("why", "")) if x.strip())
            return text or "(no reason given)"

        if item["kind"] == "check":
            return Dispute(item["id"], "check", "The check fails. Whose reading of the contract is right?",
                           position(t.builder), position(t.challenger), *self._labels(t), item["text"])
        mid = self._mutant_of(self.events(t.id))[item["id"]]
        description = item["text"].split("\n\n", 1)[0]
        return Dispute(item["id"], "mutant", f"Mutant {mid} survived: {description}. Must the probes catch it?",
                       "Yes: it breaks the contract.", position(t.challenger), *self._labels(t), item["text"])

    # Step 10
    def _land(self, t: _Task) -> Outcome:
        landed = self._landed_on_main(t)
        if landed is not None:
            # The process died after main advanced but before the journal was dropped.
            self._finish(t, f"parallax/ready/{t.id}")
            return Outcome("landed", t.id, f"landed {landed[:12]}", commit=landed)
        events = self.events(t.id)
        integrated = self._last(t.id, "task.integrated")
        if integrated is None:
            crossings = [e for e in events if e["type"] == "crossing.done"]
            last = crossings[-1]
            waived = self._waived(t)
            failed = sum(1 for e in crossings if not self._clean(t, e, waived))
            rulings = sum(1 for e in events if e["type"] == "ruling.made")
            limitations = self._limitations(events)
            integrated = self.journal.append(
                "task.integrated", t.id, verdict=receipt.verdict(t.kind, failed, rulings, limitations),
                checks=receipt.checks_line(last["count"], last["mutants"], sorted(waived)),
                limitations=limitations)
        _, _, contract_sha = self._contract_text(t)
        built_by, challenged_by = (self._seat_label(s) for s in t.seats)
        message = (f"{t.id}: {_short_title(t.title)}\n\n"
                   + receipt.trailers(t.id, contract_sha, built_by, challenged_by, integrated["checks"],
                                      integrated["verdict"], integrated["limitations"]))
        heads = [self._head(t, t.builder), self._head(t, t.challenger)]
        files = {f".parallax/contracts/{t.id}.md": self._contract_text(t)[0]}
        return self._integrate(t, heads, files, message, self._declared(t, t.seats))

    def _integrate(self, t: _Task, heads: Sequence[str], files: Mapping[str, str], message: str,
                   declared: Sequence[str] | None, status: str = "landed") -> Outcome:
        """The landing loop: build the commit on current main in `<task folder>/land`, then advance main.

        `heads` are applied in order as `base..head`; `files` are written on top. The ledger
        and PRECEDENTS.md are always written. Task 11's ledger-only drop reuses this with no heads.

        `declared` is every path the seats listed in their accepted `files`; None means the
        task began before delivery accounting, so the gate is skipped. Nothing is committed unless
        every staged change (against current main) is declared or is a conductor record, and
        the commit that results has exactly the tree that was staged.
        """
        park = f"parallax/ready/{t.id}"
        root = self.cfg.root
        for _ in range(_LAND_TRIES):
            expected = gitops.rev(root, self.cfg.main)
            land = t.dir / "land"
            if land.exists():
                self._remove_inside(t.dir, land)
            gitops.clone_at(root, land, expected)
            try:
                for seat, head in zip(t.seats, heads):
                    gitops.fetch(land, self._clone_of(t, seat), head)
                    gitops.apply_range(land, t.base, head)
            except gitops.GitError as exc:
                raise _Stop(Outcome("blocked", t.id, f"the task's changes do not apply on {self.cfg.main}: "
                                                     f"{scrub_paths(str(exc))}")) from None
            publish(self.journal.events(t.id), land / LEDGER)
            for rel, text in files.items():
                self._write(land / rel, text)
            self._write(land / ".parallax" / "PRECEDENTS.md",
                        decisions.render_precedents(decisions.precedents(self.events())))
            gitops.git(land, "add", "-A")
            if declared is not None:
                allowed = {*declared, LEDGER, ".parallax/PRECEDENTS.md", *files}
                extra = sorted(p for p in gitops.delta(land, expected) if p not in allowed)
                if extra:
                    raise _Stop(Outcome("blocked", t.id, "landing would add changes no seat declared: "
                                                         + ", ".join(extra)))
            tree = gitops.git(land, "write-tree")
            check = run_command(self.cfg.check, land, self.cfg.check_timeout, env=_no_bytecode_env())
            if check.timed_out or check.code != 0:
                raise _Stop(Outcome("blocked", t.id, f"the check failed on top of {self.cfg.main}: "
                                                     f"{_tail(check.output, 2000)}"))
            new = gitops.commit_staged(land, message, gitops.identity(root))
            if gitops.git(land, "rev-parse", f"{new}^{{tree}}") != tree:
                raise _Stop(Outcome("blocked", t.id, "a commit hook changed the landing commit; main was not moved"))
            try:
                moved = gitops.advance_main(root, self.cfg.main, land, new, expected, park)
            except gitops.MainMoved:
                continue
            if moved == "parked":
                reason = f"main has uncommitted changes in the way; the result is on {park}"
                self.journal.append("task.parked", t.id, branch=park, reason=reason)
                self.say(f"{t.id}: parked on {park}")
                return Outcome("parked", t.id, reason, commit=new)
            self._finish(t, park)
            self.say(f"{t.id}: {status} {new[:12]}; " + ", ".join(self._tokens(t, s) for s in t.seats))
            return Outcome(status, t.id, f"{status} {new[:12]}", commit=new)
        raise _Stop(Outcome("blocked", t.id, f"{self.cfg.main} kept moving; try again"))

    def _ended_on_main(self, t: _Task, type: str) -> bool:
        """Main's ledger already records `type` (task.integrated or task.dropped) for this task."""
        text = gitops.show_file(self.cfg.root, self.cfg.main, LEDGER)
        return bool(text) and any(e.get("task") == t.id and e.get("type") == type for e in parse_lines(text))

    @staticmethod
    def _changed(clone: Path, all_files: bool = False) -> list[str]:
        """Paths changed in the clone, without the mutant and scratch folders unless `all_files`."""
        paths = gitops.changed_paths(clone)
        return paths if all_files else [p for p in paths if not p.startswith((f"{MUTANTS_DIR}/", f"{SCRATCH_DIR}/"))]

    def _landed_on_main(self, t: _Task) -> str | None:
        """The commit on main that landed this task, when main's ledger already records it."""
        if not self._ended_on_main(t, "task.integrated"):
            return None
        # Anchored to a whole trailer line, so clamp-001 never matches clamp-0010. Task ids are
        # [A-Za-z0-9._-]; "." is the only character special in an extended regex.
        found = gitops.git(self.cfg.root, "log", "-1", "--format=%H", "--extended-regexp",
                           f"--grep=^Parallax-Task: {t.id.replace('.', chr(92) + '.')}$", self.cfg.main)
        return found or gitops.rev(self.cfg.root, self.cfg.main)

    def _finish(self, t: _Task, park: str) -> None:
        """After main advanced: forget the task's journal, sessions, state folder and park branch."""
        sessions = {s: (self._session(t, s), self._clone_of(t, s)) for s in t.seats}
        self.journal.drop_task(t.id)
        for seat, (session, clone) in sessions.items():
            if session:
                self.seats[seat].discard(session, clone)
        task_root = self.home / repo_key(self.cfg.root)
        if t.dir.parent == task_root and t.dir.name == t.id and not gitops.remove_tree(t.dir):
            self.say(f"{t.id}: could not remove the task's state folder; remove it by hand")
        if gitops.git(self.cfg.root, "branch", "--list", park):
            gitops.git(self.cfg.root, "branch", "-D", park)

    # ------------------------------------------------------ task bookkeeping

    def _session(self, t: _Task, seat: str) -> str | None:
        """The seat's live session: from its reading, replaced by later attempts, cleared by a void."""
        session = None
        for e in self.events(t.id):
            if e.get("seat") != seat:
                continue
            if e["type"] in ("reading.sealed", "attempt.finished", "response.done"):
                session = e.get("session", session)
            elif e["type"] == "attempt.voided":
                session = None
        return session

    def _head_event(self, t: _Task, seat: str) -> dict:
        """The seat's latest accepted event (attempt.finished, or a later response.done)."""
        head = None
        for e in self.events(t.id):
            if e.get("seat") == seat and e["type"] in ("attempt.finished", "response.done") and e.get("commit"):
                head = e
        if head is None:
            raise RuntimeError(f"{seat} has no finished attempt in {t.id}")
        return head

    def _head(self, t: _Task, seat: str) -> str:
        """The seat's latest accepted commit (attempt.finished, or a later response.done)."""
        return self._head_event(t, seat)["commit"]

    def _files(self, t: _Task, seat: str) -> list[dict] | None:
        """The accepted `files` list recorded with the seat's head; None when that event has none
        (the task began before delivery accounting)."""
        return self._head_event(t, seat).get("files")

    def _declared(self, t: _Task, seats: Sequence[str]) -> list[str] | None:
        """Every path the given seats declared, or None (with a note) when any seat has no list."""
        lists = [self._files(t, seat) for seat in seats]
        if any(rows is None for rows in lists):
            self.say(f"{t.id}: landing without delivery accounting (the task started before it existed)")
            return None
        return sorted({row["path"] for rows in lists for row in rows})

    def _mutants(self, t: _Task) -> list[dict]:
        """The builder's latest mutant list (an event with a non-empty `mutants` list wins)."""
        mutants: list[dict] = []
        for e in self.events(t.id):
            if (e.get("seat") == t.builder and e["type"] in ("attempt.finished", "response.done")
                    and isinstance(e.get("mutants"), list) and e["mutants"]):
                mutants = e["mutants"]
        return mutants

    def _contract_text(self, t: _Task) -> tuple[str, int, str]:
        """(text, version, sha) of the latest frozen contract, checked against its recorded sha."""
        frozen = self._last(t.id, "contract.frozen")
        path = self._run_dir(t) / f"contract-v{frozen['version']}.md"
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            text = None
        if text is None or sha256_text(text) != frozen["sha"]:
            raise _Stop(Outcome("blocked", t.id, f"{path.name} is missing or no longer matches its frozen sha"))
        return text, frozen["version"], frozen["sha"]

    @staticmethod
    def _limitations(events: Sequence[dict]) -> list[str]:
        return [e["limitation"] for e in events if e["type"] == "ruling.made" and e.get("limitation")]

    def _seat_label(self, seat: str) -> str:
        s = self.seats[seat]
        return f"{seat} {s.model}/{s.effort}"

    def _tokens(self, t: _Task, seat: str) -> str:
        total = {"input": 0, "output": 0}
        for e in self.events(t.id):
            if e.get("seat") == seat and isinstance(e.get("usage"), dict):
                total = _add_usage(total, e["usage"])
        return f"{seat} {total['input']} in / {total['output']} out"

    @staticmethod
    def _remove_inside(parent: Path, path: Path) -> None:
        """Delete `path`, which must sit directly inside `parent` (a folder the conductor owns)."""
        if Path(path).resolve().parent != Path(parent).resolve():
            raise RuntimeError(f"refusing to remove {path}: it is not directly inside {parent}")
        if not gitops.remove_tree(path):
            raise RuntimeError(f"could not remove {path}; close anything using it")

    # ------------------------------------------------------------- seat calls

    def _call(self, seat: str, request: SeatRequest, *, task: _Task,
              void: Callable[[SeatRequest, SeatResult, list[str]], SeatRequest] | None = None,
              check: Callable[[dict], str | None] | None = None) -> tuple[SeatResult, SeatRequest]:
        """Call `seat` under the seat-call rules; return the good result and the request that produced it.

        - Before every call the task's state folder must still be private.
        - After every call the event stream is audited for the other seat's clones. On a hit,
          `void(request, result, hits)` cleans up and returns the request to run instead (it
          raises `_Stop` itself to give up); with no `void`, a hit blocks the task.
        - Bad output (`not result.ok`, or `check(output)` returning a reason) is retried once;
          a second failure appends `seat.failed` and blocks. A seat error retries the same
          request. A `check` rejection retries with the brief of the request this call was given
          (or last returned by `void`) plus `briefs.rejected(brief, reason)`, so reasons never stack.

        Exceptions a seat raises propagate unchanged. Every other way out is `_Stop`.
        """
        t = task
        failures = 0
        base = request.brief
        while True:
            if not folders.is_private(t.dir):
                raise _Stop(Outcome("blocked", t.id, "the task's state folder is no longer private"))
            result = self.seats[seat].run(request)
            # The other seat's clones, and the conductor's own folders in the task's state folder
            # (spec: "any path belonging to the other seat or to the state folder"). A seat's own
            # clone sits in the same folder, so the task folder itself cannot be forbidden.
            forbidden = self._clones_of(t, t.other(seat)) + [
                str(t.dir / name) for name in ("cross", "land", "mutants", "artifacts")]
            hits = audit.forbidden_hits(result.events or "", forbidden)
            if hits:
                if void is None:
                    error = f"named the other seat's folder: {', '.join(hits)}"
                    self.journal.append("seat.failed", t.id, stage=request.stage, seat=seat, error=error)
                    raise _Stop(Outcome("blocked", t.id, f"{seat} failed at {request.stage}: {error}"))
                request = void(request, result, hits)
                base = request.brief
                failures = 0
                continue
            error = result.error if not result.ok else (check(result.output) if check else None)
            if result.ok and error is None:
                return result, request
            error = error or "the seat returned no output"
            failures += 1
            if failures < 2:
                if result.ok:
                    request = replace(request, brief=briefs.rejected(base, error))
                continue
            self.journal.append("seat.failed", t.id, stage=request.stage, seat=seat, error=error)
            self.say(f"{t.id}: {seat} failed at {request.stage}: {error}")
            raise _Stop(Outcome("blocked", t.id, f"{seat} failed at {request.stage}: {error}"))

    @staticmethod
    def _parallel(calls: Sequence[Callable[[], object]]) -> None:
        """Run each call in its own thread; wait for all, then re-raise the first exception raised."""
        errors: list[BaseException] = []
        guard = threading.Lock()

        def run(call):
            try:
                call()
            except BaseException as exc:            # noqa: BLE001 - re-raised below
                with guard:
                    errors.append(exc)

        threads = [threading.Thread(target=run, args=(call,), daemon=True) for call in calls]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        if errors:
            raise errors[0]

    # ------------------------------------------------------------ the journal

    def _first(self, task: str, type: str, **match) -> dict | None:
        for event in self.events(task):
            if event["type"] == type and all(event.get(k) == v for k, v in match.items()):
                return event
        return None

    def _last(self, task: str, type: str, **match) -> dict | None:
        for event in reversed(self.events(task)):
            if event["type"] == type and all(event.get(k) == v for k, v in match.items()):
                return event
        return None

    def _sealed(self, t: _Task, seat: str) -> dict | None:
        return self._last(t.id, "reading.sealed", seat=seat)

    @staticmethod
    def _pending(events: Sequence[dict]) -> list[Dispute]:
        ruled = {e["dispute"] for e in events if e["type"] == "ruling.made"}
        return [Dispute.from_event(e) for e in events if e["type"] == "dispute.opened" and e["id"] not in ruled]

    def _open_dispute(self, t: _Task, dispute: Dispute) -> None:
        marker = {"interface_protocol": "whole"} if t.whole and dispute.kind == "interface" else {}
        self.journal.append("dispute.opened", t.id, **dispute.to_fields(), **marker)
        self._write(self._run_dir(t) / "cards" / f"{dispute.id}.md", decisions.render_card(dispute))

    # ------------------------------------------------------- the state folder

    def _run_dir(self, t: _Task) -> Path:
        return self.cfg.run_dir / t.id

    @staticmethod
    def _write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")

    def _clones_of(self, t: _Task, seat: str) -> list[str]:
        return [e["path"] for e in self.events(t.id) if e["type"] == "checkout.created" and e["seat"] == seat]

    def _clone_of(self, t: _Task, seat: str) -> Path | None:
        clones = self._clones_of(t, seat)
        return Path(clones[-1]) if clones else None

    def _new_clone(self, t: _Task, seat: str) -> Path:
        path = t.dir / f"{seat}-{secrets.token_hex(4)}"
        gitops.clone_at(self.cfg.root, path, t.base)
        self.journal.append("checkout.created", t.id, seat=seat, path=str(path))
        return path

    def _remove_clone(self, t: _Task, seat: str, path: Path) -> None:
        """Delete a seat's clone: only a path a checkout.created recorded, directly inside the task's folder."""
        path = Path(path)
        if str(path) not in self._clones_of(t, seat):
            raise RuntimeError(f"refusing to remove {path}: not a recorded clone of {seat}")
        if path.resolve().parent != t.dir.resolve() or not path.name.startswith(f"{seat}-"):
            raise RuntimeError(f"refusing to remove {path}: not a clone inside the task's state folder")
        if not gitops.remove_tree(path):
            raise _Stop(Outcome("blocked", t.id, f"could not remove {seat}'s voided clone; close anything using it"))

    def _artifact_dir(self, t: _Task, seat: str, stage: str) -> Path:
        """Reserve the next `artifacts/<nn>-<seat>-<stage>/`."""
        root = t.dir / "artifacts"
        with self._artifact_lock:
            root.mkdir(exist_ok=True)
            numbers = [int(m.group(1)) for p in root.iterdir() if (m := re.match(r"(\d+)-", p.name))]
            path = root / f"{max(numbers, default=0) + 1:02d}-{seat}-{stage}"
            path.mkdir()
            return path

    @staticmethod
    def _store(out_dir: Path, output: dict) -> str:
        """Write the output in canonical form as `output.json`; return its sha."""
        text = _canonical(output)
        (out_dir / "output.json").write_text(text, encoding="utf-8", newline="\n")
        return sha256_text(text)

    def _stored(self, t: _Task, seat: str, stage: str, sha: str) -> dict:
        """The stored output of `seat` at `stage` whose sha is `sha` (the sealed one), newest first."""
        root = t.dir / "artifacts"
        pattern = re.compile(rf"(\d+)-{re.escape(seat)}-{re.escape(stage)}")
        found = sorted(((int(m.group(1)), p) for p in (root.iterdir() if root.is_dir() else [])
                        if (m := pattern.fullmatch(p.name))), reverse=True)
        for _, path in found:
            try:
                text = (path / "output.json").read_text(encoding="utf-8")
            except OSError:
                continue
            if sha256_text(text) == sha:
                return json.loads(text)
        raise _Stop(Outcome("blocked", t.id, f"the recorded {stage} of {seat} is missing from the state folder"))

    def _reading(self, t: _Task, seat: str) -> dict:
        return self._stored(t, seat, "reading", self._sealed(t, seat)["sha"])
