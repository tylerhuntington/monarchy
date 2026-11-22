#!/usr/bin/env python3
"""Optional Secretary Stop hook; never installs itself or launches a session."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from monarchy.rearm import main


if __name__ == '__main__':
    sys.exit(main())
