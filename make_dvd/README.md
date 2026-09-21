# make_dvd

**Turn your video files into a standard DVD-Video disc with one command.**

`make_dvd` is a command-line DVD authoring tool in the spirit of DeVeDe. Point
it at one or more video files (MP4, MKV, AVI, M4V, MOV, or anything ffmpeg can
read) and it produces a standards-compliant DVD-Video ISO sized to fit a
standard DVD-5 disc. Give it several files and it builds a menu, then plays
them back to back on its own. When you are ready, it can burn the disc too.

Illustrative session:

```console
$ make_dvd "Family Holiday 2019.mkv" "Birthday.mp4" "School Play.avi"
3 title(s), 94.2 min, NTSC 16:9, video 8000 kbps, target dvd5, menu yes
  1. Family Holiday 2019.mkv: 12 chapters (source)
  2. Birthday.mp4: 4 chapters (5 min)
  3. School Play.avi: 9 chapters (5 min)
Output: /home/you/dvd.iso
[########################################] 100.0%  elapsed 6:12  ETA 0:00 (done ~14:32)
ISO size 3.94 GB of 4.70 GB
Burn dvd.iso to a blank DVD now? [y/N]
```

## Why use it

- **Works in the car, on the old TV, at grandma's house.** A DVD plays
  in ordinary DVD players, with no apps, no accounts, no streaming box and
  no Wi-Fi. If you
  have ever tried to explain USB codecs to a relative, you already know why.
- **No guessing about size.** It measures your videos and picks the video
  bitrate so everything fits the disc, using as much of it as the picture
  benefits from. No more coasters from an ISO that was 100 MB too big.
- **A real DVD menu, automatically.** Several videos get a menu listing every
  title. If nobody presses anything, the disc starts playing title 1 after a
  few seconds and continues through the rest in order, ideal for a car or a
  waiting room, where nobody is holding a remote.
- **Chapters, automatically.** Chapter marks embedded in your source files are
  carried over. Files without chapters get a marker every 5 minutes, so "next
  chapter" is always useful.
- **Handles awkward video for you.** It detects NTSC or PAL from the source,
  keeps the correct widescreen or 4:3 shape (letterboxing rather than
  stretching), and adds silent audio when a file has none.
- **Progress you can trust.** A progress bar with a live completion-time
  estimate, from the first encoded frame to the finished disc.
- **Automatable.** Everything is a flag, it exits with proper status codes,
  and `--dry-run` shows the plan without encoding anything. A file chooser
  appears when you run it with no arguments on a desktop.
- **No GUI, no ads, no license nag.** It is a single Python script driving
  well-known open-source tools, and it is MIT licensed.

## Quick start

```bash
# 1. Install the dependencies (see "Installation" below), then:
make_dvd movie.mkv                  # movie.iso in the current directory
make_dvd ep1.mkv ep2.mkv ep3.mkv    # dvd.iso with an auto-playing menu
make_dvd                            # no arguments: pick files in a chooser
make_dvd movie.iso                  # burn an existing ISO (asks first)
```

## Usage

```text
make_dvd [options] [files ...]
```

| Option | Meaning |
| --- | --- |
| `files ...` | Video files to convert, in the order they should appear. With none, a file chooser opens (needs `zenity` and a desktop session). A single `.iso` argument means "burn this ISO". |
| `-o, --output PATH` | Where to write the ISO. Default: the current directory, named after the first video (`movie.iso`), or `dvd.iso` for several videos. |
| `-t, --title TEXT` | Disc name and menu heading. Default: the file name, or "Movie Collection". |
| `-s, --size {dvd5,dvd9}` | Target disc size. Default `dvd5` (4.7 GB). `dvd9` is the 8.5 GB dual-layer disc. |
| `--standard {ntsc,pal}` | Video standard. Default: chosen from the first file's frame rate (25 fps is PAL, everything else NTSC). |
| `--aspect {4:3,16:9}` | Display shape. Default: 16:9 if any source is widescreen, otherwise 4:3. |
| `--menu-timeout N` | Seconds the menu waits before auto-playing title 1. Default 5. |
| `--no-menu` | Skip the menu even with several files; the disc simply starts playing title 1. |
| `-b, --burn` | After building the ISO, burn it without asking. With a lone `.iso` argument, skip the confirmation. |
| `-d, --device PATH` | Optical drive to burn to. Default `/dev/cdrom` (or `/dev/sr0`). |
| `--speed N` | Burn speed. Default 8; `0` lets the drive decide. |
| `--workdir DIR` | Keep the intermediate files (encoded video, menu images, authoring XML) in this directory instead of a temporary one. |
| `-n, --dry-run` | Print the plan (titles, chapters, bitrate, output path) and stop. |

### Examples

```bash
# Preview what would happen, without encoding anything
make_dvd -n *.mkv

# A dual-layer disc for a long series, written to a specific file
make_dvd -s dvd9 -t "Season One" -o ~/isos/season1.iso s01e*.mkv

# Build and burn in one go, no questions asked
make_dvd --burn --speed 4 wedding.mp4

# Force PAL and 4:3 for an old European TV
make_dvd --standard pal --aspect 4:3 tape_transfer.avi

# Just burn an ISO you already have (asks before starting)
make_dvd ~/isos/season1.iso
```

## How it behaves

### Disc size and quality

The video bitrate is calculated from the total running time so that video,
audio and the menu fit the target disc with a safety margin (97 % of nominal
capacity). It is capped at 8 Mbps, because higher rates add nothing on a
DVD. Audio is AC-3 stereo at 192 kbps. The script refuses to continue if the
content is so long that video would fall under 1 Mbps (use `--size dvd9` or
fewer files), and it checks the finished ISO against the disc capacity.

Short or low-detail videos can produce an ISO much smaller than the disc: the
encoder simply has nothing to spend the extra bits on. That is normal, not a
fault. A 131-minute, 700x468 source, for example, comes out around 2.2 GB.

### The menu

With more than one video, the disc opens on a menu listing each title. Use the
remote's arrow keys and OK/Enter to pick one. If nothing is pressed for
`--menu-timeout` seconds, title 1 starts, and each title flows into the next.
After the last title the disc returns to the menu and waits (it does not loop
forever). A single video has no menu and starts playing immediately.

Up to 10 titles fit on the menu. For more, use `--no-menu`, or split them
across discs.

### Chapters

If a source file has chapter marks (common in MKV and M4V), they become the
DVD chapters for that title. Marks closer than 10 seconds together are merged,
and a title never exceeds the DVD limit of 99 chapters. Files without usable
chapters get one every 5 minutes. Use "next chapter" on the remote to skip.
The plan printed at the start (and by `--dry-run`) tells you which was used for
every title.

### Burning

`--burn`, the prompt after a build, or a lone `.iso` argument all use
`xorriso` to write the disc. Before writing, the script checks that a blank disc
of sufficient size is in the drive and asks you to insert one if not. A DVD-R is
the most widely compatible blank. The progress bar and estimate continue
through the burn (the progress figures are read from `xorriso`'s output, so
the display may vary between drives). Burning is currently supported on Linux
only; see below for other systems.

## Installation

`make_dvd` is a single Python 3 script that uses only the standard library
(written for Python 3.8 or newer, tested on 3.12).
It drives these programs, all of which must be on your `PATH`:

| Program | Used for | Required |
| --- | --- | --- |
| `ffmpeg` and `ffprobe` | Reading your videos and encoding them to DVD MPEG-2/AC-3 | Yes |
| `dvdauthor` (includes `spumux`) | Building the DVD structure and menu buttons | Yes |
| `genisoimage` | Packing the DVD structure into an ISO | Yes |
| ImageMagick (`convert`) | Drawing the menu background and button highlights | Yes |
| `xorriso` | Burning to a disc | Only for burning |
| `zenity` | The graphical file chooser | Only when run with no file arguments |
| DejaVu Sans font | Menu text (falls back to ImageMagick's default font if absent) | Optional |

The script checks for the required programs at startup and tells you which are
missing.

> **Tested on:** Linux Mint 22.3 (Ubuntu 24.04 base) with Python 3.12,
> ffmpeg 6.1, dvdauthor 0.7.2, genisoimage 1.1.11, ImageMagick 6.9 and
> xorriso 1.5.6. Everything below for other systems lists the packages that
> provide each program but has **not been tested by the author**; check the
> "Verify" step and adjust package names for your distribution version.

### Debian, Ubuntu, Linux Mint, Pop!_OS (tested)

```bash
sudo apt update
sudo apt install python3 ffmpeg dvdauthor genisoimage imagemagick fonts-dejavu-core
# Optional: file chooser and burning
sudo apt install zenity xorriso
```

### Fedora, RHEL, Rocky, AlmaLinux (untested)

Fedora's own `ffmpeg-free` omits some video decoders (notably H.264), so you
will want the full `ffmpeg` from [RPM Fusion](https://rpmfusion.org/). `dvdauthor`
is also packaged there.

```bash
sudo dnf install \
  https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm
sudo dnf install ffmpeg dvdauthor genisoimage ImageMagick dejavu-sans-fonts
sudo dnf install zenity xorriso      # optional
```

If `genisoimage` is not available for your release, the `mkisofs` from
`cdrtools` works if you make it answer to that name:
`sudo ln -s "$(command -v mkisofs)" /usr/local/bin/genisoimage`.

### Arch Linux, Manjaro, EndeavourOS (untested)

```bash
sudo pacman -S python ffmpeg dvdauthor imagemagick ttf-dejavu
sudo pacman -S zenity xorriso        # optional
# genisoimage comes from cdrkit, which is in the AUR:
yay -S cdrkit
```

### openSUSE (untested)

```bash
sudo zypper install python3 ffmpeg dvdauthor mkisofs ImageMagick dejavu-fonts
sudo zypper install zenity xorriso   # optional
```

Packman (<https://packman.links2linux.org/>) provides the full `ffmpeg` and
`dvdauthor`. If there is no `genisoimage`, symlink `mkisofs` as shown for
Fedora.

### macOS (untested)

Encoding and ISO creation should work; burning from the script does not
(device names differ, so use the macOS tools below). Install
[Homebrew](https://brew.sh/), then:

```bash
brew install python ffmpeg dvdauthor imagemagick cdrtools
```

`cdrtools` provides `mkisofs` rather than `genisoimage`, and ImageMagick 7
prefers the name `magick` over `convert`. If the script reports either as
missing, add compatibility links:

```bash
ln -s "$(command -v mkisofs)" /usr/local/bin/genisoimage
ln -s "$(command -v magick)"  /usr/local/bin/convert
```

To burn the finished ISO: `hdiutil burn dvd.iso` (or right-click the ISO in
Finder and choose *Burn Disk Image*).

### Windows (untested)

Run the tool inside **WSL 2**, which gives you a real Ubuntu:

1. In an administrator PowerShell: `wsl --install -d Ubuntu`, then reboot and
   finish the Ubuntu setup.
2. In the Ubuntu shell, follow the Debian/Ubuntu instructions above. Your
   Windows drives appear under `/mnt/c/...`, so
   `make_dvd /mnt/c/Users/you/Videos/movie.mp4 -o /mnt/c/Users/you/movie.iso`
   works.
3. WSL cannot reach your DVD drive, so burn the finished ISO from Windows:
   right-click the `.iso` and choose **Burn disc image**, or use a free tool
   such as ImgBurn.

The file chooser needs a desktop session (WSLg on Windows 11 provides one);
otherwise pass file names on the command line.

### Containers and other systems

Any system with an Ubuntu or Debian container can use the Debian instructions
above. Tools like Distrobox make a container behave like part of your desktop.
Native Windows and BSD systems are not supported.

### Verify the installation

```bash
for t in ffmpeg ffprobe dvdauthor spumux genisoimage convert; do
  command -v "$t" >/dev/null && echo "ok      $t" || echo "MISSING $t"
done
make_dvd --help
```

Every line should say `ok`. Running `make_dvd -n somevideo.mkv` also
confirms the tools work together without encoding anything.

### Putting `make_dvd` on your PATH

The repository keeps the real script in `make_dvd/` and an extensionless command
link in `bin/`. Add that directory to your `PATH`:

```bash
export PATH="/path/to/utils/bin:$PATH"     # add to ~/.bashrc or ~/.zshrc
```

## Troubleshooting

- **"Missing required tools"**: install the listed package(s) from the
  Installation section.
- **The ISO is much smaller than the disc.** Normal for short or low-detail
  video. See "Disc size and quality".
- **"Content is too long for dvd5"**: the running time does not fit at usable
  quality. Use `--size dvd9` or split the content across discs.
- **Burning says "Cannot access /dev/cdrom".** Another program (a media
  player, a file manager) has the drive open. Close it and retry. It can also
  mean the tray is open or you lack permission: on Linux, be in the `cdrom`
  group.
- **Burning says the disc is not blank.** Use a new DVD-R; used discs (other
  than erased rewritables) are rejected on purpose.
- **A very old player will not read the disc.** DVD-R media is the most
  compatible. Burning slower (`--speed 4`) can also help.
- **No file chooser appears.** It needs `zenity` and a graphical session;
  otherwise pass the file names as arguments.

## Limitations

- Titles are converted with their first video and first audio track only;
  extra audio tracks and subtitles are not carried across.
- The menu shows plain text titles taken from the file names (10 maximum).
- Chapter names from the source are not shown, since DVD chapters are numbered.
- DVD-Video only. Blu-ray and data discs are out of scope.

## Development

The tool is a single file, `make_dvd.py`, with unit tests in `tests/`:

```bash
python3 tests/test_make_dvd.py
```

or run every tool's tests from the repository root with `tests/run_tests.sh`.

## License

MIT, see the repository [LICENSE](../LICENSE).
