"""Package entry point: ``python -m eval ...`` → ``run_all.cli()``."""
from __future__ import annotations

import sys

from eval.run_all import cli

if __name__ == "__main__":
    sys.exit(cli())
