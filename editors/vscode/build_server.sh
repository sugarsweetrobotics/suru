#!/bin/sh
# 拡張に同梱する言語サーバー suru-ls を、よく使う OS と CPU の分だけ作る(Go が必要)。
# .vsix を作る前に、editors/vscode で実行します: ./build_server.sh && npx @vscode/vsce package
set -e
cd "$(dirname "$0")"
root=../..
mkdir -p server
for target in linux/amd64:linux-x64 linux/arm64:linux-arm64 darwin/amd64:darwin-x64 darwin/arm64:darwin-arm64 windows/amd64:win32-x64; do
  goos=${target%%/*}
  rest=${target#*/}
  goarch=${rest%%:*}
  name=${target##*:}
  exe=""
  [ "$goos" = windows ] && exe=.exe
  echo "suru-ls-$name$exe"
  (cd "$root" && CGO_ENABLED=0 GOOS=$goos GOARCH=$goarch go build -trimpath -ldflags="-s -w" -o "editors/vscode/server/suru-ls-$name$exe" ./cmd/suru-ls)
done
