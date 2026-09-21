# dvd2iso

**Turn a DVD in your drive into a single, playable ISO file with one command, with a sensible name picked from the disc.**

Old family videos on DVD-R, camp recordings, discs you bought and want to keep
safe: `dvd2iso` copies the whole disc (menus, extras, every title) into one
`.iso` you can store, mount, burn again or play. It is the reverse of
[`make_dvd`](../make_dvd/README.md).

```console
$ dvd2iso -o ~/isos
DVD Volume Label: FAMILY_VIDEOS_2009
Please Enter Disk label: Family_Videos_2009
Will create /home/you/isos/Family_Videos_2009.iso!
...
done: Mon Sep 21 09:52:10 AM MDT 2026
```

## Legal note

Copy only discs you have the right to copy. Many commercial DVDs are encrypted,
and reading them needs a decryption library (`libdvdcss`) that this tool does
not include or require for unencrypted discs. Whether copying an encrypted disc
is lawful depends on where you live.

## Why use it

- **Preserves the whole disc.** Menus, all titles, extras and the exact DVD-Video
  structure are kept, so the ISO plays like the original.
- **One command, one file.** No juggling `dvdbackup` and `genisoimage` options.
  The result is a single `.iso`.
- **Names discs for you.** It reads the disc's volume label, tidies it
  (`FAMILY_VIDEOS_2009_WS` becomes `Family_Videos_2009`) and offers it as the
  file name, ready to accept or edit.
- **Safe to interrupt.** Press Ctrl-C and you are asked whether to delete the
  temporary files and the partial ISO.
- **Cleans up after itself.** The multi-gigabyte working folder is removed when
  the ISO is finished, and the disc is ejected so you can load the next one.
- **Configurable once.** Put your usual output and temp folders in
  `~/.dvd2isorc` and forget about them.
- **Rehearse first.** `--dry_run` prints every command without running any.

## Quick start

```bash
dvd2iso                              # rip to the current directory, asks for a name
dvd2iso -o ~/isos                    # rip into ~/isos, asks for a name
dvd2iso -o ~/isos/Holiday2019.iso    # choose the file name yourself
dvd2iso -n -o ~/isos                 # show what would happen
```

## Usage

```text
dvd2iso [options]
```

| Option | Meaning |
| --- | --- |
| `-o`, `--out PATH` | Output: a folder (you are asked for a name) or a file ending in `.iso`. Default: the current directory. A folder that does not exist is created. Needs about 8 GB free. |
| `-t`, `--temp PATH` | Where the working copy is made. Default: the output folder. Needs about 8 GB free. |
| `-d`, `--dev DEVICE` | The drive to read. Default: the first of `/dev/dvd`, `/dev/sr0`, `/dev/cdrom`, `/dev/cdrw`, `/dev/cdr` that exists. |
| `-l`, `--label LABEL` | Volume label for the ISO (32 characters at most). |
| `-E`, `--no_eject` | Do not eject the disc when finished or on failure. |
| `-D`, `--defaults FILE` | Read defaults from `FILE` instead of `~/.dvd2isorc`. |
| `-n`, `--dry_run` | Print the commands without running them. |
| `-v`, `--verbose` | More output; repeat for more. |
| `-h`, `--help` | Show the built-in help. |

### The defaults file

`~/.dvd2isorc` (or the file named by `--defaults`) holds one setting per line:
`option = value` for options with a value, or just the option name for switches.
Lines starting with `#` are comments. Settings given on the command line win.

```text
# ~/.dvd2isorc
out = /media/isos
temp = /var/tmp
no_eject
```

## How it behaves

1. The output path and drive are checked, and the two helper programs are
   looked for.
2. If you gave a folder (or nothing), the disc's volume label is read from the
   disc and offered as the file name. Generic labels such as `DVD_VIDEO` are
   dropped, ALL-CAPS labels are converted to Title Case, and endings like
   `_WS`, `_FS`, `_16x9` and `_4x3` are removed.
3. It prints what it will create and **waits five seconds**: press Ctrl-C now to
   abort with nothing touched.
4. `dvdbackup -M` mirrors the whole disc into a temporary folder.
5. `genisoimage -dvd-video` packs it into `NAME.iso`.
6. The temporary folder is deleted and the disc is ejected.

Read errors on the disc (`Error reading VTS ... at block`) abort the run: the
temporary files are removed, the disc is ejected and an error is reported. If
`genisoimage` fails, the temporary folder is left in place so you can inspect it.

An existing ISO with the same name is overwritten (with a warning).

## Installation

`dvd2iso` is a single Perl script using core modules only. It needs these
programs:

| Program | Used for |
| --- | --- |
| `dvdbackup` | Copying the DVD's contents |
| `genisoimage` | Building the ISO |
| `eject` | Ejecting the disc |
| `libterm-readline-gnu-perl` (optional Perl module) | Pre-fills the disc-name prompt with the suggested name |
| `libdvdcss` (optional, not included) | Only for encrypted discs; see the legal note |

> **Tested on:** Linux Mint 22.3 (Ubuntu 24.04 base), Perl 5.38, with a stand-in
> for `dvdbackup`. The automated tests check everything around the copy: the
> output path and naming, temp folder handling and clean-up, the label option,
> the rc file, dry runs, ejecting and building a valid DVD-Video ISO with
> `genisoimage`. **The actual disc copy with `dvdbackup` was not tested by the
> author.** Other systems are **untested**.

### Debian, Ubuntu, Linux Mint, Pop!_OS

```bash
sudo apt update
sudo apt install perl dvdbackup genisoimage eject libterm-readline-gnu-perl
```

### Fedora, RHEL, Rocky, AlmaLinux (untested)

`dvdbackup` is in [RPM Fusion](https://rpmfusion.org/); check with `dnf search dvdbackup`.

```bash
sudo dnf install perl dvdbackup genisoimage eject perl-Term-ReadLine-Gnu
```

### Arch Linux, Manjaro, EndeavourOS (untested)

```bash
sudo pacman -S perl dvdbackup cdrkit util-linux
```

`cdrkit` provides `genisoimage`, and `eject` is in `util-linux`. If `cdrkit` is
not in the repositories it is in the AUR.

### openSUSE (untested)

```bash
sudo zypper install perl dvdbackup mkisofs eject
```

If `genisoimage` is not available, make `mkisofs` answer to that name:
`sudo ln -s "$(command -v mkisofs)" /usr/local/bin/genisoimage`.

### macOS (untested)

Not supported: the script relies on Linux-style device names and `eject`.
Ripping on a Mac is better done with other tools.

### Windows (untested)

Not supported natively. WSL 2 cannot reach a DVD drive, so rip on a Linux
machine.

### Verify the installation

```bash
for t in perl dvdbackup genisoimage eject; do
  command -v "$t" >/dev/null && echo "ok      $t" || echo "MISSING $t"
done
dvd2iso -n -o /tmp        # with a disc inserted: prints the commands, changes nothing
```

### Putting `dvd2iso` on your PATH

The repository keeps the script in `dvd2iso/` and an extensionless command link
in `bin/`. Add that directory to your `PATH`:

```bash
export PATH="/path/to/utils/bin:$PATH"     # add to ~/.bashrc or ~/.zshrc
```

## Troubleshooting

- **`dvdbackup not found`** or **`genisoimage not found`**: install the package
  named in the message.
- **`Invalid DVD device`**: pass your drive with `--dev /dev/sr0`, or check that
  a disc is inserted.
- **`Tried and failed to read the volume label`**: the drive did not become ready
  in 30 seconds; wait for the disc to spin up and retry.
- **`Error Reading a block` / `Error cracking CSS`**: the disc is scratched,
  dirty or encrypted and the decryption library is missing. Clean the disc, or
  try another drive.
- **No suggested name in the prompt**: install `libterm-readline-gnu-perl`.
- **Not enough space**: point `--temp` and `--out` at a disk with about 8 GB
  free each (dual-layer discs need the most).

## Limitations

- Linux only, and only DVD-Video discs (not data discs, Blu-ray or audio CDs).
- It waits five seconds before starting, and stops on the first read error rather
  than skipping bad sectors.
- It cannot resume an interrupted rip.
- Names are not deduplicated: an existing ISO with the same name is replaced.

## Development

```bash
bash tests/test_dvd2iso.sh      # this tool's tests (~15 seconds, needs make_dvd's tools)
tests/run_tests.sh              # every tool's tests (from the repository root)
```

## License

MIT, see the repository [LICENSE](../LICENSE).
