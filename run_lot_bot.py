#!/usr/bin/env python3
"""Arranque de LOT Bot durante el desarrollo.

Uso:  python run_lot_bot.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lot_bot.app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
