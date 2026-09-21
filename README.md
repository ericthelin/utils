# utils

A growing collection of small, practical command-line tools. Each tool lives in
its own directory with its own documentation, so you can pick the ones you
need and ignore the rest.

## Tools

| Tool | What it does |
| --- | --- |
| [make_dvd](make_dvd/README.md) | Convert one or more video files into a DVD-Video ISO that fits a standard disc, with an auto-playing menu, chapters and optional burning. |

## Using a tool

Every tool has a symlink to its command in the repository root, so putting this
directory on your `PATH` makes all of them available:

```bash
git clone git@github.com:ericthelin/utils.git
export PATH="$PWD/utils:$PATH"      # add to your shell profile to keep it
make_dvd.py --help
```

Each tool's README lists its dependencies and how to install them on Linux,
macOS and Windows.

## Repository layout

```text
utils/
├── README.md            this index
├── AGENTS.md            rules for contributors and AI coding agents
├── <tool>.py            symlink to the tool's command
├── <tool>/
│   ├── README.md        full documentation for the tool
│   ├── <tool>.py        the implementation
│   └── tests/           the tool's automated tests
└── tests/run_tests.sh   runs every tool's tests
```

Run all the tests with `tests/run_tests.sh`.

Adding a tool? See [AGENTS.md](AGENTS.md) for the conventions.

## License

MIT, see [LICENSE](LICENSE).
