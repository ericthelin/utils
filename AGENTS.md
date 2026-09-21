# AGENTS.md

This file provides guidance to AI coding agents (Claude Code, GitHub Copilot,
Codex, OpenCode, Google Antigravity, and others) and human contributors when
working in the `utils` repository. It is the single source of truth;
platform-specific files (`CLAUDE.md`, `GEMINI.md`,
`.github/copilot-instructions.md`) are symlinks to this file so every tool
reads the same guidance.

`utils` is a git submodule of the private `tools` repository (at `tools/utils`).
The parent repository's `AGENTS.md` points here, so these rules apply whether
your working directory is `tools/` or `tools/utils/`. Rules in the parent
`AGENTS.md` (commit style, no AI attribution, testing policy) also apply.

## Purpose

`utils` holds small standalone command-line tools that are polished enough to
share publicly. Every tool must be understandable and installable by someone
who has never heard of it, which is why documentation is part of the tool and
not an afterthought.

## Repository Layout (MUST follow for every tool)

Each tool gets its own directory named after the tool, containing everything
for it. Commands are exposed, without file extensions, as symlinks in `bin/`.

```text
utils/
├── README.md              index of all tools (see below)
├── .gitignore             ignores __pycache__/ and *.pyc
├── AGENTS.md              this file
├── CLAUDE.md              symlink -> AGENTS.md
├── GEMINI.md              symlink -> AGENTS.md
├── .github/copilot-instructions.md   symlink -> ../AGENTS.md
├── bin/
│   └── <command>          symlink -> ../<tool>/<implementation>   (one per command)
├── <tool>/
│   ├── README.md          documentation for the tool (required)
│   ├── <implementation>   the executable (chmod +x), e.g. make_dvd.py or plonk
│   └── tests/
│       └── test_<tool>.py   (or test_*.sh) automated tests
└── tests/run_tests.sh     discovers and runs every <tool>/tests/test_*
```

- **Tool directory name** is the tool's name in `snake_case` (e.g. `make_dvd`).
- **Commands have no file extension.** Users type `make_dvd`, `to_mp3`, `tgz`,
  never `make_dvd.py`. The implementation file inside the tool directory may
  keep an extension (`make_dvd.py`, `tgz.pl`) so editors and tests recognise it;
  its shebang decides the interpreter. The `bin/` symlink drops the extension.
- **`bin/` is what goes on `PATH`.** Because the commands live in `bin/` and not
  the repository root, a command can share its name with its tool directory
  (`bin/plonk` and `plonk/`) without a clash.
- **Symlinks are relative** (`ln -s ../make_dvd/make_dvd.py bin/make_dvd`) so the
  repository works wherever it is cloned. Never create absolute symlinks.
- A tool with several commands gets one `bin/` symlink per command.
- Put the implementation, its documentation and its tests inside the tool
  directory. Do not scatter tool files across the repository root.
- Anything a tool needs at run time (data files, helper modules) lives in the
  tool directory too.
- **Tools that call other tools** find them as `<repo>/bin/<command>` relative to
  their own real location (falling back to `PATH`), never by absolute paths.
- **Never put secrets, keys, tokens or personal data in this repository.** It is
  public. Read them from a config file under `~/.config/<tool>/` (or an
  environment variable), document the file's format in the tool's README, and
  ship none.
- Older scripts (currently `proxmox/`) predate this layout. Migrate them to it
  when you next change them; do not start new tools in the old style.

## Tool README Requirements (MUST)

`<tool>/README.md` is a project-style README written for a reader who knows
nothing about the tool. It is shareable on its own, so keep links relative to
the tool directory and never assume the reader has read anything else. It MUST
contain, in roughly this order:

1. **Title and one-line tagline** stating what the tool does.
2. **A short example** showing typical input and output.
3. **Why use it**: the value of the tool written as marketing content. Lead with
   the problem it solves and the benefit to the user, in plain and specific
   language. Concrete beats vague; claim only what the tool really does.
4. **Quick start**: the shortest path from installed to useful.
5. **Usage**: every option and argument in a table, plus realistic examples.
6. **How it behaves**: defaults, limits, output locations and other facts a
   user needs to predict what will happen.
7. **Installation**: every dependency, with what it is used for and whether it
   is required or optional, then detailed install steps for **all platforms**
   the tool could plausibly run on: Debian/Ubuntu, Fedora/RHEL, Arch, openSUSE,
   macOS (Homebrew), and Windows (WSL 2 or native), plus containers. Give the
   exact package names and commands, note distribution quirks (repositories to
   enable, packages with a different name, compatibility symlinks), and include
   a **Verify** step that proves the install worked.
8. **Troubleshooting** for the failures a real user will hit.
9. **Limitations**: what the tool deliberately does not do.
10. **Development** notes (how to run the tests) and **License**.

Honesty rules for the installation section:

- State the exact platform and versions the author actually tested on.
- Mark every other platform's instructions as untested unless you ran them.
  Never present unverified package names or commands as verified fact.
- If a platform cannot run the tool, say so and give the closest workable path.

## Top-Level README (MUST)

`README.md` at the repository root is the index. When you add, rename or remove
a tool, update it in the same commit:

- Add one row per tool to the **Tools** table: a link to `<tool>/README.md`
  and a one-sentence description.
- Keep the layout and usage sections accurate.

## Keeping Documentation Current (MUST)

Change the tool and its README together, in the same commit. If you add,
remove or change an option, default, dependency, or behavior, update the usage
table, the "how it behaves" text, the dependency list and the examples. A
tool whose README disagrees with its `--help` is broken.

## Adding a New Tool (checklist)

1. Create `<tool>/` with the implementation, `chmod +x` it.
2. Create the relative, extensionless symlink in `bin/`.
3. Add `<tool>/tests/test_<tool>.py` (or `.sh`) covering the meaningful logic
   (parsing, calculation, filtering, command construction). Run
   `tests/run_tests.sh`.
4. Write `<tool>/README.md` per the requirements above.
5. Add the tool to the root `README.md` table.
6. Commit in this repository, then update the submodule pointer in the parent
   `tools` repository (see below).

## Development Practices

- Follow the existing style of the tool you are editing; keep code simple,
  readable, and free of trailing whitespace and lint warnings.
- Prefer small, composable, testable functions. Separate pure logic (easy to
  test) from code that runs external programs.
- Comments only for critical caveats.
- Check for required external programs at startup and fail with a clear
  message naming the missing package.
- Verify changes by running the tests and, where possible, the tool itself.

## Git

- Conventional commits: `type(scope): description`, where scope is the tool
  directory name (`feat(make_dvd): ...`, `docs(make_dvd): ...`).
- Never mention Claude, Anthropic or any AI tool in commit messages.
- Commits must leave the tests passing and the docs accurate.
- Fix the last commit with `git commit --amend`.
- This repository is a submodule. After committing here, the parent repository
  shows `utils` as modified; commit that pointer update in the parent (and
  push this repository first, so the pointer refers to a published commit).

## Testing

- `tests/run_tests.sh` runs every `<tool>/tests/test_*.py` (unittest) and
  `test_*.sh`. The parent repository's test runner also runs it.
- A failing test blocks committing. Fix failures immediately, including ones
  that were already failing when you arrived.
