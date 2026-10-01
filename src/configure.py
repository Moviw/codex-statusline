"""`codex-statusline config`: pick segments, theme and thresholds with a live preview."""

import curses
import time

from .render import DEFAULT_SEGMENTS, THEMES, config_path, load_config, render

SEGMENT_NAMES = {
    "ctx": "context used",
    "5h": "5-hour quota",
    "week": "weekly quota",
    "tokens": "session tokens",
}
SETTINGS = ["theme", "ascii", "warn_at", "crit_at", "update_check"]
LABELS = {
    "theme": "Theme",
    "ascii": "ASCII only",
    "warn_at": "Quota yellow at",
    "crit_at": "Quota red at",
    "update_check": "Update notice",
}
HELP = "↑↓ move  space toggle  ←→ change  J/K reorder  s save  q quit"


def model_from(cfg: dict) -> dict:
    enabled = [name for name in cfg["segments"] if name in SEGMENT_NAMES]
    order = enabled + [name for name in DEFAULT_SEGMENTS if name not in enabled]
    return {**{key: cfg[key] for key in SETTINGS}, "order": order, "enabled": set(enabled)}


def to_config(model: dict) -> dict:
    segments = [name for name in model["order"] if name in model["enabled"]]
    return {"segments": segments, **{key: model[key] for key in SETTINGS}}


def dump_toml(cfg: dict) -> str:
    def value(v):
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, list):
            return "[" + ", ".join(f'"{x}"' for x in v) + "]"
        return f'"{v}"' if isinstance(v, str) else str(v)

    return "".join(f"{key} = {value(v)}\n" for key, v in cfg.items())


def row_count(model: dict) -> int:
    return len(model["order"]) + len(SETTINGS)


def apply(model: dict, row: int, key: str) -> int:
    """Apply one key press to the row under the cursor; returns the new cursor row."""
    rows = row_count(model)
    if key in ("up", "k"):
        return (row - 1) % rows
    if key in ("down", "j"):
        return (row + 1) % rows
    order = model["order"]
    if row < len(order):
        name = order[row]
        if key == "space":
            # Keep at least one segment on, or the bar would be empty.
            if name not in model["enabled"]:
                model["enabled"].add(name)
            elif len(model["enabled"]) > 1:
                model["enabled"].discard(name)
        elif key in ("K", "J"):
            target = row - 1 if key == "K" else row + 1
            if 0 <= target < len(order):
                order[row], order[target] = order[target], order[row]
                return target
        return row
    setting = SETTINGS[row - len(order)]
    current = model[setting]
    step = {"left": -1, "right": 1}.get(key, 0)
    if isinstance(current, bool):
        if key in ("space", "left", "right"):
            model[setting] = not current
    elif setting == "theme" and (step or key == "space"):
        names = list(THEMES)
        model[setting] = names[(names.index(current) + (step or 1)) % len(names)]
    elif step:
        model[setting] = max(0, min(100, current + 5 * step))
    return row


def rows_text(model: dict) -> list[str]:
    lines = []
    for name in model["order"]:
        mark = "x" if name in model["enabled"] else " "
        lines.append(f"[{mark}] {name:<7} {SEGMENT_NAMES[name]}")
    for setting in SETTINGS:
        value = model[setting]
        if isinstance(value, bool):
            shown = "[x]" if value else "[ ]"
        elif setting == "theme":
            shown = f"< {value} >"
        else:
            shown = f"< {value}% >"
        lines.append(f"{LABELS[setting]:<16} {shown}")
    return lines


def sample_state() -> dict:
    now = time.time()
    return {
        "context_used": 35,
        "tokens": 1_234_567,
        "quotas": {
            "5h": {"remaining": 18, "reset_at": now + 7200, "observed_at": now},
            "weekly": {"remaining": 62, "reset_at": now + 172800, "observed_at": now},
        },
    }


KEYS = {
    curses.KEY_UP: "up",
    curses.KEY_DOWN: "down",
    curses.KEY_LEFT: "left",
    curses.KEY_RIGHT: "right",
    ord(" "): "space",
}


def _ui(screen, model: dict) -> bool:
    curses.curs_set(0)
    row, state = 0, sample_state()
    while True:
        screen.erase()
        height, width = screen.getmaxyx()
        cfg = to_config(model)
        preview = render(
            state,
            max(1, width - 4),
            tmux=False,
            ascii_only=cfg["ascii"],
            segments=cfg["segments"],
            warn_at=cfg["warn_at"],
            crit_at=cfg["crit_at"],
        )
        lines = ["codex-statusline config", HELP, ""]
        lines += [("> " if i == row else "  ") + text for i, text in enumerate(rows_text(model))]
        lines += ["", "Preview (sample numbers):", "  " + preview, "", f"Saves to {config_path()}"]
        for y, text in enumerate(lines[: height - 1]):
            highlight = curses.A_REVERSE if y - 3 == row else curses.A_NORMAL
            try:
                screen.addnstr(y, 0, text, width - 1, highlight)
            except curses.error:
                pass  # tiny terminal: draw what fits
        key = screen.getch()
        name = KEYS.get(key, chr(key) if 0 <= key < 256 else "")
        if name in ("q", "\x1b"):
            return False
        if name in ("s", "\n"):
            return True
        row = apply(model, row, name)


def configure() -> int:
    model = model_from(load_config())
    try:
        save = curses.wrapper(_ui, model)
    except curses.error as error:
        print(f"codex-statusline: needs an interactive terminal ({error}).")
        print(f"Edit {config_path()} instead.")
        return 1
    if not save:
        print("No changes saved.")
        return 0
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_toml(to_config(model)))
    print(f"Saved {path}. Takes effect the next time you start codex.")
    return 0
