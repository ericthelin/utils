# utils

A growing collection of small, practical command-line tools. Each tool lives in
its own directory with its own documentation, so you can pick the ones you
need and ignore the rest.

## Tools

| Tool | What it does |
| --- | --- |
| [hist_search](hist_search/README.md) | A better Ctrl-R: fuzzy or regex search through your shell history, with no dependencies. |
| [make_dvd](make_dvd/README.md) | Convert one or more video files into a DVD-Video ISO that fits a standard disc, with an auto-playing menu, chapters and optional burning. |
| [mmmake](mmmake/README.md) | Build and install software from a source archive or folder, whatever build system it uses. |
| [plonk](plonk/README.md) | Install a downloaded Linux app (AppImage, `.deb`, Flatpak, source tarball or installer) with one command. |
| [tgz](tgz/README.md) | Extract any archive into a tidy, correctly named folder without spilling files into the current directory. |
| [to_h264](to_h264/README.md) | Batch-convert videos to H.264/AAC with HandBrake, optionally spread across machines. |
| [to_m4b](to_m4b/README.md) | Combine a folder of MP3 or Opus files into one chaptered audiobook (`.m4b`). |
| [to_mp3](to_mp3/README.md) | Convert M4A, M4B, OGG, FLAC, WAV, WMA and Audible files to MP3, keeping the tags. |

## Using a tool

Every tool has an extensionless command link in `bin/`, so putting that
directory on your `PATH` makes all of them available:

```bash
git clone git@github.com:ericthelin/utils.git
export PATH="$PWD/utils/bin:$PATH"      # add to your shell profile to keep it
make_dvd --help
```

Each tool's README lists its dependencies and how to install them on Linux,
macOS and Windows.

## Repository layout

```text
utils/
├── README.md            this index
├── AGENTS.md            rules for contributors and AI coding agents
├── bin/                 one extensionless symlink per command (put this on PATH)
├── <tool>/
│   ├── README.md        full documentation for the tool
│   ├── <tool>.<ext>     the implementation
│   └── tests/           the tool's automated tests
└── tests/run_tests.sh   runs every tool's tests
```

Run all the tests with `tests/run_tests.sh`.

Adding a tool? See [AGENTS.md](AGENTS.md) for the conventions.

## License

MIT, see [LICENSE](LICENSE).
