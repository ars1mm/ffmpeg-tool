"""Version information for FFmpeg Video Converter."""

__version__ = "1.0.0"
__version_info__ = tuple(int(x) for x in __version__.split("."))

# GitHub repository for update checking
GITHUB_REPO = "ars1mm/ffmpeg-tool"
UPDATE_CHECK_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASE_PAGE_URL = f"https://github.com/{GITHUB_REPO}/releases/latest"
