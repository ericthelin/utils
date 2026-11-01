# verify_media

Check downloaded audio and video files for truncation and corruption, so you know a torrent really finished.

```console
$ verify_media ~/Downloads/Some.Audiobook/
BAD  /home/me/Downloads/Some.Audiobook/Part 07.mp3
       - truncated: header says 120.0s, only 49.9s decodes
BAD  /home/me/Downloads/Some.Audiobook/Part 12.mp3
       - zero-filled gap of 512 KiB (missing torrent pieces?)
48 checked, 2 bad
```

## Why use it

A torrent client can report "100%" while a file still holds zero-filled holes,
or a copy can stop short. You usually find out hours later, mid-chapter or
mid-movie. `verify_media` finds those files in one pass, without the original
`.torrent`: it decodes every file the way a player would and compares what
actually plays against what the file claims. By default it only reports; with `--move-to` it can file the good
directories for you. The exit status makes it usable in scripts.

## Quick start

```bash
verify_media path/to/folder      # check everything media-like below it
verify_media -q big_movie.mkv    # fast check, no full decode
```

## Usage

`verify_media [options] PATH...`

| Option | Meaning |
| --- | --- |
| `PATH...` | Files, or directories searched recursively for media files. |
| `-q`, `--quick` | Skip the full decode: only the zero-gap, container and stream checks. |
| `-z KIB`, `--zero-run KIB` | Flag a run of at least KIB KiB of zero bytes (default 256; `0` disables). |
| `-j N`, `--jobs N` | Files checked in parallel within a directory (default 2). |
| `-m DIR`, `--move-to DIR` | As each directory argument checks out good, offer to move it into DIR. |
| `-y`, `--yes` | With `--move-to`, move every good directory without asking. |
| `-f`, `--force` | With `--move-to`, check every file and still offer to move directories that contain bad files. |
| `-v`, `--verbose` | Also list files that are OK. |

Recognised extensions: mp3, m4a, m4b, aac, flac, ogg, opus, wma, wav, mp4, m4v,
mov, mkv, webm, avi, wmv, mpg, mpeg, ts. Files named explicitly are always
checked; the extension filter applies only to directory searches.

Directories are searched recursively. Directories are processed one at a time,
and results appear as they finish. With `--move-to`, each directory you pass is
one unit (one torrent): once all of its files have been checked, a directory that
holds at least one media file and no bad file is offered for moving right away,
before the next directory starts. Since a directory with a bad file will not be
moved, checking stops at its first bad file: the files still running are killed,
the rest are skipped, and the directory is reported as `KEEP ... N files not
checked`. This early stop applies only with `--move-to`; without it every file
is checked and reported. Add `--force` to check every file anyway and be asked
about moving the directory regardless (the prompt shows the number of BAD files).
To process a folder full of torrents, pass its
children: `verify_media -m ~/Audiobooks ~/Downloads/*/`.

Exit status: `0` all files OK, `1` at least one bad file or a directory that
could not be moved, `2` usage error or missing ffmpeg, `130` interrupted with
Ctrl-C.

## How it behaves

For each file it reports as BAD when any of these hold:

1. The file is empty.
2. It contains a run of zero bytes of at least 256 KiB (the typical signature of
   torrent pieces that were never downloaded). Skipped for `.wav`, where silence
   is legitimately zeros.
3. `ffprobe` cannot read the container (for example an MP4 missing its `moov`
   atom because the end was cut off) or finds no audio or video stream.
4. A full decode with `ffmpeg` prints errors.
5. The duration in the header is more than 2 seconds (or 1%) longer than what
   actually decodes.

The full decode reads every byte, so large videos take a while; use `-q` for a
quick pass.

## Installation

| Dependency | Used for | Required |
| --- | --- | --- |
| Python 3.9+ | Runs the tool | Yes |
| ffmpeg (provides `ffmpeg` and `ffprobe`) | Probing and decoding | Yes |

Tested on Ubuntu (Linux 6.8) with the distribution's ffmpeg and Python 3. The
other platforms below are untested.

- Debian/Ubuntu: `sudo apt install ffmpeg`
- Fedora/RHEL: `sudo dnf install ffmpeg` (enable RPM Fusion first)
- Arch: `sudo pacman -S ffmpeg`
- openSUSE: `sudo zypper install ffmpeg` (Packman repository)
- macOS: `brew install ffmpeg`
- Windows: use WSL 2 with the Debian/Ubuntu steps, or install ffmpeg and Python natively and run `python verify_media.py`

Then put the repository's `bin/` directory on your `PATH`.

**Verify:** `verify_media --help` prints the usage, and `ffprobe -version` works.

## Troubleshooting

- `missing ffmpeg, ffprobe`: install the ffmpeg package for your platform.
- A good file reported with a zero-filled gap: raise the limit with `-z 4096`, or disable it with `-z 0`.
- A damaged but playable file passes: see Limitations.

Progress: on a terminal a live status line shows how many files are done and,
for each file being checked, its stage (`scan`, `probe`, `decode`) and percent
complete (decode percent is decoded time against the header duration). When the
output is not a terminal, each file is listed as `CHECK path` on stderr as it
starts instead.

Moving: when a directory passes you are asked
`Move SRC -> DEST/name? [y]es / [n]o / [a]ll / [q]uit`. Enter means no; `a` moves
this and every later good directory without asking; `q` stops the run, leaving
the remaining directories unchecked. Without a terminal, `--move-to` requires
`--yes`. A directory is skipped, and reported, if the destination already has
one of the same name or lies inside it. Moves across filesystems copy then
delete. A directory with a bad file is reported as `KEEP` and stays where it is, unless
`--force` is given. With `--force`, a directory with bad files is always asked about individually;
answering `a` does not cover it, only `--yes` does.

Ctrl-C: stops at once, kills any running `ffmpeg`/`ffprobe`, prints
`Interrupted.` and exits with status 130. Nothing is half-moved, because a move
only starts after you answer a prompt.

## Limitations

- It cannot prove a file is bit-exact. A few flipped bytes inside valid audio
  data may decode without errors. For a guarantee, verify the piece hashes
  with your torrent client's "force recheck".
- Header-less formats (some MP3s without a Xing/LAME header) have no reliable
  stored duration, so a clean cut at a frame boundary may only be caught by
  the other checks.
- It never repairs or deletes files, and moves only whole good directories on request.

## Development

```bash
python3 verify_media/tests/test_verify_media.py
```

## License

See the repository's `LICENSE`.
