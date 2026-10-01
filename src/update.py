"""Check PyPI for a newer release and upgrade with whatever installed this copy."""

import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

from . import __version__

PYPI = "https://pypi.org/pypi/codex-statusline/json"
PACKAGE = Path(__file__).resolve().parent


def _parse(version: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError:
        return ()


def is_newer(latest: str, current: str = __version__) -> bool:
    return bool(_parse(latest)) and _parse(latest) > _parse(current)


def latest_version(timeout: float = 2) -> str | None:
    """Latest release on PyPI; None on any failure. Sends only a plain GET."""
    try:
        request = urllib.request.Request(
            PYPI, headers={"User-Agent": f"codex-statusline/{__version__}"}
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            latest = json.load(response)["info"]["version"]
    except Exception:
        return None
    return latest if isinstance(latest, str) else None


def newer_version(timeout: float = 2) -> str | None:
    """Latest release if newer than this one; None otherwise or on any failure."""
    latest = latest_version(timeout)
    return latest if latest and is_newer(latest) else None


def upgrade_command(prefix: str = sys.prefix, package: Path = PACKAGE) -> list[str]:
    # uv and pipx each leave a marker file in the tool's environment. Install the latest
    # release from PyPI explicitly: `upgrade` keeps the original source, so a tool first
    # installed from a local checkout would otherwise never leave that version.
    if (Path(prefix) / "uv-receipt.toml").exists():
        return ["uv", "tool", "install", "codex-statusline@latest"]
    if (Path(prefix) / "pipx_metadata.json").exists():
        return ["pipx", "install", "--force", "codex-statusline"]
    if (package.parent / ".git").exists():
        return ["git", "-C", str(package.parent), "pull", "--ff-only"]
    return [sys.executable, "-m", "pip", "install", "--upgrade", "codex-statusline"]


def update() -> int:
    command = upgrade_command()
    print("$ " + " ".join(command))
    if not shutil.which(command[0]):
        print(
            f"codex-statusline: {command[0]} not found; run the command above yourself.",
            file=sys.stderr,
        )
        return 1
    code = subprocess.run(command).returncode
    if code == 0:
        print("Updated. Open a new terminal (or restart codex) to use it.")
    return code
