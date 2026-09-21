# clip

**One clipboard command that works the same on Linux, macOS and Windows shells: pipe text in, paste it anywhere.**

macOS has `pbcopy`, Wayland has `wl-copy`, X11 has `xclip` and `xsel`, Windows
has `clip.exe`. `clip` picks whichever is available so your scripts and muscle
memory work everywhere.

```console
$ git diff | clip            # now paste into an email or chat
$ cat ~/.ssh/id_ed25519.pub | clip
$ echo "some text" | clip -t # Linux: the middle-click (primary) selection
```

## Why use it

- **One name everywhere.** Write `cmd | clip` in a script or a dotfile and it
  works on any machine you use, with no `if uname` blocks.
- **Finds the right backend for you.** Wayland (`wl-copy`), X11 (`xclip`, then
  `xsel`), macOS (`pbcopy`), and Windows shells (`clip.exe`) are all tried in
  a sensible order.
- **Both Linux selections.** `--terminal` copies to the primary selection
  (paste with the middle mouse button) instead of the normal clipboard.
- **Fails fast and loudly.** Run it without piping anything and it tells you so
  immediately instead of hanging, and it says what it looked for when no
  clipboard tool is installed.
- **Tiny and dependency-free.** A single POSIX shell script; it only needs the
  clipboard tool your platform already has.

## Quick start

```bash
some-command | clip            # copy the output
clip < notes.txt               # copy a file
some-command | clip -t         # Linux: copy to the primary selection
```

## Usage

```text
command | clip [--terminal]
clip [--terminal] < file
```

| Option | Meaning |
| --- | --- |
| `-t`, `--terminal` | Linux only: copy to the primary (middle-click) selection instead of the clipboard. |

Text comes from standard input; `clip` refuses to run when standard input is a
terminal. On macOS, any other arguments are passed through to `pbcopy`.

| Exit status | Meaning |
| --- | --- |
| `0` | Copied. |
| `64` | Bad usage: no data on standard input, unsupported option, or `--terminal` off Linux. |
| `127` | No clipboard command was found. |

## How it behaves

`clip` uses the first of these that exists:

1. `pbcopy` (macOS)
2. `clip.exe` (when running under Git Bash, MSYS or Cygwin)
3. `wl-copy` (Wayland)
4. `xclip` (X11)
5. `xsel` (X11)

`--terminal` selects the primary selection for the Linux tools (`wl-copy
--primary`, `xclip -selection primary`, `xsel --primary`).

## Installation

`clip` is a single POSIX `sh` script. You need one clipboard tool for your
platform:

| Platform | Tool | Comes with the OS? |
| --- | --- | --- |
| macOS | `pbcopy` | Yes |
| Windows (Git Bash, MSYS2, Cygwin) | `clip.exe` | Yes |
| Linux, Wayland | `wl-copy` (package `wl-clipboard`) | No |
| Linux, X11 | `xclip` or `xsel` | No |

> **Tested on:** Linux Mint 22.3 (Ubuntu 24.04 base) with `xclip`; a real copy to
> both the clipboard and the primary selection was checked. The automated tests
> use stand-in programs to verify every backend choice, the macOS pass-through
> and the error cases, so the other backends are covered by simulation only.
> Installation commands for other systems are **untested by the author**.

### Debian, Ubuntu, Linux Mint, Pop!_OS (tested)

```bash
sudo apt update
sudo apt install xclip          # X11 (most desktops); or: wl-clipboard for Wayland
```

### Fedora, RHEL, Rocky, AlmaLinux (untested)

```bash
sudo dnf install xclip          # or: wl-clipboard
```

### Arch Linux, Manjaro, EndeavourOS (untested)

```bash
sudo pacman -S xclip            # or: wl-clipboard
```

### openSUSE (untested)

```bash
sudo zypper install xclip       # or: wl-clipboard
```

### macOS (untested)

Nothing to install: `pbcopy` is built in.

### Windows (untested)

In Git Bash, MSYS2 or Cygwin, `clip.exe` is built in and used automatically. In
**WSL 2**, install `xclip` or `wl-clipboard` (WSLg provides the display) and
follow the Debian/Ubuntu steps; `clip` does not call `clip.exe` from inside WSL.

### Verify the installation

```bash
echo "clip works" | clip
# then paste with Ctrl-V (or Cmd-V), or check with: xclip -selection clipboard -o
```

### Putting `clip` on your PATH

The repository keeps the script in `clip/` and an extensionless command link in
`bin/`. Add that directory to your `PATH`:

```bash
export PATH="/path/to/utils/bin:$PATH"     # add to ~/.bashrc or ~/.zshrc
```

## Troubleshooting

- **`no clipboard command found`**: install `xclip`, `xsel` or `wl-clipboard`
  (Linux).
- **`no standard input`**: pipe or redirect text into it; `clip` does not read
  from the keyboard.
- **Nothing pastes over SSH or in a text-only session**: there is no clipboard
  to reach. Use a terminal that supports OSC 52, or copy on the machine you are
  sitting at.
- **`--terminal is available only on Linux`**: primary selections exist only on
  X11 and Wayland.

## Limitations

- Copies text from standard input only; it does not paste.
- Only the tools listed above are supported.
- Under WSL it does not use Windows' `clip.exe`.
- On Linux the clipboard is owned by the copying program on X11; some tools
  clear it when the process exits unless a clipboard manager is running.

## Development

```bash
bash tests/test_clip.sh         # this tool's tests
tests/run_tests.sh              # every tool's tests (from the repository root)
```

## License

MIT, see the repository [LICENSE](../LICENSE).
