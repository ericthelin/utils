# hist_search

**A better Ctrl-R for your shell: fuzzy or regex search through your whole command history, in one small Python file with no dependencies.**

Press Ctrl-R, type a few letters of what you remember, and the matching
commands appear instantly, ranked, right under your prompt. Pick one and it
lands on your command line for editing. It is not run until you press Enter
again.

An illustrative session:

```text
$ ▮                      <- you press Ctrl-R
[FUZZY] > dkr up
> docker compose up -d
  docker compose up
  docker stack deploy -c stack.yml up-demo
4/5821  Enter:select  Tab:toggle-regex  Ctrl-C/Esc:cancel
```

## Why use it

- **Find commands by the letters you remember.** Fuzzy matching means `dkr up`
  finds `docker compose up`. No exact substring needed.
- **Or search by pattern.** Press Tab to switch to regular expressions
  (`^git (push|pull)`) when you need precision.
- **Smart ranking.** The tightest match wins, then the earliest, then the most
  recent, so what you want is usually the top result.
- **No fzf, no plugins, no install step.** One Python file that uses only the
  standard library, plus a short shell snippet to bind the key.
- **It stays out of your way.** The picker opens inline under your prompt
  instead of taking over the screen, and hands the space back when you are
  done. Your terminal history is untouched.
- **Edit before you run.** The selected command is placed on the command line,
  never executed for you.
- **Cleaner history.** Duplicates are collapsed to the most recent use, and
  multi-line commands are shown on one line.
- **Safe.** It only reads your history file. It never writes to it or deletes
  anything.

## Quick start

Add one line to your `~/.zshrc` and start a new shell:

```zsh
source /path/to/utils/hist_search/zsh_hist_search_widget.zsh
```

Now press **Ctrl-R**. Type to filter, Up/Down to choose, Enter to select.

## Usage

The widget binds Ctrl-R. Inside the picker:

| Key | Action |
| --- | --- |
| Type | Filter the list. The query is matched fuzzily (case-insensitive). |
| `Tab` | Switch between FUZZY and REGEX mode. Regex matching is case-sensitive. |
| `Up` / `Ctrl-P` | Move up the list. |
| `Down` / `Ctrl-N` | Move down the list. |
| `Backspace` | Delete the last character of the query. |
| `Enter` | Choose the highlighted command and put it on your command line. |
| `Esc` / `Ctrl-C` | Cancel and leave the command line as it was. |

You can also run the picker directly: `hist_search` prints the chosen command
to standard output, which is how the widget captures it. It takes no
arguments; it reads the history file named by the `HISTFILE` environment
variable.

```bash
cmd=$(hist_search) && echo "You picked: $cmd"
```

## How it behaves

- **History file.** `$HISTFILE` if set, otherwise `~/.zsh_history`, otherwise
  `~/.bash_history`.
- **Formats.** zsh extended history (`: 1690000000:0;command`) and plain
  one-command-per-line files. Backslash-continued (multi-line) commands are
  kept together. Bash timestamp lines (`#1690000000`) are ignored.
- **Order.** Newest first, with each distinct command shown once (its most
  recent use).
- **Fuzzy ranking.** The characters you type must appear in order. Results with
  the smallest gap between the first and last matched character rank first,
  then those matching earlier in the line, then the more recent command.
- **Regex ranking.** Commands whose match starts earliest rank first, then the
  more recent.
- **Display.** Up to 10 matches (fewer on very short terminals), plus a status
  line showing matches/total. Multi-line commands show a `⏎` marker between
  lines.
- **The terminal.** The picker draws on `/dev/tty`, so it works inside
  `$(...)` capture and does not disturb what is already on screen.

## Installation

`hist_search` is a single Python 3 script (uses only the standard library:
written for Python 3.8 or newer, tested on 3.12). It needs a Unix-like system
with a real terminal (`termios`), and the widget is written for **zsh**.

> **Tested on:** Linux Mint 22.3 (Ubuntu 24.04 base) with Python 3.12 and zsh
> 5.9. The automated tests drive the real picker through a pseudo-terminal and
> check the zsh widget. Everything for other systems, and the bash snippet, is
> **untested by the author**.

### Debian, Ubuntu, Linux Mint, Pop!_OS (tested)

```bash
sudo apt update
sudo apt install python3 zsh
```

### Fedora, RHEL, Rocky, AlmaLinux (untested)

```bash
sudo dnf install python3 zsh
```

### Arch Linux, Manjaro, EndeavourOS (untested)

```bash
sudo pacman -S python zsh
```

### openSUSE (untested)

```bash
sudo zypper install python3 zsh
```

### macOS (untested)

zsh is the default shell. Install Python 3 if you do not have it:

```bash
xcode-select --install       # includes python3
# or: brew install python
```

### Windows (untested)

Native Windows is not supported (the picker uses Unix terminal control). Use
**WSL 2**: `wsl --install -d Ubuntu` in an administrator PowerShell, then follow
the Debian/Ubuntu steps inside Ubuntu.

### Enable it in zsh

```zsh
# in ~/.zshrc
source /path/to/utils/hist_search/zsh_hist_search_widget.zsh
```

The widget finds `hist_search.py` next to itself, so the repository can live
anywhere. If you use another tool that also binds Ctrl-R (fzf, oh-my-zsh
plugins), source this file **after** it.

### Enable it in bash (untested)

Bash has no widget file yet. This should work in `~/.bashrc`:

```bash
bind -x '"\C-r": READLINE_LINE=$(hist_search); READLINE_POINT=${#READLINE_LINE}'
PROMPT_COMMAND='history -a'      # write each command to ~/.bash_history immediately
```

### Verify the installation

```bash
python3 --version
printf ': 1:0;git status\n: 2:0;ls -la\n' > /tmp/hist_demo
HISTFILE=/tmp/hist_demo hist_search      # type: ls  then press Enter; prints: ls -la
```

### Putting `hist_search` on your PATH

The repository keeps the script in `hist_search/` and an extensionless command
link in `bin/`. Add that directory to your `PATH` if you want to run
`hist_search` directly (the zsh widget does not need it):

```bash
export PATH="/path/to/utils/bin:$PATH"     # add to ~/.bashrc or ~/.zshrc
```

## Troubleshooting

- **Ctrl-R still does the old thing.** Something loaded after the widget
  rebinds the key. Move the `source` line to the end of `~/.zshrc`.
- **My latest commands are missing.** zsh only writes history to the file at
  exit by default. Add `setopt INC_APPEND_HISTORY` (or `SHARE_HISTORY`) to
  `~/.zshrc`.
- **Nothing happens when I press Ctrl-R.** Your history file is empty or
  `HISTFILE` points somewhere else. Check `echo $HISTFILE`.
- **Arrow keys print `^[[A`.** Your terminal was left in a strange mode by
  another program; the picker resets it on start, so update to the latest
  version of this tool.
- **The list is short.** On a terminal under 14 rows tall, fewer results fit.

## Limitations

- Read-only: it cannot delete or edit history entries.
- Typing in the query is limited to printable ASCII characters.
- No preview pane, multi-select or timestamps.
- No support for history stored in fish or PowerShell formats.
- Unix-like systems only.

## Development

```bash
python3 tests/test_hist_search.py    # this tool's tests (needs a pseudo-terminal)
tests/run_tests.sh                   # every tool's tests (from the repository root)
```

## License

MIT, see the repository [LICENSE](../LICENSE).
