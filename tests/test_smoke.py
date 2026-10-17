"""Smoke tests for the converter core (no GUI).

These are integration tests and require ffmpeg/ffprobe on PATH.
Run with: python -m pytest  or  python -m unittest discover -s tests
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from video_converter import converter, ffmpeg, presets


def _make_sample(path: str, seconds: int = 1) -> bool:
    try:
        subprocess.run(
            [
                ffmpeg.ffmpeg_path(),
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"testsrc=duration={seconds}:size=320x240:rate=15",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=440:duration={seconds}",
                "-pix_fmt",
                "yuv420p",
                "-shortest",
                path,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, ffmpeg.FFmpegNotFoundError, OSError):
        return False


class PresetTests(unittest.TestCase):
    def test_all_presets_have_labels(self) -> None:
        for key, preset in presets.PRESETS.items():
            self.assertEqual(key, preset.key)
            self.assertTrue(preset.label)
            self.assertTrue(preset.container)

    def test_mp4_args_include_faststart(self) -> None:
        preset = presets.PRESETS["mp4_h264_1080"]
        args = preset.ffmpeg_args("in.mov", "out.mp4")
        self.assertIn("-movflags", args)
        self.assertIn("+faststart", args)

    def test_audio_only_preset_disables_video(self) -> None:
        preset = presets.PRESETS["audio_mp3"]
        args = preset.ffmpeg_args("in.mp4", "out.mp3")
        self.assertIn("-vn", args)

    def test_threads_arg_precedes_output(self) -> None:
        preset = presets.PRESETS["mp4_h264_1080"]
        args = preset.ffmpeg_args("in.mp4", "out.mp4", threads=1)
        self.assertEqual(args[args.index("-threads") + 1], "1")
        self.assertLess(args.index("-threads"), args.index("out.mp4"))

    def test_gpu_encoder_substitutes_codec(self) -> None:
        preset = presets.PRESETS["mp4_h264_1080"]
        full = preset.ffmpeg_args("in.mp4", "out.mp4", gpu_encoder="h264_nvenc")
        self.assertIn("h264_nvenc", full)
        self.assertNotIn("libx264", full)
        self.assertNotIn("-crf", full)
        self.assertIn("-cq", full)

    def test_gpu_family_mismatch_falls_back_to_cpu(self) -> None:
        vp9 = presets.PRESETS["webm_vp9"]
        self.assertIsNone(vp9.gpu_args_for("h264_nvenc"))
        mp4 = presets.PRESETS["mp4_h264_1080"]
        self.assertIsNone(mp4.gpu_args_for("unknown_encoder"))

    def test_vp9_qsv_maps_to_webm_preset(self) -> None:
        vp9 = presets.PRESETS["webm_vp9"]
        full = vp9.ffmpeg_args("in.mp4", "out.webm", gpu_encoder="vp9_qsv")
        self.assertIn("vp9_qsv", full)
        self.assertNotIn("libvpx-vp9", full)
        self.assertIn("-global_quality", full)

    def test_av1_nvenc_rejected_for_webm_vp9(self) -> None:
        vp9 = presets.PRESETS["webm_vp9"]
        self.assertIsNone(vp9.gpu_args_for("av1_nvenc"))

    def test_auto_map_prefers_nvenc_over_amf_and_qsv(self) -> None:
        result = presets.auto_encoder_map(
            ["h264_qsv", "h264_amf", "h264_nvenc"]
        )
        self.assertEqual(result["h264"], "h264_nvenc")

    def test_auto_map_picks_sole_vendor(self) -> None:
        result = presets.auto_encoder_map(["vp9_qsv", "av1_nvenc"])
        self.assertEqual(result, {"vp9": "vp9_qsv", "av1": "av1_nvenc"})

    def test_auto_map_includes_av1(self) -> None:
        result = presets.auto_encoder_map(["av1_nvenc", "av1_qsv"])
        self.assertEqual(result, {"av1": "av1_nvenc"})

    def test_auto_map_ignores_unknown_encoders(self) -> None:
        result = presets.auto_encoder_map(["made_up_encoder"])
        self.assertEqual(result, {})

    def test_codec_family_property(self) -> None:
        self.assertEqual(presets.PRESETS["mp4_h264_1080"].codec_family, "h264")
        self.assertEqual(presets.PRESETS["mp4_h265"].codec_family, "hevc")
        self.assertEqual(presets.PRESETS["webm_vp9"].codec_family, "vp9")
        self.assertEqual(presets.PRESETS["mp4_av1"].codec_family, "av1")
        self.assertIsNone(presets.PRESETS["audio_mp3"].codec_family)
        self.assertIsNone(presets.PRESETS["gif"].codec_family)

    def test_auto_map_uses_detected_gpu_vendor(self) -> None:
        encoders = ["h264_nvenc", "h264_qsv", "hevc_nvenc", "hevc_qsv"]
        intel_only = presets.auto_encoder_map(
            encoders, ["Intel(R) UHD Graphics 770"]
        )
        self.assertEqual(intel_only, {"h264": "h264_qsv", "hevc": "hevc_qsv"})

        nvidia = presets.auto_encoder_map(
            encoders, ["NVIDIA GeForce RTX 5060 Ti", "Intel UHD Graphics 770"]
        )
        self.assertEqual(nvidia, {"h264": "h264_nvenc", "hevc": "hevc_nvenc"})

        amd = presets.auto_encoder_map(
            ["h264_amf", "h264_qsv", "hevc_amf"], ["AMD Radeon RX 7800 XT"]
        )
        self.assertEqual(amd, {"h264": "h264_amf", "hevc": "hevc_amf"})

    def test_auto_map_without_gpu_info_keeps_default_priority(self) -> None:
        result = presets.auto_encoder_map(
            ["h264_qsv", "h264_amf", "h264_nvenc"], []
        )
        self.assertEqual(result["h264"], "h264_nvenc")

    def test_gpu_args_rejected_for_non_video_preset(self) -> None:
        self.assertIsNone(
            presets.PRESETS["audio_mp3"].gpu_args_for("h264_nvenc")
        )
        self.assertIsNone(presets.PRESETS["gif"].gpu_args_for("h264_nvenc"))

    def test_gif_drops_audio_stream(self) -> None:
        gif = presets.PRESETS["gif"]
        args = gif.ffmpeg_args("in.mov", "out.gif")
        self.assertIn("-an", args)
        self.assertNotIn("0:a?", args)

    def test_gif_uses_palette_filtergraph(self) -> None:
        gif = presets.PRESETS["gif"]
        args = gif.ffmpeg_args("in.mov", "out.gif")
        graph = args[args.index("-vf") + 1]
        self.assertIn("palettegen", graph)
        self.assertIn("paletteuse", graph)
        self.assertIn("fps=12", graph)
        self.assertNotIn("-pix_fmt", args)

    def test_gif_hwaccel_cuda_places_option_before_input(self) -> None:
        gif = presets.PRESETS["gif"]
        args = gif.ffmpeg_args("in.mov", "out.gif", hwaccel="cuda")
        self.assertEqual(args[args.index("-hwaccel") + 1], "cuda")
        self.assertLess(args.index("-hwaccel"), args.index("in.mov"))
        graph = args[args.index("-vf") + 1]
        self.assertIn("hwupload_cuda", graph)
        self.assertIn("scale_cuda=640:-2", graph)
        self.assertIn("hwdownload", graph)

    def test_gif_hwaccel_qsv_downloads_surfaces(self) -> None:
        gif = presets.PRESETS["gif"]
        args = gif.ffmpeg_args("in.mov", "out.gif", hwaccel="qsv")
        self.assertEqual(args[args.index("-hwaccel") + 1], "qsv")
        self.assertEqual(
            args[args.index("-hwaccel_output_format") + 1], "qsv"
        )
        graph = args[args.index("-vf") + 1]
        self.assertIn("hwdownload,format=nv12", graph)

    def test_hwaccel_ignored_for_non_gif_presets(self) -> None:
        mp4 = presets.PRESETS["mp4_h264_1080"]
        args = mp4.ffmpeg_args("in.mov", "out.mp4", hwaccel="cuda")
        self.assertNotIn("-hwaccel", args)

    def test_hwaccel_for_encoders_maps_vendors(self) -> None:
        self.assertEqual(
            presets.hwaccel_for_encoders(["h264_nvenc"]), "cuda"
        )
        self.assertEqual(
            presets.hwaccel_for_encoders(["h264_qsv", "hevc_qsv"]), "qsv"
        )
        self.assertEqual(
            presets.hwaccel_for_encoders(["h264_amf"]), "d3d11va"
        )
        self.assertEqual(
            presets.hwaccel_for_encoders(["h264_nvenc", "h264_qsv"]), "cuda"
        )
        self.assertIsNone(presets.hwaccel_for_encoders(["libx264"]))


class GpuDetectionTests(unittest.TestCase):
    def test_detect_gpus_returns_name_list(self) -> None:
        gpus = ffmpeg.detect_gpus()
        self.assertIsInstance(gpus, list)
        self.assertTrue(all(isinstance(name, str) and name for name in gpus))

    def test_probe_hardware_encoder_never_raises(self) -> None:
        # Result depends on the machine; only guarantee a clean bool back.
        self.assertIn(
            ffmpeg.probe_hardware_encoder("h264_nvenc"), (True, False)
        )


class FormatPresetTests(unittest.TestCase):
    def test_webm_vp9_uses_vorbis_audio_for_qsv(self) -> None:
        self.assertEqual(presets.PRESETS["webm_vp9"].audio_codec, "libvorbis")

    def test_mkv_vp9_uses_aac_audio_for_qsv(self) -> None:
        self.assertEqual(presets.PRESETS["mkv_vp9"].audio_codec, "aac")

    def test_new_container_presets_exist(self) -> None:
        labels = {p.label for p in presets.PRESETS.values()}
        for needle in ("MOV", "MKV", "AVI", "M4V", "MPEG-TS", "FLV", "AV1"):
            self.assertTrue(any(needle in lab for lab in labels), needle)


class OutputPathTests(unittest.TestCase):
    def test_output_uses_preset_container(self) -> None:
        preset = presets.PRESETS["webm_vp9"]
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "clip.mp4"
            src.write_bytes(b"")
            dest = converter.output_path_for(str(src), preset, None)
            self.assertTrue(dest.endswith(".webm"))

    def test_output_avoid_overwrite(self) -> None:
        preset = presets.PRESETS["mp4_h264_1080"]
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "clip.mkv"
            src.write_bytes(b"")
            first = converter.output_path_for(str(src), preset, tmp)
            Path(first).write_bytes(b"existing")
            second = converter.output_path_for(str(src), preset, tmp)
            self.assertNotEqual(first, second)


class ThreadAllocationTests(unittest.TestCase):
    def test_single_job_gets_all_cores(self) -> None:
        self.assertEqual(converter.threads_for_job(16, 1), 16)

    def test_cores_split_across_concurrent_jobs(self) -> None:
        self.assertEqual(converter.threads_for_job(16, 4), 4)
        self.assertEqual(converter.threads_for_job(8, 2), 4)

    def test_never_below_one_thread(self) -> None:
        self.assertEqual(converter.threads_for_job(16, 32), 1)
        self.assertEqual(converter.threads_for_job(1, 8), 1)

    def test_defensive_zero_jobs(self) -> None:
        self.assertEqual(converter.threads_for_job(8, 0), 8)


class CropTests(unittest.TestCase):
    def test_filter_expr_rounds_to_even(self) -> None:
        crop = presets.Crop(1921, 1081, 3, 5)
        self.assertEqual(crop.filter_expr(), "crop=1920:1080:3:5")

    def test_aspect_crop_is_centred(self) -> None:
        crop = presets.crop_for_aspect(1920, 1080, 1.0)
        self.assertEqual((crop.width, crop.height), (1080, 1080))
        self.assertEqual((crop.x, crop.y), (420, 0))

    def test_crop_precedes_scale_in_args(self) -> None:
        preset = presets.PRESETS["mp4_h264_1080"]
        args = preset.ffmpeg_args(
            "a.mp4", "b.mp4", crop=presets.Crop(100, 100, 0, 0)
        )
        vf = args[args.index("-vf") + 1]
        self.assertEqual(vf, "crop=100:100:0:0,scale=1920:-2")


class OutputTemplateTests(unittest.TestCase):
    def test_sanitize_removes_invalid_chars(self) -> None:
        self.assertEqual(converter.sanitize_component('a<b>c:"|*?'), "abc")

    def test_slugify(self) -> None:
        self.assertEqual(converter.slugify("Test Artist"), "test-artist")
        self.assertEqual(converter.slugify("  ** "), "clip")

    def test_unique_naming_placeholders(self) -> None:
        preset = presets.PRESETS["mp4_h264_1080"]
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "clip.mov"
            src.write_bytes(b"")
            out = converter.build_output_path(
                str(src),
                preset,
                tmp,
                "{slug}-{hex5}-{uuid}-{time}.{format}",
                "Test Artist",
            )
            name = Path(out).name
            self.assertTrue(name.startswith("test-artist-"))
            self.assertTrue(name.endswith(".mp4"))
            parts = name[:-4].split("-")
            self.assertEqual(parts[0], "test")
            self.assertEqual(parts[1], "artist")
            self.assertEqual(len(parts[2]), 5)
            self.assertTrue(all(c in "0123456789ABCDEF" for c in parts[2]))

    def test_names_are_unique_per_call(self) -> None:
        preset = presets.PRESETS["mp4_h264_1080"]
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "clip.mov"
            src.write_bytes(b"")
            names = {
                converter.build_output_path(str(src), preset, tmp, artist="A")
                for _ in range(5)
            }
            self.assertEqual(len(names), 5)

    def test_template_builds_subfolders(self) -> None:
        preset = presets.PRESETS["webm_vp9"]
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "clip.mp4"
            src.write_bytes(b"")
            out = converter.build_output_path(
                str(src),
                preset,
                tmp,
                "{format}/{artist}/{name}.{format}",
                "Test Artist",
            )
            rel = Path(out).relative_to(tmp).parts
            self.assertEqual(rel[0], "webm")
            self.assertEqual(rel[1], "Test Artist")
            self.assertTrue(rel[2].endswith(".webm"))

    def test_template_placeholder_fallback(self) -> None:
        preset = presets.PRESETS["mp4_h264_1080"]
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "clip.mov"
            src.write_bytes(b"")
            out = converter.build_output_path(str(src), preset, tmp, "{bogus}")
            name = Path(out).name
            self.assertTrue(name.startswith("clip-"))
            self.assertTrue(name.endswith(".mp4"))


class ConversionTests(unittest.TestCase):
    def test_end_to_end_mp4(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "sample.mp4")
            if not _make_sample(src):
                self.skipTest("ffmpeg unavailable or failed to synthesize sample")

            info = ffmpeg.probe(src)
            self.assertTrue(info.has_video)
            self.assertGreater(info.duration, 0)

            dest = os.path.join(tmp, "out.webm")
            result = converter.convert(
                src, dest, presets.PRESETS["webm_vp9"]
            )
            self.assertTrue(result.success, result.message)
            self.assertTrue(os.path.exists(dest))

    def test_gif_from_source_with_audio_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "sample.mp4")
            if not _make_sample(src):
                self.skipTest("ffmpeg unavailable or failed to synthesize sample")

            dest = os.path.join(tmp, "out.gif")
            result = converter.convert(
                src, dest, presets.PRESETS["gif"], threads=4
            )
            self.assertTrue(result.success, result.message)
            self.assertTrue(os.path.exists(dest))
            self.assertGreater(os.path.getsize(dest), 0)

    def test_failed_hwaccel_falls_back_to_cpu(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "sample.mp4")
            if not _make_sample(src):
                self.skipTest("ffmpeg unavailable or failed to synthesize sample")

            dest = os.path.join(tmp, "out.gif")
            messages: list[str] = []
            with mock.patch.dict(
                presets._HWACCEL_INPUT, {"cuda": ["-hwaccel", "does_not_exist"]}
            ):
                result = converter.convert(
                    src, dest, presets.PRESETS["gif"], threads=4,
                    hwaccel="cuda",
                    on_progress=lambda _f, m: messages.append(m),
                )
            self.assertTrue(result.success, result.message)
            self.assertTrue(os.path.exists(dest))
            self.assertTrue(any("retrying on CPU" in m for m in messages))


if __name__ == "__main__":
    unittest.main()
