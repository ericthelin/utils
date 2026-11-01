# git-go

**Switch to a branch or create it in one command, and keep new branch names tidy: `git go NAME`.**

```console
$ git go login-fix
Branch 'login-fix' does not start with a standard prefix.
  1) rc/login-fix
  2) hotfix/login-fix
  3) feature/login-fix
  4) refactor/login-fix
  5) chore/login-fix
  6) spike/login-fix
  7) bugfix/login-fix
Choose 1-7 to add a prefix, or press Enter to keep 'login-fix': 3
Switched to a new branch 'feature/login-fix'

  ★ CREATED NEW BRANCH: feature/login-fix
```

## Why use it

- **One command for both cases.** An existing branch is checked out
  (`✔ REUSED EXISTING BRANCH`); a missing one is created (`★ CREATED NEW BRANCH`).
- **Consistent branch names.** Before creating a branch that does not start with
  `rc/`, `hotfix/`, `feature/`, `refactor/`, `chore/`, `spike/` or `bugfix/`, it offers to
  add one. Press Enter to keep the name exactly as typed.
- **History that matches reality.** If you add a prefix, the `git go NAME` entry
  in your shell history is rewritten to `git go feature/NAME`, so searching the
  history (Ctrl-R, [hist_search](../hist_search/README.md)) finds the branch
  you actually created.

## Quick start

Put `utils/bin` on your `PATH`, then make `git go` use it:

```bash
git config --global alias.go '!git-go'
git go my-branch
```

(Without the alias, `git go` also works because git runs any `git-go` found on
`PATH`.)

## Usage

| Argument | Meaning |
| --- | --- |
| `BRANCH` | Branch to switch to or create. Exactly one is required. |
| `-h`, `--help` | Show usage. |

## How it behaves

1. If the local branch exists, it is checked out. No prompt, no history change.
2. Otherwise, if the name has none of the standard prefixes, a menu is shown on
   the terminal (`/dev/tty`). Without a terminal the name is kept as typed.
3. The branch is created from the current commit with `git checkout -b`.
4. If a prefix was added, the history file (`$HISTFILE`, else `~/.zsh_history`,
   else `~/.bash_history`) is updated: the most recent of its last five entries
   containing `go BRANCH` has the branch replaced. The file is replaced
   atomically and keeps its permissions.

## Installation

| Needs | For |
| --- | --- |
| `git` | everything |
| `python3` (3.6+) | running the script |

Any platform with those two works; `git-go` uses no other packages.

> **Tested on:** macOS with zsh, git and Python 3. Linux, bash history and
> Windows were **not tested**.

**Verify:** `git go --help`.

## Troubleshooting

- **History still shows the old name in the current shell.** The running shell
  keeps its in-memory copy; the file (and so a new shell and `hist_search`) has
  the new name.
- **No prompt appears.** There is no controlling terminal (for example in a
  script), so the name is used unchanged.

## Limitations

- Only local branches are checked for reuse; it never fetches or tracks remotes.
- History rewriting covers the plain-text zsh and bash history formats only.
- It accepts one branch name; there is no start-point argument.

## Development

```bash
python3 tests/test_git_go.py    # this tool's tests
tests/run_tests.sh              # every tool's tests (from the repository root)
```

## License

MIT, see the repository [LICENSE](../LICENSE).
