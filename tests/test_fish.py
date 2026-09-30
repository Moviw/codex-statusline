import argparse
import contextlib
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from src import manage


@unittest.skipUnless(shutil.which("fish"), "fish not installed")
class FishTests(unittest.TestCase):
    def test_autoload_arguments_repeat_and_extension_uninstall(self):
        with tempfile.TemporaryDirectory(prefix="fish test ") as d:
            root = pathlib.Path(d)
            env = dict(
                os.environ,
                HOME=d,
                XDG_CONFIG_HOME=str(root / ".config"),
                CODEX_HOME=str(root / ".codex"),
                ZDOTDIR=d,
                TERM="xterm-256color",
            )
            fake = root / "official"
            fake.write_text(
                "#!" + sys.executable + "\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n"
            )
            fake.chmod(0o755)
            env["CODEX_STATUSLINE_CODEX"] = str(fake)
            args = argparse.Namespace(home=d, shell="zsh", yes=True, dry_run=False)
            with patch.dict(os.environ, env), contextlib.redirect_stdout(io.StringIO()):
                manage.installation(args)
                args.shell = "fish"
                manage.installation(args)
                manifest = root / ".local/share/codex-statusline/install.json"
                self.assertEqual(len(json.loads(manifest.read_text())["shells"]), 2)
                fish = root / ".config/fish/conf.d/codex-statusline.fish"
                before = fish.read_bytes()
                manage.installation(args)
                self.assertEqual(before, fish.read_bytes())
                inputs = [
                    "exec",
                    "a b",
                    "中文",
                    "a'b",
                    "$(touch /tmp/should-not-exist-csl-fish)",
                    "; echo x",
                ]
                p = subprocess.run(
                    ["fish", "-i", "-c", "codex $argv", *inputs],
                    env=env,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual(json.loads(p.stdout), inputs)
                p = subprocess.run(
                    ["fish", "-c", "functions -q codex; echo $status"],
                    env=env,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(p.stdout.strip(), "1")
                with fish.open("a") as f:
                    f.write("# later user setting\n")
                manage.installation(args, True)
                self.assertEqual(fish.read_text(), "# later user setting\n")
                self.assertNotIn(manage.BEGIN, (root / ".zshrc").read_text())

    def test_shell_detection_prefers_parent_to_login_shell(self):
        with (
            patch.dict(os.environ, {"SHELL": "/bin/zsh"}),
            patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, "/opt/homebrew/bin/fish\n", ""),
            ),
        ):
            self.assertEqual(manage.detected_shell(), "fish")
