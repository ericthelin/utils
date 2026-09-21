"""Turn the paths given on the command line into the files to convert."""

import dataclasses
import os

from .media import natural_key


@dataclasses.dataclass
class Source:
    path: str
    root: str = None


def collect(paths, extensions):
    """Expand files and folders. Folders are searched recursively for the given
    extensions; files named explicitly are always kept. Returns (sources, problems).
    """
    sources, problems = [], []
    for path in paths:
        if os.path.isdir(path):
            found = []
            for folder, dirs, files in os.walk(path):
                dirs.sort(key=natural_key)
                for name in files:
                    if os.path.splitext(name)[1].lower() in extensions:
                        found.append(os.path.join(folder, name))
            sources.extend(Source(p, path) for p in sorted(found, key=natural_key))
        elif os.path.isfile(path):
            sources.append(Source(path))
        else:
            problems.append(f"not a file or folder: {path}")
    return sources, problems
