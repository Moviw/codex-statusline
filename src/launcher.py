"""One isolated tmux server per interactive launch. No PTY input interception."""

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

from .hook import atomic_json

ENTRY = Path(__file__).resolve().parent / "entry.py"
TITLE = 'tui.terminal_title=["model","context-used","thread-id"]'
NONINTERACTIVE = {
    "exec",
    "e",
    "review",
    "login",
    "logout",
    "mcp",
    "mcp-server",
    "app",
    "app-server",
    "completion",
    "sandbox",
    "debug",
    "apply",
    "a",
    "cloud",
    "cloud-tasks",
    "features",
    "archive",
    "help",
    "update",
    "migrate-rollouts",
}
VALUE_FLAGS = {
    "-c",
    "--config",
    "-m",
    "--model",
    "-p",
    "--profile",
    "-s",
    "--sandbox",
    "-a",
    "--ask-for-approval",
    "-C",
    "--cd",
    "-i",
    "--image",
    "--add-dir",
    "--enable",
    "--disable",
}


def official():
    override = os.environ.get("CODEX_STATUSLINE_CODEX")
    path = override or shutil.which("codex")
    if not path or not Path(path).is_file() or not os.access(path, os.X_OK):
        raise RuntimeError("Official codex executable not found on PATH.")
    if Path(path).resolve() == ENTRY.resolve():
        raise RuntimeError("Official executable resolves to this wrapper; refusing recursion.")
    return os.path.abspath(path)  # Keep upgrade-managed symlinks, resolve again every launch.


def interactive(args):
    if not all(os.isatty(fd) for fd in (0, 1, 2)) or os.environ.get("TERM") in (
        "dumb",
        "",
    ):
        return False
    skip = False
    for arg in args:
        if skip:
            skip = False
            continue
        if arg in ("-h", "--help", "-V", "--version", "--remote") or arg.startswith("--remote="):
            return False
        if arg in VALUE_FLAGS:
            skip = True
            continue
        if arg == "--":
            break
        if arg.startswith("-"):
            continue
        return arg not in NONINTERACTIVE
    return True


def version(path):
    p = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=5)
    match = re.search(r"codex-cli (\d+)\.(\d+)\.(\d+)", p.stdout)
    return tuple(map(int, match.groups())) if match else (0, 0, 0)


def raw(args):
    os.execv(official(), [official(), *args])


def child(directory):
    root = Path(directory)
    config = json.loads((root / "launch.json").read_text())
    atomic_json(root / "started.json", {"started": True})
    env = dict(
        os.environ,
        CODEX_STATUSLINE_STATE=str(root),
        CODEX_STATUSLINE_LAUNCH=config["launch_id"],
    )
    try:
        proc = subprocess.Popen(config["argv"], env=env)
        # Codex owns terminal input. A late Ctrl-C after it restores canonical
        # mode must not kill this supervisor before it records the exit code.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        code = proc.wait()
        if code < 0:
            code = 128 - code
    except OSError as error:
        print(f"codex-statusline: cannot start official Codex: {error}", file=sys.stderr)
        code = 127
    atomic_json(root / "exit.json", {"code": code})
    return code


def binding_for(bindings, hint, launch_id):
    # A title is an invalidation guard, not a filesystem lookup. Bindings were
    # supplied by trusted hooks for this launch, each with the full session UUID.
    if not isinstance(hint, str) or not re.fullmatch(r"[0-9a-f-]{29}\.\.\.|[0-9a-f-]{36}", hint):
        return None
    prefix = hint.removesuffix("...")
    candidates = [
        b
        for sid, b in bindings.items()
        if sid.startswith(prefix) and b.get("launch_id") == launch_id
    ]
    return candidates[0] if len(candidates) == 1 else None


def placeholder(width=80):
    """Use the normal layout before telemetry arrives or while it is unavailable."""
    from .data import newest_quotas, sessions_dir
    from .render import load_config, render

    try:
        width = max(1, int(width))
    except (TypeError, ValueError):
        width = 80
    cfg = load_config()
    # Quota is account-wide, so even the very first frame can show it.
    state = {"quotas": newest_quotas(sessions_dir(), {})}
    return render(
        state, width, theme=cfg["theme"], ascii_only=cfg["ascii"], segments=cfg["segments"]
    )


def launch(args):
    binary = official()
    if not interactive(args):
        os.execv(binary, [binary, *args])
    tmux = shutil.which("tmux")
    try:
        if not tmux:
            raise RuntimeError(
                "tmux is missing; install it yourself (brew install tmux / your package manager)."
            )
        if version(binary) < (0, 159, 0):
            raise RuntimeError("requires Codex >= 0.159.0 for the tested title protocol.")
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(
            f"codex-statusline: {error} Falling back to official Codex.",
            file=sys.stderr,
        )
        os.execv(binary, [binary, *args])
    root = Path(tempfile.mkdtemp(prefix="csl-", dir="/tmp"))
    token = str(uuid.uuid4())
    # A private in-process server ensures SessionStart inherits this launch's
    # environment, rather than a long-lived daemon's earlier environment.
    argv = [binary, "--no-daemon", "-c", TITLE, *args]
    cwd = os.getcwd()
    for i, arg in enumerate(args):
        if arg in ("-C", "--cd") and i + 1 < len(args):
            cwd = os.path.abspath(os.path.expanduser(args[i + 1]))
        elif arg.startswith("--cd="):
            cwd = os.path.abspath(os.path.expanduser(arg.split("=", 1)[1]))
    config = {"launch_id": token, "argv": argv, "cwd": cwd, "launcher_pid": os.getpid()}
    atomic_json(root / "launch.json", config)
    conf = root / "tmux.conf"
    conf.write_text(
        "set -g status on\n"
        "set -g status-position bottom\n"
        "set -g status-interval 0\n"
        "set -g status-left-length 10000\n"
        'set -g status-right ""\n'
        'set -g status-format "#{status-left}"\n'
        'set -g status-left ""\n'
        "set -g allow-rename off\n"
        "set -g set-titles off\n"
        "set -g mouse on\n"
        # Every key belongs to Codex: no prefix (Ctrl-B), no wait after Esc.
        "set -g prefix None\n"
        "unbind C-b\n"
        "set -s escape-time 10\n"
        "set -g history-limit 10000\n"
        "set -g remain-on-exit on\n"
        "set -g exit-empty on\n"
    )
    with conf.open("a") as stream:
        stream.write(
            'set -g status-left "' + placeholder(shutil.get_terminal_size((80, 24)).columns) + '"\n'
        )
    from .render import THEMES, load_config

    with conf.open("a") as stream:
        stream.write(f'set -g status-style "{THEMES[load_config()["theme"]]}"\n')
    base = [tmux, "-S", str(root / "tmux.sock"), "-f", str(conf)]
    env = dict(os.environ)
    env.pop("TMUX", None)
    env.pop("TMUX_PANE", None)
    stop = threading.Event()
    started = False

    def call(*command, timeout=2):
        return subprocess.run(
            [*base, *command], env=env, text=True, capture_output=True, timeout=timeout
        )

    def monitor():
        from .data import LogReader, merge_quotas, newest_quotas, parse_title, sessions_dir
        from .render import load_config, render

        cfg = load_config()
        reader = LogReader()
        latest = {}
        updater = "cxbar" if shutil.which("cxbar") else "codex-statusline"
        if cfg["update_check"]:
            from .update import newer_version

            threading.Thread(
                target=lambda: latest.update(version=newer_version()), daemon=True
            ).start()
        sessions, readers, others, scan_at = sessions_dir(), {}, {}, 0.0
        last_line = None
        while not stop.is_set():
            try:
                if (root / "exit.json").exists():
                    call("kill-server")
                    return
                p = call(
                    "display-message",
                    "-p",
                    "-t",
                    "codex:0.0",
                    "#{pane_title}\n#{client_width}",
                )
                if p.returncode:
                    return
                title, _, width = p.stdout.rstrip("\n").partition("\n")
                state = parse_title(title)
                state["cwd"] = config["cwd"]
                state["quotas"] = {}
                if time.monotonic() - scan_at > 10:
                    others, scan_at = newest_quotas(sessions, readers), time.monotonic()
                try:
                    bindings = json.loads((root / "bindings.json").read_text())
                    bound = binding_for(bindings, state.get("session_hint"), token)
                except (OSError, ValueError, TypeError, AttributeError):
                    bound = None
                if bound:
                    state["cwd"] = bound.get("cwd") or config["cwd"]
                    snapshot = reader.update(bound["transcript_path"])
                    state["quotas"], state["tokens"] = (
                        snapshot.get("quotas", {}),
                        snapshot.get("tokens"),
                    )
                state["quotas"] = merge_quotas(state["quotas"], others)
                state["update"] = latest.get("version")
                state["updater"] = updater
                line = render(
                    state,
                    int(width or 80),
                    theme=cfg["theme"],
                    ascii_only=cfg["ascii"],
                    segments=cfg["segments"],
                    warn_at=cfg["warn_at"],
                    crit_at=cfg["crit_at"],
                )
                if line != last_line:
                    call("set-option", "-t", "codex", "status-left", line)
                    last_line = line
                # Save metadata-only current view for doctor/tests; never pane text.
                atomic_json(root / "view.json", state)
            except Exception as error:
                atomic_json(root / "error.json", {"error": repr(error)[:500]})
                last_line = None
                # Rendering / local log failure never terminates the official process.
                try:
                    call(
                        "set-option",
                        "-t",
                        "codex",
                        "status-left",
                        placeholder(width if "width" in locals() else 80),
                    )
                except Exception:
                    pass
            stop.wait(0.5)

    def interrupted(signum, frame):
        raise SystemExit(128 + signum)

    old_handlers = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGTERM, signal.SIGHUP)}
    try:
        p = call(
            "new-session",
            "-d",
            "-s",
            "codex",
            sys.executable,
            "-c",
            "import time; time.sleep(86400)",
        )
        if p.returncode:
            raise RuntimeError(p.stderr.strip() or "tmux initialization failed")
        # Beyond this boundary a child may exist even if tmux times out.
        started = True
        p = call(
            "respawn-pane",
            "-k",
            "-t",
            "codex:0.0",
            sys.executable,
            str(ENTRY),
            "_child",
            str(root),
        )
        if p.returncode:
            raise RuntimeError(p.stderr.strip() or "tmux child launch failed")
        worker = threading.Thread(target=monitor, daemon=True)
        worker.start()
        attach = subprocess.Popen([*base, "attach-session", "-t", "codex"], env=env)
        attach.wait()
        if (root / "exit.json").exists():
            return json.loads((root / "exit.json").read_text())["code"]
        return attach.returncode
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        # Once creation succeeds or the child marker exists, NEVER start a second Codex.
        print(f"codex-statusline: {error}", file=sys.stderr)
        if not started and not (root / "started.json").exists():
            try:
                call("kill-server")
            except Exception:
                pass
            shutil.rmtree(root, ignore_errors=True)
            os.execv(binary, [binary, *args])
        return 1
    finally:
        stop.set()
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
        try:
            call("kill-server")
        except Exception:
            pass
        if "attach" in locals() and attach.poll() is None:
            try:
                attach.wait(timeout=3)
            except subprocess.TimeoutExpired:
                attach.terminate()
                attach.wait(timeout=3)
        if "worker" in locals():
            worker.join(timeout=3)
        shutil.rmtree(root, ignore_errors=True)
