#!/usr/bin/env bash
set -euo pipefail

unset CDPATH
tool_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
clip="$tool_dir/clip"
test_dir="$(mktemp -d)"
trap 'rm -rf "$test_dir"' EXIT

make_backend() {
    local name="$1"
    cat >"$test_dir/$name" <<'EOF'
#!/bin/sh
printf '%s %s\n' "${0##*/}" "$*" >> "$CLIP_TEST_LOG"
/bin/cat > "$CLIP_TEST_OUTPUT"
EOF
    chmod +x "$test_dir/$name"
}

make_uname() {
    cat >"$test_dir/uname" <<'EOF'
#!/bin/sh
printf '%s\n' "${CLIP_TEST_UNAME-Linux}"
EOF
    chmod +x "$test_dir/uname"
}

run_case() {
    local expected="$1"
    shift
    : >"$test_dir/log"
    : >"$test_dir/output"
    printf 'clipboard content' | env -i PATH="$test_dir" OSTYPE="${OSTYPE-}" CLIP_TEST_LOG="$test_dir/log" CLIP_TEST_OUTPUT="$test_dir/output" "$@"
    [[ "$(<"$test_dir/log")" == "$expected" ]]
    [[ "$(<"$test_dir/output")" == 'clipboard content' ]]
}

make_uname
make_backend xsel
run_case 'xsel --clipboard --input' "$clip"
run_case 'xsel --primary --input' "$clip" --terminal
run_case 'xsel --primary --input' "$clip" -t

make_backend clip.exe
: >"$test_dir/log"
: >"$test_dir/output"
printf 'clipboard content' | env -i PATH="$test_dir" OSTYPE=msys CLIP_TEST_LOG="$test_dir/log" CLIP_TEST_OUTPUT="$test_dir/output" "$clip"
[[ "$(<"$test_dir/log")" == 'clip.exe ' ]]
[[ "$(<"$test_dir/output")" == 'clipboard content' ]]
rm "$test_dir/clip.exe"

make_backend xclip
run_case 'xclip -selection clipboard' "$clip"
run_case 'xclip -selection primary' "$clip" --terminal
run_case 'xclip -selection primary' "$clip" -t

make_backend wl-copy
run_case 'wl-copy ' "$clip"
run_case 'wl-copy --primary' "$clip" --terminal
run_case 'wl-copy --primary' "$clip" -t

make_backend pbcopy
: >"$test_dir/log"
: >"$test_dir/output"
printf 'clipboard content' | env -i PATH="$test_dir" OSTYPE=darwin CLIP_TEST_UNAME=Darwin CLIP_TEST_LOG="$test_dir/log" CLIP_TEST_OUTPUT="$test_dir/output" "$clip" -pboard general
[[ "$(<"$test_dir/log")" == 'pbcopy -pboard general' ]]
[[ "$(<"$test_dir/output")" == 'clipboard content' ]]

rm "$test_dir/pbcopy"
if env -i PATH="$test_dir" OSTYPE=linux "$clip" ignored >/dev/null 2>&1; then
    echo 'expected clip with arguments to fail without pbcopy' >&2
    exit 1
fi

if command -v script >/dev/null 2>&1; then
    : >"$test_dir/log"
    : >"$test_dir/output"
    if script -qefc "env -i PATH='$test_dir' OSTYPE=linux CLIP_TEST_LOG='$test_dir/log' CLIP_TEST_OUTPUT='$test_dir/output' '$clip'" /dev/null >/dev/null 2>&1; then
        echo 'expected clip without standard input to fail immediately' >&2
        exit 1
    fi
    [[ ! -s "$test_dir/log" ]]
    [[ ! -s "$test_dir/output" ]]
fi

echo 'clip tests passed'
