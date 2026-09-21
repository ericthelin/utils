"""MP3 audio, encoded with ffmpeg and LAME. Tags are carried over."""

from .base import Recipe
from ..media import probe_duration

AUDIO_INPUTS = frozenset({".flac", ".wav", ".aiff", ".aif", ".m4a", ".m4b", ".aac", ".ogg", ".oga",
                          ".opus", ".wma", ".wv", ".ape"})
DEFAULT_QUALITY = 3
AUDIOBOOK_QUALITY = 8


class Mp3(Recipe):
    name = "mp3"
    kind = "audio"
    description = "MP3 audio (ffmpeg + LAME), tags carried over"
    output_ext = ".mp3"
    input_exts = AUDIO_INPUTS

    def requires(self):
        return ["ffmpeg"]

    def add_arguments(self, parser):
        group = parser.add_argument_group("mp3 options")
        group.add_argument("--quality", type=int, choices=range(0, 10), metavar="0-9",
                           help=f"VBR quality, 0 is best (default {DEFAULT_QUALITY})")
        group.add_argument("--bitrate", metavar="RATE", help="constant bitrate instead, e.g. 192k")
        group.add_argument("--audiobook", action="store_true",
                           help="small mono files for spoken word")

    def options_from_args(self, args):
        options = {}
        if args.quality is not None:
            options["quality"] = args.quality
        if args.bitrate:
            options["bitrate"] = args.bitrate
        if args.audiobook:
            options["audiobook"] = True
        return options

    def duration(self, job):
        return probe_duration(job.inputs[0])

    def command(self, job, tmp_output):
        options = job.options
        audiobook = options.get("audiobook", False)
        command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", job.inputs[0],
                   "-map", "0:a:0", "-map_metadata", "0", "-codec:a", "libmp3lame"]
        if options.get("bitrate"):
            command += ["-b:a", options["bitrate"]]
        else:
            command += ["-q:a", str(options.get("quality", AUDIOBOOK_QUALITY if audiobook else DEFAULT_QUALITY))]
        if audiobook:
            command += ["-ac", "1", "-metadata", "genre=Audiobook"]
        return command + ["-id3v2_version", "3", "-write_id3v1", "1", "-f", "mp3", tmp_output]
