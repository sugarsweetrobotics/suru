import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from suru import Call, ListLit, SuruError, Var, parse_program, run  # noqa: E402

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
    # (引数 と 引数 を加算して) 引数 を加算する → 加算(を=[加算(を=[引数, 引数]), 引数])
    x = Var("引数", 1)
    inner = Call("加算する", {"を": ListLit([x, x])}, 1)
    assert body == Call("加算する", {"を": ListLit([inner, x])}, 1)


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
    with pytest.raises(SuruError, match="2個の値が必要"):
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


# --- 助詞で区別する引数 -----------------------------------------------------

DIV = "a を b で 割る数にする とは a / b\n"


def test_助詞で引数を区別し語順は自由():
    assert run(DIV + "10 を 2 で 割る数にする\n2 で 10 を 割る数にする") == [5, 5]


def test_助詞がくっついていてもよい():
    assert run("a を b で割る数にする とは a / b\n10 を 2 で割る数にする") == [5]


def test_ひらがなだけの関数名はエラー():
    from suru import tokenize_line
    with pytest.raises(SuruError, match="ひらがなだけの関数名"):
        tokenize_line("をへんかんする", 1)
    with pytest.raises(SuruError, match="ひらがなだけの関数名"):
        run("x を へんかんする とは x")
    assert [t.kind for t in tokenize_line("を変換する", 1)] == ["PART", "CALL"]


def test_してはをに入る():
    assert run("10 を 2 で 除算して 3 に 加算する") == [8]


def test_同じ助詞は定義で1回まで():
    with pytest.raises(SuruError, match="2回"):
        run("a を b を 足しする とは a + b")


def test_同じ助詞は呼び出しで1回まで():
    with pytest.raises(SuruError, match="2回"):
        run("1 を 2 を 加算する")


def test_足りない引数はエラー():
    with pytest.raises(SuruError, match="「で」の引数が必要"):
        run("10 を 除算する")


def test_受け取らない助詞はエラー():
    with pytest.raises(SuruError, match="「に」の引数を受け取りません"):
        run("x を三倍する とは x * 3\n5 に 三倍する")


def test_組み込みの四則():
    assert run("1 と 2 と 3 を 加算する\n10 から 3 を 減算する\n2 と 3 と 4 を 乗算する\n9 を 2 で 除算する") == [6, 7, 24, 4.5]


def test_組み込みの加算で三倍():
    # 加算する を自分で定義しなくても、三倍の例はそのまま動く
    assert run(TRIPLE + "5 を三倍する") == [15]


# --- リスト -----------------------------------------------------------------

LIST = "リスト とは 1 と 2 と 3\n"


def test_とでリスト():
    assert run("1 と 2 と 3") == [(1, 2, 3)]
    assert run("空") == [()]


def test_リストの性質():
    assert run(LIST + "リスト の 先頭\nリスト の 残り\nリスト の 最後\nリスト の 長さ\nリスト の 残り の 先頭") == [
        1, (2, 3), 3, 3, 2,
    ]


def test_追加と挿入():
    assert run(LIST + "4 を リスト に 追加する\n0 を リスト に 挿入する") == [(1, 2, 3, 4), (0, 1, 2, 3)]


def test_空の判定と再帰():
    src = LIST + (
        "xs を 合計する とは\n"
        "  もし xs が 空 ならば 0\n"
        "  そうでなければ xs の 残り を 合計して xs の 先頭 を 加算する\n"
        "リスト を 合計する"
    )
    assert run(src) == [6]


def test_引数のリストを分解して受け取る():
    assert run("a と b を 差にする とは a - b\n10 と 3 を 差にする") == [7]


def test_空のリストの先頭はエラー():
    with pytest.raises(SuruError, match="空のリスト"):
        run("空 の 先頭")


def test_中黒は予約():
    with pytest.raises(SuruError, match="予約"):
        run("1・2")


def test_表示():
    from suru import format_value
    assert format_value((1, "a", ())) == "（1 と 「a」 と 空）"


# --- 高階関数 ---------------------------------------------------------------

TRIPLE2 = "x を三倍する とは x * 3\n"


def test_それぞれでmap():
    assert run(TRIPLE2 + LIST + "リスト の それぞれ を 三倍する") == [(3, 6, 9)]


def test_それぞれと他の引数():
    assert run(LIST + "リスト の それぞれ を 10 に 加算する") == [(11, 12, 13)]


def test_することで関数の値():
    assert run(TRIPLE2 + "5 に 三倍すること を 適用する\n三倍すること") [0] == 15


def test_部分適用():
    assert run("5 に （1 を 加算すること） を 適用する") == [6]
    assert run("a から b を 引き算する とは a - b\n3 に （10 から 引き算すること） を 適用する") == [7]


def test_部分適用を値にして使う():
    assert run("足す1 とは 1 を 加算すること\n41 に 足す1 を 適用する") == [42]


def test_選別_写像_畳み込み():
    src = TRIPLE2 + LIST + (
        "n を 偶数判定する とは n % 2 == 0\n"
        "リスト から 偶数判定すること で 選別する\n"
        "リスト を 三倍すること で 写像する\n"
        "リスト を 0 から 加算すること で 畳み込みする\n"
    )
    assert run(src) == [(2,), (3, 6, 9), 6]


def test_無名関数():
    assert run("x を 受け取って x * 2 を 返すこと を 7 に 適用する") == [14]
    assert run(LIST + "リスト を 1 から （a と b を 受け取って a * b を 返すこと） で 畳み込みする") == [6]
    assert run(LIST + "リスト の それぞれ に （x を 受け取って x を 三倍する を 返すこと） を 適用する"
               + "\nx を三倍する とは x * 3") == [(3, 6, 9)]


def test_無名関数はクロージャ():
    src = "n を 足す関数にする とは x を 受け取って x + n を 返すこと\n5 に （10 を 足す関数にする） を 適用する"
    assert run(src) == [15]


def test_それぞれが2つならzip():
    assert run("（1 と 2） の それぞれ を （10 と 20） の それぞれ に 加算する") == [(11, 22)]


def test_リストの例が動く():
    src = (ROOT / "examples" / "list.suru").read_text(encoding="utf-8")
    assert run(src)[-1] == (1, 4, 9, 16)


# --- 句読点の書き方 ---------------------------------------------------------

def test_句読点で詰めて書く():
    src = "aとbを加算するとは、a+b。引数を三倍するとは、引数と引数を加算して、引数を加算する。1と2を加算する。5を三倍する。"
    assert run(src) == [3, 15]


def test_句読点と空白の書き方は同じ構文木():
    spaced = parse_program(TRIPLE)
    punct = parse_program("引数を三倍するとは、引数と引数を加算して、引数を加算する。")
    assert punct == spaced


def test_句読点の行と空白の行を混ぜてよい():
    assert run(ADD + "1と2を加算する。\n3 と 4 を加算する") == [3, 7]


def test_文は句点まで改行をまたぐ():
    src = "nを階乗するとは、\n  もしn<=1ならば1、\n  そうでなければn-1を階乗して、nを乗算する。\n5を階乗する。"
    assert run(src) == [120]


def test_句点がない文はエラー():
    with pytest.raises(SuruError, match="「。」が必要"):
        run("1と2を加算する。3を三倍する")
    with pytest.raises(SuruError, match="「。」が必要"):
        run("1、2")


def test_文字種の境目で切る():
    from suru import tokenize_punct_line
    kinds = [(t.kind, t.value) for t in tokenize_punct_line("x1とリストの長さを10で除算して", 1)]
    assert kinds == [
        ("WORD", "x1"), ("KW", "と"), ("WORD", "リスト"), ("KW", "の"), ("WORD", "長さ"),
        ("PART", "を"), ("NUM", 10), ("PART", "で"), ("CALL", "除算する"),
    ]
    assert run("3*4+1。") == [13]


def test_するの前のひらがなは関数名の一部():
    assert run("-5を絶対値にする。") == [5]
    assert run("xを三倍にするとは、x*3。2を三倍にする。") == [6]


def test_ただしで局所定義():
    src = "aとbを平均するとは、合計/2。ただし、合計とは、a+b。4と7を平均する。"
    assert run(src) == [5.5]
    src = "aとbを計算するとは、和*差。ただし、和とは、a+b。ただし、差とは、a-b。5と3を計算する。"
    assert run(src) == [16]


def test_ただしは空白の書き方でも使える():
    assert run("a と b を平均する とは 合計 / 2\nただし 合計 とは a + b\n4 と 6 を平均する") == [5]


def test_ただしの前には定義が必要():
    with pytest.raises(SuruError, match="「ただし」の前"):
        run("ただし、xとは1。")
    with pytest.raises(SuruError, match="「ただし」の前"):
        run("1+2。ただし、xとは1。")


def test_括弧の中に文を並べる():
    assert run("aとbを相乗平均するとは、（積とは、a*b。積^0.5）。4と9を相乗平均する。") == [6]
    with pytest.raises(SuruError, match="最後は式"):
        run("（xとは、1。）。")


def test_もしの入れ子は閉じなくてよい():
    assert run("もし1==1ならばもし2==3ならば10そうでなければ20そうでなければ30。") == [20]


def test_句読点の高階関数():
    src = "リストとは、1と2と3と4。リストのそれぞれを2に乗算する。リストから（nを受け取ってn%2==0を返すこと）で選別する。リストを0から加算することで畳み込みする。"
    assert run(src) == [(2, 4, 6, 8), (2, 4), 10]


def test_文字列の中の句読点はそのまま():
    assert run("「こんにちは、世界。」") == ["こんにちは、世界。"]
    assert run("「a、」+「b」。") == ["a、b"]


def test_ひらがなだけの名前はエラー():
    for src in ("するめいかとは、3。", "するめいか とは 3", "するめいかを三倍する。", "あを三倍するとは、あ*3。",
                "あ を 受け取って あ を 返すこと"):
        with pytest.raises(SuruError, match="ひらがなだけの名前「(するめいか|あ)」.*『』で囲んで"):
            run(src)


def test_ひらがなだけの関数名はエラー_句読点():
    with pytest.raises(SuruError, match="ひらがなだけの関数名.*漢字かカタカナ"):
        run("xをへんかんするとは、x。")
    with pytest.raises(SuruError, match="ひらがなだけの関数名"):
        run("『へんかん』するとは、5。")


def test_ひらがなを含む名前は二重かぎで囲む():
    assert run("『おやつの数』とは、3。『おやつの数』を2に乗算する。") == [6]
    assert run("『するめいか』 とは 3\n『するめいか』 * 2") == [6]
    assert run("a を b で 割る数にする とは a / b\n10を2で『割る数に』する。") == [5]


def test_名前に混ざったひらがなはエラー():
    with pytest.raises(SuruError, match="ひらがな「る」が混ざって"):
        run("xを割る数にするとは、x。")


def test_句読点の例が動く():
    src = (ROOT / "examples" / "punct.suru").read_text(encoding="utf-8")
    assert run(src) == [3, 15, 5.5, 6, 120, 10, 4, (3, 6, 9, 12), (2, 4), 24, 5, 9]
