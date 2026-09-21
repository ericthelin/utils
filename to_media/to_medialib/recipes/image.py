"""Image formats, converted with ImageMagick. Orientation is applied and
metadata is kept unless asked otherwise."""

import shlex
import subprocess
import sys

from .base import Recipe
from ..media import run_checked, which

IMAGE_INPUTS = frozenset({".heic", ".heif", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff",
                          ".bmp", ".gif", ".avif"})


def imagemagick():
    """The ImageMagick command, or None. Windows' own convert.exe is not ImageMagick."""
    if which("magick"):
        return ["magick"]
    if sys.platform != "win32" and which("convert"):
        return ["convert"]
    return None


def source_profiles(path):
    """The embedded profiles of an image (exif, iptc, xmp, icc...), lower-cased."""
    identify = ["magick", "identify"] if imagemagick() == ["magick"] else ["identify"]
    done = subprocess.run(identify + ["-format", "%[profiles]", path + "[0]"], capture_output=True,
                          text=True, stdin=subprocess.DEVNULL)
    return {name.strip().lower() for name in done.stdout.split(",") if name.strip()}


class ImageRecipe(Recipe):
    kind = "image"
    magick_format = ""
    default_quality = None
    own_extensions = frozenset()
    cannot_store = {}   # profile name -> what it holds, for formats that cannot keep it

    @property
    def input_exts(self):
        return IMAGE_INPUTS - self.own_extensions

    def missing(self):
        return [] if imagemagick() else ["ImageMagick (magick or convert)"]

    def add_arguments(self, parser):
        group = parser.add_argument_group(f"{self.name} options")
        if self.default_quality:
            group.add_argument("--quality", type=int, choices=range(1, 101), metavar="1-100",
                               help=f"compression quality (default {self.default_quality})")
        group.add_argument("--max", type=int, metavar="PIXELS", dest="max_size",
                           help="shrink so the longest side is at most PIXELS (never enlarges)")
        group.add_argument("--strip", action="store_true", help="remove metadata (EXIF, profiles)")

    def options_from_args(self, args):
        options = {}
        if getattr(args, "quality", None) is not None:
            options["quality"] = args.quality
        if args.max_size:
            options["max_size"] = args.max_size
        if args.strip:
            options["strip"] = True
        return options

    def command(self, job, tmp_output):
        options = job.options
        command = imagemagick() + [job.inputs[0] + "[0]", "-auto-orient"]
        if options.get("max_size"):
            command += ["-resize", f"{options['max_size']}x{options['max_size']}>"]
        quality = options.get("quality", self.default_quality)
        if quality:
            command += ["-quality", str(quality)]
        if options.get("strip"):
            command.append("-strip")
        return command + [f"{self.magick_format}:{tmp_output}"]

    def notes(self, job):
        if not self.cannot_store or job.options.get("strip"):
            return []
        lost = [what for name, what in self.cannot_store.items() if name in source_profiles(job.inputs[0])]
        if not lost:
            return []
        return [f"{' and '.join(lost)} cannot be stored in {self.name.upper()} and was left out; "
                "use jpg or png to keep it"]

    def run(self, job, tmp_output, progress=None):
        run_checked(self.command(job, tmp_output))
        return self.notes(job)

    def describe(self, job):
        return "\n".join([shlex.join(self.command(job, job.output))] + [f"note: {n}" for n in self.notes(job)])


class Jpg(ImageRecipe):
    name = "jpg"
    aliases = ("jpeg",)
    description = "JPEG images (ImageMagick); reads HEIC when ImageMagick supports it"
    output_ext = ".jpg"
    magick_format = "jpeg"
    default_quality = 90
    own_extensions = frozenset({".jpg", ".jpeg"})


class Png(ImageRecipe):
    name = "png"
    description = "PNG images (ImageMagick)"
    output_ext = ".png"
    magick_format = "png"
    own_extensions = frozenset({".png"})


class Webp(ImageRecipe):
    name = "webp"
    description = "WebP images (ImageMagick)"
    output_ext = ".webp"
    magick_format = "webp"
    default_quality = 85
    own_extensions = frozenset({".webp"})
    cannot_store = {"iptc": "IPTC data (keywords, caption, credits)"}
