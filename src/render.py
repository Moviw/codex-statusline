"""Safe, width-aware renderer for terminal and tmux status lines."""

from __future__ import annotations

import math
import os
import re
import sys
import tomllib
import unicodedata
from datetime import datetime
from itertools import combinations
from pathlib import Path
from typing import Any

DEFAULT_SEGMENTS = ["ctx", "5h", "week", "tokens"]
# tmux status-style per theme; "auto" keeps the terminal's own colors.
THEMES = {
    "auto": "bg=default,fg=default",
    "dark": "bg=#202431,fg=#d5dceb",
    "light": "bg=#f1f3f7,fg=#253047",
}
_PALETTES = {  # mid-tone colors for auto stay readable on white and black backgrounds
    "auto": {"accent": "colour33", "warning": "colour172", "critical": "colour160"},
    "dark": {"accent": "colour75", "warning": "colour220", "critical": "colour196"},
    "light": {"accent": "colour25", "warning": "colour130", "critical": "colour160"},
}
_CONFIG_DEFAULTS = {
    "update_check": True,
    "segments": DEFAULT_SEGMENTS,
    "theme": "auto",
    "ascii": False,
    "warn_at": 20,
    "crit_at": 5,
}


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "codex-statusline" / "config.toml"


def load_config(path: str | os.PathLike | None = None) -> dict[str, Any]:
    """Read $XDG_CONFIG_HOME/codex-statusline/config.toml; invalid values fall back to defaults."""
    if path is None:
        path = config_path()
    config = dict(_CONFIG_DEFAULTS)
    try:
        raw = tomllib.loads(Path(path).read_text())
    except FileNotFoundError:
        raw = {}
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        print(f"codex-statusline: ignoring config {path}: {error}", file=sys.stderr)
        raw = {}
    checks = {
        "segments": lambda v: (
            isinstance(v, list) and v and all(x in ("ctx", "5h", "week", "tokens") for x in v)
        ),
        "theme": lambda v: v in THEMES,
        "ascii": lambda v: isinstance(v, bool),
        "update_check": lambda v: isinstance(v, bool),
        "warn_at": lambda v: isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 100,
        "crit_at": lambda v: isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 100,
    }
    for key, value in raw.items():
        if key in checks and checks[key](value):
            config[key] = value
        else:
            print(
                f"codex-statusline: ignoring invalid config key {key!r}",
                file=sys.stderr,
            )
    # Existing env switches still win, so older installs behave the same.
    if os.environ.get("CODEX_STATUSLINE_THEME") in THEMES:
        config["theme"] = os.environ["CODEX_STATUSLINE_THEME"]
    if os.environ.get("CODEX_STATUSLINE_ASCII") == "1":
        config["ascii"] = True
    return config


_ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
_TMUX_STYLE_RE = re.compile(r"(?<!#)(?:##)*#\[[^\]]*\]")
_BIDI = {"RLE", "LRE", "RLO", "LRO", "PDF", "RLI", "LRI", "FSI", "PDI"}


def _char_width(ch: str) -> int:
    category = unicodedata.category(ch)
    if ch == "\u200d" or unicodedata.combining(ch) or category in {"Cf", "Cc", "Cs"}:
        return 0
    return 2 if unicodedata.east_asian_width(ch) in {"W", "F"} else 1


def visible_width(text: str) -> int:
    """Return terminal-cell width, ignoring ANSI, tmux styles, and ## escapes."""
    text = _ANSI_RE.sub("", str(text))
    text = _TMUX_STYLE_RE.sub("", text).replace("##", "#")
    return sum(_char_width(ch) for ch in text)


def _safe(value: Any, ascii_only: bool, tmux: bool) -> str:
    """Make state text printable; escape tmux syntax only when tmux is enabled."""
    text = _ANSI_RE.sub("", str(value))
    out: list[str] = []
    for ch in text:
        if unicodedata.category(ch) in {"Cc", "Cf", "Cs"} or unicodedata.bidirectional(ch) in _BIDI:
            continue
        out.append("?" if ascii_only and ord(ch) > 127 else ch)
    result = "".join(out)
    return result.replace("#", "##") if tmux else result


def _clip(text: str, width: int, ascii_only: bool = False) -> str:
    """Clip without splitting a doubled tmux hash escape."""
    if width <= 0:
        return ""
    if visible_width(text) <= width:
        return text
    marker, room, used, chunks = ("~" if ascii_only else "…"), width - 1, 0, []
    i = 0
    while i < len(text):
        if text.startswith("##", i):
            chunk, cells, i = "##", 1, i + 2
        else:
            chunk, cells, i = text[i], _char_width(text[i]), i + 1
        if used + cells > room:
            break
        chunks.append(chunk)
        used += cells
    return "".join(chunks) + marker


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _percent(value: Any) -> int | None:
    number = _number(value)
    return None if number is None else int(round(max(0.0, min(100.0, number))))


def _pct(value: Any) -> str:
    number = _percent(value)
    return "--" if number is None else f"{number}%"


def _bar(value: Any, slots: int, ascii_only: bool, *, left: bool = False) -> str:
    number = _percent(value)
    if number is None:
        symbol = "-" if ascii_only else "·"
        return symbol * slots
    ratio = number
    filled = round(ratio * slots / 100)
    if ascii_only:
        return "=" * filled + "-" * (slots - filled)
    return "█" * filled + "░" * (slots - filled)


def _reset(reset_at: Any, now: float, weekly: bool = False) -> str:
    stamp = _number(reset_at)
    if stamp is None:
        return "--"
    if stamp <= now:
        return ""  # window already reset; next reset is unknown until Codex reports again
    try:
        moment = datetime.fromtimestamp(stamp)
        time = moment.strftime("%I:%M%p").lstrip("0").lower()
        return f"{moment.strftime('%a ' if weekly else '')}{time}"
    except (OverflowError, OSError, ValueError):
        return "--"


def _quota_values(
    data: Any, now: float, weekly: bool, ascii_only: bool
) -> tuple[str, str, int | None]:
    label = "week" if weekly else "5h"
    if not isinstance(data, dict):
        return f"{label} --", f"{label} --", None
    # Past its reset time the window has rolled over: nothing seen since means full quota.
    remaining = 100 if _is_stale(data, now) else _percent(data.get("remaining"))
    left = "--" if remaining is None else f"{remaining}%"
    reset = _reset(data.get("reset_at"), now, weekly)
    compact = f"{label} {left}"
    bar = _bar(remaining, 10, ascii_only, left=True)
    detail = f"{label} {bar} {left} {reset}".rstrip()
    return detail, compact, remaining


def _context_role(value: Any) -> str:
    number = _percent(value)
    if number is not None and number >= 95:
        return "critical"
    if number is not None and number >= 80:
        return "warning"
    return "accent"


def _quota_role(value: int | None, warn_at: int = 20, crit_at: int = 5) -> str:
    if value is not None and value <= crit_at:
        return "critical"
    if value is not None and value <= warn_at:
        return "warning"
    return "accent"


def _tokens(value: Any) -> str:
    number = _number(value)
    if number is None or number < 0:
        return "tok --"
    for unit, size in (("B", 1e9), ("M", 1e6), ("k", 1e3)):
        if number >= size:
            return f"tok {number / size:.1f}{unit}"
    return f"tok {int(number)}"


def _paint(text: str, theme: str, role: str, tmux: bool) -> str:
    """Use only fixed, renderer-owned tmux style directives."""
    if not tmux:
        return text
    palette = _PALETTES.get(theme, _PALETTES["dark"])
    return f"#[fg={palette.get(role, palette['accent'])}]{text}#[default]"


def _is_stale(data: Any, now: float) -> bool:
    stamp = _number(data.get("reset_at")) if isinstance(data, dict) else None
    return stamp is not None and stamp <= now


def render(
    state: dict,
    width: int,
    theme: str = "dark",
    ascii_only: bool = False,
    tmux: bool = True,
    segments: list[str] | None = None,
    warn_at: int = 20,
    crit_at: int = 5,
) -> str:
    """Render an untrusted status snapshot to one line no wider than *width*."""
    width = max(0, int(width))
    if not width:
        return ""
    state = state if isinstance(state, dict) else {}
    now = _number(state.get("now"))
    if now is None:
        now = datetime.now().timestamp()
    theme = theme if theme in THEMES else "dark"

    context = state.get("context_used")
    context_text = f"  CTX USED {_bar(context, 8, ascii_only)} {_pct(context)}"
    context_compact = f"  CTX USED {_pct(context)}"

    quotas = state.get("quotas") if isinstance(state.get("quotas"), dict) else {}
    q5detail, q5compact, q5value = _quota_values(quotas.get("5h"), now, False, ascii_only)
    qwdetail, qwcompact, qwvalue = _quota_values(quotas.get("weekly"), now, True, ascii_only)
    tok = _tokens(state.get("tokens"))
    sep = " | "
    # Quotas are remaining percentages; expired windows read as full (see _quota_values).
    # Omit each segment as a whole rather than clipping it to a fragment.
    known = {  # name: (detail, compact, role)
        "ctx": (context_text, context_compact, _context_role(context)),
        "5h": (q5detail, q5compact, _quota_role(q5value, warn_at, crit_at)),
        "week": (qwdetail, qwcompact, _quota_role(qwvalue, warn_at, crit_at)),
        "tokens": (tok, tok, "accent"),
    }
    # Plans without a 5h (or weekly) limit report only the other window: hide the missing one.
    if (q5value is None) != (qwvalue is None):
        del known["5h" if q5value is None else "week"]
    parts = [known[name] for name in (segments or DEFAULT_SEGMENTS) if name in known] or [
        known["ctx"]
    ]
    update = state.get("update")
    hint = None
    if isinstance(update, str) and re.fullmatch(r"\d+(\.\d+)*", update):
        arrow = "^" if ascii_only else "↑"
        tool = "cxbar" if state.get("updater") == "cxbar" else "codex-statusline"
        hint = (f"{arrow} update available: {tool} update", f"{arrow} update", "warning")
    head, rest = parts[0], parts[1:]
    compact_head = (head[1], head[2])
    # Widest first: all detail, compact head, all compact, then drop segments.
    tiers: list[list[tuple[str, str]]] = []
    if hint:  # the update hint goes first whenever the bar gets tight
        tiers += [
            [(p[0], p[2]) for p in [*parts, hint]],
            [compact_head] + [(p[0], p[2]) for p in rest] + [(hint[0], hint[2])],
            [compact_head] + [(p[1], p[2]) for p in [*rest, hint]],
        ]
    tiers += [
        [(p[0], p[2]) for p in parts],
        [compact_head] + [(p[0], p[2]) for p in rest],
    ]
    for size in range(len(rest), -1, -1):
        for combo in combinations(rest, size):
            tiers.append([compact_head] + [(p[1], p[2]) for p in combo])
    chosen = tiers[-1]
    for tier in tiers:
        if visible_width(sep.join(part for part, _ in tier)) <= width:
            chosen = tier
            break

    plain = sep.join(part for part, _ in chosen)
    if visible_width(plain) > width:
        chosen = [(_clip(head[1], width, ascii_only), head[2])]

    out: list[str] = []
    for index, (part, role) in enumerate(chosen):
        if index:
            out.append(sep)
        out.append(_paint(part, theme, role, tmux))
    rendered = "".join(out)
    if visible_width(rendered) <= width:
        return rendered
    return _clip(sep.join(part for part, _ in chosen), width, ascii_only)
