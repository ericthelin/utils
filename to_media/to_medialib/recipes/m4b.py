"""Chaptered audiobooks (.m4b): a folder of audio files becomes one book with a
chapter per file."""

import datetime
import os
import re
import tempfile

from .base import Recipe
from ..jobs import Job
from ..media import RecipeError, natural_key, probe, run_checked, safe_filename

BOOK_INPUTS = frozenset({".mp3", ".opus", ".m4a", ".ogg", ".flac", ".wav", ".aac"})
DEFAULT_BITRATE = "32k"


def clean_track_name(stem):
    """Drop leading track numbers such as '01 - ', '001_' or '12.'."""
    stem = re.sub(r"^\d{1,3}\s+-\s*", "", stem)
    return re.sub(r"^\d{1,3}[._-]+", "", stem).strip()


def chapter_title(filename, number):
    stem = clean_track_name(os.path.splitext(os.path.basename(filename))[0])
    stem = re.sub(r"\s+-\s*\d+\s*$", "", stem)
    stem = re.sub(r"^(Chapter|Ch\.?)\s*\d+[\s._-]*", "", stem, flags=re.IGNORECASE)
    return stem.strip() or f"Chapter {number}"


def parse_book_name(name):
    """Split 'Author - Title (Narrator)' or 'Title by Author' into (title, author, narrator)."""
    match = re.match(r"^(.+?)\s+-\s+(.+?)\s*\((.+?)\)$", name)
    if match:
        return match.group(2), match.group(1), match.group(3)
    match = re.match(r"^(.+?)\s+-\s+(.+)$", name)
    if match:
        return match.group(2), match.group(1), None
    match = re.match(r"^(.+?)\s+by\s+(.+)$", name, flags=re.IGNORECASE)
    if match:
        return match.group(1), match.group(2), None
    return (name or None), None, None


def book_filename(title, author):
    name = f"{author} - {title}" if author and title else (title or "Unknown Audiobook")
    return safe_filename(name) + ".m4b"


def escape_ffmetadata(value):
    return re.sub(r"([=;#\\\n])", r"\\\1", value)


def chapters_metadata(chapters):
    """ffmpeg metadata text for [(title, start_seconds, end_seconds), ...]."""
    lines = [";FFMETADATA1"]
    for title, start, end in chapters:
        lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={int(start * 1000)}",
                  f"END={int(end * 1000)}", f"title={escape_ffmetadata(title)}"]
    return "\n".join(lines) + "\n"


def file_tags(path):
    tags = {k.lower(): v for k, v in probe(path).get("format", {}).get("tags", {}).items()}
    return {"title": tags.get("album") or tags.get("title"),
            "author": tags.get("album_artist") or tags.get("artist"),
            "narrator": tags.get("narrator") or tags.get("composer")}


class M4b(Recipe):
    name = "m4b"
    kind = "audio"
    description = "chaptered audiobook: a folder of audio files becomes one .m4b"
    output_ext = ".m4b"
    input_exts = BOOK_INPUTS
    many_to_one = True

    def requires(self):
        return ["ffmpeg", "ffprobe"]

    def add_arguments(self, parser):
        group = parser.add_argument_group("m4b options")
        group.add_argument("--title", help="book title (default: from the folder name or tags)")
        group.add_argument("--author", help="author (default: from the folder name or tags)")
        group.add_argument("--narrator", help="narrator (stored in the composer tag)")
        group.add_argument("--combine", action="store_true",
                           help="combine the individual files given into one book")
        group.add_argument("--bitrate", default=DEFAULT_BITRATE, metavar="RATE",
                           help=f"AAC bitrate (default {DEFAULT_BITRATE})")

    def options_from_args(self, args):
        options = {"bitrate": args.bitrate}
        for key in ("title", "author", "narrator"):
            if getattr(args, key):
                options[key] = getattr(args, key)
        if args.combine:
            options["combine"] = True
        return options

    def groups(self, sources, combine):
        """Each folder given is one book; loose files are one book together
        with --combine, otherwise one book each."""
        folders, loose = {}, []
        for source in sources:
            if source.root:
                folders.setdefault(source.root, []).append(source)
            else:
                loose.append(source)
        books = [(root, items) for root, items in folders.items()]
        if combine and loose:
            books.append((None, loose))
        else:
            books.extend((None, [item]) for item in loose)
        return books

    def plan(self, sources, options, out_dir):
        jobs = []
        for root, items in self.groups(sources, options.get("combine")):
            paths = [item.path for item in items]
            if root:
                name, home = os.path.basename(os.path.abspath(root)), os.path.dirname(os.path.abspath(root))
            elif len(paths) == 1:
                name, home = clean_track_name(os.path.splitext(os.path.basename(paths[0]))[0]), os.path.dirname(os.path.abspath(paths[0]))
            else:
                name, home = os.path.basename(os.path.dirname(os.path.abspath(paths[0]))), os.path.dirname(os.path.abspath(paths[0]))
            title, author, narrator = parse_book_name(name)
            tags = file_tags(paths[0])
            resolved = dict(options)
            resolved["title"] = options.get("title") or title or tags["title"]
            resolved["author"] = options.get("author") or author or tags["author"]
            narrator = options.get("narrator") or narrator or tags["narrator"]
            if narrator:
                resolved["narrator"] = narrator
            resolved.pop("combine", None)
            output = os.path.join(out_dir or home, book_filename(resolved["title"], resolved["author"]))
            jobs.append(Job(self.name, paths, output, resolved))
        return jobs

    def describe(self, job):
        return f"ffmpeg: join {len(job.inputs)} file(s) into {job.output} with one chapter per file"

    def run(self, job, tmp_output):
        options = job.options
        chapters, position = [], 0.0
        for number, path in enumerate(job.inputs, 1):
            try:
                duration = float(probe(path)["format"]["duration"])
            except (KeyError, ValueError):
                raise RecipeError(f"cannot read the duration of {path}")
            chapters.append((chapter_title(path, number), position, position + duration))
            position += duration
        with tempfile.TemporaryDirectory() as work:
            concat = os.path.join(work, "concat.txt")
            metadata = os.path.join(work, "chapters.txt")
            with open(concat, "w", encoding="utf-8") as handle:
                for path in job.inputs:
                    handle.write("file '%s'\n" % os.path.abspath(path).replace("'", "'\\''"))
            with open(metadata, "w", encoding="utf-8") as handle:
                handle.write(chapters_metadata(chapters))
            command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                       "-f", "concat", "-safe", "0", "-i", concat, "-i", metadata,
                       "-map", "0:a:0", "-map_metadata", "1", "-codec:a", "aac",
                       "-b:a", options.get("bitrate", DEFAULT_BITRATE)]
            for key, tag in (("title", "title"), ("author", "artist"), ("author", "album_artist"),
                             ("narrator", "composer")):
                if options.get(key):
                    command += ["-metadata", f"{tag}={options[key]}"]
            command += ["-metadata", "genre=Audiobook", "-movflags", "+faststart", "-f", "mp4", tmp_output]
            run_checked(command)
