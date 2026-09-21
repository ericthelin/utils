#!/usr/bin/env bash
# Tests for tgz: extraction naming, collision handling, and safety on unknown files.

unset CDPATH
BIN="$(cd "$(dirname "$0")/../../bin" && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
fails=0

check() {
  if [[ "$2" == ok ]]; then echo "ok   - $1"; else echo "FAIL - $1"; fails=$((fails + 1)); fi
}

# A PATH holding only what tgz needs, so a locally installed aunpack cannot change the result.
mkdir "$work/path"
for tool in perl tar gzip gunzip bunzip2 unzip file mv which sh bash rmdir; do
  found="$(command -v "$tool")" && ln -s "$found" "$work/path/$tool"
done
run_tgz() { PATH="$work/path" "$BIN/tgz" "$@"; }

cd "$work" || exit 1
mkdir src && cd src || exit 1
mkdir proj && echo hello > proj/a.txt
tar czf ../proj-1.0.tar.gz proj
echo one > a.txt; echo two > b.txt
tar czf ../multi.tgz a.txt b.txt
python3 -c "
import zipfile
with zipfile.ZipFile('../single.zip', 'w') as z:
    z.writestr('only/file.txt', 'zip content')
"
printf '#!/bin/sh\ntouch %s/executed\n' "$work" > ../not_an_archive.bin
chmod +x ../not_an_archive.bin
cd "$work" || exit 1

mkdir out1 && cd out1 || exit 1
run_tgz ../proj-1.0.tar.gz >/dev/null 2>&1
[[ -f proj/a.txt ]] && check "tar.gz with one top-level dir extracts to that dir" ok || check "tar.gz with one top-level dir extracts to that dir" no

run_tgz ../proj-1.0.tar.gz >/dev/null 2>&1
[[ -f proj_01/a.txt ]] && check "an existing target gets a numbered suffix" ok || check "an existing target gets a numbered suffix" no

run_tgz ../multi.tgz >/dev/null 2>&1
[[ -f multi/a.txt && -f multi/b.txt ]] && check "archive with loose files gets a dir named after the archive" ok || check "archive with loose files gets a dir named after the archive" no

run_tgz ../single.zip >/dev/null 2>&1
[[ -f only/file.txt ]] && check "zip archives are extracted" ok || check "zip archives are extracted" no

output="$(run_tgz ../not_an_archive.bin 2>&1)"
if [[ ! -e "$work/executed" && "$output" == *"unable to find type"* ]]; then
  check "unrecognised files are skipped, never executed" ok
else
  check "unrecognised files are skipped, never executed" no
fi

echo "plain text" | gzip -c > ../notes.txt.gz
run_tgz ../notes.txt.gz >/dev/null 2>&1
[[ "$(cat notes.txt 2>/dev/null)" == "plain text" && -f ../notes.txt.gz ]] \
  && check "a single-file .gz is decompressed here and the original is kept" ok || check "a single-file .gz is decompressed here and the original is kept" no

[[ -z "$(ls -d tgz_* 2>/dev/null)" ]] && check "no temporary directories are left behind" ok || check "no temporary directories are left behind" no

exit $((fails > 0))
