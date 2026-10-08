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

cp dl/MyApp-1.2.3-x86_64.AppImage dl/Other-3.0-x86_64.AppImage
printf 'MyApp.AppImage\n' | "$BIN/plonk" dl/Other-3.0-x86_64.AppImage >/dev/null 2>&1
[[ "$(readlink "$HOME/Applications/MyApp.AppImage")" == *Other-3.0* ]] \
  && check "a typed symlink name that already exists is replaced" ok || check "a typed symlink name that already exists is replaced" no

cp dl/MyApp-1.2.3-x86_64.AppImage dl/Slicer_ubu24-v02.08.04.57-20260922164607.AppImage
"$BIN/plonk" --no-prompt dl/Slicer_ubu24-v02.08.04.57-20260922164607.AppImage >/dev/null 2>&1
[[ -L "$HOME/Applications/Slicer.AppImage" ]] \
  && check "an abbreviated platform tag (ubu24) is stripped from the symlink name" ok || check "an abbreviated platform tag (ubu24) is stripped from the symlink name" no

cp dl/MyApp-1.2.3-x86_64.AppImage dl/Widget_foo-1.0-x86_64.AppImage
"$BIN/plonk" --no-prompt dl/Widget_foo-1.0-x86_64.AppImage >/dev/null 2>&1
cp dl/MyApp-1.2.3-x86_64.AppImage dl/Widget_bar-2.0-x86_64.AppImage
prompt_out="$(printf '\n' | "$BIN/plonk" dl/Widget_bar-2.0-x86_64.AppImage 2>&1)"
[[ "$prompt_out" == *"Symlink name [Widget_foo.AppImage]"* \
   && "$(readlink "$HOME/Applications/Widget_foo.AppImage")" == *Widget_bar-2.0* \
   && ! -e "$HOME/Applications/Widget_bar.AppImage" ]] \
  && check "an existing symlink for the same app is offered and repointed" ok || check "an existing symlink for the same app is offered and repointed: $prompt_out" no

resume_out="$(cd dl && "$BIN/plonk" --no-prompt Widget_bar-2.0-x86_64.AppImage 2>&1)"
[[ $? -eq 0 && "$resume_out" == *"from an earlier install"* ]] \
  && check "a file already moved into ~/Applications is found there" ok || check "a file already moved into ~/Applications is found there: $resume_out" no

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

# Precompiled application archive: moved into ~/Applications with a stable symlink and launcher.
cd "$work" || exit 1
mkdir -p pre/coolide/bin
printf '#!/bin/sh\nexit 0\n' > pre/coolide/bin/cool.sh
printf '#!/bin/sh\nexit 0\n' > pre/coolide/bin/format.sh
chmod +x pre/coolide/bin/cool.sh pre/coolide/bin/format.sh
: > pre/coolide/bin/cool.png
tar czf coolide-2.0-linux.tar.gz -C pre coolide
mkdir build2 && cd build2 || exit 1
"$BIN/plonk" ../coolide-2.0-linux.tar.gz >/dev/null 2>&1
[[ -x "$HOME/Applications/coolide-2.0-linux/bin/cool.sh" && -L "$HOME/Applications/coolide" ]] \
  && check "a precompiled archive is installed with a stable symlink" ok || check "a precompiled archive is installed with a stable symlink" no
grep -q '^Exec=.*Applications/coolide/bin/cool.sh' "$HOME/.local/share/applications/coolide.desktop" 2>/dev/null \
  && grep -q '^Icon=.*Applications/coolide/bin/cool.png' "$HOME/.local/share/applications/coolide.desktop" 2>/dev/null \
  && check "the launcher uses the main script and icon via the symlink" ok || check "the launcher uses the main script and icon via the symlink" no
[[ ! -e coolide-2.0-linux_extract ]] \
  && check "the extraction folder is cleaned up" ok || check "the extraction folder is cleaned up" no

# Nothing installable: the archive is kept, and plonk can finish from the extracted folder.
cd "$work" || exit 1
mkdir -p data/stuff && echo hi > data/stuff/readme.txt
tar czf stuffpack-1.0.tar.gz data
mkdir build3 && cd build3 || exit 1
"$BIN/plonk" --no-prompt ../stuffpack-1.0.tar.gz >/dev/null 2>&1
[[ -f ../stuffpack-1.0.tar.gz && -d stuffpack-1.0.tar_extract ]] \
  && check "an archive that could not be installed is kept" ok || check "an archive that could not be installed is kept" no
rm -rf stuffpack-1.0.tar_extract/data
mkdir -p stuffpack-1.0.tar_extract/recov/bin
printf '#!/bin/sh\nexit 0\n' > stuffpack-1.0.tar_extract/recov/bin/recov
chmod +x stuffpack-1.0.tar_extract/recov/bin/recov
"$BIN/plonk" stuffpack-1.0.tar_extract >/dev/null 2>&1
[[ -x "$HOME/Applications/stuffpack-1.0/bin/recov" && -L "$HOME/Applications/recov" && ! -e stuffpack-1.0.tar_extract ]] \
  && check "an extracted folder left behind can be installed directly" ok || check "an extracted folder left behind can be installed directly" no

exit $((fails > 0))
