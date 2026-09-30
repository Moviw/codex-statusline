import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from src.render import render


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
            finally:
                run("kill-server")
