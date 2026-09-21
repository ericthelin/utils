#!/usr/bin/env bash
# Tests for git-pr, using a local bare repository as the remote and a stand-in
# for the browser opener, so nothing touches GitHub or a real browser.

unset CDPATH
BIN="$(cd "$(dirname "$0")/../../bin" && pwd)"

command -v git >/dev/null 2>&1 || { echo "skip - git not installed"; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "skip - python3 not installed"; exit 0; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
fails=0

check() {
  if [[ "$2" == ok ]]; then echo "ok   - $1"; else echo "FAIL - $1"; fails=$((fails + 1)); fi
}

mkdir "$work/stubs"
printf '#!/bin/sh\necho "$@" >> "$OPENER_LOG"\n' > "$work/stubs/xdg-open"
cp "$work/stubs/xdg-open" "$work/stubs/open"
chmod +x "$work/stubs/"*

export HOME="$work/home" PATH="$work/stubs:$PATH" OPENER_LOG="$work/opened"
export GIT_CONFIG_GLOBAL="$work/gitconfig" GIT_CONFIG_SYSTEM=/dev/null
export GIT_AUTHOR_NAME=T GIT_AUTHOR_EMAIL=t@example.com GIT_COMMITTER_NAME=T GIT_COMMITTER_EMAIL=t@example.com
mkdir -p "$HOME"
: > "$OPENER_LOG"

git init -q --bare -b main "$work/acme/widgets.git"
git init -q -b main "$work/repo"
cd "$work/repo" || exit 1
git remote add origin "$work/acme/widgets.git"
echo one > file && git add file && git commit -q -m one
git push -q origin main
git checkout -q -b feature-x
echo two >> file && git commit -q -am two

last_url() { tail -1 "$OPENER_LOG"; }

out="$("$BIN/git-pr" 2>&1)"
[[ "$(git --git-dir="$work/acme/widgets.git" rev-parse feature-x 2>/dev/null)" == "$(git rev-parse HEAD)" ]] \
  && check "the branch is pushed to the remote first" ok || check "the branch is pushed to the remote first" no
[[ "$(last_url)" == https://github.com/*/compare/main...feature-x ]] \
  && check "opens the compare page against the remote's default branch" ok || check "opens the compare page against the remote's default branch: $(last_url)" no

out="$("$BIN/git-pr" 2>&1)"
[[ "$out" == *"already up to date"* ]] \
  && check "an up-to-date branch is not pushed again" ok || check "an up-to-date branch is not pushed again" no

git push -q origin main:develop
: > "$OPENER_LOG"
"$BIN/git-pr" >/dev/null 2>&1
[[ "$(last_url)" == */compare/develop...feature-x ]] \
  && check "a develop branch on the remote becomes the base" ok || check "a develop branch on the remote becomes the base: $(last_url)" no

"$BIN/git-pr" --set-branch release >/dev/null 2>&1
[[ "$(git config --get pr.target-branch)" == release ]] \
  && check "--set-branch remembers the base for this repo" ok || check "--set-branch remembers the base for this repo" no
: > "$OPENER_LOG"
"$BIN/git-pr" >/dev/null 2>&1
[[ "$(last_url)" == */compare/release...feature-x ]] \
  && check "the remembered base is used" ok || check "the remembered base is used: $(last_url)" no

"$BIN/git-pr" --set-repo upstream-org/widgets >/dev/null 2>&1
[[ "$(git config --get pr.target-repo)" == upstream-org/widgets ]] \
  && check "--set-repo remembers the target repository" ok || check "--set-repo remembers the target repository" no
: > "$OPENER_LOG"
"$BIN/git-pr" >/dev/null 2>&1
[[ "$(last_url)" == https://github.com/upstream-org/widgets/compare/release...*:feature-x ]] \
  && check "a different target repo gives a fork-style compare URL" ok || check "a different target repo gives a fork-style compare URL: $(last_url)" no

"$BIN/git-pr" --set-profile me@example.com >/dev/null 2>&1
[[ "$(git config --get pr.chrome-email)" == me@example.com ]] \
  && check "--set-profile remembers the Chrome account email" ok || check "--set-profile remembers the Chrome account email" no
: > "$OPENER_LOG"
out="$("$BIN/git-pr" 2>&1)"
[[ "$out" == *"no Chrome profile found for me@example.com"* && -s "$OPENER_LOG" ]] \
  && check "falls back to the default browser when no Chrome profile matches" ok || check "falls back to the default browser when no Chrome profile matches" no

if [[ "$(uname -s)" == Linux ]]; then
  mkdir -p "$HOME/.config/google-chrome/Default" "$HOME/.config/google-chrome/Profile 3"
  echo '{"account_info": [{"email": "other@example.com"}]}' > "$HOME/.config/google-chrome/Default/Preferences"
  echo '{"account_info": [{"email": "me@example.com"}]}' > "$HOME/.config/google-chrome/Profile 3/Preferences"
  printf '#!/bin/sh\necho "$@" >> "$OPENER_LOG"\n' > "$work/stubs/google-chrome"
  chmod +x "$work/stubs/google-chrome"
  : > "$OPENER_LOG"
  "$BIN/git-pr" >/dev/null 2>&1
  sleep 0.3
  grep -q -- '--profile-directory=Profile 3 https://github.com/' "$OPENER_LOG" \
    && check "opens the Chrome profile that belongs to the configured email" ok || check "opens the Chrome profile that belongs to the configured email: $(cat "$OPENER_LOG")" no
else
  echo "skip - Chrome profile lookup test is Linux-only"
fi

cd "$work" && mkdir notrepo && cd notrepo || exit 1
"$BIN/git-pr" >/dev/null 2>&1
[[ $? -ne 0 ]] && check "fails outside a git repository" ok || check "fails outside a git repository" no

exit $((fails > 0))
