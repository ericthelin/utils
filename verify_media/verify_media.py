#!/usr/bin/env python3
"""verify_media: check downloaded media files for truncation and corruption (see README.md)."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from collections import namedtuple
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

MEDIA_EXTENSIONS = {
    ".mp3", ".m4a", ".m4b", ".aac", ".flac", ".ogg", ".opus", ".wma", ".wav",
    ".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".wmv", ".mpg", ".mpeg", ".ts",
}
ZERO_RUN_EXEMPT = {".wav"}
DEFAULT_ZERO_RUN = 256 * 1024
DURATION_TOLERANCE_SECONDS = 2.0
DURATION_TOLERANCE_RATIO = 0.01
CHUNK_SIZE = 1024 * 1024
ZERO_RUN = re.compile(rb"\0+")
PROGRESS_LINE = re.compile(
    r"^(frame|fps|stream_\d+_\d+_q|bitrate|total_size|out_time_us|out_time_ms|out_time|"
    r"dup_frames|drop_frames|speed|progress)=")
REDRAW_SECONDS = 0.25
ANSWERS = {"y": "y", "yes": "y", "n": "n", "no": "n", "": "n",
           "a": "a", "all": "a", "q": "q", "quit": "q"}

Unit = namedtuple("Unit", "path files")

CANCEL = threading.Event()
ACTIVE = {}
ACTIVE_LOCK = threading.Lock()
CURRENT = threading.local()


class Cancelled(Exception):
    pass


def is_media(path):
    return os.path.splitext(path)[1].lower() in MEDIA_EXTENSIONS


def find_media(paths):
    for path in paths:
        if os.path.isdir(path):
            for root, dirs, files in os.walk(path):
                dirs.sort()
                for name in sorted(files):
                    full = os.path.join(root, name)
                    if is_media(full):
                        yield full
        else:
            yield path


def build_units(paths):
    seen = set()
    units = []
    loose = []
    for path in paths:
        if os.path.isdir(path):
            files = [f for f in find_media([path]) if f not in seen]
            seen.update(files)
            units.append(Unit(os.path.normpath(path), files))
        elif path not in seen:
            seen.add(path)
            loose.append(path)
    if loose:
        units.append(Unit(None, loose))
    return units


def check_cancelled():
    if CANCEL.is_set() or getattr(CURRENT, "stop", threading.Event()).is_set():
        raise Cancelled()


def longest_zero_run(path, on_progress=None):
    longest = carried = read = 0
    size = os.path.getsize(path) or 1
    with open(path, "rb") as handle:
        while True:
            check_cancelled()
            chunk = handle.read(CHUNK_SIZE)
            if not chunk:
                break
            carried_next = 0
            for match in ZERO_RUN.finditer(chunk):
                length = match.end() - match.start()
                if match.start() == 0:
                    length += carried
                longest = max(longest, length)
                if match.end() == len(chunk):
                    carried_next = length
            carried = carried_next
            read += len(chunk)
            if on_progress:
                on_progress(read / size)
    return longest


def duration_mismatch(container_seconds, decoded_seconds):
    if not container_seconds or decoded_seconds is None:
        return False
    shortfall = container_seconds - decoded_seconds
    allowed = max(DURATION_TOLERANCE_SECONDS, container_seconds * DURATION_TOLERANCE_RATIO)
    return shortfall > allowed


def is_progress_line(line):
    return bool(PROGRESS_LINE.match(line))


def parse_progress_seconds(line):
    key, _, value = line.partition("=")
    if key in ("out_time_us", "out_time_ms") and value.strip().isdigit():
        return int(value) / 1_000_000
    return None


def probe_command(path):
    return ["ffprobe", "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", path]


def decode_command(path):
    return ["ffmpeg", "-v", "error", "-nostdin", "-progress", "pipe:1",
            "-i", path, "-map", "0:a?", "-map", "0:v?", "-f", "null", "-"]


def container_duration(probe_json):
    try:
        return float(probe_json["format"]["duration"])
    except (KeyError, TypeError, ValueError):
        return None


def has_media_stream(probe_json):
    kinds = {s.get("codec_type") for s in probe_json.get("streams", [])}
    return bool(kinds & {"audio", "video"})


def spawn(command, **kwargs):
    check_cancelled()
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, text=True, errors="replace", **kwargs)
    with ACTIVE_LOCK:
        ACTIVE[process] = getattr(CURRENT, "stop", None)
    return process


def release(process):
    with ACTIVE_LOCK:
        ACTIVE.pop(process, None)
    for stream in (process.stdout, process.stderr):
        if stream:
            stream.close()
    process.wait()


def kill_active(stop=None):
    with ACTIVE_LOCK:
        processes = [p for p, owner in ACTIVE.items() if stop is None or owner is stop]
    for process in processes:
        try:
            process.kill()
        except OSError:
            pass


def run_probe(path):
    process = spawn(probe_command(path), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        out, err = process.communicate()
    finally:
        release(process)
    check_cancelled()
    return process.returncode, out, err


def run_decode(path, on_seconds=None):
    process = spawn(decode_command(path), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    errors = []
    decoded = None
    try:
        for raw in process.stdout:
            line = raw.rstrip("\n")
            if is_progress_line(line):
                seconds = parse_progress_seconds(line)
                if seconds is not None:
                    decoded = seconds
                    if on_seconds:
                        on_seconds(seconds)
            elif line.strip():
                errors.append(line)
    finally:
        release(process)
    check_cancelled()
    return process.returncode, errors, decoded


def check_file(path, zero_run_limit, quick, report=None):
    report = report or (lambda stage, fraction: None)
    try:
        size = os.path.getsize(path)
    except OSError as error:
        return ["unreadable: %s" % error.strerror]
    if size == 0:
        return ["empty file"]

    problems = []
    ext = os.path.splitext(path)[1].lower()
    if zero_run_limit and ext not in ZERO_RUN_EXEMPT:
        report("scan", 0)
        run_length = longest_zero_run(path, lambda fraction: report("scan", fraction))
        if run_length >= zero_run_limit:
            problems.append("zero-filled gap of %d KiB (missing torrent pieces?)" % (run_length // 1024))

    report("probe", None)
    returncode, out, err = run_probe(path)
    if returncode != 0 or err.strip():
        first = (err.strip().splitlines() or ["ffprobe failed"])[0]
        problems.append("unreadable container: %s" % first)
        return problems
    info = json.loads(out)
    if not has_media_stream(info):
        problems.append("no audio or video streams")
        return problems
    if quick:
        return problems

    expected = container_duration(info)
    report("decode", 0)
    returncode, errors, decoded = run_decode(
        path, lambda seconds: report("decode", min(1.0, seconds / expected) if expected else None))
    if returncode != 0 or errors:
        sample = errors[0] if errors else "ffmpeg exited %d" % returncode
        problems.append("decode errors (%d lines), first: %s" % (len(errors), sample))
    if duration_mismatch(expected, decoded):
        problems.append("truncated: header says %.1fs, only %.1fs decodes" % (expected, decoded))
    return problems


def safe_check(path, zero_run_limit, quick, report):
    try:
        return check_file(path, zero_run_limit, quick, report)
    except Cancelled:
        raise
    except Exception as error:
        return ["check failed: %s" % error]


def format_status(done, total, active, width):
    line = "[%d/%d]" % (done, total)
    labels = []
    for name, stage, fraction in active:
        label = "%s %s" % (name, stage)
        if fraction is not None:
            label += " %d%%" % int(fraction * 100)
        labels.append(label)
    if labels:
        line += " " + " | ".join(labels)
    return line[:max(width - 1, 10)]


class Progress:
    def __init__(self, total, stream):
        self.total = total
        self.done = 0
        self.active = {}
        self.lock = threading.Lock()
        self.stream = stream
        self.live = stream.isatty()
        self.shown = False

    def begin(self, path):
        with self.lock:
            self.active[path] = ("queued", None)
        if not self.live:
            print("CHECK %s" % path, file=self.stream, flush=True)

    def update(self, path, stage, fraction):
        with self.lock:
            self.active[path] = (stage, fraction)

    def finish(self, path):
        with self.lock:
            self.active.pop(path, None)
            self.done += 1

    def skip(self, path):
        with self.lock:
            self.active.pop(path, None)
            self.total -= 1

    def render(self):
        if not self.live:
            return
        with self.lock:
            active = [(os.path.basename(p), s, f) for p, (s, f) in self.active.items()]
            done = self.done
        width = shutil.get_terminal_size().columns
        self.stream.write("\r" + format_status(done, self.total, active, width) + "\x1b[K")
        self.stream.flush()
        self.shown = True

    def clear(self):
        if self.shown:
            self.stream.write("\r\x1b[K")
            self.stream.flush()
            self.shown = False

    def say(self, text="", file=None):
        self.clear()
        print(text, file=file or sys.stdout, flush=True)


def check_unit(pool, files, zero_run_limit, quick, progress, verbose, stop_on_bad=False):
    unit_stop = threading.Event()

    def work(path):
        CURRENT.stop = unit_stop
        progress.begin(path)
        try:
            return safe_check(path, zero_run_limit, quick, lambda s, f: progress.update(path, s, f))
        except Cancelled:
            if unit_stop.is_set() and not CANCEL.is_set():
                return None
            raise

    futures = {pool.submit(work, f): f for f in files}
    problems_by_file = {}
    pending = set(futures)
    while pending:
        done, pending = wait(pending, timeout=REDRAW_SECONDS, return_when=FIRST_COMPLETED)
        for future in done:
            path = futures[future]
            problems = None if future.cancelled() else future.result()
            if problems is None:
                progress.skip(path)
                continue
            problems_by_file[path] = problems
            progress.finish(path)
            if problems:
                progress.say("BAD  %s" % path)
                for problem in problems:
                    progress.say("       - %s" % problem)
                if stop_on_bad and not unit_stop.is_set():
                    unit_stop.set()
                    kill_active(unit_stop)
                    for waiting in list(pending):
                        if waiting.cancel():
                            pending.discard(waiting)
                            progress.skip(futures[waiting])
            elif verbose:
                progress.say("OK   %s" % path)
        progress.render()
    progress.clear()
    return problems_by_file


def is_within(path, directory):
    return os.path.commonpath([os.path.abspath(path), os.path.abspath(directory)]) == os.path.abspath(directory)


def destination_for(source, dest_root):
    return os.path.join(dest_root, os.path.basename(os.path.abspath(source)))


def parse_answer(text):
    return ANSWERS.get(text.strip().lower())


def ask_move(source, target, bad=0):
    warning = " (%d BAD file%s)" % (bad, "" if bad == 1 else "s") if bad else ""
    while True:
        try:
            answer = parse_answer(input("Move %s -> %s%s? [y]es / [n]o / [a]ll / [q]uit: " % (source, target, warning)))
        except EOFError:
            return "q"
        if answer:
            return answer


def offer_move(source, dest_root, move_all, progress, bad=0, yes=False):
    target = destination_for(source, dest_root)
    if is_within(dest_root, source):
        progress.say("SKIP %s: destination is inside it" % source, sys.stderr)
        return "n", 1, move_all
    if os.path.exists(target):
        progress.say("SKIP %s: %s already exists" % (source, target), sys.stderr)
        return "n", 1, move_all
    auto = move_all and (yes or not bad)
    decision = "a" if auto else ask_move(source, target, bad)
    if decision == "a":
        move_all = True
    if decision in ("y", "a"):
        try:
            os.makedirs(dest_root, exist_ok=True)
            shutil.move(source, target)
        except OSError as error:
            progress.say("FAILED to move %s: %s" % (source, error.strerror or error), sys.stderr)
            return "n", 1, move_all
        progress.say("MOVED %s -> %s" % (source, target))
        return "y", 0, move_all
    return decision, 0, move_all


def run_units(units, args, pool, progress):
    zero_limit = args.zero_run * 1024
    dest_root = os.path.abspath(args.move_to) if args.move_to else None
    move_all = args.yes
    checked = bad = moved = move_failures = 0

    for unit in units:
        label = unit.path or "(files given on the command line)"
        if not unit.files:
            progress.say("SKIP %s: no media files" % label)
            continue
        progress.say("== %s (%d file%s)" % (label, len(unit.files), "" if len(unit.files) == 1 else "s"))
        stop_on_bad = bool(dest_root and unit.path and not args.force)
        problems_by_file = check_unit(pool, unit.files, zero_limit, args.quick, progress, args.verbose,
                                      stop_on_bad)
        unit_bad = sum(1 for p in problems_by_file.values() if p)
        checked += len(problems_by_file)
        bad += unit_bad
        if not dest_root or not unit.path:
            continue
        if unit_bad and not args.force:
            unchecked = len(unit.files) - len(problems_by_file)
            progress.say("KEEP %s: bad file found, not moving%s" % (
                unit.path, "; %d file%s not checked" % (unchecked, "" if unchecked == 1 else "s")
                if unchecked else ""))
            continue
        decision, failed, move_all = offer_move(unit.path, dest_root, move_all, progress, unit_bad, args.yes)
        move_failures += failed
        moved += decision == "y"
        if decision == "q":
            progress.say("Stopped; remaining directories not checked.")
            break

    progress.say("%d checked, %d bad%s" % (checked, bad, ", %d moved" % moved if dest_root else ""))
    return 1 if bad or move_failures else 0


def missing_tools():
    return [tool for tool in ("ffmpeg", "ffprobe") if not shutil.which(tool)]


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="verify_media",
        description="Check media files (mp3, m4b, m4v, mp4, ...) for incomplete or corrupt downloads.")
    parser.add_argument("paths", nargs="+", help="files or directories to check")
    parser.add_argument("-q", "--quick", action="store_true",
                        help="skip the full decode (container, stream and zero-gap checks only)")
    parser.add_argument("-z", "--zero-run", type=int, default=DEFAULT_ZERO_RUN // 1024, metavar="KIB",
                        help="flag a run of this many KiB of zero bytes; 0 disables (default: %(default)s)")
    parser.add_argument("-j", "--jobs", type=int, default=2,
                        help="files checked in parallel within a directory (default: %(default)s)")
    parser.add_argument("-m", "--move-to", metavar="DIR",
                        help="as each directory argument checks out good, offer to move it into DIR")
    parser.add_argument("-y", "--yes", action="store_true", help="with --move-to, move without asking")
    parser.add_argument("-f", "--force", action="store_true",
                        help="with --move-to, check every file and still offer to move directories with bad files "
                             "(by default a directory is abandoned at its first bad file)")
    parser.add_argument("-v", "--verbose", action="store_true", help="also list files that are OK")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    CANCEL.clear()
    missing = missing_tools()
    if missing:
        print("verify_media: missing %s (install the ffmpeg package)" % ", ".join(missing), file=sys.stderr)
        return 2
    if args.move_to and not args.yes and not sys.stdin.isatty():
        print("verify_media: --move-to asks for confirmation and needs a terminal; pass --yes", file=sys.stderr)
        return 2

    units = build_units(args.paths)
    total = sum(len(u.files) for u in units)
    if not total:
        print("verify_media: no media files found", file=sys.stderr)
        return 2

    progress = Progress(total, sys.stderr)
    pool = ThreadPoolExecutor(max_workers=max(1, args.jobs))
    try:
        return run_units(units, args, pool, progress)
    except KeyboardInterrupt:
        CANCEL.set()
        kill_active()
        progress.clear()
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except Exception:
        CANCEL.set()
        raise
    finally:
        kill_active()
        pool.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    sys.exit(main())
