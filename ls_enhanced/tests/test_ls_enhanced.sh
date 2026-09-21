#!/usr/bin/env bash
# Tests for ls-enhanced, using stand-ins for eza so the results do not depend on
# what happens to be installed.

unset CDPATH
BIN="$(cd "$(dirname "$0")/../../bin" && pwd)"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
fails=0

check() {
  if [[ "$2" == ok ]]; then echo "ok   - $1"; else echo "FAIL - $1"; fails=$((fails + 1)); fi
}

mkdir "$work/dir" "$work/stubs"
echo a > "$work/dir/alpha.txt"
echo b > "$work/dir/beta.txt"

# Stand-in eza: succeeds silently, and reports a disabled git feature when asked to probe it.
cat > "$work/stubs/eza" <<'STUB'
#!/bin/sh
case "$*" in
  *"--git --color=auto ."*) [ -n "$STUB_NO_GIT" ] && echo "The 'git' feature is disabled" >&2 ;;
esac
[ -n "$STUB_FAIL" ] && [ "${1#--git}" = "$1" ] && exit 3
echo "eza output"
exit 0
STUB
chmod +x "$work/stubs/eza"

run_ls() { LS_ENHANCED_TOOL=ls "$BIN/ls-enhanced" "$@" 2>&1; }
run_eza() { PATH="$work/stubs:$PATH" LS_ENHANCED_TOOL=eza "$BIN/ls-enhanced" "$@" 2>&1; }

out="$(run_ls -v -l "$work/dir")"
[[ "$out" == *"Using command: /bin/ls -l --all"* ]] \
  && check "plain ls: -l maps to a long listing of all files" ok || check "plain ls: -l maps to a long listing of all files" no

for flag in -s -t; do
  out="$(LS_ENHANCED_TOOL=ls "$BIN/ls-enhanced" "$flag" "$work/dir" 2>&1)"
  first="$(head -1 <<<"$out")"
  [[ "$first" == total* && "$out" == *alpha.txt* ]] \
    && check "plain ls: $flag gives a long listing (not a comma list)" ok || check "plain ls: $flag gives a long listing (not a comma list): $first" no
done

out="$(run_ls -v -la "$work/dir")"
[[ "$out" == *"-la "* && "$out" != *"--all"* ]] \
  && check "ordinary ls flags pass through unchanged" ok || check "ordinary ls flags pass through unchanged" no

out="$(cd "$work/dir" && run_ls -v)"
[[ "$out" == *"/bin/ls "*"-F"* ]] \
  && check "no arguments gives the default classified listing" ok || check "no arguments gives the default classified listing" no

out="$(run_ls -v "$work/dir")"
[[ "$out" == *"-F"* && "$out" == *"$work/dir"* ]] \
  && check "a path with no flags also gets the default listing" ok || check "a path with no flags also gets the default listing" no

out="$(run_eza -v "$work/dir")"
[[ "$out" == *"--icons"* && "$out" == *"--color-scale"* ]] \
  && check "eza: a path with no flags also gets icons and colour" ok || check "eza: a path with no flags also gets icons and colour" no

out="$(run_eza -v -l "$work/dir")"
[[ "$out" == *"--icons"* && "$out" == *"--git "* && "$out" == *"--group-directories-first"* ]] \
  && check "eza: -l adds icons, git status and directories first" ok || check "eza: -l adds icons, git status and directories first" no

out="$(run_eza -v -t "$work/dir")"
[[ "$out" == *"-snew"* && "$out" == *"--color-scale"* && "$out" != *"--color=auto"* ]] \
  && check "eza: --color=auto is replaced by --color-scale" ok || check "eza: --color=auto is replaced by --color-scale" no

out="$(run_eza -v -lT "$work/dir")"
[[ "$out" == *"--level=4"* ]] \
  && check "eza: -lT gives a deeper tree" ok || check "eza: -lT gives a deeper tree" no

out="$(STUB_NO_GIT=1 run_eza -v -l "$work/dir")"
[[ "$out" == *"Using command"* && "$out" != *"--git"* ]] \
  && check "the git flag is skipped when eza was built without it" ok || check "the git flag is skipped when eza was built without it" no

out="$(STUB_FAIL=1 run_eza -l "$work/dir")"
[[ "$out" == *"falling back to ls"* && "$out" == *alpha.txt* ]] \
  && check "a failing eza falls back to plain ls" ok || check "a failing eza falls back to plain ls" no

out="$(LS_ENHANCED_VERBOSE=2 run_eza -l "$work/dir")"
[[ "$out" == *"Detected eza:"* && "$out" == *"Selected tool: eza"* ]] \
  && check "LS_ENHANCED_VERBOSE=2 shows tool detection" ok || check "LS_ENHANCED_VERBOSE=2 shows tool detection" no

out="$(run_eza -VV -l "$work/dir")"
[[ "$out" == *"Selected tool"* ]] \
  && check "-VV raises the verbosity" ok || check "-VV raises the verbosity" no

out="$(LS_ENHANCED_TOOL=bogus "$BIN/ls-enhanced" 2>&1)"; code=$?
[[ $code -eq 1 && "$out" == *"Unsupported LS_ENHANCED_TOOL"* ]] \
  && check "an unknown LS_ENHANCED_TOOL is rejected" ok || check "an unknown LS_ENHANCED_TOOL is rejected" no

out="$(LS_ENHANCED_VERBOSE=lots LS_ENHANCED_TOOL=ls "$BIN/ls-enhanced" "$work/dir" 2>&1)"
[[ "$out" == *"must be a non-negative integer"* ]] \
  && check "a bad LS_ENHANCED_VERBOSE is reported" ok || check "a bad LS_ENHANCED_VERBOSE is reported" no

exit $((fails > 0))
