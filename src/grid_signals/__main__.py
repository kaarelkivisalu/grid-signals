"""Allow running as `python -m grid_signals`."""

import sys

from grid_signals.cli import main

if __name__ == "__main__":
    sys.exit(main())
