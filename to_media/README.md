# to_media

**Reshape audio, video, images and audiobooks from one format to another with one safe, predictable command, and spread a big batch across every machine you own.**

`to_media mp3 *.flac`, `to_media h264 *.mkv`, `to_media jpg --max 2048 *.heic`,
`to_media m4b "My Book/"`:
the same options, the same safety rules and the same progress report whatever
you are converting. Every format also has a short alias you can call directly:
`to_mp3`, `to_jpg`, `to_m4b`.

> **Status:** inline conversion of mp3, h264, m4b, jpg, png and webp works today,
> as does the job server (`to_media server`, `to_media worker`, `--queue`,
> `--follow`, `jobs`, `status`, `cancel`, `retry`); see
> [Job server](#job-server-and-workers) below and [DESIGN.md](DESIGN.md). Data
> transfer mode (workers without shared storage) and TLS are not built yet;
> today every worker needs the same paths the server sees.

An illustrative session:

```console
$ to_media mp3 ~/Music/Album
[1/12] 01 Opening.flac -> 01 Opening.mp3
[2/12] 02 Second Song.flac -> 02 Second Song.mp3
...
12 done in 0:41
$ to_media mp3 ~/Music/Album
...
12 skipped in 0:00
```

## Why use it

- **One command for many formats.** Audio, images and audiobooks share the same
  flags, the same output rules and the same report, so you learn it once.
- **Safe by default.** Your originals are kept. Existing outputs are skipped, not
  overwritten. Results are written to a hidden temporary file and renamed only
  when complete, so a crash or a full disk never leaves a half-written file, and
  a failed conversion never deletes a source.
- **Metadata is kept, or you are told.** Tags, cover art, chapters, camera and GPS
  data, recording dates and even a file's modification date carry over. Where a
  format genuinely cannot hold something, a `note:` says exactly what was left out
  and how to keep it (see [Metadata](#metadata-what-is-kept)).
- **Folders in, folders out.** Give it a folder and it converts everything
  inside, recursively, in natural order (`track 2` before `track 10`). With
  `--out` the folder layout is preserved.
- **Audiobooks done right.** A folder of audio files becomes one `.m4b` with a
  titled chapter per file, the author and title worked out from the folder name
  or the tags, and the chapters in the right order without zero-padded names.
- **Rehearse first.** `--dry-run` prints the exact command for every file.
- **Live progress.** Long conversions (video especially) show a progress bar with
  the percentage, elapsed time and an estimated time remaining.
- **Built to scale out.** Jobs are plain data, so `--queue` sends the same work
  to a farm of machines through the job server (see
  [Job server](#job-server-and-workers) below).

## Quick start

```bash
to_media formats                          # what is available on this machine
to_media mp3 ~/Music/Album                # every audio file in the folder, next to the originals
to_media mp3 --out ~/mp3 ~/Music/Album    # same, into another folder
to_media h264 --profile fast720 *.mkv     # smaller, phone-friendly MP4s
to_media jpg --max 2048 ~/Photos/*.heic   # phone photos to shareable JPEGs
to_media m4b "Jane Doe - Sample Book/"    # a folder of files becomes one chaptered audiobook
to_media mp3 --dry-run *.flac             # show the commands, do nothing
```

## Usage

```text
to_media FORMAT [options] PATH ...
to_media formats
```

`FORMAT` is one of `mp3`, `h264`, `m4b`, `jpg` (also `jpeg`), `png`, `webp`. Any command
named `to_<format>` that points at `to_media.py` works the same as
`to_media <format>`.

### Options for every format

| Option | Meaning |
| --- | --- |
| `PATH ...` | Files or folders. Folders are searched recursively for files this format can read; files you name are always tried. |
| `-o`, `--out DIR` | Write results into `DIR` (created if missing), keeping a folder's layout. Default: next to each source. |
| `-n`, `--dry-run` | Show what would be done and stop. |
| `--force` | Overwrite outputs that already exist. |
| `--replace` | Delete each source after its output has been written successfully. Default: keep sources. |
| `--no-preserve-times` | Give outputs the current time. Default: each output keeps its source's modification time (newest source for an audiobook). |
| `-v`, `--verbose` | Report every file, not just skips and failures. |
| `--queue` | Submit to the job server and return immediately, instead of converting here. Prompts for a server if none is configured or reachable (see below). |
| `--follow` | With `--queue`, print live progress until the batch finishes. Ctrl-C stops following; the jobs keep running. |

### `mp3`

| Option | Meaning |
| --- | --- |
| `--quality 0-9` | Variable bitrate quality, 0 best (default 3). |
| `--bitrate RATE` | Constant bitrate instead, for example `192k`. |
| `--audiobook` | Small mono files for spoken word (quality 8, genre set to Audiobook). |

Reads FLAC, WAV, AIFF, M4A/M4B, AAC, OGG/Opus, WMA, WavPack and Monkey's Audio.

### `h264`

H.264 video with AAC audio in an `.mp4` (or `.mkv`), encoded with ffmpeg.

| Option | Meaning |
| --- | --- |
| `--profile NAME` | A starting point: `fast720` (720p at most, quick and small), `balanced` (default, keeps the size) or `hq1080` (1080p at most, slow and best). |
| `--crf 0-51` | Quality, lower is better. Overrides the profile (profiles use 23, 22 and 19). |
| `--speed NAME` | x264 speed from `ultrafast` to `veryslow`; slower makes smaller files. |
| `--max-height PIXELS` | Scale down so the picture is at most this tall. Never enlarges. |
| `--audio-bitrate RATE` | AAC bitrate, for example `160k`. |
| `--fps N` | Force a frame rate. |
| `--deinterlace` | Deinterlace with yadif (for older TV and camcorder video). |
| `--encoder x264\|nvenc` | `x264` on the CPU (default), or `nvenc` on an NVIDIA GPU, which is much faster. |
| `--tags auto\|all\|standard` | Which tags an MP4 keeps; see [Metadata](#metadata-what-is-kept). MKV always keeps everything. |

Chapters, metadata and **every** audio track are kept; the video is converted to
the widely playable `yuv420p` format. Reads MKV, AVI, MOV, M4V, WMV, FLV, WebM,
MPEG, TS/M2TS, VOB, 3GP and more. Files that already have the output's extension
(`.mp4`, or `.mkv` with `--container mkv`) are skipped when found in a folder,
because they would land on top of themselves; name one explicitly with `--out` to
re-encode it.

#### Subtitles

| Option | Meaning |
| --- | --- |
| `--subtitles keep\|none` | Keep subtitle tracks (default) or drop them. |
| `--burn-subtitles [TRACK]` | Hard-code one subtitle track into the picture, by number (`0` is the first and the default) or by language (`eng`, `fr`). Other subtitle tracks are then dropped. |
| `--container mp4\|mkv` | `mp4` (default) can hold text subtitles only. `mkv` keeps every subtitle track exactly as it is, including image subtitles and the fonts embedded for styled ones. |

What happens by default:

- **Text subtitles** (SubRip/SRT, ASS/SSA, WebVTT and similar) are converted to
  the MP4 text format and kept, with their languages, titles and default/forced
  flags. Fancy ASS styling (fonts, colours, positioning) does not survive that
  conversion; use `--container mkv` or `--burn-subtitles` to keep the look.
- **Image subtitles** (Blu-ray PGS, DVD VobSub, DVB) cannot be stored in an MP4.
  They are left out **and you are told**: a `note:` line names the tracks and
  points at `--burn-subtitles` and `--container mkv`, so a disc rip never loses its
  subtitles silently.
- **A track that will not convert** does not cost you the file. If ffmpeg fails
  while converting subtitles, the file is converted again without them and a
  `note:` says why.
- **Burning in** works for both kinds: text subtitles are rendered with libass,
  image subtitles are overlaid, and either way the result plays anywhere. The
  burned-in text is part of the picture and cannot be turned off. It needs an
  ffmpeg with the `subtitles` filter (libass) for text tracks.

### `m4b`

| Option | Meaning |
| --- | --- |
| `--title`, `--author`, `--narrator` | Override the detected values. |
| `--combine` | Combine the individual files you name into one book (otherwise each is its own book). |
| `--bitrate RATE` | AAC bitrate (default `32k`). |

### `jpg`, `png`, `webp`

| Option | Meaning |
| --- | --- |
| `--quality 1-100` | Compression quality (jpg default 90, webp default 85; not used by png). |
| `--max PIXELS` | Shrink so the longest side is at most `PIXELS`. Never enlarges. |
| `--strip` | Remove metadata (EXIF, colour profiles). |

Reads HEIC/HEIF (when your ImageMagick supports it), PNG, JPEG, WebP, TIFF, BMP,
GIF (first frame) and AVIF. Files already in the target format are skipped when
converting a folder.

## Job server and workers

`--queue` sends conversions to a server instead of running them here, so a
large batch can be spread across every machine you own. Everyday commands
still need no server: `to_media mp3 *.flac` never touches one.

```bash
to_media server                         # first run: sets up and starts a server, prints a join string
to_media worker                         # on another machine: paste the join string when asked, or
to_media worker tomedia://TOKEN@host:port   # ...give it directly and it is remembered

to_media mp3 *.flac --queue             # queues the files, returns immediately
to_media mp3 *.flac --queue --follow    # queues, then shows live progress until it is done
to_media status                         # batches and workers, once
to_media status --watch                 # ...refreshed every 5s
to_media jobs --state failed            # list jobs in a given state
to_media cancel --batch 3               # stop a batch (queued jobs at once; running ones asked to stop)
to_media retry --batch 3                # requeue its failed/cancelled jobs
```

| Command | Meaning |
| --- | --- |
| `to_media server` | Start (first run: also set up) the job server. Runs in the background by default. |
| `to_media server --foreground` | Stay attached; logs to the console instead of syslog/a file. |
| `to_media server --stop`, `--status` | Stop a background server, or report whether one is running. |
| `to_media server --setup` | Ask the setup questions again. |
| `to_media server --advertise hostname\|ip\|both\|VALUE` | How workers should find this server. |
| `to_media server --new-token` | Rotate the token; old join strings stop working. |
| `to_media server --join-info` | Print only the join string. |
| `to_media worker [JOIN]` | Run a worker for the given join string (remembered for next time) or the remembered server. Also backgrounds by default. |
| `to_media worker --slots N` | Run up to `N` conversions at once (default 1). |
| `to_media worker --recipes FORMAT,...` | Only claim these formats (default: everything installed on this machine). |
| `to_media worker --stop`, `--status` | Stop a background worker, or report whether one is running. |
| `to_media jobs [--state STATE] [--batch ID] [--limit N]` | List jobs. |
| `to_media status [--watch [SECONDS]]` | Batches and workers; `--watch` keeps refreshing. |
| `to_media cancel JOB_ID`, `to_media cancel --batch ID` | Cancel one job or a whole batch. |
| `to_media retry JOB_ID`, `to_media retry --batch ID` | Requeue a failed or cancelled job or batch. |

How it behaves:

- **A worker needs no shared storage today**: every input and output path is
  read and written locally by the worker, so a worker on another machine needs
  the same paths the server sees (typically an NFS or SMB share mounted the
  same way everywhere). Sending files over the connection instead is designed
  but not built yet (see [DESIGN.md](DESIGN.md)).
- **The join string** (`tomedia://TOKEN@host:port?id=...`) is a secret: anyone
  who has it can submit and see jobs on that server. It is what `to_media worker`
  and a `--queue` prompt ask for.
- **No server configured (or unreachable) when you use `--queue`** prompts you
  to start one on this machine, paste a join string, or cancel; the reason
  (timeout, refused, bad token) is stated for an unreachable one.
- **A dead worker's job is requeued.** Workers hold a job on a lease, renewed
  every few seconds; if a worker stops answering, the job goes back to the
  queue (or fails, after too many attempts), never silently lost.
- **`--force`, `--replace` and `--no-preserve-times`** apply the same way on a
  worker as they do inline.
- **Encryption is not implemented yet.** The connection is always plain HTTP
  today; treat it as a trusted LAN. The server and every worker print an
  "unencrypted" warning when `openssl` is not installed, ahead of TLS support
  that will use it (see [DESIGN.md](DESIGN.md)).
- **Logging**: the server and worker log to syslog by default, or to a file with
  `--log PATH`, or to the console with `--foreground`.

## How it behaves

- **Output name and place.** `song.flac` becomes `song.mp3` beside it, or in
  `--out` with the folder layout preserved. A conversion that would overwrite its
  own source is skipped.
- **Skipping.** An existing output is left alone unless `--force`. Running the
  same command twice is safe and fast, so an interrupted batch can simply be
  run again.
- **Atomic output.** Each result is written to a hidden `.name.partial-PID.ext`
  file in the destination folder and renamed when complete.
- **`--replace`** deletes a source only after its output exists and is not empty.
  A failed or empty result deletes nothing.
- **Exit status.** `0` everything fine (skips are fine), `1` at least one file
  failed or nothing matched, `2` bad usage, a missing program, or a feature that
  is not available yet.
- **mp3** carries the tags and cover pictures across (ID3v2.3 plus ID3v1).
- **m4b** treats each folder you give as one book, ordered naturally, with a chapter
  per file named from the file name (track numbers and "Chapter N" prefixes are
  stripped). Title, author and narrator come from your options, then the folder
  name (`Author - Title`, `Author - Title (Narrator)` or `Title by Author`), then
  the first file's tags. The narrator is stored in the composer tag and the genre
  is set to Audiobook. The book is written next to the folder unless you use
  `--out`.
- **Images** are rotated to their intended orientation and keep their metadata
  unless `--strip`.
- **Notes.** When something was deliberately left out or worked around (image
  subtitles that MP4 cannot hold, a subtitle track that would not convert), a
  `note:` line under the file says so, whether or not you used `-v`.
- **Progress.** On a terminal each file shows a live bar with the percentage,
  elapsed time and estimated time remaining, cleared when the file finishes.
  When output is redirected to a file or pipe, only the per-file lines are printed.

## Metadata: what is kept

The rule is that nothing is lost silently: it is either carried over, or a `note:`
tells you what was left out. The table lists what each format does.

| | Kept | Converted or limited |
| --- | --- | --- |
| **mp3** | Title, artist, album, album artist, composer, genre, date, copyright, publisher, comment, ReplayGain and other custom fields, **cover pictures** (with their descriptions), the file's modification date | Track and disc numbers with their totals are merged into `3/12` and `1/2`. ISRC and BPM are written as proper ID3 frames. **Lyrics** are kept but ffmpeg can only store them in a custom text field, which most players do not show. |
| **h264 to MKV** | Everything: every tag (including custom ones), **cover pictures** as attachments, chapters, track titles and languages, subtitles, embedded fonts, the recording date, the file's modification date | Nothing is lost. This is the most complete container. |
| **h264 to MP4** | Standard tags, cover pictures, chapters, track titles and languages, text subtitles, the recording date, the file's modification date | See below for tags that MP4 cannot hold. |
| **m4b** | Title, author and narrator (from your options, the folder name or the first file), plus date, comment, description, copyright and language from the first file; the cover (embedded in the first file, or a `cover`/`folder`/`front` image in the folder); the newest source's modification date | MP4 has no publisher field, so the publisher is not carried. |
| **jpg, png** | Everything ImageMagick reads: camera, lens and exposure data, capture date, **GPS location**, copyright, XMP, IPTC keywords and captions, colour profiles; rotation is applied and the orientation tag reset; the file's modification date | |
| **webp** | EXIF, XMP, colour profiles, GPS, capture date, the file's modification date | WebP cannot store **IPTC** (keywords, caption, credits); a `note:` says so and points at jpg or png. |

### Tags in MP4 files

MP4's usual tag format holds only a fixed list of fields (title, artist, genre,
description, comment, copyright and so on). Anything else, such as an MKV's
`ACTOR` or `DIRECTOR`, or an iPhone's **location, camera model and original
capture date**, needs ffmpeg's *QuickTime metadata* mode. That mode has a cost: it
stores *every* tag that way, some tag editors do not read it, and it has no place
for a cover picture. So `--tags` lets you choose:

| `--tags` | Behaviour |
| --- | --- |
| `auto` (default) | If the file has extra tags and **no cover**, keep everything using QuickTime metadata (a `note:` says so). If it has extra tags **and a cover**, keep the cover and the standard tags and report the extra tags that were left out. |
| `all` | Always keep every tag; a cover picture is dropped, and a `note:` says so. |
| `standard` | Keep only the usual MP4 tags and the cover, quietly. |

If a file has extra tags *and* a cover and you want both, convert to MKV
(`--container mkv`).

Other things that are reported rather than lost quietly: HDR sources (converted to
8-bit SDR without tone mapping, so colours look flat), camera data tracks such as
GoPro telemetry (not copied), and subtitle tracks MP4 cannot hold.

## Installation

`to_media` is a Python 3 program that uses only the standard library (written for
Python 3.8 or newer, tested on 3.12). It drives these programs:

| Program | Needed for |
| --- | --- |
| `ffmpeg` and `ffprobe` (built with `libx264` for video) | `mp3`, `h264` and `m4b` |
| ImageMagick (`magick`, or `convert` on Linux and macOS) | `jpg`, `png`, `webp` |

Only the programs for the formats you use are needed; `to_media formats` shows
what is ready. On Windows only ImageMagick 7's `magick` is accepted, because
Windows ships an unrelated `convert.exe`.

> **Tested on:** Linux Mint 22.3 (Ubuntu 24.04 base) with Python 3.12, ffmpeg 6.1
> and ImageMagick 6.9 (with HEIC read support). The automated tests run real
> conversions on generated audio and images. Everything for other systems is
> **untested by the author**; package names are best effort.

### Debian, Ubuntu, Linux Mint, Pop!_OS (tested)

```bash
sudo apt update
sudo apt install python3 ffmpeg imagemagick
```

### Fedora, RHEL, Rocky, AlmaLinux (untested)

`ffmpeg` needs [RPM Fusion](https://rpmfusion.org/) for full codec support.

```bash
sudo dnf install python3 ImageMagick
sudo dnf install ffmpeg          # after enabling RPM Fusion
```

### Arch Linux, Manjaro, EndeavourOS (untested)

```bash
sudo pacman -S python ffmpeg imagemagick
```

### openSUSE (untested)

```bash
sudo zypper install python3 ImageMagick
```

`ffmpeg` comes from the Packman repository.

### macOS (untested)

```bash
brew install python ffmpeg imagemagick
```

### Windows (untested)

Native Windows should work because the program is portable Python, but it has
not been tried. Install [Python](https://www.python.org/downloads/),
[FFmpeg](https://ffmpeg.org/download.html) and
[ImageMagick 7](https://imagemagick.org/script/download.php#windows) and make
sure `ffmpeg`, `ffprobe` and `magick` are on your `PATH`. WSL 2 with the
Debian/Ubuntu steps also works.

HEIC/HEIF support depends on how your ImageMagick was built. Check with
`magick -list format | grep -i heic` (or `convert -list format`).

### Verify the installation

```bash
to_media formats                         # every format you need should say "ready"
ffmpeg -v error -f lavfi -i sine=d=1 /tmp/tone.wav
to_media mp3 /tmp/tone.wav && ls /tmp/tone.mp3
```

### Putting `to_media` on your PATH

The repository keeps the program in `to_media/` and an extensionless command
link in `bin/`. Add that directory to your `PATH`:

```bash
export PATH="/path/to/utils/bin:$PATH"     # add to ~/.bashrc or ~/.zshrc
```

To use a short alias, link the program under the alias name, for example
`ln -s /path/to/utils/to_media/to_media.py ~/.local/bin/to_webp`. The repository's
own `bin/to_mp3`, `bin/to_m4b` and `bin/to_h264` are still the older standalone
tools; they will become aliases of `to_media` once it matches their features.
Note that `to_media h264` differs from the old `to_h264`: it uses ffmpeg (not
HandBrake), writes `.mp4` (not `.m4v`), keeps originals unless `--replace`, keeps
subtitles (see above), and defaults to the source's size (use `--profile fast720` for the old 720p default).

## Troubleshooting

- **`mp3 needs ffmpeg`** or **`needs ImageMagick`**: install the program named
  (see Installation). `to_media formats` lists what is missing.
- **HEIC files fail to convert**: your ImageMagick was built without HEIF
  support; install a build that has it.
- **`skipped: output exists`**: the result is already there; use `--force` to
  redo it.
- **Chapters in the wrong order**: folders are sorted naturally by full path;
  check that the file names sort the way you expect.
- **A file failed**: run it alone with `-v` to see the converter's error.

## Limitations

- Only mp3, h264, m4b, jpg, png and webp so far; more formats are planned.
- Burning in an **image** subtitle track (PGS, VobSub) is implemented but has not
  been run against a real bitmap subtitle file: ffmpeg cannot create one for the
  automated tests, so that path is covered only by tests of the command it builds.
  Text-subtitle keeping, MKV, and text burn-in are tested on real files.
- h264 uses ffmpeg, not HandBrake, so HandBrake presets and DVD "main feature"
  selection are not available; rip discs with `dvd2iso` first.
- Lyrics in MP3 are kept but not shown by most players (ffmpeg cannot write a real
  lyrics frame). MusicBrainz identifiers are kept as custom text fields, not the
  frames a tagger such as MusicBrainz Picard expects.
- HEIC input was not tested with a real HEIC file (none could be created here), so
  whether every HEIC tag carries over is unverified; JPEG, PNG and WebP are tested.
- Not yet as capable as the older `to_mp3`: no `.cue` splitting of FLAC albums,
  no Audible files, no per-chapter splitting, and no re-encoding of existing
  MP3s. The older tool stays until these are covered.
- The job server has no data-transfer mode yet: a worker needs the same paths
  the server sees (typically a shared mount), and there is no TLS yet either.
- m4b needs every file in a book to be readable by ffmpeg and joins them
  re-encoded to AAC; it does not keep the original codec.
- Animated images are converted from their first frame only.

## Development

```bash
python3 tests/test_to_media.py     # conversions (real ones need ffmpeg and ImageMagick)
python3 tests/test_queue.py        # the job queue
python3 tests/test_server.py       # the job server's HTTP API
python3 tests/test_worker.py       # the worker (real ones need ffmpeg)
python3 tests/test_join.py         # the tomedia:// join string
python3 tests/test_daemon.py       # background start/stop/status
python3 tests/test_serverctl.py    # server/worker/jobs/status/cancel/retry CLI, --queue prompts
tests/run_tests.sh                 # every tool's tests (from the repository root)
```

The design and the plan for later job-server work (data transfer, TLS) are in
[DESIGN.md](DESIGN.md).

## License

MIT, see the repository [LICENSE](../LICENSE).
