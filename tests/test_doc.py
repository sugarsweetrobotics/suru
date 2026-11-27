"""定義の説明(定義のすぐ上の注釈)とファイルの説明を読む(#209)。compiler/doc_test.go と同じ例"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from suru import ParseContext, doc_comments, parse_program  # noqa: E402

LIB = pathlib.Path(__file__).resolve().parent.parent / "lib"

SRC = """# SPDX-License-Identifier: MIT
# Copyright (c) 2026 だれか
# 計算のライブラリ
#
#   n を 二倍する … 2倍

# 数を2倍します。
#
# 負の数もそのまま2倍します。
数 を 二倍する は 数 を 返す
n を 二倍する とは n * 2 です

例えば 3 を 二倍する は 6 です

# これは説明ではない(空行がある)

n を 三倍する とは n * 3 です

# 円周率の近い値
# 点検しない: 未使用の定義
円周率 とは 3.14 です

# 図形の形
図形 とは 半径 の 円 か 幅 と 高 の 長方形 です
"""


def test_doc_comments():
    module, names = doc_comments(SRC, parse_program(SRC, ParseContext()))
    assert module == "計算のライブラリ\n\n  n を 二倍する … 2倍"
    assert names == {
        "二倍する": "数を2倍します。\n\n負の数もそのまま2倍します。",
        "円周率": "円周率の近い値",
        "図形": "図形の形",
    }


def test_head_comment_is_not_a_description():
    src = "# ファイルの説明\nn を 二倍する とは n * 2\n"
    assert doc_comments(src, parse_program(src)) == ("ファイルの説明", {})


def test_library_files():
    """標準ライブラリのファイルが全部読める(説明の付いた定義があるものを1つ確かめる)"""
    for path in sorted(LIB.glob("*.suru")):
        src = path.read_text(encoding="utf-8")
        module, names = doc_comments(src, parse_program(src))
        if path.name == "通信.suru":
            assert module.startswith("「する」の通信ライブラリ(TCP)")
            assert names["UDP便"].startswith("受け取った便り。")
