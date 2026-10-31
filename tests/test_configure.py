import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.configure import SETTINGS, apply, dump_toml, model_from, rows_text, to_config
from src.render import load_config


class ConfigureTests(unittest.TestCase):
    def setUp(self):
        with patch.dict("os.environ", {}, clear=True):
            self.model = model_from(load_config("/nonexistent/config.toml"))

    def test_toggle_reorder_and_adjust(self):
        m = self.model
        row = apply(m, 3, "space")  # turn tokens off
        row = apply(m, 1, "J")  # move 5h below week
        self.assertEqual(row, 2)
        line2 = len(m["order"])
        settings = line2 + len(m["line2_order"])
        apply(m, settings, "right")  # theme auto -> dark
        apply(m, settings + 2, "left")  # warn_at 40 -> 35
        apply(m, settings + 3, "left")  # crit_at 20 -> 15
        apply(m, settings + 3, "left")  # 15 -> 10
        apply(m, settings + 4, "space")  # update notice off
        apply(m, line2, "space")  # usage off
        apply(m, line2 + 1, "space")  # cost off
        apply(m, line2 + 2, "space")  # git off
        apply(m, line2 + 3, "space")  # pace on
        cfg = to_config(m)
        self.assertEqual(cfg["line2"], ["pace"])
        self.assertEqual(cfg["segments"], ["ctx", "week", "5h"])
        self.assertEqual((cfg["theme"], cfg["warn_at"], cfg["crit_at"]), ("dark", 35, 10))
        self.assertFalse(cfg["update_check"])
        self.assertIn("[ ] tokens", "\n".join(rows_text(m)))

    def test_last_segment_cannot_be_turned_off(self):
        for row in range(4):
            apply(self.model, row, "space")
        self.assertEqual(to_config(self.model)["segments"], ["tokens"])

    def test_saved_file_loads_back(self):
        apply(self.model, 0, "J")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(dump_toml(to_config(self.model)))
            with patch.dict("os.environ", {}, clear=True):
                self.assertEqual(load_config(path), to_config(self.model))


class TwoToolTests(unittest.TestCase):
    def test_model_toggle_reorder_and_roundtrip(self):
        from src.configure import dump_sections

        with patch.dict("os.environ", {}, clear=True):
            model = model_from(load_config("/nonexistent.toml", "claude"), "claude")
            self.assertIn("model", model["enabled"])
            row = apply(model, model["order"].index("model"), "J")
            self.assertEqual(row, 1)
            apply(model, row, "space")
            text = dump_sections({"claude": to_config(model)})
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "config.toml"
                path.write_text(text)
                saved = load_config(path, "claude")
                self.assertNotIn("model", saved["segments"])
                self.assertEqual(saved, to_config(model))

    def test_each_tool_saves_and_loads_its_own_section(self):
        from src.configure import dump_sections

        with patch.dict("os.environ", {}, clear=True):
            codex = model_from(load_config("/nonexistent.toml", "codex"), "codex")
            claude = model_from(load_config("/nonexistent.toml", "claude"), "claude")
        self.assertNotIn("cost", codex["line2_order"])  # Codex has no cost data
        apply(codex, 3, "space")  # codex: tokens off
        claude["theme"] = "light"
        text = dump_sections({"codex": to_config(codex), "claude": to_config(claude)})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(text)
            with patch.dict("os.environ", {}, clear=True):
                self.assertNotIn("tokens", load_config(path, "codex")["segments"])
                self.assertEqual(load_config(path, "codex")["theme"], "auto")
                self.assertEqual(load_config(path, "claude")["theme"], "light")
                self.assertEqual(
                    load_config(path, "claude")["segments"], ["model", "ctx", "5h", "week"]
                )

    def test_old_flat_config_applies_to_both_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text('theme = "dark"\n[claude]\nwarn_at = 40\n')
            with patch.dict("os.environ", {}, clear=True), patch("sys.stderr") as err:
                self.assertEqual(load_config(path, "codex")["theme"], "dark")
                self.assertEqual(load_config(path, "claude")["theme"], "dark")
                self.assertEqual(load_config(path, "claude")["warn_at"], 40)
                self.assertEqual(load_config(path, "codex")["warn_at"], 40)
            self.assertFalse(err.write.called)  # [claude] is not an "invalid key"

    def test_preview_colors_are_parsed(self):
        from src.configure import preview_lines, styled_parts

        with patch.dict("os.environ", {}, clear=True):
            model = model_from(load_config("/nonexistent.toml", "claude"), "claude")
        lines = preview_lines(model, "claude", 160, False)
        self.assertEqual(len(lines), 2)
        parts = styled_parts(lines[0])
        self.assertTrue(any(color == 160 for _, color in parts))  # 5h at 18% left is red
        self.assertIn("≈$1.84", "".join(text for text, _ in styled_parts(lines[1])))

    def test_thresholds_clamp_and_save_writes_only_changes(self):
        from src.configure import dump_sections

        with patch.dict("os.environ", {}, clear=True):
            model = model_from(load_config("/nonexistent.toml", "codex"), "codex")
            row = len(model["order"]) + len(model["line2_order"]) + SETTINGS.index("crit_at")
            for _ in range(30):
                apply(model, row, "left")  # crit_at all the way down
            self.assertEqual(model["crit_at"], 0)
            text = dump_sections({"codex": to_config(model)})
        self.assertEqual(text, "[codex]\ncrit_at = 0\n")
