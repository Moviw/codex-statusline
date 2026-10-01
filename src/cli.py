import argparse
import json
import os
import shutil
import sys
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
        prog="cxbar" if Path(sys.argv[0]).name == "cxbar" else "codex-statusline",
        description="A status bar for Codex CLI: context, 5h/weekly quota, and tokens. "
        "Run `codex` as usual once installed.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="action", required=True, metavar="<command>", title="commands")
    commands = {
        "install": "hook the status bar into `codex` for your shells",
        "uninstall": "remove everything install added",
        "config": "choose what the bar shows, interactively",
        "update": "upgrade to the latest release",
        "doctor": "check Codex, tmux, and Python versions",
    }
    parsers = {
        name: sub.add_parser(name, help=text, description=text) for name, text in commands.items()
    }
    for name in ("install", "uninstall"):
        s = parsers[name]
        s.add_argument(
            "--shell",
            choices=["auto", "bash", "zsh", "fish", "both", "all"],
            default="auto",
            help="default: every supported shell found on PATH",
        )
        s.add_argument("--home", default=str(Path.home()), help=argparse.SUPPRESS)  # tests
        s.add_argument("--yes", action="store_true", help="apply without asking")
        s.add_argument("--diff", action="store_true", help="show the exact file changes")
        s.add_argument("--dry-run", action="store_true", help="show the plan, change nothing")
    ns = parser.parse_args(args)
    try:
        if ns.action in ("install", "uninstall"):
            from .manage import installation

            return installation(ns, ns.action == "uninstall")
        if ns.action == "config":
            from .configure import configure

            return configure()
        if ns.action == "update":
            from .update import update

            return update()
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
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print(f"codex-statusline: {error}", file=sys.stderr)
        return 1
