#!/usr/bin/env python3
"""to_media: reshape files from one format to another (see README.md)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from to_medialib.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
