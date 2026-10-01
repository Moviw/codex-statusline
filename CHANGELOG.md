# Changelog

## 0.4.2

- Fix: progress bars render in terminals whose locale is not UTF-8 (common over ssh); they showed as blanks or `~` in the bar and as `�` in `cxbar config`.
- Reset times always read like `6:05pm` / `Sat 6:05pm`, whatever the system language.

## 0.4.1

- The second line is on by default and shows token usage: `in 35.4k · 45% cached · out 26`.
- `pace` moves after `usage` and stays optional; turn it on in `cxbar config`.
- Dropped `ctx` from the second line (the first line already shows context).

## 0.4.0

- **Second line** (opt-in in `cxbar config`):
  - `pace`: when your 5h and weekly quota run out at the rate you have used them so far, or `lasts to reset`.
  - `usage`: tokens in, cache hit rate, tokens out, and context used out of the model's window.

  Example: `5h pace: runs out ~4:17pm | week pace: lasts to reset | in 18.8M · 97% cached · out 66.1k · ctx 138.0k/258.4k`
- Config key `line2 = ["pace", "usage"]` for the same thing by hand.

## 0.3.1

- `cxbar doctor` is a checklist with the fix for each problem: Codex and tmux versions, whether `codex` runs this copy, whether Codex approved the hook, and whether an update is out.
- Esc reaches Codex instantly (was delayed by half a second) and Ctrl-B works inside Codex.
- `cxbar -V` / `-v` print the version.
- The bar no longer polls git every few seconds.

## 0.3.0

A big one. Highlights since 0.1:

- **`cxbar`**: a short command for everything besides `codex` itself: `cxbar config`, `cxbar update`, `cxbar doctor`. `codex-statusline` keeps working.
- **`cxbar config`**: choose segments and their order, theme, color thresholds, and the update notice in an interactive screen with a live preview.
- **Smooth scrolling**: the mouse wheel scrolls the conversation exactly like plain Codex.
- **Update notice**: every `codex` launch checks for a new release in the background and the bar shows `↑ update available: cxbar update`; one command upgrades, whichever way you installed.
- **Quota from the first frame**, refreshed to 100% the moment a window resets, read from the freshest of your local Codex sessions.
- **Every plan**: weekly-only plans show just the weekly window.
- **Follows your terminal**: the default `auto` theme fits light and dark backgrounds.
- **Friendlier install**: a short summary of which files change (`--diff` for details), and installing from a new path replaces the old install in one step.

## 0.2.2

- Clearer `codex-statusline --help`: one line per command.
- Update notice reads `↑ update available: codex-statusline update` (`↑ update` on narrow terminals).
- Removed the `preview` command; `codex-statusline config` shows a live preview.

## 0.2.1

- Fix: the mouse wheel scrolls the conversation again, just like plain Codex, instead of recalling earlier prompts.
- `codex-statusline config`: pick segments and their order, theme, thresholds, and the update notice in an interactive screen with a live preview. No more hand-editing config.toml.
- Install and uninstall print a short summary of which files change; `--diff` shows the exact changes. The prompt now defaults to yes.
- Installing from a new path (e.g. moving from a local checkout to uv/pipx) replaces the previous install in one step.
- `codex-statusline update` always fetches the latest release from PyPI, including tools first installed from a local checkout.

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
