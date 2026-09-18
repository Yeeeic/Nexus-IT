"""Best-effort local database permission hardening."""

from __future__ import annotations

import os
import subprocess
import ctypes
from pathlib import Path


def harden_directory(path: Path) -> bool:
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        try:
            path.chmod(0o700)
            return True
        except OSError:
            return False
    return _harden_windows(path, is_directory=True)


def harden_file(path: Path) -> bool:
    if os.name != "nt":
        try:
            path.chmod(0o600)
            return True
        except OSError:
            return False
    return _harden_windows(path, is_directory=False)


def _harden_windows(path: Path, *, is_directory: bool) -> bool:
    # Applying a SYSTEM-only ACL from an interactive, non-elevated process can
    # lock the caller out before SQLite opens its WAL sidecars. Production runs
    # as SYSTEM; development remains usable and reports hardening as unavailable.
    if os.environ.get("NEXUS_AGENT_ENFORCE_WINDOWS_ACL") != "1":
        return False
    try:
        if not bool(ctypes.windll.shell32.IsUserAnAdmin()):
            return False
    except (AttributeError, OSError):
        return False
    inheritance = "(OI)(CI)F" if is_directory else "F"
    command = [
        "icacls",
        str(path),
        "/inheritance:r",
        "/grant:r",
        f"*S-1-5-18:{inheritance}",
        f"*S-1-5-32-544:{inheritance}",
    ]
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            timeout=10,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0
