"""Silent SessionStart metadata recorder; no credentials or conversation copies."""

import fcntl
import json
import os
import stat
import sys
import tempfile
import time
import uuid
from pathlib import Path


def atomic_json(path, data):
    fd, temp = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def record():
    directory = os.environ.get("CODEX_STATUSLINE_STATE")
    launch = os.environ.get("CODEX_STATUSLINE_LAUNCH")
    if not directory or not launch:
        return  # Do not even read stdin for ordinary Codex sessions.
    try:
        uuid.UUID(launch)
        root = Path(directory)
        info = root.lstat()
        if (
            not root.is_absolute()
            or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
        ):
            return
        config = json.loads((root / "launch.json").read_text())
        if config["launch_id"] != launch:
            return
        raw = sys.stdin.buffer.read(65537)
        if len(raw) > 65536:
            return
        event = json.loads(raw)
        if event.get("hook_event_name") != "SessionStart":
            return
        sid = str(uuid.UUID(event["session_id"]))
        transcript = event.get("transcript_path")
        if not isinstance(transcript, str) or not Path(transcript).is_absolute():
            return
        binding = {k: event.get(k) for k in ("cwd", "model", "source")}
        binding.update(
            session_id=sid,
            transcript_path=transcript,
            launch_id=launch,
            recorded_at=time.time(),
        )
        # Keep exact bindings for switching back to a still-open thread. Never scan logs.
        with (root / "lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                bindings = json.loads((root / "bindings.json").read_text())
            except (OSError, ValueError):
                bindings = {}
            bindings[sid] = binding
            if len(bindings) > 64:
                bindings = dict(
                    sorted(bindings.items(), key=lambda item: item[1]["recorded_at"])[-64:]
                )
            atomic_json(root / "bindings.json", bindings)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return
