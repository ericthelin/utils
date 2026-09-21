# to_m4b

**Turn a folder of MP3 or Opus files into a single chaptered audiobook (`.m4b`) that any audiobook player understands.**

A book that arrives as 60 separate MP3s is a pain to load, sort and resume.
`to_m4b` joins them into one `.m4b` file with a chapter for every original
file, sets the title and author from the folder name or the tags, and marks it
as an audiobook, so players remember your place, show chapters and skip
sensibly.

```console
$ to_m4b --keep "Jane Doe - Sample Book"
Processing directory: Jane Doe - Sample Book
Found 2 audio files
Combining 2 files into: ./Jane Doe - Sample Book.m4b
Successfully created: ./Jane Doe - Sample Book.m4b
```

## Safety first

**By default `to_m4b` deletes the source files after a successful
conversion.** Use `--keep` until you have checked the result, and `--dry_run`
to preview.

## Why use it

- **One file, real chapters.** Each source file becomes a titled chapter, so you
  can jump around in any player that supports chapters (Apple Books, Audiobookshelf,
  Plex, Smart AudioBook Player, and so on).
- **Small files.** Audio is encoded as AAC at 32 kbps by default, which is
  plenty for spoken word and keeps a full-length book compact. Choose another
  rate with `--bitrate`.
- **Metadata worked out for you.** Title and author come from names like
  `Author - Title` or `Title by Author`, then from the files' own tags; override
  anything with `--title`, `--author`, `--narrator`.
- **Clean chapter names.** Track numbers and "Chapter 3" prefixes are stripped
  from file names to make readable chapter titles.
- **Fast-start files.** The output is laid out for streaming so it opens
  instantly.
- **Ctrl-C is safe.** Interrupting cancels ffmpeg, removes the partly written
  file and asks whether to continue with the rest.
- **Rehearse first.** `--dry_run` prints the exact `ffmpeg` commands.

## Quick start

```bash
to_m4b --keep "Author - Book Title"            # a folder of MP3s becomes one m4b
to_m4b --keep --out_dir ~/Audiobooks book_dir  # write it somewhere else
to_m4b --keep -c part1.mp3 part2.mp3           # combine specific files
to_m4b --keep single_file.mp3                  # convert one file
```

## Usage

```text
to_m4b [options] <folders or files ...>
```

| Option | Meaning |
| --- | --- |
| `-h`, `--help` | Show the built-in help. |
| `-n`, `--dry_run` | Print the commands without running them. |
| `-k`, `--keep` | Keep the original files. |
| `-d`, `--out_dir DIR` | Write results to `DIR` (created if missing). |
| `-t`, `--title TITLE` | Override the book title. |
| `-a`, `--author AUTHOR` | Override the author. |
| `-r`, `--narrator NAME` | Set the narrator. |
| `-c`, `--force_combine` | With several files, combine them into one book (otherwise each file is converted on its own). |
| `-b`, `--bitrate RATE` | AAC bitrate (default `32k`). |
| `-v`, `--verbose` | More detail; repeat for more. |

## How it behaves

- **A folder** is searched recursively for `.mp3` and `.opus` files, which are
  sorted by path and combined in that order (so number your files with leading
  zeros: `01`, `02`, ... `10`). The result is written **next to the folder**
  (in its parent directory) unless you use `--out_dir`.
- **A single file** is converted to an `.m4b` next to it.
- **Several files with `-c`** are combined into one book, written next to the
  first file.
- **The output name** is `Author - Title.m4b`, with characters that are unsafe
  in file names replaced by `_`.
- **Chapter titles** come from the file names with leading track numbers and
  "Chapter N" prefixes removed; if nothing is left the chapter is called
  `Chapter N`.
- **Metadata**: `genre` is set to `Audiobook`, `date` to the current year,
  `narrator` if you gave one, and title, artist and album artist as detected or
  overridden. Names are parsed from folder names of the form `Author - Title`
  or `Title by Author`, then the first file's tags, then its file name.
- The audio is re-encoded once, to AAC in an MP4 container with the `moov` atom
  at the front (`+faststart`).

## Installation

`to_m4b` is a single Perl script. It needs the Perl module `JSON` (`Term::ANSIColor`
and the rest ship with Perl) and these programs:

| Program | Used for |
| --- | --- |
| `ffmpeg`, `ffprobe` | Reading durations and encoding |
| `mp3info` | Reading tags from MP3 files (required at startup even for Opus-only jobs) |

> **Tested on:** Linux Mint 22.3 (Ubuntu 24.04 base), Perl 5.38, ffmpeg 6.1.
> Combining a folder of MP3s, chapters and metadata, `--keep`, deletion and
> `--dry_run` are covered by the automated tests. Opus input and Ctrl-C
> handling were **not** exercised. Other systems are **untested**; package
> names for them are best effort, so search your package manager if one is not
> found.

### Debian, Ubuntu, Linux Mint, Pop!_OS (tested)

```bash
sudo apt update
sudo apt install perl libjson-perl ffmpeg mp3info
```

### Fedora, RHEL, Rocky, AlmaLinux (untested)

`ffmpeg` comes from [RPM Fusion](https://rpmfusion.org/).

```bash
sudo dnf install perl perl-JSON mp3info
sudo dnf install ffmpeg          # after enabling RPM Fusion
```

### Arch Linux, Manjaro, EndeavourOS (untested)

```bash
sudo pacman -S perl perl-json ffmpeg
yay -S mp3info                   # AUR
```

### openSUSE (untested)

```bash
sudo zypper install perl perl-JSON ffmpeg
```

`ffmpeg` comes from Packman. `mp3info` may need to be built from source.

### macOS (untested)

```bash
brew install ffmpeg mp3info
cpan JSON
```

Use `brew search mp3info` if the name has changed.

### Windows (untested)

Use **WSL 2**: `wsl --install -d Ubuntu` in an administrator PowerShell, then
follow the Debian/Ubuntu instructions inside Ubuntu. Files on your Windows
drives are under `/mnt/c/...`. Native Windows is not supported.

### Verify the installation

```bash
for t in perl ffmpeg ffprobe mp3info; do
  command -v "$t" >/dev/null && echo "ok      $t" || echo "MISSING $t"
done
perl -MJSON -e 'print "JSON ok\n"'
mkdir -p "/tmp/Demo Author - Demo Book"
ffmpeg -v error -f lavfi -i sine=d=2 -c:a libmp3lame "/tmp/Demo Author - Demo Book/01 - One.mp3"
ffmpeg -v error -f lavfi -i sine=d=2 -c:a libmp3lame "/tmp/Demo Author - Demo Book/02 - Two.mp3"
to_m4b --keep --out_dir /tmp/m4b_out "/tmp/Demo Author - Demo Book"   # creates /tmp/m4b_out/Demo Author - Demo Book.m4b
```

### Putting `to_m4b` on your PATH

The repository keeps the script in `to_m4b/` and an extensionless command link
in `bin/`. Add that directory to your `PATH`:

```bash
export PATH="/path/to/utils/bin:$PATH"     # add to ~/.bashrc or ~/.zshrc
```

## Troubleshooting

- **`Missing required programs`**: install the package it names.
- **Chapters are in the wrong order**: files are ordered by name; add leading
  zeros to track numbers.
- **Author and title are wrong**: name the folder `Author - Title`, or pass
  `--author` and `--title`.
- **`No MP3 or Opus files found`**: only `.mp3` and `.opus` files are
  considered.
- **`Cannot get duration for <file>`**: that file is unreadable and is left
  out of the book.

## Limitations

- Input is MP3 or Opus only (other formats: convert with `ffmpeg` first).
- Deletes sources by default.
- No cover art handling; add it afterwards with a tagging tool.
- Folder-name parsing is deliberately simple: names with extra dashes may be
  split in the wrong place.
- One book per run per folder; it does not split a folder into several books.

## Development

```bash
bash tests/test_to_m4b.sh       # this tool's tests (skips if ffmpeg/mp3info are missing)
tests/run_tests.sh              # every tool's tests (from the repository root)
```

## License

MIT, see the repository [LICENSE](../LICENSE).
