"""Load the unchanged v1.0.0 benchmark bundled in base/."""
import sys
from pathlib import Path
BASE = Path(__file__).resolve().parent / 'base'
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
