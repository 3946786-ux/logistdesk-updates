"""Safe isolated entrypoint for LogistDesk 2.1 alpha Windows testing only.

Do NOT let a preview executable open or migrate the stable production profile.
Real 2.1 production release will use the normal app20.py entrypoint after QA.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

if os.name == "nt":
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    profile = base / "LogistDesk21Preview"
else:
    profile = Path.home() / ".local" / "share" / "LogistDesk21Preview"

os.environ["LOGIST_DATA_DIR"] = str(profile)

import app20  # imports production UI patches but uses preview-specific data dir

if __name__ == "__main__":
    sys.exit(app20.stable_app.main())
