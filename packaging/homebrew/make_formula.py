#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 sugarsweetrobotics
"""Homebrew の formula(suru.rb)を作る。

    python3 packaging/homebrew/make_formula.py 0.1.0 <ソースの tar.gz の sha256> > suru.rb

ソースは GitHub がタグから作る https://github.com/sugarsweetrobotics/suru/archive/refs/tags/v版.tar.gz。
formula は Go 版の suruc・suru-ls をソースからビルドし、Python 版の suru も入れる。
"""
import re
import sys

TEMPLATE = '''\
# このファイルは sugarsweetrobotics/suru の packaging/homebrew/make_formula.py が作ったものです
class Suru < Formula
  desc "日本語の関数型プログラミング言語「する」(インタプリタ・型検査・コンパイラ・言語サーバー)"
  homepage "https://github.com/sugarsweetrobotics/suru"
  url "https://github.com/sugarsweetrobotics/suru/archive/refs/tags/v{version}.tar.gz"
  sha256 "{sha256}"
  license all_of: ["GPL-3.0-or-later", "MIT"]
  head "https://github.com/sugarsweetrobotics/suru.git", branch: "main"

  depends_on "go" => :build
  depends_on "python@3.13"

  def install
    ldflags = "-s -w -X main.version=#{{version}}"
    system "go", "build", *std_go_args(output: bin/"suruc", ldflags:), "./cmd/suruc"
    system "go", "build", *std_go_args(output: bin/"suru-ls", ldflags:), "./cmd/suru-ls"

    # Python 版はリポジトリと同じ並び(suru.py の隣に lib/ と runtime/)で libexec に置く
    libexec.install "suru.py", "suru_check.py", "suru_compile.py", "lib", "runtime"
    python = Formula["python@3.13"].opt_bin/"python3.13"
    (bin/"suru").write <<~SH
      #!/bin/sh
      exec "#{{python}}" "#{{libexec}}/suru.py" "$@"
    SH
    pkgshare.install "examples"
  end

  def caveats
    <<~EOS
      バイナリを作る(suru --翻訳、suruc)には clang が要ります。
      macOS では Xcode のコマンドラインツール(xcode-select --install)に入っています。
      Linux では、ディストリビューションの clang か brew install llvm を入れてください。
    EOS
  end

  test do
    (testpath/"t.suru").write "1 と 2 を 加算する\\n"
    assert_equal "3", shell_output("#{{bin}}/suru t.suru").strip
    assert_match version.to_s, shell_output("#{{bin}}/suruc --version")
    assert_match version.to_s, shell_output("#{{bin}}/suru-ls --version")
  end
end
'''


def main(argv):
    if len(argv) != 3 or not re.fullmatch(r"\d+\.\d+\.\d+\S*", argv[1]) or not re.fullmatch(r"[0-9a-f]{64}", argv[2]):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    sys.stdout.write(TEMPLATE.format(version=argv[1], sha256=argv[2]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
