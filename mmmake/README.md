# mmmake

**Build and install software from a source archive or source folder with one command, whatever build system it uses.**

Every source project has its own incantation: `./configure && make && make
install`, `cmake . && make`, `perl Makefile.PL`, `phpize`... `mmmake` looks at
what is in the folder, picks the right sequence, and runs it, stopping at the
first step that fails.

```console
$ mmmake hello-1.0.tar.gz --prefix=$HOME/.local

CONFIGURE:

        ARGS: --prefix=/home/you/.local ...

MAKE:
...
MAKE INSTALL:
...
```

## Why use it

- **Stop thinking about build systems.** Point it at a tarball or a folder
  and it recognises `configure`, `CMakeLists.txt`, plain `Makefile`s, Perl
  `Makefile.PL`, PHP extension `config.m4`, `Imakefile`, and legacy `do-conf`
  projects.
- **Archive to installed program in one step.** It unpacks `.tar`, `.tar.gz`,
  `.tar.bz2`, `.gz`, `.bz2` and `.zip` archives and builds inside the folder
  they create.
- **Passes your options through.** Anything on the command line that is not an
  archive is handed to the build (`--prefix=...` to `configure`,
  `-DCMAKE_INSTALL_PREFIX=...` to `cmake`, `PREFIX=...` to `make`).
- **Stops on failure.** A failed configure, compile or install ends the run
  and names the step that failed. For `configure`, `do-conf`, `config.m4`,
  CMake and plain `Makefile` projects the exit status is also non-zero.
- **A building block.** [`plonk`](../plonk/README.md) uses it to build source
  archives it installs.

## Quick start

```bash
mmmake project-1.2.tar.gz                       # unpack, configure, make, make install
mmmake project-1.2.tar.gz --prefix=$HOME/.local # install somewhere you own
cd project-1.2 && mmmake PREFIX=$HOME/.local    # build the current folder
```

## Usage

```text
mmmake [archive ...] [build arguments ...]
```

There are no flags of its own. Every argument that is an existing file is
treated as an archive; every other argument is collected and passed on to the
build. With no archive, the project in the **current directory** is built.

| Detected in the folder | What runs |
| --- | --- |
| `do-conf` (executable) | `./do-conf ARGS`, then `qmake` if `config.mak` appears, then `make`, `make install` |
| `configure` | `./configure ARGS`, then `qmake` if `config.mak` appears, then `make`, `make install` |
| `config.m4` | `phpize`, `./configure ARGS`, `make`, `make install` |
| `Imakefile` | `xmkmf`, `make`, `make install` |
| `Makefile.PL` | `perl Makefile.PL`, `make`, `make test`, `make install` |
| `CMakeLists.txt` | `cmake . ARGS`, `make`, `make install` |
| `Makefile` / `makefile` | `make ARGS`, `make install ARGS` |
| `vmlinux`, or `kernel` and `arch` | Linux kernel build and install (see Limitations) |
| none of these | prints `UNKNOWN make type` |

The first match wins, checked roughly in the order shown, so a project with a `configure` script is
built that way even if it also has a `Makefile`.

## How it behaves

- **Archives** are unpacked into the current directory and built in the folder
  named after the archive (`hello-1.0.tar.gz` builds in `hello-1.0/`). The
  archive must unpack into a folder with that name.
- **Installing needs permission.** `make install` runs without `sudo`. To
  install system-wide run `mmmake` as root; to install without root, choose a
  prefix you own (`--prefix=$HOME/.local`, `PREFIX=...`).
- **Exit status** is non-zero when a step fails in the `configure`, `do-conf`,
  `config.m4`, CMake and plain `Makefile` flows. The `Makefile.PL`, `Imakefile`
  and kernel flows stop at the failing step but still exit 0.

## Installation

`mmmake` is a single Perl script using only core Perl modules. It needs `perl`
and the `file` command, plus the tools of whichever build systems you use.

| Tool | Needed for |
| --- | --- |
| `perl`, `file` | always |
| `tar`, `gzip`, `bzip2`, `unzip` | unpacking archives |
| `make` and a compiler | almost everything |
| `cmake` | `CMakeLists.txt` projects |
| `qmake` | projects whose configure produces `config.mak` |
| `phpize` | PHP extensions |
| `xmkmf` | `Imakefile` projects |

> **Tested on:** Linux Mint 22.3 (Ubuntu 24.04 base), Perl 5.38, GNU Make 4.3,
> CMake 3.28. Configure-script, plain Makefile and CMake builds were run there.
> `qmake`, `phpize`, `xmkmf`, `Makefile.PL` and kernel builds were **not**
> exercised. Everything for other systems is **untested**; search your package
> manager if a name differs on your release.

### Debian, Ubuntu, Linux Mint, Pop!_OS (tested)

```bash
sudo apt update
sudo apt install perl file tar gzip bzip2 unzip build-essential
# Optional, per build system
sudo apt install cmake qt5-qmake php-dev imake
```

### Fedora, RHEL, Rocky, AlmaLinux (untested)

```bash
sudo dnf install perl file tar gzip bzip2 unzip make gcc gcc-c++
sudo dnf install cmake qt5-qtbase-devel php-devel imake     # optional
```

### Arch Linux, Manjaro, EndeavourOS (untested)

```bash
sudo pacman -S perl file tar gzip bzip2 unzip base-devel
sudo pacman -S cmake qt5-base php imake                     # optional
```

### openSUSE (untested)

```bash
sudo zypper install perl file tar gzip bzip2 unzip make gcc gcc-c++
sudo zypper install cmake php-devel imake                   # optional
```

### macOS (untested)

```bash
xcode-select --install          # compiler and make
brew install cmake              # optional
```

macOS provides `perl`, `file`, `tar`, `gzip`, `bzip2` and `unzip`.

### Windows (untested)

Use **WSL 2** (`wsl --install -d Ubuntu` in an administrator PowerShell) and
follow the Debian/Ubuntu instructions inside it. Native Windows is not
supported.

### Verify the installation

```bash
for t in perl file make; do
  command -v "$t" >/dev/null && echo "ok      $t" || echo "MISSING $t"
done
mkdir /tmp/mm-check && cd /tmp/mm-check
printf 'all:\n\techo built\ninstall:\n\techo installed\n' > Makefile
mmmake        # prints MAKE: built, MAKE INSTALL: installed
```

### Putting `mmmake` on your PATH

The repository keeps the script in `mmmake/` and an extensionless command link
in `bin/`. Add that directory to your `PATH`:

```bash
export PATH="/path/to/utils/bin:$PATH"     # add to ~/.bashrc or ~/.zshrc
```

## Troubleshooting

- **`UNKNOWN make type`**: none of the build files above were found. Check you
  are in the project's top folder.
- **`make install error`** when installing system-wide: run as root, or pick a
  prefix you own.
- **Archive names containing spaces** are not supported (the name is passed to
  the shell unquoted).

## Limitations

- Kernel source trees (`vmlinux`, or `kernel` plus `arch`) trigger
  `make dep`, `clean`, `bzImage`, `modules`, `modules_install` and `install`.
  This is legacy behaviour; do not point `mmmake` at a kernel tree unless that
  is what you intend, and only as root.
- `autogen.sh` projects are recognised but not built correctly (the script is
  run with `perl`). Run `./autogen.sh` yourself first so a `configure` script
  exists, then use `mmmake`.
- No uninstall, no dependency installation, no build directory outside the
  source tree.
- `.rar`, `.7z` and `.tar.xz` archives are not unpacked; use
  [`tgz`](../tgz/README.md) first, then `mmmake` inside the folder.

## Development

```bash
bash tests/test_mmmake.sh       # this tool's tests
tests/run_tests.sh              # every tool's tests (from the repository root)
```

## License

MIT, see the repository [LICENSE](../LICENSE).
