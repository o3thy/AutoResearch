"""Project-local CLI entry point; no global skill installation required."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rr.cli import main

if __name__ == "__main__":
    main()
