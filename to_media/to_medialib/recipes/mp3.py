"""MP3 audio, encoded with ffmpeg and LAME. Tags and cover art are carried over."""

import shlex

from .base import Recipe
from ..media import attached_pictures, format_tags, probe, run_ffmpeg

AUDIO_INPUTS = frozenset({".flac", ".wav", ".aiff", ".aif", ".m4a", ".m4b", ".aac", ".ogg", ".oga",
                          ".opus", ".wma", ".wv", ".ape"})
DEFAULT_QUALITY = 3
AUDIOBOOK_QUALITY = 8

# Other formats name these fields differently from ID3. ffmpeg only writes a real
# ID3 frame for a name it knows, so these are renamed to the frame's own ID.
NATIVE_FRAMES = {"isrc": "TSRC", "bpm": "TBPM", "initialkey": "TKEY", "mood": "TMOO", "language": "TLAN",
                 "encodedby": "encoded_by"}
NUMBERED = (("track", ("track", "tracknumber"), ("tracktotal", "totaltracks", "tracks")),
            ("disc", ("disc", "discnumber"), ("disctotal", "totaldiscs", "discs")))


def first_present(tags, names):
    return next((name for name in names if tags.get(name)), None)


def id3_tag_fixes(tags):
    """(name, value) pairs to apply on top of ffmpeg's own tag copy; an empty
    value removes that field. Merges 'track' and 'tracktotal' into 'track=3/12'
    (likewise for discs) and renames fields that have a real ID3 frame."""
    fixes = []
    for name, number_names, total_names in NUMBERED:
        number, total = first_present(tags, number_names), first_present(tags, total_names)
        if number and total and "/" not in tags[number]:
            fixes.append((name, f"{tags[number]}/{tags[total]}"))
            fixes.extend((other, "") for other in number_names + total_names if other != name and tags.get(other))
    for source, frame in NATIVE_FRAMES.items():
        if tags.get(source) and frame.lower() not in tags:
            fixes.extend([(frame, tags[source]), (source, "")])
    return fixes


class Mp3(Recipe):
    name = "mp3"
    kind = "audio"
    description = "MP3 audio (ffmpeg + LAME); tags and cover art carried over"
    output_ext = ".mp3"
    input_exts = AUDIO_INPUTS

    def requires(self):
        return ["ffmpeg", "ffprobe"]

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

    def build(self, job, tmp_output, info=None):
        options = job.options
        info = info if info is not None else probe(job.inputs[0])
        audiobook = options.get("audiobook", False)
        pictures = attached_pictures(info)
        command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", job.inputs[0],
                   "-map", "0:a:0"]
        for picture in pictures:
            command += ["-map", f"0:{picture['index']}"]
        command += ["-map_metadata", "0", "-codec:a", "libmp3lame"]
        if options.get("bitrate"):
            command += ["-b:a", options["bitrate"]]
        else:
            command += ["-q:a", str(options.get("quality", AUDIOBOOK_QUALITY if audiobook else DEFAULT_QUALITY))]
        for number, picture in enumerate(pictures):
            codec = "copy" if picture.get("codec_name") in ("mjpeg", "png") else "mjpeg"
            command += [f"-c:v:{number}", codec, f"-disposition:v:{number}", "attached_pic"]
        for name, value in id3_tag_fixes(format_tags(info)):
            command += ["-metadata", f"{name}={value}"]
        if audiobook:
            command += ["-ac", "1", "-metadata", "genre=Audiobook"]
        return command + ["-id3v2_version", "3", "-write_id3v1", "1", "-f", "mp3", tmp_output]

    def command(self, job, tmp_output):
        return self.build(job, tmp_output)

    def describe(self, job):
        return shlex.join(self.build(job, job.output))

    def run(self, job, tmp_output, progress=None):
        info = probe(job.inputs[0])
        try:
            duration = float(info["format"]["duration"])
        except (KeyError, ValueError):
            duration = None
        run_ffmpeg(self.build(job, tmp_output, info), duration, progress)
