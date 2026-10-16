"""Send files/folders to the Windows Recycle Bin (undo-capable delete)."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import Path

FO_DELETE = 0x0003
FOF_ALLOWUNDO = 0x0040
FOF_NOCONFIRMATION = 0x0010
FOF_SILENT = 0x0004

# Keep all-uppercase names matching the Win32 struct for clarity.
# noqa: N801
class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", ctypes.c_uint),
        ("pFrom", ctypes.c_wchar_p),
        ("pTo", ctypes.c_wchar_p),
        ("fFlags", ctypes.c_ushort),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", ctypes.c_wchar_p),
    ]


def send_to_recycle_bin(paths: list[Path]) -> list[Path]:
    """Move `paths` to the Windows Recycle Bin.

    Returns the files that could not be moved. Raises NotImplementedError on
    platforms without the Win32 shell API.
    """
    failed: list[Path] = []
    if not paths:
        return failed
    if os.name != "nt":
        raise NotImplementedError("Recycle Bin delete is Windows-only")

    shell32 = ctypes.windll.shell32
    buffer = "\0".join(os.path.abspath(str(p)) for p in paths) + "\0\0"

    op = _SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = FO_DELETE
    op.pFrom = buffer
    op.pTo = None
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT
    result = shell32.SHFileOperationW(ctypes.byref(op))
    if result != 0 or op.fAnyOperationsAborted:
        for path in paths:
            if path.exists():
                failed.append(path)
    return failed