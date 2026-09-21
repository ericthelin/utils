# tgz

**Unpack any archive into a tidy, correctly named folder, without ever spilling files into the current directory.**

`tgz` extracts `.tar.gz`, `.tgz`, `.tar.bz2`, `.tar.xz`, `.zip`, `.rar`, `.7z`,
`.jar`, `.apk` and single-file `.gz`/`.bz2`/`.xz` archives with one command. It
works out the type from the file's contents (not just its name), extracts to a
scratch area first, and then puts the result in exactly one sensibly named
place.

```console
$ ls
project-1.0.tar.gz  loose-files.zip
$ tgz project-1.0.tar.gz loose-files.zip
extracted to project (directory)
extracted to loose-files (directory)
```

## Why use it

- **One command for every format.** No more remembering whether it is
  `tar xzf`, `tar xjf`, `unzip`, `unrar x` or `7z x`.
- **No more "tar bomb" cleanup.** Archives that dump dozens of loose files into
  the current directory are the classic mess. `tgz` detects them and wraps the
  contents in a folder named after the archive.
- **No more nested `project/project/`.** When an archive already contains a
  single top-level folder, you get that folder, not a redundant extra level.
- **Never overwrites.** If the destination name is taken, you get `project_01`,
  `project_02`, and so on.
- **Recognises files by content.** A download with a wrong or missing extension
  is still identified using `file`.
- **Safe on things that are not archives.** Unrecognised files are skipped with
  a message; they are never executed.
- **Uses `aunpack` when you have it.** If the `atool` package is installed,
  `tgz` hands the work to it instead.

## Quick start

```bash
tgz archive.tar.gz              # extract one archive
tgz *.zip *.tar.gz              # extract several at once
```

Files are extracted into the directory you run the command from.

## Usage

```text
tgz <archive> [<archive> ...]
```

`tgz` has no options. Each argument is treated as an archive.

| Archive type | Needs |
| --- | --- |
| `.tar`, `.tar.gz`, `.tgz`, `.tar.bz2`, `.tar.xz` | `tar` (plus `gzip`, `bzip2`, `xz` as needed) |
| `.zip` | `unzip` |
| `.rar` | `unrar` |
| `.7z` | `7z` |
| `.jar`, `.apk` | `jar` (from a JDK) |
| single-file `.gz`, `.bz2`, `.xz` | `gzip`, `bzip2`, `xz` |

## How it behaves

1. The archive is identified with `file`, falling back to the file name.
2. It is extracted into a temporary directory (`tgz_XXXXXXX`) inside the current
   directory.
3. If the archive held **several** top-level entries, they are moved into a new
   folder named after the archive (`multi.tgz` becomes `multi/`; a name without
   a known archive extension gets `_extracted` appended).
4. If it held **one** top-level entry, that entry is moved out as it is.
5. Either way, an existing name is never overwritten: the new folder becomes
   `name_01`, `name_02`, and so on.
6. Single-file compressed files (`notes.txt.gz`) are decompressed into
   `notes.txt` here, and the original is left in place.
7. When `aunpack` is installed, steps 1 to 5 are done by `aunpack -x` instead,
   with its own naming rules.

Anything `tgz` cannot identify is reported as
`unable to find type for '<name>', skipping it.` and left alone.

## Installation

`tgz` is a single Perl script that uses only core Perl modules. It needs
`perl`, the `file` command, `mv`, and the extraction tools for the formats you
use (see the table above).

> **Tested on:** Linux Mint 22.3 (Ubuntu 24.04 base), Perl 5.38, GNU tar 1.35.
> Extraction of tar.gz, tar.bz2, tar.xz, tar, zip, 7z, jar and single-file
> gz was run there. `.rar` and `.apk` were not exercised. Instructions for
> all other systems list the packages that should provide each tool but have
> **not been tested by the author**; if a package name does not exist on your
> release, search your package manager for the command name.

### Debian, Ubuntu, Linux Mint, Pop!_OS (tested)

```bash
sudo apt update
sudo apt install perl file tar gzip bzip2 xz-utils unzip 7zip
# Optional
sudo apt install unrar          # .rar (multiverse/non-free repository)
sudo apt install default-jdk-headless   # .jar/.apk (provides `jar`)
sudo apt install atool          # if you want tgz to delegate to aunpack
```

On older releases the 7-Zip package is called `p7zip-full`.

### Fedora, RHEL, Rocky, AlmaLinux (untested)

```bash
sudo dnf install perl file tar gzip bzip2 xz unzip p7zip p7zip-plugins
sudo dnf install java-latest-openjdk-headless   # optional: jar
sudo dnf install atool                          # optional
```

`unrar` is in RPM Fusion (nonfree). Newer Fedora releases call the 7-Zip package
`7zip`.

### Arch Linux, Manjaro, EndeavourOS (untested)

```bash
sudo pacman -S perl file tar gzip bzip2 xz unzip 7zip unrar atool
sudo pacman -S jdk-openjdk        # optional: jar
```

### openSUSE (untested)

```bash
sudo zypper install perl file tar gzip bzip2 xz unzip 7zip unrar atool
sudo zypper install java-17-openjdk-headless   # optional: jar
```

### macOS (untested)

macOS ships `perl`, `file`, `tar` (bsdtar), `gzip`, `bzip2` and `unzip`. With
[Homebrew](https://brew.sh/):

```bash
brew install xz sevenzip unrar atool
brew install openjdk               # optional: jar
```

The macOS `tar` accepts the `--gzip`, `--bzip2` and `--xz` options `tgz` uses,
but this has not been verified.

### Windows (untested)

Use **WSL 2**: in an administrator PowerShell run `wsl --install -d Ubuntu`,
reboot, then follow the Debian/Ubuntu instructions inside Ubuntu. Windows files
are under `/mnt/c/...`. Native Windows is not supported.

### Verify the installation

```bash
for t in perl file tar gzip bzip2 unzip 7z; do
  command -v "$t" >/dev/null && echo "ok      $t" || echo "MISSING $t"
done
mkdir /tmp/tgz-check && cd /tmp/tgz-check
mkdir demo && echo hi > demo/a.txt && tar czf demo.tar.gz demo && rm -r demo
tgz demo.tar.gz && cat demo/a.txt      # prints: hi
```

### Putting `tgz` on your PATH

The repository keeps the real script in `tgz/` and an extensionless command
link in `bin/`. Add that directory to your `PATH`:

```bash
export PATH="/path/to/utils/bin:$PATH"     # add to ~/.bashrc or ~/.zshrc
```

## Troubleshooting

- **Running `tgz` does something unexpected**: another program named `tgz` is
  earlier on your `PATH`. The `mtools` package installs an unrelated `tgz`
  (`command -v -a tgz` lists every match), and a shell function or alias can shadow
  it too. Put this repository's `bin/` directory first on your `PATH`, or call it
  as `/path/to/utils/bin/tgz`.
- **`sh: 1: <tool>: not found`**: the extraction tool for that format is not
  installed; see the table under Usage.
- **`unable to find type ... skipping it`**: the file is not a recognised
  archive, or `file` could not identify it.
- **Names with quotes, `$` or backticks** in an archive's file name are not
  handled safely; rename the file first.
- **A folder named `tgz_XXXXXXX` is left over** only if `tgz` was interrupted;
  it is safe to delete.

## Limitations

- Only the formats listed above; there is no `.tar.zst`, `.lz` or `.cab`
  support without `aunpack`.
- No options: no choosing a destination directory, no listing, no password
  handling.
- Very large archives are extracted in the current directory's filesystem
  first, so make sure it has room.

## Development

```bash
bash tests/test_tgz.sh          # this tool's tests
tests/run_tests.sh              # every tool's tests (from the repository root)
```

## License

MIT, see the repository [LICENSE](../LICENSE).
