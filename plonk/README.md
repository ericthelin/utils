# plonk

**Install a downloaded Linux app with one command: AppImage, `.deb`, Flatpak, source tarball or installer script.**

You download something, and the next ten minutes go on figuring out how to
install it: move it somewhere, make it executable, add a menu entry, find an
icon. `plonk` looks at the file, does the right thing, and cleans up after
itself.

```console
$ plonk ~/Downloads/Obsidian-1.5.3-x86_64.AppImage
Symlink name [Obsidian.AppImage]:
Installed /home/you/Applications/Obsidian-1.5.3-x86_64.AppImage and symlinked as /home/you/Applications/Obsidian.AppImage
Launcher set: /home/you/.local/share/applications/Obsidian.desktop
  Exec: /home/you/Applications/Obsidian.AppImage
  Icon: /home/you/Applications/icons/Obsidian-1.5.3-x86_64.png
```

## Safety first

**`plonk` runs what you give it.** For installer scripts, `.run` files and any
executable, `plonk` may execute the file, and for `.deb` files it runs
`sudo apt install`. It does not check signatures or scan for malware. Only use
it on files you downloaded from a source you trust.

## Why use it

- **One command for five kinds of download.** AppImages, Debian packages,
  Flatpak bundles, source archives and self-running installers are all handled
  by the same `plonk <file>`.
- **AppImages done properly.** The file is moved into `~/Applications`, made
  executable, given a clean version-free name (`Obsidian-1.5.3-x86_64.AppImage`
  gets a stable `Obsidian.AppImage` link), and a menu launcher with the app's
  icon is created so it shows up in your application menu.
- **Upgrades are one command.** Run `plonk` on the new version and the
  stable link and launcher are repointed. The old links and duplicates are
  cleaned up.
- **`.deb` files that just install.** It runs `apt` (so dependencies are
  resolved), retries with `--fix-broken` if needed, and deletes the `.deb`
  afterwards.
- **Source archives built for you.** Tarballs are unpacked with
  [`tgz`](../tgz/README.md) and built with [`mmmake`](../mmmake/README.md).
- **Look before you leap.** `--dryrun` prints every step without doing it, and
  `--copy` keeps your original download.

## Quick start

```bash
plonk ~/Downloads/SomeApp-2.0-x86_64.AppImage   # install + launcher
plonk ~/Downloads/tool_1.2_amd64.deb            # apt install
plonk ~/Downloads/thing.flatpak                 # flatpak install --user
plonk ~/Downloads/project-1.0.tar.gz            # unpack, build, install
plonk --dryrun -v ~/Downloads/SomeApp.AppImage  # just show what would happen
```

## Usage

```text
plonk [options] <file>
```

| Option | Meaning |
| --- | --- |
| `<file>` | The download to install. |
| `-n`, `--dryrun` | Print what would be done instead of doing it. |
| `-v`, `--verbose` | Show every command as it runs. |
| `--copy` | Keep the original file. By default it is moved (AppImage) or deleted after a successful install (`.deb`, archive). |
| `--no-prompt` | Never ask questions (symlink name, launcher confirmation); use the defaults. |

## How it behaves

`plonk` decides what to do from the file name and type, in this order:

| The file is... | What happens |
| --- | --- |
| `*.AppImage` | Moved (or copied with `--copy`) to `~/Applications`, made executable. A symlink with the version, platform and architecture stripped from the name is created there (you are asked to confirm the name for a new one). An icon is extracted from the AppImage when possible, and a launcher is written to `~/.local/share/applications/<Name>.desktop`. |
| An executable outside `~/Downloads` | Offers to create a launcher for it (it does not move or run it). |
| `*.deb` | `sudo apt install <file>`; if that fails, `sudo apt --fix-broken install` and one retry. The `.deb` is deleted afterwards unless `--copy`. |
| `*.flatpak` | `flatpak install --user <file>`. |
| An archive (`.tar.gz`, `.tgz`, `.tar.bz2`, `.tar.xz`, `.zip`, `.rar`, `.7z`, ...) | Extracted with `tgz` into `./<name>_extract`; the archive is deleted afterwards unless `--copy`. If a `Makefile`, `CMakeLists.txt` or `configure` script is found, `mmmake` is run in that folder. If only `build.sh` is found, `mmmake` runs but does not recognise it. If nothing buildable is found you are told where the files are. |
| `*.run`, or a script | Made executable and **run**. |
| Anything else | `Unhandled file type`, exit status 2. |

`tgz` and `mmmake` are found next to `plonk` in this repository's `bin/`
directory, or on your `PATH`.

Even in `--dryrun` mode, `plonk` may create the `~/Applications` folder.

## Installation

`plonk` is a single Python 3 script (uses only the standard library; written for
Python 3.8 or newer, tested on 3.12). It is for **Linux desktops**. What else
you need depends on what you install:

| Needed for | Requires |
| --- | --- |
| AppImages | FUSE 2 (`libfuse2`) so that AppImages can run, and a desktop that reads `~/.local/share/applications` |
| `.deb` files | A Debian-family system with `apt` and `sudo` |
| `.flatpak` files | `flatpak` |
| Source archives | [`tgz`](../tgz/README.md) and [`mmmake`](../mmmake/README.md) from this repository, plus a compiler and `make` |
| Script detection | the `file` command |

> **Tested on:** Linux Mint 22.3 (Ubuntu 24.04 base) with Python 3.12, apt 2.8,
> Flatpak 1.14. The automated tests cover the AppImage install and upgrade
> flow, the launcher, dry runs, the `.deb` and Flatpak command lines (dry
> run only) and a source-archive build. Actually installing a `.deb` or a
> Flatpak was **not** tested. Other systems are **untested**.

### Debian, Ubuntu, Linux Mint, Pop!_OS (tested)

```bash
sudo apt update
sudo apt install python3 file libfuse2t64 build-essential flatpak
```

On releases before Ubuntu 24.04 the FUSE package is called `libfuse2`.

### Fedora, RHEL, Rocky, AlmaLinux (untested)

`.deb` installation is not available. AppImages, Flatpak and source archives
should work:

```bash
sudo dnf install python3 file fuse-libs make gcc flatpak
```

### Arch Linux, Manjaro, EndeavourOS (untested)

`.deb` installation is not available.

```bash
sudo pacman -S python file fuse2 base-devel flatpak
```

### openSUSE (untested)

`.deb` installation is not available.

```bash
sudo zypper install python3 file libfuse2 make gcc flatpak
```

### macOS and Windows

Not supported: AppImage, `.deb` and `.desktop` launchers are Linux concepts.
On Windows, WSL 2 runs the command-line parts (source archives), but there is no
desktop to add launchers to.

### Verify the installation

```bash
plonk --help
printf '#!/bin/sh\nexit 0\n' > /tmp/Demo-1.0-x86_64.AppImage
plonk --dryrun --no-prompt -v /tmp/Demo-1.0-x86_64.AppImage
```

The dry run should print the move, `chmod +x` and symlink steps and end with a
launcher preview naming `Demo.AppImage`.

### Putting `plonk` on your PATH

The repository keeps the script in `plonk/` and an extensionless command link in
`bin/`, which also holds `tgz` and `mmmake`. Add that directory to your `PATH`:

```bash
export PATH="/path/to/utils/bin:$PATH"     # add to ~/.bashrc or ~/.zshrc
```

## Troubleshooting

- **AppImage does nothing or reports a FUSE error**: install `libfuse2` (see
  above).
- **The launcher has no icon**: not every AppImage contains one that `plonk`
  can find; the launcher falls back to a generic icon.
- **The launcher does not appear in the menu**: log out and in, or run
  `update-desktop-database ~/.local/share/applications`.
- **`Unhandled file type`**: `plonk` does not recognise the file. Give it a
  `.AppImage`, `.deb`, `.flatpak`, archive, `.run` file or script.
- **The build step does nothing**: `mmmake` could not find a build system in
  the extracted folder. Look in `./<name>_extract`.

## Limitations

- Linux only, and `.deb` support is for Debian-family systems.
- It relies on file names to recognise types, and treats any other executable
  or script as something to run.
- Icon discovery is best-effort and may pick an unexpected image.
- It installs; there is no uninstall command. Delete the entries in
  `~/Applications` and `~/.local/share/applications` yourself.

## Development

```bash
bash tests/test_plonk.sh        # this tool's tests (uses a throwaway HOME)
tests/run_tests.sh              # every tool's tests (from the repository root)
```

## License

MIT, see the repository [LICENSE](../LICENSE).
