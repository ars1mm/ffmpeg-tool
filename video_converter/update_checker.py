"""Check for application updates from GitHub releases."""

from __future__ import annotations

import json
import urllib.request
import urllib.error
from typing import NamedTuple

from .version import __version__, UPDATE_CHECK_URL, RELEASE_PAGE_URL


class UpdateInfo(NamedTuple):
    """Information about an available update."""
    available: bool
    current_version: str
    latest_version: str
    download_url: str
    release_notes: str


def parse_version(version_str: str) -> tuple[int, ...]:
    """Parse a version string like 'v1.2.3' or '1.2.3' into a tuple of ints."""
    clean = version_str.lstrip("v").strip()
    try:
        return tuple(int(x) for x in clean.split("."))
    except (ValueError, AttributeError):
        return (0, 0, 0)


def check_for_updates(timeout: float = 5.0) -> UpdateInfo | None:
    """
    Check GitHub for the latest release.
    
    Returns:
        UpdateInfo if check succeeds, None if it fails (network error, etc.)
    """
    try:
        req = urllib.request.Request(
            UPDATE_CHECK_URL,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"FFmpegConverter/{__version__}"
            }
        )
        
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status != 200:
                return None
            
            data = json.loads(response.read().decode("utf-8"))
        
        latest_version = data.get("tag_name", "").lstrip("v")
        release_notes = data.get("body", "")
        
        # Find the installer asset
        download_url = RELEASE_PAGE_URL
        assets = data.get("assets", [])
        for asset in assets:
            name = asset.get("name", "").lower()
            if name.endswith(".exe") and "setup" in name:
                download_url = asset.get("browser_download_url", RELEASE_PAGE_URL)
                break
        
        # Compare versions
        current = parse_version(__version__)
        latest = parse_version(latest_version)
        
        update_available = latest > current
        
        return UpdateInfo(
            available=update_available,
            current_version=__version__,
            latest_version=latest_version,
            download_url=download_url,
            release_notes=release_notes[:500]  # Truncate to avoid huge dialogs
        )
    
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, KeyError):
        # Network error, rate limit, malformed response, etc.
        return None
    except Exception:
        # Catch-all for any other errors (don't crash the app on update check)
        return None


def format_release_notes(notes: str, max_lines: int = 5) -> str:
    """Format release notes for display in a dialog."""
    lines = [line.strip() for line in notes.split("\n") if line.strip()]
    if len(lines) > max_lines:
        lines = lines[:max_lines] + ["..."]
    return "\n".join(lines)
