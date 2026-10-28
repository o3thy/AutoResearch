import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
    from zotero.cli import main
except ModuleNotFoundError as exc:
    if exc.name != "pypdf":
        raise
    raise SystemExit("Install zotero/requirements.txt in the project .venv, then run .venv/Scripts/python zotero/scripts/zotero_workflow.py")

if __name__ == "__main__":
    main()
