"""Windows UAC elevation helpers.

Allows the app to write to protected folders (e.g. a folder under
``C:\\Program Files`` or a locked library path) that the user legitimately
owns by relaunching itself with the ``runas`` verb.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from pathlib import Path


def is_supported() -> bool:
    return os.name == "nt"


def is_admin() -> bool:
    """Return True if the current process is elevated."""
    if not is_supported():
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except Exception:
        return False


def folder_is_writable(folder: str) -> bool:
    """Best-effort check that we can create files in `folder`."""
    path = Path(folder)
    if not path.exists() or not path.is_dir():
        return False
    probe = path / ".vc_write_test"
    try:
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _command_line() -> tuple[str, str]:
    """Return (executable, parameters) that reproduce the current run."""
    if getattr(sys, "frozen", False):
        return sys.executable, subprocess.list2cmdline(sys.argv[1:])

    script = os.path.abspath(sys.argv[0])
    params = subprocess.list2cmdline([script, *sys.argv[1:]])
    return sys.executable, params


def relaunch_as_admin() -> bool:
    """Relaunch this app elevated. Returns True if the UAC prompt launched."""
    if not is_supported():
        return False

    executable, params = _command_line()
    # SW_SHOWNORMAL == 1; returns an HINSTANCE > 32 on success.
    result = ctypes.windll.shell32.ShellExecuteW(  # type: ignore[attr-defined]
        None, "runas", executable, params, None, 1
    )
    return result > 32
