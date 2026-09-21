#!/usr/bin/env bash
# Tests for mmmake: archive builds, plain Makefile builds, failures, unknown projects.

unset CDPATH
BIN="$(cd "$(dirname "$0")/../../bin" && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
fails=0

check() {
  if [[ "$2" == ok ]]; then echo "ok   - $1"; else echo "FAIL - $1"; fails=$((fails + 1)); fi
}

cd "$work" || exit 1

# Project with a configure script that records --prefix, a Makefile that installs to it.
mkdir hello-1.0
cat > hello-1.0/configure <<'CONF'
#!/bin/sh
prefix=/usr/local
for arg in "$@"; do case "$arg" in --prefix=*) prefix="${arg#--prefix=}";; esac; done
printf 'PREFIX=%s\n' "$prefix" > Makefile
cat >> Makefile <<'MK'
all:
	echo built > hello
install:
	mkdir -p $(PREFIX)/bin
	cp hello $(PREFIX)/bin/hello
MK
CONF
chmod +x hello-1.0/configure
tar czf hello-1.0.tar.gz hello-1.0
rm -rf hello-1.0

"$BIN/mmmake" hello-1.0.tar.gz --prefix="$work/prefix1" >/dev/null 2>&1
[[ -f "$work/prefix1/bin/hello" ]] && check "builds and installs from a configure archive, passing arguments" ok || check "builds and installs from a configure archive, passing arguments" no

# Plain Makefile project, built in the current directory.
mkdir plain && cd plain || exit 1
cat > Makefile <<'MK'
PREFIX ?= /usr/local
all:
	echo built > tool
install:
	mkdir -p $(PREFIX)/bin
	cp tool $(PREFIX)/bin/tool
MK
"$BIN/mmmake" PREFIX="$work/prefix2" >/dev/null 2>&1
[[ -f "$work/prefix2/bin/tool" ]] && check "builds a plain Makefile project in the current directory" ok || check "builds a plain Makefile project in the current directory" no

# CMake project (skipped when cmake is missing).
if command -v cmake >/dev/null 2>&1; then
  cd "$work" && mkdir cm && cd cm || exit 1
  printf 'cmake_minimum_required(VERSION 3.5)\nproject(demo NONE)\ninstall(FILES note.txt DESTINATION share/demo)\n' > CMakeLists.txt
  echo hi > note.txt
  "$BIN/mmmake" -DCMAKE_INSTALL_PREFIX="$work/prefix3" >/dev/null 2>&1
  [[ -f "$work/prefix3/share/demo/note.txt" ]] && check "builds a CMake project" ok || check "builds a CMake project" no
else
  echo "skip - cmake not installed"
fi

# A failing build reports failure.
cd "$work" && mkdir broken && cd broken || exit 1
printf 'all:\n\tfalse\n' > Makefile
"$BIN/mmmake" >/dev/null 2>&1
[[ $? -ne 0 ]] && check "a failing build exits non-zero" ok || check "a failing build exits non-zero" no

# A directory with nothing recognisable.
cd "$work" && mkdir empty && cd empty || exit 1
output="$("$BIN/mmmake" 2>&1)"
[[ "$output" == *"UNKNOWN make type"* ]] && check "an unrecognised project is reported" ok || check "an unrecognised project is reported" no

exit $((fails > 0))
