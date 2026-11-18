"""Strict output schemas shared by all seat adapters."""
from __future__ import annotations


def _obj(**props):
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def _list(item):
    return {"type": "array", "items": item}


_S, _B, _I = {"type": "string"}, {"type": "boolean"}, {"type": "integer"}
FILES = _list(_obj(path=_S, change={"type": "string", "enum": ["add", "modify", "delete"]}, purpose=_S))
_MUTANTS = _list(_obj(id=_S, description=_S, files=_list(_S)))

READING = _obj(interface=_S, decisions=_list(_obj(question=_S, answer=_S, why=_S)), predicted_failures=_list(_S))
REVEAL = _obj(interface_ok=_B, interface_objection=_S, verdicts=_list(_obj(index=_I, agree=_B, counter=_S, why=_S)))
BUILD = _obj(summary=_S, blocked=_S, mutants=_MUTANTS, files=FILES)
PROBE = _obj(summary=_S, blocked=_S, files=FILES)
SOLO = PROBE
RESPOND = _obj(answers=_list(_obj(dispute=_S, stance={"type": "string", "enum": ["concede", "contest"]}, cite=_S, why=_S)),
               blocked=_S, mutants=_MUTANTS, files=FILES)


def validate(value, schema: dict) -> list[str]:
    """Report every problem in the schema subset used by seat outputs."""
    problems = []
    types = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool}

    def visit(item, rule: dict, where: str) -> None:
        kind = rule.get("type")
        if kind is not None:
            if kind not in types:
                raise ValueError(f"{where}: unsupported schema type {kind!r}")
            matches = isinstance(item, types[kind])
            if kind == "integer" and isinstance(item, bool):
                matches = False
            if not matches:
                problems.append(f"{where}: expected {kind}")
                return
        if "enum" in rule and not any(type(item) is type(option) and item == option for option in rule["enum"]):
            problems.append(f"{where}: expected one of {rule['enum']!r}")
        if isinstance(item, dict):
            props = rule.get("properties", {})
            for key in rule.get("required", []):
                if key not in item:
                    problems.append(f"{where}: missing {key!r}")
            for key, child in item.items():
                if key in props:
                    child_where = f"{where}.{key}" if isinstance(key, str) and key.isidentifier() else f"{where}[{key!r}]"
                    visit(child, props[key], child_where)
                elif rule.get("additionalProperties") is False:
                    problems.append(f"{where}: unexpected property {key!r}")
        elif isinstance(item, list) and "items" in rule:
            for index, child in enumerate(item):
                visit(child, rule["items"], f"{where}[{index}]")

    visit(value, schema, "$")
    return problems
