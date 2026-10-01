import argparse
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import doctor, manage


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        # A symlinked home, like macOS /var -> /private/var or a linked ~/.codex.
        real = Path(self.temp.name) / "real"
        real.mkdir()
        self.home = Path(self.temp.name) / "link"
        self.home.symlink_to(real)
        env = {"CODEX_HOME": str(self.home / ".codex"), "ZDOTDIR": str(self.home)}
        for p in (
            patch.dict(os.environ, env),
            patch.object(doctor, "official", return_value="/bin/codex"),
            patch.object(doctor, "version", return_value=(0, 159, 0)),
        ):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.temp.cleanup)

    def run_checks(self, latest="0.0.1"):
        return {msg: (ok, fix) for ok, msg, fix in doctor.checks(self.home, lambda: latest)}

    def install(self):
        args = argparse.Namespace(home=str(self.home), shell="zsh", yes=True, dry_run=False)
        with contextlib.redirect_stdout(io.StringIO()):
            manage.installation(args)

    def test_not_installed_points_to_install(self):
        results = self.run_checks()
        ok, fix = results["not hooked into your shell yet"]
        self.assertFalse(ok)
        self.assertTrue(fix.endswith(" install"))

    def test_installed_hook_waits_for_approval_then_passes(self):
        self.install()
        self.assertFalse(self.run_checks()["hook not approved in Codex yet"][0])
        hooks = self.home / ".codex" / "hooks.json"
        key = f"{hooks}:session_start:0:0"
        (self.home / ".codex" / "config.toml").write_text(
            f'[hooks.state."{key}"]\ntrusted_hash = "sha256:x"\n'
        )
        results = self.run_checks()
        self.assertTrue(results["hook approved in Codex"][0])
        self.assertTrue(results["codex is hooked into ~/.zshrc"][0])
        self.assertTrue(results["latest version"][0])

    def test_stale_copy_and_update_are_flagged(self):
        self.install()
        with patch.object(doctor, "hook_group", return_value={"hooks": [{"command": "new"}]}):
            results = self.run_checks(latest="99.0.0")
        stale = [m for m in results if m.startswith("codex runs another copy")]
        self.assertEqual(len(stale), 1)
        self.assertEqual(results["99.0.0 available"][1].split()[-1], "update")
        self.assertIsNone(doctor._update_check("cxbar", lambda: None)[0])

    def test_doctor_exit_code(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            with patch.object(doctor, "latest_version", return_value=None):
                code = doctor.doctor(self.home)
        self.assertEqual(code, 1)
        self.assertIn("✗ not hooked into your shell yet", out.getvalue())
        json.dumps(out.getvalue())  # plain text, printable
