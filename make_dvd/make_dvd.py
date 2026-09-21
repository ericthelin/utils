#!/usr/bin/env python3
"""Convert video files into a DVD-Video ISO (a small command-line DeVeDe).

Pick one or more videos (positional arguments, or a zenity file chooser when
none are given). Each is transcoded to DVD-compliant MPEG-2/AC-3 with the
video bitrate chosen so everything fits the target disc (DVD-5 by default).
With more than one file a menu listing each title is authored; it auto-plays
the first title after a few seconds and each title continues into the next.

The finished ISO can be burned to a blank DVD (--burn, or answer the prompt).
Given just an .iso file, the script burns it after asking for confirmation.
"""

import argparse
import collections
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

DISC_BYTES = {"dvd5": 4_700_000_000, "dvd9": 8_540_000_000}
SAFETY_FACTOR = 0.97
MENU_RESERVE_BYTES = 3_000_000
MUX_OVERHEAD = 0.03
AUDIO_KBPS = 192
MAX_VIDEO_KBPS = 8000
MIN_VIDEO_KBPS = 1000
MAX_MENU_TITLES = 10
CHAPTER_SECONDS = 300
MIN_CHAPTER_SECONDS = 10
MAX_CHAPTERS = 99
MENU_STILL_SECONDS = 3
STAGE_FRACTIONS = {"menu": 0.005, "author": 0.03, "iso": 0.015}
FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
)
STANDARDS = {
    "ntsc": {"height": 480, "fps": "30000/1001", "target": "ntsc-dvd",
             "canvas": {"16:9": (854, 480), "4:3": (640, 480)}},
    "pal": {"height": 576, "fps": "25", "target": "pal-dvd",
            "canvas": {"16:9": (1024, 576), "4:3": (768, 576)}},
}
BURN_SPEED = 8
BLOCK_BYTES = 2048
BURN_PROGRESS = re.compile(r"(\d+)\s+of\s+(\d+)\s+MB written")
BURN_NOTICES = re.compile(r"fixat|error|fail|warning", re.IGNORECASE)
REQUIRED_TOOLS = ("ffmpeg", "ffprobe", "dvdauthor", "spumux", "genisoimage", "convert")


def parse_ratio(text, default=1.0):
    try:
        num, den = text.split(":") if ":" in text else text.split("/")
        return float(num) / float(den)
    except (ValueError, ZeroDivisionError, AttributeError):
        return default


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", "-show_chapters", path],
        capture_output=True, text=True, check=True).stdout
    return parse_probe(json.loads(out), path)


def parse_probe(data, path):
    video = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    if video is None:
        raise ValueError(f"no video stream in {path}")
    width, height = int(video["width"]), int(video["height"])
    sar = parse_ratio(video.get("sample_aspect_ratio", "1:1"))
    if sar <= 0:
        sar = 1.0
    return {
        "path": path,
        "duration": float(data["format"]["duration"]),
        "dar": width / height * sar,
        "fps": parse_ratio(video.get("r_frame_rate", "30000/1001"), 29.97),
        "has_audio": any(s["codec_type"] == "audio" for s in data["streams"]),
        "chapters": [float(c["start_time"]) for c in data.get("chapters", []) if "start_time" in c],
    }


def pick_standard(fps):
    return "pal" if 24.9 <= fps <= 25.1 else "ntsc"


def pick_aspect(dars):
    return "16:9" if any(d >= 1.5 for d in dars) else "4:3"


def video_kbps(total_seconds, disc_bytes):
    budget_bits = (disc_bytes * SAFETY_FACTOR - MENU_RESERVE_BYTES) * 8
    total_kbps = budget_bits / total_seconds / 1000
    kbps = int(total_kbps * (1 - MUX_OVERHEAD) - AUDIO_KBPS)
    return min(kbps, MAX_VIDEO_KBPS)


def video_filter(standard, aspect):
    spec = STANDARDS[standard]
    width, height = spec["canvas"][aspect]
    return ",".join([
        "scale='trunc(iw*sar/2)*2':ih",
        f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2",
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black",
        f"scale=720:{spec['height']}",
        f"setdar={aspect.replace(':', '/')}",
        f"fps={spec['fps']}",
    ])


def encode_command(src, dst, info, standard, aspect, kbps):
    spec = STANDARDS[standard]
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostats", "-progress", "pipe:1", "-y", "-i", src]
    if not info["has_audio"]:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    cmd += ["-map", "0:v:0", "-map", "0:a:0" if info["has_audio"] else "1:a:0"]
    cmd += ["-vf", video_filter(standard, aspect), "-target", spec["target"],
            "-aspect", aspect, "-b:v", f"{kbps}k", "-maxrate", "9000k",
            "-bufsize", "1835k", "-flags", "+cgop", "-sc_threshold", "1000000000", "-c:a", "ac3", "-b:a", f"{AUDIO_KBPS}k",
            "-ar", "48000", "-ac", "2"]
    if not info["has_audio"]:
        cmd += ["-t", f"{info['duration']:.3f}"]
    return cmd + [dst]


def format_timestamp(seconds):
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def usable_chapters(starts, duration):
    gap = MIN_CHAPTER_SECONDS
    while True:
        kept = [0]
        for start in sorted(round(t) for t in starts if 0 < t < duration):
            if start - kept[-1] >= gap and duration - start >= gap:
                kept.append(start)
        if len(kept) <= MAX_CHAPTERS:
            return kept
        gap *= 2


def chapter_times(duration, source_chapters=None):
    source = usable_chapters(source_chapters or [], duration)
    if len(source) > 1:
        return source, "source"
    return [0] + list(range(CHAPTER_SECONDS, int(duration) - 60 + 1, CHAPTER_SECONDS)), "5 min"


def chapter_marks(duration, source_chapters=None):
    times, _ = chapter_times(duration, source_chapters)
    return ",".join("0" if t == 0 else format_timestamp(t) for t in times)


def title_label(path, limit=42):
    stem = os.path.splitext(os.path.basename(path))[0].replace("_", " ")
    return stem if len(stem) <= limit else stem[:limit - 1] + "…"


def menu_boxes(count, height):
    top, bottom = 120, height - 40
    row = min(52, (bottom - top) // count)
    return [(60, top + i * row, 660, top + i * row + row - 8) for i in range(count)]


def build_spumux_xml(boxes):
    buttons = "\n".join(
        f'    <button name="b{i + 1}" x0="{x0}" y0="{y0}" x1="{x1}" y1="{y1}"/>'
        for i, (x0, y0, x1, y1) in enumerate(boxes))
    return ('<subpictures>\n <stream>\n'
            '  <spu force="yes" start="00:00:00.00" highlight="highlight.png" select="select.png">\n'
            f'{buttons}\n  </spu>\n </stream>\n</subpictures>\n')


def build_dvdauthor_xml(dest, standard, aspect, infos, menu_file=None, timeout=5):
    count = len(infos)
    if menu_file:
        buttons = "\n".join(
            f"     <button name=\"b{i + 1}\"> jump title {i + 1}; </button>"
            for i in range(count))
        vmgm = (
            "  <vmgm>\n   <fpc> g1 = 0; jump vmgm menu entry title; </fpc>\n   <menus>\n"
            f'    <video format="{standard}" aspect="4:3"/>\n    <audio format="ac3"/>\n'
            '    <pgc entry="title">\n'
            f'     <vob file="{menu_file}" pause="{timeout}"/>\n{buttons}\n'
            "     <post> if (g1 eq 0) { g1 = 1; jump title 1; } jump cell 1; </post>\n"
            "    </pgc>\n   </menus>\n  </vmgm>\n")
    else:
        vmgm = "  <vmgm>\n   <fpc> jump title 1; </fpc>\n  </vmgm>\n"
    pgcs = []
    for i, info in enumerate(infos):
        if i + 1 < count:
            post = f"<post> jump title {i + 2}; </post>"
        else:
            post = "<post> call vmgm menu; </post>" if menu_file else ""
        pgcs.append(
            f'   <pgc>\n    <vob file="{info["mpg"]}" chapters="{chapter_marks(info["duration"], info.get("chapters"))}"/>\n'
            f"    {post}\n   </pgc>")
    titleset = (
        "  <titleset>\n   <titles>\n"
        f'    <video format="{standard}" aspect="{aspect}"/>\n    <audio format="ac3"/>\n'
        + "\n".join(pgcs) + "\n   </titles>\n  </titleset>\n")
    return f'<dvdauthor dest="{dest}">\n{vmgm}{titleset}</dvdauthor>\n'


def iso_label(text):
    return re.sub(r"[^A-Z0-9_]", "_", text.upper())[:32] or "DVD"


def imagemagick_text(text):
    return text.replace("\\", "\\\\").replace("%", "%%")


def format_duration(seconds):
    hours, rest = divmod(int(round(seconds)), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def render_bar(fraction, width):
    filled = int(round(max(0.0, min(1.0, fraction)) * width))
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def progress_line(fraction, label, elapsed, eta, finish, columns):
    eta_text = "ETA --:--" if eta is None else f"ETA {format_duration(eta)} (done ~{finish})"
    stats = f" {fraction * 100:5.1f}%  elapsed {format_duration(elapsed)}  {eta_text}"
    room = columns - 1 - len(stats) - 12
    text = f"  {label}" if len(label) + 2 <= room - 10 else ""
    bar = render_bar(fraction, max(10, min(40, room - len(text))))
    return (bar + stats + text)[:columns - 1]


class Progress:
    def __init__(self, total_units, stream=None, clock=time.monotonic, wall=time.time):
        self.total = total_units
        self.done = 0.0
        self.stream = stream or sys.stderr
        self.clock, self.wall = clock, wall
        self.start = clock()
        self.tty = self.stream.isatty()
        self.last_pct = -1

    def eta_seconds(self):
        elapsed = self.clock() - self.start
        if self.done <= 0 or elapsed < 1:
            return None
        return max(0.0, (self.total - self.done) / (self.done / elapsed))

    def update(self, done, label):
        self.done = min(done, self.total)
        fraction = self.done / self.total if self.total else 1.0
        elapsed = self.clock() - self.start
        eta = self.eta_seconds()
        finish = None if eta is None else time.strftime("%H:%M", time.localtime(self.wall() + eta))
        if self.tty:
            columns = shutil.get_terminal_size((100, 20)).columns
            self.stream.write("\r\033[K" + progress_line(fraction, label, elapsed, eta, finish, columns))
            self.stream.flush()
        elif int(fraction * 20) != self.last_pct:
            self.last_pct = int(fraction * 20)
            print(progress_line(fraction, label, elapsed, eta, finish, 100), file=self.stream)

    def message(self, text):
        if self.tty:
            self.stream.write("\r\033[K")
        print(text, file=self.stream)

    def finish_stage(self, name, label):
        self.update(self.done + self.total * STAGE_FRACTIONS[name] / (1 + sum(STAGE_FRACTIONS.values())), label)


def encode_title(cmd, duration, progress, base_units, label):
    with tempfile.TemporaryFile("w+") as errors:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errors, text=True)
        for line in proc.stdout:
            key, _, value = line.strip().partition("=")
            if key == "out_time_us" and value.lstrip("-").isdigit():
                progress.update(base_units + min(max(int(value), 0) / 1e6, duration), label)
        proc.wait()
        if proc.returncode:
            errors.seek(0)
            progress.message(errors.read().strip())
            raise subprocess.CalledProcessError(proc.returncode, cmd)
    progress.update(base_units + duration, label)


def run(cmd, **kwargs):
    subprocess.run(cmd, check=True, **kwargs)


def make_menu(workdir, infos, standard, title, timeout):
    height = STANDARDS[standard]["height"]
    boxes = menu_boxes(len(infos), height)
    font = next((["-font", f] for f in FONT_CANDIDATES if os.path.exists(f)), [])
    bg = [os.path.join(workdir, "bg.png")]
    cmd = ["convert", "-size", f"720x{height}", "gradient:#1a2a55-#05060f"] + font
    cmd += ["-fill", "white", "-pointsize", "34", "-gravity", "North", "-annotate", "+0+35",
            imagemagick_text(title), "-gravity", "NorthWest", "-pointsize", "24"]
    for info, (x0, y0, _, _) in zip(infos, boxes):
        cmd += ["-annotate", f"+{x0 + 14}+{y0 + 8}",
                imagemagick_text(f"{info['index']}. {title_label(info['path'])}")]
    run(cmd + bg)
    for name, color in (("highlight", "#ffd000"), ("select", "#ff3030")):
        cmd = ["convert", "-size", f"720x{height}", "xc:none", "+antialias", "-fill", "none",
               "-stroke", color, "-strokewidth", "4"]
        for x0, y0, x1, y1 in boxes:
            cmd += ["-draw", f"rectangle {x0},{y0} {x1},{y1}"]
        run(cmd + ["-colors", "4", f"PNG8:{os.path.join(workdir, name + '.png')}"])
    raw = os.path.join(workdir, "menu_raw.mpg")
    spec = STANDARDS[standard]
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-loop", "1", "-framerate", spec["fps"],
         "-i", bg[0], "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", str(MENU_STILL_SECONDS),
         "-vf", "format=yuv420p", "-target", spec["target"], "-aspect", "4:3", "-c:a", "ac3",
         "-b:a", "128k", "-shortest", raw])
    xml = os.path.join(workdir, "menu_spumux.xml")
    with open(xml, "w") as handle:
        handle.write(build_spumux_xml(boxes))
    menu = os.path.join(workdir, "menu.mpg")
    with open(raw, "rb") as src, open(menu, "wb") as dst:
        run(["spumux", "-m", "dvd", xml], stdin=src, stdout=dst, cwd=workdir,
            stderr=subprocess.DEVNULL)
    return menu


def default_output(files, cwd):
    name = os.path.splitext(os.path.basename(files[0]))[0] + ".iso" if len(files) == 1 else "dvd.iso"
    return os.path.join(cwd, name)


def default_device():
    return "/dev/cdrom" if os.path.exists("/dev/cdrom") else "/dev/sr0"


def parse_media(text):
    status = "none"
    if re.search(r"FAILURE|Cannot acquire drive", text):
        status = "error"
    elif re.search(r"Media status\s*:\s*is blank", text):
        status = "blank"
    elif re.search(r"Media status\s*:.*is closed", text):
        status = "closed"
    elif re.search(r"Media status\s*:.*is appendable", text):
        status = "appendable"
    writable = re.search(r"(\d+) writable", text)
    profile = re.search(r"Media current\s*:\s*(.+)", text)
    return {"status": status, "writable_blocks": int(writable.group(1)) if writable else None,
            "profile": profile.group(1).strip() if profile else "unknown"}


def media_problem(media, iso_bytes, device):
    if media["status"] == "error":
        return f"Cannot access {device}: the drive is busy, in use by another program, or the tray is open."
    if media["status"] == "none":
        return f"No disc detected in {device}."
    if media["status"] != "blank":
        return f"The disc in {device} is not blank ({media['profile']}, {media['status']})."
    blocks = -(-iso_bytes // BLOCK_BYTES)
    if media["writable_blocks"] is not None and media["writable_blocks"] < blocks:
        return (f"The disc has {media['writable_blocks'] * BLOCK_BYTES / 1e6:.0f} MB free "
                f"but the ISO needs {iso_bytes / 1e6:.0f} MB.")
    return None


def burn_command(iso, device, speed):
    cmd = ["xorriso", "-as", "cdrecord", "-v", f"dev={device}"]
    if speed:
        cmd.append(f"speed={speed}")
    return cmd + ["-dao", iso]


def parse_burn_progress(text):
    match = BURN_PROGRESS.search(text)
    return (int(match.group(1)), int(match.group(2))) if match else None


def confirm(question, default):
    answer = input(f"{question} [{'Y/n' if default else 'y/N'}] ").strip().lower()
    return default if not answer else answer.startswith("y")


def wait_for_blank_disc(iso, device, interactive):
    size = os.path.getsize(iso)
    while True:
        result = subprocess.run(["xorriso", "-outdev", device, "-toc"], capture_output=True, text=True)
        problem = media_problem(parse_media(result.stdout + result.stderr), size, device)
        if not problem:
            return
        if not interactive:
            sys.exit(problem)
        input(f"{problem} Insert a blank DVD and press Enter (Ctrl-C to cancel)... ")


def burn_iso(iso, device, speed, interactive):
    if not shutil.which("xorriso"):
        sys.exit("xorriso is required for burning.")
    wait_for_blank_disc(iso, device, interactive)
    progress = Progress(os.path.getsize(iso) / 1e6)
    recent = collections.deque(maxlen=10)
    proc = subprocess.Popen(burn_command(iso, device, speed), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)
    pending = ""
    progress.update(0, "burning (starting)")
    while chunk := os.read(proc.stdout.fileno(), 4096):
        pending += chunk.decode(errors="replace")
        *lines, pending = re.split(r"[\r\n]", pending)
        for line in lines:
            reading = parse_burn_progress(line)
            if reading:
                progress.total = float(reading[1])
                progress.update(reading[0], f"burning {os.path.basename(iso)}")
            elif line.strip():
                recent.append(line.strip())
                if BURN_NOTICES.search(line):
                    progress.message(line.strip())
    if proc.wait():
        progress.message("\n".join(recent))
        sys.exit(f"Burn failed (exit {proc.returncode}).")
    progress.update(progress.total, "burn complete")
    progress.message(f"Burned {os.path.basename(iso)} in {format_duration(progress.clock() - progress.start)}")


def burn_existing_iso(args):
    iso = os.path.abspath(args.files[0])
    if not os.path.isfile(iso):
        sys.exit(f"ISO not found: {iso}")
    interactive = sys.stdin.isatty()
    print(f"Burn {iso} ({os.path.getsize(iso) / 1e9:.2f} GB) to {args.device}")
    if args.dry_run:
        return 0
    if not args.burn:
        if not interactive:
            sys.exit("Not a terminal: pass --burn to burn without a prompt.")
        if not confirm("Burn this ISO to a blank DVD now?", True):
            return 0
    burn_iso(iso, args.device, args.speed, interactive)
    return 0


def choose_files():
    if not shutil.which("zenity") or not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        sys.exit("No files given and no zenity/display available for a file chooser.")
    result = subprocess.run(
        ["zenity", "--file-selection", "--multiple", "--separator=\n",
         "--title=Select video files for the DVD (menu order = selection order)"],
        capture_output=True, text=True)
    files = [line for line in result.stdout.splitlines() if line]
    if not files:
        sys.exit("No files selected.")
    return files


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("files", nargs="*",
                        help="video files (zenity chooser if omitted), or a single .iso to burn")
    parser.add_argument("-o", "--output", help="output ISO path")
    parser.add_argument("-t", "--title", help="disc title / menu heading")
    parser.add_argument("-s", "--size", choices=sorted(DISC_BYTES), default="dvd5",
                        help="target disc size (default: dvd5)")
    parser.add_argument("--standard", choices=sorted(STANDARDS), help="NTSC or PAL (default: from first file)")
    parser.add_argument("--aspect", choices=["4:3", "16:9"], help="display aspect (default: from sources)")
    parser.add_argument("--menu-timeout", type=int, default=5,
                        help="seconds before the menu auto-plays title 1 (default: 5)")
    parser.add_argument("--no-menu", action="store_true", help="skip the menu even for multiple files")
    parser.add_argument("--workdir", help="keep intermediate files in this directory")
    parser.add_argument("-b", "--burn", action="store_true",
                        help="burn the ISO to a blank DVD without asking (also for a lone .iso argument)")
    parser.add_argument("-d", "--device", default=default_device(), help="optical drive (default: %(default)s)")
    parser.add_argument("--speed", type=int, default=BURN_SPEED,
                        help="burn speed, 0 for drive default (default: %(default)s)")
    parser.add_argument("-n", "--dry-run", action="store_true", help="show the plan and exit")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    iso_inputs = [f for f in args.files if f.lower().endswith(".iso")]
    if iso_inputs and len(args.files) == 1:
        return burn_existing_iso(args)
    if iso_inputs:
        sys.exit("Give either one .iso to burn or video files to convert, not both.")
    missing = [t for t in REQUIRED_TOOLS if not shutil.which(t)]
    if missing:
        sys.exit(f"Missing required tools: {', '.join(missing)}")
    files = [os.path.abspath(f) for f in (args.files or choose_files())]
    if not all(os.path.isfile(f) for f in files):
        sys.exit("Input file not found: " + next(f for f in files if not os.path.isfile(f)))
    use_menu = len(files) > 1 and not args.no_menu
    if use_menu and len(files) > MAX_MENU_TITLES:
        sys.exit(f"At most {MAX_MENU_TITLES} titles fit the menu (use --no-menu to skip it).")

    infos = [probe(f) for f in files]
    standard = args.standard or pick_standard(infos[0]["fps"])
    aspect = args.aspect or pick_aspect([i["dar"] for i in infos])
    kbps = video_kbps(sum(i["duration"] for i in infos), DISC_BYTES[args.size])
    if kbps < MIN_VIDEO_KBPS:
        sys.exit(f"Content is too long for {args.size}: only {kbps} kbps available (min {MIN_VIDEO_KBPS}). "
                 "Use fewer files or --size dvd9.")
    title = args.title or (title_label(files[0]) if len(files) == 1 else "Movie Collection")
    output = os.path.abspath(args.output) if args.output else default_output(files, os.getcwd())
    print(f"{len(files)} title(s), {sum(i['duration'] for i in infos) / 60:.1f} min, {standard.upper()} {aspect}, "
          f"video {kbps} kbps, target {args.size}, menu {'yes' if use_menu else 'no'}")
    for index, info in enumerate(infos, 1):
        times, origin = chapter_times(info["duration"], info["chapters"])
        print(f"  {index}. {os.path.basename(info['path'])}: {len(times)} chapter{"" if len(times) == 1 else "s"} ({origin})")
    print(f"Output: {output}" + (f", then burn to {args.device}" if args.burn else ""))
    if args.dry_run:
        return 0

    workdir = args.workdir or tempfile.mkdtemp(prefix="make_dvd_")
    os.makedirs(workdir, exist_ok=True)
    try:
        encode_seconds = sum(i["duration"] for i in infos)
        progress = Progress(encode_seconds * (1 + sum(STAGE_FRACTIONS.values())))
        base = 0.0
        for index, info in enumerate(infos, 1):
            info["index"] = index
            info["mpg"] = os.path.join(workdir, f"title{index}.mpg")
            label = f"encoding {index}/{len(infos)} {title_label(info['path'], 24)}"
            encode_title(encode_command(info["path"], info["mpg"], info, standard, aspect, kbps),
                         info["duration"], progress, base, label)
            progress.message(f"encoded {index}/{len(infos)}: {os.path.basename(info['path'])}")
            base += info["duration"]
        menu = None
        if use_menu:
            progress.update(base, "building menu")
            menu = make_menu(workdir, infos, standard, title, args.menu_timeout)
            progress.finish_stage("menu", "building menu")
        dest = os.path.join(workdir, "dvd")
        shutil.rmtree(dest, ignore_errors=True)
        xml = os.path.join(workdir, "dvd.xml")
        with open(xml, "w") as handle:
            handle.write(build_dvdauthor_xml(dest, standard, aspect, infos, menu, args.menu_timeout))
        progress.update(progress.done, "authoring DVD structure")
        run(["dvdauthor", "-x", xml], env={**os.environ, "VIDEO_FORMAT": standard.upper()},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        progress.finish_stage("author", "authoring DVD structure")
        progress.update(progress.done, "building ISO")
        run(["genisoimage", "-quiet", "-dvd-video", "-V", iso_label(title), "-o", output, dest])
        progress.total = progress.done = max(progress.total, progress.done)
        progress.update(progress.total, "complete")
        progress.message(f"Finished in {format_duration(progress.clock() - progress.start)}")
        size = os.path.getsize(output)
        print(f"ISO size {size / 1e9:.2f} GB of {DISC_BYTES[args.size] / 1e9:.2f} GB")
        if size > DISC_BYTES[args.size]:
            sys.exit(f"ISO exceeds {args.size} capacity; re-run with fewer files or --size dvd9.")
    finally:
        if not args.workdir:
            shutil.rmtree(workdir, ignore_errors=True)
    interactive = sys.stdin.isatty()
    if args.burn or (interactive and confirm(f"Burn {os.path.basename(output)} to a blank DVD now?", False)):
        burn_iso(output, args.device, args.speed, interactive)
    return 0


if __name__ == "__main__":
    sys.exit(main())
