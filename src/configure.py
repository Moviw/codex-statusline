"""`codex-statusline config`: pick segments, theme and thresholds with a live preview."""

import curses
import locale
import time

from .render import (
    DEFAULT_SEGMENTS,
    LINE2_SEGMENTS,
    THEMES,
    config_path,
    load_config,
    render,
    render_line2,
)

SEGMENT_NAMES = {
    "ctx": "context used",
    "5h": "5-hour quota",
    "week": "weekly quota",
    "tokens": "session tokens",
}
LINE2_NAMES = {
    "usage": "line 2: tokens in / cached / out",
    "cost": "line 2: session cost estimate (Claude Code)",
    "pace": "line 2: when quota runs out at this pace",
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
    return {
        **{key: cfg[key] for key in SETTINGS},
        "order": order,
        "enabled": set(enabled),
        "line2": set(cfg["line2"]),
    }


def to_config(model: dict) -> dict:
    segments = [name for name in model["order"] if name in model["enabled"]]
    line2 = [name for name in LINE2_SEGMENTS if name in model["line2"]]
    return {"segments": segments, "line2": line2, **{key: model[key] for key in SETTINGS}}


def dump_toml(cfg: dict) -> str:
    def value(v):
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, list):
            return "[" + ", ".join(f'"{x}"' for x in v) + "]"
        return f'"{v}"' if isinstance(v, str) else str(v)

    return "".join(f"{key} = {value(v)}\n" for key, v in cfg.items())


def row_count(model: dict) -> int:
    return len(model["order"]) + len(LINE2_SEGMENTS) + len(SETTINGS)


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
    if row < len(order) + len(LINE2_SEGMENTS):
        name = LINE2_SEGMENTS[row - len(order)]
        if key in ("space", "left", "right"):
            model["line2"] ^= {name}
        return row
    setting = SETTINGS[row - len(order) - len(LINE2_SEGMENTS)]
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
    for name in LINE2_SEGMENTS:
        mark = "x" if name in model["line2"] else " "
        lines.append(f"[{mark}] {name:<7} {LINE2_NAMES[name]}")
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
        "usage": {
            "input_tokens": 1_190_000,
            "cached_input_tokens": 1_120_000,
            "output_tokens": 44_000,
        },
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


def _ui(screen, model: dict, ascii_only: bool = False) -> bool:
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
            ascii_only=cfg["ascii"] or ascii_only,
            segments=cfg["segments"],
            warn_at=cfg["warn_at"],
            crit_at=cfg["crit_at"],
        )
        help_text = (
            HELP.replace("↑↓", "up/down").replace("←→", "left/right") if ascii_only else HELP
        )
        lines = ["codex-statusline config", help_text, ""]
        lines += [("> " if i == row else "  ") + text for i, text in enumerate(rows_text(model))]
        second = render_line2(
            state,
            max(1, width - 4),
            cfg["line2"],
            tmux=False,
            ascii_only=cfg["ascii"] or ascii_only,
        )
        lines += ["", "Preview (sample numbers):", "  " + preview]
        lines += ["  " + second] if second else []
        lines += ["", f"Saves to {config_path()}"]
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


def utf8_terminal() -> bool:
    """Put curses in UTF-8 mode; under a C/POSIX locale it mangles block glyphs."""
    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        pass
    if "utf" in locale.nl_langinfo(locale.CODESET).lower():
        return True
    for name in ("C.UTF-8", "en_US.UTF-8", "UTF-8"):
        try:
            locale.setlocale(locale.LC_CTYPE, name)
            return True
        except locale.Error:
            continue
    return False


def configure() -> int:
    model = model_from(load_config())
    ascii_only = not utf8_terminal()
    try:
        save = curses.wrapper(_ui, model, ascii_only)
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
