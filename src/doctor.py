"""`cxbar doctor`: one line per check, and the command that fixes each problem."""

import json
import shutil
import subprocess
import tomllib
from pathlib import Path

from . import __version__
from .launcher import official, version
from .manage import STATUS_MESSAGE, hook_group, paths, text, tilde
from .update import is_newer, latest_version


def command_name() -> str:
    return "cxbar" if shutil.which("cxbar") else "codex-statusline"


def checks(home: Path, latest=latest_version) -> list[tuple[bool | None, str, str | None]]:
    """(ok, message, fix): ok is True, False, or None for information only."""
    cmd = command_name()
    out = []
    try:
        found = version(official())
        shown = ".".join(map(str, found))
        out.append((found >= (0, 159, 0), f"Codex CLI {shown}", "upgrade Codex CLI to 0.159.0+"))
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        out.append((False, "Codex CLI not found on PATH", "install Codex CLI"))
    tmux = shutil.which("tmux")
    if tmux:
        tmux_version = subprocess.run([tmux, "-V"], capture_output=True, text=True).stdout.strip()
        out.append((True, tmux_version or "tmux", None))
    else:
        out.append((False, "tmux not found", "brew install tmux  /  sudo apt install tmux"))

    codex_home, _, manifest_path = paths(home, "all")
    try:
        manifest = json.loads(text(manifest_path) or "{}")
    except ValueError:
        manifest = {}
    if not manifest:
        out.append((False, "not hooked into your shell yet", f"{cmd} install"))
        return out + [_update_check(cmd, latest)]

    if manifest.get("hook_group") != hook_group():
        other = manifest["hook_group"]["hooks"][0]["command"].removesuffix(" hook")
        out.append((False, f"codex runs another copy: {other}", f"{cmd} install"))
    else:
        shells = [Path(item["path"]) for item in manifest.get("shells", [])]
        missing = [p for p in shells if item_block(manifest, p) not in text(p)]
        names = ", ".join(tilde(p, home) for p in shells)
        out.append((not missing, f"codex is hooked into {names}", f"{cmd} install"))

    hooks_path = Path(manifest["hooks_path"])
    try:
        groups = json.loads(text(hooks_path) or "{}").get("hooks", {}).get("SessionStart", [])
    except ValueError:
        groups = []
    index = next((i for i, g in enumerate(groups) if g == manifest["hook_group"]), None)
    if index is None:
        out.append((False, f"hook missing from {tilde(hooks_path, home)}", f"{cmd} install"))
    else:
        try:
            state = (
                tomllib.loads(text(codex_home / "config.toml")).get("hooks", {}).get("state", {})
            )
        except tomllib.TOMLDecodeError:
            state = {}
        trusted = "trusted_hash" in state.get(f"{hooks_path}:session_start:{index}:0", {})
        out.append(
            (True, "hook approved in Codex", None)
            if trusted
            else (
                False,
                "hook not approved in Codex yet",
                f"start codex, approve '{STATUS_MESSAGE}'",
            )
        )
    return out + [_update_check(cmd, latest)]


def item_block(manifest: dict, path: Path) -> str:
    return next(i["block"] for i in manifest["shells"] if Path(i["path"]) == path)


def _update_check(cmd: str, latest) -> tuple[bool | None, str, str | None]:
    found = latest()
    if found is None:
        return (None, "could not check for updates (offline?)", None)
    if is_newer(found):
        return (False, f"{found} available", f"{cmd} update")
    return (True, "latest version", None)


def doctor(home: Path | None = None) -> int:
    results = checks(home or Path.home())
    print(f"codex-statusline {__version__}")
    for ok, message, fix in results:
        print(f"  {'✓' if ok else '✗' if ok is False else '·'} {message}")
        if ok is False and fix:
            print(f"      → {fix}")
    return 1 if any(ok is False for ok, _, _ in results) else 0
