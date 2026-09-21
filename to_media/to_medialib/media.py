"""Helpers for finding and running external programs."""

import json
import os
import re
import shutil
import subprocess
import tempfile


class RecipeError(Exception):
    """A conversion failed; the message is shown to the user."""


def which(program):
    return shutil.which(program)


def missing_programs(programs):
    return [p for p in programs if not which(p)]


def run_quiet(argv):
    """Run a command, returning (exit code, the tail of its error output)."""
    done = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                          stderr=subprocess.PIPE, text=True, errors="replace")
    return done.returncode, "\n".join(done.stderr.strip().splitlines()[-5:])


def run_checked(argv):
    code, tail = run_quiet(argv)
    if code != 0:
        raise RecipeError(f"{os.path.basename(argv[0])} failed (exit {code}): {tail}")


def probe_duration(path):
    """Length in seconds, or None when it cannot be read."""
    try:
        return float(probe(path)["format"]["duration"])
    except (RecipeError, KeyError, ValueError):
        return None


def run_ffmpeg(argv, duration=None, progress=None):
    """Run ffmpeg. When the length is known, progress(fraction) is called as it runs."""
    command = [argv[0], "-progress", "pipe:1", "-nostats"] + argv[1:]
    with tempfile.TemporaryFile("w+", errors="replace") as errors:
        with subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=errors, text=True) as process:
            for line in process.stdout:
                key, _, value = line.strip().partition("=")
                if progress and duration and key == "out_time_us" and value.lstrip("-").isdigit():
                    progress(min(1.0, max(0.0, int(value) / 1e6 / duration)))
        if process.returncode:
            errors.seek(0)
            tail = "\n".join(errors.read().strip().splitlines()[-5:])
            raise RecipeError(f"ffmpeg failed (exit {process.returncode}): {tail}")
    if progress and duration:
        progress(1.0)


def probe(path):
    """Return ffprobe's format and stream information for a file as a dict."""
    done = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
         "-show_chapters", path],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace")
    if done.returncode != 0:
        raise RecipeError(f"ffprobe could not read {path}")
    return json.loads(done.stdout)


def natural_key(text):
    """Sort key that orders 'track 2' before 'track 10'."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", text)]


def safe_filename(text):
    text = re.sub(r'[\\<>"|?*:,/]', "_", text)
    return re.sub(r"\s+", " ", text).strip()
