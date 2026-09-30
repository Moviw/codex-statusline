import argparse
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import manage


class AutoShellTests(unittest.TestCase):
    def test_detects_all_available_not_just_login_shell(self):
        with patch(
            "shutil.which",
            side_effect=lambda n: "/usr/bin/" + n if n in ("bash", "fish") else None,
        ):
            self.assertEqual(manage.available_shells(), ["bash", "fish"])
            with (
                tempfile.TemporaryDirectory() as d,
                patch.dict(
                    os.environ,
                    {
                        "HOME": d,
                        "CODEX_HOME": d + "/.codex",
                        "XDG_CONFIG_HOME": d + "/.config",
                        "ZDOTDIR": d,
                    },
                ),
            ):
                args = argparse.Namespace(home=d, shell="auto", yes=True, dry_run=False)
                with contextlib.redirect_stdout(io.StringIO()):
                    manage.installation(args)
                    manage.installation(args)
                    manifest = json.loads(
                        (Path(d) / ".local/share/codex-statusline/install.json").read_text()
                    )
                    paths = [str(Path(x["path"]).resolve()) for x in manifest["shells"]]
                    d = str(Path(d).resolve())
                    self.assertIn(d + "/.bashrc", paths)
                    self.assertIn(d + "/.config/fish/conf.d/codex-statusline.fish", paths)
                    self.assertNotIn(d + "/.zshrc", paths)
                    manage.installation(args, True)
                self.assertNotIn(manage.BEGIN, (Path(d) / ".bashrc").read_text())

    def test_no_shell_is_clear_error(self):
        with patch("shutil.which", return_value=None):
            with self.assertRaisesRegex(ValueError, "No supported shell"):
                manage.paths("/tmp/csl-none", "auto")

    def test_explicit_official_path_is_preserved_for_both_shells(self):
        with patch.dict(os.environ, {"CODEX_STATUSLINE_CODEX": "/opt/Official CLI/codex"}):
            for shell in ("bash", "fish"):
                block = manage.shell_block(shell)
                self.assertIn("CODEX_STATUSLINE_CODEX=/opt/Official CLI/codex", block)
                self.assertIn("env", block)
