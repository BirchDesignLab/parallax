"""The batch settlement: the packet two seats see, the checks on their replies, and the settlement they reach.

Task 19.2. Everything here is pure. A reply's accepted value is `accepted(reply)`: every semantic check
runs on it, and the conductor (Task 19.3) stores, hashes and shows the next seat that same value.
"""
from __future__ import annotations

import copy
import json
import unicodedata
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


def public(value):
    """`value` as confirmed-v1 shows it: every string scrubbed until another scrub changes nothing (Task 19.5).

    One scrub need not be stable: replacing a path can expose a new path start, as two backslashes before
    `<outside>`. Each scrub that changes the text replaces at least one character outside every earlier
    `<outside>` marker, which holds no path start, so this ends.
    """
    while (scrubbed := redact.scrub_values(value)) != value:
        value = scrubbed
    return value


def accepted(reply: dict) -> dict:
    """The value that is checked, stored and shown: `reply` made `public`, so scrubbing it again changes nothing."""
    return public(reply)


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
    # The rows come from the public values the seats see, so a reader holding only this packet derives the
    # same rows (Task 19.5): scrubbing a path, then trimming, need not equal trimming, then scrubbing.
    readings, reveals = public(readings), public(reveals)
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
    return public(copy.deepcopy(built))


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


# ---------------------------------------------------------------------------------------------------------
# The card a public row shows (Task 19.5)

_OTHER = {"policy": "other) Supply the policy with --note.",
          "interface": "other) Supply the complete interface with --note.",
          "combined": 'other) Supply both in one --note holding a JSON object: {"interface": "...", "policy": "..."}'}


def _hidden(char: str) -> bool:
    """A character a terminal does not show as itself: a control (a carriage return moves the cursor back), a
    format character (a bidirectional override reorders the line) or a line or paragraph separator. The line
    feed is a block's own separator."""
    return char != "\n" and unicodedata.category(char) in ("Cc", "Cf", "Zl", "Zp")


def _literal(text: str) -> str:
    """`text` as one JSON string literal with every hidden character escaped: one line, shown as written."""
    out = []
    for char in json.dumps(text, ensure_ascii=False):
        code = ord(char)
        if not _hidden(char):
            out.append(char)
        elif code > 0xFFFF:
            code -= 0x10000
            out.append(f"\\u{0xD800 + (code >> 10):04x}\\u{0xDC00 + (code & 0x3FF):04x}")
        else:
            out.append(f"\\u{code:04x}")
    return "".join(out)


def _block(text: str, indent: str = "") -> list[str]:
    """`text` exactly, one `| ` line per line: indentation, blank lines and a final line break all survive.
    Text holding a hidden character is one `|! ` line holding its `_literal` instead."""
    if any(_hidden(char) for char in text):
        return [f"{indent}|! {_literal(text)}"]
    return [f"{indent}|{' ' + line if line else ''}" for line in text.split("\n")]


def _inline(text: str) -> str:
    """Evidence on a line of its own, trimmed. Text that would span lines, holds a hidden character or starts
    with `!` is shown as `!` and its `_literal`, untrimmed."""
    shown = text.strip()
    if "\n" in shown or shown.startswith("!") or any(_hidden(char) for char in shown):
        return "!" + _literal(text)
    return shown


def _column(label: str, target: str, value: dict) -> list[str]:
    """One typed alternative under its label, exactly as a ruling for it would record it."""
    if target in ("policy", "interface"):
        return [f"{label}:", *_block(value[target])]
    return [f"{label}:", "  interface:", *_block(value["interface"], "  "), "  policy:", *_block(value["policy"], "  ")]


def _source_lines(source: dict, labels: dict, agreed: str, withdrawn: Sequence[dict] = ()) -> list[str]:
    """One source as the seats recorded it: each position under the seat that holds it, with its reason; a
    disputed source's witness under the seat that wrote it, with its citation; and each withdrawal of it."""
    owner = source["owner"]
    reviewer = "challenger" if owner == "builder" else "builder"
    lines = [f"- {source['key']}: {_inline(source['question'])}"]
    if source["agree"]:
        lines.append(f"  {labels[owner]}, {agreed}: {_inline(source['answer'])}")
        if source["why"].strip():
            lines.append(f"    why: {_inline(source['why'])}")
    else:
        for role, text, why in ((owner, source["answer"], source["why"]),
                                (reviewer, source["counter"], source["counter_why"])):
            lines.append(f"  {labels[role]}: {_inline(text)}")
            if why.strip():
                lines.append(f"    why: {_inline(why)}")
        witness = source["witness"]
        if witness:
            lines.append(f"  witness from {labels[witness['author']]}: {_inline(witness['scenario'])} "
                         f"({_inline(witness['observation'])}): {labels['builder']} {_inline(witness['a'])}; "
                         f"{labels['challenger']} {_inline(witness['b'])}")
            if witness["decided_by"]:
                lines.append(f"    decided by: {_inline(witness['decided_by'])}")
    lines += [f"  withdrawn by {labels[w['role']]}, now in {', '.join(w['destinations'])}: {_inline(w['reason'])}"
              for w in withdrawn if w["source"] == source["key"]]
    return lines


def _first_vote(reply: dict, slot: str) -> dict | None:
    return next((vote for vote in reply.get("votes", []) if vote["slot"] == slot), None)


def card_text(row: dict, packet: dict, record: dict, proposal: dict, review: dict) -> str:
    """The card for a public row of a settlement, as its card file, the CLI and the journal show it.

    Every member source shows each seat's position and reason and its original witness; an agreed one
    shows its owner and how its agreement stands. A pending row adds both columns verbatim, each seat's
    vote and reason (reviewed modes), each withdrawal and the predictions both seats confirmed. A refusal
    shows every replaced source by key, the reasons, each surviving term by key and verbatim, what the
    one replacement covers, and its form. Every value is already `public`, so the card is not scrubbed
    again: a scrub of the whole text could rewrite a `_literal`'s escapes.
    """
    labels = {role: f"{packet['seats'][role]} ({role})" for role in ("builder", "challenger")}
    sources = {source["key"]: source for source in packet["sources"]}
    lines = [f"Dispute {row['id']} ({row['kind']})", "", _inline(row["question"]), ""]
    if row["kind"] == "refusal":
        lines += ["The seats did not settle these terms. Replace all of them with one ruling, or drop the task.",
                  "", "Reasons:", _inline(record["refusal_reason"]) or "none given", "", "Replaced by the ruling:"]
        for key in row["members"]:
            lines += _source_lines(sources[key], labels, "agreed by both seats, superseded")
        lines += ["", "Kept as written:"]
        for term in record["common"]:
            lines += [f"- {', '.join(term['sources'])}:", "  question:", *_block(term["question"], "  "),
                      "  text:", *_block(term["text"], "  ")]
        if not record["common"]:
            lines.append("- nothing")
        lines += ["", f"The ruling covers: {', '.join(row['members'])}", _OTHER[row["target"]], "drop) Drop this task.",
                  "", f"parallax rule {row['id']} other --note TEXT"]
    else:
        lines += [*_column(f"a) {labels['builder']}", row["target"], row["a"]),
                  *_column(f"b) {labels['challenger']}", row["target"], row["b"]), _OTHER[row["target"]]]
        votes = [(role, _first_vote(reply, row["slot"])) for role, reply in (("builder", proposal), ("challenger", review))]
        if any(vote for _, vote in votes):
            lines += ["", "Votes:"]
            lines += [f"- {labels[role]} signs {', '.join(vote['sign'])}: {_inline(vote['reason'])}"
                      for role, vote in votes if vote]
        lines += ["", "Sources:"]
        for key in row["members"]:
            lines += _source_lines(sources[key], labels, "originally agreed by both seats", record["withdrawn"])
        if row["witnesses"] and proposal:          # a direct row's witness is its source's, shown above
            lines += ["", "Predictions both seats confirmed:"]
            lines += [f"- {w['source']}: {_inline(w['scenario'])} ({_inline(w['observation'])}): "
                      f"a) {_inline(w['a'])} b) {_inline(w['b'])}" for w in row["witnesses"]]
        lines += ["", f"parallax rule {row['id']} a"]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------------------------------------
# A ruling on a public row (Task 19.6)

RULING_FIELDS = ("dispute", "kind", "question", "choice", "text", "scope", "while", "limitation", "batch_protocol",
                 "settlement_sha", "slot", "members", "value")
_EMPTY_VALUE = {"interface": "", "policy": ""}
_COMBINED_NOTE = ('a combined note must be one JSON object with exactly the string fields "interface" and "policy", '
                  "neither blank")


def combined_text(value: dict) -> str:
    """A combined value as one standalone string: its ruling's text, and so its precedent's."""
    return f"Interface:\n{value['interface']}\nPolicy:\n{value['policy']}"


def _value_text(target: str, value: dict) -> str:
    return combined_text(value) if target == "combined" else value[target]


def _once_each(pairs: list) -> dict:
    """A JSON object whose names are all different: a repeated name would silently keep only its last value."""
    if len({name for name, _ in pairs}) != len(pairs):
        raise ValueError("a name is repeated")
    return dict(pairs)


def _other_value(target: str, note: str) -> dict:
    """The value an `other` note supplies for `target`: the note itself, or a combined note's two fields."""
    if target != "combined":
        if not note.strip():
            raise ValueError("choice 'other' needs a note")
        return {**_EMPTY_VALUE, target: note}
    try:
        value = json.loads(note, object_pairs_hook=_once_each)
    except ValueError:
        raise ValueError(_COMBINED_NOTE) from None
    if (not isinstance(value, dict) or set(value) != {"interface", "policy"}
            or not all(isinstance(text, str) and text.strip() for text in value.values())):
        raise ValueError(_COMBINED_NOTE)
    return {"interface": value["interface"], "policy": value["policy"]}


def ruling(settled: dict, row: dict, choice: str, note: str = "", scope: str | None = None, while_: str = "",
           limitation: str = "") -> dict:
    """The ruling.made fields, in RULING_FIELDS order, that `choice` on `settled`'s public `row` records.

    `a` or `b` records the row's column and takes no nonblank note; `other` records the note as the row's
    target (a combined note is a JSON object naming each field once); a refusal's `drop` records empty values
    and the note, or a default, as the reason. A reading card defaults to project scope, any other card to
    task, and `drop` is always task. The text, while and limitation must be UTF-8 text. ValueError says what
    is wrong.
    """
    if not all(isinstance(text, str) for text in (note, while_, limitation)):
        raise ValueError("note, while and limitation must be text")
    if choice not in row["allowed"]:
        raise ValueError(f"{row['id']} allows {', '.join(row['allowed'])}, not {choice!r}")
    if choice in ("a", "b"):
        if note.strip():
            raise ValueError(f"choice {choice!r} takes no note: the card's {choice} column is the ruling")
        value = row[choice]
        text = _value_text(row["target"], value)
    elif choice == "other":
        value = _other_value(row["target"], note)
        text = _value_text(row["target"], value)
    else:
        value, text = dict(_EMPTY_VALUE), note.strip() or "Drop this task."
    if choice == "drop":
        scope = "task"
    elif scope is None:
        scope = "project" if row["kind"] == "reading" else "task"
    if scope not in ("task", "project"):
        raise ValueError(f"scope must be 'task' or 'project', not {scope!r}")
    for field, words in (("text", text), ("while", while_), ("limitation", limitation)):
        try:
            words.encode("utf-8")                # a contract and a precedent are UTF-8 files
        except UnicodeEncodeError:
            raise ValueError(f"the ruling's {field} is not UTF-8 text") from None
    return {"dispute": row["id"], "kind": row["kind"], "question": row["question"], "choice": choice, "text": text,
            "scope": scope, "while": while_, "limitation": limitation, "batch_protocol": settled["batch_protocol"],
            "settlement_sha": settled["settlement_sha"], "slot": row["slot"], "members": list(row["members"]),
            "value": value}


def ruling_problem(settled: dict, row: dict, event: dict) -> str | None:
    """Why a stored ruling.made `event` on `row` is not one `ruling` writes, or None.

    The note is recovered from what was stored (an `other` value's target, a combined value as JSON, a drop's
    text), `ruling` is asked again with the stored choice, scope, while and limitation, and every field must
    then be what it returns, in its order.
    """
    choice, value = event.get("choice"), event.get("value")
    if choice == "other" and row["target"] == "combined":
        note = json.dumps(value)
    elif choice == "other":
        note = value.get(row["target"]) if isinstance(value, dict) else None
    else:
        note = event.get("text") if choice == "drop" else ""
    try:
        expected = ruling(settled, row, choice, note, event.get("scope"), event.get("while"), event.get("limitation"))
    except ValueError as exc:
        return f"is not one rule writes: {exc}"
    stored = {field: event[field] for field in event if field not in ("ts", "type", "task")}
    if list(stored) != list(expected):
        return f"has the fields {', '.join(stored)}, not {', '.join(expected)}"
    for field in RULING_FIELDS:
        if stored[field] != expected[field]:
            return f"has a {field} its card does not give"
    return None
