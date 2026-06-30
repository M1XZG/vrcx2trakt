"""Cross-platform configuration, paths, and VRCX database auto-detection.

This module centralises every filesystem location the tool uses so the rest of
the package never hardcodes a path. It works on native Windows, Linux, macOS and
WSL, and it transparently migrates from the author's original ``vrcx-trakt``
layout when present.

Locations
---------
Config (secrets) directory, holding ``credentials.json`` and ``token.json``:
  * Windows native : ``%APPDATA%\\vrcx2trakt``
  * Linux / macOS  : ``$XDG_CONFIG_HOME/vrcx2trakt`` or ``~/.config/vrcx2trakt``

Working/state directory, holding the DB copy and pipeline artefacts
(``candidates.json``, ``review.csv``, ``pushed-state.json`` ...):
  * Windows native : ``%LOCALAPPDATA%\\vrcx2trakt``
  * Linux / macOS  : ``$XDG_STATE_HOME/vrcx2trakt`` or ``~/.local/state/vrcx2trakt``

All of these can be overridden with environment variables:
  ``VRCX2TRAKT_CONFIG_DIR``, ``VRCX2TRAKT_STATE_DIR``, ``VRCX_DB``.
"""
from __future__ import annotations

import glob
import os
import sys
from pathlib import Path

APP_NAME = "vrcx2trakt"
LEGACY_APP_NAME = "vrcx-trakt"

# The three VRChat cinema "players" recorded in VRCX gamelog_video_play.video_id.
SOURCES = ("PopcornPalace", "Movie&Chill", "LSMedia")


# --------------------------------------------------------------------------- #
# Platform helpers
# --------------------------------------------------------------------------- #
def is_windows() -> bool:
    return os.name == "nt" or sys.platform.startswith("win")


def is_wsl() -> bool:
    """True when running inside Windows Subsystem for Linux."""
    if is_windows():
        return False
    release = ""
    try:
        release = os.uname().release.lower()  # type: ignore[attr-defined]
    except AttributeError:
        return False
    if "microsoft" in release or "wsl" in release:
        return True
    try:
        with open("/proc/version", "r", encoding="utf-8", errors="ignore") as fh:
            return "microsoft" in fh.read().lower()
    except OSError:
        return False


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else None


# --------------------------------------------------------------------------- #
# Config (secrets) directory
# --------------------------------------------------------------------------- #
def config_dir() -> Path:
    override = _env_path("VRCX2TRAKT_CONFIG_DIR")
    if override:
        return override
    if is_windows():
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_NAME
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_NAME


def _legacy_config_dir() -> Path:
    """The author's original location: ``~/.config/vrcx-trakt``."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / LEGACY_APP_NAME


def ensure_config_dir() -> Path:
    path = config_dir()
    path.mkdir(parents=True, exist_ok=True)
    if not is_windows():
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass
    return path


def credentials_path() -> Path:
    """Preferred credentials file, falling back to the legacy location if only it exists."""
    primary = config_dir() / "credentials.json"
    if primary.exists():
        return primary
    legacy = _legacy_config_dir() / "credentials.json"
    if legacy.exists():
        return legacy
    return primary


def token_path() -> Path:
    """Preferred token file, falling back to the legacy location if only it exists."""
    primary = config_dir() / "token.json"
    if primary.exists():
        return primary
    legacy = _legacy_config_dir() / "token.json"
    if legacy.exists():
        return legacy
    return primary


# --------------------------------------------------------------------------- #
# Working / state directory
# --------------------------------------------------------------------------- #
def state_dir() -> Path:
    override = _env_path("VRCX2TRAKT_STATE_DIR")
    if override:
        return override
    if is_windows():
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / APP_NAME


def ensure_state_dir() -> Path:
    path = state_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def state_file(name: str) -> Path:
    return state_dir() / name


# Convenience accessors for the well-known pipeline artefacts.
def db_copy_path() -> Path:
    return state_file("VRCX.copy.sqlite3")


def candidates_path() -> Path:
    return state_file("candidates.json")


def review_path() -> Path:
    return state_file("review.csv")


def match_cache_path() -> Path:
    return state_file("match-cache.json")


def pushed_state_path() -> Path:
    return state_file("pushed-state.json")


def push_log_path() -> Path:
    return state_file("push-log.json")


def log_dir() -> Path:
    return state_dir() / "logs"


# --------------------------------------------------------------------------- #
# VRCX database auto-detection
# --------------------------------------------------------------------------- #
def _windows_user_roots() -> list[str]:
    roots: list[str] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        roots.append(appdata)
    return roots


def _wsl_appdata_globs() -> list[str]:
    """Candidate VRCX paths visible from WSL via the mounted Windows drive."""
    patterns = []
    for drive in ("c", "d"):
        patterns.append(f"/mnt/{drive}/Users/*/AppData/Roaming/VRCX/VRCX.sqlite3")
    return patterns


def detect_vrcx_db() -> Path | None:
    """Best-effort location of the live VRCX SQLite database.

    Resolution order:
      1. ``VRCX_DB`` environment variable.
      2. Native Windows ``%APPDATA%\\VRCX\\VRCX.sqlite3``.
      3. WSL: ``/mnt/<drive>/Users/*/AppData/Roaming/VRCX/VRCX.sqlite3``.
      4. Linux/macOS XDG-style installs (rare; VRCX is Windows-first).
    Returns ``None`` when nothing is found.
    """
    override = _env_path("VRCX_DB")
    if override and override.exists():
        return override

    candidates: list[str] = []

    if is_windows():
        for root in _windows_user_roots():
            candidates.append(os.path.join(root, "VRCX", "VRCX.sqlite3"))
    elif is_wsl():
        for pattern in _wsl_appdata_globs():
            candidates.extend(sorted(glob.glob(pattern)))
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
        candidates.append(os.path.join(base, "VRCX", "VRCX.sqlite3"))
        candidates.append(str(Path.home() / ".local" / "share" / "VRCX" / "VRCX.sqlite3"))

    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return path
    return None


def resolve_vrcx_db(explicit: str | os.PathLike[str] | None = None) -> Path:
    """Return the VRCX DB path or raise a helpful error if it cannot be found."""
    if explicit:
        path = Path(explicit).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"VRCX database not found at: {path}")
        return path
    detected = detect_vrcx_db()
    if detected is not None:
        return detected
    raise FileNotFoundError(
        "Could not locate the VRCX database automatically. Pass --db /path/to/VRCX.sqlite3 "
        "or set the VRCX_DB environment variable. On Windows it is usually "
        "%APPDATA%\\VRCX\\VRCX.sqlite3."
    )
