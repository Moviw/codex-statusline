# codex-statusline

**See your Codex context and quota at a glance.**

[![tests](https://github.com/Moviw/codex-statusline/actions/workflows/tests.yml/badge.svg)](https://github.com/Moviw/codex-statusline/actions/workflows/tests.yml)
[![PyPI](https://img.shields.io/pypi/v/codex-statusline)](https://pypi.org/project/codex-statusline/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

English | [简体中文](README.zh-CN.md)

A status bar for [OpenAI Codex CLI](https://github.com/openai/codex). It shows context used, 5-hour and weekly quota left with reset times, and session tokens. You keep running `codex` exactly as before.

![codex-statusline demo](docs/preview.svg)

```text
CTX USED ███░░░░░ 35% | 5h ████████░░ 78% 5:41pm | week ████░░░░░░ 39% Fri 3:41pm | tok 1.2M
```

## Why

- **No more `/status` interruptions.** Quota and context sit in view while you work.
- **Local only.** Never reads `auth.json`, never calls a quota API, never makes extra model calls.
- **Zero new habits.** Keep typing `codex`. `codex exec`, pipes, and scripts pass straight through to the official binary.
- **Honest numbers.** Unknown shows as `--` and stale quota shows as `refresh`. A missing value is never passed off as 0% or 100%.
- **Fits any width.** Segments collapse, then drop, as the terminal narrows.

## Install

Requires macOS or Linux, [tmux](https://github.com/tmux/tmux), and Codex CLI ≥ 0.159.0. Bash, Zsh, and Fish are all detected automatically.

```sh
curl -fsSL https://raw.githubusercontent.com/Moviw/codex-statusline/main/install.sh | sh
```

The script installs [uv](https://docs.astral.sh/uv/) if needed (uv also fetches Python 3.11+ for you), installs the tool, then shows you the exact shell/hook diff and asks before writing anything.

Prefer to do it yourself:

```sh
uv tool install codex-statusline    # or: pipx install codex-statusline
codex-statusline install            # add --dry-run to only preview the diff
```

Then **open a new terminal** and run `codex`. The first time, Codex asks you to review a hook: confirm it is `codex-statusline binding`.

Missing tmux? `brew install tmux` or `sudo apt install tmux`.

## Usage

```sh
codex                     # same as always, now with a status bar
codex resume --last
codex exec 'task'         # non-interactive: passed straight through, no bar

codex-statusline doctor   # check versions and dependencies
codex-statusline preview --demo --width 80   # try it without launching Codex
codex-statusline uninstall
```

Uninstall removes only what this tool added and still matches exactly. If you edited its block, it stops instead of overwriting. Backups live in `~/.local/share/codex-statusline/`.

## Configuration

Optional. Create `~/.config/codex-statusline/config.toml`:

```toml
segments = ["ctx", "5h", "week", "tokens"]  # pick and reorder
theme = "dark"     # dark | light
ascii = false      # true for terminals without block glyphs
warn_at = 20       # quota remaining % that turns yellow
crit_at = 5        # quota remaining % that turns red
```

Invalid values are reported and fall back to defaults.

## How it works

`codex` becomes a small shell function that starts the official CLI inside a private tmux session and draws the bar at the bottom. Data comes from two places only: the terminal title Codex already emits (model, context, thread id), and the rollout log of *this* session, which a SessionStart hook pins by exact path. The official binary is not replaced or patched, and your tmux config is not touched. Details: [docs/architecture.md](docs/architecture.md).

## FAQ

**How do I scroll or copy?** It runs inside tmux: press `Ctrl-B` then `[` to scroll and copy. The mouse wheel may behave differently from bare Codex.

**Windows?** Not supported (tmux).

**Is this official?** No. It is a third-party tool built on a version-sensitive integration.
