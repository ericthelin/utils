# git-pr

**Push your branch and open the right GitHub "new pull request" page, in the right Chrome profile, with one command: `git pr`.**

You finish a branch, and then: push it, open GitHub, find the banner, pick the
base branch, and make sure the right account is signed in. `git pr` does all of
that in one step, and remembers the details for each repository.

```console
$ git pr
Pushing branch 'fix-login' to 'origin'...
Push succeeded.
https://github.com/acme/widgets/compare/develop...fix-login
```

Your browser opens on the pull request form, ready for a title and description.

## Safety first

**`git pr` pushes your current branch** (`git push -u <remote> <branch>`) before
opening the page. It does not ask first. If the remote already has exactly your
commit, the push is skipped. It never creates the pull request itself; you
still press the green button.

## Why use it

- **One step from finished branch to PR form.** No copying URLs, no hunting for
  the "Compare & pull request" banner.
- **Picks the right base branch.** It uses `develop` when the target repository
  has one, otherwise the repository's default branch, or a branch you choose
  and it remembers.
- **Works with forks.** If you push to your fork and the pull request belongs on
  the upstream project, it builds the cross-repository compare link for you.
- **Opens the right account.** With work and personal GitHub accounts in
  different Chrome profiles, it finds the profile by the account's email
  address, so you land signed in as the right person.
- **Per-repository memory.** Base branch, target repository and Chrome account
  are stored in the repo's own `git config`, so each project behaves correctly.
- **Falls back gracefully.** No Chrome, or no matching profile? It uses your
  default browser.

## Quick start

Put this repository's `bin/` directory on your `PATH` and git will run the
script as a subcommand:

```bash
git checkout -b my-feature
# ... commit your work ...
git pr                                          # push and open the PR page

git pr --set-profile "me@work.com"              # remember which Chrome account to use
git pr --set-branch develop                     # remember the base branch
git pr --set-repo upstream-org/project          # PRs go to the upstream project
```

## Usage

```text
git pr
git pr --set-profile EMAIL
git pr --set-branch BRANCH
git pr --set-repo OWNER/REPO | URL | REMOTE-NAME
```

| Command | Meaning |
| --- | --- |
| `git pr` | Push the current branch (if needed), then open the compare page. |
| `--set-profile EMAIL` | Remember the Chrome account email for this repository (`pr.chrome-email`). |
| `--set-branch BRANCH` | Remember the base branch for this repository (`pr.target-branch`). |
| `--set-repo TARGET` | Remember the repository pull requests should target (`pr.target-repo`): `owner/repo`, a URL, or the name of a git remote. |

The settings live in the repository's local `.git/config`; change them with
these commands or with `git config` directly.

## How it behaves

1. **Push remote.** `branch.<name>.pushRemote`, then `remote.pushDefault`, then
   the branch's tracking remote, then `origin`.
2. **Push.** The branch is pushed with upstream tracking unless the remote already
   has exactly your commit.
3. **Target repository** (where the PR goes): `pr.target-repo` if set, else the
   `upstream` remote if you have one, else the repository you pushed to.
4. **Base branch:** `pr.target-branch` if set, else `develop` if the target
   repository has that branch, else the target's default branch, else `main`.
5. **URL.** For the same repository:
   `https://github.com/OWNER/REPO/compare/BASE...BRANCH`. For a fork:
   `https://github.com/OWNER/REPO/compare/BASE...FORKOWNER:FORKREPO:BRANCH`.
6. **Browser.** With a Chrome account email (configured, or chosen from a list of
   the accounts found in your Chrome profiles for that run only), the matching
   Chrome profile is opened. Otherwise `xdg-open` (Linux) or `open` (macOS) is
   used.

## Installation

`git-pr` is a single Bash script.

| Needs | For |
| --- | --- |
| `git` | everything |
| `bash` | running the script |
| `python3` | reading Chrome's profile list |
| `xdg-open` (Linux) or `open` (macOS) | opening the default browser |
| Google Chrome (optional) | opening the right profile; Linux uses `google-chrome`, `google-chrome-stable` or `chromium-browser` |

> **Tested on:** Linux Mint 22.3 (Ubuntu 24.04 base) with git 2.43 and Bash 5.2.
> The automated tests use a local bare repository as the remote and stand-ins for
> the browser, and cover pushing, base-branch selection, the settings, fork URLs
> and Chrome profile lookup. Opening a real browser on GitHub and **macOS were
> not tested** by the author, and neither were other Linux distributions.

### Debian, Ubuntu, Linux Mint, Pop!_OS (tested)

```bash
sudo apt update
sudo apt install git python3 xdg-utils
```

### Fedora, RHEL, Rocky, AlmaLinux (untested)

```bash
sudo dnf install git python3 xdg-utils
```

### Arch Linux, Manjaro, EndeavourOS (untested)

```bash
sudo pacman -S git python xdg-utils
```

### openSUSE (untested)

```bash
sudo zypper install git python3 xdg-utils
```

### macOS (untested)

```bash
xcode-select --install       # git and python3
```

`open` is built in. Chrome profiles are read from
`~/Library/Application Support/Google/Chrome`.

### Windows (untested)

Native Windows is not supported. Use **WSL 2** (`wsl --install -d Ubuntu`) and
follow the Debian/Ubuntu steps; the default-browser fallback needs `wslu`
(`sudo apt install wslu`) so `xdg-open` can reach your Windows browser.

### Verify the installation

```bash
git pr --set-branch main      # inside any git repository: prints the confirmation
git config pr.target-branch   # prints: main
git config --unset pr.target-branch
```

### Putting `git-pr` on your PATH

The repository keeps the script in `git_pr/` and an extensionless command link in
`bin/`. With that directory on your `PATH`, `git pr` just works:

```bash
export PATH="/path/to/utils/bin:$PATH"     # add to ~/.bashrc or ~/.zshrc
```

Or define an alias instead: `git config --global alias.pr '!/path/to/utils/bin/git-pr'`.

## Troubleshooting

- **`Push failed - aborting`**: fix the push (authentication, protected branch,
  no remote) and run it again.
- **It opens the wrong base branch**: run `git pr --set-branch NAME` once.
- **The PR should go to the upstream project, not my fork**: run
  `git pr --set-repo OWNER/REPO` (or add a remote named `upstream`).
- **`no Chrome profile found for ...`**: the email is not a signed-in account in
  any Chrome profile; check with `git config pr.chrome-email`.
- **Nothing opens**: install `xdg-utils` (Linux).

## Limitations

- GitHub.com only: the links are built for `github.com`, so GitHub Enterprise
  and other hosts are not supported.
- It opens the page; it does not create the pull request (for that, see the
  GitHub CLI: `gh pr create`).
- Chrome profile lookup covers Google Chrome on Linux and macOS, not Chromium,
  Brave or Edge profiles.
- It pushes without asking.

## Development

```bash
bash tests/test_git_pr.sh       # this tool's tests
tests/run_tests.sh              # every tool's tests (from the repository root)
```

## License

MIT, see the repository [LICENSE](../LICENSE).
