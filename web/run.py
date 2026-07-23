#!/usr/bin/env python3
"""WSGI entry point for LANaxy.

Production startup is handled by Gunicorn through lanaxy-web.service. Keeping
this small module allows other WSGI servers and diagnostic imports to use the
same stable ``web.run:app`` target without starting Flask's development server.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from web.app import app  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(
        "LANaxy wird produktiv über Gunicorn gestartet. "
        "Verwende: systemctl start lanaxy-web.service"
    )
