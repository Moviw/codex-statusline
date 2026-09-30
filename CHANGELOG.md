# Changelog

## 0.1.3

- Quota appears on the very first frame when `codex` starts, read from your local Codex sessions.
- Quota lookup looks past recent sessions that were opened without any turn.

## 0.1.2

- Plans that report only one quota window (e.g. weekly only) now show just that window instead of a permanent `5h --`.

## 0.1.1

- Expired quota windows show 100% the moment they reset, instead of the old value with `refresh`.
- Quota is taken from the freshest reading across recent local Codex sessions, so it shows up before the first turn too.
- Fix plans that report only the weekly window (e.g. Plus) showing `5h -- | week --`.
- New default theme `auto`: the bar follows the terminal's own background (light or dark).
- Fix `theme = "light"` in config.toml changing text colors but keeping the dark bar.
- `install.sh` offers to install tmux with Homebrew on macOS.
- Update notice: each `codex` launch checks PyPI in the background; the bar shows `↑ x.y.z run: codex-statusline update`. New `codex-statusline update` upgrades via uv, pipx, pip, or git, whichever installed it. Opt out with `update_check = false`.

## 0.1.0

First public release.

- Status bar under the official Codex TUI: context used, 5h and weekly quota left with reset times, session tokens.
- One-line installer (`install.sh`), `uv tool install` / `pipx install` from PyPI.
- Optional `~/.config/codex-statusline/config.toml`: segments and order, theme, ascii, warning thresholds.
- Diff-first install and exact-match uninstall for Bash, Zsh, and Fish.
