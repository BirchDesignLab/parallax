"""The batch settlement: the packet two seats see, the checks on their replies, and the settlement they reach.

Task 19.2. Everything here is pure. A reply's accepted value is `accepted(reply)`: every semantic check
runs on it, and the conductor (Task 19.3) stores, hashes and shows the next seat that same value.
"""
from __future__ import annotations

import copy
import json
from typing import Sequence

from parallax import redact
from parallax.decisions import route, sources
from parallax.ledger import sha256_text

ASSENT_FIELDS = ("coverage", "shared_terms", "withdrawals", "columns_and_witnesses", "all_combinations")
_ROLES = ("builder", "challenger")
_PRECEDENT_FIELDS = ("id", "question", "ruling", "while", "task")
_INPUTS_ERROR = "inputs must give the reading and reveal sha for builder and challenger"
_SEATS_ERROR = "seats must name two different seats for builder and challenger"


def canonical(value) -> str:
    """The canonical JSON text of `value`, as the conductor hashes stored outputs."""
    return json.dumps(value, sort_keys=True, indent=2)


def digest(value) -> str:
    return sha256_text(canonical(value))


def accepted(reply: dict) -> dict:
    """The value that is checked, stored and shown: `reply` with every string scrubbed."""
    return redact.scrub_values(reply)


def _clean_text(value) -> bool:
    return isinstance(value, str) and redact.scrub_paths(value) == value


def packet(task_text: str, precedents: Sequence[dict], readings: dict[str, dict], reveals: dict[str, dict],
           inputs: dict[str, dict], seats: dict[str, str]) -> dict:
    """Everything the two seats see, as one canonical, scrubbed dict."""
    if (not isinstance(inputs, dict) or set(inputs) != set(_ROLES)
            or not all(isinstance(v, dict) and set(v) == {"reading", "reveal"}
                       and _clean_text(v["reading"]) and _clean_text(v["reveal"]) for v in inputs.values())):
        raise ValueError(_INPUTS_ERROR)
    if (not isinstance(seats, dict) or set(seats) != set(_ROLES)
            or not all(_clean_text(seats[role]) and seats[role] for role in _ROLES)
            or seats["builder"] == seats["challenger"]):
        raise ValueError(_SEATS_ERROR)
    rows = sources(readings, reveals)
    built = {
        "task": task_text,
        "seats": {role: seats[role] for role in _ROLES},
        "precedents": [{field: precedent[field] for field in _PRECEDENT_FIELDS} for precedent in precedents],
        "inputs": {role: {"reading": inputs[role]["reading"], "reveal": inputs[role]["reveal"]} for role in _ROLES},
        "sources": rows,
        "challenger_interface": readings["challenger"]["interface"],
        "predicted_failures": {role: list(readings[role]["predicted_failures"]) for role in _ROLES},
        "conflicts": {role: [{"source": c["source"], "target": c["target"], "reason": c["reason"]}
                            for c in reveals[role]["conflicts"]] for role in _ROLES},
        "reveals": {role: reveals[role] for role in _ROLES},
    }
    return redact.scrub_values(copy.deepcopy(built))


# ---------------------------------------------------------------------------------------------------------
# Shared checks


def _blank(text) -> bool:
    return not text.strip()


def _key_list(where: str, items: Sequence[str], known: set[str], non_empty: bool = False) -> list[str]:
    lines = []
    if non_empty and not items:
        lines.append(f"{where}: needs at least one source")
    seen = set()
    for key in items:
        if key not in known:
            lines.append(f"{where}: unknown source {key or '(blank)'}")
        elif key in seen:
            lines.append(f"{where}: repeats {key}")
        else:
            seen.add(key)
    return lines


def _valid_sign(sign: Sequence[str]) -> bool:
    return bool(sign) and len(set(sign)) == len(sign)


def _first_votes(votes: Sequence[dict], slots: Sequence[str]) -> tuple[list[str], dict[str, dict]]:
    """Vote problems against `slots`, and each slot's first vote in vote order."""
    lines, first = [], {}
    for vote in votes:
        slot = vote["slot"]
        if slot not in slots:
            lines.append(f"vote for unknown slot {slot or '(blank)'}")
            continue
        if slot in first:
            lines.append(f"repeated vote for {slot}")
            continue
        first[slot] = vote
        if not _valid_sign(vote["sign"]):
            lines.append(f"vote for {slot} must sign a, b or both, once each")
        if _blank(vote["reason"]):
            lines.append(f"vote for {slot} needs a reason")
    lines.extend(f"missing vote for {slot}" for slot in slots if slot not in first)
    return lines, first


def _fallback_lines(fallback: dict, known: set[str]) -> list[str]:
    lines = _key_list("fallback", fallback["members"], known)
    if fallback["known"] and (not fallback["members"] or _blank(fallback["question"])):
        lines.append("fallback: a known fallback needs members and a question")
    if not fallback["known"] and (fallback["members"] or not _blank(fallback["question"])):
        lines.append("fallback: an unknown fallback has no members or question")
    return lines


def _keys(pack: dict) -> list[str]:
    return [row["key"] for row in pack["sources"]]


def _slot_list(slots: Sequence[str]) -> str:
    return ", ".join(slots) or "none"


# ---------------------------------------------------------------------------------------------------------
# The proposal check


def proposal_problem(proposal: dict, packet: dict, packet_sha: str) -> str | None:
    """Every problem in `proposal`, one per line in a stable order, or None."""
    keys = _keys(packet)
    known = set(keys)
    lines = []
    if proposal["packet_sha"] != packet_sha:
        lines.append("packet_sha differs from the packet")
    fallback = proposal["fallback"]

    if proposal["decision"] == "refuse":
        for field in ("common", "choices", "withdrawn", "votes", "preferences"):
            if proposal[field]:
                lines.append(f"{field} must be empty when you refuse")
        for name in ASSENT_FIELDS:
            if proposal["assent"][name]:
                lines.append(f"assent.{name} must be false when you refuse")
        if _blank(proposal["refusal_reason"]):
            lines.append("refusal_reason must say why you refuse")
        lines.extend(_key_list("affected", proposal["affected"], known))
        if not proposal["affected"] and fallback["known"]:
            lines.append("affected must name the sources your refusal concerns")
        lines.extend(_fallback_lines(fallback, known))
        return "\n".join(lines) or None

    agreed = [row["key"] for row in packet["sources"] if row["agree"]]
    common, choices = proposal["common"], proposal["choices"]
    slots = [choice["slot"] for choice in choices]

    common_slots = [term["slot"] for term in common]
    decision_slots = [slot for slot in common_slots if slot != "interface"]
    if (decision_slots != [f"p/{i}" for i in range(len(decision_slots))]
            or common_slots.count("interface") > 1):
        lines.append("common slots must be interface (at most once) and p/0, p/1, ... in order; "
                     f"got {_slot_list(common_slots)}")
    if slots != [f"c/{i}" for i in range(len(slots))]:
        lines.append(f"choice slots must be c/0, c/1, ... in order; got {_slot_list(slots)}")

    for term in common:
        where = f"common {term['slot']}"
        lines.extend(_key_list(where, term["sources"], known, non_empty=True))
        if _blank(term["question"]):
            lines.append(f"{where}: question is empty")
        if _blank(term["text"]):
            lines.append(f"{where}: text is empty")

    for choice in choices:
        where = f"choice {choice['slot']}"
        target = choice["target"]
        lines.extend(_key_list(where, choice["members"], known, non_empty=True))
        if _blank(choice["question"]):
            lines.append(f"{where}: question is empty")
        filled = {"policy": ("policy",), "interface": ("interface",), "combined": ("interface", "policy")}[target]
        for column in ("a", "b"):
            for field in ("interface", "policy"):
                value = choice[column][field]
                if field in filled:
                    if _blank(value):
                        lines.append(f"{where}: {column}.{field} is empty")
                elif value != "":
                    lines.append(f"{where}: a {target} choice leaves {column}.{field} empty")
        if all(choice["a"][f].strip() == choice["b"][f].strip() for f in ("interface", "policy")):
            lines.append(f"{where}: a and b are the same")

    producers = [term["sources"] for term in common if term["slot"] == "interface"]
    producers += [choice["members"] for choice in choices if choice["target"] in ("interface", "combined")]
    if len(producers) != 1:
        lines.append(f"the interface has {len(producers)} producers; give exactly one common interface or "
                     "interface choice")
    elif "builder/interface" not in producers[0]:
        lines.append("builder/interface must be a source of the interface")

    carried = {key for term in common for key in term["sources"]} | {key for c in choices for key in c["members"]}
    lines.extend(f"missing disposition for {key}" for key in keys if key not in carried)

    destinations = {key: [c["slot"] for c in choices if key in c["members"]]
                    for key in keys if key in agreed and any(key in c["members"] for c in choices)}
    first_seen: dict[tuple[str, str], int] = {}
    for i, withdrawal in enumerate(proposal["withdrawn"]):
        source = withdrawal["source"]
        identity = (withdrawal["role"], source)
        if identity in first_seen:
            lines.append(f"withdrawal {i}: repeats withdrawal {first_seen[identity]}")
            continue
        first_seen[identity] = i
        if source not in destinations:
            lines.append(f"withdrawal {i}: {source or '(blank)'} is not an agreed source moved into a choice")
        elif withdrawal["destinations"] != destinations[source]:
            lines.append(f"withdrawal {i}: destinations must be exactly {', '.join(destinations[source])}")
        if _blank(withdrawal["reason"]):
            lines.append(f"withdrawal {i}: reason is empty")
    withdrawn_sources = {w["source"] for w in proposal["withdrawn"]}
    for key in keys:
        if key in destinations and key not in withdrawn_sources:
            lines.append(f"agreed {key} moved into {', '.join(destinations[key])} needs a withdrawal")

    for choice in choices:
        where = f"choice {choice['slot']}"
        if not choice["witnesses"]:
            lines.append(f"{where} needs a witness")
        for k, witness in enumerate(choice["witnesses"]):
            if witness["source"] not in choice["members"]:
                lines.append(f"{where} witness {k}: source {witness['source'] or '(blank)'} is not a member")
            missing = [name for name in ("scenario", "observation", "a", "b") if _blank(witness[name])]
            if missing:
                lines.append(f"{where} witness {k}: missing {', '.join(missing)}")
            elif witness["a"].strip() == witness["b"].strip():
                lines.append(f"{where} witness {k}: a and b predict the same result")

    for name in ASSENT_FIELDS:
        if not proposal["assent"][name]:
            lines.append(f"assent.{name} must be true to propose")

    vote_lines, votes = _first_votes(proposal["votes"], slots)
    lines.extend(vote_lines)

    preferred = set()
    for preference in proposal["preferences"]:
        slot = preference["slot"]
        if slot not in slots:
            lines.append(f"preference for unknown slot {slot}")
        elif slot in preferred:
            lines.append(f"repeated preference for {slot}")
        else:
            preferred.add(slot)
            if slot not in votes or preference["answer"] not in votes[slot]["sign"]:
                lines.append(f"preference for {slot} must be an answer you sign")
    lines.extend(f"missing preference for {slot}" for slot in slots if slot not in preferred)

    if proposal["refusal_reason"] != "":
        lines.append("refusal_reason must be empty when you propose")
    if proposal["affected"]:
        lines.append("affected must be empty when you propose")
    lines.extend(_fallback_lines(fallback, known))
    return "\n".join(lines) or None


# ---------------------------------------------------------------------------------------------------------
# The review check


def review_problem(review: dict, proposal: dict, packet: dict, packet_sha: str, proposal_sha: str) -> str | None:
    """Every problem in `review`, one per line in a stable order, or None."""
    known = set(_keys(packet))
    lines = []
    if review["packet_sha"] != packet_sha:
        lines.append("packet_sha differs from the packet")
    if review["proposal_sha"] != proposal_sha:
        lines.append("proposal_sha differs from the recorded proposal")

    if review["decision"] == "attest":
        if proposal["decision"] == "refuse":
            lines.append("a refused proposal can only be reviewed with refuse")
            return "\n".join(lines)
        slots = [choice["slot"] for choice in proposal["choices"]]
        for name in ASSENT_FIELDS:
            if not review["assent"][name]:
                lines.append(f"assent.{name} must be true to attest")
        vote_lines, votes = _first_votes(review["votes"], slots)
        lines.extend(vote_lines)
        _, builder_votes = _first_votes(proposal["votes"], slots)
        for slot, vote in votes.items():
            if not _valid_sign(vote["sign"]) or slot not in builder_votes:
                continue
            mine, theirs = set(vote["sign"]), set(builder_votes[slot]["sign"])
            if not mine & theirs and not (theirs == {"a"} and mine == {"b"}):
                lines.append(f"vote for {slot} holds a while the builder holds b; "
                             "refuse instead of reversing the columns")
        if review["refusal_reason"] != "":
            lines.append("refusal_reason must be empty when you attest")
        if review["affected"]:
            lines.append("affected must be empty when you attest")
        return "\n".join(lines) or None

    if review["votes"]:
        lines.append("votes must be empty when you refuse")
    for name in ASSENT_FIELDS:
        if review["assent"][name]:
            lines.append(f"assent.{name} must be false when you refuse")
    if _blank(review["refusal_reason"]):
        lines.append("refusal_reason must say why you refuse")
    lines.extend(_key_list("affected", review["affected"], known))
    if not review["affected"] and review["fallback_complete"]:
        lines.append("affected must name the sources your refusal concerns")
    return "\n".join(lines) or None


# ---------------------------------------------------------------------------------------------------------
# The settlement record


def _value(value: dict) -> dict:
    return {"interface": value["interface"], "policy": value["policy"]}


def _term(term: dict) -> dict:
    return {"slot": term["slot"], "question": term["question"], "text": term["text"],
            "sources": list(term["sources"])}


def _witness(witness: dict) -> dict:
    return {"source": witness["source"], "scenario": witness["scenario"], "observation": witness["observation"],
            "a": witness["a"], "b": witness["b"]}


def _choice(choice: dict, resolution: str, selected: str) -> dict:
    return {"slot": choice["slot"], "target": choice["target"], "question": choice["question"],
            "members": list(choice["members"]), "a": _value(choice["a"]), "b": _value(choice["b"]),
            "witnesses": [_witness(w) for w in choice["witnesses"]], "resolution": resolution,
            "selected": selected}


def _record(mode: str, common: list, withdrawn: list, choices: list, refusal_reason: str = "",
            affected: list | None = None, detail: str = "") -> dict:
    return {"mode": mode, "common": common, "withdrawn": withdrawn, "choices": choices,
            "refusal_reason": refusal_reason, "affected": affected or [], "detail": detail}


def _confirmed_choices(proposal: dict, review: dict) -> list[dict]:
    slots = [choice["slot"] for choice in proposal["choices"]]
    builder = {}
    for vote in proposal["votes"]:
        builder.setdefault(vote["slot"], vote)
    challenger = {}
    for vote in review["votes"]:
        challenger.setdefault(vote["slot"], vote)
    preferred = {}
    for preference in proposal["preferences"]:
        preferred.setdefault(preference["slot"], preference["answer"])
    result = []
    for choice in proposal["choices"]:
        slot = choice["slot"]
        mine, theirs = set(builder[slot]["sign"]), set(challenger[slot]["sign"])
        shared = mine & theirs
        if len(shared) == 1:
            result.append(_choice(choice, "mutual", next(iter(shared))))
        elif len(shared) == 2:
            result.append(_choice(choice, "tie_break", preferred[slot]))
        elif mine == {"a"} and theirs == {"b"}:
            result.append(_choice(choice, "pending", ""))
        else:
            raise ValueError(f"the votes for {slot} reverse the columns")
    return result


def confirmed_settlement(packet: dict, proposal: dict, review: dict) -> dict:
    """The settlement of a proposal and review that passed their checks."""
    if proposal["decision"] == "propose" and review["decision"] == "attest":
        return _record(
            "confirmed", [_term(t) for t in proposal["common"]],
            [{"role": w["role"], "source": w["source"], "destinations": list(w["destinations"]),
              "reason": w["reason"]} for w in proposal["withdrawn"]],
            _confirmed_choices(proposal, review))

    keys = _keys(packet)
    named = set(proposal["affected"]) | set(review["affected"])
    lines = []
    if proposal["decision"] == "refuse":
        lines.append("builder: " + " ".join(proposal["refusal_reason"].split()))
    if review["decision"] == "refuse":
        lines.append("challenger: " + " ".join(review["refusal_reason"].split()))
    reason = "\n".join(lines)
    affected = [key for key in keys if key in named]

    required = {row["key"] for row in packet["sources"] if not row["agree"]} | named
    for role in _ROLES:
        for entry in packet["conflicts"][role]:
            required |= {entry["source"], entry["target"]}
    if proposal["decision"] == "propose":
        required |= {w["source"] for w in proposal["withdrawn"]}
    fallback = proposal["fallback"]
    members = set(fallback["members"])
    if not fallback["known"]:
        return _record("blocked", [], [], [], reason, affected, "the builder gave no fallback")
    if not review["fallback_complete"]:
        return _record("blocked", [], [], [], reason, affected,
                       "the challenger did not confirm the fallback is complete")
    if not required <= members:
        left_out = ", ".join(key for key in keys if key in required and key not in members)
        return _record("blocked", [], [], [], reason, affected, f"the fallback leaves out {left_out}")

    common, kept = [], 0
    for row in packet["sources"]:
        if row["key"] in members:
            continue
        if row["kind"] == "interface":
            slot = "interface"
        else:
            slot, kept = f"p/{kept}", kept + 1
        common.append({"slot": slot, "question": row["question"], "text": row["answer"], "sources": [row["key"]]})
    ordered = [key for key in keys if key in members]
    if "builder/interface" in members:
        target = "combined" if len(ordered) > 1 else "interface"
    else:
        target = "policy"
    choice = {"slot": "c/0", "target": target, "question": fallback["question"], "members": ordered,
              "a": {"interface": "", "policy": ""}, "b": {"interface": "", "policy": ""}, "witnesses": []}
    return _record("refusal", common, [], [_choice(choice, "refused", "")], reason, affected)


def direct_settlement(packet: dict) -> dict:
    """The settlement record of a direct route, with no calls."""
    rows = packet["sources"]
    flags = {role: {"conflicts": packet["conflicts"][role]} for role in _ROLES}
    if route(rows, flags) != "direct":
        raise ValueError("direct settlement needs a direct route")
    common, kept = [], 0
    interface = next(row for row in rows if row["kind"] == "interface")
    if interface["agree"]:
        common.append({"slot": "interface", "question": interface["question"], "text": interface["answer"],
                       "sources": [interface["key"]]})
    for row in rows:
        if row["kind"] == "reading" and row["agree"]:
            common.append({"slot": f"p/{kept}", "question": row["question"], "text": row["answer"],
                           "sources": [row["key"]]})
            kept += 1
    choices = []
    disputed = next((row for row in rows if not row["agree"]), None)
    if disputed is not None:
        key = disputed["key"]
        if disputed["kind"] == "interface":
            a, b = disputed["answer"], disputed["counter"]
            field, target, witnesses = "interface", "interface", []
        else:
            if disputed["owner"] == "builder":
                a, b = disputed["answer"], disputed["counter"]
            else:
                a, b = disputed["counter"], disputed["answer"]
            field, target = "policy", "policy"
            witnesses = []
            shown = disputed["witness"]
            if shown:
                witnesses = [{"source": key, "scenario": shown["scenario"], "observation": shown["observation"],
                              "a": shown["a"], "b": shown["b"]}]
        if a.strip() == b.strip():
            raise ValueError(f"direct {key}: a and b are the same after scrubbing")
        if witnesses:
            shown = witnesses[0]
            if shown["a"].strip() == shown["b"].strip():
                raise ValueError(f"direct {key}: a and b predict the same result after scrubbing")
        columns = [{"interface": a if field == "interface" else "", "policy": a if field == "policy" else ""},
                   {"interface": b if field == "interface" else "", "policy": b if field == "policy" else ""}]
        choices.append({"slot": "c/0", "target": target, "question": disputed["question"], "members": [key],
                        "a": columns[0], "b": columns[1], "witnesses": witnesses, "resolution": "pending",
                        "selected": ""})
    return _record("direct", common, [], choices)
