"""JSON を1行に1項目で書く準クォート【JSON物】(#250)"""

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import suru_compile  # noqa: E402
from suru import Interpreter, SuruError  # noqa: E402

BLOCK = (
    "「JSON」 を 読み込んで 使う\n\n"
    "題 とは 「品屋」\n"
    "分類群 とは 「品」 と 「店」\n"
    "x とは 以下の【JSON物】です\n"
    "  「title」 は 題\n"
    "  「tags」 は 分類群\n"
    "  count は 1 +\n"
    "    2\n"
    "  「info」 は\n"
    "    「version」 は 「1.0」\n"
    "    「ok」 は 真\n"
    "  「$ref」 は 「#/components/schemas/品」\n"
    "以上です\n"
    "（x を JSON文字列にする） を 表示する\n"
    "y とは 以下の【JSON物】です\n"
    "  a は 1 だけ\n"
    "以上です\n"
    "（y を JSON文字列にする） を 表示する\n"
)
OUT = ['{"title":"品屋","tags":["品","店"],"count":3,"info":{"version":"1.0","ok":true},"$ref":"#/components/schemas/品"}',
       '{"a":[1]}']


def run(src: str, tmp_path: pathlib.Path) -> list[str]:
    out: list[str] = []
    it = Interpreter(out=out.append)
    it.ctx.base_dir = str(tmp_path)
    it.run_text(src)
    return out


def test_1行に1項目で書いたJSON物(tmp_path):
    assert run(BLOCK, tmp_path) == OUT


@pytest.mark.skipif(suru_compile.find_cc() is None, reason="clang がありません")
def test_コンパイルしても同じ(tmp_path):
    from test_compile import same
    assert same(BLOCK, tmp_path, str(tmp_path)).splitlines() == OUT


def test_前置きを付けて読み込んでも使える(tmp_path):
    src = "「JSON」 を 読み込む\n\nx とは 以下の【JSON物】です\n  a は 1\n  b は\n    c は 「d」\n以上です\n（x を JSON内のJSON文字列にする） を 表示する\n"
    assert run(src, tmp_path) == ['{"a":1,"b":{"c":"d"}}']


@pytest.mark.parametrize("body, message", [
    ("  a 1\n", "【JSON物】の1行目: 『「名前」 は 値』の形で書きます"),
    ("  a は\n", "【JSON物】の1行目: 値がありません"),
    ("  a は\n    b は 1\n   c は 2\n", "【JSON物】の3行目: 字下げが上の項目とそろっていません"),
    ("  「a」 は 1\n    「b」 は 2\n", "【JSON物】の1行目: 値を書いた項目の下には項目を書けません"),
])
def test_書き方の誤り(tmp_path, body, message):
    src = "「JSON」 を 読み込んで 使う\n\nx とは 以下の【JSON物】です\n" + body + "以上です\nx を 表示する\n"
    with pytest.raises(SuruError) as info:
        run(src, tmp_path)
    assert message in str(info.value)
