import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.configure import apply, dump_toml, model_from, rows_text, to_config
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
        apply(m, 6, "right")  # theme auto -> dark
        apply(m, 8, "left")  # warn_at 20 -> 15
        apply(m, 9, "left")  # crit_at 5 -> 0
        apply(m, 9, "left")  # clamps at 0
        apply(m, 10, "space")  # update notice off
        apply(m, 5, "space")  # line 2: usage on
        cfg = to_config(m)
        self.assertEqual(cfg["line2"], ["usage"])
        self.assertEqual(cfg["segments"], ["ctx", "week", "5h"])
        self.assertEqual((cfg["theme"], cfg["warn_at"], cfg["crit_at"]), ("dark", 15, 0))
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
