"""Run from a git checkout or package with PyInstaller."""
from pathlib import Path
import sys

if getattr(sys, "frozen", False):
    # PyInstaller packages this path through --paths src.
    pass
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from v3nl.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
