#!/usr/bin/env python3
"""Entry point: ``python scripts/pe.py <command> ...`` (no install needed)."""

import sys

if sys.version_info < (3, 10):
    sys.exit("paraphrase-anything requires Python 3.10 or newer")

from paraphrase_everything.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
