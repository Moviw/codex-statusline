import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.render import render
from src.update import is_newer, newer_version, upgrade_command


class UpdateTests(unittest.TestCase):
    def test_version_compare(self):
        self.assertTrue(is_newer("0.1.10", "0.1.9"))
        self.assertFalse(is_newer("0.1.1", "0.1.1"))
        self.assertFalse(is_newer("garbage", "0.1.1"))

    def test_newer_version_is_silent_on_failure(self):
        with patch("urllib.request.urlopen", side_effect=OSError("offline")):
            self.assertIsNone(newer_version())
        body = io.BytesIO(json.dumps({"info": {"version": "99.0.0"}}).encode())
        with patch("urllib.request.urlopen", return_value=body):
            self.assertEqual(newer_version(), "99.0.0")

    def test_upgrade_command_matches_install_method(self):
        pkg = Path("/nowhere/src")
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "uv-receipt.toml").touch()
            self.assertEqual(
                upgrade_command(tmp, pkg), ["uv", "tool", "install", "codex-statusline@latest"]
            )
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "pipx_metadata.json").touch()
            self.assertEqual(
                upgrade_command(tmp, pkg), ["pipx", "install", "--force", "codex-statusline"]
            )
        self.assertEqual(upgrade_command("/nowhere", pkg)[1:3], ["-m", "pip"])
        repo = Path(__file__).resolve().parent.parent
        if (repo / ".git").exists():
            self.assertEqual(upgrade_command("/nowhere", repo / "src")[:2], ["git", "-C"])

    def test_update_hint_is_dropped_first_when_narrow(self):
        state = {"context_used": 10, "now": 1000, "update": "0.2.0", "quotas": {}}
        wide = render(state, 240, tmux=False)
        self.assertIn("↑ update available: codex-statusline update", wide)
        self.assertIn("^ update available", render(state, 240, tmux=False, ascii_only=True))
        self.assertNotIn("update", render(state, 40, tmux=False))
        self.assertNotIn("update", render(dict(state, update="#(evil)"), 240, tmux=False))
