#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 sugarsweetrobotics
"""リポジトリを別の持ち主(GitHub の organization など)に移したあと、名前を書きかえる。

    python3 packaging/move_owner.py 新しい持ち主 [--publisher 新しい publisher] [--dry-run]

git で管理しているテキストのファイルの中の、次のものを書きかえる。
  - sugarsweetrobotics/suru(GitHub の URL と Go のモジュールの道。go.mod と import も)
  - sugarsweetrobotics/homebrew-suru(Homebrew の tap)
  - --publisher を付けたときだけ、VS Code 拡張の publisher(package.json と案内)
著作権の表示(Copyright の行)と作者の名前はそのまま残す。
リリースのワークフローは持ち主の名前を GitHub から受け取るので、書きかえなくても動く。
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OLD = "sugarsweetrobotics"


def main(argv):
    args = argv[1:]
    dry = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]
    publisher = None
    if "--publisher" in args:
        i = args.index("--publisher")
        if i + 1 >= len(args):
            print(__doc__.strip(), file=sys.stderr)
            return 2
        publisher = args[i + 1]
        del args[i:i + 2]
    if len(args) != 1:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    new = args[0]
    pairs = [
        (f"{OLD}/suru", f"{new}/suru"),
        (f"{OLD}/homebrew-suru", f"{new}/homebrew-suru"),
        (f"Owner: `{OLD}`", f"Owner: `{new}`"),
    ]
    if publisher:
        pairs += [
            (f'"publisher": "{OLD}"', f'"publisher": "{publisher}"'),
            (f"{OLD}.suru", f"{publisher}.suru"),
            (f"publisher `{OLD}`", f"publisher `{publisher}`"),
            (f"名前空間 `{OLD}`", f"名前空間 `{publisher}`"),
        ]
    files = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split("\0")
    changed = 0
    for name in files:
        path = ROOT / name
        if not name or not path.is_file() or name == "packaging/move_owner.py":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        lines = text.split("\n")
        out = []
        for line in lines:
            if "Copyright" not in line:
                for a, b in pairs:
                    line = line.replace(a, b)
            out.append(line)
        new_text = "\n".join(out)
        if new_text != text:
            changed += 1
            print(name)
            if not dry:
                path.write_text(new_text, encoding="utf-8")
    print(f"{changed} 個のファイル" + ("を書きかえます(--dry-run なので書きかえていません)" if dry else "を書きかえました"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
