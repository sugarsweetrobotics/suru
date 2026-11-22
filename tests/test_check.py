"""静的な型検査(suru_check.py)のテスト"""

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from suru import SuruError  # noqa: E402
from suru_check import check  # noqa: E402


def _err(src: str) -> SuruError:
    with pytest.raises(SuruError) as info:
        check(src)
    return info.value


@pytest.mark.parametrize("path", sorted((ROOT / "examples").glob("*.suru")), ids=lambda p: p.name)
def test_例はすべて検査を通る(path):
    check(path.read_text(encoding="utf-8"), str(path.parent))


def test_引数の型の間違い():
    e = _err("x を 三倍する とは x * 3\n「あ」 を 三倍する")
    assert (e.line, e.col) == (2, 7)
    assert "「三倍する」の「を」には数が必要ですが、文字列が渡されています" in str(e)


def test_足りない引数と余分な引数():
    assert "「で」の引数が必要です" in str(_err("a を b で 割数する とは a / b\n1 を 割数する"))
    assert "「に」の引数を受け取りません" in str(_err("a を 三倍する とは a * 3\n1 を 2 に 三倍する"))


def test_型の混ざったリストはエラー():
    e = _err("1 と 「a」")
    assert e.line == 1 and "リストの要素の型がそろっていません(数 と 文字列)" in str(e)


def test_文字列と数は足せない():
    assert "文字列化する" in str(_err("「答えは」 + 3"))
    check("「答えは」 + （3 を 文字列化する）")


def test_条件分岐の型():
    assert "「ならば」と「そうでなければ」の値の型が違います" in str(_err("もし 真 ならば 1 そうでなければ 「a」"))
    assert "「もし」の条件には真偽が必要" in str(_err("もし 1 ならば 1 そうでなければ 2"))


def test_比較():
    assert "比べられません" in str(_err("1 が 「a」"))
    assert "「<」の右には数が必要" in str(_err("1 < 「a」"))


def test_多相な関数():
    check("x を 恒等にする とは x\n1 を 恒等にする\n「a」 を 恒等にする\n（1 を 恒等にする） + 1")


def test_相互再帰():
    check(
        "n が 偶である とは もし n が 0 ならば 真 そうでなければ n - 1 が 奇である\n"
        "n が 奇である とは もし n が 0 ならば 偽 そうでなければ n - 1 が 偶である\n10 が 偶である"
    )


def test_組のフィールド():
    assert "「+」の両側の型が違います" in str(_err("点 とは 横 と 縦 の 組\np とは 1 と 2 の 点\np の 横 + 「a」"))
    # 組はフィールドごとに型の引数を持つので、別の型の点も作れる(第3段階)
    check("点 とは 横 と 縦 の 組\n1 と 2 の 点\n「a」 と 「b」 の 点")


def test_場合分けの値の型():
    src = (
        "図形 とは 半径 の 円 か 幅 と 高 の 長方形\n形 を 面積にする とは\n  もし 形 が\n"
        "    r の 円 ならば r * r\n    w と h の 長方形 ならば 「x」"
    )
    assert "場合ごとの値の型がそろっていません" in str(_err(src))


def test_場合ごとの定義():
    src = "0 を 階乗する とは 1\nn を 階乗する とは n * （n - 1 を 階乗する）\n"
    check(src + "5 を 階乗する")
    assert "「階乗する」の「を」には数が必要" in str(_err(src + "「a」 を 階乗する"))


def test_述語():
    check("x が 偶数である とは x % 2 が 0\n1 と 2 から 偶数であること で 選別する")
    assert "述語「変である」の値には真偽が必要" in str(_err("n が 変である とは n + 1"))


def test_高階関数():
    check("1 と 2 と 3 を 0 から 加算すること で 畳み込みする")
    assert "「選別する」の「で」の関数の値には真偽が必要" in str(
        _err("x を 三倍する とは x * 3\n1 と 2 から 三倍すること で 選別する")
    )
    assert "数を受け取りますが、文字列が渡されます" in str(_err("（1 を 加算すること） を 「a」 に 適用する"))
    assert "数を受け取りますが、文字列が渡されます" in str(
        _err("（x を 受け取って x * 2 を 返すこと） を 「a」 に 適用する")
    )


def test_それぞれ():
    src = "x を 三倍する とは x * 3\n"
    check(src + "（1 と 2） の それぞれ を 三倍する")
    assert "「三倍する」の「を」には数が必要" in str(_err(src + "（「a」 と 「b」） の それぞれ を 三倍する"))


def test_長さは文字列にもリストにも使える():
    check("「abc」 の 長さ\n（1 と 2） の 長さ")
    assert "「の 長さ」の前は文字列かリスト" in str(_err("5 の 長さ"))


def test_コマンドラインで検査する(tmp_path, capsys):
    import suru

    ok = tmp_path / "ok.suru"
    ok.write_text("1 + 2\n", encoding="utf-8")
    assert suru.main(["suru.py", "--検査", str(ok)]) == 0
    assert "問題は見つかりませんでした" in capsys.readouterr().out
    bad = tmp_path / "bad.suru"
    bad.write_text("1 + 「a」\n", encoding="utf-8")
    assert suru.main(["suru.py", "--検査", str(bad)]) == 1
    err = capsys.readouterr().err
    assert "1行目" in err and "^" in err


# --- 第2段階: 性質と、型の条件 ------------------------------------------------

COMPARE = (
    "比較可能 という 性質 とは\n  a と b を 比較する\n点 とは 横 と 縦 の 組\n点 は 比較可能\n"
    "  a と b を 比較する とは a の 横 - b の 横\n数 は 比較可能\n  a と b を 比較する とは a - b\n"
)


def test_性質の関数は実装の型で調べる():
    check(COMPARE + "（1 と 2 の 点） と （3 と 0 の 点） を 比較する\n（5 と 9 を 比較する） + 1")
    e = _err(COMPARE + "「a」 と 「b」 を 比較する")
    assert e.line == 8 and "文字列は性質「比較可能」を持っていません" in str(e)


def test_性質の関数の値の型は実装から決まる():
    assert "「+」の両側の型が違います(数 と 文字列)" in str(_err(COMPARE + "（5 と 9 を 比較する） + 「a」"))


def test_性質を使う多相な関数():
    src = COMPARE + "a と b を 大きい方にする とは もし （a と b を 比較する） > 0 ならば a そうでなければ b\n"
    check(src + "5 と 9 を 大きい方にする")
    e = _err(src + "「a」 と 「b」 を 大きい方にする")
    assert e.line == 9 and "性質「比較可能」を持っていません" in str(e)


def test_既定の実装():
    src = (
        "挨拶可能 という 性質 とは\n  x を 名乗る文にする\n  x を 挨拶する とは 「やあ、」 + （x を 名乗る文にする）\n"
        "犬 とは 名前 の 組\n犬 は 挨拶可能\n  d を 名乗る文にする とは d の 名前\n"
    )
    check(src + "「ポチ」 の 犬 を 挨拶する")
    assert "数は性質「挨拶可能」を持っていません" in str(_err(src + "5 を 挨拶する"))


def test_表示可能の実装は文字列を返す():
    check("箱 とは 幅 の 組\n箱 は 表示可能\n  b を 文字列化する とは （b の 幅 を 文字列化する）\n3 の 箱")
    assert "文字列" in str(_err("箱 とは 幅 の 組\n箱 は 表示可能\n  b を 文字列化する とは 1"))


def test_型の条件は呼び出し側まで運ぶ():
    e = _err("x を 測る数にする とは x の 長さ\n「abc」 を 測る数にする\n5 を 測る数にする")
    assert e.line == 3 and "「測る数にする」に渡した値: 「の 長さ」の前は文字列かリスト" in str(e)
    e = _err("a と b を 足す数にする とは a + b\n「a」 と 「b」 を 足す数にする\n真 と 偽 を 足す数にする")
    assert e.line == 3 and "「+」で足せるのは数・文字列・リスト" in str(e)


# --- 第3段階: 型の引数をとる型 ------------------------------------------------

MAYBE = (
    "『たぶん』とは、値の有か無。\n"
    "『たぶん』は連鎖可能。ただし、mをfで連鎖するとは、もしmが値の有ならばfを値に適用する、そうでなければ無。"
    "ただし、xを結果にするとは、xの有。\n"
    "xを半分にするとは、もしx%2==0ならばx/2の有、そうでなければ無。\n"
)
TREE = (
    "木 とは 値 と 左 と 右 の 節 か 葉\n"
    "t を 合計する とは もし t が\n  v と l と r の 節 ならば v + （l を 合計する） + （r を 合計する）\n  葉 ならば 0\n"
)


def test_型の引数はフィールドごとに推論する():
    check(MAYBE + "（1 の 有） と （2 の 有）\n（「a」 の 有）")
    e = _err(MAYBE + "（1 の 有） と （「a」 の 有）")
    assert "数 の たぶん と 文字列 の たぶん" in str(e)


def test_自分自身を中に持つ型():
    check(TREE + "（1 と 葉 と （2 と 葉 と 葉 の 節） の 節） を 合計する")
    e = _err(TREE + "（「a」 と 葉 と 葉 の 節） を 合計する")
    assert "「合計する」の「を」には数 の 木が必要ですが、文字列 の 木が渡されています" in str(e)


def test_いつも同じ型のフィールドは型名だけで表示する():
    e = _err("図形 とは 半径 の 円 か 幅 と 高 の 長方形\n（3 の 円） + 1")
    assert "(図形 と 数)" in str(e)


def test_入れ子の組():
    check("箱 とは 中身 の 組\n（（1 の 箱） の 箱）\n（「a」 の 箱）")


def test_再帰の呼び出しも引数を調べる():
    e = _err("n を 計数する とは もし n < 1 ならば 0 そうでなければ （「a」 を 計数する）")
    assert "「計数する」の「を」には数が必要ですが、文字列が渡されています" in str(e)


# --- 第3段階: 動作 ------------------------------------------------------------

GREET = "挨拶する とは 手順\n  名前 とは 「名前? 」 を 入力した 結果\n  「やあ、」 + 名前 を 表示する\n  名前 の 長さ を 結果にする\n"
TRIPLE = "x を 三倍する とは x * 3\n"


def test_手順の結果の型():
    check(GREET + TRIPLE + "挨拶してから 三倍して 表示する")
    e = _err(GREET + "x を 感嘆にする とは x + 「!」\n挨拶してから 感嘆にする")
    assert "「感嘆にする」の「を」には文字列が必要ですが、数が渡されています" in str(e)


def test_してからの前は動作():
    assert "「してから」の前の値(数)は動作ではありません" in str(_err("1 を 加算してから 表示する"))
    assert "「三倍する」の「を」には数が必要ですが、文字列が渡されています" in str(_err(TRIPLE + "入力してから 三倍する"))
    check(TRIPLE + "入力してから 数値にして 三倍して 表示する")


def test_手順の途中の文は動作():
    assert "手順の途中の文の値(数)は動作ではありません" in str(_err("手順（1+1。「a」を表示する）。"))


def test_した結果():
    e = _err("手順（xとは、「? 」を入力した結果。x*2を表示する）。")
    assert "「*」の左には数が必要ですが、文字列になっています" in str(e)
    check("手順（xとは、「? 」を入力した結果を数値にする。x*2を表示する）。")
    assert "手順の文の中で使ってください" in str(_err("x とは 入力した 結果\nx"))


def test_の結果は写像():
    check("（入力する） の 結果 を 数値にしてから 表示する")
    assert "「三倍する」の「を」には数が必要ですが、文字列が渡されています" in str(_err(TRIPLE + "（入力する） の 結果 を 三倍する"))
    check(TRIPLE + "（1 と 2） の 結果 を 三倍する")


def test_動作で計算するとヒント():
    assert "「+」の左が動作(文字列 の 動作)です" in str(_err("（入力する） + 1"))


def test_リストの連鎖():
    check("（1 と 2） を （n を 受け取って n と n を 返すこと） で 連鎖する")
    e = _err("（1 と 2） を （n を 受け取って n を 返すこと） で 連鎖する")
    assert "リストを連鎖するときは、続きもリストを返す必要があります" in str(e)


def test_実行するは動作のリスト():
    check("（1 と 2） の それぞれ を 表示して 実行する")
    assert "（甲 の 動作） の リストが必要" in str(_err("（1 と 2） を 実行する"))


def test_自分の型の連鎖():
    src = "手順（aとは、{}を半分にした結果。bとは、aを半分にした結果。{}を結果にする）。"
    check(MAYBE + src.format(8, "a+b"))
    assert "「+」の両側の型が違います(数 と 文字列)" in str(_err(MAYBE + src.format(8, "a+「x」")))
    check(MAYBE + "xを倍化するとは、x*2。（8を半分にする）の結果を倍化する。")


def test_自分の型の写像():
    box = "箱 とは 中身 の 組\n箱 は 写像可能\n  b を f で 写像する とは （f を （b の 中身） に 適用する） の 箱\n" + "x を 倍化する とは x * 2\n"
    check(box + "（（3 の 箱） を 倍化すること で 写像する） の 中身 + 1")
    check(box + "（3 の 箱） の 結果 を 倍化する")
    assert "「写像する」の「で」の関数は数を受け取りますが、文字列が渡されます" in str(
        _err(box + "（「a」 の 箱） を 倍化すること で 写像する"))
    assert "数 の 箱は動作ではありません" in str(_err(box + "手順（xとは、（3の箱）を写像用にした結果。xを結果にする）。\nbを写像用にするとは、b。"))


def test_写像できない値():
    assert "数は性質「写像可能」を持っていません" in str(_err("x を 倍化する とは x * 2\n3 を 倍化すること で 写像する"))


def test_多相な手順():
    check("m を 恒等にする とは m\nm を 再包装する とは 手順\n  x とは m を 恒等にした 結果\n  x を 結果にする\n"
          "（1 と 2） を 再包装する\n（入力する） を 再包装する")


# --- 第4段階: 型の宣言と、実行の前の検査 ----------------------------------------

FACT = "n を 階乗する とは もし n < 1 ならば 1 そうでなければ n * （n - 1 を 階乗する）\n"


def test_関数の型の宣言():
    check("数 を 階乗する は 数\n" + FACT + "5 を 階乗する")
    check("数を階乗するは、数。nを階乗するとは、もしn<1ならば1、そうでなければn*（n-1を階乗する）。")
    e = _err("数 を 階乗する は 数\n" + FACT + "「a」 を 階乗する")
    assert "「階乗する」の「を」には数が必要ですが、文字列が渡されています" in str(e)
    assert "文字列になっています" in str(_err("数 を 階乗する は 文字列\n" + FACT))


def test_値の型の宣言():
    check("税率 は 数\n税率 とは 0.1")
    e = _err("税率 は 文字列\n税率 とは 0.1")
    assert "「税率」は文字列と宣言されていますが、数になっています" in str(e)


def test_宣言の型の書き方():
    check("数 の リスト を 合計する は 数\nxs を 合計する とは xs を 加算する")
    check("数 が 偶数である は 真偽\nn が 偶数である とは n % 2 が 0")
    check("（数 を 受け取って 数 を 返すこと） を 二回する は 数\n"
          "f を 二回する とは f を （f を 3 に 適用する） に 適用する\nx を 三倍する とは x * 3\n三倍すること を 二回する")
    check("挨拶する は 数 の 動作\n挨拶する とは 手順\n  名前 とは 「名前? 」 を 入力した 結果\n  名前 の 長さ を 結果にする")
    check("『たぶん』とは、値の有か無。\n数を半分にするは、数の『たぶん』。\n"
          "xを半分にするとは、もしx%2==0ならばx/2の有、そうでなければ無。")
    pt = "点 とは 横 と 縦 の 組\n"
    check(pt + "p は （数 と 数） の 点\np とは 1 と 2 の 点")
    e = _err(pt + "p は （数 と 文字列） の 点\np とは 1 と 2 の 点")
    assert "（数 と 文字列） の 点と宣言されていますが、（数 と 数） の 点になっています" in str(e)


def test_甲乙はどんな型でもよいところ():
    check("甲 を 恒等にする は 甲\nx を 恒等にする とは x\n1 を 恒等にする\n「a」 を 恒等にする")
    e = _err("甲 を 恒等にする は 甲\nx を 恒等にする とは x + 1")
    assert "「甲」は、定義では数に決まります" in str(e)
    e = _err("甲 を 乙 に 選択する は 甲\na を b に 選択する とは もし 真 ならば a そうでなければ b")
    assert "「甲」と「乙」は、定義では同じ型になります" in str(e)


def test_宣言のまちがい():
    assert "一番外にその定義がありません" in str(_err("数 を 階乗する は 数"))
    assert "助詞(に)が定義の助詞(を)と違います" in str(_err("数 に 階乗する は 数\n" + FACT))
    assert "2回宣言されています" in str(_err("数 を 階乗する は 数\n数 を 階乗する は 数\n" + FACT))
    assert "「整数」という型はありません" in str(_err("数 を 階乗する は 整数\n" + FACT))


def test_宣言は実行では使わない():
    from suru import Interpreter
    assert Interpreter().run_text("数 を 階乗する は 数\n" + FACT + "5 を 階乗する") == ["120"]
    # 「点 は 比較可能」は今までどおり性質の実装
    check("比較可能 という 性質 とは\n  a と b を 比較する\n点 とは 横 と 縦 の 組\n点 は 比較可能\n"
          "  a と b を 比較する とは a の 横 - b の 横")


def test_実行の前に検査する(tmp_path, capsys):
    import suru

    bad = tmp_path / "bad.suru"
    bad.write_text("「やあ」 を 表示する\n1 と 「a」\n", encoding="utf-8")
    assert suru.main(["suru.py", str(bad)]) == 1
    out = capsys.readouterr()
    assert out.out == "" and "リストの要素の型がそろっていません" in out.err  # 何も実行しない
    assert suru.main(["suru.py", "--検査なし", str(bad)]) == 0
    assert capsys.readouterr().out.splitlines() == ["やあ", "（1 と 「a」）"]



# --- ファイルの読み込み -------------------------------------------------------


def test_読み込んだ名前の型(tmp_path):
    (tmp_path / "数学.suru").write_text("円周率 とは 3.14\nx を 二乗する とは x * x\n点 とは 横 と 縦 の 組\n", encoding="utf-8")
    d = str(tmp_path)
    check("「数学」 を 読み込む\n3 を 数学内の二乗する\n（1 と 2 の 点） の 横 + 数学内の円周率", d)
    e = _err_in("「数学」 を 読み込む\n「a」 を 数学内の二乗する", d)
    assert "「数学内の二乗する」の「を」には数が必要ですが、文字列が渡されています" in str(e)


def test_読み込んだファイルの中の型の間違い(tmp_path):
    (tmp_path / "不良.suru").write_text("x とは 1\ny とは x + 「a」\n", encoding="utf-8")
    e = _err_in("「不良」 を 読み込む", str(tmp_path))
    assert e.line == 1 and "「不良.suru」の2行目" in str(e) and "「+」の両側の型が違います" in str(e)


def test_読み込みの例を実行する(capsys):
    import suru

    assert suru.main(["suru.py", str(ROOT / "examples" / "import.suru")]) == 0
    assert capsys.readouterr().out.splitlines() == ["3.14", "9", "（1 と 4 と 9）", "自分の二乗する", "10"]


def _err_in(src: str, base_dir: str) -> SuruError:
    with pytest.raises(SuruError) as info:
        check(src, base_dir)
    return info.value


# --- 標準ライブラリ -----------------------------------------------------------


def test_標準ライブラリの型():
    check("「標準」 を 読み込んで 使う\n（3 と 1） を 整列して 逆順にする\n「ab」 を 逆順にして 大文字にする\n"
          "（（1 と 2） から 1 を 番目取得する） + 1\n「ab」 から 1 を 番目取得して 大文字にする\n"
          "逆順にすること を （1 と 2） に 適用する\n標準内の切捨すること")
    for src, msg in [
        ("（「a」 と 「b」） を 整列する", "「整列する」の「を」には数 の リストが必要ですが、文字列 の リストが渡されています"),
        ("5 を 逆順にする", "「逆順にする」の「を」は文字列かリストです(数になっています)"),
        ("（1 と 2） から 1 を 番目取得して 大文字にする", "「大文字にする」の「を」には文字列が必要ですが、数が渡されています"),
        ("「abc」 が 1 を 含有である", "「含有である」の要素には文字列が必要ですが、数になっています"),
        ("5 が 1 を 含有である", "「含有である」の「が」は文字列かリストです"),
        ("「a」 を 1 で 分割する", "「分割する」の「で」には文字列が必要です"),
        ("（1 と 2） を 「,」 で 結合する", "「結合する」の「を」には文字列 の リストが必要です"),
        ("1 が 2 で 先頭一致である", "「先頭一致である」の「が」には文字列が必要です"),
    ]:
        e = _err("「標準」 を 読み込んで 使う\n" + src)
        assert msg in str(e), (src, str(e))
    assert "「標準内の整列する」の「を」" in str(_err("「標準」 を 読み込む\n（「a」 と 「b」） を 標準内の整列する"))


def test_標準ライブラリそのものが検査を通る():
    check((ROOT / "lib" / "標準.suru").read_text(encoding="utf-8"), str(ROOT / "lib"))
