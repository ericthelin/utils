#!/usr/bin/env bash
# Tests for to_m4b. Skipped when ffmpeg or mp3info are not installed.

unset CDPATH
BIN="$(cd "$(dirname "$0")/../../bin" && pwd)"

for needed in ffmpeg ffprobe mp3info; do
  command -v "$needed" >/dev/null 2>&1 || { echo "skip - $needed not installed"; exit 0; }
done

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
fails=0

check() {
  if [[ "$2" == ok ]]; then echo "ok   - $1"; else echo "FAIL - $1"; fails=$((fails + 1)); fi
}

cd "$work" || exit 1
mkdir "Jane Doe - Sample Book"
ffmpeg -v error -f lavfi -i sine=frequency=440:d=2 -c:a libmp3lame "Jane Doe - Sample Book/01 - Introduction.mp3"
ffmpeg -v error -f lavfi -i sine=frequency=880:d=3 -c:a libmp3lame "Jane Doe - Sample Book/02 - The Middle.mp3"
cp -r "Jane Doe - Sample Book" keep_copy

"$BIN/to_m4b" -n -d dry "Jane Doe - Sample Book" >/dev/null 2>&1
[[ ! -e dry ]] && check "dry run writes nothing" ok || check "dry run writes nothing" no

"$BIN/to_m4b" -k -d out "Jane Doe - Sample Book" >/dev/null 2>&1
book="out/Jane Doe - Sample Book.m4b"
[[ -s "$book" ]] && check "a directory of mp3s becomes one m4b named Author - Title" ok || check "a directory of mp3s becomes one m4b named Author - Title" no
[[ "$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of default=nw=1:nk=1 "$book" 2>/dev/null)" == aac ]] \
  && check "the audio is AAC" ok || check "the audio is AAC" no

chapters="$(ffprobe -v error -show_chapters -of json "$book" 2>/dev/null | python3 -c "
import json, sys
print('|'.join(c['tags']['title'] for c in json.load(sys.stdin)['chapters']))
")"
[[ "$chapters" == "Introduction|The Middle" ]] \
  && check "each file becomes a titled chapter" ok || check "each file becomes a titled chapter" no

tags="$(ffprobe -v error -show_entries format_tags=artist,title,genre -of default=nw=1 "$book" 2>/dev/null)"
[[ "$tags" == *"Jane Doe"* && "$tags" == *"Sample Book"* && "$tags" == *Audiobook* ]] \
  && check "author and title come from the directory name" ok || check "author and title come from the directory name: $tags" no

[[ -d "Jane Doe - Sample Book" && -f "Jane Doe - Sample Book/01 - Introduction.mp3" ]] \
  && check "--keep leaves the source files" ok || check "--keep leaves the source files" no

"$BIN/to_m4b" -d out2 keep_copy >/dev/null 2>&1
[[ -n "$(ls out2/*.m4b 2>/dev/null)" && ! -e "keep_copy/01 - Introduction.mp3" ]] \
  && check "the source files are removed by default" ok || check "the source files are removed by default" no

exit $((fails > 0))
