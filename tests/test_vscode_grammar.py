# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 sugarsweetrobotics
"""VS Code 拡張(editors/vscode)の色分けの文法が、言語の今の言葉と合っているか"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VSCODE = os.path.join(ROOT, "editors", "vscode")
sys.path.insert(0, VSCODE)

import make_grammar  # noqa: E402


def test_grammar_is_up_to_date():
    with open(make_grammar.OUT, encoding="utf-8") as f:
        committed = f.read()
    assert committed == make_grammar.render(), "python3 editors/vscode/make_grammar.py で作り直してください"


def test_package_points_to_files():
    with open(os.path.join(VSCODE, "package.json"), encoding="utf-8") as f:
        pkg = json.load(f)
    assert os.path.exists(os.path.join(VSCODE, pkg["main"]))
    for g in pkg["contributes"]["grammars"]:
        assert os.path.exists(os.path.join(VSCODE, g["path"]))
    for lang in pkg["contributes"]["languages"]:
        assert os.path.exists(os.path.join(VSCODE, lang["configuration"]))
    commands = {c["command"] for c in pkg["contributes"]["commands"]}
    with open(os.path.join(VSCODE, "extension.js"), encoding="utf-8") as f:
        source = f.read()
    for c in commands:
        assert f'registerCommand("{c}"' in source


def test_builtins_and_keywords_are_highlighted():
    import suru
    import suru_check

    text = json.dumps(make_grammar.build(), ensure_ascii=False)
    for name in suru_check.BUILTIN_CALLS:
        stem = name[: -len("する")] if name.endswith("する") else name
        assert stem in text, name
    for w in (suru.KEYWORDS - set(suru.IKA_WORDS) - set(suru.EXT_BLOCK_WORDS)) | set(suru.PARTICLES) | set(suru.CALL_FORMS):
        assert w in text, w
    # 「以下の手順」は「以下 の 手順」とも書けるので、間の空白を許す形で入っている
    assert "以下[ 　]*の[ 　]*(?:入出力)?手順" in text
    assert "以下[ 　]*の[ 　]*外部[ 　]*の[ 　]*(?:入出力動作|関数)" in text
