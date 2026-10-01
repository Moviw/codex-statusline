import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.render import load_config, render, visible_width


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.state = {
            "model": "Claude Sonnet 4.5",
            "context_used": 62.5,
            "cwd": "/work/项目/service",
            "branch": "feature/status",
            "now": 1_700_000_000,
            "quotas": {
                "5h": {
                    "remaining": 71,
                    "reset_at": 1_700_003_600,
                    "observed_at": 1_699_999_700,
                },
                "weekly": {
                    "remaining": 42,
                    "reset_at": 1_702_000_000,
                    "observed_at": 1_699_999_700,
                },
            },
        }

    def test_widths_1_to_240_with_tmux_and_plain(self):
        for tmux in (True, False):
            for width in range(1, 241):
                result = render(self.state, width, tmux=tmux)
                self.assertLessEqual(visible_width(result), width, (width, result))
                self.assertNotIn("\n", result)

    def test_full_layout_and_quota_bars(self):
        result = render(self.state, 240)
        for expected in ("CTX USED", "62%", "5h", "week"):
            self.assertIn(expected, result)
        self.assertGreaterEqual(result.count("█"), 8)
        self.assertNotIn("reset ", result)
        for removed in ("Claude", "feature/status", "/work", "LEFT", "age"):
            self.assertNotIn(removed, result)
        # The weekly reset is disambiguated by weekday and time.
        self.assertRegex(result, r"[A-Z][a-z]{2} \d{1,2}:\d{2}[ap]m")

    def test_unknown_values(self):
        result = render(
            {"model": "M", "context_used": None, "cwd": "/x", "quotas": {}},
            240,
            tmux=False,
        )
        self.assertIn("--", result)

    def test_expired_window_shows_full_quota_without_reset_time(self):
        state = {
            "model": "M",
            "context_used": 40,
            "now": 1000,
            "quotas": {
                "5h": {"remaining": 12, "reset_at": 900, "observed_at": 800},
                "weekly": {"remaining": 42, "reset_at": 5000, "observed_at": 800},
            },
        }
        full = render(state, 200, tmux=False)
        self.assertIn("5h ██████████ 100% |", full)
        self.assertNotIn("12%", full)
        self.assertNotIn("refresh", full)
        for width in range(1, 150):
            self.assertNotIn("12%", render(state, width, tmux=False))

    def test_plan_without_5h_window_hides_that_segment(self):
        weekly = {"remaining": 31, "reset_at": 5000, "observed_at": 900}
        only_week = render({"now": 1000, "quotas": {"weekly": weekly}}, 200, tmux=False)
        self.assertNotIn("5h", only_week)
        self.assertIn("week", only_week)
        nothing_yet = render({"now": 1000, "quotas": {}}, 200, tmux=False)
        self.assertIn("5h --", nothing_yet)
        self.assertIn("week --", nothing_yet)

    def test_context_and_quota_direction_in_compact_layout(self):
        state = {
            "model": "M",
            "context_used": 81,
            "now": 1000,
            "quotas": {
                "5h": {"remaining": 19, "reset_at": 2000},
                "weekly": {"remaining": 50, "reset_at": 3000},
            },
        }
        line = render(state, 95, tmux=False)
        self.assertIn("CTX USED", line)
        if "5h" in line:
            self.assertIn("19%", line)
        if "week" in line:
            self.assertIn("50%", line)

    def test_snapshot_age(self):
        result = render(
            {"now": 10_000, "quotas": {"5h": {"remaining": 10, "observed_at": 9_880}}},
            200,
            tmux=False,
        )
        self.assertNotIn("age", result)

    def test_untrusted_text_strips_ansi_bidi_and_inert_tmux_hashes(self):
        hostile = {
            "model": "x#[fg=red]#(whoami)\x1b]0;title\x07\u202e",
            "cwd": "项目#(bad)",
            "branch": "a#[default]",
        }
        result = render(hostile, 240, tmux=True)
        # Strip renderer-owned styles. Any literal dangerous token is doubled.
        payload = re.sub(r"(?<!#)(?:##)*#\[[^\]]*\]", "", result)
        self.assertNotIn("whoami", payload)
        self.assertNotIn("bad", payload)
        self.assertNotIn("a##[default]", payload)
        self.assertNotIn("\x1b", result)
        self.assertNotIn("title", result)
        self.assertNotIn("\u202e", result)
        # Style directives in the finished string are only from fixed palettes.
        styles = re.findall(r"(?<!#)(?:##)*#\[[^\]]*\]", result)
        self.assertTrue(
            all(
                s
                in {
                    "#[fg=colour255,bg=colour237,bold]",
                    "#[fg=colour232,bg=colour250,bold]",
                    "#[fg=colour75]",
                    "#[fg=colour25]",
                    "#[fg=colour220]",
                    "#[fg=colour130]",
                    "#[fg=colour196]",
                    "#[fg=colour160]",
                    "#[default]",
                }
                for s in styles
            ),
            styles,
        )

    def test_malicious_hash_clipping_never_splits_escape(self):
        state = {
            "model": "ab#(command)#[fg=red]長長長",
            "cwd": "#()",
            "branch": "#[default]",
        }
        for width in range(1, 80):
            result = render(state, width, tmux=True)
            self.assertLessEqual(visible_width(result), width)
            # Renderer's style controls are distinguishable from escaped payload.
            payload = re.sub(r"(?<!#)(?:##)*#\[[^\]]*\]", "", result)
            self.assertIsNone(re.search(r"(?<!#)#\([^)]*\)", payload), (width, result))
            self.assertNotIn("\x1b", result)

    def test_plain_mode_does_not_tmux_escape_hashes_or_style(self):
        result = render({"model": "x#(ordinary)", "cwd": "#[plain]"}, 240, tmux=False)
        self.assertNotIn("ordinary", result)
        self.assertNotIn("#[plain]", result)
        self.assertNotIn("\x1b", result)

    def test_urgency_styles_keep_numbers_visible(self):
        cases = [
            ({"context_used": 80}, "colour220"),
            ({"context_used": 95}, "colour196"),
        ]
        for fields, color in cases:
            state = {"model": "M", "now": 1000, "quotas": {}, **fields}
            out = render(state, 240)
            self.assertIn(f"#[fg={color}]", out)
            self.assertIn(f"{fields['context_used']}%", out)
        for remaining, color in ((20, "colour220"), (5, "colour196")):
            state = {
                "model": "M",
                "context_used": 10,
                "now": 1000,
                "quotas": {"5h": {"remaining": remaining, "reset_at": 2000}},
            }
            out = render(state, 240)
            self.assertIn(f"#[fg={color}]", out)
            self.assertIn(f"{remaining}%", out)

    def test_plain_mode_has_no_tmux_or_ansi(self):
        result = render(self.state, 240, tmux=False)
        self.assertNotIn("#[", result)
        self.assertNotIn("\x1b[", result)

    def test_auto_theme_uses_terminal_background(self):
        from src.render import THEMES

        self.assertEqual(THEMES["auto"], "bg=default,fg=default")
        self.assertIn("#[fg=colour33]", render(self.state, 240, theme="auto"))

    def test_theme_and_ascii(self):
        self.assertNotEqual(
            render(self.state, 80, theme="dark"), render(self.state, 80, theme="light")
        )
        self.assertTrue(render(self.state, 240, ascii_only=True, tmux=False).isascii())

    def test_tokens_segment_is_dropped_before_quotas(self):
        state = dict(self.state, tokens=18_913_137)
        self.assertIn("tok 18.9M", render(state, 240, tmux=False))
        narrow = render(state, 45, tmux=False)
        self.assertNotIn("tok", narrow)
        self.assertIn("5h", narrow)

    def test_segments_order_and_quota_thresholds(self):
        state = dict(self.state, tokens=999)
        result = render(state, 240, tmux=False, segments=["tokens", "5h"])
        self.assertTrue(result.startswith("tok 999 | 5h"), result)
        self.assertNotIn("CTX", result)
        self.assertIn("colour196", render(self.state, 240, segments=["5h"], crit_at=80))


class ConfigTests(unittest.TestCase):
    def test_missing_file_defaults_and_invalid_keys_ignored(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(os.environ, {}, clear=True),
            patch("sys.stderr"),
        ):
            path = Path(tmp) / "config.toml"
            self.assertEqual(load_config(path)["segments"], ["ctx", "5h", "week", "tokens"])
            path.write_text('segments = ["week", "ctx"]\ntheme = "neon"\nwarn_at = 30\n')
            cfg = load_config(path)
            self.assertEqual(
                (cfg["segments"], cfg["theme"], cfg["warn_at"]),
                (["week", "ctx"], "auto", 30),
            )
            path.write_text("not = [toml")
            self.assertEqual(load_config(path)["theme"], "auto")


if __name__ == "__main__":
    unittest.main()


class ClockTests(unittest.TestCase):
    def test_reset_time_ignores_locale(self):
        import locale
        from datetime import datetime

        from src.render import _reset

        stamp = datetime(2026, 10, 3, 18, 5).timestamp()  # a Saturday, 6:05pm
        previous = locale.setlocale(locale.LC_TIME)
        try:
            for name in ("ja_JP.UTF-8", "de_DE.UTF-8", "C"):
                try:
                    locale.setlocale(locale.LC_TIME, name)
                except locale.Error:
                    continue
                self.assertEqual(_reset(stamp, 0), "6:05pm")
                self.assertEqual(_reset(stamp, 0, weekly=True), "Sat 6:05pm")
        finally:
            locale.setlocale(locale.LC_TIME, previous)
