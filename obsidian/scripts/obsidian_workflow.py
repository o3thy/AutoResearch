"""Run the third workflow stage from the project root."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from obsidian.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
