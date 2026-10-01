"""`cxbar claude`: the Claude Code statusLine command.

Claude Code runs it on each update with session JSON on stdin; we print the same two lines
as the Codex bar, in ANSI colors. Nothing is read besides that JSON and our own config.
"""

import json
import os
import re
import sys
import time
from typing import Any

from .git import git_status
from .render import load_config, render, render_line2
from .update import cached_newer_version


def _num(value: Any) -> float | None:
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0
    return float(value) if ok else None


def state_from(data: dict, now: float) -> dict:
    window = data.get("context_window") if isinstance(data.get("context_window"), dict) else {}
    limits = data.get("rate_limits") if isinstance(data.get("rate_limits"), dict) else {}
    cost = data.get("cost") if isinstance(data.get("cost"), dict) else {}
    state: dict[str, Any] = {
        "now": now,
        "context_used": _num(window.get("used_percentage")),
        "quota_optional": True,  # only subscriptions report rate limits
    }

    quotas = {}
    for key, label in (("five_hour", "5h"), ("seven_day", "weekly")):
        q = limits.get(key) if isinstance(limits.get(key), dict) else {}
        used = _num(q.get("used_percentage"))
        if used is not None:
            quotas[label] = {
                "remaining": max(0.0, 100.0 - used),
                "reset_at": _num(q.get("resets_at")),
                "observed_at": now,
            }
    state["quotas"] = quotas

    given, output = _num(window.get("total_input_tokens")), _num(window.get("total_output_tokens"))
    if given is not None and output is not None:
        state["tokens"] = given + output
        # Claude reports the cache split for the latest request only; use it as the hit rate.
        last = window.get("current_usage") if isinstance(window.get("current_usage"), dict) else {}
        keys = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
        parts = [_num(last.get(k)) or 0.0 for k in keys]
        state["usage"] = {
            "input_tokens": given,
            "cached_input_tokens": given * parts[1] / sum(parts) if sum(parts) else None,
            "output_tokens": output,
        }
    state["cost"] = _num(cost.get("total_cost_usd"))
    return state


def terminal_width() -> int:
    # stdin/stdout are pipes here; the controlling terminal still knows its size.
    try:
        with open("/dev/tty") as tty:
            return os.get_terminal_size(tty.fileno()).columns
    except OSError:
        pass
    try:
        return int(os.environ["COLUMNS"])
    except (KeyError, ValueError):
        return 120


def statusline(stream=None) -> int:
    try:
        data = json.loads((stream or sys.stdin).read(1 << 20) or "{}")
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    cfg = load_config(target="claude")
    state = state_from(data, time.time())
    if cfg["update_check"]:
        state["update"], state["updater"] = cached_newer_version(), "cxbar"
    if "git" in cfg["line2"]:
        workspace = data.get("workspace") if isinstance(data.get("workspace"), dict) else {}
        cwd = workspace.get("current_dir") or data.get("cwd")
        if isinstance(cwd, str) and cwd:
            state["git"] = git_status(cwd)
    width = max(20, terminal_width() - 4)  # Claude indents the status line a little
    style = {"theme": cfg["theme"], "ascii_only": cfg["ascii"], "tmux": False, "ansi": True}
    lines = [
        render(
            state,
            width,
            segments=cfg["segments"],
            warn_at=cfg["warn_at"],
            crit_at=cfg["crit_at"],
            **style,
        ),
        render_line2(state, width, cfg["line2"], **style),
    ]
    # Claude Code already indents the first row by two columns; drop ours there so rows align.
    lines[0] = re.sub(r"^((?:\x1b\[[0-9;]*m)*)  ", r"\1", lines[0], count=1)
    print("\n".join(line for line in lines if line))
    return 0
