import argparse
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import manage
from src.launcher import ENTRY, binding_for, interactive


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(
            os.environ,
            {"CODEX_HOME": str(self.root / ".codex"), "ZDOTDIR": str(self.root)},
        )
        self.env.start()
        self.args = argparse.Namespace(home=str(self.root), shell="both", yes=True, dry_run=False)
        self.stream = contextlib.redirect_stdout(io.StringIO())
        self.stream.__enter__()

    def tearDown(self):
        self.stream.__exit__(None, None, None)
        self.env.stop()
        self.temp.cleanup()

    def test_tool_install_uses_stable_bin_not_site_packages(self):
        fake = Path("/venv/lib/python3.12/site-packages/src/entry.py")
        with (
            patch.object(manage, "ENTRY", fake),
            patch(
                "src.manage.shutil.which",
                return_value="/home/u/.local/bin/codex-statusline",
            ),
        ):
            self.assertEqual(
                manage.hook_group()["hooks"][0]["command"],
                "/home/u/.local/bin/codex-statusline hook",
            )
            self.assertNotIn(
                "site-packages", manage.shell_block("zsh") + manage.shell_block("fish")
            )
        self.assertIn(
            str(ENTRY), manage.hook_group()["hooks"][0]["command"]
        )  # git-clone mode unchanged

    def test_install_from_new_path_replaces_previous_install(self):
        (self.root / ".zshrc").write_text("# mine\n")
        manage.installation(self.args)  # e.g. an old git-checkout install
        tool = ["/home/u/.local/bin/codex-statusline"]
        with patch.object(manage, "base_command", return_value=tool):
            manage.installation(self.args)  # now from uv/pipx
            rc = (self.root / ".zshrc").read_text()
            self.assertEqual(rc.count(manage.BEGIN), 1)
            self.assertIn(tool[0], rc)
            hooks = json.loads((self.root / ".codex/hooks.json").read_text())
            commands = [h["hooks"][0]["command"] for h in hooks["hooks"]["SessionStart"]]
            self.assertEqual(commands, [tool[0] + " hook"])
            manage.installation(self.args, True)
        self.assertEqual((self.root / ".zshrc").read_text(), "# mine\n")

    def test_cxbar_uses_its_own_shim_not_another_copy_on_path(self):
        fake = Path("/venv/lib/python3.12/site-packages/src/entry.py")
        bindir = self.root / "toolbin"
        bindir.mkdir()
        for name in ("codex-statusline", "cxbar"):
            (bindir / name).write_text("#!/bin/sh\n")
        older = "/usr/local/bin/codex-statusline"
        with (
            patch.object(manage, "ENTRY", fake),
            patch.object(sys, "argv", [str(bindir / "cxbar"), "install"]),
            patch("src.manage.shutil.which", return_value=older),
        ):
            self.assertEqual(manage.base_command(), [str(bindir / "codex-statusline")])

    def test_install_repeat_uninstall_preserves_later_changes(self):
        original = "# original rc\nexport USER_SETTING=yes\n"
        (self.root / ".zshrc").write_text(original)
        hp = self.root / ".codex/hooks.json"
        hp.parent.mkdir()
        existing = {"hooks": [{"type": "command", "command": "echo original"}]}
        hp.write_text(json.dumps({"description": "mine", "hooks": {"SessionStart": [existing]}}))
        manage.installation(self.args)
        first = (self.root / ".zshrc").read_bytes(), hp.read_bytes()
        manage.installation(self.args)
        self.assertEqual(first, ((self.root / ".zshrc").read_bytes(), hp.read_bytes()))
        with (self.root / ".zshrc").open("a") as f:
            f.write("# added later\n")
        other = {"hooks": [{"type": "command", "command": "echo later"}]}
        data = json.loads(hp.read_text())
        data["hooks"]["SessionStart"].append(other)
        hp.write_text(json.dumps(data))
        manage.installation(self.args, True)
        self.assertEqual((self.root / ".zshrc").read_text(), original + "# added later\n")
        data = json.loads(hp.read_text())
        self.assertEqual(data["hooks"]["SessionStart"], [existing, other])
        self.assertEqual(data["description"], "mine")

    def test_dry_run_writes_nothing(self):
        self.args.dry_run = True
        manage.installation(self.args)
        self.assertFalse((self.root / ".zshrc").exists())
        self.assertFalse((self.root / ".codex").exists())

    def test_invalid_json_no_shell_write(self):
        p = self.root / ".codex/hooks.json"
        p.parent.mkdir()
        p.write_text("bad")
        with self.assertRaises(ValueError):
            manage.installation(self.args)
        self.assertFalse((self.root / ".zshrc").exists())

    def test_inline_hooks_refused(self):
        p = self.root / ".codex/config.toml"
        p.parent.mkdir()
        p.write_text("[[hooks.SessionStart]]\n")
        with self.assertRaises(ValueError):
            manage.installation(self.args)

    def test_edited_owned_block_not_removed(self):
        manage.installation(self.args)
        p = self.root / ".zshrc"
        p.write_text(p.read_text().replace('launch "$@"', 'launch --foo "$@"'))
        with self.assertRaises(ValueError):
            manage.installation(self.args, True)

    def test_manifest_loss_is_not_false_success(self):
        manage.installation(self.args)
        (self.root / ".local/share/codex-statusline/install.json").unlink()
        with self.assertRaises(ValueError):
            manage.installation(self.args)

    def test_shell_array_passthrough(self):
        manage.installation(self.args)
        fake = self.root / "official"
        fake.write_text(
            "#!" + sys.executable + "\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n"
        )
        fake.chmod(0o755)
        env = dict(os.environ, CODEX_STATUSLINE_CODEX=str(fake))
        inputs = [
            "exec",
            "a b",
            "$(touch /tmp/NEVER_CSL)",
            "中文",
            "x;echo bad",
            "--json",
        ]
        for shell, rc in [("bash", ".bashrc"), ("zsh", ".zshrc")]:
            exe = shutil.which(shell)
            if not exe:
                continue
            command = [
                exe,
                "-c",
                'source "$1"; shift; codex "$@"',
                "test",
                str(self.root / rc),
                *inputs,
            ]
            p = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(json.loads(p.stdout), inputs)

    def test_absent_wrapper_hook_is_silent(self):
        env = dict(os.environ)
        env.pop("CODEX_STATUSLINE_STATE", None)
        env.pop("CODEX_STATUSLINE_LAUNCH", None)
        p = subprocess.run(
            [sys.executable, str(ENTRY), "hook"],
            input="not json",
            env=env,
            text=True,
            capture_output=True,
        )
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))


class RouteTests(unittest.TestCase):
    @patch("os.isatty", return_value=True)
    def test_commands(self, _):
        with patch.dict(os.environ, {"TERM": "xterm-256color"}):
            for args in (
                [],
                ["resume", "--last"],
                ["fork"],
                ["-m", "help"],
                ["a long prompt"],
                ["--", "exec"],
            ):
                self.assertTrue(interactive(args), args)
            for args in (
                ["exec", "x"],
                ["--help"],
                ["-m", "model", "--version"],
                ["features"],
                ["--remote", "unix://"],
            ):
                self.assertFalse(interactive(args), args)

    @patch("os.isatty", return_value=False)
    def test_redirected(self, _):
        self.assertFalse(interactive([]))

    def test_binding_uses_launch_and_ambiguity_guard(self):
        sid = "12345678-1234-1234-1234-123456789abc"
        hint = sid[:29] + "..."
        b = {sid: {"session_id": sid, "launch_id": "one"}}
        self.assertEqual(binding_for(b, hint, "one")["session_id"], sid)
        self.assertIsNone(binding_for(b, hint, "two"))
        self.assertIsNone(binding_for(b, "wrong", "one"))
        b[sid[:-1] + "d"] = {"session_id": sid[:-1] + "d", "launch_id": "one"}
        self.assertIsNone(binding_for(b, hint, "one"))


class LaunchFailureTests(unittest.TestCase):
    @patch("src.launcher.official", return_value="/official/codex")
    @patch("src.launcher.interactive", return_value=True)
    @patch("src.launcher.version", return_value=(0, 159, 0))
    @patch("src.launcher.shutil.which", return_value="/fake/tmux")
    def test_timeout_after_dispatch_does_not_launch_twice(self, *_):
        from src.launcher import launch

        def run(cmd, **kwargs):
            if "respawn-pane" in cmd:
                raise subprocess.TimeoutExpired(cmd, 2)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with (
            patch("subprocess.run", side_effect=run),
            patch("os.execv") as execv,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(launch([]), 1)
            execv.assert_not_called()

    @patch("src.launcher.official", return_value="/official/codex")
    @patch("src.launcher.interactive", return_value=True)
    @patch("src.launcher.shutil.which", return_value=None)
    def test_missing_tmux_passes_original_arguments(self, *_):
        from src.launcher import launch

        with (
            patch("os.execv", side_effect=SystemExit(0)) as execv,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            with self.assertRaises(SystemExit):
                launch(["resume", "abc"])
            execv.assert_called_once_with("/official/codex", ["/official/codex", "resume", "abc"])
