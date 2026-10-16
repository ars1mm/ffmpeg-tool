# Changelog

All notable changes to FFmpeg Video Converter will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-10-16

### Added
- Initial release
- Batch video conversion with FFmpeg
- GPU hardware acceleration (NVIDIA NVENC, AMD AMF, Intel QSV)
- Automatic GPU encoder detection and verification
- 20+ format presets (MP4, MKV, WebM, MOV, AVI, etc.)
- Source library browser with folder organization
- Flexible output naming with template system
- Aspect ratio cropping (16:9, 9:16, 1:1, 4:3, 4:5, custom)
- Parallel conversion queue with configurable workers
- Progress tracking (per-file and overall)
- Duplicate video detector with SHA-256 hashing
- UAC elevation for protected folders
- Automatic update checking
- Output folder selection with auto-creation
- Enhanced GPU detection with detailed logging

### Features
- **Hardware Acceleration**: Automatically detects and uses GPU encoders for faster encoding
- **Smart Output**: Prompts for output folder if not set, remembers your choice
- **Update Notifications**: Checks for new versions on startup and notifies users
- **Comprehensive Presets**: H.264, H.265, VP9, AV1, audio extraction, and more
- **Flexible Naming**: Template system with {artist}, {slug}, {uuid}, {time} placeholders
- **Safe Deletion**: Duplicate removal uses Windows Recycle Bin

### Technical
- Python 3.10+ with Tkinter
- FFmpeg integration with bundled binaries
- PyInstaller for standalone executable
- Inno Setup for Windows installer
