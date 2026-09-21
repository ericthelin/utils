# irmdir

**`rmdir` that clears out whole trees of empty folders in one go, and never touches a single file.**

`rmdir` only removes one empty directory at a time, and `rm -r` will happily
delete files you wanted. `irmdir` sits in between: point it at a folder and it
removes that folder and everything beneath it **if, and only if, they contain
nothing but other empty folders**. Anything that holds a file stays exactly where
it is.

```console
$ find photos_old
photos_old
photos_old/2019
photos_old/2019/raw
photos_old/2019/edits
photos_old/2020
$ irmdir -v photos_old
irmdir: removing directory, 'photos_old/2019/raw'
irmdir: removing directory, 'photos_old/2019/edits'
irmdir: removing directory, 'photos_old/2019'
irmdir: removing directory, 'photos_old/2020'
irmdir: removing directory, 'photos_old'
```

## Why use it

- **Tidy up after a clean-out.** After moving, deduplicating or deleting files,
  you are left with hundreds of empty folders. One command clears them.
- **It cannot delete your data.** Only directories are ever removed. Files,
  symlinks, sockets and pipes are never deleted, and a folder that holds any of
  them is kept, along with every folder above it.
- **Keeps the good, removes the rest.** In a tree where only some branches are
  empty, the empty branches go and the branches with files stay.
- **See before you commit.** `--dry-run` shows exactly what would be removed.
- **Drop-in for `rmdir`.** The familiar `-p` (also remove empty parents) and `-v`
  work as usual, and `-D` hands everything back to the system `rmdir`.
- **Symlinks are never followed.** A link to a folder is treated like a file, so
  it cannot lead `irmdir` outside the tree you named.

## Quick start

```bash
irmdir --dry-run -v old_project      # preview
irmdir old_project                   # remove it and any empty sub-folders
irmdir -p a/b/c                      # also remove a/b and a if they become empty
irmdir -D empty_folder               # behave exactly like plain rmdir
```

## Usage

```text
irmdir [options] <directory> [<directory> ...]
```

| Option | Meaning |
| --- | --- |
| `-r`, `-d`, `--recursive`, `--descendants` | Remove the directory and its empty descendants. This is the default. |
| `-D`, `--no-descendants`, `--no-recursive` | Turn recursion off and run the system `rmdir` with your other options. |
| `-p`, `--parents` | Afterwards remove each parent directory that has become empty, stopping at the first one that is not. |
| `-v`, `--verbose` | Say what is removed or skipped. |
| `--dry-run` | Report what would be removed without removing anything. |
| `--ignore-fail-on-non-empty` | Do not report directories that could not be removed because they are not empty. |
| `--help`, `--version` | Show `rmdir`'s help followed by irmdir's additions, or the version. |

The last recursion flag on the command line wins, as with most Unix tools.

## How it behaves

- **Only directories are removed.** A directory is removed only when everything
  inside it is an (already removed, or removable) directory.
- **A file blocks its branch.** The directory containing it, and its ancestors up
  to the folder you named, are kept. Sibling branches that are empty are still
  removed.
- **Symlinks count as files**, even links to directories, and are never
  followed or removed.
- **Exit status.** `0` when it finished normally, including when it left a
  folder in place because it held files (a message explains why); `1` for real
  errors such as a missing operand, a path that does not exist or is not a
  directory, or a permission problem.
- **`-p`** removes empty parents of each argument, working upwards, and stops at
  the current directory or the first parent that still has content (reported as
  an error unless `--ignore-fail-on-non-empty`).
- **`-D`** replaces `irmdir` with the system `rmdir`, so all of its behaviour
  applies exactly.

## Installation

`irmdir` is a single Python 3 script (standard library only; written for Python
3.8 or newer, tested on 3.12). It also needs the system `rmdir` command, which
is used for `-D`, `--help` and `--version`.

> **Tested on:** Linux Mint 22.3 (Ubuntu 24.04 base) with Python 3.12 and GNU
> coreutils `rmdir`. The automated tests cover empty and nested trees, folders
> with files, symlinks, FIFOs, permissions, `-p`, `--dry-run` and the `-D`
> fallback. Other systems are **untested by the author**.

### Debian, Ubuntu, Linux Mint, Pop!_OS (tested)

```bash
sudo apt update
sudo apt install python3 coreutils
```

### Fedora, RHEL, Rocky, AlmaLinux (untested)

```bash
sudo dnf install python3 coreutils
```

### Arch Linux, Manjaro, EndeavourOS (untested)

```bash
sudo pacman -S python coreutils
```

### openSUSE (untested)

```bash
sudo zypper install python3 coreutils
```

### macOS (untested)

macOS provides `rmdir` (BSD), which lacks GNU-only options such as
`--ignore-fail-on-non-empty` and `--help`; the recursive mode does not need
them. For full compatibility install GNU coreutils and put it first on your
`PATH`:

```bash
xcode-select --install       # python3
brew install coreutils       # optional: GNU rmdir (installed as grmdir)
```

### Windows (untested)

Native Windows is not supported. Use **WSL 2**: `wsl --install -d Ubuntu` in an
administrator PowerShell, then follow the Debian/Ubuntu steps inside Ubuntu.

### Verify the installation

```bash
mkdir -p /tmp/irmdir-demo/a/b /tmp/irmdir-demo/keep && echo hi > /tmp/irmdir-demo/keep/file
irmdir -v /tmp/irmdir-demo/a /tmp/irmdir-demo/keep
ls /tmp/irmdir-demo          # only "keep" remains, with its file
```

### Putting `irmdir` on your PATH

The repository keeps the script in `irmdir/` and an extensionless command link in
`bin/`. Add that directory to your `PATH`:

```bash
export PATH="/path/to/utils/bin:$PATH"     # add to ~/.bashrc or ~/.zshrc
```

## Troubleshooting

- **A folder was not removed.** It (or something below it) holds a file, a
  symlink or a special file. Run with `-v` to see which branch was skipped and
  why.
- **`Permission denied`.** You cannot modify that directory's parent.
- **`standard rmdir command not found`** (with `-D`): install coreutils.

## Limitations

- It cannot remove folders that contain files; use `rm -r` for that.
- Hidden files count as files, so a folder with only `.DS_Store` is kept.
- No interactive mode: it removes what qualifies without asking, so use `--dry-run`
  first on anything important.

## Development

```bash
python3 tests/test_irmdir.py    # this tool's tests
tests/run_tests.sh              # every tool's tests (from the repository root)
```

## License

MIT, see the repository [LICENSE](../LICENSE).
