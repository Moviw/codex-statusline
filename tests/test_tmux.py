import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from src.launcher import SPINNER, outer_title
from src.render import render


class OuterTitleTests(unittest.TestCase):
    def test_thread_title_dir_fallback_and_own_spinner_frames(self):
        home = os.path.expanduser("~")
        self.assertEqual(outer_title({"thread_title": "Fix login"}, "/w/app"), "Fix login")
        self.assertEqual(outer_title({}, "/w/app"), "codex · app")
        self.assertEqual(outer_title({"thread_title": None}, home), "codex · ~")
        self.assertEqual(outer_title({}, "/"), "codex · /")
        self.assertEqual(outer_title({"thread_title": "a\x1b]0;x\x07b"}, "/"), "ab")
        frames = {outer_title({"working": True}, "/w/app", i) for i in range(len(SPINNER))}
        self.assertEqual(frames, {f"{c} codex · app" for c in SPINNER})


@unittest.skipUnless(shutil.which("tmux"), "tmux not installed")
class TmuxTests(unittest.TestCase):
    def test_literal_percent_and_no_format_command_execution(self):
        with tempfile.TemporaryDirectory(prefix="csl-tmux-", dir="/tmp") as d:
            root = Path(d)
            base = ["tmux", "-S", str(root / "s"), "-f", "/dev/null"]
            env = dict(os.environ)
            env.pop("TMUX", None)

            def run(*args):
                return subprocess.run(
                    base + list(args),
                    text=True,
                    capture_output=True,
                    env=env,
                    timeout=3,
                )

            try:
                p = run("new-session", "-d", "-s", "test", "sleep", "30")
                self.assertEqual(p.returncode, 0, p.stderr)
                sentinel = root / "never"
                state = {
                    "model": f"#(touch {sentinel}) #[bg=red]",
                    "context_used": 35,
                    "cwd": "/tmp",
                }
                value = render(state, 200)
                self.assertEqual(run("set-option", "status-left", value).returncode, 0)
                self.assertEqual(
                    run("set-option", "status-format[0]", "#{status-left}").returncode,
                    0,
                )
                expanded = run("display-message", "-p", "#{status-left}").stdout
                self.assertIn("35%", expanded)
                time.sleep(0.2)
                self.assertFalse(sentinel.exists())
                self.assertEqual(len(run("list-panes").stdout.splitlines()), 1)
                # The outer title is the literal option value, never a format.
                self.assertEqual(
                    run("set-option", "set-titles-string", "#{@outer_title}").returncode, 0
                )
                self.assertEqual(
                    run("set-option", "@outer_title", f"#(touch {sentinel}) ##").returncode, 0
                )
                expanded = run("display-message", "-p", "#{T:set-titles-string}").stdout
                self.assertEqual(expanded.strip(), f"#(touch {sentinel}) ##")
                time.sleep(0.2)
                self.assertFalse(sentinel.exists())
            finally:
                run("kill-server")
