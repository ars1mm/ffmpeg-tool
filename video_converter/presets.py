"""Transcode presets.

These are neutral format/compatibility presets (container, codec,
resolution and quality). They exist to make output playable on the
target platform or device - not to obscure or alter content.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class Crop:
    """A visible reframing crop, in source pixels. (w, h, x, y)"""

    width: int
    height: int
    x: int = 0
    y: int = 0

    def filter_expr(self) -> str:
        w = max(2, self.width - self.width % 2)
        h = max(2, self.height - self.height % 2)
        return f"crop={w}:{h}:{self.x}:{self.y}"

    @property
    def label(self) -> str:
        return f"{self.width}x{self.height}+{self.x}+{self.y}"


# Aspect-ratio presets used to centre-crop a source frame.
ASPECT_PRESETS: dict[str, float] = {
    "16:9 (widescreen)": 16 / 9,
    "9:16 (vertical)": 9 / 16,
    "1:1 (square)": 1.0,
    "4:3 (classic)": 4 / 3,
    "4:5 (portrait post)": 4 / 5,
}


def crop_for_aspect(width: int, height: int, ratio: float) -> Crop:
    """Return the largest centred crop of `ratio` that fits in the frame."""
    if width <= 0 or height <= 0:
        raise ValueError("Unknown source dimensions")
    current = width / height
    if current > ratio:
        new_w = int(height * ratio)
        new_h = height
    else:
        new_w = width
        new_h = int(width / ratio)
    return Crop(
        width=new_w,
        height=new_h,
        x=(width - new_w) // 2,
        y=(height - new_h) // 2,
    )


@dataclass(frozen=True)
class Preset:
    key: str
    label: str
    container: str
    description: str
    video_codec: str | None = None
    audio_codec: str | None = None
    crf: int | None = None
    preset: str | None = None
    scale: str | None = None
    audio_bitrate: str | None = None
    extra_args: tuple[str, ...] = field(default_factory=tuple)
    audio_only: bool = False

    def ffmpeg_args(
        self,
        source: str,
        destination: str,
        crop: Crop | None = None,
        threads: int | None = None,
        gpu_encoder: str | None = None,
    ) -> list[str]:
        args: list[str] = ["-y", "-i", source, "-map_metadata", "0"]

        if self.audio_only:
            args += ["-vn"]
        else:
            args += ["-map", "0:v:0", "-map", "0:a?"]

            gpu = self.gpu_args_for(gpu_encoder) if gpu_encoder else None
            if gpu:
                args += gpu
            else:
                if self.video_codec:
                    args += ["-c:v", self.video_codec]
                if self.crf is not None:
                    args += ["-crf", str(self.crf)]
                if self.preset and self.video_codec in {"libx264", "libx265"}:
                    args += ["-preset", self.preset]

            filters: list[str] = []
            if crop is not None:
                filters.append(crop.filter_expr())
            if self.scale:
                filters.append(f"scale={self.scale}")
            if filters:
                args += ["-vf", ",".join(filters)]

            if self.video_codec in {"libx264", "libx265", "libvpx-vp9", "libaom-av1"}:
                args += ["-pix_fmt", "yuv420p"]

        if self.audio_codec:
            args += ["-c:a", self.audio_codec]
        if self.audio_bitrate:
            args += ["-b:a", self.audio_bitrate]

        args += list(self.extra_args)
        args += ["-movflags", "+faststart"] if self.container == "mp4" else []
        if threads:
            args += ["-threads", str(threads)]
        args += [destination]
        return args

    def gpu_args_for(self, gpu_encoder: str | None) -> list[str] | None:
        """Return ffmpeg args for a hardware encoder, or None if incompatible."""
        if not gpu_encoder or gpu_encoder not in GPU_ENCODERS:
            return None

        label, family, pix_fmt, quality_args = GPU_ENCODERS[gpu_encoder]
        target_family = ("h264" if self.video_codec == "libx264"
                         else "hevc" if self.video_codec == "libx265"
                         else "vp9" if self.video_codec == "libvpx-vp9"
                         else "av1" if "av1" in self.video_codec
                         else None)
        if family != target_family:
            return None

        quality = self.crf if self.crf is not None else 23
        args: list[str] = ["-c:v", gpu_encoder, "-pix_fmt", pix_fmt]
        for key, template in quality_args:
            args += [f"-{key}", template.format(q=quality)]
        if self.container == "mp4" and family == "hevc":
            args += ["-tag:v", "hvc1"]
        return args


# Hardware encoders. key = ffmpeg encoder name,
# value = (display label, codec family, pixel format, quality option templates).
# quality templates receive the preset's crf value as {q}.
GPU_ENCODERS: dict[str, tuple[str, str, str, tuple[tuple[str, str], ...]]] = {
    "h264_nvenc": (
        "NVIDIA NVENC  (h264_nvenc)",
        "h264",
        "yuv420p",
        (("rc", "vbr"), ("cq", "{q}"), ("preset", "p5")),
    ),
    "hevc_nvenc": (
        "NVIDIA NVENC  (hevc_nvenc)",
        "hevc",
        "yuv420p",
        (("rc", "vbr"), ("cq", "{q}"), ("preset", "p5")),
    ),
    "h264_amf": (
        "AMD AMF  (h264_amf)",
        "h264",
        "yuv420p",
        (("rc", "cqp"), ("qp_i", "{q}"), ("qp_p", "{q}"), ("quality", "quality")),
    ),
    "hevc_amf": (
        "AMD AMF  (hevc_amf)",
        "hevc",
        "yuv420p",
        (("rc", "cqp"), ("qp_i", "{q}"), ("qp_p", "{q}"), ("quality", "quality")),
    ),
    "h264_qsv": (
        "Intel QSV  (h264_qsv)",
        "h264",
        "nv12",
        (("global_quality", "{q}"), ("preset", "medium")),
    ),
    "hevc_qsv": (
        "Intel QSV  (hevc_qsv)",
        "hevc",
        "nv12",
        (("global_quality", "{q}"), ("preset", "medium")),
    ),
    "vp9_qsv": (
        "Intel QSV  (vp9_qsv)",
        "vp9",
        "nv12",
        (("global_quality", "{q}"), ("b", "0"), ("preset", "medium")),
    ),
    "av1_nvenc": (
        "NVIDIA NVENC  (av1_nvenc)",
        "av1",
        "yuv420p",
        (("rc", "vbr"), ("cq", "{q}"), ("preset", "p5")),
    ),
    "av1_qsv": (
        "Intel QSV  (av1_qsv)",
        "av1",
        "nv12",
        (("global_quality", "{q}"), ("preset", "medium")),
    ),
}


PRESETS: dict[str, Preset] = {
    "mp4_h264_1080": Preset(
        key="mp4_h264_1080",
        label="MP4 / H.264 / 1080p  (most compatible)",
        container="mp4",
        description="Universal playback on web, mobile and desktop.",
        video_codec="libx264",
        audio_codec="aac",
        crf=23,
        preset="medium",
        scale="1920:-2",
        audio_bitrate="128k",
    ),
    "mp4_h264_720": Preset(
        key="mp4_h264_720",
        label="MP4 / H.264 / 720p  (smaller file)",
        container="mp4",
        description="Good quality with a reduced file size.",
        video_codec="libx264",
        audio_codec="aac",
        crf=26,
        preset="medium",
        scale="1280:-2",
        audio_bitrate="128k",
    ),
    "mp4_h265": Preset(
        key="mp4_h265",
        label="MP4 / H.265 (HEVC) / 1080p",
        container="mp4",
        description="Higher compression; needs modern players.",
        video_codec="libx265",
        audio_codec="aac",
        crf=28,
        preset="medium",
        scale="1920:-2",
        audio_bitrate="128k",
        extra_args=("-tag:v", "hvc1"),
    ),
    "webm_vp9": Preset(
        key="webm_vp9",
        label="WebM / VP9 / 1080p",
        container="webm",
        description="Open format for browsers.",
        video_codec="libvpx-vp9",
        audio_codec="libvorbis",
        crf=32,
        scale="1920:-2",
        audio_bitrate="128k",
        extra_args=("-b:v", "0"),
    ),
    "mkv_h264": Preset(
        key="mkv_h264",
        label="MKV / H.264 (archival container)",
        container="mkv",
        description="Flexible container for local playback.",
        video_codec="libx264",
        audio_codec="aac",
        crf=20,
        preset="medium",
        audio_bitrate="192k",
    ),
    "mp4_h264_480": Preset(
        key="mp4_h264_480",
        label="MP4 / H.264 / 480p  (smallest mp4)",
        container="mp4",
        description="Low resolution for small file size.",
        video_codec="libx264",
        audio_codec="aac",
        crf=28,
        preset="medium",
        scale="854:-2",
        audio_bitrate="96k",
    ),
    "mp4_h265_720": Preset(
        key="mp4_h265_720",
        label="MP4 / H.265 (HEVC) / 720p",
        container="mp4",
        description="Very high compression at HD.",
        video_codec="libx265",
        audio_codec="aac",
        crf=29,
        preset="medium",
        scale="1280:-2",
        audio_bitrate="128k",
        extra_args=("-tag:v", "hvc1"),
    ),
    "mp4_av1": Preset(
        key="mp4_av1",
        label="MP4 / AV1 / 1080p",
        container="mp4",
        description="Best modern compression; needs AV1 support.",
        video_codec="libaom-av1",
        audio_codec="aac",
        crf=32,
        scale="1920:-2",
        audio_bitrate="128k",
        extra_args=("-b:v", "0", "-cpu-used", "6", "-row-mt", "1"),
    ),
    "mp4_vp9": Preset(
        key="mp4_vp9",
        label="MP4 / VP9 / 1080p",
        container="mp4",
        description="Open codec inside MP4.",
        video_codec="libvpx-vp9",
        audio_codec="aac",
        crf=32,
        scale="1920:-2",
        audio_bitrate="128k",
        extra_args=("-b:v", "0"),
    ),
    "mkv_h265": Preset(
        key="mkv_h265",
        label="MKV / H.265 (HEVC)",
        container="mkv",
        description="HEVC keeps quality, half the size.",
        video_codec="libx265",
        audio_codec="aac",
        crf=24,
        preset="medium",
        audio_bitrate="192k",
    ),
    "mkv_vp9": Preset(
        key="mkv_vp9",
        label="MKV / VP9",
        container="mkv",
        description="Open codec in an archival container.",
        video_codec="libvpx-vp9",
        audio_codec="aac",
        crf=30,
        scale="1920:-2",
        audio_bitrate="192k",
        extra_args=("-b:v", "0"),
    ),
    "mkv_av1": Preset(
        key="mkv_av1",
        label="MKV / AV1",
        container="mkv",
        description="State of the art compression in MKV.",
        video_codec="libaom-av1",
        audio_codec="libopus",
        crf=32,
        scale="1920:-2",
        audio_bitrate="192k",
        extra_args=("-b:v", "0", "-cpu-used", "6", "-row-mt", "1"),
    ),
    "webm_av1": Preset(
        key="webm_av1",
        label="WebM / AV1 / 1080p",
        container="webm",
        description="Modern browser format with AV1.",
        video_codec="libaom-av1",
        audio_codec="libopus",
        crf=32,
        scale="1920:-2",
        audio_bitrate="128k",
        extra_args=("-b:v", "0", "-cpu-used", "6", "-row-mt", "1"),
    ),
    "mov_h264": Preset(
        key="mov_h264",
        label="MOV / H.264 / 1080p",
        container="mov",
        description="Apple-friendly QuickTime container.",
        video_codec="libx264",
        audio_codec="aac",
        crf=23,
        preset="medium",
        scale="1920:-2",
        audio_bitrate="128k",
    ),
    "mov_h265": Preset(
        key="mov_h265",
        label="MOV / H.265 (HEVC) / 1080p",
        container="mov",
        description="QuickTime HEVC.",
        video_codec="libx265",
        audio_codec="aac",
        crf=28,
        preset="medium",
        scale="1920:-2",
        audio_bitrate="128k",
    ),
    "m4v_h264": Preset(
        key="m4v_h264",
        label="M4V / H.264 / 720p",
        container="m4v",
        description="iPod / Apple TV compatible MPEG-4.",
        video_codec="libx264",
        audio_codec="aac",
        crf=24,
        preset="medium",
        scale="1280:-2",
        audio_bitrate="128k",
    ),
    "avi_h264": Preset(
        key="avi_h264",
        label="AVI / H.264 / 720p",
        container="avi",
        description="Classic AVI container.",
        video_codec="libx264",
        audio_codec="aac",
        crf=24,
        preset="medium",
        scale="1280:-2",
        audio_bitrate="128k",
    ),
    "ts_h264": Preset(
        key="ts_h264",
        label="MPEG-TS / H.264 / 1080p",
        container="ts",
        description="Transport stream for streaming.",
        video_codec="libx264",
        audio_codec="aac",
        crf=23,
        preset="medium",
        scale="1920:-2",
        audio_bitrate="128k",
    ),
    "flv_h264": Preset(
        key="flv_h264",
        label="FLV / H.264 / 720p",
        container="flv",
        description="Legacy Flash video streaming.",
        video_codec="libx264",
        audio_codec="aac",
        crf=24,
        preset="medium",
        scale="1280:-2",
        audio_bitrate="128k",
    ),
    "audio_mp3": Preset(
        key="audio_mp3",
        label="Audio only / MP3 192k",
        container="mp3",
        description="Extract audio track to MP3.",
        audio_codec="libmp3lame",
        audio_bitrate="192k",
        audio_only=True,
    ),
    "audio_aac": Preset(
        key="audio_aac",
        label="Audio only / AAC 192k (m4a)",
        container="m4a",
        description="Extract audio track to AAC.",
        audio_codec="aac",
        audio_bitrate="192k",
        audio_only=True,
    ),
    "gif": Preset(
        key="gif",
        label="GIF (short clips)",
        container="gif",
        description="Animated GIF, no audio.",
        scale="640:-2",
        extra_args=("-r", "12"),
        audio_only=False,
    ),
}


def preset_by_label(label: str) -> Preset:
    for preset in PRESETS.values():
        if preset.label == label:
            return preset
    raise KeyError(label)


def auto_encoder_map(names: Iterable[str]) -> dict[str, str]:
    """Pick the best known hardware encoder per codec family.

    Priority for the same family: NVENC > AMF > QSV.
    """
    priority = {"nvenc": 0, "amf": 1, "qsv": 2}
    auto: dict[str, tuple[int, str]] = {}
    for name in names:
        if name not in GPU_ENCODERS:
            continue
        _, family, _, _ = GPU_ENCODERS[name]
        if family not in ("h264", "hevc", "vp9", "av1"):
            continue
        vendor = priority[next(k for k in priority if k in name)]
        if family not in auto or vendor < auto[family][0]:
            auto[family] = (vendor, name)
    return {family: name for family, (vendor, name) in auto.items()}


def labels() -> list[str]:
    return [preset.label for preset in PRESETS.values()]
