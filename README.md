# codex-statusline

**See your Codex and Claude Code context and quota at a glance.**

[![tests](https://github.com/Moviw/codex-statusline/actions/workflows/tests.yml/badge.svg)](https://github.com/Moviw/codex-statusline/actions/workflows/tests.yml)
[![PyPI](https://img.shields.io/pypi/v/codex-statusline?label=PyPI)](https://pypi.org/project/codex-statusline/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

English | [简体中文](README.zh-CN.md)

A status bar for [OpenAI Codex CLI](https://github.com/openai/codex) and [Claude Code](https://code.claude.com). It shows context used, 5-hour and weekly quota left with reset times, and session tokens. You keep running `codex` and `claude` exactly as before.

![codex-statusline demo](docs/demo.gif)


## Why

- **No more `/status` interruptions.** Quota and context sit in view while you work.
- **Local data only.** Never reads `auth.json`, never calls a quota API, never makes extra model calls. The one network request is a version check against PyPI when `codex` starts (turn off with `update_check = false`).
- **Zero new habits.** Keep typing `codex`. `codex exec`, pipes, and scripts pass straight through to the official binary.
- **Always current.** Quota is account-wide, so the freshest reading from any of your local Codex sessions is shown, and the bar flips to 100% the moment a window resets. Unknown shows as `--`, never a made-up number.
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
cxbar install                       # add --dry-run to see the plan first
```

Then **open a new terminal** and run `codex`. The first time, Codex asks you to review a hook: confirm it is `codex-statusline binding`.

Missing tmux? `brew install tmux` or `sudo apt install tmux`.

## Claude Code

The same bar works in [Claude Code](https://code.claude.com/docs/en/statusline): `cxbar install` sets it as Claude Code's `statusLine` when it finds `~/.claude`, so `claude` shows the same two lines, plus the session cost:

```text
CTX USED ███░░░░░ 35% | 5h ██░░░░░░░░ 18% 3:46pm | week ██████░░░░ 62% Sat 1:46pm | tok 1.2M
in 1.2M · 94% cached · out 44.0k · ≈$1.84
```

- **Keeps what you have.** Already using another statusLine? Install leaves it alone; `cxbar install --claude` switches, and `cxbar uninstall` puts yours back.
- **No tmux needed** on the Claude side: Claude Code passes the numbers to the bar directly.
- **Every account.** Pro and Max see 5h and weekly quota with reset times; API-key users see context, tokens, and cost.
- **One config.** `cxbar config` changes the bar in both tools.

## Usage

```sh
codex                     # same as always, now with a status bar
codex resume --last
codex exec 'task'         # non-interactive: passed straight through, no bar

cxbar config              # pick segments, theme and colors interactively
cxbar update              # upgrade, whichever way you installed it
cxbar update --check      # only check whether a new release is out
cxbar doctor              # check your setup; prints the fix for anything wrong
cxbar uninstall
```

`cxbar` is the short name for `codex-statusline`; both work.

Uninstall removes only what this tool added and still matches exactly. If you edited its block, it stops instead of overwriting. Backups live in `~/.local/share/codex-statusline/`.

## Configuration

Run `cxbar config` to set everything up in an interactive screen with a live, colored preview. Codex and Claude Code each get their own tab (press Tab to switch), so the two bars can look different: toggle and reorder segments, choose what the second line shows, switch theme, set the warning thresholds, then press `s` to save.

```text
  codex-statusline config

  [ Codex ]   Claude Code      Tab: switch

  Preview
    CTX USED ███░░░░░ 35% | 5h ██░░░░░░░░ 18% 3:46pm | week ██████░░░░ 62% Sat 1:46pm | tok 1.2M
    in 1.2M · 94% cached · out 44.0k

  Line 1
▶ [x] ctx     context used
  [x] 5h      5-hour quota
  [x] week    weekly quota
  [x] tokens  session tokens
  Line 2
  [x] usage   tokens in / cached / out
  [ ] pace    when quota runs out at this pace
  Style
  Theme            < auto >
  ASCII only       [ ]
  Quota yellow at  < 40% >
  Quota red at     < 20% >
  Update notice    [x]
```

The second line has three parts:

- `usage` (on by default): tokens sent, how much of that hit the cache, and tokens generated.
- `cost` (on by default): the session's estimated cost at list price. Claude Code only.
- `pace` (off by default): when your 5h and weekly quota run out at the rate you have used them so far, e.g. `week pace: runs out ~Tue 1:27am`, or `lasts to reset`.

Turn them all off to keep a single line.

It writes `~/.config/codex-statusline/config.toml`, which you can also edit by hand:

```toml
# Top-level keys apply to both tools; [codex] and [claude] override them per tool.
segments = ["ctx", "5h", "week", "tokens"]  # pick and reorder
theme = "auto"     # auto (follow terminal) | dark | light
ascii = false      # true for terminals without block glyphs
warn_at = 40       # quota remaining % that turns yellow
crit_at = 20       # quota remaining % that turns red
update_check = true  # show "↑ update available" in the bar when one is out
line2 = ["usage", "cost"]  # second line: any of "usage", "cost", "pace"; [] for none

[claude]
line2 = ["usage", "cost", "pace"]  # e.g. pace only in Claude Code
```

Context turns yellow from 60% used and red from 80%.

Invalid values are reported and fall back to defaults.

## How it works

`codex` becomes a small shell function that starts the official CLI inside a private tmux session and draws the bar at the bottom. Data comes from two places only: the terminal title Codex already emits (model, context, thread id), and local Codex session logs: this session's log (pinned by exact path through a SessionStart hook) for context and tokens, plus the most recent local logs for account-wide quota. Only quota and token counters are read, never chat text. The official binary is not replaced or patched, and your tmux config is not touched. Details: [docs/architecture.md](docs/architecture.md).

## FAQ

**How do I scroll or copy?** Exactly as in plain Codex: the mouse wheel scrolls the conversation, and text selection works the same way.

**Windows?** Not supported (tmux).

**Is this official?** No. It is a third-party tool built on a version-sensitive integration.
