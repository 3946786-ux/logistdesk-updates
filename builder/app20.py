"""Production entry point for LogistDesk 2.0.

Unlike app12.py preview, this entry point uses the existing secured LogistDesk
profile. Only publish after migration, backup and Windows QA have passed.
"""
from __future__ import annotations

import sys
import app as stable_app
from app12 import LogistWindow12, RouteDialog12, CarrierDialog12

stable_app.LogistWindow = LogistWindow12
stable_app.RouteDialog = RouteDialog12
stable_app.CarrierDialog = CarrierDialog12

if __name__ == "__main__":
    sys.exit(stable_app.main())
