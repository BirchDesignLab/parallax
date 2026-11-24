"""Write the SVG figures the README and docs/ show, into docs/assets/.

Why a script: the figures share one palette, one visual language and one set of measurements,
and the terminal replay is built from text the stub demo really printed (2026-11-23), so they
are generated rather than drawn by hand. Rerun after changing anything here:

    python scripts/docs/build_assets.py

Rules the figures follow, because GitHub shows an SVG through <img>:
- no scripts, no external fonts or files; system font stacks only;
- each figure paints its own dark, grainy panel with rounded corners, so it reads on a light
  or a dark page;
- type is set for a phone: a 960-wide figure shown 350 px wide scales by about 0.36, so no
  text is smaller than 20 units; where that does not fit, the layout is simplified instead;
- motion is CSS inside the file, plays once and settles on the final state, and is off under
  prefers-reduced-motion; the still is complete on its own;
- randomness (star fields) is seeded, so reruns write identical files.

The visual language is the project site mockup's:
- warm is the claude seat, cool is the codex seat, white is agreement. Seat colors go on seat
  names, never on the words builder and challenger, because roles swap every task;
- a sight line is a seat's line of work: a glowing stroke in its seat color with a lit head.
  Where two lines meet (the crossing) they turn white;
- the frozen contract is a band of fixed stars;
- the striped cool and warm band (the two seats taking turns, seen edge on) tops every figure.
"""
from __future__ import annotations

import random
import re
from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "docs" / "assets"

VOID, INK, PANEL, LINE = "#04080e", "#0c1726", "#13243b", "#2c4361"
TEXT, SOFT, MUTE = "#e9eff6", "#c3d0de", "#8da2b9"
WARM, COOL, WHITE = "#f5b041", "#5cc8f2", "#ffffff"
SEAT = {"claude": WARM, "codex": COOL}
SANS = "'Segoe UI', system-ui, -apple-system, 'Helvetica Neue', Helvetica, Arial, sans-serif"
MONO = "'Cascadia Mono', ui-monospace, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace"
W = 960
H1, BODY, NOTE = 32, 23, 21          # title, label and note sizes, in viewBox units


def n(v) -> str:
    """A number as short as SVG allows: 12.0 -> 12, 12.345 -> 12.3."""
    s = f"{v:.1f}"
    return s[:-2] if s.endswith(".0") else s


# ------------------------------------------------------------------ frame

def frame(h: int, body: str, title: str, style: str = "", defs: str = "") -> str:
    """The shared panel: a deep field, vignette, film grain, the fold stripe and a hairline edge."""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {h}" width="{W}" height="{h}" role="img" aria-label="{escape(title)}">
<title>{escape(title)}</title>
<style>
.s{{font-family:{SANS}}}.m{{font-family:{MONO}}}
@keyframes draw{{from{{stroke-dashoffset:1.05}}to{{stroke-dashoffset:0}}}}
@keyframes fade{{from{{opacity:0}}}}
{style}
@media (prefers-reduced-motion: reduce){{*{{animation:none!important}}}}
</style>
<defs>
<clipPath id="clip"><rect width="{W}" height="{h}" rx="16"/></clipPath>
<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#060c16"/><stop offset="1" stop-color="#0a1422"/></linearGradient>
<radialGradient id="vig" cx=".5" cy=".42" r=".8"><stop offset=".5" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".55"/></radialGradient>
<filter id="noise" x="0" y="0" width="1" height="1"><feTurbulence type="fractalNoise" baseFrequency=".85" numOctaves="2" seed="7" stitchTiles="stitch"/><feColorMatrix values="0 0 0 0 1 0 0 0 0 1 0 0 0 0 1 .28 0 0 0 -.1"/></filter>
<pattern id="grain" width="180" height="180" patternUnits="userSpaceOnUse"><rect width="180" height="180" filter="url(#noise)"/></pattern>
<pattern id="fold" width="24" height="6" patternUnits="userSpaceOnUse"><rect width="12" height="6" fill="{COOL}"/><rect x="12" width="12" height="6" fill="{WARM}"/></pattern>
<radialGradient id="hw"><stop offset="0" stop-color="#fff"/><stop offset=".22" stop-color="{WARM}" stop-opacity=".9"/><stop offset="1" stop-color="{WARM}" stop-opacity="0"/></radialGradient>
<radialGradient id="hc"><stop offset="0" stop-color="#fff"/><stop offset=".22" stop-color="{COOL}" stop-opacity=".9"/><stop offset="1" stop-color="{COOL}" stop-opacity="0"/></radialGradient>
<radialGradient id="hx"><stop offset="0" stop-color="#fff"/><stop offset=".3" stop-color="#fff" stop-opacity=".55"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>
<marker id="arr" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="9" markerHeight="9" orient="auto"><path d="M0 1 9 5 0 9z" fill="{MUTE}"/></marker>
{defs}
</defs>
<g clip-path="url(#clip)">
<rect width="{W}" height="{h}" fill="url(#bg)"/>
<rect width="{W}" height="{h}" fill="url(#vig)"/>
<rect width="{W}" height="{h}" fill="url(#grain)"/>
{body}
<rect width="{W}" height="5" fill="url(#fold)"/>
</g>
<rect x=".5" y=".5" width="{W - 1}" height="{h - 1}" rx="15.5" fill="none" stroke="#fff" stroke-opacity=".1"/>
</svg>
"""


# ------------------------------------------------------------------ text

def text(x, y, value, size=BODY, fill=TEXT, anchor="start", weight=400, mono=False, extra="", cls="") -> str:
    a = "" if anchor == "start" else f' text-anchor="{anchor}"'
    w = "" if weight == 400 else f' font-weight="{weight}"'
    c = ("m" if mono else "s") + (f" {cls}" if cls else "")
    return (f'<text x="{n(x)}" y="{n(y)}" class="{c}" font-size="{size}" fill="{fill}"{a}{w}'
            f'{" " + extra if extra else ""}>{escape(value)}</text>')


def rich(x, y, parts, size=BODY, anchor="start", mono=False, extra="", cls="") -> str:
    """One line from (string, fill, weight) parts."""
    a = "" if anchor == "start" else f' text-anchor="{anchor}"'
    spans = "".join(f'<tspan fill="{f}"{"" if wt == 400 else f" font-weight=" + chr(34) + str(wt) + chr(34)}>'
                    f'{escape(s)}</tspan>' for s, f, wt in parts)
    c = ("m" if mono else "s") + (f" {cls}" if cls else "")
    return (f'<text x="{n(x)}" y="{n(y)}" class="{c}" font-size="{size}"{a}'
            f'{" " + extra if extra else ""}>{spans}</text>')


def seats_in(value, fill, weight=400, seat_weight=None):
    """Split a string into parts with every seat name in its seat color."""
    out = []
    for piece in re.split(r"(claude|codex)", value):
        if piece in SEAT:
            out.append((piece, SEAT[piece], seat_weight or weight))
        elif piece:
            out.append((piece, fill, weight))
    return out


def wrap(value, size, width, factor=0.48):
    """Word wrap with a generous average glyph width, so every fallback font fits, then balanced:
    the same number of lines, as even as they will go, so no line is a lone word."""
    def greedy(limit):
        lines, line = [], ""
        for word in value.split():
            if line and len(line) + 1 + len(word) > limit:
                lines.append(line)
                line = word
            else:
                line = f"{line} {word}" if line else word
        return lines + [line]

    limit = max(8, int(width / (size * factor)))
    lines = greedy(limit)
    for tighter in range(-(-len(value) // len(lines)), limit):
        even = greedy(tighter)
        if len(even) == len(lines):
            return even
    return lines


# ------------------------------------------------------------------ marks

def sight(d, color, width=2.4, cls="", grad=None) -> str:
    """A sight line: two soft strokes under a crisp one. pathLength lets CSS draw it."""
    stroke = f"url(#{grad})" if grad else color
    c = f' class="{cls}"' if cls else ""
    return (f'<g{c} fill="none" stroke="{stroke}" stroke-linecap="round">'
            f'<path d="{d}" pathLength="1" stroke-width="{n(width * 5)}" stroke-opacity=".07"/>'
            f'<path d="{d}" pathLength="1" stroke-width="{n(width * 2.4)}" stroke-opacity=".16"/>'
            f'<path d="{d}" pathLength="1" stroke-width="{n(width)}"/></g>')


def head(x, y, color, r=16, cls="") -> str:
    """A lit head: white core, seat-colored halo. color is 'w', 'c' or 'x' (white)."""
    c = f' class="{cls}"' if cls else ""
    return f'<circle{c} cx="{n(x)}" cy="{n(y)}" r="{n(r)}" fill="url(#h{color})"/>'


def seat_dot(x, y, color, r=7) -> str:
    key = "w" if color == WARM else "c"
    return head(x, y, key, r * 3.2) + f'<circle cx="{n(x)}" cy="{n(y)}" r="{n(r)}" fill="{color}"/>'


def corners(x0, y0, x1, y1, size=14, color=LINE, width=1.5) -> str:
    """Registration marks at the corners of a plate."""
    out = []
    for x, y, dx, dy in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
        out.append(f'M{n(x)} {n(y + dy * size)}V{n(y)}H{n(x + dx * size)}')
    return f'<path d="{"".join(out)}" fill="none" stroke="{color}" stroke-width="{width}"/>'


def box(x, y, w, h, stroke=LINE, fill=PANEL, dash="", rx=8, opacity=None, extra="") -> str:
    d = f' stroke-dasharray="{dash}"' if dash else ""
    o = f' fill-opacity="{opacity}"' if opacity is not None else ""
    return (f'<rect x="{n(x)}" y="{n(y)}" width="{n(w)}" height="{n(h)}" rx="{rx}" fill="{fill}"{o} '
            f'stroke="{stroke}" stroke-width="1.4"{d}{" " + extra if extra else ""}/>')


def label_box(cx, cy, w, h, lines, stroke=LINE, size=NOTE, fill=TEXT, dash="", bg=PANEL) -> str:
    parts = [box(cx - w / 2, cy - h / 2, w, h, stroke, bg, dash)]
    step = size + 5
    top = cy - (len(lines) - 1) * step / 2 + size * 0.34
    for i, value in enumerate(lines):
        parts.append(text(cx, top + i * step, value, size, fill, "middle"))
    return "".join(parts)


def card(x, y, w=26, h=34, empty=False) -> str:
    """A ruling card: both answers (cool and warm rules) and a witness line. Dashed and empty: no card."""
    if empty:
        return box(x, y, w, h, LINE, "none", "4 3", 4)
    p = w * 0.22
    return (box(x, y, w, h, TEXT, VOID, rx=4)
            + f'<path d="M{n(x + p)} {n(y + h * .3)}H{n(x + w - p)}" stroke="{COOL}" stroke-width="2.2"/>'
            + f'<path d="M{n(x + p)} {n(y + h * .52)}H{n(x + w - p)}" stroke="{WARM}" stroke-width="2.2"/>'
            + f'<path d="M{n(x + p)} {n(y + h * .74)}H{n(x + w * .55)}" stroke="{MUTE}" stroke-width="2.2"/>')


def stars(rng, count, x0, y0, x1, y1, avoid=(), fringe=False, bright=False) -> str:
    """Seeded fixed stars. Bright ones in a band carry a faint warm and cool fringe."""
    out, made = [], 0
    while made < count:
        x, y = rng.uniform(x0, x1), rng.uniform(y0, y1)
        if any(a <= x <= c and b <= y <= d for a, b, c, d in avoid):
            continue
        made += 1
        r = 0.5 + rng.random() ** 4 * (2.8 if bright else 1.2)
        o = (0.4 + rng.random() * 0.5) if bright else (0.12 + rng.random() * 0.3)
        if fringe and r > 1.5:
            out.append(f'<circle cx="{n(x - 1.3)}" cy="{n(y)}" r="{n(r)}" fill="{WARM}" opacity="{o * .55:.2f}"/>'
                       f'<circle cx="{n(x + 1.3)}" cy="{n(y)}" r="{n(r)}" fill="{COOL}" opacity="{o * .55:.2f}"/>')
        out.append(f'<circle cx="{n(x)}" cy="{n(y)}" r="{r:.2f}" fill="{TEXT}" opacity="{o:.2f}"/>')
    return "".join(out)


def contract_band(rng, x0, x1, cy, half=24, count=None) -> str:
    """The frozen contract: a band of fixed stars between two dotted rules."""
    count = count or int((x1 - x0) / 9)
    return (f'<rect x="{n(x0)}" y="{n(cy - half)}" width="{n(x1 - x0)}" height="{2 * half}" fill="{PANEL}" fill-opacity=".55"/>'
            f'<path d="M{n(x0)} {n(cy - half)}H{n(x1)}M{n(x0)} {n(cy + half)}H{n(x1)}" stroke="{MUTE}" '
            f'stroke-width="1" stroke-dasharray="2 5"/>'
            + stars(rng, count, x0 + 4, cy - half + 5, x1 - 4, cy + half - 5, fringe=True, bright=True))


def heading(title, sub=()) -> str:
    out = [text(40, 58, title, H1, TEXT, weight=600)]
    for i, line in enumerate(sub):
        out.append(text(40, 94 + i * 28, line, NOTE, MUTE))
    return "".join(out)


def grad(gid, x1, y1, x2, y2, color, white_from=0.62) -> str:
    """A stroke gradient along a line, from a seat color to white: the stretch where the lines agree."""
    return (f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="{n(x1)}" y1="{n(y1)}" x2="{n(x2)}" y2="{n(y2)}">'
            f'<stop offset="0" stop-color="{color}"/><stop offset="{white_from}" stop-color="{color}"/>'
            f'<stop offset="1" stop-color="#fff"/></linearGradient>')


DRAW = "stroke-dasharray:1 2;animation:draw {d}s cubic-bezier(.5,0,.2,1) {t}s both"


# ------------------------------------------------------------------ banner

def banner() -> str:
    h = 520
    rng = random.Random(23)
    cx, cy = 480, 100                                       # the crossing
    codex, claude = (64, 266), (896, 266)                   # the seats
    band_y = 42

    def beyond(seat):                                       # where a line through the crossing meets the band
        dx, dy = cx - seat[0], cy - seat[1]
        t = (band_y - cy) / dy
        return cx + dx * t, band_y

    ec, ew = beyond(codex), beyond(claude)

    def unit(seat):
        dx, dy = cx - seat[0], cy - seat[1]
        length = (dx * dx + dy * dy) ** 0.5
        return dx / length, dy / length

    uc, uw = unit(codex), unit(claude)
    k = 46                                                  # half the stretch that turns white

    parts = [
        stars(rng, 130, 14, 72, W - 14, h - 14,
              avoid=[(120, 186, 840, 380), (40, 384, 920, 500), (400, 70, 560, 175)]),
        f'<g mask="url(#ends)">{contract_band(rng, 24, 936, band_y, 20, 104)}</g>',
        # lines: seat to crossing, the white stretch, crossing on to the contract
        sight(f"M{codex[0]} {codex[1]}L{cx} {cy}", COOL, 2.6, "d1"),
        sight(f"M{claude[0]} {claude[1]}L{cx} {cy}", WARM, 2.6, "d1"),
        sight(f"M{n(cx)} {cy}L{n(ec[0])} {n(ec[1])}", COOL, 2.2, "d3"),
        sight(f"M{n(cx)} {cy}L{n(ew[0])} {n(ew[1])}", WARM, 2.2, "d3"),
        sight(f"M{n(cx - uc[0] * k)} {n(cy - uc[1] * k)}L{n(cx + uc[0] * k)} {n(cy + uc[1] * k)}", WHITE, 2.8, "d2"),
        sight(f"M{n(cx - uw[0] * k)} {n(cy - uw[1] * k)}L{n(cx + uw[0] * k)} {n(cy + uw[1] * k)}", WHITE, 2.8, "d2"),
        # landing on the contract
        f'<g class="land">{head(ec[0], ec[1], "c", 18)}{head(ew[0], ew[1], "w", 18)}'
        f'<path d="M{n(ec[0])} {band_y - 14}v28" stroke="{COOL}" stroke-width="3"/>'
        f'<path d="M{n(ew[0])} {band_y - 14}v28" stroke="{WARM}" stroke-width="3"/></g>',
        # the crossing
        f'<g class="x">{head(cx, cy, "x", 64)}'
        f'<circle cx="{cx}" cy="{cy}" r="14" fill="none" stroke="#fff" stroke-opacity=".75" stroke-width="1.4"/>'
        f'<circle cx="{cx}" cy="{cy}" r="5" fill="#fff"/></g>',
        text(cx, 162, "the crossing", NOTE, MUTE, "middle", cls="lab"),
        seat_dot(*codex, COOL), seat_dot(*claude, WARM),
        text(codex[0], 310, "codex", BODY, COOL, "middle", 600),
        text(claude[0], 310, "claude", BODY, WARM, "middle", 600),
    ]
    # the wordmark: alternating cool and warm letters, with a warm and a cool fringe that fuse
    word = 'x="480" y="346" font-size="150" font-weight="800" text-anchor="middle" textLength="680" lengthAdjust="spacingAndGlyphs"'
    letters = "".join(f'<tspan fill="{COOL if i % 2 == 0 else WARM}">{ch}</tspan>' for i, ch in enumerate("parallax"))
    parts += [
        f'<text class="s halo" {word} filter="url(#soft)" opacity=".42">{letters}</text>',
        f'<text class="s gw" {word} fill="{WARM}">parallax</text>',
        f'<text class="s gc" {word} fill="{COOL}">parallax</text>',
        f'<text class="s core" {word}>{letters}</text>',
        text(cx, 416, "One model builds. The other checks, blind.", 30, TEXT, "middle", 600),
        text(cx, 456, "Two different models on every change. Their agreement is the evidence.", BODY, SOFT, "middle"),
        text(cx, 488, "Their disagreement is the only thing that reaches you.", BODY, MUTE, "middle"),
    ]
    style = f"""
.d1 path{{{DRAW.format(d=1.3, t=.3)}}}
.d2 path{{{DRAW.format(d=.5, t=1.45)}}}
.d3 path{{{DRAW.format(d=.8, t=1.75)}}}
.x{{transform-box:fill-box;transform-origin:center;animation:pop 1s ease-out 1.4s both}}
.land{{animation:fade .6s ease-out 2.4s both}}
.lab{{animation:fade .8s ease-out 1.9s both}}
.gw,.gc{{mix-blend-mode:screen;opacity:.8}}
.gw{{transform:translateX(-3px);animation:gw 2s cubic-bezier(.2,.7,.2,1) both}}
.gc{{transform:translateX(3px);animation:gc 2s cubic-bezier(.2,.7,.2,1) both}}
.core{{animation:core 2s ease-out both}}
.halo{{animation:core 2.6s ease-out both}}
@keyframes pop{{0%{{opacity:0;transform:scale(.3)}}55%{{opacity:1;transform:scale(1.25)}}100%{{opacity:1;transform:scale(1)}}}}
@keyframes gw{{from{{transform:translateX(-40px);opacity:1}}}}
@keyframes gc{{from{{transform:translateX(40px);opacity:1}}}}
@keyframes core{{0%,45%{{opacity:0}}}}
"""
    defs = ('<filter id="soft" x="-10%" y="-50%" width="120%" height="200%"><feGaussianBlur stdDeviation="10"/></filter>'
            '<linearGradient id="endg"><stop offset="0" stop-color="#fff" stop-opacity="0"/>'
            '<stop offset=".2" stop-color="#fff"/><stop offset=".8" stop-color="#fff"/>'
            '<stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>'
            f'<mask id="ends" maskUnits="userSpaceOnUse" x="0" y="0" width="{W}" height="90">'
            f'<rect width="{W}" height="90" fill="url(#endg)"/></mask>')
    return frame(h, "\n".join(parts), "Parallax: codex and claude look at one change from two positions; "
                                      "where their lines cross is the evidence.", style, defs)


# -------------------------------------------------------------------- flow

def flow() -> str:
    h = 936
    # column centers, set by hand so the reveal and the crossing have room to draw their lines
    top_cols = [256, 426, 664, 842]                         # open, sealed readings, reveal, settle
    bot_cols = [290, 600, 836]                              # braid, crossing, land
    lanes_top = (206, 280, 354)                             # codex, conductor, claude
    lanes_bot = (572, 646, 720)
    band_y = 458
    bw, bh = 164, 56                                        # top boxes
    bw2 = 192                                               # bottom boxes
    rng = random.Random(5)
    defs = (grad("fc", bot_cols[0] + bw2 / 2, lanes_bot[0], bot_cols[1] - 102, lanes_bot[1], COOL, .55)
            + grad("fw", bot_cols[0] + bw2 / 2, lanes_bot[2], bot_cols[1] - 102, lanes_bot[1], WARM, .55))
    p = [heading("One task, start to finish",
                 ["The conductor is plain Python. It holds no model,",
                  "does all the git work and runs every check."])]

    def lane_labels(ys):
        out = []
        for (name, role), y in zip((("codex", "builder"), ("conductor", "plain Python"), ("claude", "challenger")), ys):
            color = SEAT.get(name, TEXT)
            out.append(text(40, y - 3, name, BODY, color, weight=600))
            out.append(text(40, y + 22, role, NOTE, MUTE))
        return "".join(out)

    # ---- before the contract: open, sealed readings, reveal, settle
    for name, x in zip(("open", "sealed readings", "reveal", "settle"), top_cols):
        p.append(text(x, 162, name, NOTE, SOFT, "middle", 600))
    p.append(lane_labels(lanes_top))
    cy, ct, cw = lanes_top[1], lanes_top[0], lanes_top[2]
    p.append(f'<path d="M{n(top_cols[0] + 75)} {cy}H{n(top_cols[3] - 84)}" stroke="{LINE}" stroke-width="2"/>')
    for x in top_cols[1:3]:
        p.append(f'<circle cx="{n(x)}" cy="{cy}" r="4" fill="{MUTE}"/>')
    # seat lines into the sealed readings
    for y, color in ((ct, COOL), (cw, WARM)):
        p.append(sight(f"M{n(top_cols[1] - bw / 2 - 26)} {y}H{n(top_cols[1] - bw / 2)}", color, 2.2))
        p.append(seat_dot(top_cols[1] - bw / 2 - 26, y, color, 5))
    # each reading goes to the other seat at the reveal
    a, b = top_cols[1] + bw / 2, top_cols[2] - bw / 2
    p.append(sight(f"M{n(a)} {ct + 10}L{n(b)} {cw - 10}", COOL, 1.8, "d1"))
    p.append(sight(f"M{n(a)} {cw - 10}L{n(b)} {ct + 10}", WARM, 1.8, "d1"))
    p.append(label_box(top_cols[0], cy, 150, bh, ["read task,", "assign roles"]))
    for y, color in ((ct, COOL), (cw, WARM)):
        p.append(label_box(top_cols[1], y, bw, bh, ["its reading,", "alone"], color))
        p.append(label_box(top_cols[2], y, bw, bh, ["reviews the", "other reading"], color))
    p.append(label_box(top_cols[3], cy, 168, bh, ["settlement"]))
    # the human: only at the settlement, only on a split
    p.append(f'<path d="M{n(top_cols[3])} {ct + bh / 2}V{cy - bh / 2}" stroke="{TEXT}" stroke-width="1.4" stroke-dasharray="4 4"/>')
    p.append(label_box(top_cols[3], ct, 168, bh, ["you: a card,", "only on a split"], TEXT, dash="5 4", bg=VOID))
    p.append(text((top_cols[1] + top_cols[2]) / 2, 418, "hashes sealed before either is shown", NOTE, MUTE, "middle"))

    # ---- the contract
    p.append(f'<path d="M{n(top_cols[3])} {cy + bh / 2}V{band_y - 26}" stroke="{LINE}" stroke-width="2"/>')
    p.append(contract_band(rng, 40, 920, band_y, 24, 80))
    p.append(box(330, band_y - 19, 300, 38, LINE, VOID, rx=6))
    p.append(rich(480, band_y + 7, [("contract  ", TEXT, 600), ("frozen + hashed", SOFT, 400)], NOTE, "middle"))

    # ---- after: braid, crossing, land
    for name, x in zip(("braid", "crossing", "land"), bot_cols):
        p.append(text(x, 528, name, NOTE, SOFT, "middle", 600))
    p.append(lane_labels(lanes_bot))
    bt, bc, bwy = lanes_bot
    for y, color in ((bt, COOL), (bwy, WARM)):
        p.append(sight(f"M{n(bot_cols[0] - bw2 / 2 - 40)} {y}H{n(bot_cols[0] - bw2 / 2)}", color, 2.2))
        p.append(seat_dot(bot_cols[0] - bw2 / 2 - 40, y, color, 5))
    xa, xb = bot_cols[0] + bw2 / 2, bot_cols[1] - 102
    mid = (xa + xb) / 2
    p.append(sight(f"M{n(xa)} {bt}C{n(mid)} {bt} {n(mid)} {bc} {n(xb)} {bc}", COOL, 2.4, "d2", "fc"))
    p.append(sight(f"M{n(xa)} {bwy}C{n(mid)} {bwy} {n(mid)} {bc} {n(xb)} {bc}", WARM, 2.4, "d2", "fw"))
    p.append(sight(f"M{n(bot_cols[1] + 102)} {bc}H{n(bot_cols[2] - bw2 / 2)}", WHITE, 2.6, "d3"))
    p.append(label_box(bot_cols[0], bt, bw2, bh, ["the change", "+ mutants"], COOL))
    p.append(label_box(bot_cols[0], bwy, bw2, bh, ["probes, from", "the contract"], WARM))
    p.append(text(bot_cols[0], bc - 4, "neither sees the", NOTE, MUTE, "middle"))
    p.append(text(bot_cols[0], bc + 22, "other's files", NOTE, MUTE, "middle"))
    p.append(head(bot_cols[1] - 102, bc, "x", 26, "lit"))
    p.append(label_box(bot_cols[1], bc, 204, bh, ["probes x change", "probes x mutants"], SOFT))
    p.append(head(bot_cols[2] - bw2 / 2, bc, "x", 22, "lit"))
    p.append(label_box(bot_cols[2], bc, bw2, bh, ["main moves,", "with a receipt"], WHITE, fill=WHITE))
    # the repair loop
    yl = bwy + bh / 2 + 34
    p.append(f'<path d="M{n(bot_cols[1])} {bc + bh / 2}V{yl}H{n(bot_cols[0] + 40)}V{bwy + bh / 2 + 6}" fill="none" '
             f'stroke="{MUTE}" stroke-width="1.6" stroke-dasharray="5 4" marker-end="url(#arr)"/>')
    p.append(text(bot_cols[0] + 52, yl - 8, "repair", NOTE, MUTE))
    p.append(text(40, 820, "A failing probe or a surviving mutant goes back as evidence:", NOTE, SOFT))
    p.append(text(40, 848, "each seat concedes and repairs, or contests. At most two rounds.", NOTE, SOFT))
    p.append(text(40, 892, "Roles swap every task. Seats never message each other.", NOTE, TEXT, weight=600))
    p.append(rich(40, 920, [("Lanes show the stub demo's roles: ", MUTE, 400)] + seats_in("codex builds, claude challenges.", MUTE),
                  NOTE))
    style = f"""
.d1 path{{{DRAW.format(d=.9, t=.4)}}}
.d2 path{{{DRAW.format(d=1.1, t=.9)}}}
.d3 path{{{DRAW.format(d=.6, t=1.9)}}}
.lit{{animation:fade .5s ease-out 1.9s both}}
"""
    return frame(h, "\n".join(p), "The life of one task: open, sealed readings, reveal, settlement, contract, "
                                  "braid, crossing, landing with a receipt.", style, defs)


# ---------------------------------------------------------------- terminal

# Text the stub demo printed on 2026-11-23, condensed: the --repo and --dir arguments are
# cut from the commands, and the card's sources block is folded into one witness line.
REPLAY = [
    ("cmd", "python -m parallax demo --stub"),
    ("out", "clamp-001: opened (behavior); builder codex, challenger claude"),
    ("out", "clamp-001: claude's reading sealed"),
    ("out", "clamp-001: codex's reading sealed"),
    ("out", "clamp-001: claude's reveal done"),
    ("out", "clamp-001: codex's reveal done"),
    ("out", "clamp-001: settlement published (direct)"),
    ("hot", "clamp-001: needs a ruling on D-clamp-001-1"),
    ("gap", ""),
    ("card", "Dispute D-clamp-001-1 (reading)    What if lo > hi?"),
    ("cool", "  a) codex (builder):      raise ValueError"),
    ("warm", "  b) claude (challenger):  swap the bounds"),
    ("card", "  witness: clamp(5, 10, 1)   a raises ValueError, b returns 5"),
    ("gap", ""),
    ("cmd", "python -m parallax rule D-clamp-001-1 a"),
    ("out", "recorded D-clamp-001-1: a"),
    ("cmd", "python -m parallax demo --stub"),
    ("out", "clamp-001: contract v1 frozen"),
    ("out", "clamp-001: codex's build 1 finished"),
    ("out", "clamp-001: claude's probe 1 finished"),
    ("out", "clamp-001: crossing 1: check passed, 3 of 3 mutants caught"),
    ("hot", "clamp-001: landed 1a0a4035f05a   Verdict: ruled"),
]


def terminal() -> str:
    size, step, gap, left, top = 23, 34, 20, 38, 114
    ys, y = [], top
    for kind, _ in REPLAY:
        ys.append(y)
        y += gap if kind == "gap" else step
    h = ys[-1] + 64
    parts = [f'<rect x="0" y="5" width="{W}" height="55" fill="{VOID}" fill-opacity=".7"/>',
             f'<path d="M0 60H{W}" stroke="#fff" stroke-opacity=".08"/>',
             *(f'<circle cx="{34 + 22 * i}" cy="33" r="6" fill="{LINE}"/>' for i in range(3)),
             text(W / 2, 40, "the stub demo: no tokens spent", NOTE, MUTE, "middle")]
    # the card the run prints, as a printed card: both seats' colors on its edge
    cards = [i for i, (k, _) in enumerate(REPLAY) if k in ("card", "cool", "warm")]
    c0, c1 = ys[cards[0]] - 27, ys[cards[-1]] + 15
    parts.append(box(26, c0, W - 52, c1 - c0, "#fff", PANEL, rx=8, opacity=".55", extra='stroke-opacity=".22" class="l9"'))
    parts.append(f'<rect class="l9" x="26" y="{c0 + 8}" width="5" height="{c1 - c0 - 16}" fill="url(#foldv)"/>')
    styles, at = [], 0.5
    for i, (kind, value) in enumerate(REPLAY):
        if kind == "gap":
            at += 0.5
            continue
        if kind == "cmd":
            line = [("$ ", MUTE, 400), (value, TEXT, 600)]
        elif kind == "hot":
            line = seats_in(value, TEXT, 600)
        elif kind == "out":
            line = seats_in(value, SOFT, 400, 600)
        else:
            line = seats_in(value, TEXT, 400, 600)
        parts.append(rich(left + (14 if kind in ("card", "cool", "warm") else 0), ys[i], line, size, mono=True,
                          cls=f"l{i}", extra='xml:space="preserve"'))
        styles.append(f".l{i}{{animation:fade .3s ease-out {at:.2f}s both}}")
        at += 0.9 if kind == "cmd" else 0.42
    styles.append(".l9{animation:fade .5s ease-out 4.1s both}")
    # a cursor after the last line: appears, blinks three times, stays
    last = ys[-1]
    parts.append(f'<rect class="cur" x="{left}" y="{last + 14}" width="13" height="24" fill="{TEXT}" fill-opacity=".85"/>')
    styles.append(f".cur{{animation:fade .1s {at:.2f}s both,blink 1s steps(1) {at + .1:.2f}s 3}}"
                  "@keyframes blink{50%{opacity:0}}")
    defs = (f'<pattern id="foldv" width="6" height="24" patternUnits="userSpaceOnUse">'
            f'<rect width="6" height="12" fill="{COOL}"/><rect y="12" width="6" height="12" fill="{WARM}"/></pattern>')
    return frame(h, "\n".join(parts), "Terminal replay of the stub demo: the seats disagree about lo > hi, "
                                      "a ruling card is printed, the human rules, the task lands.", "\n".join(styles), defs)


# ----------------------------------------------------------------- receipt

def receipt() -> str:
    rows = [("Parallax-Task", "clamp-001", TEXT),
            ("Parallax-Contract", "sha256:c317c9e49ac1...6a93fe083", TEXT),
            ("Built-by", "codex gpt-6.2-astra/xhigh", COOL),
            ("Challenged-by", "claude fable/high", WARM),
            ("Checks", "84 probes passed, 3 of 3 mutants caught", TEXT),
            ("Verdict", "consensus", WHITE)]
    size, step = 22, 38
    tx, tw = 40, 882                                        # the ticket: 63 teeth wide
    slot_y = 86
    t_top, head_y = slot_y + 10, slot_y + 62
    rows_y = head_y + 60
    t_bot = rows_y + step * (len(rows) - 1) + 30
    # the torn edge: a row of teeth along the bottom
    outline = (f'M{tx} {t_top}H{tx + tw}V{t_bot}' +
               "".join(f"L{n(tx + tw - 7 - 14 * i)} {t_bot + 9}L{n(tx + tw - 14 - 14 * i)} {t_bot}" for i in range(int(tw / 14)))
               + f"L{tx} {t_bot}Z")
    paper = [f'<path d="{outline}" fill="#15273f" stroke="{LINE}" stroke-width="1.2"/>',
             f'<path d="{outline}" fill="url(#grain)"/>',
             rich(tx + 28, head_y, [("293c8db  ", MUTE, 400), ("clamp-001: Add clamp(x, lo, hi) to clamplib", TEXT, 600)],
                  size, mono=True, cls="r0"),
             f'<path d="M{tx + 28} {head_y + 22}H{tx + tw - 28}" stroke="{LINE}" stroke-width="1.4" stroke-dasharray="6 5"/>']
    for i, (key, value, color) in enumerate(rows):
        y = rows_y + i * step
        last = key == "Verdict"
        paper.append(rich(tx + 28, y, [(f"{key}:", MUTE, 400)], size, mono=True, cls=f"r{i + 1}"))
        paper.append(text(tx + 28 + 19 * size * 0.6, y, value, BODY if last else size, color, weight=700 if last else 400,
                          mono=True, cls=f"r{i + 1}"))
    p = [heading("Every commit on main carries its receipt"),
         f'<g clip-path="url(#feed)"><g class="tk">{"".join(paper)}</g></g>',
         # the printer slot, drawn over the top of the ticket
         f'<rect x="24" y="{slot_y - 12}" width="{W - 48}" height="24" rx="12" fill="{VOID}" stroke="{LINE}"/>',
         f'<rect x="44" y="{slot_y + 7}" width="{W - 88}" height="4" rx="2" fill="url(#fold)"/>']
    vy = t_bot + 66
    p.append(text(40, vy, "The verdict says how it got there", BODY, SOFT, weight=600))
    verdicts = [("consensus", "clean at the first crossing"),
                ("resolved", "a failed crossing, repaired by the seats"),
                ("ruled", "a human ruling was needed"),
                ("limited", "accepted with a stated limitation"),
                ("solo", "a chore, built by one seat")]
    for i, (name, meaning) in enumerate(verdicts):
        x = tx + 24 + (i // 3) * 440
        y = vy + 48 + (i % 3) * 68
        on = name == "consensus"
        if on:
            p.append(f'<circle cx="{x - 14}" cy="{y - 7}" r="4.5" fill="#fff"/>')
        p.append(text(x, y, name, BODY, TEXT if on else SOFT, weight=600 if on else 400, mono=True))
        p.append(text(x, y + 28, meaning, NOTE, MUTE))
    fy = vy + 48 + 3 * 68 + 4
    p.append(text(40, fy, "The receipt of the first real run with the settlement, 2026-11-23.", NOTE, MUTE))
    p.append(text(40, fy + 28, "Hash shortened to fit.", NOTE, MUTE))
    h = fy + 50
    styles = [".tk{animation:feed 1.5s cubic-bezier(.3,.6,.2,1) .2s both}",
              f"@keyframes feed{{from{{transform:translateY(-{t_bot - t_top + 20}px)}}}}"]
    for i in range(len(rows) + 1):
        styles.append(f".r{i}{{animation:fade .4s ease-out {1.0 + i * .18:.2f}s both}}")
    defs = f'<clipPath id="feed"><rect x="0" y="{slot_y}" width="{W}" height="{t_bot - slot_y + 20}"/></clipPath>'
    return frame(h, "\n".join(p), "A landing commit's receipt: task, contract hash, builder, challenger, "
                                  "checks and verdict.", "\n".join(styles), defs)


# ------------------------------------------------------------------ routes

def routes() -> str:
    rows = [("nothing in dispute", "the contract freezes", "no card", False),
            ("one objection", "both answers, both reasons, the case that splits them", "one card", True),
            ("several, or two provisions conflict",
             "one more exchange: the builder proposes one account, the challenger reviews exactly that",
             "a card only where each|holds a different answer", True),
            ("a seat refuses the proposal", "both agree what a ruling would have to replace",
             "one card: replace or drop", True)]
    tx, tw, rx = 214, 384, 620                              # text column, its width, result column
    y, laid = 140, []
    for when, what, result, has_card in rows:
        what_lines = wrap(what, NOTE, tw)
        res_lines = result.split("|")
        hgt = max(30 + 28 * len(what_lines), 6 + 29 * len(res_lines)) + 34
        laid.append((y, hgt, when, what_lines, res_lines, has_card))
        y += hgt
    h = y + 120
    oy = (laid[0][0] + laid[-1][0] + laid[-1][1]) / 2 - 10
    ox = 74
    p = [heading("How a disagreement reaches you", ["After the reveals, how much the seats disagree decides the route."])]
    p.append(f'<path d="M{rx - 26} 130V{y - 10}" stroke="#fff" stroke-opacity=".07" stroke-width="1"/>')
    for i, (ty, hgt, when, what_lines, res_lines, has_card) in enumerate(laid):
        ry = ty + 22
        d = f"M{ox} {n(oy)}C{ox + 70} {n(oy)} {ox + 40} {n(ry)} {tx - 18} {n(ry)}"
        if i == 0:                                          # agreement: one white line
            p.append(sight(d, WHITE, 2.2, f"d{i}"))
        else:                                               # disagreement: the two seats' lines, apart
            p.append(f'<g transform="translate(0 -3)">{sight(d, COOL, 1.8, f"d{i}")}</g>'
                     f'<g transform="translate(0 3)">{sight(d, WARM, 1.8, f"d{i}")}</g>')
        p.append(text(tx, ry + 7, when, BODY, TEXT, weight=600))
        for j, line in enumerate(what_lines):
            p.append(text(tx, ry + 37 + j * 28, line, NOTE, MUTE))
        p.append(card(rx, ry - 14, empty=not has_card))
        for j, line in enumerate(res_lines):
            p.append(text(rx + 42, ry + 7 + j * 28, line, 22, TEXT if has_card else MUTE, weight=600))
        if i:
            p.append(f'<path d="M{tx} {ty}H920" stroke="#fff" stroke-opacity=".07"/>')
    p.append(head(ox, oy, "x", 22) + f'<circle cx="{ox}" cy="{n(oy)}" r="6" fill="#fff"/>')
    p.append(text(ox - 34, oy + 7, "reveals", NOTE, MUTE, "middle", extra='transform="rotate(-90 ' + n(ox - 34) + ' ' + n(oy) + ')"'))
    p.append(text(40, h - 86, "If the seats cannot agree on what a ruling would replace,", NOTE, MUTE))
    p.append(text(40, h - 58, "the task is blocked and status says why.", NOTE, MUTE))
    p.append(text(40, h - 30, "Nothing is built until every card is ruled.", NOTE, SOFT, weight=600))
    style = "\n".join(f".d{i} path{{{DRAW.format(d=.8, t=.2 + i * .15)}}}" for i in range(4))
    return frame(h, "\n".join(p), "Four routes from the reveals: no dispute, one objection, several objections "
                                  "or a conflict, and a refused proposal.", style)


# ------------------------------------------------------------------- blind

def blind() -> str:
    h = 884
    p = [heading("How the blind is kept", ["Enforced where each CLI can enforce it, audited everywhere.",
                                           "Seats are treated as fallible, not hostile."])]
    # your project and the conductor
    p.append(box(40, 156, 340, 88, TEXT, PANEL))
    p.append(text(210, 192, "your project", BODY, TEXT, "middle", 600))
    p.append(text(210, 224, "main + .parallax/ledger", 20, SOFT, "middle", mono=True))
    p.append(text(210, 276, "nothing a seat writes", NOTE, MUTE, "middle"))
    p.append(text(210, 302, "enters it until the task lands", NOTE, MUTE, "middle"))
    p.append(f'<path d="M380 200H492" stroke="{MUTE}" stroke-width="1.6" marker-end="url(#arr)"/>')
    p.append(box(500, 156, 420, 88, LINE, PANEL))
    p.append(text(710, 192, "conductor", BODY, TEXT, "middle", 600))
    p.append(text(710, 224, "git, checks, audit", NOTE, SOFT, "middle"))
    # briefs down, events up
    p.append(f'<path d="M670 244V330" stroke="{MUTE}" stroke-width="1.6" marker-end="url(#arr)"/>')
    p.append(f'<path d="M750 338V252" stroke="{MUTE}" stroke-width="1.6" marker-end="url(#arr)"/>')
    p.append(text(658, 298, "briefs", NOTE, MUTE, "end"))
    p.append(text(764, 298, "events", NOTE, MUTE))
    # the state folder
    sx, sy, sw, sh = 40, 338, 880, 368
    p.append(box(sx, sy, sw, sh, MUTE, VOID, "6 5", 12, ".45"))
    p.append(text(sx + 24, sy + 40, "state folder", NOTE, TEXT, weight=600))
    p.append(text(sx + 160, sy + 40, "~/.parallax/<project key>/<task>", 20, SOFT, mono=True))
    p.append(text(sx + 24, sy + 70, "private to your account, SYSTEM and Administrators", NOTE, MUTE))
    cy0, ch = sy + 96, 104
    left, right = (sx + 24, sx + sw / 2 - 30), (sx + sw / 2 + 30, sx + sw - 24)
    xc0, xc1, xy = sx + 24, sx + sw - 24, cy0 + ch + 52
    mid = sx + sw / 2
    defs = (grad("bw", (left[0] + left[1]) / 2, cy0 + ch, mid - 40, xy, WARM, .45)
            + grad("bc", (right[0] + right[1]) / 2, cy0 + ch, mid + 40, xy, COOL, .45))
    # each clone's work runs down to the crossing, where it meets the other's and turns white
    p.append(sight(f"M{n((left[0] + left[1]) / 2)} {cy0 + ch}C{n((left[0] + left[1]) / 2)} {xy - 20} {n(mid - 40)} {xy - 30} "
                   f"{n(mid - 40)} {xy}", WARM, 2.2, "d1", "bw"))
    p.append(sight(f"M{n((right[0] + right[1]) / 2)} {cy0 + ch}C{n((right[0] + right[1]) / 2)} {xy - 20} {n(mid + 40)} {xy - 30} "
                   f"{n(mid + 40)} {xy}", COOL, 2.2, "d1", "bc"))
    for (a, b), seat, note, color in ((left, "claude", "file tools only, no shell", WARM),
                                      (right, "codex", "workspace-write sandbox", COOL)):
        p.append(box(a, cy0, b - a, ch, color, PANEL))
        p.append(rich((a + b) / 2, cy0 + 44, [(seat, color, 600), ("'s clone", TEXT, 600)], BODY, "middle"))
        p.append(text((a + b) / 2, cy0 + 76, note, NOTE, SOFT, "middle"))
    # the blind between the clones
    p.append(f'<path d="M{mid} {cy0 - 14}V{cy0 + ch + 14}" stroke="#fff" stroke-opacity=".12" stroke-width="10"/>'
             f'<path d="M{mid} {cy0 - 14}V{cy0 + ch + 14}" stroke="#fff" stroke-width="2" stroke-dasharray="3 6"/>')
    p.append(head(mid - 40, xy, "x", 20, "lit") + head(mid + 40, xy, "x", 20, "lit"))
    p.append(box(xc0, xy, xc1 - xc0, 88, SOFT, PANEL))
    p.append(text(mid, xy + 38, "crossing, mutants, artifacts", BODY, TEXT, "middle", 600))
    p.append(text(mid, xy + 68, "the conductor's alone: both seats' work meets here", NOTE, SOFT, "middle"))
    # seal, audit, voiding
    notes = [("Seal: ", "readings and attempts are hashed into the ledger before the reveal."),
             ("Audit: ", "each event stream is scanned for the other seat's paths. Best effort."),
             ("Voiding: ", "a hit discards the attempt, its session and its clone. The rerun starts "
                           "from the contract alone.")]
    y = sy + sh + 50
    for label, body in notes:
        lines = wrap(label + body, NOTE, 880)
        first = lines[0][len(label):]
        p.append(rich(40, y, [(label, TEXT, 600), (first, SOFT, 400)], NOTE))
        for extra in lines[1:]:
            y += 28
            p.append(text(40, y, extra, NOTE, SOFT))
        y += 34
    style = f".d1 path{{{DRAW.format(d=1.1, t=.4)}}}\n.lit{{animation:fade .5s ease-out 1.4s both}}"
    return frame(max(h, int(y)), "\n".join(p), "Each seat works in its own clone inside a private state folder; the "
                                               "conductor alone combines their work.", style, defs)


# ---------------------------------------------------------------- evidence

def evidence() -> str:
    runs = [("17 November", "before the settlement step", "codex", "claude", "codex builds, claude challenges", 4,
             "four rulings", "90 probes pass, 3 of 3 mutants caught", "ruled"),
            ("23 November", "the same task, after it", "codex", "claude", "codex builds, claude challenges", 0,
             "nothing asked", "84 probes pass, 3 of 3 mutants caught", "consensus"),
            ("23 November", "roles swapped, a task that contradicts itself", "claude", "codex",
             "claude builds, codex challenges", 1, "one ruling", "108 probes pass, 3 of 3 mutants caught", "ruled")]
    top, ph, gap, px, pw = 150, 184, 18, 40, 880
    h = top + len(runs) * (ph + gap) + 12
    p = [heading("Three real runs of one small task",
                 ["Real Claude Code and Codex, one Windows 11 machine, 2026.", "Not a benchmark: what happened."])]
    defs = []
    for i, (date, what, builder, challenger, roles, cards, asked, checks, verdict) in enumerate(runs):
        y = top + i * (ph + gap)
        bc, cc = SEAT[builder], SEAT[challenger]
        defs.append(f'<clipPath id="p{i}"><rect x="{px}" y="{y}" width="{pw}" height="{ph}" rx="10"/></clipPath>')
        # the plate: the builder's color then the challenger's on its top edge
        p.append(f'<g clip-path="url(#p{i})"><rect x="{px}" y="{y}" width="{pw}" height="{ph}" fill="{PANEL}" fill-opacity=".6"/>'
                 f'<rect x="{px}" y="{y}" width="290" height="{ph}" fill="{VOID}" fill-opacity=".7"/>'
                 f'<rect x="{px}" y="{y}" width="{pw / 2}" height="5" fill="{bc}"/>'
                 f'<rect x="{px + pw / 2}" y="{y}" width="{pw / 2}" height="5" fill="{cc}"/></g>'
                 f'<rect x="{px + .5}" y="{y + .5}" width="{pw - 1}" height="{ph - 1}" rx="10" fill="none" stroke="{LINE}"/>')
        p.append(corners(px + 12, y + 17, px + 278, y + ph - 12, 10, LINE, 1.2))
        # a small sight-line diagram: builder left, challenger right, cards for what reached the human
        B, C, X = (px + 50, y + ph - 34), (px + 240, y + ph - 34), (px + 145, y + 44)
        defs.append(grad(f"b{i}", *B, *X, bc, .7) + grad(f"c{i}", *C, *X, cc, .7))
        p.append(sight(f"M{B[0]} {B[1]}L{X[0]} {X[1]}", bc, 2.2, f"d{i}", f"b{i}"))
        p.append(sight(f"M{C[0]} {C[1]}L{X[0]} {X[1]}", cc, 2.2, f"d{i}", f"c{i}"))
        p.append(seat_dot(*B, bc, 6) + seat_dot(*C, cc, 6))
        p.append(head(*X, "x", 26, f"x{i}") + f'<circle class="x{i}" cx="{X[0]}" cy="{X[1]}" r="5" fill="#fff"/>')
        cw, cg = 24, 8
        total = max(cards, 1) * cw + (max(cards, 1) - 1) * cg
        for c in range(max(cards, 1)):
            p.append(card(X[0] - total / 2 + c * (cw + cg), y + 92, cw, 32, empty=not cards))
        # the account
        tx = px + 318
        p.append(text(tx, y + 46, date, 25, TEXT, weight=600))
        chip = f"Verdict: {verdict}"
        chip_w = len(chip) * 20 * 0.6 + 28
        p.append(box(px + pw - 22 - chip_w, y + 22, chip_w, 34, "#fff", VOID, rx=17, extra='stroke-opacity=".35"'))
        p.append(text(px + pw - 22 - chip_w / 2, y + 45, chip, 20, TEXT, "middle", 600, mono=True))
        p.append(text(tx, y + 76, what, NOTE, MUTE))
        p.append(rich(tx, y + 110, seats_in(roles, SOFT, 400, 600), BODY))
        p.append(rich(tx, y + 141, [("asked of the human: ", MUTE, 400), (asked, TEXT, 600)], NOTE))
        p.append(text(tx, y + 170, checks, NOTE, SOFT))
    style = "\n".join(f".d{i} path{{{DRAW.format(d=1, t=.2 + i * .25)}}}\n.x{i}{{animation:fade .5s ease-out {1.1 + i * .25:.2f}s both}}"
                      for i in range(len(runs)))
    return frame(h, "\n".join(p), "Three real runs: four rulings before the settlement step, none after it on the "
                                  "same task, and one ruling on a task written to contradict itself. Every run "
                                  "landed with 3 of 3 mutants caught.", style, "".join(defs))


FIGURES = {"banner": banner, "evidence": evidence, "flow": flow, "terminal": terminal, "receipt": receipt, "routes": routes, "blind": blind}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, build in FIGURES.items():
        (OUT / f"{name}.svg").write_text(build(), encoding="utf-8", newline="\n")
        print(f"wrote docs/assets/{name}.svg")


if __name__ == "__main__":
    main()
