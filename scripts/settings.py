#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared runtime settings for the synbio daily pipeline."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo


PROJECT_ROOT = Path(
    os.getenv("SYNBIO_DAILY_HOME", Path(__file__).resolve().parents[1])
).resolve()
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
REPORTS_DIR = PROJECT_ROOT / "reports"
TEMPLATES_DIR = PROJECT_ROOT / "templates"


def _get_tz():
    tz_name = os.getenv("SYNBIO_DAILY_TZ", "Asia/Shanghai")
    try:
        return ZoneInfo(tz_name)
    except Exception:
        # Fallback for Windows without tzdata package
        try:
            import pytz
            return pytz.timezone(tz_name)
        except ImportError:
            # Ultimate fallback: use UTC
            from datetime import timezone
            return timezone.utc


TZ = _get_tz()


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
