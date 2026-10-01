"""Diff-first installation; remove only exact owned additions on uninstall."""

import difflib
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
import tomllib
from pathlib import Path

from .hook import atomic_json
from .launcher import ENTRY

BEGIN = "# >>> codex-statusline >>>"
END = "# <<< codex-statusline <<<"
STATUS_MESSAGE = "codex-statusline binding"


def detected_shell():
    # $SHELL can remain zsh even when Ghostty's configured command is fish.
    try:
        proc = subprocess.run(
            ["ps", "-p", str(os.getppid()), "-o", "comm="],
            capture_output=True,
            text=True,
            timeout=1,
        )
        name = Path(proc.stdout.strip()).name.lstrip("-")
        if name in ("fish", "zsh", "bash"):
            return name
    except (OSError, subprocess.TimeoutExpired):
        pass
    name = Path(os.environ.get("SHELL", "/bin/zsh")).name
    return name if name in ("fish", "zsh", "bash") else "zsh"


def available_shells():
    """Install for every supported shell available on this machine."""
    return [name for name in ("bash", "zsh", "fish") if shutil.which(name)]


def base_command():
    # Installed via uv/pipx: the tool's bin shim survives upgrades; site-packages paths do not.
    invoked = Path(sys.argv[0])
    tool = (
        str(invoked)
        if invoked.name == "codex-statusline" and invoked.is_file()
        else shutil.which("codex-statusline")
    )
    if tool and "site-packages" in ENTRY.parts:
        return [os.path.abspath(tool)]
    return [sys.executable, str(ENTRY)]


def shell_block(shell="zsh"):
    prefix = (
        ["env", "CODEX_STATUSLINE_CODEX=" + os.environ["CODEX_STATUSLINE_CODEX"]]
        if os.environ.get("CODEX_STATUSLINE_CODEX")
        else []
    )
    if shell == "fish":

        def quote(value):
            return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"

        command = " ".join(quote(v) for v in [*prefix, *base_command()])
        return (
            "\n" + BEGIN + "\nif status is-interactive\n"
            '    function codex --description "Official Codex with local statusline"\n'
            "        command " + command + " launch $argv\n    end\n"
            "    function codex-statusline\n"
            "        command " + command + " $argv\n    end\nend\n" + END + "\n"
        )
    command = shlex.join([*prefix, *base_command()])
    return (
        "\n"
        + BEGIN
        + "\n"
        + "codex() {\n  "
        + command
        + ' launch "$@"\n}\n'
        + "codex-statusline() {\n  "
        + command
        + ' "$@"\n}\n'
        + END
        + "\n"
    )


def hook_group():
    return {
        "hooks": [
            {
                "type": "command",
                "command": shlex.join([*base_command(), "hook"]),
                "timeout": 2,
                "statusMessage": STATUS_MESSAGE,
            }
        ]
    }


def paths(home, shell):
    home = Path(home).expanduser().resolve()
    codex_home = Path(os.environ.get("CODEX_HOME", str(home / ".codex"))).expanduser().resolve()
    selected = (
        available_shells()
        if shell == "auto"
        else (
            ["bash", "zsh", "fish"]
            if shell == "all"
            else ["bash", "zsh"]
            if shell == "both"
            else [shell]
        )
    )
    if not selected:
        raise ValueError("No supported shell found on PATH (Bash, Zsh, Fish).")
    shells = []
    if "zsh" in selected:
        shells.append(Path(os.environ.get("ZDOTDIR", str(home))).expanduser() / ".zshrc")
    if "bash" in selected:
        shells.append(home / ".bashrc")
        shells.append(
            next(
                (
                    home / n
                    for n in (".bash_profile", ".bash_login", ".profile")
                    if (home / n).exists()
                ),
                home / ".bash_profile",
            )
        )
    if "fish" in selected:
        config = Path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config"))).expanduser()
        shells.append(config / "fish" / "conf.d" / "codex-statusline.fish")
    return (
        codex_home,
        list(dict.fromkeys(shells)),
        home / ".local" / "share" / "codex-statusline" / "install.json",
    )


def text(path):
    return path.read_text() if path.exists() else ""


def modify_hook(raw, group, add):
    # Decode before modifying: never discard malformed or unrelated configuration.
    obj = json.loads(raw or "{}")
    if not isinstance(obj, dict) or not isinstance(obj.get("hooks", {}), dict):
        raise ValueError("hooks.json must be an object with an object hooks field")
    hooks = obj.setdefault("hooks", {})
    events = hooks.get("SessionStart", [])
    if not isinstance(events, list):
        raise ValueError("hooks.SessionStart must be an array")
    if add:
        if group in events:
            return raw
        hooks["SessionStart"] = events + [group]
    else:
        if group not in events:
            return raw
        hooks["SessionStart"] = [entry for entry in events if entry != group]
    return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


def summary(changed, home):
    """One line per file: what is added or removed, in words rather than a diff."""
    lines = ["codex-statusline will:"]
    for p, old, new in changed:
        what = "the SessionStart hook" if p.name == "hooks.json" else "the codex shell function"
        if p.name == "hooks.json":  # JSON is re-serialized, so compare our marker instead
            had, has = (STATUS_MESSAGE in t for t in (old, new))
            sign, verb = (
                ("+", "add") if has and not had else ("-", "remove") if had else ("~", "update")
            )
        elif old in new:
            sign, verb = "+", "add"
        elif new in old:
            sign, verb = "-", "remove"
        else:
            sign, verb = "~", "update"
        lines.append(f"  {sign} {tilde(p, home):<44} {verb} {what}")
    return "\n".join(lines)


def tilde(p, home):
    try:
        return "~/" + str(Path(p).relative_to(home))
    except ValueError:
        return str(p)


def installation(args, uninstall=False):
    chome, shells, manifest_path = paths(args.home, args.shell)
    previous = json.loads(text(manifest_path) or "{}")
    if uninstall and not previous:
        print("Nothing installed by codex-statusline.")
        return 0
    pending = {}  # path -> new text; several steps may edit the same file

    def current(p):
        return pending.get(p, text(p))

    def remove_previous():
        # Manifest defines owned paths; never use current shell choice to guess.
        expected_home, allowed_shells, _ = paths(args.home, "all")
        if previous.get("hooks_path") != str(expected_home / "hooks.json") or any(
            Path(i["path"]) not in allowed_shells
            or not i["block"].startswith("\n" + BEGIN + "\n")
            or not i["block"].endswith(END + "\n")
            for i in previous.get("shells", [])
        ):
            raise ValueError("Manifest paths/blocks do not match this home; refusing to remove it.")
        php = Path(previous["hooks_path"])
        pending[php] = modify_hook(current(php), previous["hook_group"], False)
        for item in previous["shells"]:
            p = Path(item["path"])
            old = current(p)
            if item["block"] not in old and BEGIN in old:
                raise ValueError(f"Owned shell block was edited; remove it manually: {p}")
            pending[p] = old.replace(item["block"], "", 1)

    migrating = False
    if uninstall:
        group, hp = previous["hook_group"], Path(previous["hooks_path"])
        remove_previous()
    else:
        cfg = tomllib.loads(text(chome / "config.toml"))
        hook_config = cfg.get("hooks", {})
        if any(k not in ("state",) for k in hook_config):
            raise ValueError(
                "Inline hooks detected in config.toml. Automatic mixed-source installation "
                "refused; see docs/architecture.md."
            )
        group = hook_group()
        hp = chome / "hooks.json"
        # An older install from another path (e.g. a git checkout before uv/pipx):
        # swap it out in the same reviewed diff instead of asking for an uninstall first.
        migrating = bool(previous) and (
            previous.get("hook_group") != group or previous.get("hooks_path") != str(hp)
        )
        if migrating:
            print("Replacing a previous codex-statusline installation from another path.")
            remove_previous()
        pending[hp] = modify_hook(current(hp), group, True)
        for p in shells:
            block = shell_block("fish" if p.suffix == ".fish" else "zsh")
            old = current(p)
            if BEGIN in old and block not in old:
                raise ValueError(
                    f"A different/edited codex-statusline block exists in {p}; "
                    "uninstall that version first."
                )
            pending[p] = old if block in old else old + block
        allowed = paths(args.home, "all")[1]
        if any(Path(x["path"]) not in allowed for x in previous.get("shells", [])):
            raise ValueError("Existing manifest contains unexpected shell paths.")
    changes = [(p, text(p), new) for p, new in pending.items()]
    changed = [(p, old, new) for p, old, new in changes if old != new]
    if changed:
        print(summary(changed, Path(args.home).expanduser()))
    if changed and (getattr(args, "diff", False) or args.dry_run):
        for p, old, new in changed:
            diff = difflib.unified_diff(
                old.splitlines(True), new.splitlines(True), str(p), str(p), n=0
            )
            print("".join(diff), end="")
    if args.dry_run:
        print("Dry run: no files written.")
        return 0
    if not changed and not uninstall:
        if not previous:
            raise ValueError(
                "Matching configuration exists without ownership manifest; "
                "refusing to claim ownership."
            )
        print("Already installed; no configuration changes.")
        return 0
    if not args.yes:
        hint = "" if getattr(args, "diff", False) else "  (--diff shows the exact changes)"
        if not sys.stdin.isatty() or input(f"Apply?{hint} [Y/n] ").strip().lower() not in (
            "",
            "y",
            "yes",
        ):
            print("No files changed.")
            return 0
    # Refuse symlinks for edited files. User must explicitly manage those targets.
    for p, old, _new in changed:
        if p.is_symlink():
            raise ValueError(f"Refusing to replace symlink: {p}")
        if text(p) != old:
            raise ValueError(f"Configuration changed during confirmation: {p}")
    manifest_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = str(time.time_ns())
    backup = manifest_path.parent / ("changes-" + stamp)
    backup.mkdir(mode=0o700)
    applied = []
    try:
        for i, (p, old, new) in enumerate(changed):
            (backup / f"{i}.before").write_text(old)
            p.parent.mkdir(parents=True, exist_ok=True)
            mode = p.stat().st_mode & 0o777 if p.exists() else 0o600
            existed = p.exists()
            temp = p.with_name(p.name + ".csl-" + stamp)
            try:
                temp.write_text(new)
                temp.chmod(mode)
                os.replace(temp, p)
            finally:
                temp.unlink(missing_ok=True)
            applied.append((p, old, existed))
        (backup / "paths.json").write_text(json.dumps([str(p) for p, _, _ in changed]))
        if uninstall:
            manifest_path.unlink(missing_ok=True)
        else:
            kept = [] if migrating else previous.get("shells", [])
            owned = {item["path"]: item for item in kept}
            for p in shells:
                owned[str(p)] = {
                    "path": str(p),
                    "block": shell_block("fish" if p.suffix == ".fish" else "zsh"),
                }
            atomic_json(
                manifest_path,
                {
                    "hook_group": group,
                    "hooks_path": str(hp),
                    "shells": list(owned.values()),
                },
            )
    except Exception:
        for p, old, existed in reversed(applied):
            if existed:
                p.write_text(old)
            else:
                p.unlink(missing_ok=True)
        raise
    print(
        "Uninstalled. Open a new terminal to finish."
        if uninstall
        else "Installed. Open a new terminal and run codex; trust the "
        f"'{STATUS_MESSAGE}' hook when Codex asks."
    )
    print(f"Backup: {tilde(backup, Path(args.home).expanduser())}")
    return 0
