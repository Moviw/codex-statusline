import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

from . import __version__


def main():
    args = sys.argv[1:]
    from .launcher import child, launch, official, raw, version

    if args and args[0] in ("launch", "raw"):
        try:
            return (launch if args[0] == "launch" else raw)(args[1:])
        except KeyboardInterrupt:
            return 130
    if args and args[0] == "_child":
        return child(args[1])
    if args and args[0] == "hook":
        from .hook import record

        record()
        return 0
    parser = argparse.ArgumentParser(
        description="Third-party local tmux statusline for the official Codex CLI."
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("install", "uninstall"):
        s = sub.add_parser(name)
        s.add_argument(
            "--shell",
            choices=["auto", "bash", "zsh", "fish", "both", "all"],
            default="auto",
            help="default: all supported shells found on PATH",
        )
        s.add_argument("--home", default=str(Path.home()), help="target home (for isolated tests)")
        s.add_argument(
            "--yes",
            action="store_true",
            help="approve printed diff without interactive prompt",
        )
        s.add_argument("--dry-run", action="store_true")
    sub.add_parser("doctor")
    p = sub.add_parser("preview")
    p.add_argument("--width", type=int, default=120)
    p.add_argument("--theme", choices=["dark", "light"])
    p.add_argument("--ascii", action="store_true")
    p.add_argument("--tmux", action="store_true", help="emit tmux style syntax, not ANSI")
    ns = parser.parse_args(args)
    try:
        if ns.action in ("install", "uninstall"):
            from .manage import installation

            return installation(ns, ns.action == "uninstall")
        if ns.action == "doctor":
            path = official()
            data = {
                "python": sys.version.split()[0],
                "codex": path,
                "codex_version": ".".join(map(str, version(path))),
                "tmux": shutil.which("tmux"),
                "shell": os.environ.get("SHELL"),
                "tested_codex": "0.159.0",
                "credentials_read": False,
            }
            print(json.dumps(data, indent=2))
            return 0 if data["tmux"] and version(path) >= (0, 159, 0) else 1
        if ns.action == "preview":
            from .render import load_config, render

            cfg = load_config()
            now = time.time()
            state = {
                "context_used": 35,
                "tokens": 1_234_567,
                "quotas": {
                    "5h": {"remaining": 78, "reset_at": now + 7200, "observed_at": now},
                    "weekly": {"remaining": 39, "reset_at": now + 172800, "observed_at": now},
                },
            }
            print(
                render(
                    state,
                    ns.width,
                    theme=ns.theme or cfg["theme"],
                    ascii_only=ns.ascii or cfg["ascii"],
                    tmux=ns.tmux,
                    segments=cfg["segments"],
                    warn_at=cfg["warn_at"],
                    crit_at=cfg["crit_at"],
                )
            )
            return 0
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print(f"codex-statusline: {error}", file=sys.stderr)
        return 1
