#!/usr/bin/env bash
# Tests for to_h264. Skipped when HandBrakeCLI or ffmpeg are not installed.

unset CDPATH
BIN="$(cd "$(dirname "$0")/../../bin" && pwd)"

for needed in HandBrakeCLI ffmpeg ffprobe; do
  command -v "$needed" >/dev/null 2>&1 || { echo "skip - $needed not installed"; exit 0; }
done
perl -MJSON::XS -e1 2>/dev/null || { echo "skip - perl JSON::XS not installed"; exit 0; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
fails=0

check() {
  if [[ "$2" == ok ]]; then echo "ok   - $1"; else echo "FAIL - $1"; fails=$((fails + 1)); fi
}

cd "$work" || exit 1
ffmpeg -v error -f lavfi -i testsrc=s=320x240:r=30:d=2 -f lavfi -i sine=d=2 -shortest -c:v libx264 -c:a aac clip.mp4

plan="$("$BIN/to_h264" -n clip.mp4 2>&1)"
[[ "$plan" == *"HandBrakeCLI -i"* && "$plan" == *"General/Fast 720p30"* ]] \
  && check "dry run shows the HandBrake command with the default preset" ok || check "dry run shows the HandBrake command with the default preset" no
[[ ! -e clip.m4v ]] && check "dry run writes nothing" ok || check "dry run writes nothing" no

plan="$("$BIN/to_h264" -n -H -b '--quality 30' clip.mp4 2>&1)"
[[ "$plan" == *"HQ 1080p30"* && "$plan" == *"--quality 30"* ]] \
  && check "--high_quality selects the HQ preset and --handbrake flags are appended" ok || check "--high_quality selects the HQ preset and --handbrake flags are appended" no

mkdir out
"$BIN/to_h264" -o out clip.mp4 >/dev/null 2>&1
codecs="$(ffprobe -v error -show_entries stream=codec_name -of default=nw=1:nk=1 out/clip.m4v 2>/dev/null | tr '\n' ' ')"
[[ "$codecs" == *h264* && "$codecs" == *aac* ]] \
  && check "encodes to H.264 + AAC in the --output directory" ok || check "encodes to H.264 + AAC in the --output directory ($codecs)" no

"$BIN/to_h264" -o out clip.mp4 >/dev/null 2>&1
[[ $(ls out | wc -l) == 1 ]] && check "refuses to overwrite an existing output" ok || check "refuses to overwrite an existing output" no

cp clip.mp4 gone.mp4
"$BIN/to_h264" -R -o out gone.mp4 >/dev/null 2>&1
[[ -s out/gone.m4v && ! -e gone.mp4 ]] && check "--replace deletes the original after success" ok || check "--replace deletes the original after success" no

exit $((fails > 0))
