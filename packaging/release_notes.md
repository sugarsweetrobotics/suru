## 入れ方

- **pip**: `pip install suru-lang`(`suru` コマンドが入ります。Python 3.10 以降)
- **Homebrew**(macOS・Linux): `brew install __OWNER__/suru/suru`(`suru`・`suruc`・`suru-ls` が入ります)
- **バイナリ**: 下の `suru-版-OS-CPU.tar.gz` を開いて、`suruc`(Go 版コンパイラ)と `suru-ls`(言語サーバー)を PATH の通ったところに置きます。Windows 用は `suru-ls` だけです。`SHA256SUMS` で中身を確かめられます。
- **VS Code**: 拡張機能ビューで「する」を検索します。

バイナリを作る(`suru --翻訳`、`suruc`)には、使う人の手元に clang が要ります。
macOS では `xcode-select --install`、Ubuntu などでは `sudo apt install clang` で入ります。
