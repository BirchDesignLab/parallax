"""Probe: did the four rulings in the first real clamp run each earn a human ruling?

Run 2026-11-17 (~/.parallax/demos/clamp-6341c668) opened four reading disputes, all ruled `a`.
For each, this script encodes what each seat's reading predicts as a function, then runs
candidate calls and reports which calls separate the two readings.

Reading b (claude) is left partly unspecified in places; where it is, the prediction is
`UNSPECIFIED` rather than a guess.

A dispute earns a ruling only if some call gets different observable results from the two
readings AND no decision both seats already agreed to settles that call.

Usage: python scripts/probes/clamp_disputes.py   (pure Python, spends nothing)
"""
import math

NAN = float("nan")
UNSPECIFIED = "UNSPECIFIED"


def outcome(fn, *args):
    try:
        r = fn(*args)
    except Exception as e:  # noqa: BLE001 - the exception type is the observable result
        return f"raises {type(e).__name__}"
    if r is UNSPECIFIED:
        return r
    return f"{r!r} ({type(r).__name__})"


# Codex's reading, which every ruling chose. Same as what landed.
def codex(x, lo, hi):
    if not (lo <= hi):
        raise ValueError
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


# D1, claude: "Inclusive on both ends. x == lo returns x, x == hi returns x;
# the result always satisfies lo <= result <= hi."
def claude_d1(x, lo, hi):
    r = codex(x, lo, hi)
    if not (lo <= r <= hi):
        return UNSPECIFIED          # "always in range" rules out returning x; says nothing of what instead
    return r


# D2, claude: "Valid, not an error. Return lo for any x (including x equal to lo,
# where returning x is equivalent)."
def claude_d2(x, lo, hi):
    if lo == hi:
        return lo
    return codex(x, lo, hi)


# D3 and D4, claude: "Anything mutually orderable with < and >" ... "no validation beyond the
# lo > hi check (which is False for NaN and so does not raise)". Its bound check is `lo > hi`.
def claude_d3_d4(x, lo, hi):
    if lo > hi:
        raise ValueError
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


class LtGtOnly:
    """Orderable with < and > (claude's D3 wording) but defines no <= or >=."""
    def __init__(self, v): self.v = v
    def __lt__(self, o): return self.v < o.v
    def __gt__(self, o): return self.v > o.v
    def __repr__(self): return f"LtGtOnly({self.v})"


CASES = {
    "D-clamp-001-1 inclusive bounds": (claude_d1, [
        (0, 0, 10), (10, 0, 10), (5, 5.0, 10), (-1, 0, 10), (NAN, 0, 10)]),
    "D-clamp-001-2 lo == hi": (claude_d2, [
        (5, 5, 5), (4, 5, 5), (6, 5, 5), (5, 5.0, 5.0), (0, -0.0, -0.0)]),
    "D-clamp-001-3 accepted types": (claude_d3_d4, [
        (5, 0, 10), (5, 0.0, 10), ("m", "a", "z"), ((1, 2), (0,), (3,)),
        (LtGtOnly(5), LtGtOnly(0), LtGtOnly(10)), (5, "a", "z")]),
    "D-clamp-001-4 NaN bound": (claude_d3_d4, [
        (0.5, NAN, 1.0), (0.5, 0.0, NAN), (NAN, NAN, NAN), (0.5, 0.0, 1.0)]),
}

# Decisions both seats agreed to before the reveal (contract-v1.md, "(agreed)").
AGREED = {
    "nan x": "With valid ordinary numeric bounds, a float NaN supplied as x is returned unchanged.",
    "x equals bound": "x. ... clamp(5, 5.0, 10) returns int 5, and clamp(0, -0.0, 1) returns int 0.",
    "equal bounds": "Accept equal bounds. ... x when x compares equal to it.",
}
SETTLED_BY = {
    ("D-clamp-001-1 inclusive bounds", 4): "nan x",
    ("D-clamp-001-2 lo == hi", 3): "x equals bound / equal bounds",
    ("D-clamp-001-2 lo == hi", 4): "x equals bound / equal bounds",
}


def same(a, b):
    return a == b or ("nan" in a and "nan" in b and a.split()[-1] == b.split()[-1])


def main():
    for name, (other, calls) in CASES.items():
        print(f"\n== {name}")
        for i, args in enumerate(calls):
            a, b = outcome(codex, *args), outcome(other, *args)
            tag = "same    " if same(a, b) else "SEPARATES"
            note = ""
            if tag != "same    " and (name, i) in SETTLED_BY:
                note = f"   <- already settled by agreed decision: {SETTLED_BY[(name, i)]}"
            print(f"  {tag} clamp{args!r}: codex {a} | claude {b}{note}")


if __name__ == "__main__":
    main()
