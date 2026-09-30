#!/bin/sh
# One-line installer: curl -fsSL https://raw.githubusercontent.com/Moviw/codex-statusline/main/install.sh | sh
# Extra args go to `codex-statusline install`, e.g. `| sh -s -- --yes`.
set -eu

say() { printf 'codex-statusline: %s\n' "$*"; }

if ! command -v tmux >/dev/null 2>&1; then
    # Offer brew on macOS (no sudo needed); never escalate to root on Linux.
    if [ "$(uname)" = Darwin ] && command -v brew >/dev/null 2>&1 && [ -r /dev/tty ]; then
        printf 'codex-statusline: tmux is required. Install it with Homebrew now? [Y/n] '
        read -r answer </dev/tty || answer=n
        case "$answer" in
            ''|y|Y|yes) brew install tmux ;;
        esac
    fi
fi
if ! command -v tmux >/dev/null 2>&1; then
    say 'tmux is required. Install it first:'
    say '  macOS:          brew install tmux'
    say '  Debian/Ubuntu:  sudo apt install tmux'
    exit 1
fi
command -v codex >/dev/null 2>&1 || say 'warning: codex not found on PATH; install Codex CLI before running codex.'

if ! command -v uv >/dev/null 2>&1; then
    say 'installing uv (https://astral.sh/uv) ...'
    curl -LsSf https://astral.sh/uv/install.sh | sh
    PATH="$HOME/.local/bin:$PATH"
fi

# uv fetches Python 3.11+ itself if the system one is older.
uv tool install --upgrade --python '>=3.11' codex-statusline
BIN="$(uv tool dir --bin)/codex-statusline"

# stdin is this script when piped; read the confirmation from the terminal.
if [ -r /dev/tty ]; then
    "$BIN" install "$@" </dev/tty
else
    "$BIN" install "$@"
fi
