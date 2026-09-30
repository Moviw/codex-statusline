"""Portable macOS/Linux startup checks using a fake, offline official CLI."""

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from src.launcher import ENTRY, placeholder
from src.render import visible_width


class PlaceholderTests(unittest.TestCase):
    def test_no_fabricated_values(self):
        for theme in ("dark", "light"):
            with patch.dict(os.environ, {"CODEX_STATUSLINE_THEME": theme}):
                result = placeholder(160)
                for text in ("CTX USED", "5h", "week", "--"):
                    self.assertIn(text, result)
                for text in ("status unknown", "binding pending", "0%", "100%"):
                    self.assertNotIn(text, result)

    def test_width_and_ascii(self):
        with patch.dict(os.environ, {"CODEX_STATUSLINE_ASCII": "1"}):
            for width in range(1, 241):
                result = placeholder(width)
                self.assertLessEqual(visible_width(result), width)
                self.assertTrue(result.isascii())
        self.assertIn("CTX USED", placeholder("bad"))


@unittest.skipUnless(shutil.which("tmux"), "tmux not installed")
class StartupTests(unittest.TestCase):
    def test_initial_config_and_invalid_title_use_same_layout(self):
        with tempfile.TemporaryDirectory(prefix="csl-start-test-") as d:
            base = Path(d)
            fake = base / "codex"
            fake.write_text(
                "#!"
                + sys.executable
                + "\nimport sys,time\n"
                + 'if "--version" in sys.argv: print("codex-cli 0.159.0")\n'
                + "else: time.sleep(20)\n"
            )
            fake.chmod(0o755)
            master, slave = os.openpty()
            env = dict(
                os.environ,
                TERM="xterm-256color",
                CODEX_STATUSLINE_CODEX=str(fake),
                CODEX_HOME=str(base / "home"),
            )
            proc = subprocess.Popen(
                [sys.executable, str(ENTRY), "launch"],
                stdin=slave,
                stdout=slave,
                stderr=slave,
                env=env,
            )
            os.close(slave)
            root = None
            try:
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    for path in Path("/tmp").glob("csl-*/launch.json"):
                        try:
                            if json.loads(path.read_text()).get("launcher_pid") == proc.pid:
                                root = path.parent
                        except (OSError, ValueError):
                            pass
                    if root and (root / "error.json").exists():
                        break
                    time.sleep(0.05)
                self.assertIsNotNone(root)
                self.assertTrue(
                    (root / "error.json").exists(),
                    "invalid title must exercise recovery branch",
                )
                conf = (root / "tmux.conf").read_text()
                self.assertIn("CTX USED", conf)
                self.assertNotIn("binding pending", conf)
                # error.json is written before the fallback status is applied.
                # Faster Linux startup can observe that intermediate state.
                deadline = time.monotonic() + 3
                while True:
                    r = subprocess.run(
                        [
                            "tmux",
                            "-S",
                            str(root / "tmux.sock"),
                            "show-option",
                            "-v",
                            "status-left",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=3,
                    )
                    if "CTX USED" in r.stdout or time.monotonic() >= deadline:
                        break
                    time.sleep(0.05)
                self.assertEqual(r.returncode, 0, r.stderr)
                for field in ("CTX USED", "5h", "week", "--"):
                    self.assertIn(field, r.stdout)
                self.assertNotIn("status unknown", r.stdout)
            finally:
                if proc.poll() is None:
                    proc.send_signal(signal.SIGTERM)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                os.close(master)
