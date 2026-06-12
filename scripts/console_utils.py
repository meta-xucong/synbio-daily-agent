#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Console helpers shared by CLI and imported pipeline scripts."""

from __future__ import annotations

import io
import sys


def ensure_utf8_console() -> None:
    """Avoid UnicodeEncodeError for emoji/log output on Windows consoles."""
    if sys.platform != "win32":
        return

    try:
        stdout_encoding = (getattr(sys.stdout, "encoding", None) or "").lower()
        stderr_encoding = (getattr(sys.stderr, "encoding", None) or "").lower()
        if stdout_encoding != "utf-8" and hasattr(sys.stdout, "buffer"):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        if stderr_encoding != "utf-8" and hasattr(sys.stderr, "buffer"):
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass
