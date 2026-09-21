# to_mp3

**Convert a whole music or audiobook collection to MP3 in one command, keeping the tags.**

Point `to_mp3` at files or folders and it converts every audio file it
recognises (M4A, M4B, OGG, FLAC, WAV, AIFF, WMA and even oversized MP3s) to MP3,
carrying over the title, artist, album and other tags. It can shrink audiobooks
into small mono files, split a FLAC album image by its `.cue` sheet, and turn
one long audiobook into a file per chapter.

```console
$ to_mp3 --keep --out_dir mp3 ~/Music/Album
  ~~~~~~~~~~~~~~~~~~~~ ~/Music/Album/01 Opening.flac ~~~~~~~~~~~~~~~~~~~~
  ~~~~~~~~~~~~~~~~~~~~ ~/Music/Album/02 Second Song.flac ~~~~~~~~~~~~~~~~~~~~
$ ls mp3
01 Opening.mp3  02 Second Song.mp3
```

## Safety first

**By default `to_mp3` deletes each original after converting it.** Running it
with no arguments processes **every supported file under the current
directory, recursively**. Use `--dry_run` first to see what it would do and
`--keep` until you trust the result.

## Why use it

- **A whole library in one go.** Give it a directory and it works through every
  file it can convert, recursing into sub-folders. No shell loops.
- **Your tags survive.** Title, artist, album, year, genre, track number and
  comment are read from the source and written as ID3v2 tags.
- **FLAC albums, properly.** A single FLAC image with a `.cue` sheet is split
  into one tagged file per track (via `shntool` and `cuetools`) before
  conversion.
- **Audiobook mode.** `--audiobook` switches to a low-bitrate mono preset that
  makes spoken-word files a fraction of their size.
- **Tunable when you care.** Pass your own `lame` or `ffmpeg` quality
  arguments. The defaults are a good VBR (`-V 3`) quality.
- **Shrinks oversized MP3s.** Re-encode existing MP3s at a lower bitrate and
  see the before-and-after size for each.
- **Chapters to tracks.** With `--chapters`, a chaptered audiobook is split
  into one MP3 per chapter, named and numbered.
- **Safe to rehearse.** `--dry_run` prints every command without running it.

## Quick start

```bash
to_mp3 --dry_run ~/Music/Album                 # see what would happen
to_mp3 --keep --out_dir mp3 ~/Music/Album      # convert, keep originals
to_mp3 --audiobook --keep book.m4b             # small mono audiobook
to_mp3 song.wav                                # convert and delete the .wav
```

## Usage

```text
to_mp3 [options] [files or directories ...]
```

With no arguments, the current directory (recursively) is used.

| Option | Meaning |
| --- | --- |
| `-h`, `--help` | Show the built-in help. |
| `-n`, `--dry_run` | Print every command without running it. |
| `-k`, `--keep` | Keep the original files. |
| `-d`, `--out_dir DIR` | Write the results into `DIR` (created if missing) instead of next to the originals. |
| `-a`, `--audiobook` | Audiobook preset: mono, low bitrate (`lame -V 8 -mm`, `ffmpeg -q:a 8 -ac 1`). Ignored if you give `--lame` or `--ffmpeg`. |
| `-l`, `--lame ARGS` | Arguments for `lame` (default `-h -V 3`). Only affects conversions done by `lame`. |
| `-f`, `--ffmpeg ARGS` | Arguments for `ffmpeg` (default `-q:a 3`). Only affects conversions done by `ffmpeg`. |
| `-c`, `--chapters` | Audible files only: write one MP3 per chapter. |
| `-A`, `--audible KEYS` | Audible activation bytes to try (space separated). Overrides the keys file. |
| `-K`, `--audible_keys FILE` | File of activation bytes (default `~/.config/to_mp3/audible_keys`). |
| `-t`, `--inaudible_tables DIR` | Advanced: see the Audible section. |
| `-s`, `--skip_tag` | Accepted but currently has no effect. |
| `-v`, `--verbose` | Show more detail; repeat (`-vv`) for even more. |

## How it behaves

| Input | How it is converted |
| --- | --- |
| `.m4a`, `.m4b`, `.wma` | `ffmpeg` with the LAME encoder, tags copied (ID3v2.3 and ID3v1) |
| `.ogg` | `oggdec` piped into `lame`, tags read with `ogginfo` |
| `.flac` | `flac` piped into `lame`, tags read with `metaflac`. If a same-named `.cue` file exists, the image is first split into tracks with `shnsplit` and tagged with `cuetag`. |
| `.wav`, `.aiff` | `lame` |
| `.aa`, `.aax` | See the Audible section |
| `.mp3` | Re-encoded with `lame` (tags kept, sizes reported). Without `--out_dir` the result replaces the original; with `--keep` it is written as `name.new.mp3`. |

- Output is written next to the source (same name with `.mp3`), or into
  `--out_dir`.
- A conversion counts as successful only when `lame` or `ffmpeg` exits cleanly
  and the output file exists and is non-empty. Originals are deleted only after
  success (unless `--keep`).
- When a required program is missing, `to_mp3` lists what to install and asks
  whether to continue anyway; it only needs the programs for the formats you
  actually convert.
- Terminal output is colourised.

### Audible audiobooks (`.aa`, `.aax`)

`to_mp3` can convert Audible files you own. Decoding needs the activation bytes
(an 8-digit hex key) for the Audible account that bought the file.

- Put your key or keys in `~/.config/to_mp3/audible_keys` (or
  `$XDG_CONFIG_HOME/to_mp3/audible_keys`), one or more per line, `#` for
  comments:

  ```text
  # my audible account
  0123abcd
  ```

- Or pass them on the command line: `--audible "0123abcd 4567ef01"`.
- `to_mp3` tries each key until one decodes the file.
- **No keys are included with this tool.** Keep your keys file private
  (`chmod 600`) and never commit it.
- Advanced: `--inaudible_tables DIR` points at a local checkout of
  rainbow tables which `to_mp3` will use to try to recover the key from the
  file when none of your keys work. Nothing is downloaded or bundled.
- Only convert content you have the right to convert. Laws about removing DRM
  vary by country.

Output goes to `Artist/Title/` (or `Artist/Series/NN Title/` for books named
`Title: Series, Book N`), under `--out_dir` if given.

## Installation

`to_mp3` is a single Perl script. It needs Perl with the modules `Try::Tiny` and
`Term::ANSIColor` (the latter ships with Perl), plus the audio programs for the
formats you convert:

| Program | Used for |
| --- | --- |
| `ffmpeg` | m4a, m4b, wma, Audible conversion |
| `lame` | every conversion to MP3 except the ffmpeg ones |
| `flac`, `metaflac` | FLAC input |
| `oggdec`, `ogginfo` (package `vorbis-tools`) | OGG input |
| `mp3info` | re-encoding existing MP3s |
| `shnsplit` (package `shntool`), `cuetag` (package `cuetools`) | splitting FLAC images by a `.cue` sheet |

> **Tested on:** Linux Mint 22.3 (Ubuntu 24.04 base), Perl 5.38, ffmpeg 6.1.
> WAV, FLAC (with tags), M4A and the dry-run, deletion, and Audible-key-file
> behaviour are covered by the automated tests. OGG, WMA, MP3 re-encoding,
> `.cue` splitting, and real `.aax` conversion were **not** exercised. Other
> systems are **untested**; package names for them are best effort, so search
> your package manager if one is not found.

### Debian, Ubuntu, Linux Mint, Pop!_OS (tested)

```bash
sudo apt update
sudo apt install perl libtry-tiny-perl ffmpeg lame flac vorbis-tools mp3info shntool cuetools
```

### Fedora, RHEL, Rocky, AlmaLinux (untested)

`ffmpeg` and `lame` come from [RPM Fusion](https://rpmfusion.org/).

```bash
sudo dnf install perl perl-Try-Tiny flac vorbis-tools cuetools shntool mp3info
sudo dnf install ffmpeg lame          # after enabling RPM Fusion
```

If `mp3info` or `shntool` are not available for your release, `to_mp3` still
works for the formats that do not need them.

### Arch Linux, Manjaro, EndeavourOS (untested)

```bash
sudo pacman -S perl perl-try-tiny ffmpeg lame flac vorbis-tools
yay -S mp3info shntool cuetools      # AUR packages
```

### openSUSE (untested)

```bash
sudo zypper install perl perl-Try-Tiny ffmpeg lame flac vorbis-tools cuetools
```

`ffmpeg` and `lame` come from Packman. `mp3info` and `shntool` may need to be
built from source.

### macOS (untested)

With [Homebrew](https://brew.sh/):

```bash
brew install ffmpeg lame flac vorbis-tools shntool cuetools mp3info
cpan Try::Tiny
```

Package availability in Homebrew varies; use `brew search <name>`. The system
Perl is used.

### Windows (untested)

Use **WSL 2**: `wsl --install -d Ubuntu` in an administrator PowerShell, then
follow the Debian/Ubuntu instructions inside Ubuntu. Your files are under
`/mnt/c/...`. Native Windows is not supported.

### Verify the installation

```bash
for t in perl ffmpeg lame flac; do
  command -v "$t" >/dev/null && echo "ok      $t" || echo "MISSING $t"
done
perl -MTry::Tiny -e 'print "Try::Tiny ok\n"'
ffmpeg -v error -f lavfi -i sine=d=1 /tmp/to_mp3_demo.wav
to_mp3 --keep --out_dir /tmp/to_mp3_out /tmp/to_mp3_demo.wav   # creates /tmp/to_mp3_out/to_mp3_demo.mp3
```

### Putting `to_mp3` on your PATH

The repository keeps the script in `to_mp3/` and an extensionless command link
in `bin/`. Add that directory to your `PATH`:

```bash
export PATH="/path/to/utils/bin:$PATH"     # add to ~/.bashrc or ~/.zshrc
```

## Troubleshooting

- **`Warning: <program> not found`** with a suggested `apt install` line: install
  the package, or answer `Y` to continue if you do not need that format.
- **Nothing was converted**: only the listed extensions are handled; anything
  else is ignored silently.
- **Odd file names**: names are shell-escaped, but exotic characters in
  directory names passed to `find` may misbehave; rename if needed.
- **`Unable to find an audible key`**: none of your keys decoded the file; check
  the keys file (the message names the path it looked in).
- **Tags missing on OGG or FLAC results**: only title, artist, album, genre,
  date, track number and comment are carried over.

## Limitations

- Deletes originals by default (see Safety first).
- Only the tag fields listed above are preserved; cover art is not.
- `--skip_tag` is accepted but does nothing.
- File and directory arguments are passed to `find`, so a leading `-` or a
  glob-like name may be misread.
- There is no progress bar; use `--verbose` to see what is running.

## Development

```bash
bash tests/test_to_mp3.sh       # this tool's tests (skips if lame/flac/ffmpeg are missing)
tests/run_tests.sh              # every tool's tests (from the repository root)
```

## License

MIT, see the repository [LICENSE](../LICENSE).
