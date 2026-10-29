# ls-enhanced

**One directory-listing command for short shell aliases that uses `eza` (or `exa`) for icons, colour and git status when you have it, and falls back to plain `ls` anywhere else.**

Set up aliases for a handful of views (long list, newest files, biggest files,
tree) that behave the same on every machine you use. Flags you type after an
alias go to the selected listing command.

An illustrative listing (your icons and columns will differ):

```console
$ ls-enhanced --ls-enhanced-view=long
 .git
 src
 Cargo.toml   1.2k eric 21 Sep 09:12 -- M
 README.md    3.4k eric 21 Sep 09:10 -- N
```

## Why use it

- **The same commands everywhere.** Put your aliases in your dotfiles once;
  their views work with `eza`, `exa`, or plain `ls`.
- **Modern output when available.** With `eza` you get icons, colour-scaled
  sizes, directories listed first, and git status columns. Without it you get a
  tidy classic listing.
- **Views you actually use.** A full listing (`d`), a named directory entry
  (`d -d`), biggest files (`s`), trees (`lt`, `lT`), one per line (`dir`), and a
  long listing (`l`).
- **Never leaves you with an error.** If `eza` fails for any reason (an
  unsupported flag, a crash), the same view is re-run with plain `ls`.
- **Git-aware but forgiving.** Some `eza`/`exa` builds are compiled without git
  support; `ls-enhanced` detects that and simply skips the git columns.
- **Debuggable.** `--ls-enhanced-verbose` shows the exact command it ran;
  repeat it for tool detection and argument details.
- **Backend on demand.** Force `ls`, `eza` or `exa` with one environment variable.

## Quick start

Use wrapper-specific long options in aliases so flags typed after an alias
still keep their normal `ls` meaning:

```bash
# in ~/.bashrc or ~/.zshrc
alias d='ls-enhanced --ls-enhanced-view=full'
alias ls='ls-enhanced --ls-enhanced-view=default'
alias l='ls-enhanced --ls-enhanced-view=long'
alias ll='ls-enhanced --ls-enhanced-view=extra-long'
alias lt='ls-enhanced --ls-enhanced-view=tree-2'
alias s='ls-enhanced --ls-enhanced-view=size'
```

```bash
ll ~/projects            # long listing, hidden files, directories first
s                        # biggest files, in the current directory
ls-enhanced --ls-enhanced-verbose --ls-enhanced-view=long
d project                 # list the contents of project
d -d project              # show the project directory entry itself
```

## Usage

```text
ls-enhanced [view] [ls/eza options] [paths ...]
```

Use one wrapper view flag. Paths and ordinary options such as `-d`, `-l`,
`-s`, `-t`, and `-h` are passed to the underlying tool unchanged.
**With no options at all, even if you pass paths, you get the default view.**

| Flag | View | With `eza` / `exa` | With plain `ls` |
| --- | --- | --- | --- |
| `--ls-enhanced-view=default` (or no view) | Default; used by `ls` | icons, sorted newest last, size colour scale, git status | `-F` (mark types) with colour |
| `--ls-enhanced-view=full` | Full listing of contents, newest last; used by `d` | long, all files, group, modified, icons, size colour scale | `-lart` with colour |
| `--ls-enhanced-view=long` | Long list, hidden files, directories first; used by `l` and `la` | `-l --all --group-directories-first --icons` + git | `-l --all` (+ directories first) |
| `--ls-enhanced-view=extra-long` | As long, also showing `.` and `..`; used by `ll` | `-l --all --all ...` + git | `-l -a -a` (+ directories first) |
| `--ls-enhanced-view=tree-2` | Two-level tree; used by `lt` | `-T --level=2` with icons, git-ignore aware | `-l -t` (long, newest first) |
| `--ls-enhanced-view=tree-2-long` | Two-level long tree; used by `llt` | `-lT --level=2` with icons, git-ignore aware | `-l -t` |
| `--ls-enhanced-view=tree-4` | Deeper tree (four levels); used by `lT` | `-T --level=4` with icons, git-ignore aware | `-laR` (recursive) |
| `--ls-enhanced-view=size` | Sorted by size; used by `s` | long, all files, sorted by size, icons + git | `-lagF -S` with colour |
| `--ls-enhanced-view=time` | Long list as a tree, newest last; used by `t` | long, all files, tree, icons + git | `-lagF -t` with colour |
| `--ls-enhanced-view=one-column` | One entry per line; used by `dir` | `-1 --icons` | `-1` |

`--full-list` is accepted as a compatibility spelling for
`--ls-enhanced-view=full` in shells that loaded an older `d` alias.

| Verbosity | Effect |
| --- | --- |
| `--ls-enhanced-verbose` | Show the exact command that will be run. Repeat for more detail. |
| Level 2 | Also shows which tools were found, which was chosen, and whether git columns are supported. |
| Level 3 | Also shows the raw arguments, the final flag list and what was dropped in a fallback. |

`ls-enhanced --help` shows this wrapper's options. `ls --help`, `d --help`,
and other aliases that include `--ls-enhanced-view` show the selected backend's
help instead.

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
  instead. `eza`'s own error output is hidden, so run with
  `--ls-enhanced-verbose` to see the
  command it tried.
- **Colour:** `--color=auto` is switched to `--color-scale=size` for `eza` and
  `exa`, so file sizes are shaded by magnitude. The age scale is left off
  because some `eza` builds abort (`No such local time`) on files whose
  timestamps are corrupt or fall in a daylight-saving gap.
  With plain `ls`, `--color=auto` is used, or `-G` on systems whose `ls` has that
  instead.
- **Only wrapper-specific long options** select a view. Explicit short flags
  reach the backend as typed.
- **Directory entries:** `-d` is a backend flag. The `d` alias's long view means
  `d path` lists the path's contents, while `d -d path` shows the named entry.
  For a symlink, the long view shows `-> target`.

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
understand, so `-l` and friends may print an error. Install `eza`; the
fallback always calls `/bin/ls`.

### Windows (untested)

Native Windows is not supported. Use **WSL 2** (`wsl --install -d Ubuntu`) and
follow the Debian/Ubuntu steps.

### Verify the installation

```bash
ls-enhanced --ls-enhanced-verbose --ls-enhanced-view=long .
LS_ENHANCED_TOOL=ls ls-enhanced --ls-enhanced-view=long .
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
  `--ls-enhanced-verbose` and try the printed command by hand.
- **`eza` panics with `No such local time`**: a file has a timestamp that does
  not exist in your time zone (often a corrupt birth time, see `stat`). That
  `eza` build cannot colour or format it; `ls-enhanced` avoids the age colour
  scale for this reason. Passing `--color-scale=age` or `--time=created` by hand
  can still trigger it.
- **Git columns are missing**: your `eza`/`exa` was built without git support, or
  you are not in a repository.
- **`LS_ENHANCED_TOOL=eza was requested, but eza was not found`**: install `eza`
  or unset the variable.
- **Errors on macOS without `eza`**: see the macOS section above.

## Limitations

- Backend flags can have different meanings between `eza`, `exa`, and plain
  `ls`; wrapper views give aliases predictable results across them.
- Combining several wrapper views is not defined.
- Plain-`ls` fallback needs GNU-style options; BSD `ls` is not fully supported.

## Development

```bash
bash tests/test_ls_enhanced.sh    # this tool's tests
tests/run_tests.sh                # every tool's tests (from the repository root)
```

## License

MIT, see the repository [LICENSE](../LICENSE).
