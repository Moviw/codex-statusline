"""`cxbar config`: one screen per tool (Codex, Claude Code) with a live, colored preview."""

import curses
import locale
import re
import time

from .render import (
    DEFAULT_SEGMENTS,
    LINE2_SEGMENTS,
    TARGETS,
    THEMES,
    config_path,
    load_config,
    render,
    render_line2,
)

TAB_NAMES = {"codex": "Codex", "claude": "Claude Code"}
SEGMENT_NAMES = {
    "ctx": "context used",
    "5h": "5-hour quota",
    "week": "weekly quota",
    "tokens": "session tokens",
}
LINE2_NAMES = {
    "usage": "tokens in / cached / out",
    "cost": "session cost estimate",
    "pace": "when quota runs out at this pace",
}
# Codex reports no cost, so its screen does not offer it.
LINE2_FOR = {"codex": ["usage", "pace"], "claude": LINE2_SEGMENTS}
SETTINGS = ["theme", "ascii", "warn_at", "crit_at", "update_check"]
LABELS = {
    "theme": "Theme",
    "ascii": "ASCII only",
    "warn_at": "Quota yellow at",
    "crit_at": "Quota red at",
    "update_check": "Update notice",
}
HELP = "↑↓ move  space toggle  ←→ change  J/K reorder  Tab switch tool  s save  q quit"


def model_from(cfg: dict, target: str = "claude") -> dict:
    enabled = [name for name in cfg["segments"] if name in SEGMENT_NAMES]
    order = enabled + [name for name in DEFAULT_SEGMENTS if name not in enabled]
    line2_order = LINE2_FOR[target]
    return {
        **{key: cfg[key] for key in SETTINGS},
        "order": order,
        "enabled": set(enabled),
        "line2_order": line2_order,
        "line2": {name for name in cfg["line2"] if name in line2_order},
    }


def to_config(model: dict) -> dict:
    segments = [name for name in model["order"] if name in model["enabled"]]
    line2 = [name for name in model["line2_order"] if name in model["line2"]]
    return {"segments": segments, "line2": line2, **{key: model[key] for key in SETTINGS}}


def dump_toml(cfg: dict) -> str:
    def value(v):
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, list):
            return "[" + ", ".join(f'"{x}"' for x in v) + "]"
        return f'"{v}"' if isinstance(v, str) else str(v)

    return "".join(f"{key} = {value(v)}\n" for key, v in cfg.items())


def dump_sections(configs: dict) -> str:
    """Write only what differs from the defaults, so later default changes still apply."""
    out = []
    for target, cfg in configs.items():
        # Compare with this tool's own defaults (Codex has no cost option to differ on).
        defaults = to_config(model_from(load_config("/nonexistent", target), target))
        changed = {key: value for key, value in cfg.items() if value != defaults.get(key)}
        out.append(f"[{target}]\n{dump_toml(changed)}")
    return "\n".join(out)


def row_count(model: dict) -> int:
    return len(model["order"]) + len(model["line2_order"]) + len(SETTINGS)


def apply(model: dict, row: int, key: str) -> int:
    """Apply one key press to the row under the cursor; returns the new cursor row."""
    rows = row_count(model)
    if key in ("up", "k"):
        return (row - 1) % rows
    if key in ("down", "j"):
        return (row + 1) % rows
    order, line2_order = model["order"], model["line2_order"]
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
    if row < len(order) + len(line2_order):
        if key in ("space", "left", "right"):
            model["line2"] ^= {line2_order[row - len(order)]}
        return row
    setting = SETTINGS[row - len(order) - len(line2_order)]
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
    for name in model["line2_order"]:
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


def sample_state(target: str = "codex") -> dict:
    now = time.time()
    state = {
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
    if target == "claude":
        state["cost"] = 1.84
    return state


def preview_lines(model: dict, target: str, width: int, ascii_only: bool) -> list[str]:
    """The bar as the tool would draw it, with tmux style markers kept for coloring."""
    cfg, state = to_config(model), sample_state(target)
    style = {"theme": cfg["theme"], "ascii_only": cfg["ascii"] or ascii_only, "tmux": True}
    first = render(
        state,
        width,
        segments=cfg["segments"],
        warn_at=cfg["warn_at"],
        crit_at=cfg["crit_at"],
        **style,
    )
    second = render_line2(state, width, cfg["line2"], **style)
    return [line for line in (first, second) if line]


_STYLED = re.compile(r"#\[fg=colour(\d+)\](.*?)#\[default\]")
# Nearest basic colors for terminals without 256-color support.
_BASIC = {33: 4, 25: 4, 75: 6, 172: 3, 220: 3, 130: 3, 160: 1, 196: 1, 114: 2}


def styled_parts(line: str) -> list[tuple[str, int | None]]:
    """Split renderer output into (text, 256-color number or None)."""
    parts, pos = [], 0
    for match in _STYLED.finditer(line):
        if match.start() > pos:
            parts.append((line[pos : match.start()], None))
        parts.append((match.group(2), int(match.group(1))))
        pos = match.end()
    if pos < len(line):
        parts.append((line[pos:], None))
    return parts


class _Palette:
    def __init__(self) -> None:
        self.pairs: dict[int, int] = {}
        self.enabled = curses.has_colors()
        if self.enabled:
            curses.start_color()
            try:
                curses.use_default_colors()
            except curses.error:
                pass

    def color(self, number: int | None) -> int:
        if not self.enabled or number is None:
            return curses.A_NORMAL
        if curses.COLORS < 256:
            number = _BASIC.get(number, 7)
        if number not in self.pairs:
            pair = len(self.pairs) + 1
            if pair >= curses.COLOR_PAIRS:
                return curses.A_NORMAL
            curses.init_pair(pair, number, -1)
            self.pairs[number] = pair
        return curses.color_pair(self.pairs[number])


def _put(screen, y: int, x: int, text: str, attr: int) -> int:
    height, width = screen.getmaxyx()
    if 0 <= y < height - 1 and x < width - 1:
        try:
            screen.addnstr(y, x, text, width - 1 - x, attr)
        except curses.error:
            pass  # tiny terminal: draw what fits
    return x + len(text)


def _ui(screen, models: dict, ascii_only: bool = False) -> bool:
    curses.curs_set(0)
    palette = _Palette()
    green = palette.color(114) | curses.A_BOLD
    bold, dim = curses.A_BOLD, curses.A_DIM
    arrow = ">" if ascii_only else "▶"
    help_text = HELP.replace("↑↓", "up/down").replace("←→", "left/right") if ascii_only else HELP
    tab, row = 0, 0
    while True:
        target = TARGETS[tab]
        model = models[target]
        row = min(row, row_count(model) - 1)
        screen.erase()
        width = screen.getmaxyx()[1]

        def put(y: int, x: int, text: str, attr: int = curses.A_NORMAL) -> int:
            return _put(screen, y, x, text, attr)

        put(1, 2, "codex-statusline config", bold)
        x = 2
        for i, name in enumerate(TARGETS):
            label = f" {TAB_NAMES[name]} "
            text = f"[{label}]" if i == tab else f" {label} "
            x = put(3, x, text, green if i == tab else dim) + 1
        put(3, x + 2, "Tab: switch", dim)

        put(5, 2, "Preview", bold)
        y = 6
        for line in preview_lines(model, target, max(20, width - 8), ascii_only):
            x = 4
            for text, color in styled_parts(line):
                x = put(y, x, text, palette.color(color))
            y += 1

        texts = rows_text(model)
        sections = [
            ("Line 1", len(model["order"])),
            ("Line 2", len(model["line2_order"])),
            ("Style", len(SETTINGS)),
        ]
        y += 1
        index = 0
        for title, count in sections:
            put(y, 2, title, bold)
            y += 1
            for _ in range(count):
                selected = index == row
                put(y, 2, arrow if selected else " ", green)
                put(y, 4, texts[index], green if selected else curses.A_NORMAL)
                index += 1
                y += 1
        put(y + 1, 2, help_text, dim)
        put(y + 2, 2, f"Saves to {config_path()}", dim)

        key = screen.getch()
        if key in (ord("\t"), curses.KEY_BTAB):
            tab = (tab + 1) % len(TARGETS)
            continue
        name = KEYS.get(key, chr(key) if 0 <= key < 256 else "")
        if name in ("q", "\x1b"):
            return False
        if name in ("s", "\n"):
            return True
        row = apply(model, row, name)


KEYS = {
    curses.KEY_UP: "up",
    curses.KEY_DOWN: "down",
    curses.KEY_LEFT: "left",
    curses.KEY_RIGHT: "right",
    ord(" "): "space",
}


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
    models = {target: model_from(load_config(target=target), target) for target in TARGETS}
    ascii_only = not utf8_terminal()
    try:
        save = curses.wrapper(_ui, models, ascii_only)
    except curses.error as error:
        print(f"codex-statusline: needs an interactive terminal ({error}).")
        print(f"Edit {config_path()} instead.")
        return 1
    if not save:
        print("No changes saved.")
        return 0
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_sections({t: to_config(m) for t, m in models.items()}))
    print(f"Saved {path}. Takes effect the next time you start codex or claude.")
    return 0
