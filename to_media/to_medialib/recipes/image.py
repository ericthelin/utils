"""Image formats, converted with ImageMagick. Orientation is applied and
metadata is kept unless asked otherwise."""

import sys

from .base import Recipe
from ..media import which

IMAGE_INPUTS = frozenset({".heic", ".heif", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff",
                          ".bmp", ".gif", ".avif"})


def imagemagick():
    """The ImageMagick command, or None. Windows' own convert.exe is not ImageMagick."""
    if which("magick"):
        return ["magick"]
    if sys.platform != "win32" and which("convert"):
        return ["convert"]
    return None


class ImageRecipe(Recipe):
    kind = "image"
    magick_format = ""
    default_quality = None
    own_extensions = frozenset()

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
