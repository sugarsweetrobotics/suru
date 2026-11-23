import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from suru import Call, ListLit, SuruError, Var, format_error, parse_program, run, Interpreter  # noqa: E402

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

DIV = "a を b で 割った数にする とは a / b\n"


def test_助詞で引数を区別し語順は自由():
    assert run(DIV + "10 を 2 で 割った数にする\n2 で 10 を 割った数にする") == [5, 5]


def test_助詞がくっついていてもよい():
    assert run("a を b で割った数にする とは a / b\n10 を 2 で割った数にする") == [5]


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
    assert run("a を b で 割った数にする とは a / b\n10を2で『割った数に』する。") == [5]


def test_名前に混ざったひらがなはエラー():
    with pytest.raises(SuruError, match="ひらがな「った」が混ざって"):
        run("xを割った数にするとは、x。")


def test_句読点の例が動く():
    src = (ROOT / "examples" / "punct.suru").read_text(encoding="utf-8")
    assert run(src) == [3, 15, 5.5, 6, 120, 10, 4, (3, 6, 9, 12), (2, 4), 24, 5, 9]


# --- 組・選択肢の型 -----------------------------------------------------------

POINT = "点 とは 横 と 縦 の 組\n"
SHAPE = "図形 とは 半径 の 円 か 幅 と 高 の 長方形\n"


def _text(src):
    from suru import Interpreter
    return Interpreter().run_text(src)


def test_組を作って取り出す():
    assert _text(POINT + "3 と 4 の 点\n縦 は 4 で 横 は 3 の 点") == ["（横 は 3 で 縦 は 4 の 点）"] * 2
    assert run(POINT + "p とは 3 と 4 の 点\np の 横 + p の 縦") == [7]
    assert run(POINT + "（3 と 4 の 点） が （縦 は 4 で 横 は 3 の 点）") == [True]
    assert run(POINT + "（3 と 4） の 点 が （3 と 4 の 点）") == [True]


def test_組の更新():
    assert _text(POINT + "p とは 3 と 4 の 点\n横 は 10 の p\np") == [
        "（横 は 10 で 縦 は 4 の 点）", "（横 は 3 で 縦 は 4 の 点）"]


def test_組を並べるときは括弧():
    assert _text(POINT + "（1 と 2 の 点） と （3 と 4 の 点）") == [
        "（（横 は 1 で 縦 は 2 の 点） と （横 は 3 で 縦 は 4 の 点））"]
    with pytest.raises(SuruError, match="括弧で囲んで"):
        run(POINT + "1 と 2 の 点 と 3 と 4 の 点")


def test_組の引数の数():
    with pytest.raises(SuruError, match="「点」には2個の値が必要です"):
        run(POINT + "1 と 2 と 3 の 点")
    with pytest.raises(SuruError, match="「高」というフィールドがありません"):
        run(POINT + "（1 と 2 の 点） の 高")


def test_の先頭は今まで通り():
    assert run("xs とは 1 と 2\nys とは 3 と 4\nxs と ys の 先頭") == [((1, 2), 3)]


def test_選択肢の型():
    assert _text(SHAPE + "5 の 円\n幅 は 2 で 高 は 3 の 長方形") == [
        "（半径 は 5 の 円）", "（幅 は 2 で 高 は 3 の 長方形）"]
    assert _text("信号 とは 赤 か 黄 か 青\n赤") == ["赤"]


def test_型の定義の誤り():
    with pytest.raises(SuruError, match="「組」は形が1つのとき"):
        run("図形 とは 半径 の 組 か 幅 の 長方形")
    with pytest.raises(SuruError, match="既に型「図形」で使われています"):
        run(SHAPE + "箱 とは 幅 の 円 か 高 の 四角")


# --- パターンマッチ -----------------------------------------------------------

AREA = SHAPE + """形 を 面積にする とは
  もし 形 が
    半径 の 円 ならば 3 * 半径 ^ 2
    幅 と 高 の 長方形 ならば 幅 * 高
"""


def test_場合分け():
    assert run(AREA + "5 の 円 を 面積にする\n2 と 3 の 長方形 を 面積にする") == [75, 6]


def test_場合分けを1行で():
    assert run(SHAPE + "もし 5 の 円 が 半径 の 円 ならば 半径 そうでなければ 0") == [5]
    assert run(SHAPE + "もし 2 と 3 の 長方形 が 半径 の 円 ならば 半径 そうでなければ 0") == [0]


def test_場合分け_句読点():
    src = ("図形とは半径の円か幅と高の長方形。"
           "形を面積にするとは、もし形が半径の円ならば3*半径^2、幅と高の長方形ならば幅*高。"
           "5の円を面積にする。2と3の長方形を面積にする。")
    assert run(src) == [75, 6]


def test_リストを先頭と残りで分解():
    sum_ = """xs を 合計する とは
  もし xs が
    空 ならば 0
    先頭 は x で 残り は 他 ならば 他 を 合計して x を 加算する
"""
    assert run(sum_ + "1 と 2 と 3 を 合計する") == [6]
    assert run("xsを合計するとは、もしxsが空ならば0、先頭はxで残りは他ならば他を合計して、xを加算する。"
               "1と2と3を合計する。") == [6]


def test_列挙型の場合分け():
    src = """信号 とは 赤 か 黄 か 青
s を 次にする とは
  もし s が
    赤 ならば 青
    青 ならば 黄
    黄 ならば 赤
"""
    assert _text(src + "赤 を 次にする") == ["青"]


def test_書かれていない形はエラー():
    with pytest.raises(SuruError, match="「長方形」の場合がありません"):
        run(SHAPE + "形 を 面積にする とは\n  もし 形 が\n    半径 の 円 ならば 1\n5 の 円 を 面積にする")
    # そうでなければ があれば良い
    assert run(SHAPE + "もし 5 の 円 が 幅 と 高 の 長方形 ならば 1 そうでなければ 0") == [0]


def test_当てはまらないとエラー():
    with pytest.raises(SuruError, match="どの場合にも当てはまりません"):
        run("x を 判定する とは\n  もし x が\n    1 ならば 「一」\n    2 ならば 「二」\n3 を 判定する")


def test_入れ子のパターン():
    src = POINT + "図形 とは 中心 と 半径 の 円 か 幅 の 正方形\n" + \
        "もし （1 と 2 の 点） と 5 の 円 が （x と y の 点） と r の 円 ならば x + y + r そうでなければ 0"
    assert run(src) == [8]


def test_パターンの誤り():
    with pytest.raises(SuruError, match="2回使われています"):
        run(POINT + "もし 1 と 2 の 点 が x と x の 点 ならば x そうでなければ 0")
    with pytest.raises(SuruError, match="「点」のパターンには2個の名前が必要です"):
        run(POINT + "もし 1 と 2 の 点 が x の 点 ならば x そうでなければ 0")
    with pytest.raises(SuruError, match="「点」には「高」というフィールドがありません"):
        run(POINT + "もし 1 と 2 の 点 が 高 は x の 点 ならば x そうでなければ 0")


def test_今までのもしはそのまま():
    assert run("n を 判定する とは もし n % 2 が 0 ならば 「偶」 そうでなければ 「奇」\n3 を 判定する") == ["奇"]
    src = "x を 判定する とは\n  もし x が 1 ならば 「一」\n  そうでなければ もし x が 2 ならば 「二」 そうでなければ 「他」\n"
    assert run(src + "2 を 判定する\n3 を 判定する") == ["二", "他"]


# --- 性質 ---------------------------------------------------------------------

COMPARABLE = """比較可能 という 性質 とは
  a と b を 比較する
  a と b を 大きい方にする とは
    もし （a と b を 比較する） > 0 ならば a そうでなければ b
"""


def test_性質と実装():
    src = POINT + COMPARABLE + """点 は 比較可能
  p と q を 比較する とは p の 横 - q の 横
数 は 比較可能
  a と b を 比較する とは a - b
"""
    assert _text(src + "（1 と 2 の 点） と （3 と 0 の 点） を 大きい方にする\n5 と 9 を 大きい方にする") == [
        "（横 は 3 で 縦 は 0 の 点）", "9"]


def test_性質_句読点():
    src = ("点とは横と縦の組。"
           "比較可能という性質とは、aとbを比較する。"
           "ただし、aとbを『大きい方に』するとは、もし（aとbを比較する）>0ならばaそうでなければb。"
           "数は比較可能。ただし、aとbを比較するとは、a-b。"
           "5と9を『大きい方に』する。")
    assert run(src) == [9]


def test_性質を持たない型はエラー():
    with pytest.raises(SuruError, match="「文字列」は性質「比較可能」を持っていません"):
        run(COMPARABLE + "「a」 と 「b」 を 比較する")


def test_実装が足りないとエラー():
    with pytest.raises(SuruError, match="「点」は性質「比較可能」の「比較する」を定義していません"):
        run(POINT + COMPARABLE + "点 は 比較可能\n  p と q を 大きい方にする とは p")
    with pytest.raises(SuruError, match="助詞が性質「比較可能」での宣言と違います"):
        run(POINT + COMPARABLE + "点 は 比較可能\n  p を q で 比較する とは 0")


def test_表示可能():
    src = POINT + "点 は 表示可能\n  p を 文字列化する とは 「(」 + p の 横 + 「, 」 + p の 縦 + 「)」\n"
    assert _text(src + "1 と 2 の 点\n（1 と 2 の 点） と （3 と 4 の 点）\n5 を 文字列化する") == [
        "(1, 2)", "（(1, 2) と (3, 4)）", "5"]


def test_データの例が動く():
    src = (ROOT / "examples" / "data.suru").read_text(encoding="utf-8")
    assert _text(src)[-3:] == ["（横 は 3 で 縦 は 0 の 点）", "9", "2×3"]


# --- 動作(副作用)・連鎖可能・手順 ---------------------------------------------

def _io(src, inputs=()):
    """実行して、(表示された行, トップレベルの値) を返す"""
    from suru import Interpreter
    out, feed = [], list(inputs)

    def read(prompt):
        out.append(prompt)
        if not feed:
            raise EOFError
        return feed.pop(0)

    values = Interpreter(out=out.append, read=read).run(src)
    return out, values


def test_表示するは動作を返しトップレベルで行う():
    out, values = _io("「a」 を 表示する\n1 + 1\n「b」 を 表示する")
    assert out == ["a", "b"] and values == [2]


def test_作っただけの動作は行われない():
    out, values = _io("（「a」 を 表示する） と 1")
    assert out == [] and values[0][1] == 1


def test_手順と入力():
    src = "挨拶する とは 手順\n  名前 とは 「名前? 」 を 入力した 結果\n  「やあ、」 + 名前 を 表示する\n  名前 の 長さ を 結果にする\n"
    out, _ = _io(src + "挨拶してから 表示する", ["太郎"])
    assert out == ["名前? ", "やあ、太郎", "2"]


LOOP = "n を 数え上げする とは 手順\n  n を 表示する\n  もし n < 30000 ならば n + 1 を 数え上げする そうでなければ 「終わり」 を 表示する\n"


def test_手順の最後で自分を呼んでもスタックが尽きない():
    # 再帰の深さの上限(10000)を超えて繰り返す。サーバーの「待ち受け続ける」の形
    out, _ = _io(LOOP + "1 を 数え上げする")
    assert len(out) == 30001 and out[-2:] == ["30000", "終わり"]


def test_入力が終わるまで読み続ける():
    src = "読み続けする とは 手順\n  行 とは 入力した 結果\n  もし 行 が 「」 ならば 「終わり」 を 表示する そうでなければ 読み続けする\n"
    assert _io(src + "読み続けする", ["x"] * 20000 + [""])[0][-1] == "終わり"


def test_句読点の書き方の手順():
    src = "手順（xとは、「? 」を入力した結果を数値にする。x*2を表示する）。"
    assert _io(src, ["21"])[0] == ["? ", "42"]


def test_手順の開き括弧だけの行():
    src = "手順（\n  xとは、「? 」を入力した結果。\n  xを表示する）。"
    assert _io(src, ["q"])[0] == ["? ", "q"]


def test_してからはバインド():
    out, _ = _io("x を 三倍する とは x * 3\n入力してから 数値にして 三倍して 表示する", ["5"])
    assert out == ["", "15"]


def test_してからの前が動作でないとエラー():
    with pytest.raises(SuruError, match="動作ではありません"):
        _io("1 を 加算してから 表示する")


def test_の結果は写像():
    out, _ = _io("（入力する） の 結果 を 数値にしてから 表示する", ["7"])
    assert out == ["", "7"]
    assert run(TRIPLE2 + "（1 と 2） の 結果 を 三倍する") == [(3, 6)]  # リストにも使える


def test_結果は予約語ではない():
    assert run("結果 とは 3\n結果 * 2") == [6]
    pt = "点 とは 結果 と 他 の 組\n"
    assert run(pt + "（1 と 2 の 点） の 結果") == [1]


def test_それから():
    src = "二回 とは 「A」 を 表示する\nそれから 「B」 を 表示する\n二回\n二回"
    assert _io(src)[0] == ["A", "B", "A", "B"]
    assert _io("「a」を表示する。それから、「b」を表示する。")[0] == ["a", "b"]


def test_した結果は手順の外ではエラー():
    with pytest.raises(SuruError, match="手順の文の中で使ってください"):
        _io("x とは 入力した 結果\nx", ["a"])


def test_手順の途中の文が動作でないとエラー():
    with pytest.raises(SuruError, match="動作ではありません"):
        _io("手順（1+1。「a」を表示する）。")


def test_数値にする():
    assert run("「12」 を 数値にする\n「１．５」 を 数値にする") == [12, 1.5]
    with pytest.raises(SuruError, match="数値にできません"):
        run("「abc」 を 数値にする")


def test_動作で計算するとヒント():
    with pytest.raises(SuruError, match="してから"):
        run("（入力する） + 1")


def test_実行する():
    out, _ = _io("（1 と 2） の それぞれ を 表示して 実行する")
    assert out == ["1", "2"]


def test_リストの連鎖():
    assert run("（1 と 2） を （n を 受け取って n と n を 返すこと） で 連鎖する") == [(1, 1, 2, 2)]
    src = "手順（xとは、（1と2）を連鎖用にした結果。yとは、（10と20）を連鎖用にした結果。x+yを結果にする）。"
    assert run("xsを連鎖用にするとは、xs。" + src) == [(11, 21, 12, 22)]


MAYBE = (
    "『たぶん』とは、値の在か不在。\n"
    "『たぶん』は連鎖可能。ただし、mをfで連鎖するとは、もしmが値の在ならばfを値に適用する、そうでなければ不在。"
    "ただし、xを結果にするとは、xの在。\n"
    "xを半分にするとは、もしx%2==0ならばx/2の在、そうでなければ不在。\n"
)


def test_自分の型を連鎖可能にする():
    src = "手順（aとは、{}を半分にした結果。bとは、aを半分にした結果。a+bを結果にする）。"
    assert _text(MAYBE + src.format(8)) == ["（値 は 6 の 在）"]
    assert _text(MAYBE + src.format(6)) == ["不在"]
    assert _text(MAYBE + "（8を半分にする）の結果を三倍する。".replace("三倍", "倍化") + "\nxを倍化するとは、x*2。") == [
        "（値 は 8 の 在）"]


def test_動作の例が動く():
    src = (ROOT / "examples" / "io.suru").read_text(encoding="utf-8")
    out, values = _io(src, ["花子", "4", "5"])
    assert out[:4] == ["こんにちは", "はじめ", "おわり", "お名前は? "]
    assert "こんにちは、花子さん" in out and "12" in out and "15" in out
    assert values == [(1, 10, 2, 20, 3, 30), (3, 6)]


def test_対話版フィボナッチの例が動く():
    src = (ROOT / "examples" / "fib_input.suru").read_text(encoding="utf-8")
    out, _ = _io(src, ["6"])
    assert out[1:] == ["0", "1", "1", "2", "3", "5"]


# --- エラー位置の列表示 -----------------------------------------------------

def _error(src: str) -> SuruError:
    with pytest.raises(SuruError) as info:
        run(src)
    return info.value


def test_エラーに何文字目かが付く():
    e = _error("税率 とは 0.1\n10 を 存在しない数にする")
    assert (e.line, e.col) == (2, 6)
    assert str(e).startswith("2行目 6文字目: ")


def test_句読点の書き方でも何文字目かが分かる():
    e = _error("xを三倍するとは、x*3。5を三倍する。7を増加する。")
    assert e.line == 1 and e.col == 23


def test_実行時のエラーも位置が分かる():
    e = _error("n を 割った数にする とは 10 / n\n0 を 割った数にする")
    assert (e.line, e.col) == (1, 19)


def test_エラーの行と印を表示する():
    src = "x とは 1・2"
    text = format_error(_error(src), src)
    assert text.splitlines() == [
        "エラー: 1行目 7文字目: 中黒「・」は将来の書き方のために予約されています(文字列の中では使えます)",
        "  x とは 1・2",
        "          ^",
    ]


def test_全角の字下げでも印の位置が合う():
    src = "　　xを三倍するとは、x*3。"
    lines = format_error(_error(src), src).splitlines()
    assert lines[2].index("^") == 2 + 4


# --- パターンの条件(ガード)と「かつ」「または」 --------------------------------

SHAPES = "図形 とは 半径 の 円 か 幅 と 高 の 長方形\n"


def test_パターンの条件():
    src = SHAPES + (
        "形 を 分類する とは\n"
        "  もし 形 が\n"
        "    半径 の 円 かつ 半径 > 10 ならば 「大きい円」\n"
        "    半径 の 円 ならば 「円」\n"
        "    幅 と 高 の 長方形 ならば 「四角」\n"
        "20 の 円 を 分類する\n3 の 円 を 分類する\n1 と 2 の 長方形 を 分類する"
    )
    assert run(src) == ["大きい円", "円", "四角"]


def test_条件つきの場合は形がそろった数に入れない():
    src = SHAPES + (
        "形 を 分類する とは\n"
        "  もし 形 が\n"
        "    半径 の 円 かつ 半径 > 10 ならば 1\n"
        "    幅 と 高 の 長方形 ならば 2\n"
    )
    with pytest.raises(SuruError, match="「円」の場合がありません"):
        run(src)


def test_値のパターンにも条件を付けられる():
    assert run("nを判定するとは、もしnが0かつ真ならば「零」、そうでなければ「他」。0を判定する。1を判定する。") == ["零", "他"]


def test_かつ_または():
    assert run("1 > 0 かつ 2 > 3\n1 > 0 または 2 > 3\n1 > 2 または 2 > 3 かつ 真") == [False, True, False]
    assert run("偽 かつ （1 / 0 が 1）\n真 または （1 / 0 が 1）") == [False, True]
    assert run("もし 1 が 1 かつ 2 が 2 ならば 「両方」 そうでなければ 「違う」") == ["両方"]


def test_かつの両側は真偽():
    with pytest.raises(SuruError, match="真 か 偽"):
        run("1 かつ 真")


# --- 場合ごとの関数定義 -----------------------------------------------------

def test_値ごとの定義():
    src = "0 を 階乗する とは 1\nn を 階乗する とは n * （n - 1 を 階乗する）\n5 を 階乗する"
    assert run(src) == [120]


def test_句読点の書き方で値ごとの定義():
    assert run("0を階乗するとは、1。nを階乗するとは、n*（n-1を階乗する）。6を階乗する。") == [720]


def test_リストを分ける定義():
    src = "空 を 合計する とは 0\n先頭 は x で 残り は 他 を 合計する とは x + （他 を 合計する）\n1 と 2 と 3 を 合計する"
    assert run(src) == [6]


def test_形ごとの定義():
    src = SHAPES + (
        "（r の 円） を 面積にする とは 3 * r ^ 2\n（w と h の 長方形） を 面積にする とは w * h\n"
        "2 の 円 を 面積にする\n2 と 3 の 長方形 を 面積にする"
    )
    assert run(src) == [12, 6]


def test_中身のない形ごとの定義():
    src = "信号 とは 赤 か 黄 か 青\n赤 を 次にする とは 青\n青 を 次にする とは 黄\n黄 を 次にする とは 赤\n赤 を 次にして 次にする"
    assert _text(src) == ["黄"]


def test_複数の引数の場合ごとの定義():
    src = "0 を x で 試算する とは x\nn を x で 試算する とは n\n0 を 7 で 試算する\n3 を 7 で 試算する\n（0 と 1） の それぞれ を 7 で 試算する"
    assert run(src) == [7, 3, (7, 1)]
    src = "0 と y を 足算する とは y\nx と y を 足算する とは x + y\n0 と 5 を 足算する\n2 と 5 を 足算する"
    assert run(src) == [5, 7]


def test_場合ごとの局所定義():
    src = (
        "nを計数するとは、合計。ただし、空を合計するとは、0。"
        "ただし、先頭はxで残りは他を合計するとは、x+（他を合計する）。ただし、合計とは、nを合計する。\n1と2を計数する。"
    )
    assert run(src) == [3]


def test_性質の実装も場合ごとに定義できる():
    src = (
        "比較可能 という 性質 とは\n  a と b を 比較する\n点 とは 横 と 縦 の 組\n点 は 比較可能\n"
        "  （0 と 0 の 点） と q を 比較する とは 「原点」\n  p と q を 比較する とは 「他」\n"
        "（0 と 0 の 点） と 3 を 比較する\n（1 と 0 の 点） と 3 を 比較する"
    )
    assert run(src) == ["原点", "他"]


def test_場合ごとの定義のエラー():
    with pytest.raises(SuruError, match="どんな値にも当てはまるので、2行目"):
        run("n を 試す数にする とは 1\n0 を 試す数にする とは 2")
    with pytest.raises(SuruError, match="助詞が違います"):
        run("0 を 試す数にする とは 1\nn に 試す数にする とは 2")
    with pytest.raises(SuruError, match="「5」は「試す数にする」のどの定義にも当てはまりません"):
        run("0 を 試す数にする とは 1\n1 を 試す数にする とは 2\n5 を 試す数にする")
    with pytest.raises(SuruError, match="「面積にする」に「長方形」の場合の定義がありません"):
        run(SHAPES + "（r の 円） を 面積にする とは r")
    with pytest.raises(SuruError, match="1行目でも定義されています"):
        run("x を 試す数にする とは 1\ny とは 2\nx を 試す数にする とは 2")
    with pytest.raises(SuruError, match="2回使われています"):
        run(SHAPES + "（x と x の 長方形） を 試す数にする とは 1")


def test_場合ごとの定義の例が動く():
    src = (ROOT / "examples" / "cases.suru").read_text(encoding="utf-8")
    assert _text(src) == ["3628800", "10", "12", "10", "黄", "大きい円", "正方形", "正の偶数", "真"]


# --- 述語(である・でない・であること) ----------------------------------------

EVEN = "n が 偶数である とは n % 2 が 0\n"


def test_述語の定義と呼び出し():
    assert run(EVEN + "4 が 偶数である\n3 が 偶数である\n3 が 偶数でない") == [True, False, True]


def test_述語は条件に書ける():
    assert run(EVEN + "もし 6 が 偶数である ならば 「偶」 そうでなければ 「奇」") == ["偶"]
    assert run("nが正であるとは、n>0。もし-1が正でないならば「負か零」、そうでなければ「正」。") == ["負か零"]


def test_であることは述語の値():
    assert run(EVEN + "1 と 2 と 3 と 4 から 偶数であること で 選別する") == [(2, 4)]


def test_述語と_かつ_または():
    src = EVEN + "n が 正である とは n > 0\n"
    assert run(src + "3 が 正である かつ 3 が 偶数でない\n1 > 0 かつ 3 が 偶数である") == [True, False]
    assert run(src + "真 または 偽 かつ 1 が 偶数である") == [True]
    assert run(src + "もし 1 が 1 かつ 2 が 偶数である ならば 「a」 そうでなければ 「b」") == ["a"]


def test_して_の結果は述語の_が_に入る():
    assert run(EVEN + "x を 三倍する とは x * 3\n4 を 三倍して 偶数である") == [True]


def test_述語の引数と場合ごとの定義():
    assert run("a が b で 割切である とは a % b が 0\n9 が 3 で 割切である") == [True]
    assert run("0 が 零である とは 真\nn が 零である とは 偽\n0 が 零である\n2 が 零である") == [True, False]
    assert run(EVEN + "（1 と 2） の それぞれ が 偶数である") == [(False, True)]


def test_述語のエラー():
    with pytest.raises(SuruError, match="真 か 偽 を返す必要があります"):
        run("n が 変である とは 1\n1 が 変である")
    with pytest.raises(SuruError, match="「…である」の形で定義"):
        run("n が 奇数でない とは 真")


def test_述語の例が動く():
    src = (ROOT / "examples" / "predicate.suru").read_text(encoding="utf-8")
    assert _text(src) == ["真", "真", "真", "（2 と 4）", "正の偶数", "偽", "負か零"]


# --- 丁寧語の文末 -----------------------------------------------------------

def test_しますはすると同じ():
    assert run(TRIPLE + ADD + "5　を三倍します") == [15]
    assert run("nを三倍するとは、n*3。5を三倍します。") == [15]


def test_しましてはしてと同じ():
    assert run("nを三倍するとは、n*3。5を三倍しまして、三倍します。") == [45]
    assert run("n を 三倍する とは n * 3\n5 を 三倍しまして 三倍します") == [45]


def test_しますで定義してもよい():
    assert run("nを三倍しますとは、n*3。5を三倍する。") == [15]


def test_しましてからはしてからと同じ(capsys):
    _text("「やあ」を表示しましてから、表示します。")
    assert capsys.readouterr().out.split() == ["やあ", "やあ"]


def test_文末のですは読み捨てる():
    assert run("xとは、7です。xを三倍するとは、x*3です。x。") == [7]
    assert run("x とは 7 です\nx") == [7]
    assert run("x とは 7です\nx") == [7]
    assert _text(POINT + "p とは 3 と 4 の 点 です。\npの横。") == ["3"]


def test_ならばの後のです():
    src = "nを判定するとは、もしn>0ならば「正」です、そうでなければ「負」です。3を判定する。-1を判定する。"
    assert run(src) == ["正", "負"]
    src = "n を 判定する とは\n  もし n > 0 ならば 「正」 です\n  そうでなければ 「負」 です\n3 を 判定する"
    assert run(src) == ["正"]


def test_文の途中のですはエラー():
    with pytest.raises(SuruError, match="です"):
        run("x とは 3 です と 4")
    with pytest.raises(SuruError, match="です"):
        run("xとは、3です と4。")


def test_丁寧語の例が動く(capsys):
    src = (ROOT / "examples" / "polite.suru").read_text(encoding="utf-8")
    _text(src)
    assert capsys.readouterr().out.split() == ["15", "120", "零か負", "21"]


# --- ファイルの読み込み -------------------------------------------------------

MATH = (
    "円周率 とは 3\n"
    "x を 二乗する とは x * x\n"
    "r を 円の面積にする とは 円周率 * （r を 二乗する）\n"
    "図形 とは 半径 の 円 か 幅 と 高 の 長方形\n"
)


def _files(tmp_path, **files):
    for name, src in files.items():
        (tmp_path / f"{name}.suru").write_text(src, encoding="utf-8")


def _run_in(tmp_path, src):
    from suru import Interpreter
    it = Interpreter()
    it.ctx.base_dir = str(tmp_path)
    return it.run_text(src)


def test_ファイルを読み込む(tmp_path):
    _files(tmp_path, 数学=MATH)
    assert _run_in(tmp_path, "「数学」 を 読み込む\n数学内の円周率\n2 を 数学内の円の面積にする") == ["3", "12"]
    assert _run_in(tmp_path, "「数学」を読み込む。（1と2と3）を数学内の二乗することで写像する。") == ["（1 と 4 と 9）"]
    # 型と形は「・」なしで使える
    assert _run_in(tmp_path, "「数学」 を 読み込む\n（2 の 円） の 半径") == ["2"]


def test_読み込んだ名前は区切って使う(tmp_path):
    _files(tmp_path, 数学=MATH)
    with pytest.raises(SuruError, match="「円周率」は定義されていません"):
        _run_in(tmp_path, "「数学」 を 読み込む\n円周率")
    # 「数学」を読み込んでいなければ「数学内」はふつうの名前。同じ名前を自分で定義してもぶつからない
    assert _run_in(tmp_path, "数学内 とは 5\n数学内") == ["5"]
    assert _run_in(tmp_path, "「数学」 を 読み込む\n円周率 とは 4\n円周率 + 数学内の円周率") == ["7"]
    with pytest.raises(SuruError, match="定義できません"):
        _run_in(tmp_path, "数学内の円周率 とは 4")


def test_読み込みのまちがい(tmp_path):
    _files(tmp_path, 式付="x とは 1\nx を 表示する\n", 甲="「乙」 を 読み込む\n", 乙="「甲」 を 読み込む\n")
    with pytest.raises(SuruError, match="ファイル「不在.suru」が見つかりません"):
        _run_in(tmp_path, "「不在」 を 読み込む")
    with pytest.raises(SuruError, match="「式付.suru」の2行目.*定義だけを書いてください"):
        _run_in(tmp_path, "「式付」 を 読み込む")
    with pytest.raises(SuruError, match="自分自身を読み込む"):
        _run_in(tmp_path, "「甲」 を 読み込む")


def test_読み込んだファイルの中の読み込み(tmp_path):
    _files(tmp_path, 基本="n を 倍にする とは n * 2\n", 応用="「基本」 を 読み込む\nn を 四倍にする とは n を 基本内の倍にして 基本内の倍にする\n")
    assert _run_in(tmp_path, "「応用」 を 読み込む\n3 を 応用内の四倍にする") == ["12"]
    with pytest.raises(SuruError, match="定義されていません"):
        _run_in(tmp_path, "「応用」 を 読み込む\n3 を 応用内の基本内の倍にする")


# --- 標準ライブラリ -----------------------------------------------------------

STD_CASES = [
    ("3.7 を 切捨する", "3"), ("-3.2 を 切捨する", "-4"), ("3.2 を 切上する", "4"), ("2.5 を 四捨五入する", "3"),
    ("16 を 平方根にする", "4"), ("7 を 2 で 商にする", "3"),
    ("3 と 7 と 5 を 最大値にする", "7"), ("3 と 7 と 5 を 最小値にする", "3"), ("2 と 4 を 平均する", "3"),
    ("1 から 4 を 範囲にする", "（1 と 2 と 3 と 4）"), ("3 から 1 を 範囲にする", "空"),
    ("4 が 偶数である", "真"), ("3 が 奇数である", "真"), ("0 が 正である", "偽"), ("-1 が 負である", "真"),
    ("（1 と 2 と 3） を 逆順にする", "（3 と 2 と 1）"), ("「abc」 を 逆順にする", "cba"),
    ("（1 と 2 と 3） から 2 を 先頭取得する", "（1 と 2）"), ("「abcde」 から 2 を 先頭削除する", "cde"),
    ("（5 と 6 と 7） から 1 を 番目取得する", "5"), ("「abc」 から 3 を 番目取得する", "c"),
    ("（5 と 6） が 6 を 含有である", "真"), ("「hello」 が 「lo」 を 含有である", "真"), ("（5 と 6） が 7 を 含有でない", "真"),
    ("（1 と 2 と 1 と 3） から 1 を 除去する", "（2 と 3）"), ("（1 と 2 と 1 と 3） を 一意にする", "（1 と 2 と 3）"),
    ("（3 と 1 と 2 と 1） を 整列する", "（1 と 1 と 2 と 3）"), ("（1 と 2） と （3 と 4） を 連結する", "（1 と 2 と 3 と 4）"),
    ("（1 と 2 と 4） から 偶数であること で 計数する", "2"), ("（2 と 4） が 偶数であること で 全部真である", "真"),
    ("（1 と 3） が 偶数であること で 一部真である", "偽"), ("0 を 3 で 複製する", "（0 と 0 と 0）"),
    ("「abc」 を 文字分解する", "（「a」 と 「b」 と 「c」）"), ("「a,b」 を 「,」 で 分割する", "（「a」 と 「b」）"),
    ("（「a」 と 「b」） を 「-」 で 結合する", "a-b"), ("「banana」 を 「a」 から 「o」 へ 置換する", "bonono"),
    ("「abc」 を 大文字にする", "ABC"), ("「ABC」 を 小文字にする", "abc"), ("「　x 」 を 空白除去する", "x"),
    ("「abc」 が 「ab」 で 先頭一致である", "真"), ("「abc」 が 「ab」 で 末尾一致である", "偽"),
]


@pytest.mark.parametrize("src,want", STD_CASES, ids=[c[0] for c in STD_CASES])
def test_標準ライブラリ(tmp_path, src, want):
    assert _run_in(tmp_path, "「標準」 を 読み込んで 使う\n" + src) == [want]


def test_標準ライブラリは前置きを付けて使う(tmp_path):
    assert _run_in(tmp_path, "「標準」 を 読み込む\n（3 と 1） を 標準内の整列する\n4 が 標準内の偶数である") == ["（1 と 3）", "真"]
    assert _run_in(tmp_path, "「標準」を読み込む。（1と2）を標準内の逆順にする。") == ["（2 と 1）"]
    with pytest.raises(SuruError, match="「整列する」は定義されていません"):
        _run_in(tmp_path, "「標準」 を 読み込む\n（3 と 1） を 整列する")
    # 組み込みも読み込まなければ使えない
    with pytest.raises(SuruError, match="「逆順にする」は定義されていません"):
        _run_in(tmp_path, "（1 と 2） を 逆順にする")


def test_読み込んで使う(tmp_path):
    _files(tmp_path, 数学=MATH)
    assert _run_in(tmp_path, "「数学」 を 読み込んで 使う\n円周率 + 数学内の円周率\n3 を 二乗する") == ["6", "9"]
    assert _run_in(tmp_path, "「数学」を読み込んで使います。2を二乗する。") == ["4"]
    # 自分の定義が優先(標準のものは前置きで使える)
    src = "「標準」 を 読み込んで 使う\nxs を 逆順にする とは xs\n（1 と 2） を 逆順にする\n（1 と 2） を 標準内の逆順にする"
    assert _run_in(tmp_path, src) == ["（1 と 2）", "（2 と 1）"]
    # 標準の中の関数は、自分の定義に影響されない
    assert _run_in(tmp_path, "「標準」 を 読み込んで 使う\n空 を 除去する とは 空\n（2 と 1） を 一意にする") == ["（2 と 1）"]


def test_読み込んで使う名前がぶつかる(tmp_path):
    _files(tmp_path, 甲="x を 逆順にする とは 1\n")
    with pytest.raises(SuruError, match="「逆順にする」は「標準」と「甲」の両方にあります"):
        _run_in(tmp_path, "「標準」 を 読み込んで 使う\n「甲」 を 読み込んで 使う\n1")
    assert _run_in(tmp_path, "「標準」 を 読み込んで 使う\n「甲」 を 読み込む\n5 を 甲内の逆順にする") == ["1"]
    assert _run_in(tmp_path, "「標準」 を 読み込んで 使う\n「甲」 を 読み込んで 使う\nx を 逆順にする とは 2\n0 を 逆順にする") == ["2"]
    with pytest.raises(SuruError, match="のように書いて読み込みます"):
        _run_in(tmp_path, "「標準」 を 読み込んで 表示する")


def test_標準ライブラリのまちがい(tmp_path):
    for src, msg in [
        ("-4 を 平方根にする", "負の数「-4」の平方根"),
        ("（1 と 2） から 3 を 番目取得する", "3番目はありません"),
        ("空 を 最大値にする", "当てはまる|ありません|最大値"),
        ("「a」 を 「」 で 分割する", "空の文字列"),
        ("1.5 から 3 を 範囲にする", "整数"),
    ]:
        with pytest.raises(SuruError, match=msg):
            _run_in(tmp_path, "「標準」 を 読み込んで 使う\n" + src)


def test_自分のフォルダの同じ名前のファイルが先(tmp_path):
    _files(tmp_path, 標準="x とは 1\n")
    assert _run_in(tmp_path, "「標準」 を 読み込む\n標準内のx") == ["1"]


def test_data_files_found():
    # lib/ と runtime/ は、リポジトリでも pip で入れたとき(suru_data/)でも見つかる
    import os

    import suru
    import suru_compile

    assert os.path.exists(suru.STD_PATH)
    assert os.path.exists(suru_compile.RUNTIME)


def test_version(capsys):
    import suru

    assert suru.main(["suru", "--version"]) == 0
    assert suru.__version__ in capsys.readouterr().out


# --- 文字とバイト(標準)・通信 ---------------------------------------------


def test_バイト数と文字():
    src = "「標準」 を 読み込んで 使う\n「aあ」 を バイト数にする\n12354 を 文字にする\n「あ」 を 文字コードにする\n改行 の 長さ\n復帰改行 を バイト数にする\n"
    assert run(src) == [4, "あ", 12354, 1, 2]


def test_文字にできない番号はエラー():
    with pytest.raises(SuruError, match="「-1」は文字の番号ではありません"):
        run("「標準」 を 読み込んで 使う\n-1 を 文字にする\n")


def test_通信は読み込まないと使えない():
    with pytest.raises(SuruError, match="定義されていません"):
        run("「標準」 を 読み込む\n標準内の待受開始する\n")


def test_開いていない接続はエラー():
    with pytest.raises(SuruError, match="「5」は開いている待受口か接続ではありません"):
        run("「通信」 を 読み込む\n5 を 通信内の切断する\n")


def test_通信のサーバーに答えてもらう():
    import threading

    from net_helper import REQUESTS, SERVER, ask, expected, free_port

    port = free_port()
    ready = threading.Event()
    errors: list = []

    def serve():
        try:
            Interpreter(out=lambda s: ready.set()).run(SERVER.replace("PORT", str(port)))
        except Exception as e:  # noqa: BLE001
            errors.append(e)
            ready.set()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    assert ready.wait(10) and not errors
    for head, body in REQUESTS:
        assert ask(port, head, body) == expected(head, body)
    t.join(10)
    assert not t.is_alive() and not errors


# --- HTTP ---------------------------------------------------------------------

# HTTP のサーバーは suru-lang/http に移しました。ここでは tests/http/HTTP.suru の写しを使い、
# 通信・試行する がサーバーとして本当に動くかを確かめます(応答の作り方などの試験は suru-lang/http にあります)。

def _serve_in_thread(src: str, out: list) -> None:
    import threading

    from net_helper import HTTP_DIR

    it = Interpreter(out=out.append)
    it.ctx.base_dir = str(HTTP_DIR)
    threading.Thread(target=lambda: it.run(src), daemon=True).start()


def test_バイト列を送る():
    import threading

    from net_helper import BYTES_EXPECTED, BYTES_SERVER, free_port, read_all

    port = free_port()
    ready = threading.Event()
    out: list = []
    threading.Thread(target=lambda: Interpreter(out=lambda s: (out.append(s), ready.set())).run(
        BYTES_SERVER.replace("PORT", str(port))), daemon=True).start()
    assert ready.wait(10)
    assert read_all(port) == BYTES_EXPECTED


def test_バイト列送信するにはバイト列を渡す():
    with pytest.raises(SuruError, match="「バイト列送信する」の「を」はバイト列でなければなりません"):
        run("「通信」 を 読み込む\n「a」 を 1 へ 通信内のバイト列送信する\n")


def test_HTTPのサーバー():
    from net_helper import HTTP_SERVER, free_port, http, wait_http

    port = free_port()
    _serve_in_thread(HTTP_SERVER.replace("PORT", str(port)), [])
    wait_http(port)
    status, headers, body = http(port)
    assert (status, body, headers["Content-Type"]) == (200, "こんにちは", "text/plain; charset=utf-8")
    assert http(port, "/zz?q=1")[::2] == (404, "見つかりません: /zz?q=1")


def test_HTTPのサーバーは動作でも答える():
    from net_helper import HTTP_ACTION_SERVER, free_port, http, wait_http

    port = free_port()
    out: list = []
    _serve_in_thread(HTTP_ACTION_SERVER.replace("PORT", str(port)), out)
    wait_http(port)
    assert http(port, "/post", "本文です", {"X-Name": "taro"})[::2] == (200, "本文です/taro")
    assert out[-1] == "POST /post"


def test_試行するは失敗したら代わりを行う(capsys):
    # 失敗は動作を行っている途中(手順の中)で起きる。試行する の引数を作るときのエラーは止まる
    src = "「標準」 を 読み込んで 使う\n" \
        "x を 壊すする とは 手順\n  「前」 を 表示する\n  空 の 先頭 を 表示する\n" \
        "（1 を 壊すする） を （「代わり」 を 表示する） で 試行してから 表示する\n" \
        "（「ok」 を 表示する） を （「x」 を 表示する） で 試行する\n" \
        "（1 を 壊すする） を （「pure」 を 結果にする） で 試行してから 表示する\n"
    assert _io(src)[0] == ["前", "代わり", "代わり", "ok", "前", "pure"]
    assert capsys.readouterr().err.count("空のリストに「先頭」はありません") == 2


def test_試行するには動作を渡す():
    with pytest.raises(SuruError, match="試行する"):
        run("「標準」 を 読み込んで 使う\n（「a」 を 表示する） を 1 で 試行する\n")


def test_HTTPのサーバーは失敗しても止まらない():
    from net_helper import HTTP_SERVER, abuse, free_port, http, wait_http

    port = free_port()
    _serve_in_thread(HTTP_SERVER.replace("PORT", str(port)), [])
    wait_http(port)
    abuse(port)
    assert http(port)[::2] == (200, "こんにちは")
