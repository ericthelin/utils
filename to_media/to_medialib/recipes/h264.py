"""H.264 video with AAC audio in an MP4, encoded with ffmpeg. Chapters, metadata
and every audio track are kept; the picture is never enlarged."""

import functools
import subprocess

from .base import Recipe
from ..media import probe_duration

VIDEO_INPUTS = frozenset({".mkv", ".m4v", ".avi", ".mov", ".wmv", ".flv", ".webm", ".mpg", ".mpeg",
                          ".ts", ".m2ts", ".mts", ".vob", ".3gp", ".ogv", ".divx"})
SPEEDS = ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow")
PROFILES = {
    "fast720": {"crf": 23, "speed": "veryfast", "max_height": 720, "audio_bitrate": "128k"},
    "balanced": {"crf": 22, "speed": "medium", "max_height": None, "audio_bitrate": "160k"},
    "hq1080": {"crf": 19, "speed": "slow", "max_height": 1080, "audio_bitrate": "192k"},
}
DEFAULT_PROFILE = "balanced"


@functools.lru_cache(maxsize=None)
def has_encoder(name):
    try:
        done = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True)
    except OSError:
        return False
    return any(line.split()[1:2] == [name] for line in done.stdout.splitlines())


def settings(options):
    """The profile's values with any explicit options laid over them."""
    merged = dict(PROFILES[options.get("profile", DEFAULT_PROFILE)])
    for key in ("crf", "speed", "max_height", "audio_bitrate"):
        if options.get(key) is not None:
            merged[key] = options[key]
    return merged


class H264(Recipe):
    name = "h264"
    kind = "video"
    description = "H.264 + AAC video in an MP4 (ffmpeg); keeps chapters, metadata and all audio"
    output_ext = ".mp4"
    input_exts = VIDEO_INPUTS

    def requires(self):
        return ["ffmpeg"]

    def missing(self):
        missing = super().missing()
        if not missing and not has_encoder("libx264"):
            missing.append("an ffmpeg built with libx264")
        return missing

    def add_arguments(self, parser):
        group = parser.add_argument_group("h264 options")
        group.add_argument("--profile", choices=sorted(PROFILES),
                           help=f"starting point: fast720 (small, quick), balanced (default), hq1080 (best)")
        group.add_argument("--crf", type=int, choices=range(0, 52), metavar="0-51",
                           help="quality, lower is better (profile default: 19 to 23)")
        group.add_argument("--speed", choices=SPEEDS, help="encoder speed; slower is smaller")
        group.add_argument("--max-height", type=int, metavar="PIXELS", dest="max_height",
                           help="scale down so the picture is at most this tall (never enlarges)")
        group.add_argument("--audio-bitrate", metavar="RATE", dest="audio_bitrate", help="AAC bitrate, e.g. 160k")
        group.add_argument("--fps", type=float, help="force a frame rate")
        group.add_argument("--deinterlace", action="store_true", help="deinterlace the picture (yadif)")
        group.add_argument("--encoder", choices=("x264", "nvenc"), default="x264",
                           help="x264 (CPU, default) or nvenc (NVIDIA GPU, faster)")

    def options_from_args(self, args):
        options = {}
        for key in ("profile", "crf", "speed", "max_height", "audio_bitrate", "fps"):
            if getattr(args, key) is not None:
                options[key] = getattr(args, key)
        if args.deinterlace:
            options["deinterlace"] = True
        if args.encoder != "x264":
            options["encoder"] = args.encoder
        return options

    def duration(self, job):
        return probe_duration(job.inputs[0])

    def command(self, job, tmp_output):
        options = job.options
        chosen = settings(options)
        filters = []
        if options.get("deinterlace"):
            filters.append("yadif")
        if chosen["max_height"]:
            filters.append(f"scale=-2:'min(ih,{chosen['max_height']})'")
        command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", job.inputs[0],
                   "-map", "0:v:0", "-map", "0:a?", "-map_metadata", "0", "-map_chapters", "0"]
        if filters:
            command += ["-vf", ",".join(filters)]
        if options.get("fps"):
            command += ["-r", str(options["fps"])]
        if options.get("encoder") == "nvenc":
            command += ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", str(chosen["crf"]),
                        "-b:v", "0"]
        else:
            command += ["-c:v", "libx264", "-crf", str(chosen["crf"]), "-preset", chosen["speed"]]
        command += ["-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", chosen["audio_bitrate"],
                    "-movflags", "+faststart", "-f", "mp4", tmp_output]
        return command
