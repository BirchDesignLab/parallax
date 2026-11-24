"""Fast repository checks for CI and for a local run before a pull request.

    python scripts/ci/check_repo.py

Three checks, standard library only, a few seconds in total:

1. figures: every SVG in docs/assets/ is exactly what scripts/docs/build_assets.py generates.
   A figure edited by hand, or a generator change without a rebuild, fails here.
2. hygiene: no tracked file holds a personal email address or a real home-folder path
   (developer ruling 2026-11-23: write `~` for the home folder).
3. links: every relative link and image path in README.md and docs/*.md points at a file
   that exists.

Exits 1 when any check fails, after printing every problem found.
"""
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# An address is allowed when it cannot belong to a person.
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
EMAIL_OK = re.compile(r"noreply|@example\.(?:invalid|com|org)$", re.IGNORECASE)

# A home-folder path is allowed when the account name is an obvious placeholder.
HOME = re.compile(r"(?:[A-Za-z]:[\\/]+Users[\\/]+|/Users/|/home/)([A-Za-z0-9._-]+)")
HOME_OK = {"me", "you", "x", "user", "name", "first", "runner", "example"}  # "first" is from "First Last"

LINK = re.compile(r"\]\(([^)\s]+)\)|(?:src|href)=\"([^\"]+)\"")


def tracked_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True).stdout
    return [REPO / name for name in out.decode("utf-8").split("\0") if name]


def check_figures() -> list[str]:
    spec = importlib.util.spec_from_file_location("build_assets", REPO / "scripts" / "docs" / "build_assets.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    problems = []
    assets = REPO / "docs" / "assets"
    for name, build in module.FIGURES.items():
        path = assets / f"{name}.svg"
        if not path.exists():
            problems.append(f"docs/assets/{name}.svg is missing; run python scripts/docs/build_assets.py")
        elif path.read_text(encoding="utf-8").replace("\r\n", "\n") != build():
            problems.append(f"docs/assets/{name}.svg differs from the generator; run python scripts/docs/build_assets.py")
    known = {f"{name}.svg" for name in module.FIGURES}
    for path in sorted(assets.glob("*.svg")):
        if path.name not in known:
            problems.append(f"docs/assets/{path.name} is not produced by the generator")
    return problems


def check_hygiene(files: list[Path]) -> list[str]:
    problems = []
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable: nothing to scan
        rel = path.relative_to(REPO).as_posix()
        for number, line in enumerate(lines, 1):
            for match in EMAIL.finditer(line):
                if not EMAIL_OK.search(match.group()):
                    problems.append(f"{rel}:{number}: email address")
            for match in HOME.finditer(line):
                if match.group(1).lower() not in HOME_OK:
                    problems.append(f"{rel}:{number}: home-folder path, write ~ instead")
    return problems


def check_links() -> list[str]:
    problems = []
    for page in [REPO / "README.md", *sorted((REPO / "docs").glob("*.md"))]:
        rel = page.relative_to(REPO).as_posix()
        fenced = False
        for number, line in enumerate(page.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("```"):
                fenced = not fenced
            if fenced:
                continue
            for match in LINK.finditer(line):
                target = match.group(1) or match.group(2)
                if re.match(r"[a-z][a-z0-9+.-]*:", target, re.IGNORECASE) or target.startswith("#"):
                    continue  # another site, or an anchor on this page
                target_path = target.split("#", 1)[0].split("?", 1)[0]
                if not (page.parent / target_path).exists():
                    problems.append(f"{rel}:{number}: link target not found: {target}")
    return problems


def main() -> int:
    checks = {"figures": check_figures(), "hygiene": check_hygiene(tracked_files()), "links": check_links()}
    failed = False
    for name, problems in checks.items():
        print(f"{name}: {'ok' if not problems else f'{len(problems)} problem(s)'}")
        for problem in problems:
            print(f"  {problem}")
        failed = failed or bool(problems)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
