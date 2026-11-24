#!/usr/bin/env python3
"""Scryfall bulk sync / price refresh.

    python scripts/sync_scryfall.py sync                      # full default_cards (~110k printings)
    python scripts/sync_scryfall.py sync --recent-sets 24     # quick test DB
    python scripts/sync_scryfall.py sync --source all_cards --langs en,es
    python scripts/sync_scryfall.py prices                    # daily price refresh
"""
import sys

import _bootstrap  # noqa: F401
from scanner.scryfall_sync import main

if __name__ == "__main__":
    sys.exit(main())
