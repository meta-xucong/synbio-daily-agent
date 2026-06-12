#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared runtime settings for the synbio daily pipeline."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(
    os.getenv("SYNBIO_DAILY_HOME", Path(__file__).resolve().parents[1])
).resolve()
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
REPORTS_DIR = PROJECT_ROOT / "reports"
TEMPLATES_DIR = PROJECT_ROOT / "templates"

APP_TIMEZONE = os.getenv("SYNBIO_DAILY_TZ", "Asia/Shanghai")
TZ = ZoneInfo(APP_TIMEZONE)


def now_local() -> datetime:
    """Return the current datetime in the configured application timezone."""
    fixed_now = os.getenv("SYNBIO_DAILY_NOW")
    if fixed_now:
        dt = datetime.fromisoformat(fixed_now.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=TZ)
        return dt.astimezone(TZ)
    return datetime.now(TZ)


def date_str(dt: datetime | None = None) -> str:
    """Return YYYY-MM-DD in the configured application timezone."""
    return (dt or now_local()).strftime("%Y-%m-%d")
