# ls-enhanced

**One directory-listing command with short, memorable flags that uses `eza` (or `exa`) for icons, colour and git status when you have it, and falls back to plain `ls` anywhere else.**

`ls-enhanced -l`, `-t`, `-s`, `-lT`: a handful of one-letter views (long list,
newest files, biggest files, tree) that behave the same on every machine you
use, whether it has a fancy modern `ls` replacement installed or nothing but
the basics.

An illustrative listing (your icons and columns will differ):

```console
$ ls-enhanced -l
 .git
 src
 Cargo.toml   1.2k eric 21 Sep 09:12 -- M
 README.md    3.4k eric 21 Sep 09:10 -- N
```

## Why use it

- **The same commands everywhere.** Put your aliases in your dotfiles once. On a
  server with only GNU `ls`, `-l` and `-s` still do the sensible thing.
- **Modern output when available.** With `eza` you get icons, colour-scaled
  sizes, directories listed first, and git status columns. Without it you get a
  tidy classic listing.
- **Views you actually use.** Newest last (`-d`), biggest (`-s`), a quick tree
  (`-lt`, `-lT`), one per line (`-dir`), and a full long listing (`-l`).
- **Never leaves you with an error.** If `eza` fails for any reason (an
  unsupported flag, a crash), the same view is re-run with plain `ls`.
- **Git-aware but forgiving.** Some `eza`/`exa` builds are compiled without git
  support; `ls-enhanced` detects that and simply skips the git columns.
- **Debuggable.** `-v` shows the exact command it ran; `-vv` and `-vvv` explain
  how it chose a tool and the flags.
- **Backend on demand.** Force `ls`, `eza` or `exa` with one environment variable.

## Quick start

`ls-enhanced` changes what some short flags mean, so it is meant to be used
through aliases rather than replacing `ls` in scripts:

```bash
# in ~/.bashrc or ~/.zshrc
alias l='ls-enhanced'
alias ll='ls-enhanced -l'
alias lt='ls-enhanced -lt'
alias lS='ls-enhanced -s'
```

```bash
ll ~/projects            # long listing, hidden files, directories first
lS                       # biggest files, in the current directory
ls-enhanced -v -l        # show the exact command that ran
```

## Usage

```text
ls-enhanced [view] [ls/eza options] [paths ...]
```

Give it at most one view flag. Anything else you type (paths and ordinary
options such as `-la` or `-h`) is passed to the underlying tool unchanged.
**With no options at all, even if you pass paths, you get the default view.**

| Flag | View | With `eza` / `exa` | With plain `ls` |
| --- | --- | --- | --- |
| *(none)* | Default | icons, sorted newest last, colour scale, git status | `-F` (mark types) with colour |
| `-d` | Everything, newest last | long, all files, group, modified, icons, colour scale | `-lart` with colour |
| `-l` | Long list, hidden files, directories first | `-l --all --group-directories-first --icons` + git | `-l --all` (+ directories first) |
| `-ll` | As `-l`, also showing `.` and `..` | `-l --all --all ...` + git | `-l -a -a` (+ directories first) |
| `-lt` | Two-level tree | `-T --level=2` with icons, git-ignore aware | `-l -t` (long, newest first) |
| `-llt` | Two-level long tree | `-lT --level=2` with icons, git-ignore aware | `-l -t` |
| `-lT` | Deeper tree (four levels) | `-T --level=4` with icons, git-ignore aware | `-laR` (recursive) |
| `-s` | Sorted by size | long, all files, sorted by size, icons + git | `-lagF -S` with colour |
| `-t` | Long list as a tree, newest last | long, all files, tree, icons + git | `-lagF -t` with colour |
| `-dir` | One entry per line | `-1 --icons` | `-1` |

| Verbosity | Effect |
| --- | --- |
| `-v`, `--verbose`, `-V` | Show the exact command that will be run. Repeat (`-vv`) or chain (`-VV`) for more. |
| Level 2 | Also shows which tools were found, which was chosen, and whether git columns are supported. |
| Level 3 | Also shows the raw arguments, the final flag list and what was dropped in a fallback. |

| Environment variable | Meaning |
| --- | --- |
| `LS_ENHANCED_TOOL` | Force `ls`, `eza` or `exa`. Fails clearly if the tool is not installed. |
| `LS_ENHANCED_VERBOSE` | Starting verbosity level (a non-negative integer). |

## How it behaves

- **Which tool:** `eza` if found, otherwise `exa`, otherwise `/bin/ls`. It looks on
  your `PATH` first, then in common install locations (Homebrew, `~/.cargo/bin`,
  `~/.local/bin`, and so on).
- **Fallback:** if `eza` or `exa` exits with an error, `ls-enhanced` prints
  `Command failed (exit code N), falling back to ls...`, drops the flags plain
  `ls` does not understand (icons, sort keys, tree and git flags) and runs `ls`
  instead. `eza`'s own error output is hidden, so run with `-v` to see the
  command it tried.
- **Colour:** `--color=auto` is switched to `--color-scale` for `eza` and `exa`.
  With plain `ls`, `--color=auto` is used, or `-G` on systems whose `ls` has that
  instead.
- **Only exact matches** of the flags above are treated as views. `-la`, `-h`,
  `-R` and friends are not, and reach the tool as you typed them.

## Installation

`ls-enhanced` is a single Bash script. It works with nothing but a standard
`ls`; `eza` (or `exa`) is recommended for the full experience, and your terminal
needs a [Nerd Font](https://www.nerdfonts.com/) for the icons to display
(otherwise they show as empty boxes).

> **Tested on:** Linux Mint 22.3 (Ubuntu 24.04 base) with Bash 5.2, GNU coreutils
> 9.4 `ls` and `eza` 0.18.2. The automated tests use a stand-in `eza` and check
> the flag mappings, the git-support probe, the fallback, verbosity and the
> environment variables. **macOS and BSD `ls` were not tested**, and neither were
> other distributions.

### Debian, Ubuntu, Linux Mint, Pop!_OS (tested)

```bash
sudo apt update
sudo apt install eza          # optional but recommended (older releases: exa)
```

### Fedora, RHEL, Rocky, AlmaLinux (untested)

```bash
sudo dnf install eza          # optional but recommended
```

### Arch Linux, Manjaro, EndeavourOS (untested)

```bash
sudo pacman -S eza
```

### openSUSE (untested)

```bash
sudo zypper install eza       # may need a newer repository than Leap's default
```

### macOS (untested)

```bash
brew install eza              # strongly recommended, see below
```

Without `eza`, the fallback uses GNU-style long options (`--all`,
`--group-directories-first`) that the BSD `ls` shipped with macOS does not
understand, so `-l` and friends may print an error. Install `eza`, or GNU
coreutils (`brew install coreutils`, then use `gls` via `LS_ENHANCED_TOOL`).

### Windows (untested)

Native Windows is not supported. Use **WSL 2** (`wsl --install -d Ubuntu`) and
follow the Debian/Ubuntu steps.

### Verify the installation

```bash
ls-enhanced -v -l .           # prints "Using command: ..." then a listing
LS_ENHANCED_TOOL=ls ls-enhanced -l .   # same view with plain ls
```

### Putting `ls-enhanced` on your PATH

The repository keeps the script in `ls_enhanced/` and an extensionless command
link in `bin/`. Add that directory to your `PATH`:

```bash
export PATH="/path/to/utils/bin:$PATH"     # add to ~/.bashrc or ~/.zshrc
```

## Troubleshooting

- **Icons show as boxes**: install a Nerd Font and select it in your terminal.
- **`Command failed ... falling back to ls`**: `eza` rejected a flag. Run with
  `-v` and try the printed command by hand.
- **Git columns are missing**: your `eza`/`exa` was built without git support, or
  you are not in a repository.
- **`LS_ENHANCED_TOOL=eza was requested, but eza was not found`**: install `eza`
  or unset the variable.
- **Errors on macOS without `eza`**: see the macOS section above.

## Limitations

- The view flags (`-d`, `-l`, `-s`, `-t`, ...) deliberately differ from their
  meanings in plain `ls`, so it is not a drop-in replacement for `ls` in scripts.
- Only one view flag makes sense per call; combining several is not defined.
- The same flag can look different between backends (for example `-t` is a tree
  with `eza` but a time-sorted list with `ls`).
- Plain-`ls` fallback needs GNU-style options; BSD `ls` is not fully supported.

## Development

```bash
bash tests/test_ls_enhanced.sh    # this tool's tests
tests/run_tests.sh                # every tool's tests (from the repository root)
```

## License

MIT, see the repository [LICENSE](../LICENSE).
