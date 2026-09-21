# to_media

**Reshape audio, images and audiobooks from one format to another with one safe, predictable command, and (soon) spread a big batch across every machine you own.**

`to_media mp3 *.flac`, `to_media jpg --max 2048 *.heic`, `to_media m4b "My Book/"`:
the same options, the same safety rules and the same progress report whatever
you are converting. Every format also has a short alias you can call directly:
`to_mp3`, `to_jpg`, `to_m4b`.

> **Status:** inline conversion of mp3, m4b, jpg, png and webp works today.
> The job server and workers (`--queue`, `to_media server`, `to_media worker`)
> are designed but **not built yet**; see [DESIGN.md](DESIGN.md). Until then
> `--queue` and the server commands say so and do nothing.

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
- **Tags and orientation preserved.** Music tags carry into the MP3. Photos are
  rotated the way they were meant to be seen and keep their metadata unless you
  ask for `--strip`.
- **Folders in, folders out.** Give it a folder and it converts everything
  inside, recursively, in natural order (`track 2` before `track 10`). With
  `--out` the folder layout is preserved.
- **Audiobooks done right.** A folder of audio files becomes one `.m4b` with a
  titled chapter per file, the author and title worked out from the folder name
  or the tags, and the chapters in the right order without zero-padded names.
- **Rehearse first.** `--dry-run` prints the exact command for every file.
- **Built to scale out.** Jobs are plain data, so the planned job server can send
  the same work to a farm of machines (see [DESIGN.md](DESIGN.md)).

## Quick start

```bash
to_media formats                          # what is available on this machine
to_media mp3 ~/Music/Album                # every audio file in the folder, next to the originals
to_media mp3 --out ~/mp3 ~/Music/Album    # same, into another folder
to_media jpg --max 2048 ~/Photos/*.heic   # phone photos to shareable JPEGs
to_media m4b "Jane Doe - Sample Book/"    # a folder of files becomes one chaptered audiobook
to_media mp3 --dry-run *.flac             # show the commands, do nothing
```

## Usage

```text
to_media FORMAT [options] PATH ...
to_media formats
```

`FORMAT` is one of `mp3`, `m4b`, `jpg` (also `jpeg`), `png`, `webp`. Any command
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
| `-v`, `--verbose` | Report every file, not just skips and failures. |
| `--queue`, `--follow` | For the planned job server. Not available yet. |

### `mp3`

| Option | Meaning |
| --- | --- |
| `--quality 0-9` | Variable bitrate quality, 0 best (default 3). |
| `--bitrate RATE` | Constant bitrate instead, for example `192k`. |
| `--audiobook` | Small mono files for spoken word (quality 8, genre set to Audiobook). |

Reads FLAC, WAV, AIFF, M4A/M4B, AAC, OGG/Opus, WMA, WavPack and Monkey's Audio.

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
- **mp3** carries the tags across (ID3v2.3 plus ID3v1). Cover art is not copied.
- **m4b** treats each folder you give as one book, ordered naturally, with a chapter
  per file named from the file name (track numbers and "Chapter N" prefixes are
  stripped). Title, author and narrator come from your options, then the folder
  name (`Author - Title`, `Author - Title (Narrator)` or `Title by Author`), then
  the first file's tags. The narrator is stored in the composer tag and the genre
  is set to Audiobook. The book is written next to the folder unless you use
  `--out`.
- **Images** are rotated to their intended orientation and keep their metadata
  unless `--strip`.

## Installation

`to_media` is a Python 3 program that uses only the standard library (written for
Python 3.8 or newer, tested on 3.12). It drives these programs:

| Program | Needed for |
| --- | --- |
| `ffmpeg` and `ffprobe` | `mp3` and `m4b` |
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

- Only mp3, m4b, jpg, png and webp so far. Video (h264) and more formats are
  planned.
- No job server, workers or `--queue` yet.
- MP3 output does not copy cover art.
- m4b needs every file in a book to be readable by ffmpeg and joins them
  re-encoded to AAC; it does not keep the original codec.
- Animated images are converted from their first frame only.

## Development

```bash
python3 tests/test_to_media.py     # this tool's tests (real conversions need ffmpeg and ImageMagick)
tests/run_tests.sh                 # every tool's tests (from the repository root)
```

The design and the plan for the job server are in [DESIGN.md](DESIGN.md).

## License

MIT, see the repository [LICENSE](../LICENSE).
