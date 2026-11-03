"""Persistent error reports for CLI and GUI failures."""
from __future__ import annotations

import os
import platform
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType

from . import __version__, config


def write_error_log(
    exc: BaseException,
    *,
    context: str,
    traceback_obj: TracebackType | None = None,
) -> Path | None:
    timestamp = datetime.now(timezone.utc)
    path = config.log_dir() / f"error-{timestamp.strftime('%Y%m%dT%H%M%S.%fZ')}.log"
    details = [
        f"Time: {timestamp.isoformat()}",
        f"Version: {__version__}",
        f"Context: {context}",
        f"Executable: {sys.executable}",
        f"Python: {platform.python_version()}",
        f"Platform: {platform.platform()}",
        f"Frozen: {bool(getattr(sys, 'frozen', False))}",
        f"Process ID: {os.getpid()}",
        "",
        "Traceback:",
        "".join(traceback.format_exception(type(exc), exc, traceback_obj or exc.__traceback__)).rstrip(),
        "",
    ]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(details), encoding="utf-8")
    except OSError as log_error:
        print(f"Could not write error log: {log_error}", file=sys.stderr)
        return None
    return path
