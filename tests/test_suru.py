import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from suru import Call, Num, SuruError, Var, parse_program, run  # noqa: E402

ADD = "a　と　b　を加算する　とは　a + b\n"
TRIPLE = "引数　を三倍する　とは　引数　と　引数　を加算して　引数　を加算する\n"


# --- ユーザーの例 -----------------------------------------------------------

def test_加算する():
    assert run(ADD + "1　と　2　を加算する") == [3]


def test_三倍する_パイプライン():
    assert run(ADD + TRIPLE + "5　を三倍する") == [15]


def test_三倍するの構文木は加算の入れ子():
    prog = parse_program(TRIPLE)
    body = prog[0].body
    # (引数 と 引数 を加算して) 引数 を加算する → 加算(加算(引数, 引数), 引数)
    assert body == Call("加算する", [Call("加算する", [Var("引数", 1), Var("引数", 1)], 1), Var("引数", 1)], 1)


def test_ファイルの例が動く():
    src = (ROOT / "examples" / "basic.suru").read_text(encoding="utf-8")
    assert run(src) == [3, 15]


# --- 区切り・字句 -----------------------------------------------------------

def test_半角と全角スペースの混在():
    assert run("a と　b を加算する　とは a　+ b\n10　と 20 を加算する") == [30]


def test_をは独立トークンでもよい():
    assert run("a と b を 加算する とは a + b\n1 と 2 を 加算する") == [3]


def test_全角数字と全角記号():
    assert run("１２ ＋ ３ × ４") == [24]
    assert run("１０ ÷ ４") == [2.5]
    assert run("10 / 2") == [5]


def test_算術の優先順位と括弧():
    assert run("1 + 2 * 3") == [7]
    assert run("( 1 + 2 ) * 3") == [9]
    assert run("2 ^ 3 ^ 2") == [512]
    assert run("- 3 + 10 % 4") == [-1]


# --- 定義とオフサイドルール ------------------------------------------------

def test_とはの後で改行してインデント():
    assert run("x を二乗する とは\n  x * x\n4 を二乗する") == [16]


def test_全角スペースのインデント():
    assert run("x を二乗する とは\n　　x * x\n3 を二乗する") == [9]


def test_深い行は式の続き():
    src = "a と b と c を足し合わせする とは a\n    + b\n    + c\n1 と 2 と 3 を足し合わせする"
    assert run(src) == [6]


def test_ブロック内の局所定義():
    src = "a と b を平均する とは\n  合計 とは a + b\n  合計 / 2\n4 と 7 を平均する"
    assert run(src) == [5.5]


def test_定義の順番は自由():
    assert run(TRIPLE + "5 を三倍する\n" + ADD) == [15]


def test_インデントがそろっていないとエラー():
    with pytest.raises(SuruError):
        run("x を二乗する とは\n    x\n  * x")


def test_関数名はするで終わる必要がある():
    with pytest.raises(SuruError, match="する"):
        run("a と b を加算 とは a + b")


def test_値の定義():
    assert run("税率 とは 0.1\n1000 * 税率") == [100.0]


def test_引数なしの関数():
    assert run("答えする とは 42\n答えする") == [42]


# --- パイプライン -----------------------------------------------------------

def test_長いパイプライン():
    src = ADD + TRIPLE + "x を二乗する とは x * x\n2 を三倍して 二乗して 1 を加算する"
    assert run(src) == [37]


def test_引数に算術式():
    assert run(ADD + "1 + 1 と 2 * 3 を加算する") == [8]


def test_括弧で呼び出しを式に埋め込む():
    assert run(ADD + "( 1 と 2 を加算する ) * 3") == [9]


def test_してで終わるとエラー():
    with pytest.raises(SuruError, match="して"):
        run(ADD + "1 と 2 を加算して")


def test_引数の数が違うとエラー():
    with pytest.raises(SuruError, match="引数は2個"):
        run(ADD + "1 を加算する")


# --- 条件と再帰 -------------------------------------------------------------

def test_条件分岐と再帰():
    src = (
        "a と b を乗算する とは a * b\n"
        "n を階乗する とは\n"
        "  もし n <= 1 ならば 1\n"
        "  そうでなければ n - 1 を階乗して n を乗算する\n"
        "5 を階乗する\n"
        "10 を階乗する"
    )
    assert run(src) == [120, 3628800]


def test_フィボナッチ():
    src = (
        "n をフィボナッチする とは\n"
        "  もし n < 2 ならば n\n"
        "  そうでなければ ( n - 1 をフィボナッチする ) + ( n - 2 をフィボナッチする )\n"
        "10 をフィボナッチする"
    )
    assert run(src) == [55]


def test_文字列():
    assert run("「こんにちは、」 + 「世界」") == ["こんにちは、世界"]


def test_未定義はエラー():
    with pytest.raises(SuruError, match="定義されていません"):
        run("1 を謎する")
