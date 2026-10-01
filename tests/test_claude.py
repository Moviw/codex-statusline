import argparse
import contextlib
import io
import json
import os
import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from src import manage, update
from src.claude import state_from, statusline

NOW = time.time()
SUBSCRIBER = {
    "context_window": {
        "used_percentage": 35,
        "total_input_tokens": 1_190_000,
        "total_output_tokens": 44_000,
        "current_usage": {
            "input_tokens": 500,
            "cache_read_input_tokens": 9400,
            "cache_creation_input_tokens": 100,
        },
    },
    "rate_limits": {
        "five_hour": {"used_percentage": 82, "resets_at": NOW + 7200},
        "seven_day": {"used_percentage": 38, "resets_at": NOW + 200_000},
    },
    "cost": {"total_cost_usd": 1.8412},
}
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def run_statusline(data, home):
    env = {"XDG_CONFIG_HOME": str(home / "cfg"), "XDG_CACHE_HOME": str(home / "cache")}
    with patch.dict(os.environ, env), patch("src.claude.terminal_width", return_value=140):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            with patch("src.claude.cached_newer_version", return_value=None):
                statusline(io.StringIO(data if isinstance(data, str) else json.dumps(data)))
    return out.getvalue()


class ClaudeStatuslineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)

    def test_subscriber_gets_both_lines_with_cost(self):
        out = run_statusline(SUBSCRIBER, self.home)
        self.assertIn("\x1b[38;5;", out)  # ANSI colors for Claude Code
        plain = ANSI.sub("", out).splitlines()
        self.assertEqual(len(plain), 2)
        self.assertIn("CTX USED", plain[0])
        self.assertIn("5h ██░░░░░░░░ 18%", plain[0])
        self.assertIn("in 1.2M · 94% cached · out 44.0k · ≈$1.84", plain[1])

    def test_api_key_user_has_no_quota_segments_or_guessed_cache(self):
        data = {
            "context_window": {
                "used_percentage": 12,
                "total_input_tokens": 52_000,
                "total_output_tokens": 3100,
            },
            "cost": {"total_cost_usd": 0.43},
        }
        plain = ANSI.sub("", run_statusline(data, self.home))
        self.assertNotIn("5h", plain)
        self.assertNotIn("week", plain)
        self.assertNotIn("cached", plain)
        self.assertIn("in 52.0k · out 3.1k · ≈$0.43", plain)

    def test_bad_input_still_prints_a_bar(self):
        for data in ("not json", "[1, 2]", ""):
            self.assertIn("CTX USED", run_statusline(data, self.home))

    def test_state_mapping(self):
        state = state_from(SUBSCRIBER, NOW)
        self.assertEqual(state["quotas"]["5h"]["remaining"], 18.0)
        self.assertEqual(state["quotas"]["weekly"]["reset_at"], NOW + 200_000)
        self.assertEqual(state["tokens"], 1_234_000)


class ClaudeInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        (self.home / ".claude").mkdir()
        self.settings = self.home / ".claude" / "settings.json"
        env = {"CODEX_HOME": str(self.home / ".codex"), "ZDOTDIR": str(self.home)}
        p = patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        os.environ.pop("CLAUDE_CONFIG_DIR", None)

    def run_install(self, uninstall=False, claude=False):
        args = argparse.Namespace(
            home=str(self.home), shell="zsh", yes=True, dry_run=False, claude=claude
        )
        with contextlib.redirect_stdout(io.StringIO()) as out:
            manage.installation(args, uninstall)
        return out.getvalue()

    def status_line(self):
        return json.loads(self.settings.read_text()).get("statusLine")

    def test_adds_and_removes_only_its_own_entry(self):
        self.settings.write_text('{"theme": "dark"}')
        self.assertIn("add the Claude Code statusLine", self.run_install())
        self.assertEqual(self.status_line(), manage.claude_status_line())
        self.run_install(uninstall=True)
        self.assertEqual(json.loads(self.settings.read_text()), {"theme": "dark"})

    def test_never_replaces_another_statusline_unless_asked(self):
        theirs = {"type": "command", "command": "~/.claude/other.py"}
        self.settings.write_text(json.dumps({"statusLine": theirs}))
        self.assertIn("keeps your current statusLine", self.run_install())
        self.assertEqual(self.status_line(), theirs)
        self.run_install(claude=True)
        self.assertEqual(self.status_line(), manage.claude_status_line())
        self.run_install(uninstall=True)
        self.assertEqual(self.status_line(), theirs)  # restored

    def test_no_claude_dir_means_no_changes_there(self):
        self.settings.unlink(missing_ok=True)
        (self.home / ".claude").rmdir()
        self.assertNotIn("Claude", self.run_install())
        self.assertFalse(self.settings.exists())


class CachedUpdateTests(unittest.TestCase):
    def test_uses_cache_and_refreshes_in_background_only(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"XDG_CACHE_HOME": tmp}):
            with (
                patch.object(update.subprocess, "Popen") as popen,
                patch.object(
                    update, "latest_version", side_effect=AssertionError("no network here")
                ),
            ):
                self.assertIsNone(update.cached_newer_version())  # nothing cached yet
                self.assertEqual(popen.call_count, 1)  # refresh started, detached
                update.cache_path().write_text(
                    json.dumps({"checked": time.time(), "latest": "99.0"})
                )
                self.assertEqual(update.cached_newer_version(), "99.0")
                self.assertEqual(popen.call_count, 1)  # fresh cache: no new refresh
