#!/usr/bin/env bash
# Standalone LGPL FFmpeg with MP3 support, built from exact archived sources.
set -euo pipefail
task_root="$(pwd)/build/release-tools"
task_sources="$(pwd)/build/release-sources"
mkdir -p "$task_root" "$task_sources"
curl --fail --location --retry 3 https://ffmpeg.org/releases/ffmpeg-8.0.3.tar.xz -o "$task_sources/ffmpeg-8.0.3.tar.xz"
curl --fail --location --retry 3 https://downloads.sourceforge.net/project/lame/lame/3.100/lame-3.100.tar.gz -o "$task_sources/lame-3.100.tar.gz"
printf '%s  %s\n' 6136812ea6d4e68bdba27e33c2a94382711cdf4f8602ffef056ff792bd6f9818 "$task_sources/ffmpeg-8.0.3.tar.xz" > "$task_sources/verified-inputs.txt"
printf '%s  %s\n' ddfe36cab873794038ae2c1210557ad34857a4b6bdc515785d1da9e175b1da1e "$task_sources/lame-3.100.tar.gz" >> "$task_sources/verified-inputs.txt"
if command -v sha256sum >/dev/null; then sha256sum -c "$task_sources/verified-inputs.txt"; else shasum -a 256 -c "$task_sources/verified-inputs.txt"; fi
tar -xf "$task_sources/lame-3.100.tar.gz" -C "$task_root"
tar -xf "$task_sources/ffmpeg-8.0.3.tar.xz" -C "$task_root"
task_prefix="$task_root/prefix"
task_ldflags=''
if [[ "$(uname -s)" == MINGW* || "$(uname -s)" == MSYS* ]]; then task_ldflags='-static'; fi
cd "$task_root/lame-3.100"
./configure --prefix="$task_prefix" --disable-shared --enable-static --disable-frontend
make -j2
make install
cp COPYING "$task_sources/LAME-COPYING.txt"
cd "$task_root/ffmpeg-8.0.3"
./configure --prefix="$task_prefix" --disable-autodetect --disable-doc --disable-debug \
  --disable-x86asm --disable-shared --enable-static --disable-gpl --disable-nonfree \
  --enable-libmp3lame --extra-cflags="-I$task_prefix/include" \
  --extra-ldflags="-L$task_prefix/lib $task_ldflags"
make -j2
make install
cp config.h ffbuild/config.mak COPYING.LGPLv2.1 LICENSE.md "$task_sources/"
cp "$task_root/lame-3.100/config.log" "$task_sources/lame-config.log"
"$task_prefix/bin/ffmpeg" -version > "$task_sources/ffmpeg-version.txt"
"$task_prefix/bin/ffmpeg" -L > "$task_sources/ffmpeg-license.txt" 2>&1
mkdir -p "$task_root/../ffmpeg-source-records"
cp "$task_sources"/* "$task_root/../ffmpeg-source-records/"
echo "Release tools: $task_prefix/bin"
