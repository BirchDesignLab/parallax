import subprocess, tempfile
from pathlib import Path

def run_git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()

def make_repo(files: dict[str, str] | None = None) -> Path:
    """A git repo on branch main with one commit, under a directory whose name has a space."""
    root = Path(tempfile.mkdtemp(prefix="plx repo ")) / "my project"
    root.mkdir()
    run_git(root, "init", "-b", "main")
    run_git(root, "config", "user.name", "Test Human")
    run_git(root, "config", "user.email", "human@example.invalid")
    run_git(root, "config", "core.autocrlf", "false")
    write(root, {"README.md": "fixture\n", **(files or {})})
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "fixture")
    return root

def write(root: Path, files: dict[str, str | None]) -> None:
    for rel, text in files.items():
        path = root / rel
        if text is None:
            path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")

def commit(repo: Path, files: dict[str, str | None], message: str = "change") -> str:
    write(repo, files)
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-m", message)
    return run_git(repo, "rev-parse", "HEAD")
