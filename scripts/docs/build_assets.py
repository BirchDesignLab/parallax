"""Write the SVG figures the README and docs/ show, into docs/assets/.

Why a script: the figures share one palette and one set of measurements, and the terminal
replay is built from text the stub demo really printed (2026-11-23), so they are generated
rather than drawn by hand. Rerun after changing anything here:

    python scripts/docs/build_assets.py

Rules the figures follow, because GitHub shows an SVG through <img>:
- no scripts, no external fonts or files; system font stacks only;
- each figure paints its own dark panel, so it reads on a light or a dark page;
- motion is CSS inside the file and stops under prefers-reduced-motion.

Colors: warm is the claude seat, cool is the codex seat, everywhere.
"""
from __future__ import annotations

import random
from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "docs" / "assets"

INK, PANEL, LINE = "#0c1726", "#13243b", "#2c4361"
TEXT, SOFT, MUTE = "#e9eff6", "#c3d0de", "#8da2b9"
WARM, COOL = "#f5b041", "#5cc8f2"
SANS = "'Segoe UI', 'Helvetica Neue', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, 'Cascadia Mono', 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace"
W = 960


def svg(height: int, body: str, title: str, style: str = "") -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {height}" width="{W}" height="{height}" '
            f'role="img" aria-label="{escape(title)}">\n<title>{escape(title)}</title>\n'
            f'<style>\n.s{{font-family:{SANS}}}.m{{font-family:{MONO}}}\n{style}\n'
            '@media (prefers-reduced-motion: reduce){*{animation:none!important}}\n</style>\n'
            f'<rect width="{W}" height="{height}" rx="14" fill="{INK}"/>\n{body}\n</svg>\n')


def text(x, y, value, size=13, fill=TEXT, cls="s", anchor="start", weight=400, extra="") -> str:
    return (f'<text x="{x}" y="{y}" class="{cls}" font-size="{size}" fill="{fill}" text-anchor="{anchor}" '
            f'font-weight="{weight}" {extra}>{escape(value)}</text>')


def box(x, y, w, h, stroke=LINE, fill=PANEL, dash="") -> str:
    dashed = f' stroke-dasharray="{dash}"' if dash else ""
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="7" fill="{fill}" stroke="{stroke}"{dashed}/>'


def label_box(x, y, w, h, lines, stroke=LINE, color=TEXT, dash="", size=11.5) -> str:
    parts = [box(x, y, w, h, stroke, PANEL if not dash else "none", dash)]
    top = y + h / 2 - (len(lines) - 1) * (size + 3) / 2 + size * 0.36
    for i, line in enumerate(lines):
        parts.append(text(x + w / 2, round(top + i * (size + 3), 1), line, size, color, anchor="middle"))
    return "\n".join(parts)


def line(x1, y1, x2, y2, stroke=LINE, width=1.4, dash="", extra="") -> str:
    dashed = f' stroke-dasharray="{dash}"' if dash else ""
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-width="{width}"{dashed} {extra}/>'


ARROW = (f'<defs><marker id="a" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">'
         f'<path d="M0 0 8 4 0 8z" fill="{MUTE}"/></marker></defs>')


# ------------------------------------------------------------------ banner

def banner() -> str:
    h = 330
    rng = random.Random(23)
    stars = "".join(f'<circle cx="{rng.randint(20, W - 20)}" cy="{rng.randint(14, h - 14)}" '
                    f'r="{rng.choice((0.6, 0.8, 1.1))}" fill="{TEXT}" opacity="{rng.choice((0.18, 0.28, 0.4))}"/>'
                    for _ in range(90))
    ax, ay, bx, by, fx, fy = 36, 48, W - 36, 48, W / 2, 124
    ex, ey = 2 * fy - ay, 2 * fy - ay                      # mirrored end height past the crossing
    grads = (f'<defs><linearGradient id="gw" x1="0" x2="1"><stop offset="0" stop-color="{WARM}" stop-opacity=".55"/>'
             f'<stop offset="1" stop-color="{WARM}" stop-opacity="0"/></linearGradient>'
             f'<linearGradient id="gc" x1="1" x2="0"><stop offset="0" stop-color="{COOL}" stop-opacity=".55"/>'
             f'<stop offset="1" stop-color="{COOL}" stop-opacity="0"/></linearGradient></defs>')
    rays = (f'<line class="ray" x1="{ax}" y1="{ay}" x2="{fx}" y2="{fy}" stroke="{WARM}" stroke-width="1.6"/>'
            f'<line class="ray" x1="{bx}" y1="{by}" x2="{fx}" y2="{fy}" stroke="{COOL}" stroke-width="1.6"/>'
            f'<line class="tail" x1="{fx}" y1="{fy}" x2="{bx}" y2="{ey}" stroke="url(#gw)" stroke-width="1.2"/>'
            f'<line class="tail" x1="{fx}" y1="{fy}" x2="{ax}" y2="{ey}" stroke="url(#gc)" stroke-width="1.2"/>')
    points = (f'<circle cx="{ax}" cy="{ay}" r="5" fill="{WARM}"/><circle cx="{bx}" cy="{by}" r="5" fill="{COOL}"/>'
              f'<circle class="ring" cx="{fx}" cy="{fy}" r="9" fill="none" stroke="{TEXT}" stroke-width="1"/>'
              f'<circle cx="{fx}" cy="{fy}" r="3.6" fill="{TEXT}"/>')
    word = 'font-size="78" font-weight="600" text-anchor="middle" letter-spacing="7"'
    mark = (f'<text class="s wl" x="{fx}" y="236" {word} fill="{COOL}" opacity=".9">parallax</text>'
            f'<text class="s wr" x="{fx}" y="236" {word} fill="{WARM}" opacity=".9">parallax</text>'
            f'<text class="s" x="{fx}" y="236" {word} fill="{TEXT}">parallax</text>')
    words = "\n".join([
        text(ax - 6, ay - 18, "one model builds", 14, WARM),
        text(bx + 6, by - 18, "the other checks, blind", 14, COOL, anchor="end"),
        text(fx, fy - 24, "the crossing", 13, MUTE, anchor="middle"),
        text(fx, 276, "Two different models on every change. Their agreement is the evidence.", 19, TEXT, "s", "middle"),
        text(fx, 304, "Their disagreement is the only thing that reaches you.", 15, MUTE, "s", "middle"),
    ])
    style = """
.ray{stroke-dasharray:460;stroke-dashoffset:460;animation:draw 1.5s ease-out .2s forwards}
.tail{opacity:0;animation:fade 1.2s ease-out 1.5s forwards}
.ring{transform-origin:480px 124px;animation:pulse 3.6s ease-out 1.6s infinite}
.wl{animation:left 1.8s cubic-bezier(.2,.7,.2,1) both}.wr{animation:right 1.8s cubic-bezier(.2,.7,.2,1) both}
@keyframes draw{to{stroke-dashoffset:0}}@keyframes fade{to{opacity:1}}
@keyframes pulse{0%{transform:scale(1);opacity:.9}70%,100%{transform:scale(3.2);opacity:0}}
@keyframes left{from{transform:translateX(-26px)}to{transform:translateX(-4px)}}
@keyframes right{from{transform:translateX(26px)}to{transform:translateX(4px)}}
"""
    return svg(h, "\n".join([grads, stars, rays, points, mark, words]),
               "Parallax: two models view one change from two positions; where their lines cross is the evidence.", style)


# -------------------------------------------------------------------- flow

def flow() -> str:
    h = 462
    gutter, colw, bw, bh = 104, 105, 94, 46
    ya, yc, yb = 112, 206, 300                              # box tops: builder, conductor, challenger
    spine = yc + bh / 2
    cols = ["open", "sealed readings", "reveal", "settle", "contract", "braid", "crossing", "land"]

    def cx(i):
        return gutter + i * colw + colw / 2

    parts = [ARROW,
             text(28, 44, "One task, start to finish", 20, TEXT, weight=600),
             text(28, 66, "The conductor is plain Python. It holds no model, does all the git work and runs every check.", 13, MUTE),
             text(28, ya + 28, "builder", 13, SOFT), text(28, spine + 4, "conductor", 13, SOFT),
             text(28, yb + 28, "challenger", 13, SOFT),
             line(gutter, spine, cx(7) - bw / 2, spine, LINE, 1.6)]
    for i, name in enumerate(cols):
        parts.append(text(cx(i), 96, name, 12.5, MUTE, anchor="middle"))

    def conductor(i, lines, stroke=LINE):
        parts.append(label_box(cx(i) - bw / 2, yc, bw, bh, lines, stroke))

    def seats(i, top, bottom):
        parts.append(line(cx(i), ya + bh, cx(i), yb, LINE, 1.4))
        parts.append(f'<circle cx="{cx(i)}" cy="{spine}" r="3.5" fill="{MUTE}"/>')
        parts.append(label_box(cx(i) - bw / 2, ya, bw, bh, top, WARM))
        parts.append(label_box(cx(i) - bw / 2, yb, bw, bh, bottom, COOL))

    conductor(0, ["read task,", "assign roles"])
    seats(1, ["its reading,", "alone"], ["its reading,", "alone"])
    seats(2, ["reviews the", "other reading"], ["reviews the", "other reading"])
    conductor(3, ["settlement"])
    conductor(4, ["contract", "frozen + hashed"])
    seats(5, ["the change", "+ mutants"], ["probes, from", "the contract"])
    conductor(6, ["probes x change", "probes x mutants"])
    conductor(7, ["main moves,", "with a receipt"], TEXT)

    # the human, only at the settlement and only on a real split
    parts.append(label_box(cx(3) - bw / 2, ya, bw, bh, ["you: a card,", "only on a split"], TEXT, TEXT, "4 3"))
    parts.append(line(cx(3), ya + bh, cx(3), yc, TEXT, 1.2, "4 3"))
    # the blind
    parts.append(text(cx(1.5), yb + bh + 22, "hashes sealed before either is shown", 11.5, MUTE, anchor="middle"))
    parts.append(text(cx(5), yb + bh + 22, "neither sees the other's files", 11.5, MUTE, anchor="middle"))
    # the repair loop
    y = yb + bh + 52
    parts.append(f'<path d="M{cx(6)} {yc + bh} V{y} H{cx(5)} V{yb + bh + 30}" fill="none" stroke="{MUTE}" '
                 f'stroke-width="1.2" stroke-dasharray="4 3" marker-end="url(#a)"/>')
    parts.append(text(cx(5.5), y + 20, "a failing probe or a surviving mutant goes back as evidence:", 11.5, MUTE, anchor="middle"))
    parts.append(text(cx(5.5), y + 35, "each seat concedes and repairs, or contests. At most two rounds.", 11.5, MUTE, anchor="middle"))
    parts.append(text(28, y + 4, "Roles swap every task.", 12.5, SOFT))
    parts.append(text(28, y + 21, "Seats never message each other.", 12.5, SOFT))
    return svg(h, "\n".join(parts), "The life of one task: open, sealed readings, reveal, settlement, contract, "
                                    "braid, crossing, landing with a receipt.")


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
    top, step, left = 64, 21, 30
    h = top + step * len(REPLAY) + 22
    fills = {"cmd": TEXT, "out": SOFT, "hot": TEXT, "card": TEXT, "cool": COOL, "warm": WARM}
    total = 30.0                                            # seconds per loop
    parts = [f'<rect x="0.5" y="0.5" width="{W - 1}" height="{h - 1}" rx="14" fill="none" stroke="{LINE}"/>',
             line(0, 40, W, 40, LINE, 1),
             *(f'<circle cx="{24 + 18 * i}" cy="20" r="5" fill="{LINE}"/>' for i in range(3)),
             text(W / 2, 25, "the stub demo: no tokens spent", 12.5, MUTE, anchor="middle")]
    frames, at = [], 0.6
    for i, (kind, value) in enumerate(REPLAY):
        if kind == "gap":
            at += 0.5
            continue
        y = top + step * i
        weight = 600 if kind in ("cmd", "hot") else 400
        shown = f'<tspan fill="{MUTE}">$ </tspan>{escape(value)}' if kind == "cmd" else escape(value)
        parts.append(f'<text class="m l{i}" x="{left}" y="{y}" font-size="13.5" fill="{fills[kind]}" '
                     f'font-weight="{weight}" xml:space="preserve">{shown}</text>')
        start = at / total * 100
        frames.append(f'.l{i}{{animation:k{i} {total}s linear infinite}}'
                      f'@keyframes k{i}{{0%,{start:.2f}%{{opacity:0}}{start + 0.6:.2f}%,96%{{opacity:1}}100%{{opacity:0}}}}')
        at += 1.1 if kind == "cmd" else 0.55
    return svg(h, "\n".join(parts), "Terminal replay of the stub demo: the seats disagree about lo > hi, "
                                    "a ruling card is printed, the human rules, the task lands.", "\n".join(frames))


# ----------------------------------------------------------------- receipt

def receipt() -> str:
    h = 318
    x, y, w = 28, 76, 548
    rows = [("Parallax-Task", "clamp-001", TEXT),
            ("Parallax-Contract", "sha256:c317c9e49ac1...6a93fe083", SOFT),
            ("Built-by", "codex gpt-6.2-astra/xhigh", COOL),
            ("Challenged-by", "claude fable/high", WARM),
            ("Checks", "84 probes passed, 3 of 3 mutants caught", TEXT),
            ("Verdict", "consensus", TEXT)]
    parts = [text(28, 44, "Every commit on main carries its receipt", 20, TEXT, weight=600),
             box(x, y, w, 214),
             text(x + 20, y + 30, "293c8db", 13, MUTE, "m"),
             text(x + 92, y + 30, "clamp-001: Add clamp(x, lo, hi) to clamplib", 13, TEXT, "m", weight=600),
             line(x, y + 46, x + w, y + 46, LINE, 1)]
    for i, (key, value, color) in enumerate(rows):
        yy = y + 74 + i * 24
        parts.append(text(x + 20, yy, key + ":", 13, MUTE, "m"))
        parts.append(text(x + 180, yy, value, 13, color, "m", weight=600 if key == "Verdict" else 400))
    vx = x + w + 30
    parts.append(text(vx, y + 14, "The verdict says how it got there", 13.5, SOFT, weight=600))
    for i, (name, meaning) in enumerate([("consensus", "clean at the first crossing"),
                                         ("resolved", "the seats settled a dispute"),
                                         ("ruled", "a human ruling was needed"),
                                         ("limited", "accepted with a stated limitation"),
                                         ("solo", "a chore, built by one seat")]):
        yy = y + 44 + i * 37
        parts.append(text(vx, yy, name, 13, TEXT, "m", weight=600))
        parts.append(text(vx, yy + 16, meaning, 12, MUTE))
    parts.append(text(28, h - 10, "The receipt of the first real run with the settlement, 2026-11-23. "
                                  "Hash shortened to fit.", 11.5, MUTE))
    return svg(h + 8, "\n".join(parts), "A landing commit's receipt: task, contract hash, builder, challenger, "
                                        "checks and verdict.")


# ------------------------------------------------------------------ routes

def routes() -> str:
    rows = [("nothing in dispute", "the contract freezes", "no card", MUTE),
            ("one objection", "both answers, both reasons, the case that splits them", "one card", TEXT),
            ("several, or two provisions conflict", "one more exchange: the builder proposes one account,",
             "a card only where each", TEXT),
            ("a seat refuses the proposal", "both agree what a ruling would have to replace", "one card: replace or drop", TEXT)]
    second = {2: ("the challenger reviews exactly that", "holds a different answer")}
    h = 96 + 74 * len(rows) + 40
    ox, oy = 92, 96 + 74 * (len(rows) - 1) / 2 + 14
    parts = [ARROW, text(28, 44, "How a disagreement reaches you", 20, TEXT, weight=600),
             text(28, 66, "After the reveals, how much the seats disagree decides the route.", 13, MUTE),
             f'<circle cx="{ox}" cy="{oy}" r="5" fill="{TEXT}"/>',
             text(ox, oy + 24, "reveals", 12.5, MUTE, anchor="middle")]
    for i, (when, what, result, color) in enumerate(rows):
        y = 96 + 74 * i + 14
        parts.append(f'<path d="M{ox} {oy} C{ox + 70} {oy} {ox + 50} {y} {ox + 120} {y}" fill="none" stroke="{LINE}" stroke-width="1.5"/>')
        parts.append(text(ox + 132, y - 4, when, 13.5, TEXT, weight=600))
        parts.append(text(ox + 132, y + 14, what, 12, MUTE))
        parts.append(line(ox + 132 + 420, y, 706, y, LINE, 1.4, extra='marker-end="url(#a)"'))
        parts.append(text(718, y + 5 if i not in second else y - 4, result, 13.5, color, weight=600))
        if i in second:
            parts.append(text(ox + 132, y + 29, second[i][0], 12, MUTE))
            parts.append(text(718, y + 14, second[i][1], 13.5, color, weight=600))
    parts.append(text(28, h - 16, "If the seats cannot agree on what a ruling would replace, the task is blocked "
                                  "and status says why. Nothing is built until every card is ruled.", 12, MUTE))
    return svg(h, "\n".join(parts), "Four routes from the reveals: no dispute, one objection, several objections "
                                    "or a conflict, and a refused proposal.")


# ------------------------------------------------------------------- blind

def blind() -> str:
    h = 372
    parts = [ARROW, text(28, 44, "How the blind is kept", 20, TEXT, weight=600),
             text(28, 66, "Enforced where each CLI can enforce it, audited everywhere. Seats are treated as "
                          "fallible, not hostile.", 13, MUTE)]
    # your project
    parts.append(label_box(28, 150, 168, 78, ["your project", "main + .parallax/ledger"], TEXT, TEXT, size=12.5))
    parts.append(text(112, 250, "nothing a seat writes", 11.5, MUTE, anchor="middle"))
    parts.append(text(112, 265, "enters it until the task lands", 11.5, MUTE, anchor="middle"))
    # conductor
    parts.append(label_box(262, 150, 150, 78, ["conductor", "git, checks, audit"], LINE, TEXT, size=12.5))
    parts.append(line(196, 189, 262, 189, MUTE, 1.3, extra='marker-end="url(#a)"'))
    # state folder
    sx, sy, sw, sh = 478, 92, 454, 226
    parts.append(box(sx, sy, sw, sh, MUTE, "none", "5 4"))
    parts.append(text(sx + 16, sy + 22, "state folder  ~/.parallax/<project key>/<task>", 12, SOFT, "m"))
    parts.append(text(sx + 16, sy + 38, "private to your account, SYSTEM and Administrators", 11.5, MUTE))
    parts.append(label_box(sx + 16, sy + 54, 200, 62, ["claude's clone", "file tools only, no shell"], WARM, size=12))
    parts.append(label_box(sx + 238, sy + 54, 200, 62, ["codex's clone", "workspace-write sandbox"], COOL, size=12))
    parts.append(line(sx + 227, sy + 50, sx + 227, sy + 120, TEXT, 1.6, "2 4"))
    parts.append(label_box(sx + 16, sy + 140, 422, 62, ["crossing, mutants, artifacts",
                                                        "the conductor's alone: both seats' work meets here"], LINE, size=12))
    parts.append(line(412, 175, sx, 175, MUTE, 1.3, extra='marker-end="url(#a)"'))
    parts.append(line(sx, 203, 412, 203, MUTE, 1.3, extra='marker-end="url(#a)"'))
    parts.append(text(445, 168, "briefs", 11, MUTE, anchor="middle"))
    parts.append(text(445, 218, "events", 11, MUTE, anchor="middle"))
    parts.append(text(28, 318, "Seal: readings and attempts are hashed into the ledger before the reveal.", 12, SOFT))
    parts.append(text(28, 337, "Audit: each event stream is scanned for the other seat's paths. Best effort.", 12, SOFT))
    parts.append(text(28, 356, "Voiding: a hit discards the attempt, its session and its clone. The rerun starts "
                               "from the contract alone.", 12, SOFT))
    return svg(h, "\n".join(parts), "Each seat works in its own clone inside a private state folder; the "
                                    "conductor alone combines their work.")


# ---------------------------------------------------------------- evidence

def evidence() -> str:
    h = 336
    runs = [("17 November", "before the settlement step", COOL, WARM, "codex builds, claude challenges", 4,
             "four rulings", "90 probes pass, 3 of 3 mutants caught", "ruled"),
            ("23 November", "the same task, after it", COOL, WARM, "codex builds, claude challenges", 0,
             "nothing asked", "84 probes pass, 3 of 3 mutants caught", "consensus"),
            ("23 November", "roles swapped, a task that contradicts itself", WARM, COOL, "claude builds, codex challenges", 1,
             "one ruling", "108 probes pass, 3 of 3 mutants caught", "ruled")]
    pw, gap, top = 288, 20, 84
    parts = [text(28, 44, "Three real runs of one small task", 20, TEXT, weight=600),
             text(28, 66, "Real Claude Code and Codex, one Windows 11 machine, 2026. Not a benchmark: what happened.", 13, MUTE)]
    for i, (date, what, builder, challenger, roles, cards, asked, checks, verdict) in enumerate(runs):
        x = 28 + i * (pw + gap)
        parts.append(box(x, top, pw, 226))
        parts.append(text(x + 18, top + 28, date, 14, TEXT, weight=600))
        parts.append(text(x + 18, top + 47, what, 12, MUTE))
        parts.append(f'<circle cx="{x + 23}" cy="{top + 70}" r="4.5" fill="{builder}"/>'
                     f'<circle cx="{x + 35}" cy="{top + 70}" r="4.5" fill="{challenger}"/>')
        parts.append(text(x + 48, top + 74, roles, 12, SOFT))
        parts.append(text(x + 18, top + 104, "asked of the human", 11.5, MUTE))
        for c in range(max(cards, 1)):
            cxp = x + 18 + c * 44
            if cards:
                parts.append(f'<rect x="{cxp}" y="{top + 114}" width="36" height="46" rx="5" fill="{INK}" stroke="{TEXT}" stroke-width="1.3"/>'
                             f'<line x1="{cxp + 8}" y1="{top + 128}" x2="{cxp + 28}" y2="{top + 128}" stroke="{COOL}" stroke-width="2"/>'
                             f'<line x1="{cxp + 8}" y1="{top + 138}" x2="{cxp + 28}" y2="{top + 138}" stroke="{WARM}" stroke-width="2"/>'
                             f'<line x1="{cxp + 8}" y1="{top + 148}" x2="{cxp + 20}" y2="{top + 148}" stroke="{MUTE}" stroke-width="2"/>')
            else:
                parts.append(f'<rect x="{cxp}" y="{top + 114}" width="36" height="46" rx="5" fill="none" stroke="{LINE}" stroke-width="1.3" stroke-dasharray="4 3"/>')
        parts.append(text(x + 18 + max(cards, 1) * 44 + 6, top + 142, asked, 14, TEXT, weight=600))
        parts.append(line(x + 18, top + 176, x + pw - 18, top + 176, LINE, 1))
        parts.append(text(x + 18, top + 197, checks, 12.5, SOFT))
        parts.append(text(x + 18, top + 215, "Verdict: " + verdict, 12.5, TEXT, "m"))
    return svg(h, chr(10).join(parts), "Three real runs: four rulings before the settlement step, none after it on the "
                                    "same task, and one ruling on a task written to contradict itself. Every run "
                                    "landed with 3 of 3 mutants caught.")


FIGURES = {"banner": banner, "evidence": evidence, "flow": flow, "terminal": terminal, "receipt": receipt, "routes": routes, "blind": blind}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, build in FIGURES.items():
        (OUT / f"{name}.svg").write_text(build(), encoding="utf-8", newline="\n")
        print(f"wrote docs/assets/{name}.svg")


if __name__ == "__main__":
    main()
