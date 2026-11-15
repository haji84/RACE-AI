"""Consume local video; --connect-models records private research connections."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from race_ai.boat_video_intake import main


if __name__ == "__main__":
    raise SystemExit(main())
