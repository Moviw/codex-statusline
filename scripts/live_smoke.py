#!/usr/bin/env python3
"""Opt-in real Codex/tmux offline smoke; no real account or model requests.
Creates a private CODEX_HOME, trusts only its own hook through the official UI.
The endpoint 127.0.0.1:9 is deliberately unavailable. No user's hooks/auth read.
"""

import argparse
import fcntl
import hashlib
import json
import os
import pty
import select
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENTRY = REPO / "run.py"
parser = argparse.ArgumentParser()
parser.add_argument("--output", default="/tmp/csl-live-evidence.json")
parser.add_argument("--recording")
parser.add_argument("--shell", choices=["direct", "fish", "bash"], default="direct")
args = parser.parse_args()
events = []


def wait(check, timeout=12):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        try:
            value = check()
            if value:
                return value
        except (OSError, ValueError, KeyError, IndexError):
            pass
        time.sleep(0.15)
    raise AssertionError("timed out: " + str(check))


class Terminal:
    def __init__(self, env, argv=()):
        self.master, slave = pty.openpty()
        self.events = []
        self.start = time.monotonic()
        self.known_roots = set(Path("/tmp").glob("csl-*/launch.json"))
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 160, 0, 0))

        def setup():
            os.setsid()
            fcntl.ioctl(slave, termios.TIOCSCTTY, 0)

        command = (
            ["fish", "-i", "-c", "codex $argv", *argv]
            if args.shell == "fish"
            else ["bash", "--noprofile", "-i", "-c", 'codex "$@"', "csl", *argv]
            if args.shell == "bash"
            else [sys.executable, str(ENTRY), "launch", *argv]
        )
        self.p = subprocess.Popen(
            command,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env=env,
            cwd=env["TEST_PROJECT"],
            preexec_fn=setup,
        )
        os.close(slave)

        def drain():
            while self.p.poll() is None:
                if select.select([self.master], [], [], 0.2)[0]:
                    try:
                        b = os.read(self.master, 65536)
                    except OSError:
                        break
                    if not b:
                        break
                    self.events.append(
                        [
                            round(time.monotonic() - self.start, 3),
                            "o",
                            b.decode("utf8", "replace"),
                        ]
                    )

        self.thread = threading.Thread(target=drain, daemon=True)
        self.thread.start()

        def state():
            for p in Path("/tmp").glob("csl-*/launch.json"):
                config = json.loads(p.read_text())
                if config.get("launcher_pid") == self.p.pid or (
                    args.shell != "direct"
                    and p not in self.known_roots
                    and config.get("cwd") == env["TEST_PROJECT"]
                ):
                    return p.parent

        self.root = wait(state)
        self.socket = str(self.root / "tmux.sock")

    def tmux(self, *a):
        p = subprocess.run(
            ["tmux", "-S", self.socket, *a], capture_output=True, text=True, timeout=3
        )
        if p.returncode:
            raise RuntimeError(p.stderr)
        return p.stdout

    def screen(self):
        return self.tmux("capture-pane", "-p", "-t", "codex:0.0")

    def send(self, text):
        os.write(self.master, text.encode())
        time.sleep(0.3)

    def command(self, text):
        self.send(text)
        self.send("\r")

    def view(self):
        return json.loads((self.root / "view.json").read_text())

    def trust(self):
        def ready():
            screen = self.screen()
            if "Update now" in screen and "esc skip" in screen:
                self.send("\x1b")  # Never install/update the official CLI in a test.
                return False
            return "Hooks need review" in screen or "session_hint" in self.view()

        wait(ready)
        if "Hooks need review" in self.screen():
            self.send("2")
            self.send("\r")
        hint = wait(lambda: self.view().get("session_hint"))
        # Only the one test-owned hook exists in this isolated CODEX_HOME.
        # Linux can open the review list rather than grant trust at startup.
        screen = self.screen()
        if "trust" not in screen.lower() or "hook" not in screen.lower():
            self.command("/hooks")
        wait(lambda: "Lifecycle hooks" in self.screen() or "SessionStart hooks" in self.screen())
        if "needs review" in self.screen() or "review required" in self.screen():
            self.send("t")
        self.send("\x1b")
        self.send("\x1b")
        return hint

    def bindings(self):
        return json.loads((self.root / "bindings.json").read_text())

    def prompt(self):
        self.command("offline binding probe")
        wait(lambda: self.bindings())
        self.send("\x1b")
        time.sleep(0.4)

    def resize(self, width):
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", 32, width, 0, 0))
        os.killpg(self.p.pid, signal.SIGWINCH)
        time.sleep(0.8)

    def close(self, interrupt=False):
        if self.p.poll() is None:
            keys = (
                ("\x1b", "\x03", "\x03", "\x03") if interrupt else ("\x1b", "\x15", "/quit", "\r")
            )
            for key in keys:
                if self.p.poll() is not None:
                    break
                try:
                    self.send(key)
                except OSError:
                    break
            try:
                self.p.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.tmux("kill-server")
                self.p.wait(timeout=5)
        self.thread.join(timeout=2)
        os.close(self.master)
        return self.p.returncode


live = []
try:
    binary = shutil.which("codex")
    before = hashlib.sha256(Path(binary).read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="csl-live-") as d:
        root = Path(d).resolve()
        home = root / "home"
        home.mkdir()
        project = root / "project"
        project.mkdir()
        from sys import path

        path.insert(0, str(REPO))
        from src.manage import hook_group

        (home / "hooks.json").write_text(json.dumps({"hooks": {"SessionStart": [hook_group()]}}))
        (home / "config.toml").write_text(
            'model="offline-probe"\nmodel_provider="probe"\n'
            '[model_providers.probe]\nname="Local offline probe"\n'
            'base_url="http://127.0.0.1:9/v1"\nwire_api="responses"\n'
            "requires_openai_auth=false\n[projects."
            + json.dumps(str(project))
            + ']\ntrust_level="trusted"\n'
        )
        env = dict(
            os.environ,
            CODEX_HOME=str(home),
            HOME=str(root / "user"),
            TERM="xterm-256color",
            TEST_PROJECT=str(project),
        )
        env.pop("TMUX", None)
        env.pop("TMUX_PANE", None)
        if args.shell == "fish":
            from src.manage import shell_block

            env["XDG_CONFIG_HOME"] = str(root / "user/.config")
            fishconf = root / "user/.config/fish/conf.d/codex-statusline.fish"
            fishconf.parent.mkdir(parents=True)
            fishconf.write_text(shell_block("fish"))
        if args.shell == "bash":
            from src.manage import shell_block

            rc = root / "user/.bashrc"
            rc.parent.mkdir(parents=True, exist_ok=True)
            rc.write_text(shell_block("bash"))
        one = Terminal(env)
        live.append(one)
        hint = one.trust()
        assert one.tmux("list-panes").count("\n") == 1
        one.prompt()
        first = next(iter(one.bindings()))
        events.append(
            {
                "check": "startup binding",
                "pass": first.startswith(hint[:-3]),
                "session_id": first,
            }
        )
        one.command("/clear")
        wait(lambda: one.view()["session_hint"] != hint)
        v = one.view()
        assert v["quotas"] == {}
        assert v["context_used"] == 0
        assert first in one.bindings()  # old hook remains, but UI guard invalidates it.
        events.append(
            {
                "check": "clear before next turn",
                "pass": True,
                "context_used": v["context_used"],
                "quotas": v["quotas"],
            }
        )
        one.prompt()
        wait(lambda: len(one.bindings()) == 2)
        two = Terminal(env)
        live.append(two)
        two.trust()
        two.prompt()
        ids1 = set(one.bindings())
        ids2 = set(two.bindings())
        assert ids1.isdisjoint(ids2)
        events.append(
            {
                "check": "two live sessions same directory",
                "pass": True,
                "independent_sockets": one.socket != two.socket,
            }
        )
        for width in (160, 80, 40, 20, 160):
            one.resize(width)
            wait(lambda w=width: "CTX" in one.tmux("show-option", "-v", "status-left") or w < 40)
            status = one.tmux("show-option", "-v", "status-left").strip()
            from src.render import visible_width

            assert visible_width(status) <= width, (width, status)
            events.append({"check": "resize", "width": width, "status": status, "pass": True})
        one.send("\x1b[200~中文粘贴 测试\x1b[201~")
        assert "中文粘贴" in one.screen()
        one.send("\x03")
        events.append({"check": "Chinese bracketed paste (not submitted)", "pass": True})
        code = one.close(interrupt=True)
        assert code in (0, 130), ("unexpected Ctrl-C exit", code)
        assert not any("Traceback" in e[2] for e in one.events)
        events.append(
            {
                "check": "Ctrl-C exit and terminal wrapper cleanup",
                "exit": code,
                "state_removed": not one.root.exists(),
            }
        )
        if args.recording:
            out = Path(args.recording)
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open("w") as f:
                f.write(
                    json.dumps(
                        {
                            "version": 2,
                            "width": 160,
                            "height": 32,
                            "title": "Real Codex 0.159.0 offline smoke; no quota demo data",
                            "env": {"TERM": "xterm-256color"},
                        }
                    )
                    + "\n"
                )
                for e in one.events:
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")
        assert two.close() == 0
        events.append({"check": "/quit graceful exit", "exit": 0, "pass": True})
        for sub in ("resume", "fork"):
            t = Terminal(env, [sub, first])
            live.append(t)
            t.trust()
            t.prompt()
            binding = next(iter(t.bindings()))
            assert (binding == first) if sub == "resume" else (binding != first)
            events.append({"check": sub, "pass": True, "same_id": binding == first})
            t.close()
        terminated = Terminal(env)
        live.append(terminated)
        terminated.trust()
        launcher_pid = json.loads((terminated.root / "launch.json").read_text())["launcher_pid"]
        os.kill(launcher_pid, signal.SIGTERM)
        terminated.p.wait(timeout=8)
        assert terminated.p.returncode == 143 and not terminated.root.exists()
        events.append({"check": "SIGTERM cleanup", "exit": 143, "pass": True})
    after = hashlib.sha256(Path(binary).read_bytes()).hexdigest()
    assert before == after
    events.append({"check": "official binary unchanged", "sha256": after, "pass": True})
    Path(args.output).write_text(
        json.dumps({"status": "PASS", "events": events}, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps({"status": "PASS", "checks": len(events), "output": args.output}))
except Exception as e:
    Path(args.output).write_text(
        json.dumps(
            {
                "status": "FAIL",
                "error": repr(e),
                "terminal_tail": [t.events[-10:] for t in live],
                "screens": [t.screen() for t in live if t.p.poll() is None],
                "diagnostics": [
                    {
                        "title": t.tmux("display-message", "-p", "#{pane_title}"),
                        "error": (t.root / "error.json").read_text()
                        if (t.root / "error.json").exists()
                        else None,
                    }
                    for t in live
                    if t.p.poll() is None
                ],
                "events": events,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    raise
finally:
    for t in live:
        try:
            if t.p.poll() is None:
                t.close()
        except Exception:
            pass
