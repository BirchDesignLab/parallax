"""Pure settlement, ruling and rendering helpers for the conductor."""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass, fields

from parallax.redact import scrub_paths


_SCOPES = {"reading": "project", "interface": "project", "check": "project",
           "mutant": "task", "unresolved": "task"}
_TASK = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def _text(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value


def _task(task: str) -> None:
    if not isinstance(task, str) or _TASK.fullmatch(task) is None:
        raise ValueError("invalid task id")


def _positive(value: int, name: str) -> None:
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _rendered(text: str) -> str:
    # Absolute paths are scrubbed, never rejected: a card's evidence is check output full of
    # scratch-clone paths, and a task may mention a URL or a route like `GET /users`.
    return scrub_paths(text.replace("\r\n", "\n").replace("\r", "\n"))


@dataclass(frozen=True)
class Point:
    question: str
    answer: str
    source: str

    def __post_init__(self):
        for field in fields(self):
            _text(getattr(self, field.name), field.name)


@dataclass(frozen=True)
class Dispute:
    id: str
    kind: str
    question: str
    a: str
    b: str
    a_label: str
    b_label: str
    evidence: str = ""

    def __post_init__(self):
        for field in fields(self):
            _text(getattr(self, field.name), field.name)
        default_scope(self.kind)

    def to_fields(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_event(event: dict) -> Dispute:
        # Journal metadata is not part of a dispute. Older events may omit the
        # optional evidence field; missing required fields are still errors.
        return Dispute(**{field.name: event[field.name] for field in fields(Dispute)
                          if field.name != "evidence"}, evidence=event.get("evidence", ""))


def witness_problem(verdict: dict) -> str | None:
    """Why a verdict's witness is unusable, or None: agreeing verdicts and witnesses that show a difference pass."""
    if verdict["agree"]:
        return None
    index = verdict["index"]
    witness = verdict.get("witness") or {}
    missing = [name for name in ("scenario", "observation", "theirs", "mine") if not witness.get(name, "").strip()]
    if missing:
        return (f"verdict {index}: a disagreement needs a witness with scenario, observation, theirs and mine; "
                f"missing {', '.join(missing)}")
    theirs, mine = witness["theirs"].strip(), witness["mine"].strip()
    if theirs == mine:
        return (f"verdict {index}: the witness predicts the same result under both answers ({theirs}); "
                f"give a scenario where the two answers commit to different results, "
                f"or agree if you accept their whole answer")
    return None


def _evidence(owner: str, reviewer: str, builder: str, challenger: str, decision: dict, verdict: dict) -> str:
    witness = verdict.get("witness") or {}

    def field(name: str) -> str:
        return _text(witness.get(name, ""), name).strip()

    theirs, mine = field("theirs"), field("mine")
    pred_a, pred_b = (theirs, mine) if owner == builder else (mine, theirs)
    own_why = _text(decision["why"], "why").strip() or "(none given)"
    their_why = _text(verdict["why"], "why").strip() or "(none given)"
    why_a, why_b = (own_why, their_why) if owner == builder else (their_why, own_why)
    lines = []
    if field("scenario"):
        lines += [f"Witness, written by {reviewer}:", f"  Scenario: {field('scenario')}",
                  f"  Observe: {field('observation')}",
                  f"  Under a ({builder}), {reviewer} predicts: {pred_a}",
                  f"  Under b ({challenger}), {reviewer} predicts: {pred_b}"]
        if field("decided_by"):
            lines.append(f"  {reviewer} cites: {field('decided_by')}")
    lines += ["Reasons:", f"  a) {builder}: {why_a}", f"  b) {challenger}: {why_b}"]
    return "\n".join(lines)


def settle(task: str, builder: str, challenger: str, readings: dict[str, dict],
           reveals: dict[str, dict], start: int = 1) -> tuple[str, list[Point], list[Dispute]]:
    _task(task)
    _positive(start, "start")
    if not _text(builder, "builder") or not _text(challenger, "challenger") or builder == challenger:
        raise ValueError("builder and challenger must be distinct, nonempty seat names")
    points = []
    disputes = []
    labels = (f"{builder} (builder)", f"{challenger} (challenger)")
    interface = _text(readings[builder]["interface"], "interface")
    for owner, reviewer in ((builder, challenger), (challenger, builder)):
        decisions = readings[owner]["decisions"]
        verdicts = reveals[reviewer]["verdicts"]
        if not isinstance(decisions, list) or not isinstance(verdicts, list):
            raise ValueError("decisions and verdicts must be lists")
        by_index = {}
        for verdict in verdicts:
            if not isinstance(verdict, dict):
                raise ValueError(f"{reviewer} verdict must be an object")
            index = verdict.get("index")
            if type(index) is not int or not 0 <= index < len(decisions):
                raise ValueError(f"{reviewer} gave an invalid verdict index")
            if index in by_index:
                raise ValueError(f"{reviewer} gave duplicate verdicts on {owner} decision {index}")
            if type(verdict.get("agree")) is not bool:
                raise ValueError(f"{reviewer} verdict agree must be a boolean")
            by_index[index] = verdict
        for index, decision in enumerate(decisions):
            if index not in by_index:
                raise ValueError(f"{reviewer} gave no verdict on {owner} decision {index}")
            question = _text(decision["question"], "question")
            answer = _text(decision["answer"], "answer")
            verdict = by_index[index]
            if verdict["agree"]:
                points.append(Point(question, answer, "agreed"))
            else:
                counter = _text(verdict["counter"], "counter")
                a, b = (answer, counter) if owner == builder else (counter, answer)
                disputes.append(Dispute(f"D-{task}-{start + len(disputes)}", "reading",
                                        question, a, b, *labels,
                                        _evidence(owner, reviewer, builder, challenger, decision, verdict)))
    reveal = reveals[challenger]
    if type(reveal.get("interface_ok")) is not bool:
        raise ValueError("interface_ok must be a boolean")
    if not reveal["interface_ok"]:
        objection = _text(reveal["interface_objection"], "interface_objection")
        disputes.append(Dispute(f"D-{task}-{start + len(disputes)}", "interface",
                                "What interface should the contract use?", interface, objection, *labels))
    return interface, points, disputes


def ruling_text(dispute: Dispute, choice: str, note: str) -> str:
    if choice == "a":
        return dispute.a
    if choice == "b":
        return dispute.b
    if choice == "other" and dispute.kind in ("reading", "interface"):
        if not _text(note, "note").strip():
            raise ValueError("choice 'other' needs a note")
        return note
    raise ValueError(f"invalid choice {choice!r} for {dispute.kind}")


def default_scope(kind: str) -> str:
    if not isinstance(kind, str) or kind not in _SCOPES:
        raise ValueError("unknown dispute kind")
    return _SCOPES[kind]


def precedents(events: Sequence[dict]) -> list[dict]:
    result = []
    for event in events:
        if event.get("type") == "ruling.made" and event.get("scope") == "project":
            result.append({"id": f"P-{len(result) + 1}", "question": event["question"],
                           "ruling": event["text"], "while": event["while"], "task": event["task"]})
    return result


def _precedent_line(precedent: dict, standalone: bool) -> str:
    for key in ("id", "question", "ruling", "while", "task"):
        _text(precedent[key], key)
    prefix = (f"**{precedent['id']}** ({precedent['task']})" if standalone
              else f"{precedent['id']}:")
    condition = f" (while: {precedent['while']})" if precedent["while"] else ""
    return f"- {prefix} {precedent['question']} -> {precedent['ruling']}{condition}\n"


def render_contract(task: str, version: int, task_text: str, interface: str, points: Sequence[Point],
                    precedents: Sequence[dict]) -> str:
    _task(task)
    _positive(version, "version")
    _text(task_text, "task_text")
    _text(interface, "interface")
    decisions = "".join(f"- Q: {p.question}\n  A: {p.answer} ({p.source})\n" for p in points) or "none\n"
    in_force = "".join(_precedent_line(p, False) for p in precedents) or "none\n"
    return _rendered(f"# Contract: {task} (v{version})\n\n## Task\n{task_text}\n\n"
                     f"## Interface\n{interface}\n\n## Decisions\n{decisions}\n"
                     f"## Precedents in force\n{in_force}")


def render_precedents(precedents: Sequence[dict]) -> str:
    lines = "".join(_precedent_line(p, True) for p in precedents) or "none yet\n"
    return _rendered(f"# Precedents\n\n{lines}")


def render_card(dispute: Dispute) -> str:
    lines = [f"Dispute {dispute.id} ({dispute.kind})", "", dispute.question, "",
             f"a) {dispute.a_label}: {dispute.a}", f"b) {dispute.b_label}: {dispute.b}"]
    if dispute.kind in ("reading", "interface"):
        lines.append("other) Supply an answer with --note.")
    elif dispute.kind == "unresolved":
        lines.append("drop) Drop this task.")
    if dispute.evidence:
        lines.extend(["", "Evidence:", dispute.evidence])
    lines.extend(["", f"parallax rule {dispute.id} a"])
    return _rendered("\n".join(lines) + "\n")
