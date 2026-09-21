#!/usr/bin/env bash
# Tests for to_mp3. Skipped when ffmpeg, lame or flac are not installed.

unset CDPATH
BIN="$(cd "$(dirname "$0")/../../bin" && pwd)"
TOOL="$(cd "$(dirname "$0")/.." && pwd)/to_mp3"

for needed in ffmpeg ffprobe lame flac metaflac; do
  command -v "$needed" >/dev/null 2>&1 || { echo "skip - $needed not installed"; exit 0; }
done

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
fails=0

check() {
  if [[ "$2" == ok ]]; then echo "ok   - $1"; else echo "FAIL - $1"; fails=$((fails + 1)); fi
}
codec() { ffprobe -v error -show_entries stream=codec_name -of default=nw=1:nk=1 "$1" 2>/dev/null; }

export HOME="$work/home" XDG_CONFIG_HOME="$work/config"
mkdir -p "$HOME" "$XDG_CONFIG_HOME"
cd "$work" || exit 1
mkdir in && cd in || exit 1
ffmpeg -v error -f lavfi -i sine=d=1 a.wav
ffmpeg -v error -f lavfi -i sine=d=1 -metadata title="Flac Song" -metadata artist="Some Band" b.flac
ffmpeg -v error -f lavfi -i sine=d=1 -c:a aac c.m4a
cd "$work" || exit 1

"$BIN/to_mp3" -k -d out in/a.wav </dev/null >/dev/null 2>&1
[[ "$(codec out/a.mp3)" == mp3 ]] && check "wav becomes mp3 (lame)" ok || check "wav becomes mp3 (lame)" no
[[ -f in/a.wav ]] && check "--keep leaves the original" ok || check "--keep leaves the original" no

"$BIN/to_mp3" -k -d out in/b.flac </dev/null >/dev/null 2>&1
[[ "$(codec out/b.mp3)" == mp3 ]] && check "flac becomes mp3" ok || check "flac becomes mp3" no
tags="$(ffprobe -v error -show_entries format_tags=title,artist -of default=nw=1 out/b.mp3 2>/dev/null)"
[[ "$tags" == *"Flac Song"* && "$tags" == *"Some Band"* ]] \
  && check "flac tags are carried into the mp3" ok || check "flac tags are carried into the mp3" no

"$BIN/to_mp3" -k -d out in/c.m4a </dev/null >/dev/null 2>&1
[[ "$(codec out/c.mp3)" == mp3 ]] && check "m4a becomes mp3 (ffmpeg)" ok || check "m4a becomes mp3 (ffmpeg)" no

"$BIN/to_mp3" -n -d dry in/a.wav </dev/null >/dev/null 2>&1
[[ ! -e dry/a.mp3 ]] && check "dry run writes nothing" ok || check "dry run writes nothing" no

cp in/a.wav gone.wav
"$BIN/to_mp3" gone.wav </dev/null >/dev/null 2>&1
[[ -f gone.mp3 && ! -e gone.wav ]] && check "the original is deleted by default" ok || check "the original is deleted by default" no

# Audible keys come from the config file, never from the source.
mkdir -p "$XDG_CONFIG_HOME/to_mp3"
printf '# my key\ndeadbeef  cafe0123\n' > "$XDG_CONFIG_HOME/to_mp3/audible_keys"
head -c 4096 /dev/urandom > book.aax
out="$("$BIN/to_mp3" -n -v -k book.aax </dev/null 2>&1)"
[[ "$out" == *"-activation_bytes deadbeef"* ]] \
  && check "activation bytes are read from the config file" ok || check "activation bytes are read from the config file" no
out="$("$BIN/to_mp3" -n -v -k -A 11112222 book.aax </dev/null 2>&1)"
[[ "$out" == *"-activation_bytes 11112222"* && "$out" != *"deadbeef"* ]] \
  && check "--audible overrides the config file" ok || check "--audible overrides the config file" no
rm "$XDG_CONFIG_HOME/to_mp3/audible_keys"
out="$("$BIN/to_mp3" -n -k -t "$work/none" book.aax </dev/null 2>&1)"
[[ "$out" == *"Unable to find an audible key"* && "$out" == *"audible_keys"* ]] \
  && check "a missing key is reported with the file it looked in" ok || check "a missing key is reported with the file it looked in" no

if grep -E '\b[0-9a-f]{8}\b' "$TOOL" | grep -E '[0-9]' | grep -q .; then
  check "the source contains no embedded activation keys" no
else
  check "the source contains no embedded activation keys" ok
fi

exit $((fails > 0))
