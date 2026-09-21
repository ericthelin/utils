#!/usr/bin/env bash
# Tests for plonk, run against a throwaway HOME so nothing real is touched.

unset CDPATH
BIN="$(cd "$(dirname "$0")/../../bin" && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
fails=0

check() {
  if [[ "$2" == ok ]]; then echo "ok   - $1"; else echo "FAIL - $1"; fails=$((fails + 1)); fi
}

export HOME="$work/home"
mkdir -p "$HOME"
cd "$work" || exit 1

# AppImage: fake one is a script that ignores --appimage-extract.
mkdir dl
printf '#!/bin/sh\nexit 0\n' > dl/MyApp-1.2.3-x86_64.AppImage
"$BIN/plonk" -n --no-prompt dl/MyApp-1.2.3-x86_64.AppImage >/dev/null 2>&1
[[ ! -e "$HOME/Applications/MyApp.AppImage" && -f dl/MyApp-1.2.3-x86_64.AppImage ]] \
  && check "dry run changes nothing" ok || check "dry run changes nothing" no

"$BIN/plonk" --copy --no-prompt dl/MyApp-1.2.3-x86_64.AppImage >/dev/null 2>&1
[[ -x "$HOME/Applications/MyApp-1.2.3-x86_64.AppImage" ]] \
  && check "AppImage is copied into ~/Applications and made executable" ok || check "AppImage is copied into ~/Applications and made executable" no
[[ -L "$HOME/Applications/MyApp.AppImage" ]] \
  && check "a version-free symlink is created" ok || check "a version-free symlink is created" no
grep -q '^Exec=.*MyApp.AppImage' "$HOME/.local/share/applications/MyApp.desktop" 2>/dev/null \
  && check "a desktop launcher points at the symlink" ok || check "a desktop launcher points at the symlink" no
[[ -f dl/MyApp-1.2.3-x86_64.AppImage ]] \
  && check "--copy keeps the original" ok || check "--copy keeps the original" no

mv_out="$(cd dl && cp MyApp-1.2.3-x86_64.AppImage MyApp-2.0.0-x86_64.AppImage && "$BIN/plonk" --no-prompt MyApp-2.0.0-x86_64.AppImage 2>&1)"
[[ "$(readlink "$HOME/Applications/MyApp.AppImage")" == *MyApp-2.0.0* && ! -e dl/MyApp-2.0.0-x86_64.AppImage ]] \
  && check "upgrading repoints the symlink and moves (not copies) the file" ok || check "upgrading repoints the symlink and moves (not copies) the file: $mv_out" no

# .deb and .flatpak are only planned in a dry run.
touch dl/tool.deb dl/thing.flatpak
"$BIN/plonk" -n dl/tool.deb 2>&1 | grep -q "sudo apt install" \
  && check "a .deb is installed with apt" ok || check "a .deb is installed with apt" no
"$BIN/plonk" -n dl/thing.flatpak 2>&1 | grep -q "flatpak install --user" \
  && check "a .flatpak is installed for the user" ok || check "a .flatpak is installed for the user" no

# Source archive: extracted, then built and installed via the sibling tgz and mmmake tools.
mkdir -p proj-1.0
cat > proj-1.0/Makefile <<'MK'
all:
	echo built > prog
install:
	mkdir -p $(HOME)/installed
	cp prog $(HOME)/installed/prog
MK
tar czf proj-1.0.tar.gz proj-1.0 && rm -rf proj-1.0
mkdir build && cd build || exit 1
"$BIN/plonk" ../proj-1.0.tar.gz >/dev/null 2>&1
[[ -f "$HOME/installed/prog" ]] \
  && check "a source archive is extracted, built and installed" ok || check "a source archive is extracted, built and installed" no
[[ ! -e ../proj-1.0.tar.gz ]] \
  && check "the archive is removed after a successful install" ok || check "the archive is removed after a successful install" no

exit $((fails > 0))
