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
ln -s dir "$work/link"

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

out="$(run_ls --ls-enhanced-verbose --ls-enhanced-view=long "$work/dir")"
[[ "$out" == *"Using command: /bin/ls -l --all"* ]] \
  && check "plain ls: long view maps to a long listing of all files" ok || check "plain ls: long view maps to a long listing of all files" no

for backend in ls eza exa; do
  if [[ "$backend" != ls ]] && ! command -v "$backend" >/dev/null 2>&1; then
    continue
  fi

  out="$(cd "$work/dir" && LS_ENHANCED_TOOL="$backend" "$BIN/ls-enhanced" --ls-enhanced-view=full 2>&1)"
  [[ "$out" == *alpha.txt* && "$out" == *beta.txt* ]] \
    && check "$backend: full view lists the current directory" ok || check "$backend: full view lists the current directory" no

  out="$(LS_ENHANCED_TOOL="$backend" "$BIN/ls-enhanced" --ls-enhanced-view=full "$work/dir" 2>&1)"
  [[ "$out" == *alpha.txt* && "$out" == *beta.txt* ]] \
    && check "$backend: full view lists a named directory's contents" ok || check "$backend: full view lists a named directory's contents" no

  out="$(cd "$work/dir" && LS_ENHANCED_TOOL="$backend" "$BIN/ls-enhanced" -d 2>&1)"
  direct="$(cd "$work/dir" && "$backend" -d 2>&1)"
  [[ "$out" == "$direct" ]] \
    && check "$backend: -d alone passes through unchanged" ok || check "$backend: -d alone passes through unchanged" no

  out="$(LS_ENHANCED_TOOL="$backend" "$BIN/ls-enhanced" -d "$work/dir" 2>&1)"
  direct="$("$backend" -d "$work/dir" 2>&1)"
  [[ "$out" == "$direct" ]] \
    && check "$backend: -d path passes through unchanged" ok || check "$backend: -d path passes through unchanged" no

  out="$(LS_ENHANCED_TOOL="$backend" "$BIN/ls-enhanced" -d "$work/link" 2>&1)"
  direct="$("$backend" -d "$work/link" 2>&1)"
  [[ "$out" == "$direct" ]] \
    && check "$backend: -d symlink passes through unchanged" ok || check "$backend: -d symlink passes through unchanged" no

  out="$(LS_ENHANCED_TOOL="$backend" "$BIN/ls-enhanced" --ls-enhanced-view=full -d "$work/link" 2>&1)"
  [[ "$out" == *"link -> dir"* && "$out" != *alpha.txt* && "$out" != *beta.txt* ]] \
    && check "$backend: -d overrides the full-list alias view" ok || check "$backend: -d overrides the full-list alias view" no

  out="$(LS_ENHANCED_TOOL="$backend" "$BIN/ls-enhanced" --full-list -d "$work/link" 2>&1)"
  [[ "$out" == *"link -> dir"* && "$out" != *alpha.txt* && "$out" != *beta.txt* ]] \
    && check "$backend: loaded --full-list alias still supports -d" ok || check "$backend: loaded --full-list alias still supports -d" no
done

out="$(run_eza --ls-enhanced-verbose -d "$work/link")"
[[ "$out" == *" -d "* && "$out" != *" -ld "* ]] \
  && check "eza: -d is passed without rewriting" ok || check "eza: -d is passed without rewriting" no

out="$(cd "$work/dir" && run_eza --ls-enhanced-verbose --ls-enhanced-view=full)"
[[ "$out" == *"-lagmF"* && "$out" == *"-snew"* ]] \
  && check "eza: full view keeps the original directory listing" ok || check "eza: full view keeps the original directory listing" no

out="$(STUB_FAIL=1 run_eza -d "$work/link")"
[[ "$out" == *"falling back to ls"* && "$out" == *"$(/bin/ls -d "$work/link")"* ]] \
  && check "a failing eza preserves -d in plain ls" ok || check "a failing eza preserves -d in plain ls" no

for view in long extra-long tree-2 tree-2-long tree-4 size time one-column; do
  for backend in ls eza; do
    if [[ "$backend" == ls ]]; then
      view_out="$(run_ls --ls-enhanced-verbose "--ls-enhanced-view=$view" "$work/dir")"
    else
      view_out="$(run_eza --ls-enhanced-verbose "--ls-enhanced-view=$view" "$work/dir")"
    fi
    [[ "$view_out" == *"Using command:"* && "$view_out" != *"--ls-enhanced-view"* ]] \
      && check "$backend: $view is consumed by the wrapper" ok || check "$backend: $view is consumed by the wrapper" no
  done
done

out="$(run_eza --ls-enhanced-verbose "$work/dir")"
default_out="$(run_eza --ls-enhanced-verbose --ls-enhanced-view=default "$work/dir")"
[[ "$out" == "$default_out" ]] \
  && check "eza: default alias view keeps the unflagged listing" ok || check "eza: default alias view keeps the unflagged listing" no

out="$(LS_ENHANCED_TOOL=ls "$BIN/ls-enhanced" --help)"
[[ "$out" == *"Views for shell aliases"* && "$out" == *"--ls-enhanced-view=full"* ]] \
  && check "direct --help shows ls-enhanced help" ok || check "direct --help shows ls-enhanced help" no

out="$(run_ls --ls-enhanced-view=default --help)"
expected="$(/bin/ls --help)"
[[ "$out" == "$expected" ]] \
  && check "default alias --help shows plain ls help" ok || check "default alias --help shows plain ls help" no

out="$(run_eza --ls-enhanced-view=full --help)"
[[ "$out" == "eza output" ]] \
  && check "full alias --help reaches eza" ok || check "full alias --help reaches eza" no

out="$(run_eza --full-list "$work/dir")"
[[ "$out" == "eza output" ]] \
  && check "an already-loaded --full-list alias still works" ok || check "an already-loaded --full-list alias still works" no

for flag in -l -s -t -v; do
  out="$(run_ls --ls-enhanced-verbose "$flag" "$work/dir")"
  [[ "$out" == *"Using command: /bin/ls $flag "* && "$out" != *"--ls-enhanced-view"* ]] \
    && check "plain ls: explicit $flag passes through unchanged" ok || check "plain ls: explicit $flag passes through unchanged" no
done

out="$(run_ls --ls-enhanced-verbose -la "$work/dir")"
[[ "$out" == *"-la "* && "$out" != *"--all"* ]] \
  && check "ordinary ls flags pass through unchanged" ok || check "ordinary ls flags pass through unchanged" no

out="$(cd "$work/dir" && run_ls --ls-enhanced-verbose)"
[[ "$out" == *"/bin/ls "*"-F"* ]] \
  && check "no arguments gives the default classified listing" ok || check "no arguments gives the default classified listing" no

out="$(run_ls --ls-enhanced-verbose "$work/dir")"
[[ "$out" == *"-F"* && "$out" == *"$work/dir"* ]] \
  && check "a path with no flags also gets the default listing" ok || check "a path with no flags also gets the default listing" no

out="$(run_eza --ls-enhanced-verbose "$work/dir")"
[[ "$out" == *"--icons"* && "$out" == *"--color-scale"* ]] \
  && check "eza: a path with no flags also gets icons and colour" ok || check "eza: a path with no flags also gets icons and colour" no

out="$(run_eza --ls-enhanced-verbose --ls-enhanced-view=long "$work/dir")"
[[ "$out" == *"--icons"* && "$out" == *"--git "* && "$out" == *"--group-directories-first"* ]] \
  && check "eza: long view adds icons, git status and directories first" ok || check "eza: long view adds icons, git status and directories first" no

out="$(run_eza --ls-enhanced-verbose --ls-enhanced-view=time "$work/dir")"
[[ "$out" == *"-snew"* && "$out" == *"--color-scale=size"* && "$out" != *"--color=auto"* ]] \
  && check "eza: --color=auto is replaced by --color-scale=size" ok || check "eza: --color=auto is replaced by --color-scale=size" no

out="$(run_eza --ls-enhanced-verbose --ls-enhanced-view=tree-4 "$work/dir")"
[[ "$out" == *"--level=4"* ]] \
  && check "eza: tree-4 view gives a deeper tree" ok || check "eza: tree-4 view gives a deeper tree" no

out="$(STUB_NO_GIT=1 run_eza --ls-enhanced-verbose --ls-enhanced-view=long "$work/dir")"
[[ "$out" == *"Using command"* && "$out" != *"--git"* ]] \
  && check "the git flag is skipped when eza was built without it" ok || check "the git flag is skipped when eza was built without it" no

out="$(STUB_FAIL=1 run_eza --ls-enhanced-view=long "$work/dir")"
[[ "$out" == *"falling back to ls"* && "$out" == *alpha.txt* ]] \
  && check "a failing eza falls back to plain ls" ok || check "a failing eza falls back to plain ls" no

out="$(LS_ENHANCED_VERBOSE=2 run_eza --ls-enhanced-view=long "$work/dir")"
[[ "$out" == *"Detected eza:"* && "$out" == *"Selected tool: eza"* ]] \
  && check "LS_ENHANCED_VERBOSE=2 shows tool detection" ok || check "LS_ENHANCED_VERBOSE=2 shows tool detection" no

out="$(run_eza --ls-enhanced-verbose --ls-enhanced-verbose --ls-enhanced-view=long "$work/dir")"
[[ "$out" == *"Selected tool"* ]] \
  && check "repeated wrapper verbosity flags raise the verbosity" ok || check "repeated wrapper verbosity flags raise the verbosity" no

out="$(LS_ENHANCED_TOOL=bogus "$BIN/ls-enhanced" 2>&1)"; code=$?
[[ $code -eq 1 && "$out" == *"Unsupported LS_ENHANCED_TOOL"* ]] \
  && check "an unknown LS_ENHANCED_TOOL is rejected" ok || check "an unknown LS_ENHANCED_TOOL is rejected" no

out="$(LS_ENHANCED_VERBOSE=lots LS_ENHANCED_TOOL=ls "$BIN/ls-enhanced" "$work/dir" 2>&1)"
[[ "$out" == *"must be a non-negative integer"* ]] \
  && check "a bad LS_ENHANCED_VERBOSE is reported" ok || check "a bad LS_ENHANCED_VERBOSE is reported" no

exit $((fails > 0))
