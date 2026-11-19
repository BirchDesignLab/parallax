"""Probe: which bound check should clamp use, `hi < lo` (a) or `not (lo <= hi)` (b)?

From the 2026-11-19 real run (`~/.parallax/demos/clamp-250950f5`): all five cards came down to
this one choice. This runs both checks, and a third candidate (c, only `<` plus a NaN self-test),
over real Python types, to see what each one rejects and what each one requires of the caller.

Usage: python scripts/probes/clamp_bound_check.py   (pure Python, spends nothing)
"""
import datetime
import functools
from decimal import Decimal
from fractions import Fraction

NAN = float("nan")


def clamp_a(x, lo, hi):          # codex: strict comparisons only
    if hi < lo:
        raise ValueError
    if x < lo:
        return lo
    if hi < x:
        return hi
    return x


def clamp_b(x, lo, hi):          # claude: validate with <=
    if not (lo <= hi):
        raise ValueError
    if x < lo:
        return lo
    if hi < x:
        return hi
    return x


def clamp_c(x, lo, hi):          # neither seat's: strict comparisons, plus a self-inequality test for NaN
    if hi < lo or lo != lo or hi != hi:
        raise ValueError
    if x < lo:
        return lo
    if hi < x:
        return hi
    return x


class LtOnly:
    """Defines only __lt__ (and __eq__), like many hand-written orderable classes."""
    def __init__(self, v): self.v = v
    def __lt__(self, o): return self.v < o.v
    def __eq__(self, o): return isinstance(o, LtOnly) and self.v == o.v
    __hash__ = None
    def __repr__(self): return f"LtOnly({self.v})"


@functools.total_ordering
class Total:
    """__lt__ plus functools.total_ordering, which derives <=, > and >=."""
    def __init__(self, v): self.v = v
    def __lt__(self, o): return self.v < o.v
    def __eq__(self, o): return isinstance(o, Total) and self.v == o.v
    __hash__ = None
    def __repr__(self): return f"Total({self.v})"


def show(fn, *args):
    try:
        r = fn(*args)
        return f"{r!r}"
    except Exception as e:  # noqa: BLE001 - the exception type is the result
        return type(e).__name__


CASES = [
    ("NaN lower bound", (8, NAN, 5)),
    ("NaN upper bound", (3, 0, NAN)),
    ("NaN lower bound, x below hi", (-1, NAN, 5)),
    ("both bounds NaN", (1, NAN, NAN)),
    ("NaN x, valid bounds", (NAN, 0, 1)),
    ("Decimal NaN bound", (Decimal(8), Decimal("NaN"), Decimal(5))),
    ("Decimal sNaN bound", (Decimal(8), Decimal("sNaN"), Decimal(5))),
    ("reversed bounds", (5, 10, 1)),
    ("sets: unordered bounds {1},{2}", ({3}, {1}, {2})),
    ("sets: nested bounds {1},{1,2}", ({1, 2}, {1}, {1, 2})),
    ("class with only __lt__", (LtOnly(5), LtOnly(0), LtOnly(10))),
    ("total_ordering class", (Total(5), Total(0), Total(10))),
    ("Fraction", (Fraction(1, 3), Fraction(0), Fraction(1))),
    ("datetime", (datetime.date(2030, 1, 1), datetime.date(2026, 1, 1), datetime.date(2027, 1, 1))),
    ("str", ("m", "a", "k")),
    ("tuple", ((1, 5), (0, 0), (1, 2))),
]


def main():
    print(f"{'case':34} {'a: hi < lo':22} {'b: not lo <= hi':22} {'c: < plus NaN test':22}")
    for name, args in CASES:
        print(f"{name:34} {show(clamp_a, *args):22} {show(clamp_b, *args):22} {show(clamp_c, *args):22}")


if __name__ == "__main__":
    main()
