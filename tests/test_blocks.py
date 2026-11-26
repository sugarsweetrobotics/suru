"""「以下の手順です … 以上」と、場合分けを閉じる「以上」(#161)"""

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from suru import SuruError, parse_program, run  # noqa: E402
from suru_check import check  # noqa: E402


def output(source: str, capsys) -> list[str]:
    check(source)
    run(source)
    return capsys.readouterr().out.splitlines()


def test_以下の手順_深い行に以上(capsys):
    src = """\
名前 を 挨拶する とは 以下の手順です
  「こんにちは、」 + 名前 + 「さん」 を 表示する
  以上
「太郎」 を 挨拶する
"""
    assert output(src, capsys) == ["こんにちは、太郎さん"]


def test_以下の手順_頭と同じ字下げに以上(capsys):
    src = """\
二回する とは 以下の手順です
  「a」 を 表示する
  「b」 を 表示する
以上
二回する
"""
    assert output(src, capsys) == ["a", "b"]


def test_以下の手順_字下げしない文と以上です(capsys):
    src = """\
二回する とは 以下 の 手順
「a」 を 表示する
「b」 を 表示する
以上です
二回する
"""
    assert output(src, capsys) == ["a", "b"]


def test_以下の手順_句読点の書き方(capsys):
    src = """\
名前を挨拶するとは、以下の手順です。
  「こんにちは、」+名前+「さん」を表示する。
  以上。
二回挨拶するとは、以下の手順です。「太郎」を挨拶する。「花子」を挨拶する。以上です。
二回挨拶する。
"""
    assert output(src, capsys) == ["こんにちは、太郎さん", "こんにちは、花子さん"]


def test_以下の手順_入れ子と結果(capsys):
    src = """\
外する とは 以下の手順です
  内 とは 以下の手順です
    「内」 を 表示する
    「内2」 を 表示する
    以上
  内
  「外」 を 表示する
  以上
外する
"""
    assert output(src, capsys) == ["内", "内2", "外"]


def test_以下の手順_場合分けの枝(capsys):
    src = """\
n を 報告する とは
  もし n が
    0 ならば 「なし」 を 表示する
    そうでなければ 以下の手順です
      「数: 」 を 続表示する
      n を 表示する
      以上
0 を 報告する
3 を 報告する
"""
    assert output(src, capsys) == ["なし", "数: 3"]


def test_以下の入出力手順は動作でなければ型の誤り():
    with pytest.raises(SuruError, match="入出力手順"):
        check("x を 割るする とは 以下の入出力手順です\n  y とは 1\n  （1 の 有）\n  以上\n")


def test_場合分けの入れ子は字下げで外に戻る():
    src = """\
x と y を 分類する とは
  もし x が
    1 ならば もし y が
      1 ならば 「a」
      2 ならば 「b」
    2 ならば 「c」
    そうでなければ 「d」
1 と 1 を 分類する
1 と 2 を 分類する
2 と 1 を 分類する
3 と 1 を 分類する
"""
    check(src)
    assert run(src) == ["a", "b", "c", "d"]


def test_場合分けの入れ子は字下げで外のそうでなければに戻る():
    src = """\
x と y を 分類する とは
  もし x が
    1 ならば もし y が
      1 ならば 「a」
      2 ならば 「b」
    そうでなければ 「c」
1 と 2 を 分類する
3 と 2 を 分類する
"""
    assert run(src) == ["b", "c"]


def test_場合分けを以上で閉じる_1行():
    src = """\
xとyを分類するとは、もしxが1ならば、もしyが1ならば「a」、2ならば「b」以上、2ならば「c」、そうでなければ「d」。
1と2を分類する。2と1を分類する。3と1を分類する。
"""
    check(src)
    assert run(src) == ["b", "c", "d"]


def test_場合分けを以上で閉じる_深い行():
    src = """\
x と y を 分類する とは
  もし x が
    1 ならば もし y が
      1 ならば 「a」
      そうでなければ 「b」
      以上
    そうでなければ 「c」
1 と 5 を 分類する
2 と 5 を 分類する
"""
    assert run(src) == ["b", "c"]


@pytest.mark.parametrize("source, message", [
    ("f とは 以下の手順です\n  1 を 表示する\n", "「以下の手順です」を閉じる「以上」がありません"),
    ("fとは、以下の手順です。「a」を表示する。\n", "「以下の手順です」を閉じる「以上」がありません"),
    ("f とは 以下の手順です\n以上\n", "「以下の手順です」と「以上」の間に文がありません"),
    ("以上\n", "対応する「以下の手順です」のない「以上」があります"),
    ("f とは 以下の手順です\n  1 を 表示する\n  以上\n  2 を 表示する\n", "4行目: 「以上」の後に文があります"),
    ("x とは 1 以上\n", "「以上」"),
    ("f とは 以下の手順です\n  x とは 1\n  以上\n", "手順の最後は定義ではなく"),
])
def test_以上の誤り(source, message):
    with pytest.raises(SuruError, match=message):
        parse_program(source)
