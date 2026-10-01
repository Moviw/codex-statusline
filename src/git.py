"""Branch and uncommitted line counts for the second line. Fails quietly and quickly."""

import subprocess
from pathlib import Path

MAX_NEW_FILES = 200  # untracked files counted; keeps a stray node_modules from stalling us
MAX_FILE_BYTES = 1 << 20


def _git(cwd, *args: str, timeout: float = 1.5) -> str | None:
    p = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=timeout
    )
    return p.stdout if p.returncode == 0 else None


def _lines(path: Path) -> int:
    """Lines in a new text file; binary or oversized files count as zero."""
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return 0
        data = path.read_bytes()
    except OSError:
        return 0
    if b"\0" in data[:8000]:
        return 0
    return data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)


def git_status(cwd) -> dict | None:
    """{"branch", "added", "removed"} for the repo at cwd, or None outside a repo."""
    try:
        root = _git(cwd, "rev-parse", "--show-toplevel")
        if not root:
            return None
        root = Path(root.strip())
        branch = (_git(root, "symbolic-ref", "--short", "-q", "HEAD") or "").strip()
        if not branch:  # detached HEAD
            branch = (_git(root, "rev-parse", "--short", "HEAD") or "HEAD").strip()
        added = removed = 0
        # Staged and unstaged changes against the last commit (none yet in a new repo).
        for line in (_git(root, "diff", "HEAD", "--numstat", "--no-renames") or "").splitlines():
            plus, minus, _ = line.split("\t", 2)
            if plus != "-":  # binary files show "-"
                added, removed = added + int(plus), removed + int(minus)
        # New files an agent wrote but nobody has added yet; .gitignore is respected.
        untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z") or ""
        for name in [n for n in untracked.split("\0") if n][:MAX_NEW_FILES]:
            added += _lines(root / name)
        return {"branch": branch, "added": added, "removed": removed}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
