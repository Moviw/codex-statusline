"""Check PyPI for a newer release and upgrade with whatever installed this copy."""

import json
import os
import shutil
import subprocess
import sys
import time
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


CACHE_AGE = 6 * 3600


def cache_path() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "codex-statusline" / "latest.json"


def refresh_cache() -> None:
    latest = latest_version()
    if latest is None:
        return
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps({"checked": time.time(), "latest": latest}))
    os.replace(temp, path)


def cached_newer_version() -> str | None:
    """For commands that run often (Claude's statusLine): never wait on the network.

    Uses the cached answer and, when it is older than CACHE_AGE, refreshes it in a
    detached background process for next time.
    """
    try:
        cached = json.loads(cache_path().read_text())
        latest, checked = cached.get("latest"), float(cached.get("checked", 0))
    except (OSError, ValueError, TypeError, AttributeError):
        latest, checked = None, 0.0
    if time.time() - checked > CACHE_AGE:
        try:
            cache_path().parent.mkdir(parents=True, exist_ok=True)
            # Mark as checked now so concurrent refreshes do not pile up.
            stamp = cache_path().with_suffix(".tmp")
            stamp.write_text(json.dumps({"checked": time.time(), "latest": latest}))
            os.replace(stamp, cache_path())
            subprocess.Popen(
                [sys.executable, str(PACKAGE / "entry.py"), "_refresh-update"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError:
            pass
    return latest if isinstance(latest, str) and is_newer(latest) else None


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


def check(latest=latest_version) -> int:
    """Report without installing. Exit 0: up to date, 1: update available, 2: unknown."""
    found = latest()
    if found is None:
        print(f"codex-statusline {__version__}: could not reach PyPI to check for updates.")
        return 2
    if is_newer(found):
        print(f"codex-statusline {found} is available (you have {__version__}). Run: cxbar update")
        return 1
    print(f"codex-statusline {__version__} is the latest version.")
    return 0


def update() -> int:
    command = upgrade_command()
    print("$ " + " ".join(command), flush=True)  # before the tool's own output
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
