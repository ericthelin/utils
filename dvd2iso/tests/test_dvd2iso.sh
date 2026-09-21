#!/usr/bin/env bash
# Tests for dvd2iso. dvdbackup and eject are replaced by stand-ins (so the disc
# ripping itself is not exercised); everything around it is. A small valid DVD
# structure is generated with make_dvd, so this test needs make_dvd's tools.

unset CDPATH
BIN="$(cd "$(dirname "$0")/../../bin" && pwd)"

for needed in genisoimage ffmpeg dvdauthor spumux convert; do
  command -v "$needed" >/dev/null 2>&1 || { echo "skip - $needed not installed"; exit 0; }
done

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
fails=0

check() {
  if [[ "$2" == ok ]]; then echo "ok   - $1"; else echo "FAIL - $1"; fails=$((fails + 1)); fi
}

cd "$work" || exit 1
ffmpeg -v error -f lavfi -i testsrc=s=320x240:r=30:d=2 -f lavfi -i sine=d=2 -shortest -c:v libx264 -c:a aac clip.mp4
"$BIN/make_dvd" --workdir "$work/source" -o "$work/source.iso" clip.mp4 >/dev/null 2>&1
[[ -d "$work/source/dvd/VIDEO_TS" ]] || { echo "FAIL - could not build the sample DVD structure"; exit 1; }

mkdir stubs
cat > stubs/dvdbackup <<'STUB'
#!/bin/sh
echo "dvdbackup $*" >> "$STUB_LOG"
while [ $# -gt 0 ]; do
  case "$1" in -o) out="$2"; shift;; -n) label="$2"; shift;; esac
  shift
done
mkdir -p "$out/${label:-STUB_DISC}"
cp -r "$STUB_SOURCE/VIDEO_TS" "$out/${label:-STUB_DISC}/"
STUB
printf '#!/bin/sh\necho "eject $*" >> "$STUB_LOG"\n' > stubs/eject
chmod +x stubs/*

export PATH="$work/stubs:$PATH" STUB_LOG="$work/log" STUB_SOURCE="$work/source/dvd" HOME="$work/home"
mkdir -p "$HOME" isos
: > "$work/log"
echo "fake disc" > fake_device

# Run 1: explicit --temp, disc ejected afterwards.
"$BIN/dvd2iso" -d "$work/fake_device" -o "$work/isos/movie.iso" -t "$work" >/dev/null 2>&1
grep -aq VIDEO_TS isos/movie.iso 2>/dev/null \
  && check "builds a DVD-Video ISO at the requested path" ok || check "builds a DVD-Video ISO at the requested path" no
grep -q "^dvdbackup -M" log \
  && check "mirrors the whole disc with dvdbackup" ok || check "mirrors the whole disc with dvdbackup" no
[[ -z "$(ls -d "$work"/dvd2iso.* 2>/dev/null)" ]] \
  && check "the temporary rip directory is removed" ok || check "the temporary rip directory is removed" no
grep -q "^eject " log \
  && check "the disc is ejected afterwards" ok || check "the disc is ejected afterwards" no

# Run 2: --no_eject, --label, and no --temp (temp folder goes beside the output).
: > log
"$BIN/dvd2iso" -E -l "My Label" -d "$work/fake_device" -o "$work/isos/second.iso" >/dev/null 2>&1
grep -q "^eject" log && check "--no_eject leaves the disc alone" no || check "--no_eject leaves the disc alone" ok
grep -q -- "-n My" log \
  && check "--label is passed to dvdbackup" ok || check "--label is passed to dvdbackup" no
[[ -f isos/second.iso && -z "$(ls -d "$work"/isos/dvd2iso.* 2>/dev/null)" ]] \
  && check "with no --temp the rip uses a temp folder beside the output and cleans it up" ok || check "with no --temp the rip uses a temp folder beside the output and cleans it up" no

# Run 3: options from an rc file.
printf '# my defaults\nout = %s\nno_eject\n' "$work/isos/from_rc.iso" > custom.rc
"$BIN/dvd2iso" -D "$work/custom.rc" -d "$work/fake_device" >/dev/null 2>&1
[[ -f isos/from_rc.iso ]] \
  && check "--defaults reads options from an rc file" ok || check "--defaults reads options from an rc file" no

# No waiting or ripping for these.
: > log
rm -f dry.iso
plan="$("$BIN/dvd2iso" -n -E -d "$work/fake_device" -o "$work/dry.iso" 2>&1)"
[[ ! -e dry.iso && "$plan" == *"dvdbackup"* && "$plan" == *"genisoimage"* && ! -s log ]] \
  && check "--dry_run prints the commands and changes nothing" ok || check "--dry_run prints the commands and changes nothing" no

out="$("$BIN/dvd2iso" -d "$work/does_not_exist" -o "$work/x.iso" 2>&1)"
[[ "$out" == *"Invalid DVD device"* ]] \
  && check "a bad device is reported" ok || check "a bad device is reported" no

exit $((fails > 0))
