"""Bounded parsers for Codex native title and explicitly selected session logs.

This module deliberately does not discover log files.  Callers must provide the
path for the session they already bound to the UI.
"""

from __future__ import annotations

import json
import math
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SESSION_HINT = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{5}\.\.\.$"
)
_FULL_SESSION = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_CONTEXT = re.compile(r"^Context ([0-9]+(?:\.[0-9]+)?)% used$")
_MAX_READ_BYTES = 1024 * 1024


def parse_title(title: str) -> dict[str, Any]:
    """Parse Codex's native ``[model, context-used, thread-id]`` title.

    The emitted thread ID is a UUID shortened to its first 29 characters and
    ``...``.  A full UUID is also accepted for environments that render it
    without truncation.  A two-field ``model | session`` title is a valid
    context-less variant; its context is returned as ``None``.  Malformed or
    ambiguous titles raise ``ValueError`` rather than guessing.
    """
    if not isinstance(title, str):
        raise TypeError("title must be a string")
    parts = [part.strip() for part in title.split("|")]
    if len(parts) not in (2, 3) or not parts[0]:
        raise ValueError("not a supported Codex status title")

    session_hint = re.sub(
        r" [\u2800-\u28ff]$", "", parts[-1]
    )  # native thread-title progress spinner
    if not (_SESSION_HINT.fullmatch(session_hint) or _FULL_SESSION.fullmatch(session_hint)):
        raise ValueError("title does not end in a recognizable thread ID")

    context_used: float | None = None
    if len(parts) == 3:
        match = _CONTEXT.fullmatch(parts[1])
        if match:
            parsed_context = float(match.group(1))
            if math.isfinite(parsed_context) and 0.0 <= parsed_context <= 100.0:
                context_used = parsed_context
        elif parts[1] not in ("Context unknown", ""):
            raise ValueError("unrecognized context field")

    return {
        "model": parts[0],
        "context_used": context_used,
        "session_hint": session_hint,
    }


USAGE_KEYS = ("input_tokens", "cached_input_tokens", "output_tokens")


def _count(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _timestamp(value: Any) -> float | None:
    """Convert supported event timestamps to Unix seconds without guessing."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return None
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.timestamp()
        return number if math.isfinite(number) else None
    return None


def _empty_quotas() -> dict[str, dict[str, float | None]]:
    return {
        "5h": {"remaining": None, "reset_at": None, "observed_at": None},
        "weekly": {"remaining": None, "reset_at": None, "observed_at": None},
    }


class LogReader:
    """Incrementally read quota metadata from one caller-selected JSONL file.

    Each update reads at most 1 MiB.  Only complete JSONL records are parsed;
    an incomplete tail is held up to 1 MiB, then discarded through its newline.
    State is reset on path changes, file rotation, or truncation. Persistent
    state is quota metadata only; bounded transient input can include arbitrary
    JSON fields while parsed, but content is not copied into reader state/results.
    """

    def __init__(self) -> None:
        self._path: str | None = None
        self._identity: tuple[int, int] | None = None
        self._offset = 0
        self._partial = b""
        self._discard_until_newline = False
        self._probe = b""
        self._quotas = _empty_quotas()
        self._tokens: float | None = None
        self._usage: dict[str, float] | None = None

    def _reset(self, path: str) -> None:
        self._path = path
        self._identity = None
        self._offset = 0
        self._partial = b""
        self._discard_until_newline = False
        self._probe = b""
        self._quotas = _empty_quotas()
        self._tokens = None
        self._usage = None

    def _consume_line(self, line: bytes) -> None:
        try:
            event = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(event, dict) or event.get("type") != "event_msg":
            return
        observed_at = _timestamp(event.get("timestamp"))
        if observed_at is None:
            return
        payload = event.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != "token_count":
            return
        info = payload.get("info")
        total = info.get("total_token_usage") if isinstance(info, dict) else None
        tokens = total.get("total_tokens") if isinstance(total, dict) else None
        if _count(tokens):
            self._tokens = float(tokens)
        if isinstance(total, dict):
            usage = {key: total.get(key) for key in USAGE_KEYS}
            if all(_count(v) for v in usage.values()):
                self._usage = {key: float(v) for key, v in usage.items()}
        # Native versions may keep rate_limits inside info; quota-only events
        # can instead carry rate_limits directly on payload (even if info is null).
        rate_limits = info.get("rate_limits") if isinstance(info, dict) else None
        if not isinstance(rate_limits, dict):
            rate_limits = payload.get("rate_limits")
        if not isinstance(rate_limits, dict):
            return

        # Slots vary by plan (e.g. Plus may carry only the weekly window in "primary"),
        # so identify each quota by its window length, not by its key.
        windows = {300: "5h", 10080: "weekly"}
        for key in ("primary", "secondary"):
            quota = rate_limits.get(key)
            label = windows.get(quota.get("window_minutes")) if isinstance(quota, dict) else None
            if label is None:
                continue
            used = quota.get("used_percent")
            if isinstance(used, bool) or not isinstance(used, (int, float)):
                continue
            used = float(used)
            if not math.isfinite(used):
                continue
            prior = self._quotas[label]
            if prior["observed_at"] is not None and observed_at < float(prior["observed_at"]):
                continue
            reset_at = _timestamp(quota.get("resets_at"))
            self._quotas[label] = {
                "remaining": max(0.0, min(100.0, 100.0 - used)),
                "reset_at": reset_at,
                "observed_at": observed_at,
            }

    def _consume_bytes(self, data: bytes) -> None:
        if self._discard_until_newline:
            newline = data.find(b"\n")
            if newline < 0:
                return
            self._discard_until_newline = False
            data = data[newline + 1 :]
        data = self._partial + data
        lines = data.split(b"\n")
        tail = lines.pop()  # last record is parsed only once terminated
        for line in lines:
            if line:
                self._consume_line(line)
        if len(tail) >= _MAX_READ_BYTES:
            self._partial = b""
            self._discard_until_newline = True
        else:
            self._partial = tail

    def update(self, path: str) -> dict[str, Any]:
        """Read newly appended quota/token events from exactly ``path``."""
        if not isinstance(path, str) or not path:
            raise ValueError("path must be a non-empty string")
        if self._path != path:
            self._reset(path)

        try:
            stat = os.stat(path)
            identity = (stat.st_dev, stat.st_ino)
            skip_partial_record = False
            overwritten = False
            if (
                identity == self._identity
                and self._identity is not None
                and self._probe
                and stat.st_size >= self._offset
            ):
                with open(path, "rb") as probe_stream:
                    probe_stream.seek(self._offset - len(self._probe))
                    overwritten = probe_stream.read(len(self._probe)) != self._probe
            if identity != self._identity or stat.st_size < self._offset or overwritten:
                self._identity = identity
                self._offset = 0
                self._partial = b""
                self._discard_until_newline = False
                self._probe = b""
                self._quotas = _empty_quotas()
                self._tokens = None
                self._usage = None
                if stat.st_size > _MAX_READ_BYTES:
                    # Start at a bounded tail boundary, discarding its possibly
                    # incomplete first line.  Current quota events remain
                    # available without reading an arbitrarily large history.
                    self._offset = stat.st_size - _MAX_READ_BYTES
                    skip_partial_record = True
            with open(path, "rb") as stream:
                stream.seek(self._offset)
                chunk = stream.read(_MAX_READ_BYTES)
                self._offset = stream.tell()
            if chunk:
                self._probe = chunk[-64:]
            if skip_partial_record:
                # Initial tail read: do not interpret a fragment cut from the
                # front of a JSON record.
                newline = chunk.find(b"\n")
                if newline < 0:
                    self._partial = b""
                    self._discard_until_newline = True
                else:
                    chunk = chunk[newline + 1 :]
                self._consume_bytes(chunk)
            else:
                self._consume_bytes(chunk)
        except FileNotFoundError:
            # A missing bound file has no metadata yet.  Retain the selected
            # path, but a later appearance will be picked up by identity reset.
            self._identity = None
            self._offset = 0
            self._partial = b""
            self._discard_until_newline = False
            self._probe = b""
            self._quotas = _empty_quotas()
            self._tokens = None
            self._usage = None
        except OSError:
            # Avoid exporting filesystem details or turning transient I/O into
            # fabricated quota data; previously observed metadata remains.
            pass
        return {
            "quotas": {name: dict(value) for name, value in self._quotas.items()},
            "tokens": self._tokens,
            "usage": dict(self._usage) if self._usage else None,
        }


def merge_quotas(*snapshots: dict[str, Any]) -> dict[str, Any]:
    """Quotas are account-wide: per window, keep the most recently observed snapshot."""
    merged: dict[str, Any] = {}
    for snapshot in snapshots:
        for label, quota in (snapshot or {}).items():
            seen = quota.get("observed_at") if isinstance(quota, dict) else None
            if seen is None:
                continue
            if label not in merged or seen > merged[label]["observed_at"]:
                merged[label] = quota
    return merged


def sessions_dir() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "sessions"


def newest_quotas(sessions: Path, readers: dict[str, LogReader], limit: int = 10) -> dict[str, Any]:
    """Freshest quotas from local session logs, newest first, stopping once both windows are seen.

    Sessions opened without a single turn carry no quota, so look past them.
    """
    found = []
    try:
        for path in sessions.glob("*/*/*/*.jsonl"):
            try:
                found.append((path.stat().st_mtime, str(path)))
            except OSError:
                continue
    except OSError:
        return {}
    merged: dict[str, Any] = {}
    scanned = []
    for _, path in sorted(found, reverse=True)[:limit]:
        scanned.append(path)
        merged = merge_quotas(merged, readers.setdefault(path, LogReader()).update(path)["quotas"])
        if {"5h", "weekly"} <= merged.keys():
            break
    for stale in set(readers) - set(scanned):
        del readers[stale]
    return merged
