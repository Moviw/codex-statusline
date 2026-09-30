# Contributing

Issues and PRs welcome. For bugs, include `codex-statusline doctor` output.

```sh
git clone https://github.com/Moviw/codex-statusline && cd codex-statusline
python3 -m unittest discover -s tests -v   # Python 3.11+, needs tmux
python3 run.py preview --demo --width 80
uvx ruff format . && uvx ruff check .   # style, enforced in CI
```

No runtime dependencies beyond the standard library; please keep it that way. Keep changes small and add a test for new behavior.
