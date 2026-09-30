#!/usr/bin/env python3
"""Absolute script entry for shell functions, hooks and private tmux panes."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
