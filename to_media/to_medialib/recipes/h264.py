"""H.264 video with AAC audio, encoded with ffmpeg, in an MP4 (or an MKV).

Chapters, metadata and every audio track are kept and the picture is never
enlarged. Subtitles are handled deliberately: text subtitles are kept, image
subtitles (which MP4 cannot hold) are reported, and either kind can be
hard-coded into the picture or kept exactly by choosing the MKV container.
"""

import dataclasses
import functools
import os
import shlex
import shutil
import subprocess
import tempfile

from .base import Recipe
from ..jobs import Job
from ..media import (PICTURE_TYPES, RecipeError, attached_pictures, format_tags, main_video, probe,
                     probe_duration, run_checked, run_ffmpeg)

ALL_VIDEO = frozenset({".mkv", ".mp4", ".m4v", ".avi", ".mov", ".wmv", ".flv", ".webm", ".mpg", ".mpeg",
                       ".ts", ".m2ts", ".mts", ".vob", ".3gp", ".ogv", ".divx"})
SPEEDS = ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow")
PROFILES = {
    "fast720": {"crf": 23, "speed": "veryfast", "max_height": 720, "audio_bitrate": "128k"},
    "balanced": {"crf": 22, "speed": "medium", "max_height": None, "audio_bitrate": "160k"},
    "hq1080": {"crf": 19, "speed": "slow", "max_height": 1080, "audio_bitrate": "192k"},
}
DEFAULT_PROFILE = "balanced"

# Subtitle formats ffmpeg can convert to MP4's text format (mov_text), and the
# bitmap formats that MP4 cannot hold at all.
TEXT_SUBTITLES = frozenset({"subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "text", "microdvd",
                            "subviewer", "subviewer1", "sami", "jacosub", "realtext", "stl", "vplayer", "pjs"})
IMAGE_SUBTITLES = frozenset({"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle", "xsub"})


# The tag names MP4's standard (iTunes style) tag format can hold. Anything else
# needs QuickTime metadata, which ffmpeg-based players read but many tag editors
# do not.
STANDARD_MP4_TAGS = frozenset({
    "title", "artist", "album_artist", "album", "date", "year", "comment", "genre", "copyright", "grouping",
    "lyrics", "description", "synopsis", "show", "episode_id", "network", "season_number", "episode_sort",
    "composer", "track", "disc", "compilation", "gapless_playback", "category", "keywords", "media_type",
    "rating", "hd_video", "podcast", "episode_uid", "purl"})
IGNORED_TAGS = frozenset({"encoder", "creation_time", "major_brand", "minor_version", "compatible_brands",
                          "duration", "language", "handler_name", "vendor_id", "encoded_by"})
HDR_TRANSFERS = frozenset({"smpte2084", "arib-std-b67"})
TELEMETRY_TRACKS = frozenset({"gpmd", "tmcd", "camm", "mebx", "fdsc"})


def extra_tags(tags):
    """Tag names that MP4's standard format cannot hold."""
    return sorted(name for name in tags if name not in STANDARD_MP4_TAGS and name not in IGNORED_TAGS)


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


def subtitle_kind(codec):
    if codec in TEXT_SUBTITLES:
        return "text"
    if codec in IMAGE_SUBTITLES:
        return "image"
    return "other"


def subtitle_streams(info):
    return [s for s in info.get("streams", []) if s.get("codec_type") == "subtitle"]


def language_of(stream):
    return (stream.get("tags") or {}).get("language", "").lower()


def pick_subtitle(subtitles, selector):
    """Index (among the subtitle tracks) chosen by a number or a language code."""
    if not subtitles:
        raise RecipeError("--burn-subtitles: the video has no subtitle tracks")
    if str(selector).isdigit():
        index = int(selector)
        if index >= len(subtitles):
            raise RecipeError(f"--burn-subtitles: there is no subtitle track {index} "
                              f"(the video has {len(subtitles)})")
        return index
    wanted = str(selector).lower()
    for index, stream in enumerate(subtitles):
        language = language_of(stream)
        if language and (language == wanted or language.startswith(wanted) or wanted.startswith(language)):
            return index
    found = ", ".join(language_of(s) or "unknown" for s in subtitles)
    raise RecipeError(f"--burn-subtitles: no subtitle track matches '{selector}' (tracks: {found})")


@dataclasses.dataclass
class Plan:
    argv: list
    notes: list = dataclasses.field(default_factory=list)
    links: dict = dataclasses.field(default_factory=dict)
    soft_subtitles: int = 0
    covers: list = dataclasses.field(default_factory=list)  # pictures to extract and attach (MKV)


def link_source(name, target, folder):
    """Make `target` reachable as folder/name so a filter can name it without escaping."""
    path = os.path.join(folder, name)
    for attempt in (os.symlink, os.link, shutil.copyfile):
        try:
            attempt(target, path)
            return
        except OSError:
            continue
    raise RecipeError("could not prepare the source for subtitle burning")


class H264(Recipe):
    name = "h264"
    kind = "video"
    description = "H.264 + AAC video in an MP4 or MKV (ffmpeg); keeps chapters, metadata, audio and subtitles"
    output_ext = ".mp4"
    input_exts = ALL_VIDEO - {".mp4"}

    def requires(self):
        return ["ffmpeg"]

    def missing(self):
        missing = super().missing()
        if not missing and not has_encoder("libx264"):
            missing.append("an ffmpeg built with libx264")
        return missing

    def extension(self, options):
        return ".mkv" if options.get("container") == "mkv" else ".mp4"

    def source_extensions(self, options):
        return ALL_VIDEO - {self.extension(options)}

    def add_arguments(self, parser):
        group = parser.add_argument_group("h264 options")
        group.add_argument("--profile", choices=sorted(PROFILES),
                           help="starting point: fast720 (small, quick), balanced (default), hq1080 (best)")
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
        subtitles = parser.add_argument_group("subtitle options")
        subtitles.add_argument("--subtitles", choices=("keep", "none"), default="keep",
                               help="keep subtitle tracks (default) or drop them")
        subtitles.add_argument("--burn-subtitles", nargs="?", const="0", metavar="TRACK", dest="burn_subtitles",
                               help="hard-code one subtitle track into the picture, by number "
                                    "(0 is the first, the default) or language such as eng")
        subtitles.add_argument("--container", choices=("mp4", "mkv"), default="mp4",
                               help="mp4 (default) holds text subtitles only; mkv keeps every track")
        group.add_argument("--tags", choices=("auto", "all", "standard"), default="auto",
                           help="which tags an MP4 keeps: auto (default) keeps every tag unless that would cost "
                                "the cover picture; all always keeps every tag; standard keeps only the usual "
                                "MP4 tags plus the cover")

    def options_from_args(self, args):
        options = {}
        for key in ("profile", "crf", "speed", "max_height", "audio_bitrate", "fps", "burn_subtitles"):
            if getattr(args, key) is not None:
                options[key] = getattr(args, key)
        if args.deinterlace:
            options["deinterlace"] = True
        if args.encoder != "x264":
            options["encoder"] = args.encoder
        if args.subtitles != "keep":
            options["subtitles"] = args.subtitles
        if args.container != "mp4":
            options["container"] = args.container
        if args.tags != "auto":
            options["tags"] = args.tags
        return options

    def duration(self, job):
        return probe_duration(job.inputs[0])

    def build(self, job, tmp_output, info=None):
        """Work out the ffmpeg command, the notes for the user and any helper steps needed."""
        options = job.options
        chosen = settings(options)
        source = os.path.abspath(job.inputs[0])
        info = info if info is not None else probe(source)
        video = main_video(info)
        if video is None:
            raise RecipeError("the file has no video stream")
        v_index = video["index"]
        subtitles = subtitle_streams(info)
        pictures = attached_pictures(info)
        tags = format_tags(info)
        mkv = options.get("container") == "mkv"
        notes, links, covers = [], {}, []

        # MP4's usual tag format cannot hold arbitrary names; QuickTime metadata can, but
        # it stores every tag that way and has no place for a cover picture. Choose which
        # to keep when a file needs both, and say so.
        extras = extra_tags(tags)
        tag_mode = options.get("tags", "auto")
        quicktime_tags = False
        if not mkv and extras and tag_mode != "standard":
            shown = ", ".join(extras[:6]) + (f" and {len(extras) - 6} more" if len(extras) > 6 else "")
            if tag_mode == "all" or not pictures:
                quicktime_tags = True
                notes.append(f"{len(extras)} tag(s) that MP4's usual tag format cannot hold ({shown}) were kept by "
                             "storing all tags as QuickTime metadata; ffmpeg-based players (VLC, mpv, Plex, "
                             "Jellyfin) read it, but some tag editors do not. Use --container mkv for the most "
                             "compatible tags, or --tags standard to keep only the usual ones")
                if pictures:
                    notes.append(f"{len(pictures)} cover picture(s) cannot be stored alongside QuickTime metadata "
                                 "and were left out")
            else:
                notes.append(f"{len(extras)} tag(s) ({shown}) cannot be stored in an MP4 together with a cover "
                             "picture and were left out; use --container mkv to keep everything, or --tags all "
                             "to keep the tags instead of the cover")

        filters = ["yadif"] if options.get("deinterlace") else []
        burn_kind = None
        if options.get("burn_subtitles") is not None:
            burn_index = pick_subtitle(subtitles, options["burn_subtitles"])
            burn_kind = subtitle_kind(subtitles[burn_index].get("codec_name", ""))
            if burn_kind == "text":
                link = "source" + (os.path.splitext(source)[1] or ".mkv")
                links[link] = source
                filters.append(f"subtitles={link}:si={burn_index}")
            elif burn_kind == "other":
                raise RecipeError("--burn-subtitles: this subtitle format cannot be burned in")
        if chosen["max_height"]:
            filters.append(f"scale=-2:'min(ih,{chosen['max_height']})'")

        command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", source]
        if burn_kind == "image":
            graph = [f"[0:{v_index}][0:s:{burn_index}]overlay[ov]"]
            label = "[ov]"
            if filters:
                graph.append("[ov]" + ",".join(filters) + "[v]")
                label = "[v]"
            command += ["-filter_complex", ";".join(graph), "-map", label]
        else:
            command += ["-map", f"0:{v_index}"]
        command += ["-map", "0:a?"]

        # Cover pictures. MP4 holds them as attached pictures; in MKV they have to be
        # re-added as attachments, because copying the stream leaves a bare video track.
        if not mkv:
            for picture in ([] if quicktime_tags else pictures):
                command += ["-map", f"0:{picture['index']}"]
        else:
            covers = [{"index": p["index"], "codec": p.get("codec_name"), "tags": p.get("tags") or {}}
                      for p in pictures]

        soft = 0
        keep_subtitles = options.get("subtitles", "keep") != "none" and options.get("burn_subtitles") is None
        text_tracks = []
        fonts = 0
        if keep_subtitles and subtitles:
            if mkv:
                command += ["-map", "0:s?"]
                soft = len(subtitles)
            else:
                skipped = {"image": [], "other": []}
                for index, stream in enumerate(subtitles):
                    kind = subtitle_kind(stream.get("codec_name", ""))
                    if kind == "text":
                        text_tracks.append(index)
                        command += ["-map", f"0:s:{index}"]
                    else:
                        skipped[kind].append(stream.get("codec_name", "unknown"))
                soft = len(text_tracks)
                if skipped["image"]:
                    notes.append(
                        f"{len(skipped['image'])} image subtitle track(s) ({', '.join(sorted(set(skipped['image'])))}) "
                        "cannot be stored in an MP4 and were left out; use --burn-subtitles to hard-code one, "
                        "or --container mkv to keep them")
                if skipped["other"]:
                    notes.append(f"{len(skipped['other'])} subtitle track(s) in an unsupported format "
                                 f"({', '.join(sorted(set(skipped['other'])))}) were left out")
        if mkv and options.get("subtitles", "keep") != "none" and options.get("burn_subtitles") is None:
            command += ["-map", "0:t?"]
            fonts = sum(1 for s in info.get("streams", []) if s.get("codec_type") == "attachment")

        command += ["-map_metadata", "0", "-map_chapters", "0"]

        if filters and burn_kind != "image":
            command += ["-filter:v:0", ",".join(filters)]
        if options.get("fps"):
            command += ["-r:v:0", str(options["fps"])]
        if options.get("encoder") == "nvenc":
            command += ["-c:v:0", "h264_nvenc", "-preset:v:0", "p5", "-rc:v:0", "vbr", "-cq:v:0",
                        str(chosen["crf"]), "-b:v:0", "0"]
        else:
            command += ["-c:v:0", "libx264", "-crf:v:0", str(chosen["crf"]), "-preset:v:0", chosen["speed"]]
        command += ["-pix_fmt:v:0", "yuv420p"]
        if not mkv and not quicktime_tags:
            for number, picture in enumerate(pictures, start=1):
                codec = "copy" if picture.get("codec_name") in ("mjpeg", "png") else "mjpeg"
                command += [f"-c:v:{number}", codec, f"-disposition:v:{number}", "attached_pic"]
        command += ["-c:a", "aac", "-b:a", chosen["audio_bitrate"]]
        if mkv:
            command += (["-c:s", "copy", "-c:t", "copy"] if soft or fonts else [])
            for number, cover in enumerate(covers):
                extension, mime = PICTURE_TYPES.get(cover["codec"], (".jpg", "image/jpeg"))
                name = cover["tags"].get("filename") or f"cover{extension}"
                mime = cover["tags"].get("mimetype") or mime
                slot = fonts + number
                command += ["-attach", f"<cover:{number}>", f"-metadata:s:t:{slot}", f"mimetype={mime}",
                            f"-metadata:s:t:{slot}", f"filename={name}"]
            command += ["-f", "matroska"]
        else:
            command += (["-c:s", "mov_text"] if text_tracks else [])
            command += ["-movflags", "+faststart" + ("+use_metadata_tags" if quicktime_tags else ""), "-f", "mp4"]
        command.append(os.path.abspath(tmp_output))

        if video.get("color_transfer") in HDR_TRANSFERS:
            notes.append(f"the source is HDR ({video['color_transfer']}); H.264 output here is 8-bit SDR without "
                         "tone mapping, so colours will look flat")
        telemetry = sorted({s.get("codec_tag_string") for s in info.get("streams", [])
                            if s.get("codec_type") == "data" and s.get("codec_tag_string") in TELEMETRY_TRACKS})
        if telemetry:
            notes.append(f"camera data track(s) ({', '.join(telemetry)}) were not copied")
        return Plan(command, notes, links, soft, covers)

    def command(self, job, tmp_output):
        return self.build(job, tmp_output).argv

    def describe(self, job):
        plan = self.build(job, job.output)
        lines = [shlex.join(plan.argv)]
        if plan.links:
            lines.append("(the source is linked into a scratch folder so the subtitle filter can read it)")
        if plan.covers:
            lines.append(f"(first extracts {len(plan.covers)} cover picture(s) so they can be attached)")
        return "\n".join(lines + [f"note: {note}" for note in plan.notes])

    def extract_cover(self, source, cover, path):
        """Write one cover picture out as a file; pictures ffmpeg cannot copy become JPEG."""
        codec = "copy" if cover["codec"] in PICTURE_TYPES else "mjpeg"
        run_checked(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", source,
                     "-map", f"0:{cover['index']}", "-c:v", codec, "-frames:v", "1", "-f", "image2", path])

    def execute(self, plan, job, progress):
        duration = self.duration(job)
        if not plan.links and not plan.covers:
            run_ffmpeg(plan.argv, duration, progress)
            return
        with tempfile.TemporaryDirectory() as folder:
            for name, target in plan.links.items():
                link_source(name, target, folder)
            argv = list(plan.argv)
            for number, cover in enumerate(plan.covers):
                extension = PICTURE_TYPES.get(cover["codec"], (".jpg",))[0]
                path = os.path.join(folder, f"cover{number}{extension}")
                self.extract_cover(os.path.abspath(job.inputs[0]), cover, path)
                argv = [path if arg == f"<cover:{number}>" else arg for arg in argv]
            run_ffmpeg(argv, duration, progress, cwd=folder if plan.links else None)

    def run(self, job, tmp_output, progress=None):
        plan = self.build(job, tmp_output)
        try:
            self.execute(plan, job, progress)
        except RecipeError as error:
            if not plan.soft_subtitles:
                raise
            # A subtitle track that cannot be converted should not cost the whole file.
            retry = Job(job.recipe, job.inputs, job.output, dict(job.options, subtitles="none"))
            plan = self.build(retry, tmp_output)
            self.execute(plan, retry, progress)
            reason = str(error).splitlines()[0]
            return plan.notes + [f"the subtitle tracks could not be converted and were left out ({reason})"]
        return plan.notes
