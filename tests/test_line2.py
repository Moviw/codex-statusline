import json
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from src.data import LogReader
from src.render import load_config, render_line2

NOW = 1_800_000_000


def quota(remaining, reset_in, minutes_seen_ago=0):
    return {
        "remaining": remaining,
        "reset_at": NOW + reset_in,
        "observed_at": NOW - 60 * minutes_seen_ago,
    }


class Line2Tests(unittest.TestCase):
    def test_pace_runs_out_or_lasts(self):
        # 5h window, 2h in, 78% used -> empties ~34 min from now, before the 3h reset.
        fast = {"now": NOW, "quotas": {"5h": quota(22, 3 * 3600)}}
        self.assertIn("5h pace: runs out ~", render_line2(fast, 200, ["pace"], tmux=False))
        slow = {"now": NOW, "quotas": {"weekly": quota(85, 5 * 86400)}}
        self.assertIn("week pace: lasts to reset", render_line2(slow, 200, ["pace"], tmux=False))
        expired = {"now": NOW, "quotas": {"5h": quota(22, -10)}}
        self.assertEqual(render_line2(expired, 200, ["pace"], tmux=False), "")

    def test_usage_breakdown_and_narrow_drop(self):
        state = {
            "now": NOW,
            "context_used": 50,
            "window": 258_400,
            "usage": {
                "input_tokens": 2_000_000,
                "cached_input_tokens": 1_900_000,
                "output_tokens": 66_000,
            },
            "quotas": {"5h": quota(22, 3 * 3600)},
        }
        wide = render_line2(state, 200, ["pace", "usage"], tmux=False)
        self.assertIn("in 2.0M · 95% cached · out 66.0k · ctx 129.2k/258.4k", wide)
        narrow = render_line2(state, 40, ["pace", "usage"], tmux=False)
        self.assertIn("5h pace", narrow)
        self.assertNotIn("cached", narrow)
        self.assertTrue(render_line2(state, 200, ["usage"], tmux=False, ascii_only=True).isascii())
        self.assertEqual(render_line2(state, 200, [], tmux=False), "")

    def test_reader_keeps_breakdown_and_window(self):
        info = {
            "total_token_usage": {
                "input_tokens": 10,
                "cached_input_tokens": 4,
                "output_tokens": 2,
                "total_tokens": 12,
            },
            "model_context_window": 258_400,
        }
        event = {
            "type": "event_msg",
            "timestamp": NOW,
            "payload": {"type": "token_count", "info": info},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.jsonl"
            path.write_text(json.dumps(event) + "\n")
            snap = LogReader().update(str(path))
        self.assertEqual(
            snap["usage"], {"input_tokens": 10.0, "cached_input_tokens": 4.0, "output_tokens": 2.0}
        )
        self.assertEqual(snap["window"], 258_400.0)

    def test_config_line2_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.toml"
            path.write_text('line2 = ["pace", "usage"]\n')
            self.assertEqual(load_config(path)["line2"], ["pace", "usage"])
            path.write_text('line2 = ["bogus"]\n')
            with unittest.mock.patch("sys.stderr"):
                self.assertEqual(load_config(path)["line2"], [])
