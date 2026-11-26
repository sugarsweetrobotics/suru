#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 sugarsweetrobotics
#
# GitHub Releases に置く suruc・suru-ls を、OS と CPU ごとに作って固める(Go が必要)。
#
#   packaging/build_binaries.sh 0.1.0 dist/
#
# どの OS も suruc・suru-ls・kumu です。Linux・macOS は .tar.gz、Windows は .exe を .zip に固めます
# (Windows の suruc・kumu は MSYS2 の clang でプログラムを作ります。README の「Windows 向けのプログラムを作る」)。
# 最後に SHA256SUMS を書きます。
set -eu
version=$1
out=$2
root=$(cd "$(dirname "$0")/.." && pwd)
mkdir -p "$out"
out=$(cd "$out" && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
ldflags="-s -w -X main.version=$version"

for target in linux/amd64 linux/arm64 darwin/amd64 darwin/arm64 windows/amd64 windows/arm64; do
  goos=${target%/*}
  goarch=${target#*/}
  name=suru-$version-$goos-$goarch
  dir=$work/$name
  mkdir -p "$dir"
  exe=""
  if [ "$goos" = windows ]; then
    exe=.exe
  fi
  for cmd in suruc suru-ls kumu; do
    (cd "$root" && CGO_ENABLED=0 GOOS=$goos GOARCH=$goarch go build -trimpath -ldflags="$ldflags" -o "$dir/$cmd$exe" "./cmd/$cmd")
  done
  cp "$root/LICENSE" "$dir/LICENSE"
  cp "$root/runtime/LICENSE" "$dir/LICENSE-runtime-lib"
  cp "$root/README.md" "$dir/README.md"
  cp "$root/README_jp.md" "$dir/README_jp.md"
  if [ "$goos" = windows ]; then
    (cd "$work" && zip -qr "$out/$name.zip" "$name")
    echo "$name.zip"
  else
    tar -C "$work" -czf "$out/$name.tar.gz" "$name"
    echo "$name.tar.gz"
  fi
done

cd "$out"
if command -v sha256sum >/dev/null 2>&1; then
  sha256sum suru-"$version"-* > SHA256SUMS
else
  shasum -a 256 suru-"$version"-* > SHA256SUMS
fi
echo SHA256SUMS
