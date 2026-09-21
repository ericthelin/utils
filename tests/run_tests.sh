#!/usr/bin/env bash
# Central test runner: discovers and runs every tool's tests.
#
# Conventions:
#   <tool>/tests/test_*.py  -> run with `python3 <file>` (unittest-based)
#   <tool>/tests/test_*.sh  -> run with `bash <file>` (expected to exit non-zero on failure)
#
# Usage: tests/run_tests.sh

set -uo pipefail

cd "$(dirname "$0")/.."

pass=0
fail=0
failed_names=()

run_test() {
  local file="$1"
  local runner="$2"
  printf '==> %s\n' "$file"
  if $runner "$file"; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    failed_names+=("$file")
  fi
}

shopt -s nullglob
for file in */tests/test_*.py; do
  run_test "$file" python3
done
for file in */tests/test_*.sh; do
  run_test "$file" bash
done
shopt -u nullglob

echo
echo "----------------------------------------"
echo "Passed: $pass  Failed: $fail"
if [[ $fail -gt 0 ]]; then
  echo "Failed tests:"
  printf '  - %s\n' "${failed_names[@]}"
  exit 1
fi
exit 0
