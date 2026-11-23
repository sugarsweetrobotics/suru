#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 sugarsweetrobotics
"""リリースの版がそろっているかを調べる。

    python3 packaging/check_version.py v0.1.0        # 本体(suru.py と Go 版の既定の版)
    python3 packaging/check_version.py vscode-v0.4.0 # VS Code 拡張(package.json)

タグの版と書いてある版が違えば、違うところを出して終了コード 1 で終わる。
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def found(path, pattern):
    m = re.search(pattern, (ROOT / path).read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else None


def main(argv):
    if len(argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    tag = argv[1]
    if tag.startswith("vscode-v"):
        want = tag[len("vscode-v"):]
        pkg = json.loads((ROOT / "editors/vscode/package.json").read_text(encoding="utf-8"))
        places = {"editors/vscode/package.json": pkg.get("version")}
    elif tag.startswith("v"):
        want = tag[1:]
        places = {
            "suru.py": found("suru.py", r'^__version__ = "([^"]+)"'),
            "cmd/suruc/main.go": found("cmd/suruc/main.go", r'^var version = "([^"]+)"'),
            "cmd/suru-ls/main.go": found("cmd/suru-ls/main.go", r'^var version = "([^"]+)"'),
        }
    else:
        print(f"タグ {tag} は v… か vscode-v… の形にしてください", file=sys.stderr)
        return 2
    bad = {p: v for p, v in places.items() if v != want}
    for p, v in bad.items():
        print(f"{p} の版は {v} です(タグは {want})", file=sys.stderr)
    if not bad:
        print(f"版 {want} はそろっています")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
