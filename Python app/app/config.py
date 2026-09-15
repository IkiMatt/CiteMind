import sys
from pathlib import Path

if getattr(sys, 'frozen', False):
    # Running as a compiled .exe
    BASE_DIR = Path(sys.executable).parent
else:
    # Running as a normal script
    BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_DB_PATH  = BASE_DIR / "bibliography.db"
