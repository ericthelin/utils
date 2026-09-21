# to_h264

**Batch-convert video files to compact, widely playable H.264/AAC with HandBrake, one command or a whole render farm.**

`to_h264` wraps `HandBrakeCLI` so that converting a pile of videos is a single
command: sensible presets, safe output naming, optional deletion of the
originals, and, if you have several machines, an optional work queue so they can
share the encoding.

```console
$ to_h264 -o ~/converted holiday.avi birthday.mkv
Encoding: /home/you/holiday.avi
...
Encoding: /home/you/birthday.mkv
...
$ ls ~/converted
birthday.m4v  holiday.m4v
```

## Why use it

- **HandBrake without the clicking.** The quality of HandBrake's encoder from a
  script or a shell loop, with none of the flags to remember.
- **Good defaults.** The default is HandBrake's *Fast 720p30* preset: a small,
  fast-to-play H.264 + AAC file. `--high_quality` switches to *HQ 1080p30
  Surround*; `--preset` accepts any preset name HandBrake knows.
- **Never clobbers your files.** Existing outputs are left alone unless you say
  `--force`, and originals are removed only with an explicit `--replace`, and
  only after a successful encode.
- **Polite to your computer.** `--nice` lowers the priority so the machine stays
  responsive during long encodes.
- **Pipeline friendly.** Feed it file names on standard input:
  `find . -name '*.avi' | to_h264`.
- **Scales out.** With a [Gearman](http://gearman.org/) job server, run
  `to_h264 --worker` on any number of machines and queue work from anywhere
  with `to_h264 --client`. Failed jobs are retried.
- **Rehearse first.** `--dry_run` prints the exact `HandBrakeCLI` command.

## Quick start

```bash
to_h264 movie.avi                       # movie.m4v in the current directory
to_h264 -o ~/converted *.mkv            # write into a directory
to_h264 -H film.mkv                     # higher-quality preset
to_h264 -n movie.avi                    # show the command, do nothing
find ~/videos -name '*.avi' | to_h264   # file names from standard input
```

## Usage

```text
to_h264 [options] <files>
```

Directories are not expanded; use your shell (`*.avi`) or `find`.

| Option | Meaning |
| --- | --- |
| `-h`, `--help` | Show the built-in help. |
| `-o`, `--output PATH` | Output directory (must already exist), otherwise used as the output file name. Default: the current directory. |
| `-H`, `--high_quality` | Use the `General/HQ 1080p30 Surround` preset. |
| `-p`, `--preset NAME` | Use any HandBrake preset (see `HandBrakeCLI -z`). Takes priority over `-H`. |
| `-b`, `--handbrake ARGS` | Extra options passed straight to HandBrake (appended after the preset). |
| `-f`, `--force` | Overwrite an existing output file. |
| `-R`, `--replace` | Delete the original after a successful encode. |
| `-N`, `--nice` | Run the encode under `nice`. |
| `-n`, `--dry_run` | Print the HandBrake command without running it. |
| `-v`, `--verbose` | More detail; repeat for more. |
| `-c`, `--client` | Queue the jobs on a Gearman server instead of encoding here. |
| `-w`, `--worker` | Run as a Gearman worker and encode queued jobs. |
| `-g`, `--gearman SERVERS` | Gearman servers, comma separated, `host` or `host:port` (default `127.0.0.1:4730`). |
| `-r`, `--retry N` | Retries for a failed queued job (default 0, which means unlimited). |

## How it behaves

- Each input `name.ext` becomes `name.m4v` in the output directory: H.264 video
  and AAC audio in an MP4 container, with fast-start enabled.
- The command is `HandBrakeCLI -i INPUT -o OUTPUT -O -r 29.97 -f mp4
  --main-feature <preset> <your -b options>`. The frame rate is set to 29.97,
  and `--main-feature` picks the longest title when the input is a DVD image.
- If the output already exists, the file is skipped with a message (use
  `--force` to overwrite).
- With `--replace`, the original is deleted only after HandBrake reports success
  and the output file exists.
- **Distributed mode** (`--client`/`--worker`) sends the input path and options
  to the queue as a job. Workers must see the input and output at the **same
  paths** as the client (shared storage, for example NFS).

## Installation

`to_h264` is a single Perl script. It needs HandBrake's command-line encoder and
two Perl modules; Gearman support is optional and loaded only when you use it.

| Requirement | Used for |
| --- | --- |
| `HandBrakeCLI` (HandBrake 1.x) | All encoding. Presets use the 1.x `General/...` names. |
| Perl modules `JSON::XS`, `Term::ANSIColor` | Job encoding and colour (the latter ships with Perl) |
| Perl modules `Gearman::Client`, `Gearman::Worker`, plus a `gearmand` server | Optional: `--client` and `--worker` |

> **Tested on:** Linux Mint 22.3 (Ubuntu 24.04 base), Perl 5.38, HandBrake
> 1.7.2. The automated tests run a real encode (H.264 + AAC), dry runs, preset
> selection, `--handbrake` appending, `--output`, overwrite protection and
> `--replace`. The Gearman modes were **not** tested at all. Other systems are
> **untested**; package names for them are best effort, so search your package
> manager if one is not found.

### Debian, Ubuntu, Linux Mint, Pop!_OS (tested)

```bash
sudo apt update
sudo apt install perl libjson-xs-perl handbrake-cli
```

The Gearman parts are optional: `sudo apt install gearman-job-server` and the
`Gearman::Client` and `Gearman::Worker` Perl modules from CPAN
(`sudo cpan Gearman::Client Gearman::Worker`).

### Fedora, RHEL, Rocky, AlmaLinux (untested)

`HandBrake-cli` is in [RPM Fusion](https://rpmfusion.org/).

```bash
sudo dnf install perl perl-JSON-XS
sudo dnf install HandBrake-cli          # after enabling RPM Fusion
```

### Arch Linux, Manjaro, EndeavourOS (untested)

```bash
sudo pacman -S perl perl-json-xs handbrake-cli
```

### openSUSE (untested)

```bash
sudo zypper install perl perl-JSON-XS
```

`HandBrakeCLI` is available from the Packman repository.

### macOS (untested)

```bash
brew install handbrake            # provides HandBrakeCLI; check with `brew info handbrake`
cpan JSON::XS
```

### Windows (untested)

Use **WSL 2**: `wsl --install -d Ubuntu` in an administrator PowerShell, then
follow the Debian/Ubuntu instructions inside Ubuntu. Your Windows files are
under `/mnt/c/...`. Native Windows is not supported.

### Verify the installation

```bash
HandBrakeCLI --version 2>&1 | grep -i "HandBrake [0-9]"
perl -MJSON::XS -e 'print "JSON::XS ok\n"'
ffmpeg -v error -f lavfi -i testsrc=s=320x240:d=2 /tmp/to_h264_demo.mp4
to_h264 -o /tmp /tmp/to_h264_demo.mp4      # writes /tmp/to_h264_demo.m4v
```

### Putting `to_h264` on your PATH

The repository keeps the script in `to_h264/` and an extensionless command link
in `bin/`. Add that directory to your `PATH`:

```bash
export PATH="/path/to/utils/bin:$PATH"     # add to ~/.bashrc or ~/.zshrc
```

## Troubleshooting

- **`Can't locate JSON/XS.pm`**: install `libjson-xs-perl` (or the equivalent).
- **`Encode Failed with exit code ...`**: run with `--verbose` to see the
  HandBrake command and try it by hand; an unknown `--preset` name is the most
  common cause (list valid ones with `HandBrakeCLI -z`).
- **`... already exists. To overwrite use -f`**: the output is already there.
- **Nothing happens when using `--client`**: check the Gearman server address
  with `--gearman` and that a `--worker` is running.

## Limitations

- Every output is `.m4v`, and the frame rate is set to 29.97.
- Inputs are individual files; directories are not expanded.
- If `--output` is not an existing directory it is treated as the output file
  name, so create the directory first.
- The Gearman client and worker modes are experimental and untested; workers
  need the same file paths as the client.
- The audio and video settings other than the preset are fixed; use
  `--handbrake` to change them.

## Development

```bash
bash tests/test_to_h264.sh      # this tool's tests (skips if HandBrakeCLI is missing)
tests/run_tests.sh              # every tool's tests (from the repository root)
```

## License

MIT, see the repository [LICENSE](../LICENSE).
