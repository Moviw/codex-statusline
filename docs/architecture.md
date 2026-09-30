# How it works

## Why SessionStart alone is not enough

In isolated experiments with Codex 0.153.4 and 0.159.0, a new session runs its SessionStart hook only on the first user turn, and after `/clear` the previous session's hook data lingers until the next turn. SessionEnd is not an immediate switch signal either, so it cannot close that gap. ([official hook lifecycle](https://learn.chatgpt.com/docs/hooks#sessionend))

So each launch adds a per-invocation override to the official CLI (never written to `config.toml`):

```toml
[tui]
terminal_title = ["model", "context-used", "thread-id"]
```

The terminal title emitted by the TUI lands in the private tmux pane's `pane_title`. That is title metadata, not screen content. Context usage in the title resets immediately on `/clear`, so current context is never inferred from an old log.

Codex 0.159.0 truncates the thread UUID in the title to 29 characters plus `...`, so it is never treated as a full ID. The full UUID and the absolute rollout path come from the SessionStart hook, tagged with a unique launch ID. A log is read only when exactly one recorded binding of this launch matches; collisions, unknown formats, or no binding mean "unknown". The filesystem is never searched by prefix.

Upstream sources: [title definition](https://github.com/openai/codex/blob/rust-v0.159.0/codex-rs/tui/src/bottom_pane/title_setup.rs), [title rendering](https://github.com/openai/codex/blob/rust-v0.159.0/codex-rs/tui/src/chatwidget/status_surfaces.rs). This is a version-sensitive compatibility layer, not an official plugin API.

## Process and data flow

1. The shell function passes argv to Python untouched; non-interactive subcommands and redirected I/O `execv` straight into the official binary.
2. Python creates a 0700 private temp dir and tmux socket, verifies the host, then spawns exactly one official child.
3. The official CLI runs with `--no-daemon`, so the hook inherits this launch's private path and ID.
4. The hook exits immediately without a launch marker; with one, it checks directory permissions and the launch ID, then silently writes a 0600 binding file. It prints nothing into model context.
5. Every 0.5 s the monitor reads the title and incrementally reads the bound log. Only model / context / binding / quota / token-count metadata is kept; the parse buffer is bounded and no chat text is copied anywhere.
6. The tmux status is updated only when it changes. Exit, errors, and signals clean up the private server and state dir; an outer tmux is untouched.

Quotas are accepted only from `token_count` events whose window is exactly 300 or 10080 minutes, matched by `window_minutes` rather than by slot, since plans differ (Plus may report only the weekly window, in `primary`). Remaining = `100 - used_percent`, stamped with the event timestamp and `resets_at`. Quota is account-wide, so every 10 s the monitor also reads the three most recently written logs under `$CODEX_HOME/sessions` (same bounded, metadata-only parser) and keeps the newest snapshot per window. Once `resets_at` has passed with no newer snapshot, the window has rolled over and is shown as 100% with no reset time until Codex reports again. Session tokens are `info.total_token_usage.total_tokens` from the same events. Missing fields render as `--`; nothing is back-computed or estimated.

All state is stripped of control characters and escaped for tmux. Official args are passed as an argv array, never spliced into a shell string. The tmux status format uses `#{status-left}` and never recursively expands format commands found in state.

## Configuration transactions

Install shows a diff and asks before writing. Unrelated keys and hooks in `hooks.json` are preserved (JSON formatting may be normalized). If `config.toml` defines inline hooks (beyond trust state), install refuses to mix sources rather than migrating them silently.

Shell edits are tracked as whole marked blocks. Uninstall removes only blocks and hooks that still match the install manifest exactly; later user edits survive, and edited blocks or a missing manifest are never guessed at.

When installed with uv/pipx, hooks and shell functions call the tool's `codex-statusline` shim, which survives upgrades; a git checkout calls `python src/entry.py` instead.

No binary patching, no network quota adapter.
