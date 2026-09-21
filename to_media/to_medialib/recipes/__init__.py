"""The registry of output formats."""

from .image import Jpg, Png, Webp
from .m4b import M4b
from .mp3 import Mp3

RECIPES = [Mp3(), M4b(), Jpg(), Png(), Webp()]


def get(name):
    name = name.lower()
    for recipe in RECIPES:
        if name == recipe.name or name in getattr(recipe, "aliases", ()):
            return recipe
    return None


def names():
    return [recipe.name for recipe in RECIPES]
